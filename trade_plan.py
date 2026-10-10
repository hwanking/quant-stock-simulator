# -*- coding: utf-8 -*-
"""
매매 지시서 — "그래서 얼마에 사서 언제 파는가".

사용자 지적: *"판단 점수만 보여주는 시스템에서 끝나면 부족합니다. 결국
그래서 지금 사야 하나, 몇 % 먹고 팔아야 하나, 손절은 어디인가, 보유자는
어떻게 해야 하나를 알고 싶습니다."*

맞다. 점수는 라벨이지 지시가 아니다.

■ 이 모듈이 하는 일 / 하지 않는 일
    한다    — `verdict_core` 가 낸 값을 **실행 문장**으로 바꾼다
    안 한다 — 점수를 만들거나 가격을 새로 계산하지 않는다.
              값이 둘이면 어느 쪽을 믿을지 알 수 없다 (CLAUDE.md §4)

■ 정직하게 같이 적는 것
    · 목표 배수(0.7R)에는 **검증된 우위가 없다.** 라운드 36에서
      0.4R~3.0R 를 전부 훑었고 어느 배수도 train·valid·blind 세 구간
      모두에서 양수가 아니었다. 그래서 "최적 목표"라고 쓰지 않는다
    · 시장 4상태는 **개발 구간 진단**이다. 시장 수준 축이라 블라인드
      독립 블록이 5개뿐이라 확정할 수 없다 (라운드 45·52)
    · 추적손절 수치는 **아직 측정하지 못했다.** 원장의 mfe/mae 가 청산
      봉까지만 잰 값이라 원리적으로 못 잰다. 구조만 적고 숫자는 안 만든다
"""
from __future__ import annotations

#: KOSPI 4상태의 이름 (규칙은 `market_state_code` · 라운드 52 · 진단용 · 점수에 넣지 않는다).
#: ⚠️ 라운드 422 — 여기에 라운드 52(2026-08 초 · 원장 약 5.5만 행)의 **수와 이야기**가 글자로 박혀 있었다. 오늘 원장으로
#:   같은 규칙을 세니 *"반등 초기 — 개발 구간에서 가장 나빴던 구간"*(48.0%)은 60.2% 로 바뀌어 가장 낮은 칸은 약세가 됐고,
#:   *"약세는 60일선 기울기에 따라 67.1% vs 53.8%"* 는 차이가 사라졌다. 병렬 조사 둘이 따로 짚었다. 이제 수는 매일 밤 같은
#:   4상태로 세는 취약구간 지도(`weakness_map.json` · 통계 행 · 개발 구간 · 58점+)에서 읽고, 문장은 그 수로 판정해 **맞을 때만**
#:   낸다(`state_say`). *"약세면 엔진이 점수 상한 55"* 는 **사실이다** — 국면 게이트(regime_policy)에는 없지만 시장 맥락 상한
#:   (`market_context.CONTEXT_CAPS['domestic_bear']` · 상장 시장 지수가 20·60일선 둘 다 아래)이 건다. 한때 게이트만 보고
#:   '없다'고 적을 뻔했다 — 손으로 적지 않고 그 상수를 읽어 약세일 때 적는다(`engine_cap_line`).
MARKET_STATES = {
    'ABOVE_BOTH': dict(ko='20·60일선 모두 위'),
    'REBOUND': dict(ko='20일선 위·60일선 아래 (반등 초기)'),
    'PULLBACK': dict(ko='20일선 아래·60일선 위 (조정)'),
    'BEAR': dict(ko='20·60일선 모두 아래 (약세)'),
}
#: 취약구간 지도의 '시장 국면' 칸 이름 — `scripts/weakness_map.ST_KO` 와 같은 이름(그 지도는 이 모듈의 4상태 규칙으로 센다).
STATE_AXIS_KO = {'ABOVE_BOTH': '상승', 'REBOUND': '반등초기', 'PULLBACK': '조정', 'BEAR': '약세'}
STATE_FILE = 'weakness_map.json'
STATE_AXIS = '시장 국면'

