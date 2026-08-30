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

#: 라운드 52 실측 — 개발 구간 KOSPI 4상태 (진단용 · 점수에 넣지 않는다)
MARKET_STATES = {
    'ABOVE_BOTH': dict(
        ko='20·60일선 모두 위', n=8007, days=412, hit=59.8, ev=-0.122,
        say='시장 중기 추세가 살아 있습니다.'),
    'REBOUND': dict(
        ko='20일선 위·60일선 아래 (반등 초기)', n=1543, days=105,
        hit=48.0, ev=-0.978,
        say='개발 구간에서 **가장 나빴던 구간**입니다 — 가짜 반등이 잦습니다.'),
    'PULLBACK': dict(
        ko='20일선 아래·60일선 위 (조정)', n=2056, days=135,
        hit=60.9, ev=+0.224,
        say='개발 구간에서 **유일하게 비용후 기대값이 양수**였던 구간입니다.'),
    'BEAR': dict(
        ko='20·60일선 모두 아래 (약세)', n=4118, days=290,
        hit=57.9, ev=-0.254,
        say='엔진이 이 국면에서 신규 매수 점수에 상한 55를 겁니다.'),
}

#: 라운드 36 — 목표 배수 재탐색 결과. 카드에 그대로 적는다.
TARGET_CAVEAT = ('1차 목표는 손절거리의 0.7배로 잡는 현행 기하입니다. '
                 '0.4R~3.0R 를 전부 훑었으나 어떤 배수도 학습·검증·블라인드 '
                 '세 구간 모두에서 양수가 아니었습니다 (라운드 36) — '
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


def market_state(kospi_px, ma20, ma60, ma60_prev=None):
    """4상태 + 60일선 기울기. 못 재면 None (지어내지 않는다)."""
    px, m20, m60 = _f(kospi_px), _f(ma20), _f(ma60)
    if not (px and m20 and m60):
        return None
    if px > m20 and px > m60:
        code = 'ABOVE_BOTH'
    elif px > m20:
        code = 'REBOUND'
    elif px > m60:
        code = 'PULLBACK'
    else:
        code = 'BEAR'
    out = dict(MARKET_STATES[code])
    out['code'] = code
    mp = _f(ma60_prev)
    if mp is not None:
        out['slope'] = 'up' if m60 > mp else 'down'
        out['slope_ko'] = '상승' if m60 > mp else '하락'
        # 같은 약세라도 60선이 오르는 중이면 실측이 크게 달랐다 (67.1 vs 53.8)
        if code == 'BEAR':
            out['slope_note'] = (
                '같은 약세라도 60일선이 상승 중이면 개발 구간 적중 67.1%, '
                '하락 중이면 53.8% 로 갈렸습니다 (라운드 52).'
                if out['slope'] == 'up' else
                '60일선이 하락 중입니다 — 개발 구간 적중 53.8% · EV −0.679 로 '
                '가장 나쁜 조합이었습니다 (라운드 52).')
    return out


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
        line = (f'현재가 {px:,.0f}원이 검증된 매수구간 안에 있습니다.'
                if px else '')
    elif bucket == '눌림목 매수 대기':
        head = f'{entry:,.0f}원 부근까지 눌리면 1차 분할매수'
        line = (f'현재가 {px:,.0f}원은 매수구간보다 '
                f'{_pct(px, entry):+.1f}% 위입니다. 쫓아가지 마세요.'
                if px else '')
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
    """보유자 지시. 평단이 없으면 아무것도 만들지 않는다."""
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
    ('손절가를 종가로 이탈하면', '예외 없이 정리합니다.'),
    ('위험 공시·악재가 나오면', '가격과 무관하게 다시 판정합니다.'),
]
POST_ENTRY_CAVEAT = (
    '위 규칙은 실행 순서를 정한 것이고, **각 지점의 최적 수치는 아직 '
    '측정하지 못했습니다.** 원장의 최대상승·최대낙폭이 청산 시점까지만 '
    '기록돼 있어 추적손절을 과거에 재현할 수 없기 때문입니다. '
    '봉 단위 경로를 다시 돌리는 별도 라운드가 필요합니다.')


def build(core, fs=None, avg=None, qty=None, market=None):
    """카드 하나에 실을 전체 지시서."""
    return dict(
        market=market,
        buyer=for_buyer(core, fs),
        holder=for_holder(core, avg, qty),
        post_entry=POST_ENTRY,
        post_entry_caveat=POST_ENTRY_CAVEAT,
    )
