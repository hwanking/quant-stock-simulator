# -*- coding: utf-8 -*-
"""
라운드 72 — 표본 감사 (raw 가 아니라 **정보량**을 센다).

■ 왜
  "되돌려 본 판단 60,462건" 은 raw 개수다. 금융 시계열은 독립이 아니어서
  raw 개수는 정보량을 과대계상한다. 같은 종목의 인접 신호, 같은 날 같은
  섹터, 동일한 시장 충격이 반복되면 60,462건이 60,462개의 독립 경험은
  아니다. 그래서 **여덟 가지를 항상 같이 본다.**

    ① raw cases
    ② 고유 종목
    ③ 고유 거래일
    ④ 독립 에피소드 (같은 종목 35일 그룹)
    ⑤ 섹터군집 보정 유효표본 (같은 날 · 같은 섹터 = 1)
    ⑥ 시장국면 보정 유효표본 (같은 날 = 1 — 시장 충격은 공통)
    ⑦ 전방 전용 평가 n
    ⑧ 고신뢰 전방 신호 n

  ⑧이 가장 중요하다. 과거 케이스가 30만 건이어도 실제 미래에서 한 번도
  안 본 고신뢰 추천이 몇십 건뿐이면 그 적중률은 여전히 불안하다.

■ 8/23 동결 준수
  세기만 한다. 점수·게이트·문턱을 바꾸지 않는다.

    C:/Python314/python.exe scripts/sample_audit.py
"""
import glob
import io
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
P = os.path.join(PROJ, '.portfolio')

#: 에피소드 묶음 — 같은 종목이 이 안에 다시 나오면 같은 경험으로 본다.
#: 새 숫자가 아니다. 보유기간 20영업일(≈28일)에 여유를 둔 기존 기준
#: (weakness_map · effective_n 에서 쓰던 값)을 그대로 재사용한다.
EPISODE_DAYS = 35

#: 전방 재평가 시작일 — 이 날 이후 새로 쌓인 것만 '전방'이다
FORWARD_FROM = '2026-08-09'

#: 매수권 문턱 (이미 채택된 값 — 여기서 새로 정하지 않는다)
BUY_SCORE = 58.0


def _today():
    """오늘 날짜 — 라운드 107. 박아 두면 다시 만들어도
    안 바뀌어 낡음을 알 수 없다 (라운드 102 miss_study).
    """
    import datetime as _dt
    return _dt.date.today().isoformat()


