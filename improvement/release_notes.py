# -*- coding: utf-8 -*-
"""
릴리스 노트 — 승격·주요 버전 기록 전용.

일상 개선 이력의 원천은 git 커밋 로그(update_history)다 — 여기와 중복 기록하지
않는다. 이 테이블은 모델 승격/기각 같은 '버전 사건'만 남긴다.
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional


def add_release_note(conn: sqlite3.Connection, *, version: str, category: str,
                     title: str, summary: str, detail: Optional[str] = None,
                     is_major: bool = False) -> str:
    release_id = f"REL-{uuid.uuid4().hex[:12]}"
    conn.execute(
        """
        INSERT INTO release_notes (
            release_id, released_at, version, category, title,
            summary, detail, is_major
        ) VALUES (?,?,?,?,?,?,?,?)
        """,
        (release_id, datetime.now(timezone.utc).isoformat(), version,
         category, title, summary, detail, int(is_major)))
    return release_id


def list_release_notes(conn: sqlite3.Connection, *, limit: int = 5,
                       category: Optional[str] = None) -> list:
    if category:
        return conn.execute(
            "SELECT * FROM release_notes WHERE category=? "
            "ORDER BY released_at DESC LIMIT ?", (category, limit)).fetchall()
    return conn.execute(
        "SELECT * FROM release_notes ORDER BY released_at DESC LIMIT ?",
        (limit,)).fetchall()
