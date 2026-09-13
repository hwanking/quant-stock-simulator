# -*- coding: utf-8 -*-
"""전방 기록부에 **오늘** 행이 있나 — 거래일에 0 이면 실패다 (라운드 272).

■ 왜 필요한가 — 실측 2026-09-10 클라우드 실행(run 34478754602 · main = R260)
  25단계 전부 '성공'이었는데 쌓인 것이 0 이었다. 네이버가 그날 오후 옛 페이지를 새 사이트로
  넘겨(R270) 유니버스 수집이 실패했고, 폴백 19종목은 전부 '종목 페이지 없음' → **전방 판정
  기록 0건**(전방 기록부 360 → 360) · 케이스 축적 120분 시간초과 0행 · 전방 집중 축적 "한
  종목도 못 받았다" · 경로 기록 0행(실패 574). 증분 요약은 `⚠ 늘어난 것이 하나도 없다` 를
  찍고 rc 0 이었다 — 라운드 81 이 *"계획이 다 찬 날은 0 이 정상"* 이라 실패로 안 만든 자리다.
  원장은 그 말이 맞다(격자가 차면 0). **전방 기록부는 다르다** — 매 거래일 상위 60 을 박제하는
  것이 이 파일의 정의라 거래일의 0 은 정상일 수 없다. 11-16 재평가가 읽는 날짜가 하루 빠진
  것이고(R253 의 잃은 16일과 같은 자리), 그날은 다시 만들 수 없다.

⚠️ **판정하는 날이 수집한 날이 아니었다** (라운드 283 · 2026-09-13). 종전 이 검사는
  '오늘 = 이 프로세스의 지역 날짜' 로 봤다. 그런데 이 검사는 워크플로 **맨 뒤**에서 돌고
  수집(기록기)은 **맨 앞**에서 돈다(R253). 예약 지연이 2026-08-27 부터 42~77분에서
  **276~726분**으로 늘어 시작이 21:36~23:06 KST 가 됐고, 실행이 2~7시간이라 끝나는 시각이
  **한국 날짜로 다음 날**이 된다 — 최근 예약 12회 중 **6회가 날짜를 넘겼다.**
  실제로 돌려 보니 그중 셋은 판정까지 뒤집혔다(2026-09-13 실측):

      수집일        가드가 본 날    수집일 판정   가드 판정
      2026-09-10   2026-09-11     실패         통과   ← R272 가 잡으려던 바로 그 0 건인 날
      2026-09-07   2026-09-08     통과         실패
      2026-09-01   2026-09-02     실패         통과

  즉 **자기가 만들어진 이유였던 그 날(09-10 · 전방 0건)을 놓쳤을 것이다.**
  고침: 판정하는 날을 **가장 최근에 정규장이 끝난 거래일**로 유도한다 — 화요일 새벽 02:36
  에 도는 실행이 묻는 것은 화요일이 아니라 **월요일**이다. 마감 시각은 이미 채택된
  `bitemporal_engine.MARKET_CLOSE`(15:30) 를 그대로 쓴다(새 숫자 없음 · §2-6).
  `today=` 인자를 주면 그 날을 그대로 판정한다(검사가 심을 때 쓴다).

■ 판정 (판정일 = 위 유도값 · 워크플로는 TZ=Asia/Seoul · R222 의 UTC 함정)
  · 휴장일                       → 판정하지 않는다 (rc 0 · 그날은 기록이 없는 게 맞다)
  · 오늘 날짜의 행이 1건 이상     → 통과 (rc 0 · 몇 건인지 찍는다)
  · 거래일인데 오늘 행이 0        → 실패 (rc 1 · 그날 '전방 판정 기록' 단계 로그가 사유를 말한다)
  · 파일이 없거나 못 읽는다        → 미측정 (rc 2 · 통과가 아니다)
  휴장일 판정은 한 곳(`improvement.case_tracker.is_non_trading_date` · R252)을 부른다.
  행의 날짜 칸은 `date`(fr-1 규약 · `forward_registry.py`).

■ 자리: 워크플로 **맨 뒤**(업로드 뒤 · 실행 기록 검사 다음). 실패해도 그날 축적은 남는다 (R247).
  `|| true` 를 붙이지 않는다.

    python scripts/forward_registry_check.py
"""
import io
import json
import os
import sys
from datetime import datetime

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)
from improvement.case_tracker import is_non_trading_date          # noqa: E402
from scripts.trading_day import anchor_day, wall_date             # noqa: E402

DEFAULT_PATH = os.path.join(PROJ, '.portfolio', 'forward_registry.jsonl')


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def count_by_date(path):
    """(전체 행수, {date: 행수}) — 깨진 줄은 세되 날짜 없음으로 둔다."""
    total, by_date = 0, {}
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                d = str((json.loads(line) or {}).get('date') or '')[:10]
            except (ValueError, AttributeError):
                d = ''
            by_date[d] = by_date.get(d, 0) + 1
    return total, by_date


def check(path=DEFAULT_PATH, today=None):
    if not today:
        today = anchor_day()
        if not today:
            print('>> 못 쟀다 — 판정할 거래일을 유도하지 못했다(마감 시각 상수를 못 읽었거나 '
                  '최근 30일이 전부 휴장으로 나온다). 미측정이다.')
            return 2
    if is_non_trading_date(today):
        print(f'{today} 휴장일 — 전방 판정은 그날 기록하지 않는다. 판정하지 않는다.')
        return 0
    if not os.path.exists(path):
        print(f'>> 못 쟀다 — {path} 가 없다. 미측정이다.')
        return 2
    try:
        total, by_date = count_by_date(path)
    except (OSError, UnicodeDecodeError) as exc:
        print(f'>> 못 쟀다 — 전방 기록부를 못 읽었다 ({type(exc).__name__}: {exc}). 미측정이다.')
        return 2
    dates = sorted(d for d in by_date if d)
    n_today = by_date.get(today, 0)
    # '오늘'이라 적지 않는다 — 자정을 넘겨 도는 실행에서 그 낱말이 거짓이었다(R283).
    _wall = wall_date()
    _note = '' if _wall == today else f' (이 검사가 도는 지금은 {_wall} 이다 — 넘겼다)'
    print(f'판정일 {today} · 마지막으로 장이 끝난 거래일{_note} · '
          f'전방 기록부 {total:,}행 · 날짜 {len(dates)}일'
          + (f' ({dates[0]} ~ {dates[-1]})' if dates else '')
          + f' · 판정일 행 {n_today}건')
    if n_today <= 0:
        print(f'\n>> 실패 — 거래일 {today} 의 전방 판정 행이 0 이다. 그날 "전방 판정 기록" 단계 로그가 '
              f'사유를 말한다(유니버스 수집 실패 · 시세 미수신 · 시간초과). 이 날은 다시 만들 수 없다.')
        return 1
    print(f'\n>> 통과 — {today} 행 {n_today}건')
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(check())
