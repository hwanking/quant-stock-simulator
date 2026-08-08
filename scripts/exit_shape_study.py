# -*- coding: utf-8 -*-
"""
경로 데이터 첫 케이스 스터디 (라운드 57 사전 조사 · 기술 통계만).

⚠️ 이것은 **최적화가 아니다.** 어떤 Exit 규칙도 여기서 고르지 않는다 —
그건 R58 사전등록이 한다. 오늘은 사용자의 질문 네 개를 데이터가 어떻게
답하는지 **세어 보기만** 한다.

  ① +3% 찍고 -2%로 내려온 신호가 얼마나 되나 (되돌림의 실재)
  ② +5% 어깨를 밟고도 빈손으로 끝난 비율 (어깨에서 못 판 비용)
  ③ 목표에 간 신호도 가는 길에 얼마나 아팠나 (성공의 고통 = MAE)
  ④ 손절에 닿은 신호가 그 뒤 반등했나 (손절의 비용)

대상: 개발 구간(train+valid) 매수권(58+) · 블라인드 제외 · 판정완료.
경로: bar_paths (기준가 대비 % · 21봉).
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
H = 20                             # 판정 지평


def load_paths():
    paths = {}
    for path in sorted(glob.glob(os.path.join(P, 'bar_paths_s*.jsonl'))):
        with open(path, encoding='utf-8') as f:
            for ln in f:
                try:
                    r = json.loads(ln)
                    paths[(r['ticker'], r['date'])] = r
                except Exception:                              # noqa: BLE001
                    continue
    return paths


def main():
    paths = load_paths()
    print(f'경로 {len(paths):,}건 적재')

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
            px = float(r['price'])
            r['_hi'] = [b[1] for b in bars]     # 기준가 대비 %
            r['_lo'] = [b[2] for b in bars]
            r['_cl'] = [b[3] for b in bars]
            r['_tgt'] = (float(r['target']) / px - 1) * 100
            r['_stp'] = (float(r['stop']) / px - 1) * 100
            rows.append(r)
    n = len(rows)
    print(f'개발 매수권 · 경로 결합 {n:,}건 (블라인드 제외)\n')

    # ① +3% 찍고 -2% 로 되돌아온 비율
    touched3 = [r for r in rows if max(r['_hi']) >= 3.0]
    fell = 0
    ended_neg = 0
    for r in touched3:
        t1 = next(i for i, h in enumerate(r['_hi']) if h >= 3.0)
        if any(lo <= -2.0 for lo in r['_lo'][t1:]):
            fell += 1
        if r['_cl'][-1] < 0:
            ended_neg += 1
    print('① 되돌림의 실재')
    print(f"   +3% 를 한 번이라도 밟은 신호  {len(touched3):,}건 "
          f"({len(touched3) / n * 100:.1f}%)")
    print(f"   그중 이후 -2% 까지 되돌림      {fell:,}건 "
          f"({fell / len(touched3) * 100:.1f}%)")
    print(f"   그중 20봉 종가가 결국 마이너스  {ended_neg:,}건 "
          f"({ended_neg / len(touched3) * 100:.1f}%)")

    # ② 어깨(+5%)를 밟고도 빈손
    touched5 = [r for r in rows if max(r['_hi']) >= 5.0]
    empty = [r for r in touched5 if r['_cl'][-1] < 1.0]
    neg5 = [r for r in touched5 if r['_cl'][-1] < 0.0]
    print('\n② 어깨를 밟고도 빈손으로 끝난 비율')
    print(f"   +5% 를 밟은 신호               {len(touched5):,}건 "
          f"({len(touched5) / n * 100:.1f}%)")
    print(f"   그중 20봉 종가 +1% 미만        {len(empty):,}건 "
          f"({len(empty) / len(touched5) * 100:.1f}%)")
    print(f"   그중 아예 마이너스 마감         {len(neg5):,}건 "
          f"({len(neg5) / len(touched5) * 100:.1f}%)")

    # ③ 성공(목표 선도달)의 고통 — 목표 봉까지의 MAE
    succ = [r for r in rows if r.get('success')]
    maes = []
    for r in succ:
        tb = r.get('touched_bar')
        k = int(tb) if isinstance(tb, (int, float)) and tb else H
        k = max(1, min(k, H))
        maes.append(min(r['_lo'][:k]))
    maes = np.array(maes)
    print('\n③ 목표에 간 신호도 가는 길이 아팠다 (목표 도달 전 최대 낙폭)')
    print(f"   성공 {len(succ):,}건 · MAE 중앙 {np.median(maes):.2f}% · "
          f"p25 {np.percentile(maes, 25):.2f}% · p75 "
          f"{np.percentile(maes, 75):.2f}%")
    for th in (-2.0, -3.0, -5.0):
        c = int((maes <= th).sum())
        print(f"   목표 가기 전 {th:.0f}% 이하를 견딘 비율  {c:,}건 "
              f"({c / len(succ) * 100:.1f}%)")

    # ④ 손절의 비용 — 손절 터치 후 반등
    stops = [r for r in rows if r.get('outcome') == 'STOP']
    reb_entry = reb_half = 0
    for r in stops:
        s = r['_stp']
        try:
            sb = next(i for i, lo in enumerate(r['_lo']) if lo <= s)
        except StopIteration:
            continue
        after_hi = r['_hi'][sb:]
        if after_hi and max(after_hi) >= 0.0:
            reb_entry += 1
        if after_hi and max(after_hi) >= s / 2.0:
            reb_half += 1
    print('\n④ 손절에 닿은 뒤 무슨 일이 있었나')
    print(f"   손절 도달 {len(stops):,}건")
    print(f"   이후 지평 안에 본전(0%) 회복    {reb_entry:,}건 "
          f"({reb_entry / len(stops) * 100:.1f}%)")
    print(f"   이후 손절폭 절반 이상 반등      {reb_half:,}건 "
          f"({reb_half / len(stops) * 100:.1f}%)")

    # ⑤ 피크 반납 — 20봉 최고점 대비 종가
    give = np.array([max(r['_hi']) - r['_cl'][-1] for r in rows])
    print('\n⑤ 피크에서 얼마나 반납하고 끝나나 (최고 고가 − 최종 종가)')
    print(f"   중앙 {np.median(give):.2f}%p · p75 "
          f"{np.percentile(give, 75):.2f}%p · 5%p 이상 반납 "
          f"{(give >= 5).mean() * 100:.1f}%")

    # 대표 사례 — 패턴별 실제 (종목, 날짜)
    print('\n■ 대표 사례')
    ex1 = next((r for r in touched3
                if any(lo <= -2 for lo in
                       r['_lo'][next(i for i, h in enumerate(r['_hi'])
                                     if h >= 3):])
                and r['_cl'][-1] < 0), None)
    if ex1:
        print(f"   되돌림형: {ex1['ticker']} @ {str(ex1['date'])[:10]} — "
              f"최고 +{max(ex1['_hi']):.1f}% → 최저 {min(ex1['_lo']):.1f}% "
              f"→ 종가 {ex1['_cl'][-1]:+.1f}%")
    ex2 = next((r for r in touched5 if r['_cl'][-1] < 0), None)
    if ex2:
        print(f"   어깨놓침형: {ex2['ticker']} @ {str(ex2['date'])[:10]} — "
              f"최고 +{max(ex2['_hi']):.1f}% → 종가 {ex2['_cl'][-1]:+.1f}%")
    ex3 = None
    for r in stops:
        s = r['_stp']
        try:
            sb = next(i for i, lo in enumerate(r['_lo']) if lo <= s)
        except StopIteration:
            continue
        if r['_hi'][sb:] and max(r['_hi'][sb:]) >= 0:
            ex3 = (r, sb)
            break
    if ex3:
        r, sb = ex3
        print(f"   손절후반등형: {r['ticker']} @ {str(r['date'])[:10]} — "
              f"{sb + 1}봉째 손절({r['_stp']:.1f}%) 터치 후 최고 "
              f"+{max(r['_hi'][sb:]):.1f}% 회복")

    out = dict(n=n, touched3=len(touched3), fell_after_3=fell,
               touched5=len(touched5), empty_after_5=len(empty),
               succ=len(succ), mae_median=float(np.median(maes)),
               stops=len(stops), rebound_to_entry=reb_entry,
               giveback_median=float(np.median(give)))
    with open(os.path.join(P, 'path_case_study_r57.json'), 'w',
              encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('\n저장: .portfolio/path_case_study_r57.json (기술 통계 · 규칙 채택 없음)')


if __name__ == '__main__':
    main()
