# -*- coding: utf-8 -*-
"""라운드 480 — "몇 번 추천해 봤어? 예전 걸로 시뮬레이션 할 수 있잖아": 과거 원장에 '비용 차감 기대값 양수'를 대 본다 — 오염을 걷은 판.

    python scripts/ev_gate_past_sim_r480.py      # data/ev_gate_past_sim_r480.json 에 쓴다 (GAEUM_NO_LOCAL_WRITE 면 안 쓴다)

■ 이것은 측정이다 — 판정이 아니다
  과거 원장(특히 블라인드)은 이미 여러 라운드가 봤다(R468 표준). 그래서 이 수로 게이트를 바꾸지 않는다 — 판정은 사전등록 R475·R478 의
  앞으로의 자료가 한다. 이 산출물은 "과거에 이 조건을 대 봤다면 몇 건이 통과했고 그것이 어떻게 됐나"를 **보이는** 용도다.

■ 라운드 208(같은 물음의 첫 판 · 2026-09-02)과 다른 점 — 그 판에 들어 있던 오염 넷을 걷었다 (결과를 보기 전에 여기 적었다)
  ① 통계 행만 — 진입가 축척이 어긋난 행(첫날에 박힌 지어낸 승패 · R364·R389)과 시장 접미사만 다른 복사본(R390)을 뺀다
     (`ledger_view.stat_rows` 한 곳 · 원장 행은 안 지운다).
  ② 같은 종목 35일 간격 — 이웃 기준일의 20봉 창이 72% 겹친다(R217). 같은 종목은 앞 케이스에서 35일이 지나야 새 사례로 센다
     (`ledger_view.too_close` · 날짜 순 · 58점+ 무리 안에서 · R346 과 같은 방식).
  ③ 확률은 학습 구간에서만 — 운영 게이트의 점수대 확률(`calibration.json` bands)은 **세 구간 전부**로 센다. 그 확률로 과거 검증·블라인드를
     가르면 그 구간의 답을 미리 본 것이다. 점수대 가름은 운영과 같고(파일의 lo·hi) 적중률은 학습 구간의 판정 완료 행으로 다시 센다
     (`ledger_view.decided_hit` · n ≥ 30 인 띠만 · 운영과 같은 조건).
  ④ 비용은 지금 운영 값(`verdict_core.COST_PCT` · 0.41 · R350) — 라운드 208 은 0.36 이었다.
  비교하려고 라운드 208 방식(오염 넷을 안 걷은 판)의 수도 같이 낸다.

■ 셈 (문턱 없음)
  · 게이트: 기대값 = p × 목표폭 + (1 − p) × 손절폭 − 비용 > 0 (중앙 판정의 식 · 폭은 행의 진입가·1차 목표·손절에서 %)
  · 한 케이스의 값: 원장의 실현 수익(return_pct · 먼저 닿은 선 · 20봉 만료면 그날 종가) − 비용
  · 구간마다 통과·막힘의 건수 · 날짜 수 · 평균 · 중앙 · 날짜로 묶은 95% 구간(`proof.cluster_ci` · 시드 480) · 통과 − 막힘 차의 구간
"""
from __future__ import annotations

