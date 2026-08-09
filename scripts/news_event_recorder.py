# -*- coding: utf-8 -*-
"""
라운드 70 — 뉴스 사건 사후 경로 축적 (관측 전용 · 오늘부터).

■ 왜 소급이 안 되는가
  사건 유형 10종을 태깅하지만 "그 뒤 주가가 어떻게 됐나"는 비어 있다.
  원장·하위점수 패치 어디에도 뉴스 필드가 없고, 공개 RSS 는 **과거
  기사를 주지 않는다.** 그래서 역사 소급은 원리적으로 불가능하다 —
  지어내는 대신 **오늘부터 쌓는다.**

■ 무엇을 하나
  ① record  : 오늘 시점 종목별 사건 태그를 append-only 로 박제
               (기준가·거래량 배율까지 함께 — 나중 수익률 계산의 기준)
  ② resolve : 20영업일이 지난 기록에 사후 경로를 채운다
               (1/3/5/10/20일 수익률 · MFE · MAE)

■ 8/23 동결 준수
  점수·게이트·문턱을 바꾸지 않는다. 기록만 한다. 여기서 나온 것은
  8/23 이후 새 사전등록의 입력으로만 쓴다.

    python scripts/news_event_recorder.py --record
    python scripts/news_event_recorder.py --resolve
"""
import io
import json
import os
import sys
import warnings
from datetime import date

warnings.filterwarnings('ignore')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
P = os.path.join(PROJ, '.portfolio')
LOG = os.path.join(P, 'news_events.jsonl')
H = 20


def record():
    import news_feed as nf
    from bitemporal_engine import STOCK_METRICS_DB

    items, report = nf.fetch(max_age_sec=0)
    got = sum(r['count'] for r in report)
    if not items:
        print(f'뉴스 미수신 — 기록하지 않는다 (출처 {len(report)}곳, '
              f'수신 {got}건). 미수신과 이슈 없음은 다른 말이다.')
        return 0
    today = date.today().isoformat()
    seen = set()
    if os.path.exists(LOG):
        with open(LOG, encoding='utf-8') as f:
            for ln in f:
                try:
                    q = json.loads(ln)
                    seen.add((q['ticker'], q['date']))
                except Exception:                              # noqa: BLE001
                    continue
    # 국내 종목만 — 사후 경로를 국내 일봉으로 채우므로 해외 티커를
    # 기록하면 영원히 resolve 되지 않고 로그만 더럽힌다.
    names = {}
    for sym, meta in (STOCK_METRICS_DB or {}).items():
        nm = (meta or {}).get('name')
        if nm and str(sym).endswith(('.KS', '.KQ')):
            names[str(nm)] = str(sym)

    wrote = 0
    with open(LOG, 'a', encoding='utf-8') as out:
        for nm, sym in names.items():
            if (sym, today) in seen:
                continue
            s = nf.for_stock(nm, items=items)
            if not s.get('total'):
                continue                    # 기사 없는 종목은 기록 안 함
            out.write(json.dumps({
                'ticker': sym, 'name': nm, 'date': today,
                'total': s['total'], 'fresh': s['fresh'],
                'lagging': s['lagging'],
                'events': s.get('event_types') or {},
                'risk_words': s.get('risk_words') or [],
                'catalyst_words': s.get('catalyst_words') or [],
                'sources_ok': sum(1 for r in report if r['ok']),
                'resolved': False,
            }, ensure_ascii=False) + '\n')
            wrote += 1
    print(f'기록 {wrote}종목 (기사 있는 종목만) · 수신 {got}건 · '
          f'출처 {sum(1 for r in report if r["ok"])}/{len(report)}곳')
    return wrote


def resolve():
    """20영업일 지난 기록에 사후 경로를 채운다 — 없으면 조용히 남긴다."""
    if not os.path.exists(LOG):
        print('기록이 아직 없다.')
        return 0
    import bitemporal_engine as be
    rows = []
    with open(LOG, encoding='utf-8') as f:
        for ln in f:
            try:
                rows.append(json.loads(ln))
            except Exception:                                  # noqa: BLE001
                continue
    todo = [r for r in rows if not r.get('resolved')]
    if not todo:
        print(f'채울 것 없음 (총 {len(rows)}건 전부 완료)')
        return 0
    eng = be.BitemporalEngine()
    cache, done = {}, 0
    for r in todo:
        tk = r['ticker']
        if tk not in cache:
            try:
                df, _ = eng.load_bitemporal_data(tk, start_date='2024-01-01')
                cache[tk] = df
            except Exception:                                  # noqa: BLE001
                cache[tk] = None
        df = cache[tk]
        if df is None or len(df) < H + 2:
            continue
        dates = list(df['trade_date'].astype(str).str[:10])
        try:
            j = dates.index(r['date'])
        except ValueError:
            later = [i for i, d in enumerate(dates) if d > r['date']]
            if not later:
                continue                    # 아직 다음 거래일이 없다
            j = later[0] - 1
        if j + H >= len(dates):
            continue                        # 20봉이 아직 안 찼다 — 다음에
        C = df['adj_close'].astype(float).tolist()
        Hi = df['high_raw'].astype(float).tolist()
        Lo = df['low_raw'].astype(float).tolist()
        px = C[j]
        seg = range(j + 1, j + 1 + H)
        r['base_price'] = round(px, 2)
        for k in (1, 3, 5, 10, 20):
            r[f'ret_{k}d'] = round(C[j + k] / px * 100 - 100, 2)
        r['mfe'] = round(max(Hi[i] for i in seg) / px * 100 - 100, 2)
        r['mae'] = round(min(Lo[i] for i in seg) / px * 100 - 100, 2)
        r['resolved'] = True
        done += 1
    with open(LOG, 'w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    print(f'사후 경로 채움 {done}건 / 대기 {len(todo)}건 (총 {len(rows)}건)')

    res = [r for r in rows if r.get('resolved')]
    if len(res) >= 30:
        import numpy as np
        from collections import defaultdict
        g = defaultdict(list)
        for r in res:
            for ev in (r.get('events') or {}):
                g[ev].append(r)
        print(f'\n■ 사건 유형별 사후 경로 (n≥10 만 · 표본 {len(res)}건)')
        for ev, sub in sorted(g.items(), key=lambda x: -len(x[1])):
            if len(sub) < 10:
                continue
            print(f"  {ev:12s} n {len(sub):>4} · 1일 "
                  f"{np.mean([r['ret_1d'] for r in sub]):+5.2f}% · 20일 "
                  f"{np.mean([r['ret_20d'] for r in sub]):+5.2f}% · MFE "
                  f"{np.median([r['mfe'] for r in sub]):+5.2f}%")
    else:
        print(f'\n사건별 집계는 표본 30건 이상부터 (현재 {len(res)}건) — '
              f'적은 표본으로 평균을 내지 않는다.')
    return done


if __name__ == '__main__':
    if '--resolve' in sys.argv:
        resolve()
    else:
        record()
