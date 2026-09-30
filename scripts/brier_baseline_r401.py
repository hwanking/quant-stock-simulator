# -*- coding: utf-8 -*-
"""
라운드 401 — 외부 검토(2026-10-01) §9: 계층 확률 표의 Brier 를 **단순 기준선**과도 견준다.

라운드 397 은 옛 표(0.2416)와 새 표(0.2432)만 견줬다. 검토자가 짚은 대로, 둘 다 **아무것도 모르는
예측**보다 나은지를 먼저 봐야 한다. 기준선은 전부 **블라인드 밖**에서만 정한다(평가 구간의 발생률로
맞추면 누출이다):
  ① 상수(train+valid) — 운영 표를 적합한 **같은 자료**의 적중률 하나를 모든 행에 낸다 · 판정용 비교
  ①' 상수(train) — 첫 판이 쓴 것(검토자의 '학습자료'를 train 으로 좁게 읽었다) · 같이 적는다
  ② 점수대 — train 에서 점수대(`hier_prob_lab.band_of` 그대로 · 새 칸 없음)별 적중률

표본은 라운드 397 과 **같은 행·같은 예측**이다 — `hier_refit_r397` 의 함수를 **불러서** 쓴다(R192).
판정은 내리지 않는다 — 이 비교는 사전등록 밖의 곁들임이고, 라운드 397 의 판정((다) 현행 유지)을 바꾸지 않는다.
블라인드는 이미 라운드 397 에 한 번 쓰였다 — 여기서 새 규칙을 고르지 않는다.

실행: C:/Python314/python.exe scripts/brier_baseline_r401.py _probe/r397_hier_new.json
"""
import json
import os
import sys

import numpy as np

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:          # noqa: BLE001
    pass
HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
sys.path.insert(0, PROJ)
sys.path.insert(0, HERE)

import hier_prob_lab as H                                       # noqa: E402
import hier_refit_r397 as R                                     # noqa: E402
import ledger_view as lv                                        # noqa: E402

SEED = 401
N_BOOT = 2000


LEDGER_ROWS = {'n': 0}


