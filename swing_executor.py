# -*- coding: utf-8 -*-
"""
스윙 자동매매 한 바퀴 (라운드 446) — 워커가 부른다. **주문을 내는 길은 여기 하나다.**

모드
  OFF     아무것도 안 한다(심박만)
  SHADOW  계획을 남기고 일봉으로 모의 결과만 낸다 — 증권사에 아무것도 안 보낸다
  PAPER   한국투자 **모의투자** 서버로 실제 주문 흐름을 돈다(자격증명이 demo 여야 한다)
  LIVE    실계좌 주문 — 기본 잠김. 사용자가 직접 잠금을 풀고(문장 입력) · 위험 한도 여섯을 다 정하고 · 자격증명이 real 이고 ·
          긴급정지가 꺼져 있어야 한다. 하나라도 아니면 신규 매수를 안 낸다

'오늘'이 둘이다 — 갈라 받는다(라운드 442 가 이 모양에서 같은 추천을 두 번 셌다).
  anchor_day  리포트 판정일 = 마지막으로 장이 끝난 거래일(장중이면 전 거래일) — 계획이 '오늘 것'인지 이것으로 본다
  trade_day   주문을 내는 날 = 지금의 **한국 시각** 날짜(PC 시간대와 무관 · KST 로 바꿔 본다)

■ 한 바퀴의 차례 (보호가 맨 앞이다)
  ① 계획·모의(실패해도 다음으로 · 보호 매도를 막지 않는다)
  ② 주문 내역으로 맞추기(실패하면 신규 매수만 막고 보호 매도는 계속)
  ③ 잔고(못 읽으면 아무것도 안 한다 — 무엇을 팔지 모른다)
  ④ 관리 수량을 계좌에 맞춘다(밖에서 판 것은 관리에서 내린다 · 다시 산 것을 봇이 팔지 않게)
  ⑤ 취소 다시 하기(긴급정지 · 되돌려 받은 종목 · 손절선 아래로 내려간 대기 매수) — 취소가 확인될 때까지 바퀴마다
  ⑥ 보호 매도(손절·기간 만료) — **매도 가능 수량**만큼 시장가로. 목표 매도가 주식을 잡고 있으면 먼저 취소하고 다음 바퀴에 판다
  ⑦ 신규 매수(모든 관문 · 지금 가격이 손절선 이하면 안 산다 · 대기 매수도 한도에 센다)

■ 주문을 다시 보내지 않는다 (매수)
  네트워크 오류·시간초과는 `UNKNOWN`. 내역에서 찾을 때 PC 시계를 쓰지 않는다 — 보내기 직전 이미 있던 같은 종목·방향의
  주문번호를 빼고 남는 **하나**만 짝으로 본다. 그날 안에는 '거절'로 단정하지 않고(그 종목 매수를 막아 둔다), 거래일이 지나도
  내역에 없을 때만 만료로 본다. 매도는 증권사가 매도 가능 수량을 넘는 주문을 거절하므로 수량을 그 자리에서 다시 잰다.

■ 당일 주문은 **다음 날** 만료로 적는다 — 마감 직후 늦게 알려지는 체결(동시호가)을 버리지 않게.
"""
import datetime as _dt
import hashlib

import broker_kis
import swing_engine
import swing_ledger as L
import swing_risk

#: 실전 잠금을 풀 때 사용자가 그대로 입력해야 하는 문장(손가락이 미끄러져 켜지지 않게)
LIVE_UNLOCK_PHRASE = '실계좌 자동주문을 켭니다'
MODE_ENV = {'PAPER': 'demo', 'LIVE': 'real'}
OPEN_STATES = ('SUBMITTING', 'UNKNOWN', 'BROKER_ACK', 'PARTIAL', 'CANCEL_REQUESTED')
PROTECTIVE = ('stop', 'expiry')
#: 보호 매도가 같은 날 **거절**된 횟수의 상한 — 넘으면 사람에게 알린다. 운영 값이지 판정 문턱이 아니다
PROTECT_REJECT_CAP = 3
#: 한국 표준시 — 한국은 일광절약시간이 없다(제도 사실)
KST = _dt.timezone(_dt.timedelta(hours=9))


def now_kst():
    return _dt.datetime.now(KST)


def kst(now):
    """시각을 한국 시각으로 — 시간대가 없는 시각은 이 PC 의 지역 시각으로 보고 바꾼다."""
    if now.tzinfo is None:
        now = now.astimezone()
    return now.astimezone(KST)


def is_trading_day(day):
    from improvement.case_tracker import is_non_trading_date
    return not is_non_trading_date(str(day)[:10])


