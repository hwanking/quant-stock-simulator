# -*- coding: utf-8 -*-
"""라운드 49 재측정 — 추천이 비추천보다 나은가 (라운드 110에 재실행).

■ 왜 다시 재나
  라운드 49 는 원장이 약 2만 건일 때 "순위에 정보가 없다"고 결론냈고,
  그 결론이 CLAUDE.md §9 에서 **로드맵 우선순위 전체**를 정하고 있다
  ("진입 타점·트레일링 스탑을 얹기 전에 점수 산식부터 다시 봐야 한다").

  지금 원장은 184,759건 — **9배**다. 개발 구간·판정완료만 166,132건,
  기준일 2,609일이다. 결론이 유지되는지 같은 잣대로 다시 잰다.

■ 무엇을 새로 정하지 않았나 (중요)
  판정 기준·집단 정의·지표·채택 조건을 **하나도 새로 만들지 않았다.**
  전부 docs/PREREG_R49_RANK_VALUE.md 에 적힌 그대로다. 측정 후 기준을
  내리지 않는다(§2).

    C:/Python314/python.exe scripts/rank_value_r49.py
"""
import collections
import io
import json
import math
import os
import sys
from datetime import date, datetime, timezone

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(PROJ, '.portfolio', 'virtual_graded.jsonl')
OUT = os.path.join(PROJ, 'data', 'rank_value_r49.json')

#: 사전등록 §3 — 비용후 EV = 평균 수익률 − 0.36%
COST = 0.36
#: 사전등록 §2 — 매수권 문턱 (채택된 값, 새 숫자 아님)
BUY = 58.0
#: 사전등록 §5 — 채택 조건 (측정 **전에** 고정된 값)
R1_MIN_PP = 5.0        # TOP5 목표선도달률 − 미추천 ≥ 5.0%p
R5_MIN_CASES = 300     # 각 집단 케이스 ≥ 300
R5_MIN_DATES = 100     # 각 집단 기준일 ≥ 100


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def wilson_low(k, n, z=1.96):
    if not n:
        return None
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return round((c - m) / d * 100, 1)


def load():
    """개발 구간(train+valid) · 판정완료만. **블라인드는 읽지 않는다**(§1).

    split=='blind' 가 신규 티커 블라인드(3,603)와 기존 티커 블라인드
    (8,000)를 **둘 다** 덮는다 — 실측으로 확인했다.
    """
    rows = []
    with open(LEDGER, encoding='utf-8', errors='replace') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:                                  # noqa: BLE001
                continue
            if r.get('split') not in ('train', 'valid'):
                continue                       # 봉인 준수
            if r.get('outcome') not in ('TARGET', 'STOP'):
                continue                       # 미결은 비교 불가
            if r.get('return_pct') is None or r.get('score') is None:
                continue
            rows.append(r)
    return rows


def stats(sub, base_ev=None):
    n = len(sub)
    if not n:
        return dict(n=0, dates=0, hit=None, wilson=None, ev=None, excess=None)
    k = sum(1 for r in sub if r.get('outcome') == 'TARGET')
    ev = sum(float(r['return_pct']) for r in sub) / n - COST
    return dict(
        n=n, dates=len({str(r.get('date'))[:10] for r in sub}),
        hit=round(k / n * 100, 2), wilson=wilson_low(k, n),
        ev=round(ev, 3),
        excess=(None if base_ev is None else round(ev - base_ev, 3)))


