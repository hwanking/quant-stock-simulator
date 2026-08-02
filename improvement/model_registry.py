# -*- coding: utf-8 -*-
"""모델 버전 레지스트리 — 운영·후보·기각을 분리 보존한다 (성과 덮어쓰기 금지)."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Optional


def register_model_version(conn: sqlite3.Connection, *, model_version: str,
                           rulebook_version: str, status: str,
                           change_summary: str,
                           parent_version: Optional[str] = None) -> None:
    conn.execute(
        """
        INSERT INTO model_versions (
            model_version, rulebook_version, status, created_at,
            parent_version, change_summary
        ) VALUES (?,?,?,?,?,?)
        ON CONFLICT(model_version) DO UPDATE SET
            rulebook_version=excluded.rulebook_version,
            status=excluded.status,
            parent_version=excluded.parent_version,
            change_summary=excluded.change_summary
        """,
        (model_version, rulebook_version, status,
         datetime.now(timezone.utc).isoformat(), parent_version,
         change_summary))


def update_model_metrics(conn: sqlite3.Connection, model_version: str,
                         **metrics) -> None:
    """성과 필드만 갱신 — 존재하는 컬럼만 허용한다."""
    allowed = {
        'training_count', 'validation_count', 'oos_count', 'blind_count',
        'validation_accuracy', 'oos_accuracy', 'blind_accuracy',
        'high_confidence_accuracy', 'expected_return', 'profit_factor',
        'max_drawdown', 'signal_rate',
    }
    cols = [k for k in metrics if k in allowed]
    if not cols:
        return
    sets = ", ".join(f"{c}=?" for c in cols)
    conn.execute(f"UPDATE model_versions SET {sets} WHERE model_version=?",
                 [metrics[c] for c in cols] + [model_version])


def get_operating_model(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM model_versions WHERE status='operating' "
        "ORDER BY created_at DESC LIMIT 1").fetchone()


def get_model_history(conn: sqlite3.Connection) -> list:
    return conn.execute(
        "SELECT * FROM model_versions ORDER BY created_at DESC").fetchall()
