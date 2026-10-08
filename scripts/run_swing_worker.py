# -*- coding: utf-8 -*-
"""
스윙 자동매매 워커 (라운드 446) — 화면은 관제실이고 **주문은 여기서만** 낸다.

    python scripts/run_swing_worker.py --once                한 바퀴
    python scripts/run_swing_worker.py --loop 60             60초마다(끌 때까지) — 장중에 켜 둔다
    python scripts/run_swing_worker.py --once --no-orders    주문 없이 계획·모의·내역·계좌만 맞춘다(저녁 작업)
    python scripts/run_swing_worker.py --session --loop 60   오늘 정규장 마감까지 60초마다 돌고, 마감 뒤 한 바퀴(체결 내역 맞춤) 더
                                                             돌고 끝난다 — 작업 스케줄러가 평일 아침에 부른다(라운드 452 ·
                                                             scripts/register_swing_worker_task.ps1). 휴장일이면 아무것도 안 하고 끝난다.

화면(Streamlit)이 주문 반복을 돌리면 새로고침·세션 종료·rerun 에 끊긴다 — 그래서 따로 돈다. 같은 장부(`.portfolio/swing.db`)를
화면과 같이 읽고 쓴다. 두 워커가 동시에 돌지 않게 잠금 파일을 **원자적으로** 만든다(O_EXCL). 반복 모드는 잠금이 잡혀 있으면 꺼지지
않고 다음 간격에 다시 해 본다 — 저녁 작업이 잠깐 잡고 있다고 그날 보호가 사라지지 않게(2026-10-08 독립 검토).

⚠️ 작업 스케줄러 등록은 `scripts/register_swing_worker_task.ps1` 한 번(라운드 452 — 라운드 414·415 의 저녁 작업과 같은 모양 ·
Claude 예약 작업이 아니다). 설정 화면의 모드가 꺼짐·기록만이면 증권사에 아무것도 안 보낸다 — 그래서 등록돼 있어도 켜기 전엔 아무 일도 없다.
자격증명은 저장소 밖(환경변수 또는 ~/.gaeum/kis.env)에서만 읽는다. 쓰기 금지(GAEUM_NO_LOCAL_WRITE=1)면 장부를 안 열고 끝난다.
"""
import argparse
import datetime as _dt
import io
import os
import sys
import time

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)

LOCK = os.path.join(PROJ, '.portfolio', 'swing_worker.lock')
RUNLOG = os.path.join(PROJ, '.portfolio', 'swing_worker_run.txt')


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:                                          # noqa: BLE001
        pass


def _pid_alive(pid):
    if not pid:
        return False
    try:
        if os.name == 'nt':
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))     # PROCESS_QUERY_LIMITED_INFORMATION
            if not h:
                return False
            code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
            ctypes.windll.kernel32.CloseHandle(h)
            return code.value == 259                                        # STILL_ACTIVE
        os.kill(int(pid), 0)
        return True
    except Exception:                                          # noqa: BLE001
        return False


