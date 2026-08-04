# -*- coding: utf-8 -*-
"""
라운드 21 — 손실을 줄이는 것은 가능한가. (사용자 질문: "손실도 잘 안보게")

════════════════════════════════════════════════════════════════════════
사전등록
════════════════════════════════════════════════════════════════════════
■ 배경
  라운드 17~20 에서 '돈을 버는' 설정은 어느 것도 재현되지 않았다.
  그런데 라운드 20 ⑤ 에서 실전 한 구간만 보고 눈에 띄는 게 있었다:
  손절을 조이면 평균 손실이 -9.5% → -5.2% 로 줄고 최악 손실도 반이 된다.
  기대값은 나빠지지 않았다.

  '더 버는 것'이 아니라 '덜 잃는 것'이라면 가능할 수 있다. 다만 실전
  한 구간에서 본 것이므로 세 구간 전부에서 확인해야 한다.

■ 재는 것
  손절 배수 b ∈ {0.5, 0.6, 0.7, 0.8, 0.9, 1.0} (목표는 현행 유지)
  구간별로 · 기대값 · 손절률 · 평균 손실 · 최악 손실 · 하위 5% 손실

■ 채택 기준 — 이건 '손실 통제' 채택이지 '수익' 채택이 아니다
  ① 평균 손실이 현행보다 작을 것          … 학습·검증·실전 **전부**
  ② 최악 손실이 현행보다 작을 것          … 학습·검증·실전 **전부**
  ③ 기대값이 현행보다 나빠지지 않을 것     … 학습·검증·실전 **전부**
     (같거나 나으면 된다. 손실을 줄이려고 수익을 깎으면 의미가 없다)
  ④ 목표도달률이 현행 대비 5%p 넘게 떨어지지 않을 것
     (손절이 좁으면 흔들려서 털린다 — 그 대가가 너무 크면 안 된다)

■ 무엇을 주장하지 않는가 — 미리 못 박는다
  이게 통과해도 **엔진이 돈을 번다는 뜻이 아니다.** 기대값은 여전히 음수다.
  "같은 신호를 따르되 손실 폭을 줄인다"는 것뿐이다.
  화면에 쓸 때도 그렇게만 쓴다.
════════════════════════════════════════════════════════════════════════
"""
import io
import json
import os
import sys
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'scripts'))
OUT = os.path.join(BASE, '.portfolio', 'loss_control_r21.json')

import exec_sim as X

B_GRID = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
SPLITS = ('train', 'valid', 'blind')
MAX_REACH_DROP = 5.0


def stats(cases, b):
    e = X.ev(cases, sp_mult=b)
    rr = X.rets(cases, sp_mult=b)
    if not e or not rr:
        return None
    losses = sorted(x for x in rr if x < 0)
    n_l = len(losses)
    return {
        'n': e['traded'], 'ev': e['ev'], 'reach': e['reach'],
        'stop_rate': e['stop_rate'],
        'avg_loss': (sum(losses) / n_l) if n_l else 0.0,
        'worst': losses[0] if n_l else 0.0,
        'p5': losses[max(0, int(n_l * 0.05))] if n_l else 0.0,
        'loss_n': n_l,
    }


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    cases, _ = X.load_cases()
    by = defaultdict(list)
    for c in cases:
        by[c['split']].append(c)
    print(f'매수권({X.BUY}+) {len(cases):,}건 = ' + ' · '.join(
        f'{k} {len(by[k]):,}' for k in SPLITS) + '\n')

    tab = {sp: {b: stats(by[sp], b) for b in B_GRID} for sp in SPLITS}

    for sp in SPLITS:
        print(f'■ {sp}')
        print(f"  {'손절배수':>8s} {'기대값':>9s} {'도달':>7s} {'손절률':>7s} "
              f"{'평균손실':>9s} {'하위5%':>9s} {'최악':>9s}")
        for b in B_GRID:
            d = tab[sp][b]
            cur = ' ←현행' if b == 1.0 else ''
            print(f"  {b:>8.2f} {d['ev']:>+8.2f}% {d['reach']:>6.1f}% "
                  f"{d['stop_rate']:>6.1f}% {d['avg_loss']:>+8.2f}% "
                  f"{d['p5']:>+8.2f}% {d['worst']:>+8.2f}%{cur}")
        print()

    print('■ 사전등록 기준 판정 (세 구간 전부 충족해야 통과)')
    print(f"  {'손절배수':>8s} │ {'①평균손실':>10s} {'②최악':>8s} "
          f"{'③기대값':>10s} {'④도달률':>10s} │ 판정")
    passed = []
    for b in B_GRID:
        if b == 1.0:
            continue
        c1 = all(tab[sp][b]['avg_loss'] > tab[sp][1.0]['avg_loss'] for sp in SPLITS)
        c2 = all(tab[sp][b]['worst'] > tab[sp][1.0]['worst'] for sp in SPLITS)
        c3 = all(tab[sp][b]['ev'] >= tab[sp][1.0]['ev'] - 1e-9 for sp in SPLITS)
        c4 = all(tab[sp][b]['reach'] >= tab[sp][1.0]['reach'] - MAX_REACH_DROP
                 for sp in SPLITS)
        okall = c1 and c2 and c3 and c4
        if okall:
            passed.append(b)
        print(f"  {b:>8.2f} │ {'O' if c1 else 'X':>10s} {'O' if c2 else 'X':>8s} "
              f"{'O' if c3 else 'X':>10s} {'O' if c4 else 'X':>10s} │ "
              f"{'★통과' if okall else '기각'}")

    print('\n' + '=' * 74)
    adopted = None
    if passed:
        # 통과한 것 중 평균 손실을 가장 많이 줄이는 쪽
        adopted = min(passed,
                      key=lambda b: sum(tab[sp][b]['avg_loss'] for sp in SPLITS))
        print(f'통과 {len(passed)}개 — 채택 후보: 손절 {adopted}배')
        for sp in SPLITS:
            a, c = tab[sp][adopted], tab[sp][1.0]
            print(f"  {sp:6s} 평균손실 {c['avg_loss']:+.2f}% → {a['avg_loss']:+.2f}% "
                  f"· 최악 {c['worst']:+.2f}% → {a['worst']:+.2f}% "
                  f"· 기대값 {c['ev']:+.2f}% → {a['ev']:+.2f}% "
                  f"· 도달 {c['reach']:.1f}% → {a['reach']:.1f}%")
        print('\n  ※ 기대값은 여전히 음수다. 이건 "덜 잃는" 개선이지')
        print('    "돈을 번다"는 뜻이 아니다. 화면에도 그렇게만 쓴다.')
    else:
        print('세 구간 모두를 만족하는 손절 폭이 없다 — 채택하지 않는다.')
    print('=' * 74)

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump({'round': 21, 'b_grid': B_GRID, 'table': tab,
                   'passed': passed, 'adopted': adopted,
                   'claim': '손실 통제 개선 — 수익성 주장 아님'},
                  f, ensure_ascii=False, indent=1)
    print(f'기록: {OUT}')


if __name__ == '__main__':
    main()
