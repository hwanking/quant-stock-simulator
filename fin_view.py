# -*- coding: utf-8 -*-
"""
연간 재무 발표치 표 — **표시 전용** (라운드 339).

라운드 336 이 셌다: 엔진이 종목마다 이미 받는 `finance/annual` 응답에 16항목 × 4개 연도가 오는데 `info` 는
ROE·부채비율 둘만 옮긴다. 사용자: *"적정가는 진짜 펀더멘털은 진짜 좋은 주식인지 판단해 주고."* 판단(점수·문턱)은
잰 근거가 있어야 만든다(§2) — 여기서는 **발표된 수를 그대로 옮겨 보여 주고**, 이 화면의 적정가가 그 수를 쓰지
않는다는 사실을 같이 적는다(§3). 추정치 열은 응답의 `isConsensus` 그대로 표시한다 — 우리가 고르지 않는다.

수 파싱은 엔진의 `_api_num` 한 곳(§4). 순수 함수 — 회귀가 심어서 잰다.
"""
from bitemporal_engine import _api_num

#: 보여 줄 항목 — 응답의 행 제목 그대로. 없는 항목은 만들지 않는다.
ITEMS = ('매출액', '영업이익', '당기순이익', 'ROE', '부채비율', 'EPS')

#: 응답에 단위 칸이 없다 — 네이버 연간 재무 표의 표기를 옮겨 적는다(값을 환산하지 않는다).
UNIT_NOTE = '단위는 네이버 연간 재무 표의 표기(금액 억원 · 비율 %)를 그대로 따릅니다 — 응답에 단위 칸이 없어 환산하지 않았습니다'


def annual_table(fin, items=ITEMS):
    """`finance/annual` 응답 → {'periods': [{'title','estimate'}…], 'rows': [{'item','cells':[{'period','value','estimate'}…]}…]}
    · 받은 것이 없으면 None · 값이 '-' 면 None(0 으로 안 채운다)."""
    fi = (fin or {}).get('financeInfo') or {}
    heads = fi.get('trTitleList') or []
    periods = []
    for h in heads:
        if not isinstance(h, dict) or not h.get('key'):
            continue
        periods.append((str(h['key']), str(h.get('title') or h['key']),
                        str(h.get('isConsensus') or 'N').upper() == 'Y'))
    rows_by = {}
    for r in fi.get('rowList') or []:
        if isinstance(r, dict) and r.get('title'):
            rows_by[str(r['title']).strip()] = r.get('columns') or {}
    if not periods or not rows_by:
        return None
    rows = []
    for it in items:
        cols = rows_by.get(it)
        if cols is None:
            continue
        cells = []
        for key, title, est in periods:
            c = cols.get(key) if isinstance(cols, dict) else None
            v = _api_num(c.get('value') if isinstance(c, dict) else c)
            cells.append(dict(period=title, value=v, estimate=est))
        rows.append(dict(item=it, cells=cells))
    if not rows:
        return None
    return dict(periods=[dict(title=t, estimate=e) for _, t, e in periods], rows=rows)
