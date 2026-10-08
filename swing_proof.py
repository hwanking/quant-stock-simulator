# -*- coding: utf-8 -*-
"""
스윙 자동매매 결과 영수증 (라운드 447) — 계획 vs 실제 체결을 **같은 장부에서 읽어** 적는다. 새 값을 만들지 않는다.

가늠 PROOF(라운드 418)의 마지막 고리다: 가늠이 판단하고(개장 전 리포트의 중앙 판정 = 계획) · 한국투자가 실행하고(체결) ·
결과를 같은 규칙으로 남긴다. 영수증 한 장 = 자동매매가 열고 닫은 포지션 한 번(OPENED/ADOPTED → … → CLOSED).

적는 것(전부 장부의 사건에서 셈 · 문턱 없음 · 판정 낱말 없음):
  계획 진입가 vs 실제 평균 체결가(진입 슬리피지) · 청산 사유(목표·손절·기간 만료·밖에서 팔림) · 계획 청산가 vs 실제 평균 청산가
  (청산 슬리피지) · 총수익률 · 운영 왕복 비용(`verdict_core.COST_PCT`)을 뺀 순수익률 · 보유 거래일 · 같은 계획을 일봉으로 굴린
  모의 결과(기록만 모드와 같은 채점기)와의 차이.

하지 않는 것:
  · 실제 수수료·세금을 증권사에서 읽지 않는다 — 비용은 운영 상수 하나로 뺀다(연구·PROOF 와 같은 비용 · 다르면 그렇다고 적는다).
  · 산출물을 `data/` 에 싣지 않는다 — 어느 종목을 몇 주 샀는지는 개인 자료다(§9). 이 PC 의 화면에서만 본다.
  · 좋고 나쁨을 말하지 않는다 — 평균과 중앙을 같이 적고(R149) 부호가 갈리면 갈린다고만.
"""
import hashlib
import statistics

import swing_ledger as L

EXIT_KO = {'target': '1차 목표', 'stop': '손절', 'expiry': '기간 만료', 'manual': '밖에서 팔림', 'released': '되돌려 받음'}


