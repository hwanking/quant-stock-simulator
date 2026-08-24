# -*- coding: utf-8 -*-
"""비중을 우리가 유도해도 되는가 (라운드 170).

사전등록: `docs/PREREG_R170_DERIVED_WEIGHTS.md`
판정 기준은 거기에 **측정 전에** 적혀 있다. 여기서 내리지 않는다.

    w_i = (주식수_i × 현재가_i) ÷ Σ_j (주식수_j × 현재가_j)

**답을 이미 아는 곳에서 먼저 잰다** — 비중과 주식수를 둘 다 주는
494종목에서 유도값과 발표값을 대조한다.

    C:/Python314/python.exe scripts/etf_derived_weights_r170.py
"""
import collections
import io
import json
import os
import statistics
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
OUT = os.path.join(PROJ, 'data', 'etf_derived_weights_r170.json')

#: 사전등록 R1·R2·R3·R4 — 측정 전에 정한 값. 바꾸지 않는다.
R1_MEDIAN = 0.005
R2_P95 = 0.02
R3_SUM_TOL = 0.001
R4_MIN_TARGETS = 10
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
    mkt = {}
    for r in doc.get('rows') or []:
        c = stock_code.normalize(r.get('code'))
        n = str(r.get('name') or '').strip()
        if not c or not n or c in etf:
            continue
        by[n].add(c)
        mkt[c] = str(r.get('mkt') or '')
    return {n: next(iter(s)) for n, s in by.items() if len(s) == 1}, mkt