def _session_times():
    from bitemporal_engine import MARKET_CLOSE, MARKET_OPEN
    return MARKET_OPEN, MARKET_CLOSE


def session_open(now):
    """KRX 정규장 안인가 — 시각은 엔진의 상수 한 곳(09:00·15:30)을 부르고 **한국 시각**으로 견준다.
    ⚠️ 거래소가 시간을 바꾸는 날(수능일 등)의 달력은 없다 — 그날 15:30 뒤에는 보호 매도도 쉰다(문서에 적었다)."""
    n = kst(now)
    op, cl = _session_times()
    return is_trading_day(n.date().isoformat()) and op <= n.time() < cl


def trading_days_between(start_day, end_day):
    """start_day 다음 날부터 end_day 까지의 거래일 수(둘 다 ISO)."""
    d0 = _dt.date.fromisoformat(str(start_day)[:10])
    d1 = _dt.date.fromisoformat(str(end_day)[:10])
    n, d = 0, d0
    while d < d1:
        d += _dt.timedelta(days=1)
        if is_trading_day(d.isoformat()):
            n += 1
    return n


def _iid(*parts):
    return 'IN-' + hashlib.sha1('|'.join(str(p) for p in parts).encode('utf-8')).hexdigest()[:12].upper()


def _base(reason):
    return str(reason or '').split('#')[0]


def _odno(v):
    """주문번호 비교용 — 앞자리 0 같은 표기 차이로 들어간 주문을 '없다'로 읽지 않는다(2026-10-08 독립 검토)."""
    s = str(v or '').strip()
    return s.lstrip('0') or s


def _is_child(o):
    """취소·정정 주문의 행인가 — 원 주문번호(orgn_odno)를 가리킨다. 이런 행은 새 주문의 짝이 아니다."""
    return str(o.get('orig_odno') or '').strip().strip('0') != ''


# ── 관문 ────────────────────────────────────────────────────────────────
def broker_gate(mode, cfg, st):
    """이 모드로 증권사에 주문을 보낼 수 있나 → 막는 사유 목록(빈 목록 = 됨)."""
    out = []
    if mode not in MODE_ENV:
        return [f'{mode} 모드는 증권사에 주문을 보내지 않습니다']
    if not cfg or cfg.get('missing') or cfg.get('problems'):
        out.append('한국투자 연결 정보가 없거나 잘못됐습니다 — ' + broker_kis.config_summary(cfg))
    elif cfg.get('env') != MODE_ENV[mode]:
        out.append(f"{'모의투자' if mode == 'PAPER' else '실전'} 모드인데 자격증명이 "
                   f"{'모의투자' if cfg.get('env') == 'demo' else '실전'} 것입니다")
    if mode == 'LIVE' and (st or {}).get('live_unlock') != LIVE_UNLOCK_PHRASE:
        out.append('실전 잠금이 풀리지 않았습니다')
    return out


def buy_gate(mode, cfg, st):
    """신규 매수 관문(계좌·종목 단위 제외) → 막는 사유 목록."""
    out = broker_gate(mode, cfg, st)
    if (st or {}).get('kill_switch'):
        out.append('긴급정지가 켜져 있습니다')
    _v, missing, problems = swing_risk.validate((st or {}).get('limits') or {})
    if missing or problems:
        out.append('위험 한도가 정해지지 않았습니다: ' + ', '.join(missing + problems))
    return out


def live_readiness(cfg, st):
    """실전을 켤 수 있는가 — 화면이 항목마다 통과/미달을 그린다. [(이름, 통과, 설명)]."""
    _v, missing, problems = swing_risk.validate((st or {}).get('limits') or {})
    ok_cfg = bool(cfg) and not cfg.get('missing') and not cfg.get('problems') and cfg.get('env') == 'real'
    return [
        ('한국투자 실전 자격증명', ok_cfg, broker_kis.config_summary(cfg)),
        ('위험 한도 여섯', not (missing or problems), ', '.join(missing + problems) or '정함'),
        ('실전 잠금 해제', (st or {}).get('live_unlock') == LIVE_UNLOCK_PHRASE, '문장을 그대로 입력해야 풀립니다'),
        ('긴급정지 꺼짐', not (st or {}).get('kill_switch'), '켜져 있으면 신규 매수를 안 냅니다'),
    ]


