# -*- coding: utf-8 -*-
"""R154 — 겹침은 진짜인가, 희석(증자·CB·BW) 쏠림의 다른 얼굴인가.

사전등록: docs/PREREG_R154_CONFLUENCE_VS_DILUTION.md (측정 전 커밋).
판정 기준은 그 문서 §4 의 값을 그대로 묻는다.

  창·매칭은 R150·R153 과 동일
  T1: Δ(k>=2·증자X) − Δ(k=1·증자X) ← 본 질문
  T2: Δ(k>=2·증자O) − Δ(k=1·증자O)
  문턱 Bonferroni 2 → z 2.25 · 이벤트 >=1,000 그리고 날짜 >=300

**자기검사(§6)**: 갈래 없이 돌리면 R153 의 T2 (Δ -0.393 · z -4.91) 를
재현해야 한다. 못 하면 측정을 중단한다.

측정 전용 — 점수·게이트·문턱을 바꾸지 않는다.

    C:/Python314/python.exe scripts/confluence_dilution_r154.py
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
OUT = os.path.join(PROJ, 'data', 'confluence_dilution_r154.json')
R153 = os.path.join(PROJ, 'data', 'event_confluence_r153.json')
DISC = os.path.join(PROJ, '.portfolio', 'disclosures_daily.jsonl')
BARS = os.path.join(PROJ, '.portfolio', 'daily_bars.jsonl')
MASTER = os.path.join(PROJ, '.portfolio', 'name_master.json')

import disclosure_types as dt                                  # noqa: E402

TYPES = ('자사주·배당', '수주·공급계약', '증자·CB·BW', '투자·설비',
         'M&A·분할', 'IR·안내', '인허가·임상')
DILUTION = '증자·CB·BW'        # 사전등록 §0 — 가르는 축
MAIN_EXIT = 5                  # §1 — R150·R153 과 동일
LOOKBACK = 20
NQ = 5
Z_CRIT = 2.25                  # §4
MIN_EVENTS = 1000              # §4
MIN_DAYS = 300                 # §4
DEV_END = '2026-01-30'
BLIND = ('2026-02-03', '2026-07-15')
BAR_FIRST = '2014-05-30'
#: §6 자기검사 — R153 이 발표한 T2
R153_D, R153_Z = -0.393, -4.91
TOL_D, TOL_Z = 0.001, 0.01

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
    print('R154 — 겹침은 진짜인가, 희석 쏠림의 다른 얼굴인가')
    print('사전등록: docs/PREREG_R154_CONFLUENCE_VS_DILUTION.md')
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

    # 공시 → (코드, 접수일) 집합 → 거래일 (R148~R153 과 동일)
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
    print(f'■ 창 {sum(len(v) for v in per_day.values()):,}개 · '
          f'날짜 {len(per_day):,}일')

    def matched_delta(pick, lo=None, hi=None):
        """pick(유형집합) 이 참인 이벤트의 층화 매칭 델타 — 날짜별."""
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
                elif not tset:                 # 대조 = 7유형 어느 것도 없음
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

    def contrast(pick_hi, pick_lo, lo=None, hi=None):
        """두 집단의 매칭 델타 차이 — 둘 다 있는 날짜만."""
        a = matched_delta(pick_hi, lo, hi)
        b = matched_delta(pick_lo, lo, hi)
        both = sorted(set(a) & set(b))
        return summarize([a[d][0] - b[d][0] for d in both],
                         sum(a[d][1] for d in both))

    # ── 자기검사 (사전등록 §6) — 갈래 없이 R153 T2 재현 ────────────────
    print()
    print('■ 자기검사 — 갈래 없이 R153 의 T2 를 재현하는가 (§6)')
    chk = contrast(lambda s: len(s) >= 2, lambda s: len(s) == 1, hi=DEV_END)
    ok_d = (chk['mean_pp'] is not None
            and abs(chk['mean_pp'] - R153_D) <= TOL_D + 1e-9)
    ok_z = (chk['sign_z'] is not None
            and abs(chk['sign_z'] - R153_Z) <= TOL_Z + 1e-9)
    print(f"   {'OK ' if ok_d else '!! '}Δ  재현 {chk['mean_pp']} · "
          f"R153 {R153_D}")
    print(f"   {'OK ' if ok_z else '!! '}z  재현 {chk['sign_z']} · "
          f"R153 {R153_Z}")
    if not (ok_d and ok_z):
        print()
        print('■ 재현 실패 — 측정을 중단한다 (사전등록 §6). '
              '허용 오차를 늘리지 않는다.')
        return 2

    # ── 주 시험 ────────────────────────────────────────────────────────
    def no_dil(s):
        return DILUTION not in s

    def has_dil(s):
        return DILUTION in s

    tests = (
        ('T1_증자없는 겹침', lambda s: len(s) >= 2 and no_dil(s),
         lambda s: len(s) == 1 and no_dil(s),
         '증자 없는 겹침에서도 증폭이 남는가'),
        ('T2_증자있는 겹침', lambda s: len(s) >= 2 and has_dil(s),
         lambda s: len(s) == 1 and has_dil(s),
         '증자가 있을 때 겹침이 더 얹히는가'),
    )
    results = {}
    print()
    print(f'{"시험":<20}{"이벤트":>8}{"날짜":>7}{"평균%p":>9}{"중앙%p":>9}'
          f'{"승률":>7}{"필요":>7}{"z":>7}  판정')
    for name, ph, pl, q in tests:
        s = contrast(ph, pl, hi=DEV_END)
        sample_ok = s['events'] >= MIN_EVENTS and s['days'] >= MIN_DAYS
        z_ok = s['sign_z'] is not None and abs(s['sign_z']) >= Z_CRIT
        if not sample_ok:
            verdict = '표본 미달'
        elif z_ok:
            verdict = ('증폭이 남는다(−)' if s['sign_z'] < 0 else '방향 반대(+)')
        else:
            verdict = '미달 — 못 가른다'
        blind = contrast(ph, pl, lo=BLIND[0], hi=BLIND[1]) \
            if (sample_ok and z_ok) else None
        results[name] = dict(summary=s, question=q, sample_ok=sample_ok,
                             z_ok=z_ok, verdict=verdict, blind=blind)
        print(f'{name:<20}{s["events"]:>8,}{s["days"]:>7,}'
              f'{(s["mean_pp"] or 0):>9.3f}{(s["median_pp"] or 0):>9.3f}'
              f'{(s["win_pct"] or 0):>6.1f}%{(s["need_pct"] or 0):>6.1f}%'
              f'{(s["sign_z"] if s["sign_z"] is not None else 0):>7.2f}'
              f'  {verdict}')

    passed = [n for n, r in results.items() if r['sample_ok'] and r['z_ok']]
    print()
    if passed:
        print('■ blind 확인 (문턱 통과분만 — 사전등록 §4)')
        for n in passed:
            b = results[n]['blind']
            print(f"   {n}: 이벤트 {b['events']:,} · 날짜 {b['days']} · "
                  f"평균 {b['mean_pp']}%p · z {b['sign_z']}")
    else:
        print('■ 문턱을 넘은 시험이 없다 — blind 를 열지 않는다')

    # ── 참고 (판정에 쓰지 않는다) — 네 집단의 절대 위치 ────────────────
    print()
    print('■ 참고 (판정에 쓰지 않는다) — 네 집단의 매칭 델타')
    groups = {}
    for gname, gp in (('k>=2·증자X', lambda s: len(s) >= 2 and no_dil(s)),
                      ('k=1·증자X', lambda s: len(s) == 1 and no_dil(s)),
                      ('k>=2·증자O', lambda s: len(s) >= 2 and has_dil(s)),
                      ('k=1·증자O', lambda s: len(s) == 1 and has_dil(s))):
        g = matched_delta(gp, hi=DEV_END)
        gs = summarize([v for v, _ in g.values()],
                       sum(n for _, n in g.values()))
        groups[gname] = gs
        print(f'   {gname:<12} 이벤트 {gs["events"]:>7,} · 날짜 '
              f'{gs["days"]:>5,} · 평균 {gs["mean_pp"]:>7.3f}%p · '
              f'중앙 {gs["median_pp"]:>7.3f}%p · z {gs["sign_z"]:>6.2f}')

    doc = {
        'made': date.today().isoformat(),
        'made_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'prereg': 'docs/PREREG_R154_CONFLUENCE_VS_DILUTION.md',
        'criteria': dict(z_crit=Z_CRIT, min_events=MIN_EVENTS,
                         min_days=MIN_DAYS, main_exit=MAIN_EXIT,
                         lookback=LOOKBACK, nq=NQ, dev_end=DEV_END,
                         blind=list(BLIND), n_tests=2, dilution=DILUTION,
                         r153_delta=R153_D, r153_z=R153_Z,
                         tol_d=TOL_D, tol_z=TOL_Z),
        'self_check': dict(delta=chk['mean_pp'], z=chk['sign_z'],
                           r153_delta=R153_D, r153_z=R153_Z, passed=True),
        'tests': results, 'passed': passed, 'groups': groups,
        'note': ('측정 전용 — 점수·게이트·문턱을 바꾸지 않는다. '
                 '창·매칭은 R150·R153 과 동일. 현재 시총 미사용(누출). '
                 '원장 미조인 · mfe/mae 미사용. 조합별 시험 없음.'),
    }
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print()
    print(f'저장: {OUT}')
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
