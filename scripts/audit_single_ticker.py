# -*- coding: utf-8 -*-
"""
단일 종목 데이터 정합성 감사기.

실행:
    python scripts/audit_single_ticker.py 005930.KS

한 종목의 전체 파이프라인을 실제로 돌리고, 원천→파싱→계산→화면 값이
불변조건을 지키는지 검사한다. 오류를 숨기지 않고 전부 나열한다.
"""
import os
import sys

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

import warnings

warnings.filterwarnings("ignore")

import bitemporal_engine as be
import quant_indicators as qi


def audit_ticker(symbol, eng=None, q=None, t_ref=None, verbose=True):
    """반환: (오류 목록, 경고 목록, 요약 dict). 예외는 오류로 수집하고 삼키지 않는다."""
    eng = eng or be.BitemporalEngine()
    q = q or qi.QuantIndicatorsEngine()
    t_ref = t_ref or be.resolve_analysis_date().strftime("%Y-%m-%d")
    errors, warns = [], []
    summary = {"symbol": symbol}

    def err(m):
        errors.append(m)
        if verbose:
            print("  [오류] " + m)

    def warn(m):
        warns.append(m)
        if verbose:
            print("  [경고] " + m)

    def ok(m):
        if verbose:
            print("  [정상] " + m)

    # ── 파이프라인 실행 ───────────────────────────────────────────────
    try:
        snap = q.run_full_pipeline(symbol, t_ref, b_engine=eng, rho_cutoff=0.80)
    except be.DataUnavailableError as e:
        warn(f"데이터 없음으로 분석 제외 (정상 동작): {str(e)[:80]}")
        return errors, warns, summary
    except Exception as e:
        err(f"파이프라인 예외: {type(e).__name__}: {str(e)[:120]}")
        return errors, warns, summary

    fs = snap["four_scores"]
    sim = snap["sim_res"]
    val = snap["val_eval"]
    prices = snap["prices_df"]
    summary["name"] = (be.STOCK_METRICS_DB.get(symbol) or {}).get("name", symbol)

    # ── ① 가격 시계열 불변조건 ────────────────────────────────────────
    o = prices["open_raw"].values.astype(float)
    h = prices["high_raw"].values.astype(float)
    l = prices["low_raw"].values.astype(float)
    c = prices["close_raw"].values.astype(float)
    adj = prices["adj_close"].values.astype(float)
    dts = prices["trade_date"].astype(str).values

    bad_ohlc = int(((l > o + 1e-9) | (o > h + 1e-9) | (l > c + 1e-9) | (c > h + 1e-9)).sum())
    if bad_ohlc:
        err(f"OHLC 불변조건 위반 봉 {bad_ohlc}개 (저가≤시가·종가≤고가)")
    else:
        ok(f"OHLC 불변조건 {len(c)}봉 전체 통과")
    if np.isnan(adj).any():
        err("adj_close 에 NaN 존재")
    if (prices["volume"].values.astype(float) < 0).any():
        err("음수 거래량 존재")
    if len(set(dts)) != len(dts):
        err("거래일 중복 존재")
    if list(dts) != sorted(dts):
        err("거래일 정렬 위반 (역순 구간 존재)")
    if not errors:
        ok(f"시계열 정합 (중복·역순·NaN·음수 없음, {dts[0]}~{dts[-1]})")

    # ── ② 시세 교차검증 ─────────────────────────────────────────────
    cc = snap.get("price_cross_check") or {}
    summary["cross_check"] = cc.get("passed")
    if cc.get("passed") is False:
        err(f"시세 교차검증 실패: {cc.get('note')}")
    elif cc.get("passed") is None:
        warn(f"시세 교차 대조 불가: {cc.get('note')}")
    else:
        ok(f"시세 교차검증 통과: {cc.get('note')}")

    # ── ③ 점수·판정 일관성 ──────────────────────────────────────────
    score = fs.get("final_action_score")
    summary["score"] = score
    if score is None or not (0 <= score <= 100):
        err(f"종합 점수 범위 이탈: {score}")
    for k in ("stock_quality_score", "trading_timing_score", "risk_safety_score",
              "analysis_confidence"):
        v = fs.get(k)
        if v is not None and not (0 <= v <= 100):
            err(f"{k} 범위 이탈: {v}")
    try:
        vd = q.build_final_verdict(snap)
        if vd["score"] != score:
            err(f"결론 점수 불일치: 배너 {vd['score']} vs 엔진 {score}")
        else:
            ok(f"결론 단일화: {vd['headline']} ({score}점)")
        summary["headline"] = vd["headline"]
    except Exception as e:
        err(f"결론 생성 예외: {type(e).__name__}: {str(e)[:80]}")

    # ── ④ 확률 정합 (tp+sl+미도달 = 100) ─────────────────────────────
    tp, sl = sim.get("tp_first_prob"), sim.get("sl_first_prob")
    nt = sim.get("no_touch_prob")
    if tp is not None and sl is not None:
        if nt is None:
            err("미도달 확률(no_touch_prob) 누락 — tp+sl 만으로 합이 100% 미만으로 보임")
        elif abs(tp + sl + nt - 100.0) > 0.35:
            err(f"확률 합계 이탈: {tp}+{sl}+{nt} = {tp + sl + nt:.1f}")
        else:
            ok(f"선도달 확률 합 100% (목표 {tp} / 손절 {sl} / 미도달 {nt})")
        if not sim.get("probabilities_shown"):
            err("표본 미달인데 tp/sl 확률이 노출됨 (산출불가 문구와 모순)")
    if sim.get("probabilities_shown") and sim.get("bayes_prob") is None:
        err("확률 허용인데 베이지안 사후확률이 없음")

    # ── ⑤ 적정가·실행 가격 ──────────────────────────────────────────
    fv = val.get("displayed_fair_value")
    if fv is not None and fv <= 0:
        err(f"적정가 ≤ 0: {fv}")
    if val.get("is_fund") and fv is not None:
        err("ETF 인데 적정가가 산출됨 (합성값 의심)")
    tgt, stop = fs.get("target_tech_1st"), fs.get("stop_loss_price")
    cur = float(snap["rt_price"])
    if tgt is not None and stop is not None:
        if not (stop < cur < tgt):
            warn(f"현재가 기준 레벨 역전: 손절 {stop:,.0f} / 현재 {cur:,.0f} / 목표 {tgt:,.0f}")
        else:
            ok(f"실행 레벨 정렬 (손절 {stop:,.0f} < 현재 {cur:,.0f} < 목표 {tgt:,.0f})")

    # ── ⑥ 뉴스 서술 사실성 ──────────────────────────────────────────
    try:
        news = eng.get_timeframe_news_analysis(symbol)
        srcs = " ".join(str(news[k].get("source", "")) for k in news)
        for fake in ("KRX & 실시간", "리서치 컨센서스", "IR 공식 보고서"):
            if fake in srcs:
                err(f"뉴스 출처에 미연동 기관 표기: '{fake}'")
        body = " ".join(str(news[k].get("impact", "")) + str(news[k].get("title", ""))
                        for k in news)
        for fab in ("매수세 유입", "차익매물", "컨센서스 상향", "독보적", "해자"):
            if fab in body:
                err(f"근거 없는 서술 잔존: '{fab}'")
        if not any("미연동" in str(news[k].get("source", "")) or "관찰" in str(news[k].get("source", ""))
                   for k in news):
            warn("뉴스 카드에 미연동/관찰 표시가 없음")
        else:
            ok("뉴스 카드가 관찰·정량 해석만 서술 (미연동 명시)")
    except Exception as e:
        err(f"뉴스 모듈 예외: {type(e).__name__}")

    return errors, warns, summary


if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else "005930.KS"
    print("=" * 78)
    print("단일 종목 감사:", sym)
    print("=" * 78)
    errors, warns, summary = audit_ticker(sym)
    print("-" * 78)
    print("오류 %d건 · 경고 %d건" % (len(errors), len(warns)))
    sys.exit(1 if errors else 0)
