# -*- coding: utf-8 -*-
"""
중앙 판정 엔진 — 모든 화면이 **이 결과 하나만** 읽는다.

사용자 지적: *"추천 화면, 종목 상세, 가늠 AI, 차트, 보유자 화면이 서로 다른
결론이나 가격을 표시하지 않도록 중앙 판정 엔진을 하나로 통합해 주세요.
화면마다 값이 다르면 자동 테스트가 실패하도록 해 주세요."*

■ 왜 어긋났나 (라운드 31 진단)
  같은 개념에 이름이 여럿이었다:
    권장 매수가 5개 — recommended_buy_price · entry_pullback_price ·
                   buy_entry_max · entry_review_price · value_floor_price
    손절 2개 — stop_loss_price · entry_stop_price
    1차 목표 2개 — target_tech_1st · entry_target_1st
  그리고 추천 카드는 premarket 이 만든 rec_buy/target/stop 을,
  상세 화면은 four_scores 원본을 읽었다. **경로가 둘이었다.**
  경로가 둘이면 한쪽만 고치는 일이 생기고, 실제로 그렇게 어긋났다
  (라운드 30: GS 손절이 매수가 위, NAVER 목표가 매수가 아래).

■ 규칙
  ① 화면은 four_scores 를 직접 읽지 않는다. `build()` 결과만 읽는다.
  ② 신규 매수자 값과 보유자 값을 **다른 키**로 분리한다. 섞이면 버그다.
  ③ 미산출은 None 으로 둔다 — 임의 숫자로 채우지 않는다.
  ④ 정합(손절<진입<목표)이 깨지면 그 값을 **비우고** 사유를 남긴다.
"""
from __future__ import annotations

# 라운드 185 — 밸류 게이트(라운드 183)의 **단일 구현**을 읽는다.
# R183 이 next_action 에만 걸었더니 이 파일이 그 존재를 모른 채 같은 종목을
# '눌림목 매수 대기'로 승격시켰다 — 서진시스템(적정가 산출 불가)이 화면의
# '다음 거래일에 실제로 손댈 수 있는 후보' 칸에 오른 원인. 판정자가 둘이면
# 반드시 어긋난다 (§4). next_action 은 표준 라이브러리만 쓰는 잎 모듈이라
# 순환이 없다 — 그쪽이 verdict_core 를 임포트하게 되면 이 줄이 순환이 된다.
# 그때는 게이트를 셋째 모듈로 빼야 한다.
import next_action as _value_gate

#: 추천 자격 — 아래 checks 전부 통과해야 '오늘 살 수 있는 종목'이다
#: (사용자 사양 §2 의 10조건 + 라운드 185 의 밸류 게이트 1건 = 11)
#:
#: 진입 깊이 상한은 **손으로 고르지 않았다** — 그리고 자를 두 번 바꿨다.
#:
#: 라운드 33 (기각): 진입가를 고정 %(−0.5%~−30%)로 훑어 체결률 60% 지점을
#:   읽었다 → 5.5%. 그런데 게이트로 걸어 보니 **변동성 큰 종목만 잘렸다**:
#:   SK하이닉스 −10.1% · 삼성전자 −8.6% · 우리기술 −8.4% 전부 탈락.
#:   같은 −8% 라도 일변동성 1% 종목에겐 8σ, 5% 종목에겐 1.6σ 다.
#:   **고정 %는 잘못된 자였다.** 게다가 현행 진입 엔진은 진입가를 늘 1σ
#:   아래에 두므로 도달 확률이 전 종목 82% 로 상수가 되어 무의미했다.
#:
#: 라운드 35 (채택): 같은 측정을 **σ 단위**로 다시 했다. 세 구간이
#:   1.9~2.1σ 로 거의 일치한다 — 고정 %(4.5~9.0%)보다 훨씬 안정적이다.
#:     train 2.1σ · valid 1.9σ · blind 2.1σ · 통합 2.1σ (n=5,389)
MAX_ENTRY_SIGMA = 2.1   #: 라운드 35 실측 · 통합 표본 체결률 60% 지점
SIGMA_BASIS = ('20봉 안 체결률 60% 지점을 σ 단위로 실측 · 통합 n=5,389 '
               '(train 2.1σ · valid 1.9σ · blind 2.1σ)')
