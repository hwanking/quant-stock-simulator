# -*- coding: utf-8 -*-
"""
손절 운용 규칙 대결 — 실패 손실 2위 '노이즈 손절(-992%p)' 을 겨냥한 사전등록 검증.

후보 (문헌·실무 표준에서 사전 정의 — 원장을 보고 만들지 않는다):
  A. 고정 손절 (현행): 진입 시 정한 손절선 고정
  B. 본전 스탑 (breakeven): 목표 거리의 50% 도달 시 손절선을 진입가로 상향
     (실무 표준 트레이드 매니지먼트 — 이익을 손실로 되돌리지 않는다)
  C. 추적손절 (trailing): 최고가 갱신 시 손절선을 같은 폭으로 따라 올림
     (Wilder ATR trailing 계열)

규율:
  · 봉 내부 순서는 보수적으로 가정한다 — 같은 봉에서 손절선과 트리거가 함께
    닿으면 손절이 먼저다 (유리한 가정 금지)
  · 선정은 학습+검증만: 비용후 기대값 최대 & 손실률이 현행보다 낮을 것.
    블라인드는 승자 확정 후 보고 전용.
  · 결과 분류: 목표 도달 / 손실 청산 / 본전·이익 청산(무승부 — 성공으로 세지
    않는다) / 미도달. 분모를 명시한다.
"""
import json
import os
import sys

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

import bitemporal_engine as be
import prediction_log as plog

COST = 0.55   # 왕복 비용 보수 추정 (%)


def split_of(d):
    d = str(d)
    return 'blind' if d >= '2026-02-01' else ('valid' if d >= '2025-07-01' else 'train')


def simulate(bars, entry, tp, sl, rule):
    """봉 경로에 손절 규칙 적용. 반환 (분류, 수익률%). 보수적 봉내 순서."""
    stop_eff = sl
    be_armed = False
    peak = entry
    trail_d = entry - sl                     # 트레일 폭 = 초기 손절 폭
    trigger = entry + 0.5 * (tp - entry)     # 본전 스탑 트리거 (목표 거리 50%)
    for hi, lo, _c in bars:
        # 1) 손절선 먼저 (보수적)
        if lo <= stop_eff:
            ret = (stop_eff / entry - 1.0) * 100.0
            if stop_eff >= entry:
                return ('EXIT_EVEN_OR_WIN', ret)
            return ('STOP_LOSS', ret)
        # 2) 목표
        if hi >= tp:
            return ('TARGET', (tp / entry - 1.0) * 100.0)
        # 3) 규칙별 손절선 갱신 (다음 봉부터 적용)
        if rule == 'B' and not be_armed and hi >= trigger:
            stop_eff = max(stop_eff, entry)
            be_armed = True
        elif rule == 'C':
            peak = max(peak, hi)
            stop_eff = max(stop_eff, peak - trail_d)
    last_close = bars[-1][2]
    return ('OPEN', (last_close / entry - 1.0) * 100.0)


def main():
    rows = []
    with open(os.path.join(PROJ, ".portfolio", "virtual_predictions.jsonl"),
              encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get('target') and r.get('stop') and r.get('price'):
                rows.append(r)
    print(f"시뮬레이션 대상 {len(rows)}건")

    eng = be.BitemporalEngine()
    cache = {}
    sims = {'A': [], 'B': [], 'C': []}
    for r in rows:
        tk = r['ticker']
        if tk not in cache:
            try:
                cache[tk], _ = eng.generate_synthetic_bitemporal_data(
                    symbol=tk, start_date='2020-01-01', end_date=None)
            except Exception:
                cache[tk] = None
        pdf = cache[tk]
        if pdf is None:
            continue
        bars = plog._bars_after(pdf, r['date'], r.get('horizon_days') or 20)
        if not bars:
            continue
        for rule in ('A', 'B', 'C'):
            cls, ret = simulate(bars, float(r['price']), float(r['target']),
                                float(r['stop']), rule)
            sims[rule].append({'cls': cls, 'ret': ret, 'split': split_of(r['date']),
                               'score': r.get('score', 0)})

    def report(rule, splits, label=""):
        sub = [s for s in sims[rule] if s['split'] in splits]
        n = len(sub)
        tgt = sum(1 for s in sub if s['cls'] == 'TARGET')
        loss = sum(1 for s in sub if s['cls'] == 'STOP_LOSS')
        even = sum(1 for s in sub if s['cls'] == 'EXIT_EVEN_OR_WIN')
        openn = sum(1 for s in sub if s['cls'] == 'OPEN')
        rets = [s['ret'] for s in sub]
        wins = sum(x for x in rets if x > 0)
        losses = -sum(x for x in rets if x < 0)
        decided = tgt + loss
        hit = tgt / decided * 100 if decided else 0
        avg = float(np.mean(rets)) if rets else 0
        print(f"  {rule}{label:<14} n={n:<5} 목표 {tgt:<4} 손실 {loss:<4} "
              f"본전/이익청산 {even:<4} 미도달 {openn:<3} | "
              f"적중 {hit:5.1f}% (분모=목표+손실 {decided}) "
              f"평균 {avg:+5.2f}% 비용후 {avg-COST:+5.2f}% "
              f"PF {wins/max(losses,0.01):4.2f} 손실률 {loss/n*100:4.1f}%")
        return {'hit': hit, 'after_cost': avg - COST, 'loss_rate': loss / n * 100,
                'n': n, 'decided': decided}

    print()
    print("=" * 110)
    print("학습+검증 (선정 구간 — 블라인드 미사용)")
    print("=" * 110)
    tv = {}
    for rule, label in [('A', ' 고정(현행)'), ('B', ' 본전 스탑'), ('C', ' 추적손절')]:
        tv[rule] = report(rule, ('train', 'valid'), label)

    # 사전 등록 선정 기준: 비용후 최대 & 손실률 < 현행 & 판정 표본 충분
    best, why = 'A', "현행 유지 (개선 후보 없음)"
    for rule in ('B', 'C'):
        if (tv[rule]['after_cost'] > tv[best]['after_cost']
                and tv[rule]['loss_rate'] < tv['A']['loss_rate']
                and tv[rule]['decided'] >= 300):
            best, why = rule, "비용후 기대값 개선 + 손실률 감소"
    print(f"\n  ★ 선정: {best} — {why}")

    print()
    print("=" * 110)
    print("블라인드 재현 (승자 확정 후 보고 전용)")
    print("=" * 110)
    for rule, label in [('A', ' 고정(현행)'), (best, ' 선정 규칙')] if best != 'A' else [('A', ' 고정(현행)')]:
        report(rule, ('blind',), label)

    # 고신뢰(65+) 구간에서 선정 규칙 성과
    print()
    print("=" * 110)
    print("고신뢰(65+) 구간 — 선정 규칙 적용 시")
    print("=" * 110)
    for rule in dict.fromkeys(['A', best]):
        sub = [s for s in sims[rule] if s['score'] >= 65]
        if not sub:
            continue
        tgt = sum(1 for s in sub if s['cls'] == 'TARGET')
        loss = sum(1 for s in sub if s['cls'] == 'STOP_LOSS')
        even = sum(1 for s in sub if s['cls'] == 'EXIT_EVEN_OR_WIN')
        dec = tgt + loss
        print(f"  {rule}: n={len(sub)} 목표 {tgt} 손실 {loss} 본전 {even} → "
              f"적중 {tgt/dec*100 if dec else 0:.1f}% (분모 {dec})")


if __name__ == "__main__":
    main()
