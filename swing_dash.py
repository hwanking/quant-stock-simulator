# -*- coding: utf-8 -*-
"""
스윙 관제실의 **재료 셈**(라운드 455) — 장부·잔고·운영 상태를 받아 그림이 그릴 수를 만든다. 순수 함수 · Streamlit 모름 · 판정 낱말 없음.

여기 수는 전부 이미 있는 자료에서 센 것이다(§3): 자산 곡선은 계좌 스냅샷 · 자산 구성은 잔고 + 장부 소유 · 위험 한도 사용은 ⑥의 한도 ·
오늘 깔때기는 계획·승인·주문 · 실행 상태는 주문 사건 · 시스템 상태는 워커 잠금·작업 스케줄러·저녁 작업 기록. 못 세는 칸은 None.
"""
import datetime as _dt
import hashlib as _hl

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


def parse_task_time(text):
    """작업 스케줄러가 돌려준 다음 실행 시각 글자('10/12/2026 21:00:00' · ISO 도) → datetime 또는 None(못 읽으면 지어내지 않는다)."""
    t = (text or '').strip() if isinstance(text, str) else ''
    for fmt in ('%m/%d/%Y %H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%m/%d/%Y %I:%M:%S %p'):
        try:
            return _dt.datetime.strptime(t, fmt)
        except ValueError:
            continue
    return None


def exec_day_of(judgment_day, max_days=20):
    """판정일 → 그 판정의 계획이 처음 사는 거래일(ISO) — 판정일 **다음 거래일**(실행부 `_entries` 의 waited ≥ 1 · 라운드 524).
    거래일은 장부의 달력 한 곳(`swing_executor.is_trading_day`). 못 구하면 None(지어내지 않는다)."""
    if not judgment_day:
        return None
    try:
        d = _dt.date.fromisoformat(str(judgment_day)[:10])
    except ValueError:
        return None
    for _i in range(1, max_days):
        d += _dt.timedelta(days=1)
        if X.is_trading_day(d.isoformat()):
            return d.isoformat()
    return None


def session_ended_for(day, now):
    """그 거래일의 정규장이 끝났나 (라운드 524) — 지난 날이면 참 · 오늘이면 마감 시각(엔진의 장 시각 한 곳 · 수능일 포함)이 지났나 ·
    앞날이면 거짓. 날짜가 없으면 None(모른다)."""
    d = str(day or '')[:10]
    if len(d) != 10:
        return None
    n = X.kst(now)
    today = n.date().isoformat()
    if d < today:
        return True
    if d > today:
        return False
    _op, cl = X._session_times(n.date())
    return n.time() >= cl


def next_judgement(nightly_task, anchor_day, report_day_fn=None):
    """다음 판정이 언제 나오고 그 계획의 매수는 언제부터인가 (라운드 492) → dict(run, data_day, new, buy_day) 또는 None.

    사용자가 '오늘 계획 · 실주문 자격 0'을 보고 *"이제 시작 안 해?"* 라 물었다 — 화면은 지금 계획(판정일)만 말하고 **다음 계획이
    언제 오는지**를 안 말했다. 규칙은 이미 있다: 저녁 작업이 그날 봉이 확정된 뒤 그 자료일의 개장 전 리포트를 만들고(라운드 484·486)
    같은 작업의 스윙 단계가 그 리포트로 계획을 남기며, 실행부는 판정일 **다음 거래일**부터 산다(`swing_executor._entries` · waited ≥ 1).
    그래서 여기서는 새로 정하지 않고 **유도**만 한다 — 다음 실행 시각은 작업 스케줄러에서, 그 실행이 만들 자료일은 리포트 날짜 규칙
    (`premarket.report_day`)에서, 매수 시작일은 거래일 달력에서. 다음 실행을 못 읽으면 None(§3) · 그 실행의 자료일이 지금 판정일과
    같으면(휴장일 밤) new=False — 그 밤엔 새 계획이 없다."""
    run = parse_task_time((nightly_task or {}).get('next_run')) if (nightly_task or {}).get('ok') else None
    if run is None:
        return None
    if report_day_fn is None:
        import premarket
        report_day_fn = premarket.report_day
    try:
        dd = report_day_fn(run)
    except Exception:                                          # noqa: BLE001 — 못 정하면 주장하지 않는다
        dd = None
    if not dd:
        return dict(run=run, data_day=None, new=False, buy_day=None)
    dd = str(dd)[:10]
    new = not anchor_day or dd > str(anchor_day)[:10]
    buy = None
    if new:
        _xd = exec_day_of(dd)                                  # 라운드 524 — 판정일 다음 거래일은 한 곳에서
        buy = _dt.date.fromisoformat(_xd) if _xd else None
    return dict(run=run, data_day=dd, new=new, buy_day=buy)


