# -*- coding: utf-8 -*-
"""
라운드 330 — 코스피 일봉과 4상태 국면을 **한 곳**에서 준다.

무엇이 있었나
  연구 스크립트 여섯이 `_probe/kospi_daily_cache.json` 을 **직접** 열고 있었다. 그 파일은
  gitignored `_probe/` 안에 있어 이 PC 에만 있고, 쓰는 곳은 그중 하나(`regime_moe_lab`)뿐이었다.
  그래서 클라우드 축적의 `weakness_map.py` 는 **매번** `FileNotFoundError` 로 죽었고 `|| true`
  가 삼켰다 — 원장이 801줄 자라 신선도 검사(허용 800줄)가 붉어진 2026-09-16 에야 드러났다.
  그리고 이 PC 의 캐시도 **2026-08-07 에서 멈춰** 있어, 그 뒤 기준일 행은 국면이 조용히 비었다.

규칙
  · 국면 판정은 `trade_plan.market_state` 그대로(20·60일 평균 · 60일 평균의 5봉 전) — 새 규칙 없음.
  · 봉 수 3,000 은 `regime_moe_lab` 이 이미 쓰던 수다(새 숫자 아님).
  · `prefer_cache=False`(관측 산출물) — 먼저 받고, 못 받으면 캐시, 둘 다 없으면 None.
    `prefer_cache=True`(재현이 목적인 연구 스크립트) — 캐시가 있으면 그대로, 없을 때만 받는다.
  · 못 받으면 None 이다 — 지어내지 않는다(§3). 받은 것은 캐시에 남긴다(다음 실패 대비).
  · 어디서 왔는지(`source`)와 마지막 날짜를 같이 돌려준다 — 산출물이 그것을 적는다.
"""
import io
import json
import os
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)

IDX_CACHE = os.path.join(PROJ, '_probe', 'kospi_daily_cache.json')
COUNT = 3000


def _iso(d):
    """네이버 지수 날짜 'YYYYMMDD' · 'YYYY.MM.DD' · 'YYYY-MM-DD' → 'YYYY-MM-DD' (못 읽으면 None)."""
    d8 = str(d)[:10].replace('.', '').replace('-', '')[:8]
    if len(d8) != 8 or not d8.isdigit():
        return None
    return f'{d8[:4]}-{d8[4:6]}-{d8[6:8]}'


def _read_cache(path):
    try:
        with io.open(path, encoding='utf-8') as f:
            c = json.load(f)
        dates, closes = list(c['dates']), [float(x) for x in c['closes']]
        if len(dates) != len(closes) or len(closes) < 65:
            return None
        return dates, closes, f"캐시({c.get('made') or '만든 날 미기록'})"
    except Exception:                                          # noqa: BLE001
        return None


def _fetch(count, fetcher=None):
    try:
        if fetcher is None:
            import bitemporal_engine as be
            fetcher = be.BitemporalEngine().fetch_index_daily
        r = fetcher('KOSPI', count=count)
    except Exception:                                          # noqa: BLE001
        return None
    if r is None:
        return None
    dates, closes = [str(x) for x in r[0]], [float(x) for x in r[1]]
    if len(dates) != len(closes) or len(closes) < 65:
        return None
    return dates, closes, '실시간 수신'


def series(prefer_cache=False, count=COUNT, cache_path=IDX_CACHE, fetcher=None, write_cache=True):
    """(dates, closes, source) 또는 None. 규칙은 모듈 독스트링."""
    if prefer_cache:
        got = _read_cache(cache_path)
        if got:
            return got
        got = _fetch(count, fetcher)
    else:
        got = _fetch(count, fetcher)
        if got is None:
            return _read_cache(cache_path)
    if got and write_cache:
        try:
            import datetime as _dt
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with io.open(cache_path, 'w', encoding='utf-8') as f:
                json.dump({'dates': got[0], 'closes': got[1],
                           'made': _dt.date.today().isoformat()}, f)
        except Exception:                                      # noqa: BLE001
            pass                  # 캐시를 못 남겨도 받은 값은 쓴다
    return got


def states_from(dates, closes):
    """날짜('YYYY-MM-DD') → 4상태 코드. 앞 65봉은 평균 창이 안 차서 비운다."""
    import numpy as np
    import trade_plan as tp
    arr = np.array(closes, dtype=float)
    out = {}
    for i in range(65, len(arr)):
        st = tp.market_state(arr[i], arr[i - 19:i + 1].mean(),
                             arr[i - 59:i + 1].mean(),
                             arr[i - 64:i - 4].mean())
        k = _iso(dates[i])
        if k:
            out[k] = st.get('code')
    return out


def states(prefer_cache=False, **kw):
    """(날짜 → 상태 dict, source, 마지막 날짜) 또는 None."""
    got = series(prefer_cache=prefer_cache, **kw)
    if not got:
        return None
    dates, closes, src = got
    return states_from(dates, closes), src, _iso(dates[-1])