# ── 주문 보내기 (다시 보내지 않는다) ────────────────────────────────────
def submit(c, broker, intent_id, side, code, qty, price, ord_dvsn):
    """RISK_APPROVED 인 의도를 보낸다 → 그 직후 상태. 거절=REJECTED · 오류/시간초과=UNKNOWN(다시 안 보낸다)."""
    L.order_event(c, intent_id, 'SUBMITTING')
    try:
        r = broker.place_order(side, code, qty, price, ord_dvsn)
    except broker_kis.TransportError as e:
        L.order_event(c, intent_id, 'UNKNOWN', detail=f'보낸 뒤 응답 없음 — {e} · 다시 보내지 않고 내역으로 맞춘다')
        return 'UNKNOWN'
    except broker_kis.BrokerError as e:
        L.order_event(c, intent_id, 'REJECTED', detail=str(e))
        return 'REJECTED'
    L.order_event(c, intent_id, 'BROKER_ACK', odno=r.get('odno'), orgno=r.get('orgno'), filled_qty=0,
                  detail=f"주문번호 {r.get('odno')} · {r.get('time')}")
    return 'BROKER_ACK'


def _pre_odnos_for(orders, code, side, day):
    """보내기 직전 내역에 이미 있던 같은 종목·방향·날짜의 주문번호들 — 내역을 못 읽었으면 None."""
    if orders is None:
        return None
    d = str(day).replace('-', '')
    return [_odno(o['odno']) for o in orders if o['code'] == code and o['side'] == side and o['date'] == d]


def _match(it, orders, claimed, pre):
    """의도 ↔ 증권사 주문. 주문번호가 있으면 그것으로. 없으면 (종목·방향·수량·가격·거래일)이 같고, 보내기 직전에 이미 있던
    주문이 아니고, 다른 의도가 차지하지 않은 원 주문 행이 **하나일 때만**. PC 시계는 안 쓴다."""
    if it.get('odno'):
        for o in orders:
            if _odno(o['odno']) == _odno(it['odno']):
                return o
        return None
    day = str(it['trade_day']).replace('-', '')
    pre = pre or set()
    cands = [o for o in orders if not _is_child(o) and _odno(o['odno']) not in claimed and _odno(o['odno']) not in pre
             and o['code'] == it['code'] and o['side'] == it['side'] and o['ord_qty'] == int(it['qty']) and o['date'] == day
             and (it['ord_dvsn'] != broker_kis.ORD_LIMIT or abs((o['ord_price'] or 0) - float(it['price'] or 0)) < 0.5)]
    return cands[0] if len(cands) == 1 else None


def reconcile(c, broker, now, note):
    """열린 의도를 한국투자 주문·체결 내역에 맞춘다 → 오늘 내역(주문 직전 번호 기록에 쓴다).

    의도 하나의 체결 반영(포지션 사건)과 상태 기록은 **한 묶음**으로 커밋한다 — 중간에 멈추면 둘 다 안 남아 다음 바퀴가 처음부터
    다시 맞춘다(두 번 세지 않는다). 지난 거래일의 주문만 만료로 적는다(마감 직후 늦게 알려지는 체결을 버리지 않게)."""
    today = kst(now).date().isoformat()
    live = L.intents_with_state(c, OPEN_STATES)
    days = sorted({str(it['trade_day']) for it in live} | {today})
    orders = broker.get_daily_orders(days[0].replace('-', ''), today.replace('-', ''))
    if not live:
        return orders
    claimed = {_odno(it['odno']) for it in L.intents_with_state(c) if it.get('odno')}
    cancelled_origs = {_odno(o['orig_odno']) for o in orders
                       if _is_child(o) and (o.get('cancelled') or int(o.get('cancel_qty') or 0) > 0)}
    for it in live:
        past = str(it['trade_day']) < today
        o = _match(it, orders, claimed, L.pre_odnos(c, it['intent_id']))
        try:
            if o is None:
                if past:
                    L.order_event(c, it['intent_id'], 'EXPIRED',
                                  detail='지난 거래일 주문 — 내역에서 못 찾아 만료로 본다(체결이 있었다면 계좌 맞추기가 잡는다)')
                elif it['state'] == 'SUBMITTING':
                    L.order_event(c, it['intent_id'], 'UNKNOWN',
                                  detail='내역에 아직 없음 — 그날은 다시 보내지 않고 이 종목 매수를 막아 둔다')
                continue
            claimed.add(_odno(o['odno']))
            prev = int(it.get('filled_qty') or 0)
            filled = int(o['filled_qty'] or 0)
            if filled >= int(it['qty']):
                st = 'FILLED'
            elif o.get('cancelled') or int(o.get('cancel_qty') or 0) > 0 or _odno(o['odno']) in cancelled_origs:
                st = 'CANCELLED'
            elif past:
                st = 'EXPIRED'
            elif filled > 0:
                st = 'PARTIAL'
            else:
                st = 'CANCEL_REQUESTED' if it['state'] == 'CANCEL_REQUESTED' else 'BROKER_ACK'
            if st == it['state'] and filled == prev and it.get('odno'):
                continue
            with c:                                            # 체결 반영 + 상태 기록 = 한 묶음
                if filled > prev:
                    _apply_fill(c, it, filled - prev, o.get('avg_fill'), prev == 0)
                L.order_event(c, it['intent_id'], st, odno=o['odno'], orgno=(it.get('orgno') or o['orgno']),
                              filled_qty=filled, avg_fill=o.get('avg_fill'), detail='내역으로 맞춤', commit=False)
        except Exception as e:                                 # noqa: BLE001 — 장부 거부·잠김 등. 그 묶음은 통째로 안 남고 다음 바퀴가 다시 맞춘다
            note(f"{it['code']} 맞추기 기록 실패 — {type(e).__name__}: {e} · 다음 바퀴에 다시")
    return orders


