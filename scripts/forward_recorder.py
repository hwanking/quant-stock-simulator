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


def clock_notes(t_ref, now=None):
    """기록기가 기준일을 믿어도 되는지 — (머리 줄, [경고]) (라운드 437).

    ⚠️ 라운드 86 이 넣은 경고는 기준일을 **'달력상 최근 거래일'** — 오늘이 거래일이면 장이 열리기 전이어도 오늘 — 과
    견줬다. 예약 지연으로 기록기가 자정 뒤에 도는 날(2026-10-06 01:59 KST 실측)이면 기준일은 옳게 직전 거래일인데도
    *"뒤처졌다 · 시계가 KST 가 아닐 수 있다 · TZ 를 확인한다"* 가 찍혔다 — 거짓 경보이고 원인을 엉뚱한 데(TZ)로 보낸다.
    라운드 86 이 잡으려던 원인은 **시계의 UTC 오프셋**이므로 그것을 직접 보고(+09:00 이 아니면 경고), 기준일은 **마지막으로
    정규장이 끝난 거래일**(`scripts.trading_day.anchor_day` · 라운드 283 의 판정일 · 같은 휴장일 표·마감 시각)과 견준다.
    판정일을 못 구하면 견주지 않는다고 적는다(§3).
    """
    import datetime as _dt
    now = now or _dt.datetime.now().astimezone()
    if now.tzinfo is None:
        now = now.astimezone()
    off = now.utcoffset()
    notes = []
    if off != _dt.timedelta(hours=9):
        notes.append(f'⚠ 시계가 KST 가 아니다 (UTC{now:%z}) — 엔진은 지역 시각을 KST 로 읽는다. 기준일이 하루 밀려 '
                     f'어제 것을 다시 찍고 중복 방지에 걸려 아무것도 안 쌓일 수 있다 — TZ 를 확인한다.')
    try:
        from scripts.trading_day import anchor_day
        anchor = anchor_day(now)
    except Exception:                                          # noqa: BLE001
        anchor = None
    head = (f'  시계 {now:%Y-%m-%d %H:%M} (UTC{now:%z}) · 마지막으로 장이 끝난 거래일 {anchor}' if anchor else
            f'  시계 {now:%Y-%m-%d %H:%M} (UTC{now:%z}) · 마지막으로 장이 끝난 거래일을 못 구해 기준일과 견주지 않는다')
    if anchor and str(t_ref) != anchor:
        notes.append(f'⚠ 기준일 {t_ref} 이 마지막으로 장이 끝난 거래일 {anchor} 과 다르다 — 이대로면 그날 것을 못 쌓거나 '
                     f'이미 기록된 날을 다시 찍는다.')
    # 라운드 487 — 그날 봉이 아직 움직이는 시각이면 적는다. 2026-09-14 부터 우리가 받는 종가·일봉 종가는 KRX 애프터마켓
    #   (16:00~20:00) 마지막 체결이다(라운드 486 · 10-08 봉 60/60). 예약 지연으로 지금은 23:30 KST 뒤에 돌지만 지연이 3시간
    #   밑으로 줄면 17:00~20:00 의 미완성 봉으로 기록한다 — 크론은 안 옮긴다(긴 지연 726분이 다음 장에 걸린다 · 라운드 283).
    #   판정은 엔진 `bar_final` 한 곳 · 시계가 KST 일 때만(아니면 위 경고가 먼저다) · 기록은 막지 않는다(그날은 다시 못 만든다).
    if off == _dt.timedelta(hours=9):
        try:
            import bitemporal_engine as _be
            local = now.replace(tzinfo=None)
            if not _be.bar_final(local):
                end = _be.after_market_end(local.date())
                st = _be.get_market_status(local).get('state')
                why = '정규장 중' if st == '장중' else (f'애프터마켓 {end:%H:%M} 끝 전' if end else '장 마감 직후')
                notes.append(f'⚠ 그날 봉이 아직 확정 전이다({local:%H:%M} · {why}) — 이 기록은 아직 움직이는 종가로 잰 것이다. '
                             f'2026-09-14 부터 종가는 애프터마켓 마감가다.')
        except Exception:                                      # noqa: BLE001
            pass
    return head, notes


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
    #   라운드 437 — 견주는 상대를 '달력상 최근 거래일'에서 '마지막으로 장이 끝난 거래일'로 · TZ 는 오프셋을 직접(`clock_notes`).
    _head437, _notes437 = clock_notes(t_ref)
    print(_head437)
    for _n437 in _notes437:
        print('  ' + _n437)

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
    _op404 = {}                             # 라운드 404 — 종목 → (기준일, 운영 판) · 그림자 기록이 읽는다
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
            # 라운드 404 — 교정본 그림자 기록이 견줄 **운영 판**을 여기서 옮겨 둔다(계산 없음 · 기록부와 같은 값).
            #   실패해도 운영 기록은 이미 끝났다.
            try:
                import forward_shadow as _fsh404
                _op404[sym] = (str(snap.get('t_ref') or t_ref), _fsh404.side(snap, vc_row))
            except Exception:                                  # noqa: BLE001
                pass
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
    # ── 라운드 341 — 재무 시점 보관: 오늘 정밀분석한 종목의 연간 재무 응답을 **오늘 날짜로** 남긴다.
    #   라운드 336·339 — 응답은 이미 받아 뒀고(추가 네트워크 0) 소급이 안 되는 자료라 시작한 날부터만 쌓인다.
    #   실패해도 판정 기록은 안 죽는다(따로 세어 찍는다 · §3). 범위는 이 기록기가 본 종목(상위 {top})뿐이다.
    try:
        import fin_pit
        _pit_rows = fin_pit.rows_from(getattr(be, 'ANNUAL_FIN_BY_CODE', {}), t_ref)
        _pit_w, _pit_s = fin_pit.append_rows(fin_pit.PATH, _pit_rows)
        _pit_cov = fin_pit.coverage(fin_pit.PATH)
        print(f'재무 시점 보관 — 오늘 {_pit_w}줄 새로 · 이미 있음 {_pit_s}줄 · 받은 응답 없음 '
              f'{len(getattr(be, "ANNUAL_FIN_BY_CODE", {})) - len(_pit_rows)}종목 → 누적 {_pit_cov["rows"]:,}줄 · '
              f'종목 {_pit_cov["codes"]} · 날짜 {_pit_cov["dates"]} ({_pit_cov["first"]} ~ {_pit_cov["last"]})')
    except Exception as _pit_e:                                  # noqa: BLE001
        print(f'재무 시점 보관 실패 — {type(_pit_e).__name__}: {_pit_e} (판정 기록과 무관 · 오늘 몫은 못 남겼다)')
    # ── 라운드 342 — 잔여 호가(5단) 시점 보관. 소급이 안 되는 자료라 같은 자리에서 같이 남긴다.
    #   밤에 도는 이 기록기가 받는 것은 **시간외 마감 뒤 남은 호가**다(정규장 마감 호가·체결강도가 아니다).
    #   받은 시각·장 상태를 같이 적는다. 판정에 안 들어간다 · 실패해도 판정 기록은 안 죽는다.
    try:
        import datetime as _dt342
        import book_pit
        import stock_code as _sc342
        _bk_codes = [_sc342.strip_suffix(u['symbol']) for u in uni[:top]]
        _bk_basic = (be.fetch_json_with_retry(f"{be.NAVER_MOBILE_API}/stock/{_bk_codes[0]}/basic", timeout=6, retries=2)
                     if _bk_codes else None)
        _bk_status = (_bk_basic or {}).get('marketStatus')
        _bk_rows, _bk_fail = book_pit.rows_for(
            _bk_codes, t_ref, _dt342.datetime.now().astimezone().isoformat(timespec='seconds'), _bk_status)
        _bk_w, _bk_s = book_pit.append_rows(book_pit.PATH, _bk_rows)
        _bk_cov = book_pit.coverage(book_pit.PATH)
        print(f'잔여 호가 시점 보관 — 오늘 {_bk_w}줄 새로 · 이미 있음 {_bk_s}줄 · 못 받음 {_bk_fail}종목 · 장 상태 {_bk_status} '
              f'→ 누적 {_bk_cov["rows"]:,}줄 · 날짜 {_bk_cov["dates"]}')
    except Exception as _bk_e:                                   # noqa: BLE001
        print(f'잔여 호가 시점 보관 실패 — {type(_bk_e).__name__}: {_bk_e} (판정 기록과 무관 · 오늘 몫은 못 남겼다)')
    # ── 라운드 404 — 교정본 그림자 기록 (사용자 결정 2026-10-01 · 사전등록 docs/PREREG_R404_SHADOW_CORRECTIONS.md).
    #   운영 기록(판정 원장·전방 기록부·시점 보관)이 **전부 끝난 뒤** 따로 만든 엔진 인스턴스에만 고침 다섯을 켜서
    #   같은 기준일로 다시 판정하고 운영 판과 나란히 적는다. 운영 엔진(`q`)은 스위치가 꺼진 채 이미 끝났다 —
    #   그림자가 무엇을 하든 오늘의 운영 기록을 못 바꾼다. 실패해도 판정 기록과 무관하다(따로 세어 찍는다 · §3).
    #   운영 판이 없는 종목(오늘 이미 기록돼 이번 실행이 건너뛴 종목)은 그림자도 건너뛴다 — 다른 계산에서 온 운영 값과
    #   견주지 않는다.
    try:
        import forward_shadow as _fsh
        _q404 = qi.QuantIndicatorsEngine()
        _q404.corrections = frozenset(_fsh.CORRECTIONS)
        _st404 = _fr.stamp().get('versions')
        _rows404, _fail404, _t404 = [], 0, time.time()
        for _sym404, (_d404, _op) in _op404.items():
            try:
                _snap404 = _q404.run_full_pipeline(_sym404, t_ref, b_engine=eng, rho_cutoff=0.80)
                _vd404 = _q404.build_final_verdict(_snap404)
                _vc404 = _vc.build(_snap404['four_scores'], verdict=_vd404,
                                   price_axes=_snap404['four_scores'].get('price_axes'),
                                   next_action=_snap404.get('next_action'), corrections=_fsh.CORRECTIONS)
                import stock_code as _sc404
                _rows404.append(_fsh.make_row(_sc404.strip_suffix(_sym404), _d404, _op,
                                              _fsh.side(_snap404, _vc404), versions=_st404))
            except Exception as _e404:                         # noqa: BLE001
                _fail404 += 1
                if _fail404 <= 3:
                    print(f'  [그림자 실패] {_sym404} — {type(_e404).__name__}: {str(_e404)[:60]}')
        _w404, _s404 = _fsh.append_rows(_fsh.PATH, _rows404)
        _cov404 = _fsh.coverage(_fsh.PATH)
        _chg404 = sum(1 for r in _rows404 if r['diff'])
        print(f'교정본 그림자 기록({_fsh.SPEC} · {"·".join(_fsh.CORRECTIONS)}) — 대상 {len(_op404)}종목 · 오늘 '
              f'{_w404}줄 새로 · 이미 있음 {_s404}줄 · 실패 {_fail404} · 값이 달라진 행 {_chg404}/{len(_rows404)} · '
              f'{time.time() - _t404:,.0f}s → 누적 {_cov404["rows"]:,}줄 · 날짜 {_cov404["dates"]}')
    except Exception as _sh_e:                                   # noqa: BLE001
        print(f'교정본 그림자 기록 실패 — {type(_sh_e).__name__}: {_sh_e} (판정 기록과 무관 · 오늘 몫은 못 남겼다)')
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
