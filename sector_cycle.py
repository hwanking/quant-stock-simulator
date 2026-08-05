# -*- coding: utf-8 -*-
"""
섹터 사이클 — 업황을 **재는** 층. 판정하지 않는다.

사용자 지적: *"시장조정 펀더멘털 적정가가 과거 재무지표와 고정 업종
평균만 사용하면 현재 업황 변화를 반영하지 못합니다."*

맞다. 그리고 실제로는 더 나빴다 — `quant_indicators.py` 의 '시장조정'은
**상수 −2.0%** 였다. 2,872개 전 종목이 3년 내내 같은 값을 받았다.
조정이라는 이름만 있고 조정하는 대상이 없었다.

■ 이 모듈이 하는 일 / 하지 않는 일
    한다    — 업종을 프록시에 잇고, 모멘텀·상대강도·매크로를 **재서 낸다**
    안 한다 — 적정가를 올리거나 내리지 않는다. 그건 룰북과
              `verdict_core` 가 정한다 (라운드 42에서 뉴스에 쓴 것과 같은
              역할 분리 — 재는 쪽과 쓰는 쪽을 섞으면 검증이 안 된다)

■ 없는 값을 지어내지 않는다 (CLAUDE.md §3)
    · 프록시가 없는 업종은 `linked=False` 로 낸다. 0% 로 채우지 않는다
    · BDRY 는 **발틱운임지수 그 자체가 아니라 운임선물 ETF** 다.
      대용임을 `proxy_note` 에 적어 화면까지 끌고 간다
    · 수신 실패는 `available=False` + 이유. 실패를 중립값으로 바꾸지 않는다

■ 시점 복원
    `as_of` 를 주면 그 **전날까지의 데이터만** 쓴다. 원장 검증에서
    미래를 훔치지 않기 위한 것이고, 실시간 호출에서는 as_of=None 이다.

사전등록: docs/PREREG_R44_SECTOR_OVERLAY.md
"""
from __future__ import annotations

import bisect as _bisect
import json
import os
import re
import threading
import time

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE, '.portfolio', 'sector_cache')

#: 시세 캐시 유효시간 — 장중 갱신 주기. 사양 §1 '매일 갱신' 축.
PRICE_TTL_SEC = 60 * 60 * 6
#: 업종 분류 캐시 — 분기 단위로 바뀌므로 길게 잡는다.
LISTING_TTL_SEC = 60 * 60 * 24 * 7
#: 프록시 최종 수신일이 기준일보다 이만큼 밀리면 '신선하지 않음'
STALE_BARS = 5

_LOCK = threading.Lock()
_MEM: dict = {}


# ───────────────────────────────────────────────────────────────────
# 프록시 정의
# ───────────────────────────────────────────────────────────────────