def _apply_fill(c, it, delta, avg, first):
    """체결 차이 → 포지션 사건(커밋은 부르는 쪽이 묶음으로). 매수 첫 체결이면 관리 시작(계획의 목표·손절을 같이 박는다)."""
    p = L.plan(c, it['plan_id']) or {}
    if it['side'] == 'buy':
        if first and _base(it.get('reason')) == 'entry':
            L.position_event(c, it['code'], 'SWING_OPENED', 'OPENED', plan_id=it['plan_id'], qty=delta, price=avg,
                             target=p.get('target'), stop=p.get('stop'), trade_day=it['trade_day'], commit=False)
        else:
            L.position_event(c, it['code'], 'SWING_OPENED', 'FILL_ADD', plan_id=it['plan_id'], qty=delta, price=avg,
                             trade_day=it['trade_day'], commit=False)
        return
    pos = L.positions(c).get(it['code']) or {}
    own = pos.get('ownership') if pos.get('ownership') in L.AUTO_SELL_OWNERSHIP else 'SWING_OPENED'
    L.position_event(c, it['code'], own, 'SOLD', plan_id=it['plan_id'], qty=delta, price=avg, trade_day=it['trade_day'],
                     detail=_base(it.get('reason')), commit=False)
    if int((L.positions(c).get(it['code']) or {}).get('qty') or 0) <= 0:
        L.position_event(c, it['code'], own, 'CLOSED', plan_id=it['plan_id'], trade_day=it['trade_day'],
                         detail=_base(it.get('reason')), commit=False)


def sync_positions(c, held, trade_day, note):
    """관리 수량을 계좌에 맞춘다 — 계좌가 장부보다 적고 그 종목에 열린 매도 주문이 없으면 **밖에서 판 것**이다. 그 수량을 내리고,
    계좌에 없으면 관리를 끝낸다(사용자가 나중에 다시 산 주식을 봇이 팔지 않게 · 2026-10-08 독립 검토). 관리 밖 보유는 '기존 보유'로."""
    open_sell = {it['code'] for it in L.intents_with_state(c, OPEN_STATES) if it['side'] == 'sell'}
    pos = L.positions(c)
    for code, p in pos.items():
        if not p.get('managed'):
            continue
        aq = int((held.get(code) or {}).get('qty') or 0)
        lq = int(p.get('qty') or 0)
        if aq < lq and code not in open_sell:
            with c:
                L.position_event(c, code, p['ownership'], 'SOLD', plan_id=p.get('plan_id'), qty=lq - aq, trade_day=trade_day,
                                 detail='계좌와 맞춤 — 밖에서 줄어든 수량', commit=False)
                if aq == 0:
                    L.position_event(c, code, p['ownership'], 'CLOSED', plan_id=p.get('plan_id'), trade_day=trade_day,
                                     detail='계좌에 없음 — 밖에서 판 것으로 보고 관리를 끝낸다', commit=False)
            note(f'{code} 관리 수량을 계좌에 맞췄다 {lq} → {aq}' + (' · 관리 끝' if aq == 0 else ''))
    pos = L.positions(c)
    for code, h in held.items():
        k = pos.get(code)
        if k is None or (not k.get('managed') and int(k.get('qty') or 0) != h['qty']):
            L.position_event(c, code, 'READ_ONLY_EXISTING', 'SEEN', qty=h['qty'], price=h.get('avg_price'),
                             trade_day=trade_day, detail='계좌에서 봄 — 자동 매도 안 함')


def _cancel(c, broker, it, why, out):
    """취소 요청 — 아직 취소가 확인되지 않았으면 **바퀴마다 다시** 보낸다(한 번 실패로 멈추지 않는다). 보냈으면 True."""
    if not it.get('odno'):
        return False
    try:
        if it['state'] != 'CANCEL_REQUESTED':
            L.order_event(c, it['intent_id'], 'CANCEL_REQUESTED', detail=why)
        broker.cancel_order(it['orgno'], it['odno'])
        return True
    except (broker_kis.BrokerError, L.LedgerError) as e:
        out['notes'].append(f"{it['code']} 주문 취소 실패 — {e} · 다음 바퀴에 다시 한다")
        return False


