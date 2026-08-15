# -*- coding: utf-8 -*-
"""
라운드 3 (수정) — 매수를 막는 진짜 거부권은 무엇이고, 그것은 정당한가.

1차 가설(유효표본 게이트)은 **기각**됐다: 원장 5,660건 중 ESS 미달은 1건뿐이라
그 거부권은 사실상 발동하지 않는다.

남은 후보는 `build_final_verdict` 의 두 번째 거부권:
      "거래비용 차감 후 기대수익 net <= 0"
    net = 자기유사 평균수익(mean_perf) − 거래비용(0.55%)
원장의 `net_expected` 가 그 값이다.

물음: net_expected 가 실제 성과를 가르는가?
      가른다면 게이트는 옳다(기회가 적은 게 아니라 기회 자체가 드문 것).
      가르지 못한다면 잡음으로 기회를 죽이는 것이다.

규율(§58): 판정 규칙을 먼저 적는다. 학습·검증만으로 결론, 블라인드는 1회.

판정 규칙 — '게이트 유효' 로 인정하려면 검증 구간에서 전부 충족:
  1) net>0 그룹과 net<=0 그룹 모두 n >= 200
  2) net>0 의 적중률이 net<=0 보다 3.0%p 이상 높다
  3) net>0 의 비용후 평균수익이 net<=0 보다 0.30%p 이상 높다
충족하면 현행 유지, 미충족이면 '완화 후보'로 등록(즉시 반영 아님).
"""
from __future__ import annotations

import io
import json
import os
import sys

try:                       # 라운드 103 — 객체를 갈아끼우지 않는다
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:          # noqa: BLE001
    pass
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(BASE, '.portfolio', 'virtual_graded.jsonl')
COST = 0.55


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
    gains = sum(x for x in rets if x > 0)
    losses = -sum(x for x in rets if x < 0)
    return {'n': n, 'hit': p * 100, 'wil': wil, 'avg': avg, 'ac': avg - COST,
            'pf': (gains / losses) if losses else float('inf')}


def fmt(s):
    return ("n=0" if not s.get('n') else
            f"n={s['n']:>5}  적중 {s['hit']:5.1f}% (W {s['wil']:4.1f}%)  "
            f"비용후 {s['ac']:+5.2f}%  PF {s['pf']:.2f}")


def main():
    rows = []
    with open(LEDGER, encoding='utf-8') as f:
        for line in f:
            try:
                r = json.loads(line)
                r['score'] = int(r.get('score') or 0)
                r['_net'] = r.get('net_expected')
                rows.append(r)
            except Exception:
                continue
    tv = [r for r in rows if r.get('split') in ('train', 'valid')]
    bl = [r for r in rows if r.get('split') == 'blind']
    known = [r for r in tv if r['_net'] is not None]
    pos = [r for r in known if float(r['_net']) > 0]
    neg = [r for r in known if float(r['_net']) <= 0]

    print(f"원장 {len(rows)}건 · 학습+검증 {len(tv)} · net 기록됨 {len(known)}\n")
    print("=" * 96)
    print("1. 거래비용 차감 기대수익(net) 부호별 실제 성과 — 학습+검증")
    print("=" * 96)
    s_p, s_n = stats(pos), stats(neg)
    print(f"  net > 0  (게이트 통과): {fmt(s_p)}")
    print(f"  net <= 0 (매수 차단)  : {fmt(s_n)}")
    print(f"  → 차단 그룹이 전체의 {len(neg) / max(1, len(known)) * 100:.1f}%")

    print("\n" + "=" * 96)
    print("2. 신호 구간(58+)에서")
    print("=" * 96)
    p58, n58 = [r for r in pos if r['score'] >= 58], [r for r in neg if r['score'] >= 58]
    s_p58, s_n58 = stats(p58), stats(n58)
    print(f"  net>0  ·58+: {fmt(s_p58)}")
    print(f"  net<=0 ·58+: {fmt(s_n58)}")

    print("\n" + "=" * 96)
    print("3. 판정 규칙 — 게이트가 실제로 성과를 가르는가")
    print("=" * 96)
    c1 = s_p.get('n', 0) >= 200 and s_n.get('n', 0) >= 200
    c2 = s_p.get('hit', 0) - s_n.get('hit', 0) >= 3.0
    c3 = s_p.get('ac', 0) - s_n.get('ac', 0) >= 0.30
    for nm, ok in ((f"① 양쪽 표본 200건 이상 ({s_p.get('n',0)}/{s_n.get('n',0)})", c1),
                   (f"② 적중률 차이 3%p 이상 (실측 "
                    f"{s_p.get('hit',0) - s_n.get('hit',0):+.1f}%p)", c2),
                   (f"③ 비용후 차이 0.30%p 이상 (실측 "
                    f"{s_p.get('ac',0) - s_n.get('ac',0):+.2f}%p)", c3)):
        print(f"  {'통과' if ok else '탈락'}  {nm}")

    print()
    if c1 and c2 and c3:
        print("결론: 게이트는 실제로 성과를 가른다 — 현행 유지가 옳다.")
        print("      매수 결론이 드문 것은 결함이 아니라 '기회가 드물다'는 사실이다.")
    else:
        print("결론: 게이트가 성과를 충분히 가르지 못한다 — 완화 후보로 등록.")
        print("      (즉시 반영하지 않는다. 사전등록 → 리플레이 재생성 → 블라인드 1회)")
    print("\n" + "=" * 96)
    print("4. 블라인드 1회 공개 (결론 확정 뒤)")
    print("=" * 96)
    bp = stats([r for r in bl if r.get('net_expected') is not None
                and float(r['net_expected']) > 0])
    bn = stats([r for r in bl if r.get('net_expected') is not None
                and float(r['net_expected']) <= 0])
    print(f"  net>0  blind: {fmt(bp)}")
    print(f"  net<=0 blind: {fmt(bn)}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
