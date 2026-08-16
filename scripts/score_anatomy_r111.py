# -*- coding: utf-8 -*-
"""라운드 111 — 순위 정보가 어디서 사라지는가 (관측 전용).

사전등록: docs/PREREG_R111_SCORE_ANATOMY.md — **먼저 저장·커밋됐다.**

라운드 110 이 종합점수 순위에 정보가 없음을 8배 표본에서 확인했다.
여기서는 **재료(하위점수 7종)에도 없는지**를 같은 잣대로 잰다.
  · 재료에 있는데 합산이 죽이면  → 가중치·합산 방식 문제
  · 재료에도 없으면              → 새 재료가 필요하다
처방이 다르므로 구분해야 한다. **산식은 바꾸지 않는다** (11/16 동결).

    C:/Python314/python.exe scripts/score_anatomy_r111.py
"""
import collections
import glob
import io
import json
import math
import os
import sys
from datetime import date, datetime, timezone

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(PROJ, '.portfolio')
OUT = os.path.join(PROJ, 'data', 'score_anatomy_r111.json')

COST = 0.36            # 사전등록 §3 (라운드 49 와 같음)
BUY = 58.0             # 채택된 매수권 문턱
#: 사전등록 §4 — Bonferroni: 0.05 / 8 기준 → |z| ≥ 2.73
Z_CRIT = 2.73
N_TESTS = 8
#: 사전등록 §5 A3 — 라운드 49 의 R5 재사용 (새 숫자 아님)
MIN_CASES, MIN_DATES = 300, 100

QKEYS = ('q_stock_quality', 'q_trading_timing', 'q_risk_safety',
         'q_opportunity', 'q_execution', 'q_confidence',
         'q_strategy_quality')


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def load():
    """개발 구간·판정완료 + **하위점수 패치 합류** (라운드 99 교훈).

    원장만 읽으면 하위점수가 반쪽이다 — 옛 케이스는 백필로 뒤에 채웠고
    병합 단계가 없다.
    """
    patch = {}
    for p in sorted(glob.glob(os.path.join(P, 'subscore_patch*.jsonl'))):
        with open(p, encoding='utf-8', errors='replace') as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    q = json.loads(ln)
                except Exception:                              # noqa: BLE001
                    continue
                patch[(str(q.get('ticker')), str(q.get('date'))[:10])] = q

    rows = []
    with open(os.path.join(P, 'virtual_graded.jsonl'),
              encoding='utf-8', errors='replace') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:                                  # noqa: BLE001
                continue
            if r.get('split') not in ('train', 'valid'):
                continue                       # 봉인 준수 (§1)
            if r.get('outcome') not in ('TARGET', 'STOP'):
                continue
            if r.get('return_pct') is None or r.get('score') is None:
                continue
            q = patch.get((str(r.get('ticker')), str(r.get('date'))[:10]))
            if q:
                for k in QKEYS:
                    if r.get(k) is None and q.get(k) is not None:
                        r[k] = q[k]
            rows.append(r)
    return rows


def hit_ev(sub):
    n = len(sub)
    if not n:
        return None, None
    k = sum(1 for r in sub if r.get('outcome') == 'TARGET')
    ev = sum(float(r['return_pct']) for r in sub) / n - COST
    return k / n * 100.0, ev


