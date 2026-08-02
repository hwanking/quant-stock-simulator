# -*- coding: utf-8 -*-
"""
라운드 7 — 국면별 실적 분해와 '약세장 매수 금지' 게이트 판정.

라운드 4~6에서 확인된 사실:
  · 적중률을 지배하는 것은 점수가 아니라 **시장 국면**이다.
  · 블라인드 구간의 약세 사례는 기준선 자체가 22.2% (n=54) 였다.
    이 구간에서는 어떤 조건을 걸어도 이길 수 없었다.

두 가지를 한다:
  ① 국면별로 성적을 분해해 **화면에 정직하게 나눠 쓸 숫자**를 만든다.
     지금 화면은 '실전 적중률 47.6%' 한 줄인데, 이 값은 국면을 섞은 평균이라
     사용자가 오늘 자기 상황에 적용할 수 없다.
  ② '약세 국면에서는 매수 결론을 내지 않는다' 게이트를 사전등록 기준으로
     판정한다.

게이트 사전등록 (측정 전 고정):
  대상   : 매수권(점수 58+) 사례
  변경   : 국면=BEAR 인 매수권 사례를 매수 결론에서 제외한다
  채택   : 검증·블라인드 **양쪽에서** 아래를 모두 만족
             - 매수권 적중률이 오른다 (+1.0%p 이상)
             - 비용 차감 후 평균수익이 오른다 (+0.10%p 이상)
             - 남는 신호가 전체의 5% 이상 (기회를 다 없애면 제품이 아니다)
  실패 시: 채택하지 않는다.
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
OUT = os.path.join(BASE, '.portfolio', 'regime_breakdown.json')

COST_PCT = 0.30
BUY_SCORE = 58
MIN_HIT_GAIN = 1.0
MIN_NET_GAIN = 0.10
MIN_KEEP_RATE = 5.0


def wilson_low(hit, n, z=1.96):
    if not n:
        return None
    p = hit / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return round(100.0 * (c - m) / d, 1)


def load():
    out = []
    with open(LEDGER, encoding='utf-8') as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get('success') is None or r.get('return_pct') is None:
                continue
            out.append(r)
    return out


def stats(rows):
    n = len(rows)
    if not n:
        return None
    hit = sum(1 for r in rows if r['success'])
    rets = [float(r['return_pct']) for r in rows]
    win = [v for v in rets if v > 0]
    loss = [v for v in rets if v <= 0]
    gain, pain = sum(win), abs(sum(loss))
    maes = [abs(float(r['mae_pct'])) for r in rows
            if r.get('mae_pct') is not None]
    return {'n': n, 'hit': round(100.0 * hit / n, 1),
            'wilson_low': wilson_low(hit, n),
            'net': round(sum(rets) / n - COST_PCT, 2),
            'pf': round((gain / pain) if pain > 0 else (99.0 if gain else 0.0), 2),
            'mae': round((sum(maes) / len(maes)) if maes else 0.0, 2)}


REGIME_KO = {'BULL': '상승 추세', 'BEAR': '하락 추세',
             'SIDEWAYS': '옆걸음(횡보)', None: '판정 보류'}


def main():
    rows = load()
    by = {s: [r for r in rows if r.get('split') == s]
          for s in ('train', 'valid', 'blind')}

    print('■ 국면별 실적 분해 — 전체 사례')
    table = {}
    for s in ('train', 'valid', 'blind'):
        table[s] = {}
        print(f'  [{s}]')
        for rg in ('BULL', 'SIDEWAYS', 'BEAR'):
            sub = [r for r in by[s] if r.get('regime') == rg]
            st = stats(sub)
            table[s][rg] = st
            if st:
                print(f"    {REGIME_KO[rg]:10s} n={st['n']:5d} "
                      f"적중 {st['hit']:5.1f}% (하한 {st['wilson_low']}%) "
                      f"비용후 {st['net']:+.2f}% PF {st['pf']:.2f}")
            else:
                print(f"    {REGIME_KO[rg]:10s} 표본 없음")

    print('\n■ 국면별 매수권(58점+) 실적 — 사용자가 실제로 받는 신호')
    buy_table = {}
    for s in ('train', 'valid', 'blind'):
        buy_table[s] = {}
        print(f'  [{s}]')
        for rg in ('BULL', 'SIDEWAYS', 'BEAR'):
            sub = [r for r in by[s]
                   if r.get('regime') == rg and (r.get('score') or 0) >= BUY_SCORE]
            st = stats(sub)
            buy_table[s][rg] = st
            if st:
                print(f"    {REGIME_KO[rg]:10s} n={st['n']:5d} "
                      f"적중 {st['hit']:5.1f}% 비용후 {st['net']:+.2f}% "
                      f"PF {st['pf']:.2f} MAE {st['mae']:.2f}%")
            else:
                print(f"    {REGIME_KO[rg]:10s} 표본 없음")

    print('\n■ 게이트 판정 — 약세 국면 매수 결론을 막으면 나아지는가')
    verdict = {}
    for s in ('valid', 'blind'):
        allbuy = [r for r in by[s] if (r.get('score') or 0) >= BUY_SCORE]
        kept = [r for r in allbuy if r.get('regime') != 'BEAR']
        a, k = stats(allbuy), stats(kept)
        if not (a and k):
            print(f'  [{s}] 표본 부족 — 판정 불가')
            verdict[s] = False
            continue
        keep_rate = 100.0 * k['n'] / max(1, len(by[s]))
        d_hit = k['hit'] - a['hit']
        d_net = k['net'] - a['net']
        ok = (d_hit >= MIN_HIT_GAIN and d_net >= MIN_NET_GAIN
              and keep_rate >= MIN_KEEP_RATE)
        verdict[s] = ok
        print(f"  [{s}] 현행 n={a['n']} 적중 {a['hit']:.1f}% "
              f"비용후 {a['net']:+.2f}%")
        print(f"        게이트 후 n={k['n']} 적중 {k['hit']:.1f}% "
              f"({d_hit:+.1f}%p) 비용후 {k['net']:+.2f}% ({d_net:+.2f}%p) "
              f"· 남는 신호율 {keep_rate:.1f}%")
        print(f"        → {'통과' if ok else '미달'}")

    adopt = all(verdict.get(s) for s in ('valid', 'blind'))
    print('\n' + '=' * 70)
    if adopt:
        print('판정: 채택 — 약세 국면에서는 매수 결론을 내지 않는다.')
    else:
        print('판정: 채택 없음 — 약세장 매수 금지가 검증·블라인드 양쪽을 '
              '동시에 만족시키지 못했습니다.')
    print('=' * 70)

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump({'generated_from': 'virtual_graded.jsonl',
                   'regime_ko': {k: v for k, v in REGIME_KO.items() if k},
                   'all': table, 'buy_zone': buy_table,
                   'bear_gate_adopted': adopt}, f, ensure_ascii=False, indent=1)
    print(f'\n국면별 실적 저장: {OUT}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
