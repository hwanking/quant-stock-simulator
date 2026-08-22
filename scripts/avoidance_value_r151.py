# -*- coding: utf-8 -*-
"""R151 — 회피 규칙에 값이 있는가: 순수 창의 발견이 원장으로 옮겨지는가.

사전등록: docs/PREREG_R151_AVOIDANCE_VALUE.md (측정 전 커밋).
판정 기준은 그 문서 §4 의 값을 그대로 묻는다.

  이벤트 케이스 = D-5 ~ D-1 거래일에 해당 유형 공시가 있던 매수권 케이스
  ΔH(d) = 적중률(이벤트) − 적중률(비이벤트), 같은 날 안에서
  시험 A(7유형) · B(6유형, IR·안내 제외) 둘 다 주 시험
  문턱 Bonferroni 2 → z 2.25 · 이벤트 ≥1,000 그리고 날짜 ≥300

**자기검사(§5)**: R147 설정(원장 달력·자사주·배당·D-5·개발)을 재현해
ΔH -1.69%p · z 0.78 을 내야 한다. 못 하면 측정을 중단한다.

측정 전용 — 점수·게이트·문턱을 바꾸지 않는다.

    C:/Python314/python.exe scripts/avoidance_value_r151.py
"""
import bisect
import collections
import io
import json
import math
import os
import re
import sys
from datetime import date, datetime, timezone

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
OUT = os.path.join(PROJ, 'data', 'avoidance_value_r151.json')
LEDGER = os.path.join(PROJ, '.portfolio', 'virtual_graded.jsonl')
DISC = os.path.join(PROJ, '.portfolio', 'disclosures_daily.jsonl')
BARS = os.path.join(PROJ, '.portfolio', 'daily_bars.jsonl')
MASTER = os.path.join(PROJ, '.portfolio', 'name_master.json')

import disclosure_types as dt                                  # noqa: E402

ALL7 = ('자사주·배당', '수주·공급계약', '증자·CB·BW', '투자·설비',
        'M&A·분할', 'IR·안내', '인허가·임상')
MATERIAL6 = tuple(t for t in ALL7 if t != 'IR·안내')   # 사전등록 §2 — 시험 B
BUY = 58.0                     # R49 채택값 — 새 숫자 아님
FRESH = 5                      # §2 — D-5 ~ D-1
SUB_FRESH = (1, 3, 10, 20)     # §5 — 민감도
Z_CRIT = 2.25                  # §4 — Bonferroni 2, 올림
MIN_EVENTS = 1000              # §4
MIN_DAYS = 300                 # §4
#: §5 자기검사 — R147 이 발표한 값
R147_DH, R147_Z = -1.69, 0.78
TOL_DH, TOL_Z = 0.01, 0.01

_STRIP = re.compile(r'\s+|㈜|\(주\)|주식회사')


def norm(name):
    return _STRIP.sub('', str(name)).upper()


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def sign_test(vals):
    nz = [v for v in vals if v != 0]
    n = len(nz)
    if n == 0:
        return None, 0, 0
    win = sum(1 for v in nz if v > 0)
    return round((win - n / 2) / math.sqrt(n / 4), 2), win, n


def need_p(n):
    return round((0.5 + Z_CRIT / (2 * math.sqrt(n))) * 100, 1) if n else None


