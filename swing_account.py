# -*- coding: utf-8 -*-
"""
내 한국투자 계좌 칸의 **사실 셈** (라운드 454) — 잔고 dict(`broker_kis.KisBroker.get_balance` 또는 장부 스냅샷) → 수.

사용자가 붙인 다른 워크스페이스의 계좌 화면(총자산 · 보유 매수금액 · 평가손익 · 수익률 · 현금 · 자산 구성 · 평가 범위 ·
설정 비교 · 보유 표)을 **우리 자료로 되는 것만** 옮겼다. 전부 순수 함수이고 판정 낱말이 없다 — 매수·매도 추천이 아니라
지금 계좌의 구성을 설명하는 수다(§3 · §9). 새 문턱도 없다: '참고 비교'는 사용자가 ⑥에 정한 위험 한도와만 견준다.

못 셈하는 것은 None 으로 두고 수를 지어내지 않는다 — 현재가가 없는 보유는 평가·비중에서 빠지고 그 수를 같이 적는다.
수익률은 거래소 평균 매수가 기준 · 수수료·세금 전 · 매도 전의 평가값이다(실현 손익이 아니다).
"""


def _f(v):
    try:
        return None if v is None or v == '' else float(v)
    except (TypeError, ValueError):
        return None


def summarize(bal):
    """잔고 → dict(rows, n, priced, n_pnl, cash, cash_d2, total, total_src, buy_sum, pnl_sum, ret_total, winners, losers, flat,
    weights, cash_w, stock_w, top1, top2, unpriced_codes). 계좌 수가 없는 칸은 None."""
    rows = []
    for p in (bal or {}).get('positions') or []:
        qty = int(_f(p.get('qty')) or 0)
        avg, px = _f(p.get('avg_price')), _f(p.get('price'))
        buy = qty * avg if (qty and avg is not None) else None
        ev = _f(p.get('eval_amt'))
        if ev is None and px is not None and qty:
            ev = qty * px
        pnl = _f(p.get('pnl'))
        if pnl is None and ev is not None and buy is not None:
            pnl = ev - buy
        ret = (pnl / buy * 100.0) if (pnl is not None and buy) else _f(p.get('pnl_pct'))
        rows.append(dict(code=str(p.get('code') or ''), name=p.get('name') or '', qty=qty,
                         sellable=(int(_f(p.get('sellable_qty'))) if _f(p.get('sellable_qty')) is not None else None),
                         avg=avg, price=px, buy=buy, eval=ev, pnl=pnl, ret=ret))
    cash, cash_d2 = _f((bal or {}).get('cash')), _f((bal or {}).get('cash_d2'))
    priced = [r for r in rows if r['eval'] is not None]
    stock_sum = sum(r['eval'] for r in priced) if priced else 0.0
    total = _f((bal or {}).get('total_eval'))
    total_src = 'broker' if total is not None else None
    if total is None and cash is not None:
        total, total_src = cash + stock_sum, 'cash+eval'
    both = [r for r in rows if r['pnl'] is not None and r['buy']]
    buy_sum = sum(r['buy'] for r in both) if both else None
    pnl_sum = sum(r['pnl'] for r in both) if both else None
    ret_total = (pnl_sum / buy_sum * 100.0) if (both and buy_sum) else None
    weights = []
    if total and total > 0:
        for r in priced:
            weights.append(dict(code=r['code'], label=f"{r['name']} ({r['code']})" if r['name'] else r['code'],
                                pct=r['eval'] / total * 100.0))
        weights.sort(key=lambda w: -w['pct'])
    cash_w = (cash / total * 100.0) if (total and total > 0 and cash is not None) else None
    stock_w = (stock_sum / total * 100.0) if (total and total > 0 and priced) else None
    return dict(rows=rows, n=len(rows), priced=len(priced), n_pnl=len(both), cash=cash, cash_d2=cash_d2, total=total,
                total_src=total_src, buy_sum=buy_sum, pnl_sum=pnl_sum, ret_total=ret_total,
                winners=sum(1 for r in both if r['pnl'] > 0), losers=sum(1 for r in both if r['pnl'] < 0),
                flat=sum(1 for r in both if r['pnl'] == 0), weights=weights, cash_w=cash_w, stock_w=stock_w,
                top1=(weights[0]['pct'] if weights else None),
                top2=(sum(w['pct'] for w in weights[:2]) if len(weights) >= 2 else None),
                unpriced_codes=[r['code'] for r in rows if r['eval'] is None])


def _won(v):
    return '—' if v is None else f'{v:,.0f}원'