MIN_RR = 0.5            #: 손익비 하한 (1차 목표 0.7R 기하의 하한)
#: 왕복 거래비용 — **이 저장소에 값이 셋 있다** (라운드 191 실측).
#:
#:   0.30  scripts/engine_bakeoff_r10·r11 · layer_study_r4 · lift_study_r5 …
#:         (라운드 4~11 시절) + quant_indicators:3066 `avg_pnl - 0.3`
#:   0.36  **여기(운영 게이트)** + scripts/entry_engine_lab · exit_engine_lab ·
#:         gen_case_layers · gen_sector_perf · breakout_study ·
#:         PREREG R43·R46·R49·R54·R57·R58·R111
#:   0.41  quant_indicators.TOTAL_COST_PCT (규칙집 항목 합) +
#:         PREREG R148·R160 이 **"저장소 채택값"** 이라 적은 값 +
#:         scripts/exec_sim · exec_levels_r17 · census_r159
#:
#: 그리고 **문서가 스스로 어긋난다** — PREREG_R46 은 *"왕복 0.36%
#: (수수료 0.03 + 세금 0.20 + 슬리피지 0.18)"* 라고 적는데 그 항목 합은
#: **0.41** 이다. `scripts/exec_sim.py` 는 0.41 을 *"현행 엔진과 같은 값"*
#: 이라 적어 두었지만 현행 운영 게이트는 이 줄의 0.36 이다.
#:
#: ⚠️ **여기서 고치지 않는다.** 0.41 로 올리면 원장 복원 실측에서
#:   *"비용 차감 기대값 양수"* 를 통과하던 **547건 중 267건(48.8%)이
#:   뒤집힌다** (`_probe/r191_cost3.py` · 2026-08-31). 운영 게이트를
#:   반 토막 내는 변경을 같은 밤에 감으로 하지 않는다 (§2) —
#:   판정 기준을 먼저 적고 원장으로 잰다:
#:   `docs/PREREG_R191_COST_UNIFY.md`
COST_PCT = 0.36         #: 현행 운영값 — 위 계보와 사전등록 참조
MIN_CONF = 45           #: 분석 신뢰도 하한
MIN_QUALITY = 40        #: 전략 품질(표본외) 하한
MIN_TURNOVER = 3e8      #: 20일 평균 거래대금 하한 (3억 · 저유동성 배제)

#: 도달 확률 — 위 σ 문턱을 사람이 읽을 수 있는 확률로 바꾼 값.
#: 무추세 랜덤워크의 최저점 분포(반사원리): P(20봉 최저 ≤ −g) = 2·Φ(−g/σ√20)
#: **게이트는 σ 문턱 하나만 쓴다.** 확률은 화면 표시용이다 — 같은 것을 두 번
#: 거르면 이유 없이 두 배로 엄격해진다.
HORIZON = 20
#: 실측 대조 (라운드 35): 모형이 낸 확률과 원장 실측 체결률
#:   1.0σ 모형 82% vs 실측 78.3%  ·  2.0σ 모형 47% vs 실측 60.3%
#: 모형은 깊은 쪽에서 실제보다 비관적이다(추세·변동성 군집을 무시하므로).
#: 그래서 **판정은 실측 σ 문턱으로 하고, 모형 확률은 참고로만 보여 준다.**
FILL_MODEL_NOTE = '무추세 모형 추정 (실측 체결률과 다를 수 있음)'

#: 추천에서 빠진 이유 — **전부 행동 조건이 붙은 이름**이다 (라운드 47).
#:
#: 종전에 '장기 관찰'이 있었다. 사용자 지적: *"장기 관찰은 언제 다시 봐야
#: 하는지 알 수 없다. 차라리 눌림목 대기나 사라고 해 줘야지."* 맞다.
#: 이름이 '관찰'이면 사용자가 할 일이 없고, 할 일이 없으면 화면에 있을
#: 이유도 없다. 그래서 **무엇을 기다리는지가 이름에 들어간다.**
BUCKETS = ('오늘 매수 가능', '눌림목 매수 대기', '돌파 후 매수 대기',
           '과열 해소 대기', '거래량 회복 대기', '시장 국면 회복 대기',
           '신뢰도·표본 확보 대기', '권장가 괴리 과다', '데이터 부족',
           '추천 제외')

#: 내일(다음 거래일) 실제로 손댈 수 있는 칸 — 오늘의 추천에 올릴 것들.
#: 나머지는 **메인에서 숨기고** 관심목록으로 내린다.
ACTIONABLE_BUCKETS = ('오늘 매수 가능', '눌림목 매수 대기', '돌파 후 매수 대기')

