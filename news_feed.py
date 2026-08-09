# -*- coding: utf-8 -*-
"""
뉴스 기사 수집 — 공개 RSS만 (라운드 41).

■ 왜 만들었나
  '뉴스·공시 촉매'는 관심점수의 **20%** 인데 지금까지 DART RSS 50건만
  보고 있었다. 그래서 상태가 '부분 연동'이었고, 후보 발굴 방식 'news' 는
  아예 못 쓰는 항목으로 막혀 있었다.

■ 실측으로 고른 출처 (라운드 41 · _probe/news_sources_r41.py)
    연합뉴스 경제   120건 · 266ms   수신 OK
    한경 증권       50건 · 133ms   수신 OK
    매경 증권       50건 ·  92ms   수신 OK
  받아 보고 되는 것만 넣었다. 안 되는 곳(머니투데이·이데일리·서울경제)은
  넣지 않는다 — 출처 목록을 길게 적어 놓고 실제로는 안 받는 것이 거짓이다.

■ 규칙
  · 공개 RSS만. 로그인·쿠키·비공식 사설 API 를 쓰지 않는다
  · 기사 **본문을 저장하지 않는다.** 제목·시각·링크만 본다 (저작권)
  · 종목명 매칭은 보수적으로 — 짧은 이름의 오탐을 막는다
  · 받지 못하면 0으로 두고 **어느 출처가 실패했는지** 함께 돌려준다.
    건수를 지어내지 않는다
"""
from __future__ import annotations

import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
TIMEOUT = 10

#: 라운드 41 실측에서 수신에 성공한 공개 RSS 만
FEEDS = [
    ('연합뉴스 경제', 'https://www.yna.co.kr/rss/economy.xml'),
    ('한국경제 증권', 'https://www.hankyung.com/feed/finance'),
    ('매일경제 증권', 'https://www.mk.co.kr/rss/50200011/'),
]

#: '신선한 재료' 로 볼 시간 창 (시간). 그보다 오래된 기사는 후행 보도로 본다.
FRESH_HOURS = 24

#: 위험 낱말 — 있으면 매수 판단에서 감점 요인으로 본다
#:
#: ⚠️ **낱말은 정확해야 한다** (라운드 48 실측 결함)
#:   종전에 `'한정'` 이 있었다. **감사의견 한정**을 잡으려던 것인데
#:   "오뚜기 제주 드립 커피·팔도 왕뚜껑 **한정판**" 이 위험 이슈로 잡혔다.
#:   `'결함'` 도 마찬가지로 "구조적 결함" 기사 아닌 것에 붙는다.
#:   짧고 흔한 낱말은 **더 긴 형태로 못박는다.** 아니면 감점이 소음이 된다.
#:
#:   같은 이유로 `'소송'`·`'인수'` 처럼 중립적으로 쓰이는 말은 뺐다 —
#:   "특허 소송 승소"는 악재가 아니다. 방향을 모르는 낱말로 감점하지 않는다.
RISK_WORDS = ('상장폐지', '거래정지', '감사의견 거절', '감사의견 한정',
              '의견거절', '부적정 의견',
              '횡령', '배임', '분식회계', '압수수색', '리콜',
              '유상증자', '전환사채', '무상감자', '관리종목', '불성실공시',
              '어닝쇼크', '적자전환', '영업정지', '해킹', '파업',
              '상장적격성', '자본잠식', '회생절차', '기업회생', '법정관리')
#: 촉매 낱말 — 있으면 관심을 끌 만한 재료로 본다
CATALYST_WORDS = ('수주', '계약', '공급', '納品', '납품', '신제품', '출시',
                  '임상', '승인', '허가', '특허', '흑자전환', '어닝서프라이즈',
                  '실적개선', '증설', 'M&A', '인수', '합병', '수출', '진출',
                  '협약', 'MOU', '투자유치', '자사주')

