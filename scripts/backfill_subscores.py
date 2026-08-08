# -*- coding: utf-8 -*-
"""
기존 원장에 하위점수를 채운다 (라운드 50).

■ 왜 필요한가
  calibration_lab 기록부에 q_stock_quality 등을 추가했지만, 체크포인트가
  이미 끝난 (종목, 날짜)를 건너뛴다. 그래서 **새로 도는 건에만** 필드가
  생기고 기존 60,462건은 비어 있다. 그 상태로 분석하면 신규분만 보는
  편향된 부분표본이 된다 (라운드 44-1b 에서 똑같은 사고를 냈다).

■ 무엇을 하나
  기존 행을 읽어 같은 (종목, 기준일)로 리플레이를 다시 돌리고, **채점
  결과는 건드리지 않고** 하위점수 필드만 덧붙인다.

    · 이미 채워진 행은 건너뛴다 (재실행 안전)
    · 결과 필드(success·return_pct·outcome…)는 **읽지도 쓰지도 않는다**
    · 중간 저장 — 언제 끊어도 이어서 돈다

■ 범위
  기본값은 **개발 구간의 매수권(58+)** 만. 순위 분석이 그 구간에서만
  이뤄지기 때문이고, 봉인된 블라인드는 애초에 읽지 않는다.

    C:/Python314/python.exe scripts/backfill_subscores.py [--limit N] [--all]
"""
import io
import json
import os
import sys
import time
import warnings

warnings.filterwarnings('ignore')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

import bitemporal_engine as be                               # noqa: E402
import quant_indicators as qi                                # noqa: E402

P = os.path.join(PROJ, '.portfolio')
LEDGER = os.path.join(P, 'virtual_graded.jsonl')
PATCH = os.path.join(P, 'subscore_patch.jsonl')
THR = 58.0
SEALED = 'blind'

#: 채울 필드 — 라운드 50b 에서 7/7 실재를 확인한 것만
FIELDS = (('q_stock_quality', 'stock_quality_score'),
          ('q_trading_timing', 'trading_timing_score'),
          ('q_risk_safety', 'risk_safety_score'),
          ('q_opportunity', 'opportunity_score'),
          ('q_execution', 'execution_score'),
          ('q_confidence', 'analysis_confidence'),
          ('q_strategy_quality', 'strategy_quality_score'))


def load_done():
    done = set()
    if os.path.exists(PATCH):
        with open(PATCH, encoding='utf-8') as f:
            for ln in f:
                try:
                    r = json.loads(ln)
                    done.add((r['ticker'], r['date']))
                except Exception:                            # noqa: BLE001
                    continue
    return done


def main():
    limit = 10 ** 9
    if '--limit' in sys.argv:
        limit = int(sys.argv[sys.argv.index('--limit') + 1])
    want_all = '--all' in sys.argv

    rows = []
    with open(LEDGER, encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                try:
                    rows.append(json.loads(ln))
                except Exception:                            # noqa: BLE001
                    pass
    print(f'원장 {len(rows):,}건')

    todo = []
    for r in rows:
        if not want_all:
            if r.get('split') == SEALED:
                continue
            if float(r.get('score') or 0) < THR:
                continue
        if r.get('q_stock_quality') is not None:
            continue                      # 이미 채워짐
        todo.append((str(r.get('ticker')), str(r.get('date'))[:10]))
    todo = sorted(set(todo))
    done = load_done()
    todo = [x for x in todo if x not in done]
    print(f'채울 대상 {len(todo):,}건 '
          f'({"전체" if want_all else "개발 구간 매수권만"}) · '
          f'이미 완료 {len(done):,}건')
    if not todo:
        print('채울 것이 없다.')
        return 0

    q = qi.QuantIndicatorsEngine()
    eng = be.BitemporalEngine()
    t0, ran, fail = time.time(), 0, 0
    with open(PATCH, 'a', encoding='utf-8') as out:
        for tk, d in todo:
            if ran >= limit:
                print(f'  한도 {limit}건 도달 — 이어서 실행 가능')
                break
            try:
                snap = q.run_full_pipeline(tk, d, b_engine=eng,
                                           rho_cutoff=0.80)
                fs = snap['four_scores']
                patch = {'ticker': tk, 'date': d}
                for lk, ek in FIELDS:
                    patch[lk] = fs.get(ek)
                patch['sector'] = (snap.get('val_eval') or {}).get('sector')
                out.write(json.dumps(patch, ensure_ascii=False) + '\n')
                out.flush()
                ran += 1
                if ran % 25 == 0:
                    el = time.time() - t0
                    print(f'  {ran}/{len(todo)}건 · {el:,.0f}s · '
                          f'건당 {el / ran:.1f}s · 실패 {fail}')
            except Exception as exc:                         # noqa: BLE001
                fail += 1
                if fail <= 5:
                    print(f'  [실패] {tk} @ {d} — {type(exc).__name__}')
    print(f'\n완료 {ran:,}건 · 실패 {fail}건')
    print(f'저장: {PATCH}')
    print('  원장 병합은 merge 단계에서 한다 — 채점 결과는 건드리지 않는다.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
