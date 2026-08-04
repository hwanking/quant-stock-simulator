# -*- coding: utf-8 -*-
"""
재시뮬레이터 검증 — 현행 설정을 넣으면 원장의 판정이 **그대로** 나오는가.

이게 안 맞으면 그 위에 쌓는 모든 연구가 무의미하다.
라운드 17 의 교훈: 도구를 먼저 검증하지 않으면 결론이 통째로 날아간다.

합격 기준 (사전등록):
  · 판정(TARGET/STOP/OPEN) 일치율 ≥ 99%
  · 불일치가 있으면 원인을 하나씩 열어 본다 — 넘어가지 않는다
"""
import io
import json
import os
import sys
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'scripts'))
import exec_sim as X


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    # 원장의 원래 판정을 같이 읽어 온다
    orig = {}
    for r in X._jsonl(X.LED):
        orig[(r['ticker'], r['date'])] = r.get('outcome')

    cases, n_nopath = X.load_cases(min_score=0, need_path=True)
    print(f'경로가 붙은 사례 {len(cases):,}건 · 경로 없음 {n_nopath:,}건')
    if not cases:
        print('아직 경로 보강이 덜 됐습니다 — 나중에 다시 돌리세요.')
        return 1

    agree = Counter()
    mismatch = []
    for c in cases:
        k, _ = X.simulate(c, c['TP'], c['SP'])
        o = orig.get((c['ticker'], c['date']))
        if k == 'NODATA':
            agree['경로없음'] += 1
            continue
        if k == o:
            agree['일치'] += 1
        else:
            agree['불일치'] += 1
            if len(mismatch) < 8:
                mismatch.append((c, o, k))

    tot = agree['일치'] + agree['불일치']
    rate = agree['일치'] / max(1, tot) * 100
    print(f"\n판정 일치 {agree['일치']:,}/{tot:,} = {rate:.2f}%")

    if mismatch:
        print('\n■ 불일치 예시')
        for c, o, k in mismatch:
            print(f"  {c['ticker']} {c['date']}  원장={o} 재시뮬={k}  "
                  f"목표+{c['TP']:.2f}% 손절-{c['SP']:.2f}%")
            hi, lo = c['high'], c['low']
            for i in range(min(6, len(hi))):
                print(f'      {i + 1}봉 고 {hi[i]:+6.2f}% 저 {lo[i]:+6.2f}%')

    print('\n' + '=' * 66)
    ok = rate >= 99.0
    print('합격 — 재시뮬레이터를 신뢰할 수 있다' if ok
          else f'불합격 ({rate:.2f}% < 99%) — 원인을 찾기 전엔 쓰지 않는다')
    print('=' * 66)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
