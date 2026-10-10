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
import swing_ops as _ops
import swing_notify as _nt
import swing_proof as _sp
import swing_account as _acc454
import swing_viz as _viz
import swing_dash as _dash
import competitor_radar as _cr


def _os_exists(p):
    return _os_mod.path.exists(p)
import swing_ledger as L
import swing_risk
import swing_engine as _se

MODE_KO = {'OFF': '꺼짐', 'SHADOW': '기록만', 'PAPER': '모의투자', 'LIVE': '실전'}
MODE_HELP = {
    'OFF': ('새 매수를 내지 않습니다. 그날 계획과 일봉 재채점은 모드와 무관하게 매일 남깁니다. 자동 관리 중인 종목이 있으면 그 보호'
            "(손절·기간 만료 시장가 · 1차 목표 지정가)는 꺼짐에서도 계속합니다 — 보호까지 멈추려면 '포지션' 갈래에서 되돌려 받으세요."),
    'SHADOW': "'꺼짐'과 같습니다(옛 이름 · 기본으로 보이지 않습니다).",
    'PAPER': '한국투자 모의투자 서버로 실제 주문 흐름을 돕니다(모의투자 자격증명이 필요합니다).',
    'LIVE': "실계좌에 주문합니다. 아래 네 가지가 모두 통과해야 켜집니다. 주문 방식이 '계획마다 승인'(기본)이면 '오늘 계획' 갈래에서 승인한 계획만 삽니다.",
}
APPROVAL_KO = {'approve': '계획마다 승인', 'auto': '완전 자동'}


def mode_options(mode, cfg):
    """화면에 보이는 모드 — 기본은 꺼짐·실전 둘뿐(라운드 453 · 사용자가 모의투자를 건너뛰기로 했고 '기록만'은 꺼짐과 같아졌다).
    지금 모드가 그 둘 밖이거나 자격증명이 모의투자(demo)면 그 모드도 보인다(있는 상태를 숨기지 않는다 · §3)."""
    out = ['OFF', 'LIVE']
    if (cfg or {}).get('env') == 'demo' or mode == 'PAPER':
        out.insert(1, 'PAPER')
    if mode == 'SHADOW':
        out.insert(1, 'SHADOW')
    return out


def mode_label(mode, stt, protect_n=0):
    """운용 모드 한 마디 — 실전은 주문 방식까지 · 꺼짐인데 보호할 보유가 있으면 '보호만 N종목'."""
    if mode == 'LIVE':
        return '실전 · ' + APPROVAL_KO[X.approval_of(stt)]
    base = MODE_KO.get(mode, mode)
    return base + (f' · 보호만 {protect_n}종목' if protect_n and mode not in X.MODE_ENV else '')


def conn_label(cfg, acct, live_ts=None):
    """한국투자 연결 한 마디 — 사실만: 정보 없음 · 정보 있음(연결 확인 전) · 마지막으로 잔고를 읽은 시각(그것이 '정상'의 증거다).
    `live_ts` 는 이 화면의 계좌 판이 방금 읽은 시각(라운드 454 · 같은 값이면 장부 스냅샷을 안 쌓으므로 장부보다 새로울 수 있다) —
    더 새로우면 그것을 적는다(한 화면에 '동기화' 시각이 둘이 되지 않게 · §4)."""
    if not cfg or cfg.get('missing') or cfg.get('problems'):
        return '정보 없음'
    if live_ts and (not acct or str(live_ts) > str(acct.get('ts') or '')):
        return f"{'실계좌' if cfg.get('env') == 'real' else '모의투자'} · 읽음 {_ts(live_ts)} (이 화면)"
    if not acct:
        return '정보 있음 · 연결 확인 전'
    return f"{'실계좌' if acct.get('env') == 'real' else '모의투자'} · 동기화 {_ts(acct.get('ts'))}"
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
    # 라운드 453 — 실제 구현 그대로 적는다(종전 문장은 목표 매도도 워커가 그때 낸다고 했는데 실행부는 증권사에 지정가를 걸어 둔다 ·
    #   외부 검토 P0-2). 사용자가 자기 보호 상태를 잘못 알게 하는 문장이었다.
    out.append('1차 목표 매도는 워커가 매일 장중에 한국투자에 그날 하루짜리 지정가 매도로 걸어 둡니다. 손절·기간 만료 매도는 워커가 '
               '장중에 가격을 보고 조건이 맞으면 그때 시장가로 냅니다 — 워커가 멈추면 손절·기간 만료 보호 매도도 멈춥니다(이미 걸어 둔 '
               '목표 지정가 주문은 증권사에 그날까지 남아 있을 수 있습니다). 장이 열려 있는데 오늘 워커 기록이 없으면 이 칸 맨 위에 경고가 '
               "뜹니다. 모드를 '꺼짐'으로 두어도 자동 관리 중인 종목의 보호는 계속합니다 — 멈추려면 '포지션' 갈래에서 되돌려 받으세요.")
    try:
        import entry_facts
        out.append('이 칸이 실행하는 계획(진입가 지정가 · 1차 목표 · 손절 · 기간)의 지금까지 실측 — ' + entry_facts.line())
    except Exception:                                          # noqa: BLE001
        pass
    return out


#: 라운드 454 — 계좌 자동 갱신의 기본값. **꺼짐**이다 — 켜야 증권사를 부른다(회귀의 자식 렌더가 이 PC 의 실계좌 연결 정보로
#: 한국투자를 부르지 않게 · 켜는 것은 사람). 간격은 초 단위 선택지에서 고른다(새 문턱이 아니라 갱신 주기다).
ACCT_AUTO_DEFAULT = False
ACCT_EVERY_DEFAULT = 15
ACCT_EVERY_CHOICES = (15, 30, 60)
#: 라운드 457 — 사용자가 켠 자동 갱신은 이 PC 장부의 설정 'acct_refresh'({'on','every'})에 남는다(앱을 다시 띄워도 켜져 있게).
#: 기본값(꺼짐)은 그대로다 — 회귀의 임시 장부에는 이 설정이 없어 자식 렌더가 실계좌를 부르지 않는다.
ACCT_REFRESH_KEY = 'acct_refresh'


def acct_refresh_pref(session, stt):
    """계좌 자동 갱신 → (켜짐, 간격초). 이 화면에서 방금 바꾼 값(세션) → 이 PC 장부 설정(acct_refresh) → 기본(꺼짐 · 15초) 순."""
    v = (stt or {}).get(ACCT_REFRESH_KEY)
    v = v if isinstance(v, dict) else {}
    on = bool(session['sw_acct_auto']) if 'sw_acct_auto' in session else bool(v.get('on', ACCT_AUTO_DEFAULT))
    try:
        every = int(session['sw_acct_every']) if 'sw_acct_every' in session else int(v.get('every') or ACCT_EVERY_DEFAULT)
    except (TypeError, ValueError):
        every = ACCT_EVERY_DEFAULT
    return on, (every if every in ACCT_EVERY_CHOICES else ACCT_EVERY_DEFAULT)


def account_read(cfg, c=None, now=None):
    """한국투자 잔고를 **한 번** 읽는다(주문 없음) → (잔고 dict, None) 또는 (None, 사유). 장부 연결 `c` 가 있으면 스냅샷을 남길지
    `swing_account.should_snapshot` 이 정한다(보유·현금이 바뀌면 바로 · 가격만 바뀌면 저장 간격마다 — 15초마다 쌓지 않는다 · 라운드 457).
    화면·워커 밖에서 증권사를 부르는 자리는 여기와 시스템 → 설정의 '연결 확인' 둘뿐이다."""
    try:
        br = broker_kis.KisBroker(cfg)
        bal = br.get_balance()
    except Exception as e:                                     # noqa: BLE001 — BrokerError · TransportError · 설정 문제
        return None, f'{type(e).__name__}: {e}'
    if c is not None:
        try:
            if _acc454.should_snapshot(L.last_account(c), bal, now=now):
                L.account_snapshot(c, br.env, bal)
        except Exception:                                      # noqa: BLE001 — 읽기 전용 장부면 스냅샷은 못 남긴다(화면 값은 그대로)
            pass
    return bal, None


def _acct_panel454(st, uk, allow_write, cfg, stt, anchor_day, md, theme, scope='overview', managed=(), outer_live=False):
    """계좌 판 — `st.fragment(run_every=…)` 로 **이 판만** 다시 그린다(자동 갱신이 켜졌을 때 · 꺼지면 run_every 없음).
    조각 안에서는 바깥의 장부 연결을 쓸 수 없으므로(조각만 돌 때 바깥 연결은 이미 닫혀 있다) 제 연결을 연다.
    scope — 'overview'(관제실: 타일·한눈에·구성·범위) · 'holdings'(포지션: 보유 표·참고 비교·최근 주문) · 라운드 455 의 갈래."""
    pref_on, every = acct_refresh_pref(st.session_state, stt)
    auto_on = pref_on and allow_write and not outer_live         # 라운드 465 — 바깥이 다시 그리면 그 바퀴에 같이 읽는다(타이머 하나)

    @st.fragment(run_every=(f'{every}s' if auto_on else None))
    def _panel():
        _acct_panel_body454(st, uk, allow_write, cfg, stt, anchor_day, md, theme, scope=scope, managed=managed)
    _panel()


