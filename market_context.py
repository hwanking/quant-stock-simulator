# -*- coding: utf-8 -*-
"""
시장·글로벌·뉴스 컨텍스트 — '이 종목만' 보지 않고 판을 함께 본다.

여기서 다루는 것:
  1. 국내 지수 국면 — 그 종목이 실제로 상장된 시장(KOSPI/KOSDAQ)으로 본다.
     (이전에는 코스닥 종목도 코스피 국면으로 판정했다.)
  2. 글로벌 스트레스 — S&P500 · 나스닥 · VIX · 원/달러.
  3. 종목 뉴스 — 네이버 종목뉴스 API 로 제목·언론사·시각·연관기사를 그대로 받는다.

원칙 (이 파일 전체에 적용):
  · 받지 못한 값은 **미수신**으로 남긴다. 기본값·가정값으로 채우지 않는다.
  · 뉴스는 **받은 그대로** 보여준다. 기사 내용을 요약·해석해 지어내지 않는다.
    판정에 쓰는 것은 규칙집에 적힌 키워드가 제목에 있는지뿐이고,
    어떤 키워드가 걸렸는지 항상 함께 보여준다.
  · 점수는 올리는 쪽으로 쓰지 않는다. 위험 신호일 때 **상한(cap)** 만 건다.
    좋은 뉴스처럼 보인다고 점수를 얹으면 그 순간 이 앱은 뉴스 해석기가 된다.
"""
from __future__ import annotations

import html as _html
import re
import time

import numpy as np

import bitemporal_engine as be

# ─────────────────────────────────────────────────────────────────────────────
# 캐시 — 지수·뉴스는 종목마다 다시 받을 필요가 없다
# ─────────────────────────────────────────────────────────────────────────────
_CACHE: dict = {}
_TTL_GLOBAL = 600      # 글로벌 지수 10분
_TTL_NEWS = 300        # 종목 뉴스 5분


def _cached(key, ttl, producer):
    now = time.time()
    hit = _CACHE.get(key)
    if hit and (now - hit[0]) < ttl:
        return hit[1]
    val = producer()
    _CACHE[key] = (now, val)
    return val


# ─────────────────────────────────────────────────────────────────────────────
# 1. 글로벌 지표
# ─────────────────────────────────────────────────────────────────────────────

#: (야후 심볼, 표시명, 소수자리)
GLOBAL_SYMBOLS = (
    ("%5EGSPC", "sp500", "S&P 500", 2),
    ("%5EIXIC", "nasdaq", "나스닥", 2),
    ("%5EVIX", "vix", "VIX (변동성지수)", 2),
    ("KRW=X", "usdkrw", "원/달러 환율", 2),
)


