# -*- coding: utf-8 -*-
"""
다수 종목 배치 감사기.

실행:
    python scripts/audit_all_tickers.py            → 고정 테스트 종목군 (유형별 대표)
    python scripts/audit_all_tickers.py 30         → 유니버스 시총 상위 30개 추가 감사

오류를 숨기거나 건너뛰지 않는다 — 종목별 오류·경고를 전부 나열하고 통계를 낸다.
"""
import os
import sys
import warnings

warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8")
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

import bitemporal_engine as be
import quant_indicators as qi
from scripts.audit_single_ticker import audit_ticker

#: 유형별 고정 테스트 종목군 (§2). 유형이 다르면 실패 방식도 다르다.
FIXED_SET = [
    ("005930.KS", "KOSPI 대형주"),
    ("000660.KS", "KOSPI 대형주"),
    ("005380.KS", "KOSPI 대형주"),      # 현대차
    ("247540.KQ", "KOSDAQ"),            # 에코프로비엠
    ("086520.KQ", "KOSDAQ"),            # 에코프로
    ("052330.KQ", "KOSDAQ"),            # 코텍
    ("069500.KS", "ETF"),               # KODEX 200
    ("360750.KS", "ETF"),               # TIGER 미국S&P500
    ("005935.KS", "우선주"),             # 삼성전자우
    ("105560.KS", "금융주"),             # KB금융
    ("028300.KQ", "바이오/변동성"),       # HLB
    ("475150.KS", "신규상장/짧은이력"),    # SK이터닉스(2024 분할상장)
]


def main():
    eng = be.BitemporalEngine()
    q = qi.QuantIndicatorsEngine()
    t_ref = be.resolve_analysis_date().strftime("%Y-%m-%d")

    targets = list(FIXED_SET)
    if len(sys.argv) > 1:
        n = int(sys.argv[1])
        uni = eng.get_screener_universe(full_market=True)[:n]
        known = {s for s, _ in targets}
        targets += [(u["symbol"], "유니버스") for u in uni if u["symbol"] not in known]

    total, ok_n, warn_n, fail_n = 0, 0, 0, 0
    failures = []
    for sym, kind in targets:
        total += 1
        print("\n[%d/%d] %s (%s)" % (total, len(targets), sym, kind))
        try:
            errors, warns, summary = audit_ticker(sym, eng=eng, q=q, t_ref=t_ref,
                                                  verbose=False)
        except Exception as e:
            errors, warns, summary = [f"감사기 예외: {type(e).__name__}: {e}"], [], {}
        name = summary.get("name", sym)
        if errors:
            fail_n += 1
            print("  ✗ %s — 오류 %d건" % (name, len(errors)))
            for m in errors:
                print("      ·", m[:110])
            failures.append((sym, name, errors))
        elif warns:
            warn_n += 1
            print("  △ %s — 경고 %d건" % (name, len(warns)))
            for m in warns:
                print("      ·", m[:110])
        else:
            ok_n += 1
            print("  ✓ %s — %s (%s점)" % (name, summary.get("headline", "-"),
                                          summary.get("score", "-")))

    print("\n" + "=" * 78)
    print("배치 감사 통계: 전체 %d · 정상 %d · 경고 %d · 실패 %d" % (
        total, ok_n, warn_n, fail_n))
    if failures:
        print("실패 종목:")
        for sym, name, errs in failures:
            print("  %s %s: %s" % (sym, name, errs[0][:90]))
    return 1 if fail_n else 0


if __name__ == "__main__":
    sys.exit(main())
