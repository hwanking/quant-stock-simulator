# -*- coding: utf-8 -*-
"""라운드 129 — 과거 표본을 늘리면 무엇이 보이게 되나 (상한 계산).

R113 은 **지금 표본에서** 최소 가시 효과가 5~8%p 라고 쟀다.
그 다음 질문이 이것이다 — "미래를 기다리지 말고 과거를 더 쌓으면?"

결정을 바꾸지 않는다. 점수·게이트·문턱을 손대지 않는다.
자원을 어디에 쓸지 고르기 위한 **관측**이고, 세 가지를 가른다:

  ① 종목을 늘리면 짝비교 날짜가 느나  (실측 — 줄여서 곡선을 그린다)
  ② 810일에서 막히는 게 데이터 부족인가 잣대 구조인가
  ③ 어떤 크기의 효과를 보려면 날짜가 몇 일 필요한가

---------------------------------------------------------------------------
③에서 **첫 시도가 자기검사에 걸렸다. 그 자리를 지운다.**

처음엔 필요 날짜를 닫힌 식으로 내고, 그 식이 R113 시뮬레이션과 맞는지
대조했다. 최대 괴리가 19.9%p 로 허용(8%p)을 크게 넘었다.

원인은 **둘이 다른 것을 재고 있었다**는 것이다:

  · R113 시뮬 — 관측된 810일을 **고정**하고 주입 난수만 굴린다.
    그날의 (k, s, hb) 가 붙박이라 대부분의 날은 결과가 정해져 있고,
    z 의 흩어짐이 이론값보다 훨씬 좁다. **"이 810일에서" 의 검정력**
  · 닫힌 식 — 날짜가 매번 새로 뽑히는 것을 전제한다.
    **"이런 날을 N일 모으면" 의 검정력**

우리가 묻는 것은 뒤쪽이다("더 모으면"). 그래서 식이 아니라 **잣대를
고쳤다** — 날짜를 복원추출로 다시 뽑는다(부트스트랩). 그러면 날짜가 iid
가 되어 이긴 날 수가 이항분포를 정확히 따르고, 필요 N 이 닫힌 식으로
나온다. 그리고 그 식을 **부트스트랩으로 되짚어** 확인한다.

    z = sqrt(n) * (2p - 1),   n = 결정난 날짜(동점 제외) = f * N
    검정력 80%:  sqrt(f*N) * (2p-1) >= t + 0.8416
    => N >= ((t + 0.8416) / (2p - 1))**2 / f

p 와 f 는 난수 없이 **정확히** 구한다 — 상위5 중 미적중 s 개를 확률 q 로
뒤집는 것은 이항분포이고 s 는 0~5 라 전개가 끝난다.

자기검사 셋을 통과해야 숫자를 쓴다 (실패하면 종료 코드 1):
  ⓐ 거짓양성률 — 그날 결과를 섞은 귀무에서 z>=1.96 이 2.5% 근처인가
  ⓑ 되짚기 — 식이 낸 "필요 N" 에서 부트스트랩 검정력이 정말 80% 근처인가
  ⓒ 단조 — N 이 늘면 검정력이 늘고, 효과가 크면 필요 N 이 준다

    C:/Python314/python.exe scripts/sample_ceiling_r129.py
"""
import collections
import io
import json
import math
import os
import random
import sys
from datetime import date, datetime, timezone

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJ, 'scripts'))
OUT = os.path.join(PROJ, 'data', 'sample_ceiling_r129.json')

import power_r113 as P                                          # noqa: E402

SEED = 129
BOOT = 600                              # 자기검사용 부트스트랩 반복
DELTAS = (1, 2, 3, 4, 5, 8)
Z80 = 0.8416                            # 정규분포 80% 분위
#: R111·R112 가 실제로 쓴 문턱. 보정 없는 1.96 은 R112 가 "증거가 아니다"
#: 라고 보인 자리라 참고로만 싣는다
THRESHOLDS = (('보정없음', 1.96), ('R112보정', 2.9552))
#: ⓑ 되짚기 허용 오차 — 부트스트랩 600회면 검정력 추정의 표준오차가 최대
#: 2.0%p. 그 세 배를 넘게 벌어지면 식이 틀린 것으로 본다
TOL = 0.06
#: ⓐ 거짓양성률이 이 범위 밖이면 아래 숫자를 못 믿는다
FPR_RANGE = (0.005, 0.06)


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def frame_probs(frames, q):
    """난수 없이 정확히 — (이긴날 확률 p, 결정난 비율 f).

    상위5 중 미적중 s 개를 각각 확률 q 로 적중으로 뒤집으면 뒤집힌 수는
    이항분포다. s 는 0~5 라 전부 펼칠 수 있다. 시뮬레이션이 필요 없다.
    """
    win = lose = 0.0
    for k, s, hb in frames:
        for j in range(s + 1):
            pr = (math.comb(s, j) * (q ** j) * ((1 - q) ** (s - j))
                  if s else (1.0 if j == 0 else 0.0))
            if pr <= 0:
                continue
            ha = (k + j) * 20.0                 # (k+j)/5*100
            if ha > hb:
                win += pr
            elif ha < hb:
                lose += pr
    n = len(frames)
    dec = (win + lose) / n
    return ((win / (win + lose)) if (win + lose) else 0.0), dec