def _yahoo_series(symbol, rng="6mo"):
    """야후 차트 API → 종가 배열. 실패하면 None (빈 배열을 만들어 내지 않는다)."""
    j = be.fetch_json_with_retry(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?interval=1d&range={rng}")
    try:
        res = j['chart']['result'][0]
        closes = [c for c in res['indicators']['quote'][0]['close'] if c is not None]
        if len(closes) < 20:
            return None, None
        return np.array(closes, dtype=float), res.get('meta', {})
    except Exception:
        return None, None


def _series_stats(arr):
    """종가 배열 → 추세·낙폭 요약."""
    last = float(arr[-1])
    sma20 = float(arr[-20:].mean())
    sma60 = float(arr[-60:].mean()) if len(arr) >= 60 else None
    chg5 = (last / float(arr[-6]) - 1.0) * 100.0 if len(arr) >= 6 else None
    chg20 = (last / float(arr[-21]) - 1.0) * 100.0 if len(arr) >= 21 else None
    peak = float(arr[-120:].max()) if len(arr) >= 20 else last
    drawdown = (last / peak - 1.0) * 100.0 if peak else None
    return {
        'price': last, 'sma20': sma20, 'sma60': sma60,
        'chg5_pct': chg5, 'chg20_pct': chg20,
        'drawdown_pct': drawdown,
        'above_sma20': last > sma20,
        'above_sma60': (last > sma60) if sma60 is not None else None,
        'bars': int(len(arr)),
    }


def fetch_global_context():
    """글로벌 지표 묶음. 각 항목은 성공/실패를 스스로 밝힌다."""
    def _build():
        out = {}
        for sym, key, label, _dec in GLOBAL_SYMBOLS:
            arr, meta = _yahoo_series(sym)
            if arr is None:
                out[key] = {'available': False, 'label': label,
                            'reason': '시세 수신 실패 (Yahoo Finance)'}
                continue
            st = _series_stats(arr)
            st.update({'available': True, 'label': label,
                       'source': 'Yahoo Finance 일봉'})
            out[key] = st
        return out
    return _cached("global", _TTL_GLOBAL, _build)


# ─────────────────────────────────────────────────────────────────────────────
# 2. 국내 지수 국면 — 종목이 상장된 시장으로 본다
# ─────────────────────────────────────────────────────────────────────────────

def market_of_ticker(ticker):
    """'035760.KQ' → 'KOSDAQ'. 접미사가 없으면 KOSPI 로 본다."""
    return "KOSDAQ" if str(ticker or "").upper().endswith(".KQ") else "KOSPI"


def fetch_domestic_context(engine, market="KOSPI"):
    def _build():
        r = engine.get_index_regime(market)
        if not r or not r.get('available'):
            return {'available': False, 'market': market,
                    'reason': (r or {}).get('reason', '지수 데이터 미수신')}
        price, sma20, sma60 = r['price'], r['sma20'], r['sma60']
        if price > sma20 > sma60:
            code, label = 'BULL_STRONG', '강세 (지수 20일선·60일선 위)'
        elif price > sma20:
            code, label = 'BULL_MILD', '약강세 (20일선 위·60일선 아래)'
        elif price < sma20 < sma60 and price < sma60:
            code, label = 'BEAR_PANIC', '약세 (20일선·60일선 아래)'
        else:
            code, label = 'SIDEWAYS', '중립 (이동평균 혼조)'
        return {
            'available': True, 'market': market, 'regime_code': code,
            'regime_label': label, 'price': price, 'sma20': sma20, 'sma60': sma60,
            'basis': (f"{market} {price:,.2f} vs 20일선 {sma20:,.2f}·"
                      f"60일선 {sma60:,.2f} 기준"),
            'source': '네이버 금융 지수 일봉',
        }
    return _cached(f"dom:{market}", _TTL_GLOBAL, _build)


def fetch_domestic_detail(engine, market="KOSPI"):
    """
    지수 상세 — 이격도·최근 등락·52주 위치. 전부 일봉 실계산이다 (해석 없음).
    반환: {'available', 'market', 'price', 'disp20', 'disp60',
           'chg5', 'chg20', 'pos52', 'hi52', 'lo52'}
    """
    def _build():
        try:
            r = engine.fetch_index_daily(market, count=280)
        except Exception:
            r = None
        if not r:
            return {'available': False, 'market': market}
        _dates, closes = r
        try:
            c = [float(x) for x in closes]
        except Exception:
            return {'available': False, 'market': market}
        if len(c) < 60:
            return {'available': False, 'market': market}
        price = c[-1]
        sma20 = sum(c[-20:]) / 20.0
        sma60 = sum(c[-60:]) / 60.0
        w52 = c[-252:] if len(c) >= 252 else c
        hi52, lo52 = max(w52), min(w52)
        return {
            'available': True, 'market': market, 'price': price,
            'disp20': (price / sma20 - 1) * 100,
            'disp60': (price / sma60 - 1) * 100,
            'chg5': ((price / c[-6] - 1) * 100) if len(c) >= 6 else None,
            'chg20': ((price / c[-21] - 1) * 100) if len(c) >= 21 else None,
            'pos52': (((price - lo52) / (hi52 - lo52) * 100)
                      if hi52 > lo52 else None),
            'hi52': hi52, 'lo52': lo52,
        }
    return _cached(f"domd:{market}", _TTL_GLOBAL, _build)


# ─────────────────────────────────────────────────────────────────────────────
# 3. 종목 뉴스 (연관기사 포함)
# ─────────────────────────────────────────────────────────────────────────────

#: 제목에 이 말이 있으면 '확인이 필요한 위험 신호'로 본다. 해석이 아니라 낱말 일치다.
NEWS_RISK_KEYWORDS = (
    "유상증자", "무상감자", "감자", "전환사채", "신주인수권", "메자닌",
    "횡령", "배임", "분식", "회계처리 위반", "감사의견 거절", "한정의견",
    "상장폐지", "관리종목", "거래정지", "불성실공시", "투자경고", "투자위험",
    "영업정지", "리콜", "화재", "폭발", "파업", "소송", "특허침해",
    "회생절차", "파산", "워크아웃", "채무불이행", "디폴트",
    "블록딜", "지분매각", "대량매도", "최대주주 변경", "경영권 분쟁",
    "실적 쇼크", "어닝쇼크", "적자전환", "하향 조정", "목표주가 하향",
)

#: 참고로만 표시하는 낱말. 점수를 올리는 데는 절대 쓰지 않는다.
NEWS_WATCH_KEYWORDS = (
    "수주", "계약", "공급", "인수", "합병", "자사주", "배당", "액면분할",
    "신제품", "승인", "허가", "특허", "증설", "흑자전환", "어닝서프라이즈",
    "목표주가 상향", "상향 조정", "무상증자",
)

# ─────────────────────────────────────────────────────────────────────
# 위험 낱말 오탐 걸러내기 (라운드 98)
#
# ■ 무슨 일이 있었나
#   농심 기사 '"불닭만 잘나가는 게 아니네"…해외서 인기 폭발한 K-라면' 이
#   '폭발' 때문에 위험으로 잡혔다. 상한 넷 중 **가장 낮은 값이 뉴스**여서
#   최종 점수를 55 로 정했다(그것이 없었으면 59). 결론(HOLD)은 안 바뀌지만
#   **틀린 이유를 사용자에게 보여 주고 있었다.**
#
# ■ 감으로 목록을 손보지 않았다 — 실제 기사 219건을 먼저 셌다
#   위험 낱말이 걸린 기사 11건 중 **4건이 오탐**이었고, 모양이 셋이었다:
#     ⓐ 더 긴 낱말의 일부   '디폴트옵션'(퇴직연금 상품) · '폭발세'
#     ⓑ 상태를 뒤집는 말    '회생절차 **종결** 신청'
#     ⓒ 앞말이 성격을 정함  '인기 폭발' · '수요 폭발'
#   셋은 서로 다른 규칙이라 하나로 뭉치면 또 놓친다.
#
# ■ 해석하지 않는다
#   이 모듈의 규칙은 그대로다 — 낱말 일치만 하고 기사 뜻을 추측하지 않는다.
#   아래는 '같은 글자가 다른 낱말일 때'를 가리는 장치이지, 감성 판단이
#   아니다. 라운드 91·92 가 문장부호·띄어쓰기에서 한 것과 같은 성질이다.

#: ⓐ 위험 낱말을 **품고 있는 다른 낱말**. 여기에 걸리면 그 자리는 세지 않는다.
#:    실제 기사에서 관측된 것만 적는다 — 지어내지 않는다.
NEWS_RISK_COLLISIONS = (
    "디폴트옵션",          # 퇴직연금 상품명 (채무불이행 아님)
    "폭발세", "폭발적",     # '빚투 폭발세' 처럼 세勢·的 이 붙어 다른 뜻
    "감자탕", "감자칩", "감자전",   # 식품 (무상감자 아님)
    "소송법", "소송절차",   # 제도 일반
)

#: ⓑ 위험 낱말 **뒤**에 가까이 오면 그 위험이 끝났다는 뜻인 말
NEWS_RISK_RESOLVED = ("종결", "졸업", "해제", "철회", "취하", "기각",
                      "승소", "면제", "해소", "완료", "무혐의", "각하")

#: ⓒ 낱말만으로는 못 정하는 것 — **사고 맥락이 같이 있어야** 위험으로 센다.
#:    맥락이 없으면 '확인 필요'로 표시만 하고 점수 상한을 걸지 않는다.
#:    (제목 한 낱말로 매수를 막는 것이 이번 사고의 원인이었다)
NEWS_RISK_SOFT = {
    "폭발": ("공장", "가스", "사고", "화재", "사망", "부상", "대피",
             "붕괴", "폭발물", "누출"),
    "화재": ("공장", "창고", "사업장", "사망", "부상", "대피", "진화"),
    "소송": ("피소", "패소", "손해배상", "제기", "피고", "특허침해",
             "집단소송"),
    "파업": ("돌입", "장기화", "전면", "총파업", "무기한"),
    "감자": ("무상감자", "자본감소", "주식병합", "감자 결정", "결손"),
}

#: 뒤집는 말을 찾을 거리 — 제목에서 위험어 뒤 이만큼 안에 있으면 본다.
#: (문장 전체를 보면 관계없는 낱말까지 걸린다)
_RESOLVED_WINDOW = 12


def risk_hits_of(title):
    """제목 → (확정 위험 낱말, 확인 필요 낱말).

    **낱말 일치만 한다.** 기사 뜻을 추측하지 않는다.
    확정과 '확인 필요'를 나누는 이유: 제목 한 낱말로 매수를 막는 것이
    라운드 98 사고의 원인이었다. 애매하면 막지 말고 보여 준다.
    """
    t = str(title or '')
    hard, review = [], []
    for w in NEWS_RISK_KEYWORDS:
        i = t.find(w)
        if i < 0:
            continue
        # ⓐ 더 긴 낱말의 일부인가
        if any(c in t and t.find(c) <= i < t.find(c) + len(c)
               for c in NEWS_RISK_COLLISIONS if w in c):
            continue
        # ⓑ 뒤에 상태를 뒤집는 말이 가까이 오는가
        tail = t[i + len(w):i + len(w) + _RESOLVED_WINDOW]
        if any(r in tail for r in NEWS_RISK_RESOLVED):
            continue
        # ⓒ 맥락이 있어야 하는 낱말인가
        if w in NEWS_RISK_SOFT:
            if any(c in t for c in NEWS_RISK_SOFT[w]):
                hard.append(w)
            else:
                review.append(w)
            continue
        hard.append(w)
    return hard, review


def _clean_title(s):
    """제목 정리 — HTML 엔티티(&quot; 등)를 원래 글자로 되돌리고 공백을 정리한다."""
    return re.sub(r'\s+', ' ', _html.unescape(str(s or ''))).strip()


#: 뉴스 범위 분류 낱말 (제목 낱말 일치 — 기사 내용 해석이 아니다)
_SCOPE_MACRO = ("금리", "연준", "Fed", "환율", "달러", "국채", "물가", "CPI", "관세",
                "무역", "GDP", "경기침체", "유가")
_SCOPE_MARKET = ("코스피", "코스닥", "증시", "주식시장", "외국인 순매", "기관 순매",
                 "시가총액", "공매도", "밸류업")
_SCOPE_SECTOR = ("업종", "반도체주", "바이오주", "2차전지주", "금융주", "건설주",
                 "게임주", "엔터주", "방산주", "조선주", "화학주")
#: 시세 후행 보도 패턴 — 이미 움직인 가격을 설명하는 기사 (재료가 아니라 결과 보도)
_LAGGING_PAT = re.compile(
    r'급등|급락|상한가|하한가|신고가|신저가|[+\-]?\d+(\.\d+)?%|상승 마감|하락 마감|'
    r'52주 최고|52주 최저|불기둥|폭등|폭락')


def classify_news_scope(title):
    """제목 → 범위(거시/시장/업종/종목). 낱말 일치만 쓴다."""
    t = str(title or '')
    if any(k in t for k in _SCOPE_MACRO):
        return '거시'
    if any(k in t for k in _SCOPE_MARKET):
        return '시장'
    if any(k in t for k in _SCOPE_SECTOR):
        return '업종'
    return '종목'


def is_lagging_report(title):
    """시세 후행 보도인가 — 가격이 이미 움직인 것을 설명하는 기사는 '재료'가 아니다."""
    return bool(_LAGGING_PAT.search(str(title or '')))


def _parse_news_datetime(s):
    """'202607312027' → '2026-07-31 20:27'."""
    t = str(s or "")
    if len(t) >= 12 and t.isdigit():
        return f"{t[0:4]}-{t[4:6]}-{t[6:8]} {t[8:10]}:{t[10:12]}"
    if len(t) >= 8 and t[:8].isdigit():
        return f"{t[0:4]}-{t[4:6]}-{t[6:8]}"
    return t


def fetch_stock_news(code, limit=15, name_hint=''):
    """
    종목 뉴스 목록. 반환: {'available', 'items': [...], 'source', 'reason'}

    각 item: title, press, datetime, url, related(연관기사 목록), related_count
    네이버 종목뉴스 API 는 같은 사건을 다룬 기사를 하나로 묶어 준다.
    그 묶음을 그대로 살려 '연관 뉴스'로 보여준다.
    """
    c = re.sub(r'\D', '', str(code or ''))[:6]
    if len(c) != 6:
        return {'available': False, 'items': [], 'reason': '종목코드를 알 수 없습니다.'}

    def _build():
        j = be.fetch_json_with_retry(
            f"https://m.stock.naver.com/api/news/stock/{c}?pageSize={int(limit)}&page=1")
        if not isinstance(j, list) or not j:
            return {'available': False, 'items': [],
                    'reason': '네이버 종목뉴스 응답 없음',
                    'source': '네이버 금융 종목뉴스'}
        items = []
        for group in j:
            arts = (group or {}).get('items') or []
            if not arts:
                continue
            head = arts[0]
            rest = [{
                'title': _clean_title(a.get('titleFull') or a.get('title')),
                'press': str(a.get('officeName') or '').strip(),
                'datetime': _parse_news_datetime(a.get('datetime')),
                'url': a.get('mobileNewsUrl') or '',
            } for a in arts[1:]]
            title = _clean_title(head.get('titleFull') or head.get('title'))
            items.append({
                'title': title,
                'press': str(head.get('officeName') or '').strip(),
                'datetime': _parse_news_datetime(head.get('datetime')),
                'url': head.get('mobileNewsUrl') or '',
                'related': rest,
                'related_count': len(rest),
                # 라운드 98 — 두 곳에서 같은 한 줄을 반복하고 있었다.
                # 함수 하나로 빼서 양쪽이 **같은 것**을 부르게 한다.
                'risk_hits': risk_hits_of(title)[0],
                'risk_review': risk_hits_of(title)[1],
                'watch_hits': [k for k in NEWS_WATCH_KEYWORDS if k in title],
                # 범위·후행 분류 — 낱말 일치만. 연관 묶음(related)이 이미 반복
                # 기사 중복을 걷어낸 상태다.
                'scope': classify_news_scope(title),
                'lagging': is_lagging_report(title),
            })
        if items:
            return {'available': True, 'items': items,
                    'source': '네이버 금융 종목뉴스 (제목·언론사·시각 원문)',
                    'reason': ''}
        # ── 공개 RSS 보완 (라운드 42) ────────────────────────────────
        # 네이버 종목뉴스가 비면 뉴스 게이트가 아예 못 돈다. 그런데
        # '기사가 없다'와 '이 출처가 못 준다'는 다르다. 공개 RSS(연합뉴스·
        # 한경·매경)에서 같은 종목을 찾아 보완한다. 출처를 밝혀 섞이지 않게 한다.
        return _rss_fallback(c, name_hint)
    return _cached(f"news:{c}", _TTL_NEWS, _build)


def _rss_fallback(code, name_hint=''):
    """공개 RSS 에서 종목명으로 기사를 찾는다 (라운드 42)."""
    nm = str(name_hint or '').strip()
    if not nm:
        try:
            from bitemporal_engine import STOCK_METRICS_DB
            for k, v in (STOCK_METRICS_DB or {}).items():
                if str(k).split('.')[0] == code:
                    nm = str(v.get('name') or '')
                    break
        except Exception:
            nm = ''
    if not nm:
        return {'available': False, 'items': [],
                'reason': '종목명을 알 수 없어 RSS 보완을 하지 못했습니다.'}
    try:
        import news_feed as _nf
        s = _nf.for_stock(nm)
    except Exception as e:
        return {'available': False, 'items': [],
                'reason': f'RSS 보완 실패 ({type(e).__name__})'}
    items = []
    for h in s.get('headlines') or []:
        title = h.get('title') or ''
        items.append({
            'title': title, 'press': h.get('source', ''),
            'datetime': h.get('when', ''), 'url': h.get('link', ''),
            'related': [], 'related_count': 0,
            'risk_hits': risk_hits_of(title)[0],
            'risk_review': risk_hits_of(title)[1],
            'watch_hits': [k for k in NEWS_WATCH_KEYWORDS if k in title],
            'scope': classify_news_scope(title),
            'lagging': is_lagging_report(title),
        })
    return {'available': bool(items), 'items': items,
            'source': '공개 RSS 보완 (연합뉴스·한국경제·매일경제 · 제목·시각만)',
            'reason': '' if items else '네이버·RSS 양쪽에 기사가 없습니다.'}


def fetch_stock_disclosures(code, limit=10):
    """
    종목 공시 목록 — 네이버 금융 공시정보(원천 KOSCOM/거래소 게시) 스크래핑.

    제목·정보제공·날짜를 **원문 그대로** 나열만 한다. 공시 내용을 요약·해석해
    만들어 내지 않는다 (날조 금지 원칙). 반환:
    {'available', 'items': [{'title','provider','date','url'}], 'source', 'reason'}
    """
    c = re.sub(r'\D', '', str(code or ''))[:6]
    if len(c) != 6:
        return {'available': False, 'items': [], 'reason': '종목코드를 알 수 없습니다.'}

    def _build():
        import urllib.request
        url = f"https://finance.naver.com/item/news_notice.naver?code={c}&page=1"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=8) as r:
                body = r.read().decode('euc-kr', 'replace')
        except Exception as e:
            return {'available': False, 'items': [],
                    'reason': f'공시 페이지 수신 실패: {e}',
                    'source': '네이버 금융 공시정보'}
        rows = re.findall(
            r'<td class="title">\s*<a href="([^"]+)"[^>]*>([^<]+)</a>.*?'
            r'<td[^>]*>\s*([^<]*?)\s*</td>\s*<td[^>]*>\s*([\d.]+)\s*</td>',
            body, re.S)
        items = [{
            'title': t.strip(),
            'provider': prov.strip(),
            'date': d.strip(),
            'url': 'https://finance.naver.com' + href,
        } for href, t, prov, d in rows[:int(limit)]]
        return {'available': bool(items), 'items': items,
                'source': '네이버 금융 공시정보 (제목·정보제공·날짜 원문)',
                'reason': '' if items else '표시할 공시가 없습니다.'}
    return _cached(f"disc:{c}", _TTL_NEWS, _build)


