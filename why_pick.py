# -*- coding: utf-8 -*-
"""
왜 이 종목인가 — 추천 근거를 사람이 읽는 문장으로.

사용자 지적: *"추천주가 거의 다 권장매수가 위다 보니 왜 이 주식을 사야
하는지 말해 주면 좋겠다. 단순히 점수가 높다는 이유만 보여줄 것이 아니라."*

맞다. '49점 · 신뢰도 88' 은 근거가 아니라 라벨이다. 그 점수가 **어떤 매수
논리**를 뜻하는지 말해야 한다.

■ 이 모듈이 지키는 것
    · **실제 값이 있는 항목만 쓴다.** 없으면 그 줄을 빼지, 빈칸을 채우지
      않는다 (CLAUDE.md §3)
    · 근거마다 **숫자와 출처**를 같이 낸다. "거래량이 늘었다"가 아니라
      "20일 평균 대비 2.1배"
    · **위험요인을 반드시 하나 낸다.** 좋은 말만 늘어놓으면 그건 광고다
    · 뉴스는 **가격 선반영 여부까지 판정**한다. 좋은 뉴스인데 이미 올랐으면
      그건 매수 근거가 아니라 추격 위험이다

■ 이 모듈이 하지 않는 것
    · 점수를 만들지 않는다. `verdict_core` 가 낸 판정을 **설명만** 한다
    · 섹터 모멘텀으로 매수가를 끌어올리지 않는다 — 라운드 44에서 실측하고
      기각했다 (블라인드 호황 구간 적중 50.0% · 비용후 EV −2.467%).
      업황은 '참고'로만 적고 판정에 넣지 않는다
"""
from __future__ import annotations

#: 거래대금이 평소 대비 이 배수 이상이면 '늘었다'고 말한다.
#: 손으로 고른 값이 아니라 **화면 표현의 문턱**이다 — 판정에 쓰지 않는다.
#: (판정용 문턱은 verdict_core 가 실측값으로 갖고 있다)
TURNOVER_SURGE = 1.5
#: 52주 위치가 이 위면 '이미 많이 올랐다'로 본다 (선반영 판단 보조).
#: 룰북 RULES_SECTOR.price_priced_in_range_pos 와 같은 값을 쓴다.
PRICED_IN_RANGE_POS = 80.0


def _f(v):
    try:
        if v is None:
            return None
        x = float(v)
        return None if x != x else x
    except (TypeError, ValueError):
        return None


def _won(v):
    f = _f(v)
    return None if f is None else f'{f:,.0f}원'


# ───────────────────────────────────────────────────────────────────
# 정량 근거
# ───────────────────────────────────────────────────────────────────

