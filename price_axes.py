# -*- coding: utf-8 -*-
"""
중앙 가격 엔진 — 하나의 '적정가'를 세 축으로 분리한다.

사용자 지적: *"적정가 산정에 대해서 심히 고민 좀 해보자."*
맞다. 지금까지 '적정가' 한 숫자가 서로 다른 세 가지 질문에 동시에
답하려 했다. 그래서 26,350원짜리 종목에 21,218원이 '권장 매수가'로
붙는 일이 생겼다. 세 질문은 지평도, 근거도, 쓰임도 다르다.

■ 세 축
  ① 장기 가치 범위 (value_band)
     "이 기업의 값어치는 대략 얼마인가" — 몇 년 지평. 숫자 하나가
     아니라 **범위**다. 이익·장부가 모델의 분위수 범위를 그대로 쓴다.
     단일 중심값을 목표가처럼 읽히게 두지 않는다.

  ② 시장 기반 공정가격 (market_fair)
     "지금 시장은 이 종목을 얼마로 보는가" — 수개월 지평. 장기 가치에
     시장 상태(국면·모멘텀)를 얹어 **지금 붙을 법한 가격**을 낸다.
     장기 가치가 없으면 이 축도 없다.

  ③ 실전 진입가격 (entry)
     "그래서 얼마에 사는가" — 수일 지평. 밸류에이션이 아니라 **변동성**이
     정한다(라운드 25: 현재가 × (1 − 20일 변동성), 실측 79.3% 체결 ·
     평균 3.4일). 장기 가치가 없어도 이 축은 살아 있다.

■ 숫자를 억지로 만들지 않는다
  적자기업·바이오·ETF/ETN·레버리지/인버스·신규상장은 이익·장부가 모델이
  성립하지 않는다. 이때 **'미산출'은 오류가 아니라 정상 상태**다.
  이유를 적고 빈칸으로 둔다. 그리고 ③ 실전 진입가격은 그대로 낸다 —
  가치평가가 안 되는 종목도 매매 자체는 할 수 있기 때문이다.

■ 신뢰도 등급이 영향력을 정한다
    80 이상   정상    — 점수·판정에 그대로 반영
    60~79     제한적  — 반영하되 가중치 축소
    40~59     참고만  — 화면에 표시만, 판정에 미반영
    40 미만   제외    — 표시도 하지 않음
"""
from __future__ import annotations

#: 신뢰도 등급 경계 (사전등록 — 측정 후 내리지 않는다)
TIERS = ((80.0, 'normal', '정상', 1.0),
         (60.0, 'limited', '제한적', 0.5),
         (40.0, 'reference', '참고만', 0.0),
         (0.0, 'excluded', '제외', 0.0))

#: 이익·장부가 모델이 성립하지 않는 유형 — 미산출이 정상
NA_ASSET = {
    'ETF': 'ETF·ETN은 개별 기업이 아니라 펀드입니다',
    'ETF_LEV': '레버리지 ETF는 일일 재조정 상품이라 기업가치 개념이 없습니다',
    'ETF_INV': '인버스 ETF는 일일 재조정 상품이라 기업가치 개념이 없습니다',
}
#: 기업유형 확률이 이 이상이면 '이익 기반 가치평가 부적합'으로 본다
NA_TYPE_CUT = 0.40
NA_TYPE = {
    'F_DEFICIT': '적자 기업이라 이익 기반 적정가가 성립하지 않습니다',
    'E_BIOTECH': '신약 파이프라인 가치가 지배해 현재 이익으로 값을 매길 수 없습니다',
}
#: 상장 후 이 일수 미만이면 신규상장으로 본다 (모델·표본 모두 부족)
NEW_LISTING_BARS = 250


#: 라운드 28b 실측 — 적정가 미산출 케이스의 블라인드 성적
#: (매수권 58+ · n=152 · 적중 53.9% · Wilson 하한 46%)
#: 이 하한을 regime_policy 의 **이미 채택된** 구간 규칙에 넣으면 '주의'(상한 62)다.
#: 손으로 고른 숫자가 아니라, 다른 축에서 사전등록된 규칙의 재사용이다.
NA_SCORE_CAP = 62
NA_MEASURED = dict(blind_n=152, blind_hit=53.9, blind_low=46.0,
                   calc_n=128, calc_hit=58.6, calc_low=50.0,
                   calc_ev=1.03, na_ev=-0.84)


