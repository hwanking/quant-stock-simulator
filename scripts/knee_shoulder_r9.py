# -*- coding: utf-8 -*-
"""
라운드 9 — "머리·발이 아니라 무릎에서" 를 데이터로 정의한다.

사용자 요구: 100점짜리 도구를 만들 필요는 없다. 손실은 있을 수 있고 최대한
줄이는 것이다. 대신 **확률로 몇 %를 먹을지** 정해야 한다 — 최고점(머리)도
최저점(발)도 노리지 않고 무릎에서 사서 어깨에서 판다.

이 스크립트가 답하는 질문은 하나다:
  목표수익률을 몇 %로 잡아야 '도달 확률 × 수익' 이 가장 커지는가?

원리: 목표를 높이면 먹는 폭은 커지지만 닿을 확률이 떨어진다. 둘의 곱이
기대값이고, 그 곱이 최대가 되는 지점이 **어깨**다. 손절은 반대로 너무 좁으면
잡음에 털리고(노이즈 손절 — 우리 원장의 실패 1위) 너무 넓으면 한 번에 크게
잃는다.

측정 방법 (원장의 실제 경로를 다시 걷는다):
  각 사례는 20거래일 동안의 최고 상승폭(MFE)과 최대 하락폭(MAE)을 갖고 있다.
  목표 T% · 손절 S% 를 가정하면 그 사례의 결과를 이렇게 판정할 수 있다.
    · MFE >= T 이고 MAE > -S      → 목표 도달 (성공, +T)
    · MAE <= -S 이고 MFE < T      → 손절 (실패, -S)
    · 둘 다 닿음                  → 어느 쪽이 먼저인지 알 수 없다 → 보수적으로
                                    손절 처리 (불리한 쪽으로 가정한다)
    · 둘 다 못 닿음               → 기간 종료 시점 수익률로 청산

  ⚠️ 이것은 근사다. 봉 안의 순서를 모르기 때문에 동시 도달을 손절로 본다.
     그래서 여기서 나오는 기대값은 **실제보다 보수적**이다 — 낙관 쪽으로
     틀리는 것보다 낫다.

사전등록 (측정 전 고정):
  후보 목표 : 2 · 3 · 4 · 5 · 7 · 10 · 15%
  후보 손절 : 2 · 3 · 4 · 5 · 7%
  대상      : 매수권(58점+) 사례만 — 실제로 사용자가 받는 신호
  선정 기준 : 검증 구간에서 비용 차감 후 기대값 최대. 단 아래를 모두 만족.
    · 목표 도달률 30% 이상 (너무 안 닿는 목표는 실용성이 없다)
    · 손익비(PF) 1.0 이상
    · 평균 최대낙폭 8% 이내 (버틸 수 있어야 한다)
  확인      : 블라인드에서도 기대값 양수여야 채택. 아니면 채택하지 않는다.
"""
from __future__ import annotations

import io
import json
import math
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(BASE, '.portfolio', 'virtual_graded.jsonl')
OUT = os.path.join(BASE, '.portfolio', 'target_policy.json')

COST_PCT = 0.30
BUY_SCORE = 58

TARGETS = [2.0, 3.0, 4.0, 5.0, 7.0, 10.0, 15.0]
STOPS = [2.0, 3.0, 4.0, 5.0, 7.0]

MIN_HIT_RATE = 30.0
MIN_PF = 1.0
MAX_MAE = 8.0


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


def simulate(rows, target, stop):
    """
    목표 T·손절 S 를 가정하고 원장 경로를 다시 판정한다.
    반환: 도달률·기대값(비용후)·PF·평균 MAE·표본
    """
    n = len(rows)
    if not n:
        return None
    hits = stops_ = closes = 0
    rets = []
    maes = []
    for r in rows:
        mfe = float(r['mfe_pct'])
        mae = abs(float(r['mae_pct']))
        maes.append(mae)
        reach_t = mfe >= target
        reach_s = mae >= stop
        if reach_t and not reach_s:
            hits += 1
            rets.append(target)
        elif reach_s and not reach_t:
            stops_ += 1
            rets.append(-stop)
        elif reach_t and reach_s:
            # 같은 기간에 둘 다 닿았다 — 순서를 모르므로 불리하게 가정한다
            stops_ += 1
            rets.append(-stop)
        else:
            closes += 1
            rets.append(float(r.get('close_return_pct')
                              or r.get('return_pct') or 0.0))
    win = [v for v in rets if v > 0]
    loss = [v for v in rets if v <= 0]
    gain, pain = sum(win), abs(sum(loss))
    return {
        'n': n, 'target': target, 'stop': stop,
        'hit_rate': 100.0 * hits / n,
        'stop_rate': 100.0 * stops_ / n,
        'close_rate': 100.0 * closes / n,
        'exp_gross': sum(rets) / n,
        'exp_net': sum(rets) / n - COST_PCT,
        'pf': (gain / pain) if pain > 0 else (99.0 if gain else 0.0),
        'avg_mae': sum(maes) / len(maes),
        'rr': (target / stop) if stop else 0.0,
    }


