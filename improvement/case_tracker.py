# -*- coding: utf-8 -*-
"""케이스 동결 저장 — 중복 방지(case_id 해시)·입력 데이터 해시 동결."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date, datetime, timezone
from typing import Any, Mapping, Optional

from improvement.schemas import CaseStatus, Decision, PredictionCase


def make_data_hash(payload: Mapping[str, Any]) -> str:
    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                            default=str).encode('utf-8')
    return hashlib.sha256(normalized).hexdigest()


def make_case_id(ticker: str, signal_date: date, model_version: str,
                 decision: Decision) -> str:
    raw = (f"{ticker}|{signal_date.isoformat()}|"
           f"{model_version}|{decision.value}")
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]


def create_prediction_case(*, ticker: str, asset_type: str, signal_date: date,
                           model_version: str, rulebook_version: str,
                           decision: Decision, total_score: float,
                           confidence_score: float, reference_price: float,
                           entry_price: Optional[float],
                           target_price: Optional[float],
                           stop_price: Optional[float], holding_days: int,
                           market_regime: str, strategy_type: str,
                           source_payload: Mapping[str, Any]) -> PredictionCase:
    if reference_price <= 0:
        raise ValueError("reference_price는 0보다 커야 합니다.")
    if holding_days <= 0:
        raise ValueError("holding_days는 1 이상이어야 합니다.")
    for nm, v in (('entry_price', entry_price), ('target_price', target_price),
                  ('stop_price', stop_price)):
        if v is not None and v <= 0:
            raise ValueError(f"{nm}는 0보다 커야 합니다.")
    return PredictionCase(
        case_id=make_case_id(ticker, signal_date, model_version, decision),
        ticker=ticker, asset_type=asset_type, signal_date=signal_date,
        created_at=datetime.now(timezone.utc),
        model_version=model_version, rulebook_version=rulebook_version,
        decision=decision, total_score=float(total_score),
        confidence_score=float(confidence_score),
        reference_price=float(reference_price), entry_price=entry_price,
        target_price=target_price, stop_price=stop_price,
        holding_days=holding_days, market_regime=market_regime,
        strategy_type=strategy_type,
        data_hash=make_data_hash(source_payload))


def save_prediction_case(conn: sqlite3.Connection,
                         case: PredictionCase) -> bool:
    """INSERT OR IGNORE — 같은 종목·날짜·모델·판단이면 조용히 무시 (중복 방지)."""
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO prediction_cases (
            case_id, ticker, asset_type, signal_date, created_at,
            model_version, rulebook_version, decision,
            total_score, confidence_score,
            reference_price, entry_price, target_price, stop_price,
            holding_days, market_regime, strategy_type, data_hash, status
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (case.case_id, case.ticker, case.asset_type,
         case.signal_date.isoformat(), case.created_at.isoformat(),
         case.model_version, case.rulebook_version, case.decision.value,
         case.total_score, case.confidence_score, case.reference_price,
         case.entry_price, case.target_price, case.stop_price,
         case.holding_days, case.market_regime, case.strategy_type,
         case.data_hash, case.status.value))
    return cur.rowcount == 1


def resolve_case(conn: sqlite3.Connection, case_id: str, *, status: str,
                 exit_price, realized_return, max_drawdown, reason: str) -> None:
    """결과 확정 — open 상태만 갱신한다 (확정된 케이스는 덮어쓰지 않는다)."""
    conn.execute(
        """
        UPDATE prediction_cases
        SET status=?, exit_price=?, realized_return=?, max_drawdown=?,
            result_reason=?, resolved_at=?
        WHERE case_id=? AND status='open'
        """,
        (status, exit_price, realized_return, max_drawdown, reason,
         datetime.now(timezone.utc).isoformat(), case_id))


def open_cases(conn: sqlite3.Connection) -> list:
    return conn.execute(
        "SELECT * FROM prediction_cases WHERE status='open' "
        "ORDER BY signal_date").fetchall()


def today_added_count(conn: sqlite3.Connection, day: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM prediction_cases WHERE signal_date=?",
        (day,)).fetchone()[0]
