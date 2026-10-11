# -*- coding: utf-8 -*-
"""시장 스캔 — 관심종목 발굴 → 정밀 퀀트 분석 (라운드 484 · 화면에서 떼어 낸 한 곳).

종전엔 이 몸통이 `web_app.run_market_scan` 안에 있었다(세션 상태 · 진행 막대와 한 함수). 그래서 개장 전 리포트는 **앱을 열 때만**
만들어졌고, 리포트가 언제 만들어지는지가 사람이 언제 앱을 여는지에 묶였다 — 라운드 483 이 센 장중 리포트 9개(그 가격으로 그날 봉
전체를 채점)와 장 마감 2분 뒤 리포트(가격이 확정 종가가 아니었다)가 그 결과다. 몸통을 여기 한 곳에 두고 화면(`web_app.run_market_scan`
· 진행 막대·세션 상태만)과 이 PC 의 저녁 작업(`scripts/build_premarket_report.py` · 장 마감 뒤)이 **같은 함수**를 부른다(§4 — 스캔 길이
둘이면 한쪽만 고치는 일이 생긴다). 판정·점수·문턱·후보 수는 한 글자도 안 바꿨다 — 옮긴 것이다.

화면에 기대는 것(진행 막대 · 스피너)은 콜백으로 받는다 — 이 모듈은 streamlit 을 가져오지 않는다.
"""
from __future__ import annotations

import contextlib

import market_attention

#: 당일 거래대금 하한 — 종전 `web_app.run_market_scan` 의 `_MIN_TRADE_VALUE` 그대로(옮긴 값 · 새 숫자 아님).
MIN_TRADE_VALUE = 5e8          # 당일 거래대금 5억원

#: 화면 기본값과 같다(`web_app` 의 접힌 단계 폴백 — 'composite' · 5 · 0.80). 저녁 작업이 이것으로 돈다.
DEFAULT_STRATEGY = 'composite'
DEFAULT_DEPTH = 5
DEFAULT_RHO = 0.80


def _nothing(*_a, **_k):
    return None


