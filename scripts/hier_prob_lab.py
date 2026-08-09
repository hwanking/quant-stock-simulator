# -*- coding: utf-8 -*-
"""
라운드 59 — 계층 혼합 확률 측정.

사전등록: docs/PREREG_R59_HIER_PROB.md (먼저 저장·커밋됨).
  · 층 비율은 **train 에서만** 계산 (누출 금지)
  · m ∈ {10,30,100} 선택은 train 내부(2024-09-01~)로만
  · valid 1회 — Brier·log loss 둘 다 기준선② 대비 개선 **이고**
    보정도 이탈 ≤ 기준선이어야 채택
  · 기준선①=점수대 prior · 기준선②=현행 유사사례 확률(win_rate,
    없으면 ①로 폴백)
blind 미사용.
"""
import glob
import io
import json
import math
import os
import sys
import warnings

import numpy as np

warnings.filterwarnings('ignore')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
P = os.path.join(PROJ, '.portfolio')
INNER_FROM = '2024-09-01'
EPS = 1e-6

import trade_plan as tp                                       # noqa: E402

IDX_CACHE = os.path.join(PROJ, '_probe', 'kospi_daily_cache.json')
BANDS = ((0, 40), (40, 50), (50, 58), (58, 65), (65, 101))


def band_of(s):
    for lo, hi in BANDS:
        if lo <= s < hi:
            return f'{lo}-{hi - 1}'
    return None


def build_states():
    with open(IDX_CACHE, encoding='utf-8') as f:
        c = json.load(f)
    arr = np.array(c['closes'], dtype=float)
    dates = c['dates']
    out = {}
    for i in range(65, len(arr)):
        st = tp.market_state(arr[i], arr[i - 19:i + 1].mean(),
                             arr[i - 59:i + 1].mean(),
                             arr[i - 64:i - 4].mean())
        d8 = dates[i][:10].replace('.', '-').replace('-', '')[:8]
        out[f'{d8[:4]}-{d8[4:6]}-{d8[6:8]}'] = st.get('code')
    return out


def proxies_of(r):
    out = []
    if r.get('m10_above') and (r.get('range_pos') or 100) <= 50:
        out.append('눌림')
    if (r.get('range_pos') or 0) >= 80:
        out.append('돌파')
    if (r.get('bb_pos') or 100) <= 20:
        out.append('평균회귀')
    if 'BUY' in str(r.get('demark_state') or ''):
        out.append('DeMARK매수')
    return out


def cells_of(r, ter):
    """행 하나의 계층 셀 키들 (L5 → 좁은 층 순)."""
    b = r['_band']
    keys = [('L5', b)]
    st = r.get('_st')
    if st:
        keys.append(('L4', f'{b}|{st}'))
        for pxy in proxies_of(r):
            keys.append(('L4b', f'{b}|{st}|{pxy}'))
    v = r.get('vol20')
    if isinstance(v, (int, float)) and ter:
        vb = '저' if v <= ter[0] else ('중' if v <= ter[1] else '고')
        keys.append(('L3', f"{b}|{r.get('market')}|{vb}"))
    sec = r.get('_sector')
    if sec and st:
        keys.append(('L2', f'{b}|{sec}|{st}'))
    return keys


def fit_tables(rows):
    """train 층 통계 {(layer,key): (n, k)} + 변동성 3분위."""
    vols = [float(r['vol20']) for r in rows
            if isinstance(r.get('vol20'), (int, float))]
    ter = (float(np.percentile(vols, 33.3)),
           float(np.percentile(vols, 66.7))) if vols else None
    tab = {}
    for r in rows:
        for lk in cells_of(dict(r, _band=r['_band']), ter):
            a = tab.setdefault(lk, [0, 0])
            a[0] += 1
            a[1] += 1 if r.get('success') else 0
    return tab, ter


def predict(r, tab, ter, m):
    """L5 → 좁은 층 순으로 Beta-Binomial 축소 갱신."""
    p = None
    for lk in cells_of(r, ter):
        a = tab.get(lk)
        if not a or a[0] == 0:
            continue
        if p is None:
            p = a[1] / a[0]                   # L5 prior
        else:
            p = (a[1] + m * p) / (a[0] + m)
    return p


