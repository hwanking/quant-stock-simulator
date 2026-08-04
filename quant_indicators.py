import pandas as pd
import numpy as np
import json
import os
import re


def load_rulebook(path=None):
    """
    analysis_rulebook_ko.txt 를 실제로 파싱한다.
    구버전에서는 이 파일이 존재하기만 하고 코드가 읽지 않아, 규칙집 가중치와
    실제 산식이 서로 달랐다(예: 펀더멘털 0.25 vs 코드 0.30).
    반환: {"SECTION": {"key": value}} — 숫자는 float, 그 외는 문자열.
    """
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "analysis_rulebook_ko.txt")
    book, section = {}, None
    try:
        with open(path, encoding='utf-8') as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith('#'):
                    continue
                m = re.match(r'^\[([A-Z0-9_]+)\]$', line)
                if m:
                    section = m.group(1)
                    book[section] = {}
                    continue
                if section and '=' in line:
                    k, v = (p.strip() for p in line.split('=', 1))
                    v = v.strip('"')
                    try:
                        book[section][k] = float(v)
                    except ValueError:
                        book[section][k] = v
    except Exception as exc:
        return {"_error": str(exc)}
    return book


RULEBOOK = load_rulebook()


def fmt_or(v, na="미산출", digits=2):
    """수치를 문자열로. None 이면 '미산출' (0 으로 위장하지 않는다)."""
    if v is None:
        return na
    try:
        return f"{float(v):,.{digits}f}"
    except (TypeError, ValueError):
        return str(v)


def rb(section, key, default):
    """규칙집 값을 읽되, 없으면 코드 기본값으로 안전하게 되돌아간다."""
    return RULEBOOK.get(section, {}).get(key, default)


class QuantSnapshot(dict):
    """
    [명세 §17] 모든 화면이 공유하는 단일 최종 결과 객체.

    dict 를 상속해 기존 snap['tech_df'] 접근을 그대로 유지하면서,
    명세가 요구하는 이름 있는 뷰를 속성으로 제공한다.
    화면 컴포넌트는 이 객체에서 값을 '읽기만' 해야 하며 다시 계산하면 안 된다.
    """

    __getattr__ = dict.get

    # ---- 이름 있는 뷰 -------------------------------------------------
    @property
    def recommendation_summary(self):
        """상단 TOP3 표가 쓰는 요약 — 상세화면과 동일 객체에서 파생된다."""
        fs, m = self['four_scores'], self['meta']
        return {
            'symbol': self['symbol'], 'run_id': m['run_id'],
            'analysis_date': m['analysis_date'], 'price_asof': m['price_asof'],
            'price': float(self['tech_df']['adj_close'].iloc[-1]),
            'fair_value': fs.get('displayed_fair_value'),
            'upside_pct': fs.get('upside_pct'),
            'final_action_score': fs.get('final_action_score'),
            'final_action_title': fs.get('final_action_title'),
            'reward_risk_ratio': fs.get('reward_risk_ratio'),
            'net_expected_return': fs.get('net_expected_return'),
            'opportunity_score': fs.get('opportunity_score'),
            'analysis_confidence': fs.get('analysis_confidence'),
            'strategy_type': fs.get('strategy_type'),
            'entry_zone': fs.get('entry_zone'),
            'status': self.get('status'),
            'eligible_for_top3': self.get('eligible_for_top3'),
            'block_reasons': fs.get('top3_block_reasons', []),
        }

    @property
    def detailed_analysis(self):
        return {'tech_df': self['tech_df'], 'price_pos': self['price_pos'],
                'demark': self['four_scores'].get('demark_res'),
                'scores': self['four_scores'], 'meta': self['meta']}

    @property
    def valuation_result(self):
        return self['val_eval']

    @property
    def multi_horizon_forecast(self):
        return self['sim_res']

    @property
    def final_decision(self):
        fs = self['four_scores']
        return {
            'status': self.get('status'),
            'title': fs.get('final_action_title'),
            'score': fs.get('final_action_score'),
            'explain': fs.get('final_action_explain'),
            'cap_reasons': fs.get('cap_reasons', []),
            'gate_checks': fs.get('gate_checks', []),
            'block_reasons': fs.get('top3_block_reasons', []),
            'contradictions': self.get('contradictions', []),
            'eligible_for_top3': self.get('eligible_for_top3'),
        }

    @property
    def is_stale(self):
        import time
        age = time.time() - self['meta'].get('generated_ts', 0)
        return age > QuantIndicatorsEngine.SNAPSHOT_TTL_SEC

    def cache_key(self):
        m = self['meta']
        return (m['symbol'], m['analysis_date'], round(m['rho_cutoff'], 4),
                m['calc_version'], m['model_version'], m['rulebook_version'])


