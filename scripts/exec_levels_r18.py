# -*- coding: utf-8 -*-
"""
라운드 18 — 얼마에 사고, 얼마에 팔고, 어디서 끊을 것인가 (정확 재시뮬).

════════════════════════════════════════════════════════════════════════
사전등록 — 측정 전에 고정한다
════════════════════════════════════════════════════════════════════════

■ 도구
  라운드 17d 가 붙인 20봉 경로로 선도달 순서까지 정확히 재현한다.
  재시뮬레이터는 현행 판정을 99.99% 재현함을 확인했다(verify_exec_sim).
  라운드 17 은 mfe/mae 가 청산 봉까지만이라는 걸 모르고 돌려 무효가 됐다.

■ 세 축을 동시에 본다 (사용자 질문 그대로)
  · 얼마에 사고   진입 할인 d ∈ {0, 1, 2, 3}%
                 기준일 종가보다 d% 아래로 내려오면 산다. 안 내려오면 안 산다.
  · 얼마에 팔고   목표 배수 a ∈ {0.7, 1.0, 1.3, 1.6, 2.0, 2.5}
  · 손실 안 보게  손절 배수 b ∈ {0.6, 0.8, 1.0, 1.25, 1.5}
  총 120 조합.

■ 다중검정을 어떻게 막는가 — 이게 이번 설계의 핵심
  120개를 실전에 다 던지면 우연히 좋아 보이는 게 반드시 나온다.
  그래서 프로토콜을 나눈다:
    1단계  학습+검증만 보고 **딱 하나**를 고른다. 실전은 쳐다보지 않는다.
    2단계  그 하나를 실전에 **한 번만** 건다.
  실전을 여러 번 보면 그건 검증이 아니라 튜닝이다.

■ 1단계 선택 기준 (학습·검증)
  · 검증 기대값이 가장 높은 조합
  · 단, 검증 목표도달률 ≥ 20% (거의 안 팔리는 목표는 제외)
  · 단, 검증 미체결률 ≤ 50% (절반 넘게 못 사면 상품이 아니다)
  · 단, 학습에서도 기대값 > 0 (검증에서만 좋은 건 우연일 수 있다)

■ 2단계 채택 기준 (실전) — 전부 충족
  ① 실전 기대값 > 0
  ② 부트스트랩 95% 하한 > 0        (1만회, 시드 고정)
  ③ 종목 반반 양쪽 다 > 0          (crc32 분할)
  ④ 실전 기간 전·후반 양쪽 다 > 0
  하나라도 미달이면 **기각**. 사후에 기준을 낮추지 않는다.

■ 국면별은 따로
  실전 표본 30건 이상인 칸만 본다: 거친 옆걸음(98) · 거친 상승(94) ·
  차분한 상승(36). 하락 국면은 실전 15건·0건이라 판정하지 않는다 —
  **오늘이 하락 국면이므로, 이 연구는 오늘 상황을 검증하지 못한다.**
════════════════════════════════════════════════════════════════════════
"""
import io
import json
import os
import random
import sys
import zlib
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'scripts'))
OUT = os.path.join(BASE, '.portfolio', 'exec_levels_r18.json')

import exec_sim as X

D_GRID = [0.0, 1.0, 2.0, 3.0]
A_GRID = [0.7, 1.0, 1.3, 1.6, 2.0, 2.5]
B_GRID = [0.6, 0.8, 1.0, 1.25, 1.5]

MIN_REACH = 20.0
MAX_NOENTRY = 50.0
BOOT = 10000
SEED = 20260804
MIN_CELL_N = 30


def boot_lo(vals, n_boot=BOOT, seed=SEED, pct=0.025):
    if not vals:
        return None
    rng = random.Random(seed)
    n = len(vals)
    sims = []
    for _ in range(n_boot):
        sims.append(sum(vals[rng.randrange(n)] for _ in range(n)) / n)
    sims.sort()
    return sims[int(n_boot * pct)]


