# -*- coding: utf-8 -*-
"""
상단 시장 카드(KOSPI·KOSDAQ·환율·S&P500) 검증기.

실행:  python scripts/verify_market_snapshot.py

카드에 표시되는 값과, 독립 경로(일봉 시계열)로 재계산한 등락률을 대조한다.
장중에는 카드(실시간)와 일봉(확정/지연)이 다를 수 있으므로 허용 오차를 둔다.
"""
import os
import re
import sys
import warnings

warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

import bitemporal_engine as be


def num(s):
    try:
        return float(re.sub(r"[^\d.\-]", "", str(s)))
    except ValueError:
        return None


def main():
    eng = be.BitemporalEngine()
    cards = eng.get_market_indices()
    fails = 0

    print("=" * 82)
    print("시장 카드 vs 독립 재계산 (일봉 최근 2봉)")
    print("=" * 82)
    for label, card_key, idx_name in (("KOSPI", "kospi", "KOSPI"),
                                      ("KOSDAQ", "kosdaq", "KOSDAQ")):
        card = cards.get(card_key, {})
        c_price, c_pct = num(card.get("price")), num(card.get("pct"))
        series = eng.fetch_index_daily(idx_name, count=120)
        if series is None:
            print("  %-7s 일봉 수신 실패 — 카드 검증 불가 (미검증)" % label)
            fails += 1
            continue
        d, c = series
        last, prev = float(c[-1]), float(c[-2])
        r_pct = (last / prev - 1) * 100
        ok_price = c_price is not None and abs(c_price - last) / last < 0.02
        ok_pct = c_pct is not None and abs(abs(c_pct) - abs(r_pct)) < 1.0
        print("  %-7s 카드 %s (%s%%)  |  재계산 %s=%.2f → 전일 %s=%.2f, %.2f%%  → %s" % (
            label, card.get("price"), card.get("pct"),
            d[-1], last, d[-2], prev, r_pct,
            "일치" if (ok_price and ok_pct) else "불일치/검증실패"))
        if not (ok_price and ok_pct):
            fails += 1

    # 환율·S&P500 은 야후 원천의 chartPreviousClose 대비라 독립 시계열이 없다.
    # '전일 종가 대비'라는 산식 자체는 원천 응답 필드로 검증한다.
    for label, key in (("USD/KRW", "usd_krw"), ("S&P500", "sp500")):
        card = cards.get(key, {})
        p, ch, pct = num(card.get("price")), num(card.get("change")), num(card.get("pct"))
        if p is None or ch is None or pct is None:
            print("  %-7s 카드 값 미수신 — 미검증" % label)
            continue
        implied_prev = p - ch
        recomputed = (ch / implied_prev * 100) if implied_prev else None
        ok = recomputed is not None and abs(abs(recomputed) - abs(pct)) < 0.05
        print("  %-7s 카드 %s (%+.2f, %s%%) | 등락률 재계산 %.2f%% → %s" % (
            label, card.get("price"), ch, card.get("pct"),
            recomputed or 0, "내적 일치" if ok else "불일치"))
        if not ok:
            fails += 1

    print("-" * 82)
    print("불일치·검증실패 %d건" % fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
