# -*- coding: utf-8 -*-
"""
상단 띠에 실을 것을 모은다 — 지금 무엇이 돌고, 무슨 이슈가 있는가.

사용자 요청: *"업데이트 상황 알려주는 창 있으면 어때? 뭐 진행중이다,
핫이슈가 뭐다, 실시간으로 사이트나 뉴스 같은 거 맨 위에 계속 움직이게."*

■ 순서 — 급한 것이 먼저 지나간다
    ① 지금 돌고 있는 작업 (스캔·축적)
    ② 시장 상태 (지수·환율·VIX)
    ③ 위험 이슈 (뉴스 위험 낱말)
    ④ 최신 헤드라인

■ 지어내지 않는다 (CLAUDE.md §3)
    뉴스를 못 받으면 **"뉴스 미수신"을 흘린다.** 빈 띠를 채우려고 문구를
    만들지 않는다. 미수신과 '이슈 없음'은 다른 말이다.

■ 값을 만들지 않는다
    여기서 점수를 매기거나 판정하지 않는다. 이미 계산된 것을 **줄로
    바꿀 뿐**이다. 띠가 판단에 개입하면 화면마다 값이 달라진다 (§4).
"""
from __future__ import annotations

import time

#: 띠에 올릴 최대 줄 수 — 너무 길면 한 바퀴가 몇 분이 되어 못 읽는다
MAX_ITEMS = 14
#: 헤드라인이 이보다 길면 자른다 (한 줄로 흘러야 한다)
TITLE_MAX = 46


def _f(v):
    try:
        if v is None:
            return None
        x = float(v)
        return None if x != x else x
    except (TypeError, ValueError):
        return None


def _cut(s, n=TITLE_MAX):
    s = str(s or '').strip()
    return s if len(s) <= n else s[:n - 1] + '…'


def _busy(session):
    """지금 돌고 있는 작업 — session_state 에서 읽는다."""
    out = []
    s = session or {}
    if s.get('scan_busy'):
        stage = str(s.get('scan_stage') or '시장 데이터 최신화 중')
        out.append(dict(kind='live', text=stage))
    done = s.get('scan_done_at')
    if done and not s.get('scan_busy'):
        out.append(dict(kind='idle', text=f'마지막 갱신 {done}'))
    return out


def _market(macro):
    """지수·환율·변동성 — sector_cycle.macro() 결과를 줄로."""
    out = []
    m = macro or {}
    for key, ko in (('kospi', 'KOSPI'), ('kosdaq', 'KOSDAQ'),
                    ('spx', 'S&P500'), ('fx', '원달러'), ('vix', 'VIX')):
        v = m.get(key)
        if not isinstance(v, dict):
            continue
        chg = _f(v.get('chg60'))
        last = _f(v.get('last'))
        if last is None:
            continue
        txt = f"{ko} {last:,.2f}"
        if chg is not None:
            txt += f" ({chg:+.1f}% · 60일)"
        # 지수는 오르면 빨강(한국 관행)이 아니라 여기서는 상태색만 쓴다 —
        # 띠는 판단이 아니라 알림이라 방향색을 붙이지 않는다
        out.append(dict(kind='market', text=txt))
    miss = list(m.get('missing') or [])
    if miss:
        out.append(dict(kind='idle',
                        text=f"미수신: {', '.join(miss[:3])}"))
    return out


def _match_stock(title, name_map):
    """
    제목이 말하는 종목을 찾는다 — 있으면 "이름 (코드)" 라벨을 돌려준다.

    사용자 요청 (라운드 56): *"뉴스 기사 클릭하면 그거 관련된 대표적인
    주식으로 밑에 내용도 바뀌도록."* 매칭은 news_feed._mentions 의 보수
    규칙을 그대로 쓴다 — 짧은 이름('GS','DL')은 경계를 요구한다.
    여러 종목이 걸리면 **가장 긴 이름**을 고른다 ('삼성'보다 '삼성전자').
    못 찾으면 None — 억지로 잇지 않는다.
    """
    if not name_map:
        return None
    try:
        import news_feed as nf
    except Exception:                                        # noqa: BLE001
        return None
    best = None
    for name, ticker in name_map.items():
        if '(' in str(name):
            continue
        if nf._mentions(title, str(name)):
            if best is None or len(str(name)) > len(best[0]):
                best = (str(name), str(ticker))
    if best is None:
        return None
    code = best[1].split('.')[0]
    return f'{best[0]} ({code})'


def _news(items, report, name_map=None):
    """
    최신 헤드라인 — 위험 낱말이 붙은 것이 먼저 지나간다.

    items: news_feed.fetch() 의 첫 반환값
    """
    out = []
    try:
        import news_feed as nf
    except Exception:                                        # noqa: BLE001
        return out

    if not items:
        ok = sum(1 for r in (report or []) if r.get('ok'))
        out.append(dict(kind='idle',
                        text=('뉴스 미수신 — 판단에 반영하지 않습니다'
                              if not ok else '신규 기사 없음')))
        return out

    now = time.time()
    risky, fresh = [], []
    for it in items:
        title = str(it.get('title') or '')
        if not title:
            continue
        hit = [w for w in nf.RISK_WORDS if w in title]
        dt = it.get('dt')
        age_h = None
        if dt is not None:
            try:
                age_h = (now - dt.timestamp()) / 3600.0
            except Exception:                                # noqa: BLE001
                age_h = None
        row = dict(kind=('issue' if hit else 'news'),
                   text=_cut(title), href=it.get('link') or None,
                   meta=str(it.get('source') or '') or None)
        try:
            pick = _match_stock(title, name_map)
            if pick:
                row['pick'] = pick        # 제목 클릭 → 이 종목 분석으로
        except Exception:                                    # noqa: BLE001
            pass                          # 매칭 실패가 띠를 죽이지 않는다
        (risky if hit else fresh).append((age_h, row))

    risky.sort(key=lambda x: (x[0] is None, x[0] or 0))
    fresh.sort(key=lambda x: (x[0] is None, x[0] or 0))
    out.extend(r for _, r in risky[:4])
    out.extend(r for _, r in fresh[:8])
    return out


def build(session=None, macro=None, extra=None, name_map=None):
    """
    띠에 실을 줄 목록. ui_kit.ticker_bar 에 그대로 넘긴다.

    실패해도 화면은 떠야 한다 — 못 모으면 짧은 목록을 돌려준다.
    name_map: {종목명: 티커} — 주면 헤드라인에 종목 전환 링크가 붙는다.
    """
    rows = []
    try:
        rows.extend(_busy(session))
    except Exception:                                        # noqa: BLE001
        pass
    for x in (extra or []):
        if str(x.get('text') or '').strip():
            rows.append(x)
    try:
        rows.extend(_market(macro))
    except Exception:                                        # noqa: BLE001
        pass
    try:
        import news_feed as nf
        items, report = nf.fetch()
        rows.extend(_news(items, report, name_map=name_map))
    except Exception as e:                                   # noqa: BLE001
        rows.append(dict(kind='idle',
                         text=f'뉴스 수신 실패 ({type(e).__name__}) — '
                              f'판단에 반영하지 않습니다'))
    if not rows:
        rows = [dict(kind='idle', text='표시할 소식이 없습니다')]
    return rows[:MAX_ITEMS]
