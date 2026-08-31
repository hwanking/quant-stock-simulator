# -*- coding: utf-8 -*-
"""
"사지 마세요"로 끝내지 않는다 — 언제·어떤 조건에서 살 수 있는지 낸다.

사용자 지적: *"지금은 사지 마세요가 아니라 이때 사세요 하면 되잖아."*
그리고: *"26,350원일 때 21,218원까지 언제 떨어져 — 이런 거 추천하면 안 된다."*

■ 이 모듈이 하는 두 가지
  1. 모든 관망 판단에 **실행 가능한 다음 조건**을 붙인다
     (지지 확인 · 돌파 후 재지지 · 과열 해소 · 거래량 안정 · 예상 대기기간)
  2. 현재가와 권장 매수가의 괴리가 큰 종목을 **오늘의 추천에서 뺀다**

■ 괴리 밴드 — 고정 비율만 쓰지 않는다
  0~5% 즉시·근접 / 5~10% 눌림목 대기 / 10~15% 장기 관찰 / 15%+ 추천 제외.
  다만 변동성이 큰 종목은 같은 %도 훨씬 쉽게 닿는다 — 앱클론은 일변동성이
  7.9%라 20일 1σ 가 ±35% 다. 그래서 ATR 로 밴드를 비례 조정한다.
  기준은 일 ATR 2%(보통 종목)이고, 배율은 0.7~2.5 로 묶는다.

■ 예상 대기기간
  무작위보행 가정: 거리 ∝ σ√t → t = (거리/σ)². 상한 60거래일.
  이건 '평균적으로 이만큼 걸린다'가 아니라 '이 정도 규모의 시간'이라는 뜻이다.

■ 지어내지 않는다
  지지·저항은 실제 계산된 값(20일선·60일선·볼린저·최근 고저)에서만 고른다.
  값이 없으면 그 조건을 아예 넣지 않는다.
"""
from __future__ import annotations

import math

#: 괴리 밴드 기준선 (일 ATR 2% 종목 기준) — ATR 로 비례 조정한다
BANDS = (5.0, 10.0, 15.0)
BASE_ATR_PCT = 2.0
SCALE_MIN, SCALE_MAX = 0.7, 2.5
MAX_WAIT_DAYS = 60

#: 과열 판정 문턱
HOT_BB = 95.0          # 볼린저 위치 %
HOT_WR = -10.0         # Williams %R (0 에 가까울수록 과열)
HOT_RSI = 75.0
COOL_BB = 80.0
COOL_WR = -20.0
#: 거래량이 이보다 크면 '아직 안 가라앉음'
VOL_HOT = 1.5
VOL_CALM = 1.2


