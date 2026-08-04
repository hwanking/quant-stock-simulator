# -*- coding: utf-8 -*-
"""
라운드 19 — "지금 사도 되는가". 목표·손절이 아니라 **언제 사지 않을 것인가**.

════════════════════════════════════════════════════════════════════════
사전등록 — 측정 전에 고정한다
════════════════════════════════════════════════════════════════════════

■ 왜 이 질문으로 옮기는가
  라운드 17·18 에서 목표·손절을 아무리 조합해도 실전 기대값을 못 살렸다.
  그런데 라운드 18 의 국면별 분해가 분명한 걸 보여 줬다:
     거친 상승  +1.17%   ← 유일하게 양수
     거친 옆걸음 -0.43%
     차분한 상승 -0.23%
     거친 하락 -10.41%   ← 재앙
  같은 엔진인데 국면에 따라 11%p 가 갈린다. 그러면 손볼 곳은 실행 레벨이
  아니라 **진입 여부**다.

■ 후보 게이트 (전부 기준일에 알 수 있는 값만 — 누수 없음)
  A. 국면      6칸 각각 / 상승만 / 하락 제외 / 거친 하락만 제외
  B. 점수      58+ / 60+ / 62+ / 65+
  C. 진입 위치  안전마진 확보만 / 적정가 크게 초과 제외
  D. 추세      월봉 10선 위에서만
  E. 과열      RSI < 70 / RSI < 60
  F. 52주 위치  range_pos < 80 / < 60  (고점 근처에서 안 산다)
  G. 밴드 위치  bb_pos < 80

■ 프로토콜 — 라운드 18 과 같다. 실전은 마지막에 한 번만.
  1단계  단일 게이트를 학습·검증에서 전부 재고, 아래를 만족하는 것만 남긴다
         · 검증 기대값 > 0
         · 학습 기대값 > 0            (검증에서만 좋은 건 우연일 수 있다)
         · 신호 잔존율 ≥ 30%          (다 걸러 버리면 상품이 아니다)
  2단계  남은 것 중 검증 기대값 1위 **하나**를 실전에 한 번 건다.

■ 2단계 채택 기준 — 전부 충족
  ① 실전 기대값 > 0
  ② 부트스트랩 95% 하한 > 0
  ③ 종목 반반 양쪽 > 0
  ④ 실전 기간 전·후반 양쪽 > 0
  ⑤ 실전 잔존 표본 ≥ 30

■ 기대값의 정의를 분명히 한다
  게이트는 '안 사는' 선택이다. 안 산 건은 수익 0 이다. 그래서 두 가지를 본다:
    · 거래당 기대값   — 산 것만 놓고 잰 값
    · 신호당 기대값   — 안 산 것을 0 으로 넣고 잰 값
  게이트의 진짜 가치는 **거래당**이다(안 사면 돈이 안 나가니까).
  다만 잔존율이 너무 낮으면 쓸 수 없으므로 함께 본다.

■ 미리 밝히는 한계
  오늘은 하락 국면이다. 하락 칸의 실전 표본은 거친 15·차분한 0 이다.
  '하락장에서 사지 마라'가 이 연구에서 나와도, 그 결론의 **실전 근거는
  15건뿐**이다. 학습 구간(576건)에서는 볼 수 있지만 그건 연습이다.
════════════════════════════════════════════════════════════════════════
"""
import io
import json
import os
import random
import sys
import zlib
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'scripts'))
OUT = os.path.join(BASE, '.portfolio', 'when_not_to_buy_r19.json')

import exec_sim as X

MIN_KEEP = 30.0          # 신호 잔존율 하한 %
MIN_N = 30
BOOT = 10000
SEED = 20260804


def boot_lo(vals):
    if not vals:
        return None
    rng = random.Random(SEED)
    n = len(vals)
    sims = []
    for _ in range(BOOT):
        sims.append(sum(vals[rng.randrange(n)] for _ in range(n)) / n)
    sims.sort()
    return sims[int(BOOT * 0.025)]


def half(t):
    return zlib.crc32(str(t).encode()) % 2


