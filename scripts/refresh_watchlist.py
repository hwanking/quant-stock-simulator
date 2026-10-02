# -*- coding: utf-8 -*-
"""관심종목 스냅샷을 **혼자** 다시 잰다 (라운드 414) — 사람이 표의 '지금 재기'를 누르지 않아도.

사용자(2026-10-02): *"'지금 다시 재기' 같은 거는 너가 주기적으로 바꿔줘야지."*
재는 길은 `watch_refresh` 한 곳이고(화면의 채우기 버튼 · '지금 재기' 링크와 **같은 함수** · §4) 이 파일은
그것을 부르는 껍데기다. Windows 작업 스케줄러가 평일 장 마감 뒤 이 스크립트를 돈다
(`scripts/register_watch_refresh_task.ps1` 이 등록한다 · 이 PC · 현재 사용자).

    python scripts/refresh_watchlist.py              # 다시 잴 행을 재고 저장하고 기록한다
    python scripts/refresh_watchlist.py --plan       # 다시 잴 행만 센다 (네트워크 0 · 쓰기 0)
    python scripts/refresh_watchlist.py --dry-run    # 재기만 하고 아무것도 안 쓴다
    python scripts/refresh_watchlist.py --limit 5    # 이번엔 다섯 행까지
    python scripts/refresh_watchlist.py --code 005930 --code 000660
    python scripts/refresh_watchlist.py --force      # 기준일과 무관하게 전부

종료 코드: 0 정상(잴 것이 없는 날 포함) · 2 다른 실행이 돌고 있음 · 3 기준일을 못 구함 · 4 잰 행 0 (전부 실패)
`GAEUM_NO_LOCAL_WRITE` 가 켜져 있으면 아무 파일도 안 쓴다(§9 · 회귀·배포).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:                                              # noqa: BLE001
    pass
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)
os.chdir(PROJ)

import portfolio                                               # noqa: E402
import watch_refresh as wr                                     # noqa: E402

#: 사람이 읽는 실행 로그(그대로 덧붙임 · 최근 줄만 남긴다). 판정 산출물은 `watch_refresh.LOG_FILE`(jsonl) 이다.
TEXT_LOG = os.path.join(portfolio.PORTFOLIO_DIR, 'watch_refresh_run.txt')
TEXT_LOG_KEEP = 2000


def _tee(path, enabled):
    """찍는 줄을 화면과 텍스트 로그에 **그 자리에서** 남긴다 — 끝에 몰아 쓰면 중간에 죽은 실행은 아무 말도 안 남긴다
    (라운드 310 의 '죽은 단계는 버퍼째 말을 잃는다'). 끝에서 한 번 최근 줄만 남기도록 자른다."""
    def _log(msg):
        s = f'[{_dt.datetime.now().strftime("%m-%d %H:%M:%S")}] {msg}'
        print(s, flush=True)
        if enabled:
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, 'a', encoding='utf-8') as f:
                    f.write(s + '\n')
            except Exception:                                  # noqa: BLE001
                pass                                           # 로그가 수집을 죽이지 않는다 (라운드 271)

    def _flush():
        if not enabled or not os.path.exists(path):
            return
        try:
            with open(path, encoding='utf-8', errors='replace') as f:
                old = f.read().splitlines()
            if len(old) > TEXT_LOG_KEEP:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(old[-TEXT_LOG_KEEP:]) + '\n')
        except Exception:                                      # noqa: BLE001
            pass
    return _log, _flush


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n', 1)[0])
    ap.add_argument('--plan', action='store_true', help='다시 잴 행만 센다 (네트워크 0 · 쓰기 0)')
    ap.add_argument('--dry-run', action='store_true', help='재기만 하고 아무것도 안 쓴다')
    ap.add_argument('--limit', type=int, default=None)
    ap.add_argument('--code', action='append', default=None, help='이 종목만 (여러 번 가능)')
    ap.add_argument('--force', action='store_true', help='기준일과 무관하게 전부 다시 잰다')
    ap.add_argument('--file', default=None, help='관심종목 파일 (기본 .portfolio/watchlist.json · 시험용)')
    ap.add_argument('--log', default=None, help='실행 기록 jsonl (기본 .portfolio/watch_refresh_log.jsonl · 시험용)')
    a = ap.parse_args(argv)

    write = not (a.plan or a.dry_run) and not wr.no_local_write()
    log, flush = _tee(TEXT_LOG, enabled=write)
    path = a.file or portfolio.WATCHLIST_FILE
    items, _saved = portfolio.load_watchlist(path)
    rd = wr.ref_day()
    log(f'관심종목 자동 갱신 시작 · 지금 {_dt.datetime.now().isoformat(timespec="seconds")} · 기준일 {rd} · '
        f'행 {len(items)} · 쓰기 {"함" if write else "안 함"}' + (' · 계획만' if a.plan else ''))
    if not rd:
        log('기준일을 못 구했다 — 재지 않는다(§3)')
        flush()
        return 3
    todo = wr.due_rows(items, rd, force=a.force)
    if a.code:
        want = {portfolio.normalize_code(c) for c in a.code}
        todo = [(w, r) for w, r in todo if portfolio.normalize_code(w.get('code')) in want]
    if a.plan:
        log(f'다시 잴 행 {len(todo)} / {len(items)}'
            + (f' (이번엔 {min(len(todo), a.limit)})' if a.limit is not None else ''))
        for w, r in todo[:a.limit] if a.limit is not None else todo:
            log(f'  {w.get("name")} ({portfolio.normalize_code(w.get("code"))}) · {r} · 엔진 값 기준일 '
                f'{str(w.get("snap_at") or "없음")[:10]}' + (' · 보유' if w.get('paid') else ''))
        return 0
    if not wr.acquire_lock():
        log(f'다른 실행이 돌고 있다 — 이번은 건너뛴다 (잠금 {wr.LOCK_FILE})')
        flush()
        return 2
    try:
        out = wr.refresh(items=items, ref=rd, limit=a.limit, codes=a.code, write=write, log=log,
                         path=path, log_path=a.log, force=a.force)
    finally:
        wr.release_lock()
        flush()
    if out.get('planned') and not out.get('measured'):
        return 4
    return 0


if __name__ == '__main__':
    sys.exit(main())
