# -*- coding: utf-8 -*-
"""가늠 PROOF 성적표를 만든다 — 남긴 판정 전부를 같은 채점기로 채점하고 **수만** 담는다 (라운드 418).

    python scripts/proof_scorecard.py            # 채점하고 .portfolio/proof_scorecard.json 에 쓴다
    python scripts/proof_scorecard.py --dry-run  # 채점만 하고 안 쓴다

규칙은 `proof` 모듈 머리에 고정돼 있다(같은 채점기 · 운영 비용 · 판정 1건에 같은 금액 · 문턱 없음).
이 PC 의 평일 장 마감 뒤 작업(`scripts/nightly_local.py`)이 돈다. 일봉은 종목마다 한 번 받는다.
`GAEUM_NO_LOCAL_WRITE` 면 쓰지 않는다(§9).
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import sqlite3
import sys
import time

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:                                              # noqa: BLE001
    pass
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)
os.chdir(PROJ)

import proof                                                   # noqa: E402
import prediction_log as plog                                  # noqa: E402


def tracker_cases(db_path=None):
    """추적 DB 의 케이스 — 복사본·픽스처·휴장일 기준일은 뺀다(`case_tracker.tally` 와 같은 규칙 · §4)."""
    from improvement import case_tracker as ct
    p = db_path or os.path.join(PROJ, '.portfolio', 'improvement.db')
    if not os.path.exists(p):
        return []
    c = sqlite3.connect(p)
    try:
        rows = c.execute('SELECT ticker, signal_date, status, realized_return FROM prediction_cases').fetchall()
    finally:
        c.close()
    return [dict(ticker=t, signal_date=str(d)[:10], status=s, realized_return=r) for t, d, s, r in rows
            if s not in ct.EXCLUDED_STATUSES and not ct.is_non_trading_date(str(d)[:10])]


def report_checks(pm_dir=None):
    """날짜별 개장 전 리포트의 후보 → {(코드6, 날짜): core.checks}."""
    out = {}
    for f in glob.glob(os.path.join(pm_dir or os.path.join(PROJ, '.portfolio'), 'premarket_2*.json')):
        try:
            with open(f, encoding='utf-8') as fh:
                d = json.load(fh)
        except Exception:                                      # noqa: BLE001
            continue
        for pk in d.get('picks') or []:
            ck = (pk.get('core') or {}).get('checks')
            if ck:
                out.setdefault((proof.code6(pk.get('symbol') or pk.get('code')), str(d.get('date'))[:10]), ck)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args(argv)
    write = not a.dry_run and not os.environ.get('GAEUM_NO_LOCAL_WRITE')
    t0 = time.time()
    rows = plog.load_predictions()
    tickers = sorted({str(r.get('ticker')) for r in rows if r.get('ticker')})
    print(f'판정 원장 {len(rows):,}건 · 종목 {len(tickers)} · 쓰기 {"함" if write else "안 함"}', flush=True)
    from bitemporal_engine import BitemporalEngine
    eng = BitemporalEngine()
    bars, fail = {}, []
    for i, tk in enumerate(tickers, 1):
        try:
            bars[tk] = proof.bars_frame(eng.fetch_daily_bars(tk))
        except Exception as ex:                                # noqa: BLE001
            bars[tk] = None
            fail.append((tk, f'{type(ex).__name__}'))
        if i % 50 == 0:
            print(f'  일봉 {i}/{len(tickers)} · {time.time() - t0:.0f}초', flush=True)
    graded = [(r, proof.outcome(r, bars.get(str(r.get('ticker'))))) for r in rows]
    ab = proof.abstain_tally(graded)
    by_action = {}
    for act in sorted({str(r.get('action')) for r in rows}):
        by_action[act] = proof.abstain_tally([(r, o) for r, o in graded if str(r.get('action')) == act])
    st = collections.Counter((o or {}).get('status', 'nobars') for _r, o in graded)
    gates = proof.gate_ledger(tracker_cases(), report_checks())
    doc = dict(made=proof.now_iso(), ledger_rows=len(rows), tickers=len(tickers),
               bars_ok=sum(1 for v in bars.values() if v is not None), bars_fail=len(fail),
               status=dict(st), abstain=ab, by_action=by_action, gates=gates,
               tracker_decided=sum(1 for c in tracker_cases() if c['status'] in ('success', 'failure', 'unresolved')),
               rule=('같은 채점기(기록 가격 진입 · 먼저 닿은 선 · 같은 봉이면 손절 먼저 · 20봉 만료면 그날 종가) · '
                     f"운영 비용 {ab.get('cost_pct')}% 차감 · 판정 1건에 같은 금액 · 문턱 없음"),
               seconds=round(time.time() - t0, 1))
    print(proof.abstain_line(ab))
    print('결과 갈래', dict(st), '· 일봉 실패', len(fail))
    for act, t in by_action.items():
        print(f'  {act}: 결정 {t["decided"]} · 평균 {t["mean_net"]} · 중앙 {t["median_net"]}')
    print('규칙 원장(앞 6)')
    for g in gates[:6]:
        b, p = g['blocked'], g['passed']
        print(f"  {g['name']}: 막음 n {b['n']} 평균 {b['mean_net'] if b['mean_net'] is None else round(b['mean_net'], 2)}"
              f" · 통과 n {p['n']} 평균 {p['mean_net'] if p['mean_net'] is None else round(p['mean_net'], 2)}")
    if write:
        proof.save_scorecard(doc)
        print('썼다', proof.SCORECARD_FILE)
    print(f'{doc["seconds"]}초')
    return 0


if __name__ == '__main__':
    sys.exit(main())
