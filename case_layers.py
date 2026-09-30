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
    # 라운드 402 — 깃발을 읽기 **전에** 올려 동시에 부른 두 번째 세션이 None 을 받았다. 한 곳이 읽는다.
    import artifact_io
    return artifact_io.load_once(
        _CACHE, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'case_layers.json'))


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
    # 라운드 402 — 서버를 막 띄운 첫 화면이 이 경로로 '계층 보정 확률 미산출'을 냈다(다시 그리면 값이 나왔다)
    import artifact_io
    return artifact_io.load_once(
        _HIER, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'hier_prob_tables.json'))


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


def baseline_note(art=None, table_made=None):
    """이 확률을 **'늘 같은 확률'** 과 견준 블라인드 결과 한 문장 (라운드 401 · 표시 전용).

    외부 검토(2026-10-01)가 짚었다 — 라운드 59 의 게이트와 라운드 397 은 이 확률을 **다른 확률**(종전
    유사사례 확률 · 다시 적합한 표)과만 견줬고, **아무것도 모르는 예측**(학습 구간 적중률 하나를 모든
    행에 내는 것)과는 안 견줬다. 견주니 블라인드에서 가려지지 않았다(`scripts/brier_baseline_r401.py`).
    그 사실을 이 확률 옆에 적는다 — 없으면 '검증 게이트 통과'가 **기본값보다 낫다**로 읽힌다.

    값은 산출물에서 읽는다(손으로 적은 수는 낡는다). 문장은 차이의 **신뢰구간 부호**로만 가른다 —
    문턱 없음. 산출물이 **지금 운영 표와 다른 표**와 견준 것이면 None(낡은 비교를 지금 표의 성적처럼
    말하지 않는다 · §3). 못 읽어도 None.
    `art`·`table_made` 는 회귀가 갈래를 심어 보려고 받는다(기본은 파일과 운영 표).
    """
    try:
        a = art
        if a is None:
            p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'hier_prob_baseline.json')
            with open(p, encoding='utf-8') as f:
                a = json.load(f)
        made = table_made if table_made is not None else (_hier_doc() or {}).get('made')
        if not made or a.get('table_made') != made:
            return None
        d, lo, hi = float(a['d']), float(a['d_lo']), float(a['d_hi'])
        head = (f"블라인드 {int(a['rows']):,}행(기준일 {int(a['dates'])}일 · {a['made']} 잼)에서 이 확률의 "
                f"Brier {float(a['brier_table']):.4f} 를 '늘 {float(a['train_q']) * 100:.1f}%'(이 확률 표를 만든 "
                f"개발 구간의 적중률 하나)라고 말하는 것 {float(a['brier_const']):.4f} 와 견주면 차이 {d:+.4f} "
                f"(95% [{lo:+.4f}, {hi:+.4f}])")
        if lo <= 0.0 <= hi:
            return head + " — 가려지지 않습니다. 이 확률이 기본값보다 더 잘 맞는다는 근거는 아직 없습니다."
        if hi < 0.0:
            return head + " — 이 확률이 기본값보다 더 잘 맞았습니다."
        return head + " — 이 확률이 기본값보다 덜 맞았습니다."
    except Exception:                                          # noqa: BLE001
        return None


def self_history(ticker):
    """이 종목 자체의 과거 신호 이력 (표시 전용 · R59 혼합 미포함).

    반환: {'n','hit','wilson','recent':[[날짜,점수,결과,수익%],...]} | None
    """
    doc = _doc()
    if not doc or not ticker:
        return None
    tk = str(ticker)
    s = (doc.get('SELF') or {}).get(tk)
    if not s:
        return None
    return dict(s, recent=(doc.get('SELF_RECENT') or {}).get(tk) or [])


def layers_for(score, sector=None, regime_code=None, fs=None, ticker=None):
    """
    지금 종목의 문맥에 맞는 계층 실측 행 목록 (넓은 층 → 좁은 층 순).

    반환 행: {'label','n','hit','wilson','ev','narrow'} — 없으면 빼고,
    업종 층이 점수대 문제로 미축적이면 그 사실을 note 로 알린다.
    ticker 를 주면 SELF(이 종목 자체) 층이 가장 좁은 층으로 붙는다 —
    표시 전용이며 R59 혼합 확률에는 들어가지 않는다.
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
    if ticker:
        s = (doc.get('SELF') or {}).get(str(ticker))
        if s:
            rows.append(dict(label='이 종목 자체 과거 신호 (전 점수대)',
                             narrow=3, n=s['n'], hit=s['hit'],
                             wilson=s['wilson'], ev=None))
    rows.sort(key=lambda x: x['narrow'])
    return rows, note
