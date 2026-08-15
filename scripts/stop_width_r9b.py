# -*- coding: utf-8 -*-
"""
라운드 9b — 손절 폭이 진짜 문제인가 (세 구간 전부에서 확인).

라운드 9에서 나온 것:
  현행 목표 5% · 손절 3% 는 검증 구간에서 **목표 도달 21.5% vs 손절 54.3%**.
  손절이 목표보다 2.5배 자주 걸린다. 원장의 실패 1위가 '노이즈 손절'인 이유가
  이것이다 — 3% 는 한국 주식의 20일 변동폭 안에서 그냥 지나가는 폭이다.

질문: 손절을 넓히면 **세 구간 모두에서** 나아지는가, 아니면 검증 구간만 좋은가.
      (한 구간에서만 좋으면 그건 그 기간의 장세다 — 라운드 4에서 배운 교훈)

사전등록:
  후보 손절 : 3 · 4 · 5 · 7%   (목표는 현행 5% 고정 — 한 번에 하나만 바꾼다)
  채택 조건 : 학습·검증·블라인드 **세 구간 모두**에서 현행(3%) 대비
              ① 비용 차감 후 기대값이 낫고 ② 손절 발생률이 낮아질 것
  실패 시   : 채택하지 않는다.

⚠️ 측정의 한계: 봉 안의 순서를 모르므로 목표·손절 동시 도달은 손절로 본다.
   손절을 넓히면 '동시 도달' 이 늘어 이 가정의 불리함도 커진다 —
   즉 넓은 손절이 여기서 이기면 실제로는 더 이길 가능성이 높다.
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
LEDGER = os.path.join(BASE, '.portfolio', 'virtual_graded.jsonl')
OUT = os.path.join(BASE, '.portfolio', 'stop_policy.json')

COST_PCT = 0.30
BUY_SCORE = 58
TARGET = 5.0
BASELINE_STOP = 3.0
STOPS = [3.0, 4.0, 5.0, 7.0]


def load():
    out = []
    with open(LEDGER, encoding='utf-8') as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get('mfe_pct') is None or r.get('mae_pct') is None:
                continue
            if (r.get('score') or 0) < BUY_SCORE:
                continue
            out.append(r)
    return out


def sim(rows, target, stop):
    n = len(rows)
    if not n:
        return None
    hits = st = 0
    rets = []
    for r in rows:
        mfe, mae = float(r['mfe_pct']), abs(float(r['mae_pct']))
        rt, rs = mfe >= target, mae >= stop
        if rt and not rs:
            hits += 1
            rets.append(target)
        elif rs:
            st += 1
            rets.append(-stop)          # 동시 도달도 손절 (보수 가정)
        else:
            rets.append(float(r.get('close_return_pct')
                              or r.get('return_pct') or 0.0))
    win = [v for v in rets if v > 0]
    loss = [v for v in rets if v <= 0]
    g, p = sum(win), abs(sum(loss))
    return {'n': n, 'hit': 100.0 * hits / n, 'stop_rate': 100.0 * st / n,
            'net': sum(rets) / n - COST_PCT,
            'pf': (g / p) if p > 0 else (99.0 if g else 0.0)}


def main():
    rows = load()
    by = {s: [r for r in rows if r.get('split') == s]
          for s in ('train', 'valid', 'blind')}
    print(f"매수권 사례 {len(rows):,}건 · 목표 {TARGET:.0f}% 고정\n")

    base = {s: sim(by[s], TARGET, BASELINE_STOP) for s in by}
    print(f'■ 현행 기준선 (손절 {BASELINE_STOP:.0f}%)')
    for s, ko in (('train', '학습'), ('valid', '검증'), ('blind', '블라인드')):
        m = base[s]
        print(f"  {ko:5s} n={m['n']:4d} 목표도달 {m['hit']:5.1f}% · "
              f"손절 {m['stop_rate']:5.1f}% · 비용후 {m['net']:+.2f}% · "
              f"PF {m['pf']:.2f}")

    print('\n■ 손절 폭별 — 세 구간 동시 비교')
    print('  손절     학습(비용후/손절률)     검증                블라인드')
    results = {}
    for stp in STOPS:
        r3 = {s: sim(by[s], TARGET, stp) for s in by}
        results[stp] = r3
        cells = []
        for s in ('train', 'valid', 'blind'):
            m = r3[s]
            cells.append(f"{m['net']:+6.2f}% / {m['stop_rate']:4.1f}%")
        print(f"  {stp:3.0f}%   " + '   '.join(cells))

    print(f'\n■ 채택 판정 — 세 구간 모두에서 현행({BASELINE_STOP:.0f}%)보다 나은가')
    winners = []
    for stp in STOPS:
        if stp == BASELINE_STOP:
            continue
        ok_all = True
        detail = []
        for s, ko in (('train', '학습'), ('valid', '검증'), ('blind', '블라인드')):
            m, b = results[stp][s], base[s]
            d_net = m['net'] - b['net']
            d_stop = m['stop_rate'] - b['stop_rate']
            ok = (d_net > 0 and d_stop < 0)
            ok_all = ok_all and ok
            detail.append(f"{ko} 기대값 {d_net:+.2f}%p · 손절률 {d_stop:+.1f}%p "
                          f"{'O' if ok else 'X'}")
        print(f"  손절 {stp:.0f}%: " + ' | '.join(detail))
        if ok_all:
            winners.append(stp)

    print('\n' + '=' * 74)
    if winners:
        best = max(winners, key=lambda s: results[s]['valid']['net'])
        print(f"판정: 채택 — 손절 {BASELINE_STOP:.0f}% → {best:.0f}%")
        print("  이유: 3% 는 20일 변동폭 안에서 그냥 지나가는 폭이라 "
              "방향이 맞아도 먼저 털린다. 넓히면 버티는 만큼 목표에 닿는다.")
        for s, ko in (('train', '학습'), ('valid', '검증'), ('blind', '블라인드')):
            m = results[best][s]
            print(f"  {ko:5s} 목표도달 {m['hit']:5.1f}% · 손절 {m['stop_rate']:5.1f}% "
                  f"· 비용후 {m['net']:+.2f}% · PF {m['pf']:.2f}")
        with open(OUT, 'w', encoding='utf-8') as f:
            json.dump({'adopted': True, 'target_pct': TARGET,
                       'stop_pct': best, 'baseline_stop_pct': BASELINE_STOP,
                       'rr': TARGET / best,
                       'splits': {s: results[best][s] for s in by},
                       'baseline': {s: base[s] for s in by},
                       'note': '동시 도달은 손절로 보수 가정 — 실제는 이보다 낫다'},
                      f, ensure_ascii=False, indent=1)
        print(f'\n손절 정책 저장: {OUT}')
        return 0
    print('판정: 채택 없음 — 세 구간을 모두 개선한 손절 폭이 없습니다.')
    print('=' * 74)
    return 1


if __name__ == '__main__':
    sys.exit(main())
