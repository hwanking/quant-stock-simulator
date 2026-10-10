# -*- coding: utf-8 -*-
"""라운드 481 — 점수대 적중률(기대값 조건의 p)이 '운영 스캐너가 고를 수 있는 자산'과 같은 모집단에서 나왔나 (상태표 #80 · 측정 전용).

    python scripts/band_population_r481.py

운영 표(calibration.json bands)는 원장 판정 완료 행 전부(세 구간 · 자산 전부)로 센다. 개장 전 후보는 스캐너가 고르고 스캐너는
ETF 를 뺀다(R164·R270). 자산 갈래별·구간별로 점수대 적중률을 센다 — 통계 행(오염 뺌 · R390)으로 · 판정 완료만(R424). 읽기만 · 쓰지 않는다.
"""
from __future__ import annotations

import collections
import os
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)
_SCRIPTS = os.path.join(PROJ, 'scripts')
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)


def rate(rows):
    """판정 완료 행의 적중률(%)과 건수 — 미결은 분모에서 뺀다(`ledger_view.decided_hit` 한 곳)."""
    import ledger_view as LV
    h = [LV.decided_hit(r) for r in rows]
    h = [x for x in h if x is not None]
    return (sum(h) / len(h) * 100 if h else None), len(h)


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:                                          # noqa: BLE001
        pass
    import artifact_io
    import ledger_view as LV
    import ev_gate_past_sim_r480 as S
    raw = S.load_rows()
    print('원장', len(raw), '· asset_type', dict(collections.Counter(str(r.get('asset_type')) for r in raw)))
    stat = list(LV.stat_rows(raw, keys=LV.scale_mismatch_keys()))
    cal = artifact_io.load_json('calibration.json') or {}
    ops = {(b['lo'], b['hi']): (b.get('hit_rate'), b.get('n')) for b in cal.get('bands') or []}
    for lo, hi in S.band_edges():
        if lo < 50:
            continue
        band = [r for r in stat if S._num(r.get('score')) is not None and lo <= float(r['score']) <= hi]
        op = ops.get((lo, hi))
        lines = [f'{lo}~{hi}점 · 운영 표 {op[0]:.2f}% (n {op[1]:,})' if op and op[0] is not None else f'{lo}~{hi}점']
        for at in sorted({str(r.get('asset_type')) for r in band}):
            for sp in ('all', 'train', 'valid', 'blind'):
                p, n = rate([r for r in band if str(r.get('asset_type')) == at and (sp == 'all' or r.get('split') == sp)])
                if n:
                    lines.append(f'  {at:7s} {sp:5s} {p:.2f}% (n {n:,})')
        p, n = rate(band)
        lines.append(f'  전체    all   {p:.2f}% (n {n:,})' if n else '  전체 없음')
        print('\n'.join(lines))
    return 0


if __name__ == '__main__':
    sys.exit(main())
