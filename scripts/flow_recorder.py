# -*- coding: utf-8 -*-
"""투자자별 수급(외국인·기관) 일별 기록기 — 수집 전용, 운영 미반영.

라운드 124 가 후보 3(외국인 수급)을 **"불가 · 수집 시작 + 6~12개월"** 로
적었다. 그 전제가 틀렸다 — 네이버 종목 페이지의 '외국인·기관' 표는
**페이지를 넘기면 2013년까지 되짚힌다**(라운드 130 실측). 즉 앞으로
쌓기를 기다릴 것이 아니라 **원장 기간을 소급해서 채울 수 있다.**

이 스크립트가 하는 일은 **기록뿐**이다:
  · 점수·게이트·문턱을 건드리지 않는다
  · 화면에 새 값을 내보내지 않는다
  · 판정에 쓰지 않는다 — 사전등록 없이 측정도 하지 않는다

§9 준수: 공개 페이지만 읽는다. 로그인·쿠키·CAPTCHA 우회 없음
(`market_attention.fetch_investor_flow` 가 이미 같은 페이지를 쓴다).

§3 준수: 못 받은 것은 **비워 둔다.** 0 으로 채우지 않는다 —
"순매수 0" 과 "미수신" 은 다른 사실이다.

    # 원장에서 케이스가 많은 종목부터 40개, 각 12페이지(약 240거래일)
    C:/Python314/python.exe scripts/flow_recorder.py --tickers 40 --pages 12

    # 커버리지만 보고 싶을 때 (수집 안 함)
    C:/Python314/python.exe scripts/flow_recorder.py --report
"""
import argparse
import collections
import io
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

import bitemporal_engine as be                                 # noqa: E402
import market_attention as ma                                  # noqa: E402

LEDGER = os.path.join(PROJ, '.portfolio', 'virtual_graded.jsonl')
OUT = os.path.join(PROJ, '.portfolio', 'flow_daily.jsonl')
#: 한 페이지는 20거래일. 네이버가 서비스하는 깊이는 종목마다 다르다
#: (상장일까지). 없는 페이지는 행 0개로 오므로 그때 멈춘다.
ROWS_PER_PAGE = 20
SRC = 'naver_frgn'


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def code_of(ticker):
    """'005930.KS' → '005930'. 6자리가 아니면 None (ETF·해외 등)."""
    c = str(ticker or '').split('.')[0].strip()
    return c if re.fullmatch(r'\d{6}', c) else None


def ledger_cases():
    """원장의 (종목, 날짜) 집합과 종목별 케이스 수."""
    cases, per_ticker = set(), collections.Counter()
    with open(LEDGER, encoding='utf-8', errors='replace') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:                                  # noqa: BLE001
                continue
            t, d = r.get('ticker'), str(r.get('date') or '')[:10]
            if not t or not d:
                continue
            cases.add((t, d))
            per_ticker[t] += 1
    return cases, per_ticker


def load_have():
    """이미 기록한 (종목, 날짜). 같은 것을 두 번 받지 않는다."""
    have = set()
    if not os.path.exists(OUT):
        return have
    with open(OUT, encoding='utf-8', errors='replace') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:                                  # noqa: BLE001
                continue
            if r.get('ticker') and r.get('date'):
                have.add((r['ticker'], r['date']))
    return have


def fetch_page(code, page):
    """한 페이지의 일별 행. 실패·빈 페이지는 빈 목록 (지어내지 않는다)."""
    url = (f'https://finance.naver.com/item/frgn.naver'
           f'?code={code}&page={page}')
    try:
        html = be.fetch_html_with_retry(url)
    except Exception:                                          # noqa: BLE001
        return None                       # None = 실패 (빈 페이지와 구분)
    out = []
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', html or '', re.S):
        cells = [ma._clean(c)
                 for c in re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)]
        if len(cells) < 7 or not re.match(r'\d{4}\.\d{2}\.\d{2}', cells[0]):
            continue
        inst, frgn = ma._signed(cells[5]), ma._signed(cells[6])
        if inst is None and frgn is None:
            continue                      # 둘 다 못 읽으면 행을 만들지 않는다
        out.append({'date': cells[0].replace('.', '-'),
                    'inst': inst, 'frgn': frgn})
        if len(out) >= ROWS_PER_PAGE:
            break
    return out


#: 사전 고정한 표본 조건 (docs/CANDIDATES_R130_FLOW_ENGINES.md §5).
#: **데이터를 보기 전에** 적었다. 나중에 정하면 통과하는 쪽으로 정하게 된다.
NEED_CASES = 20_000
NEED_DAYS = 400


