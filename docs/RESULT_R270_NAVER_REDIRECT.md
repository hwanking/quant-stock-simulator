# 결과 R270 — 네이버가 옛 종목 페이지를 새 사이트로 넘겨 실시세 파서가 모든 종목을 '페이지 없음'으로 읽었다 · JSON 경로 (2026-09-10)

## 1. 무엇이 일어났나 (실측 · 2026-09-10 오후)

| 시각 | 사실 |
|---|---|
| 오전 | 회귀 §17(실시세 파이프라인)이 통과했다 — 옛 종목 페이지가 정상으로 왔다 |
| 오후 | 회귀 §17 이 `DataUnavailableError: 005930.KS: 네이버에 종목 페이지가 없습니다(메인으로 넘어감)` 로 죽었다 |
| 확인 | `finance.naver.com/item/main.naver?code=005930` → **302 → `stock.naver.com/domestic/stock/005930/price`** (JS 앱 · `no_today`·`wrap_company` 없음). 세 종목(005930·000660·035420) · UA 둘 다 같다 |
| 엔진 경로 | 차가운 프로세스 `fetch_and_update_naver_realtime` → `page_status=item_page_missing` · `base_price 0.0` · 이름에 `Npay 증권</title>…` 조각 — **세 종목 전부** |
| 여전히 되는 것 | 일봉 XML(`fchart.stock.naver.com/sise.nhn`) · 일별 시세 표(`sise_day.naver`) · 다음금융 시세 API |

즉 이 시각부터 **앱의 모든 종목 분석이 "시세 미수신"으로 막히고**, 클라우드 축적(리플레이도
`generate_synthetic_bitemporal_data` 가 실시세 삼중 확인을 먼저 부른다)이 케이스마다 실패한다.
라운드 204 가 *"종목 페이지 없음은 상장폐지·합병의 구조적 사유"* 라 적어 둔 그 문장이 오늘은
거짓이 됐다 — 페이지가 없는 게 아니라 **주소가 옮겨졌다.** 사유를 가른 덕에 로그가 그것을 바로
말했다(라운드 165 · 사유를 섞지 않는다).

## 2. 고침 — 새 사이트가 쓰는 JSON 으로 같은 칸을 채운다

새 사이트의 API(`m.stock.naver.com/api`)가 옛 페이지의 칸을 전부 준다(읽기 전용 GET · 계정·쿠키
없음 · §9):

| 칸 | 출처 |
|---|---|
| 이름 · 현재가 · 전일비 · 등락률 · 시장(KS/KQ) · ETF 여부 | `stock/{code}/basic` (`stockName` · `closePrice` · `compareToPreviousClosePrice` · `fluctuationsRatio` · `stockExchangeType.code` · `stockEndType`) |
| 시가·고가·저가·거래량 · PER·EPS·PBR·BPS | `stock/{code}/integration` → `totalInfos` |
| ROE · 부채비율 | `stock/{code}/finance/annual` → `rowList` — **가장 최근 실적**만(기간이 오늘 이후인 추정치는 뺀다) |
| 업종 이름 | `integration.industryCode` → `stocks/industry/{no}` → `groupInfo.name` (옛 KRX 업종 라벨과 같은 문자열 · 예: 반도체와반도체장비) |

- `fetch_and_update_naver_realtime` 은 **옛 표식이 없을 때만** 이 길로 간다 — 옛 페이지가 되살아나면
  옛 파서 그대로다(두 길이 같은 `info` 모양을 낸다 · `page_status='ok_mobile_api'` 로 어느 길인지 남긴다).
- 빈 칸의 뜻은 옛 파서와 같다(§3): 시고저 못 받으면 현재가 · 거래량 0 · EPS/BPS 는 PER/PBR 항등식
  또는 None · 펀드는 EPS·BPS·PER·PBR 0 · ROE·부채 None · 업종은 못 받으면 **종전 값**(업종은 종목의
  성질 · R218) 없으면 None. 값을 지어내지 않는다.
- 순수 함수(`info_from_mobile_api`)로 빼 회귀가 네트워크 없이 심어서 잰다(§284 · 9건).

