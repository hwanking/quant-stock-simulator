# -*- coding: utf-8 -*-
"""
케이스 스터디 3호 — 국면별 어깨 반납·승자 MAE (기술 통계 · R58 사전 조사).

질문: Exit 규칙은 국면마다 달라야 하는가?
  · 어깨 반납(피크 − 종가)이 국면마다 다른가
  · +5% 밟고 빈손 비율이 국면마다 다른가
  · 승자의 목표 전 MAE(손절 여유)가 국면마다 다른가

국면은 R55 와 같은 재구성(코스피 4상태, trade_plan.market_state) —
새 정의를 만들지 않는다. 여기서 어떤 규칙도 채택하지 않는다.
"""
import glob
import io
import json
import os
import sys

import numpy as np

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
P = os.path.join(PROJ, '.portfolio')
H = 20

import trade_plan as tp                                       # noqa: E402

IDX_CACHE = os.path.join(PROJ, '_probe', 'kospi_daily_cache.json')
KO = {'ABOVE_BOTH': '① 상승(20·60 위)', 'REBOUND': '② 반등 초기',
      'PULLBACK': '③ 조정', 'BEAR': '④ 약세'}


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
        key = f'{d8[:4]}-{d8[4:6]}-{d8[6:8]}'
        out[key] = st.get('code')
    return out


def main():
    states = build_states()
    paths = {}
    for path in sorted(glob.glob(os.path.join(P, 'bar_paths_s*.jsonl'))):
        with open(path, encoding='utf-8') as f:
            for ln in f:
                try:
                    r = json.loads(ln)
                    paths[(r['ticker'], r['date'])] = r
                except Exception:                              # noqa: BLE001
                    continue

    cells = {}
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
            d = str(r['date'])[:10]
            st = states.get(d)
            p = paths.get((str(r['ticker']), d))
            if not st or not p or p.get('n_bars', 0) < H:
                continue
            bars = p['bars'][:H]
            rec = dict(hi=[b[1] for b in bars], lo=[b[2] for b in bars],
                       cl=[b[3] for b in bars], succ=bool(r.get('success')),
                       tb=r.get('touched_bar'))
            cells.setdefault(st, []).append(rec)

    print(f"{'국면':16s} {'n':>6} | {'+5%밟음':>7} {'빈손':>6} | "
          f"{'반납중앙':>7} | {'승자MAE중앙':>9} {'-3%견딤':>7} | {'종가EV':>7}")
    print('-' * 84)
    out = {}
    for st in ('ABOVE_BOTH', 'REBOUND', 'PULLBACK', 'BEAR'):
        rs = cells.get(st) or []
        if len(rs) < 100:
            print(f'{KO.get(st, st):16s} {len(rs):>6,} | 표본 부족')
            continue
        n = len(rs)
        t5 = [r for r in rs if max(r['hi']) >= 5.0]
        empty = sum(1 for r in t5 if r['cl'][-1] < 1.0)
        give = np.median([max(r['hi']) - r['cl'][-1] for r in rs])
        winners = [r for r in rs if r['succ']]
        maes = []
        for r in winners:
            k = int(r['tb']) if isinstance(r['tb'], (int, float)) and r['tb'] \
                else H
            maes.append(min(r['lo'][:max(1, min(k, H))]))
        mae_med = np.median(maes) if maes else float('nan')
        endure3 = (np.array(maes) <= -3.0).mean() * 100 if maes else 0
        ev = np.mean([r['cl'][-1] for r in rs]) - 0.36
        print(f"{KO.get(st, st):16s} {n:>6,} | "
              f"{len(t5) / n * 100:>6.1f}% "
              f"{(empty / len(t5) * 100 if t5 else 0):>5.1f}% | "
              f"{give:>6.2f}p | {mae_med:>8.2f}% {endure3:>6.1f}% | "
              f"{ev:>+6.3f}")
        out[st] = dict(n=n, touch5=len(t5), empty5=empty,
                       give_med=float(give), mae_med=float(mae_med),
                       endure3=float(endure3), ev=float(ev))

    print('\n읽는 법: 빈손 = +5% 밟고 20봉 종가 +1% 미만 비율 · '
          '반납중앙 = 피크−종가 중앙값(%p)')
    print('        승자MAE = 목표 선도달 신호의 도달 전 최대 낙폭 · '
          '-3%견딤 = 그중 -3% 이하 경험 비율')
    print('⚠️ 규칙 채택 없음 — 국면별 차이의 존재 여부만 본다. '
          '설계는 R58 사전등록으로.')

    with open(os.path.join(P, 'exit_regime_study_r58.json'), 'w',
              encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('저장: .portfolio/exit_regime_study_r58.json')


if __name__ == '__main__':
    main()