#: 사건 유형 — 감성 점수가 아니라 **무슨 일인지**를 구조화한다 (라운드 54b).
#: 공시 분류(§37)와 같은 철학: 낱말 일치만, 해석 금지. 유형별로 지속성이
#: 다르다는 것(수주·임상은 수개월, 급등 해설은 하루)을 화면이 구분해
#: 말할 수 있게 하는 재료다. 점수·게이트에는 넣지 않는다 — 표시 전용.
EVENT_TYPES = (
    ('수주·공급', ('수주', '공급계약', '납품', '納品', '공급')),
    ('실적', ('실적', '영업이익', '어닝', '흑자전환', '적자전환', '매출')),
    ('임상·인허가', ('임상', '승인', '허가', 'FDA', '식약처')),
    ('M&A·지분', ('인수', '합병', 'M&A', '지분', '매각', '경영권')),
    ('증자·CB', ('유상증자', '무상증자', '전환사채', 'CB', 'BW', '감자')),
    ('자사주·배당', ('자사주', '배당', '소각')),
    ('신사업·계약', ('신제품', '출시', '협약', 'MOU', '투자유치',
                 '증설', '진출')),
    ('사법·규제', ('압수수색', '횡령', '배임', '분식회계', '제재', '과징금')),
    # 라운드 61 — 실적 선행 재료 2종 (외부 조언 채택분). 낱말 일치만.
    # '특허'는 종전 신사업 묶음에서 독립 — 특허 소송/분쟁은 사법 쪽
    # 낱말이 따로 잡으므로 여기서는 취득·등록 계열만 못박는다.
    ('특허', ('특허 취득', '특허 등록', '특허청', '특허 출원', '원천기술')),
    ('논문·학회', ('학회 발표', '논문 등재', '논문 게재', 'SCI',
                '임상 결과 발표', '연구 결과 발표')),
)

_CACHE = {'ts': 0.0, 'items': [], 'report': []}
_CACHE_SEC = 600


def _norm_title(t):
    """중복 판정용 정규화 — [단독]·(종합) 같은 장식과 기호·공백을 걷는다.

    임계값 있는 유사도가 아니라 **정규화 후 완전 일치**만 쓴다. 숫자를
    고르지 않기 위해서다(§2). 이 규칙으로 못 잡는 중복은 남는 것이 맞다.
    """
    t = re.sub(r'\[[^\]]{1,12}\]|\([^)]{1,12}\)|【[^】]{1,12}】', '', str(t))
    t = re.sub(r'[^0-9A-Za-z가-힣%]+', '', t)
    return t.lower()


def event_types_of(title):
    """제목의 사건 유형 태그. 낱말 일치만 — 해석하지 않는다."""
    out = []
    for label, words in EVENT_TYPES:
        if any(w in title for w in words):
            out.append(label)
    return out


def _get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def _parse_dt(s):
    """RSS 의 pubDate 를 KST 로. 못 읽으면 None — 지어내지 않는다."""
    if not s:
        return None
    s = str(s).strip()
    for fmt in ('%a, %d %b %Y %H:%M:%S %z', '%a, %d %b %Y %H:%M:%S %Z',
                '%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%d %H:%M:%S'):
        try:
            d = datetime.strptime(s, fmt)
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone(timedelta(hours=9)))
            return d.astimezone(timezone(timedelta(hours=9)))
        except ValueError:
            continue
    return None


def fetch(max_age_sec=_CACHE_SEC):
    """
    공개 RSS 에서 기사 제목·시각·링크를 모은다.

    반환: (items, report)
        items[i]  = {'title','link','source','dt'(KST|None)}
        report[i] = {'source','count','ok','error'}
    """
    now = time.time()
    if _CACHE['items'] and (now - _CACHE['ts']) < max_age_sec:
        return _CACHE['items'], _CACHE['report']

    items, report = [], []
    for name, url in FEEDS:
        try:
            root = ET.fromstring(_get(url))
        except Exception as e:
            report.append({'source': name, 'count': 0, 'ok': False,
                           'error': f'{type(e).__name__}'})
            continue
        got = 0
        for it in root.findall('.//item'):
            t = it.find('title')
            title = (t.text or '').strip() if t is not None else ''
            if not title:
                continue
            lk = it.find('link')
            pd = it.find('pubDate')
            items.append({
                'title': title,
                'link': (lk.text or '').strip() if lk is not None else '',
                'source': name,
                'dt': _parse_dt(pd.text if pd is not None else None),
            })
            got += 1
        report.append({'source': name, 'count': got, 'ok': got > 0,
                       'error': ''})

    # ── 중복 병합 (라운드 54b) — 같은 기사가 3사에 실려 3건으로 세지던 것
    # 신선도는 **가장 이른 시각**을 쓴다. 재탕 기사가 원 기사보다 늦게
    # 왔다고 '신선한 재료'가 되면 novelty 가 거짓이 된다.
    merged = {}
    for it in items:
        k = _norm_title(it['title'])
        if not k:
            continue
        prev = merged.get(k)
        if prev is None:
            it = dict(it, dup_sources=[it['source']])
            merged[k] = it
        else:
            if it['source'] not in prev['dup_sources']:
                prev['dup_sources'].append(it['source'])
            d_new, d_old = it.get('dt'), prev.get('dt')
            if d_new is not None and (d_old is None or d_new < d_old):
                prev['dt'] = d_new          # 첫 보도 시각으로
    items = list(merged.values())

    _CACHE.update(ts=now, items=items, report=report)
    return items, report