NO_PICK_LINE = ("오늘은 전일 확정 데이터 기준으로 다음 거래일에 실제 매수를 "
                "검토할 수 있는 종목이 없습니다. 무리하게 진입하지 않고 "
                "현금을 유지하는 것이 우선입니다.")


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


def _norm_cdf(z):
    """표준정규 누적분포 — 외부 의존 없이."""
    return 0.5 * (1.0 + _erf(z / (2.0 ** 0.5)))


def _erf(x):
    """Abramowitz–Stegun 7.1.26 (오차 < 1.5e-7)."""
    s = 1.0 if x >= 0 else -1.0
    x = abs(x)
    t = 1.0 / (1.0 + 0.3275911 * x)
    y = 1.0 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t
                - 0.284496736) * t + 0.254829592) * t * (2.718281828459045
                                                         ** (-x * x))
    return s * y


def fill_probability(entry, price, vol_20, horizon=HORIZON):
    """
    보유기간 안에 진입가에 닿을 확률 (%).

    무추세 랜덤워크의 최저점 분포를 쓴다(반사원리):
        P(min ≤ −g) = 2·Φ(−g / (σ√H))
    괴리와 다른 것을 잰다 — 같은 5% 라도 종목 변동성에 따라 확률이 다르다.
    돌파형(진입가가 현재가 위)이면 최고점 분포로 대칭 적용한다.
    """
    e, p, v = _f(entry), _f(price), _f(vol_20)
    if not (e and p and v and v > 0):
        return None
    g = abs(e / p - 1.0)
    if g == 0:
        return 100.0
    sig = v * (horizon ** 0.5)
    if sig <= 0:
        return None
    return round(min(100.0, 2.0 * _norm_cdf(-g / sig) * 100.0), 1)


