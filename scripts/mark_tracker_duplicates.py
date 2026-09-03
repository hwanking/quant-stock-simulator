# -*- coding: utf-8 -*-
"""실전 추천 추적 DB 의 복사본·시험 픽스처를 **표시**한다 (라운드 222).

■ 왜
  `run_daily_improvement` 의 케이스 열쇠에 모델 버전이 들어 있어, 버전이 바뀔
  때마다 지난 추천이 통째로 다시 동결됐다. 실측(2026-09-04): 463행 중 고유
  (종목, 기준일) 218 · 복사본 245(53%). 그리고 회귀의 시험 픽스처(2099-01-01)가
  이력에 남아 버전마다 유입됐다(7벌). 어느 쌍도 서로 다른 결과로 확정되지
  않았으므로(0건) 복사본을 빼도 정보는 하나도 사라지지 않는다.

■ 무엇을 하나 — 지우지 않는다 (R197)
  · 같은 (종목, 기준일)의 **가장 먼저** 동결된 행을 남기고, 뒤 복사본은
    status='dup_version' 으로 표시한다(원본 case_id 를 사유에 적는다).
  · 기준일이 오늘보다 뒤인 행은 status='void_fixture'.
  · 이미 표시된 행은 다시 건드리지 않는다 — **두 번 돌려도 같다**(멱등).
  · 돌리기 전에 DB 를 복사해 둔다.

    C:/Python314/python.exe scripts/mark_tracker_duplicates.py [--dry-run] [--db PATH] [--today YYYY-MM-DD]
"""
import argparse
import collections
import datetime as dt
import os
import shutil
import sqlite3
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:                                              # noqa: BLE001
    pass
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(PROJ, '.portfolio', 'improvement.db')
DUP = 'dup_version'
VOID = 'void_fixture'


def plan(conn, today):
    """(void 목록, dup 목록) — 각 원소는 (case_id, 원본 case_id | None)."""
    rows = conn.execute(
        "SELECT case_id, ticker, signal_date, status, created_at FROM prediction_cases "
        "ORDER BY signal_date, ticker, created_at").fetchall()
    first = {}
    void, dup = [], []
    for cid, tk, d, st, _ca in rows:
        if st in (DUP, VOID):
            continue                          # 이미 표시됨 — 멱등
        if str(d)[:10] > today:
            void.append((cid, None))
            continue
        key = (str(tk), str(d)[:10])
        if key in first:
            dup.append((cid, first[key]))
        else:
            first[key] = cid
    return void, dup


def apply(conn, void, dup, today):
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    for cid, _ in void:
        conn.execute(
            "UPDATE prediction_cases SET status=?, result_reason=?, resolved_at=? WHERE case_id=?",
            (VOID, f'R222 — 시험 픽스처(기준일이 {today} 보다 뒤) 가 이력에서 유입됨', now, cid))
    for cid, orig in dup:
        conn.execute(
            "UPDATE prediction_cases SET status=?, result_reason=?, resolved_at=? WHERE case_id=?",
            (DUP, f'R222 — 같은 추천이 모델 버전이 바뀔 때마다 다시 동결됨 (원본 {orig})', now, cid))
    conn.commit()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=DEFAULT_DB)
    ap.add_argument('--today', default=dt.date.today().isoformat())
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args(argv)
    if not os.path.exists(a.db):
        print('DB 없음:', a.db)
        return 1
    conn = sqlite3.connect(a.db)
    before = dict(conn.execute(
        "SELECT status, COUNT(*) FROM prediction_cases GROUP BY status").fetchall())
    void, dup = plan(conn, a.today)
    print(f'표시 전: {before}')
    print(f'계획: 시험 픽스처 {len(void)}건 · 버전 복사본 {len(dup)}건')
    if a.dry_run:
        conn.close()
        return 0
    if void or dup:
        bak = a.db + '.r222.bak'
        if not os.path.exists(bak):
            shutil.copy2(a.db, bak)
            print('백업:', bak)
        apply(conn, void, dup, a.today)
    after = dict(conn.execute(
        "SELECT status, COUNT(*) FROM prediction_cases GROUP BY status").fetchall())
    real = conn.execute(
        "SELECT COUNT(*) FROM prediction_cases WHERE status NOT IN (?, ?)", (DUP, VOID)).fetchone()[0]
    distinct = conn.execute(
        "SELECT COUNT(*) FROM (SELECT DISTINCT ticker, signal_date FROM prediction_cases "
        "WHERE status NOT IN (?, ?))", (DUP, VOID)).fetchone()[0]
    print(f'표시 후: {after}')
    print(f'실제 케이스 {real}건 = 고유 (종목,기준일) {distinct}건 → {"일치" if real == distinct else "불일치!"}')
    conn.close()
    return 0 if real == distinct else 2


if __name__ == '__main__':
    sys.exit(main())
