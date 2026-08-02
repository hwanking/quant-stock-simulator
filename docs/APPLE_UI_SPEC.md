# APPLE_UI_SPEC — 애플 HIG 수준 시각 언어 전면 재설계 명세 (2026-08-02)

> 이 문서는 CSS 부분 패치 지침이 아니다. **시각 언어를 교체**하는 명세다.
> 선행 문서(REDESIGN_BRIEF_v4_ko.md, DESIGN_SYSTEM_V2.md)는 "정돈"을 말했고
> 이 문서는 "덜어내기"를 말한다. 충돌 시 이 문서가 이긴다.
>
> 기준 측정: `web_app.py` 5,097줄 / `ui_kit.py` 215줄 (2026-08-02 시점).
> 모든 수치는 실측이며, 9장의 검증 스크립트로 재측정할 수 있다.
> **본문의 줄번호는 이 스냅샷 기준**이라 이후 편집으로 어긋난다 —
> 줄번호가 아니라 **함께 적은 코드 조각**으로 위치를 찾을 것.
>
> **애플 디자인의 실체 세 줄**
> ① 구분은 선이 아니라 **표면 대비와 여백**으로 한다.
> ② 위계는 색이 아니라 **크기·위치·침묵**으로 만든다.
> ③ 완성은 더 넣을 게 없을 때가 아니라 **뺄 게 없을 때**다.

---

## 1. 지금이 애플스럽지 않은 이유 10가지 (전부 코드 실측)

### 1) 테두리가 구조를 대신하고 있다 — 인라인 테두리 66곳
`border: Npx solid` 인라인 66회(1px 56 / 2px 7 / 1.5px 2 / 3px 1),
추가로 `border-left` 6 · `border-top` 6 · `border-bottom` 2.
최악은 **상자 안의 상자**다. 결론 배너(`web_app.py:2899`)가
`border:3px solid {_vc}` + `box-shadow:0 10px 34px` 를 두르고,
그 **안에** 다시 색 테두리 카드 4개가 들어간다:
`border:1px solid #30d15855`(2918) · `#64d2ff55`(2922) · `#ff453a55`(2926) ·
`{_dm_color}55`(2930).
애플 설정·건강·주식 앱의 그룹 카드에는 테두리가 **한 개도** 없다.

### 2) 섹션을 여백이 아니라 가로선으로 나눈다
`st.markdown("---")` 22회, `st.divider()` 0회, `hr { margin: 26px 0 }`(291).
사이드바에도 `---` 4개. 애플 설정 앱은 그룹 사이를 **35pt 여백**으로만 나누고
전면 가로선은 쓰지 않는다. 선은 "여백을 줄 자신이 없을 때" 쓰는 대체재다.

### 3) 여백 어휘가 존재하지 않는다 — padding 31종 · margin 46종
8pt 그리드 밖 값이 다수: `11px 15px`, `13px 18px`, `22px 26px`, `3px 0 0 0`,
`2px 8px`, `4px 10px`. 같은 위계의 카드가 `14px 16px` / `10px 14px` /
`18px` / `20px` 로 제각각이라, 화면을 스크롤하면 카드가 미묘하게 들썩인다.

### 4) 모서리 반경이 10종
실측 분포: `12px×36, 14px×16, 10px×14, 8px×10, 6px×6, 16px×5, 20px×2, 18px×1,
3px×1, 999px×1`. 한 화면에 12px 카드와 14px 카드와 20px 배너가 동시에 있다.
애플은 한 화면에서 실질 2종(그룹 카드 1종 + pill 1종)만 쓴다.

### 5) 색이 85종 — 토큰을 정의해놓고 하드코딩과 함께 쓴다
6자리 hex 등장 **701회 / 85종**. `_TOK` 12토큰을 만들어 놓고도
`#86868b` 93회, `#30d158` 71회, `#2c2c2e` 54회, `#ff453a` 51회, `#1c1c1e` 50회,
`#d2d2d7` 45회, `#ff9f0a` 44회가 인라인으로 남아 있다.
브랜드 팔레트에 없는 **보라 `#bf5af2` 26회**가 사이드바 select 테두리(478)와
버튼 hover(547)에 살아 있다.

### 6) 강조 수단이 오직 색이다
색 면(alert) 92개: `st.info` 19 · `st.success` 23 · `st.warning` 29 · `st.error` 21.
중요한 것마다 색을 칠했으므로 **전부 중요 = 아무것도 안 중요**가 됐다.
애플은 색을 "의미"에만 남긴다(등락·위험). 위계는 32px 값 vs 13px 라벨,
40px 여백 vs 12px 여백 같은 **무채색 수단**으로 만든다.

