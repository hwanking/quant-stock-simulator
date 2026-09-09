# -*- coding: utf-8 -*-
"""이슈 트래커 — issue_key 로 같은 이슈의 매일 중복 생성을 막는다."""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional


def create_issue(conn: sqlite3.Connection, *, category: str, severity: str,
                 title: str, summary: str, detail: Optional[str] = None,
                 related_model: Optional[str] = None,
                 related_ticker: Optional[str] = None,
                 issue_key: Optional[str] = None) -> Optional[str]:
    """
    issue_key(안 주면 category|title)가 이미 open 이면 만들지 않는다 —
    같은 경고가 매일 새 줄로 쌓이는 것을 막는다. 생성 시 issue_id 반환.
    """
    key = issue_key or f"{category}|{title}"
    dup = conn.execute(
        "SELECT issue_id FROM improvement_issues "
        "WHERE issue_key=? AND status='open'", (key,)).fetchone()
    if dup:
        return None
    issue_id = f"ISSUE-{uuid.uuid4().hex[:12]}"
    conn.execute(
        """
        INSERT OR IGNORE INTO improvement_issues (
            issue_id, issue_key, created_at, category, severity,
            title, summary, detail, status, related_model, related_ticker
        ) VALUES (?,?,?,?,?,?,?,?, 'open', ?, ?)
        """,
        (issue_id, key, datetime.now(timezone.utc).isoformat(), category,
         severity, title, summary, detail, related_model, related_ticker))
    return issue_id


def list_open_issues(conn: sqlite3.Connection, limit: int = 5) -> list:
    return conn.execute(
        """
        SELECT * FROM improvement_issues WHERE status='open'
        ORDER BY CASE severity
            WHEN 'critical' THEN 1 WHEN 'high' THEN 2
            WHEN 'medium' THEN 3 ELSE 4 END,
            created_at DESC
        LIMIT ?
        """, (limit,)).fetchall()


def resolve_issue(conn: sqlite3.Connection, issue_id: str) -> None:
    conn.execute(
        "UPDATE improvement_issues SET status='resolved', resolved_at=? "
        "WHERE issue_id=?",
        (datetime.now(timezone.utc).isoformat(), issue_id))


def resolve_by_key(conn: sqlite3.Connection, issue_key: str) -> Optional[str]:
    """조건이 해소된 이슈를 키로 닫는다 (해결 여부 표시).

    ⚠️ 라운드 256 (2026-09-10) — **재검토일이 아직 안 온 이슈는 닫지 않는다.**
      일일 규칙은 '오늘의 수'(valid−blind 괴리 · 신호율)로 이 함수를 불렀고, 이슈에는
      플레이북이 적어 둔 **다른 목표와 재검토일**이 있었다. 실측: `model|vb_gap`
      (재검토 2026-11-16 · 목표 "같은 국면끼리 5%p 이내")이 2026-09-03 에 전체 구간
      괴리 < 10%p 로 자동 '해결'됐고, `usability|signal_rate`(재검토 09-16 · 목표
      "블라인드 약세 표본 100건+ 뒤 재판정")는 08-15 에 신호율 6.7% > 5% 로 닫혔다.
      닫는 규칙과 이슈의 목표가 **다른 것을 잰다.** 재검토일 전에는 닫지 않고 사유를
      돌려준다 — 호출부가 찍는다(§3 · 조용히 넘기지 않는다). 재검토일이 없거나
      지났으면 종전처럼 닫는다. 읽는 쪽은 여전히 `status` 를 먼저 본다(라운드 172).

    반환: 닫지 않은 사유(str) 또는 None(닫았거나 열린 이슈가 없다).
    """
    try:
        row = conn.execute(
            "SELECT next_review FROM improvement_issues "
            "WHERE issue_key=? AND status='open'", (issue_key,)).fetchone()
    except sqlite3.OperationalError:
        # `next_review` 는 issue_ops.ensure_schema 가 더하는 확장 칸이다. 아직 없는
        # DB(갓 만든 것)에서는 재검토일이 없는 것과 같다 — 종전처럼 닫는다. 여기서
        # 죽으면 일일 파이프라인이 통째로 선다.
        row = conn.execute(
            "SELECT 1 FROM improvement_issues "
            "WHERE issue_key=? AND status='open'", (issue_key,)).fetchone()
        row = (None,) if row else None
    if row is None:
        return None
    nr = str(row[0] or '')[:10]
    if nr:
        try:
            due = datetime.fromisoformat(nr).date()
            today = datetime.now(timezone.utc).astimezone().date()
            if due > today:
                return f"재검토일 {nr} 전 — 오늘의 수로 닫지 않는다"
        except ValueError:
            pass
    conn.execute(
        "UPDATE improvement_issues SET status='resolved', resolved_at=? "
        "WHERE issue_key=? AND status='open'",
        (datetime.now(timezone.utc).isoformat(), issue_key))
    return None