# ── 계획과 기록만 모의 (증권사 안 부름) ─────────────────────────────────
def refresh_plans(c, report, anchor_day, bars_fn, cost_pct):
    """그날 리포트 → 계획(바뀌지 않는 영수증) · 끝나지 않은 계획마다 일봉으로 모의 → (새 계획 수, 모의 갱신 수, 메모)."""
    pn, sn, notes = 0, 0, []
    for p in swing_engine.plans_from_report(report, anchor_day):
        pn += int(L.add_plan(c, p))
    if bars_fn is None:
        return pn, sn, notes
    latest = L.shadow_latest(c)
    for p in L.plans(c):
        prev = latest.get(p['plan_id']) or {}
        if prev.get('status') in ('closed', 'no_fill', 'invalid'):
            continue
        try:
            res = swing_engine.shadow_grade(p, bars_fn(p['code']), cost_pct)
        except Exception as e:                                 # noqa: BLE001
            notes.append(f"{p['code']} 모의 실패 — {type(e).__name__}")
            continue
        if res.get('status') != prev.get('status') or res.get('exit_status') != prev.get('exit_status'):
            L.shadow_outcome(c, p['plan_id'], res)
            sn += 1
    return pn, sn, notes


# ── 한 바퀴 ─────────────────────────────────────────────────────────────
def run_cycle(c, *, broker=None, cfg=None, report=None, anchor_day=None, now=None, bars_fn=None, cost_pct=None,
              do_shadow=True, allow_orders=True, quote_fn=None):
    """워커 한 바퀴 → 요약 dict. allow_orders=False 면 계획·모의·내역·계좌 맞춤까지만 하고 주문(취소 포함)은 안 낸다
    (저녁 작업 · '놓치면 켜질 때' 돌아 장중일 수 있다). quote_fn(code) → 지금 가격 또는 None — 신규 매수 직전에 손절선과 견준다."""
    now = kst(now or now_kst())
    trade_day = now.date().isoformat()
    st = L.settings(c)
    mode = st.get('mode') if st.get('mode') in L.MODES else 'OFF'
    out = dict(mode=mode, anchor_day=anchor_day, trade_day=trade_day, plans_new=0, shadow_updates=0, orders=[],
               exits=[], blocked=[], notes=[], alerts=[])
    if mode == 'OFF':
        L.heartbeat(c, mode, 'off', '꺼짐 — 아무것도 안 했다')
        return out
    # ① 계획·모의 — 실패해도 보호 매도를 막지 않는다
    try:
        pn, sn, notes = refresh_plans(c, report, anchor_day, bars_fn if do_shadow else None, cost_pct)
        out.update(plans_new=pn, shadow_updates=sn)
        out['notes'] += notes
    except Exception as e:                                     # noqa: BLE001
        out['alerts'].append(f'계획을 못 만들었다 — {type(e).__name__}: {e} (보호 매도는 계속)')
    if mode == 'SHADOW':
        _beat(c, mode, out, f"계획 +{out['plans_new']} · 모의 갱신 {out['shadow_updates']} · 주문 안 함")
        return out
    bg = broker_gate(mode, cfg, st)
    if bg or broker is None:
        out['blocked'] += bg or ['증권사 연결이 없습니다']
        L.heartbeat(c, mode, 'blocked', ' · '.join(out['blocked']))
        return out
    # ② 내역 맞추기 — 실패하면 신규 매수만 막는다
    orders = None
    try:
        orders = reconcile(c, broker, now, out['notes'].append)
    except broker_kis.BrokerError as e:
        out['alerts'].append(f'주문 내역을 못 읽었다 — {e} · 신규 매수는 막고 보호 매도는 계속')
    # ③ 잔고 — 못 읽으면 무엇을 팔지 모른다
    try:
        bal = broker.get_balance()
    except broker_kis.BrokerError as e:
        out['alerts'].append(f'계좌를 못 읽었다 — {e}')
        L.heartbeat(c, mode, 'broker_fail', ' · '.join(out['alerts']))
        return out
    L.account_snapshot(c, broker.env, bal)
    held = {p['code']: p for p in bal['positions']}
    # ④ 관리 수량을 계좌에 맞춤
    try:
        sync_positions(c, held, trade_day, out['notes'].append)
    except Exception as e:                                     # noqa: BLE001
        out['alerts'].append(f'계좌 맞추기 실패 — {type(e).__name__}: {e}')
    if not allow_orders:
        _beat(c, mode, out, '주문 없이 돌았다(저녁 작업) · 내역·계좌만 맞춤')
        return out
    if not session_open(now):
        _beat(c, mode, out, '장 시간이 아니라 주문하지 않았다 · 내역·계좌만 맞춤')
        return out
    # ⑤ 취소 다시 하기
    _cancels(c, broker, st, quote_fn, out)
    # ⑥ 보호 매도 — 긴급정지와 무관
    _exits(c, broker, held, trade_day, mode, out)
    # ⑦ 신규 매수 — 내역을 맞췄을 때만
    if orders is None:
        out['blocked'].append('주문 내역을 못 맞춰 신규 매수를 안 냈다')
    else:
        _entries(c, broker, cfg, st, bal, held, trade_day, mode, cost_pct, out, orders, quote_fn)
    _beat(c, mode, out, f"주문 {len(out['orders'])} · 청산 {len(out['exits'])} · 막힘 {len(out['blocked'])}")
    return out


