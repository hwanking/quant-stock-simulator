# -*- coding: utf-8 -*-
"""
R232 — 이미 확정된 전방 추적 케이스를 **원장과 같은 채점기**로 다시 환산한다 (멱등).

무엇이 바뀌나: 진입 = 권장매수가(rec_buy) → 기준가(리포트 가격) · MDD 는 청산 봉까지 ·
같은 봉 동시 도달은 손절 먼저(실측 0건). 판정(status)은 진입가와 무관하므로 안 바뀌어야
한다 — 바뀌면 그 사실을 세어 찍고 새 규칙의 판정을 쓴다(같은 봉만 그럴 수 있다).
원장 행은 지우지 않는다. 두 번 돌리면 두 번째는 0건이 바뀐다.

산출: data/regrade_cases_r232.json (건별 전·후 · 바뀐 수 · 잰 날짜).
실행:  python scripts/regrade_cases_r232.py
"""
from __future__ import annotations
import os
import sys
import json
from datetime import datetime, timezone
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:  # noqa: BLE001
    pass
import prediction_log as plog
from improvement.performance import resolution_from_grade
from improvement.database import get_connection
import bitemporal_engine as be

OUT = os.path.join(BASE, 'data', 'regrade_cases_r232.json')
TOL = 1e-9


def _engine():
    for nm in dir(be):
        if 'Engine' in nm:
            return getattr(be, nm)()
    raise RuntimeError('engine not found')


def main() -> int:
    eng = _engine()
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM prediction_cases WHERE status IN ('success','failure','unresolved') "
        "ORDER BY signal_date, ticker").fetchall()
    cache, per = {}, []
    changed = status_changed = untouched = no_bars = 0
    for r in rows:
        tk = r['ticker']
        if tk not in cache:
            try:
                cache[tk], _ = eng.generate_synthetic_bitemporal_data(
                    symbol=tk, start_date='2024-01-01', end_date=None)
            except Exception as e:  # noqa: BLE001
                cache[tk] = None
                print(f"  시세 못 받음 {tk}: {e!r}"[:160])
        df = cache[tk]
        if df is None:
            no_bars += 1
            continue
        g = plog.grade_prediction(
            {'date': r['signal_date'], 'price': float(r['reference_price']),
             'target': float(r['target_price']), 'stop': float(r['stop_price']),
             'horizon_days': int(r['holding_days'])}, df)
        if not g or (g['outcome'] == 'OPEN' and not g['matured']):
            no_bars += 1
            continue
        res = resolution_from_grade(g, target_price=float(r['target_price']),
                                    stop_price=float(r['stop_price']))
        before = {'status': r['status'], 'realized_return': r['realized_return'],
                  'max_drawdown': r['max_drawdown'], 'exit_price': r['exit_price']}
        after = {'status': res.status, 'realized_return': res.realized_return,
                 'max_drawdown': res.max_drawdown, 'exit_price': res.exit_price}
        same = (before['status'] == after['status']
                and all(before[k] is not None and abs(float(before[k]) - float(after[k])) < TOL
                        for k in ('realized_return', 'max_drawdown', 'exit_price')))
        per.append({'ticker': tk, 'date': r['signal_date'], 'before': before, 'after': after,
                    'entry_was': r['entry_price'], 'reference': r['reference_price'],
                    'changed': not same})
        if same:
            untouched += 1
            continue
        if before['status'] != after['status']:
            status_changed += 1
        conn.execute(
            "UPDATE prediction_cases SET status=?, exit_price=?, realized_return=?, "
            "max_drawdown=?, result_reason=? WHERE case_id=?",
            (res.status, res.exit_price, res.realized_return, res.max_drawdown,
             res.reason, r['case_id']))
        changed += 1
    conn.commit()
    conn.close()
    art = {'regraded_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
           'resolved_rows': len(rows), 'changed': changed, 'status_changed': status_changed,
           'untouched': untouched, 'no_bars': no_bars, 'rule': 'prediction_log.grade_prediction — 진입 = 기준가(리포트 가격) · 먼저 닿은 선 · 같은 봉이면 손절 먼저 · MDD 는 청산 봉까지 (R232)',
           'per_case': per}
    prev = None
    if os.path.exists(OUT):
        try:
            with open(OUT, encoding='utf-8') as f:
                prev = json.load(f)
        except Exception:  # noqa: BLE001
            prev = None
    if prev and changed == 0 and prev.get('changed'):
        # 두 번째 실행 — 첫 실행의 전·후 기록을 지우지 않는다. 멱등 확인만 덧붙인다.
        prev.setdefault('idempotent_reruns', []).append(art['regraded_at'])
        art = prev
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(art, f, ensure_ascii=False, indent=1)
    print(f"확정 {len(rows)}건 — 다시 환산 {changed}건 (판정 바뀜 {status_changed}) · "
          f"그대로 {untouched}건 · 시세 없음 {no_bars}건 · {art.get('regraded_at')}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
