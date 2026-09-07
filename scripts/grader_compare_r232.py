# -*- coding: utf-8 -*-
"""
R232 — 같은 추천을 두 채점기가 어떻게 다르게 세는가 (측정 전용 · 값을 바꾸지 않는다).

경로 A: premarket.grade_history → prediction_log.grade_prediction
        (진입 = 리포트 가격 · 같은 봉 동시 도달 = 손절 먼저 · 창 안 미도달 = OPEN ·
         이력 마지막 100행만). 원장(scripts/calibration_lab.py)도 이 함수로 채점한다.
경로 B: improvement DB (scripts/run_daily_improvement → resolve_long_case)
        (진입 = rec_buy(권장매수가) 있으면 그것 · 같은 봉 = unresolved · 창 끝 미도달 =
         unresolved · 고유 (종목, 기준일) 전부 · 종가는 adj_close)

산출: data/grader_compare_r232.json — 재현 검사(저장된 판정을 같은 봉으로 다시 내면
같은가)가 먼저다. 재현이 깨지면 그 사실을 적고 exit 1 (R149 의 규칙).
"""
from __future__ import annotations
import os
import sys
import json
import statistics
from datetime import datetime
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:  # noqa: BLE001
    pass
import pandas as pd
import prediction_log as plog
from improvement.performance import resolve_long_case
from improvement.database import get_connection
import bitemporal_engine as be

OUT = os.path.join(BASE, 'data', 'grader_compare_r232.json')
PM_HISTORY = os.path.join(BASE, '.portfolio', 'premarket_history.jsonl')
TOL = 1e-6


def _engine():
    for nm in dir(be):
        if 'Engine' in nm:
            return getattr(be, nm)()
    raise RuntimeError('engine not found')


def _bars(eng, cache, errors, tk):
    if tk not in cache:
        try:
            cache[tk], _ = eng.generate_synthetic_bitemporal_data(
                symbol=tk, start_date='2024-01-01', end_date=None)
        except Exception as e:  # noqa: BLE001
            cache[tk] = None
            errors.append({'ticker': tk, 'error': repr(e)[:160]})
    return cache[tk]


def _window(df, signal_date, n):
    return df[df['trade_date'].astype(str) > str(signal_date)].head(int(n))


def _col(sub, *names):
    for n in names:
        if n in sub.columns:
            return sub[n]
    return None


def _frame(sub, close_name):
    return pd.DataFrame({'high': _col(sub, 'high_raw', 'high').values,
                         'low': _col(sub, 'low_raw', 'low').values,
                         'close': _col(sub, close_name, 'close').values})


def _med(xs):
    xs = [x for x in xs if x is not None]
    return (statistics.median(xs) if xs else None, len(xs))


