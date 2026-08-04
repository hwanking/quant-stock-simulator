# -*- coding: utf-8 -*-
"""
국면별 게이트 — 성적을 화면에만 보여 주지 않고 **판단에 실제로 건다**.

사용자 지적: *"국면별 성과를 표시만 하지 말고 엔진에 실제 반영해."*
맞다. 지금까지 6칸 성적은 모델 성적 화면의 참고 자료였고, 매수 판단에는
아무 영향이 없었다.

■ 라운드 27b — 첫 판을 스스로 기각했다 (중요)
  처음에는 **블라인드만** 보고 구간을 정했다. "연습보다 실전"이 옳다고
  생각해서였다. 그런데 2단계 프로토콜로 검증하니 무너졌다:

    · 학습+검증만으로 정책을 다시 뽑으면 **6칸이 전부 '정상'** 이다.
      (하한 51.4~57.4% · n=224~833) — 국면별로 갈린다는 신호가 없다.
    · 그 정책을 블라인드에 적용하면 적중 +0.0%p · EV +0.000%p.
      사전등록 기준(적중 ≥+2%p AND EV>0) **기각**.
    · 블라인드로 만든 정책을 블라인드에서 재면 +2.9%p 가 나오지만,
      그건 만든 데이터로 채점한 값이라 **우위의 증거가 아니다**.

  무엇이 문제였나: '거친 하락 실전 12%'는 **n=16**이었다. 같은 칸이
  학습+검증에서는 n=224에 63.8%다. 16건짜리 표본 하나로 신규 매수를
  차단하고 있었다.

■ 고친 방식 — 표본을 갖췄을 때만 실전을 우선한다
  ① 기본 추정은 **전 구간 통합**(학습+검증+블라인드)의 Wilson 하한.
     표본이 커야 하한을 믿을 수 있다.
  ② 블라인드 표본이 MIN_N 이상일 때만 **실전 하한을 함께 보고 더 낮은
     쪽**을 택한다. 실전이 나쁘면 실전을 따르되, n=16 짜리 공포에는
     반응하지 않는다.
  ③ 규칙(구간·Wilson·보수성)은 그대로 살아 있다. 표본이 쌓여 어떤 칸이
     실제로 무너지면 그때 자동으로 제한이 걸린다.

■ 지금 데이터에서는 무엇이 걸리는가
  전 칸 하한이 51% 이상이라 **아무 제한도 걸리지 않는다.** 그게 맞는
  답이다. 걸 근거가 없는데 거는 것이 과적합이다.

■ 무엇을 거는가 (점수 상한 · 신뢰도 상한 · 비중 · 손절 배수)
  숫자를 손으로 정하지 않는다. **실전 Wilson 하한**을 구간으로 나눠 건다:
    하한 ≥ 50%  정상        상한 없음
    40~50%      주의        점수 상한 62 · 비중 0.7배
    30~40%      제한        점수 상한 55 · 비중 0.5배 · 손절 0.8배
    < 30%       강한 제한   점수 상한 45 · 신규 매수 차단 · 비중 0.3배
    표본 없음    판정 보류   점수 상한 55 · 신뢰도 상한 60 (모르면 낮춘다)

■ 매일 바꾸지 않는다
  성적은 케이스가 쌓일 때마다 갱신되지만, 게이트는 이 파일의 구간 규칙을
  통해서만 바뀐다. 규칙 자체를 바꾸려면 사전등록 라운드를 거친다.
"""
from __future__ import annotations

import json
import math
import os

BASE = os.path.dirname(os.path.abspath(__file__))
BREAKDOWN = os.path.join(BASE, '.portfolio', 'regime_breakdown.json')

VOL_CUT = 0.03
REG_KO = {'BULL': '상승', 'SIDEWAYS': '옆걸음', 'BEAR': '하락'}
VOL_KO = {'calm': '차분한', 'rough': '거친'}

#: 실전 Wilson 하한 구간 → 거는 제한. 손으로 정한 숫자가 아니라 구간 규칙이다.
BANDS = (
    (50.0, dict(level='정상', score_cap=None, conf_cap=None,
                size_mult=1.0, stop_mult=1.0, block_new=False)),
    (40.0, dict(level='주의', score_cap=62, conf_cap=None,
                size_mult=0.7, stop_mult=1.0, block_new=False)),
    (30.0, dict(level='제한', score_cap=55, conf_cap=75,
                size_mult=0.5, stop_mult=0.8, block_new=False)),
    (0.0, dict(level='강한 제한', score_cap=45, conf_cap=60,
               size_mult=0.3, stop_mult=0.7, block_new=True)),
)
#: 실전 표본이 아예 없는 칸 — 모르면 낮춘다
NO_SAMPLE = dict(level='판정 보류', score_cap=55, conf_cap=60,
                 size_mult=0.5, stop_mult=0.9, block_new=False)
MIN_N = 30


def wilson_low(hit_pct, n, z=1.96):
    """작은 표본에서 단일 적중률을 그대로 믿지 않기 위한 하한."""
    if not n or hit_pct is None:
        return None
    p = float(hit_pct) / 100.0
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (c - m) / d) * 100.0


def cell_key(regime, vol20):
    """국면 6칸 키 — 지수 방향 × 종목 변동성."""
    if not regime or vol20 is None:
        return None
    return f"{regime}|{'rough' if float(vol20) >= VOL_CUT else 'calm'}"


