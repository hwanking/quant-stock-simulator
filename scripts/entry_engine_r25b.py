# -*- coding: utf-8 -*-
"""
라운드 25b — 진입 할인이 '방향'으로 유효한가. 한 점이 아니라 계열을 본다.

════════════════════════════════════════════════════════════════════════
■ 라운드 25 에서 본 것
  1등(변동성 2배)이 학습·검증·실전 **세 구간 모두** 현행을 이겼고 실전
  신호당 기대값이 처음으로 양수(+0.17%)가 됐다. 부트스트랩 하한도
  −1.43% → −0.59% 로 좋아졌다. 그런데 **종목 반반**에서 갈렸다
  (+0.58 / −0.27) — 사전등록 기준으로 기각했다.

  다만 표를 보면 **할인 계열 전체**가 현행보다 낫다:
    변동성 1배 +0.50 · 1.5배 +0.80 · 2배 +0.82 · 3배 +0.38 (검증 신호당)
    지정가 -2% +0.44 · -3% +0.49 · -5% +0.56 · -7% +0.64
  한 점이 튄 게 아니라 **방향이 일관**하다. 첨탑이 아니라 고원이다.

■ 그래서 이번엔 계열을 검정한다 (새 사전등록)
  후보: 1단계를 통과한 엔진 전부.
  각각에 대해 실전에서 아래를 **모두** 본다.
    ① 신호당 기대값 > 현행
    ② 부트스트랩 95% 하한 > 현행 하한
    ③ 종목 반반 **양쪽 다** 현행보다 개선
    ④ 실전 기간 전·후반 **양쪽 다** 현행보다 개선
    ⑤ 체결률 ≥ 50%
  ⑥ 고원 조건: **네 가지를 다 통과한 엔진이 2개 이상**이어야 채택한다.
     하나만 통과하면 그건 여전히 우연일 수 있다.

■ 채택 시 운영 반영 방식
  가장 보수적인(체결률이 높고 대기일이 짧은) 통과 엔진을 고른다.
  기대값 1등이 아니라 **실행 가능성**이 높은 쪽을 고른다 — 이 연구의 목적이
  '실제로 살 수 있는 가격'이기 때문이다.
════════════════════════════════════════════════════════════════════════
"""
import io
import json
import os
import sys
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'scripts'))
OUT = os.path.join(BASE, '.portfolio', 'entry_engine_r25b.json')

import exec_sim as X
from entry_engine_r25 import (ENGINE_NAMES, MIN_FILL, MAX_WAIT, boot_lo, half,
                              run)

