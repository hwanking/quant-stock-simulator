# -*- coding: utf-8 -*-
"""
라운드 55 — 국면 라우팅 측정.

사전등록: docs/PREREG_R55_REGIME_MOE.md (이 파일보다 먼저 저장·커밋됨).
학습 train · 평가 valid 1회 · blind 미사용.

  · 국면: trade_plan.market_state (R52 채택 규칙 재사용 — 새 문턱 없음)
          × 코스피 20일 변동성의 train 중앙값 상/하 (정의적 분할)
  · 프록시 5종: 원장 결정 시점 필드로만 정의 (사전등록 §2)
  · 라우팅: train 각 칸에서 순EV 최고 프록시. 칸 n<200 이면 현행 유지
  · 비교 3종(각 1회): 라우팅 / R54 메타 abstain / 결합
  · 메타 국면 피처 포함/제외는 train 내부(2024-09-01 이후를 내부 검증)
    로만 고른다 — valid 를 만지지 않는다

    C:/Python314/python.exe scripts/regime_moe_lab.py
"""
import io
import json
import math
import os
import sys
import warnings
from collections import defaultdict
from datetime import date

import numpy as np

warnings.filterwarnings('ignore')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
P = os.path.join(PROJ, '.portfolio')

import trade_plan as tp                                       # noqa: E402

THR, COST = 58.0, 0.36
PURGE_FROM = '2025-06-01'
MIN_CELL_N = 200               # 사전등록 §3
INNER_VAL_FROM = '2024-09-01'  # 메타 변형 선택용 train 내부 경계
IDX_CACHE = os.path.join(PROJ, '_probe', 'kospi_daily_cache.json')


def wilson_low(k, n, z=1.96):
    if n == 0:
        return 0.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - m) / d * 100.0


def kospi_series():
    """코스피 일봉 — 캐시 우선. 네트워크 실패 시 캐시라도 쓴다."""
    if os.path.exists(IDX_CACHE):
        with open(IDX_CACHE, encoding='utf-8') as f:
            c = json.load(f)
        return c['dates'], c['closes']
    import bitemporal_engine as be
    r = be.BitemporalEngine().fetch_index_daily('KOSPI', count=3000)
    if r is None:
        raise SystemExit('코스피 일봉을 받지 못했다 — 측정 중단 (지어내지 않는다)')
    dates = [str(x) for x in r[0]]
    closes = [float(x) for x in r[1]]
    with open(IDX_CACHE, 'w', encoding='utf-8') as f:
        json.dump({'dates': dates, 'closes': closes, 'made': '2026-08-09'}, f)
    return dates, closes


def build_states():
    """날짜 → (4상태 코드, 20일 변동성). trade_plan 분류를 그대로 쓴다."""
    dates, closes = kospi_series()
    arr = np.array(closes, dtype=float)
    out = {}
    for i in range(65, len(arr)):
        px = arr[i]
        ma20 = arr[i - 19:i + 1].mean()
        ma60 = arr[i - 59:i + 1].mean()
        ma60p = arr[i - 64:i - 4].mean()
        st = tp.market_state(px, ma20, ma60, ma60p)
        ret = np.diff(arr[i - 20:i + 1]) / arr[i - 20:i]
        # 네이버 지수 날짜는 'YYYYMMDD' — 원장('YYYY-MM-DD')에 맞춘다
        d8 = dates[i][:10].replace('.', '-').replace('-', '')[:8]
        key = f'{d8[:4]}-{d8[4:6]}-{d8[6:8]}' if len(d8) == 8 else dates[i][:10]
        out[key] = (st.get('code'), float(np.std(ret)))
    return out


PROXIES = (
    ('눌림', lambda r: bool(r.get('m10_above'))
     and (r.get('range_pos') or 100) <= 50),
    ('돌파', lambda r: (r.get('range_pos') or 0) >= 80),
    ('평균회귀', lambda r: (r.get('bb_pos') or 100) <= 20),
    ('DeMARK매수', lambda r: 'BUY' in str(r.get('demark_state') or '')),
    ('과열회피', lambda r: (r.get('rsi') or 100) < 70),
)