def _utf8_stdout():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def load_ledger():
    rows = []
    path = os.path.join(P, 'virtual_graded.jsonl')
    if not os.path.exists(path):
        return rows
    with open(path, encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                rows.append(json.loads(ln))
            except Exception:                                  # noqa: BLE001
                continue
    return rows


def load_sectors(rows):
    """(ticker, date) → 섹터. **두 곳**에서 모은다.

    ⚠️ 라운드 73 — 여기가 하위점수 패치만 봤다. 그래서 ⑤가 3,476 에서
    안 움직였고 '섹터 96.8% 미기록' 이라고 잘못 보고했다.
    라운드 72 확장분(121,497건)은 축적할 때 섹터를 **원장 행에 직접**
    쓴다 — 패치 파일이 애초에 필요 없다. 패치는 그 전 60,462건용이다.
    측정 도구가 한쪽만 보면 없는 구멍을 만들어 낸다.
    """
    out = {}
    for path in sorted(glob.glob(os.path.join(P, 'subscore_patch*.jsonl'))):
        with open(path, encoding='utf-8', errors='replace') as f:
            for ln in f:
                try:
                    q = json.loads(ln)
                except Exception:                              # noqa: BLE001
                    continue
                s = q.get('sector')
                if s:
                    out[(str(q.get('ticker')), str(q.get('date'))[:10])] = s
    for r in rows:                       # 원장에 직접 있는 것이 우선
        s = r.get('sector')
        if s:
            out[(str(r.get('ticker')), str(r.get('date'))[:10])] = s
    return out


def episodes(rows):
    """같은 종목이 EPISODE_DAYS 안에 다시 나오면 한 경험으로 센다."""
    last, n = {}, 0
    for r in sorted(rows, key=lambda x: (str(x.get('ticker')),
                                         str(x.get('date')))):
        tk = str(r.get('ticker'))
        try:
            d = date.fromisoformat(str(r.get('date'))[:10])
        except ValueError:
            continue
        if tk not in last or (d - last[tk]) > timedelta(days=EPISODE_DAYS):
            n += 1
        last[tk] = d
    return n


def forward_log():
    path = os.path.join(P, 'predictions.jsonl')
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                rows.append(json.loads(ln))
            except Exception:                                  # noqa: BLE001
                continue
    return rows


def main():
    rows = load_ledger()
    if not rows:
        print('원장이 없다 — 셀 것이 없다. 통과가 아니라 미측정이다.')
        return 1
    sect = load_sectors(rows)

    tickers = {str(r.get('ticker')) for r in rows}
    dates = {str(r.get('date'))[:10] for r in rows}
    ep = episodes(rows)

    # ⑤ 섹터군집 — 같은 날 같은 섹터 종목은 대체로 같이 움직인다
    sec_pairs, no_sec = set(), 0
    for r in rows:
        k = (str(r.get('ticker')), str(r.get('date'))[:10])
        s = sect.get(k)
        if s:
            sec_pairs.add((k[1], s))
        else:
            no_sec += 1

    # ⑥ 시장국면 — 시장 충격은 그 날 전 종목에 공통이다
    regime_dates = {(str(r.get('date'))[:10], str(r.get('regime')))
                    for r in rows}

    # ⑦⑧ 전방
    fwd_ledger = [r for r in rows if str(r.get('date'))[:10] >= FORWARD_FROM]
    flog = forward_log()
    fwd_log_new = [r for r in flog if str(r.get('date'))[:10] >= FORWARD_FROM]
    hi = [r for r in flog
          if float(r.get('score') or 0) >= BUY_SCORE
          and str(r.get('date'))[:10] >= FORWARD_FROM]

    span = sorted(dates)
    yrs = Counter(d[:4] for d in dates)

    print('■ 표본 감사 — raw 가 아니라 정보량')
    print(f'  기간 {span[0]} ~ {span[-1]}')
    print(f'  ① raw cases                    {len(rows):>9,}')
    print(f'  ② 고유 종목                     {len(tickers):>9,}')
    print(f'  ③ 고유 거래일                   {len(dates):>9,}')
    print(f'  ④ 독립 에피소드 ({EPISODE_DAYS}일 묶음)   {ep:>9,}'
          f'   (raw 대비 {ep / len(rows) * 100:.0f}%)')
    print(f'  ⑤ 섹터군집 보정 유효표본        {len(sec_pairs):>9,}'
          + (f'   ※ 섹터 미기록 {no_sec:,}건 제외' if no_sec else ''))
    print(f'  ⑥ 시장국면 보정 유효표본        {len(regime_dates):>9,}')
    print(f'  ⑦ 전방 전용 평가 n              {len(fwd_ledger):>9,}'
          f'   ({FORWARD_FROM} 이후)')
    print(f'  ⑧ 고신뢰 전방 신호 n            {len(hi):>9,}'
          f'   (전방 로그 {len(fwd_log_new):,}건 중 {BUY_SCORE:.0f}점+)')

    print('\n■ 연도별 분포 (얇은 해가 있으면 국면이 빠진 것이다)')
    for y in sorted(yrs):
        c = sum(1 for r in rows if str(r.get('date'))[:4] == y)
        bar = '█' * max(1, round(c / max(1, len(rows)) * 60))
        print(f'  {y}  {c:>7,}  {bar}')

    print('\n■ 종목당 밀도')
    per = Counter(str(r.get('ticker')) for r in rows)
    vals = sorted(per.values())
    print(f'  종목당 건수 — 최소 {vals[0]} · 중앙 {vals[len(vals) // 2]} · '
          f'최대 {vals[-1]}')

    print('\n■ 국면 기록 상태')
    rg = Counter(str(r.get('regime')) for r in rows)
    for k, c in rg.most_common():
        mark = '  ← 미기록' if k in ('None', 'none', '') else ''
        print(f'  {k:10s} {c:>7,} ({c / len(rows) * 100:4.1f}%){mark}')

    dst = os.path.join(PROJ, 'data', 'sample_audit.json')
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, 'w', encoding='utf-8') as f:
        json.dump(dict(
            made=_today(), span=[span[0], span[-1]],
            raw_cases=len(rows), unique_tickers=len(tickers),
            unique_dates=len(dates), independent_episodes=ep,
            sector_cluster_effective_n=len(sec_pairs),
            sector_missing=no_sec,
            regime_effective_n=len(regime_dates),
            forward_evaluated_n=len(fwd_ledger),
            forward_log_n=len(fwd_log_new),
            high_conf_forward_n=len(hi),
            forward_from=FORWARD_FROM, episode_days=EPISODE_DAYS,
            per_ticker=dict(min=vals[0], median=vals[len(vals) // 2],
                            max=vals[-1]),
            by_year={y: sum(1 for r in rows
                            if str(r.get('date'))[:4] == y)
                     for y in sorted(yrs)},
            regime_counts=dict(rg),
            note='세기만 한다 — 점수·게이트를 바꾸지 않는다. raw 개수보다 '
                 '④~⑥(독립성 보정)과 ⑦⑧(전방)을 우선해 읽는다.'),
            f, ensure_ascii=False, indent=1)
    print(f'\n저장: {dst}')
    return 0


if __name__ == '__main__':
    _utf8_stdout()
    sys.exit(main())
