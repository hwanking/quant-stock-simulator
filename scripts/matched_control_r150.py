# -*- coding: utf-8 -*-
"""R150 — 매칭 대조군: R149 의 음(−)은 공시 때문인가 구성 때문인가.

사전등록: docs/PREREG_R150_MATCHED_CONTROL.md (측정 전 커밋).
판정 기준은 그 문서 §4 의 값을 그대로 묻는다.

  층 = (시장, 거래대금 5분위, 변동성 5분위) — 그날 횡단면 순위로 정한다
  Δ(T,D) = 층별 (이벤트평균 − 대조평균) 을 이벤트 수로 가중평균
  창은 R148/R149 와 동일 · 문턱 z 2.70 · 이벤트 ≥1,000 그리고 날짜 ≥300

**재구현 자기검사(사전등록 §5)**: 층을 하나로 합치고 **모든 창**을
쓰면 R149 의 유형별 Δ 평균 7개를 0.001%p 이내로 재현해야 한다. 못
하면 측정을 중단한다. (사전등록은 이 조건을 '층 계산 가능한 창'으로
적었는데 §2 의 20거래일 제외와 모순이었다 — 판정 기준은 그대로 두고
검사가 같은 표본끼리 견주도록 고쳤다. 결과 문서 §1 에 적는다.)

측정 전용 — 점수·게이트·문턱을 바꾸지 않는다.

    C:/Python314/python.exe scripts/matched_control_r150.py
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
OUT = os.path.join(PROJ, 'data', 'matched_control_r150.json')
R149 = os.path.join(PROJ, 'data', 'event_vs_baseline_r149.json')
DISC = os.path.join(PROJ, '.portfolio', 'disclosures_daily.jsonl')
BARS = os.path.join(PROJ, '.portfolio', 'daily_bars.jsonl')
MASTER = os.path.join(PROJ, '.portfolio', 'name_master.json')

import disclosure_types as dt                                  # noqa: E402

TYPES = ('자사주·배당', '수주·공급계약', '증자·CB·BW', '투자·설비',
         'M&A·분할', 'IR·안내', '인허가·임상')
MAIN_EXIT = 5                  # 사전등록 §1 — R148/R149 와 동일한 창
LOOKBACK = 20                  # §2 — 매칭 변수의 직전 거래일 수
NQ = 5                         # §2 — 5분위
Z_CRIT = 2.70                  # §4
MIN_EVENTS = 1000              # §4
MIN_DAYS = 300                 # §4
DEV_END = '2026-01-30'         # §4
BLIND = ('2026-02-03', '2026-07-15')
BAR_FIRST = '2014-05-30'
REPRO_TOL = 0.001              # §5

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
    """순위 → 5분위. 동점은 순위 순서를 따른다(그날 횡단면 규칙)."""
    out = {}
    for rank, i in enumerate(sorted_idx):
        out[i] = min(NQ - 1, rank * NQ // n)
    return out


def main():
    print('R150 — 매칭 대조군: R149 의 음(−)은 공시인가 구성인가')
    print('사전등록: docs/PREREG_R150_MATCHED_CONTROL.md')
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
    print(f'■ 일봉 {len(stocks):,}종목 · {BAR_FIRST} ~ '
          f'{max(bars[c][0][-1] for c in stocks)}')

    with open(MASTER, encoding='utf-8') as f:
        m = json.load(f)
    n2c = collections.defaultdict(set)
    for r in m['rows']:
        n2c[norm(r['name'])].add(r['code'])
    name2code = {k: next(iter(v)) for k, v in n2c.items() if len(v) == 1}

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
    # 접수일 → 거래일 매핑 (R148/R149 와 동일 · 배수 유지)
    ev_map = {t: collections.Counter() for t in TYPES}
    any_ev = collections.defaultdict(set)
    for t in TYPES:
        for c, d in ev[t]:
            ds = bars[c][0]
            i = bisect.bisect_left(ds, d)
            if i >= len(ds) or d < ds[0]:
                continue
            ev_map[t][(c, ds[i])] += 1
            any_ev[(c, ds[i])].add(t)

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

    # ── 날짜별 관측: (코드, 수익, 거래대금, 변동성, 시장) ──────────────
    #   거래대금·변동성은 D0 포함 직전 20거래일만 쓴다 (시점 안전).
    per_day = collections.defaultdict(list)
    n_win = n_nostat = 0
    for c in stocks:
        ds, _bm, raw = bars[c]
        mk = mkt_of[c]
        for i, b in enumerate(raw):
            d = b[0]
            if d < BAR_FIRST:
                continue
            ret, dd = window(c, d, MAIN_EXIT)
            if ret is None:
                continue
            n_win += 1
            to = vol = None
            if i + 1 >= LOOKBACK:
                win_bars = raw[i + 1 - LOOKBACK:i + 1]
                tot = sum(x[4] * x[5] for x in win_bars) / LOOKBACK
                rets = []
                for j in range(1, len(win_bars)):
                    p0 = win_bars[j - 1][4]
                    if p0:
                        rets.append(win_bars[j][4] / p0 - 1)
                if len(rets) >= 2 and tot > 0:
                    to, vol = tot, statistics.pstdev(rets)
            if to is None:
                n_nostat += 1
            # 층을 못 만드는 창도 **버리지 않고 담는다** — 자기검사가
            # R149 와 같은 표본으로 견주려면 필요하다(아래 §5 설명).
            per_day[dd].append((c, ret, to, vol, mk))
    print(f'■ 창 {n_win:,}개 · 층 계산 가능 '
          f'{n_win - n_nostat:,} ({(n_win - n_nostat) / n_win * 100:.1f}%)'
          f' · 20거래일 부족 {n_nostat:,}')

    # ── Δ 계산 — 세 모드 ───────────────────────────────────────────────
    #   'all'        : 층 하나 · 모든 창          → R149 재현용(자기검사)
    #   'restricted' : 층 하나 · 층 계산 가능한 창 → 표본 축소 효과만 본다
    #   'matched'    : 층화 · 층 계산 가능한 창    → 주 시험
    #
    #   처음에는 'all' 모드 없이 'restricted' 로 R149 를 재현하려 했고,
    #   자기검사가 6유형에서 걸렸다. 원인은 데이터가 아니라 **사전등록의
    #   모순**이었다 — §2 는 20거래일 미만 창을 제외한다고 했고 §5 는
    #   층을 합치면 R149 를 그대로 재현한다고 했는데, 제외가 있는 한
    #   둘은 동시에 성립할 수 없다(27,538창 · 1.0% 차이).
    #   판정 기준은 그대로 두고 **검사가 같은 표본끼리 견주도록** 고쳤다.
    def deltas(t, mode, lo=None, hi=None):
        vals, days, n_ev = [], 0, 0
        for d in sorted(per_day):
            if (lo is not None and d < lo) or (hi is not None and d > hi):
                continue
            obs = per_day[d]
            if not obs:
                continue
            if mode == 'matched':
                strata = {}
                for mk in ('KOSPI', 'KOSDAQ'):
                    sub = [k for k, o in enumerate(obs)
                           if o[4] == mk and o[2] is not None]
                    if not sub:
                        continue
                    n = len(sub)
                    tq = quintile(sorted(sub, key=lambda k: obs[k][2]), n)
                    vq = quintile(sorted(sub, key=lambda k: obs[k][3]), n)
                    for k in sub:
                        strata[k] = (mk, tq[k], vq[k])
            elif mode == 'restricted':
                strata = {k: 0 for k, o in enumerate(obs) if o[2] is not None}
            else:                                  # 'all'
                strata = {k: 0 for k in range(len(obs))}
            acc = collections.defaultdict(
                lambda: [0.0, 0, 0.0, 0])   # 이벤트합·수·대조합·수
            for k, (c, ret, _to, _vol, _mk) in enumerate(obs):
                s = strata.get(k)
                if s is None:
                    continue
                a = acc[s]
                mult = ev_map[t][(c, d)]
                if mult:
                    a[0] += ret * mult
                    a[1] += mult
                elif not any_ev.get((c, d)):
                    a[2] += ret
                    a[3] += 1
            num = den = 0.0
            ev_here = 0
            for a in acc.values():
                if a[1] > 0 and a[3] > 0:
                    num += (a[0] / a[1] - a[2] / a[3]) * a[1]
                    den += a[1]
                    ev_here += a[1]
            if den > 0:
                vals.append(num / den)
                days += 1
                n_ev += ev_here
        z, win, n = sign_test(vals)
        sv = sorted(vals)
        return dict(events=n_ev, days=days,
                    delta_mean_pp=round(sum(vals) / len(vals), 3) if vals else None,
                    delta_median_pp=round(sv[len(sv) // 2], 3) if sv else None,
                    win_pct=round(win / n * 100, 1) if n else None,
                    need_pct=need_p(n), sign_z=z, sign_win=win, sign_n=n)

    # ── 재구현 자기검사 (사전등록 §5) ───────────────────────────────────
    with open(R149, encoding='utf-8') as f:
        prev = json.load(f)
    print()
    print('■ 재구현 자기검사 — 층 하나 · 모든 창이면 R149 를 재현하는가 (§5)')
    checks, bad = [], []
    unmatched, restricted = {}, {}
    for t in TYPES:
        mine = deltas(t, 'all', hi=DEV_END)
        unmatched[t] = mine
        restricted[t] = deltas(t, 'restricted', hi=DEV_END)
        theirs = ((prev['types'].get(t) or {}).get('dev') or {}).get(
            'delta_mean_pp')
        ok = (mine['delta_mean_pp'] is not None and theirs is not None
              and abs(mine['delta_mean_pp'] - theirs) <= REPRO_TOL + 1e-9)
        checks.append(dict(name=t, mine=mine['delta_mean_pp'], r149=theirs))
        print(f'   {"OK " if ok else "!! "}{t:<12} 재구현 '
              f'{mine["delta_mean_pp"]} · R149 {theirs}')
        if not ok:
            bad.append(t)
    if bad:
        print()
        print(f'■ 재현 실패 {len(bad)}건 — 측정을 중단한다 (사전등록 §5). '
              f'허용 오차를 늘리지 않는다.')
        return 2

    # ── 주 시험 — 매칭 ─────────────────────────────────────────────────
    results = {}
    print()
    print(f'{"유형":<10}{"이벤트":>8}{"날짜":>7}{"Δ평균%p":>9}{"Δ중앙%p":>9}'
          f'{"승률":>7}{"z":>7}{"R149 z":>9}  판정')
    for t in TYPES:
        dev = deltas(t, 'matched', hi=DEV_END)
        prev_z = ((prev['types'].get(t) or {}).get('dev') or {}).get('sign_z')
        sample_ok = dev['events'] >= MIN_EVENTS and dev['days'] >= MIN_DAYS
        z_ok = dev['sign_z'] is not None and abs(dev['sign_z']) >= Z_CRIT
        if not sample_ok:
            verdict = '표본 미달'
        elif z_ok:
            verdict = ('통과(+)' if dev['sign_z'] > 0
                       else '통과(−) — 매칭 뒤에도 남는다')
        else:
            verdict = '미달 — 매칭하니 사라진다'
        blind = deltas(t, 'matched', lo=BLIND[0], hi=BLIND[1]) \
            if (sample_ok and z_ok) else None
        results[t] = dict(dev=dev, unmatched_r149_z=prev_z,
                          unmatched_all=unmatched[t],
                          unmatched_restricted=restricted[t],
                          sample_ok=sample_ok,
                          z_ok=z_ok, verdict=verdict, blind=blind)
        print(f'{t:<10}{dev["events"]:>8,}{dev["days"]:>7,}'
              f'{(dev["delta_mean_pp"] or 0):>9.3f}'
              f'{(dev["delta_median_pp"] or 0):>9.3f}'
              f'{(dev["win_pct"] or 0):>6.1f}%'
              f'{(dev["sign_z"] if dev["sign_z"] is not None else 0):>7.2f}'
              f'{(prev_z if prev_z is not None else 0):>9.2f}  {verdict}')

    passed = [t for t in TYPES if results[t]['sample_ok'] and results[t]['z_ok']]
    print()
    if passed:
        print('■ blind 확인 (문턱을 넘은 유형만 — 사전등록 §4)')
        for t in passed:
            b = results[t]['blind']
            print(f"   {t}: 이벤트 {b['events']:,} · 날짜 {b['days']} · "
                  f"Δ {b['delta_mean_pp']}%p · z {b['sign_z']}")
    else:
        print('■ 문턱을 넘은 유형이 없다 — blind 를 열지 않는다')

    doc = {
        'made': date.today().isoformat(),
        'made_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'prereg': 'docs/PREREG_R150_MATCHED_CONTROL.md',
        'criteria': dict(z_crit=Z_CRIT, min_events=MIN_EVENTS,
                         min_days=MIN_DAYS, main_exit=MAIN_EXIT,
                         lookback=LOOKBACK, nq=NQ, dev_end=DEV_END,
                         blind=list(BLIND), n_tests=len(TYPES),
                         repro_tol=REPRO_TOL),
        'windows': n_win, 'no_stat': n_nostat,
        'repro_check': checks, 'types': results, 'passed': passed,
        'note': ('측정 전용 — 점수·게이트·문턱을 바꾸지 않는다. 현재 시총 '
                 '미사용(누출). 매칭 변수는 D0 까지의 일봉만 쓴다. '
                 '최근접 이웃 매칭 없음 — 층화만.'),
    }
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print()
    print(f'저장: {OUT}')
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
