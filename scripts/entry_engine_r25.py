# -*- coding: utf-8 -*-
"""
라운드 25 — "실제로 살 수 있는 가격"을 데이터에서 다시 배운다.

════════════════════════════════════════════════════════════════════════
왜 이 라운드가 필요한가
════════════════════════════════════════════════════════════════════════
현행 권장 매수가 = **적정가 × (1 − 안전마진 15%)** 다.
적정가는 분기 실적 기반 **장기 가치**라 현재가와 30~50% 벌어지는 일이 흔하다.
  우진      현재가 14,600 → 권장  9,388 (−35.7%)
  달바글로벌 현재가 242,500 → 권장 126,452 (−47.8%)
"14,600원인데 언제 9,388원까지 떨어져"라는 사용자 지적이 정확하다.
장기 가치평가 값을 **오늘의 실행 가격**으로 쓴 것이 잘못이다.

그래서 문구만 고치지 않고 **산식 자체를 데이터로 다시 고른다.**

════════════════════════════════════════════════════════════════════════
사전등록 (측정 전에 고정한다)
════════════════════════════════════════════════════════════════════════

■ 후보 진입 엔진 (전부 기준일에 알 수 있는 값만 쓴다 — 누수 없음)
  now          기준일 종가에 바로 산다
  fixed k%     기준가보다 k% 아래 지정가        k ∈ 1,2,3,5,7,10
  atr m배      기준가보다 (일변동성 × m)% 아래   m ∈ 0.5,1.0,1.5,2.0,3.0
  breakout k%  기준가보다 k% 위로 올라가면 산다  k ∈ 1,2,3

■ 재는 것 (사용자가 요청한 항목 그대로)
  체결률 · 평균 체결 소요일 · 진입 후 목표 선도달률 · 손절 선도달률 ·
  거래당 기대값 · **신호당 기대값**(미체결을 0으로 넣은 값) · 손익비

■ 왜 '신호당 기대값'이 중요한가
  체결률이 낮으면 거래당 성적이 좋아도 실제로는 거의 못 산다.
  '못 산 것'을 0 으로 넣어야 그 손해가 보인다. 이게 이번 연구의 핵심 잣대다.

■ 프로토콜 — 라운드 18·19 와 같다. 실전은 마지막에 한 번만.
  1단계  학습·검증만 보고 하나를 고른다 (실전 미열람)
         · 학습 신호당 기대값 > 현행(now) 보다 높을 것
         · 검증 신호당 기대값 > 현행보다 높을 것
         · 체결률 ≥ 50%          (절반도 못 사면 상품이 아니다)
         · 평균 체결 소요일 ≤ 10 (보유기간 20일의 절반 안에 들어와야 한다)
  2단계  그 하나만 실전에 한 번 건다
  채택   ① 실전 신호당 기대값 > 현행  ② 부트스트랩 95% 하한 > 현행
         ③ 종목 반반 양쪽 개선  ④ 실전 체결률 ≥ 50%

■ 무엇을 주장하지 않는가
  이건 '돈을 버는 엔진을 찾았다'가 아니라 **'실행 가능한 진입가를 찾는다'**는
  연구다. 라운드 17~21 에서 확인했듯 이 엔진의 기대값은 여전히 음수일 수 있다.
  그 경우에도 "더 실행 가능한 쪽"을 고르는 것은 의미가 있다 —
  닿지도 않을 가격을 내미는 것보다 낫다.
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
OUT = os.path.join(BASE, '.portfolio', 'entry_engine_r25.json')

import exec_sim as X

FIXED = [1.0, 2.0, 3.0, 5.0, 7.0, 10.0]
ATR_M = [0.5, 1.0, 1.5, 2.0, 3.0]
BREAK = [1.0, 2.0, 3.0]
MIN_FILL = 50.0          # 체결률 하한 %
MAX_WAIT = 10.0          # 평균 체결 소요일 상한
BOOT = 10000
SEED = 20260804


def engines(case):
    """
    후보 엔진 목록 → (이름, kind, pct). pct 는 사례별로 달라질 수 있다
    (변동성 비례 엔진). 사례를 받아 그때그때 계산한다.
    """
    out = [('현재가 즉시', 'now', 0.0)]
    for k in FIXED:
        out.append((f'지정가 -{k:g}%', 'limit', k))
    v = case.get('vol20')
    for m in ATR_M:
        pct = (float(v) * 100.0 * m) if v else None
        out.append((f'변동성 {m:g}배', 'limit', pct))
    for k in BREAK:
        out.append((f'돌파 +{k:g}%', 'breakout', k))
    return out


ENGINE_NAMES = [n for n, _, _ in engines({'vol20': 0.02})]


def run(cases, name):
    """엔진 하나의 성적. 미체결은 수익 0 으로 신호당 기대값에 넣는다."""
    n_t = n_s = n_o = n_ne = n_bad = 0
    tot = 0.0
    bars = []
    rets = []
    for c in cases:
        spec = next((e for e in engines(c) if e[0] == name), None)
        if not spec:
            continue
        _, kind, pct = spec
        if kind != 'now' and (pct is None or pct <= 0):
            n_bad += 1
            continue
        r = X.simulate_entry(c, c['TP'], c['SP'], kind, pct or 0.0)
        if r['kind'] == 'NODATA':
            n_bad += 1
            continue
        if r['kind'] == 'NOENTRY':
            n_ne += 1
            continue
        net = r['ret'] - X.COST
        tot += net
        rets.append(net)
        if r['entry_bar']:
            bars.append(r['entry_bar'])
        if r['kind'] == 'TARGET':
            n_t += 1
        elif r['kind'] == 'STOP':
            n_s += 1
        else:
            n_o += 1
    traded = n_t + n_s + n_o
    n_all = traded + n_ne
    if not n_all:
        return None
    return {
        'name': name, 'n': n_all, 'traded': traded,
        'fill_pct': traded / n_all * 100,
        'wait_days': (sum(bars) / len(bars)) if bars else 0.0,
        'ev_trade': (tot / traded) if traded else None,
        'ev_signal': tot / n_all,           # 못 산 것을 0 으로 — 핵심 잣대
        'reach': (n_t / traded * 100) if traded else 0.0,
        'stop_rate': (n_s / traded * 100) if traded else 0.0,
        'rets': rets,
    }


def boot_lo(vals, n_all):
    """신호당 기대값의 부트스트랩 하한 — 미체결 0 을 채워 넣고 잰다."""
    if not vals:
        return None
    pad = vals + [0.0] * max(0, n_all - len(vals))
    rng = random.Random(SEED)
    n = len(pad)
    sims = []
    for _ in range(BOOT):
        sims.append(sum(pad[rng.randrange(n)] for _ in range(n)) / n)
    sims.sort()
    return sims[int(BOOT * 0.025)]


def half(t):
    return zlib.crc32(str(t).encode()) % 2


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    cases, _ = X.load_cases()
    by = defaultdict(list)
    for c in cases:
        by[c['split']].append(c)
    print(f'매수권({X.BUY}+) 경로 확보 {len(cases):,}건 = ' + ' · '.join(
        f'{k} {len(by[k]):,}' for k in ('train', 'valid', 'blind')))
    print(f'후보 엔진 {len(ENGINE_NAMES)}개 · 비용 {X.COST}%\n')

    base_tr = run(by['train'], '현재가 즉시')
    base_va = run(by['valid'], '현재가 즉시')
    base_bl = run(by['blind'], '현재가 즉시')
    print(f"■ 현행 기준선 (현재가 즉시 진입)")
    for lab, d in (('학습', base_tr), ('검증', base_va), ('실전', base_bl)):
        print(f"  {lab} n={d['n']:>5,} 체결 {d['fill_pct']:5.1f}% · "
              f"신호당 {d['ev_signal']:+.2f}% · 거래당 {d['ev_trade']:+.2f}% · "
              f"도달 {d['reach']:.1f}%")

    print('\n■ 1단계 — 학습·검증만 보고 고른다 (실전 미열람)')
    print(f"  {'엔진':14s} │ {'학습신호당':>9s} {'검증신호당':>9s} "
          f"{'검증체결':>7s} {'대기일':>6s} {'검증도달':>7s} │ 1단계")
    rows = []
    for nm in ENGINE_NAMES:
        tr, va = run(by['train'], nm), run(by['valid'], nm)
        if not tr or not va:
            continue
        bad = []
        if tr['ev_signal'] <= base_tr['ev_signal']:
            bad.append('학습')
        if va['ev_signal'] <= base_va['ev_signal']:
            bad.append('검증')
        if va['fill_pct'] < MIN_FILL:
            bad.append('체결률')
        if va['wait_days'] > MAX_WAIT:
            bad.append('대기일')
        rows.append({'name': nm, 'train': tr, 'valid': va, 'bad': bad})
    rows.sort(key=lambda r: -r['valid']['ev_signal'])
    for r in rows:
        tr, va = r['train'], r['valid']
        mark = '통과' if not r['bad'] else '기각 ' + ','.join(r['bad'])
        cur = ' ←현행' if r['name'] == '현재가 즉시' else ''
        print(f"  {r['name']:14s} │ {tr['ev_signal']:>+8.2f}% "
              f"{va['ev_signal']:>+8.2f}% {va['fill_pct']:>6.1f}% "
              f"{va['wait_days']:>5.1f}일 {va['reach']:>6.1f}% │ {mark}{cur}")

    ok = [r for r in rows if not r['bad']]
    res = {'round': 25, 'baseline': {'train': base_tr['ev_signal'],
                                     'valid': base_va['ev_signal'],
                                     'blind': base_bl['ev_signal']},
           'stage1': [{'name': r['name'],
                       'train_ev_signal': r['train']['ev_signal'],
                       'valid_ev_signal': r['valid']['ev_signal'],
                       'valid_fill': r['valid']['fill_pct'],
                       'valid_wait': r['valid']['wait_days'],
                       'fails': r['bad']} for r in rows],
           'adopted': None}

    if not ok:
        print('\n' + '=' * 74)
        print('1단계 통과 없음 — 학습·검증 **양쪽에서** 현재가 즉시 진입을')
        print('이기는 진입 방식이 없다. 실전을 볼 필요도 없다.')
        print('=' * 74)
        with open(OUT, 'w', encoding='utf-8') as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        print(f'기록: {OUT}')
        return

    pick = ok[0]
    nm = pick['name']
    print(f"\n  ▶ 고른 엔진: {nm} "
          f"(검증 신호당 {pick['valid']['ev_signal']:+.2f}% · "
          f"체결 {pick['valid']['fill_pct']:.1f}% · "
          f"대기 {pick['valid']['wait_days']:.1f}일)")

    print('\n■ 2단계 — 실전 1회')
    bl = run(by['blind'], nm)
    print(f"  현행  신호당 {base_bl['ev_signal']:+.2f}% · "
          f"체결 {base_bl['fill_pct']:.1f}%")
    print(f"  후보  신호당 {bl['ev_signal']:+.2f}% · "
          f"체결 {bl['fill_pct']:.1f}% · 대기 {bl['wait_days']:.1f}일 · "
          f"도달 {bl['reach']:.1f}%")

    lo_new = boot_lo(bl['rets'], bl['n'])
    lo_cur = boot_lo(base_bl['rets'], base_bl['n'])
    h1 = [c for c in by['blind'] if half(c['ticker']) == 0]
    h2 = [c for c in by['blind'] if half(c['ticker']) == 1]
    a1, a2 = run(h1, nm), run(h2, nm)
    b1, b2 = run(h1, '현재가 즉시'), run(h2, '현재가 즉시')

    c1 = bl['ev_signal'] > base_bl['ev_signal']
    c2 = (lo_new is not None and lo_cur is not None and lo_new > lo_cur)
    c3 = bool(a1 and a2 and b1 and b2
              and a1['ev_signal'] > b1['ev_signal']
              and a2['ev_signal'] > b2['ev_signal'])
    c4 = bl['fill_pct'] >= MIN_FILL
    for lab, val, okk in (
            ('① 실전 신호당 개선',
             f"{bl['ev_signal']:+.2f}% vs {base_bl['ev_signal']:+.2f}%", c1),
            ('② 부트스트랩 하한 개선',
             f"{lo_new:+.2f}% vs {lo_cur:+.2f}%", c2),
            ('③ 종목 반반 양쪽 개선',
             f"{(a1 or {}).get('ev_signal', 0):+.2f}/"
             f"{(a2 or {}).get('ev_signal', 0):+.2f}", c3),
            (f'④ 실전 체결률 ≥ {MIN_FILL:.0f}%', f"{bl['fill_pct']:.1f}%", c4)):
        print(f"  {lab:22s} {val:>22s}  {'통과' if okk else '실패'}")
    adopted = c1 and c2 and c3 and c4
    print(f"\n  ▶ 판정: {'채택 가능' if adopted else '기각'}")

    res['pick'] = nm
    res['blind'] = {k: v for k, v in bl.items() if k != 'rets'}
    res['baseline_blind'] = {k: v for k, v in base_bl.items() if k != 'rets'}
    res['checks'] = {'ev>base': c1, 'boot>base': c2,
                     'ticker_halves': c3, 'fill>=50': c4}
    res['adopted'] = nm if adopted else None
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(f'\n기록: {OUT}')


if __name__ == '__main__':
    main()
