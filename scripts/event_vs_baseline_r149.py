# -*- coding: utf-8 -*-
"""R149 — 기준선 대비로 다시 묻는다: 공시가 보통 날과 다른가.

사전등록: docs/PREREG_R149_EVENT_VS_BASELINE.md (측정 전 커밋).
판정 기준은 그 문서 §3 의 값을 그대로 묻는다.

  Δ(T,D) = mean(그날 T 공시 종목의 창 초과수익)
         − mean(그날 7유형 어느 공시도 없는 종목의 창 초과수익)
  창은 R148 과 동일 — 진입 D+1 시가 → 청산 D+5 종가, 시장 초과.
  비용은 빼지 않는다 — 상수라 차분에서 정확히 상쇄된다.
  문턱 Bonferroni 7 → z 2.70 · 표본 이벤트 ≥1,000 그리고 날짜 ≥300
  구간 개발 D0 ≤ 2026-01-30 · blind 2026-02-03~07-15 (문턱 통과분만)

**재구현 자기검사**: R148 의 발표 값(유형별 평균 · 기준선 −0.232%)을
0.001%p 이내로 재현하지 못하면 **측정을 중단한다**(사전등록 §4).

측정 전용 — 점수·게이트·문턱을 바꾸지 않는다.

    C:/Python314/python.exe scripts/event_vs_baseline_r149.py
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
OUT = os.path.join(PROJ, 'data', 'event_vs_baseline_r149.json')
R148 = os.path.join(PROJ, 'data', 'event_window_r148.json')
DISC = os.path.join(PROJ, '.portfolio', 'disclosures_daily.jsonl')
BARS = os.path.join(PROJ, '.portfolio', 'daily_bars.jsonl')
MASTER = os.path.join(PROJ, '.portfolio', 'name_master.json')

import disclosure_types as dt                                  # noqa: E402

TYPES = ('자사주·배당', '수주·공급계약', '증자·CB·BW', '투자·설비',
         'M&A·분할', 'IR·안내', '인허가·임상')
MAIN_EXIT = 5                  # 사전등록 §2 — R148 과 동일한 창
SUB_EXITS = (1, 3, 10, 20)     # §5 — 민감도
COST_PCT = 0.41                # 재현 확인용(차분에서는 상쇄된다)
Z_CRIT = 2.70                  # §3
MIN_EVENTS = 1000              # §3
MIN_DAYS = 300                 # §3
DEV_END = '2026-01-30'         # §3
BLIND = ('2026-02-03', '2026-07-15')
BAR_FIRST = '2014-05-30'       # §1 — 네이버 3,000봉 상한
REPRO_TOL = 0.001              # §4 — 재현 허용 오차(%p)

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
    return round((0.5 + Z_CRIT / (2 * math.sqrt(n))) * 100, 1) if n else None


def main():
    print('R149 — 기준선 대비: 공시가 보통 날과 다른가')
    print('사전등록: docs/PREREG_R149_EVENT_VS_BASELINE.md')
    print('측정 전용 — 점수·게이트·문턱을 바꾸지 않는다')
    print()

    # ── 일봉 ────────────────────────────────────────────────────────────
    bars, mkt_of = {}, {}
    with open(BARS, encoding='utf-8') as f:
        for ln in f:
            r = json.loads(ln)
            if not r.get('bars'):
                continue
            bars[r['code']] = ([b[0] for b in r['bars']],
                               {b[0]: b for b in r['bars']})
            mkt_of[r['code']] = r['mkt']
    idx = {'KOSPI': bars.get('KS11'), 'KOSDAQ': bars.get('KQ11')}
    stocks = [c for c in bars if mkt_of[c] != 'INDEX']
    print(f'■ 일봉 {len(stocks):,}종목 · {BAR_FIRST} ~ '
          f'{max(bars[c][0][-1] for c in stocks)}')

    # ── 이름 → 코드 (R146) ─────────────────────────────────────────────
    with open(MASTER, encoding='utf-8') as f:
        m = json.load(f)
    n2c = collections.defaultdict(set)
    for r in m['rows']:
        n2c[norm(r['name'])].add(r['code'])
    name2code = {k: next(iter(v)) for k, v in n2c.items() if len(v) == 1}

    # ── 이벤트 (종목, D0) 유형별 ────────────────────────────────────────
    ev = {t: set() for t in TYPES}
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
            if len(d) == 10 and d >= BAR_FIRST:
                ev[t].add((code, d))
    print('■ 이벤트: ' + ' · '.join(f'{t} {len(ev[t]):,}' for t in TYPES))

    # ── 접수일 → 거래일 매핑 (R148 과 동일하게) ─────────────────────────
    #   접수일이 그 종목의 거래일이 아니면 **다음 거래일**이 D0 다
    #   (사전등록 §2 · R148 도 같다). 처음에 이 매핑을 빼먹고 '거래일과
    #   정확히 일치하는 공시'만 봤더니 유형당 5~221건이 통째로 빠져
    #   §4 자기검사가 4유형에서 걸렸다 — 허용 오차를 늘리지 않고
    #   매핑을 고쳤다.
    #
    #   중복도 R148 을 그대로 따른다: 서로 다른 접수일 둘이 같은 거래일로
    #   밀리면 R148 은 그 종목의 수익을 그날 **두 번** 센다. 재현이
    #   목적이므로 배수(mult)를 그대로 반영한다. 영향은 유형당 0~21건
    #   (2만 건 중 0.11% 미만)이고 결과 문서에 적는다.
    ev_map = {t: collections.Counter() for t in TYPES}
    any_ev = collections.defaultdict(set)     # (code, 거래일) -> 유형 집합
    n_shift = collections.Counter()
    for t in TYPES:
        for c, d in ev[t]:
            ds = bars[c][0]
            i = bisect.bisect_left(ds, d)
            if i >= len(ds) or d < ds[0]:
                continue
            if ds[i] != d:
                n_shift[t] += 1
            ev_map[t][(c, ds[i])] += 1
            any_ev[(c, ds[i])].add(t)
    print('   (거래일 아닌 접수일 → 다음 거래일로 이동: '
          + ' · '.join(f'{t} {n_shift[t]}' for t in TYPES) + ')')

    def window(code, d0, exit_k):
        """R148 과 동일 — D+1 시가 → D+exit 종가, 시장 초과(비용 전)."""
        ds, bm = bars[code]
        i0 = bisect.bisect_left(ds, d0)
        if i0 >= len(ds) or d0 < ds[0] or i0 + exit_k >= len(ds):
            return None, None
        d_in, d_out = ds[i0 + 1], ds[i0 + exit_k]
        ix = idx[mkt_of[code]]
        if ix is None or d_in not in ix[1] or d_out not in ix[1]:
            return None, None
        o, c = bm[d_in][1], bm[d_out][4]
        io_, ic = ix[1][d_in][1], ix[1][d_out][4]
        if not o or not io_:
            return None, None
        return (c / o - 1) * 100 - (ic / io_ - 1) * 100, ds[i0]

    # ── 전 종목·전 거래일 창을 한 번 돌며 날짜별로 모은다 ───────────────
    #   메모리를 아끼려고 값을 쌓지 않고 **합·개수**만 센다.
    #   per_day[D] = [총합, 총개수, 무공시합, 무공시개수]
    #   per_type[T][D] = [합, 개수]
    #   시장별(민감도)도 같은 방식으로 따로 센다.
    per_day = collections.defaultdict(lambda: [0.0, 0, 0.0, 0])
    per_day_mkt = collections.defaultdict(
        lambda: {'KOSPI': [0.0, 0, 0.0, 0], 'KOSDAQ': [0.0, 0, 0.0, 0]})
    per_type = {t: collections.defaultdict(lambda: [0.0, 0]) for t in TYPES}
    per_type_mkt = {t: collections.defaultdict(
        lambda: {'KOSPI': [0.0, 0], 'KOSDAQ': [0.0, 0]}) for t in TYPES}
    #: 민감도 — 대조군을 "T 만 없는 종목"으로 둘 때 필요한 값
    per_type_other = {t: collections.defaultdict(lambda: [0.0, 0])
                      for t in TYPES}
    sub_type = {k: {t: collections.defaultdict(lambda: [0.0, 0])
                    for t in TYPES} for k in SUB_EXITS}
    sub_day = {k: collections.defaultdict(lambda: [0.0, 0, 0.0, 0])
               for k in SUB_EXITS}

    n_win = 0
    for c in stocks:
        ds, _ = bars[c]
        mk = mkt_of[c]
        for d in ds:
            if d < BAR_FIRST:
                continue
            ret, dd = window(c, d, MAIN_EXIT)
            if ret is None:
                continue
            n_win += 1
            types_here = any_ev.get((c, d)) or ()
            b = per_day[dd]
            b[0] += ret
            b[1] += 1
            bm_ = per_day_mkt[dd][mk]
            bm_[0] += ret
            bm_[1] += 1
            if not types_here:
                b[2] += ret
                b[3] += 1
                bm_[2] += ret
                bm_[3] += 1
            for t in types_here:
                mult = ev_map[t][(c, dd)]       # R148 재현 — 배수 그대로
                e = per_type[t][dd]
                e[0] += ret * mult
                e[1] += mult
                em = per_type_mkt[t][dd][mk]
                em[0] += ret * mult
                em[1] += mult
            for t in TYPES:                 # 민감도용 — T 만 없는 대조군
                if t not in types_here:
                    o = per_type_other[t][dd]
                    o[0] += ret
                    o[1] += 1
            for k in SUB_EXITS:
                r2, d2 = window(c, d, k)
                if r2 is None:
                    continue
                s = sub_day[k][d2]
                s[0] += r2
                s[1] += 1
                if not types_here:
                    s[2] += r2
                    s[3] += 1
                for t in types_here:
                    mult = ev_map[t][(c, dd)]
                    st = sub_type[k][t][d2]
                    st[0] += r2 * mult
                    st[1] += mult
    print(f'■ 창 {n_win:,}개 · 날짜 {len(per_day):,}일')

    # ── 재구현 자기검사 (사전등록 §4) ───────────────────────────────────
    with open(R148, encoding='utf-8') as f:
        prev = json.load(f)
    base_days = [d for d in per_day if d <= DEV_END]
    base_mean = (sum(per_day[d][0] for d in base_days)
                 / sum(per_day[d][1] for d in base_days))
    # R148 기준선은 날짜별 평균의 평균(비용 후)이다 — 같은 방식으로 낸다
    bl_vals = [per_day[d][0] / per_day[d][1] - COST_PCT
               for d in sorted(base_days)]
    bl_mean = round(sum(bl_vals) / len(bl_vals), 3)
    prev_bl = ((prev.get('diagnostics') or {}).get('baseline') or {})
    checks = [('기준선', bl_mean, prev_bl.get('mean_pct'))]
    for t in TYPES:
        days = sorted(d for d in per_type[t] if d <= DEV_END)
        vals = [per_type[t][d][0] / per_type[t][d][1] - COST_PCT for d in days]
        mine = round(sum(vals) / len(vals), 3) if vals else None
        checks.append((t, mine, ((prev['types'].get(t) or {}).get('dev')
                                 or {}).get('mean_pct')))
    print()
    print('■ 재구현 자기검사 — R148 발표 값을 재현하는가 (사전등록 §4)')
    bad = []
    for nm, mine, theirs in checks:
        ok = (mine is not None and theirs is not None
              and abs(mine - theirs) <= REPRO_TOL)
        print(f'   {"OK " if ok else "!! "}{nm:<12} 재구현 {mine} · '
              f'R148 {theirs}')
        if not ok:
            bad.append(nm)
    if bad:
        print()
        print(f'■ 재현 실패 {len(bad)}건 — 측정을 중단한다 (사전등록 §4). '
              f'기준을 낮추지 않는다.')
        return 2

    # ── 주 시험 ────────────────────────────────────────────────────────
    def run(pt, pd, lo=None, hi=None):
        days = sorted(d for d in pt
                      if (lo is None or d >= lo) and (hi is None or d <= hi)
                      and pt[d][1] > 0 and pd[d][3] > 0)
        vals = [pt[d][0] / pt[d][1] - pd[d][2] / pd[d][3] for d in days]
        z, win, n = sign_test(vals)
        # 중앙값은 결과를 본 뒤에 **보고용으로만** 더했다 — 자사주·배당에서
        # 평균(+)과 부호검정(−)이 갈렸고, 둘 중 하나만 적으면 오해를 준다.
        # 판정에는 쓰지 않는다(사전등록 §2 의 부호검정 그대로).
        sv = sorted(vals)
        med = (round(sv[len(sv) // 2], 3) if sv else None)
        return dict(events=sum(pt[d][1] for d in days), days=len(days),
                    delta_mean_pp=round(sum(vals) / len(vals), 3) if vals else None,
                    delta_median_pp=med,
                    win_pct=round(win / n * 100, 1) if n else None,
                    need_pct=need_p(n), sign_z=z, sign_win=win, sign_n=n)

    results = {}
    print()
    print(f'{"유형":<10}{"이벤트":>8}{"날짜":>7}{"Δ평균%p":>9}{"Δ중앙%p":>9}'
          f'{"승률":>7}{"필요":>7}{"z":>7}  판정')
    for t in TYPES:
        dev = run(per_type[t], per_day, hi=DEV_END)
        sample_ok = dev['events'] >= MIN_EVENTS and dev['days'] >= MIN_DAYS
        z_ok = dev['sign_z'] is not None and abs(dev['sign_z']) >= Z_CRIT
        if not sample_ok:
            verdict = '표본 미달'
        elif z_ok:
            verdict = ('통과(+) — 보통 날보다 낫다' if dev['sign_z'] > 0
                       else '통과(−) — 보통 날보다 못하다')
        else:
            verdict = '미달 — 기각'
        blind = run(per_type[t], per_day, lo=BLIND[0], hi=BLIND[1]) \
            if (sample_ok and z_ok) else None
        results[t] = dict(dev=dev, sample_ok=sample_ok, z_ok=z_ok,
                          verdict=verdict, blind=blind)
        print(f'{t:<10}{dev["events"]:>8,}{dev["days"]:>7,}'
              f'{(dev["delta_mean_pp"] or 0):>9.3f}'
              f'{(dev["delta_median_pp"] or 0):>9.3f}'
              f'{(dev["win_pct"] or 0):>6.1f}%'
              f'{(dev["need_pct"] or 0):>6.1f}%'
              f'{(dev["sign_z"] if dev["sign_z"] is not None else 0):>7.2f}  {verdict}')

    passed = [t for t in TYPES if results[t]['sample_ok'] and results[t]['z_ok']]
    print()
    if passed:
        print('■ blind 확인 (문턱을 넘은 유형만 — 사전등록 §3)')
        for t in passed:
            b = results[t]['blind']
            print(f"   {t}: 이벤트 {b['events']:,} · 날짜 {b['days']} · "
                  f"Δ {b['delta_mean_pp']}%p · z {b['sign_z']}")
    else:
        print('■ 문턱을 넘은 유형이 없다 — blind 를 열지 않는다')

    # ── 민감도 (판정에 쓰지 않는다) ────────────────────────────────────
    print()
    print('■ 민감도 (판정에 쓰지 않는다 — 사전등록 §5)')
    sens = {}
    print(f'   {"유형":<10}{"T만없음 z":>11}{"KOSPI z":>9}{"KOSDAQ z":>10}'
          f'{"  창 D+1/3/10/20 z"}')
    for t in TYPES:
        oth = run(per_type[t], {d: [0, 0, per_type_other[t][d][0],
                                    per_type_other[t][d][1]]
                                for d in per_type_other[t]}, hi=DEV_END)
        mk = {}
        for k in ('KOSPI', 'KOSDAQ'):
            pt = {d: per_type_mkt[t][d][k] for d in per_type_mkt[t]}
            pd = {d: [0, 0, per_day_mkt[d][k][2], per_day_mkt[d][k][3]]
                  for d in per_day_mkt}
            mk[k] = run(pt, pd, hi=DEV_END)
        subs = {str(k): run(sub_type[k][t], sub_day[k], hi=DEV_END)
                for k in SUB_EXITS}
        sens[t] = dict(control_t_only=oth, by_market=mk, sub_windows=subs)
        print(f'   {t:<10}{(oth["sign_z"] or 0):>11.2f}'
              f'{(mk["KOSPI"]["sign_z"] or 0):>9.2f}'
              f'{(mk["KOSDAQ"]["sign_z"] or 0):>10.2f}  '
              + ' · '.join(f'{subs[str(k)]["sign_z"]}' for k in SUB_EXITS))

    doc = {
        'made': date.today().isoformat(),
        'made_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'prereg': 'docs/PREREG_R149_EVENT_VS_BASELINE.md',
        'criteria': dict(z_crit=Z_CRIT, min_events=MIN_EVENTS,
                         min_days=MIN_DAYS, main_exit=MAIN_EXIT,
                         dev_end=DEV_END, blind=list(BLIND),
                         n_tests=len(TYPES), bar_first=BAR_FIRST,
                         repro_tol=REPRO_TOL),
        'windows': n_win, 'window_days': len(per_day),
        'repro_check': [dict(name=n, mine=a, r148=b) for n, a, b in checks],
        'types': results, 'passed': passed, 'sensitivity': sens,
        'note': ('측정 전용 — 점수·게이트·문턱을 바꾸지 않는다. 비용은 '
                 '차분에서 상쇄되므로 빼지 않는다. 크기·유동성 매칭 없음 '
                 '(사전등록 §6). 원장 미조인.'),
    }
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print()
    print(f'저장: {OUT}')
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