def run(q_engine, b_engine, t_ref_str, *, attention_strategy=DEFAULT_STRATEGY, scan_depth=DEFAULT_DEPTH,
        rho_cutoff=DEFAULT_RHO, watch=None, progress=None, deep_ctx=None):
    """시장 스캔 한 번 → dict.

    kind: 'empty'(관심종목 후보를 못 받았다 · reason) · 'ok'(끝까지 갔다 · results).
    그 밖의 칸: lite(경량 스캔 셈) · attention_result · universe_total · unmapped · failures(정밀 분석에서 빠진 종목과 사유).
    progress(msg, step=None) · deep_ctx(n) → 정밀 분석을 감쌀 context manager — 둘 다 화면이 넘긴다(없으면 조용히).
    예외는 삼키지 않는다 — 부르는 쪽이 사유와 함께 '실패'로 적는다(라운드 383)."""
    _p = progress or _nothing
    # ── 전 종목 경량 스캔 ────────────────────────────────────────────
    # 순위 페이지 2종에서만 출발하면 거래가 한산한 종목은 애초에 후보가
    # 되지 못한다. 유니버스에는 이미 시총·거래대금이 실려 있으므로
    # **추가 요청 없이** 전 종목을 한 번 훑을 수 있다. 여기서 거르는 건
    # 데이터가 없거나 유동성이 없어 어차피 못 사는 종목뿐이다.
    #
    # ⚠️ 라운드 37 — 이 블록은 관심종목 탐색 **앞**에 와야 한다.
    # 종전에는 뒤에 있었고, 순위 페이지가 비면 그 전에 return 해 버려서
    # 경량 스캔이 **실행조차 안 된 채** 화면에 '0개'로 찍혔다. 사용자는
    # "전 종목을 훑었는데 하나도 없구나"로 읽는다 — 사실이 아니었다.
    _p("종목 코드·시장 구분 확인 중", step=1)
    universe = b_engine.get_screener_universe(full_market=True)
    by_code = {u['symbol'].split('.')[0]: u for u in universe}

    _MIN_TRADE_VALUE = MIN_TRADE_VALUE
    # ⚠️ 라운드 37 — **못 잰 것으로 거르지 않는다.**
    # 유니버스가 거래대금을 안 실어 오는 시간대(장 시작 전 등)에는
    # today_trade_value 가 전 종목 None 이고 liquidity_confirmed 도 전부
    # False 다. 종전 코드는 이걸 '유동성 없음'으로 세어 2,997종목을 전부
    # 탈락시켰고, 화면은 "유동성·데이터 조건 통과 0개"라고 말했다.
    # 실제로는 유동성이 없는 게 아니라 **거래대금을 수집하지 못한 것**이다.
    # 그래서 수신율을 먼저 보고, 거의 안 왔으면 그 필터를 끈다.
    _tv_seen = sum(1 for u in universe if (u.get('today_trade_value') or 0) > 0)
    _tv_usable = _tv_seen >= max(20, len(universe) * 0.05)
    _lite = {'total': len(universe), 'no_price': 0, 'no_liquidity': 0,
             'thin': 0, 'passed': 0, 'tv_seen': _tv_seen,
             'tv_usable': _tv_usable}
    _lite_pass, _lite_rows = set(), []
    for u in universe:
        if not u.get('base_price'):
            _lite['no_price'] += 1
            continue
        if _tv_usable:
            if not u.get('liquidity_confirmed'):
                _lite['no_liquidity'] += 1
                continue
            if (u.get('today_trade_value') or 0) < _MIN_TRADE_VALUE:
                _lite['thin'] += 1
                continue
        _lite_pass.add(u['symbol'].split('.')[0])
        _lite_rows.append(u)
    _lite['passed'] = len(_lite_pass)

    # 순위 페이지가 죽으면 경량 스캔 통과 종목을 거래대금 순으로 대신 쓴다
    _p("거래대금·상승률 순위에서 관심종목 추리는 중", step=2)
    att = market_attention.find_attention_candidates(
        attention_strategy, top_n=scan_depth, progress=progress,
        watchlist=watch, fallback_pool=_lite_rows)
    out = {'lite': _lite, 'attention_result': att, 'unmapped': [], 'failures': [], 'results': []}
    if att.get('unavailable') or not att['rows']:
        return dict(out, kind='empty', universe_total=att.get('pool_size', 0),
                    reason=str(att.get('unavailable') or '관심종목 후보가 0개입니다'))

    # 2단계 — 후보에 시장 구분을 붙여 기존 정밀 파이프라인에 넘긴다
    target, unmapped = [], []
    for r in att['rows']:
        u = by_code.get(r['code'])
        if not u:
            unmapped.append(f"{r['name']}({r['code']})")
            continue
        target.append({**u, 'attention': r['attention'],
                       'selection_reason': r.get('selection_reason'),
                       'attention_components': r['components']})
    out['unmapped'] = unmapped
    out['universe_total'] = att['pool_size']

    _p(f"관심종목 {len(target)}개를 하나씩 정밀 분석하는 중", step=4)
    with (deep_ctx(len(target)) if deep_ctx else contextlib.nullcontext()):
        results = q_engine.run_screener_scan(target, t_ref_str, b_engine=b_engine, rho_cutoff=rho_cutoff)
    # ⚠️ 라운드 216 — 실패 사유가 **rerun 을 못 넘고 있었다**(엔진 객체에만 남았다). 결과와 **같은 곳**에 사유도 담아 돌려준다(§4).
    out['failures'] = list(getattr(q_engine, 'last_scan_failures', None) or [])

    # 관심점수를 결과 행에 붙인다 (순위에는 동점 보조기준으로만 쓴다 — §12)
    _att_by_symbol = {t['symbol']: t for t in target}
    for row in (results or []):
        src = _att_by_symbol.get(row.get('symbol'))
        if src:
            row['attention'] = src['attention']
            row['selection_reason'] = src['selection_reason']
            row['attention_components'] = src['attention_components']
    out['results'] = results or []
    out['kind'] = 'ok'
    return out


def market_label_of(results):
    """개장 전 리포트에 적는 시장 국면 이름 — 첫 행 스냅샷의 맥락 국면(없으면 시장 국면 · 못 읽으면 빈 글자). 종전 `web_app` 의 그 셈."""
    try:
        fs0 = (((results or [None])[0] or {}).get('snapshot') or {}).get('four_scores') or {}
        return str(fs0.get('context_regime_label') or fs0.get('market_regime_label') or '')
    except Exception:                                          # noqa: BLE001
        return ''