def _mentions(title, name):
    """
    제목이 이 종목을 말하고 있는가 — 보수적으로.

    두 글자 이름('DL','GS')은 아무 문장에나 걸리므로 경계를 요구한다.
    괄호·조사 앞뒤는 경계로 인정한다.
    """
    if not name or len(name) < 2:
        return False
    if len(name) <= 3:
        # 짧은 이름은 앞뒤가 한글/영숫자가 아니어야 한다
        return re.search(r'(^|[^0-9A-Za-z가-힣])'
                         + re.escape(name)
                         + r'([^0-9A-Za-z가-힣]|$)', title) is not None
    return name in title


def for_stock(name, items=None, fresh_hours=FRESH_HOURS):
    """
    한 종목의 뉴스 요약. 없는 값을 만들지 않는다.

    반환: {'total','fresh','lagging','risk','catalyst',
           'risk_words','catalyst_words','headlines'}
    """
    if items is None:
        items, _ = fetch()
    hits = [it for it in items if _mentions(it['title'], str(name or ''))]
    now = datetime.now(timezone(timedelta(hours=9)))
    fresh = lagging = 0
    risk_w, cat_w = set(), set()
    ev_types = {}
    for it in hits:
        d = it.get('dt')
        if d is None:
            lagging += 1          # 시각을 모르면 신선하다고 하지 않는다
        elif (now - d) <= timedelta(hours=fresh_hours):
            fresh += 1
        else:
            lagging += 1
        for w in RISK_WORDS:
            if w in it['title']:
                risk_w.add(w)
        for w in CATALYST_WORDS:
            if w in it['title']:
                cat_w.add(w)
        for lb in event_types_of(it['title']):
            ev_types[lb] = ev_types.get(lb, 0) + 1
    return {
        'total': len(hits), 'fresh': fresh, 'lagging': lagging,
        'risk': len(risk_w), 'catalyst': len(cat_w),
        'risk_words': sorted(risk_w), 'catalyst_words': sorted(cat_w),
        # 사건 유형 (라운드 54b) — 표시 전용. 점수에 넣지 않는다
        'event_types': dict(sorted(ev_types.items(), key=lambda x: -x[1])),
        'headlines': [{'title': h['title'], 'source': h['source'],
                       'link': h['link'],
                       # 3사 중복이면 병합 사실을 밝힌다 — 건수 부풀림 방지
                       'sources_n': len(h.get('dup_sources') or [h['source']]),
                       'events': event_types_of(h['title']),
                       'when': h['dt'].strftime('%m-%d %H:%M') if h['dt']
                       else '시각 미상'} for h in hits[:6]],
    }


def status():
    """화면에 그대로 띄울 연동 현황."""
    _, report = fetch()
    got = sum(r['count'] for r in report)
    ok = sum(1 for r in report if r['ok'])
    return {
        'sources': report,
        'total_items': got,
        'ok_sources': ok,
        'availability': ('full' if ok == len(FEEDS)
                         else 'partial' if ok else 'none'),
        'detail': (f'공개 RSS {ok}/{len(FEEDS)}곳에서 기사 {got}건 수신 '
                   f'(제목·시각·링크만 · 본문 미저장)'
                   if ok else '뉴스 RSS 를 한 곳도 받지 못했습니다'),
    }