#: 라운드 36 — 목표 배수 재탐색 결과. 카드에 그대로 적는다.
TARGET_CAVEAT = ('1차 목표는 손절거리의 0.7배로 잡는 현행 기하입니다. '
                 '0.4R~3.0R 를 전부 훑었으나 어떤 배수도 학습·검증·블라인드 '
                 '세 구간 모두에서 양수가 아니었습니다 — '
                 '"최적 목표"가 아니라 "현행 기하"입니다.')


def _f(v):
    try:
        if v is None:
            return None
        x = float(v)
        return None if x != x else x
    except (TypeError, ValueError):
        return None


def _pct(a, b):
    a, b = _f(a), _f(b)
    return None if not (a and b) else (a / b - 1.0) * 100.0


def market_state_code(kospi_px, ma20, ma60):
    """4상태 코드만 — 순수 함수(산출물을 안 읽는다). 못 재면 None. 지수 일봉을 날마다 분류하는 쪽(kospi_index)이 부른다."""
    px, m20, m60 = _f(kospi_px), _f(ma20), _f(ma60)
    if not (px and m20 and m60):
        return None
    if px > m20 and px > m60:
        return 'ABOVE_BOTH'
    if px > m20:
        return 'REBOUND'
    if px > m60:
        return 'PULLBACK'
    return 'BEAR'


def state_cells(doc):
    """취약구간 지도 산출물의 '시장 국면' 칸 → {코드: 칸}. 못 읽으면 {}."""
    ax = ((doc or {}).get('axes') or {}).get(STATE_AXIS) or {}
    out = {}
    for code, ko in STATE_AXIS_KO.items():
        c = ax.get(ko)
        if isinstance(c, dict) and c.get('n') and c.get('hit') is not None:
            out[code] = c
    return out


def state_split(doc, code):
    """그 상태 칸의 학습·검증 구간별 수(날짜 수 포함) — 취약구간 지도의 `axes_split` (라운드 474). 못 읽으면 {}."""
    ko = STATE_AXIS_KO.get(code)
    per = ((((doc or {}).get('axes_split') or {}).get(STATE_AXIS) or {}).get(ko)) or {}
    out = {}
    for sp in ('train', 'valid'):
        v = per.get(sp)
        if isinstance(v, dict) and v.get('dates') and v.get('ev') is not None:
            out[sp] = v
    return out


def state_say(code, cells, cost=None):
    """그 상태에 대해 **수가 뒷받침하는 문장만** — 4상태가 다 있을 때 적중 최저·최고, 비용 뺀 기대값이 양수인 유일한 칸.
    해당 없으면 ''(이야기를 지어내지 않는다 · 라운드 422). 문턱 없음 — 넷의 순위와 부호만 본다."""
    if code not in cells or len(cells) < len(STATE_AXIS_KO):
        return ''
    hits = {k: float(v['hit']) for k, v in cells.items()}
    parts = []
    if hits[code] == min(hits.values()) and list(hits.values()).count(hits[code]) == 1:
        parts.append('개발 구간 4상태 중 매수권 적중이 **가장 낮은** 구간입니다')
    elif hits[code] == max(hits.values()) and list(hits.values()).count(hits[code]) == 1:
        parts.append('개발 구간 4상태 중 매수권 적중이 **가장 높은** 구간입니다')
    pos = [k for k, v in cells.items() if v.get('ev') is not None and float(v['ev']) > 0]
    if pos == [code]:
        c = f'비용 {float(cost):.2f}% 뺀' if cost is not None else '비용 뺀'
        parts.append(f'4상태 중 **유일하게** {c} 기대값이 양수였던 구간입니다(블라인드로 확정하지 못했습니다)')
    return ' · '.join(parts) + ('.' if parts else '')


