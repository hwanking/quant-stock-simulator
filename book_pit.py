# -*- coding: utf-8 -*-
"""
잔여 호가 시점 보관 — 장이 닫힌 뒤 남아 있는 5단 호가 잔량을 **그날 날짜로** 박제한다 (라운드 342).

■ 이것이 무엇이고 무엇이 아닌가 (이름이 값보다 넓으면 지어낸 값이다)
  클라우드 기록기는 밤(한국 시각 21~23시대)에 돈다. 그때 공개 끝점이 주는 것은 **그날 마지막 세션
  (시간외 연속매매 · 20:00 마감)이 끝난 뒤 남은 호가 5단**이다. **정규장 15:30 마감 호가가 아니고,
  체결강도도 아니다**(그 값을 주는 공개 끝점은 못 찾았다 · 2026-09-21 실측). 낮에 손으로 돌리면 살아 있는
  호가가 찍히므로 받은 시각과 장 상태를 같이 남긴다 — 나중에 재는 쪽이 그것으로 거른다.

■ 왜 지금
  호가는 지나가면 다시 받을 수 없다(소급 불가 · 라운드 341 의 재무 시점 보관과 같은 자리). 이 값이 쓸모
  있는지는 **아직 모른다** — 재려면 날짜가 30일 넘게 쌓여야 하고(채택된 하한) 그것은 사전등록의 일이다(§2).
  판정·점수·화면 어디에도 안 들어간다. 범위는 그날 기록기가 본 상위 종목뿐이다.
"""
import os

from bitemporal_engine import NAVER_MOBILE_API, _api_num, fetch_json_with_retry
import fin_pit

PROJ = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(PROJ, '.portfolio', 'book_pit.jsonl')
#: 같은 (종목, 날짜) 한 번만 — 쓰기·세기는 재무 시점 보관과 **같은 함수**다(§4 · 베끼지 않는다)
append_rows = fin_pit.append_rows
coverage = fin_pit.coverage


def _levels(items):
    out = []
    for it in (items or []):
        if not isinstance(it, dict):
            continue
        out.append([_api_num(it.get('price')), _api_num(it.get('count'))])
    return out


def parse(payload):
    """askingPrice 응답 → {total_sell, total_buy, sells, buys}. 모양이 다르면 None(자리를 채우지 않는다 · §3).
    빈 가격('')은 None 으로 남는다 — 0 으로 안 바꾼다."""
    if not isinstance(payload, dict) or 'totalSell' not in payload or 'totalBuy' not in payload:
        return None
    return dict(total_sell=_api_num(payload.get('totalSell')), total_buy=_api_num(payload.get('totalBuy')),
                sells=_levels(payload.get('sellInfo')), buys=_levels(payload.get('buyInfos')))


def rows_for(codes, date, fetched_at, market_status, getter=None):
    """종목마다 한 번 묻는다. 반환 (rows, 못 받은 수). getter 는 심기용."""
    get = getter or (lambda c: fetch_json_with_retry(f"{NAVER_MOBILE_API}/stock/{c}/askingPrice", timeout=6, retries=2))
    rows, failed = [], 0
    for c in codes:
        book = parse(get(c))
        if book is None:
            failed += 1
            continue
        rows.append(dict(date=str(date)[:10], code=str(c), fetched_at=str(fetched_at),
                         market_status=market_status, **book))
    return rows, failed
