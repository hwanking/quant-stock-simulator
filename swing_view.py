# -*- coding: utf-8 -*-
"""
'스윙 자동매매' 칸 (라운드 446) — 관제실이다. **이 화면은 주문을 내지 않는다.** 주문은 따로 도는 워커
(`scripts/run_swing_worker.py`)만 낸다 — 화면이 주문 반복을 돌리면 새로고침·rerun 에 끊긴다.

화면이 하는 일: 상태를 보이고 · 설정(모드·위험 한도·긴급정지·실전 잠금)을 장부에 적고 · 기존 보유를 자동 관리로 넘기고/되돌려
받고 · '연결 확인'(잔고 읽기만)과 '계획·모의 갱신'(증권사 안 부름)을 부른다. 원격 접속(터널·배포)에서는 아무것도 못 바꾼다 —
남의 브라우저가 이 PC 의 주문 설정을 바꾸면 안 된다(§9). 판정·계획 값은 장부에서 **읽기만** 한다(§4).
"""
import datetime as _dt
import json as _json
import os as _os_mod

import broker_kis
import swing_executor as X
import swing_proof as _sp


def _os_exists(p):
    return _os_mod.path.exists(p)
import swing_ledger as L
import swing_risk
import swing_engine as _se

MODE_KO = {'OFF': '꺼짐', 'SHADOW': '기록만', 'PAPER': '모의투자', 'LIVE': '실전'}
MODE_HELP = {
    'OFF': '아무것도 안 합니다.',
    'SHADOW': '그날 계획을 남기고 일봉으로 모의 결과만 냅니다. 증권사에 아무것도 보내지 않습니다.',
    'PAPER': '한국투자 모의투자 서버로 실제 주문 흐름을 돕니다(모의투자 자격증명이 필요합니다).',
    'LIVE': "실계좌에 주문합니다. 아래 네 가지가 모두 통과해야 켜집니다. 주문 방식이 '계획마다 승인'(기본)이면 ② 에서 승인한 계획만 삽니다.",
}
APPROVAL_KO = {'approve': '계획마다 승인', 'auto': '완전 자동'}
STATE_KO = {'PLANNED': '계획', 'RISK_APPROVED': '한도 통과', 'SUBMITTING': '보내는 중', 'BROKER_ACK': '접수',
            'PARTIAL': '일부 체결', 'FILLED': '체결', 'CANCEL_REQUESTED': '취소 요청', 'CANCELLED': '취소',
            'REJECTED': '거절', 'UNKNOWN': '확인 중(다시 보내지 않음)', 'EXPIRED': '만료(당일 주문)'}
OWN_KO = {'READ_ONLY_EXISTING': '기존 보유(자동 매도 안 함)', 'SWING_OPENED': '자동매매가 산 것',
          'USER_ADOPTED': '넘겨받은 것'}
SHADOW_KO = {'waiting': '진입가 대기', 'no_fill': '대기 기간에 안 닿음', 'open': '체결 · 보유 중', 'closed': '끝남',
             'invalid': '계획 불완전'}
EXIT_KO = {'target': '목표', 'stop': '손절', 'expired': '기간 만료'}


def _ts(v):
    """장부 시각(ISO) → 'YYYY-MM-DD HH:MM'. 못 읽으면 받은 글자 그대로(자르지 않는다)."""
    import datetime as _dt
    try:
        return _dt.datetime.fromisoformat(str(v)).strftime('%Y-%m-%d %H:%M')
    except (TypeError, ValueError):
        return str(v or '—')


def _won(v):
    try:
        return f'{float(v):,.0f}원'
    except (TypeError, ValueError):
        return '—'


def _pct(v):
    try:
        return f'{float(v):+.2f}%'
    except (TypeError, ValueError):
        return '—'


def facts_lines():
    """먼저 알아 둘 사실 — 수는 산출물에서 읽는다(손으로 안 적는다). 못 읽은 조각은 뺀다(§3)."""
    out = ['이 엔진의 매수권 신호에는 비용을 빼면 실전에서 재현되는 우위가 없습니다. 자동매매는 그 판단을 실행할 뿐 '
           '판단을 더 낫게 만들지 않습니다.']
    try:
        import proof
        rl = proof.reco_line(proof.load_scorecard())
        if rl:
            out.append(rl)
    except Exception:                                          # noqa: BLE001
        pass
    out.append('그래서 실전 모드를 켜도 추천이 없는 날에는 아무것도 사지 않습니다.')
    out.append('손절·1차 목표 매도는 증권사에 미리 걸어 두는 주문이 아니라 워커가 장중에 가격을 보고 그때 냅니다 — 워커가 멈추면 '
               '보호 매도도 멈춥니다(장이 열려 있는데 오늘 워커 기록이 없으면 이 칸 맨 위에 경고가 뜹니다).')
    try:
        import entry_facts
        out.append('이 칸이 실행하는 계획(진입가 지정가 · 1차 목표 · 손절 · 기간)의 지금까지 실측 — ' + entry_facts.line())
    except Exception:                                          # noqa: BLE001
        pass
    return out


def plan_status(p, today_day, held=False):
    """오늘 이 계획이 어디에 있나 — 사실만(판정 낱말 없음 · 라운드 450). 대기 창은 계약의 진입 대기 거래일(연구 산출물)이다."""
    if held:
        return '보유 중(자동 관리)'
    if not p.get('live_ok'):
        return '실주문 없음'
    if not today_day or not p.get('data_day'):
        return '—'
    wb = p.get('wait_bars')
    try:
        waited = X.trading_days_between(p['data_day'], today_day)
    except (TypeError, ValueError):
        return '—'
    if waited < 1:
        return '판정일 — 다음 거래일부터 지정가 주문'
    if not wb:
        return f'{waited}거래일 지남 · 대기 기간을 못 읽어 사지 않습니다'
    if waited <= int(wb):
        return f'진입 대기 {waited}/{int(wb)}거래일째 — 지정가가 닿으면 체결'
    return f'대기 기간({int(wb)}거래일) 지남 — 더 안 삽니다'