def build(four_scores, verdict=None, price_axes=None, next_action=None,
          realtime_price=None):
    """
    모든 화면이 공유할 단일 판정.

    반환 키 (사용자 사양 §6 전부):
      action · recommended · buy_zone · pullback_zone · breakout_price ·
      new_target · new_stop · hold_trim · hold_stop · horizon_days ·
      reach_prob · expected_return · rr · confidence · exclude_reason ·
      bucket · price_basis · incoherence
    """
    fs = four_scores or {}
    vd = verdict or {}
    ax = price_axes or fs.get('price_axes') or {}
    na = next_action or {}

    px = _f(realtime_price) or _f(fs.get('current_price'))
    ent = (ax.get('entry') or {})
    entry = _f(ent.get('price')) if ent.get('available') else None
    if entry is None:                      # 축이 없으면 엔진 원값으로 폴백
        # ⚠️ 라운드 53c — 여기 `recommended_buy_price`(적정가 × 안전마진)가
        # 중간에 끼어 있었다. 라운드 25 에서 폐기하고 37 에 배너에서 걷어낸
        # 산식이다. 이 폴백이 걸리면 buy_zone·정합·actionable 이 전부 그 값을
        # 기준으로 계산되는데, pullback_zone 은 entry_pullback_price 만 쓰므로
        # **매수구간은 폐기 산식으로 그려지고 진입가는 비는** 조합이 나온다.
        # 실행할 수 없는 자리를 매수구간이라 부르지 않는다.
        entry = (_f(fs.get('entry_pullback_price'))
                 or _f(fs.get('entry_review_price')))

    stop = _f(fs.get('entry_stop_price'))
    tgt = _f(fs.get('entry_target_1st'))
    rr = _f(fs.get('entry_rr'))

    # ── ④ 정합 — 깨지면 비우고 사유를 남긴다 ──────────────────────────
    inc = list(fs.get('level_incoherence') or [])
    if entry:
        if stop is not None and stop >= entry:
            inc.append(f'손절({stop:,.0f})이 진입가({entry:,.0f}) 이상 — 표시 제외')
            stop = rr = None
        if tgt is not None and tgt <= entry:
            inc.append(f'1차 목표({tgt:,.0f})가 진입가({entry:,.0f}) 이하 — 표시 제외')
            tgt = rr = None

    # ── ② 보유자 값은 별도 키 (신규 매수자와 절대 섞지 않는다) ────────
    hold_trim = _f(fs.get('target_tech_1st'))
    hold_stop = _f(fs.get('stop_loss_price'))
    if px:
        if hold_stop is not None and hold_stop >= px:
            hold_stop = None
        if hold_trim is not None and hold_trim <= px:
            hold_trim = None

    gap = _pct(entry, px)                        # 진입가가 현재가보다 얼마나 아래인가
    vol20 = _f(fs.get('vol_20')) or _f(fs.get('vol20'))
    fill_p = fill_probability(entry, px, vol20)
    turnover = _f(fs.get('avg_turnover_20d'))
    # 진입 깊이를 종목 자신의 변동성으로 정규화한다 (라운드 35).
    # 고정 %는 변동성 큰 종목을 부당하게 잘랐다.
    depth_sigma = (round(abs(gap) / (vol20 * 100.0), 2)
                   if (gap is not None and vol20 and vol20 > 0) else None)
    sigma = _f(fs.get('rec_buy_sigma'))
    reach = fs.get('rec_buy_reach')
    conf = _f(fs.get('analysis_confidence'))
    quality = _f(fs.get('strategy_quality_score'))
    score = _f(fs.get('final_action_score'))
    vetoes = list(vd.get('vetoes') or [])
    rg = fs.get('regime_gate') or {}

    # ── 밸류 게이트 (라운드 183 → 185) ────────────────────────────────
    # next_action 과 **같은 함수**를 읽는다 — na 인자에 기대지 않는다.
    # 관심 후보 경로는 na 를 tech_df 없이 만들어 늘 no_data 였고(가드가
    # 조용히 꺼진 자리 — 못 받은 na 가 게이트를 끄면 라운드 177 의 재판이다),
    # 상세 경로는 na 의 observe 를 이 파일이 도로 승격시켰다. 둘 다
    # fs 에서 직접 판정하면 막힌다. 문턱은 R183 그대로 — 새 숫자 없음.
    vb_code, vb_reason = _value_gate.value_block(fs)
    _ov = _f(fs.get('fair_overshoot_pct'))
    if vb_code:
        vb_detail = str(vb_reason)
    elif _f(fs.get('displayed_fair_value')) is None:
        # §3 — 못 잰 것(UNCALCULATED 등)으로 거르지 않는다. 막는 것은
        # 모델이 거부한 경우(OUT_OF_DOMAIN)뿐이며 그건 value_block 이 가른다.
        vb_detail = '적정가 미산출 — 못 잰 것으로 거르지 않음'
    elif _ov is not None:
        vb_detail = f'적정가 대비 {_ov:+.1f}%'
    else:
        vb_detail = '적정가 이하'

    # 기대수익 — 지어내지 않는다. 목표·손절과 과거 적중률이 다 있을 때만.
    cb = fs.get('calibration_band') or {}
    hit = _f(cb.get('hit_rate'))
    exp_ret = None
    if entry and tgt and stop and hit is not None and (cb.get('n') or 0) >= 30:
        p = hit / 100.0
        up = (tgt / entry - 1.0) * 100.0
        dn = (stop / entry - 1.0) * 100.0
        exp_ret = round(p * up + (1 - p) * dn - COST_PCT, 2)

    # ── ① 추천 조건 (사용자 사양 §2 의 10 + 라운드 185 밸류 게이트) ────
    # ⚠️ 순서를 바꾸지 않는다 — 회귀가 checks[7](과열·저유동성)을 자리로
    #   읽는다. 새 조건은 **끝에만** 더한다.
    checks = [
        ('권장 매수가 산출', entry is not None,
         f'{entry:,.0f}원' if entry else '미산출'),
        ('진입 깊이 현실적', depth_sigma is not None
         and depth_sigma <= MAX_ENTRY_SIGMA,
         (f'{depth_sigma:.2f}σ ({gap:+.1f}% · 상한 {MAX_ENTRY_SIGMA}σ · '
          f'{SIGMA_BASIS})' if depth_sigma is not None else '산출 불가')),
        ('보유기간 안 도달 가능', depth_sigma is not None
         and depth_sigma <= MAX_ENTRY_SIGMA,
         (f'{HORIZON}봉 실측 체결률 기준 통과 · 모형 확률 {fill_p:.0f}% '
          f'({FILL_MODEL_NOTE})'
          if fill_p is not None else '산출 불가')),
        ('목표·손절 산출', tgt is not None and stop is not None,
         '있음' if (tgt and stop) else '미산출'),
        ('손익비(진입가·1차) 기준 이상', rr is not None and rr >= MIN_RR,
         f'{rr}' if rr is not None else '미산출'),
        ('비용 차감 기대값 양수', exp_ret is not None and exp_ret > 0,
         f'{exp_ret:+.2f}%' if exp_ret is not None else '산출 불가'),
        ('신뢰도·전략품질 기준', (conf is not None and conf >= MIN_CONF)
         and (quality is not None and quality >= MIN_QUALITY),
         f'신뢰 {conf:.0f} · 품질 {quality:.0f}'
         if (conf is not None and quality is not None) else '미산출'),
        ('과열·저유동성 아님',
         (not _overheated(fs))
         and (turnover is None or turnover >= MIN_TURNOVER),
         _heat_txt(fs)
         + (f' · 거래대금 {turnover / 1e8:.1f}억' if turnover else '')),
        ('표본외 검증 통과', not fs.get('blind_test_not_completed'),
         str(fs.get('blind_test_status') or '미수행')),
        ('강제 차단 없음', not vetoes and not rg.get('block_new'),
         f'{len(vetoes)}건' if vetoes else '없음'),
        # 라운드 185 — 밸류 게이트 (R183 블라인드 실측: 적정가 이하만 양수
        # +0.238% · 초과는 음수 · OUT_OF_DOMAIN 은 최악 −1.237%)
        ('펀더멘털 밸류 검증', vb_code is None, vb_detail),
    ]
    failed = [c[0] for c in checks if not c[1]]
    recommended = not failed

    bucket, reason = _bucket(failed, na, gap, entry, sigma, fill_p,
                             depth_sigma, turnover=turnover,
                             heat=_heat_txt(fs),
                             regime_block=bool(rg.get('block_new')),
                             vetoes=vetoes, vb_reason=vb_reason)

    # 내일 실제로 손댈 수 있는가 — 오늘의 추천에 올릴지 가르는 단 하나의 기준.
    #
    # 사용자 지적: *"권장 매수가가 현재가보다 지나치게 낮은 종목은 추천하지
    # 말고, 현실적인 눌림목이나 돌파 조건을 제시할 수 있을 때만 대기 후보로."*
    # 맞다. 조건을 제시할 수 없으면 화면에 있을 이유가 없다.
    #
    # 자를 새로 만들지 않는다 — MAX_ENTRY_SIGMA(2.1σ)가 이미 '20봉 안 체결률
    # 60% 지점'의 실측값이다(라운드 35 · n=5,389). 그 안이면 다음 거래일부터
    # 실제로 걸어 둘 수 있는 자리고, 밖이면 장기 참고선이지 매수가가 아니다.
    actionable = (bucket in ACTIONABLE_BUCKETS
                  and entry is not None and tgt is not None and stop is not None
                  and depth_sigma is not None
                  and depth_sigma <= MAX_ENTRY_SIGMA
                  and not inc)

    # ── '다음 조건' 한 줄도 여기서 정한다 (라운드 193) ────────────────
    #
    # ⚠️ 화면의 '다음 조건 — 언제 사면 되나' 칸이 `next_action` 의 headline
    #    을 **그대로** 그리고 있었다. 그런데 next_action 은 **가격 거리만**
    #    본다 — 게이트(표본·거래대금·손익비·밸류)를 모른다. 그래서 같은
    #    화면 한 장이 반대되는 말을 했다 (2026-08-31 삼성전자 실측):
    #
    #       다음 조건  "246,930원 이하에서 분할매수할 수 있습니다"
    #       배너·지시서 "지금은 사지 마세요" / "쫓아가지 마세요"
    #
    #    실측(`_probe/r193_kind_vs_bucket.py` · 25종목 · t_ref 2026-08-28):
    #    **20종목(80%)** 에서 next_action 이 buy_now 인데 중앙 판정은 '오늘
    #    매수 가능'이 아니었다. 그중 **11종목은 actionable=False** —
    #    엔진이 명시적으로 제외한 종목에 대고 칸이 매수를 권하고 있었다.
    #    §4 가 금지한 그것이다(경로가 둘이면 한쪽만 고치는 일이 생긴다).
    #
    #    고침: 이 칸이 읽을 문장을 **중앙 판정이 정한다.** next_action 의
    #    조건 목록·가격선은 그대로 쓰되, '살 수 있다'는 **결론**은 여기서
    #    나온다. 문구는 라운드 136 이 이미 채택한 말투를 재사용한다(§2-6)
    #    — *"여기까지 내려와도 아직은 못 삽니다."*
    _na_kind = str(na.get('kind') or '')
    _na_head = str(na.get('headline') or '')
    if bucket == '오늘 매수 가능' or _na_kind != 'buy_now':
        next_kind, next_headline = _na_kind, _na_head
    else:
        next_kind = 'blocked'
        _tail = f' — {reason}' if reason else f' — {bucket}'
        next_headline = ((f'{entry:,.0f}원까지 내려와도 오늘은 아직 '
                          f'못 삽니다') if entry
                         else '오늘은 아직 못 삽니다') + _tail

    return dict(
        # 결론
        action=str(vd.get('action') or ''),
        headline=str(vd.get('headline') or ''),
        recommended=recommended,
        bucket=bucket,
        actionable=actionable,
        # 라운드 186 — 진입가의 **이름**도 여기서 정한다 (사용자 R184 분석 P1).
        #   추천 조건을 전부 통과했을 때만 '권장 매수가'다. 아니면 그 값은
        #   변동성으로 계산한 검토 기준일 뿐인데 '권장'이라 부르면 카드가
        #   "매수 후보가 아닙니다"라고 말하면서 같은 칸에서 권장가를 내미는
        #   자기모순이 된다(서진시스템 스크린샷). 화면이 각자 정하면 §4
        #   위반이라 한 곳에서 정한다.
        entry_label=('권장 매수가' if recommended else '검토 기준가'),
        exclude_reason=reason,
        # 라운드 193 — '다음 조건' 칸의 결론 문장. 화면은 이것만 읽는다.
        next_kind=next_kind, next_headline=next_headline,
        checks=[dict(name=n, ok=bool(o), detail=d) for n, o, d in checks],
        failed=failed,
        # 신규 매수자 가격 (한 기준: 진입가)
        buy_zone=(None if entry is None
                  else (round(entry * 0.99), round(entry * 1.01))),
        pullback_zone=_f(fs.get('entry_pullback_price')),
        breakout_price=_f(na.get('breakout_price')) or _f(fs.get('high_20d')),
        new_target=tgt, new_stop=stop, rr=rr,
        # 보유자 가격 (절대 섞지 않는다)
        hold_trim=hold_trim, hold_stop=hold_stop,
        # 판단 부가
        horizon_days=int(_f(fs.get('horizon_days')) or 20),
        reach_prob=fill_p, reach_label=reach, reach_sigma=sigma,
        turnover=turnover, vol_20=vol20, depth_sigma=depth_sigma,
        expected_return=exp_ret, confidence=conf, score=score,
        current_price=px, gap_pct=(round(gap, 2) if gap is not None else None),
        price_basis='진입가 기준 (신규 매수자) · 보유자 값은 hold_* 키',
        incoherence=inc,
        regime=rg.get('cell_ko'), regime_level=rg.get('level'),
    )


