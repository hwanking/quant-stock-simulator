# -*- coding: utf-8 -*-
"""엔진 축별 버전 칸 — 상단 버전 칩을 누르면 그 축의 **업데이트 이력**과 **다음에 할 일**이 펼쳐진다 (라운드 469).

사용자(2026-10-09): *"각각 항목마다 클릭하면 업데이트 히스토리가 나오고 어떤거 할건지에 대해서 나올 수 있게 해줘야지."*

■ 다음에 할 일은 손으로 적지 않는다 — 세 곳에서만 읽는다(§3 · 없는 계획을 지어내지 않는다 · 라운드 182 의 칩 툴팁과 같은 원칙)
  ① 열린 이슈 — 등록부에서 그 축에 걸린 열쇠(`AXIS_ISSUE`)가 열려 있으면 제목과 다음 점검일
  ② 연구 레이더의 열린 줄 — `data/research_radar.json` 의 `axis` 꼬리표가 그 축이고 `open` 이 참인 줄(이름 · 상태)
  ③ 전방 재평가일 — 그 줄이 재평가일을 기다리면(`status_needs_eval_date`) 날짜는 `forward_eval` 에서
  셋 다 없으면 *"이 축에 잡힌 다음 일이 없습니다"* 라고 적는다 — 빈 칸을 보기 좋게 채우지 않는다.
■ 이력은 버전 원장(`data/version_ledger.json`)의 그 축 줄을 새것부터. 원장 문장 그대로(이력 원문이다 · 고치지 않는다).
■ 이 모듈은 HTML 문자열만 낸다(판정·값 없음). 화면은 그리기만 한다(§4).
"""
from __future__ import annotations

import versioning as _ver

#: 칩에 쓰는 짧은 이름 — 종전엔 web_app 안에 있었다(라운드 44 · 목록은 versioning.AXES 가 정한다).
AXIS_SHORT = {'model': '모델', 'scoring': '산식', 'rulebook': '룰북', 'schema': '스키마', 'news': '뉴스',
              'valuation': '적정가', 'sector': '업황'}

#: 축에 걸린 열린 이슈의 열쇠 — 종전엔 web_app 의 칩 툴팁 안에 있었다(라운드 182·257). 한 곳에 둔다(§4).
#:   ⚠️ 모델 축은 일부러 안 건다 — `model|vb_gap` 은 일일 규칙이 열고 닫는 이슈라 손으로 걸지 않는다(라운드 222·262 의 결정 ·
#:   회귀 §182 가 잠근다). 모델 축의 다음 일은 연구 레이더의 재평가일 줄들이 말한다.
AXIS_ISSUE = {'scoring': 'model|score_not_separating',
              'rulebook': 'usability|loss_control_tradeoff'}

def anchor_id(axis: str) -> str:
    """칩 링크와 칸이 같이 쓰는 앵커 — 둘이 다른 글자를 만들지 않게 한 곳에서."""
    return f'ver-{axis}'


def axis_history(ledger: dict, axis: str) -> list:
    """버전 원장 → 그 축의 줄(새것부터). 원장을 못 읽었으면 []."""
    rows = [h for h in ((ledger or {}).get('history') or []) if isinstance(h, dict) and h.get('axis') == axis]
    return sorted(rows, key=lambda h: (str(h.get('effective_from') or ''), str(h.get('created_at') or '')), reverse=True)


def overdue_days(when: str | None, today=None):
    """점검 예정일이 오늘보다 앞이면 지난 날수 · 아니면(또는 못 읽으면) None. '오늘'은 이슈 등록부와 같은 정의를 쓴다(라운드 306)."""
    import datetime as _dt
    try:
        d = _dt.date.fromisoformat(str(when)[:10])
    except (TypeError, ValueError):
        return None
    if today is None:
        try:
            from improvement import issue_ops as _io
            today = _dt.date.fromisoformat(str(_io._today())[:10])
        except Exception:                                      # noqa: BLE001
            today = _dt.date.today()
    n = (today - d).days
    return n if n > 0 else None


