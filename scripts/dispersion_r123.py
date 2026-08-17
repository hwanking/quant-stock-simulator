# -*- coding: utf-8 -*-
"""라운드 123 — 선택이 통하는 날은 따로 있는가 (횡단면 분산).

사전등록: docs/PREREG_R123_DISPERSION.md
**이 스크립트는 사전등록에 적힌 것만 한다.** 문턱을 훑지 않고,
조합을 만들지 않고, 결과를 보고 기준을 바꾸지 않는다.

■ 무엇을 재는가
  같은 날 안에서 상위5 vs 6위 이하의 적중률 차이를 R49 와 같은 방식으로
  구한다. 그 다음, 그날의 **횡단면 분산**이 높은 날과 낮은 날에서
  그 차이가 다른지 본다.

■ 이 스크립트가 하지 않는 것
  · 점수·게이트·문턱을 바꾸지 않는다.
  · 블라인드는 학습·검증에서 A1~A4 를 통과한 변수에만, 한 번 연다.

    C:/Python314/python.exe scripts/dispersion_r123.py
"""
from __future__ import annotations

import io
import json
import math
import os
import statistics as stat
import sys
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:                                              # noqa: BLE001
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

LEDGER = os.path.join(BASE, '.portfolio', 'virtual_graded.jsonl')
OUT = os.path.join(BASE, 'data', 'dispersion_r123.json')

#: 사전등록 §4 — 4변수 × 1검정, Bonferroni 0.05/4 → z=2.4977 → **올림 2.50**
Z_CRIT = 2.50
TOPN = 5                     # R49 와 같은 '상위5'
MIN_DAYS = 300               # A4 — 각 3분위 날짜
MIN_CASES = 3000             # A4 — 각 3분위 케이스
MIN_EFFECT_PP = 5.0          # A3 — 중앙값 격차
VARS = ('disp', 'disp_iqr', 'breadth', 'corr')


def load(splits):
    rows = []
    with open(LEDGER, encoding='utf-8') as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:                                  # noqa: BLE001
                continue
            if r.get('success') is None or not r.get('date'):
                continue
            if r.get('split') not in splits:
                continue
            if r.get('score') is None:
                continue
            rows.append(r)
    return rows


def day_vars(rows_of_day):
    """그날의 횡단면 구조 — **그날 자료만** 쓴다 (결과를 안 본다).

    원장에 그날 추천 후보들의 당일 수익률이 직접 있지는 않다.
    대신 같은 날 케이스들의 `close_return_pct`(보유기간 종가수익)는
    **미래 정보**이므로 절대 쓰지 않는다.
    쓸 수 있는 것은 추천 시점에 이미 확정된 값뿐이다:
      · vol20     — 20일 변동성 (그날까지의 값)
      · range_pos — 그날 종가의 20일 레인지 내 위치
      · rsi · bb_pos — 그날까지의 값
    분산은 **그날 후보들 사이의 흩어짐**으로 잰다.
    """
    def col(k):
        return [float(r[k]) for r in rows_of_day
                if r.get(k) is not None]

    out = {}
    rp = col('range_pos')          # 0~100, 그날 위치
    v20 = col('vol20')
    bb = col('bb_pos')
    rsi = col('rsi')

    # ① disp — 그날 후보들의 위치가 얼마나 흩어졌나 (표준편차)
    out['disp'] = stat.pstdev(rp) if len(rp) >= 3 else None
    # ② disp_iqr — 같은 것을 IQR 로 (꼬리에 안 휘둘리는 대조)
    if len(rp) >= 4:
        q = stat.quantiles(rp, n=4)
        out['disp_iqr'] = q[2] - q[0]
    else:
        out['disp_iqr'] = None
    # ③ breadth — 강세(RSI>50) 비율의 0.5 에서의 거리 = 쏠림
    out['breadth'] = (abs(sum(1 for x in rsi if x > 50) / len(rsi) - 0.5)
                      if len(rsi) >= 3 else None)
    # ④ corr — 같이 움직임 근사: 개별 변동성 평균이 작을수록(=흩어짐이
    #    적을수록) 같이 움직인 것으로 본다. bb_pos 분산으로 잰다.
    out['corr'] = (1.0 - min(1.0, stat.pstdev(bb) / 50.0)
                   if len(bb) >= 3 else None)
    return out


def day_edge(rows_of_day):
    """그날 상위5 vs 6위 이하 적중률 차이(%p). R49 와 같은 방식."""
    if len(rows_of_day) < TOPN + 3:
        return None
    srt = sorted(rows_of_day, key=lambda r: -(r.get('score') or 0))
    top, rest = srt[:TOPN], srt[TOPN:]
    if not rest:
        return None
    ht = 100.0 * sum(1 for r in top if r['success']) / len(top)
    hr = 100.0 * sum(1 for r in rest if r['success']) / len(rest)
    return ht - hr


def mannwhitney_z(a, b):
    """정규근사 U 검정 z (동점 보정 포함)."""
    na, nb = len(a), len(b)
    if na < 10 or nb < 10:
        return None
    merged = sorted([(v, 0) for v in a] + [(v, 1) for v in b])
    ranks, i, ties = [0.0] * len(merged), 0, []
    while i < len(merged):
        j = i
        while j + 1 < len(merged) and merged[j + 1][0] == merged[i][0]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[k] = avg
        ties.append(j - i + 1)
        i = j + 1
    ra = sum(ranks[k] for k in range(len(merged)) if merged[k][1] == 0)
    u = ra - na * (na + 1) / 2.0
    mu = na * nb / 2.0
    n = na + nb
    corr = sum(t ** 3 - t for t in ties)
    var = na * nb / 12.0 * ((n + 1) - corr / (n * (n - 1)))
    if var <= 0:
        return None
    return (u - mu) / math.sqrt(var)


