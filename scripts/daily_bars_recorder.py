# -*- coding: utf-8 -*-
"""유니버스 주식의 일봉을 받아 박제한다 — 순수 이벤트 창 연구(R148)의 재료.

한계를 먼저 적는다 (사전등록이 그대로 인용한다):
  - 네이버 fchart 는 **3,000봉 하드 상한**이다 (count=6000 을 줘도
    3,000행 · 2026-08-22 기준 2014-05-30 부터). 2011~2014-05 는 못 받는다.
    FDR 의 야후 경로는 이 버전에서 막혀 있고, 엔진 캐시도 없다.
  - 유니버스는 2026-08-10 에 뽑은 시총 상위 1,500 의 **생존 종목**이다.
    그 사이 상폐된 종목의 이벤트는 애초에 표본에 없다 — 생존 편향.
  - ETF 는 뺀다 (DART 공시 주체가 아니다 — R146).
지수(KS11·KQ11)는 FDR 로 전 기간을 받는다.

측정 전용 — 점수·게이트·문턱을 바꾸지 않는다. 운영 코드가 읽지 않는다.

    C:/Python314/python.exe scripts/daily_bars_recorder.py [--refresh]
"""
import io
import json
import os
import re
import sys
import time
from datetime import date

import requests

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(PROJ, '.portfolio', 'daily_bars.jsonl')
UNIV = os.path.join(PROJ, '.portfolio', 'universe_top1500.json')
MASTER = os.path.join(PROJ, '.portfolio', 'name_master.json')
H = {'User-Agent': 'Mozilla/5.0'}
_ITEM = re.compile(r'<item data="([^"]+)"')


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def fetch_naver(code, count=3000):
    r = requests.get('https://fchart.stock.naver.com/sise.nhn?symbol='
                     f'{code}&timeframe=day&count={count}&requestType=0',
                     headers=H, timeout=20)
    r.raise_for_status()
    bars = []
    for it in _ITEM.findall(r.text):
        p = it.split('|')
        if len(p) < 6 or not p[0]:
            continue
        try:
            bars.append([f'{p[0][:4]}-{p[0][4:6]}-{p[0][6:8]}',
                         float(p[1]), float(p[2]), float(p[3]), float(p[4]),
                         float(p[5])])
        except ValueError:
            continue
    return bars


def fetch_index(sym):
    import FinanceDataReader as fdr
    df = fdr.DataReader(sym, '2010-12-01')
    return [[d.strftime('%Y-%m-%d'), float(r.Open), float(r.High),
             float(r.Low), float(r.Close), float(r.Volume)]
            for d, r in df.iterrows()]


def main():
    refresh = '--refresh' in sys.argv
    with open(UNIV, encoding='utf-8') as f:
        univ = json.load(f)['symbols']
    with open(MASTER, encoding='utf-8') as f:
        etf = set(json.load(f).get('etf_codes') or [])
    targets = [(s.split('.')[0], 'KOSPI' if s.endswith('.KS') else 'KOSDAQ')
               for s in univ if s.split('.')[0] not in etf]
    have = set()
    if os.path.exists(OUT) and not refresh:
        with open(OUT, encoding='utf-8') as f:
            for ln in f:
                try:
                    have.add(json.loads(ln)['code'])
                except Exception:                              # noqa: BLE001
                    pass
    print(f'일봉 박제 — 주식 {len(targets):,}종목 (ETF {len(univ) - len(targets)} 제외)'
          f' · 이미 있음 {len(have):,} · 기준일 {date.today().isoformat()}')
    mode = 'w' if refresh else 'a'
    n_new = n_fail = 0
    firsts = []
    t0 = time.time()
    with open(OUT, mode, encoding='utf-8') as out:
        for sym, mkt in (('KS11', 'INDEX'), ('KQ11', 'INDEX')):
            if sym in have:
                continue
            try:
                bars = fetch_index(sym)
                out.write(json.dumps(dict(code=sym, mkt=mkt, n=len(bars),
                                          first=bars[0][0], last=bars[-1][0],
                                          bars=bars), ensure_ascii=False) + '\n')
                print(f'   {sym}: {len(bars):,}봉 {bars[0][0]} ~ {bars[-1][0]}')
            except Exception as e:                             # noqa: BLE001
                print(f'   {sym}: 실패 — {type(e).__name__}')
                out.write(json.dumps(dict(code=sym, mkt=mkt, n=0, bars=None,
                                          error=type(e).__name__)) + '\n')
        for i, (code, mkt) in enumerate(targets, 1):
            if code in have:
                continue
            try:
                bars = fetch_naver(code)
                if not bars:
                    raise ValueError('empty')
                out.write(json.dumps(dict(code=code, mkt=mkt, n=len(bars),
                                          first=bars[0][0], last=bars[-1][0],
                                          bars=bars), ensure_ascii=False) + '\n')
                firsts.append(bars[0][0])
                n_new += 1
            except Exception as e:                             # noqa: BLE001
                n_fail += 1
                out.write(json.dumps(dict(code=code, mkt=mkt, n=0, bars=None,
                                          error=type(e).__name__)) + '\n')
            if i % 100 == 0:
                print(f'   {i:,}/{len(targets):,} · 새로 {n_new:,} · 실패 {n_fail}'
                      f' · {time.time() - t0:.0f}s')
            time.sleep(0.15)
    print()
    print(f'■ 새로 {n_new:,}종목 · 실패 {n_fail} · {time.time() - t0:.0f}s')
    if firsts:
        firsts.sort()
        print(f'   첫 봉 분포: 최소 {firsts[0]} · 중앙 {firsts[len(firsts) // 2]}'
              f' · 최대 {firsts[-1]}')
        late = sum(1 for x in firsts if x > '2014-06-30')
        print(f'   2014-06 이후에 시작하는 종목(신규 상장): {late:,}')
    print(f'저장: {OUT}')
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
