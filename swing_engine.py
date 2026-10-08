# -*- coding: utf-8 -*-
"""
스윙 계획 SWING_V1 (라운드 446) — **새 판단을 만들지 않는다.** 그날 고정된 개장 전 리포트의 중앙 판정을 그대로 옮긴다.

■ 계약 — 화면이 신규 매수자에게 말하는 그 계획
  진입   중앙 판정의 진입가(매수 검토 구간의 가운데 · 호가 단위로 **내림** — 계획보다 비싸게 사지 않는다) · 지정가
  대기   진입가에 닿기를 최대 `wait_bars` 거래일 기다린다 — 그 수는 라운드 32 진입 연구 산출물(`data/entry_fill_facts.json`
         의 `max_bars`)에서 읽는다(새 숫자 아님). 못 읽으면 실주문 계획을 안 만든다(§3)
  청산   1차 목표(호가 단위로 내림 · 지정가) 또는 손절(닿으면 시장가) · 둘 다 안 닿으면 체결 다음 날부터 `horizon` 거래일
  같은 봉 목표·손절 모두 닿음 → 손절 먼저(채점기 `prediction_log.first_touch` 의 규칙 그대로)
  추가매수·물타기·분할·추적 손절 없음 · 추격 없음(진입가를 벗어나면 안 산다)
  지금 가격(실주문) · 그날 시가(모의)가 이미 손절선 이하면 안 산다 — 라운드 32 연구의 계약에는 없던 한 줄이다(그 가격에 사면
  바로 손절이라 비용만 낸다 · 2026-10-08 독립 검토). 그래서 이 계약의 모의 결과는 그 연구의 수와 조금 다를 수 있다.

■ 이 계약의 지금까지 실측 (화면이 같이 적는다 · 숫자는 산출물에서 읽는다)
  라운드 32 · 2026-08-05 · 매수권 신호 5,389건 · 일봉 모의 — 20봉 안에 78.3% 가 진입가에 닿았고 닿은 뒤 비용 차감 평균은
  −0.45%(블라인드 −1.33%) · 신호당 −0.35%. 이 엔진의 매수권 신호에는 실전에서 재현되는 비용 차감 우위가 없다(§9).

■ 실주문 자격 (LIVE·PAPER) — 중앙 판정이 **추천**(조건 11개 전부 통과)이고 주식이고 가격 셋이 정합이고 리포트가 오늘
  판정일의 것일 때만. 나머지는 '기록만'(SHADOW)으로 모의 결과만 남는다 — 무엇이 막았는지 사유와 함께.
"""
import hashlib
import json
import os

import broker_kis

SPEC = 'SWING_V1'
PROJ = os.path.dirname(os.path.abspath(__file__))


def code6(sym):
    return str(sym or '').split('.')[0]


def wait_bars():
    """진입 대기 거래일 — 라운드 32 연구의 `max_bars`. 못 읽으면 None."""
    try:
        import entry_facts
        d = entry_facts.load() or {}
        v = d.get('max_bars')
        return int(v) if v else None
    except Exception:                                          # noqa: BLE001
        return None


def contract_facts():
    """이 계약의 실측 한 줄 재료(산출물 그대로) — 못 읽으면 None."""
    try:
        import entry_facts
        d = entry_facts.load() or {}
        a = (d.get('splits') or {}).get('all') or {}
        b = (d.get('splits') or {}).get('blind') or {}
        return dict(made=d.get('made'), n=a.get('n'), fill_rate=a.get('fill_rate'), ret=a.get('ret'),
                    ev_sig=a.get('ev_sig'), blind_ret=b.get('ret'), cost_pct=d.get('cost_pct'), max_bars=d.get('max_bars'))
    except Exception:                                          # noqa: BLE001
        return None


