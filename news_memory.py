# -*- coding: utf-8 -*-
"""뉴스 사건 기억 — 쌓인 사후 경로를 **읽는 쪽** (라운드 103).

■ 무엇이 없었나
  라운드 70 이 사건을 기록하고(record) 20영업일 뒤 사후 경로를 채우는
  (resolve) 길을 냈다. 워크플로에도 걸려 있다. 그런데 실측해 보니
  `news_events.jsonl` 을 읽는 코드가 **백업과 스냅샷 가드뿐**이었다.
  분석도 화면도 안 읽는다 — 기억이 아니라 창고였다.

  이 파일이 읽는 쪽이다. 지금은 답할 것이 없다(사후 경로 0건 — 첫 기록이
  2026-08-10 이라 20영업일이 안 지났다). 그래도 **먼저 만든다**:
  나중에 데이터가 와서 "이제 뭘로 읽지" 를 그때 정하면, 그때의 결과를
  보고 읽는 법을 고르게 된다. 그건 사후 선택이다.

■ 이 모듈이 지키는 것
  · **표본이 모자라면 값을 만들지 않는다.** 사유를 담아 돌려준다 (§3)
  · 하한은 새 숫자가 아니다 — resolve() 가 이미 쓰던 **30건**을 그대로
    재사용한다 ("적은 표본으로 평균을 내지 않는다")
  · 점수·게이트·문턱에 쓰지 않는다. **표시·연구 전용**이다 (11/16 동결)
  · 분모가 0이면 비율을 만들지 않는다

    import news_memory
    news_memory.lookup('수주·공급')   # → dict(available=…, why=…, …)
"""
from __future__ import annotations

import json
import os
from collections import defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(BASE, '.portfolio', 'news_events.jsonl')

#: 사건 유형별 통계를 내밀 최소 표본. **새 숫자가 아니다** —
#: news_event_recorder.resolve() 가 이미 쓰던 하한(30)을 그대로 쓴다.
MIN_N = 30

#: 사후 경로가 담고 있는 지평들 (resolve 가 채우는 필드와 같은 이름)
HORIZONS = (1, 3, 5, 10, 20)


def load(path=None):
    """사후 경로가 **채워진** 기록만 돌려준다."""
    p = path or LOG
    out = []
    if not os.path.exists(p):
        return out
    with open(p, encoding='utf-8', errors='replace') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:                                   # noqa: BLE001
                continue
            if r.get('resolved'):
                out.append(r)
    return out


def state(path=None):
    """기억이 지금 어떤 상태인가 — **기다리는 중인지 고장인지 가른다.**

    0건일 때 "없다" 로만 적으면 대기와 고장이 같은 색으로 보인다.
    가장 오래된 미해소 기록을 같이 적어 사람이 판단하게 한다.
    """
    p = path or LOG
    total = pending = 0
    oldest = None
    if os.path.exists(p):
        with open(p, encoding='utf-8', errors='replace') as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    r = json.loads(ln)
                except Exception:                               # noqa: BLE001
                    continue
                total += 1
                if not r.get('resolved'):
                    pending += 1
                    d = str(r.get('date'))[:10]
                    if oldest is None or d < oldest:
                        oldest = d
    res = total - pending
    # ⚠️ 왜 못 내미는지를 **정확히** 적는다. "기록이 없다" 로 뭉뚱그리면
    #   기다리는 중인지 아예 안 쌓이는지 구분이 안 된다 (§3).
    if res >= MIN_N:
        why = None
    elif total == 0:
        why = '기록이 한 건도 없다 — record 가 안 돌고 있을 수 있다.'
    elif pending:
        why = (f'대기 {pending}건 · 가장 오래된 것이 {oldest} 이고 '
               f'20영업일이 지나야 채워진다.')
    else:
        why = (f'대기 중인 기록도 없다 — 더 쌓이려면 record 가 새 사건을 '
               f'잡아야 한다.')
    return {
        'total': total, 'resolved': res, 'pending': pending,
        'oldest_pending': oldest, 'min_n': MIN_N,
        'usable': res >= MIN_N, 'why': why,
    }


def lookup(event_type, path=None):
    """사건 유형 하나의 사후 경로 분포. 못 내밀면 **사유를 담아** 돌려준다.

    평균을 내밀지 않는다 — 중앙값과 사분위로 낸다. 뉴스 사건 뒤 수익률은
    꼬리가 길어(급등·급락) 평균이 한두 건에 끌려간다.
    """
    rows = [r for r in load(path)
            if event_type in (r.get('events') or {})]
    st = state(path)
    if len(rows) < MIN_N:
        return {
            'event': event_type, 'available': False, 'n': len(rows),
            'min_n': MIN_N,
            # 건수는 한 번만 적는다 — state 의 사유는 **왜 더 없는지**만 붙인다
            'why': (f"'{event_type}' 사후 경로가 {len(rows)}건뿐이다 "
                    f"(하한 {MIN_N})."
                    + (f' {st["why"]}' if st.get('why') else '')),
        }
    out = {'event': event_type, 'available': True, 'n': len(rows),
           'min_n': MIN_N, 'why': None, 'horizons': {}}
    for h in HORIZONS:
        vals = sorted(float(r[f'ret_{h}d']) for r in rows
                      if r.get(f'ret_{h}d') is not None)
        if not vals:
            continue
        n = len(vals)
        out['horizons'][f'{h}d'] = {
            'n': n,
            'median': round(vals[n // 2], 2),
            'q25': round(vals[n // 4], 2),
            'q75': round(vals[(3 * n) // 4], 2),
            'up_rate': round(sum(1 for v in vals if v > 0) / n * 100, 1),
        }
    mfe = sorted(float(r['mfe']) for r in rows if r.get('mfe') is not None)
    mae = sorted(float(r['mae']) for r in rows if r.get('mae') is not None)
    if mfe:
        out['mfe_median'] = round(mfe[len(mfe) // 2], 2)
    if mae:
        out['mae_median'] = round(mae[len(mae) // 2], 2)
    return out


def event_types(path=None):
    """사후 경로가 채워진 기록에서 본 사건 유형과 그 건수."""
    g = defaultdict(int)
    for r in load(path):
        for ev in (r.get('events') or {}):
            g[ev] += 1
    return dict(sorted(g.items(), key=lambda x: -x[1]))


def _main():
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                           # noqa: BLE001
        pass
    st = state()
    print(f"뉴스 사건 기억 — 총 {st['total']:,}건 · 사후 경로 "
          f"{st['resolved']:,}건 · 대기 {st['pending']:,}건")
    if not st['usable']:
        print(f"  아직 못 내민다: {st['why']}")
        print('  (0건은 고장이 아니라 대기일 수 있다 — 위 날짜로 판단한다)')
        return 0
    for ev, n in event_types().items():
        d = lookup(ev)
        if not d['available']:
            print(f"  {ev:14s} n {d['n']:>4} — {d['why']}")
            continue
        h20 = (d.get('horizons') or {}).get('20d') or {}
        print(f"  {ev:14s} n {d['n']:>4} · 20일 중앙 "
              f"{h20.get('median')}% · 상승비율 {h20.get('up_rate')}% · "
              f"MFE {d.get('mfe_median')}% · MAE {d.get('mae_median')}%")
    return 0


if __name__ == '__main__':
    raise SystemExit(_main())
