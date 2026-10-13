# -*- coding: utf-8 -*-
"""GANEUM DAY — 분봉 수집 (라운드 516 · 2026-10-13). **조회만 · 주문 없음 · 정규장 중엔 안 돈다.**

    python scripts/collect_minute_bars.py --codes 005930,000660 --days 5            계획만(기본 · 네트워크 없음)
    python scripts/collect_minute_bars.py --codes 005930,000660 --days 5 --apply    실제로 받아 이 PC 의 연구 원장에 덧붙인다
    python scripts/collect_minute_bars.py --universe forward --days 1 --apply       전방 기록기가 마지막 판정일에 본 종목들

■ 정규장 중엔 거절한다 — 워커(보호 매도·체결 맞춤)와 같은 앱 키의 호출 간격을 나눠 쓰므로, 장중에 수백 번 부르면 워커의 조회가 밀린다.
■ 이어 받기 — 받아 온 기록(`_fetched.jsonl`)에 '완료'로 적힌 (종목, 날짜) 는 다시 안 부른다. 완료 = 그날 09:00 봉까지 닿았다(사실 ·
  문턱 아님). 원장은 (날짜, 시각) 열쇠로 중복을 막는다(멱등).
■ 쓰기 금지(GAEUM_NO_LOCAL_WRITE=1)면 받지도 적지도 않는다.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import io
import json
import os
import sys
import time

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)

import day_bars  # noqa: E402
import day_feed  # noqa: E402


def trading_days_back(end_day, n):
    """end_day(ISO · 포함)부터 거슬러 거래일 n 개(오래된 것부터). 휴장일 판정은 한 곳(`case_tracker`)."""
    from improvement.case_tracker import is_non_trading_date
    out, d = [], _dt.date.fromisoformat(str(end_day))
    guard = 0
    while len(out) < n and guard < n * 3 + 30:
        if not is_non_trading_date(d.isoformat()):
            out.append(d.isoformat())
        d -= _dt.timedelta(days=1)
        guard += 1
    return sorted(out)


def forward_codes(path=None):
    """전방 기록기(fr-1)가 마지막 판정일에 기록한 종목들 — 손으로 고르지 않는다. 못 읽으면 []."""
    p = path or os.path.join(PROJ, '.portfolio', 'forward_registry.jsonl')
    rows = []
    try:
        with io.open(p, encoding='utf-8') as f:
            for ln in f:
                try:
                    rows.append(json.loads(ln))
                except ValueError:
                    continue
    except OSError:
        return []
    if not rows:
        return []
    key = 'as_of' if 'as_of' in rows[-1] else 'date'
    last = max(str(r.get(key) or '') for r in rows)
    codes = []
    for r in rows:
        if str(r.get(key) or '') == last:
            c = str(r.get('code') or r.get('ticker') or '').split('.')[0]
            if c and c not in codes:
                codes.append(c)
    return codes


def in_session(now=None):
    import swing_executor as X
    return X.session_open(now or X.now_kst())


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    ap = argparse.ArgumentParser()
    ap.add_argument('--codes', default='', help='쉼표로 이은 종목코드')
    ap.add_argument('--universe', default='', choices=['', 'forward'], help='forward = 전방 기록기가 마지막 판정일에 본 종목')
    ap.add_argument('--days', type=int, default=1, help='판정일(마지막으로 장이 끝난 거래일)부터 거슬러 받을 거래일 수')
    ap.add_argument('--end', default='', help='끝 날짜(ISO) — 비우면 판정일')
    ap.add_argument('--apply', action='store_true', help='실제로 받아 적는다(없으면 계획만)')
    ap.add_argument('--max-stocks', type=int, default=0)
    a = ap.parse_args(argv)

    codes = [c.strip() for c in a.codes.split(',') if c.strip()]
    if a.universe == 'forward':
        codes += [c for c in forward_codes() if c not in codes]
    if a.max_stocks:
        codes = codes[:a.max_stocks]
    if not codes:
        print('종목이 없다 — --codes 또는 --universe 를 준다')
        return 2
    end = a.end
    if not end:
        sys.path.insert(0, os.path.join(PROJ, 'scripts'))
        from trading_day import anchor_day
        end = anchor_day()
        if not end:
            print('판정일을 못 구했다 — --end 로 준다')
            return 2
    days = trading_days_back(end, a.days)
    done = day_bars.fetched_set()
    todo = [(c, d) for c in codes for d in days if (c, d) not in done]
    print(f'[계획] 종목 {len(codes)} · 거래일 {len(days)}({days[0]}~{days[-1]}) · 받을 (종목, 날짜) {len(todo)} · 이미 완료 '
          f'{len(codes) * len(days) - len(todo)} · 예상 호출 약 {len(todo) * 4}회(하루 약 381봉 ÷ 120)')
    if not a.apply:
        print('[계획만] --apply 를 주면 실제로 받는다')
        return 0
    if os.environ.get('GAEUM_NO_LOCAL_WRITE') == '1':
        print('쓰기 금지 — 받지 않는다')
        return 0
    if in_session():
        print('정규장 중이다 — 워커와 같은 앱 키의 호출 간격을 나눠 쓰므로 장중엔 안 받는다(장 마감 뒤에 다시)')
        return 3
    import broker_kis
    cfg = broker_kis.load_config()
    br = broker_kis.KisBroker(cfg)
    t0 = time.time()
    tot = dict(ok=0, partial=0, err=0, bars=0, added=0, calls=0)
    for i, (code, day) in enumerate(todo, 1):
        try:
            bars, info = day_feed.fetch_day(br, code, day)
        except Exception as e:                                 # noqa: BLE001 — 한 종목의 실패가 전체를 멈추지 않는다 · 사유를 남긴다
            tot['err'] += 1
            day_bars.log_fetched(dict(code=code, day=day, complete=False, err=f'{type(e).__name__}: {str(e)[:160]}',
                                      at=_dt.datetime.now().astimezone().isoformat(timespec='seconds')))
            print(f'  {code} {day} 실패 — {type(e).__name__}: {str(e)[:120]}')
            continue
        added, dup = day_bars.append_bars(code, bars)
        n, first, last = day_bars.day_summary(bars)
        tot['calls'] += info['calls']
        tot['bars'] += n
        tot['added'] += added
        tot['ok' if info['complete'] else 'partial'] += 1
        day_bars.log_fetched(dict(code=code, day=day, n=n, first=first, last=last, calls=info['calls'], complete=info['complete'],
                                  stop=info['stop'], raw=info['raw'], other_day=info['other_day'], rejects=info['rejects'],
                                  added=added, dup=dup, at=_dt.datetime.now().astimezone().isoformat(timespec='seconds')))
        if i % 20 == 0 or i == len(todo):
            print(f'  {i}/{len(todo)} · 봉 {tot["bars"]:,} · 더함 {tot["added"]:,} · 호출 {tot["calls"]:,} · {time.time() - t0:.0f}초')
    print(f'[끝] 완료 {tot["ok"]} · 덜 받음 {tot["partial"]} · 실패 {tot["err"]} · 봉 {tot["bars"]:,} · 더함 {tot["added"]:,} · '
          f'호출 {tot["calls"]:,} · {time.time() - t0:.0f}초')
    return 0 if tot['err'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
