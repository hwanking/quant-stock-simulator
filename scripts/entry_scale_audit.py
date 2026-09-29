# -*- coding: utf-8 -*-
"""
라운드 365 — 원장 진입가가 그날 실제 봉 종가와 맞나 (전수 · 관측 전용).

■ 왜 이 감사가 필요한가
  라운드 363 이 클라우드 로그의 *"대표 놓침 사례 +1668%"* 를 따라가 4종목을
  찾았고, 라운드 364 가 판별식을 **원인**으로 바꾸니 **16종목**이었다.
  원장 진입가가 기준일 2026-08-10 앞에서 그날 봉과 **상수배**로 어긋나 있고
  (실측 0.20 ~ 10.0), 채점은 매 실행 다시 도므로(R197·R303) 어긋난 진입가를
  오늘 봉과 견주게 된다. 목표·손절이 진입가에서 2~3% 거리라 작은 어긋남으로도
  결과가 1봉에 박힌다:
      · 진입가가 낮으면 → 1봉째 TARGET (지어낸 승리)
      · 진입가가 높으면 → 1봉째 STOP   (지어낸 패배)

■ 왜 회귀가 아니라 생성기인가
  판별식이 **일봉을 종목마다 한 번** 받아야 한다(실측 252초 · 라운드 364).
  회귀에 넣으면 실시세에 묶이고(§6 이 경고하는 자리) 앱 서버와 부딪친다.
  그래서 라운드 259 가 표본 감사·ICC·업종 성적에 쓴 모양을 그대로 따른다 —
  워크플로가 만들고, 신선도 검사가 낡음을 보고, 회귀는 **산출물을 읽는다.**

■ 판별식에 문턱이 없다
  어긋남은 **항등식**이다 — `원장 진입가 == 그날 봉 종가`. 라운드 364 실측에서
  분포가 완전히 갈렸다(1,382종목은 어긋난 행이 **0개** · 16종목은 96~100%).
  그러니 "몇 % 넘으면" 같은 수를 고르지 않는다(§2).

■ 안 하는 것
  · 원장을 고치지 않는다 · 채점을 바꾸지 않는다 · 판정하지 않는다.
    세기만 하고 적는다(관측 전용 · 라운드 44 의 표시 전용과 같은 자리).
  · 못 받은 종목은 **못 읽음**으로 따로 센다 — 0 으로 세지 않는다(§3 · R194).
  · 종목 **이름**은 담지 않는다 (코드만 · §9).

    C:/Python314/python.exe scripts/entry_scale_audit.py
"""
import io
import json
import os
import statistics
import sys
import time

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
os.chdir(PROJ)

LEDGER = os.path.join(PROJ, '.portfolio', 'virtual_graded.jsonl')
OUT = os.path.join(PROJ, 'data', 'entry_scale_audit.json')

#: 종목당 최소 행 — 한두 행으로 "이 **종목**이 어긋났다"고 적지 않는다(종목 단위 목록 `offenders` 에만 쓴다).
#: 라운드 364 가 쓴 그 수이고 새로 고른 값이 아니다. ⚠️ 라운드 391 — 행 목록(`offender_keys`)에는 이 하한을
#: 쓰지 않는다: 항등식은 행 하나로도 사실이고, 이 하한 밑 종목도 재서 `small_*` 로 따로 적는다.
MIN_ROWS = 20

#: 원 단위 반올림·표기 차이를 어긋남으로 세지 않기 위한 허용 오차.
#: 라운드 364 실측에서 정상 종목은 배율이 **정확히 1.0000** 이었고
#: 어긋난 종목은 1.5% 이상이었다 — 그 사이를 가르는 값이 아니라
#: **같은 값인지**를 보는 오차다.
#: 라운드 390 — 판정은 `ledger_view.entry_scale_off` 한 곳이다(채점 자리가 같은 것을 부른다 · §4).
import ledger_view as _lv390                                      # noqa: E402
EPS = _lv390.SCALE_EPS


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def _load_ledger():
    """{종목: [(기준일, 진입가, touched_bar, outcome)]} · 원장 행수도 같이."""
    import collections
    by = collections.defaultdict(list)
    n = 0
    with io.open(LEDGER, encoding='utf-8', errors='replace') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            n += 1
            try:
                r = json.loads(ln)
            except Exception:                                  # noqa: BLE001
                continue
            p = r.get('price')
            if not isinstance(p, (int, float)) or not p:
                continue
            by[str(r.get('ticker'))].append(
                (str(r.get('date'))[:10], float(p), r.get('touched_bar'),
                 str(r.get('outcome'))))
    return by, n


