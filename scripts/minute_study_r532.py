# -*- coding: utf-8 -*-
"""라운드 532 — 분봉 첫 스터디 (사전등록 `docs/PREREG_R532_MINUTE_FIRST.md` · 이 스크립트와 그 문서는 결과 전에 커밋한다).

Q1 장중 방향(첫 봉 시가 → 15:30 종가) · Q2 같은 시간대 지속(Heston·Korajczyk·Sadka 2010 · 어제 같은 30분 구간 위 10%) ·
Q3 장중 모멘텀(Gao·Han·Li·Zhou 2018 · 첫 30분이 양수면 15:00 → 15:30) · Q4 일봉 채점의 '같은 봉 동점'(손절 먼저 가정)을 분 단위로.

읽기만 한다(분봉 원장 · 연구 원장 · ETF 색인). 쓰는 것은 결과 파일 하나(`--out` · 기본 data/minute_study_r532.json).
블라인드(2026-05-01 부터)는 `--blind` 없이는 **읽지 않는다**(그 날짜의 봉을 버린다 · 사전등록 §2).

    python scripts/minute_study_r532.py            # 학습·검증만
    python scripts/minute_study_r532.py --blind    # 백필이 끝난 뒤에만
"""
from __future__ import annotations

import argparse
import bisect
import collections
import datetime as _dt
import io
import json
import math
import os
import random
import statistics
import sys
import time

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
sys.path.insert(0, os.path.join(PROJ, 'scripts'))

# ── 사전등록에 적은 값 (결과 전에 고정 · 바꾸지 않는다) ─────────────────────────────────────────────────────────
COST_WALL = 0.23            # 수수료 0.03 + 증권거래세 0.20 · 체결 손해 0(전략에 유리한 쪽)
COST_OPS = 0.41             # 운영 비용 — 민감도만
SPLITS = (('train', '2025-01-01', '2026-01-31'), ('valid', '2026-02-01', '2026-04-30'), ('blind', '2026-05-01', '2099-12-31'))
BLIND_FROM = '2026-05-01'
LIQ_FLOOR = 2e9             # 직전 20거래일 평균 거래대금 20억원 — 이미 채택된 스캐너 하한(재사용)
LIQ_DAYS = 20
BOUNDS = ['09:30', '10:00', '10:30', '11:00', '11:30', '12:00', '12:30', '13:00', '13:30', '14:00', '14:30', '15:00', '15:30']
TOP_SHARE = 0.10            # Q2 — 위 10%(발표된 규칙의 십분위) · 민감도 0.20
MIN_XS = 10                 # Q2 — 그 (날, 구간)에 순위를 매길 종목이 이 수 미만이면 십분위를 못 만든다(10% 가 1종목이 되는 최소)
BLOCK = 20                  # 날짜 덩어리(거래일) 부트스트랩
BOOT = 2000
SEED = 532
DATE_FLOOR = 30             # 구간 날짜 하한(R84)
Z_BONF = 2.40               # Bonferroni(3) 양측 · 올림

ROOT = os.path.join(PROJ, '.portfolio', 'day_bars')


def split_of(day):
    for name, a, b in SPLITS:
        if a <= day <= b:
            return name
    return None


def etf_codes():
    try:
        d = json.load(io.open(os.path.join(PROJ, 'data', 'etf_index.json'), encoding='utf-8'))
        return set((d.get('map') or {}).keys())
    except (OSError, ValueError):
        return None


def read_code(path, keep_blind, want_days=None):
    """한 종목 분봉 → ({날: [봉 …](시각 순 · 같은 시각은 마지막 것)}, 못 읽은 줄 수, 버린 블라인드 줄 수, {날: 봉}(want_days 만))."""
    days = collections.defaultdict(dict)
    bad = blind_dropped = 0
    with io.open(path, encoding='utf-8') as f:
        for ln in f:
            try:
                r = json.loads(ln)
            except ValueError:
                bad += 1          # 백필이 덧붙이는 중의 마지막 반쪽 줄 등
                continue
            d = r.get('day')
            if not d:
                bad += 1
                continue
            if not keep_blind and d >= BLIND_FROM:
                blind_dropped += 1
                continue
            days[d][r.get('t')] = r
    out = {d: [v[t] for t in sorted(v)] for d, v in days.items()}
    return out, bad, blind_dropped