#: 업종 → 글로벌/국내 프록시.
#:
#: 이것은 **의미 대응**이지 수치가 아니다. CLAUDE.md §2 가 금지하는 것은
#: 문턱·가중치·상한을 감으로 정하는 일이고, '해상 운송업은 해운 ETF 로
#: 본다'는 대응 자체는 측정 대상이지 측정 결과가 아니다.
#:
#: `real` 은 그 업종의 **진짜 선행지표**다. 프록시는 그 대용이며, 둘이
#: 다르다는 사실을 화면까지 가져간다.
GROUPS = {
    'SHIP': dict(
        ko='해운', proxy=['BOAT', 'BDRY'], bench='US500',
        proxy_note='BOAT(글로벌 해운주)·BDRY(발틱운임 선물 ETF). '
                   'BDRY는 운임지수 자체가 아니라 선물 ETF라 괴리가 있습니다.',
        real=['컨테이너 운임지수(SCFI/CCFI)', '벌크 운임지수(BDI)',
              '유조선 운임(WS)', '항만 물동량', '선복량 증가율',
              '신조선 인도량', '폐선량', '주요 항로 운임', '항만 적체'],
        real_linked=[],
    ),
    'SHIPBUILD': dict(
        ko='조선', proxy=['BOAT'], bench='US500',
        proxy_note='조선 전용 지수가 공개 무료로 없어 해운주 ETF로 대용합니다.',
        real=['신조선가지수', '수주잔고', '선가', '후판 가격', '인도 일정'],
        real_linked=[],
    ),
    'SEMI': dict(
        ko='반도체', proxy=['SOXX', 'SMH'], bench='US500',
        proxy_note='미국 반도체 ETF. 국내 메모리 사이클과 상관은 있으나 동일하지 않습니다.',
        real=['DRAM/NAND 현물가', '재고', '출하량(빗그로스)', '설비투자',
              '주요 고객 수요'],
        real_linked=[],
    ),
    'TECH': dict(
        ko='IT·소프트웨어', proxy=['XLK'], bench='US500',
        proxy_note='미국 기술 ETF.',
        real=['클라우드 지출', 'SaaS 순증', '광고 단가'], real_linked=[],
    ),
    'AUTO': dict(
        ko='자동차', proxy=['CARZ'], bench='US500',
        proxy_note='글로벌 자동차 ETF.',
        real=['판매량', '인센티브', '재고일수', '지역별 수요'],
        real_linked=['환율'],
    ),
    'CHEM': dict(
        ko='화학', proxy=['XLB'], bench='US500',
        proxy_note='미국 소재 ETF. 국내 석유화학 스프레드와는 다릅니다.',
        real=['제품 스프레드', '나프타 가격', '가동률', '재고', '중국 수요'],
        real_linked=['유가'],
    ),
    'STEEL': dict(
        ko='철강·비철', proxy=['SLX', 'COPX'], bench='US500',
        proxy_note='철강·구리광산 ETF.',
        real=['열연/후판 가격', '철광석·원료탄', '재고', '중국 생산'],
        real_linked=['구리'],
    ),
    'ENERGY': dict(
        ko='에너지·정유', proxy=['XLE'], bench='US500',
        proxy_note='미국 에너지 ETF.',
        real=['정제마진', '가스 가격', '발전단가', '설비 이용률'],
        real_linked=['유가'],
    ),
    'DEFENSE': dict(
        ko='방산·항공우주', proxy=['ITA'], bench='US500',
        proxy_note='미국 방산 ETF.',
        real=['수주잔고', '수출계약', '납기', '국방예산'],
        real_linked=['환율'],
    ),
    'BIO': dict(
        ko='제약·바이오', proxy=['XBI'], bench='US500',
        proxy_note='미국 바이오 ETF(소형주 중심).',
        real=['임상 단계', '허가', '기술이전', '현금소진', '성공확률'],
        real_linked=[],
    ),
    'HEALTH': dict(
        ko='의료기기·헬스케어', proxy=['XLV'], bench='US500',
        proxy_note='미국 헬스케어 ETF.',
        real=['수가 정책', '병원 설비투자'], real_linked=[],
    ),
    'BANK': dict(
        ko='은행', proxy=['KRE', 'XLF'], bench='US500',
        proxy_note='미국 은행 ETF. 국내 예대마진 구조와는 다릅니다.',
        real=['기준금리', '예대마진', '연체율', '충당금', '자본비율'],
        real_linked=[],
    ),
    'FIN': dict(
        ko='증권·금융', proxy=['XLF'], bench='US500',
        proxy_note='미국 금융 ETF.',
        real=['거래대금', '금리', 'IB 실적', '운용손익'],
        real_linked=[],
    ),
    'INSUR': dict(
        ko='보험', proxy=['KIE'], bench='US500',
        proxy_note='미국 보험 ETF.',
        real=['손해율', '금리', '신계약', '해지율'], real_linked=[],
    ),
    'INDUS': dict(
        ko='기계·산업재', proxy=['XLI'], bench='US500',
        proxy_note='미국 산업재 ETF.',
        real=['수주', '가동률', '설비투자'], real_linked=[],
    ),
    'TRANSP': dict(
        ko='운송·물류', proxy=['IYT'], bench='US500',
        proxy_note='미국 운송 ETF.',
        real=['화물량', '운임', '유류할증료'], real_linked=['유가'],
    ),
    'CONSUM': dict(
        ko='소비재·유통', proxy=['XLY'], bench='US500',
        proxy_note='미국 경기소비재 ETF.',
        real=['소매판매', '소비심리', '객단가'], real_linked=[],
    ),
    'UTIL': dict(
        ko='유틸리티·전력', proxy=['XLU'], bench='US500',
        proxy_note='미국 유틸리티 ETF.',
        real=['SMP', '연료비', '요금 정책'], real_linked=[],
    ),
    'REIT': dict(
        ko='건설·부동산', proxy=['IYR'], bench='US500',
        proxy_note='미국 리츠 ETF. 국내 주택 건설과는 사업구조가 다릅니다.',
        real=['분양물량', '미분양', '착공', '자재비', 'PF 금리'],
        real_linked=[],
    ),
}

