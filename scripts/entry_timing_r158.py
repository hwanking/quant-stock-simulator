# -*- coding: utf-8 -*-
"""R158 — 효과는 언제 사라지는가 (진입 시점 자체를 잰다).

사전등록: docs/PREREG_R158_ENTRY_TIMING.md (측정 전 커밋).
R151 §5 가 "해석이지 측정이 아니다"라고 못 박은 문장을 측정으로 바꾼다.

  진입 = 거래일 D0+L 의 시가 · 청산 = D0+L+4 의 종가 (보유 5거래일 고정)
  L = 1 은 R148~R156 의 창과 정확히 같다
  층화는 언제나 D0 기준 (시장 × 거래대금 5분위 × 변동성 5분위)
  대조 = 그날 D0 에 7유형 어느 공시도 없는 종목
  L in {1,2,3,5,10} · 문턱 Bonferroni 5 → z 2.58

**자기검사(§5)**: 자사주·배당 단일 유형 · L=1 이 R150 의 Δ +0.048 ·
z -3.42 를 재현해야 한다. 못 하면 측정을 중단한다.

측정 전용 — 점수·게이트·문턱을 바꾸지 않는다.

    C:/Python314/python.exe scripts/entry_timing_r158.py
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
OUT = os.path.join(PROJ, 'data', 'entry_timing_r158.json')
DISC = os.path.join(PROJ, '.portfolio', 'disclosures_daily.jsonl')
BARS = os.path.join(PROJ, '.portfolio', 'daily_bars.jsonl')
MASTER = os.path.join(PROJ, '.portfolio', 'name_master.json')

import disclosure_types as dt                                  # noqa: E402

TYPES = ('자사주·배당', '수주·공급계약', '증자·CB·BW', '투자·설비',
         'M&A·분할', 'IR·안내', '인허가·임상')
MATERIAL6 = tuple(t for t in TYPES if t != 'IR·안내')   # §6 민감도
LAGS = (1, 2, 3, 5, 10)        # §3 — 진입 지연
HOLD = 5                       # §2 — 보유 거래일 고정
LOOKBACK = 20                  # §2 — R150 과 동일
NQ = 5
Z_CRIT = 2.58                  # §4 — Bonferroni 5, 올림
MIN_EVENTS = 1000              # §4 — 채택값
MIN_DAYS = 300                 # §4 — 채택값
DEV_END = '2026-01-30'
BLIND = ('2026-02-03', '2026-07-15')
BAR_FIRST = '2014-05-30'
#: §5 자기검사 — R150 이 발표한 자사주·배당 매칭 결과
R150_TYPE, R150_D, R150_Z = '자사주·배당', 0.048, -3.42
TOL_V, TOL_Z = 0.001, 0.01

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
    print('R158 — 효과는 언제 사라지는가 (진입 시점 자체)')
    print('사전등록: docs/PREREG_R158_ENTRY_TIMING.md')
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
    mult_at = collections.defaultdict(collections.Counter)
    for t in TYPES:
        for code, d in ev_set[t]:
            ds = bars[code][0]
            i = bisect.bisect_left(ds, d)
            if i < len(ds) and d >= ds[0]:
                types_at[(code, ds[i])].add(t)
                mult_at[(code, ds[i])][t] += 1

    def leg(code, d0, lag, hold):
        """진입 D0+lag 시가 → 청산 D0+lag+hold-1 종가, 시장 초과(%)."""
        ds, bm, _ = bars[code]
        i0 = bisect.bisect_left(ds, d0)
        if i0 >= len(ds) or d0 < ds[0]:
            return None
        a, b = i0 + lag, i0 + lag + hold - 1
        if b >= len(ds):
            return None
        d_in, d_out = ds[a], ds[b]
        ix = idx[mkt_of[code]]
        if ix is None or d_in not in ix[1] or d_out not in ix[1]:
            return None
        o, c = bm[d_in][1], bm[d_out][4]
        io_, ic = ix[1][d_in][1], ix[1][d_out][4]
        if not o or not io_:
            return None
        return (c / o - 1) * 100 - (ic / io_ - 1) * 100

    def daily_leg(code, d0, k):
        """하루치 조각 — k=0 이면 D0 종가→D+1 시가(밤사이 갭),
        k>=1 이면 D0+k 의 시가→종가(장중). 기술 통계 전용."""
        ds, bm, _ = bars[code]
        i0 = bisect.bisect_left(ds, d0)
        if i0 >= len(ds) or d0 < ds[0]:
            return None
        ix = idx[mkt_of[code]]
        if ix is None:
            return None
        if k == 0:
            if i0 + 1 >= len(ds):
                return None
            d_a, d_b = ds[i0], ds[i0 + 1]
            p0, p1 = bm[d_a][4], bm[d_b][1]
            if d_a not in ix[1] or d_b not in ix[1]:
                return None
            q0, q1 = ix[1][d_a][4], ix[1][d_b][1]
        else:
            if i0 + k >= len(ds):
                return None
            d_a = ds[i0 + k]
            if d_a not in ix[1]:
                return None
            p0, p1 = bm[d_a][1], bm[d_a][4]
            q0, q1 = ix[1][d_a][1], ix[1][d_a][4]
        if not p0 or not q0:
            return None
        return (p1 / p0 - 1) * 100 - (q1 / q0 - 1) * 100

    # ── D0 코호트: 층화 재료는 언제나 D0 기준 ─────────────────────────
    per_day = collections.defaultdict(list)   # D0 -> [(code, to, vol, mkt)]
    for c in stocks:
        _ds, _bm, raw = bars[c]
        mk = mkt_of[c]
        for i, b in enumerate(raw):
            d0 = b[0]
            if d0 < BAR_FIRST:
                continue
            to = vol = None
            if i + 1 >= LOOKBACK:
                wb = raw[i + 1 - LOOKBACK:i + 1]
                tot = sum(x[4] * x[5] for x in wb) / LOOKBACK
                rr = [wb[j][4] / wb[j - 1][4] - 1
                      for j in range(1, len(wb)) if wb[j - 1][4]]
                if len(rr) >= 2 and tot > 0:
                    to, vol = tot, statistics.pstdev(rr)
            if to is None:
                continue                       # 층을 못 만드는 날은 제외
            per_day[d0].append((c, to, vol, mk))
    print(f'■ D0 코호트 {len(per_day):,}일 · '
          f'{sum(len(v) for v in per_day.values()):,}관측 · 종목 '
          f'{len(stocks):,}')

    def matched(pick, retfn, lo=None, hi=DEV_END, weighted=False):
        """pick 이 참인 이벤트의 층화 매칭 델타 — 날짜별.

        **분위는 '이 창의 수익이 있는 관측' 안에서 매긴다.** 처음에는
        층화 재료가 있는 모든 관측에서 매겼는데, 그러면 R150 과 분위
        경계가 어긋나 자기검사가 걸렸다(Δ 0.016 vs 0.048). 사전등록
        §2 는 매칭 변수를 D0 에서 만든다고만 했지 **어느 집합에서
        분위를 매기는지**를 안 적었다 — 판정 기준은 그대로 두고
        R150 과 같은 집합을 쓰도록 고쳤다.
        """
        out = {}
        for d0, cohort in per_day.items():
            if (lo is not None and d0 < lo) or (hi is not None and d0 > hi):
                continue
            obs = []
            for (c, to, vol, mk) in cohort:
                v = retfn(c, d0)
                if v is not None:
                    obs.append((c, v, to, vol, mk))
            if not obs:
                continue
            strata = {}
            for mk in ('KOSPI', 'KOSDAQ'):
                sub = [i for i, o in enumerate(obs) if o[4] == mk]
                if not sub:
                    continue
                n = len(sub)
                tq = quintile(sorted(sub, key=lambda i: obs[i][2]), n)
                vq = quintile(sorted(sub, key=lambda i: obs[i][3]), n)
                for i in sub:
                    strata[i] = (mk, tq[i], vq[i])
            acc = collections.defaultdict(lambda: [0.0, 0, 0.0, 0])
            for i, (c, v, _to, _vol, _mk) in enumerate(obs):
                s = strata.get(i)
                if s is None:
                    continue
                tset = types_at.get((c, d0), ())
                a = acc[s]
                if tset and pick(tset):
                    w = (sum(mult_at[(c, d0)][t] for t in tset)
                         if weighted else 1)
                    a[0] += v * w
                    a[1] += w
                elif not tset:
                    a[2] += v
                    a[3] += 1
            num = den = 0.0
            for a in acc.values():
                if a[1] > 0 and a[3] > 0:
                    num += (a[0] / a[1] - a[2] / a[3]) * a[1]
                    den += a[1]
            if den > 0:
                out[d0] = (num / den, int(den))
        return out

    # ── 자기검사 (사전등록 §5) ─────────────────────────────────────────
    print()
    print('■ 자기검사 — 자사주·배당 · L=1 이 R150 을 재현하는가 (§5)')
    gchk = matched(lambda st: R150_TYPE in st,
                   lambda c, d: leg(c, d, 1, HOLD), weighted=True)
    chk = summarize([v for v, _ in gchk.values()],
                    sum(n for _, n in gchk.values()))
    ok_d = (chk['mean_pp'] is not None
            and abs(chk['mean_pp'] - R150_D) <= TOL_V + 1e-9)
    ok_z = (chk['sign_z'] is not None
            and abs(chk['sign_z'] - R150_Z) <= TOL_Z + 1e-9)
    print(f"   {'OK ' if ok_d else '!! '}Δ  재현 {chk['mean_pp']} · "
          f"R150 {R150_D}")
    print(f"   {'OK ' if ok_z else '!! '}z  재현 {chk['sign_z']} · "
          f"R150 {R150_Z}")
    if not (ok_d and ok_z):
        print()
        print('■ 재현 실패 — 측정을 중단한다 (사전등록 §5). '
              '허용 오차를 늘리지 않는다.')
        return 2

    # ── 주 시험 — L 을 밀어 가며 ───────────────────────────────────────
    any_ev = (lambda st: True)          # 7유형 중 하나 이상 (선택 없음)
    results = {}
    print()
    print(f'{"L":>3}{"진입":>12}{"이벤트":>9}{"날짜":>7}{"평균%p":>9}'
          f'{"중앙%p":>9}{"승률":>7}{"필요":>7}{"z":>7}  판정')
    for L in LAGS:
        g = matched(any_ev, lambda c, d, _l=L: leg(c, d, _l, HOLD))
        s = summarize([v for v, _ in g.values()],
                      sum(n for _, n in g.values()))
        sample_ok = s['events'] >= MIN_EVENTS and s['days'] >= MIN_DAYS
        z_ok = s['sign_z'] is not None and abs(s['sign_z']) >= Z_CRIT
        if not sample_ok:
            verdict = '표본 미달'
        elif z_ok:
            verdict = ('불이익 있음(−)' if s['sign_z'] < 0 else '유리(+)')
        else:
            verdict = '미달 — 불이익 안 보임'
        results[str(L)] = dict(lag=L, summary=s, sample_ok=sample_ok,
                               z_ok=z_ok, verdict=verdict, blind=None)
        print(f'{L:>3}{f"D+{L} 시가":>12}{s["events"]:>9,}{s["days"]:>7,}'
              f'{(s["mean_pp"] or 0):>9.3f}{(s["median_pp"] or 0):>9.3f}'
              f'{(s["win_pct"] or 0):>6.1f}%{(s["need_pct"] or 0):>6.1f}%'
              f'{(s["sign_z"] if s["sign_z"] is not None else 0):>7.2f}'
              f'  {verdict}')

    passed = [k for k, r in results.items() if r['sample_ok'] and r['z_ok']]
    print()
    if passed:
        print('■ blind 확인 (문턱 통과분만 — 사전등록 §4)')
        for k in passed:
            L = results[k]['lag']
            gb = matched(any_ev, lambda c, d, _l=L: leg(c, d, _l, HOLD),
                         lo=BLIND[0], hi=BLIND[1])
            sb = summarize([v for v, _ in gb.values()],
                           sum(n for _, n in gb.values()))
            results[k]['blind'] = sb
            print(f"   L={L}: 이벤트 {sb['events']:,} · 날짜 {sb['days']} · "
                  f"중앙 {sb['median_pp']}%p · z {sb['sign_z']}")
    else:
        print('■ 문턱을 넘은 L 이 없다 — blind 를 열지 않는다')

    # ── 기술 통계 (판정에 쓰지 않는다 — 사전등록 §6) ───────────────────
    print()
    print('■ 기술 통계 (판정에 쓰지 않는다)')
    mat6 = {}
    for L in LAGS:
        g6 = matched(lambda st: any(t in MATERIAL6 for t in st),
                     lambda c, d, _l=L: leg(c, d, _l, HOLD))
        s6 = summarize([v for v, _ in g6.values()],
                       sum(n for _, n in g6.values()))
        mat6[str(L)] = s6
    print('   6유형(IR 제외): ' + ' · '.join(
        f'L={L}: z {mat6[str(L)]["sign_z"]}' for L in LAGS))

    pieces = {}
    print('   하루씩 쌓은 초과수익 (D0 종가 기준 · 밤사이 갭은 거래 신호가 '
          '아니다):')
    for k in range(0, 11):
        gp = matched(any_ev, lambda c, d, _k=k: daily_leg(c, d, _k))
        sp = summarize([v for v, _ in gp.values()],
                       sum(n for _, n in gp.values()))
        lab = '밤사이 갭' if k == 0 else f'D+{k} 장중'
        pieces[str(k)] = dict(label=lab, summary=sp)
        print(f'      {lab:<10} 중앙 {(sp["median_pp"] or 0):>7.3f}%p · '
              f'z {sp["sign_z"]}')

    doc = {
        'made': date.today().isoformat(),
        'made_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'prereg': 'docs/PREREG_R158_ENTRY_TIMING.md',
        'criteria': dict(z_crit=Z_CRIT, lags=list(LAGS), hold=HOLD,
                         min_events=MIN_EVENTS, min_days=MIN_DAYS,
                         lookback=LOOKBACK, nq=NQ, dev_end=DEV_END,
                         blind=list(BLIND), n_tests=len(LAGS),
                         r150_delta=R150_D, r150_z=R150_Z,
                         tol_v=TOL_V, tol_z=TOL_Z),
        'self_check': dict(delta=chk['mean_pp'], z=chk['sign_z'],
                           r150_delta=R150_D, r150_z=R150_Z, passed=True),
        'tests': results, 'passed': passed,
        'descriptive': dict(material6=mat6, daily_pieces=pieces,
                            note='판정에 쓰지 않는다. 밤사이 갭은 공시 '
                                 '자체를 담고 있어 거래 신호가 아니다.'),
        'note': ('측정 전용 — 점수·게이트·문턱을 바꾸지 않는다. '
                 'D0 종가 진입은 누출이라 시험하지 않는다. 층화는 언제나 '
                 'D0 기준. 새 문턱·표본 조건 없음(채택값 재사용). '
                 '원장 미조인 · mfe/mae 미사용 · 현재 시총 미사용.'),
    }
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print()
    print(f'저장: {OUT}')
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