def quant_reasons(core, fs, limit=3):
    """
    숫자로 말할 수 있는 근거만. 각 항목은 (제목, 문장).

    없는 근거는 만들지 않는다 — 빈 목록이 정상 상태다.
    """
    out = []
    fs = fs or {}
    px = _f(core.get('current_price'))

    # ① 과거 같은 자리에서 얼마나 맞았나 — 표본을 반드시 같이 낸다
    # ⚠️ 라운드 185 — 종전 제목이 '검증된 적중률'이었다. 이 표본
    #   (calibration bands)은 학습·검증 포함 **전체 리플레이**라 '검증된'이
    #   과장이다 — 라운드 184 가 다섯 자리에서 걷어낸 그 결함('안 본
    #   사례')의 **다른 표기**가 여기 살아 있었다. 같은 카드 아래 칸은
    #   이미 '리플레이 적중'이라 적고 있어 한 카드가 두 말을 했다.
    cb = fs.get('calibration_band') or {}
    n, hit = _f(cb.get('n')), _f(cb.get('hit_rate'))
    low = _f(cb.get('wilson_low'))
    if n and hit is not None and n >= 30:
        lo, hi = cb.get('lo'), cb.get('hi')
        band = f'{lo:.0f}~{hi:.0f}점' if lo is not None and hi is not None else '같은 점수대'
        s = (f'{band} 리플레이 {int(n):,}건(학습·검증 포함) 중 {hit:.0f}%가 '
             f'손절보다 목표가에 먼저 닿았습니다')
        if low is not None:
            s += f' (95% 하한 {low:.0f}%)'
        out.append(('과거 동점수대 리플레이 적중', s + '.'))

    # ② 손익비 — 한 번 맞고 한 번 틀렸을 때 남는가
    rr = _f(core.get('rr'))
    if rr is not None:
        out.append(('손익비(진입가·1차)',
                    f'진입가 기준 목표까지와 손절까지의 비가 {rr}:1 입니다.'))

    # ③ 비용 차감 기대값 — 수수료·세금까지 빼고도 남는가
    ev = _f(core.get('expected_return'))
    if ev is not None:
        out.append(('비용 차감 기대값',
                    f'왕복 거래비용을 뺀 뒤 기대값이 {ev:+.2f}% 입니다.'))

    # ④ 진입가 도달 가능성 — σ 로 잰다 (라운드 35 실측)
    d, reach = _f(core.get('depth_sigma')), _f(core.get('reach_prob'))
    gap = _f(core.get('gap_pct'))
    if d is not None and gap is not None:
        s = (f'매수가가 현재가에서 {gap:+.1f}%({d:.2f}σ) 떨어져 있어 '
             f'{core.get("horizon_days", 20)}거래일 안에 닿을 만한 자리입니다')
        if reach is not None:
            s += f' (모형 추정 {reach:.0f}%)'
        out.append(('도달 가능성', s + '.'))

    # ⑤ 거래대금 — 계산한 가격에 실제로 체결되는가
    tv = _f(core.get('turnover'))
    tv20 = _f(fs.get('turnover_20d_avg')) or _f(fs.get('avg_turnover_20d'))
    if tv and tv20 and tv20 > 0:
        mult = tv / tv20
        if mult >= TURNOVER_SURGE:
            out.append(('거래 증가',
                        f'거래대금이 20일 평균의 {mult:.1f}배로 늘었습니다 '
                        f'({tv / 1e8:.0f}억).'))
    elif tv:
        out.append(('유동성',
                    f'20일 평균 거래대금 {tv / 1e8:.0f}억으로 계산한 가격에 '
                    f'체결될 만합니다.'))

    # ⑥ 지지선이 가까운가
    sup = _f(fs.get('support_price')) or _f(fs.get('bb_lower'))
    if sup and px and 0 < (px - sup) / px < 0.15:
        out.append(('가까운 지지선',
                    f'{_won(sup)} 부근에 지지선이 있어 손절 자리가 '
                    f'분명합니다.'))

    return out[:limit] if limit else out


def risk_note(core, fs):
    """가장 큰 위험 하나. **반드시 낸다** — 없으면 그 사실을 적는다."""
    fs = fs or {}
    if core.get('incoherence'):
        return ('가격 정합 경고',
                '손절·진입·목표의 순서가 어긋나 값을 비웠습니다. '
                '이 종목은 실행 가격을 신뢰하지 마세요.')
    rr = _f(core.get('rr'))
    if rr is not None and rr < 1.0:
        return ('손익비(진입가·1차) 1 미만',
                f'손익비(진입가·1차)가 {rr}:1 이라 맞은 횟수가 틀린 '
                f'횟수보다 많아야 '
                f'본전입니다. 현행 목표 구조(손절거리 0.7배) 탓입니다.')
    ev = _f(core.get('expected_return'))
    if ev is not None and ev <= 0:
        return ('기대값 음수',
                f'비용을 빼면 기대값이 {ev:+.2f}% 입니다. 반복하면 잃는 자리입니다.')
    rp = _f(fs.get('range_position_pct')) or _f(fs.get('range_pos'))
    if rp is not None and rp >= PRICED_IN_RANGE_POS:
        return ('52주 고점권',
                f'52주 범위의 {rp:.0f}% 지점이라 되돌림 폭이 클 수 있습니다.')
    conf = _f(core.get('confidence'))
    if conf is not None and conf < 60:
        return ('신뢰도 제한',
                f'분석 신뢰도가 {conf:.0f}점이라 판단 근거가 얇습니다.')
    n = _f((fs.get('calibration_band') or {}).get('n'))
    if not n or n < 100:
        return ('표본 부족',
                '비슷한 과거 사례가 충분히 쌓이지 않아 확률 판단의 폭이 넓습니다.')
    return ('공통 한계',
            '이 엔진의 매수권 신호에는 실전에서 재현되는 비용 차감 우위가 '
            '아직 확인되지 않았습니다. 참고 자료로만 쓰세요.')


# ───────────────────────────────────────────────────────────────────
# 뉴스 근거 — 개수가 아니라 내용
# ───────────────────────────────────────────────────────────────────