### 7) 크롬(UI 구조물)에 이모지가 섞여 있다 — 67개
`st.subheader("🏆 오늘의 AI 퀀트 최적 종목 TOP 3")`(1281),
`st.header("💼 내 보유종목")`(1720),
`st.metric("🎯 목표가 (+N%) 선도달 확률", ...)`(4070),
`st.button("⭐ 이 목록을 관심종목으로 저장")`(1402),
`st.expander("📡 관심 데이터 연동 현황")`(1109).
UI 문자열 전체 이모지 319개 / 80종 중 **67개가 크롬**이다.
애플의 크롬 아이콘은 SF Symbols 단색 1종이며, 컬러 그림문자는 콘텐츠에만 쓴다.

### 8) `st.metric` 기본 스타일 + 규칙이 서로를 덮는다
같은 셀렉터에 상충 규칙이 두 벌이다.
`web_app.py:308` → `[data-testid="stMetricValue"] { font-size:22px !important; font-weight:600 }`
`web_app.py:490` → `[data-testid="stMetricValue"] { font-size:34px !important; font-weight:700; color:#ffffff }`
둘 다 `!important`, 동일 특이도 → **뒤에 삽입된 34px가 이긴다.**
즉 "지수 숫자를 22px로 낮춘다"(v2 결정)는 코드상 **무효**다.
라벨도 `13px/500`(310) vs `15px/700/#b0b5c0`(496) 충돌.
게다가 Streamlit 기본 delta는 **상승=초록**을 강제해 한국 관례와 반대다.

### 9) 사이드바가 색 박스의 벽이다
`[data-testid="stSidebar"] * { color: #ffffff !important; }`(437) —
와일드카드로 모든 위계를 지운 뒤,
`p,span,label,li { font-size:15px !important; font-weight:600 !important }`(454)로
**전부 굵게** 만들었다. 라벨과 값이 구분되지 않는다.
그 위에 `st.sidebar.success` 2 · `info` 1 · `warning` 2 색 박스,
`---` 4개, 보라 테두리 select(478),
`border:2px solid brand` + **상시** `box-shadow 0 0 0 3px`(376) 검색창을 쌓았다.
결과: 스크롤 없이 색 면 5장 + 굵은 글자 40줄.

### 10) 라이트 모드가 라이트가 아니고, `<style>` 블록이 7개다
`_CARD_BG = '#161D2A'`(212)를 **양 테마 공통**으로 고정해, 라이트에서
흰 바탕 위에 다크 카드가 뜬다. 그 상태를 유지하려고
`:not([style*="color"]):not(div[style*="background"] *)...`(567) 같은
방어 셀렉터를 짜 넣었다. 애플의 두 테마는 **같은 구조 · 다른 표면**이다.
덤으로 `<style>` 블록이 7개(241 · 400 · 410 · 435 · 578 · 773 · 3037)라
어느 규칙이 이기는지 코드만 보고는 알 수 없다.

---

## 2. iOS Grouped Inset List 이식

애플 설정·건강 앱의 핵심 패턴. **이 앱 화면의 60%는 이 패턴 하나로 대체된다.**

### 2.1 해부도

```
[섹션 헤더]  20px/600/tx1 + 부제 13px/tx2      ← 작고 조용하게. 크지 않다.
   ↓ 12px
┌─ 그룹 카드 ─────────────────────────────┐   background: L1, radius 18, 테두리 없음
│  라벨            값                       │   padding: 12px 0 (좌우는 카드 20px)
│ ────────────────────────────────────── │   ← 헤어라인 1px (카드보다 밝은 색)
│  라벨            값                       │
│ ────────────────────────────────────── │
│  라벨            값                       │   마지막 행 아래 헤어라인 없음
└──────────────────────────────────────┘
   ↓ 16px (같은 섹션 내 다음 그룹)
   ↓ 40px (다음 섹션)
```

### 2.2 정확한 규격

| 요소 | 값 |
|---|---|
| 그룹 카드 배경 | 다크 `#161D2A` / 라이트 `#FFFFFF` |
| 그룹 카드 radius | `18px` |
| 그룹 카드 테두리 | **없음** (예외: 4.4 결론 카드만) |
| 그룹 카드 패딩 | `6px 20px` (상하 6 + 행 상하 12 = 실질 18) |
| 행 상하 패딩 | `12px` → 행 높이 최소 **44px** (애플 최소 터치 타깃) |
| 행 구분 | `border-top: 1px solid {line}`, **첫 행 제외** |
| 헤어라인 색 | 다크 `#222C3C` / 라이트 `#E6EAF0` |
| 좌측 라벨 | `15px / 400 / tx2` · `white-space: normal` |
| 우측 값 | `15px / 600 / tx1` · `tabular-nums` · `text-align: right` |
| 라벨↔값 최소 간격 | `gap: 16px`, `align-items: baseline` |
| 값 강조색 | 의미가 있을 때만(up/down/warn/neg). 기본은 tx1 |
| 섹션 헤더 여백 | 위 `40px` / 아래 `12px` |
| 그룹 간 여백 | `16px` |

구현체는 이미 있다: `ui_kit.py:90 rows()`. 규격이 위와 일치하는지 확인하고,
**모든 라벨-값 나열은 예외 없이 이 함수로만** 그린다.