def _acct_panel_body454(st, uk, allow_write, cfg, stt, anchor_day, md, theme, scope='overview', managed=()):
    import datetime as _dtm
    st.markdown('**내 한국투자 계좌** — 읽기 전용 · 이 PC 화면에만' if scope == 'overview' else '**보유 종목(증권사 잔고)** — 읽기 전용')
    # 머리 줄: 연결 · 자동 갱신 토글·간격 · 지금 새로고침 — 전부 이 조각 안(누르면 이 판만 다시 돈다)
    h1, h2, h3, h4 = st.columns([2, 1.3, 1, 1.4])
    _ok454 = bool(cfg) and not cfg.get('missing') and not cfg.get('problems')
    h1.caption(('연결 정보 등록됨 · ' + broker_kis.config_summary(cfg)) if _ok454 else '연결 정보 없음 — 시스템 → 설정에서 넣으세요')
    _auto_prev, _every_prev = acct_refresh_pref(st.session_state, stt)
    _auto = h2.toggle('자동 갱신(화면 · 잔고)', value=_auto_prev, key='sw_acct_auto_tgl', disabled=not (allow_write and _ok454),
                      help='켜면 고른 간격마다 이 화면 전체(지휘 띠 · 워커 · 계획 · 주문 · 계좌)를 다시 그리고 한국투자 잔고를 다시 '
                           '읽습니다(주문은 안 합니다). 입력 칸이 있는 \'시스템\' 갈래는 쓰는 도중에 지워지지 않게 빼고, 이 화면을 닫으면 '
                           '멈추며, 켠 상태는 이 PC 에 남습니다.')
    _every = h3.selectbox('간격(초)', list(ACCT_EVERY_CHOICES), index=list(ACCT_EVERY_CHOICES).index(_every_prev),
                          key='sw_acct_every_sel', disabled=not allow_write)
    _now_btn = h4.button('지금 새로고침(잔고 읽기)', key='sw_acct_now', disabled=not (allow_write and _ok454))
    if _auto != _auto_prev or int(_every) != _every_prev:
        st.session_state['sw_acct_auto'] = bool(_auto)
        st.session_state['sw_acct_every'] = int(_every)
        if allow_write:                                        # 라운드 457 — 이 PC 장부에 남긴다(다시 띄워도 그대로)
            try:
                _cp = L.connect()
                L.set_setting(_cp, ACCT_REFRESH_KEY, {'on': bool(_auto), 'every': int(_every)})
                _cp.close()
            except Exception:                                  # noqa: BLE001 — 못 남겨도 이 세션에서는 켜진다
                pass
        st.rerun()                                             # run_every 는 조각을 다시 정의해야 바뀐다(앱 전체 한 번)
    c = None
    try:
        c = L.connect(readonly=not allow_write)
    except Exception:                                          # noqa: BLE001
        c = None
    try:
        live = st.session_state.get('sw_acct_live')
        if allow_write and _ok454 and (_now_btn or _auto):
            with st.spinner('잔고 읽는 중 …'):
                bal, err = account_read(cfg, c)
            if err:
                st.warning(md(f'잔고를 읽지 못했습니다 — {err}' + (' · 마지막으로 읽은 값을 보입니다' if (live or (c and L.last_account(c))) else '')))
            else:
                live = dict(bal=bal, ts=_dtm.datetime.now().isoformat(timespec='seconds'))
                st.session_state['sw_acct_live'] = live
        snap = L.last_account(c) if c is not None else None
        if live:
            bal, qts = live['bal'], live['ts'][:19].replace('T', ' ')
            src = f"{qts} 에 이 화면에서 읽음"
            env_ko = '실전' if cfg.get('env') == 'real' else '모의투자'
        elif snap:
            bal, qts = snap, _ts(snap['ts'])
            src = f"{qts} 장부 스냅샷(마지막으로 읽은 것)"
            env_ko = '실전' if snap.get('env') == 'real' else '모의투자'
        else:
            st.caption('아직 계좌를 읽은 적이 없습니다 — \'지금 새로고침\'이나 시스템 → 설정의 \'연결 확인\'을 누르면 채워집니다(주문은 안 합니다).')
            return
        st.caption(f"{env_ko} · 자료 시각 {src}" + (f" · 자동 갱신 {_every_prev}초마다 켜짐(이 화면이 열려 있는 동안)"
                                              if (_auto and allow_write) else ' · 자동 갱신 꺼짐'))
        s = _acc454.summarize(bal)
        if scope == 'overview':
            pn = s['pnl_sum']
            tone = ('up' if (pn or 0) > 0 else ('down' if (pn or 0) < 0 else ''))     # 손익 색은 한국 관행(이익 빨강 · 손실 파랑 · §5)
            uk.stat_tiles([
                dict(label='총자산(증권사 총평가)', value=_won(s['total']),
                     sub=('증권사 요약값' if s['total_src'] == 'broker' else ('예수금 + 보유 평가 합' if s['total_src'] else '총평가를 못 받았습니다'))),
                dict(label='보유 매수금액', value=_won(s['buy_sum']), sub=f"거래소 평균 매수가 × 수량 · {s['n_pnl']}종목"),
                dict(label='보유 평가손익', value=(f"{pn:+,.0f}원" if pn is not None else '—'), tone=tone, sub='매도 전 · 수수료·세금 제외'),
                dict(label='보유 수익률', value=(f"{s['ret_total']:+.2f}%" if s['ret_total'] is not None else '—'), tone=tone,
                     sub='평가손익 ÷ 매수금액'),
                dict(label='예수금', value=_won(s['cash']), sub='증권사 예수금 총액'),
                dict(label='D+2 정산 예정 예수금', value=_won(s['cash_d2']),
                     sub=('주문 가능 금액은 종목별로 따로 읽습니다' if s['cash_d2'] is not None else '이 잔고에는 없는 칸입니다')),
            ], theme=theme)
            for ln in _acc454.glance_lines(s):
                st.caption(md(ln))
            l1, l2 = st.columns([1, 1])
            with l1:
                st.markdown(_viz.donut(_dash.allocation(s, set(managed or ())), theme=theme, title='자산 구성 — 현금 · 자동매매 관리 · 직접 보유'),
                            unsafe_allow_html=True)
            with l2:
                if s['n']:
                    uk.chip_row(_acc454.scope_chips(s), theme=theme, title='평가 범위 — 열린 보유의 지금 상태(매매 승률이 아닙니다)')
                    st.caption(f"최신 가격 확인 {s['priced']}/{s['n']} · 손익 계산 가능 {s['n_pnl']}/{s['n']}"
                               + (f" · 가격 없음 {', '.join(s['unpriced_codes'])}" if s['unpriced_codes'] else '')
                               + (f" · 상위 1종목 비중 {s['top1']:.2f}%" if s['top1'] is not None else '')
                               + (f" · 상위 2종목 비중 {s['top2']:.2f}%" if s['top2'] is not None else '')
                               + (f" · 현금 비중 {s['cash_w']:.2f}%" if s['cash_w'] is not None else ''))
                else:
                    st.caption('보유 종목이 없습니다 — 계좌는 전부 현금입니다.')
            return
        # ── holdings (포지션 갈래)
        lc = _acc454.limit_checks(s, stt.get('limits') or None)
        if s['rows']:
            pos = L.positions(c) if c is not None else {}

            def _own(code):
                p = pos.get(code) or {}
                return OWN_KO.get(p.get('ownership')) if p.get('managed') else OWN_KO.get(p.get('ownership'), '기존 보유(자동 매도 안 함)')
            st.dataframe(_acc454.table_rows(s, ownership_label=_own, quote_ts=qts), hide_index=True, width='stretch')
            st.caption('평가는 증권사가 보낸 현재가 기준이고 체결을 보장하지 않습니다 · 평균 매수가는 거래소(증권사) 기준 · 수수료·세금 전 · '
                       '\'매도 가능\'은 걸려 있는 매도 주문을 뺀 수량입니다.')
        else:
            st.caption('증권사 잔고에 보유 종목이 없습니다.')
        if lc:
            st.caption('시스템 → 설정의 위험 한도와 지금 계좌를 **참고로** 견준 것입니다 — 직접 산 보유를 자동매매 한도로 판정하는 것이 아니고, '
                       '규칙 위반 판정도 매매 지시도 아닙니다.')
            st.dataframe([{'항목': r['name'], '설정 한도': f"{r['setting']:g}{r['unit']}",
                           '지금 계좌': (f"{r['current']:.2f}{r['unit']}" if isinstance(r['current'], float) else
                                     (f"{r['current']}{r['unit']}" if r['current'] is not None else '—')), '비교': r['status']}
                          for r in lc], hide_index=True, width='stretch')
        # 최근 30일 주문·체결 — 읽기 전용 · 누를 때만 증권사를 부른다 · 승률·성과를 셈하지 않는다(그 셈은 영수증이 같은 채점기로 한다)
        if allow_write and _ok454 and st.button('최근 30일 주문·체결 내역 읽기(증권사 · 읽기 전용)', key='sw_acct_orders'):
            try:
                br = broker_kis.KisBroker(cfg)
                _end = _dtm.date.today()
                _rows = br.get_daily_orders((_end - _dtm.timedelta(days=30)).strftime('%Y%m%d'), _end.strftime('%Y%m%d'))
                st.session_state['sw_acct_orders'] = dict(rows=_rows, ts=_dtm.datetime.now().isoformat(timespec='seconds'))
            except Exception as e:                             # noqa: BLE001
                st.session_state['sw_acct_orders'] = dict(rows=None, err=f'{type(e).__name__}: {e}')
        _od = st.session_state.get('sw_acct_orders')
        if _od:
            if _od.get('rows') is None:
                st.caption(md(f"주문·체결 내역을 읽지 못했습니다 — {_od.get('err')}"))
            else:
                _r = _od['rows']
                st.caption(f"최근 30일 주문 {len(_r)}건 — 매수 {sum(1 for x in _r if x.get('side') == 'buy')} · "
                           f"매도 {sum(1 for x in _r if x.get('side') == 'sell')} · {_od['ts'][11:19]} 읽음. 성과는 셈하지 않습니다(영수증이 같은 채점기로 셉니다).")
                if _r:
                    st.dataframe([{'날짜': x.get('date'), '종목': x.get('code'), '방향': '매수' if x.get('side') == 'buy' else '매도',
                                   '주문 수량': x.get('ord_qty'), '체결 수량': x.get('filled_qty'), '주문가': _won(x.get('ord_price')),
                                   '평균 체결가': _won(x.get('avg_fill')), '취소': '예' if x.get('cancelled') else ''}
                                  for x in _r[-100:]], hide_index=True, width='stretch')
    finally:
        if c is not None:
            c.close()


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
        # 라운드 453 — 모델(중앙 판정) 가격과 호가 단위로 맞춘 주문 가격이 다르면 둘 다 적는다(한쪽이 다른 쪽을 덮지 않는다)
        def _px(order, model):
            s = _won(order)
            try:
                if model is not None and order is not None and abs(float(model) - float(order)) >= 0.5:
                    s += f' (중앙 판정 {float(model):,.1f}원)'
            except (TypeError, ValueError):
                pass
            return s
        rows.append({'종목': f"{p.get('name') or ''} ({p['code']})", '실주문 자격': '예' if p['live_ok'] else '아니오',
                     '오늘 상태': status,
                     '중앙 판정 조건': cond,
                     '진입가(지정가)': _px(p['entry'], p.get('entry_model')), '1차 목표': _px(p['target'], p.get('target_model')),
                     '손절': _won(p['stop']),
                     '대기·보유(거래일)': f"{p.get('wait_bars') or '—'} · {p.get('horizon') or '—'}",
                     '수량 미리보기': qty_txt, '손절 시 손실(손절가 체결 가정)': loss_txt,
                     '막은 사유': p.get('block_reason') or '—', '연구 모의(일봉)': res})
    return day, rows


