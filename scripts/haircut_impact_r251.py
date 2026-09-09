# -*- coding: utf-8 -*-
"""
라운드 251 — 사전등록 R251 의 **R1(영향의 상한)** 과 **R2(어느 쪽이 나은가)**.

■ 절차를 하나로 합쳤다 — 기준은 안 바꿨다 (측정 전에 적는다)
  사전등록은 R1 을 *"지금 유니버스에서"* 재라고 적었다. 그런데 같은 케이스를
  **원장 리플레이**로 재면 ① 네트워크를 안 쓰고(실시세 경합 없음 · R218)
  ② 여러 국면이 섞이고 ③ **R2 가 쓸 짝 자료가 같은 실행에서 나온다.**
  그래서 한 번 돌려 R1 의 수를 먼저 내고, 그것이 작으면 R2 를 **읽지 않는다.**
  판정 기준(§3·§4)은 사전등록 그대로다.

■ 어떻게 재나
  같은 (종목, 기준일)을 **두 번** 돌린다 — 고정 보정 0.98 을 켜고 한 번, 끄고
  한 번. 사이에 윈저화·확장구간 클립이라는 **비선형 단계 둘**이 있어 되나눠서
  답을 낼 수 없다(사전등록 §1).

  ⚠️ 두 번째 판이 정말 다른 상수로 돌았는지 **출력으로 확인한다** —
     엔진이 `fair_fixed_haircut_pct` 를 내보내므로 그것이 −2.0 → 0.0 으로
     바뀌었는지 본다. 상수를 바꿔 놓고 캐시가 옛 값을 돌려주면 '차이 없음'이
     나오는데, 그것은 **효과가 없는 것이 아니라 안 돈 것**이다
     (라운드 191 — 존재는 실행이 아니다).

■ 표본 — 새 숫자를 만들지 않는다
  겹치지 않는 부분집합(`ledger_view` · 같은 종목 35일 = 25봉×7/5 · R217·R54b)
  에서 구간(train/valid/blind) × 적정가 구역으로 층화해 뽑는다. 시드 251.

    C:/Python314/python.exe scripts/haircut_impact_r251.py --n 300
    C:/Python314/python.exe scripts/haircut_impact_r251.py --n 3000
"""
import argparse
import io
import json
import os
import random
import sys
import time
from collections import Counter, defaultdict

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

LEDGER = os.path.join(PROJ, '.portfolio', 'virtual_graded.jsonl')
OUT = os.path.join(PROJ, 'data', 'haircut_impact_r251.json')
#: 짝 자료(종목·기준일별 값)는 **원장과 같은 자리**(gitignored)에 둔다 — §9 의 이름 감사가
#: 원장 케이스 속 종목 코드까지 본다. 커밋되는 산출물에는 집계만 남긴다.
PAIRS_OUT = os.path.join(PROJ, '.portfolio', 'haircut_pairs_r251.json')
SEED = 251
BUY_SCORE = 58                       # R49 계열이 이미 쓰는 값


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def load_rows():
    """원장에서 필요한 칸만. 구간은 원장이 이미 적어 둔 split 을 쓴다."""
    rows = []
    for ln in io.open(LEDGER, encoding='utf-8', errors='replace'):
        ln = ln.strip()
        if not ln:
            continue
        try:
            r = json.loads(ln)
        except Exception:                                      # noqa: BLE001
            continue
        d = str(r.get('date') or '')[:10]
        if len(d) != 10 or not r.get('ticker'):
            continue
        try:
            ret = float(r.get('return_pct'))
            sc = float(r.get('score') or 0)
        except (TypeError, ValueError):
            continue
        rows.append({'ticker': r['ticker'], 'date': d,
                     'split': str(r.get('split') or '?'),
                     'zone': str(r.get('entry_zone') or '?'),
                     'score': sc, 'ret': ret,
                     'outcome': r.get('outcome'),
                     'regime': r.get('regime')})
    return rows


def spaced(rows):
    """같은 종목 35일 안 재신호는 한 사건이다 — 앞선 것만 남긴다(R217 규칙)."""
    import ledger_view as lv
    by = defaultdict(list)
    for r in sorted(rows, key=lambda x: (x['ticker'], x['date'])):
        kept = by[r['ticker']]
        if not lv.too_close(kept, r['date']):
            kept.append(r['date'])
            r['_keep'] = True
    return [r for r in rows if r.get('_keep')]


