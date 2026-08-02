# -*- coding: utf-8 -*-
"""
운영 모델 승격 게이트 — 자동 교체 방지.

후보가 적중률만 높고 신호가 거의 없거나(실용성 부족), 낙폭이 커지면 기각한다.
전부 통과해야 승격 '후보 표시'까지만 — 최종 승격 기록은 사람이 남긴다.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PromotionMetrics:
    blind_count: int
    blind_accuracy: float
    expected_return: float
    profit_factor: float
    max_drawdown: float
    signal_rate: float


@dataclass(frozen=True)
class PromotionDecision:
    approved: bool
    reason: str


def evaluate_promotion(*, current: PromotionMetrics,
                       candidate: PromotionMetrics,
                       minimum_blind_count: int = 200,
                       minimum_signal_rate: float = 0.02,
                       maximum_drawdown_deterioration: float = 0.02
                       ) -> PromotionDecision:
    if candidate.blind_count < minimum_blind_count:
        return PromotionDecision(False, (
            f"블라인드 표본 부족: {candidate.blind_count}건 "
            f"< 최소 {minimum_blind_count}건"))
    if candidate.blind_accuracy <= current.blind_accuracy:
        return PromotionDecision(False,
                                 "기존 운영 모델보다 블라인드 적중률이 개선되지 않았습니다.")
    if candidate.expected_return <= current.expected_return:
        return PromotionDecision(False,
                                 "거래비용 차감 기대수익이 개선되지 않았습니다.")
    if candidate.profit_factor <= current.profit_factor:
        return PromotionDecision(False, "Profit Factor가 개선되지 않았습니다.")
    if candidate.max_drawdown < current.max_drawdown - maximum_drawdown_deterioration:
        return PromotionDecision(False, "최대낙폭이 허용 범위보다 악화되었습니다.")
    if candidate.signal_rate < minimum_signal_rate:
        return PromotionDecision(False,
                                 "신호 발생률이 지나치게 낮아 실용성이 부족합니다.")
    return PromotionDecision(True, (
        "블라인드 표본·적중률·기대수익·Profit Factor·MDD·신호율 조건을 "
        "모두 충족했습니다."))
