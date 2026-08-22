# -*- coding: utf-8 -*-
"""R148 — 공시 자체에 알파가 있는가 (순수 이벤트 창 · 7유형 일괄).

사전등록: docs/PREREG_R148_EVENT_WINDOW.md (측정 전 커밋). 판정 기준은
그 문서 §4 의 값을 그대로 묻는다 — 여기서 바꾸면 이중 경로다.

  창: 진입 D+1 시가 → 청산 D+5 종가 (주) · 부: D+1/3/10/20 종가
  초과수익 = 종목 − 지수(시장별) − 비용 0.41%
  표본 단위: D0 날짜 (날짜별 평균 → 부호검정, 양측)
  문턱: Bonferroni 7 → z 2.70 (올림) · 표본: 이벤트 ≥1,000 그리고 날짜 ≥300
  구간: 개발 D0 ≤ 2026-01-30 · blind 2026-02-03~2026-07-15 (통과 유형만)

측정 전용 — 점수·게이트·문턱을 바꾸지 않는다.

    C:/Python314/python.exe scripts/event_window_r148.py
"""
import bisect
import collections
import io
import json
import math
import os
import re
import sys
from datetime import date, datetime, timezone

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
OUT = os.path.join(PROJ, 'data', 'event_window_r148.json')
DISC = os.path.join(PROJ, '.portfolio', 'disclosures_daily.jsonl')
BARS = os.path.join(PROJ, '.portfolio', 'daily_bars.jsonl')
MASTER = os.path.join(PROJ, '.portfolio', 'name_master.json')

import disclosure_types as dt                                  # noqa: E402

TYPES = ('자사주·배당', '수주·공급계약', '증자·CB·BW', '투자·설비',
         'M&A·분할', 'IR·안내', '인허가·임상')       # 사전등록 §2 — 7유형
MAIN_EXIT = 5                  # §2 — 주 창: D+1 시가 → D+5 종가
SUB_EXITS = (1, 3, 10, 20)     # §2 — 부 시험
COST_PCT = 0.41                # §3 — 저장소 채택값 TOTAL_COST_PCT
Z_CRIT = 2.70                  # §4 — Bonferroni 7, 올림
MIN_EVENTS = 1000              # §4
MIN_DAYS = 300                 # §4
DEV_END = '2026-01-30'         # §4 — 원장 valid 끝
BLIND = ('2026-02-03', '2026-07-15')   # §4 — 원장 blind 경계
COVER_MIN = 70.0               # §4 — 부분 표본 딱지

_STRIP = re.compile(r'\s+|㈜|\(주\)|주식회사')


def norm(name):
    return _STRIP.sub('', str(name)).upper()


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def sign_test(vals):
    nz = [v for v in vals if v != 0]
    n = len(nz)
    if n == 0:
        return None, 0, 0
    win = sum(1 for v in nz if v > 0)
    return round((win - n / 2) / math.sqrt(n / 4), 2), win, n


def need_p(n):
    """z >= Z_CRIT 에 필요한 양수 날짜 비율 — 사전등록 §5."""
    return round((0.5 + Z_CRIT / (2 * math.sqrt(n))) * 100, 1) if n else None