#: 중앙 판정의 조건 이름 — 글자가 엔진 리터럴(`verdict_core` 의 checks)과 같아야 한다(회귀 §453 이 대 본다).
EV_CHECK = '비용 차감 기대값 양수'


def _hm(ts):
    """'2026-10-08 15:32:51' · '2026-10-09T17:01:21+09:00' → '2026-10-08 15:32'. 못 읽으면 None."""
    s = str(ts or '').replace('T', ' ')
    return s[:16] if len(s) >= 16 and s[4] == '-' and s[13] == ':' else None


def judged_at(p):
    """계획이 선 판정의 시각 — 계획에 실린 개장 전 리포트 생성 시각(라운드 472 부터 싣는다). 옛 계획은 그 판정일의 리포트
    파일에서 읽는다(엔진 버전이 같은 것 먼저 · `premarket.generated_at`). 못 찾으면 None(지어내지 않는다 · §3)."""
    ts = _verdict_of(p).get('report_ts')
    if ts:
        return str(ts)
    try:
        import premarket
        return premarket.generated_at(p.get('data_day'), p.get('engine_version'))
    except Exception:                                          # noqa: BLE001
        return None


def when_line(ps):
    """'언제 막았나' 한 줄 — 판정(개장 전 리포트 생성) 시각과 장부에 계획으로 적힌 시각. 둘 다 못 읽으면 None.
    한 판정일의 계획이 여러 시각이면 처음~끝으로 적는다."""
    def _span(vals):
        vs = sorted({v for v in vals if v})
        return None if not vs else (vs[0] if len(vs) == 1 else f'{vs[0]} ~ {vs[-1]}')
    j = _span(_hm(judged_at(p)) for p in ps)
    w = _span(_hm(p.get('created_ts')) for p in ps)
    if not (j or w):
        return None
    bits = []
    if j:
        bits.append(f'판정 {j} (개장 전 리포트가 만들어진 시각 · 그 판정일 장 마감 자료)')
    if w:
        bits.append(f'자동매매 장부에 계획으로 적힌 시각 {w}')
    return '언제 막았나 — ' + ' · '.join(bits) + '.'


def ev_shortfall(p):
    """계획 하나의 '비용 차감 기대값'이 0 까지 얼마나 모자란가 — 중앙 판정의 식 그대로(라운드 472 · 새 문턱 없음).
    EV = p·up + (1 − p)·dn − 비용 (up·dn = 모델 진입가에서 1차 목표·손절까지의 폭 %). 0 이 되는 확률 p_need = (비용 − dn)/(up − dn),
    지금 확률 p_now 는 기대값에서 되짚는다(기대값이 소수 둘째 자리로 반올림돼 있어 0.1%p 안팎 어긋날 수 있다). 비용은 계획의
    계약 비용(그 판정이 쓴 비용과 같다고 본다 · 다르면 p_now 만 그만큼 어긋나고 모자란 폭 gap = −EV/(up − dn) 은 비용과 무관하다).
    재료가 하나라도 없거나 가격 정합이 깨졌으면 None."""
    v = _verdict_of(p)
    try:
        ev = float(v.get('expected_return'))
        e = float(p.get('entry_model') or p.get('entry'))
        t = float(p.get('target_model') or p.get('target'))
        s = float(p.get('stop'))
        cost = float(p.get('cost_pct'))
    except (TypeError, ValueError):
        return None
    if not (0 < s < e < t):
        return None
    up, dn = (t / e - 1.0) * 100.0, (s / e - 1.0) * 100.0
    slope = up - dn
    return dict(ev=ev, cost=cost, up=up, dn=dn, p_now=(ev + cost - dn) / slope * 100.0,
                p_need=(cost - dn) / slope * 100.0, gap=-ev / slope * 100.0)


def ev_gap_line(ps):
    """'비용 차감 기대값 양수'에 걸린 계획들이 0 까지 얼마나 모자란가 — 가장 가까운 후보의 기대값 · 필요한 확률 · 지금 확률.
    판정 낱말 없음 · 그 조건에 걸린 계획이 없거나 셀 수 없으면 None. 사용자: *"'비용 차감 기대값 양수' 미충족 개선 해줘"* —
    고칠 수 있는 것은 이 칸의 **설명**이다. 문턱(0)을 내리거나 비용을 낮춰 적으면 그것이 §2·§9 다."""
    rows = [ev_shortfall(p) for p in ps if EV_CHECK in (_verdict_of(p).get('failed') or [])]
    rows = [g for g in rows if g and g['ev'] <= 0]
    if not rows:
        return None
    best = max(rows, key=lambda g: g['ev'])
    gaps = [g['gap'] for g in rows]
    rng = f' · {len(rows)}개 범위 {min(gaps):.1f}~{max(gaps):.1f}%p' if len(rows) > 1 else ''
    try:
        import forward_eval as _fe
        ed = _fe.eval_date()
    except Exception:                                          # noqa: BLE001
        ed = None
    fwd = f'{ed} 전방 재평가' if ed else '전방 재평가'
    return (f"'{EV_CHECK}'는 기준을 낮춰 풀 조건이 아닙니다 — 가장 가까운 후보도 왕복 비용 {best['cost']:.2f}%를 뺀 기대값이 "
            f"{best['ev']:+.2f}%입니다. 0을 넘으려면 1차 목표가 손절보다 먼저 닿을 확률이 {best['p_need']:.1f}%여야 하는데, 그 점수대의 "
            f"원장 실측은 {best['p_now']:.1f}%입니다({best['gap']:.1f}%p 모자람{rng} · 지금 확률은 기대값에서 되짚은 값). "
            f"이 확률이 바뀔 수 있는 길은 새 재료(시점 재무·잔여 호가 축적)와 {fwd}이고, 둘 다 결과를 약속하지 않습니다.")


def blocked_record_line(ps, scorecard=None):
    """'비용 차감 기대값 양수'에 걸린 계획이 있으면 — 그 조건이 지금까지 막은 개장 전 후보가 실제로 어떻게 됐나(라운드 475).
    사용자: *"이거 너무 보수적 아니야?"* 문장은 `proof.gate_line` 한 곳이 성적표에서 만든다(§4 · 이 칸은 읽기만). 성적표를 못 읽거나
    그 조건이 성적표에 없으면 None(§3) — 줄을 안 그린다."""
    if not any(EV_CHECK in (_verdict_of(p).get('failed') or []) for p in ps):
        return None
    try:
        import proof as _pf
        sc = scorecard if scorecard is not None else _pf.load_scorecard()
        return _pf.gate_line(sc, EV_CHECK)
    except Exception:                                          # noqa: BLE001
        return None


def zero_day_line(c, day, scorecard=None):
    """그날 계획에 실주문 자격이 하나도 없을 때 — 가장 많이 막은 조건 한 줄(규칙은 `ui_kit.top_blocker` 한 곳 · 수만). 아니면 None.
    라운드 472 — 사용자: *"또 막고 있는데 언제 막았는지 시간도 써주고"*. 머리는 '오늘'이 아니라 **판정일**(휴장일·장 전에 열면
    오늘과 다르다)이고, 언제 막았나(`when_line`)와 기대값이 0 까지 얼마나 모자란가(`ev_gap_line`)를 줄을 바꿔 잇는다.
    라운드 475 — 그리고 그 조건이 막은 후보가 실제로 어떻게 됐나(`blocked_record_line` · 성적표에서 읽는다)."""
    ps = [p for p in L.plans(c) if p['data_day'] == day] if day else []
    if not ps or any(p.get('live_ok') for p in ps):
        return None
    import ui_kit as _uk
    top = _uk.top_blocker([_verdict_of(p).get('failed') for p in ps])
    head = f'판정일 {day} 후보 {len(ps)}개 중 실주문 자격 0 — '
    if not top:
        first = head + '조건 기록이 있는 계획이 없어 어느 조건이 막았는지 세지 못했습니다(막은 사유는 표의 칸).'
    else:
        fl = _fail_label()
        first = (head + f'가장 많이 막은 조건은 {fl(top[0])}입니다 ({top[1]}/{top[2]}개 · 조건 기록이 있는 계획 기준). '
                 '조건별로 세어 본 것이고, 어느 조건을 풀어야 한다는 뜻이 아닙니다.')
    return '  \n'.join(x for x in (first, when_line(ps), ev_gap_line(ps), blocked_record_line(ps, scorecard)) if x)


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


