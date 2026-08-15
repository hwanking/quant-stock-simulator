# -*- coding: utf-8 -*-
"""
업종별 원장 실측 성적 생성 (라운드 54b).

업황 카드가 지금은 프록시 모멘텀(현재 상태)만 말한다. 여기에 **이 업종의
매수권 신호가 과거에 실제로 얼마나 맞았는가**를 병기할 재료를 만든다.

  · 원장 개발 구간(train+valid) 매수권(58+) · 판정완료 행만
  · 업종은 백필 패치의 sector (val_eval 기준)
  · 블라인드는 읽지 않는다
  · n < 30 업종은 기록하되 화면에서 Wilson 하한과 함께 '표본 부족' 표기

출력: data/sector_perf.json — 표시 전용. 점수·게이트에 쓰지 않는다.
"""
import glob
import io
import json
import math
import os
import sys

try:                       # 라운드 103 — 객체를 갈아끼우지 않는다
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:          # noqa: BLE001
    pass
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(PROJ, '.portfolio')
COST = 0.36


def wilson_low(k, n, z=1.96):
    if n == 0:
        return 0.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - m) / d * 100.0


patch = {}
for path in sorted(glob.glob(os.path.join(P, 'subscore_patch*.jsonl'))):
    with open(path, encoding='utf-8') as f:
        for ln in f:
            try:
                q = json.loads(ln)
                patch[(q['ticker'], q['date'])] = q.get('sector')
            except Exception:                                  # noqa: BLE001
                continue

agg = {}
with open(os.path.join(P, 'virtual_graded.jsonl'), encoding='utf-8') as f:
    for ln in f:
        ln = ln.strip()
        if not ln:
            continue
        try:
            r = json.loads(ln)
        except Exception:                                      # noqa: BLE001
            continue
        if r.get('split') == 'blind' or r.get('outcome') == 'OPEN':
            continue
        if float(r.get('score') or 0) < 58.0:
            continue
        sec = patch.get((str(r.get('ticker')), str(r.get('date'))[:10]))
        if not sec:
            continue
        a = agg.setdefault(sec, dict(n=0, k=0, net=0.0))
        a['n'] += 1
        a['k'] += 1 if r.get('success') else 0
        a['net'] += float(r.get('return_pct') or 0) - COST

out = {}
for sec, a in agg.items():
    out[sec] = dict(
        n=a['n'], hit=round(a['k'] / a['n'] * 100, 1),
        wilson_low=round(wilson_low(a['k'], a['n']), 1),
        ev=round(a['net'] / a['n'], 3),
        small=a['n'] < 30)

doc = dict(
    made='2026-08-09', basis='개발 구간(train+valid) 매수권 58+ · 판정완료 · '
    '블라인드 미포함 · 비용 0.36%p 차감',
    note='표시 전용 — 점수·게이트에 사용하지 않는다 (라운드 44 결정 유지)',
    sectors=out)
dst = os.path.join(PROJ, 'data', 'sector_perf.json')
with open(dst, 'w', encoding='utf-8') as f:
    json.dump(doc, f, ensure_ascii=False, indent=1)
print(f'업종 {len(out)}개 → {dst}')
for sec, v in sorted(out.items(), key=lambda x: -x[1]['n'])[:12]:
    print(f"  {sec:14s} n {v['n']:5,} · 적중 {v['hit']:5.1f}% "
          f"(W하한 {v['wilson_low']:5.1f}) · EV {v['ev']:+.3f}"
          + ('  [표본 부족]' if v['small'] else ''))