def score_policy(band):
    """
    적정가가 판정에 얼마나 개입할 것인가.

    ■ 왜 '필수 게이트'를 그만두는가 (라운드 28b)
      종전 엔진은 '적정가 신뢰도 확보'를 TOP3 필수 조건으로 걸었다. 그런데
      원장 19,883건 중 **62.9%가 적정가 미산출**이고, 산출 여부가 블라인드
      적중률을 유의하게 가르지 못했다 (lift +4.7%p · 사전등록 기준 5%p 미달 ·
      Wilson 구간 겹침 [50~67] vs [46~62]). 근거 없이 3분의 2를 막고 있었다.

    ■ 그렇다고 그냥 열지도 않는다
      블라인드 EV 는 갈렸다 — 산출 +1.03% vs 미산출 −0.84%. 적중률로는
      유의하지 않지만 EV 로는 방향이 있다. 그래서 **차단 대신 점수 상한**을
      건다. 상한값은 regime_policy 의 사전등록 구간 규칙을 그대로 재사용한다
      (하한 46% → '주의' → 62점).

    ■ 신뢰도 등급별 개입 (사용자 사양 · 원장에 신뢰도가 없어 미검증)
      80+ 정상 / 60~79 제한적(절반) / 40~59 참고만(미반영) / 40↓ 제외
    """
    if not band.get('available'):
        return dict(usable=False, score_cap=NA_SCORE_CAP, weight=0.0,
                    tier='none', tier_ko='미산출', block=False,
                    why=(f"적정가가 산출되지 않았습니다 — {band.get('why', '')} "
                         f"실측상 미산출 자체가 추천을 막을 근거는 아니지만"
                         f"(블라인드 적중률 차이 유의하지 않음), 블라인드 EV 가"
                         f" 갈려서(산출 {NA_MEASURED['calc_ev']:+.2f}% vs 미산출"
                         f" {NA_MEASURED['na_ev']:+.2f}%) 점수 상한"
                         f" {NA_SCORE_CAP}점을 겁니다."))
    code = band.get('tier')
    weight = band.get('weight', 0.0)
    caps = {'normal': None, 'limited': None, 'reference': NA_SCORE_CAP}
    return dict(usable=(code in ('normal', 'limited')),
                score_cap=caps.get(code, NA_SCORE_CAP), weight=weight,
                tier=code, tier_ko=band.get('tier_ko'), block=False,
                why=(f"적정가 신뢰도 {band.get('confidence', 0):.0f}점 "
                     f"({band.get('tier_ko')}) — {band.get('note', '')}"))


def tier_of(confidence):
    """신뢰도 → (코드, 한글, 판정 반영 가중치)."""
    if confidence is None:
        return 'excluded', '제외', 0.0
    for edge, code, ko, w in TIERS:
        if float(confidence) >= edge:
            return code, ko, w
    return 'excluded', '제외', 0.0


def _f(v):
    try:
        if v is None:
            return None
        f = float(v)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


def _blank(why, kind='미산출'):
    return dict(available=False, why=why, kind=kind)


def value_band(val_eval, asset_type=None, bars=None):
    """
    ① 장기 가치 범위 — 숫자 하나가 아니라 범위.

    범위는 모델 분위수(core=25~75 / wide=10~90)를 그대로 쓴다. 중심값은
    참고로만 싣고, '목표가'라는 이름을 절대 붙이지 않는다.
    """
    ve = val_eval or {}
    why = None
    if asset_type in NA_ASSET:
        why = NA_ASSET[asset_type]
    elif ve.get('is_fund'):
        why = NA_ASSET['ETF']
    elif bars is not None and bars < NEW_LISTING_BARS:
        why = (f'상장 후 거래일이 {int(bars)}일뿐이라 모델도 표본도 '
               f'부족합니다 (기준 {NEW_LISTING_BARS}일)')
    else:
        probs = ve.get('type_probabilities') or ve.get('type_probs') or {}
        for k, msg in NA_TYPE.items():
            if _f(probs.get(k)) is not None and _f(probs.get(k)) >= NA_TYPE_CUT:
                why = msg
                break
    if why:
        return _blank(why + ' — 억지로 숫자를 만들지 않습니다.')

    if str(ve.get('fair_value_status')) == 'OUT_OF_DOMAIN':
        return _blank(ve.get('fair_value_status_note')
                      or '모델 적용 범위 밖이라 적정가를 산출하지 않습니다.')

    core = ve.get('fair_value_range_core')
    wide = ve.get('fair_value_range_wide')
    conf = _f(ve.get('fair_value_confidence')) or 0.0
    code, ko, weight = tier_of(conf)
    if not core or len(core) != 2 or _f(core[0]) is None:
        return _blank('가치평가 모델이 하나도 유효하지 않아 범위를 낼 수 없습니다.')
    if code == 'excluded':
        return _blank(f'적정가 신뢰도가 {conf:.0f}점이라 범위조차 제시하지 않습니다.',
                      kind='신뢰도 미달')

    lo, hi = float(core[0]), float(core[1])
    wlo, whi = ((float(wide[0]), float(wide[1]))
                if wide and len(wide) == 2 and _f(wide[0]) is not None
                else (lo, hi))
    return dict(
        available=True, low=lo, high=hi, wide_low=wlo, wide_high=whi,
        center=_f(ve.get('reference_fair_value')),
        confidence=conf, tier=code, tier_ko=ko, weight=weight,
        horizon='수년',
        basis=(f"이익·장부가 모델 {int(ve.get('independent_models') or 0)}종의 "
               f"25~75분위 범위 (넓게 보면 "
               f"{wlo:,.0f}~{whi:,.0f}원)"),
        note=('판정에 그대로 반영합니다.' if code == 'normal' else
              '판정에 절반만 반영합니다.' if code == 'limited' else
              '화면 표시용입니다 — 판정에는 넣지 않습니다.'),
    )