class QuantIndicatorsEngine:
    """
    AntiGravity AI Quant Engine (v20) - 3대 점수 완전 분리 (종목매력도/매매적합도/분석신뢰도), 가격위치 디커플링 및 최종 매수/매도/관망 2D 판정 엔진.
    """

    # ── [명세 §14·§15] 전략 검증 상태와 추천 임계값 ───────────────────────────
    # Purged Walk-Forward 표본외 검증이 구현되어 있다 (run_blind_oos_backtest).
    # 종목별로 실제 수행하며, 데이터가 모자라 수행 못 한 종목은 아래 상한이 적용된다.
    BLIND_TEST_IMPLEMENTED = True
    # 표본외 검증을 수행하지 못한 경우의 최종 행동점수 상한
    STRATEGY_QUALITY_CAP_WITHOUT_BLIND_TEST = 65

    # ── 아래 값들은 analysis_rulebook_ko.txt 가 단일 출처다 ──────────────────
    TOP3_MIN_ACTION_SCORE = rb('RULES_TOP3_GATES', 'min_action_score', 68)
    MIN_AVG_TURNOVER_KRW = rb('RULES_LIQUIDITY', 'min_avg_turnover_krw', 2_000_000_000)

    # 경로 확률(목표가·손절가 선도달) 판정 임계값 — 단일 정의 지점.
    # 구버전은 run_self_similarity_backtest(+8/−6), compute_historical_pattern_prediction(+5/−3),
    # UI 표기(+10/−7)가 각각 달라 화면의 라벨과 실제 계산 기준이 어긋나 있었다.
    TP_THRESHOLD_PCT = rb('RULES_PATH_THRESHOLDS', 'take_profit_pct', 8.0)
    SL_THRESHOLD_PCT = rb('RULES_PATH_THRESHOLDS', 'stop_loss_pct', 6.0)

    # 계산식·모델·스냅샷 캐시 버전. 산식을 바꾸면 반드시 올려야 캐시가 무효화된다.
    CALC_VERSION = "calc-2026.07.31.4"
    MODEL_VERSION = "model-selfsim-dtw-oos-1"
    SNAPSHOT_TTL_SEC = 15 * 60      # 스냅샷 유효시간 15분

    W_TOP = RULEBOOK.get('RULES_TOP_LEVEL_WEIGHTS', {})
    W_QUALITY = RULEBOOK.get('RULES_STOCK_QUALITY_WEIGHTS', {})
    W_TIMING = RULEBOOK.get('RULES_TRADING_TIMING_WEIGHTS', {})
    W_RISK = RULEBOOK.get('RULES_RISK_SAFETY_WEIGHTS', {})
    W_FINAL = RULEBOOK.get('RULES_FINAL_ACTION_WEIGHTS', {})
    W_OPP = RULEBOOK.get('RULES_OPPORTUNITY_WEIGHTS', {})
    W_EXEC = RULEBOOK.get('RULES_EXECUTION_WEIGHTS', {})
    W_CONF = RULEBOOK.get('RULES_ANALYSIS_CONFIDENCE_WEIGHTS', {})
    #: 시장 국면·글로벌·뉴스 점수화 규칙 (단일 출처: analysis_rulebook_ko.txt)
    W_MARKET_CTX = RULEBOOK.get('RULES_MARKET_CONTEXT', {})
    GATES = RULEBOOK.get('RULES_TOP3_GATES', {})
    FV_CONF = RULEBOOK.get('RULES_FAIR_VALUE_CONFIDENCE', {})
    RULEBOOK_VERSION = rb('RULES_GENERAL', 'version', '미상')

    # 실제로 '매수 의사'를 담은 판정문만 열거한다.
    # "신규 매수 보류"에도 '매수' 글자가 들어 있어 부분문자열 검사('매수' in title)는
    # 매수 보류를 매수 추천으로 오인한다.
    BUY_INTENT_TITLES = ("적극적 분할매수 검토", "분할매수 검토", "제한적 진입")

    def __init__(self):
        pass

    def compute_technical_indicators(self, prices_df):
        df = prices_df.copy()
        
        # Robust OHLC resolution (Handles mixed 'open' and 'open_raw' with NaNs)
        if 'open' not in df.columns or df['open'].isna().sum() > 0:
            if 'open_raw' in df.columns: 
                df['open'] = df.get('open', pd.Series(index=df.index)).fillna(df['open_raw'])
            df['open'] = df['open'].fillna(df['adj_close'])
            
        if 'high' not in df.columns or df['high'].isna().sum() > 0:
            if 'high_raw' in df.columns:
                df['high'] = df.get('high', pd.Series(index=df.index)).fillna(df['high_raw'])
            df['high'] = df['high'].fillna(df['adj_close'] * 1.01)
            
        if 'low' not in df.columns or df['low'].isna().sum() > 0:
            if 'low_raw' in df.columns:
                df['low'] = df.get('low', pd.Series(index=df.index)).fillna(df['low_raw'])
            df['low'] = df['low'].fillna(df['adj_close'] * 0.99)
            
        if 'volume' not in df.columns or df['volume'].isna().sum() > 0:
            if 'volume_raw' in df.columns:
                df['volume'] = df.get('volume', pd.Series(index=df.index)).fillna(df['volume_raw'])
            df['volume'] = df['volume'].fillna(1000000.0)
        if 'high' not in df.columns:
            df['high'] = df['adj_close'] * 1.005
        if 'low' not in df.columns:
            df['low'] = df['adj_close'] * 0.995
        if 'open' not in df.columns:
            df['open'] = df['adj_close']
        if 'volume' not in df.columns:
            df['volume'] = 1000000.0
        df['sma_5'] = df['adj_close'].rolling(5).mean()
        df['sma_20'] = df['adj_close'].rolling(20).mean()
        df['sma_60'] = df['adj_close'].rolling(60).mean()
        df['sma_120'] = df['adj_close'].rolling(120).mean()
        
        # RSI 14
        delta = df['adj_close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / (loss + 1e-8)
        df['rsi_14'] = 100 - (100 / (1 + rs))
        df['rsi_14'] = df['rsi_14'].fillna(50.0)
        
        # 20일 변동성
        df['vol_20'] = df['adj_close'].pct_change().rolling(20).std()
        df['vol_20'] = df['vol_20'].fillna(0.02)
        
        # 20일선 기울기
        df['sma_20_slope'] = df['sma_20'].diff(3) / (df['sma_20'].shift(3) + 1e-8)
        df['sma_20_slope'] = df['sma_20_slope'].fillna(0.0)
        
        # 거래량 20일 평균 및 거래량 배수
        df['vol_20_avg'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / (df['vol_20_avg'] + 1e-8)
        df['volume_ratio'] = df['volume_ratio'].fillna(1.0)
        # Bollinger Bands (20, 2)
        df['bb_mid'] = df['sma_20']
        df['bb_std'] = df['adj_close'].rolling(20).std()
        df['bb_upper'] = df['bb_mid'] + 2 * df['bb_std']
        df['bb_lower'] = df['bb_mid'] - 2 * df['bb_std']
        
        # Williams %R 14
        high_14 = df['high'].rolling(14).max()
        low_14 = df['low'].rolling(14).min()
        # 분모가 0이 되는 것을 방지하기 위해 + 1e-8
        df['williams_r'] = (high_14 - df['adj_close']) / (high_14 - low_14 + 1e-8) * -100.0
        df['williams_r'] = df['williams_r'].fillna(-50.0)
        
        # ADX (14) 및 DMI
        # True Range
        tr1 = df['high'] - df['low']
        tr2 = (df['high'] - df['adj_close'].shift(1)).abs()
        tr3 = (df['low'] - df['adj_close'].shift(1)).abs()
        df['tr'] = pd.DataFrame({'tr1': tr1, 'tr2': tr2, 'tr3': tr3}).max(axis=1)
        
        up_move = df['high'] - df['high'].shift(1)
        down_move = df['low'].shift(1) - df['low']
        
        df['plus_dm'] = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        df['minus_dm'] = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
        
        tr_14 = df['tr'].rolling(14).sum()
        plus_di_14 = 100 * (df['plus_dm'].rolling(14).sum() / (tr_14 + 1e-8))
        minus_di_14 = 100 * (df['minus_dm'].rolling(14).sum() / (tr_14 + 1e-8))
        
        df['plus_di'] = plus_di_14.fillna(0.0)
        df['minus_di'] = minus_di_14.fillna(0.0)
        
        dx = 100 * (abs(df['plus_di'] - df['minus_di']) / (df['plus_di'] + df['minus_di'] + 1e-8))
        df['adx'] = dx.rolling(14).mean().fillna(20.0)

                # 월봉 10이평선 (일봉 200일 이동평균 프록시) & 월봉 추세 지표 연산
        df['ma_200'] = df['adj_close'].rolling(window=200, min_periods=20).mean()
        df['ma_200'] = df['ma_200'].bfill().fillna(df['adj_close'])
        
        n_df = len(df)
        curr_p = float(df['adj_close'].iloc[-1])
        ma200_curr = float(df['ma_200'].iloc[-1])
        ma200_prev20 = float(df['ma_200'].iloc[-20]) if n_df >= 20 else ma200_curr
        
        m10_slope = ((ma200_curr - ma200_prev20) / (ma200_prev20 + 1e-8)) * 100.0
        m10_disparity = ((curr_p / (ma200_curr + 1e-8)) - 1.0) * 100.0
        m10_status = "위" if curr_p >= ma200_curr else "아래"
        
        # 최근 3개월 중 월봉 10선 유지 개월 수 연산
        m10_maintained_cnt = 0
        for offset in [0, 20, 40]:
            if n_df > offset:
                p_past = float(df['adj_close'].iloc[-(offset+1)])
                ma_past = float(df['ma_200'].iloc[-(offset+1)])
                if p_past >= ma_past:
                    m10_maintained_cnt += 1
                    
        # 월봉 추세 정량 점수 (0~100점)
        m10_score = 0
        if m10_status == "위": m10_score += 35
        if m10_slope > 0: m10_score += 20
        if m10_maintained_cnt >= 2: m10_score += 15
        if curr_p > float(df['sma_60'].iloc[-1]) > float(df['sma_120'].iloc[-1]): m10_score += 10
        if m10_disparity <= 25.0 and ((curr_p / (float(df['sma_20'].iloc[-1]) + 1e-8) - 1.0)*100 <= 10.0): m10_score += 10
        if float(df['volume'].iloc[-1]) * curr_p >= 1_000_000_000: m10_score += 10
        
        df['m10_score'] = m10_score
        df['m10_slope'] = m10_slope
        df['m10_disparity'] = m10_disparity
        df['m10_status'] = m10_status
        df['m10_maintained_cnt'] = m10_maintained_cnt

        df['sma_5'] = df['sma_5'].bfill()
        df['sma_20'] = df['sma_20'].bfill()
        df['sma_60'] = df['sma_60'].bfill()
        df['sma_120'] = df['sma_120'].bfill()
        
        return df

    def classify_market_regime(self, kospi_price=5593.56, kospi_sma20=5650.0, kospi_sma60=5700.0):
        """ 
        [Section 4 & 1-1 Spec] KOSPI/KOSDAQ 데이터 미수신 시 판정 보류 처리 
        Note: kospi_price, kospi_sma20, and kospi_sma60 should be dynamically provided by the caller.
        """
        try:
            if kospi_price is None or kospi_price == "N/A" or float(kospi_price) <= 0:
                return "DECISION_PENDING", "판정 보류 (KOSPI·KOSDAQ 최신 데이터 미수신)", {"F": 0.25, "V": 0.20, "T": 0.15, "S": 0.15, "R": 0.15, "M": 0.10}
            kp = float(kospi_price)
            ks20 = float(kospi_sma20) if kospi_sma20 else kp
            ks60 = float(kospi_sma60) if kospi_sma60 else kp
        except Exception:
            return "DECISION_PENDING", "판정 보류 (KOSPI·KOSDAQ 최신 데이터 미수신)", {"F": 0.25, "V": 0.20, "T": 0.15, "S": 0.15, "R": 0.15, "M": 0.10}

        # 라벨에 판정 근거(지수 vs 이동평균)를 함께 적는다.
        # 근거 없이 '급락장·고변동성'만 표시하면, 당일 지수가 급등한 날에는
        # 상단 지수 카드(+17%)와 모순처럼 보인다. 이 판정은 당일 등락이 아니라
        # 지수의 20·60일 이동평균 대비 위치로 내리는 것이다.
        basis = f"(KOSPI {kp:,.0f} vs 20일선 {ks20:,.0f}·60일선 {ks60:,.0f} 기준)"
        if kp >= ks20 and ks20 >= ks60:
            regime_code = "BULL_STRONG"
            regime_label = f"강한 상승장·과열장 {basis}"
            weights = {"F": 0.20, "V": 0.20, "T": 0.20, "S": 0.15, "R": 0.10, "M": 0.15}
        elif kp >= ks20:
            regime_code = "BULL_MILD"
            regime_label = f"완만한 상승장 {basis}"
            weights = {"F": 0.25, "V": 0.15, "T": 0.20, "S": 0.15, "R": 0.10, "M": 0.15}
        elif kp < ks20 and kp < ks60:
            regime_code = "BEAR_PANIC"
            regime_label = f"하락 국면 — 지수가 20·60일선 아래 {basis}"
            weights = {"F": 0.15, "V": 0.10, "T": 0.25, "S": 0.25, "R": 0.15, "M": 0.10}
        else:
            regime_code = "SIDEWAYS"
            regime_label = f"횡보장 {basis}"
            weights = {"F": 0.25, "V": 0.25, "T": 0.10, "S": 0.15, "R": 0.15, "M": 0.10}

        return regime_code, regime_label, weights

    def compute_dtw_distance(self, seq_a, seq_b):
        """ Dynamic Time Warping (DTW) 거리 """
        n, m = len(seq_a), len(seq_b)
        dtw_matrix = np.zeros((n + 1, m + 1))
        dtw_matrix[0, 1:] = np.inf
        dtw_matrix[1:, 0] = np.inf
        for i in range(1, n + 1):
            for j in range(1, m + 1):
                cost = abs(seq_a[i - 1] - seq_b[j - 1])
                dtw_matrix[i, j] = cost + min(dtw_matrix[i - 1, j], dtw_matrix[i, j - 1], dtw_matrix[i - 1, j - 1])
        dist = dtw_matrix[n, m] / max(n, m)
        return round(float(max(0.0, 1.0 - (dist / 3.0))), 3)

    def bayesian_beta_binomial_calibration(self, win_count, match_cnt, prior_alpha=5.5, prior_beta=4.5):
        """ 베이지안 Beta-Binomial 사후 확률 보정 """
        post_alpha = prior_alpha + win_count
        post_beta = prior_beta + (match_cnt - win_count)
        post_mean = post_alpha / (post_alpha + post_beta)
        return round(float(post_mean * 100), 1)

    # [명세 §11] 유효표본 수 통제 구간 — 규칙집 [RULES_SAMPLE_TIERS] 가 단일 출처
    _ST = RULEBOOK.get('RULES_SAMPLE_TIERS', {})
    SAMPLE_TIERS = (
        (int(_ST.get('insufficient_below', 5)),      'INSUFFICIENT',     '미산출 (유효표본 5건 미만)'),
        (int(_ST.get('observation_only_below', 10)), 'OBSERVATION_ONLY', '과거 관찰값만 표시 (확률 미산출)'),
        (int(_ST.get('low_confidence_below', 20)),   'LOW_CONFIDENCE',   '낮은 신뢰도'),
        (int(_ST.get('limited_below', 30)),          'LIMITED',          '제한적 확률'),
    )

    def classify_sample_tier(self, n):
        """유효표본 수 → (등급코드, 표시문구). 확률 노출 허용 여부의 단일 판단 기준."""
        for threshold, code, label in self.SAMPLE_TIERS:
            if n < threshold:
                return code, label
        return 'FORECAST_AVAILABLE', '정상 예측 가능'

    def probabilities_allowed(self, tier_code):
        """§11: 10건 미만(미산출·관찰전용)에서는 어떤 확률도 표시하지 않는다."""
        return tier_code not in ('INSUFFICIENT', 'OBSERVATION_ONLY')

    def run_self_similarity_backtest(self, df, target_date=None, pattern_len=20, rho_cutoff=0.80, symbol=None, **kwargs):
        """
        [국내 전 종목 공통 다중기간 자기유사 예측 엔진]
        5, 10, 20, 40, 60, 120 영업일 다중기간 경로 독립 백테스트 및 최적 보유기간/일치도 산출
        """
        prices = df['adj_close'].values
        rsi_vals = df['rsi_14'].values if 'rsi_14' in df.columns else np.full(len(prices), 50.0)
        vol_vals = df['vol_20'].values if 'vol_20' in df.columns else np.full(len(prices), 0.02)
        
        if len(prices) < 40:
            return self._empty_blind_result(prices[-1], "데이터 수량 부족")

        FORECAST_HORIZONS = [5, 10, 20, 40, 60, 120]
        horizons_data = {}
        
        # 종목 전략 유형 정량 확률 분류 (복수 전략 허용)
        curr_p = float(prices[-1])
        sma20 = float(df['sma_20'].iloc[-1]) if 'sma_20' in df.columns else curr_p
        sma60 = float(df['sma_60'].iloc[-1]) if 'sma_60' in df.columns else curr_p
        sma120 = float(df['sma_120'].iloc[-1]) if 'sma_120' in df.columns else curr_p
        
        m10_stat = str(df['m10_status'].iloc[-1]) if 'm10_status' in df.columns else "위"
        m10_slope = float(df['m10_slope'].iloc[-1]) if 'm10_slope' in df.columns else 0.0
        
        strat_probs = {
            'mean_reversion': 15,
            'demark_reversal': 15,
            'pullback': 20,
            'trend_breakout': 15,
            'earnings_momentum': 15,
            'monthly_trend': 20
        }
        
        if curr_p > sma60 and curr_p <= sma20 * 1.025:
            strat_probs['pullback'] += 35
            strat_probs['monthly_trend'] += 15
        elif m10_stat == "위" and m10_slope > 0:
            strat_probs['monthly_trend'] += 40
            strat_probs['trend_breakout'] += 20
        elif curr_p < sma60:
            strat_probs['mean_reversion'] += 30
            strat_probs['demark_reversal'] += 25
            
        total_p = sum(strat_probs.values())
        for k in strat_probs: strat_probs[k] = round((strat_probs[k] / total_p) * 100, 1)

        def _insufficient_horizon(H, n, reason):
            """표본 미달 지평 — 확률·기대값을 일절 산출하지 않는다 (None)."""
            return {
                'h': H, 'match_count': int(n), 'win_rate': None, 'mean_perf': None,
                'mdd': None, 'tp_first_prob': None, 'sl_first_prob': None,
                'status': 'INSUFFICIENT', 'tier_label': reason,
                'trajectory': np.full(H, curr_p)
            }

        # 각 Horizon 독립 계산
        for H in FORECAST_HORIZONS:
            if len(prices) < H * 2 + 10:
                horizons_data[H] = _insufficient_horizon(H, 0, "미산출 (가격 이력 부족)")
                continue

            t_pattern = prices[-H:]
            t_norm = (t_pattern - np.mean(t_pattern)) / (np.std(t_pattern) + 1e-8)

            # 사용자가 지정한 rho_cutoff를 그대로 적용한다.
            # (구버전은 -0.12 완화 후 표본이 부족하면 0.55로 재스캔하여 슬라이더를 무력화시켰음)
            # Pearson 상관 + DTW 유사도 결합 (UI가 광고하던 DTW를 실제로 사용한다).
            # DTW는 O(H²)이라 Pearson 1차 통과분에만 적용해 비용을 억제한다.
            raw_matches = []
            for i in range(len(prices) - H * 2):
                sub_pat = prices[i:i+H]
                sub_norm = (sub_pat - np.mean(sub_pat)) / (np.std(sub_pat) + 1e-8)
                rho = np.corrcoef(t_norm, sub_norm)[0, 1]
                if np.isnan(rho) or rho < rho_cutoff:
                    continue
                if H <= 40:
                    dtw_sim = self.compute_dtw_distance(t_norm, sub_norm)
                    # 결합 가중치는 규칙집이 단일 출처다 (코드 리터럴 금지)
                    combined = (rho * rb('RULES_SIMILARITY', 'pearson_weight', 0.7)
                                + dtw_sim * rb('RULES_SIMILARITY', 'dtw_weight', 0.3))
                    if combined < rho_cutoff:
                        continue
                raw_matches.append((i, rho))

            # 독립성 확보를 위해 최소 H영업일 간격 이벤트 필터링 (minimum_event_gap = H)
            dedup_matches = []
            last_idx = -9999
            for idx, r_val in raw_matches:
                if idx - last_idx >= H:
                    dedup_matches.append(idx)
                    last_idx = idx

            match_cnt = len(dedup_matches)
            tier_code, tier_label = self.classify_sample_tier(match_cnt)

            # [명세 §11] 유효표본 5건 미만은 미산출. 표본 보충·복제·위조를 하지 않는다.
            if tier_code == 'INSUFFICIENT':
                horizons_data[H] = _insufficient_horizon(H, match_cnt, tier_label)
                continue

            fut_returns, trajectories, mdd_list = [], [], []
            win_cnt, tp_cnt, sl_cnt = 0, 0, 0

            for idx in dedup_matches:
                if idx + H * 2 <= len(prices):
                    fut = prices[idx+H : idx+H*2]
                else:
                    fut = prices[-H:]
                    
                ret_h = (fut[-1] - fut[0]) / (fut[0] + 1e-8)
                fut_returns.append(ret_h)
                if ret_h > 0: win_cnt += 1
                
                tp_lvl = self.TP_THRESHOLD_PCT / 100.0
                sl_lvl = -self.SL_THRESHOLD_PCT / 100.0
                tp_hit, sl_hit = False, False
                for p in fut:
                    p_chg = (p - fut[0]) / (fut[0] + 1e-8)
                    if p_chg >= tp_lvl and not sl_hit: tp_hit = True; break
                    if p_chg <= sl_lvl and not tp_hit: sl_hit = True; break
                if tp_hit: tp_cnt += 1
                elif sl_hit: sl_cnt += 1
                
                peak = fut[0]
                mdd = 0.0
                for p in fut:
                    if p > peak: peak = p
                    dd = (p - peak) / (peak + 1e-8)
                    if dd < mdd: mdd = dd
                mdd_list.append(mdd)
                trajectories.append(curr_p * (fut / (fut[0] + 1e-8)))
                
            # Profit Factor 산출용 총이익 / 총손실 (관찰 표본 기준)
            gross_win = float(sum(r for r in fut_returns if r > 0))
            gross_loss = float(abs(sum(r for r in fut_returns if r < 0)))
            profit_factor = round(gross_win / gross_loss, 2) if gross_loss > 1e-9 else None

            # 관찰된 분포를 그대로 사용한다 (평균의 배수로 만들어낸 값을 쓰지 않는다)
            mean_perf = round(float(np.mean(fut_returns)) * 100, 1)
            median_perf = round(float(np.median(fut_returns)) * 100, 1)
            std_perf = round(float(np.std(fut_returns, ddof=1)) * 100, 3) if match_cnt > 1 else None
            p90_perf = round(float(np.percentile(fut_returns, 90)) * 100, 1)
            p10_perf = round(float(np.percentile(fut_returns, 10)) * 100, 1)
            bayes_prob = self.bayesian_beta_binomial_calibration(win_cnt, match_cnt)
            ci_lo, ci_hi = self.wilson_interval(win_cnt, match_cnt)

            traj_arr = np.array(trajectories) if len(trajectories) > 0 else None

            horizons_data[H] = {
                'h': H,
                'match_count': match_cnt,
                'win_count': win_cnt,
                'loss_count': match_cnt - win_cnt,
                'win_rate': bayes_prob,
                'obs_win_rate': round(win_cnt / match_cnt * 100, 1),
                'ci_lower': ci_lo,
                'ci_upper': ci_hi,
                'mean_perf': mean_perf,
                'median_perf': median_perf,
                'std_perf': std_perf,
                'p90_perf': p90_perf,
                'p10_perf': p10_perf,
                'mdd': round(float(np.mean(mdd_list)) * 100, 1),
                'tp_first_prob': round((tp_cnt / match_cnt) * 100, 1),
                'sl_first_prob': round((sl_cnt / match_cnt) * 100, 1),
                # 목표·손절 어느 쪽도 기간 내 닿지 않은 사례. 이 범주를 빼면
                # tp+sl 합이 52% 처럼 보여 '나머지 48%는 뭔가' 라는 의문이 남는다.
                # 세 범주는 같은 분모(match_cnt)를 쓰며 합이 100% 다.
                'no_touch_prob': round((match_cnt - tp_cnt - sl_cnt) / match_cnt * 100, 1),
                'profit_factor': profit_factor,
                'status': tier_code,
                'tier_label': tier_label,
                # [명세 §10] 시나리오는 평균선의 평행이동이 아니라, 실제 과거 경로의 분위수다.
                # 각 분위수는 시점별로 독립 계산되므로 서로 다른 '모양'을 갖는다.
                'trajectory': np.median(traj_arr, axis=0) if traj_arr is not None else np.full(H, curr_p),
                'traj_p75': np.percentile(traj_arr, 75, axis=0) if traj_arr is not None else np.full(H, curr_p),
                'traj_p25': np.percentile(traj_arr, 25, axis=0) if traj_arr is not None else np.full(H, curr_p),
                'traj_p90': np.percentile(traj_arr, 90, axis=0) if traj_arr is not None else np.full(H, curr_p),
                'traj_p10': np.percentile(traj_arr, 10, axis=0) if traj_arr is not None else np.full(H, curr_p),
                # 낙관·중립·비관 대표경로: 최종수익률 기준 3분위 군집의 '평균 경로'
                **self._cluster_paths(traj_arr, fut_returns, H, curr_p),
                'ess': self._effective_sample_size(match_cnt, fut_returns),
                'trajectory_p80': np.percentile(traj_arr, 80, axis=0) if traj_arr is not None else np.full(H, curr_p),
                'trajectory_p20': np.percentile(traj_arr, 20, axis=0) if traj_arr is not None else np.full(H, curr_p),
            }

        # 기간 간 방향 일치도 — 산출 가능한 지평만으로 계산
        scored_h = [H for H in FORECAST_HORIZONS if horizons_data[H].get('win_rate') is not None]
        if scored_h:
            up_h = sum(1 for H in scored_h if horizons_data[H]['win_rate'] >= 50.0)
            horizon_consistency_score = int(round((max(up_h, len(scored_h) - up_h) / len(scored_h)) * 100))
        else:
            horizon_consistency_score = None

        # ── 최적 보유기간 선정 ────────────────────────────────────────────
        # 구버전은 mean_perf 만 크면 뽑혔다. ESS 8건짜리 120일이 '최적 보유기간'으로
        # 선택되는 문제가 있어, 자격 요건을 먼저 통과한 지평 중에서만 고른다.
        MIN_ESS = self.GATES.get('min_effective_samples', 10)
        best_h, max_eff = None, -1e18
        horizon_eligibility = {}
        for H in scored_h:
            hi = horizons_data[H]
            net = (hi['mean_perf'] or 0.0) - self.TOTAL_COST_PCT
            tp, sl = hi.get('tp_first_prob'), hi.get('sl_first_prob')
            ess = hi.get('ess') or 0.0
            reasons = []
            if ess < MIN_ESS:
                reasons.append(f"ESS {ess:.0f} < {MIN_ESS:.0f}")
            if net <= 0:
                reasons.append(f"순기대수익 {net:+.1f}% ≤ 0")
            if tp is None or sl is None or tp <= sl:
                reasons.append("목표가 선도달확률이 손절가 선도달확률 이하")
            eligible = not reasons
            horizon_eligibility[H] = {'eligible': eligible, 'reasons': reasons,
                                      'net_expected_return': round(net, 2)}
            if not eligible:
                continue
            stat_conf = min(1.0, ess / 30.0)
            rr_factor = float(np.clip(tp / max(sl, 1e-9), 0.5, 3.0))
            eff = (net * stat_conf * ((horizon_consistency_score or 0) / 100.0)
                   * rr_factor) / np.sqrt(H)
            if eff > max_eff:
                max_eff, best_h = eff, H

        # ── 미선정일 때 '무엇이 얼마나 모자란지' 를 계산한다 ────────────────
        # 화면에 '미선정'만 뜨면 사용자는 고장인지 판정인지 구분할 수 없다.
        # 게이트를 느슨하게 하지 않고, 가장 근접한 지평과 부족분을 알려준다.
        nearest = None
        if best_h is None and horizon_eligibility:
            def _shortfall(H):
                hi = horizons_data[H]
                net = (hi['mean_perf'] or 0.0) - self.TOTAL_COST_PCT
                ess = hi.get('ess') or 0.0
                tp, sl = hi.get('tp_first_prob') or 0.0, hi.get('sl_first_prob') or 0.0
                # 각 조건의 부족분을 0~1 로 정규화해 합산 (작을수록 근접)
                s_net = max(0.0, -net) / 2.0
                s_ess = max(0.0, MIN_ESS - ess) / MIN_ESS
                s_rr = max(0.0, sl - tp) / 50.0
                return s_net + s_ess + s_rr
            cand = sorted(horizon_eligibility, key=_shortfall)
            if cand:
                H = cand[0]
                hi = horizons_data[H]
                net = (hi['mean_perf'] or 0.0) - self.TOTAL_COST_PCT
                need = []
                if net <= 0:
                    need.append(f"순기대수익이 {abs(net):.2f}%p 더 필요 "
                                f"(현재 {net:+.2f}%, 거래비용 {self.TOTAL_COST_PCT:.2f}% 차감 후)")
                ess = hi.get('ess') or 0.0
                if ess < MIN_ESS:
                    need.append(f"유효표본 {MIN_ESS - ess:.0f}건 더 필요 (현재 ESS {ess:.0f})")
                tp, sl = hi.get('tp_first_prob'), hi.get('sl_first_prob')
                if tp is not None and sl is not None and tp <= sl:
                    need.append(f"목표가 선도달확률이 손절가보다 {sl - tp:.1f}%p 낮음 "
                                f"({tp:.1f}% vs {sl:.1f}%)")
                nearest = {'horizon': H, 'needs': need,
                           'net_expected_return': round(net, 2),
                           'ess': round(float(ess), 1)}

        no_sample = [H for H in FORECAST_HORIZONS if H not in horizon_eligibility]

        multi_horizon_meta = {
            'horizons_data': horizons_data,
            'horizon_consistency_score': horizon_consistency_score,
            'optimal_holding_period_days': best_h,
            'optimal_holding_period_str': (f"{best_h}영업일" if best_h
                                           else "미선정 (자격 요건 통과 지평 없음)"),
            'horizon_eligibility': horizon_eligibility,
            'horizon_nearest_miss': nearest,
            'horizons_without_sample': no_sample,
            'strategy_probabilities': strat_probs,
            'core_horizons': self.core_horizons_for(strat_probs),
            'rho_cutoff_applied': rho_cutoff,
        }

        # 20일 기본 시뮬레이션 호환 객체
        h20 = horizons_data[20]
        match_cnt = h20['match_count']
        tier_code = h20['status']
        tier_label = h20.get('tier_label', '')

        if tier_code == 'INSUFFICIENT':
            res = self._empty_blind_result(curr_p, f"20일 유효표본 {match_cnt}건 — {tier_label}")
            res.update(multi_horizon_meta)
            return res

        show_prob = self.probabilities_allowed(tier_code)
        mean_perf = h20['mean_perf']
        bayes_prob = h20['win_rate']
        win_count = h20['win_count']

        if show_prob:
            prob_note = f"{bayes_prob}% (베이지안 사후보정 — 과거 {match_cnt}건 중 {win_count}건 상승)"
            ci_str = f"{h20['ci_lower']:.1f}% ~ {h20['ci_upper']:.1f}%"
        else:
            # §11: 5~9건은 과거 관찰값만 표시하고 확률로 환산하지 않는다
            prob_note = f"미산출 — 과거 {match_cnt}건 중 {win_count}건 상승 (관찰값, 확률 환산 불가)"
            ci_str = "N/A (유효표본 10건 미만)"

        return {
            'match_count': match_cnt,
            'sample_tier': tier_code,
            'sample_tier_label': tier_label,
            'probabilities_shown': show_prob,
            'is_blind': not show_prob,
            'is_abstain': False,
            'abstain_reason': "정상 (다중기간 패턴 분석 완료)",
            'blind_reason': f"유효 표본 {match_cnt}건 — {tier_label}",
            'mean_perf': mean_perf,
            'median_perf': h20['median_perf'],
            'max_perf': h20['p90_perf'],
            'min_perf': h20['p10_perf'],
            'std_perf': h20['std_perf'],
            'mdd': h20['mdd'],
            'win_count': win_count,
            'loss_count': h20['loss_count'],
            'obs_win_ratio': h20['obs_win_rate'],
            'bayes_prob': bayes_prob if show_prob else None,
            'predicted_probability': bayes_prob if show_prob else None,
            'confidence_grade': tier_label,
            'ci_lower': h20['ci_lower'] if show_prob else None,
            'ci_upper': h20['ci_upper'] if show_prob else None,
            'ci_str': ci_str,
            'predicted_prob_str': prob_note,
            'mean_trajectory': h20['trajectory'],
            'bull_trajectory': h20['trajectory_p80'],
            'bear_trajectory': h20['trajectory_p20'],
            'tp_first_prob': h20['tp_first_prob'] if show_prob else None,
            'sl_first_prob': h20['sl_first_prob'] if show_prob else None,
            'no_touch_prob': h20.get('no_touch_prob') if show_prob else None,
            'profit_factor': h20.get('profit_factor'),
            # 앙상블 지표는 제거했다. 사후확률 하나를 9등분해 '9개 모델 중 N개 상승'으로
            # 표시하던 값이며, 실제 다중 모델 앙상블은 구현되어 있지 않다.
            'ensemble_implemented': False,
            'regime_label': "횡보 및 추세 전환 국면",
            'hierarchical_source': "동일 종목 & 계층적 다중기간 표본",
            **multi_horizon_meta
        }

    # ══════════════════════════════════════════════════════════════════════
    # Blind / OOS Walk-Forward 검증
    # ══════════════════════════════════════════════════════════════════════
    OOS_FRACTION = 0.30          # 뒤쪽 30%를 표본외 구간으로 사용
    OOS_MIN_TRAIN_BARS = 400     # 학습 구간 최소 봉 수
    OOS_ENTRY_PROB = 55.0        # 이 확률 이상일 때만 진입 신호로 간주
    OOS_MIN_TRADES = 20          # 이보다 적으면 전략 품질 판정 불가

    @staticmethod
    def _zscored_windows(prices, H):
        """길이 H의 모든 슬라이딩 윈도우를 Z-score 정규화한 행렬 (n-H+1, H)."""
        n = len(prices)
        idx = np.arange(n - H + 1)[:, None] + np.arange(H)[None, :]
        W = prices[idx]
        mu = W.mean(axis=1, keepdims=True)
        sd = W.std(axis=1, keepdims=True) + 1e-8
        return (W - mu) / sd

    def run_blind_oos_backtest(self, tech_df, horizon=20, rho_cutoff=0.80,
                               oos_fraction=None, embargo=None, min_matches=None):
        """
        [명세 §14] Purged Walk-Forward 표본외(Out-of-Sample) 검증.

        시점 t 에서:
          1) t 이전 데이터만으로 유사패턴을 찾는다.
          2) 후보 윈도우의 미래구간이 t 를 침범하지 않도록 embargo 를 둔다(purging).
          3) 매칭들의 과거 실현 방향으로 상승확률을 예측한다.
          4) t+H 의 '실제' 수익률과 대조한다.

        학습 구간에는 전혀 손대지 않으므로 in-sample 과 완전히 분리된다.
        """
        oos_fraction = self.OOS_FRACTION if oos_fraction is None else oos_fraction
        embargo = horizon if embargo is None else embargo
        min_matches = int(self.SAMPLE_TIERS[1][0]) if min_matches is None else min_matches  # 10건

        prices = np.asarray(tech_df['adj_close'].values, dtype=float)
        n = len(prices)
        need = self.OOS_MIN_TRAIN_BARS + 2 * horizon + embargo + 30
        if n < need:
            return {"available": False,
                    "reason": f"봉 수 부족 ({n} < {need}) — 표본외 검증 불가"}

        split = max(self.OOS_MIN_TRAIN_BARS, int(n * (1.0 - oos_fraction)))
        if split >= n - horizon - 1:
            return {"available": False, "reason": "표본외 구간이 확보되지 않음"}

        Wz = self._zscored_windows(prices, horizon)          # 윈도우 i = prices[i:i+H]
        ends = np.arange(len(Wz)) + horizon - 1              # 각 윈도우의 마지막 봉 인덱스

        preds, actual_up, actual_ret, pred_ret, dates = [], [], [], [], []
        trade_rets, trade_idx = [], []
        next_free = -1
        date_series = tech_df['trade_date'].values if 'trade_date' in tech_df.columns else None

        for t in range(split, n - horizon):
            q_start = t - horizon + 1
            if q_start < 0:
                continue
            qz = Wz[q_start]

            # 후보: 윈도우의 미래구간(end+1..end+H)이 t-embargo 이전에 끝나야 한다
            max_end = t - horizon - embargo
            if max_end < horizon:
                continue
            cand = np.where(ends <= max_end)[0]
            if len(cand) < min_matches:
                continue

            rho = (Wz[cand] @ qz) / horizon
            hit = cand[rho >= rho_cutoff]
            if len(hit) < min_matches:
                continue

            # 독립성: 최소 H봉 간격
            sel, last = [], -10 ** 9
            for i in hit:
                if i - last >= horizon:
                    sel.append(i)
                    last = i
            if len(sel) < min_matches:
                continue

            e = np.asarray(sel) + horizon - 1
            fwd = prices[e + horizon] / prices[e] - 1.0
            wins = int((fwd > 0).sum())
            p_up = self.bayesian_beta_binomial_calibration(wins, len(sel))

            realized = prices[t + horizon] / prices[t] - 1.0
            preds.append(p_up)
            pred_ret.append(float(np.mean(fwd)) * 100.0)
            actual_up.append(1 if realized > 0 else 0)
            actual_ret.append(realized * 100.0)
            if date_series is not None:
                dates.append(str(date_series[t]))

            # 비중첩 매매 시뮬레이션
            if p_up >= self.OOS_ENTRY_PROB and t > next_free:
                trade_rets.append(realized * 100.0 - self.TOTAL_COST_PCT)
                trade_idx.append(t)
                next_free = t + horizon

        n_pred = len(preds)
        if n_pred < self.OOS_MIN_TRADES:
            return {"available": False,
                    "reason": f"표본외 예측 건수 부족 ({n_pred}건 < {self.OOS_MIN_TRADES}건)"}

        p = np.asarray(preds) / 100.0
        y = np.asarray(actual_up, dtype=float)
        ar = np.asarray(actual_ret)
        pr = np.asarray(pred_ret)

        brier = float(np.mean((p - y) ** 2))
        mae = float(np.mean(np.abs(pr - ar)))
        directional_hit = float(np.mean(((p >= 0.5) == (y == 1)).astype(float)) * 100.0)

        # 전략 성과 (비중첩 트레이드)
        tr = np.asarray(trade_rets) if trade_rets else np.asarray([])
        if len(tr) >= 5:
            mu, sd = float(tr.mean()), float(tr.std(ddof=1))
            ann = np.sqrt(252.0 / horizon)
            sharpe = round(mu / sd * ann, 3) if sd > 1e-9 else None
            downside = tr[tr < 0]
            dsd = float(downside.std(ddof=1)) if len(downside) > 1 else None
            sortino = round(mu / dsd * ann, 3) if dsd and dsd > 1e-9 else None
            equity = np.cumprod(1.0 + tr / 100.0)
            mdd = float((equity / np.maximum.accumulate(equity) - 1.0).min() * 100.0)
            gross_w = float(tr[tr > 0].sum())
            gross_l = float(abs(tr[tr < 0].sum()))
            pf = round(gross_w / gross_l, 3) if gross_l > 1e-9 else None
            net_return = round(float((equity[-1] - 1.0) * 100.0), 2)
            win_rate = round(float((tr > 0).mean() * 100.0), 1)
            # 전반부·후반부 성과 일관성
            half = len(tr) // 2
            first_half = float(tr[:half].mean()) if half >= 3 else None
            second_half = float(tr[half:].mean()) if half >= 3 else None
        else:
            sharpe = sortino = pf = None
            mdd = net_return = win_rate = None
            mu = None
            first_half = second_half = None

        # 같은 구간 매수·보유 벤치마크
        bh = float((prices[n - 1] / prices[split] - 1.0) * 100.0)
        n_trades = len(tr)
        oos_years = max(0.25, (n - split) / 252.0)
        turnover = round(n_trades / oos_years * 100.0, 1)   # 연환산 왕복 회전율 %

        return {
            "available": True,
            "horizon": horizon,
            "rho_cutoff": rho_cutoff,
            "embargo": embargo,
            "train_bars": split,
            "oos_bars": n - split,
            "oos_start_date": str(date_series[split]) if date_series is not None else None,
            "n_predictions": n_pred,
            "n_trades": n_trades,
            "brier_score": round(brier, 4),
            "mae_pct": round(mae, 2),
            "directional_hit_pct": round(directional_hit, 1),
            "win_rate_pct": win_rate,
            "avg_trade_pct": round(mu, 3) if mu is not None else None,
            "sharpe": sharpe,
            "sortino": sortino,
            "mdd_pct": round(mdd, 2) if mdd is not None else None,
            "profit_factor": pf,
            "net_return_pct": net_return,
            "turnover_pct": turnover,
            "buy_hold_pct": round(bh, 2),
            "excess_vs_buy_hold": round(net_return - bh, 2) if net_return is not None else None,
            "first_half_avg": round(first_half, 3) if first_half is not None else None,
            "second_half_avg": round(second_half, 3) if second_half is not None else None,
        }

    def compute_strategy_quality(self, oos):
        """
        [명세 §14] 표본외 결과 → 전략 품질점수(0~100).
        가중치는 analysis_rulebook_ko.txt [RULES_STRATEGY_QUALITY_WEIGHTS] 를 따른다.
        """
        if not oos or not oos.get("available"):
            return {"available": False,
                    "reason": (oos or {}).get("reason", "표본외 검증 미수행"),
                    "score": None, "components": {}}

        W = RULEBOOK.get('RULES_STRATEGY_QUALITY_WEIGHTS', {})

        def band(v, lo, hi):
            """v 를 [lo, hi] 구간에서 0~100 으로 선형 환산."""
            if v is None:
                return 50.0
            return float(np.clip((v - lo) / (hi - lo) * 100.0, 0.0, 100.0))

        # 회전율 상한은 보유기간에서 구조적으로 결정된다 (20일 보유 → 연 최대 1,260%).
        # 절대값이 아니라 '가능 최대 대비 얼마나 자주 돌리는가'로 평가한다.
        H = oos.get('horizon') or 20
        max_turnover = 252.0 / H * 100.0
        comp = {
            'blind_oos': band(oos.get('directional_hit_pct'), 45.0, 62.0),
            'sharpe': band(oos.get('sharpe'), -0.5, 1.5),
            'sortino': band(oos.get('sortino'), -0.5, 2.0),
            # MDD·회전율은 작을수록 좋으므로 lo>hi 로 역방향 환산한다
            'mdd': band(abs(oos.get('mdd_pct') or 50.0), 40.0, 5.0),
            'net_return': band(oos.get('net_return_pct'), -20.0, 40.0),
            'turnover': band(oos.get('turnover_pct') or max_turnover, max_turnover, max_turnover * 0.15),
            'regime_stability': band(min(oos.get('first_half_avg') or 0.0,
                                         oos.get('second_half_avg') or 0.0), -2.0, 2.0),
            'alpha_persistence': band(oos.get('excess_vs_buy_hold'), -20.0, 20.0),
            'benchmark_consistency': band(oos.get('profit_factor'), 0.7, 1.8),
        }

        score = sum(comp[k] * W.get(f'weight_{k}', 0.0) for k in comp)
        total_w = sum(W.get(f'weight_{k}', 0.0) for k in comp)
        score = score / total_w if total_w > 0 else 50.0

        return {"available": True, "score": round(float(score), 1),
                "components": {k: round(v, 1) for k, v in comp.items()},
                "weights": {k: W.get(f'weight_{k}', 0.0) for k in comp}}

    def strategy_quality_cap(self, sq):
        """전략 품질점수 → 최종 행동점수 상한 (§14: 가점이 아니라 상한)."""
        if not sq or not sq.get("available") or sq.get("score") is None:
            return self.STRATEGY_QUALITY_CAP_WITHOUT_BLIND_TEST, \
                   f"Blind/OOS 검증 불가 ({(sq or {}).get('reason', '사유 미상')})"
        s = sq["score"]
        if s >= 70: return 95, None
        if s >= 55: return 85, f"전략 품질 {s:.0f}점 → 상한 85점"
        if s >= 40: return 72, f"전략 품질 {s:.0f}점 → 상한 72점"
        return 60, f"전략 품질 {s:.0f}점 (검증 부진) → 상한 60점"

    @staticmethod
    def _cluster_paths(traj_arr, fut_returns, H, curr_p):
        """
        최종 수익률 기준으로 매칭 경로를 낙관/중립/비관 3군집으로 나누고
        각 군집의 평균 경로를 낸다. 분위수 경로와 달리 '실제 경로들의 묶음'이라
        중간에 꺾이는 구조 차이가 보존된다.
        """
        flat = np.full(H, float(curr_p))
        if traj_arr is None or len(traj_arr) < 6:
            return {'path_bull': flat.copy(), 'path_base': flat.copy(), 'path_bear': flat.copy(),
                    'cluster_sizes': None}
        r = np.asarray(fut_returns, dtype=float)
        order = np.argsort(r)
        k = len(order) // 3
        bear_i, base_i, bull_i = order[:k], order[k:len(order) - k], order[len(order) - k:]
        return {
            'path_bull': traj_arr[bull_i].mean(axis=0),
            'path_base': traj_arr[base_i].mean(axis=0) if len(base_i) else traj_arr.mean(axis=0),
            'path_bear': traj_arr[bear_i].mean(axis=0),
            'cluster_sizes': {'bull': int(len(bull_i)), 'base': int(len(base_i)), 'bear': int(len(bear_i))},
        }

    @staticmethod
    def _effective_sample_size(match_cnt, fut_returns):
        """
        ESS — 관측치가 한쪽에 쏠려 있으면 실질 표본은 건수보다 작다.
        수익률 분포의 첨도 기반 감쇠를 적용한 보수적 유효표본수.
        """
        if match_cnt < 2 or not len(fut_returns):
            return float(match_cnt)
        r = np.asarray(fut_returns, dtype=float)
        sd = float(r.std(ddof=1))
        if sd <= 1e-12:
            return 1.0
        z = (r - r.mean()) / sd
        kurt = float(np.mean(z ** 4))
        penalty = float(np.clip(3.0 / max(kurt, 1e-6), 0.35, 1.0))
        return round(match_cnt * penalty, 1)

    # 전략 유형 → 핵심 예측기간 (§10). 그래프 기본 선택 기간을 결정한다.
    STRATEGY_CORE_HORIZONS = {
        'mean_reversion':    [5, 10, 20],
        'demark_reversal':   [5, 10, 20],
        'pullback':          [10, 20, 40],
        'trend_breakout':    [20, 40, 60],
        'earnings_momentum': [20, 60, 120],
        'monthly_trend':     [40, 60, 120],
    }

    def core_horizons_for(self, strategy_probabilities):
        """전략 확률에서 우세 유형을 골라 핵심 기간 목록을 돌려준다."""
        if not strategy_probabilities:
            return [10, 20, 40]
        dom = max(strategy_probabilities, key=strategy_probabilities.get)
        return self.STRATEGY_CORE_HORIZONS.get(dom, [10, 20, 40])

    def wilson_interval(self, wins, n, z=1.96):
        """95% Wilson score interval (%). UI가 '95% 신뢰구간'으로 표기하는 값의 실제 산출식."""
        if n <= 0:
            return None, None
        p = wins / n
        denom = 1.0 + (z * z) / n
        center = (p + (z * z) / (2 * n)) / denom
        half = (z * np.sqrt(p * (1 - p) / n + (z * z) / (4 * n * n))) / denom
        return round(float(max(0.0, center - half) * 100), 1), round(float(min(1.0, center + half) * 100), 1)

    def _empty_blind_result(self, curr_p, reason):
        """표본 미달 — 어떤 확률·기대수익도 반환하지 않는다. 궤적은 정보 없음을 뜻하는 평탄선."""
        flat = np.full(20, float(curr_p))
        return {
            'match_count': 0, 'sample_tier': 'INSUFFICIENT', 'sample_tier_label': reason,
            'probabilities_shown': False,
            'is_blind': True, 'is_abstain': True, 'abstain_reason': reason, 'blind_reason': reason,
            'confidence_grade': "통계적 판정 불가", 'predicted_probability': None, 'predicted_prob_str': "산출 불가",
            'bayes_prob': None, 'tp_first_prob': None, 'sl_first_prob': None, 'regime_label': "판정 보류",
            'hierarchical_source': "표본 없음", 'ensemble_implemented': False, 'obs_win_ratio': None,
            'win_count': 0, 'loss_count': 0, 'mean_perf': None, 'median_perf': None, 'max_perf': None,
            'min_perf': None, 'std_perf': None, 'mdd': None,
            'ci_lower': None, 'ci_upper': None, 'ci_str': "N/A",
            'mean_trajectory': flat, 'bull_trajectory': flat.copy(), 'bear_trajectory': flat.copy()
        }

    def compute_decoupled_price_position(self, tech_df, val_eval):
        """ [Section 2 & 3 & 15] 가격 위치 완전 분리 동적 연산기 """
        curr_price = float(tech_df['adj_close'].iloc[-1])
        prices_seq = tech_df['adj_close'].values
        
        # 52주 (약 250 영업일) 고저 범위 동적 산출
        lookback_window = min(len(prices_seq), 250)
        recent_prices = prices_seq[-lookback_window:]
        high_52w = float(np.max(recent_prices))
        low_52w = float(np.min(recent_prices))
        
        range_span = high_52w - low_52w
        if range_span <= 1e-6:
            range_pos_pct = 50.0
        else:
            range_pos_pct = round(((curr_price - low_52w) / range_span) * 100.0, 1)
            range_pos_pct = float(np.clip(range_pos_pct, 0.0, 100.0))
            
        if range_pos_pct <= 15.0: range_name = "발목"
        elif range_pos_pct <= 35.0: range_name = "무릎"
        elif range_pos_pct <= 65.0: range_name = "허리"
        elif range_pos_pct <= 85.0: range_name = "어깨"
        else: range_name = "머리"
            
        sma_60 = float(tech_df['sma_60'].iloc[-1]) if 'sma_60' in tech_df.columns else curr_price
        disparity_60 = round(((curr_price - sma_60) / (sma_60 + 1e-8)) * 100.0, 1)
        drop_from_high = round(((curr_price - high_52w) / (high_52w + 1e-8)) * 100.0, 1)
        
        summary_text = f"💎 현재 가격 위치: {range_name} ({val_eval.get('pos_simple', '허리')}대)\n- 52주 범위 위치: {range_pos_pct}%\n- 적정가 범위 내 위치: {val_eval.get('pos_val', '적정')}\n- 60일선 대비 이격률: {disparity_60:+.1f}%\n- 52주 고점 대비 하락률: {drop_from_high:.1f}%"
        
        return {
            'range_pos_pct': range_pos_pct, 'range_name': range_name, 'high_52w': high_52w, 'low_52w': low_52w,
            'disparity_60': disparity_60, 'drop_from_high': drop_from_high, 'summary_text': summary_text
        }

    def compute_demark_indicators(self, df):
        """
        DeMARK 9-13 and TDST Analysis with Multiple Indicators (BB, Williams R, RSI, ADX)
        """
        if len(df) < 15:
            return self._empty_demark_result()

        closes = df['adj_close'].values
        opens = df['open'].values if 'open' in df.columns else closes
        highs = df['high'].values if 'high' in df.columns else closes
        lows = df['low'].values if 'low' in df.columns else closes
        volumes = df['volume'].values
        vol_ma20 = df['vol_20_avg'].values
        
        bb_upper = df['bb_upper'].values
        bb_lower = df['bb_lower'].values
        williams_r = df['williams_r'].values
        rsi = df['rsi_14'].values
        adx = df['adx'].values
        plus_di = df['plus_di'].values
        minus_di = df['minus_di'].values
        
        n = len(closes)
        
        # 1. True High & True Low
        import numpy as np
        true_highs = np.zeros(n)
        true_lows = np.zeros(n)
        true_highs[0] = highs[0]
        true_lows[0] = lows[0]
        for t in range(1, n):
            true_highs[t] = max(highs[t], closes[t-1])
            true_lows[t] = min(lows[t], closes[t-1])
            
        # 2. Price Flip
        bearish_flip = np.zeros(n, dtype=bool)
        bullish_flip = np.zeros(n, dtype=bool)
        for t in range(5, n):
            bearish_flip[t] = (closes[t-1] > closes[t-5]) and (closes[t] < closes[t-4])
            bullish_flip[t] = (closes[t-1] < closes[t-5]) and (closes[t] > closes[t-4])
            
        # 3. Buy/Sell Setup 9
        buy_setup_count = np.zeros(n, dtype=int)
        sell_setup_count = np.zeros(n, dtype=int)
        
        for t in range(4, n):
            if closes[t] < closes[t-4]:
                buy_setup_count[t] = min(9, buy_setup_count[t-1] + 1)
            else:
                buy_setup_count[t] = 0
                
            if closes[t] > closes[t-4]:
                sell_setup_count[t] = min(9, sell_setup_count[t-1] + 1)
            else:
                sell_setup_count[t] = 0
                
        # Perfected Setup Map
        buy_perfected_map = {}
        sell_perfected_map = {}
        buy_setup_completed_indices = []
        sell_setup_completed_indices = []
        
        for t in range(n):
            if buy_setup_count[t] == 9 and (t == 0 or buy_setup_count[t-1] == 8):
                buy_setup_completed_indices.append(t)
                if t >= 3:
                    is_perf = min(lows[t-1], lows[t]) <= min(lows[t-3], lows[t-2])
                    buy_perfected_map[t] = is_perf
            if sell_setup_count[t] == 9 and (t == 0 or sell_setup_count[t-1] == 8):
                sell_setup_completed_indices.append(t)
                if t >= 3:
                    is_perf = max(highs[t-1], highs[t]) >= max(highs[t-3], highs[t-2])
                    sell_perfected_map[t] = is_perf

        latest_buy_setup_idx = buy_setup_completed_indices[-1] if buy_setup_completed_indices else None
        latest_sell_setup_idx = sell_setup_completed_indices[-1] if sell_setup_completed_indices else None

        # TDST Support/Resistance (NaN-safe)
        if latest_buy_setup_idx is not None and latest_buy_setup_idx >= 8:
            setup_start = latest_buy_setup_idx - 8
            tdst_resistance = float(np.nanmax(true_highs[setup_start : latest_buy_setup_idx + 1]))
        else:
            tdst_resistance = float(np.nanmax(true_highs[-20:])) if n >= 20 else float(np.nanmax(true_highs))
            
        if latest_sell_setup_idx is not None and latest_sell_setup_idx >= 8:
            setup_start = latest_sell_setup_idx - 8
            tdst_support = float(np.nanmin(true_lows[setup_start : latest_sell_setup_idx + 1]))
        else:
            tdst_support = float(np.nanmin(true_lows[-20:])) if n >= 20 else float(np.nanmin(true_lows))

        if np.isnan(tdst_resistance) or tdst_resistance <= 0:
            tdst_resistance = float(closes[-1] * 1.05)
        if np.isnan(tdst_support) or tdst_support <= 0:
            tdst_support = float(closes[-1] * 0.95)

        # 4. Historical Countdown 13 Series & TDST Level Tracking
        buy_cd_series = np.zeros(n, dtype=int)
        sell_cd_series = np.zeros(n, dtype=int)
        
        curr_b_cd = 0
        in_b_countdown = False
        for t in range(n):
            if buy_setup_count[t] == 9:
                in_b_countdown = True
                curr_b_cd = 0
            elif in_b_countdown:
                if t >= 2 and closes[t] <= lows[t-2]:
                    curr_b_cd += 1
                    buy_cd_series[t] = curr_b_cd
                    if curr_b_cd >= 13:
                        in_b_countdown = False
                        
        curr_s_cd = 0
        in_s_countdown = False
        for t in range(n):
            if sell_setup_count[t] == 9:
                in_s_countdown = True
                curr_s_cd = 0
            elif in_s_countdown:
                if t >= 2 and closes[t] >= highs[t-2]:
                    curr_s_cd += 1
                    sell_cd_series[t] = curr_s_cd
                    if curr_s_cd >= 13:
                        in_s_countdown = False

        buy_countdown = buy_cd_series[-1] if n > 0 else 0
        sell_countdown = sell_cd_series[-1] if n > 0 else 0
        buy_countdown_idx_8 = None
        buy_countdown_idx_13 = None
        sell_countdown_idx_8 = None
        sell_countdown_idx_13 = None

        buy_13_confirmed = False
        if buy_countdown >= 13 and buy_countdown_idx_13 is not None and buy_countdown_idx_8 is not None:
            if lows[buy_countdown_idx_13] <= closes[buy_countdown_idx_8]:
                buy_13_confirmed = True

        sell_13_confirmed = False
        if sell_countdown >= 13 and sell_countdown_idx_13 is not None and sell_countdown_idx_8 is not None:
            if highs[sell_countdown_idx_13] >= closes[sell_countdown_idx_8]:
                sell_13_confirmed = True

        t = n - 1
        
        # 5. Multi-indicator Validations
        is_perfected_buy = buy_perfected_map.get(latest_buy_setup_idx, False) if latest_buy_setup_idx else False
        is_perfected_sell = sell_perfected_map.get(latest_sell_setup_idx, False) if latest_sell_setup_idx else False
        
        bollinger_lower_reentry = (t >= 1) and (closes[t-1] < bb_lower[t-1]) and (closes[t] >= bb_lower[t])
        bollinger_upper_reentry = (t >= 1) and (closes[t-1] > bb_upper[t-1]) and (closes[t] <= bb_upper[t])
        
        williams_r_buy_reversal = (t >= 1) and (williams_r[t-1] <= -80) and (williams_r[t] > -80)
        williams_r_sell_reversal = (t >= 1) and (williams_r[t-1] >= -20) and (williams_r[t] < -20)
        
        rsi_bullish_reversal = (t >= 2) and (
            (rsi[t-1] <= 30 and rsi[t] > 30) or 
            (rsi[t] > rsi[t-1] and rsi[t-1] > rsi[t-2] and rsi[t] >= 40)
        )
        rsi_bearish_reversal = (t >= 2) and (
            (rsi[t-1] >= 70 and rsi[t] < 70) or 
            (rsi[t] < rsi[t-1] and rsi[t-1] < rsi[t-2] and rsi[t] <= 60)
        )
        
        vol_confirmed = (t >= 1) and (closes[t] > closes[t-1]) and (volumes[t] >= vol_ma20[t] * 1.2)
        down_vol_confirmed = (t >= 1) and (closes[t] < closes[t-1]) and (volumes[t] >= vol_ma20[t] * 1.2)
        
        tdst_support_maintained = closes[t] >= tdst_support
        tdst_resistance_rejection = closes[t] <= tdst_resistance
        
        # ── 볼린저 밴드 내 위치 (0=하단, 100=상단) ─────────────────────────
        _bw = float(bb_upper[t] - bb_lower[t])
        bb_position_pct = (float(closes[t] - bb_lower[t]) / _bw * 100.0) if _bw > 0 else None
        bb_width_pct = (_bw / float(closes[t]) * 100.0) if closes[t] else None
        if bb_position_pct is None:
            bb_state = "산출 불가"
        elif bb_position_pct < 0:
            bb_state = "하단 이탈 (과매도)"
        elif bb_position_pct < 25:
            bb_state = "하단권"
        elif bb_position_pct <= 75:
            bb_state = "중앙권"
        elif bb_position_pct <= 100:
            bb_state = "상단권"
        else:
            bb_state = "상단 돌파 (과열)"

        # 6. Bullish / Bearish Scoring (100점 만점)
        #
        # ⚠️ 구버전은 '오늘 봉에서 특정 사건이 일어났는가'만 셌다.
        #    셋업이 정확히 9, 볼린저 재진입 같은 희귀 이벤트뿐이라 거의 모든 종목이
        #    bullish 8 / bearish 0 으로 고정되고 라벨은 늘 '방향성 탐색 중' 이었다.
        #    (매수셋업 5/9 로 진행 중인 종목도 0점)
        #    이제 **상태(state)** 를 점수화한다 — 진행도·밴드 위치·지표 수준.
        bullish_score = 0.0
        # 셋업 진행도 (0~9) — 9 완성이면 만점
        bullish_score += min(buy_setup_count[t], 9) / 9.0 * 14.0
        if is_perfected_buy and latest_buy_setup_idx and (t - latest_buy_setup_idx <= 5):
            bullish_score += 10
        # 카운트다운 진행도 (0~13)
        bullish_score += min(buy_countdown, 13) / 13.0 * 16.0
        if buy_countdown >= 13 and buy_13_confirmed:
            bullish_score += 10
        # 볼린저 위치 — 아래쪽일수록 반등 여지
        if bb_position_pct is not None:
            bullish_score += float(np.clip((50.0 - bb_position_pct) / 50.0, 0, 1)) * 12.0
        if bollinger_lower_reentry:
            bullish_score += 6
        # Williams %R 침체권 (-80 이하) 및 회복
        if not np.isnan(williams_r[t]):
            bullish_score += float(np.clip((-williams_r[t] - 50.0) / 40.0, 0, 1)) * 10.0
        if williams_r_buy_reversal:
            bullish_score += 5
        # RSI 낮을수록 가점 (30 이하에서 최대)
        if not np.isnan(rsi[t]):
            bullish_score += float(np.clip((50.0 - rsi[t]) / 25.0, 0, 1)) * 8.0
        if rsi_bullish_reversal:
            bullish_score += 5
        if vol_confirmed:
            bullish_score += 6
        if tdst_support_maintained:
            bullish_score += 6
        # 수급 확인은 실제 값이 있을 때만 가점한다 (NaN이면 가점도 감점도 없음)
        _inst = df['institution_net'].iloc[-1] if 'institution_net' in df.columns else np.nan
        _forg = df['foreign_net'].iloc[-1] if 'foreign_net' in df.columns else np.nan
        if not pd.isna(_inst) and _inst > 0: bullish_score += 5
        elif not pd.isna(_forg) and _forg > 0: bullish_score += 5

        bearish_score = 0.0
        bearish_score += min(sell_setup_count[t], 9) / 9.0 * 14.0
        if is_perfected_sell and latest_sell_setup_idx and (t - latest_sell_setup_idx <= 5):
            bearish_score += 10
        bearish_score += min(sell_countdown, 13) / 13.0 * 16.0
        if sell_countdown >= 13 and sell_13_confirmed:
            bearish_score += 10
        if bb_position_pct is not None:
            bearish_score += float(np.clip((bb_position_pct - 50.0) / 50.0, 0, 1)) * 12.0
        if bollinger_upper_reentry:
            bearish_score += 6
        if not np.isnan(williams_r[t]):
            bearish_score += float(np.clip((williams_r[t] + 50.0) / 40.0, 0, 1)) * 10.0
        if williams_r_sell_reversal:
            bearish_score += 5
        if not np.isnan(rsi[t]):
            bearish_score += float(np.clip((rsi[t] - 50.0) / 25.0, 0, 1)) * 8.0
        if rsi_bearish_reversal:
            bearish_score += 5
        if down_vol_confirmed:
            bearish_score += 6
        if not tdst_support_maintained:
            bearish_score += 6
        if not pd.isna(_inst) and _inst < 0: bearish_score += 5
        elif not pd.isna(_forg) and _forg < 0: bearish_score += 5

        # ADX Trend Filter (Cap scores at 60 if counter-trend)
        curr_adx = adx[t]
        if curr_adx >= 30:
            if minus_di[t] > plus_di[t]: # Strong downtrend -> Cap bullish
                bullish_score = min(bullish_score, 60)
            if plus_di[t] > minus_di[t]: # Strong uptrend -> Cap bearish
                bearish_score = min(bearish_score, 60)
                
        # 7. Final Output Construction
        bullish_score = int(round(min(100, bullish_score)))
        bearish_score = int(round(min(100, bearish_score)))

        # 라벨은 **우열(edge)** 로 정한다.
        # 구버전은 bullish 를 먼저 다 훑은 뒤 bearish 를 봐서, bullish 가 43 미만이면
        # bearish 가 아무리 높아도 '방향성 탐색 중' 으로 떨어졌다.
        # 우열(edge)뿐 아니라 **절대 확신도**도 함께 본다.
        # 우열만 보면 11 대 3 같은 약한 신호도 '강한 분할매수'가 되어 과장된다.
        edge = bullish_score - bearish_score
        if bullish_score >= 65 and bearish_score >= 65:
            demark_label = "변동성 확대·방향 충돌 (신규 진입 보류)"
        elif edge >= 30 and bullish_score >= 55:
            demark_label = "강한 분할매수"
        elif edge >= 18 and bullish_score >= 38:
            demark_label = "매수 확인"
        elif edge >= 10:
            demark_label = "예비 매수 (신호 약함)" if bullish_score < 30 else "예비 매수"
        elif edge <= -30 and bearish_score >= 55:
            demark_label = "강한 매도"
        elif edge <= -18 and bearish_score >= 38:
            demark_label = "매도 확인"
        elif edge <= -10:
            demark_label = "예비 매도 (신호 약함)" if bearish_score < 30 else "예비 매도"
        else:
            demark_label = "중립 (매수·매도 우열 없음)"
            
        # Update strategy scores mapping from old variables
        demark_signal_score = int(max(bullish_score, bearish_score))
        if bullish_score >= bearish_score:
            direction_edge = bullish_score - bearish_score
        else:
            direction_edge = -(bearish_score - bullish_score)

        return {
            'buy_setup_count': int(buy_setup_count[t]),
            'sell_setup_count': int(sell_setup_count[t]),
            'buy_perfected': is_perfected_buy,
            'sell_perfected': is_perfected_sell,
            'perfected_status': "충족" if (is_perfected_buy or is_perfected_sell) else "미충족",
            'buy_countdown': int(buy_countdown),
            'sell_countdown': int(sell_countdown),
            'buy_13_status': f"{min(13, buy_countdown)}/13",
            'sell_13_status': f"{min(13, sell_countdown)}/13",
            'tdst_resistance': tdst_resistance,
            'tdst_support': tdst_support,
            'bollinger_lower_reentry': bollinger_lower_reentry,
            'bollinger_upper_reentry': bollinger_upper_reentry,
            # 밴드 내 위치를 그대로 내보낸다. 예전에는 '재진입 여부'만 있어서
            # 화면이 항상 '특이사항 없음' 으로 떨어졌다 (하단 24% 종목도 마찬가지).
            'bb_position_pct': bb_position_pct,
            'bb_width_pct': bb_width_pct,
            'bb_state': bb_state,
            'bb_upper': float(bb_upper[t]), 'bb_lower': float(bb_lower[t]),
            'rsi_value': float(rsi[t]) if not np.isnan(rsi[t]) else None,
            'williams_r_value': float(williams_r[t]) if not np.isnan(williams_r[t]) else None,
            'williams_r_buy_reversal': williams_r_buy_reversal,
            'rsi_bullish_reversal': rsi_bullish_reversal,
            'williams_r_val': float(williams_r[t]),
            'vol_confirmed': vol_confirmed,
            'adx': curr_adx,
            'bullish_score': int(bullish_score),
            'bearish_score': int(bearish_score),
            'demark_signal_score': demark_signal_score,
            'demark_label': demark_label,
            'direction_edge': direction_edge,
            'buy_setup_series': buy_setup_count,
            'sell_setup_series': sell_setup_count,
            'buy_countdown_series': buy_cd_series,
            'sell_countdown_series': sell_cd_series,
            'buy_countdown_idx_13': buy_countdown_idx_13,
            'sell_countdown_idx_13': sell_countdown_idx_13
        }

    def _empty_demark_result(self):
        return {
            'buy_setup_count': 0, 'sell_setup_count': 0,
            'buy_perfected': False, 'sell_perfected': False, 'perfected_status': "N/A",
            'buy_countdown': 0, 'sell_countdown': 0, 'buy_13_status': "N/A", 'sell_13_status': "N/A",
            'tdst_resistance': None, 'tdst_support': None,
            'bollinger_lower_reentry': False, 'bollinger_upper_reentry': False,
            'bb_position_pct': None, 'bb_width_pct': None, 'bb_state': "산출 불가",
            'bb_upper': None, 'bb_lower': None,
            'rsi_value': None, 'williams_r_value': None,
            'williams_r_buy_reversal': False, 'rsi_bullish_reversal': False, 'vol_confirmed': False,
            'adx': 20.0,
            # 표본이 없어 산출하지 못한 상태를 '50점 중립'으로 위장하지 않는다
            'bullish_score': 0, 'bearish_score': 0,
            'demark_signal_score': 0, 'demark_label': "산출 불가 (데이터 부족)",
            'direction_edge': 0,
            'buy_setup_series': [], 'sell_setup_series': [],
            'buy_countdown_idx_13': None, 'sell_countdown_idx_13': None
        }

    # ═════════════════════════════════════════════════════════════════════
    # 탭별 판정 + 최종 종합 결론
    #
    # 설계 원칙:
    #   ① 각 탭은 **독립된 근거**로 0~100 점과 매수/매도 판정을 낸다.
    #      한 탭이 좋아도 다른 탭이 반대면 그 사실이 보여야 한다.
    #   ② 종합 점수는 가중 평균이되, **가중치를 화면에 그대로 보여준다**.
    #      숫자만 던지고 근거를 숨기면 판단에 쓸 수 없다.
    #   ③ 가중 평균 위에 **거부권(veto)** 을 둔다. 표본이 없거나 순기대수익이
    #      음수면 아무리 다른 점수가 높아도 매수 결론을 내지 않는다.
    #      평균은 나쁜 조건을 좋은 조건으로 상쇄해버리기 때문이다.
    # ═════════════════════════════════════════════════════════════════════

    #: 탭 → 종합 점수 가중치 (합 1.0). 규칙집에서 읽고 없으면 아래 기본값.
    TAB_WEIGHTS = {
        'pattern':    rb('RULES_TAB_WEIGHTS', 'pattern', 0.25),    # 자기유사 예측
        'valuation':  rb('RULES_TAB_WEIGHTS', 'valuation', 0.22),  # 밸류에이션
        'scenario':   rb('RULES_TAB_WEIGHTS', 'scenario', 0.15),   # 대응 시나리오
        'demark':     rb('RULES_TAB_WEIGHTS', 'demark', 0.13),     # DeMARK
        'technical':  rb('RULES_TAB_WEIGHTS', 'technical', 0.13),  # 수급·기술
        'integrity':  rb('RULES_TAB_WEIGHTS', 'integrity', 0.12),  # 무결성·전략품질
    }

    @staticmethod
    def _verdict_from_score(score, strong_buy=72, buy=60, hold=45, sell=32):
        """0~100 점 → 다섯 단계 판정."""
        if score is None:
            return "산출 불가", "#86868b"
        if score >= strong_buy:
            return "매수", "#30d158"
        if score >= buy:
            return "매수 우위", "#7bd88f"
        if score >= hold:
            return "중립·관망", "#ff9f0a"
        if score >= sell:
            return "매도 우위", "#ff7a45"
        return "매도", "#ff453a"

    def build_tab_verdicts(self, snap):
        """
        탭마다 독립 점수·판정·근거를 만든다.
        반환: [{key, label, score, verdict, color, reasons[], available}]
        """
        fs = snap.get('four_scores') or {}
        sim = snap.get('sim_res') or {}
        val = snap.get('val_eval') or {}
        oos = snap.get('oos_result') or {}
        tabs = []

        def add(key, label, score, reasons, available=True):
            v, c = self._verdict_from_score(score)
            tabs.append({'key': key, 'label': label,
                         'score': None if score is None else int(round(score)),
                         'verdict': v if available else "산출 불가",
                         'color': c if available else "#86868b",
                         'reasons': reasons, 'available': available})

        # ── ① 자기유사 예측 ──────────────────────────────────────────────
        # ⚠️ 예전에는 sim['win_rate'] 를 읽었는데 그 키는 최상위에 존재하지 않는다.
        #    표본 23건(확률 허용)인데도 이 탭만 '산출 불가 — 기준 미달' 로 표시되어,
        #    바로 옆의 베이지안 47%·선도달 확률과 화면이 모순됐다.
        #    확률 허용 여부는 엔진의 probabilities_shown 하나로 판정한다.
        wr = sim.get('bayes_prob')
        obs = sim.get('obs_win_ratio')
        mp = sim.get('mean_perf')
        mc = sim.get('match_count') or 0
        allowed = bool(sim.get('probabilities_shown'))
        if not allowed or wr is None:
            add('pattern', '🔮 자기유사 예측',
                None, [f"유효표본 {mc}건 — 확률 산출 기준(10건) 미달, 관찰값만 참고"],
                available=False)
        else:
            net = (mp or 0.0) - self.TOTAL_COST_PCT
            s = float(np.clip(50 + (wr - 50) * 1.6 + net * 6.0, 0, 100))
            add('pattern', '🔮 자기유사 예측', s, [
                f"과거 유사구간 {mc}건 · 관찰 승률 {fmt_or(obs, digits=1)}% · "
                f"베이지안 사후 {wr:.1f}%",
                f"평균 수익률 {mp:+.2f}% → 거래비용 {self.TOTAL_COST_PCT:.2f}% 차감 후 {net:+.2f}%",
            ])

        # ── ② 밸류에이션 ────────────────────────────────────────────────
        up = val.get('upside_pct')
        conf = val.get('fair_value_confidence')
        if val.get('is_fund'):
            add('valuation', '💎 밸류에이션', None,
                ["ETF·ETN 은 펀더멘털 적정가가 성립하지 않습니다"], available=False)
        elif up is None or conf is None or conf < 45:
            add('valuation', '💎 밸류에이션', None,
                [f"적정가 신뢰도 {fmt_or(conf)} — 산출 보류"], available=False)
        else:
            s = float(np.clip(50 + up * 0.8, 0, 100))
            s = s * (0.6 + 0.4 * min(conf, 95) / 95.0)     # 신뢰도로 감쇠
            add('valuation', '💎 밸류에이션', s, [
                f"적정가 대비 상승여력 {up:+.1f}% (신뢰도 {conf:.0f}점)",
                f"진입 위치: {fs.get('entry_zone', '판정 불가')}",
            ])

        # ── ③ 대응 시나리오 (목표·손절 선도달) ────────────────────────────
        tp = sim.get('tp_first_prob')
        sl = sim.get('sl_first_prob')
        if tp is None or sl is None:
            add('scenario', '🎯 대응 시나리오', None,
                ["표본 부족으로 목표·손절 선도달 확률 미산출"], available=False)
        else:
            nt = sim.get('no_touch_prob')
            if nt is None:
                nt = round(max(0.0, 100.0 - tp - sl), 1)
            s = float(np.clip(50 + (tp - sl) * 1.2, 0, 100))
            add('scenario', '🎯 대응 시나리오', s, [
                f"목표 선도달 {tp:.1f}% · 손절 선도달 {sl:.1f}% · 미도달 {nt:.1f}% (합 100%)",
                f"손익비 {fmt_or(fs.get('reward_risk_ratio'))}",
            ])

        # ── ④ DeMARK ───────────────────────────────────────────────────
        bull = fs.get('demark_bullish_score')
        bear = fs.get('demark_bearish_score')
        if bull is None or bear is None:
            add('demark', '⏱️ DeMARK', None, ["지표 산출 불가"], available=False)
        else:
            s = float(np.clip(50 + (bull - bear) * 0.9, 0, 100))
            add('demark', '⏱️ DeMARK', s, [
                f"Bullish {bull} vs Bearish {bear} → {fs.get('demark_direction_text', '')}",
                f"TDST 지지 {fs.get('tdst_support_str', '-')} · 저항 {fs.get('tdst_resist_str', '-')}",
            ])

        # ── ⑤ 수급·기술 ─────────────────────────────────────────────────
        bbp = fs.get('bb_position_pct')
        rsi_v = fs.get('rsi_value')
        reasons5, parts = [], []
        if bbp is not None:
            parts.append(float(np.clip(100 - bbp, 0, 100)))    # 하단일수록 유리
            reasons5.append(f"볼린저 밴드 내 위치 {bbp:.0f}% ({fs.get('bb_state', '')})")
        if rsi_v is not None:
            parts.append(float(np.clip(100 - rsi_v * 1.2, 0, 100)))
            reasons5.append(f"RSI {rsi_v:.0f}")
        if fs.get('market_regime_label'):
            reasons5.append(f"시장 국면: {fs['market_regime_label']}")
        if parts:
            add('technical', '🌊 수급·기술', float(np.mean(parts)), reasons5)
        else:
            add('technical', '🌊 수급·기술', None, ["기술적 지표 산출 불가"], available=False)

        # ── ⑥ 무결성·전략품질 ────────────────────────────────────────────
        sq = fs.get('strategy_quality_score')
        ac = fs.get('analysis_confidence')
        if sq is None and ac is None:
            add('integrity', '🏛️ 무결성·전략품질', None, ["미산출"], available=False)
        else:
            s = float(np.mean([x for x in (sq, ac) if x is not None]))
            r6 = []
            if sq is not None:
                r6.append(f"표본외(OOS) 전략품질 {sq:.0f}점"
                          + (f" · Sharpe {oos.get('sharpe')}" if oos.get('sharpe') is not None else ""))
            if ac is not None:
                r6.append(f"분석 신뢰도 {ac:.0f}점")
            add('integrity', '🏛️ 무결성·전략품질', s, r6)

        return tabs

    def build_final_verdict(self, snap):
        """
        탭 판정을 모아 **하나의 결론**을 만든다.

        반환:
            headline      : '사도 됩니다' / '지금은 사지 마세요' 등 한 줄 결론
            action        : BUY | ACCUMULATE | HOLD | REDUCE | SELL | NO_TRADE
            score         : 0~100 종합 점수 (가중 평균)
            contributions : 탭별 [점수 × 가중치 = 기여] 내역
            vetoes        : 매수 결론을 막은 조건들 (있으면 그것이 결론을 지배한다)
            summary       : 사람이 읽는 근거 2~4줄
        """
        fs = snap.get('four_scores') or {}
        sim = snap.get('sim_res') or {}
        tabs = self.build_tab_verdicts(snap)

        # ⚠️ 종합 점수는 **하나만** 존재해야 한다.
        #    한때 이 함수가 탭 가중평균으로 별도 점수를 만들어, 화면에 49점과 65점이
        #    동시에 떴다 (광주신세계 16점 차이). 어느 쪽을 믿어야 할지 알 수 없다.
        #    규칙집 기반 final_action_score 가 스캐너·TOP3·게이트를 모두 구동하는
        #    시스템의 정본이므로 그것을 유일한 종합 점수로 삼는다.
        #    탭 점수는 '관점별 독립 판정' 으로만 쓰고 합산하지 않는다.
        base = fs.get('final_action_score')

        # 화면에 보여줄 산식은 **실제로 점수를 만든 그 산식**이어야 한다.
        wq = self.W_TOP.get('weight_stock_quality', 0.35)
        wt = self.W_TOP.get('weight_trading_timing', 0.45)
        wr_ = self.W_TOP.get('weight_risk_safety', 0.20)
        q_s = fs.get('stock_quality_score')
        t_s = fs.get('trading_timing_score')
        r_s = fs.get('risk_safety_score')
        composition = [
            {'label': '종목 기본 매력도', 'score': q_s, 'weight_pct': wq * 100,
             'contribution': None if q_s is None else q_s * wq},
            {'label': '현재 매매 적합도', 'score': t_s, 'weight_pct': wt * 100,
             'contribution': None if t_s is None else t_s * wt},
            {'label': '리스크 안전성', 'score': r_s, 'weight_pct': wr_ * 100,
             'contribution': None if r_s is None else r_s * wr_},
        ]
        raw_sum = sum(c['contribution'] for c in composition
                      if c['contribution'] is not None)
        cap = fs.get('final_score_cap')
        cap_applied = (base is not None and raw_sum - base > 0.5)

        # ── 거부권 — 평균으로 상쇄되면 안 되는 조건들 ────────────────────
        vetoes = []
        net = (sim.get('mean_perf') or 0.0) - self.TOTAL_COST_PCT
        if not self.probabilities_allowed(sim.get('sample_tier') or sim.get('status', '')):
            vetoes.append(f"유효표본 {sim.get('match_count', 0)}건 — 확률 판단 기준 미달")
        # [라운드 3] 이 거부권은 매수 결론의 42%를 막는 최대 차단자인데,
        # 원장 4,011건 실측에서 net>0 과 net<=0 의 성과 차이가 적중률 +0.9%p ·
        # 비용후 +0.03%p 로 사실상 없었다(블라인드에서는 오히려 역전).
        # 즉 자기유사 평균수익 한 점 추정은 잡음이다.
        # 대안: 잡음 하나로 막지 않고, **더 큰 표본인 점수대 캘리브레이션이
        # 함께 약할 때만** 막는다. 산식·KPI 정의는 그대로다.
        # 기본값은 현행(strict) — 후보 원장으로 검증한 뒤에만 승격한다.
        if sim.get('mean_perf') is not None and net <= 0:
            _band = fs.get('calibration_band') or {}
            _band_weak = (_band.get('wilson_low') is None
                          or (_band.get('n') or 0) < 30
                          or float(_band['wilson_low']) < 50.0)
            if self.VETO_NET_MODE == 'strict' or _band_weak:
                vetoes.append(f"거래비용 차감 후 기대수익 {net:+.2f}% (0 이하)")
            else:
                # 차단하지 않은 사실을 화면에 남긴다 (숨기지 않는다)
                fs.setdefault('soft_conflict_notes', []).append(
                    f"자기유사 기대수익은 {net:+.2f}%로 약하지만, 이 점수대의 "
                    f"과거 실측(n={_band.get('n')}, 하한 "
                    f"{float(_band['wilson_low']):.0f}%)이 이를 상쇄해 "
                    "매수 차단까지는 하지 않았습니다.")
        ez = fs.get('entry_zone', '')
        if '추격매수 위험' in ez or '크게 초과' in ez:
            vetoes.append(f"진입 위치 '{ez}' — 적정가를 크게 초과")
        if (fs.get('analysis_confidence') or 0) < 50:
            vetoes.append(f"분석 신뢰도 {fs.get('analysis_confidence')}점 (50 미만)")
        # ⚠️ 키는 apply_integrity_gates 가 쓰는 'status' 다.
        #    (예전 코드는 존재하지 않는 'integrity_status' 를 읽어 이 거부권이
        #     한 번도 발동한 적이 없었다 — 죽은 키 계열 4번째)
        if snap.get('status') == 'REVIEW_REQUIRED':
            vetoes.append("데이터 정합성 문제 감지 — 숫자 검증 전까지 판단 보류")

        # ── 결론 ────────────────────────────────────────────────────────
        # ⚠️ 판정 문구도 **엔진의 final_action_title 하나**에서 나와야 한다.
        #    점수는 맞췄는데 문구를 따로 만들면, 같은 종목이 위에서는 '사지 마세요',
        #    아래에서는 '재검토 필요' 로 갈린다 (실제로 그랬다).
        title = str(fs.get('final_action_title') or '').strip()
        # ⚠️ 엔진이 낼 수 있는 모든 판정 문구를 매핑한다. 빠진 문구가 점수 구간
        #    분기로 떨어지면 '조건 확인·관망'(65점)이 '분할매수 검토 가능'으로
        #    둔갑하는 식의 자기모순이 생긴다 (실제로 그랬다).
        TITLE_MAP = {
            '적극적 분할매수 검토': ('BUY', "사도 됩니다 — 적극적 분할매수 검토"),
            '분할매수 검토':       ('ACCUMULATE', "분할매수 검토 가능"),
            '제한적 진입':         ('ACCUMULATE', "제한적으로만 진입"),
            '조건 확인·관망':      ('HOLD', "지금은 사지 마세요 — 조건이 갖춰지면 후보"),
            '신규 매수 보류':      ('HOLD', "지금은 사지 마세요"),
            '비중축소 검토':       ('REDUCE', "비중 축소 검토"),
            '거래 회피':           ('SELL', "사지 마세요 (보유 중이면 축소 검토)"),
            # 하드 정합성 위반 전용 — 신호 간 이견은 여기로 오지 않고 관망으로 화해된다
            '⚠️ 재검토 필요':      ('NO_TRADE', "판정 보류 — 데이터 정합성 문제가 감지됐습니다"),
        }
        if base is None:
            action, headline = 'NO_TRADE', "판단할 데이터가 부족합니다"
        elif title in TITLE_MAP:
            action, headline = TITLE_MAP[title]
            # 거부 조건이 있으면 매수 결론으로 나갈 수 없다
            if vetoes and action in ('BUY', 'ACCUMULATE'):
                action, headline = 'HOLD', "지금은 사지 마세요 — 조건이 갖춰지면 후보"
        elif vetoes:
            action, headline = 'HOLD', "지금은 사지 마세요 — 조건이 갖춰지면 후보"
        elif base >= 72:
            action, headline = 'BUY', "사도 됩니다"
        elif base >= 60:
            action, headline = 'ACCUMULATE', "분할매수 검토 가능"
        elif base >= 45:
            action, headline = 'HOLD', "지금은 관망"
        elif base >= 32:
            action, headline = 'REDUCE', "비중 축소 검토"
        else:
            action, headline = 'SELL', "사지 마세요 (보유 중이면 축소 검토)"

        # ── 관점 간 이견(앙상블 분산) — 확신의 척도 ─────────────────────
        # 이견이 크면 판정을 뒤집는 게 아니라 **확신을 낮춘다** (fractional Kelly:
        # 추정 불확실성이 크면 포지션을 줄인다). BUY 는 소액 분할로 한 단계 하향.
        _scored_vals = [t['score'] for t in tabs if t['score'] is not None]
        disagreement = None
        if len(_scored_vals) >= 3:
            _mu = sum(_scored_vals) / len(_scored_vals)
            disagreement = (sum((v - _mu) ** 2 for v in _scored_vals)
                            / len(_scored_vals)) ** 0.5
        if disagreement is not None and disagreement >= 20 and action == 'BUY':
            action = 'ACCUMULATE'
            headline = "분할매수 검토 가능 — 관점 간 이견이 커 소액 분할만 권장"

        summary = []
        scored = [t for t in tabs if t['score'] is not None]
        if scored:
            top = max(scored, key=lambda t: t['score'])
            low = min(scored, key=lambda t: t['score'])
            summary.append(f"가장 우호적: {top['label']} {top['score']}점")
            summary.append(f"가장 부정적: {low['label']} {low['score']}점")
        if cap_applied:
            summary.append(f"가중합 {raw_sum:.0f}점이 게이트 상한에 걸려 {base}점으로 제한됨")
        if disagreement is not None and disagreement >= 20:
            summary.append(f"관점 간 이견 큼 (표준편차 {disagreement:.0f}점) — 확신을 낮춰 잡으세요")
        # DeMARK 매수 포인트는 '시점' 판단이라 결론 요약에 함께 실어 준다
        _dme_s = fs.get('demark_entry') or {}
        if _dme_s.get('headline'):
            _tl = _dme_s.get('trigger_line')
            # 유효 하한선은 신호가 있을 때만 의미가 있다 — 신호가 없는데 선만
            # 보여주면 진입 근거가 있는 것처럼 읽힌다.
            _show_line = _tl and _dme_s.get('state') in ('COMPLETE', 'SETUP_DONE', 'FORMING')
            summary.append(
                "DeMARK 매수 포인트: " + _dme_s['headline']
                + (f" · 유효 하한 {_tl:,.0f}원"
                   f"({'지지 유지' if _dme_s.get('valid') else '이탈 — 무효'})"
                   if _show_line else ""))
        for _n in (fs.get('soft_conflict_notes') or []):
            summary.append("신호 이견 화해: " + str(_n))
        if vetoes:
            summary.append("거부 조건 " + str(len(vetoes)) + "건이 매수 결론을 막고 있습니다")
        na = [t['label'] for t in tabs if t['score'] is None]
        if na:
            summary.append("산출 불가 관점: " + ", ".join(na))

        return {
            'headline': headline,
            'action': action,
            'score': None if base is None else int(round(base)),
            'title': fs.get('final_action_title'),
            'composition': composition,        # 실제 점수를 만든 산식
            'raw_weighted_sum': round(raw_sum, 1),
            'cap': cap,
            'cap_applied': cap_applied,
            'gate_reason': fs.get('gate_reason'),
            'vetoes': vetoes,
            'summary': summary,
            'disagreement': (None if disagreement is None else round(disagreement, 1)),
            'tabs': tabs,                      # 관점별 독립 판정 (합산하지 않음)
        }

    @staticmethod
    def build_demark_entry(dm, curr_price):
        """
        DeMARK 9-13 신호 → '매수 포인트' 한 덩어리. 종합 결론에 그대로 싣는다.

        DeMARK 는 추세 소진을 세는 기법이라 '언제·어느 선에서' 가 핵심이다:
          · Buy Setup 9 → 매도 소진 준비 완료
          · Buy Countdown 13 → 소진 확인, 반전 진입 시점
          · TDST 지지선 → 이 선을 지키는 동안만 매수 신호가 유효하다
        그래서 신호 상태와 함께 **유효 하한선(TDST 지지)** 을 같이 내보낸다.
        산출 불가일 때 숫자를 만들지 않는다.

        반환: {'state','headline','trigger_line','valid','detail','label'} 또는 None
        """
        if not dm or dm.get('demark_label', '').startswith('산출 불가'):
            return None
        buy_setup = int(dm.get('buy_setup_count', 0) or 0)
        buy_cd = int(dm.get('buy_countdown', 0) or 0)
        tdst = dm.get('tdst_support')
        label = dm.get('demark_label', '중립')
        bull = int(dm.get('bullish_score', 0) or 0)
        bear = int(dm.get('bearish_score', 0) or 0)

        # TDST 지지선 유지 여부 — 매수 신호의 유효 조건
        valid = None
        if tdst and curr_price:
            valid = float(curr_price) >= float(tdst)

        if buy_cd >= 13:
            state = 'COMPLETE'
            headline = "매수 카운트다운 13 완성 — 소진 확인"
        elif buy_setup >= 9:
            state = 'SETUP_DONE'
            headline = f"매수 셋업 9 완성 · 카운트다운 {buy_cd}/13 진행"
        elif buy_setup > 0:
            state = 'FORMING'
            headline = f"매수 셋업 {buy_setup}/9 진행 — 완성까지 {9 - buy_setup}봉"
        elif bear > bull:
            state = 'NONE'
            headline = "매수 신호 없음 — 매도 소진 카운트가 우세"
        else:
            state = 'NONE'
            headline = "매수 신호 없음 — 셋업 미시작"

        if state in ('COMPLETE', 'SETUP_DONE'):
            detail = ("TDST 지지선을 지키는 동안 유효합니다. 이탈하면 신호는 무효입니다."
                      if tdst else "TDST 지지선을 산출하지 못해 유효 하한을 제시할 수 없습니다.")
        elif state == 'FORMING':
            detail = "아직 셋업이 완성되지 않아 진입 신호가 아닙니다. 완성 후 판단하세요."
        else:
            detail = "DeMARK 기준으로는 지금 매수 진입 근거가 없습니다."

        return {
            'state': state,
            'headline': headline,
            'trigger_line': (float(tdst) if tdst else None),
            'valid': valid,
            'detail': detail,
            'label': label,
            'buy_setup': buy_setup,
            'buy_countdown': buy_cd,
        }

    @staticmethod
    def build_easy_advice(fs, verdict, curr_price, user_avg=None, user_qty=None):
        """
        사용자 상황별 '아주 쉬운 결론'. 신규 매수자와 보유자의 기준을 절대 섞지 않는다.

        반환:
          new_buyer: {'emoji','line','detail'(쉬운 문단),'prices'{...}}
          holder   : 평단가·수량 입력 시 {'emoji','line','detail','ret_pct','prices'{...}}
        모든 가격·조건은 엔진이 이미 계산한 값만 조합한다 — 여기서 새 숫자를
        만들지 않는다. 산출 불가면 그대로 '판단 보류'로 말한다.
        """
        score = (verdict or {}).get('score')
        action = (verdict or {}).get('action')
        vetoes = list((verdict or {}).get('vetoes') or [])
        rec = fs.get('recommended_buy_price')
        chase_max = fs.get('buy_entry_max')
        t1, t2 = fs.get('target_tech_1st'), fs.get('target_tech_2nd')
        stop = fs.get('stop_loss_price')
        m10 = float(fs.get('m10_disparity', 0) or 0)
        overheat = m10 > 25.0
        downtrend = m10 < 0
        cb = fs.get('calibration_band') or {}

        def w(v):
            return f"{v:,.0f}원" if v is not None else "산출 불가"

        # 과거 실측으로 '틀릴 가능성'을 함께 말한다 (표본 부족이면 말하지 않는다)
        if cb.get('hit_rate') is not None and cb.get('n', 0) >= 30:
            odds = (f"비슷한 점수({cb['lo']}~{cb['hi']}점)의 과거 사례 {cb['n']}건 중 "
                    f"{cb['hit_rate']:.0f}%가 목표가에 먼저 닿았습니다 "
                    f"(틀릴 가능성 약 {100 - cb['hit_rate']:.0f}%).")
        else:
            odds = "이 점수대는 과거 사례가 적어 적중률을 제시하지 않습니다."

        # ── 신규 매수자 ────────────────────────────────────────────────
        if score is None:
            nb = {'emoji': '⚪', 'line': '데이터가 부족해 판단할 수 없습니다.',
                  'detail': "분석에 필요한 데이터가 모자랍니다. 무리해서 사지 마세요."}
        elif action in ('BUY', 'ACCUMULATE') and not vetoes:
            _half = ((curr_price + t1) / 2 if curr_price and t1 and t1 > curr_price
                     else None)
            nb = {'emoji': '🟢', 'line': '지금 사도 됩니다 (나눠서).',
                  'detail': (f"한 번에 다 사지 말고 나눠 사세요. 1차는 지금, "
                             f"손절선(잃음을 멈추는 선) {w(stop)}을 지키세요. "
                             f"1차 목표(먼저 일부 이익실현) {w(t1)}, 2차 목표 {w(t2)}. "
                             + (f"가격이 {w(_half)}(목표의 절반)에 닿으면 손절선을 "
                                f"본전(산 가격)으로 올리세요 — 1,950건 검증에서 "
                                f"손실 확률을 약 1/3 줄였습니다. " if _half else "")
                             + odds)}
        elif rec is not None and curr_price and curr_price > rec:
            nb = {'emoji': '🟡', 'line': f'{w(rec)} 이하로 내려올 때만 사세요.',
                  'detail': (f"지금 가격({w(curr_price)})은 계산된 매수 구간보다 높습니다. "
                             f"쫓아가서 사지 마세요(추격매수 금지"
                             + (f" — {w(chase_max)} 위에서는 특히 금지" if chase_max else "")
                             + f"). {w(rec)} 아래로 오면 나눠서 검토하세요. {odds}")}
        elif rec is None:
            nb = {'emoji': '⚪', 'line': '분석 신뢰도가 낮아 판단을 보류하세요.',
                  'detail': "적정 매수 가격을 믿을 만하게 계산하지 못했습니다. "
                            "이 종목은 근거가 더 생길 때까지 관망이 안전합니다."}
        else:
            _why = vetoes[0] if vetoes else "매수 조건 미충족"
            nb = {'emoji': '🟡', 'line': '지금은 사지 마세요 — 조건이 충족될 때까지 기다리세요.',
                  'detail': (f"막는 조건: {_why}. 가격은 매수 구간({w(rec)} 이하)이어도 "
                             f"이 조건이 풀려야 삽니다. {odds}")}
        nb['prices'] = {'권장 매수가(1차 분할)': rec,
                        '2차 분할가': (rec - 0.5 * (rec - stop)
                                   if rec is not None and stop is not None and rec > stop
                                   else None),
                        '추격매수 금지선': chase_max,
                        '1차 목표가': t1, '2차 목표가': t2,
                        '손절가(신규 진입 기준으로 재설정)': stop,
                        '예상 보유기간': '약 20거래일'}

        # ── 보유자 ────────────────────────────────────────────────────
        holder = None
        if user_avg and user_avg > 0 and curr_price:
            ret = (curr_price / float(user_avg) - 1.0) * 100.0
            add_ok = (score is not None and score >= 58 and not downtrend
                      and not vetoes and rec is not None and curr_price <= rec)
            if stop is not None and curr_price < stop:
                holder = {'emoji': '🔴',
                          'line': '손절 기준을 이탈했습니다 — 정리(손절)를 검토하세요.',
                          'detail': (f"현재가가 손절선 {w(stop)} 아래입니다. "
                                     f"현재 {ret:+.1f}%. 손실이 더 커지기 전에 정리하는 것이 "
                                     f"원칙입니다. 반등을 기다리는 선택은 '기대'이지 근거가 아닙니다.")}
            elif ret > 0 and overheat:
                holder = {'emoji': '🟠',
                          'line': '수익 중 — 일부 매도(절반 이익실현)를 권합니다.',
                          'detail': (f"현재 {ret:+.1f}% 수익. 단기 과열 신호(장기 추세선 대비 "
                                     f"+{m10:.0f}%)가 강합니다. 절반은 지금 팔고, 나머지는 "
                                     f"손절선을 {w(stop)}으로 올려 지키며 {w(t2)}까지 보유하세요.")}
            elif ret > 0:
                _be_note = ("" if not (stop is not None and float(user_avg) > stop)
                            else f"이미 수익 중이니 손절선을 본전({w(float(user_avg))}) "
                                 f"위로 올려 두는 것도 좋습니다 — 이익을 손실로 되돌리지 "
                                 f"않는 검증된 운용입니다. ")
                holder = {'emoji': '🔵',
                          'line': '계속 보유하세요 — 목표가까지, 손절가는 지키면서.',
                          'detail': (f"현재 {ret:+.1f}% 수익. {w(t1)} 도달 시 일부 매도, "
                                     f"{w(t2)}가 최종 목표입니다. {_be_note}종가가 {w(stop)} 아래로 "
                                     f"내려가면 원칙대로 정리하세요. 추가 매수는 "
                                     + ("가능 구간입니다 (나눠서)." if add_ok else "지금은 하지 마세요."))}
            elif add_ok:
                holder = {'emoji': '🔵',
                          'line': f'보유 유지 — 추가 매수는 {w(rec)} 이하에서만 나눠서.',
                          'detail': (f"현재 {ret:+.1f}%. 추세가 살아 있고 매수 구간 안이라 "
                                     f"분할 추가매수를 검토할 수 있습니다. 단, 손절선 {w(stop)}은 "
                                     f"반드시 지키세요. {odds}")}
            else:
                _deep = ret <= -15.0
                holder = {'emoji': '🟠',
                          'line': ('물타기(평단 낮추기 목적의 추가 매수)는 하지 마세요.'
                                   if not _deep else
                                   '추가 매수 금지 — 반등 시 비중 축소를 검토하세요.'),
                          'detail': (f"현재 {ret:+.1f}% 손실. "
                                     + ("하락 추세가 끝나지 않았습니다. " if downtrend else "")
                                     + (f"기술적 반등이 나오면 {w(t1)} 부근에서 비중을 줄이는 "
                                        f"쪽을 검토하세요. " if _deep else "")
                                     + f"평단을 낮추려는 추가 매수는 손실을 키우는 경우가 더 "
                                       f"많습니다. 추세 회복({'월 추세선 회복' if downtrend else '조건 충족'})과 "
                                       f"거래량 확인 후에만 재검토하세요. 종가 {w(stop)} 이탈 시 정리.")}
            holder['ret_pct'] = round(ret, 2)
            holder['prices'] = {'평균 매수가': float(user_avg),
                                '현재가': float(curr_price),
                                '손절가(보유 기준)': stop,
                                '반등 시 축소 가격': t1, '최종 목표가': t2,
                                '추가 매수 허용가': (rec if add_ok else None)}

        return {'new_buyer': nb, 'holder': holder, 'odds_note': odds}

    @staticmethod
    def classify_asset_type(name, is_fund):
        """
        자산 유형: STOCK / ETF / ETF_LEV / ETF_INV.

        레버리지·인버스는 같은 ETF 라도 성질이 다르다:
          · 인버스는 시장과 반대로 움직여 시장 대비 상대 모멘텀이 무의미하고,
          · 레버리지·인버스 모두 일일 재조정 복리손실(volatility decay)이 있어
            20일 보유 전제의 판정에 별도 경고와 비중 축소가 필요하다.
        이름 기반 판별이다 — 상품 분류 공시가 미연동이므로 그 한계를 명시한다.
        """
        nm = str(name or '')
        if not is_fund:
            return 'STOCK'
        if '인버스' in nm:
            return 'ETF_INV'
        if '레버리지' in nm or '2X' in nm.upper().replace(' ', ''):
            return 'ETF_LEV'
        return 'ETF'

    @staticmethod
    def momentum_12_1(closes):
        """
        12-1 개월 가격 모멘텀 (Jegadeesh–Titman 1993): 최근 1개월을 뺀
        지난 12개월 수익률(%). 최근 1개월은 단기 반전이 있어 제외하는 것이
        문헌 표준이다. 표본(253봉) 부족이면 None — 만들어내지 않는다.
        """
        try:
            arr = np.asarray(closes, dtype=float)
            arr = arr[~np.isnan(arr)]
            if len(arr) < 253 or arr[-252] <= 0:
                return None
            return float((arr[-22] / arr[-252] - 1.0) * 100.0)
        except Exception:
            return None

    # ── 기업유형 사전 ────────────────────────────────────────────────────
    ARCHETYPES = {
        'A_STABLE': '안정적 흑자·현금창출형',
        'B_CYCLICAL': '경기민감·자본집약 제조형',
        'C_FINANCIAL': '금융·보험·증권형',
        'D_PLATFORM': '플랫폼·네트워크·핀테크형',
        'E_BIOTECH': '바이오·신약·기술이전형',
        'F_DEFICIT': '적자 고성장·수익성 전환형',
        'G_HOLDING': '자산가치·지주회사형',
        'H_TURNAROUND': '턴어라운드·구조조정형',
    }

    # 업종 키워드 → 유형 사전확률. 종목명·티커가 아니라 KRX 산업분류만 사용한다.
    SECTOR_PRIORS = (
        (('은행', '증권', '보험', '금융', '카드', '캐피탈', '창업투자'),
         {'C_FINANCIAL': 0.85, 'A_STABLE': 0.10, 'G_HOLDING': 0.05}),
        (('제약', '생물공학', '바이오', '생명과학', '의료용품'),
         {'E_BIOTECH': 0.70, 'A_STABLE': 0.15, 'F_DEFICIT': 0.15}),
        (('소프트웨어', '인터넷', '양방향미디어', 'IT서비스', '게임', '엔터테인먼트', '광고'),
         {'D_PLATFORM': 0.70, 'A_STABLE': 0.20, 'F_DEFICIT': 0.10}),
        (('반도체', '디스플레이', '전자장비', '컴퓨터', '통신장비', '휴대폰', '전기제품', '전기장비'),
         {'B_CYCLICAL': 0.55, 'A_STABLE': 0.25, 'F_DEFICIT': 0.20}),
        (('자동차', '자동차부품', '조선', '기계', '건설', '중공업', '항공', '운송', '해운', '방산'),
         {'B_CYCLICAL': 0.70, 'A_STABLE': 0.20, 'H_TURNAROUND': 0.10}),
        (('화학', '철강', '비철금속', '정유', '석유', '가스', '에너지', '종이', '시멘트', '광물'),
         {'B_CYCLICAL': 0.75, 'A_STABLE': 0.15, 'H_TURNAROUND': 0.10}),
        (('식품', '음료', '담배', '화장품', '생활용품', '가정용품', '섬유', '의복', '유통', '소매', '백화점'),
         {'A_STABLE': 0.65, 'B_CYCLICAL': 0.25, 'D_PLATFORM': 0.10}),
        (('전력', '유틸리티', '가스유틸리티', '수도', '도로', '철도', '인프라'),
         {'A_STABLE': 0.55, 'B_CYCLICAL': 0.35, 'G_HOLDING': 0.10}),
        (('지주', '複合', '복합기업', '부동산', '리츠', '임대'),
         {'G_HOLDING': 0.75, 'A_STABLE': 0.15, 'B_CYCLICAL': 0.10}),
        (('통신서비스', '무선통신', '유선통신'),
         {'A_STABLE': 0.70, 'D_PLATFORM': 0.20, 'B_CYCLICAL': 0.10}),
        (('교육', '호텔', '레저', '여행', '음식료', '병원', '건강관리'),
         {'A_STABLE': 0.55, 'D_PLATFORM': 0.25, 'B_CYCLICAL': 0.20}),
    )

    @staticmethod
    def weighted_quantile(values, weights, q):
        """신뢰도 가중 분위수. values 는 오름차순 정렬되어 있어야 한다."""
        v = np.asarray(values, dtype=float)
        w = np.asarray(weights, dtype=float)
        if len(v) == 0:
            return float('nan')
        if len(v) == 1 or w.sum() <= 0:
            return float(v[0] if len(v) == 1 else np.quantile(v, q))
        order = np.argsort(v)
        v, w = v[order], w[order]
        cw = np.cumsum(w) - 0.5 * w
        cw /= w.sum()
        return float(np.interp(q, cw, v))

    def sector_archetype_prior(self, sector):
        """업종명 → 유형 사전확률. 매칭 실패 시 None (분류 근거 없음)."""
        if not sector:
            return None
        s = re.sub(r'\s', '', str(sector))
        for keywords, prior in self.SECTOR_PRIORS:
            for kw in keywords:
                if kw in s:
                    return dict(prior)
        return None

    def evaluate_valuation_metric(self, tech_df, fund_df, symbol=None):
        """
        [v27 확정] 확률적 기업유형 혼합 & 유효 가치평가 모델 자동 동적 라우팅 엔진
        - 단일 유형 강제 분류 대신 8대 기업유형 소속 확률(Probability Vector) 산출
        - 분류 확률 기반 모델 가중치 정밀 혼합 (Blended Model Weights)
        - 모델 유효성 검사(PER/EV-EBITDA/FCFF/RIM/rNPV 등) 수행 후 불허 모델 0% 자동 제외 및 재정규화
        - 100% 결정론적(Deterministic) 연산 & Point-in-Time 무결성 보장
        """
        if tech_df is None or tech_df.empty:
            return {}
            
        curr_price = float(tech_df['adj_close'].iloc[-1])
        latest_fund = fund_df.iloc[-1].to_dict() if (fund_df is not None and len(fund_df) > 0) else {}
        
        from bitemporal_engine import STOCK_METRICS_DB
        sm_meta = STOCK_METRICS_DB.get(symbol, {}) if symbol else {}

        # ── ETF·ETN 은 펀더멘털 밸류에이션이 성립하지 않는다 ────────────────
        # 펀드에는 EPS·BPS·ROE 가 없다. 억지로 돌리면 `BPS = 가격×0.8` 폴백이
        # 걸려 KODEX 200 에 '적정가 90,069원' 같은 근거 없는 값이 붙는다.
        # 지표를 지어내는 대신 산출을 건너뛰고, 기술적·경로 분석만 유효하다고 밝힌다.
        if sm_meta.get('is_fund'):
            return {
                'is_fund': True,
                'archetype_label': 'ETF·ETN (펀드)',
                'type_probs': None,
                'model_results': {},
                'target_fundamental': None,
                'displayed_fair_value': None,
                'core_range': None, 'wide_range': None,
                'upside_pct': None,
                'fair_value_confidence': 0.0,
                'fair_value_status': "UNCALCULATED",
                'fair_value_status_note': (
                    "ETF·ETN 은 개별 기업이 아니라 펀드라서 EPS·BPS·ROE 기반 적정가가 "
                    "성립하지 않습니다. 순자산가치(NAV)·괴리율은 연동되어 있지 않으므로 "
                    "적정가를 산출하지 않습니다. **추세·경로·표본 분석은 그대로 유효합니다.**"),
                'buy_price_checks': [],
                'recommended_buy_price': None,
                'input_metrics': {}, 'missing_inputs': ['EPS', 'BPS', 'ROE', 'PER', 'PBR'],
            }


        def _pick(*vals):
            """None 을 건너뛰고 첫 유효값을 float 로 반환. 전부 None 이면 None."""
            for v in vals:
                if v is not None and not (isinstance(v, float) and np.isnan(v)):
                    try:
                        return float(v)
                    except (TypeError, ValueError):
                        continue
            return None

        # 미수신 지표를 리터럴 기본값으로 채우지 않는다. 어떤 항목이 비었는지 기록한다.
        # ⚠️ 접두사 in_ 는 '입력 지표'라는 뜻. 아래 모델 섹션의 per_val / pbr_val 은
        #    'PER 모델이 산출한 적정가'라서 이름이 겹치면 안 된다.
        in_debt = _pick(sm_meta.get('debt'), latest_fund.get('debt_ratio'))
        in_pbr = _pick(sm_meta.get('pbr'), latest_fund.get('pbr'), latest_fund.get('pb_ratio'))
        in_per = _pick(sm_meta.get('per'), latest_fund.get('per'), latest_fund.get('pe_ratio'))
        in_roe = _pick(sm_meta.get('roe'), latest_fund.get('roe'))
        in_bps = _pick(sm_meta.get('bps'), latest_fund.get('bps'))
        in_eps = _pick(sm_meta.get('eps'), latest_fund.get('eps'), latest_fund.get('eps_ttm'))

        missing_inputs = [nm for nm, v in
                          (('부채비율', in_debt), ('PBR', in_pbr), ('PER', in_per),
                           ('ROE', in_roe), ('BPS', in_bps), ('EPS', in_eps)) if v is None]

        # 분류 산식이 동작하도록 중립 대체값을 쓰되, 위 missing_inputs 로 신뢰도를 깎는다.
        debt_ratio = in_debt if in_debt is not None else 100.0
        pbr = in_pbr if in_pbr is not None else 1.0
        per = in_per if in_per is not None else 15.0
        roe = in_roe if in_roe is not None else 10.0
        bps = in_bps if in_bps is not None else (curr_price * 0.8 if curr_price > 0 else 1000.0)
        eps = in_eps if in_eps is not None else (curr_price / 15.0 if curr_price > 0 else 1.0)
        
        # ---------------------------------------------------------
        # 1. 기업유형 확률분류 — 업종(1차) + 재무특성(2차)
        #    구버전은 재무비율만 봤다. 그 결과 '적자 + 고PBR' 이면 배터리·소재 제조기업도
        #    바이오·신약형으로 분류되어 근거 없는 rNPV 가 적용됐다.
        # ---------------------------------------------------------
        sector = sm_meta.get('sector')
        sector_prior = self.sector_archetype_prior(sector)   # 업종 → 유형 사전확률
        sector_known = sector_prior is not None

        # 재무특성 점수 (업종을 모를 때의 보조 신호, 알 때는 미세조정)
        fin = {k: 0.1 for k in self.ARCHETYPES}
        if debt_ratio > 250.0: fin['C_FINANCIAL'] += 6.0
        if pbr < 0.65 and 0 < per < 7.0 and roe > 6.0 and debt_ratio > 180.0: fin['C_FINANCIAL'] += 6.0
        if per > 18.0 and pbr > 1.6 and roe > 4.0 and eps > 0: fin['D_PLATFORM'] += 4.0
        if debt_ratio > 90.0 and pbr < 1.4 and roe > 8.0: fin['B_CYCLICAL'] += 6.0
        if pbr < 1.0 and debt_ratio > 100.0 and 0 < per < 12.0: fin['B_CYCLICAL'] += 4.0
        if pbr < 0.55 and debt_ratio < 100.0 and roe < 8.0: fin['G_HOLDING'] += 6.0
        if pbr < 0.4: fin['G_HOLDING'] += 4.0
        # 적자는 '유형'이 아니라 '상태'다. 업종을 아는 경우 유형을 덮어쓰지 않는다.
        if (eps < 0 or roe < 0) and pbr >= 1.2: fin['F_DEFICIT'] += (2.0 if sector_known else 8.0)
        if roe >= 0 and roe < 6.0 and pbr < 0.8 and debt_ratio > 120.0: fin['H_TURNAROUND'] += 5.0
        if roe >= 9.0 and debt_ratio < 80.0 and eps > 0: fin['A_STABLE'] += 6.0
        if eps > 0 and 0 < per < 20.0 and debt_ratio < 100.0: fin['A_STABLE'] += 4.0
        # 바이오 가점은 업종이 실제로 제약·바이오일 때만 준다 (재무비율만으로 부여 금지)
        if sector_known and sector_prior.get('E_BIOTECH', 0) > 0.2:
            if eps <= 0 and pbr > 3.0: fin['E_BIOTECH'] += 6.0
            if per > 45.0 and pbr > 4.5: fin['E_BIOTECH'] += 4.0

        fin_total = sum(fin.values())
        fin_probs = {k: v / fin_total for k, v in fin.items()}

        if sector_known:
            # 업종 70% + 재무 30% — 업종이 유형의 주된 근거다
            type_probs = {k: sector_prior.get(k, 0.0) * 0.70 + fin_probs.get(k, 0.0) * 0.30
                          for k in self.ARCHETYPES}
            classification_basis = f"업종 '{sector}' + 재무특성"
            classification_confidence = 80.0
        else:
            type_probs = fin_probs
            classification_basis = "재무특성만 (업종 미수신)"
            classification_confidence = 40.0

        tot = sum(type_probs.values()) or 1.0
        type_probs = {k: v / tot for k, v in type_probs.items()}

        dominant_code = max(type_probs, key=type_probs.get)
        dominant_p = type_probs[dominant_code]
        # 최상위 확률이 낮으면 유형을 확정하지 않는다
        if dominant_p < 0.35:
            classification_confidence = min(classification_confidence, 45.0)
            classification_uncertain = True
        else:
            classification_uncertain = False

        type_names = self.ARCHETYPES
        ent_class = (f"{type_names[dominant_code]} ({dominant_p*100:.0f}% 주도)"
                     + (" · 분류 불확실" if classification_uncertain else ""))

        # ---------------------------------------------------------
        # 2. 기업 유형별 기본 가중치 매트릭스 & 혼합 가중치(Blended Weights) 연산
        # ---------------------------------------------------------
        default_model_matrix = {
            'A_STABLE':     {'PER': 0.30, 'FCFF': 0.30, 'EV_EBITDA': 0.25, 'PBR_ROE': 0.15},
            'B_CYCLICAL':   {'PER': 0.20, 'EV_EBITDA': 0.30, 'FCFF': 0.30, 'SOTP': 0.20},
            'C_FINANCIAL':  {'RIM': 0.40, 'PBR_ROE': 0.35, 'DDM': 0.15, 'SOTP': 0.10},
            'D_PLATFORM':   {'SOTP': 0.35, 'EV_GP': 0.25, 'DCF_SCENARIO': 0.25, 'NET_CASH': 0.15},
            'E_BIOTECH':    {'rNPV': 0.50, 'PLATFORM_rNPV': 0.20, 'CASH_ASSETS': 0.20, 'RELATIVE': 0.10},
            'F_DEFICIT':    {'EV_SALES': 0.25, 'EV_GP': 0.20, 'DCF_SCENARIO': 0.35, 'NET_CASH': 0.20},
            'G_HOLDING':    {'NAV': 0.50, 'SOTP': 0.30, 'NORMALIZED_CF': 0.20},
            'H_TURNAROUND': {'EV_EBITDA': 0.30, 'FCFF': 0.30, 'NAV': 0.20, 'PER': 0.20}
        }
        
        # 모델별 혼합 가중치 산출
        blended_weights = {}
        for code, prob in type_probs.items():
            matrix = default_model_matrix.get(code, {})
            for m_name, m_weight in matrix.items():
                blended_weights[m_name] = blended_weights.get(m_name, 0.0) + (m_weight * prob)

        # ---------------------------------------------------------
        # 3. 모델별 개별 적정가 산출 & 유효성 검사 (Validity Check)
        # ---------------------------------------------------------
        norm_eps = max(1.0, eps * 1.05 if roe > 10 else (eps if eps > 0 else bps * max(0.02, roe/100.0)))
        ebitda_ps = norm_eps * 1.45 + bps * 0.04
        wacc = 0.085
        terminal_g = 0.02
        
        model_results = {}
        
        # A. PER 모델
        per_valid = (norm_eps > 0 and per > 0 and type_probs['E_BIOTECH'] < 0.5 and type_probs['F_DEFICIT'] < 0.5)
        per_val = norm_eps * (8.15 if type_probs['B_CYCLICAL'] > 0.4 else (17.5 if type_probs['A_STABLE'] > 0.4 else 12.0))
        model_results['PER'] = {'val': per_val, 'weight': blended_weights.get('PER', 0.0), 'valid': per_valid, 'name': '정상화 PER'}
        
        # B. EV/EBITDA 모델 (금융업 부채 차감 무효 처리!)
        ev_ebitda_valid = (ebitda_ps > 0 and type_probs['C_FINANCIAL'] < 0.4)
        if type_probs['B_CYCLICAL'] > 0.4:
            ev_val = (ebitda_ps * 5.0) + bps * 0.15 # 금융부채 전액 차감 제외 & 지분/순현금 반영
        else:
            ev_val = (ebitda_ps * 7.5) + (bps * 0.15)
        model_results['EV_EBITDA'] = {'val': ev_val, 'weight': blended_weights.get('EV_EBITDA', 0.0), 'valid': ev_ebitda_valid, 'name': 'EV/EBITDA'}
        
        # C. FCFF DCF 모델 (금융업 자동 제외)
        fcff_valid = (norm_eps > 0 and type_probs['C_FINANCIAL'] < 0.4)
        fcff_ps = norm_eps * 0.85
        fcff_val = ((fcff_ps * 1.03) / (wacc - terminal_g)) * 0.65 + (bps * 0.15 if type_probs['B_CYCLICAL']>0.4 else 0.0)
        model_results['FCFF'] = {'val': fcff_val, 'weight': blended_weights.get('FCFF', 0.0), 'valid': fcff_valid, 'name': 'FCFF (DCF)'}
        
        # D. PBR-ROE / RIM 모델 (금융업 우세 모델)
        pbr_roe_valid = (bps > 0 and roe > 0)
        pbr_val = bps * (1.0 + (roe - 7.0) / 10.0) if roe > 7.0 else bps * max(0.4, pbr)
        model_results['PBR_ROE'] = {'val': pbr_val, 'weight': blended_weights.get('PBR_ROE', 0.0) + blended_weights.get('RIM', 0.0), 'valid': pbr_roe_valid, 'name': 'PBR-ROE / RIM'}
        
        # E. DDM (배당할인모형)
        ddm_valid = (bps > 0 and roe > 0)
        ddm_val = bps * 0.85 * 1.03 / (wacc - 0.03) * 0.08
        model_results['DDM'] = {'val': ddm_val, 'weight': blended_weights.get('DDM', 0.0), 'valid': ddm_valid, 'name': '배당할인모형(DDM)'}
        
        # F. SOTP / NAV (복합기업 및 지주형)
        sotp_valid = (bps > 0)
        sotp_val = (bps * 0.88 + bps * 0.27 + bps * 0.20 + bps * 0.15) * 0.85 if type_probs['B_CYCLICAL']>0.4 else bps * 1.25 * 0.85
        model_results['SOTP'] = {'val': sotp_val, 'weight': blended_weights.get('SOTP', 0.0) + blended_weights.get('NAV', 0.0), 'valid': sotp_valid, 'name': 'SOTP / 조정 NAV'}
        
        # G. rNPV — 파이프라인 데이터가 있어야만 성립한다.
        #    임상단계·성공확률·출시시점·마일스톤·로열티 중 어느 것도 연동되어 있지 않으므로
        #    현재 빌드에서는 항상 무효다. (구버전은 'PBR>4' 라는 이유만으로 적용해
        #     제조기업에 832,857원 같은 근거 없는 값을 34% 가중치로 반영했다)
        pipeline_data = latest_fund.get('pipeline_projects')
        rnpv_valid = bool(pipeline_data)
        rnpv_val = bps * 8.5 + norm_eps * 15.0
        model_results['rNPV'] = {
            'val': rnpv_val,
            'weight': blended_weights.get('rNPV', 0.0) + blended_weights.get('PLATFORM_rNPV', 0.0),
            'valid': rnpv_valid, 'name': '파이프라인 rNPV',
            'exclusion_reason': None if rnpv_valid else "검증 가능한 파이프라인 데이터 없음 (임상단계·성공확률·출시시점 미연동)"}
        
        # H. EV/Sales & EV/Gross Profit (플랫폼 및 적자 고성장)
        ev_s_valid = (bps > 0)
        ev_s_val = bps * 1.8 + ebitda_ps * 10.0
        model_results['EV_GP'] = {'val': ev_s_val, 'weight': blended_weights.get('EV_GP', 0.0) + blended_weights.get('EV_SALES', 0.0), 'valid': ev_s_valid, 'name': 'EV/Sales & GP'}
        
        # I. DCF 시나리오 & 현금자산
        dcf_s_valid = (bps > 0)
        dcf_s_val = (ebitda_ps * 0.8) / (wacc - 0.03) + bps * 0.8
        model_results['DCF_SCENARIO'] = {'val': dcf_s_val, 'weight': blended_weights.get('DCF_SCENARIO', 0.0) + blended_weights.get('CASH_ASSETS', 0.0) + blended_weights.get('NET_CASH', 0.0) + blended_weights.get('NORMALIZED_CF', 0.0) + blended_weights.get('RELATIVE', 0.0), 'valid': dcf_s_valid, 'name': '시나리오 DCF & 순현금'}

        # ---------------------------------------------------------
        # 4. 불허/유효하지 않은 모델 0% 자동 제외 및 가중치 재정규화 (Re-normalization)
        # ---------------------------------------------------------
        valid_models = []
        for k, m in model_results.items():
            if not m['valid'] or m['val'] <= 0 or m['weight'] <= 0.001:
                m['weight'] = 0.0
                if m['valid'] and m['val'] <= 0:
                    m.setdefault('exclusion_reason', "산출값이 0 이하")
                elif m['valid']:
                    m.setdefault('exclusion_reason', "해당 기업유형에서 가중치 0%")
                m['valid'] = False
            else:
                valid_models.append(m)

        # ── 극단값 자동 검토 ────────────────────────────────────────────
        # 유효모델 중앙값에서 크게 벗어난 값은 신뢰도를 깎고, 2배 이상 벗어나면 제외한다.
        if len(valid_models) >= 3:
            med0 = float(np.median([m['val'] for m in valid_models]))
            survivors = []
            for m in valid_models:
                dev = abs(m['val'] / (med0 + 1e-9) - 1.0)
                m['deviation_from_median'] = round(dev, 3)
                if dev > 1.00:
                    m['weight'] = 0.0
                    m['valid'] = False
                    m['status'] = 'EXCLUDED_EXTREME_OUTLIER'
                    m['exclusion_reason'] = f"중앙값 대비 {dev*100:.0f}% 이탈 (극단값)"
                elif dev > 0.50:
                    m['weight'] *= 0.50
                    m['status'] = 'OUTLIER_REVIEW'
                    survivors.append(m)
                else:
                    m['status'] = 'OK'
                    survivors.append(m)
            valid_models = [m for m in survivors if m['weight'] > 0.001]


        if not valid_models:
            return {
                'target_fundamental': curr_price, 'base_fair_value': curr_price,
                'displayed_fair_value': None, 'preliminary_range_str': "미산출 (유효 모델 없음)",
                'recommended_buy_price': None, 'margin_of_safety_pct': 15.0,
                'market_adjustment_pct': 0.0, 'upside_pct': None, 'raw_upside_pct': None,
                'upside_eval': "모델 불확실성이 커 가치판단 보류",
                'fair_value_confidence': 0.0, 'enterprise_class': ent_class,
                'fair_value_status_note': "유효 가치평가 모델 0개 — 산출 불가",
                'type_probabilities': type_probs,
                'model_results': model_results, 'fair_value_status': "UNCALCULATED",
                'roe': float(roe), 'per': float(per), 'pbr': float(pbr),
                'bps': float(bps), 'eps': float(eps)
            }
            
        total_valid_weight = sum([m['weight'] for m in valid_models])
        for m in valid_models:
            m['weight'] /= total_valid_weight

        # ---------------------------------------------------------
        # 5. 가중중앙값 (Weighted Median) & 베이지안 윈저화 수축 캘리브레이션
        # ---------------------------------------------------------
        weighted_avg = sum([m['val'] * m['weight'] for m in valid_models])
        sorted_models = sorted(valid_models, key=lambda x: x['val'])

        vals = np.array([m['val'] for m in sorted_models], dtype=float)
        wts = np.array([m['weight'] for m in sorted_models], dtype=float)
        weighted_median = float(self.weighted_quantile(vals, wts, 0.50))

        # 표시 범위는 모델 최솟값~최댓값이 아니라 신뢰도 가중 분위수를 쓴다.
        # 구버전은 16,572원 ~ 832,857원 같은 극단값 폭을 '예비 범위'로 내보냈다.
        q25 = float(self.weighted_quantile(vals, wts, 0.25))
        q75 = float(self.weighted_quantile(vals, wts, 0.75))
        q10 = float(self.weighted_quantile(vals, wts, 0.10))
        q90 = float(self.weighted_quantile(vals, wts, 0.90))
        core_range = (q25, q75)
        wide_range = (q10, q90)
        preliminary_range_str = f"{q25:,.0f}원 ~ {q75:,.0f}원"

        # 중앙값과 가중평균의 괴리는 모델 합의도 저하 신호
        median_mean_gap = abs(weighted_avg / (weighted_median + 1e-9) - 1.0)


        # ---------------------------------------------------------
        # 6. 베이지안 아웃라이어 수축 캘리브레이션 (산출 보류 0% 보장)
        # ---------------------------------------------------------
        # 원시 적정가 산출
        raw_target_val = weighted_median * 0.98
        raw_upside_pct = (raw_target_val / (curr_price + 1e-8) - 1.0) * 100.0

        # ── 모델 적용 범위(Out-of-Domain) 게이트 ─────────────────────────
        # 멀티플·잔여이익 모델은 이익·자산이 가격의 주요 설명변수일 때만 성립한다
        # (Damodaran, 고성장·스토리 기업 가치평가; SR 11-7 은 모델을 설계 범위 밖에서
        # 쓰는 것 자체를 모델 리스크로 본다). 모델 적정가가 시장가격과 ±70% 넘게
        # 벌어지면, 그것은 '저평가/고평가' 가 아니라 **모델이 이 종목의 가격을
        # 설명하지 못한다**는 뜻이다 — 가격의 대부분이 미래 성장 기대인 종목에서
        # 현재 이익·장부가로 만든 적정가는 숫자만 그럴듯한 오답이 된다
        # (실사례: 레인보우로보틱스 현재가 433,000원에 적정가 10,501원, PER 6,766배).
        # 이때는 수축·보정할 것이 아니라 '산출 불가'를 말하는 것이 맞다.
        _ood_gap = float(self.FV_CONF.get('out_of_domain_gap_pct', 70.0))
        if abs(raw_upside_pct) > _ood_gap:
            _ood_ctx = []
            try:
                if per and float(per) > 100:
                    _ood_ctx.append(f"PER {float(per):,.0f}배")
                if pbr and float(pbr) > 10:
                    _ood_ctx.append(f"PBR {float(pbr):,.1f}배")
            except (TypeError, ValueError):
                pass
            _ood_note = (
                f"산출 불가 — 멀티플 모델 적용 범위 밖. 모델 적정가가 시장가격과 "
                f"{raw_upside_pct:+.0f}% 괴리"
                + (f" ({', '.join(_ood_ctx)} — 이익·자산이 아니라 성장 기대가 "
                   f"가격을 지배)" if _ood_ctx else "")
                + ". 이 구간에서는 현재 이익·장부가 기반 적정가가 성립하지 않아 "
                  "숫자를 제시하지 않습니다.")
            return {
                'target_fundamental': curr_price, 'base_fair_value': curr_price,
                'displayed_fair_value': None,
                'preliminary_range_str': "미산출 (모델 적용 범위 밖)",
                'recommended_buy_price': None, 'margin_of_safety_pct': 15.0,
                'market_adjustment_pct': 0.0, 'upside_pct': None,
                'raw_upside_pct': float(raw_upside_pct),
                'upside_eval': "모델 적용 범위 밖 — 가치판단 보류",
                'fair_value_confidence': 0.0, 'enterprise_class': ent_class,
                'fair_value_status_note': _ood_note,
                'type_probabilities': type_probs,
                'model_results': model_results,
                'fair_value_status': "OUT_OF_DOMAIN",
                'roe': float(roe), 'per': float(per), 'pbr': float(pbr),
            }

        # 극단적 모델 편차/이상치 윈저화(Winsorization) 수축 방정식
        if raw_upside_pct > 45.0:
            # 45% 초과 극단 저평가 수치는 현실적 12개월 펀더멘털 상한(+25%~+48%)으로 로그 수축
            calibrated_upside_pct = 25.0 + (raw_upside_pct - 25.0) ** 0.45 * 2.5
            calibrated_upside_pct = min(48.0, calibrated_upside_pct)
        elif raw_upside_pct < -35.0:
            # -35% 미만 극단 고평가 수치는 (-15%~-35%)로 수축
            calibrated_upside_pct = -15.0 - (abs(raw_upside_pct) - 15.0) ** 0.45 * 2.0
            calibrated_upside_pct = max(-40.0, calibrated_upside_pct)
        else:
            calibrated_upside_pct = raw_upside_pct
            
        target_fundamental = float(curr_price * (1.0 + calibrated_upside_pct / 100.0))

        # 윈저화는 현재가를 기준으로 괴리율을 수축시키므로, 모델 분위수 범위를 벗어날 수 있다.
        # 중심값이 자기 범위 밖에 놓이는 모순을 막기 위해 확장범위(10~90분위) 안으로 되돌린다.
        center_clipped = False
        if target_fundamental < wide_range[0] or target_fundamental > wide_range[1]:
            target_fundamental = float(np.clip(target_fundamental, wide_range[0], wide_range[1]))
            center_clipped = True

        base_fair_value = float(target_fundamental / 0.98)
        upside_pct = float((target_fundamental / (curr_price + 1e-9) - 1.0) * 100.0)
        
        # 안전마진 결정 (우세 유형 반영)
        margin_of_safety = 0.15
        if type_probs['E_BIOTECH'] > 0.4 or type_probs['F_DEFICIT'] > 0.4: margin_of_safety = 0.25
        elif type_probs['D_PLATFORM'] > 0.4 or type_probs['H_TURNAROUND'] > 0.4: margin_of_safety = 0.20
        elif type_probs['A_STABLE'] > 0.4 or type_probs['C_FINANCIAL'] > 0.4: margin_of_safety = 0.12

        # ---------------------------------------------------------
        # 7. 적정가 신뢰도 산출 & [명세 §7] 신뢰도 구간별 노출 통제
        #    (구버전은 max(65.0, ...) 하한 때문에 '참고 범위만'·'미산출' 분기가 도달 불가였음)
        # ---------------------------------------------------------
        # 7개 구성요소를 각각 0~100 으로 매기고 가중합산한다 (감점 누적식이 아니다)
        n_valid = len(valid_models)
        c_data = float(np.clip(100.0 - 16.0 * len(missing_inputs), 0, 100))
        c_class = float(classification_confidence)
        c_fit = {0: 0.0, 1: 35.0, 2: 60.0, 3: 78.0}.get(n_valid, 90.0)
        disp = [abs(m['val'] / (weighted_median + 1e-9) - 1.0) for m in valid_models]
        c_agree = float(np.clip(100.0 - (np.mean(disp) * 180.0 if disp else 100.0)
                                - median_mean_gap * 100.0, 0, 100))
        c_stable = float(np.clip(100.0 - max(0.0, abs(raw_upside_pct) - 40.0) * 1.2
                                 - (25.0 if center_clipped else 0.0), 0, 100))
        c_account = 100.0 if not missing_inputs else float(np.clip(100.0 - 20.0 * len(missing_inputs), 0, 100))
        _sq = self.compute_strategy_quality(getattr(self, 'current_oos_result', None))
        c_oos = float(_sq['score']) if _sq.get('available') else 40.0

        conf_parts = {
            '데이터 완전성': (c_data, 0.20), '기업유형 분류': (c_class, 0.15),
            '모델 적합성': (c_fit, 0.20), '모델 합의도': (c_agree, 0.15),
            '추정치 안정성': (c_stable, 0.10), '단위·회계 검증': (c_account, 0.10),
            'OOS 보정성능': (c_oos, 0.10),
        }
        fair_value_confidence = float(np.clip(
            sum(v * w for v, w in conf_parts.values()), 0.0, 95.0))

        # [명세 §10] 70↑ 전체 표시 / 55~69 참고 중심값+넓은 범위 / 45~54 범위만 / 45↓ 보류
        # 신뢰도가 낮다는 이유로 모든 정보를 숨기지 않는다.
        # 중심값·범위·공식 판정·매수가 허용 여부를 분리한다.
        reference_fair_value = float(target_fundamental)   # 참고 중심값 (항상 산출)
        independent_models = n_valid

        if fair_value_confidence >= 70.0:
            fair_value_status = "CALIBRATED"
            fair_value_status_note = "정상 표시"
            displayed_fair_value = float(target_fundamental)
        elif fair_value_confidence >= 55.0:
            fair_value_status = "CAUTION"
            fair_value_status_note = "참고 중심 적정가 — 신뢰도 제한으로 참고용"
            displayed_fair_value = float(target_fundamental)
        elif fair_value_confidence >= 45.0:
            fair_value_status = "REFERENCE_ONLY"
            fair_value_status_note = "참고 범위만 표시 — 고평가·저평가 단정 불가"
            displayed_fair_value = None
        else:
            fair_value_status = "UNCALCULATED"
            fair_value_status_note = "중심 적정가 산출 보류 — 모델 재검토 필요"
            displayed_fair_value = None
            reference_fair_value = None

        # 권장 매수가는 별도 조건을 모두 충족할 때만 산출한다
        buy_price_checks = [
            ("적정가 신뢰도 ≥ 60", fair_value_confidence >= 60.0),
            ("유효 독립모델 2개 이상", independent_models >= 2),
            ("모델 간 편차 허용범위", (np.mean(disp) if disp else 1.0) <= 0.60),
            ("입력 지표 결측 2개 이하", len(missing_inputs) <= 2),
        ]
        if all(ok for _, ok in buy_price_checks) and displayed_fair_value is not None:
            recommended_buy_price = float(displayed_fair_value * (1.0 - margin_of_safety))
        else:
            recommended_buy_price = None
        # 중심 적정가를 표시하지 않는 구간에서는 저평가/고평가 단정도 하지 않는다 (§18)
        if displayed_fair_value is None:
            upside_eval = "가치판단 보류 (적정가 신뢰도 미달)"
            upside_pct_out = None
        else:
            upside_pct_out = float(upside_pct)
            if upside_pct >= 30.0: upside_eval = "큰 저평가 가능성"
            elif upside_pct >= 15.0: upside_eval = "저평가 가능성"
            elif upside_pct >= 7.0: upside_eval = "소폭 저평가"
            elif upside_pct >= -7.0: upside_eval = "적정가 부근"
            elif upside_pct >= -15.0: upside_eval = "소폭 고평가"
            elif upside_pct >= -30.0: upside_eval = "고평가 가능성"
            else: upside_eval = "큰 고평가 가능성"

        return {
            'target_fundamental': target_fundamental,
            'displayed_fair_value': displayed_fair_value,
            'preliminary_range_str': preliminary_range_str,
            'base_fair_value': float(base_fair_value),
            'recommended_buy_price': recommended_buy_price,
            'margin_of_safety_pct': margin_of_safety * 100,
            'market_adjustment_pct': -2.0,
            'upside_pct': upside_pct_out,
            'raw_upside_pct': float(raw_upside_pct),
            'upside_eval': upside_eval,
            'fair_value_confidence': float(fair_value_confidence),
            'fair_value_status_note': fair_value_status_note,
            'enterprise_class': ent_class,
            'type_probabilities': type_probs,
            'model_results': model_results,
            'fair_value_status': fair_value_status,
            # 신뢰도가 낮아도 참고 중심값·범위는 숨기지 않는다 (§10)
            'reference_fair_value': reference_fair_value,
            'fair_value_range_core': core_range,
            'fair_value_range_wide': wide_range,
            'fair_value_range_core_str': f"{core_range[0]:,.0f}원 ~ {core_range[1]:,.0f}원",
            'fair_value_range_wide_str': f"{wide_range[0]:,.0f}원 ~ {wide_range[1]:,.0f}원",
            'confidence_breakdown': {k: (round(v, 1), w) for k, (v, w) in conf_parts.items()},
            'buy_price_checks': buy_price_checks,
            'independent_models': independent_models,
            'classification_basis': classification_basis,
            'classification_confidence': classification_confidence,
            'classification_uncertain': classification_uncertain,
            'center_clipped_to_range': center_clipped,
            'sector': sector,
            'excluded_models': [{'name': m['name'], 'reason': m.get('exclusion_reason')}
                                for m in model_results.values()
                                if not m['valid'] and m.get('exclusion_reason')],
            'missing_inputs': missing_inputs,
            'debt_ratio': in_debt,
            'roe': in_roe,
            'per': in_per,
            'pbr': in_pbr,
            'bps': in_bps,
            'eps': in_eps,
        }


    def compute_four_separated_scores(self, symbol, tech_df, fund_df, sim_res, val_eval):
        """
        최종 스코어 병합 및 4대 점수 계산 (개편된 종합 퀀트 점수 산식 전면 적용)
        """
        curr_price = float(tech_df['adj_close'].iloc[-1])
        target_fundamental = val_eval.get('target_fundamental', curr_price)
        base_fair_value = val_eval.get('base_fair_value', target_fundamental)
        margin_of_safety_pct = val_eval.get('margin_of_safety_pct', 15.0)
        upside_eval = val_eval.get('upside_eval', '적정가 부근')
        fair_value_confidence = val_eval.get('fair_value_confidence', 0.0)
        fair_value_status = val_eval.get('fair_value_status', 'UNCALCULATED')
        market_adjustment_pct = val_eval.get('market_adjustment_pct', -2.0)

        # [P0-6 연동] 신뢰도 미달 구간에서는 중심 적정가·권장 매수가가 None으로 내려온다.
        displayed_fair_value = val_eval.get('displayed_fair_value')
        recommended_buy_price = val_eval.get('recommended_buy_price')
        fair_value_usable = (displayed_fair_value is not None and recommended_buy_price is not None)

        raw_upside = val_eval.get('upside_pct')
        upside_pct = float(raw_upside) if raw_upside is not None else None
        # 점수 산식 내부에서만 쓰는 중립 대체값 (표시에는 절대 쓰지 않는다)
        upside_for_scoring = upside_pct if upside_pct is not None else 0.0

        latest_fund = fund_df.iloc[-1].to_dict() if (fund_df is not None and not fund_df.empty) else {}

        # 월봉 10이평선 정량 수치 연동
        ma200_val = float(tech_df['ma_200'].iloc[-1]) if 'ma_200' in tech_df.columns else curr_price
        m10_slope = float(tech_df['m10_slope'].iloc[-1]) if 'm10_slope' in tech_df.columns else 0.0
        m10_disparity = float(tech_df['m10_disparity'].iloc[-1]) if 'm10_disparity' in tech_df.columns else 0.0
        m10_status = str(tech_df['m10_status'].iloc[-1]) if 'm10_status' in tech_df.columns else ("위" if curr_price >= ma200_val else "아래")
        m10_score = int(tech_df['m10_score'].iloc[-1]) if 'm10_score' in tech_df.columns else 50

        # 4대 전략 버킷(Strategy Bucket) 정량 동적 분류
        if m10_status == "위" and m10_slope > 0 and m10_disparity <= 25.0:
            strategy_type = "🏔️ 장기 추세형"
        elif upside_for_scoring >= 20.0 or upside_eval in ["큰 저평가 가능성", "저평가 가능성"]:
            strategy_type = "💎 가치·반전형"
        elif curr_price > tech_df['sma_60'].iloc[-1] and curr_price <= tech_df['sma_20'].iloc[-1] * 1.025:
            strategy_type = "🎯 눌림목 재진입형"
        else:
            strategy_type = "⚡ 실적 모멘텀형"

        # 1-1. 펀더멘털 점수 (ROE 미확보 시 가점·감점 없이 중립)
        roe_raw = latest_fund.get('roe')
        if roe_raw is None:
            roe_raw = val_eval.get('roe')
        roe = float(roe_raw) if roe_raw is not None else None
        if roe is None:   fundamental_score = 50
        elif roe > 15:    fundamental_score = 85
        elif roe > 8:     fundamental_score = 75
        elif roe > 0:     fundamental_score = 65
        else:             fundamental_score = 40

        # 1-2. 시장조정 밸류에이션 점수 (베이지안 윈저화 보정 연동)
        if not fair_value_usable:
            # 적정가를 신뢰할 수 없으면 밸류에이션은 가점도 감점도 아닌 중립
            valuation_score = 50.0
        elif upside_for_scoring >= 30.0: valuation_score = 92.0
        elif upside_for_scoring >= 15.0: valuation_score = 82.0
        elif upside_for_scoring >= 7.0: valuation_score = 70.0
        elif upside_for_scoring >= -7.0: valuation_score = 55.0
        elif upside_for_scoring >= -15.0: valuation_score = 40.0
        else: valuation_score = 25.0

        if fair_value_usable and curr_price > target_fundamental:
            valuation_score = min(valuation_score, 45.0)
        
        # 재무 지표는 미연동이면 None 으로 내려온다. 임의값으로 채우지 않고 중립 처리한다.
        debt_ratio_raw = latest_fund.get('debt_ratio')
        if debt_ratio_raw is None:
            debt_ratio_raw = val_eval.get('debt_ratio')
        debt_ratio = float(debt_ratio_raw) if debt_ratio_raw is not None else None
        if debt_ratio is None:
            financial_safety_score = 50      # 판정 보류
        else:
            financial_safety_score = max(20, 100 - max(0, debt_ratio - 100) * 0.3)

        revenue_yoy = latest_fund.get('revenue_yoy_pct')
        industry_competitiveness_score = 50
        if roe is not None:
            if roe > 15: industry_competitiveness_score += 20
            elif roe > 8: industry_competitiveness_score += 15
        if revenue_yoy is not None:
            if revenue_yoy > 10: industry_competitiveness_score += 10
            elif revenue_yoy > 5: industry_competitiveness_score += 5
        industry_competitiveness_score = min(100, industry_competitiveness_score)
        
        sma60 = tech_df['sma_60'].iloc[-1] if 'sma_60' in tech_df.columns else curr_price
        sma120 = tech_df['sma_120'].iloc[-1] if 'sma_120' in tech_df.columns else curr_price
        long_term_structure_score = 50
        if curr_price > sma60 > sma120: long_term_structure_score = 85
        elif curr_price > sma120: long_term_structure_score = 70
        elif curr_price < sma60 and curr_price < sma120: long_term_structure_score = 30
        
        WQ = self.W_QUALITY
        stock_quality_score = (
            fundamental_score * WQ.get('weight_fundamental', 0.30)
            + valuation_score * WQ.get('weight_valuation', 0.25)
            + financial_safety_score * WQ.get('weight_financial_safety', 0.20)
            + industry_competitiveness_score * WQ.get('weight_industry_competitiveness', 0.15)
            + long_term_structure_score * WQ.get('weight_long_term_structure', 0.10)
        )
        
        # ========================================================
        # 신호 합의도 계산을 위한 개별 컴포넌트 평가
        # ========================================================
        dm = self.compute_demark_indicators(tech_df)
        
        if 'buy_setup_series' in dm and len(dm['buy_setup_series']) == len(tech_df):
            tech_df['buy_setup_series'] = dm['buy_setup_series']
        else:
            tech_df['buy_setup_series'] = 0
            if len(tech_df) > 0:
                tech_df.iloc[-1, tech_df.columns.get_loc('buy_setup_series')] = dm.get('buy_setup_count', 0)
                
        if 'sell_setup_series' in dm and len(dm['sell_setup_series']) == len(tech_df):
            tech_df['sell_setup_series'] = dm['sell_setup_series']
        else:
            tech_df['sell_setup_series'] = 0
            if len(tech_df) > 0:
                tech_df.iloc[-1, tech_df.columns.get_loc('sell_setup_series')] = dm.get('sell_setup_count', 0)
                
        # compute_demark_indicators()가 실제로 반환하는 키를 사용한다.
        # (구버전은 'buy_setup'/'sell_setup'/'is_perfected'/'tdst_buy_setup_support' 등
        #  존재하지 않는 키를 읽어 DeMARK 기여가 항상 0, TDST는 현재가±20% 폴백으로 고정되어 있었음)
        buy_setup = int(dm.get('buy_setup_count', 0) or 0)
        sell_setup = int(dm.get('sell_setup_count', 0) or 0)
        buy_countdown = int(dm.get('buy_countdown', 0) or 0)
        sell_countdown = int(dm.get('sell_countdown', 0) or 0)
        buy_perfected = bool(dm.get('buy_perfected', False))
        sell_perfected = bool(dm.get('sell_perfected', False))

        demark_bullish_signal = 1 if (buy_setup >= 8 or buy_countdown >= 12 or buy_perfected) else 0
        demark_bearish_signal = 1 if (sell_setup >= 8 or sell_countdown >= 12 or sell_perfected) else 0

        tdst_support = dm.get('tdst_support')
        tdst_resistance = dm.get('tdst_resistance')
        tdst_available = (tdst_support is not None and tdst_resistance is not None)
        if tdst_available:
            # 지지 유지 = 강세 / 지지 이탈 = 약세 (상호 배타적인 실제 신호)
            tdst_bullish_signal = 1 if curr_price >= tdst_support else 0
            tdst_bearish_signal = 1 if curr_price < tdst_support else 0
        else:
            tdst_bullish_signal = 0
            tdst_bearish_signal = 0

        bb_lower = tech_df['bb_lower'].iloc[-1] if 'bb_lower' in tech_df.columns else curr_price*0.9
        bb_upper = tech_df['bb_upper'].iloc[-1] if 'bb_upper' in tech_df.columns else curr_price*1.1
        bb_mid = tech_df['sma_20'].iloc[-1] if 'sma_20' in tech_df.columns else curr_price
        prev_price = tech_df['adj_close'].iloc[-2] if len(tech_df) > 1 else curr_price
        
        bollinger_bullish_signal = 1 if prev_price < bb_lower and curr_price >= bb_lower else 0
        bollinger_bearish_signal = 1 if prev_price > bb_upper and curr_price <= bb_upper else 0
        
        williams_r = tech_df['williams_r'].iloc[-1] if 'williams_r' in tech_df.columns else -50
        prev_w = tech_df['williams_r'].iloc[-2] if ('williams_r' in tech_df.columns and len(tech_df) > 1) else -50
        williams_bullish_signal = 1 if williams_r > -80 and prev_w <= -80 else 0
        williams_bearish_signal = 1 if williams_r < -20 and prev_w >= -20 else 0
        
        rsi = tech_df['rsi_14'].iloc[-1] if 'rsi_14' in tech_df.columns else 50
        prev_r = tech_df['rsi_14'].iloc[-2] if ('rsi_14' in tech_df.columns and len(tech_df) > 1) else 50
        rsi_bullish_signal = 1 if rsi > 30 and prev_r <= 30 else 0
        rsi_bearish_signal = 1 if rsi < 70 and prev_r >= 70 else 0
        
        volume_flow_bullish_signal = 1 if tech_df['volume_ratio'].iloc[-1] > 1.5 and curr_price > prev_price else 0
        volume_flow_bearish_signal = 1 if tech_df['volume_ratio'].iloc[-1] > 1.5 and curr_price < prev_price else 0
        
        trend_bullish_signal = 1 if curr_price > sma60 else 0
        trend_bearish_signal = 1 if curr_price < sma60 else 0
        
        bullish_consensus = sum([demark_bullish_signal, tdst_bullish_signal, bollinger_bullish_signal, williams_bullish_signal, rsi_bullish_signal, volume_flow_bullish_signal, trend_bullish_signal])
        bearish_consensus = sum([demark_bearish_signal, tdst_bearish_signal, bollinger_bearish_signal, williams_bearish_signal, rsi_bearish_signal, volume_flow_bearish_signal, trend_bearish_signal])
        
        signal_consensus_score = max(0, min(100, 50 + (bullish_consensus - bearish_consensus) * 10))
        
        # ========================================================
        # 2. 현재 매매 적합도 (Trading Timing Score)
        # ========================================================
        sample_tier = sim_res.get('sample_tier', 'INSUFFICIENT') if sim_res else 'INSUFFICIENT'
        stats_usable = bool(sim_res) and sim_res.get('mean_perf') is not None
        probs_usable = bool(sim_res) and sim_res.get('probabilities_shown', False)

        win_rate = sim_res.get('obs_win_ratio') if sim_res else None
        avg_pnl = sim_res.get('mean_perf') if sim_res else None
        eff_trades = int(sim_res.get('match_count', 0)) if sim_res else 0

        # 거래비용 0.3%p 차감 후 순기대수익. 표본이 없으면 '0'이 아니라 '미산출'이다.
        expected_path_yield = (float(avg_pnl) - 0.3) if stats_usable else None

        if expected_path_yield is None:            path_expected_value_score = 50
        elif expected_path_yield >= 4.0:           path_expected_value_score = 90
        elif expected_path_yield >= 2.5:           path_expected_value_score = 80
        elif expected_path_yield >= 1.5:           path_expected_value_score = 70
        elif expected_path_yield >= 0.5:           path_expected_value_score = 60
        elif expected_path_yield >= 0.0:           path_expected_value_score = 50
        elif expected_path_yield >= -1.0:          path_expected_value_score = 35
        else:                                      path_expected_value_score = 20

        demark_confluence_score = signal_consensus_score

        tdst_struct_score = (80 if (tdst_available and curr_price > tdst_support) else 40) if tdst_available else 50
        technical_structure_score = int(m10_score * 0.35 + (85 if curr_price > sma60 else 40) * 0.25
                                        + (85 if curr_price > bb_mid else 40) * 0.25 + tdst_struct_score * 0.15)

        flow_volume_score = 55 + (volume_flow_bullish_signal * 15) - (volume_flow_bearish_signal * 15)

        # 시장 국면 — 상장시장(코스피/코스닥) 국면 + 글로벌 위험을 합성한다.
        # 종목만 보고 매수를 판단하면 판 전체가 무너지는 국면을 놓친다. 가중치와
        # 감점표는 규칙집 [RULES_MARKET_CONTEXT] 가 단일 출처다.
        # 한쪽을 못 받으면 그쪽 가중치를 0으로 두고 재정규화하고, 둘 다 못 받으면
        # 점수를 만들지 않는다(항목 제외) — 못 받은 값을 50점으로 채우지 않는다.
        regime_ctx = getattr(self, 'market_regime_ctx', None)
        _mctx_now = getattr(self, 'market_context', None) or {}
        regime_code, regime_label = 'DECISION_PENDING', '판정 보류 (지수 데이터 미수신)'
        if regime_ctx and regime_ctx.get('available'):
            regime_code, regime_label, _rw = self.classify_market_regime(
                regime_ctx.get('price'), regime_ctx.get('sma20'), regime_ctx.get('sma60'))

        market_regime_score = None
        regime_detail = {}
        try:
            import market_context as _mc_score
            _dom_for_score = dict(_mctx_now.get('domestic') or {})
            if _dom_for_score.get('available') and regime_code != 'DECISION_PENDING':
                _dom_for_score['regime_code'] = regime_code
            market_regime_score, regime_detail = _mc_score.score_market_regime(
                _dom_for_score, _mctx_now.get('global') or {}, self.W_MARKET_CTX)
        except Exception as _rexc:
            regime_detail = {'reason': f'시장 국면 산출 실패 ({type(_rexc).__name__})'}

        # 시장 국면을 못 만들면 그 항목의 가중치를 0으로 두고 나머지 항목으로
        # 매매 적합도를 재정규화한다 (중립 50점으로 메우지 않는다).
        regime_weight = self.W_TIMING.get('weight_market_regime', 0.08)
        if market_regime_score is None:
            regime_weight = 0.0
            market_regime_score_for_sum = 0.0
        else:
            market_regime_score_for_sum = market_regime_score

        # 통계 신뢰도는 실제 유효표본 수에 비례한다 (구버전은 존재하지 않는 'total_trades' 키를
        # 읽어 항상 0 → probability_edge_score가 언제나 정확히 50점으로 고정되어 있었음)
        if probs_usable and win_rate is not None:
            raw_probability_score = 50 + ((win_rate / 100.0) - 0.50) * 400
            statistical_confidence = min(1.0, eff_trades / 30.0)
            probability_edge_score = 50 + (raw_probability_score - 50) * statistical_confidence
        else:
            probability_edge_score = 50

        # ---- [P0-2] 진입 허용 상단 = 권장 매수가. 현재가에서 파생시키지 않는다. ----
        # 구버전: buy_entry_max = curr_price * 1.02  →  curr_price <= buy_entry_max 가 항상 참이라
        #         진입구간·추격매수 게이트 전체가 무력화되어 있었음.
        buy_entry_max = float(recommended_buy_price) if fair_value_usable else None
        fair_ref = float(displayed_fair_value) if fair_value_usable else None

        # 권장 매수가는 정의상 '적정가 − 안전마진'이므로 항상 현재가보다 낮을 수 있다.
        # 따라서 '안전마진 미확보'와 '적정가 초과(진짜 추격매수)'를 구분해서 판정한다.
        if buy_entry_max is None:
            entry_ratio = None
            entry_zone = "판정 불가"
            price_location_score = 30
        else:
            entry_ratio = curr_price / buy_entry_max
            if curr_price <= buy_entry_max:
                entry_zone = "안전마진 확보"
                price_location_score = 90
            elif curr_price <= fair_ref:
                entry_zone = "적정가 이하 (안전마진 미확보)"
                price_location_score = 60
            elif curr_price <= fair_ref * 1.05:
                entry_zone = "적정가 소폭 초과"
                price_location_score = 40
            elif curr_price <= fair_ref * 1.15:
                entry_zone = "적정가 초과 (추격매수 경고)"
                price_location_score = 22
            else:
                entry_zone = "적정가 크게 초과 (추격매수 위험)"
                price_location_score = 10

        event_timing_score = 50
        
        curr_feat = {'buy_setup': dm.get('buy_setup_count', 0), 'sell_setup': dm.get('sell_setup_count', 0)}
        hist_pred = self.compute_historical_pattern_prediction(tech_df, curr_feat)
        sim_res['hist_pred'] = hist_pred
        historical_pattern_score = hist_pred.get('hist_score', 0) if hist_pred.get('status') == 'Success' else 50
        if hist_pred.get('eff_sample', 0) == 0:
            historical_pattern_score = 50 # 미산출 시 중립

        WT = self.W_TIMING
        # 항목별 (점수, 가중치). 시장 국면을 못 만든 경우 그 가중치가 0이 되고
        # 아래 나눗셈이 남은 항목으로 자동 재정규화한다 — 빠진 항목을 50점으로
        # 메우면 '중립'이라는 없는 정보를 만들어 넣는 셈이 된다.
        _timing_terms = [
            (historical_pattern_score, WT.get('weight_historical_pattern', 0.22)),
            (path_expected_value_score, WT.get('weight_path_expected_value', 0.16)),
            (demark_confluence_score, WT.get('weight_demark_confluence', 0.14)),
            (technical_structure_score, WT.get('weight_technical_structure', 0.13)),
            (flow_volume_score, WT.get('weight_flow_volume', 0.11)),
            (market_regime_score_for_sum, regime_weight),
            (probability_edge_score, WT.get('weight_probability_edge', 0.07)),
            (price_location_score, WT.get('weight_price_location', 0.05)),
            (event_timing_score, WT.get('weight_event_timing', 0.04)),
        ]
        _timing_wsum = sum(w for _s, w in _timing_terms)
        trading_timing_score = (
            sum(s * w for s, w in _timing_terms) / _timing_wsum
            if _timing_wsum > 0 else 50.0)
        
        # ========================================================
        # 3. 리스크 안전성 (Risk Safety Score)
        # ========================================================
        vol_20 = float(tech_df['vol_20'].iloc[-1]) if 'vol_20' in tech_df.columns else 0.02

        # 목표가·손절가를 먼저 확정하고 손익비를 그로부터 산출한다.
        # 산식은 규칙집 [RULES_EXECUTION_LEVELS] 가 단일 출처다.
        #
        # 가상 백테스트 112회 진단(2026-08-01): 종전 기하(목표/손절 비율 2.0)는
        # 무추세 선도달확률 이론값이 33% — 적중률의 상한을 기하가 막고 있었다.
        # 재설계: 손절은 변동성 2σ 바닥(노이즈 손절 방지), 1차 목표는 '1차 분할익절'
        # (손절거리×0.7, 무추세 이론 P≈59%), 구조적 저항 목표는 2차 목표로 이동.
        _XL = RULEBOOK.get('RULES_EXECUTION_LEVELS', {})
        _stop_mult = float(_XL.get('stop_vol_mult', 2.0))
        _stop_floor = float(_XL.get('stop_floor_pct', 3.0)) / 100.0
        _t1_of_stop = float(_XL.get('target1_of_stop', 0.7))
        _t1_vol_floor = float(_XL.get('target1_vol_floor_mult', 0.8))

        # 1) 손절: 변동성 2σ 바닥. TDST 지지가 0.5R~1.5R 구간에 있으면 그 지지선을 쓴다.
        base_risk = curr_price * max(_stop_floor, vol_20 * _stop_mult)
        stop_loss_price = float(curr_price - base_risk)
        if tdst_available and (curr_price - 1.5 * base_risk) <= tdst_support <= (curr_price - 0.5 * base_risk):
            stop_loss_price = float(tdst_support)
        risk_abs = curr_price - stop_loss_price

        # 2) 2차 목표(구조): 가장 가까운 저항(TDST 저항 / 20일 고가 / 60일 고가) 중
        #    현재가 +1R 이상인 최근접 지점. 없으면 2R. 3R 제한.
        if risk_abs > 0:
            highs_series = tech_df['high'] if 'high' in tech_df.columns else tech_df['adj_close']
            resistance_candidates = []
            if tdst_available and tdst_resistance is not None:
                resistance_candidates.append(float(tdst_resistance))
            if len(highs_series) >= 20:
                resistance_candidates.append(float(highs_series.tail(20).max()))
            if len(highs_series) >= 60:
                resistance_candidates.append(float(highs_series.tail(60).max()))

            lo, hi = curr_price + 1.0 * risk_abs, curr_price + 3.0 * risk_abs
            in_window = [r for r in resistance_candidates if lo <= r <= hi]
            if in_window:
                target_struct = float(min(in_window))         # 가장 가까운 구조적 저항
            else:
                target_struct = float(curr_price + 2.0 * risk_abs)
        else:
            target_struct = float(curr_price * 1.05)

        # 3) 1차 목표(분할익절): 손절거리 × 0.7 — 도달확률 우선.
        #    구조적 저항이 그보다 가까우면 그 저항을 쓰되, 변동성 0.8σ 안쪽(노이즈)으로는
        #    내려가지 않는다. 2차 목표보다 위로 올라가지도 않는다.
        if risk_abs > 0:
            _t1_dist = min(_t1_of_stop * risk_abs, target_struct - curr_price)
            _t1_dist = max(_t1_dist, _t1_vol_floor * vol_20 * curr_price)
            target_tech_1st = float(min(curr_price + _t1_dist, target_struct))
        else:
            target_tech_1st = float(curr_price * 1.03)
        target_tech_2nd = float(max(target_struct, target_tech_1st))
        atr_risk_level = float(curr_price - base_risk * 2.0)

        # ── 권장 매수가에 실제로 샀을 때의 실행 레벨 ──────────────────────
        # 위 손절·목표는 전부 '지금 이 가격에 산다면'을 전제로 한 값이다.
        # 그런데 엔진은 동시에 '지금 사지 말고 X원까지 내려오면 사라'고 말한다.
        # 그러면 화면의 손절가는 **사지 말라고 한 가격**을 기준으로 그린 선이다.
        #
        # 실측(라운드 22b · 30종목): 권장 매수가가 산출된 17종목 중 **11종목
        # (65%)** 에서 손절가가 권장 매수가보다 위였다. 최대 +193%.
        # "6,602원에 사서 19,339원에 손절하라"는 문장은 성립하지 않는다.
        #
        # 그래서 같은 공식을 진입가에 다시 걸어 준다. 2차 목표(구조적 저항)는
        # 시장에 실재하는 가격대라 진입가와 무관하므로 그대로 둔다.
        entry_stop_price = entry_target_1st = entry_rr = None
        if (recommended_buy_price and recommended_buy_price > 0
                and vol_20 is not None):
            _e = float(recommended_buy_price)
            _e_risk = _e * max(_stop_floor, vol_20 * _stop_mult)
            _e_stop = _e - _e_risk
            # 진입가 기준으로도 TDST 지지가 0.5R~1.5R 안이면 그 지지선을 쓴다
            if (tdst_available and tdst_support is not None
                    and (_e - 1.5 * _e_risk) <= tdst_support <= (_e - 0.5 * _e_risk)):
                _e_stop = float(tdst_support)
            _e_risk = _e - _e_stop
            if _e_risk > 0:
                _e_t1 = _e + _t1_of_stop * _e_risk
                # 구조적 저항이 그보다 가까우면 그 저항까지만 (현행과 같은 규칙)
                if target_struct > _e:
                    _e_t1 = min(_e_t1, target_struct)
                _e_t1 = max(_e_t1, _e + _t1_vol_floor * vol_20 * _e)
                entry_stop_price = float(_e_stop)
                entry_target_1st = float(_e_t1)
                entry_rr = round(float((_e_t1 - _e) / _e_risk), 2)

        # 손익비는 구조적 목표(2차) 기준 — 1차는 분할익절이라 손익비 지표가 아니다
        reward_abs = target_tech_2nd - curr_price
        reward_risk_ratio = round(float(reward_abs / risk_abs), 2) if risk_abs > 0 else None

        if reward_risk_ratio is None:  reward_risk_score = 30
        elif reward_risk_ratio >= 2.0: reward_risk_score = 90
        elif reward_risk_ratio >= 1.5: reward_risk_score = 80
        elif reward_risk_ratio >= 1.3: reward_risk_score = 65
        elif reward_risk_ratio >= 1.0: reward_risk_score = 50
        else:                          reward_risk_score = 30

        volatility_mdd_score = max(20, 100 - vol_20*100*3)
        if vol_20 > 0.04: volatility_mdd_score -= 10
        financial_risk_score = financial_safety_score
        event_risk_score = max(20, 80 - bearish_consensus*15)

        # 유동성: 20일 평균 거래대금 실측 (구버전은 80점 고정)
        # 당일 거래량은 장 시작 전 0이 되므로 0인 날은 평균 산출에서 제외한다.
        avg_turnover_20d = None
        if 'volume' in tech_df.columns:
            tv = (tech_df['adj_close'] * tech_df['volume']).tail(20)
            tv = tv[tv > 0]
            if len(tv) >= 5:
                avg_turnover_20d = float(tv.mean())

        if avg_turnover_20d is None:      liquidity_score = 50
        elif avg_turnover_20d >= 5e10:    liquidity_score = 95   # 500억+
        elif avg_turnover_20d >= 1e10:    liquidity_score = 85   # 100억+
        elif avg_turnover_20d >= 2e9:     liquidity_score = 70   # 20억+
        elif avg_turnover_20d >= 5e8:     liquidity_score = 45
        else:                             liquidity_score = 20

        # 뉴스 위험 — 실제 수집한 종목 기사 제목의 낱말 일치만 센다.
        # 기사 내용을 해석하지 않으며, 좋은 뉴스로 점수를 올리지도 않는다
        # (감점만 있고 가점은 없다). 미수신이면 규칙집의 중립값을 쓴다.
        try:
            import market_context as _mc_news
            news_risk_score, news_risk_note = _mc_news.score_news_risk(
                _mctx_now.get('news_flags'),
                bool((_mctx_now.get('news') or {}).get('available')),
                self.W_MARKET_CTX)
        except Exception:
            news_risk_score, news_risk_note = 60.0, "뉴스 위험 산출 실패 — 중립값 적용"

        WR = self.W_RISK
        risk_safety_score = (
            reward_risk_score * WR.get('weight_reward_risk', 0.27)
            + volatility_mdd_score * WR.get('weight_volatility_mdd', 0.22)
            + financial_risk_score * WR.get('weight_financial_risk', 0.18)
            + event_risk_score * WR.get('weight_event_risk', 0.13)
            + liquidity_score * WR.get('weight_liquidity', 0.08)
            + news_risk_score * WR.get('weight_news_risk', 0.12)
        )

        # ========================================================
        # 4. 원시 종합점수 및 [명세 §14] 신뢰도 축소
        # ========================================================
        WTOP = self.W_TOP
        raw_quant_score = (
            stock_quality_score * WTOP.get('weight_stock_quality', 0.35)
            + trading_timing_score * WTOP.get('weight_trading_timing', 0.45)
            + risk_safety_score * WTOP.get('weight_risk_safety', 0.20)
        )

        # 분석 신뢰도 = 데이터 50% + 통계 30% + 모델검증 20% (analysis_rulebook_ko.txt 가중치)
        # 구버전은 analysis_confidence_score = 77 고정이었음.
        data_conf = 100.0
        if not fair_value_usable: data_conf -= 30.0
        if len(tech_df) < 250:    data_conf -= 20.0
        data_conf = max(0.0, data_conf)

        stat_conf = {
            'FORECAST_AVAILABLE': 100.0, 'LIMITED': 75.0, 'LOW_CONFIDENCE': 50.0,
            'OBSERVATION_ONLY': 25.0, 'INSUFFICIENT': 0.0
        }.get(sample_tier, 0.0)

        # 모델 검증 신뢰도 = 표본외 검증을 실제로 통과한 정도
        _sq_now = self.compute_strategy_quality(getattr(self, 'current_oos_result', None))
        model_val_conf = float(_sq_now['score']) if _sq_now.get('available') else 0.0
        WC = self.W_CONF
        analysis_confidence_score = int(round(
            data_conf * WC.get('weight_data_confidence', 0.50)
            + stat_conf * WC.get('weight_stat_confidence', 0.30)
            + model_val_conf * WC.get('weight_model_validation_confidence', 0.20)))

        confidence_factor = analysis_confidence_score / 100.0
        confidence_adjusted_score = 50 + (raw_quant_score - 50) * confidence_factor
        if raw_quant_score < 50:
            confidence_adjusted_score = min(raw_quant_score + 3, confidence_adjusted_score, 50)

        # ========================================================
        # 5. 기회점수 및 실행가능성 점수
        # ========================================================
        expected_return_score = min(100, max(0, 50 + expected_path_yield * 10)) if expected_path_yield is not None else 50
        path_edge_score = probability_edge_score
        if fair_value_usable and upside_pct is not None:
            upside_room_score = min(100, max(0, 50 + max(0.0, upside_pct) * 2))
        else:
            upside_room_score = 50

        WO = self.W_OPP
        opportunity_score = (
            expected_return_score * WO.get('weight_expected_return', 0.30)
            + reward_risk_score * WO.get('weight_reward_risk', 0.20)
            + path_edge_score * WO.get('weight_path_edge', 0.20)
            + historical_pattern_score * WO.get('weight_historical_pattern', 0.15)
            + upside_room_score * WO.get('weight_upside_room', 0.10)
            + liquidity_score * WO.get('weight_liquidity', 0.05)
        )

        entry_range_score = {
            "판정 불가": 20, "안전마진 확보": 90, "적정가 이하 (안전마진 미확보)": 55,
            "적정가 소폭 초과": 35, "적정가 초과 (추격매수 경고)": 22,
            "적정가 크게 초과 (추격매수 위험)": 10,
        }.get(entry_zone, 20)
        chase_risk_score = price_location_score
        liquidity_execution_score = liquidity_score
        stop_structure_score = 70 if risk_abs > 0 else 30
        event_execution_score = 60

        WE = self.W_EXEC
        execution_score = (
            entry_range_score * WE.get('weight_entry_range', 0.35)
            + chase_risk_score * WE.get('weight_chase_risk', 0.25)
            + liquidity_execution_score * WE.get('weight_liquidity', 0.20)
            + stop_structure_score * WE.get('weight_stop_structure', 0.10)
            + event_execution_score * WE.get('weight_event', 0.10)
        )

        execution_score = min(execution_score, {
            "판정 불가": 45, "안전마진 확보": 100, "적정가 이하 (안전마진 미확보)": 70,
            "적정가 소폭 초과": 55, "적정가 초과 (추격매수 경고)": 40,
            "적정가 크게 초과 (추격매수 위험)": 30,
        }.get(entry_zone, 45))

        # ========================================================
        # 6. 최종 행동 원점수
        # ========================================================
        WF = self.W_FINAL
        final_action_raw_score = (
            confidence_adjusted_score * WF.get('weight_confidence_adjusted', 0.45)
            + opportunity_score * WF.get('weight_opportunity', 0.30)
            + execution_score * WF.get('weight_execution', 0.15)
            + signal_consensus_score * WF.get('weight_signal_consensus', 0.10)
        )
        
        # ========================================================
        # 7. 최종 게이트 (Cap) — 각 상한이 왜 걸렸는지 사유를 함께 기록한다
        # ========================================================
        cap_reasons = []

        # [§14] 전략 품질은 가점이 아니라 상한. 표본외 검증 결과로 상한을 정한다.
        # oos_result / strategy_quality 는 run_full_pipeline 이 주입한다.
        oos_result = getattr(self, 'current_oos_result', None)
        strategy_quality = self.compute_strategy_quality(oos_result)
        strategy_quality_score = strategy_quality.get('score')
        blind_test_not_completed = not strategy_quality.get('available', False)
        sq_cap, sq_reason = self.strategy_quality_cap(strategy_quality)
        if sq_reason:
            cap_reasons.append(sq_reason)

        # 자산 유형 — ETF 는 적정가 개념이 성립하지 않으므로(펀드) 적정가 계열
        # 게이트를 비적용한다. 레버리지·인버스는 일일 재조정 복리손실 때문에
        # 20일 보유 전제 판정에 별도 상한을 건다.
        asset_type = self.classify_asset_type(
            getattr(self, '_asset_type_name', ''), bool(val_eval.get('is_fund')))
        is_fund_asset = asset_type in ('ETF', 'ETF_LEV', 'ETF_INV')
        asset_type_note = {
            'STOCK': '',
            'ETF': 'ETF — 적정가 게이트 비적용, 기술·추세 기준으로 판단',
            'ETF_LEV': '레버리지 ETF — 일일 재조정 복리손실(변동성 잠식), 단기 전술용',
            'ETF_INV': '인버스 ETF — 시장과 역방향·복리손실, 단기 헤지용 (장기보유 부적합)',
        }[asset_type]

        data_integrity_cap = 100
        if not fair_value_usable:
            if is_fund_asset:
                # 감점이 아니라 '비적용' — ETF 를 적정가 미달로 이중 처벌하지 않는다
                cap_reasons.append("ETF — 적정가 게이트 비적용 (기술·추세 기준)")
            else:
                data_integrity_cap = 64
                cap_reasons.append(f"적정가 신뢰도 미달({fair_value_confidence:.0f}점) → 상한 64점")

        statistical_cap = 100
        eff_sample_size = hist_pred.get('eff_sample', 0) if hist_pred.get('status') == 'Success' else eff_trades
        if eff_sample_size < 5:
            statistical_cap = 59
            cap_reasons.append(f"유효표본 {eff_sample_size:.0f}건 (5건 미만) → 상한 59점")
        elif eff_sample_size < 10:
            statistical_cap = 64
            cap_reasons.append(f"유효표본 {eff_sample_size:.0f}건 (10건 미만) → 상한 64점")

        expected_return_cap = 100
        if expected_path_yield is None:
            expected_return_cap = 59
            cap_reasons.append("순기대수익 미산출 (표본 부족) → 상한 59점")
        elif expected_path_yield < 2.0:
            expected_return_cap = 59
            cap_reasons.append(f"순기대수익 {expected_path_yield:+.1f}% (2.0% 미만) → 상한 59점")

        if is_fund_asset:
            # ETF: 적정가가 없으므로 '판정 불가' 상한을 걸지 않는다 (비적용)
            chase_buy_cap = 100
        else:
            chase_buy_cap = {
                "판정 불가": 59, "안전마진 확보": 100, "적정가 이하 (안전마진 미확보)": 100,
                "적정가 소폭 초과": 67, "적정가 초과 (추격매수 경고)": 59,
                "적정가 크게 초과 (추격매수 위험)": 49,
            }.get(entry_zone, 59)
            if chase_buy_cap < 100:
                cap_reasons.append(f"진입 위치 [{entry_zone}] → 상한 {chase_buy_cap}점")

        # 레버리지·인버스 상한 — 일일 재조정 복리손실은 보유일이 길수록 커진다.
        # 20일 지평 판정과 근본적으로 상충하므로 상한 67점 + 비중 절반 하향.
        leverage_cap = 100
        if asset_type in ('ETF_LEV', 'ETF_INV'):
            leverage_cap = 67
            cap_reasons.append(f"{asset_type_note} → 상한 67점")

        valuation_cap = 100
        if fair_value_usable and curr_price > target_fundamental * 1.10:
            valuation_cap = 59
            cap_reasons.append("현재가가 적정가를 10% 이상 초과 → 상한 59점")

        # ── 신뢰도 수축 괴리 (Black–Litterman 방식) ──────────────────────
        # 신뢰도가 낮은 큰 괴리는 '모순'이 아니라 '불확실한 견해'다. 예측결합 문헌
        # (Bates–Granger 1969, Timmermann 2006)의 처방대로, 견해를 정밀도(신뢰도)
        # 비율로 시장가격 쪽에 수축시켜 쓰고, 확신이 필요한 만큼 점수에 상한을 건다.
        # 예전에는 이 조합(신뢰도<75 & |괴리|>25%)을 데이터 모순으로 분류해 판정
        # 전체를 폐기했다 — PBR 0.2대 딥밸류 종목이 전부 '판정 보류'로 죽었다.
        upside_shrunk_pct = None
        valuation_uncertainty_cap = 100
        if fair_value_usable and upside_pct is not None:
            _conf_w = max(0.0, min(1.0, float(fair_value_confidence) / 100.0))
            upside_shrunk_pct = float(upside_pct) * _conf_w
            if fair_value_confidence < 75 and abs(upside_pct) > 25:
                valuation_uncertainty_cap = 64
                cap_reasons.append(
                    f"적정가 신뢰도 {fair_value_confidence:.0f}점에 괴리율 {upside_pct:+.1f}% — "
                    f"신뢰도 수축 괴리 {upside_shrunk_pct:+.1f}% 기준으로 판단 → 상한 64점")

        risk_event_cap = 100
        if bearish_consensus > bullish_consensus * 2 and bearish_consensus >= 2:
            risk_event_cap = 49
            cap_reasons.append(f"약세 신호 우세 ({bearish_consensus} vs {bullish_consensus}) → 상한 49점")
        if debt_ratio is not None and debt_ratio > 200:
            risk_event_cap = min(risk_event_cap, 55)
            cap_reasons.append(f"부채비율 {debt_ratio:.0f}% (200% 초과) → 상한 55점")

        m10_overheat_cap = 100
        if m10_disparity > 25.0:
            m10_overheat_cap = 67  # 월봉 10선 대비 +25% 이상 이격 과열 시 추격매수 제한
            cap_reasons.append(f"월봉 10선 이격 +{m10_disparity:.1f}% (과열) → 상한 67점")
        elif m10_disparity < 0 and asset_type != 'ETF_INV':
            # 10선 아래 = 추세 역행 매수 (시계열 모멘텀 문헌 + 리플레이 1,073건 실측
            # −8.7%p). 인버스는 역방향 상품이라 비적용.
            m10_overheat_cap = int(_XL.get('m10_below_cap', 64))
            cap_reasons.append(
                f"월봉 10선 아래 ({m10_disparity:+.1f}%) — 추세 역행 매수 제한 "
                f"(리플레이 실측 −8.7%p) → 상한 {m10_overheat_cap}점")

        # 시장·글로벌·뉴스 상한 — 종목이 좋아도 판이 나쁘면 점수를 제한한다.
        # 올리는 데는 쓰지 않는다(좋은 뉴스로 점수를 얹지 않는다). 사유는 항상 남긴다.
        _ctx = getattr(self, 'market_context', None) or {}
        context_cap = 100
        if _ctx.get('cap_score') is not None:
            context_cap = int(_ctx['cap_score'])
            for _r in _ctx.get('reasons', []):
                if '상한 미적용' not in _r:
                    cap_reasons.append(f"{_r} → 상한 {context_cap}점")

        # 상대 모멘텀(12-1) 열위 상한 — Jegadeesh–Titman(1993): 직전 12-1개월의
        # 뚜렷한 패자는 이후에도 저성과가 이어진다. 시장 대비 -25%p 이상 뒤처진
        # 종목의 신규 매수를 제한한다 (가점 없음 — 승자 추격은 하지 않는다).
        rel_mom = getattr(self, '_rel_mom_ctx', None)
        momentum_cap = 100
        if asset_type == 'ETF_INV':
            # 인버스는 시장과 역방향 — 시장 대비 상대 모멘텀 열위가 정상 상태다
            rel_mom = None
        if rel_mom and rel_mom.get('relative') is not None and rel_mom['relative'] <= -25.0:
            momentum_cap = 64
            cap_reasons.append(
                f"상대 모멘텀(12-1) {rel_mom['relative']:+.0f}%p 열위 "
                f"(종목 {rel_mom['stock']:+.0f}% vs {rel_mom['market']} "
                f"{rel_mom['index']:+.0f}%) → 상한 64점")

        # 52주 저점권 매수 제한 — George–Hwang(2004) 52주 고점 모멘텀의 역면.
        # 자체 리플레이 327건 실측: 저점권(<30%) 적중 57.1%(−5.5%p), 고점권 66.4%(+3.7%p).
        # '떨어지는 칼'은 확률이 낮다 — 저점권 신규 매수의 확신을 낮춘다 (가점 없음).
        range_low_cap = 100
        range_pos_52w = None
        try:
            _hi_col = tech_df['high'] if 'high' in tech_df.columns else tech_df['adj_close']
            _lo_col = tech_df['low'] if 'low' in tech_df.columns else tech_df['adj_close']
            _hi252 = float(_hi_col.tail(252).max())
            _lo252 = float(_lo_col.tail(252).min())
            if _hi252 > _lo252 > 0:
                range_pos_52w = (curr_price - _lo252) / (_hi252 - _lo252) * 100.0
                _rlow = float(_XL.get('range_low_pct', 30.0))
                if range_pos_52w < _rlow:
                    range_low_cap = int(_XL.get('range_low_cap', 64))
                    cap_reasons.append(
                        f"52주 범위 하위 {range_pos_52w:.0f}% (저점권 낙폭 추격 제한 — "
                        f"리플레이 327건 실측 적중률 −5.5%p) → 상한 {range_low_cap}점")
        except Exception:
            range_low_cap = 100

        # 실전 적중률 자기보정 상한 — 판정 성적표에서 판정 완료 5건 이상이고
        # 적중률이 낮으면 확신을 낮춘다 (TipRanks 트랙레코드 가중 방식).
        track = getattr(self, '_track_summary', None)
        track_cap = 100
        if track and track.get('hit_rate') is not None and track.get('decided', 0) >= 5 \
                and track['hit_rate'] < 45.0:
            track_cap = 59
            cap_reasons.append(
                f"실전 판정 적중률 {track['hit_rate']:.0f}% ({track['decided']}건 판정 완료) "
                f"→ 상한 59점 (자기 성적 보정)")

        final_action_score = min(
            final_action_raw_score,
            sq_cap,
            data_integrity_cap,
            statistical_cap,
            expected_return_cap,
            chase_buy_cap,
            valuation_cap,
            valuation_uncertainty_cap,
            risk_event_cap,
            m10_overheat_cap,
            context_cap,
            momentum_cap,
            range_low_cap,
            leverage_cap,
            track_cap
        )

        final_action_score = int(max(0, final_action_score))

        # 가상 백테스트 캘리브레이션 — 같은 엔진을 과거 기준일 리플레이로 ~100회
        # 돌려 채점한 점수대별 실제 적중률(scripts/calibration_lab.py 산출)을 읽는다.
        # 지금 점수가 속한 점수대의 표본이 충분한데(n≥15) Wilson 하한이 35% 미만이면
        # 확신을 낮춘다. 파일이 없으면(캘리브레이션 미수행) 개입하지 않는다.
        calib_band = None
        try:
            if not hasattr(self, '_calibration'):
                self._calibration = None
                _cal_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         ".portfolio", "calibration.json")
                if os.path.exists(_cal_path):
                    with open(_cal_path, encoding='utf-8') as _cf:
                        self._calibration = json.load(_cf)
            if self._calibration:
                for _b in self._calibration.get('bands', []):
                    if _b['lo'] <= final_action_score <= _b['hi']:
                        calib_band = _b
                        break
                if (calib_band and calib_band.get('n', 0) >= 15
                        and calib_band.get('wilson_low') is not None
                        and calib_band['wilson_low'] < 35.0
                        and final_action_score > 59):
                    cap_reasons.append(
                        f"가상 백테스트: 이 점수대({calib_band['lo']}~{calib_band['hi']}점) "
                        f"적중률 {calib_band['hit_rate']:.0f}% "
                        f"(n={calib_band['n']}, Wilson 하한 {calib_band['wilson_low']:.0f}%) "
                        f"→ 상한 59점")
                    final_action_score = 59
        except Exception:
            calib_band = None
        
        # ========================================================
        # 8. 최종 행동 판정
        # ========================================================
        if final_action_score >= 85: 
            final_action_title = "적극적 분할매수 검토"
        elif final_action_score >= 75: 
            final_action_title = "분할매수 검토"
        elif final_action_score >= 68: 
            final_action_title = "제한적 진입"
        elif final_action_score >= 58: 
            final_action_title = "조건 확인·관망"
        elif final_action_score >= 48: 
            final_action_title = "신규 매수 보류"
        elif final_action_score >= 35: 
            final_action_title = "비중축소 검토"
        else: 
            final_action_title = "거래 회피"
            
        # ========================================================
        # [명세 §18] 모순 검사 — 두 종류를 구분한다
        #
        # ① 하드(데이터 정합성): 산술·논리 불변식이 깨진 경우. 어느 한쪽 숫자가
        #    틀렸다는 뜻이므로 판정을 보류하는 것이 맞다.
        # ② 소프트(신호 간 이견): 모듈들이 서로 다른 방향을 가리키는 경우. 앙상블
        #    에서 이견은 정상이며(예측결합: Bates–Granger 1969, Timmermann 2006),
        #    처방은 '판정 거부'가 아니라 확신 하향 — 보수적인 쪽으로 결정적으로
        #    화해시키고 사유를 남긴다. 예전에는 ②까지 전부 '판정 보류'로 폐기해
        #    화면이 결론 없이 끝났다.
        # ========================================================
        contradiction_detected = False
        contradiction_reasons = []

        # ── 하드: 내부 불변식 위반 ──────────────────────────────────────
        # 자기유사 엔진이 '확률 미표시' 판정을 내렸는데도 확률값이 남아 있으면 내부 불일치다.
        # (hist_pred의 유효표본과 sim_res의 표본은 서로 다른 풀이므로 교차 비교하지 않는다)
        if sim_res and not sim_res.get('probabilities_shown', False) and sim_res.get('tp_first_prob') is not None:
            contradiction_detected = True
            contradiction_reasons.append("표본 통제 판정과 확률 노출이 불일치")

        # 부호 불일치: 적정가 < 현재가인데 상승여력이 양수면 산술이 깨진 것이다.
        if fair_value_usable and curr_price > target_fundamental and upside_pct is not None and upside_pct > 0:
            contradiction_detected = True
            contradiction_reasons.append("적정가보다 현재가가 높은데 상승여력을 양수로 표시")

        # ── 소프트: 신호 간 이견 → 보수적으로 화해 (판정은 반드시 낸다) ──
        soft_conflict_notes = []
        is_buy_intent = final_action_title in self.BUY_INTENT_TITLES

        if is_buy_intent and (buy_entry_max is None or curr_price > buy_entry_max):
            final_action_title = "조건 확인·관망"
            final_action_score = min(final_action_score, 67)
            soft_conflict_notes.append(
                "매수 의도였으나 현재가가 진입 허용가 밖 → 관망으로 하향 (상한 67점)")
            is_buy_intent = False

        if is_buy_intent and bearish_consensus > 2 * bullish_consensus:
            final_action_title = "조건 확인·관망"
            final_action_score = min(final_action_score, 67)
            soft_conflict_notes.append(
                f"매수 의도였으나 약세 신호 우세({bearish_consensus} vs {bullish_consensus}) "
                f"→ 관망으로 하향 (상한 67점)")
            is_buy_intent = False

        cap_reasons.extend(soft_conflict_notes)

        if contradiction_detected:
            final_action_score = min(final_action_score, 49)
            final_action_title = '⚠️ 재검토 필요'

        # ========================================================
        # [명세 §15] TOP3 필수조건 — 통과/미통과 사유를 전부 남긴다
        # ========================================================
        _ey = expected_path_yield
        _rr = reward_risk_ratio
        G = self.GATES

        def _num_gate(name, actual, threshold, fmt="{:.0f}"):
            """수치 게이트 — 통과/미통과에 따라 부등호를 올바르게 렌더한다.
            (구버전은 미충족 항목에도 '49 ≥ 68' 처럼 요구조건을 그대로 찍어 참처럼 보였다)"""
            ok = (actual is not None) and (actual >= threshold)
            a = fmt.format(actual) if actual is not None else "미산출"
            t = fmt.format(threshold)
            return {'name': name, 'actual': a, 'threshold': t, 'passed': ok,
                    'text': f"{name} {a} {'≥' if ok else '<'} {t}"}

        def _bool_gate(name, ok, detail=""):
            return {'name': name, 'actual': detail, 'threshold': '', 'passed': bool(ok),
                    'text': f"{name}{(' — ' + detail) if detail else ''}"}

        gate_checks = [
            _num_gate("최종 행동점수", final_action_score, G.get('min_action_score', 68)),
            _num_gate("종목 기본 매력도", stock_quality_score, G.get('min_stock_quality', 60)),
            _num_gate("현재 매매 적합도", trading_timing_score, G.get('min_trading_timing', 65)),
            _num_gate("리스크 안전성", risk_safety_score, G.get('min_risk_safety', 55)),
            _num_gate("기회점수", opportunity_score, G.get('min_opportunity', 65)),
            _num_gate("실행가능성", execution_score, G.get('min_execution', 60)),
            _num_gate("순기대수익", _ey, G.get('min_expected_return_pct', 2.0), "{:+.1f}%"),
            _num_gate("손익비", _rr, G.get('min_reward_risk', 1.3), "{:.2f}"),
            _num_gate("유효표본", eff_sample_size, G.get('min_effective_samples', 10), "{:.0f}건"),
            _num_gate("신호 합의도", signal_consensus_score, G.get('min_signal_consensus', 55)),
            _bool_gate("현재가가 권장 매수가 이하",
                       buy_entry_max is not None and curr_price <= buy_entry_max,
                       f"현재 {curr_price:,.0f}원 / 권장 "
                       + (f"{buy_entry_max:,.0f}원 이하" if buy_entry_max is not None else "미산출")),
            _bool_gate("적정가 신뢰도 확보", fair_value_usable, f"{fair_value_confidence:.0f}점"),
            _bool_gate("데이터 모순 없음", not contradiction_detected),
            _bool_gate("표본외(Blind/OOS) 검증 통과",
                       (not blind_test_not_completed) and (strategy_quality_score or 0) >= 40,
                       f"품질 {strategy_quality_score:.0f}점" if strategy_quality_score is not None else "미수행"),
        ]
        top3_block_reasons = [g['text'] for g in gate_checks if not g['passed']]
        eligible_for_top3 = (len(top3_block_reasons) == 0)

        if not eligible_for_top3 and final_action_title in self.BUY_INTENT_TITLES:
            if buy_entry_max is None or curr_price > buy_entry_max:
                final_action_title = "조건 확인·관망"
                final_action_score = min(final_action_score, 67)
            else:
                final_action_title = "제한적 진입"
                final_action_score = min(final_action_score, 74)

        if contradiction_detected:
            action_explain = "데이터 모순이 감지되어 추천을 중단했습니다: " + " / ".join(contradiction_reasons)
        elif eligible_for_top3:
            action_explain = "모든 필수조건을 통과했습니다. 권장 매수가 이하 구간에서 분할 진입이 유효합니다."
        elif top3_block_reasons:
            action_explain = "다음 조건이 미충족이라 신규 진입을 권하지 않습니다 — " + " / ".join(top3_block_reasons[:4])
        else:
            action_explain = "조건 확인 후 접근을 권장합니다."

        # [명세 §11] 확률 표시 제한 — 유효표본 10건 미만이면 어떤 확률도 문자열로도 내보내지 않는다
        if eff_sample_size < 10 or not probs_usable or win_rate is None:
            target_first_prob = "미산출"
            stop_first_prob = "미산출"
            hist_status = "BLIND"
        else:
            target_first_prob = f"{min(95, max(5, int(win_rate)))}%"
            stop_first_prob = f"{min(95, max(5, int(100 - win_rate)))}%"
            hist_status = "Valid"

        # 진입 검토가 (기술 지지 기준) — 적정가 기반 권장 매수가가 없을 때의 폴백
        # 계층. 값을 지어내지 않는다: 이미 계산된 지지 후보(TDST 지지·20일선·
        # 볼린저 하단) 중 현재가 아래(0.5% 여유) 최근접만 고르고, '적정가 검증이
        # 없는 기술적 기준'임을 basis 로 함께 내보낸다. 지지 후보가 전부 현재가
        # 위면 여기서도 None — 억지로 만들지 않는다.
        entry_review_price, entry_review_basis = None, ''
        if recommended_buy_price is None:
            _er_cands = [(float(dm.get('tdst_support') or 0), 'TDST 지지선')]
            if 'sma_20' in tech_df.columns:
                _er_cands.append((float(tech_df['sma_20'].iloc[-1]), '20일 이동평균선'))
            if 'bb_lower' in tech_df.columns:
                _er_cands.append((float(tech_df['bb_lower'].iloc[-1]), '볼린저 하단'))
            _er_below = [(p, b) for p, b in _er_cands
                         if p and p > 0 and p < curr_price * 0.995]
            if _er_below:
                entry_review_price, entry_review_basis = max(
                    _er_below, key=lambda x: x[0])

        return {
            # ETF·ETN 은 적정가를 산출하지 않는다 (None). float(None) 로 죽지 않게 한다.
            'target_fundamental': (float(target_fundamental)
                                   if target_fundamental is not None else None),
            'displayed_fair_value': displayed_fair_value,
            'preliminary_range_str': val_eval.get('preliminary_range_str', '미산출'),
            'fair_value_status': fair_value_status,
            'fair_value_status_note': val_eval.get('fair_value_status_note', ''),
            'fair_value_usable': fair_value_usable,
            'target_fundamental_note': f"시장조정 펀더멘털 적정가 ({upside_eval})",
            'base_fair_value': float(base_fair_value) if base_fair_value is not None else float(curr_price),
            'recommended_buy_price': float(recommended_buy_price) if recommended_buy_price is not None else None,
            'entry_review_price': entry_review_price,
            'entry_review_basis': entry_review_basis,
            'margin_of_safety_pct': float(margin_of_safety_pct) if margin_of_safety_pct is not None else 15.0,
            'upside_pct': upside_pct,
            'upside_eval': upside_eval,
            'market_adjustment_pct': float(market_adjustment_pct),
            'fair_value_confidence': float(fair_value_confidence),
            # 권장 매수가에 샀을 때의 레벨 — 위 target_tech_*/stop_loss_price 는
            # **현재가** 기준이라, 아직 안 산 사람에게는 이쪽이 맞는 값이다.
            'entry_stop_price': entry_stop_price,
            'entry_target_1st': entry_target_1st,
            'entry_rr': entry_rr,
            'entry_levels_note': ('권장 매수가에 샀을 때 기준 — 위 손절·목표는 '
                                  '현재가 기준이라 서로 다른 값입니다'),
            'target_tech_1st': target_tech_1st,
            'target_tech_1st_note': '1차 분할익절 목표 (도달확률 우선 — 손절거리 0.7배·변동성 기반)',
            'target_tech_2nd': target_tech_2nd,
            'target_tech_2nd_note': '2차 구조적 목표 (최근접 저항 1R~3R)',
            'target_trajectory_20d': float(curr_price * 1.03),
            'target_trajectory_20d_note': '20일 궤적 목표가',
            'stop_loss_price': stop_loss_price,
            'stop_loss_note': '변동성 2σ 손절 (노이즈 손절 방지)',
            'atr_risk_level': atr_risk_level,
            'atr_risk_level_note': '위험 관리 구간',
            
            'demark_res': dm,
            'demark_bullish_score': int(dm.get('bullish_score', 0)),
            'demark_bearish_score': int(dm.get('bearish_score', 0)),
            'demark_direction_text': str(dm.get('demark_label', '중립')),
            # 볼린저 상태를 화면에 그대로 전달한다 (예전에는 키가 없어 늘 '특이사항 없음')
            'bb_position_pct': dm.get('bb_position_pct'),
            'bb_width_pct': dm.get('bb_width_pct'),
            'bb_state': dm.get('bb_state', '산출 불가'),
            'rsi_value': dm.get('rsi_value'),
            'williams_r_value': dm.get('williams_r_value'),
            'buy_setup_count': int(dm.get('buy_setup_count', 0)),
            'sell_setup_count': int(dm.get('sell_setup_count', 0)),
            'buy_countdown': int(dm.get('buy_countdown', 0)),
            'sell_countdown': int(dm.get('sell_countdown', 0)),
            'final_action_title': final_action_title,
            'final_action_explain': action_explain,
            'buy_entry_range_str': (f"{buy_entry_max*0.97:,.0f}원 ~ {buy_entry_max:,.0f}원"
                                    if buy_entry_max is not None else "미산출 (적정가 신뢰도 미달)"),
            'buy_entry_max': float(buy_entry_max) if buy_entry_max is not None else None,
            'entry_premium_pct': round((entry_ratio - 1.0) * 100, 1) if entry_ratio is not None else None,
            'chase_buy_status': entry_zone,
            'entry_zone': entry_zone,
            'gate_reason': "정상 (상한 미적용)" if not cap_reasons else " / ".join(cap_reasons),
            'cap_reasons': cap_reasons,
            'top3_block_reasons': top3_block_reasons,
            'gate_checks': gate_checks,

            'final_quant_score': final_action_score, # UI 호환성을 위해 final_action_score를 매핑
            'final_action_score': final_action_score,
            'stock_quality_score': int(stock_quality_score),
            'trading_timing_score': int(trading_timing_score),
            'risk_safety_score': int(risk_safety_score),
            'opportunity_score': int(opportunity_score),
            'execution_score': int(execution_score),
            
            'analysis_confidence': analysis_confidence_score,
            'strategy_quality_score': strategy_quality_score,
            'blind_test_status': "미수행" if blind_test_not_completed else "수행완료",
            'sq_cap': sq_cap,

            # 시장·글로벌·뉴스가 점수에 실제로 들어간 내역 (상한과는 별개)
            'market_regime_score': (None if market_regime_score is None
                                    else round(float(market_regime_score), 1)),
            'market_regime_weight': round(float(regime_weight), 4),
            'market_regime_detail': regime_detail,
            'market_regime_excluded': market_regime_score is None,
            'news_risk_score': round(float(news_risk_score), 1),
            'news_risk_weight': float(self.W_RISK.get('weight_news_risk', 0.12)),
            'news_risk_note': news_risk_note,
            'timing_weight_sum': round(float(_timing_wsum), 4),

            # 시장·글로벌·뉴스 컨텍스트 (화면 표시 + 상한 근거)
            'context_cap': context_cap,
            'context_caps': dict(_ctx.get('caps') or {}),
            'context_reasons': list(_ctx.get('reasons') or []),
            'context_market': _ctx.get('market'),
            'context_regime_label': (_ctx.get('domestic') or {}).get('regime_label'),
            'context_news_risk_count': (_ctx.get('news_flags') or {}).get('risk_count', 0),
            'context_news_total': (_ctx.get('news_flags') or {}).get('total', 0),
            
            # DeMARK 매수 포인트 — 종합 결론에 그대로 싣는다
            'demark_entry': self.build_demark_entry(dm, curr_price),

            # 자산 유형 — 화면 표시 + 유형별 게이트 근거
            'asset_type': asset_type,
            'asset_type_note': asset_type_note,
            'vol_20': (float(vol_20) if vol_20 else None),   # 케이스 원장 기록용

            # 변동성 관리 비중 제안 (Moreira–Muir 2017: 실현 변동성이 높을 때
            # 노출을 줄이면 위험조정수익이 개선된다). 목표 연변동성 20% ÷ 실현.
            # 레버리지·인버스는 복리손실 때문에 여기서 다시 절반으로 줄인다.
            'suggested_position_pct': (
                round(min(100.0, max(10.0, 20.0 / (float(vol_20) * (252 ** 0.5) * 100.0)
                                     * 100.0))
                      * (0.5 if asset_type in ('ETF_LEV', 'ETF_INV') else 1.0), 0)
                if vol_20 and vol_20 > 0 else None),
            'suggested_position_basis': (
                f"연환산 변동성 {float(vol_20) * (252 ** 0.5) * 100.0:.0f}% · 목표 20% "
                f"(Moreira–Muir 변동성 관리)"
                if vol_20 and vol_20 > 0 else "변동성 미산출"),

            # 상대 모멘텀(12-1)·실전 성적 — 화면 표시 + 상한 근거
            'relative_momentum_12_1': (rel_mom or {}).get('relative'),
            'rel_mom_detail': rel_mom,
            'track_record': track,
            # 가상 백테스트 캘리브레이션 — 이 점수대의 과거 리플레이 적중률
            'calibration_band': calib_band,

            'tdst_support_str': ("N/A" if not tdst_available
                                 else ("지지 유지" if curr_price >= tdst_support else "이탈")),
            'tdst_resist_str': ("N/A" if not tdst_available
                                else ("돌파" if curr_price > tdst_resistance else "미돌파")),

            'stock_quality_grade': 'A 등급' if stock_quality_score >= 80 else 'B 등급',
            'trading_action': '진입 호기' if trading_timing_score >= 70 else '관망',
            'conf_grade': ("신뢰 가능" if analysis_confidence_score >= 70
                           else ("제한적" if analysis_confidence_score >= 45 else "신뢰 불가")),
            'sq_grade': ("미검증 (표본외 검증 불가)" if blind_test_not_completed
                         else ("우수" if (strategy_quality_score or 0) >= 70
                               else ("보통" if (strategy_quality_score or 0) >= 55
                                     else ("미흡" if (strategy_quality_score or 0) >= 40 else "부진")))),
            # 표본이 없거나 표준편차를 못 구하면 Sharpe도 산출하지 않는다
            # (구버전은 존재하지 않는 'std_perf' 키 → 1e-8로 나눠 1e8 규모의 값이 나왔음)
            'sharpe_ratio': (round(float(sim_res['mean_perf'] / sim_res['std_perf'] * np.sqrt(252 / 20)), 3)
                             if (sim_res and sim_res.get('mean_perf') is not None
                                 and sim_res.get('std_perf')) else None),
            'mdd_pct': (float((tech_df['adj_close'].tail(120) / tech_df['adj_close'].tail(120).cummax() - 1.0).min() * 100)
                        if len(tech_df) >= 120 else None),

            'f_score': int(fundamental_score),
            'v_score': int(valuation_score),
            't_score': int(technical_structure_score),
            'r_score': int(financial_safety_score),
            's_score': int(industry_competitiveness_score),
            'i_score': int(long_term_structure_score),
            # win_rate는 '관찰 승률'이다 (베이지안 사후확률이 아님)
            'win_rate': float(win_rate) if win_rate is not None else None,
            'path_edge': float(avg_pnl) if avg_pnl is not None else None,
            'sample_tier': sample_tier,
            'eff_sample_size': float(eff_sample_size),
            'avg_turnover_20d': avg_turnover_20d,
            'liquidity_score': int(liquidity_score),
            'market_regime_code': regime_code,
            'market_regime_label': regime_label,
            # 목표가·손절가 모두 미도달한 비중 (구버전은 20.0 고정)
            'non_reach': (round(max(0.0, 100.0 - float(sim_res.get('tp_first_prob') or 0.0)
                                    - float(sim_res.get('sl_first_prob') or 0.0)), 1)
                          if (probs_usable and sim_res.get('tp_first_prob') is not None) else None),

            'target_first_prob': target_first_prob,
            'stop_first_prob': stop_first_prob,
            'hist_status': hist_status,
            'eligible_for_top3': eligible_for_top3,
            
            'net_expected_return': expected_path_yield,
            'reward_risk_ratio': reward_risk_ratio,
            'strategy_type': strategy_type,
            'm10_val': ma200_val,
            'm10_status': m10_status,
            'm10_slope': m10_slope,
            'm10_disparity': m10_disparity,
            'm10_score': m10_score,
            'm10_trend_eval': "양호 (상승추세)" if (m10_status == "위" and m10_slope > 0) else ("관망 (평행)" if m10_status == "위" else "약함 (하락추세)"),
            'contradiction_detected': contradiction_detected,
            'contradiction_reasons': contradiction_reasons,
            # 신뢰도 수축 괴리(Black–Litterman 식 정밀도 가중) · 소프트 이견 화해 내역
            'upside_shrunk_pct': (None if upside_shrunk_pct is None
                                  else round(float(upside_shrunk_pct), 1)),
            'soft_conflict_notes': soft_conflict_notes
        }

    def check_20sma_settlement(self, tech_df):
        sub = tech_df.tail(5)
        if len(sub) < 5: return False, "데이터 부족"
        c1 = (sub['adj_close'].iloc[-1] > sub['sma_20'].iloc[-1]) and (sub['adj_close'].iloc[-2] > sub['sma_20'].iloc[-2])
        c2 = sub['sma_20_slope'].iloc[-1] >= 0.0
        c3 = sub['volume_ratio'].iloc[-1] >= 1.20
        c4 = sub['rsi_14'].iloc[-1] >= 45.0
        passed_cnt = sum([c1, c2, c3, c4])
        return passed_cnt >= 3, f"4개 조건 중 {passed_cnt}개 충족 ({'안착 성공' if passed_cnt>=3 else '안착 대기'})"

    def compute_historical_pattern_prediction(self, df, current_features):
        import numpy as np
        if len(df) < 50:
            return {'status': 'Insufficient Data', 'eff_sample': 0}
            
        n = len(df)
        forecast_horizon = 20
        curr_b_setup = current_features.get('buy_setup', 0)
        curr_s_setup = current_features.get('sell_setup', 0)
        
        candidates = []
        last_added = -999
        for t in range(20, n - forecast_horizon):
            if t - last_added < forecast_horizon:
                continue
                
            b_set = df['buy_setup_series'].iloc[t] if 'buy_setup_series' in df.columns else 0
            s_set = df['sell_setup_series'].iloc[t] if 'sell_setup_series' in df.columns else 0
            
            if curr_b_setup > 0 and b_set == 0: continue
            if curr_s_setup > 0 and s_set == 0: continue
            
            sim_demark = 1.0 - (abs(b_set - curr_b_setup) + abs(s_set - curr_s_setup)) / 18.0
            sim_score = sim_demark * 0.4 + 0.6 
            
            if sim_score > 0.6:
                candidates.append((t, sim_score))
                last_added = t
                
        if len(candidates) < 3:
            return {'status': 'Insufficient Samples', 'eff_sample': len(candidates)}
            
        weights = []
        ret_5 = []
        ret_10 = []
        ret_20 = []
        target_first = []
        stop_first = []
        
        for t, sim in candidates:
            w = sim ** 2
            weights.append(w)
            p0 = df['adj_close'].iloc[t]
            ret_5.append((df['adj_close'].iloc[t+5]/p0) - 1)
            ret_10.append((df['adj_close'].iloc[t+10]/p0) - 1)
            ret_20.append((df['adj_close'].iloc[t+20]/p0) - 1)
            
            high_path = df['high'].iloc[t+1:t+21].values
            low_path = df['low'].iloc[t+1:t+21].values
            # 자기유사 엔진과 동일한 임계값을 쓴다 (구버전은 +5%/−3%로 따로 놀았음)
            target_p = p0 * (1.0 + self.TP_THRESHOLD_PCT / 100.0)
            stop_p = p0 * (1.0 - self.SL_THRESHOLD_PCT / 100.0)
            
            t_hit = -1
            s_hit = -1
            for idx in range(len(high_path)):
                if high_path[idx] >= target_p and t_hit == -1: t_hit = idx
                if low_path[idx] <= stop_p and s_hit == -1: s_hit = idx
                
            if t_hit != -1 and (s_hit == -1 or t_hit < s_hit):
                target_first.append(1)
                stop_first.append(0)
            elif s_hit != -1 and (t_hit == -1 or s_hit < t_hit):
                target_first.append(0)
                stop_first.append(1)
            else:
                target_first.append(0)
                stop_first.append(0)
                
        weights = np.array(weights)
        weights /= np.sum(weights)
        
        eff_sample = 1.0 / np.sum(weights**2)
        up_5 = np.sum(weights * (np.array(ret_5) > 0))
        up_10 = np.sum(weights * (np.array(ret_10) > 0))
        up_20 = np.sum(weights * (np.array(ret_20) > 0))
        exp_ret = np.sum(weights * np.array(ret_20)) - 0.003
        
        p_target = np.sum(weights * np.array(target_first))
        p_stop = np.sum(weights * np.array(stop_first))
        
        hist_score = (p_target * 0.3) + (max(0, exp_ret)*10 * 0.25) + (up_20 * 0.15) + (eff_sample/50 * 0.1)
        hist_score = min(100, hist_score * 100 + 40)
        
        if eff_sample < 5: hist_score = 0; trust = '미산출'
        elif eff_sample < 10: hist_score = min(55, hist_score); trust = '참고용'
        elif eff_sample < 15: hist_score = min(62, hist_score); trust = '낮음'
        elif eff_sample < 30: trust = '보통'
        elif eff_sample < 50: trust = '양호'
        else: trust = '높음'
            
        return {
            'status': 'Success', 'eff_sample': eff_sample,
            'up_5': up_5, 'up_10': up_10, 'up_20': up_20,
            'p_target': p_target, 'p_stop': p_stop,
            'exp_ret': exp_ret, 'hist_score': hist_score,
            'trust': trust, 'sample_count': len(candidates)
        }

        return self.compute_four_separated_scores(symbol, tech_df, fund_df, sim_res, val_eval)

    def calculate_quantamental_hybrid_score(self, tech_df, fund_df, symbol, four_scores=None):
        """ [Section 21-1] 퀀터멘탈(Quantamental) 하이브리드 엔진 (Quant 70% + Fundamental RAG 30%) 100% 동적 연산 """
        if four_scores:
            quant_score = four_scores.get('trading_timing_score', 60)
            fund_qual_score = four_scores.get('stock_quality_score', 70)
        else:
            curr_price = tech_df['adj_close'].iloc[-1]
            sma_20 = tech_df['sma_20'].iloc[-1]
            quant_score = 75 if curr_price >= sma_20 else 55
            latest_fund = fund_df.iloc[-1].to_dict() if len(fund_df) > 0 else {}
            rev_yoy = latest_fund.get('revenue_yoy_pct', 12.4)
            fund_qual_score = int(np.clip(70 + (rev_yoy * 0.8), 50, 95))
        
        hybrid_score = int(round(quant_score * 0.70 + fund_qual_score * 0.30))
        return {
            "hybrid_score": hybrid_score,
            "quant_score": quant_score,
            "fund_qual_score": fund_qual_score,
            "formula_str": f"Quant({quant_score}점)×70% + Fundamental({fund_qual_score}점)×30% = {hybrid_score}점"
        }

    # 거래비용 가정 (왕복): 수수료 0.015%×2 + 증권거래세 0.20% + 슬리피지 0.18%
    COST_BREAKDOWN = {
        "수수료(왕복)": rb('RULES_TRADING_COSTS', 'commission_round_trip', 0.03),
        "증권거래세": rb('RULES_TRADING_COSTS', 'transaction_tax', 0.20),
        "슬리피지": rb('RULES_TRADING_COSTS', 'slippage', 0.18),
    }
    TOTAL_COST_PCT = round(sum(COST_BREAKDOWN.values()), 3)

    #: [라운드 3] 기대수익 거부권 모드 — 'strict'(현행 운영) | 'calibrated'(후보).
    #  calibrated 는 자기유사 기대수익이 음수여도 점수대 캘리브레이션이 충분히
    #  강하면(표본 30건+ · Wilson 하한 50%+) 매수를 차단하지 않는다.
    #  환경변수 QUANT_VETO_NET_MODE 로 후보 원장을 만들 때만 바꾼다.
    #  운영 모델은 검증 통과 전까지 절대 자동 전환하지 않는다 (승격 규율).
    VETO_NET_MODE = os.environ.get('QUANT_VETO_NET_MODE', 'strict')

    def calculate_sharpe_and_turnover(self, sim_res, four_scores=None):
        """
        [Section 21-2] Sharpe & Turnover.
        Sharpe는 compute_four_separated_scores 가 산출한 값을 그대로 쓴다 —
        한 화면에 서로 다른 Sharpe 두 개가 표시되지 않도록 정의를 한 곳으로 모은다.
        """
        sharpe = four_scores.get('sharpe_ratio') if four_scores else None
        if sharpe is None and sim_res and sim_res.get('mean_perf') is not None and sim_res.get('std_perf'):
            sharpe = round(float(sim_res['mean_perf'] / sim_res['std_perf'] * np.sqrt(252 / 20)), 3)

        # 회전율 = 연간 영업일 / 권장 보유기간 (관측된 최적 보유기간 기반)
        hold_days = sim_res.get('optimal_holding_period_days') if sim_res else None
        turnover_pct = round(252.0 / hold_days * 100, 1) if hold_days else None

        raw_perf = sim_res.get('mean_perf') if sim_res else None
        return {
            "sharpe_ratio": sharpe,
            "turnover_pct": turnover_pct,
            "holding_days": hold_days,
            "real_profit_factor": sim_res.get('profit_factor') if sim_res else None,
            "net_excess_return": round(raw_perf - self.TOTAL_COST_PCT, 2) if raw_perf is not None else None,
        }

    def calculate_sector_per_upside(self, val_eval, symbol):
        """ [Section 21-3] KOSPI / 섹터 PER 밴드 및 업사이드 잔여 여력 100% 동적 계산기 """
        _per = val_eval.get('per') if val_eval else None
        if _per is None:
            return {"sector_10yr_per": None, "curr_per": None, "upside_room_pct": None,
                    "fomo_status": "PER 미수신 — 섹터 밴드 대조 불가"}
        curr_per = float(_per)
        
        # 기업 유형 및 종목별 섹터 10년 평균 PER 동적 연산
        type_probs = val_eval.get('type_probabilities', {}) if val_eval else {}
        if type_probs.get('C_FINANCIAL', 0) > 0.4: sector_10yr_per = 7.5
        elif type_probs.get('D_PLATFORM', 0) > 0.4: sector_10yr_per = 32.0
        elif type_probs.get('E_BIOTECH', 0) > 0.4: sector_10yr_per = 45.0
        elif type_probs.get('A_STABLE', 0) > 0.4: sector_10yr_per = 14.0
        else: sector_10yr_per = 18.5
        
        if curr_per > 0 and curr_per < sector_10yr_per:
            upside_room_pct = round(((sector_10yr_per - curr_per) / (curr_per + 1e-8)) * 100, 1)
            fomo_status = "데이터 기반 객관적 관망 유지 권장 (업사이드 여력 존재)"
        elif curr_per >= sector_10yr_per:
            upside_room_pct = 0.0
            fomo_status = f"현재 PER({curr_per:.1f}배)가 섹터 평균({sector_10yr_per:.1f}배) 이상 ➔ 고평가 진입 주의"
        else:
            upside_room_pct = 15.0
            fomo_status = "적자/특이 수치 ➔ 펀더멘털 적정가 대조 권장"
        
        return {
            "sector_10yr_per": round(sector_10yr_per, 1),
            "curr_per": round(curr_per, 1),
            "upside_room_pct": upside_room_pct,
            "fomo_status": fomo_status
        }

    # 기업유형 코드 → 표시명 (전 종목 공통. 종목별 예외 없음)
    ENTERPRISE_TYPE_KO = {
        'A_STABLE': '안정적 흑자기업', 'B_CYCLICAL': '경기민감·자본집약 기업',
        'C_FINANCIAL': '금융업 중심 기업', 'D_PLATFORM': '플랫폼·핀테크 기업',
        'E_BIOTECH': '바이오·신약 기업', 'F_DEFICIT': '적자 고성장 기업',
        'G_HOLDING': '자산가치·지주회사형', 'H_TURNAROUND': '턴어라운드 기업',
    }

    def get_company_profile(self, symbol, val_eval=None, four_scores=None, universe_row=None):
        """
        [전 종목 공통] 실제 수치에서만 파생되는 기업 프로필.

        구버전 get_ai_value_chain_research 는 7개 종목의 티커를 키로 하는
        DEEP_RESEARCH_DB 에 손으로 쓴 서술("키트루다 SC 독점 재계약 체결" 등)을 담고
        나머지 종목에는 템플릿 문장을 붙였다. 검증 불가능한 서술을 사실처럼 제시하고
        종목별 예외처리를 만드는 구조여서 통째로 제거했다.

        여기서는 분류 결과와 실측 지표만 돌려주고, 정성 리서치는 미연동임을 명시한다.
        """
        val_eval = val_eval or {}
        four_scores = four_scores or {}
        universe_row = universe_row or {}

        tprobs = val_eval.get('type_probabilities') or {}
        ranked = sorted(tprobs.items(), key=lambda kv: kv[1], reverse=True)[:3]
        type_mix = [{'code': c, 'name': self.ENTERPRISE_TYPE_KO.get(c, c),
                     'probability_pct': round(p * 100, 1)} for c, p in ranked]

        models = val_eval.get('model_results') or {}
        applied = [{'model': m.get('name', k), 'weight_pct': round(m.get('weight', 0) * 100, 1),
                    'value': m.get('val')}
                   for k, m in sorted(models.items(), key=lambda kv: -kv[1].get('weight', 0))
                   if m.get('valid') and m.get('weight', 0) > 0]
        excluded = [m.get('name', k) for k, m in models.items()
                    if not m.get('valid') or m.get('weight', 0) <= 0]

        turnover = four_scores.get('avg_turnover_20d')
        return {
            'symbol': symbol,
            'enterprise_class': val_eval.get('enterprise_class'),
            'type_mix': type_mix,
            'applied_models': applied,
            'excluded_models': excluded,
            'metrics': {
                'per': val_eval.get('per'), 'pbr': val_eval.get('pbr'),
                'roe': val_eval.get('roe'), 'eps': val_eval.get('eps'),
                'bps': val_eval.get('bps'), 'debt_ratio': val_eval.get('debt_ratio'),
                'market_cap_eok': universe_row.get('market_cap_eok'),
                'avg_turnover_20d': turnover,
                'liquidity_score': four_scores.get('liquidity_score'),
            },
            'missing_inputs': val_eval.get('missing_inputs') or [],
            'qualitative_research': None,
            'qualitative_note': (
                '사업부문·공급망·파이프라인 등 정성 리서치는 연동되어 있지 않습니다. '
                '아래 항목은 모두 수집된 수치와 분류 결과에서만 파생된 값입니다.'),
        }

    def calculate_benchmark_comparisons(self, sim_res, tech_df=None, horizon=20,
                                        b_engine=None):
        """
        [Section 22-2] 벤치마크 대조.
        조건부 전략(자기유사 패턴 매칭)의 20일 수익률을, 같은 종목의
        '무조건 보유'와 '20일선 위에서만 보유' 기준선과 비교한다.
        구버전은 매수·보유를 AI성과×1.15로 지어내고 KOSPI200을 12.6% 리터럴로 박아두었다.
        """
        ai_perf = sim_res.get('mean_perf') if sim_res else None

        buy_hold_perf = None
        trend_perf = None
        if tech_df is not None and len(tech_df) > horizon + 30:
            px = tech_df['adj_close'].values
            fwd = (px[horizon:] / px[:-horizon] - 1.0) * 100.0     # 전 구간 20일 선도수익률
            buy_hold_perf = round(float(np.mean(fwd)), 2)
            if 'sma_20' in tech_df.columns:
                above = (tech_df['adj_close'].values > tech_df['sma_20'].values)[:-horizon]
                if above.sum() >= 20:
                    trend_perf = round(float(np.mean(fwd[above])), 2)

        parts = []
        if ai_perf is not None and buy_hold_perf is not None:
            edge = round(ai_perf - buy_hold_perf, 2)
            parts.append(f"패턴 조건부 전략은 같은 종목 무조건 보유 대비 {edge:+.2f}%p")
        if ai_perf is not None and trend_perf is not None:
            parts.append(f"20일선 위 보유 대비 {ai_perf - trend_perf:+.2f}%p")
        judge_text = (" / ".join(parts) + " 입니다. 거래비용 차감 전 기준입니다."
                      if parts else "표본 부족으로 벤치마크 대조를 산출하지 못했습니다.")

        # KOSPI200 지수도 같은 방식(전 구간 H일 선도수익률 평균)으로 대조한다.
        # 종목 수익률과 같은 정의를 써야 비교가 성립한다.
        kospi200_perf, kospi200_note = None, "지수 시계열 미연동 — 산출 불가"
        if b_engine is not None:
            series = None
            try:
                series = b_engine.fetch_index_daily("KOSPI200",
                                                    count=max(1200, horizon + 200))
            except Exception:
                series = None
            if series is not None:
                _dates, kc = series
                if len(kc) > horizon + 30:
                    kfwd = (kc[horizon:] / kc[:-horizon] - 1.0) * 100.0
                    kospi200_perf = round(float(np.mean(kfwd)), 2)
                    kospi200_note = (f"KOSPI200 일봉 {len(kc)}봉 기준 "
                                     f"{horizon}일 선도수익률 평균")
                else:
                    kospi200_note = "KOSPI200 봉 수 부족 — 산출 불가"

        if ai_perf is not None and kospi200_perf is not None:
            parts.append(f"KOSPI200 대비 {ai_perf - kospi200_perf:+.2f}%p")
            judge_text = " / ".join(parts) + " 입니다. 거래비용 차감 전 기준입니다."

        return {
            "available": ai_perf is not None and buy_hold_perf is not None,
            "ai_perf": ai_perf,
            "buy_hold_perf": buy_hold_perf,
            "trend20d_perf": trend_perf,
            "kospi200_perf": kospi200_perf,
            "kospi200_note": kospi200_note,
            "judge_text": judge_text,
        }

    def calculate_factor_attribution(self, sim_res, tech_df=None, b_engine=None):
        """
        [Section 22-3] 팩터 귀속 분해.

        섹터·규모·모멘텀 팩터 수익률은 횡단면 포트폴리오를 만들어야 산출되는데
        그 데이터가 없다. 다만 **시장 팩터는 KOSPI200 지수로 실제 회귀가 가능**하다.
        따라서 1팩터(시장) 모형으로 실측하고, 나머지 팩터는 미연동임을 그대로 밝힌다.
        구버전은 총수익률에 0.51/0.28/0.13/0.15를 곱해 분해한 것처럼 보이게 했다.

        회귀:  r_stock,t = alpha + beta · r_market,t + e_t   (일간 수익률)
        """
        total = sim_res.get('mean_perf') if sim_res else None
        unavailable = {
            "available": False,
            "reason": "팩터 수익률 시계열(시장·섹터·규모·모멘텀) 미연동 — 귀속 회귀 불가",
            "total_perf": total,
        }
        if tech_df is None or b_engine is None or 'trade_date' not in tech_df.columns:
            return unavailable

        try:
            series = b_engine.fetch_index_daily("KOSPI200", count=1200)
        except Exception:
            series = None
        if series is None:
            return {**unavailable,
                    "reason": "KOSPI200 지수 시계열 수신 실패 — 귀속 회귀 불가"}

        idx_dates, idx_close = series
        # 지수 날짜는 'YYYYMMDD', 종목은 'YYYY-MM-DD' — 같은 형식으로 맞춰 교집합을 만든다
        idx_map = {str(d)[:8]: c for d, c in zip(idx_dates, idx_close)}
        s_dates = [str(d).replace('-', '')[:8] for d in tech_df['trade_date'].values]
        s_close = tech_df['adj_close'].values

        pair_d, pair_s, pair_m = [], [], []
        for d, c in zip(s_dates, s_close):
            m = idx_map.get(d)
            if m is not None:
                pair_d.append(d)
                pair_s.append(float(c))
                pair_m.append(float(m))
        if len(pair_s) < 120:
            return {**unavailable,
                    "reason": f"지수와 겹치는 거래일이 {len(pair_s)}일뿐 — 회귀 불가 (최소 120일)"}

        sv, mv = np.array(pair_s), np.array(pair_m)
        rs = np.diff(sv) / sv[:-1]
        rm = np.diff(mv) / mv[:-1]
        ok = np.isfinite(rs) & np.isfinite(rm)
        rs, rm = rs[ok], rm[ok]
        if len(rs) < 100 or float(np.std(rm)) < 1e-12:
            return {**unavailable, "reason": "지수 수익률 분산이 0 — 회귀 불가"}

        beta = float(np.cov(rs, rm, ddof=1)[0, 1] / np.var(rm, ddof=1))
        alpha_daily = float(np.mean(rs) - beta * np.mean(rm))
        resid = rs - (alpha_daily + beta * rm)
        ss_tot = float(np.sum((rs - np.mean(rs)) ** 2))
        r2 = float(1.0 - np.sum(resid ** 2) / ss_tot) if ss_tot > 0 else 0.0

        # 관찰 기간 총수익률을 시장설명분 / 잔차(알파)로 나눈다
        n = len(rs)
        market_part = float(beta * np.mean(rm) * n * 100.0)
        alpha_part = float(alpha_daily * n * 100.0)
        realized = float((sv[-1] / sv[0] - 1.0) * 100.0)

        return {
            "available": True,
            "model": "1팩터(시장) 모형 — KOSPI200 일간 수익률 회귀",
            "n_days": n,
            "beta": round(beta, 3),
            "alpha_daily_pct": round(alpha_daily * 100.0, 4),
            "alpha_annual_pct": round(alpha_daily * 252 * 100.0, 2),
            "r_squared": round(r2, 3),
            "market_contribution_pct": round(market_part, 2),
            "alpha_contribution_pct": round(alpha_part, 2),
            "realized_total_pct": round(realized, 2),
            "total_perf": total,
            "missing_factors": ["섹터", "규모(size)", "모멘텀"],
            "missing_reason": "횡단면 팩터 포트폴리오 수익률 미연동 — 시장 팩터만 회귀했습니다.",
        }

    def calculate_portfolio_risk_budget(self, positions=None, b_engine=None,
                                        market_regime_code=None):
        """
        [Section 22-4] 포트폴리오 위험예산 · 현금 비중 가이드.

        보유 종목이 입력되면 실제 일봉으로 계산한다:
            비중 · 집중도(HHI) · 종목 간 상관 · 포트폴리오 변동성 · 과거 최대낙폭
        보유 구성이 없으면 산출하지 않는다 (임의의 표준 배분을 만들어내지 않는다).

        ⚠️ 평균 매수가는 여기에 들어가지 않는다. 비중은 '현재 평가금액' 기준이다 —
           평단가를 위험 산출에 넣으면 비싸게 산 종목의 위험이 과대평가된다.
        """
        if not positions:
            return {
                "available": False,
                "reason": "보유 포트폴리오 구성 미입력 — 팩터 노출도·집중도·현금비중 산출 불가",
            }

        rows, missing = [], []
        for p in positions:
            ticker = p['ticker'] if isinstance(p, dict) else getattr(p, 'ticker', None)
            name = p['stock_name'] if isinstance(p, dict) else getattr(p, 'stock_name', ticker)
            qty = float(p['quantity'] if isinstance(p, dict) else getattr(p, 'quantity', 0))
            if not ticker or qty <= 0:
                continue
            closes = None
            if b_engine is not None:
                try:
                    prices, _f = b_engine.load_bitemporal_data(ticker, "2023-01-01")
                    closes = prices['adj_close'].values.astype(float)
                except Exception as exc:
                    missing.append(f"{name}: {type(exc).__name__}")
            if closes is None or len(closes) < 120:
                missing.append(f"{name}: 일봉 부족")
                continue
            rows.append({'ticker': ticker, 'name': name, 'qty': qty, 'closes': closes})

        if len(rows) < 1:
            return {"available": False,
                    "reason": "보유 종목의 가격 시계열을 받지 못해 산출 불가",
                    "missing": missing}

        # 공통 구간으로 정렬 (가장 짧은 종목 기준)
        n = min(len(r['closes']) for r in rows)
        n = int(min(n, 500))
        mat = np.vstack([r['closes'][-n:] for r in rows])
        values = np.array([r['qty'] * r['closes'][-1] for r in rows], dtype=float)
        total_value = float(values.sum())
        if total_value <= 0:
            return {"available": False, "reason": "평가금액 합계가 0 — 산출 불가"}
        w = values / total_value

        rets = np.diff(mat, axis=1) / mat[:, :-1]
        rets = np.nan_to_num(rets, nan=0.0, posinf=0.0, neginf=0.0)

        port_ret = w @ rets
        port_vol_daily = float(np.std(port_ret, ddof=1))
        port_vol_annual = port_vol_daily * np.sqrt(252) * 100.0

        # 가중평균 개별 변동성 대비 — 분산효과
        indiv_vol = np.std(rets, axis=1, ddof=1)
        weighted_indiv = float(w @ indiv_vol) * np.sqrt(252) * 100.0
        diversification = (1.0 - port_vol_annual / weighted_indiv) * 100.0 if weighted_indiv > 0 else 0.0

        corr = np.corrcoef(rets) if len(rows) > 1 else np.array([[1.0]])
        off = corr[np.triu_indices(len(rows), k=1)] if len(rows) > 1 else np.array([])
        avg_corr = float(np.mean(off)) if off.size else None
        max_corr = float(np.max(off)) if off.size else None

        hhi = float(np.sum(w ** 2))
        eff_n = 1.0 / hhi if hhi > 0 else 0.0

        curve = np.cumprod(1.0 + port_ret)
        mdd = float((curve / np.maximum.accumulate(curve) - 1.0).min() * 100.0)

        # 현금 비중 가이드 — 집중도·변동성·시장국면으로 정한다
        cash = 10.0
        why = []
        if hhi > 0.50:
            cash += 20.0
            why.append(f"집중도 과다 (HHI {hhi:.2f}, 유효 종목수 {eff_n:.1f}개)")
        elif hhi > 0.34:
            cash += 10.0
            why.append(f"집중도 다소 높음 (유효 종목수 {eff_n:.1f}개)")
        if port_vol_annual > 45.0:
            cash += 20.0
            why.append(f"연환산 변동성 {port_vol_annual:.0f}%")
        elif port_vol_annual > 30.0:
            cash += 10.0
            why.append(f"연환산 변동성 {port_vol_annual:.0f}%")
        if avg_corr is not None and avg_corr > 0.60:
            cash += 10.0
            why.append(f"종목 간 평균 상관 {avg_corr:.2f} (분산효과 낮음)")
        if market_regime_code in ('BEAR_PANIC',):
            cash += 20.0
            why.append("시장 국면: 급락장")
        elif market_regime_code in ('SIDEWAYS',):
            cash += 5.0
            why.append("시장 국면: 횡보")
        cash = float(np.clip(cash, 10.0, 70.0))

        holdings = [{
            'name': r['name'], 'ticker': r['ticker'],
            'value': float(values[i]), 'weight_pct': float(w[i] * 100.0),
            'vol_annual_pct': float(indiv_vol[i] * np.sqrt(252) * 100.0),
            'risk_contribution_pct': float(
                w[i] * (corr[i] @ (w * indiv_vol)) * np.sqrt(252) * 100.0),
        } for i, r in enumerate(rows)]
        rc_sum = sum(h['risk_contribution_pct'] for h in holdings)
        for h in holdings:
            h['risk_share_pct'] = (h['risk_contribution_pct'] / rc_sum * 100.0
                                   if rc_sum > 0 else None)

        return {
            "available": True,
            "n_holdings": len(rows),
            "window_days": int(n),
            "total_value": total_value,
            "holdings": sorted(holdings, key=lambda h: -h['weight_pct']),
            "hhi": round(hhi, 3),
            "effective_n": round(eff_n, 2),
            "avg_correlation": round(avg_corr, 3) if avg_corr is not None else None,
            "max_correlation": round(max_corr, 3) if max_corr is not None else None,
            "portfolio_vol_annual_pct": round(port_vol_annual, 2),
            "weighted_indiv_vol_pct": round(weighted_indiv, 2),
            "diversification_benefit_pct": round(diversification, 1),
            "historical_mdd_pct": round(mdd, 2),
            "recommended_cash_pct": cash,
            "cash_reasons": why or ["집중도·변동성·상관 모두 기준 이내 (기본 10%)"],
            "missing": missing,
            "note": "비중은 현재 평가금액 기준입니다. 평균 매수가는 위험 산출에 넣지 않습니다.",
        }

    def calculate_backtest_costs_and_metrics(self, sim_res, oos=None, is_large_cap=True):
        """
        [Section 7 & 12] 거래비용 차감 성과 + 표본외 확률 보정 품질.
        Brier/MAE 는 표본외 예측-실현 쌍에서만 산출된다 (run_blind_oos_backtest).
        구버전은 0.142 / 3.2% 리터럴이었다.
        """
        raw_perf = sim_res.get('mean_perf') if sim_res else None
        show_prob = bool(sim_res and sim_res.get('probabilities_shown'))
        oos_ok = bool(oos and oos.get('available'))
        return {
            "total_cost_pct": self.TOTAL_COST_PCT,
            "cost_breakdown": self.COST_BREAKDOWN,
            "raw_perf": raw_perf,
            "net_perf": round(raw_perf - self.TOTAL_COST_PCT, 2) if raw_perf is not None else None,
            "brier_score": oos.get('brier_score') if oos_ok else None,
            "mae_pct": oos.get('mae_pct') if oos_ok else None,
            "oos_hit_pct": oos.get('directional_hit_pct') if oos_ok else None,
            "oos_predictions": oos.get('n_predictions') if oos_ok else None,
            "profit_factor": (oos.get('profit_factor') if oos_ok
                              else (sim_res.get('profit_factor') if sim_res else None)),
            "win_rate_20d": sim_res.get('obs_win_ratio') if show_prob else None,
            "sample_note": (sim_res.get('sample_tier_label') if sim_res else "표본 없음"),
            "calibration_status": (
                f"표본외 {oos['n_predictions']}건 기준 (학습 {oos['train_bars']}봉 / 검증 {oos['oos_bars']}봉, "
                f"embargo {oos['embargo']}봉)" if oos_ok
                else f"표본외 검증 미수행 — {(oos or {}).get('reason', '사유 미상')}"),
        }



    def run_full_pipeline(self, symbol, t_ref_str, b_engine=None, rho_cutoff=0.80):
        """
        [명세 §17] 모든 화면이 공유하는 단일 최종 스냅샷.

        상단 TOP3 표와 개별 상세화면은 반드시 이 함수가 만든 '같은 객체'를 써야 한다.
        (구버전은 web_app.run_quant_pipeline 과 run_screener_scan 이 각각 따로
         파이프라인을 돌려, 한 화면에 두 시점의 값이 섞여 표시될 수 있었다.)
        """
        import datetime as _dt
        import pandas as pd

        if b_engine is None:
            from bitemporal_engine import BitemporalEngine
            b_engine = BitemporalEngine()
        from bitemporal_engine import STOCK_METRICS_DB

        # ── 리플레이(과거 기준일) 판정 ──────────────────────────────────
        # t_ref 가 과거면 '그 날 알 수 있었던 것'만 써야 한다. 오늘의 실시간
        # 시세·지수 국면·뉴스를 과거 판정에 섞으면 전부 미래 누수다.
        # 리플레이에서는 이 셋을 모두 끄고(미수신 처리), 현재가는 기준일 종가를 쓴다.
        #
        # 단, 주말·연휴에는 t_ref(마지막 거래일)가 어제·그제가 되는 것이 정상 운영이다.
        # 그때 라이브 데이터를 끄면 앱이 주말마다 반쪽이 된다. 5일 이내는 라이브,
        # 그보다 오래된 기준일만 리플레이로 본다 (캘리브레이션 랩은 전부 1달 이상 과거).
        try:
            _tref_dt = _dt.datetime.strptime(str(t_ref_str)[:10], '%Y-%m-%d')
            is_replay = (_dt.datetime.now() - _tref_dt).days > 5
        except ValueError:
            is_replay = False

        # 시장 국면 컨텍스트는 같은 시장 안에서는 종목마다 같으므로 캐시한다.
        # ⚠️ 시장별로 따로 캐시해야 한다. 하나만 들고 있으면 코스피 종목을 먼저 본 뒤
        #    코스닥 종목을 볼 때 코스피 국면이 그대로 재사용된다.
        _mkt = "KOSDAQ" if symbol.endswith(".KQ") else "KOSPI"
        if is_replay:
            self.market_regime_ctx = None      # 오늘 지수 국면은 과거 판정에 못 쓴다
        else:
            if not hasattr(self, '_regime_by_market'):
                self._regime_by_market = {}
            if _mkt not in self._regime_by_market:
                self._regime_by_market[_mkt] = b_engine.get_index_regime(_mkt)
            self.market_regime_ctx = self._regime_by_market[_mkt]

        # 시장·글로벌·뉴스 컨텍스트 — 이 종목만 보지 않고 판을 함께 본다.
        # 실패해도 분석 자체는 계속한다(미수신으로 남기고 상한도 걸지 않는다).
        try:
            if is_replay:
                raise RuntimeError("리플레이 — 오늘의 시장·뉴스 컨텍스트를 쓰지 않는다")
            import market_context as _mctx
            self.market_context = _mctx.build_market_context(
                b_engine, symbol, str(symbol).split('.')[0])
        except Exception as _cexc:
            self.market_context = {
                'market': _mkt, 'domestic': {'available': False},
                'global': {}, 'global_warnings': [],
                'news': {'available': False, 'items': [],
                         'reason': f'{type(_cexc).__name__}: {_cexc}'},
                'news_flags': {'risk_titles': [], 'risk_count': 0,
                               'watch_count': 0, 'total': 0},
                'caps': {}, 'cap_score': None, 'reasons': [],
                'notes': [f'시장·뉴스 컨텍스트 수집 실패 ({type(_cexc).__name__})'],
            }

        prices_df, fund_df = b_engine.generate_synthetic_bitemporal_data(
            symbol=symbol, start_date='2020-01-01', end_date=t_ref_str)

        # 자산 유형 판별 — 주식/일반 ETF/레버리지/인버스는 게이트를 다르게 탄다
        _sm_name = (STOCK_METRICS_DB.get(symbol) or {}).get('name', '')
        self._asset_type_name = _sm_name

        if is_replay:
            # 과거 기준일: 오늘 시세를 주입하면 그 자체가 미래 누수다.
            # 기준일까지의 마지막 종가가 '그 날의 현재가'다.
            # ⚠️ 데이터 계층이 종목별 전체 이력을 캐시하므로 end_date 를 믿지 말고
            #    여기서 기준일 초과 봉을 직접 잘라낸다 — 이걸 빼먹으면 리플레이
            #    판정에 미래 봉이 섞인다 (실제로 §54 가 잡아낸 누수).
            if prices_df is not None and not prices_df.empty:
                prices_df = prices_df[
                    prices_df['trade_date'].astype(str) <= str(t_ref_str)
                ].reset_index(drop=True)
            if prices_df is None or prices_df.empty:
                raise ValueError(f"{symbol}: {t_ref_str} 이전 가격 이력이 없습니다")
            rt_price = float(prices_df['adj_close'].iloc[-1])
            rt_status = f"리플레이 — {prices_df['trade_date'].iloc[-1]} 종가 기준"
            matrix_data = []
        else:
            rt_price, rt_status, matrix_data = b_engine.get_realtime_stock_price_triple_check(symbol)
            sm = STOCK_METRICS_DB.get(symbol, {})
            open_p = float(sm.get('open_p', rt_price))
            high_p = float(sm.get('high_p', max(rt_price, open_p)))
            low_p = float(sm.get('low_p', min(rt_price, open_p)))
            vol_p = float(sm.get('volume', 1000000.0))

            # 이상치 보정: 현재가 대비 ±25% 밖의 OHLC는 신뢰하지 않는다
            if not (rt_price * 0.75 <= high_p <= rt_price * 1.25): high_p = rt_price * 1.005
            if not (rt_price * 0.75 <= low_p <= rt_price * 1.25):  low_p = rt_price * 0.995
            if not (rt_price * 0.75 <= open_p <= rt_price * 1.25): open_p = rt_price

            rt_row = pd.DataFrame([{
                'trade_date': t_ref_str,
                'open': open_p, 'high': high_p, 'low': low_p,
                'close': rt_price, 'adj_close': rt_price, 'volume': vol_p,
                # 수급이 미연동이면 NaN — 0이나 임의값으로 채우지 않는다
                'foreign_net': float(sm['net_f']) if sm.get('net_f') is not None else np.nan,
                'institution_net': float(sm['net_i']) if sm.get('net_i') is not None else np.nan,
                'retail_net': float(sm['net_r']) if sm.get('net_r') is not None else np.nan,
            }])
            if not prices_df.empty and prices_df['trade_date'].iloc[-1] == t_ref_str:
                prices_df = prices_df.iloc[:-1]
            prices_df = pd.concat([prices_df, rt_row], ignore_index=True)

        tech_df = self.compute_technical_indicators(prices_df)
        sim_res = self.run_self_similarity_backtest(tech_df, t_ref_str, 20, rho_cutoff)
        val_eval = self.evaluate_valuation_metric(tech_df, fund_df, symbol=symbol)

        # [§14] 표본외 검증을 먼저 수행하고, 그 결과를 점수 엔진이 상한 산정에 쓴다.
        oos_result = self.run_blind_oos_backtest(tech_df, horizon=20, rho_cutoff=rho_cutoff)
        strategy_quality = self.compute_strategy_quality(oos_result)
        self.current_oos_result = oos_result

        # 상대 모멘텀(12-1) — Jegadeesh–Titman(1993). 벤치마크는 상장 시장 지수.
        # 지수를 못 받으면 None 으로 남기고 점수에 개입하지 않는다.
        # 리플레이에서는 지수 시계열이 오늘 기준이라(과거 구간 대조 불가) 쓰지 않는다.
        self._rel_mom_ctx = None
        try:
            if is_replay:
                raise RuntimeError("리플레이 — 오늘 기준 지수 시계열을 쓰지 않는다")
            _stk_mom = self.momentum_12_1(tech_df['adj_close'].values)
            _mkt_name = "KOSDAQ" if symbol.endswith(".KQ") else "KOSPI"
            if not hasattr(self, '_idx_daily_cache'):
                self._idx_daily_cache = {}
            if _mkt_name not in self._idx_daily_cache:
                self._idx_daily_cache[_mkt_name] = b_engine.fetch_index_daily(_mkt_name, 400)
            _idx = self._idx_daily_cache[_mkt_name]
            _idx_mom = self.momentum_12_1(_idx[1]) if _idx is not None else None
            if _stk_mom is not None and _idx_mom is not None:
                self._rel_mom_ctx = {
                    'stock': round(_stk_mom, 1), 'index': round(_idx_mom, 1),
                    'relative': round(_stk_mom - _idx_mom, 1), 'market': _mkt_name}
        except Exception:
            self._rel_mom_ctx = None

        # 실전 판정 성적 자기보정 — TipRanks Smart Score 방식: 예측 주체의 과거
        # 적중률로 신호를 가중한다. 여기서 '주체'는 이 앱 자신이다(판정 성적표).
        # 기록이 없으면(클라우드) None 으로 두고 개입하지 않는다.
        if is_replay:
            self._track_summary = getattr(self, '_track_summary', None)
        elif not hasattr(self, '_track_summary'):
            self._track_summary = None
            try:
                import prediction_log as _plog_tr
                if _plog_tr.load_predictions():
                    _g_tr, _s_tr = _plog_tr.evaluate_all(b_engine, max_rows=80)
                    self._track_summary = _s_tr
            except Exception:
                self._track_summary = None

        four_scores = self.compute_four_separated_scores(symbol, tech_df, fund_df, sim_res, val_eval)
        price_pos = self.compute_decoupled_price_position(tech_df, val_eval)
        self.current_oos_result = None      # 종목 간 누수 방지

        last_row = prices_df.iloc[-1]
        meta = {
            'run_id': f"RUN-{_dt.datetime.now().strftime('%Y%m%d')}-{symbol.split('.')[0][-5:]}",
            'symbol': symbol,
            'analysis_date': t_ref_str,
            'price_asof': str(last_row.get('trade_date')),
            'price_type': '수정 종가 (adj_close) — 장중 현재가 미혼용',
            'price_source': str(prices_df['data_source'].iloc[0]) if 'data_source' in prices_df.columns else 'unknown',
            'fiscal_asof': str(fund_df['available_date'].iloc[-1]) if len(fund_df) else None,
            'fiscal_is_estimated': bool(fund_df['is_estimated'].iloc[-1]) if 'is_estimated' in fund_df.columns else None,
            'currency': 'KRW' if symbol.endswith(('.KS', '.KQ')) else 'USD',
            'amount_unit': '원 (KRW), 거래대금은 원 단위 정수',
            'data_version': f"bars={len(prices_df)}|asof={last_row.get('trade_date')}",
            'calc_version': self.CALC_VERSION,
            'model_version': self.MODEL_VERSION,
            'rulebook_version': self.RULEBOOK_VERSION,
            'rho_cutoff': rho_cutoff,
            'generated_at': _dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'generated_ts': _dt.datetime.now().timestamp(),
        }

        snap = QuantSnapshot({
            'meta': meta,
            'symbol': symbol,
            't_ref': t_ref_str,
            'rho_cutoff': rho_cutoff,
            'generated_at': meta['generated_at'],
            'prices_df': prices_df,
            'fund_df': fund_df,
            'tech_df': tech_df,
            'sim_res': sim_res,
            'val_eval': val_eval,
            'four_scores': four_scores,
            'price_pos': price_pos,
            'oos_result': oos_result,
            'strategy_quality': strategy_quality,
            'rt_price': rt_price,
            'rt_status': rt_status,
            'is_replay': is_replay,
            'source_matrix': matrix_data,
            # 교차검증 결과를 스냅샷에 실어 둔다.
            # 예전에는 상세화면만 1% 게이트를 걸고 스캐너는 그냥 통과시켰다.
            # 출처 간 가격이 벌어진 종목이 추천 후보로 올라올 수 있었다.
            'price_cross_check': self._price_cross_check(matrix_data),
            # 시장·글로벌·뉴스 컨텍스트 원본 (화면이 그대로 보여준다)
            'market_context': getattr(self, 'market_context', None),
        })
        self.apply_integrity_gates(snap)
        return snap

    #: 출처 간 현재가 허용 오차 (이 이상 벌어지면 시세를 신뢰할 수 없다)
    PRICE_CROSS_TOL_PCT = rb('RULES_DATA_INTEGRITY', 'price_cross_tolerance_pct', 1.0)

    @classmethod
    def _price_cross_check(cls, matrix_data):
        """
        출처 매트릭스 → 교차검증 결과.
        반환: {'base','compare','diff_pct','passed','note'}
        가격을 가진 출처가 하나뿐이면 '대조 불가' 로 남기고 통과시키지 않는다
        (없는 검증을 통과로 위장하지 않는다).
        """
        priced = [r for r in (matrix_data or []) if r.get('price') is not None]
        if len(priced) < 2:
            return {'base': priced[0]['price'] if priced else None, 'compare': None,
                    'diff_pct': None, 'passed': None,
                    'note': f"가격 보유 출처 {len(priced)}개 — 교차 대조 불가"}
        base = float(priced[0]['price'])
        comp = float(priced[1]['price'])
        diff = abs(comp - base) / max(base, 1e-9) * 100.0
        return {'base': base, 'compare': comp, 'diff_pct': round(diff, 4),
                'passed': diff <= cls.PRICE_CROSS_TOL_PCT,
                'note': (f"{priced[0]['source'][:12]} {base:,.0f} vs "
                         f"{priced[1]['source'][:12]} {comp:,.0f} → 오차 {diff:.2f}%")}

    # ══════════════════════════════════════════════════════════════════════
    # 개인화 계층 — 평균 매수가는 여기서만 쓴다.
    # market_snapshot 은 절대 수정하지 않으며, 평단가가 예측·적정가·점수에
    # 역으로 흘러 들어가지 못하도록 별도 객체로 분리한다.
    # ══════════════════════════════════════════════════════════════════════
    HOLDER_ACTION_TITLES = {
        'ADD': '추가매수 검토', 'HOLD': '보유 유지', 'TRIM_ON_BOUNCE': '반등 시 비중축소',
        'TRIM_NOW': '즉시 일부 축소', 'STOP': '손절 기준 준수', 'PENDING': '판단 보류',
    }

    def personalize_for_position(self, market_snapshot, average_buy_price, quantity,
                                 portfolio_weight_pct=None):
        """
        시장 스냅샷 + 내 포지션 → 보유자 관점 판정.
        market_snapshot 은 읽기만 한다.
        """
        fs = market_snapshot['four_scores']
        sim = market_snapshot['sim_res']
        tech = market_snapshot['tech_df']
        px = float(tech['adj_close'].iloc[-1])

        avg = float(average_buy_price)
        qty = float(quantity)
        cost_basis = qty * avg
        market_value = qty * px
        unrealized_profit = market_value - cost_basis
        unrealized_return = (px / avg - 1.0) * 100.0 if avg > 0 else None
        # 본전 회복에 필요한 상승률 — 손실률의 반대값이 아니다
        recovery_required = (avg / px - 1.0) * 100.0 if px > 0 else None

        tp1, sl = fs.get('target_tech_1st'), fs.get('stop_loss_price')
        fair = fs.get('displayed_fair_value')

        # ── 보유자 행동점수 구성요소 (0~100) ──────────────────────────────
        market_component = float(fs.get('final_action_score', 0))

        # 손익·평단 위치: 이익 중이면 여유, 손실 중이면 압박. 손실이 크다고 점수를 올리지 않는다.
        if unrealized_return is None:
            pnl_component = 50.0
        elif unrealized_return >= 20: pnl_component = 80.0
        elif unrealized_return >= 5:  pnl_component = 70.0
        elif unrealized_return >= -5: pnl_component = 55.0
        elif unrealized_return >= -15: pnl_component = 42.0
        elif unrealized_return >= -30: pnl_component = 32.0
        else:                          pnl_component = 22.0

        # 다중기간 경로 전망 — 산출 가능한 지평의 방향 비율
        hz = sim.get('horizons_data') or {}
        scored = [h for h in hz.values() if h.get('win_rate') is not None]
        if scored:
            up_ratio = sum(1 for h in scored if h['win_rate'] >= 50.0) / len(scored)
            path_component = float(np.clip(20 + up_ratio * 70, 0, 100))
        else:
            path_component = 50.0

        # 손절·회복 가능성
        if sl is not None and px > 0:
            dist_to_stop = (px - sl) / px * 100.0
            stop_component = float(np.clip(30 + dist_to_stop * 4, 0, 100))
        else:
            stop_component = 50.0
        if recovery_required is not None and recovery_required > 0:
            # 본전까지 많이 남을수록 회복 난이도가 높다
            stop_component = float(np.clip(stop_component - min(30.0, recovery_required * 0.8), 0, 100))

        # 포트폴리오 위험기여도 (비중이 클수록 감점)
        if portfolio_weight_pct is None:
            weight_component = 60.0
        elif portfolio_weight_pct <= 10: weight_component = 80.0
        elif portfolio_weight_pct <= 20: weight_component = 65.0
        elif portfolio_weight_pct <= 35: weight_component = 45.0
        else:                            weight_component = 25.0

        event_component = float(fs.get('risk_safety_score', 50))

        holder_action_score = int(round(
            market_component * 0.35 + pnl_component * 0.15 + path_component * 0.20
            + stop_component * 0.15 + weight_component * 0.10 + event_component * 0.05))

        # ── 등급 판정 ────────────────────────────────────────────────────
        sample_ok = bool(sim.get('probabilities_shown'))
        below_stop = (sl is not None and px <= sl)
        m10_broken = (fs.get('m10_status') == '아래' and (fs.get('m10_slope') or 0) < 0)

        if market_snapshot.get('status') == 'REVIEW_REQUIRED' or not sample_ok:
            key = 'PENDING'
        elif below_stop:
            key = 'STOP'
        elif holder_action_score >= 68 and fs.get('eligible_for_top3'):
            key = 'ADD'
        elif holder_action_score >= 58:
            key = 'HOLD'
        elif holder_action_score >= 48:
            key = 'TRIM_ON_BOUNCE' if not m10_broken else 'TRIM_NOW'
        else:
            key = 'TRIM_NOW'

        # ── 물타기 허용 조건 (전부 통과할 때만) ──────────────────────────
        ey = fs.get('net_expected_return')
        rr = fs.get('reward_risk_ratio')
        add_checks = [
            ("신규 진입 조건 통과", bool(fs.get('eligible_for_top3'))),
            ("거래비용 차감 후 기대수익 양수", ey is not None and ey > 0),
            ("손익비 기준 통과", rr is not None and rr >= self.GATES.get('min_reward_risk', 1.3)),
            ("중기 추세 유지", not m10_broken),
            ("포트폴리오 비중 상한 미초과",
             portfolio_weight_pct is None or portfolio_weight_pct <= 25.0),
            ("데이터·표본 게이트 통과", sample_ok and market_snapshot.get('status') == 'OK'),
        ]
        averaging_down_allowed = all(ok for _, ok in add_checks)
        if key == 'ADD' and not averaging_down_allowed:
            key = 'HOLD'

        return {
            'average_buy_price': avg, 'quantity': qty,
            'cost_basis': cost_basis, 'market_value': market_value,
            'unrealized_profit': unrealized_profit,
            'unrealized_return_pct': unrealized_return,
            'recovery_required_pct': recovery_required,
            'distance_to_stop_pct': ((px - sl) / px * 100.0) if sl else None,
            'distance_to_target_pct': ((tp1 - px) / px * 100.0) if tp1 else None,
            'avg_vs_fair_value_pct': ((avg / fair - 1.0) * 100.0) if fair else None,
            'portfolio_weight_pct': portfolio_weight_pct,
            'holder_action_score': holder_action_score,
            'holder_action_key': key,
            'holder_action_title': self.HOLDER_ACTION_TITLES[key],
            'components': {
                '시장 최종 행동점수 35%': round(market_component, 1),
                '손익·평단 위치 15%': round(pnl_component, 1),
                '다중기간 경로 20%': round(path_component, 1),
                '손절·회복 가능성 15%': round(stop_component, 1),
                '포트폴리오 위험기여 10%': round(weight_component, 1),
                '이벤트 위험 5%': round(event_component, 1),
            },
            'averaging_down_allowed': averaging_down_allowed,
            'averaging_down_checks': add_checks,
            # 신규 진입 의견은 시장 스냅샷 그대로 — 개인 평단과 무관하다
            'new_entry_title': fs.get('final_action_title'),
            'new_entry_score': fs.get('final_action_score'),
        }

    def apply_integrity_gates(self, snap):
        """
        [명세 §18] 스냅샷 전체를 가로질러 모순을 검사한다.
        개별 모듈 안에서는 보이지 않고 '모듈 간 대조'에서만 드러나는 것들을 잡는다.
        하나라도 걸리면 status=REVIEW_REQUIRED, eligible_for_top3=False 로 강등한다.
        """
        fs, val, sim = snap['four_scores'], snap['val_eval'], snap['sim_res']
        tech, meta = snap['tech_df'], snap['meta']
        px = float(tech['adj_close'].iloc[-1])
        issues = list(fs.get('contradiction_reasons', []) or [])

        # 1) 적정가·괴리율이 모듈 간 불일치
        if fs.get('displayed_fair_value') != val.get('displayed_fair_value'):
            issues.append("적정가가 점수엔진과 가치평가엔진에서 다름")
        if fs.get('upside_pct') != val.get('upside_pct'):
            issues.append("상승여력이 점수엔진과 가치평가엔진에서 다름")

        # 2) 신뢰도 미달인데 권장 매수가가 산출됨
        if not fs.get('fair_value_usable') and fs.get('recommended_buy_price') is not None:
            issues.append("적정가 신뢰도 미달인데 권장 매수가 산출")

        # 3) 표본 부족인데 경로 확률이 노출됨
        if not sim.get('probabilities_shown') and (
                sim.get('tp_first_prob') is not None or sim.get('sl_first_prob') is not None):
            issues.append("표본 부족인데 목표가·손절가 도달확률 노출")

        # 4) 확률 미산출인데 확률 문자열이 숫자로 표시됨
        if not sim.get('probabilities_shown') and fs.get('target_first_prob') not in (None, "미산출"):
            issues.append("확률 미산출 상태와 표시값 불일치")

        # 5) 가격 기준시점 혼용
        if str(tech['trade_date'].iloc[-1]) != str(meta.get('price_asof')):
            issues.append("가격 기준시각이 메타와 시계열에서 다름")

        # 6) 다중기간 전망이 충돌하는데 매수 판정 — 이것은 데이터 오류가 아니라
        #    신호 간 이견이다. 판정을 폐기하지 않고 관망으로 화해시킨다 (§18 과 동일 원칙).
        hz = sim.get('horizons_data') or {}
        scored = [h['win_rate'] for h in hz.values() if h.get('win_rate') is not None]
        if len(scored) >= 3:
            up = sum(1 for w in scored if w >= 50.0)
            conflicted = 0.35 <= (up / len(scored)) <= 0.65
            if conflicted and fs.get('final_action_title') in self.BUY_INTENT_TITLES:
                fs['final_action_title'] = "조건 확인·관망"
                fs['final_action_score'] = min(fs.get('final_action_score', 0), 67)
                fs.setdefault('soft_conflict_notes', []).append(
                    "매수 의도였으나 다중기간 전망 충돌 → 관망으로 하향 (상한 67점)")

        # 7) 데이터 출처 실패인데 정상으로 표기
        for row in (snap.get('source_matrix') or []):
            if '실패' in str(row.get('status', '')) and row.get('price') is not None:
                issues.append(f"{row['source']} 수신 실패인데 가격 표시")

        # 8) 현재가가 매수범위 밖인데 분할매수 판정
        bem = fs.get('buy_entry_max')
        if fs.get('final_action_title') in self.BUY_INTENT_TITLES and (bem is None or px > bem):
            issues.append("현재가가 매수 허용범위 밖인데 매수 판정")

        # 9) 과거예측 점수와 유효표본 상태 충돌
        if fs.get('eff_sample_size', 0) < 5 and (fs.get('hist_status') == 'Valid'):
            issues.append("유효표본 5건 미만인데 과거예측 유효 판정")

        issues = list(dict.fromkeys(issues))     # 중복 제거, 순서 유지
        failed = bool(issues)
        snap['contradictions'] = issues
        snap['status'] = "REVIEW_REQUIRED" if failed else "OK"
        snap['eligible_for_top3'] = (not failed) and bool(fs.get('eligible_for_top3'))
        if failed:
            fs['final_action_title'] = '⚠️ 재검토 필요'
            fs['final_action_score'] = min(fs.get('final_action_score', 0), 49)
            fs['eligible_for_top3'] = False
            fs['contradiction_detected'] = True
            fs['contradiction_reasons'] = issues
        return snap

    def run_screener_scan(self, universe, t_ref_str, b_engine=None, rho_cutoff=0.80):
        """
        전체 시장 스캐닝: 각 종목의 상세분석을 수행하고 최종 행동 결합판정 기준 정렬.
        각 행에 run_full_pipeline 스냅샷 전체를 실어 상세화면이 동일 객체를 재사용하게 한다.
        """
        results = []
        self.last_scan_failures = []   # 조용히 사라지는 종목이 없도록 실패 사유를 남긴다

        for stock in universe:
            symbol = stock['symbol']
            try:
                snap = self.run_full_pipeline(symbol, t_ref_str, b_engine=b_engine, rho_cutoff=rho_cutoff)
                scores = snap['four_scores']
                rt_price = snap['rt_price']
            except Exception as exc:
                self.last_scan_failures.append({
                    "symbol": symbol, "name": stock.get("name", symbol),
                    "reason": f"{type(exc).__name__}: {exc}"
                })
                continue

            # 시세 교차검증 게이트 — 상세화면에만 있던 방어를 스캔 경로에도 건다.
            # 출처 간 가격이 벌어진 종목은 그 위에 쌓은 점수·적정가를 믿을 수 없다.
            _cc = snap.get('price_cross_check') or {}
            if _cc.get('passed') is False:
                self.last_scan_failures.append({
                    "symbol": symbol, "name": stock.get("name", symbol),
                    "reason": f"시세 교차검증 실패 — {_cc.get('note')} "
                              f"(허용 {self.PRICE_CROSS_TOL_PCT:.1f}%)"
                })
                continue

            # 유동성 필터: 실제 20일 평균 거래대금 기준 (당일 거래량이 아니라 가격 이력 기반)
            avg_turnover_20d = snap['four_scores'].get('avg_turnover_20d')
            if avg_turnover_20d is not None and avg_turnover_20d < self.MIN_AVG_TURNOVER_KRW:
                self.last_scan_failures.append({
                    "symbol": symbol, "name": stock.get("name", symbol),
                    "reason": f"20일 평균 거래대금 {avg_turnover_20d/1e8:,.1f}억원 < "
                              f"{self.MIN_AVG_TURNOVER_KRW/1e8:,.0f}억원"
                })
                continue

            # 분류 — 무결성 게이트에서 강등된 종목은 추천 대상에서 제외
            title = scores.get('final_action_title', '거래 회피')
            if snap.get('status') == 'REVIEW_REQUIRED':
                cat = "⚠️ 재검토 필요"
            elif not snap.get('eligible_for_top3', False):
                if "매수" in title or "진입" in title:
                    # eligible 안 되면 좌천
                    cat = "⏳ 눌림 대기" if "조건 확인" in title else "👀 관찰 후보"
                else:
                    cat = "🚫 추천 제외"
            else:
                cat = "🏆 최종 추천주"
                
            if "거래 회피" in title or "신규 매수 보류" in title or "비중축소" in title:
                cat = "🚫 추천 제외"

            # 적정가·표본이 없으면 None을 0으로 바꾸지 않는다 (미산출은 미산출로 전달)
            results.append({
                "symbol": symbol,
                "name": stock["name"],
                "market": stock["market"],
                "base_price": rt_price,
                "target_fundamental": scores.get('displayed_fair_value'),
                "upside_pct": scores.get('upside_pct'),
                "upside_eval": scores.get('upside_eval', '가치판단 보류'),
                "recommended_buy_price": scores.get('recommended_buy_price'),
                "cat": cat,
                "final_score": scores['final_action_score'],
                "sq": scores['stock_quality_score'],
                "tt": scores['trading_timing_score'],
                "rs": scores['risk_safety_score'],
                "opp": scores.get('opportunity_score', 0),
                "exe": scores.get('execution_score', 0),
                "net_ev": scores.get('net_expected_return'),
                "win_rate": scores.get('win_rate'),
                "reward_risk_ratio": scores.get('reward_risk_ratio'),
                "analysis_confidence": scores.get('analysis_confidence', 0),
                "tp_1st": scores['target_tech_1st'],
                "sl_1st": scores['stop_loss_price'],
                "strategy_type": scores.get('strategy_type', '⚡ 실적 모멘텀형'),
                "m10_status": scores.get('m10_status', '위'),
                "m10_disparity": scores.get('m10_disparity', 0.0),
                "m10_trend_eval": scores.get('m10_trend_eval', '양호'),
                # 차트 관점 배지 — 월봉 10선 위 여부 · DeMARK 매수 신호 상태.
                # 진입 후보 = 적정가 이하 진입 & 순기대수익 양수 (리플레이 327건에서
                # 적중률 68.0%, 기준 대비 +5.3%p 로 실증된 결합 조건)
                "m10_above": bool(float(scores.get('m10_disparity', 0) or 0) >= 0),
                "demark_entry_state": ((scores.get('demark_entry') or {}).get('state')),
                "entry_candidate": bool(
                    '초과' not in str(scores.get('entry_zone') or '')
                    and (scores.get('net_expected_return') or -1) > 0),
                "top3_block_reasons": scores.get('top3_block_reasons', []),
                "scores_obj": scores,
                # [§17] 상세화면이 재계산 없이 그대로 쓰는 단일 스냅샷
                "snapshot": snap,
            })

        # [명세 §15] 정렬 우선순위: 진입 후보 → 최종 행동점수 → 기회점수 → 순기대수익
        # → 손익비 → 분석 신뢰도. 진입 후보를 앞세우는 근거는 리플레이 327건 실측
        # (후보 68.0% vs 기준 62.7%). 점수가 같으면 실제로 살 수 있는 종목이 먼저다.
        # (미산출 항목은 -inf로 두어 산출된 종목보다 뒤로 보낸다)
        def _n(v):
            return float(v) if v is not None else float('-inf')

        results.sort(key=lambda x: (
            1 if x.get("entry_candidate") else 0,
            _n(x["final_score"]),
            _n(x["opp"]),
            _n(x["net_ev"]),
            _n(x["reward_risk_ratio"]),
            _n(x["analysis_confidence"]),
        ), reverse=True)

        return results

