# -*- coding: utf-8 -*-
"""
스윙 자동매매 위험 한도와 주문 수량 (라운드 446) — **기본값이 없다.**

한도 여섯은 사용자가 정한다. 1% · 10% · 15% 같은 수를 여기서 고르면 그것이 손으로 고른 운영 값이고(§2), 그 성과는 잰 적이
없다. 정하기 전에는 모의투자·실전 주문이 막힌다(`missing`). 수량은 아래 네 제한 중 **가장 작은 것**이고, 어느 제한이 정했는지
(`binding`)를 같이 돌려준다 — 화면이 "왜 이 수량인가"를 말할 수 있게.

  ① 거래당 위험: 손절에 닿았을 때 잃는 돈(왕복 비용 포함) ≤ 거래당 최대 손실
  ② 종목당 비중: 주문 금액 ≤ 총평가 × 종목당 최대 비중
  ③ 전체 주식 비중: 지금 주식 평가 + 주문 금액 ≤ 총평가 × 최대 주식 비중
  ④ 남길 현금: 미수 없는 주문 가능 금액 − 총평가 × 최소 현금 비중 ≥ 주문 금액

손절가에 그대로 팔린다고 가정한다 — 실제로는 더 아래에서 팔릴 수 있다(라운드 367 이 바로 그 가정에 속을 뻔했다). 화면은 그
가정을 같이 적는다.
"""
import math

#: (열쇠, 이름, 단위) — 순서가 화면 순서다
LIMITS = (
    ('risk_per_trade_krw', '거래당 최대 손실', '원'),
    ('max_position_pct', '종목당 최대 비중', '%'),
    ('max_total_exposure_pct', '최대 주식 비중', '%'),
    ('min_cash_pct', '최소 현금 비중', '%'),
    ('max_open_positions', '최대 동시 보유 종목', '개'),
    ('max_daily_new_orders', '하루 최대 신규 주문', '건'),
)
_PCT = {'max_position_pct', 'max_total_exposure_pct', 'min_cash_pct'}
_INT = {'max_open_positions', 'max_daily_new_orders'}


def _f(v):
    try:
        return None if v is None or v == '' else float(v)
    except (TypeError, ValueError):
        return None


def validate(cfg):
    """→ (값 dict, 빠진 이름 목록, 문제 목록). 빠졌거나 범위 밖이면 그 한도는 없는 것으로 본다."""
    vals, missing, problems = {}, [], []
    for k, label, _u in LIMITS:
        v = _f((cfg or {}).get(k))
        if v is None:
            missing.append(label)
            continue
        if k in _PCT and not (0 < v <= 100):
            problems.append(f'{label}는 0 보다 크고 100 이하여야 합니다 (받은 값 {v:g})')
            continue
        if k in _INT and not (v >= 1 and float(v).is_integer()):
            problems.append(f'{label}는 1 이상의 정수여야 합니다 (받은 값 {v:g})')
            continue
        if k == 'risk_per_trade_krw' and v <= 0:
            problems.append(f'{label}은 0 보다 커야 합니다')
            continue
        vals[k] = int(v) if k in _INT else v
    if 'min_cash_pct' in vals and 'max_total_exposure_pct' in vals \
            and vals['min_cash_pct'] + vals['max_total_exposure_pct'] > 100 + 1e-9:
        problems.append('최소 현금 비중 + 최대 주식 비중이 100% 를 넘습니다 — 둘을 같이 지킬 수 없습니다')
    return vals, missing, problems


def size(entry, stop, account, limits, cost_pct, orderable_amt=None):
    """주문 수량 → dict(qty, binding, per_share_risk, planned_loss, caps, reason).

    account: dict(total_eval, stock_eval, cash) — 한국투자 잔고에서. orderable_amt: 미수 없는 주문 가능 금액(없으면 cash).
    한 칸이라도 못 읽으면 수량을 안 낸다(qty 0 · 사유) — 모르는 것을 0 이나 추정으로 채우지 않는다(§3)."""
    vals, missing, problems = validate(limits)
    if missing or problems:
        return dict(qty=0, binding=None, reason='위험 한도가 정해지지 않았습니다: ' + ', '.join(missing + problems))
    entry, stop = _f(entry), _f(stop)
    if not entry or stop is None or stop >= entry:
        return dict(qty=0, binding=None, reason='진입가·손절가가 없거나 손절이 진입가 이상입니다')
    eq = _f((account or {}).get('total_eval'))
    stock = _f((account or {}).get('stock_eval'))
    cash = _f(orderable_amt) if orderable_amt is not None else _f((account or {}).get('cash'))
    if not eq or eq <= 0 or stock is None or cash is None:
        return dict(qty=0, binding=None, reason='계좌 총평가·주식 평가·주문 가능 금액 중 못 읽은 것이 있습니다')
    c = (_f(cost_pct) or 0.0) / 100.0
    per_share = (entry - stop) + entry * c
    caps = {
        '거래당 위험': math.floor(vals['risk_per_trade_krw'] / per_share),
        '종목당 비중': math.floor(eq * vals['max_position_pct'] / 100.0 / entry),
        '전체 주식 비중': math.floor(max(0.0, eq * vals['max_total_exposure_pct'] / 100.0 - stock) / entry),
        '남길 현금': math.floor(max(0.0, cash - eq * vals['min_cash_pct'] / 100.0) / entry),
    }
    binding = min(caps, key=lambda k: caps[k])
    q = max(0, int(caps[binding]))
    return dict(qty=q, binding=binding, per_share_risk=per_share, planned_loss=q * per_share, caps=caps,
                reason=('' if q >= 1 else f"'{binding}' 제한으로 한 주도 살 수 없습니다"))


def count_gates(limits, open_managed, new_orders_today):
    """동시 보유 수 · 하루 신규 주문 수 → 막는 사유 목록(빈 목록이면 통과)."""
    vals, missing, problems = validate(limits)
    out = []
    if missing or problems:
        return ['위험 한도가 정해지지 않았습니다']
    if open_managed >= vals['max_open_positions']:
        out.append(f"동시 보유 {open_managed}개 — 최대 {vals['max_open_positions']}개")
    if new_orders_today >= vals['max_daily_new_orders']:
        out.append(f"오늘 신규 주문 {new_orders_today}건 — 최대 {vals['max_daily_new_orders']}건")
    return out
