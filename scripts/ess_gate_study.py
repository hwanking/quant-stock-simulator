# -*- coding: utf-8 -*-
"""
라운드 3 — 유효표본 게이트가 정당한가 (매수 결론 0.1% 문제의 원인 검증)

배경: `build_final_verdict` 의 거부권
      "유효표본 N건 — 확률 판단 기준 미달" 이 60점+ 신호에서도 매수를 막아,
      원장 6,508건 중 매수 계열 판정이 5건(0.1%)뿐이다.

물음: 자기유사 유효표본(ESS)이 적은 사례는 **실제로도** 성적이 나쁜가?
      나쁘지 않다면 게이트는 기회만 없애는 것이고, 그 자리에 더 큰 표본인
      **점수대 캘리브레이션(6,508건 실측)**을 대체 확률로 쓰면 된다.

규율 (§58): 아래 가설·판정 규칙을 먼저 적는다. 평가는 학습·검증 구간만 쓰고,
      블라인드는 결론 확정 뒤 1회만 본다. 통과 못 하면 현행 게이트를 유지한다.

판정 규칙 (검증 구간 기준, 전부 충족해야 '게이트 완화 정당'):
  1) 저ESS 그룹 n >= 100
  2) 저ESS 적중률 >= 고ESS 적중률 - 3.0%p   (실질적 열위가 없을 것)
  3) 저ESS 비용후 평균수익 >= 고ESS - 0.30%p
  4) 점수 58+ 부분집합에서도 1~3이 유지될 것 (신호 구간에서 특히 중요)
"""
from __future__ import annotations

import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(BASE, '.portfolio', 'virtual_graded.jsonl')
COST = 0.55
ESS_GATE = 10.0            # 현행 게이트 기준 (규칙집 min_effective_samples)


def stats(rows):
    n = len(rows)
    if not n:
        return {'n': 0}
    hit = sum(1 for r in rows if r.get('success'))
    rets = [float(r.get('return_pct') or 0) for r in rows]
    avg = sum(rets) / n
    z, p = 1.96, hit / n
    wil = ((p + z * z / (2 * n) - z * ((p * (1 - p) / n
            + z * z / (4 * n * n)) ** 0.5)) / (1 + z * z / n)) * 100
    return {'n': n, 'hit': p * 100, 'wil': wil, 'avg': avg, 'ac': avg - COST}


def fmt(s):
    return ("n=0" if not s.get('n') else
            f"n={s['n']:>5}  적중 {s['hit']:5.1f}% (W {s['wil']:4.1f}%)  "
            f"비용후 {s['ac']:+5.2f}%")


def main():
    rows = []
    with open(LEDGER, encoding='utf-8') as f:
        for line in f:
            try:
                r = json.loads(line)
                r['score'] = int(r.get('score') or 0)
                r['_ess'] = float(r.get('eff_sample') or 0)
                rows.append(r)
            except Exception:
                continue
    tv = [r for r in rows if r.get('split') in ('train', 'valid')]
    bl = [r for r in rows if r.get('split') == 'blind']
    lo = [r for r in tv if r['_ess'] < ESS_GATE]
    hi = [r for r in tv if r['_ess'] >= ESS_GATE]

    print(f"원장 {len(rows)}건 · 학습+검증 {len(tv)} · 블라인드 {len(bl)}")
    print(f"ESS 게이트 기준 {ESS_GATE:.0f}건\n")
    print("=" * 92)
    print("1. 전체 — 게이트에 걸리는 그룹(저ESS) vs 통과 그룹(고ESS), 학습+검증만")
    print("=" * 92)
    s_lo, s_hi = stats(lo), stats(hi)
    print(f"  저ESS(게이트 차단): {fmt(s_lo)}")
    print(f"  고ESS(게이트 통과): {fmt(s_hi)}")
    print(f"  → 차단 그룹이 전체의 {len(lo) / max(1, len(tv)) * 100:.1f}%")

    print("\n" + "=" * 92)
    print("2. 신호 구간(점수 58+) — 실제로 추천이 나가는 자리")
    print("=" * 92)
    lo58 = [r for r in lo if r['score'] >= 58]
    hi58 = [r for r in hi if r['score'] >= 58]
    s_lo58, s_hi58 = stats(lo58), stats(hi58)
    print(f"  저ESS·58+: {fmt(s_lo58)}")
    print(f"  고ESS·58+: {fmt(s_hi58)}")

    print("\n" + "=" * 92)
    print("3. 판정 규칙 적용")
    print("=" * 92)
    c1 = s_lo58.get('n', 0) >= 100
    c2 = (s_lo58.get('hit', 0) >= s_hi58.get('hit', 0) - 3.0
          if s_hi58.get('n') else False)
    c3 = (s_lo58.get('ac', -9e9) >= s_hi58.get('ac', -9e9) - 0.30
          if s_hi58.get('n') else False)
    c0 = s_lo.get('n', 0) >= 100
    for nm, ok in (("① 저ESS·58+ 표본 100건 이상", c1),
                   ("② 적중률 열위 3%p 이내", c2),
                   ("③ 비용후 열위 0.30%p 이내", c3),
                   ("④ 전체 저ESS 표본 100건 이상", c0)):
        print(f"  {'통과' if ok else '탈락'}  {nm}")
    ok_all = c1 and c2 and c3 and c0

    print()
    if not ok_all:
        print("결론: 게이트 완화 근거 부족 — 현행 유지. 블라인드는 보지 않는다.")
        return 0
    print("결론: 저ESS 그룹이 실질적으로 열위가 아니다 → 게이트는 기회만 없앤다.")
    print("      확률 판단 근거를 '자기유사 표본' 대신 '점수대 캘리브레이션'으로")
    print("      대체하는 완화가 정당하다.")
    print("\n" + "=" * 92)
    print("4. 블라인드 공개 — 결론 확정 뒤 1회")
    print("=" * 92)
    b_lo58 = stats([r for r in bl if r['_ess'] < ESS_GATE and r['score'] >= 58])
    b_hi58 = stats([r for r in bl if r['_ess'] >= ESS_GATE and r['score'] >= 58])
    print(f"  저ESS·58+ blind: {fmt(b_lo58)}")
    print(f"  고ESS·58+ blind: {fmt(b_hi58)}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
