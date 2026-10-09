# -*- coding: utf-8 -*-
"""
스윙 관제실의 **재료 셈**(라운드 455) — 장부·잔고·운영 상태를 받아 그림이 그릴 수를 만든다. 순수 함수 · Streamlit 모름 · 판정 낱말 없음.

여기 수는 전부 이미 있는 자료에서 센 것이다(§3): 자산 곡선은 계좌 스냅샷 · 자산 구성은 잔고 + 장부 소유 · 위험 한도 사용은 ⑥의 한도 ·
오늘 깔때기는 계획·승인·주문 · 실행 상태는 주문 사건 · 시스템 상태는 워커 잠금·작업 스케줄러·저녁 작업 기록. 못 세는 칸은 None.
"""
import datetime as _dt

import swing_executor as X
import swing_ledger as L

WEEK_KO = '월화수목금토일'


def next_session_start(now, skip_today=False, max_days=20):
    """now(한국 시각) 이후 가장 가까운 정규장 시작 → (날짜, 시작 시각) · 장중이면 오늘. skip_today 면 내일부터. 못 구하면 (None, None).
    거래일은 장부의 달력 한 곳(`swing_executor.is_trading_day` → 휴장일 표) · 시각은 엔진 한 곳(`session_times` · 수능일 포함)."""
    n = X.kst(now)
    for i in range(1 if skip_today else 0, max_days):
        d = n.date() + _dt.timedelta(days=i)
        if not X.is_trading_day(d.isoformat()):
            continue
        op, cl = X._session_times(d)
        if i == 0 and n.time() >= cl:
            continue
        return d, op
    return None, None


def _when(d, op):
    return f"{d.isoformat()}({WEEK_KO[d.weekday()]}) {op.strftime('%H:%M')}" if d else None


def start_status(mode, stt, cfg, task=None, worker=None, now=None):
    """자동매매 언제 시작하나 (라운드 457) — 장부 설정 · 실전 준비 넷(`live_readiness`) · 운용 모드 · 워커 예약 작업 · 거래일 달력에서
    **유도**한다. 실제 첫 매수 날짜는 말하지 않는다 — 중앙 판정이 추천을 언제 낼지는 아무도 모른다(§3). 판정 낱말 없음.
    → dict(live, headline, start, first_buy, items=[{label, ok, why}], n_ok, n_items, missing)"""
    now = now or X.now_kst()
    items = [dict(label=n, ok=bool(ok), why=str(w)) for n, ok, w in X.live_readiness(cfg, stt)]
    mko = {'OFF': '꺼짐', 'SHADOW': '기록만', 'PAPER': '모의투자', 'LIVE': '실전'}.get(mode, mode)
    items.append(dict(label='운용 모드 실전', ok=(mode == 'LIVE'),
                      why=('실전' if mode == 'LIVE' else f'지금 {mko} — 시스템 → 설정에서 실전으로 바꿉니다(위 넷이 다 통과해야 바뀝니다)')))
    task_ok = bool(task and task.get('ok') and task.get('installed'))
    items.append(dict(label='워커 예약 작업', ok=task_ok,
                      why=(f"등록됨 · 다음 실행 {task.get('next_run') or '—'}" if task_ok else
                           ((task or {}).get('reason') or '등록 안 됨 — scripts/register_swing_worker_task.ps1 을 한 번 돌립니다'))))
    missing = [i for i in items if not i['ok']]
    in_sess = X.session_open(now)
    w_run = (worker or {}).get('running') is True
    nxt = _when(*next_session_start(now))
    nxt_after = _when(*next_session_start(now, skip_today=True))
    live = not missing
    if live:
        headline = '실전 자동매매가 켜져 있습니다'
        if in_sess and w_run:
            start = '지금 — 워커가 돌고 있어 다음 바퀴(1분 안)부터 실주문 자격이 있는 계획을 냅니다'
        elif in_sess:
            start = (f'지금은 장중인데 워커가 돌고 있지 않습니다 — 직접 켜면 지금부터(python scripts/run_swing_worker.py --session --loop 60), '
                     f'아니면 다음 장 {nxt_after}')
        else:
            start = f'다음 장 {nxt} — 그 전에 워커 예약 작업이 돌고 장이 열리면 주문합니다'
    else:
        headline = f'자동매매는 아직 시작하지 않았습니다 — 남은 일 {len(missing)}개'
        if in_sess and w_run:
            start = '남은 일을 채우면 지금(워커가 돌고 있어 다음 바퀴 · 1분 안)부터'
        elif in_sess:
            start = f'남은 일을 채우면 가장 빨리 다음 장 {nxt_after}부터(오늘은 워커가 안 돌고 있습니다 · 직접 켜면 오늘부터)'
        else:
            start = f'남은 일을 채우면 가장 빨리 다음 장 {nxt}부터' if nxt else '다음 장 날짜를 구하지 못했습니다(휴장일 표 밖)'
    first = ("실제 첫 매수: 중앙 판정이 '추천'(조건 11개 전부 통과)을 낸 판정일의 다음 거래일부터, 그 계획의 진입가 지정가가 닿을 때입니다"
             + (" · 주문 방식이 '계획마다 승인'이라 그 계획을 '오늘 계획'에서 승인해야 삽니다" if X.approval_of(stt) == 'approve' else '')
             + '. 그 날짜는 미리 말할 수 없습니다 — 추천이 언제 나올지는 아무도 모릅니다.')
    return dict(live=live, headline=headline, start=start, first_buy=first, items=items, n_ok=len(items) - len(missing),
                n_items=len(items), missing=[i['label'] for i in missing], next_session=nxt)


