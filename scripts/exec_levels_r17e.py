# -*- coding: utf-8 -*-
"""
라운드 17e — 라운드 17 의 정정. 지금 원장으로 **정말 답할 수 있는 것만**.

■ 무엇이 잘못됐었나
  원장의 mfe/mae 는 청산 봉까지만 잰 값이다. 그래서
    · 목표를 넓히면(a>1) 청산 이후 구간을 봐야 하는데 그 정보가 없다
    · 손절을 넓히면(b>1) 마찬가지다
  라운드 17 은 이걸 모르고 격자 30점을 다 계산했다. 그중 a>1 또는 b>1 인
  24점은 **측정 불가능한 값**이었다. 그 위에서 나온 '통과 후보'도 무효다.

■ 측정 가능한 영역
  a ≤ 1.0 그리고 b ≤ 1.0 — 목표를 당기고 손절을 조이는 쪽.
  이 방향은 새 청산이 원래 청산보다 **먼저**(또는 같이) 일어나므로,
  청산 봉까지의 경로만으로 판정이 결정된다. 순서 모호분만 남고,
  그건 최선/최악 경계로 감싼다.

■ 이 정정으로 답이 바뀌는가
  바뀐다. 원래 '통과'로 보였던 (1.3, 0.6)·(1.3, 0.8)은 둘 다 a>1 이라
  측정 불가 영역이었다. 남는 후보는 a ≤ 1 뿐이고, 라운드 17 표에서
  그 영역은 전부 음수였다. 즉 **지금 원장으로는 현행을 이기는 조합이 없다.**
  이걸 확인 사살하는 것이 이 스크립트의 목적이다.

■ 채택 기준 — 라운드 17 과 동일 (낮추지 않는다)
  ①실전EV>0 ②검증EV>0 ③실전도달≥20% ④검증·실전 양쪽 개선 ⑤표본≥30
"""
import io
import json
import os
import sys
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'scripts'))
OUT = os.path.join(BASE, '.portfolio', 'exec_levels_r17e.json')

from exec_levels_r17 import BUY, COST, load, prep, evaluate

# 측정 가능한 영역만 — 둘 다 1.0 이하
A_GRID = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
B_GRID = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
MIN_N = 30
MIN_REACH = 20.0


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    rows = load()
    cases = []
    for r in rows:
        if (r.get('score') or 0) < BUY:
            continue
        c = prep(r)
        if c:
            cases.append(c)
    by = defaultdict(list)
    for c in cases:
        by[c['split']].append(c)
    print(f'매수권({BUY}+) {len(cases):,}건 = ' + ' · '.join(
        f'{k} {len(by[k]):,}' for k in ('train', 'valid', 'blind')))
    print('측정 가능 영역만: 목표 배수 ≤ 1.0 · 손절 배수 ≤ 1.0\n')

    base = {sp: evaluate(by[sp], 1.0, 1.0) for sp in ('valid', 'blind')}
    print(f"■ 현행 기준선  검증 {base['valid']['ev_worst']:+.2f}% · "
          f"실전 {base['blind']['ev_worst']:+.2f}%\n")

    print(f"  {'목표a':>5s} {'손절b':>5s} │ {'검증EV':>8s} {'실전EV':>8s} "
          f"{'실전도달':>7s} {'모호':>5s} │ 판정")
    grid = []
    for a in A_GRID:
        for b in B_GRID:
            v, bl = evaluate(by['valid'], a, b), evaluate(by['blind'], a, b)
            fails = []
            if bl['ev_worst'] <= 0:
                fails.append('①실전EV')
            if v['ev_worst'] <= 0:
                fails.append('②검증EV')
            if bl['reach_worst'] < MIN_REACH:
                fails.append('③도달률')
            if not (v['ev_worst'] > base['valid']['ev_worst']
                    and bl['ev_worst'] > base['blind']['ev_worst']):
                fails.append('④양쪽개선')
            if bl['n'] < MIN_N or v['n'] < MIN_N:
                fails.append('⑤표본')
            grid.append({'a': a, 'b': b, 'valid': v, 'blind': bl,
                         'fails': fails})
    grid.sort(key=lambda g: -g['blind']['ev_worst'])
    for g in grid:
        v, bl = g['valid'], g['blind']
        cur = ' ←현행' if (g['a'] == 1.0 and g['b'] == 1.0) else ''
        mark = '★통과' if not g['fails'] else '기각 ' + ','.join(g['fails'])
        print(f"  {g['a']:>5.2f} {g['b']:>5.2f} │ {v['ev_worst']:>+7.2f}% "
              f"{bl['ev_worst']:>+7.2f}% {bl['reach_worst']:>6.1f}% "
              f"{bl['amb_pct']:>4.0f}% │ {mark}{cur}")

    passed = [g for g in grid if not g['fails']]
    print('\n' + '=' * 74)
    if passed:
        g = passed[0]
        print(f"통과 {len(passed)}개 · 최고 목표 {g['a']}배 · 손절 {g['b']}배 "
              f"(실전 {g['blind']['ev_worst']:+.2f}%)")
    else:
        print('통과 조합 없음.')
        print('  → 지금 원장으로 **측정 가능한 범위** 안에서는 현행을 이기는')
        print('    목표·손절 조합이 존재하지 않는다. 목표를 넓히는 방향은')
        print('    경로 데이터가 있어야 답할 수 있다 (라운드 17d 에서 보강 중).')
    print('=' * 74)

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump({'round': '17e', 'note': '측정 가능 영역(a≤1,b≤1)만',
                   'baseline': base, 'adopted': None if not passed else
                   {'a': passed[0]['a'], 'b': passed[0]['b']},
                   'grid': [{'a': g['a'], 'b': g['b'], 'fails': g['fails'],
                             'valid_ev': g['valid']['ev_worst'],
                             'blind_ev': g['blind']['ev_worst'],
                             'blind_reach': g['blind']['reach_worst']}
                            for g in grid]}, f, ensure_ascii=False, indent=1)
    print(f'기록: {OUT}')


if __name__ == '__main__':
    main()