def protection_line(hb, now, managed_n, mode=None, task=None):
    """보호 매도는 워커가 낸다 — 장이 열려 있는데 **오늘 장 시작 뒤** 워커 기록이 없으면 그 사실을 적는다(라운드 450).
    문턱 없음 — 기준은 그날 장 시작 시각 한 곳(`bitemporal_engine.session_times`). 장 밖이거나 기록이 장 시작 뒤면 None.
    모드가 '꺼짐'이고 관리 중인 종목도 없으면 워커가 안 도는 것이 설계라 None(관리 중인 종목이 있으면 모드와 무관하게 적는다).
    task(작업 스케줄러 상태 · `swing_ops.scheduled_task`)가 '등록 안 됨'이면 그 사실을 같은 줄에 붙인다(라운드 453)."""
    if not managed_n and (mode or 'OFF') == 'OFF':
        return None
    tail = ''
    if task and task.get('ok') and task.get('installed') is False:
        tail = f' 워커 예약 작업({_ops.TASK_NAME})도 등록돼 있지 않습니다.'
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
            "scripts/register_swing_worker_task.ps1 을 한 번 돌립니다)" + tail)


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


#: 라운드 455 — 스윙 칸의 갈래(정보구조). 세로로 쌓인 접힌 칸 여섯 대신 **한 번에 한 갈래**만 그린다(외부 검토 R455). 설정·연결 정보·
#: 운영 방법은 '시스템' 갈래로 간다 — 관제실에는 돈·위험·오늘 엔진·포지션·실행 상태만.
NAV = ('관제실', '오늘 계획', '포지션', '주문·체결', '성과·PROOF', '시스템')
NAV_KEY = 'sw_nav'
#: 라운드 465 — 자동 갱신이 켜져 있으면 이 갈래들은 **본문 전체**(지휘 띠 · 워커 · 계획 · 주문 · 계좌)를 그 간격으로 다시 그린다.
#:   '시스템'은 뺀다 — 설정·연결 정보 입력 칸이 있어 쓰는 도중에 다시 그리면 안 된다(입력 위젯이 있는 갈래는 그 하나뿐 · 회귀가 센다).
LIVE_VIEWS = ('관제실', '오늘 계획', '포지션', '주문·체결', '성과·PROOF')


def live_refresh(auto_on, view):
    """이 갈래를 자동 갱신으로 다시 그리나 — 자동 갱신이 켜져 있고(쓰기 가능한 화면) 입력 칸이 없는 갈래일 때만."""
    return bool(auto_on) and (view or NAV[0]) in LIVE_VIEWS


def render(st, uk, *, allow_read, allow_write, hold_levels=None, report=None, anchor_day=None, md_safe=None,
           resolve_market=None):
    """칸 전체. hold_levels(code) → (손절선, 1차 매도가) 또는 None — 관심종목 표와 같은 함수로 화면이 만든다.
    resolve_market(code) → 'KOSPI'·'KOSDAQ'·None — 계좌 보유를 앱 보유종목으로 가져올 때 시장 접미사를 정한다(CSV 가져오기와 같은 길)."""
    md = md_safe or (lambda s: s)
    # 라운드 455 — 머리는 두 줄: 한 줄 안내 + 우위 없음 한 줄. 외부 검토 둘이 모두 *"변명성 텍스트 삭제"* 를 요구했지만 받지 않았다(§9 ·
    #   면책 한 줄은 접지 않는다 · 라운드 226·453). 나머지 사실은 '시스템' 갈래의 접힌 칸으로 갔다 — 지운 것이 아니다.
    st.caption('가늠이 판단하고 · 한국투자증권이 실행하고 · 결과는 같은 채점 규칙으로 남깁니다. 이 칸은 관제실이고 주문은 따로 도는 워커만 냅니다. '
               '분석 화면은 맨 위 탭 \'가늠 분석\'.')
    _facts = facts_lines()
    st.caption(md(_facts[0]))
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
        _pref465, _every465 = acct_refresh_pref(st.session_state, L.settings(c))
    finally:
        c.close()
    # 라운드 465 — 사용자: "15초마다 자동 갱신 해줘". 종전엔 계좌 칸 하나만 다시 그려 지휘 띠·워커·주문 사건은 화면을 다시 열어야 바뀌었다.
    #   본문 전체를 조각 하나로 감싸 켜져 있으면 그 간격으로 다시 그린다(앱 전체는 안 돈다 · 사이드바·분석 화면은 그대로).
    _live465 = live_refresh(_pref465 and allow_write, st.session_state.get(NAV_KEY))

    @st.fragment(run_every=(f'{_every465}s' if _live465 else None))
    def _body465():
        try:                                                   # 조각만 다시 돌 때 바깥 연결은 이미 닫혀 있다(라운드 454) — 제 연결을 연다
            c2 = L.connect(readonly=not allow_write)
        except Exception as e:                                 # noqa: BLE001
            st.warning(f'장부를 못 열었습니다 — {type(e).__name__}: {e}')
            return
        if c2 is None:
            return
        try:
            _render_body(st, uk, c2, allow_write, hold_levels, report, anchor_day, md, resolve_market, facts=_facts, live=_live465)
        finally:
            c2.close()
    _body465()


def bar_items(ctx):
    """지휘 띠 재료 — 값은 **짧게**(정상 · 꺼짐 · 3), 세부는 sub(외부 검토 R456 · 긴 글자를 값으로 넣지 않는다). 판정 낱말 없음."""
    conn = conn_label(ctx['cfg'], ctx['acct'], live_ts=(ctx.get('live') or {}).get('ts'))
    if conn == '정보 없음':
        cv, ct = '정보 없음', 'neg'
    elif conn.startswith('정보 있음'):
        cv, ct = '확인 전', 'warn'
    else:
        cv, ct = '정상', 'pos'
    mode, stt = ctx['mode'], ctx['stt']
    kill = bool(stt.get('kill_switch'))
    buy_on = mode in X.MODE_ENV and not kill
    n_prot = len(ctx['managed']) + len(ctx['releasing'])
    w, task, hb = ctx.get('worker') or {}, ctx.get('task') or {}, ctx.get('hb')
    if w.get('running') is True:
        wv, wt = '실행 중', 'pos'
    elif w.get('running') is None:
        wv, wt = '확인 불가', 'warn'
    elif ctx.get('pl'):
        wv, wt = '안 돎', 'neg'
    elif task.get('ok') and task.get('installed'):
        wv, wt = '예약됨', ''
    elif task.get('ok'):
        wv, wt = '예약 안 됨', 'warn'
    else:
        wv, wt = '확인 불가', 'warn'
    live_n = sum(1 for p in ctx['plans_today'] if p.get('live_ok'))
    # 라운드 458 — 15초 자동 갱신이 켜져 있으면 이 띠의 시각은 화면 전체가 다시 그려질 때만 바뀐다(조각 밖) → 시각 대신 갱신 사실을 적는다
    _ar = ctx.get('auto_refresh')
    if _ar and _ar[0] and cv == '정상':
        conn = f"자동 갱신 {_ar[1]}초 · 시각은 아래 계좌 칸"
    ss = ctx.get('start') or {}
    start_sub = (f"시작 조건 {ss['n_ok']}/{ss['n_items']} · " if ss.get('n_items') else '') + mode_label(mode, stt, n_prot)
    return [dict(label='한국투자', value=cv, tone=ct, sub=conn),
            dict(label='신규 매수', value=('켜짐' if buy_on else '꺼짐'), tone=('pos' if buy_on else ''), sub=start_sub),
            dict(label='보호 매도', value=(f'{n_prot}종목' if n_prot else '없음'), tone=('warn' if (n_prot and ctx.get('pl')) else ''),
                 sub=('워커가 손절·목표를 관리' if n_prot else '자동 관리 중인 종목 없음')),
            dict(label='워커', value=wv, tone=wt, sub=(f"마지막 기록 {_ts(hb['ts'])}" if hb else '기록 없음')),
            dict(label='긴급정지', value=('켜짐' if kill else '꺼짐'), tone=('neg' if kill else ''), sub='토글은 오른쪽'),
            dict(label='오늘 계획', value=str(len(ctx['plans_today'])), sub=f"실주문 자격 {live_n} · 판정일 {ctx.get('today') or '—'}")]


def _summary_now(ctx):
    bal = (ctx.get('live') or {}).get('bal') or ctx.get('acct')
    return _acc454.summarize(bal) if bal else None


