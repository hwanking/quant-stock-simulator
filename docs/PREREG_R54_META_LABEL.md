# 사전등록 — 라운드 54: 메타 라벨 게이트 (측정 전 고정)

작성: 2026-08-08 (측정 전). 이 문서를 저장한 뒤에 학습을 시작한다.
기준을 측정 후에 내리지 않는다 (CLAUDE.md §2).

## 0. 왜 이 라운드인가 — R49와의 관계

R49의 결론: **순위에 정보가 없다** (TOP5 vs 미추천 −2.29%p, 단조성 없음).
따라서 개선을 얹기 전에 점수 산식 자체를 다시 봐야 한다고 못박았다.

이 라운드는 그 재검토 자체다. 새 지표를 얹는 것이 아니라, **이미 기록된
결정 시점 피처들이 성공을 조금이라도 가르는지**를 원장 전체로 묻는다.
메타 라벨(López de Prado)은 1차 신호(매수권 진입)를 그대로 두고 "이 신호를
실행할 가치가 있는가"만 2차 모델이 판단하는 구조라, 채택되면 abstain
(자신 없으면 안 산다)이 자연스럽게 따라온다. 부산물로 피처 중요도가
나오므로 R50에서 하려던 "어느 하위점수가 순위를 망가뜨리는가" 분해도
같이 끝난다.

## 1. 데이터 (고정)

- 원장 `.portfolio/virtual_graded.jsonl` 60,462건 중 **매수권(score ≥ 58)**
- 하위점수 패치 `subscore_patch*.jsonl` 를 (ticker, date)로 조인
- split 은 원장 기록을 그대로 쓴다: train / valid 만 사용.
  **blind 는 이 라운드에서 챔피언 1개가 1회만 본다** (아래 §5)
- 퍼지(purge): train 중 date ≥ 2025-06-01 행 제외 — 20봉 결과 창이
  valid 기간에 걸친다
- 오염 표본(`contaminated_blind` 681건)은 어떤 용도로도 쓰지 않는다

## 2. 피처 (결정 시점 값만 — 결과 필드 금지)

원장 행: score · rsi · bb_pos · vol20 · range_pos · demark_bull ·
demark_bear · m10_above · eff_sample · win_rate(자기유사) · net_expected ·
entry_zone(원핫) · demark_state(원핫) · regime(원핫, None 은 자체 범주) ·
market · asset_type
패치: q_stock_quality · q_trading_timing · q_risk_safety · q_opportunity ·
q_execution · q_confidence · q_strategy_quality · sector(상위 12 원핫) ·
news_risk_count · news_fresh_count · news_available

결측은 **중앙값 대치 + 결측 지시자 열**. 지어내지 않고 결측이었음을
모델에 알린다 (§3).

## 3. 라벨·비용 (고정)

- 라벨 = 원장 `success` (목표 선도달, 채점 완료분)
- 순수익 = `return_pct − 0.36` (왕복 비용: 수수료 0.03×2 + 세 0.20 + 슬리피지 0.18)
- OPEN(미판정) 행은 학습·평가 모두 제외

## 4. 모델·선택 (고정)

- 로지스틱 회귀 (C ∈ {0.1, 1}) · XGBoost (depth ∈ {3,5}, lr 0.05, 400그루,
  subsample 0.8) · LightGBM (같은 격자) — 총 6개 구성
- 학습은 train, **선택은 valid 하나로만**. 실행 문턱은 valid 에서
  "커버리지 제약 하 순EV 최대" 지점
- 복잡한 모델이라는 이유로 우선하지 않는다. 동률이면 단순한 쪽

## 5. 채택 게이트 (전부 충족해야 blind 1회 진행)

valid 선택집합이 기준선(= valid 매수권 전체) 대비:

1. 순EV(비용후) > 0
2. 적중률 리프트 ≥ +3.0%p **이고** 선택집합 Wilson 하한 > 기준선 점추정
3. 커버리지 ≥ 20% **이고** 월평균 신호 ≥ 8건 — 신호 10개로 줄여 90%
   만드는 길을 막는다
4. Profit Factor > 1.0

전부 통과한 **챔피언 1개만** blind 를 1회 본다. blind 는 이미 현행 엔진
평가에 1회 소모된 표본이므로, 이번이 **두 번째이자 마지막 사용**임을
기록한다. 이후 어떤 라운드도 이 blind 로 모델을 고르지 않는다 — 다음
검증은 오늘 이후 실전 축적분(전방 표본)으로만 한다.

blind 에서 순EV > 0 · PF > 1 · 적중률 ≥ 기준선 blind 값이면 채택.
하나라도 미달이면 **기각하고 현행 유지**. 기준을 내리지 않는다.

## 6. 채택 시 적용 방식 (미리 고정)

- 점수·가격·게이트는 그대로. 메타 모델은 **실행 여부만** 판단해
  `EXECUTE / ABSTAIN` 을 추천 카드에 붙인다
- 화면에는 Precision 과 Coverage 를 **항상 같이** 표기한다
- 적용 전 최소 2주 전방 병행 표시(paper) 후 versioning.release(axis='model')

## 7. 이 라운드에서 하지 않는 것

- 손으로 고른 가중치·문턱 (문서의 눌림목 30% 등은 후보 서술일 뿐)
- 국면별 고정 −10점 (기존 CONTEXT_CAPS=55 가 이미 측정 근거로 존재)
- 추적손절 수치 최적화 (원장 mfe/mae 가 청산 시점까지만 — 원리적 불가,
  봉 단위 경로 축적 후 별도 라운드)
- TSFM(Chronos·TimesFM·Moirai) — 환경(torch cp314)·용량 확인 후 별도
  라운드로. XGBoost 가 이번 라운드의 복잡도 상한이다
