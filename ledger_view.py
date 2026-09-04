# -*- coding: utf-8 -*-
"""원장 기준일 간격 규칙 — 한 곳 (라운드 217).

■ 왜 이 파일이 있는가
  `scripts/calibration_lab.py` 의 기준일 격자는 **가장 최근 봉에서** 25봉씩
  거슬러 뽑는다 (`usable[::-25]`). 그래서 격자는 거래일마다 한 봉씩 밀리고,
  완료 집합은 (종목, 날짜) **정확히 일치**로만 본다. 다른 날에 랩을 돌릴
  때마다 한 봉 어긋난 격자가 통째로 "새 케이스"가 됐다.

  2026-09-03 실측(원장 250,725행 · 1,547종목): 같은 종목의 이웃 기준일
  간격이 3일 이하 18.4% · 4~14일 32.1% · 15~30일 21.6% — **72%가 20봉
  결과 창 안에서 겹친다.** 종목당 기준일 수가 108(한 격자) · 296 · 484 ·
  376 으로 뭉친다 — 밀린 격자 여러 벌의 합집합이다.
  채택된 규칙(25봉 간격 · `calibration_lab.py:53` "건드리지 않는다")을
  실제로 지키는 부분집합은 **122,554건(48.9%)** 이다.

■ 규칙 — 새 숫자가 아니다
  25봉 × 7/5 = **35 달력일**. 이미 채택된 25봉 간격을 달력일로 옮긴 것이다
  (봉 달력은 종목마다 조금 다르고, 화면은 원장의 날짜열만 가지므로
  달력일이 양쪽에서 같은 답을 준다). 문턱을 새로 고르지 않았다 (§2).

■ 어디서 쓰나 — 둘 다 이 함수를 부른다 (§4 · 두 벌 금지)
  · 랩(`calibration_lab.main`): 같은 종목에 35일 안 케이스가 이미 있으면
    그 기준일을 **계획에서 뺀다** (전방 모드 제외 — R78 이 일부러 촘촘히
    뽑고 에피소드로 병기한다).
  · 화면(원장 캡션): "독립 사례 N건" 대신 **겹침 없는 부분집합 수**를
    같이 낸다. 원장 행은 지우지 않는다 (R197 — 파생물을 줄이지 않는다).
"""
import bisect
import datetime as _dt

#: 25봉 × 7/5. 채택된 간격(25봉)의 달력일 표기 — 새 문턱이 아니다.
SPACING_BARS = 25
MIN_GAP_DAYS = SPACING_BARS * 7 // 5          # = 35


def _day(d):
    return _dt.date.fromisoformat(str(d)[:10])


def too_close(sorted_dates, d, min_gap_days=MIN_GAP_DAYS):
    """`sorted_dates`(ISO 문자열 오름차순) 안에 `d` 와 `min_gap_days` 미만인
    날짜가 있으면 True. 같은 날짜(0일)도 '가깝다'로 본다."""
    if not sorted_dates:
        return False
    d = str(d)[:10]
    i = bisect.bisect_left(sorted_dates, d)
    dd = _day(d)
    for j in (i - 1, i):
        if 0 <= j < len(sorted_dates):
            if abs((_day(sorted_dates[j]) - dd).days) < min_gap_days:
                return True
    return False


def dates_by_ticker(pairs):
    """{(ticker, date), ...} → {ticker: [date, ...] 오름차순}."""
    out = {}
    for tk, d in pairs:
        out.setdefault(tk, []).append(str(d)[:10])
    for tk in out:
        out[tk].sort()
    return out


def spaced_mask(df, ticker_col='ticker', date_col='date',
                min_gap_days=MIN_GAP_DAYS):
    """종목별로 이른 날짜부터 탐욕적으로 `min_gap_days` 이상 떨어진 행만 True.

    입력 순서와 인덱스를 보존한 bool Series 를 돌려준다. 한 종목의 같은
    날짜가 여러 행이면 첫 행만 True 다. 겹침 없는 부분집합의 크기를 재는
    용도 — 규칙을 바꾸지 않는 **표시·측정 전용**이다.
    """
    import pandas as pd
    if df is None or len(df) == 0:
        return pd.Series([], dtype=bool)
    # 250,725행에서 pandas .iat 루프는 3.5초였다 — 리스트로 내려 돈다 (같은 답).
    tks = df[ticker_col].astype(str).tolist()
    ds = df[date_col].astype(str).str[:10].tolist()
    order = sorted(range(len(tks)), key=lambda k: (tks[k], ds[k]))
    flags = [False] * len(tks)
    last_tk, last_day = None, None
    for k in order:
        tk, d = tks[k], ds[k]
        try:
            day = _day(d)
        except Exception:                                   # noqa: BLE001
            continue                                        # 날짜 못 읽으면 못 센다
        if tk != last_tk:
            last_tk, last_day = tk, None
        if last_day is None or (day - last_day).days >= min_gap_days:
            flags[k] = True
            last_day = day
    return pd.Series(flags, index=df.index, dtype=bool)


