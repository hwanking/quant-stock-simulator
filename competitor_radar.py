# -*- coding: utf-8 -*-
"""
경쟁 서비스 레이더 (라운드 456) — `data/competitor_radar.json` 하나를 화면(시스템 → 제품 벤치마크)과 문서(`docs/COMPETITOR_RADAR.md` ·
`scripts/update_competitor_radar.py --render` 가 만든다)가 같이 읽는다(§4).

규칙(JSON 의 note 와 같다): 1차 근거는 공식 사이트·문서뿐 · 읽지 않은 축은 '미확인' · 점수·등급 없음(§2·§9 — 외부 검토가 제안한
'Visual polish 63/95' 같은 수는 지어낸 수라 받지 않았다) · 레이더는 아이디어 발견까지이고 도입은 필요성 → 기존 자료 검증 → 구현 ·
경쟁사 변화가 산식·가중치·문턱을 바꾸지 않는다(계산부 어디도 이 모듈을 읽지 않는다 · 회귀가 잠근다).
"""
import datetime as _dt
import json
import os
import re

PROJ = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(PROJ, 'data', 'competitor_radar.json')
DOC = os.path.join(PROJ, 'docs', 'COMPETITOR_RADAR.md')
STATES = ('보유', '부분', '없음', '미확인')
DECISIONS = ('BUILD', 'CONSIDER', 'WATCH', 'SKIP')
DECISION_KO = {'BUILD': '만든다', 'CONSIDER': '검토', 'WATCH': '지켜본다', 'SKIP': '안 한다'}
_ITEM_KEYS = ('competitor', 'dimension', 'feature', 'source_url', 'checked_at', 'previous_state', 'current_state', 'changed',
              'ganeum_state', 'gap', 'decision', 'reason')


def load(path=PATH):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def validate(doc, today=None):
    """→ 문제 목록(비면 통과). 구조 · 상태·결정 낱말 · 공식 도메인 · 날짜(미래 금지) · 점수 칸 없음 · 축·경쟁사 참조."""
    out = []
    today = today or _dt.date.today().isoformat()
    comps = {c['id']: c for c in doc.get('competitors') or []}
    dims = {d['id'] for d in doc.get('dimensions') or []}
    if not comps or not dims:
        out.append('경쟁사·축 목록이 비었다')
    for k in ('made', 'note', 'ganeum', 'items'):
        if k not in doc:
            out.append(f'{k} 없음')
    for d in dims:
        g = (doc.get('ganeum') or {}).get(d)
        if not g or g.get('state') not in STATES:
            out.append(f'가늠 상태 없음·틀림: {d}')
    for i, it in enumerate(doc.get('items') or []):
        miss = [k for k in _ITEM_KEYS if k not in it]
        if miss:
            out.append(f'items[{i}] 칸 없음: {miss}')
            continue
        if it['competitor'] not in comps:
            out.append(f"items[{i}] 모르는 경쟁사 {it['competitor']}")
        if it['dimension'] not in dims:
            out.append(f"items[{i}] 모르는 축 {it['dimension']}")
        if it['current_state'] not in STATES or it['ganeum_state'] not in STATES:
            out.append(f'items[{i}] 상태 낱말 틀림')
        if it['previous_state'] is not None and it['previous_state'] not in STATES:
            out.append(f'items[{i}] previous_state 틀림')
        if it['decision'] not in DECISIONS:
            out.append(f"items[{i}] 결정 낱말 틀림 {it['decision']}")
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(it['checked_at'])) or str(it['checked_at']) > today:
            out.append(f"items[{i}] 확인일 틀림·미래 {it['checked_at']}")
        host = re.sub(r'^https?://', '', str(it['source_url'])).split('/')[0].lower()
        hosts = [h.lower() for h in (comps.get(it['competitor']) or {}).get('official_hosts') or []]
        if not str(it['source_url']).startswith('https://') or not any(host == h or host.endswith('.' + h) for h in hosts):
            out.append(f"items[{i}] 공식 도메인이 아니다 {it['source_url']}")
        if it['changed'] != (it['previous_state'] is not None and it['previous_state'] != it['current_state']):
            out.append(f'items[{i}] changed 가 상태 변화와 안 맞는다')
        for k in it:
            if 'score' in k.lower() or 'rating' in k.lower():
                out.append(f'items[{i}] 점수 칸 금지: {k}')
    return out


def matrix(doc):
    """축 × (경쟁사… + 가늠) 표 — 칸은 상태 낱말(없으면 '미확인')."""
    comps = doc.get('competitors') or []
    cells = {}
    for it in doc.get('items') or []:
        cells[(it['competitor'], it['dimension'])] = it['current_state']
    rows = []
    for d in doc.get('dimensions') or []:
        row = {'축': d['ko']}
        for c in comps:
            row[c['name']] = cells.get((c['id'], d['id']), '미확인')
        row['가늠'] = (doc.get('ganeum') or {}).get(d['id'], {}).get('state', '미확인')
        rows.append(row)
    return rows


def gaps(doc):
    """결정이 BUILD·CONSIDER 인 항목(결정 → 축 → 경쟁사 순 · 결정적)."""
    order = {d: i for i, d in enumerate(DECISIONS)}
    out = [it for it in (doc.get('items') or []) if it['decision'] in ('BUILD', 'CONSIDER')]
    return sorted(out, key=lambda it: (order[it['decision']], it['dimension'], it['competitor']))


