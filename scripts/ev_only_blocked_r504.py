# -*- coding: utf-8 -*-
"""라운드 504 — "비용 차감 기대값 빼고 다 통과한 자리가 과거에 몇 번 나왔고, 들어갔으면 벌었나": 과거 원장으로 센다.

    python scripts/ev_only_blocked_r504.py      # data/ev_only_blocked_r504.json 에 쓴다 (GAEUM_NO_LOCAL_WRITE 면 안 쓴다)

■ 이것은 측정이다 — 판정이 아니다
  과거 원장(특히 블라인드)은 이미 여러 라운드가 봤다(R468 표준). 그래서 이 수로 게이트를 바꾸지 않는다 — '비용 차감 기대값'
  게이트의 판정은 사전등록 R475(막힌 후보의 앞으로의 결과)·R478(자동매매 계약 그대로의 모의 결과)이 한다. 이 산출물은 사용자가
  물은 그대로 — *"그 조건 하나 때문에 못 산 자리가 과거에 몇 번이었고 샀다면 어땠나"* — 를 **보이는** 용도다.

■ 앞으로의 자료로는 이미 센다 — 왜 과거 원장을 또 보나
  개장 전 리포트 후보는 중앙 판정의 조건 11개를 전부 싣고 있어 *"그 조건 하나에만 걸린 후보"* 를 정확히 센다(성적표 · R444·R475).
  그런데 2026-07-31 부터라 결과가 닫힌 것이 13건(날짜 10일)뿐이다. 원장은 2011 년부터 25만 행이지만 조건 11개를 다 싣지 않는다 —
  그래서 **다시 만들 수 있는 조건만** 다시 만들고, 못 만드는 것을 숫자로 적는다.

■ 조건 11개 중 무엇을 원장에서 다시 만드나 (결과를 보기 전에 여기 적었다 · 문턱·함수는 운영 것을 그대로 부른다 · 새 숫자 없음)
  ① 권장 매수가 · ② 진입 깊이 · ③ 보유기간 안 도달 · ④ 목표·손절 — 원장 행에 진입가·1차 목표·손절이 있고 손절 < 진입 < 목표인 행.
     (②③ 은 운영에서 늘 1.00σ 로 같은 식이라 늘 통과한다 · 라운드 401 · 앞으로의 후보 233/233 통과)
  ⑤ 손익비 ≥ `verdict_core.MIN_RR` — (목표 − 진입) ÷ (진입 − 손절). 운영은 눌림 진입가에 같은 배수를 건 값이라 비가 같다(R279).
  ⑥ **비용 차감 기대값** — 이것만 가른다. 식은 중앙 판정 그대로(p × 목표폭 + (1 − p) × 손절폭 − 비용) · p 는 **학습 구간 판정 완료
     행으로 다시 센 점수대 적중률**(운영 표는 세 구간 전부로 세므로 과거 검증·블라인드를 가르면 답을 미리 본 것 · R480 ③) · 비용은
     지금 운영 값(`verdict_core.COST_PCT`).
  ⑦ 신뢰도·전략품질 — 원장 `q_confidence` ≥ `MIN_CONF` 이고 `q_strategy_quality` ≥ `MIN_QUALITY` (없으면 미달 · 운영과 같다).
  ⑧ 과열·저유동성 — `next_action.heat_state` 에 볼린저 위치·RSI 를 넣어 운영 규칙(셋 중 둘 이상 읽고 둘 이상 켜짐)으로 센다.
     **W%R 은 원장에 없다** → 과열을 덜 잡을 수 있다(볼린저·RSI 중 하나 + W%R 로 켜지는 행). 거래대금도 원장에 없다 → 운영 규칙대로
     못 잰 것은 거르지 않는다(§3).
  ⑨ 표본외 검증 — 원장에 상태 칸이 없다. 운영에서 검증을 못 하면 전략 품질이 None 이라(라운드 386) ⑦ 이 이미 막는다 — 그래서
     ⑦ 을 통과한 행은 검증을 한 것으로 본다(추론 · 측정 아님).
  ⑩ 강제 차단(거부권 · 국면 게이트) — 다시 만드는 것: 유사패턴 표본 미달(`win_rate` 가 비어 있음 · 라운드 265 의 추론) · 진입 위치
     '추격매수 위험'·'크게 초과' · 분석 신뢰도 50 미만 · 국면 게이트의 신규 매수 차단(`regime_policy.policy` · 원장 국면·변동성).
     **다시 못 만드는 것: '유사패턴 평균 수익(비용 차감) 0 이하' 거부권**(원장에 유사패턴 평균이 없다 · 칸 `net_expected` 는 다른
     값이다 — 전략 백테스트 평균 − 0.30) · 데이터 정합성 거부권. 라운드 3 이 그 거부권의 net>0·≤0 성과 차이를 비용 뒤 +0.03%p 로
     쟀다 — 빠져도 결과를 한쪽으로 끌 근거는 약하지만, 실제보다 많은 행이 '통과'로 들어간다는 사실은 같이 적는다.
  ⑪ 펀더멘털 밸류 검증 — `next_action.value_block` 에 원장 `entry_zone` 을 넣고, 운영이 초과폭(> 0)으로 막는 '소폭 초과'·'초과'는
     구역 이름의 정의(현재가 > 적정가)로 막는다(폭은 원장에 없어 부호만). 원장 구역 '판정 불가'는 운영에서 막힐 수도(모델이
     거부 · OUT_OF_DOMAIN) 안 막힐 수도(못 잼) 있어 **어느 쪽인지 모른다** → 본 표에서 빼고 몇 건인지 적는다.
     (⚠️ 측정 중 정정 — 첫 판은 구역 이름만 넘겨 '소폭 초과'·'초과' 8,784행을 통과로 셌다. 결과를 보고 고친 것이 아니라 운영
     함수가 그 둘을 이름이 아니라 폭으로 가른다는 것을 놓친 것이다 · 고친 판만 싣는다.)

■ 무리와 셈
  · 통계 행만(`ledger_view.stat_rows` · 진입가 축척 어긋남·접미사 복사본 뺌) — 점수 하한 없음(중앙 판정에는 점수 하한이 없다 · R422)
  · 다시 만든 조건 ①~⑤·⑦~⑪ 을 **모두** 통과한 행 = "기대값 빼고 다 통과(재구성)" 무리 → 그 안에서 같은 종목 35일 간격
    (`ledger_view.too_close` · R217) → ⑥ 으로 가른다: 기대값 > 0 = 추천됐을 자리(재구성) · ≤ 0 = **기대값 하나에 막힌 자리(재구성)**
  · 한 자리의 값: 원장의 실현 수익(`return_pct` · 진입가에 바로 산 계약 · 먼저 닿은 선 · 20봉 만료면 그날 종가) − 비용.
    ⚠️ 자동매매 계약(눌림 진입가 지정가 · 최대 20거래일 대기)과는 진입이 다르다 — 그 계약의 결과는 R478 이 앞으로 센다.
  · 구간마다: 건수 · 날짜 수 · 목표 먼저 비율(판정 완료만 · `ledger_view.decided_hit`) · 평균 · 중앙 · 날짜로 묶은 95% 구간
    (`proof.cluster_ci` · 시드 504) · 비교로 '같은 구간 35일 간격 통계 행 전체'의 평균.
  · 문턱 없음 — 0 을 포함하는지만 말한다. 판정 낱말('좋다'·'풀어야 한다')을 쓰지 않는다.

■ 오염 (유리한 쪽 · R468) — 리플레이는 과거 케이스에 오늘의 재무 스냅샷을 쓴다 → 원장 `entry_zone`·`q_confidence` 는 그날 알 수
  없던 재무가 섞였다. 이 셈은 ⑦⑩⑪ 에서 그 칸을 쓴다 — 결과가 실제보다 좋게 보일 수 있는 쪽이다.
"""
from __future__ import annotations

