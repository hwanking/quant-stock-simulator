# -*- coding: utf-8 -*-
"""연구 후보 등록부 — 논문·특허·공개 전략은 여기 등록만 하고, 채택은 검증 후."""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional


def register_research_candidate(conn: sqlite3.Connection, *, source: str,
                                core_idea: str, year: Optional[str] = None,
                                target_failure: Optional[str] = None,
                                required_data: Optional[str] = None,
                                implementable: Optional[bool] = None,
                                leakage_risk: Optional[str] = None,
                                compute_cost: Optional[str] = None,
                                stock_applicable: Optional[bool] = None,
                                etf_applicable: Optional[bool] = None) -> str:
    cid = f"RC-{uuid.uuid4().hex[:12]}"
    conn.execute(
        """
        INSERT INTO research_candidates (
            candidate_id, registered_at, source, year, core_idea,
            target_failure, required_data, implementable, leakage_risk,
            compute_cost, stock_applicable, etf_applicable, adopted
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?, NULL)
        """,
        (cid, datetime.now(timezone.utc).isoformat(), source, year, core_idea,
         target_failure, required_data,
         None if implementable is None else int(implementable),
         leakage_risk, compute_cost,
         None if stock_applicable is None else int(stock_applicable),
         None if etf_applicable is None else int(etf_applicable)))
    return cid


def record_decision(conn: sqlite3.Connection, candidate_id: str, *,
                    adopted: bool, validation_result: str,
                    decision_reason: str) -> None:
    conn.execute(
        "UPDATE research_candidates SET adopted=?, validation_result=?, "
        "decision_reason=? WHERE candidate_id=?",
        (int(adopted), validation_result, decision_reason, candidate_id))


def list_candidates(conn: sqlite3.Connection, limit: int = 50) -> list:
    return conn.execute(
        "SELECT * FROM research_candidates ORDER BY registered_at DESC "
        "LIMIT ?", (limit,)).fetchall()
