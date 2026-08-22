# -*- coding: utf-8 -*-
"""R155 — "증자 한 건 ≈ 다른 것 두 건"을 동등성 검정으로 잰다.

사전등록: docs/PREREG_R155_DILUTION_EQUIVALENCE.md (측정 전 커밋).

  A(D) = Δ(k=1·증자O) · B(D) = Δ(k>=2·증자X) · C(D) = A − B
  D1: C 의 양측 부호검정 — 차이가 있는가
  E1: TOST — 두 단측 부호검정, 둘 다 z >= 2.25 여야 동등
  마진 Δ = 0.170%p (R154 가 발표한 k=1·증자X 중앙값의 절댓값 = 공시
  한 건어치). 새 숫자를 만들지 않았다.

**자기검사(§7)**: 네 집단의 평균·중앙·z 가 R154 발표값과 일치해야
한다(0.001 / 0.01). 못 하면 측정을 중단한다.

"차이가 유의하지 않다"는 "같다"가 아니다 — 그래서 동등성을 따로 잰다.

측정 전용 — 점수·게이트·문턱을 바꾸지 않는다.

    C:/Python314/python.exe scripts/dilution_equivalence_r155.py
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
OUT = os.path.join(PROJ, 'data', 'dilution_equivalence_r155.json')
R154 = os.path.join(PROJ, 'data', 'confluence_dilution_r154.json')
DISC = os.path.join(PROJ, '.portfolio', 'disclosures_daily.jsonl')
BARS = os.path.join(PROJ, '.portfolio', 'daily_bars.jsonl')
MASTER = os.path.join(PROJ, '.portfolio', 'name_master.json')

import disclosure_types as dt                                  # noqa: E402

TYPES = ('자사주·배당', '수주·공급계약', '증자·CB·BW', '투자·설비',
         'M&A·분할', 'IR·안내', '인허가·임상')
DILUTION = '증자·CB·BW'
MAIN_EXIT = 5                  # §1 — R150·R153·R154 와 동일
LOOKBACK = 20
NQ = 5
Z_CRIT = 2.25                  # §6 — R153·R154 의 값 재사용
MARGIN = 0.170                 # §4 — R154 발표 k=1·증자X 중앙값의 절댓값
MIN_EVENTS = 1000              # §6
MIN_DAYS = 300                 # §6
DEV_END = '2026-01-30'
BLIND = ('2026-02-03', '2026-07-15')
BAR_FIRST = '2014-05-30'
TOL_V, TOL_Z = 0.001, 0.01     # §7

_STRIP = re.compile(r'\s+|㈜|\(주\)|주식회사')


def norm(name):
    return _STRIP.sub('', str(name)).upper()


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def sign_z(count, n):
    """이항 부호검정 z — count 가 n 중 '성공' 수."""
    return round((count - n / 2) / math.sqrt(n / 4), 2) if n else None


def sign_test(vals):
    nz = [v for v in vals if v != 0]
    n = len(nz)
    if n == 0:
        return None, 0, 0
    win = sum(1 for v in nz if v > 0)
    return sign_z(win, n), win, n


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


def tost(vals, margin):
    """TOST — 두 단측 부호검정. 둘 다 z >= Z_CRIT 이면 동등."""
    lo_n = [v for v in vals if v != -margin]
    lo_cnt = sum(1 for v in lo_n if v > -margin)
    hi_n = [v for v in vals if v != margin]
    hi_cnt = sum(1 for v in hi_n if v < margin)
    z_lo, z_hi = sign_z(lo_cnt, len(lo_n)), sign_z(hi_cnt, len(hi_n))
    ok = (z_lo is not None and z_hi is not None
          and z_lo >= Z_CRIT and z_hi >= Z_CRIT)
    return dict(margin=margin, z_lower=z_lo, z_upper=z_hi,
                lower_cnt=lo_cnt, lower_n=len(lo_n),
                upper_cnt=hi_cnt, upper_n=len(hi_n), equivalent=ok)


def main():
    print('R155 — "증자 한 건 ≈ 다른 것 두 건" 을 동등성 검정으로 잰다')
    print('사전등록: docs/PREREG_R155_DILUTION_EQUIVALENCE.md')
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

    ev_set = {t: set() for t in TYPES}
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
                ev_set[t].add((code, d))
    types_at = collections.defaultdict(set)
    for t in TYPES:
        for code, d in ev_set[t]:
            ds = bars[code][0]
            i = bisect.bisect_left(ds, d)
            if i < len(ds) and d >= ds[0]:
                types_at[(code, ds[i])].add(t)

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

    per_day = collections.defaultdict(list)
    for c in stocks:
        _ds, _bm, raw = bars[c]
        mk = mkt_of[c]
        for i, b in enumerate(raw):
            d = b[0]
            if d < BAR_FIRST:
                continue
            ret, dd = window(c, d, MAIN_EXIT)
            if ret is None:
                continue
            to = vol = None
            if i + 1 >= LOOKBACK:
                wb = raw[i + 1 - LOOKBACK:i + 1]
                tot = sum(x[4] * x[5] for x in wb) / LOOKBACK
                rr = [wb[j][4] / wb[j - 1][4] - 1
                      for j in range(1, len(wb)) if wb[j - 1][4]]
                if len(rr) >= 2 and tot > 0:
                    to, vol = tot, statistics.pstdev(rr)
            per_day[dd].append((c, ret, to, vol, mk))

    def matched_delta(pick, lo=None, hi=None):
        out = {}
        for d, obs in per_day.items():
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
                tset = types_at.get((c, d), ())
                a = acc[s]
                if tset and pick(tset):
                    a[0] += ret
                    a[1] += 1
                elif not tset:
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

    GROUPS = {
        'k=1·증자X': lambda s: len(s) == 1 and DILUTION not in s,
        'k>=2·증자X': lambda s: len(s) >= 2 and DILUTION not in s,
        'k=1·증자O': lambda s: len(s) == 1 and DILUTION in s,
        'k>=2·증자O': lambda s: len(s) >= 2 and DILUTION in s,
    }

    # ── 자기검사 (사전등록 §7) — 네 집단이 R154 와 일치하는가 ───────────
    with open(R154, encoding='utf-8') as f:
        prev = (json.load(f).get('groups') or {})
    print('■ 자기검사 — 네 집단이 R154 발표값과 일치하는가 (§7)')
    checks, bad = [], []
    dev_groups = {}
    for gname, gp in GROUPS.items():
        g = matched_delta(gp, hi=DEV_END)
        s = summarize([v for v, _ in g.values()],
                      sum(n for _, n in g.values()))
        dev_groups[gname] = dict(summary=s, daily=g)
        p = prev.get(gname) or {}
        ok = all([
            s['mean_pp'] is not None and p.get('mean_pp') is not None
            and abs(s['mean_pp'] - p['mean_pp']) <= TOL_V + 1e-9,
            s['median_pp'] is not None and p.get('median_pp') is not None
            and abs(s['median_pp'] - p['median_pp']) <= TOL_V + 1e-9,
            s['sign_z'] is not None and p.get('sign_z') is not None
            and abs(s['sign_z'] - p['sign_z']) <= TOL_Z + 1e-9,
        ])
        checks.append(dict(name=gname, mean=s['mean_pp'],
                           median=s['median_pp'], z=s['sign_z'],
                           r154_mean=p.get('mean_pp'),
                           r154_median=p.get('median_pp'),
                           r154_z=p.get('sign_z')))
        print(f'   {"OK " if ok else "!! "}{gname:<12} 평균 {s["mean_pp"]} '
              f'/ 중앙 {s["median_pp"]} / z {s["sign_z"]}  ←  R154 '
              f'{p.get("mean_pp")} / {p.get("median_pp")} / {p.get("sign_z")}')
        if not ok:
            bad.append(gname)
    if bad:
        print()
        print(f'■ 재현 실패 {len(bad)}건 — 측정을 중단한다 (사전등록 §7). '
              f'허용 오차를 늘리지 않는다.')
        return 2

    # ── 짝 차이 C(D) ───────────────────────────────────────────────────
    def paired(lo=None, hi=None, b_pick=None):
        A = matched_delta(GROUPS['k=1·증자O'], lo, hi)
        B = matched_delta(b_pick or GROUPS['k>=2·증자X'], lo, hi)
        both = sorted(set(A) & set(B))
        return ([A[d][0] - B[d][0] for d in both],
                sum(B[d][1] for d in both), both)

    C, n_ev, days = paired(hi=DEV_END)
    s = summarize(C, n_ev)
    e = tost(C, MARGIN)
    sample_ok = n_ev >= MIN_EVENTS and len(days) >= MIN_DAYS

    print()
    print(f'■ 짝 차이 C = Δ(증자 한 건) − Δ(증자 아닌 것 둘 이상)')
    print(f'   짝 날짜 {len(days):,} · k>=2·증자X 이벤트 {n_ev:,}'
          f'  (표본 조건 {"통과" if sample_ok else "미달"})')
    print(f'   평균 {s["mean_pp"]}%p · 중앙 {s["median_pp"]}%p · '
          f'승률 {s["win_pct"]}% (필요 {s["need_pct"]}%)')
    print()
    print(f'■ D1 — 차이가 있는가 (양측 부호검정, 문턱 {Z_CRIT})')
    d1_ok = s['sign_z'] is not None and abs(s['sign_z']) >= Z_CRIT
    print(f'   z = {s["sign_z"]}  →  {"차이 있음" if d1_ok else "차이 못 봄"}')
    print()
    print(f'■ E1 — 마진 안에서 같은가 (TOST, 마진 ±{MARGIN}%p, '
          f'두 단측 모두 {Z_CRIT} 이상)')
    print(f'   아래(C > −{MARGIN}): {e["lower_cnt"]:,}/{e["lower_n"]:,} '
          f'→ z {e["z_lower"]}')
    print(f'   위  (C < +{MARGIN}): {e["upper_cnt"]:,}/{e["upper_n"]:,} '
          f'→ z {e["z_upper"]}')
    print(f'   → {"동등" if e["equivalent"] else "동등 못 보임"}')

    if not sample_ok:
        verdict = '표본 미달 — 판정 보류'
    elif not d1_ok and e['equivalent']:
        verdict = '동등하다 — "증자 한 건 ≈ 다른 것 두 건" 성립'
    elif not d1_ok and not e['equivalent']:
        verdict = '못 가린다 — 차이도 동등성도 못 보인다 (표본 부족)'
    elif d1_ok and not e['equivalent']:
        verdict = '다르다 — 주장 기각'
    else:
        verdict = '통계적으로 다르나 실질적으로 동등 (차이 < 마진)'
    print()
    print(f'■ 판정: {verdict}')

    blind = None
    if sample_ok and (d1_ok or e['equivalent']):
        cb, nb, db = paired(lo=BLIND[0], hi=BLIND[1])
        sb = summarize(cb, nb)
        eb = tost(cb, MARGIN)
        blind = dict(summary=sb, tost=eb)
        print()
        print(f'■ blind 확인 (사전등록 §6)')
        print(f'   날짜 {sb["days"]} · 이벤트 {sb["events"]:,} · 중앙 '
              f'{sb["median_pp"]}%p · D1 z {sb["sign_z"]} · '
              f'TOST z {eb["z_lower"]}/{eb["z_upper"]}')

    # ── 민감도 (판정에 쓰지 않는다) ────────────────────────────────────
    print()
    print('■ 민감도 (판정에 쓰지 않는다 — 사전등록 §8)')
    c2, n2, d2 = paired(hi=DEV_END,
                        b_pick=lambda s2: len(s2) == 2 and DILUTION not in s2)
    s2 = summarize(c2, n2)
    e2 = tost(c2, MARGIN)
    print(f'   k=2 정확히: 날짜 {s2["days"]:,} · 이벤트 {n2:,} · 중앙 '
          f'{s2["median_pp"]}%p · D1 z {s2["sign_z"]} · TOST '
          f'{e2["z_lower"]}/{e2["z_upper"]} → '
          f'{"동등" if e2["equivalent"] else "동등 못 보임"}')
    print(f'   평균 기준 차이: {s["mean_pp"]}%p '
          f'(판정은 중앙값으로 한다 — R154 에서 평균과 중앙이 방향까지 '
          f'어긋났다)')

    # ── 사후 진단 (판정에 쓰지 않는다) — 얼마나 더 있어야 하나 ─────────
    #   "못 가린다"로 끝내면 '얼마나 못 가리는지'를 안 적는 것이다.
    #   관측 비율에서 z 2.25 에 닿는 데 필요한 날짜를 역산한다.
    #   물리 상한은 246거래일/년 × 14.9년 (R129 유도값).
    def need_days(cnt, n):
        if not n:
            return None
        p = cnt / n
        if p <= 0.5:
            return None                     # 방향이 반대면 늘려도 안 닿는다
        return int(math.ceil((Z_CRIT / (2 * (p - 0.5))) ** 2))

    nd_lo = need_days(e['lower_cnt'], e['lower_n'])
    nd_hi = need_days(e['upper_cnt'], e['upper_n'])
    ceiling = int(246 * 14.9)
    diag = dict(observed_days=len(days), need_days_lower=nd_lo,
                need_days_upper=nd_hi, physical_ceiling_days=ceiling,
                note='사후 진단 — 판정에 쓰지 않는다. 관측 비율이 그대로일 '
                     '때 z 2.25 에 닿는 날짜 수. 물리 상한은 246일/년 × '
                     '14.9년(R129).')
    print()
    print('■ 사후 진단 (판정에 쓰지 않는다) — 동등성을 보이려면 얼마나 더?')
    print(f'   지금 짝 날짜 {len(days):,}일')
    print(f'   아래 단측: 관측 {e["lower_cnt"]}/{e["lower_n"]} '
          f'({e["lower_cnt"] / e["lower_n"] * 100:.1f}%) → 필요 '
          f'{nd_lo:,}일' if nd_lo else '   아래 단측: 방향이 반대 — 늘려도 안 닿는다')
    print(f'   위  단측: 관측 {e["upper_cnt"]}/{e["upper_n"]} '
          f'({e["upper_cnt"] / e["upper_n"] * 100:.1f}%) → 필요 '
          f'{nd_hi:,}일' if nd_hi else '   위 단측: 방향이 반대 — 늘려도 안 닿는다')
    print(f'   물리 상한 {ceiling:,}일 (246일/년 × 14.9년) — '
          f'{"상한 안" if (nd_lo and nd_hi and max(nd_lo, nd_hi) <= ceiling) else "상한 밖"}')

    doc = {
        'made': date.today().isoformat(),
        'made_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'prereg': 'docs/PREREG_R155_DILUTION_EQUIVALENCE.md',
        'criteria': dict(z_crit=Z_CRIT, margin=MARGIN, min_events=MIN_EVENTS,
                         min_days=MIN_DAYS, main_exit=MAIN_EXIT,
                         lookback=LOOKBACK, nq=NQ, dev_end=DEV_END,
                         blind=list(BLIND), dilution=DILUTION,
                         tol_v=TOL_V, tol_z=TOL_Z,
                         margin_source='R154 k=1·증자X 중앙값의 절댓값'),
        'repro_check': checks,
        'groups': {k: v['summary'] for k, v in dev_groups.items()},
        'paired': dict(summary=s, sample_ok=sample_ok, d1_pass=d1_ok),
        'tost': e, 'verdict': verdict, 'blind': blind,
        'sensitivity': dict(k2_exact=dict(summary=s2, tost=e2)),
        'diagnostics': diag,
        'note': ('측정 전용 — 점수·게이트·문턱을 바꾸지 않는다. '
                 '"차이가 유의하지 않다"는 "같다"가 아니므로 동등성을 '
                 'TOST 로 따로 쟀다. 마진은 R154 가 이미 발표한 값이라 '
                 '이번 결과를 보고 고른 것이 아니다. 판정은 중앙값으로 '
                 '한다. 인과 주장 없음 · 원장 미조인 · 시총 미사용.'),
    }
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print()
    print(f'저장: {OUT}')
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