def metrics(sub, base_n, months):
    n = len(sub)
    if n == 0:
        return dict(n=0, cover=0.0, hit=0.0, wilson=0.0, ev=0.0, pf=0.0,
                    monthly=0.0)
    k = sum(1 for r in sub if r['success'])
    net = [float(r['return_pct']) - COST for r in sub]
    pos = sum(x for x in net if x > 0)
    neg = -sum(x for x in net if x < 0)
    return dict(n=n, cover=n / base_n * 100, hit=k / n * 100,
                wilson=wilson_low(k, n), ev=float(np.mean(net)),
                pf=(pos / neg if neg > 0 else float('inf')),
                monthly=n / max(1, months))


def fmt(m):
    return (f"커버 {m['cover']:5.1f}% · 적중 {m['hit']:5.1f}% "
            f"(W {m['wilson']:4.1f}) · 순EV {m['ev']:+.3f} · "
            f"PF {m['pf']:.2f} · 월 {m['monthly']:.0f}건 · n {m['n']:,}")


def main():
    states = build_states()
    print(f'코스피 상태 재구성: {len(states)}일 '
          f'({min(states)} ~ {max(states)})')

    rows = []
    with open(os.path.join(P, 'virtual_graded.jsonl'), encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:                                  # noqa: BLE001
                continue
            if (r.get('split') == 'blind' or r.get('outcome') == 'OPEN'
                    or float(r.get('score') or 0) < THR):
                continue
            rows.append(r)
    joined = dropped = 0
    for r in rows:
        st = states.get(str(r['date'])[:10])
        if st is None:
            r['_cell'] = None
            dropped += 1
        else:
            r['_cell'] = st
            joined += 1
    print(f'매수권 판정완료 {len(rows):,} · 국면 조인 {joined:,} · '
          f'지수 이력 밖(측정 제외) {dropped:,}')
    rows = [r for r in rows if r['_cell'] is not None]

    tr = [r for r in rows if r['split'] == 'train'
          and str(r['date'])[:10] < PURGE_FROM]
    va = [r for r in rows if r['split'] == 'valid']
    months = len({str(r['date'])[:7] for r in va})

    # 변동성 중앙값 — train 날짜 기준 (정의적 분할)
    vmed = float(np.median([r['_cell'][1] for r in tr]))
    for r in rows:
        code, v = r['_cell']
        r['_cell8'] = f"{code}|{'고변동' if v > vmed else '저변동'}"
    print(f'train 변동성 중앙값 {vmed:.4f} → 8칸')

    base = metrics(va, len(va), months)
    print(f'\n기준선(valid 전체): {fmt(base)}')

    # ── train: 칸 × 프록시 성적 → 라우팅 ────────────────────────────
    print('\n■ train 칸별 최고 프록시 (n≥200 칸만 라우팅)')
    cell_rows = defaultdict(list)
    for r in tr:
        cell_rows[r['_cell8']].append(r)
    routing = {}
    for cell in sorted(cell_rows):
        crs = cell_rows[cell]
        best = None
        for name, cond in PROXIES:
            sub = [r for r in crs if cond(r)]
            if len(sub) < MIN_CELL_N:
                continue
            ev = float(np.mean([float(r['return_pct']) - COST for r in sub]))
            if best is None or ev > best[1]:
                best = (name, ev, len(sub))
        if best:
            routing[cell] = best[0]
            print(f'  {cell:22s} → {best[0]:8s} (EV {best[1]:+.3f} · '
                  f'n {best[2]:,})  [칸 전체 {len(crs):,}]')
        else:
            print(f'  {cell:22s} → 현행 유지 (프록시 표본 부족 · '
                  f'칸 전체 {len(crs):,})')

    # ── valid 1회: ① 라우팅 ───────────────────────────────────────
    pmap = dict(PROXIES)
    sel_route = [r for r in va
                 if (r['_cell8'] not in routing)
                 or pmap[routing[r['_cell8']]](r)]
    m_route = metrics(sel_route, len(va), months)
    print(f'\n① 라우팅        {fmt(m_route)}')

    # ── ② R54 메타 abstain — 국면 피처 포함/제외를 train 내부로 선택 ──
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    NUM = ('score', 'rsi', 'bb_pos', 'vol20', 'range_pos', 'demark_bull',
           'demark_bear', 'eff_sample', 'win_rate', 'net_expected')

    def featurize(sub, with_regime, cells):
        med = {k: float(np.nanmedian([float(r[k]) for r in sub
                                      if isinstance(r.get(k), (int, float))]
                                     or [0.0])) for k in NUM}
        X = []
        for r in sub:
            v = []
            for k in NUM:
                x = r.get(k)
                isna = not isinstance(x, (int, float))
                v += [med[k] if isna else float(x), 1.0 if isna else 0.0]
            v.append(1.0 if r.get('m10_above') else 0.0)
            if with_regime:
                v += [1.0 if r['_cell8'] == c else 0.0 for c in cells]
            X.append(v)
        return np.array(X, dtype=float)

    cells = sorted(cell_rows)
    tr_in = [r for r in tr if str(r['date'])[:10] < INNER_VAL_FROM]
    tr_iv = [r for r in tr if str(r['date'])[:10] >= INNER_VAL_FROM]
    pick, pick_ev = None, None
    for wr in (False, True):
        Xa = featurize(tr_in + tr_iv, wr, cells)
        Xi, Xv = Xa[:len(tr_in)], Xa[len(tr_in):]
        yi = np.array([1.0 if r['success'] else 0.0 for r in tr_in])
        sc = StandardScaler().fit(Xi)
        mdl = LogisticRegression(C=1.0, max_iter=2000).fit(sc.transform(Xi),
                                                           yi)
        p = mdl.predict_proba(sc.transform(Xv))[:, 1]
        thr_q = float(np.quantile(p, 0.80))
        sub = [r for r, pi in zip(tr_iv, p) if pi >= thr_q]
        ev = float(np.mean([float(r['return_pct']) - COST for r in sub])) \
            if sub else -9e9
        tag = '국면 포함' if wr else '국면 제외'
        print(f'  (내부) 메타 {tag}: 내부검증 EV {ev:+.3f} (n {len(sub)})')
        if pick_ev is None or ev > pick_ev:
            pick, pick_ev = wr, ev
    print(f'  → 메타 변형 선택: {"국면 포함" if pick else "국면 제외"} '
          f'(train 내부 기준)')

    Xa = featurize(tr + va, pick, cells)
    Xt, Xv = Xa[:len(tr)], Xa[len(tr):]
    yt = np.array([1.0 if r['success'] else 0.0 for r in tr])
    sc = StandardScaler().fit(Xt)
    mdl = LogisticRegression(C=1.0, max_iter=2000).fit(sc.transform(Xt), yt)
    p_va = mdl.predict_proba(sc.transform(Xv))[:, 1]
    thr80 = float(np.quantile(p_va, 0.80))
    sel_meta = [r for r, pi in zip(va, p_va) if pi >= thr80]
    m_meta = metrics(sel_meta, len(va), months)
    print(f'② 메타 abstain  {fmt(m_meta)}')

    # ── ③ 결합: 라우팅 ∩ 메타 ─────────────────────────────────────
    keep = {id(r) for r in sel_route}
    sel_both = [r for r in sel_meta if id(r) in keep]
    m_both = metrics(sel_both, len(va), months)
    print(f'③ 라우팅∩메타   {fmt(m_both)}')

    # ── 게이트 (사전등록 §4) ──────────────────────────────────────
    def gate(m):
        return {
            'EV>기준선 & EV>0': m['ev'] > base['ev'] and m['ev'] > 0,
            '적중 ≥ 기준선-1.0%p': m['hit'] >= base['hit'] - 1.0,
            '커버≥30% & 월≥10': m['cover'] >= 30 and m['monthly'] >= 10,
            'PF > 기준선': m['pf'] > base['pf'],
        }
    print('\n■ 채택 게이트 (사전등록 §4 — 전부 충족해야 함)')
    verdicts = {}
    for name, m in (('라우팅', m_route), ('메타', m_meta), ('결합', m_both)):
        g = gate(m)
        ok = all(g.values())
        verdicts[name] = ok
        marks = ' · '.join(f"{'O' if v else 'X'} {k}" for k, v in g.items())
        print(f'  {name:6s} {"통과" if ok else "기각"} — {marks}')

    out = dict(base=base, routing=m_route, meta=m_meta, both=m_both,
               routing_table=routing, meta_regime_included=bool(pick),
               vol_median=vmed, verdicts=verdicts,
               made='2026-08-09', blind_touched=False)
    with open(os.path.join(P, 'regime_moe_r55.json'), 'w',
              encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1, default=float)
    print('\n저장: .portfolio/regime_moe_r55.json (blind 미접촉)')


if __name__ == '__main__':
    main()