def daily_last(history):
    """계좌 스냅샷 이력 → 하루 마지막 스냅샷 한 개씩(오래된 날부터) — 자산 곡선이 15초 갱신의 장중 흔들림에 묻히지 않게(라운드 457)."""
    by = {}
    for r in history or []:
        k = str(r.get('ts') or '')[:10]
        if k:
            by[k] = r                                          # 오래된 것부터 들어오므로 마지막이 남는다
    return [by[k] for k in sorted(by)]

#: 깔때기 단계 이름 — 수는 부르는 쪽이 센다. '승인' 단계는 실전 승인형일 때만 뜻이 있다(아니면 자격 = 승인).
FUNNEL_STAGES = ('후보', '실주문 자격', '승인', '주문 냄', '체결')


def _f(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def equity_points(history, managed_codes=None, positions_by_ts=None):
    """계좌 스냅샷 이력 → 곡선 점 [{'ts','total','cash','managed'}]. 자동매매 평가는 스냅샷 보유 JSON 이 있을 때만(없으면 None)."""
    out = []
    for r in history or []:
        tot = _f(r.get('total_eval'))
        if tot is None:
            continue
        managed = None
        if managed_codes and positions_by_ts and r.get('ts') in positions_by_ts:
            vals = [_f(p.get('eval_amt')) for p in positions_by_ts[r['ts']] if str(p.get('code')) in managed_codes]
            managed = sum(v for v in vals if v is not None) if vals else 0.0
        out.append(dict(ts=r.get('ts'), total=tot, cash=_f(r.get('cash')), managed=managed))
    return out


def allocation(summary, managed_codes):
    """자산 구성 세 조각 — 현금 · 자동매매 관리 보유 · 직접 보유(총자산 대비 %). 총자산이 없으면 []."""
    total = summary.get('total')
    if not total or total <= 0:
        return []
    man = sum(r['eval'] for r in summary['rows'] if r.get('eval') is not None and r['code'] in (managed_codes or ()))
    stock = sum(r['eval'] for r in summary['rows'] if r.get('eval') is not None)
    parts = []
    if summary.get('cash') is not None:
        parts.append(dict(label='현금(예수금)', pct=summary['cash'] / total * 100.0, tone='tx3'))
    if man:
        parts.append(dict(label='자동매매 관리 보유', pct=man / total * 100.0, tone='brand'))
    if stock - man > 0:
        parts.append(dict(label='직접 보유(자동 매도 안 함)', pct=(stock - man) / total * 100.0, tone='warn'))
    return parts


def risk_usage(summary, limits, managed_n=0, new_orders_today=0, planned_loss_sum=None):
    """위험 한도 사용 — ⑥의 한도와 지금 값. 한도가 비면 []. 거래당 최대손실은 열린 자동관리 포지션의 계획 손실 **합**을 옆에 둔다(비율 아님)."""
    import swing_risk
    vals, missing, problems = swing_risk.validate(limits or {})
    if missing or problems:
        return []
    items = [dict(label='동시 보유 종목(자동관리)', used=managed_n, limit=vals['max_open_positions'], unit='개'),
             dict(label='주식 평가 비중(계좌 전체)', used=summary.get('stock_w'), limit=vals['max_total_exposure_pct'], unit='%',
                  text='직접 보유 포함'),
             dict(label='오늘 신규 주문', used=new_orders_today, limit=vals['max_daily_new_orders'], unit='건'),
             dict(label='최대 단일 종목 비중', used=summary.get('top1'), limit=vals['max_position_pct'], unit='%', text='직접 보유 포함')]
    if planned_loss_sum is not None:
        items.append(dict(label='열린 자동관리 계획 손실 합', used=planned_loss_sum, limit=None, unit='원',
                          text=f"거래당 최대손실 {vals['risk_per_trade_krw']:,.0f}원"))
    return items


def funnel_today(plans_today, approved=None, approval_on=False, intents_today=None, managed_codes=None):
    """오늘 깔때기 — 후보 → 실주문 자격 → 승인 → 주문 냄 → 체결. 전부 장부의 수(지어내지 않는다)."""
    ps = list(plans_today or [])
    live = [p for p in ps if p.get('live_ok')]
    if approval_on:
        appr = [p for p in live if p.get('plan_id') in (approved or set())]
        appr_sub = '계획마다 승인'
    else:
        appr, appr_sub = live, '승인 불필요(자격 = 승인)'
    its = [it for it in (intents_today or []) if it.get('side') == 'buy']
    filled = [it for it in its if it.get('state') in ('FILLED', 'PARTIAL')]
    return [dict(label='후보', n=len(ps), sub='개장 전 리포트'), dict(label='실주문 자격', n=len(live), sub='중앙 판정 조건 전부 통과'),
            dict(label='승인', n=len(appr), sub=appr_sub), dict(label='주문 냄', n=len(its), sub='오늘 매수 의도'),
            dict(label='체결', n=len(filled), sub='부분 체결 포함')]


def planned_loss_sum(managed):
    """열린 자동관리 포지션의 계획 손실 합 — Σ (진입가 − 손절가) × 수량 · 셋 다 있는 것만. 하나도 없으면 None."""
    tot, n = 0.0, 0
    for p in (managed or {}).values():
        e, s, q = _f(p.get('entry_price')), _f(p.get('stop')), int(p.get('qty') or 0)
        if e is not None and s is not None and q:
            tot += (e - s) * q
            n += 1
    return tot if n else None


def execution_health(intents):
    """주문 사건 수 — 상태별. 판정 없음(수만)."""
    by = {}
    for it in intents or []:
        by[it.get('state') or '?'] = by.get(it.get('state') or '?', 0) + 1
    return dict(total=len(intents or []), by=by, unknown=by.get('UNKNOWN', 0), partial=by.get('PARTIAL', 0),
                rejected=by.get('REJECTED', 0), ack=by.get('BROKER_ACK', 0), filled=by.get('FILLED', 0), cancelled=by.get('CANCELLED', 0))


def system_health(worker, task, nightly, cfg, acct, plans_today, today=None, protection_warn=False, ledger_ok=True):
    """다섯 상태 띠 — 워커 · 한국투자 연결 · 계획 생성 · 장부 · 저녁 작업. 규칙은 여기 한 곳(문턱 없음 · 사실의 분류):
    워커: 잠금 주인 살아 있음 → RUNNING · 장중인데 오늘 기록 없음 → ERROR · 예약 작업 Ready → SCHEDULED · 등록 안 됨 → DEGRADED · 못 읽음 → UNKNOWN
    연결: 정보 없음 → ERROR · 연결 확인 전 → DEGRADED · 오늘 읽음 → OK(정상) · 전에 읽음 → IDLE
    계획: 오늘 계획 있음 → RUNNING · 없음 → IDLE(사유) · 장부: 열림 → OK(정상) / ERROR
    저녁 작업: 도는 중 → RUNNING · 마지막 종료 코드 0 → SCHEDULED · 0 아님 → DEGRADED · 기록 없음 → UNKNOWN"""
    out = []
    w = worker or {}
    if w.get('running') is True:
        out.append(dict(label='워커', state='RUNNING', text=w.get('note') or ''))
    elif protection_warn:
        out.append(dict(label='워커', state='ERROR', text='장중인데 오늘 기록 없음'))
    elif w.get('running') is None:
        out.append(dict(label='워커', state='UNKNOWN', text=w.get('note') or ''))
    elif task and task.get('ok') and task.get('installed'):
        out.append(dict(label='워커', state='SCHEDULED', text=(f"다음 {task.get('next_run')}" if task.get('next_run') else '예약 작업 등록됨')))
    elif task and task.get('ok') and task.get('installed') is False:
        out.append(dict(label='워커', state='DEGRADED', text='예약 작업 등록 안 됨'))
    else:
        out.append(dict(label='워커', state='UNKNOWN', text=(task or {}).get('reason') or '작업 상태를 못 읽음'))
    if not cfg or cfg.get('missing') or cfg.get('problems'):
        out.append(dict(label='한국투자 연결', state='ERROR', text='연결 정보 없음'))
    elif not acct:
        out.append(dict(label='한국투자 연결', state='DEGRADED', text='연결 확인 전'))
    else:
        ts = str(acct.get('ts') or '')
        if today and ts[:10] == str(today):
            out.append(dict(label='한국투자 연결', state='OK', text=f'오늘 {ts[11:16]} 읽음'))
        else:
            out.append(dict(label='한국투자 연결', state='IDLE', text=f'마지막 읽음 {ts[:10]}'))
    n = len(plans_today or [])
    out.append(dict(label='계획 생성', state=('RUNNING' if n else 'IDLE'), text=(f'오늘 계획 {n}' if n else '오늘 계획 없음')))
    out.append(dict(label='장부', state=('OK' if ledger_ok else 'ERROR'), text=('열림' if ledger_ok else '못 열음')))
    nn = nightly or {}
    if nn.get('running'):
        out.append(dict(label='저녁 작업', state='RUNNING', text=f"{nn.get('last_start')} 시작"))
    elif nn.get('last_end') and nn.get('worst') == 0:
        out.append(dict(label='저녁 작업', state='SCHEDULED', text=f"마지막 {nn['last_end']} 정상"))
    elif nn.get('last_end'):
        out.append(dict(label='저녁 작업', state='DEGRADED', text=f"마지막 종료 코드 {nn.get('worst')}"))
    else:
        out.append(dict(label='저녁 작업', state='UNKNOWN', text=nn.get('note') or '기록 없음'))
    return out


def position_card(code, pos, acct_row=None, target_intent=None, hb=None, horizon=None, today=None):
    """자동 관리 포지션 카드 재료 — 장부 포지션 + 잔고 행 + 걸린 목표 주문 + 워커 심박. 못 세면 None 칸."""
    entry, stop, target = _f(pos.get('entry_price')), _f(pos.get('stop')), _f(pos.get('target'))
    cur = _f((acct_row or {}).get('price'))
    qty = int(pos.get('qty') or 0)
    gross = (cur / entry - 1.0) * 100.0 if (cur and entry) else None
    d_stop = (stop / cur - 1.0) * 100.0 if (cur and stop) else None
    d_tgt = (target / cur - 1.0) * 100.0 if (cur and target) else None
    planned_loss = (entry - stop) * qty if (entry is not None and stop is not None and qty) else None
    held = None
    if pos.get('opened_day') and today:
        try:
            held = X.trading_days_between(pos['opened_day'], str(today))
        except (TypeError, ValueError):
            held = None
    return dict(code=code, name=(acct_row or {}).get('name') or '', ownership=pos.get('ownership'), qty=qty, entry=entry, stop=stop,
                target=target, current=cur, gross_pct=gross, dist_stop_pct=d_stop, dist_target_pct=d_tgt, planned_loss=planned_loss,
                held_days=held, horizon=horizon, target_order_state=(target_intent or {}).get('state'),
                heartbeat_ts=(hb or {}).get('ts'), releasing=bool(pos.get('releasing')))


_EV_KO = {'PLANNED': '계획', 'RISK_APPROVED': '한도 통과', 'SUBMITTING': '보내는 중', 'BROKER_ACK': '증권사 접수', 'PARTIAL': '일부 체결',
          'FILLED': '체결', 'CANCEL_REQUESTED': '취소 요청', 'CANCELLED': '취소', 'REJECTED': '거절', 'UNKNOWN': '확인 중',
          'EXPIRED': '만료'}
_EV_TONE = {'FILLED': 'pos', 'PARTIAL': 'warn', 'REJECTED': 'neg', 'UNKNOWN': 'warn', 'CANCELLED': 'tx3', 'EXPIRED': 'tx3'}


def order_timeline(events):
    """주문 사건 → 타임라인 재료 [{'ts','label','detail','tone'}]."""
    out = []
    for ev in events or []:
        st = ev.get('state')
        lab = _EV_KO.get(st, st or '?')
        det = []
        if ev.get('filled_qty'):
            det.append(f"체결 {ev['filled_qty']}" + (f" @ {float(ev['avg_fill']):,.0f}" if ev.get('avg_fill') else ''))
        if ev.get('detail'):
            det.append(str(ev['detail']))
        out.append(dict(ts=str(ev.get('ts') or '')[5:19].replace('T', ' '), label=lab, detail=' · '.join(det), tone=_EV_TONE.get(st, 'brand')))
    return out


def receipt_waterfall(r):
    """영수증 → 폭포 단계. 계획가 기준 수익(계획 진입→계획 청산) + 체결 차이 합(정확히 gross − 계획 수익) + 비용 가정 = 추정 비용후.
    진입·청산 슬리피지는 참고 칸(합이 정확히 맞지 않는 근사)이라 폭포에는 '체결 차이 합' 하나로 넣는다(§3). 못 세면 None."""
    gross, net, cost = _f(r.get('gross_pct')), _f(r.get('net_pct')), _f(r.get('cost_pct'))
    ep, xp = _f(r.get('entry_plan')), _f(r.get('exit_plan'))
    if gross is None or net is None:
        return None
    if ep and xp:
        plan_ret = (xp / ep - 1.0) * 100.0
        steps = [dict(label='계획가 기준', delta=plan_ret), dict(label='체결 차이 합', delta=gross - plan_ret)]
    else:
        steps = [dict(label='실제 체결가 수익', delta=gross)]
    if cost is not None:
        steps.append(dict(label='비용 가정', delta=-cost))
    return steps


def recent_events(heartbeats=None, nightly=None, acct=None, task=None, limit=6):
    """최근 사건 몇 줄 — 워커 심박 · 계좌 동기화 · 저녁 작업 끝 · 예약 작업 마지막 실행. 시각 있는 것만, 최근순."""
    ev = []
    for hb in heartbeats or []:
        if hb.get('ts'):
            ev.append((str(hb['ts']), f"워커 {hb.get('status') or ''}" + (f" · {hb.get('detail')}" if hb.get('detail') else '')))
    if acct and acct.get('ts'):
        ev.append((str(acct['ts']), '계좌 동기화(잔고 스냅샷)'))
    if nightly and nightly.get('last_end'):
        ev.append((f"2000-{nightly['last_end']}" if len(nightly['last_end']) == 14 else nightly['last_end'],
                   f"저녁 작업 끝 · 종료 코드 {nightly.get('worst')}"))
    ev.sort(key=lambda x: x[0], reverse=True)
    return [(ts[5:16].replace('T', ' ') if len(ts) >= 16 else ts, txt) for ts, txt in ev[:limit]]
