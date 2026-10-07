# -*- coding: utf-8 -*-
"""실전 추천 추적 케이스의 기준일을 **자료 기준일**로 옮긴다 (라운드 442 · 한 번 · 멱등).

■ 왜 (2026-10-07 실측)
  개장 전 리포트의 열쇠가 연 날(벽시계 날짜)이었고, 동결은 그 날짜를 기준일로 썼다. 그런데 리포트의 가격은 스캔이 쓴
  자료 기준일(마지막으로 장이 끝난 거래일)의 종가다. 장 전·자정 넘어 연 리포트는 날짜 D · 가격은 D-1 종가라, 채점이
  **D 다음 봉부터** 돌아 리포트가 겨냥한 거래일 D 가 통째로 빠졌다(케이스 364건 · 그중 복사본이 아닌 233건이 이 모양).
  그리고 같은 자료가 저녁 판(D)과 다음 날 아침 판(D+1) 두 날짜로 동결돼 **같은 추천이 두 번** 세어졌다(확정 32건 ·
  휴장일 판은 라운드 389 가 이미 뺐다). 원장(`calibration_lab`)·종목 판정 기록(`prediction_log`)은 자료 기준일을 쓴다(§4).

■ 무엇을 하나 — 지우지 않는다 (R197)
  · 케이스가 만들어진 이력 줄(옛 줄 · 같은 (날짜, 종목)의 첫 줄)에서 자료 기준일을 `premarket.data_day_of` 로 구한다.
  · 자료 기준일이 기준일과 다르면 기준일을 옮기고 원래 날짜를 `orig_signal_date` 에 남긴다.
      - 확정된 케이스는 **같은 채점기**(`prediction_log.grade_prediction` → `resolution_from_grade`)로 다시 채점한다
        (라운드 232 의 재환산과 같은 길 · 가격·목표·손절·보유기간은 그대로 · 바뀌는 것은 채점 창의 시작뿐).
      - 아직 open 이면 옮기기만 한다 — 일일 루틴이 새 기준일로 채점한다.
  · 옮긴 뒤 같은 (종목, 자료 기준일)에 케이스가 둘 이상이면 하나만 남기고 나머지는 `dup_version`(복사본 · 갈래에서
    빠진다)으로 표시하고 원본 case_id 를 사유에 적는다. 남기는 것: 이미 그 날짜에 있던 것 → 먼저 동결된 것.
  · 자료 기준일을 못 구하면(이력 줄이 없다 · 생성 시각을 못 읽는다) 건드리지 않고 센다(§3).
  · 일봉을 못 받은 종목은 그 종목 케이스를 하나도 안 건드린다(채점을 못 하면 옮기지도 않는다) — 다음에 다시 돌면 된다.
  · 이미 옮긴 케이스(`orig_signal_date` 있음)는 다시 안 본다 — **두 번 돌려도 같다**.
  · 새 규칙으로 동결된 케이스(이력에 `day_basis='data'` 줄이 있는 (날짜, 종목))는 이미 자료 기준일이라 안 본다.

  기본은 미리보기 — DB 를 메모리에 복사해 거기에 적용하고 전·후 집계(`case_tracker.tally`)를 찍는다.
  `--apply` 면 원본을 먼저 복사해 두고(.r442.bak) 고친다.

    C:/Python314/python.exe scripts/rekey_tracker_basis.py [--apply] [--db PATH] [--history PATH]
"""
import argparse
import collections
import datetime as dt
import json
import os
import shutil
import sqlite3
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:                                              # noqa: BLE001
    pass
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)

import premarket as pm                                         # noqa: E402
from improvement import case_tracker as ct                     # noqa: E402

DEFAULT_DB = os.path.join(PROJ, '.portfolio', 'improvement.db')
DEFAULT_HISTORY = os.path.join(PROJ, '.portfolio', 'premarket_history.jsonl')
DUP = 'dup_version'
DECIDED = ('success', 'failure', 'unresolved')


def history_index(path):
    """(옛 줄의 날짜, 종목) → 그 줄(첫 줄) · 새 규칙 줄의 (날짜, 종목) 집합. 파일이 없으면 None."""
    if not path or not os.path.exists(path):
        return None
    old, new = {}, set()
    with open(path, encoding='utf-8') as f:
        for line in f:
            try:
                h = json.loads(line)
            except Exception:                                  # noqa: BLE001
                continue
            k = (str(h.get('date') or '')[:10], str(h.get('symbol') or ''))
            if h.get('day_basis') == pm.DAY_BASIS:
                new.add(k)
            else:
                old.setdefault(k, h)
    return old, new


