# -*- coding: utf-8 -*-
"""
케이스 스터디 5호 — 거래량과 어깨 (기술 통계 · R58 Exit 재료).

질문: 피크(최고 고가) 근처에서 거래량이 마르는가, 폭발하는가?
      "거래량 이탈" 류 Exit 후보가 잡을 신호가 실재하는지 본다.

  ① 피크 봉의 거래량 배율(신호일 대비) 분포 — 어깨는 시끄러운가
  ② 피크 이후 3봉 거래량 vs 피크 전 3봉 — 마름의 실재
  ③ 되돌림형(+3% 후 -2%)에서 되돌림 시작 봉의 거래량
  ④ 보유기간 EV 곡선 — 5·10·15·20봉 시점의 평균 종가 (20봉이 최적 지평인가)

규칙 채택 없음. 대상: 개발 매수권 · 판정완료 · 블라인드 제외.
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
            if any(len(b) < 5 or b[4] is None for b in bars):
                continue                     # 볼륨 없는 행은 정직하게 제외
            rows.append(dict(hi=[b[1] for b in bars],
                             lo=[b[2] for b in bars],
                             cl=[b[3] for b in bars],
                             vol=[b[4] for b in bars]))
    n = len(rows)
    print(f'표본 {n:,}건 (볼륨 있는 행만 · 개발 매수권 · 블라인드 제외)\n')

    # ① 피크 봉의 거래량
    pk_vol, pre_all = [], []
    dry_after = loud_peak = 0
    for r in rows:
        pk = int(np.argmax(r['hi']))
        pk_vol.append(r['vol'][pk])
        pre = r['vol'][max(0, pk - 3):pk]
        post = r['vol'][pk + 1:pk + 4]
        if pre and post:
            pre_m, post_m = np.mean(pre), np.mean(post)
            pre_all.append(pre_m)
            if post_m < pre_m * 0.7:
                dry_after += 1
        if r['vol'][pk] >= 1.5:
            loud_peak += 1
    print('① 피크 봉의 거래량 (신호일 = 1.0 기준)')
    print(f"   피크 봉 배율 중앙 {np.median(pk_vol):.2f}배 · "
          f"1.5배 이상(시끄러운 어깨) {loud_peak / n * 100:.1f}%")
    print(f"② 피크 후 3봉 거래량이 피크 전 대비 30%+ 마름: "
          f"{dry_after / n * 100:.1f}%")

    # ③ 되돌림 시작 봉의 거래량
    rev_vols = []
    for r in rows:
        try:
            t3 = next(i for i, h in enumerate(r['hi']) if h >= 3.0)
        except StopIteration:
            continue
        try:
            rv = next(i for i in range(t3, H) if r['lo'][i] <= -2.0)
        except StopIteration:
            continue
        rev_vols.append(r['vol'][rv])
    if rev_vols:
        print(f"③ 되돌림(-2% 터치) 시작 봉 거래량 중앙 "
              f"{np.median(rev_vols):.2f}배 (n {len(rev_vols):,}) — "
              f"1.0배 미만(조용한 붕괴) {np.mean(np.array(rev_vols) < 1.0) * 100:.1f}%")

    # ④ 보유기간 EV 곡선
    print('\n④ 보유기간별 평균 종가 (비용 0.36 차감)')
    for k in (3, 5, 10, 15, 20):
        ev = np.mean([r['cl'][k - 1] for r in rows]) - 0.36
        pos = np.mean([r['cl'][k - 1] > 0 for r in rows]) * 100
        print(f"   {k:>2}봉째  순EV {ev:+.3f}%p · 양수 비율 {pos:.1f}%")

    out = dict(n=n, peak_vol_med=float(np.median(pk_vol)),
               loud_peak_pct=loud_peak / n * 100,
               dry_after_pct=dry_after / n * 100,
               rev_vol_med=(float(np.median(rev_vols)) if rev_vols else None))
    with open(os.path.join(P, 'volume_exit_study_r58.json'), 'w',
              encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('\n저장: .portfolio/volume_exit_study_r58.json (규칙 채택 없음)')


if __name__ == '__main__':
    main()
