# -*- coding: utf-8 -*-
"""
가상 백테스트 캘리브레이션 랩 — 실제 판정 엔진을 과거 기준일로 ~100회 돌려 채점한다.

무엇을 하나:
  1. 종목 × 과거 기준일 격자에서 run_full_pipeline(리플레이 모드)을 돌린다.
     리플레이 모드는 그 날 알 수 있었던 것만 쓴다(오늘 시세·지수·뉴스 차단).
  2. 각 가상 판정을 이후 실제 봉과 대조해 채점한다 (목표가/손절가 선도달).
  3. 점수대별 실제 적중률(캘리브레이션 표)과 조건별 리프트를 집계해
     .portfolio/calibration.json 으로 저장한다 — 엔진이 이 표를 읽어
     종합점수 확신에 되먹인다.

정직성 원칙:
  · 채점 기준(목표가·손절가·기간)은 엔진이 그 시점에 내놓은 값 그대로다.
    사후에 유리하게 고르지 않는다.
  · 표본이 적은 점수대는 적중률을 내밀지 않는다 (Wilson 하한 병기).
  · 결과 파일은 중간 산출물을 체크포인트로 남겨 재실행 시 이어서 돈다.

실행:  python scripts/calibration_lab.py [--limit N]
"""
import json
import os
import sys
import time
import warnings

warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

import numpy as np

import bitemporal_engine as be
import prediction_log as plog
import quant_indicators as qi

VIRT_FILE = os.path.join(PROJ, ".portfolio", "virtual_predictions.jsonl")
CALIB_FILE = os.path.join(PROJ, ".portfolio", "calibration.json")

#: 종목 풀 — 시총·업종·시장이 섞이도록 고정 (감사 §41 FIXED_SET 계열)
TICKERS = [
    "005930.KS",  # 삼성전자 (대형 기술)
    "003490.KS",  # 대한항공 (대형 경기민감)
    "051910.KS",  # LG화학 (대형 소재)
    "035760.KQ",  # CJ ENM (코스닥 대형)
    "052330.KQ",  # 코텍 (코스닥 중소형)
    "002990.KS",  # 금호건설 (소형 건설)
    "073240.KS",  # 금호타이어
    "111770.KS",  # 영원무역
]