def _verdict_of(p):
    v = p.get('verdict')
    if isinstance(v, dict):
        return v
    try:
        return _json.loads(v) if v else {}
    except (TypeError, ValueError):
        return {}


def size_preview(p, account, limits, cost_pct):
    """계획 한 줄의 수량 미리보기 — 워커와 **같은 함수**(`swing_risk.size`)로 마지막으로 읽은 계좌와 지금 한도에서 센다(§4).
    자격이 없거나 계좌·한도가 없으면 None. 워커는 주문 때 잔고·주문 가능 금액·대기 주문을 다시 읽어 센다 — 이것은 미리보기다."""
    if not p.get('live_ok') or not account or not limits:
        return None
    sz = swing_risk.size(p.get('entry'), p.get('stop'), account, limits, cost_pct)
    q = int(sz.get('qty') or 0)
    after = None
    try:
        eq, stock = account.get('total_eval'), account.get('stock_eval')
        if q and eq and stock is not None:
            after = (float(stock) + q * float(p['entry'])) / float(eq) * 100.0
    except (TypeError, ValueError, ZeroDivisionError):
        after = None
    return dict(qty=q, amount=(q * float(p['entry']) if q else 0.0), planned_loss=(sz.get('planned_loss') if q else None),
                binding=sz.get('binding'), reason=sz.get('reason') or '', exposure_after_pct=after)


def _fail_label():
    try:
        from verdict_core import fail_label
        return fail_label
    except Exception:                                          # noqa: BLE001
        return lambda n: f"'{n}' 미충족"


def plan_rows(c, today_day=None, account=None, limits=None, cost_pct=None, held=(), approval_on=False, approved=None):
    """가장 최근 판정일의 계획 + 모의 결과 — 표 한 줄씩. 라운드 450: 오늘 상태 · 중앙 판정 조건(통과 수와 미충족 전부) · 수량 미리보기."""
    ps = L.plans(c)
    if not ps:
        return None, []
    day = ps[0]['data_day']
    sh = L.shadow_latest(c)
    fl = _fail_label()
    rows = []
    for p in [x for x in ps if x['data_day'] == day]:
        s = sh.get(p['plan_id']) or {}
        res = SHADOW_KO.get(s.get('status'), '아직 안 굴림')
        if s.get('status') == 'closed':
            res += f" · {EXIT_KO.get(s.get('exit_status'), s.get('exit_status'))} {_pct(s.get('net_pct'))}(비용 뺀)"
        v = _verdict_of(p)
        failed, n_ck = v.get('failed'), v.get('checks_n')
        if isinstance(failed, list) and n_ck:
            cond = (f'{int(n_ck) - len(failed)}/{int(n_ck)} 통과'
                    + ((' · 미충족: ' + ' · '.join(fl(x) for x in failed)) if failed else ' · 미충족 없음'))
        else:
            cond = '— (이 계획에는 조건 기록이 없습니다)'
        sz = size_preview(p, account, limits, cost_pct)
        if sz is None:
            qty_txt, loss_txt = '—', '—'
        elif sz['qty'] < 1:
            qty_txt, loss_txt = f"0주 — {sz['reason']}", '—'
        else:
            qty_txt = f"{sz['qty']}주 · {_won(sz['amount'])} (정한 제한: {sz['binding']})"
            loss_txt = _won(sz['planned_loss']) + (f" · 매수 뒤 주식 비중 {sz['exposure_after_pct']:.1f}%"
                                                  if sz['exposure_after_pct'] is not None else '')
        status = plan_status(p, today_day, held=p['code'] in (held or ()))
        if approval_on and p['live_ok'] and p['code'] not in (held or ()):
            # 라운드 451 — 실전 승인형이면 승인 여부가 오늘 상태 앞에 온다(승인 전이면 워커가 사지 않는다)
            status = ('승인됨 · ' if p['plan_id'] in (approved or set()) else '승인 전 — 사지 않습니다 · ') + status
        rows.append({'종목': f"{p.get('name') or ''} ({p['code']})", '실주문 자격': '예' if p['live_ok'] else '아니오',
                     '오늘 상태': status,
                     '중앙 판정 조건': cond,
                     '진입가(지정가)': _won(p['entry']), '1차 목표': _won(p['target']), '손절': _won(p['stop']),
                     '대기·보유(거래일)': f"{p.get('wait_bars') or '—'} · {p.get('horizon') or '—'}",
                     '수량 미리보기': qty_txt, '손절 시 손실(손절가 체결 가정)': loss_txt,
                     '막은 사유': p.get('block_reason') or '—', '연구 모의(일봉)': res})
    return day, rows


def zero_day_line(c, day):
    """그날 계획에 실주문 자격이 하나도 없을 때 — 가장 많이 막은 조건 한 줄(규칙은 `ui_kit.top_blocker` 한 곳 · 수만). 아니면 None."""
    ps = [p for p in L.plans(c) if p['data_day'] == day] if day else []
    if not ps or any(p.get('live_ok') for p in ps):
        return None
    import ui_kit as _uk
    top = _uk.top_blocker([_verdict_of(p).get('failed') for p in ps])
    head = f'오늘 후보 {len(ps)}개 중 실주문 자격 0 — '
    if not top:
        return head + '조건 기록이 있는 계획이 없어 어느 조건이 막았는지 세지 못했습니다(막은 사유는 표의 칸).'
    fl = _fail_label()
    return (head + f'가장 많이 막은 조건은 {fl(top[0])}입니다 ({top[1]}/{top[2]}개 · 조건 기록이 있는 계획 기준). '
            '조건별로 세어 본 것이고, 어느 조건을 풀어야 한다는 뜻이 아닙니다.')


