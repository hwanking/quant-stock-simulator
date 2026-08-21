# -*- coding: utf-8 -*-
"""공시 분류를 **연도별로** 잰다 — 평균은 이 물음에 답하는 잣대가 아니다.

물음: 옛날 구간에서 분류 규칙이 덜 먹히는가.

전체 평균만 보다가 두 번 틀렸다: ① 3일 표본의 '기타' 57.8% 를 안정값으로
읽었고(실제 74.8%), ② 회차 세 점(74.8→75.6→76.5)만 보고 "옛날일수록 덜
잡힌다"는 경향을 읽었는데 네 점째(75.9)가 뒤집었다. 그래서 연도로 가른다.

이것이 이벤트 연구 전에 알아야 할 사실이다 — 옛 구간에서 '기타'가 훨씬
높다면 규칙이 최근 제목 관행에 맞춰져 있다는 뜻이고, 그 구간의 이벤트
통계는 태깅 오류에 더 오염된다 (라운드 124 §3.1 의 경고가 구간마다 다를
수 있다).

측정 전용 — 점수·게이트·문턱을 바꾸지 않는다.

    C:/Python314/python.exe scripts/disclosure_year_audit.py
"""
import collections
import io
import json
import os
import sys
from datetime import date, datetime, timezone

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
OUT = os.path.join(PROJ, 'data', 'disclosure_year_audit.json')
SRC = os.path.join(PROJ, '.portfolio', 'disclosures_daily.jsonl')

import disclosure_types as dt                                  # noqa: E402
import market_attention as ma                                  # noqa: E402

#: 이보다 날짜가 적은 해는 '온전한 해'가 아니다 — 첫해·끝해는 일부만
#: 있어서 섞으면 오해한다 (연간 거래일은 약 246일 · 라운드 129 유도값)
FULL_YEAR_DAYS = 200


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def main():
    print('공시 분류 연도별 감사 — 옛 구간에서 규칙이 덜 먹히는가')
    print('측정 전용 — 점수·게이트·문턱을 바꾸지 않는다')
    print()

    by = collections.defaultdict(
        lambda: {'n': 0, 'o': 0, 'r': 0, 'd': set()})
    miss_earn = 0                 # '영업(잠정)실적'인데 여전히 '기타'인 것
    total = 0
    with open(SRC, encoding='utf-8', errors='replace') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:                                  # noqa: BLE001
                continue
            d = str(r.get('day') or '')[:10]
            if len(d) < 4:
                continue
            t = r.get('title')
            b = by[d[:4]]
            total += 1
            b['n'] += 1
            b['d'].add(d)
            if ma._classify_disclosure(t) == '기타':
                b['o'] += 1
            if dt.classify(t) == '기타':
                b['r'] += 1
                if '영업(잠정)실적' in str(t).replace(' ', ''):
                    miss_earn += 1

    years = []
    print(f'{"연도":>6}{"건수":>10}{"날짜":>7}{"운영 기타":>10}'
          f'{"연구 기타":>10}{"감소":>9}')
    for y in sorted(by):
        b = by[y]
        o = round(b['o'] / b['n'] * 100, 1)
        r = round(b['r'] / b['n'] * 100, 1)
        years.append(dict(year=y, n=b['n'], days=len(b['d']),
                          op_etc_pct=o, res_etc_pct=r,
                          full=len(b['d']) >= FULL_YEAR_DAYS))
        print(f'{y:>6}{b["n"]:>10,}{len(b["d"]):>7,}'
              f'{o:>9.1f}%{r:>9.1f}%{o - r:>8.1f}p')

    full = [x for x in years if x['full']]
    head = {}
    if len(full) >= 2:
        lo = min(full, key=lambda x: x['res_etc_pct'])
        hi = max(full, key=lambda x: x['res_etc_pct'])
        old = [x['res_etc_pct'] for x in full if x['year'] <= '2019']
        new = [x['res_etc_pct'] for x in full if x['year'] >= '2023']
        head = dict(
            min_year=lo['year'], min_pct=lo['res_etc_pct'],
            max_year=hi['year'], max_pct=hi['res_etc_pct'],
            spread_pp=round(hi['res_etc_pct'] - lo['res_etc_pct'], 1),
            old_avg_pct=(round(sum(old) / len(old), 1) if old else None),
            new_avg_pct=(round(sum(new) / len(new), 1) if new else None),
        )
        if head['old_avg_pct'] is not None and head['new_avg_pct'] is not None:
            head['era_gap_pp'] = round(
                head['old_avg_pct'] - head['new_avg_pct'], 1)
        print()
        print(f"■ 온전한 해({len(full)}개, {FULL_YEAR_DAYS}일 이상)만 비교")
        print(f"   최저 {head['min_year']} {head['min_pct']:.1f}% · "
              f"최고 {head['max_year']} {head['max_pct']:.1f}% · "
              f"폭 {head['spread_pp']:.1f}%p")
        if head.get('era_gap_pp') is not None:
            print(f"   2019 이전 평균 {head['old_avg_pct']:.1f}% vs "
                  f"2023 이후 평균 {head['new_avg_pct']:.1f}% "
                  f"(차 {head['era_gap_pp']:.1f}%p)")

    print()
    print(f"■ '영업(잠정)실적'인데 여전히 '기타'인 것: {miss_earn:,}건")
    print('   운영 분류기의 괄호 누락(라운드 140 §5) — 표본에 비례해 '
          '자란다. 2026-11-16 이후에 고친다.')

    doc = {
        'made': date.today().isoformat(),
        'made_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'question': '옛날 구간에서 분류 규칙이 덜 먹히는가 (연도별)',
        'source': '.portfolio/disclosures_daily.jsonl',
        'rows_total': total,
        'full_year_days': FULL_YEAR_DAYS,
        'years': years,
        'full_years': len(full),
        'headline': head,
        'missing_earnings_in_etc': miss_earn,
        'note': ('측정 전용 — 점수·게이트·문턱을 바꾸지 않는다. '
                 '운영 분류기(market_attention)는 건드리지 않는다.'),
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
