# -*- coding: utf-8 -*-
"""바꿔 끼우기 한 곳 — 임시 파일을 제자리로(라운드 519).

Windows 에서는 다른 프로세스가 **읽느라 연** 파일을 `os.replace` 로 바꿔 끼울 수 없다(PermissionError 5). 이 저장소는
앱(15초 갱신)·저녁 작업·워커가 같은 파일을 서로 읽고 쓰므로, 바꿔 끼우기가 그 순간 막힐 수 있다. 종전엔 같은 대처가 세 벌
(관심종목 저장 · 알림 상태 · 클라우드 되받기)으로 따로 있었고 나머지 쓰는 자리(성적표 · 관심종목 추천 문서 · 조건 알림 ·
워커 세션 표시)는 대처가 없어 막히면 그 단계가 통째로 실패했다.

규칙(종전 세 벌과 같다): 짧게 다시 해 보고 → 그래도 막히면 **임시 파일의 내용을 제자리에 복사**한다(저장을 포기하지 않는다 ·
상대가 반쯤 쓰인 파일을 읽을 수 있는 종전 동작으로 물러선다) → 임시 파일은 어느 쪽이든 남기지 않는다. 물러섰으면 그 이름을
`FALLBACK` 에 남긴다(부르는 쪽이 찍을 수 있게). 다시 해 보는 횟수·간격은 부르는 자리가 정한다 — 매달림 방지이지 판정 문턱이
아니다(종전 값 그대로 옮겼다).
"""
import os
import shutil
import time

FALLBACK = []


def replace_retry(tmp, dst, tries=5, wait=0.05, replace=None):
    """tmp → dst. 바꿔 끼웠으면 True · 끝내 막혀 복사로 물러섰으면 False. 다른 오류는 그대로 올린다.

    `replace` 는 시험이 막힘을 심는 자리다 — 주지 않으면 **부르는 순간의** `os.replace` 를 쓴다(시험이 os.replace 를 바꿔
    심어도 닿게 · 정의 때 묶지 않는다)."""
    try:
        for i in range(max(1, int(tries))):
            try:
                (replace or os.replace)(tmp, dst)
                return True
            except PermissionError:
                if i + 1 < tries:
                    time.sleep(wait)
        shutil.copyfile(tmp, dst)
        FALLBACK.append(os.path.basename(dst))
        return False
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