def market_fair(val_eval, band, regime_gate=None):
    """
    ② 시장 기반 공정가격 — 장기 가치에 지금 시장 상태를 얹은 값.

    장기 가치 범위가 없으면 이 축도 없다. 지어내지 않는다.
    """
    if not band.get('available'):
        return _blank('장기 가치 범위가 없어 시장 공정가격도 낼 수 없습니다.')
    ve = val_eval or {}
    center = _f(ve.get('displayed_fair_value')) or _f(band.get('center'))
    if center is None:
        return _blank('중심 가치가 없어 시장 공정가격을 낼 수 없습니다.')

    adj = _f(ve.get('market_adjustment_pct')) or 0.0
    # 성적이 무너진 국면에서는 시장가를 더 보수적으로 본다. 올리지는 않는다.
    rg = regime_gate or {}
    size = _f(rg.get('size_mult'))
    regime_adj = 0.0
    if size is not None and size < 1.0:
        regime_adj = -(1.0 - size) * 10.0
    price = center * (1.0 + (adj + regime_adj) / 100.0)
    parts = [f"장기 가치 중심 {center:,.0f}원", f"시장 조정 {adj:+.1f}%"]
    if regime_adj:
        parts.append(f"{rg.get('cell_ko') or '국면'} 보정 {regime_adj:+.1f}%")
    return dict(available=True, price=float(price), horizon='수개월',
                basis=' · '.join(parts),
                confidence=band.get('confidence'), tier=band.get('tier'),
                tier_ko=band.get('tier_ko'), weight=band.get('weight'))


def entry(four_scores, curr_price=None):
    """
    ③ 실전 진입가격 — 밸류에이션이 아니라 변동성이 정한다.

    장기 가치가 미산출이어도 이 축은 살아 있다. 가치평가가 안 되는
    종목도 매매는 할 수 있기 때문이다.
    """
    fs = four_scores or {}
    px = _f(curr_price) or _f(fs.get('current_price'))
    p = _f(fs.get('entry_pullback_price'))
    basis = '현재가 − 20일 변동성 1σ (라운드 25 · 실측 체결률 79.3% · 평균 3.4일)'
    if p is None:
        p = _f(fs.get('recommended_buy_price'))
        basis = '적정가 − 안전마진 (변동성 기반 진입가 미산출 시 폴백)'
    if p is None:
        p = _f(fs.get('entry_review_price'))
        basis = str(fs.get('entry_review_basis') or '기술적 지지선 (적정가 검증 없음)')
    if p is None:
        return _blank('변동성도 지지선도 산출되지 않아 진입가를 낼 수 없습니다.')

    out = dict(available=True, price=float(p), horizon='수일', basis=basis,
               stop=_f(fs.get('entry_stop_price')),
               target1=_f(fs.get('entry_target_1st')),
               rr=_f(fs.get('entry_rr')))
    if px:
        out['gap_pct'] = round((p / px - 1.0) * 100.0, 2)
    return out


def build(val_eval, four_scores, curr_price=None, asset_type=None, bars=None):
    """
    세 축을 한 번에. 화면·추천·AI 요약이 전부 이 결과 하나만 본다.

    반환: value_band · market_fair · entry · tier · consistent · notes
    """
    fs = four_scores or {}
    at = asset_type or fs.get('asset_type')
    rg = fs.get('regime_gate')
    band = value_band(val_eval, asset_type=at, bars=bars)
    mkt = market_fair(val_eval, band, regime_gate=rg)
    ent = entry(fs, curr_price=curr_price)

    notes = []
    # 세 축이 서로 모순인가 — 진입가가 장기 가치 범위 위쪽 밖이면 경고
    consistent = True
    px = _f(curr_price) or _f(fs.get('current_price'))
    if band.get('available') and ent.get('available'):
        if ent['price'] > band['wide_high']:
            consistent = False
            notes.append(
                f"실전 진입가 {ent['price']:,.0f}원이 장기 가치 범위 상단 "
                f"{band['wide_high']:,.0f}원보다 높습니다 — 값어치보다 비싸게 "
                f"사는 자리입니다.")
    if band.get('available') and px:
        if px > band['wide_high']:
            notes.append(
                f"현재가 {px:,.0f}원은 장기 가치 범위 상단 "
                f"{band['wide_high']:,.0f}원 위입니다.")
        elif px < band['wide_low']:
            notes.append(
                f"현재가 {px:,.0f}원은 장기 가치 범위 하단 "
                f"{band['wide_low']:,.0f}원 아래입니다.")
    if not band.get('available'):
        notes.append(f"장기 가치는 {band['why']} 실전 진입가는 그대로 유효합니다.")

    code, ko, weight = tier_of(band.get('confidence'))
    return dict(value_band=band, market_fair=mkt, entry=ent,
                tier=code, tier_ko=ko, weight=weight,
                policy=score_policy(band),
                consistent=consistent, notes=notes,
                current_price=px)
