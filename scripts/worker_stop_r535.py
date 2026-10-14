# -*- coding: utf-8 -*-
"""라운드 535 — 실제 워커의 손절(1분마다 지금 가격 확인 · 손절선 이하면 시장가)을 분봉으로 따라가 원장 채점(장중 터치)과 대 본다
(사전등록 `docs/PREREG_R535_WORKER_STOP.md` · 결과 전 커밋 · 측정 · 판정 없음).

행마다 원장 진입·목표·손절 그대로 · 기준일 다음 20거래일을 분 단위로: 고가 ≥ 목표면 max(시가, 목표)(같은 분이면 목표 먼저) · 종가 ≤ 손절이면
그 종가 · 둘 다 없으면 20번째 날 마지막 종가. 블라인드(2026-05-01~)는 `--blind` 없이는 안 읽는다. 읽기만 하고 결과 파일 하나를 쓴다.
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

HORIZON = 20
FROM_DAY = '2025-09-26'
BUYZONE = 58          # 매수권 — 이미 채택된 하한(원장 통계·화면이 쓰는 58점+ · 새 숫자 아님)


def trading_days_after(d0, n, is_off):
    out, d = [], _dt.date.fromisoformat(d0)
    for _ in range(400):
        d += _dt.timedelta(days=1)
        if not is_off(d.isoformat()):
            out.append(d.isoformat())
            if len(out) == n:
                return out
    return None


def simulate(days_bars, entry, target, stop):
    """[[분봉 …] × 20일] → (갈래, 체결가). 고가 ≥ 목표면 목표(같은 분이면 목표 먼저) · 종가 ≤ 손절이면 그 종가 · 없으면 마지막 종가."""
    for bars in days_bars:
        for b in bars:
            if target and b['h'] >= target:
                return 'TARGET', max(b['o'], target)
            if stop and b['c'] <= stop:
                return 'STOP', b['c']
    return 'OPEN', days_bars[-1][-1]['c']


def pct(xs, q):
    if not xs:
        return None
    s = sorted(xs)
    return s[min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--blind', action='store_true')
    ap.add_argument('--out', default=os.path.join(PROJ, 'data', 'worker_stop_r535.json'))
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
        etf, pool = M.etf_codes(), pool_codes()
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
            if (LV.code6(r.get('ticker')) in codes_set and r.get('outcome') in ('TARGET', 'STOP', 'OPEN') and r.get('price')
                    and r.get('target') and r.get('stop') and r.get('return_pct') is not None and str(r.get('date'))[:10] >= FROM_DAY):
                win = trading_days_after(str(r['date'])[:10], HORIZON, ct.is_non_trading_date)
                if win and (a.blind or win[-1] < M.BLIND_FROM):
                    r['_win'] = win
                    rows.append(r)
    by_code = collections.defaultdict(list)
    for r in rows:
        by_code[LV.code6(r['ticker'])].append(r)
    cnt = collections.Counter()
    res_rows = []
    for code, rs in sorted(by_code.items()):
        p = os.path.join(root, f'{code}.jsonl')
        if not os.path.exists(p):
            cnt['분봉 파일 없음'] += len(rs)
            continue
        days, _b1, _b2 = M.read_code(p, a.blind)
        for r in rs:
            win = r['_win']
            if any(not days.get(d) for d in win):
                cnt['20거래일 중 분봉 없는 날'] += 1
                continue
            entry, tp, sl = float(r['price']), float(r['target']), float(r['stop'])
            oc, fill = simulate([days[d] for d in win], entry, tp, sl)
            wret = (fill / entry - 1.0) * 100.0
            sp = M.split_of(str(r['date'])[:10])
            res_rows.append(dict(split=sp, date=str(r['date'])[:10], score=r.get('score'), led_oc=r['outcome'], led_ret=float(r['return_pct']),
                                 w_oc=oc, w_ret=wret, stop_ret=(sl / entry - 1.0) * 100.0))
            cnt['잼'] += 1
        del days

    def summ(xs):
        if not xs:
            return dict(n=0)
        by_day = collections.defaultdict(list)
        for x in xs:
            by_day[x['date']].append(x['w_ret'] - x['led_ret'])
        dv = {d: statistics.mean(v) for d, v in by_day.items()}
        ci = M.boot_ci(dv, sorted(dv))
        trans = collections.Counter(f"{x['led_oc']}→{x['w_oc']}" for x in xs)
        deep = [x['w_ret'] - x['stop_ret'] for x in xs if x['w_oc'] == 'STOP']
        return dict(n=len(xs), dates=len(dv), led_mean=statistics.mean(x['led_ret'] for x in xs),
                    w_mean=statistics.mean(x['w_ret'] for x in xs), diff_mean_by_date=ci.get('mean'), diff_ci95=ci.get('ci95'),
                    transitions=dict(trans.most_common()), stop_depth_mean=(statistics.mean(deep) if deep else None),
                    stop_depth_p05=pct(deep, 0.05))
    out = {}
    for sp in ('train', 'valid', 'blind'):
        xs = [x for x in res_rows if x['split'] == sp]
        if xs:
            out[sp] = dict(all=summ(xs), buyzone=summ([x for x in xs if (x['score'] or 0) >= BUYZONE]))
    doc = dict(made=_dt.datetime.now().isoformat(timespec='seconds'), prereg='docs/PREREG_R535_WORKER_STOP.md', blind_read=bool(a.blind),
               rows_considered=len(rows), counts=dict(cnt), horizon=HORIZON, buyzone=BUYZONE, results=out,
               seconds=round(time.time() - t0, 1))
    tmp = a.out + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    os.replace(tmp, a.out)
    for sp, d in out.items():
        for k in ('all', 'buyzone'):
            x = d[k]
            if x.get('n'):
                print(f"{sp} {k}: {x['n']}행 · 날짜 {x['dates']} · 원장 평균 {x['led_mean']:+.3f}% · 워커식 {x['w_mean']:+.3f}% · 차이(날짜 평균) "
                      f"{x['diff_mean_by_date']:+.3f}%p {x['diff_ci95'] and [round(v, 3) for v in x['diff_ci95']]} · 갈래 {x['transitions']} · "
                      f"손절 깊이 평균 {x['stop_depth_mean'] if x['stop_depth_mean'] is None else round(x['stop_depth_mean'], 3)} "
                      f"하위5% {x['stop_depth_p05'] if x['stop_depth_p05'] is None else round(x['stop_depth_p05'], 3)}")
    print('셈', dict(cnt), '·', doc['seconds'], '초')
    return 0


if __name__ == '__main__':
    sys.exit(main())
