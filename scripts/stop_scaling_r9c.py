# -*- coding: utf-8 -*-
"""
라운드 9c — 손절이 좁은 진짜 이유: 보유기간 스케일링 누락.

라운드 9b 에서 손절 3%→7% 가 세 구간 모두를 개선한다는 실측이 나왔다.
그런데 "7% 로 바꾸자" 는 결론은 위험하다 — 종목마다 변동성이 다른데 고정
퍼센트를 쓰면 조용한 종목은 너무 넓고 급한 종목은 여전히 좁다.

엔진 산식을 보니 원인이 분명하다:

    base_risk = 현재가 × max(3%, 일간변동성_20일 × 2.0)

**일간** 표준편차에 2를 곱해 **20일** 보유의 손절로 쓴다. 랜덤워크에서
기간 T 의 표준편차는 σ_일간 × √T 이므로, 20일이면 σ × 4.47 이 1σ 다.
지금 쓰는 2σ_일간은 실제로는 **0.45σ_20일** — 즉 20일 안에 그냥 지나가는
폭이다. 방향이 맞아도 먼저 털린다.

이 스크립트는 세 가지를 한다:
  ① 원장에서 실제 변동성 분포와 현행 손절 폭을 잰다
  ② √기간 스케일링을 적용하면 손절 폭이 얼마가 되는지 계산한다
  ③ 그 폭으로 다시 판정했을 때 세 구간 성과를 비교한다

사전등록:
  후보 배수 k : 0.8 · 1.0 · 1.25 · 1.5 (손절거리 = σ_일간 × √20 × k)
  채택 조건   : 학습·검증·블라인드 **세 구간 모두** 현행 대비
                기대값 개선 + 손절률 감소
  실패 시     : 채택하지 않는다.
"""
from __future__ import annotations

import io
import json
import math
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
HORIZON = 20
CUR_FLOOR = 3.0          # 현행 하한 %
CUR_MULT = 2.0           # 현행 일간 배수
TARGET_R = 0.7           # 1차 목표 = 손절거리 × 0.7 (현행 산식 유지)
KS = [0.8, 1.0, 1.25, 1.5]


def load():
    out = []
    with open(LEDGER, encoding='utf-8') as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if (r.get('mfe_pct') is None or r.get('mae_pct') is None
                    or r.get('vol20') is None):
                continue
            if (r.get('score') or 0) < BUY_SCORE:
                continue
            out.append(r)
    return out


def cur_stop_pct(r):
    return max(CUR_FLOOR, 100.0 * float(r['vol20']) * CUR_MULT)


def scaled_stop_pct(r, k):
    return 100.0 * float(r['vol20']) * math.sqrt(HORIZON) * k


def sim(rows, stop_fn, target_ratio=TARGET_R):
    """손절 폭이 사례마다 다르므로 목표도 사례마다 손절×0.7 로 잡는다."""
    n = len(rows)
    if not n:
        return None
    hits = st = 0
    rets, stops = [], []
    for r in rows:
        s = max(0.5, stop_fn(r))          # 0.5% 미만 손절은 현실적이지 않다
        t = s * target_ratio
        stops.append(s)
        mfe, mae = float(r['mfe_pct']), abs(float(r['mae_pct']))
        rt, rs = mfe >= t, mae >= s
        if rt and not rs:
            hits += 1
            rets.append(t)
        elif rs:
            st += 1
            rets.append(-s)               # 동시 도달은 손절 (보수 가정)
        else:
            rets.append(float(r.get('close_return_pct')
                              or r.get('return_pct') or 0.0))
    win = [v for v in rets if v > 0]
    loss = [v for v in rets if v <= 0]
    g, p = sum(win), abs(sum(loss))
    return {'n': n, 'hit': 100.0 * hits / n, 'stop_rate': 100.0 * st / n,
            'net': sum(rets) / n - COST_PCT,
            'pf': (g / p) if p > 0 else (99.0 if g else 0.0),
            'avg_stop': sum(stops) / len(stops)}