#: KSIC 업종명 → 프록시 그룹. 앞에서부터 먼저 걸리는 것을 쓴다.
#: 매칭 안 되면 **미연동** — 억지로 붙이지 않는다.
_RULES = (
    ('SHIP', r'해상\s*운송|외항|수상\s*운송'),
    ('SHIPBUILD', r'선박|보트\s*건조'),
    ('SEMI', r'반도체'),
    ('DEFENSE', r'항공기|우주선|무기|총포'),
    ('TRANSP', r'항공\s*여객|항공\s*화물|도로\s*화물|운송관련|창고|물류|철도'),
    ('BIO', r'의약품|의약물질|생물학적|의약\s*관련'),
    ('HEALTH', r'의료용\s*기기|의료용품|병원|의료'),
    ('BANK', r'은행|저축기관'),
    ('INSUR', r'보험|연금'),
    ('FIN', r'금융|증권|신탁|자산\s*운용|투자'),
    ('STEEL', r'1차\s*철강|철강|비철금속|금속\s*광업|구조용\s*금속|금속\s*가공'),
    ('ENERGY', r'석유\s*정제|가스\s*제조|연료|원유|전기업|발전'),
    ('CHEM', r'화학|화학섬유|고무|플라스틱|비료|농약'),
    ('AUTO', r'자동차'),
    ('SEMI', r'전자부품|영상\s*및\s*음향|통신\s*및\s*방송\s*장비|일차전지|이차전지'),
    ('TECH', r'소프트웨어|컴퓨터\s*프로그|자료처리|포털|인터넷|정보\s*서비스|게임'),
    ('UTIL', r'수도|증기|공기\s*조절|폐기물'),
    ('REIT', r'건설업|건물\s*건설|토목|부동산|건축기술|엔지니어링|전기\s*및\s*통신\s*공사'),
    ('INDUS', r'기계|장비|전동기|발전기|측정|정밀기기|조선|금형|절연'),
    ('CONSUM', r'소매|도매|음식료|식품|음료|담배|의복|섬유|신발|가구|화장품|"'
               r'교습|오락|숙박|음식점|출판|방송|영화'),
    ('TECH', r'전기\s*통신업'),
)


def group_of(industry):
    """KSIC 업종명 → 프록시 그룹 코드. 매칭 실패 시 None (미연동)."""
    if not industry:
        return None
    s = str(industry).strip()
    if not s or s.lower() == 'nan':
        return None
    for code, pat in _RULES:
        if re.search(pat, s):
            return code
    return None


# ───────────────────────────────────────────────────────────────────
# 수신 · 캐시
# ───────────────────────────────────────────────────────────────────

def _cache_path(name):
    # 디렉터리 생성 실패로 예외를 밖으로 내보내지 않는다. 캐시는 **선택**이고,
    # 쓰기 불가 파일시스템(읽기 전용 컨테이너 등)에서 캐시 때문에 조회 자체가
    # 죽으면 안 된다. 못 만들면 그냥 캐시 미스로 흘러간다.
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
    except OSError:
        pass
    safe = re.sub(r'[^A-Za-z0-9_.=-]', '_', str(name))
    return os.path.join(CACHE_DIR, f'{safe}.json')


def _cache_read(name, ttl):
    try:
        p = _cache_path(name)
        if os.path.exists(p) and (time.time() - os.path.getmtime(p)) < ttl:
            with open(p, encoding='utf-8') as f:
                return json.load(f)
    except Exception:                                        # noqa: BLE001
        pass
    return None


def _cache_write(name, obj):
    try:
        with open(_cache_path(name), 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False)
    except Exception:                                        # noqa: BLE001
        pass