#: 홀드아웃 — 산식(기하·필터)을 위 8종목으로 진단·수정한 뒤, 손대지 않은 종목에서
#: 같은 성적이 나오는지 확인한다. 여기서 무너지면 과적합이다.
HOLDOUT_TICKERS = [
    "000660.KS",  # SK하이닉스
    "005380.KS",  # 현대차
    "035420.KS",  # NAVER
    "036570.KS",  # 엔씨소프트
    # 2차 확장 (2026-08-01) — 업종·시총 다변화로 표본을 넓힌다
    "005490.KS",  # POSCO홀딩스 (철강)
    "055550.KS",  # 신한지주 (금융)
    "068270.KS",  # 셀트리온 (바이오)
    "015760.KS",  # 한국전력 (유틸리티)
    "017670.KS",  # SK텔레콤 (통신)
    "097950.KS",  # CJ제일제당 (음식료)
    "247540.KQ",  # 에코프로비엠 (코스닥 2차전지)
    "196170.KQ",  # 알테오젠 (코스닥 바이오)
    "042700.KS",  # 한미반도체 (중형 장비)
    "064350.KS",  # 현대로템 (방산·기계)
    "009830.KS",  # 한화솔루션 (화학·태양광)
    "030200.KS",  # KT (통신)
    # 3차 확장 (2026-08-02) — 1,000건 목표: 중·소형, 저유동성, ETF 유형까지 전방위
    "051910.KS",  # (기존 유지 자리표시 — 중복은 자동 건너뜀)
    "032830.KS",  # 삼성생명 (보험)
    "010130.KS",  # 고려아연 (비철금속)
    "011200.KS",  # HMM (해운)
    "086790.KS",  # 하나금융지주
    "000270.KS",  # 기아
    "012330.KS",  # 현대모비스
    "051900.KS",  # LG생활건강 (경기소비)
    "090430.KS",  # 아모레퍼시픽
    "047810.KS",  # 한국항공우주 (방산)
    "028670.KS",  # 팬오션 (중형 해운)
    "004000.KS",  # 롯데정밀화학 (중형 화학)
    "336260.KS",  # 두산퓨얼셀 (중형 성장)
    "112610.KS",  # 씨에스윈드 (중형 풍력)
    "025900.KQ",  # 동화기업 (코스닥 중소형)
    "036930.KQ",  # 주성엔지니어링 (코스닥 장비)
    "058470.KQ",  # 리노공업 (코스닥 부품)
    "215200.KQ",  # 메가스터디교육 (코스닥 교육)
    "078340.KQ",  # 컴투스 (코스닥 게임)
    "041510.KQ",  # 에스엠 (코스닥 엔터)
    "035900.KQ",  # JYP Ent.
    "095340.KQ",  # ISC (코스닥 소형)
    "137400.KQ",  # 피엔티 (코스닥 소형 장비)
    "900140.KQ",  # 엘브이엠씨홀딩스 (저유동성)
    # ETF 유형 — 일반 / 해외지수 / 레버리지 / 인버스
    "069500.KS",  # KODEX 200 (일반)
    "229200.KS",  # KODEX 코스닥150 (일반)
    "360750.KS",  # TIGER 미국S&P500 (해외지수)
    "133690.KS",  # TIGER 미국나스닥100 (해외지수)
    "122630.KS",  # KODEX 레버리지
    "233740.KS",  # KODEX 코스닥150레버리지
    "114800.KS",  # KODEX 인버스
    "252670.KS",  # KODEX 200선물인버스2X
    # 4차 확장 (2026-08-02) — 2,000건 방향: 중형·경기방어·바이오 보강
    "010950.KS",  # S-Oil
    "034020.KS",  # 두산에너빌리티
    "018260.KS",  # 삼성에스디에스
    "032640.KS",  # LG유플러스
    "000810.KS",  # 삼성화재
    "009150.KS",  # 삼성전기
    "006400.KS",  # 삼성SDI
    "128940.KS",  # 한미약품
    "008930.KS",  # 한솔케미칼 (중형)
    "095700.KQ",  # 제넥신 (코스닥 바이오 소형)
]

#: 시간 분할 — 모델 개선은 학습·검증 구간의 통계로만 하고, 블라인드 구간은
#: 성능 보고에만 쓴다 (개선 근거로 사용 금지). 경계는 사례 기준일 기준.
SPLIT_VALID_FROM = "2025-07-01"
SPLIT_BLIND_FROM = "2026-02-01"


def split_of(date_str):
    d = str(date_str)
    if d >= SPLIT_BLIND_FROM:
        return 'blind'
    if d >= SPLIT_VALID_FROM:
        return 'valid'
    return 'train'

#: 과거 기준일 — 20영업일(판정 지평)보다 넓은 25봉 간격으로 떼어 표본 중복을 줄인다
def make_asof_dates(prices_df, n_dates, horizon=20, spacing=25):
    dates = list(prices_df['trade_date'].astype(str))
    # 마지막 판정도 채점 가능해야 하므로 horizon 봉 이전에서 끊는다
    usable = dates[260:len(dates) - horizon - 1]
    picked = usable[::-spacing][:n_dates]     # 최근에서 과거로 spacing 간격
    return sorted(picked)