def _render_body(st, uk, c, allow_write, hold_levels, report, anchor_day, md, resolve_market=None, facts=None, live=False):
    stt = L.settings(c)
    mode = L.mode_of(c)
    cfg = broker_kis.load_config()
    hb = L.last_heartbeat(c)
    acct = L.last_account(c)
    plans_today = [p for p in L.plans(c) if p['data_day'] == str(anchor_day)] if anchor_day else []
    managed = L.managed_open(c)
    releasing = L.releasing(c)
    theme = st.session_state.get('ui_theme', 'dark')
    task = _ops.scheduled_task()
    worker = _ops.worker_status()
    nightly = _ops.nightly_status()
    pl = protection_line(hb, X.now_kst(), len(managed) + len(releasing), mode=mode, task=task)
    try:
        from verdict_core import COST_PCT as _cost
    except Exception:                                          # noqa: BLE001
        _cost = None
    ctx = dict(stt=stt, mode=mode, cfg=cfg, hb=hb, acct=acct, plans_today=plans_today, managed=managed, releasing=releasing,
               theme=theme, task=task, worker=worker, nightly=nightly, pl=pl, today=anchor_day,
               live=st.session_state.get('sw_acct_live'), allow_write=allow_write, hold_levels=hold_levels, report=report,
               resolve_market=resolve_market, cost=_cost, intents=L.intents_with_state(c),
               approval_on=(mode == 'LIVE' and X.approval_of(stt) == 'approve'), approved=X.approved_plans(stt), facts=facts or [])
    # 라운드 457 — 자동매매 언제 시작하나: 장부 설정 · 실전 준비 넷 · 작업 스케줄러 · 거래일 달력에서 **유도**한다(날짜를 지어내지 않는다)
    ctx['start'] = _dash.start_status(mode, stt, cfg, task=task, worker=worker, now=X.now_kst())
    _ar458 = acct_refresh_pref(st.session_state, stt)
    ctx['auto_refresh'] = (_ar458[0] and allow_write, _ar458[1])
    ctx['live_refresh'] = bool(live)                           # 라운드 465 — 본문 전체가 그 간격으로 다시 그려지는 중인가
    # ── 지휘 띠(R456) — 짧은 값 · 긴급정지 토글은 한 곳(sw_kill) · 갈래 고르기
    st.markdown(_viz.command_bar(bar_items(ctx), theme=theme), unsafe_allow_html=True)
    nc, kc = st.columns([5, 1.2])
    with nc:
        pick = st.radio('갈래', list(NAV), horizontal=True, key=NAV_KEY, label_visibility='collapsed')
    if live_refresh(ctx['auto_refresh'][0], pick) != bool(live):
        st.rerun()                                             # 라운드 465 — '시스템'으로 가거나 돌아오면 조각을 다시 정의한다(run_every)
    with kc:
        if allow_write:
            ks = st.toggle('긴급정지', value=bool(stt.get('kill_switch')), key='sw_kill',
                           help='켜면 새 매수를 안 내고 열린 매수 주문을 취소합니다. 자동 관리 중인 종목의 손절·목표 매도는 계속합니다.')
            if ks != bool(stt.get('kill_switch')):
                L.set_setting(c, 'kill_switch', bool(ks))
                st.rerun()
        else:
            st.caption('긴급정지 ' + ('켜짐' if stt.get('kill_switch') else '꺼짐'))
    # 워커가 보호(손절·취소·계좌 맞추기)에 문제를 적었으면 조용히 'ok' 로 덮지 않고 그대로 띄운다
    if hb and hb.get('status') in ('warn', 'broker_fail', 'blocked'):
        st.warning(md(f"워커 마지막 바퀴({_ts(hb['ts'])}) — {hb.get('detail') or hb['status']}"))
    if pl:
        st.warning(md(pl))
    if st.session_state.get('sw_flash'):
        st.success(st.session_state.pop('sw_flash'))
    view = {'관제실': _view_center, '오늘 계획': _view_plans, '포지션': _view_positions, '주문·체결': _view_orders,
            '성과·PROOF': _view_proof, '시스템': _view_system}.get(pick, _view_center)
    view(st, uk, c, ctx, md)


def _title(st, text, theme):
    t = _uk_tokens(theme)
    st.markdown(f"<p style='margin:14px 0 6px 2px; font-size:13px; color:{t['tx2']}; font-weight:500;'>{_uk_esc(text)}</p>",
                unsafe_allow_html=True)


def _uk_tokens(theme):
    import ui_kit as _uk
    return _uk.tokens(theme)


def _uk_esc(s):
    import ui_kit as _uk
    return _uk._esc(s)


def _view_center(st, uk, c, ctx, md):
    """관제실 — 열자마자 돈 · 위험 · 오늘 엔진 · 포지션 · 실행 상태가 보이게(외부 검토 §2). 전부 장부·잔고·운영 상태의 사실이다."""
    theme = ctx['theme']
    # 라운드 457 — 사용자: "자동매매 언제 시작할지 딱 써놔야지". 관제실 맨 위 — 지금 상태 · 언제부터 · 실제 첫 매수의 조건 · 남은 일
    try:
        import proof as _pf457
        _rl457 = _pf457.reco_line(_pf457.load_scorecard())
    except Exception:                                          # noqa: BLE001 — 못 읽으면 그 한 줄만 빠진다
        _rl457 = None
    st.markdown(_viz.start_card(ctx['start'], theme=theme, reco_line=_rl457), unsafe_allow_html=True)
    sh = _dash.system_health(ctx['worker'], ctx['task'], ctx['nightly'], ctx['cfg'], ctx['acct'], ctx['plans_today'], today=ctx['today'],
                             protection_warn=bool(ctx['pl']), ledger_ok=True)
    st.markdown(_viz.health_strip(sh, theme=theme, title='시스템 상태 — 워커 · 한국투자 연결 · 계획 생성 · 장부 · 저녁 작업'), unsafe_allow_html=True)
    _acct_panel454(st, uk, ctx['allow_write'], ctx['cfg'], ctx['stt'], ctx['today'], md, theme, scope='overview', managed=set(ctx['managed']), outer_live=ctx.get('live_refresh', False))
    s = _summary_now(ctx)
    pts = _dash.equity_points(_dash.daily_last(L.account_history(c, limit=20000)))
    its_today = [it for it in ctx['intents'] if it.get('trade_day') == str(ctx['today'])]
    n_new = sum(1 for it in its_today if it.get('side') == 'buy')
    a, b = st.columns([1.6, 1])
    with a:
        _title(st, '자산 곡선 — 증권사 총평가·예수금(하루 마지막으로 읽은 값 한 점 · 수익률로 바꾸지 않는다)', theme)
        st.markdown(_viz.equity_curve(pts, theme=theme), unsafe_allow_html=True)
    with b:
        st.markdown(_viz.risk_bars(_dash.risk_usage(s or {}, ctx['stt'].get('limits'), managed_n=len(ctx['managed']), new_orders_today=n_new,
                                                    planned_loss_sum=_dash.planned_loss_sum(ctx['managed'])),
                                   theme=theme, title='위험 한도 사용 — 설정 한도 대비(참고 · 직접 보유 포함)'), unsafe_allow_html=True)
    st.markdown(_viz.funnel(_dash.funnel_today(ctx['plans_today'], approved=ctx['approved'], approval_on=ctx['approval_on'], intents_today=its_today,
                                               managed_codes=set(ctx['managed'])),
                            theme=theme, title=f"오늘의 엔진 — 판정일 {ctx['today'] or '—'} · 후보 → 실주문 자격 → 승인 → 주문 → 체결"), unsafe_allow_html=True)
    zl = zero_day_line(c, str(ctx['today'])) if ctx['today'] else None
    if zl:
        st.caption(md(zl))
    elif not ctx['plans_today']:
        st.caption('오늘 계획이 아직 없습니다 — 워커 · 저녁 작업 · 시스템의 \'계획 갱신\'이 그날 개장 전 리포트에서 만듭니다.')
    eh = _dash.execution_health(ctx['intents'])
    rc = _sp.receipts(c, ctx['cost'])
    c1, c2 = st.columns(2)
    with c1:
        rows = [(f"{code} · {OWN_KO.get(p.get('ownership'), '')}", f"수량 {p.get('qty')} · 손절 {_won(p.get('stop'))} · 목표 {_won(p.get('target'))}")
                for code, p in list(ctx['managed'].items())[:5]] or [('지금', '자동 관리 중인 종목 없음')]
        st.markdown(_viz.kv_card('자동 관리 포지션', rows, theme=theme), unsafe_allow_html=True)
        st.markdown(_viz.kv_card('PROOF — 계획 vs 실제',
                                 [('닫힌 거래 영수증', str(sum(1 for r in rc if r.get('closed_day')))),
                                  ('보유 중(영수증 열림)', str(sum(1 for r in rc if r.get('open')))),
                                  ('오늘 후보 중 실주문 자격', f"{sum(1 for p in ctx['plans_today'] if p.get('live_ok'))}/{len(ctx['plans_today'])}")],
                                 theme=theme), unsafe_allow_html=True)
    with c2:
        st.markdown(_viz.kv_card('실행 상태(주문 사건)',
                                 [('주문 전체', str(eh['total'])), ('증권사 접수', str(eh['ack'])), ('체결', str(eh['filled'])),
                                  ('일부 체결', str(eh['partial']), 'warn' if eh['partial'] else None),
                                  ('확인 중(UNKNOWN)', str(eh['unknown']), 'warn' if eh['unknown'] else None),
                                  ('거절', str(eh['rejected']), 'neg' if eh['rejected'] else None)], theme=theme), unsafe_allow_html=True)
        st.markdown(_viz.kv_card('최근 사건', [(ts, txt) for ts, txt in _dash.recent_events(L.heartbeats_recent(c, 3), ctx['nightly'], ctx['acct'],
                                                                                        ctx['task'])] or [('—', '기록 없음')],
                                 theme=theme), unsafe_allow_html=True)


