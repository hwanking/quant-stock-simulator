# -*- coding: utf-8 -*-
"""
결과 판정 — 실제 OHLC 경로로 성공·실패·미도달을 가른다.

⚠️ 정의 주의: 같은 봉에서 목표·손절이 모두 닿으면 **unresolved** 로 남긴다
(분봉이 없어 선도달 순서를 확정할 수 없다 — 임의로 성공 처리 금지).
기존 리플레이 KPI(prediction_log — 같은 봉이면 손절 우선의 보수 정의)와
다르다. KPI 정의 불변 원칙에 따라 두 계층은 섞지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass(frozen=True)
class CaseResolution:
    status: str
    exit_price: Optional[float]
    realized_return: Optional[float]
    max_drawdown: Optional[float]
    reason: str


def calculate_max_drawdown(lows: pd.Series, entry_price: float) -> float:
    if lows.empty:
        raise ValueError("가격 시계열이 비어 있습니다.")
    return float((lows.astype(float) / float(entry_price) - 1.0).min())


def resolve_long_case(*, price_data: pd.DataFrame, entry_price: float,
                      target_price: float, stop_price: float) -> CaseResolution:
    required = {"high", "low", "close"}
    if not required.issubset(price_data.columns):
        raise ValueError(f"필수 컬럼 누락: {sorted(required - set(price_data.columns))}")
    if price_data.empty:
        return CaseResolution("data_error", None, None, None,
                              "결과 가격 데이터가 없습니다.")
    for _, row in price_data.iterrows():
        high, low = float(row["high"]), float(row["low"])
        t_hit, s_hit = high >= target_price, low <= stop_price
        mdd = calculate_max_drawdown(price_data["low"], entry_price)
        if t_hit and s_hit:
            return CaseResolution(
                "unresolved", None, None, mdd,
                "같은 거래일에 목표가·손절가 모두 도달 — 분봉이 없어 선도달 "
                "순서를 확정할 수 없어 성공으로 세지 않습니다.")
        if s_hit:
            return CaseResolution("failure", stop_price,
                                  stop_price / entry_price - 1.0, mdd,
                                  "손절가가 목표가보다 먼저 도달했습니다.")
        if t_hit:
            return CaseResolution("success", target_price,
                                  target_price / entry_price - 1.0, mdd,
                                  "목표가가 손절가보다 먼저 도달했습니다.")
    final_close = float(price_data.iloc[-1]["close"])
    return CaseResolution(
        "unresolved", final_close, final_close / entry_price - 1.0,
        calculate_max_drawdown(price_data["low"], entry_price),
        "보유기간 내 목표가·손절가 모두 미도달했습니다.")
