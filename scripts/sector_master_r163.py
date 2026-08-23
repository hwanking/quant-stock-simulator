# -*- coding: utf-8 -*-
"""업종 매핑을 연구용으로 박제하고 커버리지를 잰다 (라운드 163).

■ 왜
  R148 이래 이벤트 연구가 계속 "업종조정 없음"을 한계로 적어 왔다
  (R150 §4 · R151 · R153 · R154 · R158). 업종조정을 하려면 먼저
  **종목 → 업종 매핑이 얼마나 붙는지**를 재야 한다 — R146 이 이름→코드
  조인을 먼저 잰 것과 같은 순서다.

■ 재료
  `sector_cycle.industry_map()` 이 이미 있다 — FDR `KRX-DESC` 의
  `Industry`(KSIC 업종명)를 코드에 붙인다. 여기서는 그것을 **연구용으로
  박제**하고(재현 가능하게) 커버리지·그룹 크기를 센다.

■ ⚠️ 한계를 먼저 적는다
  · **현재 스냅샷이다.** 과거 시점의 업종이 아니다. 업종은 시총·가격과
    달리 잘 안 바뀌지만 바뀌기도 한다(사업 전환·재분류). 이벤트 연구에
    쓸 때는 이 사실을 결과에 적는다 — R160 이 현재 시총을 누출로 보고
    안 쓴 것과 같은 성격이되, 업종은 정적이라 정도가 다르다.
  · 상장폐지 종목은 KRX-DESC 에 없다 — 생존 편향(R148 §1 과 같다).
  · `group_of()` 는 정규식 규칙이라 **매칭 실패가 있다.** 그 수를 적는다.

측정 전용 — 점수·게이트·문턱을 바꾸지 않는다.

    C:/Python314/python.exe scripts/sector_master_r163.py [--refresh]
"""
import collections
import io
import json
import os
import sys
from datetime import date, datetime, timezone

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
OUT = os.path.join(PROJ, 'data', 'sector_master_r163.json')
SNAP = os.path.join(PROJ, '.portfolio', 'sector_master.json')
BARS = os.path.join(PROJ, '.portfolio', 'daily_bars.jsonl')
UNIV = os.path.join(PROJ, '.portfolio', 'universe_top1500.json')

import sector_cycle as sc                                      # noqa: E402