def _view_plans(st, uk, c, ctx, md):
    """오늘 계획 — 라운드 450·451 의 표·승인 그대로(갈래로 옮겼을 뿐)."""
    day, rows = plan_rows(c, today_day=ctx['today'], account=ctx['acct'], limits=(ctx['stt'].get('limits') or None), cost_pct=ctx['cost'],
                          held=set(ctx['managed']), approval_on=ctx['approval_on'], approved=ctx['approved'])
    if not rows:
        st.caption('아직 계획이 없습니다 — 워커가 돌거나(저녁 작업 포함) 시스템의 \'계획 갱신\'을 누르면 그날 개장 전 리포트에서 만들어집니다. '
                   '운용 모드와 무관하게 남깁니다.')
        return
    st.caption(f'판정일 {day} 의 개장 전 후보 — 실주문 자격은 중앙 판정이 조건 11개를 전부 통과했을 때만 \'예\'입니다. '
               '자격이 없는 후보도 같은 계약을 일봉으로 되돌려 채점한 결과(연구 모의 · 증권사와 무관한 원장 기준 값)를 남깁니다. '
               '진입가·1차 목표는 호가 단위로 맞춘 주문 가격이고, 중앙 판정 값과 다르면 괄호에 같이 적습니다.')
    _zl450 = zero_day_line(c, day)
    if _zl450:
        st.caption(md(_zl450))
        try:                                                   # 라운드 464 — '목표를 넓히면?' 잰 값 한 줄(산출물에서 · 못 읽으면 빠진다)
            import artifact_io as _aio464
            import ledger_view as _lv464
            _tw464 = _lv464.target_widen_line(_aio464.load_json('target_multiple_r160.json'))
        except Exception:                                      # noqa: BLE001
            _tw464 = None
        if _tw464:
            st.caption(md(_tw464))
    st.dataframe(rows, hide_index=True, width='stretch')
    acct = ctx['acct']
    if acct and (ctx['stt'].get('limits') or None):
        st.caption(f"수량 미리보기는 마지막으로 읽은 계좌({_ts(acct['ts'])} · 예수금 {_won(acct['cash'])})와 지금 위험 한도로 "
                   "워커와 같은 함수로 센 것입니다 — 워커는 주문 때 잔고·주문 가능 금액·대기 주문을 다시 읽어 셉니다.")
    else:
        st.caption('수량 미리보기 없음 — 계좌를 읽은 적이 없거나 위험 한도가 비어 있습니다(시스템 → 설정).')
    # 라운드 451 — 실전 승인형: 승인은 계획(진입가·손절·목표가 박힌 영수증)에 붙는다. 쓰는 자리는 여기뿐이다.
    if ctx['approval_on']:
        _live451 = [p for p in L.plans(c) if p['data_day'] == day and p.get('live_ok') and p['code'] not in ctx['managed']]
        if _live451:
            st.caption('실전 주문 방식이 \'계획마다 승인\'입니다 — 아래에서 승인한 계획만 워커가 그 계획의 대기 창 안에서 진입가 지정가 '
                       '매수를 냅니다. 승인해도 중앙 판정·위험 한도·긴급정지는 그대로 적용되고, 보호 매도는 승인과 무관합니다.')
        if ctx['allow_write']:
            _apset451 = ctx['approved']
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


def position_card_html(pc, theme):
    """포지션 카드 — 머리 + 가격선 + 사실 줄(외부 검토 R458). 판정 낱말 없음 · 값 없으면 '—'."""
    t = _uk_tokens(theme)
    name = f"{pc.get('name') or ''} {pc['code']}".strip()
    own = OWN_KO.get(pc.get('ownership'), pc.get('ownership') or '')
    head = (f"<div style='display:flex; justify-content:space-between; gap:12px; align-items:baseline; flex-wrap:wrap;'>"
            f"<span style='font-size:16px; font-weight:600; color:{t['tx1']};'>{_uk_esc(name)}</span>"
            f"<span style='font-size:12px; color:{t['tx3']};'>{_uk_esc(own)}{' · 해제 확인 중' if pc.get('releasing') else ''} · 수량 {pc.get('qty')}</span></div>")
    g = pc.get('gross_pct')
    gcol = t['up'] if (g or 0) > 0 else (t['down'] if (g or 0) < 0 else t['tx1'])
    big = (f"<p style='margin:4px 0 0 0; font-size:20px; font-weight:600; color:{gcol}; font-variant-numeric:tabular-nums;'>"
           f"{(f'{g:+.2f}%' if g is not None else '—')} <span style='font-size:12px; color:{t['tx3']}; font-weight:400;'>현재가 기준 · "
           f"{(f'{pc['held_days']}/{pc['horizon']} 거래일' if pc.get('held_days') is not None and pc.get('horizon') else '보유 거래일 —')}</span></p>")
    bar = _viz.range_bar(pc.get('stop'), pc.get('entry'), pc.get('current'), pc.get('target'), theme=theme)
    tgt = pc.get('target_order_state')
    rows = [('손절까지', f"{pc['dist_stop_pct']:+.2f}%" if pc.get('dist_stop_pct') is not None else '—'),
            ('목표까지', f"{pc['dist_target_pct']:+.2f}%" if pc.get('dist_target_pct') is not None else '—'),
            ('계획 손실(손절가 체결 가정)', f"{-pc['planned_loss']:,.0f}원" if pc.get('planned_loss') is not None else '—'),
            ('목표 지정가 주문(증권사)', STATE_KO.get(tgt, tgt) if tgt else '없음 — 워커가 장중에 건다'),
            ('손절 보호(워커 시장가)', (f"마지막 기록 {_ts(pc['heartbeat_ts'])}" if pc.get('heartbeat_ts') else '기록 없음'))]
    body = ''.join(f"<div style='display:flex; justify-content:space-between; gap:12px; padding:5px 0; border-top:1px solid {t['line']};'>"
                   f"<span style='font-size:13px; color:{t['tx2']};'>{_uk_esc(k)}</span>"
                   f"<span style='font-size:13px; color:{t['tx1']}; font-variant-numeric:tabular-nums;'>{_uk_esc(v)}</span></div>" for k, v in rows)
    return (f"<div style='background:{t['card']}; border-radius:18px; padding:16px 18px; margin-bottom:10px;'>{head}{big}"
            f"<div style='margin:8px 0;'>{bar}</div>{body}</div>")


def _view_positions(st, uk, c, ctx, md):
    """포지션 — 자동 관리 카드(가격선) · 넘기기·되돌려 받기 · 증권사 보유 표 · 앱 보유종목과 견주기·가져오기."""
    theme = ctx['theme']
    acct = ctx['acct']
    rows_by_code = {str(p.get('code')): p for p in ((acct or {}).get('positions') or [])}
    its = ctx['intents']
    allp = list(ctx['managed'].items()) + list(ctx['releasing'].items())
    if not allp:
        st.caption('자동 관리 중인 종목이 없습니다 — 자동매매가 산 종목이나 아래에서 넘긴 기존 보유가 여기에 카드로 보입니다.')
    for code, p in allp:
        tgt = next((it for it in reversed(its) if it.get('code') == code and it.get('side') == 'sell' and X._base(it.get('reason')) == 'target'
                    and it.get('state') in ('BROKER_ACK', 'PARTIAL', 'CANCEL_REQUESTED')), None)
        plan = L.plan(c, p.get('plan_id')) or {}
        pc = _dash.position_card(code, p, rows_by_code.get(code), target_intent=tgt, hb=ctx['hb'], horizon=plan.get('horizon'), today=ctx['today'])
        st.markdown(position_card_html(pc, theme), unsafe_allow_html=True)
        if p.get('ownership') == 'USER_ADOPTED' and ctx['allow_write'] and not p.get('releasing') and st.button('되돌려 받기', key=f'sw_rel_{code}'):
            _ev453 = X.release(c, code)
            st.session_state['sw_flash'] = (f'{code} 되돌려 받았습니다(열린 매도 주문 없음)' if _ev453 == 'RELEASED' else
                                            f'{code} 되돌려 받기 요청 — 걸려 있는 매도 주문의 취소를 워커가 확인하면 해제됩니다')
            st.rerun()
    st.caption('자동 매도는 자동매매가 산 종목과 직접 넘긴 종목만 합니다. 계좌의 기존 보유는 넘기기 전에는 절대 팔지 않습니다. '
               '넘긴 종목은 관심종목 표의 손절선·1차 매도가에 닿을 때만 팔고(기간 만료로는 안 팝니다), 손절선 가격에 그대로 '
               '팔린다는 보장은 없습니다(더 아래에서 팔릴 수 있습니다). 되돌려 받기는 두 단계입니다 — 걸려 있는 1차 목표 매도를 '
               '워커가 취소하고 그 취소가 확인된 뒤에야 해제됩니다(확인 전엔 \'확인 중\'으로 보이고 새 보호 주문은 내지 않습니다). '
               '증권사 앱에서 직접 판 수량은 워커가 계좌에 맞춰 관리에서 내립니다.')
    hold_levels = ctx['hold_levels']
    if acct and ctx['allow_write'] and hold_levels:
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
                    st.caption(f"넘기면 손절 {_won(lv[0])} 아래에서 시장가로 · 1차 목표 {_won(lv[1])} 에 지정가로 팝니다 (수량 {p['qty']}).")
                    ok = st.checkbox('이 종목을 자동 관리로 넘기는 데 동의합니다', key='sw_adopt_ok')
                    if ok and st.button('자동 관리로 넘기기', key='sw_adopt_go'):
                        try:
                            X.adopt(c, p['code'], p['qty'], lv[1], lv[0], by_user=True)
                            st.rerun()
                        except L.LedgerError as e:
                            st.warning(str(e))
    _acct_panel454(st, uk, ctx['allow_write'], ctx['cfg'], ctx['stt'], ctx['today'], md, theme, scope='holdings', managed=set(ctx['managed']), outer_live=ctx.get('live_refresh', False))
    with st.expander('앱 보유종목과 견주기 · 가져오기', expanded=False):
        if not acct:
            st.caption('아직 계좌를 읽은 적이 없습니다 — 위 \'지금 새로고침\'이나 시스템 → 설정의 \'연결 확인\'을 누르면 채워집니다.')
        else:
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
            if ctx['allow_write'] and acct['positions']:
                st.caption('아래 버튼은 이 계좌의 보유를 앱의 \'내 보유종목\'(.portfolio/positions.json · 이 PC 에만)으로 옮깁니다. 지금 보유종목은 '
                           '덮이고, 바로 아래 \'되돌리기\'로 한 번 되돌릴 수 있습니다. 관심종목 표의 매입가·수량은 건드리지 않습니다.')
                ca, cb = st.columns(2)
                if ca.button('계좌 보유를 앱 보유종목으로 가져오기', key='sw_sync_pos'):
                    import portfolio as _pf
                    _rows = broker_kis.balance_to_rows(acct)
                    _pos, _warns = _pf.rows_to_positions(_rows, source_type='kis_sync', resolve_market=ctx['resolve_market'])
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


