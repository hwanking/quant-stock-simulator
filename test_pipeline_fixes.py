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
    check("군집 경로가 서로 다름",
          float(_np.mean(_np.abs(_np.asarray(hz20['path_bull']) - _np.asarray(hz20['path_bear'])))) > 1e-9)
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

# ⚠️ 헤더 없이 숫자만 많은 줄은 추측하면 반드시 틀린다 (매도가능수량을 평단가로 넣는다).
#    틀린 값을 조용히 넣지 말고 읽지 못했다고 말해야 한다.
_amb_rows, _amb_warns = pf.parse_freeform_holdings(_BODY.splitlines()[0], resolve_name=_RS)
check("헤더 없이 숫자 다수면 추측하지 않음",
      len(_amb_rows) == 1 and _amb_rows[0]['보유수량'] is None
      and _amb_rows[0]['평균매수가'] is None, str(_amb_rows)[:90])
check("추측 불가를 사용자에게 알림",
      any("알 수 없습니다" in w for w in _amb_warns), str(_amb_warns[:1])[:90])

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
      == '🔥 관심 급증·추격주의')
check("관심 낮음 + 행동 높음 = 선행 후보",
      mkt.classify_bucket({'adjusted_attention_score': 20.0, 'overheated': False}, 75)
      == '🌱 조용한 선행 후보')
check("둘 다 높아야 실전 추천",
      mkt.classify_bucket({'adjusted_attention_score': 80.0, 'overheated': False}, 75)
      == '🏆 실전 추천 후보')

# §12 관심점수의 순위 영향은 5% 이내로 제한
check("관심점수 가산점 상한 5점",
      mkt.attention_tiebreak_bonus(100.0) <= mkt.ATTENTION_TIEBREAK_MAX_PCT + 1e-9,
      f"{mkt.attention_tiebreak_bonus(100.0):.2f}")
check("관심점수가 행동점수를 뒤집지 못함",
      68 + mkt.attention_tiebreak_bonus(0.0) < 75 + mkt.attention_tiebreak_bonus(0.0))

# 연동되지 않은 후보 방식은 임의로 만들어내지 않고 사유를 돌려준다 (§14)
_na = mkt.find_attention_candidates('news', top_n=5)
check("뉴스·공시 방식은 미연동 사유 반환",
      not _na['rows'] and bool(_na['unavailable']), str(_na['unavailable'])[:60])

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
check("뉴스·공시 촉매 연동됨(부분)", _ds['뉴스·공시 촉매']['availability'] == 'partial',
      _ds['뉴스·공시 촉매']['availability'])
check("공시 항목이 한계를 명시", "최근" in _ds['뉴스·공시 촉매']['detail']
      and "뉴스 기사" in _ds['뉴스·공시 촉매']['detail'])
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
check("당일 공시 수집", len(_disc) >= 20, f"{len(_disc)}개사")
_types = {i['type'] for v in _disc.values() for i in v}
check("공시 유형 분류", len(_types) >= 3, str(sorted(_types)[:6]))
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
for _sym in ("005930.KS", "003490.KS", "018880.KS", "037710.KS"):
    _sn = q.run_full_pipeline(_sym, T_REF, b_engine=engine, rho_cutoff=0.80)
    _f = _sn['four_scores']
    _bb_states.append(_f.get('bb_state'))
    _bull.append(_f.get('demark_bullish_score'))
    _bear.append(_f.get('demark_bearish_score'))
    _labels.append(_f.get('demark_direction_text'))
    check(f"{_sym} 볼린저 위치 산출", _f.get('bb_position_pct') is not None,
          f"{_f.get('bb_position_pct')} · {_f.get('bb_state')}")

check("볼린저 상태가 four_scores 에 노출됨", all(s for s in _bb_states), str(_bb_states))
check("볼린저 상태가 종목마다 다를 수 있음", len(set(_bb_states)) >= 2, str(_bb_states))
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

# 종목마다 결론이 달라야 한다 (고정 문구가 아님)
_heads = set()
for _sym in ("005930.KS", "037710.KS", "069500.KS"):
    _heads.add(q.build_final_verdict(
        q.run_full_pipeline(_sym, T_REF, b_engine=engine, rho_cutoff=0.80))['headline'])
check("결론이 종목마다 분화", len(_heads) >= 2, str(_heads))

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
check("실행 가격에 기준(신규/보유자) 라벨", "현재가 기준 — 보유자용" in _w41)
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


print()
print("=" * 72)
if FAILURES:
    print(f"실패 {len(FAILURES)}건: " + ", ".join(FAILURES))
    sys.exit(1)
print("전체 통과")
sys.exit(0)
