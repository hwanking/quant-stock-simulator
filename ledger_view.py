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

#: 원장 집계표(calibration.json)의 '비용 차감 평균수익'이 빼는 왕복 비용(%) — 라운드 386.
#:   집계 랩(`scripts/calibration_lab.py`)이 2026-08 부터 **보수적 추정 0.55** 로 빼 왔고(라운드 195 의 §55
#:   계약값과 같다), 중앙 판정의 운영 비용은 `verdict_core.COST_PCT`(오늘 0.41 · 라운드 350)다. 두 수가 한
#:   사이트에 '비용 차감'이라는 같은 이름으로 나가므로(외부 검토 · 2026-09-29) 화면이 **어느 비용인지**를
#:   같이 적는다. 수는 바꾸지 않았다 — 바꾸면 그동안 발표한 표가 전부 움직인다(R255 · 각 라운드 재현용).
#:   랩과 화면이 이 한 곳을 읽는다(§4).
CALIB_COST_PCT = 0.55

#: 라운드 389 — 원장 진입가가 그날 봉 종가와 어긋난 행의 목록을 담는 산출물(라운드 365 가 배선).
SCALE_AUDIT_FILE = 'entry_scale_audit.json'

#: 라운드 390 — '같은 값인가'를 보는 허용 오차(배율 1 에서 1%). 라운드 365 감사가 쓰던 그 수이고 새로 고른 값이
#:   아니다 — 정상 종목은 배율이 정확히 1.0000, 어긋난 종목은 1.5% 이상이었다(R364 실측). 감사와 채점이 **같은
#:   판정**을 쓰도록 여기 한 곳에 둔다(§4).
SCALE_EPS = 0.01


def entry_scale_off(price, bar_close, eps=SCALE_EPS):
    """원장 진입가가 그날 봉 종가와 **다른 축척**인가 (라운드 390 · 항등식 · 문턱 없음).

    True = 어긋남 · False = 같음 · None = 댈 수 없음(봉 없음·값 못 읽음 — '같다'로 세지 않는다 · §3).
    채점하는 자리(`calibration_lab`)가 **그때 쓰는 봉으로** 이것을 불러 행에 도장(`entry_scale_off`)을 찍는다 —
    감사 산출물을 다음 실행에 읽는 방식(R389)은 하루 늦고 클라우드 복원이 덮어쓴다(R389 결과 문서)."""
    try:
        p, b = float(price), float(bar_close)
    except (TypeError, ValueError):
        return None
    if not (p > 0 and b > 0) or p != p or b != b:
        return None
    return abs(b / p - 1.0) > eps


def scale_mismatch_keys():
    """진입가 축척이 어긋난 원장 행 → {(종목코드 6자리, 기준일)} (라운드 389).

    라운드 364 가 찾은 결함이다 — 그 행들은 진입가가 그날 봉과 5~10배(또는 0.2배) 어긋나 채점이
    1봉째에 박힌다(지어낸 승리·패배). 원장 행은 **지우지 않는다**(R197) — 통계에서만 뺀다.
    판별식은 `scripts/entry_scale_audit.py` 의 항등식(`진입가 == 그날 봉 종가`)이고 문턱이 없다.
    운영 보정표(`calibration_lab`)와 화면 통계가 **이 하나**를 읽는다(§4).
    못 읽으면(산출물 없음 · 옛 판이라 행 목록이 없음) None — 그때는 거르지 않고 그 사실을 적는다(§3).
    """
    try:
        import artifact_io
        doc = artifact_io.load_json(SCALE_AUDIT_FILE)
    except Exception:                                          # noqa: BLE001
        return None
    keys = (doc or {}).get('offender_keys')
    if not isinstance(keys, dict):
        return None
    out = set()
    for code, days in keys.items():
        for d in days or ():
            out.add(scale_key(code, d))
    return out


def code6(ticker):
    """종목코드 6자리 — 시장 접미사(.KS/.KQ)를 뗀다. 같은 종목의 **정체**는 이것이다(접미사는 도장 · R222 의 모양)."""
    return str(ticker or '').split('.')[0]


def scale_key(ticker, date):
    """(종목코드 6자리, 기준일) — 감사 목록과 원장 행을 같은 모양으로 맞춘다(시장 접미사를 뗀다)."""
    return (code6(ticker), str(date or '')[:10])


def stat_rows(rows, keys=None, counter=None):
    """통계에 쓰는 원장 행만 흘린다 (라운드 390 · 한 곳 · §4).

    빼는 것 둘 — 행은 원장에 그대로 두고(R197) **셈에서만** 뺀다:
      ① 진입가 축척이 어긋난 행(`is_scale_mismatch` · 도장 또는 감사 목록 · R364·R389·R390)
      ② 같은 (종목 6자리, 기준일)의 **두 번째 행부터** — 2026-09-29 실측: 원장 2,499쌍(25종목)이 시장 접미사만
         다르게(.KS/.KQ) 두 번 들어가 있었고 **2,499/2,499 가 진입가·결과까지 같은 복사본**이었다. 완료 판정이
         접미사까지 든 열쇠로 물어 접미사가 바뀐 종목을 새 케이스로 봤다(R222 의 '열쇠에 바뀌는 것이 들면 옛 것이
         매번 새 것'). 먼저 나온 행을 쓴다.
    `counter`(dict)가 있으면 'scale'·'dup' 에 뺀 수를 센다."""
    seen = set()
    for r in rows:
        if is_scale_mismatch(r, keys):
            if counter is not None:
                counter['scale'] = counter.get('scale', 0) + 1
            continue
        k = scale_key((r or {}).get('ticker'), (r or {}).get('date'))
        if k in seen:
            if counter is not None:
                counter['dup'] = counter.get('dup', 0) + 1
            continue
        seen.add(k)
        yield r


def is_scale_mismatch(row, keys):
    """원장 한 행이 진입가 축척이 어긋난 행인가 — 행의 도장(`entry_scale_off` · 라운드 390 · 채점 자리에서 찍음)
    **또는** 감사 목록(`scale_mismatch_keys()` · 라운드 389). 둘 다 같은 항등식이고, 도장은 하루 늦지 않는다.
    둘 다 없으면 False(거를 근거가 없다)."""
    if (row or {}).get('entry_scale_off') is True:
        return True
    if not keys:
        return False
    return scale_key((row or {}).get('ticker'), (row or {}).get('date')) in keys


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