def need_days(p, f, t):
    """검정력 80% 를 넘는 최소 **전체 날짜 수**. 효과 방향이 없으면 None."""
    if 2 * p - 1 <= 0 or f <= 0:
        return None
    return ((t + Z80) / (2 * p - 1)) ** 2 / f


def boot_power(p, f, days, t, rng, repeats=BOOT):
    """날짜를 복원추출로 N일 뽑았을 때의 검정력 — 식을 되짚는 잣대."""
    days = int(round(days))
    if days < 1:
        return 0.0
    hit = 0
    for _ in range(repeats):
        dec = rng.binomialvariate(days, f)
        if not dec:
            continue
        w = rng.binomialvariate(dec, p)
        if (w - dec / 2) / math.sqrt(dec / 4) >= t:
            hit += 1
    return hit / repeats


def null_fpr(rows, t, rng, repeats=BOOT):
    """ⓐ 그날 결과를 섞은 귀무에서 z>=t 가 얼마나 나오나 (R113 과 같은 방식)."""
    nf = P.null_frames(rows, 'score')
    hit = 0
    for _ in range(repeats):
        z = P.null_z(nf, rng)
        if z is not None and z >= t:
            hit += 1
    return hit / repeats, len(nf)


def trading_days_per_year(dates):
    """관측된 가장 촘촘한 해들로 연간 거래일을 **유도**한다.

    245 같은 숫자를 손으로 적지 않는다 — 우리 데이터가 이미 알고 있다.
    """
    per = collections.Counter(d[:4] for d in dates)
    full = sorted(per.values())[-6:]          # 촘촘한 상위 6개 해
    return sum(full) / len(full)


