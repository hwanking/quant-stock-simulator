# -*- coding: utf-8 -*-
"""라운드 121 — 국면 6칸의 표본을 **날짜 단위로도** 센다 (표시 전용).

■ 왜 만들었나
  화면의 국면 표는 케이스 수(n)만 적는다:

      차분한 옆걸음   연습 77% (n=109) · 실전 34~74% (n=20)
      거친 하락       연습 64~96% (n=16) · 실전 4~36% (n=16)

  그런데 국면은 **시장 수준** 값이다. 같은 날 추천이 90건이면 케이스는
  90이지만 독립 관측은 **1일**뿐이다. 이미 같은 함정에 빠진 적이 있다 —
  VIX 축이 블라인드 6조건을 다 통과했는데 "케이스 280건"이 실은 날짜
  5개였다. CLAUDE.md 라운드 113 도 같은 결론을 적어 뒀다:
  **"표본 조건에는 케이스와 날짜를 함께 넣는다."**

■ 이것이 하지 않는 것 (중요)
  · 점수·게이트·문턱을 **바꾸지 않는다.**
  · 게이트가 읽는 `regime_breakdown.json` 을 **건드리지 않는다.**
    그 파일은 `regime_policy` 가 점수 상한·비중·손절 배수를 정하는 데
    쓴다. R55·R57·R66 전방 표본이 2026-08-09 부터 쌓이는 중이므로
    지금 다시 재면 그 표본이 무효가 된다 (재평가 2026-11-16).
  · 그래서 **다른 파일**에 **다른 수치**(날짜 수)만 적는다. 같은 값을
    두 경로로 만들지 않는다 (§4).

■ 산식을 베끼지 않는다
  국면·변동성 분류는 `regime_split_r14` 의 것을 그대로 부른다.
  여기서 새로 정의하면 언젠가 두 정의가 갈린다.

    C:/Python314/python.exe scripts/regime_cell_days_r121.py
"""
from __future__ import annotations

import io
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:                                              # noqa: BLE001
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import regime_split_r14 as R                                   # noqa: E402

OUT = os.path.join(BASE, '.portfolio', 'regime_cell_days.json')

#: 원장 행에서 '어느 날의 판단인가'를 읽을 수 있는 키 후보.
#: 손으로 하나만 적어 두면 원장 스키마가 바뀔 때 조용히 0 이 된다.
DATE_KEYS = ('date', 'entry_date', 'as_of', 'asof', 'signal_date',
             'recommended_at', 'entry_at', 'graded_at')


def day_of(row):
    for k in DATE_KEYS:
        v = row.get(k)
        if v:
            return str(v)[:10]
    return None


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    rows = [r for r in R.load() if (r.get('score') or 0) >= R.BUY]
    if not rows:
        print('원장에서 매수권 사례를 못 읽었다 — 아무것도 쓰지 않는다.')
        return 1

    dated = sum(1 for r in rows if day_of(r))
    print(f'매수권 사례 {len(rows):,}건 · 날짜를 읽어낸 사례 {dated:,}건')
    if not dated:
        # 0 을 '날짜가 없다'로 적으면 거짓이다. 못 읽었다고 적고 멈춘다.
        print('→ 날짜 키를 못 찾았다. 산출물을 쓰지 않는다 (§3).')
        print('   원장 첫 행 키:', sorted(rows[0].keys())[:24])
        return 1

    by = {s: [r for r in rows if r.get('split') == s]
          for s in ('train', 'valid', 'blind')}
    cells, worst = {}, []
    print(f"\n{'칸':<14}{'연습 n':>7}{'연습 일':>7}{'실전 n':>8}{'실전 일':>7}"
          f"{'케이스/일':>10}")
    print('-' * 54)
    for rg in ('BULL', 'SIDEWAYS', 'BEAR'):
        for vb in ('calm', 'rough'):
            key = f'{rg}|{vb}'
            ent = {}
            for s in ('valid', 'blind'):
                sub = [r for r in by[s]
                       if r.get('regime') == rg and R.volband(r) == vb]
                days = {day_of(r) for r in sub if day_of(r)}
                ent[s] = {'n': len(sub), 'days': len(days)}
            cells[key] = ent
            ko = f"{R.VOL_KO[vb]} {R.REG_KO[rg]}"
            bn, bd = ent['blind']['n'], ent['blind']['days']
            ratio = f'{bn / bd:.1f}' if bd else '—'
            print(f"{ko:<14}{ent['valid']['n']:>7}{ent['valid']['days']:>7}"
                  f"{bn:>8}{bd:>7}{ratio:>10}")
            if bd:
                worst.append((ko, bn, bd, bn / bd))

    worst.sort(key=lambda x: -x[3])
    print('\n■ 케이스 수가 날짜 수를 가장 크게 넘는 칸')
    for ko, bn, bd, rt in worst[:3]:
        print(f'   {ko:<14} 케이스 {bn:>5}건 = 날짜 {bd:>3}일  ({rt:.0f}배)')

    # 측정 날짜를 **반드시** 함께 적는다 — 날짜 없는 숫자는 낡는다 (§2).
    import datetime as _dt
    out = {
        'measured_at': _dt.date.today().isoformat(),
        'ledger_buyzone_n': len(rows),
        'dated_n': dated,
        'score_floor': R.BUY,
        'vol_split': R.VOL_SPLIT,
        'note': ('표시 전용. 점수·게이트·문턱에 쓰지 않는다. '
                 'regime_breakdown.json(게이트용)은 건드리지 않았다.'),
        'cells': cells,
    }
    if '--dry-run' in argv:
        print('\n--dry-run — 파일을 쓰지 않았다.')
        return 0
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f'\n저장: {OUT}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
