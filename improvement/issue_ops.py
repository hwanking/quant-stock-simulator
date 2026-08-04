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
        cause="60점 이상 신호 자체가 드물어(전체의 약 3%) 블라인드 구간에서 "
              "쌓인 표본이 30건에 못 미칩니다.",
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
    'model|vb_gap': dict(
        cause="연습(검증) 구간과 실전(안 본) 구간의 장세가 다릅니다. 검증 구간은 "
              "상승장 비중이 높고 실전 구간은 횡보장이 많습니다.",
        user_impact="실전 적중률이 연습보다 낮게 나옵니다. 화면에는 항상 낮은 쪽인 "
                    "실전 수치를 함께 표시하므로, 과대평가된 값을 보시지는 않습니다.",
        fixable_now=False,
        status=ST_LONGTERM,
        module='scripts/blind_gap_analysis.py · 국면 조건부 게이트',
        action="국면별로 분해해 어느 장세에서 무너지는지 추적하고(보고서 상시 갱신), "
               "국면 조건부 임계값을 사전등록 절차로 실험합니다.",
        safeguard="실전 수치를 홈 화면 첫 줄에 그대로 노출하고, 연습 수치만 "
                  "따로 강조하지 않습니다.",
        target="같은 국면끼리 비교했을 때의 잔여 격차 5%p 이내",
        eta_days=21),
    'usability|signal_rate': dict(
        cause="원인을 다시 규명했습니다(라운드 3~4 실측). 거부권 때문이 아니라 "
              "**점수 자체가 60점을 넘지 못하기 때문**입니다. 6,508건 중 70점 "
              "이상은 4건뿐이고, 60~64점 구간은 55~59점보다 오히려 성적이 "
              "나빴습니다(52.6% vs 59.3%) — 문턱을 올리는 방식으로는 풀 수 "
              "없다는 뜻입니다.",
        user_impact="매수 결론이 드물게 나옵니다. 기회를 놓칠 수 있지만, 근거 없는 "
                    "매수 신호를 보시는 것보다는 안전한 쪽입니다.",
        fixable_now=False,
        status=ST_LONGTERM,
        module='scripts/layer_study_r4.py · lift_study_r5.py · regime_rule_r6.py',
        action="점수 문턱을 낮추는 대신 국면 조건부 규칙을 사전등록 절차로 "
               "검정하고 있습니다. 라운드 6에서 약세장 과매도 반등 규칙이 종목 "
               "홀드아웃(본 적 없는 종목 174건, +7.4%p)을 통과했으나 블라인드 "
               "약세 표본이 15건뿐이라 채택을 보류했습니다.",
        safeguard="검정을 통과하지 못한 규칙은 운영에 넣지 않습니다. 문턱을 "
                  "낮춰 신호 수만 늘리는 일은 하지 않습니다.",
        target="블라인드 약세 표본 100건+ 축적 후 라운드 6 규칙 재판정",
        eta_days=45),
    'model|regime_dependence': dict(
        cause="적중률을 지배하는 것은 점수가 아니라 시장 국면입니다(라운드 7). "
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
        cause="연습 구간에서 좋을수록 실전에서 더 크게 무너집니다(라운드 10 실측). "
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
               "①②는 국면별 엔진 성과가 먼저 검증돼야 합니다 — 라운드 12에서 "
               "국면별 대결을 돌렸으나 채택 후보가 없었습니다. 근거 없이 "
               "가중치를 손대면 그게 곧 과최적화입니다.",
        safeguard="미연결 항목을 화면에 그대로 적었습니다 — '아직 연결되지 않은 "
                  "것도 있습니다'라고 판단 화면에서 밝힙니다.",
        target="국면별 엔진 성과가 블라인드에서 재현되면 ①② 연결",
        eta_days=45),
    'model|negative_edge': dict(
        cause="승률이 아니라 **손익비**가 문제입니다(라운드 15 실측). 실전 승률 "
              "58.2%로 동전보다 8%p 높은데, 이길 때 +6.64% 벌고 질 때 −9.20% "
              "잃습니다(손익비 0.72:1). 그래서 기대값이 비용 차감 후 −0.28%로 "
              "마이너스입니다. 원인은 목표를 손절거리의 0.7배로 잡는 설계입니다 "
              "— 자주 닿지만 조금 먹으므로 구조적으로 기대값이 음수가 됩니다.",
        user_impact="지금 이 신호대로만 매매하면 평균적으로 손실입니다. 그래서 "
                    "화면에 '이 판단은 매수 신호가 아니라 참고'라고 적고, "
                    "국면별로 성적이 갈린다는 것을 먼저 보여 드립니다.",
        fixable_now=False,
        status=ST_LONGTERM,
        module='quant_indicators RULES_EXECUTION_LEVELS · scripts/rr_structure_r15.py',
        action="손익비 k를 0.7 → 1.3 이상으로 올리면 실전 기대값이 +0.15~+0.42%로 "
               "양수가 됩니다. 다만 목표 도달률이 54.6% → 12.1%로 떨어져 "
               "사전등록 기준(20%+)에 미달해 기각했습니다. 국면별로는 거친 "
               "상승장에서 k=1.3이 +4.46%로 압도적이라, 국면별 k를 별도 "
               "사전등록으로 검정합니다.",
        safeguard="근거 없이 목표를 바꾸지 않습니다. 기대값이 음수라는 사실을 "
                  "숨기지 않고 모델 성적 화면에 그대로 적습니다.",
        target="국면별 손익비 검정 — 거친 상승장 표본 200건+ 확보 후 재판정",
        eta_days=30),
    'model|us_overnight': dict(
        cause="전날 미국장이 **보합(±0.5%)** 인 날의 추천 성적이 가장 나쁩니다 "
              "(라운드 16 실측): 검증 47.6%·−1.18% / 실전 46.5%·−0.66%. "
              "반대로 미국이 확실히 오르거나(+0.5~+2%) 내린 날(−2~−0.5%)은 "
              "65~71%로 좋습니다. 미국이 방향을 정하지 못하면 한국은 방향 없이 "
              "흔들린다는 뜻입니다.",
        user_impact="보합인 다음날에도 매수 결론이 나올 수 있습니다. 그래서 "
                    "홈 화면 상단에 '어젯밤 미국장이 보합이었습니다 — 오늘은 "
                    "특히 조심하세요' 경고를 띄웁니다.",
        fixable_now=True,
        status=ST_VERIFYING,
        module='scripts/us_overnight_r16.py · web_app 전날 미국장 경고',
        action="보합 구간을 게이트로 막으면 검증 +0.87%·실전 +0.11%로 둘 다 "
               "양수가 되지만 신호가 49%로 줄어 사전등록(60% 유지) 미달입니다. "
               "게이트 대신 경고로 넣었고, 표본이 더 쌓이면 게이트를 재판정합니다.",
        safeguard="게이트가 아니므로 판단 자체는 바뀌지 않습니다 — 사용자가 "
                  "직접 조심할 수 있게 사실만 알립니다.",
        target="보합 구간 블라인드 표본 300건+ 확보 후 게이트 재판정",
        eta_days=30),
    'data|index_missing': dict(
        cause="지수 데이터 출처(네이버 금융)에서 응답을 받지 못했습니다.",
        user_impact="시장 국면 판정이 보류되고, 매매 적합도에 상한이 걸립니다. "
                    "판단이 보수적으로 바뀔 뿐 잘못된 값을 쓰지는 않습니다.",
        fixable_now=True,
        status=ST_FIXING,
        module='bitemporal_engine.get_index_regime',
        action="재조회 후에도 실패하면 국면 판정을 '보류'로 두고 상한 게이트를 "
               "유지합니다. 지어낸 값으로 채우지 않습니다.",
        safeguard="미수신 동안 매매 적합도 상한 59점 자동 적용.",
        target="다음 조회 성공 시 자동 해소",
        eta_days=1),
    # ── 라운드 17~21 (2026-08-04) 실행 레벨 전면 재조사에서 나온 것 ──
    'model|score_not_separating': dict(
        cause="점수는 여러 관점의 가중합에 게이트 상한을 씌운 값인데, 그 조합이 "
              "20거래일 목표·손절 선도달과 상관을 갖는지 한 번도 직접 검정된 적이 "
              "없습니다. 라운드 20 이 처음 재 봤고, 상관이 확인되지 않았습니다 — "
              "매수권(58+)과 나머지의 거래당 기대값 차이가 학습 -0.01%p · "
              "검증 -0.03%p 로 사실상 0 입니다.",
        user_impact="점수를 '높을수록 좋은 신호'로 읽으시면 안 됩니다. 화면에서 "
                    "점수와 함께 '이 점수대의 표본외 실측'을 항상 병기하며, 그 "
                    "수치가 점수 순서를 따르지 않는다는 점을 밝힙니다.",
        fixable_now=False,
        status=ST_CHECKING,
        module='quant_engine.py 점수 산식 · scripts/does_score_work_r20.py',
        action="① 가중합 이전의 구성요소별로 결과와의 상관을 개별 측정합니다. "
               "② 상관이 없는 구성요소를 가중치에서 빼는 안을 사전등록 검정합니다. "
               "③ 그래도 분리되지 않으면 점수를 '매수 신호'가 아니라 '점검 "
               "체크리스트'로 화면에서 재정의합니다.",
        safeguard="분리력이 확인되기 전까지 점수만으로 매수를 권하지 않습니다. "
                  "화면의 결론은 계속 거부권·게이트가 먼저 판단합니다.",
        target="구성요소 중 학습·검증 양쪽에서 lift>0 인 것 1개 이상 확인",
        eta_days=57),
    'data|ledger_path_window': dict(
        cause="grade_prediction 이 의도적으로 청산 봉까지만 mfe/mae 를 재기 "
              "때문입니다 — 손절 뒤 반등을 성과로 세지 않으려는 옳은 설계입니다. "
              "문제는 연구 코드가 그 전제를 모른 채 20일 종가수익과 섞어 쓴 "
              "것입니다. 라운드 17 이 그렇게 통째로 무효가 됐습니다.",
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
        user_impact="지금은 화면에 노출하지 않습니다. 노출한다면 '손실을 줄이는 "
                    "대신 목표 도달이 11%p 줄어든다'를 같은 카드에 함께 적습니다.",
        fixable_now=False,
        status=ST_CHECKING,
        module='화면 — 실행 가격 카드',
        action="선택지로 노출할지 검토합니다. 노출 시 기본값은 현행을 유지하고, "
               "사용자가 고른 경우에만 좁은 손절을 적용합니다.",
        safeguard="기본값은 바꾸지 않습니다(사전등록 기준 미달). 대가를 적지 "
                  "않고 '손실이 줄어든다'만 쓰지 않습니다.",
        target="노출 여부 결정 · 노출 시 대가 표기 동반",
        eta_days=42),
}


def _today():
    return datetime.now(timezone.utc).date()


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
    """화면용 — 조치 정보까지 포함한 이슈 목록 (경과일 계산 포함)."""
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
        d['age_days'] = age
        d['stale'] = (age >= 3 and (r['status'] == 'open')
                      and not (r['work_status'] or '').startswith(
                          (ST_BLOCKED, ST_LONGTERM, ST_DONE)))
        out.append(d)
    return out


def resolve_with_verification(conn: sqlite3.Connection, issue_key: str, *,
                              version: str, verification: str) -> None:
    conn.execute(
        "UPDATE improvement_issues SET status='resolved', work_status=?, "
        "resolved_at=?, resolved_version=?, verification=? "
        "WHERE issue_key=? AND status='open'",
        (ST_DONE, datetime.now(timezone.utc).isoformat(), version,
         verification, issue_key))
    conn.commit()
