# -*- coding: utf-8 -*-
"""
제품 운영 계층 — 업데이트 내역(카테고리 분류)과 주요 이슈(실데이터 파생).

원칙 (docs/REDESIGN_BRIEF_v4_ko.md):
  · 업데이트 = 그동안 바뀐 것. 원천은 git 커밋 로그 — 손으로 쓰지 않는다.
    카테고리는 제목 낱말 규칙으로만 분류한다 (내용 재작성 금지).
  · 이슈 = 지금 중요한 것. **이미 계산된 실측·실경고에서만** 만든다 —
    새 판단이나 예측 문장을 생성하지 않는다 (날조 금지).
"""
from __future__ import annotations

from datetime import datetime

# ── 업데이트 카테고리 — 커밋 제목 낱말 규칙 (순서 = 우선순위) ─────────────
UPDATE_CATEGORIES = [
    ('버그 수정', ['수정', '버그', '오류', 'TypeError', '폭탄', '죽던', '깨지']),
    ('케이스 스터디', ['케이스', '리플레이', '원장', '캘리브레이션', '표본']),
    ('뉴스 분석', ['뉴스', '공시', '후행', '컨텍스트']),
    ('추천 로직', ['추천', '개장 전', '게이트', '스캔', '관심종목']),
    ('모델', ['모델', '점수', '판정', '적정가', 'DeMARK', '블라인드', '검증',
            '손절', '기하', '모멘텀', '산식', '벤치마크']),
    ('데이터', ['데이터', '시세', '출처', '수집', '평단가', 'OCR', '인식',
             '붙여넣기', '엑셀', '배당']),
    ('UI/UX', ['UI', '디자인', '라이트', '다크', '테마', '차트', '탭', '카드',
             '내비게이션', '화면', '위계', '재설계', '토큰', '이모지', '히스토리']),
    ('성능 개선', ['성능', '캐시', '속도']),
]


def classify_update_category(subject):
    """커밋 제목 → 카테고리. 규칙에 안 걸리면 '기타'."""
    s = str(subject or '')
    for cat, words in UPDATE_CATEGORIES:
        if any(w in s for w in words):
            return cat
    return '기타'


def enrich_update_history(history):
    """update_history.json 구조에 카테고리·버전 표기를 입힌다 (원문 불변)."""
    out = []
    for day in (history or {}).get('days', []):
        d = str(day.get('date', ''))
        ver = 'v' + d[2:].replace('-', '.') if len(d) == 10 else ''
        items = [{
            **it,
            'category': classify_update_category(it.get('subject')),
        } for it in day.get('items', [])]
        out.append({'date': d, 'version': ver, 'items': items})
    return out


# ── 주요 이슈 — 실측·실경고에서만 파생 ────────────────────────────────────
_SEV_ORDER = {'높음': 0, '중간': 1, '낮음': 2}


def _issue(kind, sev, title, detail, scope='전체'):
    return {'type': kind, 'severity': sev, 'title': str(title)[:80],
            'detail': str(detail)[:200], 'scope': scope,
            'created': datetime.now().strftime('%Y-%m-%d %H:%M')}


