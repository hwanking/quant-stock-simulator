# -*- coding: utf-8 -*-
"""
온라인 시장정보 정기 갱신 — 사양 §1.

    C:/Python314/python.exe scripts/refresh_market_data.py            # 매일 축
    C:/Python314/python.exe scripts/refresh_market_data.py --weekly   # + 주간 축
    C:/Python314/python.exe scripts/refresh_market_data.py --all      # 전체

■ 무엇을 갱신하나
    매일   지수·환율·금리·원자재·업종 프록시 시세·변동성
    매주   글로벌/국내 섹터 성과·업종 상대강도
    분기   업종 분류(KRX-DESC) — 상장·업종 재분류 반영

■ 무엇을 갱신하지 **못하나** (사양이 요구했지만 소스가 없다)
    운임지수(SCFI/BDI 원지수) · 항만 물동량 · 메모리 현물가·재고 ·
    자동차 판매량·재고일수 · 화학 스프레드 · 정제마진 · 수주잔고 ·
    신조선가 · 실적 컨센서스 · 미국채 10년(HTTPError)

    이것들은 공개 무료 API 가 없거나 유료다. 대용 지표를 원지표인 척
    쓰지 않는다 — 각 업종의 진짜 선행지표 목록은 `sector_cycle.GROUPS`
    의 `real` 에 적어 두고, 실제 연동된 것만 `real_linked` 에 넣는다.
    화면은 둘을 갈라서 '연동 / 미연동'으로 보여 준다.

■ 결과
    `.portfolio/sector_cache/` 에 저장. 실패한 축은 **빈칸으로 남긴다** —
    직전 값이나 0 으로 메우지 않는다 (CLAUDE.md §3).
"""
import io
import json
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import sector_cycle as sc                                    # noqa: E402

REPORT = os.path.join(BASE, '.portfolio', 'market_refresh.json')


def _daily():
    """지수·환율·원자재·변동성·업종 프록시."""
    tk = {t for t, _, _ in sc.MACRO}
    for g in sc.GROUPS.values():
        tk.update(g['proxy'])
        tk.add(g['bench'])
    ok, bad = {}, {}
    for t in sorted(tk):
        t0 = time.time()
        s = sc.series(t)
        if not s:
            bad[t] = '미수신'
            print(f'  [실패] {t:10s} 미수신')
            continue
        last = max(s)
        ok[t] = dict(bars=len(s), last_date=last, last=s[last],
                     ms=int((time.time() - t0) * 1000))
        print(f'  [수신] {t:10s}{len(s):>6,}행 · 최종 {last} {s[last]:,.2f}')
    return ok, bad


def _weekly():
    """섹터 성과·상대강도 — 프록시 시세에서 파생되므로 계산만."""
    snap = sc.sector_snapshot()
    print(f"\n  {'그룹':12s}{'업종':16s}{'60일':>9s}{'상대강도':>10s}{'신선':>6s}")
    rows = {}
    for g, m in snap.items():
        if not m.get('available'):
            print(f"  {g:12s}{sc.GROUPS[g]['ko']:16s}  {m.get('why', '')[:40]}")
            continue
        rows[g] = m
        print(f"  {g:12s}{m['ko']:16s}{m['mom60']:>+8.2f}%"
              f"{(m['rs60'] if m['rs60'] is not None else 0):>+9.2f}%p"
              f"{'  O' if m.get('fresh') else '  X':>6s}")
    return rows


def _quarterly():
    """업종 분류 — 캐시를 지우고 다시 받는다."""
    p = sc._cache_path('krx_desc')
    if os.path.exists(p):
        os.remove(p)
    m = sc.industry_map()
    print(f'  업종 분류 {len(m):,}종목 · 업종 {len(set(m.values()))}종')
    unl = sorted({v for v in m.values() if not sc.group_of(v)})
    print(f'  프록시 미연동 업종 {len(unl)}종 (조정하지 않고 미연동으로 표시)')
    for u in unl[:12]:
        print(f'    · {u}')
    return dict(stocks=len(m), industries=len(set(m.values())),
                unlinked=len(unl), unlinked_sample=unl[:40])


def main():
    args = set(sys.argv[1:])
    do_all = '--all' in args
    out = dict(ran_at=time.strftime('%Y-%m-%d %H:%M:%S'))

    print('■ 매일 갱신 — 지수·환율·원자재·변동성·섹터 프록시\n')
    ok, bad = _daily()
    out['daily'] = dict(received=len(ok), failed=bad, detail=ok)
    print(f'\n  수신 {len(ok)} · 실패 {len(bad)}')
    if bad:
        print(f"  실패 축은 빈칸으로 남깁니다: {', '.join(bad)}")

    if do_all or '--weekly' in args:
        print('\n\n■ 주간 갱신 — 섹터 성과·상대강도')
        out['weekly'] = _weekly()

    if do_all or '--quarterly' in args:
        print('\n\n■ 분기 갱신 — 업종 분류')
        out['quarterly'] = _quarterly()

    print('\n\n■ 미연동 — 소스가 없어 이번에도 못 받은 것')
    miss = []
    for g, meta in sc.GROUPS.items():
        un = [x for x in meta['real'] if x not in set(meta['real_linked'])]
        if un:
            miss.append(f"{meta['ko']}: {', '.join(un[:4])}"
                        + ('…' if len(un) > 4 else ''))
    for line in miss:
        print(f'  · {line}')
    out['unlinked_real_indicators'] = miss

    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f'\n저장: {REPORT}')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
