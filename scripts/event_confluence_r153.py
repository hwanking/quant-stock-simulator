# -*- coding: utf-8 -*-
"""R153 — 겹침(Event Confluence): 여러 공시가 같은 날 나면 반응이 더 큰가.

사전등록: docs/PREREG_R153_EVENT_CONFLUENCE.md (측정 전 커밋).
판정 기준은 그 문서 §4 의 값을 그대로 묻는다.

  창·매칭은 R150 과 동일 (D+1 시가 → D+5 종가 · 시장 초과 ·
  층 = 시장 × 거래대금 5분위 × 변동성 5분위 · 비용 미차감)
  Δ2(D) = k>=2 이벤트의 매칭 델타 · Δ1(D) = k=1 이벤트의 매칭 델타
  T1: Δ2 부호검정 · T2: (Δ2 − Δ1) 부호검정 ← 본 질문
  문턱 Bonferroni 2 → z 2.25 · 이벤트 >=1,000 그리고 날짜 >=300

**자기검사(§5)**: 단일 유형(자사주·배당)으로 돌리면 R150 의 매칭 결과
Δ +0.048%p · z -3.42 를 재현해야 한다. 못 하면 측정을 중단한다.

**조합별 시험은 하지 않는다**(§3) — 21조합 보정은 z 3.04 인데 가장 흔한
조합조차 975건으로 표본 조건 1,000 을 못 넘는다. 개수 k 로 묻는다.

측정 전용 — 점수·게이트·문턱을 바꾸지 않는다.

    C:/Python314/python.exe scripts/event_confluence_r153.py
"""
import bisect
import collections
import io
import json
import math
import os
import re
import statistics
import sys
from datetime import date, datetime, timezone

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
OUT = os.path.join(PROJ, 'data', 'event_confluence_r153.json')
R150 = os.path.join(PROJ, 'data', 'matched_control_r150.json')
DISC = os.path.join(PROJ, '.portfolio', 'disclosures_daily.jsonl')
BARS = os.path.join(PROJ, '.portfolio', 'daily_bars.jsonl')
MASTER = os.path.join(PROJ, '.portfolio', 'name_master.json')
LEDGER = os.path.join(PROJ, '.portfolio', 'virtual_graded.jsonl')

import disclosure_types as dt                                  # noqa: E402

TYPES = ('자사주·배당', '수주·공급계약', '증자·CB·BW', '투자·설비',
         'M&A·분할', 'IR·안내', '인허가·임상')
MATERIAL6 = tuple(t for t in TYPES if t != 'IR·안내')   # §5 민감도
MAIN_EXIT = 5                  # §2 — R150 과 동일한 창
SUB_EXITS = (1, 3, 10, 20)     # §5 민감도
LOOKBACK = 20                  # §2 — R150 과 동일
NQ = 5                         # §2
Z_CRIT = 2.25                  # §4 — Bonferroni 2, 올림
MIN_EVENTS = 1000              # §4
MIN_DAYS = 300                 # §4
DEV_END = '2026-01-30'         # §4
BLIND = ('2026-02-03', '2026-07-15')
BAR_FIRST = '2014-05-30'
BUY = 58.0                     # §5 민감도(원장) — R49 채택값
#: §5 자기검사 — R150 이 발표한 자사주·배당 매칭 결과
R150_TYPE, R150_D, R150_Z = '자사주·배당', 0.048, -3.42
TOL_D, TOL_Z = 0.001, 0.01
#: §3 — 조합별로 갔다면 치렀을 비용 (기록용, 시험하지 않는다)
PAIR_COMBOS, PAIR_Z, PAIR_MAX_N = 21, 3.04, 975

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


