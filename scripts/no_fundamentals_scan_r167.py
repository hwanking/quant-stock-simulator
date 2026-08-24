# -*- coding: utf-8 -*-
"""게시 재무가 없는 종목이 몇 개인가 (라운드 167 — 결함 영향 범위).

고치기 전 `generate_synthetic_bitemporal_data` 는 **처음 보는 종목**에
`{"eps":5000.0,"bps":45000.0,"pbr":1.5,"roe":12.0}` 를 넣었다. 그래서
**게시 EPS·BPS 가 둘 다 없는 종목**이 전부 같은 가짜 적정가
(52,713.75원 · 신뢰도 70.8 · CALIBRATED)를 받았다.

여기서는 그 **영향권 크기**만 센다 — 재무 게시 여부는 프로세스가
차갑든 데워졌든 같으므로 한 프로세스에서 빠르게 훑을 수 있다.

    C:/Python314/python.exe scripts/no_fundamentals_scan_r167.py [--limit 0]
"""
import argparse
import collections
import io
import json
import os
import sys
import time
from datetime import datetime

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
os.chdir(PROJ)

OUT = os.path.join(PROJ, 'data', 'no_fundamentals_scan_r167.json')


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()

    import bitemporal_engine as be
    eng = be.BitemporalEngine()

    with open(os.path.join(PROJ, '.portfolio', 'name_master.json'),
              encoding='utf-8') as f:
        doc = json.load(f)
    etf = set(str(c) for c in (doc.get('etf_codes') or []))
    rows = [r for r in (doc.get('rows') or [])
            if str(r.get('code')) not in etf and r.get('live')]
    if a.limit:
        rows = rows[:a.limit]
    print(f'게시 재무 없는 종목 훑기 (라운드 167) — 대상 {len(rows):,}종목\n')

    none_both, none_one, have, err = [], [], [], []
    t0 = time.time()
    for i, r in enumerate(rows, 1):
        c = str(r.get('code'))
        sym = f"{c}.KQ" if str(r.get('mkt')) == 'KOSDAQ' else f"{c}.KS"
        try:
            eng.fetch_and_update_naver_realtime(sym)
            m = be.STOCK_METRICS_DB.get(sym) or {}
        except Exception:                                      # noqa: BLE001
            err.append(c)
            continue
        if m.get('is_fund'):
            continue                    # 펀드는 애초에 밸류에이션 대상이 아니다
        eps, bps = m.get('eps'), m.get('bps')
        if not eps and not bps:
            none_both.append((c, r.get('name')))
        elif not eps or not bps:
            none_one.append((c, r.get('name')))
        else:
            have.append(c)
        if i % 200 == 0 or i == len(rows):
            print(f'   {i:>5}/{len(rows)}  둘 다 없음 {len(none_both):,} · '
                  f'하나 없음 {len(none_one):,} · 있음 {len(have):,} · '
                  f'오류 {len(err):,} · {time.time() - t0:.0f}s')

    n = len(none_both) + len(none_one) + len(have)
    print(f'\n■ 읽은 종목 {n:,} (오류 {len(err):,})')
    print(f'■ **둘 다 없음 = 가짜 적정가를 받던 종목** {len(none_both):,} '
          f'({len(none_both) / max(1, n) * 100:.1f}%)')
    print(f'■ 하나만 없음 {len(none_one):,} '
          f'({len(none_one) / max(1, n) * 100:.1f}%)')
    print('\n■ 영향권 종목 앞 25')
    for c, nm in none_both[:25]:
        print(f'   {c} {nm}')

    doc_out = {
        'made': datetime.now().strftime('%Y-%m-%d'),
        'scanned': n, 'errors': len(err),
        'no_eps_and_bps': len(none_both), 'no_one': len(none_one),
        'have_both': len(have),
        'affected_pct': round(len(none_both) / max(1, n) * 100, 2),
        'affected': [{'code': c, 'name': nm} for c, nm in none_both],
        'note': ('고치기 전에는 이 종목들이 전부 같은 적정가 52,713.75원 · '
                 '신뢰도 70.8 · CALIBRATED 를 받았다. 고친 뒤에는 각자의 '
                 '가격 기반 값과 CAUTION 이 나온다.'),
    }
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(doc_out, f, ensure_ascii=False, indent=1)
    print(f'\n저장: {OUT}')
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