def main():
    print('R151 — 회피 규칙에 값이 있는가 (순수 창 → 원장)')
    print('사전등록: docs/PREREG_R151_AVOIDANCE_VALUE.md')
    print('측정 전용 — 점수·게이트·문턱을 바꾸지 않는다')
    print()

    # ── 일봉 달력 ──────────────────────────────────────────────────────
    bar_days = {}
    with open(BARS, encoding='utf-8') as f:
        for ln in f:
            r = json.loads(ln)
            if r.get('bars') and r['mkt'] != 'INDEX':
                bar_days[r['code']] = [b[0] for b in r['bars']]

    # ── 이름 → 코드 (R146) ─────────────────────────────────────────────
    with open(MASTER, encoding='utf-8') as f:
        m = json.load(f)
    n2c = collections.defaultdict(set)
    for r in m['rows']:
        n2c[norm(r['name'])].add(r['code'])
    name2code = {k: next(iter(v)) for k, v in n2c.items() if len(v) == 1}

    # ── 공시 (유형별 · 코드 → 접수일 집합) ─────────────────────────────
    ev_raw = {t: collections.defaultdict(set) for t in ALL7}
    for ln in open(DISC, encoding='utf-8', errors='replace'):
        ln = ln.strip()
        if not ln:
            continue
        try:
            r = json.loads(ln)
        except Exception:                                      # noqa: BLE001
            continue
        t = dt.classify(r.get('title'))
        if t not in ALL7:
            continue
        code = name2code.get(norm(r.get('name') or ''))
        if not code:
            continue
        d = str(r.get('day') or '')[:10]
        if len(d) == 10:
            ev_raw[t][code].add(d)
    print('■ 공시(코드 붙은 것): '
          + ' · '.join(f'{t} {sum(len(v) for v in ev_raw[t].values()):,}'
                       for t in ALL7))

    # ── 원장 ───────────────────────────────────────────────────────────
    cases = []
    ledger_days = set()
    for ln in open(LEDGER, encoding='utf-8', errors='replace'):
        ln = ln.strip()
        if not ln:
            continue
        try:
            r = json.loads(ln)
        except Exception:                                      # noqa: BLE001
            continue
        d = str(r.get('date') or '')[:10]
        if len(d) == 10:
            ledger_days.add(d)
        if r.get('score') is None or float(r['score']) < BUY:
            continue
        if r.get('success') is None or r.get('return_pct') is None:
            continue
        cases.append((d, str(r.get('ticker') or '').split('.')[0],
                      bool(r['success']), float(r['return_pct']),
                      str(r.get('split') or '')))
    ledger_cal = sorted(ledger_days)
    print(f'■ 매수권 케이스 {len(cases):,}건 · 원장 달력 '
          f'{len(ledger_cal):,}일 · 일봉 종목 {len(bar_days):,}')

    def flagged(code, d, types, k, cal_mode):
        """D-k ~ D-1 거래일에 types 중 하나라도 공시가 있었나."""
        if cal_mode == 'bars':
            cal = bar_days.get(code)
            if not cal:
                return None                     # 일봉 없음 — 판정 불가
        else:
            cal = ledger_cal
        i = bisect.bisect_left(cal, d)
        prev = set(cal[max(0, i - k):i])
        if not prev:
            return False
        for t in types:
            if prev & ev_raw[t].get(code, set()):
                return True
        return False

    def run(types, k=FRESH, cal_mode='bars', splits=('train', 'valid')):
        by_day = collections.defaultdict(lambda: {'E': [], 'N': []})
        skipped = 0
        for d, code, suc, ret, sp in cases:
            if sp not in splits:
                continue
            f = flagged(code, d, types, k, cal_mode)
            if f is None:
                skipped += 1
                continue
            by_day[d]['E' if f else 'N'].append((suc, ret))
        dh, dev = [], []
        n_ev = 0
        for d, b in by_day.items():
            if not b['E'] or not b['N']:
                continue
            n_ev += len(b['E'])
            hr_e = sum(1 for s, _ in b['E'] if s) / len(b['E'])
            hr_n = sum(1 for s, _ in b['N'] if s) / len(b['N'])
            dh.append((hr_e - hr_n) * 100)
            dev.append(sum(r for _, r in b['E']) / len(b['E'])
                       - sum(r for _, r in b['N']) / len(b['N']))
        z, win, n = sign_test(dh)
        return dict(event_cases=n_ev, valid_days=len(dh), skipped=skipped,
                    dh_mean_pp=round(sum(dh) / len(dh), 3) if dh else None,
                    dh_median_pp=(round(sorted(dh)[len(dh) // 2], 3)
                                  if dh else None),
                    dev_mean_pp=round(sum(dev) / len(dev), 3) if dev else None,
                    win_pct=round(win / n * 100, 1) if n else None,
                    need_pct=need_p(n), sign_z=z, sign_win=win, sign_n=n)

    # ── 자기검사 (사전등록 §5) ─────────────────────────────────────────
    print()
    print('■ 자기검사 — R147 설정을 재현하는가 (§5)')
    chk = run(('자사주·배당',), k=5, cal_mode='ledger')
    ok_dh = (chk['dh_mean_pp'] is not None
             and abs(chk['dh_mean_pp'] - R147_DH) <= TOL_DH + 1e-9)
    ok_z = (chk['sign_z'] is not None
            and abs(chk['sign_z'] - R147_Z) <= TOL_Z + 1e-9)
    print(f"   {'OK ' if ok_dh else '!! '}ΔH  재현 {chk['dh_mean_pp']} · "
          f"R147 {R147_DH}")
    print(f"   {'OK ' if ok_z else '!! '}z   재현 {chk['sign_z']} · "
          f"R147 {R147_Z}")
    if not (ok_dh and ok_z):
        print()
        print('■ 재현 실패 — 측정을 중단한다 (사전등록 §5). '
              '허용 오차를 늘리지 않는다.')
        return 2

    # ── 주 시험 A · B ──────────────────────────────────────────────────
    tests = (('A_전체7유형', ALL7), ('B_내용6유형', MATERIAL6))
    results = {}
    print()
    print(f'{"시험":<14}{"이벤트":>8}{"날짜":>7}{"ΔH평균":>9}{"ΔH중앙":>9}'
          f'{"ΔEV":>8}{"승률":>7}{"필요":>7}{"z":>7}  판정')
    for name, types in tests:
        dev = run(types)
        sample_ok = (dev['event_cases'] >= MIN_EVENTS
                     and dev['valid_days'] >= MIN_DAYS)
        z_ok = dev['sign_z'] is not None and abs(dev['sign_z']) >= Z_CRIT
        if not sample_ok:
            verdict = '표본 미달'
        elif z_ok:
            verdict = ('옮겨진다 — 회피에 값이 있다' if dev['sign_z'] < 0
                       else '방향 반대 — 채택하지 않는다')
        else:
            verdict = '미달 — 기각, 옮겨지지 않는다'
        blind = run(types, splits=('blind',)) if (sample_ok and z_ok) else None
        results[name] = dict(dev=dev, sample_ok=sample_ok, z_ok=z_ok,
                             verdict=verdict, blind=blind,
                             types=list(types))
        print(f'{name:<14}{dev["event_cases"]:>8,}{dev["valid_days"]:>7,}'
              f'{(dev["dh_mean_pp"] or 0):>9.3f}{(dev["dh_median_pp"] or 0):>9.3f}'
              f'{(dev["dev_mean_pp"] or 0):>8.3f}{(dev["win_pct"] or 0):>6.1f}%'
              f'{(dev["need_pct"] or 0):>6.1f}%'
              f'{(dev["sign_z"] if dev["sign_z"] is not None else 0):>7.2f}'
              f'  {verdict}')

    passed = [n for n, r in results.items() if r['sample_ok'] and r['z_ok']]
    print()
    if passed:
        print('■ blind 확인 (개발이 통과한 시험만 — 사전등록 §4)')
        for n in passed:
            b = results[n]['blind']
            print(f"   {n}: 이벤트 {b['event_cases']:,} · 날짜 "
                  f"{b['valid_days']} · ΔH {b['dh_mean_pp']}%p · "
                  f"z {b['sign_z']}")
    else:
        print('■ 통과한 시험이 없다 — blind 를 열지 않는다')

    # ── 민감도 (판정에 쓰지 않는다) ────────────────────────────────────
    print()
    print('■ 민감도 (판정에 쓰지 않는다 — 사전등록 §5)')
    sens = {}
    for name, types in tests:
        led = run(types, cal_mode='ledger')
        subs = {str(k): run(types, k=k) for k in SUB_FRESH}
        sens[name] = dict(ledger_calendar=led, sub_windows=subs)
        print(f'   {name:<14} 원장달력 z {led["sign_z"]}  ·  창 '
              + ' · '.join(f'D-{k}: {subs[str(k)]["sign_z"]}'
                           for k in SUB_FRESH))

    doc = {
        'made': date.today().isoformat(),
        'made_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'prereg': 'docs/PREREG_R151_AVOIDANCE_VALUE.md',
        'criteria': dict(z_crit=Z_CRIT, min_events=MIN_EVENTS,
                         min_days=MIN_DAYS, fresh=FRESH, buy=BUY,
                         n_tests=len(tests), r147_dh=R147_DH, r147_z=R147_Z,
                         tol_dh=TOL_DH, tol_z=TOL_Z),
        'ledger_cases_buy': len(cases),
        'self_check': dict(dh=chk['dh_mean_pp'], z=chk['sign_z'],
                           r147_dh=R147_DH, r147_z=R147_Z, passed=True),
        'tests': results, 'passed': passed, 'sensitivity': sens,
        'note': ('측정 전용 — 점수·게이트·문턱을 바꾸지 않는다. '
                 'R147 이 자사주·배당 한 유형으로 같은 잣대를 이미 돌려 '
                 '기각했다(z 0.78) — 이것은 두 번째 시도이고 그 사실을 '
                 '결과 문서에 적는다. 원장 mfe/mae 미사용. D0 제외.'),
    }
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print()
    print(f'저장: {OUT}')
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
