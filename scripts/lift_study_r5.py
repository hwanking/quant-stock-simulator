# -*- coding: utf-8 -*-
"""
라운드 5 — 적중률이 아니라 **기준선 대비 초과성과(lift)** 로 규칙을 고른다.

라운드 4에서 밝혀진 것 (이것이 이 라운드의 출발점이다):
  · 구간마다 시장이 달라 기준선 자체가 다르다.
    학습 55.8% · 검증 63.6% · 블라인드 44.9%
  · 그래서 '검증 70%' 같은 절대 수치로 규칙을 고르면 **그 기간의 장세**를
    고르게 된다. 실제로 검증 70%+ 층은 전부 횡보 국면이었고, 같은 규칙이
    학습에서는 50% 안팎이었다.
  · 학습에서 좋았던 규칙 727개 중 567개가 검증에서 '올랐다' — 규칙이 좋아서가
    아니라 검증 구간이 통째로 쉬웠기 때문이다.

그러므로 이 라운드의 질문은 바뀐다:
  "어떤 규칙이 **어느 장세에서든 그 장세의 평균보다** 꾸준히 나은가?"

사전등록 (측정 전 고정):
  선정 지표 : lift = 해당 구간 적중률 − 그 구간 전체 기준선
  탐색      : 학습 구간에서만. 표본 300건+ · 학습 lift +5.0%p 이상
  순위      : 학습 lift 의 Wilson 하한 기준 상위 8개만 검증으로 넘긴다
  채택      : 검증 lift +3.0%p 이상 · 검증 표본 150건+ · 검증 비용후 > 0
  최종 확인 : 위를 통과한 것에 한해 블라인드 lift 를 한 번 열어 본다.
              블라인드 lift 가 음수면 채택하지 않는다 (세 구간 모두 양수여야
              '장세와 무관한 신호'라고 부를 수 있다).
  실패 시   : 아무것도 채택하지 않고 그대로 기록한다.
"""
from __future__ import annotations

import io
import json
import math
import os
import sys
from itertools import combinations

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(BASE, '.portfolio', 'virtual_graded.jsonl')

COST_PCT = 0.30
MIN_TRAIN_N = 300
MIN_TRAIN_LIFT = 5.0
TOP_K = 8
MIN_VALID_N = 150
MIN_VALID_LIFT = 3.0


def wilson_low(hit, n, z=1.96):
    if not n:
        return 0.0
    p = hit / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return 100.0 * (c - m) / d


def _b(v, edges, labels):
    if v is None:
        return None
    for e, la in zip(edges, labels):
        if v < e:
            return la
    return labels[-1]


AXES = {
    '점수대': lambda r: _b(r.get('score'), [50, 55, 58, 60, 65],
                        ['~49', '50~54', '55~57', '58~59', '60~64', '65+']),
    '국면': lambda r: r.get('regime'),
    '진입구역': lambda r: r.get('entry_zone'),
    '디마크': lambda r: r.get('demark_state'),
    '월10선': lambda r: ('위' if r.get('m10_above') else '아래'),
    'RSI': lambda r: _b(r.get('rsi'), [35, 45, 55, 65],
                        ['과매도', '약세', '중립', '강세', '과열']),
    '볼밴위치': lambda r: _b(r.get('bb_pos'), [20, 40, 60, 80],
                          ['하단', '중하', '중간', '중상', '상단']),
    '레인지위치': lambda r: _b(r.get('range_pos'), [25, 50, 75],
                           ['저점권', '중하', '중상', '고점권']),
    '변동성': lambda r: _b(r.get('vol20'), [0.010, 0.018, 0.028],
                        ['낮음', '보통', '높음', '매우높음']),
    '시장': lambda r: r.get('market'),
    '자산': lambda r: r.get('asset_type'),
}


def load():
    out = []
    with open(LEDGER, encoding='utf-8') as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get('success') is None or r.get('return_pct') is None:
                continue
            out.append(r)
    return out


def stats(rows):
    n = len(rows)
    if not n:
        return None
    hit = sum(1 for r in rows if r['success'])
    rets = [float(r['return_pct']) for r in rows]
    win = [v for v in rets if v > 0]
    loss = [v for v in rets if v <= 0]
    gain, pain = sum(win), abs(sum(loss))
    maes = [abs(float(r['mae_pct'])) for r in rows
            if r.get('mae_pct') is not None]
    return {'n': n, 'hit': 100.0 * hit / n, 'hits': hit,
            'wilson': wilson_low(hit, n), 'net': sum(rets) / n - COST_PCT,
            'pf': (gain / pain) if pain > 0 else (99.0 if gain else 0.0),
            'mae': (sum(maes) / len(maes)) if maes else 0.0}


def label(combo, key):
    return ' & '.join(f"{a}={v}" for a, v in zip(combo, key))