def next_judgement_line(nj, anchor_day, live_n):
    """`next_judgement` → 한 문장(판정 낱말 없음 · 수는 넘겨받은 것만). 못 읽었으면 None."""
    if not nj:
        return None
    run = nj['run'].strftime('%m-%d %H:%M')
    if not nj.get('new'):
        return (f"다음 저녁 작업({run})은 새 판정일이 아닙니다(휴장일 밤 — 그 실행의 자료일이 지금 판정일 {anchor_day} 와 같다) — "
                "그 밤엔 새 계획이 생기지 않습니다.")
    b = nj.get('buy_day')
    return (f"다음 계획 — 저녁 작업({run} · 그날 봉이 확정된 뒤)이 자료일 {nj['data_day']} 판정으로 만들고, 그 계획의 매수는 "
            + (f"{b.isoformat()}({WEEK_KO[b.weekday()]}) 장부터입니다" if b else '그다음 거래일 장부터입니다')
            + f" — 그 판정에 '추천'이 있을 때만(또는 '오늘 계획'에서 사람이 그 계획을 직접 고를 때). "
              f"지금 보이는 계획은 판정일 {anchor_day} 의 것이고 실주문 자격은 {live_n}개입니다.")


def _when(d, op):
    return f"{d.isoformat()}({WEEK_KO[d.weekday()]}) {op.strftime('%H:%M')}" if d else None


#: 라운드 502 — 실전을 켜는 자리(라운드 501 의 한 칸). 시작 카드의 남은 일이 이 이름을 그대로 쓴다(화면의 제목과 같은 글자).
START_HERE = "시스템 → 설정 맨 위 '실전 시작 — 한 번에'"


def start_status(mode, stt, cfg, task=None, worker=None, now=None, live_buys=None):
    """자동매매 언제 시작하나 (라운드 457) — 장부 설정 · 실전 준비 넷(`live_readiness`) · 운용 모드 · 워커 예약 작업 · 거래일 달력에서
    **유도**한다. 실제 첫 매수 날짜는 말하지 않는다 — 중앙 판정이 추천을 언제 낼지는 아무도 모른다(§3). 판정 낱말 없음.
    → dict(live, headline, start, first_buy, items=[{label, ok, why}], n_ok, n_items, missing)"""
    now = now or X.now_kst()
    items = [dict(label=n, ok=bool(ok), why=str(w)) for n, ok, w in X.live_readiness(cfg, stt)]
    # 라운드 502 — 잠금과 모드는 라운드 501 의 한 칸에서 같이 켠다 — 남은 일이 그 자리를 가리킨다(조건·판정 불변)
    for it in items:
        if it['label'] == '실전 잠금 해제' and not it['ok']:
            it['why'] = START_HERE + ' — 문장 한 번으로 운용 모드와 같이 풀립니다'
    mko = {'OFF': '꺼짐', 'SHADOW': '기록만', 'PAPER': '모의투자', 'LIVE': '실전'}.get(mode, mode)
    items.append(dict(label='운용 모드 실전', ok=(mode == 'LIVE'),
                      why=('실전' if mode == 'LIVE' else f'지금 {mko} — {START_HERE}에서 잠금과 같이 켭니다(위 넷이 다 통과해야 켜집니다)')))
    task_ok = bool(task and task.get('ok') and task.get('installed'))
    items.append(dict(label='워커 예약 작업', ok=task_ok,
                      why=(f"등록됨 · 다음 실행 {task.get('next_run') or '—'}" if task_ok else
                           ((task or {}).get('reason') or '등록 안 됨 — scripts/register_swing_worker_task.ps1 을 한 번 돌립니다'))))
    missing = [i for i in items if not i['ok']]
    in_sess = X.session_open(now)
    w_run = (worker or {}).get('running') is True
    # 라운드 511 — '안 돈다'고 적을 때는 왜 그렇게 보는지(워커 상태 문장)를 같은 줄에 — 사용자가 하나를 더 켜기 전에 사실을 본다
    _wnote = str((worker or {}).get('note') or '').strip()
    _wnote = f' ({_wnote})' if _wnote else ''
    nxt = _when(*next_session_start(now))
    nxt_after = _when(*next_session_start(now, skip_today=True))
    live = not missing
    if live:
        headline = '실전 자동매매가 켜져 있습니다'
        if in_sess and w_run:
            start = '지금 — 워커가 돌고 있어 다음 바퀴(1분 안)부터 실주문 자격이 있는 계획을 냅니다'
        elif in_sess:
            start = (f'지금은 장중인데 워커가 돌고 있지 않습니다{_wnote} — 직접 켜면 지금부터(python scripts/run_swing_worker.py --session --loop 60), '
                     f'아니면 다음 장 {nxt_after}')
        else:
            start = f'다음 장 {nxt} — 그 전에 워커 예약 작업이 돌고 장이 열리면 주문합니다'
    else:
        headline = f'자동매매는 아직 시작하지 않았습니다 — 남은 일 {len(missing)}개'
        if in_sess and w_run:
            start = '남은 일을 채우면 지금(워커가 돌고 있어 다음 바퀴 · 1분 안)부터'
        elif in_sess:
            start = f'남은 일을 채우면 가장 빨리 다음 장 {nxt_after}부터(오늘은 워커가 안 돌고 있습니다{_wnote} · 직접 켜면 오늘부터)'
        else:
            start = f'남은 일을 채우면 가장 빨리 다음 장 {nxt}부터' if nxt else '다음 장 날짜를 구하지 못했습니다(휴장일 표 밖)'
    # 라운드 517 — 첫 실매수 주문이 나간 뒤에도 카드가 '그 날짜는 미리 말할 수 없습니다'만 적었다(2026-10-13 09:00:12 첫 실주문).
    #   장부의 실전 매수 주문(`live_buys` · 실행부가 적은 그대로)을 사실로 먼저 적는다 — 주문이 나간 것과 체결(실제 매수)은 다르다.
    lb = sorted([it for it in (live_buys or []) if it.get('side') == 'buy' and it.get('mode') == 'LIVE'],
                key=lambda it: str(it.get('created_ts') or ''))
    if lb:
        f0 = lb[0]
        fq = sum(int(it.get('filled_qty') or 0) for it in lb)
        ts0 = str(f0.get('created_ts') or '')
        st0 = f0.get('state')
        w0 = _EV_KO.get(st0, st0 or '—')
        # 라운드 524 — 2026-10-13 22:34 관제실이 그날 체결 0 으로 끝난 첫 실주문을 '지금 증권사 접수'라 적었다. 실행부는 마감 직후 늦게
        #   알려지는 체결을 버리지 않으려고 그날 주문을 그날엔 만료로 적지 않는다(`reconcile` · 지난 거래일만 만료) — 장부 상태는 맞고
        #   '지금'이 틀렸다. 그날 정규장이 끝났으면 장부 상태라고 적고 다음 거래일 첫 바퀴가 무엇을 하는지(실행부 그대로)를 같은 줄에.
        ended0 = st0 in X.OPEN_STATES and session_ended_for(f0.get('trade_day'), now) is True
        fact = (f"실주문은 이미 나갔습니다 — 실전 매수 주문 {len(lb)}건 · 처음 {ts0[:10]} {ts0[11:19]} "
                f"({f0.get('code') or '—'} · {_f(f0.get('price')) or 0:,.0f}원 지정가 · {'장부 상태' if ended0 else '지금'} {w0}) · "
                + (f"체결 합계 {fq}주. " if fq else
                   ("아직 체결 0주 — 그날 정규장이 끝났고 그날 주문이라 다음 거래일로 넘어가지 않습니다 · 다음 거래일 워커의 첫 바퀴가 그날 "
                    "내역으로 맞춰 체결이 있었으면 체결로, 없으면 만료로 적습니다. " if ended0 else
                    "아직 체결 0주 — 체결은 진입가 지정가에 닿을 때입니다. ")))
    else:
        fact = ''
    first = (fact + "실제 첫 매수: 중앙 판정이 '추천'(조건 11개 전부 통과)을 낸 판정일의 다음 거래일부터, 그 계획의 진입가 지정가가 닿을 때입니다"
             + (" · 주문 방식이 '계획마다 승인'이라 그 계획을 '오늘 계획'에서 승인해야 삽니다" if X.approval_of(stt) == 'approve' else '')
             + '. 그 날짜는 미리 말할 수 없습니다 — 추천이 언제 나올지는 아무도 모릅니다.'
             # 라운드 494 — 사람이 고른 계획 매수: 엔진 판정은 그대로, 고르는 것은 사람이다(이 카드는 아무 계획도 권하지 않는다)
             + " 엔진이 추천하지 않은 계획도 '오늘 계획'에서 사람이 직접 고르면 같은 계약(진입가 지정가 · 손절 · 1차 목표)으로 "
               '판정일 다음 거래일부터 삽니다 — 그 매수는 엔진 추천이 아니라 사람의 결정으로 적힙니다.')
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


