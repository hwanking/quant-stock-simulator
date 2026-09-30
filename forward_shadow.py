# -*- coding: utf-8 -*-
"""
교정본 그림자 기록 (라운드 404) — 운영 산식은 그대로 두고, 고친 산식의 값을 **같은 날 같은 종목**으로 옆에 적는다.

■ 왜 (사용자 결정 2026-10-01 · *"교정본 그림자 기록으로 해줘"*)
  외부 검토(2026-10-01)가 찾은 산식 결함 다섯은 전부 코드에 있었다(docs/RESULT_R401_EXTERNAL_REVIEW_CHECK.md).
  그런데 고치면 값이 바뀌고, 지금은 11-16 전방 평가 한가운데다 — 운영을 바꾸면 그 평가의 표본이 둘로 갈린다.
  그래서 운영은 **안 바꾸고**, 고친 판을 따로 돌려 매일 기록한다. 판정은 사전등록대로 한다
  (docs/PREREG_R404_SHADOW_CORRECTIONS.md · 측정 전에 커밋).

■ 다섯 고침 (스위치 이름 · 켜는 곳은 이 기록기 한 곳 · 운영 엔진은 전부 꺼져 있다)
  B1  적정가 괴리율 윈저화 → 이미 있는 상·하한(+48 · −40)으로 자르기만 (quant_indicators)
  B2  확률우위 점수 → 0~100 으로 자르기 (quant_indicators)
  B3  비용 차감 기대값 → 같은 계획(눌림 진입가 · 20봉)의 실측 확률로 (verdict_core · data/entry_fill_facts.json)
  B4  ROE 7% 이하에서 현재가를 돌려주는 PBR 가지 → 그 모형 무효 (quant_indicators)
  B5  적정가 신뢰도의 '검증 성능' 칸(늘 40 · 잰 적 없음) → 빼고 나머지 여섯으로 (quant_indicators)

■ 무엇을 남기나
  종목·날짜마다 한 줄: `op`(운영 · 그날 전방 기록부에 적힌 것과 같은 계산) · `sh`(교정본) · `diff`(달라진 칸 이름).
  같은 (종목, 날짜)는 한 번만(멱등 · `fin_pit.append_rows` 를 그대로 쓴다). 값을 해석하지 않는다.

■ 범위 (정직하게)
  전방 판정 기록기가 그날 본 **상위 60종목**뿐이다. 전 종목이 아니다. 그리고 결과(20봉)가 닫혀야 성적을 잰다 —
  2026-10-01 에 시작하면 11-16 까지 결과가 닫힌 날짜는 **12일 안팎**이라 이미 채택된 날짜 하한(30)에 못 미친다.
  그날 잴 수 있는 것은 '판정이 얼마나 다른가'까지다(사전등록 R0).
"""
import os
from datetime import datetime, timezone

import fin_pit

PROJ = os.path.dirname(os.path.abspath(__file__))
#: 규약 이름 — 칸이나 고침이 바뀌면 sh-2 로 올린다(같은 파일 안에서 앞뒤 행의 뜻이 달라지지 않게 · fr-1 과 같은 규칙)
SPEC = 'sh-1'
#: 교정본에 켜는 고침 — 엔진·중앙 판정이 이 이름을 읽는다
CORRECTIONS = ('B1', 'B2', 'B3', 'B4', 'B5')
PATH = os.path.join(PROJ, '.portfolio', 'forward_shadow.jsonl')

#: 한 판(op · sh)이 싣는 칸 — 전부 **이미 있는 출력**을 옮겨 적는다(여기서 계산하지 않는다 · §4)
SIDE_FIELDS = ('action', 'score', 'bucket', 'recommended', 'actionable', 'expected_return',
               'new_entry', 'new_target', 'new_stop', 'rr',
               'fair', 'fair_status', 'fair_conf', 'upside_pct', 'entry_zone')

append_rows = fin_pit.append_rows
coverage = fin_pit.coverage


def _f(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def side(snap, vc):
    """스냅샷 + 중앙 판정 → 한 판의 칸. 계산하지 않고 옮긴다 — 진입가는 기록부와 같은 함수로 되돌린다."""
    import forward_registry as _fr
    fs = (snap or {}).get('four_scores') or {}
    vc = vc or {}
    return {
        'action': str(vc.get('action') or ''),
        'score': vc.get('score'),
        'bucket': vc.get('bucket'),
        'recommended': bool(vc.get('recommended')),
        'actionable': bool(vc.get('actionable')),
        'expected_return': _f(vc.get('expected_return')),
        'new_entry': _fr._entry_of(vc),
        'new_target': _f(vc.get('new_target')),
        'new_stop': _f(vc.get('new_stop')),
        'rr': _f(vc.get('rr')),
        'fair': _f(fs.get('displayed_fair_value')),
        'fair_status': fs.get('fair_value_status'),
        'fair_conf': _f(fs.get('fair_value_confidence')),
        'upside_pct': _f(fs.get('upside_pct')),
        'entry_zone': fs.get('entry_zone'),
    }


def make_row(code, date, op, sh, versions=None):
    """한 줄. `diff` 는 두 판에서 값이 다른 칸 이름(정확히 같은지로 · 문턱 없음)."""
    return dict(spec=SPEC, code=str(code), date=str(date)[:10], corrections=list(CORRECTIONS),
                versions=versions, recorded_at=datetime.now(timezone.utc).isoformat(timespec='seconds'),
                op=op, sh=sh, diff=[k for k in SIDE_FIELDS if (op or {}).get(k) != (sh or {}).get(k)])
