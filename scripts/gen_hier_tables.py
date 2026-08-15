# -*- coding: utf-8 -*-
"""
계층 혼합 확률 운영 표 생성 (라운드 59 채택분 — PREREG_R59 §3).

게이트는 train 적합·valid 1회로 통과했다 (Brier 0.2305 vs 0.2566 ·
보정이탈 12.1 vs 35.4%p · 유사사례 보유 부분집합에서도 압승). 운영 표는
관행대로 **개발 구간 전체(train+valid)** 로 재적합한다 — 게이트 측정은
끝났고 blind 는 여기서도 읽지 않는다.

출력: data/hier_prob_tables.json — 층별 (n, k) 원시 집계 + 변동성 3분위
+ m(=100, train 내부 Brier 로 선택 — 선택 기준이 사전등록에 명시되지
않았던 점은 문서에 공개한다).
"""
import glob
import io
import json
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

import trade_plan as tp                                       # noqa: E402

IDX_CACHE = os.path.join(PROJ, '_probe', 'kospi_daily_cache.json')
BANDS = ((0, 40), (40, 50), (50, 58), (58, 65), (65, 101))


def _today():
    """오늘 날짜 — 라운드 107. 박아 두면 다시 만들어도
    안 바뀌어 낡음을 알 수 없다 (라운드 102 miss_study).
    """
    import datetime as _dt
    return _dt.date.today().isoformat()


def band_of(s):
    for lo, hi in BANDS:
        if lo <= s < hi:
            return f'{lo}-{hi - 1}'
    return None


def build_states():
    with open(IDX_CACHE, encoding='utf-8') as f:
        c = json.load(f)
    arr = np.array(c['closes'], dtype=float)
    dates = c['dates']
    out = {}
    for i in range(65, len(arr)):
        st = tp.market_state(arr[i], arr[i - 19:i + 1].mean(),
                             arr[i - 59:i + 1].mean(),
                             arr[i - 64:i - 4].mean())
        d8 = dates[i][:10].replace('.', '-').replace('-', '')[:8]
        out[f'{d8[:4]}-{d8[4:6]}-{d8[6:8]}'] = st.get('code')
    return out


def proxies_of(r):
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
            b = band_of(float(r.get('score') or 0))
            if not b:
                continue
            rows.append((r, b, states.get(str(r['date'])[:10]),
                         patch.get((str(r['ticker']), str(r['date'])[:10]))))

    vols = [float(r['vol20']) for r, _, _, _ in rows
            if isinstance(r.get('vol20'), (int, float))]
    t1, t2 = float(np.percentile(vols, 33.3)), float(np.percentile(vols, 66.7))
    tab = {}

    def add(layer, key, r):
        a = tab.setdefault(f'{layer}|{key}', [0, 0])
        a[0] += 1
        a[1] += 1 if r.get('success') else 0

    for r, b, st, sec in rows:
        add('L5', b, r)
        if st:
            add('L4', f'{b}|{st}', r)
            for pxy in proxies_of(r):
                add('L4b', f'{b}|{st}|{pxy}', r)
        v = r.get('vol20')
        if isinstance(v, (int, float)):
            vb = '저' if v <= t1 else ('중' if v <= t2 else '고')
            add('L3', f"{b}|{r.get('market')}|{vb}", r)
        if sec and st:
            add('L2', f'{b}|{sec}|{st}', r)

    doc = dict(made=_today(), m=100,
               basis='개발 구간(train+valid) 재적합 · 블라인드 미접촉 · '
                     '게이트는 train 적합·valid 1회로 통과 (R59)',
               note='m=100 은 train 내부 Brier 로 선택 — 선택 기준이 '
                    '사전등록에 명시되지 않았던 점을 공개한다 (세 후보 '
                    '전부 내부검증에서 기준선 대비 우위였다)',
               vol_terciles=[round(t1, 5), round(t2, 5)],
               cells={k: v for k, v in tab.items() if v[0] >= 1})
    dst = os.path.join(PROJ, 'data', 'hier_prob_tables.json')
    with open(dst, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False)
    print(f'셀 {len(doc["cells"]):,}개 → {dst}')


if __name__ == '__main__':
    main()
