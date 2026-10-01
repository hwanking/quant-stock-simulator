# -*- coding: utf-8 -*-
"""거래소 업종표(KSIC) 동봉본을 만든다 — 라운드 409.

■ 왜
  업황 연결(`sector_cycle.for_stock`)은 종목코드 → KSIC 업종명 표로 프록시 그룹을 찾는다. 그 표의 원천인
  FinanceDataReader `StockListing('KRX-DESC')` 가 HTTP 404 를 내고(2026-10-01 실측), 표는 로컬 캐시
  (`.portfolio/sector_cache/krx_desc.json` · gitignored)에만 남아 있다. 배포 앱은 `.portfolio/` 가 빈 채 뜨므로
  (라운드 331) 로컬 사본이 없다 — 저장소에 한 벌을 둔다.

■ 무엇을 담나
  공개 상장 목록의 **업종명**뿐이다(열쇠 = 종목코드 6자리 · 값 = KSIC 업종명). 종목명·가격·개인 자료는 없다.
  `made` 는 로컬 사본을 마지막으로 받은 날(파일 수정일)이다 — 이 스크립트를 돌린 날이 아니다.

■ 쓰는 법
  C:/Python314/python.exe scripts/ship_krx_industry.py          (미리보기)
  C:/Python314/python.exe scripts/ship_krx_industry.py --apply  (data/krx_industry_ksic.json 을 쓴다)
"""
import io
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
import sector_cycle as sc            # noqa: E402

src = sc._cache_path('krx_desc')
if not os.path.exists(src):
    print('로컬 사본이 없습니다 —', src)
    sys.exit(1)
with io.open(src, encoding='utf-8') as f:
    rows = json.load(f)
if not isinstance(rows, dict) or not rows:
    print('로컬 사본이 비어 있습니다')
    sys.exit(1)
bad = [k for k in rows if not (len(str(k)) == 6)]
made = time.strftime('%Y-%m-%d', time.localtime(os.path.getmtime(src)))
doc = dict(made=made,
           source="FinanceDataReader StockListing('KRX-DESC') · 'Industry' 칸(KSIC 업종명)",
           note='원천이 응답하지 않을 때 sector_cycle.industry_map 이 쓰는 마지막 판 · 업종명만(종목명 없음)',
           rows=dict(sorted(rows.items())))
print(f'항목 {len(rows):,} · 판 날짜 {made} · 6자리가 아닌 열쇠 {len(bad)}')
if '--apply' in sys.argv:
    with io.open(sc.SHIPPED_INDUSTRY, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=0)
    print('썼습니다 →', os.path.relpath(sc.SHIPPED_INDUSTRY, PROJ))