def score(preds, ys, name):
    p = np.clip(np.array(preds, dtype=float), EPS, 1 - EPS)
    y = np.array(ys, dtype=float)
    brier = float(np.mean((p - y) ** 2))
    ll = float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))
    # 10분위 보정도 — 각 분위의 |평균확률 − 실측| 최대
    order = np.argsort(p)
    dev = 0.0
    for c in np.array_split(order, 10):
        if len(c):
            dev = max(dev, abs(float(p[c].mean()) - float(y[c].mean())))
    # 변별력 — 상·하위 10분위 실측 차
    top, bot = order[-len(order) // 10:], order[:len(order) // 10]
    spread = float(y[top].mean() - y[bot].mean()) * 100
    print(f'  {name:22s} Brier {brier:.4f} · logloss {ll:.4f} · '
          f'보정이탈 {dev * 100:.1f}%p · 상하위10분위차 {spread:+.1f}%p')
    return dict(brier=brier, logloss=ll, calib_dev=dev * 100, spread=spread)


def main():
    states = build_states()
    patch = {}
    for path in sorted(glob.glob(os.path.join(P, 'subscore_patch*.jsonl'))):
        with open(path, encoding='utf-8') as f:
            for ln in f:
                try:
                    q = json.loads(ln)
                    patch[(q['ticker'], q['date'])] = q.get('sector')
                except Exception:                              # noqa: BLE001
                    continue
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
            if r.get('split') == 'blind' or r.get('outcome') == 'OPEN':
                continue
            b = band_of(float(r.get('score') or 0))
            if not b:
                continue
            d = str(r['date'])[:10]
            r['_band'] = b
            r['_st'] = states.get(d)
            r['_sector'] = patch.get((str(r['ticker']), d))
            rows.append(r)
    tr = [r for r in rows if r['split'] == 'train']
    va = [r for r in rows if r['split'] == 'valid']
    tr_in = [r for r in tr if str(r['date'])[:10] < INNER_FROM]
    tr_iv = [r for r in tr if str(r['date'])[:10] >= INNER_FROM]
    print(f'train {len(tr):,} (내부적합 {len(tr_in):,} · 내부검증 '
          f'{len(tr_iv):,}) · valid {len(va):,}')

    # m 선택 — train 내부만
    tab_in, ter_in = fit_tables(tr_in)
    print('\n■ m 선택 (train 내부검증 · Brier)')
    best_m, best_b = None, None
    for m in (10, 30, 100):
        preds = [predict(r, tab_in, ter_in, m) for r in tr_iv]
        ys = [1.0 if r.get('success') else 0.0 for r in tr_iv]
        keep = [(p, y) for p, y in zip(preds, ys) if p is not None]
        s = score([p for p, _ in keep], [y for _, y in keep], f'm={m}')
        if best_b is None or s['brier'] < best_b:
            best_m, best_b = m, s['brier']
    print(f'  → m = {best_m}')

    # valid 1회 — 층은 train 전체로 재적합
    tab, ter = fit_tables(tr)
    ys = [1.0 if r.get('success') else 0.0 for r in va]
    p_hier = [predict(r, tab, ter, best_m) for r in va]
    # 기준선① 점수대 prior
    l5 = {}
    for r in tr:
        a = l5.setdefault(r['_band'], [0, 0])
        a[0] += 1
        a[1] += 1 if r.get('success') else 0
    p_b1 = [(l5.get(r['_band'], [1, 0])[1] / max(1, l5.get(r['_band'],
                                                           [1, 0])[0]))
            for r in va]
    # 기준선② 현행 유사사례 확률 (win_rate, 없으면 ①)
    p_b2 = []
    for r, pb in zip(va, p_b1):
        w = r.get('win_rate')
        p_b2.append(float(w) / 100 if isinstance(w, (int, float)) else pb)

    print('\n■ valid 1회')
    s1 = score(p_b1, ys, '기준선① 점수대 prior')
    s2 = score(p_b2, ys, '기준선② 유사사례 확률')
    keep = [(p, y, i) for i, (p, y) in enumerate(zip(p_hier, ys))
            if p is not None]
    sh = score([p for p, _, _ in keep], [y for _, y, _ in keep], '계층 혼합')

    # 부분집합 — 유사사례 확률이 **있는** 행에서도 혼합이 이기는가.
    # 여기서 지면 채택 범위를 '미산출 채움'으로 좁힌다 (있는 값 존중).
    idx_w = [i for i, r in enumerate(va)
             if isinstance(r.get('win_rate'), (int, float))
             and p_hier[i] is not None]
    if idx_w:
        print(f'\n■ 부분집합 — 유사사례 확률 보유 행 {len(idx_w):,}건')
        score([p_b2[i] for i in idx_w], [ys[i] for i in idx_w],
              '  유사사례 확률')
        score([p_hier[i] for i in idx_w], [ys[i] for i in idx_w],
              '  계층 혼합')

    gates = {
        'Brier < 기준선②': sh['brier'] < s2['brier'],
        'logloss < 기준선②': sh['logloss'] < s2['logloss'],
        '보정이탈 ≤ 기준선②': sh['calib_dev'] <= s2['calib_dev'],
    }
    print('\n■ 채택 게이트 (사전등록 §2)')
    ok = True
    for k, v in gates.items():
        ok &= v
        print(f"  [{'통과' if v else '미달'}] {k}")
    print(f"\n판정: {'전부 통과 — 표시 채택 자격' if ok else '기각 — 현행 유지'}")

    with open(os.path.join(P, 'hier_prob_r59.json'), 'w',
              encoding='utf-8') as f:
        json.dump(dict(m=best_m, base1=s1, base2=s2, hier=sh,
                       gates={k: bool(v) for k, v in gates.items()},
                       gate_pass=bool(ok), made='2026-08-09',
                       blind_touched=False),
                  f, ensure_ascii=False, indent=1)
    print('저장: .portfolio/hier_prob_r59.json (blind 미접촉)')


if __name__ == '__main__':
    main()