def main():
    _utf8()
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=300)
    args = ap.parse_args()

    print("R251 R1 — 고정 보정을 지우면 무엇이 얼마나 바뀌나")
    print("=" * 78)
    rows = load_rows()
    print(f"원장에서 읽은 행 {len(rows):,}")
    sp = spaced(rows)
    print(f"겹치지 않는 부분집합 {len(sp):,} "
          f"({100.0 * len(sp) / max(1, len(rows)):.1f}%) — 같은 종목 35일 규칙")

    # 층화: 구간 × 구역 — 둘 다 이미 채택된 칸
    strata = defaultdict(list)
    for r in sp:
        strata[(r['split'], r['zone'])].append(r)
    rng = random.Random(SEED)
    keys = sorted(strata)
    per = max(1, args.n // max(1, len(keys)))
    pick = []
    for k in keys:
        v = strata[k][:]
        rng.shuffle(v)
        pick += v[:per]
    rng.shuffle(pick)
    pick = pick[:args.n]
    print(f"층 {len(keys)}개 × 층당 최대 {per} → 표본 {len(pick)}건")
    print(f"   구간별 {dict(Counter(r['split'] for r in pick))}")

    import quant_indicators as qi
    import bitemporal_engine as be

    def run(pairs, haircut, tag):
        qi.QuantIndicatorsEngine.FAIR_FIXED_HAIRCUT = haircut
        q = qi.QuantIndicatorsEngine()
        eng = be.BitemporalEngine()
        got, err = {}, 0
        t0 = time.time()
        for i, r in enumerate(pairs, 1):
            try:
                snap = q.run_full_pipeline(r['ticker'], r['date'],
                                           b_engine=eng, rho_cutoff=0.80)
                fs = snap['four_scores']
                ve = snap.get('val_eval') or {}
                got[(r['ticker'], r['date'])] = {
                    'fair': fs.get('displayed_fair_value'),
                    'zone': fs.get('entry_zone'),
                    'status': ve.get('fair_value_status'),
                    'buy': ve.get('recommended_buy_price'),
                    'wins': ve.get('fair_winsorized'),
                    'clip': ve.get('fair_center_clipped'),
                    'hc': ve.get('fair_fixed_haircut_pct'),
                    'score': fs.get('final_action_score'),
                }
            except Exception:                                  # noqa: BLE001
                err += 1
            if i % 50 == 0:
                print(f"   {tag} {i}/{len(pairs)} · "
                      f"{time.time() - t0:.0f}초 · 실패 {err}")
        print(f"   {tag} 끝 — 성공 {len(got)} · 실패 {err} · "
              f"{time.time() - t0:.0f}초")
        return got, err

    a, err_a = run(pick, 0.98, '켠 판')
    b, err_b = run(pick, 1.00, '끈 판')

    # ── 실행 증거 — 두 번째 판이 정말 다른 상수로 돌았나 ──────────────────
    hc_a = Counter(round(v['hc'], 2) for v in a.values() if v['hc'] is not None)
    hc_b = Counter(round(v['hc'], 2) for v in b.values() if v['hc'] is not None)
    print()
    print("실행 증거 — 엔진이 내보낸 고정 보정 값 (존재가 아니라 실행을 본다)")
    print(f"   켠 판 {dict(hc_a)}   끈 판 {dict(hc_b)}")
    ran_ok = (set(hc_a) == {-2.0} and set(hc_b) == {0.0})
    if not ran_ok:
        print("   ⚠️ 두 판이 같은 상수로 돌았다 — 이것은 '차이 없음'이 아니라")
        print("      '안 돌았다'이다. 여기서 멈춘다 (라운드 191).")

    keys2 = sorted(set(a) & set(b))
    print()
    print(f"R1 — 양쪽 다 성공한 {len(keys2)}건에서 무엇이 바뀌나")
    print("-" * 78)
    ch = Counter()
    zone_moves = Counter()
    fair_deltas = []
    for k in keys2:
        x, y = a[k], b[k]
        if x['zone'] != y['zone']:
            ch['구역 바뀜'] += 1
            zone_moves[f"{x['zone']} → {y['zone']}"] += 1
        if (x['buy'] is None) != (y['buy'] is None):
            ch['권장매수가 생김/사라짐'] += 1
        if x['status'] != y['status']:
            ch['신뢰도 등급 바뀜'] += 1
        if x['score'] != y['score']:
            ch['최종 점수 바뀜'] += 1
        if x['fair'] and y['fair']:
            fair_deltas.append(y['fair'] / x['fair'] - 1.0)
    for k2, v in ch.most_common():
        print(f"   {k2:<24}{v:>6} / {len(keys2)}  ({100.0 * v / max(1, len(keys2)):5.1f}%)")
    if not ch:
        print("   바뀐 것이 없다")
    if fair_deltas:
        fair_deltas.sort()
        med = fair_deltas[len(fair_deltas) // 2]
        print(f"   적정가 변화율 — 중앙 {100 * med:+.3f}% · "
              f"최소 {100 * fair_deltas[0]:+.3f}% · 최대 {100 * fair_deltas[-1]:+.3f}%")
        print(f"      (단순 되나눔이면 전부 +2.041% 여야 한다 — "
              f"그렇지 않은 것이 윈저화·클립의 몫이다)")
    print()
    print("   구역이 어떻게 움직였나 (상위 10)")
    for mv, v in zone_moves.most_common(10):
        print(f"      {mv:<44}{v:>5}")

    out = {'gate': 'R1', 'seed': SEED, 'n_asked': args.n,
           'ledger_rows': len(rows), 'spaced_rows': len(sp),
           'sample': len(pick), 'paired': len(keys2),
           'err_on': err_a, 'err_off': err_b,
           'haircut_seen_on': {str(k): v for k, v in hc_a.items()},
           'haircut_seen_off': {str(k): v for k, v in hc_b.items()},
           'execution_evidence_ok': ran_ok,
           'changes': dict(ch), 'zone_moves': dict(zone_moves),
           'fair_delta_median_pct': (100 * fair_deltas[len(fair_deltas) // 2]
                                     if fair_deltas else None),
           'pairs_file': os.path.relpath(PAIRS_OUT, PROJ),
           }
    json.dump(out, io.open(OUT, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    json.dump({'seed': SEED, 'pairs': [{'ticker': k[0], 'date': k[1],
                                        'on': a[k], 'off': b[k]} for k in keys2]},
              io.open(PAIRS_OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    print(f"\n저장: {OUT}  · 짝 자료: {PAIRS_OUT} (gitignored)")
    print("   (R2 는 이 짝 자료를 읽어 별도로 판정한다 — R1 이 작으면 안 읽는다)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
