# -*- coding: utf-8 -*-
"""
관망 조건 감시 — 조건이 풀리면 알려 준다.

라운드 24 에서 관망 종목마다 '다음 조건'(지지 확인·돌파 후 재지지·과열
해소·거래량 안정)을 냈지만 **저장만 하고 다시 보지 않았다.** 그러면
사용자는 매번 직접 검색해야 한다. 여기서 그걸 잇는다.

■ 저장하는 것 (.portfolio/watch_conditions.json)
  종목마다: 등록 시각 · 등록 당시 가격 · 조건 묶음(지지가·돌파가·과열
  해소 필요 여부·거래량 안정 기준) · 등록 엔진 버전

■ 확인하는 것
  최신 시세와 지표로 각 조건을 다시 재서, 충족되면 '해소'로 표시한다.
  · 지지 조건: 저가가 지지가 부근(±0.5%)까지 왔고 종가가 그 위에서 버텼는가
  · 돌파 조건: 종가가 돌파가를 넘었는가
  · 과열 해소: 볼린저 위치 80% 아래 **그리고** Williams %R −20 아래
  · 거래량 안정: 20일 평균 대비 1.2배 아래

■ 지어내지 않는다
  시세를 못 받으면 '확인 불가'로 남긴다. 조건이 애매하면 미충족으로 둔다 —
  좋은 쪽으로 기울이면 알림이 거짓이 된다.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(BASE, '.portfolio', 'watch_conditions.json')

#: 지지 확인 허용 오차 % — 정확히 그 값을 찍는 일은 드물다
SUPPORT_TOL = 0.5
COOL_BB = 80.0
COOL_WR = -20.0
VOL_CALM = 1.2


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def load():
    try:
        with open(STORE, encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {'items': []}
    except Exception:
        return {'items': []}


def save(data):
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    tmp = STORE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STORE)


def register(symbol, name, price, next_action, engine_version=''):
    """
    관망 조건을 저장한다. 같은 종목이 이미 있으면 **덮어쓴다** —
    조건은 최신 판단이 맞다.

    반환: 저장된 항목 dict, 또는 None(저장할 조건이 없음)
    """
    alert = (next_action or {}).get('alert')
    if not alert or not alert.get('levels'):
        return None
    data = load()
    items = [it for it in data.get('items', []) if it.get('symbol') != symbol]
    item = {
        'symbol': symbol, 'name': name,
        'registered_at': _now(),
        'price_at_register': price,
        'kind': alert.get('kind'),
        'levels': alert.get('levels'),
        'need_cooldown': bool(alert.get('need_cooldown')),
        'need_volume_calm': bool(alert.get('need_volume_calm')),
        'vol_calm_ratio': alert.get('vol_calm_ratio', VOL_CALM),
        'engine_version': engine_version,
        'resolved': False, 'resolved_at': None, 'resolved_why': None,
    }
    items.append(item)
    data['items'] = items
    save(data)
    return item


def remove(symbol):
    data = load()
    n0 = len(data.get('items', []))
    data['items'] = [it for it in data.get('items', [])
                     if it.get('symbol') != symbol]
    save(data)
    return n0 - len(data['items'])


def check_one(item, price, low, high, close, bb_pos=None, wr=None,
              vol_ratio=None):
    """
    한 항목의 조건을 지금 값으로 다시 잰다.

    반환: {'met': [...], 'unmet': [...], 'resolved': bool, 'why': str}
    값이 없으면 그 조건은 '확인 불가'로 미충족에 남긴다.
    """
    # 가격 조건(지지·돌파)은 **둘 중 하나**만 맞으면 된다 — "24,000에서
    # 지지되거나, 26,550을 돌파하거나" 였지 둘 다가 아니었다.
    # 반면 과열 해소·거래량 안정은 **필수**다(막는 조건이므로).
    met, unmet, price_pending = [], [], []
    price_ok = None

    for lv in item.get('levels') or []:
        kind, level = lv.get('kind'), lv.get('level')
        if not level:
            continue
        if kind == 'support':
            if low is None or close is None:
                price_pending.append(f"지지 {level:,.0f}원 — 시세 확인 불가")
                continue
            touched = low <= level * (1 + SUPPORT_TOL / 100.0)
            held = close >= level * (1 - SUPPORT_TOL / 100.0)
            if touched and held:
                met.append(f"{level:,.0f}원 지지 확인 (저가 {low:,.0f} · "
                           f"종가 {close:,.0f})")
                price_ok = 'support'
            else:
                price_pending.append(f"{level:,.0f}원 지지 아직 (저가 "
                             f"{low:,.0f} · 종가 {close:,.0f})")
        elif kind == 'breakout':
            if close is None:
                price_pending.append(f"돌파 {level:,.0f}원 — 시세 확인 불가")
                continue
            if close > level:
                met.append(f"{level:,.0f}원 돌파 (종가 {close:,.0f})")
                price_ok = price_ok or 'breakout'
            else:
                price_pending.append(f"{level:,.0f}원 돌파 아직 (종가 {close:,.0f})")

    if item.get('need_cooldown'):
        if bb_pos is None or wr is None:
            unmet.append('과열 해소 — 지표 확인 불가')
        elif bb_pos < COOL_BB and wr < COOL_WR:
            met.append(f'과열 해소 (볼린저 {bb_pos:.0f}% · %R {wr:.0f})')
        else:
            unmet.append(f'과열 아직 (볼린저 {bb_pos:.0f}% · %R {wr:.0f})')

    if item.get('need_volume_calm'):
        r = item.get('vol_calm_ratio', VOL_CALM)
        if vol_ratio is None:
            unmet.append('거래량 안정 — 확인 불가')
        elif vol_ratio <= r:
            met.append(f'거래량 안정 ({vol_ratio:.1f}배)')
        else:
            unmet.append(f'거래량 아직 높음 ({vol_ratio:.1f}배)')

    # 가격 조건이 하나라도 충족되고, 남은 필수 조건이 없어야 '해소'다.
    # 애매하면 미충족으로 둔다 — 좋은 쪽으로 기울이면 알림이 거짓이 된다.
    # 가격은 둘 중 하나면 되고(price_pending 은 판정에서 뺀다),
    # 막는 조건(과열·거래량)은 전부 풀려야 한다.
    resolved = bool(price_ok) and not unmet
    why = ''
    if resolved:
        why = '지지 확인' if price_ok == 'support' else '돌파 확인'
        if len(met) > 1:
            why += ' · ' + ' · '.join(met[1:])
    # 아직 안 맞은 가격 조건도 돌려준다 — 무엇을 더 기다리는지 알아야 한다
    return {'met': met, 'unmet': unmet, 'pending': price_pending,
            'resolved': resolved, 'why': why}


def sentence(item, res):
    """알림 문장 — 무엇이 풀렸고 이제 무엇을 하면 되는지."""
    nm = item.get('name') or item.get('symbol')
    if not res['resolved']:
        return None
    head = f"{nm} — 이전 관망 조건이 해소됐습니다."
    body = ' · '.join(res['met'])
    tail = ('1차 분할매수 검토 구간에 들어왔습니다.'
            if item.get('kind') in ('pullback', 'observe')
            else '돌파 후 지지가 확인됐습니다.')
    return f"{head} {body}. {tail}"
