# -*- coding: utf-8 -*-
"""
라운드 54 — 메타 라벨 게이트 학습·평가.

사전등록: docs/PREREG_R54_META_LABEL.md (이 파일보다 먼저 저장됨).
학습 train · 선택 valid. blind 는 --blind-shot 플래그로만, 게이트 전부
통과한 챔피언 1개가 1회만 본다.

    C:/Python314/python.exe scripts/meta_label_lab.py
"""
import io
import json
import math
import os
import sys
import warnings
from collections import Counter

import numpy as np

warnings.filterwarnings('ignore')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(PROJ, '.portfolio')

THR = 58.0
COST = 0.36                    # 왕복 비용 %p
PURGE_FROM = '2025-06-01'      # train 말단 퍼지 (20봉 결과창이 valid 에 걸림)
MIN_COVER = 0.20               # 사전등록 §5-3
MIN_MONTHLY = 8.0
MIN_LIFT = 3.0                 # %p


def wilson_low(k, n, z=1.96):
    if n == 0:
        return 0.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - m) / d * 100.0


def load_rows():
    rows = []
    with open(os.path.join(P, 'virtual_graded.jsonl'), encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:                                  # noqa: BLE001
                continue
            if float(r.get('score') or 0) < THR:
                continue
            if r.get('outcome') == 'OPEN':
                continue
            rows.append(r)
    patch = {}
    import glob
    for path in sorted(glob.glob(os.path.join(P, 'subscore_patch*.jsonl'))):
        with open(path, encoding='utf-8') as f:
            for ln in f:
                try:
                    q = json.loads(ln)
                    patch[(q['ticker'], q['date'])] = q
                except Exception:                              # noqa: BLE001
                    continue
    for r in rows:
        r.update({k: v for k, v in
                  patch.get((str(r['ticker']), str(r['date'])[:10]), {}).items()
                  if k not in ('ticker', 'date')})
    return rows


NUM = ('score', 'rsi', 'bb_pos', 'vol20', 'range_pos', 'demark_bull',
       'demark_bear', 'eff_sample', 'win_rate', 'net_expected',
       'q_stock_quality', 'q_trading_timing', 'q_risk_safety',
       'q_opportunity', 'q_execution', 'q_confidence', 'q_strategy_quality',
       'news_risk_count', 'news_fresh_count')
CAT = ('entry_zone', 'demark_state', 'regime', 'market', 'asset_type',
       'sector')


def featurize(rows):
    cat_vals = {c: [v for v, _ in
                    Counter(str(r.get(c)) for r in rows).most_common(12)]
                for c in CAT}
    names, X = [], []
    med = {k: float(np.nanmedian([float(r[k]) for r in rows
                                  if isinstance(r.get(k), (int, float))]
                                 or [0.0])) for k in NUM}
    for k in NUM:
        names += [k, k + '_isna']
    names += ['m10_above', 'news_available']
    for c in CAT:
        names += [f'{c}={v}' for v in cat_vals[c]]
    for r in rows:
        v = []
        for k in NUM:
            x = r.get(k)
            isna = not isinstance(x, (int, float))
            v += [med[k] if isna else float(x), 1.0 if isna else 0.0]
        v.append(1.0 if r.get('m10_above') else 0.0)
        v.append(1.0 if r.get('news_available') else 0.0)
        for c in CAT:
            s = str(r.get(c))
            v += [1.0 if s == vv else 0.0 for vv in cat_vals[c]]
        X.append(v)
    return np.array(X, dtype=float), names


def metrics(sub, base_n, months):
    n = len(sub)
    if n == 0:
        return dict(n=0)
    hit = sum(1 for r in sub if r['success']) / n * 100
    net = [float(r['return_pct']) - COST for r in sub]
    ev = float(np.mean(net))
    pos = sum(x for x in net if x > 0)
    neg = -sum(x for x in net if x < 0)
    return dict(n=n, cover=n / base_n * 100, hit=round(hit, 1),
                wilson=round(wilson_low(sum(1 for r in sub if r['success']),
                                        n), 1),
                ev=round(ev, 3),
                pf=round(pos / neg, 2) if neg > 0 else float('inf'),
                monthly=round(n / max(1, months), 1))


def main():
    rows = load_rows()
    tr = [r for r in rows if r['split'] == 'train'
          and str(r['date'])[:10] < PURGE_FROM]
    va = [r for r in rows if r['split'] == 'valid']
    purged = sum(1 for r in rows if r['split'] == 'train') - len(tr)
    months = len({str(r['date'])[:7] for r in va})
    print(f'매수권 판정완료 {len(rows):,} · train {len(tr):,} '
          f'(퍼지 {purged:,}) · valid {len(va):,} · valid {months}개월')
    q_cov = sum(1 for r in tr + va if r.get('q_stock_quality') is not None)
    print(f'하위점수 조인율 {q_cov / len(tr + va) * 100:.1f}%')

    base = metrics(va, len(va), months)
    print(f"\n기준선(valid 매수권 전체): 적중 {base['hit']}% · "
          f"순EV {base['ev']:+.3f} · PF {base['pf']} · n {base['n']:,}")

    Xall, names = featurize(tr + va)
    Xtr, Xva = Xall[:len(tr)], Xall[len(tr):]
    ytr = np.array([1.0 if r['success'] else 0.0 for r in tr])

    from lightgbm import LGBMClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from xgboost import XGBClassifier

    sc = StandardScaler().fit(Xtr)
    configs = []
    for C in (0.1, 1.0):
        configs.append((f'logit_C{C}',
                        LogisticRegression(C=C, max_iter=2000), True))
    for d in (3, 5):
        configs.append((f'xgb_d{d}', XGBClassifier(
            max_depth=d, learning_rate=0.05, n_estimators=400,
            subsample=0.8, colsample_bytree=0.8, eval_metric='logloss',
            verbosity=0, n_jobs=8), False))
        configs.append((f'lgbm_d{d}', LGBMClassifier(
            max_depth=d, learning_rate=0.05, n_estimators=400,
            subsample=0.8, colsample_bytree=0.8, verbose=-1, n_jobs=8),
            False))

    results = []
    for name, mdl, scale in configs:
        mdl.fit(sc.transform(Xtr) if scale else Xtr, ytr)
        p = mdl.predict_proba(sc.transform(Xva) if scale else Xva)[:, 1]
        best = None
        for q in np.arange(0.20, 0.96, 0.05):     # 문턱 = valid 확률 분위
            thr = float(np.quantile(p, q))
            sub = [r for r, pi in zip(va, p) if pi >= thr]
            m = metrics(sub, len(va), months)
            if m['n'] == 0 or m['cover'] < MIN_COVER * 100 \
                    or m['monthly'] < MIN_MONTHLY:
                continue
            if best is None or m['ev'] > best[1]['ev']:
                best = (thr, m)
        if best:
            results.append((name, mdl, scale, best[0], best[1]))
            m = best[1]
            print(f"  {name:10s} 커버 {m['cover']:5.1f}% · 적중 {m['hit']}% "
                  f"(W하한 {m['wilson']}) · 순EV {m['ev']:+.3f} · "
                  f"PF {m['pf']} · 월 {m['monthly']}건")

    if not results:
        print('\n제약(커버리지·월신호)을 만족하는 구성이 없다 — 기각.')
        return
    name, mdl, scale, thr, m = max(results, key=lambda x: x[4]['ev'])
    print(f'\n챔피언(valid 순EV 기준): {name}')

    gate = {
        '순EV > 0': m['ev'] > 0,
        f"리프트 ≥ +{MIN_LIFT}%p": m['hit'] - base['hit'] >= MIN_LIFT,
        'Wilson하한 > 기준선': m['wilson'] > base['hit'],
        f'커버 ≥ {MIN_COVER * 100:.0f}%': m['cover'] >= MIN_COVER * 100,
        f'월 ≥ {MIN_MONTHLY:.0f}건': m['monthly'] >= MIN_MONTHLY,
        'PF > 1': m['pf'] > 1.0,
    }
    print('\n채택 게이트 (사전등록 §5):')
    ok_all = True
    for k, ok in gate.items():
        ok_all &= ok
        print(f"  [{'통과' if ok else '미달'}] {k}")
    print(f"\n판정: {'전부 통과 — blind 1회 진행 자격' if ok_all else '기각 — 현행 유지'}")

    # 부산물 — R50 분해: 피처 중요도
    print('\n피처 중요도 상위 15 (챔피언):')
    if hasattr(mdl, 'feature_importances_'):
        imp = mdl.feature_importances_
    else:
        imp = np.abs(mdl.coef_[0])
    for i in np.argsort(imp)[::-1][:15]:
        print(f'  {names[i]:34s}{imp[i]:.4f}')

    out = dict(champion=name, threshold=thr, valid=m, base=base,
               gate={k: bool(v) for k, v in gate.items()},
               gate_pass=bool(ok_all))
    with open(os.path.join(P, 'meta_label_r54.json'), 'w',
              encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('\n저장: .portfolio/meta_label_r54.json (blind 미접촉)')


if __name__ == '__main__':
    main()
