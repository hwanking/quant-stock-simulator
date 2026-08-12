# -*- coding: utf-8 -*-
"""
라운드 74 — 커버리지 점검 (빠진 곳과 **그 사유**를 함께 낸다).

■ 왜 사유까지 내나
  이 라운드에서 커버리지 숫자만 보고 두 번 틀렸다.
    · 돌파 89.9% 를 '미완' 으로 읽었다 → blind·OPEN 을 뺀 정상값이었다
    · 섹터를 패치 파일에서만 세어 '96.8% 미기록' 이라 했다 → 확장분은
      원장에 직접 갖고 있었다
  **못 채운 것과 원래 못 채우는 것은 다르다.** 숫자만 내면 그 둘이
  같은 색으로 보인다. 그래서 빈 곳마다 사유를 붙인다.

    C:/Python314/python.exe scripts/coverage_report.py
"""
import glob
import io
import json
import os
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(PROJ, '.portfolio')
LEDGER = os.path.join(P, 'virtual_graded.jsonl')


def _utf8_stdout():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def keys(pattern, need=None):
    """패턴의 (종목,날짜) 집합. need 를 주면 그 필드가 있는 행만."""
    out = set()
    for path in sorted(glob.glob(os.path.join(P, pattern))):
        with open(path, encoding='utf-8', errors='replace') as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    q = json.loads(ln)
                except Exception:                              # noqa: BLE001
                    continue
                if need and not q.get(need):
                    continue
                out.add((str(q.get('ticker')), str(q.get('date'))[:10]))
    return out


def main():
    rows = []
    with open(LEDGER, encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                try:
                    rows.append(json.loads(ln))
                except Exception:                              # noqa: BLE001
                    pass
    led = {(str(r.get('ticker')), str(r.get('date'))[:10]): r for r in rows}
    n = len(led)
    print(f'원장 {n:,}건\n')

    # ── 파생층 ────────────────────────────────────────────────────────
    print('■ 파생층 커버리지')
    for name, pat in (('경로 (bar_paths)', 'bar_paths_s*.jsonl'),
                      ('진입 기준선', 'entry_anchors_s*.jsonl'),
                      ('돌파 플래그', 'breakout_flags_s*.jsonl')):
        have = keys(pat)
        miss = set(led) - have
        why = {'blind (봉인)': 0, 'OPEN (채점 미완)': 0, '설명 안 됨': 0}
        for k in miss:
            r = led[k]
            if r.get('split') == 'blind':
                why['blind (봉인)'] += 1
            elif r.get('outcome') == 'OPEN':
                why['OPEN (채점 미완)'] += 1
            else:
                why['설명 안 됨'] += 1
        pct = len(have & set(led)) / n * 100
        print(f'  {name:20s} {len(have & set(led)):>7,}/{n:,} ({pct:5.1f}%)'
              f' · 빈 곳 {len(miss):,}')
        for k, v in why.items():
            if v:
                mark = '  ← 채울 수 있다' if k == '설명 안 됨' else ''
                print(f'      {k:18s} {v:>7,}{mark}')

    # ── 섹터 (두 곳을 다 본다) ────────────────────────────────────────
    sec = keys('subscore_patch*.jsonl', need='sector')
    sec |= {k for k, r in led.items() if r.get('sector')}
    miss = set(led) - sec
    print(f'\n■ 섹터  {len(sec):,}/{n:,} ({len(sec) / n * 100:.1f}%) · '
          f'빈 곳 {len(miss):,}')
    tks = sorted({t for t, _ in miss})
    print(f'    빈 곳 종목 {len(tks):,}개')
    if tks:
        print(f'    예: {", ".join(tks[:8])}')
    print('    ※ ETF·펀드는 업종이 원래 없다 — 지어내지 않는다')

    # ── 국면 ──────────────────────────────────────────────────────────
    rg_miss = [k for k, r in led.items()
               if r.get('regime') in (None, 'None', '')]
    print(f'\n■ 국면  {n - len(rg_miss):,}/{n:,} '
          f'({(n - len(rg_miss)) / n * 100:.1f}%) · 빈 곳 {len(rg_miss):,}')
    if rg_miss:
        ds = sorted(d for _t, d in rg_miss)
        print(f'    빈 곳 날짜 {ds[0]} ~ {ds[-1]}')
        print('    ※ 지수 시계열이 2014-05 부터라 그 이전은 원리적으로 못 잰다')

    # ── 전방 ──────────────────────────────────────────────────────────
    fwd = [r for r in rows if str(r.get('date'))[:10] >= '2026-08-09']
    print(f'\n■ 전방 전용 평가  {len(fwd):,}건')
    print('    ※ 백필로 만들 수 없다 — 시간이 쌓아야 하는 숫자다')
    return 0


if __name__ == '__main__':
    _utf8_stdout()
    sys.exit(main())
