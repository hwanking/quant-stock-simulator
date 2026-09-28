# -*- coding: utf-8 -*-
"""휴장일 표가 **실제로 장이 열린 날**과 맞는지 본다 (라운드 375 · 2026-09-28).

사고: `bitemporal_engine.KRX_HOLIDAYS` 가 2026-09-28(월)을 휴장으로 적고 있었다. 추석(9/24~26)이
토요일과 겹친 것을 대체공휴일로 읽은 것인데 — 설·추석의 대체는 **일요일**이나 다른 공휴일과
겹칠 때만이다. 그날 삼성전자·KODEX200 일봉이 있었다(장이 열렸다). 사용자가 *"나 출근했는데"* 로
잡았다. 그날 하루 앱의 분석 기준일이 09-23 으로 밀렸고, 그대로 뒀으면 그날 밤 전방 기록기가 오늘을
휴장으로 보고 0건을 남기고 **0건 가드도 휴장이라 통과시켰을 것**이다(그날은 다시 만들 수 없다 · R253).
같은 대조에서 2025-01-27(임시공휴일)이 표에서 **빠져 있던** 것도 나왔다.

라운드 88 이 이미 이 방법을 적어 두었다 — *"① 실제 코스피 일봉의 거래일과 대조한다"*. 그런데 그것은
**한 번 손으로** 한 대조였고, 미래 날짜(②)는 공개 자료 + 요일 규칙으로 넣었다. 그러면 틀린 미래
날짜는 **그날이 와도 아무도 대 보지 않는다.** 이 검사가 그 대조를 매일 한다 — 지나간 날만 잴 수 있으므로
미래 항목은 그날이 지나야 걸린다(오늘의 실수는 오늘 밤에 걸린다).

판정(문턱 없음 · 항등식):
  · 표에 휴장인데 그날 일봉이 있다        → 실패 (표가 거래일을 지웠다 — 이번 사고)
  · 평일인데 일봉이 없고 표에도 없다       → 실패 (표가 휴장을 빠뜨렸다)
  · 일봉을 못 받았다                        → 미측정 (rc 2 · 통과가 아니다)
대조 창은 마지막 봉에서 거꾸로 `WINDOW_DAYS` 달력일 — 그보다 옛날은 라운드 88 이 이미 맞췄고,
옛 결손(상장 전·거래정지)이 섞이지 않게 **지수를 따르는 ETF 둘**의 합집합을 쓴다(한쪽만 쉬는 날은 없다).
"""
import datetime as dt
import os
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:                                                 # noqa: BLE001
    pass

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)

#: 대조에 쓰는 종목 — 코스피200 을 따르는 ETF 와 시총 1위. 둘 다 매 거래일 거래된다.
PROBE_SYMBOLS = ('069500.KS', '005930.KS')
#: 대조 창(달력일). 2025-01-01 부터 전체도 이 PC 에서 맞췄다(라운드 375) — 매일은 최근만 본다.
WINDOW_DAYS = 120


def _iso(x):
    s = str(x)[:10].replace('.', '-').replace('/', '-')
    if '-' not in s and len(s) >= 8:
        s = '%s-%s-%s' % (s[:4], s[4:6], s[6:8])
    return s


def mismatches(bar_dates, holidays, start, end):
    """순수 함수. `bar_dates`(장이 열린 날 ISO 문자열 집합)와 `holidays`(표)를 `start`~`end`
    (date · 양끝 포함) 평일에서 대 본다. 반환 (표가 틀린 날 목록, 표가 빠뜨린 날 목록)."""
    wrong_closed, missing = [], []
    d = start
    while d <= end:
        if d.weekday() < 5:
            s = d.isoformat()
            opened = s in bar_dates
            listed = s in holidays
            if listed and opened:
                wrong_closed.append(s)
            elif (not listed) and (not opened):
                missing.append(s)
        d += dt.timedelta(days=1)
    return wrong_closed, missing


def bar_dates_live(fetch=None):
    """두 종목 일봉의 날짜 합집합. 못 받으면 빈 집합과 사유."""
    if fetch is None:
        import bitemporal_engine as be
        eng = be.BitemporalEngine()
        fetch = eng.fetch_daily_bars
    dates, notes = set(), []
    for sym in PROBE_SYMBOLS:
        try:
            df = fetch(sym)
        except Exception as exc:                                  # noqa: BLE001
            notes.append('%s 못 받음 (%s: %s)' % (sym, type(exc).__name__, exc))
            continue
        if df is None or len(df) == 0:
            notes.append('%s 빈 응답' % sym)
            continue
        col = 'trade_date' if 'trade_date' in df.columns else df.columns[0]
        ds = {_iso(x) for x in df[col]}
        notes.append('%s %d봉 · 마지막 %s' % (sym, len(ds), max(ds)))
        dates |= ds
    return dates, notes


def check(fetch=None, holidays=None):
    if holidays is None:
        import bitemporal_engine as be
        holidays = be.KRX_HOLIDAYS
    dates, notes = bar_dates_live(fetch)
    print('일봉: ' + ' · '.join(notes))
    if not dates:
        print('>> 못 쟀다 — 일봉을 한 종목도 못 받았다. 미측정이다(통과가 아니다).')
        return 2
    end = dt.date.fromisoformat(max(dates))
    start = end - dt.timedelta(days=WINDOW_DAYS)
    wrong, missing = mismatches(dates, holidays, start, end)
    n_wd = sum(1 for i in range((end - start).days + 1)
               if (start + dt.timedelta(days=i)).weekday() < 5)
    print('대조 %s ~ %s · 평일 %d일' % (start, end, n_wd))
    if wrong:
        print('>> 실패 — 표는 휴장인데 장이 열린 날: %s (KRX_HOLIDAYS 에서 뺀다)' % ', '.join(wrong))
    if missing:
        print('>> 실패 — 평일인데 봉이 없고 표에도 없는 날: %s (공휴일이면 표에 넣는다 · '
              '거래정지면 종목을 바꿔 본다)' % ', '.join(missing))
    if wrong or missing:
        return 1
    print('>> 통과 — 표와 실제 거래일이 평일 %d일 전부 맞다.' % n_wd)
    return 0


if __name__ == '__main__':
    sys.exit(check())
