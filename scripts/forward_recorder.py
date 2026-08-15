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
    import forward_registry as _fr
    import prediction_log as plog
    import quant_indicators as qi
    import verdict_core as _vc

    eng = be.BitemporalEngine()
    q = qi.QuantIndicatorsEngine()
    t_ref = be.resolve_analysis_date().strftime('%Y-%m-%d')
    print(f'전방 판정 기록 — 기준일 {t_ref} · 상위 {top}종목')

    # ⚠️ 라운드 86 — 기준일이 **뒤처졌는지** 여기서 밝힌다.
    #   resolve_analysis_date 는 now() 가 KST 라고 가정한다. 클라우드
    #   러너는 UTC 라 08:00 을 '장 시작 전'으로 읽고 직전 거래일을 줬다.
    #   그러면 매일 어제 날짜를 찍고 중복 방지에 걸려 **아무것도 안 쌓인다.**
    #   실제로 predictions.jsonl 이 171 에서 멈춰 있었다 — 축소가 아니라
    #   정체라 가드도 못 잡았다. 이제 눈에 보이게 적는다.
    import datetime as _dt
    _now = _dt.datetime.now()
    _cal = be.KrxCalendar()
    _latest = (_now.date() if _cal.is_trading_day(_now.date())
               else _cal.previous_trading_day(_now.date()))
    print(f'  시계 {_now:%Y-%m-%d %H:%M} · 달력상 최근 거래일 {_latest}')
    if t_ref < _latest.strftime('%Y-%m-%d'):
        print(f'  ⚠ 기준일이 최근 거래일({_latest})보다 뒤처졌다. '
              f'시계가 KST 가 아닐 수 있다 (러너는 UTC). '
              f'이대로면 어제 것을 다시 찍고 중복 방지에 걸려 '
              f'아무것도 안 쌓인다 — TZ 를 확인한다.')

    # 이미 오늘 기록한 종목은 건너뛴다 (하루 여러 번 돌아도 안전)
    # ⚠️ 라운드 97 — 여기가 predictions.jsonl 만 보고 있었다. 전방 기록부를
    #   새로 붙인 날에는 **모든 종목이 이미 옛 원장에 있으므로** 건너뛰게
    #   되고, 새 기록부는 영영 0건으로 남는다. 실측으로 그렇게 나왔다
    #   (오늘 62종목 전부 건너뜀 → 기록부 0건).
    #   원장이 둘이면 '이미 했다'도 **둘 다** 봐야 한다.
    _pred_done, _reg_done = set(), set()
    for r in plog.load_predictions():
        if str(r.get('date'))[:10] == t_ref:
            _pred_done.add(str(r.get('ticker')))
    for r in _fr.load():
        if str(r.get('date'))[:10] == t_ref:
            _reg_done.add(str(r.get('ticker')))
    done = _pred_done & _reg_done          # 둘 다 있는 것만 건너뛴다
    print(f'  오늘 이미 기록됨 — 판정원장 {len(_pred_done)}종목 · '
          f'전방기록부 {len(_reg_done)}종목 → 건너뛸 것 {len(done)}종목')

    try:
        uni = eng.get_screener_universe(full_market=True, max_pages=40)
    except Exception as exc:                                   # noqa: BLE001
        # 유니버스를 못 받으면 **기록하지 않는다.** 임의 종목으로 채우면
        # 그 날의 '추천'이 무엇이었는지 왜곡된다 (§3).
        print(f'유니버스 수신 실패 — 오늘은 기록하지 않는다: '
              f'{type(exc).__name__}: {exc}')
        return 1
    # 종목명은 유니버스에 있다 — 스냅샷에는 없다.
    # (라운드 97: 옛 기록은 이름 자리에 티커를 넣고 있었다)
    names = {str(u['symbol']): str(u.get('name') or '') for u in uni}
    pool = [u['symbol'] for u in uni[:top] if u['symbol'] not in done]
    print(f'  대상 {len(pool)}종목 (전 종목 {len(uni):,} 중 상위 {top})')

    t0, wrote, failed = time.time(), 0, 0
    reg_wrote, reg_bad = 0, 0
    for i, sym in enumerate(pool, 1):
        try:
            snap = q.run_full_pipeline(sym, t_ref, b_engine=eng,
                                       rho_cutoff=0.80)
            fs = snap['four_scores']
            vd = q.build_final_verdict(snap)
            # 앱과 같은 필드·같은 출처 (web_app.py 판정 기록 블록)
            # ⚠️ 여기 target/stop 은 **보유자 값**이다(target_tech_1st ·
            #   stop_loss_price). 옛 규약이라 그대로 두지만, 전방 재평가는
            #   아래 forward_registry 를 읽는다 — 거기서는 신규 매수자
            #   값과 보유자 값이 다른 키로 갈려 있다 (§4).
            ok = plog.record_prediction({
                'ticker': sym,
                'name': (names.get(sym) or sym),
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

            # ── 전방 기록부 (라운드 97) ──────────────────────────────
            #   화면이 읽는 그 함수로 값을 만든다 — 경로가 둘이면 갈린다(§4).
            vc_row = _vc.build(fs, verdict=vd,
                               price_axes=fs.get('price_axes'),
                               next_action=snap.get('next_action'))
            reg_ok, reg_why = _fr.record(
                _fr.build_row(sym, snap, vc_row, name=names.get(sym)))
            if reg_ok:
                reg_wrote += 1
            elif reg_why and '이미 있다' not in reg_why[0]:
                reg_bad += 1
                if reg_bad <= 5:
                    print(f'  [기록부 거부] {sym} — {reg_why[:2]}')
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
    cov = _fr.coverage()
    print(f'전방 기록부 {reg_wrote}건 추가 · 규약 거부 {reg_bad}건 '
          f'→ 누적 {cov["n"]:,}건 (규약 통과 {cov["valid"]:,}건 · '
          f'신규 레벨 있음 {cov["with_new_levels"]:,}건)')
    # ⚠️ 라운드 97 — 여기가 `wrote == 0` 하나로 실패를 판정했다. 원장이
    #   둘이 되면서 **한쪽은 이미 다 있고 다른 쪽만 새로 쌓는 날**이
    #   정상인데 그걸 실패로 읽었다(실측: 기록부 6건을 넣고도 종료코드 1).
    #   각 원장에 **쓸 것이 있었는데 못 썼는가**로 따로 본다.
    _pred_todo = [s for s in pool if s not in _pred_done]
    _reg_todo = [s for s in pool if s not in _reg_done]
    bad = []
    if _pred_todo and wrote == 0:
        bad.append(f'판정 원장: 쓸 것 {len(_pred_todo)}종목인데 0건')
    if _reg_todo and reg_wrote == 0:
        bad.append(f'전방 기록부: 쓸 것 {len(_reg_todo)}종목인데 0건')
    if bad:
        print('한 건도 기록하지 못했다 — 통과가 아니라 미측정이다: '
              + ' · '.join(bad))
        return 1
    if reg_bad:
        print(f'전방 기록부가 규약으로 {reg_bad}건을 거부했다 — '
              f'11/16 에 읽을 수 없는 행이다.')
        return 1
    return 0


if __name__ == '__main__':
    _utf8_stdout()
    sys.exit(main())