def engine_cap_line(code):
    """그 상태에서 엔진이 실제로 거는 시장 상한 — 약세면 시장 맥락 상한값을 **모듈 상수에서 읽어** 적는다. 그 밖은 ''.

    상한은 그 종목이 **상장된 시장의 지수**로 판정된다(코스닥 종목은 코스닥 지수). 이 카드의 4상태는 코스피라서 그 사실도 적는다."""
    if code != 'BEAR':
        return ''
    try:
        import market_context
        cap = market_context.CONTEXT_CAPS.get('domestic_bear')
    except Exception:                                          # noqa: BLE001
        cap = None
    if cap is None:
        return ''
    return (f"상장 시장 지수가 20·60일선 둘 다 아래면 엔진이 신규 매수 점수에 상한 {int(cap)}점을 겁니다"
            f"(코스닥 종목은 코스닥 지수로 판정합니다).")


def _state_doc():
    try:
        import artifact_io
        return artifact_io.load_json(STATE_FILE)
    except Exception:                                          # noqa: BLE001
        return None


def market_state(kospi_px, ma20, ma60, ma60_prev=None, doc=None):
    """4상태 + 60일선 기울기 + 그 상태의 매수권 성적(산출물에서 · 날짜·원장 행과 함께). 못 재면 None (지어내지 않는다).

    doc 을 안 주면 취약구간 지도 산출물을 읽는다(artifact_io · 배포 앱은 동봉본). 산출물이 없으면 이름과 기울기만 돌려준다."""
    code = market_state_code(kospi_px, ma20, ma60)
    if code is None:
        return None
    out = dict(MARKET_STATES[code])
    out['code'] = code
    m60, mp = _f(ma60), _f(ma60_prev)
    if mp is not None and m60 is not None:
        out['slope'] = 'up' if m60 > mp else 'down'
        out['slope_ko'] = '상승' if m60 > mp else '하락'
    d = _state_doc() if doc is None else doc
    cells = state_cells(d)
    cost = (d or {}).get('cost_pct')
    c = cells.get(code)
    if c:
        out.update(n=int(c['n']), ep=c.get('ep'), hit=float(c['hit']), ev=c.get('ev'),
                   made=(d or {}).get('made'), ledger_rows=(d or {}).get('ledger_rows'), cost_pct=cost,
                   split=state_split(d, code))
    out['say'] = ' '.join(x for x in (state_say(code, cells, cost), engine_cap_line(code)) if x)
    return out


def state_basis_line(m):
    """그 상태 성적의 출처 한 줄 — 수·날짜·원장 행·비용을 산출물에서. 없으면 그 사실을 적는다(§3)."""
    m = m or {}
    if m.get('n') is None or m.get('hit') is None:
        return '이 상태의 성적은 산출물을 못 읽어 적지 않습니다.'
    ev = m.get('ev')
    cost = m.get('cost_pct')
    ev_txt = (f" · {'비용 ' + format(float(cost), '.2f') + '% 뺀' if cost is not None else '비용 뺀'} 기대값 {float(ev):+.3f}%"
              if ev is not None else '')
    return (f"개발 구간 매수권(58점+) n={int(m['n']):,}"
            + (f" · 독립 사건 {int(m['ep']):,}" if m.get('ep') else '')
            + f" · 적중 {float(m['hit']):.1f}%{ev_txt}"
            + (f" ({m.get('made')} 측정 · 원장 {int(m.get('ledger_rows') or 0):,}행)" if m.get('made') else '')
            + state_split_clause(m.get('split')))


def state_split_clause(split):
    """라운드 474 — 개발 구간을 학습·검증으로 가른 한 마디(날짜 수와 같이). 국면은 시장 수준 축이라 표본이 날짜다(R45) —
    합친 수만 내면 짧은 구간이 칸을 끌어올린 것이 안 보인다. 판정 낱말·문턱 없음. 못 읽으면 ''."""
    split = split or {}
    parts = []
    for sp, ko in (('train', '학습'), ('valid', '검증')):
        v = split.get(sp)
        if v and v.get('dates') and v.get('ev') is not None:
            parts.append(f"{ko} {int(v['dates']):,}일 {float(v['ev']):+.2f}%")
    if not parts:
        return ''
    # 왜 날짜 수인지는 카드가 바로 뒤에 적는다("유효 표본이 날짜입니다" · ui_kit) — 여기서 되풀이하지 않는다.
    return ' — 구간별: ' + ' · '.join(parts)


