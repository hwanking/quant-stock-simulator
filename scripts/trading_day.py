# -*- coding: utf-8 -*-
"""꼬리 검사가 판정해야 할 날 — '오늘'이 아니라 **마지막으로 장이 끝난 거래일** (라운드 283).

■ 왜 이 규칙이 필요했나 (2026-09-13 실측)
  워크플로의 꼬리 검사들(전방 기록부 가드 R272 · 실행 기록 검사 R263)은 작업 **맨 뒤**에서
  돌고, 수집은 **맨 앞**에서 돈다(R253 이 기록기를 앞으로 옮겼다). 예약 지연이 2026-08-27
  부터 42~77분에서 **276~726분**으로 늘어 시작이 21:36~23:06 KST 가 됐고, 실행이 2~7시간
  이라 끝나는 시각이 한국 날짜로 **다음 날**이 된다 — 최근 예약 12회 중 **6회가 넘겼다.**

  그 6회에서 두 검사가 묻는 '오늘'은 수집한 날이 아니다. 전방 기록부 가드를 실제 기록부로
  되돌려 보니 셋은 판정까지 뒤집혔다:

      수집일        검사가 본 날    수집일 판정   검사 판정
      2026-09-10   2026-09-11     실패         통과   ← R272 가 잡으려던 바로 그 0 건인 날
      2026-09-07   2026-09-08     통과         실패
      2026-09-01   2026-09-02     실패         통과

  화요일 새벽 02:36 에 도는 검사가 물어야 할 것은 화요일이 아니라 **월요일**이다.

■ 규칙 (새 숫자 없음)
  마지막으로 **정규장 마감이 지난** 거래일. 마감 시각은 이미 채택된 상수 하나
  (`bitemporal_engine.MARKET_CLOSE` = 15:30)를 부르고 여기서 다시 적지 않는다(§2-6 ·
  R192 의 '베낀 판별식'). 휴장일 판정도 한 곳(`improvement.case_tracker`)을 부른다(R252).

      월 21:42 → 월      화 02:36 → **월**      토 04:25 → 금
      금 23:59 → 금      금 09:00 → **목**(마감 전)

■ 못 유도하면 None 이다 — 몰래 '오늘'로 떨어지지 않는다 (§3). 부르는 쪽이 미측정으로 적는다.
"""
import os
import sys
from datetime import datetime, timedelta

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)
from improvement.case_tracker import is_non_trading_date          # noqa: E402

#: 며칠까지 거슬러 볼까 — 연휴가 아무리 길어도 이 안에 거래일이 있다.
#: 문턱이 아니라 무한 루프 방지용 상한이다.
MAX_BACK_DAYS = 30


def anchor_day(now=None, max_back=MAX_BACK_DAYS):
    """마지막으로 정규장이 끝난 거래일 (ISO 문자열) · 못 구하면 None."""
    try:
        from bitemporal_engine import MARKET_CLOSE
    except Exception:                                          # noqa: BLE001
        return None
    now = now or datetime.now().astimezone()
    d = now.date()
    if now.time() <= MARKET_CLOSE:      # 오늘 장은 아직 안 끝났다
        d -= timedelta(days=1)
    for _ in range(max_back):
        if not is_non_trading_date(d.isoformat()):
            return d.isoformat()
        d -= timedelta(days=1)
    return None


def wall_date():
    """이 프로세스가 실제로 도는 지금의 지역 날짜 — 로그에 판정일과 같이 적는다."""
    return datetime.now().astimezone().date().isoformat()


if __name__ == '__main__':
    print(f'지금 {wall_date()} · 판정일 {anchor_day()}')
