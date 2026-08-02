# -*- coding: utf-8 -*-
"""
버전 관리 — 무엇이 바뀌면 어느 자리가 올라가는가를 코드로 못박는다.

형식:  vYYYY.MM.DD.PATCH     예) v2026.08.02 → v2026.08.02.1 → v2026.08.02.2
       알고리즘이 바뀌면 날짜 자리가 올라간다  예) v2026.08.03.0

증가 규칙 (사용자 지정):
  · PATCH  — 데이터 오류·UI·문구 수정. 판단 결과가 바뀌지 않는 변경.
  · DATE   — 점수 가중치·게이트·알고리즘 변경. 같은 입력에 다른 결론이 나올 수 있다.
  · MAJOR  — 전면 모델 교체. 이전 성과와 직접 비교하지 않는다.

왜 자리를 나누나: 버전 하나로 뭉뜽그리면 "숫자가 올랐는데 결과가 왜 같지"
또는 "패치라더니 판단이 뒤집혔다"가 된다. **결론이 바뀔 수 있는 변경인지**가
자리를 가르는 유일한 기준이다.

이전 버전 기록은 지우거나 덮어쓰지 않는다 — 성과 비교의 근거가 사라진다.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(BASE, 'data', 'version_ledger.json')

#: 각 축은 독립적으로 오른다. 화면·케이스마다 어느 축이 쓰였는지 함께 남긴다.
AXES = ('model', 'scoring', 'rulebook', 'schema', 'news')
AXIS_KO = {
    'model': '모델', 'scoring': '점수 산식', 'rulebook': '룰북',
    'schema': '데이터 스키마', 'news': '뉴스 분석',
}

BUMP_PATCH = 'patch'
BUMP_DATE = 'date'
BUMP_MAJOR = 'major'

#: 변경 종류 → 올릴 자리. 여기 없는 종류는 등록을 거부한다 (임의 판단 금지).
CHANGE_KINDS = {
    'ui': BUMP_PATCH,
    'copy': BUMP_PATCH,
    'data_fix': BUMP_PATCH,
    'bugfix': BUMP_PATCH,
    'weight': BUMP_DATE,
    'gate': BUMP_DATE,
    'algorithm': BUMP_DATE,
    'engine_swap': BUMP_MAJOR,
}
KIND_KO = {
    'ui': '화면 수정', 'copy': '문구 수정', 'data_fix': '데이터 오류 수정',
    'bugfix': '버그 수정', 'weight': '점수 가중치 변경',
    'gate': '게이트 변경', 'algorithm': '알고리즘 변경',
    'engine_swap': '엔진 전면 교체',
}

_RE_VER = re.compile(r'^v(\d{4})\.(\d{2})\.(\d{2})(?:\.(\d+))?$')


def parse(v: str):
    """'v2026.08.02.1' → (date(2026,8,2), 1). 형식이 틀리면 None."""
    m = _RE_VER.match(str(v or '').strip())
    if not m:
        return None
    y, mo, d, p = m.groups()
    try:
        return date(int(y), int(mo), int(d)), int(p or 0)
    except ValueError:
        return None


def fmt(d: date, patch: int) -> str:
    return f"v{d.year:04d}.{d.month:02d}.{d.day:02d}.{patch}"


def bump(current: str, kind: str, today: date | None = None) -> str:
    """
    현재 버전 + 변경 종류 → 다음 버전.

    PATCH 는 같은 날짜 안에서 올라간다. DATE·MAJOR 는 날짜를 오늘로 옮기고
    패치를 0 으로 되돌린다 — 날짜가 바뀌었는데 패치가 이어지면 '어제 것의
    수정'처럼 보여 오해를 부른다.
    """
    if kind not in CHANGE_KINDS:
        raise ValueError(
            f"등록되지 않은 변경 종류: {kind} — {sorted(CHANGE_KINDS)} 중 하나여야 "
            "합니다. 어느 자리를 올릴지 사람이 즉흥으로 정하지 않는다.")
    today = today or date.today()
    p = parse(current)
    if p is None:
        return fmt(today, 0)
    cur_d, cur_p = p
    how = CHANGE_KINDS[kind]
    if how == BUMP_PATCH:
        if cur_d == today:
            return fmt(cur_d, cur_p + 1)
        # 날짜가 지났으면 오늘 날짜의 첫 패치로 시작한다
        return fmt(today, 1) if today > cur_d else fmt(cur_d, cur_p + 1)
    # DATE·MAJOR — 결론이 바뀔 수 있는 변경.
    # 같은 날 두 번 알고리즘을 바꿔도 버전이 같으면 안 된다. 날짜 자리는
    # 달력이 아니라 **세대(generation)** 로 쓴다 — 사용자 예시가 그렇다
    # (v2026.08.02 에서 로직을 바꾸면 v2026.08.03.0).
    from datetime import timedelta
    nxt_d = today if today > cur_d else (cur_d + timedelta(days=1))
    return fmt(nxt_d, 0)


def _load() -> dict:
    try:
        with open(LEDGER, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {'axes': {}, 'history': []}


def _save(led: dict) -> None:
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(LEDGER, 'w', encoding='utf-8') as f:
        json.dump(led, f, ensure_ascii=False, indent=1)


def current(axis: str = 'model') -> str:
    return str((_load().get('axes') or {}).get(axis) or 'v2026.08.02.0')


def snapshot() -> dict:
    """지금 이 순간의 모든 축 버전 — 분석 결과·케이스에 통째로 붙인다."""
    led = _load()
    ax = led.get('axes') or {}
    return {a: str(ax.get(a) or 'v2026.08.02.0') for a in AXES}


def release(axis: str, kind: str, *, reason: str, effective: str = '',
            note: str = '') -> dict:
    """
    한 축의 버전을 올리고 이력에 남긴다.

    reason(변경 이유)은 필수다 — 이유 없는 버전 증가는 추적을 무의미하게 만든다.
    이전 버전은 previous 로 보존한다 (덮어쓰지 않는다).
    """
    if not str(reason or '').strip():
        raise ValueError('변경 이유 없이 버전을 올릴 수 없습니다.')
    if axis not in AXES:
        raise ValueError(f'알 수 없는 축: {axis} — {AXES} 중 하나여야 합니다.')
    led = _load()
    led.setdefault('axes', {})
    led.setdefault('history', [])
    prev = str(led['axes'].get(axis) or 'v2026.08.02.0')
    nxt = bump(prev, kind)
    led['axes'][axis] = nxt
    entry = {
        'axis': axis, 'axis_ko': AXIS_KO[axis],
        'version': nxt, 'previous': prev,
        'kind': kind, 'kind_ko': KIND_KO[kind],
        'bump': CHANGE_KINDS[kind],
        'reason': str(reason).strip(),
        'note': str(note or '').strip(),
        'created_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'effective_from': str(effective or date.today().isoformat()),
    }
    led['history'].insert(0, entry)      # 최신이 앞
    _save(led)
    return entry


def history(limit: int = 50, axis: str = '') -> list:
    h = (_load().get('history') or [])
    if axis:
        h = [e for e in h if e.get('axis') == axis]
    return h[:limit]


def stamp(payload: dict | None = None) -> dict:
    """
    분석 결과·케이스에 붙일 버전 도장.

    사용자 요청 필드를 모두 담는다: 모델·산식·룰북·스키마·뉴스 버전,
    생성 시각, 적용 시작일, 이전 버전, 변경 이유.
    """
    led = _load()
    snap = snapshot()
    last = (led.get('history') or [{}])[0]
    out = {
        'versions': snap,
        'versions_ko': {AXIS_KO[a]: snap[a] for a in AXES},
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'effective_from': str(last.get('effective_from')
                              or date.today().isoformat()),
        'previous_version': str(last.get('previous') or ''),
        'change_reason': str(last.get('reason') or ''),
        'change_kind': str(last.get('kind_ko') or ''),
    }
    if payload:
        out.update(payload)
    return out