# ───────────────────────────────────────────────────────────────────
# 미보유자 — 무엇을 얼마에 사는가
# ───────────────────────────────────────────────────────────────────

def for_buyer(core, fs=None):
    """
    신규 매수자 지시. 값은 전부 `core`(중앙 판정)에서만 가져온다.
    """
    fs = fs or {}
    px = _f(core.get('current_price'))
    zone = core.get('buy_zone') or []
    entry = _f(core.get('pullback_zone')) or (_f(zone[0]) if zone else None)
    tgt, stop = _f(core.get('new_target')), _f(core.get('new_stop'))
    brk = _f(core.get('breakout_price'))
    bucket = str(core.get('bucket') or '')
    actionable = bool(core.get('actionable'))

    if not (entry and tgt and stop):
        return dict(available=False,
                    why='실행 가격 3종(진입·목표·손절)이 다 나오지 않아 '
                        '지시를 만들지 않습니다.')

    tgt_pct = _pct(tgt, entry)
    stop_pct = _pct(stop, entry)
    # 2차 목표는 **만들지 않는다** — 엔진이 낸 값이 있을 때만 싣는다
    tgt2 = _f(fs.get('entry_target_2nd')) or _f(fs.get('target_tech_2nd'))
    tgt2_pct = _pct(tgt2, entry) if tgt2 else None

    if not actionable:
        head = f'{bucket} — 오늘은 실행 자리가 아닙니다'
        line = str(core.get('exclude_reason') or '')
    elif bucket == '오늘 매수 가능':
        head = '지금 가격에서 1차 분할매수를 검토할 수 있습니다'
        # ⚠️ 라운드 188 — 여기가 *"검증된 매수구간"* 이었다. 이 파일 머리말이
        #   바로 위에서 *"목표 배수에는 검증된 우위가 없다"* 고 적어 두었고,
        #   §9 는 *"우위가 없으면 없다고 적는다"* 다. 원장 실측도 그렇다 —
        #   60+ 블라인드 n=1,068 · 적중 51.3% · 비용후 −1.81%
        #   (.portfolio/calibration.json · 원장 184,759건 · 잰 날 2026-08-16).
        #   '검증된'은 우리가 하지 않은 주장이다.
        line = (f'현재가 {px:,.0f}원이 오늘의 진입 기준 안에 있습니다. '
                f'이 구간에 비용 차감 후 재현되는 우위는 확인되지 '
                f'않았습니다.' if px else '')
    elif bucket == '눌림목 매수 대기':
        head = f'{entry:,.0f}원 부근까지 눌리면 1차 분할매수'
        # ⚠️ 라운드 192 — 여기가 `_pct(px, entry)`, 즉 **역수**였다.
        #   중앙 판정·next_action·price_axes 는 전부 `(진입/현재 − 1)` 인데
        #   이 한 줄만 `(현재/진입 − 1)` 을 스스로 다시 계산했다. 그래서
        #   같은 화면 한 장에 두 숫자가 나란히 있었다 (§4):
        #       다음 조건  괴리 −5.0%
        #       지시서     매수구간보다 +5.3% 위
        #   이제 단일 출처(core['gap_pct'])에서 읽고, 화면이 쓰는 '위'
        #   방향은 그 값에서 **대수로** 유도한다. 카드(web_app)와 같은
        #   식이다 — 같은 결함을 두 번째 고치는 것이므로 식을 맞춘다.
        #   그리고 **정합이 깨지면 비운다** (§4). gap_pct 가 가리키는 진입가와
        #   이 문장이 이름 부른 진입가가 다르면 두 숫자가 서로 다른 가격을
        #   말하게 된다 — 그때는 고치지 말고 문장을 비운다.
        _g = _f(core.get('gap_pct'))
        _above = None
        if _g is not None and px and 100.0 + _g > 0:
            _entry_of_gap = px * (1.0 + _g / 100.0)
            if entry and abs(_entry_of_gap / entry - 1.0) <= 0.005:
                _above = (100.0 / (100.0 + _g) - 1.0) * 100.0
        line = (f'현재가 {px:,.0f}원은 매수구간보다 '
                f'{_above:+.1f}% 위입니다. 쫓아가지 마세요.'
                if (px and _above is not None) else '')
    else:
        head = (f'{brk:,.0f}원을 거래량과 함께 돌파한 뒤 지지하면 매수'
                if brk else '돌파 확인 후 매수')
        line = '돌파 전에는 진입하지 않습니다.'

    return dict(
        available=True, actionable=actionable, bucket=bucket,
        # 라운드 186 — 진입가의 이름은 중앙 판정이 정한다 (entry_label).
        # recommended 가 아니면 화면이 '매수구간' 대신 '검토 기준가'로 적는다.
        recommended=bool(core.get('recommended')),
        entry_label=str(core.get('entry_label') or '검토 기준가'),
        headline=head, line=line,
        entry=entry, entry_zone=(zone[0], zone[1]) if len(zone) == 2 else None,
        breakout=brk, target=tgt, target_pct=tgt_pct,
        target2=tgt2, target2_pct=tgt2_pct,
        stop=stop, stop_pct=stop_pct, rr=_f(core.get('rr')),
        horizon=int(_f(core.get('horizon_days')) or 20),
        chase_limit=(entry * 1.01 if entry else None),
        expected=_f(core.get('expected_return')),
        target_caveat=TARGET_CAVEAT)


