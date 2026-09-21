# -*- coding: utf-8 -*-
"""
라운드 349 — 지평별 표본 커버리지. 라운드 348 이 *"안 쟀다"* 고 적은 그 칸을 같은 표본에서 채운다.

라운드 234 가 삼성전자 **한 종목**에서 본 모양(20일 0건인데 5일 195건 · 60일 12건)이 모집단에서도 같은가.
판정 창은 20봉인데(`ledger_view.HORIZON_BARS`) 그 지평이 유독 비는 것이라면, *"매번 산출 불가"* 는
라운드 348 이 밝힌 **기준의 엄격함** 위에 **창의 선택**이라는 결이 하나 더 있는 것이다.

■ 표본을 새로 안 고른다 (§2-6)
  라운드 348 산출물의 **그 종목·그 기준일**을 그대로 읽는다. 오늘 다시 고르면 기준일이 밀려(장 마감 뒤에는
  판정일이 오늘로 옮겨간다) 같은 칸이 아니게 되고, 그러면 R348 의 표와 나란히 못 읽는다.

■ 재는 것은 커버리지뿐이다
  운영 rho(0.80) 하나에서 지평별 관측 건수만 센다. **문턱·창·판정은 아무것도 안 바꾼다** — 이 산출물은
  사실이지 규칙이 아니다(R348 과 같은 자리).

산출물: data/horizon_coverage_r349.json
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
import ledger_view as lv                                       # noqa: E402
import quant_indicators as qi                                  # noqa: E402
import ui_kit as uk                                            # noqa: E402

SRC = os.path.join(PROJ, 'data', 'rho_coverage_r348.json')
OUT = os.path.join(PROJ, 'data', 'horizon_coverage_r349.json')


def main():
    with io.open(SRC, encoding='utf-8') as f:
        src = json.load(f)
    q = qi.QuantIndicatorsEngine()
    eng = be.BitemporalEngine()
    rho = float(src['operating_rho'])
    asofs = list(src['asof_dates'])
    obs_floor = int(q.SAMPLE_TIERS[0][0])
    prob_floor = int(q.SAMPLE_TIERS[1][0])
    horizons = list(uk.HORIZONS_ALL)                           # 화면이 쓰는 그 목록 (§4)

    # 종목은 R348 이 쓴 그 모집단 — 전방 기록부의 같은 기준일에서 다시 읽는다
    rows = []
    with io.open(os.path.join(PROJ, '.portfolio', 'forward_registry.jsonl'), encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                try:
                    rows.append(json.loads(ln))
                except Exception:                              # noqa: BLE001
                    continue
    codes = sorted({str(r.get('ticker')) for r in rows
                    if str(r.get('date'))[:10] == str(src['registry_day'])})

    per = {str(H): dict(obs_ok=0, prob_ok=0, zero=0, counts=[]) for H in horizons}
    cells = 0
    t0 = time.time()
    for code in codes:
        sym = str(code).split('.')[0]
        try:
            df_all = eng.fetch_daily_bars(sym)
        except Exception:                                      # noqa: BLE001
            df_all = None
        if df_all is None or len(df_all) < 60:
            continue
        dcol = 'trade_date' if 'trade_date' in df_all.columns else df_all.columns[0]
        days = df_all[dcol].astype(str).str[:10]
        for asof in asofs:
            sub = df_all[days <= asof]
            if len(sub) < 60:
                continue
            tech = q.compute_technical_indicators(sub.reset_index(drop=True))
            r = q.run_self_similarity_backtest(tech, asof, 20, rho, symbol=sym) or {}
            hz = r.get('horizons_data') or {}
            cells += 1
            for H in horizons:
                h = hz.get(H) or hz.get(str(H)) or {}
                n = int(h.get('match_count') or 0)
                d = per[str(H)]
                d['counts'].append(n)
                d['obs_ok'] += int(n >= obs_floor)
                d['prob_ok'] += int(n >= prob_floor)
                d['zero'] += int(n == 0)
    res = dict(made=datetime.date.today().isoformat(), source=os.path.basename(SRC),
               reused_asof_dates=asofs, registry_day=src['registry_day'], rho=rho,
               judgment_window_bars=lv.HORIZON_BARS,
               floors=dict(observation=obs_floor, probability=prob_floor),
               cells=cells, elapsed_sec=round(time.time() - t0, 1), per_horizon={})
    for H in horizons:
        d = per[str(H)]
        c = sorted(d.pop('counts'))
        res['per_horizon'][str(H)] = dict(
            obs_ok=d['obs_ok'], prob_ok=d['prob_ok'], zero=d['zero'], n=len(c),
            median=(c[len(c) // 2] if c else None), max=(c[-1] if c else None))
    ph = res['per_horizon']
    ranked = sorted(ph, key=lambda k: ph[k]['prob_ok'])
    res['sparsest_horizon'] = int(ranked[0]) if ranked else None
    res['judgment_window_is_sparsest'] = (res['sparsest_horizon'] == lv.HORIZON_BARS)
    with io.open(OUT, 'w', encoding='utf-8', newline='\n') as f:
        f.write(json.dumps(res, ensure_ascii=False, indent=1) + '\n')
    sys.stdout.write(f"cells={cells} sparsest={res['sparsest_horizon']} {res['elapsed_sec']}s\n")


if __name__ == '__main__':
    main()
