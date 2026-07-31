"""
오늘의 시장 관심종목 발굴 (§A).

설계 원칙:
    1. 관심점수와 매수점수는 다른 것이다.
       market_attention_score  = 지금 시장에서 얼마나 주목받는가
       final_action_score      = 지금 실제로 매매할 가치가 있는가
       관심점수가 높다는 이유로 추천에 넣지 않는다. TOP3 순위에서는 동점 보조기준으로만
       쓰고 실질 영향도를 5% 이내로 제한한다 (ATTENTION_TIEBREAK_MAX_PCT).

    2. 수집하지 못한 데이터는 만들어내지 않는다.
       포털 검색량·조회수·뉴스 건수는 연동돼 있지 않다. 해당 항목은 가중치를 0으로 두고
       나머지 유효 항목에 재정규화한 뒤, 화면에 무엇이 빠졌는지 그대로 표시한다.

    3. 전 종목에 일봉을 받아오지 않는다.
       코스피·코스닥 2,900여 종목에 종목당 일봉을 요청하면 스캔이 끝나지 않는다.
       네이버 '순위 페이지'(거래대금 상위·상승률 상위·투자자별 순매수 상위)로 후보를
       먼저 좁힌 뒤, 그 후보에만 일봉을 받아 실제 지표를 계산한다.
       순위 페이지 자체가 '오늘 관심이 몰린 종목' 이라는 1차 신호다.

    4. 비공식 API·로그인 데이터는 쓰지 않는다. 공개된 시세 페이지만 읽는다.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import numpy as np

import bitemporal_engine as be


# ─────────────────────────────────────────────────────────────────────────────
# 관심점수 구성요소
# availability: 'full'    실제 지표로 계산됨
#               'partial' 일부만 연동됨 (한계를 label 에 명시)
#               'none'    미연동 — 가중치 0, 나머지에 재정규화
# ─────────────────────────────────────────────────────────────────────────────
COMPONENT_SPEC = [
    {'key': 'turnover_surge', 'label': '거래대금 이상 증가', 'weight': 0.25,
     'availability': 'full',
     'detail': '최근 확정 거래대금 ÷ 20일 평균 거래대금'},
    {'key': 'event_catalyst', 'label': '뉴스·공시 촉매', 'weight': 0.20,
     'availability': 'none',
     'detail': 'DART·KIND 공시 API 미연동 — 기사 건수를 임의로 세지 않는다'},
    {'key': 'price_volatility', 'label': '가격·변동성 변화', 'weight': 0.15,
     'availability': 'full',
     'detail': '갭, ATR 확대(ATR5÷ATR20), 당일 변동폭'},
    {'key': 'investor_flow', 'label': '외국인·기관 수급', 'weight': 0.15,
     'availability': 'partial',
     'detail': '투자자별 순매수 "상위 목록 진입 여부"만 반영. '
               '전 종목 5·20일 누적 순매수 시계열은 미연동'},
    {'key': 'sector_rs', 'label': '업종 상대강도', 'weight': 0.10,
     'availability': 'none',
     'detail': '업종 분류가 종목당 개별 조회라 전 종목 상대강도 산출 불가'},
    {'key': 'trend_breakout', 'label': '기술적 돌파', 'weight': 0.10,
     'availability': 'full',
     'detail': '20·60일 고점 돌파 여부와 고점 대비 위치'},
    {'key': 'liquidity', 'label': '유동성', 'weight': 0.05,
     'availability': 'full',
     'detail': '20일 평균 거래대금 (슬리피지 감내 가능성)'},
]

#: 관심점수가 TOP3 최종 순위에 미칠 수 있는 최대 영향 (§12)
ATTENTION_TIEBREAK_MAX_PCT = 5.0

#: 후보 발굴 방식
STRATEGIES = [
    ('composite',  '종합 이슈'),
    ('turnover',   '거래대금 급증'),
    ('news',       '뉴스·공시'),
    ('flow',       '외국인·기관'),
    ('breakout',   '추세 돌파'),
    ('pullback',   '상승추세 눌림'),
    ('demark',     'DeMARK 반전'),
    ('monthly10',  '월봉 10선'),
    ('marketcap',  '시총 상위'),
    ('watchlist',  '사용자 관심종목'),
]
STRATEGY_LABELS = dict(STRATEGIES)

#: 현재 데이터로는 후보를 만들 수 없는 방식 (선택 시 사유를 알리고 대체 방식을 권한다)
STRATEGY_UNAVAILABLE = {
    'news': '공시·뉴스 API가 연동되지 않아 촉매 기반 후보를 만들 수 없습니다. '
            '기사 건수를 임의로 세지 않습니다.',
}

#: 유동성 하한 — 이보다 작으면 슬리피지로 전략이 성립하지 않는다
MIN_AVG_TURNOVER_KRW = 2_000_000_000

#: 관심점수 계산에 일봉을 받아올 최대 후보 수 (스캔 시간 상한)
DEEP_POOL_MAX = 120


def available_components():
    return [c for c in COMPONENT_SPEC if c['availability'] != 'none']


def effective_weights():
    """미연동 항목의 가중치를 유효 항목에 재정규화한다 (§14)."""
    avail = available_components()
    total = sum(c['weight'] for c in avail)
    if total <= 0:
        return {}
    return {c['key']: c['weight'] / total for c in avail}


def data_status():
    """화면에 그대로 띄울 데이터 연동 현황."""
    w = effective_weights()
    out = []
    for c in COMPONENT_SPEC:
        out.append({
            'label': c['label'],
            'availability': c['availability'],
            'spec_weight_pct': c['weight'] * 100.0,
            'effective_weight_pct': w.get(c['key'], 0.0) * 100.0,
            'detail': c['detail'],
        })
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 1단계 — 순위 페이지로 후보 모으기 (종목당 조회 없음)
# ─────────────────────────────────────────────────────────────────────────────
_SOSOK = {'KOSPI': 0, 'KOSDAQ': 1}

#: ETF·ETN·인버스·레버리지는 기업 분석 대상이 아니다. 거래대금 상위를 이들이 뒤덮는다.
_FUND_TOKENS = ('KODEX', 'TIGER', 'KBSTAR', 'ARIRANG', 'HANARO', 'SOL ', 'ACE ',
                'PLUS ', 'RISE ', 'TIMEFOLIO', 'KOSEF', 'SMART ', 'FOCUS ',
                'KINDEX', 'KTOP', 'TREX', '히어로즈', '마이다스', 'ITF',
                'ETN', 'ETF', '인버스', '레버리지', '선물', '커버드콜', '채권',
                '인덱스', '지수', 'TR)', '합성', '리츠', 'REIT')

#: 브랜드명을 나열하는 방식은 새 상품이 나올 때마다 샌다. 구조적 규칙을 함께 쓴다.
#:  · 이름에 지수 번호가 들어감: '파워 200', 'HK 200', 'KODEX 200'
#:  · 만기·배수 표기: '2X', '3X', 'H)' 등
_FUND_PATTERNS = (
    re.compile(r'(^|\s)\d{2,3}(\s|$)'),        # 200, 500 같은 지수 번호가 독립 토큰
    re.compile(r'\d+X$|\dX\s'),                # 2X, 3X 배수형
    re.compile(r'\(H\)|\(합성'),
)


def _is_fund_like(name):
    n = str(name or '')
    if any(t in n for t in _FUND_TOKENS):
        return True
    return any(p.search(n) for p in _FUND_PATTERNS)


def _clean(html_cell):
    return re.sub(r'<.*?>', '', html_cell or '').replace('\n', '').replace('\t', '').strip()


def _num(text):
    s = re.sub(r'[^\d.\-]', '', str(text or ''))
    try:
        return float(s)
    except ValueError:
        return None


def _parse_rank_table(html, source_tag, limit=None):
    """
    네이버 순위 페이지의 표를 읽는다.
    거래상위/상승률 페이지는 열 구성이 같다:
        N 종목명 현재가 전일비 등락률 거래량 거래대금 매수호가 매도호가 시가총액 PER ROE

    ⚠️ '상승률 상위' 페이지는 페이지당 상위 N개가 아니라 정렬된 전 종목을 돌려준다.
       전부 담으면 '상위'라는 신호가 사라지므로 문서 순서 앞쪽만 취한다.
    """
    out = {}
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', html or '', re.S):
        if limit is not None and len(out) >= limit:
            break
        m = re.search(r'code=(\d{6})', tr)
        if not m:
            continue
        tds = [_clean(t) for t in re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)]
        if len(tds) < 7:
            continue
        code = m.group(1)
        name = tds[1]
        if not name or _is_fund_like(name) or be.BitemporalEngine._is_excluded_name(name):
            continue
        out[code] = {
            'code': code,
            'name': name,
            'price': _num(tds[2]),
            'change_pct': _num(tds[4]),
            'volume': _num(tds[5]),
            'turnover_mil': _num(tds[6]),          # 백만원
            'market_cap_eok': _num(tds[9]) if len(tds) > 9 else None,
            'sources': {source_tag},
        }
    return out


def _parse_flow_names(html):
    """투자자별 순매수 상위 페이지에서 종목명만 뽑는다 (열 구성이 페이지마다 달라 이름만 신뢰)."""
    names = set()
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', html or '', re.S):
        if 'code=' not in tr:
            continue
        m = re.search(r'code=\d{6}[^>]*>([^<]+)<', tr)
        if m:
            nm = m.group(1).strip()
            if nm and not _is_fund_like(nm):
                names.add(nm)
    return names


def fetch_candidate_pool(pages_per_source=2, progress=None):
    """
    순위 페이지에서 후보를 모은다. 반환: (pool_dict, flow_names_set, source_report)

    pool_dict[code] = {code, name, price, change_pct, volume, turnover_mil,
                       market_cap_eok, sources}
    """
    pool, report = {}, []

    def merge(part, tag):
        for code, row in part.items():
            if code in pool:
                pool[code]['sources'].add(tag)
            else:
                pool[code] = row

    specs = [
        ('거래대금 상위', 'https://finance.naver.com/sise/sise_quant.naver?sosok={s}&page={p}',
         'turnover', 60),
        ('상승률 상위', 'https://finance.naver.com/sise/sise_rise.naver?sosok={s}&page={p}',
         'rise', 40),
    ]
    for label, tmpl, tag, per_page in specs:
        got = 0
        for market, sosok in _SOSOK.items():
            for page in range(1, pages_per_source + 1):
                url = tmpl.format(s=sosok, p=page)
                if progress:
                    progress(f"{label} · {market} {page}페이지")
                try:
                    html = be.fetch_html_with_retry(url)
                except Exception:
                    continue
                part = _parse_rank_table(html, tag, limit=per_page)
                got += len(part)
                merge(part, tag)
        report.append({'source': label, 'count': got, 'ok': got > 0})

    # 투자자별 순매수 상위 — 이름 기준 '진입 여부'만 쓴다
    flow_names = set()
    flow_ok = 0
    for inv_label, gubun in (('외국인', 9000), ('기관', 1000)):
        for market, sosok in _SOSOK.items():
            url = (f"https://finance.naver.com/sise/sise_deal_rank.naver"
                   f"?sosok={sosok}&investor_gubun={gubun}&type=buy")
            if progress:
                progress(f"{inv_label} 순매수 상위 · {market}")
            try:
                html = be.fetch_html_with_retry(url)
            except Exception:
                continue
            got = _parse_flow_names(html)
            flow_names |= got
            flow_ok += len(got)
    report.append({'source': '외국인·기관 순매수 상위', 'count': flow_ok, 'ok': flow_ok > 0})

    return pool, flow_names, report


# ─────────────────────────────────────────────────────────────────────────────
# 2단계 — 후보에만 일봉을 받아 실제 지표 계산
# ─────────────────────────────────────────────────────────────────────────────
def fetch_daily_bars(code, count=260):
    """네이버 차트 XML → (dates, open, high, low, close, volume) numpy 배열. 실패 시 None."""
    url = (f"https://fchart.stock.naver.com/sise.nhn?symbol={code}"
           f"&timeframe=day&count={int(count)}&requestType=0")
    try:
        xml = be.fetch_html_with_retry(url)
        root = ET.fromstring(xml)
    except Exception:
        return None
    o, h, l, c, v, d = [], [], [], [], [], []
    for item in root.iter('item'):
        parts = (item.get('data') or '').split('|')
        if len(parts) < 6:
            continue
        try:
            d.append(parts[0])
            o.append(float(parts[1])); h.append(float(parts[2]))
            l.append(float(parts[3])); c.append(float(parts[4]))
            v.append(float(parts[5]))
        except ValueError:
            continue
    if len(c) < 30:
        return None
    return (np.array(d), np.array(o), np.array(h), np.array(l),
            np.array(c), np.array(v))


def _score_from_ratio(ratio, lo=1.0, hi=5.0):
    """배수 → 0~100. 로그 스케일 (3배와 5배의 체감 차이가 1배와 3배보다 작다)."""
    if ratio is None or ratio <= 0:
        return 0.0
    r = float(np.clip(ratio, lo, hi))
    return float(100.0 * (np.log(r) - np.log(lo)) / (np.log(hi) - np.log(lo) + 1e-12))


def compute_components(bars, in_flow_list=False, drop_unconfirmed=False,
                       live_turnover_krw=None):
    """
    일봉 → 관심점수 구성요소 + 부가 지표. 반환 dict.

    drop_unconfirmed: 장중이면 오늘 봉은 미완성이다. 그 값을 20일 평균과 비교하면
        배수가 왜곡되므로, 추세·돌파·변동성 같은 지표는 확정봉까지만 쓴다.

    live_turnover_krw: 순위 페이지에서 받은 '오늘 누적 거래대금'. 장중이라면
        '오늘 관심이 커지는가'라는 질문에는 이쪽이 맞는 답이다. 다만 장 초반에는
        누적이 적어 배수가 낮게 나오므로, 어느 기준을 썼는지 반드시 표시한다.
        확정 기준 배수도 함께 돌려주어 둘을 비교할 수 있게 한다.
    """
    _d, _o, high, low, close, vol = bars
    if drop_unconfirmed and len(close) > 30:
        _d, _o, high, low, close, vol = (_d[:-1], _o[:-1], high[:-1],
                                         low[:-1], close[:-1], vol[:-1])
    px = float(close[-1])
    turnover = close * vol
    t_now = float(turnover[-1])
    base = turnover[-21:-1]
    t_avg20 = float(np.mean(base)) if len(base) >= 10 else None

    # ── 거래대금 이상 증가
    ratio_confirmed = (t_now / t_avg20) if (t_avg20 and t_avg20 > 0) else None
    ratio_live = None
    if live_turnover_krw and t_avg20 and t_avg20 > 0:
        ratio_live = float(live_turnover_krw) / t_avg20
    # 장중이면 오늘 누적을, 아니면 확정 거래일을 기준으로 삼는다
    ratio = ratio_live if (drop_unconfirmed and ratio_live is not None) else ratio_confirmed
    turnover_basis = ('오늘 누적(장중)' if (drop_unconfirmed and ratio_live is not None)
                      else '직전 확정 거래일')
    turnover_score = _score_from_ratio(ratio, 1.0, 5.0)
    t5 = float(np.mean(turnover[-5:]))
    t5_ratio = (t5 / t_avg20) if (t_avg20 and t_avg20 > 0) else None

    # ── 가격·변동성 변화
    tr = np.maximum(high[1:] - low[1:],
                    np.maximum(np.abs(high[1:] - close[:-1]),
                               np.abs(low[1:] - close[:-1])))
    atr5 = float(np.mean(tr[-5:])) if len(tr) >= 5 else None
    atr20 = float(np.mean(tr[-20:])) if len(tr) >= 20 else None
    atr_exp = (atr5 / atr20) if (atr20 and atr20 > 0) else None
    gap_pct = float((_o[-1] / close[-2] - 1.0) * 100.0) if len(close) >= 2 else 0.0
    day_range_pct = float((high[-1] - low[-1]) / (px + 1e-9) * 100.0)
    vol_score = float(np.clip(
        _score_from_ratio(atr_exp, 1.0, 2.0) * 0.5
        + min(abs(gap_pct) / 5.0, 1.0) * 100 * 0.25
        + min(day_range_pct / 8.0, 1.0) * 100 * 0.25, 0, 100))

    # ── 기술적 돌파
    hi20 = float(np.max(high[-21:-1])) if len(high) >= 21 else None
    hi60 = float(np.max(high[-61:-1])) if len(high) >= 61 else None
    brk20 = bool(hi20 and px > hi20)
    brk60 = bool(hi60 and px > hi60)
    pos60 = float(px / hi60 * 100.0) if hi60 else None
    breakout_score = float(np.clip(
        (100.0 if brk60 else (75.0 if brk20 else 0.0))
        + (0.0 if (brk20 or brk60) else max(0.0, (pos60 or 0) - 85.0) * 3.0), 0, 100))

    # ── 유동성
    liq_score = _score_from_ratio(
        (t_avg20 / MIN_AVG_TURNOVER_KRW) if t_avg20 else None, 1.0, 25.0)

    # ── 수급 (상위 목록 진입 여부만)
    flow_score = 100.0 if in_flow_list else 0.0

    # ── 추세 구조 (전략별 후보 분류용)
    ma20 = float(np.mean(close[-20:]))
    ma60 = float(np.mean(close[-60:])) if len(close) >= 60 else None
    ma120 = float(np.mean(close[-120:])) if len(close) >= 120 else None
    disp20 = float((px / ma20 - 1.0) * 100.0)
    # 월봉 10선 ≈ 200 거래일 이동평균 (10개월)
    ma_m10 = float(np.mean(close[-200:])) if len(close) >= 200 else None
    ma_m10_slope = None
    if len(close) >= 220:
        prev = float(np.mean(close[-220:-20]))
        ma_m10_slope = float((ma_m10 / prev - 1.0) * 100.0)

    hi_recent = float(np.max(high[-60:])) if len(high) >= 60 else None
    drawdown_from_high = (float((px / hi_recent - 1.0) * 100.0)
                          if hi_recent else None)

    return {
        'price': px,
        'turnover_now': t_now, 'turnover_avg20': t_avg20,
        'turnover_ratio': ratio, 'turnover_ratio_5d': t5_ratio,
        'turnover_ratio_confirmed': ratio_confirmed,
        'turnover_ratio_live': ratio_live,
        'turnover_basis': turnover_basis,
        'atr_expansion': atr_exp, 'gap_pct': gap_pct,
        'day_range_pct': day_range_pct,
        'break_20d_high': brk20, 'break_60d_high': brk60,
        'pos_vs_60d_high_pct': pos60,
        'ma20': ma20, 'ma60': ma60, 'ma120': ma120,
        'disparity_20_pct': disp20,
        'ma_month10': ma_m10, 'ma_month10_slope_pct': ma_m10_slope,
        'drawdown_from_60d_high_pct': drawdown_from_high,
        'ret_5d': float((px / close[-6] - 1.0) * 100.0) if len(close) >= 6 else None,
        'ret_20d': float((px / close[-21] - 1.0) * 100.0) if len(close) >= 21 else None,
        'in_flow_list': in_flow_list,
        # 구성요소 점수
        'scores': {
            'turnover_surge': turnover_score,
            'price_volatility': vol_score,
            'investor_flow': flow_score,
            'trend_breakout': breakout_score,
            'liquidity': liq_score,
        },
    }


def compute_penalties(comp, change_pct=None):
    """
    과열·추격 위험 감점 (§7). 관심점수가 높아도 지금 사면 안 되는 상태를 분리한다.
    반환: (총감점, 사유 목록)
    """
    pen, why = 0.0, []
    disp = comp.get('disparity_20_pct')
    if disp is not None and disp > 15.0:
        p = min((disp - 15.0) * 1.5, 25.0)
        pen += p
        why.append(f"20일선 이격 +{disp:.1f}% (과열)")
    chg = change_pct if change_pct is not None else 0.0
    if chg >= 15.0:
        pen += 20.0
        why.append(f"당일 급등 +{chg:.1f}%")
    elif chg <= -10.0:
        pen += 10.0
        why.append(f"당일 급락 {chg:.1f}% (악재성 관심)")
    r5 = comp.get('ret_5d')
    if r5 is not None and r5 > 30.0:
        pen += 15.0
        why.append(f"5일 누적 +{r5:.1f}%")
    m10 = comp.get('ma_month10')
    if m10 and comp['price'] / m10 - 1.0 > 0.60:
        pen += 10.0
        why.append("월봉 10선 이격 과다")
    t_avg = comp.get('turnover_avg20')
    if t_avg is not None and t_avg < MIN_AVG_TURNOVER_KRW:
        pen += 20.0
        why.append(f"저유동성 (20일 평균 {t_avg / 1e8:,.0f}억)")
    return float(min(pen, 60.0)), why


def score_candidate(comp, change_pct=None):
    """구성요소 → 관심점수(0~100). 미연동 항목은 재정규화된 가중치로 제외된다."""
    w = effective_weights()
    raw = sum(comp['scores'].get(k, 0.0) * wt for k, wt in w.items())
    raw = float(np.clip(raw, 0.0, 100.0))
    pen, why = compute_penalties(comp, change_pct)
    return {
        'market_attention_score': raw,
        'adjusted_attention_score': float(np.clip(raw - pen, 0.0, 100.0)),
        'penalty': pen,
        'penalty_reasons': why,
        'overheated': pen >= 20.0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3단계 — 전략별 후보 선별
# ─────────────────────────────────────────────────────────────────────────────
def strategy_filter(strategy, row):
    """
    후보 방식별 조건. 통과하면 (True, 사유문자열), 아니면 (False, None).
    조건은 관심 여부만 판단한다 — 매수 여부는 퀀트 엔진이 따로 정한다.
    """
    c = row['components']
    s = c['scores']

    if strategy == 'turnover':
        r = c.get('turnover_ratio')
        if r and r >= 2.0:
            return True, f"거래대금 20일 평균 대비 {r:.1f}배"
        return False, None

    if strategy == 'flow':
        if c.get('in_flow_list'):
            return True, "외국인·기관 순매수 상위 진입"
        return False, None

    if strategy == 'breakout':
        if c.get('break_60d_high'):
            return True, "60일 신고가 돌파"
        if c.get('break_20d_high') and (c.get('turnover_ratio') or 0) >= 1.5:
            return True, "20일 고점 돌파 + 거래대금 증가"
        return False, None

    if strategy == 'pullback':
        dd = c.get('drawdown_from_60d_high_pct')
        ma60 = c.get('ma60')
        if (dd is not None and -15.0 <= dd <= -5.0
                and ma60 and c['price'] >= ma60 * 0.98
                and (c.get('ret_20d') or -99) > -10):
            return True, f"고점 대비 {dd:.1f}% 조정 · 60일선 지지"
        return False, None

    if strategy == 'demark':
        # 지표 엔진 없이 판단 가능한 근사: 하락 조정 + 저점권 + 변동성 확대
        dd = c.get('drawdown_from_60d_high_pct')
        if dd is not None and dd <= -15.0 and (c.get('ret_5d') or 0) > -3.0:
            return True, f"고점 대비 {dd:.1f}% 하락 후 낙폭 축소"
        return False, None

    if strategy == 'monthly10':
        m10, slope = c.get('ma_month10'), c.get('ma_month10_slope_pct')
        if m10 and c['price'] > m10 and (slope or 0) > 0:
            return True, f"월봉 10선 위 · 기울기 +{slope:.1f}%"
        return False, None

    if strategy == 'marketcap':
        return True, "시가총액 상위"

    # composite — 관심 신호를 모아 하나라도 뚜렷하면 후보로 올리고, 순위는 관심점수가 정한다.
    # 고정 임계값 두 개를 동시에 요구하면 시장 국면에 따라 후보가 0개가 된다
    # (거래대금이 전반적으로 줄어든 날에는 어떤 종목도 '2배 + 돌파'를 만족하지 못한다).
    hits = []
    r = c.get('turnover_ratio') or 0
    if r >= 1.5:
        hits.append(f"거래대금 {r:.1f}배")
    if (c.get('turnover_ratio_5d') or 0) >= 1.5:
        hits.append(f"5일 거래대금 {c['turnover_ratio_5d']:.1f}배")
    if c.get('in_flow_list'):
        hits.append("외국인·기관 순매수 상위")
    if c.get('break_60d_high'):
        hits.append("60일 신고가")
    elif c.get('break_20d_high'):
        hits.append("20일 고점 돌파")
    if s.get('price_volatility', 0) >= 65:
        hits.append("변동성 확대")
    if hits:
        return True, " · ".join(hits[:3])
    return False, None


def classify_bucket(attention, action_score, entry_ok=None):
    """§13 결과 분류. action_score 가 없으면 관심도만으로 임시 분류한다."""
    if action_score is None:
        return ('🔥 관심 급증·추격주의' if attention.get('overheated')
                else '👀 관찰 후보')
    hot = attention['adjusted_attention_score'] >= 55
    good = action_score >= 68
    if hot and good:
        return '🏆 실전 추천 후보'
    if hot and not good:
        return '🔥 관심 급증·추격주의'
    if (not hot) and good:
        return '🌱 조용한 선행 후보'
    return '🚫 추천 제외'


def find_attention_candidates(strategy='composite', top_n=15,
                              deep_max=DEEP_POOL_MAX, progress=None,
                              watchlist=None):
    """
    관심종목 후보를 찾는다.
    반환: {'rows': [...], 'pool_size': int, 'deep_count': int,
           'sources': [...], 'failures': [...], 'unavailable': str|None}
    """
    if strategy in STRATEGY_UNAVAILABLE:
        return {'rows': [], 'pool_size': 0, 'deep_count': 0, 'sources': [],
                'failures': [], 'unavailable': STRATEGY_UNAVAILABLE[strategy]}

    if strategy == 'watchlist':
        codes = [str(c).strip() for c in (watchlist or []) if str(c).strip()]
        if not codes:
            return {'rows': [], 'pool_size': 0, 'deep_count': 0, 'sources': [],
                    'failures': [], 'unavailable':
                        "관심종목이 비어 있습니다. 보유종목을 등록하거나 종목을 추가하세요."}
        pool = {c: {'code': c, 'name': c, 'price': None, 'change_pct': None,
                    'volume': None, 'turnover_mil': None, 'market_cap_eok': None,
                    'sources': {'watchlist'}} for c in codes}
        flow_names, report = set(), [{'source': '사용자 관심종목',
                                      'count': len(codes), 'ok': True}]
    else:
        pool, flow_names, report = fetch_candidate_pool(progress=progress)

    if not pool:
        return {'rows': [], 'pool_size': 0, 'deep_count': 0, 'sources': report,
                'failures': [], 'unavailable': "순위 페이지에서 후보를 받지 못했습니다."}

    # 일봉을 받을 순서: 순위 페이지가 이미 관심 순이므로 등장 소스 수 → 거래대금 순
    ordered = sorted(pool.values(),
                     key=lambda r: (len(r['sources']), r.get('turnover_mil') or 0),
                     reverse=True)
    if strategy == 'marketcap':
        ordered = sorted(pool.values(),
                         key=lambda r: (r.get('market_cap_eok') or 0), reverse=True)
    deep = ordered[:max(deep_max, top_n)]

    # 장중에는 오늘 봉이 미완성이므로 확정 봉까지만 쓴다 (거래대금 배수가 왜곡된다)
    try:
        live = be.get_market_status()['state'] == "장중"
    except Exception:
        live = False

    rows, failures = [], []
    for i, base in enumerate(deep):
        if progress:
            progress(f"관심지표 계산 {i + 1}/{len(deep)} · {base['name']}")
        bars = fetch_daily_bars(base['code'])
        if bars is None:
            failures.append(f"{base['name']}({base['code']}): 일봉 수신 실패")
            continue
        _live_to = ((base.get('turnover_mil') or 0) * 1e6) or None    # 백만원 → 원
        comp = compute_components(bars, in_flow_list=base['name'] in flow_names,
                                  drop_unconfirmed=live,
                                  live_turnover_krw=_live_to)
        att = score_candidate(comp, change_pct=base.get('change_pct'))
        row = {**base, 'components': comp, 'attention': att,
               'sources': sorted(base['sources'])}
        ok, why = strategy_filter(strategy, row)
        if not ok:
            continue
        row['selection_reason'] = why
        rows.append(row)

    rows.sort(key=lambda r: r['attention']['adjusted_attention_score'], reverse=True)
    return {'rows': rows[:top_n], 'pool_size': len(pool), 'deep_count': len(deep),
            'sources': report, 'failures': failures, 'unavailable': None,
            'used_confirmed_bars_only': live}


def attention_tiebreak_bonus(attention_score):
    """
    TOP3 순위에서 관심점수가 쓸 수 있는 최대 가산점 (§12).
    최종 행동점수를 뒤집지 못하도록 5점 이내로 제한한다.
    """
    if attention_score is None:
        return 0.0
    return float(np.clip(attention_score, 0, 100) / 100.0 * ATTENTION_TIEBREAK_MAX_PCT)