def pick(rows, combo, key):
    return [r for r in rows if tuple(AXES[a](r) for a in combo) == key]


def main():
    rows = load()
    by = {s: [r for r in rows if r.get('split') == s]
          for s in ('train', 'valid', 'blind')}
    base = {s: stats(v) for s, v in by.items()}

    print('■ 구간 기준선 — lift 는 이 값 대비로 잰다')
    for s in ('train', 'valid', 'blind'):
        b = base[s]
        print(f"  {s:6s} n={b['n']:5d} 적중 {b['hit']:.1f}% "
              f"비용후 {b['net']:+.2f}%")

    names = list(AXES)
    cands = []
    for k in (1, 2, 3):
        for combo in combinations(names, k):
            g = {}
            for r in by['train']:
                key = tuple(AXES[a](r) for a in combo)
                if any(v is None for v in key):
                    continue
                g.setdefault(key, []).append(r)
            for key, sub in g.items():
                st = stats(sub)
                if st['n'] < MIN_TRAIN_N:
                    continue
                lift = st['hit'] - base['train']['hit']
                if lift >= MIN_TRAIN_LIFT and st['net'] > 0:
                    cands.append({'combo': combo, 'key': key, 'st': st,
                                  'lift': lift,
                                  'wl': st['wilson'] - base['train']['hit']})

    cands.sort(key=lambda c: -c['wl'])
    print(f"\n■ 학습 1차 통과 {len(cands)}개 "
          f"(표본 {MIN_TRAIN_N}+ · lift +{MIN_TRAIN_LIFT}%p+ · 비용후 양수)")
    if not cands:
        print('  없음.')
        print('\n판정: 채택 없음 — 장세와 무관하게 기준선을 이기는 규칙이 '
              '학습 구간에 없습니다.')
        return 1

    sel = cands[:TOP_K]
    for i, c in enumerate(sel, 1):
        print(f"  {i}. {label(c['combo'], c['key'])}")
        print(f"     학습 n={c['st']['n']} 적중 {c['st']['hit']:.1f}% "
              f"(lift {c['lift']:+.1f}%p · Wilson lift {c['wl']:+.1f}%p) "
              f"비용후 {c['st']['net']:+.2f}%")

    print(f"\n■ 검증 확인 — lift +{MIN_VALID_LIFT}%p+ · 표본 {MIN_VALID_N}+ "
          f"· 비용후 양수")
    passed = []
    for i, c in enumerate(sel, 1):
        v = stats(pick(by['valid'], c['combo'], c['key']))
        nm = label(c['combo'], c['key'])
        if not v:
            print(f"  {i}. {nm} — 검증 표본 0건")
            continue
        vl = v['hit'] - base['valid']['hit']
        ok = (vl >= MIN_VALID_LIFT and v['n'] >= MIN_VALID_N and v['net'] > 0)
        print(f"  {i}. {nm}")
        print(f"     검증 n={v['n']} 적중 {v['hit']:.1f}% (lift {vl:+.1f}%p) "
              f"비용후 {v['net']:+.2f}% PF {v['pf']:.2f} "
              f"→ {'통과' if ok else '미달'}")
        if ok:
            passed.append((c, v, vl))

    print('\n■ 블라인드 최종 확인 — lift 가 양수여야 채택한다')
    winners = []
    for c, v, vl in passed:
        b = stats(pick(by['blind'], c['combo'], c['key']))
        nm = label(c['combo'], c['key'])
        if not b:
            print(f"  {nm} — 블라인드 표본 0건 → 채택 보류")
            continue
        bl = b['hit'] - base['blind']['hit']
        ok = bl > 0
        print(f"  {nm}")
        print(f"     블라인드 n={b['n']} 적중 {b['hit']:.1f}% "
              f"(lift {bl:+.1f}%p) 비용후 {b['net']:+.2f}% "
              f"→ {'채택' if ok else '기각'}")
        if ok:
            winners.append((c, v, b, vl, bl))

    print('\n' + '=' * 70)
    if winners:
        print(f"판정: 채택 {len(winners)}개 — 세 구간 모두에서 그 구간의 "
              "기준선을 이겼습니다 (장세 의존이 아니라는 뜻).")
        for c, v, b, vl, bl in winners:
            print(f"  · {label(c['combo'], c['key'])}")
            print(f"    학습 {c['lift']:+.1f}%p · 검증 {vl:+.1f}%p · "
                  f"블라인드 {bl:+.1f}%p")
    else:
        print('판정: 채택 없음 — 세 구간을 모두 통과한 규칙이 없습니다.')
        print('     기준을 낮춰 통과시키지 않습니다. 운영 모델은 그대로 둡니다.')
    print('=' * 70)
    return 0 if winners else 1


if __name__ == '__main__':
    sys.exit(main())
