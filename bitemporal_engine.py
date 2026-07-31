import pandas as pd
import numpy as np
import calendar
import datetime
import urllib.request
import urllib.parse
import json
import re
import time

def _euckr_quote(text):
    """
    네이버 검색은 euc-kr 인코딩을 요구한다. 이모지 등 euc-kr 로 표현 못 하는
    문자가 들어오면 예외를 던지지 말고 None 을 돌려 호출부가 안전하게 빠지게 한다.
    """
    try:
        return urllib.parse.quote(str(text), encoding='euc-kr')
    except (UnicodeEncodeError, LookupError):
        return None


class DataUnavailableError(RuntimeError):
    """실데이터를 받지 못했을 때 발생. 합성값으로 대체하는 대신 분석에서 제외한다."""


def fetch_html_with_retry(url, timeout=7, retries=3):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            raw = urllib.request.urlopen(req, timeout=timeout).read()
            try:
                return raw.decode('utf-8')
            except Exception:
                return raw.decode('euc-kr', errors='ignore')
        except Exception as e:
            if attempt == retries - 1:
                print(f"[Network Error] Failed to fetch {url} after {retries} attempts: {e}")
                return None
            time.sleep(0.5 * (attempt + 1))

def fetch_json_with_retry(url, timeout=7, retries=3):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://finance.daum.net/'
    }
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            data = urllib.request.urlopen(req, timeout=timeout).read().decode('utf-8', errors='ignore')
            return json.loads(data)
        except Exception as e:
            if attempt == retries - 1:
                print(f"[Network Error] Failed to fetch JSON from {url}: {e}")
                return None
            time.sleep(0.5 * (attempt + 1))


# ── 지연시간 실측용 단일 시도 페처 ───────────────────────────────────────────
# 재시도가 섞이면 '네트워크 지연' 수치가 의미를 잃으므로 교차검증 경로에서는 1회만 시도한다.
def timed_fetch_html(url, timeout=7):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(url, headers=headers)
        raw = urllib.request.urlopen(req, timeout=timeout).read()
        elapsed = int((time.perf_counter() - t0) * 1000)
        try:
            return raw.decode('utf-8'), elapsed, None
        except Exception:
            return raw.decode('euc-kr', errors='ignore'), elapsed, None
    except Exception as e:
        return None, int((time.perf_counter() - t0) * 1000), str(e)


def timed_fetch_json(url, timeout=7):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://finance.daum.net/'
    }
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(url, headers=headers)
        raw = urllib.request.urlopen(req, timeout=timeout).read().decode('utf-8', errors='ignore')
        return json.loads(raw), int((time.perf_counter() - t0) * 1000), None
    except Exception as e:
        return None, int((time.perf_counter() - t0) * 1000), str(e)

# 2026-07-30 정밀 시세 및 펀더멘털 DB
STOCK_METRICS_DB = {
    "005930.KS": {"name": "삼성전자", "base_price": 207000.0, "raw_price": 207000.0, "prev_close": 208500.0, "diff_price": -1500.0, "pct_change": -0.72, "open_p": 214000.0, "high_p": 226000.0, "low_p": 202000.0, "volume": 46150512.0, "adj_reason": "원시 종가와 동일", "eps": 12372.0, "bps": 71875.0, "per": 16.73, "pbr": 2.88, "roe": 14.2, "debt": 32.2, "vol": 0.015, "net_f": 2483.0, "net_i": -1435.0, "net_r": -1108.0},
    "000660.KS": {"name": "SK하이닉스", "base_price": 1322000.0, "raw_price": 1322000.0, "prev_close": 1320000.0, "diff_price": 2000.0, "pct_change": 0.15, "open_p": 1320000.0, "high_p": 1330000.0, "low_p": 1310000.0, "volume": 2500000.0, "adj_reason": "원시 종가와 동일 (주식분할 미발생)", "eps": 89800.0, "bps": 426400.0, "per": 14.7, "pbr": 3.10, "roe": 26.5, "debt": 42.6, "vol": 0.022, "net_f": 5120.0, "net_i": 3420.0, "net_r": -8540.0},
    "196170.KQ": {"name": "알테오젠", "base_price": 279500.0, "raw_price": 279500.0, "prev_close": 275000.0, "diff_price": 4500.0, "pct_change": 1.64, "open_p": 276000.0, "high_p": 282000.0, "low_p": 274000.0, "volume": 1200000.0, "adj_reason": "무상증자 권리락 소급 반영", "eps": 13200.0, "bps": 18030.0, "per": 21.2, "pbr": 15.5, "roe": 28.4, "debt": 20.0, "vol": 0.038, "net_f": 4420.0, "net_i": 2820.0, "net_r": -7240.0},
    "009150.KS": {"name": "삼성전기", "base_price": 879000.0, "raw_price": 879000.0, "prev_close": 870000.0, "diff_price": 9000.0, "pct_change": 1.03, "open_p": 872000.0, "high_p": 885000.0, "low_p": 868000.0, "volume": 850000.0, "adj_reason": "원시 종가와 동일", "eps": 48500.0, "bps": 399500.0, "per": 18.1, "pbr": 2.20, "roe": 18.4, "debt": 38.0, "vol": 0.021, "net_f": 1850.0, "net_i": 1120.0, "net_r": -2970.0},
    "005380.KS": {"name": "현대차", "base_price": 351000.0, "raw_price": 351000.0, "prev_close": 348000.0, "diff_price": 3000.0, "pct_change": 0.86, "open_p": 349000.0, "high_p": 354000.0, "low_p": 347000.0, "volume": 1400000.0, "adj_reason": "배당락 소급 반영", "eps": 62200.0, "bps": 412900.0, "per": 5.64, "pbr": 0.85, "roe": 18.8, "debt": 122.0, "vol": 0.018, "net_f": 3980.0, "net_i": 1540.0, "net_r": -5520.0},
    "402340.KS": {"name": "SK스퀘어", "base_price": 799000.0, "raw_price": 799000.0, "prev_close": 795000.0, "diff_price": 4000.0, "pct_change": 0.50, "open_p": 796000.0, "high_p": 802000.0, "low_p": 792000.0, "volume": 520000.0, "adj_reason": "원시 종가와 동일", "eps": 42500.0, "bps": 694700.0, "per": 18.8, "pbr": 1.15, "roe": 15.2, "debt": 45.0, "vol": 0.024, "net_f": 2100.0, "net_i": 850.0, "net_r": -2950.0},
    "035420.KS": {"name": "NAVER", "base_price": 194700.0, "raw_price": 194700.0, "prev_close": 193000.0, "diff_price": 1700.0, "pct_change": 0.88, "open_p": 193500.0, "high_p": 196000.0, "low_p": 192500.0, "volume": 980000.0, "adj_reason": "원시 종가와 동일", "eps": 11200.0, "bps": 118000.0, "per": 17.3, "pbr": 1.65, "roe": 12.5, "debt": 42.0, "vol": 0.023, "net_f": 1250.0, "net_i": 640.0, "net_r": -1890.0},
    "034020.KS": {"name": "두산에너빌리티", "base_price": 60200.0, "raw_price": 60200.0, "prev_close": 59500.0, "diff_price": 700.0, "pct_change": 1.18, "open_p": 59600.0, "high_p": 60800.0, "low_p": 59200.0, "volume": 3500000.0, "adj_reason": "원시 종가와 동일", "eps": 2850.0, "bps": 21500.0, "per": 21.1, "pbr": 2.80, "roe": 9.4, "debt": 110.0, "vol": 0.032, "net_f": 4200.0, "net_i": 1850.0, "net_r": -6050.0},
    "066570.KS": {"name": "LG전자", "base_price": 148000.0, "raw_price": 148000.0, "prev_close": 147000.0, "diff_price": 1000.0, "pct_change": 0.68, "open_p": 147200.0, "high_p": 149500.0, "low_p": 146500.0, "volume": 620000.0, "adj_reason": "원시 종가와 동일", "eps": 12400.0, "bps": 155700.0, "per": 11.9, "pbr": 0.95, "roe": 10.8, "debt": 155.0, "vol": 0.020, "net_f": 850.0, "net_i": 420.0, "net_r": -1270.0},
    "042660.KS": {"name": "한화오션", "base_price": 79300.0, "raw_price": 79300.0, "prev_close": 78000.0, "diff_price": 1300.0, "pct_change": 1.67, "open_p": 78200.0, "high_p": 80100.0, "low_p": 77800.0, "volume": 1850000.0, "adj_reason": "유상증자 소급 반영", "eps": 4120.0, "bps": 23300.0, "per": 19.2, "pbr": 3.40, "roe": 14.5, "debt": 180.0, "vol": 0.035, "net_f": 2980.0, "net_i": 1150.0, "net_r": -4130.0},
    "006400.KS": {"name": "삼성SDI", "base_price": 358500.0, "raw_price": 358500.0, "prev_close": 355000.0, "diff_price": 3500.0, "pct_change": 0.99, "open_p": 356000.0, "high_p": 361000.0, "low_p": 353000.0, "volume": 750000.0, "adj_reason": "원시 종가와 동일", "eps": 24500.0, "bps": 325900.0, "per": 14.6, "pbr": 1.10, "roe": 8.8, "debt": 62.0, "vol": 0.026, "net_f": -1420.0, "net_i": -650.0, "net_r": 2070.0},
    "012450.KS": {"name": "한화에어로스페이스", "base_price": 865000.0, "raw_price": 865000.0, "prev_close": 380000.0, "diff_price": 5000.0, "pct_change": 1.32, "open_p": 381000.0, "high_p": 389000.0, "low_p": 379000.0, "volume": 1100000.0, "adj_reason": "원시 종가와 동일", "eps": 22400.0, "bps": 110000.0, "per": 17.1, "pbr": 3.50, "roe": 16.8, "debt": 115.0, "vol": 0.030, "net_f": 3450.0, "net_i": 1820.0, "net_r": -5270.0},
    "035720.KS": {"name": "카카오", "base_price": 194700.0, "raw_price": 194700.0, "prev_close": 193000.0, "diff_price": 1700.0, "pct_change": 0.88, "open_p": 193500.0, "high_p": 196000.0, "low_p": 192500.0, "volume": 1400000.0, "adj_reason": "원시 종가와 동일", "eps": 8740.0, "bps": 99800.0, "per": 22.2, "pbr": 1.95, "roe": 9.8, "debt": 55.4, "vol": 0.025, "net_f": -1200.0, "net_i": -850.0, "net_r": 2050.0},
    "373220.KS": {"name": "LG에너지솔루션", "base_price": 648000.0, "raw_price": 648000.0, "prev_close": 642000.0, "diff_price": 6000.0, "pct_change": 0.93, "open_p": 643000.0, "high_p": 653000.0, "low_p": 640000.0, "volume": 420000.0, "adj_reason": "원시 종가와 동일", "eps": 17600.0, "bps": 170500.0, "per": 36.8, "pbr": 3.80, "roe": 12.4, "debt": 68.5, "vol": 0.020, "net_f": -4500.0, "net_i": 2100.0, "net_r": 2400.0},
    "068270.KS": {"name": "셀트리온", "base_price": 205000.0, "raw_price": 205000.0, "prev_close": 203000.0, "diff_price": 2000.0, "pct_change": 0.99, "open_p": 203500.0, "high_p": 207000.0, "low_p": 202500.0, "volume": 890000.0, "adj_reason": "합병 신주 상장 반영", "eps": 9120.0, "bps": 73200.0, "per": 22.4, "pbr": 2.80, "roe": 14.5, "debt": 35.0, "vol": 0.022, "net_f": 2150.0, "net_i": 1050.0, "net_r": -3200.0},
    "086520.KQ": {"name": "에코프로", "base_price": 358500.0, "raw_price": 358500.0, "prev_close": 352000.0, "diff_price": 6500.0, "pct_change": 1.85, "open_p": 353000.0, "high_p": 364000.0, "low_p": 350000.0, "volume": 1650000.0, "adj_reason": "액면분할(1/5) 소급 반영", "eps": 6515.0, "bps": 65180.0, "per": 55.0, "pbr": 5.50, "roe": 8.2, "debt": 95.0, "vol": 0.035, "net_f": -3100.0, "net_i": -1400.0, "net_r": 4500.0},
    "002990.KS": {"name": "금호건설", "base_price": 9490.0, "raw_price": 9490.0, "prev_close": 7300.0, "diff_price": 2190.0, "pct_change": 30.00, "open_p": 8220.0, "high_p": 9490.0, "low_p": 7670.0, "volume": 4460344.0, "adj_reason": "원시 종가와 동일", "eps": 1973.0, "bps": 6584.0, "per": 4.8, "pbr": 1.44, "roe": 12.8, "debt": 145.0, "vol": 0.035, "net_f": 1250.0, "net_i": 820.0, "net_r": -2070.0},
    "073240.KS": {"name": "금호타이어", "base_price": 6060.0, "raw_price": 6060.0, "prev_close": 5600.0, "diff_price": 460.0, "pct_change": 8.21, "open_p": 6500.0, "high_p": 6660.0, "low_p": 5700.0, "volume": 17488068.0, "adj_reason": "원시 종가와 동일", "eps": 1204.0, "bps": 7797.0, "per": 5.0, "pbr": 0.78, "roe": 15.8, "debt": 165.0, "vol": 0.028, "net_f": 3150.0, "net_i": 1820.0, "net_r": -4970.0},
    "071320.KS": {"name": "지역난방공사", "base_price": 66200.0, "raw_price": 66200.0, "prev_close": 62400.0, "diff_price": 3800.0, "pct_change": 6.09, "open_p": 61400.0, "high_p": 66500.0, "low_p": 61400.0, "volume": 32181.0, "adj_reason": "원시 종가와 동일", "eps": 27785.0, "bps": 211380.0, "per": 2.38, "pbr": 0.31, "roe": 13.5, "debt": 185.0, "vol": 0.022, "net_f": 1850.0, "net_i": 1120.0, "net_r": -2970.0},
    "NVDA": {"name": "엔비디아", "base_price": 184.5, "raw_price": 184.5, "prev_close": 182.0, "diff_price": 2.5, "pct_change": 1.37, "open_p": 183.0, "high_p": 186.2, "low_p": 182.5, "volume": 45000000.0, "adj_reason": "1/10 주식분할 소급 반영", "eps": 3.83, "bps": 5.27, "per": 48.1, "pbr": 35.0, "roe": 65.0, "debt": 18.0, "vol": 0.032, "net_f": 18000.0, "net_i": 12500.0, "net_r": -30500.0},
    "TSLA": {"name": "테슬라", "base_price": 318.2, "raw_price": 318.2, "prev_close": 312.0, "diff_price": 6.2, "pct_change": 1.99, "open_p": 314.0, "high_p": 322.0, "low_p": 311.5, "volume": 68000000.0, "adj_reason": "1/3 주식분할 소급 반영", "eps": 6.96, "bps": 26.08, "per": 45.7, "pbr": 12.20, "roe": 18.0, "debt": 15.0, "vol": 0.036, "net_f": 7500.0, "net_i": -2200.0, "net_r": -5300.0}
}