import io
import json
import os
import statistics
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)
LED = os.path.join(PROJ, '.portfolio', 'virtual_graded.jsonl')
OUT = os.path.join(PROJ, 'data', 'ev_gate_past_sim_r480.json')
SCORE_MIN = 58          # 매수권(이미 채택된 띠 · R2)
SEED = 480
BOOT = 2000
SPLITS = ('train', 'valid', 'blind')


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def load_rows(path=LED):
    out = []
    with io.open(path, encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except ValueError:
                continue
    return out


def band_edges():
    """운영 점수대의 가름(lo·hi) — calibration.json 에서 읽는다(새 띠를 만들지 않는다)."""
    import artifact_io
    cal = artifact_io.load_json('calibration.json') or {}
    return [(int(b['lo']), int(b['hi'])) for b in (cal.get('bands') or []) if b.get('lo') is not None and b.get('hi') is not None]


def band_p(rows, edges, split='train', min_n=30):
    """점수대별 적중률 — 그 구간의 판정 완료 행만(미결은 분모에서 뺀다 · R424) · n < min_n 인 띠는 None."""
    import ledger_view as LV
    out = {}
    for lo, hi in edges:
        h = [LV.decided_hit(r) for r in rows
             if r.get('split') == split and _num(r.get('score')) is not None and lo <= float(r['score']) <= hi]
        h = [x for x in h if x is not None]
        out[(lo, hi)] = (sum(h) / len(h)) if len(h) >= min_n else None
    return out


def p_for(score, ptab):
    for (lo, hi), p in ptab.items():
        if lo <= score <= hi:
            return p
    return None


def gate_ev(row, p, cost):
    px, tg, st = _num(row.get('price')), _num(row.get('target')), _num(row.get('stop'))
    if p is None or not (px and tg and st) or not (st < px < tg):
        return None
    up, dn = (tg / px - 1.0) * 100.0, (st / px - 1.0) * 100.0
    return p * up + (1.0 - p) * dn - cost


def spaced(rows):
    """같은 종목 35일 간격 — 날짜 순으로 앞 케이스에서 35일이 지난 것만(58점+ 무리 안에서)."""
    import ledger_view as LV
    kept, last = [], {}
    for r in sorted(rows, key=lambda x: (str(x.get('date'))[:10], LV.code6(x.get('ticker')))):
        c, d = LV.code6(r.get('ticker')), str(r.get('date'))[:10]
        prev = last.get(c)
        if prev and LV.too_close(prev, d):
            continue
        last.setdefault(c, []).append(d)
        last[c].sort()
        kept.append(r)
    return kept


def summarize(rows, ptab, cost, boot=BOOT, seed=SEED):
    """구간마다 통과·막힘 — 건수 · 날짜 · 평균 · 중앙 · 구간 · 차(같은 날짜 뽑기 안의 통과 − 막힘)."""
    import proof
    import random
    out = {}
    for sp in SPLITS:
        cells = {'pass': {}, 'block': {}}
        for r in rows:
            if r.get('split') != sp:
                continue
            sc = _num(r.get('score'))
            ret = _num(r.get('return_pct'))
            if sc is None or ret is None or r.get('outcome') not in ('TARGET', 'STOP', 'OPEN'):
                continue
            ev = gate_ev(r, p_for(sc, ptab), cost)
            if ev is None:
                continue
            cells['pass' if ev > 0 else 'block'].setdefault(str(r.get('date'))[:10], []).append(ret - cost)
        o = {}
        for side, by in cells.items():
            v = [x for xs in by.values() for x in xs]
            o[side] = dict(n=len(v), dates=len(by), mean_net=(sum(v) / len(v) if v else None),
                           median_net=(statistics.median(v) if v else None),
                           ci95=proof.cluster_ci(by, boot, seed) if v else None)
        # 차의 구간 — 날짜를 다시 뽑고 그 안에서 통과 평균 − 막힘 평균
        ds = sorted(set(cells['pass']) | set(cells['block']))
        diff_ci = None
        if o['pass']['n'] and o['block']['n'] and len(ds) >= 2 and boot:
            rng, ms = random.Random(seed), []
            for _ in range(int(boot)):
                ps, bs = [], []
                for d in (rng.choice(ds) for _ in ds):
                    ps += cells['pass'].get(d, [])
                    bs += cells['block'].get(d, [])
                if ps and bs:
                    ms.append(sum(ps) / len(ps) - sum(bs) / len(bs))
            if len(ms) >= 40:
                ms.sort()
                diff_ci = [ms[int(0.025 * len(ms))], ms[int(0.975 * len(ms)) - 1]]
        o['diff'] = ((o['pass']['mean_net'] - o['block']['mean_net'])
                     if o['pass']['mean_net'] is not None and o['block']['mean_net'] is not None else None)
        o['diff_ci'] = diff_ci
        out[sp] = o
    return out


#: 원장 `action_title` 의 매수 쪽 제목 — 2026-10-10 원장 258,330행의 값 여섯 종류를 세어 확인했다(신규 매수 보류 · 조건 확인·관망 ·
#: 비중축소 검토 · 제한적 진입 · 분할매수 검토 · 거래 회피). ⚠️ 첫 판은 화면 문장('사도 됩니다' 등)으로 찾아 0 을 냈다 — 원장 칸의 값이 아니었다.
BUY_TITLES = ('제한적 진입', '분할매수 검토')


def engine_buy_titles(rows, cost):
    """엔진이 매수 쪽 제목을 낸 통계 행 — 구간별 건수와 비용 뺀 평균(엔진 판정이지 중앙 판정의 추천이 아니다)."""
    out = {}
    for sp in SPLITS:
        v = [_num(r.get('return_pct')) for r in rows
             if r.get('split') == sp and str(r.get('action_title') or '') in BUY_TITLES]
        v = [x - cost for x in v if x is not None]
        out[sp] = dict(n=len(v), mean_net=(sum(v) / len(v) if v else None))
    return out


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:                                          # noqa: BLE001
        pass
    import ledger_view as LV
    import verdict_core
    cost = float(verdict_core.COST_PCT)
    raw = load_rows()
    edges = band_edges()
    cnt = {}
    stat = list(LV.stat_rows(raw, keys=LV.scale_mismatch_keys(), counter=cnt))
    pool = [r for r in stat if (_num(r.get('score')) or 0) >= SCORE_MIN]
    sp_rows = spaced(pool)
    ptab_train = band_p(stat, edges, 'train')
    clean = summarize(sp_rows, ptab_train, cost)
    # 라운드 208 방식(오염을 안 걷은 판) — 모든 행 · 간격 없음 · 운영 확률(세 구간 전부) · 같은 비용
    import artifact_io
    cal = artifact_io.load_json('calibration.json') or {}
    ptab_ops = {(int(b['lo']), int(b['hi'])): (float(b['hit_rate']) / 100.0 if b.get('hit_rate') is not None
                                                and (b.get('n') or 0) >= 30 else None)
                for b in (cal.get('bands') or []) if b.get('lo') is not None}
    asr208 = summarize([r for r in raw if (_num(r.get('score')) or 0) >= SCORE_MIN], ptab_ops, cost)
    doc = dict(made=__import__('datetime').datetime.now().isoformat(timespec='seconds'), ledger_rows=len(raw),
               stat_rows=len(stat), dropped=cnt, pool_58=len(pool), spaced_58=len(sp_rows), cost_pct=cost,
               p_train={f'{lo}~{hi}': p for (lo, hi), p in ptab_train.items()},
               p_ops={f'{lo}~{hi}': p for (lo, hi), p in ptab_ops.items()},
               clean=clean, as_r208=asr208, engine_buy_titles=engine_buy_titles(stat, cost), seed=SEED, boot=BOOT,
               note='측정 · 판정 아님 — 과거 원장은 이미 봤다(R468) · 판정은 사전등록 R475·R478 의 앞으로의 자료')
    print(f"원장 {len(raw):,} · 통계 행 {len(stat):,} (뺀 것 {cnt}) · 58점+ {len(pool):,} · 35일 간격 {len(sp_rows):,} · 비용 {cost}")
    print('학습 구간 점수대 확률', {k: (round(v, 4) if v is not None else None) for k, v in doc['p_train'].items()})
    for name, res in (('깨끗한 판', clean), ('라운드 208 방식', asr208)):
        print(f'[{name}]')
        for sp in SPLITS:
            o = res[sp]
            pa, bl = o['pass'], o['block']
            f = lambda x: '—' if x is None else f'{x:+.2f}'                       # noqa: E731
            ci = lambda c: '—' if not c else f'[{c[0]:+.2f}, {c[1]:+.2f}]'       # noqa: E731
            print(f"  {sp}: 통과 {pa['n']:,}건(날짜 {pa['dates']}) 평균 {f(pa['mean_net'])} {ci(pa['ci95'])} 중앙 {f(pa['median_net'])}"
                  f" · 막힘 {bl['n']:,}건 평균 {f(bl['mean_net'])} · 차 {f(o['diff'])} {ci(o['diff_ci'])}")
    print('엔진 판정 제목이 사도 된다 쪽인 통계 행', doc['engine_buy_titles'])
    if not os.environ.get('GAEUM_NO_LOCAL_WRITE'):
        with io.open(OUT, 'w', encoding='utf-8') as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=1)
        print('썼다', OUT)
    return 0


if __name__ == '__main__':
    sys.exit(main())