def unblock_date(sorted_dates, d, min_gap_days=MIN_GAP_DAYS):
    """`d` 가 `too_close` 로 막혔을 때, **기준일이 언제가 되어야 열리는지**.

    막은 것은 `d` 바로 앞의 케이스다(뒤엣것은 `d` 보다 미래라 후보가 나아가면
    멀어지지 않는다). 그 케이스 + `min_gap_days` 가 답이다 — 같은 규칙을
    거꾸로 읽은 것뿐이고 **새 숫자가 아니다.** 안 막혔으면 None.

    ⚠️ 이것은 **기준일**이지 달력 날짜가 아니다. 후보 기준일은 마지막 봉에서
    20봉 뒤에 서므로(`make_asof_dates`) 실제로 그 날이 오는 것은 더 나중이고,
    후보는 거래일로 나아가는데 이 값은 달력일이라 **환산하지 않는다** —
    환산하면 그 순간 손으로 고른 수가 된다 (§2 · R307 이 그렇게 틀렸다).
    """
    if not sorted_dates or not too_close(sorted_dates, d, min_gap_days):
        return None
    d = str(d)[:10]
    i = bisect.bisect_left(sorted_dates, d)
    prev = sorted_dates[i - 1] if i - 1 >= 0 else None
    if prev is None:
        return None
    return (_day(prev) + _dt.timedelta(days=int(min_gap_days))).isoformat()


def split_open_by_frontier(per_stock, newest):
    """종목별 '가장 이른 열리는 기준일'을 **시장 격자 끝에 선 종목**과 **뒤처진 종목**으로 가른다.

    `per_stock`: [(그 종목 격자 끝 기준일, 그 종목의 가장 이른 열리는 기준일), ...]
    `newest`   : 이번에 만든 후보 중 가장 최신 기준일(시장 격자 끝).
    반환: {'front': (최소 또는 None, 종목 수), 'lag': (최소 또는 None, 종목 수)}

    ■ 왜 가르는가 (라운드 379 · 2026-09-29)
      09-28 실행이 *"가장 이른 것은 기준일이 2026-05-08 이 되어야 열린다 (이번 최신 후보
      2026-08-26)"* 를 찍었다 — 열릴 날이 최신 후보보다 **앞**이라 읽는 사람에게는 이미
      열렸어야 하는 날로 보인다. 그 값을 낸 종목은 마지막 봉이 09-28 인데 격자 끝이
      **04-07** 이었다(최근 봉 사이가 비어 20봉 앞이 4월로 간다). 그 종목의 후보는 **자기
      봉**으로 나아가므로 거짓은 아니지만, 시장 격자 끝에 선 573종목의 답(**09-14**)과 한
      줄에 섞으면 원장이 언제 자라는지를 말하지 못한다. 규칙·문턱 불변 — 세는 대상을
      격자 끝으로 가를 뿐이고 가르는 기준은 '같은 날인가' 하나다(새 숫자 없음).
    """
    front, lag = [], []
    for stock_newest, ub in per_stock:
        if not ub:
            continue
        (front if stock_newest == newest else lag).append(ub)
    return {'front': (min(front) if front else None, len(front)),
            'lag': (min(lag) if lag else None, len(lag))}


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


def ledger_regime(price, sma20, sma60):
    """원장(국면 표)이 쓰는 시장 국면 규칙 — 'BULL'·'BEAR'·'SIDEWAYS', 못 정하면 None (라운드 421 · 한 곳).

    현재가 > 20일선 > 60일선 → 상승 · 현재가가 20일선과 60일선 **둘 다** 아래 → 하락 · 그 밖 → 옆걸음.
    랩(`calibration_lab.regime_at`)이 원장 행마다 이 규칙으로 국면을 붙였고 화면의 국면 표가 그 행을 센다. 종전엔
    화면의 '지금은 ○○ 국면' 카드가 **다른 규칙**(60일선 아래면 하락 · 20일선 위면 상승)을 써서, 같은 날을 표와 다른
    줄로 가리킬 수 있었다(현재가가 20일선 위·60일선 아래면 카드는 하락, 표는 옆걸음). 새 숫자 없음 — 랩 규칙 그대로."""
    try:
        p, s20, s60 = float(price), float(sma20), float(sma60)
    except (TypeError, ValueError):
        return None
    if not (p > 0 and s20 > 0 and s60 > 0):
        return None
    if p > s20 > s60:
        return 'BULL'
    if p < s20 and p < s60:
        return 'BEAR'
    return 'SIDEWAYS'


def engine_live_regime(price, sma20, sma60):
    """엔진의 실시간 국면 게이트(`quant_indicators.classify_market_regime` → `_RP_MAP`)가 쓰는 갈래를 같은 이름으로
    옮긴다 — 화면이 두 규칙이 **갈리는 날**을 알아보게 하려는 것뿐이다(엔진은 이 함수를 안 부른다 · 판정 불변).

    엔진: 현재가 ≥ 20일선 ≥ 60일선 → 강한 상승 · 현재가 ≥ 20일선 → 완만한 상승(둘 다 'BULL') · 둘 다 아래 → 하락 ·
    그 밖 → 옆걸음. 원장 규칙과 갈리는 것은 '현재가 ≥ 20일선인데 20일선 < 60일선'(반등 초입)이다 — 엔진은 상승,
    원장은 옆걸음. 회귀가 엔진 소스의 갈래 식과 이 함수를 같이 잠근다."""
    try:
        p, s20, s60 = float(price), float(sma20), float(sma60)
    except (TypeError, ValueError):
        return None
    if not (p > 0 and s20 > 0 and s60 > 0):
        return None
    if p >= s20:
        return 'BULL'
    if p < s20 and p < s60:
        return 'BEAR'
    return 'SIDEWAYS'