def holdings_diff(acct_positions, app_positions):
    """한국투자 잔고 보유 vs 앱 보유종목(.portfolio/positions.json) — 종목코드로 맞춰 사실만 적는다(라운드 450 · 덮어쓰지 않는다).
    평단은 원 단위 소수 둘째 자리까지 같으면 같다고 본다(표시 정밀도이지 판정 문턱이 아니다). 수량 0 인 계좌 행은 뺀다."""
    a = {}
    for p in acct_positions or []:
        if p.get('qty') and p.get('code'):
            a[_se.code6(p['code'])] = p
    b = {}
    for q in app_positions or []:
        code = _se.code6(getattr(q, 'ticker', None))
        if code:
            b[code] = q
    rows = []
    for code in sorted(set(a) | set(b)):
        pa, pb = a.get(code), b.get(code)
        qa = int(pa['qty']) if pa else None
        qb = getattr(pb, 'quantity', None) if pb else None
        aa = pa.get('avg_price') if pa else None
        ab = getattr(pb, 'average_buy_price', None) if pb else None
        if pa and pb:
            same_q = qb is not None and float(qb) == float(qa)
            same_a = aa is not None and ab is not None and round(float(aa), 2) == round(float(ab), 2)
            status = '같음' if (same_q and same_a) else ' · '.join(
                s for s, bad in (('수량 다름', not same_q), ('평단 다름', not same_a)) if bad)
        elif pa:
            status = '계좌에만(앱 보유종목에 없음)'
        else:
            status = '앱에만(계좌에 없음 — 팔았거나 다른 계좌)'
        rows.append(dict(code=code, name=((pa or {}).get('name') or getattr(pb, 'stock_name', None) or ''),
                         acct_qty=qa, app_qty=qb, acct_avg=aa, app_avg=ab, status=status))
    return rows


def protection_line(hb, now, managed_n, mode=None):
    """보호 매도는 워커가 낸다 — 장이 열려 있는데 **오늘 장 시작 뒤** 워커 기록이 없으면 그 사실을 적는다(라운드 450).
    문턱 없음 — 기준은 그날 장 시작 시각 한 곳(`bitemporal_engine.session_times`). 장 밖이거나 기록이 장 시작 뒤면 None.
    모드가 '꺼짐'이고 관리 중인 종목도 없으면 워커가 안 도는 것이 설계라 None(관리 중인 종목이 있으면 모드와 무관하게 적는다)."""
    if not managed_n and (mode or 'OFF') == 'OFF':
        return None
    if not X.session_open(now):
        return None
    n = X.kst(now)
    op, _cl = X._session_times(n.date())
    start = n.replace(hour=op.hour, minute=op.minute, second=0, microsecond=0)
    ts = None
    if hb and hb.get('ts'):
        try:
            ts = X.kst(_dt.datetime.fromisoformat(str(hb['ts'])))
        except ValueError:
            ts = None
    if ts is not None and ts >= start:
        return None
    who = (f'자동 관리 중 {managed_n}종목의 손절·1차 목표 매도가 서 있습니다' if managed_n
           else '지금 자동 관리 중인 종목은 없습니다(살 계획이 있어도 사지 않습니다)')
    last = f"마지막 기록 {_ts(hb['ts'])}" if hb and hb.get('ts') else '기록이 한 번도 없습니다'
    return (f"장이 열려 있는데 오늘 장 시작({op.strftime('%H:%M')}) 뒤 워커 기록이 없습니다 — {who} · {last}. "
            "워커 창을 켜세요: python scripts/run_swing_worker.py --loop 60 (평일 아침마다 혼자 돌게 하려면 "
            "scripts/register_swing_worker_task.ps1 을 한 번 돌립니다)")