def funnel_today(plans_today, approved=None, approval_on=False, intents_today=None, managed_codes=None, approval_mode=None,
                 picks=None, report=None, prices=None, exec_day=None):
    """오늘 깔때기 — 후보 → 실주문 자격 → 승인 → 주문 냄 → 체결. 전부 장부의 수(지어내지 않는다).

    라운드 491 — 실전이 아니면 `approval_on` 이 거짓이라 승인 칸이 '승인 불필요(자격 = 승인)'였는데, 같은 화면의 시작 카드는 주문 방식이
    '계획마다 승인'이라 승인해야 산다고 적었다(한 화면의 두 말). 주문 방식(`approval_mode`)이 승인형이면 실전이 아니어도 승인한 수를
    세고 '실전에서 계획마다 승인'이라 적는다.

    라운드 514 — `prices`({코드: 현재가 또는 None})를 주면 줄마다 현재가와 그 가격에서 진입가·지정가까지의 거리를 적는다(사용자:
    *"너무 간단하게만 나오지 않아? 현재가가 얼마고 하면서 나와야 하는 거 아닌가"*). 가격은 부르는 쪽(화면)이 받는다 — 이 함수는
    네트워크를 안 탄다. 안 주면(None) 종전 줄 그대로."""
    ps = list(plans_today or [])
    _lv514 = prices is not None
    _px514 = (lambda code: (prices or {}).get(str(code or '')))
    live = [p for p in ps if p.get('live_ok')]
    if approval_on:
        appr = [p for p in live if p.get('plan_id') in (approved or set())]
        appr_sub = '계획마다 승인'
    elif approval_mode == 'approve':
        appr = [p for p in live if p.get('plan_id') in (approved or set())]
        appr_sub = '실전으로 켜면 계획마다 승인 · 지금은 주문 안 냄'
    else:
        appr, appr_sub = live, '승인 불필요(자격 = 승인)'
    # 라운드 494 — 사람이 고른 계획(실주문 자격 없음 · 고르기로 넘을 수 없는 막힘 없음)은 자격 칸에 따로 세고, 고르기가 승인을 겸한다
    import swing_engine as _se494
    hp = [p for p in ps if not p.get('live_ok') and p.get('plan_id') in (picks or set()) and not _se494.pick_blockers(p, report)]
    elig_sub = '중앙 판정 조건 전부 통과' + (f' {len(live)} · 사람이 고름 {len(hp)}' if hp else '')
    if hp:
        appr = list(appr) + hp
        appr_sub += f' · 사람이 고른 {len(hp)} 포함(고르기 = 승인)'
    its = [it for it in (intents_today or []) if it.get('side') == 'buy']
    filled = [it for it in its if it.get('state') in ('FILLED', 'PARTIAL')]
    # 라운드 508 — 사용자: "후보 · 실주문 · 승인 · 주문 냄 클릭하면 뭔 종목인지 나와야 하는 거 아닌가?" 칸마다 그 단계의 종목을 싣는다
    #   (장부의 계획·주문 그대로 · 새 값 없음). 그리고 라운드 507 뒤로 후보는 개장 전 리포트만이 아니다 — 출처를 세어 적는다.
    n_watch = sum(1 for p in ps if _se494.verdict_of(p).get('source') == 'watchlist')
    cand_sub = (f'개장 전 리포트 {len(ps) - n_watch} · 관심종목 추천 {n_watch}' if n_watch else '개장 전 리포트')
    names = {str(p.get('code')): plan_label(p) for p in ps if p.get('code')}
    hp_ids = {p.get('plan_id') for p in hp}
    # 실주문 자격이 있는 후보를 먼저(안정 정렬 · 나머지 차례는 장부 그대로) — 누른 사람이 찾는 줄이 맨 위에 오게
    return [dict(label='후보', n=len(ps), sub=cand_sub,
                 items=[candidate_item(p, px=_px514(p.get('code')), live=_lv514) for p in sorted(ps, key=lambda p: not p.get('live_ok'))]),
            dict(label='실주문 자격', n=len(live) + len(hp), sub=elig_sub,
                 items=[plan_price_item(p, picked=p.get('plan_id') in hp_ids, px=_px514(p.get('code')), live=_lv514)
                        for p in list(live) + hp]),
            dict(label='승인', n=len(appr), sub=appr_sub,
                 items=[plan_price_item(p, picked=p.get('plan_id') in hp_ids, px=_px514(p.get('code')), live=_lv514) for p in appr]),
            dict(label='주문 냄', n=len(its), sub=(f'매수일 {str(exec_day)[5:10]} 매수 의도' if exec_day else '오늘 매수 의도'),
                 items=[intent_item(it, names, px=_px514(it.get('code')), live=_lv514) for it in its]),
            dict(label='체결', n=len(filled), sub='부분 체결 포함',
                 items=[intent_item(it, names, px=_px514(it.get('code')), live=_lv514) for it in filled])]