#: 과열 지표의 실제 키 이름 (라운드 190 에 문턱은 next_action 으로 옮겼다 —
#: 아래 표는 그 이력을 남기기 위한 것이고 판정에는 쓰이지 않는다). 라운드 35 에서 **이름을 잘못 읽고 있었다** —
#: bb_position/williams_r/rsi_14 로 찾았는데 엔진은 *_pct/*_value 로 내보낸다.
#: 그래서 지표가 전부 None 이 되고, 대신 적정가 구간('크게 초과')만으로
#: 과열을 판정했다. 그 결과 삼성전자·SK하이닉스처럼 유동성 최상위 종목이
#: '과열'로 탈락했다. 라운드 28b 에서 적정가 구간이 성과를 유의하게 가르지
#: 못한다고 이미 측정했으므로, 적정가를 과열 판정에 쓰지 않는다.
_HEAT_KEYS = (('bb_position_pct', '볼린저', 95.0, 'ge'),
              ('williams_r_value', 'W%R', -10.0, 'ge'),
              ('rsi_value', 'RSI', 75.0, 'ge'))


def _heat_hits(fs):
    """과열 지표 중 몇 개가 임계를 넘었나 · 읽은 값들.

    ⚠️ 라운드 190 — 세는 일을 `next_action.heat_state()` **한 곳**으로
      옮겼다. 문턱(95 / −10 / 75)이 두 파일에 각각 적혀 있었고, 우연히
      같았을 뿐 한쪽만 고치면 어긋나는 상태였다. **결합 규칙은 각자
      그대로다** — 여기는 3중 2, next_action 은 3중 1. 규칙을 바꾸는 것은
      게이트를 바꾸는 일이라 측정 없이 하지 않는다 (§2).
    """
    st = _value_gate.heat_state(fs)
    return st['hits'], st['seen'], st['parts']


