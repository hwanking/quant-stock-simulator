# -*- coding: utf-8 -*-
"""
라운드 69 — 취약구간 지도 (관측 전용).

"어디서 약한가"만 그린다. 점수·게이트를 바꾸지 않는다 — 8/23 이후
무엇부터 연구할지 순서를 정하는 근거로만 쓴다.

축 (전부 이미 기록된 필드):
  · 시장 국면 (코스피 4상태 · R52 규칙 재사용)
  · 변동성 3분위 (train 기준)
  · 진입 위치 (entry_zone · 원장 기록)
  · 업종 (하위점수 패치)
  · 점수대
  · 유사표본 구간 (eff_sample)

각 칸: n · 에피소드 n · 적중 · Wilson 하한 · 비용후EV · PF · 최대낙폭 중앙
"""
import glob
import io
import json
import math
import os
import sys
from collections import defaultdict
from datetime import date, timedelta

import numpy as np

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
P = os.path.join(PROJ, '.portfolio')
H, COST = 20, 0.36
MIN_N = 60

import trade_plan as tp                                       # noqa: E402
import forward_eval as _fe                                     # noqa: E402

#: 재평가일은 여기서 만들지 않는다 (라운드 78 단일 출처). 라운드 93 에서
#: 이 파일이 '8/23' 을 화면과 data/weakness_map.json 에 계속 찍고 있는 것을
#: 찾았다 — 회귀가 검사 대상 파일을 **손으로 다섯 개** 적어 둔 탓이다.
_FE = _fe.eval_date() or '재평가일 미기록'

IDX = os.path.join(PROJ, '_probe', 'kospi_daily_cache.json')
ST_KO = {'ABOVE_BOTH': '상승', 'REBOUND': '반등초기', 'PULLBACK': '조정',
         'BEAR': '약세'}


def wilson_low(k, n, z=1.96):
    if n == 0:
        return 0.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - m) / d * 100.0


def ep_n(sub):
    last, n = {}, 0
    for r in sorted(sub, key=lambda x: (str(x['ticker']), str(x['date']))):
        tk = str(r['ticker'])
        try:
            dd = date.fromisoformat(str(r['date'])[:10])
        except ValueError:
            continue
        if tk not in last or (dd - last[tk]) > timedelta(days=35):
            n += 1
            last[tk] = dd
    return n


def states():
    with open(IDX, encoding='utf-8') as f:
        c = json.load(f)
    arr = np.array(c['closes'], dtype=float)
    dts = c['dates']
    out = {}
    for i in range(65, len(arr)):
        st = tp.market_state(arr[i], arr[i - 19:i + 1].mean(),
                             arr[i - 59:i + 1].mean(),
                             arr[i - 64:i - 4].mean())
        d8 = dts[i][:10].replace('.', '-').replace('-', '')[:8]
        out[f'{d8[:4]}-{d8[4:6]}-{d8[6:8]}'] = st.get('code')
    return out


def cell(sub):
    n = len(sub)
    k = sum(1 for r in sub if r.get('success'))
    net = np.array([float(r['return_pct']) - COST for r in sub])
    pos, neg = float(net[net > 0].sum()), float(-net[net < 0].sum())
    mae = ([min(r['_lo']) for r in sub if '_lo' in r] or [float('nan')])
    return dict(n=n, ep=ep_n(sub), hit=round(k / n * 100, 1),
                wilson=round(wilson_low(k, n), 1),
                ev=round(float(net.mean()), 3),
                pf=round(pos / neg, 2) if neg > 0 else None,
                mae=round(float(np.median(mae)), 2))


def main():
    stt = states()
    paths = {}
    for path in sorted(glob.glob(os.path.join(P, 'bar_paths_s*.jsonl'))):
        with open(path, encoding='utf-8') as f:
            for ln in f:
                try:
                    q = json.loads(ln)
                    paths[(q['ticker'], q['date'])] = q
                except Exception:                              # noqa: BLE001
                    continue
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
            if (r.get('split') == 'blind' or r.get('outcome') == 'OPEN'
                    or float(r.get('score') or 0) < 58.0):
                continue
            k = (str(r['ticker']), str(r['date'])[:10])
            p = paths.get(k)
            if p and p.get('n_bars', 0) >= H:
                r['_lo'] = [b[2] for b in p['bars'][:H]]
            r['_st'] = stt.get(str(r['date'])[:10])
            r['_sec'] = patch.get(k)
            rows.append(r)
    vols = [float(r['vol20']) for r in rows
            if isinstance(r.get('vol20'), (int, float))]
    t1, t2 = np.percentile(vols, 33.3), np.percentile(vols, 66.7)
    base = cell(rows)
    print(f"기준선 (매수권 전체) n {base['n']:,} · 적중 {base['hit']}% · "
          f"EV {base['ev']:+.3f} · PF {base['pf']}\n")

    axes = {
        '시장 국면': lambda r: ST_KO.get(r['_st']),
        '변동성': lambda r: (None if not isinstance(r.get('vol20'),
                                                (int, float))
                          else '저변동' if r['vol20'] <= t1
                          else '중변동' if r['vol20'] <= t2 else '고변동'),
        '진입 위치': lambda r: str(r.get('entry_zone') or '')[:14] or None,
        '업종': lambda r: r['_sec'],
        '점수대': lambda r: f"{int(float(r.get('score') or 0)) // 5 * 5}점대",
        '유사표본': lambda r: (None if not isinstance(r.get('eff_sample'),
                                                 (int, float))
                           else '표본<30' if r['eff_sample'] < 30
                           else '표본30~99' if r['eff_sample'] < 100
                           else '표본100+'),
    }
    out = {}
    weak = []
    for ax, fn in axes.items():
        g = defaultdict(list)
        for r in rows:
            v = fn(r)
            if v:
                g[v].append(r)
        cells = {k: cell(v) for k, v in g.items() if len(v) >= MIN_N}
        if not cells:
            continue
        out[ax] = cells
        print(f'■ {ax}')
        for k in sorted(cells, key=lambda x: cells[x]['ev']):
            c = cells[k]
            mark = '  ← 취약' if c['ev'] < base['ev'] - 0.3 else ''
            print(f"  {k:16s} n {c['n']:>6,}(ep {c['ep']:>5,}) · "
                  f"적중 {c['hit']:5.1f}%(W {c['wilson']:4.1f}) · "
                  f"EV {c['ev']:+7.3f} · PF {str(c['pf']):>5} · "
                  f"MAE {c['mae']:+6.2f}%{mark}")
            if c['ev'] < base['ev'] - 0.3:
                weak.append((ax, k, c['ev'], c['n']))
        print()

    print(f'■ 가장 약한 칸 ({_FE} 이후 연구 우선순위 후보)')
    for ax, k, ev, n in sorted(weak, key=lambda x: x[2])[:8]:
        print(f'  {ax:10s} {k:16s} EV {ev:+.3f} (n {n:,})')

    dst = os.path.join(PROJ, 'data', 'weakness_map.json')
    with open(dst, 'w', encoding='utf-8') as f:
        json.dump(dict(made='2026-08-10', base=base, axes=out,
                       min_n=MIN_N,
                       note='관측 전용 — 점수·게이트를 바꾸지 않는다. '
                            f'{_FE} 이후 연구 순서를 정하는 근거로만 쓴다.',
                       weakest=[dict(axis=a, cell=k, ev=e, n=n)
                                for a, k, e, n in
                                sorted(weak, key=lambda x: x[2])[:10]]),
                  f, ensure_ascii=False, indent=1)
    print(f'\n저장: {dst}')


if __name__ == '__main__':
    main()