def paired_by(rows, key):
    """`key` 로 같은 날 순위를 매겨 상위5 vs 6위 이하 매수권을 짝비교."""
    by_day = collections.defaultdict(list)
    for r in rows:
        if r.get(key) is None:
            continue
        by_day[str(r.get('date'))[:10]].append(r)

    win = lose = tie = 0
    d_hit, d_ev, n_top, n_rest, ties_edge = [], [], 0, 0, 0
    for d, day in by_day.items():
        if len(day) < 6:
            continue
        ordered = sorted(day, key=lambda r: (-float(r[key]),
                                             str(r.get('ticker'))))
        t5 = ordered[:5]
        rb = [r for r in ordered[5:] if float(r.get('score') or 0) >= BUY]
        if not rb:
            continue
        b = float(ordered[4][key])
        if any(float(r[key]) == b for r in ordered[5:]):
            ties_edge += 1
        n_top += len(t5)
        n_rest += len(rb)
        ha, ea = hit_ev(t5)
        hb, eb = hit_ev(rb)
        if ha is None or hb is None:
            continue
        d_hit.append(ha - hb)
        d_ev.append(ea - eb)
        if ha > hb:
            win += 1
        elif ha < hb:
            lose += 1
        else:
            tie += 1

    n = win + lose
    z = ((win - n / 2) / math.sqrt(n / 4)) if n else None
    med = (sorted(d_hit)[len(d_hit) // 2] if d_hit else None)
    med_ev = (sorted(d_ev)[len(d_ev) // 2] if d_ev else None)
    return dict(
        days=len(d_hit), win=win, lose=lose, tie=tie,
        sign_z=(round(z, 2) if z is not None else None),
        median_hit_diff=(round(med, 2) if med is not None else None),
        median_ev_diff=(round(med_ev, 3) if med_ev is not None else None),
        n_top=n_top, n_rest=n_rest,
        boundary_tie_days=ties_edge,
        tie_rate=(round(ties_edge / max(1, len(by_day)) * 100, 1)))


def judge(p):
    """사전등록 §5 — 그대로 적용한다."""
    return {
        'A1 z ≥ +2.73 (Bonferroni)': (p['sign_z'] is not None
                                      and p['sign_z'] >= Z_CRIT),
        'A2 적중률 차이 중앙값 > 0': (p['median_hit_diff'] is not None
                                and p['median_hit_diff'] > 0),
        'A3 표본 (케이스≥300 · 날짜≥100)': (p['n_top'] >= MIN_CASES
                                       and p['days'] >= MIN_DATES),
    }


def granularity(rows, key):
    """점수의 분해능 — 판정 기준이 아니라 서술 (사전등록 §3)."""
    vals = [float(r[key]) for r in rows if r.get(key) is not None]
    if not vals:
        return dict(n=0)
    uniq = sorted(set(vals))
    top = [v for v in uniq if v >= BUY]
    return dict(n=len(vals), distinct=len(uniq),
                min=round(uniq[0], 2), max=round(uniq[-1], 2),
                distinct_in_buyzone=len(top))


def main():
    print('라운드 111 — 순위 정보가 어디서 사라지는가')
    print('사전등록: docs/PREREG_R111_SCORE_ANATOMY.md (측정 전 커밋)\n')
    rows = load()
    print(f'개발 구간·판정완료 {len(rows):,}건 · '
          f'기준일 {len({str(r.get("date"))[:10] for r in rows}):,}일')
    have = {k: sum(1 for r in rows if r.get(k) is not None) for k in QKEYS}
    print(f'하위점수 보유: '
          + ' · '.join(f'{k.replace("q_", "")} {v:,}' for k, v in have.items()))

    keys = [('score', '종합점수 (대조군)')] + [(k, k.replace('q_', ''))
                                          for k in QKEYS]
    res, verd = {}, {}
    print(f'\n{"기준":<20}{"날짜":>7}{"이김":>7}{"짐":>7}{"z":>8}'
          f'{"적중차중앙":>11}{"EV차중앙":>10}{"동점일":>8}')
    for k, label in keys:
        p = paired_by(rows, k)
        res[k] = p
        verd[k] = judge(p)
        print(f'{label:<20}{p["days"]:>7,}{p["win"]:>7,}{p["lose"]:>7,}'
              f'{(f"{p["sign_z"]:+.2f}" if p["sign_z"] is not None else "—"):>8}'
              f'{(f"{p["median_hit_diff"]:+.2f}%p" if p["median_hit_diff"] is not None else "—"):>11}'
              f'{(f"{p["median_ev_diff"]:+.3f}" if p["median_ev_diff"] is not None else "—"):>10}'
              f'{p["tie_rate"]:>7.1f}%')

    print(f'\n■ 채택 조건 (측정 전 고정 · Bonferroni |z| ≥ {Z_CRIT})')
    passed = [k for k, v in verd.items() if all(v.values())]
    for k, label in keys:
        v = verd[k]
        print(f'   {label:<20} '
              + ' · '.join(f'{n.split()[0]}={"O" if ok else "X"}'
                           for n, ok in v.items()))
    print(f'\n>> 통과한 기준: {passed if passed else "없음"}')

    gran = {k: granularity(rows, k) for k, _ in keys}
    print('\n■ 분해능 (서술 — 판정 기준 아님)')
    for k, label in keys:
        g = gran[k]
        print(f'   {label:<20} 서로 다른 값 {g.get("distinct", 0):>6,}개 · '
              f'매수권 안 {g.get("distinct_in_buyzone", 0):>5,}개 · '
              f'범위 {g.get("min")}~{g.get("max")}')

    doc = {
        'made': date.today().isoformat(),
        'made_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'prereg': 'docs/PREREG_R111_SCORE_ANATOMY.md',
        'basis': '개발 구간(train+valid) · 판정완료 · 블라인드 미사용',
        'cost': COST, 'buy_zone': BUY,
        'z_crit': Z_CRIT, 'n_tests': N_TESTS,
        'min_cases': MIN_CASES, 'min_dates': MIN_DATES,
        'n_rows': len(rows), 'subscore_coverage': have,
        'paired': res, 'verdict': verd, 'passed': passed,
        'granularity': gran,
        'note': ('관측 전용 — 점수·게이트·문턱을 바꾸지 않는다. '
                 '통과한 기준이 있어도 2026-11-16 이후 사전등록의 '
                 '후보 목록으로만 쓴다.'),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f'\n저장: {OUT}')
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
