# -*- coding: utf-8 -*-
"""라운드 482 — '비용 차감 기대값 양수'를 다르게 볼 길 둘 — 비용 쪽에서 (측정 전용 · 판정 아님 · 운영 비용은 안 바꾼다).

    python scripts/cost_paths_r482.py      # data/cost_paths_r482.json 에 쓴다 (GAEUM_NO_LOCAL_WRITE 면 안 쓴다)

사용자: *"개선해줄 방법 다르게 찾아줘서 개선해줘"*. 지금까지의 길은 전부 확률(p) 쪽이었다(국면 · 조건부 회귀 · 계층 확률 · 청산 규칙).
이 라운드는 비용 쪽이다 — 0.41% 는 수수료 0.03 + 증권거래세 0.20 + 체결 손해 0.18 이고, 뒤의 둘이 **모든 자산·모든 주문에 같다고** 본 값이다.

■ 길 ① 국내 주식형 ETF — 증권거래세가 없다
  '비용 차감 기대값 양수'의 비용 0.41% 중 0.20% 가 증권거래세다(R350). 국내 상장 ETF 는 매도에 증권거래세가 없고, 국내 **주식형**
  ETF 는 매매차익도 비과세다(KB자산운용 · KB Think · 택스넷 안내 · 2026-10-11 확인 · 법령 원문은 안 열었다). 레버리지·인버스·해외·채권 ETF 는
  매매차익에 15.4% 가 붙어 단순한 왕복 비용이 아니므로 뺀다. 그러면 국내 주식형 ETF 의 왕복 비용은 수수료 0.03 + 체결 손해 0.18 = **0.21%**
  다 — 문턱을 낮추는 것이 아니라 그 자산에 맞는 비용이다. 지금 스캐너는 ETF 를 후보에서 뺀다(R164 · 연구 표본 경계).

■ 오염을 걷는 방식은 라운드 480 과 같다 (그 함수들을 부른다 · 결과를 보기 전에 여기 적었다)
  통계 행 → 일반 ETF(asset_type 'ETF') 중 분류표(R170)의 주된 자산이 '국내주식'인 것 → 58점+ → 같은 종목 35일 간격 →
  점수대 확률은 **학습 구간 · 같은 무리(국내 주식형 ETF)** 의 판정 완료 행(n ≥ 30 띠만) → 게이트 식(운영과 같음)을 비용 0.21 로 →
  실현 수익 − 0.21 · 날짜로 묶은 구간. 비교로 주식(같은 절차 · 비용 0.41)도 낸다.
  ⚠️ 분류표는 2026-08-24 한 장이라 그 뒤 상장·폐지·구성 변화는 모른다 · 커버드콜 등 국내 주식형이라도 세제가 다를 수 있다 — 근사다.

■ 길 ② 자동매매 계약의 주문 방식 — 체결 손해 0.18 은 사고팔 때 **둘 다 시장가**라고 본 가정이다
  계약은 진입·1차 목표를 지정가로 낸다(그 자리의 체결 손해는 0 · 대신 불리할 때만 체결되는 손해는 결과 분포에 이미 들어 있다) · 시장가는
  손절·만료로 나갈 때뿐이다. 그 비율 P 를 원장 58점+ 통계 행에서 세면 계약 비용 = 0.03 + 0.20 + 0.09 × P (0.09 = 0.18 의 한 다리).
  후보의 기대값은 비용에 선형이라(R350 과 같은 셈) 지난 개장 전 후보의 기대값에 0.41 − 계약 비용을 더해 몇 개가 0 을 넘는지 센다.
  ⚠️ 0.18 자체가 실제 체결로 잰 적 없는 가정이다 — 이 셈은 '가정을 계약에 맞추면'까지다. 비용을 바꿀지는 실제 체결 자료가 생긴 뒤 사람이 정한다.
"""
from __future__ import annotations

import io
import json
import os
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)
_SCRIPTS = os.path.join(PROJ, 'scripts')
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)
OUT = os.path.join(PROJ, 'data', 'cost_paths_r482.json')
#: 계약 비용의 항목 — 규칙집의 수수료 0.03 · 증권거래세 0.20 · 체결 손해 0.18(왕복)을 그대로 쓴다(새 숫자 아님)
FEE, TAX, SLIP_ROUND = 0.03, 0.20, 0.18
ETF_COST = 0.21          # 수수료 0.03 + 체결 손해 0.18 (규칙집 항목에서 증권거래세 0.20 만 뺀 것 · 새 숫자 아님)
TAXONOMY = os.path.join(PROJ, 'data', 'etf_taxonomy_r170.json')


def domestic_equity_codes(path=TAXONOMY):
    """분류표에서 주된 자산이 '국내주식'인 ETF 코드(6자리) 집합 — 못 읽으면 빈 집합(§3 · 지어내지 않는다)."""
    try:
        with io.open(path, encoding='utf-8') as f:
            d = json.load(f)
    except Exception:                                          # noqa: BLE001
        return set()
    return {str(r.get('code')) for r in d.get('rows') or [] if r.get('dominant') == '국내주식' and r.get('code')}