def train_rates(splits=('train',)):
    """판정 완료 · 점수대 안 · 통계 행 — 라운드 397 의 블라인드 표본과 같은 거름을 개발 구간에 건다.

    운영 표(gen_hier_tables)는 **train+valid** 로 적합했다(블라인드 미접촉). 그래서 공정한 상수는 같은 자료를
    본 train+valid 적중률이다 — 첫 판은 train 만 썼다(검토자의 '학습자료에서만'을 train 으로 좁게 읽었다).
    둘 다 낸다 — 표가 본 자료와 같은 자료의 상수가 판정용 비교다."""
    elig = []
    with open(os.path.join(R.P, 'virtual_graded.jsonl'), encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:                                  # noqa: BLE001
                continue
            if splits == ('train',):
                LEDGER_ROWS['n'] += 1
            if r.get('split') not in splits or r.get('outcome') == 'OPEN':
                continue
            if not H.band_of(float(r.get('score') or 0)):
                continue
            elig.append(r)
    # stat_rows 는 생성기다 — 두 번 돌면 두 번째가 빈다(첫 판이 그렇게 점수대 표를 비워 측정이 멈췄다)
    rows = list(lv.stat_rows(elig, lv.scale_mismatch_keys(), {}))
    ys = [1.0 if r.get('success') else 0.0 for r in rows]
    by_band = {}
    for r, y in zip(rows, ys):
        b = H.band_of(float(r.get('score') or 0))
        by_band.setdefault(b, []).append(y)
    return (float(np.mean(ys)), len(ys),
            {b: (float(np.mean(v)), len(v)) for b, v in by_band.items()})


def brier(p, y):
    p = np.asarray(p, float)
    y = np.asarray(y, float)
    return float(np.mean((p - y) ** 2))


def boot_ci(d_row, dkey):
    uniq = sorted(set(dkey))
    idx = {d: i for i, d in enumerate(uniq)}
    di = np.array([idx[d] for d in dkey])
    S = np.bincount(di, weights=d_row, minlength=len(uniq))
    C = np.bincount(di, minlength=len(uniq)).astype(float)
    rng = np.random.default_rng(SEED)
    pick = rng.integers(0, len(uniq), size=(N_BOOT, len(uniq)))
    boot = S[pick].sum(1) / C[pick].sum(1)
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return float(lo), float(hi), len(uniq)


def main(new_path):
    q, n_tr, bands = train_rates()
    print(f'train 판정 완료 통계 행 {n_tr:,} · 적중 {q * 100:.2f}% (상수 기준선)')
    qd, n_dev, _ = train_rates(('train', 'valid'))
    print(f'train+valid(운영 표가 본 자료) 판정 완료 통계 행 {n_dev:,} · 적중 {qd * 100:.2f}% (공정한 상수)')
    for b in sorted(bands, key=str):
        print(f'  점수대 {b}: train 적중 {bands[b][0] * 100:.2f}% · n {bands[b][1]:,}')

    states = H.build_states()
    old_doc, old_tab, old_ter, old_m = R.load_table(os.path.join(PROJ, 'data', 'hier_prob_tables.json'))
    _, new_tab, new_ter, new_m = R.load_table(new_path)
    rows = R.blind_rows(states)
    po, pn, pc, pd_, pb, ys, dkey = [], [], [], [], [], [], []
    for r in rows:
        a = H.predict(r, old_tab, old_ter, old_m)
        b = H.predict(r, new_tab, new_ter, new_m)
        if a is None or b is None:          # 라운드 397 과 같은 행만(둘 다 낸 행)
            continue
        band = r['_band']
        if band not in bands:
            print('train 에 없는 점수대 — 측정 중단:', band)
            return
        po.append(a)
        pn.append(b)
        pc.append(q)
        pd_.append(qd)
        pb.append(bands[band][0])
        ys.append(1.0 if r.get('success') else 0.0)
        dkey.append(str(r['date'])[:10])
    ys = np.array(ys)
    print(f'\n블라인드 견줄 행 {len(ys):,} (라운드 397 과 같은 거름) · 실측 적중 {ys.mean() * 100:.2f}%')
    res = {}
    for name, p in (('옛 표', po), ('새 표', pn), ('상수(train)', pc), ('상수(train+valid)', pd_),
                    ('점수대(train)', pb)):
        res[name] = brier(p, ys)
        print(f'  Brier {name:16s} {res[name]:.5f} · 평균 예측 {np.mean(p) * 100:.2f}%')
    for base_name, base_p in (('상수(train)', pc), ('상수(train+valid)', pd_)):
        for name, p in (('옛 표', po), ('새 표', pn), ('점수대(train)', pb)):
            d = (np.asarray(p) - ys) ** 2 - (np.asarray(base_p) - ys) ** 2
            lo, hi, nd = boot_ci(d, dkey)
            print(f'  Δ Brier({name} − {base_name}) {d.mean():+.5f} · 날짜 군집 부트 95% [{lo:+.5f}, {hi:+.5f}] '
                  f'(날짜 {nd})')
            res[f'd_{name}|{base_name}'] = [float(d.mean()), lo, hi]
    out = dict(round=401, rows=int(len(ys)), dates=len(set(dkey)), train_q=q, train_n=n_tr,
               dev_q=qd, dev_n=n_dev, blind_hit=float(ys.mean()), brier=res,
               note='사전등록 밖의 곁들임 · 판정에 안 씀 · 라운드 397 판정 불변')
    with open(os.path.join(PROJ, '_probe', 'r401_brier_baseline.json'), 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('\n결과 → _probe/r401_brier_baseline.json')
    # 화면이 읽는 판 — 운영 표(옛 표)와 **그 표가 본 자료(train+valid)의 상수**. 어느 표와 견줬는지(table_made)를
    #   싣는다 — 표가 바뀌면 화면이 이 문장을 안 낸다(case_layers.baseline_note · 낡은 비교를 지금 표의 성적처럼
    #   말하지 않는다).
    import datetime as _dt
    d_old = res['d_옛 표|상수(train+valid)']
    shown = dict(made=_dt.date.today().isoformat(), ledger_rows=LEDGER_ROWS['n'],
                 table_made=old_doc.get('made'), rows=int(len(ys)), dates=len(set(dkey)),
                 train_q=round(qd, 5), const_basis='train+valid (운영 표가 적합한 자료)',
                 blind_hit=round(float(ys.mean()), 5),
                 brier_table=round(res['옛 표'], 5), brier_const=round(res['상수(train+valid)'], 5),
                 d=round(d_old[0], 5), d_lo=round(d_old[1], 5), d_hi=round(d_old[2], 5),
                 boot=N_BOOT, seed=SEED, source='scripts/brier_baseline_r401.py')
    with open(os.path.join(PROJ, 'data', 'hier_prob_baseline.json'), 'w', encoding='utf-8') as f:
        json.dump(shown, f, ensure_ascii=False, indent=1)
    print('화면용 → data/hier_prob_baseline.json')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        raise SystemExit('새 표 경로를 인자로 준다 — 예: _probe/r397_hier_new.json')
    p = sys.argv[1]
    main(p if os.path.isabs(p) else os.path.join(PROJ, p))