def ensure_column(conn):
    try:
        conn.execute("ALTER TABLE prediction_cases ADD COLUMN orig_signal_date TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass                                                   # 이미 있다 (멱등)


def plan(conn, hist):
    """할 일 목록 · 센 수. 각 할 일은 dict(case_id, ticker, old, new, kind='rekey'|'dup', keeper, row)."""
    old_idx, new_keys = hist
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM prediction_cases")]
    cnt = collections.Counter()
    final = {}                       # case_id → (ticker, 기준일 · 옮긴 뒤)
    moves = {}                       # case_id → 새 기준일
    for r in rows:
        if r['status'] in ct.EXCLUDED_STATUSES:
            cnt['이미 복사본·픽스처 — 안 봄'] += 1
            continue
        sd = str(r['signal_date'])[:10]
        final[r['case_id']] = (str(r['ticker']), sd)
        if r.get('orig_signal_date'):
            cnt['이미 옮김 — 안 봄'] += 1
            continue
        k = (sd, str(r['ticker']))
        if k in new_keys:
            cnt['새 규칙으로 동결됨 — 이미 자료 기준일'] += 1
            continue
        h = old_idx.get(k)
        dd = pm.data_day_of(h) if h else None
        if not dd:
            cnt['자료 기준일 못 구함 — 그대로 둠'] += 1
            continue
        if dd == sd:
            cnt['기준일 = 자료 기준일 — 그대로'] += 1
            continue
        moves[r['case_id']] = dd
        final[r['case_id']] = (str(r['ticker']), dd)
    by_id = {r['case_id']: r for r in rows}
    groups = collections.defaultdict(list)
    for cid, key in final.items():
        groups[key].append(cid)
    actions = []
    for key, cids in groups.items():
        # 남길 것: 이미 그 날짜에 있던 것(옮기지 않는 것) → 먼저 동결된 것 → case_id
        cids.sort(key=lambda c: (c in moves, str(by_id[c]['created_at']), c))
        keeper = cids[0]
        for c in cids:
            if c not in moves:
                continue
            r = by_id[c]
            actions.append(dict(case_id=c, ticker=str(r['ticker']), old=str(r['signal_date'])[:10], new=moves[c],
                                kind=('rekey' if c == keeper else 'dup'), keeper=keeper, row=r))
    cnt['옮김 · 남김'] = sum(1 for a in actions if a['kind'] == 'rekey')
    cnt['옮김 · 복사본으로 표시'] = sum(1 for a in actions if a['kind'] == 'dup')
    return actions, cnt


def _bars(eng, ticker, cache):
    if ticker not in cache:
        try:
            cache[ticker] = eng.fetch_daily_bars(ticker)
        except Exception:                                      # noqa: BLE001
            cache[ticker] = None
    return cache[ticker]


def apply(conn, actions, eng):
    """할 일을 적용한다 · 센 수를 돌려준다. 일봉을 못 받은 종목의 할 일은 하나도 안 한다."""
    import prediction_log as plog
    from improvement.performance import resolution_from_grade
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    cnt = collections.Counter()
    cache = {}
    need = {a['ticker'] for a in actions if a['kind'] == 'rekey' and a['row']['status'] in DECIDED}
    bad = {t for t in need if _bars(eng, t, cache) is None}
    for a in actions:
        r = a['row']
        if a['ticker'] in bad:
            cnt['일봉 못 받음 — 그 종목은 안 건드림'] += 1
            continue
        if a['kind'] == 'dup':
            conn.execute(
                "UPDATE prediction_cases SET signal_date=?, orig_signal_date=?, status=?, result_reason=?, resolved_at=? "
                "WHERE case_id=?",
                (a['new'], a['old'], DUP,
                 f"R442 — 같은 자료 기준일({a['new']})의 같은 추천이 다른 날짜({a['old']})로 한 번 더 동결됨 "
                 f"(원본 {a['keeper']})", now, a['case_id']))
            cnt['복사본 표시'] += 1
            continue
        if r['status'] not in DECIDED:
            conn.execute("UPDATE prediction_cases SET signal_date=?, orig_signal_date=? WHERE case_id=?",
                         (a['new'], a['old'], a['case_id']))
            cnt[f"옮김 · {r['status']} 그대로(일일 루틴이 새 기준일로 채점)"] += 1
            continue
        if not (r['target_price'] and r['stop_price']):
            conn.execute("UPDATE prediction_cases SET signal_date=?, orig_signal_date=? WHERE case_id=?",
                         (a['new'], a['old'], a['case_id']))
            cnt['옮김 · 목표·손절 없음(채점 안 함)'] += 1
            continue
        g = plog.grade_prediction(
            {'date': a['new'], 'price': float(r['reference_price']), 'target': float(r['target_price']),
             'stop': float(r['stop_price']), 'horizon_days': int(r['holding_days'])}, cache[a['ticker']])
        if not g:
            cnt['채점 못 함 — 안 건드림'] += 1
            continue
        if g['outcome'] == 'OPEN' and not g['matured']:
            conn.execute(
                "UPDATE prediction_cases SET signal_date=?, orig_signal_date=?, status='open', exit_price=NULL, "
                "realized_return=NULL, max_drawdown=NULL, result_reason=NULL, resolved_at=NULL WHERE case_id=?",
                (a['new'], a['old'], a['case_id']))
            cnt[f"옮김 · {r['status']} → open"] += 1
            continue
        res = resolution_from_grade(g, target_price=float(r['target_price']), stop_price=float(r['stop_price']))
        conn.execute(
            "UPDATE prediction_cases SET signal_date=?, orig_signal_date=?, status=?, exit_price=?, realized_return=?, "
            "max_drawdown=?, result_reason=? WHERE case_id=?",
            (a['new'], a['old'], res.status, res.exit_price, res.realized_return, res.max_drawdown,
             f"{res.reason} · R442 기준일 재환산(옛 기준일 {a['old']})", a['case_id']))
        cnt[f"옮김 · {r['status']} → {res.status}"] += 1
    conn.commit()
    return cnt


def _engine():
    import bitemporal_engine as be
    for nm in dir(be):
        if 'Engine' in nm:
            return getattr(be, nm)()
    raise RuntimeError('엔진 클래스를 못 찾았다')


def _tally_line(t):
    return (f"성공 {t['success']} · 실패 {t['failure']} · 미도달 {t['unresolved']} · open {t['open']} · "
            f"뺀 수 {t['excluded']} · 휴장일 기준일 {t['non_trading']} · 거래일 고유 기준일 {t['trading_dates']} · "
            f"성공률 {('%.1f%%' % t['success_pct']) if t['success_pct'] is not None else '없음'}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=DEFAULT_DB)
    ap.add_argument('--history', default=DEFAULT_HISTORY)
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args(argv)
    if not os.path.exists(a.db):
        print('DB 없음:', a.db)
        return 1
    hist = history_index(a.history)
    if hist is None:
        print('리포트 이력 없음:', a.history, '— 자료 기준일을 구할 수 없어 아무것도 안 한다')
        return 1
    if a.apply:
        bak = a.db + '.r442.bak'
        if not os.path.exists(bak):
            shutil.copy2(a.db, bak)
            print('백업:', bak)
        conn = sqlite3.connect(a.db)
    else:
        src = sqlite3.connect(f'file:{a.db}?mode=ro', uri=True)
        conn = sqlite3.connect(':memory:')
        src.backup(conn)
        src.close()
    ensure_column(conn)
    conn.row_factory = sqlite3.Row
    before = ct.tally(conn)
    actions, cnt = plan(conn, hist)
    for k, n in cnt.items():
        print(f'  {k:40s} {n}')
    done = apply(conn, actions, _engine()) if actions else collections.Counter()
    for k, n in sorted(done.items()):
        print(f'  {k:40s} {n}')
    after = ct.tally(conn)
    real = conn.execute(
        f"SELECT COUNT(*) FROM prediction_cases WHERE status NOT IN ({','.join('?' * len(ct.EXCLUDED_STATUSES))})",
        ct.EXCLUDED_STATUSES).fetchone()[0]
    distinct = conn.execute(
        "SELECT COUNT(*) FROM (SELECT DISTINCT ticker, signal_date FROM prediction_cases "
        f"WHERE status NOT IN ({','.join('?' * len(ct.EXCLUDED_STATUSES))}))", ct.EXCLUDED_STATUSES).fetchone()[0]
    print('전:', _tally_line(before))
    print('후:', _tally_line(after))
    print(f'실제 케이스 {real} = 고유 (종목, 기준일) {distinct} → {"일치" if real == distinct else "불일치!"}')
    print('적용함' if a.apply else '미리보기 — 원본은 안 바뀌었다 (--apply 로 적용)')
    conn.close()
    return 0 if real == distinct else 2


if __name__ == '__main__':
    sys.exit(main())