### 2.3 화면 매핑 — 어디를 이 패턴으로 바꾸는가

| 현재 위치 (web_app.py) | 현재 형태 | 전환 후 |
|---|---|---|
| 2472–2496 모델 신뢰도 5개 | `st.metric` ×5 | `stat_tiles` (완료, 2481) |
| **2916–2935 실행 가격 4칸** | 색 테두리 카드 4개 | **`rows()` 4행: 권장 매수가 / 1차 목표가 / 손절가 / DeMARK** |
| 3042–3053 우측 고정 패널 `.qside` | `<table>` + 테두리 | `rows()` 규격으로 통일, 테두리 제거 |
| 3128–3133 점수 구성 | `st.dataframe` 4열 | `rows()` — 항목명 / `N점 · 비중 M%` |
| 1234–1260 시세 교차검증 | `.cross-val-matrix` 표 (테두리) | `rows()` 3행 (네이버 / 다음 / 판정) |
| 928 자산·통화 스키마 검증 | `st.sidebar.info` 색 박스 | `expander("데이터 검증")` 안 `rows()` 4행, 기본 접힘 |
| 927 선택 종목 | `st.sidebar.success` 색 박스 | `rows()` 2행 (종목 / 현재가) |
| 4183–4201 시뮬레이션 통계 6개 | `st.metric` ×6 | `rows()` 6행 |
| 4128–4135 일치도·보유기간·rho | `st.metric` ×3 | `rows()` 3행 |
| 1130–1137 분석 파라미터 | 사이드바 위젯 나열 | 위젯 유지 + 하단 `rows()` 요약 3행 |
| 3018 모델·케이스 수 캡션 | 인라인 caption | `rows()` 2행 (모델 버전 / 누적 케이스) |
| 데이터 출처·갱신 시각 | 산재한 caption | 화면 하단 `rows()` 그룹 1개로 수렴 |

**판단 기준**: "라벨 : 값" 쌍이 2개 이상 나열되면 무조건 `rows()`.
카드도 아니고 표도 아니고 metric도 아니다.

---

## 3. 수직 리듬 규격 (8pt 그리드)

**허용 여백 값은 6종뿐이다: `4 · 8 · 12 · 16 · 24 · 40`** (+ 페이지 상단 32).
이 밖의 값을 쓰려면 이 문서를 고쳐야 한다.

| 구간 | 값 | 근거 |
|---|---|---|
| 페이지 상단 패딩 | `32px` | `.stMainBlockContainer { padding-top: 2rem }` |
| 본문 최대 폭 | `1120px` | 15px 본문에서 한 줄 72–80자. 현재 1440은 너무 넓다 |
| **섹션 ↔ 섹션** | `40px` | `ui_kit.section(top=40)` — 가로선 없이 이것만으로 나뉜다 |
| 섹션 헤더 ↔ 첫 그룹 | `12px` | 헤더는 그룹의 소유물이라 가깝게 |
| 섹션 제목 ↔ 부제 | `2px` | 한 덩어리로 읽혀야 함 |
| 그룹 ↔ 그룹 (같은 섹션) | `16px` | |
| 그룹 카드 안쪽 좌우 | `20px` | |
| 그룹 카드 안쪽 상하 | `6px` (+행 12 = 18) | |
| 행 상하 패딩 | `12px` | 행 높이 ≥ 44px |
| 일반 카드 안쪽 | `22px` | `ui_kit.card(pad=22)` |
| 카드 내부 블록 간 | `12px` | |
| 라벨 ↔ 값 (세로) | `6px` | 타일 |
| 값 ↔ 보조설명 | `4px` | |
| 캡션·note 위 | `10px` | 카드 **밖**에 둔다 |
| 열(column) 사이 | `16px` | `st.columns(gap="medium")` |
| 사이드바 그룹 간 | `28px` | `---` 대신 |

**금지**: `st.markdown("---")`, `st.divider()`, `<hr>`, `<div style='height:Npx'>`
스페이서. 여백은 섹션 컴포넌트가 만든다. 예외는 페이지 최하단 저작권 구분선 1개.

---

## 4. 표면 계층 (Elevation)

테두리가 없으므로 **층은 명도로만 보인다.** 값이 이 스펙의 심장이다.

### 4.1 다크

| 층 | 이름 | 색 | 용도 |
|---|---|---|---|
| L0 | `bg` | `#0B0F17` | 앱 배경, 사이드바 배경 |
| L1 | `card` | `#161D2A` | 그룹 카드, expander, alert, 표 |
| L2 | `raised` | `#1C2635` | 카드 안의 카드, hover, 입력창, 배지 |
| — | `line` | `#222C3C` | 헤어라인 전용 (테두리 아님) |

인접 대비비(WCAG 상대휘도 기준 실측):
`L0→L1 = 1.12:1`, `L1→L2 = 1.12:1`, `L1→line = 1.23:1`.

