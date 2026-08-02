# -*- coding: utf-8 -*-
"""
가늠 AI — '무엇을 가늠했는지' 를 사용자 말로 설명하는 계층.

사용자 요구: 이름만 AI 처럼 보이게 하지 말고 실제로 무엇을 쟀는지 쉽게 보여라.
필수 항목 10가지가 모두 있어야 한다 (없으면 '산출 불가'로 표시하고 지어내지
않는다):
  상승 가능성 · 하락 가능성 · 기간 내 미도달 가능성 · 기대 가격 범위 ·
  예상 보유기간 · 과거 유사 사례 수 · 실제 표본외 적중률 · 신뢰구간 ·
  가장 큰 위험요인 · 현재 판단의 한계

계산은 여기서 새로 하지 않는다. 이미 엔진이 낸 값을 **모아서 번역**할 뿐이다
— 화면용 숫자를 따로 만들면 그 순간 두 개의 진실이 생긴다.
"""
from __future__ import annotations

import json
import math
import os

BASE = os.path.dirname(os.path.abspath(__file__))
NA = '산출 불가'


def _wilson(hit: int, n: int, z: float = 1.96):
    if not n:
        return None, None
    p = hit / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return round(100.0 * (c - m) / d, 1), round(100.0 * (c + m) / d, 1)


