# -*- coding: utf-8 -*-
"""GANEUM DAY — 분봉 수집 (라운드 516 · 2026-10-13). **조회만 · 주문 없음 · 정규장 중엔 안 돈다.**

    python scripts/collect_minute_bars.py --codes 005930,000660 --days 5            계획만(기본 · 네트워크 없음)
    python scripts/collect_minute_bars.py --codes 005930,000660 --days 5 --apply    실제로 받아 이 PC 의 연구 원장에 덧붙인다
    python scripts/collect_minute_bars.py --universe forward --days 1 --apply       전방 기록기가 마지막 판정일에 본 종목들
    python scripts/collect_minute_bars.py --universe forward-pit --apply            날마다 **그날** 전방 기록기가 본 종목들(라운드 521)
    python scripts/collect_minute_bars.py --universe pool --days 260 --backfill --apply   연구 원장의 고정 목록 · 오래 도는 백필(라운드 527)

■ 라운드 527 — 사용자 결정(2026-10-13 · *"분봉 받아줘"*): 연구 원장 랩의 **고정 목록**(`calibration_lab` 의 TICKERS + HOLDOUT +
  EXPANSION · 코드로 거른 599종목 · 2026-08 에 정해진 목록이라 분봉 결과를 보고 고른 것이 아니다 — 다만 그때까지 살아남은 종목이라는
  약한 선택 편향은 남는다)을 한국투자가 두는 만큼(약 1년) 받는다. 약 15만 (종목, 날짜) · 건당 약 0.77초라 **수십 시간**이다. 그래서
  `--backfill` 은 ① **오래된 날부터** 받는다(보관 1년의 끝이 날마다 지워진다 — 그쪽부터) ② 바퀴마다 멈출 자리를 본다(`backfill_block` ·
  워커가 도는 장 시간 · 저녁 작업 · 디스크) — 멈추면 받은 만큼 남고 다음 실행이 이어 받는다 ③ 한 번에 하나만 돈다(잠금 파일 · 저녁
  작업의 분봉 단계도 같은 잠금을 본다 — 같은 종목 파일에 두 프로세스가 덧붙이지 않게) ④ 연속 실패가 이어지면 멈춘다(연결이 끊겼는데
  15만 건을 실패로 훑지 않게) ⑤ 기록은 `.portfolio/day_bars/_backfill_run.txt`.

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


# ── 라운드 527 — 오래 도는 백필 ─────────────────────────────────────────────────────────────────────────
#: 멈출 자리 — 전부 **운영 값**이다(판정 문턱 아님). 근거는 이미 정해진 시각에서 온다.
#:   워커 예약 작업이 평일 08:50 에 뜬다(register_swing_worker_task.ps1 · 라운드 452) → 그 10분 전에 멈춘다(같은 앱 키의 호출 간격).
WORKER_LEAD = '08:40'
#:   워커는 마감 뒤 한 바퀴(체결 맞춤)를 더 돈다(라운드 452·462) → 그날 마감(엔진 한 곳 · 수능일 16:30) 뒤 이만큼은 비켜 둔다.
AFTER_CLOSE_MIN = 30
#:   저녁 작업이 평일 21:00 에 뜬다(register_watch_refresh_task.ps1 · 라운드 486) → 10분 전에 멈추고, 그 기록에 끝 줄이 생길 때까지 안 돈다.
NIGHTLY_LEAD = '20:50'
#:   그 작업은 작업 스케줄러가 3시간에 끊는다(같은 등록 스크립트의 ExecutionTimeLimit) — 끝 줄 없이 그보다 오래면 끊긴 것으로 본다.
NIGHTLY_LIMIT_H = 3
#:   디스크 여유가 이보다 적으면 멈춘다(15만 건이면 약 10GB · 이 PC 는 디스크가 0바이트가 된 적이 있다).
DISK_FLOOR_GB = 20
#:   연속 실패가 이만큼이면 멈춘다(연결이 끊겼는데 남은 15만 건을 실패로 훑지 않게 · 실패한 쌍은 완료로 안 적혀 다음 실행이 다시 받는다).
MAX_CONSEC_ERR = 20
LOCK_NAME = '_collect.lock'
BACKFILL_LOG = '_backfill_run.txt'


def pool_codes(lab_path=None):
    """연구 원장 랩의 고정 목록 → 종목코드 6자리(랩의 차례 · 같은 코드는 앞에 든 것 · `calibration_lab.dedupe_by_code` 와 같은 규칙).

    목록은 랩 한 곳에 있다 — 손으로 다시 적지 않는다. 랩을 가져오면 엔진 전체가 따라오므로 그 세 목록의 **글자**를 AST 로 읽는다.
    못 읽으면 [] (지어 채우지 않는다)."""
    import ast
    from ledger_view import code6
    p = lab_path or os.path.join(PROJ, 'scripts', 'calibration_lab.py')
    try:
        tree = ast.parse(io.open(p, encoding='utf-8').read())
    except (OSError, SyntaxError, ValueError):
        return []
    lists = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in ('TICKERS', 'HOLDOUT_TICKERS', 'EXPANSION_TICKERS') and isinstance(node.value, ast.List)):
            lists[node.targets[0].id] = [e.value for e in node.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    if len(lists) != 3:
        return []
    out, seen = [], set()
    for t in lists['TICKERS'] + lists['HOLDOUT_TICKERS'] + lists['EXPANSION_TICKERS']:
        c = code6(t)
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _hhmm(s):
    return _dt.time(int(s[:2]), int(s[3:5]))


def nightly_running(now, status=None):
    """저녁 작업이 지금 도는가 — 그 기록의 시작 줄 뒤에 끝 줄이 없고 시작이 NIGHTLY_LIMIT_H 안이면 True. 못 읽으면 None."""
    if status is None:
        try:
            import swing_ops
            status = swing_ops.nightly_status()
        except Exception:                                      # noqa: BLE001
            return None
    if status.get('running') is None:
        return None
    if not status.get('running'):
        return False
    st = str(status.get('last_start') or '')                   # 'MM-DD HH:MM:SS' — 기록은 연도를 안 적는다
    try:
        t = _dt.datetime(now.year, int(st[:2]), int(st[3:5]), int(st[6:8]), int(st[9:11]), int(st[12:14]), tzinfo=now.tzinfo)
    except (ValueError, IndexError):
        return True                                            # 시작 시각을 못 읽으면 도는 중으로 본다(비켜 가는 쪽)
    if t > now:
        t = t.replace(year=now.year - 1)
    return (now - t) < _dt.timedelta(hours=NIGHTLY_LIMIT_H)


def backfill_block(now, nightly=None, free_gb=None, trading=None, close=None):
    """오래 도는 백필이 지금 멈춰야 하는 사유 → 문장(멈출 필요 없으면 None). 끼워 넣을 수 있다(시험).

    now 는 한국 시각. 거래일이면 [WORKER_LEAD, 마감 + AFTER_CLOSE_MIN) 동안 · 평일이면 [NIGHTLY_LEAD, 21:00) 동안 · 저녁 작업이
    도는 동안 · 디스크 여유가 DISK_FLOOR_GB 아래면 멈춘다. 장 시각과 휴장일은 엔진·달력 한 곳에서 읽는다."""
    day = now.date().isoformat()
    if trading is None:
        from improvement.case_tracker import is_non_trading_date
        trading = not is_non_trading_date(day)
    t = now.time().replace(tzinfo=None)
    if trading:
        if close is None:
            import swing_executor as X
            close = X._session_times(now.date())[1]
        end = (_dt.datetime.combine(now.date(), close) + _dt.timedelta(minutes=AFTER_CLOSE_MIN)).time()
        if _hhmm(WORKER_LEAD) <= t < end:
            return f'장 시간(워커 {WORKER_LEAD}~마감 뒤 {AFTER_CLOSE_MIN}분 · 같은 앱 키)'
    if now.weekday() < 5 and _hhmm(NIGHTLY_LEAD) <= t < _dt.time(21, 0):
        return f'저녁 작업 직전({NIGHTLY_LEAD}~21:00)'
    if nightly is None:
        nightly = nightly_running(now)
    if nightly:
        return '저녁 작업이 도는 중(끝 줄이 생기면 다음 실행이 이어 받는다)'
    if free_gb is None:
        import shutil
        try:
            free_gb = shutil.disk_usage(day_bars.ROOT if os.path.isdir(day_bars.ROOT) else PROJ).free / 1e9
        except OSError:
            free_gb = None
    if free_gb is not None and free_gb < DISK_FLOOR_GB:
        return f'디스크 여유 {free_gb:.1f}GB < {DISK_FLOOR_GB}GB'
    return None


def _pid_alive(pid):
    """워커와 같은 판별(한 곳 · `scripts.run_swing_worker._pid_alive`). 못 가르면 None."""
    try:
        from scripts.run_swing_worker import _pid_alive as _alive
        return _alive(pid)
    except Exception:                                          # noqa: BLE001
        return None


def lock_acquire(root=None, pid=None):
    """한 번에 하나만 — (잡았나, 주인 pid). 주인이 죽은 잠금은 치우고 다시 잡는다. 주인이 살았는지 못 가르면 못 잡은 것으로 본다."""
    d = root or day_bars.ROOT
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, LOCK_NAME)
    me = int(pid or os.getpid())
    for _ in range(2):
        try:
            fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                owner = int(io.open(p, encoding='utf-8').read().strip() or 0)
            except (OSError, ValueError):
                owner = 0
            if owner and owner != me and _pid_alive(owner) is not False:
                return False, owner
            try:                                               # 빈 파일이 막 생겼다 — 남이 만들고 pid 를 아직 안 적은 순간일 수 있다
                if not owner and time.time() - os.path.getmtime(p) < 5:
                    return False, None
            except OSError:
                pass
            try:
                os.remove(p)                                   # 주인이 죽었다(또는 빈 파일) — 치우고 한 번 더
            except OSError:
                return False, owner
            continue
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(str(me))
        return True, me
    return False, None


def lock_release(root=None, pid=None):
    p = os.path.join(root or day_bars.ROOT, LOCK_NAME)
    try:
        if int(io.open(p, encoding='utf-8').read().strip() or 0) == int(pid or os.getpid()):
            os.remove(p)
    except (OSError, ValueError):
        pass


class _Tee:
    """백필 기록 — 표준출력이 있으면 거기에도(작업 스케줄러의 pythonw 는 표준출력이 없다)."""

    def __init__(self, path, also=None):
        self.f = io.open(path, 'a', encoding='utf-8')
        self.also = also

    def write(self, s):
        self.f.write(s)
        self.f.flush()
        if self.also is not None:
            try:
                self.also.write(s)
            except Exception:                                  # noqa: BLE001
                pass
        return len(s)

    def flush(self):
        self.f.flush()
        if self.also is not None:
            try:
                self.also.flush()
            except Exception:                                  # noqa: BLE001
                pass


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):                     # 라운드 521 — 표준출력이 바뀐 자리(시험·pythonw)에서도 죽지 않는다
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    ap = argparse.ArgumentParser()
    ap.add_argument('--codes', default='', help='쉼표로 이은 종목코드')
    ap.add_argument('--universe', default='', choices=['', 'forward', 'forward-pit', 'pool'],
                    help='forward = 전방 기록기가 마지막 판정일에 본 종목 · forward-pit = 날마다 그날 전방 기록기가 본 종목 · '
                         'pool = 연구 원장 랩의 고정 목록(라운드 527)')
    ap.add_argument('--backfill', action='store_true',
                    help='오래 도는 백필 — 장 시간·저녁 작업·디스크 부족이면 멈추고(0) 다음 실행이 이어 받는다 · 기록은 _backfill_run.txt (라운드 527)')
    ap.add_argument('--days', type=int, default=None,
                    help='판정일부터 거슬러 받을 거래일 수(기본 1 · forward-pit 은 기본 전부 — 전방 기록부가 있는 날)')
    ap.add_argument('--registry', default='', help='전방 기록부 경로(시험용 · 비우면 .portfolio)')
    ap.add_argument('--nightly', action='store_true',
                    help='저녁 작업 — 장중·연결 정보 없음이면 받지 않고 0 으로 끝난다(실패로 세지 않는다)')
    ap.add_argument('--end', default='', help='끝 날짜(ISO) — 비우면 판정일')
    ap.add_argument('--apply', action='store_true', help='실제로 받아 적는다(없으면 계획만)')
    ap.add_argument('--max-stocks', type=int, default=0)
    a = ap.parse_args(argv)
    _out527 = sys.stdout
    if a.backfill and a.apply and os.environ.get('GAEUM_NO_LOCAL_WRITE') != '1':
        os.makedirs(day_bars.ROOT, exist_ok=True)
        sys.stdout = _Tee(os.path.join(day_bars.ROOT, BACKFILL_LOG), also=_out527)
        print(f'[{_dt.datetime.now().strftime("%m-%d %H:%M:%S")}] 백필 시작 · pid {os.getpid()} · 인자 {" ".join(argv if argv is not None else sys.argv[1:])}')
    try:
        return _main(a)
    except BaseException:
        if sys.stdout is not _out527:                          # 백필 기록이 열려 있으면 그 자리에 남긴다(작업 스케줄러의 pythonw 는 표준오류가 없다)
            import traceback
            traceback.print_exc(file=sys.stdout)
        raise
    finally:
        if sys.stdout is not _out527:
            try:
                sys.stdout.f.close()
            except Exception:                                  # noqa: BLE001
                pass
            sys.stdout = _out527


def _main(a):
    codes = [c.strip() for c in a.codes.split(',') if c.strip()]
    pit = {}
    if a.universe == 'pool':
        got = pool_codes()
        if not got:
            print('연구 원장 랩의 고정 목록을 못 읽었다 — 받지 않는다')
            return 2
        codes += [c for c in got if c not in codes]
    elif a.universe == 'forward':
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
        # 라운드 527 — 날 먼저 · 오래된 날부터: 보관 1년의 끝이 날마다 지워지므로 그쪽을 먼저 받는다(멈췄다 이어 받아도 잃는 날이 없게)
        pairs = [(c, d) for d in days for c in codes]
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
    import swing_executor as _X527
    if a.backfill:
        why = backfill_block(_X527.now_kst())
        if why:
            print(f'[멈춤] {why} — 지금은 안 받는다 · 다음 실행이 이어 받는다')
            return 0
    import broker_kis
    try:
        cfg = broker_kis.load_config()
        br = broker_kis.KisBroker(cfg)
    except Exception as e:                                     # noqa: BLE001 — 연결 정보가 없으면 받지 않는다(지어 받지 않는다)
        print(f'한국투자 연결 정보가 없거나 못 읽었다 — 받지 않는다 · {type(e).__name__}: {str(e)[:120]}')
        return 0 if a.nightly else 2
    ok_lock, owner = lock_acquire()
    if not ok_lock:
        print(f'다른 분봉 수집이 돌고 있다(pid {owner}) — 같은 종목 파일에 둘이 덧붙이지 않게 이번엔 안 받는다')
        return 0 if (a.nightly or a.backfill) else 4
    try:
        return _collect(a, br, todo)
    finally:
        lock_release()


def _collect(a, br, todo):
    import swing_executor as _X527
    t0 = time.time()
    tot = dict(ok=0, partial=0, err=0, bars=0, added=0, calls=0, none=0)
    keys_by_code = {}                                         # 라운드 520 — 종목 파일은 한 번만 읽고 열쇠를 들고 다닌다
    # 라운드 527 — 백필은 날 먼저 599종목을 돌므로 종목 열쇠를 다 들고 다니면 수천만 개가 메모리에 남는다. 그 날만 · 기록이 있는 날만 읽는다.
    touched = day_bars.touched_set() if a.backfill else None
    consec, stopped = 0, None
    for i, (code, day) in enumerate(todo, 1):
        if a.backfill:
            # 바퀴마다 시각을 본다 · 저녁 작업 기록과 디스크는 20건마다(파일·디스크를 매 건 읽지 않는다 · 20건 ≈ 15초)
            heavy = (i % 20 == 1)
            why = backfill_block(_X527.now_kst(), nightly=None if heavy else False, free_gb=None if heavy else DISK_FLOOR_GB + 1)
            if why:
                stopped = why
                break
        try:
            bars, info = day_feed.fetch_day(br, code, day)
        except Exception as e:                                 # noqa: BLE001 — 한 종목의 실패가 전체를 멈추지 않는다 · 사유를 남긴다
            tot['err'] += 1
            day_bars.log_fetched(dict(code=code, day=day, complete=False, err=f'{type(e).__name__}: {str(e)[:160]}',
                                      at=_dt.datetime.now().astimezone().isoformat(timespec='seconds')))
            print(f'  {code} {day} 실패 — {type(e).__name__}: {str(e)[:120]}')
            consec += 1
            if a.backfill and consec >= MAX_CONSEC_ERR:
                stopped = f'연속 실패 {consec}건(연결·토큰을 볼 것)'
                break
            continue
        consec = 0
        if touched is not None:
            keys = day_bars.existing_keys_day(code, day) if (code, day) in touched else set()
            if bars:                                           # 덧붙이기 직전 표시 — 덧붙이고 기록 전에 끊겨도 다음 실행이 그 날 열쇠를 읽는다
                day_bars.log_fetched(dict(code=code, day=day, pending=True,
                                          at=_dt.datetime.now().astimezone().isoformat(timespec='seconds')))
        else:
            if code not in keys_by_code:
                keys_by_code[code] = day_bars.existing_keys(code)
            keys = keys_by_code[code]
        added, dup = day_bars.append_bars(code, bars, keys=keys)
        n, first, last = day_bars.day_summary(bars)
        tot['calls'] += info['calls']
        tot['bars'] += n
        tot['added'] += added
        tot['ok' if info['complete'] else ('none' if info.get('none') else 'partial')] += 1
        day_bars.log_fetched(dict(code=code, day=day, n=n, first=first, last=last, calls=info['calls'], complete=info['complete'],
                                  stop=info['stop'], none=bool(info.get('none')), raw=info['raw'], other_day=info['other_day'],
                                  rejects=info['rejects'],
                                  added=added, dup=dup, at=_dt.datetime.now().astimezone().isoformat(timespec='seconds')))
        every = 200 if a.backfill else 20                      # 백필 기록은 줄을 아낀다(15만 건)
        if i % every == 0 or i == len(todo):
            stamp = f'[{_dt.datetime.now().strftime("%m-%d %H:%M:%S")}] ' if a.backfill else '  '
            print(f'{stamp}{i}/{len(todo)} · {day} · 봉 {tot["bars"]:,} · 더함 {tot["added"]:,} · 호출 {tot["calls"]:,} · '
                  f'{time.time() - t0:.0f}초')
    if stopped:
        print(f'[멈춤] {stopped} — 받은 만큼 남는다 · 남은 {len(todo) - tot["ok"] - tot["none"] - tot["partial"] - tot["err"]:,}건은 다음 실행이 이어 받는다')
    print(f'[끝] 완료 {tot["ok"]} · 봉 없음(답) {tot["none"]} · 덜 받음 {tot["partial"]} · 실패 {tot["err"]} · 봉 {tot["bars"]:,} · '
          f'더함 {tot["added"]:,} · '
          f'호출 {tot["calls"]:,} · {time.time() - t0:.0f}초')
    return 0 if tot['err'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
