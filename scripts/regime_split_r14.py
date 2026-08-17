# -*- coding: utf-8 -*-
"""
라운드 14 — 국면을 변동성 축으로 쪼갠다 (횡보 실전 하락의 진짜 원인).

라운드 13에서 밝혀진 것:
  블라인드의 '횡보'는 이름만 횡보였다.
    일간 변동성  검증 2.79%  vs  블라인드 5.09%  (1.8배)
    평균 최대낙폭 검증 3.69%  vs  블라인드 7.68%  (2.1배)
  지수는 옆으로 가는데 개별 종목은 하루 5%씩 흔들리는 장이다.
  조용한 횡보와 험한 횡보를 같은 이름으로 묶으니 성적이 뒤섞였다.

그래서 국면을 하나 더 쪼갠다:
    상승/횡보/하락  ×  차분함(일변동 3% 미만) / 거침(3% 이상)  =  6국면

이건 새 지표를 만드는 게 아니다. 이미 원장에 있는 vol20 으로 나누는 것이고,
**분류가 세분되면 각 칸의 성적이 서로 더 안정적이어야 한다**는 것이 가설이다.

검정 (사전등록):
  ① 6국면 각 칸에서 검증↔블라인드 적중률 격차가 3국면일 때보다 줄어드는가
     (평균 절대 격차로 비교 — 줄어야 '분류가 나아졌다'고 말할 수 있다)
  ② 표본이 충분한 칸(블라인드 30건+)이 3개 이상 남는가
  ③ 어느 칸도 기존보다 크게 나빠지지 않는가
  → 셋 다 충족하면 화면의 국면 표를 6칸으로 바꾼다.
     실패하면 3국면을 유지하고 이유를 적는다.

⚠️ 이 라운드는 **점수·게이트를 바꾸지 않는다.** 같은 판단을 더 정확한
   이름으로 묶어 보여 주는 것이다. 판단 로직 변경은 별도 사전등록이 필요하다.
"""
from __future__ import annotations

import io
import json
import math
import os
import sys

try:                       # 라운드 103 — 객체를 갈아끼우지 않는다
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:          # noqa: BLE001
    pass
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(BASE, '.portfolio', 'virtual_graded.jsonl')
OUT = os.path.join(BASE, '.portfolio', 'regime_breakdown.json')

COST = 0.30
BUY = 58
VOL_SPLIT = 0.030          # 일간 변동성 3% — 차분함/거침 경계
MIN_CELL_N = 30

REG_KO = {'BULL': '상승', 'SIDEWAYS': '옆걸음', 'BEAR': '하락'}
VOL_KO = {'calm': '차분한', 'rough': '거친'}


def load():
    out = []
    with open(LEDGER, encoding='utf-8') as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get('success') is None or r.get('return_pct') is None:
                continue
            out.append(r)
    return out


def wilson(hit, n, z=1.96):
    if not n:
        return None, None
    p = hit / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return round(100 * (c - m) / d, 1), round(100 * (c + m) / d, 1)


def stats(rows):
    n = len(rows)
    if not n:
        return None
    hit = sum(1 for r in rows if r['success'])
    rets = [float(r['return_pct']) for r in rows]
    maes = [abs(float(r['mae_pct'])) for r in rows
            if r.get('mae_pct') is not None]
    vols = [float(r['vol20']) for r in rows if r.get('vol20') is not None]
    lo, hi = wilson(hit, n)
    return {'n': n, 'hit': round(100.0 * hit / n, 1),
            'ci_low': lo, 'ci_high': hi,
            'net': round(sum(rets) / n - COST, 2),
            'mae': round((sum(maes) / len(maes)) if maes else 0.0, 2),
            'vol': round((sum(vols) / len(vols) * 100) if vols else 0.0, 2)}


def volband(r):
    v = r.get('vol20')
    if v is None:
        return None
    return 'calm' if float(v) < VOL_SPLIT else 'rough'