def _view_orders(st, uk, c, ctx, md):
    """주문·체결 — 실행 상태 수 · 최근 주문의 생애 타임라인(계획 → 한도 통과 → 접수 → 체결/취소/거절/확인 중) · 전체 표."""
    theme = ctx['theme']
    its = ctx['intents']
    eh = _dash.execution_health(its)
    st.markdown(_viz.kv_card('실행 상태(주문 사건)',
                             [('주문 전체', str(eh['total'])), ('증권사 접수', str(eh['ack'])), ('체결', str(eh['filled'])),
                              ('일부 체결', str(eh['partial']), 'warn' if eh['partial'] else None),
                              ('확인 중(UNKNOWN · 다시 보내지 않음)', str(eh['unknown']), 'warn' if eh['unknown'] else None),
                              ('거절', str(eh['rejected']), 'neg' if eh['rejected'] else None), ('취소', str(eh['cancelled']))], theme=theme),
                unsafe_allow_html=True)
    if not its:
        st.caption('아직 주문이 없습니다.')
        return
    _title(st, '최근 주문의 생애(최근 5건 · 시간순)', theme)
    for it in list(reversed(its))[:5]:
        head = (f"{it['trade_day']} · {it['code']} · {'매수' if it['side'] == 'buy' else '매도'} · "
                f"{ {'entry': '진입', 'target': '1차 목표', 'stop': '손절', 'expiry': '기간 만료'}.get(X._base(it.get('reason')), it.get('reason')) } · "
                f"수량 {it['qty']} · {_won(it['price']) if it['price'] else '시장가'} · 지금 {STATE_KO.get(it['state'], it['state'])}")
        st.markdown(_viz.timeline(_dash.order_timeline(L.events_of(c, it['intent_id'])), theme=theme, title=head), unsafe_allow_html=True)
    st.dataframe([{'날짜': it['trade_day'], '종목': it['code'], '방향': '매수' if it['side'] == 'buy' else '매도',
                   '이유': {'entry': '진입', 'target': '1차 목표', 'stop': '손절', 'expiry': '기간 만료'}.get(X._base(it.get('reason')), it.get('reason')),
                   '수량': it['qty'], '가격': _won(it['price']) if it['price'] else '시장가',
                   '상태': STATE_KO.get(it['state'], it['state']), '체결': it.get('filled_qty') or 0,
                   '모드': MODE_KO.get(it['mode'], it['mode']), '메모': (it.get('detail') or '')}
                  for it in reversed(its[-200:])], hide_index=True, width='stretch')


def execution_quality(its, rc, min_n=30):
    """실행 품질 — 주문 수 · 체결률 · 부분 체결률 · 거절률 · 확인 중 비율 · 평균 슬리피지. 주문이 min_n 미만이면 **비율을 내지 않고** 수만(§3)."""
    eh = _dash.execution_health(its)
    sm = _sp.summary(rc)
    out = dict(n=eh['total'], counts=eh, rates=None, slip_entry=(sm or {}).get('slip_entry_mean'), slip_exit=(sm or {}).get('slip_exit_mean'),
               n_closed=(sm or {}).get('n', 0))
    if eh['total'] >= min_n:
        n = float(eh['total'])
        out['rates'] = dict(filled=eh['filled'] / n * 100.0, partial=eh['partial'] / n * 100.0, rejected=eh['rejected'] / n * 100.0,
                            unknown=eh['unknown'] / n * 100.0)
    return out


def _view_proof(st, uk, c, ctx, md):
    """성과·PROOF — 영수증 폭포(계획 vs 실제) · 요약 · 실행 품질. '순수익'이라 부르지 않는다(실제 수수료·세금 미수신 · 라운드 453)."""
    theme = ctx['theme']
    rc = _sp.receipts(c, ctx['cost'])
    closed = [r for r in rc if r.get('closed_day')]
    st.caption('자동매매가 열고 닫은 보유마다 계획 진입가와 실제 평균 체결가, 청산 사유와 계획 청산가 대비 실제 청산가를 적습니다. '
               f"수익률은 세 겹입니다 — 실제 체결가 수익률(비용 전) · 운영 왕복 비용 {ctx['cost'] if ctx['cost'] is not None else '미상'}%(가정) · "
               '추정 비용후 수익률(앞의 둘의 차). 실제 수수료·세금은 증권사에서 읽지 않으므로 \'실제 순수익\'이 아닙니다. '
               '같은 계획을 일봉으로 되돌려 채점한 결과(원장 기준)도 옆에 둡니다. 좋고 나쁨은 말하지 않습니다.')
    _ln447 = _sp.summary_line(_sp.summary(rc), ctx['cost'])
    if _ln447:
        st.caption(md(_ln447))
    if not rc:
        st.caption('아직 자동매매가 열고 닫은 보유가 없습니다 — 첫 거래가 닫히면 여기 계획 vs 실제 폭포가 생깁니다.')
    for r in list(reversed(closed))[:5]:
        _title(st, f"{r['receipt_id']} · {r['code']} · {r.get('opened_day')} → {r.get('closed_day')} · "
                   f"{_sp.EXIT_KO.get(r.get('exit_reason'), r.get('exit_reason') or '—')} · 원장 기준 재채점 {_pct(r.get('shadow_net_pct'))}", theme)
        st.markdown(_viz.waterfall(_dash.receipt_waterfall(r), theme=theme), unsafe_allow_html=True)
        st.caption(f"계획 진입 {_won(r['entry_plan'])} → 실제 {_won(r['entry_fill'])}({_pct(r['slip_entry_pct'])}) · 계획 청산 {_won(r['exit_plan'])} → "
                   f"실제 {_won(r['exit_fill'])}({_pct(r['slip_exit_pct'])}) · 실제 체결가 수익률 {_pct(r['gross_pct'])} · 추정 비용후 {_pct(r['net_pct'])}")
    if rc:
        st.dataframe([{'영수증': r['receipt_id'], '종목': r['code'], '산 날': r.get('opened_day') or '—',
                       '닫은 날': r.get('closed_day') or ('보유 중' if r.get('open') else '—'), '수량': r['qty'],
                       '계획 진입가': _won(r['entry_plan']), '실제 진입가': _won(r['entry_fill']),
                       '진입 슬리피지': _pct(r['slip_entry_pct']),
                       '청산 사유': _sp.EXIT_KO.get(r.get('exit_reason'), r.get('exit_reason') or '—'),
                       '계획 청산가': _won(r['exit_plan']), '실제 청산가': _won(r['exit_fill']),
                       '청산 슬리피지': _pct(r['slip_exit_pct']),
                       '실제 체결가 수익률(비용 전)': _pct(r['gross_pct']), '추정 비용후 수익률': _pct(r['net_pct']),
                       '원장 기준 재채점(같은 계획)': _pct(r['shadow_net_pct']), '메모': ' · '.join(r['notes'])}
                      for r in reversed(rc)], hide_index=True, width='stretch')
    eq = execution_quality(ctx['intents'], rc)
    rows = [('주문 수', str(eq['n'])), ('닫힌 거래', str(eq['n_closed']))]
    if eq['rates']:
        rows += [('체결률', f"{eq['rates']['filled']:.1f}%"), ('부분 체결률', f"{eq['rates']['partial']:.1f}%"),
                 ('거절률', f"{eq['rates']['rejected']:.1f}%"), ('확인 중 비율', f"{eq['rates']['unknown']:.1f}%")]
    else:
        rows.append(('비율', f"주문 30건 미만이라 내지 않습니다(지금 {eq['n']}건)"))
    if eq['slip_entry'] is not None:
        rows.append(('평균 진입 슬리피지', f"{eq['slip_entry']:+.2f}%"))
    if eq['slip_exit'] is not None:
        rows.append(('평균 청산 슬리피지', f"{eq['slip_exit']:+.2f}%"))
    st.markdown(_viz.kv_card('실행 품질 — 전략이 틀렸는지 실행이 나빴는지 가르는 재료', rows, theme=theme), unsafe_allow_html=True)
    try:
        import proof
        rl = proof.reco_line(proof.load_scorecard())
    except Exception:                                          # noqa: BLE001
        rl = None
    if rl:
        st.caption(md('안 산 판단도 같은 채점기로 셉니다(가늠 PROOF · 홈 카드와 같은 산출물) — ' + rl))


