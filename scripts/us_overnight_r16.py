# -*- coding: utf-8 -*-
"""
라운드 16 — 전날 미국장이 우리 판단에 얼마나 영향을 주는가.

사용자 지시: "미장 영향 많이 받으니까 미리 전날에 영향받으면 조심할 수
있도록 해 달라."

맞는 직관이다. 다만 '많이 받는다'를 느낌이 아니라 숫자로 확인해야 조심할
기준을 만들 수 있다. 확인할 것:
  ① 전날 미국장(S&P·나스닥) 등락이 다음 날 우리 판단 성적을 가르는가
  ② 가른다면 어느 선부터 조심해야 하는가
  ③ 그 선을 게이트로 걸면 기대값이 나아지는가

데이터: Yahoo Finance 에서 ^GSPC · ^IXIC 일봉을 받아 각 사례의 기준일
**직전 미국 거래일** 등락률을 붙인다. 한국 시장은 미국보다 먼저 열리므로,
기준일 D 의 한국 판단이 참조할 수 있는 미국장은 D−1 종가다 (누수 없음).

사전등록 (측정 전 고정):
  구간    : 전날 S&P 등락률을 −2%↓ / −2~−0.5% / −0.5~+0.5% / +0.5~+2% / +2%↑
  1차     : 각 구간 학습 표본 300건+
  채택    : 특정 구간의 성적이 나쁘고 그 구간을 빼면
            **검증·블라인드 양쪽에서** 비용 차감 후 기대값이 개선될 것
            + 남는 신호가 전체의 60% 이상 (기회를 절반 넘게 없애면 안 된다)
  실패 시 : 게이트를 만들지 않고, '전날 미국장' 을 화면 참고 정보로만 둔다.
"""
from __future__ import annotations

import io
import json
import os
import sys
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(BASE, '.portfolio', 'virtual_graded.jsonl')
CACHE = os.path.join(BASE, 'data', 'us_index_daily.json')
OUT = os.path.join(BASE, '.portfolio', 'us_overnight.json')

COST = 0.30
BUY = 58
MIN_TRAIN_N = 300
MIN_KEEP = 60.0

BANDS = [(-99.0, -2.0, '급락 (−2%↓)'), (-2.0, -0.5, '하락 (−2~−0.5%)'),
         (-0.5, 0.5, '보합 (±0.5%)'), (0.5, 2.0, '상승 (+0.5~+2%)'),
         (2.0, 99.0, '급등 (+2%↑)')]


def fetch_us(symbol='%5EGSPC'):
    """야후에서 일봉 종가를 받아 {날짜: 등락률%} 로 만든다."""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?interval=1d&range=10y")
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        j = json.load(r)
    res = j['chart']['result'][0]
    ts = res['timestamp']
    close = res['indicators']['quote'][0]['close']
    import datetime as dt
    out = {}
    prev = None
    for t, c in zip(ts, close):
        if c is None:
            continue
        d = dt.datetime.utcfromtimestamp(t).strftime('%Y-%m-%d')
        if prev is not None and prev > 0:
            out[d] = round(100.0 * (c - prev) / prev, 3)
        prev = c
    return out


def load_us():
    if os.path.exists(CACHE):
        try:
            with open(CACHE, encoding='utf-8') as f:
                d = json.load(f)
            if d.get('sp500'):
                return d
        except Exception:
            pass
    print('야후에서 미국 지수 일봉 수집 중…')
    d = {'sp500': fetch_us('%5EGSPC')}
    try:
        d['nasdaq'] = fetch_us('%5EIXIC')
    except Exception:
        d['nasdaq'] = {}
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, 'w', encoding='utf-8') as f:
        json.dump(d, f)
    print(f"  S&P {len(d['sp500'])}일 · 나스닥 {len(d.get('nasdaq') or {})}일 저장")
    return d


def prev_us(us, date_str, back=7):
    """기준일 직전 미국 거래일의 등락률 (누수 방지: 당일은 쓰지 않는다)."""
    import datetime as dt
    try:
        d = dt.date.fromisoformat(date_str)
    except Exception:
        return None
    for i in range(1, back + 1):
        k = (d - dt.timedelta(days=i)).isoformat()
        if k in us:
            return us[k]
    return None


def band_of(pct):
    if pct is None:
        return None
    for lo, hi, ko in BANDS:
        if lo <= pct < hi:
            return ko
    return None


