# -*- coding: utf-8 -*-
"""라운드 137 — 수급 종목을 더 모으면 짝비교 날짜가 얼마나 느나.

라운드 134 가 다음 걸음을 이렇게 적었다:

> 짝비교 날짜를 늘리려면 **날짜가 아니라 '그날 수급 붙은 종목 수'** 를
> 늘려야 한다 → 250종목 → 더 많은 종목. 다만 라운드 129 가 종목 축은
> 포화라고 쟀으므로, **늘어나는 폭을 먼저 재고 시작한다.**

전 종목을 채우려면 약 24만 요청 · 40시간이다(라운드 130 실측).
**공짜가 아니므로 재고 시작한다.**

늘려 본 결과는 지어낼 수 없으니 **줄여서 곡선을 그린다**(라운드 129 와
같은 방식). 위로 늘렸을 때는 어떻게 될지는 **가정**이라고 밝힌다.

측정 전용 — 점수·게이트·문턱을 바꾸지 않는다. 사전등록이 필요한
가설 검정이 아니라, **자원을 쓸지 말지 고르는 관측**이다.

    C:/Python314/python.exe scripts/flow_ticker_curve_r137.py
"""
import collections
import io
import json
import os
import sys
from datetime import date, datetime, timezone

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJ, 'scripts'))
OUT = os.path.join(PROJ, 'data', 'flow_ticker_curve_r137.json')

import flow_rank_r131 as R                                     # noqa: E402
import power_r113 as P                                         # noqa: E402

FRACS = (0.2, 0.4, 0.6, 0.8, 1.0)
KEY = 'frgn_days5'          # 어떤 변수를 쓰든 짝비교 날짜 수는 거의 같다


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def main():
    print('라운드 137 — 수급 종목을 더 모으면 짝비교 날짜가 얼마나 느나')
    print('측정 전용 — 자원을 쓸지 말지 고르기 위한 관측')
    print()

    rows = P.load()
    flow = R.load_flow()
    print(f'개발 구간·판정완료 {len(rows):,}건 · 수급 종목 {len(flow):,}개')

    # 수집 순서와 같게 — 원장 케이스가 많은 종목부터 담았다
    cnt = collections.Counter(r.get('ticker') for r in rows)
    order = [t for t in sorted(flow, key=lambda x: (-cnt.get(x, 0), x))]

    print()
    print(f'   {"수급 종목":>9}{"조인 케이스":>12}{"수급 날짜":>10}'
          f'{"짝비교 날짜":>12}{"직전 대비":>10}')
    curve, prev = [], None
    for fr in FRACS:
        keep = set(order[:max(1, int(len(order) * fr))])
        joined = {}
        for r in rows:
            t, d = r.get('ticker'), str(r.get('date'))[:10]
            if t not in keep:
                continue
            seq = flow.get(t)
            f = R.features(seq, d) if seq else None
            if f is not None:
                joined[(t, d)] = f
        days_cov = len({d for _t, d in joined})
        paired = len(R.day_frames(rows, KEY, joined))
        gain = None if prev is None else paired - prev
        curve.append(dict(frac=fr, tickers=len(keep), cases=len(joined),
                          covered_days=days_cov, paired_days=paired,
                          gain=gain))
        print(f'   {len(keep):>9,}{len(joined):>12,}{days_cov:>10,}'
              f'{paired:>12,}'
              + (f'{gain:>+10,}' if gain is not None else f'{"—":>10}'))
        prev = paired

    # ── 폭을 읽는다 — 종목 1개가 벌어들이는 날짜 ────────────────
    print()
    print('■ 종목 하나가 벌어들이는 짝비교 날짜')
    per = []
    for i in range(1, len(curve)):
        d_t = curve[i]['tickers'] - curve[i - 1]['tickers']
        d_d = curve[i]['paired_days'] - curve[i - 1]['paired_days']
        rate = (d_d / d_t) if d_t else 0.0
        per.append(rate)
        print(f'   {curve[i - 1]["tickers"]:>4,} → {curve[i]["tickers"]:>4,}'
              f'종목 : 날짜 {d_d:>+5,} → 종목당 **{rate:+.3f}일**')

    first, last = (per[0] if per else 0.0), (per[-1] if per else 0.0)
    ratio = (first / last) if last > 0 else None
    print()
    if last <= 0:
        print('   마지막 구간에서 **더 늘지 않는다** — 포화다.')
    else:
        print(f'   첫 구간 {first:+.3f}일/종목 · 마지막 {last:+.3f}일/종목'
              + (f' ({ratio:.1f}배 감소)' if ratio else ''))

    # ── 그래서 얼마를 더 모으면 얼마가 되나 (가정임을 밝힌다) ────
    have_t, have_d = curve[-1]['tickers'], curve[-1]['paired_days']
    print()
    print('■ 더 모으면 — **마지막 구간 기울기가 이어진다고 가정**하면')
    print('   (실제로는 나중 종목일수록 얇으므로 이보다 덜 는다)')
    for add in (250, 750, 1250):
        est = have_d + last * add
        print(f'   +{add:,}종목 → 짝비교 약 {est:,.0f}일 '
              f'(지금 {have_d:,}일) · 수집 약 {add * 160:,}요청'
              f' ≈ {add * 160 * 0.6 / 3600:.0f}시간')

    # R134 가 못 넘은 하한(600일)에 닿으려면
    need = 600
    if last > 0 and have_d < need:
        add_need = (need - have_d) / last
        print()
        print(f'   R134 의 P4 하한 {need}일에 닿으려면 '
              f'+{add_need:,.0f}종목 (같은 기울기 가정) · '
              f'약 {add_need * 160 * 0.6 / 3600:.0f}시간')
    print()
    print('   ※ 위 셋은 **외삽이다.** 줄여서 잰 곡선은 사실이고, 늘렸을 '
          '때의 값은 가정이다. 나중 종목일수록 원장 케이스가 얇으므로 '
          '실제로는 이보다 덜 는다 (라운드 129 가 종목 축에서 본 그 모양).')

    doc = {
        'made': date.today().isoformat(),
        'made_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'question': ('수급 종목을 더 모으면 짝비교 날짜가 얼마나 느나 — '
                     '40시간을 긁기 전에 폭부터 잰다'),
        'basis': '개발 구간(train+valid) · 판정완료 · 블라인드 미사용',
        'method': ('늘린 결과는 지어낼 수 없으므로 **줄여서** 곡선을 '
                   '그린다. 위로 늘렸을 때의 값은 외삽이며 가정이다.'),
        'key': KEY, 'curve': curve,
        'per_ticker_days': [round(x, 4) for x in per],
        'first_rate': round(first, 4), 'last_rate': round(last, 4),
        'have_tickers': have_t, 'have_paired_days': have_d,
        'note': ('관측 전용 — 점수·게이트·문턱을 바꾸지 않는다. '
                 '가설 검정이 아니라 자원 배분을 고르기 위한 측정이다.'),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print()
    print(f'저장: {OUT}')
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