def _overheated(fs):
    """
    기술적 과열만 본다 — 적정가 구간은 쓰지 않는다 (라운드 28b·35).

    지표를 하나도 못 읽으면 **과열이 아니라고 본다.** 못 읽은 것을
    과열로 취급하면 데이터 결측이 매수 차단으로 둔갑한다.
    """
    hits, seen, _ = _heat_hits(fs)
    return seen >= 2 and hits >= 2


def _heat_txt(fs):
    _, seen, parts = _heat_hits(fs)
    if not parts:
        return '과열 지표 미수신 (과열로 보지 않음)'
    return ' · '.join(parts)


def _bucket(failed, na, gap, entry, sigma, fill_p=None, depth=None,
            turnover=None, heat=None, regime_block=False, vetoes=None,
            vb_reason=None):
    """
    왜 추천에서 빠졌는가 — **무엇을 기다리면 되는지**를 이름에 넣는다.

    순서가 곧 우선순위다. 위쪽이 더 근본적인 막힘이라 먼저 잡는다.
    """
    if not failed:
        return '오늘 매수 가능', ''
    if '권장 매수가 산출' in failed or '목표·손절 산출' in failed:
        return '데이터 부족', '실행 가격을 산출하지 못했습니다.'
    # 라운드 185 — 밸류 게이트는 기다림이 아니라 제외다. OUT_OF_DOMAIN 은
    # 가격이 움직여도 안 풀리고, 적정가 초과는 사유 문장이 스스로 조건
    # (적정가 아래)을 말한다. 아래 kind='observe' 승격보다 **먼저** 잡아야
    # R183 이 뺀 종목이 '눌림목 매수 대기'로 되살아나지 않는다.
    if '펀더멘털 밸류 검증' in failed:
        return '추천 제외', str(vb_reason or '펀더멘털 밸류 검증 미통과')
    if '강제 차단 없음' in failed:
        if regime_block:
            return '시장 국면 회복 대기', (
                '지금 시장 국면에서 이 전략의 성적이 무너져 신규 매수를 '
                '막고 있습니다. 국면이 돌아서면 다시 봅니다.')
        # 거부권은 이미 사람이 읽을 수 있는 문장이다 — 그걸 그대로 낸다.
        # 종전에는 "매수를 막는 조건이 있습니다"로 뭉뜽그려서, 무엇이 막는지
        # 알 수 없었다. 막힌 이유를 모르면 언제 풀리는지도 알 수 없다.
        vs = [str(v).strip() for v in (vetoes or []) if str(v).strip()]
        if vs:
            more = f' 외 {len(vs) - 2}건' if len(vs) > 2 else ''
            return '추천 제외', ' · '.join(vs[:2]) + more
        return '추천 제외', '매수를 막는 조건이 있습니다.'
    if '과열·저유동성 아님' in failed:
        # 과열과 저유동성은 기다리는 것이 다르다 — 섞어 부르지 않는다
        if turnover is not None and turnover < MIN_TURNOVER:
            return '거래량 회복 대기', (
                f'20일 평균 거래대금이 {turnover / 1e8:.1f}억으로 기준'
                f'({MIN_TURNOVER / 1e8:.0f}억)에 못 미칩니다. 거래가 붙어야 '
                f'계산한 가격에 실제로 체결됩니다.')
        return '과열 해소 대기', (
            f'급등 직후라 추격 위험이 큽니다. {heat or "과열 지표"}가 '
            f'풀린 뒤 다시 봅니다.')
    if '진입 깊이 현실적' in failed or '보유기간 안 도달 가능' in failed:
        g = f'{gap:+.1f}%' if gap is not None else '산출 불가'
        d = f'{depth:.2f}σ' if depth is not None else '산출 불가'
        return '권장가 괴리 과다', (
            f'진입가가 현재가 대비 {g}({d}) 라 {HORIZON}봉 안에 닿을 확률이 '
            f'60% 미만입니다 (상한 {MAX_ENTRY_SIGMA}σ · 실측). '
            f'현실적인 매수 조건을 제시할 수 없어 추천에서 뺍니다.')
    # 라운드 128 — 종전에는 이 둘을 한 문장으로 묶어
    #   "사례가 더 쌓여야 판단할 수 있습니다" 라고만 했다. **둘 중 하나는
    #   그 말이 거짓이다.**
    #
    #     · 표본외 검증 통과 ✗  — 그 종목의 일봉이 모자라(학습 400봉 ·
    #       표본외 20건 미만) **검증 자체를 못 한** 경우다. 거래일이
    #       쌓이면 실제로 풀린다.
    #     · 신뢰도·전략품질 기준 ✗ — 검증은 **이미 했고 성적이 나빴다.**
    #       품질 점수가 화면에 찍혀 있다는 것이 그 증거다(예: 품질 32).
    #       사례가 쌓인다고 풀리지 않는다 — 가격 흐름이 달라져야 한다.
    #
    #   기다리면 된다고 말해 놓고 영원히 안 풀리면, 화면이 없는 길을
    #   가리킨 것이다 (§3 · §9). 두 경우를 갈라서 말한다.
    if '표본외 검증 통과' in failed:
        return '신뢰도·표본 확보 대기', (
            '이 종목은 표본외 검증을 아직 하지 못했습니다 — 일봉이 모자라 '
            '학습·검증 구간을 나눌 수 없습니다. 거래일이 쌓이면 다시 봅니다.')
    if '신뢰도·전략품질 기준' in failed:
        return '신뢰도·표본 확보 대기', (
            '표본외 검증은 마쳤고, 그 성적이 기준에 못 미쳤습니다. '
            '사례가 쌓인다고 풀리는 조건이 아닙니다 — 이 종목에서 이 전략의 '
            '표본외 성적이 살아나야 합니다.')
    kind = str(na.get('kind') or '')
    if kind == 'breakout':
        return '돌파 후 매수 대기', '돌파 후 재지지를 확인해야 합니다.'
    if kind == 'pullback':
        return '눌림목 매수 대기', '눌림을 기다립니다.'
    if kind == 'observe':
        # 종전 '장기 관찰' — 조건이 없으면 화면에 둘 이유가 없다.
        # 손익비·기대값처럼 **가격이 움직여야 풀리는** 조건이면 눌림목 대기,
        # 그것도 아니면 추천에서 뺀다.
        # 라운드 191 — 체크 이름을 '손익비(진입가·1차) 기준 이상' 으로
        #   갈랐으므로 여기 매칭도 같이 맞춘다. 이름만 바뀌었다.
        if any(x in failed for x in ('손익비(진입가·1차) 기준 이상',
                                     '비용 차감 기대값 양수')):
            return '눌림목 매수 대기', (
                '지금 가격에서는 손익비(진입가·1차)·기대값이 기준에 '
            '못 미칩니다. '
                '더 낮은 자리에서만 셈이 맞습니다.')
        return '추천 제외', _unmet(failed)
    return '눌림목 매수 대기', _unmet(failed)