MIN_PASS = 2        # 고원 조건 — 이만큼은 통과해야 우연이 아니다


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    cases, _ = X.load_cases()
    by = defaultdict(list)
    for c in cases:
        by[c['split']].append(c)
    bl = by['blind']
    print(f"실전 {len(bl)}건 · 후보 {len(ENGINE_NAMES)}개\n")

    base = run(bl, '현재가 즉시')
    base_lo = boot_lo(base['rets'], base['n'])
    h1 = [c for c in bl if half(c['ticker']) == 0]
    h2 = [c for c in bl if half(c['ticker']) == 1]
    sb = sorted(bl, key=lambda c: c['date'])
    f1, f2 = sb[:len(sb) // 2], sb[len(sb) // 2:]
    b_h1, b_h2 = run(h1, '현재가 즉시'), run(h2, '현재가 즉시')
    b_f1, b_f2 = run(f1, '현재가 즉시'), run(f2, '현재가 즉시')
    print(f"■ 현행 실전 기준선  신호당 {base['ev_signal']:+.2f}% · "
          f"부트하한 {base_lo:+.2f}% · 종목반반 "
          f"{b_h1['ev_signal']:+.2f}/{b_h2['ev_signal']:+.2f} · "
          f"기간반반 {b_f1['ev_signal']:+.2f}/{b_f2['ev_signal']:+.2f}\n")

    # 1단계를 통과했던 엔진만 다시 본다 (학습·검증에서 이미 걸러진 것들)
    tr, va = by['train'], by['valid']
    b_tr, b_va = run(tr, '현재가 즉시'), run(va, '현재가 즉시')
    stage1 = []
    for nm in ENGINE_NAMES:
        t_, v_ = run(tr, nm), run(va, nm)
        if not t_ or not v_:
            continue
        if (t_['ev_signal'] > b_tr['ev_signal']
                and v_['ev_signal'] > b_va['ev_signal']
                and v_['fill_pct'] >= MIN_FILL
                and v_['wait_days'] <= MAX_WAIT):
            stage1.append(nm)
    print(f"1단계 통과 {len(stage1)}개: {', '.join(stage1)}\n")

    print(f"  {'엔진':14s} │ {'신호당':>8s} {'부트하한':>8s} "
          f"{'종목반반':>15s} {'기간반반':>15s} {'체결':>6s} │ 판정")
    passed = []
    rows = []
    for nm in stage1:
        d = run(bl, nm)
        if not d:
            continue
        lo = boot_lo(d['rets'], d['n'])
        a1, a2 = run(h1, nm), run(h2, nm)
        g1, g2 = run(f1, nm), run(f2, nm)
        c1 = d['ev_signal'] > base['ev_signal']
        c2 = lo is not None and base_lo is not None and lo > base_lo
        c3 = bool(a1 and a2 and a1['ev_signal'] > b_h1['ev_signal']
                  and a2['ev_signal'] > b_h2['ev_signal'])
        c4 = bool(g1 and g2 and g1['ev_signal'] > b_f1['ev_signal']
                  and g2['ev_signal'] > b_f2['ev_signal'])
        c5 = d['fill_pct'] >= MIN_FILL
        okk = c1 and c2 and c3 and c4 and c5
        if okk:
            passed.append(nm)
        rows.append({'name': nm, 'ev_signal': d['ev_signal'], 'boot_lo': lo,
                     'fill': d['fill_pct'], 'wait': d['wait_days'],
                     'reach': d['reach'],
                     'halves': [(a1 or {}).get('ev_signal'),
                                (a2 or {}).get('ev_signal')],
                     'times': [(g1 or {}).get('ev_signal'),
                               (g2 or {}).get('ev_signal')],
                     'checks': [c1, c2, c3, c4, c5], 'pass': okk})
        print(f"  {nm:14s} │ {d['ev_signal']:>+7.2f}% {lo:>+7.2f}% "
              f"{(a1 or {}).get('ev_signal', 0):>+6.2f}/"
              f"{(a2 or {}).get('ev_signal', 0):>+6.2f}   "
              f"{(g1 or {}).get('ev_signal', 0):>+6.2f}/"
              f"{(g2 or {}).get('ev_signal', 0):>+6.2f}   "
              f"{d['fill_pct']:>5.1f}% │ "
              f"{'★통과' if okk else '기각 ' + ''.join(
                  m for m, c in zip('①②③④⑤', [c1, c2, c3, c4, c5]) if not c)}")

    print('\n' + '=' * 78)
    adopted = None
    if len(passed) >= MIN_PASS:
        # 기대값 1등이 아니라 **실행 가능성**이 높은 쪽을 고른다
        cand = [r for r in rows if r['pass']]
        cand.sort(key=lambda r: (-r['fill'], r['wait']))
        adopted = cand[0]['name']
        print(f'통과 {len(passed)}개 — 고원 조건({MIN_PASS}개 이상) 충족')
        print(f'  통과 목록: {", ".join(passed)}')
        print(f'  ▶ 채택: **{adopted}** '
              f"(체결 {cand[0]['fill']:.1f}% · 대기 {cand[0]['wait']:.1f}일 · "
              f"신호당 {cand[0]['ev_signal']:+.2f}%)")
        print('  기대값 1등이 아니라 체결률이 높은 쪽을 골랐다 — 이 연구의')
        print('  목적은 "실제로 살 수 있는 가격"이기 때문이다.')
    elif passed:
        print(f'통과 {len(passed)}개 — 고원 조건({MIN_PASS}개) 미달로 기각.')
        print(f'  ({", ".join(passed)} 하나만 통과 — 우연일 수 있다)')
    else:
        print('전 항목 통과 엔진 없음 — 채택하지 않는다.')
    print('=' * 78)

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump({'round': '25b', 'min_pass': MIN_PASS,
                   'baseline': {'ev_signal': base['ev_signal'],
                                'boot_lo': base_lo,
                                'halves': [b_h1['ev_signal'], b_h2['ev_signal']],
                                'times': [b_f1['ev_signal'], b_f2['ev_signal']]},
                   'stage1': stage1, 'rows': rows,
                   'passed': passed, 'adopted': adopted},
                  f, ensure_ascii=False, indent=1)
    print(f'기록: {OUT}')


if __name__ == '__main__':
    main()
