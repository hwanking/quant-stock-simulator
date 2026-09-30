# -*- coding: utf-8 -*-
"""
라운드 397 — 계층 보정 확률 표를 오늘 원장으로 다시 적합하면 블라인드에서 더 맞는가.

사전등록: docs/PREREG_R397_HIER_REFIT.md (측정 전 커밋 83cef75). 기준은 그 문서 §3 그대로.

- 옛 표: 운영 data/hier_prob_tables.json (2026-08-09).
- 새 표: scripts/gen_hier_tables.py --out 으로 오늘 원장에서 만든 것 (인자로 받는다).
- 표본: 오늘 원장 블라인드 · 판정 완료 · 통계 행(ledger_view.stat_rows). 블라인드는 이 비교에 한 번 쓴다.
- 칸 열쇠·예측·지표는 R59 측정 스크립트(hier_prob_lab)의 함수를 **불러서** 쓴다(R192 · 베끼지 않는다).
- 재현 확인: 블라인드 200행에서 옛 표 확률이 운영 함수 case_layers.blended_prob 와 1e-9 안에서 같아야 한다.
  아니면 측정을 중단한다(판정을 내지 않는다).

실행: C:/Python314/python.exe scripts/hier_refit_r397.py _probe/r397_hier_new.json
"""
import glob
import json
import os
import random
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
P = os.path.join(PROJ, '.portfolio')

import hier_prob_lab as H                                       # noqa: E402
import ledger_view as lv                                        # noqa: E402
import case_layers as cl                                        # noqa: E402
import bitemporal_engine as be                                  # noqa: E402

DATE_FLOOR = 30          # R0 — R84·R45 하한 (사전등록 §3)
SEED = 397
N_BOOT = 2000
N_REPRO = 200
TOL = 1e-9


def load_table(path):
    with open(path, encoding='utf-8') as f:
        doc = json.load(f)
    tab = {}
    for k, v in (doc.get('cells') or {}).items():
        layer, rest = k.split('|', 1)
        tab[(layer, rest)] = v
    ter = doc.get('vol_terciles') or None
    ter = tuple(ter) if ter and len(ter) == 2 else None
    return doc, tab, ter, float(doc.get('m') or 100)


def row_sector(r):
    """새 생성기와 같은 규칙 — 원장 행의 업종 먼저(업종 아닌 라벨은 엔진의 판별로 거름)."""
    s = str(r.get('sector') or '').strip()
    if not s or s.startswith(be.SECTOR_LABEL_PREFIX) or s in be.SECTOR_NON_LABELS:
        return None
    return s