import io
import json
import os
import statistics
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (PROJ, os.path.join(PROJ, 'scripts')):
    if _p not in sys.path:
        sys.path.insert(0, _p)
OUT = os.path.join(PROJ, 'data', 'ev_only_blocked_r504.json')
SEED = 504
BOOT = 2000
SPLITS = ('train', 'valid', 'blind')
UNKNOWN_ZONE = '판정 불가'


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


_BD = {}


def _breakdown():
    """국면 성적 파일 — 한 번만 읽는다(행마다 읽으면 25만 번이다). 못 읽으면 None 그대로 넘겨 운영과 같은 갈래로."""
    import regime_policy as RP
    if 'v' not in _BD:
        _BD['v'] = RP._load()
    return _BD['v']


def rebuilt_checks(row):
    """원장 한 행 → {조건 이름: True/False} (⑥ 기대값은 빼고) · 판단할 수 없으면 그 조건은 None.

    운영 함수·상수를 그대로 부른다(§4 · R192 — 논리를 베끼지 않는다)."""
    import next_action as NA
    import regime_policy as RP
    import verdict_core as VC
    px, tg, st = _num(row.get('price')), _num(row.get('target')), _num(row.get('stop'))
    ok_levels = bool(px and tg and st and st < px < tg)
    rr = ((tg - px) / (px - st)) if ok_levels else None
    conf, qual = _num(row.get('q_confidence')), _num(row.get('q_strategy_quality'))
    ez = str(row.get('entry_zone') or '')
    heat = NA.heat_state({'bb_position_pct': row.get('bb_pos'), 'rsi_value': row.get('rsi')})
    overheated = heat['seen'] >= 2 and heat['hits'] >= 2           # verdict_core._overheated 와 같은 결합 규칙
    try:
        bd = _breakdown()
        pol = RP.policy(row.get('regime'), _num(row.get('vol20')), breakdown=bd) if bd is not None else None
        block_new = bool(pol.get('block_new')) if pol is not None else None
    except Exception:                                          # noqa: BLE001
        block_new = None
    vetoes = []
    if row.get('win_rate') is None:
        vetoes.append('유사패턴 표본 미달(추론)')
    if '추격매수 위험' in ez or '크게 초과' in ez:
        vetoes.append('진입 위치')
    if conf is None or conf < 50:
        vetoes.append('분석 신뢰도 50 미만')
    # 밸류 게이트는 현재가가 적정가보다 위면(초과폭 > 0 · `next_action._OVER_BLOCK_PCT` 0.0) 막는데, 원장에는 그 폭이 없다.
    # 구역 이름은 엔진 `_zone_of` 가 적정가 대비 위치로 정한 것이라 '초과' 셋(소폭 초과 · 초과 · 크게 초과)은 정의상 현재가 > 적정가다
    # → 부호만 쓴다. ⚠️ 첫 판은 구역 이름만 넘겨 '소폭 초과'·'초과'(원장 8,784행)를 통과로 셌다 — 운영 함수가 그 둘은 폭으로 가른다.
    vb_code, _ = NA.value_block({'entry_zone': ez})
    value_ok = (vb_code is None) and ('초과' not in ez)
    return {
        '①~④ 가격 세 칸': ok_levels,
        '⑤ 손익비': (rr is not None and rr >= VC.MIN_RR) if ok_levels else False,
        '⑦ 신뢰도·전략품질': (conf is not None and conf >= VC.MIN_CONF and qual is not None and qual >= VC.MIN_QUALITY),
        '⑧ 과열 아님': not overheated,
        '⑩ 강제 차단 없음(재구성)': (not vetoes) and (block_new is False),
        '⑪ 밸류 검증': (None if ez.startswith(UNKNOWN_ZONE) else value_ok),
    }