def build_global_issues(calib, market_ctx=None):
    """
    전역 이슈 — calibration.json 실측과 시장 컨텍스트 실측에서만 만든다.
    반환: 중요도순 이슈 목록 (각: type/severity/title/detail/scope/created)
    """
    issues = []
    c = calib or {}
    sp = c.get('splits') or {}
    v, b = sp.get('valid') or {}, sp.get('blind') or {}
    bz = (sp.get('buy_zone') or {}).get('blind') or {}

    if (bz.get('n') or 0) < 30:
        issues.append(_issue(
            '모델', '높음',
            f"고신뢰(60점+) 신호 표본 부족 경고 유지 (n={bz.get('n', 0)})",
            f"블라인드 고신뢰 적중률 {bz.get('hit_rate', 0):.0f}%는 표본이 적어 "
            "확정 성능으로 인정하지 않습니다. 30건까지는 참고만 하세요."))
    if (v.get('hit_rate') is not None and b.get('hit_rate') is not None
            and v['hit_rate'] - b['hit_rate'] >= 10):
        issues.append(_issue(
            '모델', '높음',
            f"검증({v['hit_rate']:.1f}%)-블라인드({b['hit_rate']:.1f}%) 괴리 감시 중",
            "장세 변화·과최적화 가능성을 조사하고 있습니다 — 상세: "
            "docs/BLIND_GAP_REPORT.md. 블라인드 개선이 최우선 과제입니다."))
    sig = c.get('signal_frequency') or {}
    if sig.get('rate_pct') is not None and sig['rate_pct'] < 5:
        issues.append(_issue(
            '추천', '중간',
            f"매수권 신호율 {sig['rate_pct']:.1f}% — 선별이 매우 엄격합니다",
            f"전체 {sig.get('total', 0)}건 중 {sig.get('buy_zone', 0)}건만 매수권. "
            "기회가 드문 대신 표본 축적이 느립니다 — 우연 적중 위험을 함께 점검합니다."))

    m = market_ctx or {}
    if m.get('regime_label') and '약세' in str(m.get('regime_label')):
        issues.append(_issue(
            '시장', '중간',
            f"국내 시장 국면: {m['regime_label']}",
            "약세 국면에서는 종목 점수가 좋아도 최종 점수에 상한이 걸립니다.",
            scope=str(m.get('market', '국내'))))
    if m.get('index_missing'):
        issues.append(_issue(
            '데이터', '높음', "지수 데이터 미수신 — 시장 국면 판정 보류",
            "KOSPI·KOSDAQ 최신 지수가 연동되지 않아 매매 적합도 상한(59점) "
            "게이트가 활성화됐습니다."))

    issues.sort(key=lambda i: _SEV_ORDER.get(i['severity'], 9))
    return issues


def build_stock_issues(four_scores, verdict, news_flags=None, name=''):
    """
    종목 이슈 — 이미 계산된 게이트·경고·뉴스 낱말 감지의 재표현만.
    """
    issues = []
    fs = four_scores or {}
    vd = verdict or {}
    nf = news_flags or {}

    for veto in (vd.get('vetoes') or [])[:2]:
        issues.append(_issue('추천', '높음',
                             f"{name} 신규 매수 차단 조건", str(veto), scope=name))
    if vd.get('cap_applied') and fs.get('gate_reason'):
        issues.append(_issue(
            '추천', '중간', f"{name} 점수 상한 적용",
            f"가중합보다 낮은 {vd.get('score')}점으로 제한 — "
            + str(fs.get('gate_reason'))[:150], scope=name))
    if nf.get('risk_count'):
        issues.append(_issue(
            '뉴스', '중간',
            f"{name} 뉴스 제목에 확인 필요 낱말 {nf['risk_count']}건",
            "위험 낱말이 걸린 기사가 있어 점수에 상한이 걸렸습니다. "
            "기사 원문을 직접 확인하세요.", scope=name))
    if fs.get('m10_disparity') is not None and fs.get('m10_overheat'):
        issues.append(_issue(
            '리스크', '중간', f"{name} 월봉 10선 과열권",
            f"월10선 이격 {fs['m10_disparity']:+.1f}% — 추격 매수 위험 구간입니다.",
            scope=name))
    _cb = fs.get('calibration_band') or {}
    if _cb and (_cb.get('n') or 0) < 5:
        issues.append(_issue(
            '데이터', '낮음', f"{name} 점수대 리플레이 표본 부족",
            f"이 점수대 과거 표본 {_cb.get('n', 0)}건 — 실측 적중률을 "
            "표시하지 않습니다.", scope=name))

    issues.sort(key=lambda i: _SEV_ORDER.get(i['severity'], 9))
    return issues
