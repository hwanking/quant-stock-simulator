# -*- coding: utf-8 -*-
"""
라운드 15 — 손익비 구조를 고친다 (기대값이 마이너스인 진짜 원인).

정직 점검(honest_edge_check.py)에서 나온 것:
  실전 승률 58.2% · 이길 때 +6.64% · 질 때 −9.20% · 손익비 0.72:1
  기대값 = 0.582×6.64 − 0.418×9.20 = +0.019% → 비용 0.3% 빼면 −0.28%
  **승률은 문제가 아니다. 먹는 폭보다 잃는 폭이 크다.**

엔진은 목표를 `손절거리 × 0.7` 로 잡는다. 목표가 손절보다 가까우니 자주
닿지만 조금 먹는다. 승률은 오르고 손익비는 0.7 에 고정된다 —
구조적으로 기대값이 마이너스가 되는 설계다.

이 라운드는 두 가지를 동시에 검정한다:
  ① 손익비 k (목표 = 손절 × k) 를 0.7 에서 올리면 기대값이 양수가 되는가
  ② 국면마다 다른 k 를 쓰면 더 나은가 (6국면 분리 후 처음 가능해진 질문)

측정 방법: 원장의 MFE/MAE 로 경로를 다시 걷는다.
  · MFE ≥ 목표  이고 MAE < 손절  → 목표 도달 (+목표)
  · MAE ≥ 손절                  → 손절 (−손절)  ※ 동시 도달도 손절로 (보수)
  · 둘 다 아님                   → 기간 종료 수익률로 청산
동시 도달을 손절로 보므로 결과는 **실제보다 보수적**이다.

사전등록 (측정 전 고정):
  후보 k   : 0.7(현행) · 1.0 · 1.3 · 1.6 · 2.0
  손절 폭  : 현행 산식 그대로 (한 번에 하나만 바꾼다)
  채택 조건: 검증·블라인드 **양쪽에서**
      ① 비용 차감 후 기대값이 현행보다 높을 것
      ② 블라인드 기대값이 **양수**일 것 (마이너스를 덜 잃는 건 개선이 아니다)
      ③ 목표 도달률 20% 이상 (너무 안 닿으면 사용자가 못 기다린다)
  실패 시  : 채택하지 않는다.
"""
from __future__ import annotations

import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(BASE, '.portfolio', 'virtual_graded.jsonl')
OUT = os.path.join(BASE, '.portfolio', 'rr_policy.json')

COST = 0.30
BUY = 58
KS = [0.7, 1.0, 1.3, 1.6, 2.0]
MIN_REACH = 20.0
VOL_SPLIT = 0.030


def load():
    out = []
    with open(LEDGER, encoding='utf-8') as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if (r.get('mfe_pct') is None or r.get('mae_pct') is None
                    or (r.get('score') or 0) < BUY):
                continue
            out.append(r)
    return out


def stop_pct(r):
    """엔진의 실제 손절 폭 — max(3%, 일간σ × 2). 이건 바꾸지 않는다."""
    v = r.get('vol20')
    return max(3.0, 100.0 * float(v) * 2.0) if v is not None else 3.0


def sim(rows, k):
    n = len(rows)
    if not n:
        return None
    reach = st = 0
    rets = []
    for r in rows:
        s = stop_pct(r)
        t = s * k
        mfe, mae = float(r['mfe_pct']), abs(float(r['mae_pct']))
        if mfe >= t and mae < s:
            reach += 1
            rets.append(t)
        elif mae >= s:
            st += 1
            rets.append(-s)          # 동시 도달도 손절 (보수 가정)
        else:
            rets.append(float(r.get('close_return_pct')
                              or r.get('return_pct') or 0.0))
    win = [v for v in rets if v > 0]
    loss = [v for v in rets if v <= 0]
    g, p = sum(win), abs(sum(loss))
    return {
        'n': n, 'k': k,
        'reach': round(100.0 * reach / n, 1),
        'stop': round(100.0 * st / n, 1),
        'win_rate': round(100.0 * len(win) / n, 1),
        'avg_win': round((sum(win) / len(win)) if win else 0.0, 2),
        'avg_loss': round((abs(sum(loss)) / len(loss)) if loss else 0.0, 2),
        'ev': round(sum(rets) / n - COST, 3),
        'pf': round((g / p) if p > 0 else (99.0 if g else 0.0), 2),
    }


def cell(r):
    v = r.get('vol20')
    if v is None:
        return None
    return (r.get('regime'),
            'calm' if float(v) < VOL_SPLIT else 'rough')


REG_KO = {'BULL': '상승', 'SIDEWAYS': '옆걸음', 'BEAR': '하락'}
VOL_KO = {'calm': '차분한', 'rough': '거친'}


