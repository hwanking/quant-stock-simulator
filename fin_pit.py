# -*- coding: utf-8 -*-
"""
재무 시점 보관 (point-in-time) — 오늘 받은 연간 재무 응답을 **오늘 날짜로** 박제한다 (라운드 341).

■ 왜
  라운드 336 이 셌다: 이 저장소에는 재무 시점 자료가 없고(원장 43칸에 재무 0), 받는 연간 재무는 **재작성된
  현재 보고치**라 과거 기준일에 붙이면 누출이다(§1). *"좋은 기업인가"* 를 원장으로 재려면 **그날 알 수 있던
  재무**가 날짜와 함께 남아 있어야 한다 — 그것은 시작한 날부터만 쌓이고 소급되지 않는다. 늦출수록 손해라
  오늘 시작한다. 추가 네트워크 비용 0 — 엔진이 이미 받아 둔 응답(`bitemporal_engine.ANNUAL_FIN_BY_CODE` ·
  라운드 339)을 옮겨 적을 뿐이다.

■ 무엇을 남기나
  종목·날짜마다 한 줄: 응답의 연도 열(추정 여부 그대로 · `isConsensus`)과 항목별 값. 값은 수로 옮기되
  '-' 는 None(0 으로 안 채운다 · §3). 같은 (종목, 날짜)는 한 번만(append-only · 멱등). 값을 해석하거나
  고르지 않는다 — 규칙은 나중에 사전등록으로(§2).

■ 범위 (정직하게)
  엔진이 그날 **정밀분석한 종목**만 남는다 — 클라우드에서는 전방 판정 기록기의 상위 60종목이다. 전 종목이
  아니다. 그 사실을 화면·문서가 적는다.
"""
import io
import json
import os

from bitemporal_engine import _api_num

PROJ = os.path.dirname(os.path.abspath(__file__))
#: 저장 자리 — 연구 자료(개인 자료 아님 · 백업 화이트리스트에 넣는다)
PATH = os.path.join(PROJ, '.portfolio', 'fin_pit.jsonl')


def rows_from(annual_by_code, date):
    """{code: finance 응답} → 시점 행 목록. 응답이 비었거나 표가 없으면 그 종목은 건너뛴다(지어내지 않는다)."""
    out = []
    for code, fin in sorted((annual_by_code or {}).items()):
        fi = (fin or {}).get('financeInfo') or {}
        heads = [h for h in (fi.get('trTitleList') or []) if isinstance(h, dict) and h.get('key')]
        rows = [r for r in (fi.get('rowList') or []) if isinstance(r, dict) and r.get('title')]
        if not heads or not rows:
            continue
        periods = [dict(key=str(h['key']), title=str(h.get('title') or h['key']),
                        estimate=str(h.get('isConsensus') or 'N').upper() == 'Y') for h in heads]
        items = {}
        for r in rows:
            cols = r.get('columns') or {}
            vals = {}
            for p in periods:
                c = cols.get(p['key']) if isinstance(cols, dict) else None
                vals[p['key']] = _api_num(c.get('value') if isinstance(c, dict) else c)
            items[str(r['title']).strip()] = vals
        out.append(dict(date=str(date)[:10], code=str(code), periods=periods, items=items))
    return out


def _existing_keys(path):
    keys = set()
    if not os.path.exists(path):
        return keys
    with io.open(path, encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
                keys.add((str(r.get('code')), str(r.get('date'))[:10]))
            except Exception:                                  # noqa: BLE001
                continue
    return keys


def append_rows(path, rows):
    """같은 (종목, 날짜)가 이미 있으면 안 쓴다(멱등). 반환: (새로 쓴 수, 이미 있어 건너뛴 수)."""
    have = _existing_keys(path)
    wrote = skipped = 0
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, 'a', encoding='utf-8') as f:
        for r in rows:
            k = (str(r.get('code')), str(r.get('date'))[:10])
            if k in have:
                skipped += 1
                continue
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
            have.add(k)
            wrote += 1
    return wrote, skipped


def coverage(path=PATH):
    """{'rows', 'codes', 'dates', 'first', 'last'} — 없으면 rows 0."""
    rows, codes, dates = 0, set(), set()
    if os.path.exists(path):
        with io.open(path, encoding='utf-8') as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    r = json.loads(ln)
                except Exception:                              # noqa: BLE001
                    continue
                rows += 1
                codes.add(str(r.get('code')))
                dates.add(str(r.get('date'))[:10])
    ds = sorted(d for d in dates if d)
    return dict(rows=rows, codes=len(codes), dates=len(ds), first=ds[0] if ds else None, last=ds[-1] if ds else None)
