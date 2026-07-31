# 데이터 계보 (Data Lineage)

각 화면 값이 어디서 와서 어떻게 변환되는지. **여기 없는 출처는 연결되지 않은 것이다.**

## 파이프라인 흐름

```
원천 수집(네이버·다음·DART목록·야후지수)
→ 파싱(bitemporal_engine)
→ 봉 정제(거래정지 0원 봉 제외 · 고저 정의 복원)
→ 거래일/기준일 결정(KrxCalendar, resolve_analysis_date)
→ 기술지표(quant_indicators.compute_technical_indicators)
→ 밸류에이션(evaluate_valuation_metric)
→ 자기유사·OOS 백테스트(run_self_similarity_backtest / run_blind_oos_backtest)
→ 점수·게이트(compute_four_separated_scores, 캡은 min() 결합)
→ 최종 판정(build_final_verdict — 단일 정본)
→ 화면(web_app) / 캐시(QuantSnapshot: 종목+기준일+rho+버전+TTL 15분)
```

## 값별 계보

| 화면 값 | 원천 | 경로 | 기준일 | 결측 시 |
|---|---|---|---|---|
| 현재가 | 네이버 종목페이지(기준) + 다음 API(교차) | `get_realtime_stock_price_triple_check` | 실시간/최근 확정 | 분석 제외 |
| 일봉 OHLCV | 네이버 fchart XML (3,000봉) | `load_bitemporal_data` → 정제 | 봉 날짜 | `DataUnavailableError` — 합성 금지 |
| KOSPI/KOSDAQ 카드 | 네이버 모바일 지수 API(`fluctuationsRatio`) | `get_market_indices` | 당일 | "N/A" |
| 환율/S&P500 카드 | 야후 chart API(`chartPreviousClose` 대비) | 〃 | 당일 | 직전 폴백 표기 |
| PER·PBR·EPS·BPS·ROE·부채비율 | 네이버 종목페이지 게시값(FnGuide 제공분) + 다음 보조 | `fetch_and_update_naver_realtime` | 게시 시점 스냅샷 | None — 리터럴 대체 금지 |
| DPS·배당수익률·배당락일 | 네이버 게시 DPS ÷ 현재가, 배당락일은 관례 **추정** | `fetch_dividend_info` (단일 소유자) | 수집 시점 | 사유 반환 |
| 업종·업종등락률 | 네이버 업종 페이지(79업종) | `market_attention.fetch_sector_map` | 당일, 1h 캐시 | 항목 미산출 |
| 외국인·기관 순매매 | 네이버 종목 frgn 페이지 (일자별) | `fetch_investor_flow` | 봉 날짜 | None |
| 당일 공시 | DART 공개 목록 (당일 최근 ~300건) | `fetch_disclosures` | 당일 | 0점 |
| 적정가 | 위 재무값 → 다중모델 신뢰도 가중 | `evaluate_valuation_metric` | 분석 기준일 | ETF/신뢰도 미달 시 미산출 |
| 뉴스 카드 | **가격·거래량·게시지표의 관찰만** | `get_timeframe_news_analysis` | 당일 | — (기사·IR 미연동 명시) |

## 명시적 미연동 (화면 문구와 일치해야 함)

KRX/KIND 직접 API · DART OpenAPI(키) · FnGuide/Investing 직접 조회 ·
뉴스 기사 · 리서치 컨센서스 · IR 원문 · 재무 보고서 기준일 · 섹터/규모/모멘텀 팩터 ·
투자자별 프로그램 매매 · 해외주식 · 암호화폐
