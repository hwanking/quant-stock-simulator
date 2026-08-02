# -*- coding: utf-8 -*-
"""
라운드 4 — 검증 적중률 70% 를 실제로 넘는 조건층이 있는가 (사전등록 연구).

배경 (라운드 3에서 규명된 사실):
  · 점수는 40~64 구간에 눌려 있다. 6,508건 중 70점 이상은 4건(0.06%).
  · 점수대별 적중률이 단조롭지 않다 — 60~64점(52.6%)이 55~59점(59.3%)보다
    오히려 나쁘다. 따라서 '문턱을 올려서' 70%에 도달하는 길은 막혀 있다.
  → 점수 하나가 아니라 **조건 조합**에서 답을 찾아야 한다.

사전등록 (측정 전에 고정 — 결과를 보고 규칙을 고치면 그건 실험이 아니다):
  탐색 구간 : train (<2025-07-01) 만 사용한다. 검증·블라인드는 보지 않는다.
  후보 공간 : 아래 AXES 의 1축·2축 조합 전체 (코드에 선명시)
  1차 통과  : train 표본 300건+ · 적중률 68%+ · 비용 차감 후 평균수익 > 0
  선정      : 통과한 것 중 train Wilson 하한 상위 5개만 검증으로 넘긴다
  채택 기준 : 검증 적중률 70%+ · 검증 표본 150건+ · 검증 비용후 > 0
  블라인드  : 마지막에 한 번만 열어 보고용으로 적는다 (선정에 쓰지 않는다)
  실패 시   : 아무것도 채택하지 않고 '70% 미달'을 그대로 기록한다.
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
MIN_TRAIN_HIT = 68.0
TOP_K = 5
TARGET_VALID_HIT = 70.0
MIN_VALID_N = 150


def wilson_low(hit, n, z=1.96):
    if not n:
        return 0.0
    p = hit / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return 100.0 * (c - m) / d


# ── 후보 축 — 원장에 실제로 있는 필드만 쓴다 (없는 값을 만들지 않는다) ────
def _bucket(v, edges, labels):
    if v is None:
        return None
    for e, la in zip(edges, labels):
        if v < e:
            return la
    return labels[-1]


AXES = {
    '점수대': lambda r: _bucket(r.get('score'), [50, 55, 58, 60, 65],
                             ['~49', '50~54', '55~57', '58~59', '60~64', '65+']),
    '국면': lambda r: r.get('regime'),
    '진입구역': lambda r: r.get('entry_zone'),
    '디마크': lambda r: r.get('demark_state'),
    '월10선': lambda r: ('위' if r.get('m10_above') else '아래'),
    'RSI': lambda r: _bucket(r.get('rsi'), [35, 45, 55, 65],
                             ['과매도', '약세', '중립', '강세', '과열']),
    '볼밴위치': lambda r: _bucket(r.get('bb_pos'), [20, 40, 60, 80],
                               ['하단', '중하', '중간', '중상', '상단']),
    '레인지위치': lambda r: _bucket(r.get('range_pos'), [25, 50, 75],
                                ['저점권', '중하', '중상', '고점권']),
    '변동성': lambda r: _bucket(r.get('vol20'), [0.010, 0.018, 0.028],
                             ['낮음', '보통', '높음', '매우높음']),
    '시장': lambda r: r.get('market'),
    '자산': lambda r: r.get('asset_type'),
}


def load():
    rows = []
    with open(LEDGER, encoding='utf-8') as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get('success') is None or r.get('return_pct') is None:
                continue
            rows.append(r)
    return rows


def stats(rows):
    n = len(rows)
    if not n:
        return None
    hit = sum(1 for r in rows if r['success'])
    rets = [float(r['return_pct']) for r in rows]
    win = [v for v in rets if v > 0]
    loss = [v for v in rets if v <= 0]
    gain, pain = sum(win), abs(sum(loss))
    maes = [abs(float(r['mae_pct'])) for r in rows if r.get('mae_pct') is not None]
    return {
        'n': n, 'hit': 100.0 * hit / n,
        'wilson': wilson_low(hit, n),
        'net': sum(rets) / n - COST_PCT,
        'pf': (gain / pain) if pain > 0 else (99.0 if gain else 0.0),
        'mae': (sum(maes) / len(maes)) if maes else 0.0,
    }


def main():
    rows = load()
    by = {s: [r for r in rows if r.get('split') == s]
          for s in ('train', 'valid', 'blind')}
    print(f"원장 {len(rows)}건 — 학습 {len(by['train'])} · 검증 {len(by['valid'])} "
          f"· 블라인드 {len(by['blind'])}\n")

    base = {s: stats(v) for s, v in by.items()}
    print('■ 기준선 (조건 없음)')
    for s in ('train', 'valid', 'blind'):
        b = base[s]
        print(f"  {s:6s} n={b['n']:5d} 적중 {b['hit']:.1f}% "
              f"비용후 {b['net']:+.2f}% PF {b['pf']:.2f}")

    # ── 1차: train 에서만 탐색한다 ──────────────────────────────────────
    names = list(AXES)
    cands = []
    for k in (1, 2):
        for combo in combinations(names, k):
            groups = {}
            for r in by['train']:
                key = tuple(AXES[a](r) for a in combo)
                if any(v is None for v in key):
                    continue
                groups.setdefault(key, []).append(r)
            for key, sub in groups.items():
                st = stats(sub)
                if (st['n'] >= MIN_TRAIN_N and st['hit'] >= MIN_TRAIN_HIT
                        and st['net'] > 0):
                    cands.append({'axes': combo, 'key': key, 'train': st})

    cands.sort(key=lambda c: -c['train']['wilson'])
    print(f"\n■ 학습에서 1차 통과한 규칙 {len(cands)}개 "
          f"(표본 {MIN_TRAIN_N}+ · 적중 {MIN_TRAIN_HIT}%+ · 비용후 양수)")
    if not cands:
        print('  없음 — 학습 구간에서조차 68% 를 넘는 조건 조합이 없습니다.')
        print('\n판정: 채택 없음. 검증 70% 목표 미달을 그대로 기록합니다.')
        return 1

    sel = cands[:TOP_K]
    for i, c in enumerate(sel, 1):
        lab = ' & '.join(f"{a}={v}" for a, v in zip(c['axes'], c['key']))
        t = c['train']
        print(f"  {i}. {lab}")
        print(f"     학습 n={t['n']} 적중 {t['hit']:.1f}% "
              f"(Wilson {t['wilson']:.1f}%) 비용후 {t['net']:+.2f}%")

    # ── 2차: 검증에서 확인 (여기서 규칙을 고치지 않는다) ────────────────
    print(f"\n■ 검증 확인 — 채택 기준 적중 {TARGET_VALID_HIT}%+ · "
          f"표본 {MIN_VALID_N}+ · 비용후 양수")
    winners = []
    for i, c in enumerate(sel, 1):
        sub = [r for r in by['valid']
               if tuple(AXES[a](r) for a in c['axes']) == c['key']]
        v = stats(sub)
        lab = ' & '.join(f"{a}={x}" for a, x in zip(c['axes'], c['key']))
        if not v:
            print(f"  {i}. {lab} — 검증 표본 0건")
            continue
        ok = (v['hit'] >= TARGET_VALID_HIT and v['n'] >= MIN_VALID_N
              and v['net'] > 0)
        print(f"  {i}. {lab}")
        print(f"     검증 n={v['n']} 적중 {v['hit']:.1f}% "
              f"비용후 {v['net']:+.2f}% PF {v['pf']:.2f} MAE {v['mae']:.2f}% "
              f"→ {'채택 가능' if ok else '기준 미달'}")
        if ok:
            winners.append((c, v))

    # ── 블라인드는 마지막에 한 번, 보고용으로만 ─────────────────────────
    print('\n■ 블라인드 (보고 전용 — 위 판정에 쓰지 않았다)')
    for i, c in enumerate(sel, 1):
        sub = [r for r in by['blind']
               if tuple(AXES[a](r) for a in c['axes']) == c['key']]
        b = stats(sub)
        lab = ' & '.join(f"{a}={x}" for a, x in zip(c['axes'], c['key']))
        if b:
            print(f"  {i}. {lab} — n={b['n']} 적중 {b['hit']:.1f}% "
                  f"비용후 {b['net']:+.2f}%")
        else:
            print(f"  {i}. {lab} — 표본 0건")

    print('\n' + '=' * 70)
    if winners:
        c, v = winners[0]
        lab = ' & '.join(f"{a}={x}" for a, x in zip(c['axes'], c['key']))
        print(f"판정: 채택 후보 {len(winners)}개. 최상위 = {lab} "
              f"(검증 {v['hit']:.1f}%, n={v['n']})")
    else:
        print(f"판정: 채택 없음 — 검증 {TARGET_VALID_HIT}% 를 표본 "
              f"{MIN_VALID_N}건 이상으로 넘는 조건층이 없습니다.")
        print("     기준을 낮추거나 규칙을 다시 짜서 통과시키지 않습니다.")
    print('=' * 70)
    return 0 if winners else 1


if __name__ == '__main__':
    sys.exit(main())