def price_before(bars_t, bars, hhmm, inclusive=False):
    """그 시각 **전**(inclusive 면 그 시각 포함)의 마지막 봉 종가 · 없으면 None."""
    i = bisect.bisect_right(bars_t, hhmm) if inclusive else bisect.bisect_left(bars_t, hhmm)
    return bars[i - 1]['c'] if i > 0 else None


def day_features(bars):
    """하루 분봉 → 시가 · 종가(15:30 포함 마지막) · 30분 구간 13개의 (시작가, 끝가, 그 구간에 봉이 있었나) · 거래대금 · 첫·끝 시각."""
    ts = [b['t'] for b in bars]
    op = bars[0]['o']
    close = price_before(ts, bars, '15:30', inclusive=True)
    seg = []
    start = op
    prev_b = '09:00'
    for b in BOUNDS:
        end = price_before(ts, bars, b, inclusive=(b == '15:30'))
        lo = bisect.bisect_left(ts, prev_b)
        hi = bisect.bisect_right(ts, b) if b == '15:30' else bisect.bisect_left(ts, b)
        traded = hi > lo
        seg.append((start, end, traded))
        start = end
        prev_b = b
    amt = bars[-1].get('cum_amt')
    return dict(open=op, close=close, seg=seg, amt=(float(amt) if isinstance(amt, (int, float)) else None),
                first_t=ts[0], last_t=ts[-1], p0930=price_before(ts, bars, '09:30'), p1500=price_before(ts, bars, '15:00'))


def ret(a, b):
    if a is None or b is None or a <= 0:
        return None
    return (b / a - 1.0) * 100.0


def boot_ci(day_vals, days_sorted, seed=SEED, boot=BOOT, block=BLOCK):
    """날짜 평균의 평균 · 20거래일 덩어리 부트스트랩 95% 구간 · z(평균 ÷ 부트스트랩 표준편차)."""
    xs = [day_vals[d] for d in days_sorted if d in day_vals]
    n = len(xs)
    if n == 0:
        return dict(n_dates=0, mean=None, ci95=None, z=None)
    m = statistics.mean(xs)
    if n < 2:
        return dict(n_dates=n, mean=m, ci95=None, z=None)
    rng = random.Random(seed)
    nb = max(1, math.ceil(n / block))
    starts = list(range(0, n))
    means = []
    for _ in range(boot):
        smp = []
        for _b in range(nb):
            s = rng.choice(starts)
            smp.extend(xs[s:s + block] if s + block <= n else xs[s:] + xs[:s + block - n])
        smp = smp[:n]
        means.append(statistics.mean(smp))
    means.sort()
    lo, hi = means[int(0.025 * boot)], means[int(0.975 * boot) - 1]
    sd = statistics.pstdev(means)
    return dict(n_dates=n, mean=m, ci95=[lo, hi], z=(m / sd if sd > 0 else None))


def summarize(trades_by_day, cost, all_days):
    """{날: [수익(비용 전) …]} → 구간별 날짜 평균(비용 뺀)의 평균·구간·z · 거래 수 · 중앙 · 0 넘은 비율."""
    out = {}
    for name, a, b in SPLITS:
        ds = [d for d in all_days if a <= d <= b and trades_by_day.get(d)]
        dv = {d: statistics.mean([x - cost for x in trades_by_day[d]]) for d in ds}
        flat = [x - cost for d in ds for x in trades_by_day[d]]
        r = boot_ci(dv, ds)
        r.update(trades=len(flat), median_trade=(statistics.median(flat) if flat else None),
                 share_pos=(sum(1 for x in flat if x > 0) / len(flat) if flat else None))
        out[name] = r
    return out


