# -*- coding: utf-8 -*-
"""이 PC 의 평일 장 마감 뒤 작업 — 사람이 누르던 버튼 둘을 차례로 돈다 (라운드 414 → 415).

  ① 추적 동결·채점 — `scripts/run_daily_improvement.py` (화면의 '장 종료 후 지금 실행' 버튼과 같은 스크립트)
  ② 관심종목 재측정 — `scripts/refresh_watchlist.py` (표의 '지금 재기'와 같은 함수 · 라운드 414)

■ 왜 ① 이 여기 있나 (라운드 415 · 2026-10-02 실측)
  개장 전 리포트는 **이 PC 의 앱만** 만든다(클라우드에는 09-12 판이 마지막 — 라운드 281 이 손으로 올린 것).
  클라우드의 추적 루틴은 그 옛 사본을 읽어 **09-14 뒤로 한 건도 동결하지 못했고**(496건에서 멈춤), 이 PC 에서
  추적을 돌리는 길은 화면의 버튼뿐이라 18일이 비었다. 추적은 **리포트가 있는 곳에서** 돈다.

■ 규칙
  · 단계마다 자식 프로세스 · 시간 상한 · 종료 코드와 걸린 시간을 텍스트 로그(`.portfolio/nightly_local_run.txt`)에
    **그 자리에서** 남긴다(중간에 죽어도 말이 남는다 · 라운드 310). 한 단계가 실패해도 다음 단계는 돈다.
  · 산출물은 각 단계가 제 자리에 남긴다 — ① 은 개선 DB 의 실행 기록(화면 추적 줄의 '마지막 실행'), ② 는
    `watch_refresh_log.jsonl`(관심종목 절의 상태 줄). 켜져 있다가 아니라 산출물로 센다(라운드 412).
  · `GAEUM_NO_LOCAL_WRITE` 면 ① 은 건너뛰고(개선 DB 를 쓴다) ② 는 계획만 센다 — 회귀·배포는 사용자 자료를 안 쓴다(§9).
  · `--plan` 은 무엇을 돌릴지만 적는다(네트워크 0 · 쓰기 0).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:                                              # noqa: BLE001
    pass
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEXT_LOG = os.path.join(PROJ, '.portfolio', 'nightly_local_run.txt')
TEXT_LOG_KEEP = 2000

#: (이름, 스크립트, 시간 상한 초). 상한은 문턱이 아니라 매달림 방지다 — 실측 ① 수십 초 · ② 51행 123초(2026-10-02).
STEPS = (
    ('추적 동결·채점', 'scripts/run_daily_improvement.py', 30 * 60),
    ('관심종목 재측정', 'scripts/refresh_watchlist.py', 120 * 60),
    # 라운드 418 — 가늠 PROOF 성적표(남긴 판정 전부를 같은 채점기로 · 실측 198종목 33초). 쓰기 금지면 --dry-run.
    ('PROOF 성적표', 'scripts/proof_scorecard.py', 60 * 60),
)


def _log(msg, write):
    s = f'[{_dt.datetime.now().strftime("%m-%d %H:%M:%S")}] {msg}'
    print(s, flush=True)
    if write:
        try:
            os.makedirs(os.path.dirname(TEXT_LOG), exist_ok=True)
            with open(TEXT_LOG, 'a', encoding='utf-8') as f:
                f.write(s + '\n')
        except Exception:                                      # noqa: BLE001
            pass                                               # 로그가 작업을 죽이지 않는다 (라운드 271)


def _trim():
    try:
        with open(TEXT_LOG, encoding='utf-8', errors='replace') as f:
            old = f.read().splitlines()
        if len(old) > TEXT_LOG_KEEP:
            with open(TEXT_LOG, 'w', encoding='utf-8') as f:
                f.write('\n'.join(old[-TEXT_LOG_KEEP:]) + '\n')
    except Exception:                                          # noqa: BLE001
        pass


def plan_steps(no_write):
    """돌릴 단계 — (이름, 인자 목록, 상한, 건너뛰는 사유 또는 None). 순수 함수."""
    out = []
    for name, script, limit in STEPS:
        args = [os.path.join(PROJ, script)]
        skip = None
        if no_write and script.endswith('run_daily_improvement.py'):
            skip = '쓰기 금지(GAEUM_NO_LOCAL_WRITE) — 개선 DB 를 쓰는 단계라 건너뛴다'
        if no_write and script.endswith('refresh_watchlist.py'):
            args.append('--plan')
        if no_write and script.endswith('proof_scorecard.py'):
            args.append('--dry-run')
        out.append((name, args, limit, skip))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description='이 PC 의 평일 장 마감 뒤 작업')
    ap.add_argument('--plan', action='store_true', help='무엇을 돌릴지만 적는다')
    a = ap.parse_args(argv)
    no_write = bool(os.environ.get('GAEUM_NO_LOCAL_WRITE'))
    write = not (a.plan or no_write)
    steps = plan_steps(no_write)
    _log(f'이 PC 장 마감 뒤 작업 시작 · 단계 {len(steps)}' + (' · 계획만' if a.plan else '')
         + (' · 쓰기 금지' if no_write else ''), write)
    worst = 0
    for name, args, limit, skip in steps:
        if a.plan or skip:
            _log(f'  {name} — {skip or "계획"} · {" ".join(os.path.relpath(x, PROJ) if os.path.isabs(x) else x for x in args)}', write)
            continue
        t0 = time.time()
        env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1')
        try:
            r = subprocess.run([sys.executable] + args, cwd=PROJ, capture_output=True, text=True,
                               encoding='utf-8', errors='replace', timeout=limit, env=env)
            tail = [ln for ln in (r.stdout or '').splitlines() if ln.strip()][-3:]
            err = [ln for ln in (r.stderr or '').splitlines() if ln.strip()][-2:]
            _log(f'  {name} — 종료 {r.returncode} · {time.time() - t0:.0f}초 · ' + ' | '.join(tail)[-300:]
                 + ((' · stderr ' + ' | '.join(err)[-200:]) if (r.returncode and err) else ''), write)
            worst = max(worst, int(r.returncode or 0))
        except subprocess.TimeoutExpired:
            _log(f'  {name} — 시간 상한 {limit // 60}분을 넘겨 멈췄다', write)
            worst = max(worst, 9)
        except Exception as ex:                                # noqa: BLE001
            _log(f'  {name} — 못 돌렸다 {type(ex).__name__}: {str(ex)[:120]}', write)
            worst = max(worst, 9)
    _log(f'끝 · 가장 나쁜 종료 코드 {worst}', write)
    if write:
        _trim()
    return worst


if __name__ == '__main__':
    sys.exit(main())