def _beat(c, mode, out, summary):
    """심박 — 보호에 문제가 있으면 'warn' 과 그 사유를 같이 남긴다(화면이 그린다 · 조용히 'ok' 로 덮지 않는다)."""
    if out['alerts']:
        L.heartbeat(c, mode, 'warn', ' · '.join(out['alerts'] + [summary]))
    else:
        L.heartbeat(c, mode, 'ok', summary)


def _cancels(c, broker, st, quote_fn, out):
    """취소가 확인될 때까지 바퀴마다 — ⓐ 긴급정지면 열린 매수 ⓑ 관리 밖 종목의 열린 매도(되돌려 받은 종목) ⓒ 지금 가격이 손절선
    이하로 내려간 대기 매수(그 가격에 사면 바로 손절이다)."""
    managed = set(L.managed_open(c))
    for it in L.intents_with_state(c, ('BROKER_ACK', 'PARTIAL', 'CANCEL_REQUESTED')):
        if not it.get('odno'):
            continue
        why = None
        if it['side'] == 'buy' and st.get('kill_switch'):
            why = '긴급정지 — 열린 매수 취소'
        elif it['side'] == 'sell' and it['code'] not in managed:
            why = '관리에서 빠진 종목 — 열린 매도 취소'
        elif it['side'] == 'buy' and quote_fn is not None:
            stop = (L.plan(c, it['plan_id']) or {}).get('stop')
            try:
                q = quote_fn(it['code'])
            except Exception:                                  # noqa: BLE001
                q = None
            if q is not None and stop is not None and q <= stop:
                why = f'지금 가격 {q:,.0f} 이 손절선 {stop:,.0f} 이하 — 대기 매수 취소'
        if it['state'] == 'CANCEL_REQUESTED' and why is None:
            why = '취소 다시 요청(아직 확인 안 됨)'
        if why:
            _cancel(c, broker, it, why, out)


def _exits(c, broker, held, trade_day, mode, out):
    every = L.intents_with_state(c)
    for code, pos in L.managed_open(c).items():
        try:
            _exit_one(c, broker, held, trade_day, mode, out, code, pos, every)
        except Exception as e:                                 # noqa: BLE001 — 한 종목의 실패가 다른 종목의 손절을 막지 않는다
            out['alerts'].append(f'{code} 보호 매도 처리 실패 — {type(e).__name__}: {e}')


