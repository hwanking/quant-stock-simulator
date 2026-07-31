# 점수 체계 규칙서

**종합 점수는 하나다.** `final_action_score` — 규칙집(`analysis_rulebook_ko.txt`) 산식으로
`compute_four_separated_scores` 가 계산하며, 스캐너·TOP3·게이트·최종 결론 배너가
전부 이 값을 쓴다. 다른 어떤 점수도 이것과 재합산되지 않는다.

## 산식

```
가중합 = 기본매력×35% + 매매적합×45% + 리스크×20%     (RULES_TOP_WEIGHTS)
최종   = min(가중합, 캡1, 캡2, …)                      ← 선언 순서 무관
```

캡(상한)의 예 — 전부 `cap_reasons` 로 사유가 남는다:
전략품질 구간별(95/85/72/60) · 순기대수익<2% → 59 · 적정가 신뢰도 미달 → 64 ·
진입 위치(추격매수 위험) → 49 · 월봉 이격 과열 → 67 · 무결성 충돌 → 49.

## 점수 목록과 역할

| 점수 | 역할 | 종합 점수와의 관계 |
|---|---|---|
| final_action_score | **정본 종합 점수** | 그 자체 |
| stock_quality / trading_timing / risk_safety | 종합 점수의 3구성 | 가중합 입력 |
| analysis_confidence | 신뢰도 게이트 | 캡 조건 |
| strategy_quality (OOS) | 표본외 검증 게이트 | 캡 조건 |
| 탭 6개 관점 점수 | 근거 표시 전용 | **합산 안 함** |
| market_attention_score | 후보 발굴 전용 | TOP3 동점 보조 ≤5점 |
| holder_action_score | 보유자 개인화 전용 | 시장 판정과 분리 |

## 판정 문구

`final_action_title` 하나에서 파생 (`build_final_verdict` 의 TITLE_MAP).
거부 조건(표본 미달·순기대수익≤0·추격 구간·신뢰도<50·무결성 충돌)이 있으면
점수와 무관하게 매수 결론(BUY/ACCUMULATE)으로 나갈 수 없다.

## 확률 표기 규칙 (§11)

- 유효표본 <5: INSUFFICIENT — 아무 확률도 표시하지 않음
- 5~9: 관찰값만 (확률 환산 금지)
- ≥10: 베이지안 사후확률 + Wilson 95% 구간 표시
- 선도달 확률은 목표/손절/미도달 3범주, 같은 분모, 합 100%
