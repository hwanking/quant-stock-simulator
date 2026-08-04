# -*- coding: utf-8 -*-
"""
라운드 19b — 게이트를 **lift** 로 다시 본다. 원시 기대값은 구간에 오염돼 있다.

■ 라운드 19 에서 본 것
  게이트 20개 전부 학습 기대값이 음수였다. 그런데 검증에서는 여럿이 양수다
  (RSI<60 +0.34%, 데마크 +0.32%, 52주<80 +0.27% …).
  그 값들이 하나같이 '검증 기준선(-0.04%) + 0.3%p' 언저리다.
  → 게이트가 좋은 게 아니라 **검증 구간이 그냥 좋았을** 가능성이 크다.

■ 그래서 lift 로 본다
  lift = (그 게이트를 켰을 때 기대값) − (같은 구간 전체 기대값)
  구간이 좋아서 오른 건 기준선도 같이 오르므로 lift 에서 상쇄된다.
  이건 기준을 낮추는 게 아니라 **올바른 추정량으로 바꾸는** 것이다.

■ 사전등록 — 판정 기준
  1단계  학습 lift > 0 **그리고** 검증 lift > 0 인 게이트만 남긴다.
         (한쪽만 양수면 구간 우연이다. 양쪽 부호가 같아야 신호다.)
         잔존율 ≥ 30% 도 그대로 요구한다.
  2단계  남은 것 중 (학습 lift + 검증 lift)/2 가 가장 큰 하나를 실전에 1회.
  채택   ① 실전 lift > 0  ② 실전 기대값 > 0  ③ 부트스트랩 95% 하한 > 0
         ④ 종목 반반 양쪽 lift > 0  ⑤ 실전 잔존 표본 ≥ 30
  ②를 남겨 둔 이유: lift 가 양수라도 절대값이 음수면 여전히 돈을 잃는다.
  '덜 잃는 것'은 개선이지 수익이 아니다 — 둘을 구분해서 보고한다.
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
OUT = os.path.join(BASE, '.portfolio', 'gate_lift_r19b.json')

import exec_sim as X
from when_not_to_buy_r19 import GATES, boot_lo, half

MIN_KEEP = 30.0
MIN_N = 30


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    cases, _ = X.load_cases()
    by = defaultdict(list)
    for c in cases:
        by[c['split']].append(c)

    base = {sp: X.ev(by[sp]) for sp in ('train', 'valid', 'blind')}
    print(f'매수권({X.BUY}+) {len(cases):,}건')
    print('구간 기준선(게이트 없음): ' + ' · '.join(
        f"{k} {base[k]['ev']:+.2f}%" for k in ('train', 'valid', 'blind')))
    print(f"  → 검증이 학습보다 "
          f"{base['valid']['ev'] - base['train']['ev']:+.2f}%p 좋다. "
          f"이만큼은 게이트의 공이 아니다.\n")

    print('■ 1단계 — 학습·검증 lift (실전 미열람)')
    print(f"  {'게이트':22s} {'학습lift':>9s} {'검증lift':>9s} "
          f"{'평균':>8s} {'잔존':>6s} │ 1단계")
    rows = []
    for name, fn in GATES.items():
        t = X.ev([c for c in by['train'] if fn(c)])
        v = X.ev([c for c in by['valid'] if fn(c)])
        if not t or not v:
            continue
        keep = len([c for c in by['valid'] if fn(c)]) / len(by['valid']) * 100
        lt = t['ev'] - base['train']['ev']
        lv = v['ev'] - base['valid']['ev']
        bad = []
        if lt <= 0:
            bad.append('학습lift')
        if lv <= 0:
            bad.append('검증lift')
        if keep < MIN_KEEP:
            bad.append('잔존율')
        rows.append({'name': name, 'lt': lt, 'lv': lv, 'keep': keep,
                     'train_ev': t['ev'], 'valid_ev': v['ev'], 'bad': bad})
    rows.sort(key=lambda r: -(r['lt'] + r['lv']) / 2)
    for r in rows:
        mark = '통과' if not r['bad'] else '기각 ' + ','.join(r['bad'])
        print(f"  {r['name']:22s} {r['lt']:>+8.2f}%p {r['lv']:>+8.2f}%p "
              f"{(r['lt'] + r['lv']) / 2:>+7.2f}%p {r['keep']:>5.1f}% │ {mark}")

    ok = [r for r in rows if not r['bad']]
    res = {'round': '19b', 'baseline': {k: v['ev'] for k, v in base.items()},
           'stage1': rows, 'adopted': None}
    if not ok:
        print('\n' + '=' * 74)
        print('1단계 통과 없음 — 학습·검증 **양쪽에서** 기준선을 이기는 게이트가')
        print('하나도 없다. 국면·점수·진입위치·RSI·52주위치·데마크 어느 것으로')
        print('잘라도, 그 부분집합이 나머지보다 낫다고 말할 근거가 없다.')
        print('=' * 74)
        with open(OUT, 'w', encoding='utf-8') as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        print(f'기록: {OUT}')
        return

    pick = ok[0]
    fn = GATES[pick['name']]
    print(f"\n  ▶ 고른 게이트: {pick['name']} "
          f"(학습 {pick['lt']:+.2f}%p · 검증 {pick['lv']:+.2f}%p)")

    print('\n■ 2단계 — 실전 1회')
    bl = by['blind']
    kept = [c for c in bl if fn(c)]
    e = X.ev(kept)
    lift_b = e['ev'] - base['blind']['ev'] if e else None
    print(f"  기준선 {base['blind']['ev']:+.2f}% → 게이트 "
          f"{(e or {}).get('ev', 0):+.2f}%  (lift {lift_b:+.2f}%p · "
          f"잔존 {len(kept) / len(bl) * 100:.1f}%)")
    rr = X.rets(kept)
    lo = boot_lo(rr)
    h1 = [c for c in kept if half(c['ticker']) == 0]
    h2 = [c for c in kept if half(c['ticker']) == 1]
    b1 = [c for c in bl if half(c['ticker']) == 0]
    b2 = [c for c in bl if half(c['ticker']) == 1]
    l1 = (X.ev(h1) or {}).get('ev', 0) - (X.ev(b1) or {}).get('ev', 0)
    l2 = (X.ev(h2) or {}).get('ev', 0) - (X.ev(b2) or {}).get('ev', 0)

    c1 = lift_b is not None and lift_b > 0
    c2 = e is not None and e['ev'] > 0
    c3 = lo is not None and lo > 0
    c4 = l1 > 0 and l2 > 0
    c5 = len(kept) >= MIN_N
    for lab, val, okk in (('① 실전 lift > 0', f'{lift_b:+.2f}%p', c1),
                          ('② 실전 기대값 > 0', f"{e['ev']:+.2f}%", c2),
                          ('③ 부트스트랩 하한 > 0', f'{lo:+.2f}%', c3),
                          ('④ 종목 반반 lift > 0',
                           f'{l1:+.2f}/{l2:+.2f}%p', c4),
                          ('⑤ 표본 ≥ 30', f'{len(kept)}건', c5)):
        print(f"  {lab:22s} {val:>16s}  {'통과' if okk else '실패'}")
    adopted = c1 and c2 and c3 and c4 and c5
    print(f"\n  ▶ 판정: {'채택 가능' if adopted else '기각'}")
    if c1 and not c2:
        print('    (lift 는 양수지만 절대값이 여전히 음수 — 덜 잃을 뿐,')
        print('     돈을 버는 것은 아니다. 이걸 수익이라고 쓰면 거짓말이다.)')

    res['pick'] = pick['name']
    res['blind'] = {'ev': (e or {}).get('ev'), 'lift': lift_b,
                    'kept': len(kept), 'boot_lo': lo,
                    'ticker_lift': [l1, l2]}
    res['adopted'] = pick['name'] if adopted else None
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(f'\n기록: {OUT}')


if __name__ == '__main__':
    main()