def report(cases, per_ticker, have):
    """커버리지 — 원장 케이스 중 수급이 붙은 비율. 케이스와 날짜를 함께 센다.

    라운드 113 의 교훈: 표본 조건을 **케이스 수로만** 걸면 날짜가 날아간
    것을 못 본다. 둘 다 찍는다.
    """
    hit = sum(1 for k in cases if k in have)
    days_all = {d for _, d in cases}
    days_hit = {d for t, d in cases if (t, d) in have}
    print('■ 커버리지 (원장 대비)')
    print(f'   케이스 {hit:,} / {len(cases):,} '
          f'({hit / max(1, len(cases)) * 100:.1f}%)  '
          f'[조건 {NEED_CASES:,} — {"충족" if hit >= NEED_CASES else "미달"}]')
    print(f'   날짜   {len(days_hit):,} / {len(days_all):,} '
          f'({len(days_hit) / max(1, len(days_all)) * 100:.1f}%)  '
          f'[조건 {NEED_DAYS:,} — '
          f'{"충족" if len(days_hit) >= NEED_DAYS else "미달"}]')
    print(f'   기록 총량 {len(have):,}행 · 종목 '
          f'{len({t for t, _ in have}):,}개')
    if have:
        ds = sorted({d for _, d in have})
        print(f'   기록 구간 {ds[0]} ~ {ds[-1]}')

    # ── 구멍 검사 — 페이지를 건너뛰면 여기서 보여야 한다 ──────────
    # 원장의 날짜 합집합을 거래일 달력의 대용으로 쓴다. 한 종목의
    # 기록 구간 **안에서** 달력에 있는데 기록에 없는 날을 센다.
    # 이걸 안 찍으면 --from-page 로 건너뛴 구멍을 영영 모른다.
    cal = sorted(days_all)
    by_t = collections.defaultdict(set)
    for t, d in have:
        by_t[t].add(d)
    holes, worst = 0, (None, 0)
    for t, ds_t in by_t.items():
        lo, hi = min(ds_t), max(ds_t)
        miss = sum(1 for d in cal if lo <= d <= hi and d not in ds_t)
        holes += miss
        if miss > worst[1]:
            worst = (t, miss)
    print(f'   기록 구간 안의 빈 날 {holes:,}일 '
          f'(최다 {worst[0]} {worst[1]:,}일)')
    print('   ※ 상장 전·거래정지·원장 달력의 한계로도 생긴다. '
          '갑자기 20의 배수로 늘면 페이지를 건너뛴 것이다.')
    return hit, len(days_hit)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tickers', type=int, default=20,
                    help='원장 케이스가 많은 순으로 몇 종목까지')
    ap.add_argument('--pages', type=int, default=6,
                    help='종목당 몇 페이지까지 (1페이지 = 20거래일)')
    # 이어 받을 때 이미 받은 페이지를 다시 요청하면 그만큼 통째로 낭비다.
    # 1차 수집(1~25페이지) 뒤 깊이를 늘릴 때는 --from-page 26 처럼 준다.
    # **한 페이지 겹쳐서** 시작하는 것이 안전하다 — 중복은 어차피
    # 걸러지고, 경계에서 빠지는 것이 훨씬 나쁘다.
    ap.add_argument('--from-page', type=int, default=1,
                    help='몇 페이지부터 (이어 받기 — 일일 수집은 1)')
    ap.add_argument('--delay', type=float, default=0.25,
                    help='요청 사이 간격(초)')
    ap.add_argument('--report', action='store_true',
                    help='수집 없이 커버리지만 본다')
    a = ap.parse_args()

    print('라운드 130 — 투자자별 수급 일별 기록기 (수집 전용)')
    print('점수·게이트·문턱을 바꾸지 않는다. 판정에 쓰지 않는다.')
    print()

    cases, per_ticker = ledger_cases()
    have = load_have()
    if a.report:
        report(cases, per_ticker, have)
        return 0

    order = [t for t, _ in sorted(per_ticker.items(),
                                  key=lambda x: (-x[1], x[0]))]
    picked, skipped = [], 0
    for t in order:
        if len(picked) >= a.tickers:
            break
        if code_of(t):
            picked.append(t)
        else:
            skipped += 1
    first = max(1, a.from_page)
    print(f'대상 {len(picked)}종목 (6자리 아님으로 건너뜀 {skipped}개) '
          f'· 페이지 {first}~{a.pages}')
    if first > 1:
        print(f'   ※ {first - 1}페이지까지는 이미 받은 것으로 보고 건너뛴다. '
              f'경계가 어긋나면 아래 "구간"에 구멍이 보인다.')

    added = 0
    fail_t, empty_t = [], []
    with open(OUT, 'a', encoding='utf-8') as out:
        for i, t in enumerate(picked, 1):
            code = code_of(t)
            got_t = 0
            for page in range(first, a.pages + 1):
                rows = fetch_page(code, page)
                if rows is None:
                    fail_t.append((t, page))
                    break                 # 실패하면 그 종목은 여기서 멈춘다
                if not rows:
                    break                 # 더 깊은 과거가 없다 (상장일 등)
                for r in rows:
                    key = (t, r['date'])
                    if key in have:
                        continue
                    have.add(key)
                    out.write(json.dumps({
                        'ticker': t, 'date': r['date'],
                        'inst': r['inst'], 'frgn': r['frgn'],
                        'src': SRC,
                        'fetched_at': datetime.now(timezone.utc)
                        .isoformat(timespec='seconds'),
                    }, ensure_ascii=False) + '\n')
                    added += 1
                    got_t += 1
                time.sleep(a.delay)
            if got_t == 0:
                empty_t.append(t)
            if i % 10 == 0 or i == len(picked):
                print(f'   {i}/{len(picked)} · 새로 {added:,}행')

    print()
    if fail_t:
        print(f'※ 요청 실패 {len(fail_t)}건 — 그 종목은 거기서 멈췄다 '
              f'(예: {fail_t[:3]})')
    if empty_t:
        print(f'※ 새로 받은 것이 없는 종목 {len(empty_t)}개 '
              f'(이미 있거나 페이지가 비었다)')
    print(f'새로 기록 {added:,}행 → {OUT}')
    print()
    report(cases, per_ticker, have)
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
