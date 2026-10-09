# -*- coding: utf-8 -*-
"""
뉴스 축 사전등록을 열 수 있나 — 갈래별 거래일을 **결과를 읽지 않고** 센다 (라운드 473).

일정 문서(`docs/SCHEDULE_R223_AXES.md`)는 *"확정 케이스 30건 · 거래일 30 이상이면 '위험 낱말이 있는 추천은 없는 추천보다
못한가'를 사전등록한다"* 고 적었다. 2026-10-10 에 세니 그 **전체** 조건은 이미 찼다(확정 243건 · 거래일 44). 그런데 비교는
두 갈래가 하고, 표본은 날짜이며(R45·R80), 비교를 정하는 것은 **작은 쪽**이다(R129). 그래서 하한(30 · R84 재사용 · 새 숫자
아님)을 **두 갈래 각각의 거래일**에 댄다.

갈래 — 위험 낱말이 있던 추천 / 없던 추천(**피드를 받은 날만**). 리포트 후보는 라운드 473 전까지 피드를 못 받은 날도
'위험 낱말 0'으로 적었다 — 그 줄은 '없던 쪽'에 넣지 않고 따로 센다(§3 · 못 잰 것을 '없음'으로 읽지 않는다). 위험 낱말이
있었다면 피드는 받은 것이므로 그 줄은 옛 줄이어도 '있던 쪽'이다.

출처 둘을 따로 센다(섞지 않는다):
  · 추적 케이스 — `improvement.db` 의 확정 케이스(성공·실패·미결 · 거래일 기준일만) ↔ 그날 개장 전 리포트 후보의 뉴스 칸
  · 전방 기록부 — `forward_registry.jsonl` 의 행(피드 상태 칸이 처음부터 있다 · 결과는 11-16 채점기가 일봉으로 낸다)

결과(성공·실패·수익)는 읽지 않는다 — 상태는 '확정됐는가'를 고르는 데만 쓴다. 사전등록 전에 결과를 보면 §2 다.
"""
import glob
import json
import os
import sqlite3
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)

#: 하한 — 라운드 84 의 날짜 하한 재사용(새 숫자 아님)
DATE_FLOOR = 30
RISK, CLEAN, NOFEED, UNKNOWN = '위험 낱말 있음', '위험 낱말 없음(피드 받음)', '피드 못 받음', '피드 상태 모름(옛 줄 · 0)'


def group_of(pick):
    """후보·기록부 행 하나 → 갈래 이름. 뉴스 칸 자체가 없으면 None."""
    if pick is None:
        return None
    risk = pick.get('news_risk')
    feed = pick.get('news_feed_ok')
    if feed is False:
        return NOFEED
    if risk is None:
        return None if feed is None else UNKNOWN
    try:
        r = int(risk)
    except (TypeError, ValueError):
        return None
    if r > 0:
        return RISK
    return CLEAN if feed is True else UNKNOWN


def count(items):
    """items: [(거래일, 행)] → {갈래: {'cases': n, 'dates': n}} · 열림 여부(두 비교 갈래 모두 하한 이상)."""
    out = {}
    for day, pick in items:
        g = group_of(pick) or '뉴스 칸 없음'
        b = out.setdefault(g, {'cases': 0, 'dates': set()})
        b['cases'] += 1
        b['dates'].add(day)
    res = {g: {'cases': b['cases'], 'dates': len(b['dates'])} for g, b in out.items()}
    small = min(res.get(RISK, {}).get('dates', 0), res.get(CLEAN, {}).get('dates', 0))
    return res, small, small >= DATE_FLOOR


def tracker_items(db=None, pm_dir=None):
    """확정 추적 케이스(거래일 기준일) ↔ 그 자료 기준일 개장 전 리포트 후보."""
    import premarket
    from improvement import case_tracker as ct
    db = db or os.path.join(PROJ, '.portfolio', 'improvement.db')
    conn = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    try:
        rows = conn.execute('SELECT ticker, signal_date, status FROM prediction_cases').fetchall()
    finally:
        conn.close()
    picks = {}
    for p in sorted(glob.glob(os.path.join(pm_dir or premarket.PM_DIR, 'premarket_*.json'))):
        try:
            with open(p, encoding='utf-8') as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        dd = premarket.data_day_of(d)
        for pk in d.get('picks') or []:
            picks[(str(pk.get('symbol') or pk.get('code') or '')[:6], dd)] = pk
    out = []
    for t, d, st in rows:
        day = str(d)[:10]
        if st in ('success', 'failure', 'unresolved') and not ct.is_non_trading_date(day):
            out.append((day, picks.get((str(t)[:6], day))))
    return out


def window_closed(day, horizon, anchor, is_closed_day):
    """그 행의 결과 창(거래일 horizon 개)이 판정일 anchor 까지 다 지났나. 결과는 안 읽는다 — 날짜만 센다.
    거래일은 휴장일 판정 한 곳(`is_closed_day`)으로 센다. 판정일을 못 구하면 False(모르면 닫혔다고 안 한다 · §3)."""
    import datetime as _dt
    if not (day and anchor and horizon):
        return False
    d = _dt.date.fromisoformat(day)
    a = _dt.date.fromisoformat(str(anchor)[:10])
    n = 0
    while d < a and n < horizon:
        d += _dt.timedelta(days=1)
        if not is_closed_day(d.isoformat()):
            n += 1
    return n >= horizon


def registry_items(path=None, anchor=None):
    """전방 기록부의 거래일 행 중 **결과 창이 닫힌** 행만(창이 안 닫힌 날을 세면 잴 수 없는 날을 표본으로 센다)."""
    from improvement import case_tracker as ct
    path = path or os.path.join(PROJ, '.portfolio', 'forward_registry.jsonl')
    if anchor is None:
        try:
            from scripts.trading_day import anchor_day
            anchor = anchor_day()
        except Exception:                                  # noqa: BLE001
            anchor = None
    out = []
    with open(path, encoding='utf-8') as f:
        for ln in f:
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            day = str(r.get('date') or '')[:10]
            if day and not ct.is_non_trading_date(day) and window_closed(
                    day, int(r.get('horizon_days') or 20), anchor, ct.is_non_trading_date):
                out.append((day, r))
    return out


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:                                          # noqa: BLE001
        pass
    for name, fn in (('추적 케이스(확정)', tracker_items), ('전방 기록부', registry_items)):
        try:
            res, small, ok = count(fn())
        except Exception as e:                                 # noqa: BLE001
            print(f'{name} — 못 셌다: {type(e).__name__}: {e}')
            continue
        print(f'{name} — 작은 비교 갈래의 거래일 {small} · 하한 {DATE_FLOOR} → {"열 수 있다(사전등록 먼저)" if ok else "아직 아니다"}')
        for g, v in sorted(res.items()):
            print(f'  {g}: 케이스 {v["cases"]:,} · 거래일 {v["dates"]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
