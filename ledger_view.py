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
            + f'. {tail}.')


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