def news_reason(nf, core, fs):
    """
    뉴스를 '몇 건'이 아니라 **무엇이 어떻게 관련되는가**로 낸다.

    반환: dict(available, headline, source, when, dropped, direction,
               priced_in, applied, text)
    확인 못 한 것은 그대로 '확인되지 않았습니다'라고 쓴다.
    """
    nf = nf or {}
    fs = fs or {}
    if not nf.get('feed_available', True):
        return dict(available=False, text=(
            '뉴스를 수신하지 못했습니다. 뉴스 미수신은 악재가 아니며, '
            '이 종목의 판단에 뉴스를 반영하지 않았습니다.'))

    fresh = int(_f(nf.get('fresh')) or 0)
    lag = int(_f(nf.get('lagging')) or 0)
    risk = list(nf.get('risk_words') or [])
    heads = list(nf.get('headlines') or [])
    if not fresh and not risk:
        return dict(available=False, text=(
            f'추천 판단에 반영할 정도로 신뢰할 수 있는 신규 뉴스나 공시는 '
            f'확인되지 않았습니다'
            + (f' (후행·중복 보도 {lag}건 제외).' if lag else '.')))

    top = heads[0] if heads else {}
    title = str(top.get('title') or '').strip()
    src = str(top.get('source') or '').strip()
    when = str(top.get('when') or top.get('published') or '').strip()

    # 선반영 판정 — 좋은 뉴스라도 이미 올랐으면 매수 근거가 아니다
    rp = _f(fs.get('range_position_pct')) or _f(fs.get('range_pos'))
    chg20 = _f(fs.get('change_20d_pct')) or _f(fs.get('return_20d_pct'))
    priced = None
    why_priced = ''
    if rp is not None and rp >= PRICED_IN_RANGE_POS:
        priced = True
        why_priced = f'52주 범위의 {rp:.0f}% 지점'
    elif chg20 is not None and chg20 >= 15.0:
        priced = True
        why_priced = f'최근 20거래일 {chg20:+.0f}%'
    elif rp is not None:
        priced = False
        why_priced = f'52주 범위의 {rp:.0f}% 지점'

    direction = '위험' if risk else '긍정'
    parts = []
    if title:
        parts.append(f'"{title}"'
                     + (f' ({src}{" · " + when if when else ""})' if src else ''))
    if lag:
        parts.append(f'중복·후행 보도 {lag}건은 제외했습니다')
    if risk:
        parts.append(f'확인이 필요한 낱말이 잡혔습니다 — {", ".join(risk[:3])}. '
                     f'룰북이 신규 매수를 차단합니다')
    elif priced is True:
        parts.append(f'다만 {why_priced}이라 재료가 이미 가격에 반영된 것으로 '
                     f'보고 **긍정 가점을 넣지 않았습니다**')
    elif priced is False:
        parts.append(f'{why_priced}이라 가격에 아직 크게 반영되지는 않았습니다')

    # 실제로 판정에 얼마나 들어갔는가 — 숨기지 않는다
    applied = ('신규 매수 차단' if risk else '가점 0 (검증 전까지 올리지 않음)')
    parts.append(f'추천 점수 반영: {applied}')

    return dict(available=True, headline=title, source=src, when=when,
                dropped=lag, direction=direction, priced_in=priced,
                applied=applied, text=' · '.join(parts) + '.')


def sector_reason(cyc):
    """업황 — **참고**로만. 라운드 44에서 판정 반영은 기각됐다."""
    cyc = cyc or {}
    if not cyc.get('linked'):
        return None
    rs, mom = _f(cyc.get('rs60')), _f(cyc.get('mom60'))
    if rs is None and mom is None:
        return None
    bits = []
    if mom is not None:
        bits.append(f'프록시 60일 {mom:+.1f}%')
    if rs is not None:
        bits.append(f'S&P500 대비 {rs:+.1f}%p')
    return ('업황 (참고)',
            f'{cyc.get("ko") or "업종"} 업황은 {" · ".join(bits)} 입니다. '
            f'다만 업황 모멘텀이 국내 종목 결과를 예측하는지 원장 16,805건으로 '
            f'실측했고 게이트를 넘지 못해 **판정에는 넣지 않았습니다** '
            f'(라운드 44).')


def build(core, fs, news_flags=None, sector_cycle=None):
    """카드에 실을 '왜 이 종목인가' 한 묶음."""
    q = quant_reasons(core, fs)
    n = news_reason(news_flags, core, fs)
    s = sector_reason(sector_cycle)
    r = risk_note(core, fs)
    return dict(quant=q, news=n, sector=s, risk=r,
                has_any=bool(q or (n and n.get('available'))))
