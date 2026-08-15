# -*- coding: utf-8 -*-
"""
라운드 63 — 적정가 프리미엄 감사 (Valuation–Entry Consistency).

질문(사용자 지적): "적정가가 173,656원인데 왜 211,023원에 사라고 하나?"
→ 문구로 덮지 말고 **적정가보다 비싸게 산 과거가 실제로 어땠는지** 잰다.

원장에 이미 `entry_zone`(진입 위치 판정)이 기록돼 있어 프리미엄 구간을
그대로 쓸 수 있다 — 새 정의를 만들지 않는다. 경로 데이터(21봉)로
MFE/MAE/도달률까지 같이 낸다.

⚠️ 이것은 기술 통계다. 여기서 게이트를 채택하지 않는다 — 결과에 따라
사전등록(R64)으로 간다.
"""
import glob
import io
import json
import math
import os
import sys

import numpy as np

try:                       # 라운드 103 — 객체를 갈아끼우지 않는다
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:          # noqa: BLE001
    pass
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(PROJ, '.portfolio')
H, COST = 20, 0.36

#: 원장 entry_zone 값 → 프리미엄 구간 (낮은 프리미엄 → 높은 순)
ZONE_ORDER = ['안전마진 확보', '적정가 이하 (안전마진 미확보)',
              '적정가 소폭 초과', '적정가 초과 (추격매수 경고)',
              '적정가 크게 초과 (추격매수 위험)', '판정 불가']


def wilson_low(k, n, z=1.96):
    if n == 0:
        return 0.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - m) / d * 100.0


def main():
    paths = {}
    for path in sorted(glob.glob(os.path.join(P, 'bar_paths_s*.jsonl'))):
        with open(path, encoding='utf-8') as f:
            for ln in f:
                try:
                    r = json.loads(ln)
                    paths[(r['ticker'], r['date'])] = r
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
            if (r.get('split') == 'blind' or r.get('outcome') == 'OPEN'
                    or float(r.get('score') or 0) < 58.0):
                continue
            p = paths.get((str(r['ticker']), str(r['date'])[:10]))
            if p and p.get('n_bars', 0) >= H:
                bars = p['bars'][:H]
                r['_hi'] = [b[1] for b in bars]
                r['_lo'] = [b[2] for b in bars]
                r['_cl'] = [b[3] for b in bars]
            rows.append(r)
    print(f'개발 매수권 판정완료 {len(rows):,}건 '
          f'(경로 결합 {sum(1 for r in rows if "_hi" in r):,})\n')

    print(f"{'진입 위치 (적정가 대비)':32s}{'n':>7} {'적중':>6} {'W하한':>6} "
          f"{'순EV':>8} {'PF':>6} {'MFE중앙':>7} {'MAE중앙':>7}")
    print('-' * 92)
    out = {}
    for z in ZONE_ORDER:
        sub = [r for r in rows if str(r.get('entry_zone') or '') == z]
        if not sub:
            continue
        n = len(sub)
        k = sum(1 for r in sub if r.get('success'))
        net = np.array([float(r['return_pct']) - COST for r in sub])
        pos = float(net[net > 0].sum())
        neg = float(-net[net < 0].sum())
        withp = [r for r in sub if '_hi' in r]
        mfe = (np.median([max(r['_hi']) for r in withp]) if withp else
               float('nan'))
        mae = (np.median([min(r['_lo']) for r in withp]) if withp else
               float('nan'))
        out[z] = dict(n=n, hit=round(k / n * 100, 1),
                      wilson=round(wilson_low(k, n), 1),
                      ev=round(float(net.mean()), 3),
                      pf=(round(pos / neg, 2) if neg > 0 else None),
                      mfe=round(float(mfe), 2) if withp else None,
                      mae=round(float(mae), 2) if withp else None)
        print(f"{z:32s}{n:>7,} {k / n * 100:>5.1f}% "
              f"{wilson_low(k, n):>5.1f}% {net.mean():>+8.3f} "
              f"{(pos / neg if neg > 0 else 0):>6.2f} "
              f"{(mfe if withp else 0):>+6.2f}% {(mae if withp else 0):>+6.2f}%")

    # 국면별 — 프리미엄이 국면에 따라 다른가
    print('\n■ "적정가 크게 초과"만 국면별로')
    over = [r for r in rows
            if '크게 초과' in str(r.get('entry_zone') or '')]
    for rg in ('BULL', 'SIDEWAYS', 'BEAR', 'None'):
        sub = [r for r in over if str(r.get('regime')) == rg]
        if len(sub) < 30:
            continue
        k = sum(1 for r in sub if r.get('success'))
        net = np.mean([float(r['return_pct']) - COST for r in sub])
        print(f"  {rg:10s} n {len(sub):>5,} · 적중 {k / len(sub) * 100:5.1f}% "
              f"· 순EV {net:+.3f}")

    dst = os.path.join(PROJ, 'data', 'valuation_premium_audit.json')
    with open(dst, 'w', encoding='utf-8') as f:
        json.dump(dict(made='2026-08-09', basis='개발 구간 매수권(58+) · '
                       '판정완료 · 블라인드 제외 · 비용 0.36%p 차감',
                       note='기술 통계 — 게이트 채택 없음. entry_zone 은 '
                            '원장 기록값을 그대로 썼다(새 정의 없음).',
                       zones=out), f, ensure_ascii=False, indent=1)
    print(f'\n저장: {dst}')


if __name__ == '__main__':
    main()
