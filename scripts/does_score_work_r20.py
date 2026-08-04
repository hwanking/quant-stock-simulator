# -*- coding: utf-8 -*-
"""
라운드 20 — 진단. 점수가 애초에 **좋은 상황을 골라내기는 하는가**.

════════════════════════════════════════════════════════════════════════
왜 이 질문으로 내려가는가
════════════════════════════════════════════════════════════════════════
라운드 17·17e·18·19·19b — 네 가지 독립 설계로 실행 레벨과 게이트를 다 뒤졌고
전부 기각됐다. 그러면 위층(목표·손절·게이트)이 아니라 **아래층**을 봐야 한다.

  점수 58점 이상을 '매수권'이라 부르는데, 그 58점이 정말 뭔가를 아는가?
  점수가 높을수록 결과가 좋은가? 아니면 점수는 결과와 무관한가?

이건 후보를 고르는 라운드가 아니라 **진단** 라운드다. 채택할 것이 없다.
대신 답이 무엇이든 그대로 적는다.

■ 재는 것 (전부 정확 재시뮬 · 현행 목표·손절 그대로)
  ① 점수대별 기대값 — 점수가 오르면 기대값도 오르는가 (단조성)
  ② 매수권(58+) vs 비매수권(<58) — 엔진의 선택이 나머지보다 나은가
  ③ 목표·손절을 아예 쓰지 않고 20일 보유 — 실행 레벨이 도움이 되긴 하는가
  ④ 보유기간 5·10·15·20일 — 20일이 맞는 길이인가
  ⑤ 손실 통제: 설정별 평균 손실·최악 손실 — '덜 잃는' 쪽은 가능한가

■ 미리 정한 해석 규칙 (결과 보고 말 바꾸지 않기 위해)
  · 점수대별 기대값이 학습·검증·실전에서 **모두** 우상향이면 '점수는 작동한다'
  · 한 구간에서만 우상향이면 '구간 우연' 으로 적는다
  · 매수권이 비매수권보다 학습·검증·실전 **모두**에서 높아야 '선택이 낫다'
════════════════════════════════════════════════════════════════════════
"""
import io
import json
import os
import sys
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'scripts'))
OUT = os.path.join(BASE, '.portfolio', 'does_score_work_r20.json')

import exec_sim as X

BANDS = [(0, 40), (40, 50), (50, 55), (55, 58), (58, 60), (60, 100)]
SPLITS = ('train', 'valid', 'blind')


