# -*- coding: utf-8 -*-
"""
라운드 3 승격 판정 — 완화 거부권(calibrated)이 운영 모델을 이길 수 있는가.

사전등록 (측정 전에 고정한다 — 결과를 보고 기준을 고치면 그건 실험이 아니다):
  후보  : QUANT_VETO_NET_MODE=calibrated 로 생성한 .portfolio/virtual_graded.jsonl
  운영  : .portfolio/virtual_graded_OPERATING.jsonl (기존 strict)
  구간  : 학습 <2025-07-01 · 검증 ~2026-01-31 · 블라인드 >=2026-02-01
          블라인드는 **보고 전용**이며 승격 판단에 쓰지 않는다 (§58).

승격 6조건 — 하나라도 어기면 승격하지 않는다 (전부 검증 구간 기준):
  1. 매수 신호율이 늘어난다               (후보 > 운영, 실용성 개선이 이 라운드의 목적)
  2. 매수권 적중률이 크게 나빠지지 않는다  (하락 3.0%p 이내)
  3. 매수권 비용 차감 후 기대수익이 나빠지지 않는다 (하락 0.30%p 이내)
  4. 손익비(PF)가 나빠지지 않는다          (하락 0.10 이내)
  5. 평균 최대낙폭(MAE)이 나빠지지 않는다  (악화 0.50%p 이내)
  6. 전체 표본 적중률이 나빠지지 않는다    (하락 1.0%p 이내)

승격하지 않으면 운영 원장을 원상 복구한다 (후보를 그냥 두면 조용히 채택된다).
"""
from __future__ import annotations

import io
import json
import os
import sys

try:                       # 라운드 103 — 객체를 갈아끼우지 않는다
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:          # noqa: BLE001
    pass
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PF = os.path.join(BASE, '.portfolio')

CAND = os.path.join(PF, 'virtual_graded.jsonl')
OPER = os.path.join(PF, 'virtual_graded_OPERATING.jsonl')

VALID_END = '2026-01-31'
BLIND_START = '2026-02-01'
TRAIN_END = '2025-07-01'
BUY_SCORE = 58.0          # 채택된 확장 매수권 하한 (라운드 2)
COST_PCT = 0.30           # 왕복 거래비용 가정 (%)

RULES = [
    ('신호율 증가', lambda o, c: c['signal_rate'] > o['signal_rate']),
    ('매수권 적중률 -3.0%p 이내',
     lambda o, c: c['buy_hit'] >= o['buy_hit'] - 3.0),
    ('매수권 비용후 -0.30%p 이내',
     lambda o, c: c['buy_net'] >= o['buy_net'] - 0.30),
    ('손익비 -0.10 이내', lambda o, c: c['buy_pf'] >= o['buy_pf'] - 0.10),
    ('평균 최대낙폭 +0.50%p 이내',
     lambda o, c: c['buy_mae'] <= o['buy_mae'] + 0.50),
    ('전체 적중률 -1.0%p 이내', lambda o, c: c['all_hit'] >= o['all_hit'] - 1.0),
]


def load(path):
    rows = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def _d(r):
    return str(r.get('t_ref') or r.get('date') or r.get('signal_date') or '')


def _score(r):
    for k in ('score', 'total_score', 'final_score'):
        if r.get(k) is not None:
            try:
                return float(r[k])
            except Exception:
                pass
    return None


def _ret(r):
    for k in ('realized_return', 'ret_pct', 'perf', 'return_pct'):
        if r.get(k) is not None:
            try:
                return float(r[k])
            except Exception:
                pass
    return None


def _hit(r):
    if r.get('hit') is not None:
        return bool(r['hit'])
    v = _ret(r)
    return (v is not None and v > 0)


def _mae(r):
    for k in ('mae', 'max_drawdown', 'mdd'):
        if r.get(k) is not None:
            try:
                return abs(float(r[k]))
            except Exception:
                pass
    return None


def metrics(rows, lo, hi):
    """구간 내 지표. buy_* 는 매수권(58점+) 부분집합."""
    sub = [r for r in rows if lo <= _d(r) <= hi and _score(r) is not None]
    if not sub:
        return None
    buy = [r for r in sub if _score(r) >= BUY_SCORE]
    rets = [_ret(r) for r in buy if _ret(r) is not None]
    win = [v for v in rets if v > 0]
    loss = [v for v in rets if v <= 0]
    maes = [_mae(r) for r in buy if _mae(r) is not None]
    gain, pain = sum(win), abs(sum(loss))
    return {
        'n': len(sub), 'buy_n': len(buy),
        'signal_rate': 100.0 * len(buy) / len(sub),
        'all_hit': 100.0 * sum(1 for r in sub if _hit(r)) / len(sub),
        'buy_hit': (100.0 * sum(1 for r in buy if _hit(r)) / len(buy)
                    if buy else 0.0),
        'buy_ret': (sum(rets) / len(rets)) if rets else 0.0,
        'buy_net': ((sum(rets) / len(rets)) - COST_PCT) if rets else 0.0,
        'buy_pf': (gain / pain) if pain > 0 else (99.0 if gain > 0 else 0.0),
        'buy_mae': (sum(maes) / len(maes)) if maes else 0.0,
    }


def show(tag, m):
    if not m:
        print(f'  {tag}: 표본 없음')
        return
    print(f"  {tag}: 전체 {m['n']}건 · 매수권 {m['buy_n']}건 "
          f"(신호율 {m['signal_rate']:.2f}%) · 매수권 적중 {m['buy_hit']:.1f}% · "
          f"비용후 {m['buy_net']:+.2f}% · PF {m['buy_pf']:.2f} · "
          f"MAE {m['buy_mae']:.2f}% · 전체 적중 {m['all_hit']:.1f}%")


def main():
    if not os.path.exists(CAND) or not os.path.exists(OPER):
        print('원장 없음 — 후보 또는 운영 파일을 찾지 못했습니다.')
        return 2
    cand, oper = load(CAND), load(OPER)
    print(f'후보 {len(cand)}건 · 운영 {len(oper)}건\n')

    print('■ 검증 구간 (승격 판단에 쓰는 유일한 구간)')
    ov = metrics(oper, TRAIN_END, VALID_END)
    cv = metrics(cand, TRAIN_END, VALID_END)
    show('운영', ov)
    show('후보', cv)

    if not (ov and cv):
        print('\n판정 불가 — 검증 표본 부족')
        return 2

    print('\n■ 승격 6조건')
    passed = []
    for name, fn in RULES:
        ok = bool(fn(ov, cv))
        passed.append(ok)
        print(f"  [{'통과' if ok else '탈락'}] {name}")

    print('\n■ 블라인드 (보고 전용 — 판단에 쓰지 않는다)')
    show('운영', metrics(oper, BLIND_START, '2099-12-31'))
    show('후보', metrics(cand, BLIND_START, '2099-12-31'))

    verdict = all(passed)
    print('\n' + '=' * 66)
    if verdict:
        print('판정: 승격 — 6조건 전부 통과. 후보를 운영 원장으로 채택합니다.')
    else:
        print('판정: 기각 — 조건 미달. 운영 원장(strict)을 그대로 유지합니다.')
        print('     후보 원장은 폐기하고 운영본을 원상 복구해야 합니다.')
    print('=' * 66)
    return 0 if verdict else 1


if __name__ == '__main__':
    sys.exit(main())
