# -*- coding: utf-8 -*-
"""
진입 갭 연구 (라운드 2.5) — "권장 매수가와 현재가 갭이 큰 조건부 추천이
실제로 유효한가?" (사용자 관찰: 현재가 34,550 vs 권장 31,665 = -8.4% 갭)

원장의 entry_zone(판정 당시 가격이 권장/적정 대비 어디였는지)으로 검증한다.

규율 (§58): 후보·선정 규칙 먼저 명문화, 평가는 학습·검증만,
블라인드는 승자 확정 후 1회. 통과 없으면 기준선 유지.

선정 규칙 (검증 기준): 1) n>=30  2) 비용후 > 기준선 B(58+)
3) 적중률 > 기준선 B  — 이번 목적은 '품질'이므로 신호수 조건은 두지 않는다.
충족 후보 중 검증 비용후 최고 1개. train 방향 일치 여부 기록.
"""
from __future__ import annotations

import io
import json
import os
import sys
from collections import OrderedDict, defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(BASE, '.portfolio', 'virtual_graded.jsonl')
COST = 0.55

_SAFE = '안전마진 확보'
_BELOW = '적정가 이하 (안전마진 미확보)'
_OVER_BIG = '적정가 크게 초과 (추격매수 위험)'

CANDIDATES = OrderedDict([
    ('B(기준선) 58+', lambda r: r['score'] >= 58),
    ('G 58+·안전마진 확보', lambda r: r['score'] >= 58
     and r.get('entry_zone') == _SAFE),
    ('H 58+·적정가 이하(안전마진 무관)', lambda r: r['score'] >= 58
     and r.get('entry_zone') in (_SAFE, _BELOW)),
    ('I 58+·추격위험 제외', lambda r: r['score'] >= 58
     and r.get('entry_zone') != _OVER_BIG),
])


def stats(rows):
    n = len(rows)
    if not n:
        return {'n': 0}
    hit = sum(1 for r in rows if r.get('success'))
    rets = [float(r.get('return_pct') or 0) for r in rows]
    avg = sum(rets) / n
    z = 1.96
    p = hit / n
    wil = ((p + z * z / (2 * n) - z * ((p * (1 - p) / n
            + z * z / (4 * n * n)) ** 0.5)) / (1 + z * z / n)) * 100
    return {'n': n, 'hit': p * 100, 'wil': wil, 'avg': avg, 'ac': avg - COST}


def fmt(s):
    if not s.get('n'):
        return "n=0"
    return (f"n={s['n']:>4}  적중 {s['hit']:5.1f}% (W {s['wil']:4.1f}%)  "
            f"비용후 {s['ac']:+5.2f}%")


def main():
    rows = []
    with open(LEDGER, encoding='utf-8') as f:
        for line in f:
            try:
                r = json.loads(line)
                r['score'] = int(r.get('score') or 0)
                rows.append(r)
            except Exception:
                continue
    tv = {sp: [r for r in rows if r.get('split') == sp]
          for sp in ('train', 'valid', 'blind')}
    print(f"원장 {len(rows)}건 (t {len(tv['train'])} / v {len(tv['valid'])} "
          f"/ b {len(tv['blind'])})\n")

    print("=" * 88)
    print("참고: 진입구간(entry_zone)별 성공률 — 학습+검증 (블라인드 미포함)")
    print("=" * 88)
    zones = defaultdict(list)
    for r in tv['train'] + tv['valid']:
        zones[str(r.get('entry_zone') or '?')].append(r)
    for z, rs in sorted(zones.items(), key=lambda x: -len(x[1])):
        print(f"  {z:28} {fmt(stats(rs))}")

    print()
    print("=" * 88)
    print("사전등록 대결 — 학습·검증만 공개")
    print("=" * 88)
    res = {}
    for name, rule in CANDIDATES.items():
        res[name] = {sp: stats([r for r in tv[sp] if rule(r)])
                     for sp in ('train', 'valid')}
        print(f"\n  {name}")
        for sp in ('train', 'valid'):
            print(f"    {sp:5}: {fmt(res[name][sp])}")

    base = res['B(기준선) 58+']['valid']
    passed = [nm for nm, r in res.items() if not nm.startswith('B(')
              and r['valid'].get('n', 0) >= 30
              and r['valid'].get('ac', -9e9) > base.get('ac', -9e9)
              and r['valid'].get('hit', 0) > base.get('hit', 0)]
    print("\n선정 규칙 통과:", passed if passed else "없음 — 기준선 유지, 블라인드 미공개")
    if not passed:
        return 0
    winner = max(passed, key=lambda nm: res[nm]['valid']['ac'])
    tr_ok = res[winner]['train']['ac'] > res['B(기준선) 58+']['train']['ac']
    print(f"승자: {winner} · train 방향 일치: {'예' if tr_ok else '아니오(주의)'}")
    print("\n블라인드 공개 — 승자 1회 (기준선 58+는 기공개 수치)")
    for nm in ('B(기준선) 58+', winner):
        s = stats([r for r in tv['blind'] if CANDIDATES[nm](r)])
        print(f"  {nm:28} blind: {fmt(s)}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