def _calib():
    try:
        with open(os.path.join(BASE, '.portfolio', 'calibration.json'),
                  encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _band_for(score, calib):
    for b in (calib.get('bands') or []):
        if b.get('lo') is not None and b['lo'] <= score <= b['hi']:
            return b
    return None


def _confidence_word(n, spread):
    """신뢰도를 낱말로 — 숫자만 주면 사용자가 해석을 떠안는다."""
    if not n:
        return '판단 불가', '비슷한 과거 사례를 찾지 못했습니다.'
    if n < 30:
        return '낮음', f'비슷한 사례가 {n}건뿐이라 우연일 수 있습니다.'
    if spread is not None and spread > 20:
        return '보통', '사례는 충분하지만 결과가 넓게 흩어져 있습니다.'
    if n < 100:
        return '보통', f'사례 {n}건 — 방향은 보이지만 확정하기엔 이릅니다.'
    return '높음', f'사례 {n}건에서 일관된 결과가 나왔습니다.'


def build(four_scores: dict, sim_res: dict, verdict: dict,
          price: float | None = None) -> dict:
    """
    엔진 결과 → 가늠 AI 카드에 들어갈 값 묶음.

    모든 항목은 '있으면 값, 없으면 NA' 다. 빈 칸을 그럴듯한 추정으로 채우지
    않는다 — 그게 이 제품이 지키는 유일한 선이다.
    """
    fs, sim, vd = four_scores or {}, sim_res or {}, verdict or {}
    calib = _calib()

    n = sim.get('match_count')
    up = sim.get('predicted_probability')
    tp = sim.get('tp_first_prob')
    sl = sim.get('sl_first_prob')

    # 상승·하락·미도달 — 합이 100이 되게 정규화하지 않는다.
    # tp/sl 은 '먼저 닿을 확률'이고 나머지가 '기간 내 미도달'이다.
    undecided = None
    if tp is not None and sl is not None:
        undecided = max(0.0, round(100.0 - float(tp) - float(sl), 1))

    score = int(fs.get('final_action_score') or vd.get('score') or 0)
    band = _band_for(score, calib)
    lo = hi = None
    oos = None
    if band and band.get('n'):
        oos = band.get('hit_rate')
        lo, hi = _wilson(int(band.get('hit') or 0), int(band['n']))

    spread = None
    if sim.get('p10_perf') is not None and sim.get('p90_perf') is not None:
        spread = float(sim['p90_perf']) - float(sim['p10_perf'])
    conf_word, conf_why = _confidence_word(n, spread)

    # 기대 가격 범위 — 10~90분위를 현재가에 얹는다 (평균 한 점은 오해를 부른다)
    price_lo = price_hi = None
    if price and sim.get('p10_perf') is not None:
        price_lo = price * (1 + float(sim['p10_perf']) / 100.0)
        price_hi = price * (1 + float(sim['p90_perf']) / 100.0)

    # 가장 큰 위험요인 — 이미 계산된 거부권·상한 사유에서 고른다 (새로 만들지 않음)
    risk = None
    if vd.get('vetoes'):
        risk = str(vd['vetoes'][0])
    elif fs.get('gate_reason'):
        # gate_reason 은 상한 사유를 ' / ' 로 이어붙인 목록이다. 글자수로
        # 자르면 낱말 한가운데서 끊긴 문장이 화면에 남는다 — 가장 먼저 걸린
        # 사유 하나만 고른다. 그게 '가장 큰' 위험요인이기도 하다.
        _first = str(fs['gate_reason']).split(' / ')[0].strip()
        risk = _first if _first else None
    elif sim.get('mdd') is not None:
        risk = f"비슷한 사례에서 보유 중 평균 {abs(float(sim['mdd'])):.1f}% 까지 밀렸습니다"

    # 현재 판단의 한계 — 조건에 따라 실제로 해당하는 것만 담는다
    limits = []
    if not n:
        limits.append('비슷한 과거 사례를 찾지 못해 확률을 계산하지 못했습니다.')
    elif n < 30:
        limits.append(f'비슷한 사례가 {n}건뿐입니다. 확률로 보기엔 적습니다.')
    if (band and (band.get('n') or 0) < 100):
        limits.append('이 점수대의 표본외 검증 사례가 100건에 못 미칩니다.')
    if not sim.get('probabilities_shown', True):
        limits.append(str(sim.get('blind_reason')
                          or '표본 부족으로 확률을 표시하지 않습니다.'))
    if fs.get('market_regime_label') and '하락' in str(fs['market_regime_label']):
        limits.append('하락 국면에서는 연습과 실전 성적이 크게 엇갈립니다. '
                      '이 구간의 판단은 특히 신뢰하지 마세요.')
    if not limits:
        limits.append('미래를 맞히는 도구가 아니라 과거를 세어 본 결과입니다.')

    return {
        'up_prob': up,
        'down_prob': (round(100.0 - float(up), 1) if up is not None else None),
        'tp_first': tp, 'sl_first': sl, 'undecided': undecided,
        'price_low': price_lo, 'price_high': price_hi,
        'hold_days': sim.get('optimal_holding_period_days')
                     or sim.get('horizon_days') or 20,
        'hold_label': sim.get('optimal_holding_period_str'),
        'sample_n': n,
        'oos_hit': oos,
        'oos_n': (band or {}).get('n'),
        'ci_low': lo, 'ci_high': hi,
        'confidence': conf_word, 'confidence_why': conf_why,
        'risk': risk,
        'limits': limits,
        'score': score,
    }


def sentence(g: dict) -> str:
    """한 문장 요약 — 사용자에게 제일 먼저 보이는 줄."""
    n, oos = g.get('sample_n'), g.get('oos_hit')
    if not n:
        return ('비슷한 과거 사례를 찾지 못했습니다. 지금은 확률로 말할 수 '
                '없어 판단을 보류합니다.')
    tp = g.get('tp_first')
    if tp is None:
        return (f'비슷한 과거 사례 {n:,}건을 찾았지만, 표본이 조건을 채우지 못해 '
                '확률은 표시하지 않습니다.')
    hit = int(round(n * float(tp) / 100.0))
    base = (f'과거 비슷한 사례 {n:,}건 중 {hit:,}건에서 목표 방향이 먼저 '
            f'나타났습니다.')
    tail = f" 다만 신뢰도는 '{g.get('confidence')}'입니다 — {g.get('confidence_why')}"
    if oos is not None and g.get('oos_n'):
        tail += (f" 이 점수대의 실제 성적은 {oos:.0f}% "
                 f"(안 본 사례 {g['oos_n']:,}건 기준)입니다.")
    return base + tail