def run(splits, label):
    rows = load(splits)
    by_day = defaultdict(list)
    for r in rows:
        by_day[str(r['date'])[:10]].append(r)

    days = {}
    for d, rs in by_day.items():
        e = day_edge(rs)
        if e is None:
            continue
        v = day_vars(rs)
        days[d] = {'edge': e, 'n': len(rs), **v}

    print(f'\n■ {label} — 날짜 {len(days):,}일 · 케이스 '
          f'{sum(x["n"] for x in days.values()):,}건')
    if len(days) < 30:
        print('  날짜가 너무 적다 — 판정하지 않는다.')
        return {}

    res = {}
    for var in VARS:
        vals = [(x[var], d) for d, x in days.items() if x.get(var) is not None]
        if len(vals) < 60:
            print(f'  {var:10s} 표본 부족 ({len(vals)}일) — 판정 불가')
            res[var] = {'verdict': '판정 불가', 'days': len(vals)}
            continue
        vals.sort()
        cut = len(vals) // 3
        lo_d = [d for _, d in vals[:cut]]
        hi_d = [d for _, d in vals[-cut:]]
        lo = [days[d]['edge'] for d in lo_d]
        hi = [days[d]['edge'] for d in hi_d]
        lo_n = sum(days[d]['n'] for d in lo_d)
        hi_n = sum(days[d]['n'] for d in hi_d)
        z = mannwhitney_z(hi, lo)
        med_gap = stat.median(hi) - stat.median(lo)

        a1 = z is not None and abs(z) >= Z_CRIT
        a2 = med_gap > 0
        a3 = abs(med_gap) >= MIN_EFFECT_PP
        a4 = (len(lo_d) >= MIN_DAYS and len(hi_d) >= MIN_DAYS
              and lo_n >= MIN_CASES and hi_n >= MIN_CASES)
        ok = a1 and a2 and a3 and a4
        res[var] = {
            'z': None if z is None else round(z, 3),
            'median_gap_pp': round(med_gap, 2),
            'days_low': len(lo_d), 'days_high': len(hi_d),
            'cases_low': lo_n, 'cases_high': hi_n,
            'A1_z': a1, 'A2_direction': a2, 'A3_effect': a3, 'A4_sample': a4,
            'verdict': '통과' if ok else '미달',
        }
        print(f"  {var:10s} z={'  —  ' if z is None else f'{z:+6.3f}'}"
              f"  중앙값격차 {med_gap:+6.2f}%p"
              f"  날짜 {len(lo_d)}/{len(hi_d)}"
              f"  케이스 {lo_n:,}/{hi_n:,}"
              f"  → {res[var]['verdict']}"
              f"  (A1 {'O' if a1 else 'X'} A2 {'O' if a2 else 'X'} "
              f"A3 {'O' if a3 else 'X'} A4 {'O' if a4 else 'X'})")
    return res


def main():
    print('=' * 74)
    print('라운드 123 — 선택이 통하는 날은 따로 있는가 (횡단면 분산)')
    print(f'사전등록 문턱 z={Z_CRIT} (0.05/4 올림) · 효과 {MIN_EFFECT_PP}%p · '
          f'날짜 {MIN_DAYS}일 · 케이스 {MIN_CASES:,}건')
    print('=' * 74)

    dev = run(('train', 'valid'), '개발 구간 (학습+검증)')
    passed = [v for v, r in dev.items() if r.get('verdict') == '통과']

    blind = {}
    if passed:
        print(f'\n개발에서 통과한 변수 {passed} — 블라인드를 **한 번** 연다')
        blind = run(('blind',), '블라인드')
    else:
        print('\n개발 구간에서 통과한 변수가 없다 — '
              '블라인드를 열지 않는다 (사전등록 §6).')

    adopt = [v for v in passed
             if blind.get(v, {}).get('A2_direction')
             and blind.get(v, {}).get('z') is not None
             and abs(blind[v]['z']) >= 1.96]

    print('\n' + '=' * 74)
    if adopt:
        print(f'판정: 조건부 통과 — {adopt}')
        print('  ※ 채택되어도 2026-11-16 이전에는 엔진에 넣지 않는다.')
    else:
        print('판정: 기각 — 현행 유지. 화면에 아무것도 넣지 않는다.')
    print('  ※ 이 잣대는 5%p 미만의 효과를 보지 못한다 (R113).')
    print('=' * 74)

    import datetime as _dt
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump({'measured_at': _dt.date.today().isoformat(),
                   'z_crit': Z_CRIT, 'min_effect_pp': MIN_EFFECT_PP,
                   'min_days': MIN_DAYS, 'min_cases': MIN_CASES,
                   'dev': dev, 'blind': blind, 'adopted': adopt,
                   'note': '표시·연구 전용. 점수·게이트·문턱을 바꾸지 않는다.'},
                  f, ensure_ascii=False, indent=1)
    print(f'저장: {OUT}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