def wilson(k, n):
    if not n:
        return None, None
    p = k / n
    z = 1.96
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return (c - m) / d * 100, (c + m) / d * 100


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    # 점수 문턱 없이 전부 — 비매수권과 비교해야 하므로
    cases, _ = X.load_cases(min_score=0)
    by = defaultdict(list)
    for c in cases:
        by[c['split']].append(c)
    print(f'전체 {len(cases):,}건 = ' + ' · '.join(
        f'{k} {len(by[k]):,}' for k in SPLITS) + '\n')

    res = {}

    print('■ ① 점수대별 기대값 — 점수가 오르면 결과도 오르는가')
    print(f"  {'점수대':10s} " + ' '.join(f'{s:>18s}' for s in SPLITS))
    band_out = {}
    for lo, hi in BANDS:
        line = f'  {lo}~{hi if hi < 100 else ""}점'.ljust(12)
        rec = {}
        for sp in SPLITS:
            g = [c for c in by[sp] if lo <= (c['score'] or 0) < hi]
            e = X.ev(g)
            rec[sp] = {'n': len(g), 'ev': (e or {}).get('ev'),
                       'reach': (e or {}).get('reach')}
            if e:
                line += f"  {e['ev']:>+6.2f}% (n={len(g):>5,})"
            else:
                line += f"  {'—':>15s}"
        band_out[f'{lo}-{hi}'] = rec
        print(line)
    res['by_score_band'] = band_out

    # 단조성 판정
    print('\n  단조성 판정:')
    for sp in SPLITS:
        evs = [(f'{lo}~{hi}', band_out[f'{lo}-{hi}'][sp]['ev'])
               for lo, hi in BANDS
               if band_out[f'{lo}-{hi}'][sp]['ev'] is not None
               and band_out[f'{lo}-{hi}'][sp]['n'] >= 30]
        if len(evs) < 3:
            print(f'    {sp:6s} 표본 부족으로 판정 불가')
            continue
        ups = sum(1 for i in range(1, len(evs)) if evs[i][1] > evs[i - 1][1])
        print(f'    {sp:6s} 구간 {len(evs) - 1}개 중 상승 {ups}개 '
              f'→ {"우상향" if ups >= len(evs) - 1 else "우상향 아님"}'
              f'  (최저 {min(e[1] for e in evs):+.2f}% ~ '
              f'최고 {max(e[1] for e in evs):+.2f}%)')

    print('\n■ ② 엔진의 선택이 나머지보다 나은가 (58+ vs 58 미만)')
    print(f"  {'구간':8s} {'매수권 58+':>22s} {'비매수권 <58':>22s} {'차이':>10s}")
    sel_out = {}
    for sp in SPLITS:
        hi_g = [c for c in by[sp] if (c['score'] or 0) >= 58]
        lo_g = [c for c in by[sp] if (c['score'] or 0) < 58]
        eh, el = X.ev(hi_g), X.ev(lo_g)
        diff = (eh['ev'] - el['ev']) if (eh and el) else None
        sel_out[sp] = {'buy_ev': (eh or {}).get('ev'),
                       'buy_n': len(hi_g),
                       'other_ev': (el or {}).get('ev'),
                       'other_n': len(lo_g), 'diff': diff}
        print(f"  {sp:8s} {(eh or {}).get('ev', 0):>+9.2f}% (n={len(hi_g):>6,}) "
              f"{(el or {}).get('ev', 0):>+9.2f}% (n={len(lo_g):>6,}) "
              f"{diff if diff is not None else 0:>+9.2f}%p")
    res['selection'] = sel_out
    allpos = all(v['diff'] is not None and v['diff'] > 0 for v in sel_out.values())
    print(f"  → 세 구간 모두에서 매수권이 낫다? {'예' if allpos else '아니오'}")

    print('\n■ ③ 목표·손절을 안 쓰고 그냥 20일 보유하면')
    print(f"  {'구간':8s} {'현행(목표/손절)':>18s} {'20일 보유':>18s} {'차이':>10s}")
    hold_out = {}
    for sp in SPLITS:
        g = [c for c in by[sp] if (c['score'] or 0) >= 58]
        cur = X.ev(g)
        # 목표·손절을 아주 멀리 두면 사실상 만기 보유가 된다
        hold = X.ev(g, tp_mult=100.0, sp_mult=100.0)
        d = (hold['ev'] - cur['ev']) if (cur and hold) else None
        hold_out[sp] = {'current': (cur or {}).get('ev'),
                        'hold': (hold or {}).get('ev'), 'diff': d}
        print(f"  {sp:8s} {(cur or {}).get('ev', 0):>+17.2f}% "
              f"{(hold or {}).get('ev', 0):>+17.2f}% "
              f"{d if d is not None else 0:>+9.2f}%p")
    res['hold_vs_levels'] = hold_out

    print('\n■ ④ 보유기간 — 20일이 맞는 길이인가 (현행 목표·손절 유지)')
    print(f"  {'구간':8s} " + ' '.join(f'{b:>2d}일'.rjust(10) for b in (5, 10, 15, 20)))
    bars_out = {}
    for sp in SPLITS:
        g = [c for c in by[sp] if (c['score'] or 0) >= 58]
        line = f'  {sp:8s}'
        rec = {}
        for mb in (5, 10, 15, 20):
            e = X.ev(g, max_bars=mb)
            rec[mb] = (e or {}).get('ev')
            line += f"  {(e or {}).get('ev', 0):>+8.2f}%"
        bars_out[sp] = rec
        print(line)
    res['by_bars'] = bars_out

    print('\n■ ⑤ 손실 통제 — 손절을 조이면 덜 잃는가 (실전 기준)')
    g = [c for c in by['blind'] if (c['score'] or 0) >= 58]
    print(f"  {'손절배수':>8s} {'기대값':>9s} {'손절률':>8s} "
          f"{'평균손실':>9s} {'최악손실':>9s}")
    loss_out = {}
    for b in (0.5, 0.6, 0.8, 1.0, 1.25, 1.5):
        e = X.ev(g, sp_mult=b)
        rr = X.rets(g, sp_mult=b)
        losses = sorted(x for x in rr if x < 0)
        avg_l = sum(losses) / len(losses) if losses else 0
        wst = losses[0] if losses else 0
        loss_out[b] = {'ev': e['ev'], 'stop_rate': e['stop_rate'],
                       'avg_loss': avg_l, 'worst': wst}
        print(f"  {b:>8.2f} {e['ev']:>+8.2f}% {e['stop_rate']:>7.1f}% "
              f"{avg_l:>+8.2f}% {wst:>+8.2f}%")
    res['loss_control'] = loss_out

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(f'\n기록: {OUT}')


if __name__ == '__main__':
    main()
