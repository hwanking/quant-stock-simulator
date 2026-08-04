# -*- coding: utf-8 -*-
"""
라운드 17 — 실행 레벨 격자 탐색: 얼마에 팔고, 어디서 끊을 것인가.

════════════════════════════════════════════════════════════════════════
사전등록 (측정 전에 고정한다. 결과를 보고 내리지 않는다)
════════════════════════════════════════════════════════════════════════

■ 묻는 것
  현행은 목표 = 손절 × 0.7 이다(손익비 0.70:1). 승률 58%로도 돈을 못 버는
  이유가 여기 있다고 라운드 15 에서 봤다. 그럼 목표·손절을 **각각** 어떻게
  잡아야 하는가. 라운드 15 는 목표만 건드렸다(k 스윕). 이번엔 격자로 본다.

■ 후보 격자
  목표 배수 a ∈ {0.5, 0.7, 1.0, 1.3, 1.6, 2.0}   (현행 목표폭 × a)
  손절 배수 b ∈ {0.6, 0.8, 1.0, 1.25, 1.5}       (현행 손절폭 × b)
  현행은 (a=1.0, b=1.0). 총 30개 조합.

■ 채택 기준 — **전부** 충족해야 한다
  ① 실전(blind) 기대값 > 0  … 최악 경계 기준
  ② 검증(valid) 기대값 > 0  … 최악 경계 기준
  ③ 실전 목표도달률 ≥ 20%   … 20% 미만이면 '거의 안 팔리는 목표'다
  ④ 검증·실전 **양쪽 모두** 현행(1.0,1.0)보다 기대값이 높을 것
  ⑤ 종목 홀드아웃에서도 실전 기대값 > 0  (본 적 없는 종목에서 재현)
  ⑥ 표본 n ≥ 30 (해당 구간)
  하나라도 미달이면 **기각**한다. 사후에 기준을 낮추지 않는다.

■ 판정 모호분 처리 — 이게 이 연구의 정직성이 걸린 지점
  원장의 mfe/mae 는 '얼마나 갔나'만 알고 '어느 쪽이 먼저'는 모른다.
  다만 원래 판정(outcome)으로 **단조성 연역**이 가능하다:
    · 원래 TARGET 이고, 목표를 더 가깝게·손절을 더 멀게 → 반드시 TARGET
    · 원래 STOP  이고, 손절을 더 가깝게·목표를 더 멀게 → 반드시 STOP
    · 원래 OPEN  이고, 목표·손절 둘 다 더 멀게        → 반드시 OPEN
  연역이 안 되고 mfe/mae 가 둘 다 닿았으면 **모호**다.
  모호분은 최선(전부 TARGET)·최악(전부 STOP) 두 경계를 다 계산하고,
  **채택 판정은 최악 경계로만** 한다. 좋은 쪽을 고르면 연구가 아니라 희망이다.

■ 거래비용
  왕복 0.41% (현행 엔진과 같은 값). 모든 결과에서 차감한다.

■ 미리 밝히는 한계
  오늘은 하락 국면인데 하락 국면 실전 표본은 거친 15건·차분한 0건이다.
  이 연구가 무엇을 찾아내든 **오늘 상황에서 검증된 것은 아니다.**
  국면별 결론은 라운드 18 에서 측정 가능한 3칸에 대해서만 낸다.
════════════════════════════════════════════════════════════════════════
"""
import io
import json
import os
import sys
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LED = os.path.join(BASE, '.portfolio', 'virtual_graded.jsonl')
OUT = os.path.join(BASE, '.portfolio', 'exec_levels_r17.json')

BUY = 58                    # 매수권 문턱 — 화면의 국면 표와 같은 기준
COST = 0.41                 # 왕복 거래비용 %
A_GRID = [0.5, 0.7, 1.0, 1.3, 1.6, 2.0]
B_GRID = [0.6, 0.8, 1.0, 1.25, 1.5]
MIN_N = 30
MIN_REACH = 20.0            # 실전 목표도달률 하한 %