def main():
    rows = load()
    by = {s: [r for r in rows if r.get('split') == s]
          for s in ('train', 'valid', 'blind')}
    print(f"매수권(58점+) 사례 {len(rows):,}건 — 학습 {len(by['train']):,} · "
          f"검증 {len(by['valid']):,} · 블라인드 {len(by['blind']):,}\n")

    print('■ 현행 설정의 위치부터 확인 (참고)')
    cur = simulate(by['valid'], 5.0, 3.0)
    if cur:
        print(f"  목표 5% / 손절 3%: 도달 {cur['hit_rate']:.1f}% · "
              f"손절 {cur['stop_rate']:.1f}% · 비용후 기대값 {cur['exp_net']:+.2f}%")

    print('\n■ 목표별 도달률 — 목표를 높일수록 닿을 확률이 떨어진다 (검증 구간)')
    print('  목표    도달률    평균MFE 대비')
    mfes = sorted(float(r['mfe_pct']) for r in by['valid'])
    for t in TARGETS:
        rate = 100.0 * sum(1 for v in mfes if v >= t) / max(1, len(mfes))
        print(f"  {t:4.0f}%   {rate:5.1f}%")

    print('\n■ 목표 × 손절 격자 — 검증 구간 비용 차감 후 기대값')
    grid = []
    for t in TARGETS:
        for s in STOPS:
            m = simulate(by['valid'], t, s)
            if m:
                grid.append(m)
    # 표로 보여 준다 (행=목표, 열=손절)
    head = '  목표\\손절 ' + ''.join(f"{s:>8.0f}%" for s in STOPS)
    print(head)
    for t in TARGETS:
        row = [m for m in grid if m['target'] == t]
        cells = ''.join(f"{next(x['exp_net'] for x in row if x['stop'] == s):>+8.2f}"
                        for s in STOPS)
        print(f"  {t:6.0f}%  {cells}")

    print('\n■ 사전등록 기준을 통과한 조합 (도달률 30%+ · PF 1.0+ · MAE 8% 이내)')
    ok = [m for m in grid
          if m['hit_rate'] >= MIN_HIT_RATE and m['pf'] >= MIN_PF
          and m['avg_mae'] <= MAX_MAE]
    ok.sort(key=lambda m: -m['exp_net'])
    if not ok:
        print('  없음 — 어떤 목표·손절 조합도 기준을 통과하지 못했습니다.')
        best = max(grid, key=lambda m: m['exp_net'])
        print(f"  참고: 기대값 최대는 목표 {best['target']:.0f}% / "
              f"손절 {best['stop']:.0f}% ({best['exp_net']:+.2f}%)이지만 "
              f"도달률 {best['hit_rate']:.1f}% · PF {best['pf']:.2f} 로 기준 미달.")
        return 1
    for m in ok[:6]:
        print(f"  목표 {m['target']:.0f}% / 손절 {m['stop']:.0f}% "
              f"(손익비 {m['rr']:.1f}:1) — 도달 {m['hit_rate']:.1f}% · "
              f"손절 {m['stop_rate']:.1f}% · 비용후 {m['exp_net']:+.2f}% · "
              f"PF {m['pf']:.2f} · MAE {m['avg_mae']:.1f}%")

    win = ok[0]
    print(f"\n■ 블라인드 확인 — 목표 {win['target']:.0f}% / 손절 {win['stop']:.0f}%")
    b = simulate(by['blind'], win['target'], win['stop'])
    t_ = simulate(by['train'], win['target'], win['stop'])
    if t_:
        print(f"  학습    n={t_['n']:4d} 도달 {t_['hit_rate']:.1f}% "
              f"비용후 {t_['exp_net']:+.2f}% PF {t_['pf']:.2f}")
    if not b:
        print('  블라인드 표본 없음 — 채택 보류')
        return 1
    print(f"  블라인드 n={b['n']:4d} 도달 {b['hit_rate']:.1f}% "
          f"비용후 {b['exp_net']:+.2f}% PF {b['pf']:.2f}")

    adopt = b['exp_net'] > 0
    print('\n' + '=' * 70)
    if adopt:
        print(f"판정: 채택 — 목표 {win['target']:.0f}% · 손절 {win['stop']:.0f}% "
              f"(손익비 {win['rr']:.1f}:1)")
        print(f"  무릎에서 사서 어깨에서 판다는 뜻: 목표 도달 확률 "
              f"{win['hit_rate']:.0f}% 를 받아들이고 {win['target']:.0f}% 에서 "
              "나온다. 더 높은 목표는 기대값이 오히려 줄어든다.")
    else:
        print('판정: 채택 없음 — 블라인드 기대값이 음수입니다.')
    print('=' * 70)

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump({
            'generated_from': 'virtual_graded.jsonl (매수권 58점+)',
            'method': '원장의 MFE·MAE 로 목표·손절 도달을 재판정 '
                      '(동시 도달은 손절로 보수 가정)',
            'adopted': bool(adopt),
            'target_pct': win['target'], 'stop_pct': win['stop'],
            'rr': win['rr'],
            'valid': win, 'blind': b, 'train': t_,
            'grid': grid,
        }, f, ensure_ascii=False, indent=1)
    print(f'\n목표 정책 저장: {OUT}')
    return 0 if adopt else 1


if __name__ == '__main__':
    sys.exit(main())