def _view_system(st, uk, c, ctx, md):
    """시스템 — 지금 진행 중인가 · 작업 스케줄러 · 설정(모드·한도·연결 정보·연결 확인·계획 갱신) · 먼저 알아 두실 것 · 운영 방법 · 제품 벤치마크."""
    theme = ctx['theme']
    _on457, _every457 = acct_refresh_pref(st.session_state, ctx['stt'])
    _auto454 = dict(on=(_on457 and ctx['allow_write']), every=_every457,
                    last=((st.session_state.get('sw_acct_live') or {}).get('ts') or '')[11:19] or None)
    _prog454 = _ops.progress(worker=ctx['worker'], tasks={_ops.TASK_NAME: ctx['task'], _ops.WATCH_TASK: _ops.scheduled_task(_ops.WATCH_TASK)},
                             nightly=ctx['nightly'], auto=_auto454)
    uk.rows([(p['label'], (('실행 중 · ' if p['running'] else ('확인 불가 · ' if p['running'] is None else '')) + p['text']),
              ('pos' if p['running'] else ('warn' if p['running'] is None else ''))) for p in _prog454],
            theme=theme, title='지금 진행 중인가 — 워커 · 예약 작업 · 저녁 작업 · 자동 갱신')
    st.caption(md(_ops.task_line(ctx['task'])))
    st.caption(md(_nt.status_line(ctx['stt'])))               # 라운드 463 — 이 PC 알림(켜짐·꺼짐 · 마지막으로 띄운 때)
    st.caption(md(f"연결 정보: {broker_kis.config_summary(ctx['cfg'])}" + (' · ' + ' · '.join(ctx['cfg']['problems']) if ctx['cfg'].get('problems') else '')
                  + f" · 자동 관리 중 {len(ctx['managed'])}종목" + (f" · 되돌려 받기 확인 중 {len(ctx['releasing'])}종목" if ctx['releasing'] else '')))
    with st.expander('설정 — 모드 · 주문 방식 · 실전 잠금 · 위험 한도 · 연결 정보 · 연결 확인 · 계획 갱신 · 이 PC 알림', expanded=False):
        if not ctx['allow_write']:
            st.caption('쓰기가 꺼진 화면이라 설정을 바꿀 수 없습니다.')
        _settings(st, c, ctx['stt'], ctx['mode'], ctx['cfg'], ctx['allow_write'], ctx['report'], ctx['today'], md)
    with st.expander('먼저 알아 두실 것 — 자세히', expanded=False):
        for ln in (ctx.get('facts') or [])[1:]:
            st.caption(md(ln))
    with st.expander('운영 방법 — 자격증명 · 연결 확인 · 워커', expanded=False):
        st.markdown(md(
            "1. 한국투자 API 포탈에서 앱 키를 받습니다. **채팅·코드·저장소에 붙이지 마세요.** 이미 어딘가에 붙였다면 재발급하세요.\n"
            "2. 위 설정의 '한국투자 연결 정보' 가려진 칸에 직접 넣습니다(저장은 저장소 밖 `~/.gaeum/kis.env` 에만). 환경변수로 넣어도 됩니다 — "
            "`KIS_ENV`(demo 또는 real) · `KIS_APP_KEY` · `KIS_APP_SECRET` · `KIS_ACCOUNT_NO`(계좌 앞 8자리) · "
            "`KIS_ACCOUNT_PRODUCT_CODE`(뒤 2자리). 환경변수는 앱을 다시 띄워야 읽힙니다.\n"
            "3. 설정의 **'연결 확인'** 을 누릅니다(잔고만 읽고 주문은 안 합니다). 관제실 지휘 띠의 '한국투자'가 정상이고 마지막으로 잔고를 읽은 "
            "시각이 보이면 그것이 연결이 정상이라는 증거입니다.\n"
            "4. 실전: 실전 자격증명 · 위험 한도 여섯 · 잠금 해제 문장 · 긴급정지 꺼짐이 모두 맞아야 켜집니다. 처음에는 거래당 "
            "최대 손실을 작게 두고 주문 방식은 '계획마다 승인'으로 두기를 권합니다. 워커는 평일 아침 Windows 작업(`gaeum-swing-worker` · "
            "`scripts/register_swing_worker_task.ps1` 로 한 번 등록 · 등록됐는지는 위 줄과 관제실 상태 띠가 직접 읽어 보입니다)이 정규장 마감까지 "
            "돌리고(장중에 워커가 죽으면 작업 스케줄러가 10분 안에 다시 부릅니다 — 등록 스크립트의 기본값 · 그날 마감 뒤 바퀴까지 끝냈으면 다시 불려도 안 돕니다), 직접 켜려면 `python scripts/run_swing_worker.py --loop 60` 입니다. PC 가 꺼져 있거나 잠들면 워커도 없습니다 — "
            "정규장 동안 절전을 끄세요. '주문·체결' 갈래에서 계획 · 접수 · 체결 · 손절·목표가 계약대로 움직이는지 봅니다.\n"
            "5. 멈추기: 모드를 '꺼짐'으로 두면 새 매수가 멈춥니다. 자동 관리 중인 종목의 손절·목표 보호는 꺼짐에서도 계속되고, 그것까지 "
            "멈추려면 '포지션' 갈래에서 '되돌려 받기'를 누릅니다(걸려 있는 목표 매도의 취소가 확인된 뒤 해제됩니다). 긴급정지는 새 매수를 막고 열린 "
            "매수를 취소할 뿐 보호 매도는 그대로입니다."))
    with st.expander('제품 벤치마크 — 경쟁 서비스와 가늠(내부 우선순위용 · 점수 없음)', expanded=False):
        _cr.render(st, uk, theme=theme, md=md)


def _settings(st, c, stt, mode, cfg, allow_write, report, anchor_day, md):
    modes = mode_options(mode, cfg)          # 라운드 453 — 기본은 꺼짐·실전 둘(모의투자 자격증명이거나 그 모드일 때만 더 보인다)
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
    st.caption("'계획마다 승인'(기본)은 '오늘 계획' 갈래에서 승인한 계획만 삽니다 · '완전 자동'은 실주문 자격이 있는 계획을 워커가 그대로 삽니다. "
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
    # 긴급정지 토글은 라운드 453 부터 맨 위 상태 띠에 있다(한 곳) — 여기서는 설명만.
    st.caption('긴급정지 토글은 관제실 지휘 띠 오른쪽에 있습니다 — 켜면 새 매수를 안 내고 열린 매수 주문을 취소합니다. 관리 중인 종목의 '
               '손절·목표 매도는 계속합니다.')
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
    st.caption("'연결 확인'은 토큰을 받고 잔고를 한 번 읽습니다(주문은 안 합니다). '계획 갱신'은 증권사를 부르지 않고 그날 "
               "리포트에서 계획을 남기고 일봉으로 되돌려 채점합니다 — 운용 모드와 무관합니다(꺼짐이어도 남깁니다).")
    a, b = st.columns(2)
    if allow_write and a.button('연결 확인', key='sw_health'):
        try:
            br = broker_kis.KisBroker(cfg)
            hc = br.health_check()
            if hc['ok']:
                L.account_snapshot(c, br.env, hc.get('balance') or br.get_balance())   # 라운드 459 — 확인에서 읽은 잔고를 그대로(두 번 안 읽는다)
                st.success(hc['message'])
            else:
                st.warning(hc['message'])
        except broker_kis.BrokerError as e:
            st.warning(str(e))
    if st.session_state.get('sw_flash'):
        st.success(st.session_state.pop('sw_flash'))
    if allow_write and b.button('계획 갱신 (증권사 안 부름)', key='sw_refresh'):
        from verdict_core import COST_PCT
        import bitemporal_engine as be
        eng = be.BitemporalEngine()
        # 화면에서는 주문하지 않는다 — 워커와 같은 함수로 계획과 일봉 재채점만(증권사 안 부름 · 모드와 무관 · 라운드 453)
        pn, sn, notes = X.refresh_plans(c, report, anchor_day, lambda code: eng.fetch_daily_bars(f'{code}.KS'), COST_PCT)
        st.session_state['sw_flash'] = (f'새 계획 {pn}건 · 일봉 재채점 갱신 {sn}건 (주문 없음)'
                                        + (f" · {len(notes)}건 못 굴림" if notes else ''))
        st.rerun()
    # 라운드 463 — 이 PC 알림. 밖으로 보내지 않는다(메일·메신저·웹훅 없음 · 계좌 자료가 나가지 않게). 기본 꺼짐.
    st.markdown('**이 PC 알림 (Windows)**')
    st.caption('자동매매의 체결 · 일부 체결 · 거절 · 응답 없음 · 매수 주문 접수 · 보호 매도(손절·기간 만료) 접수 · 관리 끝과 워커 경고를 '
               '이 PC 의 Windows 알림으로 띄웁니다. 메일·메신저·웹훅으로는 보내지 않습니다(계좌 자료가 밖으로 나가지 않게). '
               '1차 목표 지정가 매도는 날마다 다시 걸리므로 접수는 안 알리고 체결·거절만 알립니다. 같은 날 같은 문장은 한 번만 뜨고, '
               '워커가 도는 동안 이 PC 에 로그인해 있어야 보입니다.')
    _on463 = _nt.notify_on(stt)
    if allow_write:
        _new463 = st.toggle('이 PC 알림 켜기', value=_on463, key='sw_notify')
        if bool(_new463) != _on463:
            L.set_setting(c, _nt.NOTIFY_KEY, {'on': bool(_new463)})
            st.rerun()
        if st.button('알림 시험 — 지금 한 번 띄웁니다', key='sw_notify_test'):
            _ok463, _why463 = _nt.toast('가늠 알림 시험', '자동매매 알림이 이 PC 에 이렇게 뜹니다 — 밖으로 보내지 않습니다')
            st.session_state['sw_flash'] = ('알림을 띄웠습니다 — 화면 오른쪽 아래(알림 센터)를 보세요' if _ok463
                                            else f'알림을 못 띄웠습니다 — {_why463}')
            st.rerun()
    else:
        st.caption('지금: ' + ('켜짐' if _on463 else '꺼짐'))