def load():
    out = []
    with open(LED, encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except Exception:
                pass
    return out


def prep(r):
    """한 사례를 재시뮬레이션에 필요한 최소 형태로 — 못 쓰면 None."""
    p, t, s = r.get('price'), r.get('target'), r.get('stop')
    mfe, mae = r.get('mfe_pct'), r.get('mae_pct')
    o = r.get('outcome')
    if not (p and t and s) or mfe is None or mae is None:
        return None
    if o not in ('TARGET', 'STOP', 'OPEN'):
        return None
    TP = (t / p - 1) * 100          # 현행 목표폭 %
    SP = (1 - s / p) * 100          # 현행 손절폭 %
    if TP <= 0 or SP <= 0:
        return None
    return {
        'TP': TP, 'SP': SP, 'O': o,
        'mfe': float(mfe), 'mae': abs(float(mae)),
        'close': float(r.get('close_return_pct') or 0.0),
        'split': r['split'], 'cohort': r.get('cohort'),
        'regime': r.get('regime'), 'vol20': r.get('vol20'),
        'entry_zone': r.get('entry_zone'), 'score': r.get('score'),
    }


def resim(c, tp, sp):
    """
    목표 tp% · 손절 sp% 로 바꿨을 때의 결과.

    반환: ('TARGET'|'STOP'|'OPEN'|'AMB', best_ret, worst_ret)
    AMB 면 best 는 목표달성, worst 는 손절 기준이다.
    """
    O, TP, SP, mfe, mae = c['O'], c['TP'], c['SP'], c['mfe'], c['mae']

    # ① 단조성 연역 — mfe/mae 보다 강한 정보다 (선도달 순서를 안다)
    if O == 'TARGET' and tp <= TP and sp >= SP:
        return 'TARGET', tp, tp
    if O == 'STOP' and sp <= SP and tp >= TP:
        return 'STOP', -sp, -sp
    if O == 'OPEN' and tp >= TP and sp >= SP:
        return 'OPEN', c['close'], c['close']

    # ② mfe/mae 로 닿았는지 판단
    hit_t = mfe >= tp
    hit_s = mae >= sp
    if hit_t and not hit_s:
        return 'TARGET', tp, tp
    if hit_s and not hit_t:
        return 'STOP', -sp, -sp
    if not hit_t and not hit_s:
        return 'OPEN', c['close'], c['close']
    return 'AMB', tp, -sp        # 둘 다 닿음 — 순서 모름


def evaluate(cases, a, b):
    """격자 한 점의 성적. 최선·최악 두 경계를 함께 낸다."""
    n = len(cases)
    if not n:
        return None
    best_sum = worst_sum = 0.0
    n_t = n_s = n_o = n_amb = 0
    maes = []
    for c in cases:
        tp, sp = c['TP'] * a, c['SP'] * b
        kind, bst, wst = resim(c, tp, sp)
        best_sum += bst
        worst_sum += wst
        maes.append(c['mae'])
        if kind == 'TARGET':
            n_t += 1
        elif kind == 'STOP':
            n_s += 1
        elif kind == 'OPEN':
            n_o += 1
        else:
            n_amb += 1
    maes.sort()
    return {
        'n': n,
        'ev_best': best_sum / n - COST,
        'ev_worst': worst_sum / n - COST,
        # 도달률도 경계로 — 모호분이 전부 목표(최선) / 전부 손절(최악)
        'reach_best': (n_t + n_amb) / n * 100,
        'reach_worst': n_t / n * 100,
        'stop_rate_worst': (n_s + n_amb) / n * 100,
        'open_rate': n_o / n * 100,
        'amb_pct': n_amb / n * 100,
        'mae_mean': sum(maes) / n,
        'mae_p90': maes[min(n - 1, int(n * 0.9))],
    }


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer,
                                  encoding='utf-8')
    rows = load()
    cases = []
    for r in rows:
        if (r.get('score') or 0) < BUY:
            continue
        c = prep(r)
        if c:
            cases.append(c)
    by_split = defaultdict(list)
    for c in cases:
        by_split[c['split']].append(c)
    print(f'매수권({BUY}+) 재시뮬 가능 {len(cases):,}건 = ' + ' · '.join(
        f"{k} {len(by_split[k]):,}" for k in ('train', 'valid', 'blind')))
    print(f'거래비용 {COST}% 차감 · 격자 {len(A_GRID)}×{len(B_GRID)}'
          f'={len(A_GRID) * len(B_GRID)}점\n')

    base = {sp: evaluate(by_split[sp], 1.0, 1.0)
            for sp in ('train', 'valid', 'blind')}
    print('■ 현행 (a=1.0, b=1.0) — 기준선')
    for sp in ('train', 'valid', 'blind'):
        d = base[sp]
        print(f"  {sp:6s} n={d['n']:>5,}  기대값 {d['ev_worst']:+.2f}% "
              f"(최선 {d['ev_best']:+.2f}%)  도달 {d['reach_worst']:.1f}% "
              f"· 손절 {d['stop_rate_worst']:.1f}% · 미도달 {d['open_rate']:.1f}%"
              f"  평균MAE -{d['mae_mean']:.2f}%")
    print(f"  현행 목표폭 중앙값 대비 손익비 0.70:1\n")

    hold = [c for c in by_split['blind'] if c['cohort'] == 'holdout']

    print('■ 격자 전체 — 실전(blind) 최악 기대값 기준 정렬')
    print(f"  {'목표a':>5s} {'손절b':>5s} │ "
          f"{'검증EV':>8s} {'실전EV':>8s} {'실전도달':>7s} "
          f"{'실전손절':>7s} {'모호':>5s} │ 사전등록 통과?")
    grid = []
    for a in A_GRID:
        for b in B_GRID:
            v = evaluate(by_split['valid'], a, b)
            bl = evaluate(by_split['blind'], a, b)
            ho = evaluate(hold, a, b)
            if not (v and bl):
                continue
            fails = []
            if bl['ev_worst'] <= 0:
                fails.append('①실전EV')
            if v['ev_worst'] <= 0:
                fails.append('②검증EV')
            if bl['reach_worst'] < MIN_REACH:
                fails.append('③도달률')
            if not (v['ev_worst'] > base['valid']['ev_worst']
                    and bl['ev_worst'] > base['blind']['ev_worst']):
                fails.append('④양쪽개선')
            if not (ho and ho['n'] >= MIN_N and ho['ev_worst'] > 0):
                fails.append('⑤홀드아웃')
            if bl['n'] < MIN_N or v['n'] < MIN_N:
                fails.append('⑥표본')
            grid.append({'a': a, 'b': b, 'valid': v, 'blind': bl,
                         'holdout': ho, 'fails': fails})

    grid.sort(key=lambda g: -g['blind']['ev_worst'])
    for g in grid:
        v, bl = g['valid'], g['blind']
        mark = '★통과' if not g['fails'] else '기각 ' + ','.join(g['fails'])
        cur = ' ←현행' if (g['a'] == 1.0 and g['b'] == 1.0) else ''
        print(f"  {g['a']:>5.2f} {g['b']:>5.2f} │ "
              f"{v['ev_worst']:>+7.2f}% {bl['ev_worst']:>+7.2f}% "
              f"{bl['reach_worst']:>6.1f}% {bl['stop_rate_worst']:>6.1f}% "
              f"{bl['amb_pct']:>4.0f}% │ {mark}{cur}")

    passed = [g for g in grid if not g['fails']]
    print()
    print('=' * 74)
    if passed:
        b0 = passed[0]
        print(f"사전등록 전 기준 통과 {len(passed)}개 · 최고: "
              f"목표 {b0['a']}배 · 손절 {b0['b']}배")
        print(f"  검증 {b0['valid']['ev_worst']:+.2f}% · "
              f"실전 {b0['blind']['ev_worst']:+.2f}% · "
              f"홀드아웃 {b0['holdout']['ev_worst']:+.2f}%"
              f" (현행 실전 {base['blind']['ev_worst']:+.2f}%)")
        print(f"  → 손익비 {0.70 * b0['a'] / b0['b']:.2f}:1 "
              f"(현행 0.70:1)")
    else:
        print('사전등록 기준을 통과한 조합 없음 — 채택하지 않는다.')
        near = min(grid, key=lambda g: len(g['fails']))
        print(f"  가장 근접: 목표 {near['a']}배 · 손절 {near['b']}배 — "
              f"미달 {','.join(near['fails'])}")
    print('=' * 74)

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump({
            'round': 17, 'buy_min_score': BUY, 'cost_pct': COST,
            'a_grid': A_GRID, 'b_grid': B_GRID,
            'min_n': MIN_N, 'min_reach_pct': MIN_REACH,
            'baseline': base,
            'grid': [{'a': g['a'], 'b': g['b'], 'fails': g['fails'],
                      'valid': g['valid'], 'blind': g['blind'],
                      'holdout': g['holdout']} for g in grid],
            'adopted': ({'a': passed[0]['a'], 'b': passed[0]['b']}
                        if passed else None),
        }, f, ensure_ascii=False, indent=1)
    print(f'기록: {OUT}')


if __name__ == '__main__':
    main()
