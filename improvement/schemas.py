# -*- coding: utf-8 -*-
"""데이터 스키마 — 케이스·판단·모델 상태의 고정 어휘."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Optional


class CaseStatus(str, Enum):
    OPEN = "open"
    SUCCESS = "success"
    FAILURE = "failure"
    UNRESOLVED = "unresolved"
    DATA_ERROR = "data_error"


class Decision(str, Enum):
    BUY = "buy"
    CONDITIONAL_BUY = "conditional_buy"
    HOLD = "hold"
    PARTIAL_SELL = "partial_sell"
    SELL = "sell"
    AVOID = "avoid"
    UNAVAILABLE = "unavailable"


class ModelStatus(str, Enum):
    OPERATING = "operating"
    CANDIDATE = "candidate"
    BLIND_TEST = "blind_test"
    REJECTED = "rejected"
    ARCHIVED = "archived"


#: 추천 4분류(한국어 어휘) → Decision 매핑 — premarket 연동용
RECO_CLASS_TO_DECISION = {
    '오늘 사도 되는 종목': Decision.BUY,
    '조건부로 사도 되는 종목': Decision.CONDITIONAL_BUY,
    '오늘은 기다려야 하는 종목': Decision.HOLD,
    '오늘은 사면 안 되는 종목': Decision.AVOID,
}


@dataclass(frozen=True)
class PredictionCase:
    case_id: str
    ticker: str
    asset_type: str
    signal_date: date
    created_at: datetime
    model_version: str
    rulebook_version: str
    decision: Decision
    total_score: float
    confidence_score: float
    reference_price: float
    entry_price: Optional[float]
    target_price: Optional[float]
    stop_price: Optional[float]
    holding_days: int
    market_regime: str
    strategy_type: str
    data_hash: str
    status: CaseStatus = CaseStatus.OPEN
    exit_price: Optional[float] = None
    realized_return: Optional[float] = None
    max_drawdown: Optional[float] = None
    result_reason: Optional[str] = None