def main():
    print('유도 비중 검증 (라운드 170)')
    print('사전등록: docs/PREREG_R170_DERIVED_WEIGHTS.md')
    print('측정 전용 — 점수·게이트·문턱을 바꾸지 않는다\n')

    with open(HOLD, encoding='utf-8') as f:
        holdings = json.load(f)['holdings']
    with open(LT, encoding='utf-8') as f:
        lt = json.load(f)
    fair_ratio = {}                    # 코드 → 적정가÷현재가 (167 산출물 재사용)
    uniq, mkt = name_map()

    # ── 라운드 167 이 이미 낸 종목별 적정가/현재가 비율을 다시 만든다 ──
    #    (그 스크립트와 같은 순서로 부른다 — §4)
    import bitemporal_engine as be
    import quant_indicators as qi
    eng, q = be.BitemporalEngine(), qi.QuantIndicatorsEngine()

    # 대상: 494(대조군) + 국내주식형 비중 미기재(적용 후보)
    both, cand = [], []
    for c, hs in holdings.items():
        ws = [h for h in hs if h.get('weight') is not None]
        qs = [h for h in hs if h.get('qty') is not None]
        if not qs:
            continue
        dom_kr = sum(1 for h in hs if uniq.get(h['name']))
        if ws and dom_kr >= max(1, int(len(hs) * 0.9)):
            both.append(c)
        elif not ws and dom_kr >= max(1, int(len(hs) * 0.9)):
            cand.append(c)
    print(f'■ 대조군(비중·주식수 둘 다 · 국내주식형) {len(both):,}개')
    print(f'■ 적용 후보(비중 없음 · 국내주식형) {len(cand):,}개')

    need = set()
    for c in both + cand:
        for h in holdings[c]:
            code = uniq.get(h['name'])
            if code:
                need.add(code)
    print(f'■ 가격·적정가를 낼 종목 {len(need):,}개')

    px, fv = {}, {}
    t0 = time.time()
    for i, code in enumerate(sorted(need), 1):
        sym = f"{code}.KQ" if mkt.get(code) == 'KOSDAQ' else f"{code}.KS"
        try:
            df, fd = eng.generate_synthetic_bitemporal_data(
                symbol=sym, start_date='2022-01-01')
            cur = float(df['adj_close'].iloc[-1])
            tech = q.compute_technical_indicators(df)
            val = q.evaluate_valuation_metric(tech, fd, symbol=sym)
            f_ = val.get('displayed_fair_value')
            if cur > 0:
                px[code] = cur
                if f_:
                    fv[code] = float(f_)
        except Exception:                                      # noqa: BLE001
            pass
        if i % 100 == 0 or i == len(need):
            print(f'   {i:>5}/{len(need)}  가격 {len(px):,} · 적정가 '
                  f'{len(fv):,} · {time.time() - t0:.0f}s')

    def weights_pub(hs):
        out, tot = {}, 0.0
        for h in hs:
            w = h.get('weight')
            if w is None:
                continue
            tot += w
            out[h['name']] = out.get(h['name'], 0.0) + w
        return ({k: v / tot for k, v in out.items()} if tot else {}), tot

    def weights_der(hs):
        out, tot = {}, 0.0
        for h in hs:
            qn, code = h.get('qty'), uniq.get(h['name'])
            if qn is None or not code or code not in px:
                continue
            v = float(qn) * px[code]
            if v <= 0:
                continue                    # 공매도·마이너스 수량은 제외
            tot += v
            out[h['name']] = out.get(h['name'], 0.0) + v
        return ({k: v / tot for k, v in out.items()} if tot else {}), tot

    def ratio_of(w):
        """Σ w_i × (적정가_i ÷ 현재가_i) + w_기타 × 1 — 167 과 같은 식."""
        num = den = 0.0
        for nm_, w_ in w.items():
            den += w_
            code = uniq.get(nm_)
            num += w_ * ((fv[code] / px[code])
                         if (code in fv and code in px) else 1.0)
        return (num / den) if den else None

    # ── R3 자기검사: 유도 비중 합이 1 인가 ────────────────────────────
    bad_sum = []
    for c in both[:50]:
        w, _ = weights_der(holdings[c])
        if w and abs(sum(w.values()) - 1.0) > R3_SUM_TOL:
            bad_sum.append((c, round(sum(w.values()), 5)))
    print(f'\n■ R3 자기검사 (유도 비중 합 = 1) '
          f'{"통과" if not bad_sum else f"실패 {bad_sum[:3]}"}')
    if bad_sum:
        print('   계산이 틀렸다 — 측정을 중단한다.')
        return 2

    # ── R1·R2: 대조군에서 비율이 같은가 ───────────────────────────────
    diffs, pairs = [], []
    for c in both:
        wp, tot = weights_pub(holdings[c])
        wd, _ = weights_der(holdings[c])
        if not wp or not wd or not (95.0 <= tot <= 105.0):
            continue
        rp, rd = ratio_of(wp), ratio_of(wd)
        if rp is None or rd is None:
            continue
        diffs.append(abs(rd - rp))
        pairs.append((c, round(rp, 4), round(rd, 4)))
    diffs.sort()
    med = statistics.median(diffs) if diffs else None
    p95 = diffs[int(len(diffs) * 0.95)] if diffs else None
    print(f'\n■ 대조 {len(diffs):,}개 · 비율 차이 중앙 {med:.5f} · '
          f'95분위 {p95:.5f}' if diffs else '\n■ 대조군 없음')
    r1 = med is not None and med <= R1_MEDIAN
    r2 = p95 is not None and p95 <= R2_P95
    print(f'   R1 중앙 ≤ {R1_MEDIAN}  → {"통과" if r1 else "미달"}')
    print(f'   R2 95분위 ≤ {R2_P95} → {"통과" if r2 else "미달"}')
    print('\n■ 차이가 가장 큰 5개')
    for c, rp, rd in sorted(pairs, key=lambda t: -abs(t[2] - t[1]))[:5]:
        print(f'   {c} {str(etf_registry.index().get(c, ""))[:26]:28} '
              f'발표 {rp} · 유도 {rd} · 차 {abs(rd - rp):.4f}')

    # ── R4: 적용하면 몇 개가 열리나 ───────────────────────────────────
    opened = {}
    for c in cand:
        wd, _ = weights_der(holdings[c])
        if not wd:
            continue
        cov = sum(w for nm_, w in wd.items()
                  if uniq.get(nm_) in fv) * 100.0
        if cov >= COVER_MIN:
            r = ratio_of(wd)
            nv = etf_registry.nav_of(c) or {}
            opened[c] = {'name': etf_registry.index().get(c),
                         'valued_pct': round(cov, 2), 'ratio': round(r, 4),
                         'nav': nv.get('nav'),
                         'holdings': len(holdings[c])}
    r4 = len(opened) >= R4_MIN_TARGETS
    print(f'\n■ R4 유도 비중으로 열리는 ETF {len(opened):,}개 '
          f'(기준 {R4_MIN_TARGETS}) → {"통과" if r4 else "미달"}')
    for c, v in list(opened.items())[:10]:
        print(f'   {c} {str(v["name"])[:28]:30} 평가 {v["valued_pct"]:5.1f}% · '
              f'비율 {v["ratio"]}')

    verdict = ('채택' if (r1 and r2 and r4) else '기각')
    print(f'\n■ 판정: **{verdict}** '
          f'(R1 {r1} · R2 {r2} · R3 True · R4 {r4})')
    if verdict == '기각':
        print('   기준 미달 — 유도 비중을 쓰지 않는다. 기준을 내리지 않는다.')

    doc = {'made': datetime.now().strftime('%Y-%m-%d'),
           'prereg': 'docs/PREREG_R170_DERIVED_WEIGHTS.md',
           'r1_median': (round(med, 6) if med is not None else None),
           'r2_p95': (round(p95, 6) if p95 is not None else None),
           'r1_pass': r1, 'r2_pass': r2, 'r3_pass': True, 'r4_pass': r4,
           'controls': len(diffs), 'candidates': len(cand),
           'opened': len(opened), 'opened_detail': opened,
           'verdict': verdict,
           'note': ('측정 전용. 해외·채권 ETF 577종목은 이 방법으로도 안 '
                    '된다 — 구성종목 가격·적정가가 우리에게 없다. '
                    '통과해도 원장에 ETF 가 없어 쓸모는 못 잰다(표시 전용).')}
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f'\n저장: {OUT}')
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
