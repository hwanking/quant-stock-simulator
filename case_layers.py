# -*- coding: utf-8 -*-
"""
계층형 케이스 실측 조회 (라운드 58 — 표시 전용).

'산출 불가'로 끝내지 않기 위한 정직한 확장: 초근접 표본이 부족하면
**더 넓은 계층의 실측을 이름표와 함께** 보여 준다.

지키는 것
  · 어떤 층의 값도 '이 종목의 확률'이라 부르지 않는다 — 그 계층의 실측이다
  · 층을 섞어 하나의 보정확률을 만들지 않는다 — 그건 R59 사전등록
    (Brier·보정도 valid 비교) 게이트를 통과해야 한다
  · 좁은 층이 비어 있으면 비어 있다고 말한다. 문턱을 낮춰 채우지 않는다
"""
from __future__ import annotations

import json
import os

_CACHE = {'loaded': False, 'doc': None}


def _doc():
    if not _CACHE['loaded']:
        _CACHE['loaded'] = True
        try:
            p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             'data', 'case_layers.json')
            with open(p, encoding='utf-8') as f:
                _CACHE['doc'] = json.load(f)
        except Exception:                                      # noqa: BLE001
            _CACHE['doc'] = None
    return _CACHE['doc']


def _band_of(score):
    for lo, hi in ((0, 40), (40, 50), (50, 58), (58, 65), (65, 101)):
        if lo <= score < hi:
            return f'{lo}-{hi - 1}'
    return None


def _proxies_of(fs):
    """R55/생성 스크립트와 같은 정의 — 값으로 대조되는 검사가 있다."""
    out = []
    rp = fs.get('range_position_pct')
    bb = fs.get('bb_position_pct')
    if fs.get('m10_disparity', 0) > 0 and rp is not None and rp <= 50:
        out.append('눌림')
    if rp is not None and rp >= 80:
        out.append('돌파')
    if bb is not None and bb <= 20:
        out.append('평균회귀')
    if 'BUY' in str(fs.get('demark_state') or ''):
        out.append('DeMARK매수')
    return out


_ST_KO = {'ABOVE_BOTH': '상승(20·60선 위)', 'REBOUND': '반등 초기',
          'PULLBACK': '조정', 'BEAR': '약세'}


_HIER = {'loaded': False, 'doc': None}


def _hier_doc():
    if not _HIER['loaded']:
        _HIER['loaded'] = True
        try:
            p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             'data', 'hier_prob_tables.json')
            with open(p, encoding='utf-8') as f:
                _HIER['doc'] = json.load(f)
        except Exception:                                      # noqa: BLE001
            _HIER['doc'] = None
    return _HIER['doc']


def blended_prob(score, sector=None, regime_code=None, fs=None):
    """
    계층 혼합 목표 선도달 확률 (라운드 59 채택 — PREREG_R59 게이트 통과).

    L5 → L4 → L4b → L3 → L2 순으로 Beta-Binomial 축소 갱신 (m=100).
    valid 1회 실측: Brier 0.2305 vs 현행 유사사례 0.2566 · 보정이탈
    12.1 vs 35.4%p. 유사사례 확률이 있는 행 부분집합에서도 우위.

    반환: {'p': 0~1, 'layers': 사용 층 수, 'n_narrow': 가장 좁은 층 n,
           'wilson_low','wilson_high': 그 n 기준 구간, 'label': 근거 요약}
    없으면 None — L5 조차 없는 점수는 지어내지 않는다.
    """
    doc = _hier_doc()
    if not doc or score is None:
        return None
    b = _band_of(float(score))
    if not b:
        return None
    m = float(doc.get('m') or 100)
    cells = doc.get('cells') or {}
    fs = fs or {}
    keys = [('L5', b)]
    if regime_code:
        keys.append(('L4', f'{b}|{regime_code}'))
        for pxy in _proxies_of(fs):
            keys.append(('L4b', f'{b}|{regime_code}|{pxy}'))
    vol = fs.get('vol_20')
    ter = doc.get('vol_terciles') or []
    if fs.get('market') and isinstance(vol, (int, float)) and len(ter) == 2:
        vb = '저' if vol <= ter[0] else ('중' if vol <= ter[1] else '고')
        keys.append(('L3', f"{b}|{fs.get('market')}|{vb}"))
    if sector and regime_code:
        keys.append(('L2', f'{b}|{sector}|{regime_code}'))

    p = None
    used, n_narrow, label = 0, None, ''
    for layer, key in keys:
        a = cells.get(f'{layer}|{key}')
        if not a or a[0] == 0:
            continue
        n, k = a[0], a[1]
        if p is None:
            p = k / n
        else:
            p = (k + m * p) / (n + m)
        used += 1
        n_narrow, label = n, f'{layer}:{key}'
    if p is None:
        return None
    import math as _m
    z = 1.96
    n_ = max(1, n_narrow)
    d = 1 + z * z / n_
    c = p + z * z / (2 * n_)
    w = z * _m.sqrt(max(0.0, p * (1 - p) / n_ + z * z / (4 * n_ * n_)))
    return dict(p=float(p), layers=used, n_narrow=n_narrow,
                wilson_low=float((c - w) / d), wilson_high=float((c + w) / d),
                label=label)


def layers_for(score, sector=None, regime_code=None, fs=None):
    """
    지금 종목의 문맥에 맞는 계층 실측 행 목록 (넓은 층 → 좁은 층 순).

    반환 행: {'label','n','hit','wilson','ev','narrow'} — 없으면 빼고,
    업종 층이 점수대 문제로 미축적이면 그 사실을 note 로 알린다.
    """
    doc = _doc()
    if not doc or score is None:
        return [], None
    b = _band_of(float(score))
    if not b:
        return [], None
    fs = fs or {}
    rows = []

    v = (doc.get('L5') or {}).get(b)
    if v:
        rows.append(dict(label=f'같은 점수대({b}점) 전체', narrow=0, **v))
    if regime_code:
        v = (doc.get('L4') or {}).get(f'{b}|{regime_code}')
        if v:
            rows.append(dict(
                label=f'점수대 × {_ST_KO.get(regime_code, regime_code)} 국면',
                narrow=1, **v))
        for pxy in _proxies_of(fs):
            v = (doc.get('L4b') or {}).get(f'{b}|{regime_code}|{pxy}')
            if v:
                rows.append(dict(
                    label=f'점수대 × 국면 × {pxy} 자리', narrow=2, **v))
    mkt = fs.get('market')
    vol = fs.get('vol_20')
    ter = doc.get('vol_terciles') or []
    if mkt and isinstance(vol, (int, float)) and len(ter) == 2:
        vb = ('저변동' if vol <= ter[0]
              else '중변동' if vol <= ter[1] else '고변동')
        v = (doc.get('L3') or {}).get(f'{b}|{mkt}|{vb}')
        if v:
            rows.append(dict(label=f'점수대 × {mkt} × {vb} 종목',
                             narrow=1, **v))
    note = None
    if sector and regime_code:
        v = (doc.get('L2') or {}).get(f'{b}|{sector}|{regime_code}')
        if v:
            rows.append(dict(label=f'점수대 × {sector} × 국면', narrow=2, **v))
        elif b not in ('58-64', '65-100'):
            note = ('업종별 실측은 매수권(58점 이상)만 축적돼 있어 이 '
                    '점수대에서는 아직 없습니다')
    rows.sort(key=lambda x: x['narrow'])
    return rows, note
