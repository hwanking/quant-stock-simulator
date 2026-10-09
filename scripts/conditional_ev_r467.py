# -*- coding: utf-8 -*-
"""
라운드 467 — 과거 원장으로 '비용을 넘는 조건'을 찾을 수 있나 (사전등록 docs/PREREG_R467_CONDITIONAL_EV.md).

판정 기준은 그 문서에 **재기 전에** 적었다. 여기서는 그대로 잰다 — 기준을 다시 적지 않고 아래 상수로만 옮긴다.
판정에 쓰는 모형은 하나(학습 구간 OLS · 예측 > 0 이면 고름)이고, 재료 하나씩 나눈 지도(52칸)는 설명용이다.
원장은 **읽기만** 한다. 산출물: data/conditional_ev_r467.json
"""
import datetime
import io
import json
import math
import os
import sys
from collections import Counter

import numpy as np

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
import artifact_io                                             # noqa: E402
import ledger_view as lv                                       # noqa: E402
import verdict_core                                            # noqa: E402

LEDGER = os.path.join(PROJ, '.portfolio', 'virtual_graded.jsonl')
OUT = os.path.join(PROJ, 'data', 'conditional_ev_r467.json')
SEED, BOOT = 467, 2000
COST = 0.41                  # 운영 왕복 비용 (R350) — verdict_core.COST_PCT 와 다르면 멈춘다
DATE_FLOOR = 30              # R0 — 이미 채택된 하한 (R84·R45)
REPRO_TOL = 0.01             # R-재현 — 점수대 평균 수익 차이 %p
SPLITS = ('train', 'valid', 'blind')
BANDS = ((0, 39), (40, 49), (50, 54), (55, 59), (60, 64), (65, 69), (70, 100))
CATS = ('band', 'regime', 'market', 'asset_type', 'm10_above', 'demark_state', 'entry_zone', 'action_title')
CONTS = ('rsi', 'bb_pos', 'range_pos', 'vol20', 'net_expected', 'eff_sample', 'win_rate')
MAP_CELLS = 52               # 사전등록이 고정한 지도 칸 수
Z_MAP = 3.31                 # Bonferroni(52) — 3.3015 를 올림 (R113)