FUNNEL_WHY_CUT = 44          # 후보 칸의 막힌 사유를 이 글자에서 줄인다(칸 폭 · 판정 문턱 아님) — 전체는 '오늘 계획' 갈래의 표


def plan_label(p):
    """계획 한 줄의 이름표 — '이름 (코드)' · 이름이 없으면 코드 · 둘 다 없으면 계획 번호 · 그것도 없으면 '—' (라운드 508)."""
    nm, cd = str((p or {}).get('name') or '').strip(), str((p or {}).get('code') or '').strip()
    if nm and cd:
        return f'{nm} ({cd})'
    return nm or cd or str((p or {}).get('plan_id') or '—')


def px_clause(px, entry=None, stop=None, live=False, to='진입가', buyable=True):
    """현재가 한 조각(라운드 514) — 지금 가격과 그 가격에서 `to`(진입가·지정가)까지의 거리. 판정 낱말 없음 · 새 문턱 없음.
    손절선 이하면 워커가 사지 않는다는 사실(실행부 `_entries` 의 손절선 확인과 같은 비교). `live` 가 거짓이면 ''(종전 줄 그대로) ·
    가격을 못 받았으면 그 사실. `buyable` 이 거짓(추천 아님 · 고르지 않은 후보)이면 진입가 이하여도 '체결될 수 있음'을 안 붙인다 —
    그 계획은 워커가 사지 않는다."""
    if not live:
        return ''
    px = _f(px)
    if not px:
        return '현재가 못 받음'
    head = f'현재가 {px:,.0f}원'
    e, s = _f(entry), _f(stop)
    if s and px <= s:
        return f'{head} · 손절선 {s:,.0f}원 이하 — 워커가 사지 않음'
    if e and px > e:
        return f'{head} · {to}까지 {(e / px - 1) * 100:+.1f}%'
    if e:
        return f'{head} · {to} 이하' + (' — 지정가 매수가 체결될 수 있음' if buyable else '')
    return head


