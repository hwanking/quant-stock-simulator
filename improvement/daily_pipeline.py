# -*- coding: utf-8 -*-
"""일일 파이프라인 골격 — 단계별 실패를 격리하고 실행 로그를 남긴다."""
from __future__ import annotations

import logging
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    run_id: str
    added_cases: int
    resolved_cases: int
    error_count: int
    status: str


def run_daily_pipeline(conn: sqlite3.Connection, *,
                       create_new_cases: Callable[[], int],
                       resolve_open_cases: Callable[[], int],
                       refresh_metrics: Callable[[], None],
                       detect_issues: Callable[[], None]) -> PipelineResult:
    run_id = f"DAILY-{uuid.uuid4().hex[:12]}"
    conn.execute(
        "INSERT INTO pipeline_runs (run_id, pipeline_type, started_at, status)"
        " VALUES (?, 'daily', ?, 'running')",
        (run_id, datetime.now(timezone.utc).isoformat()))
    conn.commit()

    added = resolved = errors = 0
    try:
        added = int(create_new_cases())
    except Exception:
        errors += 1
        logger.exception("신규 케이스 저장 실패")
    try:
        resolved = int(resolve_open_cases())
    except Exception:
        errors += 1
        logger.exception("미결 케이스 평가 실패")
    try:
        refresh_metrics()
    except Exception:
        errors += 1
        logger.exception("모델 성과 갱신 실패")
    try:
        detect_issues()
    except Exception:
        errors += 1
        logger.exception("주요 이슈 감지 실패")

    status = 'success' if errors == 0 else 'partial_success'
    conn.execute(
        "UPDATE pipeline_runs SET finished_at=?, status=?, added_cases=?, "
        "resolved_cases=?, error_count=? WHERE run_id=?",
        (datetime.now(timezone.utc).isoformat(), status, added, resolved,
         errors, run_id))
    conn.commit()
    return PipelineResult(run_id, added, resolved, errors, status)


def last_run(conn: sqlite3.Connection):
    return conn.execute(
        "SELECT * FROM pipeline_runs ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
