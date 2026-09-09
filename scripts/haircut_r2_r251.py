# -*- coding: utf-8 -*-
"""
라운드 251 — 사전등록 R251 의 **R2·R3** (어느 쪽이 나은가 · 방향이 같은가).

■ 재료
  `scripts/haircut_impact_r251.py` 가 만든 짝 자료(`data/haircut_impact_r251.json`) —
  같은 (종목, 기준일)을 고정 보정을 **켜고(0.98) · 끄고(1.00)** 두 번 돌린 구역.
  20봉 결과(`return_pct`)는 원장에서 (종목, 기준일)로 잇는다. 결과는 두 판이 같다 —
  다른 것은 **구역 라벨**뿐이다.

■ 무엇을 재나 (사전등록 §2 H1 — 구역이 20봉 결과를 **더 잘** 가르는가)
  '가르는 정도' = **싼 구역(안전마진 확보 · 적정가 이하) 의 평균 수익 − 나머지 구역의
  평균 수익**. R183 의 구역 표와 R215 가 견준 바로 그 갈래를 재사용한다 — 새 문턱 없음.
  '판정 불가'는 어느 쪽에도 안 넣는다(적정가가 없는 행 · R183·R185 가 이미 막는다).
  Δ = 끈 판의 간격 − 켠 판의 간격. 양수면 지우는 쪽이 더 잘 가른다.

  보조로 **바뀐 케이스만** 본다(146건) — 옮겨 간 구역의 기존 케이스와 수익이
  닮았으면 새 라벨이 맞고, 떠난 구역과 닮았으면 옛 라벨이 맞다. 판정에는 안 쓴다.

■ 표본 단위 · 불확실성
  날짜 군집 부트스트랩(시드 251 · 2,000회) — 같은 날 케이스는 시장을 공유한다(R45·R80).
  세 구간 각각 CI95. 판정은 사전등록 §4 의 세 갈래 그대로.

    C:/Python314/python.exe scripts/haircut_r2_r251.py
"""
import io
import json
import os
import random
import sys
from collections import defaultdict

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

LEDGER = os.path.join(PROJ, '.portfolio', 'virtual_graded.jsonl')
PAIRS = os.path.join(PROJ, 'data', 'haircut_impact_r251.json')          # 집계 · 실행 증거
PAIRS_ROWS = os.path.join(PROJ, '.portfolio', 'haircut_pairs_r251.json')  # 짝 자료 (gitignored · §9)
OUT = os.path.join(PROJ, 'data', 'haircut_r2_r251.json')
SEED = 251
BOOT = 2000
CHEAP = ('안전마진 확보', '적정가 이하 (안전마진 미확보)')      # R183 구역 이름 그대로
NA_ZONE = '판정 불가'


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def ledger_join(keys):
    want = set(keys)
    got = {}
    for ln in io.open(LEDGER, encoding='utf-8', errors='replace'):
        ln = ln.strip()
        if not ln:
            continue
        try:
            r = json.loads(ln)
        except Exception:                                      # noqa: BLE001
            continue
        k = (r.get('ticker'), str(r.get('date') or '')[:10])
        if k in want and k not in got:
            try:
                got[k] = (float(r['return_pct']), str(r.get('split') or '?'))
            except (KeyError, TypeError, ValueError):
                pass
    return got


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def spread(rows, which):
    """싼 구역 평균 − 나머지 평균 (판정 불가 제외). rows: (date, zone_on, zone_off, ret)."""
    cheap, rest = [], []
    for _d, zon, zoff, ret in rows:
        z = zon if which == 'on' else zoff
        if not z or z == NA_ZONE:
            continue
        (cheap if z in CHEAP else rest).append(ret)
    if len(cheap) < 2 or len(rest) < 2:
        return None, len(cheap), len(rest)
    return mean(cheap) - mean(rest), len(cheap), len(rest)


def boot_delta(rows, rng):
    by_date = defaultdict(list)
    for r in rows:
        by_date[r[0]].append(r)
    dates = sorted(by_date)
    deltas = []
    for _ in range(BOOT):
        samp = []
        for _ in dates:
            samp += by_date[dates[rng.randrange(len(dates))]]
        s_on, _a, _b = spread(samp, 'on')
        s_off, _c, _d = spread(samp, 'off')
        if s_on is None or s_off is None:
            continue
        deltas.append(s_off - s_on)
    if len(deltas) < BOOT // 2:
        return None
    deltas.sort()
    return deltas[int(0.025 * len(deltas))], deltas[int(0.975 * len(deltas)) - 1], len(deltas)


