# -*- coding: utf-8 -*-
"""GANEUM DAY — 한국투자 일별 분봉 조회 (라운드 516 · 2026-10-13). **조회만** — 주문·취소 경로는 이 모듈에 없다.

공식 샘플(open-trading-api · `inquire_time_dailychartprice`): 경로 `/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice` ·
TR `FHKST03010230` · 한 번에 최대 120건 · 서버 보관 최대 1년. 인자 `FID_COND_MRKT_DIV_CODE`(J = KRX) · `FID_INPUT_ISCD` ·
`FID_INPUT_HOUR_1`(HHMMSS) · `FID_INPUT_DATE_1`(YYYYMMDD) · `FID_PW_DATA_INCU_YN` · `FID_FAKE_TICK_INCU_YN`.

■ 토큰·호출 간격은 `broker_kis.KisBroker._call` 을 **그대로** 쓴다(화면·워커와 같은 토큰 파일 · 같은 간격 · 만료 응답 처리 R459·R496).
  `broker_kis.py` 는 실주문을 내는 파일이라 장중엔 고치지 않는다 — 이 조회 경로만 이 모듈이 그 경로 표에 **등록**한다(`ensure_path`).
  다음 장외 라운드에 broker_kis 의 표로 옮길 수 있다.
■ 하루를 거꾸로 넘겨 받는다: 마감 시각부터 120건씩 · 다음 요청은 받은 가장 이른 봉의 1분 전 · 09:00 봉에 닿으면 그날 완료.
  닿지 못하면(빈 응답 · 호출 상한) **완료로 적지 않는다** — 다음 실행이 다시 받는다(중복은 원장 열쇠가 막는다).
"""
from __future__ import annotations

import datetime as _dt

import day_bars

PATH_KEY = 'minute_day'
PATH = '/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice'
TR = 'FHKST03010230'
SESSION_FIRST = '09:00'          # 정규장 첫 봉(엔진의 장 시작과 같은 시각 · 수능일은 부르는 쪽이 날짜로 판단한다)
MAX_CALLS_PER_DAY = 6            # 하루 약 381봉 ÷ 120 = 4 — 여유 둘(무한 반복 방지 상한 · 판정 문턱 아님)


def ensure_path(bk_module=None):
    """`broker_kis.PATHS` 에 이 조회 경로를 등록한다(이 프로세스 안에서만 · 파일은 안 고친다)."""
    if bk_module is None:
        import broker_kis as bk_module
    bk_module.PATHS.setdefault(PATH_KEY, PATH)
    return bk_module.PATHS[PATH_KEY]


def _minus_one_minute(t):
    h, m = int(t[:2]), int(t[3:5])
    x = _dt.datetime(2000, 1, 1, h, m) - _dt.timedelta(minutes=1)
    return x.strftime('%H%M%S')


def fetch_day(broker, code, day, until='153000', max_calls=MAX_CALLS_PER_DAY, first=SESSION_FIRST):
    """그날(ISO) 하루치 분봉 → (분봉 목록, 정보 dict(calls, raw, other_day, rejects, complete, stop)). 네트워크는 broker 가 탄다."""
    ensure_path()
    ymd = str(day).replace('-', '')
    hour = until
    got, calls, raw, other, rejects = {}, 0, 0, 0, {}
    stop = None
    while calls < max_calls:
        params = dict(FID_COND_MRKT_DIV_CODE='J', FID_INPUT_ISCD=str(code), FID_INPUT_HOUR_1=hour, FID_INPUT_DATE_1=ymd,
                      FID_PW_DATA_INCU_YN='N', FID_FAKE_TICK_INCU_YN='')
        doc, _h = broker._call('GET', PATH_KEY, TR, params=params)
        calls += 1
        rows = doc.get('output2') or []
        raw += len(rows)
        bars, why = day_bars.parse_kis_rows(rows, code)
        for k, n in why.items():
            rejects[k] = rejects.get(k, 0) + n
        mine = [b for b in bars if b['day'] == str(day)]
        other += len(bars) - len(mine)
        new = [b for b in mine if (b['day'], b['t']) not in got]
        if not new:
            stop = '빈 응답' if not rows else '새 봉 없음'
            break
        for b in new:
            got[(b['day'], b['t'])] = b
        earliest = min(b['t'] for b in new)
        if earliest <= first:
            stop = '첫 봉 닿음'
            break
        hour = _minus_one_minute(earliest)
    else:
        stop = '호출 상한'
    out = sorted(got.values(), key=lambda b: b['t'])
    return out, dict(calls=calls, raw=raw, other_day=other, rejects=rejects, complete=(stop == '첫 봉 닿음'), stop=stop)
