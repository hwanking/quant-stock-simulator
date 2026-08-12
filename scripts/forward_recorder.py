# -*- coding: utf-8 -*-
"""
라운드 77 — 전방 판정 기록기 (오늘 판정을 박제한다).

■ 왜 필요한가 — 확인한 사실
  8/23 전방 재평가는 2026-08-09 이후 새로 쌓이는 데이터로만 판정한다.
  그런데 그 데이터를 **아무도 자동으로 쌓고 있지 않았다.**

    · predictions.jsonl 을 쓰는 것은 web_app.py 와 premarket.py 뿐이다
    · 둘 다 클라우드에서 돌지 않는다 (일일 워크플로 9개 스크립트에 없다)
    · 실측: 전방 27건이 전부 8/10·8/11·8/12 — **사람이 앱을 띄운 날만**

  즉 전방 축적이 "PC 를 켜 뒀는가"에 달려 있었다. 라운드 68 에서 없애려
  했던 바로 그 의존이 전방 쪽에 그대로 남아 있었다.

  또 하나 — calibration_lab 은 전방을 만들 수 없다. usable 이
  `dates[260:len-21]` 이라 **오늘 날짜 케이스는 원리적으로 못 만든다**
  (20봉이 지나야 채점되므로 당연하다). 전방은 여기서 먼저 쌓이고
  20영업일 뒤에 채점되어 원장으로 들어온다.

■ 무엇을 하나
  오늘 시점으로 유니버스 상위 N 종목을 판정해 predictions.jsonl 에
  append 한다. 필드는 앱이 쓰던 것과 **똑같이** 맞춘다 (web_app.py
  '판정 기록' 블록). 화면과 다른 값을 쌓으면 나중에 대조가 안 된다.

  같은 (종목, 날짜) 는 다시 쓰지 않는다 — 하루 여러 번 돌아도 안전하다.

■ 8/23 동결 준수
  기록만 한다. 점수·게이트·문턱을 바꾸지 않는다.

    C:/Python314/python.exe scripts/forward_recorder.py [--top 60]
"""
import io
import json
import os
import sys
import time
import warnings

warnings.filterwarnings('ignore')
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

DEFAULT_TOP = 60


def _utf8_stdout():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def main():
    top = DEFAULT_TOP
    if '--top' in sys.argv:
        top = int(sys.argv[sys.argv.index('--top') + 1])

    import bitemporal_engine as be
    import prediction_log as plog
    import quant_indicators as qi

    eng = be.BitemporalEngine()
    q = qi.QuantIndicatorsEngine()
    t_ref = be.resolve_analysis_date().strftime('%Y-%m-%d')
    print(f'전방 판정 기록 — 기준일 {t_ref} · 상위 {top}종목')

    # 이미 오늘 기록한 종목은 건너뛴다 (하루 여러 번 돌아도 안전)
    done = set()
    for r in plog.load_predictions():
        if str(r.get('date'))[:10] == t_ref:
            done.add(str(r.get('ticker')))
    if done:
        print(f'  오늘 이미 기록됨 {len(done)}종목 — 건너뛴다')

    try:
        uni = eng.get_screener_universe(full_market=True, max_pages=40)
    except Exception as exc:                                   # noqa: BLE001
        # 유니버스를 못 받으면 **기록하지 않는다.** 임의 종목으로 채우면
        # 그 날의 '추천'이 무엇이었는지 왜곡된다 (§3).
        print(f'유니버스 수신 실패 — 오늘은 기록하지 않는다: '
              f'{type(exc).__name__}: {exc}')
        return 1
    pool = [u['symbol'] for u in uni[:top] if u['symbol'] not in done]
    print(f'  대상 {len(pool)}종목 (전 종목 {len(uni):,} 중 상위 {top})')

    t0, wrote, failed = time.time(), 0, 0
    for i, sym in enumerate(pool, 1):
        try:
            snap = q.run_full_pipeline(sym, t_ref, b_engine=eng,
                                       rho_cutoff=0.80)
            fs = snap['four_scores']
            vd = q.build_final_verdict(snap)
            # 앱과 같은 필드·같은 출처 (web_app.py 판정 기록 블록)
            ok = plog.record_prediction({
                'ticker': sym,
                'name': (fs.get('name') or snap.get('name') or sym),
                'date': snap.get('t_ref') or t_ref,
                'price': fs.get('current_price'),
                'action': vd.get('action'),
                'action_label': vd.get('headline'),
                'score': vd.get('score'),
                'target': fs.get('target_tech_1st'),
                'stop': fs.get('stop_loss_price'),
                'horizon_days': 20,
            })
            if ok:
                wrote += 1
        except Exception as exc:                               # noqa: BLE001
            failed += 1
            if failed <= 5:
                print(f'  [실패] {sym} — {type(exc).__name__}: '
                      f'{str(exc)[:60]}')
        if i % 10 == 0:
            el = time.time() - t0
            print(f'  {i}/{len(pool)} · 기록 {wrote} · {el:,.0f}s', flush=True)

    # 실패를 삼키더라도 집계로는 남긴다
    print(f'\n기록 {wrote}건 · 실패 {failed}건 / 대상 {len(pool)}종목')
    if pool and wrote == 0:
        print('한 건도 기록하지 못했다 — 통과가 아니라 미측정이다.')
        return 1
    return 0


if __name__ == '__main__':
    _utf8_stdout()
    sys.exit(main())