def blind_rows(states):
    patch = {}
    for path in sorted(glob.glob(os.path.join(P, 'subscore_patch*.jsonl'))):
        with open(path, encoding='utf-8') as f:
            for ln in f:
                try:
                    q = json.loads(ln)
                    patch[(q['ticker'], q['date'])] = q.get('sector')
                except Exception:                              # noqa: BLE001
                    continue
    elig = []
    read = 0
    with open(os.path.join(P, 'virtual_graded.jsonl'), encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:                                  # noqa: BLE001
                continue
            read += 1
            if r.get('split') != 'blind' or r.get('outcome') == 'OPEN':
                continue
            if not H.band_of(float(r.get('score') or 0)):
                continue
            elig.append(r)
    cnt = {}
    out = []
    for r in lv.stat_rows(elig, lv.scale_mismatch_keys(), cnt):
        k = (str(r['ticker']), str(r['date'])[:10])
        r = dict(r)
        r['_band'] = H.band_of(float(r.get('score') or 0))
        r['_st'] = states.get(k[1])
        r['_sector'] = row_sector(r) or patch.get(k)
        out.append(r)
    print(f'원장 읽은 행 {read:,} · 블라인드 판정 완료 {len(elig):,} · 통계 행 {len(out):,} '
          f'(축척 어긋남 {cnt.get("scale", 0):,} · 복사본 {cnt.get("dup", 0):,} 뺌)')
    return out


def layers_used(r, tab, ter):
    return sum(1 for lk in H.cells_of(r, ter) if tab.get(lk) and tab[lk][0] > 0)


def main(new_path):
    states = H.build_states()
    old_doc, old_tab, old_ter, old_m = load_table(os.path.join(PROJ, 'data', 'hier_prob_tables.json'))
    new_doc, new_tab, new_ter, new_m = load_table(new_path)
    print(f"옛 표: made {old_doc.get('made')} · 칸 {len(old_tab):,} · m {old_m:g} · 변동성 3분위 {old_ter}")
    print(f"새 표: made {new_doc.get('made')} · 칸 {len(new_tab):,} · m {new_m:g} · 변동성 3분위 {new_ter}")
    if old_m != new_m:
        raise SystemExit('m 이 다르다 — 사전등록 §1 위반 · 측정 중단')

    rows = blind_rows(states)
    dates = sorted({str(r['date'])[:10] for r in rows})
    print(f'R0 — 블라인드 고유 기준일 {len(dates)} (하한 {DATE_FLOOR})')
    if len(dates) < DATE_FLOOR:
        print('R0 미달 — 측정하지 않는다 (미측정)')
        return

    # ── 재현 확인 (판정 전) ──────────────────────────────────────────────────────────────────
    rng = random.Random(SEED)
    sample = rng.sample(rows, min(N_REPRO, len(rows)))
    bad = []
    for r in sample:
        fs = dict(range_position_pct=r.get('range_pos'), bb_position_pct=r.get('bb_pos'),
                  m10_disparity=(1 if r.get('m10_above') else -1),
                  demark_state=r.get('demark_state'), vol_20=r.get('vol20'), market=r.get('market'))
        got = cl.blended_prob(float(r.get('score') or 0), sector=r['_sector'],
                              regime_code=r['_st'], fs=fs)
        mine = H.predict(r, old_tab, old_ter, old_m)
        g = None if got is None else got['p']
        if (g is None) != (mine is None) or (g is not None and abs(g - mine) > TOL):
            bad.append((r.get('ticker'), str(r.get('date'))[:10], g, mine,
                        r.get('range_pos'), r.get('bb_pos')))
    print(f'재현 확인 — 블라인드 {len(sample)}행 중 운영 함수와 다른 행 {len(bad)}')
    if bad:
        for b in bad[:10]:
            print('   다름:', b)
        print('재현 실패 — 측정 중단 (판정을 내지 않는다)')
        return

    # ── 예측 ────────────────────────────────────────────────────────────────────────────────
    po, pn, ys, keep = [], [], [], []
    none_old = none_new = 0
    for r in rows:
        a = H.predict(r, old_tab, old_ter, old_m)
        b = H.predict(r, new_tab, new_ter, new_m)
        if a is None:
            none_old += 1
        if b is None:
            none_new += 1
        if a is None or b is None:
            continue
        po.append(a)
        pn.append(b)
        ys.append(1.0 if r.get('success') else 0.0)
        keep.append(r)
    print(f'확률을 못 낸 행 — 옛 표 {none_old} · 새 표 {none_new} (둘 다 낸 {len(keep):,}행으로 견준다)')
    print(f'실측 적중 {np.mean(ys) * 100:.2f}% · 평균 예측 옛 {np.mean(po) * 100:.2f}% · 새 {np.mean(pn) * 100:.2f}%')

    print('\n[판정 지표 — 블라인드 전체]')
    so = H.score(po, ys, '옛 표 (2026-08-09)')
    sn = H.score(pn, ys, f"새 표 ({new_doc.get('made')})")
    ok = (sn['brier'] < so['brier'], sn['logloss'] < so['logloss'], sn['calib_dev'] <= so['calib_dev'])
    verdict = '(가) 교체 제안' if all(ok) else '(다) 현행 유지'
    print(f'  Brier 낮음 {ok[0]} · log loss 낮음 {ok[1]} · 보정이탈 ≤ {ok[2]} → {verdict}')

    # ── 곁들여 적는 것 (판정에 안 씀) ────────────────────────────────────────────────────────
    po_a, pn_a, y_a = np.array(po), np.array(pn), np.array(ys)
    d_row = (pn_a - y_a) ** 2 - (po_a - y_a) ** 2
    dkey = np.array([str(r['date'])[:10] for r in keep])
    uniq = sorted(set(dkey.tolist()))
    idx = {d: i for i, d in enumerate(uniq)}
    di = np.array([idx[d] for d in dkey])
    S = np.bincount(di, weights=d_row, minlength=len(uniq))
    C = np.bincount(di, minlength=len(uniq)).astype(float)
    brng = np.random.default_rng(SEED)
    pick = brng.integers(0, len(uniq), size=(N_BOOT, len(uniq)))
    boot = S[pick].sum(1) / C[pick].sum(1)
    lo, hi = np.percentile(boot, [2.5, 97.5])
    print(f'\n[곁들여] Δ Brier(새 − 옛) {d_row.mean():+.5f} · 날짜 군집 부트 95% [{lo:+.5f}, {hi:+.5f}] '
          f'(날짜 {len(uniq)} · {N_BOOT}회 · 시드 {SEED})')

    sub = [i for i, r in enumerate(keep) if float(r.get('score') or 0) >= 60]
    if sub:
        print(f'\n[곁들여] 60점+ 부분집합 n {len(sub):,} · 날짜 {len({dkey[i] for i in sub})} · '
              f'실측 {y_a[sub].mean() * 100:.2f}% · 평균 예측 옛 {po_a[sub].mean() * 100:.2f}% · 새 {pn_a[sub].mean() * 100:.2f}%')
        H.score(po_a[sub], y_a[sub], '옛 표 · 60점+')
        H.score(pn_a[sub], y_a[sub], '새 표 · 60점+')

    print('\n[곁들여] 국면별 (원장 행의 regime)')
    for rg in ('BULL', 'SIDEWAYS', 'BEAR'):
        ii = [i for i, r in enumerate(keep) if r.get('regime') == rg]
        if not ii:
            print(f'  {rg}: 행 없음')
            continue
        bo = float(np.mean((po_a[ii] - y_a[ii]) ** 2))
        bn = float(np.mean((pn_a[ii] - y_a[ii]) ** 2))
        print(f'  {rg:8s} n {len(ii):6,} · 날짜 {len({dkey[i] for i in ii}):3d} · 실측 {y_a[ii].mean() * 100:5.1f}% · '
              f'예측 옛 {po_a[ii].mean() * 100:5.1f}% 새 {pn_a[ii].mean() * 100:5.1f}% · Brier 옛 {bo:.4f} 새 {bn:.4f}')

    lu_o = [layers_used(r, old_tab, old_ter) for r in keep]
    lu_n = [layers_used(r, new_tab, new_ter) for r in keep]
    print(f'\n[곁들여] 행마다 쓰인 층 수 — 옛 평균 {np.mean(lu_o):.2f} · 새 평균 {np.mean(lu_n):.2f}')
    for k in range(1, 6):
        print(f'  {k}층: 옛 {sum(1 for x in lu_o if x == k):6,} · 새 {sum(1 for x in lu_n if x == k):6,}')

    out = dict(round=397, made_old=old_doc.get('made'), made_new=new_doc.get('made'),
               cells_old=len(old_tab), cells_new=len(new_tab), rows=len(keep), dates=len(uniq),
               hit=float(y_a.mean()), old=so, new=sn, gates=list(ok), verdict=verdict,
               d_brier=float(d_row.mean()), d_brier_ci=[float(lo), float(hi)])
    with open(os.path.join(PROJ, '_probe', 'r397_result.json'), 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('\n결과 → _probe/r397_result.json')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        raise SystemExit('새 표 경로를 인자로 준다 — 예: _probe/r397_hier_new.json')
    p = sys.argv[1]
    main(p if os.path.isabs(p) else os.path.join(PROJ, p))