차가운 프로세스 실측(고친 뒤): 005930 → 269,000 · 삼성전자 · 반도체와반도체장비 · KOSPI /
035420 → 208,000 · NAVER · 양방향미디어와서비스 / 247540 → 118,700 · 에코프로비엠 · 전기제품 · **KOSDAQ**.

## 2b. 유니버스도 같은 날 넘어갔다

옛 시가총액 페이지(`sise/sise_market_sum.naver`)도 `stock.naver.com/market/stock/kr/stocklist/
capitalization` 으로 302 — 코드 0개라 전 종목 수집이 통째로 실패했고, 폴백 유니버스는 부채비율
`None` 에 `TypeError` 로 죽었다(`meta.get("debt", 0) < 150` · 키가 None 으로 있으면 기본값이 안 쓰인다).
고침: 첫 페이지부터 행이 없으면 `stocks/marketValue/{KOSPI|KOSDAQ}` JSON 목록으로 같은 칸을 채운다 —
**종목만**(`stockEndType == 'stock'` · 옛 페이지도 종목만 실었다 · R164 경계) · 시총은 억원 그대로 ·
PER·ROE 는 목록에 없어 None. 폴백은 부채 None 이면 'Unknown'. 차가운 프로세스 실측: KOSPI 945 ·
KOSDAQ 1,823 종목 → 제외 규칙 뒤 **2,443**(KOSPI 788 · KOSDAQ 1,655) · 시총 내림차순 그대로.
실시세 교차검증(`fetch_naver_price_live`)도 표식이 없으면 같은 JSON 의 현재가를 쓴다.

## 2c. 검색 · 업종 목록 · 수급도 — 같은 날 다섯 경로가 한꺼번에 넘어갔다

회귀가 하나씩 드러냈다(§29 정확 검색 · 업종 상대강도 5건 · 수급 2건 — 10건 실패). 셋 다 옛
페이지가 새 사이트로 302 된다. 같은 방식으로 옮겼고 옛 파서는 남겼다:

| 경로 | 옛 페이지 | 새 JSON | 순수 함수(§284 심기) |
|---|---|---|---|
| 종목명 검색 | `search/search.naver` | `ac.stock.naver.com/ac?q=…&target=stock` — 국내 종목만 · 시장(KOSPI/KOSDAQ)을 **읽어** 붙인다(옛 길은 .KS 를 박았다) | `search_hits_from_ac` |
| 업종 목록·구성 | `sise_group.naver` · `sise_group_detail` | `stocks/industry`(79 업종 · 번호·이름·등락률) · `stocks/industry/{no}` — `pageSize` 상한이 있어(200 → 400) `totalCount` 까지 넘긴다 | `sector_groups_from_api` |
| 외국인·기관 수급 | `item/frgn.naver` | `stock/{code}/trend` — bizdate · organPureBuyQuant · foreignerPureBuyQuant(부호 있음) | `flow_rows_from_trend` (`scripts/flow_recorder` 도 같은 함수를 부른다 · 베끼지 않는다) |

차가운 프로세스 실측: 검색 셋 전부 복구 · 업종 79개 · 종목→업종 4,414 · 반도체와반도체장비 RS 50.6 ·
수급 20일(기관 5일 +15,471,628 · 외국인 5일 −2,190,216).

## 3. 남은 것

- **돌고 있는 앱은 옛 모듈을 들고 있다** — 재시작해야 이 길을 탄다(`running-server-keeps-old-modules`).
- 종목명 검색(`finance.naver.com/search/search.naver`)·배당(`fetch_dividend_info`)·뉴스 페이지도 같은
  이전을 겪을 수 있다 — 이번엔 실시세 삼중 확인만 고쳤다. 검색이 막히면 다음금융 검색 폴백이 이미 있다.
- 옛 페이지 파서(`sector_from_html` · 시장 배지)는 남겨 둔다 — 되살아날 수 있고, 회귀 §237·§159 가 그
  판별을 심어서 잰다.
- 오늘 17:00 KST 클라우드 실행이 이 커밋 **전**에 돌았다면 케이스마다 실패했을 것이다 — 실행 기록
  검사(R263)와 신선도 검사가 그것을 붉게 낸다. 다음 실행은 이 커밋을 탄다.

값·판정·게이트·산식 불변 — 바뀐 것은 **어디서 읽느냐**다. 회귀 §284.