# ───────────────────────────────────────────────────────────────────
# 보유자 — 평단 기준. 예측·적정가·점수에는 절대 안 쓴다 (§9)
# ───────────────────────────────────────────────────────────────────

def for_holder(core, avg, qty=None):
    """보유자 지시. 평단이 없으면 아무것도 만들지 않는다.

    ⚠️ 라운드 357 — **여기가 라운드 304 의 나머지 절반이었다.**

    라운드 304 는 가늠 AI 의 보유자 답이 **평단 대비 수익률**(+5 / 0 / −7 · 저장소 어디에도
    근거가 없는 손으로 고른 수)로 갈래를 고르고, 중앙 판정은 **가격선 위치**(버틸 수 없는
    가격 · 1차 매도가 · 진입가)로 고르는 것을 찾아 `ui_kit.holder_kind` 한 곳으로 올렸다.
    그런데 **이 함수에는 그 수가 그대로 남아 있었다** — 그리고 이 함수는 죽지 않았다:
    `build()` 가 부르고 화면이 그 카드를 그린다. 라운드 246 의 *"고침이 판정자 한 명에게만
    갔다"* 가 또 일어난 것이다.

    실측(격자 30칸 · 고치기 전): **어긋남 21칸(70%)** — 그중 **지시서 '유지' vs 중앙
    '정리' 3칸**이 가장 나쁘다(중앙은 팔라는데 지시서가 들고 있으라 한다).

    고침은 라운드 304 와 같다 — **갈래는 `holder_kind` 가 정하고 이 함수는 말로 옮긴다.**
    문장·값·가격은 그대로다. 평단은 **수익률을 적는 데만** 쓴다(§9 — 판정에 안 쓴다).
    킷을 못 불러오면 **옛 수로 되돌아가지 않고** 판단을 비운다(§3).
    """
    a, px = _f(avg), _f(core.get('current_price'))
    if not (a and px):
        return dict(available=False)
    ret = (px / a - 1.0) * 100.0
    trim, hstop = _f(core.get('hold_trim')), _f(core.get('hold_stop'))
    buy = _f(core.get('pullback_zone')) or _f(core.get('buy_zone'))

    try:                       # 늦은 임포트 — 연구 스크립트가 이 파일을 쓸 때 화면 모듈을 안 끈다
        import ui_kit as _uk357
        kind, why = _uk357.holder_kind(px, hstop, trim, buy=buy,
                                       avg_down_ok=core.get('avg_down_ok'))
    except Exception:                                          # noqa: BLE001
        return dict(available=False,
                    reason='보유 판정을 불러오지 못했습니다 — 옛 규칙으로 대신 판단하지 '
                           '않습니다')

    _ret_txt = f'현재 {ret:+.1f}% ' + ('수익' if ret >= 0 else '손실') + '입니다(평단 기준).'
    if kind == '정리 검토':
        head = '매도 — 계획대로면 파는 자리입니다'
        body = (f'{_ret_txt} '
                + (f'{hstop:,.0f}원(버틸 수 없는 가격)을 밑돌았습니다. ' if hstop else '')
                + '계획을 세운 날 정한 선이고, 오늘 값으로 다시 고르지 않습니다.')
        add = '여기서 평단을 낮추려는 추가 매수(물타기)는 하지 않습니다.'
    elif kind == '일부 정리':
        head = '일부 매도 — 1차 매도가를 넘었습니다'
        body = (f'{_ret_txt} '
                + (f'{trim:,.0f}원(1차 매도가)을 넘었습니다. ' if trim else '')
                + '일부를 덜어내고 남은 물량은 손절선을 지켜 두세요.')
        add = '추가 매수는 하지 않습니다 — 이미 1차 매도가 위입니다.'
    elif kind == '추가 매수 가능':
        head = '보유 유지 · 추가매수 조건을 통과했습니다'
        body = (f'{_ret_txt} '
                + (f'{hstop:,.0f}원 이탈 시 정리합니다. ' if hstop else '')
                + '조건을 통과했다는 뜻이지 지금 사라는 뜻은 아닙니다.')
        add = (f'추가 매수를 본다면 {buy:,.0f}원 이하입니다.' if buy
               else '추가 매수 기준가는 산출되지 않았습니다.')
    elif kind == '보유 유지':
        head = '보유를 유지합니다'
        body = (f'{_ret_txt} '
                + (f'{trim:,.0f}원에 닿으면 1차 정리를 검토하세요. ' if trim else '')
                # 라운드 386 — '종가 이탈' 이 아니다: 보유 판정(holder_kind)은 현재가가 선 **이하**면 매도이고,
                #   원장 채점은 장중 저가가 선에 **닿으면** 손절로 센다(라운드 367 이 종가 기준을 재고 (다)).
                + (f'{hstop:,.0f}원에 닿으면 정리합니다.' if hstop else ''))
        # 라운드 413 — 종전 꼬리는 *매수구간까지 눌리면 본다*였다. 진입가 **아래**인데 새로 사도 되는 판정이 아니면
        #   눌려도 안 산다(라운드 387 이 잰 그대로) — 그 자리에서는 거짓이 된다. 진입가 아래면 킷 한 곳이 두 사실을
        #   잇고(어느 칸이 막는지 · 라운드 224 실측), 위면 조건을 바르게 적는다.
        _blk413 = _uk357.hold_add_blocked_line(px, buy, core.get('avg_down_ok'), fails=None,
                                               bucket=core.get('bucket'), bucket_why=core.get('exclude_reason'))
        add = _blk413 or ('가격이 내렸다는 이유만으로 추가 매수(물타기)하지 않습니다 — 진입가 아래로 와도 '
                          '새로 사도 되는 판정(물타기 6조건의 첫 조건)일 때만 봅니다.')
    else:
        head = '판단 보류'
        body = f'{_ret_txt} ' + str(why or '보유 기준값을 받지 못했습니다.')
        add = '기준값이 없어 추가 매수 여부를 말하지 않습니다.'
    # ⚠️ 칸 이름은 **옛 반환 그대로**다 — 카드가 `avg`·`add_note`·`trim`·`stop` 을 읽는다.
    #   라운드 357 이 처음에 `add=` 로 바꿨다가 화면이 `KeyError: 'avg'` 로 죽었다
    #   (갈래 논리를 격자로만 확인하고 카드를 한 번도 안 그렸다 · R195). 더한 칸은 `kind` 뿐이다.
    out = dict(available=True, avg=a, ret_pct=round(ret, 2),
               headline=head, body=body, add_note=add,
               trim=trim, stop=hstop, kind=kind)
    if qty:
        out['pnl'] = round((px - a) * float(qty))
    return out


