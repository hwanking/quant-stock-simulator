# 디자인 시스템 V2 (v4 확장 — 2026-08-01)

기존 docs/DESIGN_SYSTEM.md(토큰·타이포·카드 규칙)를 계승한다. 여기는 v4 추가분만.

## 토큰 (확정 — web_app.py `_TOK` 구현됨)
다크: bg1 #0B0F17 / bg2 #111827 / surface #161D2A / hover #1C2635 /
border #273244 / tx1 #F3F6FA / tx2 #9DAABC / brand #4C8DFF / pos #35C98B /
warn #F2B84B / neg #F26161
라이트: bg1 #F5F7FA / bg2·surface #FFFFFF / hover #F7F9FC / border #E1E6ED /
tx1 #172033 / tx2 #667085 / brand #2563EB / pos #16875D / warn #B7791F / neg #D14343

## 상태 라벨 통일
- 정상: tx2 텍스트 + "정상" / 경고: warn 뱃지 / 오류: neg 뱃지.
- 중요도 뱃지(주요 이슈): 높음=neg / 중간=warn / 낮음=tx2.
  형식: `배경 {색}22 · 글자 {색} · 11px 800 · radius 6px` (구현: `_SEV_BADGE`).
- 카테고리 뱃지(업데이트): 배경 hover · 글자 brand(전역)/tx2(보조) · 11px 700.

## 섹션 헤더 규격
h3(20px 750) 또는 h4(제품 패널). 장식·이모지 금지. 부제는 caption 13px tx2.
"— 부연 설명" 대시 패턴으로 통일 (예: "주요 이슈 — 오늘 꼭 봐야 할 핵심 변화").

## '전체 보기' CTA 규격
- 요약 N건(3~5) 기본 노출 → `st.expander("전체 X 보기 (n건[·필터])")`.
- expander 안은 표(st.dataframe) 또는 동일 카드 반복.
- 적용처: 주요 이슈 / 업데이트 / 공시 / 케이스 스터디 / 모델 성과 분해 /
  기업 재무(전문가 보기) — 전부 같은 패턴 (구현 완료).

## 컬러 테두리 허용처 (그 외 전부 중립 border)
① 최종 결론 배너(동적 판정색) ② 중요도 '높음' 이슈 카드(neg)
③ st.error/warning 기본 스타일. 나머지는 접합 오버라이드가 강제한다.