def glance_lines(s):
    """'내 계좌 한눈에' — 사실 문장 셋까지(없는 수는 문장도 없다). 추천 낱말 없음."""
    out = []
    if s['n_pnl']:
        sign = '평가이익' if (s['pnl_sum'] or 0) >= 0 else '평가손실'
        out.append(f"보유 {s['n']}종목 중 손익을 셈한 {s['n_pnl']}종목은 거래소 평균 매수금액 {_won(s['buy_sum'])} 대비 "
                   f"{_won(abs(s['pnl_sum']))} {sign}입니다({s['ret_total']:+.2f}% · 매도 전 · 수수료·세금 제외).")
    elif s['n']:
        out.append(f"보유 {s['n']}종목 — 평균 매수가나 현재가가 없어 손익을 셈하지 못했습니다.")
    if s['cash_w'] is not None:
        out.append(f"현금(예수금) 비중 {s['cash_w']:.2f}% · 보유 종목 {s['n']}개.")
    if s['weights']:
        w = s['weights'][0]
        out.append(f"{w['label']} 비중이 {w['pct']:.2f}%로 가장 큽니다 — 이 종목의 가격 변동이 계좌에 가장 크게 반영됩니다.")
    return out


def composition(s):
    """자산 구성 막대 재료 — [{'label','pct','sub'}] · 현금 포함. 총평가가 없으면 빈 목록."""
    items = [dict(label=w['label'], pct=w['pct']) for w in s['weights']]
    if s['cash_w'] is not None:
        items.append(dict(label='현금(예수금)', pct=s['cash_w']))
    return items


def scope_chips(s):
    """평가 범위 칩 재료 — 수익 중 · 손실 중 · 본전(열린 보유의 지금 상태이지 매매 승률이 아니다)."""
    return [dict(label='수익 중', count=s['winners'], tone='up'), dict(label='손실 중', count=s['losers'], tone='down'),
            dict(label='본전', count=s['flat'])]


def limit_checks(s, limits):
    """⑥의 위험 한도와 지금 계좌를 **참고로** 견준다 → [dict(name, setting, current, status)] · 한도가 없으면 [].
    규칙 위반 판정·건강 점수·매매 지시가 아니다 — 사용자가 직접 산 보유를 자동매매가 산 것으로 보지 않는다."""
    import swing_risk
    vals, missing, problems = swing_risk.validate(limits or {})
    if missing or problems:
        return []
    out = []

    def add(name, setting, current, unit, higher_is_over=True):
        if current is None:
            st = '비교 불가(값 없음)'
        else:
            over = current > setting if higher_is_over else current < setting
            st = '참고 한도 밖' if over else '참고 한도 이내'
        out.append(dict(name=name, setting=setting, current=current, unit=unit, status=st))
    add('보유 종목 수', vals['max_open_positions'], s['n'], '개')
    add('주식 평가 비중', vals['max_total_exposure_pct'], s['stock_w'], '%')
    add('최대 단일 종목 비중', vals['max_position_pct'], s['top1'], '%')
    add('현금 비중(최소)', vals['min_cash_pct'], s['cash_w'], '%', higher_is_over=False)
    return out


def table_rows(s, ownership_label=None, quote_ts=None):
    """보유 표 한 줄씩 — 비중 · 수량/매도 가능 · 평균 매수가 · 현재가 · 평가금액 · 평가손익/수익률 · 시세 시각 · 관리."""
    wmap = {w['code']: w['pct'] for w in s['weights']}
    out = []
    for r in s['rows']:
        w = wmap.get(r['code'])
        pnl = ('—' if r['pnl'] is None else f"{r['pnl']:+,.0f}원") + (f" / {r['ret']:+.2f}%" if r['ret'] is not None else '')
        out.append({'종목': f"{r['name']} ({r['code']})" if r['name'] else r['code'],
                    '자산 비중': (f'{w:.2f}%' if w is not None else '—'),
                    '수량 / 매도 가능': f"{r['qty']:,} / {r['sellable'] if r['sellable'] is not None else '—'}",
                    '평균 매수가': _won(r['avg']), '현재가': _won(r['price']), '평가금액': _won(r['eval']),
                    '평가손익 / 수익률': pnl, '시세 시각': quote_ts or '—',
                    '관리': (ownership_label(r['code']) if ownership_label else '—')})
    return out


def changed(prev_bal, bal):
    """장부 스냅샷을 다시 적을지 — 보유(종목·수량·현재가·평단)나 예수금·총평가가 바뀌었을 때만(15초마다 같은 값을 쌓지 않는다)."""
    if not prev_bal:
        return True

    def key(b):
        return (tuple(sorted((str(p.get('code')), int(_f(p.get('qty')) or 0), _f(p.get('price')), _f(p.get('avg_price')))
                             for p in (b.get('positions') or []))),
                _f(b.get('cash')), _f(b.get('cash_d2')), _f(b.get('total_eval')), _f(b.get('stock_eval')))
    return key(prev_bal) != key(bal)