def spaced_count(df, **kw):
    """`spaced_mask` 의 True 개수. 빈 입력이면 0."""
    m = spaced_mask(df, **kw)
    return int(m.sum()) if len(m) else 0


# ── 라운드 224 — 보유 관리가 읽는 두 가지 (표시 전용 · 문턱 없음) ─────────
#
# ① 봉 → 달력일. 위 MIN_GAP_DAYS 와 같은 환산(×7/5)이다. 보유 계획의 창은
#    엔진의 결과 창 `horizon_days`(20봉)이고, 화면은 날짜열만 가지므로 달력일로
#    옮긴다 — 새 숫자가 아니다.
# ② 적정가 도달 비율. 사용자: *"적정가는 [있는데] 너무 오래 기다려야 한다."*
#    적정가까지 걸리는 시간은 이 원장이 못 잰다(옛 행에 적정가가 없다 · R215).
#    잴 수 있는 것은 하나 — **같은 국면·같은 구역의 원장 케이스가 20봉 안에
#    그만큼(적정가까지의 상승 여력) 오른 비율**이다. `close_return_pct` 는 창 끝
#    종가 수익(손절·목표로 잘리지 않은 값)이라 mfe 의 함정(청산 봉까지만 잰다)
#    이 없다. 분모가 0 이면 None — 비율을 만들지 않는다(§3). 어디까지가 '낮다'
#    인지는 정하지 않는다 — 문턱을 고르면 §2 다. 수와 n 을 그대로 낸다.
HORIZON_BARS = 20                              # 엔진 결과 창 (horizon_days)


def bars_to_days(bars):
    """봉 수 → 달력일 (×7/5 · MIN_GAP_DAYS 와 같은 환산). 20봉 = 28일."""
    return int(bars) * 7 // 5


def reach_table(records, regime_key='regime', zone_key='entry_zone',
                ret_key='close_return_pct'):
    """{(국면, 구역): 오름차순 창 끝 종가 수익 리스트}. `records` 는 dict 의 반복자
    (원장 jsonl 한 줄씩) 또는 DataFrame — 둘 다 같은 표를 만든다.
    화면이 원장 전체를 다시 들지 않게 세 칸만 남긴 작은 표다."""
    out = {}
    try:
        import pandas as pd
        if isinstance(records, pd.DataFrame):
            records = records[[regime_key, zone_key, ret_key]].to_dict('records')
    except Exception:                                          # noqa: BLE001
        pass
    for r in records:
        rg, zn, rt = r.get(regime_key), r.get(zone_key), r.get(ret_key)
        if not rg or not zn or rt is None:
            continue
        try:
            rt = float(rt)
        except (TypeError, ValueError):
            continue
        if rt != rt:                                           # NaN
            continue
        out.setdefault((str(rg), str(zn)), []).append(rt)
    for k in out:
        out[k].sort()
    return out


def reach_share(table, regime, zone, upside_pct):
    """(비율 %, n) — 같은 (국면, 구역) 케이스 중 창 끝 종가 수익 ≥ upside_pct 인 비율.

    upside_pct ≤ 0 이면 '이미 적정가 위' 라 비율의 뜻이 없다 → None.
    n == 0 이면 None — 분모가 0 이면 비율을 만들지 않는다(§3). 문턱 없음.
    """
    try:
        up = float(upside_pct)
    except (TypeError, ValueError):
        return None
    if not table or up <= 0 or not regime or not zone:
        return None
    rets = table.get((str(regime), str(zone)))
    if not rets:
        return None
    n = len(rets)
    k = n - bisect.bisect_left(rets, up)
    return round(100.0 * k / n, 1), n


def reach_line(share, n, upside_pct, regime=None, zone=None, bars=HORIZON_BARS):
    """화면 한 줄 — 숫자를 판단으로 바꾸지 않는다. 예:
    '적정가까지 +38.2% · 같은 국면·구역 원장 1,204건 중 20봉 안에 그만큼 오른 비율 3.1%'"""
    where = ''
    if regime or zone:
        where = f"({regime or '?'} · {zone or '?'}) "
    return (f"적정가까지 {float(upside_pct):+.1f}% · 같은 국면·구역 {where}원장 {int(n):,}건 중 "
            f"{int(bars)}봉 안에 그만큼 오른 비율 {float(share):.1f}%")