def main():
    print('라운드 129 — 과거 표본을 늘리면 무엇이 보이게 되나')
    print('관측 전용 — 점수·게이트·문턱을 바꾸지 않는다')
    print()

    rows = P.load()
    by_day = collections.defaultdict(list)
    for r in rows:
        by_day[str(r.get('date'))[:10]].append(r)
    dates = sorted(by_day)
    print(f'개발 구간·판정완료 {len(rows):,}건 · 날짜 {len(dates):,}일 '
          f'({dates[0]} ~ {dates[-1]})')

    # ── ② 짝비교가 막히는 정체 ──────────────────────────────────
    n_six = sum(1 for d in by_day.values() if len(d) >= 6)
    lost = collections.Counter()
    for d, day in by_day.items():
        if len(day) < 6:
            continue
        o = sorted(day, key=lambda r: (-float(r['score']),
                                       str(r.get('ticker'))))
        rest = [r for r in o[5:] if float(r.get('score') or 0) >= P.BUY]
        if not rest:
            lost[sum(1 for r in day
                     if float(r.get('score') or 0) >= P.BUY)] += 1
    n_lost = sum(lost.values())
    print()
    print('■ ② 짝비교 날짜가 막히는 정체')
    print(f'   날짜 {len(dates):,}일 -> 6종목 이상 {n_six:,}일 '
          f'-> 대조군까지 남는 날 {n_six - n_lost:,}일')
    print(f'   여기서 탈락 {n_lost:,}일 — 전부 그날 매수권이 '
          f'{max(lost) if lost else 0}종목 이하라 상위5를 떼면 대조군이 빈다')
    print('   -> 절반은 데이터가 아니라 잣대 구조다. '
          '상위5가 자기 대조군을 먹는다.')

    # ── ① 종목을 늘리면 날짜가 느나 (줄여서 곡선) ────────────────
    cnt = collections.Counter(r.get('ticker') for r in rows)
    order = [t for t, _ in sorted(cnt.items(), key=lambda x: (-x[1], x[0]))]
    print()
    print(f'■ ① 종목 축 — 줄여서 곡선을 그린다 (전체 {len(order):,}개)')
    curve = []
    for frac in (0.25, 0.50, 0.75, 1.00):
        keep = set(order[:max(1, int(len(order) * frac))])
        sub = [r for r in rows if r.get('ticker') in keep]
        d = len(P.day_frames(sub, 'score'))
        curve.append(dict(frac=frac, tickers=len(keep), cases=len(sub),
                          paired_days=d))
        print(f'   종목 {len(keep):>5,}개 ({frac * 100:>3.0f}%) -> '
              f'케이스 {len(sub):>7,}건 · 짝비교 {d:>4,}일')
    gain = curve[-1]['paired_days'] - curve[-2]['paired_days']
    add = curve[-1]['tickers'] - curve[-2]['tickers']
    print(f'   -> 마지막 {add:,}종목이 벌어들인 날짜 {gain}일. '
          f'첫 {curve[0]["tickers"]:,}종목은 {curve[0]["paired_days"]:,}일을 '
          '벌었다 — 포화다.')

    # ── ③ 어떤 크기를 보려면 날짜가 몇 일 필요한가 ───────────────
    frames = P.day_frames(rows, 'score')
    have = len(frames)
    tot = sum(k + s for k, s, _ in frames)
    p_stop = sum(s for _, s, _ in frames) / tot
    print()
    print(f'■ ③ 그 크기를 보려면 날짜가 몇 일 필요한가 '
          f'(지금 {have:,}일 · 상위5 미적중률 {p_stop * 100:.1f}%)')
    head = f'   {"차이(%p)":>9}{"이긴날 p":>10}{"결정 f":>9}'
    for name, _ in THRESHOLDS:
        head += f'{name + " 필요":>16}'
    print(head)

    rng = random.Random(SEED)
    need, checks = {}, []
    for dpp in DELTAS:
        q = (dpp / 100.0) / p_stop
        if q > 1.0:
            need[dpp] = dict(note='미적중을 다 뒤집어도 부족')
            continue
        p, f = frame_probs(frames, q)
        row = dict(q=round(q, 4), p=round(p, 4), f=round(f, 4))
        line = f'   {dpp:>9}{p:>10.4f}{f:>9.3f}'
        for name, t in THRESHOLDS:
            N = need_days(p, f, t)
            row[name] = round(N) if N else None
            line += (f'{N:>14,.0f}일' if N else f'{"불가":>16}')
            if N and N <= 200_000:          # ⓑ 되짚기 (너무 큰 N 은 생략)
                got = boot_power(p, f, N, t, rng)
                checks.append(dict(delta=dpp, threshold=name, days=round(N),
                                   target=0.80, got=round(got, 3),
                                   gap=round(abs(got - 0.80), 3)))
        need[dpp] = row
        print(line)
    for dpp in DELTAS:
        if 'note' in need[dpp]:
            print(f'   {dpp:>9}  {need[dpp]["note"]}')

    # ── 자기검사 ────────────────────────────────────────────────
    print()
    print('■ 자기검사 — 통과해야 위 숫자를 쓴다')

    # ⓐ 거짓양성률
    fpr, n_null = null_fpr(rows, 1.96, random.Random(SEED * 7919))
    ok_a = FPR_RANGE[0] <= fpr <= FPR_RANGE[1]
    print(f'   ⓐ 거짓양성률 — 그날 결과를 섞은 귀무({n_null:,}일)에서 '
          f'z>=1.96 이 {fpr * 100:.1f}% '
          f'({"정상" if ok_a else "이상"} · 허용 '
          f'{FPR_RANGE[0] * 100:.1f}~{FPR_RANGE[1] * 100:.0f}%)')

    # ⓑ 되짚기
    worst = max(checks, key=lambda x: x['gap']) if checks else None
    ok_b = bool(checks) and worst['gap'] <= TOL
    print(f'   ⓑ 되짚기 — 식이 낸 "필요 N" 에서 부트스트랩 검정력 '
          f'({len(checks)}쌍)')
    for c in checks:
        print(f'      {c["delta"]}%p {c["threshold"]:<9} '
              f'{c["days"]:>7,}일 -> {c["got"] * 100:>5.1f}% '
              f'(목표 80.0% · 차 {c["gap"] * 100:.1f}%p)')
    print(f'      최대 괴리 {worst["gap"] * 100:.1f}%p — '
          f'{"정상" if ok_b else "이상 — 위 필요날짜를 쓰지 말 것"} '
          f'(허용 {TOL * 100:.0f}%p)')

    # ⓒ 단조
    seq = [need[d].get('R112보정') for d in DELTAS
           if need.get(d, {}).get('R112보정')]
    ok_c1 = all(a > b for a, b in zip(seq, seq[1:]))
    p5, f5 = frame_probs(frames, (5 / 100.0) / p_stop)
    ramp = [boot_power(p5, f5, n, 2.9552, random.Random(SEED + n))
            for n in (400, 800, 1600, 3200)]
    ok_c2 = all(a <= b for a, b in zip(ramp, ramp[1:]))
    ok_c = ok_c1 and ok_c2
    print(f'   ⓒ 단조 — 효과가 크면 필요 N 이 준다 '
          f'({"예" if ok_c1 else "아니오"}) · '
          f'N 이 늘면 검정력이 는다 '
          f'({" -> ".join(f"{x * 100:.0f}%" for x in ramp)}) '
          f'{"정상" if ok_c else "이상"}')

    ok = ok_a and ok_b and ok_c

    # ── 물리 상한 ───────────────────────────────────────────────
    tpy = trading_days_per_year(dates)
    y0, y1 = dates[0][:4], dates[-1][:4]
    span = (datetime.strptime(dates[-1], '%Y-%m-%d')
            - datetime.strptime(dates[0], '%Y-%m-%d')).days / 365.25
    ceiling = tpy * span
    print()
    print('■ 물리 상한 — 과거를 끝까지 채우면')
    print(f'   연간 거래일 {tpy:.0f}일 (촘촘한 해들에서 유도) x '
          f'{span:.1f}년 ({y0}~{y1}) = 약 {ceiling:,.0f}일')
    print(f'   지금 {have:,}일 -> 상한 {ceiling:,.0f}일 '
          f'({ceiling / have:.1f}배)')
    print('   ※ 날짜 칸의 상한이지 그 날들을 다 채울 수 있다는 말이 아니다. '
          '상한까지 간다는 것은 2011년까지 매 거래일 매수권 6종목 이상을 '
          '확보한다는 뜻이다.')

    verdict = {}
    for name, t in THRESHOLDS:
        got = next((d for d in DELTAS
                    if need.get(d, {}).get(name)
                    and need[d][name] <= ceiling), None)
        verdict[name] = got
        print(f'   {name}: 과거를 다 채워도 볼 수 있는 최소 효과 = '
              + (f'{got}%p' if got else f'{max(DELTAS)}%p 로도 부족'))

    doc = {
        'made': date.today().isoformat(),
        'made_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'basis': '개발 구간(train+valid) · 판정완료 · 블라인드 미사용',
        'question': ('미래 전방 표본을 기다리지 않고 과거 표본을 늘리면 '
                     '무엇이 보이게 되는가'),
        'seed': SEED, 'boot': BOOT, 'deltas': list(DELTAS),
        'thresholds': {n: t for n, t in THRESHOLDS},
        'ledger': dict(cases=len(rows), dates=len(dates),
                       first=dates[0], last=dates[-1],
                       tickers=len(order)),
        'structure': dict(dates=len(dates), six_plus=n_six,
                          paired=n_six - n_lost, lost=n_lost,
                          lost_by_buyzone={str(k): v
                                           for k, v in sorted(lost.items())}),
        'ticker_curve': curve,
        'need_days': {str(k): v for k, v in need.items()},
        'selfcheck': dict(
            fpr=dict(rate=round(fpr, 4), days=n_null,
                     allow=list(FPR_RANGE), ok=ok_a),
            recover=dict(pairs=checks, tolerance=TOL,
                         worst_gap=worst['gap'] if worst else None, ok=ok_b),
            monotone=dict(need_decreasing=ok_c1,
                          power_ramp=[round(x, 3) for x in ramp], ok=ok_c),
            ok=ok),
        'ceiling': dict(trading_days_per_year=round(tpy, 1),
                        span_years=round(span, 1),
                        max_dates=round(ceiling),
                        have=have, multiple=round(ceiling / have, 2)),
        'visible_at_ceiling': verdict,
        'method_note': ('첫 시도는 닫힌 식을 R113 의 고정 프레임 '
                        '시뮬레이션과 대조했고 최대 괴리 19.9%p 로 '
                        '자기검사에 걸렸다. 둘이 다른 것을 재고 있었다 — '
                        'R113 은 "이 810일에서", 식은 "이런 날을 N일 '
                        '모으면" 이다. 우리가 묻는 것은 뒤쪽이라 잣대를 '
                        '부트스트랩으로 바꿨다. 기준을 내리지 않고 '
                        '재려던 것을 제대로 쟀다.'),
        'note': ('관측 전용 — 점수·게이트·문턱을 바꾸지 않는다. '
                 '잣대(짝비교 규칙)를 바꾸는 것은 결과를 본 뒤의 재분석이 '
                 '되므로 새 사전등록 없이는 하지 않는다.'),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print()
    print(f'저장: {OUT}')
    return 0 if ok else 1


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
