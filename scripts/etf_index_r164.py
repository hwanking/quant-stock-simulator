# -*- coding: utf-8 -*-
"""ETF 이름·코드 색인을 저장소에 동봉한다 (라운드 164).

■ 왜
  사용자가 두 ETF 를 못 찾았다. 원인 하나는 코드 판별(`stock_code` 가
  고쳤다)이고, 다른 하나는 **이름으로 찾을 길이 없었다**는 것이다 —
  실측에서 네이버 검색이 '미국빅테크7' 에 **0건**을 돌려줬는데
  ETF 목록에는 8종목이 있다.

■ 무엇을 담나 · 무엇을 안 담나
  · 담는다: 코드 · 이름
  · **안 담는다: NAV·가격.** 낡은 값을 오늘 값처럼 보여 주지 않기
    위해서다. NAV 는 살아 있는 조회에서만 나오고 화면이 받은 시각을
    함께 적는다 (§3).

    C:/Python314/python.exe scripts/etf_index_r164.py
"""
import io
import os
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
os.chdir(PROJ)

import etf_registry                                            # noqa: E402
import stock_code                                              # noqa: E402


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def main():
    print('ETF 이름·코드 색인 (라운드 164)')
    doc = etf_registry.write_index()
    if not doc:
        print('■ 목록 수신 실패 — 색인을 만들지 않았다. 지어내지 않는다.')
        return 2
    print(f"■ {doc['count']:,}종목 · 문자 포함 코드 {doc['with_letter']:,}종목 "
          f"({doc['with_letter'] / doc['count'] * 100:.1f}%)")
    print(f"   기준일 {doc['made']} · {etf_registry.INDEX}")

    # 사용자가 못 찾았던 둘이 실제로 들어갔는지 확인한다 —
    # '만들었다'와 '고쳤다'는 다른 말이다.
    print()
    print('■ 사용자가 못 찾았던 종목이 색인에 있나')
    for c in ('0040Y0', '480020'):
        nm = doc['map'].get(c)
        print(f"   {c} → {nm!r}" if nm else f"   {c} → 없다 (확인 필요)")

    print()
    print('■ 이름 검색이 되나')
    for q in ('팔란티어', '미국빅테크7', '커버드콜'):
        hits = etf_registry.search(q, limit=5)
        print(f"   {q!r:12} → {len(hits)}건 " +
              (', '.join(f'{n}({c})' for c, n in hits[:3]) if hits else ''))

    print()
    print('■ NAV (살아 있는 조회 · 받은 시각을 함께 적는다)')
    for c in ('0040Y0', '480020'):
        nv = etf_registry.nav_of(c)
        if nv:
            print(f"   {c} {nv['name']} · 현재가 {nv['price']:,.0f} · "
                  f"NAV {nv['nav']:,.0f} · 괴리 {nv['premium_pct']:+.2f}% "
                  f"· {nv['at']}")
        else:
            print(f'   {c} → NAV 미수신')
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
