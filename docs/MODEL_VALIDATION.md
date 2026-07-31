# 모델 검증 문서

## 자기유사 예측

- 최근 H봉 종가 Z-score 정규화 (`_zscored_windows`)
- Pearson 상관 1차 통과(rho ≥ 사용자 설정, 기본 0.80) 후 H≤40 은 DTW 결합:
  `combined = rho×0.7 + dtw×0.3` — 가중치는 규칙집 `RULES_SIMILARITY` 단일 출처
- 매칭 간 최소 H영업일 간격 (중복 이벤트 제거)
- 후보 구간의 미래 H봉이 기준시점을 침범하지 않음 (`range(len-2H)`)
- 목표 +8% / 손절 -6% (규칙집 `RULES_PATH_THRESHOLDS`) 선도달 3범주 합 100%
- Beta-Binomial 사후평균 (사전 α=5.5, β=4.5) + Wilson 95% 구간
- ESS: 첨도 기반 감쇠 — 표본 수를 부풀리지 않음

## 표본외(OOS) 검증

- Purged Walk-Forward: 학습 최소 400봉, OOS 30%, embargo = horizon
- 후보 윈도우 미래구간이 `t - H - embargo` 이전에 끝나야 채택 (누출 차단)
- 산출: Brier·MAE·방향적중·Sharpe·Sortino·MDD·PF·순수익·회전율 → 전략품질 9요소 가중
- **표본내와 표본외 지표는 별개다.** 화면의 "표본내 Sharpe" 와 "OOS Sharpe" 는
  다른 표본·다른 집계이며 나란히 표기해 혼동을 방지한다.

## 밸류에이션

- 기업유형 확률(업종 70% + 재무 30%) → 모델 가중 라우팅
- 입력 없는 모델은 유효성 미통과로 제외 (rNPV: 파이프라인 데이터 없으면 항상 제외)
- 중앙값 대비 100% 이탈 자동 제외, 50% 이탈 가중치 반감
- 범위는 신뢰도 가중 분위수 (핵심 25~75 / 확장 10~90), 중심값은 확장범위로 clip
- ETF·ETN: 펀더멘털 모델 전체 미적용 — 적정가 미산출이 정답

## 검증 방법

- 회귀 스위트 41개 섹션 477건 (`test_pipeline_fixes.py`)
- 단일 종목 감사 (`scripts/audit_single_ticker.py`)
- 배치 감사 (`scripts/audit_all_tickers.py`) — 유형별 12종목 통과
- 시장 카드 검증 (`scripts/verify_market_snapshot.py`) — 소수점 대조