def acquire_lock(path=LOCK):
    """잠금 → True. 살아 있는 다른 워커가 쥐고 있으면 False. 주인이 죽은 잠금은 치우고 다시 한 번 잡는다."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(f'{os.getpid()} {_dt.datetime.now().isoformat(timespec="seconds")}')
            return True
        except FileExistsError:
            try:
                with io.open(path, encoding='utf-8') as f:
                    pid = int((f.read().split() or ['0'])[0])
            except (OSError, ValueError):
                pid = 0
            if pid and _pid_alive(pid):
                return False
            try:
                os.remove(path)          # 주인이 죽었다 — 치우고 한 번 더
            except OSError:
                return False
    return False


def release_lock(path=LOCK):
    try:
        with io.open(path, encoding='utf-8') as f:
            pid = int((f.read().split() or ['0'])[0])
        if pid == os.getpid():
            os.remove(path)
    except (OSError, ValueError):
        pass


def _bars_fn():
    import bitemporal_engine as be
    eng = be.BitemporalEngine()
    cache = {}

    def fn(code):
        if code not in cache:
            cache[code] = eng.fetch_daily_bars(f'{code}.KS')
        return cache[code]
    return fn


def quote(code):
    """지금 가격 — 네이버 종목 기본 정보의 현재가(엔진이 쓰는 같은 끝점). 못 읽으면 None(그러면 그 종목은 안 산다)."""
    import bitemporal_engine as be
    from broker_kis import _num
    d = be.fetch_json_with_retry(f'{be.NAVER_MOBILE_API}/stock/{code}/basic', timeout=6, retries=1) or {}
    return _num(d.get('closePrice'))


def one_cycle(do_shadow, allow_orders=True):
    import broker_kis
    import premarket
    import swing_executor as X
    import swing_ledger as L
    from verdict_core import COST_PCT
    c = L.connect()
    try:
        st = L.settings(c)
        cfg = broker_kis.load_config()
        broker = None
        if st.get('mode') in X.MODE_ENV and not X.broker_gate(st['mode'], cfg, st):
            broker = broker_kis.KisBroker(cfg)
        anchor = premarket.report_day()
        report = premarket.load_today_report(anchor) if anchor else None
        return X.run_cycle(c, broker=broker, cfg=cfg, report=report, anchor_day=anchor,
                           bars_fn=_bars_fn() if do_shadow else None, cost_pct=COST_PCT, do_shadow=do_shadow,
                           allow_orders=allow_orders, quote_fn=quote)
    finally:
        c.close()


def session_window(now):
    """오늘 정규장 (시작, 마감) 시각 — 엔진 한 곳(`bitemporal_engine.session_times` · 수능일 10:00~16:30 포함 · 라운드 448).
    휴장일이면 None. 시각은 한국 시각으로 견준다."""
    import swing_executor as X
    n = X.kst(now)
    if not X.is_trading_day(n.date().isoformat()):
        return None
    op, cl = X._session_times(n.date())
    return (n.replace(hour=op.hour, minute=op.minute, second=0, microsecond=0),
            n.replace(hour=cl.hour, minute=cl.minute, second=0, microsecond=0))


def _log(line):
    print(line)
    try:
        with io.open(RUNLOG, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except OSError:
        pass


def main(argv=None, clock=None, sleeper=None, cycle=None):
    """clock() · sleeper(초) · cycle(do_shadow, allow_orders) 는 시험이 끼워 넣는다(기본은 실제 시계·sleep·one_cycle)."""
    _utf8()
    clock = clock or (lambda: _dt.datetime.now().astimezone())
    sleeper = sleeper or time.sleep
    cycle = cycle or one_cycle
    ap = argparse.ArgumentParser()
    ap.add_argument('--once', action='store_true')
    ap.add_argument('--loop', type=int, default=0, help='초 간격(0 이면 한 바퀴)')
    ap.add_argument('--no-orders', action='store_true',
                    help='주문을 내지 않는다 — 계획·모의·체결 내역·계좌 맞춤만(저녁 작업이 쓴다)')
    ap.add_argument('--session', action='store_true',
                    help='오늘 정규장 마감까지 --loop 간격으로 돌고, 마감 뒤 한 바퀴(체결 내역 맞춤) 더 돌고 끝난다 — 작업 스케줄러용')
    a = ap.parse_args(argv)
    if a.session and a.loop <= 0:
        print('--session 에는 --loop 초 간격이 필요하다')
        return 2
    if os.environ.get('GAEUM_NO_LOCAL_WRITE') == '1':
        print('쓰기 금지 — 장부를 열지 않고 끝낸다')
        return 0
    import swing_ledger as _L
    if not os.path.exists(_L.PATH):
        # 모드를 정한 적이 없다(장부가 없으면 모드는 꺼짐) — 저녁 작업이 불러도 파일을 만들지 않는다
        print('장부가 없다 — 스윙 칸에서 모드를 정한 적이 없어 할 일이 없다(꺼짐)')
        return 0
    loop = a.loop > 0 and not a.once
    end = None
    if a.session and loop:
        n0 = clock()
        win = session_window(n0)
        if win is None:
            _log(f'[{n0:%m-%d %H:%M:%S}] 휴장일 — 워커를 안 돌린다')
            return 0
        end = win[1]
        _log(f'[{n0:%m-%d %H:%M:%S}] 정규장 {win[0]:%H:%M}~{win[1]:%H:%M} — 마감까지 {a.loop}초마다 돌고 마감 뒤 한 바퀴 더')
    last_shadow_day = None
    while True:
        now = clock()
        past_close = end is not None and now >= end
        if not acquire_lock(LOCK):
            _log(f'[{now:%m-%d %H:%M:%S}] 다른 워커가 돌고 있다 — 이번 바퀴는 건너뛴다'
                 + (f' · {a.loop}초 뒤 다시' if loop else ''))
        else:
            try:
                # 기록만 모의(일봉 받기)는 하루 한 번이면 된다 — 장중 매 바퀴 일봉을 받지 않는다
                do_shadow = last_shadow_day != now.date().isoformat()
                out = cycle(do_shadow, allow_orders=not a.no_orders)
                if do_shadow:
                    last_shadow_day = now.date().isoformat()
                _log(f"[{now:%m-%d %H:%M:%S}] {out['mode']} · 판정일 {out.get('anchor_day')} · 계획 +{out['plans_new']} · "
                     f"모의 {out['shadow_updates']} · 주문 {len(out['orders'])} · 청산 {len(out['exits'])} · "
                     f"막힘 {len(out['blocked'])} · 경고 {len(out.get('alerts') or [])}")
                for n in (out.get('alerts') or []) + out['notes'] + out['blocked']:
                    _log('   ' + n)
            except Exception as e:                             # noqa: BLE001 — 한 바퀴가 죽어도 다음 바퀴는 돈다
                _log(f'[{now:%m-%d %H:%M:%S}] 바퀴 실패 — {type(e).__name__}: {e}')
            finally:
                release_lock(LOCK)
        if not loop:
            break
        if past_close:
            _log(f'[{now:%m-%d %H:%M:%S}] 마감 뒤 한 바퀴를 돌았다 — 끝')
            break
        sleeper(a.loop)
    return 0


if __name__ == '__main__':
    sys.exit(main())
