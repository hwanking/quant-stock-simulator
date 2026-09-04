# -*- coding: utf-8 -*-
"""라운드 224 — 사전등록 `docs/PREREG_R224_AVG_DOWN.md` 의 R2 를 잰다.

물음: 원장 매수권(58+) 케이스에서 '직전 관측 대비 하락 중'(A) 이 '아님'(B) 보다
**세 구간 모두** 나쁜가 — 25봉 간격 부분집합(R217) · 날짜 군집 부트스트랩
(R208·R215 잣대 · 시드 224). 새 숫자 없음.

  재현 자기검사: 부분집합 크기 = R217 발표값 122,554. 다르면 중단.

실행: C:/Python314/python.exe scripts/avg_down_r224.py
산출: data/avg_down_r224.json
"""
import io
import json
import os
import random
import statistics
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:                                              # noqa: BLE001
    pass
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
LED = os.path.join(PROJ, '.portfolio', 'virtual_graded.jsonl')
OUT = os.path.join(PROJ, 'data', 'avg_down_r224.json')

BUY = 58.0                      # R216 '매수권 58+' 재사용
N_BOOT = 2000                   # R208·R215 재사용
SEED = 224
SPACED_PUBLISHED = 122554       # R217 발표값 — 재현 자기검사
SPLITS = ('train', 'valid', 'blind')


def _wilson_low(k, n, z=1.96):
    if not n:
        return None
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5
    return round((c - r) / d * 100.0, 1)


def _pct(xs):
    return round(100.0 * sum(xs) / len(xs), 2) if xs else None


def _mean(xs):
    return round(sum(xs) / len(xs), 3) if xs else None


def _boot_diff(by_date, key, rng):
    """by_date: {date: {'A': [..], 'B': [..]}} · key 'hit'|'ret' → CI95 of mean(A)-mean(B)."""
    dates = sorted(by_date)
    if not dates:
        return None
    diffs = []
    for _ in range(N_BOOT):
        a, b = [], []
        for _k in range(len(dates)):
            d = by_date[dates[rng.randrange(len(dates))]]
            a.extend(d['A'][key])
            b.extend(d['B'][key])
        if a and b:
            diffs.append(sum(a) / len(a) - sum(b) / len(b))
    if len(diffs) < N_BOOT // 2:
        return None
    diffs.sort()
    lo = diffs[int(0.025 * len(diffs))]
    hi = diffs[int(0.975 * len(diffs)) - 1]
    scale = 100.0 if key == 'hit' else 1.0
    return [round(lo * scale, 2), round(hi * scale, 2), len(diffs)]