def learning_draw(cands, day, qty_of):
    """학습용 1종목 추첨 (라운드 526) → (계획 또는 None, 뽑을 수 있던 수, 못 뽑은 사유).

    사용자: *"후보 1개나 무조건 내줘 … 실제로 매매하면서 얻는 게 있을 거잖아."* 엔진 추천은 0 이고, 다섯 후보 중 어느 것이 낫다고 말할
    근거가 없다 — 같은 날 종목을 점수로 세운 짝비교(라운드 49·110)도, 비용 차감 기대값의 순서(라운드 475)도 결과를 못 갈랐다. 그래서
    '가장 좋은 것'을 고르는 규칙은 지어낸 것이 되고(§2), 대신 **좋고 나쁨과 무관한** 추첨을 둔다: 고를 수 있고 수량 미리보기가 한 주
    이상인 계획만 · 판정일과 그 계획 번호들로 정해진 해시(sha256) 한 번 — 같은 판정일엔 몇 번 눌러도 같은 계획이다(마음에 드는 종목이
    나올 때까지 다시 뽑는 길을 막는다 · 그것은 고르는 것이다). 이 함수는 고르지 않는다 — 부르는 화면이 고를 칸에 넣기만 하고, 적는 것은
    종전 그대로 사람이 확인 체크와 단추로 한다(§473). `qty_of(p)` 가 None 이면(미리보기를 못 셈) 그 계획은 뽑지 않는다(§3)."""
    elig = []
    for p in cands or []:
        try:
            q = qty_of(p)
        except Exception:                                      # noqa: BLE001 — 못 세면 뽑지 않는다
            q = None
        if q is not None and int(q) >= 1 and p.get('plan_id'):
            elig.append(p)
    if not elig:
        return None, 0, '고를 수 있고 한 주 이상 살 수 있는 계획이 없습니다(수량 미리보기 0주이거나 못 셈)'
    ids = sorted(str(p['plan_id']) for p in elig)
    h = int(_hl.sha256((str(day)[:10] + '|' + ','.join(ids)).encode('utf-8')).hexdigest(), 16)
    pid = ids[h % len(ids)]
    return next(p for p in elig if str(p['plan_id']) == pid), len(elig), ''


#: 추첨이 무엇인지 — 화면 문장(규칙 한 곳)
LEARNING_DRAW_RULE = ('추첨은 좋은 종목을 고르는 규칙이 아닙니다 — 같은 날 종목을 점수·기대값으로 세워도 결과를 못 갈랐기 때문에 '
                      '좋고 나쁨과 무관하게 뽑습니다(판정일과 계획 번호로 정해진 해시 · 같은 판정일엔 늘 같은 계획). '
                      '고를 칸에 넣기만 하고, 사는 것은 아래에서 확인 체크와 고르기를 직접 눌러야 정해집니다.')


GAP_REACH_SHOW = 5          # 한 줄에 이름을 적는 계획 수(칸 폭 · 판정 문턱 아님) — 나머지는 '외 N개'


def gap_reach_line(plans, prices, reach=''):
    """실주문 자격 계획 중 지금 가격이 진입가 지정가보다 **위**인 것 — 사실 한 줄(라운드 523 · 판정 낱말 없음 · 새 문턱 없음).

    2026-10-13 첫 실주문이 지정가 13,620원(판정 때 가격보다 10.6% 아래 · 그 종목의 일변동성 1배)이라 장 마감까지 체결 0 이었다.
    사용자: *"괴리가 큰데 이거 못 사는 거 아냐? 내일도 계속 사는 거야?"* 화면은 거리(라운드 509·514)만 적고 두 물음에는 답하지
    않았다. ① 지정가라 그 가격까지 내려와야 체결된다 ② 다음 거래일엔 그날 밤 다시 잰 판정을 따른다 — 실행부 `_entries` 그대로:
    같은 종목의 더 새 판정 계획이 있으면 그것이 대신하고(다시 추천이면 새 진입가) · 더 새 판정이 추천이 아니면 이 계획으로 안 사고 ·
    다시 안 잰 종목이면 이 계획으로 대기 기간 안에서 거래일마다 다시 주문한다(체결된 수량이 있으면 그 계획은 다시 안 산다)
    ③ 같은 규칙의 진입가가 얼마나 닿았고 닿은 뒤 어땠는지는 `entry_facts.reach_clause` 한 곳(부르는 쪽이 넘긴다 · 못 읽으면 '').
    가격을 못 받은 계획은 세지 않는다(위인지 모른다 · §3). 없으면 None."""
    above = []
    for p in plans or []:
        if not (p or {}).get('live_ok'):
            continue
        px, e = _f((prices or {}).get(p.get('code'))), _f(p.get('entry'))
        if px and e and px > e:
            above.append((p, (e / px - 1) * 100))
    if not above:
        return None
    shown = ' · '.join(f'{plan_label(p)} 진입가까지 {g:+.1f}%' for p, g in above[:GAP_REACH_SHOW])
    more = f' 외 {len(above) - GAP_REACH_SHOW}개' if len(above) > GAP_REACH_SHOW else ''
    wbs = sorted({int(p.get('wait_bars')) for p, _ in above if str(p.get('wait_bars') or '').isdigit()})
    wb = f'{wbs[0]}거래일' if len(wbs) == 1 else '정해진 대기 거래일'
    s = (f'실주문 자격 계획 {len(above)}개는 지금 가격이 진입가 지정가보다 위입니다({shown}{more}) — 지정가 매수라 그 가격까지 '
         '내려와야 체결되고, 지정가보다 비싸게 사지는 않습니다. 다음 거래일엔 그날 밤 다시 잰 판정을 따릅니다: 다시 추천이면 그 판정의 '
         '새 계획(새 진입가)이 대신하고, 추천이 아니면 이 계획으로는 사지 않으며, 다시 재지 않은 종목이면 이 계획으로 판정일 다음 '
         f'거래일부터 {wb} 안에서 거래일마다 다시 주문합니다.')
    return s + (f' {reach}.' if reach else '')