def _exit_one(c, broker, held, trade_day, mode, out, code, pos, every):
    acct = held.get(code)
    if not acct:
        return                  # 계좌 맞추기가 처리한다
    px = acct.get('price')
    held_qty = min(int(pos.get('qty') or 0), int(acct.get('qty') or 0))
    sellable = int(acct.get('sellable_qty') if acct.get('sellable_qty') is not None else acct.get('qty') or 0)
    if held_qty <= 0 or px is None:
        return
    plan = L.plan(c, pos.get('plan_id')) or {}
    horizon = plan.get('horizon')
    held_days = trading_days_between(pos['opened_day'], trade_day) if pos.get('opened_day') else 0
    why = None
    if pos.get('stop') is not None and px <= pos['stop']:
        why = 'stop'
    elif pos.get('ownership') == 'SWING_OPENED' and horizon and held_days >= int(horizon):
        why = 'expiry'
    open_sells = [it for it in every if it['code'] == code and it['side'] == 'sell' and it['state'] in OPEN_STATES]
    pid = pos.get('plan_id') or f'ADOPT-{code}'
    if why:
        # 목표 매도가 주식을 잡고 있으면 취소를 (다시) 요청한다 — 확인될 때까지 바퀴마다
        sent = [_cancel(c, broker, it, f'{why} — 목표 매도 취소', out)
                for it in open_sells if _base(it.get('reason')) not in PROTECTIVE and it.get('odno')]
        qty_now = min(held_qty, sellable)      # 매도 가능 수량 — 잡혀 있거나 이미 내 보호 매도가 걸린 몫은 빠진다
        if qty_now <= 0 and any(sent):
            # 취소를 방금 보냈다 — 이 바퀴의 잔고는 취소 전 값이다. 한 번 더 읽어 풀렸으면 같은 바퀴에 판다(손절은 빨라야 한다)
            try:
                a2 = next((p for p in broker.get_balance()['positions'] if p['code'] == code), None)
                if a2:
                    s2 = a2.get('sellable_qty') if a2.get('sellable_qty') is not None else a2.get('qty')
                    qty_now = min(held_qty, int(a2.get('qty') or 0), int(s2 or 0))
            except broker_kis.BrokerError as e:
                out['notes'].append(f'{code} 취소 뒤 잔고 다시 읽기 실패 — {e} · 다음 바퀴에 판다')
        if qty_now <= 0:
            out['notes'].append(f'{code} {why} — 팔 수 있는 수량이 아직 0(목표 매도 취소·앞선 매도 체결을 기다린다)')
            return
        today_prot = [it for it in every if it['code'] == code and it['side'] == 'sell' and it['trade_day'] == trade_day
                      and _base(it.get('reason')) in PROTECTIVE]
        if sum(1 for it in today_prot if it['state'] == 'REJECTED') >= PROTECT_REJECT_CAP:
            out['alerts'].append(f'{code} {why} 매도가 오늘 {PROTECT_REJECT_CAP}번 거절됐다 — 사람이 확인해야 한다')
            return
        n = len(today_prot) + 1
        reason = why if n == 1 else f'{why}#{n}'
        iid = _iid(pid, code, 'sell', trade_day, reason)
        L.add_intent(c, dict(intent_id=iid, plan_id=pid, side='sell', code=code, qty=qty_now, price=None,
                             ord_dvsn=broker_kis.ORD_MARKET, mode=mode, trade_day=trade_day, reason=reason))
        L.order_event(c, iid, 'RISK_APPROVED', detail=f'{why} · 현재가 {px:,.0f}')
        out['exits'].append((code, why, submit(c, broker, iid, 'sell', code, qty_now, None, broker_kis.ORD_MARKET)))
        return
    qty = min(held_qty, sellable)
    if qty > 0 and pos.get('target') and not any(_base(it.get('reason')) == 'target' for it in open_sells):
        iid = _iid(pid, code, 'sell', trade_day, 'target')
        try:
            L.add_intent(c, dict(intent_id=iid, plan_id=pid, side='sell', code=code, qty=qty, price=pos['target'],
                                 ord_dvsn=broker_kis.ORD_LIMIT, mode=mode, trade_day=trade_day, reason='target'))
        except L.LedgerError:
            return              # 오늘 목표 매도는 이미 냈다(체결·거절·만료 포함)
        L.order_event(c, iid, 'RISK_APPROVED', detail='1차 목표 지정가 매도(오늘 하루)')
        out['exits'].append((code, 'target', submit(c, broker, iid, 'sell', code, qty, pos['target'], broker_kis.ORD_LIMIT)))