def main():
    _utf8()
    print("R251 R2·R3 — 고정 보정을 지우면 구역이 20봉 결과를 더 잘 가르나")
    print("=" * 78)
    pj = json.load(io.open(PAIRS, encoding='utf-8'))
    pairs = pj.get('pairs') or []
    if not pairs and os.path.isfile(PAIRS_ROWS):
        pairs = json.load(io.open(PAIRS_ROWS, encoding='utf-8')).get('pairs') or []
    print(f"짝 자료 {len(pairs):,}건 (실행 증거 {pj.get('execution_evidence_ok')})")
    if not pj.get('execution_evidence_ok'):
        print("   실행 증거가 없다 — 두 판이 같은 상수로 돌았을 수 있다. 여기서 멈춘다.")
        return 1

    keys = [(p['ticker'], p['date']) for p in pairs]
    joined = ledger_join(keys)
    print(f"원장에서 20봉 결과를 이은 건 {len(joined):,} / {len(keys):,}")

    rows_by_split = defaultdict(list)
    changed = []
    for p in pairs:
        k = (p['ticker'], p['date'])
        if k not in joined:
            continue
        ret, sp = joined[k]
        zon, zoff = p['on'].get('zone'), p['off'].get('zone')
        rows_by_split[sp].append((p['date'], zon, zoff, ret))
        if zon != zoff:
            changed.append((sp, zon, zoff, ret))

    rng = random.Random(SEED)
    out = {'gate': 'R2·R3', 'seed': SEED, 'boot': BOOT, 'pairs': len(pairs),
           'joined': len(joined), 'cheap_zones': list(CHEAP), 'splits': {}}
    print()
    print(f"   {'구간':<7}{'케이스':>7}{'날짜':>6}{'켠 간격':>9}{'끈 간격':>9}"
          f"{'Δ(끈−켠)':>10}{'CI95':>20}")
    print('   ' + '-' * 70)
    signs = {}
    for sp in ('train', 'valid', 'blind'):
        rows = rows_by_split.get(sp, [])
        nd = len({r[0] for r in rows})
        s_on, c_on, r_on = spread(rows, 'on')
        s_off, c_off, r_off = spread(rows, 'off')
        if s_on is None or s_off is None:
            print(f"   {sp:<7}{len(rows):>7}{nd:>6}   한쪽 구역이 비어 못 잰다")
            out['splits'][sp] = {'n': len(rows), 'dates': nd, 'note': '한쪽 구역이 비었다'}
            continue
        d = s_off - s_on
        ci = boot_delta(rows, rng)
        lo, hi, nb = ci if ci else (None, None, 0)
        excl = (ci is not None) and (lo > 0 or hi < 0)
        signs[sp] = 1 if d > 0 else (-1 if d < 0 else 0)
        out['splits'][sp] = {
            'n': len(rows), 'dates': nd,
            'spread_on': round(s_on, 4), 'spread_off': round(s_off, 4),
            'n_cheap_on': c_on, 'n_cheap_off': c_off,
            'delta': round(d, 4),
            'ci95': [round(lo, 4), round(hi, 4)] if ci else None,
            'boot_ok': nb, 'ci95_excl0': excl}
        ci_txt = f"[{lo:+.2f}, {hi:+.2f}]" if ci else '부트 실패'
        print(f"   {sp:<7}{len(rows):>7}{nd:>6}{s_on:>+9.3f}{s_off:>+9.3f}"
              f"{d:>+10.3f}{ci_txt:>20}")

    # ── 보조: 바뀐 케이스만 ──────────────────────────────────────────────
    print()
    print(f"보조 — 구역이 바뀐 {len(changed)}건 (판정에는 안 쓴다)")
    print("-" * 78)
    mv = defaultdict(list)
    for sp, zon, zoff, ret in changed:
        mv[(zon, zoff)].append(ret)
    for (zon, zoff), rets in sorted(mv.items(), key=lambda kv: -len(kv[1])):
        print(f"   {str(zon)[:22]:<22} → {str(zoff)[:22]:<22}"
              f"  n={len(rets):>3}  평균 {mean(rets):+.2f}%")
    out['changed'] = {f"{a} → {b}": {'n': len(v), 'mean_ret': round(mean(v), 4)}
                      for (a, b), v in mv.items()}

    # ── 판정 — 사전등록 §4 세 갈래 ──────────────────────────────────────
    print()
    print("판정 (사전등록 §4)")
    print("-" * 78)
    have = [sp for sp in ('train', 'valid', 'blind') if sp in signs]
    all_excl = all(out['splits'][sp].get('ci95_excl0') for sp in have) and len(have) == 3
    same = len(set(signs.values())) == 1 and len(have) == 3
    if same and all_excl and signs['train'] > 0:
        verdict = '(가) 지우는 쪽이 세 구간에서 낫다 — 결정 · 배포는 11-16 이후'
    elif same and all_excl and signs['train'] < 0:
        verdict = '(나) 유지하는 쪽이 세 구간에서 낫다 — 유지 · 실측으로 유지'
    else:
        verdict = '(다) 못 가린다 — 현행 유지 · 지울 근거도 유지할 근거도 못 세웠다'
    print(f"   방향 {[(sp, signs[sp]) for sp in have]} · CI 가 0 을 제외한 구간 "
          f"{[sp for sp in have if out['splits'][sp].get('ci95_excl0')]}")
    print(f"   >> {verdict}")
    out['verdict'] = verdict
    out['same_sign'] = same
    out['all_ci_excl0'] = all_excl

    json.dump(out, io.open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f"\n저장: {OUT}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