def main():
    print('R148 — 공시 자체에 알파가 있는가 (순수 이벤트 창 · 7유형 일괄)')
    print('사전등록: docs/PREREG_R148_EVENT_WINDOW.md')
    print('측정 전용 — 점수·게이트·문턱을 바꾸지 않는다')
    print()

    # ── 일봉 ────────────────────────────────────────────────────────────
    bars = {}                      # code -> (dates[], {date: [d,o,h,l,c,v]})
    mkt_of = {}
    n_fail = 0
    with open(BARS, encoding='utf-8') as f:
        for ln in f:
            r = json.loads(ln)
            if not r.get('bars'):
                n_fail += 1
                continue
            ds = [b[0] for b in r['bars']]
            bars[r['code']] = (ds, {b[0]: b for b in r['bars']})
            mkt_of[r['code']] = r['mkt']
    idx = {'KOSPI': bars.get('KS11'), 'KOSDAQ': bars.get('KQ11')}
    stocks = [c for c in bars if mkt_of[c] != 'INDEX']
    firsts = sorted(bars[c][0][0] for c in stocks)
    bar_first = firsts[0]
    last_day = max(bars[c][0][-1] for c in stocks)
    print(f"■ 일봉 {len(stocks):,}종목 (실패 {n_fail}) · 최초 {bar_first} · "
          f"최종 {last_day} · 지수 KS11 {len(idx['KOSPI'][0]):,}봉 · "
          f"KQ11 {len(idx['KOSDAQ'][0]):,}봉")

    # ── 이름 → 코드 (R146) ─────────────────────────────────────────────
    with open(MASTER, encoding='utf-8') as f:
        m = json.load(f)
    n2c = collections.defaultdict(set)
    for r in m['rows']:
        n2c[norm(r['name'])].add(r['code'])
    name2code = {k: next(iter(v)) for k, v in n2c.items() if len(v) == 1}

    # ── 이벤트 (종목, D0, 유형) — 유니버스·일봉 있는 것만 ─────────────
    events = collections.defaultdict(set)        # type -> {(code, d0)}
    joined_total = collections.Counter()         # type -> 조인된 공시 건수
    with open(DISC, encoding='utf-8', errors='replace') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:                                  # noqa: BLE001
                continue
            t = dt.classify(r.get('title'))
            if t not in TYPES:
                continue
            code = name2code.get(norm(r.get('name') or ''))
            if not code or code not in bars:
                continue
            d = str(r.get('day') or '')[:10]
            if len(d) == 10:
                events[t].add((code, d))
                joined_total[t] += 1

    def window(code, d0, exit_k):
        """D0(또는 다음 거래일) 기준 D+1 시가 → D+exit 종가 초과수익(%)."""
        ds, bm = bars[code]
        i0 = bisect.bisect_left(ds, d0)
        if i0 >= len(ds) or i0 + exit_k >= len(ds):
            return None, None
        d_in, d_out = ds[i0 + 1], ds[i0 + exit_k]
        ix = idx[mkt_of[code]]
        if ix is None or d_in not in ix[1] or d_out not in ix[1]:
            return None, None
        o = bm[d_in][1]
        c = bm[d_out][4]
        io_, ic = ix[1][d_in][1], ix[1][d_out][4]
        if not o or not io_:
            return None, None
        ret = (c / o - 1) * 100 - (ic / io_ - 1) * 100 - COST_PCT
        return ret, ds[i0]

    def agg(bd, lo=None, hi=None):
        days = sorted(x for x in bd if (lo is None or x >= lo)
                      and (hi is None or x <= hi))
        vals = [sum(bd[x]) / len(bd[x]) for x in days]
        n_ev = sum(len(bd[x]) for x in days)
        z, win, n = sign_test(vals)
        return dict(events=n_ev, days=len(days),
                    mean_pct=round(sum(vals) / len(vals), 3) if vals else None,
                    win_pct=round(win / n * 100, 1) if n else None,
                    need_pct=need_p(n), sign_z=z, sign_win=win, sign_n=n)

    results = {}
    print()
    print(f'{"유형":<10}{"조인":>8}{"기간내":>8}{"창온전":>8}{"커버":>7}'
          f'{"날짜":>6}{"평균%":>8}{"승률":>7}{"필요":>7}{"z":>7}  판정')
    for t in TYPES:
        evs = events[t]
        in_range = [(c, d) for c, d in evs if d >= bar_first]
        by_day = collections.defaultdict(list)
        by_day_sub = {k: collections.defaultdict(list) for k in SUB_EXITS}
        ok = 0
        for c, d in in_range:
            ret, dd = window(c, d, MAIN_EXIT)
            if ret is None:
                continue
            ok += 1
            by_day[dd].append(ret)
            for k in SUB_EXITS:
                r2, d2 = window(c, d, k)
                if r2 is not None:
                    by_day_sub[k][d2].append(r2)
        cover = round(ok / len(in_range) * 100, 1) if in_range else None

        dev = agg(by_day, hi=DEV_END)
        sample_ok = dev['events'] >= MIN_EVENTS and dev['days'] >= MIN_DAYS
        z_ok = dev['sign_z'] is not None and abs(dev['sign_z']) >= Z_CRIT
        if not sample_ok:
            verdict = '표본 미달'
        elif z_ok:
            verdict = '통과(+)' if dev['sign_z'] > 0 else '유의(-) 방향 반대'
        else:
            verdict = '미달 — 기각'
        if cover is not None and cover < COVER_MIN:
            verdict += ' · 부분 표본'
        blind = None
        if sample_ok and z_ok:
            blind = agg(by_day, lo=BLIND[0], hi=BLIND[1])
        subs = {str(k): agg(by_day_sub[k], hi=DEV_END) for k in SUB_EXITS}
        results[t] = dict(joined=joined_total[t], in_range=len(in_range),
                          window_ok=ok, coverage_pct=cover, dev=dev,
                          sample_ok=sample_ok, z_ok=z_ok, verdict=verdict,
                          blind=blind, subs=subs)
        mp = dev['mean_pct'] if dev['mean_pct'] is not None else 0.0
        zz = dev['sign_z'] if dev['sign_z'] is not None else 0.0
        print(f'{t:<10}{joined_total[t]:>8,}{len(in_range):>8,}{ok:>8,}'
              f'{(cover or 0):>6.1f}%{dev["days"]:>6,}{mp:>8.3f}'
              f'{(dev["win_pct"] or 0):>6.1f}%{(dev["need_pct"] or 0):>6.1f}%'
              f'{zz:>7.2f}  {verdict}')

    passed = [t for t, r in results.items() if r['sample_ok'] and r['z_ok']]
    print()
    if passed:
        print('■ blind 확인 (통과 유형만 — 사전등록 §4)')
        for t in passed:
            b = results[t]['blind']
            print(f"   {t}: 이벤트 {b['events']:,} · 날짜 {b['days']} · "
                  f"평균 {b['mean_pct']}% · z {b['sign_z']}")
    else:
        print('■ 통과한 유형이 없다 — blind 를 열지 않는다 (사전등록 §4)')

    print()
    print('■ 부 시험 (판정에 쓰지 않는다) — 개발 구간 · 청산 D+k 종가 · z')
    for t in TYPES:
        s = results[t]['subs']
        print(f"   {t:<10} " + ' · '.join(
            f"D+{k}: {s[str(k)]['sign_z']}" for k in SUB_EXITS))

    doc = {
        'made': date.today().isoformat(),
        'made_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'prereg': 'docs/PREREG_R148_EVENT_WINDOW.md',
        'criteria': dict(z_crit=Z_CRIT, min_events=MIN_EVENTS,
                         min_days=MIN_DAYS, main_exit=MAIN_EXIT,
                         cost_pct=COST_PCT, dev_end=DEV_END, blind=list(BLIND),
                         cover_min=COVER_MIN, n_tests=len(TYPES)),
        'bars': dict(stocks=len(stocks), failed=n_fail, first=bar_first,
                     last=last_day),
        'types': results,
        'passed': passed,
        'note': ('측정 전용 — 점수·게이트·문턱을 바꾸지 않는다. 원장 미조인. '
                 '진입 D+1 시가(누출 차단). 생존 편향·2014-05-30 기간 제한은 '
                 '사전등록 §1 에 적었다.'),
    }
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print()
    print(f'저장: {OUT}')
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