def changed(doc):
    return [it for it in (doc.get('items') or []) if it.get('changed')]


def last_checked(doc):
    ds = [str(it.get('checked_at')) for it in (doc.get('items') or []) if it.get('checked_at')]
    return (min(ds), max(ds)) if ds else (None, None)


def render_md(doc):
    """문서 본문 — JSON 에서 결정적으로 만든다(손으로 고치지 않는다 · 회귀가 파일과 대 본다)."""
    comps = {c['id']: c['name'] for c in doc.get('competitors') or []}
    dims = {d['id']: d['ko'] for d in doc.get('dimensions') or []}
    lo, hi = last_checked(doc)
    L = ['# 경쟁 서비스 레이더 (자동 생성 — 손으로 고치지 않는다 · 출처는 data/competitor_radar.json)', '',
         f"만든 날 {doc.get('made')} · 항목 {len(doc.get('items') or [])}개 · 확인일 {lo} ~ {hi}", '', doc.get('note', ''), '',
         '## 축 × 서비스 (상태 낱말만 · 점수 없음)', '']
    heads = ['축'] + list(comps.values()) + ['가늠']
    L.append('| ' + ' | '.join(heads) + ' |')
    L.append('|' + '---|' * len(heads))
    for row in matrix(doc):
        L.append('| ' + ' | '.join(str(row[h]) for h in heads) + ' |')
    L += ['', '## 가늠의 자리(축마다 한 줄)', '']
    for d_id, ko in dims.items():
        g = (doc.get('ganeum') or {}).get(d_id) or {}
        L.append(f"- **{ko}** — {g.get('state', '미확인')} · {g.get('note', '')}")
    L += ['', '## 차이(결정이 BUILD · CONSIDER 인 것)', '']
    gs = gaps(doc)
    if not gs:
        L.append('- 없음')
    for it in gs:
        L.append(f"- **{DECISION_KO[it['decision']]}({it['decision']})** · {dims.get(it['dimension'], it['dimension'])} · "
                 f"{comps.get(it['competitor'], it['competitor'])} — {it['gap']} · {it['reason']}")
    L += ['', '## 지난번 대비 바뀐 것', '']
    ch = changed(doc)
    if not ch:
        L.append('- 없음(첫 판이거나 바뀐 상태가 없다)')
    for it in ch:
        L.append(f"- {comps.get(it['competitor'])} · {dims.get(it['dimension'])} — {it['previous_state']} → {it['current_state']}")
    L += ['', '## 항목 전부 (근거 URL · 확인일)', '']
    for it in doc.get('items') or []:
        L.append(f"- {comps.get(it['competitor'])} · {dims.get(it['dimension'])} · **{it['current_state']}** (가늠 {it['ganeum_state']}) · "
                 f"{DECISION_KO[it['decision']]} — {it['feature']} · {it['source_url']} · {it['checked_at']}")
    L += ['', '규칙: 경쟁사가 기능을 냈다고 바로 넣지 않는다 — 레이더는 아이디어 발견까지이고, 도입은 필요성 → 기존 자료로 검증 → 구현이다. '
          '경쟁사 변화가 산식·가중치·문턱을 바꾸지 않는다.', '']
    return '\n'.join(L)


def render(st, uk, theme='dark', md=None, doc=None):
    """화면(시스템 → 제품 벤치마크) — 표 · 차이 · 바뀐 것 · 확인일. 판정·점수 없음."""
    md = md or (lambda s: s)
    try:
        doc = doc or load()
    except (OSError, ValueError) as e:
        st.caption(f'경쟁사 레이더 파일을 읽지 못했습니다 — {type(e).__name__}: {e}')
        return
    lo, hi = last_checked(doc)
    st.caption(md(f"공식 사이트·문서만 근거로 적은 표입니다(확인일 {lo} ~ {hi} · 항목 {len(doc.get('items') or [])}개). 점수는 없습니다 — "
                  "상태 낱말(보유·부분·없음·미확인)과 결정(만든다·검토·지켜본다·안 한다)뿐이고, 경쟁사 변화가 가늠의 산식·문턱을 바꾸지 않습니다. "
                  "갱신은 scripts/update_competitor_radar.py 가 돕고 근거를 읽고 적는 일은 사람·조사 작업이 합니다."))
    st.dataframe(matrix(doc), hide_index=True, width='stretch')
    gs = gaps(doc)
    comps = {c['id']: c['name'] for c in doc.get('competitors') or []}
    dims = {d['id']: d['ko'] for d in doc.get('dimensions') or []}
    if gs:
        uk.rows([(f"{DECISION_KO[it['decision']]} · {dims.get(it['dimension'])} · {comps.get(it['competitor'])}", it['gap'],
                  ('warn' if it['decision'] == 'BUILD' else '')) for it in gs[:6]], theme=theme, title='차이 — 검토할 것(위부터)')
    for it in gs[:6]:
        st.caption(md(f"{dims.get(it['dimension'])} · {comps.get(it['competitor'])} — {it['reason']}"))
    ch = changed(doc)
    st.caption('지난번 대비 바뀐 상태: ' + (' · '.join(f"{comps.get(it['competitor'])} {dims.get(it['dimension'])} {it['previous_state']}→{it['current_state']}"
                                            for it in ch) if ch else '없음'))
