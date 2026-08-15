# -*- coding: utf-8 -*-
"""
라운드 67 — 놓친 종목·잘못 고른 종목 자동 수집 (관측 전용).

BGF리테일을 사람이 눈으로 찾아야 했다. 그건 늦다. 원장 전체에서
**엔진이 제외했는데 이후 오른 신호(FN)** 와 **추천했는데 손절된
신호(FP)** 를 자동으로 모은다.

■ 8/23 동결 준수
  · 점수·게이트·문턱을 하나도 바꾸지 않는다. 읽기만 한다
  · 여기서 나온 패턴으로 오늘 규칙을 고치지 않는다 — 8/23 이후
    새 사전등록의 **후보 목록**으로만 쓴다
  · append-only 산출물 (data/miss_study.json)

■ 정의 (고정)
  FN(놓침)  = 매수권 미달(score < 58) 인데 20봉 내 고가 +10% 이상
  FP(오선택) = 매수권(58+) 인데 손절 선도달(outcome=STOP)
  대상: 개발 구간 · 판정완료 · 경로 21봉 결합 · blind 제외
"""
import glob
import io
import json
import os
import sys
from collections import Counter
from datetime import date, datetime, timezone

import numpy as np

try:                       # 라운드 103 — 객체를 갈아끼우지 않는다
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:          # noqa: BLE001
    pass
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
P = os.path.join(PROJ, '.portfolio')
H, COST = 20, 0.36
FN_UP = 10.0                       # 놓침 판정 상승폭 (%)

import forward_eval as _fe                                     # noqa: E402

#: 재평가일 단일 출처 (라운드 78). 라운드 93 에서 이 파일이 결과 json 에
#: 옛 날짜를 계속 적고 있는 것을 찾았다 — 회귀가 검사할 파일을 손으로
#: 적어 둔 탓에 보름 넘게 안 보였다.
_FE = _fe.eval_date() or '재평가일 미기록'


def load_map(pattern):
    m = {}
    for path in sorted(glob.glob(os.path.join(P, pattern))):
        with open(path, encoding='utf-8') as f:
            for ln in f:
                try:
                    r = json.loads(ln)
                    m[(r['ticker'], r['date'])] = r
                except Exception:                              # noqa: BLE001
                    continue
    return m


