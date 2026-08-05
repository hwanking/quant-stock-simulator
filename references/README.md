# references/ — 디자인 레퍼런스

우리 프로젝트의 **사양이 아니다.** 참고 자료다.
정본은 루트 `CLAUDE.md` 와 `docs/` 다.

## design-md/ (74개)

출처: <https://github.com/VoltAgent/awesome-design-md> · **MIT 라이선스**
받는 법: `python scripts/fetch_design_md.py`

유명 사이트의 디자인 시스템을 분석한 `DESIGN.md` 모음이다. Google Stitch 가
제안한 형식으로, AI 코딩 에이전트가 읽어 UI 를 일관되게 만들도록 돕는다.

### 왜 루트가 아니라 여기인가

`DESIGN.md` 를 프로젝트 루트에 두면 "이 프로젝트의 디자인 사양"이 된다.
74개를 루트에 쏟으면 어느 것이 우리 것인지 알 수 없다. 레퍼런스는 여기
모으고, 그중 **골라 쓴 결정만** `CLAUDE.md` §5 에 적는다.

### 우리가 실제로 쓴 것 (라운드 40)

74개 중 금융·데이터 밀집 계열 **17종**만 분석했다. BMW·Nintendo·Bugatti 는
우리 화면과 성격이 다르다.

> binance · coinbase · kraken · revolut · wise · stripe · mastercard ·
> linear.app · vercel · clickhouse · sentry · posthog · raycast · warp ·
> superhuman · notion · claude

셋 이상에서 반복되는 값만 채택 후보로 봤다 (하나에서만 나온 값은 그
브랜드의 취향이지 원칙이 아니다). 분석 스크립트: `_probe/design_tokens_r40.py`

| 항목 | 레퍼런스 공통 | 우리 현행 | 판정 |
|---|---|---|---|
| 폰트 | Inter(176) · system-ui(87) · SF Pro(19) | SF Pro → Pretendard → Inter | 이미 일치 |
| 숫자 | tabular-nums | 전역 `font-variant-numeric` | 이미 일치 |
| 여백 | 4·8·12·16·24·32·64 | 같은 배수 | 이미 일치 |
| 배경 | #0a0a0a ~ #1a1a1a | #0A0B0F | 이미 충족 |
| 모서리 | 8·12·14 | 9~14 | 이미 일치 |
| **이모지** | **UI 상태 표시에 사용 예 0** | **화면 200개** | **← 격차** |

그래서 라운드 40 에서 바꾼 것은 **이모지 제거 하나**다. 색 토큰은 WCAG
대비를 브라우저에서 실측해 정한 값이라 레퍼런스를 보고 바꾸지 않았다.

판정 색 점(🟢🔴🟡🟠⚪)은 `ui_kit.dot()` — 토큰 색 원으로 교체했다.
이모지는 OS·폰트마다 모양과 크기가 달라 정렬이 깨지고 색을 통제할 수 없다.

## 라이선스

`design-md/` 의 파일은 원 저장소의 MIT 라이선스를 따른다. 각 파일은 해당
브랜드의 공개 웹사이트를 **분석한 문서**이며 브랜드 자산 자체가 아니다.
