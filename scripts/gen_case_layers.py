# -*- coding: utf-8 -*-
"""
계층형 케이스 실측 표 생성 (라운드 58 — '산출 불가' 화면 개선의 데이터).

문제: 초근접 유사사례가 5건이면 화면이 '산출 불가' 세 개로 끝난다.
같은 화면에 점수대 전체 20,824건이 있는데도. 데이터가 없는 게 아니라
**가장 좁은 버킷만 비어 있는 것**이다.

해법(정직한 쪽): 좁은 버킷을 억지로 채우지 않는다 — 유사도 문턱을
낮추거나(측정 후 기준 인하, §2 위반) 남의 종목 표본을 '이 종목 확률'로
둔갑시키지(§3 위반) 않는다. 대신 **더 넓은 계층의 실측을 이름표와 함께**
보여 준다. 각 층은 반드시 점수대를 조건으로 한다 — 49점 종목에 매수권
(58+) 통계를 붙이는 것도 오도다.

층 (전부 개발 구간 · 판정완료 · 블라인드 제외):
  L5  점수대 전체
  L4  점수대 × 시장국면(코스피 4상태)
  L4b 점수대 × 국면 × 전략 프록시(R55 정의 재사용)
  L3  점수대 × 시장(KOSPI/KOSDAQ) × 변동성 3분위
  L2  점수대 × 업종 × 국면 — 업종 표본은 매수권(58+)만 축적돼 있어
      그 외 점수대는 '미축적'으로 정직하게 비운다

출력: data/case_layers.json — 표시 전용. 확률 혼합(shrinkage)은 별도
사전등록(R59) 게이트를 통과하기 전에는 하지 않는다.
"""
import glob
import io
import json
import math
import os
import sys

import numpy as np

try:                       # 라운드 103 — 객체를 갈아끼우지 않는다
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:          # noqa: BLE001
    pass
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
P = os.path.join(PROJ, '.portfolio')
COST = 0.36

import trade_plan as tp                                       # noqa: E402

IDX_CACHE = os.path.join(PROJ, '_probe', 'kospi_daily_cache.json')
BANDS = ((0, 40), (40, 50), (50, 58), (58, 65), (65, 101))


def band_of(score):
    for lo, hi in BANDS:
        if lo <= score < hi:
            return f'{lo}-{hi - 1}'
    return None


def wilson_low(k, n, z=1.96):
    if n == 0:
        return 0.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - m) / d * 100.0


def proxies_of(r):
    """R55 프록시 정의 재사용 — 새 정의를 만들지 않는다."""
    out = []
    if r.get('m10_above') and (r.get('range_pos') or 100) <= 50:
        out.append('눌림')
    if (r.get('range_pos') or 0) >= 80:
        out.append('돌파')
    if (r.get('bb_pos') or 100) <= 20:
        out.append('평균회귀')
    if 'BUY' in str(r.get('demark_state') or ''):
        out.append('DeMARK매수')
    return out


def build_states():
    with open(IDX_CACHE, encoding='utf-8') as f:
        c = json.load(f)
    dates, closes = c['dates'], c['closes']
    arr = np.array(closes, dtype=float)
    out = {}
    for i in range(65, len(arr)):
        st = tp.market_state(arr[i], arr[i - 19:i + 1].mean(),
                             arr[i - 59:i + 1].mean(),
                             arr[i - 64:i - 4].mean())
        d8 = dates[i][:10].replace('.', '-').replace('-', '')[:8]
        out[f'{d8[:4]}-{d8[4:6]}-{d8[6:8]}'] = st.get('code')
    return out


def agg_add(d, key, r):
    a = d.setdefault(key, [0, 0, 0.0])
    a[0] += 1
    a[1] += 1 if r.get('success') else 0
    a[2] += float(r.get('return_pct') or 0) - COST


def agg_out(d, min_n=1):
    return {('|'.join(k) if isinstance(k, tuple) else k):
            dict(n=a[0], hit=round(a[1] / a[0] * 100, 1),
                 wilson=round(wilson_low(a[1], a[0]), 1),
                 ev=round(a[2] / a[0], 3))
            for k, a in d.items() if a[0] >= min_n}


