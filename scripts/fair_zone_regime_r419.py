# -*- coding: utf-8 -*-
"""R419 측정 — 사전등록 `docs/PREREG_R419_FAIR_ZONE_BY_REGIME.md` 그대로 (읽기만 · 원장을 바꾸지 않는다).

    python scripts/fair_zone_regime_r419.py            # 측정 · data/fair_zone_regime_r419.json 에 쓴다
"""
from __future__ import annotations

import json
import os
import random
import sys
from collections import defaultdict

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:                                              # noqa: BLE001
    pass
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)
os.chdir(PROJ)
import artifact_io                                             # noqa: E402
import ledger_view                                             # noqa: E402

COST = 0.41
SCORE_FLOOR = 58
BELOW = ('적정가 이하 (안전마진 미확보)', '안전마진 확보')
REGIMES = ('BULL', 'SIDEWAYS', 'BEAR')
SPLITS = ('train', 'valid', 'blind')
DATE_FLOOR = 30
B = 2000
SEED = 419
OUT = os.path.join(PROJ, 'data', 'fair_zone_regime_r419.json')


def rows():
    p = artifact_io.find('virtual_graded.jsonl')
    keys = ledger_view.scale_mismatch_keys()

    def _it():
        import gzip
        fh = gzip.open(p, 'rt', encoding='utf-8') if str(p).endswith('.gz') else open(p, encoding='utf-8')
        with fh:
            for line in fh:
                try:
                    yield json.loads(line)
                except Exception:                              # noqa: BLE001
                    continue
    return ledger_view.stat_rows(_it(), keys)


def boot_ci(by_date_a, by_date_b=None, b=B, seed=SEED):
    """날짜 군집 부트스트랩 — by_date_a: {날짜: [값]} · b 가 있으면 차이(a 평균 − b 평균) · (점추정, 하한, 상한, 하한(본페로니 3), 상한)."""
    rng = random.Random(seed)
    da = list(by_date_a)
    db = list(by_date_b) if by_date_b is not None else None

    def _mean(dd, src):
        v = [x for d in dd for x in src[d]]
        return sum(v) / len(v) if v else None
    pt_a = _mean(da, by_date_a)
    pt = pt_a if db is None else (None if pt_a is None or _mean(db, by_date_b) is None else pt_a - _mean(db, by_date_b))
    sims = []
    for _ in range(b):
        sa = [rng.choice(da) for _ in da]
        ma = _mean(sa, by_date_a)
        if db is None:
            if ma is not None:
                sims.append(ma)
            continue
        sb = [rng.choice(db) for _ in db]
        mb = _mean(sb, by_date_b)
        if ma is not None and mb is not None:
            sims.append(ma - mb)
    sims.sort()
    if not sims:
        return (pt, None, None, None, None)
    q = lambda p: sims[min(len(sims) - 1, max(0, int(p * len(sims))))]   # noqa: E731
    return (pt, q(0.025), q(0.975), q(0.025 / 3), q(1 - 0.025 / 3))


def main():
    cell = defaultdict(lambda: defaultdict(list))     # (regime, split, group) -> {date: [net]}
    allrows = defaultdict(lambda: defaultdict(list))  # 보조(점수 무관)
    n_none = n_total = 0
    for r in rows():
        n_total += 1
        rg = r.get('regime')
        sp = r.get('split')
        try:
            net = float(r.get('return_pct')) - COST
        except (TypeError, ValueError):
            continue
        if rg not in REGIMES:
            n_none += 1
            continue
        grp = 'below' if r.get('entry_zone') in BELOW else 'rest'
        d = str(r.get('date'))[:10]
        allrows[(rg, sp, grp)][d].append(net)
        try:
            if float(r.get('score')) >= SCORE_FLOOR:
                cell[(rg, sp, grp)][d].append(net)
        except (TypeError, ValueError):
            pass
    import datetime as _dt
    out = dict(prereg='docs/PREREG_R419_FAIR_ZONE_BY_REGIME.md', made=_dt.date.today().isoformat(),
               cost=COST, score_floor=SCORE_FLOOR,
               date_floor=DATE_FLOOR, boot=B, seed=SEED, rows_total=n_total, rows_regime_none=n_none, regimes={})
    for rg in REGIMES:
        R = {'r0': {}, 'r1': {}, 'r2': {}, 'all_rows': {}}
        measurable = True
        for sp in SPLITS:
            a, b = cell[(rg, sp, 'below')], cell[(rg, sp, 'rest')]
            R['r0'][sp] = dict(rows=sum(len(v) for v in a.values()), dates=len(a),
                               rest_rows=sum(len(v) for v in b.values()), rest_dates=len(b))
            if sp in ('valid', 'blind') and len(a) < DATE_FLOOR:
                measurable = False
            aa, bb = allrows[(rg, sp, 'below')], allrows[(rg, sp, 'rest')]
            R['all_rows'][sp] = dict(below_rows=sum(len(v) for v in aa.values()),
                                     below_mean=(sum(x for v in aa.values() for x in v) / max(1, sum(len(v) for v in aa.values()))),
                                     rest_mean=(sum(x for v in bb.values() for x in v) / max(1, sum(len(v) for v in bb.values()))))
        R['measurable'] = measurable
        if measurable:
            for sp in SPLITS:
                a, b = cell[(rg, sp, 'below')], cell[(rg, sp, 'rest')]
                R['r1'][sp] = dict(zip(('mean', 'lo', 'hi', 'lo_bonf', 'hi_bonf'), boot_ci(a)))
                R['r2'][sp] = dict(zip(('diff', 'lo', 'hi', 'lo_bonf', 'hi_bonf'), boot_ci(a, b)))
            r1 = all((R['r1'][sp]['lo'] or -1) > 0 for sp in SPLITS)
            r2 = all((R['r2'][sp]['lo'] or -1) > 0 for sp in SPLITS)
            R['verdict'] = '가' if (r1 and r2) else ('나' if r2 else '다')
        else:
            R['verdict'] = '미측정'
        out['regimes'][rg] = R
        print(f'== {rg} · 측정 가능 {measurable} · 판정 {R["verdict"]}')
        for sp in SPLITS:
            print(f'  {sp}: R0 {R["r0"][sp]}')
            if measurable:
                r1, r2 = R['r1'][sp], R['r2'][sp]
                print(f'      R1 평균 {r1["mean"]:+.3f} [{r1["lo"]:+.3f}, {r1["hi"]:+.3f}] · '
                      f'R2 차이 {r2["diff"]:+.3f} [{r2["lo"]:+.3f}, {r2["hi"]:+.3f}]')
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('썼다', OUT)
    return 0


if __name__ == '__main__':
    sys.exit(main())