FAIR_ZONE_FILE = 'fair_zone_regime_r419.json'


def fair_zone_line(doc):
    """'적정가 여력은 살 근거가 아니다' 한 줄 — 사전등록 R419 의 산출물에서 읽는다(손으로 적은 수는 낡는다 · R285).

    사용자(2026-10-03): *"적정가 다 좋다고 하지 말고 진짜 좋은 것만 시장 상황이랑 해서."* R419 가 원장 매수권에서 '적정가 아래'
    구역을 국면별로 쟀다. 판정이 (다)일 때 화면이 그 사실을 같은 자리에 적는다(사전등록의 갈래 그대로). 산출물이 없거나 측정된
    국면이 없으면 빈 글자(지어내지 않는다 · §3). 문턱 없음 — 수와 갈래만."""
    regs = (doc or {}).get('regimes') or {}
    meas = {k: v for k, v in regs.items() if v.get('verdict') not in (None, '미측정')}
    if not meas:
        return ''
    ko = {'BULL': '상승장', 'SIDEWAYS': '옆걸음', 'BEAR': '하락장'}
    sp_ko = (('train', '학습'), ('valid', '검증'), ('blind', '실전'))
    parts = []
    for rg, v in meas.items():
        r1 = v.get('r1') or {}
        means = ' · '.join(f"{nm} {float(r1[sp]['mean']):+.2f}%" for sp, nm in sp_ko if (r1.get(sp) or {}).get('mean') is not None)
        r0 = v.get('r0') or {}
        shares = [r0[sp]['rows'] / (r0[sp]['rows'] + r0[sp]['rest_rows']) * 100
                  for sp, _nm in sp_ko if r0.get(sp) and (r0[sp]['rows'] + r0[sp]['rest_rows'])]
        verdict = v.get('verdict')
        tail = ('그 밖보다 낫지 않았습니다' if verdict == '다' else
                '그 밖보다 나았지만 비용을 넘지는 못했습니다' if verdict == '나' else '비용을 넘었습니다')
        parts.append(f"{ko.get(rg, rg)}에서 비용 {doc.get('cost')}% 뺀 평균 {means} — {tail}"
                     + (f"(이 국면 매수권의 {min(shares):.0f}~{max(shares):.0f}% 가 '적정가 아래'로 나와 가르는 힘이 약합니다)"
                        if shares else ''))
    miss = [ko.get(k, k) for k, v in regs.items() if v.get('verdict') == '미측정']
    lead = ("적정가가 현재가보다 높아도 그것만으로는 살 근거가 아닙니다"
            if all(v.get('verdict') == '다' for v in meas.values()) else "적정가 아래 구역의 원장 성적")
    return (f"{lead} — 원장 매수권({doc.get('score_floor')}점+)의 '적정가 아래' 구역은 " + ' / '.join(parts)
            + (f". {'·'.join(miss)}은 날짜가 모자라 못 쟀습니다" if miss else '')
            + f" ({doc.get('made') or '측정일 미상'} 측정 · 같은 날 판정은 함께 움직여 날짜로 묶어 셌습니다).")


def reach_line(share, n, upside_pct, regime=None, zone=None, bars=HORIZON_BARS):
    """화면 한 줄 — 숫자를 판단으로 바꾸지 않는다. 예:
    '적정가까지 +38.2% · 같은 국면·구역 원장 1,204건 중 20봉 안에 그만큼 오른 비율 3.1%'"""
    where = ''
    if regime or zone:
        where = f"({regime or '?'} · {zone or '?'}) "
    return (f"적정가까지 {float(upside_pct):+.1f}% · 같은 국면·구역 {where}원장 {int(n):,}건 중 "
            f"{int(bars)}봉 안에 그만큼 오른 비율 {float(share):.1f}%")


_REACH_RE = None


def parse_reach_line(text):
    """`reach_line` 이 만든 한 줄을 다시 읽는다 — {upside, n, bars, share} 또는 None.
    쓰는 쪽과 읽는 쪽이 같은 모듈에 있어야 형식이 바뀌어도 한 곳만 고친다 (§4)."""
    global _REACH_RE
    import re
    if _REACH_RE is None:
        _REACH_RE = re.compile(
            r'적정가까지 ([+\-−]?[\d.]+)% .*?원장 ([\d,]+)건 중 (\d+)봉 안에 그만큼 오른 비율 ([\d.]+)%')
    m = _REACH_RE.search(str(text or ''))
    if not m:
        return None
    try:
        return dict(upside=float(m.group(1).replace('−', '-')), n=int(m.group(2).replace(',', '')),
                    bars=int(m.group(3)), share=float(m.group(4)))
    except ValueError:
        return None


def touch_cdf(records, bars=HORIZON_BARS):
    """{'n': 전체 케이스, 'cum': {봉: 그 봉째까지 두 선(손절·목표) 중 하나에 닿은 누적 비율 %}}.
    사용자: "다 보유 유지인데 맞아?" — 계획 n봉째에 아무 선에도 안 닿은 것이 얼마나 흔한지
    원장이 답한다(R230 · 표시 전용 · 문턱 없음). `records` 는 dict 반복자 또는 DataFrame.
    분모가 0 이면 None."""
    try:
        import pandas as pd
        if isinstance(records, pd.DataFrame):
            records = records[['touched_bar', 'outcome']].to_dict('records')
    except Exception:                                          # noqa: BLE001
        pass
    n = 0
    hit = {}
    for r in records:
        n += 1
        if r.get('outcome') not in ('TARGET', 'STOP'):
            continue
        try:
            b = int(r.get('touched_bar'))
        except (TypeError, ValueError):
            continue
        if b >= 1:
            hit[b] = hit.get(b, 0) + 1
    if n == 0:
        return None
    cum, acc = {}, 0
    for b in range(1, int(bars) + 1):
        acc += hit.get(b, 0)
        cum[b] = round(100.0 * acc / n, 1)
    return {'n': n, 'cum': cum}


#: 매수권 하한 — 이 저장소가 이미 쓰는 값(원장 요약·감시가 같은 58 을 쓴다). 새 숫자 아님.
BUY_ZONE_SCORE = 58