def cell_ko(key):
    if not key or '|' not in key:
        return None
    rg, vk = key.split('|', 1)
    return f"{VOL_KO.get(vk, vk)} {REG_KO.get(rg, rg)}"


def _load():
    try:
        with open(BREAKDOWN, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


SPLITS = ('train', 'valid', 'blind')


def _pool(cell):
    """전 구간 통합 (n·적중건수 합산). 표본이 커야 하한을 믿을 수 있다."""
    n = k = 0
    for s in SPLITS:
        d = cell.get(s) or {}
        cn = int(d.get('n') or 0)
        ch = d.get('hit')
        if cn and ch is not None:
            n += cn
            k += round(cn * float(ch) / 100.0)
    return n, k


def policy(regime, vol20, breakdown=None):
    """
    이 국면에 무엇을 걸 것인가.

    ■ 하한을 두 개 본다 (라운드 27b)
      pooled_low  전 구간 통합 하한 — 기본 추정
      blind_low   실전 하한 — **표본이 MIN_N 이상일 때만** 함께 본다
      effective_low = 둘 중 더 낮은 쪽 (실전이 나쁘면 실전을 따른다)

      블라인드 n=16 짜리 값으로 차단하지 않는다. 그렇게 했다가 2단계
      검증에서 기각당했다(모듈 상단 참조).

    반환 (없는 값은 None — 지어내지 않는다):
      cell · cell_ko · pooled_n/hit/low · blind_n/hit/low · effective_low ·
      level · score_cap · conf_cap · size_mult · stop_mult · block_new · why
    """
    out = dict(cell=None, cell_ko=None, pooled_n=None, pooled_hit=None,
               pooled_low=None, blind_n=None, blind_hit=None, blind_low=None,
               effective_low=None, basis=None, level='판정 보류',
               score_cap=None, conf_cap=None, size_mult=1.0, stop_mult=1.0,
               block_new=False, why='')
    key = cell_key(regime, vol20)
    if not key:
        out['why'] = '국면을 판정하지 못해 국면별 제한을 걸지 않습니다.'
        return out
    d = breakdown if breakdown is not None else _load()
    cell = ((d.get('cells6') or {}).get(key) or {})
    out['cell'], out['cell_ko'] = key, cell_ko(key)

    pn, pk = _pool(cell)
    bl = cell.get('blind') or {}
    bn, bhit = int(bl.get('n') or 0), bl.get('hit')
    out['blind_n'], out['blind_hit'] = bn, bhit
    if pn:
        out['pooled_n'] = pn
        out['pooled_hit'] = round(pk / pn * 100.0, 1)
        out['pooled_low'] = round(wilson_low(out['pooled_hit'], pn), 1)
    if bn >= MIN_N and bhit is not None:
        out['blind_low'] = round(wilson_low(bhit, bn), 1)

    if not pn:
        out.update(NO_SAMPLE)
        out['basis'] = '표본 없음'
        out['why'] = (f"{out['cell_ko']} 국면은 **표본이 없습니다**. "
                      f"모르는 국면이므로 점수와 신뢰도에 상한을 겁니다.")
        return out

    cands = [(out['pooled_low'], '통합 표본')]
    if out['blind_low'] is not None:
        cands.append((out['blind_low'], '실전 표본'))
    low, basis = min(cands, key=lambda x: x[0])
    out['effective_low'], out['basis'] = low, basis
    for edge, rule in BANDS:
        if low >= edge:
            out.update(rule)
            break

    if bn and bn < MIN_N:
        note = (f" 실전 표본은 {bn}건뿐이라 판단 근거로 쓰지 않았습니다"
                f" (기준 {MIN_N}건)")
    elif out['blind_low'] is not None:
        note = (f" 실전만 보면 {bhit:.0f}%(n={bn}, 하한 "
                f"{out['blind_low']:.0f}%)입니다")
    else:
        note = " 실전 표본이 없습니다"
    out['why'] = (
        f"{out['cell_ko']} 국면의 통합 적중률은 {out['pooled_hit']:.0f}% "
        f"(n={pn}, 95% 하한 {out['pooled_low']:.0f}%)입니다.{note}. "
        f"판단 근거는 {basis}(하한 {low:.0f}%). "
        + {'정상': '국면별 추가 제한은 걸지 않습니다.',
           '주의': f"점수 상한 {out['score_cap']}점 · 비중 "
                   f"{out['size_mult']:.1f}배를 적용합니다.",
           '제한': f"점수 상한 {out['score_cap']}점 · 신뢰도 상한 "
                   f"{out['conf_cap']} · 비중 {out['size_mult']:.1f}배 · "
                   f"손절 {out['stop_mult']:.1f}배를 적용합니다.",
           '강한 제한': f"**신규 매수를 차단**합니다 (점수 상한 "
                    f"{out['score_cap']}점 · 비중 {out['size_mult']:.1f}배).",
           }.get(out['level'], ''))
    return out


def apply_caps(score, confidence, pol):
    """점수·신뢰도에 국면 상한을 씌운다. 올리지는 않는다 — 상한이다."""
    s, c = score, confidence
    if pol.get('score_cap') is not None and s is not None:
        s = min(s, pol['score_cap'])
    if pol.get('conf_cap') is not None and c is not None:
        c = min(c, pol['conf_cap'])
    return s, c
