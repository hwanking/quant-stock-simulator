# -*- coding: utf-8 -*-
"""
라운드 267 — 사전등록 R267: R251(고정 보정 0.98 지울 것인가)을 **날짜 하한을 채우는 표본**으로
다시 잰다. 판정 기준은 R251 §4 그대로 · 바꾸는 것은 표본뿐.

■ 표본 (사전등록 §1)
  겹치지 않는 부분집합에서 valid·blind 는 **기준일 전부** × 날짜당 K, train 은 시드로 뽑은
  날짜 300개 × K'. K·K' 는 4시간 예산 나눗셈(20 · 6). 시드 267 · R251 표본과 독립.

■ 실행
  같은 (종목, 기준일)을 켜고(0.98)·끄고(1.00) 두 번 돌린다. **체크포인트** — 200건마다 짝
  자료를 저장하고 `--resume` 이면 이어서 돈다(라운드 253 · 긴 실행이 죽으면 그날 것을 통째로
  잃는다). 실행 증거(`fair_fixed_haircut_pct`)를 두 판에서 센다.

■ 판정
  잣대·부트·조인은 `scripts/haircut_r2_r251.py` 의 함수를 불러 쓴다 — 베끼면 한쪽만 고쳐진다.

    C:/Python314/python.exe scripts/haircut_r267.py --plan          (표본만 세고 끝)
    C:/Python314/python.exe scripts/haircut_r267.py                 (측정)
    C:/Python314/python.exe scripts/haircut_r267.py --resume        (이어서)
    C:/Python314/python.exe scripts/haircut_r267.py --judge         (짝 자료로 판정만)
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
from scripts import haircut_impact_r251 as _r1              # noqa: E402  (load_rows · spaced)
from scripts import haircut_r2_r251 as _r2                  # noqa: E402  (ledger_join · spread · boot_delta)

OUT = os.path.join(PROJ, 'data', 'haircut_r267.json')
PAIRS_OUT = os.path.join(PROJ, '.portfolio', 'haircut_pairs_r267.json')   # gitignored (§9)
SEED = 267
BUDGET_HOURS = 4.0
K_VB = 20            # valid·blind 날짜당 — 예산 나눗셈 (사전등록 §1)
TRAIN_DATES = 300
K_TRAIN = 6
DATE_FLOOR = 30      # R45·R84 가 쓰는 시장 수준 변수의 날짜 하한
CHECKPOINT_EVERY = 200


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def build_sample():
    rows = _r1.load_rows()
    sp = _r1.spaced(rows)
    by_split_date = defaultdict(lambda: defaultdict(list))
    for r in sp:
        by_split_date[r['split']][r['date']].append(r)
    rng = random.Random(SEED)
    pick = []
    plan = {}
    for split in ('valid', 'blind'):
        dates = sorted(by_split_date[split])
        n = 0
        for d in dates:
            v = by_split_date[split][d][:]
            rng.shuffle(v)
            pick += v[:K_VB]
            n += len(v[:K_VB])
        plan[split] = {'dates_all': len(dates), 'k': K_VB, 'cases': n}
    tdates = sorted(by_split_date['train'])
    rng.shuffle(tdates)
    tdates = sorted(tdates[:TRAIN_DATES])
    n = 0
    for d in tdates:
        v = by_split_date['train'][d][:]
        rng.shuffle(v)
        pick += v[:K_TRAIN]
        n += len(v[:K_TRAIN])
    plan['train'] = {'dates_all': len(by_split_date['train']), 'dates_used': len(tdates),
                     'k': K_TRAIN, 'cases': n}
    rng.shuffle(pick)
    return rows, sp, pick, plan


def _load_pairs():
    if os.path.isfile(PAIRS_OUT):
        try:
            return json.load(io.open(PAIRS_OUT, encoding='utf-8'))
        except Exception:                                      # noqa: BLE001
            pass
    return {'seed': SEED, 'on': {}, 'off': {}, 'err_on': 0, 'err_off': 0}


def _save_pairs(st):
    json.dump(st, io.open(PAIRS_OUT, 'w', encoding='utf-8'), ensure_ascii=False)


def run_pass(pick, haircut, tag, st, key):
    import quant_indicators as qi
    import bitemporal_engine as be
    qi.QuantIndicatorsEngine.FAIR_FIXED_HAIRCUT = haircut
    q = qi.QuantIndicatorsEngine()
    eng = be.BitemporalEngine()
    got = st[key]
    done = set(got)
    todo = [r for r in pick if f"{r['ticker']}|{r['date']}" not in done]
    print(f"   {tag} — 이미 {len(done)} · 남음 {len(todo)}")
    t0 = time.time()
    err = 0
    for i, r in enumerate(todo, 1):
        k = f"{r['ticker']}|{r['date']}"
        try:
            snap = q.run_full_pipeline(r['ticker'], r['date'], b_engine=eng, rho_cutoff=0.80)
            fs = snap['four_scores']
            ve = snap.get('val_eval') or {}
            got[k] = {'zone': fs.get('entry_zone'), 'hc': ve.get('fair_fixed_haircut_pct'),
                      'fair': fs.get('displayed_fair_value')}
        except Exception:                                      # noqa: BLE001
            err += 1
        if i % CHECKPOINT_EVERY == 0:
            st[f'err_{key}'] = st.get(f'err_{key}', 0) + err
            err = 0
            _save_pairs(st)
            print(f"   {tag} {i}/{len(todo)} · {time.time() - t0:.0f}초 · 체크포인트")
    st[f'err_{key}'] = st.get(f'err_{key}', 0) + err
    _save_pairs(st)
    print(f"   {tag} 끝 — 성공 {len(got)} · 이번 실패 {err} · {time.time() - t0:.0f}초")


def judge(rows_n, sp_n, plan):
    st = _load_pairs()
    on, off = st['on'], st['off']
    hc_on = Counter(round(v['hc'], 2) for v in on.values() if v.get('hc') is not None)
    hc_off = Counter(round(v['hc'], 2) for v in off.values() if v.get('hc') is not None)
    ran_ok = (set(hc_on) == {-2.0} and set(hc_off) == {0.0})
    print()
    print(f"실행 증거 — 켠 판 {dict(hc_on)} · 끈 판 {dict(hc_off)} · ok={ran_ok}")
    keys = sorted(set(on) & set(off))
    pairs = [(k.split('|')[0], k.split('|')[1]) for k in keys]
    joined = _r2.ledger_join(pairs)
    print(f"짝 {len(keys):,} · 원장 결과 이음 {len(joined):,}")
    rows_by_split = defaultdict(list)
    for k in keys:
        t, d = k.split('|')
        if (t, d) not in joined:
            continue
        ret, split = joined[(t, d)]
        rows_by_split[split].append((d, on[k].get('zone'), off[k].get('zone'), ret))
    rng = random.Random(SEED)
    out = {'gate': 'R2·R3 (R267)', 'seed': SEED, 'boot': _r2.BOOT, 'ledger_rows': rows_n,
           'spaced_rows': sp_n, 'plan': plan, 'pairs': len(keys), 'joined': len(joined),
           'execution_evidence_ok': ran_ok, 'date_floor': DATE_FLOOR, 'splits': {}}
    if not ran_ok:
        out['verdict'] = '미측정 — 실행 증거 없음(두 판이 같은 상수로 돌았다)'
        json.dump(out, io.open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f"   >> {out['verdict']}")
        return 1
    print()
    print(f"   {'구간':<7}{'케이스':>7}{'날짜':>6}{'켠 간격':>9}{'끈 간격':>9}{'Δ(끈−켠)':>10}{'CI95':>20}")
    print('   ' + '-' * 70)
    signs = {}
    floor_ok = True
    for split in ('train', 'valid', 'blind'):
        rws = rows_by_split.get(split, [])
        nd = len({r[0] for r in rws})
        if split in ('valid', 'blind') and nd < DATE_FLOOR:
            floor_ok = False
        s_on, c_on, r_on = _r2.spread(rws, 'on')
        s_off, c_off, r_off = _r2.spread(rws, 'off')
        if s_on is None or s_off is None:
            print(f"   {split:<7}{len(rws):>7}{nd:>6}   한쪽 구역이 비어 못 잰다")
            out['splits'][split] = {'n': len(rws), 'dates': nd, 'note': '한쪽 구역이 비었다'}
            continue
        d = s_off - s_on
        ci = _r2.boot_delta(rws, rng)
        lo, hi, nb = ci if ci else (None, None, 0)
        excl = (ci is not None) and (lo > 0 or hi < 0)
        signs[split] = 1 if d > 0 else (-1 if d < 0 else 0)
        out['splits'][split] = {'n': len(rws), 'dates': nd, 'spread_on': round(s_on, 4),
                                'spread_off': round(s_off, 4), 'n_cheap_on': c_on, 'n_cheap_off': c_off,
                                'delta': round(d, 4), 'ci95': [round(lo, 4), round(hi, 4)] if ci else None,
                                'boot_ok': nb, 'ci95_excl0': excl}
        ci_txt = f"[{lo:+.2f}, {hi:+.2f}]" if ci else '부트 실패'
        print(f"   {split:<7}{len(rws):>7}{nd:>6}{s_on:>+9.3f}{s_off:>+9.3f}{d:>+10.3f}{ci_txt:>20}")
    have = [s for s in ('train', 'valid', 'blind') if s in signs]
    all_excl = all(out['splits'][s].get('ci95_excl0') for s in have) and len(have) == 3
    same = len(set(signs.values())) == 1 and len(have) == 3
    if not floor_ok:
        verdict = '미측정 — valid·blind 날짜 하한 30 을 못 채웠다'
    elif same and all_excl and signs['train'] > 0:
        verdict = '(가) 지우는 쪽이 세 구간에서 낫다 — 결정 · 배포는 11-16 이후'
    elif same and all_excl and signs['train'] < 0:
        verdict = '(나) 유지하는 쪽이 세 구간에서 낫다 — 유지 · 실측으로 유지'
    else:
        verdict = '(다) 못 가린다 — 현행 유지 · 날짜 하한은 채웠다 (못 봤다가 아니라 보니 없다)'
    print()
    print(f"   방향 {[(s, signs[s]) for s in have]} · CI 가 0 을 제외한 구간 "
          f"{[s for s in have if out['splits'][s].get('ci95_excl0')]} · 날짜 하한 충족 {floor_ok}")
    print(f"   >> {verdict}")
    out.update({'verdict': verdict, 'same_sign': same, 'all_ci_excl0': all_excl, 'date_floor_ok': floor_ok})
    json.dump(out, io.open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f"\n저장: {OUT}")
    return 0


def main():
    _utf8()
    ap = argparse.ArgumentParser()
    ap.add_argument('--plan', action='store_true')
    ap.add_argument('--resume', action='store_true')
    ap.add_argument('--judge', action='store_true')
    args = ap.parse_args()
    print("R267 — R251 을 날짜 하한을 채우는 표본으로 다시 잰다")
    print("=" * 78)
    rows, sp, pick, plan = build_sample()
    print(f"원장 {len(rows):,} · 겹치지 않는 부분집합 {len(sp):,}")
    for s, p in plan.items():
        print(f"   {s:<6} {p}")
    print(f"표본 {len(pick):,}건 · 두 판 = {2 * len(pick):,} 케이스-판 · "
          f"예산 {BUDGET_HOURS}시간(케이스당 0.76~1.70초 → {2 * len(pick) * 0.76 / 3600:.1f}~{2 * len(pick) * 1.70 / 3600:.1f}시간)")
    if args.plan:
        return 0
    if not args.judge:
        st = _load_pairs() if args.resume else {'seed': SEED, 'on': {}, 'off': {}, 'err_on': 0, 'err_off': 0}
        if not args.resume and os.path.isfile(PAIRS_OUT):
            os.remove(PAIRS_OUT)
        run_pass(pick, 0.98, '켠 판', st, 'on')
        run_pass(pick, 1.00, '끈 판', st, 'off')
    return judge(len(rows), len(sp), plan)


if __name__ == '__main__':
    sys.exit(main())
