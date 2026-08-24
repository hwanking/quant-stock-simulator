# -*- coding: utf-8 -*-
"""ETF 이름·코드·순자산가치(NAV) (라운드 164).

■ 왜
  사용자 요청: *"같은 주식도 검색해서 적정가 살때말때도 해줬으면 좋겠어"*
  (ETF 두 개를 가리키며).

  그런데 **ETF 에 기업 적정가는 없다.** EPS·BPS·ROE 가 존재하지 않는
  자산이라 엔진은 이미 `is_fund_like` 로 펀더멘털 밸류에이션을 건너뛴다 —
  그건 옳은 처리다. 라운드 44 주석이 경고하듯 여기서 `가격 × 0.8` 같은
  폴백이 걸리면 **근거 없는 적정가**가 붙는다.

  그렇다고 "적정가 없음" 으로 끝낼 일도 아니다. ETF 에는 **원래부터
  정답에 해당하는 값**이 있다 — 순자산가치(NAV)다. 담고 있는 자산을
  그날 종가로 평가한 값이므로, 기업 적정가처럼 **추정하는 값이 아니라
  발표되는 값**이다. 그것을 받아다 그대로 적는다.

■ 지어내지 않았는지 확인한 것 (_probe/etf_nav_probe.py · 2026-08-23)
      0040Y0  현재가 8,180  NAV 8,148  → 괴리 +0.39%
      480020  현재가 10,290 NAV 10,240 → 괴리 +0.49%
  사용자 HTS 화면의 'NAV괴리율 0.39% / 0.49%' 와 **같은 값**이다.
  괴리율 = (현재가 − NAV) ÷ NAV.

■ 왜 별도 모듈인가
  · 이 목록은 네이버가 **euc-kr** 로 준다. 공용 `fetch_json_with_retry`
    는 utf-8 고정이라 이름이 깨진다(`'SOL ȶƼĿOTMäȥ'`). 공용 함수를
    바꾸면 다음(utf-8)이 깨지므로 여기서만 다르게 읽는다.
  · ETF 1,161종목 중 **296종목(25.5%)이 문자 포함 코드**다. 이름으로
    찾는 길을 네이버 검색에만 맡기면 안 된다 — 실측에서 '미국빅테크7'
    검색이 **0건**이었는데 이 목록에는 8종목이 있다.

■ ⚠️ 한계를 먼저 적는다 (§3)
  · **NAV 는 받은 그 시점의 값이다.** 저장소에 동봉하는 색인
    (`data/etf_index.json`)에는 **이름과 코드만** 넣는다 — 낡은 NAV 를
    오늘 값처럼 보여 주지 않기 위해서다. NAV 는 살아 있는 조회에서만
    나오고, 화면은 **받은 시각을 함께** 적는다.
  · 못 받으면 `None` 이고 화면은 '미수신'과 이유를 쓴다. 0 으로 채우지
    않는다.
  · 이 모듈은 **추천 스캔 모집단을 바꾸지 않는다.** 사용자가 직접 친
    것을 찾아 주고, 찾은 ETF 의 NAV 를 보여 줄 뿐이다.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from datetime import datetime

import stock_code

_BASE = os.path.dirname(os.path.abspath(__file__))
#: 살아 있는 조회 결과(NAV 포함). 개인 자료가 아니지만 낡으므로 gitignore 쪽에 둔다.
CACHE = os.path.join(_BASE, '.portfolio', 'etf_live.json')
#: 저장소 동봉 색인 — **이름·코드만.** 네트워크가 없어도 검색은 되게 한다.
INDEX = os.path.join(_BASE, 'data', 'etf_index.json')

URL = 'https://finance.naver.com/api/sise/etfItemList.nhn'

#: 살아 있는 조회를 다시 하기까지의 시간(초). 장중 가격이 움직이므로 짧게 둔다.
TTL_SEC = 600


def _fetch_raw(timeout=10):
    """네이버 ETF 목록 원문 → 파싱된 항목 목록. 실패하면 None (지어내지 않는다)."""
    req = urllib.request.Request(URL, headers={
        'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                       'AppleWebKit/537.36'),
        'Referer': 'https://finance.naver.com/'})
    try:
        raw = urllib.request.urlopen(req, timeout=timeout).read()
    except Exception as e:                                     # noqa: BLE001
        print(f'[etf_registry] 목록 수신 실패: {e}')
        return None
    for enc in ('euc-kr', 'cp949', 'utf-8'):
        try:
            doc = json.loads(raw.decode(enc))
            break
        except Exception:                                      # noqa: BLE001
            doc = None
    if not doc:
        print('[etf_registry] 목록 해독 실패 — 인코딩을 못 맞췄다')
        return None
    rows = (doc.get('result') or {}).get('etfItemList') or []
    out = []
    for r in rows:
        code = stock_code.normalize(r.get('itemcode'))
        name = str(r.get('itemname') or '').strip()
        if not code or not name:
            continue                    # 못 읽은 행은 버린다 (추측하지 않는다)
        out.append({
            'code': code, 'name': name,
            'price': _num(r.get('nowVal')), 'nav': _num(r.get('nav')),
            'change_rate': _num(r.get('changeRate')),
            'market_sum': _num(r.get('marketSum')),
        })
    return out or None


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None                               # NaN → None


#: 파일 → (mtime, 파싱 결과). 260KB JSON 을 rerun 마다 다시 파싱하지
#: 않는다 — 검색은 글자 하나 칠 때마다 부른다. 파일이 바뀌면 다시 읽는다.
_MEMO = {}


def _read_json(path):
    try:
        mt = os.path.getmtime(path)
    except OSError:
        return None
    hit = _MEMO.get(path)
    if hit and hit[0] == mt:
        return hit[1]
    try:
        with open(path, encoding='utf-8') as f:
            doc = json.load(f)
    except Exception:                                          # noqa: BLE001
        return None
    _MEMO[path] = (mt, doc)
    return doc


def live(force=False):
    """
    살아 있는 ETF 목록 `{'at': ISO시각, 'rows': [...]}`. 못 받으면 None.

    캐시가 `TTL_SEC` 안이면 다시 받지 않는다. **낡은 캐시를 오늘 값처럼
    돌려주지 않는다** — 시각(`at`)을 같이 돌려주고 화면이 그것을 적는다.
    """
    if not force:
        doc = _read_json(CACHE)
        if doc and doc.get('rows'):
            try:
                age = time.time() - float(doc.get('epoch') or 0)
            except (TypeError, ValueError):
                age = TTL_SEC + 1
            if age <= TTL_SEC:
                return doc
    rows = _fetch_raw()
    if not rows:
        # 새로 못 받았으면 **있는 캐시라도** 시각과 함께 돌려준다.
        # 값을 지어내지는 않되, 있는 사실을 감추지도 않는다.
        return _read_json(CACHE)
    doc = {'at': datetime.now().strftime('%Y-%m-%d %H:%M'),
           'epoch': time.time(), 'source': 'FINANCE.NAVER etfItemList',
           'rows': rows}
    try:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        with open(CACHE, 'w', encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False)
        _MEMO.pop(CACHE, None)          # 새로 썼으니 메모를 버린다
    except Exception:                                          # noqa: BLE001
        pass                            # 캐시를 못 써도 조회 자체는 됐다
    return doc


def index():
    """
    이름·코드 색인 `{code: name}`. 살아 있는 목록 우선, 없으면 동봉 색인.

    ⚠️ 동봉 색인에는 **NAV 가 없다.** 낡은 NAV 를 오늘 값처럼 쓰지
       않기 위해 일부러 빼 두었다.
    """
    doc = live()
    if doc and doc.get('rows'):
        return {r['code']: r['name'] for r in doc['rows']}
    shipped = _read_json(INDEX) or {}
    return dict(shipped.get('map') or {})


def index_source():
    """지금 색인이 어디서 왔나 — 화면이 밝힐 수 있게 (§3)."""
    doc = _read_json(CACHE)
    if doc and doc.get('rows'):
        return f"조회 {doc.get('at')}"
    shipped = _read_json(INDEX)
    if shipped:
        return f"동봉 색인 {shipped.get('made')} (NAV 없음)"
    return None


def search(query, limit=12):
    """이름·코드 부분 일치 → `[(code, name), ...]`. 이름이 짧은 것 먼저."""
    q = str(query or '').strip()
    if not q:
        return []
    ql = q.lower()
    qc = stock_code.normalize(q)
    hits = []
    for code, name in index().items():
        if (qc and code == qc) or ql in name.lower() or ql in code.lower():
            hits.append((code, name))
    hits.sort(key=lambda t: (len(t[1]), t[1]))
    return hits[:limit]


def is_etf(code):
    """이 코드가 ETF 목록에 있나. 목록을 못 받았으면 None (모른다)."""
    c = stock_code.normalize(code)
    if not c:
        return False
    idx = index()
    if not idx:
        return None                     # '아니다' 와 '모른다' 를 가른다
    return c in idx


def nav_of(code):
    """
    ETF 한 종목의 NAV. 반환:

        {'code','name','price','nav','premium_pct','at'}  또는 None

    · `premium_pct` = (현재가 − NAV) ÷ NAV × 100  — HTS 의 'NAV괴리율'
    · 못 받았거나 ETF 가 아니면 **None**. 0 으로 채우지 않는다.
    """
    c = stock_code.normalize(code)
    if not c:
        return None
    doc = live()
    if not doc or not doc.get('rows'):
        return None
    for r in doc['rows']:
        if r['code'] != c:
            continue
        nav, px = r.get('nav'), r.get('price')
        prem = ((px - nav) / nav * 100.0) if (nav and px and nav > 0) else None
        return {'code': c, 'name': r['name'], 'price': px, 'nav': nav,
                'premium_pct': (round(prem, 2) if prem is not None else None),
                'at': doc.get('at')}
    return None


#: 룩스루 적정가 산출물 (라운드 167). 사전등록 기준을 통과한 ETF 만 들어 있다.
LOOKTHROUGH = os.path.join(_BASE, 'data', 'etf_lookthrough_r167.json')


def lookthrough_of(code):
    """
    한 ETF 의 **룩스루 적정가**. 없으면 None — 지어내지 않는다.

    구성종목의 펀더멘털 적정가를 비중으로 가중해 *"담은 기업들이 모두
    적정가에 거래된다면 NAV 가 몇 % 다를까"* 를 낸다. 배수·좌수가 식에
    없다 (`docs/PREREG_R167_ETF_LOOKTHROUGH.md` §1).

    ⚠️ **표시 전용이다.** 게이트·점수·추천에 넣지 않는다. 원장에 ETF 가
       없어 이 값이 성과를 가르는지는 **재지 않았다** (라운드 44 가 업황을
       표시 전용으로 낸 것과 같은 자리).
    ⚠️ **잰 날의 값이다.** 구성종목 적정가는 매일 바뀐다 — 화면이 기준일을
       함께 적는다.
    """
    c = stock_code.normalize(code)
    if not c:
        return None
    doc = _read_json(LOOKTHROUGH)
    if not doc:
        return None
    row = (doc.get('results') or {}).get(c)
    if not row or row.get('lookthrough_fair') is None:
        return None
    # 사전등록 R2 를 통과한 것만 낸다 — 커버리지가 모자라면 값이 아니다
    if (row.get('valued_pct') or 0) < (doc.get('cover_min') or 90.0):
        return None
    return dict(row, made=doc.get('made'), cover_min=doc.get('cover_min'))


#: ETF 전수 분류 (라운드 170). 1,161종목 각각이 **왜** 룩스루가 안 되는지.
TAXONOMY = os.path.join(_BASE, 'data', 'etf_taxonomy_r170.json')

#: 우세 자산유형 → 사람 말. 라운드 170 이 전수로 가른 사유 그대로다.
#: **여기서 사유를 새로 짓지 않는다** — 분류는 산출물이 하고, 여기는 옮긴다.
_GAP_WHY = {
    '해외주식': '구성종목이 해외 주식이라 우리에게 그 종목의 가격도 '
             '적정가도 없습니다',
    '채권': '구성종목이 채권이라 주식 적정가 모델이 닿지 않습니다',
    '스왑': '스왑 계약으로 되어 있어 들여다볼 구성종목이 없습니다',
    '현금성': '현금성 자산이 대부분이라 들여다볼 기업이 없습니다',
    '국내주식': '운용사가 구성종목 비중을 게시하지 않습니다',
    '분류 안 됨': '구성종목의 자산유형을 우리가 가르지 못했습니다',
}


def lookthrough_gap(code):
    """룩스루 적정가를 **왜 못 내는지**. 낼 수 있으면 None.

    ⚠️ 라운드 171 — 라운드 170 이 1,161종목을 전수로 갈라 *"왜 148개
       뿐인가"* 를 문서에 적었는데, **화면은 아무 말도 안 하고 있었다.**
       사용자가 ETF 를 열면 적정가 칸이 그냥 비어 있었고, 그것은
       "적정가가 없다"인지 "우리가 못 낸다"인지 구분되지 않는다 —
       §3 이 갈라 놓으라고 한 바로 그 두 문장이다.

    ⚠️ **새로 재지 않는다.** 이미 디스크에 있는 R170 산출물을 읽어 옮길
       뿐이다. 산출물이 없으면 `None` 을 돌려주고 화면은 조용히 있는다 —
       없는 사유를 지어내지 않는다.
    """
    c = stock_code.normalize(code)
    if not c:
        return None
    if lookthrough_of(c):
        return None                       # 낼 수 있는 ETF 다
    tax = _read_json(TAXONOMY)
    if not tax:
        return None
    row = None
    for r in (tax.get('rows') or []):
        if stock_code.normalize(r.get('code')) == c:
            row = r
            break
    if not row:
        return None

    dom = str(row.get('dominant') or '')
    state = str(row.get('state') or '')
    cover_min = tax.get('cover_min') or 90.0

    # 비중이 있는데 통과 못 한 경우 — **얼마나 모자랐는지**를 적는다.
    valued = None
    if state.startswith('비중 있음'):
        lt = _read_json(LOOKTHROUGH) or {}
        r167 = (lt.get('results') or {}).get(c) or {}
        valued = r167.get('valued_pct')

    # ⚠️ 사유를 뭉뚱그리지 않는다. '비중 있음 · 미통과' 안에 서로 다른 셋이
    #   섞여 있고, 셋 다 실측으로 갈렸다 (`_probe/gap_107_r171.py`):
    #     ⓐ 커버리지 미달 239개 — 구성종목 적정가가 모자란다
    #     ⓑ 비중 합이 100%가 아님 76개 — 레버리지·인버스 (합 187~196%)
    #     ⓒ 이름→코드 조인 미달 31개 — 금현물·리츠혼합 등
    ws = row.get('weight_sum') or 0
    if valued is not None:
        why = (f'구성종목 중 적정가를 낼 수 있는 몫이 {valued:.1f}% 라 '
               f'기준 {cover_min:.0f}% 에 못 미칩니다')
    elif state.startswith('비중 있음') and not (95 <= ws <= 105):
        why = (f'게시된 비중의 합이 {ws:.0f}% 입니다 (레버리지·인버스 등) '
               f'— 그대로 가중하면 값이 틀립니다')
    elif state.startswith('비중 있음'):
        why = '구성종목 이름을 우리 종목코드에 붙이지 못한 몫이 있습니다'
    else:
        why = _GAP_WHY.get(dom, '구성종목 비중을 받지 못했습니다')

    return {
        'code': c, 'name': row.get('name'), 'holdings': row.get('holdings'),
        'state': state, 'dominant': dom, 'why': why,
        'valued_pct': valued, 'cover_min': cover_min,
        'made': tax.get('made'),
        'total': tax.get('total'), 'passed': tax.get('passed'),
    }


def write_index(path=None):
    """동봉 색인을 새로 만든다 (`scripts/etf_index_r164.py` 가 부른다)."""
    rows = _fetch_raw()
    if not rows:
        return None
    doc = {'made': datetime.now().strftime('%Y-%m-%d'),
           'source': 'FINANCE.NAVER etfItemList',
           'note': ('이름·코드만 담는다 — NAV 는 살아 있는 조회에서만 낸다. '
                    '낡은 NAV 를 오늘 값처럼 보여 주지 않기 위해서다.'),
           'count': len(rows),
           'with_letter': sum(1 for r in rows
                              if stock_code.has_letter(r['code'])),
           'map': {r['code']: r['name'] for r in rows}}
    p = path or INDEX
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    return doc