def candidate_item(p, px=None, live=False):
    """후보 칸의 한 줄 — 이름표 · 출처(개장 전 리포트 / 관심종목 추천) · 실주문 자격 또는 막힌 사유(길면 '…' · 전체는 '오늘 계획').
    라운드 514 — `live` 면 이름표 바로 뒤에 현재가와 진입가까지의 거리(`px_clause`)."""
    import swing_engine as _se
    src = '관심종목 추천' if _se.verdict_of(p).get('source') == 'watchlist' else '개장 전 리포트'
    if p.get('live_ok'):
        why = '실주문 자격 있음'
    else:
        why = str(p.get('block_reason') or '실주문 자격 없음')
        if len(why) > FUNNEL_WHY_CUT:
            why = why[:FUNNEL_WHY_CUT] + '…'
    pc = px_clause(px, p.get('entry'), None, live, buyable=bool(p.get('live_ok')))
    return f'{plan_label(p)}' + (f' · {pc}' if pc else '') + f' · {src} · {why}'


def plan_price_item(p, picked=False, px=None, live=False):
    """자격·승인 칸의 한 줄 — 이름표 · 진입 지정가 · 1차 목표 · 손절(장부의 계획 값 그대로 · 없는 값은 안 적는다).

    라운드 509 — 판정 때 가격(계획의 판정 기록 `current_price`)과 진입가까지의 거리도 적는다. 진입가는 지정가라 그 가격까지
    내려와야 체결되는데, 칸이 진입가만 적어 *"현재가랑 차이가 많이 나는데"* 를 화면이 먼저 말하지 않았다. 판정 기록에 가격이
    없으면 안 적는다(§3 · 지금 가격을 새로 받지 않는다 — 이 칸은 15초마다 다시 그려진다)."""
    import swing_engine as _se
    parts = []
    for k, nm in (('entry', '진입 지정가'), ('target', '1차 목표'), ('stop', '손절')):
        v = _f((p or {}).get(k))
        if v is not None:
            parts.append(f'{nm} {v:,.0f}원')
    cp, e = _f(_se.verdict_of(p).get('current_price')), _f((p or {}).get('entry'))
    if cp and e:
        if live:            # 라운드 514 — 현재가 쪽이 '진입가까지'를 이미 말한다 · 한 줄에 같은 이름의 수가 둘이면 단위를 옆에(R233)
            parts.append(f'판정 때 가격 {cp:,.0f}원(그때 ' + (f'{(e / cp - 1) * 100:+.1f}%)' if cp > e else '진입가 이하)'))
        else:
            parts.append(f'판정 때 가격 {cp:,.0f}원 · ' + (f'진입가까지 {(e / cp - 1) * 100:+.1f}%' if cp > e else '진입가 이하'))
    # 라운드 514 — 현재가를 이름표 바로 뒤에(가장 먼저 읽히게) · 손절선 이하면 워커가 사지 않는다는 사실까지
    pc = px_clause(px, (p or {}).get('entry'), (p or {}).get('stop'), live)
    if pc:
        parts.insert(0, pc)
    return plan_label(p) + (' · 사람이 고름' if picked else '') + (' · ' + ' · '.join(parts) if parts else '')


def intent_item(it, names=None, px=None, live=False):
    """주문 칸의 한 줄 — 이름표(계획에서) · 수량 · 지정가 · 지금 상태(관제실 사건 낱말과 같은 표).

    라운드 514 — 체결이 있으면 체결 수량·평균 체결가(장부의 맞춘 값 그대로) · `live` 면 현재가와 지정가까지의 거리, 체결된 뒤엔
    평균 체결가 대비 지금 평가(비용 제외 · 매도 전)."""
    code = str((it or {}).get('code') or '')
    lab = (names or {}).get(code) or code or '—'
    q = (it or {}).get('qty')
    st_ = (it or {}).get('state')
    lim = _f((it or {}).get('price'))
    out = (f'{lab}' + (f' · {q}주' if q else '') + (f' · {lim:,.0f}원 지정가' if lim else ' · 시장가')
           + (f' · {_EV_KO.get(st_, st_)}' if st_ else ''))
    fq, avg = int((it or {}).get('filled_qty') or 0), _f((it or {}).get('avg_fill'))
    if fq > 0:
        out += f' · 체결 {fq}주' + (f' · 평균 {avg:,.0f}원' if avg else '')
    if live:
        now = _f(px)
        if fq > 0 and avg and now:
            out += f' · 현재가 {now:,.0f}원 · 평균 체결가 대비 {(now / avg - 1) * 100:+.1f}%(비용 제외 · 매도 전)'
        elif (it or {}).get('side') == 'sell':
            out += ' · ' + (f'현재가 {now:,.0f}원' + (f' · 지정가까지 {(lim / now - 1) * 100:+.1f}%' if lim else '') if now else '현재가 못 받음')
        else:
            out += ' · ' + px_clause(now, lim, None, True, to='지정가')
    return out


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


