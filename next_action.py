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
    hot = bool((bb is not None and bb >= HOT_BB)
               or (wr is not None and wr >= HOT_WR)
               or (rsi is not None and rsi >= HOT_RSI))

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
    rec = _f(fs.get('entry_pullback_price')) or _f(
        fs.get('recommended_buy_price'))
    if rec is None:
        # 진입가가 없어도 **과열이면 그 사실이 먼저**다. 급등 직후에
        # '진입 기준이 없습니다'만 적으면 사용자는 뭘 하지 말아야 할지 모른다.
        if hot:
            out['kind'] = 'pullback'
            out['headline'] = '급등 직후입니다 — 지금은 추격매수하지 마세요.'
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
    zone = str(fs.get('chase_buy_status') or fs.get('entry_zone') or '')
    over_value = ('크게 초과' in zone)
    vfloor = _f(fs.get('value_floor_price'))
    if over_value:
        out['kind'] = 'observe'
        out['exclude_reason'] = '적정가 크게 초과 — 추격매수 위험'
        out['headline'] = '고평가 구간입니다 — 오늘의 매수 후보가 아닙니다.'
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
        out['headline'] = '급등 직후입니다 — 지금은 추격매수하지 마세요.'
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