def summarize_news_flags(news):
    """
    뉴스 목록 → 위험 낱말 요약. 기사 내용을 해석하지 않는다.
    반환: {'risk_titles': [(제목, [걸린 낱말])], 'risk_count', 'watch_count', 'total'}
    """
    items = (news or {}).get('items') or []
    risk = [(it['title'], it['risk_hits']) for it in items if it.get('risk_hits')]
    watch = sum(1 for it in items if it.get('watch_hits'))
    # 신선한 참고 재료 = 종목 뉴스 + 참고 낱말 + 시세 후행 보도가 아님.
    # (이미 급등한 걸 설명하는 기사는 '재료'가 아니라 '결과'다)
    fresh_watch = sum(1 for it in items
                      if it.get('watch_hits') and not it.get('lagging')
                      and it.get('scope') == '종목')
    # 라운드 42 — 룰북의 뉴스 게이트가 쓸 수 있게 두 가지를 더 싣는다.
    #  · risk_words   : 어떤 낱말이 걸렸는지 (화면에 사유로 적어야 한다)
    #  · feed_available: 뉴스를 **받기는 했는가**.
    #    받지 못한 것과 악재가 없는 것은 다르다. 미수신을 '악재 없음'으로
    #    읽으면 데이터 장애가 매수 허가로 둔갑한다.
    risk_words = sorted({w for _, hits in risk for w in (hits or [])})
    # 라운드 98 — '확인 필요'(맥락이 없어 확정 못 한 것)를 따로 싣는다.
    # 점수 상한은 안 걸지만 **안 보이면 없는 것과 같다.** 사용자가
    # 직접 판단할 수 있게 화면이 읽어 갈 자리를 만든다.
    review = [(it['title'], it.get('risk_review') or [])
              for it in items if it.get('risk_review')]
    return {
        'risk_titles': risk,
        'risk_count': len(risk),
        'risk_words': risk_words,
        'review_titles': review,
        'review_count': len(review),
        'review_words': sorted({w for _, hs in review for w in (hs or [])}),
        'watch_count': watch,
        'fresh_watch_count': fresh_watch,
        'lagging_count': sum(1 for it in items if it.get('lagging')),
        'by_scope': {s: sum(1 for it in items if it.get('scope') == s)
                     for s in ('종목', '업종', '시장', '거시')},
        'total': len(items),
        'total_count': len(items),
        'feed_available': bool((news or {}).get('available', bool(items))),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 4. 종합 — 점수 상한(cap)과 사유
# ─────────────────────────────────────────────────────────────────────────────

def score_global_risk(glob, rules=None):
    """
    글로벌 지표 → 0~100 위험 점수(높을수록 안전) + 감점 내역.

    규칙집 [RULES_MARKET_CONTEXT] 의 감점표를 그대로 적용한다. 지표를 못 받으면
    그 항목은 감점하지 않고 '미수신'으로 남긴다 — 못 받은 것을 나쁘게도, 좋게도
    치지 않는다. 하나도 못 받으면 None 을 돌려주고 호출자가 항목을 뺀다.
    반환: (점수 또는 None, [감점 내역], [미수신 항목])
    """
    r = dict(rules or {})

    def g(k, d):
        try:
            return float(r.get(k, d))
        except (TypeError, ValueError):
            return d

    score = g('global_base', 100.0)
    hits, missing, seen = [], [], 0

    sp = (glob or {}).get('sp500') or {}
    if sp.get('available'):
        seen += 1
        if sp.get('above_sma60') is False:
            p = g('penalty_sp500_below_sma60', 12)
            score -= p
            hits.append((f"S&P500 이 60일선 아래 ({sp['price']:,.0f} < {sp['sma60']:,.0f})", p))
    else:
        missing.append("S&P500")

    nq = (glob or {}).get('nasdaq') or {}
    if nq.get('available'):
        seen += 1
        dd = nq.get('drawdown_pct')
        if dd is not None and dd <= g('nasdaq_drawdown_pct', -10.0):
            p = g('penalty_nasdaq_drawdown', 15)
            score -= p
            hits.append((f"나스닥 최근 고점 대비 {dd:.1f}%", p))
    else:
        missing.append("나스닥")

    vx = (glob or {}).get('vix') or {}
    if vx.get('available'):
        seen += 1
        v = vx.get('price')
        if v is not None and v >= g('vix_extreme', 35.0):
            p = g('penalty_vix_extreme', 25)
            score -= p
            hits.append((f"VIX {v:.1f} (공포 구간)", p))
        elif v is not None and v >= g('vix_warn', 25.0):
            p = g('penalty_vix_warn', 10)
            score -= p
            hits.append((f"VIX {v:.1f} (경계 구간)", p))
    else:
        missing.append("VIX")

    fx = (glob or {}).get('usdkrw') or {}
    if fx.get('available'):
        seen += 1
        c = fx.get('chg20_pct')
        if c is not None and c >= g('fx_spike_20d_pct', 3.0):
            p = g('penalty_fx_spike', 10)
            score -= p
            hits.append((f"원/달러 20일 {c:+.1f}% (원화 약세)", p))
    else:
        missing.append("원/달러")

    if seen == 0:
        return None, [], missing
    return max(0.0, min(100.0, score)), hits, missing


def score_news_risk(news_flags, news_available, rules=None):
    """
    뉴스 위험 낱말 → 0~100 점수(높을수록 안전).

    제목에 위험 낱말이 있는 기사 1건마다 감점한다. 기사를 못 받았으면
    중립값을 쓰고 그 사실을 함께 돌려준다 — 못 받은 것을 안전하다고 치지 않는다.
    반환: (점수, 설명)
    """
    r = dict(rules or {})

    def g(k, d):
        try:
            return float(r.get(k, d))
        except (TypeError, ValueError):
            return d

    if not news_available:
        return g('news_unavailable_score', 60), "뉴스 미수신 — 중립값 적용"
    n = int((news_flags or {}).get('risk_count', 0) or 0)
    total = int((news_flags or {}).get('total', 0) or 0)
    if n == 0:
        return g('news_base', 100), f"최근 기사 {total}건에 위험 낱말 없음"
    score = max(g('news_score_floor', 25),
                g('news_base', 100) - n * g('news_penalty_per_article', 25))
    return score, f"위험 낱말 기사 {n}건 (기사 {total}건 중) — 1건당 " \
                  f"{g('news_penalty_per_article', 25):.0f}점 감점"


def score_market_regime(domestic, glob, rules=None):
    """
    상장시장 국면 + 글로벌 위험 → 시장 국면 점수(0~100).

    한쪽이 미수신이면 그 가중치를 0으로 두고 나머지로 재정규화한다.
    둘 다 미수신이면 None — 이 항목을 빼고 나머지 항목으로 판정한다.
    반환: (점수 또는 None, 내역 dict)
    """
    r = dict(rules or {})

    def g(k, d):
        try:
            return float(r.get(k, d))
        except (TypeError, ValueError):
            return d

    dom_score = None
    if (domestic or {}).get('available'):
        dom_score = {
            'BULL_STRONG': g('score_bull_strong', 78),
            'BULL_MILD': g('score_bull_mild', 70),
            'SIDEWAYS': g('score_sideways', 55),
            'BEAR_PANIC': g('score_bear_panic', 32),
        }.get(domestic.get('regime_code'))

    glob_score, glob_hits, glob_missing = score_global_risk(glob, r)

    w_dom = g('weight_domestic_regime', 0.60)
    w_glob = g('weight_global_risk', 0.40)
    parts, wsum, total = [], 0.0, 0.0
    if dom_score is not None:
        total += dom_score * w_dom
        wsum += w_dom
        parts.append(('국내 지수 국면', dom_score, w_dom))
    if glob_score is not None:
        total += glob_score * w_glob
        wsum += w_glob
        parts.append(('글로벌 위험', glob_score, w_glob))

    detail = {
        'domestic_score': dom_score,
        'domestic_label': (domestic or {}).get('regime_label'),
        'domestic_basis': (domestic or {}).get('basis'),
        'global_score': glob_score,
        'global_hits': glob_hits,
        'global_missing': glob_missing,
        'parts': parts,
        'renormalized': (dom_score is None) != (glob_score is None),
    }
    if wsum <= 0:
        detail['reason'] = "국내 지수·글로벌 지표를 모두 받지 못해 시장 국면을 산출하지 않습니다."
        return None, detail
    return round(total / wsum, 1), detail


#: 상한 규칙. (조건 이름, 상한점수) — 여러 개가 걸리면 가장 낮은 값이 적용된다.
CONTEXT_CAPS = {
    'domestic_bear': 55,      # 상장 시장 지수가 20·60일선 아래
    'global_stress_high': 58,  # 글로벌 위험지표 2개 이상 경고
    'vix_extreme': 50,        # VIX 35 이상
    'news_risk': 55,          # 제목에 위험 낱말이 있는 기사 존재
}

VIX_WARN = 25.0
VIX_EXTREME = 35.0
FX_SPIKE_20D_PCT = 3.0        # 원/달러 20일 상승률
NASDAQ_DRAWDOWN_PCT = -10.0   # 나스닥 최근 고점 대비


def build_market_context(engine, ticker, code=None, with_news=True):
    """
    한 종목을 판정할 때 함께 볼 판(板)을 모은다.

    반환 dict:
      domestic / global / news / flags / caps / cap_score / reasons / notes
    """
    market = market_of_ticker(ticker)
    dom = fetch_domestic_context(engine, market)
    glob = fetch_global_context()
    news = fetch_stock_news(code or str(ticker or '').split('.')[0]) if with_news \
        else {'available': False, 'items': [], 'reason': '뉴스 조회를 건너뜀'}
    nflags = summarize_news_flags(news)

    caps, reasons, warns = {}, [], []

    # ① 국내 — 그 종목이 상장된 시장 기준
    if dom.get('available'):
        if dom['regime_code'] == 'BEAR_PANIC':
            caps['domestic_bear'] = CONTEXT_CAPS['domestic_bear']
            reasons.append(f"{market} 지수가 20일선·60일선 아래 ({dom['basis']})")
    else:
        warns.append(f"{market} 지수 국면 미수신 — {dom.get('reason', '')}")

    # ② 글로벌 — 경고 항목을 세어 본다
    g_warn = []
    vix = glob.get('vix', {})
    if vix.get('available'):
        if vix['price'] >= VIX_EXTREME:
            caps['vix_extreme'] = CONTEXT_CAPS['vix_extreme']
            g_warn.append(f"VIX {vix['price']:.1f} (≥{VIX_EXTREME:.0f} 공포 구간)")
        elif vix['price'] >= VIX_WARN:
            g_warn.append(f"VIX {vix['price']:.1f} (≥{VIX_WARN:.0f} 경계)")
    else:
        warns.append("VIX 미수신")

    sp = glob.get('sp500', {})
    if sp.get('available'):
        if sp.get('above_sma60') is False:
            g_warn.append(f"S&P500 이 60일선 아래 ({sp['price']:,.0f} < {sp['sma60']:,.0f})")
    else:
        warns.append("S&P500 미수신")

    nq = glob.get('nasdaq', {})
    if nq.get('available') and nq.get('drawdown_pct') is not None:
        if nq['drawdown_pct'] <= NASDAQ_DRAWDOWN_PCT:
            g_warn.append(f"나스닥 최근 고점 대비 {nq['drawdown_pct']:.1f}%")

    fx = glob.get('usdkrw', {})
    if fx.get('available') and fx.get('chg20_pct') is not None:
        if fx['chg20_pct'] >= FX_SPIKE_20D_PCT:
            g_warn.append(f"원/달러 20일 {fx['chg20_pct']:+.1f}% (원화 약세)")

    if len(g_warn) >= 2:
        caps['global_stress_high'] = CONTEXT_CAPS['global_stress_high']
        reasons.append("글로벌 위험 신호 " + str(len(g_warn)) + "건 — " + " / ".join(g_warn))
    elif g_warn:
        reasons.append("글로벌 위험 신호 1건 — " + g_warn[0] + " (상한 미적용)")

    # ③ 뉴스 — 낱말 일치만으로 위험을 표시한다
    if nflags['risk_count'] > 0:
        caps['news_risk'] = CONTEXT_CAPS['news_risk']
        first = nflags['risk_titles'][0]
        reasons.append(f"뉴스 제목에 확인이 필요한 낱말 {nflags['risk_count']}건 — "
                       f"'{first[0][:40]}' ({', '.join(first[1])})")
    elif not news.get('available'):
        warns.append("종목 뉴스 미수신 — " + str(news.get('reason', '')))

    cap_score = min(caps.values()) if caps else None
    return {
        'market': market,
        'domestic': dom,
        'global': glob,
        'global_warnings': g_warn,
        'news': news,
        'news_flags': nflags,
        'caps': caps,
        'cap_score': cap_score,
        'reasons': reasons,
        'notes': warns,
    }
