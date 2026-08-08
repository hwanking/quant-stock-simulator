# -*- coding: utf-8 -*-
"""
케이스 스터디 2호 — 진입 깊이별 체결률·기대값 (기술 통계 · R57 사전 조사).

질문: "지금 안 사고 더 깊은 눌림을 기다리면 무엇을 얻고 무엇을 잃나?"

각 깊이 d (기준가 대비 -1 ~ -7%)에 대해:
  · 20봉 안에 그 가격이 왔는가 (체결률) — 5봉/10봉/20봉
  · 체결됐다면: 체결가 기준 20봉 종가 수익 (비용 0.36%p 차감)
  · 체결 후 종가가 체결가 위로 끝난 비율
  · 체결까지 걸린 봉 수 (중앙)
  · 안 왔다면: 그냥 기준가에 샀을 때의 20봉 종가 수익 (기회비용)

⚠️ 최적 깊이를 여기서 **채택하지 않는다** — 그건 R57 사전등록이 σ 단위·
국면별로 한다 (%는 변동성 큰 종목에 편향된다 — 라운드 33 교훈).
"""
import glob
import io
import json
import os
import sys

import numpy as np

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(PROJ, '.portfolio')
H = 20
COST = 0.36
DEPTHS = (-1.0, -2.0, -3.0, -4.0, -5.0, -7.0)


def main():
    paths = {}
    for path in sorted(glob.glob(os.path.join(P, 'bar_paths_s*.jsonl'))):
        with open(path, encoding='utf-8') as f:
            for ln in f:
                try:
                    r = json.loads(ln)
                    paths[(r['ticker'], r['date'])] = r
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
            p = paths.get((str(r['ticker']), str(r['date'])[:10]))
            if not p or p.get('n_bars', 0) < H:
                continue
            bars = p['bars'][:H]
            rows.append(dict(lo=[b[2] for b in bars],
                             cl=[b[3] for b in bars]))
    n = len(rows)
    base_ev = float(np.mean([r['cl'][-1] for r in rows])) - COST
    print(f'표본 {n:,}건 (개발 매수권 · 블라인드 제외)')
    print(f'기준: 신호일 기준가에 그냥 샀다면 20봉 종가 순EV '
          f'{base_ev:+.3f}%p\n')

    print(f"{'깊이':>5} | {'5봉체결':>7} {'10봉':>6} {'20봉':>6} | "
          f"{'체결후순EV':>9} {'양수마감':>7} {'체결중앙봉':>9} | {'미체결시EV':>9}")
    print('-' * 78)
    out = []
    for d in DEPTHS:
        f5 = f10 = f20 = 0
        evs, wins, tfill, miss_ev = [], 0, [], []
        for r in rows:
            fill = None
            for i, lo in enumerate(r['lo']):
                if lo <= d:
                    fill = i
                    break
            if fill is None:
                miss_ev.append(r['cl'][-1])
                continue
            f20 += 1
            if fill < 5:
                f5 += 1
            if fill < 10:
                f10 += 1
            ev = ((1 + r['cl'][-1] / 100) / (1 + d / 100) - 1) * 100 - COST
            evs.append(ev)
            wins += 1 if ev > 0 else 0
            tfill.append(fill + 1)
        row = dict(depth=d, fill5=f5 / n * 100, fill10=f10 / n * 100,
                   fill20=f20 / n * 100,
                   ev=float(np.mean(evs)) if evs else None,
                   win=wins / len(evs) * 100 if evs else None,
                   tfill=float(np.median(tfill)) if tfill else None,
                   miss_ev=(float(np.mean(miss_ev)) - COST
                            if miss_ev else None),
                   n_fill=f20)
        out.append(row)
        print(f"{d:>4.0f}% | {row['fill5']:>6.1f}% {row['fill10']:>5.1f}% "
              f"{row['fill20']:>5.1f}% | {row['ev']:>+8.3f} "
              f"{row['win']:>6.1f}% {row['tfill']:>8.0f}봉 | "
              f"{(row['miss_ev'] if row['miss_ev'] is not None else 0):>+8.3f}")

    print('\n읽는 법: 체결후순EV = 그 깊이에 지정가를 걸어 체결된 경우의 '
          '20봉 종가 순수익(비용 차감).')
    print('        미체결시EV = 그 깊이까지 안 내려온 신호를 그냥 기준가에 '
          '샀다면의 순수익 — 깊이 기다림의 기회비용.')
    print('⚠️ 깊이 선택은 여기서 하지 않는다 — σ 단위·국면별 사전등록(R57)로 '
          '간다. %는 변동성 큰 종목에 편향된다 (라운드 33).')

    with open(os.path.join(P, 'entry_depth_study_r57.json'), 'w',
              encoding='utf-8') as f:
        json.dump(dict(n=n, base_ev=base_ev, depths=out), f,
                  ensure_ascii=False, indent=1)
    print('\n저장: .portfolio/entry_depth_study_r57.json')


if __name__ == '__main__':
    main()
