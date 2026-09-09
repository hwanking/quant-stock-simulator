# -*- coding: utf-8 -*-
"""일일 개선 파이프라인이 오늘 실제로 돌았나 — 값으로 판정한다 (라운드 263).

■ 왜 필요한가 — 실측 2026-09-10
  `pipeline_runs` 14행 · 고유 날짜 6일 · 2026-08-02~09-07 평일 26일 중 **24일 기록 없음.**
  남은 6일은 전부 사람이 이 PC 에서 돌린 시각(주말 · 저녁)이다. 클라우드 단계
  "일일 개선 파이프라인"은 매 평일 도는데 `|| true` 라 죽어도 초록불이다 — 라운드 250 이
  센 아홉 `|| true` 단계 중 하나. 파이프라인은 시작하자마자 'running' 행을 **커밋**하므로
  (`improvement.daily_pipeline.run_daily_pipeline`) 행이 없다는 것은 그날 **시작도 못
  했다**는 뜻이다. 원인은 그날 로그에 있고, 이 검사는 침묵을 붉게 만든다(R102·R259 의
  신선도 검사와 같은 모양 · 검사 대상은 산출물이 아니라 실행 기록).

■ 판정 (오늘 = 이 프로세스의 지역 날짜 · 워크플로는 TZ=Asia/Seoul · R222 의 UTC 함정)
  · 휴장일                                → 판정하지 않는다 (rc 0 · 그날은 안 도는 게 맞다)
  · 오늘 시작한 행이 없다                  → 실패 (rc 1)
  · 있는데 success/partial_success 가 아니다 → 실패 (rc 1 · 'running' 은 죽은 채 남은 것)
  · 표를 못 읽는다                          → 미측정 (rc 2 · 통과가 아니다)
  휴장일 판정은 한 곳(`improvement.case_tracker.is_non_trading_date` · R252)을 부른다.

■ 자리: 워크플로 **맨 뒤**(업로드 뒤). 실패해도 그날 축적은 남는다 (R247).

    python scripts/pipeline_run_check.py
"""
import io
import os
import sqlite3
import sys
from datetime import datetime

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)
from improvement.database import DEFAULT_DB_PATH                # noqa: E402
from improvement.case_tracker import is_non_trading_date          # noqa: E402

OK_STATUS = ('success', 'partial_success')


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def _local_date(iso):
    """UTC ISO(+00:00) 시각을 이 프로세스의 지역 날짜로 — 한국 아침의 어제 함정(R222)."""
    try:
        return datetime.fromisoformat(str(iso)).astimezone().date().isoformat()
    except (TypeError, ValueError):
        return None


def check(db_path=DEFAULT_DB_PATH, today=None):
    today = today or datetime.now().astimezone().date().isoformat()
    if is_non_trading_date(today):
        print(f'{today} 휴장일 — 일일 파이프라인은 그날 안 돈다. 판정하지 않는다.')
        return 0
    if not os.path.exists(db_path):
        print(f'>> 못 쟀다 — {db_path} 가 없다. 미측정이다.')
        return 2
    try:
        cn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
        rows = cn.execute(
            "SELECT run_id, started_at, finished_at, status, added_cases, resolved_cases, "
            "error_count FROM pipeline_runs ORDER BY started_at DESC LIMIT 5").fetchall()
        cn.close()
    except sqlite3.Error as exc:
        print(f'>> 못 쟀다 — pipeline_runs 를 못 읽었다 ({type(exc).__name__}: {exc}). 미측정이다.')
        return 2
    print(f'오늘 {today} · 최근 실행 기록 {len(rows)}건:')
    for r in rows:
        print(f'  {r[0]}  시작 {r[1]}  끝 {r[2]}  {r[3]}  +{r[4]} 확정 {r[5]} 오류 {r[6]}')
    todays = [r for r in rows if _local_date(r[1]) == today]
    if not todays:
        print(f'\n>> 실패 — 오늘({today}) 시작한 실행 기록이 없다. 파이프라인이 시작조차 못 했다 '
              f'(시작하면 running 행을 먼저 커밋한다). 그날 단계 로그를 본다.')
        return 1
    bad = [r for r in todays if r[3] not in OK_STATUS]
    if bad:
        print(f'\n>> 실패 — 오늘 실행 {len(todays)}건 중 {len(bad)}건이 '
              f'{[r[3] for r in bad]} 로 끝났다(running 은 죽은 채 남은 것).')
        return 1
    print(f'\n>> 통과 — 오늘 실행 {len(todays)}건 · {[r[3] for r in todays]}')
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(check())
