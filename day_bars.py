# -*- coding: utf-8 -*-
"""GANEUM DAY — 분봉 연구 원장 (라운드 516 · 2026-10-13).

사용자가 붙인 단타 제안을 검토하고 고른 길: *"분봉 수집부터"*. 이 저장소는 지금까지 **일봉만** 다뤘다 — 단타 전략(갭 뒤 첫 눌림 ·
VWAP 회복 · 장 초반 고점 재돌파 …)은 분봉 없이는 잴 수 없다. 네이버 차트 끝점은 분봉을 **최근 7거래일**만 주고 그나마 **시가·고가·저가가
비어 있다**(종가·거래량만 · 2026-10-13 실측) — 손절과 목표 중 무엇이 먼저 닿았는지를 재현할 수 없다. 한국투자 일별 분봉 조회
(`FHKST03010230`)는 서버에 **최대 1년** 분봉을 두고 한 번에 120건까지 준다(공식 샘플의 설명).

■ 이 모듈은 **받은 값만** 적는다(§3) — 빈 칸을 메우지 않고, 앞 봉 값을 끌어오지 않고, 모양이 깨진 봉(고가 < 저가 등)은 버리고 **그 수를
  사유별로 센다.** 판정·주문·점수 없음 — 연구 원장일 뿐이다. 전략과 그 문턱은 결과를 보기 전에 사전등록으로 정한다(§2).
■ 저장: `.portfolio/day_bars/<종목코드>.jsonl`(이 PC 에만 · 백업 거부) · 한 줄 = 분봉 하나 · 열쇠 (날짜, 시각) 로 중복을 막는다.
  받아 온 기록(무엇을 언제 몇 번 불러 몇 개를 받았나)은 `_fetched.jsonl` 에 따로 — 되받기·이어 받기의 근거.
"""
from __future__ import annotations

import io
import json
import os

PROJ = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(PROJ, '.portfolio', 'day_bars')
SCHEMA = 'db-1'

#: 한국투자 분봉 응답(output2)의 칸 이름 → 원장 칸. 이 표에 없는 모양이면 지어 읽지 않는다(그 행을 '모르는 칸'으로 센다).
KIS_FIELDS = dict(day='stck_bsop_date', hms='stck_cntg_hour', o='stck_oprc', h='stck_hgpr', l='stck_lwpr', c='stck_prpr',
                  v='cntg_vol', cum_amt='acml_tr_pbmn')


def _num(v):
    try:
        if v is None or str(v).strip() == '':
            return None
        return float(str(v).replace(',', ''))
    except (TypeError, ValueError):
        return None


def parse_kis_rows(rows, code):
    """한국투자 분봉 행들 → (분봉 목록, 버린 사유 {사유: 수}). 판정 없음 · 값을 만들지 않는다."""
    bars, why = [], {}

    def drop(reason):
        why[reason] = why.get(reason, 0) + 1

    for r in rows or []:
        if not isinstance(r, dict):
            drop('행 모양 아님')
            continue
        d, t = str(r.get(KIS_FIELDS['day']) or '').strip(), str(r.get(KIS_FIELDS['hms']) or '').strip()
        if len(d) != 8 or not d.isdigit() or len(t) != 6 or not t.isdigit():
            drop('날짜·시각 칸 없음 또는 모양 아님')
            continue
        o, h, l, c, v = (_num(r.get(KIS_FIELDS[k])) for k in ('o', 'h', 'l', 'c', 'v'))
        if None in (o, h, l, c, v):
            drop('가격·거래량 칸 비었음')
            continue
        if min(o, h, l, c) <= 0 or v < 0:
            drop('0 이하 가격 또는 음수 거래량')
            continue
        if not (l <= min(o, c) and max(o, c) <= h):
            drop('봉 모양 깨짐(고가·저가가 시가·종가를 안 감쌈)')
            continue
        bars.append(dict(code=str(code), day=f'{d[:4]}-{d[4:6]}-{d[6:]}', t=f'{t[:2]}:{t[2:4]}', o=o, h=h, l=l, c=c, v=v,
                         cum_amt=_num(r.get(KIS_FIELDS['cum_amt']))))
    bars.sort(key=lambda b: (b['day'], b['t']))
    return bars, why


def path_for(code, root=None):
    return os.path.join(root or ROOT, f'{code}.jsonl')


def existing_keys(code, root=None):
    """이미 적힌 (날짜, 시각) 열쇠 — 못 읽으면 빈 집합(그 사실은 부르는 쪽이 셀 일이 아니라 다시 받으면 중복 열쇠가 막는다)."""
    p = path_for(code, root)
    keys = set()
    if not os.path.exists(p):
        return keys
    with io.open(p, encoding='utf-8') as f:
        for ln in f:
            try:
                d = json.loads(ln)
                keys.add((d['day'], d['t']))
            except (ValueError, KeyError, TypeError):
                continue
    return keys


def append_bars(code, bars, root=None):
    """분봉을 덧붙인다 — 이미 있는 (날짜, 시각) 은 건너뛴다(멱등). → (더한 수, 건너뛴 수)."""
    if os.environ.get('GAEUM_NO_LOCAL_WRITE') == '1':
        return 0, len(bars or [])
    keys = existing_keys(code, root)
    new = [b for b in bars or [] if (b['day'], b['t']) not in keys]
    if new:
        os.makedirs(root or ROOT, exist_ok=True)
        with io.open(path_for(code, root), 'a', encoding='utf-8') as f:
            for b in new:
                f.write(json.dumps(dict(b, schema=SCHEMA), ensure_ascii=False) + '\n')
    return len(new), len(bars or []) - len(new)


def fetched_path(root=None):
    return os.path.join(root or ROOT, '_fetched.jsonl')


def fetched_set(root=None):
    """받아 온 (종목, 날짜) — 이어 받기에서 건너뛴다. 못 읽은 줄은 건너뛴다."""
    out = set()
    p = fetched_path(root)
    if not os.path.exists(p):
        return out
    with io.open(p, encoding='utf-8') as f:
        for ln in f:
            try:
                d = json.loads(ln)
                if d.get('complete'):
                    out.add((d['code'], d['day']))
            except (ValueError, KeyError, TypeError):
                continue
    return out


def log_fetched(rec, root=None):
    if os.environ.get('GAEUM_NO_LOCAL_WRITE') == '1':
        return
    os.makedirs(root or ROOT, exist_ok=True)
    with io.open(fetched_path(root), 'a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')


def day_summary(bars):
    """하루치 분봉 요약 — (봉 수, 첫 시각, 마지막 시각). 판정 없음."""
    if not bars:
        return 0, None, None
    ts = sorted(b['t'] for b in bars)
    return len(bars), ts[0], ts[-1]
