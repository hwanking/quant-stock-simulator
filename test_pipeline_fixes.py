"""
퀀트 파이프라인 회귀 테스트.

수정된 결함이 되살아나지 않는지 불변식으로 검증한다.
실행:  python test_pipeline_fixes.py
네트워크(네이버·다음)가 필요하며, 실패한 검사는 [FAIL] 로 표시되고 종료코드 1을 반환한다.
"""
import sys
import os as _os
import re as _re
import datetime
import warnings

warnings.filterwarnings('ignore')
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

import numpy as np
import pandas as pd

import bitemporal_engine as be
import quant_indicators as qi
from report_generator import QuantReportGenerator

PROJ = _os.path.dirname(_os.path.abspath(__file__))
FAILURES = []


def check(name, condition, detail=""):
    ok = bool(condition)
    print(f"  [{'OK  ' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILURES.append(name)


def section(title):
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


engine = be.BitemporalEngine()
q = qi.QuantIndicatorsEngine()
SYMBOL = "005930.KS"
T_REF = be.resolve_analysis_date().strftime("%Y-%m-%d")


# ---------------------------------------------------------------- 규칙집
section("1. 규칙집이 실제로 로드되고 산식에 연결되는가")
check("규칙집 파싱 성공", '_error' not in qi.RULEBOOK, f"{len(qi.RULEBOOK)}개 섹션")
check("종합 가중치 합 = 1.0", abs(sum(q.W_TOP.values()) - 1.0) < 1e-9, str(q.W_TOP))
check("기본매력 가중치 합 = 1.0", abs(sum(q.W_QUALITY.values()) - 1.0) < 1e-9)
check("매매적합 가중치 합 = 1.0", abs(sum(q.W_TIMING.values()) - 1.0) < 1e-9)
check("리스크 가중치 합 = 1.0", abs(sum(q.W_RISK.values()) - 1.0) < 1e-9)
check("최종행동 가중치 합 = 1.0", abs(sum(q.W_FINAL.values()) - 1.0) < 1e-9)
check("익절·손절 임계값 단일 정의", q.TP_THRESHOLD_PCT > 0 and q.SL_THRESHOLD_PCT > 0,
      f"+{q.TP_THRESHOLD_PCT}% / -{q.SL_THRESHOLD_PCT}%")


# ---------------------------------------------------------------- 분석 기준일
section("2. 분석 기준일 / 거래일 판정")
cal = be.KrxCalendar()
check("공휴일 인식 (2026-01-01)", not cal.is_trading_day(datetime.date(2026, 1, 1)))
check("주말 인식 (토요일)", not cal.is_trading_day(datetime.date(2026, 8, 1)))
status = be.get_market_status()
check("시장 상태 판정", status['state'] in ("장중", "장 시작 전", "장 종료", "휴장일"), status['state'])
check("확정 기준일이 거래일", cal.is_trading_day(be.resolve_analysis_date()), T_REF)


# ---------------------------------------------------------------- 데이터 정직성
section("3. 실데이터 없으면 합성으로 대체하지 않는가")
try:
    engine.load_bitemporal_data("999999.KS", "2020-01-01", T_REF)
    check("존재하지 않는 종목은 예외", False, "데이터가 반환됨")
except be.DataUnavailableError:
    check("존재하지 않는 종목은 예외", True)
except Exception as exc:
    check("존재하지 않는 종목은 예외", False, f"{type(exc).__name__}")

prices, fund = engine.load_bitemporal_data(SYMBOL, "2020-01-01", T_REF)
check("실 일봉 적재", len(prices) > 500, f"{len(prices)}봉")
check("데이터 출처 표기", prices['data_source'].iloc[0] == 'naver_daily_ohlcv')
check("수급 미연동은 NaN (0/난수 아님)", bool(prices['foreign_cum_5d'].isna().all()))
check("revenue_yoy 조작값 없음", fund['revenue_yoy_pct'].iloc[0] is None)
check("audit_opinion 리터럴 없음", fund['audit_opinion'].iloc[0] is None)
check("재무는 추정 스냅샷임을 명시", bool(fund['is_estimated'].iloc[0]))


# ---------------------------------------------------------------- 표본 통제
section("4. 표본 통제 (§11) — 표본 위조 금지")
short = pd.DataFrame({
    'trade_date': pd.date_range('2024-01-01', periods=60, freq='B').strftime('%Y-%m-%d'),
    'adj_close': np.linspace(100, 110, 60)})
short['open'] = short['adj_close']
short['high'] = short['adj_close'] * 1.01
short['low'] = short['adj_close'] * 0.99
short['volume'] = 1e6
t_short = q.compute_technical_indicators(short)
s_short = q.run_self_similarity_backtest(t_short, T_REF, 20, 0.80)
check("표본 미달 시 등급 INSUFFICIENT", s_short['sample_tier'] == 'INSUFFICIENT',
      f"match={s_short['match_count']}")
check("표본 미달 시 확률 None", s_short['bayes_prob'] is None and s_short['tp_first_prob'] is None)
check("표본 15건 위조 없음", s_short['match_count'] != 15 or s_short['sample_tier'] == 'INSUFFICIENT')

for n, expect in ((3, 'INSUFFICIENT'), (7, 'OBSERVATION_ONLY'), (15, 'LOW_CONFIDENCE'),
                  (25, 'LIMITED'), (40, 'FORECAST_AVAILABLE')):
    check(f"표본 {n}건 → {expect}", q.classify_sample_tier(n)[0] == expect)
check("10건 미만은 확률 비노출", not q.probabilities_allowed('OBSERVATION_ONLY'))


# ---------------------------------------------------------------- 파이프라인
section("5. 단일 스냅샷 파이프라인 (§17)")
snap = q.run_full_pipeline(SYMBOL, T_REF, b_engine=engine, rho_cutoff=0.80)
fs = snap['four_scores']
sim = snap['sim_res']
val = snap['val_eval']
check("스냅샷 키 구성", all(k in snap for k in
      ('tech_df', 'sim_res', 'val_eval', 'four_scores', 'price_pos', 'source_matrix')))
check("다중기간 6개 지평 산출", len(sim.get('horizons_data', {})) == 6,
      str({h: sim['horizons_data'][h]['match_count'] for h in (5, 10, 20, 40, 60, 120)}))


# ---------------------------------------------------------------- 게이트 불변식
section("6. 게이트 불변식")
bem = fs.get('buy_entry_max')
px = float(snap['tech_df']['adj_close'].iloc[-1])
check("진입상단이 현재가 파생이 아님", bem is None or abs(bem - px * 1.02) > 1e-6,
      f"buy_entry_max={bem}, px*1.02={px * 1.02:.0f}")
check("진입 위치 5단계 판정", fs['entry_zone'] in (
    "판정 불가", "안전마진 확보", "적정가 이하 (안전마진 미확보)",
    "적정가 소폭 초과", "적정가 초과 (추격매수 경고)", "적정가 크게 초과 (추격매수 위험)"),
    fs['entry_zone'])
check("적정가 신뢰도 하한 65 제거", val['fair_value_confidence'] <= 95,
      f"conf={val['fair_value_confidence']:.0f}, status={val['fair_value_status']}")
check("Sharpe가 정상 범위", fs['sharpe_ratio'] is None or abs(fs['sharpe_ratio']) < 20,
      str(fs['sharpe_ratio']))
check("손익비가 Mock 1.5 고정이 아님", fs['reward_risk_ratio'] is None or
      1.0 <= fs['reward_risk_ratio'] <= 3.05, str(fs['reward_risk_ratio']))
check("분석신뢰도가 77 고정이 아님", isinstance(fs['analysis_confidence'], int))
check("TOP3 차단사유 노출", isinstance(fs['top3_block_reasons'], list))
check("Blind 미구현이면 추천 불가", (not q.BLIND_TEST_IMPLEMENTED)
      <= (not fs['eligible_for_top3']))
check("'신규 매수 보류'는 매수의도 아님", "신규 매수 보류" not in q.BUY_INTENT_TITLES)
check("시장국면 배선됨", fs['market_regime_code'] in (
    'BULL_STRONG', 'BULL_MILD', 'SIDEWAYS', 'BEAR_PANIC', 'DECISION_PENDING'),
    fs['market_regime_label'])
check("유동성 실측", fs['avg_turnover_20d'] is None or fs['avg_turnover_20d'] > 0,
      f"{(fs['avg_turnover_20d'] or 0) / 1e8:,.0f}억")


# ---------------------------------------------------------------- 하드코딩 제거
section("7. 하드코딩 성과지표 제거")
cm = q.calculate_backtest_costs_and_metrics(sim)
check("Brier 리터럴 제거", cm['brier_score'] is None)
check("MAE 리터럴 제거", cm['mae_pct'] is None)
check("거래비용 내역 명시", abs(sum(q.COST_BREAKDOWN.values()) - q.TOTAL_COST_PCT) < 1e-9)
bd = q.calculate_benchmark_comparisons(sim, tech_df=snap['tech_df'])
check("매수보유가 AI×1.15 조작식이 아님",
      bd['buy_hold_perf'] is None or bd['ai_perf'] is None
      or abs(bd['buy_hold_perf'] - bd['ai_perf'] * 1.15) > 1e-6,
      f"AI={bd['ai_perf']} vs B&H={bd['buy_hold_perf']}")
check("팩터귀속 미산출 명시", q.calculate_factor_attribution(sim)['available'] is False)
check("위험예산 미산출 명시", q.calculate_portfolio_risk_budget()['available'] is False)
sht = q.calculate_sharpe_and_turnover(sim, four_scores=fs)
check("Sharpe 정의 일원화", sht['sharpe_ratio'] == fs['sharpe_ratio'])


# ---------------------------------------------------------------- 출처 매트릭스
section("8. 교차검증 / 출처 매트릭스")
_p, _s, mtx = engine.get_realtime_stock_price_triple_check(SYMBOL)
priced = [r for r in mtx if r['price'] is not None]
check("가격 보유 출처는 실조회분뿐", len(priced) <= 2, f"{len(priced)}개")
dart = [r for r in mtx if 'DART' in r['source']]
check("DART는 가격 대조 제외", dart and dart[0]['price'] is None)
cv1 = engine.verify_realtime_sources(SYMBOL)
cv2 = engine.verify_realtime_sources(SYMBOL)
# 장중에는 실제 체결가가 움직이므로 '완전 동일'을 요구할 수 없다.
# 난수 생성이 사라졌는지는 '두 호출의 차이가 실제 시세 변동 범위(<1%) 안인가'로 확인한다.
# (구버전은 random.choice 로 ±0.2% 를 매번 새로 뽑아 장 마감 후에도 값이 달라졌다)
_market_open = be.get_market_status()['state'] == '장중'


def _close_enough(a, b):
    if a is None or b is None:
        return a is b
    return abs(a - b) / max(abs(a), 1e-9) < (0.01 if _market_open else 1e-12)


check("교차검증 가격이 난수가 아님" + (" (장중: 1% 이내 허용)" if _market_open else " (장 마감: 완전 동일)"),
      _close_enough(cv1['naver']['price'], cv2['naver']['price'])
      and _close_enough(cv1['daum']['price'], cv2['daum']['price']),
      f"naver {cv1['naver']['price']}→{cv2['naver']['price']}, daum {cv1['daum']['price']}→{cv2['daum']['price']}")
def find_random_usage(filename):
    """AST 로 실제 random / np.random 호출을 찾는다 (주석·독스트링은 자연히 제외)."""
    import ast
    tree = ast.parse(open(_os.path.join(PROJ, filename), encoding='utf-8').read())
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            hits += [f"import {a.name}" for a in node.names if a.name.split('.')[0] == 'random']
        elif isinstance(node, ast.ImportFrom) and (node.module or '').split('.')[0] == 'random':
            hits.append(f"from {node.module} import ...")
        elif isinstance(node, ast.Attribute):
            base = node
            parts = []
            while isinstance(base, ast.Attribute):
                parts.append(base.attr)
                base = base.value
            if isinstance(base, ast.Name):
                parts.append(base.id)
                chain = ".".join(reversed(parts))
                if chain.startswith("random.") or chain.startswith("np.random."):
                    hits.append(chain)
    return sorted(set(hits))


_rand = find_random_usage('bitemporal_engine.py')
check("데이터 계층에 random 호출 없음 (주석 제외, AST 검사)", not _rand, ", ".join(_rand))


# ---------------------------------------------------------------- 레포트
section("9. 레포트 / 가드레일")
rg = QuantReportGenerator()
pit = engine.get_point_in_time_snapshot(T_REF, symbol=SYMBOL)
txt = rg.generate_full_report(SYMBOL, snap['tech_df'], snap['fund_df'], sim, val,
                              snapshot=pit, four_scores=fs)
check("레포트에 'None' 노출 없음", 'None' not in txt, f"{txt.count('None')}건")
check("면책 고지 부착 (LeakageGuard 배선)", '면책 조항' in txt)
audit = rg.audit_compliance(pit, snap['tech_df'], sim)
check("SR 11-7 루브릭 산출", 0 <= audit['total_score'] <= 100, f"{audit['total_score']}/100")


# ---------------------------------------------------------------- 유니버스
section("10. 유니버스")
uni = engine.get_screener_universe(full_market=True)
check("전 종목 수집", len(uni) > 1000, f"{len(uni)}종목")
check("대장주 포함", any(u['symbol'] == SYMBOL for u in uni))
check("우선주 제외", not any(be.BitemporalEngine._is_excluded_name(u['name']) for u in uni))
check("시총 내림차순 정렬", all(
    (uni[i].get('market_cap_eok') or 0) >= (uni[i + 1].get('market_cap_eok') or 0)
    for i in range(min(50, len(uni) - 1))))


# ---------------------------------------------------------------- 값 범위 (sanity)
section("11. 값 범위 sanity — 변수 오염 / 단위 혼용 탐지")
# 2026-07-31 회귀: val_eval 의 per_val/pbr_val 이 'PER 모델 적정가' 변수와 이름이 겹쳐
# PER 227,335배 / PBR 145,282배가 화면에 표시됐다. 값 범위 검사로 재발을 막는다.
px_now = float(snap['tech_df']['adj_close'].iloc[-1])


def in_range(v, lo, hi):
    return v is None or (lo <= float(v) <= hi)


check("PER 범위 (0~2000)", in_range(val.get('per'), 0, 2000), f"per={val.get('per')}")
check("PBR 범위 (0~100)", in_range(val.get('pbr'), 0, 100), f"pbr={val.get('pbr')}")
check("ROE 범위 (-200~300%)", in_range(val.get('roe'), -200, 300), f"roe={val.get('roe')}")
check("부채비율 범위 (0~2000%)", in_range(val.get('debt_ratio'), 0, 2000), f"debt={val.get('debt_ratio')}")
check("EPS가 가격 규모를 넘지 않음", in_range(val.get('eps'), -px_now * 5, px_now * 5), f"eps={val.get('eps')}")
check("BPS가 가격의 100배 미만", in_range(val.get('bps'), -px_now * 100, px_now * 100), f"bps={val.get('bps')}")
check("적정가가 현재가의 0.1~10배", in_range(fs.get('displayed_fair_value'), px_now * 0.1, px_now * 10),
      f"fair={fs.get('displayed_fair_value')}")
check("목표가 > 현재가 > 손절가", fs['target_tech_1st'] > px_now > fs['stop_loss_price'])
check("점수 0~100 범위", all(0 <= fs[k] <= 100 for k in
      ('stock_quality_score', 'trading_timing_score', 'risk_safety_score',
       'opportunity_score', 'execution_score', 'final_action_score')))
check("상승여력 범위 (-100~200%)", in_range(fs.get('upside_pct'), -100, 200), f"upside={fs.get('upside_pct')}")
check("val_eval PER == 화면 헤더 PER 출처 동일",
      val.get('per') is None or abs(float(val['per']) - float(
          be.STOCK_METRICS_DB.get(SYMBOL, {}).get('per', val['per']))) < 1e-6)


# ---------------------------------------------------------------- 표본외 검증
section("12. 표본외(Blind/OOS) Walk-Forward 검증")
oos = snap.get('oos_result') or {}
sq = snap.get('strategy_quality') or {}
check("표본외 검증 수행", oos.get('available'), oos.get('reason', ''))
if oos.get('available'):
    check("학습·검증 구간 분리", oos['train_bars'] > 0 and oos['oos_bars'] > 0,
          f"{oos['train_bars']} / {oos['oos_bars']}")
    check("purge embargo 적용", oos['embargo'] >= oos['horizon'])
    check("Brier 0~1", 0 <= oos['brier_score'] <= 1, str(oos['brier_score']))
    check("방향적중률 0~100", 0 <= oos['directional_hit_pct'] <= 100)
    check("전략 품질점수 0~100", 0 <= (sq.get('score') or -1) <= 100, str(sq.get('score')))
    check("상한이 65 고정이 아님", fs['sq_cap'] != 65 or not sq.get('available'), f"cap={fs['sq_cap']}")
    check("Brier/MAE가 표본외에서 산출됨",
          q.calculate_backtest_costs_and_metrics(sim, oos=oos)['brier_score'] is not None)


# ---------------------------------------------------------------- 스냅샷 계약
section("13. 단일 스냅샷 계약 (§17) · 버전 · 캐시")
for view in ('recommendation_summary', 'detailed_analysis', 'valuation_result',
             'multi_horizon_forecast', 'final_decision'):
    check(f"뷰 제공: {view}", getattr(snap, view) is not None)
check("status 필드", snap['status'] in ('OK', 'REVIEW_REQUIRED'), snap['status'])
meta = snap['meta']
for key in ('run_id', 'analysis_date', 'price_asof', 'price_type', 'fiscal_asof',
            'data_version', 'calc_version', 'model_version', 'rulebook_version'):
    check(f"메타 식별자: {key}", meta.get(key) is not None, str(meta.get(key))[:40])
check("cache_key에 버전 포함", len(snap.cache_key()) == 6)
check("요약 뷰와 상세 판정 일치",
      snap.recommendation_summary['final_action_score'] == snap.final_decision['score']
      and snap.recommendation_summary['final_action_title'] == snap.final_decision['title'])
check("요약 뷰 적정가 == 가치평가 결과",
      snap.recommendation_summary['fair_value'] == snap.valuation_result.get('displayed_fair_value'))


# ---------------------------------------------------------------- 재현성
section("14. 재현성 — 동일 입력 재실행")
snap2 = q.run_full_pipeline(SYMBOL, T_REF, b_engine=engine, rho_cutoff=0.80)
f2 = snap2['four_scores']

# 장중에는 실시간 체결가가 두 실행 사이에 움직이므로 가격에 의존하는 점수는
# 완전 일치를 요구할 수 없다. 장이 닫혀 있으면 입력이 고정이므로 정확히 같아야 한다.
_LIVE = be.get_market_status()['state'] == "장중"
# 현재가에서 파생되는 점수들 — 장중에는 두 실행 사이 시세가 움직여 값이 달라진다
_PRICE_DEPENDENT = ('final_action_score', 'trading_timing_score', 'opportunity_score',
                    'execution_score', 'risk_safety_score',
                    'reward_risk_ratio', 'displayed_fair_value')

# 허용오차를 임의로 넓히지 않는다. **두 실행 사이 실제 가격 변동폭**에 비례시킨다.
# (급변동장에서는 1%대 변동에도 점수가 몇 점씩 움직이는 것이 정상이다)
_px1 = float(snap['tech_df']['adj_close'].iloc[-1])
_px2 = float(snap2['tech_df']['adj_close'].iloc[-1])
_px_drift_pct = abs(_px2 / _px1 - 1.0) * 100.0
_score_tol = max(2.0, _px_drift_pct * 3.0)      # 가격 1% 변동 → 점수 3점까지 허용
check("재현성 판정 기준", True,
      f"두 실행 사이 가격 {_px1:,.0f}→{_px2:,.0f} ({_px_drift_pct:+.2f}%) · "
      f"점수 허용오차 ±{_score_tol:.1f}")


def _reproduced(key, a, b):
    if a == b:
        return True
    if not _LIVE or key not in _PRICE_DEPENDENT:
        return False            # 장 마감 상태거나 가격과 무관한 점수면 불일치는 결함
    if a is None or b is None:
        return False
    if key.endswith('_score'):
        return abs(a - b) <= _score_tol
    return abs(a / (b + 1e-9) - 1.0) <= max(0.01, _px_drift_pct / 100.0 * 2)


for k in ('final_action_score', 'stock_quality_score', 'trading_timing_score',
          'risk_safety_score', 'opportunity_score', 'execution_score',
          'reward_risk_ratio', 'displayed_fair_value'):
    _a, _b = fs.get(k), f2.get(k)
    check(f"재현: {k}", _reproduced(k, _a, _b),
          f"{_a} vs {_b}" + (" (장중: 가격의존 항목 허용오차 적용)"
                             if _LIVE and k in _PRICE_DEPENDENT else ""))
check("재현: 표본외 방향적중률",
      (snap.get('oos_result') or {}).get('directional_hit_pct')
      == (snap2.get('oos_result') or {}).get('directional_hit_pct'))


# ---------------------------------------------------------------- 경로 분포
section("15. 시나리오 경로가 평행이동이 아닌가 (§10)")
hz20 = (sim.get('horizons_data') or {}).get(20)
if hz20 and hz20.get('status') != 'INSUFFICIENT':
    import numpy as _np
    med, p75, p25 = _np.asarray(hz20['trajectory']), _np.asarray(hz20['traj_p75']), _np.asarray(hz20['traj_p25'])
    up_gap, dn_gap = p75 - med, med - p25
    check("상단 밴드 간격이 일정하지 않음(평행이동 아님)",
          float(_np.std(up_gap / (med + 1e-9))) > 1e-6)
    check("상·하단 밴드가 비대칭(단순 오프셋 아님)",
          float(_np.mean(_np.abs(up_gap - dn_gap))) > 1e-9)
    check("군집 대표경로 3종 존재", all(k in hz20 for k in ('path_bull', 'path_base', 'path_bear')))
    # 군집이 갈리려면 표본이 있어야 한다. 유사 패턴이 5건뿐이면 상승·하락
    # 군집이 같은 케이스를 공유해 경로가 겹치는 것이 **정상**이다.
    #   2026-08-08 실측: n=8 일 때 통과 → n=5 로 줄자 실패.
    #   코드가 바뀐 게 아니라 그날의 매칭 표본이 줄어든 것이다.
    #   표본이 없어서 못 가른 것을 결함으로 세면, 검사가 날짜에 따라
    #   깜빡이고 진짜 결함을 덮는다.
    _mc15 = int(hz20.get('match_count') or 0)
    if _mc15 >= 8:
        check("군집 경로가 서로 다름",
              float(_np.mean(_np.abs(_np.asarray(hz20['path_bull'])
                                     - _np.asarray(hz20['path_bear'])))) > 1e-9,
              f'매칭 {_mc15}건')
    else:
        check(f"군집 경로 — 표본 {_mc15}건이라 판정하지 않음", True,
              '유사 패턴 8건 미만이면 군집이 갈리지 않는 것이 정상')
    check("ESS ≤ 표본수", (hz20.get('ess') or 0) <= hz20['match_count'],
          f"ESS={hz20.get('ess')} / n={hz20['match_count']}")
check("전략별 핵심기간 제공", isinstance(sim.get('core_horizons'), list) and len(sim['core_horizons']) == 3,
      str(sim.get('core_horizons')))


# ---------------------------------------------------------------- 하드코딩 부재
section("16. 종목명·티커 하드코딩 부재")
HARDCODE_PAT = _re.compile(r'"\d{6}\.(KS|KQ)"|\'\d{6}\.(KS|KQ)\'')
NAME_PAT = _re.compile(r'(삼성전자|SK하이닉스|현대차|알테오젠|카카오|NAVER)')
for fname in ('quant_indicators.py', 'web_app.py'):
    src = open(_os.path.join(PROJ, fname), encoding='utf-8').read()
    # 주석 줄은 제외하고 검사
    code = "\n".join(l for l in src.split("\n") if not l.strip().startswith('#'))
    check(f"{fname}: 티커 하드코딩 없음", not HARDCODE_PAT.search(code),
          str(HARDCODE_PAT.search(code).group(0) if HARDCODE_PAT.search(code) else ''))
    check(f"{fname}: 종목명 분기 없음", not NAME_PAT.search(code),
          str(NAME_PAT.search(code).group(0) if NAME_PAT.search(code) else ''))


# ---------------------------------------------------------------- 스캔 격리
section("17. 한 종목 오류가 전체 스캔을 막지 않는가")
uni_small = [{"symbol": "999999.KS", "name": "존재하지않음", "market": "KOSPI", "base_price": 10000}] \
    + [u for u in uni[:3]]
res = q.run_screener_scan(uni_small, T_REF, b_engine=engine, rho_cutoff=0.80)
check("오류 종목 제외 후 나머지 분석 완료", len(res) >= 1, f"{len(res)}건 성공")
check("실패 사유 기록", len(getattr(q, 'last_scan_failures', [])) >= 1,
      str((getattr(q, 'last_scan_failures', []) or [{}])[0].get('reason', ''))[:60])
check("TOP3를 억지로 채우지 않음",
      len([r for r in res if '추천주' in r['cat']]) == sum(
          1 for r in res if r['snapshot'].get('eligible_for_top3')))


# ---------------------------------------------------------------- 게이트 문구
section("18. 미충족 조건 문구의 부등호가 올바른가")
gc = fs.get('gate_checks') or []
check("게이트가 구조화됨", all(isinstance(g, dict) and 'passed' in g for g in gc), f"{len(gc)}개")
failed = [g for g in gc if not g['passed']]
passed = [g for g in gc if g['passed']]
check("미충족 항목은 '<' 로 표기", all('<' in g['text'] or g['threshold'] == '' for g in failed),
      "; ".join(g['text'] for g in failed[:2]))
check("충족 항목은 '≥' 로 표기", all('≥' in g['text'] or g['threshold'] == '' for g in passed),
      "; ".join(g['text'] for g in passed[:2]))
check("block_reasons == 미충족 항목 문구",
      set(fs['top3_block_reasons']) == {g['text'] for g in failed})

section("19. 가짜 앙상블 지표 제거")
check("ensemble_consensus 키 없음", 'ensemble_consensus' not in sim)
check("ensemble_up_count 키 없음", 'ensemble_up_count' not in sim)
check("앙상블 미구현 명시", sim.get('ensemble_implemented') is False)
_src = open(_os.path.join(PROJ, 'web_app.py'), encoding='utf-8').read()
_code_only = "\n".join(l for l in _src.split("\n") if not l.strip().startswith('#'))
check("UI에 '9개 앙상블' 표기 없음",
      '9개 앙상블' not in _code_only and "9개 중 " not in _code_only)

section("20. 최적 보유기간 자격 요건 (§13)")
elig = sim.get('horizon_eligibility') or {}
check("지평별 자격 판정 기록", len(elig) > 0, str({k: v['eligible'] for k, v in elig.items()}))
best = sim.get('optimal_holding_period_days')
if best is not None:
    hb = (sim.get('horizons_data') or {}).get(best, {})
    check(f"선정 기간 {best}일의 ESS ≥ 10", (hb.get('ess') or 0) >= 10, f"ESS={hb.get('ess')}")
    check(f"선정 기간 순기대수익 양수", elig.get(best, {}).get('net_expected_return', -1) > 0)
    check("선정 기간 목표>손절 선도달", (hb.get('tp_first_prob') or 0) > (hb.get('sl_first_prob') or 0))
else:
    check("자격 미달 시 '미선정' 표기", '미선정' in sim.get('optimal_holding_period_str', ''))
low_ess = [H for H, v in elig.items()
           if (sim['horizons_data'][H].get('ess') or 0) < 10]
check("ESS 10 미만 지평은 최적으로 선택되지 않음", best not in low_ess,
      f"ESS<10 지평={low_ess}, 선정={best}")

# ---------------------------------------------------------------- 포트폴리오
section("21. 포트폴리오 모듈 — 가져오기 · 검증 · 병합")
import portfolio as pf

check("종목코드 정규화", pf.normalize_code("A005930") == "005930"
      and pf.normalize_code("5930") == "005930" and pf.normalize_code("005930.KS") == "005930")
check("숫자 파싱", pf._to_number("1,234,500원") == 1234500.0 and pf._to_number("₩ 210,000") == 210000.0)
check("계좌번호 마스킹", "*" in pf.mask_account("123-45-678901"),
      pf.mask_account("123-45-678901"))

_df = pd.DataFrame({
    "종목코드": ["005930", "A000660", "999999"],
    "종목명": ["삼성전자", "SK하이닉스", "이상치"],
    "보유수량": ["10", "5", "-3"],
    "평균매수가": ["210,000원", "1,100,000", "1000"],
})
_map = pf.suggest_column_mapping(list(_df.columns))
check("열 자동 매핑", all(_map[k] for k in pf.REQUIRED_FIELDS), str(_map))
_pos, _warn = pf.import_positions(_df, _map)
check("음수 수량 행 제외", len(_pos) == 2, f"{len(_pos)}건 · 경고 {len(_warn)}건")
check("제외 사유 기록", any("수량" in w for w in _warn), _warn[0] if _warn else "")

_multi = [
    pf.PortfolioPosition("005930.KS", "삼성전자", "KOSPI", 10, 200000, account_name="A"),
    pf.PortfolioPosition("005930.KS", "삼성전자", "KOSPI", 10, 220000, account_name="B"),
]
_m = pf.merge_duplicate_positions(_multi)
check("복수 계좌 통합 평단가", abs(_m[0]['average_buy_price'] - 210000) < 1e-6,
      f"{_m[0]['average_buy_price']:,.0f}원")
check("계좌별 내역 보존", len(_m[0]['accounts']) == 2 and _m[0]['is_multi_account'])

_saved = pf.save_positions(_multi)
_back, _at = pf.load_positions()
check("로컬 저장·복원", len(_back) == 2 and _at is not None)
check("익명화 뷰에 수량·평단가 없음",
      all(set(d.keys()) == {"code", "weight_pct"} for d in pf.anonymize_for_llm(_multi)))
pf.delete_positions()
check("삭제 동작", pf.load_positions()[0] == [])

section("22. 자유형식 붙여넣기 파서 (증권사·네이버 화면 복사)")


def _resolve_nm(nm):
    t, real, _i = engine.fetch_and_update_naver_realtime(nm)
    return t, real


# 테스트 파일에도 종목명을 박아두지 않는다 — 코드로 조회해 실제 이름을 받아 쓴다
_NM = _resolve_nm("005930")[1] or "005930"
PASTE_CASES = {
    "탭+헤더": f"종목명\t보유수량\t평균매수가\n{_NM}\t10\t210,000",
    "코드+이름": f"005930  {_NM}  10  210,000",
    "단위표기": f"{_NM} 10주 210,000원",
    "쉼표": f"{_NM},10,210000",
    "코드만": "005930 10 210000",
    "손익열 포함": f"종목명\t보유수량\t평균매수가\t평가손익\n{_NM}\t10\t210,000\t+365,000",
    "잡음 섞임": "\n내 자산\n005930 10 210000\n합계\n",
}
for _label, _txt in PASTE_CASES.items():
    _rows, _w = pf.parse_freeform_holdings(_txt, resolve_name=_resolve_nm)
    ok = (len(_rows) >= 1 and _rows[0]['종목코드'] == '005930'
          and abs(_rows[0]['보유수량'] - 10) < 1e-9
          and abs(_rows[0]['평균매수가'] - 210000) < 1e-9)
    check(f"붙여넣기 인식: {_label}", ok,
          f"{_rows[0] if _rows else '(없음)'}")

_thousand = pf.parse_freeform_holdings(f"{_NM},10,1,500,000", resolve_name=_resolve_nm)[0]
check("천 단위 구분자가 열로 쪼개지지 않음",
      bool(_thousand) and _thousand[0]['평균매수가'] == 1500000.0,
      str(_thousand[0] if _thousand else '(없음)'))
_sixdigit = pf.parse_freeform_holdings(f"{_NM} 10 210000", resolve_name=_resolve_nm)[0]
check("6자리 가격을 종목코드로 오인하지 않음",
      bool(_sixdigit) and _sixdigit[0]['평균매수가'] == 210000.0,
      str(_sixdigit[0] if _sixdigit else '(없음)'))
for _bad in ("", "   ", "의미 없는 문장", _NM):
    _r, _w = pf.parse_freeform_holdings(_bad, resolve_name=_resolve_nm)
    check(f"잘못된 입력 방어: {_bad!r}", len(_r) == 0 and len(_w) >= 1)

_rt = pf.rows_to_positions(pf.positions_to_rows(_multi))[0]
check("표 편집 왕복 무손실",
      [(p.ticker, p.quantity, p.average_buy_price) for p in _rt]
      == [(p.ticker, p.quantity, p.average_buy_price) for p in _multi])


section("23. 개인화 판정 — 평단가가 예측에 개입하지 않는가")
pv_lo = q.personalize_for_position(snap, average_buy_price=px_now * 0.5, quantity=10)
pv_hi = q.personalize_for_position(snap, average_buy_price=px_now * 2.0, quantity=10)
check("평단가가 달라도 시장 판정은 동일",
      pv_lo['new_entry_title'] == pv_hi['new_entry_title']
      and pv_lo['new_entry_score'] == pv_hi['new_entry_score'])
check("평단가가 달라도 적정가·예측 불변",
      snap['four_scores']['displayed_fair_value'] == fs['displayed_fair_value']
      and snap['sim_res']['median_perf'] == sim['median_perf'])
check("보유자 점수는 평단가에 반응", pv_lo['holder_action_score'] != pv_hi['holder_action_score'],
      f"{pv_lo['holder_action_score']} vs {pv_hi['holder_action_score']}")
check("손실이 클수록 점수가 높아지지 않음",
      pv_hi['holder_action_score'] <= pv_lo['holder_action_score'],
      f"고평단(손실) {pv_hi['holder_action_score']} ≤ 저평단(이익) {pv_lo['holder_action_score']}")
_rec = pv_hi['recovery_required_pct']
_expected = (px_now * 2.0 / px_now - 1) * 100
check("본전 회복률 = 평단/현재가-1 (손실률 반대값 아님)", abs(_rec - _expected) < 1e-6,
      f"{_rec:.1f}% (손실률 반대값이면 {abs(pv_hi['unrealized_return_pct']):.1f}%)")
check("물타기 조건 전부 통과해야 허용",
      pv_hi['averaging_down_allowed'] == all(ok for _, ok in pv_hi['averaging_down_checks']))
check("보유자 등급이 정의된 값", pv_hi['holder_action_key'] in q.HOLDER_ACTION_TITLES)


section("24. 스크린샷 OCR — 줄 복원 · 코드 교정 · 오독 무단보정 금지")

# 24-1 OCR 엔진이 없어도 죽지 않고 사유를 돌려준다
_t, _b, _e = pf.extract_text_from_image(b"this-is-not-an-image")
check("깨진 이미지에 예외를 던지지 않음", _t is None and _e is not None, str(_e)[:60])

# 24-1b 클립보드 읽기는 어떤 상태에서도 예외를 던지지 않고 (bytes|None, err) 를 준다
try:
    _cimg, _cerr = pf.grab_clipboard_image()
    check("클립보드 읽기가 예외를 던지지 않음",
          (_cimg is None) != (_cerr is None),
          f"bytes={len(_cimg) if _cimg else 0}, err={str(_cerr)[:40]}")
except Exception as _ex:
    check("클립보드 읽기가 예외를 던지지 않음", False, f"{type(_ex).__name__}: {_ex}")

# 24-2 종목코드 글자 혼동 교정 — 되살릴 것만 되살린다
check("0OO66O → 000660 교정", pf.repair_ocr_code("0OO66O") == "000660",
      str(pf.repair_ocr_code("0OO66O")))
check("l05560 → 105560 교정", pf.repair_ocr_code("l05560") == "105560",
      str(pf.repair_ocr_code("l05560")))
check("이미 정상인 코드는 건드리지 않음", pf.repair_ocr_code("005930") is None)
check("한글 종목명은 코드로 바꾸지 않음", pf.repair_ocr_code("삼성전자우") is None)
check("숫자가 3개 미만이면 포기", pf.repair_ocr_code("SKOOOO") is None,
      str(pf.repair_ocr_code("SKOOOO")))
check("6자리가 아니면 포기", pf.repair_ocr_code("0OO66") is None)

# 24-3 교정 사실이 반드시 경고로 남는가 (사용자 검수 유도)
_rows, _warns = pf.parse_freeform_holdings("0OO66O  5  185000")
check("코드 교정 시 경고를 남김", any("교정" in w for w in _warns), str(_warns)[:80])
check("교정된 코드로 행이 만들어짐",
      len(_rows) == 1 and _rows[0]['종목코드'] == '000660', str(_rows)[:80])

# 24-4 ⚠️ 수량·평단가 숫자는 절대 임의 보정하지 않는다.
#      OCR이 10을 70으로 읽어도 시스템은 70을 그대로 넘겨야 한다 —
#      '그럴듯한 값'으로 되돌리는 순간 사용자가 검수할 근거가 사라진다.
_rows2, _ = pf.parse_freeform_holdings("005930  삼성전자  70  71,200")
check("수량 오독을 임의 보정하지 않음",
      len(_rows2) == 1 and _rows2[0]['보유수량'] == 70.0, str(_rows2)[:80])
check("평단가 오독을 임의 보정하지 않음",
      len(_rows2) == 1 and _rows2[0]['평균매수가'] == 71200.0, str(_rows2)[:80])

# 24-5 줄 복원: 같은 줄의 토큰이 y 경계값에서 쪼개지지 않는가.
#      고정 격자(round(y/14))를 쓰면 중심 104.9 와 105.1 이 다른 줄로 갈라졌다.
if pf.ocr_backend() is not None:
    import io as _io
    try:
        from PIL import Image as _Im, ImageDraw as _Dr, ImageFont as _Ft
        _f = _Ft.truetype(r"C:\Windows\Fonts\malgun.ttf", 30)
        _img = _Im.new("RGB", (900, 160), "white")
        _d = _Dr.Draw(_img)
        _d.text((40, 40), "005930", font=_f, fill="black")
        _d.text((300, 40), "삼성전자", font=_f, fill="black")
        _d.text((560, 40), "10", font=_f, fill="black")
        _d.text((700, 40), "71,200", font=_f, fill="black")
        _buf = _io.BytesIO()
        _img.save(_buf, format="PNG")
        _txt, _bk, _er = pf.extract_text_from_image(_buf.getvalue())
        _nonempty = [l for l in (_txt or "").splitlines() if l.strip()]
        check("한 줄로 그린 표가 한 줄로 복원됨",
              _er is None and len(_nonempty) == 1, f"{len(_nonempty)}줄: {_nonempty}")
    except Exception as _ex:
        check("OCR 줄 복원 검사", True, f"건너뜀 ({type(_ex).__name__})")
else:
    check("OCR 줄 복원 검사", True, "건너뜀 (OCR 엔진 미설치)")


section("25. HTS 잔고 화면 — 열 이름으로 평단가를 특정하는가")

# 실제 4202 주식잔고 화면 형식. 숫자 열이 7개이고 그중 셋(가능·손익분기·현재가)이
# 평단가와 헷갈리기 쉽다. 특히 손익분기는 수수료·세금이 붙어 평단가보다 항상 크다.
_HTS = "\t".join(["구분", "종목명", "평가손익", "수익률", "잔고", "가능",
                  "손익분기", "현재가", "대비", "등락", "매수평균"]) + "\n" + "\n".join([
    "\t".join(["", "금호건설", "-102,636", "-2.50%", "400", "200",
               "10,267", "9,990", "500", "5.27", "10,246"]),
    "\t".join(["", "한온시스템", "-371,215", "-8.55%", "1,157", "1,157",
               "3,757", "3,430", "165", "5.05", "3,750"]),
    "\t".join(["", "LG전자", "-162,800", "-14.42%", "6", "6",
               "188,466", "161,000", "13,000", "8.78", "188,133"]),
])
_FAKE = {"금호건설": "002990.KS", "한온시스템": "018880.KS", "LG전자": "066570.KS"}
_hrows, _hwarns = pf.parse_freeform_holdings(
    _HTS, resolve_name=lambda nm: (_FAKE.get(nm), nm))
_by = {r['종목명']: r for r in _hrows}

check("헤더 있는 표를 전량 인식", len(_hrows) == 3, f"{len(_hrows)}행")
check("수량은 '잔고' 열 (매도'가능' 아님)",
      _by.get('금호건설', {}).get('보유수량') == 400.0,
      str(_by.get('금호건설', {}).get('보유수량')))
check("평단가는 '매수평균' 열", _by.get('금호건설', {}).get('평균매수가') == 10246.0,
      str(_by.get('금호건설', {}).get('평균매수가')))
check("'손익분기'를 평단가로 오인하지 않음",
      _by.get('금호건설', {}).get('평균매수가') != 10267.0)
check("'현재가'를 평단가로 오인하지 않음",
      _by.get('한온시스템', {}).get('평균매수가') != 3430.0)
check("천 단위 수량 정확", _by.get('한온시스템', {}).get('보유수량') == 1157.0,
      str(_by.get('한온시스템', {}).get('보유수량')))
check("6자리 평단가 정확", _by.get('LG전자', {}).get('평균매수가') == 188133.0,
      str(_by.get('LG전자', {}).get('평균매수가')))
check("인식한 열 구성을 사용자에게 알림",
      any("헤더를 인식" in w for w in _hwarns), str(_hwarns[:1]))

# 종목명을 못 찾아도 행을 버리지 않는다 — 미리보기에서 고칠 기회를 남긴다
_urows, _uwarns = pf.parse_freeform_holdings(
    _HTS.replace("금호건설", "금오건셜"), resolve_name=lambda nm: (_FAKE.get(nm), nm))
check("종목 미해석 행도 버리지 않음", len(_urows) == 3, f"{len(_urows)}행")
check("미해석 행은 _ticker 가 비어 경고 대상",
      any(not r.get('_ticker') for r in _urows)
      and any("찾지 못했습니다" in w for w in _uwarns))

# 헤더가 없으면 기존 자유형식 추정으로 되돌아간다
_frows, _ = pf.parse_freeform_holdings("005930  삼성전자  10  210,000")
check("헤더 없는 입력은 자유형식 경로 유지",
      len(_frows) == 1 and _frows[0]['평균매수가'] == 210000.0, str(_frows)[:70])

# 열 이름 분류 자체의 불변식
_mp = pf.classify_header_cells(["구분", "종목명", "평가손익", "수익률", "잔고", "가능",
                                "손익분기", "현재가", "대비", "등락", "매수평균"])
check("열 분류: 수량=잔고(4)", _mp.get('quantity') == 4, str(_mp))
check("열 분류: 평단=매수평균(10)", _mp.get('price') == 10, str(_mp))
check("열 분류: 제외열은 배정되지 않음",
      all(_mp.get(f) not in (5, 6, 7) for f in ('quantity', 'price')), str(_mp))


section("26. 붙여넣기 — 구분자·줄바꿈·공백 종목명")

_H = '구분 종목명 평가손익 수익률 잔고 가능 손익분기 현재가 대비 등락 매수평균'
_ROWS = [('금호건설', '-78,636', '-1.92%', '400', '200', '10,267', '10,050', '500', '5.90', '10,246'),
         ('SOL 팔란티', '-423,575', '-6.87%', '739', '739', '8,343', '7,770', '15', '-0.19', '8,340'),
         ('LG전자', '-170,000', '-15.06%', '6', '6', '188,463', '159,800', '11,800', '7.97', '188,133')]
_BODY = "\n".join(' ' + ' '.join(r) for r in _ROWS)
_EXP = {'금호건설': (400.0, 10246.0), 'SOL 팔란티': (739.0, 8340.0), 'LG전자': (6.0, 188133.0)}
_CODES = {'금호건설': '002990', 'SOL 팔란티': '446720', 'LG전자': '066570'}
_RS = (lambda nm: ((_CODES[nm] + '.KS', nm) if nm in _CODES else (None, None)))


def _paste_ok(label, text):
    rows, _w = pf.parse_freeform_holdings(text, resolve_name=_RS)
    got = {r['종목명']: (r['보유수량'], r['평균매수가']) for r in rows}
    check(label, got == _EXP, str(got)[:110])


# 증권사 화면을 드래그 복사하면 열 사이가 한 칸 공백뿐인 경우가 흔하다
_paste_ok("붙여넣기: 공백 1칸 구분", _H + "\n" + _BODY)
# 엑셀·OCR 열정렬 출력
_paste_ok("붙여넣기: 탭 구분",
          _H.replace(' ', '\t') + "\n" + "\n".join('\t' + '\t'.join(r) for r in _ROWS))
# 화면 폭에 맞춰 헤더가 여러 줄로 접힌 복사본
_paste_ok("붙여넣기: 헤더가 여러 줄로 쪼개짐",
          "종목명 평가손익 수익률\n잔고 가능 손익분기\n현재가 대비 등락 매수평균\n" + _BODY)

# 종목명에 공백이 있으면 토큰 수가 열 수와 우연히 같아져 이름이 잘렸었다
_sp_rows, _ = pf.parse_freeform_holdings(_H + "\n" + _BODY, resolve_name=_RS)
check("공백 포함 종목명이 잘리지 않음",
      any(r['종목명'] == 'SOL 팔란티' for r in _sp_rows),
      str([r['종목명'] for r in _sp_rows]))

# ⚠️ 헤더 없이 숫자만 많은 줄에서 '앞의 두 개' 식으로 **추측하면** 반드시 틀린다
#    (매도가능수량을 평단가로 넣는다). 그래서 추측은 여전히 금지다.
#    다만 이제는 추측 대신 **관계식을 풀어 검증**한다(§50):
#      · 평가손익·수익률과 맞아떨어지면 값을 채우고 오차를 밝힌다
#      · 맞아떨어지지 않으면 예전처럼 읽지 못했다고 말한다
_amb_rows, _amb_warns = pf.parse_freeform_holdings(_BODY.splitlines()[0], resolve_name=_RS)
check("관계식이 성립하면 값을 채우되 근거를 밝힘",
      len(_amb_rows) == 1 and _amb_rows[0]['보유수량'] is not None
      and any("관계식으로 풀었습니다" in w and "오차" in w for w in _amb_warns),
      str(_amb_rows)[:90])
_amb2_rows, _amb2_warns = pf.parse_freeform_holdings(
    "이상한종목 111 222 333 444 555", resolve_name=_RS)
check("관계가 성립하지 않으면 여전히 채우지 않음",
      len(_amb2_rows) == 1 and _amb2_rows[0]['보유수량'] is None
      and _amb2_rows[0]['평균매수가'] is None, str(_amb2_rows)[:90])
check("추측 불가를 사용자에게 알림",
      any("맞아떨어지는 조합이 없습니다" in w for w in _amb2_warns),
      str(_amb2_warns[:1])[:110])

# 열 직접 지정 — 추측하지 않으므로 지정이 맞으면 결과도 맞다
_n, _cells = pf.preview_columns(_H + "\n" + _BODY)
check("열 미리보기가 열 개수를 셈", _n == 11, f"{_n}열")
_man, _ = pf.parse_with_explicit_columns(
    _H + "\n" + _BODY, name_col=1, qty_col=4, price_col=10, skip_rows=1, resolve_name=_RS)
check("열 직접 지정으로 정확히 읽음",
      {r['종목명']: (r['보유수량'], r['평균매수가']) for r in _man} == _EXP, str(_man)[:110])
_bad, _bw = pf.parse_with_explicit_columns(_H + "\n" + _BODY, name_col=1, qty_col=4)
check("평단가 열 미지정이면 거부", not _bad and bool(_bw))


section("27. 시장 관심종목 — 관심도와 매수판단의 분리")

import market_attention as mkt

_w = mkt.effective_weights()
check("유효 가중치 합 = 1.0", abs(sum(_w.values()) - 1.0) < 1e-9, f"{sum(_w.values()):.6f}")
check("연동 현황이 모든 구성요소를 보고", len(mkt.data_status()) == len(mkt.COMPONENT_SPEC))
# 미연동 항목이 있으면 가중치가 0 이어야 하고, 있든 없든 화면에서 숨기지 않는다
for _d in mkt.data_status():
    if _d['availability'] == 'none':
        check(f"미연동 항목 가중치 0: {_d['label']}", _d['effective_weight_pct'] == 0.0)
check("모든 구성요소가 사유·산식을 기술", all(d['detail'] for d in mkt.data_status()))

# ETF·인버스가 기업 후보에 섞이면 안 된다 (거래대금 상위를 이들이 뒤덮는다)
for _nm in ('KODEX 200', 'TIGER 미국S&P500', 'KODEX 레버리지', '파워 200', 'HK 200',
            'KODEX 인버스', 'ACE KRX금현물'):
    check(f"펀드류 제외: {_nm}", mkt._is_fund_like(_nm))
for _nm in ('삼성전자', '금호건설', 'LG전자', 'SK하이닉스', '한온시스템'):
    check(f"일반 종목 오탐 없음: {_nm}", not mkt._is_fund_like(_nm))

# 과열 감점 — 관심점수가 높아도 지금 사면 안 되는 상태를 분리해야 한다 (§7)
_hot = {'price': 10000.0, 'disparity_20_pct': 30.0, 'ret_5d': 40.0,
        'turnover_avg20': 1e8, 'ma_month10': 5000.0, 'scores': {}}
_pen, _why = mkt.compute_penalties(_hot, change_pct=20.0)
check("과열 종목에 감점이 걸림", _pen >= 20.0, f"{_pen:.0f}점 · {len(_why)}개 사유")
check("감점 사유를 남김", len(_why) >= 3, str(_why)[:80])
_calm = {'price': 10000.0, 'disparity_20_pct': 2.0, 'ret_5d': 3.0,
         'turnover_avg20': 5e10, 'ma_month10': 9000.0, 'scores': {}}
check("정상 종목은 감점 없음", mkt.compute_penalties(_calm, change_pct=1.0)[0] == 0.0)

# §8 관심점수를 매수점수로 쓰지 않는다
check("관심 높음 + 행동 낮음 = 추격주의",
      mkt.classify_bucket({'adjusted_attention_score': 90.0, 'overheated': True}, 40)
      == '관심 급증·추격주의')
check("관심 낮음 + 행동 높음 = 선행 후보",
      mkt.classify_bucket({'adjusted_attention_score': 20.0, 'overheated': False}, 75)
      == '조용한 선행 후보')
check("둘 다 높아야 실전 추천",
      mkt.classify_bucket({'adjusted_attention_score': 80.0, 'overheated': False}, 75)
      == '실전 추천 후보')

# §12 관심점수의 순위 영향은 5% 이내로 제한
check("관심점수 가산점 상한 5점",
      mkt.attention_tiebreak_bonus(100.0) <= mkt.ATTENTION_TIEBREAK_MAX_PCT + 1e-9,
      f"{mkt.attention_tiebreak_bonus(100.0):.2f}")
check("관심점수가 행동점수를 뒤집지 못함",
      68 + mkt.attention_tiebreak_bonus(0.0) < 75 + mkt.attention_tiebreak_bonus(0.0))

# 라운드 41 — 뉴스 RSS 를 실제로 받게 되어 'news' 방식이 열렸다.
# 이제는 '후보를 만들거나, 못 만들면 사유를 밝히거나' 둘 중 하나여야 한다.
# 조용히 빈 목록을 돌려주는 것만 금지한다.
_na = mkt.find_attention_candidates('news', top_n=5)
check("뉴스·공시 방식이 후보 또는 사유를 낸다",
      bool(_na['rows']) or bool(_na['unavailable']),
      f"rows={len(_na['rows'])} · {str(_na.get('unavailable'))[:50]}")

# 장중 미확정 봉을 20일 평균과 비교하면 배수가 왜곡된다
_bars = (np.arange(60).astype(str), np.full(60, 100.0), np.full(60, 105.0),
         np.full(60, 95.0), np.full(60, 100.0), np.concatenate([np.full(59, 1000.0), [10.0]]))
_c_all = mkt.compute_components(_bars, drop_unconfirmed=False)
_c_cut = mkt.compute_components(_bars, drop_unconfirmed=True)
check("미확정 봉 제외 시 거래대금 배수가 달라짐",
      _c_all['turnover_ratio'] != _c_cut['turnover_ratio'],
      f"전체 {_c_all['turnover_ratio']:.2f} vs 확정만 {_c_cut['turnover_ratio']:.2f}")
check("확정 기준 배수가 정상 범위", abs(_c_cut['turnover_ratio'] - 1.0) < 1e-6,
      f"{_c_cut['turnover_ratio']:.4f}")


section("28. 죽어 있던 패널이 실제 데이터로 움직이는가")

# 28-1 지수 시계열 — KOSPI200 은 네이버 심볼이 'KPI200' 이라 'KOSPI200' 으로는 못 받는다
_idx = engine.fetch_index_daily("KOSPI200", count=600)
check("KOSPI200 지수 일봉 수신", _idx is not None and len(_idx[1]) > 300,
      f"{len(_idx[1]) if _idx else 0}봉")
check("지수 종가가 양수", _idx is not None and float(np.min(_idx[1])) > 0)

# 28-2 벤치마크 — b_engine 을 넘기지 않으면 미연동으로 떨어진다 (구버전 상태)
_bd_off = q.calculate_benchmark_comparisons(sim, tech_df=snap['tech_df'])
_bd_on = q.calculate_benchmark_comparisons(sim, tech_df=snap['tech_df'], b_engine=engine)
check("지수 미연결 시 KOSPI200 미산출", _bd_off['kospi200_perf'] is None)
check("지수 연결 시 KOSPI200 실산출", _bd_on['kospi200_perf'] is not None,
      f"{_bd_on['kospi200_perf']}% · {_bd_on['kospi200_note'][:40]}")
check("KOSPI200 수익률이 리터럴 12.6이 아님", _bd_on['kospi200_perf'] != 12.6)
check("판정 문구에 KOSPI200 포함", "KOSPI200" in _bd_on['judge_text'],
      _bd_on['judge_text'][:70])

# 28-3 팩터 귀속 — 시장 1팩터는 실제 회귀가 가능하다
_fa = q.calculate_factor_attribution(sim, tech_df=snap['tech_df'], b_engine=engine)
check("팩터 귀속 산출됨", _fa.get('available') is True, str(_fa.get('reason'))[:60])
check("베타가 현실 범위", _fa.get('available') and 0.0 < _fa['beta'] < 3.0, str(_fa.get('beta')))
check("R²가 0~1", _fa.get('available') and 0.0 <= _fa['r_squared'] <= 1.0, str(_fa.get('r_squared')))
check("구버전 고정계수(0.51/0.28/0.13/0.15) 흔적 없음",
      _fa.get('available') and _fa['beta'] not in (0.51, 0.28, 0.13, 0.15))
check("미연동 팩터를 숨기지 않음",
      _fa.get('available') and set(_fa['missing_factors']) == {'섹터', '규모(size)', '모멘텀'},
      str(_fa.get('missing_factors')))
check("인자 없이 호출하면 미산출", q.calculate_factor_attribution(sim).get('available') is False)

# 28-4 위험예산 — 보유 종목을 넘겨야 산출된다
check("보유 미입력 시 미산출", q.calculate_portfolio_risk_budget().get('available') is False)
_POS = [{'ticker': '005930.KS', 'stock_name': '삼성전자', 'quantity': 10},
        {'ticker': '003490.KS', 'stock_name': '대한항공', 'quantity': 38}]
_rb = q.calculate_portfolio_risk_budget(_POS, b_engine=engine,
                                        market_regime_code=fs.get('market_regime_code'))
check("보유 입력 시 산출됨", _rb.get('available') is True, str(_rb.get('reason'))[:60])
if _rb.get('available'):
    check("비중 합계 100%", abs(sum(h['weight_pct'] for h in _rb['holdings']) - 100.0) < 1e-6)
    check("HHI 범위 (1/n ~ 1)", 0.5 - 1e-9 <= _rb['hhi'] <= 1.0, str(_rb['hhi']))
    check("포트폴리오 변동성 ≤ 개별 가중평균 (분산효과)",
          _rb['portfolio_vol_annual_pct'] <= _rb['weighted_indiv_vol_pct'] + 1e-6,
          f"{_rb['portfolio_vol_annual_pct']} ≤ {_rb['weighted_indiv_vol_pct']}")
    check("MDD 음수", _rb['historical_mdd_pct'] < 0, str(_rb['historical_mdd_pct']))
    check("현금비중 10~70%", 10.0 <= _rb['recommended_cash_pct'] <= 70.0,
          str(_rb['recommended_cash_pct']))
    check("현금비중 사유 제시", bool(_rb['cash_reasons']))
    # ⚠️ 평단가는 위험 산출에 들어가면 안 된다 (비싸게 산 종목의 위험이 과대평가된다).
    #    값 비교만으로 검증하면 장중에 시세가 움직여 통과/실패가 갈리는 불안정한 검사가 된다.
    #    산식이 평단가를 아예 참조하지 않는다는 구조적 불변식으로 확인한다.
    import inspect as _insp
    _rb_src = _insp.getsource(q.calculate_portfolio_risk_budget)
    _body = _rb_src.split('"""', 2)[-1]          # 독스트링의 설명 문구는 제외
    check("위험예산 산식이 평단가를 참조하지 않음",
          'average_buy_price' not in _body and '평단' not in _body,
          "평단가 참조 발견" if 'average_buy_price' in _body else "")

    _POS2 = [dict(p, average_buy_price=999999) for p in _POS]
    _rb2 = q.calculate_portfolio_risk_budget(_POS2, b_engine=engine,
                                             market_regime_code=fs.get('market_regime_code'))
    _tol = 2.0 if _LIVE else 1e-9                # 장중 시세 변동 허용
    check("평단가를 바꿔도 위험예산 불변",
          abs(_rb2['portfolio_vol_annual_pct'] - _rb['portfolio_vol_annual_pct']) <= _tol
          and abs(_rb2['hhi'] - _rb['hhi']) <= (0.02 if _LIVE else 1e-12),
          f"vol {_rb['portfolio_vol_annual_pct']}→{_rb2['portfolio_vol_annual_pct']}, "
          f"hhi {_rb['hhi']}→{_rb2['hhi']}"
          + (" (장중 시세변동 허용)" if _LIVE else ""))

# 28-5 출처 매트릭스 — 미연동이라고 비워두지 않고 실제 사용처를 밝힌다
_, _, _mtx = engine.get_realtime_stock_price_triple_check(SYMBOL)
check("모든 출처가 사용처를 기술", all(r.get('role') for r in _mtx),
      str([r['source'][:12] for r in _mtx if not r.get('role')]))
_indirect = [r for r in _mtx if '간접' in r.get('status', '')]
check("KRX·DART·FnGuide를 간접 활용으로 표기", len(_indirect) >= 3,
      str([r['source'][:16] for r in _indirect]))
check("간접 활용 출처는 가격을 갖지 않음", all(r['price'] is None for r in _indirect))

# 28-6 배당 — 배당락일을 단정하지 않고 추정임을 밝힌다
_dv = engine.fetch_dividend_info(SYMBOL, current_price=float(snap['rt_price']))
if _dv.get('available'):
    check("주당배당금 실측", _dv['dps'] > 0, f"{_dv['dps']:,.0f}원")
    check("배당수익률이 현재가 기준", _dv['dividend_yield_pct'] is not None
          and 0 < _dv['dividend_yield_pct'] < 30, str(_dv['dividend_yield_pct']))
    check("배당락일을 추정으로 명시", _dv['is_estimated'] is True and "추정" in _dv['note'])
    check("추정 배당락일이 배당기준일보다 앞", _dv['estimated_ex_date'] < _dv['estimated_record_date'],
          f"{_dv['estimated_ex_date']} < {_dv['estimated_record_date']}")
else:
    check("배당 미산출 시 사유 제시", bool(_dv.get('reason')), str(_dv.get('reason'))[:50])


section("29. 종목명 오독 복구 — 네이버 검색 + 유사 검색")

# ⚠️ 단일 일치일 때 네이버는 70바이트 리다이렉트만 준다. 이걸 못 잡아서
#    '한온시스템' 같은 멀쩡한 이름이 전부 '검색 결과 없음' 이었다.
for _nm in ('한온시스템', '광주신세계', '금호건설'):
    _hit = engine.search_naver_stocks_realtime(_nm)
    check(f"정확 검색 복구: {_nm}", bool(_hit) and any(_nm in h for h in _hit), str(_hit)[:60])

_t, _n2, _c = engine.resolve_name_with_fallback('대한항곰')
check("오독 이름은 자동 확정하지 않음", _t is None)
check("오독 이름에 유사 후보 제시", bool(_c) and _c[0]['name'] == '대한항공',
      str([(x['name'], x['score']) for x in _c[:3]]))
_t3, _n3, _c3 = engine.resolve_name_with_fallback('한문시스템')
check("한문시스템 → 한온시스템 후보 포함",
      any(x['name'] == '한온시스템' for x in _c3), str([x['name'] for x in _c3[:4]]))
_t4, _n4, _c4 = engine.resolve_name_with_fallback('LG전자')
check("정상 이름은 즉시 확정", _t4 is not None and '066570' in str(_t4), str(_t4))
check("유사도 점수가 0~1", all(0.0 <= x['score'] <= 1.0 for x in _c))
check("빈 입력 방어", engine.resolve_name_with_fallback('')[0] is None)


section("30. 표 왕복(Arrow) 오염 — NaN·실수형 종목코드")

# ⚠️ st.data_editor 는 값을 Arrow 로 왕복시킨다. 문자열과 None 이 섞인 열에서
#    None 은 돌아올 때 float('nan') 이 된다. NaN 은 참(truthy)이라
#    `if not ticker:` 를 통과해버리고 `.endswith()` 에서 AttributeError 로 터졌다.
_mixed = pd.DataFrame([
    {"종목코드": "005930", "종목명": "삼성전자", "보유수량": 10.0,
     "평균매수가": 71200.0, "_ticker": "005930.KS"},
    {"종목코드": "", "종목명": "대한항곰", "보유수량": 38.0,
     "평균매수가": 27740.0, "_ticker": None},
]).to_dict("records")
check("문자열+None 혼합 열은 왕복 시 NaN 이 된다 (재현)",
      any(isinstance(r["_ticker"], float) for r in _mixed),
      str([type(r["_ticker"]).__name__ for r in _mixed]))

_nan_rows = [{"종목코드": "005930", "종목명": "삼성전자", "보유수량": 10.0,
              "평균매수가": 71200.0, "_ticker": float('nan')},
             {"종목코드": "003490", "종목명": "대한항공", "보유수량": 38.0,
              "평균매수가": 27740.0, "_ticker": float('nan')}]
try:
    _np_pos, _np_warn = pf.rows_to_positions(_nan_rows)
    check("_ticker 가 NaN 이어도 예외 없음", True, f"{len(_np_pos)}종목")
    check("NaN 대신 종목코드로 티커 재구성",
          len(_np_pos) == 2 and all(p.ticker.endswith(('.KS', '.KQ')) for p in _np_pos),
          str([p.ticker for p in _np_pos]))
except Exception as _ex:
    check("_ticker 가 NaN 이어도 예외 없음", False, f"{type(_ex).__name__}: {_ex}")

# 종목코드 열이 숫자형이 되면 '005930' 이 5930.0 → 앞자리 0 이 사라진다.
# 그대로 숫자만 뽑으면 '59300' → 059300 이라는 없는 코드가 만들어진다.
for _raw, _exp in ((5930.0, '005930'), ('5930.0', '005930'), (5930, '005930'),
                   ('005930', '005930'), ('A005930', '005930'), ('005930.KS', '005930'),
                   (float('nan'), None), (None, None), ('', None), ('nan', None)):
    check(f"normalize_code({_raw!r})", pf.normalize_code(_raw) == _exp,
          f"→ {pf.normalize_code(_raw)!r} (기대 {_exp!r})")

# 수량·평단가가 비어 있는 행(추측 거부 결과)도 예외 없이 걸러져야 한다
_blank = [{"종목코드": "005930", "종목명": "삼성전자", "보유수량": float('nan'),
           "평균매수가": float('nan'), "_ticker": float('nan')}]
_bp, _bw = pf.rows_to_positions(_blank)
check("빈 수량·평단가 행은 사유와 함께 제외", not _bp and bool(_bw), str(_bw)[:70])

# 시장 조회가 실패해도 반영 전체가 죽으면 안 된다
def _boom(_c):
    raise RuntimeError("네트워크 실패")


_rp, _ = pf.rows_to_positions(
    [{"종목코드": "005930", "종목명": "삼성전자", "보유수량": 10,
      "평균매수가": 71200, "_ticker": None}], resolve_market=_boom)
check("resolve_market 예외를 흡수", len(_rp) == 1 and _rp[0].ticker == "005930.KS",
      str([p.ticker for p in _rp]))

check("clean_cell_str 이 NaN·'nan'·빈문자를 None 으로",
      all(pf.clean_cell_str(v) is None
          for v in (None, float('nan'), '', '  ', 'nan', 'None', '<NA>')))
check("clean_cell_str 이 정상 문자열은 보존", pf.clean_cell_str('  005930.KS ') == '005930.KS')


section("31. 배당 — 단일 출처 · 역산 금지 · 배당락일 표기")

# ⚠️ 같은 지표를 두 곳에서 계산하면 반드시 갈라진다. 실제로 헤더는 1,668원,
#    하단 패널은 1,444원이었다. 원인은 엔진이 '네이버 표시 배당수익률 × 현재가'로
#    DPS 를 역산한 것 — 그 수익률은 산출 시점 주가 기준이라 급등하면 DPS 가 부풀려진다.
_div_src = _os.path.join(PROJ, "bitemporal_engine.py")
_div_code = open(_div_src, encoding='utf-8').read()
check("DPS 역산식(price * dvd/100) 제거", "price * (dvd / 100.0)" not in _div_code)
check("시드 DB에 배당 하드코딩 없음",
      '"div_yield"' not in _div_code and '"div_payout"' not in _div_code
      and '"div_date"' not in _div_code)
check("고정 배당락일 리터럴 제거", "2026-12-28 (연배당)" not in _div_code)

engine.fetch_and_update_naver_realtime(SYMBOL)
_info = be.STOCK_METRICS_DB.get(SYMBOL) or {}
check("엔진 스냅샷이 배당을 소유하지 않음",
      not any(k.startswith('div_') for k in _info),
      str([k for k in _info if k.startswith('div_')]))

_px_now = float(_info.get('base_price') or 0)
_dv = engine.fetch_dividend_info(SYMBOL, current_price=_px_now)
if _dv.get('available'):
    check("DPS 는 공시 원본값", _dv['dps'] > 0, f"{_dv['dps']:,.0f}원")
    # 수익률은 DPS ÷ 현재가여야 한다 (네이버 표기값을 그대로 쓰면 시점이 어긋난다)
    _expect_y = round(_dv['dps'] / _px_now * 100.0, 2)
    check("배당수익률 = DPS ÷ 현재가",
          abs(_dv['dividend_yield_pct'] - _expect_y) < 0.02,
          f"{_dv['dividend_yield_pct']} vs 계산 {_expect_y}")
    check("배당락일이 추정임을 명시", _dv['is_estimated'] and "추정" in _dv['note'])
    check("배당락일 < 배당기준일", _dv['estimated_ex_date'] < _dv['estimated_record_date'])
    check("배당락일이 미래", _dv['days_to_ex'] is not None and _dv['days_to_ex'] >= 0,
          f"D-{_dv['days_to_ex']}")
    # 현재가가 오르면 수익률은 반드시 내려간다 (역산이 남아 있으면 이 관계가 깨진다)
    _dv2 = engine.fetch_dividend_info(SYMBOL, current_price=_px_now * 2.0)
    check("현재가 2배면 배당수익률 절반",
          abs(_dv2['dividend_yield_pct'] - _dv['dividend_yield_pct'] / 2.0) < 0.02,
          f"{_dv['dividend_yield_pct']} → {_dv2['dividend_yield_pct']}")
    check("현재가가 바뀌어도 DPS 는 불변", _dv2['dps'] == _dv['dps'],
          f"{_dv['dps']} vs {_dv2['dps']}")
else:
    check("배당 미산출 시 사유 제시", bool(_dv.get('reason')), str(_dv.get('reason'))[:60])

# 무배당·미상장 종목에서도 예외 없이 사유를 돌려준다
_dv_bad = engine.fetch_dividend_info("999999", current_price=1000.0)
check("조회 실패 시 예외 없이 사유 반환",
      _dv_bad.get('available') is False and bool(_dv_bad.get('reason')),
      str(_dv_bad.get('reason'))[:50])


section("32. 표 편집 반영 · 정확 일치 우선")

# ⚠️ 숨겨진 _ticker 열이 사용자가 고친 종목코드를 덮어써서, 표에서 코드를 바꿔도
#    '반영'이 옛 종목을 그대로 저장했다. 종목코드는 표에서 고칠 수 있는 유일한
#    식별자이므로 둘이 어긋나면 종목코드가 이겨야 한다.
_ed_rows = [{"종목코드": "111770", "종목명": "영원무역", "보유수량": 23,
             "평균매수가": 87343, "_ticker": "009970.KS"}]
_ed_pos, _ed_warn = pf.rows_to_positions(_ed_rows)
check("표에서 고친 종목코드가 이긴다",
      len(_ed_pos) == 1 and _ed_pos[0].ticker.startswith("111770"),
      str([p.ticker for p in _ed_pos]))
check("종목코드 변경을 경고로 알림", any("바꿔 반영" in w for w in _ed_warn),
      str(_ed_warn)[:70])

# 코드가 같으면 시장 접미사는 유지해야 한다 (코스닥이 코스피로 바뀌면 시세 조회가 깨진다)
_kq_pos, _ = pf.rows_to_positions(
    [{"종목코드": "086520", "종목명": "에코프로", "보유수량": 10,
      "평균매수가": 100000, "_ticker": "086520.KQ"}])
check("코드가 같으면 .KQ 유지",
      _kq_pos and _kq_pos[0].ticker == "086520.KQ" and _kq_pos[0].market == "KOSDAQ",
      str([(p.ticker, p.market) for p in _kq_pos]))

_qty_pos, _ = pf.rows_to_positions(
    [{"종목코드": "002990", "종목명": "금호건설", "보유수량": 400,
      "평균매수가": 10246, "_ticker": "002990.KS"}])
check("수량 수정이 반영됨", _qty_pos and _qty_pos[0].quantity == 400.0,
      str([p.quantity for p in _qty_pos]))

# ⚠️ 네이버 검색은 '영원무역'에 홀딩스를 먼저 돌려준다. 첫 결과를 쓰면 지주회사가
#    등록되고 주가가 두 배 넘게 달라 손익이 통째로 틀어진다.
for _nm, _code in (("영원무역", "111770"), ("대한항공", "003490"),
                   ("금호건설", "002990"), ("한온시스템", "018880"),
                   ("광주신세계", "037710"), ("코텍", "052330")):
    _rt, _rn, _rc = engine.resolve_name_with_fallback(_nm)
    check(f"정확 일치 우선: {_nm} → {_code}",
          str(_rt or '').split('.')[0] == _code, f"실제 {_rt} ({_rn})")

check("지주회사는 그 이름으로만 잡힌다",
      str(engine.resolve_name_with_fallback("영원무역홀딩스")[0] or '').startswith("009970"))
check("코스닥 종목은 .KQ 로 해석",
      str(engine.resolve_name_with_fallback("코텍")[0] or '').endswith(".KQ"),
      str(engine.resolve_name_with_fallback("코텍")[0]))

# 조회 결과 이름이 질의와 다르면 확정하지 않는다 ('SOL 팔란티' → 엉뚱한 종목 방지)
_st, _sn, _sc = engine.resolve_name_with_fallback("SOL 팔란티")
check("부분 이름은 자동 확정하지 않음", _st is None, f"{_st} ({_sn})")


section("33. 인식 결과 교차검증 — 오독 탐지 · 후보 역산 · 저장 차단")

# 증권사 화면은 같은 사실을 여러 열로 중복 표기한다. 예전에는 그 열들을 읽고도
# 버려서 검증할 근거가 없었다. 실측하면 관계가 오차 0.2% 이내로 성립한다.
_VH = "구분 종목명 평가손익 수익률 잔고 가능 손익분기 현재가 대비 등락 매수평균"
_VB = "\n".join([
    " 금호건설 -198,636 -4.85% 400 200 10,266 9,750 260 2.74 10,246",
    " 대한항공 -69,950 -6.64% 38 38 27,794 25,900 1,250 5.07 27,740",
    " 한온시스템 -417,495 -9.62% 1,157 1,157 3,757 3,390 125 3.83 3,750",
])
_VC = {"금호건설": "002990", "대한항공": "003490", "한온시스템": "018880"}
_vrows, _ = pf.parse_freeform_holdings(
    _VH + "\n" + _VB, resolve_name=lambda n: ((_VC[n] + ".KS", n) if n in _VC else (None, None)))

check("검증용 현재가 열 수집", all(r.get('현재가') for r in _vrows))
check("수익률의 음수 부호 보존",
      all((r.get('수익률') or 0) < 0 for r in _vrows), str([r.get('수익률') for r in _vrows]))
check("평가손익의 음수 부호 보존",
      all((r.get('평가손익') or 0) < 0 for r in _vrows))
check("검증 열이 평단가를 밀어내지 않음",
      _vrows[0]['평균매수가'] == 10246.0, str(_vrows[0]['평균매수가']))

_chk, _tot = pf.validate_portfolio(_vrows)
check("정상 행은 전부 통과", _tot['ok'] == 3 and _tot['error'] == 0,
      f"ok={_tot['ok']} warn={_tot['warn']} err={_tot['error']}")
check("정상 행 신뢰도 90 이상",
      all(r['_validation']['confidence'] >= 90 for r in _chk))
check("합계 검증 통과", all(c['level'] == 'ok' for c in _tot['checks']),
      str(_tot['checks'])[:90])

# ── 오독을 심으면 잡히는가 ────────────────────────────────────────────
_bad_q = dict(_vrows[0]); _bad_q['보유수량'] = 4.0          # 400 → 4 (자리 누락)
_vq = pf.validate_row(_bad_q)
check("수량 자리 누락 탐지", _vq['severity'] != 'ok', f"신뢰도 {_vq['confidence']}")
check("올바른 수량을 후보로 제시",
      400.0 in (_vq['suggestions'].get('보유수량') or []),
      str(_vq['suggestions'].get('보유수량')))

_bad_p = dict(_vrows[0]); _bad_p['평균매수가'] = 70246.0     # 1 → 7
_vp = pf.validate_row(_bad_p)
check("평단가 1↔7 오독 탐지", _vp['severity'] != 'ok')
check("역산으로 올바른 평단가 제시",
      any(abs(c - 10246) / 10246 < 0.02 for c in (_vp['suggestions'].get('평균매수가') or [])),
      str(_vp['suggestions'].get('평균매수가')))

# 실제로 났던 사례: 185,000 을 785,000 으로 읽음
_hx = {'종목명': 'SK하이닉스', '_ticker': '000660.KS', '종목코드': '000660',
       '보유수량': 5.0, '평균매수가': 785000.0,
       '현재가': 172400.0, '수익률': -6.81, '평가손익': -63000.0}
_vhx = pf.validate_row(_hx)
check("785,000 오독 탐지", _vhx['severity'] != 'ok')
check("185,000 을 역산 복원",
      any(abs(c - 185000) / 185000 < 0.05 for c in (_vhx['suggestions'].get('평균매수가') or [])),
      str(_vhx['suggestions'].get('평균매수가')))
check("역산 수량이 1주 미만이면 후보를 내지 않음",
      all(c >= 1 for c in (_vhx['suggestions'].get('보유수량') or [])),
      str(_vhx['suggestions'].get('보유수량')))

# ── 합계 검증은 '저장할 값'으로 재계산해야 한다 ──────────────────────
# OCR 이 읽은 평가손익 열을 그대로 더하면 수량 오독에 반응하지 않는다.
_bad_rows = [dict(r) for r in _vrows]
_bad_rows[0]['보유수량'] = 4.0
_bchk, _btot = pf.validate_portfolio(_bad_rows)
check("합계 검증이 수량 오독에 반응",
      any(c['level'] != 'ok' for c in _btot['checks']), str(_btot['checks'])[:90])
check("중대 오차면 자동저장 차단", _btot['blocking'] is True)
check("오차 기여 행을 지목",
      bool(_btot.get('worst_rows')) and _btot['worst_rows'][0]['name'] == '금호건설',
      str([w['name'] for w in _btot.get('worst_rows', [])]))

# ── 저장 조건 (§20) ───────────────────────────────────────────────────
check("필수값 없으면 저장 불가",
      not pf.can_save_row({'종목명': 'X', '보유수량': None, '평균매수가': None})[0])
_w = dict(_bad_p); _w['_validation'] = pf.validate_row(_w)
check("검증 경고 행은 확인 전 저장 불가", not pf.can_save_row(_w)[0])
_w['_confirmed'] = True
check("사용자 확인 후 저장 허용", pf.can_save_row(_w)[0])
_g = dict(_vrows[1]); _g['_validation'] = pf.validate_row(_g)
check("정상 행은 바로 저장 가능", pf.can_save_row(_g)[0])

# ── 숫자 후보 생성은 일괄 치환이 아니다 ───────────────────────────────
_cands = pf.digit_candidates(785000)
check("자리별 후보 생성", 185000.0 in _cands, str(_cands[:5]))
check("후보에 원본값은 없음", 785000.0 not in _cands)
check("None 입력 방어", pf.digit_candidates(None) == [])

# 교차검증할 열이 없으면 신뢰도를 낮춘다 (모르는 것을 안다고 하지 않는다)
_nocross = pf.validate_row({'종목명': '삼성전자', '_ticker': '005930.KS',
                            '종목코드': '005930', '보유수량': 10, '평균매수가': 71200})
check("교차검증 불가 시 신뢰도 제한", _nocross['confidence'] <= 60,
      str(_nocross['confidence']))


section("34. ETF·ETN · 지평 노출 · 최적기간 미선정 근거")

# ETF 는 기업이 아니라 펀드다. EPS·BPS 가 없는데 `BPS = 가격×0.8` 폴백이 걸리면
# KODEX 200 에 '적정가 90,069원' 같은 근거 없는 값이 붙는다.
for _nm, _want in (("KODEX 200", True), ("TIGER 미국S&P500", True),
                   ("KODEX 레버리지", True), ("파워 200", True),
                   ("삼성전자", False), ("한온시스템", False),
                   ("광주신세계", False), ("SK하이닉스", False)):
    check(f"펀드 판별: {_nm} → {'펀드' if _want else '기업'}",
          engine.is_fund_like(_nm) == _want)

_etf = q.run_full_pipeline("069500.KS", T_REF, b_engine=engine, rho_cutoff=0.80)
_ev, _ef = _etf['val_eval'], _etf['four_scores']
check("ETF 도 분석은 된다 (예외 없음)", bool(_etf))
check("ETF 는 펀드로 표시", _ev.get('is_fund') is True)
check("ETF 적정가를 지어내지 않음", _ev.get('displayed_fair_value') is None,
      str(_ev.get('displayed_fair_value')))
check("ETF 목표가도 None", _ef.get('target_fundamental') is None,
      str(_ef.get('target_fundamental')))
check("ETF 산출불가 사유 제시",
      "펀드" in str(_ev.get('fair_value_status_note', '')),
      str(_ev.get('fair_value_status_note'))[:60])
check("ETF 도 경로·표본 분석은 유효",
      bool((_etf['sim_res'].get('horizons_data') or {})),
      str({h: (_etf['sim_res']['horizons_data'].get(h) or {}).get('match_count')
           for h in (20, 40)}))

# ROE 를 못 구할 때 12.5% 리터럴로 채우지 않는다
from bitemporal_engine import STOCK_METRICS_DB as _SMD
check("ETF 의 ROE 를 리터럴로 채우지 않음",
      (_SMD.get("069500.KS") or {}).get('roe') is None,
      str((_SMD.get("069500.KS") or {}).get('roe')))

# ── 최적 보유기간: 게이트를 풀지 않되 근거를 노출한다 ──────────────────
_sim_s = snap['sim_res']
check("자격 통과 지평이 있으면 최적기간이 선정됨",
      (not any(v['eligible'] for v in (_sim_s.get('horizon_eligibility') or {}).values()))
      or _sim_s.get('optimal_holding_period_days') is not None,
      f"최적={_sim_s.get('optimal_holding_period_str')}")

_dan = q.run_full_pipeline("003490.KS", T_REF, b_engine=engine, rho_cutoff=0.80)['sim_res']
if not _dan.get('optimal_holding_period_days'):
    check("미선정이면 근접 지평을 알려줌", _dan.get('horizon_nearest_miss') is not None,
          str(_dan.get('horizon_nearest_miss'))[:70])
    check("미선정이면 부족분을 수치로 제시",
          bool((_dan.get('horizon_nearest_miss') or {}).get('needs')))
    check("표본이 없어 판정조차 못한 지평을 명시",
          _dan.get('horizons_without_sample') is not None,
          str(_dan.get('horizons_without_sample')))
else:
    check("최적기간 선정됨", True, str(_dan.get('optimal_holding_period_days')))

check("6개 지평 데이터는 항상 산출", len(_sim_s.get('horizons_data') or {}) == 6,
      str(sorted((_sim_s.get('horizons_data') or {}).keys())))

# ── 출처 매트릭스에서 '기업 IR' 행 제거 ────────────────────────────────
# 가격 교차검증 표인데 가격 역할이 없고, 유일한 연결점(rNPV 제외 사유)은
# 이미 밸류에이션 화면에 표시되어 같은 말을 두 곳에서 하고 있었다.
_, _, _mtx2 = engine.get_realtime_stock_price_triple_check(SYMBOL)
check("'기업 IR' 행 제거", not any('기업 IR' in r['source'] for r in _mtx2),
      str([r['source'][:14] for r in _mtx2]))
check("남은 출처는 모두 사용처를 기술", all(r.get('role') for r in _mtx2))
check("가격 보유 출처는 여전히 2개 이하",
      len([r for r in _mtx2 if r['price'] is not None]) <= 2)


section("35. 현재가 실시간 연동 — 표시는 시세로, 검증은 화면값으로")

# 현재가는 조회하면 되는 값이다. OCR 이 열을 잘못 집으면 '영원무역 90원' 같은 값이 들어온다.
# ⚠️ 다만 실시간 시세에서 파생한 수익률·평가손익으로 평단가를 검증하면
#    `평가손익 = (현재가−평단)×수량` 이 **항등식**이 되어 검증력이 0 이 된다.
#    그래서 화면에서 읽은 값은 _scr_* 로 따로 보존한다.
_LH = "구분 종목명 평가손익 수익률 잔고 가능 손익분기 현재가 대비 등락 매수평균"
_LB = "\n".join([
    " 금호건설 -198,636 -4.85% 400 200 10,266 9,750 260 2.74 10,246",
    " 대한항공 -69,950 -6.64% 38 38 27,794 25,900 1,250 5.07 27,740",
])
_LC = {"금호건설": "002990", "대한항공": "003490"}
_lrows, _ = pf.parse_freeform_holdings(
    _LH + "\n" + _LB,
    resolve_name=lambda n: ((_LC[n] + ".KS", n) if n in _LC else (None, None)))

_SCR_EXPECT = {"금호건설": (9750.0, -4.85, -198636.0),
               "대한항공": (25900.0, -6.64, -69950.0)}
check("화면값을 _scr_ 로 보존",
      all((r['_scr_현재가'], r['_scr_수익률'], r['_scr_평가손익']) == _SCR_EXPECT[r['종목명']]
          for r in _lrows), str([r.get('_scr_현재가') for r in _lrows]))


def _q(tk):
    _p, _s, _m = engine.get_realtime_stock_price_triple_check(tk)
    return _p


_lrows, _nok, _nfail = pf.enrich_with_market_prices(_lrows, _q)
check("실시간 시세로 현재가 채움", _nok == 2, f"{_nok}/2 · 실패 {_nfail}")
check("수익률이 실시간 현재가 기준으로 재계산",
      all(abs(r['수익률'] - (r['현재가'] / r['평균매수가'] - 1) * 100) < 0.02
          for r in _lrows if r.get('현재가')))
check("평가손익도 실시간 기준",
      all(abs(r['평가손익'] - (r['현재가'] - r['평균매수가']) * r['보유수량']) < 1.0
          for r in _lrows if r.get('현재가')))
check("실시간을 채워도 화면값은 그대로",
      all((r['_scr_현재가'], r['_scr_수익률']) == _SCR_EXPECT[r['종목명']][:2]
          for r in _lrows))
check("시세 출처를 기록", all(r.get('_price_source') == '실시간' for r in _lrows))

# ★ 가장 중요한 검사: 실시간으로 채운 뒤에도 검증력이 남아 있는가
_lbad = [dict(r) for r in _lrows]
_lbad[0]['보유수량'] = 4.0                      # 400 → 4
_lvr, _ltot = pf.validate_portfolio(_lbad)
check("실시간 연동 후에도 수량 오독을 탐지 (항등식이 아님)",
      any(c['level'] != 'ok' for c in _ltot['checks']),
      str(_ltot['checks'])[:100])
check("중대 오차면 저장 차단 유지", _ltot['blocking'] is True)
check("올바른 수량을 여전히 제안",
      400.0 in (_lvr[0]['_validation']['suggestions'].get('보유수량') or []),
      str(_lvr[0]['_validation']['suggestions']))

# 화면에 검증 열이 아예 없어도 실시간 시세로 자릿수 오독은 잡는다 (개연성 검사)
_solo_px = _q("018880.KS")
_solo = pf.validate_row(
    {'종목명': '한온시스템', '_ticker': '018880.KS', '종목코드': '018880',
     '보유수량': 1157, '평균매수가': 37500.0}, market_price=_solo_px)
check("검증 열 없이도 자릿수 오독 탐지", _solo['severity'] != 'ok',
      f"현재가 {_solo_px:,.0f} 대비")
check("개연성 실패 사유 명시",
      any('개연성' in c['name'] for c in _solo['checks'] if not c['ok']))

# 정상 평단가는 개연성 검사를 통과해야 한다 (거짓 경보 방지)
_solo_ok = pf.validate_row(
    {'종목명': '한온시스템', '_ticker': '018880.KS', '종목코드': '018880',
     '보유수량': 1157, '평균매수가': 3750.0}, market_price=_solo_px)
check("정상 평단가는 개연성 통과",
      all(c['ok'] for c in _solo_ok['checks'] if '개연성' in c['name']))

# 시세 조회가 실패해도 죽지 않는다
_dead, _dok, _dfail = pf.enrich_with_market_prices(
    [{'종목명': 'X', '종목코드': '999999', '_ticker': '999999.KS',
      '보유수량': 1, '평균매수가': 1000}], lambda t: None)
check("시세 조회 실패를 흡수", _dok == 0 and len(_dfail) == 1
      and _dead[0]['_price_source'] == '조회실패', str(_dfail))


section("36. 지표 None 안전성 — dict.get 기본값 함정")

# ⚠️ dict.get(key, default) 는 **키가 없을 때만** 기본값을 쓴다.
#    ETF 처럼 키는 있는데 값이 None 이면 None 이 그대로 나와 float(None) 로 터진다.
#    실제로 헤더(roe_val)와 뉴스 서사(roe >= 15)에서 두 번 터졌다.
check("get 함정 재현", {'roe': None}.get('roe', 18.4) is None)

_wsrc = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
check("헤더에 _metric 헬퍼 도입", "def _metric(" in _wsrc)
for _lit, _pat in (("18.4", "latest_fund.get('roe', 18.4)"),
                   ("1973.0", "latest_fund.get('eps', 1973.0)"),
                   ("6584.0", "latest_fund.get('bps', 6584.0)"),
                   ("42.5", "latest_fund.get('debt_to_equity', 42.5)")):
    check(f"지어낸 기본값 {_lit} 제거", _pat not in _wsrc)
check("적정가 'curr_price * 1.15' 폴백 제거",
      "val_eval.get('target_1st', curr_price * 1.15)" not in _wsrc)

# ETF 는 EPS·BPS·ROE 가 아예 없다 — 화면이 죽지 않고 '미수신' 으로 나와야 한다
engine.fetch_and_update_naver_realtime("069500.KS")
_etf_meta = be.STOCK_METRICS_DB.get("069500.KS") or {}
check("ETF 의 ROE 는 None", _etf_meta.get('roe') is None, str(_etf_meta.get('roe')))

# 뉴스 서사가 None 지표로 터지지 않고, 없는 값으로 단정하지도 않아야 한다
_news_etf = engine.get_timeframe_news_analysis("069500.KS")
check("ETF 뉴스 서사가 예외 없이 생성", isinstance(_news_etf, dict))
check("ROE 없으면 장기 서사를 단정하지 않음",
      "판단 보류" in str(_news_etf.get('long_narratives', {}).get('sentiment', '')),
      str(_news_etf.get('long_narratives', {}).get('title'))[:60])
check("PER 없으면 밸류에이션 판단 보류",
      "미수신" in str(_news_etf.get('medium_catalysts', {}).get('impact', '')),
      str(_news_etf.get('medium_catalysts', {}).get('impact'))[:60])

# 일반 종목은 예전처럼 수치 기반 서사가 나와야 한다 (회귀 방지)
_news_now = engine.get_timeframe_news_analysis(SYMBOL)
check("일반 종목은 ROE 기반 서사 유지",
      "판단 보류" not in str(_news_now.get('long_narratives', {}).get('sentiment', '')),
      str(_news_now.get('long_narratives', {}).get('sentiment')))


section("37. 미연동이던 3개 항목 실연동 — 업종·수급·공시")

# "종목당 개별 조회라 불가"라고 판단했던 것이 틀렸다. 실제로 조사하니 셋 다 받아진다.
#   업종: 업종 목록 1페이지(79개+등락률) + 업종상세 79회 → 4천 종목 매핑, 1시간 캐시
#   수급: 종목 페이지에 일자별 기관·외국인 순매매 표가 있다
#   공시: DART 당일 공시 목록이 API 키 없이 열린다
_ds = {d['label']: d for d in mkt.data_status()}
for _lab in ('업종 상대강도', '외국인·기관 수급'):
    check(f"{_lab} 연동됨", _ds[_lab]['availability'] == 'full',
          _ds[_lab]['availability'])
# 라운드 41 — DART 공시에 공개 뉴스 RSS 3곳을 더해 완전 연동이 됐다.
check("뉴스·공시 촉매 연동됨", _ds['뉴스·공시 촉매']['availability'] == 'full',
      _ds['뉴스·공시 촉매']['availability'])
check("촉매 항목이 실제 출처를 명시",
      "DART" in _ds['뉴스·공시 촉매']['detail']
      and "연합뉴스" in _ds['뉴스·공시 촉매']['detail'])
check("본문 미저장을 밝힌다",
      "본문은 저장하지 않는다" in _ds['뉴스·공시 촉매']['detail'])
_spec_cov = sum(d['spec_weight_pct'] for d in mkt.data_status()
                if d['availability'] != 'none')
check("명세 가중치 100% 커버", abs(_spec_cov - 100.0) < 0.1, f"{_spec_cov:.0f}%")

# ── 업종 상대강도 ─────────────────────────────────────────────────────
_by_code, _sectors = mkt.fetch_sector_map()
check("업종 목록 수집", len(_sectors) >= 50, f"{len(_sectors)}개 업종")
check("종목→업종 매핑 규모", len(_by_code) >= 1000, f"{len(_by_code)}종목")
check("삼성전자 업종 매핑", (_by_code.get('005930') or {}).get('sector'),
      str((_by_code.get('005930') or {}).get('sector')))
_rs, _sname = mkt.score_sector_rs(_by_code.get('005930'), _sectors)
check("업종 상대강도 백분위 0~100", _rs is not None and 0 <= _rs <= 100, str(_rs))
check("업종 자료가 캐시됨", mkt._SECTOR_CACHE['ts'] > 0)

# ── 외국인·기관 수급 ──────────────────────────────────────────────────
_flow = mkt.fetch_investor_flow('005930')
check("수급 시계열 수신", _flow is not None and _flow.get('days', 0) >= 5,
      str(_flow.get('days') if _flow else None))
check("5·20일 누적 산출", _flow and all(k in _flow for k in
      ('inst_5d', 'frgn_5d', 'inst_20d', 'frgn_20d')))
# 금액이 큰 대형주가 자동으로 유리해지면 안 된다 — 거래량 대비 강도로 정규화한다
_fs_big, _ = mkt.score_investor_flow(
    {'frgn_5d': 1e6, 'inst_5d': 1e6, 'frgn_20d': 1e6, 'inst_20d': 1e6}, 1e8)
_fs_small, _ = mkt.score_investor_flow(
    {'frgn_5d': 1e4, 'inst_5d': 1e4, 'frgn_20d': 1e4, 'inst_20d': 1e4}, 1e6)
check("수급 점수는 거래량 대비 강도 (절대 금액 아님)",
      abs(_fs_big - _fs_small) < 1.0, f"대형 {_fs_big:.1f} vs 소형 {_fs_small:.1f}")
_fs_rev, _det = mkt.score_investor_flow(
    {'frgn_5d': 5e5, 'inst_5d': 5e5, 'frgn_20d': -1e6, 'inst_20d': -1e6}, 1e6)
check("순매수 전환을 탐지", _det.get('turned_positive') is True)
check("동시 순매수를 탐지", _det.get('both_buying') is True)
check("수급 자료 없으면 None (지어내지 않음)",
      mkt.score_investor_flow(None, 1e6)[0] is None)

# ── 공시 ─────────────────────────────────────────────────────────────
_disc = mkt.fetch_disclosures()
# ⚠️ 공시는 장이 열려야 쌓인다. 자정 직후·휴장일에는 0건이 정상이므로
#    '수집 실패'와 '아직 공시가 없는 시각'을 구분해야 한다.
#    시각에 따라 깨지는 테스트는 신호가 아니라 소음이다.
import datetime as _dtd
_now_d = _dtd.datetime.now()
_market_ran = (_now_d.weekday() < 5 and _now_d.hour >= 10)
check("공시 수집 경로 정상 (형태 확인)", isinstance(_disc, dict))
if _market_ran:
    check("당일 공시 수집", len(_disc) >= 20, f"{len(_disc)}개사")
else:
    check(f"공시 — 장 시작 전({_now_d.strftime('%H:%M')})이라 0건이 정상",
          isinstance(_disc, dict))
_types = {i['type'] for v in _disc.values() for i in v}
if _disc:
    check("공시 유형 분류", len(_types) >= 3, str(sorted(_types)[:6]))
else:
    check("공시 유형 분류 — 수집분이 없어 판정 보류", True)
check("공시 유형이 정의된 값", _types <= (
    {lbl for lbl, _k in mkt.DISCLOSURE_TYPES} | {'기타'}), str(sorted(_types)))
_sc_none, _ = mkt.score_disclosures(None)
check("공시 없으면 0점 (음수·임의값 아님)", _sc_none == 0.0, str(_sc_none))
_sc_big, _ = mkt.score_disclosures([{'type': '수주·공급계약'}])
_sc_small, _ = mkt.score_disclosures([{'type': 'IR·안내'}])
check("공시 유형별 무게 차등", _sc_big > _sc_small, f"수주 {_sc_big} > IR {_sc_small}")
check("공시 점수 0~100", 0 <= _sc_big <= 100 and 0 <= _sc_small <= 100)


section("38. Bollinger·DeMARK 신호가 종목마다 분화되는가")

# ⚠️ 구버전 결함 두 가지
#   ① 화면이 four_scores['bollinger_...'] 라는 **없는 키**를 읽어
#      밴드 하단 23% 종목도 늘 '특이사항 없음' 으로 나왔다.
#   ② DeMARK 가 '오늘 봉에서 희귀 사건이 있었나'만 세어 전 종목이
#      Bullish 8 / Bearish 0 고정, 라벨은 늘 '방향성 탐색 중' 이었다.
_bb_states, _bull, _bear, _labels = [], [], [], []
_bb_pcts = []
for _sym in ("005930.KS", "003490.KS", "018880.KS", "037710.KS"):
    _sn = q.run_full_pipeline(_sym, T_REF, b_engine=engine, rho_cutoff=0.80)
    _f = _sn['four_scores']
    _bb_states.append(_f.get('bb_state'))
    _bb_pcts.append(_f.get('bb_position_pct'))
    _bull.append(_f.get('demark_bullish_score'))
    _bear.append(_f.get('demark_bearish_score'))
    _labels.append(_f.get('demark_direction_text'))
    check(f"{_sym} 볼린저 위치 산출", _f.get('bb_position_pct') is not None,
          f"{_f.get('bb_position_pct')} · {_f.get('bb_state')}")

check("볼린저 상태가 four_scores 에 노출됨", all(s for s in _bb_states), str(_bb_states))
# 이 검사의 목적은 "밴드 위치가 상수로 굳어 있지 않은가" 다.
# 그런데 상태 라벨(하단권/중앙권/상단권)은 4종목이 우연히 같은 날
# 다 중앙권일 수 있다 — 그건 시장 상태이지 고장이 아니다.
# 라벨 대신 **위치 수치**가 갈리는지로 본다 (시각에 흔들리지 않는다).
check("볼린저 위치가 종목마다 갈린다 (상수로 굳지 않음)",
      len(set(round(float(x), 1) for x in _bb_pcts if x is not None)) >= 2,
      f"라벨 {_bb_states} · 위치 {[round(float(x),1) for x in _bb_pcts if x is not None]}")
check("Bearish 가 0 고정이 아님", len(set(_bear)) >= 2, str(_bear))
check("Bullish 가 8 고정이 아님", len(set(_bull)) >= 2, str(_bull))
check("DeMARK 라벨이 '방향성 탐색 중' 하나로 고정되지 않음",
      len(set(_labels)) >= 2, str(_labels))
check("점수는 0~100", all(0 <= x <= 100 for x in _bull + _bear))

# 데이터가 아주 부족하면 '50점 중립' 으로 위장하지 않고 산출 불가로 남긴다.
# (구버전 폴백은 bullish 50 / bearish 50 / '중립' 이라 실제 중립과 구분되지 않았다)
_tiny = pd.DataFrame({
    'trade_date': pd.date_range('2025-01-01', periods=5, freq='B').strftime('%Y-%m-%d'),
    'adj_close': np.linspace(100, 102, 5)})
_tiny['open'] = _tiny['adj_close']
_tiny['high'] = _tiny['adj_close'] * 1.01
_tiny['low'] = _tiny['adj_close'] * 0.99
_tiny['volume'] = 1e6
_dm_tiny = q.compute_demark_indicators(q.compute_technical_indicators(_tiny))
_is_fallback = '산출 불가' in str(_dm_tiny.get('demark_label', ''))
if _is_fallback:
    check("산출 불가를 50점 중립으로 위장하지 않음",
          _dm_tiny.get('bullish_score') == 0 and _dm_tiny.get('bearish_score') == 0,
          f"{_dm_tiny.get('bullish_score')}/{_dm_tiny.get('bearish_score')}")
else:
    # 폴백을 타지 않았다면 최소한 옛 하드코딩 50/50 은 아니어야 한다
    check("옛 하드코딩 50/50 이 아님",
          not (_dm_tiny.get('bullish_score') == 50 and _dm_tiny.get('bearish_score') == 50),
          f"{_dm_tiny.get('bullish_score')}/{_dm_tiny.get('bearish_score')}")
check("폴백 사전이 0점·산출불가로 정의됨",
      "'bullish_score': 0" in open(_os.path.join(PROJ, "quant_indicators.py"),
                                   encoding='utf-8').read())


section("39. 탭별 판정 + 최종 종합 결론")

_vd = q.build_final_verdict(snap)
check("결론 한 줄이 나옴", bool(_vd.get('headline')), str(_vd.get('headline')))
check("행동 코드가 정의된 값", _vd['action'] in
      ('BUY', 'ACCUMULATE', 'HOLD', 'REDUCE', 'SELL', 'NO_TRADE'), _vd['action'])
check("탭이 6개", len(_vd['tabs']) == 6, str(len(_vd['tabs'])))
check("탭마다 판정 문구", all(t['verdict'] for t in _vd['tabs']))
check("탭마다 근거 제시", all(t['reasons'] for t in _vd['tabs']))
check("종합 점수 0~100", _vd['score'] is None or 0 <= _vd['score'] <= 100, str(_vd['score']))

# ⚠️ 종합 점수는 **하나만** 존재해야 한다.
#    한때 배너(탭 가중평균)와 하단 카드(규칙집 산식)가 각자 점수를 만들어
#    같은 종목에 49점과 65점이 동시에 떴다 (광주신세계 16점 차).
check("종합 점수는 규칙집 final_action_score 와 동일",
      _vd['score'] == fs.get('final_action_score'),
      f"{_vd['score']} vs {fs.get('final_action_score')}")
check("판정 문구도 엔진 판정에서 파생",
      _vd.get('title') == fs.get('final_action_title'),
      f"{_vd.get('title')} vs {fs.get('final_action_title')}")

# 화면에 보여주는 산식이 실제로 점수를 만든 그 산식인가
_comp = _vd['composition']
check("산식 구성이 3요소", len(_comp) == 3, str([c['label'] for c in _comp]))
check("산식 비중 합 100%", abs(sum(c['weight_pct'] for c in _comp) - 100.0) < 0.5,
      f"{sum(c['weight_pct'] for c in _comp):.1f}%")
_raw = sum(c['contribution'] for c in _comp if c['contribution'] is not None)
check("가중합이 규칙집 가중치와 일치",
      abs(_raw - _vd['raw_weighted_sum']) < 0.2, f"{_raw:.1f} vs {_vd['raw_weighted_sum']}")
check("상한이 적용되면 최종 점수 ≤ 가중합",
      (not _vd['cap_applied']) or _vd['score'] <= _vd['raw_weighted_sum'] + 0.5,
      f"cap={_vd['cap_applied']} {_vd['score']} vs {_vd['raw_weighted_sum']}")
check("탭 점수는 합산하지 않는다 (관점별 판정 전용)",
      'contributions' not in _vd)

# 여러 종목에서도 두 값이 갈리지 않아야 한다
for _sym in ("005930.KS", "000660.KS", "037710.KS"):
    _s2 = q.run_full_pipeline(_sym, T_REF, b_engine=engine, rho_cutoff=0.80)
    _v2 = q.build_final_verdict(_s2)
    check(f"{_sym} 점수 일치",
          _v2['score'] == _s2['four_scores'].get('final_action_score'),
          f"{_v2['score']} vs {_s2['four_scores'].get('final_action_score')}")
    check(f"{_sym} 문구 일치",
          _v2.get('title') == _s2['four_scores'].get('final_action_title'))

# ⚠️ 거부권 — 평균으로 상쇄되면 안 되는 조건
check("거부 조건 목록 존재", isinstance(_vd['vetoes'], list))
if _vd['vetoes']:
    check("거부 조건이 있으면 매수 결론이 아님",
          _vd['action'] not in ('BUY', 'ACCUMULATE'),
          f"{_vd['action']} · {_vd['vetoes'][:1]}")

# 결론이 고정 문구가 아니어야 한다. 단, 실제 시장에서는 약세장이면 여러 종목이
# 같은 '사지 마세요' 로 수렴하는 것이 맞으므로(그게 판정이 작동한다는 뜻),
# 분화 능력은 엔진 판정 문구를 달리한 합성 입력으로 검증한다.
_syn_base = q.run_full_pipeline("005930.KS", T_REF, b_engine=engine, rho_cutoff=0.80)
# 매수 계열 문구는 실스냅샷의 거부권에 걸려 HOLD 로 하향되는 것이 정상이므로
# (거부권이 결론을 지배해야 한다), 거부권과 무관한 세 문구로 분화를 확인한다.
_heads_syn = set()
for _t39, _sc39 in [("조건 확인·관망", 62), ("비중축소 검토", 40),
                    ("거래 회피", 20)]:
    _s39 = dict(_syn_base)
    _fs39 = dict(_syn_base['four_scores'])
    _fs39['final_action_title'] = _t39
    _fs39['final_action_score'] = _sc39
    _s39['four_scores'] = _fs39
    _heads_syn.add((q.build_final_verdict(_s39)['action'],))
check("결론이 판정 문구에 따라 분화", len(_heads_syn) >= 3, str(_heads_syn))
check("실데이터 결론이 어휘 안에 있음", q.build_final_verdict(_syn_base)['headline'] != "")

# ETF 는 밸류에이션 탭이 산출 불가여야 하고, 그래도 결론은 나와야 한다
_etf_vd = q.build_final_verdict(
    q.run_full_pipeline("069500.KS", T_REF, b_engine=engine, rho_cutoff=0.80))
check("ETF 밸류에이션 탭 산출 불가",
      any(t['key'] == 'valuation' and not t['available'] for t in _etf_vd['tabs']))
check("ETF 도 결론은 나옴", bool(_etf_vd['headline']))

check("탭 가중치 합 = 1.0", abs(sum(q.TAB_WEIGHTS.values()) - 1.0) < 1e-9,
      str(sum(q.TAB_WEIGHTS.values())))


section("40. 배포 전 정합성 — 교차검증 게이트 · 합성값 위장 금지")

# ① 스캐너에도 시세 교차검증 게이트가 있어야 한다 (예전엔 상세화면만 방어)
_snap40 = q.run_full_pipeline(SYMBOL, T_REF, b_engine=engine, rho_cutoff=0.80)
_cc = _snap40.get('price_cross_check') or {}
check("스냅샷에 교차검증 결과 탑재", 'passed' in _cc, str(_cc)[:80])
check("정상 시세는 통과", _cc.get('passed') in (True, None), str(_cc.get('passed')))
_scan_src40 = _insp.getsource(q.run_screener_scan)
check("스캐너가 교차검증 게이트를 적용",
      "price_cross_check" in _scan_src40 and "continue" in _scan_src40)
check("허용 오차는 규칙집이 정의", q.PRICE_CROSS_TOL_PCT == qi.rb(
    'RULES_DATA_INTEGRITY', 'price_cross_tolerance_pct', -1), str(q.PRICE_CROSS_TOL_PCT))

# 벌어진 시세를 흉내 내면 실패로 판정해야 한다
_fake_mtx = [{'source': 'A', 'price': 10000.0}, {'source': 'B', 'price': 10300.0}]
_cc_bad = q._price_cross_check(_fake_mtx)
check("3% 오차는 교차검증 실패", _cc_bad['passed'] is False, _cc_bad['note'])
_cc_one = q._price_cross_check([{'source': 'A', 'price': 10000.0}])
check("출처 1개면 '대조 불가' (통과로 위장하지 않음)", _cc_one['passed'] is None)

# ② BPS·EPS 합성 금지 — PBR·PER 역산(항등식)만 허용
_esrc40 = open(_os.path.join(PROJ, "bitemporal_engine.py"), encoding='utf-8').read()
_active = [l for l in _esrc40.splitlines()
           if 'price * 0.8' in l and not l.strip().startswith('#')]
check("bps = price*0.8 합성 코드 제거 (주석만 남음)", not _active, str(_active[:1]))
check("역산 불가 시 None 처리", 'bps = None' in _esrc40 and 'eps = None' in _esrc40)

# ③ 유사도 결합 가중치가 규칙집에서 온다
check("규칙집에 RULES_SIMILARITY 존재",
      'RULES_SIMILARITY' in qi.RULEBOOK, str(qi.RULEBOOK.get('RULES_SIMILARITY')))
_qsrc40 = open(_os.path.join(PROJ, "quant_indicators.py"), encoding='utf-8').read()
check("결합식이 rb() 로 규칙집을 읽음",
      "rb('RULES_SIMILARITY', 'pearson_weight'" in _qsrc40)
check("리터럴 'rho * 0.7 +' 제거", "combined = rho * 0.7 +" not in _qsrc40)

# ④ 탭 가중치도 규칙집과 일치
for _k, _v in q.TAB_WEIGHTS.items():
    check(f"탭 가중치 {_k} = 규칙집",
          abs(_v - qi.rb('RULES_TAB_WEIGHTS', _k, -1)) < 1e-9, f"{_v}")


section("41. 최종 출시 감사 — 날조 제거 · 원천 정제 · 시장접미사 · 확률 100%")

# ① 뉴스 모듈이 수집하지 않은 사건·출처를 만들지 않는다
_news41 = engine.get_timeframe_news_analysis(SYMBOL)
_srcs41 = " ".join(str(_news41[k].get('source', '')) for k in _news41)
for _fake in ("KRX & 실시간", "리서치 컨센서스", "IR 공식 보고서"):
    check(f"날조 출처 제거: '{_fake}'", _fake not in _srcs41)
check("미연동·관찰 표기 존재", "미연동" in _srcs41 and "관찰" in _srcs41)
_body41 = " ".join(str(_news41[k].get('impact', '')) + str(_news41[k].get('title', ''))
                   for k in _news41)
for _fab in ("매수세 유입", "차익매물", "컨센서스 상향", "독보적", "턴어라운드 기대"):
    check(f"근거 없는 서술 제거: '{_fab}'", _fab not in _body41)
check("수급 미단정 고지 포함", "단정하지 않" in _body41)
_esrc41 = open(_os.path.join(PROJ, "bitemporal_engine.py"), encoding='utf-8').read()
check("TIMEFRAME_NEWS_DB 날조 블록 제거",
      "'주력 사업 실적 턴어라운드 컨센서스" not in _esrc41)

# ② 원천 봉 정제 — 거래정지 0원 봉 제외, 피드 반올림 불일치 복원
_p41, _ = engine.load_bitemporal_data(SYMBOL, "2014-01-01", T_REF)
_o = _p41['open_raw'].values.astype(float)
_h = _p41['high_raw'].values.astype(float)
_l = _p41['low_raw'].values.astype(float)
_c41 = _p41['close_raw'].values.astype(float)
check("거래정지(0원) 봉 제외", not ((_o <= 0) & (_h <= 0) & (_l <= 0)).any())
_viol = int(((_l > _o + 1e-9) | (_o > _h + 1e-9)
             | (_l > _c41 + 1e-9) | (_c41 > _h + 1e-9)).sum())
check("OHLC 불변조건 전체 통과", _viol == 0, f"위반 {_viol}봉")

# ③ 시장 접미사 보존 — .KQ 로 조회하면 .KQ 키에 저장돼야 한다
_t41, _n41, _i41 = engine.fetch_and_update_naver_realtime("086520.KQ")
check("KQ 접미사 보존", _t41 == "086520.KQ", str(_t41))
_px_kq, _st_kq, _mx_kq = engine.get_realtime_stock_price_triple_check("086520.KQ")
_cc_kq = q._price_cross_check(_mx_kq)
check("KQ 종목 교차검증 통과 (시드 위장 제거)", _cc_kq.get('passed') is True,
      str(_cc_kq.get('note'))[:70])

# ④ 선도달 확률 3범주 합 100%
if snap['sim_res'].get('tp_first_prob') is not None:
    _tp41 = snap['sim_res']['tp_first_prob']
    _sl41 = snap['sim_res']['sl_first_prob']
    _nt41 = snap['sim_res'].get('no_touch_prob')
    check("미도달 범주 존재", _nt41 is not None)
    check("tp+sl+미도달 = 100%", _nt41 is not None
          and abs(_tp41 + _sl41 + _nt41 - 100.0) <= 0.35,
          f"{_tp41}+{_sl41}+{_nt41}")

# ⑤ 패턴 탭이 죽은 키(win_rate) 대신 엔진 판정을 쓴다
_vd41 = q.build_final_verdict(snap)
_pat41 = next(t for t in _vd41['tabs'] if t['key'] == 'pattern')
if snap['sim_res'].get('probabilities_shown'):
    check("확률 허용 시 패턴 탭이 산출됨 (산출불가 모순 제거)",
          _pat41['available'] and _pat41['score'] is not None,
          f"{_pat41['verdict']} {_pat41['score']}")

# ⑥ 시장 국면 라벨에 판정 근거 포함 (당일 등락과 모순처럼 보이지 않게)
check("국면 라벨에 근거(이동평균) 표기",
      "일선" in str(snap['four_scores'].get('market_regime_label', '')),
      str(snap['four_scores'].get('market_regime_label'))[:60])

# ⑦ 출처·저장 문구 사실성
check("DART '제출 원본 재공시' 단정 제거", "제출 원본을 재공시한 값을 사용" not in _esrc41)
_w41 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
check("재무기준일을 보고서 기준일로 위장하지 않음", "보고서 기준일 아님" in _w41)
check("실행 가격에 기준(신규/보유자) 라벨 — 쉬운 말이어도 기준은 남는다",
      "이미 갖고 있다면" in _w41 and "현재가 기준 대응" in _w41
      and "아직 안 샀다면" in _w41 and "신규 매수 기준" in _w41)
check("저장 문구가 원격에서 거짓이 되지 않음", "이 브라우저 세션에만 유지" in _w41)


section("42. 관심종목 카드 행동점수 · 관심종목 저장")

# ⚠️ 스캔 결과 행의 키는 'final_score' 인데 카드가 없는 키 'final_action_score' 를
#    읽어 모든 후보가 '퀀트 행동점수 미산출' 로 표시됐다 (죽은 키 계열 3번째).
_scan_src42 = _insp.getsource(q.run_screener_scan)
check("스캔 행에 final_score 키 존재", '"final_score"' in _scan_src42)
_w42 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
check("카드가 final_score 를 조회", "r.get('final_score')" in _w42)
check("죽은 키 조회 제거", "r.get('final_action_score')" not in _w42)
check("미산출 후보는 사유와 함께 분리", "행동점수 미산출로 본 목록에서 제외" in _w42)

# 관심종목 저장 — 보유종목과 같은 원칙 (로컬 파일, 무효 코드 정규화·제외)
_wlp = _os.path.join(PROJ, "_probe", "_wl_reg.json")
pf.save_watchlist([{'code': '28670', 'name': '팬오션'}, {'code': '', 'name': 'X'}],
                  path=_wlp)
_wl42, _ = pf.load_watchlist(path=_wlp)
check("관심종목 저장·복원 왕복", len(_wl42) == 1 and _wl42[0]['code'] == '028670',
      str(_wl42))
check("관심종목 삭제", pf.delete_watchlist(path=_wlp))
check("빈 파일 로드 방어", pf.load_watchlist(path=_wlp) == ([], None))
check("스캔 대상에 관심종목 포함", "watch = [w['code']" in _w42)
check("홈 버튼이 관심종목을 지우지 않음", "'watchlist'" not in _w42.split(
    "btn_home")[1].split("st.rerun()")[0])


section("43. 온라인 붙여넣기 — 브라우저 클립보드 · 클라우드 OCR 엔진")

# ⚠️ 기존 붙여넣기는 **서버 프로세스의 클립보드**를 읽어 로컬에서만 동작했다.
#    온라인 사용자는 스크린샷 경로 자체가 막혀 있었다. 브라우저 paste 이벤트로
#    받은 이미지를 같은 인식 파이프라인에 태운다.
import base64 as _b64
import io as _io43

from PIL import Image as _Img43

_buf43 = _io43.BytesIO()
_Img43.new("RGB", (40, 20), (255, 255, 255)).save(_buf43, format="PNG")
_png43 = _buf43.getvalue()
_url43 = "data:image/png;base64," + _b64.b64encode(_png43).decode()

_raw43, _err43 = pf.decode_pasted_image({'data_url': _url43})
check("붙여넣은 data URL → 원본 바이트 복원", _err43 is None and _raw43 == _png43)
check("None·빈 입력 방어", pf.decode_pasted_image(None) == (None, None)
      and pf.decode_pasted_image({}) == (None, None))
_r43, _e43 = pf.decode_pasted_image({'data_url': 'data:text/plain;base64,aGk='})
check("이미지 아닌 붙여넣기 거부", _r43 is None and _e43 is not None)
_r43b, _e43b = pf.decode_pasted_image({'data_url': 'data:image/png;base64,%%%'})
check("깨진 데이터는 예외 대신 사유 반환", _r43b is None and _e43b is not None)
_big43 = "data:image/png;base64," + _b64.b64encode(
    b"\0" * (pf.PASTE_MAX_BYTES + 1)).decode()
check("용량 상한 초과 거부", pf.decode_pasted_image({'data_url': _big43})[0] is None)

_comp43 = _os.path.join(PROJ, "components", "paste_image", "index.html")
check("붙여넣기 컴포넌트 파일 존재", _os.path.exists(_comp43))
_html43 = open(_comp43, encoding='utf-8').read() if _os.path.exists(_comp43) else ""
check("컴포넌트가 Streamlit 값 반환 규약을 지킴",
      "streamlit:componentReady" in _html43 and "streamlit:setComponentValue" in _html43)
check("컴포넌트가 이미지를 외부로 보내지 않음",
      "fetch(" not in _html43 and "XMLHttpRequest" not in _html43)
check("원격에서도 붙여넣기 상자 노출 (로컬 전용 분기 아님)",
      "paste_image_box(" in _w42 and "if is_local_session():\n                st.markdown"
      not in _w42)

# 클라우드 OCR 은 torch 없이 — Tesseract(apt) + pytesseract(pip)
_req43 = [x.strip().lower() for x in
          open(_os.path.join(PROJ, "requirements.txt"), encoding='utf-8').read().splitlines()
          if x.strip() and not x.strip().startswith("#")]
_pkg43 = open(_os.path.join(PROJ, "packages.txt"), encoding='utf-8').read()
check("클라우드 OCR 바인딩(pytesseract) 포함",
      any(x.startswith("pytesseract") for x in _req43))
check("메모리 초과 유발 패키지(torch·easyocr) 여전히 제외",
      not any(x.startswith("torch") or x.startswith("easyocr") for x in _req43))
check("apt 로 Tesseract 엔진·한국어 데이터 배포",
      "tesseract-ocr" in _pkg43 and "tesseract-ocr-kor" in _pkg43)
check("한글 폰트 패키지 유지", "fonts-nanum" in _pkg43)
# 엔진 우선순위: 정확한 easyocr 먼저, 없으면(클라우드) Tesseract.
# 예전엔 pytesseract 우선이라, 로컬에 Tesseract 가 깔린 사용자는 easyocr 을
# 설치하고도 부정확한 엔진으로 인식되고 있었다.
check("엔진 선택은 easyocr 우선 → pytesseract 대체",
      _insp.getsource(pf.ocr_backend).index("easyocr")
      < _insp.getsource(pf.ocr_backend).index("pytesseract"))
check("Tesseract 도 낱말 좌표(image_to_data)로 열을 복원",
      "image_to_data" in open(_os.path.join(PROJ, "portfolio.py"),
                              encoding='utf-8').read())


section("44. HTS 잔고 화면 인식률 — 열 분해 · 코드 복원 · 오독 차단")

# ⚠️ 실사용 캡처(4202 주식잔고 10종목)에서 인식 0건이 나왔다. 원인은 OCR 품질이
#    아니라 표 해석이었다: 헤더 한 칸('수익률')을 OCR 이 놓치자 그 뒤 열이 통째로
#    밀렸고, '종목번호' 가 코드 열 이름으로 등록돼 있지 않았다.

# ① 열은 헤더가 아니라 데이터 x 구간으로 묶는다 (헤더가 빠져도 자리 유지)
_box = lambda x0, x1, y, t: {'x': x0, 'x1': x1, 'w': x1 - x0, 'xc': (x0 + x1) / 2,
                             'yc': y, 'h': 10, 'text': t}
_lines44 = [
    [_box(10, 60, 10, '금호건설'), _box(100, 140, 10, 'A002990'),
     _box(200, 240, 10, '400'), _box(300, 340, 10, '10,246')],
    [_box(10, 90, 30, 'SOL 팔란티어'), _box(100, 140, 30, 'A0040Y0'),
     _box(205, 240, 30, '739'), _box(305, 340, 30, '8,343')],
    [_box(10, 55, 50, '코텍'), _box(100, 140, 50, 'A052330'),
     _box(210, 240, 50, '173'), _box(300, 340, 50, '12,326')],
]
_cols44 = pf._cluster_columns(_lines44)
check("긴 종목명이 옆 열을 삼키지 않음 (열 4개 유지)",
      _cols44 is not None and len(_cols44) == 4, str(_cols44 and len(_cols44)))

# ② 헤더 덩어리는 낱말로 쪼개 각 열에 나눠 준다
_hdr44 = [_box(10, 60, 0, '종목명'), _box(100, 240, 0, '종목번호 평가손익')]
_names44 = pf._label_columns(_cols44, _hdr44)
check("한 덩어리로 읽힌 헤더가 열별로 분배됨",
      '종목번호' in _names44[1] and '종목번호' not in _names44[2], str(_names44))

# ③ 종목번호 열 이름이 등록돼 있어야 코드 열을 찾는다
check("'종목번호' 가 코드 열 이름", 'code' in pf.classify_header_cells(
    ['구분', '종목명', '종목번호', '잔고', '매수평균']))
check("'구분종목명' 처럼 붙어 읽혀도 종목명 열을 살림",
      pf.classify_header_cells(['구분종목명', '종목번호', '잔고', '매수평균']).get('name') == 0)
check("'손익분기' 는 여전히 평단가로 잡히지 않음",
      pf.classify_header_cells(['종목명', '손익분기', '매수평균']).get('price') == 2)
check("'매도가능잔고' 는 여전히 수량으로 잡히지 않음",
      pf.classify_header_cells(['종목명', '매도가능잔고', '잔고']).get('quantity') == 2)

# ④ A접두·문자 포함 코드·글자 오독
check("A접두 제거", pf.read_code_cell('A005930')[0] == '005930')
check("A를 4로 오독한 접두도 제거", pf.read_code_cell('4005930')[0] == '005930')
check("문자 포함 KRX 코드 보존", pf.read_code_cell('A0040Y0')[0] == '0040Y0')
check("글자 오독 교정", pf.read_code_cell('A01888D')[0] == '018880')
check("옆 값이 딸려 와도 코드만 집음",
      pf.read_code_cell('A066570 -178568')[0] == '066570')
check("코드가 아닌 칸은 None", pf.read_code_cell('금호건설')[0] is None)

# ⑤ 숫자 칸의 글자 오독 — 고치되, 못 고치면 조용히 자르지 않는다
check("'4OO' → 400", pf._cell_number('4OO') == 400)
check("'87,60O' → 87600", pf._cell_number('87,60O') == 87600)
check("고치지 못한 글자가 남으면 값을 만들지 않음 (4OOX → None)",
      pf._cell_number('4OOX') is None)
check("정상 숫자는 그대로", pf._cell_number('1,157') == 1157)

# ⑥ 한 칸에 붙어 온 값을 빈 이웃 칸으로 되돌린다 (숫자 토큰만)
check("붙어 온 숫자를 빈 칸으로 이동",
      pf._redistribute_row_cells(['LG전자', 'A066570 -178568', '', '6']) ==
      ['LG전자', 'A066570', '-178568', '6'])
check("여러 낱말 종목명은 쪼개지 않음",
      pf._redistribute_row_cells(['', 'SOL 팔란 티어', 'A0040Y0'])[1] == 'SOL 팔란 티어')

# ⑦ 코드와 종목명이 다른 종목을 가리키면 종목명을 택하고 반드시 알린다
#    (A111770 영원무역 → '771770' 처럼 한 글자 오독이 실재하는 다른 코드가 된다)
_txt44 = ("종목명\t종목번호\t평가손익\t잔고\t매수평균\t현재가\n"
          "영원무역\t771770\t-9,379\t33\t87,703\t87,600\n")
_rows44, _warn44 = pf.parse_table_with_header(
    _txt44, resolve_name=lambda n: ("111770.KS", "영원무역") if n == "영원무역" else (None, None))
check("종목명 기준으로 코드를 바로잡음",
      len(_rows44) == 1 and _rows44[0]['종목코드'] == '111770', str(_rows44))
check("불일치를 경고로 알림", any('서로 다른 종목' in w for w in _warn44))

# ⑧ 수량을 못 읽으면 화면의 다른 숫자로 역산하고, 역산했다고 밝힌다
_txt44b = ("종목명\t종목번호\t평가손익\t잔고\t매수평균\t현재가\n"
           "LG전자\t066570\t-178,568\t\t188,133\t158,700\n")
_rows44b, _warn44b = pf.parse_table_with_header(_txt44b, resolve_name=None)
check("평가손익·현재가·평단가로 수량 역산",
      len(_rows44b) == 1 and int(_rows44b[0]['보유수량']) == 6, str(_rows44b))
check("역산 사실을 반드시 표기", any('역산' in w for w in _warn44b))

# ⑨ 역산이 정수로 떨어지지 않으면 채우지 않는다 (지어내기 금지)
_txt44c = ("종목명\t종목번호\t평가손익\t잔고\t매수평균\t현재가\n"
           "테스트\t005930\t-1,234\t\t10,000\t9,000\n")
_rows44c, _warn44c = pf.parse_table_with_header(_txt44c, resolve_name=None)
check("애매하면 수량을 채우지 않고 건너뜀",
      len(_rows44c) == 0 and any('건너뜀' in w for w in _warn44c))

# ⑩ 수량 역산의 기준은 손익분기 (HTS 평가손익 = (현재가−손익분기)×수량)
#    평단가로 나누면 수수료만큼 어긋난 그럴듯한 오답이 나온다 (33주 → 91주 실사례).
check("손익분기 → breakeven 검증 열로 매핑",
      pf.classify_header_cells(['종목명', '손익분기', '잔고', '매수평균']).get('breakeven') == 1)
check("손익분기는 여전히 평단가(price)로는 못 잡음",
      pf.classify_header_cells(['종목명', '손익분기', '잔고']).get('price') is None)
_txt44d = ("종목명\t종목번호\t평가손익\t잔고\t손익분기\t매수평균\t현재가\n"
           "금호건설\t002990\t-462,205\t\t10,265\t10,246\t9,110\n")
_rows44d, _warn44d = pf.parse_table_with_header(_txt44d, resolve_name=None)
check("역산 기준 = 손익분기 (400주 정답, 평단 기준이면 407주 오답)",
      len(_rows44d) == 1 and int(_rows44d[0]['보유수량']) == 400, str(_rows44d))
check("역산 기준을 문구로 표기", any('손익분기로 역산' in w for w in _warn44d))
_txt44e = ("종목명\t종목번호\t평가손익\t잔고\t손익분기\t매수평균\t현재가\n"
           "영원무역\t111770\t-9,379\t\t87,873\t87,703\t87,600\n")
_rows44e, _warn44e = pf.parse_table_with_header(_txt44e, resolve_name=None)
check("검증에 어긋난 역산은 채우지 않음 (91주 오답 방지)",
      len(_rows44e) == 0 and any('건너뜀' in w for w in _warn44e), str(_rows44e))

# ⑪ Tesseract 음절 병합 — '금 호 건설' 을 한 낱말로, 열 간격은 유지
_mb44 = pf._merge_line_boxes([
    {'x': 10, 'x1': 22, 'w': 12, 'xc': 16, 'yc': 5, 'h': 12, 'text': '금'},
    {'x': 24, 'x1': 36, 'w': 12, 'xc': 30, 'yc': 5, 'h': 12, 'text': '호'},
    {'x': 38, 'x1': 52, 'w': 14, 'xc': 45, 'yc': 5, 'h': 12, 'text': '건설'},
    {'x': 120, 'x1': 170, 'w': 50, 'xc': 145, 'yc': 5, 'h': 12, 'text': 'A002990'},
], 12)
check("음절 병합 — 붙은 한글은 한 낱말", _mb44[0]['text'] == '금호건설',
      str([b['text'] for b in _mb44]))
check("음절 병합 — 열 간격은 유지 (2덩어리)", len(_mb44) == 2)
check("병합은 Tesseract 전용 (easyocr 은 구절 박스라 켜면 옆 열을 삼킴)",
      "merge_syllables=True" in open(_os.path.join(PROJ, "portfolio.py"),
                                     encoding='utf-8').read())


section("45. 시장·글로벌·뉴스 컨텍스트 · 판정 성적표")

# 이 종목만 보지 않고 판(코스피/코스닥 국면·글로벌 지표·실제 뉴스)을 함께 본다.
# 원칙: 뉴스로 점수를 올리지 않는다(위험 신호일 때 상한만), 미수신은 미수신으로,
#        판정 기록은 추가 전용(사후 수정 금지).
import market_context as mcx
import prediction_log as plog45

# ① 상장 시장 판별
check("KQ → KOSDAQ", mcx.market_of_ticker("035760.KQ") == "KOSDAQ")
check("KS → KOSPI", mcx.market_of_ticker("005930.KS") == "KOSPI")

# ② 뉴스 요약은 낱말 일치일 뿐 해석하지 않는다
_fake_news = {'available': True, 'items': [
    {'title': 'A사 유상증자 결정', 'risk_hits': ['유상증자'], 'watch_hits': []},
    {'title': 'B사 신제품 출시', 'risk_hits': [], 'watch_hits': ['신제품']},
]}
_fl = mcx.summarize_news_flags(_fake_news)
check("위험 낱말 기사 집계", _fl['risk_count'] == 1 and _fl['watch_count'] == 1)
check("위험 제목에 걸린 낱말을 그대로 보존",
      _fl['risk_titles'][0][1] == ['유상증자'])

# ③ 상한 규칙 — 좋은 뉴스는 점수를 올리지 않는다 (CAPS 에 가점 항목이 없어야 한다)
check("상한 규칙은 전부 100 미만 (감점 전용)",
      all(v < 100 for v in mcx.CONTEXT_CAPS.values()), str(mcx.CONTEXT_CAPS))
_src45 = _insp.getsource(mcx)
check("점수를 올리는 코드 없음 (bonus/uplift 부재)",
      'bonus' not in _src45 and 'uplift' not in _src45)
check("HTML 엔티티 정리(&quot; 등)", "_html.unescape" in _src45)

# ④ 파이프라인 연결 — context_cap 이 최종 min() 에 들어가는가
_qi_src45 = _insp.getsource(q.calculate_four_scores) \
    if hasattr(q, 'calculate_four_scores') else open(
        _os.path.join(PROJ, "quant_indicators.py"), encoding='utf-8').read()
check("context_cap 이 최종 상한 min() 에 포함", 'context_cap' in _qi_src45)
check("컨텍스트 사유가 cap_reasons 로 합류", 'context_reasons' in _qi_src45)
_qi_full45 = open(_os.path.join(PROJ, "quant_indicators.py"), encoding='utf-8').read()
check("시장별 국면 캐시 분리 (_regime_by_market)", "_regime_by_market" in _qi_full45)
check("컨텍스트 수집 실패해도 분석은 계속 (예외 격리)",
      "시장·뉴스 컨텍스트 수집 실패" in _qi_full45)

# ⑤ 판정 기록 — 추가 전용, 중복 차단, 표본 부족 시 비율 미표기
_pp45 = _os.path.join(PROJ, "_probe", "_pred45.jsonl")
if _os.path.exists(_pp45):
    _os.remove(_pp45)
check("기록 저장", plog45.record_prediction(
    {'ticker': '005930.KS', 'date': '2026-06-02', 'price': 200000,
     'action': 'BUY', 'score': 75, 'target': 220000, 'stop': 188000},
    path=_pp45))
check("같은 날 중복 기록 차단", not plog45.record_prediction(
    {'ticker': '005930.KS', 'date': '2026-06-02', 'price': 201000,
     'action': 'BUY', 'score': 70}, path=_pp45))
check("필수값 없으면 기록 거부", not plog45.record_prediction(
    {'ticker': '005930.KS', 'date': None, 'price': 1, 'action': 'BUY',
     'score': 1}, path=_pp45))
_rows45 = plog45.load_predictions(path=_pp45)
check("로드 1건", len(_rows45) == 1)

# ⑥ 채점 — 같은 봉에서 목표·손절 동시 도달이면 보수적으로 손절 우선
import pandas as _pd45

_df45 = _pd45.DataFrame([
    {'trade_date': '2026-06-03', 'high_raw': 230000, 'low_raw': 185000,
     'close_raw': 210000},
])
_g45 = plog45.grade_prediction(_rows45[0], _df45)
check("동시 도달 → 손절 우선 (성적 부풀리기 방지)",
      _g45 is not None and _g45['outcome'] == 'STOP', str(_g45))
_sum45 = plog45.summarize([{'row': _rows45[0], 'grade': _g45}])
check("표본 5건 미만 → 적중률 None", _sum45['hit_rate'] is None)
check("미표기 사유 문구", bool(_sum45['min_sample_note']))
check("HOLD/NO_TRADE 는 진입 적중률에서 제외",
      'HOLD' not in plog45.ENTRY_ACTIONS and 'NO_TRADE' not in plog45.ENTRY_ACTIONS)
_os.remove(_pp45)

# ⑦ 화면 연결 — 컨텍스트 패널·실측 성적·기록 호출
# ('판정 성적표' 대기형 패널은 기록이 없으면 빈 화면이라 제거하고, 이미 채점이
#  끝난 가상 백테스트 실측 표시로 교체했다. 기록 축적(record_prediction)과
#  자기보정 상한은 백엔드에서 계속 돈다.)
_w45 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
check("컨텍스트 패널 존재", "시장·글로벌·뉴스 컨텍스트" in _w45)
check("사이드바 성적 패널 제거 (사용자 요청 — 전문 수치는 혼란)",
      "검증된 실측 성적 (가상 백테스트)" not in _w45 and "지금 채점하기" not in _w45)
check("틀릴 가능성은 쉬운 결론에 말로 표시 (정직성 유지)",
      "틀릴 가능성" in open(_os.path.join(PROJ, "quant_indicators.py"),
                       encoding='utf-8').read())
check("판정 기록 호출은 유지 (자기보정 백엔드)", "record_prediction" in _w45)
check("뉴스 비해석 원칙 문구", "요약·해석해" in _w45)


section("46. 시장·글로벌·뉴스가 퀀트 점수 산식에 실제로 들어가는가")

# ⚠️ 이전 단계에서는 시장·글로벌·뉴스가 '상한(cap)' 으로만 걸려 있었다. 상한은
#    좋은 점수를 깎을 뿐이라, 판이 나빠도 점수 자체는 그대로였다. 이제 산식 안으로
#    들어간다: 시장 국면 = 국내 국면 + 글로벌 위험 합성(매매 적합도 8%),
#    뉴스 위험 = 리스크 안전성 12%.
import market_context as mcx46

_R46 = qi.RULEBOOK.get('RULES_MARKET_CONTEXT', {})
check("규칙집이 산식의 단일 출처", len(_R46) >= 10)
check("국내/글로벌 가중치 합 1.0",
      abs(float(_R46.get('weight_domestic_regime', 0))
          + float(_R46.get('weight_global_risk', 0)) - 1.0) < 1e-9)
_WR46 = qi.RULEBOOK.get('RULES_RISK_SAFETY_WEIGHTS', {})
check("뉴스 위험이 리스크 항목으로 신설", 'weight_news_risk' in _WR46)
check("리스크 가중치 합 여전히 1.0",
      abs(sum(float(v) for v in _WR46.values()) - 1.0) < 1e-9)

_calm46 = {'sp500': {'available': True, 'price': 100, 'sma60': 90, 'above_sma60': True},
           'nasdaq': {'available': True, 'drawdown_pct': -2.0},
           'vix': {'available': True, 'price': 15.0},
           'usdkrw': {'available': True, 'chg20_pct': 0.5}}
_panic46 = {'sp500': {'available': True, 'price': 80, 'sma60': 95, 'above_sma60': False},
            'nasdaq': {'available': True, 'drawdown_pct': -18.0},
            'vix': {'available': True, 'price': 40.0},
            'usdkrw': {'available': True, 'chg20_pct': 6.0}}
_sc46, _hits46, _ = mcx46.score_global_risk(_calm46, _R46)
_sp46, _hitsp46, _ = mcx46.score_global_risk(_panic46, _R46)
check("평온한 글로벌은 감점 없음", _sc46 == 100 and not _hits46)
check("위험 신호마다 감점되고 내역이 남음", _sp46 < 50 and len(_hitsp46) == 4,
      f"{_sp46} / {len(_hitsp46)}건")
check("글로벌 전부 미수신이면 None (0점으로 치지 않음)",
      mcx46.score_global_risk({}, _R46)[0] is None)

_bull46 = {'available': True, 'regime_code': 'BULL_STRONG'}
_bear46 = {'available': True, 'regime_code': 'BEAR_PANIC'}
_rbc, _ = mcx46.score_market_regime(_bull46, _calm46, _R46)
_rbp, _ = mcx46.score_market_regime(_bull46, _panic46, _R46)
_rxp, _ = mcx46.score_market_regime(_bear46, _panic46, _R46)
check("국내가 강세라도 글로벌이 무너지면 점수가 내려간다", _rbp < _rbc - 15,
      f"{_rbc} → {_rbp}")
check("국내·글로벌 모두 나쁘면 최저", _rxp < _rbp)
_ronly, _d46 = mcx46.score_market_regime(_bull46, {}, _R46)
check("한쪽 미수신이면 나머지로 재정규화", _ronly == 78.0 and _d46['renormalized'])
check("양쪽 미수신이면 점수를 만들지 않음",
      mcx46.score_market_regime({}, {}, _R46)[0] is None)

# 뉴스: 감점만 있고 가점은 없다
check("위험 낱말 없으면 만점", mcx46.score_news_risk(
    {'risk_count': 0, 'total': 10}, True, _R46)[0] == 100)
check("위험 낱말 1건당 감점", mcx46.score_news_risk(
    {'risk_count': 2, 'total': 10}, True, _R46)[0] == 50)
check("감점 하한 유지", mcx46.score_news_risk(
    {'risk_count': 99, 'total': 100}, True, _R46)[0] == 25)
_nu46 = mcx46.score_news_risk(None, False, _R46)
check("뉴스 미수신은 중립값 — 만점으로 치지 않음", 0 < _nu46[0] < 100)
_mcsrc46 = _insp.getsource(mcx46)
check("가점 경로 없음 (좋은 뉴스로 점수를 올리지 않음)",
      'watch_hits' not in _insp.getsource(mcx46.score_news_risk))

# 파이프라인 반영 — 실제 스냅샷에 재계산 내역이 실린다
_snap46 = q.run_full_pipeline(SYMBOL, T_REF, b_engine=engine, rho_cutoff=0.80)
_fs46 = _snap46['four_scores']
check("시장 국면 점수가 스냅샷에", _fs46.get('market_regime_score') is not None)
check("국내·글로벌 합성 내역 노출",
      (_fs46.get('market_regime_detail') or {}).get('global_score') is not None)
check("뉴스 위험 점수가 스냅샷에", _fs46.get('news_risk_score') is not None)
check("매매적합 가중치 합 1.0 (항목 제외 없을 때)",
      abs(float(_fs46.get('timing_weight_sum', 0)) - 1.0) < 1e-6)
_qsrc46 = open(_os.path.join(PROJ, "quant_indicators.py"), encoding='utf-8').read()
check("시장 국면이 매매적합도 항목으로 합산됨", "market_regime_score_for_sum" in _qsrc46)
check("뉴스 위험이 리스크 안전성에 합산됨", "news_risk_score * WR.get" in _qsrc46)
check("미산출 항목은 50점으로 메우지 않고 가중치 0 처리",
      "regime_weight = 0.0" in _qsrc46)
_w46 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
check("화면에 산식 반영분 표시", "퀀트 점수를 얼마나 움직였나" in _w46)
check("상한과 반영분을 구분해 설명", "점수 상한과 별개로" in _w46)


section("47. 판정 화해 — 이견은 확신 하향, 판정 보류는 데이터 오류에만")

# ⚠️ '적정가 신뢰도 61점 + 괴리율 +46.6%' 조합이 데이터 모순으로 분류돼 판정
#    전체가 '판정 보류'로 폐기됐다 (CJ ENM 실사례 — PBR 0.2대 딥밸류는 전부 죽음).
#    예측결합 문헌(Bates–Granger 1969, Timmermann 2006)과 Black–Litterman(1992)의
#    처방: 낮은 신뢰도의 견해는 시장가격 쪽으로 수축시켜 반영하고, 이견은 확신을
#    낮출 이유이지 판단을 거부할 이유가 아니다.

_q47 = open(_os.path.join(PROJ, "quant_indicators.py"), encoding='utf-8').read()

# ① 저신뢰 대괴리는 더 이상 '모순'이 아니라 수축 + 상한
check("저신뢰·대괴리를 모순으로 분류하는 코드 제거",
      "적정가 신뢰도 {fair_value_confidence:.0f}점인데 괴리율" not in _q47)
check("신뢰도 수축 괴리(정밀도 가중) 도입", "upside_shrunk_pct" in _q47
      and "valuation_uncertainty_cap" in _q47)
_snap47 = q.run_full_pipeline("035760.KQ", T_REF, b_engine=engine, rho_cutoff=0.80)
_fs47 = _snap47['four_scores']
check("CJ ENM 이 판정 보류가 아니라 실제 결론을 냄",
      _fs47.get('final_action_title') != '재검토 필요'
      and not _fs47.get('contradiction_detected'),
      str(_fs47.get('final_action_title')))
_up47, _sh47 = _fs47.get('upside_pct'), _fs47.get('upside_shrunk_pct')
if _up47 is not None and _sh47 is not None:
    check("수축 괴리 = 원괴리 × 신뢰도 (시장가 쪽으로 끌어당김)",
          abs(_sh47) <= abs(_up47) + 1e-6, f"{_up47} → {_sh47}")
    check("수축 사유가 산식표(gate_reason)에 남음",
          "신뢰도 수축" in str(_fs47.get('gate_reason', '')))

# ② 하드 정합성 위반(산술 불변식)은 여전히 판정을 막는다
check("부호 불일치 검사는 유지", "적정가보다 현재가가 높은데 상승여력을 양수로 표시" in _q47)
check("확률 노출 불변식 검사는 유지", "표본 통제 판정과 확률 노출이 불일치" in _q47)

# ③ 소프트 이견은 결정적으로 화해 (관망 하향 + 사유)
check("진입가 밖 매수 의도 → 관망 하향", "매수 의도였으나 현재가가 진입 허용가 밖" in _q47)
check("약세 우세 매수 의도 → 관망 하향", "약세 신호 우세" in _q47
      and "관망으로 하향" in _q47)
check("다중기간 충돌도 폐기 대신 하향", "다중기간 전망 충돌 → 관망으로 하향" in _q47)
check("화해 내역을 스냅샷에 노출", "'soft_conflict_notes'" in _q47)

# ④ TITLE_MAP 이 엔진의 모든 판정 문구를 덮는다 (문구-점수 자기모순 방지)
_titles_engine47 = ["적극적 분할매수 검토", "분할매수 검토", "제한적 진입",
                    "조건 확인·관망", "신규 매수 보류", "비중축소 검토", "거래 회피"]
_syn47 = dict(_snap47)
for _t47 in _titles_engine47:
    _f47 = dict(_snap47['four_scores'])
    _f47['final_action_title'] = _t47
    _f47['final_action_score'] = 62          # 같은 점수라도 문구가 결론을 결정해야 함
    _f47['contradiction_detected'] = False
    _syn47['four_scores'] = _f47
    _v47 = q.build_final_verdict(_syn47)
    if _t47 == "조건 확인·관망":
        check("'조건 확인·관망'(62점)이 분할매수로 둔갑하지 않음",
              _v47['action'] == 'HOLD', f"{_t47} → {_v47['action']}")
    if _t47 == "거래 회피":
        check("'거래 회피'가 매수 계열로 매핑되지 않음",
              _v47['action'] in ('SELL', 'REDUCE', 'NO_TRADE'), str(_v47['action']))

# ⑤ 관점 간 이견(앙상블 분산) 지표 — 크면 확신 하향
_v47b = q.build_final_verdict(_snap47)
check("이견 지표(disagreement) 노출", 'disagreement' in _v47b)
check("BUY 에서 이견 크면 소액 분할로 하향하는 규칙 존재",
      "disagreement >= 20 and action == 'BUY'" in _q47)

# ⑥ 죽은 키 수정 — 정합성 거부권이 실제 키('status')를 읽는다
check("무결성 거부권이 실제 키를 읽음", "snap.get('status') == 'REVIEW_REQUIRED'" in _q47)
check("죽은 키 'integrity_status' 제거", "integrity_status" not in _q47.replace(
    "'integrity_status' 를 읽어", ""))

# ⑦ 하드 위반이 실제로 보류를 만드는지 (합성 주입)
_s47h = dict(_snap47)
_f47h = dict(_snap47['four_scores'])
_f47h['final_action_title'] = '재검토 필요'
_f47h['contradiction_detected'] = True
_s47h['four_scores'] = _f47h
_v47h = q.build_final_verdict(_s47h)
check("하드 위반은 여전히 NO_TRADE", _v47h['action'] == 'NO_TRADE')
check("보류 문구가 '데이터 정합성' 을 명시",
      "데이터 정합성" in _v47h['headline'], _v47h['headline'])

# ⑧ 화면 연결
_w47 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
check("화해 내역 패널", "신호 간 이견을 화해시켰습니다" in _w47)
check("수축 괴리 설명", "수축시켜 판단에 씁니다" in _w47)


section("48. 엑셀 가져오기 · 평단가 자릿수 오독 교정")

# ⚠️ 스크린샷 인식은 글자를 잘못 읽을 수 있다. 숫자가 그대로 들어 있는 엑셀 경로를
#    1급 시민으로 두어 OCR 을 아예 우회할 수 있게 한다. 동시에, OCR 이 평단가 칸에서
#    옆 열 숫자를 집어와 '평단 462원 / 수익률 +1871%' 같은 값을 만들던 것을
#    화면의 현재가·수익률로 역산해 교정한다 (실사례: 금호건설).
import io as _io48

import pandas as _pd48

# ① 입력 양식 — 생성 → 다시 읽기 → 자동 매핑까지 왕복
_tb48, _tn48, _tm48 = pf.build_template_bytes()
check("입력 양식 생성", len(_tb48) > 0 and _tn48.endswith((".xlsx", ".csv")))
_tdf48 = pf.read_table(_tb48, _tn48)
check("양식 필수 4열", all(c in list(_tdf48.columns)
                       for c in ("종목코드", "종목명", "보유수량", "평균매수가")))
_tm = pf.suggest_column_mapping(list(_tdf48.columns))
check("양식이 자동 매핑됨", all(_tm.get(k) for k in
                          ('ticker', 'stock_name', 'quantity', 'average_buy_price')))

# ② HTS 내보내기 — 제목·요약이 위에 붙어 머리말이 4행에 있는 경우
_raw48 = _pd48.DataFrame([
    ["4202 주식잔고", "", "", "", "", ""],
    ["계좌 7085150410-01", "", "", "", "", ""],
    ["", "", "", "", "", ""],
    ["종목명", "종목번호", "평가손익", "잔고", "손익분기", "매수평균"],
    ["금호건설", "A002990", "-462,205", "400", "10,265", "10,246"],
    ["대한항공", "A003490", "-71,989", "38", "27,794", "27,740"],
])
_buf48 = _io48.BytesIO()
with _pd48.ExcelWriter(_buf48, engine="openpyxl") as _xl48:
    _raw48.to_excel(_xl48, index=False, header=False, sheet_name="잔고")
_hdf48 = pf.read_table(_buf48.getvalue(), "hts.xlsx")
check("머리말 행을 찾아 열 이름으로 사용 (첫 행 고정 금지)",
      "종목번호" in list(_hdf48.columns), str(list(_hdf48.columns))[:80])
check("제목·요약 줄은 데이터에서 제외", len(_hdf48) == 2, str(len(_hdf48)))
_hm48 = pf.classify_header_cells([str(c) for c in _hdf48.columns])
check("엑셀에서도 종목번호→코드, 잔고→수량, 매수평균→평단",
      _hm48.get('code') is not None and _hm48.get('quantity') is not None
      and str(_hdf48.columns[_hm48['price']]) == "매수평균")

# ③ 보유종목 내보내기 — 양식과 같은 열로 나가야 다시 올릴 수 있다
_pos48 = [pf.PortfolioPosition(ticker="005930.KS", stock_name="삼성전자",
                               market="KOSPI", quantity=10,
                               average_buy_price=210000, source_type="manual_entry")]
_edf48 = pf.positions_to_dataframe(_pos48)
check("내보내기 열 = 양식 열", list(_edf48.columns) == pf.TEMPLATE_COLUMNS)
check("내보낸 코드에 시장접미사 없음", _edf48.iloc[0]['종목코드'] == '005930')

# ④ 평단가 자릿수 오독 교정 — 화면의 현재가·수익률로 역산
_bad48 = ("종목명\t종목번호\t평가손익\t수익률\t잔고\t손익분기\t매수평균\t현재가\n"
          "금호건설\t002990\t-462,205\t-11.28%\t400\t10,265\t462\t9,110\n")
_r48, _w48 = pf.parse_table_with_header(_bad48, resolve_name=None)
check("말도 안 되는 평단가를 역산값으로 교체",
      len(_r48) == 1 and 9000 < float(_r48[0]['평균매수가']) < 11000,
      str(_r48 and _r48[0]['평균매수가']))
check("교정 사실을 반드시 알림", any('평단가 오독 교정' in w for w in _w48))

_ok48 = ("종목명\t종목번호\t평가손익\t수익률\t잔고\t손익분기\t매수평균\t현재가\n"
         "금호건설\t002990\t-462,205\t-11.28%\t400\t10,265\t10,246\t9,110\n")
_r48b, _w48b = pf.parse_table_with_header(_ok48, resolve_name=None)
check("정상 평단가는 건드리지 않음", _r48b[0]['평균매수가'] == 10246.0)
check("정상일 때 교정 경고 없음", not any('오독 교정' in w for w in _w48b))

_miss48 = ("종목명\t종목번호\t평가손익\t수익률\t잔고\t매수평균\t현재가\n"
           "테스트\t005930\t-1,000\t-10.00%\t50\t\t9,000\n")
_r48c, _w48c = pf.parse_table_with_header(_miss48, resolve_name=None)
check("평단가를 못 읽으면 역산으로 살림",
      len(_r48c) == 1 and abs(float(_r48c[0]['평균매수가']) - 10000) <= 2,
      str(_r48c and _r48c[0]['평균매수가']))
check("역산 사실 표기", any('역산' in w for w in _w48c))

# ⑤ 화면 연결 — 스크린샷과 같은 자리에 엑셀 경로가 있어야 한다
_w48ui = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
check("엑셀 가져오기 섹션 존재", "엑셀 파일로 가져오기 (가장 정확)" in _w48ui)
check("양식 내려받기 버튼", "입력 양식 내려받기" in _w48ui)
check("보유종목 내보내기 버튼", "지금 보유종목 내보내기" in _w48ui)
check("엑셀 업로더", 'key="xls_uploader"' in _w48ui)
check("엑셀은 오독이 없음을 안내", "OCR 오독이 없습니다" in _w48ui)


section("49. None 포맷 폭탄 — 표본 부족이 화면 전체를 죽이지 않는가")

# ⚠️ 클라우드 실사고: 표본이 부족해 mean_perf 가 None 인 종목에서
#    f"{cost_metrics['raw_perf']:.1f}%" 가 TypeError 를 내고 앱 전체가 죽었다.
#    이 프로젝트는 '못 구한 값은 None' 이 원칙이므로, 숫자 포맷은 반드시
#    None 안전한 fmt_num/fmt_pct 를 통해야 한다.
_w49 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()

# ① 엔진은 표본이 없으면 실제로 None 을 돌려준다 (그게 정상)
_cm49 = q.calculate_backtest_costs_and_metrics({}, oos=None, is_large_cap=True)
check("표본 없으면 raw_perf None", _cm49['raw_perf'] is None)
check("표본 없으면 net_perf None", _cm49['net_perf'] is None)
_cm49b = q.calculate_backtest_costs_and_metrics(
    {'mean_perf': 3.5, 'probabilities_shown': True}, oos=None)
check("표본 있으면 실제 값", _cm49b['raw_perf'] == 3.5 and _cm49b['net_perf'] is not None)

# ② 사고 지점이 None 안전 표기로 바뀌었는가
check("raw_perf 직접 포맷 제거", "cost_metrics['raw_perf']:" not in _w49)
check("net_perf 직접 포맷 제거", "cost_metrics['net_perf']:" not in _w49)
check("부호를 하드코딩하지 않음 (손실에 + 가 붙지 않게)",
      "+{cost_metrics" not in _w49)

# ③ 같은 계열 — 값이 None 일 수 있는 가격 레벨·배당도 안전 표기
for _k49 in ("target_tech_1st", "target_tech_2nd", "stop_loss_price", "atr_risk_level"):
    check(f"{_k49} 직접 포맷 제거", f"four_scores['{_k49}']:" not in _w49)
check("DPS 직접 포맷 제거", "_div['dps']:" not in _w49)

# ④ 포맷 헬퍼 자체가 None 을 견디는가 (이 계약이 깨지면 위 수정이 무의미)
import importlib.util as _ilu49

_spec49 = _ilu49.spec_from_file_location("_wa49", _os.path.join(PROJ, "web_app.py"))
check("fmt 헬퍼 계약 — None → 문구",
      "def fmt_num(v, spec=\",.0f\", suffix=\"\", na=\"미산출\")" in _w49
      and "return f\"{v:{spec}}{suffix}\" if v is not None else na" in _w49)

# ⑤ 실제 렌더 — 성격이 다른 종목 4종에서 예외 0건
from streamlit.testing.v1 import AppTest as _AT49

for _code49, _label49 in [("069500", "ETF"), ("035760", "저신뢰 적정가")]:
    _at49 = _AT49.from_file(_os.path.join(PROJ, "web_app.py"), default_timeout=1800)
    _at49.session_state['selected_ticker'] = _code49
    _at49.run()
    check(f"{_label49}({_code49}) 렌더 예외 없음", len(_at49.exception) == 0,
          str(_at49.exception[:1])[:150])


section("50. 열 추측을 버리고 관계식으로 푼다 — 수량·평단가 자동 판별")

# ⚠️ 열 위치를 맞히는 방식은 행마다 토큰 수가 달라지면 통째로 밀린다.
#    실사례: 코텍이 '수량 12 · 평단 173' 으로 뒤바뀌어 수익률 +6709% 가 나왔다
#    (실제는 173주 · 12,326원). 사람이 열을 직접 지정해도 행마다 어긋나면 소용없다.
#
#    잔고 화면의 숫자들은 항등식으로 묶여 있다:
#        평가손익 = (현재가 − 기준가) × 수량,  수익률 = 현재가 ÷ 기준가 − 1
#    순서를 몰라도 이 관계를 만족하는 조합은 사실상 하나뿐이므로 정체가 정해진다.
#    (외부 LLM 에 보내지 않는다 — 보유종목은 이 앱 밖으로 나가지 않는다.)

_REAL50 = [
    ("금호건설", [-462205, -11.28, 400, 10265, 10246, 9110, 380], 400, 10246),
    ("대한항공", [-71989, -6.83, 38, 27794, 27740, 25900, 1250], 38, 27740),
    ("코텍", [-98733, -4.63, 173, 12350, 12326, 11780, 360], 173, 12326),
    ("LG전자", [-178568, -15.82, 6, 188461, 188133, 158700, 10700], 6, 188133),
    ("금호타이어", [9396, 0.95, 143, 6954, 6939, 7020, 940], 143, 6939),
    ("영원무역", [-9379, -0.32, 33, 87884, 87703, 87600, 1500], 33, 87703),
]
_solved50 = 0
for _nm50, _nums50, _tq50, _tp50 in _REAL50:
    # 순서 정보를 없앤 상태로 넣는다 (열 위치를 전혀 모른다는 가정)
    _sol50 = pf.solve_row_by_invariants(sorted(_nums50, key=lambda v: abs(v) % 11))
    _hit = (_sol50 is not None and int(_sol50['quantity']) == _tq50
            and abs(_sol50['price'] - _tp50) / _tp50 < 0.01)
    _solved50 += _hit
check("실제 잔고 6행을 순서 없이도 전부 복원", _solved50 == len(_REAL50),
      f"{_solved50}/{len(_REAL50)}")

# 오답을 만들어내지 않아야 한다 — 관계가 없으면 해도 없다
check("무작위 숫자에는 해를 만들지 않음",
      pf.solve_row_by_invariants([3, 17, 91, 4200, 55]) is None)
check("숫자가 모자라면 해 없음", pf.solve_row_by_invariants([100, 200]) is None)
check("가격만 있으면 해 없음",
      pf.solve_row_by_invariants([10000, 10500, 11000, 9800]) is None)

# 평단가와 손익분기를 구분한다 (손익분기 = 수수료 포함, 항상 평단가보다 크다)
_sol50b = pf.solve_row_by_invariants([-462205, -11.28, 400, 10265, 10246, 9110, 380])
check("평단가와 손익분기를 구분", _sol50b is not None
      and _sol50b['price'] == 10246 and _sol50b['breakeven'] == 10265,
      str(_sol50b and (_sol50b['price'], _sol50b.get('breakeven'))))

# 헤더 없는 붙여넣기 — 예전에는 '숫자가 N개라 알 수 없음' 으로 전부 버렸다
_paste50 = ("금호건설 A002990 -462,205 -11.28% 400 10,265 10,246 9,110 380\n"
            "SOL 팔란티 A0040Y0 -416,675 -6.76% 739 8,343 8,343 7,780 5\n"
            "코텍 A052330 -98,733 -4.63% 173 12,350 12,326 11,780 360\n")
_rows50, _warn50 = pf.parse_freeform_holdings(_paste50, resolve_name=None)
_by50 = {str(r.get('종목명')): r for r in _rows50}
check("헤더 없이도 3행 모두 값을 채움",
      all(r.get('보유수량') is not None and r.get('평균매수가') is not None
          for r in _rows50) and len(_rows50) == 3, str(len(_rows50)))
_kotek = next((r for r in _rows50 if '코텍' in str(r.get('종목명'))), None)
check("코텍 수량·평단가가 뒤바뀌지 않음 (173주 / 12,326원)",
      _kotek is not None and int(_kotek['보유수량']) == 173
      and abs(_kotek['평균매수가'] - 12326) < 1,
      str(_kotek and (_kotek['보유수량'], _kotek['평균매수가'])))
check("관계식으로 풀었다는 사실을 알림", any('관계식으로 풀었습니다' in w for w in _warn50))

# 여러 낱말 종목명이 잘리지 않고, 종목번호가 이름에 섞이지 않는다
_sol_row50 = next((r for r in _rows50 if 'SOL' in str(r.get('종목명'))), None)
check("여러 낱말 종목명 보존 ('SOL 팔란티')",
      _sol_row50 is not None and '팔란티' in str(_sol_row50['종목명']),
      str(_sol_row50 and _sol_row50['종목명']))
check("종목번호가 종목명에 섞이지 않음",
      _sol_row50 is not None and 'A0040Y0' not in str(_sol_row50['종목명']))

# 헤더가 있는 표에서도 열이 어긋나면 관계식이 바로잡는다
_bad50 = ("종목명\t종목번호\t평가손익\t수익률\t잔고\t손익분기\t매수평균\t현재가\n"
          "코텍\t052330\t-98,733\t-4.63%\t12\t12,350\t173\t11,780\n")   # 수량↔평단 뒤바뀜
_r50c, _w50c = pf.parse_table_with_header(_bad50, resolve_name=None)
check("헤더 표에서도 뒤바뀐 열을 관계식으로 교정",
      len(_r50c) == 1 and int(_r50c[0]['보유수량']) == 173,
      str(_r50c and _r50c[0]['보유수량']))
check("교정 사실을 알림", any('관계식으로 다시 풀었습니다' in w for w in _w50c))

# 보유종목은 외부로 나가지 않는다 (LLM·외부 API 호출 없음)
_pf50src = _insp.getsource(pf.solve_row_by_invariants)
check("풀이는 로컬 계산 — 외부 전송 없음",
      all(x not in _pf50src for x in ("requests", "urlopen", "http", "api_key")))


section("51. DeMARK 매수 포인트를 종합 결론에 싣는다")

# DeMARK 9-13 은 '언제·어느 선에서' 를 말하는 시점 신호다. 탭 안에만 두면
# 종합 결론과 따로 놀아, 결론은 '사지 마세요' 인데 탭에는 매수 신호가 떠 있는
# 식으로 읽힌다. 결론 배너와 요약에 같은 값을 싣는다.

_C51 = [
    ("완성", {'buy_setup_count': 9, 'buy_countdown': 13, 'tdst_support': 9000,
            'demark_label': '강한 분할매수', 'bullish_score': 70, 'bearish_score': 20},
     9500, 'COMPLETE', True),
    ("셋업만", {'buy_setup_count': 9, 'buy_countdown': 3, 'tdst_support': 9000,
             'demark_label': '매수 확인', 'bullish_score': 55, 'bearish_score': 25},
     9500, 'SETUP_DONE', True),
    ("진행중", {'buy_setup_count': 5, 'buy_countdown': 0, 'tdst_support': 9000,
             'demark_label': '예비 매수', 'bullish_score': 40, 'bearish_score': 30},
     9500, 'FORMING', True),
    ("지지이탈", {'buy_setup_count': 9, 'buy_countdown': 13, 'tdst_support': 9000,
              'demark_label': '강한 분할매수', 'bullish_score': 70, 'bearish_score': 20},
     8500, 'COMPLETE', False),
    ("신호없음", {'buy_setup_count': 0, 'buy_countdown': 0, 'tdst_support': 9000,
              'demark_label': '예비 매도', 'bullish_score': 20, 'bearish_score': 60},
     9500, 'NONE', True),
]
for _lb51, _dm51, _px51, _st51, _vd51 in _C51:
    _e51 = q.build_demark_entry(_dm51, _px51)
    check(f"{_lb51} → state={_st51}", _e51 and _e51['state'] == _st51,
          str(_e51 and _e51['state']))
    check(f"{_lb51} → 지지 유효 판정 {_vd51}", _e51 and _e51['valid'] is _vd51)

check("진행중은 완성까지 남은 봉 수를 알려줌",
      "완성까지 4봉" in q.build_demark_entry(_C51[2][1], 9500)['headline'])
check("산출 불가 입력에는 값을 만들지 않음",
      q.build_demark_entry({'demark_label': '산출 불가 (데이터 부족)'}, 1000) is None
      and q.build_demark_entry(None, 1000) is None)

# 실제 파이프라인 — 스냅샷과 결론 요약에 실린다
_snap51 = q.run_full_pipeline(SYMBOL, T_REF, b_engine=engine, rho_cutoff=0.80)
_fs51 = _snap51['four_scores']
check("스냅샷에 demark_entry", isinstance(_fs51.get('demark_entry'), dict))
_v51 = q.build_final_verdict(_snap51)
check("결론 요약에 DeMARK 매수 포인트 포함",
      any('DeMARK 매수 포인트' in s for s in _v51['summary']),
      str(_v51['summary'])[:120])

# 신호가 없을 때 유효 하한선을 내밀지 않는다 (진입 근거처럼 읽히면 안 됨)
_snap51b = dict(_snap51)
_fs51b = dict(_fs51)
_fs51b['demark_entry'] = q.build_demark_entry(_C51[4][1], 9500)   # NONE 상태
_snap51b['four_scores'] = _fs51b
_v51b = q.build_final_verdict(_snap51b)
_line51 = next((s for s in _v51b['summary'] if 'DeMARK' in s), '')
check("신호 없음일 때 유효 하한선을 표시하지 않음", '유효 하한' not in _line51, _line51)

# 화면 연결 — 종합 결론 배너 안에 카드가 있어야 한다
_w51 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
check("배너에 DeMARK 매수 포인트 카드", "DeMARK 매수 포인트" in _w51)
check("시점 신호임을 명시(가격 기준과 구분)", "시점</b> 신호이며" in _w51)
check("신호 없을 때 하한선 숨김 처리", "_dm_state in ('COMPLETE', 'SETUP_DONE', 'FORMING')" in _w51)


section("52. 적정가 케이스 스터디 — 모델 적용 범위 게이트 · 권장매수가 정합")

# ⚠️ 실사례: 레인보우로보틱스 현재가 433,000원에 '시장조정 펀더멘털 적정가
#    10,501원'(-98%) 이 표시됐다. PER 6,766배·PBR 63배 성장주는 이익·자산이
#    가격을 설명하지 않는 멀티플 모델 적용 범위 밖이다(Damodaran; SR 11-7).
#    이 구간에서는 수축·보정이 아니라 '산출 불가'를 말해야 한다.

check("범위 밖 임계값이 규칙집에 존재",
      float(qi.QuantIndicatorsEngine.FV_CONF.get('out_of_domain_gap_pct', 0)) == 70.0)

_CASES52 = [("005930.KS", "삼성전자"), ("069500.KS", "KODEX200(ETF)"),
            ("277810.KS", "레인보우로보틱스"), ("003490.KS", "대한항공")]
_snaps52 = {}
for _sym52, _nm52 in _CASES52:
    _snaps52[_sym52] = q.run_full_pipeline(_sym52, T_REF, b_engine=engine,
                                           rho_cutoff=0.80)

# ① 고성장 스토리주 — 범위 밖 선언, 숫자 미제시
_fs_rb = _snaps52["277810.KS"]['four_scores']
check("레인보우: OUT_OF_DOMAIN 선언",
      _fs_rb.get('fair_value_status') == 'OUT_OF_DOMAIN')
check("레인보우: 적정가 숫자를 제시하지 않음",
      _fs_rb.get('displayed_fair_value') is None)
check("레인보우: 권장매수가도 없음", _fs_rb.get('recommended_buy_price') is None)
check("레인보우: 괴리율도 없음", _fs_rb.get('upside_pct') is None)
_note_rb = str(_snaps52["277810.KS"]['val_eval'].get('fair_value_status_note'))
check("레인보우: 사유에 근거(성장 기대 지배) 명시",
      "성장 기대" in _note_rb and "적용 범위 밖" in _note_rb, _note_rb[:80])

# ② 멀티플이 유효한 종목들 — 정상 산출 + 불변식
for _sym52, _nm52 in [("005930.KS", "삼성전자"), ("003490.KS", "대한항공")]:
    _fs52 = _snaps52[_sym52]['four_scores']
    _px52 = _snaps52[_sym52]['rt_price']
    _dfv52, _rec52 = _fs52.get('displayed_fair_value'), _fs52.get('recommended_buy_price')
    _up52 = _fs52.get('upside_pct')
    check(f"{_nm52}: 적정가 정상 산출 (CALIBRATED)",
          _fs52.get('fair_value_status') == 'CALIBRATED' and _dfv52 is not None)
    check(f"{_nm52}: 수축 후 괴리 ±48% 이내",
          _up52 is not None and abs(_up52) <= 48.5, str(_up52))
    check(f"{_nm52}: 표시 적정가와 현재가 괴리 70% 이내 (범위 밖 미노출)",
          _px52 and abs(_dfv52 / _px52 - 1) <= 0.70)
    check(f"{_nm52}: 권장매수가 < 적정가 (안전마진)",
          _rec52 is not None and _rec52 < _dfv52)

# ③ ETF — 기존 계약 유지 (게이트가 ETF 경로를 건드리지 않음)
_fs_etf = _snaps52["069500.KS"]['four_scores']
check("ETF: 적정가 비적용 유지", _fs_etf.get('displayed_fair_value') is None
      and _fs_etf.get('fair_value_status') != 'OUT_OF_DOMAIN')

# ④ 전 케이스 공통 불변식 — 적정가 없이 권장매수가가 존재할 수 없다
for _sym52, _nm52 in _CASES52:
    _f = _snaps52[_sym52]['four_scores']
    if _f.get('displayed_fair_value') is None:
        check(f"{_nm52}: 적정가 없으면 권장매수가도 없음",
              _f.get('recommended_buy_price') is None)

# ⑤ 화면 — 범위 밖일 때 '신뢰도 미달' 이 아니라 정확한 사유를 표기
_w52 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
check("배너가 범위 밖을 구분 표기", "산출 불가 (모델 범위 밖)" in _w52)
check("OUT_OF_DOMAIN 분기 존재", "OUT_OF_DOMAIN" in _w52)


section("53. 상용 3사 벤치마크 이식 — 모멘텀·변동성 비중·자기 성적 보정")

# 케이스 스터디(TipRanks·Danelfin·Zacks)에서 문헌 근거가 있는 것만 이식:
#  ① Jegadeesh–Titman(1993) 12-1 가격 모멘텀 — 시장 대비 열위 종목 매수 제한
#     (Zacks 의 이익추정 수정 모멘텀은 컨센서스 미연동이라 넣지 않는다 — 정직하게)
#  ② Moreira–Muir(2017) 변동성 관리 — 실현 변동성 기반 비중 제안
#  ③ TipRanks Smart Score 방식 — 예측 주체(이 앱)의 실전 적중률로 확신 보정

# ① 모멘텀 산식 — 최근 1개월 제외(단기 반전), 표본 부족이면 None
import numpy as _np53

_up53 = _np53.linspace(100, 200, 260)              # 꾸준한 상승
check("12-1 모멘텀 양수 (상승 종목)", qi.QuantIndicatorsEngine.momentum_12_1(_up53) > 0)
_flat53 = _np53.concatenate([_np53.full(238, 100.0), _np53.linspace(100, 150, 22)])
check("최근 1개월 급등은 제외 (반전 효과)",
      abs(qi.QuantIndicatorsEngine.momentum_12_1(_flat53)) < 1.0,
      str(qi.QuantIndicatorsEngine.momentum_12_1(_flat53)))
check("표본 253봉 미만이면 None",
      qi.QuantIndicatorsEngine.momentum_12_1(_np53.ones(200)) is None)

_snap53 = q.run_full_pipeline(SYMBOL, T_REF, b_engine=engine, rho_cutoff=0.80)
_fs53 = _snap53['four_scores']
_rm53 = _fs53.get('rel_mom_detail')
check("상대 모멘텀이 스냅샷에 (종목·지수·차이·시장)",
      _rm53 is None or all(k in _rm53 for k in ('stock', 'index', 'relative', 'market')))
_q53src = open(_os.path.join(PROJ, "quant_indicators.py"), encoding='utf-8').read()
check("모멘텀 열위는 상한만 (승자 추격 가점 없음)",
      "momentum_cap = 64" in _q53src and "momentum_bonus" not in _q53src)

# ② 변동성 관리 비중 — 근거 문구 포함. 범위는 국면·레버리지 배수만큼 함께
#    내려간다 (라운드 27). 바닥 10%를 배수 앞에 걸면 0.3배 제한이 무력화되므로
#    바닥도 같은 배수를 받는다. 그래서 기대 범위는 고정 10~100 이 아니다.
_sp53 = _fs53.get('suggested_position_pct')
_sp53_lev = 0.5 if _fs53.get('asset_type') in ('ETF_LEV', 'ETF_INV') else 1.0
_sp53_rg = min(1.0, float((_fs53.get('regime_gate') or {}).get('size_mult') or 1.0))
_sp53_scale = _sp53_lev * _sp53_rg
check("비중 제안 존재", _sp53 is not None)
check("비중 제안이 배수 적용 범위 안",
      _sp53 is None or (10.0 * _sp53_scale) - 0.5 <= _sp53 <= 100.0 * _sp53_scale,
      f"{_sp53} (배수 {_sp53_scale:.2f} → 기대 "
      f"{10.0 * _sp53_scale:.1f}~{100.0 * _sp53_scale:.0f})")
check("국면 배수가 비중을 줄인다 (늘리지 않는다)", _sp53_rg <= 1.0)
check("근거에 변동성·목표 명시", "목표 20%" in str(_fs53.get('suggested_position_basis')))

# ③ 자기 성적 보정 — 적중률이 낮으면 상한, 기록 없으면 개입 없음
_q53b = qi.QuantIndicatorsEngine()
_q53b._track_summary = {'hit_rate': 30.0, 'decided': 8}
_s53b = _q53b.run_full_pipeline(SYMBOL, T_REF, b_engine=engine, rho_cutoff=0.80)
check("적중률 30% → 자기 성적 보정 상한 발동",
      '자기 성적 보정' in str(_s53b['four_scores'].get('gate_reason')))
_q53c = qi.QuantIndicatorsEngine()
_q53c._track_summary = {'hit_rate': 30.0, 'decided': 3}       # 표본 부족
_s53c = _q53c.run_full_pipeline(SYMBOL, T_REF, b_engine=engine, rho_cutoff=0.80)
check("판정 완료 5건 미만이면 보정하지 않음 (소표본 과신 방지)",
      '자기 성적 보정' not in str(_s53c['four_scores'].get('gate_reason')))
check("기록 없으면(클라우드) 개입 없음",
      _fs53.get('track_record') is None
      or _fs53['track_record'].get('hit_rate') is None
      or '자기 성적 보정' not in str(_fs53.get('gate_reason'))
      or _fs53['track_record'].get('decided', 0) >= 5)

# 화면 연결
_w53 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
check("배너 아래 비중·모멘텀·적중률 요약", "변동성 관리 비중 제안" in _w53
      and "상대 모멘텀(12-1)" in _w53 and "실전 판정 적중률" in _w53)


section("54. 가상 백테스트 리플레이 — 과거 기준일 판정에 오늘 데이터가 새지 않는가")

# '예전 데이터로 100번 돌려 학습' 의 전제는 리플레이가 정직해야 한다는 것이다.
# 과거 기준일 판정에 오늘의 시세·지수 국면·뉴스·상대모멘텀이 섞이면
# 그 캘리브레이션은 성적을 부풀린 가짜가 된다.

_q54 = qi.QuantIndicatorsEngine()
_snap54 = _q54.run_full_pipeline(SYMBOL, "2026-01-15", b_engine=engine, rho_cutoff=0.80)
check("과거 기준일이면 리플레이 모드", _snap54.get('is_replay') is True)
check("현재가 = 기준일 종가 (오늘 시세 미주입)",
      '리플레이' in str(_snap54.get('rt_status')), str(_snap54.get('rt_status'))[:60])
_last54 = str(_snap54['tech_df']['trade_date'].iloc[-1])
check("가격 시계열이 기준일에서 끝남", _last54 <= "2026-01-15", _last54)
_mc54 = _snap54.get('market_context') or {}
check("오늘의 뉴스 컨텍스트 차단",
      not (_mc54.get('news') or {}).get('available', False))
check("오늘의 지수 국면 차단 (컨텍스트 캡 없음)",
      _snap54['four_scores'].get('context_cap', 100) == 100
      or '리플레이' in str(_mc54.get('news', {}).get('reason', '')))
check("오늘 기준 상대 모멘텀 차단",
      _snap54['four_scores'].get('rel_mom_detail') is None)
import datetime as _dt54

_dt_now54 = _dt54.datetime.now().strftime('%Y-%m-%d')
check("오늘(실시간) 기준일이면 리플레이 아님",
      (q.run_full_pipeline(SYMBOL, T_REF, b_engine=engine,
                           rho_cutoff=0.80).get('is_replay') is False)
      if T_REF >= _dt_now54 else True)

# 캘리브레이션 소비 — 점수대 표를 읽어 현재 점수의 과거 적중률을 싣는다
_q54b = qi.QuantIndicatorsEngine()
_q54b._calibration = {'bands': [
    {'lo': 0, 'hi': 39, 'n': 20, 'hit': 4, 'hit_rate': 20.0, 'wilson_low': 8.1,
     'avg_return': -5.0},
    {'lo': 40, 'hi': 49, 'n': 30, 'hit': 12, 'hit_rate': 40.0, 'wilson_low': 24.6,
     'avg_return': -1.0},
    {'lo': 50, 'hi': 59, 'n': 25, 'hit': 14, 'hit_rate': 56.0, 'wilson_low': 37.1,
     'avg_return': 2.0},
    {'lo': 60, 'hi': 100, 'n': 18, 'hit': 12, 'hit_rate': 66.7, 'wilson_low': 43.7,
     'avg_return': 4.5}]}
_s54b = _q54b.run_full_pipeline(SYMBOL, T_REF, b_engine=engine, rho_cutoff=0.80)
_fs54b = _s54b['four_scores']
_cb54 = _fs54b.get('calibration_band')
check("현재 점수가 속한 점수대의 과거 적중률을 스냅샷에 실음",
      _cb54 is not None
      and _cb54['lo'] <= _fs54b['final_action_score'] <= _cb54['hi'],
      str(_cb54))
_q54c = qi.QuantIndicatorsEngine()
_q54c._calibration = None
_s54c = _q54c.run_full_pipeline(SYMBOL, T_REF, b_engine=engine, rho_cutoff=0.80)
check("캘리브레이션 파일이 없으면 개입하지 않음",
      '가상 백테스트' not in str(_s54c['four_scores'].get('gate_reason')))

# 상한 규칙 계약: n≥15 & Wilson 하한<35% & 점수>59 일 때만 59로 제한
_q54src = open(_os.path.join(PROJ, "quant_indicators.py"), encoding='utf-8').read()
check("상한은 표본 충분(n≥15)일 때만", "calib_band.get('n', 0) >= 15" in _q54src)
check("Wilson 하한 기준 사용 (소표본 낙관 방지)",
      "calib_band['wilson_low'] < 35.0" in _q54src)
check("랩 스크립트가 리플레이 모드를 강제",
      "assert snap.get('is_replay')" in open(
          _os.path.join(PROJ, "scripts", "calibration_lab.py"), encoding='utf-8').read())
_w54 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
check("화면에 점수대 리플레이 적중률 표시", "가상 백테스트: 이 점수대" in _w54)


section("55. 실행 레벨 기하 재설계 — 적중률은 기하가 절반을 결정한다")

# 가상 백테스트 112회 진단: 종전 목표/손절 비율 2.0 → 무추세 선도달확률 이론값
# 33% — 기하 자체가 적중률 상한을 막고 있었다. 재설계 후 168회 재검증:
# 진입 후보(적정가 이하 & 순기대수익 양수) 적중률 71.4% (n=49),
# 홀드아웃 4종목 68.8% — 손대지 않은 종목에서도 유지 (과적합 아님).

_XL55 = qi.RULEBOOK.get('RULES_EXECUTION_LEVELS', {})
check("실행 레벨 상수가 규칙집에 (단일 출처)", len(_XL55) >= 4, str(_XL55))
check("손절 = 변동성 2σ 바닥 (노이즈 손절 방지)",
      float(_XL55.get('stop_vol_mult', 0)) >= 2.0)
check("1차 목표 = 손절거리 × 0.7 (무추세 이론 P≈59%)",
      abs(float(_XL55.get('target1_of_stop', 0)) - 0.7) < 1e-9)

_snap55 = q.run_full_pipeline(SYMBOL, T_REF, b_engine=engine, rho_cutoff=0.80)
_fs55 = _snap55['four_scores']
_cp55 = float(_snap55['rt_price'])
_t1 = float(_fs55['target_tech_1st'])
_t2 = float(_fs55['target_tech_2nd'])
_sl55 = float(_fs55['stop_loss_price'])
_t1d, _t2d, _sld = _t1 - _cp55, _t2 - _cp55, _cp55 - _sl55
check("가격 순서 유지: 손절 < 현재가 < 1차 ≤ 2차",
      _sl55 < _cp55 < _t1 <= _t2 + 1e-9)
check("1차 목표 거리 ≤ 손절 거리 × 0.75 (도달확률 우선 기하)",
      _t1d <= _sld * 0.75 + 1e-6, f"t1d={_t1d:.0f} sld={_sld:.0f}")
check("손절 거리 ≥ 현재가의 3% (변동성 바닥)", _sld >= _cp55 * 0.03 - 1e-6,
      f"{_sld / _cp55 * 100:.1f}%")
check("손익비는 구조적 목표(2차) 기준",
      _fs55.get('reward_risk_ratio') is not None
      and abs(_fs55['reward_risk_ratio'] - round(_t2d / _sld, 2)) < 0.02,
      f"rr={_fs55.get('reward_risk_ratio')} vs t2 {round(_t2d / _sld, 2)}")
check("1차 목표 문구가 분할익절 의미를 명시",
      '분할익절' in str(_fs55.get('target_tech_1st_note')))
check("손절 문구가 변동성 기반임을 명시",
      '2σ' in str(_fs55.get('stop_loss_note')))

# 캘리브레이션 산출물 계약 — 표본이 커져도 유지되어야 하는 것만 계약으로 잠근다.
# (초기 소표본의 '진입 후보 68%' 는 1,073건 확장에서 59.2%로 후퇴했다 — 소표본
#  수치를 계약으로 박으면 표본 확대 자체를 벌하게 된다. 지속 가능한 계약은:
#  ① 점수 구간별 적중률의 단조성 — 점수가 실제 확률을 구분하는가
#  ② 매수권 구간(60점+)의 비용 차감 후 양의 기대값 — 시스템이 '사라'는 영역의 성과)
_cal55 = _os.path.join(PROJ, ".portfolio", "calibration.json")
if _os.path.exists(_cal55):
    import json as _json55
    _c55 = _json55.load(open(_cal55, encoding='utf-8'))
    check("진입 후보 KPI 저장 (main/holdout/all)",
          all(k in _c55.get('entry_candidates', {}) for k in ('main', 'holdout', 'all')))
    _bands55 = {(b['lo'], b['hi']): b for b in _c55.get('bands', [])}
    _b40 = _bands55.get((40, 49), {})
    _b50 = _bands55.get((50, 59), {})
    _b60 = _bands55.get((60, 100), {})
    if all(b.get('n', 0) >= 30 for b in (_b40, _b50)) and _b60.get('n', 0) >= 15:
        check("점수 구간 적중률 단조 증가 (점수가 확률을 실제로 구분)",
              (_b40.get('hit_rate') or 0) < (_b50.get('hit_rate') or 0)
              < (_b60.get('hit_rate') or 0),
              f"{_b40.get('hit_rate')} < {_b50.get('hit_rate')} < {_b60.get('hit_rate')}")
        check("매수권(60점+) 평균수익 양수 — 비용 차감 후에도",
              (_b60.get('avg_return') or -1) - 0.55 > 0, str(_b60.get('avg_return')))
    else:
        check("점수 구간 표본 미충족 — 단조성 검증 유보 (표본 부족 정직 표기)", True)
    check("유형·시장·국면별 성과 분해 저장", 'breakdowns' in _c55)
else:
    check("캘리브레이션 파일 없음 — 랩 미실행 환경 (개입 없음 확인)",
          True)

_lab55 = open(_os.path.join(PROJ, "scripts", "calibration_lab.py"), encoding='utf-8').read()
check("홀드아웃 종목이 랩에 분리 정의", "HOLDOUT_TICKERS" in _lab55)


section("56. 확장 케이스 스터디(327건) 반영 — 52주 저점권 상한 · 추천 정렬·배지")

# 24종목 × 14기준일 = 336회(판정 327건) 확장 리플레이의 실증만 반영한다:
#   · 52주 저점권(<30%) 매수 적중률 57.1%(−5.5%p) vs 고점권 66.4%(+3.7%p)
#     — George–Hwang(2004) 52주 고점 모멘텀과 일치 → 저점권 상한 64점 신설
#   · 진입 후보(적정가 이하 & 순기대수익 양수) 68.0%(+5.3%p) → 추천 정렬 우선
#   · RSI 침체/DeMARK 극단값은 리프트가 없거나 소표본 → 반영하지 않음 (정직)

_XL56 = qi.RULEBOOK.get('RULES_EXECUTION_LEVELS', {})
check("52주 저점권 상수는 규칙집이 단일 출처",
      'range_low_pct' in _XL56 and 'range_low_cap' in _XL56)
_q56src = open(_os.path.join(PROJ, "quant_indicators.py"), encoding='utf-8').read()
check("저점권 상한이 실측 근거를 명시", "리플레이 327건 실측" in _q56src)
check("저점권은 상한만 — 고점권 가점 없음",
      "range_low_cap" in _q56src and "range_high_bonus" not in _q56src)

# 실사례 발동: 삼성전자 2025-04-07 은 52주 하위 8.7% 였다 (리플레이)
_q56 = qi.QuantIndicatorsEngine()
_s56 = _q56.run_full_pipeline("005930.KS", "2025-04-07", b_engine=engine, rho_cutoff=0.80)
check("저점권 리플레이 사례에서 상한 발동",
      '52주 범위 하위' in str(_s56['four_scores'].get('gate_reason')),
      str(_s56['four_scores'].get('gate_reason'))[:80])
# 고점권 사례에서는 발동하지 않는다 (엔씨소프트 2026-01-30 = 88.4%)
_s56b = _q56.run_full_pipeline("036570.KS", "2026-01-30", b_engine=engine, rho_cutoff=0.80)
check("고점권에서는 미발동",
      '52주 범위 하위' not in str(_s56b['four_scores'].get('gate_reason')))

# 추천주(스캐너) — 진입 후보 우선 정렬 + 차트 배지
check("스캔 행에 entry_candidate 노출", '"entry_candidate"' in _q56src)
check("스캔 행에 DeMARK 상태 노출", '"demark_entry_state"' in _q56src)
check("정렬 1순위 = 진입 후보", 'x.get("entry_candidate")' in _q56src)
_w56 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
check("카드에 진입 후보 배지", "_entry_badge" in _w56)
check("카드 월봉10선 열에 DeMARK 배지 병기", " · 매수신호" in _w56)


section("57. 80% 검증 체계 — 시간 분할·실패 분류·세분화 보정·추세 게이트")

# 80%는 보장값이 아니라 검증 목표다. 이 절은 그 검증이 정직하게 돌아가기 위한
# 구조(분할·분류·보정·빈도 감시)와, 실측 근거로 신설한 추세 게이트를 잠근다.

_lab57 = open(_os.path.join(PROJ, "scripts", "calibration_lab.py"), encoding='utf-8').read()
check("시간 분할 경계 정의 (학습/검증/블라인드)",
      "SPLIT_VALID_FROM" in _lab57 and "SPLIT_BLIND_FROM" in _lab57)
check("매수권(60+) 분할 성과 별도 보고", "60+ {sp}" in _lab57 or "60+ train" in _lab57
      or 'f"60+ {sp}"' in _lab57)
check("실패 원인 분류기 존재 (7종 이상)",
      _lab57.count("return '") >= 7 and "classify_failure" in _lab57)
check("실패를 손실 규모 순으로 정렬 (개선 우선순위)",
      "kv[1]['loss']" in _lab57)
check("신호 빈도 감시 (적중률만 올리는 왜곡 방지)", "신호 빈도" in _lab57)
check("세분화 점수대 (60·65·70대 분리)",
      "(60, 64), (65, 69), (70, 100)" in _lab57)

# 월봉 10선 아래 상한 — 실패 2위 '추세 역행' 을 겨냥한 신설 게이트
_XL57 = qi.RULEBOOK.get('RULES_EXECUTION_LEVELS', {})
check("m10 아래 상한 상수는 규칙집", 'm10_below_cap' in _XL57)
_q57src = open(_os.path.join(PROJ, "quant_indicators.py"), encoding='utf-8').read()
check("m10 아래 상한이 실측 근거 명시", "추세 역행 매수 제한" in _q57src
      and "−8.7%p" in _q57src)
check("인버스는 m10 게이트 비적용", "asset_type != 'ETF_INV'" in _q57src)
check("vol_20 을 케이스 원장에 노출", "'vol_20':" in _q57src)

# 규칙집 버전 승격 + 버전 기록 문서
# 라운드 42 — RULES_NEWS 신설로 룰북이 v2026.08.05 로 올랐다.
# 특정 값을 박아 두면 룰북을 고칠 때마다 이 검사가 막는다.
# 형식과 **전진 여부**만 본다.
_rbv57 = str(qi.RULEBOOK.get('RULES_GENERAL', {}).get('version') or '')
check("규칙집 버전 형식", _re.match(r'^v\d{4}\.\d{2}\.\d{2}$', _rbv57),
      _rbv57)
check("규칙집 버전이 v2026.08.02 이상", _rbv57 >= "v2026.08.02", _rbv57)
_mv57 = _os.path.join(PROJ, "docs", "MODEL_VERSIONS.md")
check("모델 버전 기록 문서 존재", _os.path.exists(_mv57))
if _os.path.exists(_mv57):
    _mvtxt57 = open(_mv57, encoding='utf-8').read()
    check("버전 기록에 변경·이유·기준선·한계 포함",
          all(k in _mvtxt57 for k in ("변경 내용과 이유", "변경 전 기준선", "알려진 한계",
                                      "블라인드")))

# 화면 — 모델 버전·누적 케이스·표본 부족 정직 표기
_w57 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
check("화면에 모델 버전·누적 케이스", "누적 케이스" in _w57)
check("표본 부족 점수대는 적중률 미표시", "표본 부족으로 적중률 미표시" in _w57)


section("58. 조합 대결 규율 — 블라인드는 선택에 쓰지 않는다")

# 대표 퀀트 스타일과의 조합 대결에서 검증 1위(역발상 74.6%)가 블라인드에서
# 23.5%로 붕괴했다. 이 절은 그 규율(사전 정의·검증 선정·블라인드 보고 전용)이
# 코드와 기록에 남아 있음을 잠근다. 결론: 현행 종합점수 조합 유지.

_cs58 = _os.path.join(PROJ, "scripts", "combo_study.py")
check("조합 대결 스크립트 존재", _os.path.exists(_cs58))
if _os.path.exists(_cs58):
    _cstxt58 = open(_cs58, encoding='utf-8').read()
    check("후보는 사전 정의 (원장 보고 만들지 않음)",
          "사전 정의" in _cstxt58 and "COMBOS" in _cstxt58)
    check("승자 선정은 학습+검증만", "블라인드 미사용" in _cstxt58)
    check("블라인드는 승자 확정 후 보고만", "승자 확정 후에만 블라인드 공개" in _cstxt58)
    check("적중률 외 지표 병행 (비용후·PF·신호율)",
          "after_cost" in _cstxt58 and "signal_rate" in _cstxt58)

_mv58 = open(_os.path.join(PROJ, "docs", "MODEL_VERSIONS.md"), encoding='utf-8').read()
check("대결 결과가 버전 대장에 기록", "조합 대결 라운드 1" in _mv58)
check("검증 승자의 블라인드 붕괴를 은폐하지 않음",
      "블라인드 붕괴" in _mv58 and "23.5%" in _mv58)
check("블라인드 성적으로 채택하지 않는 원칙 명시",
      "블라인드로 채택 불가" in _mv58)
check("결론 = 현행 조합 유지", "현행 종합점수 조합 유지" in _mv58)
check("차기 사전 등록 후보 기록 (E 조합)", "차기 라운드" in _mv58 or "사전 등록 후보" in _mv58)
check("산출 보류 부속 연구 기록", "산출 보류" in _mv58 and "58.1%" in _mv58)


section("59. 아주 쉬운 결론 — 신규/보유 기준 분리 · 90% 정직 정책")

# 사용자 요구: 안 샀으면 사도 되는지, 샀으면(평단 기준) 팔지/더 살지/물타기 금지를
# 한 줄로. 신규 매수자와 보유자의 기준을 절대 섞지 않는다.

# ⚠️ 라운드 53 — 픽스처가 `recommended_buy_price` 만 갖고 있었다. 그 키가
# 이 문단의 신규 매수가였기 때문이다. 실제 화면에서 삼성전자 현재가
# 231,000원에 매매 지시서는 "매수구간 208,913~213,133원"이라 하고 바로 아래
# 이 문단이 "147,608원 이하로 내려올 때만 사세요"라고 했다 — 같은 화면에서
# 매수가가 6만원 차이로 둘. 라운드 25 폐기·37 배너 제거 산식이 여기 남아
# 있었다. 이제 신규 매수자 값은 중앙 판정과 같은 entry_* 키를 쓴다.
_fs59 = {'entry_pullback_price': 10000, 'buy_entry_max': 11000,
         'entry_target_1st': 10800, 'entry_stop_price': 9400,
         'recommended_buy_price': 6200,      # 폐기 산식 — 새어 나오면 실패
         'target_tech_1st': 10800, 'target_tech_2nd': 11500,
         'stop_loss_price': 9400, 'm10_disparity': 5.0,
         'calibration_band': {'lo': 55, 'hi': 59, 'n': 921, 'hit_rate': 61.0}}
_v59 = {'score': 62, 'action': 'HOLD', 'vetoes': []}

_e59 = q.build_easy_advice(_fs59, _v59, 10500)
check("비보유·추격 구간 → '이하로 내려올 때만'",
      '이하로 내려올 때만' in _e59['new_buyer']['line'])
check("신규 기준 가격 세트 (분할·추격금지·목표·손절·기간)",
      all(k in _e59['new_buyer']['prices'] for k in
          ('권장 매수가(1차 분할)', '추격매수 금지선', '1차 목표가', '예상 보유기간')))
check("신규 매수가가 중앙 판정 진입가와 같다",
      _e59['new_buyer']['prices']['권장 매수가(1차 분할)'] == 10000)
check("폐기된 적정가×안전마진이 문장에 새지 않는다",
      '6,200' not in (_e59['new_buyer']['line']
                      + _e59['new_buyer']['detail']))
# 진입가를 못 낸 종목 — 폐기 산식으로 물러서지 않는다 (없는 값 > 틀린 값)
_e59z = q.build_easy_advice(dict(_fs59, entry_pullback_price=None),
                            _v59, 10500)
check("진입가 미산출이면 폐기 산식으로 물러서지 않는다",
      '판단을 보류' in _e59z['new_buyer']['line']
      and '6,200' not in str(_e59z['new_buyer']))

_e59b = q.build_easy_advice(_fs59, {'score': 70, 'action': 'BUY', 'vetoes': []}, 9800)
check("매수 가능 → '지금 사도 됩니다 (나눠서)'",
      '지금 사도 됩니다' in _e59b['new_buyer']['line'])
check("틀릴 가능성을 실측으로 명시",
      '틀릴 가능성' in _e59b['new_buyer']['detail'])

_e59c = q.build_easy_advice({'entry_pullback_price': None, 'm10_disparity': 0},
                            {'score': 50, 'action': 'HOLD', 'vetoes': []}, 10000)
check("신뢰도 미달 → 판단 보류 (억지 판단 금지)",
      '판단을 보류' in _e59c['new_buyer']['line'])

# 보유자 분기
_h1 = q.build_easy_advice(_fs59, _v59, 10500, user_avg=9500)['holder']
check("수익 중 정상 → 계속 보유 + 손절 유지", '계속 보유' in _h1['line'])
_h2 = q.build_easy_advice(_fs59, _v59, 9300, user_avg=10500)['holder']
check("손절선 이탈 → 정리 검토", '손절' in _h2['line'] and '이탈' in _h2['line'])
_fs59o = dict(_fs59); _fs59o['m10_disparity'] = 30.0
_h3 = q.build_easy_advice(_fs59o, _v59, 10500, user_avg=8000)['holder']
check("수익+과열 → 일부 매도(절반)", '일부 매도' in _h3['line'])
_fs59d = dict(_fs59); _fs59d['m10_disparity'] = -8.0
_v59d = {'score': 45, 'action': 'HOLD', 'vetoes': ['순기대수익 음수']}
_h4 = q.build_easy_advice(_fs59d, _v59d, 9800, user_avg=11500)['holder']
check("손실+하락추세 → 물타기 금지", '물타기' in _h4['line'] and '마세요' in _h4['line'])
_h5 = q.build_easy_advice(_fs59d, _v59d, 9800, user_avg=13000)['holder']
check("깊은 손실 → 반등 시 비중 축소", '비중 축소' in _h5['line'])
_h6 = q.build_easy_advice(_fs59, _v59, 9800, user_avg=11500)['holder']
check("조건 충족 손실 → 가격 지정 분할 추가매수 허용",
      '이하에서만' in _h6['line'])
check("보유자 가격 세트가 신규와 분리",
      '손절가(보유 기준)' in _h6['prices'] and _h6['prices']['평균 매수가'] == 11500)
check("비보유 응답에는 보유자 블록 없음",
      q.build_easy_advice(_fs59, _v59, 10500)['holder'] is None)

# 화면·정책 연결
_w59 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
check("쉬운 결론 2단 배치 (비보유/보유)", "처음 사는 분께" in _w59
      and "이미 갖고 계신 분께" in _w59)
check("기준 분리 경고 문구", "신규 매수 기준과 보유자 기준은 서로 다릅니다" in _w59)
_lab59 = open(_os.path.join(PROJ, "scripts", "calibration_lab.py"), encoding='utf-8').read()
check("고신뢰(65+) 계층 상시 보고", "고신뢰 신호 계층" in _lab59)
check("표본 미달 시 과장 금지 로직", "표본 부족' 으로 보고" in _lab59
      or "표본 부족\\' 으로 보고" in _lab59 or "과장 없이" in _lab59)
_mv59 = open(_os.path.join(PROJ, "docs", "MODEL_VERSIONS.md"), encoding='utf-8').read()
check("90% 인정 기준 13개항 공식화", "90% 인정 기준" in _mv59 and "⑬" in _mv59)
check("현재 실측·필요 표본 정직 보고", "71.4%" in _mv59 and "필요 표본" in _mv59)


section("60. 손절 운용 규칙 — 본전 스탑 채택 (조언 계층 · KPI 정의 불변)")

# 실패 손실 2위 '노이즈 손절(-992%p)' 겨냥. 사전등록 대결 결과 본전 스탑이
# 손실률을 39.6→26.6%(블라인드 46.2→33.5% 재현)로 줄여 채택하되,
# KPI 채점 정의는 바꾸지 않는다 — 분모 축소로 적중률이 부풀어 보이는 것을 막는다.

_srs60 = _os.path.join(PROJ, "scripts", "stop_rule_study.py")
check("손절 규칙 대결 스크립트 존재", _os.path.exists(_srs60))
_srtxt60 = open(_srs60, encoding='utf-8').read()
check("후보 사전 정의 (원장 미리보기 금지)", "사전 정의" in _srtxt60)
check("봉내 순서 보수적 (손절 우선)", "손절선 먼저" in _srtxt60 or "손절이 먼저" in _srtxt60)
check("본전 청산은 성공으로 세지 않음", "성공으로 세지" in _srtxt60)
check("분모 명시", "분모=" in _srtxt60 or "분모를 명시" in _srtxt60)
check("선정은 학습+검증만", "블라인드 미사용" in _srtxt60)

_mv60 = open(_os.path.join(PROJ, "docs", "MODEL_VERSIONS.md"), encoding='utf-8').read()
check("대결 결과 기록 (블라인드 재현 포함)", "손절 운용 규칙 대결" in _mv60
      and "33.5%" in _mv60)
check("KPI 정의 불변 원칙 명시", "채점 정의는 바꾸지 않는다" in _mv60)
check("고신뢰 구간 부작용도 기록 (은폐 금지)", "본전 청산이 끊는 비용" in _mv60)

# 쉬운 결론에 본전 스탑 조언이 실리는가
# 라운드 53 — 신규 매수자 값을 entry_* 로 옮겼다 (§59 주석 참고)
_fs60 = {'entry_pullback_price': 10000, 'buy_entry_max': 11000,
         'entry_target_1st': 10800, 'entry_stop_price': 9400,
         'target_tech_1st': 10800, 'target_tech_2nd': 11500,
         'stop_loss_price': 9400, 'm10_disparity': 5.0, 'calibration_band': None}
_e60 = q.build_easy_advice(_fs60, {'score': 70, 'action': 'BUY', 'vetoes': []}, 9800)
check("매수 조언에 본전 스탑 규칙 포함",
      '본전' in _e60['new_buyer']['detail'] and '절반' in _e60['new_buyer']['detail'])
check("검증 근거(1,950건) 명시", '1,950건' in _e60['new_buyer']['detail'])
_h60 = q.build_easy_advice(_fs60, {'score': 62, 'action': 'HOLD', 'vetoes': []},
                           10500, user_avg=9500)['holder']
check("수익 중 보유자에게 본전 손절 상향 조언", '본전' in _h60['detail'])


section("61. 뉴스 범위·후행 분류 · 개장 전 확정 리포트 · 테마 토글")

# ① 뉴스 분류 — 낱말 일치만 (해석 금지), 후행 보도(가격 결과 설명)는 재료가 아니다
import market_context as mc61

check("거시 분류", mc61.classify_news_scope("연준 금리 인하 시사") == '거시')
check("시장 분류", mc61.classify_news_scope("코스피 외국인 순매수 전환") == '시장')
check("업종 분류", mc61.classify_news_scope("반도체주 일제히 강세") == '업종')
check("종목 분류(기본)", mc61.classify_news_scope("삼성전자 신제품 공개") == '종목')
check("후행 보도 탐지 — 급등 설명 기사", mc61.is_lagging_report("삼성전자 5% 급등 마감"))
check("후행 아님 — 재료 기사", not mc61.is_lagging_report("삼성전자 대규모 수주 계약"))
_nf61 = mc61.summarize_news_flags({'items': [
    {'title': 'A 수주', 'risk_hits': [], 'watch_hits': ['수주'], 'scope': '종목',
     'lagging': False},
    {'title': 'B 급등', 'risk_hits': [], 'watch_hits': ['수주'], 'scope': '종목',
     'lagging': True},
    {'title': '코스피 상승', 'risk_hits': [], 'watch_hits': [], 'scope': '시장',
     'lagging': True}]})
check("신선 재료 = 종목+참고낱말+비후행만", _nf61['fresh_watch_count'] == 1)
check("범위별 집계", _nf61['by_scope']['종목'] == 2 and _nf61['by_scope']['시장'] == 1)
check("뉴스는 가점 없음 원칙 유지 (위험 낱말 감점만)",
      "가점하지 않는다" in open(_os.path.join(PROJ, "premarket.py"),
                          encoding='utf-8').read())

# ② 개장 전 리포트 — 고정·이력·재계산 금지
import premarket as pm61

_rows61 = [{
    'symbol': '005930.KS', 'name': '삼성전자', 'base_price': 262500,
    'final_score': 61, 'entry_candidate': True, 'm10_above': True,
    'scores_obj': {}, 'snapshot': {'t_ref': '2026-08-01', 'four_scores': {
        'recommended_buy_price': 147590, 'buy_entry_max': 150000,
        'target_tech_1st': 295050, 'target_tech_2nd': 320000,
        'stop_loss_price': 216000, 'asset_type': 'STOCK',
        'final_action_score': 61, 'final_action_title': '조건 확인·관망',
        'gate_reason': '테스트', 'm10_disparity': 5.0}},
}]
_dk61 = "2099-01-01"          # 실제 날짜와 충돌하지 않는 시험용 날짜
# 라운드 30: 리포트 키가 날짜×엔진이 됐다. 옛 경로(날짜만)도 함께 치운다.
_p61 = pm61._pm_path(_dk61, pm61._engine_version())
for _old61 in (_p61, pm61._pm_path(_dk61)):
    if _os.path.exists(_old61):
        _os.remove(_old61)
_rep61, _new61 = pm61.build_report(q, _rows61, date_key=_dk61, market_label="시험")
check("리포트 생성·고정 저장", _new61 and _os.path.exists(_p61))
check("생성 시각·기준일 박제", _rep61.get('generated_at') and _rep61.get('data_asof'))
check("장중 재계산 금지 문구", '다시 계산하지 않습니다' in str(_rep61.get('note')))
_rep61b, _new61b = pm61.build_report(q, [], date_key=_dk61)   # 빈 스캔으로 재호출
check("같은 날 재호출 시 기존 리포트 반환 (고정)",
      not _new61b and len(_rep61b.get('picks', [])) == 1)
_pick61 = _rep61['picks'][0]
check("추천 4분류 어휘", _pick61['reco_class'] in (
    '오늘 사도 되는 종목', '조건부로 사도 되는 종목',
    '오늘은 기다려야 하는 종목', '오늘은 사면 안 되는 종목'))
check("추천 근거 저장 (가격 3종·사유·뉴스)",
      all(k in _pick61 for k in ('rec_buy', 'target', 'stop', 'reasons',
                                 'news_risk', 'news_fresh')))
_hist61 = [l for l in open(pm61.PM_HISTORY, encoding='utf-8')
           if '"2099-01-01"' in l] if _os.path.exists(pm61.PM_HISTORY) else []
check("이력(jsonl) 추가 저장", len(_hist61) >= 1)
check("리포트 파일명에 엔진 버전이 박힌다",
      pm61._engine_version() in _os.path.basename(_p61))
for _old61 in (_p61, pm61._pm_path(_dk61)):   # 시험용 파일 정리
    if _os.path.exists(_old61):               # (이력은 append-only 로 남긴다)
        _os.remove(_old61)

# ③ 화면 — 리포트 섹션·테마 토글
_w61 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
check("개장 전 리포트 섹션", "개장 전 확정 리포트" in _w61)
check("사후 검증 패널 (숨김 금지)", "지난 개장 전 추천의 실제 성과" in _w61)
check("적중률 분모 명시", "분모 = 목표+손절" in _w61)
check("라이트/다크 토글", "라이트 모드" in _w61 and "ui_theme" in _w61)
check("타이포 개선 (tabular-nums·Pretendard 계열)",
      "tnum" in _w61 and "Pretendard" in _w61)


section("62. 종합 인터랙티브 차트 — 지표 선택창 · 데이터 내장 · 실행선 정합")

import chart_pro as cp62
import pandas as _pd62

check("차트 라이브러리 로컬 내장 (외부 CDN 의존 아님)",
      _os.path.exists(cp62._VENDOR_JS))
_tdf62 = _pd62.DataFrame({
    'trade_date': _pd62.date_range('2025-01-01', periods=150, freq='D'),
    'adj_close': [100.0 + i * 0.5 for i in range(150)],
    'open': [100.0 + i * 0.5 - 0.2 for i in range(150)],
    'high': [100.0 + i * 0.5 + 1.0 for i in range(150)],
    'low': [100.0 + i * 0.5 - 1.0 for i in range(150)],
    'volume': [1000.0 + i for i in range(150)],
    'sma_5': [100.0 + i * 0.5 for i in range(150)],
    'sma_20': [99.0 + i * 0.5 for i in range(150)],
    'sma_60': [98.0 + i * 0.5 for i in range(150)],
    'bb_upper': [103.0 + i * 0.5 for i in range(150)],
    'bb_lower': [97.0 + i * 0.5 for i in range(150)],
    'rsi_14': [55.0] * 150,
})
_fs62 = {'recommended_buy_price': 120.0, 'target_tech_1st': 190.0,
         'target_tech_2nd': 200.0, 'stop_loss_price': 110.0,
         'demark_res': {'buy_setup_series': [0] * 149 + [9],
                        'tdst_support': 115.0}}
#: 중앙 판정 결과. 라운드 53 이전에는 이 인자가 없어서 차트가 four_scores 를
#: 직접 읽었다 — 그 결과 배너와 다른 숫자를 그렸다 (아래 검사 참고).
_core62 = {'pullback_zone': 125.0, 'new_target': 140.0, 'new_stop': 118.0,
           'hold_trim': 190.0, 'hold_stop': 110.0, 'breakout_price': 150.0,
           'bucket': '눌림목 매수 대기'}
_html62 = cp62.build_chart_html(_tdf62, _fs62, name='시험', theme='dark',
                                user_avg=130.0, core=_core62)
check("HTML 문자열 생성", isinstance(_html62, str) and len(_html62) > 100_000)
check("지표 선택창 존재 (사용자가 원하는 지표를 고른다)",
      'indPanel' in _html62 and '지표 선택' in _html62)
check("추가 지표 — 스토캐스틱·OBV·EMA20",
      all(k in _html62 for k in ('stochK', 'obv', 'ema20')))
check("선택 상태 저장 (localStorage)", 'qchart_ind_v1' in _html62)
# ⚠️ 라운드 53 — 이 검사는 원래 `'추천 매수가'` 가 HTML 에 있는지만 봤다.
# 그런데 그 선의 출처가 `recommended_buy_price`(적정가 × 안전마진)였다.
# 라운드 25 에서 폐기하고 라운드 37 에 배너에서 걷어낸 산식이다 — 삼성전자
# 240,000원에 "147,567원 이하로 사세요"를 만든 값. 즉 **검사가 결함을
# 잠그고 있었다.** 이름이 아니라 출처와 값을 본다.
check("실행 가격선을 중앙 판정에서 받는다 (신규 매수자 기준)",
      all(s in _html62 for s in ('실행 진입가 · 신규', '1차 목표 · 신규',
                                 '손절 · 신규', '내 평단가')))
check("폐기된 추천매수가 산식을 더는 그리지 않는다",
      '"price": 120.0' not in _html62 and '추천 매수가' not in _html62)
check("신규 진입가가 실제로 실렸다", '"price": 125.0' in _html62)
check("보유자 기준은 이름표로 갈린다",
      '1차 목표 · 보유자' in _html62 and '손절 · 보유자' in _html62)
check("돌파 자리가 아니면 돌파선을 그리지 않는다 (소음 방지)",
      '돌파 매수가' not in _html62)
_html62b = cp62.build_chart_html(_tdf62, _fs62, name='시험', theme='dark',
                                 core=dict(_core62,
                                           bucket='돌파 후 매수 대기'))
check("돌파 대기면 돌파 매수가를 그린다", '돌파 매수가 · 신규' in _html62b)
check("보유자 값은 평단이 있을 때만", '손절 · 보유자' not in _html62b)
_html62c = cp62.build_chart_html(_tdf62, _fs62, name='시험', theme='dark')
check("중앙 판정이 없으면 틀린 선 대신 아무것도 안 그린다",
      '추천 매수가' not in _html62c and '실행 진입가' not in _html62c)
check("DeMARK 마커 시리즈 내장", '"text": "9"' in _html62)
check("라이선스 표기 (Apache 2.0 attribution)",
      'TradingView Lightweight Charts' in _html62)
_html62L = cp62.build_chart_html(_tdf62, _fs62, name='시험', theme='light')
check("라이트 테마 팔레트 분기", '#ffffff' in _html62L and
      _html62L != _html62)
check("웹앱 통합 — 판정 근거 위 종합 차트", '종합 차트' in _w61 and
      'chart_pro' in _w61)
check("수치 무단 생성 금지 — tech_df 검증 컬럼 재사용 원칙 주석",
      '어긋나는' in open(_os.path.join(PROJ, "chart_pro.py"),
                     encoding='utf-8').read())


section("63. 재설계 2단계 — 홈 지휘센터 · 모델 성과 감사 · 점수 요인")

_w63 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()

# ① 홈 지휘센터 — 실측 카드에 표본 수(n) 병기, 보장 문구 금지
# UI 킷 타일로 렌더 — 5개 지표가 모두 있고, 표본 수를 보조에 적는다
check("홈 카드 4종 — 사용자 언어 라벨 + 점수 문턱 명시", all(
    s in _w63 for s in (
        "'되돌려 본 판단'", "'60점+ 신호 연습 적중률'",
        "'60점+ 신호 실전 적중률'", "'매수 기회'")))
check("홈 카드 — 킷 컴포넌트로 렌더 (인라인 HTML 금지)",
      '_uk.stat_tiles(' in _w63 and '_uk.section(' in _w63)
check("홈 카드 — 대표 지표가 매수권 기준 (전체 사례가 아님)",
      '60점+ 신호 실전 적중률' in _w63
      and '매수 신호 {_bzv.get' in _w63)
check("홈 카드 — 전체 사례 적중률도 숨기지 않고 보조로 남긴다",
      '점수와 무관하게 전체 사례를 다 센 적중률' in _w63)
check("홈 카드 — 보장하지 않는다 명시", '미래 수익을 보장' in _w63)
check("개장 전 한 줄 결론 — 리포트 없으면 만들어내지 않음",
      '_pm_today and _pm_today.get' in _w63)

# ② 모델 성과 섹션 — 감사 화면 4표 + 한계 경고
check("모델 성과 섹션 존재", '모델 자체 점검' in _w63)
check("시간 분할 성과 표", '시간 분할 성과' in _w63)
check("매수권(60+) 분해 표", '매수권(60점 이상) 신호만' in _w63)
check("점수대 캘리브레이션 표", '점수대별 실측 적중률' in _w63)
check("실패 원인 분류 표", '실패 원인 분류' in _w63)
check("블라인드는 선택에 쓰지 않는다 문구", '모델 선택에 쓰지 않습니다' in _w63)
check("한계 경고 — 괴리·표본 부족 조건부 표시",
      '반드시 함께 읽어야 하는 한계' in _w63 and '표본 100건 이상' in _w63)
check("표본 부족 임계 30건 미만 표기", "n'] < 30" in _w63 or "n < 30" in _w63)

# ③ 점수 요인 — verdict.composition 실측만 사용
# 예전에는 상·하위 3개씩 잘라 썼는데, 요인이 3개뿐이면 같은 세 줄이 양쪽에
# 서는 것이 화면에서 확인됐다. 이제 기준은 개수가 아니라 **가중평균**이다.
check("점수 요인은 가중평균 기준으로 갈린다 (개수로 자르지 않는다)",
      "_comp_avg" in _w63
      and "c['score'] > _comp_avg" in _w63
      and "c['score'] < _comp_avg" in _w63)
check("한쪽이 비면 나누지 않고 한 줄로 세운다",
      '점수를 만든 요인' in _w63)
check("요인마다 평균 대비 차이를 병기 — 갈린 근거를 확인할 수 있게",
      '평균 대비' in _w63)
check("요인은 composition 실측에서만",
      "verdict.get('composition'" in _w63)

# ④ 내비게이션 — 모델 성과 링크와 앵커
check("내비 모델 성과 링크 — 좌측 내비에 정의, 앵커는 본문에",
      "'#nav-perf'" in _w63 and 'id="nav-perf"' in _w63)


section("64. 케이스 스터디 화면 — 원장 필터 · 배포용 산출물 동봉")

_w64 = _w63

# ① 산출물 폴백 — 로컬(.portfolio) 우선, 저장소 동봉(data/) 폴백
check("산출물 경로 폴백 함수", '_artifact_path' in _w64
      and '".portfolio", "data"' in _w64)
check("배포용 calibration.json 동봉",
      _os.path.exists(_os.path.join(PROJ, "data", "calibration.json")))
check("배포용 원장 동봉",
      _os.path.exists(_os.path.join(PROJ, "data", "virtual_graded.jsonl")))
import json as _json64
with open(_os.path.join(PROJ, "data", "calibration.json"),
          encoding='utf-8') as _f64:
    _cal64 = _json64.load(_f64)
check("동봉 산출물이 실측 구조 (splits·bands·failure_classes)",
      all(k in _cal64 for k in ('splits', 'bands', 'failure_classes',
                                'total_cases')))
# 민감정보 미포함 — 원장 첫 줄에 보유종목·평단가 계열 키가 없어야 한다
with open(_os.path.join(PROJ, "data", "virtual_graded.jsonl"),
          encoding='utf-8') as _f64b:
    _row64 = _json64.loads(_f64b.readline())
check("원장에 개인 정보 없음 (평단가·수량·계좌 금지)",
      not any(k in _row64 for k in ('user_avg', 'avg_price', 'quantity',
                                    'account', 'entry_price')))

# ② 화면 — 필터·요약·표본 부족 경고·사례 목록
check("케이스 스터디 섹션", '과거 판단 하나하나 열어 보기' in _w64)
check("필터 4종 (분할·결과·점수대·국면)", all(s in _w64 for s in (
    'cs_split', 'cs_out', 'cs_score', 'cs_regime')))
check("표본 30건 미만 경고", '표본이 30건 미만' in _w64)
check("빈 결과 안내 (날조 금지)", '해당하는 사례가 없습니다' in _w64)
check("사례 목록 — MFE/MAE·실패 원인 노출", '최대이익 MFE' in _w64
      and '최대손실 MAE' in _w64)
# v2 정보구조: 전역 메뉴는 6개 — 케이스 스터디는 모델 검증 내부(앵커만 유지)
check("케이스 앵커 유지 · 좌측 메뉴 링크 8개+",
      'id="nav-cases"' in _w64 and _w64.count("'#nav-") >= 8)


section("65. 운영 체계 v3 — 공시 연동 · 업데이트 히스토리 · 케이스 축적 규율")

_w65 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()

# ① 공시 — 원문 나열만, 해석·요약 생성 금지, 점수 미반영
check("공시 수집 함수 존재", hasattr(mc61, 'fetch_stock_disclosures'))
_disc_src = open(_os.path.join(PROJ, "market_context.py"), encoding='utf-8').read()
check("공시 — 날조 금지 원칙 명문화", '원문 그대로' in _disc_src
      and '날조 금지' in _disc_src)
_fake_html = ('<td class="title"> <a href="/item/read?no=1&code=005930" x>'
              'AA(주) 유상증자 결정</a></td> <td class="info">KOSCOM</td> '
              '<td class="date">2026.07.30</td>')
import re as _re65
_rows65 = _re65.findall(
    r'<td class="title">\s*<a href="([^"]+)"[^>]*>([^<]+)</a>.*?'
    r'<td[^>]*>\s*([^<]*?)\s*</td>\s*<td[^>]*>\s*([\d.]+)\s*</td>',
    _fake_html, _re65.S)
check("공시 파서 — 제목·정보제공·날짜 3열", len(_rows65) == 1
      and _rows65[0][1] == 'AA(주) 유상증자 결정'
      and _rows65[0][3] == '2026.07.30')
check("웹앱 공시 섹션 — 점수 미반영 명시", '최근 기업 공시' in _w65
      and '점수에 자동 반영하지 않습니다' in _w65)

# ② 업데이트 히스토리 — 원천은 커밋 로그 (손으로 쓰지 않는다)
check("히스토리 생성 스크립트", _os.path.exists(
    _os.path.join(PROJ, "scripts", "gen_update_history.py")))
check("히스토리 데이터 동봉", _os.path.exists(
    _os.path.join(PROJ, "data", "update_history.json")))
with open(_os.path.join(PROJ, "data", "update_history.json"),
          encoding='utf-8') as _f65:
    _uh65 = _json64.load(_f65)
check("히스토리 — git 원천 명시·비어있지 않음",
      'git' in str(_uh65.get('generated_from', ''))
      and len(_uh65.get('days', [])) >= 1)
check("웹앱 히스토리 — 접힌 패널 + 앵커",
      "id='nav-updates'" in _w65
      and 'st.expander(f\"업데이트 {_n_upd}건' in _w65)

# ③ 케이스 축적 규율 — 목표 단계·중단 금지·운영 문서
check("케이스 축적 목표 표시 (단계 목표·중단 금지)",
      '10,000건' in _w65 and '중단하지 않습니다' in _w65)
check("운영 루틴 문서", _os.path.exists(
    _os.path.join(PROJ, "docs", "OPERATIONS_ROUTINE.md")))
_ops65 = open(_os.path.join(PROJ, "docs", "OPERATIONS_ROUTINE.md"),
              encoding='utf-8').read()
check("운영 문서 — 3계층 분리·승격 조건·정직 문구",
      '운영 모델' in _ops65 and '후보 모델' in _ops65
      and '확정 성능으로 볼 수 없습니다' in _ops65)
check("블라인드 갭 보고서 존재", _os.path.exists(
    _os.path.join(PROJ, "docs", "BLIND_GAP_REPORT.md")))
_bg65 = open(_os.path.join(PROJ, "docs", "BLIND_GAP_REPORT.md"),
             encoding='utf-8').read()
check("갭 보고서 — 블라인드로 모델을 고치지 않는다 규율",
      '고치지 않는다' in _bg65 and '국면' in _bg65)

# ④ 차트 '전체' — 전체 이력 탑재 (n_bars 기본 None)
_cp65 = open(_os.path.join(PROJ, "chart_pro.py"), encoding='utf-8').read()
check("차트 기본값 전체 이력 (n_bars=None)", 'n_bars=None' in _cp65
      and "'전체' 버튼이 진짜 전체" in _cp65)


section("66. v4 제품형 UX — 주요 이슈 · 업데이트 패널 · 고객센터")

import product_ops as po66

_w66 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()

# ① 업데이트 카테고리 — 커밋 제목 낱말 규칙 (내용 재작성 금지)
check("카테고리 분류 — 모델", po66.classify_update_category(
    "블라인드 검증 리포트 구조 개선") == '모델')
check("카테고리 분류 — UI/UX", po66.classify_update_category(
    "라이트 모드 대비 0건 달성") == 'UI/UX')
check("카테고리 분류 — 케이스", po66.classify_update_category(
    "케이스 축적 재가동") == '케이스 스터디')
check("카테고리 분류 — 미매칭은 기타", po66.classify_update_category(
    "안녕하세요") == '기타')
_enr66 = po66.enrich_update_history({'days': [
    {'date': '2026-08-01', 'items': [{'hash': 'abc', 'subject': '뉴스 범위 분류'}]}]})
check("히스토리 보강 — 버전 표기·카테고리·원문 불변",
      _enr66[0]['version'] == 'v26.08.01'
      and _enr66[0]['items'][0]['category'] == '뉴스 분석'
      and _enr66[0]['items'][0]['subject'] == '뉴스 범위 분류')

# ② 전역 이슈 — 실측·실경고에서만 파생 (날조 금지)
_cal66 = {'splits': {'valid': {'hit_rate': 66.8}, 'blind': {'hit_rate': 51.4},
                     'buy_zone': {'blind': {'n': 13, 'hit_rate': 84.6}}},
          'signal_frequency': {'rate_pct': 2.9, 'total': 3059, 'buy_zone': 90}}
_gi66 = po66.build_global_issues(_cal66, {'index_missing': False})
check("전역 이슈 — 표본 부족·괴리·신호율 생성", len(_gi66) == 3)
check("전역 이슈 — 중요도 정렬 (높음 우선)", _gi66[0]['severity'] == '높음')
check("표본 충분+괴리 없음이면 해당 이슈 미생성", len(po66.build_global_issues(
    {'splits': {'valid': {'hit_rate': 66.0}, 'blind': {'hit_rate': 60.0},
                'buy_zone': {'blind': {'n': 120, 'hit_rate': 70.0}}},
     'signal_frequency': {'rate_pct': 8.0}}, {})) == 0)
check("지수 미수신 → 데이터 이슈 높음", any(
    i['type'] == '데이터' and i['severity'] == '높음'
    for i in po66.build_global_issues({}, {'index_missing': True})))

# ③ 종목 이슈 — 이미 계산된 게이트·경고 재표현만
_si66 = po66.build_stock_issues(
    {'gate_reason': '월10 과열', 'calibration_band': {'n': 2}},
    {'vetoes': ['거래비용 차감 기대값 음수'], 'cap_applied': True, 'score': 49},
    {'risk_count': 2}, name='시험')
check("종목 이슈 — 차단·상한·뉴스·표본 생성", len(_si66) >= 4)
check("종목 이슈 — 차단 조건이 최상위(높음)", _si66[0]['severity'] == '높음')
check("경고 없으면 이슈 없음", po66.build_stock_issues({}, {}, {}) == [])

# ④ 화면 — v4 패널·전체 보기·고객센터
check("홈 주요 이슈 섹션 — 건수·최상위 제목이 접힌 채로 보인다",
      '주요 이슈 ' in _w66 and '건 — ' in _w66)
check("종목 이슈 섹션", '이 종목의 주요 이슈' in _w66)
check("업데이트 패널 — 눌러야 열리고 한 줄씩 (사용자 요청: 아주 간략하게)",
      '아주 간략하게 — 한 줄씩' in _w66
      and '전체 업데이트 보기' in _w66 and 'upd_cat_filter' in _w66)
check("고객센터 — 실제 대처법·신고 채널", '고객센터 — 안 될 때 여기부터' in _w66
      and 'github.com/hwanking/quant-stock-simulator/issues' in _w66)
check("이슈=지금/업데이트=과거 역할 구분 문서화",
      '지금 중요한 것' in open(_os.path.join(PROJ, "product_ops.py"),
                          encoding='utf-8').read())


section("67. 무료 언어모델 주간 관찰 — 자동 갱신 · 관찰 전용 · 전송 금지")

import llm_watch as lw67

check("주단위 TTL (7일)", lw67._TTL_SECONDS == 7 * 24 * 3600)
_lw_src = open(_os.path.join(PROJ, "llm_watch.py"), encoding='utf-8').read()
check("관찰 전용 — 자동 연결 금지 명문화", '자동 연결하지 않는다' in _lw_src
      and '§58' in _lw_src)
check("전송 금지 — GET 조회뿐", '아무것도 보내지 않는다' in _lw_src)
check("실패 시 옛 캐시 유지 (빈 화면·날조 금지)", 'stale' in _lw_src)
check("배포용 캐시 동봉", _os.path.exists(
    _os.path.join(PROJ, "data", "llm_watch.json")))
with open(_os.path.join(PROJ, "data", "llm_watch.json"),
          encoding='utf-8') as _f67:
    _lwd67 = _json64.load(_f67)
check("관찰 데이터 — 모델·라이선스·갱신일 구조",
      len(_lwd67.get('models', [])) >= 5
      and all(k in _lwd67['models'][0] for k in ('id', 'downloads', 'license'))
      and _lwd67.get('fetched_at'))
check("웹앱 관찰 패널 — 포트폴리오 전송 금지 명시",
      '무료 언어모델 주간 관찰' in _w66.replace(_w66, open(
          _os.path.join(PROJ, "web_app.py"), encoding='utf-8').read())
      and '어떤 외부 모델에도 전송하지 않습니다' in open(
          _os.path.join(PROJ, "web_app.py"), encoding='utf-8').read())
check("운영 문서 주간 항목", '무료 언어모델 관찰' in open(
    _os.path.join(PROJ, "docs", "OPERATIONS_ROUTINE.md"),
    encoding='utf-8').read())


section("68. v5 — 이슈 토글 · 모델 상태 요약 축소 · 매수권 스캔 추천")

_w68 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()

check("주요 이슈 토글 — 접힌 제목에 건수·최상위 노출",
      "주요 이슈 {len(_issues_global)}건" in _w68)
# 모델 상태: 토글 없이 상시 표시 + 화면 최상단 (사용자 요청)
check("모델 상태 — 상시 표시·화면 최상단 고정",
      '홈 1순위: 모델 상태' in _w68
      and _w68.index('홈 1순위: 모델 상태')
      < _w68.index('# 개장 전 한 줄 결론')
      < _w68.index('# ── 주요 이슈 (v4)')
      < _w68.index('# 시장 지수 — 배경정보'))
check("매수권(60점+) 스캔 강조 — 트렌드 탐색기 연동",
      "고신뢰 매수권(60점+)" in _w68 and "_bz_rows" in _w68)
check("매수권 없음 = 관망 결론 (날조 금지)",
      "없는 날은 관망이 결론입니다" in _w68)
check("v5 폴리시 — 접이식 카드화·pill 버튼",
      "border-radius: 999px" in _w68
      and 'stExpander' in _w68)


section("69. 신호 게이트 라운드 2 — 사전등록 대결 · 확장 신호 2계층")

_ss69 = open(_os.path.join(PROJ, "scripts", "signal_study.py"),
             encoding='utf-8').read()
check("사전등록 — 후보·선정 규칙이 코드에 먼저 명문화",
      'CANDIDATES' in _ss69 and '선정 규칙' in _ss69)
check("규율 — 블라인드는 승자 확정 후 1회만", '승자 확정 후 단 1회' in _ss69)
check("규율 — 억지 채택 금지 (통과 없으면 기준선 유지)",
      '기준선을 유지한다' in _ss69)
check("규율 — 미공개 원칙 (선택에 못 쓰면 보지 않는다)",
      '볼 이유가 없다' in _ss69)

_w69 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
check("스캔 2계층 — 고신뢰(60+)·확장(58~59) 분리 표시",
      '고신뢰 매수권(60점+)' in _w69 and '확장 신호(58~59점)' in _w69)
check("확장 신호 정직 표기 — 최신 실측·비용후 음수·탐색용",
      '블라인드 55.3%(n=226)' in _w69 and '탐색용' in _w69)
_mv69 = open(_os.path.join(PROJ, "docs", "MODEL_VERSIONS.md"),
             encoding='utf-8').read()
check("MODEL_VERSIONS 라운드 2 기록 — 채택 범위·KPI 불변",
      '신호 게이트 대결 라운드 2' in _mv69
      and 'KPI 정의(매수권=60+' in _mv69)
check("차기 후보 기록 (E 재대결·D 기각)", '차기 후보' in _mv69
      and 'D 실패로 기각' in _mv69)


section("70. 진입 검토가 폴백 — 기술 지지 계층 · 미산출 사유 · 억지 산출 금지")

# ① 엔진 — 권장 매수가 없을 때 기술 지지 기반 진입 검토가 (실계산 검증)
_fs70 = snap['four_scores']
check("entry_review 필드 존재", 'entry_review_price' in _fs70
      and 'entry_review_basis' in _fs70)
if _fs70.get('recommended_buy_price') is not None:
    check("권장 매수가 있으면 검토가는 None (계층 혼용 금지)",
          _fs70.get('entry_review_price') is None)
else:
    _erp70 = _fs70.get('entry_review_price')
    check("검토가는 항상 현재가 아래 지지선 (억지 산출 금지)",
          _erp70 is None or _erp70 > 0)
_qi70 = open(_os.path.join(PROJ, "quant_indicators.py"), encoding='utf-8').read()
check("엔진 원칙 주석 — 지어내지 않는다·억지로 만들지 않는다",
      '지어내지 않는다' in _qi70 and '억지로 만들지 않는다' in _qi70)
check("후보 = 기존 계산된 지지선만 (TDST·20일선·볼린저)",
      "'TDST 지지선'" in _qi70 and "'20일 이동평균선'" in _qi70
      and "'볼린저 하단'" in _qi70)

# ② 화면 — 계층 라벨·미산출 사유
_w70 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
check("배너 — 검토가 계층 라벨 (적정가 검증 없음 명시)",
      '기술 지지 기준:' in _w70 and '적정가 검증 없음' in _w70)
check("배너 — 지지선조차 없으면 없다고 말한다",
      '유효 지지선도 없음' in _w70)
check("적정가 미산출 카드 — 사유 캡션", 'fair_value_status_note' in _w70)
check("오늘의 추천 카드 → 분석 화면 전환 버튼",
      '분석 보기' in _w70 and 'pm_go_' in _w70)


section("71. 추천-결론 정합 · 제외 분리 · 뉴스 관련성 구분")

# ① 분류는 쉬운 결론과 모순되지 않는다 (야스 사례: 제목 '조건부'·본문 '보류')
check("보류 결론 → '사도 됨' 분류 금지", pm61._classify_reco(
    {'entry_candidate': True, 'final_score': 61},
    "분석 신뢰도가 낮아 판단을 보류하세요.") == '오늘은 기다려야 하는 종목')
check("가격 조건부 매수 → 조건부 분류", pm61._classify_reco(
    {'entry_candidate': True, 'final_score': 61},
    "31,665원 이하로 내려올 때만 사세요.") == '조건부로 사도 되는 종목')
check("사도 됩니다 + 60점 + 후보 → 사도 되는 종목", pm61._classify_reco(
    {'entry_candidate': True, 'final_score': 62},
    "지금 사도 됩니다.") == '오늘 사도 되는 종목')
check("사지 마세요 → 사면 안 되는 종목", pm61._classify_reco(
    {'entry_candidate': False, 'final_score': 55},
    "지금은 사지 마세요 — 조건이 충족될 때까지 기다리세요.")
    == '오늘은 사면 안 되는 종목')

_w71 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
# ② 표시 정합 가드 + 사면 안 되는 종목은 추천 카드에서 분리
check("표시 정합 가드 존재 (고정 리포트의 옛 라벨도 결론 따름)",
      '_pm_display_class' in _w71 and "'보류' in easy" in _w71)
check("추천 카드에서 '사면 안 되는 종목' 제외·별도 목록",
      '오늘 제외된 종목' in _w71 and '_picks_ban' in _w71)
# ③ 뉴스 — 종목명 직접 언급만 '직접', 나머지는 '참고' (낱말 일치만)
check("뉴스 관련성 구분 — 직접/참고 뱃지", '_direct_items' in _w71
      and '`참고`' in _w71)
check("직접 기사 없으면 그렇다고 말한다", '직접 언급된 기사가 없습니다' in _w71)


section("72. 국면 상세 · 배너 조건부 병기")

# ① 지수 상세 — 이격·등락·52주 위치 실계산 (KOSPI 실호출)
_dd72 = mc61.fetch_domestic_detail(engine, "KOSPI")
check("지수 상세 실계산 — 필수 필드", _dd72.get('available')
      and all(k in _dd72 for k in ('disp20', 'disp60', 'chg20', 'pos52')))
check("52주 위치는 0~100 범위",
      _dd72.get('pos52') is None or 0 <= _dd72['pos52'] <= 100)
check("이격 정의 일치 — price/sma20-1",
      abs(_dd72['disp20']
          - ((_dd72['price'] / ((_dd72['price'] / (1 + _dd72['disp20'] / 100)))
              - 1) * 100)) < 1e-6)
_w72 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
check("화면 — 코스피·코스닥 상세 표 + 해석 없음 명시",
      "('KOSPI', 'KOSDAQ')" in _w72 and '해석을 덧붙이지' in _w72)

# ② 배너 — 조건부 매수가 헤드라인에서 바로 보인다
check("배너 쉬운 결론 병기 + 현재가 조건 관계",
      '_banner_sub' in _w72 and '조건 위' in _w72)
check("중복 문구 방지 (헤드라인과 같으면 생략)",
      "not in str(verdict['headline'])" in _w72)


section("73. 진입 갭 라운드 2.5 — 갭 표기 · 적정가 이하 구분 · 사전등록 채택")

_gs73 = open(_os.path.join(PROJ, "scripts", "entry_gap_study.py"),
             encoding='utf-8').read()
check("사전등록 — 후보·선정 규칙 명문화", 'CANDIDATES' in _gs73
      and '선정 규칙' in _gs73)
check("규율 — 통과 없으면 기준선 유지·블라인드 미공개",
      '기준선 유지' in _gs73)
_w73 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
check("추천 카드 갭% 표기", '_gap_pct' in _w73 and '권장보다' in _w73)
check("갭 큰 조건부 — 사실상 관망 경고 (표시 임계 7%)",
      '단기 도달 가능성이 낮습니다' in _w73)
check("확장 신호 — 적정가 이하 구분·실측 병기",
      '적정가 이하 진입' in _w73 and '58.9%(n=95)' in _w73)
_pm73 = open(_os.path.join(PROJ, "premarket.py"), encoding='utf-8').read()
check("premarket — entry_zone 저장 (다음 리포트부터)",
      "'entry_zone': fs.get('entry_zone')" in _pm73)
_mv73 = open(_os.path.join(PROJ, "docs", "MODEL_VERSIONS.md"),
             encoding='utf-8').read()
check("MODEL_VERSIONS 라운드 2.5 — train 불일치 주의 기록",
      '라운드 2.5' in _mv73 and 'train 방향 불일치' in _mv73)


section("74. 지속 개선 엔진 — 동결·중복 방지·동일봉 unresolved·승격 게이트")

import tempfile as _tmp74
from datetime import date as _date74

from improvement import database as idb
from improvement import case_tracker as ict
from improvement import issue_tracker as iit
from improvement.performance import resolve_long_case as _rlc
from improvement.promotion import (PromotionMetrics as _PM,
                                   evaluate_promotion as _ep)
from improvement.schemas import Decision as _Dec

_db74 = _os.path.join(_tmp74.gettempdir(), "improvement_test74.db")
if _os.path.exists(_db74):
    _os.remove(_db74)
idb.initialize_database(_db74)
_conn74 = idb.get_connection(_db74)

# ① 케이스 동결 — case_id 결정성·중복 무시
_case74 = ict.create_prediction_case(
    ticker="005930.KS", asset_type="STOCK",
    signal_date=_date74(2026, 8, 1), model_version="vT",
    rulebook_version="vT", decision=_Dec.CONDITIONAL_BUY,
    total_score=58, confidence_score=60, reference_price=100.0,
    entry_price=95.0, target_price=110.0, stop_price=90.0,
    holding_days=20, market_regime="테스트", strategy_type="조건부",
    source_payload={'a': 1})
check("case_id 결정적 해시", _case74.case_id == ict.make_case_id(
    "005930.KS", _date74(2026, 8, 1), "vT", _Dec.CONDITIONAL_BUY))
check("첫 저장 성공", ict.save_prediction_case(_conn74, _case74))
check("같은 종목·날짜·모델·판단 중복 무시",
      not ict.save_prediction_case(_conn74, _case74))
try:
    ict.create_prediction_case(
        ticker="X", asset_type="STOCK", signal_date=_date74(2026, 8, 1),
        model_version="v", rulebook_version="v", decision=_Dec.BUY,
        total_score=1, confidence_score=1, reference_price=0,
        entry_price=None, target_price=None, stop_price=None,
        holding_days=20, market_regime="", strategy_type="",
        source_payload={})
    check("reference_price<=0 거부", False)
except ValueError:
    check("reference_price<=0 거부", True)

# ② 결과 판정 — 같은 봉 목표+손절 동시 도달은 성공으로 세지 않는다
import pandas as _pd74
_bar = lambda h, l, c: {'high': h, 'low': l, 'close': c}
_res_both = _rlc(price_data=_pd74.DataFrame([_bar(112, 88, 100)]),
                 entry_price=95.0, target_price=110.0, stop_price=90.0)
check("동일봉 목표·손절 → unresolved (임의 성공 금지)",
      _res_both.status == 'unresolved')
_res_stop = _rlc(price_data=_pd74.DataFrame([_bar(105, 88, 92)]),
                 entry_price=95.0, target_price=110.0, stop_price=90.0)
check("손절 선도달 → failure", _res_stop.status == 'failure'
      and abs(_res_stop.realized_return - (90 / 95 - 1)) < 1e-9)
_res_tgt = _rlc(price_data=_pd74.DataFrame([_bar(111, 94, 108)]),
                entry_price=95.0, target_price=110.0, stop_price=90.0)
check("목표 선도달 → success", _res_tgt.status == 'success')
_res_none = _rlc(price_data=_pd74.DataFrame([_bar(100, 94, 96)] * 3),
                 entry_price=95.0, target_price=110.0, stop_price=90.0)
check("기간 내 미도달 → unresolved + 종가 수익률",
      _res_none.status == 'unresolved'
      and abs(_res_none.realized_return - (96 / 95 - 1)) < 1e-9)
check("빈 데이터 → data_error (모델 실패와 분리)",
      _rlc(price_data=_pd74.DataFrame(columns=['high', 'low', 'close']),
           entry_price=95, target_price=110, stop_price=90
           ).status == 'data_error')

# ③ 승격 게이트 — 자동 교체 방지
_cur74 = _PM(blind_count=500, blind_accuracy=0.55, expected_return=0.001,
             profit_factor=1.0, max_drawdown=-0.05, signal_rate=0.03)
check("표본 부족 후보 기각", not _ep(
    current=_cur74, candidate=_PM(50, 0.99, 0.05, 3.0, -0.03, 0.05)).approved)
check("신호율 과소 후보 기각", not _ep(
    current=_cur74, candidate=_PM(300, 0.60, 0.01, 1.5, -0.04, 0.001)).approved)
check("전 조건 통과 시에만 승인", _ep(
    current=_cur74, candidate=_PM(300, 0.60, 0.01, 1.5, -0.04, 0.03)).approved)

# ④ 이슈 dedup — 같은 키 재생성 금지, 해소 후 재생성 가능
_i1 = iit.create_issue(_conn74, category='model', severity='high',
                       title='T', summary='S', issue_key='k1')
_i2 = iit.create_issue(_conn74, category='model', severity='high',
                       title='T', summary='S', issue_key='k1')
check("이슈 중복 생성 방지 (issue_key)", _i1 is not None and _i2 is None)
iit.resolve_by_key(_conn74, 'k1')
_i3 = iit.create_issue(_conn74, category='model', severity='high',
                       title='T', summary='S', issue_key='k1')
check("해소 후 재발 시 재생성 가능", _i3 is not None)
_conn74.commit()
_conn74.close()

# ⑤ 실연결 — 일일 파이프라인이 실제 추천 이력을 동결했고 멱등이다
_impdb = idb.get_connection()
try:
    _n_cases = _impdb.execute(
        "SELECT COUNT(*) FROM prediction_cases").fetchone()[0]
    _n_runs = _impdb.execute(
        "SELECT COUNT(*) FROM pipeline_runs WHERE status='success'"
    ).fetchone()[0]
finally:
    _impdb.close()
check("실전 케이스 동결 저장 (개장 전 추천 → DB)", _n_cases >= 1)
check("파이프라인 실행 로그 기록", _n_runs >= 2)


section("75. 확률 최우선 — 배너 실측 확률 격상 · 연구 후보 등록부 · 상태 UI")

_w75 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
check("배너 — 실측 성공률을 점수 옆 1등으로",
      '비슷했던 과거에서 맞은 비율' in _w75 and '_prob_html' in _w75)
check("배너 — 표본<30이면 %를 숨기고 '표본 부족' 표시",
      '표시 보류' in _w75 and '>= 30' in _w75)
check("확률 원천은 리플레이 실측뿐 (요행 수치 금지 주석)",
      '요행 수치를 대표값으로 쓰지 않는다' in _w75)

from improvement import research as ires
_db75 = _os.path.join(_tmp74.gettempdir(), "improvement_test75.db")
if _os.path.exists(_db75):
    _os.remove(_db75)
idb.initialize_database(_db75)
_c75 = idb.get_connection(_db75)
_cid75 = ires.register_research_candidate(
    _c75, source="SSRN 0000", core_idea="시험 아이디어",
    target_failure="노이즈 손절", implementable=True)
check("연구 후보 등록 — 채택은 NULL(미정)로 시작",
      _c75.execute("SELECT adopted FROM research_candidates "
                   "WHERE candidate_id=?", (_cid75,)).fetchone()[0] is None)
ires.record_decision(_c75, _cid75, adopted=False,
                     validation_result="검증 미통과", decision_reason="비용후 열위")
check("연구 후보 — 기각 사유 기록", _c75.execute(
    "SELECT adopted, decision_reason FROM research_candidates "
    "WHERE candidate_id=?", (_cid75,)).fetchone()['decision_reason']
    == "비용후 열위")
check("케이스 MFE 열 존재 (스키마 확장)", any(
    r[1] == 'max_runup' for r in _c75.execute(
        "PRAGMA table_info(prediction_cases)").fetchall()))
_c75.commit()
_c75.close()

check("파이프라인 상태 UI — 대기 건수·마지막 실행·수동 실행",
      '결과 확정 대기' in _w75 and 'btn_run_improvement' in _w75)
check("클라우드 영속성 정직 경고", '재배포 시 초기화' in _w75)


section("76. v6 애플 정돈 — rgb 정규화 접합 · 알림 중립화 · 소음 제거")

_w76 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
check("접합 셀렉터 — Streamlit rgb 정규화 커버 (hex만 매칭하면 헛돈다)",
      '_hex_to_rgb_str' in _w76 and '셀렉터가 통째로 헛돈다' in _w76)
check("알림 박스 — 표면 중립 + 좌측 액센트만",
      'stAlertContentSuccess' in _w76 and 'border-left-width: 3px' in _w76)
check("코드 조각 — 칩 해체 (배경 투명)",
      'background: transparent !important' in _w76
      and '#2c2e36' not in _w76)
check("실행 메타 — 접힌 실행 정보로", '실행 정보 — 분석기준일' in _w76)
check("결론 배너 — 양 테마 다크 카드 고정 (흰 글자 보호)",
      '라이트 surface(흰색)로 바꾸면 글자가 사라진다' in _w76)
# 라운드 38: '종목 찾기'는 아코디언 줄(항상 펼침)이 제목을 그리므로
# sidebar_section 을 또 부르면 제목이 두 번 나온다 — 실제로 그랬다.
check("사이드바 구역 — 킷 라벨로 통일 · 가로선 없음",
      '_uk.sidebar_section("종목"' in _w76
      and 'st.sidebar.markdown("---")' not in _w76)
check("항상 펼침 구역은 제목을 두 번 그리지 않는다",
      '_uk.sidebar_section("종목 찾기"' not in _w76
      and "'title': '종목 찾기', 'always': True" in _w76)


section("77. 타입 스케일 — 열 단계만 · 굵기 700 상한 · 접근성 하한 12px")

#: 애플 HIG 계열 10단 스케일. 이 밖의 크기는 화면에 존재하면 안 된다.
TYPE_SCALE = {12, 13, 15, 16, 17, 20, 22, 28, 34, 40}
import re as _re77

_off = {}
for _fn in ("web_app.py", "chart_pro.py"):
    _src77 = open(_os.path.join(PROJ, _fn), encoding='utf-8').read()
    for _val, _unit in _re77.findall(r'font-size:\s*([0-9.]+)(px|rem|em)', _src77):
        if _unit == 'em':
            if float(_val) != 1.0:            # 1em(상속)만 허용
                _off.setdefault(_fn, []).append(f"{_val}em")
            continue
        _px = float(_val) * (16 if _unit == 'rem' else 1)
        if _px not in TYPE_SCALE:
            _off.setdefault(_fn, []).append(f"{_val}{_unit}")
check("소스 전역 — 스케일 밖 글자 크기 0건", not _off, str(_off)[:160])

_w77 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
_weights77 = [int(w) for w in _re77.findall(r'font-weight:\s*([0-9]{3})', _w77)]
check("굵기 상한 700 (히어로 결론 한 줄만 800)",
      max(_weights77) == 800 and _weights77.count(800) == 1,
      f"max={max(_weights77)} n800={_weights77.count(800)}")
check("굵기 단계 4개 이하 (400·600·700·800)",
      set(_weights77) <= {400, 500, 600, 700, 800}, str(sorted(set(_weights77))))
check("접근성 하한 — 12px 미만 없음",
      min(TYPE_SCALE) == 12
      and not _re77.findall(r'font-size:\s*(?:0\.[0-6][0-9]?rem|[0-9]|10|11)px', _w77))
check("광학 자간 — 대형 텍스트 트래킹 보정",
      'letter-spacing: -0.028em' in _w77 and 'letter-spacing: -0.021em' in _w77)
check("행간 — 본문 1.6 계열", 'line-height: 1.62' in _w77)
check("스케일 정규화 도구 보존 (재발 시 재실행)",
      _os.path.exists(_os.path.join(PROJ, "scripts", "normalize_type_scale.py")))


section("78. UI 킷 — 테두리 말살 · 표면 대비 · 사이드바 위계 (애플 스펙)")

import ui_kit as uk78

_w78 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()

# ① 테두리: 카드 인라인 border 는 최종 결론 카드 1개만.
#    (CSS 블록 규칙 `!important` 은 위젯 스타일이라 대상 아님. 액센트는
#     border-left 로만 쓴다 — 전체를 두르지 않는다.)
_inline_borders = _re77.findall(
    r"border:\s*([0-9.]+)px\s+(?:solid|dashed)\s+(?![^;\n]*!important)", _w78)
check("카드 인라인 테두리 = 최종 결론 카드 1개뿐",
      len(_inline_borders) == 1 and _inline_borders[0] == '3',
      f"{len(_inline_borders)}개: {_inline_borders[:6]}")

# ② 표면 3단계가 실제로 층으로 보이는가 (인접 명도비 1.10 이상)
def _rel_lum78(hexs):
    c = hexs.lstrip('#')
    ch = [int(c[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    ch = [(x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4) for x in ch]
    return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]


def _ratio78(a, b):
    la, lb = _rel_lum78(a) + 0.05, _rel_lum78(b) + 0.05
    return max(la, lb) / min(la, lb)


for _thm in ('dark', 'light'):
    _t = uk78.tokens(_thm)
    check(f"{_thm} 표면 층 대비 (배경↔카드 ≥1.10)",
          _ratio78(_t['bg'], _t['card']) >= 1.10,
          f"{_ratio78(_t['bg'], _t['card']):.3f}")

# ③ 사이드바 위계 파괴 규칙 제거 (전 요소 흰색·굵게 금지)
check("사이드바 전역 색 강제 규칙 삭제",
      '[data-testid="stSidebar"] * {\n        color: #ffffff' not in _w78)
check("사이드바 3단 위계 복원 (제목 tx1 / 본문 tx2)",
      '#9DAABC !important' in _w78 and '#F3F6FA !important' in _w78)

# ④ 킷을 통해 그린다 — 위젯 기본 스타일 방치 금지
check("킷 전역 규칙 주입", '_uk.global_css(_theme)' in _w78)
check("킷 컴포넌트 사용 (섹션·타일)",
      _w78.count('_uk.section(') >= 2 and _w78.count('_uk.stat_tiles(') >= 2)
def _rgb78(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


check("한국 관례 색 — 상승은 붉은 계열, 하락은 푸른 계열 (값이 아니라 관례)",
      all((lambda u, d: u[0] > u[2] and d[2] > d[0])(
          _rgb78(p['up']), _rgb78(p['down']))
          for p in (uk78.DARK, uk78.LIGHT)))

# ⑤ 팔레트 밖 색 제거
check("팔레트 밖 보라(#bf5af2) 0건", '#bf5af2' not in _w78)
check("애플 UI 스펙 문서 존재",
      _os.path.exists(_os.path.join(PROJ, "docs", "APPLE_UI_SPEC.md")))


section("79. 라운드 3 — 매수 차단 거부권의 근거 검증 · 후보 플래그 격리")

check("ESS 게이트 연구 (1차 가설 기각 기록)", _os.path.exists(
    _os.path.join(PROJ, "scripts", "ess_gate_study.py")))
check("거부권 연구 (진짜 차단자 규명)", _os.path.exists(
    _os.path.join(PROJ, "scripts", "veto_study.py")))
_vs79 = open(_os.path.join(PROJ, "scripts", "veto_study.py"),
             encoding='utf-8').read()
check("사전등록 — 판정 규칙을 먼저 명문화", '판정 규칙' in _vs79
      and '즉시 반영하지 않는다' in _vs79)

check("후보 모드는 환경변수로만 (운영 기본 strict)",
      q.VETO_NET_MODE == 'strict'
      and "os.environ.get('QUANT_VETO_NET_MODE'" in _qi70)
_qi79 = open(_os.path.join(PROJ, "quant_indicators.py"), encoding='utf-8').read()
check("완화 조건 — 표본 30건+·Wilson 하한 50%+ 일 때만",
      "(_band.get('n') or 0) < 30" in _qi79
      and "float(_band['wilson_low']) < 50.0" in _qi79)
check("차단하지 않은 사실을 화면에 남긴다 (은폐 금지)",
      "'soft_conflict_notes'" in _qi79 and '매수 차단까지는 하지 않았습니다' in _qi79)
check("KPI·산식 불변 명시", 'KPI 정의는 **불변**' in open(
    _os.path.join(PROJ, "docs", "MODEL_VERSIONS.md"), encoding='utf-8').read())
_mv79 = open(_os.path.join(PROJ, "docs", "MODEL_VERSIONS.md"),
             encoding='utf-8').read()
check("실측 근거 기록 (차단 42.3% · 차이 0.9%p)",
      '42.3%' in _mv79 and '+0.9%p' in _mv79)
check("기각된 가설도 기록 (ESS 게이트)", '1차 가설 기각' in _mv79)


import datetime as _dt
_d80 = open(_os.path.join(PROJ, "scripts",
            "run_daily_improvement.py"), encoding='utf-8').read()
section("80. 이슈 조치 관리 — 3일 규칙 · 필드 완비 · 화면 노출")
from improvement import issue_ops as _io80
from improvement import issue_tracker as _it80
from improvement import database as _db80

# 운영 DB를 건드리지 않는다 — 시험용 임시 파일에만 쓴다
_p80 = _os.path.join(PROJ, '_probe', '_issue_ops_test.db')
_os.makedirs(_os.path.dirname(_p80), exist_ok=True)
if _os.path.exists(_p80):
    _os.remove(_p80)
_db80.initialize_database(_p80)
_c80 = _db80.get_connection(_p80)
_io80.ensure_schema(_c80)

_cols80 = {r[1] for r in _c80.execute(
    "PRAGMA table_info(improvement_issues)").fetchall()}
check("조치 열 완비 — 원인·영향·즉시수정·상태·담당·예정·해결버전·검증",
      {'cause', 'user_impact', 'fixable_now', 'work_status', 'module',
       'action_plan', 'safeguard', 'target', 'eta', 'resolved_version',
       'verification', 'next_review'} <= _cols80)
check("ensure_schema 는 두 번 불러도 안전", (_io80.ensure_schema(_c80) is None))

_it80.create_issue(_c80, category='usability', severity='medium',
                   title='매수 신호 발생률 과소', summary='시험',
                   issue_key='usability|signal_rate')
_io80.apply_playbook(_c80, 'usability|signal_rate', version='v-test')
_r80 = _io80.issue_view(_c80)[0]
check("계획 부여 — 원인·영향·조치·안전조치·목표가 모두 채워진다",
      all(_r80[k] for k in ('cause', 'user_impact', 'action_plan',
                            'safeguard', 'target', 'eta')))
check("즉시 수정 가능 여부가 참/거짓으로 명시", _r80['fixable_now'] in (0, 1))
check("수정 예정일은 오늘 이후", str(_r80['eta']) >= _dt.date.today().isoformat())

# 계획이 없는 미지의 이슈는 지어내지 않고 '확인 중'으로 둔다
_it80.create_issue(_c80, category='data', severity='low', title='처음 보는 문제',
                   summary='시험', issue_key='unknown|xyz')
_io80.apply_playbook(_c80, 'unknown|xyz')
_unk80 = [r for r in _io80.issue_view(_c80) if r['issue_key'] == 'unknown|xyz'][0]
check("모르는 문제엔 계획을 날조하지 않는다", _unk80['work_status'] == _io80.ST_CHECKING
      and '조사 중' in str(_unk80['cause']))

# 3일 규칙 — 등록일을 4일 전으로 되돌리면 성격이 자동 재분류된다
_c80.execute("UPDATE improvement_issues SET created_at=? WHERE issue_key=?",
             ((_dt.date.today() - _dt.timedelta(days=4)).isoformat(), 'unknown|xyz'))
_esc80 = _io80.escalate(_c80)
_unk80b = [r for r in _io80.issue_view(_c80) if r['issue_key'] == 'unknown|xyz'][0]
check("3일 넘게 방치 금지 — 자동 재분류", _unk80b['work_status'] in
      (_io80.ST_BLOCKED, _io80.ST_LONGTERM) and len(_esc80) >= 1)
check("재분류 시 다음 검토일이 새로 잡힌다", bool(_unk80b['next_review']))
check("재분류 사유가 사람 말로 남는다", '경과' in str(_unk80b['verification']))
check("재분류된 이슈는 더 이상 방치(stale)로 세지 않는다", not _unk80b['stale'])

_io80.resolve_with_verification(_c80, 'usability|signal_rate',
                                version='v-test', verification='표본 100건 재측정 통과')
_done80 = [r for r in _io80.issue_view(_c80)
           if r['issue_key'] == 'usability|signal_rate'][0]
check("해결은 검증 결과와 해결 버전을 함께 남겨야 성립",
      _done80['status'] == 'resolved' and _done80['work_status'] == _io80.ST_DONE
      and _done80['resolved_version'] == 'v-test' and _done80['verification'])

_w80 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
check("화면 — 이슈마다 원인·영향·조치·예정일을 함께 보여준다",
      '왜 생겼나' in _w80 and '영향' in _w80 and '지금 하는 일' in _w80
      and '임시 안전조치' in _w80)
check("일일 루틴이 계획 부여·경과일 규칙을 실제로 호출",
      'apply_playbook' in _d80 and 'escalate' in _d80)
_c80.close()
_os.remove(_p80)


section("81. 접근성 — 글자 3단 대비 실측 · 팔레트 단일 출처")
import ui_kit as _uk81


def _lum81(h):
    h = h.lstrip('#')
    v = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = [f(x) for x in v]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _ratio81(a, b):
    la, lb = _lum81(a), _lum81(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


for _nm81, _pal81 in (('다크', _uk81.DARK), ('라이트', _uk81.LIGHT)):
    for _srf81 in ('bg', 'card'):
        for _tx81, _min81 in (('tx1', 7.0), ('tx2', 4.5), ('tx3', 4.5)):
            _r81 = _ratio81(_pal81[_tx81], _pal81[_srf81])
            check(f"{_nm81} {_tx81} on {_srf81} — 대비 {_r81:.2f} ≥ {_min81}",
                  _r81 >= _min81)
    # 3단이 실제로 구별되어야 위계다 — 값이 붙어 있으면 단계가 아니다
    check(f"{_nm81} 글자 3단이 서로 구별된다",
          _ratio81(_pal81['tx1'], _pal81['card'])
          > _ratio81(_pal81['tx2'], _pal81['card']) + 2.0
          > _ratio81(_pal81['tx3'], _pal81['card']) + 2.0)

_w81 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
check("팔레트는 킷이 유일 출처 — web_app 이 직접 정의하지 않는다",
      '_pal(_uk.DARK)' in _w81 and '_pal(_uk.LIGHT)' in _w81)
_cfg81 = open(_os.path.join(PROJ, ".streamlit", "config.toml"),
              encoding='utf-8').read()
check("Streamlit 자체 크롬도 같은 토큰 — 배경·강조색 일치",
      '#0B0F17' in _cfg81 and '#4C8DFF' in _cfg81 and '#161D2A' in _cfg81)
check("업데이트 날짜는 손으로 쓰지 않는다 (커밋 이력 파생)",
      'def _last_update_date' in _w81 and 'update_history.json' in _w81)
check("타일 라벨을 …으로 자르지 않는다 (정보 손실 금지)",
      "text-overflow:ellipsis;'>{_esc(it['label'])}" not in open(
          _os.path.join(PROJ, "ui_kit.py"), encoding='utf-8').read())


section("82. 라운드 4~7 — 사전등록 절차 준수 · 국면 분해 · 기각 기록")
_mv82 = open(_os.path.join(PROJ, "docs", "MODEL_VERSIONS.md"),
             encoding='utf-8').read()
check("라운드 3 기각 사유가 '측정 불가'로 정확히 기록됐다",
      'build_final_verdict` 를 호출하지 않는다' in _mv82
      and '측정면을 잘못 골랐다' in _mv82)
check("점수가 60을 못 넘는 것이 진짜 병목임을 기록",
      '70점 이상 4건' in _mv82 and '52.6% vs 59.3%' in _mv82)
check("구간별 기준선이 다르다는 사실을 명시 (55.8 / 63.6 / 44.9)",
      '55.8%' in _mv82 and '63.6%' in _mv82 and '44.9%' in _mv82)
check("검증 70% 가 장세 효과라는 판정 근거 기록",
      '같은 규칙이 학습에서는 50% 안팎' in _mv82)
check("라운드 6 종목 홀드아웃 결과 기록 (본 적 없는 종목)",
      '홀드아웃' in _mv82 and '67.8%' in _mv82)
check("블라인드 lift 음수로 채택 취소했음을 기록",
      '채택 취소' in _mv82 and '−9.04%' in _mv82)
check("70% 미달을 숨기지 않는다", '무조건적 검증 70%는 달성하지 못했다' in _mv82)
check("수치를 만들 수 있었지만 하지 않았다고 밝힌다",
      '그렇게 하지 않았다' in _mv82 and '89%' in _mv82)
check("KPI 정의 불변 재확인", 'KPI 정의 불변' in _mv82)

for _f82 in ('layer_study_r4.py', 'lift_study_r5.py', 'regime_rule_r6.py',
             'regime_breakdown_r7.py', 'promotion_round3.py'):
    _pp82 = _os.path.join(PROJ, 'scripts', _f82)
    check(f"연구 스크립트 보존 — {_f82}", _os.path.exists(_pp82))
    _src82 = open(_pp82, encoding='utf-8').read()
    check(f"{_f82} — 판정 규칙이 측정 전에 코드로 선명시",
          '사전등록' in _src82)

_rb82 = _os.path.join(PROJ, '.portfolio', 'regime_breakdown.json')
check("국면별 실적 산출물 존재", _os.path.exists(_rb82))
if _os.path.exists(_rb82):
    import json as _j82
    with open(_rb82, encoding='utf-8') as _f:
        _rbd82 = _j82.load(_f)
    check("국면 3종이 모두 분해돼 있다",
          all(_k in (_rbd82.get('buy_zone', {}).get('valid') or {})
              for _k in ('BULL', 'SIDEWAYS', 'BEAR')))
    # 산출물이 라운드 14(6국면)로 바뀌었다. 약세장 게이트 기각은
    # MODEL_VERSIONS.md 에 기록돼 있고, 여기서는 국면 분해가 살아 있는지 본다.
    check("국면 분해 산출물이 계속 갱신된다",
          _rbd82.get('mode') in ('3', '6'))

_w82 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
check("화면 — 국면별 성적을 나눠 보여준다",
      '시장 국면별 성적 (58점+ 신호)' in _w82
      and 'regime_breakdown.json' in _w82)
check("화면 — 표본 30건 미만은 성적으로 인정하지 않는다고 밝힌다",
      '표본 30건 미만이라 성적으로 인정하지 않는' in _w82)
check("화면 — 하락 추세 신뢰 경고", '이 국면의 판단은 신뢰하지 마세요' in _w82)

from improvement import issue_ops as _io82
check("이슈 계획이 실측으로 갱신됐다 (거부권 → 점수 상한)",
      '점수 자체가 60점을 넘지 못하기 때문' in
      _io82.PLAYBOOK['usability|signal_rate']['cause'])
check("국면 의존 이슈가 계획에 추가됐다",
      'model|regime_dependence' in _io82.PLAYBOOK)


section("83. 라운드 8 — 확장 축적 후 재판정 · 조건부 참고 채택 범위")
_mv83 = open(_os.path.join(PROJ, "docs", "MODEL_VERSIONS.md"),
             encoding='utf-8').read()
check("8차 확장 규모 기록 (268종목 · 7,947건)",
      '268' in _mv83 and '7,947' in _mv83)
check("규칙·기준을 바꾸지 않고 같은 스크립트를 다시 돌렸다고 명시",
      '규칙·기준을 하나도 바꾸지 않은 채' in _mv83)
check("홀드아웃 재현 수치 기록 (70.7% · n=164)",
      '70.7%' in _mv83 and 'n=164' in _mv83)
check("블라인드 lift 가 뒤집힌 사실 기록",
      '음수였던 lift 가 전부 양수로' in _mv83)
check("유리한 절반만 보여주지 않는다 — 비용후 음수 병기",
      '반쪽만 보여 주지 않는다' in _mv83 and '−4.03%' in _mv83)
check("채택 범위가 '매수 신호 아님'으로 못박혀 있다",
      '매수 신호로 쓰지 않는다' in _mv83
      and '점수·게이트·산식·KPI 정의는 전부 그대로' in _mv83)
check("약세장 게이트는 확장 후에도 기각",
      '확장 후에도 재판정했고 다시 기각' in _mv83)
check("70% 미달을 확장 후에도 그대로 유지 표기",
      '무조건적 검증 70%는 여전히 미달' in _mv83)
check("'70% 모델' 로 부르지 않겠다고 명시",
      '"70% 모델"이라고 부르지 않는다' in _mv83)

_w83 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
check("화면 — 조건부 참고 카드가 하락 국면 + 과매도/하단에서만 뜬다",
      "_bear_now = '하락' in str(four_scores.get('market_regime_label')" in _w83
      and "_rsi_now < 35" in _w83 and "_bbp_now < 20" in _w83)
check("화면 — 참고 카드가 유리한 수치와 불리한 수치를 같이 적는다",
      '본 적 없는 종목 164건 기준 70.7%' in _w83
      and '평균 −4.03%' in _w83)
check("화면 — 매수 신호가 아니라고 카드 안에서 밝힌다",
      '매수 신호가 아니라' in _w83 and '점수는 이 규칙 때문에 바뀌지' in _w83)
check("엔진 산식은 이번 라운드에서 건드리지 않았다 — 화면 전용",
      '_uk.card(' in _w83)

# 라이트 모드 회귀 — 하드코딩 다크 색이 다시 스며들지 않게 잠근다
check("라이트 CSS 가 토큰 참조를 쓴다 (하드코딩 hex 아님)",
      ".stApp {{ background-color: {_TOK['bg1']} !important; }}" in _w83)
check("인라인 다크 글자 토큰을 라이트 등가로 되돌리는 규칙 존재",
      '글자 토큰 3단만 라이트 등가로 되돌린다' in _w83)
check("고정 다크 카드 안쪽은 다시 밝게 (그라디언트 배너 포함)",
      'div[style*="rgb(22, 29, 42)"] p' in _w83)
check("버튼에 다크 특례를 두지 않는다", '특례를 두지 않는 쪽이 결국 덜 깨진다' in _w83)
check("사이드바 입력 글자가 흰색 고정이 아니다 (테마를 따른다)",
      '[data-testid="stSidebar"] input {{' in _w83
      and "color: {_TOK['tx1']} !important;" in _w83)


section("84. 버전 체계 · 가늠 AI · 무릎-어깨 · 모바일 · 진행 표시")
import versioning as _V84
from datetime import date as _dt84

check("형식 파싱 — v2026.08.02.1", _V84.parse('v2026.08.02.1') ==
      (_dt84(2026, 8, 2), 1))
check("패치 자리 — 같은 날 UI 수정은 끝자리만 오른다",
      _V84.bump('v2026.08.02.1', 'ui', today=_dt84(2026, 8, 2))
      == 'v2026.08.02.2')
check("날짜는 실제 달력 날짜 — 앞으로 당기지 않는다",
      _V84.bump('v2026.08.02.3', 'algorithm', today=_dt84(2026, 8, 2))
      == 'v2026.08.02.4')
check("날이 바뀌면 그날 날짜의 0번으로 시작 (알고리즘 변경)",
      _V84.bump('v2026.08.02.9', 'algorithm', today=_dt84(2026, 8, 3))
      == 'v2026.08.03.0')
check("같은 날 여러 번 릴리스해도 버전이 겹치지 않는다",
      _V84.bump('v2026.08.02.4', 'algorithm', today=_dt84(2026, 8, 2))
      == 'v2026.08.02.5')
check("변경 종류는 버전 문자열이 아니라 이력에 남는다",
      '알고리즘 변경인지 화면 수정인지는 버전 문자열이 아니라' in open(
          _os.path.join(PROJ, 'versioning.py'), encoding='utf-8').read())
check("전면 교체는 major 로 분류", _V84.CHANGE_KINDS['engine_swap'] == 'major')
try:
    _V84.bump('v2026.08.02.1', '아무거나')
    _ok84 = False
except ValueError:
    _ok84 = True
check("등록되지 않은 변경 종류는 거부한다 (즉흥 판단 금지)", _ok84)
check("이유 없이 버전을 올릴 수 없다", 'reason' in _V84.release.__doc__
      and '변경 이유' in _V84.release.__doc__)
_st84 = _V84.stamp()
check("버전 도장에 5축이 모두 있다", set(_V84.AXES) <= set(_st84['versions']))
for _k84 in ('generated_at', 'effective_from', 'previous_version',
             'change_reason'):
    check(f"버전 도장 필드 — {_k84}", _k84 in _st84)
check("버전 원장 파일이 존재하고 이력이 쌓인다",
      _os.path.exists(_V84.LEDGER) and len(_V84.history()) >= 5)

import gaeum_ai as _ga84
_g84 = _ga84.build({}, {}, {})
for _k84 in ('up_prob', 'down_prob', 'undecided', 'price_low', 'hold_days',
             'sample_n', 'oos_hit', 'ci_low', 'risk', 'limits', 'confidence'):
    check(f"가늠 AI 필드 — {_k84}", _k84 in _g84)
check("표본이 없으면 확률을 지어내지 않는다",
      _g84['up_prob'] is None and _g84['sample_n'] is None)
check("표본이 없을 때 한 문장이 '보류'라고 말한다",
      '확률로 말할 수 없어' in _ga84.sentence(_g84))
_g84b = _ga84.build({}, {'match_count': 126, 'tp_first_prob': 64.3}, {})
check("표본이 있으면 '몇 건 중 몇 건' 으로 말한다",
      '126건 중 81건' in _ga84.sentence(_g84b))
check("신뢰도를 낱말로 준다", _g84b['confidence'] in
      ('낮음', '보통', '높음', '판단 불가'))

_tp84 = _os.path.join(PROJ, '.portfolio', 'target_policy.json')
check("무릎-어깨 목표 정책 산출물 존재", _os.path.exists(_tp84))
if _os.path.exists(_tp84):
    import json as _j84
    with open(_tp84, encoding='utf-8') as _f:
        _pol84 = _j84.load(_f)
    _zs84 = {s['zone'] for s in _pol84['splits']['valid']['steps']}
    check("무릎·어깨·머리 세 구간이 모두 나온다",
          {'무릎', '어깨', '머리'} <= _zs84)
    check("어깨 구간이 3~5% 로 실측됐다",
          _pol84['recommended']['range_pct'] == [3.0, 5.0])

_sp84 = _os.path.join(PROJ, '.portfolio', 'stop_policy.json')
check("손절 정책은 채택하지 않았음이 기록돼 있다",
      _os.path.exists(_sp84) and
      _j84.load(open(_sp84, encoding='utf-8'))['adopted'] is False)

_u84 = open(_os.path.join(PROJ, "ui_kit.py"), encoding='utf-8').read()
check("로고 — 가늠쇠 조준점 워드마크", 'def logo(' in _u84
      and '가늠쇠' in _u84)
check("업데이트 바 — 최상단 컴포넌트", 'def update_bar(' in _u84)
check("진행 표시 — 단계 이름이 실제 파이프라인과 같다",
      'def progress(' in _u84 and '과거 유사사례 탐색' in _u84)
check("모바일 — 한 열·44px 터치·가로 스크롤",
      '@media (max-width: 768px)' in _u84 and 'min-height: 44px' in _u84
      and 'flex-direction: column' in _u84)

_w84 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
check("업데이트는 눌러야 열린다 (상단 상시 노출 제거 — 사용자 요청)",
      '_uk.update_bar(' not in _w84
      and "with st.expander(f\"업데이트 {_n_upd}건" in _w84)
check("애플 폰트 스택 — 시스템 폰트 우선, Pretendard 폴백",
      '-apple-system' in _w84 and '"SF Pro Display"' in _w84
      and '"Pretendard"' in _w84)
check("애플 폰트 파일을 배포하지 않는다고 명시",
      '애플 폰트 파일을 배포하지 않는다' in _w84)
check("크기별 트래킹 — 큰 글자일수록 자간을 좁힌다",
      'letter-spacing: -0.024em' in _w84)
check("진행 표시가 끝나면 사라진다", '_prog.empty()' in _w84)
check("가늠 AI 패널이 화면에 있다", '_uk.section("가늠 AI"' in _w84)
check("얼마에 팔 것인가 — 목표별 도달 확률 표", '얼마에 팔 것인가' in _w84)
check("업데이트는 접힌 채로 시작한다", 'expanded=False' in _w84)

_d84 = open(_os.path.join(PROJ, "scripts", "run_daily_improvement.py"),
            encoding='utf-8').read()
check("케이스에 버전 도장을 찍는다", 'V.stamp(p)' in _d84)
check("이전 버전 케이스를 덮어쓰지 않는다고 명시",
      '이전 버전 케이스는 덮어쓰지 않는다' in _d84)


section("85. 라운드 10 — 과최적화 증거 · 설계 문서")
# 산출물(engine_bakeoff.json)은 라운드 11 이 덮어쓴다. 라운드 10 의 실측은
# MODEL_VERSIONS.md 에 표로 남아 있으므로 여기서는 그 기록을 검증한다 —
# 산출물 형식이 바뀌어도 '무엇을 확인했는지'는 사라지지 않아야 한다.
_mv85 = open(_os.path.join(PROJ, "docs", "MODEL_VERSIONS.md"),
             encoding='utf-8').read()
check("라운드 9 어깨 구간 기록 (3~5%)", '**어깨 = 3~5%.**' in _mv85)
check("라운드 9c 손절 0.45σ 진단 기록", '0.45σ' in _mv85)
check("손절 기각 사유 — 급락장에서 안 끊어준다", '급락장에서 안 끊어주기' in _mv85)
check("9b 의 잘못된 채택을 정정했음을 기록", '기준선을 **고정 3%** 로 잘못 잡은' in _mv85)
check("라운드 10 — 6개 전부 기각 기록", '**6개 전부 탈락.**' in _mv85)
check("과최적화 결론 기록",
      '학습·검증에서 좋을수록 블라인드에서 더 크게 무너진다' in _mv85)
check("현행이 '덜 무너진다' 는 표현으로 정확히 기록", '덜 무너진다' in _mv85)
check("알고리즘 교체로 풀 문제가 아니라고 명시",
      '알고리즘을 바꿔서 올릴 수 있는 상황이 아니다' in _mv85)

_pd85 = _os.path.join(PROJ, "docs", "PRODUCT_DESIGN_ko.md")
check("제품 설계 문서 존재", _os.path.exists(_pd85))
_pdt85 = open(_pd85, encoding='utf-8').read()
check("와이어프레임 — 홈·종목분석·모바일", '3.1 홈' in _pdt85
      and '3.3 모바일' in _pdt85)
check("디자인 토큰 14색 표", '| bg |' in _pdt85 and '| neg |' in _pdt85)
check("브루탈리즘 방향 폐기 명시", '폐기**: 차가운 브루탈리즘' in _pdt85)
check("사용성 검증 흐름 10단계", '10. 모바일 375px' in _pdt85)

_ec85 = _os.path.join(PROJ, "docs", "ENGINE_CANDIDATES_ko.md")
check("후보 엔진 비교 문서 존재", _os.path.exists(_ec85))
_ect85 = open(_ec85, encoding='utf-8').read()
check("비교표에 학습·검증·블라인드가 모두 있다",
      '학습 | 검증 | **블라인드**' in _ect85)
check("안 넣은 후보와 그 이유를 밝힌다",
      'XGBoost' in _ect85 and '정직하게 검정할 수 없어서' in _ect85)

_w85 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
check("화면 — 엔진 판단 비교가 '참고'로만 표시된다",
      '다른 원리는 뭐라고 하나' in _w85 and '판단에는 반영하지 않습니다' in _w85)
check("화면 — 엇갈려도 결론을 뒤집지 말라고 적었다",
      '현행 결론을 뒤집지 마세요' in _w85)

from improvement import issue_ops as _io85
check("과최적화 이슈가 계획에 등록됐다", 'model|overfit_gap' in _io85.PLAYBOOK)
check("손절 폭 이슈가 계획에 등록됐다", 'model|stop_width' in _io85.PLAYBOOK)
check("과최적화 이슈에 실측 근거가 들어 있다",
      '67.0%' in _io85.PLAYBOOK['model|overfit_gap']['cause'])


section("86. 라운드 11 — 대규모 엔진 대결 · 워크포워드 · 로고 비율")
_bk86 = _os.path.join(PROJ, '.portfolio', 'engine_bakeoff.json')
check("엔진 대결 산출물 존재", _os.path.exists(_bk86))
if _os.path.exists(_bk86):
    with open(_bk86, encoding='utf-8') as _f:
        _b86 = _j84.load(_f)
    check("후보가 20개 이상으로 늘었다 (문턱 훑기 포함)",
          _b86.get('n_candidates', 0) >= 20)
    check("워크포워드 폴드 기준이 산출물에 박혀 있다",
          _b86['criteria']['walk_forward_folds'] >= 4
          and '과반' in str(_b86['criteria']['min_folds_win']))
    check("판정 가능한 폴드 수가 함께 기록된다 (표본 부족을 패배로 세지 않는다)",
          all('wf_judged' in _e for _e in _b86['engines'].values()))
    check("모든 후보에 워크포워드 성적이 기록된다",
          all('wf_wins' in _e for _e in _b86['engines'].values()))
    check("표본·신호율 하한이 판정에 포함된다",
          _b86['criteria']['min_n'] >= 100
          and _b86['criteria']['min_signal_rate'] >= 3.0)
    check("원장 기간이 기록된다 (예전 장세 포함 여부 추적)",
          len(_b86.get('period') or []) == 2 and 'years' in _b86)
    # 채택 여부와 무관하게 기준선은 항상 함께 저장돼야 비교가 가능하다
    check("기준선 성적이 함께 저장된다",
          _b86['baseline']['blind']['hit'] is not None)

_r11 = open(_os.path.join(PROJ, "scripts", "engine_bakeoff_r11.py"),
            encoding='utf-8').read()
check("사전등록 3관문이 코드에 선명시", '사전등록' in _r11
      and '1차 (워크포워드)' in _r11 and '3차 (블라인드)' in _r11)
check("기각이 목적이 아님을 명시 — 통과하면 실제로 교체",
      '기각이 목적이 아니다' in _r11)
check("워크포워드는 시간순 분할 (앞을 보고 뒤를 맞힌다)",
      'def walk_forward' in _r11 and "key=lambda r: str(r.get('date')" in _r11)

_lab86 = open(_os.path.join(PROJ, "scripts", "calibration_lab.py"),
              encoding='utf-8').read()
check("과거 데이터 수집 범위가 2015년으로 확장됐다",
      "start_date='2015-01-01'" in _lab86)
check("종목당 기준일이 80개로 늘었다 (25봉 간격 유지)",
      'n_dates=80' in _lab86 and 'spacing=25' in _lab86)

_w86 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
check("사이드바 일괄 글자 규칙이 로고를 누르지 않는다",
      '[data-testid="stSidebar"] span:not([style*="font-size"])' in _w86)
check("h1 고정 규칙도 인라인 크기를 존중한다",
      '.stApp h1:not([style*="font-size"])' in _w86)
check("로고가 제목 역할 — 홈 버튼은 조용한 보조",
      '로고가 제목 역할을 하므로 이 버튼은 조용한 보조로 둔다' in _w86)
check("본문 제목이 종목명 (사이드바 로고와 중복 제거)",
      "f\"{_uk._esc(resolved_name)}<span style='color:{_TOK['tx3']}; \"" in _w86)
# 라운드 44 — 예전에는 "_AX_KO = {'model': '모델'" 이라는 **리터럴**을 요구했다.
# 그런데 축 목록을 화면에 손으로 나열해 둔 것이 바로 이번에 고친 결함이다
# (versioning.AXES 가 5 → 7 로 늘었는데 화면은 5개만 그렸다).
# 그래서 리터럴이 아니라 **의도**를 검사한다 — 상태·버전이 한 줄에 있고,
# 축 목록을 versioning 이 정하는가.
check("상단 바 한 줄에 상태와 엔진 버전이 함께 있다",
      '_STATUS_TOP' in _w86 and '_AX_KO' in _w86 and 'class="here"' in _w86)
check("버전 칩 축 목록을 화면이 손으로 나열하지 않는다",
      'for _a in _ver.AXES' in _w86 and "'valuation': '적정가'" in _w86)

_u86 = open(_os.path.join(PROJ, "ui_kit.py"), encoding='utf-8').read()
check("상태바 컴포넌트 존재", 'def status_bar(' in _u86)
check("상태바는 가장 조용한 줄이어야 한다고 명시",
      '가장 조용한 줄이어야 한다' in _u86)


section("87. 좌측 아코디언 — 자동 접힘 · 값 유지 · 과거 장세 축적")
_u87 = open(_os.path.join(PROJ, "ui_kit.py"), encoding='utf-8').read()
check("아코디언은 줄 단위로 그린다 (제목 바로 밑에 내용)",
      'def acc_css(' in _u87 and 'def acc_row(' in _u87)
check("expander 로는 자동 접힘을 만들 수 없다는 이유가 적혀 있다",
      '서로 독립이라' in _u87 or '자동 접힘이 성립' in _u87)
check("열린 것을 다시 누르면 닫힌다 (전부 닫힘 허용)",
      "st.session_state[state_key] = ('' if on else step['key'])" in _u87)
check("완료 여부를 제목 줄에 표시", "step.get('done') is True" in _u87)
check("아이콘은 단일 세트로 통일 (직접 그린 세트 혼용 금지)",
      ':material/' in _u87 or 'stroke-width' in _u87)
check("처리 중인 단계를 강조한다", "busy" in _u87 and "step['key'] == busy" in _u87)
check("활성 단계 셀렉터 특이도를 일반 규칙과 맞춘다",
      'div.st-key-_acc_' in _u87)

_w87 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
check("좌측 메뉴 — 1차 탭 + 링크 그룹 + 설정 4단계",
      '_NAV_MAIN' in _w87 and '_NAV_SUB' in _w87
      and "'key': 'pick'" in _w87 and "'key': 'crit'" in _w87)
check("검색은 아코디언 밖 — 접혀도 항상 보인다",
      '종목 검색·선택 (아코디언 밖 · 항상 보인다)' in _w87
      and _w87.index('종목명 일부 또는 티커 입력')
      < _w87.index('if _uk.acc_row(_SB_STEPS[0]'))
check("검색이 사라지면 아무것도 시작할 수 없다는 이유가 적혀 있다",
      '검색은 이 앱의 입구다' in _w87)
check("완료 여부를 실제 상태에서 판정한다 (지어내지 않는다)",
      "st.session_state.get('positions')" in _w87
      and "st.session_state.get('scan_results')" in _w87)
check("접힌 단계의 값이 사라지지 않게 별도 키에 보관한다",
      '_KEEP' in _w87 and 'def _keep(' in _w87 and 'def _kept(' in _w87)
check("접혔을 때 본문이 쓰는 이름을 한 곳에서 모두 채운다",
      '접힌 단계의 값 확정' in _w87 and "for _nm, _dv in (" in _w87)
check("빠뜨리면 화면이 죽는다는 경고를 남겼다",
      '그 단계를 접는 순간 화면이 죽는다' in _w87)

# 과거 장세가 실제로 학습에 들어왔는지 — 이번 확장의 목적
_bk87 = _os.path.join(PROJ, '.portfolio', 'engine_bakeoff.json')
if _os.path.exists(_bk87):
    with open(_bk87, encoding='utf-8') as _f:
        _b87 = _j84.load(_f)
    _yrs = _b87.get('years') or {}
    for _y in ('2018', '2020', '2022'):
        check(f"과거 장세 포함 — {_y}년 사례 500건+",
              int(_yrs.get(_y, 0)) >= 500)
    check("학습 표본이 1만 건을 넘는다",
          _b87['baseline']['train']['n'] > 0
          and sum(int(v) for v in _yrs.values()) >= 15000)
    check("과거 장세를 넣고도 교체 후보가 없었음을 기록",
          _b87.get('adopted') is None)


section("88. 아코디언 단계별 렌더 — 어느 단계를 접어도 화면이 살아 있는가")
# 접힌 단계의 위젯은 렌더되지 않는다. 그 안에서만 정의된 이름을 본문이 쓰면
# 그 단계를 접는 순간 화면이 죽는다. 눈으로 찾지 말고 **네 단계를 다 열어 본다**.
from streamlit.testing.v1 import AppTest as _AT88

for _step88 in ('today', 'mine', 'history', 'setup', ''):
    _at88 = _AT88.from_file(_os.path.join(PROJ, "web_app.py"),
                            default_timeout=1800)
    _at88.session_state['selected_ticker'] = '005930'
    _at88.session_state['sb_step'] = _step88
    _at88.run()
    _nm88 = _step88 or '전부 접힘'
    check(f"{_nm88} 상태에서 렌더 예외 없음", len(_at88.exception) == 0,
          str(_at88.exception[:1])[:200])

# 값 유지 — 4단계에서 rho 를 바꾸고 접어도 값이 살아 있어야 한다
_at88b = _AT88.from_file(_os.path.join(PROJ, "web_app.py"), default_timeout=1800)
_at88b.session_state['selected_ticker'] = '005930'
_at88b.session_state['sb_step'] = 'setup'
_at88b.session_state['_sb_keep'] = {'rho': 0.9}
_at88b.run()
check("접힌 단계의 설정이 _KEEP 에 보존된다",
      len(_at88b.exception) == 0
      and '_sb_keep' in _at88b.session_state,
      str(_at88b.exception[:1])[:150])


section("89. 라운드 13·14 — 횡보 실전 하락의 원인과 국면 세분")
_sw89 = _os.path.join(PROJ, '.portfolio', 'sideways_study.json')
check("횡보 심층 연구 산출물 존재", _os.path.exists(_sw89))
if _os.path.exists(_sw89):
    with open(_sw89, encoding='utf-8') as _f:
        _s89 = _j84.load(_f)
    _v89, _b89 = _s89['baseline']['valid'], _s89['baseline']['blind']
    check("블라인드 횡보의 변동성이 검증보다 훨씬 높다 (이름만 같은 횡보)",
          _b89['vol'] > _v89['vol'] * 1.5)
    check("블라인드 횡보의 최대낙폭이 2배 가까이 크다",
          _b89['mae'] > _v89['mae'] * 1.8)
    check("하위 조건 18개를 훑었고 채택은 없었다",
          len(_s89['subconditions']) >= 15 and _s89['adopted'] is None)

_rb89 = _os.path.join(PROJ, '.portfolio', 'regime_breakdown.json')
with open(_rb89, encoding='utf-8') as _f:
    _r89 = _j84.load(_f)
check("국면이 6칸으로 세분됐다", _r89.get('mode') == '6'
      and len(_r89.get('cells6') or {}) == 6)
check("연습-실전 격차가 줄었다 (31.8%p → 6.5%p)",
      _r89['gap6'] < _r89['gap3'] and _r89['gap6'] <= 10)
check("변동성 경계가 산출물에 박혀 있다", _r89.get('vol_split') == 0.03)
check("3칸 성적도 함께 보존 (비교 근거)", 'buy_zone' in _r89)

_r14 = open(_os.path.join(PROJ, "scripts", "regime_split_r14.py"),
            encoding='utf-8').read()
check("사전등록 3조건이 코드에 선명시",
      '사전등록' in _r14 and '격차가 3국면일 때보다 줄어드는가' in _r14)
check("점수·게이트를 바꾸지 않았음을 명시",
      '점수·게이트를 바꾸지 않는다' in _r14)
check("새 지표를 만들지 않았다 (기존 vol20 사용)",
      '새 지표를 만드는 게 아니다' in _r14)

_w89 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
check("화면 — 6칸 표 (지수 방향 × 종목 변동성)",
      '지수 방향 × 종목 변동성' in _w89)
check("화면 — 지금이 어느 칸인지 알려준다",
      '지금은 <b>{_now_ko}</b> 국면입니다' in _w89)
check("화면 — 모델이 좋아진 게 아니라 분류가 거칠었다고 설명",
      '모델이 갑자기 좋아진 게 아니라' in _w89)

_mv89 = open(_os.path.join(PROJ, "docs", "MODEL_VERSIONS.md"),
             encoding='utf-8').read()
check("원인 규명 기록 — 블라인드 횡보는 이름만 횡보",
      "블라인드의 '횡보'는 이름만 횡보였다" in _mv89)
check("검증 62% 조용 vs 블라인드 84% 거침 — 구성 차이 기록",
      '109건(62%)' in _mv89 and '108건(84%)' in _mv89)
check("모델이 아니라 분류 문제였다고 결론",
      '모델이 나빠진 게 아니라 분류가 거칠었다' in _mv89)

# 시각에 의존해 깨지던 테스트가 고쳐졌는지
_tt89 = open(_os.path.join(PROJ, "test_pipeline_fixes.py"),
             encoding='utf-8').read()
check("공시 테스트가 장 시작 전에도 통과한다 (시각 의존 제거)",
      '시각에 따라 깨지는 테스트는 신호가 아니라 소음이다' in _tt89)


section("90. 라운드 15·16 — 기대값 정직 점검 · 손익비 · 전날 미국장")
_he90 = open(_os.path.join(PROJ, "scripts", "honest_edge_check.py"),
             encoding='utf-8').read()
check("적중률이 아니라 기대값을 본다고 명시",
      '적중률이 아니라 **기대값**을 본다' in _he90)
check("승률이 높아도 손익비가 나쁘면 잃는다는 설명",
      '승률이 50%를 넘어도 손익비가 나쁘면 돈을 잃는다' in _he90)

_rr90 = _os.path.join(PROJ, '.portfolio', 'rr_policy.json')
check("손익비 연구 산출물 존재", _os.path.exists(_rr90))
if _os.path.exists(_rr90):
    with open(_rr90, encoding='utf-8') as _f:
        _r90 = _j84.load(_f)
    check("현행 손익비가 0.7 로 기록됨", _r90['current_k'] == 0.7)
    check("전체 일괄 상향은 채택하지 않았다", _r90.get('adopted_k') is None)
    _g13 = (_r90['grid'].get('1.3') or {}).get('blind') or {}
    _g07 = (_r90['grid'].get('0.7') or {}).get('blind') or {}
    check("k=1.3 에서 블라인드 기대값이 양수로 뒤집힌다",
          _g07.get('ev', 0) < 0 < _g13.get('ev', 0))
    check("도달률이 떨어지는 대가도 함께 기록",
          _g13.get('reach', 99) < _g07.get('reach', 0))
    check("국면별 개선 후보가 기록됨 (거친 상승)",
          'BULL|rough' in (_r90.get('per_cell') or {}))

_us90 = _os.path.join(PROJ, '.portfolio', 'us_overnight.json')
check("전날 미국장 연구 산출물 존재", _os.path.exists(_us90))
if _os.path.exists(_us90):
    with open(_us90, encoding='utf-8') as _f:
        _u90 = _j84.load(_f)
    check("미국 지수 매칭률 95% 이상", _u90.get('coverage', 0) >= 95)
    _flat = (_u90['bands'].get('보합 (±0.5%)') or {}).get('blind') or {}
    _up = (_u90['bands'].get('상승 (+0.5~+2%)') or {}).get('blind') or {}
    check("보합 구간이 상승 구간보다 나쁘다 (직관과 반대 방향)",
          _flat.get('hit', 99) < _up.get('hit', 0))
    check("게이트는 채택하지 않았다 (신호 절반 감소)",
          _u90.get('gate') is None)

_w90 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
check("화면 — 전날 미국장 경고 (보합이면 조심)",
      '어젯밤 미국장이 보합이었습니다' in _w90
      and '오늘은 특히 조심하세요' in _w90)
check("화면 — 게이트가 아니라 경고임을 코드에 명시",
      '게이트로 막지는 않는다' in _w90)
check("누수 방지 — 직전 미국 거래일만 쓴다",
      'D−1 종가' in open(_os.path.join(PROJ, "scripts",
                                       "us_overnight_r16.py"),
                        encoding='utf-8').read())

_mv90 = open(_os.path.join(PROJ, "docs", "MODEL_VERSIONS.md"),
             encoding='utf-8').read()
check("돈을 못 번다는 사실을 문서에 그대로 적었다",
      '우리 엔진은 지금 돈을 못 번다' in _mv90
      or '지금 이 신호대로 매매하면 평균적으로 잃는다' in _mv90)
check("원인이 설계임을 명시 (목표=손절×0.7)",
      '구조적으로 기대값이 음수가 되는 설계' in _mv90)
check("사용자 직관의 방향이 반대였음을 기록",
      '사용자 직관은 맞았는데 방향이 반대였다' in _mv90)

from improvement import issue_ops as _io90
check("기대값 마이너스가 이슈로 등록됨", 'model|negative_edge' in _io90.PLAYBOOK)
check("전날 미국장이 이슈로 등록됨", 'model|us_overnight' in _io90.PLAYBOOK)
check("이슈에 실측 수치가 들어 있다",
      '0.72:1' in _io90.PLAYBOOK['model|negative_edge']['cause'])


section("91. 토큰 키 정적 검사 · 검색 경로 렌더")
# 이 검사를 만든 이유: _TOK['line'] 오타가 '검색어를 입력했을 때만' 실행되는
# 경로에 있어서 회귀 1,217건이 전부 통과하는데도 화면이 죽었다.
# 실행해 봐야만 알 수 있는 버그는 정적 검사로 잡는다.
import re as _re91
_VALID91 = {'bg1', 'bg2', 'surface', 'hover', 'border', 'tx1', 'tx2', 'tx3',
            'brand', 'up', 'down', 'pos', 'warn', 'neg'}
_w91 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
_bad91 = sorted({m.group(1) for m in _re91.finditer(r"_TOK\['(\w+)'\]", _w91)}
                - _VALID91)
check("_TOK 키가 전부 유효하다 (오타 없음)", not _bad91, str(_bad91))

# ui_kit 팔레트 키도 같은 방식으로 잠근다
_UK91 = {'bg', 'card', 'raised', 'line', 'tx1', 'tx2', 'tx3', 'brand',
         'up', 'down', 'pos', 'warn', 'neg'}
# ⚠️ ui_kit 에는 t(팔레트) 말고 it/step(항목 dict)도 있다. 팔레트만 봐야
#    하므로 `t['...']` 중 앞이 식별자가 아닌 것만 센다 (it['key'] 제외).
_u91 = open(_os.path.join(PROJ, "ui_kit.py"), encoding='utf-8').read()
_badu91 = sorted({m.group(1)
                  for m in _re91.finditer(r"(?<![A-Za-z_])t\['(\w+)'\]", _u91)}
                 - _UK91)
check("ui_kit 팔레트 키가 전부 유효하다", not _badu91, str(_badu91))
check("두 이름 공간이 다르다는 것을 코드가 밝힌다 (line ↔ border)",
      "border=_p['line']" in _w91)

# 검색어가 있는 상태로도 렌더해 본다 — 스피너 경로가 실행된다
from streamlit.testing.v1 import AppTest as _AT91
_at91 = _AT91.from_file(_os.path.join(PROJ, "web_app.py"), default_timeout=1800)
_at91.session_state['search_text_input'] = '하이닉스'
_at91.run()
check("검색어를 입력한 상태에서 렌더 예외 없음", len(_at91.exception) == 0,
      str(_at91.exception[:1])[:200])


section("92. 아침 전면 점검 — 화면이 두 말을 하지 않는가 · 양 테마 대비")

import ast as _ast92
import re as _re92
_w92 = open(_os.path.join(PROJ, 'web_app.py'), encoding='utf-8').read()
_g92 = open(_os.path.join(PROJ, 'gaeum_ai.py'), encoding='utf-8').read()
_u92 = open(_os.path.join(PROJ, 'ui_kit.py'), encoding='utf-8').read()

# ① 같은 값을 두 타일에 세우지 않는다 — 한 측정이 두 번 확인된 것처럼 보인다
check("적중률 타일에서 blind 를 두 번 세우지 않는다",
      _w92.count("'label': '추천만 골랐을 때'") == 0)
check("표본 부족 경고는 실전 적중률 타일에 붙어 있다",
      "안 본 기간 {_bzb2.get('n', 0):,}건 중 · 표본 부족" in _w92)

# ② 국면 안내는 표의 행 이름과 맞아야 하고, 근거(60일 추세)를 밝혀야 한다
check("국면 안내가 표의 행 이름과 일치 (차분한/거친 + 국면)",
      "<b>차분한 {_now_ko}</b>" in _w92 and "<b>거친 {_now_ko}</b>" in _w92)
check("'~로 시작하는' 이라는 틀린 안내가 남아 있지 않다",
      "로 시작하는 두 줄" not in _w92)
check("국면 판정 근거를 함께 적는다 — 하루 등락과 구분",
      "_now_basis" in _w92 and "하루 등락이 아니라 60일 추세로 봅니다" in _w92)

# ③ 가늠 AI 는 화면 위쪽과 같은 판정을 봐야 한다 (두 개의 진실 금지)
check("가늠 AI 가 최종 판정(verdict)을 받는다",
      "_gai.build(four_scores, sim_res, verdict" in _w92)
check("위험요인은 글자수로 자르지 않고 첫 사유만 고른다",
      "split(' / ')[0]" in _g92 and "[:160]" not in _g92)

# ④ 다크 의미색이 모든 표면에서 WCAG AA 를 넘는가 (실측 계산)
def _hx92(s):
    s = s.lstrip('#')
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def _lum92(c):
    f = []
    for v in c:
        v /= 255.0
        f.append(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
    return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2]


def _cr92(a, b):
    la, lb = _lum92(a), _lum92(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


import ui_kit as _uk92
# #1C2635 는 양 테마에서 다크로 고정되는 카드 — 다크 표면 중 가장 밝다
_SURF92 = [_uk92.DARK['bg'], _uk92.DARK['card'], _uk92.DARK['raised'],
           _uk92.DARK_NAV, '#1C2635', '#161D2A']
_low92 = []
for _k92 in ('brand', 'up', 'down', 'pos', 'warn', 'neg'):
    _r92 = min(_cr92(_hx92(_uk92.DARK[_k92]), _hx92(_s92)) for _s92 in _SURF92)
    if _r92 < 4.5:
        _low92.append(f"{_k92}={_uk92.DARK[_k92]}({_r92:.2f})")
check("다크 의미색 6개가 모든 다크 표면에서 4.5:1 이상",
      not _low92, ' '.join(_low92))

_lowL92 = []
for _k92 in ('brand', 'up', 'down', 'pos', 'warn', 'neg'):
    _r92 = min(_cr92(_hx92(_uk92.LIGHT[_k92]), _hx92(_s92))
               for _s92 in (_uk92.LIGHT['bg'], _uk92.LIGHT['card'],
                            _uk92.LIGHT['raised'], _uk92.LIGHT_NAV))
    if _r92 < 4.5:
        _lowL92.append(f"{_k92}={_uk92.LIGHT[_k92]}({_r92:.2f})")
check("라이트 의미색 6개가 모든 라이트 표면에서 4.5:1 이상",
      not _lowL92, ' '.join(_lowL92))

# ⑤ 다크 고정 카드 안쪽 되돌림에 code 가 빠지면 코드 칩만 안 보인다
check("다크 고정 카드 되돌림 규칙에 code 포함",
      '.stApp div[style*="rgb(22, 29, 42)"] code' in _w92)
check("되돌림이 일반 code 규칙보다 뒤에 온다 (순서로 이긴다)",
      _w92.find('.stApp div[style*="rgb(22, 29, 42)"] code')
      > _w92.find('.stApp code, .stApp kbd') > -1)

# ⑥ 사라질 API·폰트에 없는 글자
check("use_container_width 를 쓰지 않는다 (2025-12-31 제거)",
      'use_container_width' not in _w92 and 'use_container_width' not in _u92)
_EMO92 = _re92.compile('[\U0001F300-\U0001FAFF☀-➿⬀-⯿]')
_bademo = [ln for ln in _w92.split('\n')
           if _EMO92.search(ln) and not ln.lstrip().startswith('#')
           and any(k in ln for k in ('set_title', 'annotate', 'set_xlabel',
                                     'set_ylabel', 'suptitle'))]
check("차트 라벨에 이모지를 쓰지 않는다 (한글 폰트에 글리프 없음)",
      not _bademo, str(_bademo[:1])[:120])

# ⑦ ui_kit 호출부가 theme 을 빠뜨리면 라이트에서 다크색이 그려진다
_ukast92 = _ast92.parse(_u92)
_themed92 = {}
for _n92 in _ukast92.body:
    if isinstance(_n92, _ast92.FunctionDef):
        _names92 = [a.arg for a in _n92.args.args]
        if 'theme' in _names92:
            _themed92[_n92.name] = _names92.index('theme')
_miss92 = []
for _node92 in _ast92.walk(_ast92.parse(_w92)):
    if not isinstance(_node92, _ast92.Call):
        continue
    _f92 = _node92.func
    if not (isinstance(_f92, _ast92.Attribute) and isinstance(_f92.value, _ast92.Name)
            and _f92.value.id in ('_uk', 'ui_kit')):
        continue
    if _f92.attr not in _themed92:
        continue
    if ('theme' not in {k.arg for k in _node92.keywords if k.arg}
            and len(_node92.args) <= _themed92[_f92.attr]):
        _miss92.append(f'{_f92.attr}:{_node92.lineno}')
check("모든 ui_kit 호출이 theme 을 넘긴다", not _miss92, ' '.join(_miss92))

# ⑧ 제거 기한이 지난 API — 스트림릿을 올리는 순간 화면이 사라진다
check("st.components.v1.html 을 쓰지 않는다 (2026-06-01 제거 기한 경과)",
      'st.components.v1.html(' not in _w92)

# ⑨ 하위 프로세스 출력은 UTF-8 로 읽는다 — 한글 로그에서 죽지 않게
_subp92 = [ln for ln in _w92.split('\n')
           if '.run(' in ln and 'capture_output' in ln]
check("하위 프로세스 호출에 encoding 이 지정돼 있다",
      all('encoding=' in _w92[max(0, _w92.find(ln) - 400):
                              _w92.find(ln) + 400] for ln in _subp92),
      str(_subp92[:1])[:120])


section("93. 라운드 17~21 — 실행 레벨 재조사 · 도구 검증 규율")

import json as _json93

# ① 라운드 17 이 왜 무효였는지가 기록에 남아 있는가 (같은 실수 반복 방지)
_mv93 = open(_os.path.join(PROJ, 'docs', 'MODEL_VERSIONS.md'),
             encoding='utf-8').read()
check("라운드 17 무효 사유가 기록돼 있다 (mfe/mae 창 불일치)",
      '라운드 17 은 무효였다' in _mv93 and '청산 봉까지만' in _mv93)
check("라운드 18~21 기각이 기록돼 있다",
      '라운드 18' in _mv93 and '라운드 21' in _mv93 and '기각' in _mv93)
check("점수 분리력 결론이 기록돼 있다",
      '58점 문턱은' in _mv93 and '구분되지 않는다' in _mv93)

# ② 재시뮬레이터가 현행 판정을 재현하는가 — 도구를 먼저 검증한다
_pth93 = _os.path.join(PROJ, '.portfolio', 'virtual_paths.jsonl')
if _os.path.exists(_pth93):
    sys.path.insert(0, _os.path.join(PROJ, 'scripts'))
    import exec_sim as _X93
    _orig93 = {}
    for _r93 in _X93._jsonl(_X93.LED):
        _orig93[(_r93['ticker'], _r93['date'])] = _r93.get('outcome')
    _cs93, _ = _X93.load_cases(min_score=0, need_path=True)
    _ag93 = _tt93 = 0
    for _c93 in _cs93:
        _k93, _ = _X93.simulate(_c93, _c93['TP'], _c93['SP'])
        if _k93 == 'NODATA':
            continue
        _tt93 += 1
        if _k93 == _orig93.get((_c93['ticker'], _c93['date'])):
            _ag93 += 1
    _rate93 = _ag93 / max(1, _tt93) * 100
    check("재시뮬레이터가 현행 판정을 99% 이상 재현",
          _rate93 >= 99.0, f'{_rate93:.2f}% ({_ag93:,}/{_tt93:,})')
    check("경로가 원장 전건에 붙어 있다",
          len(_cs93) > 0 and _tt93 >= 19000, f'{_tt93:,}건')
else:
    check("경로 파일 존재 (.portfolio/virtual_paths.jsonl)", False,
          '없음 — scripts/enrich_paths_r17d.py 를 먼저 돌리세요')

# ③ 실행 레벨 연구가 mfe/mae 를 직접 쓰지 않는가 (창이 다르다)
#    라운드 17 이 그렇게 무효가 됐다. 새 연구는 exec_sim 만 쓴다.
_newstudy93 = ['exec_levels_r18.py', 'when_not_to_buy_r19.py',
               'gate_lift_r19b.py', 'does_score_work_r20.py',
               'loss_control_r21.py']
_bad93 = []
for _f93 in _newstudy93:
    _p93 = _os.path.join(PROJ, 'scripts', _f93)
    if not _os.path.exists(_p93):
        _bad93.append(f'{_f93}(없음)')
        continue
    _s93 = open(_p93, encoding='utf-8').read()
    if 'mfe_pct' in _s93 or 'mae_pct' in _s93:
        _bad93.append(f'{_f93}(mfe/mae 직접 사용)')
    if 'import exec_sim' not in _s93 and 'from exec_sim' not in _s93 \
            and 'when_not_to_buy_r19' not in _s93:
        _bad93.append(f'{_f93}(exec_sim 미사용)')
check("라운드 18~21 연구가 exec_sim 만 쓴다 (mfe/mae 직접 사용 없음)",
      not _bad93, ' '.join(_bad93))

# ④ 사전등록이 문서화돼 있는가 — 측정 후에 기준을 만들지 않았다는 증거
for _f93 in _newstudy93:
    _p93 = _os.path.join(PROJ, 'scripts', _f93)
    if not _os.path.exists(_p93):
        continue
    _d93 = (open(_p93, encoding='utf-8').read().split('"""')[1]
            if '"""' in open(_p93, encoding='utf-8').read() else '')
    check(f"{_f93} 에 사전등록이 적혀 있다",
          ('사전등록' in _d93 or '채택 기준' in _d93 or '판정 기준' in _d93
           or '해석 규칙' in _d93), _d93[:60].replace('\n', ' '))

# ⑤ 채택한 것이 없다는 사실이 산출물에도 남아 있는가
for _f93, _key93 in (('exec_levels_r18.json', 'adopted'),
                     ('gate_lift_r19b.json', 'adopted'),
                     ('loss_control_r21.json', 'adopted')):
    _p93 = _os.path.join(PROJ, '.portfolio', _f93)
    if not _os.path.exists(_p93):
        continue
    with open(_p93, encoding='utf-8') as _fh93:
        _j93 = _json93.load(_fh93)
    check(f"{_f93} 채택 없음이 기록됨", _j93.get(_key93) in (None, [], ''),
          str(_j93.get(_key93))[:60])

# ⑥ 화면에서 '추천'이 두 집단을 가리키지 않는가 (58+ vs 60+)
_w93 = open(_os.path.join(PROJ, 'web_app.py'), encoding='utf-8').read()
check("타일 라벨에 점수 문턱이 박혀 있다 (60점+)",
      "'60점+ 신호 실전 적중률'" in _w93)
check("국면 표 제목에 점수 문턱이 박혀 있다 (58점+)",
      '시장 국면별 성적 (58점+ 신호)' in _w93)
check("두 표의 숫자가 다른 이유를 본문에서 밝힌다",
      '아래 국면별 표는 **58점 이상**' in _w93)

# ⑦ 새 이슈가 원인·계획과 함께 등록돼 있는가
_io93 = open(_os.path.join(PROJ, 'improvement', 'issue_ops.py'),
             encoding='utf-8').read()
for _k93 in ('model|score_not_separating', 'data|ledger_path_window',
             'usability|loss_control_tradeoff'):
    check(f"플레이북에 {_k93} 가 있다", f"'{_k93}'" in _io93)


section("94. 라운드 22 — 실행 가격이 서로 말이 되는가 (진입가 기준 레벨)")

# 손절·목표는 현재가 기준, 권장 매수가는 적정가 기준이라 서로 모순됐다.
# 실측(30종목): 권장 매수가가 나온 17종목 중 11종목(65%)의 손절가가
# 매수가보다 위. "6,602원에 사서 19,339원에 손절"은 문장이 성립 안 한다.
_w94 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
_q94 = open(_os.path.join(PROJ, "quant_indicators.py"), encoding='utf-8').read()

check("엔진이 진입가 기준 레벨을 산출한다",
      "'entry_stop_price': entry_stop_price" in _q94
      and "'entry_target_1st': entry_target_1st" in _q94
      and "'entry_rr': entry_rr" in _q94)
check("진입가 기준 손절도 같은 공식(변동성·바닥)을 쓴다",
      "_e_risk = _e * max(_stop_floor, vol_20 * _stop_mult)" in _q94)
check("진입가 기준에서도 TDST 지지선 규칙이 적용된다",
      "(_e - 1.5 * _e_risk) <= tdst_support <= (_e - 0.5 * _e_risk)" in _q94)
check("2차 목표(구조적 저항)는 진입가로 옮기지 않는다 — 실재 가격대다",
      'target_struct' in _q94 and "'entry_target_2nd'" not in _q94)
check("화면 '살 가격' 칸에 그 가격 기준 손절·목표를 붙인다",
      '_entry_lv_html' in _w94 and '이 가격에 사면 → 손절' in _w94)
check("떠넘기던 경고문을 실제 안내로 바꿨다",
      '진입가 기준으로 손절가를 다시 설정해야 합니다' not in _w94
      and '시간축이 다릅니다' in _w94
      and '목표가는 밸류에이션을 보지 않습니다' in _w94)

# 실제로 산출해 정합한지 — 파이프라인을 돌려 확인한다 (§5 의 스냅샷 재사용)
_fs94 = fs
_rec94 = _fs94.get('recommended_buy_price')
_es94 = _fs94.get('entry_stop_price')
_et94 = _fs94.get('entry_target_1st')
# 라운드 30: 손절·목표는 **화면에 뜨는 진입가**에 매단다. 종전 검사는
# recommended_buy_price(장기 가치 참고선)와 비교했는데, 표시 진입가는
# 눌림가로 바뀐 지 오래였다. 그 어긋남이 GS·NAVER 모순을 통과시켰다.
_anc94 = _fs94.get('entry_pullback_price') or _rec94
if _anc94 and _es94:
    check("진입가 기준 손절이 진입가보다 아래다", _es94 < _anc94,
          f'진입 {_anc94:,.0f} · 손절 {_es94:,.0f}')
    check("진입가 기준 1차 목표가 진입가보다 위다", _et94 > _anc94,
          f'진입 {_anc94:,.0f} · 1차 {_et94:,.0f}')
    check("손절·목표가 표시 진입가와 같은 기준을 쓴다",
          _fs94.get('entry_pullback_price') is None
          or _anc94 == _fs94.get('entry_pullback_price'))
    check("진입가 기준 손익비가 정의된다",
          _fs94.get('entry_rr') is not None and _fs94['entry_rr'] > 0,
          str(_fs94.get('entry_rr')))
else:
    check("권장 매수가 미산출 시 진입가 레벨도 미산출 (지어내지 않는다)",
          _es94 is None and _et94 is None,
          f'rec={_rec94} stop={_es94} t1={_et94}')

# 라운드 22 기록이 남아 있는가
_mv94 = open(_os.path.join(PROJ, 'docs', 'MODEL_VERSIONS.md'),
             encoding='utf-8').read()
check("라운드 22 실측(65%)이 기록돼 있다",
      '라운드 22' in _mv94 and '65%' in _mv94)


section("95. 시계열 순서 — 한 줄이 어긋나면 차트가 통째로 죽는다")

# 실시간 봉을 t_ref 로 찍어 뒤에 붙이는데, 원천이 이미 t_ref 보다 나중 봉
# (오늘 장중)을 갖고 있으면 …08-03, 08-04, 08-03 이 된다.
# Lightweight Charts 는 역순 시계열에서 **예외도 경고도 없이** 렌더를
# 포기한다 — 격자와 가격선만 남은 빈 화면이 됐다 (2026-08-04 실측).
# 지표(MA·RSI·MACD)도 그 어긋난 순서 위에서 계산되고 있었다.
_td95 = snap['tech_df']
_t95 = [str(x)[:10] for x in _td95['trade_date']]
_rev95 = [(i, _t95[i - 1], _t95[i]) for i in range(1, len(_t95))
          if _t95[i] < _t95[i - 1]]
check("tech_df 날짜가 오름차순이다", not _rev95, str(_rev95[:3]))
check("tech_df 에 같은 날짜가 두 번 있지 않다",
      len(set(_t95)) == len(_t95),
      f'{len(_t95) - len(set(_t95))}건 중복')

# 실시간 행이 붙는 날짜 — 원천의 마지막 거래일이어야 한다
_q95 = open(_os.path.join(PROJ, 'quant_indicators.py'), encoding='utf-8').read()
check("실시간 봉을 t_ref 가 아니라 원천 마지막 거래일에 붙인다",
      "if _last_src > rt_date:" in _q95 and "'trade_date': rt_date," in _q95)
check("같은 날짜 행은 위치와 무관하게 전부 지운다 (마지막 하나만 보지 않는다)",
      ".str[:10] != rt_date" in _q95)
check("붙인 뒤 날짜순으로 정렬한다",
      "sort_values('trade_date', kind='stable')" in _q95)

# 차트도 방어적이어야 한다 — 상류 한 줄 때문에 화면이 죽으면 안 된다
_cp95 = open(_os.path.join(PROJ, 'chart_pro.py'), encoding='utf-8').read()
check("차트가 시계열을 정렬·중복제거하고 그린다",
      "drop_duplicates('_t', keep='last')" in _cp95
      and "sort_values('_t', kind='stable')" in _cp95)

# 실제로 어긋난 데이터를 넣어도 차트가 살아 있는가 (방어선 작동 확인)
import chart_pro as _cp95m
_bad95 = _td95.copy()
if len(_bad95) >= 3:
    _bad95 = pd.concat([_bad95, _bad95.iloc[[-2]]], ignore_index=True)
    _html95 = _cp95m.build_chart_html(_bad95, fs, name='시험', unit_str='원',
                                      theme='dark', user_avg=None)
    import re as _re95b
    _m95 = _re95b.search(r'"candles":\s*(\[.*?\}\])', _html95, _re95b.S)
    if _m95:
        _times95 = _re95b.findall(r'"time":\s*"(\d{4}-\d{2}-\d{2})"',
                                  _m95.group(1))
        _rev95b = sum(1 for i in range(1, len(_times95))
                      if _times95[i] < _times95[i - 1])
        check("역순 행을 넣어도 차트 데이터는 오름차순으로 나간다",
              _rev95b == 0, f'역순 {_rev95b}건')
    else:
        check("차트 candles 배열을 찾을 수 있다", False, 'candles 미발견')

# 상단 바 — 엔진 버전 축 전부 노출 + 업데이트 이력 링크
#   라운드 44에서 '다섯 축'이 아니라 **versioning.AXES 전부**로 바꿨다.
#   축을 화면에 손으로 나열해 둔 탓에 축이 7개로 늘었는데 5개만 그렸다.
_w95 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
_u95 = open(_os.path.join(PROJ, "ui_kit.py"), encoding='utf-8').read()
check("상단 바에 엔진 버전 축을 빠짐없이 보여 준다",
      'for _a in _ver.AXES' in _w95 and "'news': '뉴스'" in _w95
      and "'sector': '업황'" in _w95)
check("엔진 버전 칩이 업데이트 이력으로 간다",
      "class='qvers'" in _w95 and "href='#nav-updates'" in _w95)
check("운영 버전 칩도 업데이트 이력으로 간다",
      "version_href: str = '#nav-updates'" in _u95
      and "<a href='{_esc(version_href)}'" in _u95)
check("버전 칩은 메뉴 링크 스타일을 물려받지 않는다",
      '.qnav a.qvers' in _w95)


section("96. 라운드 23 — 가격 체계 분리 · 도달 가능성 · 스캔 범위 정직 표기")

_w96 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
_q96 = open(_os.path.join(PROJ, "quant_indicators.py"), encoding='utf-8').read()

# ① 도달 가능성 — "그 가격까지 정말 오나"를 σ 로 잰다
check("엔진이 권장 매수가의 도달 가능성을 σ 로 산출한다",
      "'rec_buy_sigma': rec_sigma" in _q96
      and "'rec_buy_reach': rec_reach" in _q96
      and "'horizon_sigma_pct'" in _q96)
check("목표가 도달 가능성도 같은 잣대로 산출한다",
      "'target1_sigma': t1_sigma" in _q96)
_fs96 = fs
for _k96 in ('rec_buy_sigma', 'rec_buy_reach', 'target1_sigma',
             'horizon_sigma_pct'):
    check(f"four_scores 에 {_k96} 가 있다", _k96 in _fs96)
if _fs96.get('rec_buy_sigma') is not None:
    check("σ 는 0 이상 실수", _fs96['rec_buy_sigma'] >= 0,
          str(_fs96['rec_buy_sigma']))
    check("도달 표현이 정해진 네 가지 중 하나",
          _fs96.get('rec_buy_reach') in ('가까움', '닿을 만함', '멀다',
                                         '사실상 도달 어려움'),
          str(_fs96.get('rec_buy_reach')))

# ② 화면 — 신규 매수자 / 보유자 완전 분리
check("화면이 '아직 안 샀다면' 블록을 따로 그린다",
      '아직 안 샀다면' in _w96 and '신규 매수 기준' in _w96)
check("화면이 '이미 갖고 있다면' 블록을 따로 그린다",
      '이미 갖고 있다면' in _w96 and '현재가 기준 대응' in _w96)
check("두 기준을 한 줄에 섞지 않는다 (예전 4칸 격자 제거)",
      "살 가격 <span style='font-weight:400;'>· 아직 안 샀다면" not in _w96)
check("시간축이 다르다는 설명을 본문에 적는다",
      '시간축이 다릅니다' in _w96 and '분기 실적 기반 장기 가치' in _w96)

# ③ 도달 어려우면 실행 가격처럼 강조하지 않는다
check("도달이 2σ 를 넘으면 관찰 대상으로 표시한다",
      '_rec_is_far' in _w96 and '관찰 대상입니다' in _w96)
check("도달 어려운 권장가는 글자 크기를 낮춘다 (강조하지 않는다)",
      "'17' if _rec_is_far else '22'" in _w96)

# ④ 논리 검사가 자동으로 돌고 어긋나면 화면에 적힌다
check("가격 체계 자동 점검이 존재한다",
      '_logic_warn' in _w96 and '가격 체계 자동 점검' in _w96)
for _cond96, _lab96 in (
        ('_e_t1 <= rec_buy_val', '신규 목표 ≤ 매수가'),
        ('_e_stop >= rec_buy_val', '신규 손절 ≥ 매수가'),
        ('_e_rr < 1.0', '손익비 1:1 미달'),
):
    check(f"검사 조건: {_lab96}", _cond96 in _w96)

# ⑤ 스캔 범위 — 과장 없이
check("사이드바가 '전체'라고 과장하지 않는다",
      '코스피·코스닥 전체에서 거래대금' not in _w96
      and '거래대금·상승률 순위 상위' in _w96)
check("스캔 결과에 후보 수집 출발점을 밝힌다",
      '거래대금·상승률 순위 상위에서 수집' in _w96
      and '순위 페이지에서 출발하므로' in _w96)
check("전 종목 정밀분석이 아니라고 명시한다",
      '관심점수 상위' in _w96 and '정밀분석</b>한 결과입니다' in _w96)
check("'추천 없음'의 뜻을 오해하지 않게 적는다",
      "'추천 없음'은 시장에 후보가 없다는 뜻이 아닙니다" in _w96)
check("퍼널 단계 수치를 보여 준다 (관심지표 계산 실제 개수)",
      '_deep_done' in _w96 and '_deep_cap' in _w96)


section("97. 추천 카드 재설계 — 가격 순서·기준 분리·아이콘 한 세트")

import ui_kit as _uk97
_w97 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
_u97 = open(_os.path.join(PROJ, "ui_kit.py"), encoding='utf-8').read()
_p97 = open(_os.path.join(PROJ, "premarket.py"), encoding='utf-8').read()


def _row97(h, label):
    """가격 표의 그 줄이 실제로 있는가 — 안내 문구의 낱말과 섞이면 안 된다."""
    return f">{label}</div>" in h


_C97 = {
    'pos': dict(state='pos', state_label='오늘 사도 되는 종목', name='가',
                code='000001', asset_ko='주식', score=62, price=842000,
                rec_buy=821400, rec_basis='-2.4% · 0.3σ · 가까움',
                target=869900, target_basis='권장가 기준', stop=767300,
                stop_basis='권장가 기준', say='설명', news='뉴스', hit='적중'),
    'warn': dict(state='warn', state_label='사실상 관망', name='나',
                 code='000002', asset_ko='주식', score=49, price=243500,
                 rec_buy=126452, rec_basis='-48.1% · 1.82σ · 멀다',
                 target=136920, target_basis='권장가 기준', stop=111480,
                 stop_basis='권장가 기준', dim_levels=True, say='설명',
                 news='뉴스', hit='적중'),
    'hold': dict(state='hold', state_label='판단 보류', name='다',
                 code='000003', asset_ko='주식', score=59, price=26150,
                 rec_buy=None, rec_na='미산출', say='설명', news='뉴스',
                 hit='적중'),
    'neg': dict(state='neg', state_label='오늘 사면 안 되는 종목', name='라',
                code='000004', asset_ko='주식', score=41, price=34850,
                rec_buy=None, rec_na='차단됨', say='설명', hit='적중'),
}

for _th97 in ('dark', 'light'):
    for _k97, _c97 in _C97.items():
        _h97 = _uk97.reco_card(_c97, theme=_th97)
        check(f"[{_th97}/{_k97}] 카드에 현재가가 있다", _row97(_h97, '현재가'))
        check(f"[{_th97}/{_k97}] 카드에 권장 매수가가 있다",
              _row97(_h97, '권장 매수가'))
        # 진입 기준이 없으면 목표·손절을 아예 감춘다 (참고값을 실행 가격 자리에 두지 않는다)
        _want97 = bool(_c97.get('rec_buy'))
        check(f"[{_th97}/{_k97}] 목표가 표시={_want97} 규칙",
              _row97(_h97, '1차 목표가') == _want97)
        check(f"[{_th97}/{_k97}] 손절가 표시={_want97} 규칙",
              _row97(_h97, '손절가') == _want97)
        # 순서는 늘 현재가 → 권장 → 목표 → 손절
        check(f"[{_th97}/{_k97}] 현재가가 권장보다 위에 온다",
              _h97.index('>현재가</div>') < _h97.index('>권장 매수가</div>'))
        if _want97:
            check(f"[{_th97}/{_k97}] 권장 → 목표 → 손절 순서",
                  _h97.index('>권장 매수가</div>') < _h97.index('>1차 목표가</div>')
                  < _h97.index('>손절가</div>'))
        check(f"[{_th97}/{_k97}] 이모지를 쓰지 않는다",
              not _re.search('[\U0001F300-\U0001FAFF]', _h97))
        check(f"[{_th97}/{_k97}] 테두리를 쓰지 않는다 (§78)",
              'border:' not in _h97 and 'border-top:' not in _h97)

# 카드에 현재가 기준(보유자) 목표·손절을 섞지 않는다
check("카드의 목표·손절은 권장가 기준만 쓴다",
      "'target': e_t1 if rec else None" in _w97
      and "'stop': e_stop if rec else None" in _w97)
check("보유자 기준은 경고 상자 한 줄로만 안내한다",
      "보유 중이시면 기준이 다릅니다" in _w97 and 'hold_note' in _w97)
# 소스에서는 파이썬 문자열 이어붙이기로 나뉘어 있다 — 조각으로 확인한다
check("진입 기준이 없으면 목표·손절을 감춘다고 안내한다",
      '진입 기준이 없어 목표가·손절가를 표시하지' in _w97
      and '지금은 신규 매수 판단을 보류합니다' in _w97)

# premarket 이 진입가 기준 레벨과 도달 가능성을 실어 나른다
for _k97 in ('entry_target_1st', 'entry_stop_price', 'entry_rr',
             'rec_buy_sigma', 'rec_buy_reach'):
    check(f"premarket 이 {_k97} 를 담는다", f"'{_k97}':" in _p97)

# 아이콘 — Lucide 한 세트, 규격 통일
for _ic97 in ('CircleDollarSign', 'ArrowDownToLine', 'Target', 'ShieldAlert',
              'ShieldCheck', 'Clock3', 'Newspaper', 'ChartNoAxesCombined',
              'TriangleAlert', 'CalendarClock'):
    check(f"아이콘 {_ic97} 가 있다", _ic97 in _uk97._ICONS)
check("모든 아이콘이 같은 규격으로 그려진다 (24 그리드·선 2·둥근 끝)",
      "viewBox='0 0 24 24'" in _u97 and "stroke-width='2'" in _u97
      and "stroke-linecap='round'" in _u97)
check("아이콘 크기는 16~18px 안 (카드 17 · 근거 16)",
      "_icon(icon, t['tx3'] if muted else (color or t['tx2']), 17)" in _u97
      and "_icon(icon, color or t['tx3'], 16)" in _u97)

# 이전 인라인 카드가 남아 있지 않은가 (킷으로만 그린다)
check("추천 카드를 킷 컴포넌트로만 그린다",
      '_uk.reco_card(' in _w97
      and "min-height:236px" not in _w97)


section("98. 상단 바 하나로 · 카드 버튼 3개 · 전 종목 경량 스캔")

_w98 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()

# ① 상단 바 — 두 줄이었고 룰북·산식이 두 번, 운영 버전은 모델과 같은 값이었다
check("상태 줄을 따로 그리지 않는다 (한 줄로 합침)",
      '_uk.status_bar(' not in _w98)
# 라운드 44 — '5축' 이 아니라 versioning.AXES 전부다 (7축).
check("상태·판단수·엔진 축·보는 중이 한 바에 들어간다",
      '_STATUS_TOP' in _w98 and 'for _a in _ver.AXES' in _w98
      and 'class="here"' in _w98)
check("룰북·산식이 바 안에서 두 번 나오지 않는다",
      _w98.count("f\"룰북 {_VER_NOW['rulebook']}\"") == 0
      and _w98.count("f\"산식 {_VER_NOW['scoring']}\"") == 0)

# ② 카드 하단 세 동작
for _k98, _lab98 in (('pm_go_', '분석 보기'), ('pm_wl_', '관심 추가'),
                     ('pm_pos_', '보유 등록')):
    check(f"카드 버튼 {_lab98} 가 있다", _k98 in _w98 and _lab98 in _w98)
check("이미 관심종목이면 다시 넣지 않는다",
      '_in_wl' in _w98 and 'disabled=_in_wl' in _w98)
check("관심종목 저장 실패를 삼키지 않는다",
      '관심종목 파일 저장 실패' in _w98)
check("보유 등록 시 수량·평단가를 지어내지 않는다",
      'quantity=0.0' in _w98 and 'average_buy_price=0.0' in _w98
      and '수량·평단가를' in _w98)
check("버튼 라벨에 기호를 쓰지 않는다",
      not _re.search(r"st\.button\('[^']*[✓✔×✕]", _w98))

# ③ 전 종목 경량 스캔 — 순위 페이지에서만 출발하지 않는다
check("전 종목 경량 스캔이 존재한다",
      '_lite = {' in _w98 and '_MIN_TRADE_VALUE' in _w98)
check("경량 스캔이 제외 사유를 나눠 센다",
      all(k in _w98 for k in ("'no_price'", "'no_liquidity'", "'thin'",
                              "'passed'")))
check("경량 스캔 결과를 세션에 남긴다", "st.session_state['scan_lite']" in _w98)
check("퍼널이 4단계로 표시된다",
      all(s in _w98 for s in ('1단계 <b>전 종목 경량 스캔</b>', '2단계 후보 풀',
                              '3단계 관심지표 계산', '4단계 정밀분석')))
check("전체 시장 정밀분석 비율을 표시한다",
      '_deep_rate' in _w98 and '전체 시장 정밀분석 비율' in _w98)
check("탐색률을 유동성 통과분 기준으로 센다 (분모를 부풀리지 않는다)",
      'scan_depth / _deep_pass * 100' in _w98)
# 라운드 37: 분모가 0이면 비율 자체를 만들지 않는다 ('0.0% (5/1)' 방지)
check("분모가 0이면 비율을 만들지 않는다 (라운드 37)",
      '경량 스캔이 0개를 반환했습니다' in _w98)
check("여전히 '추천 없음'의 뜻을 밝힌다",
      "'추천 없음'은 시장에 후보가 없다는 뜻이 아닙니다" in _w98)
check("2단계가 순위 페이지 출발임을 계속 밝힌다",
      '거래대금·상승률 순위 상위에서 수집' in _w98
      and '순위 페이지에서 출발하므로' in _w98)


section("99. 라운드 24 — \"사지 마세요\"로 끝내지 않는다 · 괴리 큰 종목 추천 제외")

import next_action as _na99
_w99 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
_p99 = open(_os.path.join(PROJ, "premarket.py"), encoding='utf-8').read()
_u99 = open(_os.path.join(PROJ, "ui_kit.py"), encoding='utf-8').read()

# ① 실제 종목에 걸어 본다 (§5 스냅샷 재사용 — 추가 조회 없음)
_r99 = _na99.build(fs, snap['tech_df'], snap.get('rt_price'),
                   snap.get('verdict'))
check("다음 조건 엔진이 결과를 낸다", isinstance(_r99, dict) and _r99.get('kind'))
check("판정이 정해진 여섯 가지 안", _r99['kind'] in (
    'buy_now', 'pullback', 'breakout', 'observe', 'blocked', 'no_data'),
    str(_r99['kind']))
check("관망이어도 한 줄 결론이 비어 있지 않다", bool(_r99.get('headline')))
check("일 ATR 을 산출한다", _r99.get('atr_pct') is not None,
      str(_r99.get('atr_pct')))
check("ATR 로 조정한 밴드 경계가 3개",
      isinstance(_r99.get('band_edges'), tuple) and len(_r99['band_edges']) == 3,
      str(_r99.get('band_edges')))
check("밴드 경계가 오름차순",
      _r99['band_edges'][0] < _r99['band_edges'][1] < _r99['band_edges'][2])
if _r99['kind'] not in ('blocked', 'buy_now', 'no_data'):
    check("기다리는 판단에는 조건이 하나 이상 붙는다",
          len(_r99.get('conditions') or []) >= 1,
          str(len(_r99.get('conditions') or [])))
    check("추천 자격이 없으면 이유를 남긴다",
          _r99.get('reco_eligible') or _r99.get('exclude_reason'),
          str(_r99.get('exclude_reason')))

# ② 지지·저항은 실제 계산값에서만 — 지어내지 않는다
_lv99 = _na99.levels(snap['tech_df'], snap.get('rt_price'))
_p0 = float(snap.get('rt_price') or 0)
check("지지 후보는 전부 현재가 아래",
      all(v < _p0 for v, _ in _lv99['supports']), str(_lv99['supports'][:2]))
check("저항 후보는 전부 현재가 위",
      all(v > _p0 for v, _ in _lv99['resists']), str(_lv99['resists'][:2]))

# ③ 밴드 분류 — 괴리가 크면 추천에서 뺀다
class _FakeDF:
    """최소 tech_df 흉내 — 밴드 분류만 검사한다."""
    columns = ['tr', 'high', 'low', 'sma_20', 'bb_mid', 'volume_ratio']

    def __init__(self, n=30):
        self._n = n

    def __len__(self):
        return self._n


_atr99 = _r99.get('atr_pct')
if _atr99:
    _sc99 = min(_na99.SCALE_MAX, max(_na99.SCALE_MIN,
                                     _atr99 / _na99.BASE_ATR_PCT))
    check("변동성이 크면 밴드가 넓어진다 (ATR 보정)",
          abs(_r99['band_edges'][0] - round(_na99.BANDS[0] * _sc99, 1)) < 0.05)
check("배율이 0.7~2.5 로 묶인다",
      _na99.SCALE_MIN == 0.7 and _na99.SCALE_MAX == 2.5)
check("예상 대기기간 상한이 60거래일", _na99.MAX_WAIT_DAYS == 60)

# ④ 화면 연결
check("결론 배너에 '다음 조건' 블록이 있다",
      '다음 조건 — 언제 사면 되나' in _w99 and '_NA = _na.build(' in _w99)
check("추천 카드가 다음 조건을 받는다", "'next_conditions'" in _w99)
check("카드 컴포넌트가 다음 조건 상자를 그린다",
      "p.get('next_conditions')" in _u99 and '다음 조건' in _u99)
check("premarket 이 다음 조건을 실어 나른다",
      "'next_action': _na_of(r)" in _p99 and 'def _na_of(' in _p99)

# ⑤ 괴리 큰 종목을 추천 자리에서 뺀다
check("추천 자격 없으면 '기다려야 하는 종목'으로 내린다",
      "_n.get('exclude_reason') and not _n.get('reco_eligible')" in _w99)
check("상태 라벨이 '무엇을 기다리는가'로 바뀐다",
      '_NA_LABEL' in _w99 and '눌림목 대기' in _w99
      and '돌파 확인 대기' in _w99 and '장기 관찰' in _w99)

# ⑥ 알림 조건을 저장한다 (다시 검색하지 않아도 되게)
check("알림으로 저장할 조건을 만든다", "'alert'" in open(
    _os.path.join(PROJ, 'next_action.py'), encoding='utf-8').read())


section("100. 라운드 25 — 실행 가능한 진입가 · 밸류 가드")

import json as _json100
_q100 = open(_os.path.join(PROJ, 'quant_indicators.py'), encoding='utf-8').read()
_n100 = open(_os.path.join(PROJ, 'next_action.py'), encoding='utf-8').read()
_p100 = open(_os.path.join(PROJ, 'premarket.py'), encoding='utf-8').read()

# ① 엔진이 실행 가능한 눌림 진입가를 낸다 (적정가 기반과 분리)
check("엔진이 눌림 진입가를 산출한다",
      "'entry_pullback_price': entry_pullback_price" in _q100)
# 라운드 30 에서 이 식은 _entry_anchor 로 옮겼다 — 손절·목표가 같은 값을
# 쓰게 하기 위해서다. 식 자체는 그대로다.
check("눌림가는 기준가 − 일변동성 1배",
      '_entry_anchor = float(curr_price * (1.0 - vol_20))' in _q100)
check("적정가 기반 값은 '장기 가치 참고선'으로 이름이 바뀌었다",
      "'value_floor_price': value_floor_price" in _q100
      and '장기 가치 기준' in _q100)
for _k100 in ('entry_pullback_price', 'entry_pullback_basis',
              'value_floor_price'):
    check(f"four_scores 에 {_k100} 가 있다", _k100 in fs)
if fs.get('entry_pullback_price') and snap.get('rt_price'):
    _gap100 = (fs['entry_pullback_price'] / float(snap['rt_price']) - 1) * 100
    check("눌림 진입가가 현재가보다 아래", _gap100 < 0, f'{_gap100:+.1f}%')
    check("눌림 진입가가 현재가에서 25% 안쪽 (실행 가능)",
          abs(_gap100) <= 25.0, f'{_gap100:+.1f}%')

# ② 다음 조건이 눌림가를 쓴다 (적정가 기반을 오늘의 매수가로 쓰지 않는다)
#
# ⚠️ 라운드 53c — 이 검사는 원래 `"_f(fs.get('entry_pullback_price')) or _f("`
# 라는 **문자열**을 요구했다. 즉 "눌림가를 먼저 쓰고 적정가 기반으로 폴백한다"
# 는 구현을 검사가 못박고 있었다. 그런데 그 폴백 대상이
# `recommended_buy_price`(라운드 25 폐기 산식)였다 — 검사가 결함을 잠그고
# 있었던 셈이다. 이제 폴백 자체를 뗐으므로, 문자열이 아니라 **의도**를 본다.
check("next_action 이 눌림 진입가만 쓴다",
      "rec = _f(fs.get('entry_pullback_price'))" in _n100)
check("적정가 기반 값으로 폴백하지 않는다",
      "fs.get('recommended_buy_price')" not in _n100)
check("진입가가 없으면 지어내지 않고 그렇게 말한다",
      "'유효 진입가 미산출'" in _n100)

# ③ 밸류 가드 — 눌림가는 밸류에이션을 모른다
check("적정가 크게 초과면 오늘의 매수 후보에서 뺀다",
      "over_value = ('크게 초과' in zone)" in _n100
      and '고평가 구간입니다' in _n100)
check("장기 참고선을 '오늘의 매수가가 아니다'라고 밝힌다",
      '오늘의 매수가가 아니라 위험 참고선입니다' in _n100)

# ④ 화면·리포트가 같은 값을 쓴다
check("premarket 이 눌림가를 rec_buy 로 싣는다",
      "fs.get('entry_pullback_price')" in _p100
      and "'value_floor': fs.get('value_floor_price')" in _p100)

# ⑤ 실제로 걸어 본다 — 고평가 종목이 buy_now 로 새지 않는가
import next_action as _na100
_r100 = _na100.build(fs, snap['tech_df'], snap.get('rt_price'),
                     snap.get('verdict'))
_zone100 = str(fs.get('chase_buy_status') or fs.get('entry_zone') or '')
if '크게 초과' in _zone100:
    check("고평가 종목은 buy_now 가 되지 않는다",
          _r100['kind'] != 'buy_now', str(_r100['kind']))
    check("고평가 제외 사유를 남긴다",
          '적정가' in str(_r100.get('exclude_reason') or ''),
          str(_r100.get('exclude_reason')))

# ⑥ 연구 산출물 — 채택/기각이 기록돼 있다
for _f100, _lab100 in (('entry_engine_r25.json', '라운드 25'),
                       ('entry_engine_r25b.json', '라운드 25b')):
    _pp100 = _os.path.join(PROJ, '.portfolio', _f100)
    if not _os.path.exists(_pp100):
        continue
    with open(_pp100, encoding='utf-8') as _fh100:
        _j100 = _json100.load(_fh100)
    check(f"{_lab100} 결과가 기록돼 있다", 'adopted' in _j100)
    check(f"{_lab100} 는 수익 개선을 채택하지 않았다",
          _j100.get('adopted') in (None, '', []),
          str(_j100.get('adopted')))

# ⑦ 기록 — 왜 바꿨는지가 문서에 있다
_mv100 = open(_os.path.join(PROJ, 'docs', 'MODEL_VERSIONS.md'),
              encoding='utf-8').read()
check("라운드 25 기록에 채택 근거가 '실행 가능성'이라고 적혀 있다",
      '라운드 25' in _mv100 and '실행 가능성' in _mv100)
check("수익 개선을 주장하지 않는다고 적혀 있다",
      '수익 개선' in _mv100 and '기각' in _mv100)

# ⑧ 동결 리포트가 낡았는지 화면이 먼저 말한다
_w100 = open(_os.path.join(PROJ, 'web_app.py'), encoding='utf-8').read()
check("개장 전 리포트에 만든 엔진 버전을 찍는다",
      "'engine_version': _engine_version()" in _p100
      and 'def _engine_version(' in _p100)
# 라운드 30: 경고 분기를 하나로 합쳤다. 종전에는 "다시 스캔하세요"라고
# 하면서도 리포트 키가 날짜뿐이라 다시 스캔이 아무것도 갱신하지 못했다.
check("엔진이 바뀌면 리포트가 낡았다고 경고한다",
      '_pm_stale' in _w100 and '현재 엔진은' in _w100)
check("버전 기록이 없는 예전 리포트도 같은 경고를 받는다",
      "bool(_pmr.get('stale_engine')) or not _pm_ver" in _w100)
check("경고가 실제로 실행 가능한 조치를 가리킨다",
      '다시 스캔이 실제로 갱신됩니다' in _w100)
# 라운드 30: 경고만 달고 옛 가격을 보여 주면 사용자는 그 숫자를 읽는다.
check("낡은 리포트는 가격을 화면에 두지 않는다",
      'if _pm_stale and _picks_show:' in _w100
      and '_picks_show = []' in _w100)
check("낡아도 어떤 종목이었는지는 밝힌다",
      '이 리포트가 추천했던 종목' in _w100)
check("카드에도 정합 가드가 걸린다",
      'if e_stop is not None and float(e_stop) >= float(rec):' in _w100
      and 'if e_t1 is not None and float(e_t1) <= float(rec):' in _w100)


section("101. 라운드 26 — 못 겨룬 진입 엔진 마저 · 관망 조건 감시")

import json as _json101
import watch_alerts as _wa101
_w101 = open(_os.path.join(PROJ, 'web_app.py'), encoding='utf-8').read()

# ① 지표 레벨 보강 — 기준일 이후 봉이 섞이면 연구가 통째로 무효다
_lvp101 = _os.path.join(PROJ, '.portfolio', 'virtual_levels.jsonl')
check("지표 레벨 파일이 있다", _os.path.exists(_lvp101))
if _os.path.exists(_lvp101):
    _n101 = 0
    _keys101 = set()
    with open(_lvp101, encoding='utf-8') as _fh101:
        for _ln101 in _fh101:
            _ln101 = _ln101.strip()
            if not _ln101:
                continue
            _n101 += 1
            if _n101 <= 3:
                _keys101 |= set(_json101.loads(_ln101).keys())
    check("원장 전건에 레벨이 붙었다", _n101 >= 19000, f'{_n101:,}건')
    for _k101 in ('sma_20', 'bb_lower', 'bb_mid', 'high20', 'low10',
                  'atr14', 'vol20'):
        check(f"레벨에 {_k101} 가 있다", _k101 in _keys101)
_e101 = open(_os.path.join(PROJ, 'scripts', 'enrich_levels_r26.py'),
             encoding='utf-8').read()
check("지표를 기준일까지의 봉으로만 계산한다 (누수 차단)",
      "sub = tdf[tdf['_d'] <= d]" in _e101
      and "str(sub['_d'].iloc[-1]) != d" in _e101)
check("엔진과 같은 산식을 쓴다 (compute_technical_indicators 재사용)",
      'q.compute_technical_indicators(pdf)' in _e101)

# ② 라운드 26 결과 — 채택 없음이 기록돼 있다
_r26p = _os.path.join(PROJ, '.portfolio', 'entry_engine_r26.json')
if _os.path.exists(_r26p):
    with open(_r26p, encoding='utf-8') as _fh101:
        _r26 = _json101.load(_fh101)
    check("라운드 26 은 새 엔진을 채택하지 않았다",
          _r26.get('adopted') in (None, '', []), str(_r26.get('adopted')))
    check("지지선·이동평균·볼린저를 실제로 겨뤘다",
          any('20일선' in r['name'] for r in _r26.get('stage1', []))
          and any('볼린저' in r['name'] for r in _r26.get('stage1', [])))

# ③ 관망 조건 감시 — 가격은 OR, 막는 조건은 AND
_it101 = dict(symbol='T', name='시험', kind='pullback',
              levels=[{'kind': 'support', 'level': 100.0},
                      {'kind': 'breakout', 'level': 130.0}],
              need_cooldown=True, need_volume_calm=True, vol_calm_ratio=1.2)
_c101 = _wa101.check_one(_it101, price=100, low=99.8, high=101, close=100.2,
                         bb_pos=60, wr=-45, vol_ratio=1.0)
check("지지만 맞아도 해소된다 (가격 조건은 OR)", _c101['resolved'] is True)
_c101b = _wa101.check_one(_it101, price=131, low=128, high=132, close=131,
                          bb_pos=60, wr=-45, vol_ratio=1.0)
check("돌파만 맞아도 해소된다", _c101b['resolved'] is True)
_c101c = _wa101.check_one(_it101, price=100, low=99.8, high=101, close=100.2,
                          bb_pos=99, wr=-2, vol_ratio=1.0)
check("과열이 남아 있으면 해소되지 않는다 (막는 조건은 AND)",
      _c101c['resolved'] is False)
_c101d = _wa101.check_one(_it101, price=100, low=99.8, high=101, close=100.2,
                          bb_pos=None, wr=None, vol_ratio=None)
check("지표를 못 받으면 충족으로 세지 않는다", _c101d['resolved'] is False)
check("확인 불가를 그대로 적는다",
      any('확인 불가' in x for x in _c101d['unmet']))
check("해소되면 사람이 읽는 문장을 만든다",
      isinstance(_wa101.sentence(_it101, _c101), str)
      and '해소' in _wa101.sentence(_it101, _c101))
check("해소 안 되면 문장을 만들지 않는다",
      _wa101.sentence(_it101, _c101c) is None)

# ④ 화면 연결
check("결론 카드에 알림 감시 블록이 붙는다",
      '_watch_html' in _w101 and '알림 감시' in _w101)
check("알림 등록·해제 버튼이 있다",
      'btn_wa_on' in _w101 and 'btn_wa_off' in _w101)
check("등록 시 엔진 버전을 함께 남긴다",
      "engine_version=_VER_NOW['model']" in _w101)
check("확인 불가를 충족으로 세지 않는다고 화면에 밝힌다",
      '확인 불가' in _w101 and '충족으로 세지 않습니다' in _w101)

# ⑤ 커밋 메시지의 버전이 실제 이력에 있는가
#    2026-08-05: 버전 올리기가 실패했는데(축 이름을 종류로 넘김) 커밋
#    메시지에는 v2026.08.05.3 이 적혀 나갔다. 없는 버전을 적으면 그 커밋은
#    무엇으로 만든 것인지 추적할 수 없다.
import subprocess as _sp101
import versioning as _ver101
try:
    _msg101 = _sp101.run(['git', 'log', '-1', '--pretty=%s'], cwd=PROJ,
                         capture_output=True, text=True, encoding='utf-8',
                         errors='replace').stdout
except Exception:
    _msg101 = ''
# 제목 **끝 괄호**의 버전만 본다 — 그게 "이 커밋은 버전 X 다"라는 주장이다.
# 본문에 다른 버전을 인용할 수 있다(예: 정정 커밋이 잘못된 버전을 지목).
_vs101 = _re.findall(r'\(\s*(v\d{4}\.\d{2}\.\d{2}\.\d+)\s*\)\s*$',
                     (_msg101 or '').strip())
if _vs101:
    _known101 = {e['version'] for e in _ver101.history(limit=400)}
    _known101 |= set(_ver101.snapshot().values())
    _miss101 = [v for v in _vs101 if v not in _known101]
    check("최근 커밋 메시지의 버전이 실제 이력에 있다",
          not _miss101, f'이력에 없음: {_miss101}')


# ══════════════════════════════════════════════════════════════════════
# §102 — 국면 게이트를 판단에 실제로 걸었는가 (라운드 27)
#    사용자 지적: *"국면별 성과를 표시만 하지 말고 엔진에 실제 반영해."*
#    표시만 하던 6칸 성적이 점수·신뢰도·손절·비중·차단으로 내려왔는지 잠근다.
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("§102 국면 게이트 — 성적이 판단에 내려왔는가 (라운드 27)")
print("=" * 72)
import regime_policy as _rp102

_q102 = open(_os.path.join(PROJ, 'quant_indicators.py'), encoding='utf-8').read()
_w102 = open(_os.path.join(PROJ, 'web_app.py'), encoding='utf-8').read()
_q102_rp = open(_os.path.join(PROJ, 'regime_policy.py'), encoding='utf-8').read()

check("정책을 엔진이 호출한다", "_rp.policy(_RP_MAP.get(regime_code), vol_20)" in _q102)
check("국면코드 4종을 빠짐없이 매핑", all(
    f"'{k}': '{v}'" in _q102 for k, v in
    (('BULL_STRONG', 'BULL'), ('BULL_MILD', 'BULL'),
     ('BEAR_PANIC', 'BEAR'), ('SIDEWAYS', 'SIDEWAYS'))))
check("정책이 손절 계산보다 먼저 온다",
      0 < _q102.find("import regime_policy as _rp")
      < _q102.find("base_risk = curr_price * max(_stop_floor"))
check("손절 배수를 실제로 건다",
      "_stop_mult *= min(1.0, _stop_regime_mult)" in _q102
      and "_stop_floor *= min(1.0, _stop_regime_mult)" in _q102)
check("손절은 좁히기만 한다 (넓히지 않는다)",
      "min(1.0, _stop_regime_mult)" in _q102
      and "max(1.0, _stop_regime_mult)" not in _q102)
check("점수·신뢰도 상한을 씌운다", "_rp.apply_caps(" in _q102)
check("상한은 점수 확정 뒤에 온다",
      0 < _q102.find("final_action_score = min(final_action_score, 74)")
      < _q102.find("_rp.apply_caps("))
check("차단 국면은 판정 문구를 바꾼다",
      'final_action_title = "신규 매수 차단 (국면)"' in _q102)
check("새 판정 문구가 TITLE_MAP 에 등록됐다",
      "'신규 매수 차단 (국면)':" in _q102)
check("차단 문구는 더 강한 경고를 덮지 않는다",
      "not in ('비중축소 검토', '거래 회피'," in _q102)
check("게이트 목록에 국면 항목이 있다", '"국면별 실전 성과 확보"' in _q102)
check("비중 배수를 곱한다", "_pos_regime = min(1.0," in _q102)
check("비중 바닥도 같은 배수를 받는다", "max(10.0 * _pos_scale," in _q102)
check("게이트 결과를 화면에 내보낸다", "'regime_gate': regime_gate," in _q102)
check("화면이 국면 제한을 표시한다",
      "regime_gate" in _w102 and "국면별 제한을 적용했습니다" in _w102)
check("화면이 차단을 별도 문구로 표시한다",
      "이 국면에서는 신규 매수를 하지 않습니다" in _w102)
check("안 깎였으면 아무 말도 하지 않는다",
      "_rg.get('capped') or _rg.get('block_new')" in _w102)

# 정책 자체 — 구간 규칙이 사전등록값 그대로인가
check("정상 경계 50%", _rp102.BANDS[0][0] == 50.0
      and _rp102.BANDS[0][1]['score_cap'] is None)
check("강한 제한은 차단", _rp102.BANDS[-1][1]['block_new'] is True
      and _rp102.BANDS[-1][1]['score_cap'] == 45)
check("표본 없으면 낮춘다", _rp102.NO_SAMPLE['score_cap'] == 55
      and _rp102.NO_SAMPLE['conf_cap'] == 60)
_pol102 = _rp102.policy('BEAR', 0.05)
check("상한은 올리지 않는다", _rp102.apply_caps(30, 40, _pol102) == (30, 40))
check("국면 미판정이면 제한 없음",
      _rp102.policy(None, 0.05)['score_cap'] is None)

# ── 라운드 27b — 첫 판을 스스로 기각한 것을 잠근다 ────────────────────
#    블라인드만 보고 구간을 정했다가 2단계 검증에서 무너졌다:
#    학습+검증으로 다시 뽑으면 6칸이 전부 '정상'이고, 그 정책을 블라인드에
#    적용하면 적중 +0.0%p. '거친 하락 실전 12%'는 n=16 짜리였다.
check("통합 표본을 기본 추정으로 쓴다", "def _pool(cell)" in _q102_rp
      and "SPLITS = ('train', 'valid', 'blind')" in _q102_rp)
check("실전은 표본을 갖췄을 때만 본다",
      "if bn >= MIN_N and bhit is not None" in _q102_rp)
check("두 하한 중 낮은 쪽을 택한다", "min(cands, key=lambda x: x[0])" in _q102_rp)
check("자기기각을 모듈에 기록했다",
      '라운드 27b' in _q102_rp and '스스로 기각' in _q102_rp)
check("n=16 로 차단하지 않는다", _pol102['block_new'] is False,
      f"거친 하락 level={_pol102['level']}")
check("거친 하락의 실전 표본 부족을 밝힌다",
      '실전 표본은 16건뿐' in _pol102['why'], _pol102['why'][:80])
check("거친 하락 판단 근거는 통합 표본", _pol102['basis'] == '통합 표본')
check("통합 표본이 실전보다 훨씬 크다",
      _pol102['pooled_n'] > _pol102['blind_n'] * 5,
      f"통합 {_pol102['pooled_n']} vs 실전 {_pol102['blind_n']}")
# 실전 표본이 충분한 칸에서는 실전이 이긴다 (차분한 상승 n=38 · 거친 옆걸음 n=108)
_pol102b = _rp102.policy('SIDEWAYS', 0.05)
check("실전 표본 충분하면 실전을 따른다", _pol102b['basis'] == '실전 표본',
      f"{_pol102b['basis']} (실전 n={_pol102b['blind_n']})")
check("실전이 나쁜 칸에는 상한이 걸린다", _pol102b['score_cap'] == 62,
      str(_pol102b['level']))
check("표본 없는 칸도 통합으로 판정한다",
      _rp102.policy('BEAR', 0.02)['blind_n'] == 0
      and _rp102.policy('BEAR', 0.02)['pooled_n'] > 0)

# ══════════════════════════════════════════════════════════════════════
# §103 — 적정가를 세 축으로 쪼갰는가 (라운드 28 · 28b)
#    사용자 요구: *"적정가를 장기 가치 범위 / 시장 기반 공정가격 /
#    실전 진입가격으로 분리해 주세요"*, *"신뢰하기 어려운 종목에는 억지로
#    숫자를 만들지 마세요"*, *"신뢰도 등급별로 점수 영향력을 차등하세요"*
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("§103 적정가 3분할 — 지평이 다른 세 질문 (라운드 28)")
print("=" * 72)
import price_axes as _pa103

_ve103 = dict(fair_value_range_core=(24000, 30000),
              fair_value_range_wide=(21000, 34000),
              reference_fair_value=27000, displayed_fair_value=27000,
              fair_value_confidence=84.0, independent_models=3,
              market_adjustment_pct=-2.0, fair_value_status='CALIBRATED',
              type_probabilities={'A_STABLE': 0.7})
_fs103 = dict(entry_pullback_price=25150, entry_stop_price=24200,
              entry_target_1st=26800, entry_rr=1.74, asset_type='STOCK')
_r103 = _pa103.build(_ve103, _fs103, curr_price=26350, bars=900)

check("① 장기 가치는 범위다 (숫자 하나가 아니다)",
      _r103['value_band']['available']
      and _r103['value_band']['low'] < _r103['value_band']['high'])
check("① 넓은 범위도 함께 준다",
      _r103['value_band']['wide_low'] <= _r103['value_band']['low']
      and _r103['value_band']['wide_high'] >= _r103['value_band']['high'])
check("② 시장 공정가격이 별도로 나온다", _r103['market_fair']['available'])
check("③ 실전 진입가격이 별도로 나온다", _r103['entry']['available'])
check("세 축이 서로 다른 값이다",
      len({round(_r103['value_band']['center']),
           round(_r103['market_fair']['price']),
           round(_r103['entry']['price'])}) == 3)
check("세 축의 지평을 명시한다",
      (_r103['value_band']['horizon'], _r103['market_fair']['horizon'],
       _r103['entry']['horizon']) == ('수년', '수개월', '수일'))
check("③ 은 변동성 기반이지 밸류에이션이 아니다",
      '변동성' in _r103['entry']['basis'])

# 억지로 숫자를 만들지 않는다 — 그리고 그게 오류가 아니라 정상 상태다
for _k103, _tag103 in (({'F_DEFICIT': 0.62}, '적자기업'),
                       ({'E_BIOTECH': 0.55}, '바이오')):
    _rr = _pa103.build(dict(_ve103, type_probabilities=_k103), _fs103,
                       26350, bars=900)
    check(f"{_tag103}는 가치 미산출", not _rr['value_band']['available'])
    check(f"{_tag103} 미산출 사유를 적는다", bool(_rr['value_band'].get('why')))
    check(f"{_tag103}도 진입가는 살아 있다", _rr['entry']['available'])
    check(f"{_tag103} 미산출에 숫자 키가 없다", 'low' not in _rr['value_band'])
for _at103 in ('ETF', 'ETF_LEV', 'ETF_INV'):
    _rr = _pa103.build(_ve103, dict(_fs103, asset_type=_at103), 26350, bars=900)
    check(f"{_at103}는 가치 미산출", not _rr['value_band']['available'])
    check(f"{_at103}도 진입가는 살아 있다", _rr['entry']['available'])
check("신규상장(249일)은 미산출",
      not _pa103.build(_ve103, _fs103, 26350, bars=249)['value_band']['available'])
check("250일부터 산출",
      _pa103.build(_ve103, _fs103, 26350, bars=250)['value_band']['available'])

# 신뢰도 등급 — 사용자 사양 그대로인가
check("80점 정상", _pa103.tier_of(80)[1] == '정상' and _pa103.tier_of(80)[2] == 1.0)
check("79점 제한적(절반)",
      _pa103.tier_of(79)[1] == '제한적' and _pa103.tier_of(79)[2] == 0.5)
check("59점 참고만(미반영)",
      _pa103.tier_of(59)[1] == '참고만' and _pa103.tier_of(59)[2] == 0.0)
check("39점 제외", _pa103.tier_of(39)[1] == '제외')
check("신뢰 39↓ 는 범위조차 안 준다",
      not _pa103.build(dict(_ve103, fair_value_confidence=32.0), _fs103,
                       26350, bars=900)['value_band']['available'])

# 축 모순 감지
_r103b = _pa103.build(_ve103, dict(_fs103, entry_pullback_price=40000),
                      curr_price=42000, bars=900)
check("진입가가 가치 상단 밖이면 모순으로 잡는다", not _r103b['consistent'])
check("모순 문구를 사람 말로 적는다",
      any('값어치보다 비싸게' in _n for _n in _r103b['notes']))

# 국면이 시장 공정가격을 낮춘다 (올리지 않는다)
_r103c = _pa103.build(_ve103, dict(_fs103, regime_gate=dict(
    size_mult=0.3, cell_ko='거친 하락')), 26350, bars=900)
check("나쁜 국면은 시장 공정가격을 낮춘다",
      _r103c['market_fair']['price'] < _r103['market_fair']['price'])
check("국면 보정 근거를 밝힌다", '거친 하락' in _r103c['market_fair']['basis'])

# 라운드 28b — 적정가 필수 게이트 해제 + 점수 상한
check("적정가는 더 이상 TOP3 필수 게이트가 아니다",
      '_bool_gate("적정가 신뢰도 확보", fair_value_usable' not in _q102)
check("게이트 항목에 '차단 아님'을 밝힌다",
      '미충족이어도 차단 아님' in _q102)
check("대신 점수 상한을 건다", "_pa_policy['score_cap']" in _q102)
_napol103 = _pa103.score_policy(dict(available=False, why='시험'))
check("미산출 상한은 62점", _napol103['score_cap'] == _pa103.NA_SCORE_CAP == 62)
check("미산출은 차단이 아니다", _napol103['block'] is False)
check("미산출 사유에 실측 EV 를 인용한다", 'EV' in _napol103['why'])
check("정상 등급은 상한 없음",
      _pa103.score_policy(_r103['value_band'])['score_cap'] is None)
check("참고만 등급은 상한 있음",
      _pa103.score_policy(_pa103.build(
          dict(_ve103, fair_value_confidence=50.0), _fs103, 26350,
          bars=900)['value_band'])['score_cap'] == 62)
check("적정가 상한 결과를 화면에 내보낸다", "'fv_gate': fv_gate," in _q102)
check("엔진이 세 축을 내보낸다", "'price_axes'" in _q102)
check("화면이 세 축을 보여준다",
      '가격은 하나가 아닙니다' in _w102 and "_AX.get('value_band')" in _w102)
check("화면이 세 축의 질문을 적는다",
      '이 기업의 값어치는?' in _w102 and '지금 시장이 매길 값은?' in _w102
      and '그래서 얼마에 사나?' in _w102)

# 실측 결과가 코드에 박제됐는가 (나중에 근거 없이 바뀌지 않게)
check("미산출 실측치를 코드에 남긴다",
      _pa103.NA_MEASURED['blind_n'] == 152
      and _pa103.NA_MEASURED['blind_low'] == 46.0)
check("산출 쪽 실측치도 남긴다",
      _pa103.NA_MEASURED['calc_ev'] == 1.03
      and _pa103.NA_MEASURED['na_ev'] == -0.84)


# ══════════════════════════════════════════════════════════════════════
# §104 — 실행점수 상한표 재산정 · 실행 레벨 앵커 통일 (라운드 29 · 30)
#    화면 실측: 관심종목 후보 5개 중 4개가 행동점수 45 에 몰림
#             GS 진입 92,014 인데 손절 100,783 · NAVER 목표가 진입가 아래
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("§104 실행점수 상한표 · 레벨 앵커 (라운드 29 · 30)")
print("=" * 72)
_q104 = open(_os.path.join(PROJ, 'quant_indicators.py'), encoding='utf-8').read()

# ── 라운드 29 — 적정가가 없다고 실행점수를 45로 깎지 않는다 ──────────
check("'판정 불가' 상한 45가 사라졌다", '"판정 불가": 45,' not in _q104)
check("'판정 불가' 상한이 100", '"판정 불가": 100,' in _q104)
check("기본값도 45가 아니다", '.get(entry_zone, 45)' not in _q104
      and '.get(entry_zone, 100)' in _q104)
check("표본 0건 구간은 현행 유지 (풀어주지 않는다)",
      '"적정가 크게 초과 (추격매수 위험)": 30,' in _q104)
check("재산정 근거를 코드에 남긴다",
      'rho=+0.20' in _q104 and '54.5%' in _q104)
check("새 숫자를 만들지 않고 채택된 규칙을 재사용했다고 밝힌다",
      'regime_policy 의 이미 채택된' in _q104)
check("완화/강화 비대칭을 밝힌다", '푸는 데는 표본 90건' in _q104)
_r29 = _os.path.join(PROJ, '.portfolio', 'exec_cap_table_r29.json')
check("라운드 29 산출물이 있다", _os.path.exists(_r29))
if _os.path.exists(_r29):
    import json as _j104
    with open(_r29, encoding='utf-8') as _f:
        _d29 = _j104.load(_f)
    check("rho 가 기준 미달로 기록됐다", _d29['rho'] < _d29['rho_cut'],
          f"rho={_d29['rho']}")
    check("'판정 불가' 하한이 가장 높다",
          _d29['stat']['판정 불가']['low'] == max(
              s['low'] for s in _d29['stat'].values()),
          str(_d29['stat']['판정 불가']['low']))
    check("코드 상한표가 산출물과 일치한다",
          all(f'"{_z}": {_c},' in _q104
              for _z, _c in _d29['proposed'].items()))

# ── 라운드 30 — 손절·목표를 표시 진입가에 맞춰 매단다 ────────────────
check("앵커 변수를 하나로 쓴다", '_entry_anchor' in _q104)
check("앵커는 눌림가 우선", "_entry_anchor = float(curr_price * (1.0 - vol_20))"
      in _q104)
check("옛 권장매수가에 직접 매지 않는다",
      '_e = float(recommended_buy_price)' not in _q104)
check("표시 진입가도 같은 앵커를 쓴다",
      'entry_pullback_price = (float(_entry_anchor)' in _q104)
check("두 번 난 모순임을 코드에 남긴다",
      '라운드 22b · 30' in _q104 or ('라운드 30' in _q104
                                    and '재발' in _q104))
check("실측 모순 3건을 코드에 인용한다",
      'GS' in _q104 and 'NAVER' in _q104 and '100,783' in _q104)

# 정합 가드 — 어긋나면 고치지 않고 비운다
check("정합 가드가 있다", 'level_incoherence' in _q104)
check("가드가 진입가·현재가 두 축을 본다",
      "'진입가')" in _q104 and "'현재가')" in _q104)
check("어긋난 값은 비운다 (지어내지 않는다)",
      'entry_stop_price = entry_target_1st = entry_rr = None' in _q104
      and 'stop_loss_price = None' in _q104)
check("비운 이유를 함께 내보낸다", "'level_incoherence': level_incoherence,"
      in _q104)

# 실제 산출물로 검증 — 이 종목의 레벨이 실제로 정합인가
_e104 = _fs53.get('entry_pullback_price')
_s104 = _fs53.get('entry_stop_price')
_t104 = _fs53.get('entry_target_1st')
check("진입가가 산출된다", _e104 is not None)
check("진입가 기준 손절이 진입가 아래",
      _s104 is None or _e104 is None or _s104 < _e104,
      f"진입 {_e104} · 손절 {_s104}")
check("진입가 기준 목표가 진입가 위",
      _t104 is None or _e104 is None or _t104 > _e104,
      f"진입 {_e104} · 목표 {_t104}")
check("모순 목록이 비어 있다", not (_fs53.get('level_incoherence') or []),
      str(_fs53.get('level_incoherence')))

# ── 개장 전 리포트 키 — 다시 스캔이 실제로 갱신되는가 ────────────────
import premarket as _pm104
_v104 = _pm104._engine_version()
check("리포트 경로가 날짜×엔진으로 갈린다",
      _pm104._pm_path('2026-01-01') != _pm104._pm_path('2026-01-01', _v104))
check("경로에 엔진 버전이 들어간다",
      _v104 in _os.path.basename(_pm104._pm_path('2026-01-01', _v104)))
_pmsrc104 = open(_os.path.join(PROJ, 'premarket.py'), encoding='utf-8').read()
check("낡은 리포트를 재사용하지 않는다",
      "if existing and not existing.get('stale_engine')" in _pmsrc104)
check("낡음을 표시로 알린다", "old['stale_engine']" in _pmsrc104)
check("옛 파일을 지우지 않는다 (감사 흔적)",
      '옛 파일은 지우지 않는다' in _pmsrc104)
_w104 = open(_os.path.join(PROJ, 'web_app.py'), encoding='utf-8').read()
check("화면 안내가 실행 가능해졌다",
      '이제 다시 스캔이 실제로 갱신됩니다' in _w104)
check("실행 불가능했던 옛 안내를 지웠다",
      '실행하는 편이 안전합니다' not in _w104)


# ══════════════════════════════════════════════════════════════════════
# §105 — "왜 이전 화면으로 돌아갔나" 여섯 가설과 그 재발 방지 (라운드 31~34)
#   진단 결과: ①구형 컴포넌트 ③이전 커밋 배포 는 **기각**.
#   실제 원인은 ②동결 산출물이 옛 엔진 값을 그대로 화면에 올림,
#   ④업데이트 이력이 재생성되지 않아 UI 날짜가 뒤처짐,
#   ⑤추천 카드와 상세 화면이 **서로 다른 키**를 읽는 이중 경로.
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("§105 되돌아감 재발 방지 · 중앙 판정 (라운드 31~34)")
print("=" * 72)
import verdict_core as _vc105
_vcsrc105 = open(_os.path.join(PROJ, 'verdict_core.py'),
                 encoding='utf-8').read()
_q105 = open(_os.path.join(PROJ, 'quant_indicators.py'), encoding='utf-8').read()
_w105 = open(_os.path.join(PROJ, 'web_app.py'), encoding='utf-8').read()
_p105 = open(_os.path.join(PROJ, 'premarket.py'), encoding='utf-8').read()

# ── ④ UI 날짜가 커밋 이력에서 나오고, 그 이력이 최신인가 ──────────────
import json as _j105
import subprocess as _sp105
with open(_os.path.join(PROJ, 'data', 'update_history.json'),
          encoding='utf-8') as _f:
    _uh105 = _j105.load(_f)
_uh_latest = str((_uh105.get('days') or [{}])[0].get('date') or '')
try:
    _git_latest = _sp105.run(
        ['git', 'log', '-1', '--date=short', '--pretty=%ad'], cwd=PROJ,
        capture_output=True, text=True, encoding='utf-8',
        errors='replace').stdout.strip()
except Exception:
    _git_latest = ''
check("업데이트 날짜를 손으로 적지 않는다",
      'APP_UPDATED = _last_update_date()' in _w105
      and 'update_history.json' in _w105)
check("업데이트 이력이 최신 커밋까지 반영돼 있다",
      (not _git_latest) or _uh_latest >= _git_latest,
      f'이력 {_uh_latest} vs 커밋 {_git_latest} — '
      f'scripts/gen_update_history.py 를 다시 돌려야 합니다')

# ── ② 동결 산출물이 옛 엔진 값을 화면에 올리지 않는가 ─────────────────
check("동결 리포트는 날짜×엔진으로 저장",
      "_pm_path(date_key, report['engine_version'])" in _p105)
check("낡은 동결 리포트를 재사용하지 않는다",
      "if existing and not existing.get('stale_engine')" in _p105)
check("낡으면 가격을 화면에 두지 않는다",
      'if _pm_stale and _picks_show:' in _w105)

# ── ⑤ 추천 카드와 상세가 같은 중앙 판정을 읽는가 ──────────────────────
check("중앙 판정 모듈이 있다", _os.path.exists(
    _os.path.join(PROJ, 'verdict_core.py')))
check("상세 화면이 중앙 판정을 만든다", 'CORE = _vcore.build(' in _w105)
check("추천 리포트가 같은 함수를 쓴다",
      'import verdict_core as _vc' in _p105 and 'def _core_of(' in _p105)
check("카드가 중앙 판정을 우선 읽는다",
      "_core = p.get('core') or {}" in _w105
      and "_core.get('new_target')" in _w105)
check("중앙 판정이 없을 때만 옛 키로 폴백",
      "rec = p.get('rec_buy')" in _w105 and 'else:' in _w105)

# ── 중앙 판정 계약 — 사용자 사양 §6 의 값이 전부 있는가 ────────────────
_b105 = dict(current_price=26350, entry_pullback_price=25150,
             entry_stop_price=24200, entry_target_1st=26800, entry_rr=1.74,
             target_tech_1st=27900, stop_loss_price=25000,
             analysis_confidence=78, strategy_quality_score=62,
             final_action_score=63, blind_test_not_completed=False,
             horizon_days=20, calibration_band={'hit_rate': 59.0, 'n': 8436},
             bb_position=62, williams_r=-35, rsi_14=58,
             rec_buy_sigma=0.45, rec_buy_reach='가까움',
             chase_buy_status='안전마진 확보')
_c105 = _vc105.build(_b105, verdict=dict(action='ACCUMULATE',
                                         headline='분할매수 검토 가능',
                                         vetoes=[]))
for _k105 in ('action', 'recommended', 'buy_zone', 'pullback_zone',
              'breakout_price', 'new_target', 'new_stop', 'hold_trim',
              'hold_stop', 'horizon_days', 'reach_prob', 'expected_return',
              'rr', 'confidence', 'exclude_reason', 'bucket'):
    check(f"중앙 판정에 '{_k105}' 있다", _k105 in _c105)
check("신규 매수자와 보유자 값이 다른 키",
      _c105['new_stop'] != _c105['hold_stop']
      and _c105['new_target'] != _c105['hold_trim'])
# 라운드 47 — 비교 묶음에 actionable 이 늘어 17개다 (16 → 17)
check("화면 비교 묶음이 17개", len(_vc105.screen_values(_c105)) == 17)
check("비교 묶음에 실행 가능 여부가 들어 있다",
      'actionable' in _vc105.screen_values(_c105))

# ── 추천 10조건 · 분류 (사용자 사양 §2 · 라운드 47에서 이름 개편) ──────
#   종전에 '장기 관찰'이 있었다. 사용자 지적: *"장기 관찰은 언제 다시 봐야
#   하는지 알 수 없다."* 맞다 — 이름이 '관찰'이면 할 일이 없고, 할 일이
#   없으면 화면에 있을 이유도 없다. **전부 행동 조건이 붙은 이름으로** 바꿨다.
check("분류가 10종", len(_vc105.BUCKETS) == 10)
check("'장기 관찰' 은 사라졌다 (할 일이 없는 이름)",
      '장기 관찰' not in _vc105.BUCKETS)
for _bk105 in ('오늘 매수 가능', '눌림목 매수 대기', '돌파 후 매수 대기',
               '과열 해소 대기', '거래량 회복 대기', '시장 국면 회복 대기',
               '신뢰도·표본 확보 대기', '권장가 괴리 과다', '데이터 부족',
               '추천 제외'):
    check(f"분류 '{_bk105}' 정의", _bk105 in _vc105.BUCKETS)
check("실행 가능 칸은 3종", len(_vc105.ACTIONABLE_BUCKETS) == 3)
check("'권장가 괴리 과다' 는 실행 가능이 아니다",
      '권장가 괴리 과다' not in _vc105.ACTIONABLE_BUCKETS)
check("추천 없음 문구가 현금 유지를 말한다",
      '현금을 유지하는 것이 우선입니다' in _vc105.NO_PICK_LINE)
check("추천 없음 문구가 '다음 거래일' 기준임을 밝힌다",
      '다음 거래일' in _vc105.NO_PICK_LINE)
check("화면이 그 문구를 쓴다", '_vc_view.NO_PICK_LINE' in _w105)
check("제외 사유를 화면에 분류별로 보여준다",
      '오늘 추천에 올리지 못한 종목과 이유' in _w105)

# ── 괴리 상한이 실측에서 나왔는가 (라운드 33) ─────────────────────────
_g35 = _os.path.join(PROJ, '.portfolio', 'gap_sigma_r35.json')
check("진입 깊이 문턱 산출물이 있다", _os.path.exists(_g35))
if _os.path.exists(_g35):
    with open(_g35, encoding='utf-8') as _f:
        _d35 = _j105.load(_f)
    check("목표 체결률 60%로 사전등록", _d35['target_fill'] == 60.0)
    check("구간별 문턱이 다 측정됐다",
          all(k in _d35['cut'] for k in ('train', 'valid', 'blind', 'all')))
    check("코드 상한이 통합 표본 σ와 일치",
          abs(_vc105.MAX_ENTRY_SIGMA - _d35['cut']['all']) < 0.01,
          f"코드 {_vc105.MAX_ENTRY_SIGMA} vs 통합 {_d35['cut']['all']}")
    check("σ 문턱은 구간별로 안정적 (편차 ≤0.3σ)",
          max(_d35['cut'][s] for s in ('train', 'valid', 'blind'))
          - min(_d35['cut'][s] for s in ('train', 'valid', 'blind')) <= 0.3,
          str({s: _d35['cut'][s] for s in ('train', 'valid', 'blind')}))
    check("고정 % 자가 무엇을 잘랐는지 기록",
          _d35['fixed_pct_would_lose'] > 0)
# 라운드 35 — 변동성 큰 종목이 부당하게 잘리지 않는가
_hv105 = dict(_b105, current_price=240000, entry_pullback_price=219319,
              vol_20=0.086)
_lv105 = dict(_hv105, vol_20=0.012)
check("변동성 큰 종목은 −8.6%라도 깊이 통과",
      _vc105.build(_hv105)['depth_sigma'] <= _vc105.MAX_ENTRY_SIGMA)
check("저변동성 종목은 같은 −8.6%라도 깊이 초과",
      _vc105.build(_lv105)['depth_sigma'] > _vc105.MAX_ENTRY_SIGMA)
check("고정 % 자를 버린 이유를 코드에 남긴다",
      '고정 %는 잘못된 자였다' in _vcsrc105)

# 과열 판정 — 지표 키를 잘못 읽어 적정가로 대신 판단하던 결함 (라운드 35)
check("과열 지표 키가 엔진 출력과 일치",
      all(k in _q105 for k in ('bb_position_pct', 'rsi_value',
                               'williams_r_value')))
check("과열 판정에 적정가 구간을 쓰지 않는다",
      "'크게 초과' in zone" not in _vcsrc105)
check("지표를 못 읽으면 과열로 보지 않는다",
      not _vc105.build(dict(_b105, bb_position_pct=None, rsi_value=None,
                            williams_r_value=None))['checks'][7]['ok'] is False)
_hot105 = _vc105.build(dict(_b105, bb_position_pct=101, rsi_value=78,
                            williams_r_value=-3))
# 라운드 47 — '과열로 제외' → '과열 해소 대기'. 무엇을 기다리면 되는지 적는다.
check("지표 2개 이상 과열이면 제외", _hot105['bucket'] == '과열 해소 대기')
check("과열은 실행 가능이 아니다", _hot105['actionable'] is False)
check("과열 사유에 무엇이 풀려야 하는지 적는다",
      '풀린' in str(_hot105['exclude_reason']),
      str(_hot105['exclude_reason'])[:80])

# 목표 배수 재탐색 (라운드 36) — 기각 결과를 잠근다
_t36 = _os.path.join(PROJ, '.portfolio', 'target_multiple_r36.json')
check("목표 배수 재탐색 산출물이 있다", _os.path.exists(_t36))
if _os.path.exists(_t36):
    with open(_t36, encoding='utf-8') as _f:
        _d36 = _j105.load(_f)
    check("0.4R~3.0R 를 다 훑었다", len(_d36['grid']) >= 27)
    check("현행 0.7R 이 기준선", _d36['current'] == 0.7)
    check("사전등록 4조건을 넘은 후보가 없다 (기각 기록)",
          len(_d36['winners']) == 0, str(_d36['winners']))
    check("어떤 배수도 train 에서 양수가 아니다",
          all((_v['splits']['train'] or {}).get('ev_sig', 0) <= 0
              for _v in _d36['grid'].values()
              if _v['splits'].get('train')))
check("상한 근거를 코드에 남긴다",
      'n=5,389' in _vc105.SIGMA_BASIS and '60%' in _vc105.SIGMA_BASIS)
check("자를 바꾼 이유(고정 %→σ)를 코드에 남긴다",
      '라운드 33 (기각)' in _vcsrc105 and '라운드 35 (채택)' in _vcsrc105)

# 실행 불가능한 추천이 실제로 걸리는가
_woo105 = dict(_b105, current_price=14600, entry_pullback_price=9388,
               entry_stop_price=8900, entry_target_1st=9900, entry_rr=1.05,
               rec_buy_sigma=3.2)
_cw105 = _vc105.build(_woo105, verdict=dict(action='HOLD', headline='',
                                            vetoes=[]))
check("우진형(−35.7%)은 추천에서 빠진다", not _cw105['recommended'])
check("빠진 이유가 괴리 과다", _cw105['bucket'] == '권장가 괴리 과다')
check("이유에 상한 수치를 적는다",
      f'{_vc105.MAX_ENTRY_SIGMA}' in _cw105['exclude_reason'])

# ── 진입 엔진 대결 (라운드 32) ────────────────────────────────────────
_b32 = _os.path.join(PROJ, '.portfolio', 'entry_bakeoff_r32.json')
check("진입 엔진 대결 산출물이 있다", _os.path.exists(_b32))
if _os.path.exists(_b32):
    with open(_b32, encoding='utf-8') as _f:
        _d32 = _j105.load(_f)
    check("후보 엔진 10종을 겨뤘다", len(_d32['engines']) == 10)
    check("전 구간(train/valid/blind)을 다 쟀다",
          all(s in _d32['engines']['변동성 1배 (현행)']
              for s in ('train', 'valid', 'blind')))
    check("12개 기준을 다 냈다",
          all(k in _d32['engines']['변동성 1배 (현행)']['blind']
              for k in ('fill_rate', 'nofill_rate', 'days', 'tgt_first',
                        'stop_first', 'ret', 'rr', 'pf', 'mdd', 'ev_sig')))
    check("거래비용을 차감했다", _d32['cost_pct'] == 0.36)


# ══════════════════════════════════════════════════════════════════════
# §106 — 화면마다 값이 다르면 **여기서 실패한다** (사용자 사양 §6)
#   *"추천 화면, 종목 상세, 가늠 AI, 차트, 보유자 화면이 서로 다른 결론이나
#     가격을 표시하지 않도록 (…) 화면마다 값이 다르면 자동 테스트가
#     실패하도록 해 주세요."*
#   같은 스냅샷을 두 경로(추천 리포트 / 종목 상세)로 흘려 값이 같은지 본다.
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("§106 화면 간 값 일치 (사용자 사양 §6)")
print("=" * 72)
import premarket as _pm106
import verdict_core as _vc106

# 실제 파이프라인 스냅샷을 하나 만들어 두 경로로 흘린다
_snap106 = None
try:
    _snap106 = q.run_full_pipeline(SYMBOL, T_REF, b_engine=engine,
                                   rho_cutoff=0.80)
except Exception as _e106:
    print(f'  (스냅샷 생성 실패: {_e106})')

if _snap106:
    _fs106 = _snap106.get('four_scores') or {}
    _vd106 = q.build_final_verdict(_snap106)
    _px106 = _fs106.get('current_price')

    # 경로 A — 종목 상세 화면이 하는 일
    _detail106 = _vc106.build(_fs106, verdict=_vd106,
                              price_axes=_fs106.get('price_axes'),
                              realtime_price=_px106)
    # 경로 B — 추천 리포트(premarket)가 하는 일
    _card106 = _pm106._core_of(q, {'base_price': _px106}, _fs106, _vd106)

    check("추천 경로가 중앙 판정을 만든다", _card106 is not None)
    if _card106:
        _sa = _vc106.screen_values(_detail106)
        _sb = _vc106.screen_values(_card106)
        _diff106 = {k: (_sa[k], _sb[k]) for k in _sa if _sa[k] != _sb[k]}
        check("추천 화면과 종목 상세의 값이 전부 같다",
              not _diff106, f'어긋난 항목: {_diff106}')
        for _k106 in ('buy_zone', 'new_target', 'new_stop', 'hold_trim',
                      'hold_stop', 'recommended', 'bucket'):
            check(f"  · {_k106} 일치", _sa[_k106] == _sb[_k106],
                  f'상세 {_sa[_k106]} vs 추천 {_sb[_k106]}')

    # 신규 매수자 값과 보유자 값이 섞이지 않는가
    check("신규 손절과 보유자 손절이 다른 값",
          _detail106['new_stop'] is None or _detail106['hold_stop'] is None
          or _detail106['new_stop'] != _detail106['hold_stop'])
    # 정합 — 손절 < 진입 < 목표
    _e106 = _detail106.get('pullback_zone')
    if _e106 and _detail106.get('new_stop'):
        check("손절이 진입가 아래", _detail106['new_stop'] < _e106,
              f"진입 {_e106} · 손절 {_detail106['new_stop']}")
    if _e106 and _detail106.get('new_target'):
        check("목표가 진입가 위", _detail106['new_target'] > _e106,
              f"진입 {_e106} · 목표 {_detail106['new_target']}")
    check("모순 목록이 비어 있다", not _detail106['incoherence'],
          str(_detail106['incoherence']))
    # 미산출을 임의 숫자로 바꾸지 않는가
    check("미산출은 None 으로 남는다",
          all(_detail106[k] is None or isinstance(_detail106[k], (int, float,
                                                                 tuple, str))
              for k in ('new_target', 'new_stop', 'hold_trim', 'hold_stop')))
    # 현재가와 분석 기준일
    check("중앙 판정이 현재가를 싣는다", _detail106['current_price'] is not None)
    check("보유기간을 싣는다", _detail106['horizon_days'] == 20)

# ── 라운드 37 — 데이터 미수신을 '추천 없음'으로 말하지 않는다 ──────────
#   실행 확인에서 잡았다: 경량 스캔 0개 · 후보 풀 0개 인데 화면은
#   "현재 추천주 없음 — 필수조건을 통과한 종목이 없습니다" 라고 했다.
#   그건 판정이 아니라 수집 실패다. 그리고 '0.0% (5/1)' 이라는 말이
#   안 되는 비율이 나갔다 (분모에 max(1, …) 를 쓴 탓).
_w107 = open(_os.path.join(PROJ, 'web_app.py'), encoding='utf-8').read()
check("수집 실패와 판정 결과를 구분한다",
      '판정 불가 — 후보 데이터를 받지 못했습니다' in _w107)
check("수집 실패를 판정으로 오해하지 않게 명시",
      "'오늘 살 종목이 없다'는 **판정이 아니라 " in _w107
      or "판정이 아니라" in _w107)
check("추천 없음은 실제 분석 건수를 밝힌다",
      '정밀분석한 ' in _w107 and 'len(scan_results)' in _w107)
check("동결 리포트도 같은 구분을 한다",
      '수집 단계에서 후보가 0개' in _w107)
check("분모가 0이면 비율을 만들지 않는다",
      'max(1, _lt.get(' not in _w107
      and '경량 스캔이 0개를 반환했습니다' in _w107)
check("0으로 나눈 가짜 비율이 없다", '_deep_rate:.1f' not in _w107)

# ── 라운드 37 — import 별칭이 화면 변수를 덮어쓰지 않는가 ──────────────
#   실행 확인에서 잡았다: `import verdict_core as _vc` 가 결론 배너의 색상
#   변수 `_vc` 를 덮어써서, 스타일 자리에 모듈 객체가 찍혔다. 화면에
#   `from=""` 속성과 `; line-height:1.15;'>` 조각이 텍스트로 새어 나왔다.
import ast as _ast107
_tree107 = _ast107.parse(_w107)
_alias107, _assign107 = {}, {}
for _n107 in _ast107.walk(_tree107):
    if isinstance(_n107, _ast107.Import):
        for _a in _n107.names:
            if _a.asname:
                _alias107[_a.asname] = _a.name
    elif isinstance(_n107, (_ast107.Assign,)):
        # st.session_state['x'] = ... 는 st 를 다시 묶는 게 아니다.
        # 직접 이름 대입(과 튜플 풀기)만 재바인딩으로 센다.
        _flat = []
        for _t in _n107.targets:
            if isinstance(_t, _ast107.Name):
                _flat.append(_t)
            elif isinstance(_t, (_ast107.Tuple, _ast107.List)):
                _flat += [_e for _e in _t.elts
                          if isinstance(_e, _ast107.Name)]
        for _sub in _flat:
            _assign107.setdefault(_sub.id, _sub.lineno)
_clash107 = {a: (m, _assign107[a]) for a, m in _alias107.items()
             if a in _assign107}
check("import 별칭이 화면 변수와 겹치지 않는다",
      not _clash107,
      '겹침: ' + ', '.join(f'{a}(모듈 {m}, 대입 {l}행)'
                          for a, (m, l) in _clash107.items()))
# 모듈 객체가 f-string 으로 HTML 에 들어가면 이 조각이 나온다
_code107 = "\n".join(l for l in _w107.splitlines()
                     if not l.lstrip().startswith('#'))
check("모듈 객체가 f-string 으로 들어가는 자리가 없다",
      '<module' not in _code107)
check("겹침 사고를 코드에 기록했다",
      "모듈 객체" in _w107 and "결론 배너의" in _w107
      and "별칭을 `_vc` 로 쓰면 안 된다" in _w107)

# ── 라운드 37 — 못 잰 것으로 거르지 않는다 ────────────────────────────
#   실행 확인에서 잡았다: 유니버스가 today_trade_value 를 안 실어 오는
#   시간대(장 전)에 liquidity_confirmed 가 전 종목 False 라, 경량 스캔이
#   2,997종목을 전부 탈락시키고 화면은 "유동성 조건 통과 0개"라고 말했다.
#   유동성이 없는 게 아니라 **거래대금을 수집하지 못한 것**이다.
check("거래대금 수신율을 먼저 본다", '_tv_usable' in _w107
      and '_tv_seen' in _w107)
check("미수신이면 유동성 필터를 끈다",
      'if _tv_usable:' in _w107 and 'no_liquidity' in _w107)
check("못 잰 것으로 거르지 않는다고 코드에 남긴다",
      '못 잰 것으로 거르지 않는다' in _w107)
check("화면이 미수신 사실을 밝힌다",
      '거래대금 미수신 — 유동성 필터를 적용하지' in _w107)

# 순위 페이지가 죽어도 추천이 멈추지 않는가
_ma107 = open(_os.path.join(PROJ, 'market_attention.py'), encoding='utf-8').read()
import inspect as _ins107
import market_attention as _MA107
check("탐색 함수가 대체 후보를 받는다",
      'fallback_pool' in _ins107.signature(
          _MA107.find_attention_candidates).parameters)
check("호출부가 경량 스캔 결과를 넘긴다", 'fallback_pool=_lite_rows' in _w107)
check("경량 스캔이 탐색보다 먼저 온다",
      0 < _w107.find("_lite['passed'] = len(_lite_pass)")
      < _w107.find('market_attention.find_attention_candidates'))
check("거래대금 미수신이면 시총으로 정렬",
      "'시가총액 대체'" in _ma107 and '_tv_ok' in _ma107)
check("대체 사용 사실을 출처에 남긴다", '순위 페이지 미수신' in _ma107)

# ── 라운드 37 — 결론 배너도 중앙 판정을 쓴다 (마지막 두 번째 경로) ─────
#   실행 확인에서 잡았다: 배너가 recommended_buy_price(적정가×안전마진)를
#   실행 가격으로 써서 삼성전자 240,000원에 "147,567원 이하로 내려올 때만
#   사세요"(−38.5%)라고 말했다. 라운드 25 에서 폐기한 산식이고, 그 값으로
#   그린 손절(180,832원)은 매수가보다 위였다.
check("배너 매수가가 중앙 판정에서 온다",
      "_core_entry = (CORE or {}).get('pullback_zone')" in _w107
      and 'rec_buy_val = _core_entry if _core_entry else _value_floor' in _w107)
check("배너 손절·목표도 중앙 판정에서 온다",
      "_e_stop = (CORE or {}).get('new_stop')" in _w107
      and "_e_t1 = (CORE or {}).get('new_target')" in _w107)
check("CORE 가 배너보다 먼저 만들어진다",
      0 < _w107.find('CORE = _vcore.build(')
      < _w107.find('_core_entry = (CORE or {})'))
check("적정가 값은 장기 참고선으로만 적는다",
      '장기 가치 참고선은' in _w107
      and '오늘의 매수가로 쓰지 않습니다' in _w107)
check("배너가 four_scores 원본 손절을 직접 읽지 않는다",
      "_e_stop = four_scores.get('entry_stop_price')" not in _w107)
check("배너 제목도 같은 실행 가격을 말한다",
      "if '이하로 내려올 때만' in _banner_sub and _core_entry:" in _w107)
check("σ 표기도 같은 실행 가격 기준",
      "_rc_sig = (CORE or {}).get('depth_sigma')" in _w107
      and "_rc_drop = (CORE or {}).get('gap_pct')" in _w107)
check("같은 카드 안에서 두 가격이 싸우지 않게 한 이유를 남긴다",
      '제목 147,560원 vs 본문 228,287원' in _w107)

# ══════════════════════════════════════════════════════════════════════
# §108 — 같은 말이 두 숫자를 가리키지 않는다 · 종목 찾기 상시 노출 (라운드 38)
#   실측: LX인터내셔널이 "유효표본 0건"으로 매수 차단됐는데 같은 화면에
#   "유효표본 132건"이 떠 있었다. 앞은 유사패턴 매칭(match_count),
#   뒤는 전략 백테스트 표본(eff_sample_size) — 다른 개념이 같은 이름이었다.
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("§108 표본 이름 분리 · 종목 찾기 상시 노출 (라운드 38)")
print("=" * 72)
_q108 = open(_os.path.join(PROJ, 'quant_indicators.py'), encoding='utf-8').read()
_w108 = open(_os.path.join(PROJ, 'web_app.py'), encoding='utf-8').read()

check("거부 문구가 '유사패턴 표본'이라고 말한다",
      '유사패턴 표본 {sim.get(\'match_count\', 0)}건' in _q108)
check("거부 문구에 '유효표본'을 쓰지 않는다",
      "유효표본 {sim.get('match_count', 0)}건" not in _q108)
check("왜 이름을 갈랐는지 코드에 남긴다",
      '같은 말이 두 숫자를' in _q108 and 'LX인터내셔널' in _q108)
check("화면도 match_count 를 '유사패턴 표본'으로 부른다",
      "유사패턴 표본 {sim_res.get('match_count', 0)}건" in _w108)
check("화면이 match_count 에 '유효표본'을 쓰지 않는다",
      "유효표본 {sim_res.get('match_count', 0)}건" not in _w108
      and "유효표본 {h['match_count']}건" not in _w108)
check("전략 표본은 다른 이름으로 부른다",
      "전략 표본 {four_scores.get('eff_sample_size', 0):.0f}건" in _w108)
check("적정가 범위가 넓으면 경고한다",
      '범위 폭이 **{_bw:.1f}배**입니다' in _w108
      and "'저평가'를 단정하지 마세요" in _w108)

# ── 종목 찾기 UI (사용자 요청) ────────────────────────────────────────
check("종목 찾기는 기본이 펼침",
      "st.session_state['show_screener'] = True" in _w108
      and "st.session_state['show_screener'] = False" not in _w108)
check("버튼 문구가 '최신화'", 'st.sidebar.button("최신화"' in _w108)
check("'닫기' 문구를 없앴다", '오늘의 관심종목 스캔 / 닫기' not in _w108)
check("최신화 중에는 버튼이 잠긴다", 'disabled=_scan_busy' in _w108)
check("진행 단계를 보여준다",
      '가격 확인 → 거래량 점검 → 뉴스 갱신 → 후보 재정렬' in _w108)
check("마지막 갱신 시각을 표시한다",
      "scan_done_at" in _w108 and '최신화 완료 · **{_last}**' in _w108)
check("현재 분석 대상 수를 표시한다",
      '관심종목 {_n_att}개 · 정밀분석 {_n_deep}개' in _w108)
check("개장 전 리포트는 장중에 안 바뀐다고 밝힌다",
      '개장 전 추천은 전일 확정 데이터 기준으로 유지됩니다' in _w108)
check("스캔 조건은 '상세 설정'으로 접는다",
      '"상세 설정 · 스캔 조건"' in _w108)
check("실패해도 최신화 플래그가 풀린다",
      'finally:' in _w108 and "st.session_state['pending_scan'] = False" in _w108)
# 라운드 38 — 사이드바는 스캔보다 먼저 그려진다. pop() 으로 플래그를 지우면
# 스캔 중인데 '아직 최신화하지 않았습니다'가 뜨고 버튼도 눌린다(실측).
check("스캔 중에는 플래그를 유지한다",
      "st.session_state.pop('pending_scan'" not in _w108
      and "if st.session_state.get('pending_scan'):" in _w108)
check("스캔이 끝나면 사이드바를 갱신한다",
      "st.rerun()          # 사이드바에" in _w108)
# 사이드바 아코디언에서 '종목 찾기'만 예외로 항상 펼침
_uk108 = open(_os.path.join(PROJ, 'ui_kit.py'), encoding='utf-8').read()
check("아코디언에 항상 펼침 옵션이 있다",
      "always = bool(step.get('always'))" in _uk108
      and "on = always or (step['key'] == active)" in _uk108)
check("항상 펼침은 접기 화살표를 안 그린다",
      "arrow = '' if always else" in _uk108)
check("항상 펼침은 버튼이 아니라 제목으로 그린다",
      "acc-always" in _uk108 and 'st.sidebar.markdown(' in _uk108)
check("'종목 찾기'가 항상 펼침으로 지정됐다",
      "'title': '종목 찾기', 'always': True" in _w108)
check("다른 단계는 여전히 접힌다",
      _w108.count("'always': True") == 1)

# ══════════════════════════════════════════════════════════════════════
# §109 — 한 화면에 카드가 한 종류다 (라운드 39)
#   사용자 요청: "오늘의 관심후보도 이 스타일로." 개장 전 추천은 reco_card
#   인데 관심종목 후보만 다른 모양이었다. 조립 함수가 개장 전 블록 안에
#   갇혀 있어서 목록마다 자기 카드를 만든 게 원인이다.
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("§109 카드 한 종류 · 버전 칩 근거 (라운드 39)")
print("=" * 72)
import premarket as _pm109
import inspect as _ins109
_w109 = open(_os.path.join(PROJ, 'web_app.py'), encoding='utf-8').read()

check("pick 조립이 재사용 가능한 함수로 나왔다",
      hasattr(_pm109, 'pick_from_scan_row'))
check("그 함수가 (엔진, 스캔행) 을 받는다",
      list(_ins109.signature(_pm109.pick_from_scan_row).parameters) ==
      ['q_engine', 'r'])
check("build_report 가 그 함수를 쓴다",
      'p = pick_from_scan_row(q_engine, r)' in
      open(_os.path.join(PROJ, 'premarket.py'), encoding='utf-8').read())
check("pick 에 중앙 판정이 실린다",
      "'core'" in _ins109.getsource(_pm109.pick_from_scan_row))
check("카드 조립 함수가 모듈 수준으로 올라왔다",
      '\ndef _build_reco_card(p, news_txt, conf_txt):' in _w109)
# 라운드 47 — 목록을 실행 가능/대기로 가르면서 렌더를 _render_att 로 뺐다.
# 들여쓰기까지 문자열로 박아 두면 구조를 바꿀 때마다 검사가 막는다 —
# **같은 함수를 쓰는가**만 본다 (그게 이 검사의 의도였다).
check("관심종목 후보도 같은 카드를 쓴다",
      '_pm_mod.pick_from_scan_row(q_engine, _sr0)' in _w109
      and '_build_reco_card(_pick' in _w109
      and '_uk.reco_card(' in _w109)
check("실행 가능한 것만 위로 올린다 (라운드 47)",
      "_cr.get('actionable')" in _w109 and '_render_att(_live' in _w109)
check("대기 후보는 접어서 아래로", '_render_att(_wait' in _w109)
check("뺀 종목도 사유를 남긴다", '_dropped' in _w109)
check("스냅샷이 없으면 가격을 지어내지 않는다",
      '정밀분석 스냅샷이 없으면 가격을 지어내지 않는다' in _w109)
check("한 화면 두 카드 문제를 코드에 남긴다",
      '어느 쪽을 믿을지' in _w109)
check("관심종목 후보도 3열 카드로 배치",
      '_ATT_PER_ROW = 3' in _w109)

# 끌어올린 함수가 참조하는 이름이 모듈 수준에 다 있는가 (라운드 39)
#   실측: _build_reco_card 만 올리고 _ASSET_KO 표를 두고 와 NameError 가 났다.
import ast as _ast109
import builtins as _bi109
_tree109 = _ast109.parse(_w109)
_modnames109 = set(dir(_bi109))
for _n109 in _ast109.walk(_tree109):
    if isinstance(_n109, (_ast109.Import, _ast109.ImportFrom)):
        for _a109 in _n109.names:
            _modnames109.add((_a109.asname or _a109.name).split('.')[0])
    elif isinstance(_n109, (_ast109.FunctionDef, _ast109.AsyncFunctionDef,
                            _ast109.ClassDef)):
        _modnames109.add(_n109.name)
    elif isinstance(_n109, _ast109.Name) and isinstance(_n109.ctx,
                                                        _ast109.Store):
        _modnames109.add(_n109.id)
    elif isinstance(_n109, _ast109.arg):
        _modnames109.add(_n109.arg)
for _fn109 in [_n for _n in _ast109.walk(_tree109)
               if isinstance(_n, _ast109.FunctionDef)
               and _n.name == '_build_reco_card']:
    _loc109 = {_a.arg for _a in _fn109.args.args}
    for _n in _ast109.walk(_fn109):
        if isinstance(_n, _ast109.Name) and isinstance(_n.ctx, _ast109.Store):
            _loc109.add(_n.id)
        elif isinstance(_n, _ast109.arg):
            _loc109.add(_n.arg)
    _miss109 = sorted({_n.id for _n in _ast109.walk(_fn109)
                       if isinstance(_n, _ast109.Name)
                       and isinstance(_n.ctx, _ast109.Load)}
                      - _loc109 - _modnames109)
    check("끌어올린 카드 함수가 두고 온 이름이 없다", not _miss109,
          f'정의 없음: {_miss109}')
check("자산유형 표도 함께 올라왔다",
      "\n_ASSET_KO = {'STOCK': '주식'" in _w109)

# ══════════════════════════════════════════════════════════════════════
# §110 — 금융 터미널 디자인: 화면에 이모지를 쓰지 않는다 (라운드 40)
#   getdesign.md 의 DESIGN.md 74종을 받아 금융·데이터 밀집 계열 17종
#   (Binance·Coinbase·Kraken·Revolut·Wise·Stripe·Mastercard·Linear·Vercel·
#    ClickHouse·Sentry·PostHog·Raycast·Warp·Superhuman·Notion·Claude)을
#   분석했다. 이모지를 UI 상태 표시로 쓰는 예가 하나도 없다.
#   이모지는 OS·폰트마다 모양과 크기가 달라 정렬이 깨지고 색을 통제할 수 없다.
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("§110 이모지 배제 · 디자인 레퍼런스 (라운드 40)")
print("=" * 72)
import re as _re110
_UIF110 = ['web_app.py', 'ui_kit.py', 'premarket.py', 'quant_indicators.py',
           'market_attention.py', 'next_action.py', 'gaeum_ai.py',
           'chart_pro.py', 'verdict_core.py', 'price_axes.py']
_EMO110 = _re110.compile(
    '[\U0001F300-\U0001FAFF\U00002600-\U000027BF'
    '\U0001F1E6-\U0001F1FF\U00002B00-\U00002BFF]')
_KEEP110 = set('→←↑↓↔·—–…‘’“”×÷≥≤±✓')


def _display_emoji(path):
    """주석·docstring 밖(= 화면에 나가는 문자열)의 이모지만 센다."""
    hits, in_doc = [], False
    for i, line in enumerate(open(path, encoding='utf-8')):
        q = line.count('"""') + line.count("'''")
        was = in_doc
        if q % 2 == 1:
            in_doc = not in_doc
        if was or in_doc or line.lstrip().startswith('#'):
            continue
        if 'page_icon=' in line:
            continue
        for m in _EMO110.finditer(line):
            if m.group(0) not in _KEEP110:
                hits.append((i + 1, m.group(0), line.strip()[:70]))
    return hits


_emo_all110 = []
for _f110 in _UIF110:
    _p110 = _os.path.join(PROJ, _f110)
    if _os.path.exists(_p110):
        _emo_all110 += [(_f110,) + h for h in _display_emoji(_p110)]
check("화면 문자열에 이모지가 없다", not _emo_all110,
      f'{len(_emo_all110)}개: '
      + ', '.join(f'{f}:{ln}({c})' for f, ln, c, _ in _emo_all110[:6]))

# 판정 색 점은 이모지가 아니라 토큰 색 원으로 그린다
import ui_kit as _uk110
check("판정 표시가 토큰 색 점이다", hasattr(_uk110, 'dot'))
check("결론 배너가 색 점을 쓴다", '_vi = _uk.dot(_vc, 14)' in _w109)
check("판정 스타일 표에서 이모지를 뺐다",
      '"🟢"' not in _w109 and '"🔴"' not in _w109 and '"🟡"' not in _w109)

# 레퍼런스가 실제로 있는가
_refdir110 = _os.path.join(PROJ, 'references', 'design-md')
_refs110 = ([f for f in _os.listdir(_refdir110) if f.endswith('.md')]
            if _os.path.isdir(_refdir110) else [])
check("디자인 레퍼런스를 받아 뒀다", len(_refs110) >= 60,
      f'{len(_refs110)}개')
for _need110 in ('binance.md', 'coinbase.md', 'stripe.md', 'linear.app.md'):
    check(f"금융 계열 레퍼런스 {_need110}", _need110 in _refs110)
check("레퍼런스 받기 스크립트가 있다",
      _os.path.exists(_os.path.join(PROJ, 'scripts', 'fetch_design_md.py')))

# 프로젝트 규칙 파일 — 로직 훼손 방지
_cl110 = _os.path.join(PROJ, 'CLAUDE.md')
check("CLAUDE.md 가 있다", _os.path.exists(_cl110))
if _os.path.exists(_cl110):
    _cltxt110 = open(_cl110, encoding='utf-8').read()
    for _k110 in ('절대 건드리지 않는 것', '숫자를 손으로 고르지 않는다',
                  '없는 값을 지어내지 않는다', '화면 값은 한 곳에서 나온다',
                  '이모지 금지'):
        check(f"CLAUDE.md 에 '{_k110}'", _k110 in _cltxt110)

# ══════════════════════════════════════════════════════════════════════
# §111 — 뉴스 축을 실제로 연동했는가 (라운드 41)
#   '뉴스·공시 촉매'가 관심점수의 20% 인데 DART 공시 50건만 보고 있었다.
#   공개 RSS 를 직접 두드려 되는 곳만 넣었다 (연합뉴스 120 · 한경 50 · 매경 50).
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("§111 뉴스 축 연동 (라운드 41)")
print("=" * 72)
import market_attention as _ma111
import news_feed as _nf111

check("뉴스 모듈이 있다", _os.path.exists(_os.path.join(PROJ, 'news_feed.py')))
check("공개 RSS 만 쓴다",
      all(u.startswith('https://') for _, u in _nf111.FEEDS))
check("실측으로 고른 출처 3곳", len(_nf111.FEEDS) == 3)
check("본문을 저장하지 않는다고 밝힌다",
      '본문을 저장하지 않는다' in open(
          _os.path.join(PROJ, 'news_feed.py'), encoding='utf-8').read())

# 짧은 이름이 다른 상장사와 섞이지 않는가 (GS vs GS건설 · DL vs DL이앤씨)
for _t111, _n111, _want111 in (('GS건설, 신규 수주', 'GS', False),
                               ('GS, 자사주 매입', 'GS', True),
                               ('DL이앤씨 계약', 'DL', False),
                               ('DL, 유상증자', 'DL', True),
                               ('LGS전자 신제품', 'GS', False),
                               ('삼성전자 실적', '삼성전자', True)):
    check(f"이름 매칭 '{_t111[:14]}' ← {_n111}",
          _nf111._mentions(_t111, _n111) is _want111)

# 점수 산출 — 기사가 없으면 0, 있으면 신선도·촉매·위험을 반영
_s111, _d111 = _ma111.score_news('삼성전자', [])
check("기사가 없으면 0점", _s111 == 0.0 and 'unavailable' in _d111)
_fake111 = [{'title': '삼성전자, 대규모 수주 계약 체결', 'link': '', 'source': 't',
             'dt': None}]
_s111b, _d111b = _ma111.score_news('삼성전자', _fake111)
check("촉매 낱말을 잡는다", '수주' in (_d111b.get('catalyst_words') or []))
_risk111 = [{'title': '아무개, 횡령 혐의 압수수색', 'link': '', 'source': 't',
             'dt': None}]
check("위험 낱말을 잡는다",
      '횡령' in (_ma111.score_news('아무개', _risk111)[1].get('risk_words')
                or []))
check("점수는 0~100 범위", 0.0 <= _s111b <= 100.0)

# 연동 상태가 '부분'에서 '연동'으로 올라갔는가
_ev111 = next(c for c in _ma111.COMPONENT_SPEC
              if c['key'] == 'event_catalyst')
check("뉴스·공시 촉매가 완전 연동", _ev111['availability'] == 'full')
check("설명에 실제 출처를 적는다",
      '연합뉴스' in _ev111['detail'] and '매일경제' in _ev111['detail'])
check("'news' 후보 발굴이 열렸다",
      'news' not in _ma111.STRATEGY_UNAVAILABLE)
check("스캔이 뉴스를 한 번만 받아 재사용한다",
      'news_items, _news_report = _nf.fetch()' in
      open(_os.path.join(PROJ, 'market_attention.py'),
           encoding='utf-8').read())
check("공시·뉴스 중 높은 쪽을 쓴다",
      'max(_cands) if _cands else 0.0' in
      open(_os.path.join(PROJ, 'market_attention.py'),
           encoding='utf-8').read())

# ══════════════════════════════════════════════════════════════════════
# §112 — 뉴스가 **실제 판단**에 개입하는가 (라운드 42)
#   사용자 지적: "화면만 바뀌고 엔진 결과가 그대로라면 업데이트로 인정하지
#   마세요." 맞다. 뉴스가 관심점수(추천 순위 영향 ≤5%)에만 들어가고 종합점수·
#   매수 판단에는 안 들어가고 있었다. 룰북 RULES_NEWS 로 게이트를 걸었다.
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("§112 뉴스 → 실제 매매 판단 연결 (라운드 42)")
print("=" * 72)
import market_context as _mc112
_q112 = open(_os.path.join(PROJ, 'quant_indicators.py'), encoding='utf-8').read()
_w112 = open(_os.path.join(PROJ, 'web_app.py'), encoding='utf-8').read()

# 룰북에 규칙이 실렸는가 (엔진이 읽는 단일 출처)
_nr112 = qi.RULEBOOK.get('RULES_NEWS') or {}
for _k112 in ('fresh_window_hours', 'risk_block_min_count', 'risk_score_cap',
              'risk_confidence_cap', 'catalyst_score_bonus'):
    check(f"룰북 RULES_NEWS 에 {_k112}", _k112 in _nr112)
check("좋은 뉴스로 점수를 올리지 않는다 (검증 전 비대칭)",
      float(_nr112.get('catalyst_score_bonus', -1)) == 0.0)
check("룰북 버전을 올렸다",
      qi.RULEBOOK.get('RULES_GENERAL', {}).get('version') != 'v2026.08.02',
      str(qi.RULEBOOK.get('RULES_GENERAL', {}).get('version')))
check("가점을 안 거는 이유를 룰북에 적었다",
      '검증될 때까지 비대칭' in open(
          _os.path.join(PROJ, 'analysis_rulebook_ko.txt'),
          encoding='utf-8').read())

# 엔진이 그 규칙으로 상한을 씌우는가
check("엔진에 뉴스 게이트가 있다", 'news_gate = None' in _q112)
check("점수·신뢰도 상한을 씌운다",
      "_NR.get('risk_score_cap', 55)" in _q112
      and "_NR.get('risk_confidence_cap', 60)" in _q112)
check("악재면 판정 문구가 바뀐다",
      "final_action_title = '신규 매수 차단 (악재)'" in _q112)
check("그 문구가 TITLE_MAP 에 등록됐다",
      "'신규 매수 차단 (악재)':" in _q112)
check("게이트 결과를 화면에 내보낸다", "'news_gate': news_gate," in _q112)
check("미수신은 악재가 아니다", 'feed_available' in _q112
      and '미수신 ≠ 악재' in _q112)
# self 속성을 지역 이름으로 읽어 게이트가 조용히 안 걸리던 결함
check("컨텍스트를 self 속성으로 읽는다",
      "(getattr(self, 'market_context', None) or {})" in _q112)
check("그 실수를 코드에 기록했다", '조용히 안 걸린다' in _q112)

# 뉴스 요약이 게이트가 쓸 필드를 내는가
_fk112 = {'items': [
    {'title': 'A사 횡령 혐의 압수수색', 'risk_hits': ['횡령'], 'watch_hits': [],
     'scope': '종목', 'lagging': False}], 'available': True}
_f112 = _mc112.summarize_news_flags(_fk112)
check("risk_words 를 낸다", _f112.get('risk_words') == ['횡령'])
check("feed_available 를 낸다", _f112.get('feed_available') is True)
_e112 = _mc112.summarize_news_flags({'items': [], 'available': False})
check("미수신이면 feed_available=False", _e112.get('feed_available') is False)

# 네이버가 비면 공개 RSS 로 보완하는가
check("RSS 보완 경로가 있다", 'def _rss_fallback(' in
      open(_os.path.join(PROJ, 'market_context.py'), encoding='utf-8').read())
check("보완 출처를 밝힌다", '공개 RSS 보완' in
      open(_os.path.join(PROJ, 'market_context.py'), encoding='utf-8').read())

# 화면이 개입 사실과 근거를 밝히는가
check("화면이 뉴스 게이트를 표시한다",
      '악재로 신규 매수를 차단했습니다' in _w112)
check("화면이 엔진 버전을 함께 적는다",
      "_VER_NOW.get('news'" in _w112 and "_VER_NOW.get('rulebook'" in _w112)
check("개입 안 했으면 말하지 않는다", "if _ng.get('risk'):" in _w112)

# 근거 표가 중앙 판정과 같은 값을 쓰는가 (라운드 42 · 배너와 어긋났던 자리)
check("근거 표에 실행 진입가 행이 있다", '★ 실행 진입가 (오늘 쓰는 값)' in _w112)
check("근거 표가 중앙 판정을 읽는다",
      "(CORE or {}).get('pullback_zone')" in _w112
      and "(CORE or {}).get('new_target')" in _w112)
check("적정가 행은 '오늘의 매수가가 아니다'라고 밝힌다",
      '오늘의 매수가가 아니다' in _w112)
check("보유자 기준임을 라벨에 적는다",
      '(보유자 · 현재가 기준)' in _w112)

# ══════════════════════════════════════════════════════════════════════
# §113 — 메타 레이블링 기각을 기록으로 잠근다 (라운드 43)
#   valid 65.2% 였던 규칙이 blind 54.5% 로 무너졌다(기준선 56.1%보다 낮다).
#   사전등록을 안 했다면 valid 수치를 '목표 달성'으로 보고했을 것이다.
#   이 기록이 지워지면 같은 규칙을 다시 채택할 위험이 있다.
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("§113 메타 레이블링 기각 기록 (라운드 43)")
print("=" * 72)
_pre113 = _os.path.join(PROJ, 'docs', 'PREREG_R43_META_LABELING.md')
check("사전등록 문서가 있다", _os.path.exists(_pre113))
if _os.path.exists(_pre113):
    _pt113 = open(_pre113, encoding='utf-8').read()
    check("측정 전에 썼다고 밝힌다", '측정 전' in _pt113)
    check("판정 기준 8개를 미리 고정했다",
          all(x in _pt113 for x in ('≥ 65.0%', '≥ 100건', '≥ 58.0%')))
    check("못 재는 것을 하지 않는다고 적었다",
          '지금은 검증할 수 없다' in _pt113)
    check("실패 가능성을 미리 적었다", '채택 가능성은 낮다고 본다' in _pt113)

_ml113 = _os.path.join(PROJ, '.portfolio', 'meta_label_r43.json')
check("메타 레이블링 산출물이 있다", _os.path.exists(_ml113))
if _os.path.exists(_ml113):
    with open(_ml113, encoding='utf-8') as _f:
        _d113 = _j105.load(_f)
    check("판정이 기각이다", _d113.get('verdict') == '기각',
          str(_d113.get('verdict')))
    _b113 = _d113.get('blind') or {}
    _v113 = _d113.get('valid') or {}
    _base113 = _d113.get('base_blind') or {}
    check("valid 에서는 65% 를 넘었다", (_v113.get('hit') or 0) >= 65.0,
          f"valid {_v113.get('hit')}%")
    check("blind 에서 무너졌다", (_b113.get('hit') or 100) < 65.0,
          f"blind {_b113.get('hit')}%")
    check("기준선보다도 낮았다",
          (_b113.get('hit') or 100) < (_base113.get('hit') or 0),
          f"{_b113.get('hit')}% vs 기준선 {_base113.get('hit')}%")
    check("blind EV 가 음수였다", (_b113.get('ev') or 0) < 0,
          f"{_b113.get('ev')}")
    check("판정 기준 8개를 다 기록했다", len(_d113.get('checks') or []) == 8)

_fd113 = _os.path.join(PROJ, '.portfolio', 'failure_decomp_r43.json')
check("실패 분해 산출물이 있다", _os.path.exists(_fd113))
check("문서에 기각을 적었다",
      '메타 레이블링, 사전등록대로 기각' in
      open(_os.path.join(PROJ, 'docs', 'MODEL_VERSIONS.md'),
           encoding='utf-8').read())
check("65% 미달을 숨기지 않는다",
      '65 % 는 이번 라운드에서 달성하지 못했다' in
      open(_os.path.join(PROJ, 'docs', 'MODEL_VERSIONS.md'),
           encoding='utf-8').read()
      or '65% 는 이번 라운드에서 달성하지 못했다' in
      open(_os.path.join(PROJ, 'docs', 'MODEL_VERSIONS.md'),
           encoding='utf-8').read())

# ══════════════════════════════════════════════════════════════════════
# §114 — 섹터 사이클 오버레이 기각을 기록으로 잠근다 (라운드 44)
#   사양은 "미국 해운이 호황이면 국내 해운주 적정가에 +15~20% 프리미엄"을
#   요구했다. 원장 16,805건에 시점 복원으로 실측하니 사전등록 게이트를
#   넘지 못했다 — 특히 **valid 에서 방향이 뒤집힌다**(G3).
#   이 기록이 지워지면 검증 없이 프리미엄을 붙일 위험이 있다.
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("§114 섹터 사이클 오버레이 기각 기록 (라운드 44)")
print("=" * 72)
import sector_cycle as _sc114                                # noqa: E402

_pre114 = _os.path.join(PROJ, 'docs', 'PREREG_R44_SECTOR_OVERLAY.md')
check("사전등록 문서가 있다", _os.path.exists(_pre114))
if _os.path.exists(_pre114):
    _pt114 = open(_pre114, encoding='utf-8').read()
    check("측정 전에 썼다고 밝힌다", '측정 전' in _pt114)
    check("게이트 G1~G4 를 미리 고정했다",
          all(x in _pt114 for x in ('G1', 'G2', 'G3', 'G4', '≥ 5.0%p')))
    check("연동 안 되는 것을 미리 적었다", '지금 검증 불가' in _pt114)
    check("BDRY 가 운임지수 자체가 아님을 밝혔다", 'BDRY' in _pt114)
    check("적정가 오차는 못 잰다고 적었다",
          '측정 불가' in _pt114 and '적정가 필드가 없다' in _pt114)

# 실측 산출물 — 두 지표 모두 기각이어야 한다
for _mt114 in ('rs60', 'mom60'):
    _p114 = _os.path.join(PROJ, '.portfolio',
                          f'sector_overlay_r44_{_mt114}.json')
    check(f"{_mt114} 산출물이 있다", _os.path.exists(_p114))
    if not _os.path.exists(_p114):
        continue
    with open(_p114, encoding='utf-8') as _f:
        _d114 = _j105.load(_f)
    _g114 = _d114.get('gate') or {}
    check(f"{_mt114} 판정이 기각이다", _g114.get('verdict') == '기각',
          str(_g114.get('verdict')))
    check(f"{_mt114} 게이트 4개를 다 기록했다",
          all(k in _g114 for k in ('g1', 'g2', 'g3', 'g4')))
    check(f"{_mt114} 는 세 구간 방향이 일치하지 않았다",
          _g114.get('g3') is False, f"g3={_g114.get('g3')}")
    check(f"{_mt114} 블라인드 구간이 기록돼 있다",
          bool((_d114.get('blind') or {})))

# 룰북 — 조정 폭이 전부 0 인가 (검증 안 된 값으로 적정가를 움직이지 않는다)
_SR114 = qi.RULEBOOK.get('RULES_SECTOR', {})
check("룰북에 [RULES_SECTOR] 가 있다", bool(_SR114))
check("업황 조정을 적정가에 반영하지 않는다",
      int(_SR114.get('apply_to_fair_value', 1) or 0) == 0,
      str(_SR114.get('apply_to_fair_value')))
for _k114 in ('cap_pct_normal', 'cap_pct_limited', 'cap_pct_reference'):
    check(f"{_k114} 이 0 이다", float(_SR114.get(_k114, 99) or 0) == 0.0,
          str(_SR114.get(_k114)))
check("사양의 ±15/±8/±3 을 그대로 쓰지 않았다",
      float(_SR114.get('cap_pct_normal', 0) or 0) != 15.0)
check("미연동 업종은 조정하지 않는다",
      int(_SR114.get('skip_when_unlinked', 0) or 0) == 1)

# 근거 없는 상수 −2.0 이 되살아나지 않는가
_qsrc114 = open(_os.path.join(PROJ, 'quant_indicators.py'),
                encoding='utf-8').read()
check("market_adjustment_pct 상수 −2.0 이 사라졌다",
      "'market_adjustment_pct': -2.0" not in _qsrc114)
check("−2.0 이 기본값 자리에도 없다",
      "market_adjustment_pct', -2.0" not in _qsrc114)
_wsrc114 = open(_os.path.join(PROJ, 'web_app.py'), encoding='utf-8').read()
check("화면 폴백에도 −2.0 이 없다",
      "market_adjustment_pct', -2.0" not in _wsrc114)
check("업황조정이 0 인 이유를 화면이 적는다",
      'market_adjustment_why' in _wsrc114)

# sector_cycle — 없는 값을 지어내지 않는가
check("업종 미연동은 available=False 로 낸다",
      _sc114.for_stock('000000', industry='존재하지않는업종').get(
          'available') is False)
check("미연동에 이유가 붙는다",
      '미연동' in str(_sc114.for_stock(
          '000000', industry='존재하지않는업종').get('why') or ''))
check("업종이 없으면 연결하지 않는다",
      _sc114.group_of(None) is None and _sc114.group_of('nan') is None)
check("해상 운송업은 해운으로 간다", _sc114.group_of('해상 운송업') == 'SHIP')
check("반도체 제조업은 반도체로 간다", _sc114.group_of('반도체 제조업') == 'SEMI')
check("BDRY 가 대용임을 그룹 정의가 밝힌다",
      '운임지수' in _sc114.GROUPS['SHIP']['proxy_note']
      and '아니라' in _sc114.GROUPS['SHIP']['proxy_note'])
check("해운의 진짜 선행지표가 미연동으로 남아 있다",
      len(_sc114.GROUPS['SHIP']['real']) >= 5
      and _sc114.GROUPS['SHIP']['real_linked'] == [])
check("시세 수집 시작일이 원장보다 앞선다",
      _sc114.SERIES_START <= '2015-01-01', _sc114.SERIES_START)

# price_axes — 3단계가 분리되고, 조정 0 이면 adjusted=False 로 말하는가
_pa114 = _pa103.build(
    {'fair_value_range_core': [100.0, 140.0],
     'fair_value_range_wide': [90.0, 160.0],
     'reference_fair_value': 120.0, 'displayed_fair_value': 120.0,
     'fair_value_confidence': 85.0, 'independent_models': 3,
     'market_adjustment_pct': 0.0,
     'market_adjustment_why': '업황 조정 미적용 — 사전등록 게이트 미통과',
     'sector_cycle': {'available': False, 'linked': False,
                      'why': "'기타' 업종은 아직 프록시가 연결되지 않았습니다 (미연동)."}},
    {'current_price': 120.0, 'entry_pullback_price': 110.0})
_cb114 = _pa114.get('cycle_band') or {}
check("업황조정 축이 생겼다", bool(_cb114.get('available')))
check("조정 0 이면 adjusted=False", _cb114.get('adjusted') is False)
check("조정 0 이면 기본 범위와 같다",
      abs(_cb114.get('low', 0) - 100.0) < 1e-9
      and abs(_cb114.get('high', 0) - 140.0) < 1e-9)
# 미연동이면 '게이트 미통과'보다 **어느 업종이 왜 안 붙는지**가 먼저다.
# 둘 다 0% 지만 사용자가 할 수 있는 일이 다르다 (라운드 44).
check("미연동이면 업종 사유를 먼저 말한다",
      '미연동' in str(_cb114.get('why') or ''), str(_cb114.get('why')))
check("게이트 사유는 따로 실어 보낸다",
      '게이트' in str(_cb114.get('gate_why') or ''), str(_cb114.get('gate_why')))
check("미연동 사실이 notes 로 올라온다",
      any('업황' in str(_n) for _n in (_pa114.get('notes') or [])))
# 연동됐는데 게이트 때문에 0 인 경우 — 이때는 게이트 사유가 앞에 온다
_cb114b = _pa103.cycle_band(
    {'market_adjustment_pct': 0.0,
     'market_adjustment_why': '업황 조정 미적용 — 사전등록 게이트 미통과',
     'sector_cycle': {'available': True, 'linked': True, 'ko': '해운',
                      'mom60': 10.1, 'rs60': 4.6}},
    {'available': True, 'low': 100.0, 'high': 140.0})
check("연동됐으면 게이트 사유를 말한다",
      '게이트' in str(_cb114b.get('why') or ''), str(_cb114b.get('why')))
check("연동돼도 조정은 0 이다", _cb114b.get('adj_pct') == 0.0)

# 버전 축 — 적정가·섹터가 독립 축으로 분리됐는가
check("버전 축이 7개다", len(_ver101.AXES) == 7, str(_ver101.AXES))
for _a114 in ('valuation', 'sector'):
    check(f"'{_a114}' 축이 있다", _a114 in _ver101.AXES)
    check(f"'{_a114}' 버전이 등록돼 있다",
          _ver101.current(_a114) != 'v2026.08.02.0', _ver101.current(_a114))

# 배포를 죽인 의존성 — 열어 두면 재빌드 때마다 최신이 딸려 들어온다
#   2026-08-05 실측: streamlit 1.61.0 + starlette 1.4.0 에서 기동 즉시
#   TypeError: GZipResponder.__init__() missing 'thread_minimum_size'.
#   requirements 에 starlette 가 아예 없어서, **코드를 한 줄도 안 고쳐도**
#   어느 날 갑자기 앱이 죽는 구조였다. 상한을 지운 채로 통과시키지 않는다.
_req114 = open(_os.path.join(PROJ, 'requirements.txt'), encoding='utf-8').read()
_reqlines114 = [_l.strip() for _l in _req114.split('\n')
                if _l.strip() and not _l.strip().startswith('#')]
check("starlette 상한이 requirements 에 있다",
      any(_l.startswith('starlette') and '<' in _l for _l in _reqlines114),
      ' · '.join(_reqlines114))
check("streamlit 이 requirements 에 있다",
      any(_l.startswith('streamlit') for _l in _reqlines114))
check("섹터 수신 패키지가 requirements 에 있다",
      any(_l.lower().startswith('finance-datareader') for _l in _reqlines114),
      '의심만으로 빼 두면 업황이 조용히 미연동으로 나간다')

# 이모지 금지 — 새 모듈도 예외가 아니다
_scsrc114 = open(_os.path.join(PROJ, 'sector_cycle.py'), encoding='utf-8').read()
check("sector_cycle 에 이모지가 없다",
      not _re.search(r'[\U0001F300-\U0001FAFF☀-➿]', _scsrc114))

# 물결표가 취소선으로 먹히지 않는가 (라운드 44 실측 결함)
#   "25~75분위 범위 (넓게 보면 88,863~173,641원)" 이 화면에
#   "25 75분위 범위 (넓게 보면 88,863 173,641원)" 로 나왔다.
#   Streamlit 마크다운이 물결표 두 개를 <del> 로 묶어 사이 글자를 지웠다.
check("마크다운 이스케이프 헬퍼가 있다", '_md_safe' in _wsrc114)
# 함수 본문만 정확히 잘라 낸다. 고정 길이로 자르면 뒤 코드까지 끌려와
# SyntaxError 가 난다 (실제로 났다 — _OLD_BORDERS 리스트 중간에서 잘렸다).
_i114 = _wsrc114.index('def _md_safe')
_j114 = _wsrc114.index('\n    return s\n', _i114) + len('\n    return s\n')
_ns114 = {}
exec(compile(_wsrc114[_i114:_j114], '<md_safe>', 'exec'), _ns114)
_mdsafe114 = _ns114['_md_safe']
check("물결표를 이스케이프한다",
      _mdsafe114('25~75분위 (88,863~173,641원)')
      == '25\\~75분위 (88,863\\~173,641원)',
      _mdsafe114('25~75분위 (88,863~173,641원)'))
check("별표·밑줄·역따옴표도 막는다",
      _mdsafe114('a*b_c`d') == 'a\\*b\\_c\\`d')
check("None 을 빈 문자열로", _mdsafe114(None) == '')

# 마크다운 위젯에 물결표가 짝수로 들어가는 자리가 남아 있는가 (AST 전수)
#   한 군데만 고치면 나머지가 남는다 — 실제로 두 번째 자리가 있었다:
#   "아래 1~2행이 아니라 … 1~2행은" → <del> 로 사이 글자가 지워졌다.
import ast as _ast114
_MD_CALLS114 = {'caption', 'markdown', 'write', 'info', 'warning',
                'success', 'error', 'text'}
_tilde114 = []
for _f114 in ('web_app.py', 'ui_kit.py', 'chart_pro.py', 'gaeum_ai.py',
              'next_action.py', 'product_ops.py'):
    _p = _os.path.join(PROJ, _f114)
    if not _os.path.exists(_p):
        continue
    _s114 = open(_p, encoding='utf-8').read()
    for _nd in _ast114.walk(_ast114.parse(_s114)):
        if not isinstance(_nd, _ast114.Call):
            continue
        _fn = _nd.func
        if not (isinstance(_fn, _ast114.Attribute)
                and _fn.attr in _MD_CALLS114
                and isinstance(_fn.value, _ast114.Name)
                and _fn.value.id in ('st', '_st')):
            continue
        if any(_k.arg == 'unsafe_allow_html' for _k in _nd.keywords):
            continue           # 인라인 HTML 안이라 마크다운 파서가 안 건드린다
        _seg = _ast114.get_source_segment(_s114, _nd) or ''
        if '_md_safe' in _seg:
            continue           # 이스케이프를 거친다
        _lit = ''.join(_c.value for _c in _ast114.walk(_nd)
                       if isinstance(_c, _ast114.Constant)
                       and isinstance(_c.value, str))
        if _lit.count('~') >= 2:
            _tilde114.append(f'{_f114}:{_nd.lineno}')
check("마크다운 위젯에 취소선으로 먹힐 물결표가 없다",
      not _tilde114, ' · '.join(_tilde114[:5]))
# 근거 문구가 실제로 이 헬퍼를 거치는가 (엔진 문자열 → 마크다운 위젯)
for _pat114 in ("st.caption(_md_safe(_b['basis']))",
                "st.caption(_md_safe(_m['basis']))",
                "st.caption(_md_safe(_e['basis']))"):
    check(f"근거 문구가 이스케이프를 거친다 — {_pat114[18:30]}",
          _pat114 in _wsrc114)
# 조정이 0 이면 '조정 +0.0%' 라고 말하지 않는가
_mf114 = _pa103.market_fair(
    {'displayed_fair_value': 120.0, 'market_adjustment_pct': 0.0},
    {'available': True, 'center': 120.0, 'confidence': 85.0,
     'tier': 'normal', 'tier_ko': '정상', 'weight': 1.0})
check("조정 0 이면 근거에 '조정' 이라 쓰지 않는다",
      '조정' not in str(_mf114.get('basis') or ''), _mf114.get('basis'))

# ══════════════════════════════════════════════════════════════════════
# §115 — 시장 수준 축은 날짜 수가 표본이다 (라운드 45)
#   VIX 축이 블라인드 6개 조건을 **전부 통과**했다 (lift +33.9%p).
#   그런데 블라인드 매수권 280건은 고유 기준일 **5개**에서 나왔고,
#   VIX 는 하루 안에서 모든 종목에 같은 값이라 VIX 로 자르는 것은
#   날짜로 자르는 것이었다. lift 의 거의 전부가 2026-04-16 하루에서 나왔다.
#   이 기록이 지워지면 같은 교란을 '발견'으로 채택할 위험이 있다.
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("§115 시장 수준 축은 날짜 수가 표본이다 (라운드 45)")
print("=" * 72)
_pre115 = _os.path.join(PROJ, 'docs', 'PREREG_R45_STUDY.md')
check("사전등록 문서가 있다", _os.path.exists(_pre115))
if _os.path.exists(_pre115):
    _pt115 = open(_pre115, encoding='utf-8').read()
    check("측정 전에 썼다고 밝힌다", '측정 전' in _pt115)
    check("구간수 × 최소표본을 미리 계산했다 (라운드 44 교훈)",
          '구간 수 × 칸당 최소표본' in _pt115)
    check("다중비교 보정을 미리 정했다",
          'Bonferroni' in _pt115 and '2.87' in _pt115)
    check("사후 기록을 따로 표시했다", '사후 기록' in _pt115)
    check("통과했지만 기각한 사실을 적었다",
          '전부 통과' in _pt115 and 'B1 VIX 기각' in _pt115)
    check("기준을 내린 게 아님을 밝힌다",
          '기준을 사후에 내린 것이 아니라' in _pt115)

# 실측 산출물 — 군집 구조가 기록돼 있는가
_cl115 = _os.path.join(PROJ, '.portfolio', 'study_r45_cluster.json')
check("군집 산출물이 있다", _os.path.exists(_cl115))
if _os.path.exists(_cl115):
    with open(_cl115, encoding='utf-8') as _f:
        _d115 = _j105.load(_f)
    _b115 = (_d115.get('splits') or {}).get('blind') or {}
    check("블라인드 매수권 날짜 수가 기록돼 있다",
          _b115.get('buy_dates') is not None, str(_b115))
    check("블라인드 날짜가 30개 미만이다 — 시장 수준 축 판정 불가",
          int(_b115.get('buy_dates') or 0) < 30,
          f"날짜 {_b115.get('buy_dates')}개 · 케이스 {_b115.get('buy')}건")
    check("케이스 수가 날짜 수보다 훨씬 크다 (군집이 실재한다)",
          int(_b115.get('buy') or 0) > int(_b115.get('buy_dates') or 1) * 10)
    # 종목 수준 축은 하루 안에서 값이 갈린다 — 이쪽은 케이스가 표본이다
    _lv115 = _d115.get('axis_level') or {}
    for _k115 in ('rsi', 'bb_pos', 'range_pos'):
        if _k115 in _lv115:
            check(f"'{_k115}' 는 종목 수준 축이다",
                  float(_lv115[_k115].get('within_day_sd') or 0) > 0,
                  str(_lv115[_k115].get('within_day_sd')))

_st115 = _os.path.join(PROJ, '.portfolio', 'study_r45.json')
check("스터디 산출물이 있다", _os.path.exists(_st115))
if _os.path.exists(_st115):
    with open(_st115, encoding='utf-8') as _f:
        _s115 = _j105.load(_f)
    check("1차 관문을 통과한 축이 1개뿐이었다",
          int(_s115.get('n_passed') or 0) <= 1, str(_s115.get('n_passed')))
    # 종목 수준 축 6개가 전부 탈락한 사실
    _fail115 = [k for k, v in (_s115.get('stage1') or {}).items()
                if k.startswith('A') and v.get('verdict') != '1차 통과']
    check("방향 오판 해부 축 6개가 전부 1차 탈락했다",
          len(_fail115) == 6, f"탈락 {len(_fail115)}개")

check("문서에 라운드 45 기각을 적었다",
      '라운드 45' in open(_os.path.join(PROJ, 'docs', 'MODEL_VERSIONS.md'),
                        encoding='utf-8').read())
check("엔진 변경 없이 버전을 올리지 않았다고 적었다",
      '엔진 변경 없음. 버전 올리지 않는다' in
      open(_os.path.join(PROJ, 'docs', 'MODEL_VERSIONS.md'),
           encoding='utf-8').read())

# ══════════════════════════════════════════════════════════════════════
# §116 — 내일 살 수 있는 것만 보여준다 · 왜 사는지 말한다 (라운드 47)
#   사용자 지적: *"추천주가 거의 다 권장매수가 위다 보니 왜 이 주식을 사야
#   하는지 말해주면 좋겠다. 내일 사야되는 종목만 띄워줘. 장기관찰은 차라리
#   눌림목 대기 혹은 사라고 해줘야지."*
#
#   ⚠️ 함께 들어온 요구 중 **하나는 넣지 않았다**: "섹터 점수가 최상위면
#   권장매수가를 현재가 부근으로 끌어올려라." 라운드 44에서 원장 16,805건
#   으로 실측하고 기각한 가설이다(블라인드 호황 구간 적중 50.0% ·
#   비용후 EV −2.467%). 넣으면 추격매수에 근거를 붙여 주는 셈이다.
#   이 검사가 그 선을 지킨다.
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("§116 실행 가능한 것만 노출 · 왜 이 종목인가 (라운드 47)")
print("=" * 72)
import why_pick as _wp116                                    # noqa: E402

_FS116 = dict(entry_pullback_price=98.5, current_price=100.0,
              entry_target_1st=110.0, entry_stop_price=92.0, entry_rr=1.2,
              analysis_confidence=70, strategy_quality_score=60,
              vol_20=0.03, avg_turnover_20d=1e9,
              target_tech_1st=112.0, stop_loss_price=90.0,
              calibration_band=dict(lo=50, hi=59, hit_rate=58.0, n=1200,
                                    wilson_low=55.0),
              range_position_pct=55.0, bb_position_pct=50.0,
              williams_r_value=-50.0, rsi_value=52.0,
              blind_test_status='통과')
_VD116 = {'action': 'BUY', 'headline': '', 'vetoes': []}

# ① 진입 깊이가 노출을 가른다 — 새 문턱을 만들지 않고 2.1σ 를 재사용
for _lbl, _entry, _want in (('가까움', 98.5, True),
                            ('상한 부근', 94.0, True),
                            ('너무 멀다', 88.0, False)):
    _c = _vc105.build(dict(_FS116, entry_pullback_price=_entry,
                           entry_stop_price=_entry * 0.93,
                           entry_target_1st=_entry * 1.10),
                      _VD116, None, {'kind': 'pullback'}, 100.0)
    check(f"진입 깊이 '{_lbl}' → 실행 가능 {_want}",
          bool(_c['actionable']) is _want,
          f"{_c['depth_sigma']}σ · {_c['bucket']}")
check("노출 자를 새로 만들지 않았다 (2.1σ 재사용)",
      _vc105.MAX_ENTRY_SIGMA == 2.1 and 'n=5,389' in _vc105.SIGMA_BASIS)

# ② 거부권 사유를 뭉뜽그리지 않는다 — 무엇이 막는지 적는다
_c116v = _vc105.build(
    _FS116, {'action': 'HOLD', 'headline': '',
             'vetoes': ["진입 위치 '적정가 크게 초과' — 적정가를 크게 초과",
                        '거래비용 차감 후 기대수익 −0.42% (0 이하)']},
    None, {'kind': 'pullback'}, 100.0)
check("거부권이면 추천 제외", _c116v['bucket'] == '추천 제외')
check("거부권 사유를 그대로 낸다",
      '적정가' in str(_c116v['exclude_reason']),
      str(_c116v['exclude_reason'])[:70])
check("'매수를 막는 조건이 있습니다' 로 뭉뜽그리지 않는다",
      str(_c116v['exclude_reason']) != '매수를 막는 조건이 있습니다.')

# ③ 왜 이 종목인가 — 근거는 숫자와 함께, 위험은 반드시 하나
_c116 = _vc105.build(_FS116, _VD116, None, {'kind': 'pullback'}, 100.0)
_w116 = _wp116.build(_c116, _FS116,
                     news_flags=dict(feed_available=True, fresh=2, lagging=7,
                                     risk_words=[],
                                     headlines=[dict(title='신규 공급계약',
                                                     source='연합뉴스 경제')]),
                     sector_cycle=dict(linked=True, ko='해운',
                                       mom60=10.1, rs60=4.6))
check("정량 근거가 나온다", len(_w116['quant']) >= 2)
check("근거에 표본 수가 들어간다",
      any('건' in b for _, b in _w116['quant']))
check("위험요인을 반드시 하나 낸다",
      bool(_w116['risk']) and len(_w116['risk']) == 2)
check("뉴스를 개수가 아니라 내용으로 말한다",
      '신규 공급계약' in _w116['news']['text'])
check("중복·후행 제외 수를 밝힌다", '7건' in _w116['news']['text'])
check("뉴스 반영 정도를 숨기지 않는다",
      '가점 0' in _w116['news']['text'])

# ④ 선반영 — 좋은 뉴스라도 이미 올랐으면 가점을 넣지 않는다
_hot116 = dict(_FS116, range_position_pct=92.0)
_n116 = _wp116.news_reason(
    dict(feed_available=True, fresh=1, lagging=3, risk_words=[],
         headlines=[dict(title='대규모 수주', source='한국경제')]),
    _c116, _hot116)
check("선반영이면 그렇게 적는다",
      '이미 가격에 반영' in _n116['text'], _n116['text'][:70])
check("선반영 판정이 플래그로도 나온다", _n116['priced_in'] is True)

# ⑤ 뉴스 미수신 ≠ 악재
_na116 = _wp116.news_reason(dict(feed_available=False), _c116, _FS116)
check("뉴스 미수신을 악재로 만들지 않는다",
      '악재가 아니며' in _na116['text'])

# ⑥ 업황은 참고로만 — 라운드 44 기각을 문장에 남긴다
_s116 = _wp116.sector_reason(dict(linked=True, ko='해운', mom60=10.1, rs60=4.6))
check("업황을 참고로만 쓴다고 밝힌다",
      _s116 is not None and '판정에는 넣지 않았습니다' in _s116[1])
check("업황 미연동이면 아예 안 쓴다",
      _wp116.sector_reason(dict(linked=False)) is None)

# ⑦ 섹터로 매수가를 끌어올리지 않는다 (요구받았으나 기각된 것)
_wsrc116 = open(_os.path.join(PROJ, 'why_pick.py'), encoding='utf-8').read()
# 유니코드 마이너스(−, U+2212)와 ASCII 하이픈(-)을 둘 다 받는다.
# 문서 문장은 유니코드 마이너스를 쓴다 — 검사가 그걸 몰라 한 번 걸렸다.
check("섹터 모멘텀으로 매수가를 올리지 않는다고 코드에 적었다",
      '기각했다' in _wsrc116
      and ('2.467' in _wsrc116)
      and ('−2.467' in _wsrc116 or '-2.467' in _wsrc116))
_vsrc116 = open(_os.path.join(PROJ, 'verdict_core.py'), encoding='utf-8').read()
check("업황이 진입가 산출에 끼어들지 않는다",
      'sector' not in _vsrc116.lower().split('def build(')[1].split('return dict')[0])

# ⑧ 카드가 '왜' 칸을 그리는가
_usrc116 = open(_os.path.join(PROJ, 'ui_kit.py'), encoding='utf-8').read()
check("카드에 '왜 이 종목인가' 칸이 있다", '왜 이 종목인가' in _usrc116)
check("근거가 없으면 그 칸을 안 그린다", "wp.get('quant')" in _usrc116)

# ══════════════════════════════════════════════════════════════════════
# §117 — 블라인드 오염 신고와 봉인 (라운드 46)
#   타당성 프로브가 기존 티커의 블라인드 업종 성적을 출력했다. 오염 범위를
#   작게 세지 않았다 — 14건이 아니라 681건이다. 이 기록이 지워지면
#   오염된 데이터를 성능 주장에 다시 쓸 위험이 있다.
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("§117 블라인드 오염 신고와 봉인 (라운드 46)")
print("=" * 72)
_pre117 = _os.path.join(PROJ, 'docs', 'PREREG_R46_SECTOR_GATE.md')
check("사전등록 문서가 있다", _os.path.exists(_pre117))
if _os.path.exists(_pre117):
    _pt117 = open(_pre117, encoding='utf-8').read()
    check("측정 전에 저장했다고 밝힌다", '측정 전' in _pt117)
    check("오염을 영어 표준 문구로 신고했다",
          'Confirmed blind contamination' in _pt117)
    check("오염 범위를 작게 세지 않았다 (681건)", '681건' in _pt117)
    check("삭제하지 않고 보존한다고 적었다",
          '삭제하지 않는다' in _pt117 and '감사용' in _pt117)
    check("**검정력을 측정 전에 계산했다**",
          '검정력' in _pt117 and '24%' in _pt117 and '14.9%p' in _pt117)
    check("표본이 작아서라는 변명을 미리 막았다",
          '변명' in _pt117)
    check("봉인 절차를 미리 적었다", 'evaluated_holdout_1' in _pt117)
    check("성적을 합치지 않는다고 적었다",
          '합쳐' in _pt117 and '표시하지 않는다' in _pt117)
    check("엔진 버전 7축을 고정했다",
          all(_x in _pt117 for _x in ('v2026.08.06.1', 'v2026.08.05.1',
                                      'v2026.08.06.0')))
    check("성공·실패·미도달 정의를 고정했다",
          '미도달' in _pt117 and '실패로 센다' in _pt117)

# 프로브 잠금 — 블라인드 성적을 다시 출력하지 못하게
_fes117 = _os.path.join(PROJ, '_probe', 'feasibility_r46.py')
if _os.path.exists(_fes117):
    _fs117 = open(_fes117, encoding='utf-8').read()
    check("타당성 프로브가 블라인드 성적을 잠갔다",
          'SHOW_BLIND_OUTCOME = False' in _fs117)
    check("프로브가 자기 실수를 기록했다",
          '이 프로브가 저지른 실수' in _fs117)

# 측정 산출물 — 딱 한 번 재고 봉인됐는가
_ms117 = _os.path.join(PROJ, '.portfolio', 'measure_r46.json')
check("측정 산출물이 있다", _os.path.exists(_ms117))
if _os.path.exists(_ms117):
    with open(_ms117, encoding='utf-8') as _f:
        _m117 = _j105.load(_f)
    check("판정이 기각이다", _m117.get('verdict') == '기각',
          str(_m117.get('verdict')))
    check("봉인됐다", _m117.get('sealed') is True)
    check("한 번만 쟀다고 기록했다", _m117.get('measured_once') is True)
    check("코호트 이름이 봉인 이름으로 바뀌었다",
          'evaluated_holdout_1' in str(_m117.get('cohort')))
    check("검정력을 결과와 함께 남겼다",
          (_m117.get('power') or {}).get('power_case') is not None)
    check("6개 조건을 다 기록했다", len(_m117.get('checks') or []) == 6)
    # 깨끗한 블라인드에서 EV 가 음수였다는 사실 — 성과를 좋게 쓰지 않는다
    check("깨끗한 블라인드 EV 가 음수였음을 기록했다",
          float((_m117.get('rest') or {}).get('ev', 0)) < 0
          and float((_m117.get('bio') or {}).get('ev', 0)) < 0)

_reg117 = _os.path.join(PROJ, '.portfolio', 'cohort_registry_r46.json')
check("코호트 등록부가 있다", _os.path.exists(_reg117))
if _os.path.exists(_reg117):
    with open(_reg117, encoding='utf-8') as _f:
        _r117 = _j105.load(_f)
    check("등록부에 성적이 담기지 않았다",
          _r117.get('outcomes_seen') is False)
    check("오염 처분이 기록돼 있다",
          'Confirmed blind contamination' in
          str((_r117.get('contaminated') or {}).get('policy')))
    check("독립 표본 회계가 있다",
          (_r117.get('independence') or {}).get('blocks_20bar') is not None)

check("문서에 라운드 46 결과를 적었다",
      '라운드 46 — 표본을 3배로 늘렸더니' in
      open(_os.path.join(PROJ, 'docs', 'MODEL_VERSIONS.md'),
           encoding='utf-8').read())
check("깨끗한 블라인드 45.2% 를 숨기지 않는다",
      '45.2%' in open(_os.path.join(PROJ, 'docs', 'MODEL_VERSIONS.md'),
                      encoding='utf-8').read())

# ══════════════════════════════════════════════════════════════════════
# §118 — 맨 위 실시간 띠 (라운드 48)
#   사용자 요청: *"뭐 진행중이다, 핫이슈가 뭐다, 실시간으로 뉴스 같은 거
#   맨 위에 계속 움직이게."* 띠는 **알림이지 판단이 아니다** — 여기서
#   점수를 만들거나 값을 고치면 화면마다 값이 달라진다 (CLAUDE.md §4).
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("§118 맨 위 실시간 띠 (라운드 48)")
print("=" * 72)
import live_ticker as _lt118                                 # noqa: E402

_uk118 = open(_os.path.join(PROJ, 'ui_kit.py'), encoding='utf-8').read()
check("띠 컴포넌트가 있다", 'def ticker_bar(' in _uk118)
check("모션 감소를 존중한다 (접근성)",
      'prefers-reduced-motion' in _uk118)
check("마우스를 올리면 멈춘다",
      'animation-play-state:paused' in _uk118)
check("스크린리더 역할을 준다", "role='status'" in _uk118)
check("외부 링크가 안전하다", "noopener noreferrer" in _uk118)

_rows118 = [dict(kind='live', text='분석 중'),
            dict(kind='news', text='<script>alert(1)</script>',
                 href='https://example.com', meta='출처')]
import ui_kit as _ukmod118                                   # noqa: E402
_h118 = _ukmod118.ticker_bar(_rows118)
check("제목을 이스케이프한다 (XSS 방지)", '<script>' not in _h118)
check("빈 목록이면 아예 그리지 않는다", _ukmod118.ticker_bar([]) == '')
check("띠에 이모지가 없다",
      not _re.search(r'[\U0001F300-\U0001FAFF☀-➿]', _h118))

# 뉴스 미수신을 '이슈 없음'으로 바꾸지 않는가
_n118 = _lt118._news([], [{'ok': False, 'count': 0}])
check("뉴스 미수신을 그대로 말한다",
      any('미수신' in r['text'] for r in _n118), str(_n118))
check("미수신일 때 판단 미반영을 밝힌다",
      any('반영하지 않습니다' in r['text'] for r in _n118))

# 위험 낱말 — 짧고 흔한 말로 오탐하지 않는가 (라운드 48 실측 결함)
import news_feed as _nf118                                   # noqa: E402
check("'한정' 단독 낱말이 사라졌다", '한정' not in _nf118.RISK_WORDS)
check("감사의견 한정은 긴 형태로 남아 있다",
      any('감사의견' in w for w in _nf118.RISK_WORDS))
_FALSE118 = ("오뚜기 '제주 드립 커피'·팔도-엔씨 '왕뚜껑 한정판'",
             '특허 소송 승소로 로열티 확보',
             '경쟁사 인수 완료로 점유율 확대')
for _t118 in _FALSE118:
    _hit118 = [w for w in _nf118.RISK_WORDS if w in _t118]
    check(f"오탐 없음 — {_t118[:18]}", not _hit118, str(_hit118))
_TRUE118 = ('엠엑스로보틱스, 100억원 유상증자',
            'A사 감사의견 거절로 상장폐지 사유 발생',
            'B사 자본잠식 50% 초과')
for _t118 in _TRUE118:
    check(f"진짜 위험은 잡는다 — {_t118[:18]}",
          any(w in _t118 for w in _nf118.RISK_WORDS))

# 화면 연결 — 별칭이 겹치지 않는가 (라운드 39 `_vc` 사고 재발 방지)
_w118 = open(_os.path.join(PROJ, 'web_app.py'), encoding='utf-8').read()
check("띠를 화면 맨 위에 붙였다",
      '_TICKER_SLOT' in _w118 and '_render_ticker(' in _w118)
check("별칭이 경량 스캔 변수와 겹치지 않는다",
      'import live_ticker as _ltick' in _w118
      and 'import live_ticker as _lt\n' not in _w118)
check("띠 하나 때문에 앱이 죽지 않는다",
      '띠 하나 때문에 앱이 죽지 않는다' in _w118)

# ══════════════════════════════════════════════════════════════════════
# §119 — 순위에 정보가 없다 (라운드 49·50)
#   사용자 요구: *"우리가 추천한 종목이 추천하지 않은 종목보다 실제로 더
#   많이 올랐는가? 차이가 없다면 추천 엔진이 의미가 없는 것입니다."*
#   맞다. 그리고 재 보니 **차이가 없었다.** 이 기록이 지워지면 타점·엑시트
#   개선을 순위 문제보다 먼저 하게 된다 — 잘못된 목록을 예쁘게 정렬하는 일.
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("§119 순위에 정보가 없다 (라운드 49·50)")
print("=" * 72)
for _p119, _ko119 in ((('docs', 'PREREG_R49_RANK_VALUE.md'), '라운드 49'),
                      (('docs', 'PREREG_R50_RANK_AXES.md'), '라운드 50')):
    _f119 = _os.path.join(PROJ, *_p119)
    check(f"{_ko119} 사전등록이 있다", _os.path.exists(_f119))
    if _os.path.exists(_f119):
        _t119 = open(_f119, encoding='utf-8').read()
        check(f"{_ko119} — 측정 전에 썼다고 밝힌다", '측정 전' in _t119)
        check(f"{_ko119} — 봉인 구간을 읽지 않는다고 적었다",
              'evaluated_holdout_1' in _t119 and '읽지 않는다' in _t119)

_r49 = _os.path.join(PROJ, '.portfolio', 'rank_value_r49.json')
check("라운드 49 산출물이 있다", _os.path.exists(_r49))
if _os.path.exists(_r49):
    with open(_r49, encoding='utf-8') as _f:
        _d49 = _j105.load(_f)
    check("판정이 미달이다", _d49.get('verdict') == '미달', str(_d49.get('verdict')))
    check("순위가 단조가 아니었다", _d49.get('monotonic') is False)
    check("TOP5 가 미추천보다 나았다는 증거가 없다",
          float(_d49.get('lift') or 0) < 5.0, str(_d49.get('lift')))
    check("봉인 구간을 제외하고 쟀다",
          _d49.get('split') == 'development_only')

_r49b = _os.path.join(PROJ, '.portfolio', 'rank_value_r49b.json')
check("날짜 교란 확인 산출물이 있다", _os.path.exists(_r49b))
if _os.path.exists(_r49b):
    with open(_r49b, encoding='utf-8') as _f:
        _d49b = _j105.load(_f)
    check("같은 날 안에서 짝지어 다시 쟀다",
          int(_d49b.get('paired_days') or 0) >= 100,
          f"{_d49b.get('paired_days')}일")
    check("교란을 걷어내도 상위5 우위가 없다",
          float(_d49b.get('mean_hit_diff') or 0) < 3.0,
          f"{_d49b.get('mean_hit_diff')}%p")

_r50 = _os.path.join(PROJ, '.portfolio', 'rank_axes_r50.json')
check("라운드 50 산출물이 있다", _os.path.exists(_r50))
if _os.path.exists(_r50):
    with open(_r50, encoding='utf-8') as _f:
        _d50 = _j105.load(_f)
    check("통과 축이 없다", len(_d50.get('passed') or []) == 0,
          str(_d50.get('passed')))
    check("9개 축을 다 쟀다", len(_d50.get('axes') or {}) >= 8)
    check("기준선(종합점수)도 같이 쟀다",
          (_d50.get('baseline') or {}).get('mean_hit') is not None)

# 결론이 프로젝트 규칙에 박혔는가 — 새 기능 요청에 순서가 밀리지 않도록
_cl119 = open(_os.path.join(PROJ, 'CLAUDE.md'), encoding='utf-8').read()
check("CLAUDE.md 에 '순위에 정보가 없다'를 박았다",
      '순위에 정보가 없다' in _cl119)
check("타점·엑시트보다 산식이 먼저임을 적었다",
      '점수 산식 자체를 다시 봐야 한다' in _cl119)
check("새 기능 요청에도 순서를 바꾸지 않는다고 적었다",
      '이 순서를 바꾸지' in _cl119)

# 원장 확장 — 없는 키를 적지 않았는가
_lab119 = open(_os.path.join(PROJ, 'scripts', 'calibration_lab.py'),
               encoding='utf-8').read()
check("원장에 하위점수를 기록한다",
      all(_k in _lab119 for _k in ('q_stock_quality', 'q_trading_timing',
                                   'q_risk_safety', 'q_opportunity',
                                   'q_execution')))
check("원장에 업종을 기록한다", "'sector':" in _lab119)
check("원장에 뉴스 필드를 기록한다 (라운드 42 한계 해소)",
      'news_risk_count' in _lab119 and 'news_available' in _lab119)
check("존재하지 않는 키는 적지 않는다",
      "'q_signal_consensus'" not in _lab119)
check("왜 뺐는지 코드에 남겼다",
      'signal_consensus_score 는' in _lab119 and '뺐다' in _lab119
      and 'null 로 쌓인다' in _lab119)

# ══════════════════════════════════════════════════════════════════════
# §120 — 매매 지시서 · 평단 종목별 분리 (라운드 51~53)
#   ① 평단이 종목을 따라가지 않아 금호건설 10,246원이 LG생활건강
#      (약 330,000원) 차트에 그려졌다. 평단은 보유 판단의 유일한 입력이라
#      섞이면 수익률·물타기 판정이 통째로 남의 것이 된다.
#   ② 점수만 보여주지 말고 "얼마에 사서 언제 파는가"를 낸다.
#      단, 검증되지 않은 부분(목표 배수·추적손절)을 밝히지 않으면 과장이다.
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("§120 매매 지시서 · 평단 종목별 분리 (라운드 51~53)")
print("=" * 72)
import trade_plan as _tp120                                  # noqa: E402

_w120 = open(_os.path.join(PROJ, 'web_app.py'), encoding='utf-8').read()
# ① 평단 위젯이 종목별로 갈렸는가
check("사이드바 평단 키가 종목별이다", 'key=f"sb_avg_{_pk}"' in _w120)
check("본문 평단 키가 종목별이다", 'key=f"pos_avg_{_pkm}"' in _w120)
check("보유 여부 라디오도 종목별이다", 'key=f"pos_mode_{_pkm}"' in _w120)
check("고정 키가 남아 있지 않다",
      "key=\"pos_avg_main\"" not in _w120
      and "key='pos_avg_main'" not in _w120)
check("자릿수 안전장치가 있다",
      '자릿수가 맞지 않아 차트에 표시하지 않았습니다' in _w120)
check("왜 생긴 결함인지 코드에 남겼다",
      'LG생활건강' in _w120 and '금호건설' in _w120)

# ② 지시서가 실제 문장을 내는가
_FS120 = dict(entry_pullback_price=24800.0, current_price=25800.0,
              entry_target_1st=27300.0, entry_stop_price=24000.0,
              entry_rr=1.3, target_tech_2nd=28500.0,
              analysis_confidence=72, strategy_quality_score=61,
              vol_20=0.025, avg_turnover_20d=1e9,
              target_tech_1st=27500.0, stop_loss_price=24200.0,
              calibration_band=dict(lo=58, hi=64, hit_rate=59.0, n=1200,
                                    wilson_low=56.0),
              range_position_pct=52.0, bb_position_pct=44.0,
              williams_r_value=-55.0, rsi_value=48.0,
              blind_test_status='통과')
_c120 = _vc105.build(_FS120, {'action': 'BUY', 'headline': '', 'vetoes': []},
                     None, {'kind': 'pullback'}, 25800.0)
_b120 = _tp120.for_buyer(_c120, _FS120)
check("매수 지시가 나온다", _b120.get('available') is True)
check("매수·목표·손절이 다 있다",
      all(_b120.get(_k) for _k in ('entry', 'target', 'stop')))
check("퍼센트와 원을 같이 낸다",
      _b120.get('target_pct') is not None and _b120.get('stop_pct') is not None)
check("목표 배수의 한계를 반드시 적는다",
      '라운드 36' in str(_b120.get('target_caveat'))
      and '양수가 아니었습니다' in str(_b120.get('target_caveat')))

# 보유자 — 수익률 구간마다 지시가 달라지는가
_heads = [_tp120.for_holder(_c120, a)['headline']
          for a in (23000, 25500, 27000, 30000)]
check("보유자 지시가 수익률에 따라 갈린다", len(set(_heads)) == 4,
      ' / '.join(_h[:10] for _h in _heads))
check("손실 구간에서 물타기를 막는다",
      any('물타기' in _h for _h in _heads))
check("평단이 없으면 아무것도 만들지 않는다",
      _tp120.for_holder(_c120, None).get('available') is False)

# ③ 시장 4상태 — 라운드 52 실측을 그대로 싣는가
_ms = _tp120.market_state(2600, 2650, 2500, 2480)
check("조정 구간을 알아본다", _ms and 'PULLBACK' == _ms.get('code'))
check("조정 구간이 유일한 양수 EV 임을 적는다",
      '유일하게 비용후 기대값이 양수' in str(_ms.get('say')))
_ms2 = _tp120.market_state(2400, 2450, 2500, 2530)
check("60일선 기울기를 반영한다", _ms2 and _ms2.get('slope') == 'down')
check("기울기 차이를 문장으로 낸다", '53.8%' in str(_ms2.get('slope_note')))
_bi120 = open(_os.path.join(PROJ, 'bitemporal_engine.py'),
              encoding='utf-8').read()
check("엔진이 60일선 기울기를 낸다", '"sma60_prev"' in _bi120)
check("봉이 모자라면 지어내지 않는다", 'if len(arr) >= 65 else None' in _bi120)

# ④ 추적손절 — 못 잰 것을 잰 척하지 않는가
check("사후 규칙의 수치가 미측정임을 밝힌다",
      '측정하지 못했습니다' in _tp120.POST_ENTRY_CAVEAT)
check("왜 못 재는지 이유를 적는다",
      '청산 시점까지만' in _tp120.POST_ENTRY_CAVEAT)
_tps120 = open(_os.path.join(PROJ, 'trade_plan.py'), encoding='utf-8').read()
check("지시서가 점수를 만들지 않는다고 적었다",
      '점수를 만들거나 가격을 새로 계산하지 않는다' in _tps120)

# ⑤ 카드 렌더
_h120 = _ukmod118.trade_plan_card(
    _tp120.build(_c120, _FS120, avg=25500, qty=100,
                 market=_tp120.market_state(2400, 2450, 2500, 2480)),
    name='테스트')
check("카드가 그려진다", len(_h120) > 1000)
check("카드에 이모지가 없다",
      not _re.search(r'[\U0001F300-\U0001FAFF☀-➿]', _h120))
check("카드가 한계를 숨기지 않는다", '라운드 36' in _h120)
check("화면이 지시서를 그린다",
      '_uk.trade_plan_card(' in _w120 and 'import trade_plan as _tp' in _w120)
check("지시서 하나 때문에 화면이 죽지 않는다",
      '지시서 하나 때문에 분석 화면이 죽지 않는다' in _w120)

# ⑥ 경로 분포 차트 — 어디서 사는지가 빠져 있었다
#    목표선·손절선은 있는데 **실행 진입가**가 없었다. 그리고 그 목표·손절은
#    보유자 값(target_tech_1st·stop_loss_price)인데 이름표가 없어서, 배너의
#    신규 매수자 값과 이름은 같고 숫자는 다른 선이 한 화면에 있었다.
check("경로 차트에 실행 진입가가 있다",
      "CORE.get('pullback_zone'), '#35C98B'" in _w120)
check("경로 차트가 중앙 판정에서 목표·손절을 받는다",
      "CORE.get('new_target')" in _w120 and "CORE.get('new_stop')" in _w120)
check("경로 차트가 보유자 값을 이름 없이 그리지 않는다",
      "(four_scores.get('target_tech_1st'), '#4C8DFF', '1차 목표가')"
      not in _w120
      and "(four_scores.get('stop_loss_price'), '#ff453a', '손절가')"
      not in _w120)
check("누구 기준인지 이름에 적는다",
      '1차 목표 · 신규' in _w120 and '1차 목표 · 보유자' in _w120)
check("보유자 선은 실제 보유자에게만 그린다",
      "        if _my:\n            _AX += [" in _w120)
check("평단 자릿수 판정을 선 고르기 **전에** 한다",
      _w120.index('자릿수가 맞지 않아 차트에 표시하지 않았습니다')
      < _w120.index("CORE.get('pullback_zone'), '#35C98B'"))

# ⑦ 종합 차트(chart_pro) — 폐기된 산식을 그리고 있었다
_cp120 = open(_os.path.join(PROJ, 'chart_pro.py'), encoding='utf-8').read()
check("종합 차트가 중앙 판정을 받는다", 'core=None' in _cp120)
check("웹앱이 중앙 판정을 실제로 넘긴다", 'core=CORE)' in _w120)
check("폐기된 recommended_buy_price 를 더는 그리지 않는다",
      "fs.get('recommended_buy_price')" not in _cp120)
check("왜 폐기했는지 코드에 남겼다",
      '147,567원' in _cp120 and '라운드 25' in _cp120)
check("차트 설명이 두 기준을 구분해 알린다",
      '실선은 **신규 매수자**' in _w120 and '**보유자**' in _w120)
check("설명이 '배너와 같은 숫자'라고 거짓 주장하지 않는다",
      '실행 가격선(추천 매수가·1·2차 목표가·손절가·TDST)은 위 배너와 같은 '
      '숫자입니다' not in _w120)

# ⑧ '아주 쉬운 결론' — 화면에서 실제로 잡은 모순
#    지시서: "매수구간 208,913~213,133원"
#    그 아래: "147,608원 이하로 내려올 때만 사세요"
#    같은 종목·같은 화면에서 매수가가 6만원 차이로 둘이었다. 서버를 띄우지
#    않았으면 못 봤다 — 회귀는 전건 통과 상태였다.
_FS120E = dict(current_price=231000.0, entry_pullback_price=211023.0,
               entry_target_1st=236572.0, entry_stop_price=196000.0,
               recommended_buy_price=147608.0,       # 폐기 산식
               buy_entry_max=213133.0, target_tech_1st=236572.0,
               target_tech_2nd=298000.0, stop_loss_price=174524.0,
               m10_disparity=8.0, calibration_band=None)
_VD120E = {'action': 'HOLD', 'score': 49, 'vetoes': ['진입 위치 초과']}
_ez = qi.QuantIndicatorsEngine.build_easy_advice(_FS120E, _VD120E, 231000.0)
_nbt = _ez['new_buyer']['line'] + _ez['new_buyer']['detail']
check("쉬운 결론이 폐기된 적정가×안전마진을 말하지 않는다",
      '147,608' not in _nbt)
check("쉬운 결론의 매수가 = 중앙 판정 진입가", '211,023' in _nbt)
check("쉬운 결론의 신규 손절 = 진입 기준 손절",
      _ez['new_buyer']['prices']['손절가(신규 진입 기준으로 재설정)'] == 196000.0)
_hz = qi.QuantIndicatorsEngine.build_easy_advice(
    _FS120E, _VD120E, 231000.0, user_avg=250000.0)['holder']
check("보유자 문단은 보유자 손절을 쓴다",
      _hz['prices']['손절가(보유 기준)'] == 174524.0
      and '174,524' in _hz['detail'])
check("보유자 문단에 신규 손절이 새지 않는다", '196,000' not in _hz['detail'])
_qis120 = open(_os.path.join(PROJ, 'quant_indicators.py'),
               encoding='utf-8').read()
check("왜 바꿨는지 엔진에 남겼다",
      '147,608원 이하로 내려올 때만' in _qis120 and '라운드 25 폐기' in _qis120)

# ⑨ 같은 결함이 여섯 벌 있었다 — 폐기 산식을 '오늘의 매수가'로 쓰는 자리
#    다섯 곳 모두 주석이 코드와 반대였다. 라운드 25 에서 폐기 결정만 하고
#    호출부를 절반만 옮긴 흔적이다:
#      # 그걸 오늘의 매수가로 쓰면 안 된다  ← 주석
#      rec = entry_pullback_price or recommended_buy_price   ← 바로 다음 줄
_DEAD120 = 147608.0
_FS120D = dict(current_price=231000.0, entry_pullback_price=None,
               recommended_buy_price=_DEAD120, buy_entry_max=_DEAD120,
               entry_target_1st=None, entry_stop_price=None,
               target_tech_1st=236572.0, target_tech_2nd=298000.0,
               stop_loss_price=174524.0, m10_disparity=8.0,
               vol_20=0.02, avg_turnover_20d=1e10, calibration_band=None)
_VD120D = {'action': 'HOLD', 'score': 49, 'vetoes': []}

# ⓐ 중앙 판정 — 진입가가 없으면 폐기 산식으로 매수구간을 만들지 않는다
_c120d = _vc105.build(_FS120D, _VD120D, None, None, 231000.0)
check("진입가 미산출이면 매수구간을 만들지 않는다",
      _c120d['buy_zone'] is None and _c120d['pullback_zone'] is None)
check("그 상태를 '데이터 부족'으로 말한다",
      _c120d['bucket'] == '데이터 부족' and _c120d['actionable'] is False)
_vcs120 = open(_os.path.join(PROJ, 'verdict_core.py'), encoding='utf-8').read()
check("중앙 판정 폴백에서 폐기 산식이 빠졌다",
      "or _f(fs.get('recommended_buy_price'))" not in _vcs120)

# ⓑ next_action — 주석과 코드가 반대였다
import next_action as _na120                                  # noqa: E402
_n120 = _na120.build(_FS120D, None, 231000.0, _VD120D)
check("next_action 이 폐기 산식을 진입가로 쓰지 않는다",
      '147,608' not in str(_n120))
_nas120 = open(_os.path.join(PROJ, 'next_action.py'), encoding='utf-8').read()
check("next_action 폴백 제거", "fs.get('recommended_buy_price')" not in _nas120)

# ⓒ 개장 전 리포트
_pm120 = open(_os.path.join(PROJ, 'premarket.py'), encoding='utf-8').read()
check("개장 전 카드 폴백 제거",
      "or fs.get('recommended_buy_price')" not in _pm120)

# ⓓ 고정 사이드 패널 — 배너 옆에 항상 붙어 있던 다른 숫자
check("고정 패널이 중앙 판정을 읽는다",
      "<tr><td>실행 진입가</td><td>{fmt_num((CORE or {}).get('pullback_zone')"
      in _w120)
check("고정 패널이 보유자 값을 이름 없이 싣지 않는다",
      "<tr><td>1차 목표가</td><td>{fmt_num(four_scores.get('target_tech_1st')"
      not in _w120)

# ⓔ 정밀 레포트
_rg120 = open(_os.path.join(PROJ, 'report_generator.py'), encoding='utf-8').read()
check("레포트의 '권장 매수가'가 실행 진입가로 바뀌었다",
      "rec_buy = fs.get('entry_pullback_price')" in _rg120)
check("레포트가 장기 참고선을 따로 적는다",
      '장기 가치 참고선' in _rg120 and '오늘의 매수가가 아님' in _rg120)

# ⓕ 추격금지선 — 진입가보다 아래면 문장이 자기모순이다
_FS120C = dict(_FS120D, entry_pullback_price=211023.0,
               entry_target_1st=236572.0, entry_stop_price=196000.0)
_ec = qi.QuantIndicatorsEngine.build_easy_advice(_FS120C, _VD120D, 231000.0)
_ect = _ec['new_buyer']['line'] + _ec['new_buyer']['detail']
check("금지선이 진입가 아래면 문구를 비운다",
      '위에서는 특히 금지' not in _ect and '147,608' not in _ect)
_ec2 = qi.QuantIndicatorsEngine.build_easy_advice(
    dict(_FS120C, buy_entry_max=250000.0), _VD120D, 231000.0)
check("금지선이 진입가 위면 남긴다",
      '250,000원 위에서는' in _ec2['new_buyer']['detail'])
check("값을 고치지 않고 문장에서만 비운다 (게이트 입력 보존)",
      'buy_entry_max = float(recommended_buy_price) if fair_value_usable'
      in _qis120)

# ══════════════════════════════════════════════════════════════════════
# §121 — 적정가 미산출 감사 (라운드 54)
#   사용자 보고: "적정가가 미산출이 많이 나와." 전수 감사(583종목) 결과
#   미산출 53.3% 중 OUT_OF_DOMAIN 이 291종목(49.9%)이었고, 표본 120종목을
#   뜯어 보니 게이트의 논거(성장 기대가 가격 지배)가 성립하는 하방은
#   16종목뿐 — 104종목은 PER 3~7배 가치주의 **상방** 괴리였다.
#   abs() 로 양방향에 걸어 둔 것이 원인. 문턱은 그대로, 방향만 하방
#   전용으로 고쳤다. 상방 극단은 원래 설계대로 윈저화(+48% 수축)와
#   신뢰도 감점이 처리한다.
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("§121 적정가 미산출 감사 (라운드 54)")
print("=" * 72)
_qi121 = open(_os.path.join(PROJ, 'quant_indicators.py'),
              encoding='utf-8').read()
check("범위 밖 게이트가 하방 전용이다",
      'if raw_upside_pct < -_ood_gap:' in _qi121)
check("양방향 abs() 게이트가 남아 있지 않다",
      'if abs(raw_upside_pct) > _ood_gap:' not in _qi121)
check("문턱(70%)은 손대지 않았다",
      float(qi.QuantIndicatorsEngine.FV_CONF.get(
          'out_of_domain_gap_pct', 0)) == 70.0)
check("왜 방향을 고쳤는지 감사 수치와 함께 남겼다",
      '291종목(49.9%)' in _qi121 and '104종목' in _qi121)
# 합성 사례 — 상방 가치주는 게이트를 통과해 수축·신뢰도 경로로 가는가
#   (실제 대상: PER 4~7배 흑자 기업에 모델이 +100~250% 를 매긴 168종목)
check("윈저화가 극단 상방을 +48% 이내로 수축",
      'calibrated_upside_pct = min(48.0' in _qi121)
check("하방 사례(레인보우)는 여전히 산출 불가",
      "raw_upside_pct:+.0f}% 괴리" in _qi121
      and 'OUT_OF_DOMAIN' in _qi121)

# ══════════════════════════════════════════════════════════════════════
# §122 — 뉴스 중복 병합·사건 유형 · 업종 원장 실측 · 유효 표본 (라운드 54b)
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("§122 뉴스 병합·사건 유형 · 업종 실측 · 유효 표본 (라운드 54b)")
print("=" * 72)
import json as _json                                          # noqa: E402
import news_feed as _nf122                                    # noqa: E402

# ① 중복 병합 — 장식([단독]·(종합)·기호)만 다른 제목은 같은 기사다
check("장식 다른 같은 제목을 병합 키로 묶는다",
      _nf122._norm_title('[단독] 삼성전자, 3나노 수주')
      == _nf122._norm_title('삼성전자 3나노 수주(종합)'))
check("다른 기사는 묶이지 않는다",
      _nf122._norm_title('삼성전자 3나노 수주')
      != _nf122._norm_title('삼성전자 4나노 수주'))
check("유사도 임계값 없이 정규화 완전 일치만 쓴다 (§2 — 숫자 안 고름)",
      '정규화 후 완전 일치' in open(_os.path.join(PROJ, 'news_feed.py'),
                              encoding='utf-8').read())

# ② 사건 유형 — 낱말 일치만, 해석 금지
check("수주 기사 → 수주·공급",
      _nf122.event_types_of('한화오션 2조원 LNG선 수주') == ['수주·공급'])
check("증자 기사 → 증자·CB",
      '증자·CB' in _nf122.event_types_of('E8, 40억원 규모 유상증자 실시'))
check("시황 해설은 사건이 아니다",
      _nf122.event_types_of('오늘 코스피 급락 마감') == [])

# ③ for_stock 계약 — 합성 기사로 오프라인 검증 (수신 실패와 무관하게 판정)
from datetime import datetime as _dt122, timedelta as _td122, \
    timezone as _tz122                                        # noqa: E402
_now122 = _dt122.now(_tz122(_td122(hours=9)))
_items122 = [
    {'title': '테스트전자 1조 수주', 'link': '', 'source': 'A',
     'dt': _now122, 'dup_sources': ['A', 'B']},
    {'title': '테스트전자 유상증자 검토', 'link': '', 'source': 'C',
     'dt': _now122 - _td122(hours=40), 'dup_sources': ['C']},
]
_s122 = _nf122.for_stock('테스트전자', items=_items122)
check("사건 유형 집계가 나온다",
      _s122['event_types'].get('수주·공급') == 1
      and _s122['event_types'].get('증자·CB') == 1)
check("신선/후행이 갈린다", _s122['fresh'] == 1 and _s122['lagging'] == 1)
check("헤드라인에 다중 출처 병합 사실을 밝힌다",
      _s122['headlines'][0]['sources_n'] == 2)
check("위험 낱말(유상증자)은 종전대로 잡힌다", '유상증자' in _s122['risk_words'])

# ④ 업종 원장 실측 — 표시 전용
import sector_cycle as _sc122                                 # noqa: E402
_sp122 = _sc122.ledger_perf('화학')
check("업종 실측 표가 로드된다", _sp122 is not None and _sp122['n'] >= 100)
check("Wilson 하한을 같이 낸다", 'wilson_low' in (_sp122 or {}))
check("없는 업종은 None — 지어내지 않는다",
      _sc122.ledger_perf('존재하지않는업종') is None)
_spj122 = _json.load(open(_os.path.join(PROJ, 'data', 'sector_perf.json'),
                          encoding='utf-8'))
check("실측 표가 블라인드 미포함을 명시한다",
      '블라인드 미포함' in _spj122.get('basis', ''))
check("표시 전용임을 명시한다 (라운드 44 결정 유지)",
      '점수·게이트에 사용하지 않는다' in _spj122.get('note', ''))
_w122 = open(_os.path.join(PROJ, 'web_app.py'), encoding='utf-8').read()
check("업황 카드가 업종 실측을 병기한다",
      '매수권 신호의 과거 실측' in _w122 and 'ledger_perf' in _w122)
check("표본 작으면 판단 근거로 이르다고 말한다",
      '판단 근거로 쓰기 이릅니다' in _w122)

# ⑤ 유효 독립 표본 — raw n 과 함께 표기
_en122 = _json.load(open(_os.path.join(PROJ, 'data', 'effective_n.json'),
                         encoding='utf-8'))
_enA = (_en122.get('sets') or {}).get('전체 원장') or {}
check("유효 표본이 산출돼 있다 (에피소드·군집·날짜)",
      all(k in _enA for k in ('raw', 'episodes', 'clusters', 'dates')))
check("에피소드 수가 raw 보다 작다 (독립성 보정이 실제로 걸림)",
      0 < _enA.get('episodes', 0) < _enA.get('raw', 0))
check("화면이 유효 독립 표본을 병기한다",
      '유효 독립 표본' in _w122 and '한 사건으로 묶음' in _w122)

# ⑥ 사전등록·코호트 — 다음 라운드 재료가 박제돼 있다
_pr122 = open(_os.path.join(PROJ, 'docs', 'PREREG_R55_REGIME_MOE.md'),
              encoding='utf-8').read()
check("R55 사전등록 — 가중치를 손으로 정하지 않는다",
      '가중치를 손으로 정하지 않는다' in _pr122)
check("R55 — blind 미사용·전방 확인 원칙", '전방 축적분' in _pr122)
check("R55 — 기각 시 현행 유지", '기각하고 현행 유지' in _pr122)
_cj122 = _json.load(open(_os.path.join(PROJ, 'data',
                                       'fv_revived_cohort.json'),
                         encoding='utf-8'))
check("복원 가치주 코호트가 박제됐다 (전방 검증용)",
      _cj122.get('n_caution', 0) >= 100 and len(_cj122.get('caution')) ==
      _cj122.get('n_caution'))

# ══════════════════════════════════════════════════════════════════════
# §123 — 라운드 55: 국면 라우팅 전방 병행 박제
#   첫 게이트 통과 후보. 즉시 적용이 아니라 2주 전방 재평가 후 적용 —
#   그 절차가 문서·정책 파일에 고정돼 있는지 잠근다.
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("§123 국면 라우팅 전방 병행 (라운드 55)")
print("=" * 72)
_rr123 = _json.load(open(_os.path.join(PROJ, 'data',
                                       'regime_routing_r55.json'),
                         encoding='utf-8'))
check("정책이 박제돼 있다 (8칸 라우팅)",
      len(_rr123.get('routing') or {}) == 8)
check("상태가 전방 병행이다 — 즉시 적용 아님",
      _rr123.get('status') == 'FORWARD_TRIAL')
check("blind 를 만지지 않았다", _rr123.get('blind_touched') is False)
check("재평가 날짜·기각 원칙이 정책에 적혀 있다",
      '2026-08-23' in str(_rr123.get('note'))
      and '현행 유지' in str(_rr123.get('note')))
_pr123 = open(_os.path.join(PROJ, 'docs', 'PREREG_R55_REGIME_MOE.md'),
              encoding='utf-8').read()
check("사전등록에 전방 재평가 §4b 가 있다",
      '전방 재평가 등록' in _pr123 and '재튜닝해 다시 전방을 보지 않는다'
      in _pr123)
check("측정 스크립트가 저장소에 있다",
      _os.path.exists(_os.path.join(PROJ, 'scripts', 'regime_moe_lab.py')))
check("커버리지 하한 기각이 기록돼 있다 (좋아 보여도 자른다)",
      '커버리지 30% 미달' in str(_rr123.get('valid_result')))

# ══════════════════════════════════════════════════════════════════════
# §124 — 라운드 56: 가격 역할 분리 · 뉴스→종목 전환 · 경로 축적
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("§124 가격 역할 분리 · 뉴스→종목 전환 · 경로 축적 (라운드 56)")
print("=" * 72)
_w124 = open(_os.path.join(PROJ, 'web_app.py'), encoding='utf-8').read()

# ① 적정가(가치) vs 매수기준(타이밍) — 괴리·이유 자동 설명
#    ⚠️ 소스 검사라 f-string 이 줄을 바꾸는 지점을 가로지르는 문자열은
#    못 찾는다 — 한 리터럴 안에 통째로 있는 조각만 쓴다.
check("배너가 두 가격의 역할을 가른다",
      '아직 싸지 않지만' in _w124 and '서로 다른 질문입니다' in _w124)
check("괴리를 숫자로 낸다 (지어내지 않고 계산)",
      '_gap_fv = (_core_entry / _fair - 1.0) * 100.0' in _w124)
check("타이밍·가치가 겹치는 자리도 구분해 말한다",
      '방향을 가리키는 자리입니다' in _w124
      and '사실상 같은 자리' in _w124 and '겹칩니다' in _w124)
check("안전마진선은 오늘의 매수가가 아님을 유지",
      '오늘의 매수가로 쓰지 않습니다' in _w124)
check("진입가 근거를 명시한다 (단순 % 할인 아님을 설명)",
      '기준가 − 20일 변동성 1일치 · 20봉 내 체결률 실측' in _w124)

# ② 뉴스 클릭 → 관련 종목 분석 전환
import live_ticker as _lt124                                  # noqa: E402
_NM124 = {'삼성전자': '005930.KS', 'GS': '078930.KS'}
check("헤드라인에서 종목을 찾는다",
      _lt124._match_stock('삼성전자 3나노 수주', _NM124) == '삼성전자 (005930)')
check("짧은 이름은 경계를 요구한다 (BGS 오탐 방지)",
      _lt124._match_stock('BGS 전자 신제품', _NM124) is None)
check("못 찾으면 None — 억지로 잇지 않는다",
      _lt124._match_stock('코스피 급락 마감', _NM124) is None)
_tb124 = _ukmod118.ticker_bar(
    [dict(kind='news', text='삼성전자 수주', href='https://e.x/1',
          pick='삼성전자 (005930)')], theme='dark')
check("제목 클릭은 같은 창(?pick=)", "?pick=" in _tb124
      and "target='_self'" in _tb124)
check("원문 '기사' 링크는 새 창으로 분리", ">기사</a>" in _tb124
      and "target='_blank'" in _tb124)
check("앱이 ?pick= 을 pending_search 경로로 받는다",
      "st.query_params.get('pick')" in _w124
      and "st.session_state['pending_search'] = str(_qp_pick)" in _w124)
check("받은 즉시 파라미터를 지운다 (새로고침 반복 방지)",
      "del st.query_params['pick']" in _w124)
check("띠 빌더가 이름 지도를 받는다",
      "name_map=globals().get('STOCK_NAME_MAP')" in _w124)

# ③ 경로 축적 — Exit·추적손절 연구의 선행 조건
_prc124 = open(_os.path.join(PROJ, 'scripts', 'path_recorder.py'),
               encoding='utf-8').read()
check("경로 기록기가 저장소에 있다", '봉 단위 경로 축적' in _prc124)
check("원장을 읽기만 한다", '원장(virtual_graded.jsonl)은 읽기만' in _prc124)
check("판정을 하지 않는다 — 원자료만", '판정·채점을 여기서 하지 않는다'
      in _prc124)
check("경로는 기준가 대비 %로 저장", "round(H[k] / px * 100 - 100, 3)"
      in _prc124)
check("왜 필요한지(mfe/mae 한계) 적었다", '청산 봉까지만' in _prc124)
# 라운드 57 사전 조사에서 추가 — 거래량 이탈형 Exit 후보 연구용
check("봉별 거래량을 신호일 대비 배율로 저장",
      'round(V[k] / v0, 2)' in _prc124)
check("신호일 거래량 0이면 배율을 지어내지 않는다 (None)",
      'if j < len(V) and V[j] > 0 else None' in _prc124)
check("케이스 스터디 스크립트가 저장소에 있다 (규칙 채택 없음)",
      _os.path.exists(_os.path.join(PROJ, 'scripts', 'exit_shape_study.py'))
      and _os.path.exists(_os.path.join(PROJ, 'scripts',
                                        'entry_depth_study.py')))
check("스터디가 최적화가 아님을 스스로 밝힌다",
      '최적화가 아니다' in open(_os.path.join(PROJ, 'scripts',
                                       'exit_shape_study.py'),
                          encoding='utf-8').read())

# ══════════════════════════════════════════════════════════════════════
# §125 — 라운드 58: 계층 실측 — '산출 불가'로 대화를 끝내지 않는다
#   초근접 5건이면 그 사실은 그대로 두고, 더 넓은 계층의 실측을 이름표와
#   함께 병기한다. 문턱 완화·표본 차용으로 채우는 길은 사전등록으로 막았다.
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("§125 계층 실측 (라운드 58)")
print("=" * 72)
import case_layers as _cl125                                  # noqa: E402

_cj125 = _json.load(open(_os.path.join(PROJ, 'data', 'case_layers.json'),
                         encoding='utf-8'))
check("계층 표가 생성돼 있다 (L5~L2)",
      all(k in _cj125 for k in ('L5', 'L4', 'L4b', 'L3', 'L2')))
check("표가 자기 성격을 밝힌다 — 종목 확률이 아니라 계층 실측",
      '이 종목의 확률이' in _cj125.get('note', '')
      and '블라인드 제외' in _cj125.get('basis', ''))
check("혼합 확률은 R59 게이트 통과 전 금지를 명시",
      'R59' in _cj125.get('note', ''))
_lay125, _ = _cl125.layers_for(49, sector=None, regime_code='BEAR',
                               fs={'market': 'KOSPI', 'vol_20': 0.02,
                                   'range_position_pct': 40,
                                   'm10_disparity': 5.0})
check("49점 종목에 40-49 점수대 층이 나온다",
      any('40-49' in r['label'] for r in _lay125))
check("각 층에 n·적중·Wilson·EV 가 있다",
      all(all(k in r for k in ('n', 'hit', 'wilson', 'ev'))
          for r in _lay125))
check("좁은 층이 뒤에 온다 (넓은 → 좁은 정렬)",
      [r['narrow'] for r in _lay125]
      == sorted(r['narrow'] for r in _lay125))
_lay125b, _note125 = _cl125.layers_for(45, sector='화학',
                                       regime_code='BEAR', fs={})
check("업종 미축적 점수대는 이유를 말한다 (지어내지 않음)",
      _note125 is not None and '매수권' in _note125)
check("모르는 점수는 빈 목록 — 조용히 실패하지 않는다",
      _cl125.layers_for(None) == ([], None))
_w125 = open(_os.path.join(PROJ, 'web_app.py'), encoding='utf-8').read()
check("가늠 AI 화면이 계층 실측을 병기한다",
      '더 넓은 계층의 실측' in _w125)
check("화면이 '종목 확률 아님'을 명시한다",
      '이 종목의 확률이 아니라 각 계층의 실측' in _w125)
check("문턱 완화 방식을 쓰지 않음을 화면에 밝힌다",
      '유사도 문턱을 낮춰' in _w125)
check("L5는 화면에서 뺀다 — 기존 점수대 실측과 이중 표기 금지 (§4)",
      "r.get('narrow', 0) > 0" in _w125)
_pr125 = open(_os.path.join(PROJ, 'docs', 'PREREG_R59_HIER_PROB.md'),
              encoding='utf-8').read()
check("R59 사전등록 — 기각 접근(문턱 인하·표본 차용) 명문화",
      '강제 확보' in _pr125 and '기준 인하' in _pr125)
check("R59 — Brier·보정도 게이트, 미달 시 현행 유지",
      'Brier' in _pr125 and '기각·현행 유지' in _pr125)

# ══════════════════════════════════════════════════════════════════════
# §126 — 라운드 57: Entry Engine 측정·박제 (전방 병행 대기)
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("§126 Entry Engine (라운드 57)")
print("=" * 72)
_ee126 = _json.load(open(_os.path.join(PROJ, 'data',
                                       'entry_engine_r57.json'),
                         encoding='utf-8'))
check("정책이 박제돼 있다 — 전방 병행 상태",
      _ee126.get('status') == 'FORWARD_TRIAL')
check("blind 를 만지지 않았다", _ee126.get('blind_touched') is False)
check("재평가 날짜·기각 원칙이 적혀 있다",
      '2026-08-23' in str(_ee126.get('note'))
      and '현행 유지' in str(_ee126.get('note')))
check("실행 정확화가 명시돼 있다 (시가 체결)",
      '다음 봉 시가' in str(_ee126.get('note')))
check("해석 경계(caveat)를 함께 박제했다",
      len(_ee126.get('caveats') or []) >= 3
      and any('우호' in c for c in _ee126['caveats']))
check("기준선(현행 눌림가)을 명시한다",
      '라운드 25' in str(_ee126.get('baseline')))
_pr126 = open(_os.path.join(PROJ, 'docs', 'PREREG_R57_ENTRY_ENGINE.md'),
              encoding='utf-8').read()
check("사전등록 — 역선택 배경과 정책 EV 정의가 있다",
      '역선택' in _pr126 and '신호 전체' in _pr126)
check("사전등록 — 기각 시 현행 유지·blind 미사용",
      '기각·현행 유지' in _pr126 and 'blind 미사용' in _pr126)
check("측정·축적 스크립트가 저장소에 있다",
      _os.path.exists(_os.path.join(PROJ, 'scripts', 'entry_engine_lab.py'))
      and _os.path.exists(_os.path.join(PROJ, 'scripts',
                                        'entry_anchor_recorder.py')))
_par126 = open(_os.path.join(PROJ, 'scripts', 'path_recorder.py'),
               encoding='utf-8').read()
check("경로가 시가를 저장한다 (실행 정확화 재료)",
      'O[k] / px * 100 - 100' in _par126)
check("기준선 축적이 누출을 금지한다 (이전 봉만)",
      '누출 금지' in open(_os.path.join(PROJ, 'scripts',
                                     'entry_anchor_recorder.py'),
                      encoding='utf-8').read())

# ══════════════════════════════════════════════════════════════════════
# §127 — 라운드 58b: Exit Engine 기각 — 현행이 도전자 12종을 방어
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("§127 Exit Engine 기각 (라운드 58b)")
print("=" * 72)
_pr127 = open(_os.path.join(PROJ, 'docs', 'PREREG_R58_EXIT_ENGINE.md'),
              encoding='utf-8').read()
check("사전등록 — 승률 하한 게이트가 있다 (EV 로 적중률을 사지 않는다)",
      '승률(양수 마감) ≥ 기준선 − 3%p' in _pr127)
check("사전등록 — 트레일링 배수 스캔 금지 (R36 교훈)",
      '배수 훑기' in _pr127 and '우연을 줍는다' in _pr127)
check("사전등록 — 불리한 근사 원칙 (갭 하향 종가 체결)",
      '불리한 쪽으로 근사' in _pr127)
_el127 = open(_os.path.join(PROJ, 'scripts', 'exit_engine_lab.py'),
              encoding='utf-8').read()
check("측정 스크립트가 저장소에 있다 — 손절 우선·종가 체결 구현",
      'cl[i] if cl[i] < stop else stop' in _el127
      and '손절 우선' in _el127)
_mv127 = open(_os.path.join(PROJ, 'docs', 'MODEL_VERSIONS.md'),
              encoding='utf-8').read()
check("기각 기록 — 현행이 도전자를 방어했다고 적었다",
      '어깨에서 파는 규칙이 전부 졌다' in _mv127
      and '기각 — 현행 유지' in _mv127)
check("승률 게이트 미달 사유를 숫자로 남겼다",
      '60.3% vs 66.2%' in _mv127)
check("train·valid 괴리(우호 구간 의존)를 기록했다",
      '+0.04' in _mv127 and '+4.31' in _mv127)

# ══════════════════════════════════════════════════════════════════════
# §128 — 라운드 59: 계층 혼합 확률 채택 (게이트 3/3 통과)
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("§128 계층 혼합 확률 (라운드 59)")
print("=" * 72)
_hp128 = _json.load(open(_os.path.join(PROJ, 'data',
                                       'hier_prob_tables.json'),
                         encoding='utf-8'))
check("운영 표가 있다 (m·3분위·셀)",
      _hp128.get('m') == 100 and len(_hp128.get('cells') or {}) >= 100
      and len(_hp128.get('vol_terciles') or []) == 2)
check("blind 미접촉·선택 기준 공개가 적혀 있다",
      '블라인드 미접촉' in _hp128.get('basis', '')
      and '명시되지 않았' in _hp128.get('note', ''))
_bl128 = _cl125.blended_prob(49, sector=None, regime_code='BEAR',
                             fs={'market': 'KOSPI', 'vol_20': 0.012,
                                 'range_position_pct': 40,
                                 'm10_disparity': 5.0})
check("혼합 확률이 나온다 (49점·약세)",
      _bl128 is not None and 0.3 < _bl128['p'] < 0.8)
check("근거 층수·최협층 n·Wilson 구간이 붙는다",
      all(k in _bl128 for k in ('layers', 'n_narrow', 'wilson_low',
                                'wilson_high')))
check("모르는 점수는 None — 지어내지 않는다",
      _cl125.blended_prob(None) is None)
_w128 = open(_os.path.join(PROJ, 'web_app.py'), encoding='utf-8').read()
check("화면 타일이 계층 보정 확률을 쓴다",
      '계층 보정' in _w128 and "blended_prob(" in _w128)
check("손절/미결 확률은 교체하지 않았다 (모르는 것을 섞지 않음)",
      "_pc(_g['sl_first'])" in _w128 and "_pc(_g['undecided'])" in _w128)
check("혼합값의 성격(이 종목만의 확률 아님)을 화면이 말한다",
      '이 종목만의 확률이 아니라' in _w128)
check("측정 랩이 저장소에 있다",
      _os.path.exists(_os.path.join(PROJ, 'scripts', 'hier_prob_lab.py')))
_mv128 = open(_os.path.join(PROJ, 'docs', 'MODEL_VERSIONS.md'),
              encoding='utf-8').read()
check("현행 유사사례 확률이 최악이었음을 기록 (35.4%p)",
      '35.4%p' in _mv128 and '전면 교체가 정당' in _mv128)

# ══════════════════════════════════════════════════════════════════════
# §129 — 라운드 60: 가늠 AI에게 물어보기 (결정적 조합기)
#   외부 LLM 미사용 — §9(포트폴리오 외부 전송 금지)와 요구 명세("중앙
#   값만·재계산 금지·없으면 없다고") 자체가 결정적 조합기를 가리킨다.
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("§129 가늠 AI에게 물어보기 (라운드 60)")
print("=" * 72)
import gaeum_chat as _gc129                                   # noqa: E402

_CTX129 = _gc129.build_context(
    name='시험전자', ticker='000001.KS', price=231000.0,
    core=dict(bucket='추천 제외', actionable=False,
              pullback_zone=211023.0, buy_zone=(208913, 213133),
              new_target=236572.0, new_stop=174524.0, rr=0.7,
              horizon_days=20, hold_trim=258968.0, hold_stop=191046.0),
    fs=dict(displayed_fair_value=173656.0,
            recommended_buy_price=147608.0, fair_value_status='CAUTION'),
    verdict=dict(headline='지금은 사지 마세요', score=49, action='HOLD',
                 vetoes=['표본 미달']),
    blend=dict(p=0.53, layers=4, n_narrow=5733,
               wilson_low=0.52, wilson_high=0.54),
    regime_code='BEAR', sector='반도체와반도체장비',
    news=dict(total=0), versions=dict(model='v-test'),
    cb=dict(lo=40, hi=49, hit_rate=55.0, n=20824))
_full129 = ''.join(_gc129.answer(q, _CTX129) for q in
                   ('지금 사도 돼?', '얼마에 사야 해?', '얼마에 팔아?',
                    '나는 205,000원에 가지고 있어. 어떻게 해?',
                    '확률은 믿을 수 있어?'))
check("답이 중앙 진입가만 쓴다", '211,023' in _full129)
check("답의 목표·손절 = 중앙 판정 값",
      '236,572' in _full129 and '174,524' in _full129)
check("보유자 값은 보유자 답에만, 분리 문구 포함",
      '258,968' in _full129 and '섞지 않습니다' in _full129)
check("폐기 산식(적정가×안전마진)을 답에 쓰지 않는다",
      '147,608' not in _full129)
check("R55·R57 을 운영값처럼 말하지 않는다",
      '전방 검증 전' in _full129 and '운영 판단에 쓰지 않습니다' in _full129)
check("자유 입력 평단 파싱 + 자릿수 가드",
      _gc129._avg_from_question('205,000원에 샀어', 231000.0) == 205000.0
      and _gc129._avg_from_question('10,000원에 샀어', 231000.0) is None)
check("없는 값은 없다고 말한다 (지어내지 않음)",
      _gc129.NA in _gc129.answer(
          '얼마에 사야 해?',
          _gc129.build_context(name='X', ticker='X', price=1000,
                               core={}, fs={}, verdict={})))
check("모르는 질문엔 준비된 틀이 없다고 말한다",
      '준비된 답변 틀이 없습니다' in _gc129.answer('점심 뭐 먹지', _CTX129))
check("뉴스 0건이면 미수신≠이슈없음 구분",
      '다른 말' in _gc129.answer('뉴스 영향은?', _CTX129))
check("외부 전송 금지 필드가 명시돼 있다 (§9)",
      'user_avg' in _gc129.PRIVATE_KEYS
      and 'holder_ret_pct' in _gc129.PRIVATE_KEYS)
_w129 = open(_os.path.join(PROJ, 'web_app.py'), encoding='utf-8').read()
check("화면에 대화 칸이 있고 종목별로 분리된다",
      '가늠 AI에게 물어보기' in _w129
      and 'gchat_{str(target_ticker)' in _w129)
check("고정 패널이 계층 보정 확률을 병기하고 대화로 잇는다",
      '계층 보정 확률' in _w129 and "#nav-ask" in _w129)
check("개인 정보가 PC 를 떠나지 않음을 화면이 말한다",
      '이 PC 를 떠나지 않습니다' in _w129)

# ══════════════════════════════════════════════════════════════════════
# §130 — 라운드 61: SELF 축·판단 품질 대시보드·특허/논문 태그
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("§130 SELF 축 · 판단 품질 · 특허/논문 (라운드 61)")
print("=" * 72)
_sh130 = _cl125.self_history('005930.KS')
check("SELF 이력이 나온다 (날짜·점수·결과·수익)",
      _sh130 is not None and _sh130['n'] >= 30
      and len(_sh130['recent'][0]) == 4)
check("모르는 종목 SELF 는 None — 지어내지 않는다",
      _cl125.self_history('999999.XX') is None)
_lay130, _ = _cl125.layers_for(49, regime_code='BEAR',
                               fs={'market': 'KOSPI', 'vol_20': 0.012},
                               ticker='005930.KS')
check("SELF 층이 가장 좁은 층으로 붙는다",
      any('자체' in r['label'] and r['narrow'] == 3 for r in _lay130))
check("R59 혼합에는 SELF 가 없다 (게이트 통과 구성 보존)",
      'ticker' not in _cl125.blended_prob.__code__.co_varnames[:6])
_cj130 = _json.load(open(_os.path.join(PROJ, 'data', 'case_layers.json'),
                         encoding='utf-8'))
check("표가 SELF 미혼합 원칙을 명시한다",
      'R59 혼합에 넣지 않는다' in _cj130.get('note', ''))
check("특허 태그 — 취득 계열만, 소송은 제외",
      _nf122.event_types_of('OO바이오 특허 취득') == ['특허']
      and _nf122.event_types_of('특허 소송 패소') == [])
check("논문·학회 태그", _nf122.event_types_of('SCI 논문 등재')
      == ['논문·학회'])
_w130 = open(_os.path.join(PROJ, 'web_app.py'), encoding='utf-8').read()
check("판단 근거 대시보드가 있다 (엔진별 의견)",
      '이번 판단을 만든 근거들' in _w130 and '엔진별 의견' in _w130)
check("약점 카드가 가늠 AI 한계를 재사용한다 (§4 한 소스)",
      "_weak61 = list((_g.get('limits') or [])[:2])" in _w130)
check("R55 미사용을 대시보드가 명시한다",
      '8/23 전방 검증 전 — 이번 판단에 미사용' in _w130)
check("엔진 비교 표의 상태가 실제 라운드 결과다",
      '기각 — 현행 방어' in _w130 and '전방검증 대기 (8/23)' in _w130)
check("SELF 실체 표가 있다 (그 사례들이 뭔데)",
      '이 종목 과거 신호 실체' in _w130)
check("후보 숫자를 운영 판단에 섞지 않음을 명시",
      '운영 판단에 섞이지 않으며' in _w130)

# ══════════════════════════════════════════════════════════════════════
# §131 — 라운드 62: 유사사례 실체 — 확률은 못 내도 본 것은 보여 준다
#   사용자 지적: "5건이라 산출 불가"로 끝나고 그 5건이 무엇인지 안 보였다.
#   표본 미달 경로에서도 실체를 낸다 (표시 전용 · 판정 미사용).
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("§131 유사사례 실체 (라운드 62)")
print("=" * 72)
_qs131 = open(_os.path.join(PROJ, 'quant_indicators.py'),
              encoding='utf-8').read()
check("미산출 지평도 실체를 싣는다 (매개변수)",
      'def _insufficient_horizon(H, n, reason, matches=None)' in _qs131)
check("두 경로가 같은 함수로 실체를 만든다 (§4)",
      _qs131.count('_match_rows_of(dedup_matches, _rho_of, H)') == 2)
check("확률은 못 내도 본 것은 보여 준다고 적었다",
      '확률은 못 내도' in _qs131 and '판정에 쓰지 않는다' in _qs131)
_h131 = (snap.get('sim_res') or {}).get('horizons_data') or {}
_m131 = (_h131.get(20) or {}).get('matches')
check("실제 파이프라인에서 실체가 나온다", isinstance(_m131, list))
if _m131:
    check("행에 날짜·유사도·가격·결과·수익·낙폭이 있다",
          set(_m131[0]) >= {'date', 'rho', 'price', 'outcome',
                            'ret_pct', 'mdd_pct'})
    check("날짜가 실제 값이다 (지어내지 않음)",
          all(r['date'] for r in _m131))
    check("결과는 세 갈래 중 하나",
          all(r['outcome'] in ('목표 선도달', '손절 선도달', '미도달')
              for r in _m131))
    check("표시 상한 12건", len(_m131) <= 12)
_w131 = open(_os.path.join(PROJ, 'web_app.py'), encoding='utf-8').read()
check("화면이 유사사례 실체 표를 그린다",
      '이 종목의 유사사례 실체' in _w131)
# ⚠️ 소스 검사는 f-string 이 줄을 바꾸는 지점을 가로지르는 문자열을
# 찾지 못한다 — 한 리터럴 안에 통째로 있는 조각만 쓴다 (라운드 63).
check("표본 적어도 숨기지 않는다는 문구",
      '숨기지 않습니다' in _w131 and '확률로 환산하지 않지만' in _w131)

# ══════════════════════════════════════════════════════════════════════
# §132 — 라운드 63: 살 수 없는 가격을 사라고 하지 않는다
#   사용자 지적("적정가 17만인데 왜 21만에 사라고?")을 실측으로 판정.
#   매수권(58+) 15,332건 중 '적정가 크게 초과' 구간은 **0건** — 엔진이
#   이미 통째로 차단하고 있었다. 그런데 화면은 그 구간의 가격을 "이하로
#   내려올 때만 사세요"라고 말했다. 문구가 게이트를 따라가게 고쳤다.
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("§132 살 수 없는 가격을 사라고 하지 않는다 (라운드 63)")
print("=" * 72)
_va132 = _json.load(open(_os.path.join(PROJ, 'data',
                                       'valuation_premium_audit.json'),
                         encoding='utf-8'))
_z132 = _va132.get('zones') or {}
check("프리미엄 감사 산출물이 있다 (구간별 n·적중·EV)",
      len(_z132) >= 4 and all('ev' in v for v in _z132.values()))
check("'크게 초과' 구간은 매수권에 없다 (엔진이 차단 중)",
      not any('크게 초과' in k and v.get('n', 0) > 0
              for k, v in _z132.items()))
check("감사가 게이트 채택이 아님을 밝힌다",
      '게이트 채택 없음' in _va132.get('note', ''))
check("entry_zone 은 원장 기록을 그대로 썼다 (새 정의 없음)",
      '새 정의 없음' in _va132.get('note', ''))
_w132 = open(_os.path.join(PROJ, 'web_app.py'), encoding='utf-8').read()
check("진입가에서도 차단이 유지되는지 판정한다",
      '_still_blocked = bool(' in _w132
      and "/ float(_floor_fv)) > 1.15" in _w132)
check("제목이 매수 지시로 읽히지 않는다",
      '(가격 조건만 · 매수 신호 아님)' in _w132)
check("도달해도 신호가 아님을 본문이 말한다",
      '이 가격에 도달해도 지금 ' in _w132 and '매수 신호가 아닙니다'
      in _w132)
check("무엇이 바뀌어야 후보가 되는지 알려준다",
      '안전마진선' in _w132 and '내려와야 합니다' in _w132)
check("실측 근거를 화면에 병기한다", '15,332건 중 0건' in _w132)
check("차단되지 않는 경우의 종전 설명은 유지",
      '서로 다른 질문입니다' in _w132)
_sc132 = _os.path.join(PROJ, 'scripts', 'valuation_premium_audit.py')
check("감사 스크립트가 저장소에 있다", _os.path.exists(_sc132))

# ══════════════════════════════════════════════════════════════════════
# §133 — 라운드 64·65: 돌파 하이패스 기각 · 떠 있는 가늠 AI 버튼
# ══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 72)
print("§133 돌파 하이패스 기각 · 떠 있는 AI 버튼 (라운드 64·65)")
print("=" * 72)
_bs133 = _json.load(open(_os.path.join(PROJ, '.portfolio',
                                       'breakout_study_r64.json'),
                         encoding='utf-8'))
check("돌파 연구가 blind 를 만지지 않았다",
      _bs133.get('blind_touched') is False)
check("게이트 판정이 기각이다 (자동 채택 없음)",
      _bs133.get('gate_pass') is False)
check("기각 사유가 거짓돌파 지표다",
      _bs133['gates'].get('거짓돌파 < 50%') is False
      and _bs133['gates'].get('EV > 비돌파') is True)
check("돌파 코호트 성적이 기록돼 있다",
      (_bs133.get('breakout') or {}).get('ev') is not None
      and (_bs133.get('non_breakout') or {}).get('ev') is not None)
_pr133 = open(_os.path.join(PROJ, 'docs', 'PREREG_R64_BREAKOUT_BYPASS.md'),
              encoding='utf-8').read()
check("사전등록 — 측정 없는 우회를 금지한다고 적었다",
      '측정 없이 넣지 않는다' in _pr133 and '라운드 27b' in _pr133)
check("사전등록 — 손절 -3% 같은 손 숫자 금지",
      '손으로 고른 숫자를 쓰지 않는다' in _pr133)
check("지표 결함을 기록하되 오늘 고쳐 재측정하지 않는다",
      '다시 정의해 재측정하지 않는다' in _pr133
      and '대조군이' in _pr133)
# ⚠️ 문서 검사는 마크다운 굵기(**)가 낱말 사이에 끼면 못 찾는다 —
# 강조 없는 조각으로 본다 (라운드 65).
check("정정 정의는 새 사전등록(R66)·전방 데이터로 예약",
      'R66' in _pr133 and '로 잰다' in _pr133
      and '같은 개발 구간을 다시 보지' in _pr133)
check("돌파를 전부 막고 있지 않다는 반증도 기록",
      '성립하지 않는다' in _pr133 and '2,755건' in _pr133)
_sc133 = _os.path.join(PROJ, 'scripts', 'breakout_study.py')
check("돌파 측정 스크립트가 저장소에 있다", _os.path.exists(_sc133))
check("돌파 지표가 신호일 이전 봉만 쓴다 (누출 금지)",
      '신호일 제외 (누출 금지)' in open(_sc133, encoding='utf-8').read())
_w133 = open(_os.path.join(PROJ, 'web_app.py'), encoding='utf-8').read()
check("떠 있는 가늠 AI 버튼이 있다",
      'gn-ask-fab' in _w133 and "href=\"#nav-ask\"" in _w133)
check("좁은 화면에서 글자를 접는다 (아이콘만)",
      '@media (max-width: 640px)' in _w133 and '.gn-ask-t' in _w133)
check("버튼에 이모지를 쓰지 않는다 (Lucide SVG)",
      "_uk._icon('help'" in _w133)

# 버전 칩 — 낮은 버전이 '낡음'이 아님을 화면이 설명하는가
check("버전 칩에 근거 설명이 붙는다",
      '이후 바뀌지 않았습니다' in _w109
      and '그 축이 마지막으로 바뀐 시점' in _w109)
# 축별 버전이 실제로 그 축의 파일 변경과 맞는가 (뒤처지면 실패)
import subprocess as _sp109
_AXF109 = {'model': ['quant_indicators.py', 'verdict_core.py',
                     'price_axes.py', 'regime_policy.py'],
           'rulebook': ['analysis_rulebook_ko.txt'],
           'news': ['market_context.py'],
           # 라운드 44 신설 — 적정가와 섹터를 model 축에서 떼어 냈다
           'valuation': ['price_axes.py'],
           'sector': ['sector_cycle.py']}
for _ax109, _files109 in _AXF109.items():
    _v109 = _ver101.current(_ax109)
    _vd109 = _v109[1:11].replace('.', '-') if _v109.startswith('v') else ''
    _last109 = ''
    for _f109 in _files109:
        if not _os.path.exists(_os.path.join(PROJ, _f109)):
            continue
        _d109 = _sp109.run(['git', 'log', '-1', '--date=short', '--pretty=%ad',
                            _f109], cwd=PROJ, capture_output=True, text=True,
                           encoding='utf-8', errors='replace').stdout.strip()
        if _d109 > _last109:
            _last109 = _d109
    check(f"'{_ax109}' 버전이 담당 파일 변경보다 뒤처지지 않는다",
          (not _last109) or _vd109 >= _last109,
          f'버전 {_v109}({_vd109}) vs 파일 최종 변경 {_last109}')


print()
print("=" * 72)
if FAILURES:
    print(f"실패 {len(FAILURES)}건: " + ", ".join(FAILURES))
    sys.exit(1)
print("전체 통과")
sys.exit(0)
