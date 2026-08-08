import pandas as pd
import numpy as np
import os
from leakage_guard import LeakageGuard
from bitemporal_engine import STOCK_METRICS_DB


def _num(v, spec=",.0f", suffix="", na="미산출"):
    """None 안전 포맷터 — 값이 없으면 0으로 채우지 않고 '미산출'로 적는다."""
    try:
        return f"{v:{spec}}{suffix}" if v is not None else na
    except (TypeError, ValueError):
        return na


def _pct(v, digits=1, signed=True, na="미산출"):
    if v is None:
        return na
    return f"{v:+.{digits}f}%" if signed else f"{v:.{digits}f}%"


class QuantReportGenerator:
    """
    [Section 14] analysis_rulebook_ko.txt 정적 규칙집 기반 AI 퀀트 정밀 레포트 생성기.

    원칙: 엔진이 산출하지 못한 값은 임의 기본값으로 대체하지 않고 '미산출'로 표기한다.
    (구버전은 val_eval 에 존재하지 않는 키 4종을 참조해 'None배', '[None]' 을 출력했고
     20일선 안착·거래량 배수·감사의견·시나리오 가격을 리터럴로 박아두었다.)
    """

    def __init__(self):
        self.guard = LeakageGuard()
        self.rulebook_path = os.path.join(os.path.dirname(__file__), "analysis_rulebook_ko.txt")

    def generate_full_report(self, symbol, tech_df, fund_df, sim_res, val_eval,
                             snapshot=None, four_scores=None, **kwargs):
        sym_meta = STOCK_METRICS_DB.get(symbol, {})
        stock_name = sym_meta.get("name", symbol)

        unit_currency = val_eval.get('unit_currency', 'KRW')
        unit_str = val_eval.get('unit_str', '원')

        curr_price = float(tech_df['adj_close'].iloc[-1])
        curr_p_formatted = (f"{curr_price:,.0f}{unit_str}" if unit_currency == "KRW"
                            else f"${curr_price:,.2f}")

        tech_row = tech_df.iloc[-1].to_dict()
        fundamental_dict = fund_df.iloc[-1].to_dict() if (fund_df is not None and len(fund_df) > 0) else {}

        bps = val_eval.get('bps')
        per = val_eval.get('per')
        pbr = val_eval.get('pbr')
        roe = val_eval.get('roe')
        debt_ratio = val_eval.get('debt_ratio', sym_meta.get('debt'))

        # 수급: 합성/미연동이면 NaN 이므로 그대로 '미연동'으로 표기한다
        f5 = tech_row.get('foreign_cum_5d')
        i5 = tech_row.get('institution_cum_5d')
        f5_str = _num(f5 / 1e8, "+,.1f", "억 원") if (f5 is not None and not pd.isna(f5)) else "미연동"
        i5_str = _num(i5 / 1e8, "+,.1f", "억 원") if (i5 is not None and not pd.isna(i5)) else "미연동"

        match_cnt = sim_res.get('match_count', 0)
        pred_prob_str = sim_res.get('predicted_prob_str', '산출 불가')
        tier_label = sim_res.get('sample_tier_label', sim_res.get('blind_reason', ''))

        rsi_val = tech_df['rsi_14'].iloc[-1] if 'rsi_14' in tech_df.columns else None
        vol_ratio = tech_row.get('volume_ratio')

        t_ref_val = snapshot.get('t_ref') if snapshot else '미상'
        blocked_cnt = snapshot.get('blocked_future_count') if snapshot else 0
        shapley = snapshot.get('shapley_dclr_status') if snapshot else '미산출'

        fs = four_scores or {}
        fair_disp = fs.get('displayed_fair_value', val_eval.get('displayed_fair_value'))
        # 라운드 53c — '권장 매수가' 자리에 recommended_buy_price(적정가 −
        # 안전마진)를 싣고 있었다. 라운드 25 폐기 산식이라 현재가와 30~50%
        # 벌어진다. 실행 진입가를 쓰고, 장기 참고선은 아래에 따로 적는다.
        rec_buy = fs.get('entry_pullback_price')
        value_floor = fs.get('recommended_buy_price',
                             val_eval.get('recommended_buy_price'))
        tp1 = fs.get('target_tech_1st')
        tp2 = fs.get('target_tech_2nd')
        sl = fs.get('stop_loss_price')
        rr = fs.get('reward_risk_ratio')
        action = fs.get('final_action_title', '미판정')
        blocks = fs.get('top3_block_reasons') or []
        block_str = " / ".join(blocks[:5]) if blocks else "없음 (전 조건 통과)"

        report_md = f"""
### 📋 [{stock_name} ({symbol})] AI 퀀트 정밀 종합 분석 레포트

---

#### 1. 🎯 종합 결단 시그널 및 밸류에이션 위치
- **자산 구분**: `{unit_currency}` | **현재가**: **{curr_p_formatted}**
- **최종 행동 판정**: **`[{action}]`** (최종 행동점수 {_num(fs.get('final_action_score'), na='미산출')}점)
- **밸류에이션 판정**: **`[{val_eval.get('upside_eval', '판단 보류')}]`** (현재가 대비 {_pct(val_eval.get('upside_pct'))})
- **수급 동향 (5일 누적)**: 외국인 `{f5_str}` | 기관 `{i5_str}`

---

#### 2. 🏛️ 펀더멘털 및 적정가
- **PER**: `{_num(per, ".2f", "배")}` | **PBR**: `{_num(pbr, ".2f", "배")}` | **BPS**: `{_num(bps, ",.0f", unit_str)}` | **ROE**: `{_num(roe, ".2f", "%")}`
- **부채비율**: `{_num(debt_ratio, ".1f", "%")}` | **Piotroski F-Score**: `{_num(fundamental_dict.get('piotroski_f_score'), ".0f", "/9")}`
- **시장조정 적정가**: **`{_num(fair_disp, ",.0f", unit_str, na="산출 보류 (신뢰도 미달)")}`**
- **적정가 신뢰도**: `{val_eval.get('fair_value_confidence', 0):.0f}점` — {val_eval.get('fair_value_status_note', '')}
- **실행 진입가 (신규 매수자 · 오늘 쓰는 값)**: **`{_num(rec_buy, ",.0f", unit_str + " 이하", na="미산출")}`**
- **장기 가치 참고선 (적정가 − 안전마진)**: `{_num(value_floor, ",.0f", unit_str, na="미산출")}` — 오늘의 매수가가 아님
- **예비 모델 범위**: `{val_eval.get('preliminary_range_str', '미산출')}`

---

#### 3. 🔮 자기유사 과거 백테스트 관찰 통계 (표본 통제)
- **유효 패턴 표본 수**: `{match_cnt}건` (`{tier_label}`)
- **예측 상승확률**: **`{pred_prob_str}`**
- **과거 관찰 성과**: 평균 `{_pct(sim_res.get('mean_perf'))}` | 중앙값 `{_pct(sim_res.get('median_perf'))}` | 평균 MDD `{_pct(sim_res.get('mdd'))}`
- **분포 (10~90분위)**: `{_pct(sim_res.get('min_perf'))} ~ {_pct(sim_res.get('max_perf'))}`
- **95% Wilson 신뢰구간**: `{sim_res.get('ci_str', 'N/A')}`
- **최적 보유기간**: `{sim_res.get('optimal_holding_period_str', '산출 불가')}`

---

#### 4. 🌊 기술적 지표 실측치
- **RSI 14**: `{_num(rsi_val, ".1f")}`
- **거래량 비율 (20일 평균 대비)**: `{_num(vol_ratio, ".2f", "배")}`
- **20일선 / 60일선 대비**: `{_num(tech_row.get('sma_20'), ",.0f", unit_str)}` / `{_num(tech_row.get('sma_60'), ",.0f", unit_str)}`
- **월봉 10선 상태**: `{fs.get('m10_status', '미산출')}` (이격 {_pct(fs.get('m10_disparity'))})

---

#### 5. 🎯 목표가·손절가 및 손익비
- **1차 목표가**: `{_num(tp1, ",.0f", unit_str)}` | **2차 목표가**: `{_num(tp2, ",.0f", unit_str)}`
- **손절가**: `{_num(sl, ",.0f", unit_str)}`
- **손익비 (Reward/Risk)**: **`{_num(rr, ".2f")}`**
- **순기대수익 (거래비용 차감)**: `{_pct(fs.get('net_expected_return'))}`

---

#### 6. 🛡️ 무결성 감사 및 게이트 판정
- **분석 기준일 (t_ref)**: `{t_ref_val}`
- **차단된 미래 데이터 수**: `{blocked_cnt}건` (available_date 통제)
- **Shapley-DCLR 미래 누수율**: `{shapley}`
- **적용된 점수 상한**: `{fs.get('gate_reason', '미상')}`
- **TOP3 추천 미충족 조건**: `{block_str}`
- **규칙집 버전**: `{self.load_rulebook_version()}`
"""
        # [SR 11-7] 금지 표현 런타임 교정 + 면책 고지 부착.
        # 구버전은 LeakageGuard 를 import 만 하고 한 번도 호출하지 않았다.
        guard_res = self.guard.enforce_guardrails(report_md)
        self.last_guardrail_result = guard_res
        return guard_res['cleaned_text']

    def audit_compliance(self, snapshot, tech_df, sim_res):
        """SR 11-7 무결성 루브릭 채점 — 감사 탭에서 실제 점수를 표시하기 위한 진입점."""
        guard_res = getattr(self, 'last_guardrail_result', {'violations_found': 0})
        return self.guard.evaluate_compliance_rubric(snapshot, tech_df, sim_res, guard_res)

    def load_rulebook_version(self):
        """규칙집 파일에서 버전을 실제로 읽는다 (구버전은 'v2026.06.23' 리터럴)."""
        try:
            with open(self.rulebook_path, encoding='utf-8') as fh:
                for line in fh:
                    if line.strip().startswith('version'):
                        return line.split('=', 1)[1].strip().strip('"')
        except Exception:
            pass
        return "미상 (규칙집 로드 실패)"