def system_health(worker, task, nightly, cfg, acct, plans_today, today=None, protection_warn=False, ledger_ok=True, live_ts=None):
    """다섯 상태 띠 — 워커 · 한국투자 연결 · 계획 생성 · 장부 · 저녁 작업. 규칙은 여기 한 곳(문턱 없음 · 사실의 분류):
    워커: 잠금 주인 살아 있음 → RUNNING · 장중인데 오늘 기록 없음 → ERROR · 예약 작업 Ready → SCHEDULED · 등록 안 됨 → DEGRADED · 못 읽음 → UNKNOWN
    연결: 정보 없음 → ERROR · 연결 확인 전 → DEGRADED · 오늘 읽음 → OK(정상) · 전에 읽음 → IDLE
    계획: 오늘 계획 있음 → OK(정상 · 판정일과 함께) · 없음 → IDLE · 장부: 열림 → OK(정상) / ERROR
    저녁 작업: 도는 중 → RUNNING · 마지막 종료 코드 0 → SCHEDULED · 0 아님 → DEGRADED · 기록 없음 → UNKNOWN

    `live_ts` — 이 화면의 계좌 칸이 방금 잔고를 읽은 시각(라운드 492). 장부 스냅샷은 값이 같으면 다시 안 쌓으므로(라운드 457·458)
    화면이 15초마다 읽어도 장부의 시각은 그날 첫 값(예: 01:03)에 머문다 — 상태 띠가 그것만 보면 바로 아래 계좌 칸의 '방금 읽음'과
    한 화면에서 다른 말을 했다(라운드 454 가 지휘 띠에서 고친 그 모양 · `swing_view.conn_label`). 둘 중 새로운 쪽을 적는다."""
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
    elif not acct and not live_ts:
        out.append(dict(label='한국투자 연결', state='DEGRADED', text='연결 확인 전'))
    else:
        ts = str((acct or {}).get('ts') or '')
        here = bool(live_ts) and str(live_ts) > ts           # 같은 ISO 앞부분(YYYY-MM-DDTHH:MM:SS)이라 글자 순서 = 시각 순서
        if here:
            ts = str(live_ts)
        if today and ts[:10] == str(today):
            out.append(dict(label='한국투자 연결', state='OK', text=f"오늘 {ts[11:16]} 읽음" + (' (이 화면)' if here else '')))
        else:
            out.append(dict(label='한국투자 연결', state='IDLE', text=f'마지막 읽음 {ts[:10]}'))
    n = len(plans_today or [])
    # 라운드 491 — 계획이 **있으면** '실행 중'이라 적었다(아무것도 안 도는 일요일 저녁에도). 계획은 도는 것이 아니라 남은 것이다 —
    #   연결·장부를 '정상'으로 고친 라운드 455 의 그 자리 · 판정일을 같이 적는다(그 계획은 '오늘' 판정이 아닐 수 있다).
    _pd491 = next((str(p.get('data_day'))[:10] for p in (plans_today or []) if isinstance(p, dict) and p.get('data_day')), None)
    out.append(dict(label='계획 생성', state=('OK' if n else 'IDLE'),
                    text=((f'판정일 {_pd491} 계획 {n}' if _pd491 else f'계획 {n}') if n else '오늘 계획 없음')))
    out.append(dict(label='장부', state=('OK' if ledger_ok else 'ERROR'), text=('열림' if ledger_ok else '못 열음')))
    nn = nightly or {}
    if nn.get('running'):
        out.append(dict(label='저녁 작업', state='RUNNING', text=f"{nn.get('last_start')} 시작"))
    elif nn.get('last_end') and nn.get('worst') == 0:
        out.append(dict(label='저녁 작업', state='SCHEDULED', text=f"마지막 {nn['last_end']} 정상"))
    elif nn.get('last_end'):
        # 라운드 508 — '종료 코드 1' 만으로는 무엇이 실패했는지 모른다. 실패한 단계를 이름으로(`swing_ops.nightly_status` 가 싣는 한 줄 ·
        #   여기는 읽기만 · 단계 줄을 못 읽었으면 종전 문장)
        out.append(dict(label='저녁 작업', state='DEGRADED',
                        text=f"마지막 종료 코드 {nn.get('worst')}" + (f" · {nn['failed']}" if nn.get('failed') else '')))
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


#: '최근 사건' 칸이 읽는 심박 수(라운드 495) — 장중 워커는 1분마다 한 줄을 남긴다. 이어진 같은 기록을 한 줄로 묶으려면 몇 줄을 봐야
#: 하는지의 창이지 판정 문턱이 아니다. 창 끝까지 같은 기록이면 횟수를 'N번 이상'으로 적는다(본 것만 센다 · §3).
#: 라운드 498 — 처음 400 으로 뒀는데 2026-10-12 첫 장중 세션이 심박을 **400줄**(08:50~15:30) 남겨 창이 그날 하나로 꽉 찼고, 칸에는
#: '같은 기록 400번 이상' 한 줄만 남아 그 전 저녁 작업의 기록이 다시 밀렸다. 세션 셋 몫(1,200)을 읽는다(질의는 장부 한 번 · 가볍다).
BEAT_WINDOW = 1200


