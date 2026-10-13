# -*- coding: utf-8 -*-
"""GANEUM DAY — 분봉 수집 (라운드 516 · 2026-10-13). **조회만 · 주문 없음 · 정규장 중엔 안 돈다.**

    python scripts/collect_minute_bars.py --codes 005930,000660 --days 5            계획만(기본 · 네트워크 없음)
    python scripts/collect_minute_bars.py --codes 005930,000660 --days 5 --apply    실제로 받아 이 PC 의 연구 원장에 덧붙인다
    python scripts/collect_minute_bars.py --universe forward --days 1 --apply       전방 기록기가 마지막 판정일에 본 종목들
    python scripts/collect_minute_bars.py --universe forward-pit --apply            날마다 **그날** 전방 기록기가 본 종목들(라운드 521)

■ 라운드 521 — 대상 규칙: **그날** 전방 기록기가 본 상위 60(시총 순 · 이미 채택된 규칙 · 그날 기준이라 오늘의 큰 종목으로
  과거를 거슬러 고르는 선택 편향이 없다). 전방 기록부가 있는 날(2026-08-09~)만 · 매일 저녁 작업이 이어 받는다(`--nightly` ·
  정규장 중이거나 연결 정보가 없으면 받지 않고 0 으로 끝난다 — 저녁 작업의 실패로 세지 않는다). 한국투자는 분봉을 약 1년만
  둔다 — 그날 받지 않은 날은 1년 뒤 영영 못 받는다(소급이 안 되는 자료 · 라운드 341 의 그 모양).

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


def split_unfinal(todo, unfinal):
    """(종목, 날짜) 목록 → (받을 것, 확정 전이라 건너뛸 것). 라운드 520 — 2026-10-13 15:3x 에 받은 그날 분봉은 15:19 까지였다(마감
    동시호가 15:30 봉이 아직 없었다) · 그런데 09:00 봉에 닿아 '완료'로 적혀 빠진 채 굳을 자리였다. 확정 판정은 한 곳
    (`prediction_log.unfinal_day` · 애프터마켓 20:00 뒤 확정 · 라운드 490)을 쓴다 — 새 시각을 고르지 않는다."""
    if not unfinal:
        return list(todo), []
    keep = [(c, d) for c, d in todo if d != unfinal]
    return keep, [(c, d) for c, d in todo if d == unfinal]


def forward_codes_by_day(path=None):
    """전방 기록부 → {기준일: [종목코드 …]}(그날 기록한 차례 그대로 · 중복 없이). 못 읽으면 {}. 손으로 고르지 않는다(라운드 521)."""
    p = path or os.path.join(PROJ, '.portfolio', 'forward_registry.jsonl')
    out = {}
    try:
        with io.open(p, encoding='utf-8') as f:
            for ln in f:
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                day = str(r.get('as_of') or r.get('date') or '')[:10]
                c = str(r.get('code') or r.get('ticker') or '').split('.')[0]
                if len(day) == 10 and c:
                    lst = out.setdefault(day, [])
                    if c not in lst:
                        lst.append(c)
    except OSError:
        return {}
    return out


def in_session(now=None):
    import swing_executor as X
    return X.session_open(now or X.now_kst())


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):                     # 라운드 521 — 표준출력이 바뀐 자리(시험·pythonw)에서도 죽지 않는다
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    ap = argparse.ArgumentParser()
    ap.add_argument('--codes', default='', help='쉼표로 이은 종목코드')
    ap.add_argument('--universe', default='', choices=['', 'forward', 'forward-pit'],
                    help='forward = 전방 기록기가 마지막 판정일에 본 종목 · forward-pit = 날마다 그날 전방 기록기가 본 종목')
    ap.add_argument('--days', type=int, default=None,
                    help='판정일부터 거슬러 받을 거래일 수(기본 1 · forward-pit 은 기본 전부 — 전방 기록부가 있는 날)')
    ap.add_argument('--registry', default='', help='전방 기록부 경로(시험용 · 비우면 .portfolio)')
    ap.add_argument('--nightly', action='store_true',
                    help='저녁 작업 — 장중·연결 정보 없음이면 받지 않고 0 으로 끝난다(실패로 세지 않는다)')
    ap.add_argument('--end', default='', help='끝 날짜(ISO) — 비우면 판정일')
    ap.add_argument('--apply', action='store_true', help='실제로 받아 적는다(없으면 계획만)')
    ap.add_argument('--max-stocks', type=int, default=0)
    a = ap.parse_args(argv)

    codes = [c.strip() for c in a.codes.split(',') if c.strip()]
    pit = {}
    if a.universe == 'forward':
        codes += [c for c in forward_codes(a.registry or None) if c not in codes]
    elif a.universe == 'forward-pit':
        pit = forward_codes_by_day(a.registry or None)
        if not pit:
            print('전방 기록부를 못 읽었다(또는 비었다) — 받지 않는다')
            return 0 if a.nightly else 2
        for d in sorted(pit):
            codes += [c for c in pit[d] if c not in codes]
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
    if pit:
        days = sorted(d for d in pit if d <= str(end))
        if a.days:
            days = days[-a.days:]
        if not days:
            print(f'전방 기록부에 {end} 이전 날이 없다 — 받지 않는다')
            return 0
        pairs = [(c, d) for d in days for c in pit[d] if c in codes]
    else:
        days = trading_days_back(end, a.days or 1)
        pairs = [(c, d) for c in codes for d in days]
    done = day_bars.fetched_set()
    todo = [(c, d) for c, d in pairs if (c, d) not in done]
    already = len(pairs) - len(todo)                             # 이어 받기로 건너뛰는 것(완료·'없다'는 답) — 확정 전 건너뜀과 따로 센다
    import prediction_log
    todo, unfin = split_unfinal(todo, prediction_log.unfinal_day())
    if unfin:
        print(f'[건너뜀] {unfin[0][1]} — 그날 봉이 아직 확정 전이다(애프터마켓 20:00 뒤) · {len(unfin)}건은 다음 실행이 받는다')
    print(f'[계획] 종목 {len(codes)} · 거래일 {len(days)}({days[0]}~{days[-1]}) · 받을 (종목, 날짜) {len(todo)} · 이미 받음 '
          f'{already} · 확정 전 건너뜀 {len(unfin)} · 예상 호출 약 {len(todo) * 4}회(하루 약 381봉 ÷ 120)')
    if not a.apply:
        print('[계획만] --apply 를 주면 실제로 받는다')
        return 0
    if os.environ.get('GAEUM_NO_LOCAL_WRITE') == '1':
        print('쓰기 금지 — 받지 않는다')
        return 0
    if not todo:
        print('[끝] 받을 것이 없다')
        return 0
    if in_session():
        print('정규장 중이다 — 워커와 같은 앱 키의 호출 간격을 나눠 쓰므로 장중엔 안 받는다(장 마감 뒤에 다시)')
        return 0 if a.nightly else 3
    import broker_kis
    try:
        cfg = broker_kis.load_config()
        br = broker_kis.KisBroker(cfg)
    except Exception as e:                                     # noqa: BLE001 — 연결 정보가 없으면 받지 않는다(지어 받지 않는다)
        print(f'한국투자 연결 정보가 없거나 못 읽었다 — 받지 않는다 · {type(e).__name__}: {str(e)[:120]}')
        return 0 if a.nightly else 2
    t0 = time.time()
    tot = dict(ok=0, partial=0, err=0, bars=0, added=0, calls=0, none=0)
    keys_by_code = {}                                         # 라운드 520 — 종목 파일은 한 번만 읽고 열쇠를 들고 다닌다
    for i, (code, day) in enumerate(todo, 1):
        try:
            bars, info = day_feed.fetch_day(br, code, day)
        except Exception as e:                                 # noqa: BLE001 — 한 종목의 실패가 전체를 멈추지 않는다 · 사유를 남긴다
            tot['err'] += 1
            day_bars.log_fetched(dict(code=code, day=day, complete=False, err=f'{type(e).__name__}: {str(e)[:160]}',
                                      at=_dt.datetime.now().astimezone().isoformat(timespec='seconds')))
            print(f'  {code} {day} 실패 — {type(e).__name__}: {str(e)[:120]}')
            continue
        if code not in keys_by_code:
            keys_by_code[code] = day_bars.existing_keys(code)
        added, dup = day_bars.append_bars(code, bars, keys=keys_by_code[code])
        n, first, last = day_bars.day_summary(bars)
        tot['calls'] += info['calls']
        tot['bars'] += n
        tot['added'] += added
        tot['ok' if info['complete'] else ('none' if info.get('none') else 'partial')] += 1
        day_bars.log_fetched(dict(code=code, day=day, n=n, first=first, last=last, calls=info['calls'], complete=info['complete'],
                                  stop=info['stop'], none=bool(info.get('none')), raw=info['raw'], other_day=info['other_day'],
                                  rejects=info['rejects'],
                                  added=added, dup=dup, at=_dt.datetime.now().astimezone().isoformat(timespec='seconds')))
        if i % 20 == 0 or i == len(todo):
            print(f'  {i}/{len(todo)} · 봉 {tot["bars"]:,} · 더함 {tot["added"]:,} · 호출 {tot["calls"]:,} · {time.time() - t0:.0f}초')
    print(f'[끝] 완료 {tot["ok"]} · 봉 없음(답) {tot["none"]} · 덜 받음 {tot["partial"]} · 실패 {tot["err"]} · 봉 {tot["bars"]:,} · '
          f'더함 {tot["added"]:,} · '
          f'호출 {tot["calls"]:,} · {time.time() - t0:.0f}초')
    return 0 if tot['err'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
