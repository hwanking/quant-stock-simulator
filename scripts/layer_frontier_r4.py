# -*- coding: utf-8 -*-
"""
라운드 4 진단 — '70%가 어디까지 가능한가'의 지도를 그린다.

라운드 4 본 실험(layer_study_r4.py)은 사전등록 기준을 충족하는 조건층을
찾지 못했다. 그렇다면 남은 질문은 하나다: **도달 가능한 상한은 얼마인가.**

이 파일은 채택을 위한 실험이 아니라 **진단**이다. 여기서 나온 규칙을
그대로 운영에 넣지 않는다 (검증 구간을 보고 고른 것은 이미 과최적화다).
목적은 두 가지다:
  · 학습 구간에서 조건을 조합해 갈 수 있는 최대 적중률을 안다
  · 그 규칙이 검증·블라인드로 넘어갈 때 얼마나 무너지는지(이월성)를 잰다
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
    return {'n': n, 'hit': 100.0 * hit / n, 'wilson': wilson_low(hit, n),
            'net': sum(rets) / n - COST_PCT,
            'pf': (gain / pain) if pain > 0 else (99.0 if gain else 0.0)}


def label(combo, key):
    return ' & '.join(f"{a}={v}" for a, v in zip(combo, key))


def scan(rows, max_k=3, min_n=120):
    out = []
    names = list(AXES)
    for k in range(1, max_k + 1):
        for combo in combinations(names, k):
            g = {}
            for r in rows:
                key = tuple(AXES[a](r) for a in combo)
                if any(v is None for v in key):
                    continue
                g.setdefault(key, []).append(r)
            for key, sub in g.items():
                st = stats(sub)
                if st and st['n'] >= min_n:
                    out.append((st, combo, key))
    return out


def pick(rows, combo, key):
    return [r for r in rows if tuple(AXES[a](r) for a in combo) == key]


def main():
    rows = load()
    by = {s: [r for r in rows if r.get('split') == s]
          for s in ('train', 'valid', 'blind')}

    print('■ 학습 구간에서 조건을 조합해 갈 수 있는 최대치 (표본 120건+)')
    res = scan(by['train'])
    res.sort(key=lambda x: -x[0]['hit'])
    for st, combo, key in res[:10]:
        v = stats(pick(by['valid'], combo, key))
        b = stats(pick(by['blind'], combo, key))
        vs = f"검증 {v['hit']:.1f}% (n={v['n']})" if v else '검증 표본 0'
        bs = f"블라인드 {b['hit']:.1f}% (n={b['n']})" if b else '블라인드 표본 0'
        print(f"  학습 {st['hit']:.1f}% n={st['n']:4d} "
              f"비용후 {st['net']:+.2f}% → {vs} · {bs}")
        print(f"     └ {label(combo, key)}")

    print('\n■ 이월성 — 학습에서 좋았던 규칙이 검증에서 얼마나 남는가')
    keep = []
    for st, combo, key in res:
        v = stats(pick(by['valid'], combo, key))
        if v and v['n'] >= 100:
            keep.append((st['hit'], v['hit'], st, v, combo, key))
    if keep:
        drops = [t - v for t, v, *_ in keep]
        print(f"  비교 가능한 규칙 {len(keep)}개 · "
              f"평균 낙폭 {sum(drops)/len(drops):+.1f}%p · "
              f"최대 낙폭 {max(drops):+.1f}%p · 최소 {min(drops):+.1f}%p")
        up = sum(1 for d in drops if d < 0)
        print(f"  검증에서 오히려 오른 규칙 {up}개 / {len(keep)}개 — "
              "학습 성적이 검증을 예측하지 못한다는 뜻이면 위험 신호다.")

    print('\n■ 검증 구간에서 실제로 70%+ 인 층 (사후 관찰 — 채택 근거 아님)')
    v70 = [(st, c, k) for st, c, k in scan(by['valid'], min_n=100)
           if st['hit'] >= 70.0]
    v70.sort(key=lambda x: -x[0]['wilson'])
    if not v70:
        print('  없음 — 표본 100건 이상으로 검증 70%를 넘는 조건층이 없습니다.')
    for st, combo, key in v70[:8]:
        t = stats(pick(by['train'], combo, key))
        b = stats(pick(by['blind'], combo, key))
        print(f"  검증 {st['hit']:.1f}% n={st['n']:4d} 비용후 {st['net']:+.2f}% | "
              f"학습 {t['hit']:.1f}% (n={t['n']}) | "
              + (f"블라인드 {b['hit']:.1f}% (n={b['n']})" if b else '블라인드 0'))
        print(f"     └ {label(combo, key)}")

    print('\n■ 구간별 기준선 — 목표(검증 70%)까지의 실제 거리')
    for s in ('train', 'valid', 'blind'):
        st = stats(by[s])
        print(f"  {s:6s} n={st['n']:5d} 적중 {st['hit']:.1f}% "
              f"비용후 {st['net']:+.2f}% PF {st['pf']:.2f}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