def verdict(s):
    """사전등록 §4 — R0(학습 위끝 < 0 → 접음) · (가) 세 구간 · (나) 학습·검증 · (다) 그 밖."""
    tr = s.get('train') or {}
    if tr.get('ci95') and tr['ci95'][1] < 0:
        return 'R0 접음 — 학습 구간 95% 구간 위끝이 0 아래'

    def ok(x):
        return (x.get('n_dates') or 0) >= DATE_FLOOR and x.get('mean') is not None and x['mean'] > 0 and x.get('ci95') \
            and x['ci95'][0] > 0 and (x.get('z') or 0) >= Z_BONF
    if all(ok(s.get(k) or {}) for k in ('train', 'valid', 'blind')):
        return '(가) 후보 — 전방 모의 30거래일을 새 사전등록으로'
    if ok(tr) and ok(s.get('valid') or {}):
        return '(나) 보류 — 블라인드를 기다린다'
    return '(다) 접음'


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--blind', action='store_true', help='블라인드(2026-05-01 부터)도 읽는다 — 백필이 끝난 뒤에만')
    ap.add_argument('--out', default=os.path.join(PROJ, 'data', 'minute_study_r532.json'))
    ap.add_argument('--limit', type=int, default=0, help='시험용 — 종목 수 상한')
    ap.add_argument('--root', default=None, help='시험용 — 분봉 폴더(심은 자료로 스크립트만 돌려 볼 때)')
    ap.add_argument('--codes', default=None, help='시험용 — 고정 목록 대신 쓸 코드(쉼표)')
    ap.add_argument('--ledger', default=None, help='시험용 — 원장 대신 읽을 파일(심은 행으로 Q4 를 재 볼 때)')
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError):
        pass
    t0 = time.time()
    global ROOT
    if a.root:
        ROOT = a.root
    from collect_minute_bars import pool_codes
    import ledger_view as LV
    pool = [c.strip() for c in a.codes.split(',') if c.strip()] if a.codes else pool_codes()
    etf = etf_codes()
    if not pool or etf is None:
        print('고정 목록 또는 ETF 색인을 못 읽었다 — 멈춘다')
        return 2
    codes = [c for c in pool if c not in etf]
    if a.limit:
        codes = codes[:a.limit]

    # ── Q4 준비: 원장 통계 행 중 결과 STOP 인 고정 목록 종목 행 · 결정 봉 날짜 = 기준일 뒤 touched_bar 번째 거래일(거래소 달력 한 곳)
    from improvement import case_tracker as _ct
    codes_set = set(codes)
    keys = LV.scale_mismatch_keys()
    q4_rows = []
    with io.open(a.ledger or os.path.join(PROJ, '.portfolio', 'virtual_graded.jsonl'), encoding='utf-8') as f:
        def _rows():
            for ln in f:
                try:
                    yield json.loads(ln)
                except ValueError:
                    continue
        for r in LV.stat_rows(_rows(), keys=keys):
            if r.get('outcome') == 'STOP' and LV.code6(r.get('ticker')) in codes_set and r.get('touched_bar') \
                    and r.get('target') and r.get('stop') and r.get('price') and str(r.get('date'))[:10] >= '2025-09-01':
                q4_rows.append(r)

    def nth_trading_day_after(d0, n):
        d = _dt.date.fromisoformat(d0)
        k = 0
        for _ in range(400):
            d += _dt.timedelta(days=1)
            if not _ct.is_non_trading_date(d.isoformat()):
                k += 1
                if k == n:
                    return d.isoformat()
        return None

    q4_need = collections.defaultdict(dict)        # code → {결정 봉 날짜: [행 …]}
    for r in q4_rows:
        dd = nth_trading_day_after(str(r['date'])[:10], int(r['touched_bar']))
        r['_dd'] = dd
        if dd:
            q4_need[LV.code6(r['ticker'])].setdefault(dd, []).append(r)

    feats = {}            # code → {day: features}
    bad = blind_dropped = 0
    q4_bars = {}          # (code, 결정 봉 날짜) → 그날 분봉(필요한 날만 들고 있는다 — 전부 들면 메모리를 넘는다)
    day_union = set()
    for i, code in enumerate(codes, 1):
        p = os.path.join(ROOT, f'{code}.jsonl')
        if not os.path.exists(p):
            continue
        days, b1, b2 = read_code(p, a.blind)
        bad += b1
        blind_dropped += b2
        for dd in q4_need.get(code, {}):
            if days.get(dd):
                q4_bars[(code, dd)] = days[dd]
        feats[code] = {d: day_features(bs) for d, bs in days.items() if bs}
        day_union.update(feats[code])
        del days
        if i % 100 == 0:
            print(f'  읽음 {i}/{len(codes)} · {time.time() - t0:.0f}초', flush=True)
    cal = sorted(day_union)
    # 장 시각이 09:00~15:30 인 날만 — 그날 어느 종목에든 09:00 봉이 있고 마지막 봉이 15:30 인 날(수능일·새해 첫날은 빠진다)
    first_any = collections.defaultdict(lambda: '99:99')
    last_any = collections.defaultdict(str)
    for code, fd in feats.items():
        for d, f in fd.items():
            first_any[d] = min(first_any[d], f['first_t'])
            last_any[d] = max(last_any[d], f['last_t'])
    normal = [d for d in cal if first_any[d] == '09:00' and last_any[d] == '15:30']
    abnormal = [d for d in cal if d not in set(normal)]
    normal_set = set(normal)
    prev_of = {cal[i]: cal[i - 1] for i in range(1, len(cal))}

    # 유동성 — 그 종목의 직전 20거래일(달력) 평균 거래대금 ≥ 20억
    def liquid(code, d):
        fd = feats[code]
        i = bisect.bisect_left(cal, d)
        prior = cal[max(0, i - LIQ_DAYS):i]
        if len(prior) < LIQ_DAYS:
            return False
        amts = [fd[x]['amt'] for x in prior if x in fd and fd[x].get('amt') is not None]
        if len(amts) < LIQ_DAYS:
            return False
        return statistics.mean(amts) >= LIQ_FLOOR

    q1 = collections.defaultdict(list)
    q2 = collections.defaultdict(list)
    q2_all = collections.defaultdict(list)
    q2_20 = collections.defaultdict(list)
    q3 = collections.defaultdict(list)
    q3_neg = collections.defaultdict(list)
    n_liq = 0
    elig_by_day = collections.defaultdict(list)
    for code, fd in feats.items():
        for d, f in fd.items():
            if d not in normal_set or not liquid(code, d):
                continue
            n_liq += 1
            elig_by_day[d].append(code)
            r1 = ret(f['open'], f['close'])
            if r1 is not None:
                q1[d].append(r1)
            pd_ = prev_of.get(d)
            pf = fd.get(pd_) if pd_ else None
            if pf and pd_ in normal_set:
                r30 = ret(pf['close'], f['p0930'])
                r3 = ret(f['p1500'], f['close'])
                if r30 is not None and r3 is not None and f['seg'][12][2]:
                    if r30 > 0:
                        q3[d].append(r3)
                    elif r30 < 0:
                        q3_neg[d].append(r3)          # 0 이면 어느 쪽에도 안 넣는다
    # Q2 — (날, 구간)마다 어제 같은 구간 수익으로 순위
    for d in normal:
        pd_ = prev_of.get(d)
        if not pd_ or pd_ not in normal_set:
            continue
        for k in range(len(BOUNDS)):
            xs = []
            for code in elig_by_day.get(d, ()):
                fd = feats[code]
                f, pf = fd.get(d), fd.get(pd_)
                if not pf:
                    continue
                s0, e0, tr0 = pf['seg'][k]
                s1, e1, tr1 = f['seg'][k]
                ry, rt = ret(s0, e0), ret(s1, e1)
                if ry is None or rt is None or not tr0 or not tr1:
                    continue
                xs.append((ry, rt, code))
            if len(xs) < MIN_XS:
                continue
            xs.sort(key=lambda x: (-x[0], x[2]))
            n10 = max(1, math.floor(len(xs) * TOP_SHARE))
            n20 = max(1, math.floor(len(xs) * 0.20))
            q2[d].extend(x[1] for x in xs[:n10])
            q2_20[d].extend(x[1] for x in xs[:n20])
            q2_all[d].extend(x[1] for x in xs)
    res = {}
    for name, tb, extra in (('Q1', q1, None), ('Q2', q2, q2_all), ('Q3', q3, q3_neg)):
        s = summarize(tb, COST_WALL, normal)
        s_ops = summarize(tb, COST_OPS, normal)
        res[name] = dict(wall=s, ops=s_ops, verdict=verdict(s))
        if extra is not None:
            res[name]['compare_gross'] = summarize(extra, 0.0, normal)      # 비교 무리(비용 전) — 효과 크기를 보려고
            res[name]['self_gross'] = summarize(tb, 0.0, normal)
    res['Q2']['top20_wall'] = summarize(q2_20, COST_WALL, normal)

    # ── Q4 — 결정 봉 날짜(거래소 달력)의 분봉으로 무엇이 먼저였나 · 분봉 범위 밖이면 그렇게 센다
    q4 = collections.Counter()
    delta = []
    lo_day, hi_day = (cal[0], cal[-1]) if cal else ('9999', '0000')
    for r in q4_rows:
        code = LV.code6(r['ticker'])
        dd = r.get('_dd')
        if not dd or dd < lo_day or dd > hi_day or (not a.blind and dd >= BLIND_FROM):
            q4['분봉 범위 밖(결정 봉 날짜가 분봉 기간 밖 · 블라인드 포함)'] += 1
            continue
        bars = q4_bars.get((code, dd))
        if not bars:
            q4['그날 분봉 없음'] += 1
            continue
        tp, sl, entry = float(r['target']), float(r['stop']), float(r['price'])
        hi, lo = max(b['h'] for b in bars), min(b['l'] for b in bars)
        if lo > sl:
            q4['분봉으로는 손절에 안 닿음(일봉과 어긋남)'] += 1
            continue
        if hi < tp:
            q4['동점 아님(손절만)'] += 1
            continue
        ft = next((b['t'] for b in bars if b['h'] >= tp), None)
        fs = next((b['t'] for b in bars if b['l'] <= sl), None)
        if ft == fs:
            q4['동점 · 같은 분(못 가림)'] += 1
        elif ft < fs:
            q4['동점 · 목표가 먼저'] += 1
            delta.append((tp / entry - 1.0) * 100.0 - float(r['return_pct']))
        else:
            q4['동점 · 손절이 먼저'] += 1
    checked = sum(v for k, v in q4.items() if not k.startswith('분봉 범위 밖') and k != '그날 분봉 없음')
    res['Q4'] = dict(stop_rows=len(q4_rows), counts=dict(q4), checked_in_range=checked,
                     mean_delta_if_target_first=(statistics.mean(delta) if delta else None),
                     shift_on_checked_mean=(sum(delta) / checked if checked else None))

    out = dict(made=_dt.datetime.now().isoformat(timespec='seconds'), prereg='docs/PREREG_R532_MINUTE_FIRST.md',
               blind_read=bool(a.blind), codes=len(codes), codes_with_bars=len(feats), etf_excluded=len(pool) - len([c for c in pool if c not in etf]),
               days=len(cal), normal_days=len(normal), abnormal_days=abnormal, first_day=(cal[0] if cal else None),
               last_day=(cal[-1] if cal else None), stock_days_liquid=n_liq, bad_lines=bad, blind_lines_dropped=blind_dropped,
               cost_wall=COST_WALL, cost_ops=COST_OPS, liq_floor=LIQ_FLOOR, splits=SPLITS, results=res,
               seconds=round(time.time() - t0, 1))
    tmp = a.out + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    os.replace(tmp, a.out)
    for q in ('Q1', 'Q2', 'Q3'):
        w = res[q]['wall']
        print(q, res[q]['verdict'])
        for name, _a, _b in SPLITS:
            x = w.get(name) or {}
            if x.get('n_dates'):
                print(f"   {name}: 날짜 {x['n_dates']} · 거래 {x['trades']:,} · 0.23% 뺀 날짜평균 {x['mean']:+.3f}% "
                      f"· 구간 {x['ci95'] and [round(v, 3) for v in x['ci95']]} · z {x['z'] and round(x['z'], 2)} "
                      f"· 거래 중앙 {x['median_trade'] and round(x['median_trade'], 3)} · 0 넘은 비율 {x['share_pos'] and round(x['share_pos'], 3)}")
    print('Q4', res['Q4'])
    print(f"끝 · {out['seconds']}초 · 종목 {len(feats)} · 날 {len(cal)}(정상 {len(normal)}) · 유동성 통과 종목-날 {n_liq:,} · 못 읽은 줄 {bad}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
