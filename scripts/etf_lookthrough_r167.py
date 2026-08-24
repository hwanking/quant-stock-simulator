# -*- coding: utf-8 -*-
"""ETF 룩스루 적정가 — 조인·커버리지·산출 (라운드 167).

사전등록: `docs/PREREG_R167_ETF_LOOKTHROUGH.md`
판정 기준은 거기에 **측정 전에** 적혀 있다. 여기서 내리지 않는다.

■ 산식 (배수를 만들지 않는 형태)

      적정 NAV ÷ NAV  =  Σ_i w_i × (적정가_i ÷ 현재가_i)  +  w_기타 × 1
      적정가(ETF)     =  NAV × 위 비율

  좌수·설정단위가 식에 없다 — 못 아는 값을 안 쓴다.
  `w_기타`(주식이 아닌 몫)는 비율 1 로 두고, 그 크기를 결과에 적는다.

    C:/Python314/python.exe scripts/etf_lookthrough_r167.py [--value-limit 400]
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

#: 원시 수집물은 `.portfolio/` (6MB · gitignored). 없으면
#: `scripts/etf_holdings_r167.py` 를 먼저 돌린다.
HOLD = os.path.join(PROJ, '.portfolio', 'etf_holdings_r167.json')
NAMES = os.path.join(PROJ, '.portfolio', 'name_master.json')
OUT = os.path.join(PROJ, 'data', 'etf_lookthrough_r167.json')

#: 사전등록 R1·R2 문턱. 라운드 163 이 업종 매핑에서 채택한 90% 재사용.
COVER_MIN = 90.0
#: 사전등록 R3 — 통과 ETF 가 이보다 적으면 기능이 아니다.
MIN_ETFS = 30
#: 사전등록 R5 — 비중 합이 이 범위를 벗어난 ETF 는 뺀다.
WSUM_LO, WSUM_HI = 95.0, 105.0


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def load_name_map():
    """이름 → 코드. **정확 일치만** 쓴다 (사전등록 §4④).

    같은 이름이 둘 이상이면 **버린다** — 억지로 붙이면 남의 적정가가
    섞인다. ETF 는 제외한다(ETF 안의 ETF 는 룩스루 대상이 아니다).
    """
    with open(NAMES, encoding='utf-8') as f:
        doc = json.load(f)
    etf = set(etf_registry.index() or {})
    by_name = collections.defaultdict(set)
    meta = {}
    for r in doc.get('rows') or []:
        c = stock_code.normalize(r.get('code'))
        nm = str(r.get('name') or '').strip()
        if not c or not nm or c in etf:
            continue
        by_name[nm].add(c)
        meta[c] = {'name': nm, 'mkt': str(r.get('mkt') or '')}
    uniq = {nm: next(iter(cs)) for nm, cs in by_name.items() if len(cs) == 1}
    dupes = {nm: sorted(cs) for nm, cs in by_name.items() if len(cs) > 1}
    return uniq, dupes, meta


def fair_of(symbol, eng, q):
    """한 종목의 (적정가, 현재가). 못 내면 (None, 가격 또는 None).

    ⚠️ 라운드 167 — 처음에 **원본 일봉 프레임**을 그대로 넘겼다가 값이
       조용히 남의 것이 됐다(롯데리츠·SK리츠·ESR켄달스퀘어가 모두
       52,714원). 화면(`run_full_pipeline`)은 `compute_technical_indicators`
       를 거친 tech_df 를 넘긴다 — **같은 순서를 그대로 따른다** (§4).
       엔진에도 전제 가드를 넣어(§3) 다시는 조용히 틀리지 않게 했다.
    """
    try:
        px_df, fd = eng.generate_synthetic_bitemporal_data(
            symbol=symbol, start_date='2022-01-01')
        cur = float(px_df['adj_close'].iloc[-1])
        tech = q.compute_technical_indicators(px_df)
    except Exception:                                          # noqa: BLE001
        return None, None
    try:
        val = q.evaluate_valuation_metric(tech, fd, symbol=symbol)
    except Exception:                                          # noqa: BLE001
        return None, cur
    fv = val.get('displayed_fair_value')
    try:
        fv = float(fv) if fv is not None else None
    except (TypeError, ValueError):
        fv = None
    return fv, cur


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--value-limit', type=int, default=400,
                    help='적정가를 계산할 종목 수 상한 (등장 비중 순)')
    a = ap.parse_args()

    print('ETF 룩스루 적정가 (라운드 167)')
    print('사전등록: docs/PREREG_R167_ETF_LOOKTHROUGH.md')
    print('측정 전용 — 점수·게이트·문턱을 바꾸지 않는다\n')

    with open(HOLD, encoding='utf-8') as f:
        hdoc = json.load(f)
    holdings = hdoc.get('holdings') or {}
    print(f"■ 구성종목 있는 ETF {len(holdings):,}개 "
          f"(수집 {hdoc.get('made')})")

    uniq, dupes, meta = load_name_map()
    print(f'■ 이름→코드 표 {len(uniq):,}개 · 동명이인으로 버린 이름 '
          f'{len(dupes):,}개')

    # ── R5: 비중 합이 이상한 ETF 를 먼저 뺀다 ─────────────────────────
    ok_w, bad_w = {}, []
    for c, rows in holdings.items():
        s = sum(r['weight'] for r in rows if r.get('weight') is not None)
        if WSUM_LO <= s <= WSUM_HI:
            ok_w[c] = rows
        else:
            bad_w.append((c, round(s, 1)))
    print(f'■ R5 비중 합 {WSUM_LO:.0f}~{WSUM_HI:.0f}% — 통과 {len(ok_w):,} · '
          f'제외 {len(bad_w):,}')

    # ── R1: 이름→코드 조인율 (비중 가중) ──────────────────────────────
    join = {}
    need = collections.Counter()
    for c, rows in ok_w.items():
        w_all = w_join = 0.0
        for r in rows:
            w = r.get('weight')
            if w is None:
                continue
            w_all += w
            code = uniq.get(r['name'])
            if code:
                w_join += w
                need[code] += w
        join[c] = dict(weight_total=round(w_all, 2),
                       weight_joined=round(w_join, 2),
                       join_pct=round(w_join / w_all * 100, 2) if w_all else 0.0)
    r1_pass = [c for c, v in join.items() if v['join_pct'] >= COVER_MIN]
    print(f'■ R1 조인율 ≥ {COVER_MIN:.0f}% — 통과 {len(r1_pass):,} / '
          f'{len(ok_w):,} ({len(r1_pass) / max(1, len(ok_w)) * 100:.1f}%)')

    # ── 적정가 계산 — 등장 비중이 큰 종목부터 ─────────────────────────
    import bitemporal_engine as be
    import quant_indicators as qi
    eng, q = be.BitemporalEngine(), qi.QuantIndicatorsEngine()
    targets = [c for c, _ in need.most_common(a.value_limit)]
    print(f'\n■ 적정가 계산 대상 {len(targets):,}종목 '
          f'(구성종목으로 등장한 {len(need):,}개 중 상위)')
    fv, px, t0 = {}, {}, time.time()
    for i, c in enumerate(targets, 1):
        sym = f"{c}.KQ" if meta.get(c, {}).get('mkt') == 'KOSDAQ' else f"{c}.KS"
        f_, p_ = fair_of(sym, eng, q)
        if f_ is not None and p_:
            fv[c], px[c] = f_, p_
        if i % 25 == 0 or i == len(targets):
            print(f'   {i:>4}/{len(targets)}  적정가 {len(fv):,}개 · '
                  f'{time.time() - t0:.0f}s')

    print(f'■ 적정가를 낸 종목 {len(fv):,} / {len(targets):,} '
          f'({len(fv) / max(1, len(targets)) * 100:.1f}%)')

    # ── R4 자기검사: 적정가=현재가를 넣으면 비율이 1.000 인가 ──────────
    def ratio(rows, use_fv=True):
        num = den = other = 0.0
        for r in rows:
            w = r.get('weight')
            if w is None:
                continue
            den += w
            code = uniq.get(r['name'])
            if code and code in fv:
                num += w * ((fv[code] / px[code]) if use_fv else 1.0)
            else:
                other += w
                num += w * 1.0          # 값 판단을 하지 않는 몫
        return (num / den if den else None), (other / den * 100 if den else None)

    self_ok = True
    for c in r1_pass[:40]:
        r_, _ = ratio(ok_w[c], use_fv=False)
        if r_ is None or abs(r_ - 1.0) > 0.001:
            self_ok = False
            print(f'   [자기검사 실패] {c} → {r_}')
    print(f'■ R4 자기검사 (적정가=현재가 → 비율 1.000) '
          f'{"통과" if self_ok else "실패 ← 측정 중단"}')
    if not self_ok:
        return 2

    # ── R2: 적정가를 낼 수 있는 비중 ─────────────────────────────────
    res, r2_pass = {}, []
    live = etf_registry.live() or {}
    nav_by = {r['code']: r for r in (live.get('rows') or [])}
    for c in r1_pass:
        rows = ok_w[c]
        w_all = sum(r['weight'] for r in rows if r.get('weight') is not None)
        w_val = sum(r['weight'] for r in rows
                    if r.get('weight') is not None
                    and uniq.get(r['name']) in fv)
        cov = w_val / w_all * 100 if w_all else 0.0
        r_, other = ratio(rows)
        nv = nav_by.get(c) or {}
        nav = nv.get('nav')
        res[c] = {
            'name': (etf_registry.index() or {}).get(c),
            'join_pct': join[c]['join_pct'],
            'valued_pct': round(cov, 2),
            'other_pct': round(other or 0.0, 2),
            'ratio': round(r_, 4) if r_ else None,
            'nav': nav,
            'lookthrough_fair': (round(nav * r_, 2)
                                 if (nav and r_) else None),
            'price': nv.get('price'),
            'holdings': len(rows),
        }
        if cov >= COVER_MIN:
            r2_pass.append(c)
    print(f'■ R2 적정가 커버리지 ≥ {COVER_MIN:.0f}% — 통과 {len(r2_pass):,}')
    print(f'■ R3 통과 ETF ≥ {MIN_ETFS} — '
          f'{"통과" if len(r2_pass) >= MIN_ETFS else "미달"} '
          f'({len(r2_pass)}개)')

    print('\n■ 통과 ETF 상위 12 (룩스루 적정가)')
    for c in sorted(r2_pass,
                    key=lambda x: -(res[x]['valued_pct'] or 0))[:12]:
        v = res[c]
        print(f"   {c} {str(v['name'])[:26]:28} 조인 {v['join_pct']:5.1f}% · "
              f"평가 {v['valued_pct']:5.1f}% · 비율 {v['ratio']} · "
              f"NAV {v['nav']} → 룩스루 {v['lookthrough_fair']}")

    print('\n■ 사용자가 물어본 둘')
    for c in ('0040Y0', '480020'):
        v = res.get(c)
        if v:
            print(f'   {c} → {v}')
        else:
            j = join.get(c)
            print(f'   {c} → 통과 못 함 · 조인 {j}')

    doc = {
        'made': datetime.now().strftime('%Y-%m-%d'),
        'prereg': 'docs/PREREG_R167_ETF_LOOKTHROUGH.md',
        'cover_min': COVER_MIN, 'min_etfs': MIN_ETFS,
        'etfs_with_holdings': len(holdings),
        'wsum_excluded': len(bad_w), 'wsum_excluded_sample': bad_w[:10],
        'name_map': len(uniq), 'name_dupes': len(dupes),
        'r1_pass': len(r1_pass), 'r2_pass': len(r2_pass),
        'r3_pass': len(r2_pass) >= MIN_ETFS,
        'r4_selfcheck': self_ok,
        'valued_stocks': len(fv), 'valued_attempted': len(targets),
        'results': res,
        'note': ('측정 전용 — 점수·게이트·문턱을 바꾸지 않는다. 구성종목은 '
                 '스냅샷이라 과거 시점 구성이 아니고, 원장에 ETF 가 없어 '
                 '쓸모(성과 분리)는 이 라운드에서 잴 수 없다.'),
    }
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f'\n저장: {OUT}')
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