#: 업종 지수를 만들려면 한 업종에 최소 몇 종목이 있어야 하나.
#: 새 숫자를 만들지 않는다 — R150 이 층을 5분위로 가를 때 쓴 것과 같은
#: 생각으로, **한 칸에 최소 5종목**을 본다(분위 하나 분량).
MIN_PER_SECTOR = 5


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def main():
    refresh = '--refresh' in sys.argv
    print('업종 매핑 박제 · 커버리지 (라운드 163)')
    print('측정 전용 — 점수·게이트·문턱을 바꾸지 않는다')
    print()

    # ── 박제 ───────────────────────────────────────────────────────────
    if os.path.exists(SNAP) and not refresh:
        with open(SNAP, encoding='utf-8') as f:
            snap = json.load(f)
        print(f"■ 스냅샷 재사용 — {snap.get('made')} · "
              f"{len(snap.get('map') or {}):,}종목")
    else:
        m = sc.industry_map()
        if not m:
            print('■ 업종 수신 실패 — 지어내지 않는다. 박제하지 않았다.')
            return 2
        snap = {'made': date.today().isoformat(), 'source': 'FDR KRX-DESC',
                'field': 'Industry (KSIC 업종명)', 'map': m}
        os.makedirs(os.path.dirname(SNAP), exist_ok=True)
        with open(SNAP, 'w', encoding='utf-8') as f:
            json.dump(snap, f, ensure_ascii=False)
        print(f"■ 새로 박제 — {snap['made']} · {len(m):,}종목")

    imap = snap['map']

    # ── 커버리지: 일봉이 있는 유니버스 주식 기준 ───────────────────────
    stocks, mkt = [], {}
    with open(BARS, encoding='utf-8') as f:
        for ln in f:
            r = json.loads(ln)
            if r.get('bars') and r.get('mkt') != 'INDEX':
                stocks.append(r['code'])
                mkt[r['code']] = r['mkt']
    have = [c for c in stocks if imap.get(c)]
    print()
    print(f"■ 커버리지 — 일봉 있는 주식 {len(stocks):,}종목")
    print(f"   업종이 붙는 것 {len(have):,} "
          f"({len(have) / len(stocks) * 100:.1f}%)")
    miss = [c for c in stocks if not imap.get(c)]
    if miss:
        print(f"   안 붙는 것 {len(miss):,} — 앞 8개 {miss[:8]}")

    # ── 업종 크기 ──────────────────────────────────────────────────────
    by_ind = collections.Counter(imap[c] for c in have)
    big = {k: v for k, v in by_ind.items() if v >= MIN_PER_SECTOR}
    cov_big = sum(big.values())
    print()
    print(f"■ 업종 {len(by_ind):,}개 · {MIN_PER_SECTOR}종목 이상인 업종 "
          f"{len(big):,}개")
    print(f"   그 업종들이 담는 종목 {cov_big:,} "
          f"({cov_big / len(stocks) * 100:.1f}% of 전체)")
    print("   큰 업종 상위 8:")
    for k, v in by_ind.most_common(8):
        print(f"      {v:>4}  {k}")
    tiny = sum(1 for v in by_ind.values() if v < MIN_PER_SECTOR)
    print(f"   {MIN_PER_SECTOR}종목 미만 업종 {tiny:,}개 — 업종 지수를 "
          f"만들 수 없다")

    # ── 프록시 그룹 (sector_cycle.group_of) ────────────────────────────
    grp = collections.Counter()
    nogrp = 0
    for c in have:
        g = sc.group_of(imap[c])
        if g:
            grp[g] += 1
        else:
            nogrp += 1
    print()
    print(f"■ 프록시 그룹(group_of) — 매칭 {sum(grp.values()):,} · "
          f"실패 {nogrp:,} ({nogrp / len(have) * 100:.1f}%)")
    for k, v in grp.most_common():
        print(f"      {v:>4}  {k}")
    print("   ※ group_of 는 정규식 규칙이라 실패가 있다. 업종조정에는 "
          "그룹보다 **업종명 자체**를 쓰는 것이 커버리지가 높다.")

    # ── 시장별 ─────────────────────────────────────────────────────────
    by_mkt = collections.Counter(mkt[c] for c in have)
    print()
    print("■ 시장별 업종 보유: " + ' · '.join(
        f'{k} {v:,}' for k, v in by_mkt.items()))

    ok = len(have) / len(stocks) >= 0.90
    print()
    print(f"■ 판정: 업종조정 연구를 {'열 수 있다' if ok else '열기 어렵다'} "
          f"— 커버리지 {len(have) / len(stocks) * 100:.1f}%")

    doc = {
        'made': date.today().isoformat(),
        'made_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'snapshot_made': snap.get('made'), 'source': snap.get('source'),
        'field': snap.get('field'),
        'mapped_total': len(imap),
        'universe_stocks': len(stocks), 'with_sector': len(have),
        'coverage_pct': round(len(have) / len(stocks) * 100, 1),
        'sectors': len(by_ind), 'min_per_sector': MIN_PER_SECTOR,
        'sectors_big_enough': len(big),
        'stocks_in_big_sectors': cov_big,
        'sectors_too_small': tiny,
        'top_sectors': by_ind.most_common(20),
        'group_matched': sum(grp.values()), 'group_failed': nogrp,
        'groups': dict(grp), 'by_market': dict(by_mkt),
        'ready': ok,
        'note': ('측정 전용 — 점수·게이트·문턱을 바꾸지 않는다. '
                 '⚠️ 현재 스냅샷이라 과거 시점 업종이 아니다(업종은 정적에 '
                 '가깝지만 바뀌기도 한다) · 상장폐지 종목은 없다(생존 편향) '
                 '· group_of 는 정규식이라 매칭 실패가 있다. 이 셋을 쓰는 '
                 '연구는 결과에 그대로 적는다.'),
    }
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f'\n저장: {OUT} · 스냅샷 {SNAP}')
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