def fnum(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def band_of(score):
    s = fnum(score)
    if s is None:
        return None
    for lo, hi in BANDS:
        if lo <= s <= hi:
            return f'{lo}-{hi}'
    return None


def load():
    rows = []
    with io.open(LEDGER, encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                rows.append(json.loads(ln))
    return rows


def repro(stat, n_ledger, cal):
    """R-재현 — 원장 행수와 점수대 평균 수익이 집계표와 같은가."""
    sums, cnts = Counter(), Counter()
    for r in stat:
        b, ret = band_of(r.get('score')), fnum(r.get('return_pct'))
        if b is None or ret is None:
            continue
        sums[b] += ret
        cnts[b] += 1
    per, ok = [], cal.get('ledger_rows') == n_ledger
    for cb in cal.get('bands') or []:
        key = f"{cb.get('lo')}-{cb.get('hi')}"
        mine = sums[key] / cnts[key] if cnts[key] else None
        theirs = fnum(cb.get('avg_return'))
        diff = (mine - theirs) if (mine is not None and theirs is not None) else None
        per.append(dict(band=key, mine=None if mine is None else round(mine, 5), calibration=theirs,
                        diff=None if diff is None else round(diff, 5)))
        ok = ok and diff is not None and abs(diff) <= REPRO_TOL
    ok = ok and len(per) == len(BANDS)
    return dict(ledger_rows=n_ledger, calibration_rows=cal.get('ledger_rows'), calibration_made=cal.get('made'),
                bands=per, tol=REPRO_TOL, ok=bool(ok))


def prepare(stat):
    base, cnt = [], Counter()
    for r in stat:
        sp = r.get('split')
        if sp not in SPLITS:
            cnt['split_other'] += 1
            continue
        ret = fnum(r.get('return_pct'))
        if ret is None:
            cnt['no_return'] += 1
            continue
        if r.get('regime') is None:
            cnt['no_regime'] += 1
            continue
        b = band_of(r.get('score'))
        if b is None:
            cnt['no_band'] += 1
            continue
        x = dict(code=lv.code6(r.get('ticker')), date=str(r.get('date'))[:10], split=sp, ret=ret, net=ret - COST, band=b)
        for c in CATS[1:]:
            x[c] = str(r.get(c))
        for c in CONTS:
            x[c] = fnum(r.get(c))
        base.append(x)
    base.sort(key=lambda x: (x['code'], x['date']))
    kept, last = [], {}
    for x in base:
        prev = last.get(x['code'])
        if prev is not None and lv.too_close([prev], x['date']):
            continue
        last[x['code']] = x['date']
        kept.append(x)
    return base, kept, dict(cnt)


def design(train):
    spec = dict(cats={}, conts={})
    for c in CATS:
        cc = Counter(x[c] for x in train)
        order = sorted(cc, key=lambda v: (-cc[v], v))
        spec['cats'][c] = dict(ref=order[0], levels=order[1:])
    for c in CONTS:
        v = np.array([x[c] for x in train if x[c] is not None], dtype=float)
        miss = any(x[c] is None for x in train)
        if not len(v):           # 학습에 값이 하나도 없으면 그 칸은 상수 0 (빈 값 표시 칸만 남는다)
            spec['conts'][c] = dict(mean=0.0, sd=1.0, missing_col=miss)
            continue
        spec['conts'][c] = dict(mean=float(v.mean()), sd=float(v.std()) or 1.0, missing_col=miss)
    names = ['절편']
    for c in CATS:
        names += [f'{c}={lvl}' for lvl in spec['cats'][c]['levels']]
    for c in CONTS:
        names.append(f'{c}(표준화)')
        if spec['conts'][c]['missing_col']:
            names.append(f'{c}(빈 값)')
    spec['names'] = names
    return spec


def matrix(rows, spec):
    X = np.zeros((len(rows), len(spec['names'])), dtype=float)
    unseen = Counter()
    for i, x in enumerate(rows):
        j = 0
        X[i, j] = 1.0
        j += 1
        for c in CATS:
            cs = spec['cats'][c]
            v = x[c]
            if v in cs['levels']:
                X[i, j + cs['levels'].index(v)] = 1.0
            elif v != cs['ref']:
                unseen[c] += 1
            j += len(cs['levels'])
        for c in CONTS:
            cs = spec['conts'][c]
            v = x[c]
            X[i, j] = 0.0 if v is None else (v - cs['mean']) / cs['sd']
            j += 1
            if cs['missing_col']:
                X[i, j] = 1.0 if v is None else 0.0
                j += 1
    return X, dict(unseen)


def _date_arrays(rows):
    uniq = sorted({x['date'] for x in rows})
    pos = {d: i for i, d in enumerate(uniq)}
    return uniq, np.array([pos[x['date']] for x in rows], dtype=int)


def boot_mean(rows, rng):
    """날짜 군집 부트스트랩 — 평균 · CI95(백분위) · 표준오차. 행이 없으면 None."""
    if not rows:
        return None
    uniq, inv = _date_arrays(rows)
    vals = np.array([x['net'] for x in rows], dtype=float)
    sums = np.bincount(inv, weights=vals, minlength=len(uniq))
    cnts = np.bincount(inv, minlength=len(uniq)).astype(float)
    idx = rng.integers(0, len(uniq), size=(BOOT, len(uniq)))
    bm = sums[idx].sum(1) / cnts[idx].sum(1)
    mean = float(vals.mean())
    se = float(bm.std(ddof=1))
    lo, hi = np.percentile(bm, [2.5, 97.5])
    return dict(n=len(rows), dates=len(uniq), mean=round(mean, 4), ci95=[round(float(lo), 4), round(float(hi), 4)],
                se=round(se, 4), z=(round(mean / se, 3) if se > 0 else None))


def boot_diff(rows, sel, rng):
    """고른 행 − 고르지 않은 행 (같은 날짜 뽑기)."""
    uniq, inv = _date_arrays(rows)
    vals = np.array([x['net'] for x in rows], dtype=float)
    s = np.asarray(sel, dtype=bool)
    D = len(uniq)
    ss = np.bincount(inv[s], weights=vals[s], minlength=D)
    sc = np.bincount(inv[s], minlength=D).astype(float)
    us = np.bincount(inv[~s], weights=vals[~s], minlength=D)
    uc = np.bincount(inv[~s], minlength=D).astype(float)
    if not sc.sum() or not uc.sum():
        return None
    idx = rng.integers(0, D, size=(BOOT, D))
    with np.errstate(invalid='ignore', divide='ignore'):
        b = ss[idx].sum(1) / sc[idx].sum(1) - us[idx].sum(1) / uc[idx].sum(1)
    b = b[np.isfinite(b)]
    point = float(vals[s].mean() - vals[~s].mean())
    lo, hi = np.percentile(b, [2.5, 97.5])
    return dict(diff=round(point, 4), ci95=[round(float(lo), 4), round(float(hi), 4)], boots=int(len(b)))


def _q(a, p):
    a = sorted(a)
    return a[min(len(a) - 1, max(0, int(round(p * (len(a) - 1)))))]


def main():
    res = dict(made=datetime.date.today().isoformat(), prereg='docs/PREREG_R467_CONDITIONAL_EV.md', seed=SEED, boot=BOOT,
               cost_pct=COST, date_floor=DATE_FLOOR)
    if abs(float(verdict_core.COST_PCT) - COST) > 1e-9:
        res['verdict'] = f'중단 — 운영 비용이 {verdict_core.COST_PCT} 로 사전등록(0.41)과 다르다'
        return _write(res)
    rows = load()
    keys = lv.scale_mismatch_keys()
    sc = {}
    stat = list(lv.stat_rows(rows, keys=keys, counter=sc))
    res['stat_excluded'] = sc
    res['scale_keys_read'] = keys is not None
    cal = artifact_io.load_json('calibration.json') or {}
    res['repro'] = repro(stat, len(rows), cal)
    if not res['repro']['ok']:
        res['verdict'] = '중단 — R-재현 미달 (허용 오차를 늘리지 않는다)'
        return _write(res)

    base, kept, drop = prepare(stat)
    res['counts'] = dict(stat_rows=len(stat), dropped=drop, analysed=len(base), spaced=len(kept),
                         by_split={sp: sum(1 for x in kept if x['split'] == sp) for sp in SPLITS})
    rng = np.random.default_rng(SEED)

    # ── 판정 — 학습 구간 OLS 하나 ──
    by = {sp: [x for x in kept if x['split'] == sp] for sp in SPLITS}
    spec = design(by['train'])
    Xtr, _ = matrix(by['train'], spec)
    ytr = np.array([x['net'] for x in by['train']], dtype=float)
    beta, _, rank, _ = np.linalg.lstsq(Xtr, ytr, rcond=None)
    res['model'] = dict(columns=len(spec['names']), rank=int(rank),
                        reference={c: spec['cats'][c]['ref'] for c in CATS},
                        coef={n: round(float(b), 4) for n, b in zip(spec['names'], beta)})
    model = {}
    for sp in SPLITS:
        X, unseen = matrix(by[sp], spec)
        pred = X @ beta
        sel = pred > 0
        chosen = [x for x, s in zip(by[sp], sel) if s]
        info = dict(n=len(by[sp]), selected=int(sel.sum()),
                    selected_share=round(float(sel.mean()) * 100, 2) if len(sel) else None,
                    unseen=unseen, pred_mean=round(float(pred.mean()), 4) if len(pred) else None,
                    pred_max=round(float(pred.max()), 4) if len(pred) else None)
        info['all'] = boot_mean(by[sp], rng)
        info['chosen'] = boot_mean(chosen, rng)
        if chosen:
            nets = [x['net'] for x in chosen]
            info['chosen_median'] = round(_q(nets, 0.5), 3)
            info['chosen_pos_pct'] = round(100.0 * sum(1 for v in nets if v > 0) / len(nets), 1)
            info['chosen_p05'] = round(_q(nets, 0.05), 2)
            info['diff'] = boot_diff(by[sp], sel, rng)
        model[sp] = info
    res['selection'] = model

    v, b = model['valid'], model['blind']
    if not v['selected'] or not b['selected']:
        res['R0'] = dict(ok=False, reason='valid 또는 blind 에서 고른 행이 없다')
        res['verdict'] = '(다) 현행 유지 — 모형이 valid·blind 에서 비용을 넘는 자리를 고르지 못했다'
    else:
        dv, db = v['chosen']['dates'], b['chosen']['dates']
        res['R0'] = dict(dates=dict(valid=dv, blind=db), floor=DATE_FLOOR, ok=dv >= DATE_FLOOR and db >= DATE_FLOOR)
        if not res['R0']['ok']:
            res['verdict'] = '미측정 — R0(고른 행의 날짜 하한) 미달'
        else:
            lv_ok = v['chosen']['ci95'][0] > 0
            lb_ok = b['chosen']['ci95'][0] > 0
            res['R1'] = dict(valid=lv_ok, blind=lb_ok)
            if lv_ok and lb_ok:
                res['verdict'] = '(가) 후보 — 규칙은 안 바꾼다(11-16 동결 · 전방 확인 · 사람이 정한다)'
            elif lv_ok and b['chosen']['mean'] > 0:
                res['verdict'] = '(나) 후보 유지 · 현행 유지 — 블라인드만 CI 가 0 포함'
            else:
                res['verdict'] = '(다) 현행 유지'

    # ── 설명용 지도 — 재료 하나씩 (판정에 안 쓴다) ──
    cells = []
    for c in CATS:
        for lvl in sorted({x[c] for x in base}):
            cells.append((c, lvl, (lambda x, c=c, lvl=lvl: x[c] == lvl)))
    for c in CONTS:
        med = float(np.median([x[c] for x in by['train'] if x[c] is not None]))
        cells.append((c, f'중앙값 이하 (≤ {med:.4g})', (lambda x, c=c, m=med: x[c] is not None and x[c] <= m)))
        cells.append((c, f'중앙값 초과 (> {med:.4g})', (lambda x, c=c, m=med: x[c] is not None and x[c] > m)))
        if any(x[c] is None for x in base):
            cells.append((c, '빈 값', (lambda x, c=c: x[c] is None)))
    res['map_cells_defined'] = len(cells)
    res['map_cells_prereg'] = MAP_CELLS
    res['map_z'] = Z_MAP
    out = []
    for c, lvl, fn in cells:
        row = dict(var=c, level=lvl)
        all3 = True
        for sp in SPLITS:
            sub = [x for x in by[sp] if fn(x)]
            st = boot_mean(sub, rng)
            if st is None or st['dates'] < DATE_FLOOR:
                row[sp] = dict(n=len(sub), dates=(st or {}).get('dates', 0), mean=(st or {}).get('mean'), status='미측정')
                all3 = False
            else:
                row[sp] = st
                all3 = all3 and st['z'] is not None and st['z'] >= Z_MAP
        row['all_three_bonferroni'] = all3
        out.append(row)
    res['map'] = out
    res['map_passing'] = [f"{r['var']}={r['level']}" for r in out if r['all_three_bonferroni']]
    return _write(res)


def _write(res):
    with io.open(OUT, 'w', encoding='utf-8', newline='\n') as f:
        f.write(json.dumps(res, ensure_ascii=False, indent=1) + '\n')
    sys.stdout.reconfigure(encoding='utf-8')
    print('판정:', res.get('verdict'))
    return res


if __name__ == '__main__':
    main()