def collapse_beats(heartbeats, window=None):
    """최근순 심박 → 이어진 같은 기록(상태 · 내용)을 한 묶음으로 (라운드 495). → [dict(ts=마지막 · first=처음 · n · status · detail ·
    more=창 끝까지 이어졌나)]. 장중 워커가 1분마다 같은 줄을 남기면 '최근 사건' 칸 세 줄이 전부 그 줄이 되어 저녁 작업의 계획 줄 같은
    다른 기록을 밀어냈다 — 지우지 않고 묶는다. 시각 없는 줄은 건너뛴다."""
    out = []
    rows = [hb for hb in (heartbeats or []) if isinstance(hb, dict) and hb.get('ts')]
    for hb in rows:
        key = (hb.get('status'), hb.get('detail'))
        if out and (out[-1]['status'], out[-1]['detail']) == key:
            out[-1]['first'] = str(hb['ts'])
            out[-1]['n'] += 1
        else:
            out.append(dict(ts=str(hb['ts']), first=str(hb['ts']), n=1, status=hb.get('status'), detail=hb.get('detail'), more=False))
    if out and window and len(rows) >= window:
        out[-1]['more'] = True
    return out


def _beat_line(b):
    txt = f"워커 {b.get('status') or ''}" + (f" · {b.get('detail')}" if b.get('detail') else '')
    if b['n'] > 1:
        f, t = str(b['first']), str(b['ts'])
        when = f[11:16] if f[:10] == t[:10] else f[5:16].replace('T', ' ')
        txt += f" (같은 기록 {b['n']}번{' 이상' if b.get('more') else ''} · {when}부터)"
    return txt


def funnel_intents(intents, judgment_day, trade_day):
    """깔때기의 주문·체결 칸이 셀 주문 (라운드 524) → (주문 목록, 매수일, 오늘 낸 다른 판정의 매수 주문 목록).

    깔때기의 계획 칸은 판정일 J 의 계획인데 주문 칸은 달력 '오늘'의 주문을 셌다(라운드 491). 장중엔 J 가 전 거래일이라 둘이 같은 날을
    가리키지만, 그날 봉이 확정돼 J 가 오늘로 넘어간 저녁엔 계획 칸은 내일 살 계획을, 주문 칸은 오늘 낸(어제 판정의) 주문을 세어
    *'실주문 자격 0 → 주문 냄 1'* 이 한 줄에 섰다(2026-10-13 22:34 실측). 주문 칸은 J 의 계획이 사는 날(`exec_day_of(J)`)의 주문을 센다 —
    장중엔 종전과 같은 날이다. 오늘 낸 다른 판정의 매수 주문은 따로 돌려줘 화면이 한 줄로 가리킨다(지우지 않는다)."""
    xd = exec_day_of(judgment_day)
    its = [it for it in (intents or []) if xd and str(it.get('trade_day') or '')[:10] == xd]
    ids = {id(it) for it in its}
    other = [it for it in (intents or []) if it.get('side') == 'buy' and id(it) not in ids
             and str(it.get('trade_day') or '')[:10] == str(trade_day or '')[:10]]
    return its, xd, other


def recent_events(heartbeats=None, nightly=None, acct=None, task=None, limit=6, beats=3, window=None, now=None):
    """최근 사건 몇 줄 — 워커 심박 · 계좌 동기화 · 저녁 작업 끝 · 예약 작업 마지막 실행. 시각 있는 것만, 최근순.
    라운드 495 — 심박은 이어진 같은 기록을 한 줄로 묶어(`collapse_beats`) 그 묶음 `beats` 개까지 싣는다."""
    ev = []
    for b in collapse_beats(heartbeats, window=window)[:beats]:
        ev.append((b['ts'], _beat_line(b)))
    if acct and acct.get('ts'):
        ev.append((str(acct['ts']), '계좌 동기화(잔고 스냅샷)'))
    if nightly and nightly.get('last_end'):
        # 라운드 524 — 기록 줄은 'MM-DD HH:MM:SS'(연도 없음)인데 종전엔 '2000-' 을 붙여 늘 맨 뒤로 갔다(10-13 21:05 끝 줄이 01:04 계좌
        #   동기화 아래). 지금의 연도를 붙이되 앞날이 되면 한 해 전으로(12월 기록을 1월에 읽는 자리) · 시각 구분은 다른 줄과 같은 'T'.
        le = str(nightly['last_end'])
        if len(le) == 14:
            nk = X.kst(now or X.now_kst())
            key = f"{nk.year}-{le[:5]}T{le[6:]}"
            if key > nk.strftime('%Y-%m-%dT%H:%M:%S'):
                key = f"{nk.year - 1}-{le[:5]}T{le[6:]}"
        else:
            key = le
        ev.append((key, f"저녁 작업 끝 · 종료 코드 {nightly.get('worst')}"))
    ev.sort(key=lambda x: x[0], reverse=True)
    return [(ts[5:16].replace('T', ' ') if len(ts) >= 16 else ts, txt) for ts, txt in ev[:limit]]