def _f(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


#: 밸류 가드 문턱 — 적정가를 넘는 순간 막는다 (라운드 183).
#: 종전 +15% 에서 0% 로 당겼다. 블라인드 실측(매수권 58+ · 판정완료):
#:   적정가 이하        n 335 · 적중 59.4% · 원시수익 +0.238%  ← 유일한 양수
#:   적정가 소폭 초과    n  71 · 적중 53.5% · 원시수익 −0.890%
#:   적정가 초과(경고)   n  97 · 적중 54.6% · 원시수익 −0.652%
#: 새 숫자를 만들지 않았다 — 구역 판정이 이미 쓰는 경계(적정가 × 1.00)를
#: 그대로 재사용한다 (§2-6). ⚠️ 표본이 작다(71·97) — 방향은 개발 구간과
#: 같지만 그 사실을 밝힌다. 근거: docs/RESULT_R183_VALUE_GATE.md
_OVER_BLOCK_PCT = 0.0           # = entry_zone 의 fair_ref * 1.00 과 같다


#: 과열 지표 — **문턱은 한 벌만 둔다** (라운드 190).
#:
#: 종전에는 이 셋(95 / −10 / 75)이 `next_action` 과 `verdict_core` 에 각각
#: 적혀 있었다. 문턱은 우연히 같았지만 **결합 규칙이 달랐다** —
#:   verdict_core._overheated : 3중 2 이상
#:   next_action.hot          : 3중 1 이상
#: 그래서 지표 하나만 켜지면 배지는 '오늘 매수 가능', 본문은 '급등
#: 직후입니다 — 추격매수하지 마세요' 가 되어 **한 카드가 두 말을 했다**
#: (실측 5개 조합 중 3개 · `_probe/r190_heat.py`).
#:
#: 규칙을 바꾸는 것은 게이트를 바꾸는 일이라 측정 없이 하지 않는다 (§2).
#: 대신 **재는 것을 한 곳으로 모은다** — 두 판정자가 같은 입력을 읽고,
#: 각자의 규칙은 그대로 두되 화면이 그 근거(몇 개가 켜졌나)를 말한다.
_HEAT_KEYS = (('bb_position_pct', '볼린저', HOT_BB),
              ('williams_r_value', 'W%R', HOT_WR),
              ('rsi_value', 'RSI', HOT_RSI))


def heat_state(four_scores):
    """과열 지표를 **한 곳에서** 센다 (라운드 190).

    반환: {'hits': 켜진 개수, 'seen': 읽은 개수, 'parts': ['RSI 76', …]}

    ⚠️ 못 읽은 지표는 세지 않는다 — 결측을 과열로 취급하면 데이터 미수신이
      매수 차단으로 둔갑한다 (§3 · verdict_core 가 이미 쓰던 규칙).
    """
    fs = four_scores or {}
    hits, seen, parts = 0, 0, []
    for key, lbl, thr in _HEAT_KEYS:
        v = _f(fs.get(key))
        if v is None:
            continue
        seen += 1
        parts.append(f'{lbl} {v:.0f}')
        if v >= thr:
            hits += 1
    return {'hits': hits, 'seen': seen, 'parts': parts}


def value_block(four_scores):
    """
    밸류 게이트 판정 — **단일 구현** (라운드 185).

    반환 (code, reason):
      (None, None)       통과 — 막을 이유가 없다
      ('no_fair', …)     모델이 적정가를 거부(OUT_OF_DOMAIN) — 밸류 검증 불가
      ('over_fair', …)   현재가가 적정가를 초과 — 추격매수 위험

    ■ 왜 함수로 뺐나 (라운드 185)
      라운드 183 이 이 판정을 build() 안에만 걸었더니, 중앙 판정
      (verdict_core)이 그 존재를 모른 채 같은 종목을 '눌림목 매수 대기'로
      승격시켰다 — 사용자 화면에서 서진시스템(178320)이 배지 '장기 관찰'
      · 본문 "매수 후보에서 뺐습니다" 를 단 채 **'다음 거래일에 실제로
      손댈 수 있는 후보'** 칸에 올라온 원인이다. 판정자가 둘이면 반드시
      어긋난다 (§4) — 이제 next_action 과 verdict_core 가 **같은 함수**를
      읽는다. 문턱은 라운드 183 그대로다 — 새 숫자는 없다.

    ■ §3 — 못 잰 것과 모델이 거부한 것을 가른다
      시세·재무를 못 받아 계산을 못 한 경우(UNCALCULATED 등)는 막지
      않는다. 막으면 라운드 37(2,997종목 전멸)과 같은 실수다.
      막는 것은 모델이 값을 거부한 경우(OUT_OF_DOMAIN)뿐이다 —
      블라인드에서 그 구역이 최악이었다(n 1,536 · 수익 −1.237%).
    """
    fs = four_scores or {}
    if (_f(fs.get('displayed_fair_value')) is None
            and str(fs.get('fair_value_status') or '') == 'OUT_OF_DOMAIN'):
        return 'no_fair', '적정가 산출 불가 — 밸류 검증 없이 추천하지 않음'
    zone = str(fs.get('chase_buy_status') or fs.get('entry_zone') or '')
    if '크게 초과' in zone:
        return 'over_fair', '적정가 크게 초과 — 추격매수 위험'
    overshoot = _f(fs.get('fair_overshoot_pct'))
    if overshoot is not None and overshoot > _OVER_BLOCK_PCT:
        return ('over_fair',
                f'현재가가 적정가보다 {overshoot:+.1f}% 위 — 추격매수 위험')
    return None, None


def atr_pct(tech_df, price, window=14):
    """일 ATR 을 가격 대비 %로. tr 열이 있으면 그걸 쓰고 없으면 고가−저가."""
    p = _f(price)
    if tech_df is None or not p or len(tech_df) < 5:
        return None
    try:
        if 'tr' in tech_df.columns:
            v = _f(tech_df['tr'].tail(window).mean())
        else:
            v = _f((tech_df['high'].tail(window)
                    - tech_df['low'].tail(window)).mean())
    except Exception:
        return None
    if not v or v <= 0:
        return None
    return v / p * 100.0


def levels(tech_df, price):
    """지지·저항 후보를 실제 계산값에서만 뽑는다 — 없으면 안 넣는다."""
    out = {'supports': [], 'resists': []}
    p = _f(price)
    if tech_df is None or not p or len(tech_df) < 20:
        return out
    try:
        last = tech_df.iloc[-1]
    except Exception:
        return out
    for key, label in (('sma_20', '20일선'), ('sma_60', '60일선'),
                       ('bb_mid', '볼린저 중심선'), ('bb_lower', '볼린저 하단')):
        v = _f(last.get(key) if hasattr(last, 'get') else None)
        if v is None:
            continue
        (out['supports'] if v < p else out['resists']).append((v, label))
    try:
        lo10 = _f(tech_df['low'].tail(10).min())
        if lo10 is not None and lo10 < p:
            out['supports'].append((lo10, '최근 10일 저가'))
        hi20 = _f(tech_df['high'].tail(20).max())
        if hi20 is not None and hi20 > p:
            out['resists'].append((hi20, '최근 20일 고가'))
    except Exception:
        pass
    out['supports'].sort(key=lambda x: -x[0])   # 현재가에 가까운 지지부터
    out['resists'].sort(key=lambda x: x[0])     # 현재가에 가까운 저항부터
    return out


def _hot_headline(heat):
    """과열 머리말 — **근거를 숫자로** 적는다 (라운드 190).

    종전에는 지표가 하나만 켜져도 *"급등 직후입니다 — 지금은 추격매수하지
    마세요."* 라고 단정했다. 그런데 중앙 판정의 과열 규칙은 **3중 2** 라
    같은 카드의 배지가 '오늘 매수 가능' 으로 남았고, 한 카드가 두 말을
    했다(실측 5개 조합 중 3개).

    규칙은 안 바꾼다 (§2 — 게이트 변경은 측정이 필요하다). 대신 **몇 개가
    켜졌는지**를 문장에 적어, 배지와 본문이 서로 다른 잣대를 쓴다는 사실이
    화면에서 보이게 한다. 강한 단정을 근거에 맞게 낮추는 쪽이다.
    """
    h, n = heat.get('hits', 0), heat.get('seen', 0)
    if h >= 2:
        return f'급등 직후입니다 — 지금은 추격매수하지 마세요 (과열 지표 {h}/{n}).'
    return (f'과열 지표 {h}/{n} 이 켜졌습니다 — 추격매수는 피하세요 '
            f'(종합 판정은 위 결론을 따릅니다).')


def build(four_scores, tech_df, price, verdict=None):
    """
    관망 판단에 다음 조건을 붙이고, 괴리가 큰 종목을 추천에서 걸러 낸다.

    반환 (없는 값은 None — 지어내지 않는다):
      kind           buy_now / pullback / breakout / observe / blocked / no_data
      headline       "24,000원 부근에서 지지되면 사세요" 같은 한 줄
      conditions     [{kind, level, text}]
      gap_pct        현재가 대비 권장 매수가 (음수 = 아래)
      gap_band       즉시·근접 / 눌림목 대기 / 장기 관찰 / 괴리 과다
      atr_pct        일 ATR (가격 대비 %)
      band_edges     ATR 로 조정한 밴드 경계
      wait_days      예상 대기 거래일 (상한 60)
      reco_eligible  오늘의 추천에 넣어도 되는가
      exclude_reason 추천에서 뺐다면 그 이유
      alert          알림으로 저장할 조건 (없으면 None)
    """
    fs = four_scores or {}
    p = _f(price)
    out = {'kind': 'observe', 'headline': '', 'conditions': [],
           'gap_pct': None, 'gap_band': None, 'atr_pct': None,
           'band_edges': None, 'wait_days': None,
           'reco_eligible': False, 'exclude_reason': None, 'alert': None}

    if not p or tech_df is None or len(tech_df) < 20:
        out['kind'] = 'no_data'
        out['headline'] = '현재는 판단할 수 없습니다.'
        out['exclude_reason'] = '데이터 부족'
        return out

    a = atr_pct(tech_df, p)
    out['atr_pct'] = round(a, 2) if a else None
    scale = min(SCALE_MAX, max(SCALE_MIN, a / BASE_ATR_PCT)) if a else 1.0
    edges = tuple(round(b * scale, 1) for b in BANDS)
    out['band_edges'] = edges

    lv = levels(tech_df, p)
    sup = lv['supports'][0] if lv['supports'] else None
    res = lv['resists'][0] if lv['resists'] else None

    bb = _f(fs.get('bb_position_pct'))
    wr = _f(fs.get('williams_r_value'))
    rsi = _f(fs.get('rsi_value'))
    try:
        vr = _f(tech_df.iloc[-1].get('volume_ratio')) or 0.0
    except Exception:
        vr = 0.0
    # 규칙은 종전 그대로 **3중 1** 이다 — 세는 일만 한 곳으로 옮겼다.
    _heat = heat_state(fs)
    out['heat'] = _heat
    hot = _heat['hits'] >= 1

    def cond(kind, level, text):
        out['conditions'].append({'kind': kind, 'level': level, 'text': text})

    def support_cond():
        if sup:
            cond('support', sup[0],
                 f"{sup[0]:,.0f}원({sup[1]}) 부근에서 가격이 지지되고 "
                 f"거래량이 줄어들면 1차 분할매수를 검토하세요")

    def breakout_cond():
        if res:
            cond('breakout', res[0],
                 f"{res[0]:,.0f}원({res[1]})을 거래량과 함께 돌파한 뒤 "
                 f"다시 지지하면 진입할 수 있습니다")

    def cooldown_cond():
        bits = []
        if bb is not None:
            bits.append(f"볼린저 위치 {bb:.0f}%")
        if wr is not None:
            bits.append(f"Williams %R {wr:.0f}")
        if rsi is not None:
            bits.append(f"RSI {rsi:.0f}")
        cond('cooldown', None,
             ("과열이 풀려야 합니다 — " + ' · '.join(bits)
              + f" (볼린저 {COOL_BB:.0f}% 아래 · Williams %R {COOL_WR:.0f} 아래로)")
             if bits else "과열이 풀릴 때까지 기다리세요")

    def volume_cond():
        if vr and vr > VOL_HOT:
            cond('volume', None,
                 f"거래량이 20일 평균의 {vr:.1f}배입니다 — "
                 f"{VOL_CALM}배 아래로 가라앉아야 지지를 신뢰할 수 있습니다")

    # ── 거부권이 있으면 조건이 아니라 차단이다 ──────────────────────
    vetoes = (verdict or {}).get('vetoes') or []
    if vetoes:
        out['kind'] = 'blocked'
        out['headline'] = '지금은 매수를 차단합니다.'
        for v in vetoes[:2]:
            cond('veto', None, str(v))
        out['exclude_reason'] = '강제 매수 차단 조건'
        return out

    # 오늘의 진입가는 **실행 가능한 눌림가**(기준가 − 일변동성)를 쓴다.
    # 적정가 기반 값(value_floor_price)은 장기 가치 참고선이라 현재가와
    # 30~50% 벌어지는 일이 흔했다 — 그걸 오늘의 매수가로 쓰면 안 된다.
    # (라운드 25: 눌림가는 실전 체결률 79.3% · 평균 3.4거래일)
    # 라운드 53c — 바로 위 주석이 "그걸 오늘의 매수가로 쓰면 안 된다"인데
    # 정작 다음 줄이 그 값으로 폴백하고 있었다. 라운드 25 에서 결정만 하고
    # 호출부를 절반만 옮긴 흔적이다. 폴백을 뗀다 — 진입가가 없으면 아래에서
    # '진입 기준이 아직 없습니다'로 정직하게 말한다.
    rec = _f(fs.get('entry_pullback_price'))
    if rec is None:
        # 진입가가 없어도 **과열이면 그 사실이 먼저**다. 급등 직후에
        # '진입 기준이 없습니다'만 적으면 사용자는 뭘 하지 말아야 할지 모른다.
        if hot:
            out['kind'] = 'pullback'
            out['headline'] = _hot_headline(_heat)
            out['exclude_reason'] = '과열 — 추격 위험'
        else:
            out['kind'] = 'observe'
            out['headline'] = '진입 기준이 아직 없습니다.'
            out['exclude_reason'] = '유효 진입가 미산출'
        support_cond()
        breakout_cond()
        if hot:
            cooldown_cond()
        volume_cond()
        _w = [c for c in out['conditions']
              if c['kind'] in ('support', 'breakout') and c['level']]
        if _w:
            out['alert'] = {
                'kind': out['kind'],
                'levels': [{'kind': c['kind'], 'level': c['level']} for c in _w],
                'need_cooldown': hot,
                'need_volume_calm': bool(vr and vr > VOL_HOT),
                'vol_calm_ratio': VOL_CALM,
            }
        return out

    gap = (rec / p - 1.0) * 100.0            # 음수 = 현재가보다 아래
    out['gap_pct'] = round(gap, 1)
    g = abs(gap)
    if a and g > 0:
        out['wait_days'] = int(min(MAX_WAIT_DAYS, max(1, round((g / a) ** 2))))

    if gap >= 0 or g <= edges[0]:
        out['gap_band'] = '즉시·근접'
    elif g <= edges[1]:
        out['gap_band'] = '눌림목 대기'
    elif g <= edges[2]:
        out['gap_band'] = '장기 관찰'
    else:
        out['gap_band'] = '괴리 과다'

    # ── 밸류 가드 ───────────────────────────────────────────────────
    # 눌림 진입가는 변동성만 본다 — 밸류에이션을 전혀 모른다. 그래서 적정가를
    # 크게 초과한 종목도 "−5.8%면 살 만하다"로 보일 수 있다(달바글로벌 실측:
    # 현재가가 적정가보다 +69.5% 위인데 buy_now 로 나왔다).
    # 진입 위치 판정이 '크게 초과'면 오늘 살 종목이 아니다.
    #
    # ⚠️ 라운드 177 — 이 판정이 **조용히 꺼지는 자리**가 있었다.
    #   `entry_zone` 은 적정가와 **권장 매수가가 둘 다** 있어야 계산된다.
    #   권장 매수가가 None 이면 '판정 불가'가 되어 가드가 통째로 안 걸렸다
    #   (현대건설 +32.1% 실측). **못 잰 값(권장 매수가) 때문에 아는 값
    #   (적정가)까지 버리지 않는다** — 적정가만 있어도 넘침은 잰다.
    # ⚠️ 라운드 183 — 문턱을 +15% 에서 0% 로 당겼다 (`_OVER_BLOCK_PCT`
    #   주석의 블라인드 실측 근거 참조).
    # ⚠️ 라운드 185 — 판정 자체를 `value_block()` **한 곳**으로 올렸다.
    #   여기 인라인으로 있던 판정을 중앙 판정(verdict_core)이 몰라서,
    #   R183 이 뺀 종목이 '실제로 손댈 수 있는 후보' 칸에 다시 올라왔다.
    #   이 함수와 verdict_core 가 같은 함수를 읽는다 — 판정은 불변이다.
    zone = str(fs.get('chase_buy_status') or fs.get('entry_zone') or '')
    _overshoot = _f(fs.get('fair_overshoot_pct'))
    _vb, _vb_reason = value_block(fs)
    out['value_block'] = _vb

    # ⚠️ 라운드 182 — 사용자 지적: *"서진시스템은 펀더멘털 적정가가 안
    #   나오는데 왜 추천한 거야?"*
    #   위 가드는 **적정가가 있을 때만** 돈다. 적정가가 없으면 `_overshoot`
    #   이 None 이라 통째로 건너뛴다 — 그건 §3 대로다(못 잰 것으로 거르지
    #   않는다). 그런데 그때 화면에 남는 것은 **눌림 진입가 하나**이고,
    #   그 값은 이 파일 머리말이 적어 둔 대로 **변동성만 본다.**
    #   즉 밸류 검증을 한 번도 못 받은 가격이 '권장 매수가'로 나간다.
    #
    #   실측(서진시스템 178320 · 2026-08-27):
    #     displayed_fair_value  None (OUT_OF_DOMAIN · 모델이 −72% 괴리)
    #     화면                   권장 매수가 38,681원 · 1차 목표 43,813원
    #   두 사실이 같은 화면에 있지만 **멀리 떨어져 있어** 이어 읽히지 않는다.
    #
    #   → 거르지는 않는다. 대신 **그 카드에서** 밸류 검증을 못 했다고 말한다.
    #     '데이터 미수신'과 '모델이 거부'는 다른 말이라 갈라 적는다.
    _fv_status = str(fs.get('fair_value_status') or '')
    _no_fair = (_f(fs.get('displayed_fair_value')) is None)
    if _no_fair:
        if _fv_status == 'OUT_OF_DOMAIN':
            out['value_check'] = (
                '적정가를 내지 못해 **밸류 검증을 못 했습니다** — 우리 '
                '적정가 모델이 이 종목을 적용 범위 밖으로 봅니다(고배수·'
                '적자 구간). 아래 가격은 **변동성만으로** 계산한 값이라 '
                '싸고 비싼지는 판단하지 않았습니다.')
        else:
            out['value_check'] = (
                '적정가를 내지 못해 **밸류 검증을 못 했습니다** — 아래 '
                '가격은 **변동성만으로** 계산한 값이라 싸고 비싼지는 '
                '판단하지 않았습니다.')

    # ⚠️ 라운드 183 — **원장이 사용자 지적을 뒷받침했다.**
    #   사용자: *"적정가가 없는데 추천한 게 못 미덥다 — 개선해주던가
    #   추천 안 하던가. 적정가보다 현재가가 높은데 추천한 것도 이상하다."*
    #   라운드 182 에서 나는 §3 을 들어 고지만 붙였다. **그 방어가 틀렸다.**
    #   블라인드 실측에서 '판정 불가'(적정가 없음)가 **최악**이었고
    #   (n 1,536 · 적중 52.9% · 수익 −1.237%), 적정가 이하만 유일한 양수다.
    #   → 모델이 거부한 경우(OUT_OF_DOMAIN)와 적정가 초과를 막는다.
    #     판정과 근거는 `value_block()` 에 있다 (라운드 185 에서 단일화).
    #     근거: docs/RESULT_R183_VALUE_GATE.md
    if _vb == 'no_fair':
        out['kind'] = 'observe'
        out['exclude_reason'] = _vb_reason
        out['headline'] = (
            '펀더멘털 적정가를 내지 못해 오늘의 매수 후보에서 뺐습니다 '
            '— 우리 모델의 적용 범위 밖입니다(고배수·적자 구간).')
        cond('value', None,
             '적정가가 나오는 종목에서 고르세요 — 이 종목은 밸류 검증을 '
             '할 수 없어 싸고 비싼지 판단하지 못합니다')
        support_cond()
        breakout_cond()
        if hot:
            cooldown_cond()
        volume_cond()
        return out

    vfloor = _f(fs.get('value_floor_price'))
    if _vb == 'over_fair':
        out['kind'] = 'observe'
        out['exclude_reason'] = _vb_reason
        out['headline'] = '고평가 구간입니다 — 오늘의 매수 후보가 아닙니다.'
        if '크게 초과' not in zone and _overshoot is not None:
            # 왜 막혔는지 **숫자로** 말한다 — '판정 불가'로 얼버무리지 않는다
            out['headline'] = (
                f'현재가가 펀더멘털 적정가보다 {_overshoot:+.1f}% 높습니다 '
                f'— 오늘의 매수 후보가 아닙니다.')
        cond('value', vfloor,
             (f"장기 가치 기준 참고선은 {vfloor:,.0f}원입니다 — "
              f"오늘의 매수가가 아니라 위험 참고선입니다"
              if vfloor else "현재가가 적정가를 크게 넘었습니다"))
        support_cond()
        breakout_cond()
        if hot:
            cooldown_cond()
        volume_cond()
        return out

    # ── 바로 살 수 있는 경우 ────────────────────────────────────────
    if out['gap_band'] == '즉시·근접' and not hot:
        out['kind'] = 'buy_now'
        out['reco_eligible'] = True
        out['headline'] = f"{rec:,.0f}원 이하에서 분할매수할 수 있습니다."
        cond('price', rec,
             f"현재가 {p:,.0f}원은 권장 구간에 "
             f"{'들어와 있습니다' if gap >= 0 else '거의 닿았습니다'}")
        return out

    # ── 여기부터는 전부 '기다리는' 경우 ─────────────────────────────
    #    무엇을 기다리는지 반드시 적는다. 이게 이 모듈의 존재 이유다.
    if hot:
        out['kind'] = 'pullback'
        out['headline'] = _hot_headline(_heat)
        out['exclude_reason'] = '과열 — 추격 위험'
    elif out['gap_band'] == '눌림목 대기':
        out['kind'] = 'pullback'
        out['headline'] = (f"{sup[0]:,.0f}원 부근에서 지지 확인 후 사세요."
                           if sup else '눌림을 기다렸다가 사세요.')
        out['reco_eligible'] = True
    elif out['gap_band'] == '장기 관찰':
        out['kind'] = 'breakout' if res else 'observe'
        out['headline'] = (f"{res[0]:,.0f}원을 돌파한 뒤 지지하면 사세요."
                           if res else '방향이 정해질 때까지 지켜봅니다.')
        out['exclude_reason'] = '매수구간과 괴리 과다'
    else:
        out['kind'] = 'observe'
        out['headline'] = '오늘의 매수 후보가 아닙니다.'
        out['exclude_reason'] = '매수구간과 괴리 과다'
        cond('gap', rec,
             f"계산상 매수 기준은 {rec:,.0f}원이지만 현재가보다 "
             f"{g:.1f}% 낮아 단기 매매 후보로는 부적합합니다. "
             f"장기 관찰종목으로 전환합니다")

    support_cond()
    breakout_cond()
    if hot:
        cooldown_cond()
    volume_cond()
    if out['wait_days']:
        cond('wait', None,
             f"계산된 매수가까지는 변동성 기준 약 {out['wait_days']}거래일 "
             f"규모의 시간이 걸립니다")

    # ── 알림 조건 — 다시 검색하지 않아도 되게 저장한다 ──────────────
    watch = [c for c in out['conditions']
             if c['kind'] in ('support', 'breakout') and c['level']]
    if watch:
        out['alert'] = {
            'kind': out['kind'],
            'levels': [{'kind': c['kind'], 'level': c['level']} for c in watch],
            'need_cooldown': hot,
            'need_volume_calm': bool(vr and vr > VOL_HOT),
            'vol_calm_ratio': VOL_CALM,
        }
    return out