def quintile(sorted_idx, n):
    out = {}
    for rank, i in enumerate(sorted_idx):
        out[i] = min(NQ - 1, rank * NQ // n)
    return out


def summarize(vals, n_ev):
    z, win, n = sign_test(vals)
    sv = sorted(vals)
    return dict(events=n_ev, days=len(vals),
                mean_pp=round(sum(vals) / len(vals), 3) if vals else None,
                median_pp=round(sv[len(sv) // 2], 3) if sv else None,
                win_pct=round(win / n * 100, 1) if n else None,
                need_pct=need_p(n), sign_z=z, sign_win=win, sign_n=n)


def main():
    print('R153 — 겹침: 여러 공시가 같은 날 나면 반응이 더 큰가')
    print('사전등록: docs/PREREG_R153_EVENT_CONFLUENCE.md')
    print('측정 전용 — 점수·게이트·문턱을 바꾸지 않는다')
    print()

    bars, mkt_of = {}, {}
    with open(BARS, encoding='utf-8') as f:
        for ln in f:
            r = json.loads(ln)
            if not r.get('bars'):
                continue
            bars[r['code']] = ([b[0] for b in r['bars']],
                               {b[0]: b for b in r['bars']}, r['bars'])
            mkt_of[r['code']] = r['mkt']
    idx = {'KOSPI': bars.get('KS11'), 'KOSDAQ': bars.get('KQ11')}
    stocks = [c for c in bars if mkt_of[c] != 'INDEX']

    with open(MASTER, encoding='utf-8') as f:
        m = json.load(f)
    n2c = collections.defaultdict(set)
    for r in m['rows']:
        n2c[norm(r['name'])].add(r['code'])
    name2code = {k: next(iter(v)) for k, v in n2c.items() if len(v) == 1}

    # ── (코드, 거래일) -> 유형 집합 ────────────────────────────────────
    types_at = collections.defaultdict(set)
    mult_at = collections.defaultdict(collections.Counter)  # R150 재현용 배수
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
            if len(d) != 10 or d < BAR_FIRST:
                continue
            ds = bars[code][0]
            i = bisect.bisect_left(ds, d)
            if i >= len(ds) or d < ds[0]:
                continue
            key = (code, ds[i])
            types_at[key].add(t)
            # 배수는 R150 재현(자기검사)에만 쓴다 — 서로 다른 접수일 둘이
            # 같은 거래일로 밀리면 R150 은 그 종목을 그날 두 번 셌다.
            # k 기반 본 시험은 (종목, 거래일)당 1 로 센다 — 겹침의 정의가
            # "몇 **유형**이 겹쳤나" 이지 "몇 건이 접수됐나" 가 아니다.
            mult_at[key][t] += 1
    kc = collections.Counter(len(v) for v in types_at.values())
    print('■ 동시 유형 수 분포: '
          + ' · '.join(f'k={k}: {kc[k]:,}' for k in sorted(kc)))

    def window(code, d0, exit_k):
        ds, bm, _ = bars[code]
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

    # ── 관측 수집 (R150 과 같은 구조) ─────────────────────────────────
    #   per_day[d] = [(code, ret, turnover, vol, mkt), ...]  · 창별
    per_day = {k: collections.defaultdict(list) for k in (MAIN_EXIT,) + SUB_EXITS}
    for c in stocks:
        ds, _bm, raw = bars[c]
        mk = mkt_of[c]
        for i, b in enumerate(raw):
            d = b[0]
            if d < BAR_FIRST:
                continue
            to = vol = None
            if i + 1 >= LOOKBACK:
                wb = raw[i + 1 - LOOKBACK:i + 1]
                tot = sum(x[4] * x[5] for x in wb) / LOOKBACK
                rr = [wb[j][4] / wb[j - 1][4] - 1
                      for j in range(1, len(wb)) if wb[j - 1][4]]
                if len(rr) >= 2 and tot > 0:
                    to, vol = tot, statistics.pstdev(rr)
            for k in (MAIN_EXIT,) + SUB_EXITS:
                ret, dd = window(c, d, k)
                if ret is not None:
                    per_day[k][dd].append((c, ret, to, vol, mk))
    print(f'■ 창(D+{MAIN_EXIT}) {sum(len(v) for v in per_day[MAIN_EXIT].values()):,}개'
          f' · 날짜 {len(per_day[MAIN_EXIT]):,}일')

    def matched_delta(pick, exit_k=MAIN_EXIT, lo=None, hi=None,
                      type_set=TYPES):
        """pick(types) 가 참인 이벤트의 층화 매칭 델타를 날짜별로 낸다.

        대조 = 그날 type_set 중 **어느 공시도 없는** 종목 (R149·R150 동일).
        반환: {날짜: (델타, 이벤트수)}
        """
        out = {}
        for d, obs in per_day[exit_k].items():
            if (lo is not None and d < lo) or (hi is not None and d > hi):
                continue
            strata = {}
            for mk in ('KOSPI', 'KOSDAQ'):
                sub = [i for i, o in enumerate(obs)
                       if o[4] == mk and o[2] is not None]
                if not sub:
                    continue
                n = len(sub)
                tq = quintile(sorted(sub, key=lambda i: obs[i][2]), n)
                vq = quintile(sorted(sub, key=lambda i: obs[i][3]), n)
                for i in sub:
                    strata[i] = (mk, tq[i], vq[i])
            acc = collections.defaultdict(lambda: [0.0, 0, 0.0, 0])
            for i, (c, ret, _to, _vol, _mk) in enumerate(obs):
                s = strata.get(i)
                if s is None:
                    continue
                # 대조군은 **언제나 7유형 어느 공시도 없는 종목**이다
                # (R149·R150 과 동일). type_set 은 이벤트 쪽만 좁힌다 —
                # 처음에 대조까지 좁혔더니 다른 유형 공시가 난 종목이
                # 대조에 섞여 자기검사가 걸렸다(Δ 0.067 vs R150 0.048).
                all_t = types_at.get((c, d), ())
                tset = {t for t in all_t if t in type_set}
                a = acc[s]
                if tset and pick(tset):
                    w = sum(mult_at[(c, d)][t] for t in tset) if len(
                        type_set) == 1 else 1
                    a[0] += ret * w
                    a[1] += w
                elif not all_t:
                    a[2] += ret
                    a[3] += 1
            num = den = 0.0
            for a in acc.values():
                if a[1] > 0 and a[3] > 0:
                    num += (a[0] / a[1] - a[2] / a[3]) * a[1]
                    den += a[1]
            if den > 0:
                out[d] = (num / den, int(den))
        return out

    # ── 자기검사 (사전등록 §5) ─────────────────────────────────────────
    print()
    print('■ 자기검사 — 단일 유형으로 R150 을 재현하는가 (§5)')
    solo = matched_delta(lambda s: R150_TYPE in s, hi=DEV_END,
                         type_set=(R150_TYPE,))
    sv = [v for v, _ in solo.values()]
    s_sum = summarize(sv, sum(n for _, n in solo.values()))
    ok_d = (s_sum['mean_pp'] is not None
            and abs(s_sum['mean_pp'] - R150_D) <= TOL_D + 1e-9)
    ok_z = (s_sum['sign_z'] is not None
            and abs(s_sum['sign_z'] - R150_Z) <= TOL_Z + 1e-9)
    print(f"   {'OK ' if ok_d else '!! '}Δ  재현 {s_sum['mean_pp']} · "
          f"R150 {R150_D}")
    print(f"   {'OK ' if ok_z else '!! '}z  재현 {s_sum['sign_z']} · "
          f"R150 {R150_Z}")
    if not (ok_d and ok_z):
        print()
        print('■ 재현 실패 — 측정을 중단한다 (사전등록 §5). '
              '허용 오차를 늘리지 않는다.')
        return 2

    # ── 주 시험 T1 · T2 ───────────────────────────────────────────────
    def run_pair(lo=None, hi=None, exit_k=MAIN_EXIT, type_set=TYPES):
        d2 = matched_delta(lambda s: len(s) >= 2, exit_k, lo, hi, type_set)
        d1 = matched_delta(lambda s: len(s) == 1, exit_k, lo, hi, type_set)
        t1 = summarize([v for v, _ in d2.values()],
                       sum(n for _, n in d2.values()))
        both = sorted(set(d2) & set(d1))
        t2 = summarize([d2[d][0] - d1[d][0] for d in both],
                       sum(d2[d][1] for d in both))
        return t1, t2, d1, d2

    T1, T2, d1_dev, d2_dev = run_pair(hi=DEV_END)
    print()
    print(f'{"시험":<28}{"이벤트":>8}{"날짜":>7}{"평균%p":>9}{"중앙%p":>9}'
          f'{"승률":>7}{"필요":>7}{"z":>7}  판정')
    results = {}
    for name, s, label in (('T1_겹침 vs 보통날', T1, '겹친 날이 보통 날과 다른가'),
                           ('T2_겹침 vs 하나', T2, '겹침이 하나보다 큰가')):
        sample_ok = s['events'] >= MIN_EVENTS and s['days'] >= MIN_DAYS
        z_ok = s['sign_z'] is not None and abs(s['sign_z']) >= Z_CRIT
        if not sample_ok:
            verdict = '표본 미달'
        elif z_ok:
            verdict = ('증폭한다(−)' if s['sign_z'] < 0 else '완화한다(+)')
        else:
            verdict = '미달 — 기각'
        results[name] = dict(summary=s, question=label, sample_ok=sample_ok,
                             z_ok=z_ok, verdict=verdict, blind=None)
        print(f'{name:<28}{s["events"]:>8,}{s["days"]:>7,}'
              f'{(s["mean_pp"] or 0):>9.3f}{(s["median_pp"] or 0):>9.3f}'
              f'{(s["win_pct"] or 0):>6.1f}%{(s["need_pct"] or 0):>6.1f}%'
              f'{(s["sign_z"] if s["sign_z"] is not None else 0):>7.2f}  {verdict}')

    passed = [n for n, r in results.items() if r['sample_ok'] and r['z_ok']]
    print()
    if passed:
        print('■ blind 확인 (문턱 통과분만 — 사전등록 §4)')
        b1, b2, _, _ = run_pair(lo=BLIND[0], hi=BLIND[1])
        for n, s in (('T1_겹침 vs 보통날', b1), ('T2_겹침 vs 하나', b2)):
            if n in passed:
                results[n]['blind'] = s
                print(f"   {n}: 이벤트 {s['events']:,} · 날짜 {s['days']} · "
                      f"평균 {s['mean_pp']}%p · z {s['sign_z']}")
    else:
        print('■ 문턱을 넘은 시험이 없다 — blind 를 열지 않는다')

    # ── 민감도 (판정에 쓰지 않는다 — 사전등록 §5) ─────────────────────
    print()
    print('■ 민감도 (판정에 쓰지 않는다)')
    m6_1, m6_2, _, _ = run_pair(hi=DEV_END, type_set=MATERIAL6)
    print(f'   k 를 6유형으로: T1 z {m6_1["sign_z"]} · T2 z {m6_2["sign_z"]}')
    d3 = matched_delta(lambda s: len(s) >= 3, hi=DEV_END)
    s3 = summarize([v for v, _ in d3.values()],
                   sum(n for _, n in d3.values()))
    print(f'   k>=3 만: 이벤트 {s3["events"]:,} · 날짜 {s3["days"]:,} · '
          f'평균 {s3["mean_pp"]}%p · z {s3["sign_z"]}'
          + ('  (표본 미달 — 참고만)'
             if s3['events'] < MIN_EVENTS or s3['days'] < MIN_DAYS else ''))
    subs = {}
    for k in SUB_EXITS:
        a, b, _, _ = run_pair(hi=DEV_END, exit_k=k)
        subs[str(k)] = dict(t1=a, t2=b)
    print('   창 D+k: ' + ' · '.join(
        f'D+{k}: T1 {subs[str(k)]["t1"]["sign_z"]} / T2 '
        f'{subs[str(k)]["t2"]["sign_z"]}' for k in SUB_EXITS))

    # 원장 venue — R124 §4 대로 기술 통계로만
    led_days = collections.defaultdict(lambda: {'E': [], 'N': []})
    with open(LEDGER, encoding='utf-8', errors='replace') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:                                  # noqa: BLE001
                continue
            if r.get('score') is None or float(r['score']) < BUY:
                continue
            if r.get('success') is None or r.get('split') not in (
                    'train', 'valid'):
                continue
            c = str(r.get('ticker') or '').split('.')[0]
            d = str(r.get('date') or '')[:10]
            if c not in bars or len(d) != 10:
                continue
            ds = bars[c][0]
            i = bisect.bisect_left(ds, d)
            prev = ds[max(0, i - 5):i]
            k = max((len(types_at.get((c, p), ())) for p in prev), default=0)
            led_days[d]['E' if k >= 2 else 'N'].append(bool(r['success']))
    dh = [(sum(b['E']) / len(b['E']) - sum(b['N']) / len(b['N'])) * 100
          for b in led_days.values() if b['E'] and b['N']]
    led = summarize(dh, sum(len(b['E']) for b in led_days.values()
                            if b['E'] and b['N']))
    print(f'   원장(기술 통계만): 케이스 {led["events"]:,} · 날짜 '
          f'{led["days"]:,} · ΔH {led["mean_pp"]}%p · z {led["sign_z"]}'
          f'  ← 개별이 귀무라 판정하지 않는다 (R124 §4)')

    doc = {
        'made': date.today().isoformat(),
        'made_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'prereg': 'docs/PREREG_R153_EVENT_CONFLUENCE.md',
        'criteria': dict(z_crit=Z_CRIT, min_events=MIN_EVENTS,
                         min_days=MIN_DAYS, main_exit=MAIN_EXIT,
                         lookback=LOOKBACK, nq=NQ, dev_end=DEV_END,
                         blind=list(BLIND), n_tests=2,
                         r150_delta=R150_D, r150_z=R150_Z,
                         tol_d=TOL_D, tol_z=TOL_Z,
                         pair_combos=PAIR_COMBOS, pair_z=PAIR_Z,
                         pair_max_n=PAIR_MAX_N),
        'k_distribution': {str(k): kc[k] for k in sorted(kc)},
        'self_check': dict(delta=s_sum['mean_pp'], z=s_sum['sign_z'],
                           r150_delta=R150_D, r150_z=R150_Z, passed=True),
        'tests': results, 'passed': passed,
        'sensitivity': dict(material6=dict(t1=m6_1, t2=m6_2), k3=s3,
                            sub_windows=subs, ledger_descriptive=led),
        'note': ('측정 전용 — 점수·게이트·문턱을 바꾸지 않는다. '
                 '조합별 시험은 하지 않는다 — 21조합 보정 z 3.04 인데 최대 '
                 '조합이 975건으로 표본 조건 1,000 을 못 넘는다(사전등록 §3). '
                 '원장 venue 는 개별이 귀무라 기술 통계로만 낸다(R124 §4). '
                 '현재 시총 미사용 · 원장 mfe/mae 미사용.'),
    }
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print()
    print(f'저장: {OUT}')
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