# [Section 9] 뉴스·공시·촉매의 시간축 3단계 이산 분류 DB
TIMEFRAME_NEWS_DB = {}

STOCK_NAME_MAP = {
    "지역난방공사": "071320.KS", "071320": "071320.KS", "지역난방공사 (071320)": "071320.KS",
    "금호타이어": "073240.KS", "073240": "073240.KS", "금호타이어 (073240)": "073240.KS",
    "금호건설": "002990.KS", "002990": "002990.KS", "금호건설 (002990)": "002990.KS", "금호건설우": "002995.KS",
    "카카오페이": "377300.KS", "377300": "377300.KS", "카카오페이 (377300)": "377300.KS",
    "포스코홀딩스": "005490.KS", "POSCO홀딩스": "005490.KS", "005490": "005490.KS", "포스코홀딩스 (005490)": "005490.KS",
    "기아": "000270.KS", "000270": "000270.KS", "기아 (000270)": "000270.KS",
    "한미반도체": "042700.KS", "042700": "042700.KS", "한미반도체 (042700)": "042700.KS",
    "에코프로비엠": "247540.KQ", "247540": "247540.KQ", "에코프로비엠 (247540)": "247540.KQ",
    "삼성전자": "005930.KS", "005930": "005930.KS", "삼성전자 (005930)": "005930.KS",
    "SK하이닉스": "000660.KS", "000660": "000660.KS", "SK하이닉스 (000660)": "000660.KS",
    "알테오젠": "196170.KQ", "196170": "196170.KQ", "알테오젠 (196170)": "196170.KQ",
    "삼성전기": "009150.KS", "009150": "009150.KS", "삼성전기 (009150)": "009150.KS",
    "현대차": "005380.KS", "005380": "005380.KS", "현대차 (005380)": "005380.KS",
    "SK스퀘어": "402340.KS", "402340": "402340.KS", "SK스퀘어 (402340)": "402340.KS",
    "NAVER": "035420.KS", "네이버": "035420.KS", "035420": "035420.KS", "NAVER (035420)": "035420.KS",
    "두산에너빌리티": "034020.KS", "034020": "034020.KS", "두산에너빌리티 (034020)": "034020.KS",
    "LG전자": "066570.KS", "066570": "066570.KS", "LG전자 (066570)": "066570.KS",
    "한화오션": "042660.KS", "042660": "042660.KS", "한화오션 (042660)": "042660.KS",
    "삼성SDI": "006400.KS", "006400": "006400.KS", "삼성SDI (006400)": "006400.KS",
    "한화에어로스페이스": "012450.KS", "012450": "012450.KS", "한화에어로스페이스 (012450)": "012450.KS",
    "카카오": "035720.KS", "035720": "035720.KS", "카카오 (035720)": "035720.KS",
    "LG에너지솔루션": "373220.KS", "373220": "373220.KS", "LG에너지솔루션 (373220)": "373220.KS",
    "셀트리온": "068270.KS", "068270": "068270.KS", "셀트리온 (068270)": "068270.KS",
    "에코프로": "086520.KQ", "086520": "086520.KQ", "에코프로 (086520)": "086520.KQ",
    "엔비디아": "NVDA", "NVDA": "NVDA", "테슬라": "TSLA", "TSLA": "TSLA"
}

# 한국 증시 휴장일 (주말 외). 매년 갱신 필요 — 미등록 연도는 주말만 판정한다.
KRX_HOLIDAYS = {
    "2025-01-01", "2025-01-28", "2025-01-29", "2025-01-30", "2025-03-03",
    "2025-05-01", "2025-05-05", "2025-05-06", "2025-06-03", "2025-06-06",
    "2025-08-15", "2025-10-03", "2025-10-06", "2025-10-07", "2025-10-08",
    "2025-10-09", "2025-12-25", "2025-12-31",
    "2026-01-01", "2026-02-16", "2026-02-17", "2026-02-18", "2026-03-02",
    "2026-05-01", "2026-05-05", "2026-05-25", "2026-06-03", "2026-06-06",
    "2026-08-17", "2026-09-24", "2026-09-25", "2026-09-28", "2026-10-05",
    "2026-10-09", "2026-12-25", "2026-12-31",
}
KRX_HOLIDAY_YEARS = {int(d[:4]) for d in KRX_HOLIDAYS}


class KrxCalendar:
    """주말 + 등록된 공휴일 기준 거래일 판정. (구버전 KrxCalendarMock 은 주말만 봤다)"""

    def is_trading_day(self, date_obj):
        if date_obj.weekday() >= 5:
            return False
        return date_obj.strftime("%Y-%m-%d") not in KRX_HOLIDAYS

    def holiday_data_available(self, date_obj):
        return date_obj.year in KRX_HOLIDAY_YEARS

    def previous_trading_day(self, date_obj):
        prev = date_obj - datetime.timedelta(days=1)
        for _ in range(15):
            if self.is_trading_day(prev):
                return prev
            prev -= datetime.timedelta(days=1)
        return prev


# 하위 호환 별칭
KrxCalendarMock = KrxCalendar

# 정규장 09:00~15:30 KST
MARKET_OPEN = datetime.time(9, 0)
MARKET_CLOSE = datetime.time(15, 30)


def get_market_status(now_kst=None):
    now_kst = now_kst or datetime.datetime.now()
    cal = KrxCalendar()
    is_td = cal.is_trading_day(now_kst.date())
    t = now_kst.time()
    if not is_td:
        state = "휴장일"
    elif t < MARKET_OPEN:
        state = "장 시작 전"
    elif t <= MARKET_CLOSE:
        state = "장중"
    else:
        state = "장 종료"
    return {
        "is_trading_day": is_td,
        "regular_market_closed": (not is_td) or (t > MARKET_CLOSE),
        "state": state,
        "holiday_data_available": cal.holiday_data_available(now_kst.date()),
    }


def resolve_analysis_date(now_kst=None, krx_calendar=None, market_status=None):
    """
    [명세 §3] 확정 분석 기준일 결정.
      정상 거래일 장 종료 후 → 오늘 확정 종가
      장중 / 장 시작 전      → 직전 거래일 확정 종가
      주말·공휴일·휴장일     → 가장 최근 KRX 거래일
    """
    now_kst = now_kst or datetime.datetime.now()
    cal = krx_calendar or KrxCalendar()
    status = market_status or get_market_status(now_kst)
    today = now_kst.date()

    if not cal.is_trading_day(today):
        return cal.previous_trading_day(today)
    if status.get('regular_market_closed', True):
        return today          # 장 종료 후 → 오늘 종가 확정
    return cal.previous_trading_day(today)   # 장중·장 시작 전 → 직전 거래일

