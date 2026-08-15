# -*- coding: utf-8 -*-
"""
사전등록 신호 게이트 연구 — 신호율 2.9%를 품질 손실 없이 넓힐 수 있는가.

규율 (§58 — 스크립트에 박제):
  · 후보 정의와 선정 규칙을 **먼저** 적는다 (아래 CANDIDATES / 선정 규칙).
  · 평가는 학습(train)·검증(valid) 구간만 쓴다.
  · 블라인드는 **승자 확정 후 단 1회** 공개한다 — 후보 비교·선택에 쓰지 않는다.
  · 어떤 후보도 선정 규칙을 통과하지 못하면 기준선을 유지한다 (억지 채택 금지).

선정 규칙 (검증 구간 기준, 전부 충족해야 승자 후보):
  1) 신호 수 n >= 30
  2) 비용후 평균수익 > 기준선(비용후)
  3) 적중률 >= 기준선 적중률 - 2.0%p
  4) 신호 수 > 기준선 신호 수 (신호율 확대가 이번 연구의 목적이므로)
  충족 후보가 여럿이면 검증 비용후 평균수익 최고인 것 하나.
  추가 감시: 승자의 train 방향(기준선 대비 개선 여부)이 valid와 일치하는지 기록.
"""
from __future__ import annotations

import io
import json
import os
import sys
from collections import OrderedDict

try:                       # 라운드 103 — 객체를 갈아끼우지 않는다
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:          # noqa: BLE001
    pass
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(BASE, '.portfolio', 'virtual_graded.jsonl')
COST_PCT = 0.55

CANDIDATES = OrderedDict([
    ('A(기준선) 점수60+', lambda r: r['score'] >= 60),
    ('B 점수58+', lambda r: r['score'] >= 58),
    ('C 점수58+·월10선위', lambda r: r['score'] >= 58 and r.get('m10_above')),
    ('D 점수60+·비약세', lambda r: r['score'] >= 60 and r.get('regime') != 'BEAR'),
    ('E 점수58+·월10선위·비약세',
     lambda r: r['score'] >= 58 and r.get('m10_above')
     and r.get('regime') != 'BEAR'),
    ('F 점수55+·월10선위·비약세',
     lambda r: r['score'] >= 55 and r.get('m10_above')
     and r.get('regime') != 'BEAR'),
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
    gains = sum(x for x in rets if x > 0)
    losses = -sum(x for x in rets if x < 0)
    return {'n': n, 'hit_rate': p * 100, 'wilson_low': wil, 'avg': avg,
            'after_cost': avg - COST_PCT,
            'pf': (gains / losses) if losses else float('inf')}


def fmt(s):
    if not s.get('n'):
        return "n=0"
    return (f"n={s['n']:>4}  적중 {s['hit_rate']:5.1f}% (W하한 {s['wilson_low']:4.1f}%)  "
            f"평균 {s['avg']:+5.2f}%  비용후 {s['after_cost']:+5.2f}%  PF {s['pf']:.2f}")


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
    n_tot = {sp: len(tv[sp]) or 1 for sp in tv}

    print(f"원장 {len(rows)}건 (train {len(tv['train'])} / valid {len(tv['valid'])} "
          f"/ blind {len(tv['blind'])}) · 비용 {COST_PCT}%\n")
    print("=" * 100)
    print("후보별 성적 — 학습·검증만 공개 (블라인드는 승자 확정 후 1회)")
    print("=" * 100)

    results = {}
    for name, rule in CANDIDATES.items():
        res = {}
        for sp in ('train', 'valid'):
            sel = [r for r in tv[sp] if rule(r)]
            res[sp] = stats(sel)
            res[sp]['rate'] = len(sel) / n_tot[sp] * 100
        results[name] = res
        print(f"\n  {name}")
        for sp in ('train', 'valid'):
            print(f"    {sp:5}: {fmt(res[sp])}  신호율 {res[sp]['rate']:.1f}%")

    base = results['A(기준선) 점수60+']['valid']
    print("\n" + "=" * 100)
    print("선정 규칙 적용 (검증 기준): n>=30 · 비용후>기준선 · 적중률>=기준선-2p · 신호수>기준선")
    print("=" * 100)
    passed = []
    for name, res in results.items():
        if name.startswith('A('):
            continue
        v = res['valid']
        ok = (v.get('n', 0) >= 30
              and v.get('after_cost', -9e9) > base.get('after_cost', -9e9)
              and v.get('hit_rate', 0) >= base.get('hit_rate', 0) - 2.0
              and v.get('n', 0) > base.get('n', 0))
        print(f"  {'통과' if ok else '탈락'}  {name}"
              + ("" if ok else "  (조건 미충족)"))
        if ok:
            passed.append(name)

    if not passed:
        print("\n결론: 어떤 후보도 선정 규칙을 통과하지 못했다 — 기준선(60+) 유지.")
        print("블라인드는 공개하지 않는다 (선택에 쓸 수 없으므로 볼 이유가 없다).")
        return 0

    winner = max(passed, key=lambda nm: results[nm]['valid']['after_cost'])
    print(f"\n승자: {winner}")
    tr_dir = (results[winner]['train']['after_cost']
              > results['A(기준선) 점수60+']['train'].get('after_cost', -9e9))
    print(f"train 방향 일치(개선): {'예' if tr_dir else '아니오 — 과적합 주의 기록'}")

    print("\n" + "=" * 100)
    print("블라인드 공개 — 승자 1회 (기준선은 이미 공개된 수치)")
    print("=" * 100)
    rule = CANDIDATES[winner]
    for name in ('A(기준선) 점수60+', winner):
        sel = [r for r in tv['blind'] if CANDIDATES[name](r)]
        s = stats(sel)
        print(f"  {name:28} blind: {fmt(s)}  신호율 {len(sel) / n_tot['blind'] * 100:.1f}%")
    return 0


if __name__ == '__main__':
    sys.exit(main())
