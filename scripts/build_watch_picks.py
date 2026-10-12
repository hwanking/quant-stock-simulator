# -*- coding: utf-8 -*-
"""
관심종목 추천 → 스윙 계획 재료를 만든다 (라운드 507 · 저녁 작업 단계 · 손으로도 돈다).

리포트와 **같은 관문·같은 길**(2026-10-13 독립 검토가 첫 판의 빈틈 둘을 잡았다 — 정규장 중 막기 · 시세 관문):
  만들지 = `build_premarket_report.decide` 그대로(정규장 중이면 안 만든다 · 그날 봉이 확정 전이면 안 만든다 · 쓰기 금지면 안
  만든다 · 그 판정일 문서가 있으면 다시 안 만든다 — `--force` 는 마지막 하나만 넘는다) · 시세 관문 = `feed_gate` 그대로 ·
  정밀 분석 = `run_screener_scan`(시세 교차검증·유동성 하한까지) · 후보 조립 = `premarket.pick_from_scan_row` · 추천만 · 그 판정일
  리포트에 있는 종목은 뺀다 · **저장 직전에 같은 판단을 한 번 더**(스캔 2~3분 사이 장이 열리면 버린다).
문서는 `swing_watch` 한 곳(이 PC 의 `.portfolio/` · §9).
"""
import argparse
import os
import sys
import time
from datetime import datetime

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
sys.path.insert(0, os.path.join(PROJ, 'scripts'))
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:                                              # noqa: BLE001 — pythonw 는 표준출력이 없다
    pass
import noconsole  # noqa: E402
noconsole.install()


def _p(msg):
    try:
        print(msg, flush=True)
    except Exception:                                          # noqa: BLE001 — 로그 한 줄이 작업을 죽이지 않는다(2026-09-11)
        pass


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--force', action='store_true', help='그 판정일 문서가 있어도 다시 만든다(사람이 손으로 · 장중·봉 확정 전 막힘은 못 넘는다)')
    a = ap.parse_args(argv)
    import premarket
    import portfolio
    import swing_watch
    import market_scan
    import build_premarket_report as BPR
    from bitemporal_engine import BitemporalEngine
    from quant_indicators import QuantIndicatorsEngine

    no_write = bool(os.environ.get('GAEUM_NO_LOCAL_WRITE'))

    def _has(day):
        p = swing_watch.path_of(day)
        return bool(p and os.path.exists(p) and not a.force)

    ok, anchor = BPR.decide(datetime.now(), _has, no_write=no_write)
    if not ok:
        _p(f'[관심종목 추천 계획] 만들지 않음 — {anchor}')
        return 0
    items, _ = portfolio.load_watchlist(portfolio.WATCHLIST_FILE)
    codes = []
    for w in items or []:
        c = portfolio.normalize_code((w or {}).get('code'))
        if c and c not in codes:
            codes.append(c)
    t0 = time.time()
    b = BitemporalEngine()
    gate_ok, gate_line = BPR.feed_gate(b)
    if not gate_ok:
        _p(f'[관심종목 추천 계획] 실패 — {gate_line} · 문서를 안 만들었다(리포트와 같은 관문)')
        return 1
    uni = b.get_screener_universe(full_market=True) or []
    by_code = {str(u['symbol']).split('.')[0]: u for u in uni if u.get('symbol')}
    targets = [by_code[c] for c in codes if c in by_code]
    not_in_uni = len(codes) - len(targets)
    q = QuantIndicatorsEngine()
    results = q.run_screener_scan(targets, anchor, b_engine=b, rho_cutoff=market_scan.DEFAULT_RHO)
    failures = list(getattr(q, 'last_scan_failures', None) or [])
    picks = []
    for r in results or []:
        try:
            pk = premarket.pick_from_scan_row(q, r)
        except Exception as e:                                 # noqa: BLE001 — 한 종목이 이상해도 다른 종목을 막지 않는다
            failures.append({'symbol': r.get('symbol'), 'reason': f'후보 조립 실패 — {type(e).__name__}: {e}'})
            continue
        if pk:
            picks.append(pk)
    rep = premarket.load_today_report(anchor)
    rep_codes = [str((p or {}).get('code') or str((p or {}).get('symbol') or '').split('.')[0])
                 for p in ((rep or {}).get('picks') or [])]
    doc = swing_watch.doc_from(
        picks, anchor, engine_version=premarket._engine_version(),
        generated_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'), day_basis=premarket.DAY_BASIS,
        report_codes=rep_codes,
        excluded_codes=[str(f.get('symbol') or '').split('.')[0] for f in failures if f.get('symbol')],
        counts=dict(watch_codes=len(codes), not_in_universe=not_in_uni, measured=len(targets),
                    scan_excluded=len(failures), report_found=bool(rep)))
    # 저장 직전에 같은 판단을 한 번 더 — 스캔하는 사이 장이 열렸거나 판정일이 넘어갔으면 버린다(장중 가격으로 고정하지 않는다)
    ok2, anchor2 = BPR.decide(datetime.now(), lambda d: False, no_write=no_write)
    if not ok2 or anchor2 != anchor:
        _p(f'[관심종목 추천 계획] 버림 — 스캔하는 사이 상태가 바뀌었다({anchor2 if not ok2 else "판정일 " + str(anchor2)}) · 저장 안 함')
        return 1
    out = swing_watch.save(doc)
    c = doc['counts']
    # 저녁 작업 기록은 단계 출력의 **마지막 세 줄**만 남긴다 — 요약을 맨 끝에 찍고 제외 사유는 갈래별로 한 줄에 센다
    kinds = {}
    for f in failures:
        k = str(f.get('reason') or '사유 없음').split(' — ')[0].split('(')[0]
        k = '20일 평균 거래대금 하한 미달' if '평균 거래대금' in k else k[:40]
        kinds[k] = kinds.get(k, 0) + 1
    if kinds:
        _p('  제외 사유 — ' + ' · '.join(f'{k} {n}' for k, n in sorted(kinds.items(), key=lambda kv: -kv[1])))
    if not rep:
        _p('  주의: 그 판정일 리포트를 못 읽어 겹침을 확인하지 못했다 — 실행부가 같은 종목은 한 번만 산다')
    _p(f"[관심종목 추천 계획] 판정일 {anchor} · 관심종목 {c['watch_codes']}종목 · 유니버스 밖(ETF 등) {c['not_in_universe']} · "
       f"정밀 분석 {c['measured']} · 제외 {c['scan_excluded']} · 추천 {c['kept'] + c['in_report']} "
       f"(리포트에 이미 있음 {c['in_report']}) · 계획 재료 {c['kept']} · {gate_line} · {time.time() - t0:.0f}초 · "
       + (f'저장 {os.path.basename(out)}' if out else '저장 안 함(쓰기 금지)'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
