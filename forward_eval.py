# -*- coding: utf-8 -*-
"""전방 재평가 날짜 — **한 곳에서만 나온다** (라운드 78).

■ 왜 모듈이 따로 있는가
  종전 날짜(2026-08-23)가 코드·문서·워크플로 여덟 군데에 문자열로 박혀
  있었다. 라운드 78 에서 날짜를 정정하면서 그중 하나만 고쳤다면, 화면의
  가늠 AI 는 계속 "8/23 전방 검증 전"이라고 말했을 것이다.
  이미 같은 사고가 있었다 — 폐기한 산식이 여섯 곳에 살아 있었고 결정은
  주석에만 적혀 있었다.

  그래서 날짜는 박제 파일(data/regime_routing_r55.json)에서만 읽는다.
  여기서 상수를 새로 만들지 않는다.

■ 이 값은 무엇인가
  R55(국면 라우팅)·R57(Entry Engine)·R66(돌파 거짓돌파)의 전방 재평가일.
  = 2026-08-10(동결 뒤 첫 거래일) 부터 65번째 거래일 = 45(기록) + 20(채점)
  유도 과정: docs/FORWARD_EVAL_DATE_R78.md
"""
import json
import os

_PROJ = os.path.dirname(os.path.abspath(__file__))
_PINNED = os.path.join(_PROJ, 'data', 'regime_routing_r55.json')

#: 사전등록이 정한 지평(영업일). 원장 전 케이스가 이 값이다.
HORIZON_DAYS = 20

#: 전방 구간 시작 — 동결일 다음.
FORWARD_FROM = '2026-08-09'


def eval_date():
    """재평가일 'YYYY-MM-DD'. 박제 파일을 못 읽으면 **지어내지 않는다.**"""
    try:
        with open(_PINNED, encoding='utf-8') as f:
            return (json.load(f).get('forward_eval') or {}).get('date')
    except Exception:                                          # noqa: BLE001
        return None


def eval_date_ko():
    """화면·설명용 표기. 값이 없으면 없다고 말한다 (§3)."""
    d = eval_date()
    if not d:
        return '전방 재평가일 미기록'
    y, m, dd = d.split('-')
    return f'{y}-{m}-{dd}'


def pending_note():
    """가늠 AI·화면이 쓰는 한 문장 — 후보를 운영 판단처럼 말하지 않게."""
    d = eval_date()
    when = f'{d} 전방 검증 전' if d else '전방 검증 전(날짜 미기록)'
    return (f'국면 라우팅(R55)·즉시 진입(R57)·돌파 예외(R66)는 {when}'
            f'이라 운영 판단에 쓰지 않습니다')
