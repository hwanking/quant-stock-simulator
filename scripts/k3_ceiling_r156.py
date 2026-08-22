# -*- coding: utf-8 -*-
"""R156 — k≥3 겹침은 언젠가 판정할 수 있나 (표본 상한).

사전등록: docs/PREREG_R156_K3_CEILING.md (측정 전 커밋).
가설 검정이 아니라 **실현 가능성 계산**이다 — 효과를 주장하지 않는다.

  C1 지금 k>=3 표본 (R153 재현)
  C2 z 2.25 에 닿는 날짜   n >= (2.25 / (2(p-0.5)))^2
  C3 이벤트 1,000 에 닿는 날짜  (관측 적립률로)
  C4 필요 날짜 = max(C2, C3, 300)
  C5 물리 상한 3,665일 = 246 x 14.9 (R129 유도값)
  C6 종목 축 여력 = 상장 종목수 / 유니버스 종목수

  S1 재현 자기검사 — 못 하면 중단
  S2 닫힌 식 vs 부트스트랩 (씨앗 20260822 · 2,000회) — 괴리 20% 넘으면
     둘을 나란히 적고 부트스트랩 채택 (R129 의 판단)
  E1 종목 축 실측 — 하루당 이벤트 수별 승률 (판정 아님)

측정 전용 — 점수·게이트·문턱을 바꾸지 않는다.

    C:/Python314/python.exe scripts/k3_ceiling_r156.py
"""
import bisect
import collections
import io
import json
import math
import os
import random
import re
import statistics
import sys
from datetime import date, datetime, timezone

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
OUT = os.path.join(PROJ, 'data', 'k3_ceiling_r156.json')
R153 = os.path.join(PROJ, 'data', 'event_confluence_r153.json')
DISC = os.path.join(PROJ, '.portfolio', 'disclosures_daily.jsonl')
BARS = os.path.join(PROJ, '.portfolio', 'daily_bars.jsonl')
MASTER = os.path.join(PROJ, '.portfolio', 'name_master.json')

import disclosure_types as dt                                  # noqa: E402

TYPES = ('자사주·배당', '수주·공급계약', '증자·CB·BW', '투자·설비',
         'M&A·분할', 'IR·안내', '인허가·임상')
MAIN_EXIT = 5
LOOKBACK = 20
NQ = 5
Z_CRIT = 2.25                  # 채택값 재사용 (R153~R155)
MIN_EVENTS = 1000              # 채택값
MIN_DAYS = 300                 # 채택값
DEV_END = '2026-01-30'
BAR_FIRST = '2014-05-30'
CEILING_DAYS = int(246 * 14.9)  # §3 C5 — R129 유도값 (3,665)
SEED = 20260822                # §5 S2 — 고정
BOOT = 2000                    # §5 S2
BOOT_POWER = 0.80              # §5 S2 — 80% 기준
DIVERGE_TOL = 0.20             # §5 S2 — 상대 괴리 허용
#: §5 S1 — R153 이 발표한 k>=3 값
R153_EV, R153_DAYS, R153_MEAN, R153_Z = 219, 190, -0.979, -2.47
TOL_V, TOL_Z = 0.001, 0.01

_STRIP = re.compile(r'\s+|㈜|\(주\)|주식회사')


def norm(name):
    return _STRIP.sub('', str(name)).upper()


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def sign_z(cnt, n):
    return round((cnt - n / 2) / math.sqrt(n / 4), 2) if n else None


def sign_test(vals):
    nz = [v for v in vals if v != 0]
    n = len(nz)
    if n == 0:
        return None, 0, 0
    win = sum(1 for v in nz if v > 0)
    return sign_z(win, n), win, n


