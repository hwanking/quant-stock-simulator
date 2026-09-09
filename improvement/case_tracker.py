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


EXCLUDED_STATUSES = ('dup_version', 'void_fixture')


def is_non_trading_date(iso_day) -> bool:
    """휴장일(주말 · KRX 휴일)인가 — **한 곳** (라운드 252).

    실측 2026-09-09: 확정 169건 · 고유 기준일 33개 중 9개가 토·일이었고 일요일 픽은
    토요일 픽과 5/5 같았다. 개장 전 리포트가 만들어진 날이 기준일로 들어와서다.
    휴일 목록은 저장소가 이미 가진 것을 쓴다(손으로 안 적는다) — 못 읽으면 주말만 본다.
    """
    from datetime import date as _date
    try:
        y, m, d = (int(x) for x in str(iso_day)[:10].split('-'))
        if _date(y, m, d).weekday() >= 5:
            return True
    except (TypeError, ValueError):
        return False
    try:
        from bitemporal_engine import KRX_HOLIDAYS
        return str(iso_day)[:10] in KRX_HOLIDAYS
    except Exception:                                          # noqa: BLE001
        return False


def tally(conn: sqlite3.Connection) -> dict:
    """
    확정·대기의 갈래 — **한 곳** (라운드 232). 화면의 두 자리(개장 전 절의 '사후 검증' ·
    모델 성적의 '실전 추천 추적' 줄)가 이것만 읽는다. 버전 복사본·시험 픽스처(R222)는
    행으로 남기되 세지 않고 `excluded` 에 따로 센다(§3). 분모가 0 이면 비율은 None.
    """
    counts = dict(conn.execute(
        "SELECT status, COUNT(*) FROM prediction_cases GROUP BY status").fetchall())
    ok = int(counts.get('success') or 0)
    bad = int(counts.get('failure') or 0)
    un = int(counts.get('unresolved') or 0)
    excluded = sum(int(counts.get(s) or 0) for s in EXCLUDED_STATUSES)
    # 라운드 252 — 휴장일 기준일은 **날짜 표본**을 부풀린다(토·일 픽이 같은 추천의
    #   복사본). 행은 그대로 두고, 그 수와 **거래일 고유 기준일 수**를 같이 낸다 —
    #   날짜가 표본인 판정(뉴스 축 하한 30 · R84)은 `trading_dates` 를 읽는다.
    _days = conn.execute(
        "SELECT signal_date, status FROM prediction_cases").fetchall()
    non_trading = sum(1 for d, st in _days
                      if st not in EXCLUDED_STATUSES and is_non_trading_date(d))
    trading_dates = len({str(d)[:10] for d, st in _days
                         if st in ('success', 'failure', 'unresolved')
                         and not is_non_trading_date(d)})
    return {
        'success': ok, 'failure': bad, 'unresolved': un,
        'open': int(counts.get('open') or 0),
        'data_error': int(counts.get('data_error') or 0),
        'excluded': excluded,
        'non_trading': non_trading,
        'trading_dates': trading_dates,
        'frozen': sum(int(v) for k, v in counts.items() if k not in EXCLUDED_STATUSES),
        'resolved': ok + bad + un,
        'decided': ok + bad,
        'success_pct': (ok / (ok + bad) * 100.0) if (ok + bad) else None,
    }
