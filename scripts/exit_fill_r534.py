# -*- coding: utf-8 -*-
"""라운드 534 — 매도는 계획한 가격에 나가나 (사전등록 `docs/PREREG_R534_EXIT_FILLS.md` · 결과 전 커밋 · 측정 · 판정 없음).

원장 STOP·TARGET 행(통계 행 · 고정 목록 주식 · 결정 봉 날짜에 분봉)마다 그날 분봉으로 실행부식 체결을 추정한다:
  손절 = 처음 저가 ≤ 손절선인 분봉의 min(시가, 손절선) — 워커의 시장가 매도
  목표 = 처음 고가 ≥ 목표인 분봉의 max(시가, 목표) — 하루짜리 지정가 매도
원장 수익(선 가격에 나갔다고 본 값)과의 차이를 구간별로 센다. 블라인드(2026-05-01~)는 `--blind` 없이는 읽지 않는다. 읽기만 하고 결과 파일 하나를 쓴다.
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import io
import json
import os
import statistics
import sys
import time

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
sys.path.insert(0, os.path.join(PROJ, 'scripts'))
import minute_study_r532 as M  # noqa: E402

FROM_DAY = '2025-09-01'


def nth_trading_day_after(d0, n, is_off):
    d = _dt.date.fromisoformat(d0)
    k = 0
    for _ in range(400):
        d += _dt.timedelta(days=1)
        if not is_off(d.isoformat()):
            k += 1
            if k == n:
                return d.isoformat()
    return None


def fill_of(bars, outcome, line):
    """그날 분봉(시각 순) → (추정 체결가, 그 분봉이 선을 이미 넘어 시작했나) 또는 (None, None)(분봉으로는 안 닿음)."""
    for b in bars:
        if outcome == 'STOP' and b['l'] <= line:
            return min(b['o'], line), b['o'] < line
        if outcome == 'TARGET' and b['h'] >= line:
            return max(b['o'], line), b['o'] > line
    return None, None


def pct(xs, q):
    if not xs:
        return None
    s = sorted(xs)
    return s[min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--blind', action='store_true')
    ap.add_argument('--out', default=os.path.join(PROJ, 'data', 'exit_fill_r534.json'))
    ap.add_argument('--root', default=None, help='시험용 — 분봉 폴더')
    ap.add_argument('--codes', default=None, help='시험용 — 대상 코드(쉼표)')
    ap.add_argument('--ledger', default=None, help='시험용 — 원장 대신 읽을 파일')
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError):
        pass
    t0 = time.time()
    import ledger_view as LV
    from improvement import case_tracker as ct
    root = a.root or M.ROOT
    if a.codes:
        codes = [c.strip() for c in a.codes.split(',') if c.strip()]
    else:
        from collect_minute_bars import pool_codes
        etf = M.etf_codes()
        pool = pool_codes()
        if not pool or etf is None:
            print('고정 목록 또는 ETF 색인을 못 읽었다 — 멈춘다')
            return 2
        codes = [c for c in pool if c not in etf]
    codes_set = set(codes)
    rows = []
    with io.open(a.ledger or os.path.join(PROJ, '.portfolio', 'virtual_graded.jsonl'), encoding='utf-8') as f:
        def _rows():
            for ln in f:
                try:
                    yield json.loads(ln)
                except ValueError:
                    continue
        for r in LV.stat_rows(_rows(), keys=LV.scale_mismatch_keys()):
            if r.get('outcome') in ('STOP', 'TARGET') and LV.code6(r.get('ticker')) in codes_set and r.get('touched_bar') \
                    and r.get('price') and r.get('stop') and r.get('target') and str(r.get('date'))[:10] >= FROM_DAY:
                dd = nth_trading_day_after(str(r['date'])[:10], int(r['touched_bar']), ct.is_non_trading_date)
                if dd and (a.blind or dd < M.BLIND_FROM):
                    r['_dd'] = dd
                    rows.append(r)
    need = collections.defaultdict(set)
    for r in rows:
        need[LV.code6(r['ticker'])].add(r['_dd'])
    bars_of = {}
    lo_day, hi_day = '9999', '0000'
    for code in sorted(need):
        p = os.path.join(root, f'{code}.jsonl')
        if not os.path.exists(p):
            continue
        days, _b1, _b2 = M.read_code(p, a.blind)
        if days:
            lo_day, hi_day = min(lo_day, min(days)), max(hi_day, max(days))
        for d in need[code]:
            if days.get(d):
                bars_of[(code, d)] = days[d]
    cnt = collections.Counter()
    by = collections.defaultdict(lambda: collections.defaultdict(list))   # split → outcome → [(diff, gap)]
    for r in rows:
        code, dd = LV.code6(r['ticker']), r['_dd']
        if dd < lo_day or dd > hi_day:
            cnt['분봉 기간 밖'] += 1
            continue
        bars = bars_of.get((code, dd))
        if not bars:
            cnt['그날 분봉 없음'] += 1
            continue
        oc = r['outcome']
        line = float(r['stop'] if oc == 'STOP' else r['target'])
        entry = float(r['price'])
        fill, gap = fill_of(bars, oc, line)
        if fill is None:
            cnt[f'{oc} · 분봉으로는 선에 안 닿음(일봉과 어긋남)'] += 1
            continue
        sp = M.split_of(dd)
        diff = (fill / entry - 1.0) * 100.0 - (line / entry - 1.0) * 100.0
        by[sp][oc].append((diff, bool(gap)))
        cnt[f'{oc} · 잼'] += 1
    res = {}
    for sp, d in by.items():
        out = {}
        allv = []
        for oc, xs in d.items():
            diffs = [x for x, _g in xs]
            allv += diffs
            out[oc] = dict(n=len(xs), gap_share=sum(1 for _x, g in xs if g) / len(xs), mean_diff=statistics.mean(diffs),
                           median_diff=statistics.median(diffs), p05=pct(diffs, 0.05), p95=pct(diffs, 0.95),
                           gap_mean_diff=(statistics.mean([x for x, g in xs if g]) if any(g for _x, g in xs) else None))
        out['all'] = dict(n=len(allv), mean_shift=(statistics.mean(allv) if allv else None))
        res[sp] = out
    doc = dict(made=_dt.datetime.now().isoformat(timespec='seconds'), prereg='docs/PREREG_R534_EXIT_FILLS.md', blind_read=bool(a.blind),
               rows=len(rows), counts=dict(cnt), minute_days=[lo_day, hi_day], results=res, seconds=round(time.time() - t0, 1))
    tmp = a.out + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    os.replace(tmp, a.out)
    for sp in ('train', 'valid', 'blind'):
        if sp in res:
            for oc in ('STOP', 'TARGET'):
                x = res[sp].get(oc)
                if x:
                    print(f"{sp} {oc}: {x['n']}행 · 갭 {x['gap_share'] * 100:.1f}% · 차이 평균 {x['mean_diff']:+.3f}%p · 중앙 {x['median_diff']:+.3f} "
                          f"· 하위5% {x['p05']:+.3f} · 상위5% {x['p95']:+.3f}")
            print(f"{sp} 전체 {res[sp]['all']['n']}행 · 평균 이동 {res[sp]['all']['mean_shift']:+.3f}%p")
    print('셈', dict(cnt), '·', doc['seconds'], '초')
    return 0


if __name__ == '__main__':
    sys.exit(main())