def main():
    import pandas as pd
    import ledger_view as lv
    rows = []
    n_rows = 0
    for line in io.open(LED, encoding='utf-8'):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:                                      # noqa: BLE001
            continue
        n_rows += 1
        rows.append((str(r.get('ticker')), str(r.get('date'))[:10], r.get('price'),
                     r.get('score'), r.get('success'), r.get('return_pct'),
                     str(r.get('split') or ''), r.get('horizon_days')))
    df = pd.DataFrame(rows, columns=['ticker', 'date', 'price', 'score', 'success',
                                     'return_pct', 'split', 'horizon_days'])
    mask = lv.spaced_mask(df)
    n_spaced = int(mask.sum())
    horizons = sorted(set(int(h) for h in df['horizon_days'].dropna().unique()))
    out = {'made': '2026-09-04', 'prereg': 'docs/PREREG_R224_AVG_DOWN.md',
           'ledger_rows': n_rows, 'spaced_rows': n_spaced,
           'spaced_published_r217': SPACED_PUBLISHED, 'horizon_days_seen': horizons,
           'buy_band': BUY, 'n_boot': N_BOOT, 'seed': SEED}
    if n_spaced != SPACED_PUBLISHED:
        out['abort'] = (f'재현 실패: 부분집합 {n_spaced} != R217 발표값 {SPACED_PUBLISHED} — '
                        f'측정 중단 (사전등록 §3)')
        with open(OUT, 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print(out['abort'])
        return 2
    sp = df[mask].sort_values(['ticker', 'date']).reset_index(drop=True)
    sp['prev_price'] = sp.groupby('ticker')['price'].shift(1)
    sp['prev_date'] = sp.groupby('ticker')['date'].shift(1)
    has_prev = sp['prev_price'].notna() & sp['price'].notna()
    gaps = (pd.to_datetime(sp.loc[has_prev, 'date']) - pd.to_datetime(sp.loc[has_prev, 'prev_date'])).dt.days
    out['pairs'] = int(has_prev.sum())
    out['gap_days'] = {'median': float(gaps.median()), 'q25': float(gaps.quantile(0.25)),
                       'q75': float(gaps.quantile(0.75))} if len(gaps) else None
    buy = sp[has_prev & (pd.to_numeric(sp['score'], errors='coerce') >= BUY)].copy()
    buy['down'] = buy['price'] < buy['prev_price']
    buy['hit'] = buy['success'].astype(bool).astype(int)
    buy['ret'] = pd.to_numeric(buy['return_pct'], errors='coerce')
    buy = buy[buy['ret'].notna()]
    out['buy_pairs'] = int(len(buy))
    rng = random.Random(SEED)
    res = {}
    all_h_below = True
    all_h_above = True
    for s in SPLITS:
        d = buy[buy['split'] == s]
        A = d[d['down']]
        B = d[~d['down']]
        by_date = {}
        for _, r in d.iterrows():
            g = by_date.setdefault(r['date'], {'A': {'hit': [], 'ret': []}, 'B': {'hit': [], 'ret': []}})
            g['A' if r['down'] else 'B']['hit'].append(int(r['hit']))
            g['A' if r['down'] else 'B']['ret'].append(float(r['ret']))
        ci_hit = _boot_diff(by_date, 'hit', rng)
        ci_ret = _boot_diff(by_date, 'ret', rng)
        row = {
            'n_A_down': int(len(A)), 'n_B': int(len(B)), 'dates': int(d['date'].nunique()),
            'hit_A': _pct(A['hit'].tolist()), 'hit_B': _pct(B['hit'].tolist()),
            'hit_diff_pp': (round(_pct(A['hit'].tolist()) - _pct(B['hit'].tolist()), 2)
                            if len(A) and len(B) else None),
            'hit_diff_ci95_pp': ci_hit,
            'ret_A': _mean(A['ret'].tolist()), 'ret_B': _mean(B['ret'].tolist()),
            'ret_diff_ci95': ci_ret,
            'wilson_low_A': _wilson_low(int(A['hit'].sum()), int(len(A))) if len(A) < 30 else None,
            'wilson_low_B': _wilson_low(int(B['hit'].sum()), int(len(B))) if len(B) < 30 else None,
        }
        res[s] = row
        if not ci_hit or ci_hit[1] >= 0:
            all_h_below = False
        if not ci_hit or ci_hit[0] <= 0:
            all_h_above = False
    out['by_split'] = res
    if all_h_below:
        verdict, reason = 'h', '세 구간 모두 적중률 차 A−B 의 CI95 가 0 아래 — 하락 중 추가 매수가 일관되게 나쁘다. 조건 1 을 열지 않는다.'
    elif all_h_above:
        verdict, reason = 'b', '세 구간 모두 CI95 가 0 위 — 배선은 (n) 과 같다. 더 느슨한 게이트는 만들지 않는다.'
    else:
        verdict, reason = 'n', '어느 구간에서 CI95 가 0 을 포함하거나 부호가 갈린다 — 하락 중이라는 사실이 판정을 바꾼다는 증거가 없다. 조건 1 = verdict_core.actionable. 5%p 미만 효과는 이 잣대로 못 본다(R113).'
    out['verdict'] = verdict
    out['verdict_reason'] = reason
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