def contract_cost(stat_rows, score_min=58):
    """계약 비용 = 수수료 + 증권거래세 + 한 다리 체결 손해 × P(손절·만료로 나감) — P 는 58점+ 행의 손절·만료(OPEN) 비율.
    → (비용, P, 구간별 P). 행이 없으면 (None, None, {})."""
    import ev_gate_past_sim_r480 as S
    rows = [r for r in stat_rows if (S._num(r.get('score')) or 0) >= score_min and r.get('outcome') in ('TARGET', 'STOP', 'OPEN')]
    if not rows:
        return None, None, {}
    def share(rs):
        return (sum(1 for r in rs if r.get('outcome') in ('STOP', 'OPEN')) / len(rs)) if rs else None
    p = share(rows)
    by = {sp: share([r for r in rows if r.get('split') == sp]) for sp in S.SPLITS}
    return FEE + TAX + (SLIP_ROUND / 2.0) * p, p, by


def candidates_shift(evs, shift):
    """지난 후보의 기대값(운영 비용으로 뺀 값) → 운영 비용에서 0 넘은 수 · 계약 비용에서 0 넘은 수(비용은 선형)."""
    v = [float(x) for x in evs]
    return dict(n=len(v), pass_ops=sum(1 for x in v if x > 0), pass_contract=sum(1 for x in v if x + shift > 0))


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:                                          # noqa: BLE001
        pass
    import ledger_view as LV
    import ev_gate_past_sim_r480 as S
    raw = S.load_rows()
    stat = list(LV.stat_rows(raw, keys=LV.scale_mismatch_keys()))
    dom = domestic_equity_codes()
    etf = [r for r in stat if r.get('asset_type') == 'ETF' and LV.code6(r.get('ticker')) in dom]
    stock = [r for r in stat if r.get('asset_type') == 'STOCK']
    edges = S.band_edges()
    out = dict(made=__import__('datetime').datetime.now().isoformat(timespec='seconds'), ledger_rows=len(raw),
               taxonomy_codes=len(dom), etf_rows=len(etf), etf_codes=len({LV.code6(r.get('ticker')) for r in etf}),
               etf_cost=ETF_COST, note='측정 · 판정 아님 — 과거 원장(R468) · 앞으로 걸지는 사전등록이 정한다')
    for name, rows, cost in (('etf_domestic_equity', etf, ETF_COST), ('etf_at_041', etf, 0.41), ('stock', stock, 0.41)):
        pool = [r for r in rows if (S._num(r.get('score')) or 0) >= S.SCORE_MIN]
        sp = S.spaced(pool)
        ptab = S.band_p(rows, edges, 'train')
        allrows = S.summarize(sp, {k: -1e9 for k in ptab}, cost)          # 확률을 아주 낮게 → 전부 '막힘' 쪽에 모인다 = 58점+ 전부
        gate = S.summarize(sp, ptab, cost)
        out[name] = dict(cost=cost, pool_58=len(pool), spaced_58=len(sp),
                         p_train={f'{lo}~{hi}': p for (lo, hi), p in ptab.items()},
                         all_58={s: allrows[s]['block'] for s in S.SPLITS}, gate=gate)
    # 길 ② — 계약 비용과, 지난 개장 전 후보 중 몇 개가 0 을 넘었을지
    import proof
    import proof_scorecard as PS
    import verdict_core
    from improvement import case_tracker as CT
    cc, p_mkt, p_by = contract_cost(stat)
    ops_cost = float(verdict_core.COST_PCT)
    latest, _off = proof.latest_by_date(PS.load_reports(), CT.is_non_trading_date)
    evs = [(p.get('core') or {}).get('expected_return') for d in latest.values() for p in (d.get('picks') or [])]
    evs = [x for x in evs if isinstance(x, (int, float)) and not isinstance(x, bool)]
    days = sorted(latest)
    out['contract'] = dict(ops_cost=ops_cost, contract_cost=cc, p_market_exit=p_mkt, p_market_exit_by_split=p_by,
                           fee=FEE, tax=TAX, slip_round=SLIP_ROUND,
                           candidates=dict(candidates_shift(evs, ops_cost - cc) if cc is not None else {},
                                           days=len(days), first=(days[0] if days else None), last=(days[-1] if days else None)))
    print(f"[계약 비용] {FEE} + {TAX} + {SLIP_ROUND / 2:.2f} × {p_mkt:.3f} = {cc:.3f}% (운영 {ops_cost}) · 구간별 P {p_by}")
    print(f"  지난 후보 {out['contract']['candidates']}")
    for name in ('etf_domestic_equity', 'etf_at_041', 'stock'):
        o = out[name]
        print(f"[{name}] 비용 {o['cost']} · 58점+ {o['pool_58']:,} · 35일 간격 {o['spaced_58']:,}")
        print('  학습 확률', {k: (round(v, 4) if v is not None else None) for k, v in o['p_train'].items() if v is not None})
        for s in S.SPLITS:
            a = o['all_58'][s]
            g = o['gate'][s]['pass']
            f = lambda x: '—' if x is None else f'{x:+.2f}'                       # noqa: E731
            ci = lambda c: '—' if not c else f'[{c[0]:+.2f}, {c[1]:+.2f}]'       # noqa: E731
            print(f"  {s}: 58점+ 전부 {a['n']:,}건(날짜 {a['dates']}) 평균 {f(a['mean_net'])} {ci(a['ci95'])} 중앙 {f(a['median_net'])}"
                  f" · 게이트 통과 {g['n']:,}건 평균 {f(g['mean_net'])} {ci(g['ci95'])}")
    if not os.environ.get('GAEUM_NO_LOCAL_WRITE'):
        with io.open(OUT, 'w', encoding='utf-8') as fh:
            json.dump(out, fh, ensure_ascii=False, indent=1)
        print('썼다', OUT)
    return 0


if __name__ == '__main__':
    sys.exit(main())