#: 시세 수집 시작일.
#:
#: 라운드 44-1b 사고 — 처음에 '2022-01-01' 로 뒀다가 원장 케이스 7,527건이
#: 통째로 빠졌다. 원장은 2015-12-28 부터인데 프록시 시세가 2021-12-31
#: 부터라 60봉 확보가 안 됐던 것이다. 신호가 없어서 빠진 게 아니라
#: **내 수집 시작일 때문에** 빠졌고, 그 상태로 낸 게이트 결과는 편향된
#: 부분표본에서 나온 값이었다. 원장 최소일보다 넉넉히 앞에서 시작한다.
SERIES_START = '2014-01-01'


def series(ticker, start=SERIES_START):
    """
    티커 일별 종가. `{'YYYY-MM-DD': close}`.

    수신 실패는 `None` 이다. 0 이나 직전값으로 채우지 않는다.
    """
    key = f'px_{ticker}_{start}'
    with _LOCK:
        if key in _MEM:
            return _MEM[key]
    hit = _cache_read(key, PRICE_TTL_SEC)
    if hit is not None:
        with _LOCK:
            _MEM[key] = hit
        return hit
    try:
        import FinanceDataReader as fdr
        df = fdr.DataReader(ticker, start)
        if df is None or df.empty or 'Close' not in df.columns:
            return None
        out = {}
        for idx, v in df['Close'].items():
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if fv == fv and fv > 0:
                out[str(idx)[:10]] = fv
        if len(out) < 30:
            return None
    except Exception:                                        # noqa: BLE001
        return None
    _cache_write(key, out)
    with _LOCK:
        _MEM[key] = out
    return out


def industry_map():
    """종목코드(6자리) → KSIC 업종명. 실패 시 빈 dict."""
    # 파이프라인이 **종목마다** 부른다. 메모리 캐시가 없으면 2,759항목 JSON을
    # 매번 다시 파싱한다.
    with _LOCK:
        if 'krx_desc' in _MEM:
            return _MEM['krx_desc']
    hit = _cache_read('krx_desc', LISTING_TTL_SEC)
    if hit is not None:
        with _LOCK:
            _MEM['krx_desc'] = hit
        return hit
    try:
        import FinanceDataReader as fdr
        df = fdr.StockListing('KRX-DESC')
        # 'Sector' 는 코스닥 소속부라 업종이 아니다 — 'Industry' 를 쓴다
        out = {}
        for _, r in df.iterrows():
            code = str(r.get('Code') or '').zfill(6)
            ind = str(r.get('Industry') or '').strip()
            if code and ind and ind.lower() != 'nan':
                out[code] = ind
    except Exception:                                        # noqa: BLE001
        return {}
    _cache_write('krx_desc', out)
    return out


# ───────────────────────────────────────────────────────────────────
# 측정
# ───────────────────────────────────────────────────────────────────

def _sorted_rows(px):
    """(날짜목록, (날짜,종가)목록) — 한 번만 정렬해 두고 재사용한다."""
    if not px:
        return [], []
    key = ('rows', id(px), len(px))
    with _LOCK:
        hit = _MEM.get(key)
    if hit is not None:
        return hit
    ks = sorted(px)
    out = (ks, [(k, px[k]) for k in ks])
    with _LOCK:
        _MEM[key] = out
    return out


def _upto(px, as_of):
    """`as_of` **전날까지**만 남긴 (날짜, 종가) 목록. 미래를 훔치지 않는다."""
    dates, rows = _sorted_rows(px)
    if not rows or not as_of:
        return rows
    # 오름차순이므로 이분 탐색으로 자른다 (파이프라인이 종목마다 부른다)
    return rows[:_bisect.bisect_left(dates, str(as_of)[:10])]


def _ret(rows, bars):
    if len(rows) < bars + 1:
        return None
    a, b = rows[-1 - bars][1], rows[-1][1]
    if not a or a <= 0:
        return None
    return (b / a - 1.0) * 100.0


