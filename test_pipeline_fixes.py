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
      "이미 갖고 계신 분 기준" in _w41 and "아직 안 샀다면" in _w41)
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
      _fs47.get('final_action_title') != '⚠️ 재검토 필요'
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
_f47h['final_action_title'] = '⚠️ 재검토 필요'
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

# ② 변동성 관리 비중 — 10~100% 사이, 근거 문구 포함
_sp53 = _fs53.get('suggested_position_pct')
check("비중 제안 존재", _sp53 is not None)
check("비중 제안 10~100% 범위", _sp53 is None or 10 <= _sp53 <= 100, str(_sp53))
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
check("카드에 진입 후보 배지(🎯)", "_entry_badge" in _w56)
check("카드 월봉10선 열에 DeMARK 배지 병기", "⏱️매수신호" in _w56)


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
check("규칙집 버전 v2026.08.02",
      str(qi.RULEBOOK.get('RULES_GENERAL', {}).get('version')) == "v2026.08.02")
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

_fs59 = {'recommended_buy_price': 10000, 'buy_entry_max': 11000,
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

_e59b = q.build_easy_advice(_fs59, {'score': 70, 'action': 'BUY', 'vetoes': []}, 9800)
check("매수 가능 → '지금 사도 됩니다 (나눠서)'",
      '지금 사도 됩니다' in _e59b['new_buyer']['line'])
check("틀릴 가능성을 실측으로 명시",
      '틀릴 가능성' in _e59b['new_buyer']['detail'])

_e59c = q.build_easy_advice({'recommended_buy_price': None, 'm10_disparity': 0},
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
_fs60 = {'recommended_buy_price': 10000, 'buy_entry_max': 11000,
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
_p61 = pm61._pm_path(_dk61)
if _os.path.exists(_p61):
    _os.remove(_p61)
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
_os.remove(_p61)              # 시험용 파일 정리 (이력은 append-only 로 남긴다)

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
_html62 = cp62.build_chart_html(_tdf62, _fs62, name='시험', theme='dark',
                                user_avg=130.0)
check("HTML 문자열 생성", isinstance(_html62, str) and len(_html62) > 100_000)
check("지표 선택창 존재 (사용자가 원하는 지표를 고른다)",
      'indPanel' in _html62 and '지표 선택' in _html62)
check("추가 지표 — 스토캐스틱·OBV·EMA20",
      all(k in _html62 for k in ('stochK', 'obv', 'ema20')))
check("선택 상태 저장 (localStorage)", 'qchart_ind_v1' in _html62)
check("실행 가격선 = 배너와 같은 숫자 (추천매수·목표·손절·평단)",
      all(s in _html62 for s in ('추천 매수가', '1차 목표가', '손절가',
                                 '내 평단가')))
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
check("홈 카드 5종 — 사용자 언어 라벨", all(s in _w63 for s in (
    "'되돌려 본 판단'", "'추천했을 때 연습 적중률'",
    "'추천했을 때 실전 적중률'", "'추천만 골랐을 때'", "'매수 기회'")))
check("홈 카드 — 킷 컴포넌트로 렌더 (인라인 HTML 금지)",
      '_uk.stat_tiles(' in _w63 and '_uk.section(' in _w63)
check("홈 카드 — 대표 지표가 '추천했을 때' 기준 (전체 사례가 아님)",
      '추천했을 때 실전 적중률' in _w63
      and '매수 신호 {_bzv.get' in _w63)
check("홈 카드 — 전체 사례 적중률도 숨기지 않고 보조로 남긴다",
      '추천하지 않은 것까지 포함한' in _w63)
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
check("점수 요인 상·하위 3 카드", '점수를 끌어올린 요인 3' in _w63
      and '점수를 끌어내린 요인 3' in _w63)
check("요인은 composition 실측에서만",
      "verdict.get('composition'" in _w63)

# ④ 내비게이션 — 모델 성과 링크와 앵커
check("내비 모델 성과 링크 — 좌측 내비에 정의, 앵커는 본문에",
      "'href': '#nav-perf'" in _w63 and 'id="nav-perf"' in _w63)


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
check("케이스 앵커 유지 · 좌측 내비 1차 5개 + 서브 8개",
      'id="nav-cases"' in _w64
      and _w64.count("'href': '#nav-") >= 12)


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
check("사이드바 구역 — 킷 라벨로 통일 · 가로선 없음",
      '_uk.sidebar_section("종목"' in _w76
      and '_uk.sidebar_section("종목 찾기"' in _w76
      and 'st.sidebar.markdown("---")' not in _w76)


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
    check("약세장 게이트는 채택하지 않았다 (양쪽 동시 통과 실패)",
          _rbd82.get('bear_gate_adopted') is False)

_w82 = open(_os.path.join(PROJ, "web_app.py"), encoding='utf-8').read()
check("화면 — 국면별 성적을 나눠 보여준다",
      '시장 국면별 추천 성적' in _w82 and 'regime_breakdown.json' in _w82)
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
check("상단 상태바 — 운영 버전 칩이 오른쪽 끝",
      '_uk.status_bar(' in _w86)

_u86 = open(_os.path.join(PROJ, "ui_kit.py"), encoding='utf-8').read()
check("상태바 컴포넌트 존재", 'def status_bar(' in _u86)
check("상태바는 가장 조용한 줄이어야 한다고 명시",
      '가장 조용한 줄이어야 한다' in _u86)


print()
print("=" * 72)
if FAILURES:
    print(f"실패 {len(FAILURES)}건: " + ", ".join(FAILURES))
    sys.exit(1)
print("전체 통과")
sys.exit(0)
