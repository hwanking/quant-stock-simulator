# -*- coding: utf-8 -*-
"""ETF 구성종목·비중을 박제한다 (라운드 167).

사전등록: `docs/PREREG_R167_ETF_LOOKTHROUGH.md`

■ 재료
  WiseReport ETF 페이지가 `var CU_data = {"grid_data":[...]}` 를 **HTML 안에
  그대로** 담고 있다 (실측). 각 행은

      {"TRD_DT":"2026-08-21","AGMT_STK_CNT":6924.0,
       "STK_NM_KOR":"삼성전자","ETF_WEIGHT":35.37}

  ⚠️ **코드가 없고 이름만 준다.** 조인은 측정 스크립트가 하고, 여기서는
     받은 그대로 박제만 한다 — 수집과 해석을 섞지 않는다.

    C:/Python314/python.exe scripts/etf_holdings_r167.py [--limit 200]
"""
import argparse
import io
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
os.chdir(PROJ)

import etf_registry                                            # noqa: E402

#: 원시 수집물(6MB)은 `.portfolio/` 에 둔다 — 저장소에 넣지 않는다.
#: 이 스크립트가 10분에 다시 만든다. 저장소에 들어가는 것은 그것으로부터
#: 유도한 `data/etf_lookthrough_r167.json`(97KB) 하나다.
OUT = os.path.join(PROJ, '.portfolio', 'etf_holdings_r167.json')
URL = 'https://navercomp.wisereport.co.kr/v2/ETF/index.aspx?cmp_cd={code}'
HDRS = {'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                       'AppleWebKit/537.36'),
        'Referer': 'https://finance.naver.com/'}

_RE_CU = re.compile(r'var\s+CU_data\s*=\s*(\{.*?\});', re.DOTALL)


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def fetch_holdings(code, timeout=12):
    """한 ETF 의 구성종목. 실패하면 None — 지어내지 않는다 (§3)."""
    try:
        req = urllib.request.Request(URL.format(code=code), headers=HDRS)
        raw = urllib.request.urlopen(req, timeout=timeout).read()
    except Exception:                                          # noqa: BLE001
        return None
    html = None
    for enc in ('utf-8', 'euc-kr', 'cp949'):
        try:
            html = raw.decode(enc)
            break
        except Exception:                                      # noqa: BLE001
            continue
    if not html:
        return None
    m = _RE_CU.search(html)
    if not m:
        return None
    try:
        doc = json.loads(m.group(1))
    except Exception:                                          # noqa: BLE001
        return None
    rows = doc.get('grid_data') or []
    out = []
    for r in rows:
        nm = str(r.get('STK_NM_KOR') or '').strip()
        if not nm:
            continue
        try:
            w = float(r.get('ETF_WEIGHT'))
        except (TypeError, ValueError):
            w = None                    # 비중 미기재 — 0 으로 채우지 않는다
        try:
            q = float(r.get('AGMT_STK_CNT'))
        except (TypeError, ValueError):
            q = None
        out.append({'name': nm, 'weight': w, 'qty': q,
                    'at': str(r.get('TRD_DT') or '')[:10]})
    return out or None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0,
                    help='0 이면 전부')
    ap.add_argument('--sleep', type=float, default=0.25)
    a = ap.parse_args()

    print('ETF 구성종목 수집 (라운드 167)')
    print('사전등록: docs/PREREG_R167_ETF_LOOKTHROUGH.md')
    print('측정 전용 — 점수·게이트·문턱을 바꾸지 않는다\n')

    idx = etf_registry.index()
    if not idx:
        print('■ ETF 색인 없음 — scripts/etf_index_r164.py 를 먼저 돌린다')
        return 2
    codes = sorted(idx)
    if a.limit:
        codes = codes[:a.limit]
    print(f'■ 대상 {len(codes):,}종목')

    got, miss = {}, []
    t0 = time.time()
    for i, c in enumerate(codes, 1):
        h = fetch_holdings(c)
        if h:
            got[c] = h
        else:
            miss.append(c)
        if i % 50 == 0 or i == len(codes):
            print(f'   {i:>5}/{len(codes)}  받음 {len(got):,} · '
                  f'못 받음 {len(miss):,} · {time.time() - t0:.0f}s')
        time.sleep(a.sleep)

    doc = {
        'made': datetime.now().strftime('%Y-%m-%d'),
        'source': 'WiseReport ETF CU_data.grid_data (네이버 ETF 상세 iframe)',
        'note': ('구성종목은 **이름만** 온다 — 코드 조인은 측정 스크립트가 '
                 '한다. 스냅샷이라 과거 시점 구성이 아니다.'),
        'requested': len(codes), 'received': len(got),
        'missing': len(miss), 'missing_sample': miss[:20],
        'holdings': got,
    }
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False)
    print(f"\n■ 받음 {len(got):,} / {len(codes):,} "
          f"({len(got) / max(1, len(codes)) * 100:.1f}%)")
    print(f'저장: {OUT}')

    # 사용자가 물어본 둘은 어떤 모양인가 — 짐작하지 않고 찍어 둔다
    for c in ('0040Y0', '480020', '069500'):
        h = got.get(c)
        if not h:
            print(f'  {c} → 구성종목 미수신')
            continue
        tot = sum(x['weight'] for x in h if x['weight'] is not None)
        top = ', '.join(f"{x['name']}({x['weight']})" for x in h[:4])
        print(f'  {c} → {len(h)}행 · 비중합 {tot:.1f}% · {top}')
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
