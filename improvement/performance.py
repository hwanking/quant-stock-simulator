# -*- coding: utf-8 -*-
"""
결과 판정 — 실제 OHLC 경로로 성공·실패·미도달을 가른다.

⚠️ 라운드 232 (2026-09-07) — **채점기는 하나다.** 종전 이 모듈은 같은 봉에서 목표·손절이
모두 닿으면 'unresolved' 로 두고("KPI 정의 불변 원칙에 따라 두 계층은 섞지 않는다"),
일일 루틴은 진입을 권장매수가(rec_buy)로 잡아 리플레이 원장(prediction_log — 진입 =
기록 시점 가격 · 같은 봉이면 손절 먼저)과 **다른 규칙**으로 같은 추천을 세고 있었다.
화면은 둘을 같은 페이지에 냈다. 실측(51건 · docs/RESULT_R232_ONE_GRADER.md): 39건이
권장매수가 진입이고 그중 18건은 그 가격에 닿은 적이 없다 — 중앙 수익 +10.4% vs 리포트
가격 기준 +6.4%. 전방 추적은 원장과 **견주기 위해** 있으므로(R216 연습 vs 실전) 규칙이
같아야 한다. 이제 선도달 규칙은 `prediction_log.first_touch` 한 곳이고, 여기는 그것을
부른다: 같은 봉이면 손절 먼저(보수 · 성공으로 세지 않는다) · MDD 는 청산 봉까지.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from prediction_log import first_touch

STATUS_OF = {'TARGET': 'success', 'STOP': 'failure', 'OPEN': 'unresolved'}
REASON = {
    'success': "목표가가 손절가보다 먼저 도달했습니다.",
    'failure': "손절가가 목표가보다 먼저 도달했습니다.",
    'unresolved': "보유기간 내 목표가·손절가 모두 미도달했습니다.",
}
REASON_SAME_BAR = ("같은 거래일에 목표가·손절가 모두 도달 — 분봉이 없어 순서를 알 수 "
                   "없으므로 원장과 같은 규칙으로 손절 먼저로 봅니다 (성공으로 세지 않습니다).")


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


def resolution_from_grade(grade, *, target_price: float, stop_price: float) -> CaseResolution:
    """
    prediction_log.grade_prediction 결과 → 케이스 확정. 일일 루틴과 R232 재환산 스크립트가
    같은 것을 부른다. 수익률·MDD 는 grade 가 잰 대로(진입 = 기록 시점 가격 · 청산 봉까지).
    """
    status = STATUS_OF[grade['outcome']]
    if status == 'success':
        exit_price = float(target_price)
    elif status == 'failure':
        exit_price = float(stop_price)
    else:
        exit_price = float(grade['last_close'])
    reason = REASON_SAME_BAR if grade.get('same_bar') else REASON[status]
    return CaseResolution(status, exit_price,
                          float(grade['return_pct']) / 100.0,
                          float(grade['mae_pct']) / 100.0, reason)


def resolve_long_case(*, price_data: pd.DataFrame, entry_price: float,
                      target_price: float, stop_price: float) -> CaseResolution:
    """날짜 없는 OHLC 창으로 판정 — 규칙은 `first_touch` 그대로 (검사·API 용)."""
    required = {"high", "low", "close"}
    if not required.issubset(price_data.columns):
        raise ValueError(f"필수 컬럼 누락: {sorted(required - set(price_data.columns))}")
    if price_data.empty:
        return CaseResolution("data_error", None, None, None,
                              "결과 가격 데이터가 없습니다.")
    bars = [(float(h), float(l), float(c)) for h, l, c in
            zip(price_data["high"], price_data["low"], price_data["close"])]
    outcome, touched_at, same_bar = first_touch(bars, target_price, stop_price)
    path = bars[:touched_at] if touched_at else bars
    mdd = min(l for _h, l, _c in path) / float(entry_price) - 1.0
    status = STATUS_OF[outcome]
    if status == 'success':
        exit_price = float(target_price)
    elif status == 'failure':
        exit_price = float(stop_price)
    else:
        exit_price = bars[-1][2]
    reason = REASON_SAME_BAR if same_bar else REASON[status]
    return CaseResolution(status, exit_price, exit_price / float(entry_price) - 1.0,
                          mdd, reason)
