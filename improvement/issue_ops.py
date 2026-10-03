# -*- coding: utf-8 -*-
"""
이슈 운영 — 경고를 띄우는 데서 끝내지 않고 **조치까지 관리**한다.

규칙 (사용자 지시):
  · 모든 이슈에 원인·사용자 영향·즉시 수정 가능 여부·조치 상태·담당 모듈·
    수정 예정일·해결 버전·검증 결과가 있어야 한다.
  · 3일 이상 아무 설명 없이 같은 경고만 반복하는 것은 금지.
    경과일에 따라 자동으로 등급이 올라가고 조치가 강제된다.
  · 물리적으로 3일 안에 못 고치는 것(표본 축적 등)은 억지로 해결 처리하지
    않는다 — 대신 '왜 못 고치는지·임시 안전조치·목표·재평가 시점'을 적는다.

상태: 확인 중 → 수정 중 → 검증 중 → 해결 완료
      (또는) 즉시 수정 불가 · 장기 개선 과제
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

ST_CHECKING = '확인 중'
ST_FIXING = '수정 중'
ST_VERIFYING = '검증 중'
ST_DONE = '해결 완료'
ST_BLOCKED = '즉시 수정 불가'
ST_LONGTERM = '장기 개선 과제'

#: 자동 감지되는 이슈마다 조치 계획을 **미리** 적어 둔다.
#  왜 미리 적을 수 있나: 이 이슈들은 우리가 원인을 이미 아는 것들이다.
#  (모르는 문제에 대해 계획을 지어내지 않는다 — 그런 이슈는 '확인 중'으로 둔다)
PLAYBOOK = {
    'validation|high_conf_n': dict(
        # 라운드 394 — 종전 '(전체의 약 3%)' 는 날짜 없는 수라 낡았다(2026-09-30 실측 신호율 6.6%).
        #   이 칸은 다시 열릴 때 화면에 그대로 나가므로 날짜 없는 수를 두지 않는다.
        cause="60점 이상 신호가 드물어 블라인드 구간에서 쌓인 표본이 30건에 "
              "못 미칩니다.",
        user_impact="서비스 사용에는 지장이 없습니다. 다만 이 구간의 적중률을 "
                    "공식 성능으로 인정하지 않아, 화면에서 수치보다 '표본 부족'을 "
                    "먼저 보여 드립니다.",
        fixable_now=False,
        status=ST_BLOCKED,
        module='scripts/calibration_lab.py · 종목 유니버스 확장',
        action="종목 유니버스를 계속 넓혀 독립 사례를 축적합니다. 같은 종목·인접 "
               "기준일 반복은 25봉 간격 규칙으로 차단하므로 표본이 물리적으로 "
               "천천히 쌓입니다.",
        safeguard="표본 30건 미만인 동안에는 해당 적중률을 대표 성과로 표시하지 "
                  "않고, 매수권 판정에도 이 수치를 근거로 쓰지 않습니다.",
        target="1차 재평가 표본 30건 · 정식 판정 표본 100건",
        eta_days=30),
    # ⚠️ 라운드 394 — 이 칸들은 이슈가 열려 있으면 화면 '주요 이슈' 카드에 **그대로** 나간다(`issue_view` 가
    #   열린 이슈의 문구를 여기서 읽는다). 종전 원인 *"실전 구간은 횡보장이 많습니다"* 는 오늘 원장으로 재니
    #   사실이 아니었고(아래 수), 조치의 *"(보고서 상시 갱신)"* 도 아니었다 — 그 보고서를 다시 만드는 단계는
    #   워크플로에 없다. 잰 것과 날짜로 다시 적었다(§3 · 라운드 250 의 *재고 나면 문구도 같이 바뀐다*).
    'model|vb_gap': dict(
        cause="연습(검증) 구간과 실전(블라인드) 구간의 장세가 다릅니다. 매수권(60점+) "
              "판정 완료 기준으로 검증 구간에는 하락장이 거의 없고(0.2%) 실전 구간은 "
              "23.6%가 하락장이며, 하락장의 실전 적중이 45.8%로 가장 낮습니다. 다만 같은 "
              "국면끼리 견줘도 격차가 남습니다(상승장 65.2% vs 56.0% · 횡보장 81.8% vs "
              "59.3%) — 국면별 날짜가 12~38개뿐이라 크게 흔들리는 수입니다(2026-09-30 "
              "실측 · 오염 행을 뺀 통계 행 기준).",
        user_impact="실전 적중률이 연습보다 낮게 나옵니다. 화면에는 항상 낮은 쪽인 "
                    "실전 수치를 함께 표시하므로, 과대평가된 값을 보시지는 않습니다.",
        fixable_now=False,
        status=ST_LONGTERM,
        module='모델 성적 화면(국면×구간 표) · 반등 확인 사전등록 · 전방 재평가',
        action="국면×구간 성적은 모델 성적 화면에 늘 나눠 냅니다. 하락장을 겨눈 규칙"
               "(반등 확인)은 사전등록까지 했지만 하락장 에피소드가 검증 구간 0~3개 · 실전 "
               "구간 1~2개(코스피·코스닥)뿐이라 재지 못했습니다(2026-09-03 실측) — 새 "
               "하락장이 끝나야 표본이 늘고, 전방 "
               "재평가 때 국면 라우팅 판정과 함께 다시 셉니다. 기준을 낮춰 먼저 채택하지 "
               "않습니다.",
        safeguard="실전 수치를 홈 화면 첫 줄에 그대로 노출하고, 연습 수치만 "
                  "따로 강조하지 않습니다.",
        target="같은 국면끼리 비교했을 때의 잔여 격차 5%p 이내",
        # 같은 국면끼리 견주는 것은 전방 표본이 쌓여야 되므로 점검일은 전방 재평가일이다
        #   (라운드 162 가 이 이슈에 그렇게 정했다 · 날짜는 박제 파일 한 곳에서 읽는다)
        review_on='forward_eval',
        eta_days=21),
    'usability|signal_rate': dict(
        cause="원인을 다시 규명했습니다(2026-08-02 실측). 거부권 때문이 아니라 "
              "**점수 자체가 60점을 넘지 못하기 때문**입니다. 6,508건 중 70점 "
              "이상은 4건뿐이고, 60~64점 구간은 55~59점보다 오히려 성적이 "
              "나빴습니다(52.6% vs 59.3%) — 문턱을 올리는 방식으로는 풀 수 "
              "없다는 뜻입니다.",
        user_impact="매수 결론이 드물게 나옵니다. 기회를 놓칠 수 있지만, 근거 없는 "
                    "매수 신호를 보시는 것보다는 안전한 쪽입니다.",
        fixable_now=False,
        status=ST_LONGTERM,
        module='scripts/layer_study_r4.py · lift_study_r5.py · regime_rule_r6.py',
        # 라운드 423 — 종전 문구는 라운드 6 시점(블라인드 약세 15건 · 보류)에 멈춰 있었고 그 뒤 라운드 8 이
        #   참고 표시로 채택했다. 아래 목표(블라인드 약세 100건+)가 찬 뒤 같은 스크립트로 다시 재니 채택 기준 미달.
        action="점수 문턱을 낮추는 대신 국면 조건부 규칙을 사전등록 절차로 "
               "검정했습니다. 약세장 과매도 반등 규칙은 원장 7,947건 때 종목 "
               "홀드아웃을 통과해 참고 표시로만 채택했으나, 2026-10-03 원장 "
               "257,130행에서 같은 스크립트로 다시 재니 채택 기준(같은 국면 "
               "평균 대비 +5.0%p)에 못 미쳤습니다 — 종목 화면의 참고 카드는 "
               "그 사실을 적습니다.",
        safeguard="검정을 통과하지 못한 규칙은 운영에 넣지 않습니다. 문턱을 "
                  "낮춰 신호 수만 늘리는 일은 하지 않습니다.",
        target="블라인드 약세 표본 100건+ 축적 후 그 규칙 재판정",
        eta_days=45),
    'model|regime_dependence': dict(
        cause="적중률을 지배하는 것은 점수가 아니라 시장 국면입니다(실측). "
              "매수권 성적이 횡보장 검증 71.8%에서 하락장 블라인드 8.3%까지 "
              "벌어집니다.",
        user_impact="평균 적중률 한 줄만 보시면 오늘 상황에 잘못 적용하실 수 "
                    "있습니다. 그래서 홈 화면에 국면별 성적을 나눠 표시하고, "
                    "표본 30건 미만 구간은 성적으로 인정하지 않습니다.",
        fixable_now=True,
        status=ST_DONE,
        module='scripts/regime_breakdown_r7.py · web_app 국면별 성적',
        action="국면별 분해 수치를 원장에서 산출해 화면에 상시 노출합니다. "
               "산식·점수·게이트는 바꾸지 않았습니다.",
        safeguard="하락 추세 구간은 연습·실전이 크게 엇갈린다는 경고를 함께 "
                  "띄웁니다.",
        target="국면별 표본 각 100건+ 확보",
        eta_days=30),
    'model|overfit_gap': dict(
        cause="연습 구간에서 좋을수록 실전에서 더 크게 무너집니다(실측). "
              "후보 엔진 6개를 같은 데이터로 겨뤄 봤는데, 눌림 되돌림은 연습 "
              "67.0%로 1위였다가 실전 31.1%로 꼴찌였고, 로지스틱 회귀는 학습 "
              "1위(62.6%)였다가 실전 42.2%였습니다. 현행 엔진이 실전에서 "
              "가장 높습니다(56.1%) — 잘 맞혀서가 아니라 덜 무너져서입니다.",
        user_impact="적중률이 기대보다 낮게 보입니다. 다만 화면에는 항상 낮은 쪽인 "
                    "실전 수치를 함께 표시하므로, 부풀린 값을 보시지는 않습니다.",
        fixable_now=False,
        status=ST_LONGTERM,
        module='scripts/engine_bakeoff_r10.py · regime_breakdown_r7.py',
        action="알고리즘 교체로는 풀리지 않는다는 것이 실측으로 확인됐습니다. "
               "대신 ① 국면별 성적 분리 표시 ② 표본 확대(특히 하락장) "
               "③ 엔진 간 판단 불일치를 화면에 그대로 노출 — 세 가지를 합니다.",
        safeguard="후보 엔진은 어느 것도 판단에 반영하지 않습니다. 참고 표시만 "
                  "하고, 엇갈린다고 결론을 뒤집지 말라고 화면에 적었습니다.",
        target="블라인드 하락장 표본 100건+ 확보 후 국면 조건부 엔진 재판정",
        eta_days=60),
    'model|stop_width': dict(
        cause="손절 폭이 보유기간에 맞게 스케일되지 않았습니다. 20일 보유의 "
              "1σ 는 일간σ×√20 = 11.7% 인데 현행 손절은 5.25%(0.45σ)입니다.",
        user_impact="방향이 맞아도 먼저 손절에 닿는 경우가 있습니다. 다만 넓히면 "
                    "급락장에서 더 크게 잃어 지금은 바꾸지 않았습니다.",
        fixable_now=False,
        status=ST_LONGTERM,
        module='quant_indicators RULES_EXECUTION_LEVELS · scripts/stop_scaling_r9c.py',
        action="√기간 스케일링을 넣으면 학습 +1.3%p·검증 +3.2%p 이지만 "
               "블라인드가 -2.5%p 악화돼 사전등록을 통과하지 못했습니다. "
               "다음은 국면 조건부 손절 — 급락장에서는 좁게, 상승·횡보에서는 넓게.",
        safeguard="현행 산식 유지. 근거 없이 넓히지 않습니다.",
        target="국면 판정의 블라인드 성적이 먼저 개선될 것",
        eta_days=60),
    'model|validation_not_wired': dict(
        cause="모델 검증 결과가 매매 판단에 연결되는지 코드로 전수 감사한 결과 "
              "10개 항목 중 7개는 연결돼 있고 3개는 없습니다"
              "(scripts/validation_linkage_audit.py). 없는 것: ① 표본외 성과가 "
              "나쁜 전략의 가중치 하향 ② 국면별 성능이 낮은 엔진의 해당 장세 제한 "
              "③ 버전별 확률 개선 자동 비교.",
        user_impact="지금도 검증은 판단에 쓰입니다 — 점수대별 표본외 적중률이 "
                    "낮으면 상한이 걸리고, 표본이 모자라면 확률을 표시하지 "
                    "않습니다. 다만 국면별 엔진 제한이 없어 하락장에서 판단이 "
                    "더 자주 빗나갑니다.",
        fixable_now=False,
        status=ST_LONGTERM,
        module='quant_indicators · scripts/validation_linkage_audit.py',
        action="③ 버전별 비교는 이번에 만들었습니다(gen_version_compare.py). "
               "①②는 국면별 엔진 성과가 먼저 검증돼야 합니다 — 국면별 "
               "대결을 돌렸으나 채택 후보가 없었습니다. 근거 없이 "
               "가중치를 손대면 그게 곧 과최적화입니다.",
        safeguard="미연결 항목을 화면에 그대로 적었습니다 — '아직 연결되지 않은 "
                  "것도 있습니다'라고 판단 화면에서 밝힙니다.",
        target="국면별 엔진 성과가 블라인드에서 재현되면 ①② 연결",
        eta_days=45),
    'model|negative_edge': dict(
        cause="승률이 아니라 **손익비**가 문제입니다(2026-08-03 실측). 실전 승률 "
              "58.2%로 동전보다 8%p 높은데, 이길 때 +6.64% 벌고 질 때 −9.20% "
              "잃습니다(손익비(진입가·1차) 0.72:1). 그래서 기대값이 비용 "
              "차감 후 −0.28%로 "
              "마이너스입니다. 원인은 목표를 손절거리의 0.7배로 잡는 설계입니다 "
              "— 자주 닿지만 조금 먹으므로 구조적으로 기대값이 음수가 됩니다.",
        user_impact="지금 이 신호대로만 매매하면 평균적으로 손실입니다. 그래서 "
                    "화면에 '이 판단은 매수 신호가 아니라 참고'라고 적고, "
                    "국면별로 성적이 갈린다는 것을 먼저 보여 드립니다.",
        fixable_now=False,
        status=ST_LONGTERM,
        module='quant_indicators RULES_EXECUTION_LEVELS · scripts/rr_structure_r15.py',
        action="손익비(진입가·1차) k 를 0.7 → 1.3 이상으로 올리면 실전 "
               "기대값이 +0.15~+0.42%로 "
               "양수가 됩니다. 다만 목표 도달률이 54.6% → 12.1%로 떨어져 "
               "사전등록 기준(20%+)에 미달해 기각했습니다. 국면별로는 거친 "
               "상승장에서 k=1.3이 +4.46%로 압도적이라, 국면별 k를 별도 "
               "사전등록으로 검정합니다.",
        safeguard="근거 없이 목표를 바꾸지 않습니다. 기대값이 음수라는 사실을 "
                  "숨기지 않고 모델 성적 화면에 그대로 적습니다.",
        target="국면별 손익비(진입가·1차) 검정 — 거친 상승장 표본 200건+ "
               "확보 후 재판정",
        eta_days=30),
    # 라운드 421(2026-10-03) — 이 이슈가 적어 둔 재판정 조건(보합 블라인드 300건+)이 찼다(4,117건). 같은 생성기를 오늘
    #   원장의 통계 행으로 다시 돌리니 '보합이 가장 나쁘다'는 서지 않았다. 문구를 잰 사실로 바꾼다(상태는 사람이 바꾼다 · R256).
    'model|us_overnight': dict(
        cause="2026-08 초 원장(실전 142건)에서는 전날 미국장이 보합(±0.5%)인 날의 매수권 성적이 가장 나빴습니다. "
              "2026-10-03 원장(통계 행 · 판정 완료만 · 지수 매칭 100%)으로 다시 재니 보합은 학습(57.7%)·검증(57.2%)"
              "에서는 가장 낮지만 실전에서는 59.8%(3,712건)로 실전 전체(57.1%)보다 높습니다 — 세 구간에서 같은 답이 "
              "아닙니다. 실전 구간 표본은 날짜로 하락 15일 · 보합 29일 · 상승 14일뿐이라(시장 수준 값은 날짜가 "
              "표본입니다) 어느 구간이 나쁘다고 말할 수도 없습니다.",
        user_impact="화면은 보합인 날마다 '조심하라'는 경고를 고정으로 띄우던 것을 그만두고, 오늘 구간이 학습·검증·"
                    "실전 세 구간 모두에서 가장 낮을 때만 경고합니다. 평소에는 그 구간의 성적(운영 비용 차감 · 건수와 "
                    "날짜 수)과 '구간마다 가장 나쁜 칸이 다르다'는 사실을 적습니다.",
        fixable_now=True,
        status=ST_VERIFYING,
        module='scripts/us_overnight_r16.py · trust_view.us_overnight_card · web_app 어젯밤 미국장 카드',
        action="보합 구간을 게이트로 막으면 검증은 +1.41% 로 나아지지만 실전은 −1.06% 로 나빠지고 신호가 49% 로 "
               "줄어 사전등록(검증·실전 둘 다 개선 · 60% 유지) 미달입니다(2026-10-03 · 비용 0.30% 재현 규칙). "
               "게이트는 만들지 않습니다.",
        safeguard="게이트가 아니므로 판단 자체는 바뀌지 않습니다 — 사실만 적습니다.",
        target="실전 구간 날짜가 구간마다 30일을 넘을 때 같은 규칙으로 다시 잽니다(전방 구간이 날짜를 더합니다)",
        eta_days=30),
    'data|index_missing': dict(
        cause="지수 데이터 출처(네이버 금융)에서 응답을 받지 못했습니다.",
        # 라운드 426 — 종전 문구는 '미수신이면 매매 적합도 상한 59점이 걸린다 · 판단이 보수적으로 바뀐다'였다. 엔진에는
        #   그런 상한이 없다 — 지수를 못 받으면 시장 국면은 '판정 보류'가 되고, 시장 국면 점수는 그 항목을 빼고 다시
        #   세며(quant_indicators 의 시장 국면 산출), 지수 약세 상한(market_context.CONTEXT_CAPS['domestic_bear'])과
        #   국면별 제한(regime_policy.policy · *"국면을 판정하지 못해 국면별 제한을 걸지 않습니다"*)은 **빠진다.**
        user_impact="시장 국면 판정이 보류됩니다. 그동안 시장 국면 점수는 그 항목을 빼고 나머지로 다시 세고, "
                    "지수 국면에 거는 상한과 국면별 제한은 걸리지 않습니다 — 판단이 오히려 덜 보수적일 수 "
                    "있습니다. 못 받은 값을 지어내 채우지는 않습니다.",
        fixable_now=True,
        status=ST_FIXING,
        module='bitemporal_engine.get_index_regime',
        action="재조회 후에도 실패하면 국면 판정을 '보류'로 두고, 지어낸 값으로 채우지 않습니다.",
        safeguard="못 받은 지수를 50점으로 채우지 않고, 판정 보류 상태를 화면에 적습니다.",
        target="다음 조회 성공 시 자동 해소",
        eta_days=1),
    # ── 라운드 17~21 (2026-08-04) 실행 레벨 전면 재조사에서 나온 것 ──
    'model|score_not_separating': dict(
        cause="점수는 여러 관점의 가중합에 게이트 상한을 씌운 값인데, 그 조합이 "
              "20거래일 목표·손절 선도달과 상관을 갖는지 한 번도 직접 검정된 적이 "
              "없습니다. 그래서 처음으로 직접 쟀고, 상관이 확인되지 않았습니다 — "
              "매수권(58+)과 나머지의 거래당 기대값 차이가 학습 -0.01%p · "
              "검증 -0.03%p 로 사실상 0 입니다(2026-08-04 실측).",
        user_impact="점수를 '높을수록 좋은 신호'로 읽으시면 안 됩니다. 화면에서 "
                    "점수와 함께 '이 점수대의 표본외 실측'을 항상 병기하며, 그 "
                    "수치가 점수 순서를 따르지 않는다는 점을 밝힙니다.",
        fixable_now=False,
        status=ST_CHECKING,
        module='quant_engine.py 점수 산식 · scripts/does_score_work_r20.py',
        # ⚠️ 라운드 394 — 종전 이 칸은 ①②③ 을 **앞으로 할 일**로 적고 있었는데 ①② 는 2026-08-16 에 했고
        #   결과는 음성이었다(그 결과는 등록부의 다른 칸에만 붙어 화면에는 안 나갔다). 이슈가 열려 있어
        #   화면에 그대로 나가므로 한 것과 남은 것을 가른다(§3 · 라운드 250).
        action="①② 했습니다 — 종합점수와 하위점수 7종, 8개를 같은 날·짝비교로 하나씩 "
               "재니 전부 기준 미달이었고, 업종 안 순위·자기 이력 대비로 바꾼 16개도 전부 "
               "미달이었습니다(2026-08-16 · 개발 구간 166,132건). 점수를 쪼개거나 다시 "
               "조합해서는 같은 날 종목을 가르지 못한다는 뜻입니다. 남은 ③ 은 점수를 "
               "'매수 신호'가 아니라 '점검표'로 읽게 하는 일입니다 — 화면은 점수 띠 옆에 "
               "그 띠의 블라인드 적중을 적고 '더 잘 맞는다는 뜻이 아니다'를 같이 씁니다.",
        safeguard="분리력이 확인되기 전까지 점수만으로 매수를 권하지 않습니다. "
                  "화면의 결론은 계속 거부권·게이트가 먼저 판단합니다.",
        target="구성요소 중 학습·검증 양쪽에서 lift>0 인 것 1개 이상 확인",
        eta_days=57),
    'data|ledger_path_window': dict(
        cause="grade_prediction 이 의도적으로 청산 봉까지만 mfe/mae 를 재기 "
              "때문입니다 — 손절 뒤 반등을 성과로 세지 않으려는 옳은 설계입니다. "
              "문제는 연구 코드가 그 전제를 모른 채 20일 종가수익과 섞어 쓴 "
              "것입니다. 그 탓에 재시뮬레이션 한 벌이 통째로 무효가 됐습니다.",
        user_impact="화면 수치에는 영향이 없습니다. 채점 방식은 그대로이고, "
                    "잘못된 것은 연구용 재시뮬레이션이었습니다.",
        fixable_now=True,
        status=ST_FIXING,
        module='scripts/enrich_paths_r17d.py · scripts/exec_sim.py',
        action="경로 전체(20봉 고·저·종)를 별도 파일로 남기고 재시뮬레이터가 "
               "그것만 쓰도록 했습니다(현행 판정 일치율 99.99%). 남은 일은 신규 "
               "케이스가 쌓일 때 경로도 함께 남도록 축적 파이프라인에 연결하는 "
               "것입니다.",
        safeguard="실행 레벨 연구는 exec_sim 만 사용합니다.",
        target="신규 케이스 축적 시 경로 자동 기록 · 재시뮬 일치율 99% 이상 유지",
        eta_days=16),
    'usability|loss_control_tradeoff': dict(
        cause="손절을 좁히면 흔들림에 먼저 털려 목표 도달 기회를 잃습니다. "
              "손실 통제와 기대값은 맞바꾸는 관계입니다 — 공짜 개선이 아닙니다.",
        # 라운드 293 (2026-09-15) — 재검토일에 사람이 **(a) 노출**을 골랐다.
        #   종전 이 칸은 *"지금은 화면에 노출하지 않습니다"* 였고 그것은 이제 거짓이다
        #   (R250 — 재고 나면 화면 문구도 같이 바뀐다). 그리고 종전의 **11%p** 는
        #   라운드 21 표본(학습 17,265 · 검증 1,576) 시절 값이다 — 라운드 258 이 지금
        #   원장(경로 있는 매수권 6,085건)으로 다시 재니 **구간별 10~15%p** 다.
        user_impact="실행 가격 카드에 '손절 폭 좁게' 선택지로 노출합니다. 기본은 "
                    "현행이고, 켜면 보유자 손절 한 칸만 좁아집니다. 대가(목표 "
                    "도달률 구간별 10~15%p 하락)는 켜든 안 켜든 같은 카드에 "
                    "항상 적습니다 — 켜야 보이는 것이 아닙니다.",
        fixable_now=True,
        status=ST_CHECKING,
        module='화면 — 실행 가격 카드',
        action="노출했습니다(2026-09-15 결정). 배수는 verdict_core 한 곳에서만 "
               "보유자 손절에 걸고, 판정·점수·게이트·신규 매수자 값에는 넣지 "
               "않습니다. 대가 문장은 실측 산출물에서 그 자리에서 만듭니다.",
        safeguard="기본값은 바꾸지 않습니다(사전등록 기준 미달 · 기각 그대로). "
                  "대가를 적지 않고 '손실이 줄어든다'만 쓰지 않습니다.",
        target="노출 여부 결정 · 노출 시 대가 표기 동반",
        eta_days=42),
}


def _today():
    """등록부의 '오늘' — **지역 날짜**다. 이 자리가 유일한 정의다 (라운드 306).

    ⚠️ 종전에는 `datetime.now(timezone.utc).date()` 였다. 그런데 이 등록부에 적히는
    날짜(`next_review`·`eta`)는 사람이 KST 로 정한 날이고, **닫는 쪽**
    (`issue_tracker.resolve_by_key` · 라운드 256)은 이미 지역 날짜로 견주고 있었다 —
    **한 등록부에 '오늘'이 둘이었다.**

    어긋나는 창은 **KST 00:00~09:00**(UTC 로는 전날)이다. 그래서 낮에 돌리면 안 보이고
    자정 직후에만 보인다 — 실제로 2026-09-16 00시대에 전체 회귀가 처음 잡았다
    (재검토일 09-15 인 이슈를 화면이 *"다음 점검 2026-09-15"* 라 적었고, 지역 날짜로는
    **1일 지남**이었다). 라운드 222 가 SQLite `date('now')` 에서, 라운드 283 이 꼬리
    검사에서 고친 **그 자리**다 — *검사의 '오늘'은 사건의 날이 아니다.*
    """
    return datetime.now(timezone.utc).astimezone().date()


def ensure_schema(conn: sqlite3.Connection) -> None:
    """이슈 테이블에 조치 관리 열을 더한다 (기존 데이터 보존)."""
    cols = {r[1] for r in conn.execute(
        "PRAGMA table_info(improvement_issues)").fetchall()}
    add = {
        'cause': 'TEXT', 'user_impact': 'TEXT', 'fixable_now': 'INTEGER',
        'work_status': 'TEXT', 'module': 'TEXT', 'action_plan': 'TEXT',
        'safeguard': 'TEXT', 'target': 'TEXT', 'eta': 'TEXT',
        'resolved_version': 'TEXT', 'verification': 'TEXT',
        'next_review': 'TEXT', 'escalated_at': 'TEXT',
    }
    for c, t in add.items():
        if c not in cols:
            try:
                conn.execute(
                    f"ALTER TABLE improvement_issues ADD COLUMN {c} {t}")
            except Exception:
                pass
    conn.commit()


def apply_playbook(conn: sqlite3.Connection, issue_key: str,
                   version: str = '') -> None:
    """이슈에 미리 정해 둔 조치 계획을 붙인다 (없으면 '확인 중'으로 둔다)."""
    pb = PLAYBOOK.get(issue_key)
    row = conn.execute(
        "SELECT issue_id, created_at FROM improvement_issues "
        "WHERE issue_key=? AND status='open'", (issue_key,)).fetchone()
    if not row:
        return
    if not pb:
        conn.execute(
            "UPDATE improvement_issues SET work_status=?, "
            "cause=COALESCE(cause,'원인 조사 중'), "
            "user_impact=COALESCE(user_impact,'영향 평가 중') "
            "WHERE issue_id=?", (ST_CHECKING, row['issue_id']))
        conn.commit()
        return
    eta = (_today() + timedelta(days=int(pb['eta_days']))).isoformat()
    # 라운드 394 — 전방 표본이 있어야 목표를 잴 수 있는 이슈는 점검일이 전방 재평가일이다(라운드 162 가
    #   괴리 이슈에 손으로 정한 것을 규칙으로). 날짜는 박제 파일 한 곳에서 읽고 못 읽으면 종전 규칙(§3).
    if pb.get('review_on') == 'forward_eval':
        try:
            import forward_eval as _fe394
            _d394 = str(_fe394.eval_date() or '')[:10]
            if _d394:
                eta = _d394
        except Exception:                                      # noqa: BLE001
            pass
    conn.execute(
        """
        UPDATE improvement_issues
        SET cause=?, user_impact=?, fixable_now=?, work_status=?, module=?,
            action_plan=?, safeguard=?, target=?,
            eta=COALESCE(eta, ?), next_review=COALESCE(next_review, ?)
        WHERE issue_id=?
        """,
        (pb['cause'], pb['user_impact'], int(bool(pb['fixable_now'])),
         pb['status'], pb['module'], pb['action'], pb['safeguard'],
         pb['target'], eta, eta, row['issue_id']))
    conn.commit()


def escalate(conn: sqlite3.Connection) -> list:
    """
    경과일 규칙 — 1일 계획 / 2일 재평가 / 3일 강제 조치.
    3일이 지났는데 설명이 없으면 자동으로 '장기 개선 과제'로 전환하고
    다음 검토일을 새로 잡는다. 같은 경고만 반복 노출하는 것을 막는다.
    """
    out = []
    for r in conn.execute(
            "SELECT * FROM improvement_issues WHERE status='open'").fetchall():
        try:
            born = datetime.fromisoformat(str(r['created_at'])).date()
        except Exception:
            continue
        age = (_today() - born).days
        ws = r['work_status'] or ST_CHECKING
        new_ws, note = ws, None
        if age >= 3 and ws in (ST_CHECKING, ST_FIXING):
            # 3일 규칙 — 아직 못 고쳤으면 성격을 분명히 한다
            new_ws = (ST_BLOCKED if not (r['fixable_now'] or 0)
                      else ST_LONGTERM)
            note = (f"{age}일 경과 — 즉시 해결되지 않아 성격을 다시 분류했습니다. "
                    "임시 안전조치는 유지되며, 다음 검토일에 재평가합니다.")
        elif age >= 2 and ws == ST_CHECKING:
            new_ws = ST_FIXING
            note = f"{age}일 경과 — 조치 단계로 올렸습니다."
        if new_ws != ws or note:
            nxt = (_today() + timedelta(days=7)).isoformat()
            conn.execute(
                "UPDATE improvement_issues SET work_status=?, next_review=?, "
                "escalated_at=?, verification=COALESCE(verification,?) "
                "WHERE issue_id=?",
                (new_ws, nxt, datetime.now(timezone.utc).isoformat(),
                 note, r['issue_id']))
            out.append({'key': r['issue_key'], 'age': age, 'to': new_ws})
    conn.commit()
    return out


def issue_view(conn: sqlite3.Connection, limit: int = 20) -> list:
    """화면용 — 조치 정보까지 포함한 이슈 목록 (경과일 계산 포함).

    ⚠️ 라운드 172 — **화면이 원장과 다른 말을 하고 있었다.** 해결된 이슈
       3건이 전부 진행 중처럼 나왔고, 그중 하나는 *"장기 개선 과제 ·
       20일 경과 · **즉시 수정 가능** · 다음 점검 2026-08-15"* 였다 —
       그 날짜는 **10일 지난 날**이다. 회귀는 초록불이었다.

       원인은 **닫는 길이 넷인데 하나만 `work_status` 를 같이 고쳤다**는
       것이다(`resolve_with_verification` 만). 나머지 셋
       (`issue_tracker.resolve_issue` · `resolve_by_key` ·
       `scripts/close_issue_mfe.py`)은 `status` 만 바꾼다.

       → **쓰는 쪽을 넷 다 고치지 않는다.** 읽는 쪽이 `status` 를 먼저
         보게 한다 — 그러면 앞으로 어느 길로 닫혀도 화면이 안 어긋난다.
         (호출부 말고 기본값을 바꾼다 — 라운드 120e 와 같은 자리.)

       여기서 **화면 문구까지 만들어 돌려준다.** 화면이 조립하면 조립
       규칙이 또 두 곳에 생긴다 (§4).
    """
    rows = conn.execute(
        """
        SELECT * FROM improvement_issues
        ORDER BY CASE status WHEN 'open' THEN 0 ELSE 1 END,
                 CASE severity WHEN 'critical' THEN 1 WHEN 'high' THEN 2
                               WHEN 'medium' THEN 3 ELSE 4 END,
                 created_at DESC
        LIMIT ?
        """, (limit,)).fetchall()
    out = []
    for r in rows:
        try:
            age = (_today() - datetime.fromisoformat(
                str(r['created_at'])).date()).days
        except Exception:
            age = 0
        d = {k: r[k] for k in r.keys()}
        # 라운드 394 — **열린** 이슈의 원인·영향·조치·목표 문구는 PLAYBOOK(코드) 한 곳에서 읽는다. 등록부
        #   칸은 `apply_playbook` 이 그날 적어 둔 **복사본**이고, 매일 다시 적는 키는 넷뿐이라 나머지는
        #   코드가 고쳐져도 옛 문장을 안고 있었다 — 실측(2026-09-30): 손절 노출 이슈는 2026-09-15 에
        #   노출했는데 등록부 칸은 *"선택지로 노출할지 검토합니다"* 그대로였고, 점수 분리 이슈는 08-16 에 한
        #   ①② 를 *앞으로 할 일*로 적고 있었다. 닫힌 이슈는 등록부 칸 그대로 둔다(그때의 이력이다).
        #   열쇠 뒤의 `@<id>`(라운드 394 · 닫힌 행의 이력 표시)는 떼고 찾는다.
        _pb = PLAYBOOK.get(str(d.get('issue_key') or '').split('@')[0])
        if _pb and str(d.get('status') or '') == 'open':
            d.update(cause=_pb['cause'], user_impact=_pb['user_impact'],
                     action_plan=_pb['action'], safeguard=_pb['safeguard'],
                     target=_pb['target'], module=_pb['module'])
        d['age_days'] = age
        d['stale'] = (age >= 3 and (r['status'] == 'open')
                      and not (r['work_status'] or '').startswith(
                          (ST_BLOCKED, ST_LONGTERM, ST_DONE)))
        d.update(_display_fields(d, age))
        out.append(d)
    return out


def _display_fields(d: dict, age: int) -> dict:
    """화면이 그대로 찍을 문구. **`status` 가 우선이다** (라운드 172).

    돌려주는 것 넷:
      `state_label`  배지 — 해결분은 무조건 '해결 완료'
      `age_label`    '20일 경과' / '18일 만에 해결'
      `fix_label`    '즉시 수정 가능' 류. 해결분은 `None` (붙이지 않는다)
      `review_label` '다음 점검 …' / '점검 예정일 … · N일 지남'.
                     해결분은 `None`
    """
    resolved = str(d.get('status') or '') == 'resolved'
    ws = str(d.get('work_status') or '') or ST_CHECKING

    if resolved:
        # 해결까지 **얼마나 걸렸나** — 지금도 자라는 경과일이 아니다.
        took = None
        try:
            took = (datetime.fromisoformat(str(d['resolved_at'])).date()
                    - datetime.fromisoformat(str(d['created_at'])).date()).days
        except Exception:                                      # noqa: BLE001
            took = None
        # 라운드 422 — 닫힌 행의 원인 칸은 그때의 복사본이다(위 issue_view 주석). '왜 생겼나'로 그리면 지금의 사실로 읽힌다
        #   — 실측(2026-10-03): 닫힌 행이 *"60점 이상 신호는 전체의 약 3%"* 를 적는데 같은 홈 타일은 6.6% 였다. 이름에 기간을 붙인다.
        _c0, _c1 = str(d.get('created_at') or '')[:10], str(d.get('resolved_at') or '')[:10]
        return {
            'state_label': ST_DONE,
            'age_label': (f'{took}일 만에 해결' if took is not None
                          else '해결 완료'),
            'fix_label': None,
            'review_label': None,
            'cause_label': (f'당시 원인 ({_c0}~{_c1})' if (_c0 and _c1) else '당시 원인'),
        }

    # 아직 열려 있다 — 점검일이 지났으면 **지났다고 적는다** (§3)
    raw = str(d.get('next_review') or d.get('eta') or '')[:10]
    review = None
    if raw:
        try:
            due = datetime.fromisoformat(raw).date()
            late = (_today() - due).days
            review = (f'점검 예정일 {raw} · {late}일 지남' if late > 0
                      else f'다음 점검 {raw}')
        except Exception:                                      # noqa: BLE001
            review = f'다음 점검 {raw}'
    return {
        'state_label': ws,
        'age_label': f'{age}일 경과',
        'fix_label': ('즉시 수정 가능' if d.get('fixable_now')
                      else '지금은 즉시 해결 불가'),
        'review_label': review,
        'cause_label': '왜 생겼나',
    }


def resolve_with_verification(conn: sqlite3.Connection, issue_key: str, *,
                              version: str, verification: str) -> None:
    conn.execute(
        "UPDATE improvement_issues SET status='resolved', work_status=?, "
        "resolved_at=?, resolved_version=?, verification=? "
        "WHERE issue_key=? AND status='open'",
        (ST_DONE, datetime.now(timezone.utc).isoformat(), version,
         verification, issue_key))
    conn.commit()