#: DeMARK 카운트다운 계산을 고친 날(라운드 386 · `quant_indicators.td_countdown`). 원장의 `demark_state`
#: 는 그 행을 만든 날의 계산으로 찍혔으므로, 이 날 앞의 행과 뒤의 행은 13 의 정의가 다르다.
DEMARK_DEF_CHANGED = '2026-09-29'


def demark_complete_lift(records, min_score=BUY_ZONE_SCORE):
    """차트의 '13 매수' 표식이 원장에서 무엇을 했나 — 구간별 (라운드 285 · 표시 전용).

    사용자: *"삼성전자 13매수 나왔는데 사야 하는 거 맞아?"* 차트는 그 표식을 크게 그리면서
    **얼마짜리인지 한 줄도 안 적고 있었다** — 숫자만 보여 주면 그게 판단이 된다(R223).

    가르는 값은 엔진이 이미 원장에 찍는 `demark_state == 'COMPLETE'`(= 매수 카운트다운 13
    완성 · `quant_indicators` 의 `buy_cd >= 13` 가지)다. **새 문턱을 만들지 않는다** —
    매수권 하한도 이미 쓰는 58 을 그대로 쓴다.

    돌려주는 것: {split: {'yes': (n, 적중%, 날짜수), 'no': (...), 'diff': %p}} · 판정은 안 한다.
    분모가 0 인 칸은 담지 않는다(§3 — 비율을 만들지 않는다).
    """
    box = {}
    for r in records:
        sp = r.get('split')
        ok = r.get('success')
        if sp not in ('train', 'valid', 'blind') or ok is None:
            continue
        try:
            if float(r.get('score') or 0) < float(min_score):
                continue
        except (TypeError, ValueError):
            continue
        key = (sp, str(r.get('demark_state')) == 'COMPLETE')
        cell = box.setdefault(key, [0, 0, set()])
        cell[0] += 1
        cell[1] += 1 if ok else 0
        cell[2].add(str(r.get('date'))[:10])
    out = {}
    for sp in ('train', 'valid', 'blind'):
        y, n = box.get((sp, True)), box.get((sp, False))
        if not y or not n or not y[0] or not n[0]:
            continue
        y_rate = 100.0 * y[1] / y[0]
        n_rate = 100.0 * n[1] / n[0]
        out[sp] = {'yes': (y[0], round(y_rate, 1), len(y[2])),
                   'no': (n[0], round(n_rate, 1), len(n[2])),
                   'diff': round(y_rate - n_rate, 1)}
    return out or None


def demark_lift_line(lift):
    """위 결과 → 화면 한 줄. 없으면 None (지어내지 않는다).

    **판정을 대신 내리지 않는다** — 세 구간 부호가 갈리는지만 사실로 적는다(R44·R213 의
    그 규칙). 부호가 같아도 '사라'가 되지 않게 문장은 그대로 둔다.
    """
    if not lift:
        return None
    seen = [lift[s]['diff'] for s in ('train', 'valid', 'blind') if s in lift]
    if not seen:
        return None
    parts = []
    for sp, label in (('train', '학습'), ('valid', '검증'), ('blind', '실전')):
        if sp in lift:
            d = lift[sp]
            parts.append(f"{label} {d['diff']:+.1f}%p(n {d['yes'][0]}·날짜 {d['yes'][2]})")
    mixed = not (all(v > 0 for v in seen) or all(v < 0 for v in seen))
    tail = ('세 구간의 방향이 서로 어긋나 근거로 쓰지 않습니다'
            if mixed else '방향은 같지만 이 표식만으로 판단하지 않습니다')
    return ('차트의 13 매수·매도 표식은 **판정에 들어가지 않습니다** — 원장에서 '
            '매수권 안 13 완성과 그 외의 적중 차이를 재면 ' + ' · '.join(parts)
            + f'. {tail}. '
            # 라운드 386 — 카운트다운 계산을 고쳤다(셋업 9 가 이어지는 동안 매 봉 0 으로 돌아가던 결함). 원장 행
            #   대부분은 그 전 계산으로 찍힌 13 이라, 지금 차트의 13 과 **같은 정의가 아니다** — 말하지 않으면
            #   이 수가 지금 표식의 값어치로 읽힌다(§3).
            + f'원장 행 대부분은 {DEMARK_DEF_CHANGED} 전 카운트다운 계산으로 찍힌 13 이라, 지금 차트의 13 과 '
              '같은 정의가 아닙니다.')


# ── 선에 닿은 뒤 판 것 vs 든 것 (라운드 340 · 표시 전용) ─────────────────────
#   사용자: *"(보유 종목 하나) 진짜 팔어? 면밀히 검토해줘."* 화면은 '매도 — 손절선 아래' 라고만 적고 그 선을 넘어 파는
#   것이 원장에서 무엇을 했는지는 안 적었다(R285 의 '값어치 없는 표식'과 같은 자리). 채점기는 두 값을 다
#   남긴다 — `return_pct`(선에 닿아 판 수익률)와 `close_return_pct`(창 끝 종가 수익률 · R296). 그 둘을
#   구간별로 **세기만** 한다. 새 문턱 없음 · 판정 없음 — 부호가 갈리면 갈린다고 적는다(R44·R213).
EXIT_TAIL_PCT = {'STOP': -10.0, 'TARGET': 0.0}   # '꼬리' 문장의 기준 — 손절은 −10% 아래, 목표는 마이너스 종료


