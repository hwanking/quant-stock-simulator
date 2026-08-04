# -*- coding: utf-8 -*-
"""
라운드 17c — 원장의 mfe/mae/close 가 서로 모순되지 않는가.

라운드 17b 의 버킷 분해에서 말이 안 되는 값이 나왔다:
  목표(+4.5%)도 손절(-2.96%)도 안 닿은 'OPEN' 사례의 평균 종가수익 +9.80%.
  둘 다 안 닿았으면 가격은 그 사이에 머물렀다는 뜻인데, +9.8% 로 끝날 수 없다.

둘 중 하나다:
  (가) 내 재시뮬 함수가 틀렸다
  (나) 원장의 mfe/mae 와 close_return 이 **서로 다른 창**을 재고 있다

어느 쪽인지 가른다. (나)라면 라운드 17 의 결과 전체가 무효다 —
OPEN 버킷이 총수익의 대부분을 만들고 있었기 때문이다.

불변식 (성립해야 하는 것):
  ① mfe ≥ 0 이고 mae ≤ 0
  ② close_return ≤ mfe          (최고점보다 높게 끝날 수 없다)
  ③ close_return ≥ mae          (최저점보다 낮게 끝날 수 없다)
  ④ outcome=TARGET 이면 mfe ≥ 목표폭
  ⑤ outcome=STOP   이면 |mae| ≥ 손절폭
"""
import io
import json
import os
import sys
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LED = os.path.join(BASE, '.portfolio', 'virtual_graded.jsonl')


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    rows = []
    with open(LED, encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                try:
                    rows.append(json.loads(ln))
                except Exception:
                    pass
    print(f'원장 {len(rows):,}건\n')

    bad = Counter()
    examples = {}
    n_ok = 0
    for r in rows:
        mfe, mae = r.get('mfe_pct'), r.get('mae_pct')
        cl, p = r.get('close_return_pct'), r.get('price')
        t, s, o = r.get('target'), r.get('stop'), r.get('outcome')
        if mfe is None or mae is None or cl is None:
            bad['필드 없음'] += 1
            continue
        mfe, mae, cl = float(mfe), float(mae), float(cl)
        hit = False
        if mfe < -1e-9:
            bad['① mfe < 0'] += 1
            hit = True
        if mae > 1e-9:
            bad['① mae > 0'] += 1
            hit = True
        if cl > mfe + 1e-6:
            bad['② 종가 > 최고점'] += 1
            examples.setdefault('② 종가 > 최고점', r)
            hit = True
        if cl < mae - 1e-6:
            bad['③ 종가 < 최저점'] += 1
            examples.setdefault('③ 종가 < 최저점', r)
            hit = True
        if p and t and o == 'TARGET':
            tp = (t / p - 1) * 100
            if mfe < tp - 1e-6:
                bad['④ TARGET인데 mfe < 목표폭'] += 1
                examples.setdefault('④ TARGET인데 mfe < 목표폭', r)
                hit = True
        if p and s and o == 'STOP':
            sp = (1 - s / p) * 100
            if abs(mae) < sp - 1e-6:
                bad['⑤ STOP인데 |mae| < 손절폭'] += 1
                examples.setdefault('⑤ STOP인데 |mae| < 손절폭', r)
                hit = True
        if not hit:
            n_ok += 1

    print('■ 불변식 위반')
    if not bad:
        print('  없음 — 원장은 자체 정합이다')
    for k, v in bad.most_common():
        print(f'  {k:28s} {v:>7,}건 ({v / len(rows) * 100:.1f}%)')
    print(f'  전부 통과 {n_ok:,}건 ({n_ok / len(rows) * 100:.1f}%)')

    for k, r in examples.items():
        print(f'\n■ 예시 — {k}')
        for fld in ('ticker', 'date', 'price', 'target', 'stop', 'outcome',
                    'mfe_pct', 'mae_pct', 'close_return_pct', 'return_pct',
                    'touched_bar', 'horizon_days'):
            print(f'    {fld:20s} = {r.get(fld)}')

    # OPEN 사례만 따로 — 여기가 문제였다
    print('\n■ OPEN(현행 기준 미도달) 사례의 종가수익 분포')
    op = [float(r['close_return_pct']) for r in rows
          if r.get('outcome') == 'OPEN' and r.get('close_return_pct') is not None]
    if op:
        op.sort()
        print(f'  n={len(op):,}  최소 {op[0]:+.1f}%  '
              f'25% {op[len(op) // 4]:+.1f}%  중앙 {op[len(op) // 2]:+.1f}%  '
              f'75% {op[len(op) * 3 // 4]:+.1f}%  최대 {op[-1]:+.1f}%')
        print(f'  평균 {sum(op) / len(op):+.2f}%')

    # 현행 목표·손절 폭과 mfe/mae 의 관계 — horizon 이 같은 창인가
    print('\n■ horizon_days 분포 (mfe/mae/close 가 같은 창을 보는지)')
    print('  ' + ' · '.join(f'{k}일={v:,}' for k, v in
                            Counter(r.get('horizon_days') for r in rows).most_common()))
    print('\n■ touched_bar 분포 요약')
    tb = [r.get('touched_bar') for r in rows if r.get('touched_bar') is not None]
    if tb:
        tb = sorted(int(x) for x in tb)
        print(f'  n={len(tb):,}  중앙 {tb[len(tb) // 2]}봉  최대 {tb[-1]}봉')


if __name__ == '__main__':
    main()