def run(min_per_day=0, label=''):
    """사전등록 §2 — **같은 날 안에서만** 순위를 매긴다.

    min_per_day 는 사전등록에 없다. 0 이 본 판정이고, 양수는 **민감도**로
    따로 낸다 (하루 종목이 적은 날이 섞이면 '상위5 vs 6위 이하' 가
    성립하지 않는 날이 생기기 때문 — 그 사실을 숨기지 않고 같이 낸다).
    """
    rows = load()
    by_day = collections.defaultdict(list)
    for r in rows:
        by_day[str(r.get('date'))[:10]].append(r)

    top1, top3, top5, rest_buy, allrows = [], [], [], [], []
    ties = 0
    for d, day in by_day.items():
        if len(day) < min_per_day:
            continue
        allrows.extend(day)
        # 점수 내림차순. 동점은 티커로 결정적으로 가른다 —
        # 선호를 지어내지 않되 실행마다 달라지지 않게 한다.
        ordered = sorted(day, key=lambda r: (-float(r['score']),
                                             str(r.get('ticker'))))
        if len(ordered) > 5:
            b = float(ordered[4]['score'])
            if any(float(r['score']) == b for r in ordered[5:]):
                ties += 1
        top1.extend(ordered[:1])
        top3.extend(ordered[:3])
        top5.extend(ordered[:5])
        rest_buy.extend([r for r in ordered[5:]
                         if float(r['score']) >= BUY])

    base = stats(allrows)
    g = {
        'TOP1': stats(top1, base['ev']),
        'TOP3': stats(top3, base['ev']),
        'TOP5': stats(top5, base['ev']),
        '후보 미추천': stats(rest_buy, base['ev']),
        '전체 비교군': base,
    }
    return g, ties, len(by_day)