def main():
    rows = load()
    by = {s: [r for r in rows if r.get('split') == s]
          for s in ('train', 'valid', 'blind')}
    print(f"매수권 사례 {len(rows):,}건\n")

    vols = sorted(100.0 * float(r['vol20']) for r in rows)
    med = vols[len(vols) // 2]
    print('■ 변동성과 손절 폭의 실제 관계')
    print(f"  일간 변동성 중앙값 {med:.2f}% "
          f"(하위25% {vols[len(vols)//4]:.2f}% · 상위25% {vols[3*len(vols)//4]:.2f}%)")
    print(f"  현행 손절: max({CUR_FLOOR:.0f}%, 일간 {CUR_MULT:.0f}σ) = "
          f"{max(CUR_FLOOR, med*CUR_MULT):.2f}%  ← 중앙값 종목 기준")
    print(f"  20일 1σ  : 일간 {med:.2f}% × √{HORIZON} = "
          f"{med*math.sqrt(HORIZON):.2f}%")
    print(f"  → 현행 손절은 20일 기준 {max(CUR_FLOOR, med*CUR_MULT)/(med*math.sqrt(HORIZON)):.2f}σ "
          "다. 1σ 도 안 되는 폭이라 방향이 맞아도 먼저 털린다.")

    cur = {s: sim(by[s], cur_stop_pct) for s in by}
    print('\n■ 현행 산식')
    for s, ko in (('train', '학습'), ('valid', '검증'), ('blind', '블라인드')):
        m = cur[s]
        print(f"  {ko:5s} n={m['n']:4d} 평균손절 {m['avg_stop']:4.1f}% · "
              f"목표도달 {m['hit']:5.1f}% · 손절 {m['stop_rate']:5.1f}% · "
              f"비용후 {m['net']:+.2f}% · PF {m['pf']:.2f}")

    print(f'\n■ √{HORIZON} 스케일링 적용 — 손절거리 = 일간σ × √{HORIZON} × k')
    res = {}
    for k in KS:
        res[k] = {s: sim(by[s], lambda r, kk=k: scaled_stop_pct(r, kk))
                  for s in by}
        cells = []
        for s in ('train', 'valid', 'blind'):
            m = res[k][s]
            cells.append(f"{m['net']:+6.2f}% / {m['stop_rate']:4.1f}%")
        print(f"  k={k:4.2f} (평균손절 {res[k]['valid']['avg_stop']:4.1f}%)  "
              + '   '.join(cells))

    print('\n■ 채택 판정 — 세 구간 모두 개선')
    winners = []
    for k in KS:
        ok_all, detail = True, []
        for s, ko in (('train', '학습'), ('valid', '검증'), ('blind', '블라인드')):
            m, b = res[k][s], cur[s]
            d_net, d_stop = m['net'] - b['net'], m['stop_rate'] - b['stop_rate']
            ok = (d_net > 0 and d_stop < 0)
            ok_all = ok_all and ok
            detail.append(f"{ko} {d_net:+.2f}%p/{d_stop:+.1f}%p "
                          f"{'O' if ok else 'X'}")
        print(f"  k={k:4.2f}: " + ' | '.join(detail))
        if ok_all:
            winners.append(k)

    print('\n' + '=' * 74)
    if not winners:
        print('판정: 채택 없음 — 세 구간을 모두 개선한 배수가 없습니다.')
        print('=' * 74)
        return 1
    best = max(winners, key=lambda k: res[k]['valid']['net'])
    print(f"판정: 채택 — 손절거리 = 일간σ × √{HORIZON} × {best}")
    print(f"  변경 전: max({CUR_FLOOR:.0f}%, 일간σ × {CUR_MULT:.0f})  "
          "— 보유기간이 산식에 없었다")
    print(f"  변경 후: 일간σ × √{HORIZON} × {best}  "
          "— 20일 보유의 실제 변동폭을 반영한다")
    for s, ko in (('train', '학습'), ('valid', '검증'), ('blind', '블라인드')):
        m = res[best][s]
        print(f"  {ko:5s} 평균손절 {m['avg_stop']:4.1f}% · 목표도달 {m['hit']:5.1f}% "
              f"· 손절 {m['stop_rate']:5.1f}% · 비용후 {m['net']:+.2f}% "
              f"· PF {m['pf']:.2f}")
    print('=' * 74)

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump({
            'adopted': True,
            'method': 'stop_distance = daily_sigma * sqrt(horizon) * k',
            'k': best, 'horizon': HORIZON,
            'target_of_stop': TARGET_R,
            'previous': {'floor_pct': CUR_FLOOR, 'daily_mult': CUR_MULT},
            'splits': {s: res[best][s] for s in by},
            'baseline': {s: cur[s] for s in by},
            'caveat': '동시 도달은 손절로 보수 가정 — 실제는 이보다 낫다',
        }, f, ensure_ascii=False, indent=1)
    print(f'\n손절 정책 저장: {OUT}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
