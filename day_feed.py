# -*- coding: utf-8 -*-
"""GANEUM DAY — 한국투자 일별 분봉 조회 (라운드 516 · 2026-10-13). **조회만** — 주문·취소 경로는 이 모듈에 없다.

공식 샘플(open-trading-api · `inquire_time_dailychartprice`): 경로 `/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice` ·
TR `FHKST03010230` · 한 번에 최대 120건 · 서버 보관 최대 1년. 인자 `FID_COND_MRKT_DIV_CODE`(J = KRX) · `FID_INPUT_ISCD` ·
`FID_INPUT_HOUR_1`(HHMMSS) · `FID_INPUT_DATE_1`(YYYYMMDD) · `FID_PW_DATA_INCU_YN` · `FID_FAKE_TICK_INCU_YN`.

■ 토큰·호출 간격은 `broker_kis.KisBroker._call` 을 **그대로** 쓴다(화면·워커와 같은 토큰 파일 · 같은 간격 · 만료 응답 처리 R459·R496).
  조회 경로는 라운드 525 부터 `broker_kis.PATHS['minute_day']` 에 있다(라운드 516 은 실주문 파일을 장중에 안 고치려고 이 모듈이 프로세스
  안에서 등록했다). `ensure_path` 는 남겨 둔다 — 표에 있으면 아무것도 안 하고, 경로가 표와 다르면 표를 믿는다.
■ 하루를 거꾸로 넘겨 받는다: 마감 시각부터 120건씩 · 다음 요청은 받은 가장 이른 봉의 1분 전 · 09:00 봉에 닿으면 그날 완료.
  닿지 못하면(빈 응답 · 호출 상한) **완료로 적지 않는다** — 다음 실행이 다시 받는다(중복은 원장 열쇠가 막는다).
■ 라운드 520 — 실측(2026-10-13 · 두 종목 × 9개 날짜): 이 조회는 **그 날짜의 봉만** 준다(다른 날 봉 0) · 보관은 약 1년(250거래일 전은
  오고 260거래일 전은 빈다) · 새해 첫 거래일(2026-01-02)은 **10:00 개장**이라 09:00 봉이 없고 · 거래가 드문 종목은 09:00 정각 봉이
  없을 수 있다. 그래서 '완료'를 09:00 봉 하나로만 재면 그 날들은 영영 미완료라 실행마다 다시 받는다. **한 쪽에 그날 봉이 120개보다
  적게 오면** 그 앞에는 그날 봉이 없다는 뜻이므로 그것도 완료다(쪽 크기 120 은 공식 설명의 상한이지 고른 수가 아니다). 꽉 찬 쪽 뒤의
  빈 응답은 여전히 미완료(일시적인 빈 응답과 못 가른다). 처음부터 봉이 0 이면 `none` — 보관 밖이거나 그날 거래가 없다는 **답**이다.
"""
from __future__ import annotations

import datetime as _dt

import day_bars

PATH_KEY = 'minute_day'
PATH = '/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice'
TR = 'FHKST03010230'
SESSION_FIRST = '09:00'          # 정규장 첫 봉(엔진의 장 시작과 같은 시각 · 수능일은 부르는 쪽이 날짜로 판단한다)
MAX_CALLS_PER_DAY = 6            # 하루 약 381봉 ÷ 120 = 4 — 여유 둘(무한 반복 방지 상한 · 판정 문턱 아님)
PAGE = 120                       # 한 번에 오는 최대 행 수(공식 설명) — 이보다 적게 오면 그 앞에 그날 봉이 없다(라운드 520)


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
        if len(mine) < PAGE:
            stop = f'그날 첫 거래까지(마지막 쪽 {len(mine)}개 < {PAGE})'
            break
        hour = _minus_one_minute(earliest)
    else:
        stop = '호출 상한'
    out = sorted(got.values(), key=lambda b: b['t'])
    done = stop == '첫 봉 닿음' or str(stop).startswith('그날 첫 거래까지')
    return out, dict(calls=calls, raw=raw, other_day=other, rejects=rejects, complete=done, stop=stop,
                     none=(not got and stop == '빈 응답'))