def _for_holder_legacy(core, avg, qty=None):
    """⚠️ 옛 갈래 — **쓰지 않는다.** 라운드 357 이 남겨 둔 기록이다.

    평단 대비 +5 / 0 / −7 로 갈래를 골랐다. 그 수는 저장소 어디에도 근거가 없고, 라운드
    304 가 같은 수를 챗에서 걷어냈다. 지우지 않고 남기는 것은 *무엇이 어떻게 달랐는지*를
    나중에 셀 수 있게 하기 위해서다 — 부르는 곳은 **0곳**이고 회귀가 그것을 잠근다.
    """
    a, px = _f(avg), _f(core.get('current_price'))
    if not (a and px):
        return dict(available=False)
    ret = (px / a - 1.0) * 100.0
    trim, hstop = _f(core.get('hold_trim')), _f(core.get('hold_stop'))

    if ret >= 5.0:
        head = '절반 정리하고 나머지는 끌고 갑니다'
        body = (f'현재 {ret:+.1f}% 수익입니다. '
                + (f'{trim:,.0f}원 부근에서 절반을 덜어내고, ' if trim else '')
                + '남은 절반은 손절선을 최소 본전까지 올려 두세요.')
        add = '추가 매수는 하지 않습니다 — 이미 오른 자리입니다.'
    elif ret >= 0:
        head = '보유를 유지합니다'
        body = (f'현재 {ret:+.1f}% 입니다. '
                + (f'{trim:,.0f}원에 닿으면 1차 정리를 검토하세요. ' if trim else '')
                + (f'{hstop:,.0f}원 종가 이탈 시 정리합니다.' if hstop else ''))
        add = '추가 매수는 매수구간까지 눌렸을 때만 검토하세요.'
    elif ret >= -7.0:
        head = '물타기(평단 낮추기)는 하지 마세요'
        body = (f'현재 {ret:+.1f}% 손실입니다. 평단을 낮추려는 추가 매수는 '
                f'손실을 키우는 경우가 더 많습니다. '
                + (f'{hstop:,.0f}원 종가 이탈 시 정리합니다.' if hstop else ''))
        add = '추세 회복과 거래량 확인 후에만 재검토하세요.'
    else:
        head = '비중을 줄이는 쪽으로 봅니다'
        body = (f'현재 {ret:+.1f}% 손실입니다. 하락 추세가 끝났다는 확인이 '
                f'없습니다. '
                + (f'{hstop:,.0f}원 아래에서는 반등 시 비중 축소를 '
                   f'검토하세요.' if hstop else ''))
        add = '추가 매수 금지.'

    out = dict(available=True, avg=a, ret_pct=round(ret, 2),
               headline=head, body=body, add_note=add,
               trim=trim, stop=hstop)
    if qty:
        out['pnl'] = round((px - a) * float(qty))
    return out