def need_p(row, cost):
    """그 계획에서 비용 뒤 기대값이 0 이 되는 목표 먼저 비율(%) — p × 목표폭 + (1 − p) × 손절폭 − 비용 = 0 을 p 로 푼 값.
    새 문턱이 아니라 중앙 판정의 식을 거꾸로 푼 것이다(라운드 472 의 '필요 확률'과 같은 셈). 가격 셋이 안 맞으면 None."""
    px, tg, st = _num(row.get('price')), _num(row.get('target')), _num(row.get('stop'))
    if not (px and tg and st and st < px < tg):
        return None
    up, dn = (tg / px - 1.0) * 100.0, (st / px - 1.0) * 100.0
    return (cost - dn) / (up - dn) * 100.0


def _stats(by_date, hits, boot, seed):
    import proof
    v = [x for xs in by_date.values() for x in xs]
    h = [x for x in hits if x is not None]
    return dict(n=len(v), dates=len(by_date),
                hit=(sum(h) / len(h) * 100.0 if h else None), decided=len(h),
                mean_net=(sum(v) / len(v) if v else None),
                median_net=(statistics.median(v) if v else None),
                ci95=(proof.cluster_ci(by_date, boot, seed) if v else None))


def measure(raw, boot=BOOT, seed=SEED):
    import ledger_view as LV
    import verdict_core
    import ev_gate_past_sim_r480 as R480
    cost = float(verdict_core.COST_PCT)
    if _breakdown() is None:
        # 국면 성적 파일을 못 읽으면 ⑩ 을 다시 만들 수 없다 — 전부 '미달'로 떨어뜨리지 않고 멈춘다(§3 · 0 은 못 잰 것)
        raise SystemExit('국면 성적 파일(regime_breakdown.json)을 못 읽어 국면 게이트를 다시 만들 수 없습니다 — 측정하지 않습니다')
    cnt = {}
    stat = list(LV.stat_rows(raw, keys=LV.scale_mismatch_keys(), counter=cnt))
    ptab = R480.band_p(stat, R480.band_edges(), 'train')
    fails = {}                       # 조건별로 몇 행이 걸렸나(그 조건 하나만이 아니라 걸린 전부)
    unknown_value = 0
    pool, base_pool = [], []
    for r in stat:
        if _num(r.get('return_pct')) is None or r.get('outcome') not in ('TARGET', 'STOP', 'OPEN'):
            continue
        base_pool.append(r)
        ch = rebuilt_checks(r)
        if ch['⑪ 밸류 검증'] is None:
            unknown_value += 1
        for k, v in ch.items():
            if v is False:
                fails[k] = fails.get(k, 0) + 1
        if all(v is True for v in ch.values()):
            pool.append(r)
    sp = R480.spaced(pool)
    base_sp = R480.spaced(base_pool)
    import proof
    out = {}
    for s in SPLITS:
        cells = {'ev_pass': ({}, []), 'ev_only_blocked': ({}, []), 'ev_unknown': ({}, [])}
        blocked_rows = []            # (날짜, 기대값, 비용 뺀 수익, 적중) — '문턱을 낮추면?' 의 셈(R475 ev_order 와 같은 모양)
        needs = []                   # 막힌 자리마다 비용 뒤 0 이 되는 목표 먼저 비율(%)
        for r in sp:
            if r.get('split') != s:
                continue
            sc = _num(r.get('score'))
            ev = R480.gate_ev(r, R480.p_for(sc, ptab), cost) if sc is not None else None
            side = 'ev_unknown' if ev is None else ('ev_pass' if ev > 0 else 'ev_only_blocked')
            by, hits = cells[side]
            net = float(r['return_pct']) - cost
            by.setdefault(str(r.get('date'))[:10], []).append(net)
            hits.append(LV.decided_hit(r))
            if side == 'ev_only_blocked':
                blocked_rows.append((str(r.get('date'))[:10], ev, net, LV.decided_hit(r)))
                _np = need_p(r, cost)
                if _np is not None:
                    needs.append(_np)
        base_by, base_hits = {}, []
        for r in base_sp:
            if r.get('split') != s:
                continue
            base_by.setdefault(str(r.get('date'))[:10], []).append(float(r['return_pct']) - cost)
            base_hits.append(LV.decided_hit(r))
        out[s] = {k: _stats(by, hits, boot, seed) for k, (by, hits) in cells.items()}
        out[s]['all_spaced_rows'] = _stats(base_by, base_hits, boot, seed)
        out[s]['ev_only_blocked']['need_p_median'] = statistics.median(needs) if needs else None
        # '문턱을 낮추면?' — 막힌 자리 안에서 기대값이 0 에 가까운 절반 vs 먼 절반(가르는 값은 그 구간 막힌 자리의 중앙값 · 문턱 없음)
        if len(blocked_rows) >= 4:
            med = statistics.median(e for _, e, _, _ in blocked_rows)
            halves = {}
            for name, keep in (('near_zero', lambda e: e > med), ('far', lambda e: e <= med)):
                by, hits = {}, []
                for d, e, x, h in blocked_rows:
                    if keep(e):
                        by.setdefault(d, []).append(x)
                        hits.append(h)
                halves[name] = _stats(by, hits, boot, seed)
            out[s]['blocked_ev_halves'] = dict(
                median_ev=med, **halves,
                rank_corr=proof._spearman([e for _, e, _, _ in blocked_rows], [x for _, _, x, _ in blocked_rows]))
    return dict(cost_pct=cost, ledger_rows=len(raw), stat_rows=len(stat), dropped=cnt,
                graded_rows=len(base_pool), fails=fails, value_zone_unknown=unknown_value,
                pool_rebuilt=len(pool), pool_spaced=len(sp),
                p_train={f'{lo}~{hi}': p for (lo, hi), p in ptab.items()}, splits=out, seed=seed, boot=int(boot))


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:                                          # noqa: BLE001
        pass
    import ev_gate_past_sim_r480 as R480
    raw = R480.load_rows()
    res = measure(raw)
    res['made'] = __import__('datetime').datetime.now().isoformat(timespec='seconds')
    res['note'] = ('측정 · 판정 아님 — 과거 원장은 이미 봤다(R468) · 조건 11개 중 다시 못 만든 것: 유사패턴 평균 수익 거부권 · '
                   '데이터 정합성 거부권 · W%R · 거래대금 · 진입은 원장 진입가(계약의 눌림 지정가와 다름) · '
                   '판정은 사전등록 R475·R478 의 앞으로의 자료')
    f = lambda x: '—' if x is None else f'{x:+.2f}'                       # noqa: E731
    ci = lambda c: '—' if not c else f'[{c[0]:+.2f}, {c[1]:+.2f}]'       # noqa: E731
    print(f"원장 {res['ledger_rows']:,} · 통계 행 {res['stat_rows']:,} · 채점된 행 {res['graded_rows']:,} · 비용 {res['cost_pct']}")
    print('조건별로 걸린 행', res['fails'], '· 밸류 구역 모름', res['value_zone_unknown'])
    print(f"기대값 빼고 다 통과(재구성) {res['pool_rebuilt']:,}행 → 35일 간격 {res['pool_spaced']:,}건")
    for s in SPLITS:
        o = res['splits'][s]
        for k in ('ev_only_blocked', 'ev_pass', 'ev_unknown', 'all_spaced_rows'):
            c = o[k]
            hit = '—' if c['hit'] is None else f"{c['hit']:.1f}%"
            print(f"  {s} · {k}: {c['n']:,}건(날짜 {c['dates']}) 목표 먼저 {hit} · 평균 {f(c['mean_net'])} "
                  f"{ci(c['ci95'])} · 중앙 {f(c['median_net'])}")
        npm = o['ev_only_blocked'].get('need_p_median')
        if npm is not None:
            print(f"    막힌 자리에서 비용 뒤 0 이 되는 목표 먼저 비율(중앙) {npm:.1f}%")
        hv = o.get('blocked_ev_halves')
        if hv:
            for k in ('near_zero', 'far'):
                c = hv[k]
                print(f"    막힌 자리 중 기대값 {'0 에 가까운' if k == 'near_zero' else '먼'} 절반(중앙 {hv['median_ev']:+.2f}): "
                      f"{c['n']:,}건 평균 {f(c['mean_net'])} {ci(c['ci95'])}")
            rc = hv.get('rank_corr')
            print(f"    순위 상관 {'—' if rc is None else f'{rc:+.3f}'}")
    if not os.environ.get('GAEUM_NO_LOCAL_WRITE'):
        with io.open(OUT, 'w', encoding='utf-8') as fh:
            json.dump(res, fh, ensure_ascii=False, indent=1)
        print('썼다', OUT)
    return 0


if __name__ == '__main__':
    sys.exit(main())