def _entries(c, broker, cfg, st, bal, held, trade_day, mode, cost_pct, out, orders, quote_fn):
    gate = buy_gate(mode, cfg, st)
    if gate:
        out['blocked'] += gate
        return
    limits = st.get('limits') or {}
    every = L.intents_with_state(c)
    today_new = sum(1 for it in every if it['side'] == 'buy' and it['trade_day'] == trade_day)
    pending = [it for it in every if it['side'] == 'buy' and it['state'] in OPEN_STATES]
    busy = {it['code'] for it in every if it['state'] in OPEN_STATES}
    # 대기 매수도 한도에 센다 — 동시 보유 수와 주식 비중(남은 수량 × 지정가)
    open_count = len(L.managed_open(c)) + len({it['code'] for it in pending} - set(L.managed_open(c)))
    pending_amt = sum((int(it['qty']) - int(it.get('filled_qty') or 0)) * float(it['price'] or 0) for it in pending)
    pos_now = L.positions(c)
    for p in L.plans(c):
        if not p.get('live_ok'):
            continue
        waited = trading_days_between(p['data_day'], trade_day)
        if waited < 1 or waited > int(p.get('wait_bars') or 0):
            continue     # 판정일 다음 거래일부터 · 대기 기간이 지나면 안 산다(추격 없음)
        code = p['code']
        if code in held or code in busy or (pos_now.get(code) or {}).get('managed'):
            continue     # 이미 갖고 있거나 주문 중(확인 중인 주문 포함) — 겹쳐 사지 않는다
        if any(it['plan_id'] == p['plan_id'] and it['side'] == 'buy' and int(it.get('filled_qty') or 0) > 0 for it in every):
            continue     # 이 계획은 이미 (일부라도) 샀다
        cg = swing_risk.count_gates(limits, open_count, today_new)
        if cg:
            out['blocked'] += cg
            break
        if quote_fn is None:
            out['blocked'].append(f'{code} — 지금 가격을 읽는 길이 없어 사지 않는다')
            continue
        try:
            q = quote_fn(code)
        except Exception:                                      # noqa: BLE001
            q = None
        if q is None:
            out['blocked'].append(f'{code} — 지금 가격을 못 읽어 사지 않는다')
            continue
        if q <= p['stop']:
            out['blocked'].append(f"{code} — 지금 가격 {q:,.0f} 이 손절선 {p['stop']:,.0f} 이하라 사지 않는다")
            continue
        try:
            orderable = broker.get_orderable(code, p['entry'])
        except broker_kis.BrokerError as e:
            out['blocked'].append(f'{code} 매수 가능 금액을 못 읽었다 — {e}')
            continue
        if orderable.get('amt') is None:
            out['blocked'].append(f'{code} — 매수 가능 금액 칸이 비어 사지 않는다')
            continue
        acct = dict(bal, stock_eval=(float(bal.get('stock_eval') or 0) + pending_amt) if bal.get('stock_eval') is not None else None)
        sz = swing_risk.size(p['entry'], p['stop'], acct, limits, cost_pct, orderable.get('amt'))
        if sz['qty'] < 1:
            out['blocked'].append(f"{code} — {sz['reason']}")
            continue
        iid = _iid(p['plan_id'], 'buy', trade_day, 'entry')
        try:
            L.add_intent(c, dict(intent_id=iid, plan_id=p['plan_id'], side='buy', code=code, qty=sz['qty'],
                                 price=p['entry'], ord_dvsn=broker_kis.ORD_LIMIT, mode=mode, trade_day=trade_day,
                                 reason='entry', planned_loss=sz['planned_loss']),
                         pre_odnos=_pre_odnos_for(orders, code, 'buy', trade_day))
        except L.LedgerError:
            continue     # 오늘 이 계획의 매수는 이미 냈다
        L.order_event(c, iid, 'RISK_APPROVED', detail=f"수량 {sz['qty']} · 정한 제한 {sz['binding']} · "
                                                        f"손절 시 손실 약 {sz['planned_loss']:,.0f}원(손절가 체결 가정)")
        out['orders'].append((code, sz['qty'], submit(c, broker, iid, 'buy', code, sz['qty'], p['entry'],
                                                      broker_kis.ORD_LIMIT)))
        today_new += 1
        open_count += 1
        pending_amt += sz['qty'] * float(p['entry'])
        busy.add(code)


def adopt(c, code, qty, target, stop, by_user=False):
    """사용자가 기존 보유를 자동 관리로 넘긴다 — 화면의 명시 행동에서만(by_user=True). 목표·손절은 그때의 값으로 박는다.
    넘긴 종목은 기간 만료로 팔지 않는다(산 날짜·계획을 모른다) — 손절선·1차 매도가에 닿을 때만."""
    if not by_user:
        raise L.LedgerError('자동관리로 넘기기는 사용자만 할 수 있습니다')
    if stop is None or target is None or not (float(stop) < float(target)) or int(qty or 0) <= 0:
        raise L.LedgerError('수량·손절선·1차 매도가가 없거나 정합이 깨져 넘길 수 없습니다')
    L.position_event(c, code, 'USER_ADOPTED', 'ADOPTED', plan_id=f'ADOPT-{code}', qty=int(qty), target=float(target),
                     stop=float(stop), trade_day=now_kst().date().isoformat(), detail='사용자가 넘김')


def release(c, code):
    """자동 관리에서 되돌려 받는다. 열린 매도 주문은 워커의 다음 장중 바퀴가 취소한다(관리 밖 종목의 매도는 취소가 확인될 때까지
    바퀴마다 다시 요청한다) — 그 사이 체결될 수 있다는 것을 화면이 같이 적는다."""
    pos = L.positions(c).get(code) or {}
    L.position_event(c, code, pos.get('ownership') or 'USER_ADOPTED', 'RELEASED', plan_id=pos.get('plan_id'),
                     trade_day=now_kst().date().isoformat(), detail='사용자가 되돌려 받음')