def paired(min_per_day=0):
    """**같은 날 안에서** TOP5 와 6위 이하 매수권을 짝지어 비교한다.

    ⚠️ 합계 비교만 하면 날짜 집합이 다르다 — 실측으로 TOP5 는 2,609일,
      후보 미추천은 810일이었다(그날 매수권이 6종목 넘는 날만 미추천이
      생긴다). 서로 다른 날을 합쳐 비교하면 시장이 다른 것을 비교하게
      된다. 라운드 49 가 "158일치 짝지어" 비교한 이유다.

      두 집단이 **모두 있는 날**만 쓰고, 날짜를 표본 단위로 부호검정한다.
    """
    rows = load()
    by_day = collections.defaultdict(list)
    for r in rows:
        by_day[str(r.get('date'))[:10]].append(r)

    win = lose = tie = 0
    d_hit, d_ev = [], []
    for d, day in by_day.items():
        if len(day) < max(6, min_per_day):
            continue
        ordered = sorted(day, key=lambda r: (-float(r['score']),
                                             str(r.get('ticker'))))
        t5 = ordered[:5]
        rb = [r for r in ordered[5:] if float(r['score']) >= BUY]
        if not rb or not t5:
            continue
        a, b = stats(t5), stats(rb)
        if a['hit'] is None or b['hit'] is None:
            continue
        d_hit.append(a['hit'] - b['hit'])
        d_ev.append(a['ev'] - b['ev'])
        if a['hit'] > b['hit']:
            win += 1
        elif a['hit'] < b['hit']:
            lose += 1
        else:
            tie += 1

    n = win + lose
    z = None
    if n:
        z = (win - n / 2) / math.sqrt(n / 4)
    med_hit = (sorted(d_hit)[len(d_hit) // 2] if d_hit else None)
    med_ev = (sorted(d_ev)[len(d_ev) // 2] if d_ev else None)
    return dict(days=len(d_hit), win=win, lose=lose, tie=tie,
                sign_z=(round(z, 2) if z is not None else None),
                median_hit_diff=(round(med_hit, 2) if med_hit is not None
                                 else None),
                median_ev_diff=(round(med_ev, 3) if med_ev is not None
                                else None))


def judge(g):
    """사전등록 §5 — 조건을 **그대로** 적용한다. 내리지 않는다."""
    t5, rb, base = g['TOP5'], g['후보 미추천'], g['전체 비교군']
    out = {}
    out['R1 TOP5 적중 − 미추천 ≥ 5.0%p'] = (
        t5['hit'] is not None and rb['hit'] is not None
        and (t5['hit'] - rb['hit']) >= R1_MIN_PP)
    out['R2 TOP5 EV > 미추천 EV'] = (
        t5['ev'] is not None and rb['ev'] is not None and t5['ev'] > rb['ev'])
    out['R3 단조성 TOP1 ≥ TOP3 ≥ TOP5'] = (
        None not in (g['TOP1']['hit'], g['TOP3']['hit'], t5['hit'])
        and g['TOP1']['hit'] >= g['TOP3']['hit'] >= t5['hit'])
    out['R4 TOP5 초과수익 > 0'] = (
        t5['ev'] is not None and base['ev'] is not None
        and t5['ev'] - base['ev'] > 0)
    out['R5 표본 케이스≥300 · 날짜≥100'] = all(
        (g[k]['n'] >= R5_MIN_CASES and g[k]['dates'] >= R5_MIN_DATES)
        for k in ('TOP1', 'TOP3', 'TOP5', '후보 미추천'))
    return out


def show(g, ties, days, title):
    print(f'\n■ {title}  (기준일 {days:,}일 · 상위5 경계 동점 {ties:,}일)')
    print(f'{"집단":<12}{"케이스":>9}{"날짜":>7}{"적중":>8}{"Wilson":>8}'
          f'{"비용후EV":>10}{"초과":>8}')
    for k in ('TOP1', 'TOP3', 'TOP5', '후보 미추천', '전체 비교군'):
        c = g[k]
        print(f'{k:<12}{c["n"]:>9,}{c["dates"]:>7,}'
              f'{(f"{c["hit"]}%" if c["hit"] is not None else "—"):>8}'
              f'{(f"{c["wilson"]}" if c["wilson"] is not None else "—"):>8}'
              f'{(f"{c["ev"]:+.3f}" if c["ev"] is not None else "—"):>10}'
              f'{(f"{c["excess"]:+.3f}" if c.get("excess") is not None else "—"):>8}')


def main():
    print('라운드 49 재측정 — 사전등록 docs/PREREG_R49_RANK_VALUE.md 그대로')
    print('판정 기준·집단·지표를 하나도 새로 만들지 않았다.\n')

    g, ties, days = run(0, '본 판정')
    show(g, ties, days, '본 판정 (사전등록 그대로 — 모든 기준일)')
    verdict = judge(g)

    print('\n■ 채택 조건 (측정 전 고정)')
    for k, v in verdict.items():
        print(f'   [{"통과" if v else "미달"}] {k}')
    passed = all(verdict.values())
    print(f'\n>> {"전부 통과" if passed else "미달 있음"}')

    # 민감도 — 하루 종목이 적은 날이 섞이면 '상위5 vs 6위 이하'가
    # 성립하지 않는다. 사전등록에 없는 조건이므로 **따로** 낸다.
    g10, ties10, days10 = run(10, '민감도')
    show(g10, ties10, days10, '민감도 (하루 10종목 이상인 날만 — 사전등록 밖)')
    v10 = judge(g10)
    print('\n   민감도 판정: '
          + ' · '.join(f'{k.split()[0]}={"O" if v else "X"}'
                       for k, v in v10.items()))

    # 날짜별 짝비교 — 합계 비교의 날짜 불일치를 없앤다 (라운드 49 방식)
    pr = paired(0)
    print('\n■ 같은 날 안에서 짝지어 비교 (TOP5 vs 6위 이하 매수권)')
    print(f'   두 집단이 다 있는 날 {pr["days"]:,}일 · '
          f'TOP5 가 이긴 날 {pr["win"]:,} · 진 날 {pr["lose"]:,} · '
          f'같은 날 {pr["tie"]:,}')
    print(f'   부호검정 z = {pr["sign_z"]}  '
          f'(|z|>1.96 이면 유의)')
    print(f'   날짜별 적중률 차이 중앙 {pr["median_hit_diff"]}%p · '
          f'EV 차이 중앙 {pr["median_ev_diff"]}')

    doc = {
        'made': date.today().isoformat(),
        'paired': pr,
        'made_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'prereg': 'docs/PREREG_R49_RANK_VALUE.md',
        'basis': '개발 구간(train+valid) · 판정완료 · 블라인드 미사용',
        'ledger_rows': sum(1 for _ in open(LEDGER, encoding='utf-8',
                                           errors='replace')),
        'cost': COST, 'buy_zone': BUY,
        'primary': {k: v for k, v in g.items()},
        'primary_days': days, 'primary_boundary_ties': ties,
        'verdict': verdict, 'passed': passed,
        'sensitivity_min10': {k: v for k, v in g10.items()},
        'sensitivity_days': days10, 'sensitivity_verdict': v10,
        'note': ('관측 전용 — 점수·게이트·문턱을 바꾸지 않는다. '
                 '미달이면 기준을 내리지 않고 다음 라운드 과제로 적는다.'),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f'\n저장: {OUT}')
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