def _unmet(failed):
    """미충족 체크 이름을 **사유 문장**으로 쓸 때 (라운드 193).

    ⚠️ 종전에는 `' / '.join(failed[:3])` 을 그대로 사유 자리에 넣었다.
       그런데 체크 이름은 **통과했을 때 참인 문장**이다. 그래서
       "오늘은 아직 못 삽니다 — 비용 차감 기대값 양수" 처럼 **뜻이
       뒤집혀** 읽혔다(기대값이 양수여서 못 산다는 말로).
       화면의 제외 목록이 이미 쓰는 말투를 재사용한다(§2-6) — '미충족:'.
    """
    names = [str(f) for f in (failed or []) if str(f).strip()]
    if not names:
        return ''
    more = f' 외 {len(names) - 3}건' if len(names) > 3 else ''
    return '미충족: ' + ' / '.join(names[:3]) + more


def screen_values(v):
    """
    화면 간 일치를 확인할 때 비교하는 값들.

    회귀 테스트가 이 묶음을 모든 화면에서 뽑아 같은지 본다.
    다르면 실패한다 — 사용자 요구 그대로다.
    """
    return {k: v.get(k) for k in (
        'action', 'recommended', 'buy_zone', 'pullback_zone',
        'breakout_price', 'new_target', 'new_stop', 'hold_trim', 'hold_stop',
        'horizon_days', 'reach_prob', 'expected_return', 'rr', 'confidence',
        'exclude_reason', 'bucket', 'actionable')}
