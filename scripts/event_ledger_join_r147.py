# -*- coding: utf-8 -*-
"""R147 — 주주환원 공시는 같은 날 케이스를 가르는가 (원장 조인).

사전등록: docs/PREREG_R147_EVENT_LEDGER_JOIN.md (측정 전 커밋).
판정 기준은 저 문서 §4 에 있고, 이 스크립트는 그 값을 그대로 묻는다 —
여기서 바꾸면 §106 류의 이중 경로다.

  주 시험: 신선도 5거래일 · 같은 날 ΔH(이벤트−비이벤트 적중률) 의
           부호검정 · 양측 |z| ≥ 1.96 · 개발 구간(train+valid)
  표본 조건: 이벤트 케이스 ≥ 1,000 그리고 유효 날짜 ≥ 300
  부 시험(판정에 안 씀): 신선도 1/3/10/20 · Δ비용후 EV

측정 전용 — 점수·게이트·문턱을 바꾸지 않는다.

    C:/Python314/python.exe scripts/event_ledger_join_r147.py
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
OUT = os.path.join(PROJ, 'data', 'event_ledger_join_r147.json')
LEDGER = os.path.join(PROJ, '.portfolio', 'virtual_graded.jsonl')
DISC = os.path.join(PROJ, '.portfolio', 'disclosures_daily.jsonl')
MASTER = os.path.join(PROJ, '.portfolio', 'name_master.json')

import disclosure_types as dt                                  # noqa: E402

BUY = 58.0                     # R49 사전등록 §2 의 채택값 — 새 숫자 아님
EVENT_TYPE = '자사주·배당'      # 사전등록 §1 — 이 하나만
MAIN_FRESH = 5                 # 사전등록 §2 — 주 시험 신선도(거래일)
SUB_FRESH = (1, 3, 10, 20)     # 부 시험 — 기술 통계만
Z_CRIT = 1.96                  # 사전등록 §4 — 주 시험 1개, 양측
MIN_CASES = 1000               # 사전등록 §4 — 케이스 조건
MIN_DAYS = 300                 # 사전등록 §4 — 날짜 조건 (함께 건다)

_STRIP = re.compile(r'\s+|㈜|\(주\)|주식회사')


def norm(name):
    return _STRIP.sub('', str(name)).upper()


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def sign_test(diffs):
    """R110 과 같은 부호검정 — 0 제외, win = 양수 날."""
    nz = [d for d in diffs if d != 0]
    n = len(nz)
    if n == 0:
        return None, 0, 0
    win = sum(1 for d in nz if d > 0)
    z = (win - n / 2) / math.sqrt(n / 4)
    return round(z, 2), win, n


def main():
    print('R147 — 주주환원 공시는 같은 날 케이스를 가르는가')
    print('사전등록: docs/PREREG_R147_EVENT_LEDGER_JOIN.md')
    print('측정 전용 — 점수·게이트·문턱을 바꾸지 않는다')
    print()

    # ── 이름 → 코드 (R146 규칙: 정규화 정확 · 충돌 제외) ────────────────
    with open(MASTER, encoding='utf-8') as f:
        m = json.load(f)
    n2c = collections.defaultdict(set)
    for r in m['rows']:
        n2c[norm(r['name'])].add(r['code'])
    collide = {k for k, v in n2c.items() if len(v) > 1}
    name2code = {k: next(iter(v)) for k, v in n2c.items() if len(v) == 1}
    print(f"■ 이름 마스터 {len(m['rows']):,}행 · 충돌 제외 {len(collide)}개"
          f" (스냅샷 {m['made']})")

    # ── 공시 → (코드, 날짜) — 대상 유형만 ──────────────────────────────
    ev_days = collections.defaultdict(set)      # code -> {'YYYY-MM-DD'}
    ev_rows = 0
    with open(DISC, encoding='utf-8', errors='replace') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:                                  # noqa: BLE001
                continue
            if dt.classify(r.get('title')) != EVENT_TYPE:
                continue
            code = name2code.get(norm(r.get('name') or ''))
            if not code:
                continue
            d = str(r.get('day') or '')[:10]
            if len(d) == 10:
                ev_days[code].add(d)
                ev_rows += 1
    print(f"■ '{EVENT_TYPE}' 공시 중 코드가 붙은 것 {ev_rows:,}건 · "
          f"{len(ev_days):,}종목")

    # ── 원장 — 매수권 · 개발 구간 ──────────────────────────────────────
    cases = []
    all_days = set()
    with open(LEDGER, encoding='utf-8', errors='replace') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:                                  # noqa: BLE001
                continue
            d = str(r.get('date') or '')[:10]
            if len(d) == 10:
                all_days.add(d)
            if r.get('score') is None or float(r['score']) < BUY:
                continue
            if r.get('success') is None or r.get('return_pct') is None:
                continue
            cases.append((d, str(r.get('ticker') or '').split('.')[0],
                          bool(r['success']), float(r['return_pct']),
                          str(r.get('split') or '')))
    cal = sorted(all_days)
    print(f"■ 원장 거래일 달력 {len(cal):,}일 · 매수권 케이스 "
          f"{len(cases):,}건 (2026-08-21 기준)")

    def fresh(code, d, k):
        """케이스일 d 기준 D-k ~ D-1 (거래일) 에 공시가 있었나."""
        days = ev_days.get(code)
        if not days:
            return False
        i = bisect.bisect_left(cal, d)
        lo = max(0, i - k)
        return any(cal[j] in days for j in range(lo, i))

    # ── 잣대: 같은 날 E vs N (개발 구간) ────────────────────────────────
    def run(k, splits=('train', 'valid')):
        by_day = collections.defaultdict(lambda: {'E': [], 'N': []})
        for d, code, suc, ret, sp in cases:
            if sp not in splits:
                continue
            by_day[d]['E' if fresh(code, d, k) else 'N'].append((suc, ret))
        dh, dev = [], []
        n_ev = 0
        for d, b in by_day.items():
            if not b['E'] or not b['N']:
                continue
            n_ev += len(b['E'])
            hr_e = sum(1 for s, _ in b['E'] if s) / len(b['E'])
            hr_n = sum(1 for s, _ in b['N'] if s) / len(b['N'])
            dh.append(hr_e - hr_n)
            dev.append(sum(r for _, r in b['E']) / len(b['E'])
                       - sum(r for _, r in b['N']) / len(b['N']))
        z, win, n = sign_test(dh)
        return dict(fresh_days=k, event_cases=n_ev, valid_days=len(dh),
                    dh_median=round(sorted(dh)[len(dh) // 2], 4) if dh else None,
                    dh_mean_pp=round(sum(dh) / len(dh) * 100, 2) if dh else None,
                    dev_mean_pp=round(sum(dev) / len(dev), 3) if dev else None,
                    sign_win=win, sign_n=n, sign_z=z)

    main_r = run(MAIN_FRESH)
    print()
    print(f"■ 주 시험 — 신선도 {MAIN_FRESH}거래일 · 개발 구간")
    print(f"   이벤트 케이스 {main_r['event_cases']:,} · "
          f"유효 날짜 {main_r['valid_days']:,}")
    print(f"   ΔH 평균 {main_r['dh_mean_pp']}%p · "
          f"ΔEV 평균 {main_r['dev_mean_pp']}%p · "
          f"부호검정 z = {main_r['sign_z']} "
          f"({main_r['sign_win']}/{main_r['sign_n']})")

    ok_sample = (main_r['event_cases'] >= MIN_CASES
                 and main_r['valid_days'] >= MIN_DAYS)
    ok_z = main_r['sign_z'] is not None and abs(main_r['sign_z']) >= Z_CRIT
    if not ok_sample:
        verdict = '표본 미달 — 판정 보류 (기준을 내리지 않는다)'
    elif ok_z:
        verdict = ('통과 — blind 확인이 남는다' if main_r['sign_z'] > 0
                   else '방향 반대로 유의 — 채택하지 않는다 (R44 전례)')
    else:
        verdict = '미달 — 기각, 현행 유지'
    print(f"   판정: {verdict}")

    subs = [run(k) for k in SUB_FRESH]
    print()
    print("■ 부 시험 (판정에 쓰지 않는다 — 기술 통계)")
    for s in subs:
        print(f"   신선도 {s['fresh_days']:>2}일: 케이스 "
              f"{s['event_cases']:>6,} · 날짜 {s['valid_days']:>5,} · "
              f"ΔH {s['dh_mean_pp']}%p · z {s['sign_z']}")

    blind = None
    if ok_sample and ok_z and main_r['sign_z'] > 0:
        blind = run(MAIN_FRESH, splits=('blind',))
        print()
        print(f"■ blind 확인 (개발 구간 통과 시에만 — 사전등록 §4)")
        print(f"   케이스 {blind['event_cases']:,} · 날짜 "
              f"{blind['valid_days']:,} · ΔH {blind['dh_mean_pp']}%p · "
              f"z {blind['sign_z']}")

    doc = {
        'made': date.today().isoformat(),
        'made_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'prereg': 'docs/PREREG_R147_EVENT_LEDGER_JOIN.md',
        'event_type': EVENT_TYPE,
        'criteria': dict(z_crit=Z_CRIT, min_cases=MIN_CASES,
                         min_days=MIN_DAYS, main_fresh=MAIN_FRESH,
                         buy=BUY),
        'joined_event_rows': ev_rows,
        'joined_event_stocks': len(ev_days),
        'ledger_cases_buy': len(cases),
        'calendar_days': len(cal),
        'main': main_r,
        'sample_ok': ok_sample,
        'z_ok': ok_z,
        'verdict': verdict,
        'subs': subs,
        'blind': blind,
        'note': ('측정 전용 — 점수·게이트·문턱을 바꾸지 않는다. '
                 '원장 mfe/mae 미사용. D0 공시 제외(누출 차단).'),
    }
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print()
    print(f'저장: {OUT}')
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
