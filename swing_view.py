# -*- coding: utf-8 -*-
"""
'스윙 자동매매' 칸 (라운드 446) — 관제실이다. **이 화면은 주문을 내지 않는다.** 주문은 따로 도는 워커
(`scripts/run_swing_worker.py`)만 낸다 — 화면이 주문 반복을 돌리면 새로고침·rerun 에 끊긴다.

화면이 하는 일: 상태를 보이고 · 설정(모드·위험 한도·긴급정지·실전 잠금)을 장부에 적고 · 기존 보유를 자동 관리로 넘기고/되돌려
받고 · '연결 확인'(잔고 읽기만)과 '계획·모의 갱신'(증권사 안 부름)을 부른다. 원격 접속(터널·배포)에서는 아무것도 못 바꾼다 —
남의 브라우저가 이 PC 의 주문 설정을 바꾸면 안 된다(§9). 판정·계획 값은 장부에서 **읽기만** 한다(§4).
"""
import broker_kis
import swing_executor as X
import swing_ledger as L
import swing_risk

MODE_KO = {'OFF': '꺼짐', 'SHADOW': '기록만', 'PAPER': '모의투자', 'LIVE': '실전'}
MODE_HELP = {
    'OFF': '아무것도 안 합니다.',
    'SHADOW': '그날 계획을 남기고 일봉으로 모의 결과만 냅니다. 증권사에 아무것도 보내지 않습니다.',
    'PAPER': '한국투자 모의투자 서버로 실제 주문 흐름을 돕니다(모의투자 자격증명이 필요합니다).',
    'LIVE': '실계좌에 주문합니다. 아래 네 가지가 모두 통과해야 켜집니다.',
}
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
    try:
        import entry_facts
        out.append('이 칸이 실행하는 계획(진입가 지정가 · 1차 목표 · 손절 · 기간)의 지금까지 실측 — ' + entry_facts.line())
    except Exception:                                          # noqa: BLE001
        pass
    return out


def plan_rows(c):
    """가장 최근 판정일의 계획 + 모의 결과 — 표 한 줄씩."""
    ps = L.plans(c)
    if not ps:
        return None, []
    day = ps[0]['data_day']
    sh = L.shadow_latest(c)
    rows = []
    for p in [x for x in ps if x['data_day'] == day]:
        s = sh.get(p['plan_id']) or {}
        res = SHADOW_KO.get(s.get('status'), '아직 안 굴림')
        if s.get('status') == 'closed':
            res += f" · {EXIT_KO.get(s.get('exit_status'), s.get('exit_status'))} {_pct(s.get('net_pct'))}(비용 뺀)"
        rows.append({'종목': f"{p.get('name') or ''} ({p['code']})", '실주문 자격': '예' if p['live_ok'] else '아니오',
                     '진입가(지정가)': _won(p['entry']), '1차 목표': _won(p['target']), '손절': _won(p['stop']),
                     '대기·보유(거래일)': f"{p.get('wait_bars') or '—'} · {p.get('horizon') or '—'}",
                     '막은 사유': p.get('block_reason') or '—', '기록만 모의': res})
    return day, rows


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


def render(st, uk, *, allow_read, allow_write, hold_levels=None, report=None, anchor_day=None, md_safe=None):
    """칸 전체. hold_levels(code) → (손절선, 1차 매도가) 또는 None — 관심종목 표와 같은 함수로 화면이 만든다."""
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
        _render_body(st, uk, c, allow_write, hold_levels, report, anchor_day, md)
    finally:
        c.close()


def _render_body(st, uk, c, allow_write, hold_levels, report, anchor_day, md):
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

    # ② 오늘의 계획
    day, rows = plan_rows(c)
    with st.expander('② 스윙 계획과 기록만 모의', expanded=True):
        if not rows:
            st.caption('아직 계획이 없습니다 — 모드를 \'기록만\' 이상으로 두고 \'계획·모의 갱신\'을 누르거나 워커가 돌면 그날 개장 전 '
                       '리포트에서 만들어집니다.')
        else:
            st.caption(f'판정일 {day} 의 개장 전 후보 — 실주문 자격은 중앙 판정이 추천(조건 11개 전부 통과)일 때만 \'예\'입니다. '
                       '자격이 없는 후보도 같은 계약으로 모의 결과를 남깁니다(사지 않은 경우의 성적).')
            st.dataframe(rows, hide_index=True, width='stretch')
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

    # ⑤ 설정
    with st.expander('⑤ 설정 — 모드 · 위험 한도 · 긴급정지 · 연결 확인', expanded=False):
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
            "최대 손실을 작게 두기를 권합니다. 장중에 워커 창 하나를 켜 둡니다 — "
            "`python scripts/run_swing_worker.py --loop 60`. '③ 주문·체결 이력'에서 계획 · 접수 · 체결 · 손절·목표가 계약대로 "
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
            st.warning('실전 조건이 다 통과하지 않아 실전으로 바꾸지 않았습니다.')
        elif blocks:
            st.warning('이 모드로 바꾸지 않았습니다 — ' + ' · '.join(blocks))
        elif st.button(f"'{MODE_KO[new_mode]}' 로 바꾸기", key='sw_mode_go'):
            L.set_setting(c, 'mode', new_mode)
            st.rerun()
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
