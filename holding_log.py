# -*- coding: utf-8 -*-
"""보유 변경 기록 — 추가로 산 물량이 나중에 어떻게 됐는지 셀 수 있게 (라운드 388).

사용자(2026-09-29): *"추가매수하라고 해서 더 샀는데 결국 손해 — 거의 추가매수한 게 손해 본 듯."* 앱은 체결 기록을
남기지 않아 그 물음에 **답할 수 없었다**('팔았음'은 매입가·수량만 비운다). 이 모듈은 사용자가 **앱에 적은** 매입가·
수량이 바뀐 순간을 이 PC 에만 적는다. 지난 거래는 되살릴 수 없다 — 앞으로의 것만 셀 수 있다.

■ 무엇을 아는가 · 모르는가
  · 안다: 바뀌기 전·후의 평단·수량, 그 순간 앱이 그 종목에 뭐라고 했는지(표의 판정 · 추가매수 판정).
  · 계산한다: 추가 단가 = (새 평단 × 새 수량 − 옛 평단 × 옛 수량) ÷ 늘어난 수량 — 산수다(문턱 없음).
    사용자가 증권사 평단·수량을 그대로 옮겨 적으면 실제 추가 단가와 같다. 수수료가 평단에 들어 있으면 그만큼 다르다.
  · 모른다: **판 가격.** '팔았음'·수량 줄임은 그 순간의 참고 가격만 적는다(체결가가 아니다 · §3 — 판 가격을
    지어내지 않는다). 그래서 판 물량의 확정 손익은 '모름'이고, 참고 가격 기준 값을 따로 적는다.

■ §9
  파일은 `.portfolio/holding_log.jsonl`(gitignore) · 백업 묶음 목록(INCLUDE)에 없다 · 외부 API/LLM 로 안 보낸다.
  배포 앱은 로컬 저장이 꺼져 있어 적지 않는다(web_app 이 ALLOW_LOCAL_STORE 로 가른다).
"""
from __future__ import annotations

import json
import os

PROJ = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(PROJ, '.portfolio', 'holding_log.jsonl')


def _num(v, as_int=False):
    """양수면 그 수, 아니면 None (NaN·0 이하·숫자 아님) — web_app._wl_pos_num 과 같은 규칙."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f <= 0:
        return None
    return int(round(f)) if as_int else f


def _norm(code):
    try:
        import portfolio as _pf
        return _pf.normalize_code(code)
    except Exception:                                          # noqa: BLE001
        return str(code or '').strip()


def change_events(before, after, at, px_by_code=None, app_said=None, batch=None):
    """두 목록(관심종목 행) → 매입가·수량이 바뀐 행마다 기록 한 줄. 순수 함수.

    kind: 'buy'(새로 삼) · 'add'(수량이 늘었다) · 'reduce'(수량이 줄었다) · 'sell_all'(보유 기록이 비었다) ·
          'fix'(수량은 같고 평단만 바뀌었다 — 정정) · 'edit'(수량을 몰라 가르지 못함).
    app_said: {코드: (표 판정 kind, 추가매수 판정 등급)} — 그 순간 앱이 뭐라고 했나(있을 때만).
    """
    px_by_code = px_by_code or {}
    app_said = app_said or {}
    old = {_norm(w.get('code')): w for w in (before or [])}
    out = []
    for w in (after or []):
        c = _norm(w.get('code'))
        o = old.get(c)
        if o is None:
            continue
        p0, q0 = _num(o.get('paid')), _num(o.get('qty'), as_int=True)
        p1, q1 = _num(w.get('paid')), _num(w.get('qty'), as_int=True)
        if (p0, q0) == (p1, q1):
            continue
        ev = dict(at=str(at), batch=batch, code=c, name=str(w.get('name') or o.get('name') or c),
                  paid_before=p0, qty_before=q0, paid_after=p1, qty_after=q1,
                  px_at_record=_num(px_by_code.get(c)))
        said = app_said.get(c)
        if said:
            ev['app_kind'], ev['app_avg_down'] = said[0], said[1]
        if not p0 and p1:
            ev.update(kind='buy', qty=q1, price=p1)
        elif p0 and not p1:
            ev.update(kind='sell_all', qty=q0, price=None)
        elif q0 and q1 and q1 > q0:
            added = q1 - q0
            cost = (p1 * q1) - (p0 * q0)
            ev.update(kind='add', qty=added, price=(cost / added if cost > 0 else None))
        elif q0 and q1 and q1 < q0:
            ev.update(kind='reduce', qty=q0 - q1, price=None)
        elif q0 and q1 and q1 == q0:
            ev.update(kind='fix', qty=0, price=None)
        else:
            ev.update(kind='edit', qty=None, price=None)
        out.append(ev)
    return out


def append(events, path=PATH):
    """기록을 덧붙인다. 적은 줄 수를 돌려준다(없으면 0)."""
    if not events:
        return 0
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'a', encoding='utf-8') as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + '\n')
    return len(events)


def mark_undone(batch, at, path=PATH):
    """되돌리기 — 그 묶음(batch)의 기록을 **지우지 않고** '되돌림' 한 줄을 덧붙인다(읽는 쪽이 뺀다)."""
    if not batch:
        return 0
    return append([dict(kind='undo', batch=batch, at=str(at))], path)


def load(path=PATH):
    """되돌린 묶음을 뺀 기록(시간 순). 못 읽으면 빈 목록."""
    try:
        with open(path, encoding='utf-8') as f:
            rows = [json.loads(ln) for ln in f if ln.strip()]
    except (OSError, ValueError):
        return []
    undone = {r.get('batch') for r in rows if r.get('kind') == 'undo' and r.get('batch')}
    return [r for r in rows if r.get('kind') != 'undo' and r.get('batch') not in undone]


def add_tranches(events, px_by_code=None):
    """'추가로 산 물량' 한 덩어리씩 — 그 뒤에 판 기록이 있으면 판 것으로 본다.

    반환 행: dict(code, name, at, qty, price, app_kind, app_avg_down, status('보유 중'|'이후 매도'),
                  px(지금 가격 또는 매도 기록 시점 참고 가격), pnl, ret, px_basis)
    가격을 모르면 pnl·ret 은 None(0 으로 채우지 않는다 · §3). 판 물량의 확정 손익은 모른다 — px_basis 가 그렇게 말한다.
    """
    px_by_code = px_by_code or {}
    evs = list(events or [])
    rows = []
    for i, e in enumerate(evs):
        if e.get('kind') != 'add' or not e.get('qty'):
            continue
        later = [x for x in evs[i + 1:] if x.get('code') == e.get('code')
                 and x.get('kind') in ('reduce', 'sell_all')]
        if later:
            status, px = '이후 매도', _num(later[0].get('px_at_record'))
            basis = '판 가격을 안 받아 확정 손익은 모름 — 매도를 적을 때 앱이 가진 가격(체결가 아님) 기준 참고'
        else:
            status, px = '보유 중', _num(px_by_code.get(e.get('code')))
            basis = '지금 가격 기준(평가)'
        price = _num(e.get('price'))
        pnl = ((px - price) * e['qty']) if (px and price) else None
        ret = ((px / price - 1.0) * 100.0) if (px and price) else None
        rows.append(dict(code=e.get('code'), name=e.get('name'), at=e.get('at'), qty=e.get('qty'),
                         price=price, app_kind=e.get('app_kind'), app_avg_down=e.get('app_avg_down'),
                         status=status, px=px, pnl=pnl, ret=ret, px_basis=basis))
    return rows