def main():
    paths = load_map('bar_paths_s*.jsonl')
    flags = load_map('breakout_flags_s*.jsonl')
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
    _ledger_rows = 0        # 원장이 몇 줄일 때 잰 것인지 — 낡음 판정의 근거
    with open(os.path.join(P, 'virtual_graded.jsonl'), encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:                                  # noqa: BLE001
                continue
            _ledger_rows += 1
            if r.get('split') == 'blind' or r.get('outcome') == 'OPEN':
                continue
            k = (str(r['ticker']), str(r['date'])[:10])
            p = paths.get(k)
            if not p or p.get('n_bars', 0) < H:
                continue
            bars = p['bars'][:H]
            r['_hi'] = [b[1] for b in bars]
            r['_lo'] = [b[2] for b in bars]
            r['_cl'] = [b[3] for b in bars]
            r['_fl'] = flags.get(k)
            r['_sector'] = patch.get(k)
            rows.append(r)
    print(f'결합 {len(rows):,}건 (개발 구간 · blind 제외)\n')

    below = [r for r in rows if float(r.get('score') or 0) < 58]
    inbuy = [r for r in rows if float(r.get('score') or 0) >= 58]
    fn = [r for r in below if max(r['_hi']) >= FN_UP]
    fp = [r for r in inbuy if r.get('outcome') == 'STOP']

    print(f'■ 놓침(FN) — 매수권 미달인데 20봉 내 +{FN_UP:.0f}% 이상')
    print(f'  {len(fn):,}건 / 미달 {len(below):,}건 '
          f'({len(fn) / max(1, len(below)) * 100:.1f}%)')
    hi_all = [max(r['_hi']) for r in below]
    print(f'  참고 — 미달 전체의 20봉 최고 상승 중앙 '
          f'{np.median(hi_all):+.2f}% · 매수권 전체 '
          f'{np.median([max(r["_hi"]) for r in inbuy]):+.2f}%')
    # ⚠️ 36.6% 라는 수치만으로는 아무것도 말할 수 없다. 매수권에서도
    # 같은 비율이면 문턱이 가르지 못한다는 뜻이다 — 기준선을 함께 본다.
    up_in = np.mean([max(r['_hi']) >= FN_UP for r in inbuy]) * 100
    up_bl = len(fn) / max(1, len(below)) * 100
    print(f'  대조 — +{FN_UP:.0f}% 도달률: 매수권 {up_in:.1f}% vs '
          f'미달 {up_bl:.1f}% (차이 {up_in - up_bl:+.1f}%p)')
    print(f'         매수권 종가 중앙 '
          f'{np.median([r["_cl"][-1] for r in inbuy]):+.2f}% vs '
          f'미달 {np.median([r["_cl"][-1] for r in below]):+.2f}%')
    # FN 이 끝까지 갔나 — 최고만 찍고 반납했으면 '놓친 기회'가 아니다
    fn_end = np.median([r['_cl'][-1] for r in fn])
    fn_pos = np.mean([r['_cl'][-1] > 0 for r in fn]) * 100
    print(f'  FN 의 20봉 종가 중앙 {fn_end:+.2f}% · 양수 마감 {fn_pos:.1f}% '
          f'— 고점만 스치고 되돌린 비율이 크면 "놓쳤다"고 말할 수 없다')

    print('\n  FN 상위 점수대 분포')
    for b, c in Counter((int(float(r.get('score') or 0)) // 10) * 10
                        for r in fn).most_common(5):
        print(f'    {b}~{b + 9}점  {c:,}건')
    print('  FN 업종 상위')
    for s, c in Counter(r['_sector'] for r in fn
                        if r['_sector']).most_common(6):
        print(f'    {s:20s}{c:,}건')
    if any(r['_fl'] for r in fn):
        br = sum(1 for r in fn if r['_fl']
                 and (r['_fl']['b1'] or r['_fl']['b2']))
        brb = sum(1 for r in below if r['_fl']
                  and (r['_fl']['b1'] or r['_fl']['b2']))
        print(f'  FN 중 돌파 신호 {br:,}건 ({br / max(1, len(fn)) * 100:.1f}%) '
              f'· 미달 전체 중 돌파 {brb / max(1, len(below)) * 100:.1f}% '
              f'— 차이가 크면 돌파가 놓침의 원인 후보')

    print(f'\n■ 오선택(FP) — 매수권인데 손절 선도달')
    print(f'  {len(fp):,}건 / 매수권 {len(inbuy):,}건 '
          f'({len(fp) / max(1, len(inbuy)) * 100:.1f}%)')
    print('  FP 업종 상위')
    for s, c in Counter(r['_sector'] for r in fp
                        if r['_sector']).most_common(6):
        tot = sum(1 for r in inbuy if r['_sector'] == s)
        print(f'    {s:20s}{c:,}건 / {tot:,} ({c / max(1, tot) * 100:.0f}%)')

    # 대표 사례 — 사람이 복기할 수 있게
    fn_top = sorted(fn, key=lambda r: -max(r['_hi']))[:8]
    print('\n■ 대표 놓침 사례 (20봉 최고 상승 순)')
    for r in fn_top:
        print(f"    {r['ticker']:10s} {str(r['date'])[:10]} · 점수 "
              f"{float(r.get('score') or 0):.0f} · 최고 "
              f"{max(r['_hi']):+.1f}% · 종가 {r['_cl'][-1]:+.1f}% · "
              f"{r.get('action_title') or ''}")

    out = dict(
        # ⚠️ 라운드 102 — 여기가 `made='2026-08-10'` 으로 **박혀 있었다.**
        #   방금 다시 만든 산출물이 "8/10 에 만들었다" 고 적으니, 이게
        #   오늘 원장으로 잰 것인지 닷새 전 것인지 알 방법이 없었다.
        #   자동으로 도는 연구에서 그건 치명적이다 — 조용히 멈춰도
        #   눈치채지 못한다 (라운드 96 에서 개선 파이프라인이 그랬다).
        #   **언제 돌렸는지**와 **무엇으로 쟀는지**를 같이 적는다.
        made=date.today().isoformat(),
        made_at=datetime.now(timezone.utc).isoformat(timespec='seconds'),
        #: 이 값으로 낡음을 **판정**한다 — 원장이 자란 만큼 벌어진다
        ledger_rows=_ledger_rows,
        joined_n=len(rows),
        basis='개발 구간 · 판정완료 · blind 제외 · 경로 21봉 결합',
        note='관측 전용 — 점수·게이트·문턱을 바꾸지 않는다. 여기서 나온 '
             f'패턴은 {_FE} 이후 새 사전등록의 후보 목록으로만 쓴다.',
        fn_rule=f'score<58 & 20봉 최고 >= +{FN_UP:.0f}%',
        fp_rule='score>=58 & outcome=STOP',
        fn_n=len(fn), below_n=len(below),
        fp_n=len(fp), inbuy_n=len(inbuy),
        fn_end_median=round(float(fn_end), 2),
        fn_positive_close_pct=round(float(fn_pos), 1),
        fn_sectors=dict(Counter(r['_sector'] for r in fn
                                if r['_sector']).most_common(10)),
        fp_sectors=dict(Counter(r['_sector'] for r in fp
                                if r['_sector']).most_common(10)),
        fn_examples=[{'ticker': r['ticker'], 'date': str(r['date'])[:10],
                      'score': float(r.get('score') or 0),
                      'max_up': round(max(r['_hi']), 1),
                      'close': round(r['_cl'][-1], 1)} for r in fn_top],
    )
    dst = os.path.join(PROJ, 'data', 'miss_study.json')
    with open(dst, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f'\n저장: {dst} (관측 전용 · 규칙 변경 없음)')


if __name__ == '__main__':
    main()