# ───────────────────────────────────────────────────────────────────
# 매수 후 — 무엇을 보고 언제 손을 대는가 (§9)
# ───────────────────────────────────────────────────────────────────

#: ⚠️ 이 숫자들은 **측정되지 않았다.**
#:   원장의 mfe/mae 는 청산 봉까지만 잰 값이라 "고점 대비 −5% 청산" 같은
#:   추적손절을 원리적으로 재현할 수 없다(메모리: ledger-mfe-mae-window-trap).
#:   그래서 **구조만 적고 숫자는 만들지 않는다.** 재려면 봉 단위 경로를
#:   다시 돌려야 하고, 그건 별도 라운드다.
POST_ENTRY = [
    ('목표의 절반에 닿으면', '손절선을 최소 본전까지 올립니다.'),
    ('1차 목표에 닿으면', '절반을 정리하고 나머지는 추세가 유지되는 동안 둡니다.'),
    ('보유기간의 절반이 지나도 반응이 없으면',
     '거래량이 줄었는지 보고, 줄었으면 비중을 줄입니다.'),
    # 라운드 386 — 종전 '손절가를 **종가로** 이탈하면' 이었다. 보유 판정은 현재가가 선 이하면 매도이고 원장 채점은
    #   장중 저가가 선에 닿으면 손절로 센다 — 종가 기준 손절은 라운드 367 이 사전등록으로 재고 (다) 현행 유지였다.
    #   화면이 종가라 적고 엔진이 장중으로 돌면 §4 위반이다(R367 이 *"문구만 고치는 제안은 안 했다"* 고 적은 그 자리).
    ('손절가에 닿으면', '예외 없이 정리합니다.'),
    ('위험 공시·악재가 나오면', '가격과 무관하게 다시 판정합니다.'),
]
#: ⚠️ 라운드 386 — 종전 문장은 *"추적손절을 과거에 재현할 수 없기 때문 · 별도 라운드가 필요"* 였다. 그 뒤
#:   봉 단위 경로로 **쟀다**(2026-08-02 본전 스탑 · 2026-09-21 1차 목표 미청산) — 같은 화면의 쉬운 결론 카드가
#:   *"1,950건 검증"* 을 말하는데 이 칸은 *"못 잰다"* 고 해 한 화면이 두 말을 했다. 그리고 외부 검토가 짚은 대로
#:   **성적표가 이 규칙으로 채점되지 않는다**는 사실을 안 적었다. 잰 것·안 잰 것·채점 규칙을 같이 적는다.
POST_ENTRY_CAVEAT = (
    '위 규칙은 산 뒤의 실행 순서입니다. **화면의 성적(원장 채점)은 이 규칙이 아니라 '
    "'1차 목표나 손절에 먼저 닿으면 전량 청산, 20봉이 지나면 그날 종가'로 셉니다.** "
    '원장의 최대상승·최대낙폭은 청산 시점까지만 기록돼 있어 아래 변형은 봉 단위 경로로 따로 쟀습니다 — '
    '본전 올리기는 2026-08-02 경로 1,950건에서 손실로 끝난 비율을 약 3분의 1 줄였지만 비용 차감 평균은 '
    '여전히 음수였고, 1차 목표에서 팔지 않는 변형은 2026-09-21 에 쟀으나 블라인드 구간에서 통과하지 못해 '
    '채택하지 않았습니다. 절반 정리·기간 경과 축소의 수치는 측정하지 못했습니다.')