def _f(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _wavg(pairs):
    """[(수량, 가격)] 의 가중 평균 · 가격이 하나라도 없으면 None(지어내지 않는다)."""
    pairs = [(int(q), _f(p)) for q, p in pairs if q]
    if not pairs or any(p is None for _, p in pairs):
        return None
    tot = sum(q for q, _ in pairs)
    return sum(q * p for q, p in pairs) / tot if tot else None


def _reason(detail):
    d = str(detail or '')
    for k in ('target', 'stop', 'expiry'):
        if d.startswith(k):
            return k
    if '밖에서' in d or '계좌' in d:
        return 'manual'
    return d or None


def episodes(c):
    """포지션 사건을 **한 번의 보유**(열림 → 닫힘) 단위로 가른다 → [dict]. 열려 있는 것도 담는다(closed=False)."""
    out, cur = [], {}
    for r in c.execute('SELECT * FROM position_events ORDER BY id'):
        d = dict(r)
        code, ev = d['code'], d['event']
        if ev in ('OPENED', 'ADOPTED'):
            cur[code] = dict(code=code, ownership=d['ownership'], plan_id=d.get('plan_id'), opened_day=d.get('trade_day'),
                             buys=[(d.get('qty') or 0, d.get('price'))], sells=[], target=d.get('target'), stop=d.get('stop'),
                             closed=False)
        elif code not in cur:
            continue
        elif ev == 'FILL_ADD':
            cur[code]['buys'].append((d.get('qty') or 0, d.get('price')))
        elif ev == 'SOLD':
            cur[code]['sells'].append((d.get('qty') or 0, d.get('price'), _reason(d.get('detail'))))
        elif ev in ('CLOSED', 'RELEASED'):
            e = cur.pop(code)
            e.update(closed=(ev == 'CLOSED'), end_day=d.get('trade_day'), end_event=ev)
            out.append(e)
    out.extend(cur.values())
    return out


def receipt(c, ep, cost_pct):
    """한 보유의 결과 영수증 — 못 셈한 칸은 None 으로 두고 사유를 적는다(§3)."""
    plan = L.plan(c, ep.get('plan_id')) or {}
    qty = sum(int(q) for q, _ in ep['buys'])
    entry_fill = _wavg(ep['buys'])
    entry_plan = _f(plan.get('entry'))
    sold_q = sum(int(q) for q, _, _ in ep['sells'])
    exit_fill = _wavg([(q, p) for q, p, _ in ep['sells']]) if ep['sells'] else None
    reasons = [r for _, _, r in ep['sells'] if r]
    reason = ('released' if ep.get('end_event') == 'RELEASED' else
              (max(set(reasons), key=reasons.count) if reasons else None))
    exit_plan = {'target': _f(plan.get('target') or ep.get('target')),
                 'stop': _f(plan.get('stop') or ep.get('stop'))}.get(reason)
    gross = (exit_fill / entry_fill - 1.0) * 100.0 if (entry_fill and exit_fill) else None
    net = (gross - float(cost_pct)) if (gross is not None and cost_pct is not None) else None
    sh = (L.shadow_latest(c).get(ep.get('plan_id')) or {}) if ep.get('plan_id') else {}
    days = None
    if ep.get('opened_day') and ep.get('end_day'):
        try:
            import swing_executor as X
            days = X.trading_days_between(ep['opened_day'], ep['end_day'])
        except Exception:                                      # noqa: BLE001
            days = None
    body = f"{ep.get('plan_id')}|{ep['code']}|{ep.get('opened_day')}|{ep.get('end_day')}|{entry_fill}|{exit_fill}|{qty}"
    rid = f"SWR-{str(ep.get('end_day') or ep.get('opened_day') or '').replace('-', '')}-{ep['code']}-" \
          f"{hashlib.sha1(body.encode('utf-8')).hexdigest()[:6].upper()}"
    notes = []
    if entry_fill is None:
        notes.append('체결가를 못 받아 진입가를 모른다')
    if ep.get('closed') and exit_fill is None:
        notes.append('청산가를 모른다(밖에서 팔렸거나 체결가를 못 받았다)')
    if ep.get('closed') and sold_q != qty:
        notes.append(f'판 수량 {sold_q} ≠ 산 수량 {qty}')
    return dict(receipt_id=rid, code=ep['code'], plan_id=ep.get('plan_id'), ownership=ep['ownership'],
                opened_day=ep.get('opened_day'), closed_day=ep.get('end_day') if ep.get('closed') else None,
                open=not ep.get('closed') and ep.get('end_event') != 'RELEASED', qty=qty,
                entry_plan=entry_plan, entry_fill=entry_fill,
                slip_entry_pct=((entry_fill / entry_plan - 1.0) * 100.0 if (entry_fill and entry_plan) else None),
                exit_reason=reason, exit_plan=exit_plan, exit_fill=exit_fill,
                slip_exit_pct=((exit_fill / exit_plan - 1.0) * 100.0 if (exit_fill and exit_plan) else None),
                gross_pct=gross, net_pct=net, cost_pct=cost_pct, days_held=days,
                shadow_net_pct=_f(sh.get('net_pct')) if sh.get('status') == 'closed' else None,
                shadow_exit=sh.get('exit_status') if sh.get('status') == 'closed' else None,
                notes=notes)


def receipts(c, cost_pct):
    return [receipt(c, ep, cost_pct) for ep in episodes(c)]


def summary(rs):
    """닫힌 영수증의 수 — 판정 낱말 없음. 없으면 None."""
    done = [r for r in rs if r.get('closed_day') and r.get('net_pct') is not None]
    if not done:
        return None
    v = sorted(r['net_pct'] for r in done)
    by = {}
    for r in done:
        by[r.get('exit_reason') or '?'] = by.get(r.get('exit_reason') or '?', 0) + 1
    se = [r['slip_entry_pct'] for r in done if r.get('slip_entry_pct') is not None]
    sx = [r['slip_exit_pct'] for r in done if r.get('slip_exit_pct') is not None]
    pair = [(r['net_pct'], r['shadow_net_pct']) for r in done if r.get('shadow_net_pct') is not None]
    return dict(n=len(v), mean=sum(v) / len(v), median=statistics.median(v), by_reason=by,
                slip_entry_mean=(sum(se) / len(se) if se else None), slip_exit_mean=(sum(sx) / len(sx) if sx else None),
                n_shadow=len(pair), vs_shadow_mean=((sum(a - b for a, b in pair) / len(pair)) if pair else None))


def summary_line(s, cost_pct):
    if not s:
        return None
    parts = [f"닫힌 거래 {s['n']}건 — 비용 {cost_pct}% 를 뺀 평균 {s['mean']:+.2f}% · 중앙 {s['median']:+.2f}%"
             + (' — 평균과 중앙의 부호가 갈립니다' if (s['mean'] < 0 < s['median']) or (s['median'] < 0 < s['mean']) else ''),
             '청산 ' + ' · '.join(f"{EXIT_KO.get(k, k)} {n}" for k, n in sorted(s['by_reason'].items()))]
    if s.get('slip_entry_mean') is not None:
        parts.append(f"진입 체결가는 계획보다 평균 {s['slip_entry_mean']:+.2f}%")
    if s.get('slip_exit_mean') is not None:
        parts.append(f"청산 체결가는 계획 가격보다 평균 {s['slip_exit_mean']:+.2f}%")
    if s.get('n_shadow'):
        parts.append(f"같은 계획을 일봉으로 굴린 모의와 견주면 실제가 평균 {s['vs_shadow_mean']:+.2f}%p ({s['n_shadow']}건)")
    if s['n'] < 30:
        parts.append('표본이 작아 무엇을 가를 수 있는 수가 아닙니다')
    return ' · '.join(parts) + '.'
