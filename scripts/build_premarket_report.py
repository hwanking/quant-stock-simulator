# -*- coding: utf-8 -*-
"""개장 전 리포트를 이 PC 의 저녁 작업이 장 마감 뒤에 만든다 (라운드 484 · 화면의 첫 스캔과 같은 함수).

■ 왜 (2026-10-11 실측 · 라운드 483)
  개장 전 리포트는 **앱을 열 때만** 만들어졌다. 그래서 리포트가 언제 만들어지는지가 사람이 언제 앱을 여는지에 묶였다 —
  107개 중 9개가 다음 거래일 **장중**에 만들어져 가격이 장중 값이었고(추적 32건 · 라운드 483 이 채점 경계로 막았다), 하나는 장
  마감 2분 뒤라 가격이 확정 종가가 아니었다(+0.21~+3.66%). 그리고 앱을 안 연 날은 리포트가 없어 그날 추적·전방 판정(R475·R478)·
  자동매매 계획 표본이 통째로 빠진다 — 사람의 습관이 연구 표본을 정했다. 주기적인 일은 사람이 아니라 저녁 작업이 한다(라운드 414).

■ 무엇을 하나
  · 스캔은 `market_scan.run` — 화면의 '최신화'·첫 진입 스캔과 **같은 함수**(§4) · 화면 기본값(종합 이슈 · 상위 5 · rho 0.80) 그대로.
  · 리포트는 `premarket.build_report` — 화면과 같은 함수 · 같은 자료 기준일 규칙(라운드 442) · 이미 있으면 다시 안 만든다(라운드 228).
  · **정규장 중에는 만들지 않는다** — 그때 받는 가격은 장중 값이다(라운드 483). 장 전·장 마감 뒤·휴장일에만.
  · 쓰기 금지(`GAEUM_NO_LOCAL_WRITE`)면 아무것도 안 한다(리포트·이력은 `.portfolio` 에 쓴다 · 회귀·배포는 사용자 자료를 안 쓴다).
  · 예외는 삼키지 않는다 — 사유를 찍고 종료 1(저녁 작업이 그 줄을 기록에 남긴다).

    C:/Python314/python.exe scripts/build_premarket_report.py           # 만들 수 있으면 만든다
    C:/Python314/python.exe scripts/build_premarket_report.py --plan    # 만들지 판단만(네트워크 0 · 쓰기 0)
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:                                              # noqa: BLE001
    pass
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)


def decide(now, has_report, no_write=False):
    """만들지 — (True, 자료 기준일) 또는 (False, 사유). 순수 판단(달력·장 시각은 엔진 한 곳 · 리포트 유무는 넘겨받는다)."""
    if no_write:
        return False, '쓰기 금지(GAEUM_NO_LOCAL_WRITE) — 리포트·이력을 쓰는 단계라 건너뛴다'
    import bitemporal_engine as be
    import premarket
    st = be.get_market_status(now)
    if st.get('state') == '장중':
        return False, ('정규장 중이다 — 이때 받는 가격은 장중 값이라 자료일 리포트로 고정하지 않는다(라운드 483) · '
                       '장 마감 뒤 저녁 작업이 다시 본다')
    day = premarket.report_day(now)
    if not day:
        return False, '자료 기준일을 정하지 못했다 — 만들지 않는다(§3)'
    if has_report(day):
        return False, f'자료일 {day} 리포트가 이미 있다 — 다시 안 만든다(라운드 228)'
    return True, day


def main(argv=None):
    ap = argparse.ArgumentParser(description='개장 전 리포트를 장 마감 뒤에 만든다')
    ap.add_argument('--plan', action='store_true', help='만들지 판단만')
    a = ap.parse_args(argv)
    import premarket
    now = _dt.datetime.now()
    ok, why = decide(now, lambda d: bool(premarket.load_today_report(d)),
                     no_write=bool(os.environ.get('GAEUM_NO_LOCAL_WRITE')))
    if not ok:
        print(f'건너뜀 — {why}')
        return 0
    day = why
    if a.plan:
        print(f'계획 — 자료일 {day} 리포트를 만든다(스캔 상위 5 · 약 2~3분)')
        return 0
    import market_scan
    from bitemporal_engine import BitemporalEngine
    from quant_indicators import QuantIndicatorsEngine
    t0 = time.time()
    try:
        q, b = QuantIndicatorsEngine(), BitemporalEngine()
        r = market_scan.run(q, b, day)
    except Exception as ex:                                    # noqa: BLE001
        print(f'실패 — 스캔이 멈췄다 {type(ex).__name__}: {str(ex)[:200]} · 리포트를 안 만들었다')
        return 1
    if r.get('kind') != 'ok':
        print(f"실패 — 관심종목 후보를 못 받았다: {r.get('reason')} · 리포트를 안 만들었다")
        return 1
    rep, new = premarket.build_report(q, r['results'], market_label=market_scan.market_label_of(r['results']))
    picks = len((rep or {}).get('picks') or [])
    print(f"{'만듦' if new else '이미 있음'} — 자료일 {(rep or {}).get('date')} · 후보 {picks} · 정밀 분석 {len(r['results'])} · "
          f"빠진 후보 {len(r.get('failures') or [])} · 코드 못 찾음 {len(r.get('unmapped') or [])} · "
          f"생성 {(rep or {}).get('generated_at')} · {time.time() - t0:.0f}초")
    return 0


if __name__ == '__main__':
    sys.exit(main())