def main():
    rows = [r for r in load() if (r.get('score') or 0) >= BUY]
    by = {s: [r for r in rows if r.get('split') == s]
          for s in ('train', 'valid', 'blind')}
    print(f"매수권 사례 {len(rows):,}건 · 변동성 경계 {VOL_SPLIT * 100:.0f}%\n")

    # ── 현행 3국면 ────────────────────────────────────────────────────
    print('■ 현행 3국면')
    gaps3 = []
    old = {}
    for rg in ('BULL', 'SIDEWAYS', 'BEAR'):
        cell = {s: stats([r for r in by[s] if r.get('regime') == rg])
                for s in by}
        old[rg] = cell
        v, b = cell['valid'], cell['blind']
        if v and b:
            gap = abs(v['hit'] - b['hit'])
            gaps3.append(gap)
            print(f"  {REG_KO[rg]:4s}  연습 {v['hit']:5.1f}%(n={v['n']:4d}) · "
                  f"실전 {b['hit']:5.1f}%(n={b['n']:4d})  격차 {gap:5.1f}%p")
    print(f"  평균 격차 {sum(gaps3) / len(gaps3):.1f}%p")

    # ── 6국면 ────────────────────────────────────────────────────────
    print(f'\n■ 6국면 (변동성 {VOL_SPLIT * 100:.0f}% 로 분할)')
    gaps6 = []
    new = {}
    enough = 0
    for rg in ('BULL', 'SIDEWAYS', 'BEAR'):
        for vb in ('calm', 'rough'):
            key = f'{rg}|{vb}'
            cell = {s: stats([r for r in by[s]
                              if r.get('regime') == rg and volband(r) == vb])
                    for s in by}
            new[key] = cell
            v, b = cell['valid'], cell['blind']
            ko = f"{VOL_KO[vb]} {REG_KO[rg]}"
            if not (v and b):
                print(f"  {ko:10s}  표본 부족 — 판정 불가")
                continue
            gap = abs(v['hit'] - b['hit'])
            if b['n'] >= MIN_CELL_N and v['n'] >= MIN_CELL_N:
                gaps6.append(gap)
                enough += 1
                tag = ''
            else:
                tag = '  (표본 부족)'
            print(f"  {ko:10s}  연습 {v['hit']:5.1f}%(n={v['n']:4d}) · "
                  f"실전 {b['hit']:5.1f}%(n={b['n']:4d})  격차 {gap:5.1f}%p"
                  f"  일변동 {b['vol']:.1f}%{tag}")
    if gaps6:
        print(f"  평균 격차 {sum(gaps6) / len(gaps6):.1f}%p "
              f"(표본 충분한 {enough}칸 기준)")

    # ── 사전등록 판정 ─────────────────────────────────────────────────
    print('\n■ 사전등록 판정')
    g3 = sum(gaps3) / len(gaps3) if gaps3 else 99
    g6 = sum(gaps6) / len(gaps6) if gaps6 else 99
    c1 = g6 < g3
    c2 = enough >= 3
    print(f"  ① 연습-실전 격차 감소: {g3:.1f}%p → {g6:.1f}%p  "
          f"{'통과' if c1 else '미달'}")
    print(f"  ② 표본 충분한 칸 3개+: {enough}칸  {'통과' if c2 else '미달'}")
    worse = []
    for rg in ('BULL', 'SIDEWAYS', 'BEAR'):
        ob = old[rg]['blind']
        for vb in ('calm', 'rough'):
            nb = new[f'{rg}|{vb}']['blind']
            if nb and ob and nb['n'] >= MIN_CELL_N and nb['hit'] < ob['hit'] - 15:
                worse.append(f"{VOL_KO[vb]} {REG_KO[rg]}")
    c3 = not worse
    print(f"  ③ 크게 나빠진 칸 없음: {'없음' if c3 else ', '.join(worse)}  "
          f"{'통과' if c3 else '미달'}")

    adopt = c1 and c2 and c3
    print('\n' + '=' * 74)
    if adopt:
        print('판정: 채택 — 화면의 국면 표를 6칸으로 바꾼다.')
        print(f"  같은 판단을 더 정확한 이름으로 묶으니 연습-실전 격차가 "
              f"{g3:.1f}%p → {g6:.1f}%p 로 줄었다.")
        print('  ⚠️ 점수·게이트는 바꾸지 않았다 — 분류(이름)만 세분했다.')
    else:
        print('판정: 채택 없음 — 3국면을 유지한다.')
    print('=' * 74)

    # 산출물은 화면이 바로 쓸 수 있게 두 벌 다 담는다
    #
    # 라운드 121 — `generated_at` · `ledger_buyzone_n` 을 추가했다.
    #   종전 산출물에는 **측정 시각이 없었다.** 8/3 에 잰 표가 화면에
    #   그대로 떠 있는 동안 원장은 4천 건대에서 82,259 건으로 자랐고,
    #   화면은 "연습 54% (n=225)" 를 계속 보여 주고 있었다 (같은 칸을
    #   지금 원장으로 세면 n=3,577 이다).
    #   §2 가 적어 둔 그대로다 — **날짜 없는 숫자는 반드시 낡는다.**
    import datetime as _dt
    out = {'generated_from': 'virtual_graded.jsonl',
           'generated_at': _dt.date.today().isoformat(),
           'ledger_buyzone_n': len(rows),
           'vol_split': VOL_SPLIT, 'min_cell_n': MIN_CELL_N,
           'mode': '6' if adopt else '3',
           'gap3': round(g3, 1), 'gap6': round(g6, 1),
           'regime_ko': REG_KO, 'vol_ko': VOL_KO,
           'buy_zone': {}, 'cells6': {}}
    for rg in ('BULL', 'SIDEWAYS', 'BEAR'):
        out['buy_zone'].setdefault('train', {})[rg] = old[rg]['train']
        out['buy_zone'].setdefault('valid', {})[rg] = old[rg]['valid']
        out['buy_zone'].setdefault('blind', {})[rg] = old[rg]['blind']
    for k, cell in new.items():
        out['cells6'][k] = cell
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f'\n저장: {OUT}')
    return 0 if adopt else 1


if __name__ == '__main__':
    sys.exit(main())