def main():
    states = build_states()
    patch = {}
    for path in sorted(glob.glob(os.path.join(P, 'subscore_patch*.jsonl'))):
        with open(path, encoding='utf-8') as f:
            for ln in f:
                try:
                    q = json.loads(ln)
                    patch[(q['ticker'], q['date'])] = q.get('sector')
                except Exception:                              # noqa: BLE001
                    continue

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
            if r.get('split') == 'blind' or r.get('outcome') == 'OPEN':
                continue
            rows.append(r)
    vols = [float(r['vol20']) for r in rows
            if isinstance(r.get('vol20'), (int, float))]
    t1, t2 = np.percentile(vols, 33.3), np.percentile(vols, 66.7)

    L5, L4, L4b, L3, L2 = {}, {}, {}, {}, {}
    for r in rows:
        b = band_of(float(r.get('score') or 0))
        if not b:
            continue
        d = str(r['date'])[:10]
        st = states.get(d)
        agg_add(L5, b, r)
        if st:
            agg_add(L4, (b, st), r)
            for pxy in proxies_of(r):
                agg_add(L4b, (b, st, pxy), r)
        v = r.get('vol20')
        if isinstance(v, (int, float)):
            vb = '저변동' if v <= t1 else ('중변동' if v <= t2 else '고변동')
            agg_add(L3, (b, str(r.get('market') or '?'), vb), r)
        sec = patch.get((str(r['ticker']), d))
        if sec and st:
            agg_add(L2, (b, sec, st), r)

    # SELF 축 (라운드 61) — 이 종목 자체의 과거 신호 이력. 표시 전용이며
    # **혼합 확률(R59 채택분)에는 넣지 않는다** — 게이트는 SELF 없는
    # 구성으로 통과했고, 통과 후 층을 추가하면 무단 변경이다.
    SELF, SELF_RECENT = {}, {}
    for r in rows:
        tk = str(r['ticker'])
        a = SELF.setdefault(tk, [0, 0])
        a[0] += 1
        a[1] += 1 if r.get('success') else 0
        SELF_RECENT.setdefault(tk, []).append(
            [str(r['date'])[:10], int(float(r.get('score') or 0)),
             '성공' if r.get('success') else
             ('손절' if r.get('outcome') == 'STOP' else '미도달'),
             round(float(r.get('return_pct') or 0), 1)])
    for tk in SELF_RECENT:
        SELF_RECENT[tk] = sorted(SELF_RECENT[tk])[-10:]

    doc = dict(
        made='2026-08-09',
        basis='개발 구간(train+valid) · 판정완료 · 블라인드 제외 · '
              '비용 0.36%p 차감 · 국면=코스피 4상태(R52 규칙 재사용)',
        note='표시 전용 — 각 층은 그 계층의 실측이지 이 종목의 확률이 '
             '아니다. 확률 혼합(shrinkage)은 R59 사전등록 게이트 통과 '
             '전에는 하지 않는다. 업종 층은 매수권(58+)만 축적돼 있다. '
             'SELF 축은 표시 전용 — R59 혼합에 넣지 않는다(게이트가 SELF '
             '없는 구성으로 통과).',
        vol_terciles=[round(float(t1), 5), round(float(t2), 5)],
        L5=agg_out(L5), L4=agg_out(L4, 30), L4b=agg_out(L4b, 30),
        L3=agg_out(L3, 30), L2=agg_out(L2, 30),
        SELF={k: dict(n=v[0], hit=round(v[1] / v[0] * 100, 1),
                      wilson=round(wilson_low(v[1], v[0]), 1))
              for k, v in SELF.items() if v[0] >= 1},
        SELF_RECENT=SELF_RECENT)
    dst = os.path.join(PROJ, 'data', 'case_layers.json')
    with open(dst, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f'층 크기: L5 {len(doc["L5"])} · L4 {len(doc["L4"])} · '
          f'L4b {len(doc["L4b"])} · L3 {len(doc["L3"])} · L2 {len(doc["L2"])}')
    print(f'→ {dst}')
    # 표본 예시
    for k in list(doc['L4b'])[:4]:
        v = doc['L4b'][k]
        print(f"  {k:34s} n {v['n']:>6,} · 적중 {v['hit']}% "
              f"(W {v['wilson']}) · EV {v['ev']:+.3f}")


if __name__ == '__main__':
    main()