def _f(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def entry_of(core):
    """중앙 판정의 진입가 — 매수 검토 구간(진입가 ±1%)의 가운데. 구간이 없으면 None."""
    bz = (core or {}).get('buy_zone')
    if not bz or len(bz) != 2 or bz[0] is None or bz[1] is None:
        return None
    return (float(bz[0]) + float(bz[1])) / 2.0


def plan_id(code, data_day, entry, target, stop, engine_version):
    body = json.dumps([SPEC, code, data_day, entry, target, stop, engine_version], ensure_ascii=False)
    return 'SW1-' + str(data_day).replace('-', '') + '-' + code + '-' + hashlib.sha1(body.encode('utf-8')).hexdigest()[:6].upper()


def plan_from_pick(pick, data_day, engine_version, today_day, wbars):
    """리포트 후보 하나 → 계획 dict. 실주문 자격이 없으면 live_ok=False 와 사유(맨 앞의 것 하나)."""
    core = (pick or {}).get('core') or {}
    code = code6(pick.get('symbol') or pick.get('code'))
    e_raw = entry_of(core)
    entry = broker_kis.round_to_tick(e_raw, 'buy') if e_raw else None
    t_raw = _f(core.get('new_target'))
    target = broker_kis.round_to_tick(t_raw, 'sell') if t_raw else None
    stop = _f(core.get('new_stop'))
    horizon = core.get('horizon_days')
    why = []
    if str(data_day) != str(today_day):
        why.append(f'리포트 판정일 {data_day} 가 오늘 판정일 {today_day} 와 다릅니다')
    if core.get('recommended') is not True:
        why.append('추천 아님 — ' + str(core.get('exclude_reason') or core.get('bucket') or '중앙 판정이 막았습니다'))
    if str(pick.get('asset_type') or 'stock') != 'stock':
        why.append('주식이 아닙니다(이 버전은 주식만 · ETF 호가 단위를 확인하지 않았습니다)')
    if not (entry and target and stop and horizon):
        why.append('진입가·목표·손절·기간 중 비어 있는 것이 있습니다')
    elif not (stop < entry < target):
        why.append(f'가격 정합이 깨졌습니다(손절 {stop:,.0f} · 진입 {entry:,.0f} · 목표 {target:,.0f})')
    if core.get('incoherence'):
        why.append('중앙 판정이 정합 문제를 적었습니다')
    if wbars is None:
        why.append('진입 대기 기간을 연구 산출물에서 못 읽었습니다')
    return dict(plan_id=plan_id(code, data_day, entry, target, stop, engine_version), data_day=str(data_day),
                code=code, name=pick.get('name'), spec=SPEC, entry=entry, target=target, stop=stop,
                horizon=int(horizon) if horizon else None, wait_bars=wbars, live_ok=not why,
                block_reason=(why[0] if why else None),
                verdict=dict(recommended=core.get('recommended'), bucket=core.get('bucket'),
                             exclude_reason=core.get('exclude_reason'), headline=core.get('headline'),
                             # 라운드 450 — 조건 통과·미충족은 중앙 판정의 `checks` 에서만 센다(R312·R316 과 같은 규칙 · 없으면 None)
                             checks_n=(len(core['checks']) if isinstance(core.get('checks'), list) else None),
                             failed=([str(ck.get('name')) for ck in core['checks'] if isinstance(ck, dict) and not ck.get('ok')]
                                     if isinstance(core.get('checks'), list) else None),
                             expected_return=_f(core.get('expected_return')), wait_curable=core.get('wait_curable'),
                             current_price=_f(core.get('current_price'))),
                engine_version=engine_version)


def plans_from_report(report, today_day):
    """그날 리포트 → 계획 목록. 리포트가 없으면 빈 목록(지어내지 않는다)."""
    if not report:
        return []
    try:
        import premarket
        dday = premarket.data_day_of(report) or report.get('date')
    except Exception:                                          # noqa: BLE001
        dday = report.get('date')
    wb = wait_bars()
    out = []
    for p in (report.get('picks') or []):
        try:
            out.append(plan_from_pick(p, dday, report.get('engine_version'), today_day, wb))
        except Exception:                                      # noqa: BLE001 — 후보 하나가 이상해도 다른 계획·보호 매도를 막지 않는다
            continue
    return out


# ── 기록만(SHADOW) 모의 — 같은 계약을 일봉으로 ─────────────────────────
def _rows(df):
    if df is None or 'trade_date' not in getattr(df, 'columns', ()):
        return []
    def col(*n):
        for x in n:
            if x in df.columns:
                return x
        return None
    co, ch, cl, cc = col('open_raw', 'open'), col('high_raw', 'high'), col('low_raw', 'low'), col('close_raw', 'close', 'adj_close')
    out = []
    for _, r in df.sort_values('trade_date').iterrows():
        try:
            out.append((str(r['trade_date'])[:10], float(r[co]) if co else None, float(r[ch]), float(r[cl]), float(r[cc])))
        except (TypeError, ValueError):
            continue
    return out


def shadow_grade(plan, bars_df, cost_pct):
    """계획 하나를 그 계약대로 일봉에서 굴린다 → dict(status, fill_day, fill_price, exit_status, return_pct, net_pct, detail).

    status: 'waiting'(아직 대기 중) · 'no_fill'(대기 기간에 진입가에 안 닿음) · 'open'(체결 · 아직 보유 중) · 'closed'.
    체결가: 그날 시가가 진입가 아래면 시가(지정가 주문은 더 싸게 체결된다) · 아니면 진입가. 체결한 날의 봉은 청산 판정에
    안 쓴다(같은 봉 안에서 무엇이 먼저였는지 모른다) — 다음 날부터 채점기(`prediction_log.grade_prediction`)를 그대로 부른다."""
    import prediction_log as plog
    rows = [r for r in _rows(bars_df) if r[0] > str(plan['data_day'])]
    wb = plan.get('wait_bars')
    if not plan.get('entry') or not wb:
        return dict(status='invalid', detail='진입가 또는 대기 기간이 없습니다')
    fill = None
    for i, (d, o, h, lo, c) in enumerate(rows[:wb]):
        # 실주문과 같게 — 시가가 이미 손절선 이하인 날은 사지 않는다(그 가격에 사면 바로 손절이다 · 워커도 그날 안 산다)
        if o is not None and plan.get('stop') is not None and o <= plan['stop']:
            continue
        if lo <= plan['entry']:
            px = o if (o is not None and o <= plan['entry']) else plan['entry']
            fill = (d, float(px))
            break
    if fill is None:
        return dict(status='no_fill' if len(rows) >= wb else 'waiting',
                    detail=f'{min(len(rows), wb)}/{wb} 거래일 동안 진입가에 안 닿음')
    row = dict(date=fill[0], price=fill[1], target=plan['target'], stop=plan['stop'], horizon_days=plan['horizon'])
    g = plog.grade_prediction(row, bars_df)
    if not g:
        return dict(status='open', fill_day=fill[0], fill_price=fill[1], detail='체결 · 다음 봉 전')
    if g['outcome'] == 'OPEN' and not g.get('matured'):
        return dict(status='open', fill_day=fill[0], fill_price=fill[1], detail=f"체결 · {g.get('bars_used')}봉 보유 중")
    ex = {'TARGET': 'target', 'STOP': 'stop'}.get(g['outcome'], 'expired')
    ret = float(g['return_pct'])
    return dict(status='closed', fill_day=fill[0], fill_price=fill[1], exit_status=ex, return_pct=ret,
                net_pct=(ret - float(cost_pct)) if cost_pct is not None else None,
                detail=f"{g.get('touched_bar') or g.get('bars_used')}봉째")
