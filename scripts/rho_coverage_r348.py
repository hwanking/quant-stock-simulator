# -*- coding: utf-8 -*-
"""
라운드 348 — rho 수준별 유사도 커버리지 감사 (사전등록 docs/PREREG_R348_RHO_COVERAGE.md).

판정 기준은 그 문서에 **재기 전에** 적었다. 여기서는 그대로 잰다 — 문턱을 새로 고르지 않는다.
운영 rho(0.80)·표본 하한(5·10)은 **결과와 무관하게 불변**이다. 이 산출물은 사실이지 규칙이 아니다.

규칙을 새로 짓지 않는다: 닮음 판정은 엔진의 `run_self_similarity_backtest` 를 그대로 부르고,
기준일 간격은 이미 채택된 `ledger_view.MIN_GAP_DAYS`(35일 · 25봉의 달력일 표기)를 읽는다.

산출물: data/rho_coverage_r348.json
"""
import datetime
import io
import json
import os
import sys
import time

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
import bitemporal_engine as be                                 # noqa: E402
import forward_registry as fr                                  # noqa: E402
import ledger_view as lv                                       # noqa: E402
import quant_indicators as qi                                  # noqa: E402

OUT = os.path.join(PROJ, 'data', 'rho_coverage_r348.json')
RHOS = (0.90, 0.85, 0.80, 0.75, 0.70)          # 라운드 234 가 미리 적은 다섯 수준
OPERATING_RHO = 0.80                           # 운영 값 — 이 스크립트는 읽기만 한다
N_ASOF = 6                                     # 오늘 + 35일 간격 5개 (사전등록)
HORIZON = lv.HORIZON_BARS                      # 20봉 — 엔진의 판정 창
DATE_FLOOR = 30                                # R1 날짜 하한 (이미 채택된 값)


def _codes():
    """전방 기록부의 가장 최근 기준일에 기록된 종목 전부 (손 목록 아님)."""
    rows = fr.load() if hasattr(fr, 'load') else None
    if rows is None:
        rows = []
        with io.open(os.path.join(PROJ, '.portfolio', 'forward_registry.jsonl'), encoding='utf-8') as f:
            for ln in f:
                ln = ln.strip()
                if ln:
                    try:
                        rows.append(json.loads(ln))
                    except Exception:                          # noqa: BLE001
                        continue
    last = max(str(r.get('date'))[:10] for r in rows)
    codes = sorted({str(r.get('ticker')) for r in rows if str(r.get('date'))[:10] == last})
    return last, codes


def _asof_dates(today):
    gap = datetime.timedelta(days=lv.MIN_GAP_DAYS)
    d = datetime.date.fromisoformat(today)
    return [(d - gap * i).isoformat() for i in range(N_ASOF)]


def main():
    q = qi.QuantIndicatorsEngine()
    eng = be.BitemporalEngine()
    last_day, codes = _codes()
    today = be.resolve_analysis_date().strftime('%Y-%m-%d')
    asofs = _asof_dates(today)
    res = dict(made=datetime.date.today().isoformat(), prereg='docs/PREREG_R348_RHO_COVERAGE.md',
               rhos=list(RHOS), operating_rho=OPERATING_RHO, horizon_bars=HORIZON,
               gap_days=lv.MIN_GAP_DAYS, registry_day=last_day, n_codes=len(codes), asof_dates=asofs)
    # 하한은 엔진이 규칙집에서 읽은 그 값을 그대로 쓴다 — 손으로 5·10 을 적지 않는다 (§2-6 · §4).
    #   엔진 자신이 SAMPLE_TIERS[0][0](관찰) · [1][0](확률)로 읽는다(quant_indicators:847·1637).
    obs_floor = int(q.SAMPLE_TIERS[0][0])
    prob_floor = int(q.SAMPLE_TIERS[1][0])
    res['floors'] = dict(observation=obs_floor, probability=prob_floor)

    per = {f'{r:.2f}': dict(obs_ok=0, prob_ok=0, obs_counts=[]) for r in RHOS}
    cells = 0
    bars_fail = 0
    t0 = time.time()
    for code in codes:
        sym = str(code).split('.')[0]
        try:
            df_all = eng.fetch_daily_bars(sym)
        except Exception:                                      # noqa: BLE001
            df_all = None
        if df_all is None or len(df_all) < 60:
            bars_fail += 1
            continue
        dcol = 'trade_date' if 'trade_date' in df_all.columns else df_all.columns[0]
        days = df_all[dcol].astype(str).str[:10]
        for asof in asofs:
            sub = df_all[days <= asof]
            if len(sub) < 60:
                continue
            tech = q.compute_technical_indicators(sub.reset_index(drop=True))
            cells += 1
            for rho in RHOS:
                r = q.run_self_similarity_backtest(tech, asof, 20, rho, symbol=sym)
                obs = (r or {}).get('observed_match_count')
                if obs is None:
                    obs = (r or {}).get('match_count')
                obs = int(obs or 0)
                k = f'{rho:.2f}'
                per[k]['obs_counts'].append(obs)
                if obs >= obs_floor:
                    per[k]['obs_ok'] += 1
                if obs >= prob_floor:
                    per[k]['prob_ok'] += 1
    res['elapsed_sec'] = round(time.time() - t0, 1)
    res['cells'] = cells
    res['bars_fail'] = bars_fail
    for k, d in per.items():
        c = sorted(d.pop('obs_counts'))
        d['n'] = len(c)
        d['obs_median'] = (c[len(c) // 2] if c else None)
        d['obs_max'] = (c[-1] if c else None)
        d['obs_zero'] = sum(1 for x in c if x == 0)
    res['per_rho'] = per
    base = per[f'{OPERATING_RHO:.2f}']['prob_ok']
    loose = per[f'{min(RHOS):.2f}']['prob_ok']
    res['R0'] = dict(base_prob_ok=base, loosest_prob_ok=loose, gain=loose - base,
                     note='rho 를 가장 낮은 수준까지 낮췄을 때 확률 하한을 새로 넘는 칸 수 (이득 상한)')
    res['verdict'] = ('(가) 드물어서다 — 잣대를 넓히는 연구는 이 근거로는 안 열린다 · rho 불변'
                      if res['R0']['gain'] <= 0 else
                      '(나) 커버리지는 는다 — 보정은 별도 측정 · rho 불변')
    with io.open(OUT, 'w', encoding='utf-8', newline='\n') as f:
        f.write(json.dumps(res, ensure_ascii=False, indent=1) + '\n')
    sys.stdout.write(f"cells={cells} gain={res['R0']['gain']} {res['elapsed_sec']}s\n")


if __name__ == '__main__':
    main()