def exit_vs_hold(records, outcome):
    """{split: {'n', 'exit_mean', 'hold_mean', 'exit_med', 'hold_med', 'hold_better_pct', 'diff_mean',
    'diff_med', 'tail_pct'}} · 분모 0 인 구간은 담지 않는다 · 하나도 없으면 None."""
    box = {}
    for r in records:
        if r.get('outcome') != outcome:
            continue
        sp = r.get('split')
        if sp not in ('train', 'valid', 'blind'):
            continue
        try:
            ex, hd = float(r.get('return_pct')), float(r.get('close_return_pct'))
        except (TypeError, ValueError):
            continue
        box.setdefault(sp, []).append((ex, hd))
    out = {}
    tail = EXIT_TAIL_PCT.get(outcome, 0.0)
    for sp, pairs in box.items():
        if not pairs:
            continue
        exs = sorted(p[0] for p in pairs)
        hds = sorted(p[1] for p in pairs)
        diffs = sorted(p[1] - p[0] for p in pairs)
        n = len(pairs)
        mid = lambda a: a[n // 2] if n % 2 else (a[n // 2 - 1] + a[n // 2]) / 2.0     # noqa: E731
        out[sp] = {
            'n': n,
            'exit_mean': round(sum(exs) / n, 2), 'hold_mean': round(sum(hds) / n, 2),
            'exit_med': round(mid(exs), 2), 'hold_med': round(mid(hds), 2),
            'hold_better_pct': round(100.0 * sum(1 for d in diffs if d > 0) / n, 1),
            'diff_mean': round(sum(diffs) / n, 2), 'diff_med': round(mid(diffs), 2),
            'tail_pct': round(100.0 * sum(1 for h in hds if h < tail) / n, 1),
        }
    return out or None


def exit_vs_hold_line(res, outcome):
    """위 결과 → 화면 한 줄. 없으면 None. **판정을 대신 내리지 않는다** — 세 구간 부호가 갈리면 그 사실만."""
    if not res:
        return None
    what = '손절선' if outcome == 'STOP' else '1차 목표'
    seen = [res[s]['diff_med'] for s in ('train', 'valid', 'blind') if s in res]
    if not seen:
        return None
    parts = []
    for sp, label in (('train', '학습'), ('valid', '검증'), ('blind', '실전')):
        if sp in res:
            d = res[sp]
            parts.append(f"{label} {d['hold_better_pct']:.0f}%(n {d['n']:,})")
    mixed = not (all(v > 0 for v in seen) or all(v < 0 for v in seen))
    tail_txt = ('' if 'blind' not in res else
                (f" · 실전에서 안 팔고 들었을 때 {'−10% 아래로' if outcome == 'STOP' else '마이너스로'} 끝난 비율 "
                 f"{res['blind']['tail_pct']:.0f}%"))
    tail = ('구간마다 방향이 갈려 어느 쪽이 낫다고 말하지 않습니다'
            if mixed else '방향은 같지만 이것만으로 팔지 말지를 정하지 않습니다')
    return (f"원장에서 {what}에 닿은 뒤 **안 팔고 창 끝까지 든 쪽이 더 나았던 비율**: " + ' · '.join(parts)
            + f"{tail_txt}. {tail}.")


def days_to_bars(days):
    """달력일 → 봉 수 (×5/7 · bars_to_days 의 역). 0 미만은 0."""
    try:
        return max(0, int(days) * 5 // 7)
    except (TypeError, ValueError):
        return 0


# ── 손절 폭 좁히기의 대가 (라운드 293) ─────────────────────────────────
#   사용자가 2026-09-15 에 *"노출해줘, 대가 같이 적고"* 로 골랐다. 그 대가를 **손으로
#   적지 않는다** — 라운드 21 사전등록이 만들고 라운드 258 이 지금 원장으로 다시 채운
#   산출물(`.portfolio/loss_control_r21.json`)을 읽어 그 자리에서 문장으로 만든다
#   (손으로 적은 수는 낡는다 · R285 와 같은 자리). 못 읽으면 None — 지어내지 않는다(§3).
def stop_tighten_cost(art, mult):
    """{split: {'reach_delta','ev_delta','avg_loss_delta','worst_delta','n'}} 또는 None.

    art: loss_control_r21.json 을 읽은 dict · mult: 견줄 배수(예: 0.6).
    기준선은 같은 표의 **1.0** 이다 — 다른 데서 가져오지 않는다(§4).
    """
    tbl = (art or {}).get('table') or {}
    key, base = f'{float(mult):g}', '1'
    out = {}
    for sp, row in tbl.items():
        if not isinstance(row, dict):
            continue
        a = row.get(key) or row.get(f'{float(mult):.1f}')
        b = row.get(base) or row.get('1.0')
        if not (isinstance(a, dict) and isinstance(b, dict)):
            continue
        try:
            out[sp] = {
                'n': a.get('n'),
                'reach_delta': float(a['reach']) - float(b['reach']),
                'ev_delta': float(a['ev']) - float(b['ev']),
                'avg_loss_delta': float(a['avg_loss']) - float(b['avg_loss']),
                'worst_delta': float(a['worst']) - float(b['worst']),
            }
        except (KeyError, TypeError, ValueError):
            continue
    return out or None


def stop_tighten_cost_line(cost, mult):
    """대가 한 줄 — **좋은 쪽만 쓰지 않는다**(§9). 줄어드는 손실과 잃는 도달률을
    같은 문장에 넣고, 구간별로 적는다. 못 세면 그 사실을 돌려준다(§3)."""
    if not cost:
        return ('손절을 좁혔을 때의 대가를 지금 셀 수 없습니다 — 실측 산출물을 '
                '읽지 못했습니다. 켜기 전에 대가를 확인할 수 없으므로 '
                '권하지 않습니다.')
    parts = []
    for sp, label in (('train', '학습'), ('valid', '검증'), ('blind', '실전')):
        d = cost.get(sp)
        if not d:
            continue
        # 평균 손실은 **음수**다 — 차이가 양수면 손실 폭이 *줄어든 것*이다.
        #   `+1.98%p` 로 적으면 손실이 **늘어난 것처럼** 읽힌다(§9 는 좋은 쪽만
        #   쓰지 말라는 규칙이지, 나쁜 쪽으로 읽히게 쓰라는 규칙이 아니다).
        _al = d['avg_loss_delta']
        _alw = (f"평균 손실 폭 {abs(_al):.2f}%p {'축소' if _al > 0 else '확대'}"
                if _al else "평균 손실 폭 그대로")
        parts.append(f"{label} 목표도달률 {d['reach_delta']:+.1f}%p · "
                     f"{_alw}(n {d['n']:,})")
    if not parts:
        return ('손절을 좁혔을 때의 대가를 구간별로 세지 못했습니다 — 산출물에 '
                '견줄 칸이 없습니다.')
    return (f'손절 폭을 {float(mult):g}배로 좁히면 **손실은 줄고 목표도달률은 '
            f'떨어집니다** — ' + ' · '.join(parts)
            + '. 이것은 **개선이 아니라 맞바꿈**입니다. 기본값으로는 사전등록 기준'
              '(기대값 · 도달률 −5%p 이내)을 세 구간 모두에서 통과하지 못해 '
              '기각된 값이고, 판정·점수·추천에는 들어가지 않습니다.')


def outcome_quantiles(table, regime, zone):
    """같은 (국면, 구역) 원장 사례의 **창 끝 수익 분위**. 없으면 None (§3 · 분모 0 금지).

    ■ 왜 (라운드 296 · 사용자: *"그래프 고쳐줘 원장으로 재서"*)
      경로 그래프가 **유사패턴 6건**으로 10~90분위 밴드를 그리고 있었다. 엔진 자신은
      10건 미만이면 확률로 환산하지 않는데(§11), 그 표본으로 **분포를 그리고** 있었다.
      실측(2026-09-15 · 매수권 109,083행): 같은 (국면, 구역) 칸은 **중앙 n=1,689 ·
      최대 30,415** 건이다. 6건이 아니라 수천~수만 건이 같은 자리를 말한다.
      그리고 6건 밴드는 상단을 부풀렸다 — 6건 25~75분위가 −2.5~**+16.7%** 인데
      원장 같은 칸은 −3.8~**+3.4%** 였다.

    새 문턱을 만들지 않는다 — 분위만 읽어 돌려주고, **n 은 화면이 같이 적는다.**
    표는 `reach_table` 이 만든 것을 그대로 쓴다(§4 — 원장을 두 번 훑지 않는다).
    """
    if not table or not regime or not zone:
        return None
    rets = table.get((str(regime), str(zone)))
    if not rets:
        return None
    n = len(rets)

    def _q(p):
        return rets[min(n - 1, max(0, int(round(p * (n - 1)))))]

    return {'n': n, 'p10': _q(.10), 'p25': _q(.25), 'p50': _q(.50),
            'p75': _q(.75), 'p90': _q(.90)}


def outcome_band_line(q, bars=HORIZON_BARS):
    """화면 한 줄 — **판단을 대신 내리지 않는다.** 원장이 말하는 것만 적는다."""
    if not q:
        return None
    return (f"같은 국면·구역 원장 **{q['n']:,}건**의 {bars}봉 뒤 결과: "
            f"가운데 절반이 **{q['p25']:+.1f}% ~ {q['p75']:+.1f}%** "
            f"(중앙 {q['p50']:+.1f}% · 10~90분위 {q['p10']:+.1f}~{q['p90']:+.1f}%). "
            f"위 경로 그래프의 밴드는 **유사패턴 몇 건**으로 그린 것이라 이것과 다릅니다 "
            # 라운드 405 — 종전 꼬리 *"표본이 큰 쪽은 이 줄"* 은 **더 믿으라**로 읽혔다. 이 줄은 표본이 크지만 이 종목의
            #   모양이 아니라 같은 국면·구역 **전체**의 기준선이고, 원장 행은 서로 겹쳐(R217) 행 수만큼 독립도 아니다.
            #   큰 것과 이 종목에 맞는 것은 다른 말이다(외부 검토 · 2026-10-01).
            f"— 표본은 이 줄이 훨씬 크지만, 이 종목의 모양이 아니라 같은 국면·구역 전체의 기준선입니다.")


# ── 라운드 346 — '손절은 지키고 1차 목표에서 안 판' 경우 (표시 전용) ──────────────────────
#   사전등록(docs/PREREG_R346_NO_TARGET_KEEP_STOP.md)대로 일봉 경로로 쟀고 판정은 (나) — 학습·검증은 평균 CI 가 0 을
#   제외하지만 블라인드가 0 을 포함해 **규칙은 안 바꿨다.** 그래도 '일부 매도' 판정 앞에 선 보유자에게는 그 수가
#   쓸모 있는 사실이라 같은 자리에 적는다(R285·R340). 수는 산출물에서 읽고 판정을 대신 내리지 않는다.
def no_target_line(art):
    """data/exit_rule_r346.json(dict) → 화면 한 줄. 모양이 다르면 None(지어내지 않는다 · §3).
    물결표를 쓰지 않는다 — 캡션은 마크다운이라 둘이 만나면 취소선이 된다(R295·R337)."""
    sp = (art or {}).get('splits') or {}
    need = ('diff_mean', 'ci95', 'cand_better_pct', 'cand_worse_pct', 'target_then_stop_pct')
    if any(k not in sp or any(sp[k].get(f) is None for f in need) for k in ('train', 'valid', 'blind')):
        return None
    parts = []
    for k, ko in (('train', '학습'), ('valid', '검증'), ('blind', '실전')):
        lo, hi = sp[k]['ci95']
        parts.append(f"{ko} {sp[k]['diff_mean']:+.2f}%p" + ('' if (lo > 0 or hi < 0) else '(오차 범위에 0 포함)'))
    better = [sp[k]['cand_better_pct'] for k in ('train', 'valid', 'blind')]
    worse = [sp[k]['cand_worse_pct'] for k in ('train', 'valid', 'blind')]
    back = [sp[k]['target_then_stop_pct'] for k in ('train', 'valid', 'blind')]
    n = ((art or {}).get('counts') or {}).get('spaced')
    passed = str((art or {}).get('verdict') or '').startswith('(가)')
    tail = ('미리 정한 기준(세 구간 모두)을 넘었지만 독립 확인 전이라 규칙은 아직 바꾸지 않았습니다'
            if passed else '미리 정한 기준(세 구간 모두 통과)을 못 넘어 규칙은 바꾸지 않았습니다')
    return (f"같은 자리에서 **손절선은 지키고 1차 목표에서는 안 판** 경우를 일봉 경로로 다시 재면"
            f"({art.get('made')}" + (f" · 매수권 {int(n):,}건 · 같은 종목 35일 간격" if n else '') + "): "
            f"평균 차이 {' · '.join(parts)}. 다만 그쪽이 더 나았던 경우는 {min(better):.0f}%에서 {max(better):.0f}%, "
            f"더 나빴던 경우는 {min(worse):.0f}%에서 {max(worse):.0f}%입니다 — 목표를 지난 뒤 손절선까지 되밀린 비율이 "
            f"{min(back):.0f}%에서 {max(back):.0f}%이기 때문입니다. {tail}.")


# ── 라운드 368 — 원장이 **자체 모순**인가 (mfe/mae/close_return) ──────────────────────────
#   라운드 17c 가 이 물음을 위해 `scripts/ledger_consistency_r17c.py` 를 만들었고, 라운드 363 이
#   그것을 찾았다 — **저장소 전체에서 부르는 곳 0곳**(R195 '존재는 실행이 아니다' · R284 '배선된 적이
#   없다' · R297 '읽는 곳 0곳'이 만나는 자리). 돌려 보면 68.6% 가 '위반'이라 그대로는 못 넣었고,
#   R363 은 *"경계를 오늘 고르면 결과를 보고 고른 문턱이다(§2-5)"* 라며 접었다.
#
#   그 68.6% 를 하나씩 가르니 **틀린 것은 원장이 아니라 검사였다.** 셋 다 문턱이 아니라 정의다:
#
#   ⓐ ① *"mfe ≥ 0 이고 mae ≤ 0"* 은 **애초에 불변식이 아니다.** 교과서의 MFE/MAE 는 진입점을
#      포함해 0 에서 시작하지만, 이 엔진의 값은 `prediction_log.grade_prediction` 의
#      `path = bars[:upto]` — **진입 다음 봉부터의** 최고·최저를 진입가에 견준 것이다. 갭상승해
#      진입가 아래로 한 번도 안 내려가면 `min(low) > entry` 라 **mae > 0 이 옳다**(실측 21,856행).
#      바르게 적으면 **조건부**다 — 손절가 < 진입가 < 목표가 이므로 `mae > 0 이면 outcome ≠ STOP` ·
#      `mfe < 0 이면 outcome ≠ TARGET`. (R237·R239·R359 와 같은 계열 — 이름이 계산보다 넓었다.)
#   ⓑ ②③ 은 **outcome == 'OPEN' 에서만** 불변식이다. 청산이 있으면 mfe/mae 는 **청산 봉까지**,
#      `close_return_pct` 는 **20봉 전체**라 두 창이 다르다(`MODEL_VERSIONS.md` 가 이미 적어 둔
#      사실이고, 그 창 차이가 이 검사가 배선 안 된 까닭일 것이다). OPEN 이면 `upto = len(bars)` 라
#      창이 같아진다 — 실측 위반 **0 / 9,819**.
#   ⓒ ④⑤ 는 진짜 불변식인데(청산 봉이 경로에 **들어간다**) **허용 오차가 틀렸다.** 원장은
#      `calibration_lab` 이 `round(mfe_pct, 2)` 로 담는데 검사는 `1e-6` 으로 견줬다 — 2자리로 담긴
#      수의 허용 오차는 **마지막 자리의 반**이다. 걸린 911행 전부 배율(최저가÷손절가) **1.000**,
#      즉 반올림이 유일한 원인이다. R363 이 *"미분류"* 로 남긴 ⑤ 771 · ④ 140 은 **결함이 아니었다.**
#
#   바르게 적으면 **254,329행 전부 통과**다(2026-09-27). 허용 오차는 결과를 보고 늘린 것이 아니라
#   **저장 정밀도에서 유도**했다(§2-5) — 아래 상수가 그 자리이고, 회귀가 랩의 반올림 자리와 대 본다.
#
#   ⚠️ **이 다섯은 전부 '행 안'의 정합이다.** 라운드 364 의 결함(원장 진입가가 **일봉 계열**과
#   축척이 어긋난 16종목)은 행과 **바깥 세계**의 불일치라 어떤 내부 불변식도 못 본다 — 실제로
#   바르게 적은 다섯을 그 16종목에 대 봐도 위반 0 이다. 그래서 `scripts/entry_scale_audit.py`(R365)가
#   따로 있어야 한다. **둘 중 어느 쪽도 다른 쪽을 대신하지 않는다.**
#: 원장이 담는 소수 자리 — `scripts/calibration_lab.py` 의 `round(..., 2)`. 회귀가 둘을 대 본다.
LEDGER_STORED_DP = 2
#: 허용 오차 = 마지막 자리의 반 + float 여유. **고른 값이 아니라 저장 정밀도에서 유도한 값.**
CONSISTENCY_TOL = 0.5 * 10.0 ** (-LEDGER_STORED_DP) + 1e-9


def consistency_violations(row, tol=CONSISTENCY_TOL):
    """원장 한 행이 자체 모순인가. **어긴 불변식 이름들**을 tuple 로 돌린다(없으면 빈 tuple).

    칸을 못 읽으면 `('칸 못 읽음',)` 이다 — **통과로 세지 않는다**(§3 · 0건이 '없다'인지
    '못 봤다'인지 갈려야 한다 · R194). 순수 함수 — 파일도 네트워크도 안 읽는다.
    """
    try:
        p = float(row['price'])
        mfe = float(row['mfe_pct'])
        mae = float(row['mae_pct'])
        cl = float(row['close_return_pct'])
    except (KeyError, TypeError, ValueError):
        return ('칸 못 읽음',)
    if not p:
        return ('진입가 0',)
    oc = row.get('outcome')
    out = []
    # ⓐ ① 은 조건부로만 불변식이다 (위 주석)
    if mae > tol and oc == 'STOP':
        out.append('① mae>0 인데 STOP')
    if mfe < -tol and oc == 'TARGET':
        out.append('① mfe<0 인데 TARGET')
    # ⓑ ②③ 은 OPEN 에서만 두 창이 같다
    if oc == 'OPEN':
        if cl > mfe + tol:
            out.append('② OPEN 인데 종가>최고')
        if cl < mae - tol:
            out.append('③ OPEN 인데 종가<최저')
    # ⓒ ④⑤ — 청산 봉이 경로에 들어가므로 반드시 성립한다
    try:
        if oc == 'TARGET' and row.get('target') is not None:
            if mfe < (float(row['target']) / p - 1.0) * 100.0 - tol:
                out.append('④ TARGET인데 mfe<목표폭')
        if oc == 'STOP' and row.get('stop') is not None:
            if abs(mae) < (1.0 - float(row['stop']) / p) * 100.0 - tol:
                out.append('⑤ STOP인데 |mae|<손절폭')
    except (TypeError, ValueError, ZeroDivisionError):
        out.append('목표·손절 못 읽음')
    return tuple(out)


# ── 하락 국면 + 과매도/하단 — 그 자리의 값어치 (라운드 423 · 표시 전용) ─────────────
#   라운드 8 이 원장 7,947건으로 '조건부 참고'로 채택한 규칙이다. 2026-10-03 같은 스크립트를 한 글자도 안 고치고
#   원장 257,130행에서 돌리니 채택 없음이었다(scripts/bear_oversold_r423.py 가 오늘 셈 규칙으로 다시 재어 산출물에
#   싣는다). 카드는 이 함수로 **산출물이 뒷받침하는 말만** 한다 — 수를 글자로 박지 않는다(라운드 422 의 그 자리).
BEAR_OVERSOLD_RULES = ('RSI 과매도', '볼린저 하단')     # 화면이 고르는 규칙 이름 — 산출물의 rules 열쇠와 같다


def bear_oversold_rules(rsi, bb_pos, doc=None):
    """지금 값이 맞는 규칙 이름들. 문턱은 산출물의 `thresholds`(= regime_rule_r6.RULES 의 수)에서 읽고, 못 읽으면 빈
    목록이다 — 문턱을 여기서 다시 적지 않는다(§4). RSI 가 맞으면 RSI 규칙, 볼린저가 맞으면 볼린저 규칙, 둘 다면 둘 다."""
    th = (doc or {}).get('thresholds') or {}
    out = []
    try:
        if rsi is not None and th.get('rsi_lt') is not None and float(rsi) < float(th['rsi_lt']):
            out.append(BEAR_OVERSOLD_RULES[0])
        if bb_pos is not None and th.get('bb_pos_lt') is not None and float(bb_pos) < float(th['bb_pos_lt']):
            out.append(BEAR_OVERSOLD_RULES[1])
    except (TypeError, ValueError):
        return []
    return out


def bear_oversold_card(doc, rules):
    """산출물 + 맞는 규칙 이름 → (제목, 본문) 또는 None(못 읽음 · 규칙 없음 · 표본 없음 — 지어내지 않는다).

    제목은 첫 규칙의 판정에서 고른다 — 채택 기준 충족이면 '높았던 자리', 홀드아웃 lift 가 0 이하면 '더 잦던 자리가
    아니었다', 양수지만 미달이면 '기준에 못 미쳤다'. 문턱 없음(기준은 산출물의 criteria · 라운드 8 의 수).
    **판정을 대신 내리지 않는다** — 어느 경우든 매수 근거가 아니라고 적는다(라운드 8 의 채택 범위도 그랬다)."""
    if not doc or not rules:
        return None
    R = doc.get('rules') or {}
    base = (doc.get('baseline') or {}).get('hold') or {}
    first = R.get(rules[0]) or {}
    h, b = first.get('hold') or {}, first.get('blind') or {}
    lift = first.get('lift') or {}
    if not h.get('n') or base.get('hit') is None or lift.get('hold') is None:
        return None
    cond = ' · '.join(rules)
    if first.get('adopted'):
        head = '같은 국면 평균보다 목표에 먼저 닿는 비율이 높았던 자리입니다'
    elif lift['hold'] <= 0:
        head = '반등이 더 잦던 자리가 아니었습니다'
    else:
        head = '같은 국면 평균보다 조금 높았지만 채택 기준에 못 미쳤습니다'
    title = f'하락 국면 + {cond} — {head}'
    s = [f"{doc.get('made', '?')} 원장(판정 완료 {int(doc.get('graded_rows') or 0):,}건)으로 다시 재니, 본 적 없는 "
         f"종목에서 {rules[0]} 조건의 사례 {int(h['n']):,}건 중 <b>{h['hit']:.1f}%</b>가 20거래일 안에 목표에 먼저 "
         f"닿았습니다 — 같은 하락 국면 평균 {base['hit']:.1f}%보다 <b>{lift['hold']:+.1f}%p</b>."]
    if lift.get('blind') is not None and b.get('n'):
        s.append(f"실전 구간에서는 {lift['blind']:+.1f}%p였습니다({int(b['n']):,}건이지만 날짜 {b.get('dates')}일이라 "
                 f"약한 근거입니다).")
    if h.get('net') is not None and doc.get('cost_pct') is not None:
        s.append(f"운영 비용 {doc['cost_pct']}%를 빼면 평균 {h['net']:+.2f}%입니다.")
    for name in rules[1:]:
        o = R.get(name) or {}
        oh, ol = o.get('hold') or {}, (o.get('lift') or {}).get('hold')
        if oh.get('n') and ol is not None:
            s.append(f"{name} 조건은 {int(oh['n']):,}건 {oh['hit']:.1f}%({ol:+.1f}%p)였습니다.")
    prev = doc.get('previous') or {}
    if not first.get('adopted') and prev.get('hold_hit') is not None:
        s.append(f"원장이 {int(prev.get('ledger_rows') or 0):,}건이던 때에는 RSI 과매도 조건이 본 적 없는 종목 "
                 f"{prev.get('hold_n')}건에서 {prev['hold_hit']}%({prev.get('hold_lift', 0):+.1f}%p)로 재여 참고 표시로 "
                 f"채택했던 규칙입니다 — 표본이 커지자 그 우위가 재현되지 않았습니다.")
    s.append('이 조건은 매수 근거가 아니며, 위의 결론과 점수는 이 규칙과 무관합니다.')
    return title, ' '.join(s)