def half(t):
    return zlib.crc32(str(t).encode()) % 2


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    cases, n_nopath = X.load_cases()
    by = defaultdict(list)
    for c in cases:
        by[c['split']].append(c)
    print(f'매수권({X.BUY}+) 경로 확보 {len(cases):,}건 = ' + ' · '.join(
        f'{k} {len(by[k]):,}' for k in ('train', 'valid', 'blind')))
    print(f'경로 없어 제외 {n_nopath:,}건 · 비용 {X.COST}% · '
          f'격자 {len(D_GRID)}×{len(A_GRID)}×{len(B_GRID)}'
          f'={len(D_GRID) * len(A_GRID) * len(B_GRID)}조합\n')

    base_v = X.ev(by['valid'])
    base_b = X.ev(by['blind'])
    print(f"■ 현행 (진입 0% · 목표 1.0배 · 손절 1.0배)")
    print(f"  검증 n={base_v['traded']:,} 기대값 {base_v['ev']:+.2f}% "
          f"도달 {base_v['reach']:.1f}%")
    print(f"  실전 n={base_b['traded']:,} 기대값 {base_b['ev']:+.2f}% "
          f"도달 {base_b['reach']:.1f}%\n")

    # ── 1단계: 학습+검증만 보고 고른다 ──────────────────────────────
    print('■ 1단계 — 학습·검증만 보고 후보 하나를 고른다 (실전 미열람)')
    cand = []
    for d in D_GRID:
        for a in A_GRID:
            for b in B_GRID:
                v = X.ev(by['valid'], a, b, d)
                t = X.ev(by['train'], a, b, d)
                if not v or not t:
                    continue
                bad = []
                if v['reach'] < MIN_REACH:
                    bad.append('도달률')
                if v['noentry_pct'] > MAX_NOENTRY:
                    bad.append('미체결')
                if t['ev'] <= 0:
                    bad.append('학습EV')
                cand.append({'d': d, 'a': a, 'b': b, 'valid': v, 'train': t,
                             'bad': bad})
    okc = [c for c in cand if not c['bad']]
    okc.sort(key=lambda c: -c['valid']['ev'])
    print(f'  전체 {len(cand)}조합 중 1단계 요건 통과 {len(okc)}조합')
    print(f"  {'진입d':>5s} {'목표a':>5s} {'손절b':>5s} │ {'학습EV':>8s} "
          f"{'검증EV':>8s} {'검증도달':>7s} {'미체결':>6s}")
    for c in okc[:10]:
        print(f"  {c['d']:>5.1f} {c['a']:>5.2f} {c['b']:>5.2f} │ "
              f"{c['train']['ev']:>+7.2f}% {c['valid']['ev']:>+7.2f}% "
              f"{c['valid']['reach']:>6.1f}% {c['valid']['noentry_pct']:>5.1f}%")

    if not okc:
        print('\n1단계를 통과한 조합이 없다 — 실전을 볼 필요도 없다. 기각.')
        with open(OUT, 'w', encoding='utf-8') as f:
            json.dump({'round': 18, 'stage1_passed': 0, 'adopted': None},
                      f, ensure_ascii=False, indent=1)
        return

    pick = okc[0]
    d, a, b = pick['d'], pick['a'], pick['b']
    print(f"\n  ▶ 고른 조합: 진입 -{d:.0f}% · 목표 {a}배 · 손절 {b}배")
    print(f"    (손익비 {0.70 * a / b:.2f}:1 · 현행 0.70:1)")

    # ── 2단계: 실전에 딱 한 번 ──────────────────────────────────────
    print('\n■ 2단계 — 이 조합 하나만 실전에 건다 (한 번만 본다)')
    bl = by['blind']
    e = X.ev(bl, a, b, d)
    rr = X.rets(bl, a, b, d)
    print(f"  실전 신호 {e['n']:,}건 중 체결 {e['traded']:,}건 "
          f"(미체결 {e['noentry_pct']:.1f}%)")
    print(f"  기대값 {e['ev']:+.2f}%  도달 {e['reach']:.1f}% · "
          f"손절 {e['stop_rate']:.1f}% · 미도달 {e['open_rate']:.1f}%")
    print(f"  신호당 기대값 {e['ev_per_signal']:+.2f}% "
          f"(못 산 건까지 포함하면 이 값이다)")

    lo = boot_lo(rr)
    h1 = [c for c in bl if half(c['ticker']) == 0]
    h2 = [c for c in bl if half(c['ticker']) == 1]
    e1, e2 = X.ev(h1, a, b, d), X.ev(h2, a, b, d)
    sb = sorted(bl, key=lambda c: c['date'])
    f1, f2 = sb[:len(sb) // 2], sb[len(sb) // 2:]
    t1, t2 = X.ev(f1, a, b, d), X.ev(f2, a, b, d)

    c1 = e['ev'] > 0
    c2 = lo is not None and lo > 0
    c3 = bool(e1 and e2 and e1['ev'] > 0 and e2['ev'] > 0)
    c4 = bool(t1 and t2 and t1['ev'] > 0 and t2['ev'] > 0)
    print(f"\n  ① 실전 기대값 > 0            {e['ev']:+.2f}%   "
          f"{'통과' if c1 else '실패'}")
    print(f"  ② 부트스트랩 95% 하한 > 0    {lo:+.2f}%   "
          f"{'통과' if c2 else '실패'}")
    print(f"  ③ 종목 반반 양쪽 > 0         "
          f"{(e1 or {}).get('ev', 0):+.2f}% / {(e2 or {}).get('ev', 0):+.2f}%   "
          f"{'통과' if c3 else '실패'}")
    print(f"  ④ 기간 전·후반 양쪽 > 0      "
          f"{(t1 or {}).get('ev', 0):+.2f}% / {(t2 or {}).get('ev', 0):+.2f}%   "
          f"{'통과' if c4 else '실패'}")
    adopted = c1 and c2 and c3 and c4
    print(f"\n  ▶ 판정: {'채택 가능' if adopted else '기각'}")

    # ── 국면별 — 표본이 되는 칸만 ─────────────────────────────────
    print('\n■ 국면별 (실전 30건 이상인 칸만 판정한다)')
    cells = defaultdict(list)
    for c in bl:
        cells[c['cell6'] or '국면 미상'].append(c)
    print(f"  {'칸':12s} {'실전n':>6s} │ {'현행EV':>8s} {'후보EV':>8s} "
          f"{'도달':>6s} │ 판정")
    cell_out = {}
    for name in sorted(cells, key=lambda x: -len(cells[x])):
        g = cells[name]
        cur = X.ev(g)
        new = X.ev(g, a, b, d)
        judge = ('표본 부족' if len(g) < MIN_CELL_N
                 else '개선' if (new and cur and new['ev'] > cur['ev'])
                 else '악화')
        cell_out[name] = {'n': len(g),
                          'cur_ev': (cur or {}).get('ev'),
                          'new_ev': (new or {}).get('ev'),
                          'judge': judge}
        print(f"  {name:12s} {len(g):>6,} │ "
              f"{(cur or {}).get('ev', 0):>+7.2f}% "
              f"{(new or {}).get('ev', 0):>+7.2f}% "
              f"{(new or {}).get('reach', 0):>5.1f}% │ {judge}")

    print('\n  ※ 오늘은 하락 국면이다. 하락 칸의 실전 표본은 위에 보이는 만큼뿐이고,')
    print('    30건에 못 미치면 이 연구는 오늘 상황을 검증하지 못한다.')

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump({
            'round': 18, 'protocol': '1단계 학습·검증 선택 → 2단계 실전 1회',
            'grids': {'d': D_GRID, 'a': A_GRID, 'b': B_GRID},
            'stage1_passed': len(okc),
            'stage1_top': [{'d': c['d'], 'a': c['a'], 'b': c['b'],
                            'train_ev': c['train']['ev'],
                            'valid_ev': c['valid']['ev'],
                            'valid_reach': c['valid']['reach'],
                            'noentry': c['valid']['noentry_pct']}
                           for c in okc[:10]],
            'pick': {'d': d, 'a': a, 'b': b},
            'blind': e, 'bootstrap_lo': lo,
            'checks': {'ev>0': c1, 'boot_lo>0': c2,
                       'ticker_halves': c3, 'time_halves': c4},
            'adopted': ({'d': d, 'a': a, 'b': b} if adopted else None),
            'baseline': {'valid': base_v, 'blind': base_b},
            'by_cell': cell_out,
        }, f, ensure_ascii=False, indent=1)
    print(f'\n기록: {OUT}')


if __name__ == '__main__':
    main()