def build(core, fs=None, avg=None, qty=None, market=None, hold_core=None, market_na=None):
    """카드 하나에 실을 전체 지시서.

    hold_core — 보유자 판정에 쓸 중앙 판정(라운드 386). 관심종목의 **보유 계획**이 있으면 화면이 그 기준선
      (계획의 손절선·1차 매도가·진입가·물타기 판정)을 얹은 사본을 넘긴다 — 같은 화면의 보유 카드가 *"관리
      기준은 계획 값"* 이라 적는데 지시서만 오늘 다시 잰 값으로 판정하면 두 칸이 다른 답을 낸다(R225·R371).
      안 넘기면 종전 그대로 `core`.
    market_na — 시장 진단을 못 낸 **사유**(라운드 441 · `market` 이 None 일 때만 뜻이 있다). 카드가 '시장 진단
      미산출 — 사유' 로 적는다(§3). 종전엔 못 내면 그 절이 말없이 빠졌고, 실제로 2026-08-08 부터 한 번도
      안 나갔다(화면이 엔진 객체의 없는 속성을 읽었다).
    """
    return dict(
        market=market,
        market_na=(None if market else market_na),
        buyer=for_buyer(core, fs),
        holder=for_holder(hold_core or core, avg, qty),
        post_entry=POST_ENTRY,
        post_entry_caveat=POST_ENTRY_CAVEAT,
    )