def quintile(sorted_idx, n):
    out = {}
    for rank, i in enumerate(sorted_idx):
        out[i] = min(NQ - 1, rank * NQ // n)
    return out


def main():
    print('R156 — k≥3 겹침은 언젠가 판정할 수 있나 (표본 상한)')
    print('사전등록: docs/PREREG_R156_K3_CEILING.md')
    print('가설 검정이 아니다 — 효과를 주장하지 않는다')
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
    live = 0
    for r in m['rows']:
        n2c[norm(r['name'])].add(r['code'])
        if r.get('live'):
            live += 1
    name2code = {k: next(iter(v)) for k, v in n2c.items() if len(v) == 1}
    # 종목 축 여력(C6)은 **주식만** 센다 — ETF 는 DART 공시 주체가
    # 아니므로(R146) 확장 여력에 넣으면 부풀려진다.
    etf = set(m.get('etf_codes') or [])
    live = sum(1 for r in m['rows']
               if r.get('live') and r['code'] not in etf)

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
    cal_days = sorted(d for d in per_day if d <= DEV_END)
    print(f'■ 개발 구간 거래일 {len(cal_days):,}일 · 종목 {len(stocks):,}')

    def matched_delta(pick, hi=DEV_END):
        out = {}
        for d, obs in per_day.items():
            if hi is not None and d > hi:
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

    # ── C1 + S1 자기검사 ───────────────────────────────────────────────
    g3 = matched_delta(lambda s: len(s) >= 3)
    v3 = [v for v, _ in g3.values()]
    n3 = sum(n for _, n in g3.values())
    z3, win3, nn3 = sign_test(v3)
    mean3 = round(sum(v3) / len(v3), 3) if v3 else None
    print()
    print('■ S1 자기검사 — k≥3 이 R153 발표값과 일치하는가')
    s1 = all([n3 == R153_EV, len(v3) == R153_DAYS,
              mean3 is not None and abs(mean3 - R153_MEAN) <= TOL_V + 1e-9,
              z3 is not None and abs(z3 - R153_Z) <= TOL_Z + 1e-9])
    print(f'   {"OK " if s1 else "!! "}이벤트 {n3} (R153 {R153_EV}) · '
          f'날짜 {len(v3)} ({R153_DAYS}) · 평균 {mean3} ({R153_MEAN}) · '
          f'z {z3} ({R153_Z})')
    if not s1:
        print()
        print('■ 재현 실패 — 측정을 중단한다 (사전등록 §5 S1). '
              '허용 오차를 늘리지 않는다.')
        return 2

    p_hat = win3 / nn3
    print()
    print(f'■ C1 — 지금 k≥3: 이벤트 {n3:,} · 날짜 {len(v3):,} · '
          f'승률 {p_hat * 100:.1f}% · z {z3}')

    # ── C2 닫힌 식 ─────────────────────────────────────────────────────
    if p_hat <= 0.5:
        c2 = None
        print('■ C2 — 승률이 0.5 이하 방향 — 날짜를 늘려도 z 2.25 에 '
              '안 닿는다')
    else:
        c2 = int(math.ceil((Z_CRIT / (2 * (p_hat - 0.5))) ** 2))
        print(f'■ C2 — z {Z_CRIT} 에 닿는 날짜(닫힌 식): {c2:,}일')

    # ── S2 부트스트랩 대조 ─────────────────────────────────────────────
    rnd = random.Random(SEED)
    signs = [1 if v > 0 else (0 if v == 0 else -1) for v in v3]
    nz = [s for s in signs if s != 0]

    def power_at(n):
        hit = 0
        for _ in range(BOOT):
            w = sum(1 for _ in range(n) if rnd.choice(nz) > 0)
            if abs(sign_z(w, n) or 0) >= Z_CRIT:
                hit += 1
        return hit / BOOT

    boot_n = None
    lo, hi_ = 100, 60000
    while lo < hi_:                       # 이분 탐색 — 80% 되는 N
        mid = (lo + hi_) // 2
        if power_at(mid) >= BOOT_POWER:
            hi_ = mid
        else:
            lo = mid + 1
        if hi_ - lo < max(50, lo // 20):
            break
    boot_n = hi_
    diverge = (abs(boot_n - c2) / c2) if (c2 and boot_n) else None
    print(f'■ S2 — 부트스트랩(씨앗 {SEED} · {BOOT:,}회): '
          f'검정력 {BOOT_POWER:.0%} 되는 날짜 {boot_n:,}일')
    if diverge is not None:
        print(f'   닫힌 식 대비 상대 괴리 {diverge * 100:.1f}% '
              f'(허용 {DIVERGE_TOL:.0%}) — '
              f'{"일치" if diverge <= DIVERGE_TOL else "괴리 — 부트스트랩 채택"}')
    c2_use = c2 if (diverge is not None and diverge <= DIVERGE_TOL) else boot_n

    # ── C3 이벤트 적립 ─────────────────────────────────────────────────
    rate = n3 / len(cal_days)
    c3 = int(math.ceil(MIN_EVENTS / rate)) if rate > 0 else None
    print(f'■ C3 — 이벤트 적립률 {rate:.4f}건/거래일 → '
          f'{MIN_EVENTS:,}건에 닿는 날짜 {c3:,}일')

    # ── C4 · C5 · C6 ───────────────────────────────────────────────────
    c4 = max(x for x in (c2_use, c3, MIN_DAYS) if x)
    c6 = round(live / len(stocks), 2)
    print(f'■ C4 — 필요 날짜 = max(C2 {c2_use:,}, C3 {c3:,}, 300) '
          f'= {c4:,}일')
    print(f'■ C5 — 물리 상한 {CEILING_DAYS:,}일 (246×14.9, R129)')
    print(f'■ C6 — 종목 축 여력: 상장 {live:,} ÷ 유니버스 {len(stocks):,} '
          f'= {c6}배')

    if c4 <= CEILING_DAYS:
        verdict = '언젠가 가능하다 — 필요 날짜가 물리 상한 안'
    elif c3 and c3 > CEILING_DAYS and c2_use <= CEILING_DAYS:
        verdict = ('부분적으로 가능 — 이벤트는 종목 확장으로 채울 수 '
                   '있으나 날짜가 관건')
    else:
        verdict = '불가능하다 — 모든 거래일을 다 모아도 판정 못 한다'
    print()
    print(f'■ 판정(실현 가능성): {verdict}')

    # ── E1 종목 축 실측 (판정 아님) ────────────────────────────────────
    g2 = matched_delta(lambda s: len(s) >= 2)
    bins = collections.defaultdict(list)
    for d, (v, n) in g2.items():
        b = '1건' if n == 1 else ('2건' if n == 2 else '3건+')
        bins[b].append(v)
    print()
    print('■ E1 — 하루당 이벤트 수별 승률 (k≥2 · 판정에 쓰지 않는다)')
    e1 = {}
    for b in ('1건', '2건', '3건+'):
        vals = bins.get(b) or []
        z, w, n = sign_test(vals)
        e1[b] = dict(days=len(vals), win_pct=round(w / n * 100, 1) if n else None,
                     sign_z=z)
        print(f'   하루 {b:<4} 날짜 {len(vals):>5,} · 승률 '
              f'{(w / n * 100 if n else 0):>5.1f}% · z {z}')
    print('   → 하루당 이벤트가 늘 때 승률이 0.5 에서 멀어지는지 본다 '
          '(가정 없이 실측)')

    doc = {
        'made': date.today().isoformat(),
        'made_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'prereg': 'docs/PREREG_R156_K3_CEILING.md',
        'constants': dict(z_crit=Z_CRIT, min_events=MIN_EVENTS,
                          min_days=MIN_DAYS, ceiling_days=CEILING_DAYS,
                          seed=SEED, boot=BOOT, boot_power=BOOT_POWER,
                          diverge_tol=DIVERGE_TOL, main_exit=MAIN_EXIT),
        'self_check': dict(events=n3, days=len(v3), mean_pp=mean3, z=z3,
                           r153_events=R153_EV, r153_days=R153_DAYS,
                           r153_mean=R153_MEAN, r153_z=R153_Z, passed=True),
        'C1': dict(events=n3, days=len(v3), win_pct=round(p_hat * 100, 1),
                   sign_z=z3),
        'C2_closed_form_days': c2, 'S2_bootstrap_days': boot_n,
        'S2_divergence': (round(diverge, 4) if diverge is not None else None),
        'C2_used_days': c2_use,
        'C3_days_for_events': c3, 'accrual_per_day': round(rate, 4),
        'C4_required_days': c4, 'C5_ceiling_days': CEILING_DAYS,
        'C6_stock_headroom': c6, 'listed': live, 'universe': len(stocks),
        'dev_trading_days': len(cal_days),
        'verdict': verdict, 'E1_by_events_per_day': e1,
        'note': ('측정 전용 — 점수·게이트·문턱을 바꾸지 않는다. '
                 '실현 가능성 계산이지 가설 검정이 아니다 — k≥3 의 효과를 '
                 '주장하지 않는다. 상수는 전부 채택값 재사용(문턱 2.25 · '
                 '표본 1,000/300 · 상한 3,665일).'),
    }
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print()
    print(f'저장: {OUT}')
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