def main() -> int:
    eng = _engine()
    cache, errors = {}, []
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM prediction_cases WHERE status IN ('success','failure','unresolved') "
        "ORDER BY signal_date, ticker").fetchall()
    per, repro_bad = [], []
    for r in rows:
        df = _bars(eng, cache, errors, r['ticker'])
        if df is None:
            continue
        sub = _window(df, r['signal_date'], r['holding_days'])
        if len(sub) < int(r['holding_days']):
            per.append({'ticker': r['ticker'], 'date': r['signal_date'],
                        'skip': 'window_short', 'bars': int(len(sub))})
            continue
        ref = float(r['reference_price'])
        tgt, stp = float(r['target_price']), float(r['stop_price'])
        ent = float(r['entry_price'] or ref)
        fr_adj = _frame(sub, 'adj_close')
        fr_raw = _frame(sub, 'close_raw')
        # B 를 기준가 진입으로 · 원시 종가로 (= R232 채택 규칙)
        b_ref = resolve_long_case(price_data=fr_raw, entry_price=ref,
                                  target_price=tgt, stop_price=stp)
        # B 재현 — 저장 당시 규칙으로. 2026-09-07 19:05 첫 측정은 R232 이전 저장(진입 = rec_buy ·
        #   종가 adj)이었고, 재환산(scripts/regrade_cases_r232.py) 뒤의 저장은 기준가 규칙이다.
        #   둘 중 어느 것으로 재현되는지 적는다 — 어느 쪽도 아니면 재현 실패.
        b_rep = resolve_long_case(price_data=fr_adj, entry_price=ent,
                                  target_price=tgt, stop_price=stp)

        def _same(res):
            return (res.status == r['status']
                    and (r['realized_return'] is None or res.realized_return is None
                         or abs(float(res.realized_return)
                                - float(r['realized_return'])) < TOL))
        repro_rule = ('pre_r232' if _same(b_rep) else
                      'r232' if _same(b_ref) else None)
        rep_ok = repro_rule is not None
        if not rep_ok:
            repro_bad.append({'ticker': r['ticker'], 'date': r['signal_date'],
                              'stored': [r['status'], r['realized_return']],
                              'pre_r232': [b_rep.status, b_rep.realized_return],
                              'r232': [b_ref.status, b_ref.realized_return]})
        # A — 원장과 같은 채점기
        gA = plog.grade_prediction({'date': r['signal_date'], 'price': ref, 'target': tgt,
                                    'stop': stp, 'horizon_days': r['holding_days']}, df)
        hi, lo = fr_raw['high'].tolist(), fr_raw['low'].tolist()
        touch = None
        for i, (h, l) in enumerate(zip(hi, lo), start=1):
            if h >= tgt or l <= stp:
                touch = i
                break
        same_bar = bool(touch and hi[touch - 1] >= tgt and lo[touch - 1] <= stp)
        upto = touch or len(lo)
        is_rec = bool(r['entry_price']) and abs(ent - ref) > 1e-9
        rec_reached = is_rec and any(l <= ent for l in lo[:upto])
        last_adj = float(fr_adj['close'].iloc[-1])
        last_raw = float(fr_raw['close'].iloc[-1])
        per.append({
            'ticker': r['ticker'], 'date': r['signal_date'], 'decision': r['decision'],
            'B_status': r['status'], 'B_ret_entry': r['realized_return'],
            'B_ret_ref': b_ref.realized_return, 'B_ref_status': b_ref.status,
            'A_outcome': gA['outcome'] if gA else None,
            'A_ret': gA['return_pct'] / 100.0 if gA else None,
            'same_bar': same_bar, 'touch_bar': touch,
            'entry_is_rec_buy': is_rec,
            'rec_buy_above_ref': is_rec and ent > ref,
            'rec_buy_reached_before_touch': rec_reached,
            'last_close_adj_ne_raw': abs(last_adj - last_raw) > 1e-9,
            'repro_ok': rep_ok, 'repro_rule': repro_rule,
        })
    graded = [p for p in per if 'skip' not in p]

    # A 가 지금 화면에 내는 수 — 이력 마지막 100행 (grade_history 의 슬라이스 그대로)
    hist = []
    with open(PM_HISTORY, encoding='utf-8') as f:
        for line in f:
            try:
                hist.append(json.loads(line))
            except Exception:  # noqa: BLE001
                continue
    today = datetime.now().strftime('%Y-%m-%d')
    screen = {'n': 0, 'TARGET': 0, 'STOP': 0, 'OPEN': 0, 'rows_seen': 0,
              'skipped_today': 0, 'no_bars': 0, 'dates': [None, None]}
    for h in hist[-100:]:
        screen['rows_seen'] += 1
        if h.get('date') == today:
            screen['skipped_today'] += 1
            continue
        df = _bars(eng, cache, errors, h.get('symbol'))
        if df is None:
            screen['no_bars'] += 1
            continue
        g = plog.grade_prediction({'date': h['date'], 'price': h.get('price'),
                                   'target': h.get('target'), 'stop': h.get('stop'),
                                   'horizon_days': h.get('horizon_days') or 20}, df)
        if not g:
            screen['no_bars'] += 1
            continue
        screen['n'] += 1
        screen[g['outcome']] += 1
        d = h['date']
        lo_d, hi_d = screen['dates']
        screen['dates'] = [d if lo_d is None or d < lo_d else lo_d,
                           d if hi_d is None or d > hi_d else hi_d]

    def _cnt(key):
        return sum(1 for p in graded if p.get(key) is True)

    agree = {}
    for p in graded:
        k = f"{p['B_status']}|{p['A_outcome']}"
        agree[k] = agree.get(k, 0) + 1
    db_tally = dict(conn.execute(
        "SELECT status, COUNT(*) FROM prediction_cases GROUP BY status").fetchall())
    art = {
        'measured_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'db_status_counts': db_tally,
        'resolved_rows': len(rows), 'graded': len(graded),
        'window_short': len(per) - len(graded),
        'fetch_errors': errors,
        'reproduction': {'ok': not repro_bad, 'bad': repro_bad, 'checked': len(graded)},
        'status_agreement_B_vs_A': agree,
        'same_bar_cases': _cnt('same_bar'),
        'entry_basis': {
            'entry_is_rec_buy': _cnt('entry_is_rec_buy'),
            'rec_buy_above_ref': _cnt('rec_buy_above_ref'),
            'rec_buy_never_reached_before_touch': sum(
                1 for p in graded
                if p['entry_is_rec_buy'] and not p['rec_buy_reached_before_touch']),
            'median_ret_B_entry': _med([p['B_ret_entry'] for p in graded]),
            'median_ret_B_ref': _med([p['B_ret_ref'] for p in graded]),
            'median_ret_A': _med([p['A_ret'] for p in graded]),
            'B_ref_status_eq_B_status': sum(
                1 for p in graded if p['B_ref_status'] == p['B_status']),
        },
        'close_basis_last_bar_adj_ne_raw': _cnt('last_close_adj_ne_raw'),
        'screen_now_A_last100': screen,
        'per_case': per,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(art, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in art.items() if k != 'per_case'},
                     ensure_ascii=False, indent=1))
    if repro_bad:
        print(f"재현 실패 {len(repro_bad)}건 — 측정을 판정에 쓰지 않는다 (R149)")
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