def load_done():
    done = set()
    if os.path.exists(VIRT_FILE):
        with open(VIRT_FILE, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                    done.add((r['ticker'], r['date']))
                except Exception:
                    continue
    return done


def wilson_low(hit, n, z=1.96):
    if n == 0:
        return None
    p = hit / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5
    return max(0.0, (centre - margin) / denom) * 100.0


def main(limit=200):
    q = qi.QuantIndicatorsEngine()
    eng = be.BitemporalEngine()
    done = load_done()
    os.makedirs(os.path.dirname(VIRT_FILE), exist_ok=True)

    # 시장 국면(그 날짜 기준) — 지수 시계열을 기준일 이하로 잘라 계산한다 (누수 없음)
    idx_series = {}
    for mkt in ("KOSPI", "KOSDAQ"):
        idx_series[mkt] = eng.fetch_index_daily(mkt, 1200)

    def regime_at(mkt, d):
        s = idx_series.get(mkt)
        if s is None:
            return None
        dates_i, closes_i = s
        import numpy as _np
        mask = dates_i.astype(str) <= str(d).replace('-', '')
        c = closes_i[mask] if mask.any() else closes_i[:0]
        if len(c) < 60:
            return None
        p, s20, s60 = float(c[-1]), float(c[-20:].mean()), float(c[-60:].mean())
        if p > s20 > s60:
            return 'BULL'
        if p < s20 and p < s60:
            return 'BEAR'
        return 'SIDEWAYS'

    todo = []
    price_cache = {}
    for tk in dict.fromkeys(TICKERS + HOLDOUT_TICKERS):     # 중복 자동 제거
        try:
            pdf, _f = eng.generate_synthetic_bitemporal_data(
                symbol=tk, start_date='2020-01-01', end_date=None)
            price_cache[tk] = pdf
            for d in make_asof_dates(pdf, n_dates=30):
                if (tk, d) not in done:
                    todo.append((tk, d))
        except Exception as exc:
            print(f"  [건너뜀] {tk} — {type(exc).__name__}: {exc}")

    total_planned = len(done) + len(todo)
    print(f"가상 판정 계획: 완료 {len(done)}건 · 남음 {len(todo)}건 (계획 {total_planned}건)")
    t0 = time.time()
    ran = 0
    for tk, d in todo:
        if ran >= limit:
            print(f"  이번 실행 한도({limit}건) 도달 — 체크포인트에서 이어서 실행 가능")
            break
        try:
            snap = q.run_full_pipeline(tk, d, b_engine=eng, rho_cutoff=0.80)
            fs = snap['four_scores']
            assert snap.get('is_replay'), "리플레이 모드가 아니면 누수다"
            row = {
                'ticker': tk, 'date': d,
                'cohort': 'holdout' if tk in HOLDOUT_TICKERS else 'main',
                'asset_type': fs.get('asset_type', 'STOCK'),
                'market': 'KOSDAQ' if tk.endswith('.KQ') else 'KOSPI',
                'regime': regime_at('KOSDAQ' if tk.endswith('.KQ') else 'KOSPI', d),
                'price': float(fs.get('curr_price') or snap['rt_price']),
                'score': int(fs.get('final_action_score')),
                'action_title': fs.get('final_action_title'),
                'target': fs.get('target_tech_1st'),
                'stop': fs.get('stop_loss_price'),
                'horizon_days': 20,
                # 조건 리프트 분석용 특징 (그 시점 값)
                'm10_above': bool(float(fs.get('m10_disparity', 0) or 0) >= 0),
                'demark_state': ((fs.get('demark_entry') or {}).get('state')),
                'entry_zone': fs.get('entry_zone'),
                'net_expected': fs.get('net_expected_return'),
                # 2차 확장 특징 — 어떤 상태가 적중을 예측하는지 볼 재료
                'rsi': (fs.get('demark_res') or {}).get('rsi_value'),
                'bb_pos': (fs.get('demark_res') or {}).get('bb_position_pct'),
                'vol20': fs.get('vol_20') or None,
                'range_pos': (snap.get('price_pos') or {}).get('range_pos_pct'),
                'demark_bull': (fs.get('demark_res') or {}).get('bullish_score'),
                'demark_bear': (fs.get('demark_res') or {}).get('bearish_score'),
                'win_rate': (snap.get('sim_res') or {}).get('obs_win_ratio'),
                'eff_sample': fs.get('eff_sample_size'),
            }
            with open(VIRT_FILE, 'a', encoding='utf-8') as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            ran += 1
            if ran % 10 == 0:
                el = time.time() - t0
                print(f"  {ran}/{len(todo)}건 · {el:,.0f}s 경과 · 건당 {el/ran:.1f}s")
        except Exception as exc:
            print(f"  [실패] {tk} @ {d} — {type(exc).__name__}: {str(exc)[:80]}")

    # ── 채점 & 집계 ──────────────────────────────────────────────────────
    rows = []
    with open(VIRT_FILE, encoding='utf-8') as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    print(f"\n채점 대상 가상 판정: {len(rows)}건")

    graded = []
    for r in rows:
        pdf = price_cache.get(r['ticker'])
        if pdf is None:
            try:
                pdf, _ = eng.generate_synthetic_bitemporal_data(
                    symbol=r['ticker'], start_date='2020-01-01', end_date=None)
                price_cache[r['ticker']] = pdf
            except Exception:
                continue
        g = plog.grade_prediction(r, pdf)
        if g:
            graded.append({'row': r, 'grade': g})

    decided = [g for g in graded if g['grade']['outcome'] in ('TARGET', 'STOP')]
    print(f"판정 완료(목표 또는 손절 도달): {len(decided)}건 · "
          f"미결 {len(graded) - len(decided)}건")

    # 점수대 캘리브레이션 — 세분화 (60·65·70·75·80대의 실제 성공률 검증 요구)
    BANDS = [(0, 39), (40, 49), (50, 54), (55, 59), (60, 64), (65, 69), (70, 100)]
    bands_out = []
    print("\n" + "=" * 74)
    print("점수대별 실제 적중률 (가상 백테스트 · 목표가 선도달 기준)")
    print("=" * 74)
    for lo, hi in BANDS:
        sub = [g for g in decided if lo <= g['row']['score'] <= hi]
        hit = sum(1 for g in sub if g['grade']['outcome'] == 'TARGET')
        rets = [g['grade']['return_pct'] for g in graded
                if lo <= g['row']['score'] <= hi]
        n = len(sub)
        hr = hit / n * 100.0 if n else None
        wl = wilson_low(hit, n) if n else None
        avg = float(np.mean(rets)) if rets else None
        bands_out.append({'lo': lo, 'hi': hi, 'n': n, 'hit': hit,
                          'hit_rate': hr, 'wilson_low': wl, 'avg_return': avg})
        print(f"  {lo:>3}~{hi:<3}점: n={n:<3} 적중 {hit:<3} "
              f"적중률 {hr if hr is None else round(hr, 1)}% "
              f"(Wilson 하한 {wl if wl is None else round(wl, 1)}%) "
              f"평균수익 {avg if avg is None else round(avg, 2)}%")

    # 조건 리프트
    def lift(cond_fn, label):
        yes = [g for g in decided if cond_fn(g['row'])]
        no = [g for g in decided if not cond_fn(g['row'])]
        hy = sum(1 for g in yes if g['grade']['outcome'] == 'TARGET')
        hn = sum(1 for g in no if g['grade']['outcome'] == 'TARGET')
        ry = hy / len(yes) * 100 if yes else None
        rn = hn / len(no) * 100 if no else None
        print(f"  {label:<28} 충족 {ry if ry is None else round(ry,1)}% (n={len(yes)}) "
              f"vs 미충족 {rn if rn is None else round(rn,1)}% (n={len(no)})")
        return {'label': label, 'yes_n': len(yes), 'yes_rate': ry,
                'no_n': len(no), 'no_rate': rn}

    print("\n" + "=" * 74)
    print("조건별 리프트 (충족 vs 미충족 적중률)")
    print("=" * 74)
    lifts = [
        lift(lambda r: r.get('m10_above'), "월봉 10선 위"),
        lift(lambda r: r.get('demark_state') in ('COMPLETE', 'SETUP_DONE'),
             "DeMARK 매수 신호"),
        lift(lambda r: (r.get('net_expected') or -1) > 0, "순기대수익 양수"),
        lift(lambda r: '초과' not in str(r.get('entry_zone') or ''), "적정가 이하 진입"),
    ]

    # ── 진입 후보 KPI — 앱이 실제로 '진입해도 된다'고 보는 조건의 성적 ────────
    # (적정가 이하 진입 & 순기대수익 양수 — 이 둘은 앱의 매수 거부권 조건과 동일)
    def _is_entry(r):
        return ('초과' not in str(r.get('entry_zone') or '')
                and (r.get('net_expected') or -1) > 0)

    print("\n" + "=" * 74)
    print("진입 후보 KPI (적정가 이하 & 순기대수익 양수) — 코호트별")
    print("=" * 74)
    entry_out = {}
    for cohort in ('main', 'holdout', 'all'):
        sub = [g for g in decided
               if _is_entry(g['row'])
               and (cohort == 'all' or g['row'].get('cohort', 'main') == cohort)]
        hitc = sum(1 for g in sub if g['grade']['outcome'] == 'TARGET')
        rets = [g['grade']['return_pct'] for g in sub]
        hr = hitc / len(sub) * 100 if sub else None
        wl = wilson_low(hitc, len(sub)) if sub else None
        avg = float(np.mean(rets)) if rets else None
        entry_out[cohort] = {'n': len(sub), 'hit': hitc, 'hit_rate': hr,
                             'wilson_low': wl, 'avg_return': avg}
        print(f"  {cohort:<8} n={len(sub):<3} 적중률 "
              f"{hr if hr is None else round(hr, 1)}% "
              f"(Wilson 하한 {wl if wl is None else round(wl, 1)}%) "
              f"평균수익 {avg if avg is None else round(avg, 2)}%")

    # ── 유형·시장·국면별 성과 + PF·비용차감·MAE ─────────────────────────────
    def perf_block(sub, label):
        if not sub:
            return {'label': label, 'n': 0}
        hitb = sum(1 for g in sub if g['grade']['outcome'] == 'TARGET')
        rets = [g['grade']['return_pct'] for g in sub]
        wins = sum(r for r in rets if r > 0)
        losses = -sum(r for r in rets if r < 0)
        maes = [g['grade'].get('mae_pct') for g in sub if g['grade'].get('mae_pct') is not None]
        out = {
            'label': label, 'n': len(sub), 'hit': hitb,
            'hit_rate': round(hitb / len(sub) * 100, 1),
            'wilson_low': round(wilson_low(hitb, len(sub)) or 0, 1),
            'avg_return': round(float(np.mean(rets)), 2),
            'median_return': round(float(np.median(rets)), 2),
            'profit_factor': round(wins / losses, 2) if losses > 0 else None,
            'avg_mae': round(float(np.mean(maes)), 2) if maes else None,
            # 왕복 거래비용 차감 (수수료+세금+슬리피지 총합의 보수적 추정 0.55%)
            'avg_return_after_cost': round(float(np.mean(rets)) - 0.55, 2),
        }
        return out

    def show_block(b):
        if b['n'] == 0:
            print(f"  {b['label']:<26} n=0")
            return
        print(f"  {b['label']:<26} n={b['n']:<4} 적중 {b['hit_rate']:5.1f}% "
              f"(W하한 {b['wilson_low']:4.1f}%) 평균 {b['avg_return']:+5.2f}% "
              f"중앙값 {b['median_return']:+5.2f}% PF {b['profit_factor']} "
              f"MAE {b['avg_mae']}% 비용후 {b['avg_return_after_cost']:+5.2f}%")

    breakdowns = {}
    print("\n" + "=" * 74)
    print("자산 유형별 성과")
    print("=" * 74)
    breakdowns['by_asset_type'] = []
    for at in ('STOCK', 'ETF', 'ETF_LEV', 'ETF_INV'):
        b = perf_block([g for g in decided if g['row'].get('asset_type') == at], at)
        breakdowns['by_asset_type'].append(b)
        show_block(b)

    print("\n" + "=" * 74)
    print("시장·국면별 성과")
    print("=" * 74)
    breakdowns['by_market'] = []
    for mk in ('KOSPI', 'KOSDAQ'):
        b = perf_block([g for g in decided if g['row'].get('market') == mk], mk)
        breakdowns['by_market'].append(b)
        show_block(b)
    breakdowns['by_regime'] = []
    for rg in ('BULL', 'SIDEWAYS', 'BEAR'):
        b = perf_block([g for g in decided if g['row'].get('regime') == rg], rg)
        breakdowns['by_regime'].append(b)
        show_block(b)

    # ── 시간 분할 성과 — 학습/검증/블라인드 (개선은 train+valid 통계만 사용) ──
    print("\n" + "=" * 74)
    print(f"시간 분할 성과 (학습 <{SPLIT_VALID_FROM} ≤ 검증 <{SPLIT_BLIND_FROM} ≤ 블라인드)")
    print("=" * 74)
    splits_out = {}
    for sp in ('train', 'valid', 'blind'):
        b = perf_block([g for g in decided if split_of(g['row']['date']) == sp], sp)
        splits_out[sp] = b
        show_block(b)
    # 매수권(60점+) 분할 성과 — 80% 목표의 정직한 잣대
    print("  --- 매수권(60점+) 만 ---")
    splits_out['buy_zone'] = {}
    for sp in ('train', 'valid', 'blind'):
        b = perf_block([g for g in decided if split_of(g['row']['date']) == sp
                        and g['row']['score'] >= 60], f"60+ {sp}")
        splits_out['buy_zone'][sp] = b
        show_block(b)

    # ── 실패 원인 분류 — 빈도와 손실 규모, 큰 손실부터 ─────────────────────
    def classify_failure(g):
        r, gr = g['row'], g['grade']
        if gr['outcome'] == 'OPEN':
            return '기간 내 미도달'
        if gr['outcome'] == 'TARGET':
            return None
        tp_d = ((r.get('target') or 0) / max(r.get('price') or 1, 1) - 1) * 100
        mfe = gr.get('mfe_pct') or 0
        at = r.get('asset_type', 'STOCK')
        if at == 'ETF_INV':
            return '인버스 방향 해석'
        if at == 'ETF_LEV':
            return '레버리지 변동성'
        if (r.get('eff_sample') or 99) < 5:
            return '자기유사 표본 부족'
        if (r.get('rsi') or 0) >= 70 and (r.get('bb_pos') or 0) > 85:
            return '과열 추격'
        if r.get('regime') == 'BEAR':
            return '시장 국면 역풍'
        if mfe >= 0.5 * tp_d and tp_d > 0:
            return '노이즈 손절(목표 절반까지 갔다 반락)'
        if not r.get('m10_above'):
            return '추세 역행(월10선 아래)'
        return '방향 오판'

    from collections import defaultdict
    fail_stats = defaultdict(lambda: {'n': 0, 'loss': 0.0})
    for g in decided:
        cls = classify_failure(g)
        if cls:
            fail_stats[cls]['n'] += 1
            fail_stats[cls]['loss'] += min(0.0, g['grade']['return_pct'])
    print("\n" + "=" * 74)
    print("실패 원인 분류 — 손실 규모 순 (다음 개선 우선순위)")
    print("=" * 74)
    fail_out = []
    for cls, st in sorted(fail_stats.items(), key=lambda kv: kv[1]['loss']):
        print(f"  {cls:<32} {st['n']:>4}건 · 누적손실 {st['loss']:+9.1f}%p")
        fail_out.append({'class': cls, 'n': st['n'], 'total_loss': round(st['loss'], 1)})

    # ── 신호 빈도 — 적중률만 높이려 신호를 말려 죽이지 않는지 감시 ─────────
    n_buy = sum(1 for g in graded if g['row']['score'] >= 60)
    print("\n" + "=" * 74)
    print("신호 빈도 (매수권 = 점수 60+)")
    print("=" * 74)
    print(f"  전체 분석 {len(graded)}건 · 매수권 {n_buy}건 · 발생률 {n_buy/len(graded)*100:.1f}%")
    freq_out = {'total': len(graded), 'buy_zone': n_buy,
                'rate_pct': round(n_buy / len(graded) * 100, 1)}

    # ── 고신뢰 신호 계층 (90% 검증 목표의 잣대) — 점수 65+ ────────────────────
    hc = perf_block([g for g in decided if g['row']['score'] >= 65], "고신뢰(65+)")
    print("\n" + "=" * 74)
    print("고신뢰 신호 계층 (점수 65+) — 90% 는 이 계층의 장기 표본외 검증 목표")
    print("=" * 74)
    show_block(hc)
    if hc['n'] < 30:
        print(f"  ⚠️ 표본 {hc['n']}건 — 90% 도달 여부를 논할 최소 표본(30건+)에 미달. "
              f"과장 없이 '표본 부족' 으로 보고한다.")

    # ── 케이스 스터디 원장 — 17개 항목을 채운 채점 결과를 그대로 남긴다 ──────
    graded_file = os.path.join(PROJ, ".portfolio", "virtual_graded.jsonl")
    with open(graded_file, 'w', encoding='utf-8') as gf:
        for g in graded:
            rec = dict(g['row'])
            rec.update({
                'outcome': g['grade']['outcome'],
                'touched_bar': g['grade'].get('touched_bar'),
                'return_pct': round(g['grade']['return_pct'], 2),
                'close_return_pct': round(g['grade']['close_return_pct'], 2),
                'mfe_pct': round(g['grade'].get('mfe_pct') or 0, 2),
                'mae_pct': round(g['grade'].get('mae_pct') or 0, 2),
                'success': g['grade']['outcome'] == 'TARGET',
                'split': split_of(g['row']['date']),
                'failure_class': classify_failure(g),
            })
            gf.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"\n케이스 원장 저장: {graded_file} ({len(graded)}건)")

    calib = {
        'generated_from': f"{len(rows)}건 가상 판정 · 판정 완료 {len(decided)}건",
        'bands': bands_out,
        'lifts': lifts,
        'entry_candidates': entry_out,
        'breakdowns': breakdowns,
        'splits': splits_out,
        'failure_classes': fail_out,
        'signal_frequency': freq_out,
        'high_confidence': hc,
        'total_cases': len(graded),
        'rulebook_version': "v2026.08.02",
        'note': ("실제 판정 엔진을 과거 기준일 리플레이로 돌려 채점한 결과다. "
                 "리플레이는 그 날 알 수 있었던 것만 쓴다(시장 컨텍스트·상대모멘텀·"
                 "실시간 시세 차단). 재무·배당 게시값은 이력이 없어 현재 게시값이 "
                 "쓰인다는 한계가 있다."),
    }
    with open(CALIB_FILE, 'w', encoding='utf-8') as f:
        json.dump(calib, f, ensure_ascii=False, indent=1)
    print(f"\n캘리브레이션 저장: {CALIB_FILE}")


if __name__ == "__main__":
    lim = 200
    if "--limit" in sys.argv:
        lim = int(sys.argv[sys.argv.index("--limit") + 1])
    main(lim)
