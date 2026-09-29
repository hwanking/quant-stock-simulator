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


def _code6(tk):
    """종목의 정체 = 코드 6자리 (시장 접미사는 도장 · `ledger_view.code6` 한 곳을 부른다 · 라운드 391)."""
    import ledger_view as _lv391
    return _lv391.code6(tk)


def episodes(rows):
    """같은 종목이 EPISODE_DAYS 안에 다시 나오면 한 경험으로 센다.

    라운드 391 — 종목을 **코드 6자리**로 묶는다. 종전엔 전체 티커(005930.KS)로 묶어, 시장 접미사만
    다르게 들어간 같은 종목(원장 25종목 · R390)이 두 흐름으로 갈려 에피소드를 두 번 셌다.
    """
    last, n = {}, 0
    for r in sorted(rows, key=lambda x: (_code6(x.get('ticker')),
                                         str(x.get('date')))):
        tk = _code6(r.get('ticker'))
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

    # ── 라운드 391 — 정보량은 통계 행(`ledger_view.stat_rows` · 한 곳 · §4)으로 센다 ──
    #   ① raw cases 와 신선도 규약(ledger_rows)은 **원장 행 전체**다(§234 가 '기준 행수 = 원장 행수'를 잠근다).
    #   ②~⑧·연도·밀도·국면은 운영 보정표(랩)·화면 통계와 같은 행으로 센다 — 진입가 축척이 어긋난 행
    #   (지어낸 승패 · R364)과 시장 접미사만 다른 복사본(R390)을 빼고, 뺀 수를 산출물에 적는다.
    #   원장 행은 지우지 않는다(R197).
    import ledger_view as _lv391
    _keys391 = _lv391.scale_mismatch_keys()
    _cnt391 = {}
    srows = list(_lv391.stat_rows(rows, _keys391, _cnt391))

    tickers = {_code6(r.get('ticker')) for r in srows}
    dates = {str(r.get('date'))[:10] for r in srows}
    ep = episodes(srows)

    # ⑤ 섹터군집 — 같은 날 같은 섹터 종목은 대체로 같이 움직인다
    sec_pairs, no_sec = set(), 0
    for r in srows:
        k = (str(r.get('ticker')), str(r.get('date'))[:10])
        s = sect.get(k)
        if s:
            sec_pairs.add((k[1], s))
        else:
            no_sec += 1

    # ⑥ 시장국면 — 시장 충격은 그 날 전 종목에 공통이다
    regime_dates = {(str(r.get('date'))[:10], str(r.get('regime')))
                    for r in srows}

    # ⑦⑧ 전방
    fwd_ledger = [r for r in srows if str(r.get('date'))[:10] >= FORWARD_FROM]
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
    print(f'     통계 행 (②~⑧의 모집단)       {len(srows):>9,}'
          f'   (축척 어긋남 {_cnt391.get("scale", 0):,} · 복사본 {_cnt391.get("dup", 0):,} 제외'
          + ('' if _keys391 is not None else ' · 축척 감사 못 읽음 — 행 도장으로만 거름') + ')')
    print(f'  ② 고유 종목 (코드 6자리)        {len(tickers):>9,}')
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
        c = sum(1 for r in srows if str(r.get('date'))[:4] == y)
        bar = '█' * max(1, round(c / max(1, len(srows)) * 60))
        print(f'  {y}  {c:>7,}  {bar}')

    print('\n■ 종목당 밀도')
    per = Counter(_code6(r.get('ticker')) for r in srows)
    vals = sorted(per.values())
    print(f'  종목당 건수 — 최소 {vals[0]} · 중앙 {vals[len(vals) // 2]} · '
          f'최대 {vals[-1]}')

    print('\n■ 국면 기록 상태')
    rg = Counter(str(r.get('regime')) for r in srows)
    for k, c in rg.most_common():
        mark = '  ← 미기록' if k in ('None', 'none', '') else ''
        print(f'  {k:10s} {c:>7,} ({c / len(srows) * 100:4.1f}%){mark}')

    dst = os.path.join(PROJ, 'data', 'sample_audit.json')
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, 'w', encoding='utf-8') as f:
        json.dump(dict(
            made=_today(), span=[span[0], span[-1]],
            ledger_rows=len(rows),      # 신선도 검사 규약 (라운드 259)
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
            by_year={y: sum(1 for r in srows
                            if str(r.get('date'))[:4] == y)
                     for y in sorted(yrs)},
            regime_counts=dict(rg),
            # 라운드 391 — ②~⑧은 통계 행(`ledger_view.stat_rows`)으로 센다. 뺀 수와 그 사유를 같이 적는다(§3).
            stat_rows=len(srows),
            stat_excluded=dict(scale=int(_cnt391.get('scale', 0)), dup=int(_cnt391.get('dup', 0))),
            scale_audit_read=_keys391 is not None,
            stat_note='①·ledger_rows 는 원장 행 전체, ②~⑧·연도·밀도·국면은 통계 행이다 — 진입가 축척이 '
                      '어긋난 행(지어낸 승패)과 시장 접미사만 다른 복사본을 뺀다(원장 행은 안 지운다). '
                      '종목은 코드 6자리로 센다.',
            note='세기만 한다 — 점수·게이트를 바꾸지 않는다. raw 개수보다 '
                 '④~⑥(독립성 보정)과 ⑦⑧(전방)을 우선해 읽는다.'),
            f, ensure_ascii=False, indent=1)
    print(f'\n저장: {dst}')
    return 0


if __name__ == '__main__':
    _utf8_stdout()
    sys.exit(main())
