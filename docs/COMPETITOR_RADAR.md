# 경쟁 서비스 레이더 (자동 생성 — 손으로 고치지 않는다 · 출처는 data/competitor_radar.json)

만든 날 2026-10-09 · 항목 23개 · 확인일 2026-10-09 ~ 2026-10-09

경쟁 서비스 레이더 — 화면(시스템 → 제품 벤치마크)과 docs/COMPETITOR_RADAR.md 가 읽는 단일 출처(라운드 456). 1차 근거는 공식 사이트·공식 문서뿐이고 checked_at 은 그 페이지를 실제로 읽은 날이다. 읽지 않은 축은 '미확인'으로 둔다(지어내지 않는다 · §3). 점수·등급은 없다(§2·§9) — 상태 네 가지(보유·부분·없음·미확인)와 결정 네 가지(BUILD·CONSIDER·WATCH·SKIP)만. 이 표는 아이디어 발견까지다: 가늠에 넣는 것은 필요성 → 기존 자료로 검증 → 구현의 순서이고, 경쟁사 변화가 산식·가중치·문턱을 바꾸지 않는다(scripts/update_competitor_radar.py --check 가 잠근다).

## 축 × 서비스 (상태 낱말만 · 점수 없음)

| 축 | QuantConnect | TradingView | Composer | TrendSpider | Quantus(퀀터스) | 가늠 |
|---|---|---|---|---|---|---|
| 관제 대시보드 시각화 | 미확인 | 미확인 | 부분 | 미확인 | 부분 | 보유 |
| 차트 | 미확인 | 보유 | 미확인 | 보유 | 미확인 | 부분 |
| 전략 편집기 | 미확인 | 미확인 | 보유 | 미확인 | 보유 | 없음 |
| 백테스트·실전 같은 규칙 | 보유 | 미확인 | 보유 | 보유 | 미확인 | 보유 |
| 실전 자동 실행 | 보유 | 미확인 | 미확인 | 보유 | 보유 | 보유 |
| 증권사 계좌·주문 맞추기 | 부분 | 미확인 | 미확인 | 부분 | 미확인 | 보유 |
| 위험 한도 | 미확인 | 미확인 | 부분 | 미확인 | 미확인 | 보유 |
| 주문 생애 추적 | 미확인 | 미확인 | 미확인 | 미확인 | 미확인 | 보유 |
| 알림·외부 전달 | 보유 | 보유 | 미확인 | 보유 | 미확인 | 부분 |
| 상시 실행·복구 | 보유 | 미확인 | 미확인 | 미확인 | 미확인 | 부분 |
| 사후 감사(판단·결과 보존) | 미확인 | 미확인 | 미확인 | 미확인 | 미확인 | 보유 |
| 모바일 | 미확인 | 보유 | 미확인 | 미확인 | 보유 | 부분 |

## 가늠의 자리(축마다 한 줄)

