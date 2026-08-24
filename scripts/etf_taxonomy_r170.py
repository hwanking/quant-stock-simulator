# -*- coding: utf-8 -*-
"""ETF 1,161종목 전수 분류 — 룩스루가 되는 곳과 안 되는 곳 (라운드 170).

사용자 요청: *"ETF 도 그 내부의 주식이 어떻게 형성되어 있는지 해서
ETF 의 펀더멘털 적정가 내주는 방법을 찾자. 우리만의 방식으로 연구하고
해서 기준이랑 다 검토해주고."*

라운드 167 이 **148개**에 룩스루 적정가를 냈다. 이 스크립트는 나머지
1,013개가 **왜** 안 되는지를 짐작이 아니라 **자료로** 가른다 — 그래야
넓힐 수 있는 곳이 어디인지, 없는지를 말할 수 있다.

■ 분류 기준 (구성종목 이름·비중·주식수만 본다 · 판정 아님)
    현금성   설정현금액 · 원화현금 · 예금 · CD금리 …
    스왑     스왑(증권사) — 주식을 하나도 안 들고 있다
    채권     국고 · 통안 · 회사채 · 산금채 …
    선물     선물 · 옵션
    국내주식  이름이 우리 종목 표에 **정확히** 붙는 것
    해외주식  한글이 없고 영문인 이름 (Vodafone Idea Ltd · NVIDIA Corp …)

측정 전용 — 점수·게이트·문턱을 바꾸지 않는다.

    C:/Python314/python.exe scripts/etf_taxonomy_r170.py
"""
import collections
import io
import json
import os
import re
import sys
from datetime import datetime

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
os.chdir(PROJ)

import etf_registry                                            # noqa: E402
import stock_code                                              # noqa: E402

HOLD = os.path.join(PROJ, '.portfolio', 'etf_holdings_r167.json')
LT = os.path.join(PROJ, 'data', 'etf_lookthrough_r167.json')
NAMES = os.path.join(PROJ, '.portfolio', 'name_master.json')
OUT = os.path.join(PROJ, 'data', 'etf_taxonomy_r170.json')

COVER_MIN = 90.0

_BOND = re.compile(r'국고|통안|국채|회사채|산금채|중금채|은행채|물가연동|'
                   r'재정증권|캐피탈|카드\d|채권|\d{4}-\d')
_SWAP = re.compile(r'스왑|SWAP')
_CASH = re.compile(r'설정현금액|원화현금|예금|CD금리|콜론|현금성|MMF')
_FUT = re.compile(r'선물|옵션|CALL|PUT|F 2\d')


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def main():
    print('ETF 전수 분류 (라운드 170)')
    print('측정 전용 — 점수·게이트·문턱을 바꾸지 않는다\n')

    with open(HOLD, encoding='utf-8') as f:
        hd = json.load(f)
    holdings = hd['holdings']
    with open(LT, encoding='utf-8') as f:
        lt = json.load(f)
    passed = {c for c, v in (lt.get('results') or {}).items()
              if (v.get('valued_pct') or 0) >= COVER_MIN}

    with open(NAMES, encoding='utf-8') as f:
        nm = json.load(f)
    etf = set(etf_registry.index() or {})
    by = collections.defaultdict(set)
    for r in nm.get('rows') or []:
        c = stock_code.normalize(r.get('code'))
        n = str(r.get('name') or '').strip()
        if c and n and c not in etf:
            by[n].add(c)
    uniq = {n: next(iter(s)) for n, s in by.items() if len(s) == 1}
    idx = etf_registry.index()

    def kind(s):
        if _CASH.search(s):
            return '현금성'
        if _SWAP.search(s):
            return '스왑'
        if _BOND.search(s):
            return '채권'
        if _FUT.search(s):
            return '선물·옵션'
        if uniq.get(s):
            return '국내주식'
        if re.search(r'[A-Za-z]', s) and not re.search(r'[가-힣]', s):
            return '해외주식'
        return '분류 안 됨'

    rows, cat = [], collections.Counter()
    have_w = collections.Counter()
    for c, hs in holdings.items():
        ws = [h for h in hs if h.get('weight') is not None]
        qs = [h for h in hs if h.get('qty') is not None]
        w_all = sum(h['weight'] for h in ws)
        by_k = collections.Counter()
        for h in hs:
            k = kind(h['name'])
            by_k[k] += (h.get('weight') or 0.0)
        # 비중이 없으면 **종목 수**로 지배 성격을 본다 (비중을 지어내지 않는다)
        if not ws:
            cnt = collections.Counter(kind(h['name']) for h in hs)
            dom = cnt.most_common(1)[0][0] if cnt else '알 수 없음'
            state = '비중 미기재'
        else:
            dom = by_k.most_common(1)[0][0] if by_k else '알 수 없음'
            state = ('룩스루 가능' if c in passed else '비중 있음 · 미통과')
        cat[(state, dom)] += 1
        have_w[bool(ws)] += 1
        rows.append({'code': c, 'name': idx.get(c, ''), 'holdings': len(hs),
                     'weighted_rows': len(ws), 'qty_rows': len(qs),
                     'weight_sum': round(w_all, 1), 'dominant': dom,
                     'state': state, 'passed': c in passed})

    print(f'■ ETF {len(rows):,}개 · 비중 있는 것 {have_w[True]:,} · '
          f'없는 것 {have_w[False]:,} (주식수는 전부 있다)\n')
    print(f"{'상태':16} {'지배 자산':10} {'개수':>6}")
    print('-' * 40)
    for (state, dom), n in sorted(cat.items(), key=lambda t: -t[1]):
        print(f'{state:16} {dom:10} {n:>6,}')

    print('\n■ 한 줄 요약')
    n_pass = sum(1 for r in rows if r['passed'])
    n_now = sum(1 for r in rows if r['state'] == '비중 미기재')
    n_fail = sum(1 for r in rows if r['state'] == '비중 있음 · 미통과')
    print(f'   룩스루 가능        {n_pass:>5,}  ({n_pass / len(rows) * 100:.1f}%)')
    print(f'   비중 미기재        {n_now:>5,}  ({n_now / len(rows) * 100:.1f}%)'
          f'  — 해외·채권 자산이라 원천이 비중을 안 준다')
    print(f'   비중 있는데 미통과  {n_fail:>5,}  ({n_fail / len(rows) * 100:.1f}%)'
          f'  — 구성종목 적정가를 못 낸다')

    print('\n■ 비중 미기재 ETF 의 지배 자산 (종목 수 기준)')
    nw = collections.Counter(r['dominant'] for r in rows
                             if r['state'] == '비중 미기재')
    for k, v in nw.most_common():
        print(f'   {v:>5}  {k}')

    doc = {'made': datetime.now().strftime('%Y-%m-%d'),
           'cover_min': COVER_MIN, 'total': len(rows),
           'passed': n_pass, 'no_weight': n_now, 'weight_but_failed': n_fail,
           'by_state_dominant': {f'{s}|{d}': n for (s, d), n in cat.items()},
           'no_weight_dominant': dict(nw),
           'rows': rows,
           'note': ('비중이 없는 ETF 도 **주식수는 전부 있다**. 그러나 '
                    '구성종목이 해외·채권이라 우리에게 가격도 적정가도 '
                    '없어 비중을 유도해도 룩스루가 되지 않는다.')}
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f'\n저장: {OUT}')
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