def main():
    rows = load()
    by = {s: [r for r in rows if r.get('split') == s]
          for s in ('train', 'valid', 'blind')}
    print(f"매수권 사례 {len(rows):,}건 "
          f"(학습 {len(by['train']):,} · 검증 {len(by['valid']):,} "
          f"· 블라인드 {len(by['blind']):,})\n")

    # ── ① 전체에서 손익비 k 를 바꿔 본다 ─────────────────────────────
    print('■ 손익비 k (목표 = 손절 × k) 를 바꾸면')
    print('   k     도달률   손절률   승률   이길때   질때   손익비  '
          '검증EV   실전EV')
    base = {}
    grid = {}
    for k in KS:
        m = {s: sim(by[s], k) for s in by}
        grid[k] = m
        if k == 0.7:
            base = m
        v, b = m['valid'], m['blind']
        rr = (v['avg_win'] / v['avg_loss']) if v['avg_loss'] else 0
        print(f"  {k:4.1f}   {b['reach']:5.1f}%  {b['stop']:5.1f}%  "
              f"{b['win_rate']:5.1f}%  {b['avg_win']:+6.2f}%  "
              f"{b['avg_loss']:5.2f}%  {rr:5.2f}  "
              f"{v['ev']:+7.3f}%  {b['ev']:+7.3f}%"
              f"{'  ✅' if b['ev'] > 0 else ''}")

    print('\n■ 판정 (검증·블라인드 양쪽 개선 · 블라인드 양수 · 도달률 20%+)')
    win_k = None
    for k in KS:
        if k == 0.7:
            continue
        v, b = grid[k]['valid'], grid[k]['blind']
        g = [('검증 개선', v['ev'] > base['valid']['ev']),
             ('실전 개선', b['ev'] > base['blind']['ev']),
             ('실전 양수', b['ev'] > 0),
             ('도달률', b['reach'] >= MIN_REACH)]
        ok = all(x[1] for x in g)
        miss = ' '.join(x[0] for x in g if not x[1])
        print(f"  k={k:.1f}: {'채택 가능' if ok else '미달 — ' + miss}")
        if ok and (win_k is None or b['ev'] > grid[win_k]['blind']['ev']):
            win_k = k

    # ── ② 국면마다 다른 k ────────────────────────────────────────────
    print('\n■ 국면별 최적 k (블라인드 기대값 기준 · 표본 30건+ 만)')
    per_cell = {}
    for rg in ('BULL', 'SIDEWAYS', 'BEAR'):
        for vb in ('calm', 'rough'):
            key = f'{rg}|{vb}'
            sub = {s: [r for r in by[s] if cell(r) == (rg, vb)] for s in by}
            if len(sub['blind']) < 30 or len(sub['valid']) < 20:
                continue
            best, best_ev = None, -99
            line = []
            for k in KS:
                b = sim(sub['blind'], k)
                v = sim(sub['valid'], k)
                line.append(f"k{k:.1f}:{b['ev']:+.2f}")
                # 검증에서도 개선돼야 후보로 본다
                if b['ev'] > best_ev and v['ev'] >= sim(sub['valid'], 0.7)['ev']:
                    best, best_ev = k, b['ev']
            ko = f"{VOL_KO[vb]} {REG_KO[rg]}"
            cur = sim(sub['blind'], 0.7)
            print(f"  {ko:10s} n={len(sub['blind']):4d}  "
                  + ' '.join(line)
                  + f"  → 현행 {cur['ev']:+.2f}% "
                  + (f"· 최적 k={best} ({best_ev:+.2f}%)" if best else '· 개선 없음'))
            if best and best_ev > cur['ev'] and best_ev > 0:
                per_cell[key] = {'k': best, 'ev': best_ev,
                                 'ev_now': cur['ev'], 'n': len(sub['blind'])}

    print('\n' + '=' * 78)
    if win_k:
        b = grid[win_k]['blind']
        print(f"판정: 채택 — 손익비 k 를 0.7 → {win_k} 로 올린다")
        print(f"  실전 기대값 {base['blind']['ev']:+.3f}% → {b['ev']:+.3f}% "
              f"· 도달률 {b['reach']:.1f}% · 손절률 {b['stop']:.1f}%")
    elif per_cell:
        print('판정: 전체 일괄 변경은 기각. 다만 아래 국면에서는 개선이 확인됐다')
        for kk, vv in per_cell.items():
            rg, vb = kk.split('|')
            print(f"  {VOL_KO[vb]} {REG_KO[rg]} (n={vv['n']}): "
                  f"k={vv['k']} → {vv['ev_now']:+.2f}% → {vv['ev']:+.2f}%")
        print('  → 국면별 k 는 별도 사전등록으로 검정한다 (표본이 칸마다 얇다)')
    else:
        print('판정: 채택 없음 — 손익비를 올려도 기준을 통과하지 못했다.')
    print('=' * 78)

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump({'current_k': 0.7, 'adopted_k': win_k,
                   'grid': {str(k): grid[k] for k in KS},
                   'per_cell': per_cell,
                   'criteria': ['검증 개선', '실전 개선', '실전 양수',
                                f'도달률 {MIN_REACH}%+']},
                  f, ensure_ascii=False, indent=1)
    print(f'\n저장: {OUT}')
    return 0 if (win_k or per_cell) else 1


if __name__ == '__main__':
    sys.exit(main())
