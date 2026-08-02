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
