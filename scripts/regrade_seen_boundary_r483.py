# -*- coding: utf-8 -*-
"""확정된 추적 케이스 중 **장중에 본 가격**으로 동결된 것을 그 장의 봉을 빼고 다시 채점한다 (라운드 483 · 한 번 · 멱등).

■ 왜 (2026-10-11 실측)
  추적 케이스의 진입가는 동결한 이력 줄(개장 전 리포트)의 가격이고, 채점은 자료 기준일 D 의 다음 봉부터 돌았다. 그런데 리포트가
  D 다음 거래일 T 의 **정규장 중**에 만들어지면(앱을 장중에 처음 연 날) 그 가격은 T 의 장중 값이다 — 255건 중 32건이 그랬고
  (종가 대비 +0.05~+24.4% · 전부 T 봉의 고가·저가 사이), 채점은 T 봉 전체(그 가격을 보기 **전**의 아침 고가·저가 포함)를 봤다.
  규칙은 `prediction_log.grade_after_day` 한 곳이고, 일일 루틴은 이제 그것으로 채점한다. 이 스크립트는 이미 확정된 옛 케이스에
  같은 채점기로 한 번 적용한다(라운드 232·442 의 재환산과 같은 길 · 가격·목표·손절·보유기간은 그대로 · 바뀌는 것은 채점 창의 시작뿐).

■ 무엇을 하나 — 지우지 않는다 (R197)
  · 경계가 자료일과 같은 케이스는 안 본다(대부분).
  · 확정(success·failure·unresolved)이면 경계 다음 봉부터 다시 채점해 결과를 바꾸고 사유 끝에 `R483` 과 경계를 적는다.
    다시 채점해 아직 기간 중이면 open 으로 되돌린다(일일 루틴이 이어 채점한다).
  · open 이면 안 건드린다 — 일일 루틴이 이제 새 규칙으로 채점한다.
  · 사유에 `R483` 이 이미 있으면 다시 안 본다 — **두 번 돌려도 같다**.
  · 일봉을 못 받은 종목은 건드리지 않고 센다(§3).

  기본은 미리보기(DB 를 메모리에 복사해 적용하고 전·후 집계를 찍는다) · `--apply` 면 원본을 먼저 복사해 두고(.r483.bak) 고친다.

    C:/Python314/python.exe scripts/regrade_seen_boundary_r483.py [--apply] [--db PATH] [--history PATH]
"""
import argparse
import collections
import os
import shutil
import sqlite3
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:                                              # noqa: BLE001
    pass
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (PROJ, os.path.join(PROJ, 'scripts')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import prediction_log as plog                                  # noqa: E402
from improvement import case_tracker as ct                     # noqa: E402
from improvement.performance import resolution_from_grade      # noqa: E402

DEFAULT_DB = os.path.join(PROJ, '.portfolio', 'improvement.db')
DEFAULT_HISTORY = os.path.join(PROJ, '.portfolio', 'premarket_history.jsonl')
DECIDED = ('success', 'failure', 'unresolved')
TAG = 'R483'


def plan_actions(rows, seen):
    """(case_id, 경계, row) — 경계가 기준일과 다른 확정 케이스만 · 이미 고친 것(사유에 R483)은 뺀다. (actions, 셈)"""
    cnt = collections.Counter()
    out = []
    for r in rows:
        if r['status'] in ct.EXCLUDED_STATUSES:
            continue
        s = seen.get((str(r['ticker']), str(r['signal_date']), float(r['reference_price'])))
        b = plog.grade_after_day(r['signal_date'], s)
        if b == str(r['signal_date'])[:10]:
            cnt['경계 = 기준일(그대로)'] += 1
            continue
        if TAG in str(r['result_reason'] or ''):
            cnt['이미 고침'] += 1
            continue
        if r['status'] not in DECIDED:
            cnt[f"경계 다름 · {r['status']}(일일 루틴이 새 규칙으로 채점)"] += 1
            continue
        out.append((r['case_id'], b, r))
    return out, cnt


def apply(conn, actions, bars_fn):
    cnt = collections.Counter()
    for cid, b, r in actions:
        if not (r['target_price'] and r['stop_price']):
            cnt['목표·손절 없음 — 안 건드림'] += 1
            continue
        df = bars_fn(r['ticker'])
        if df is None:
            cnt['일봉 못 받음 — 안 건드림'] += 1
            continue
        g = plog.grade_prediction({'date': b, 'price': float(r['reference_price']), 'target': float(r['target_price']),
                                   'stop': float(r['stop_price']), 'horizon_days': int(r['holding_days'])}, df)
        if not g:
            cnt['채점 못 함 — 안 건드림'] += 1
            continue
        if g['outcome'] == 'OPEN' and not g['matured']:
            conn.execute("UPDATE prediction_cases SET status='open', exit_price=NULL, realized_return=NULL, "
                         "max_drawdown=NULL, result_reason=?, resolved_at=NULL WHERE case_id=?",
                         (f"{TAG} — 가격을 본 장({b})의 봉을 빼면 아직 기간 중", cid))
            cnt[f"{r['status']} → open"] += 1
            continue
        res = resolution_from_grade(g, target_price=float(r['target_price']), stop_price=float(r['stop_price']))
        conn.execute("UPDATE prediction_cases SET status=?, exit_price=?, realized_return=?, max_drawdown=?, result_reason=? "
                     "WHERE case_id=?",
                     (res.status, res.exit_price, res.realized_return, res.max_drawdown,
                      f"{res.reason} · {TAG} 가격을 본 장({b})의 봉을 빼고 재환산", cid))
        cnt[f"{r['status']} → {res.status}"] += 1
    conn.commit()
    return cnt


def _tally_line(t):
    return (f"성공 {t['success']} · 실패 {t['failure']} · 미도달 {t['unresolved']} · open {t['open']} · "
            f"성공률 {('%.1f%%' % t['success_pct']) if t['success_pct'] is not None else '없음'}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=DEFAULT_DB)
    ap.add_argument('--history', default=DEFAULT_HISTORY)
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args(argv)
    if not os.path.exists(a.db):
        print('DB 없음:', a.db)
        return 1
    import run_daily_improvement as rdi
    seen = rdi.freeze_seen_at(a.history)
    if not seen:
        print('리포트 이력 없음:', a.history, '— 본 시각을 구할 수 없어 아무것도 안 한다')
        return 1
    if a.apply:
        bak = a.db + '.r483.bak'
        if not os.path.exists(bak):
            shutil.copy2(a.db, bak)
            print('백업:', bak)
        conn = sqlite3.connect(a.db)
    else:
        src = sqlite3.connect(f'file:{a.db}?mode=ro', uri=True)
        conn = sqlite3.connect(':memory:')
        src.backup(conn)
        src.close()
    conn.row_factory = sqlite3.Row
    before = ct.tally(conn)
    rows = conn.execute('SELECT * FROM prediction_cases').fetchall()
    actions, cnt = plan_actions(rows, seen)
    import bitemporal_engine as be
    eng = be.BitemporalEngine()
    cache = {}

    def bars(tk):
        if tk not in cache:
            try:
                cache[tk] = eng.fetch_daily_bars(tk)
            except Exception:                                  # noqa: BLE001
                cache[tk] = None
        return cache[tk]

    cnt.update(apply(conn, actions, bars))
    after = ct.tally(conn)
    print(('적용' if a.apply else '미리보기') + f' — 케이스 {len(rows)} · 다시 채점 대상 {len(actions)}')
    for k, v in sorted(cnt.items()):
        print(f'  {k}: {v}')
    print('  전:', _tally_line(before))
    print('  후:', _tally_line(after))
    conn.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