def shadow_summary(c):
    """끝난 모의 결과 — 수만(판정 낱말 없음). 없으면 None."""
    done = [s for s in L.shadow_latest(c).values() if s.get('status') == 'closed' and s.get('net_pct') is not None]
    if not done:
        return None
    v = sorted(float(s['net_pct']) for s in done)
    mid = v[len(v) // 2] if len(v) % 2 else (v[len(v) // 2 - 1] + v[len(v) // 2]) / 2
    return dict(n=len(v), mean=sum(v) / len(v), median=mid,
                target=sum(1 for s in done if s.get('exit_status') == 'target'),
                stop=sum(1 for s in done if s.get('exit_status') == 'stop'))


def render(st, uk, *, allow_read, allow_write, hold_levels=None, report=None, anchor_day=None, md_safe=None,
           resolve_market=None):
    """칸 전체. hold_levels(code) → (손절선, 1차 매도가) 또는 None — 관심종목 표와 같은 함수로 화면이 만든다.
    resolve_market(code) → 'KOSPI'·'KOSDAQ'·None — 계좌 보유를 앱 보유종목으로 가져올 때 시장 접미사를 정한다(CSV 가져오기와 같은 길)."""
    md = md_safe or (lambda s: s)
    st.caption('가늠이 판단하고 · 한국투자증권이 실행하고 · 결과는 같은 채점 규칙으로 남깁니다. 이 칸은 관제실이고, '
               '주문은 따로 도는 워커만 냅니다. 분석 화면으로 돌아가려면 맨 위 탭에서 \'가늠 분석\'을 고르세요.')
    with st.container(border=True):
        st.markdown('**먼저 알아 두실 것**')
        for ln in facts_lines():
            st.caption(md(ln))
    if not allow_read:
        st.info('이 칸은 이 PC 에서 직접 연 화면에서만 씁니다. 원격으로 연 화면에서는 주문 설정을 보거나 바꿀 수 없습니다.')
        return
    try:
        c = L.connect(readonly=not allow_write)
    except Exception as e:                                     # noqa: BLE001
        st.warning(f'장부를 못 열었습니다 — {type(e).__name__}: {e}')
        return
    if c is None:
        st.caption('아직 장부가 없습니다 — 쓰기가 꺼진 화면이라 만들지 않았습니다(이 PC 에서 직접 연 화면에서 모드를 정하면 생깁니다).')
        return
    try:
        _render_body(st, uk, c, allow_write, hold_levels, report, anchor_day, md, resolve_market)
    finally:
        c.close()


def _render_body(st, uk, c, allow_write, hold_levels, report, anchor_day, md, resolve_market=None):
    stt = L.settings(c)
    mode = L.mode_of(c)
    cfg = broker_kis.load_config()
    hb = L.last_heartbeat(c)
    plans_today = [p for p in L.plans(c) if p['data_day'] == str(anchor_day)] if anchor_day else []
    managed = L.managed_open(c)
    cols = st.columns(5)
    cols[0].metric('한국투자 연결', '정보 있음' if not cfg.get('missing') and not cfg.get('problems') else '정보 없음')
    cols[1].metric('운용 모드', MODE_KO.get(mode, mode))
    cols[2].metric('워커 마지막 기록', (_ts(hb['ts']) + f" · {hb['status']}") if hb else '기록 없음')
    cols[3].metric('긴급정지', '켜짐' if stt.get('kill_switch') else '꺼짐')
    cols[4].metric('오늘 계획 · 실주문 자격', f"{len(plans_today)} · {sum(1 for p in plans_today if p['live_ok'])}")
    st.caption(md(f"연결 정보: {broker_kis.config_summary(cfg)}" + (' · ' + ' · '.join(cfg['problems']) if cfg.get('problems') else '')
                  + f" · 자동 관리 중 {len(managed)}종목"))
    # 워커가 보호(손절·취소·계좌 맞추기)에 문제를 적었으면 조용히 'ok' 로 덮지 않고 그대로 띄운다
    if hb and hb.get('status') in ('warn', 'broker_fail', 'blocked'):
        st.warning(md(f"워커 마지막 바퀴({_ts(hb['ts'])}) — {hb.get('detail') or hb['status']}"))
    _pl450 = protection_line(hb, X.now_kst(), len(managed), mode=mode)
    if _pl450:
        st.warning(md(_pl450))

    # ① 계좌
    acct = L.last_account(c)
    with st.expander('① 한국투자 계좌 (마지막으로 읽은 것)', expanded=False):
        if not acct:
            st.caption('아직 계좌를 읽은 적이 없습니다 — 아래 설정의 \'연결 확인\'을 누르거나, 모의투자·실전 모드에서 워커가 돌면 채워집니다.')
        else:
            pos = L.positions(c)
            st.caption(f"{_ts(acct['ts'])} · {'모의투자' if acct['env'] == 'demo' else '실전'} · "
                       f"예수금 {_won(acct['cash'])} · 총평가 {_won(acct['total_eval'])} · 주식 평가 {_won(acct['stock_eval'])}")
            rows = [{'종목': f"{p.get('name') or ''} ({p['code']})", '수량': p['qty'], '평단': _won(p.get('avg_price')),
                     '현재가': _won(p.get('price')), '평가손익률': _pct(p.get('pnl_pct')),
                     '관리': OWN_KO.get((pos.get(p['code']) or {}).get('ownership'), '기존 보유(자동 매도 안 함)')
                     if not (pos.get(p['code']) or {}).get('managed') else OWN_KO.get(pos[p['code']]['ownership'])}
                    for p in acct['positions']]
            if rows:
                st.dataframe(rows, hide_index=True, width='stretch')
            # 라운드 450 — 앱 보유종목과 견주기(사실만 · 덮어쓰지 않는다 · 옮기는 것은 아래 버튼)
            try:
                import portfolio as _pf450
                _app450, _ = _pf450.load_positions()
            except Exception:                                  # noqa: BLE001
                _app450 = None
            if _app450 is None:
                st.caption('앱 보유종목 파일을 읽지 못해 견주지 못했습니다.')
            else:
                _diff450 = holdings_diff(acct['positions'], _app450)
                _same450 = sum(1 for r in _diff450 if r['status'] == '같음')
                st.caption(f"앱 보유종목(.portfolio/positions.json)과 견줌 — {len(_diff450)}종목 중 같음 {_same450} · "
                           f"다름·한쪽에만 {len(_diff450) - _same450}. 이 표는 아무것도 덮어쓰지 않습니다.")
                if _diff450:
                    st.dataframe([{'종목': f"{r['name']} ({r['code']})",
                                   '계좌 수량': r['acct_qty'] if r['acct_qty'] is not None else '—',
                                   '앱 수량': (f"{r['app_qty']:g}" if r['app_qty'] is not None else '—'),
                                   '계좌 평단': _won(r['acct_avg']), '앱 평단': _won(r['app_avg']), '상태': r['status']}
                                  for r in _diff450], hide_index=True, width='stretch')
            # 라운드 449 — 계좌 보유를 앱의 '내 보유종목'으로 가져온다(CSV 가져오기와 같은 함수 · 이 PC 에만 저장 · 되돌리기 한 번)
            if allow_write and acct['positions']:
                st.caption('아래 버튼은 이 계좌의 보유를 앱의 \'내 보유종목\'(.portfolio/positions.json · 이 PC 에만)으로 옮깁니다. 지금 보유종목은 '
                           '덮이고, 바로 아래 \'되돌리기\'로 한 번 되돌릴 수 있습니다. 관심종목 표의 매입가·수량은 건드리지 않습니다.')
                ca, cb = st.columns(2)
                if ca.button('계좌 보유를 앱 보유종목으로 가져오기', key='sw_sync_pos'):
                    import portfolio as _pf
                    _rows = broker_kis.balance_to_rows(acct)
                    _pos, _warns = _pf.rows_to_positions(_rows, source_type='kis_sync', resolve_market=resolve_market)
                    st.session_state['sw_pos_before'] = list(st.session_state.get('positions') or [])
                    st.session_state['positions'] = _pos
                    try:
                        _pf.save_positions(_pos)
                        import datetime as _dt
                        st.session_state['positions_saved_at'] = _dt.datetime.now().isoformat(timespec='seconds')
                        st.session_state['sw_flash'] = f'{len(_pos)}종목을 앱 보유종목으로 가져와 저장했습니다' + \
                            (f' · 제외 {len(_warns)}건(사유는 아래)' if _warns else '')
                        st.session_state['sw_sync_warns'] = _warns
                    except Exception as e:                     # noqa: BLE001
                        st.session_state['sw_flash'] = f'{len(_pos)}종목을 가져왔지만 저장은 실패했습니다 — {type(e).__name__}: {e}'
                    st.rerun()
                if 'sw_pos_before' in st.session_state and cb.button('되돌리기(가져오기 전으로)', key='sw_sync_undo'):
                    import portfolio as _pf
                    _prev = st.session_state.pop('sw_pos_before')
                    st.session_state['positions'] = _prev
                    try:
                        _pf.save_positions(_prev)
                        st.session_state['sw_flash'] = f'가져오기 전 보유종목 {len(_prev)}종목으로 되돌렸습니다'
                    except Exception as e:                     # noqa: BLE001
                        st.session_state['sw_flash'] = f'되돌렸지만 저장은 실패했습니다 — {type(e).__name__}: {e}'
                    st.rerun()
                for _w in st.session_state.get('sw_sync_warns') or []:
                    st.caption(md(_w))

    # ② 오늘의 계획 (라운드 450 — 오늘 상태 · 조건 전부 · 수량 미리보기 · 자격 0 인 날의 가장 많이 막은 조건)
    try:
        from verdict_core import COST_PCT as _cost450
    except Exception:                                          # noqa: BLE001
        _cost450 = None
    _appr451 = (mode == 'LIVE' and X.approval_of(stt) == 'approve')
    _apset451 = X.approved_plans(stt)
    day, rows = plan_rows(c, today_day=anchor_day, account=acct, limits=(stt.get('limits') or None), cost_pct=_cost450,
                          held=set(managed), approval_on=_appr451, approved=_apset451)
    with st.expander('② 오늘의 스윙 계획', expanded=True):
        if not rows:
            st.caption('아직 계획이 없습니다 — 모드를 \'기록만\' 이상으로 두고 \'계획·모의 갱신\'을 누르거나 워커가 돌면 그날 개장 전 '
                       '리포트에서 만들어집니다.')
        else:
            st.caption(f'판정일 {day} 의 개장 전 후보 — 실주문 자격은 중앙 판정이 추천(조건 11개 전부 통과)일 때만 \'예\'입니다. '
                       '자격이 없는 후보도 같은 계약으로 일봉 모의 결과를 남깁니다(사지 않은 경우의 성적 · 증권사와 무관한 연구 값).')
            _zl450 = zero_day_line(c, day)
            if _zl450:
                st.caption(md(_zl450))
            st.dataframe(rows, hide_index=True, width='stretch')
            if acct and (stt.get('limits') or None):
                st.caption(f"수량 미리보기는 마지막으로 읽은 계좌({_ts(acct['ts'])} · 예수금 {_won(acct['cash'])})와 지금 위험 한도로 "
                           "워커와 같은 함수로 센 것입니다 — 워커는 주문 때 잔고·주문 가능 금액·대기 주문을 다시 읽어 셉니다.")
            else:
                st.caption('수량 미리보기 없음 — 계좌를 읽은 적이 없거나 위험 한도가 비어 있습니다(⑥ 설정).')
            # 라운드 451 — 실전 승인형: 승인은 계획(진입가·손절·목표가 박힌 영수증)에 붙는다. 쓰는 자리는 여기뿐이다.
            if _appr451:
                _live451 = [p for p in L.plans(c) if p['data_day'] == day and p.get('live_ok') and p['code'] not in managed]
                if _live451:
                    st.caption('실전 주문 방식이 \'계획마다 승인\'입니다 — 아래에서 승인한 계획만 워커가 그 계획의 대기 창 안에서 진입가 지정가 '
                               '매수를 냅니다. 승인해도 중앙 판정·위험 한도·긴급정지는 그대로 적용되고, 보호 매도는 승인과 무관합니다.')
                if allow_write:
                    for _p451 in _live451:
                        _pid451 = _p451['plan_id']
                        _ca451, _cb451 = st.columns([4, 1])
                        _ca451.caption(f"{_p451.get('name') or ''} ({_p451['code']}) · 진입 {_won(_p451['entry'])} · 손절 {_won(_p451['stop'])} · "
                                       f"1차 목표 {_won(_p451['target'])} · {'승인됨' if _pid451 in _apset451 else '승인 전'}")
                        if _pid451 in _apset451:
                            if _cb451.button('승인 취소', key=f'sw_unappr_{_pid451}'):
                                L.set_setting(c, 'approved_plans', sorted(_apset451 - {_pid451}))
                                st.rerun()
                        elif _cb451.button('이 계획 승인', key=f'sw_appr_{_pid451}'):
                            L.set_setting(c, 'approved_plans', sorted(_apset451 | {_pid451}))
                            st.rerun()
        ss = shadow_summary(c)
        if ss:
            st.caption(md(f"끝난 모의 {ss['n']}건 — 목표 {ss['target']} · 손절 {ss['stop']} · 기간 만료 "
                          f"{ss['n'] - ss['target'] - ss['stop']} · 비용 뺀 평균 {ss['mean']:+.2f}% · 중앙 {ss['median']:+.2f}%"
                          + (' — 표본이 작아 무엇을 가를 수 있는 수가 아닙니다' if ss['n'] < 30 else '')))

    # ③ 주문·체결 이력
    its = L.intents_with_state(c)
    with st.expander(f'③ 주문·체결 이력 ({len(its)}건)', expanded=False):
        if not its:
            st.caption('아직 주문이 없습니다.')
        else:
            st.dataframe([{'날짜': it['trade_day'], '종목': it['code'], '방향': '매수' if it['side'] == 'buy' else '매도',
                           '이유': {'entry': '진입', 'target': '1차 목표', 'stop': '손절', 'expiry': '기간 만료'}.get(
                               X._base(it.get('reason')), it.get('reason')),
                           '수량': it['qty'], '가격': _won(it['price']) if it['price'] else '시장가',
                           '상태': STATE_KO.get(it['state'], it['state']), '체결': it.get('filled_qty') or 0,
                           '모드': MODE_KO.get(it['mode'], it['mode']), '메모': (it.get('detail') or '')}
                          for it in reversed(its[-200:])], hide_index=True, width='stretch')

    # ④ 자동 관리
    with st.expander(f'④ 자동 관리 중 {len(managed)}종목 · 기존 보유 넘기기', expanded=False):
        st.caption('자동 매도는 자동매매가 산 종목과 직접 넘긴 종목만 합니다. 계좌의 기존 보유는 넘기기 전에는 절대 팔지 않습니다. '
                   '넘긴 종목은 관심종목 표의 손절선·1차 매도가에 닿을 때만 팔고(기간 만료로는 안 팝니다), 손절선 가격에 그대로 '
                   '팔린다는 보장은 없습니다(더 아래에서 팔릴 수 있습니다). 되돌려 받아도 이미 걸린 1차 목표 매도는 워커의 다음 장중 '
                   '바퀴가 취소합니다 — 그 사이 체결될 수 있습니다. 증권사 앱에서 직접 판 수량은 워커가 계좌에 맞춰 관리에서 내립니다.')
        for code, p in managed.items():
            a, b = st.columns([4, 1])
            a.caption(f"{code} · {OWN_KO.get(p['ownership'])} · 수량 {p.get('qty')} · 손절 {_won(p.get('stop'))} · "
                      f"1차 목표 {_won(p.get('target'))}" + (f" · 체결일 {p.get('opened_day')}" if p.get('opened_day') else ''))
            if p['ownership'] == 'USER_ADOPTED' and allow_write and b.button('되돌려 받기', key=f'sw_rel_{code}'):
                X.release(c, code)
                st.rerun()
        if acct and allow_write and hold_levels:
            cand = [p for p in acct['positions'] if not (L.positions(c).get(p['code']) or {}).get('managed')]
            if cand:
                pick = st.selectbox('넘길 기존 보유', [f"{p.get('name') or ''} ({p['code']})" for p in cand], index=None,
                                    placeholder='고르세요', key='sw_adopt_pick')
                if pick:
                    p = cand[[f"{x.get('name') or ''} ({x['code']})" for x in cand].index(pick)]
                    lv = hold_levels(p['code'])
                    if not lv:
                        st.caption('이 종목은 관심종목 표에 손절선·1차 매도가가 없어 넘길 수 없습니다 — 관심종목에 담고 잰 뒤 넘기세요.')
                    else:
                        st.caption(f"넘기면 손절 {_won(lv[0])} 아래에서 시장가로 · 1차 목표 {_won(lv[1])} 에 지정가로 팝니다 "
                                   f"(수량 {p['qty']}).")
                        ok = st.checkbox('이 종목을 자동 관리로 넘기는 데 동의합니다', key='sw_adopt_ok')
                        if ok and st.button('자동 관리로 넘기기', key='sw_adopt_go'):
                            try:
                                X.adopt(c, p['code'], p['qty'], lv[1], lv[0], by_user=True)
                                st.rerun()
                            except L.LedgerError as e:
                                st.warning(str(e))

    # ⑤ 결과 영수증 — 계획 vs 실제 (라운드 447 · 장부에서 읽기만 · 종목·수량은 이 PC 화면에서만)
    try:
        from verdict_core import COST_PCT as _cost447
    except Exception:                                          # noqa: BLE001
        _cost447 = None
    _rcpts = _sp.receipts(c, _cost447)
    _closed = [r for r in _rcpts if r.get('closed_day')]
    with st.expander(f'⑤ 결과 영수증 — 계획 vs 실제 체결 ({len(_closed)}건 닫힘 · {sum(1 for r in _rcpts if r.get("open"))}건 보유 중)',
                     expanded=False):
        st.caption('자동매매가 열고 닫은 보유마다 계획 진입가와 실제 평균 체결가, 청산 사유와 계획 청산가 대비 실제 청산가, '
                   f'운영 왕복 비용 {_cost447 if _cost447 is not None else "미상"}% 를 뺀 순수익을 적습니다. 실제 수수료·세금은 증권사에서 읽지 않습니다. '
                   '같은 계획을 일봉으로 굴린 모의 결과(기록만 모드와 같은 채점기)도 옆에 둡니다. 좋고 나쁨은 말하지 않습니다.')
        _ln447 = _sp.summary_line(_sp.summary(_rcpts), _cost447)
        if _ln447:
            st.caption(md(_ln447))
        if _rcpts:
            st.dataframe([{'영수증': r['receipt_id'], '종목': r['code'], '산 날': r.get('opened_day') or '—',
                           '닫은 날': r.get('closed_day') or ('보유 중' if r.get('open') else '—'), '수량': r['qty'],
                           '계획 진입가': _won(r['entry_plan']), '실제 진입가': _won(r['entry_fill']),
                           '진입 슬리피지': _pct(r['slip_entry_pct']),
                           '청산 사유': _sp.EXIT_KO.get(r.get('exit_reason'), r.get('exit_reason') or '—'),
                           '계획 청산가': _won(r['exit_plan']), '실제 청산가': _won(r['exit_fill']),
                           '청산 슬리피지': _pct(r['slip_exit_pct']), '순수익(비용 뺀)': _pct(r['net_pct']),
                           '모의(같은 계획)': _pct(r['shadow_net_pct']), '메모': ' · '.join(r['notes'])}
                          for r in reversed(_rcpts)], hide_index=True, width='stretch')
        else:
            st.caption('아직 자동매매가 열고 닫은 보유가 없습니다.')

    # ⑥ 설정
    with st.expander('⑥ 설정 — 모드 · 위험 한도 · 긴급정지 · 연결 확인', expanded=False):
        if not allow_write:
            st.caption('쓰기가 꺼진 화면이라 설정을 바꿀 수 없습니다.')
        _settings(st, c, stt, mode, cfg, allow_write, report, anchor_day, md)

    with st.expander('운영 방법 — 자격증명 · 연결 확인 · 워커', expanded=False):
        st.markdown(md(
            "1. 한국투자 API 포탈에서 앱 키를 받습니다. **채팅·코드·저장소에 붙이지 마세요.** 이미 어딘가에 붙였다면 재발급하세요.\n"
            "2. 이 PC 의 사용자 환경변수(또는 저장소 밖 `~/.gaeum/kis.env` 파일)에 다섯 칸을 넣습니다 — "
            "`KIS_ENV`(demo 또는 real) · `KIS_APP_KEY` · `KIS_APP_SECRET` · `KIS_ACCOUNT_NO`(계좌 앞 8자리) · "
            "`KIS_ACCOUNT_PRODUCT_CODE`(뒤 2자리). 앱을 다시 띄워야 읽힙니다.\n"
            "3. 아래 설정의 **'연결 확인'** 을 먼저 누릅니다(잔고만 읽고 주문은 안 합니다). 이 프로그램은 한국투자 서버에 "
            "실제로 닿아 본 적이 없어서, 첫 연결이 곧 첫 시험입니다. 모의투자 자격증명으로 모의투자 모드를 먼저 돌려 볼 수도 "
            "있습니다(건너뛰어도 실전은 켜집니다).\n"
            "4. 실전: 실전 자격증명 · 위험 한도 여섯 · 잠금 해제 문장 · 긴급정지 꺼짐이 모두 맞아야 켜집니다. 처음에는 거래당 "
            "최대 손실을 작게 두기를 권합니다. 워커는 평일 아침 Windows 작업(`gaeum-swing-worker` · "
            "`scripts/register_swing_worker_task.ps1` 로 한 번 등록)이 정규장 마감까지 돌리고, 직접 켜려면 "
            "`python scripts/run_swing_worker.py --loop 60` 입니다. '③ 주문·체결 이력'에서 계획 · 접수 · 체결 · 손절·목표가 계약대로 "
            "움직이는지 봅니다.\n"
            "5. 되돌리기: 모드를 '꺼짐'으로 두고 워커 창을 닫으면 새 주문은 나가지 않습니다. 이미 낸 주문은 증권사 앱에서 취소합니다."))


def _settings(st, c, stt, mode, cfg, allow_write, report, anchor_day, md):
    modes = list(L.MODES)
    new_mode = st.radio('운용 모드', modes, index=modes.index(mode), format_func=lambda m: MODE_KO[m], horizontal=True,
                        key='sw_mode', disabled=not allow_write)
    st.caption(MODE_HELP[new_mode])
    rd = X.live_readiness(cfg, stt)
    if new_mode == 'LIVE':
        for name, ok, why in rd:
            st.caption(md(f"{'통과' if ok else '미달'} — {name}: {why}"))
    if allow_write and new_mode != mode:
        blocks = []
        if new_mode in X.MODE_ENV:
            blocks = [b for b in X.broker_gate(new_mode, cfg, stt) if '잠금' not in b]
        if new_mode == 'LIVE' and not all(ok for _n, ok, _w in rd):
            _miss = [n for n, ok, _w in rd if not ok]
            st.warning(md('실전으로 바꾸지 않았습니다 — 미달 ' + ' · '.join(_miss) + '. '
                          + ('연결 정보는 아래 \'한국투자 연결 정보\'에 넣고, ' if '한국투자 실전 자격증명' in _miss else '')
                          + ('위험 한도는 아래 \'위험 한도\' 여섯 칸을 채워 저장하고, ' if '위험 한도 여섯' in _miss else '')
                          + ('잠금은 아래 \'실전 잠금\'에 문장을 입력해 풀고, ' if '실전 잠금 해제' in _miss else '')
                          + ('긴급정지는 아래 토글을 끄고, ' if '긴급정지 꺼짐' in _miss else '')
                          + '다시 고르세요.'))
        elif blocks:
            st.warning('이 모드로 바꾸지 않았습니다 — ' + ' · '.join(blocks))
        elif st.button(f"'{MODE_KO[new_mode]}' 로 바꾸기", key='sw_mode_go'):
            L.set_setting(c, 'mode', new_mode)
            st.rerun()
    st.markdown('**실전 주문 방식**')
    _ap451 = X.approval_of(stt)
    st.caption("'계획마다 승인'(기본)은 ② 에서 승인한 계획만 삽니다 · '완전 자동'은 실주문 자격이 있는 계획을 워커가 그대로 삽니다. "
               "모의투자·기록만 모드에는 적용되지 않고, 보호 매도(손절·1차 목표)는 어느 쪽이든 승인 없이 냅니다.")
    if allow_write:
        _ap_new451 = st.radio('실전 주문 방식', list(X.APPROVAL_MODES), index=list(X.APPROVAL_MODES).index(_ap451),
                              format_func=lambda v: APPROVAL_KO[v], horizontal=True, key='sw_approval')
        if _ap_new451 != _ap451:
            L.set_setting(c, 'order_approval', _ap_new451)
            st.rerun()
    else:
        st.caption('지금: ' + APPROVAL_KO[_ap451])
    st.markdown('**실전 잠금**')
    if stt.get('live_unlock') == X.LIVE_UNLOCK_PHRASE:
        st.caption('풀려 있습니다.')
        if allow_write and st.button('다시 잠그기', key='sw_lock'):
            L.set_setting(c, 'live_unlock', None)
            if mode == 'LIVE':
                L.set_setting(c, 'mode', 'OFF')
            st.rerun()
    elif allow_write:
        ph = st.text_input(f"풀려면 다음 문장을 그대로 입력하세요: {X.LIVE_UNLOCK_PHRASE}", key='sw_unlock')
        if ph and ph.strip() == X.LIVE_UNLOCK_PHRASE and st.button('잠금 풀기', key='sw_unlock_go'):
            L.set_setting(c, 'live_unlock', X.LIVE_UNLOCK_PHRASE)
            st.rerun()
    st.markdown('**긴급정지**')
    st.caption('켜면 새 매수를 안 내고 열린 매수 주문을 취소합니다. 이미 관리 중인 종목의 손절·목표 매도는 계속합니다.')
    if allow_write:
        ks = st.toggle('긴급정지', value=bool(stt.get('kill_switch')), key='sw_kill')
        if ks != bool(stt.get('kill_switch')):
            L.set_setting(c, 'kill_switch', bool(ks))
            st.rerun()
    st.markdown('**위험 한도** — 직접 정합니다(기본값이 없습니다 · 비워 두면 모의투자·실전 주문이 막힙니다)')
    lim = dict(stt.get('limits') or {})
    if allow_write:
        with st.form('sw_limits'):
            vals = {}
            for k, label, unit in swing_risk.LIMITS:
                cur = lim.get(k)
                vals[k] = st.text_input(f'{label} ({unit})', value='' if cur is None else f'{cur:g}', key=f'sw_lim_{k}')
            if st.form_submit_button('위험 한도 저장'):
                newlim = {k: (v.strip() or None) for k, v in vals.items()}
                _v, missing, problems = swing_risk.validate(newlim)
                L.set_setting(c, 'limits', newlim)
                if missing or problems:
                    st.warning('저장했지만 아직 주문이 막힙니다 — ' + ', '.join(missing + problems))
                st.rerun()
    # 라운드 449 — 연결 정보는 사용자가 **여기서 직접** 넣는다(가려진 칸). 저장은 저장소 밖 ~/.gaeum/kis.env 에만 · 값은 화면·로그에
    #   되비치지 않는다(요약은 가린 글자). 환경변수로 이미 넣었으면 그쪽이 먼저다(파일은 빈 칸만 채운다).
    st.markdown('**한국투자 연결 정보**')
    _src = (cfg or {}).get('source') or {}
    st.caption(md('지금: ' + broker_kis.config_summary(cfg)
                  + (' · 출처 ' + ', '.join(f"{k.replace('KIS_', '')}={'환경변수' if v == 'env' else '파일'}" for k, v in _src.items())
                     if _src else '')
                  + f' · 파일 자리 {broker_kis.SECRET_FILE}(저장소 밖 · 커밋·백업 안 됨)'))
    if allow_write:
        with st.form('sw_cred'):
            _env_pick = st.selectbox('계좌 종류', ['real', 'demo'], format_func=lambda v: '실전' if v == 'real' else '모의투자',
                                     key='sw_cred_env')
            _k = st.text_input('앱 키 (APP Key)', type='password', key='sw_cred_key')
            _s = st.text_input('앱 시크릿 (APP Secret)', type='password', key='sw_cred_secret')
            _a = st.text_input('계좌번호 (10자리 또는 8자리-2자리)', type='password', key='sw_cred_acct')
            if st.form_submit_button('연결 정보 저장 (이 PC 의 저장소 밖 파일에만)'):
                try:
                    _acct = str(_a or '').replace('-', '').strip()
                    _cfg2 = broker_kis.save_config({'KIS_ENV': _env_pick, 'KIS_APP_KEY': _k, 'KIS_APP_SECRET': _s,
                                                    'KIS_ACCOUNT_NO': _acct[:8] if len(_acct) == 10 else _acct,
                                                    'KIS_ACCOUNT_PRODUCT_CODE': _acct[8:] if len(_acct) == 10 else ''})
                    st.session_state['sw_flash'] = '연결 정보를 저장했습니다 — ' + broker_kis.config_summary(_cfg2) + \
                        ((' · ' + ' · '.join(_cfg2['problems'])) if _cfg2.get('problems') else '') + \
                        " · 이제 '연결 확인'을 누르세요(앱을 다시 띄우지 않아도 됩니다)"
                except broker_kis.BrokerError as e:
                    st.session_state['sw_flash'] = f'저장하지 않았습니다 — {e}'
                for _kk in ('sw_cred_key', 'sw_cred_secret', 'sw_cred_acct'):
                    st.session_state.pop(_kk, None)          # 입력값을 세션에 남기지 않는다
                st.rerun()
        if _os_exists(broker_kis.SECRET_FILE) and st.button('저장된 연결 정보 지우기', key='sw_cred_del'):
            broker_kis.delete_config()
            st.session_state['sw_flash'] = '저장된 연결 정보 파일을 지웠습니다(환경변수는 사용자가 지웁니다)'
            st.rerun()
    st.markdown('**연결 확인 · 계획 갱신**')
    st.caption("'연결 확인'은 토큰을 받고 잔고를 한 번 읽습니다(주문은 안 합니다). '계획·모의 갱신'은 증권사를 부르지 않고 그날 "
               "리포트에서 계획을 남기고 일봉으로 모의 결과를 냅니다.")
    a, b = st.columns(2)
    if allow_write and a.button('연결 확인', key='sw_health'):
        try:
            br = broker_kis.KisBroker(cfg)
            hc = br.health_check()
            if hc['ok']:
                L.account_snapshot(c, br.env, br.get_balance())
                st.success(hc['message'])
            else:
                st.warning(hc['message'])
        except broker_kis.BrokerError as e:
            st.warning(str(e))
    if st.session_state.get('sw_flash'):
        st.success(st.session_state.pop('sw_flash'))
    if allow_write and b.button('계획·모의 갱신', key='sw_refresh'):
        if L.mode_of(c) == 'OFF':
            st.warning("모드가 '꺼짐'이라 아무것도 안 했습니다 — '기록만' 이상으로 바꾸세요.")
        else:
            from verdict_core import COST_PCT
            import bitemporal_engine as be
            eng = be.BitemporalEngine()
            # 화면에서는 주문하지 않는다 — 워커와 같은 함수로 계획과 모의만(증권사 안 부름)
            pn, sn, notes = X.refresh_plans(c, report, anchor_day, lambda code: eng.fetch_daily_bars(f'{code}.KS'), COST_PCT)
            st.session_state['sw_flash'] = (f'새 계획 {pn}건 · 모의 결과 갱신 {sn}건 (주문 없음)'
                                            + (f" · {len(notes)}건 못 굴림" if notes else ''))
            st.rerun()
