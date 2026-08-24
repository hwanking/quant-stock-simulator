# -*- coding: utf-8 -*-
"""룩스루가 왜 148개에서 멈추나 — 막는 것을 전수로 가른다 (라운드 170).

라운드 167 이 1,161종목 중 148개에 룩스루 적정가를 냈다. 나머지가 왜
안 되는지 **재서** 가른다. 짐작으로 "해외라서" 라고 적지 않는다.

■ 실측으로 이미 안 것 (`_probe/etf_taxonomy.py` · `_probe/etf_qty_probe.py`)
  · 비중을 안 주는 ETF **667개(57%)** — 전부 해외·채권 자산이다
    (인도 Vodafone · 미국 NVIDIA · 통안채 · 스왑). 주식수는 있으나
    구성종목 **가격과 적정가**가 우리에게 없어 비중을 유도해도 소용없다.
  · 국내주식이 사실상 100%인데 통과 못 한 ETF **290개** ← 여기가 지렛대
  · 현금성 지배 68개 (단일종목 레버리지 등)

■ 이 스크립트가 재는 것
  그 290개를 막는 **구성종목**이 누구이고 왜 적정가가 안 나오는지.
  적정가를 못 내는 사유를 엔진이 주는 그대로 세어, 고칠 수 있는 결함과
  본래 못 내는 것(재무 미게시 등)을 가른다.

측정 전용 — 점수·게이트·문턱을 바꾸지 않는다.

    C:/Python314/python.exe scripts/etf_gap_audit_r170.py [--limit 0]
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

import etf_registry                                            # noqa: E402
import stock_code                                              # noqa: E402

HOLD = os.path.join(PROJ, '.portfolio', 'etf_holdings_r167.json')
LT = os.path.join(PROJ, 'data', 'etf_lookthrough_r167.json')
NAMES = os.path.join(PROJ, '.portfolio', 'name_master.json')
OUT = os.path.join(PROJ, 'data', 'etf_gap_audit_r170.json')

#: 라운드 167 이 채택한 커버리지 문턱. **바꾸지 않는다** (§2).
COVER_MIN = 90.0


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def name_map():
    with open(NAMES, encoding='utf-8') as f:
        doc = json.load(f)
    etf = set(etf_registry.index() or {})
    by = collections.defaultdict(set)
    meta = {}
    for r in doc.get('rows') or []:
        c = stock_code.normalize(r.get('code'))
        n = str(r.get('name') or '').strip()
        if not c or not n or c in etf:
            continue
        by[n].add(c)
        meta[c] = str(r.get('mkt') or '')
    return {n: next(iter(s)) for n, s in by.items() if len(s) == 1}, meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()

    print('룩스루를 막는 것 — 전수 (라운드 170)')
    print('측정 전용 — 점수·게이트·문턱을 바꾸지 않는다\n')

    with open(HOLD, encoding='utf-8') as f:
        holdings = json.load(f)['holdings']
    with open(LT, encoding='utf-8') as f:
        lt = json.load(f)
    passed = {c for c, v in (lt.get('results') or {}).items()
              if (v.get('valued_pct') or 0) >= COVER_MIN}
    uniq, mkt = name_map()

    # ── 어느 구성종목이 막고 있나 (비중 가중) ─────────────────────────
    blockers = collections.Counter()          # 코드 → 막은 비중 합
    blocked_etfs = collections.Counter()      # 코드 → 막은 ETF 수
    near = []
    for c, hs in holdings.items():
        if c in passed:
            continue
        w_all = sum(h['weight'] for h in hs if h.get('weight') is not None)
        if w_all < 95 or w_all > 105:
            continue                          # 비중 자체가 없거나 이상한 ETF
        dom = sum(h['weight'] for h in hs
                  if h.get('weight') is not None and uniq.get(h['name']))
        if dom / w_all * 100 < COVER_MIN:
            continue                          # 조인부터 안 되는 ETF
        near.append(c)
        for h in hs:
            w = h.get('weight')
            code = uniq.get(h['name'])
            if w is None or not code:
                continue
            if code not in (lt.get('valued_codes') or []):
                pass
        # 그 ETF 에서 적정가가 없던 종목을 찾는다 — 아래에서 실측한다

    print(f'■ 조인은 되는데 통과 못 한 ETF {len(near):,}개')

    # ── 그 ETF 들의 구성종목 전부에 대해 적정가를 다시 내 본다 ────────
    #    (라운드 167 과 같은 방식 — 화면이 부르는 순서 그대로)
    import bitemporal_engine as be
    import quant_indicators as qi
    eng, q = be.BitemporalEngine(), qi.QuantIndicatorsEngine()

    need = collections.Counter()
    for c in near:
        for h in holdings[c]:
            code = uniq.get(h['name'])
            if code and h.get('weight'):
                need[code] += h['weight']
    targets = [c for c, _ in need.most_common(a.limit or None)]
    print(f'■ 막는 ETF 들의 구성종목 {len(targets):,}종목을 다시 잰다')

    reasons = collections.Counter()
    detail = {}
    t0 = time.time()
    for i, code in enumerate(targets, 1):
        sym = f"{code}.KQ" if mkt.get(code) == 'KOSDAQ' else f"{code}.KS"
        why, fv = None, None
        try:
            px_df, fd = eng.generate_synthetic_bitemporal_data(
                symbol=sym, start_date='2022-01-01')
            tech = q.compute_technical_indicators(px_df)
            val = q.evaluate_valuation_metric(tech, fd, symbol=sym)
            fv = val.get('displayed_fair_value')
            if fv is None:
                why = (str(val.get('fair_value_status_note') or '')[:60]
                       or str(val.get('fair_value_status') or '사유 미기재'))
        except Exception as e:                                 # noqa: BLE001
            why = f'{type(e).__name__}: {str(e)[:50]}'
        if fv is None:
            reasons[why or '사유 미기재'] += 1
            detail[code] = {'weight_seen': round(need[code], 1), 'why': why}
        if i % 25 == 0 or i == len(targets):
            print(f'   {i:>4}/{len(targets)}  못 낸 것 {len(detail):,} · '
                  f'{time.time() - t0:.0f}s')

    print(f'\n■ 적정가를 못 낸 구성종목 {len(detail):,} / {len(targets):,} '
          f'({len(detail) / max(1, len(targets)) * 100:.1f}%)')
    print('\n■ 사유별')
    for why, n in reasons.most_common(12):
        print(f'   {n:>5}  {why}')

    print('\n■ 가장 많이 막은 종목 (등장 비중 합)')
    for code, d in sorted(detail.items(), key=lambda t: -t[1]['weight_seen'])[:15]:
        print(f'   {code}  비중합 {d["weight_seen"]:>7.1f}  {str(d["why"])[:52]}')

    doc = {
        'made': datetime.now().strftime('%Y-%m-%d'),
        'cover_min': COVER_MIN,
        'etfs_total': len(holdings), 'etfs_passed': len(passed),
        'etfs_join_ok_but_failed': len(near),
        'constituents_checked': len(targets),
        'constituents_unvalued': len(detail),
        'reasons': dict(reasons), 'detail': detail,
        'note': ('측정 전용. 비중을 안 주는 667개는 전부 해외·채권 자산이라 '
                 '구성종목 가격·적정가가 우리에게 없다 — 비중을 유도해도 '
                 '소용없다. 여기서는 국내주식형만 본다.'),
    }
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f'\n저장: {OUT}')
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
