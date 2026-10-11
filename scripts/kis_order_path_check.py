# -*- coding: utf-8 -*-
"""한국투자 주문 경로 점검 — **주문은 안 낸다** (라운드 491).

실주문 한 번에 워커가 부르는 증권사 호출 중 조회 셋(잔고 · 주문·체결 내역 · 매수가능)을 실제로 불러 응답을 읽는지 본다.
매수·취소 주문은 보내야만 확인되므로 부르지 않고 그렇다고 적는다. 물어볼 종목·가격은 자동매매 장부의 가장 최근 계획 진입가다
(장부는 읽기 전용으로 연다). 금액·계좌번호는 찍지 않는다. 규칙은 `broker_kis.KisBroker.order_path_check` 한 곳이다(화면의
'주문 경로 점검' 버튼과 같은 함수).

    C:/Python314/python.exe scripts/kis_order_path_check.py
"""
import os
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:                                          # noqa: BLE001
        pass
    import broker_kis
    import swing_ledger as L
    cfg = broker_kis.load_config()
    if not cfg or cfg.get('missing'):
        print('연결 정보가 없다 — 스윙 칸 시스템 → 설정에서 넣는다(증권사를 부르지 않았다)')
        return 2
    code = price = None
    if os.path.exists(L.PATH):
        c = L.connect(readonly=True)
        try:
            ps = [p for p in L.plans(c) if p.get('entry')]
        finally:
            c.close()
        if ps:
            code, price = ps[-1].get('code'), ps[-1].get('entry')
    res = broker_kis.KisBroker(cfg).order_path_check(code, price)
    print(f"한국투자 주문 경로 점검 — {cfg.get('env')} · 주문은 안 냈다")
    mark = {True: '통과', False: '실패', None: '안 부름'}
    for r in res:
        print(f"  [{mark[r['ok']]}] {r['step']} — {r['detail']}")
    return 1 if any(r['ok'] is False for r in res) else 0


if __name__ == '__main__':
    sys.exit(main())