def ev(rows):
    n = len(rows)
    if not n:
        return None
    rets = [float(r['return_pct']) for r in rows]
    win = [v for v in rets if v > 0]
    loss = [v for v in rets if v <= 0]
    g, p = sum(win), abs(sum(loss))
    hit = sum(1 for r in rows if r['success'])
    return {'n': n, 'hit': round(100.0 * hit / n, 1),
            'ev': round(sum(rets) / n - COST, 3),
            'pf': round((g / p) if p > 0 else (99.0 if g else 0.0), 2)}


def main():
    us = load_us()['sp500']
    rows = []
    with open(LEDGER, encoding='utf-8') as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get('success') is None or (r.get('score') or 0) < BUY:
                continue
            r['_us'] = prev_us(us, str(r.get('date') or ''))
            r['_band'] = band_of(r['_us'])
            rows.append(r)

    matched = [r for r in rows if r['_band']]
    print(f"매수권 {len(rows):,}건 중 전날 미국장을 붙인 것 {len(matched):,}건 "
          f"({100.0 * len(matched) / max(1, len(rows)):.0f}%)\n")

    by = {s: [r for r in matched if r.get('split') == s]
          for s in ('train', 'valid', 'blind')}
    base = {s: ev(by[s]) for s in by}
    print('■ 기준선 (전날 미국장 조건 없음)')
    for s, ko in (('train', '학습'), ('valid', '검증'), ('blind', '블라인드')):
        m = base[s]
        if m:
            print(f"  {ko:5s} n={m['n']:4d} 적중 {m['hit']:5.1f}% "
                  f"비용후 {m['ev']:+.3f}% PF {m['pf']:.2f}")

    print('\n■ 전날 미국장 등락별 성적')
    print('  구간                 학습(n·적중·EV)        검증               블라인드')
    band_stats = {}
    for _lo, _hi, ko in BANDS:
        cells = {s: ev([r for r in by[s] if r['_band'] == ko]) for s in by}
        band_stats[ko] = cells
        def f(m):
            return (f"{m['n']:4d} {m['hit']:5.1f}% {m['ev']:+6.2f}%"
                    if m else '     표본 없음     ')
        print(f"  {ko:18s} {f(cells['train'])}  {f(cells['valid'])}  "
              f"{f(cells['blind'])}")

    print('\n■ 게이트 판정 — 나쁜 구간을 빼면 나아지는가')
    adopted = []
    for _lo, _hi, ko in BANDS:
        tr = band_stats[ko]['train']
        if not tr or tr['n'] < MIN_TRAIN_N:
            continue
        # 이 구간을 제외했을 때
        kept = {s: [r for r in by[s] if r['_band'] != ko] for s in by}
        k = {s: ev(kept[s]) for s in by}
        if not (k['valid'] and k['blind']):
            continue
        keep_rate = 100.0 * k['blind']['n'] / max(1, base['blind']['n'])
        g = [('검증 개선', k['valid']['ev'] > base['valid']['ev']),
             ('실전 개선', k['blind']['ev'] > base['blind']['ev']),
             ('신호 유지', keep_rate >= MIN_KEEP)]
        ok = all(x[1] for x in g)
        miss = ' '.join(x[0] for x in g if not x[1])
        print(f"  '{ko}' 제외 → 검증 {k['valid']['ev']:+.3f}% · "
              f"실전 {k['blind']['ev']:+.3f}% · 남는 신호 {keep_rate:.0f}%  "
              f"{'채택 가능' if ok else '미달: ' + miss}")
        if ok:
            adopted.append((ko, k))

    print('\n' + '=' * 80)
    if adopted:
        adopted.sort(key=lambda x: -x[1]['blind']['ev'])
        ko, k = adopted[0]
        print(f"판정: 채택 — 전날 미국장이 '{ko}' 이면 매수 신호를 내지 않는다")
        print(f"  검증 {base['valid']['ev']:+.3f}% → {k['valid']['ev']:+.3f}% · "
              f"실전 {base['blind']['ev']:+.3f}% → {k['blind']['ev']:+.3f}%")
    else:
        print('판정: 게이트 없음 — 전날 미국장으로 걸러도 기준을 넘지 못했다.')
        print('     그래도 화면에는 참고 정보로 표시한다 (사용자가 직접 판단).')
    print('=' * 80)

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump({'baseline': base, 'bands': band_stats,
                   'gate': (adopted[0][0] if adopted else None),
                   'coverage': round(100.0 * len(matched) / max(1, len(rows)), 1),
                   'criteria': ['검증 개선', '실전 개선',
                                f'남는 신호 {MIN_KEEP}%+']},
                  f, ensure_ascii=False, indent=1)
    print(f'\n저장: {OUT}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