- **관제 대시보드 시각화** — 보유 · 관제실 지휘 띠 · 시스템 상태 띠 · 자산 곡선 · 자산 구성 도넛 · 위험 한도 막대 · 오늘 엔진 깔때기 (2026-10-09)
- **차트** — 부분 · 종목 차트(지표·DeMARK·경로) · 자산 곡선 — 드로잉·다중 차트 없음
- **전략 편집기** — 없음 · 의도적 — 산식은 사전등록·세 구간 측정으로만 바뀐다(§2). 사용자가 규칙을 조립하는 편집기는 만들지 않는다
- **백테스트·실전 같은 규칙** — 보유 · 같은 채점기(grade_prediction) · 원장 · 전방 기록부 · 그림자 기록 · 영수증의 원장 기준 재채점
- **실전 자동 실행** — 보유 · 한국투자 실계좌 · 워커(평일 Windows 작업) · 계획마다 승인/완전 자동 · 보호 매도
- **증권사 계좌·주문 맞추기** — 보유 · 주문 내역으로 상태 맞추기 · UNKNOWN 은 다시 안 보냄 · 밖에서 판 수량 반영 · 되돌려 받기 2단계
- **위험 한도** — 보유 · 여섯 한도(기본값 없음) · 수량 계산 · 긴급정지 · 실전 잠금 문장
- **주문 생애 추적** — 보유 · 상태기계(허락된 전이만) · 주문 생애 타임라인 화면
- **알림·외부 전달** — 부분 · 화면 안 조건 알림(중앙 판정을 따름) · 이 PC 의 Windows 알림(자동매매 체결·거절·응답 없음·보호 매도 접수·관리 끝·워커 경고 · 켜야 뜸 · 2026-10-09) — 메일·메신저·웹훅 전달 없음(계좌 자료가 밖으로 나가는 문제 · §9)
- **상시 실행·복구** — 부분 · Windows 작업 스케줄러 · 장중 10분마다 다시 부름(워커가 죽어도 10분 안에 다시 뜸 · 돌고 있으면 건너뜀 · 2026-10-09) · 잠금 · 심박 · 절전 경고 — 이 PC 에 묶여 있다(PC 가 꺼지거나 잠들면 못 돈다)
- **사후 감사(판단·결과 보존)** — 보유 · 가늠 PROOF — 판정 영수증 · 안 산 판단 채점 · 조건별 장부 · 결과 영수증(계획 vs 실제)
- **모바일** — 부분 · 휴대폰 폭 반응형(375px 실측) — 전용 앱·푸시 없음

## 차이(결정이 BUILD · CONSIDER 인 것)

- **검토(CONSIDER)** · 알림·외부 전달 · QuantConnect — 체결·오류 사건을 밖으로 보내는 길이 없다 — 이 PC 안의 Windows 알림은 있다(2026-10-09) · 체결·거절·UNKNOWN 을 메일로 보내는 것은 유용하지만 계좌 자료가 밖으로 나간다(§9) — 종목·수량 없이 사건 종류만 보내는 설계를 먼저 적어야 한다
- **검토(CONSIDER)** · 알림·외부 전달 · TradingView — 가늠 알림은 이 PC 안(화면 · Windows 알림 센터)에서만 보인다 — 웹훅 없음 · 웹훅은 사건을 밖으로 보내는 표준 — 보낼 내용에서 종목·수량·계좌를 뺀 형태로만 검토
- **검토(CONSIDER)** · 알림·외부 전달 · TrendSpider — 가늠 알림은 밖으로 안 나간다 — 이 PC 의 Windows 알림까지만(2026-10-09) · 위 QuantConnect·TradingView 와 같은 축 — 한 번에 설계
- **검토(CONSIDER)** · 상시 실행·복구 · QuantConnect — 가늠 워커는 이 PC 에 묶여 있다 — 장중에 죽으면 작업 스케줄러가 10분 안에 다시 부르지만(2026-10-09), PC 가 꺼지거나 잠들면 못 돈다 · 워커만 늘 켜진 다른 기기에 두는 구조는 외부 검토(2026-10-08·09)도 짚었다 — 비용·안전 설계가 먼저. 재시작해도 상태를 증권사에서 다시 읽는 모양은 가늠 워커가 이미 한다(내역으로 맞춤 · UNKNOWN 은 다시 안 보냄)

## 지난번 대비 바뀐 것

- 없음(첫 판이거나 바뀐 상태가 없다)

## 항목 전부 (근거 URL · 확인일)

