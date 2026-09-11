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

■ 판정 (오늘 = 이 프로세스의 지역 날짜 · 워크플로는 TZ=Asia/Seoul · R222 의 UTC 함정)
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
    today = today or datetime.now().astimezone().date().isoformat()
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
    print(f'오늘 {today} · 전방 기록부 {total:,}행 · 날짜 {len(dates)}일'
          + (f' ({dates[0]} ~ {dates[-1]})' if dates else '') + f' · 오늘 행 {n_today}건')
    if n_today <= 0:
        print(f'\n>> 실패 — 거래일 {today} 의 전방 판정 행이 0 이다. 그날 "전방 판정 기록" 단계 로그가 '
              f'사유를 말한다(유니버스 수집 실패 · 시세 미수신 · 시간초과). 이 날은 다시 만들 수 없다.')
        return 1
    print(f'\n>> 통과 — 오늘 행 {n_today}건')
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(check())
