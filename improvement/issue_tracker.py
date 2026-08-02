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


def resolve_by_key(conn: sqlite3.Connection, issue_key: str) -> None:
    """조건이 해소된 이슈를 키로 닫는다 (해결 여부 표시)."""
    conn.execute(
        "UPDATE improvement_issues SET status='resolved', resolved_at=? "
        "WHERE issue_key=? AND status='open'",
        (datetime.now(timezone.utc).isoformat(), issue_key))