def num(x, d=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


# ── 게이트 정의 — 전부 기준일에 알 수 있는 값 ────────────────────────
GATES = {
    '전체 (게이트 없음)': lambda c: True,
    '거친 상승만': lambda c: c['cell6'] == '거친 상승',
    '상승 국면만': lambda c: c['regime'] == 'BULL',
    '하락 국면 제외': lambda c: c['regime'] != 'BEAR',
    '거친 하락만 제외': lambda c: c['cell6'] != '거친 하락',
    '하락·옆걸음 제외': lambda c: c['regime'] == 'BULL',
    '국면 아는 것만': lambda c: c['regime'] is not None,
    '점수 60+': lambda c: (c['score'] or 0) >= 60,
    '점수 62+': lambda c: (c['score'] or 0) >= 62,
    '점수 65+': lambda c: (c['score'] or 0) >= 65,
    '안전마진 확보만': lambda c: c['entry_zone'] == '안전마진 확보',
    '적정가 크게 초과 제외': lambda c: '크게 초과' not in str(c['entry_zone']),
    '월봉 10선 위': lambda c: bool(c['m10_above']),
    'RSI < 70': lambda c: (num(c['rsi'], 50) or 50) < 70,
    'RSI < 60': lambda c: (num(c['rsi'], 50) or 50) < 60,
    'RSI 40~65': lambda c: 40 <= (num(c['rsi'], 50) or 50) <= 65,
    '52주 위치 < 80': lambda c: (num(c['range_pos'], 50) or 50) < 80,
    '52주 위치 < 60': lambda c: (num(c['range_pos'], 50) or 50) < 60,
    '밴드 위치 < 80': lambda c: (num(c['bb_pos'], 50) or 50) < 80,
    '데마크 셋업 있음': lambda c: str(c['demark_state']) not in ('NONE', 'None'),
}


def measure(cases, fn):
    kept = [c for c in cases if fn(c)]
    if not kept:
        return None
    e = X.ev(kept)
    if not e:
        return None
    e['keep_pct'] = len(kept) / len(cases) * 100
    e['kept'] = len(kept)
    # 신호당 — 거른 건은 0 으로
    e['ev_all_signals'] = e['ev'] * e['traded'] / len(cases)
    return e


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    cases, _ = X.load_cases()
    by = defaultdict(list)
    for c in cases:
        by[c['split']].append(c)
    print(f'매수권({X.BUY}+) {len(cases):,}건 = ' + ' · '.join(
        f'{k} {len(by[k]):,}' for k in ('train', 'valid', 'blind')) + '\n')

    print('■ 1단계 — 학습·검증에서 단일 게이트 전수 측정 (실전 미열람)')
    print(f"  {'게이트':22s} {'학습EV':>8s} {'검증EV':>8s} "
          f"{'검증n':>6s} {'잔존':>6s} │ 1단계")
    rows = []
    for name, fn in GATES.items():
        t = measure(by['train'], fn)
        v = measure(by['valid'], fn)
        if not t or not v:
            continue
        bad = []
        if v['ev'] <= 0:
            bad.append('검증EV')
        if t['ev'] <= 0:
            bad.append('학습EV')
        if v['keep_pct'] < MIN_KEEP:
            bad.append('잔존율')
        rows.append({'name': name, 'train': t, 'valid': v, 'bad': bad})
    rows.sort(key=lambda r: -r['valid']['ev'])
    for r in rows:
        t, v = r['train'], r['valid']
        mark = '통과' if not r['bad'] else '기각 ' + ','.join(r['bad'])
        print(f"  {r['name']:22s} {t['ev']:>+7.2f}% {v['ev']:>+7.2f}% "
              f"{v['kept']:>6,} {v['keep_pct']:>5.1f}% │ {mark}")

    ok = [r for r in rows if not r['bad']]
    if not ok:
        print('\n1단계 통과 없음 — 실전을 볼 필요도 없다. 기각.')
        with open(OUT, 'w', encoding='utf-8') as f:
            json.dump({'round': 19, 'stage1_passed': 0, 'adopted': None,
                       'stage1': [{'name': r['name'],
                                   'train_ev': r['train']['ev'],
                                   'valid_ev': r['valid']['ev'],
                                   'keep_pct': r['valid']['keep_pct'],
                                   'fails': r['bad']} for r in rows]},
                      f, ensure_ascii=False, indent=1)
        return

    pick = ok[0]
    fn = GATES[pick['name']]
    print(f"\n  ▶ 고른 게이트: {pick['name']} "
          f"(검증 {pick['valid']['ev']:+.2f}% · 잔존 "
          f"{pick['valid']['keep_pct']:.1f}%)")

    print('\n■ 2단계 — 이 게이트 하나만 실전에 건다 (한 번만 본다)')
    bl = by['blind']
    kept = [c for c in bl if fn(c)]
    e = measure(bl, fn)
    base = X.ev(bl)
    print(f"  현행(게이트 없음)  n={base['traded']:,}  "
          f"기대값 {base['ev']:+.2f}%")
    print(f"  게이트 적용        n={e['kept']:,}  "
          f"기대값 {e['ev']:+.2f}%  (잔존 {e['keep_pct']:.1f}%)")
    print(f"  신호당 기대값 {e['ev_all_signals']:+.2f}% "
          f"(거른 건을 0 으로 넣은 값)")

    rr = X.rets(kept)
    lo = boot_lo(rr)
    h1 = [c for c in kept if half(c['ticker']) == 0]
    h2 = [c for c in kept if half(c['ticker']) == 1]
    e1, e2 = X.ev(h1), X.ev(h2)
    sk = sorted(kept, key=lambda c: c['date'])
    f1, f2 = sk[:len(sk) // 2], sk[len(sk) // 2:]
    t1, t2 = X.ev(f1), X.ev(f2)

    c1 = e['ev'] > 0
    c2 = lo is not None and lo > 0
    c3 = bool(e1 and e2 and e1['ev'] > 0 and e2['ev'] > 0)
    c4 = bool(t1 and t2 and t1['ev'] > 0 and t2['ev'] > 0)
    c5 = e['kept'] >= MIN_N
    print(f"\n  ① 실전 기대값 > 0          {e['ev']:+.2f}%  "
          f"{'통과' if c1 else '실패'}")
    print(f"  ② 부트스트랩 95% 하한 > 0  {lo:+.2f}%  "
          f"{'통과' if c2 else '실패'}")
    print(f"  ③ 종목 반반 양쪽 > 0       "
          f"{(e1 or {}).get('ev', 0):+.2f}% / {(e2 or {}).get('ev', 0):+.2f}%  "
          f"{'통과' if c3 else '실패'}")
    print(f"  ④ 기간 전·후반 양쪽 > 0    "
          f"{(t1 or {}).get('ev', 0):+.2f}% / {(t2 or {}).get('ev', 0):+.2f}%  "
          f"{'통과' if c4 else '실패'}")
    print(f"  ⑤ 실전 표본 ≥ 30           {e['kept']}건  "
          f"{'통과' if c5 else '실패'}")
    adopted = c1 and c2 and c3 and c4 and c5
    print(f"\n  ▶ 판정: {'채택 가능' if adopted else '기각'}")

    print('\n■ 참고 — 실전에서 국면 6칸의 현행 성적 (게이트 설계의 근거)')
    cells = defaultdict(list)
    for c in bl:
        cells[c['cell6'] or '국면 미상'].append(c)
    for name in sorted(cells, key=lambda x: -len(cells[x])):
        g = cells[name]
        ee = X.ev(g)
        flag = '' if len(g) >= MIN_N else '  ← 표본 부족, 판정 안 함'
        print(f"  {name:12s} n={len(g):>4,}  기대값 "
              f"{(ee or {}).get('ev', 0):>+7.2f}%  "
              f"도달 {(ee or {}).get('reach', 0):>5.1f}%{flag}")

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump({
            'round': 19,
            'protocol': '1단계 학습·검증 선택 → 2단계 실전 1회',
            'stage1': [{'name': r['name'], 'train_ev': r['train']['ev'],
                        'valid_ev': r['valid']['ev'],
                        'keep_pct': r['valid']['keep_pct'],
                        'fails': r['bad']} for r in rows],
            'pick': pick['name'],
            'blind': e, 'baseline_blind': base, 'bootstrap_lo': lo,
            'checks': {'ev>0': c1, 'boot_lo>0': c2, 'ticker_halves': c3,
                       'time_halves': c4, 'n>=30': c5},
            'adopted': (pick['name'] if adopted else None),
            'blind_cells': {k: {'n': len(v), 'ev': (X.ev(v) or {}).get('ev')}
                            for k, v in cells.items()},
        }, f, ensure_ascii=False, indent=1)
    print(f'\n기록: {OUT}')


if __name__ == '__main__':
    main()