def axis_plans(axis: str, open_issues: dict | None = None, radar_rows: list | None = None,
               eval_date: str | None = None, today=None) -> list:
    """그 축의 다음에 할 일 — [{'what','state','when','src'}]. 세 출처 밖의 것은 만들지 않는다.
    지난 점검일은 앞으로의 일처럼 적지 않는다 — 'N일 지남' 을 같은 칸에(라운드 306 의 그 모양)."""
    out = []
    key = AXIS_ISSUE.get(axis)
    iss = (open_issues or {}).get(key) if key else None
    if iss:
        when = str(iss.get('next_review') or iss.get('eta') or '')[:10] or None
        od = overdue_days(when, today)
        if when and od:
            when = f'점검 예정일 {when} · {od}일 지남'
        out.append(dict(what=str(iss.get('title') or key), state='열린 과제', when=when, src='이슈 등록부'))
    for r in radar_rows or []:
        if not isinstance(r, dict) or r.get('axis') != axis or not r.get('open'):
            continue
        when = (eval_date if r.get('status_needs_eval_date') else None)
        out.append(dict(what=str(r.get('name') or ''), state=str(r.get('status') or ''), when=when, src='연구 레이더'))
    return out


def _owner_line(axis: str) -> str:
    files = getattr(_ver, 'AXIS_FILES', {}).get(axis) or []
    if files:
        return '이 축은 이 파일들이 바뀌면 오릅니다: ' + ' · '.join(files)
    return '이 축은 담당 파일 표가 없습니다 — 바뀔 때 손으로 올립니다'


def panel_html(axis: str, version: str, history: list, plans: list, esc, tok: dict) -> str:
    """한 축의 칸 — 바깥 div 에 앵커 id(정화기가 details 의 id 를 지우므로 · ui_kit.disclose 와 같은 이유), 안에 펼침."""
    import ui_kit as _uk
    short = AXIS_SHORT.get(axis, axis)
    head = f"{short} {version} · 업데이트 {len(history)}건 · 다음에 할 일 {len(plans)}건"
    tx2, tx3 = tok.get('tx2', '#9DAABC'), tok.get('tx3', '#9DAABC')
    parts = [f"<div style='color:{tx3};'>{esc(_ver.AXIS_KO.get(axis, axis))} — 버전은 앱 출시일이 아니라 이 축이 마지막으로 "
             f"바뀐 시점입니다. {esc(_owner_line(axis))}.</div>"]
    parts.append(f"<div style='margin-top:8px; color:{tx2}; font-weight:700;'>다음에 할 일</div>")
    if plans:
        for p in plans:
            when = f" · {esc(p['when'])}" if p.get('when') else ''
            parts.append(f"<div style='margin-top:2px;'>· {esc(p['what'])} <span style='color:{tx3};'>— {esc(p['state'])}"
                         f"{when} · 출처 {esc(p['src'])}</span></div>")
    else:
        parts.append(f"<div style='color:{tx3};'>이 축에 잡힌 다음 일이 없습니다 — 열린 과제·연구 레이더 기준입니다"
                     f"(없는 계획을 만들어 적지 않습니다).</div>")
    parts.append(f"<div style='margin-top:8px; color:{tx2}; font-weight:700;'>업데이트 이력 (새것부터)</div>")
    if not history:
        parts.append(f"<div style='color:{tx3};'>버전 원장에 이 축의 줄이 없습니다.</div>")
    for h in history:                                          # 자르지 않는다 — 칸은 접혀 있다(라운드 314)
        # 이력 줄은 버전 원장 문장 그대로다(역사 산문 · 업데이트 카드와 같은 종류) — 'vp-hist' 표식으로 화면 상태값 감사
        #   (scripts/unavailable_audit)가 이 줄만 걷는다. '다음에 할 일' 줄에는 표식이 없어 계속 감사받는다.
        parts.append(f"<div class='vp-hist' style='margin-top:4px;'><span style='color:{tx3}; font-variant-numeric:tabular-nums;'>"
                     f"{esc(str(h.get('effective_from') or '')[:10])} · {esc(h.get('version') or '')} · "
                     f"{esc(h.get('kind_ko') or h.get('kind') or '')}</span><br>{esc(h.get('reason') or '')}</div>")
    return f"<div id='{anchor_id(axis)}'>" + _uk.disclose(head, ''.join(parts), color=tx2) + "</div>"


