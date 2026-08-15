# -*- coding: utf-8 -*-
"""
라운드 6 — 약세장 과매도 반등 규칙의 일반화 검정 (종목 홀드아웃).

라운드 5에서 나온 것:
  국면=BEAR & (RSI 과매도 | 볼린저 하단) 조합이
    학습 n=348~434 적중 67~68% (기준선 대비 +12%p) 비용후 +0.8~0.9%
    검증 n=13~23  적중 77~83% (기준선 대비 +13~19%p)
  → 방향은 일관되지만 **검증 표본이 20건 안팎**이라 채택 기준(150건)에 미달.
    이유는 성능이 아니라 달력이다 — 검증 기간(2025-07~2026-01)에 약세 국면이
    거의 없었다. 표본을 기다린다고 생기지 않는다.

그래서 검정 축을 바꾼다 (기준을 낮추는 것이 아니라, 다른 방향으로 자른다):
  시간이 아니라 **종목**으로 자른다. 규칙이 본 적 없는 종목에서도 통하면
  그것은 특정 종목에 대한 과최적화가 아니라는 뜻이다.

사전등록 (측정 전 고정):
  대상    : 국면=BEAR 인 전체 사례 (학습·검증·블라인드 모두 포함)
  분할    : 티커를 사전순 정렬해 3의 배수 번째를 홀드아웃으로 뗀다.
            (난수 없음 — 다시 돌려도 같은 분할이 나온다)
  규칙    : RULES 에 코드로 미리 적어 둔 3개만 잰다. 추가·수정 금지.
  채택    : 홀드아웃 종목에서 표본 150건+ · 같은 국면 기준선 대비 +5.0%p+ ·
            비용 차감 후 평균수익 > 0
  추가확인: 블라인드 날짜 구간의 BEAR 사례에서도 lift 가 양수일 것
  실패 시 : 채택하지 않고 그대로 기록한다.

주의: 이 규칙이 채택돼도 '언제나 70%'가 되는 것이 아니다. 약세 국면에서만
      쓰는 조건부 규칙이며, 화면에도 조건부로만 표시한다.
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

COST_PCT = 0.30
MIN_HOLDOUT_N = 150
MIN_LIFT = 5.0

RULES = {
    'RSI 과매도': lambda r: (r.get('rsi') is not None and r['rsi'] < 35),
    '볼린저 하단': lambda r: (r.get('bb_pos') is not None and r['bb_pos'] < 20),
    '과매도 또는 하단': lambda r: (
        (r.get('rsi') is not None and r['rsi'] < 35)
        or (r.get('bb_pos') is not None and r['bb_pos'] < 20)),
}


def wilson_low(hit, n, z=1.96):
    if not n:
        return 0.0
    p = hit / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return 100.0 * (c - m) / d


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
    return {'n': n, 'hit': 100.0 * hit / n, 'wilson': wilson_low(hit, n),
            'net': sum(rets) / n - COST_PCT,
            'pf': (gain / pain) if pain > 0 else (99.0 if gain else 0.0),
            'mae': (sum(maes) / len(maes)) if maes else 0.0}


def main():
    rows = load()
    bear = [r for r in rows if r.get('regime') == 'BEAR']
    print(f"전체 {len(rows)}건 · 약세 국면 {len(bear)}건 "
          f"({100.0 * len(bear) / len(rows):.1f}%)")

    tickers = sorted({r['ticker'] for r in bear})
    holdout = {t for i, t in enumerate(tickers) if i % 3 == 0}
    dev = [r for r in bear if r['ticker'] not in holdout]
    hold = [r for r in bear if r['ticker'] in holdout]
    print(f"종목 {len(tickers)}개 → 개발 {len(tickers) - len(holdout)}개 "
          f"({len(dev)}건) · 홀드아웃 {len(holdout)}개 ({len(hold)}건)\n")

    bd, bh = stats(dev), stats(hold)
    print('■ 약세 국면 기준선 (규칙 없음)')
    print(f"  개발  n={bd['n']:4d} 적중 {bd['hit']:.1f}% 비용후 {bd['net']:+.2f}%")
    print(f"  홀드아웃 n={bh['n']:4d} 적중 {bh['hit']:.1f}% "
          f"비용후 {bh['net']:+.2f}%")

    print('\n■ 규칙별 성과')
    winners = []
    for name, fn in RULES.items():
        d = stats([r for r in dev if fn(r)])
        h = stats([r for r in hold if fn(r)])
        print(f"  · {name}")
        if d:
            print(f"    개발    n={d['n']:4d} 적중 {d['hit']:.1f}% "
                  f"(lift {d['hit'] - bd['hit']:+.1f}%p) "
                  f"비용후 {d['net']:+.2f}% PF {d['pf']:.2f}")
        if not h:
            print('    홀드아웃 표본 0건 → 판정 불가')
            continue
        lift = h['hit'] - bh['hit']
        ok = (h['n'] >= MIN_HOLDOUT_N and lift >= MIN_LIFT and h['net'] > 0)
        print(f"    홀드아웃 n={h['n']:4d} 적중 {h['hit']:.1f}% "
              f"(lift {lift:+.1f}%p · Wilson {h['wilson']:.1f}%) "
              f"비용후 {h['net']:+.2f}% PF {h['pf']:.2f} MAE {h['mae']:.2f}% "
              f"→ {'통과' if ok else '미달'}")
        if ok:
            winners.append((name, fn, d, h, lift))

    print('\n■ 블라인드 날짜 구간의 약세 사례에서도 통하는가 (최종 확인)')
    bl_bear = [r for r in bear if r.get('split') == 'blind']
    bb = stats(bl_bear)
    if not bb:
        print('  블라인드 구간에 약세 사례가 없습니다 — 확인 불가.')
    else:
        print(f"  블라인드 약세 기준선 n={bb['n']} 적중 {bb['hit']:.1f}%")
        for name, fn, d, h, lift in list(winners):
            s = stats([r for r in bl_bear if fn(r)])
            if not s:
                print(f"  · {name}: 표본 0건 → 확인 불가 (채택 보류)")
                winners = [w for w in winners if w[0] != name]
                continue
            bl = s['hit'] - bb['hit']
            print(f"  · {name}: n={s['n']} 적중 {s['hit']:.1f}% "
                  f"(lift {bl:+.1f}%p) 비용후 {s['net']:+.2f}%")
            if bl <= 0:
                print('    → 블라인드 lift 음수 · 채택 취소')
                winners = [w for w in winners if w[0] != name]

    print('\n' + '=' * 70)
    if winners:
        print(f"판정: 채택 {len(winners)}개 — 본 적 없는 종목에서도 약세 국면 "
              "기준선을 이겼습니다.")
        for name, fn, d, h, lift in winners:
            print(f"  · {name} — 홀드아웃 {h['hit']:.1f}% (lift {lift:+.1f}%p, "
                  f"n={h['n']}) · 비용후 {h['net']:+.2f}%")
        print("\n적용 방식: 약세 국면에서만 쓰는 **조건부** 규칙이다. "
              "다른 국면의 판정에는 손대지 않는다.")
    else:
        print('판정: 채택 없음 — 홀드아웃 종목에서 기준을 넘지 못했습니다.')
    print('=' * 70)
    return 0 if winners else 1


if __name__ == '__main__':
    sys.exit(main())