**목표 범위: 인접 표면 1.10–1.20:1.**
1.10 미만이면 층이 안 보이고, **1.5 초과면 카드가 "박스"로 보여 테두리를 지운 의미가 사라진다.**

### 4.2 라이트

| 층 | 이름 | 색 | 비고 |
|---|---|---|---|
| L0 | `bg` | **`#EFF1F6`** | ⚠️ 현재 `#F5F7FA` → 흰 카드와 대비 **1.08:1**로 부족. 아래 참조 |
| L1 | `card` | `#FFFFFF` | |
| L2 | `raised` | `#F2F5F9` | |
| — | `line` | `#E6EAF0` | |

**`#F5F7FA` → `#EFF1F6` 변경 근거 (실측):**
`#F5F7FA` 상대휘도 0.9192 → 흰색 대비 **1.083:1** (층이 안 보임)
`#EFF1F6` 상대휘도 0.8790 → 흰색 대비 **1.130:1** (다크와 동일한 층감)
참고: iOS `systemGroupedBackground`(#F2F2F7) 대 흰색 = 1.126:1.

### 4.3 테두리 사용 금지 원칙

```
그룹 카드   테두리 없음
일반 카드   테두리 없음
expander   테두리 없음
alert      테두리 없음 (좌측 3px 액센트만 허용)
표         테두리 없음 (행 사이 헤어라인만)
버튼       1px line 색 허용 (형태를 위한 최소한)
입력창     테두리 없음. 배경 L2로 구분. 포커스에만 3px 링
탭         테두리 없음. 선택 탭만 L2 배경
사이드바   우측 창 분리선 1px line 1개만 (레이아웃 경계라 예외)
```

**그림자 금지.** 다크도 라이트도. 층은 명도로만.
현재 `box-shadow` 8회 → 목표 **1회**(4.4).

### 4.4 유일한 예외 — 최종 결론 카드

화면 전체에서 테두리와 그림자를 가진 요소는 **이 하나뿐**이다.
하나뿐이기 때문에 시선이 반드시 여기로 온다. 두 개가 되는 순간 효과는 0이다.

```css
background: {L1};                       /* 그라디언트 금지 — 단색 */
border: 1px solid {판정색}40;           /* 3px → 1px. 40 = 25% 알파 */
border-radius: 22px;
box-shadow: 0 8px 32px {판정색}1A;      /* 1A = 10% 알파. 색면이 아니라 후광 */
padding: 28px 32px;
```

내부의 실행가격 4칸은 **색 테두리를 전부 제거**하고 `rows()` 4행으로 바꾼다
(2.3 매핑 참조). 결론 카드 안에 또 카드를 넣지 않는다.

---

## 5. `st.metric` 대체 스펙

**`st.metric` 사용 횟수 목표: 22 → 0.**
이유: ① 라벨/값 크기를 CSS로만 통제해야 해서 규칙 충돌이 생긴다(1장 8번)
② delta가 **상승=초록**을 강제해 한국 관례와 반대다
③ 테두리·간격을 Streamlit이 정한다.

### 5.1 타일 규격 (`ui_kit.stat_tiles`)

| 요소 | 규격 |
|---|---|
| 컨테이너 | `background: L1` · `radius: 18px` · `padding: 20px 6px` · `display:flex` |
| 타일 | `flex: 1 1 0` · `min-width: 0` · `padding: 4px 14px` |
| 타일 구분 | `border-left: 1px solid {line}` — **첫 타일 제외** |
| 라벨 | `13px / 500 / tx2` · `letter-spacing: 0` · **대문자 변환 금지** · 1줄 말줄임 |
| 값 | `clamp(20px, 2.4vw, 28px)` / `600` / `letter-spacing: -0.02em` / `line-height: 1.15` / `tabular-nums` / **줄바꿈 금지**(`white-space:nowrap` + 말줄임) |
| 주인공 값 | 상한만 `34px`로 (화면당 최대 1곳) |
| 보조 | `12px / 400 / tx3` · `line-height: 1.45` · 최대 2줄 · `word-break: keep-all` |
| 값↔라벨 | `6px` · 값↔보조 `4px` |

`text-transform: uppercase` 금지 — 한글에 무의미하고 영문 라벨만 튄다.

### 5.2 색 규칙 (한국 관례)

**두 축을 절대 섞지 않는다.**

| 축 | 의미 | 다크 | 라이트 |
|---|---|---|---|
| **가격 등락** | 상승·이익 | `up #FF453A` (빨강) | `#D93025` |
| | 하락·손실 | `down #0A84FF` (파랑) | `#1A73E8` |
| | 보합 | `tx1` | `tx1` |
| **모델 판정** | 양호 | `pos #35C98B` | `#16875D` |
| | 주의 | `warn #F2B84B` | `#B7791F` |
| | 위험 | `neg #F26161` | `#D14343` |
| **중립** | 그 외 전부 | `tx1 #F3F6FA` | `#111827` |

- 가격·수익률·등락률에 `pos`(초록)를 쓰면 **버그**다. 현재 `#30d158`(초록)이
  71회 쓰이고 그중 "🟢 상승 시나리오"(4490)처럼 관례를 어기는 곳이 있다.
- 판정색(pos/warn/neg)은 **모델의 평가**에만. 시장 숫자에는 절대 쓰지 않는다.
- 색을 쓰는 타일은 한 줄(4칸)에 **최대 2칸**. 전부 색이면 색이 아니다.
- 화살표 기호(▲▼)는 값 앞이 아니라 **보조 줄**에만. 값은 숫자로 시작한다.

---

## 6. 사이드바 정숙화

목표: 사이드바에서 **색 면 0개, 가로선 0개, 굵은 글자는 값에만.**

### 6.1 지우는 것 (먼저)

```
[data-testid="stSidebar"] * { color:#ffffff !important }      (437)  → 삭제
[data-testid="stSidebar"] p,span,label,li { font-size:15px !important;
                                            font-weight:600 !important } (454) → 삭제
[data-testid="stSidebar"] [data-baseweb="select"] {
    border:1.5px solid #bf5af2 }                              (478)  → 삭제
input[aria-label*="종목명"] { border:2px solid brand;
    box-shadow:0 0 0 3px brand30 }                            (376)  → 상시 링 삭제
홈 버튼 { font-size:28px; border:2px solid; box-shadow:0 2px 0;
          :active{transform:translateY(2px)} }                (791)  → 전부 삭제
st.sidebar.markdown("---") ×4                                        → 삭제
st.sidebar.success ×2 / info ×1 / warning ×2                         → rows()·dot 로 전환
```

### 6.2 새 규격

| 요소 | 규격 |
|---|---|
| 사이드바 배경 | 본문과 **동일** `L0` (`#0B0F17` / `#EFF1F6`) |
| 우측 경계 | `1px solid {line}` — 창 분리선 1개만 |
| 좌우 패딩 | `20px` |
| 그룹 헤더 | `13px / 500 / tx2` · 아래 `8px` |
| 그룹 간 | `28px` (가로선 아님) |
| 앱 이름(홈) | `17px / 600 / tx1` · 테두리·배경·그림자 없음 · `:hover { color: brand }` · `:active { opacity:.6 }` |
| 위젯 라벨 | `13px / 500 / tx2` |
| 위젯 값·입력 텍스트 | `15px / 500 / tx1` |
| 입력창 | `background: L2` · 테두리 없음 · `radius: 10px` · `padding: 10px 12px` |
| 입력창 포커스 | `box-shadow: 0 0 0 3px {brand}40` — **포커스에만** |
| 버튼 | `radius: 980px` · `background: L2` · `1px solid {line}` · `15px/600` |

### 6.3 상태는 색 박스가 아니라 점(dot) 하나

```html
<div style='display:flex; align-items:center; gap:8px; padding:6px 0;'>
  <span style='width:8px; height:8px; border-radius:50%;
               background:{dot}; flex:none;'></span>
  <span style='font-size:13px; color:{tx2};'>{한 줄 설명}</span>
</div>
```

| 상태 | dot 색 | 문구 예 |
|---|---|---|
| 정상 | `pos #35C98B` | `실시간 시세 교차검증 일치` |
| 주의 | `warn #F2B84B` | `지수 일부 미수신 — 판정 보류` |
| 오류 | `neg #F26161` | `데이터 수집 실패` |
| 대기 | `tx3 #6B7A90` | `스캔 대기` |

점의 지름은 8px. **색이 화면에서 차지하는 면적은 50px² 이하**다.
현재 색 박스 5장은 대략 40,000px² — 800배 줄어든다.

### 6.4 사이드바 색 총량 규칙

사이드바 안에서 브랜드색(`#4C8DFF`)이 칠해진 요소는 **동시에 최대 1개**
(포커스 링 **또는** 활성 항목). 그 외 모든 것은 무채색 3단계(tx1/tx2/tx3)뿐.

---

## 7. 모션

애플은 모션을 "정보"로 쓴다. 장식으로 쓰지 않는다.

### 7.1 허용 목록

| 대상 | 속성 | 규격 |
|---|---|---|
| 카드·행 hover | `background-color` | `0.2s ease` (L1 → L2) |
| 버튼 hover | `background-color, border-color` | `0.2s ease` |
| 링크·아이콘 hover | `color` | `0.2s ease` |
| 버튼 누름 | `opacity` | `0.6`, 트랜지션 없음(즉시) |
| 입력 포커스 링 | `box-shadow` | `0.15s ease` |
| expander 펼침 | Streamlit 기본 | 그대로 |
| 요소 등장 | `opacity 0→1` | `0.2s ease`, 이동 없음 |

**최대 지속시간 0.2s.** 동시에 트랜지션되는 속성은 **최대 2개**.

```css
@media (prefers-reduced-motion: reduce) {
  * { transition: none !important; animation: none !important; }
}
```
이 블록은 필수다. 현재 없다.

### 7.2 금지 목록

```
✗ transform: scale()            — 카드가 커지는 hover
✗ transform: rotate()
✗ transform: translateY(2px)    — '눌림' 효과 (현재 818에 있음) → opacity로 대체
✗ @keyframes / animation        — 펄스·글로우·blink·shimmer·회전 스피너 장식
✗ box-shadow 트랜지션           — 현재 271에 있음. 그림자 자체를 없앤다
✗ 0.2s 초과 지속시간            — 현재 hr·카드에 .12s/.15s 혼재 → 0.2s로 통일
✗ transition: all              — 무엇이 움직이는지 통제 불능
✗ cubic-bezier 커스텀 이징      — ease 하나로 통일
✗ 스크롤 연동 애니메이션 / 패럴랙스
✗ 로딩 중 색이 변하는 스켈레톤   — 정적 L2 면으로
```

현재 `transform` 5회 · `transition` 2회 · `animation` 0 · `keyframes` 0.
**목표: `transform` 0회, `transition`은 `ui_kit.global_css` 안에서만.**

---

## 8. 구현 우선순위 5단계

각 단계는 **"무엇을 지우는가"가 먼저**다. 넣기 전에 뺀다.
단계 하나가 끝날 때마다 9장 체크리스트를 돌려 수치로 확인한다.

### 1단계 — 테두리 말살 (화면이 가장 많이 바뀌는 단계)

**지운다**
- 인라인 `border: Npx solid` **66개 → 1개** (결론 카드만 생존, 3px→1px)
- `border-left` 6 → 4 (alert 액센트만), `border-top` 6 → 헤어라인으로 재해석,
  `border-bottom` 2 → 0
- 실행가격 4칸의 색 테두리(2918·2922·2926·2930) 전부
- `.cross-val-matrix` 의 `border: 1px solid #2d3139`(516)와 셀 `border-top`
- `.qnav` 의 `border: 1px solid`(406) — 하단 헤어라인 1개로
- expander·alert·dataframe 테두리 (`ui_kit.global_css` 가 이미 처리)
- **`_CSS_BORDER_MAP` 접합 오버라이드(232–238) 블록 자체** — 테두리 색을 통일하는
  코드다. 테두리가 없어지면 존재 이유가 없다.
- `box-shadow` 8 → 1, `linear-gradient` 3 → 0

**넣는다**: 표면 3단계(4장) 적용, `ui_kit.rows()` / `card()` 로 카드 렌더 교체.

**효과**: 화면 속 "상자"가 66개에서 1개로. 이 단계만으로 인상의 절반이 바뀐다.

---

### 2단계 — 수직 리듬

**지운다**
- `st.markdown("---")` **22개 → 0**, 사이드바 `---` 4개 → 0
- `<div style='margin-bottom: 12px'></div>` 류 수동 스페이서 전부
- padding **31종 → 4종** (`20 / 12 / 6 / 4`)
- margin **46종 → 6종** (`0 / 4 / 8 / 12 / 16 / 40`)
- `.stMainBlockContainer { max-width: 1440px }` → `1120px`

**넣는다**: 모든 섹션 진입을 `ui_kit.section(title, subtitle, top=40)` 으로 통일.

**효과**: 스크롤이 "리듬"을 갖는다. 가로선 없이도 섹션이 나뉜다.

---

### 3단계 — 색 소음 제거

**지운다**
- 하드코딩 hex **85종 → 14종** (토큰 12 + 판정 동적색 2)
  - `#86868b`(93) → `tx2` / `#2c2c2e`(54) → `line` / `#1c1c1e`(50) → `card`
  - `#f5f5f7`(50) → `tx1` / `#d2d2d7`(45) → `tx2` / `#141416`(20) → `card`
  - `#30d158`(71) → 문맥에 따라 `up`(가격) 또는 `pos`(판정) — **전수 판별 필요**
  - `#ff453a`(51) → `up`(가격) 또는 `neg`(판정) — 전수 판별 필요
  - `#ff9f0a`(44) → `warn` / `#64d2ff`(22) → `brand`
  - **`#bf5af2`(26) → 전부 삭제.** 보라는 팔레트에 없다.
- `[data-testid="stSidebar"] * { color:#ffffff !important }`(437)
- 상충하는 `stMetricValue` 규칙 2벌 중 1벌(490–506 블록)
- `p, span, li, label { font-size: 16px }`(555) — 타입 스케일 밖
- 라이트 모드 방어 셀렉터 `_G`(567) 전체 — 카드가 흰색이 되면 불필요해진다
- `_CARD_BG` 양테마 고정(212–230) — 라이트는 `#FFFFFF` 카드로
- `<style>` 블록 **7개 → 2개** (전역 1 + `ui_kit.global_css` 1)

**넣는다**: 라이트 L0를 `#EFF1F6` 로(4.2), 등락/판정 2축 색 규칙(5.2).

---

### 4단계 — 크롬 이모지 제거 · 위젯 교체

**지운다**
- 크롬 이모지 **67개 → 0** (`st.subheader` / `st.header` / `st.button` /
  `st.expander` / `st.metric` 라벨 / `### ` 제목)
- `st.metric` **22개 → 0** → `stat_tiles` / `rows`
- alert 92개 → **≤ 12개**. 남기는 것은 실제 차단·실패뿐:
  veto(3105), 지수 미수신(2616), OCR 실패, 저장 실패.
  나머지 정보 전달용은 `rows()` 또는 `ui_kit.note()` 로.
- `st.caption` 85개 → ≤ 40개 (같은 섹션 내 중복 주의문 병합)
- 본문 이모지 252개 중 상태 표기용(🟢🟡🔴⚪ 35개) → 6.3 dot 로

**넣는다**: 상태 dot 컴포넌트, `ui_kit.note()`.

**남겨도 되는 이모지**: 없다. 크롬은 0, 본문도 dot·텍스트로 대체 가능하면 대체.
단 사용자 작성 콘텐츠·뉴스 원문 인용은 예외.

---

### 5단계 — 사이드바·내비 정숙화 + 모션 정리

**지운다**
- 6.1 목록 전부 (와일드카드 color, 전역 600 굵기, 보라 테두리, 상시 글로우,
  28px 홈 버튼과 그 눌림 효과)
- `.qnav` 배경 색면 + 테두리 + `border-radius: 12px` → 배경 투명 + 하단 헤어라인
- `transform` 5회 → 0, `transition` 은 `global_css` 안으로 회수
- 카드 hover `translateY(-1px)`(274) → 배경 변화만

**넣는다**: 상태 dot, `prefers-reduced-motion` 블록, 포커스 링(포커스에만).

---

### 단계별 완료 게이트

| 단계 | 통과 조건 (9장 항목 번호) |
|---|---|
| 1 | ①②⑨⑩ 통과 |
| 2 | ③④ 통과 |
| 3 | ⑤⑧⑬⑭⑮ 통과 |
| 4 | ⑥⑦ 통과 |
| 5 | ⑪⑫ 통과 |

---

## 9. 검증 체크리스트 (15항목 · 전부 자동 측정)

| # | 항목 | 판정 기준 | 측정 정규식 / 방법 |
|---|---|---|---|
| ① | 테두리 있는 카드가 결론 카드 1개뿐인가 | `== 1` | `border:\s*[\d.]+px\s+(solid|dashed)` 인라인 카운트 |
| ② | 모서리 반경이 4종 이하인가 | `≤ 4` 이고 `⊆ {10,14,18,980}` | `border-radius:\s*([\d.]+)px` 고유값 |
| ③ | 가로 구분선이 사라졌는가 | `== 0` | `st.markdown("---")` + `st.divider()` + `<hr` |
| ④ | 섹션 간 여백이 40px 이상인가 | `top < 40` 인 호출 `== 0` | `_uk\.section\([^)]*top\s*=\s*(\d+)` |
| ⑤ | 하드코딩 색이 14종 이하인가 | `≤ 14` | `#[0-9a-fA-F]{6}` 고유값 (토큰 정의부 제외) |
| ⑥ | 크롬에 이모지가 0개인가 | `== 0` | 이모지 정규식 ∩ `st\.(subheader\|header\|title\|button\|expander\|metric)\(` 또는 `st\.markdown\("#{2,4} ` 인 줄 |
| ⑦ | `st.metric` 이 0개인가 | `== 0` | `st\.metric\(` |
| ⑧ | `<style>` 블록이 2개 이하인가 | `≤ 2` | `<style>` 카운트 |
| ⑨ | 그림자가 1개 이하인가 | `≤ 1` | `box-shadow` (포커스 링·`prefers-reduced` 제외) |
| ⑩ | 그라디언트가 0개인가 | `== 0` | `linear-gradient\|radial-gradient` |
| ⑪ | 금지 모션이 0개인가 | `== 0` | `@keyframes\|animation:\|scale\(\|rotate\(\|transition:\s*all\|transition:[^;]*0\.[3-9]s` |
| ⑫ | 사이드바에 색 면 alert가 0개인가 | `== 0` | `st\.sidebar\.(info\|success\|warning\|error)\(` + `with st.sidebar` 블록 내 동일 |
| ⑬ | 와일드카드 color 강제가 없는가 | `== 0` | `\]\s*\*\s*\{[^}]*color` |
| ⑭ | 폰트 크기가 스케일 안에 있는가 | 고유값 `⊆ {12,13,15,17,20,22,28,34}` | `font-size:\s*([\d.]+)px` |
| ⑮ | 라이트 모드 카드가 흰색인가 | `_CARD_BG` 양테마 고정 규칙 `== 0` | `_CARD_BG\s*=\s*'#161D2A'` 및 `background:\s*#161D2A\s*!important` |

### 측정 스크립트 (임시 파일로 실행 — 저장소에 커밋하지 않는다)

```python
# -*- coding: utf-8 -*-
import re, collections
S = open(r"...\web_app.py", encoding="utf-8").read()
E = re.compile("[\U0001F300-\U0001FAFF☀-➿⬀-⯿←-⇿"
               "ℹ✅❌⚠]")
CHROME = re.compile(r'st\.(subheader|header|title|button|expander|metric)\('
                    r'|st\.markdown\(f?"#{2,4}\s')
chk = {}
chk['①테두리']   = len(re.findall(r"border:\s*[\d.]+px\s+(?:solid|dashed)", S))
rad = set(re.findall(r"border-radius:\s*([\d.]+)px", S))
chk['②반경']     = (len(rad), sorted(rad))
chk['③구분선']   = S.count('st.markdown("---")') + S.count('st.divider()') + S.count('<hr')
chk['⑤색']       = len(set(h.lower() for h in re.findall(r"#[0-9a-fA-F]{6}", S)))
chk['⑥크롬이모지'] = sum(len(E.findall(l)) for l in S.splitlines()
                        if CHROME.search(l) and not l.strip().startswith('#'))
chk['⑦metric']   = S.count('st.metric(')
chk['⑧style']    = S.count('<style>')
chk['⑨그림자']   = S.count('box-shadow')
chk['⑩그라디언트'] = len(re.findall(r"(linear|radial)-gradient", S))
chk['⑪금지모션'] = len(re.findall(
    r"@keyframes|animation:|scale\(|rotate\(|transition:\s*all"
    r"|transition:[^;]*0\.[3-9]s", S))
chk['⑫사이드바색면'] = len(re.findall(r"st\.sidebar\.(info|success|warning|error)\(", S))
chk['⑬와일드카드'] = len(re.findall(r"\]\s*\*\s*\{[^}]*color", S))
fs = set(re.findall(r"font-size:\s*([\d.]+)px", S))
chk['⑭폰트']     = (sorted(fs), sorted(fs - {'12','13','15','17','20','22','28','34'}))
chk['⑮라이트카드'] = len(re.findall(r"_CARD_BG\s*=\s*'#161D2A'"
                                  r"|background:\s*#161D2A\s*!important", S))
for k, v in chk.items():
    print(k, '=', v)
```

### 기준선 (2026-08-02 실측) → 목표

| 항목 | 현재 | 목표 |
|---|---|---|
| ① 인라인 테두리 | 66 | 1 |
| ② 반경 종류 | 10 | ≤ 4 |
| ③ 가로 구분선 | 22 | 0 |
| ⑤ 하드코딩 색 종류 | 85 | ≤ 14 |
| ⑥ 크롬 이모지 | 67 | 0 |
| ⑦ st.metric | 22 | 0 |
| ⑧ `<style>` 블록 | 7 | ≤ 2 |
| ⑨ box-shadow | 8 | ≤ 1 |
| ⑩ 그라디언트 | 3 | 0 |
| ⑫ 사이드바 색 면 | 5 | 0 |
| ⑬ 와일드카드 color | 1 | 0 |
| (참고) alert 총량 | 92 | ≤ 12 |
| (참고) padding 종류 | 31 | ≤ 4 |
| (참고) margin 종류 | 46 | ≤ 6 |

---

## 부록 A. 판정 요약 — "애플스러움"의 조작적 정의

이 앱이 애플스러워졌다는 것은 다음 문장이 전부 참이라는 뜻이다.

1. 스크린샷을 흑백으로 바꿔도 **정보 위계가 그대로 읽힌다** (색이 위계를 안 만듦).
2. 한 화면에서 **색이 칠해진 면적이 5% 미만**이다.
3. 화면에 **테두리를 가진 요소가 1개**다.
4. 섹션이 몇 개인지 **가로선을 세지 않고 여백만으로** 알 수 있다.
5. 라벨-값 나열이 **전부 같은 모양**이다 (rows 하나로만 그려서).
6. 제목·버튼·탭에 **그림문자가 없다**.
7. 값 숫자가 **자릿수 정렬**되어 위아래로 흔들리지 않는다 (tabular-nums).
8. 라이트/다크 전환 시 **구조가 1px도 안 움직인다** (표면 색만 바뀜).

## 부록 B. 이 문서와 기존 문서의 관계

| 문서 | 관계 |
|---|---|
| `REDESIGN_BRIEF_v4_ko.md` | 정보 구조·제품 UX. **유효**, 이 문서는 그 위의 시각 언어. |
| `DESIGN_SYSTEM_V2.md` | 토큰 값 계승. **단, 라이트 `bg1` `#F5F7FA`→`#EFF1F6`, 테두리 허용처 3종→1종으로 이 문서가 갱신한다.** |
| `COMPONENT_RULES.md` | 카드 규칙 → 이 문서 2·4장으로 대체. |
| `ui_kit.py` | 이 문서의 **구현체**. 규격 불일치 시 이 문서가 기준. |
| `CURRENT_UI_PROBLEMS.md` | 1장이 코드 실측으로 이를 대체·확장. |