def proxy_momentum(gcode, as_of=None):
    """
    프록시 그룹의 업황 모멘텀.

    반환 키:
      available · mom60 · mom20 · rs60(벤치 대비) · fresh · last_date ·
      sources · proxy_note · why(미산출 이유)
    """
    g = GROUPS.get(gcode)
    if not g:
        return dict(available=False, why='업종이 프록시에 연결되지 않았습니다.',
                    linked=False)
    got, srcs = [], []
    for t in g['proxy']:
        rows = _upto(series(t), as_of)
        if len(rows) < 61:
            continue
        m60, m20 = _ret(rows, 60), _ret(rows, 20)
        if m60 is None:
            continue
        got.append((m60, m20))
        srcs.append(dict(ticker=t, last_date=rows[-1][0], bars=len(rows)))
    if not got:
        return dict(available=False, linked=True,
                    why=(f"{g['ko']} 프록시({'·'.join(g['proxy'])}) 시세를 "
                         f"받지 못했습니다."))

    mom60 = sum(x[0] for x in got) / len(got)
    m20s = [x[1] for x in got if x[1] is not None]
    mom20 = (sum(m20s) / len(m20s)) if m20s else None

    brows = _upto(series(g['bench']), as_of)
    bench60 = _ret(brows, 60) if len(brows) >= 61 else None
    rs60 = (mom60 - bench60) if bench60 is not None else None

    last = max(s['last_date'] for s in srcs)
    fresh = True
    if as_of:
        # 거래일 환산 없이 달력일로 보수적으로 본다 (STALE_BARS 의 약 1.5배)
        try:
            import datetime as _dt
            d1 = _dt.date.fromisoformat(last)
            d2 = _dt.date.fromisoformat(str(as_of)[:10])
            fresh = (d2 - d1).days <= int(STALE_BARS * 1.5)
        except Exception:                                    # noqa: BLE001
            fresh = True

    return dict(available=True, linked=True, group=gcode, ko=g['ko'],
                mom60=round(mom60, 2), mom20=(round(mom20, 2) if mom20 is not None else None),
                bench60=(round(bench60, 2) if bench60 is not None else None),
                rs60=(round(rs60, 2) if rs60 is not None else None),
                fresh=fresh, last_date=last, sources=srcs,
                proxy_note=g['proxy_note'],
                real_indicators=list(g['real']),
                real_linked=list(g['real_linked']),
                collected_at=time.strftime('%Y-%m-%d %H:%M:%S'))


#: 매크로 축 — 사양 §1 '매일 갱신'. 수신 실패는 그대로 남긴다.
MACRO = (('USD/KRW', '원달러', 'fx'), ('CL=F', 'WTI 유가', 'oil'),
         ('HG=F', '구리', 'copper'), ('VIX', '변동성지수', 'vix'),
         ('KS11', 'KOSPI', 'kospi'), ('KQ11', 'KOSDAQ', 'kosdaq'),
         ('US500', 'S&P500', 'spx'))


def macro(as_of=None):
    """매크로 축 60일 변화율. 못 받은 축은 `None` 으로 남긴다."""
    out, miss = {}, []
    for t, ko, key in MACRO:
        rows = _upto(series(t), as_of)
        r = _ret(rows, 60) if len(rows) >= 61 else None
        if r is None:
            miss.append(ko)
            out[key] = None
        else:
            out[key] = dict(ko=ko, ticker=t, chg60=round(r, 2),
                            last=rows[-1][1], last_date=rows[-1][0])
    out['missing'] = miss
    return out


def sector_snapshot(as_of=None):
    """전 그룹 모멘텀 한 번에 — 화면 '업황 지도'용."""
    return {g: proxy_momentum(g, as_of=as_of) for g in GROUPS}


def for_stock(code, industry=None, as_of=None):
    """
    종목 하나의 업황 신호.

    적정가를 **고치지 않는다.** 재서 낼 뿐이고, 쓸지 말지는 룰북이 정한다.
    """
    code = str(code or '').split('.')[0].zfill(6)
    ind = industry
    if not ind:
        ind = (industry_map() or {}).get(code)
    if not ind:
        return dict(available=False, linked=False, industry=None,
                    why='업종 분류를 받지 못해 업황을 연결할 수 없습니다.')
    gcode = group_of(ind)
    if not gcode:
        return dict(available=False, linked=False, industry=ind,
                    why=f"'{ind}' 업종은 아직 프록시가 연결되지 않았습니다 (미연동).")
    m = proxy_momentum(gcode, as_of=as_of)
    m['industry'] = ind
    m['code'] = code
    return m