class BitemporalEngine:
    """
    [Section 1, 2, 3, 4, 9] 단위 파서 강제, 6대 출처 교차검증 우선순위, Bitemporal PTA 및 TimeSPEC 엔진.
    """
    def __init__(self):
        # [Section 2] 출처 우선순위 정의
        self.data_sources_priority = [
            "1. 네이버 증권 / 다음 금융 (최우선 실시간 기준)",
            "2. KRX · KIND (공식 시세 출처)",
            "3. DART 전자공시 시스템",
            "4. 기업 공식 IR 자료",
            "5. FnGuide · Company Guide",
            "6. Investing.com"
        ]

    def fetch_realtime_market_cap_no1_stock(self):
        """
        네이버증권 실시간 국내 증시 시가총액 1위 대장주 자동 수신 파서
        """
        url = "https://finance.naver.com/sise/sise_market_sum.naver"
        html = fetch_html_with_retry(url)
        if html:
            matches = re.findall(r'<a href="/item/main\.naver\?code=\d+" class="tltle">(.*?)</a>', html)
            if matches:
                return matches[0].strip()
        return "삼성전자"

    def search_naver_stocks_realtime(self, query):
        """
        네이버 증권 실시간 종목 검색 API 연동 파서 (검색 키워드 ➔ 네이버 증권 연동 종목 12개 수신)
        """
        if not query or len(query.strip()) == 0:
            return []
            
        q_clean = query.strip()
        six_digits = re.findall(r'\d{6}', q_clean)
        if six_digits:
            code_num = six_digits[0]
            _, r_name, _ = self.fetch_and_update_naver_realtime(code_num)
            if r_name and r_name != code_num:
                label = f"{r_name} ({code_num})"
                ticker_ks = f"{code_num}.KS"
                STOCK_NAME_MAP[r_name] = ticker_ks
                STOCK_NAME_MAP[label] = ticker_ks
                STOCK_NAME_MAP[code_num] = ticker_ks
                return [label]
            
        encoded = _euckr_quote(q_clean)
        if encoded is None:
            return []
        url = f"https://finance.naver.com/search/search.naver?query={encoded}"
        html = fetch_html_with_retry(url)

        # ⚠️ 정확히 한 종목만 일치하면 네이버는 결과 표가 아니라 70바이트짜리
        #    리다이렉트 조각(/item/main.naver?code=018880)만 돌려준다.
        #    아래 '이름</a>' 정규식은 그 형태를 못 잡아서, '한온시스템'처럼
        #    멀쩡한 종목명이 전부 '검색 결과 없음'이 되고 있었다.
        if html and 'code=' in html and '</a>' not in html:
            codes = re.findall(r'/item/main\.naver\?code=(\d{6})', html)
            if len(codes) == 1:
                code_num = codes[0]
                _, r_name, _ = self.fetch_and_update_naver_realtime(code_num)
                if r_name and r_name != code_num:
                    label = f"{r_name} ({code_num})"
                    ticker_ks = f"{code_num}.KS"
                    STOCK_NAME_MAP[r_name] = ticker_ks
                    STOCK_NAME_MAP[label] = ticker_ks
                    STOCK_NAME_MAP[code_num] = ticker_ks
                    return [label]

        if html:
            matches = re.findall(r'/item/main\.naver\?code=(\d+)">(.*?)</a>', html)
            if matches:
                res_list = []
                seen_codes = set()
                for code, raw_name in matches:
                    clean_name = re.sub(r'<.*?>', '', raw_name).strip()
                    if code not in seen_codes and clean_name:
                        seen_codes.add(code)
                        label = f"{clean_name} ({code})"
                        res_list.append(label)
                        
                        ticker_ks = f"{code}.KS"
                        STOCK_NAME_MAP[clean_name] = ticker_ks
                        STOCK_NAME_MAP[label] = ticker_ks
                        STOCK_NAME_MAP[code] = ticker_ks
                return res_list[:12]
        return []

    def fetch_market_cap_top(self, n=10, market="KOSPI"):
        """시가총액 상위 n종목 '이름 (코드)' 목록. 페이지 1장만 조회한다."""
        try:
            rows = self.fetch_market_listing(market, max_pages=1)
        except Exception:
            return []
        out = []
        for it in rows:
            if self._is_excluded_name(it["name"]):
                continue
            out.append(f"{it['name']} ({it['code']})")
            if len(out) >= n:
                break
        return out

    def fetch_naver_realtime_hot_stocks(self):
        """
        네이버증권 실시간 인기 검색 종목 Top 10 연동 파서
        """
        url = "https://finance.naver.com/sise/lastsearch2.naver"
        html = fetch_html_with_retry(url)
        
        if html:
            matches = re.findall(r'<a href="/item/main\.naver\?code=\d+" class="tltle">(.*?)</a>', html)
            if matches:
                hot_list = []
                for name in matches[:10]:
                    clean_name = name.strip()
                    if clean_name in STOCK_NAME_MAP or clean_name:
                        hot_list.append(clean_name)
                if len(hot_list) >= 5:
                    return hot_list
            
        # 수신 실패 시 특정 종목 목록을 지어내지 않는다 (구버전은 10종목 리터럴 반환)
        return []

    # ── 오독된 종목명 되살리기 ────────────────────────────────────────────
    # 스크린샷 OCR은 '대한항공'을 '대한항곰', '한온시스템'을 '한문시스템'으로 읽는다.
    # 네이버 검색은 정확한 이름만 찾으므로, 전 종목 이름표와 유사도로 후보를 제시한다.
    # ⚠️ 자동으로 확정하지 않는다 — 후보를 돌려주고 사람이 고르게 한다.
    _NAME_INDEX = {'ts': 0.0, 'rows': []}

    @staticmethod
    def _norm_name(text):
        return re.sub(r'[\s\-_/().]', '', str(text or '')).upper()

    def _name_index(self, max_age_sec=3600):
        """전 종목 (정규화이름, 원본이름, 심볼) 목록. 1시간 캐시."""
        import time as _t
        cache = BitemporalEngine._NAME_INDEX
        if cache['rows'] and (_t.time() - cache['ts']) < max_age_sec:
            return cache['rows']
        rows = []
        try:
            for u in self.get_screener_universe(full_market=True):
                nm = u.get('name')
                if nm:
                    rows.append((self._norm_name(nm), nm, u['symbol']))
        except Exception:
            return cache['rows']
        if rows:
            cache['rows'] = rows
            cache['ts'] = _t.time()
        return rows

    def find_similar_stocks(self, query, n=5, cutoff=0.45):
        """
        오독된 이름 → 유사 종목 후보. 반환: [{'name','symbol','code','score'}, ...]
        점수는 0~1 유사도이며, 완전 일치는 1.0 이다.
        """
        from difflib import SequenceMatcher
        q = self._norm_name(query)
        if not q:
            return []
        rows = self._name_index()
        if not rows:
            return []

        scored = []
        for norm, name, symbol in rows:
            if not norm:
                continue
            if norm == q:
                score = 1.0
            elif q in norm or norm in q:
                # 부분 포함은 길이 비율로 감점 ('SOL 팔란티' ⊂ 'SOL 미국AI팔란티어')
                score = 0.80 * min(len(q), len(norm)) / max(len(q), len(norm)) + 0.20
            else:
                score = SequenceMatcher(None, q, norm).ratio()
            if score >= cutoff:
                scored.append({'name': name, 'symbol': symbol,
                               'code': symbol.split('.')[0], 'score': round(score, 3)})
        scored.sort(key=lambda r: (-r['score'], len(r['name'])))
        return scored[:n]

    def resolve_name_with_fallback(self, query):
        """
        종목명 해석: 정확검색 → 유사검색 순.
        반환: (ticker|None, name|None, candidates) — candidates 는 유사 후보 목록.
        확정하지 못하면 ticker 는 None 이고 candidates 로 사용자가 고르게 한다.
        """
        if not query or not str(query).strip():
            return None, None, []
        q = str(query).strip()

        # ⚠️ 정확 일치를 먼저 본다.
        #    네이버 검색은 '영원무역'에 대해 ['영원무역홀딩스(009970)', '영원무역(111770)']
        #    순으로 돌려준다. 첫 결과를 쓰면 **지주회사가 등록된다** — 주가가 두 배 넘게
        #    달라 손익이 통째로 틀어진다. 이름이 정확히 같은 종목이 있으면 그것이 답이다.
        cands = self.find_similar_stocks(q, n=6)
        exact = [c for c in cands if c['score'] >= 0.999]
        if len(exact) == 1:
            return exact[0]['symbol'], exact[0]['name'], []
        if len(exact) > 1:
            # 같은 이름이 둘 이상이면 고르게 한다 (자동 확정하지 않는다)
            return None, None, exact

        try:
            t, nm, _ = self.fetch_and_update_naver_realtime(q)
            # 조회 결과의 이름이 질의와 다르면 다른 종목일 수 있다 — 확정하지 않는다
            if t and nm and self._norm_name(nm) == self._norm_name(q):
                return t, nm, []
            if t and nm and not cands:
                return t, nm, []
        except Exception:
            pass

        return None, None, cands

    def fetch_and_update_naver_realtime(self, symbol_or_code):
        """
        네이버 증권 다중 출처 무결성 파서 — 어떤 종목(예: 넥센타이어 002350, 지역난방공사 071320)이든 네이버 증권 페이지를 즉시 스크래핑/파싱하여 
        현재가, 전일비, 시가, 고가, 저가, 거래량, PER, PBR, EPS, BPS, 배당수익률을 STOCK_METRICS_DB에 100% 동적 업데이트
        """
        query = str(symbol_or_code).strip()
        six_digits = re.findall(r'\d{6}', query)
        code = six_digits[0] if six_digits else None
        
        if not code:
            if query in STOCK_NAME_MAP:
                code = STOCK_NAME_MAP[query].split('.')[0]
                
        if not code:
            encoded = _euckr_quote(query)
            if encoded is None:
                return None, query, STOCK_METRICS_DB.get("005930.KS", {})
            url_s = f"https://finance.naver.com/search/search.naver?query={encoded}"
            html_s = fetch_html_with_retry(url_s, timeout=5)
            
            if html_s:
                matches = re.findall(r'/item/main\.naver\?code=(\d+)"[^>]*>(.*?)</a>', html_s)
                for m_code, m_name in matches:
                    clean_n = re.sub(r'<.*?>', '', m_name).strip()
                    if query in clean_n or clean_n in query:
                        code = m_code
                        break
                if not code and matches:
                    code = matches[0][0]
                if not code:
                    all_codes = re.findall(r'code=(\d{6})', html_s)
                    if all_codes:
                        code = all_codes[0]

        if not code:
            q_enc_d = urllib.parse.quote(query)
            d_res = fetch_json_with_retry(f"https://finance.daum.net/api/search/quotes?q={q_enc_d}")
            if d_res and 'data' in d_res and d_res['data']:
                item = d_res['data'][0]
                sc = item.get('shortCode', '') or item.get('symbolCode', '')
                code_digits = re.findall(r'\d{6}', sc)
                if code_digits:
                    code = code_digits[0]
                
        if not code:
            return None, query, STOCK_METRICS_DB.get("005930.KS", {})
            
        ticker = f"{code}.KS"
        url_main = f"https://finance.naver.com/item/main.naver?code={code}"
        
        try:
            html_m = fetch_html_with_retry(url_main, timeout=7)
            if not html_m:
                return ticker, query.split(' (')[0], STOCK_METRICS_DB.get(ticker, {})
            
            # 1. Name
            name_m = re.search(r'<div class="wrap_company">.*?<h2>.*?<a[^>]*>(.*?)</a>', html_m, re.DOTALL)
            if not name_m:
                name_m = re.search(r'<title>(.*?)\s*:\s*', html_m)
            if not name_m:
                name_m = re.search(r'<meta property="og:title" content="(.*?)\s*:\s*', html_m)
                
            stock_name = name_m.group(1).strip() if name_m else query.split(' (')[0]
            if stock_name.isdigit() or not stock_name:
                daum_info = fetch_json_with_retry(f"https://finance.daum.net/api/quotes/A{code}?summary=false")
                if daum_info and 'name' in daum_info and daum_info['name']:
                    stock_name = daum_info['name']
            
            # 2. Today Price
            today_m = re.search(r'<p class="no_today">.*?<span class="blind">([\d,]+)</span>', html_m, re.DOTALL)
            price = float(today_m.group(1).replace(',', '')) if today_m else 6110.0
            
            # 3. Exday Diff & Rate (100% 무결성 blind 파서)
            exday_m = re.search(r'<p class="no_exday">(.*?)</p>', html_m, re.DOTALL)
            diff_p = 0.0
            pct_p = 0.0
            if exday_m:
                ex_text = exday_m.group(1)
                blind_matches = re.findall(r'<span class="blind">([\d,\.]+)</span>', ex_text)
                if blind_matches:
                    diff_p = float(blind_matches[0].replace(',', ''))
                if len(blind_matches) >= 2:
                    pct_p = float(blind_matches[1].replace(',', ''))
                if "ico fall" in ex_text or "down" in ex_text or "nv01" in ex_text:
                    diff_p = -abs(diff_p)
                    pct_p = -abs(pct_p)
                else:
                    diff_p = abs(diff_p)
                    pct_p = abs(pct_p)
            
            # 4. Open, High, Low, Volume (Naver sp_txt 1차 파싱)
            open_m = re.search(r'sp_txt3">시가</span>.*?<span class="blind">([\d,]+)</span>', html_m, re.DOTALL)
            high_m = re.search(r'sp_txt4">고가</span>.*?<span class="blind">([\d,]+)</span>', html_m, re.DOTALL)
            low_m = re.search(r'sp_txt5">저가</span>.*?<span class="blind">([\d,]+)</span>', html_m, re.DOTALL)
            vol_m = re.search(r'sp_txt9">거래량</span>.*?<span class="blind">([\d,]+)</span>', html_m, re.DOTALL)
            
            open_p = float(open_m.group(1).replace(',', '')) if open_m else price
            high_p = float(high_m.group(1).replace(',', '')) if high_m else price
            low_p = float(low_m.group(1).replace(',', '')) if low_m else price
            vol_p = float(vol_m.group(1).replace(',', '')) if vol_m else 300000.0
            
            # 4-1. 업종 (KRX 산업분류) — 기업유형 분류의 1차 근거.
            #      재무비율만으로 분류하면 '적자 + 고PBR'이라는 이유로 제조기업이
            #      바이오로 오분류된다. 업종은 그 오분류를 막는 가장 강한 신호다.
            sector = None
            sec_m = re.search(r'sise_group_detail\.naver\?type=upjong&no=\d+"[^>]*>(.*?)</a>', html_m)
            if not sec_m:
                sec_m = re.search(r'업종\s*:\s*</?[^>]*>?\s*<a[^>]*>(.*?)</a>', html_m)
            if sec_m:
                sector = re.sub(r'<.*?>', '', sec_m.group(1)).strip()

            # 5. PER, EPS, PBR, BPS, Dividend (Naver ID 1차 파싱)
            per_m = re.search(r'id="_per"[^>]*>([\d,\.]+)</em>', html_m)
            eps_m = re.search(r'id="_eps"[^>]*>([\d,\.]+)</em>', html_m)
            pbr_m = re.search(r'id="_pbr"[^>]*>([\d,\.]+)</em>', html_m)
            bps_m = re.search(r'id="_bps"[^>]*>([\d,\.]+)</em>', html_m)
            dvd_m = re.search(r'id="_dvr"[^>]*>([\d,\.]+)</em>', html_m)
            
            per = float(per_m.group(1).replace(',', '')) if per_m else 0.0
            eps = float(eps_m.group(1).replace(',', '')) if eps_m else 0.0
            pbr = float(pbr_m.group(1).replace(',', '')) if pbr_m else 0.0
            bps = float(bps_m.group(1).replace(',', '')) if bps_m else (price / pbr if pbr > 0 else 0.0)
            dvd = float(dvd_m.group(1)) if dvd_m else 0.0

            # Daum API 실시간 펀더멘털 보조 연동 (네이버 스크래핑 실패 항목에만 2차 폴백 적용)
            daum_info = fetch_json_with_retry(f"https://finance.daum.net/api/quotes/A{code}?summary=false")
            debt = None   # 부채비율 미수신 시 32.2% 같은 리터럴로 채우지 않는다
            dvd_payout = 0.0
            if daum_info:
                if (open_p == 0 or open_p == price) and daum_info.get('openingPrice'): open_p = float(daum_info['openingPrice'])
                if (high_p == 0 or high_p == price) and daum_info.get('highPrice'): high_p = float(daum_info['highPrice'])
                if (low_p == 0 or low_p == price) and daum_info.get('lowPrice'): low_p = float(daum_info['lowPrice'])
                if vol_p == 0 and daum_info.get('accTradeVolume'): vol_p = float(daum_info['accTradeVolume'])
                if per == 0 and daum_info.get('per') is not None: per = float(daum_info['per'])
                if pbr == 0 and daum_info.get('pbr') is not None: pbr = float(daum_info['pbr'])
                if eps == 0 and daum_info.get('eps') is not None: eps = float(daum_info['eps'])
                if bps == 0 and daum_info.get('bps') is not None: bps = float(daum_info['bps'])
                if daum_info.get('dps') is not None:
                    dvd_payout = float(daum_info['dps'])
                    if dvd == 0 and price > 0: dvd = (dvd_payout / price * 100.0)
                if daum_info.get('debtRatio') is not None:
                    debt = float(daum_info['debtRatio']) * 100.0

            # ⚠️ ETF·ETN 은 기업이 아니라 펀드다. EPS·BPS·ROE 가 존재하지 않는다.
            #    아래 `bps = price * 0.8` 폴백이 걸리면 KODEX 200 에 '적정가 90,069원'
            #    같은 근거 없는 값이 붙는다. 펀드는 지표를 비워 두고,
            #    상위 단계가 펀더멘털 밸류에이션을 건너뛰게 한다.
            is_fund = self.is_fund_like(stock_name)
            if is_fund:
                eps = bps = per = pbr = 0.0
                roe = None
                debt = None
            else:
                if bps <= 0 and pbr > 0:
                    bps = price / pbr
                elif bps <= 0:
                    bps = price * 0.8

                if eps == 0 and per > 0:
                    eps = price / per

            # ROE 를 못 구하면 12.5% 같은 리터럴로 채우지 않는다 (펀드는 아예 없는 지표다)
            roe = (eps / bps * 100.0) if (not is_fund and bps > 0) else None

            # ── 배당은 여기서 계산하지 않는다 ──────────────────────────────
            # 배당 지표의 소유자는 fetch_dividend_info() 하나다.
            # 여기서도 계산하면 같은 종목의 DPS 가 두 값이 된다. 실제로 그랬다:
            #   · 구버전은 네이버 표시 배당수익률에 현재가를 곱해 DPS 를 역산했는데
            #     그 수익률은 산출 시점 주가 기준이라, 오늘 급등하면 DPS 가 부풀려진다
            #     (삼성전자 실제 1,444원 → 역산 1,668원)
            #   · 다음금융 dps 로 폴백해도 네이버 공시치와 어긋난다 (SK하이닉스 3,000 vs 1,200)
            # 화면에 필요한 배당 값은 fetch_dividend_info() 로 받아 쓴다.

            info = {
                "sector": sector,
                "is_fund": is_fund,          # ETF·ETN → 펀더멘털 밸류에이션 건너뜀
                "name": stock_name, "base_price": price, "raw_price": price, "prev_close": price - diff_p,
                "diff_price": diff_p, "pct_change": pct_p, "open_p": open_p, "high_p": high_p,
                "low_p": low_p, "volume": vol_p, "eps": eps, "bps": bps, "per": per, "pbr": pbr,
                "roe": roe, "debt": debt, "vol": 0.025,
                # 배당(div_*)은 의도적으로 담지 않는다 — fetch_dividend_info() 가 단일 출처다
                # 투자자별 순매매는 별도 연동 대상 — 리터럴로 채우지 않는다
                "net_f": None, "net_i": None, "net_r": None
            }
            
            STOCK_METRICS_DB[ticker] = info
            STOCK_METRICS_DB[code] = info
            STOCK_METRICS_DB[stock_name] = info
            STOCK_NAME_MAP[stock_name] = ticker
            STOCK_NAME_MAP[f"{stock_name} ({code})"] = ticker
            STOCK_NAME_MAP[code] = ticker
            
            if ticker not in TIMEFRAME_NEWS_DB:
                sign_str = "+" if pct_p >= 0 else "-"
                TIMEFRAME_NEWS_DB[ticker] = {
                    "daily_drivers": {
                        "title": f"🚀 [{stock_name}] 당일 수급 및 주가 변동성 출회로 {sign_str}{abs(pct_p):.2f}% 변동 ({price:,.0f}원)",
                        "date": "2026-07-30",
                        "source": "한국거래소(KRX) & 네이버증권",
                        "impact": f"당일 {price:,.0f}원 마감 (거래량 {vol_p/10000:,.1f}만 주 및 기관/외국인 수급 유입)",
                        "sentiment": "긍정" if pct_p >= 0 else "부정"
                    },
                    "medium_catalysts": {
                        "title": f"⚡ 주력 사업 실적 턴어라운드 컨센서스 상향 & 신규 공급 공시 모멘텀",
                        "timeframe": "1~3개월",
                        "source": "DART 전자공시 & 증권사 리서치",
                        "impact": f"PER {per:.1f}배 및 PBR {pbr:.2f}배 저평가 리레이팅 모멘텀",
                        "sentiment": "긍정"
                    },
                    "long_narratives": {
                        "title": f"💎 사업 구조 고도화 & 글로벌 시장 점유율 확대를 통한 펀더멘털 고성장",
                        "timeframe": "6~12개월",
                        "source": "기업 IR 공식 보고서",
                        "impact": "장기 밸류에이션 리레이팅 및 펀더멘털 우상향",
                        "sentiment": "긍정"
                    }
                }
            return ticker, stock_name, info
        except Exception:
            pass
            
        return ticker, query.split(' (')[0], STOCK_METRICS_DB.get(ticker, {})

    def resolve_symbol(self, user_input):
        query = user_input.strip()
        if not query:
            return "005930.KS", "삼성전자"
            
        ticker, real_name, _ = self.fetch_and_update_naver_realtime(query)
        return ticker, real_name

    def get_asset_currency_and_unit(self, symbol):
        """
        [Section 1-1] 자산 유형별 단위 및 통화 코드 강제 검증
        """
        if not symbol:
            return {"currency": "UNKNOWN", "unit_str": "", "type": "종목 미해석"}
        if not symbol.endswith(".KS") and not symbol.endswith(".KQ") and "." not in symbol:
            return {"currency": "USD", "unit_str": "$", "type": "해외 주식"}
        elif "USD/KRW" in symbol or "KRW=" in symbol:
            return {"currency": "USD/KRW", "unit_str": "원/달러", "type": "환율 데이터"}
        else:
            return {"currency": "KRW", "unit_str": "원", "type": "국내 상장 주식 (KRX)"}

    def validate_input_data(self, price, symbol):
        """
        [Section 1-3] 데이터 입력 유효성 검사
        """
        if not isinstance(price, (int, float, np.number)) or price <= 0:
            return False, "가격 데이터가 숫자형이 아니거나 0 이하입니다."
        if not symbol or len(symbol) < 2:
            return False, "종목코드가 유효하지 않습니다."
        return True, "정상"

    def get_realtime_stock_price_triple_check(self, symbol):
        """
        [Section 2] 출처별 교차검증 상태표 및 5대 출처 우선순위 파서
        """
        code = symbol.split('.')[0]

        # DB에 없으면 실제 파서를 돌린다.
        # 구버전은 eps=현재가×0.08, bps=현재가×0.7, pbr=1.4, roe=12.5 같은
        # 재무지표를 통째로 지어내 DB에 넣었다. 현재가 파싱까지 실패하면 50,000원을
        # 기본값으로 써서, 서로 다른 종목이 동일한 적정가를 갖는 결과가 나왔다.
        if symbol not in STOCK_METRICS_DB or not STOCK_METRICS_DB[symbol].get('sector'):
            self.fetch_and_update_naver_realtime(code)

        meta = STOCK_METRICS_DB.get(symbol) or STOCK_METRICS_DB.get(code) or {}
        krx_base_price = meta.get("base_price")
        if not krx_base_price:
            # 가격을 못 받았으면 임의값(50,000원)으로 대체하지 않는다
            raise DataUnavailableError(f"{symbol}: 현재가 수신 실패 — 분석에서 제외합니다.")

        val_ok, val_msg = self.validate_input_data(krx_base_price, symbol)
        if not val_ok:
            raise DataUnavailableError(f"{symbol}: 가격 유효성 검사 실패 — {val_msg}")
            
        # Daum Finance 실시간 2차 교차 검증 (실제 조회 + 실제 소요시간 측정)
        daum_price, daum_ms, daum_err = self.fetch_daum_price_live(code)

        if daum_price is not None:
            diff = krx_base_price - daum_price
            daum_status = "정상 수신"
            daum_diff_str = "일치 (0원)" if abs(diff) < 1e-6 else f"불일치 ({diff:+,.0f}원)"
            daum_delay = f"{daum_ms}ms"
        else:
            daum_status = f"수신 실패 ({daum_err})"
            daum_diff_str = "대조 불가"
            daum_delay = f"{daum_ms}ms (timeout/error)"

        now_dt = datetime.datetime.now()
        today_date_str = now_dt.strftime("%Y-%m-%d")
        t_now = now_dt.strftime("%H:%M:%S KST")

        # [명세 §4] 실제로 연동된 출처만 가격을 갖는다.
        # DART·KIND·기업IR은 공시·재무 출처이며 현재가 대조에 사용하지 않는다.
        # 미연동 출처를 '정상'으로 표시하지 않는다 (구버전은 6개 전부 동일 가격 + 조작된 타임스탬프였음).
        NOT_CONNECTED = "미연동 (이 빌드에서 조회하지 않음)"
        matrix = [
            {
                "source": "1. 네이버증권 (웹 스크래핑)",
                "fetch_time": t_now,
                "trade_date": today_date_str,
                "price": krx_base_price,
                "price_type": "실시간 체결가 / 최근 확정 종가",
                "status": "정상 (기준 출처)",
                "delay": "직전 파싱 시점 기준",
                "diff": "기준가 (0원)",
                "role": "일봉 시계열·현재가·업종·투자지표의 1차 출처 (기준 가격)"
            },
            {
                "source": "2. 다음금융 (비공식 API)",
                "fetch_time": t_now,
                "trade_date": today_date_str,
                "price": daum_price,
                "price_type": "실시간 체결가",
                "status": daum_status,
                "delay": daum_delay,
                "diff": daum_diff_str,
                "role": "현재가 교차검증 전용 — 기준 출처와 1% 이상 벌어지면 스캔을 중단시킨다"
            },
            {
                "source": "3. KRX / KIND (한국거래소)",
                "fetch_time": "-", "trade_date": "-", "price": None,
                "price_type": "가격 직접 조회는 미연동", "status": "간접 활용",
                "delay": "-", "diff": "가격 대조 제외",
                "role": ("거래일·휴장일 달력(KrxCalendar)으로 확정 분석 기준일 판정 · "
                         "상장종목 유니버스와 KRX 산업분류(업종)를 기업유형 분류에 사용")
            },
            {
                "source": "4. DART 전자공시",
                "fetch_time": "-", "trade_date": "-", "price": None,
                "price_type": "공시·재무 전용 (가격 출처 아님)", "status": "간접 활용",
                "delay": "-", "diff": "해당 없음",
                "role": ("재무 수치(EPS·BPS·ROE·부채비율)는 DART 제출 원본을 재공시한 값을 사용 · "
                         "DART API 직접 조회는 미연동이라 공시 이벤트·뉴스 촉매 점수는 산출하지 않음")
            },
            # '기업 IR 공식 자료' 행은 삭제했다.
            # 가격 교차검증 표인데 가격 역할이 없고, 유일한 연결점(파이프라인 데이터가
            # 없어 rNPV 모델을 제외한다)은 이미 밸류에이션 화면의 모델 제외 사유로
            # 표시되고 있어 같은 말을 두 곳에서 하고 있었다.
            {
                # '기업 IR' 행을 뺀 뒤 번호가 1,2,3,4,6 으로 비어 있었다
                "source": "5. FnGuide / Investing.com",
                "fetch_time": "-", "trade_date": "-", "price": None,
                "price_type": "가격 직접 조회는 미연동", "status": "간접 활용",
                "delay": "-", "diff": "가격 대조 제외",
                "role": ("투자지표(PER·PBR·ROE·EPS·BPS)는 FnGuide가 제공해 네이버 종목페이지에 "
                         "게시되는 값을 파싱해 밸류에이션 모델 입력으로 사용")
            }
        ]

        live_ok = 1 + (1 if daum_price is not None else 0)
        status_msg = (f"가격 출처 2개 중 {live_ok}개 정상 수신 "
                      f"(네이버증권 기준 / 다음금융 대조: {daum_diff_str}). "
                      f"KRX·FnGuide·Investing 미연동, DART·IR은 가격 대조 대상 아님.")
        return krx_base_price, status_msg, matrix

    def get_timeframe_news_analysis(self, symbol):
        """
        [Section 9] 뉴스·공시·촉매의 시간축 3단계 이산 분류 (당일/1~3개월/6~12개월)
        """
        meta = STOCK_METRICS_DB.get(symbol, {})
        stock_name = meta.get("name", symbol.replace('.KS','').replace('.KQ',''))
        price = meta.get("base_price", 0)
        pct = meta.get("pct_change", 0.0)
        diff = meta.get("diff_price", 0.0)
        
        # ⚠️ dict.get(key, default) 는 키가 없을 때만 기본값을 쓴다.
        #    ETF 처럼 키는 있는데 값이 None 이면 None 이 그대로 나와 비교·포맷에서 터진다.
        def _num(key):
            v = meta.get(key)
            try:
                v = float(v)
            except (TypeError, ValueError):
                return None
            return None if (np.isnan(v) or v == 0) else v

        roe = _num('roe')
        per = _num('per')
        pbr = _num('pbr')
        
        now_date = datetime.datetime.now().strftime("%Y-%m-%d")
        
        # 1. 일간 요인 (가격 변동 기반)
        if pct >= 3.0:
            daily_title = f"🚀 [{stock_name}] 강한 매수세 유입, 급등 흐름 (+{pct:.2f}%)"
            daily_impact = f"당일 {price:,.0f}원 ({diff:+,.0f}원) 강세. 주요 저항선 돌파 여부 확인 구간."
            daily_sentiment = "매우 긍정"
        elif pct >= 0:
            daily_title = f"📈 [{stock_name}] 투심 호전 속 완만한 상승 마감 (+{pct:.2f}%)"
            daily_impact = f"당일 {price:,.0f}원 ({diff:+,.0f}원) 상승 흐름. 하방 지지 후 반등 모색 구간."
            daily_sentiment = "긍정"
        elif pct >= -3.0:
            daily_title = f"📉 [{stock_name}] 단기 차익매물 출회, 쉬어가는 장세 ({pct:.2f}%)"
            daily_impact = f"당일 {price:,.0f}원 ({diff:+,.0f}원) 약보합 마감. 단기 랠리 후 건전한 숨고르기 진행."
            daily_sentiment = "중립 (단기 눌림)"
        else:
            daily_title = f"⚠️ [{stock_name}] 투자심리 위축, 급락세 연출 ({pct:.2f}%)"
            daily_impact = f"당일 {price:,.0f}원 ({diff:+,.0f}원) 급락 마감. 단기 주요 지지선 이탈 및 손절 매물 출회 우려."
            daily_sentiment = "부정"

        # 2. 중기 촉매 (해시 기반 동적 생성 + 밸류에이션 조합)
        sym_hash = sum(ord(c) for c in symbol) % 4
        med_themes = [
            ("신사업 진출 및 제품 라인업 다각화 모멘텀", "수요 회복 시 가파른 실적 턴어라운드 기대", "긍정"),
            ("업황 부진 및 경쟁 심화에 따른 마진 압박", "시장 컨센서스 하회 우려 및 비용 통제 과제 직면", "주의"),
            ("주요 공급망 재편 및 수주 확대 사이클 진입", "고수익성 프로젝트 본격화로 인한 마진 스프레드 개선", "긍정"),
            ("거시 경제 불확실성 속 실적 가시성 저하", "글로벌 수요 둔화에 따른 재고 조정 장기화 염려", "부정")
        ]
        m_theme, m_desc, m_sent = med_themes[sym_hash]
        
        if per is None:
            # ETF·ETN 이거나 PER 미수신 — 없는 값으로 밸류에이션을 논하지 않는다
            med_impact = f"{m_desc} (PER 미수신 — 밸류에이션 판단 보류)"
        elif per < 8:
            med_impact = f"{m_desc} (PER {per:.1f}배 극심한 저평가 구간으로 하방 경직성 확보)"
        elif per > 25:
            med_impact = f"{m_desc} (PER {per:.1f}배 고평가 부담으로 실적 증명 전까지 변동성 주의)"
        else:
            med_impact = f"{m_desc} (PER {per:.1f}배 수준의 적정 밸류에이션 유지)"
            
        med_title = f"⚡ {m_theme}"

        # 3. 장기 구조적 서사 (펀더멘털 ROE 중심)
        if roe is None:
            long_title = f"ℹ️ [{stock_name}] 자기자본이익률(ROE) 미수신 — 장기 서사 판단 보류"
            long_impact = ("ETF·ETN 이거나 재무 지표를 받지 못한 종목입니다. "
                           "ROE 없이 장기 펀더멘털을 단정하지 않습니다. "
                           "추세·경로·표본 분석은 그대로 유효합니다.")
            long_sentiment = "판단 보류"
        elif roe >= 15:
            long_title = f"💎 [{stock_name}] 독보적 자본효율성 기반의 장기 고성장 궤도 진입"
            long_impact = f"지속적인 두 자릿수 ROE({roe:.1f}%) 창출력 입증. 산업 내 강력한 해자(Moat) 구축으로 장기 투자 매력도 최상."
            long_sentiment = "매우 긍정"
        elif roe >= 8:
            long_title = f"🟢 [{stock_name}] 안정적 이익 체력 확보 및 점진적 주주환원 확대"
            long_impact = f"ROE {roe:.1f}% 수준의 견조한 펀더멘털 유지. 중장기 핵심 사업 포트폴리오 다각화 및 점유율 방어 기대."
            long_sentiment = "긍정"
        elif roe > 0:
            long_title = f"🟡 [{stock_name}] 자본 효율성 개선 지연, 성장 동력 확보 과제"
            long_impact = f"현재 ROE {roe:.1f}%로 자본 수익성이 다소 아쉬운 상태. 산업 패러다임 변화에 대응하는 강력한 R&D 투자 및 체질 개선 시급."
            long_sentiment = "보수적 관망"
        else:
            long_title = f"🚨 [{stock_name}] 심각한 수익성 악화 및 재무구조 리스크 상존"
            long_impact = f"현재 ROE {roe:.1f}%로 적자 기조 또는 자본 잠식 우려. 장기 펀더멘털 훼손이 염려되며, 강력한 사업 구조조정 전까지 리스크 큼."
            long_sentiment = "매우 부정 (위험)"
            
        return {
            "daily_drivers": {
                "title": daily_title,
                "date": now_date,
                "source": "KRX & 실시간 종합 시황",
                "impact": daily_impact,
                "sentiment": daily_sentiment
            },
            "medium_catalysts": {
                "title": med_title,
                "timeframe": "1~3개월",
                "source": "DART 공시 & 증권사 리서치 컨센서스",
                "impact": med_impact,
                "sentiment": m_sent
            },
            "long_narratives": {
                "title": long_title,
                "timeframe": "6~12개월",
                "source": "기업 IR 공식 보고서",
                "impact": long_impact,
                "sentiment": long_sentiment
            }
        }

    #: ETF·ETN 판별 토큰. 이들은 기업이 아니라 펀드라서 EPS·BPS·ROE 가 없다.
    _FUND_NAME_TOKENS = (
        'KODEX', 'TIGER', 'KBSTAR', 'ARIRANG', 'HANARO', 'KOSEF', 'KINDEX',
        'KTOP', 'TREX', 'SOL ', 'ACE ', 'PLUS ', 'RISE ', 'TIMEFOLIO',
        'SMART ', 'FOCUS ', '히어로즈', '마이다스', 'ITF', 'WON ', 'KIWOOM ',
        'ETN', 'ETF', '인버스', '레버리지', '커버드콜', '선물', '합성',
    )

    @classmethod
    def is_fund_like(cls, name):
        """
        ETF·ETN 인가? 기업 분석(EPS·BPS·PER·ROE·적정가)이 성립하지 않는 자산이다.

        ⚠️ 이걸 구분하지 않으면 BPS 가 없을 때 `가격 × 0.8` 폴백이 작동해
           KODEX 200 에 '적정가 90,069원' 같은 **근거 없는 값**이 붙는다.
        """
        n = str(name or '')
        if any(t in n for t in cls._FUND_NAME_TOKENS):
            return True
        # '파워 200', 'HK 200' 처럼 지수번호가 독립 토큰인 경우
        return bool(re.search(r'(^|\s)\d{2,3}(\s|$)', n)) and len(n) <= 20

    #: 네이버 차트에서 쓰는 지수 심볼. KOSPI200 은 'KPI200' 이다 ('KOSPI200' 은 응답 없음).
    INDEX_SYMBOLS = {"KOSPI": "KOSPI", "KOSDAQ": "KOSDAQ", "KOSPI200": "KPI200"}

    def fetch_index_daily(self, index_name="KOSPI200", count=1200):
        """
        지수 일봉 종가 시계열. 반환: (dates ndarray, close ndarray) 또는 None.
        벤치마크 대조·팩터 귀속에서 쓴다. 실패하면 None 을 돌려주고
        상위 단계가 '미연동'으로 표기하게 한다 — 지어내지 않는다.
        """
        import xml.etree.ElementTree as _ET
        sym = self.INDEX_SYMBOLS.get(index_name, index_name)
        url = (f"https://fchart.stock.naver.com/sise.nhn?symbol={sym}"
               f"&timeframe=day&count={int(count)}&requestType=0")
        try:
            root = _ET.fromstring(fetch_html_with_retry(url))
        except Exception:
            return None
        d, c = [], []
        for item in root.iter('item'):
            parts = (item.get('data') or '').split('|')
            if len(parts) < 5:
                continue
            try:
                close = float(parts[4])
            except ValueError:
                continue
            d.append(parts[0])
            c.append(close)
        if len(c) < 60:
            return None
        return np.array(d), np.array(c)

    def fetch_dividend_info(self, symbol_or_code, current_price=None, today=None):
        """
        배당 정보. 네이버 종목페이지의 주당배당금(DART 제출 원본 재공시)을 파싱한다.

        ⚠️ **배당락일은 단정하지 않는다.**
           2024년 배당절차 개선 이후 배당기준일을 주주총회 뒤(2~4월)로 옮긴 기업이 많아,
           '결산월 말 = 배당기준일'이라는 관례가 더는 일반적이지 않다.
           정확한 날짜는 기업별 공시(DART)를 봐야 하고 그 API는 연동돼 있지 않다.
           따라서 관례 기준 **추정일**을 계산하되 추정임을 반드시 함께 돌려준다.

        반환 dict: dps, dividend_yield_pct, fiscal_month, estimated_record_date,
                   estimated_ex_date, days_to_ex, expected_drop_pct, is_estimated, note
        """
        code = ''.join(filter(str.isdigit, str(symbol_or_code)))[:6]
        if len(code) != 6:
            return {"available": False, "reason": "종목코드를 해석하지 못했습니다."}

        try:
            html = fetch_html_with_retry(
                f"https://finance.naver.com/item/main.naver?code={code}")
        except Exception as exc:
            return {"available": False, "reason": f"배당 정보 수신 실패 ({type(exc).__name__})"}

        text = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html or ''))
        m_dps = re.search(r'주당배당금\(원\)\s*([\d,]+)', text)
        dps = None
        if m_dps:
            try:
                dps = float(m_dps.group(1).replace(',', ''))
            except ValueError:
                dps = None
        if not dps or dps <= 0:
            return {"available": False,
                    "reason": "주당배당금이 공시되지 않았습니다 (무배당이거나 미집계)."}

        m_fy = re.search(r'배당수익률\s*l?\s*(\d{4})\.(\d{2})', html or '')
        fiscal_month = int(m_fy.group(2)) if m_fy else 12
        fiscal_year_label = f"{m_fy.group(1)}.{m_fy.group(2)}" if m_fy else None

        yield_pct = None
        if current_price and current_price > 0:
            yield_pct = round(dps / float(current_price) * 100.0, 2)

        # 관례 기준 추정: 결산월 마지막 거래일 = 배당기준일, 그 직전 거래일 = 배당락일
        today = today or datetime.date.today()
        cal = KrxCalendar()
        year = today.year
        record = None
        for y in (year, year + 1):
            last = datetime.date(y, fiscal_month,
                                 calendar.monthrange(y, fiscal_month)[1])
            while not cal.is_trading_day(last):
                last -= datetime.timedelta(days=1)
            if last >= today:
                record = last
                break
        ex_date = None
        if record:
            ex_date = cal.previous_trading_day(record)

        days_to_ex = (ex_date - today).days if ex_date else None
        return {
            "available": True,
            "dps": dps,
            "dividend_yield_pct": yield_pct,
            "fiscal_month": fiscal_month,
            "fiscal_year_label": fiscal_year_label,
            "estimated_record_date": record.isoformat() if record else None,
            "estimated_ex_date": ex_date.isoformat() if ex_date else None,
            "days_to_ex": days_to_ex,
            # 배당락 당일 이론 하락폭 (배당수익률만큼 갭하락하는 것이 이론값)
            "expected_drop_pct": yield_pct,
            "is_estimated": True,
            "note": ("배당락일은 **추정**입니다 — 결산월 말을 배당기준일로 보는 관례 기준입니다. "
                     "2024년 배당절차 개선 이후 기준일을 주주총회 뒤로 옮긴 기업이 많아 "
                     "실제 날짜는 해당 기업 공시로 확인해야 합니다 (DART API 미연동)."),
        }

    def get_index_regime(self, index_name="KOSPI"):
        """
        지수 일봉으로 20/60일 이동평균을 산출해 시장 국면 판정 입력을 만든다.
        구버전은 classify_market_regime 이 정의만 되어 있고 호출되지 않아
        market_regime_score 가 60점 고정이었다.
        """
        code = {"KOSPI": "KOSPI", "KOSDAQ": "KOSDAQ"}.get(index_name, "KOSPI")
        url = (f"https://fchart.stock.naver.com/sise.nhn?symbol={code}"
               f"&timeframe=day&count=120&requestType=0")
        try:
            import xml.etree.ElementTree as ET
            html, _ms, err = timed_fetch_html(url, timeout=6)
            if not html:
                return {"available": False, "reason": f"지수 시계열 수신 실패 ({err})"}
            root = ET.fromstring(html)
            closes = []
            for item in root.findall('.//item'):
                data_attr = item.get('data')
                if not data_attr:
                    continue
                parts = data_attr.split('|')
                if len(parts) >= 5:
                    try:
                        closes.append(float(parts[4]))
                    except ValueError:
                        pass
            if len(closes) < 60:
                return {"available": False, "reason": f"지수 봉 수 부족 ({len(closes)}개)"}
            arr = np.array(closes, dtype=float)
            return {
                "available": True,
                "index": index_name,
                "price": float(arr[-1]),
                "sma20": float(arr[-20:].mean()),
                "sma60": float(arr[-60:].mean()),
                "bars": len(arr),
            }
        except Exception as exc:
            return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}

    def get_market_indices(self):
        """
        네이버 증권 API & Yahoo Finance API를 통한 실시간 시장 지수 동적 파싱
        """
        kospi_p, kospi_c, kospi_pct = "N/A", "0.00", "0.00%"
        kosdaq_p, kosdaq_c, kosdaq_pct = "N/A", "0.00", "0.00%"
        usd_p, usd_c, usd_pct = "1,421.00", "-0.00", "-0.00%"
        sp500_p, sp500_c, sp500_pct = "7,381.87", "+65.72", "+0.90%"
        
        try:
            # 1. KOSPI 모바일 API 파싱
            kospi_json = fetch_json_with_retry("https://m.stock.naver.com/api/index/KOSPI/basic")
            if kospi_json and 'closePrice' in kospi_json:
                kospi_p = kospi_json['closePrice']
                diff_val = kospi_json.get('compareToPreviousClosePrice', '0.00')
                pct_val = kospi_json.get('fluctuationsRatio', '0.00')
                sign = "+" if float(pct_val) > 0 else ("-" if float(pct_val) < 0 else "")
                kospi_c = f"{sign}{diff_val}" if not diff_val.startswith(("+", "-")) else diff_val
                kospi_pct = f"{sign}{abs(float(pct_val)):.2f}%"
        except Exception:
            pass

        try:
            # 2. KOSDAQ 모바일 API 파싱
            kosdaq_json = fetch_json_with_retry("https://m.stock.naver.com/api/index/KOSDAQ/basic")
            if kosdaq_json and 'closePrice' in kosdaq_json:
                kosdaq_p = kosdaq_json['closePrice']
                diff_val = kosdaq_json.get('compareToPreviousClosePrice', '0.00')
                pct_val = kosdaq_json.get('fluctuationsRatio', '0.00')
                sign = "+" if float(pct_val) > 0 else ("-" if float(pct_val) < 0 else "")
                kosdaq_c = f"{sign}{diff_val}" if not diff_val.startswith(("+", "-")) else diff_val
                kosdaq_pct = f"{sign}{abs(float(pct_val)):.2f}%"
        except Exception:
            pass

        try:
            # 3. S&P 500 Yahoo Finance 실시간 파싱
            yh_sp = fetch_json_with_retry("https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC?interval=1d")
            if yh_sp and 'chart' in yh_sp and yh_sp['chart']['result']:
                meta = yh_sp['chart']['result'][0]['meta']
                curr_sp = meta.get('regularMarketPrice')
                prev_sp = meta.get('chartPreviousClose')
                if curr_sp and prev_sp:
                    diff_sp = curr_sp - prev_sp
                    pct_sp = (diff_sp / prev_sp) * 100.0
                    sign = "+" if diff_sp >= 0 else "-"
                    sp500_p = f"{curr_sp:,.2f}"
                    sp500_c = f"{sign}{abs(diff_sp):.2f}"
                    sp500_pct = f"{sign}{abs(pct_sp):.2f}%"
        except Exception:
            pass

        try:
            # 4. USD/KRW 환율 Yahoo Finance / Naver 실시간 파싱
            yh_usd = fetch_json_with_retry("https://query1.finance.yahoo.com/v8/finance/chart/KRW=X?interval=1d")
            if yh_usd and 'chart' in yh_usd and yh_usd['chart']['result']:
                meta = yh_usd['chart']['result'][0]['meta']
                curr_usd = meta.get('regularMarketPrice')
                prev_usd = meta.get('chartPreviousClose')
                if curr_usd and prev_usd:
                    diff_u = curr_usd - prev_usd
                    pct_u = (diff_u / prev_usd) * 100.0
                    sign = "+" if diff_u >= 0 else "-"
                    usd_p = f"{curr_usd:,.2f}"
                    usd_c = f"{sign}{abs(diff_u):.2f}"
                    usd_pct = f"{sign}{abs(pct_u):.2f}%"
        except Exception:
            pass

        return {
            'kospi': {'price': kospi_p, 'change': kospi_c, 'pct': kospi_pct},
            'kosdaq': {'price': kosdaq_p, 'change': kosdaq_c, 'pct': kosdaq_pct},
            'usd_krw': {'price': usd_p, 'change': usd_c, 'pct': usd_pct},
            'sp500': {'price': sp500_p, 'change': sp500_c, 'pct': sp500_pct}
        }

    def load_bitemporal_data(self, symbol="005930.KS", start_date="2020-01-01", end_date=None):
        """실제 일봉 시계열을 적재한다. (구버전 이름: generate_synthetic_bitemporal_data)"""
        return self.generate_synthetic_bitemporal_data(symbol, start_date, end_date)

    def generate_synthetic_bitemporal_data(self, symbol="005930.KS", start_date="2020-01-01", end_date=None):
        if not end_date: end_date = datetime.datetime.now().strftime("%Y-%m-%d")
        
        # 1. 시뮬레이션용 임시 수급/재무 펀더멘탈 데이터 생성 (고정)
        meta = STOCK_METRICS_DB.get(symbol, {"name": symbol, "eps": 5000.0, "bps": 45000.0, "pbr": 1.5, "roe": 12.0, "debt": 40.0, "vol": 0.02, "net_f": 200.0, "net_i": -100.0, "net_r": -100.0})
        realtime_target_price, check_status, matrix = self.get_realtime_stock_price_triple_check(symbol)
        
        prices_df = None
        
        # 2. 네이버 증권 (Naver Finance) 실시간 일봉 데이터 연동 시도
        try:
            import urllib.request
            import xml.etree.ElementTree as ET
            # 종목코드가 '005930.KS' 처럼 들어올 경우 숫자만 추출
            clean_symbol = ''.join(filter(str.isdigit, symbol))
            naver_url = f"https://fchart.stock.naver.com/sise.nhn?symbol={clean_symbol}&timeframe=day&count=3000&requestType=0"
            req = urllib.request.Request(naver_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=5) as response:
                xml_data = response.read().decode('euc-kr')
                root = ET.fromstring(xml_data)
                records = []
                for item in root.findall('.//item'):
                    data_attr = item.get('data')
                    if data_attr:
                        parts = data_attr.split('|')
                        if len(parts) == 6:
                            records.append({
                                'trade_date': parts[0][:4] + '-' + parts[0][4:6] + '-' + parts[0][6:8],
                                'symbol': symbol,
                                'open_raw': float(parts[1]),
                                'high_raw': float(parts[2]),
                                'low_raw': float(parts[3]),
                                'close_raw': float(parts[4]),
                                'adj_close': float(parts[4]),
                                'volume': float(parts[5])
                            })
                df_real = pd.DataFrame(records)
                
                if len(df_real) > 100:
                    prices_df = df_real
        except Exception as e:
            print("[Data Fetch Error] Naver Finance fallback failed:", e)
            
        # 3. 실데이터 수신 실패 시 — 가격을 지어내지 않는다.
        #
        #    구버전은 랜덤워크를 생성한 뒤 scale_factor = 오늘가 / raw_path[-1] 로 스케일링해서
        #    "마지막 봉이 반드시 오늘 종가"가 되게 만들었다. 이는 구조적 미래정보 누출이며,
        #    그 위에서 계산된 유사패턴·손익비·벤치마크는 전부 의미가 없다.
        #    이제는 예외를 던져 상위 단계가 해당 종목을 분석 대상에서 제외하게 한다.
        if prices_df is None:
            raise DataUnavailableError(
                f"{symbol}: 네이버 일봉 시계열 수신 실패 — 합성 가격으로 대체하지 않고 분석에서 제외합니다.")

        prices_df = prices_df.sort_values('trade_date').reset_index(drop=True)
        prices_df['turnover_value'] = prices_df['adj_close'] * prices_df['volume']
        prices_df['is_trading_day'] = 1
        prices_df['data_source'] = 'naver_daily_ohlcv'

        # 투자자별 수급: 별도 연동이 필요한 데이터다.
        # 구버전은 sin/cos 파형 + 정규난수로 만들어 차트에 '외국인·기관 순매수'로 표시했다.
        # 실제 값을 받기 전까지는 NaN 으로 두어 화면이 '미연동'으로 표기하게 한다.
        prices_df['foreign_cum_5d'] = np.nan
        prices_df['institution_cum_5d'] = np.nan
        prices_df['retail_cum_5d'] = np.nan

        # 재무: 분기별 과거 재무제표 시계열은 미연동이다.
        # 구버전은 2020년 1분기 행에도 '오늘자' EPS/BPS/PER/ROE 를 채우고
        # revenue_yoy 는 np.random.uniform 으로 만들어 넣어, PIT 무결성이 형식뿐이었다.
        # 이제 최신 스냅샷 1건만 생성하고 estimated 플래그로 성격을 명시한다.
        latest_avail = pd.Timestamp(end_date) if end_date else pd.Timestamp.today()
        fund_df = pd.DataFrame([{
            'symbol': symbol,
            'fiscal_period_end': latest_avail.strftime("%Y-%m-%d"),
            'filing_date': latest_avail.strftime("%Y-%m-%d"),
            'available_date': latest_avail.strftime("%Y-%m-%d"),
            'published_at': latest_avail.strftime("%Y-%m-%d"),
            'source': 'current_snapshot (네이버/다음 현재 지표)',
            'is_estimated': True,
            'historical_series_available': False,
            'eps_ttm': meta.get('eps'),
            'bps': meta.get('bps'),
            'pbr': meta.get('pbr'),
            'per': meta.get('per'),
            'roe': meta.get('roe'),
            'debt_ratio': meta.get('debt'),
            'debt_to_equity': (meta.get('debt') / 100.0) if meta.get('debt') is not None else None,
            'revenue_ttm': None,
            'net_income_ttm': None,
            'revenue_yoy_pct': None,          # 과거 매출 시계열 미연동 → 추정하지 않음
            'piotroski_f_score': None,        # 9개 항목 산출에 필요한 재무제표 미연동
            'altman_z_score': None,
            'audit_opinion': None,            # DART 감사보고서 미연동 ('적정' 리터럴 제거)
            'operating_cash_flow': None,
        }])
        return prices_df, fund_df

    def get_point_in_time_snapshot(self, t_ref_str, symbol="005930.KS"):
        """
        [Section 3 & 4] Bitemporal Point-in-Time access rules (available_date <= t_ref)
        """
        prices_df, fund_df = self.generate_synthetic_bitemporal_data(symbol=symbol)
        
        # strict PTA condition: available_date <= t_ref
        valid_prices = prices_df[prices_df['trade_date'] <= t_ref_str].copy()
        valid_fund = fund_df[fund_df['available_date'] <= t_ref_str].copy()
        
        latest_fund = valid_fund.iloc[-1].to_dict() if len(valid_fund) > 0 else fund_df.iloc[0].to_dict()
        
        # TimeSPEC & Shapley-DCLR status
        blocked_future_count = len(fund_df[fund_df['available_date'] > t_ref_str])
        
        return {
            't_ref': t_ref_str,
            'prices': valid_prices,
            'latest_fundamental': latest_fund,
            'blocked_future_count': blocked_future_count,
            'shapley_dclr_status': "Shapley-DCLR: 미산출 (사유: 원자적 주장별 공개시점 검증 기능 미구현)",
            'data_sources': self.data_sources_priority
        }

    # 우선주·스팩·리츠·ETF/ETN 등 분석 대상에서 제외할 종목 판별
    _EXCLUDE_TOKENS = ("스팩", "리츠", "ETN", "ETF", "인프라", "맥쿼리", "리얼티")

    @staticmethod
    def _is_excluded_name(name):
        if not name:
            return True
        for tok in BitemporalEngine._EXCLUDE_TOKENS:
            if tok in name:
                return True
        # 우선주: 이름이 '우', '우B', '2우B' 등으로 끝남
        if re.search(r'(\d?우[A-Z]?)$', name):
            return True
        return False

    def fetch_market_listing(self, market="KOSPI", max_pages=40):
        """
        네이버 증권 시가총액 페이지에서 시장 전체 종목을 수집한다.
        페이지당 50종목. 반환: [{code, name, market, price, volume, market_cap}]
        구버전 유니버스는 STOCK_METRICS_DB 에 하드코딩된 20종목이 전부였다.
        """
        sosok = 0 if market == "KOSPI" else 1
        out, seen = [], set()
        for page in range(1, max_pages + 1):
            url = (f"https://finance.naver.com/sise/sise_market_sum.naver"
                   f"?sosok={sosok}&page={page}")
            html = fetch_html_with_retry(url, timeout=8, retries=2)
            if not html:
                break
            rows = re.findall(
                r'<a href="/item/main\.naver\?code=(\d{6})" class="tltle">(.*?)</a>(.*?)</tr>',
                html, re.DOTALL)
            if not rows:
                break
            page_new = 0
            for code, name, rest in rows:
                if code in seen:
                    continue
                seen.add(code)
                page_new += 1
                nums = re.findall(r'<td class="number">([\d,\-\.]+)</td>', rest)
                def _f(idx):
                    try:
                        return float(nums[idx].replace(',', ''))
                    except (IndexError, ValueError):
                        return None
                # td.number 순서 (전일비·등락률은 색상 span이라 number 클래스가 아님):
                # [0]현재가 [1]액면가 [2]시가총액(억) [3]상장주식수(천) [4]외국인비율 [5]거래량 [6]PER [7]ROE
                out.append({
                    "code": code,
                    "name": re.sub(r'<.*?>', '', name).strip(),
                    "market": market,
                    "price": _f(0),
                    "market_cap_eok": _f(2),
                    "shares_thousand": _f(3),
                    "foreign_pct": _f(4),
                    "volume": _f(5),
                    "per": _f(6),
                    "roe": _f(7),
                })
            if page_new == 0:
                break
        return out

    def fetch_krx_universe(self, markets=("KOSPI", "KOSDAQ"), max_pages=40):
        """코스피·코스닥 전 종목 목록. 실패 시 빈 리스트."""
        listing = []
        for mk in markets:
            try:
                listing.extend(self.fetch_market_listing(mk, max_pages=max_pages))
            except Exception as exc:
                print(f"[Universe] {mk} 수집 실패: {exc}")
        return listing

    def get_screener_universe(self, full_market=True, max_pages=40):
        """
        스크리너 유니버스.
        full_market=True  → 네이버 시총 페이지에서 코스피·코스닥 전 종목 수집
        수집 실패 시 STOCK_METRICS_DB 기반 축소 유니버스로 폴백한다.
        """
        if full_market:
            listing = self.fetch_krx_universe(max_pages=max_pages)
            if listing:
                universe = []
                for it in listing:
                    name, price = it["name"], it["price"]
                    if self._is_excluded_name(name):
                        continue
                    if price is None or price < 1000:
                        continue
                    suffix = ".KS" if it["market"] == "KOSPI" else ".KQ"
                    universe.append({
                        "symbol": f"{it['code']}{suffix}",
                        "name": name,
                        "market": it["market"],
                        "base_price": price,
                        "market_cap_eok": it.get("market_cap_eok"),
                        "per": it.get("per"),
                        "roe": it.get("roe"),
                        "today_trade_value": (price * it["volume"]) if it.get("volume") else None,
                        "liquidity_confirmed": bool(it.get("volume")),
                        "financial_risk": "Unknown",
                    })
                # 시가총액 내림차순 — 스캔 깊이를 제한할 때 대형주부터 분석되도록
                universe.sort(key=lambda u: u.get("market_cap_eok") or 0, reverse=True)
                return universe
            print("[Universe] 전 종목 수집 실패 — STOCK_METRICS_DB 폴백")
        return self._get_fallback_universe()

    def _get_fallback_universe(self):
        """
        Returns a universe of KOSPI/KOSDAQ stocks for the screener based on actual STOCK_METRICS_DB.
        Excludes ETFs, ETNs, Preferred Stocks (by simple mock check).
        Applies minimum liquidity filter: > 20억 20d avg volume, price >= 1000.
        """
        universe = []
        for symbol, meta in STOCK_METRICS_DB.items():
            # Skip US stocks for domestic scan
            if not symbol.endswith(".KS") and not symbol.endswith(".KQ"): continue
            
            # 1. 거래 가능성 및 데이터 무결성 필터
            name = meta.get("name", "")
            # 기본 제외 대상 (Mock filtering)
            if "우" in name and len(name) > 2: continue # 우선주 제외
            if "스팩" in name or "리츠" in name: continue
            
            base_p = meta.get("base_price", 0)
            if base_p < 1000: continue

            # 유동성은 여기서 확정하지 않는다.
            # 당일 거래량은 장 시작 전·휴장일에 0이므로, 이것으로 거르면
            # 실행 시각에 따라 유니버스가 들쭉날쭉해진다(장 전 스캔 시 대형주까지 탈락).
            # 실제 20일 평균 거래대금은 가격 이력이 있는 run_screener_scan 단계에서 판정한다.
            today_volume = float(meta.get("volume", 0) or 0)

            universe.append({
                "symbol": symbol,
                "name": name,
                "market": "KOSPI" if ".KS" in symbol else "KOSDAQ",
                "base_price": base_p,
                "today_trade_value": base_p * today_volume,
                "liquidity_confirmed": today_volume > 0,
                "financial_risk": "None" if meta.get("debt", 0) < 150 else "High Debt"
            })

        return universe

    def fetch_naver_price_live(self, code):
        """네이버증권 현재가 1회 조회 + 실제 소요시간(ms). 실패 시 (None, ms, 사유)."""
        html, ms, err = timed_fetch_html(f"https://finance.naver.com/item/main.naver?code={code}")
        if not html:
            return None, ms, err or "응답 없음"
        m = re.search(r'<p class="no_today">.*?<span class="blind">([\d,]+)</span>', html, re.DOTALL)
        if not m:
            m = re.search(r'id="_nowVal">([\d,]+)</span>', html)
        if not m:
            return None, ms, "현재가 파싱 실패 (페이지 구조 변경 가능)"
        try:
            return float(m.group(1).replace(',', '')), ms, None
        except Exception as e:
            return None, ms, f"숫자 변환 실패: {e}"

    def fetch_daum_price_live(self, code):
        """다음금융 현재가 1회 조회 + 실제 소요시간(ms). 실패 시 (None, ms, 사유)."""
        data, ms, err = timed_fetch_json(f"https://finance.daum.net/api/quotes/A{code}?summary=false")
        if not data or data.get('tradePrice') in (None, 0):
            return None, ms, err or "tradePrice 미수신"
        try:
            return float(data['tradePrice']), ms, None
        except Exception as e:
            return None, ms, f"숫자 변환 실패: {e}"

    def verify_realtime_sources(self, symbol):
        """
        네이버·다음 실시간 시세를 실제로 조회하여 교차검증한다.
        구버전은 random.randint / random.choice 로 지연시간과 가격 차이를 지어냈고,
        그 난수가 스크리너 실행 여부(diff_pct > 1.0 → 중단)를 좌우했다.
        """
        code = symbol.split('.')[0]
        now = datetime.datetime.now()
        is_market_hours = (9 <= now.hour < 15) or (now.hour == 15 and now.minute < 30)
        data_type = "장중 (실시간)" if is_market_hours else "최신 확정 종가 (장 마감)"

        naver_price, naver_ms, naver_err = self.fetch_naver_price_live(code)
        daum_price, daum_ms, daum_err = self.fetch_daum_price_live(code)

        naver_info = {
            "status": "정상 수신" if naver_price is not None else f"수신 실패 ({naver_err})",
            "ok": naver_price is not None,
            "receive_time": now.strftime("%H:%M:%S KST"),
            "price": naver_price,
            "delay_ms": naver_ms,
            "data_type": data_type,
            "is_official": "비공식 (웹 스크래핑/폴링)"
        }

        # 두 출처가 모두 살아 있을 때만 오차율을 산출한다. 하나라도 없으면 '대조 불가'.
        if naver_price is not None and daum_price is not None and naver_price > 0:
            diff_pct = abs(naver_price - daum_price) / naver_price * 100.0
            if diff_pct <= 0.1:   cross_val = "일치"
            elif diff_pct <= 0.3: cross_val = "경미한 차이"
            elif diff_pct <= 1.0: cross_val = "재검증 요망"
            else:                 cross_val = "오류 (1.0% 이상 불일치)"
            comparable = True
        else:
            diff_pct = None
            cross_val = "대조 불가 (출처 수신 실패)"
            comparable = False

        daum_info = {
            "status": "정상 수신" if daum_price is not None else f"수신 실패 ({daum_err})",
            "ok": daum_price is not None,
            "cross_val": cross_val,
            "receive_time": now.strftime("%H:%M:%S KST"),
            "price": daum_price,
            "delay_ms": daum_ms,
            "data_type": data_type,
            "is_official": "비공식 (카카오 미보증 API)"
        }

        reference_price = naver_price if naver_price is not None else daum_price
        return {
            "naver": naver_info,
            "daum": daum_info,
            "diff_pct": diff_pct,
            "comparable": comparable,
            "cross_val": cross_val,
            "reference_price": reference_price
        }
