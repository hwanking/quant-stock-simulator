# -*- coding: utf-8 -*-
"""DART 공시 일별 기록기 — 수집 전용, 운영 미반영 (라운드 139).

라운드 124 가 후보 1·2(주주환원·장기계약)를 **"DART 미연동 · 수집 시작 +
12개월"** 로 적었다. **또 틀렸다.** `dsac001/mainAll.do` 에
`selectDate=YYYYMMDD` (하이픈 없이) 를 붙이면 과거 하루가 그대로 열린다 —
2012년까지 확인했다. API 키도 로그인도 필요 없다.

라운드 130 에서 네이버 수급이 같은 식으로 열렸다. **두 번째다.**
→ "못 잰다"고 적어 둔 줄은 계획을 영원히 막는다. 한 번은 눌러 본다.

이 스크립트가 하는 일은 **기록뿐**이다:
  · 점수·게이트·문턱을 건드리지 않는다
  · 화면에 새 값을 내보내지 않는다
  · 판정에 쓰지 않는다 — 사전등록 없이 측정도 하지 않는다

§9 준수: 공개 페이지만. 로그인·API 키·CAPTCHA 우회 없음
(`market_attention.fetch_disclosures` 가 이미 같은 페이지를 쓴다).

§3 준수: 못 받은 것은 비워 둔다. 지어내지 않는다.

    # 최근 20거래일, 하루 최대 20페이지
    C:/Python314/python.exe scripts/disclosure_recorder.py --days 20

    # 커버리지만 (수집 안 함)
    C:/Python314/python.exe scripts/disclosure_recorder.py --report
"""
import argparse
import collections
import io
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

import bitemporal_engine as be                                 # noqa: E402
import market_attention as ma                                  # noqa: E402

OUT = os.path.join(PROJ, '.portfolio', 'disclosures_daily.jsonl')
BASE = 'https://dart.fss.or.kr/dsac001/mainAll.do'
TR = re.compile(r'<tr[^>]*>(.*?)</tr>', re.S)
TD = re.compile(r'<td[^>]*>(.*?)</td>', re.S)
RCP = re.compile(r'rcpNo=(\d{14})')
SRC = 'dart_dsac001'


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def _flat(html):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html or '')).strip()


def fetch_day(day, page=1):
    """하루치 한 페이지. 실패는 None, 빈 페이지는 [] 로 구분한다."""
    url = f'{BASE}?selectDate={day}' + (f'&currentPage={page}'
                                        if page > 1 else '')
    try:
        html = be.fetch_html_with_retry(url)
    except Exception:                                          # noqa: BLE001
        return None
    out = []
    for tr in TR.findall(html or ''):
        tds = TD.findall(tr)
        if len(tds) < 3:
            continue
        cells = [_flat(c).replace('&nbsp;', ' ').strip() for c in tds]
        if not re.match(r'\d{1,2}:\d{2}', cells[0]):
            continue
        m = RCP.search(tr)
        if not m:
            continue
        rcp = m.group(1)
        name = re.sub(r'^[유코기넥]\s+', '', cells[1]).strip()
        name = re.sub(r'\s+(IR|공)$', '', name).strip()
        title = cells[2]
        if not name or not title:
            continue
        out.append({'rcp': rcp, 'time': cells[0], 'name': name,
                    'title': title[:200],
                    'type': ma._classify_disclosure(title),
                    # ⚠️ 정정공시는 **원본(옛 날짜)** 접수번호를 싣는다.
                    #   그래서 rcp 앞 8자리가 요청 날짜와 다를 수 있다
                    #   (실측 1~10%). 결함이 아니므로 그대로 적는다.
                    'rcp_day': rcp[:8]})
    return out


def load_have():
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
            if r.get('rcp'):
                have.add(r['rcp'])
    return have


def report(have):
    """무엇을 얼마나 모았나. 날짜와 건수를 **함께** 찍는다 (R113 교훈)."""
    if not os.path.exists(OUT):
        print('아직 모은 것이 없다')
        return
    days, types, n = set(), collections.Counter(), 0
    with open(OUT, encoding='utf-8', errors='replace') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:                                  # noqa: BLE001
                continue
            n += 1
            days.add(r.get('day'))
            types[r.get('type')] += 1
    ds = sorted(d for d in days if d)
    print(f'■ 모은 것 {n:,}건 · 날짜 {len(ds):,}일')
    if ds:
        print(f'   구간 {ds[0]} ~ {ds[-1]}')
    print('   유형별:')
    for k, v in types.most_common():
        print(f'      {str(k):<14} {v:>7,}건 ({v / max(1, n) * 100:.1f}%)')
    etc = types.get('기타', 0)
    print(f'   ※ 제목만으로 태깅하므로 재현율이 낮다 — "기타"가 '
          f'{etc / max(1, n) * 100:.0f}% 다. 라운드 124 가 "그 낮음을 '
          f'측정해서 적는다"고 한 그 숫자다.')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=10,
                    help='오늘부터 며칠 거슬러 올라갈지 (달력일)')
    ap.add_argument('--from-date', default='',
                    help='이 날짜부터 거슬러 (YYYY-MM-DD · 없으면 오늘)')
    ap.add_argument('--pages', type=int, default=20, help='하루 최대 페이지')
    ap.add_argument('--delay', type=float, default=0.4)
    ap.add_argument('--report', action='store_true')
    a = ap.parse_args()

    print('라운드 139 — DART 공시 일별 기록기 (수집 전용)')
    print('점수·게이트·문턱을 바꾸지 않는다. 판정에 쓰지 않는다.')
    print()

    have = load_have()
    if a.report:
        report(have)
        return 0

    start = (datetime.strptime(a.from_date, '%Y-%m-%d').date()
             if a.from_date else date.today())
    print(f'{start} 부터 {a.days}일 거슬러 · 하루 최대 {a.pages}페이지 · '
          f'이미 가진 접수번호 {len(have):,}개')

    added = empty = fail = 0
    with open(OUT, 'a', encoding='utf-8') as out:
        for i in range(a.days):
            d = start - timedelta(days=i)
            if d.weekday() >= 5:              # 주말은 공시가 거의 없다
                continue
            day = d.strftime('%Y%m%d')
            got = 0
            for page in range(1, a.pages + 1):
                rows = fetch_day(day, page)
                if rows is None:
                    fail += 1
                    break
                if not rows:
                    break
                fresh = 0
                for r in rows:
                    if r['rcp'] in have:
                        continue
                    have.add(r['rcp'])
                    r['day'] = d.isoformat()
                    r['src'] = SRC
                    r['fetched_at'] = datetime.now(timezone.utc).isoformat(
                        timespec='seconds')
                    out.write(json.dumps(r, ensure_ascii=False) + '\n')
                    added += 1
                    fresh += 1
                    got += 1
                time.sleep(a.delay)
                if fresh == 0:                # 이 페이지가 통째로 중복
                    break
            if got == 0:
                empty += 1
            print(f'   {d.isoformat()}  새로 {got:>4}건 (누적 {added:,})')

    print()
    if fail:
        print(f'※ 요청 실패 {fail}건 — 그 날은 거기서 멈췄다')
    if empty:
        print(f'※ 새로 받은 것이 없는 날 {empty}일 (이미 있거나 휴장)')
    print(f'새로 기록 {added:,}건 → {OUT}')
    print()
    report(have)
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