- QuantConnect · 실전 자동 실행 · **보유** (가늠 보유) · 지켜본다 — 실시간 시세로 알고리즘을 라이브 모드로 돌린다('run your algorithms in live mode with real-time market data') · https://www.quantconnect.com/docs/v2/writing-algorithms/live-trading · 2026-10-09
- QuantConnect · 백테스트·실전 같은 규칙 · **보유** (가늠 보유) · 지켜본다 — 같은 알고리즘을 백테스트와 라이브에 쓴다(증권사·데이터 공급자만 바꿔서) · https://www.quantconnect.com/docs/v2/writing-algorithms/live-trading · 2026-10-09
- QuantConnect · 증권사 계좌·주문 맞추기 · **부분** (가늠 보유) · 지켜본다 — Key Concepts 에 계좌와 알고리즘 동기화 · Reconciliation(백테스트와의 차이) 절이 있다 — 세부는 그 페이지에 없음 · https://www.quantconnect.com/docs/v2/writing-algorithms/live-trading · 2026-10-09
- QuantConnect · 알림·외부 전달 · **보유** (가늠 부분) · 검토 — Notifications(알고리즘 결정을 알린다) · Commands · Signal exports(포트폴리오 목표를 외부 서비스로) · https://www.quantconnect.com/docs/v2/writing-algorithms/live-trading · 2026-10-09
- QuantConnect · 상시 실행·복구 · **보유** (가늠 부분) · 검토 — 라이브 알고리즘은 Equinix 상주 서버에서 돈다(IDE 를 닫아도 계속) · 배포 때 켜면 런타임 오류·API 끊김에 '최선을 다해' 최대 5번 재시작(5분 넘게 돈 뒤에만 · 상태는 보존 안 됨 — 현금·보유는 증권사에서 다시 읽음) · 가동률 수치·SLA 는 적혀 있지 않다 · https://www.quantconnect.com/docs/v2/cloud-platform/live-trading/deployment · 2026-10-09
- TradingView · 알림·외부 전달 · **보유** (가늠 부분) · 검토 — 알림이 울리면 지정 URL 로 HTTP POST 웹훅(JSON 이면 application/json) · 포트 80·443 만 · 3초 안 응답 없으면 취소 · 2단계 인증 필요 · https://www.tradingview.com/support/solutions/43000529348-how-to-configure-webhook-alerts/ · 2026-10-09
- TradingView · 차트 · **보유** (가늠 부분) · 지켜본다 — 차트 21종(캔들·바·하이킨아시·렌코·카기·P&F·볼륨 풋프린트 …) · 내장 지표·전략 400+ · 공개 지표 100,000+ · 드로잉 도구 110+ · 한 화면 최대 16 차트(종목·시간틀·드로잉 동기화) · 초 단위·레인지 바 · 드로잉·Pine 스크립트에서 알림 · https://www.tradingview.com/features/ · 2026-10-09
- TradingView · 모바일 · **보유** (가늠 부분) · 지켜본다 — 모바일 앱이 있고 레이아웃·관심 목록·설정이 웹·모바일·데스크톱에서 동기화된다(모바일 전용 차트 기능은 적혀 있지 않다) · https://www.tradingview.com/features/ · 2026-10-09
- Composer · 전략 편집기 · **보유** (가늠 없음) · 안 한다 — 자연어로 목표·전략·위험 우려를 적으면 AI 편집기가 전략을 만들고, 코드 없는 시각 편집기(가중 방식 · if/then · 필터)로 고친다 · https://www.composer.trade/ · 2026-10-09
- Composer · 백테스트·실전 같은 규칙 · **보유** (가늠 보유) · 지켜본다 — 백테스트에 수수료·슬리피지·최종 가치를 계산하고, 같은 전략을 자동으로 실행·리밸런싱한다(Composer 자신이 증권사) · https://www.composer.trade/ · 2026-10-09
- Composer · 관제 대시보드 시각화 · **부분** (가늠 보유) · 지켜본다 — 보유 변화를 시간순으로 보이는 Historical Allocation Graph · 백테스트 성과 그래프·지표 표 — 라이브 포트폴리오 대시보드는 페이지에 없음 · https://www.composer.trade/ · 2026-10-09
- Composer · 모바일 · **미확인** (가늠 부분) · 지켜본다 — 모바일 앱은 홈·가격표 어디에도 적혀 있지 않고 앱 스토어 링크도 없다 · /faq 는 404(2026-10-09) — 링크가 없다고 앱이 없다는 뜻은 아니다 · https://www.composer.trade/pricing · 2026-10-09
- Composer · 위험 한도 · **부분** (가늠 보유) · 지켜본다 — 가격표에 자동 위험 한도(손절·포지션 한도·리밸런싱 문턱)는 적혀 있지 않다 · Pro 의 수동 'Skip Trading and Go to Cash'(사람이 거래를 건너뛰고 현금으로)만 있다 · https://www.composer.trade/pricing · 2026-10-09
- TrendSpider · 실전 자동 실행 · **보유** (가늠 보유) · 지켜본다 — Strategy Bots 가 검증된 전략을 라이브 자료로 돌려 알리거나 대신 사고판다('fully autonomous') · 롱/숏/플랫을 아는 position-aware · 웹훅으로 주문 라우팅 서비스(SignalStack) · https://trendspider.com/product/trade-timing-and-execution-tools/ · 2026-10-09
- TrendSpider · 알림·외부 전달 · **보유** (가늠 부분) · 검토 — 추세선·지표·가격대 알림(여러 조건·여러 시간틀) · 클라우드에서 돈다 · 문자·메일·푸시·앱 안 · 웹훅(Discord·Telegram) · https://trendspider.com/product/trade-timing-and-execution-tools/ · 2026-10-09
- TrendSpider · 백테스트·실전 같은 규칙 · **보유** (가늠 보유) · 지켜본다 — 코드 없는 Strategy Tester · 백테스트를 포워드 테스트로 전환 · https://trendspider.com/product/trade-timing-and-execution-tools/ · 2026-10-09
- TrendSpider · 증권사 계좌·주문 맞추기 · **부분** (가늠 보유) · 지켜본다 — 증권사 계좌를 연결해 계좌별 보유를 보고 화면에서 주문 — 지원 증권사 목록은 페이지에 그림으로만 · https://trendspider.com/product/trade-timing-and-execution-tools/ · 2026-10-09
- TrendSpider · 차트 · **보유** (가늠 부분) · 안 한다 — 자동 다중 차트 · 자바스크립트 또는 AI 보조로 사용자 지표 · https://trendspider.com/product/trade-timing-and-execution-tools/ · 2026-10-09
- Quantus(퀀터스) · 전략 편집기 · **보유** (가늠 없음) · 안 한다 — 유니버스(한국·미국·글로벌·암호화폐 · 시총·섹터·테마 필터) → 팩터 → 백테스트 → 실전투자 네 단계 · https://www.quantus.kr/ko · 2026-10-09
- Quantus(퀀터스) · 실전 자동 실행 · **보유** (가늠 보유) · 지켜본다 — 실전투자 메뉴(트레이더 홈 · 퀀터스 주식 · 퀀터스 코인) · 자산은 증권사·거래소에 보관 — 파트너 로고 파일명에 kis 등이 보이나 본문에 회사명은 없음 · https://www.quantus.kr/ko · 2026-10-09
- Quantus(퀀터스) · 관제 대시보드 시각화 · **부분** (가늠 보유) · 지켜본다 — 트레이더 홈이 실전투자 현황과 전략 관리를 제공한다 — 그 밖의 대시보드는 페이지에 없음 · https://www.quantus.kr/ko · 2026-10-09
- Quantus(퀀터스) · 모바일 · **보유** (가늠 부분) · 지켜본다 — Android(Google Play)·iOS(App Store) 앱 링크 · https://www.quantus.kr/ko · 2026-10-09
- Quantus(퀀터스) · 위험 한도 · **미확인** (가늠 보유) · 지켜본다 — 위험 관리 도구는 페이지에 없고 면책 문구만 있다 · https://www.quantus.kr/ko · 2026-10-09

규칙: 경쟁사가 기능을 냈다고 바로 넣지 않는다 — 레이더는 아이디어 발견까지이고, 도입은 필요성 → 기존 자료로 검증 → 구현이다. 경쟁사 변화가 산식·가중치·문턱을 바꾸지 않는다.