def load_inputs():
    """칸의 재료 넷 — (버전 원장, 열린 이슈 {열쇠: 행}, 레이더 줄, 재평가일). 하나를 못 읽어도 나머지는 그린다(§3 · 못 읽은 것은 비운다)."""
    import json
    import os
    try:
        led = _ver._load()
    except Exception:                                          # noqa: BLE001
        led = {}
    issues = {}
    try:
        from improvement import issue_ops
        from improvement.database import get_connection
        c = get_connection()
        try:
            issue_ops.ensure_schema(c)
            issues = {str(r.get('issue_key')): r for r in issue_ops.issue_view(c, 40) if str(r.get('status')) == 'open'}
        finally:
            c.close()
    except Exception:                                          # noqa: BLE001
        issues = {}
    rows = []
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'research_radar.json'),
                  encoding='utf-8') as f:
            rows = json.load(f).get('rows') or []
    except Exception:                                          # noqa: BLE001
        rows = []
    try:
        import forward_eval
        ed = forward_eval.eval_date()
    except Exception:                                          # noqa: BLE001
        ed = None
    return led, issues, rows, ed


def section_html(esc, tok: dict, inputs=None) -> str:
    """일곱 축의 칸 전부 — 머리 한 줄 + 축마다 접힌 칸. 축 목록은 versioning.AXES 가 정한다(손으로 나열하지 않는다)."""
    led, issues, rows, ed = inputs if inputs is not None else load_inputs()
    cur = (led or {}).get('axes') or {}
    tx3 = tok.get('tx3', '#9DAABC')
    head = (f"<div style='font-size:13px; color:{tx3}; margin:4px 0 2px 0;'>엔진 축별 — 위 버전 칩을 누르면 그 축이 "
            f"펼쳐집니다(업데이트 이력 · 다음에 할 일)</div>")
    body = ''.join(panel_html(a, str(cur.get(a) or '—'), axis_history(led, a), axis_plans(a, issues, rows, ed), esc, tok)
                   for a in _ver.AXES)
    return head + body


#: 칩 링크(#ver-축)를 누르거나 주소에 그 해시가 있으면 그 칸을 펼치고 그 자리로 간다. 부모 문서에 한 번만 심는다
#:   (`web_app._WL_COMMIT_JS` 와 같은 모양 · 라운드 390). 스크립트가 죽어도 칸은 거기 있고 눌러서 연다.
OPEN_JS = """
<script>
(function () {
  const W = window.parent;
  if (!W || !W.document || W.__gnVerBound) return;
  W.__gnVerBound = true;
  const s = W.document.createElement('script');
  s.textContent = `(function () {
    function openIt(h) {
      if (!h || h.indexOf('#ver-') !== 0) return;
      const box = document.getElementById(h.slice(1));
      if (!box) return;
      const d = box.querySelector('details');
      if (d) d.open = true;
      box.scrollIntoView({block: 'start'});
    }
    document.addEventListener('click', function (e) {
      const a = (e.target && e.target.closest) ? e.target.closest('a[href^="#ver-"]') : null;
      if (!a) return;
      const h = a.getAttribute('href');
      setTimeout(function () { openIt(h); }, 60);
    }, true);
    window.addEventListener('hashchange', function () { openIt(location.hash); });
    setTimeout(function () { openIt(location.hash); }, 800);
  })();`;
  W.document.head.appendChild(s);
})();
</script>
"""