def main():
    _utf8()
    print('원장 진입가 축척 감사 (라운드 365)')
    print('관측 전용 — 원장·채점·문턱을 바꾸지 않는다\n')

    if not os.path.exists(LEDGER):
        print('■ 원장이 없다 — 셀 수 없다 (§3)')
        return 2

    import bitemporal_engine as be
    by, ledger_rows = _load_ledger()
    print(f'■ 원장 {ledger_rows:,}행 · 종목 {len(by):,}')

    eng = be.BitemporalEngine()
    rows, unread = {}, []
    # ⚠️ 라운드 391 — 여기가 20행 미만 종목을 **조용히 건너뛰었다**(몇 개를 건너뛰었는지도 안 적었다 · R194).
    #   2026-09-30 실측: 1,549종목 중 139종목(1,623행)이 안 재졌고, 채점 자리의 도장(R390 · 같은 항등식)이 그중
    #   22종목 256행을 어긋남으로 찍었다 — 배율 0.94~0.99 로 종목마다 일정한 계단(R389 의 '자료원이 과거 봉을
    #   고쳐 쓴다'와 같은 모양 · 2024년 상장 종목들). 그래서 감사는 2,342행, 도장은 2,598행을 말했다(§4 — 두 판정자).
    #   항등식은 행 하나로도 사실이므로 **행 목록(offender_keys)에는 전부 넣고**, 종목 단위 목록(offenders ·
    #   R364 의 정의 · §362 상한)은 20행 이상 그대로 두고 작은 종목은 **따로** 적는다(small_*).
    small, small_unread = {}, []
    t0 = time.time()
    codes = sorted(by)
    for i, tk in enumerate(codes, 1):
        led = by[tk]
        if len(led) < MIN_ROWS:
            try:
                df = eng.fetch_daily_bars(symbol=tk)
            except Exception:                                  # noqa: BLE001
                df = None
            if df is None or not len(df):
                small_unread.append(tk)
                continue
            dcol = 'trade_date' if 'trade_date' in df.columns else df.columns[0]
            try:
                bars = {str(df[dcol].iloc[k])[:10]: float(df['close_raw'].iloc[k])
                        for k in range(len(df))}
            except Exception:                                  # noqa: BLE001
                small_unread.append(tk)
                continue
            _m = [(d, _lv390.entry_scale_off(p, bars[d])) for d, p, _tb, _oc in led if d in bars and p]
            small[tk] = dict(n=len(led), matched=len(_m),
                             off_days=sorted(d for d, v in _m if v is True))
            continue
        try:
            df = eng.fetch_daily_bars(symbol=tk)
        except Exception:                                      # noqa: BLE001
            unread.append(tk)
            continue
        if df is None or not len(df):
            unread.append(tk)
            continue
        dcol = 'trade_date' if 'trade_date' in df.columns else df.columns[0]
        try:
            bars = {str(df[dcol].iloc[k])[:10]: float(df['close_raw'].iloc[k])
                    for k in range(len(df))}
        except Exception:                                      # noqa: BLE001
            unread.append(tk)
            continue
        _pairs = [(d, bars[d] / p) for d, p, _tb, _oc in led if d in bars and p]
        mult = [v for _d, v in _pairs]
        if len(mult) < MIN_ROWS:
            unread.append(tk)          # 댈 수 있는 행이 모자라다 — 0 이 아니다
            continue
        # 라운드 389 — 어긋난 **행**(기준일)을 같이 적는다. 종목 단위로만 적으면 부분 오염 종목
        #   (어긋남 16.9% · 32.6% · R365)의 정상 행까지 통계에서 빼게 된다. 같은 항등식이다.
        _off_days = sorted(d for d, p, _tb, _oc in led
                           if d in bars and _lv390.entry_scale_off(p, bars[d]) is True)
        off = len(_off_days)
        one = sum(1 for _d, _p, tb, _oc in led if tb == 1)
        rows[tk] = dict(n=len(led), matched=len(mult),
                        median_mult=round(statistics.median(mult), 4),
                        off=off, off_pct=round(off / len(mult) * 100, 1),
                        pinned_pct=round(one / len(led) * 100, 1),
                        off_days=_off_days)
        if i % 300 == 0:
            print(f'   {i:>5}/{len(codes)} · 잰 종목 {len(rows):,} · '
                  f'못 읽음 {len(unread)} · {time.time() - t0:.0f}s')

    took = round(time.time() - t0, 1)
    bad = sorted((tk for tk, v in rows.items() if v['off'] > 0),
                 key=lambda t: -rows[t]['off_pct'])
    clean = len(rows) - len(bad)
    print(f'\n■ 잰 종목 {len(rows):,} · 못 읽음 {len(unread)} · {took}s')
    print(f'■ 어긋난 행이 **0개** 인 종목 {clean:,} · '
          f'하나라도 어긋난 종목 **{len(bad)}**')
    for tk in bad:
        v = rows[tk]
        print(f'   {tk} : {v["n"]:>4}행 · 어긋남 {v["off_pct"]:>5.1f}% · '
              f'배율 중앙 {v["median_mult"]:.4f} · 1봉째 {v["pinned_pct"]:>5.1f}%')

    # 증상 잣대(1봉째 박힘)가 이 중 몇 개를 놓치는지 — 회귀가 그것을 쓴다
    missed = [tk for tk in bad if rows[tk]['pinned_pct'] <= 90]
    print(f'\n■ 증상 잣대(1봉째 > 90%)가 놓치는 종목 {len(missed)} / {len(bad)}')
    for tk in missed:
        v = rows[tk]
        print(f'   {tk} : 배율 {v["median_mult"]:.4f} · 1봉째 {v["pinned_pct"]:.1f}%')

    bad_rows = sum(rows[tk]['n'] for tk in bad)
    # 라운드 389 — 어긋난 행 자체(종목 → 기준일 목록). 운영 통계(보정표)와 화면 통계가 이것 하나로
    #   거른다(`ledger_view.scale_mismatch_keys` · §4). 봉과 못 댄 행(그날 봉 없음)은 **모른다**라 안 넣는다.
    off_keys = {tk: rows[tk].pop('off_days') for tk in list(rows)}
    off_keys = {tk: ds for tk, ds in off_keys.items() if ds}
    # 라운드 391 — 20행 미만 종목의 어긋난 행도 행 목록에 넣는다(항등식은 행 하나로도 사실이다).
    small_bad = sorted(tk for tk, v in small.items() if v['off_days'])
    for tk in small_bad:
        off_keys[tk] = small[tk]['off_days']
    print(f'\n■ {MIN_ROWS}행 미만 종목 — 잰 것 {len(small):,} · 못 읽음 {len(small_unread)} · '
          f'어긋난 행이 있는 종목 {len(small_bad)} · 그 행 {sum(len(small[t]["off_days"]) for t in small_bad):,}'
          f' (종목 단위 목록·상한에는 안 넣는다 — 따로 적는다)')
    doc = {
        'made': time.strftime('%Y-%m-%d'),
        'made_at': time.strftime('%Y-%m-%d %H:%M'),
        'ledger_rows': ledger_rows,          # 신선도 검사 규약 (라운드 259)
        'min_rows': MIN_ROWS,
        'eps': EPS,
        'took_sec': took,
        'measured': len(rows),
        'unread': len(unread),
        'unread_sample': unread[:20],
        'clean': clean,
        'offenders': len(bad),
        'offender_rows': bad_rows,
        'offender_codes': bad,
        'offender_keys': off_keys,
        'offender_key_rows': sum(len(v) for v in off_keys.values()),
        # 라운드 391 — 20행 미만 종목(종목 단위 목록 밖 · 행 목록 안). 원장의 모든 종목이 네 갈래 중 하나에
        #   든다(tickers = measured + unread + small_measured + small_unread) — 조용히 건너뛴 종목이 없다.
        'tickers': len(by),
        'small_measured': len(small),
        'small_unread': len(small_unread),
        'small_rows': sum(v['n'] for v in small.values()),
        'small_offenders': len(small_bad),
        'small_offender_codes': small_bad,
        'small_offender_key_rows': sum(len(small[t]['off_days']) for t in small_bad),
        'symptom_missed': len(missed),
        'symptom_missed_codes': missed,
        'rows': {tk: rows[tk] for tk in bad},
        'note': ('원장 진입가가 그날 실제 봉 종가와 맞는지 전수로 센다. '
                 '판별식은 항등식이고 문턱이 없다 — 라운드 364 실측에서 정상 종목은 '
                 '어긋난 행이 0개였다. 관측 전용 — 원장·채점·판정을 바꾸지 않는다. '
                 '못 읽은 종목은 따로 세고 0 으로 세지 않는다.'),
    }
    with io.open(OUT, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f'\n저장: {OUT}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
