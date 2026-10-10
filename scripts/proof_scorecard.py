# -*- coding: utf-8 -*-
"""가늠 PROOF 성적표를 만든다 — 남긴 판정 전부를 같은 채점기로 채점하고 **수만** 담는다 (라운드 418).

    python scripts/proof_scorecard.py            # 채점하고 .portfolio/proof_scorecard.json 에 쓴다
                                                 # · 배포용 data/ 동봉본도(종목코드 모양이 없을 때만 · 라운드 420)
    python scripts/proof_scorecard.py --dry-run  # 채점만 하고 안 쓴다

규칙은 `proof` 모듈 머리에 고정돼 있다(같은 채점기 · 운영 비용 · 판정 1건에 같은 금액 · 문턱 없음).
이 PC 의 평일 장 마감 뒤 작업(`scripts/nightly_local.py`)이 돈다. 일봉은 종목마다 한 번 받는다.
`GAEUM_NO_LOCAL_WRITE` 면 쓰지 않는다(§9).
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import sqlite3
import sys
import time

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:                                              # noqa: BLE001
    pass
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)
os.chdir(PROJ)

import proof                                                   # noqa: E402
import prediction_log as plog                                  # noqa: E402


def tracker_cases(db_path=None):
    """추적 DB 의 케이스 — 복사본·픽스처·휴장일 기준일은 뺀다(`case_tracker.tally` 와 같은 규칙 · §4)."""
    from improvement import case_tracker as ct
    p = db_path or os.path.join(PROJ, '.portfolio', 'improvement.db')
    if not os.path.exists(p):
        return []
    c = sqlite3.connect(p)
    try:
        rows = c.execute('SELECT ticker, signal_date, status, realized_return FROM prediction_cases').fetchall()
    finally:
        c.close()
    return [dict(ticker=t, signal_date=str(d)[:10], status=s, realized_return=r) for t, d, s, r in rows
            if s not in ct.EXCLUDED_STATUSES and not ct.is_non_trading_date(str(d)[:10])]


# 라운드 475 — 종전 `report_checks`(파일 이름 순 첫 파일의 조건 목록 · `setdefault`)는 걷었다. 운영체제가 돌려주는 파일 순서에
#   기댔고 추적 케이스를 만든 판과 다를 수 있었다 — 짝은 `proof.origin_cores` 한 곳이 정한다.


def load_reports(pm_dir=None):
    """날짜별 개장 전 리포트 원본(같은 날 여러 판은 `proof.reco_summary` 가 늦은 판 하나로 · 결과 짝은 `proof.origin_cores`)."""
    out = []
    for f in glob.glob(os.path.join(pm_dir or os.path.join(PROJ, '.portfolio'), 'premarket_2*.json')):
        try:
            with open(f, encoding='utf-8') as fh:
                out.append(json.load(fh))
        except Exception:                                      # noqa: BLE001
            continue
    return out


def load_history(path=None):
    """개장 전 리포트 이력(추가 전용 · 시간 순) — 추적 동결이 읽는 그 파일(라운드 475 · `proof.origin_cores` 의 재료). 못 읽은 줄은 건너뛴다."""
    p = path or os.path.join(PROJ, '.portfolio', 'premarket_history.jsonl')
    rows = []
    if not os.path.exists(p):
        return rows
    with open(p, encoding='utf-8') as fh:
        for ln in fh:
            try:
                rows.append(json.loads(ln))
            except Exception:                                  # noqa: BLE001
                continue
    return rows


def load_registry(path=None):
    """전방 기록부 — 매일 상위 60종목의 엔진 판정(라운드 433 · 정밀분석을 더 깊게 했을 때의 답). 못 읽은 줄은 건너뛴다."""
    p = path or os.path.join(PROJ, '.portfolio', 'forward_registry.jsonl')
    rows = []
    if not os.path.exists(p):
        return rows
    with open(p, encoding='utf-8') as fh:
        for ln in fh:
            try:
                rows.append(json.loads(ln))
            except Exception:                                  # noqa: BLE001
                continue
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args(argv)
    write = not a.dry_run and not os.environ.get('GAEUM_NO_LOCAL_WRITE')
    t0 = time.time()
    rows = plog.load_predictions()
    tickers = sorted({str(r.get('ticker')) for r in rows if r.get('ticker')})
    print(f'판정 원장 {len(rows):,}건 · 종목 {len(tickers)} · 쓰기 {"함" if write else "안 함"}', flush=True)
    from bitemporal_engine import BitemporalEngine
    eng = BitemporalEngine()
    bars, fail = {}, []
    for i, tk in enumerate(tickers, 1):
        try:
            bars[tk] = proof.bars_frame(eng.fetch_daily_bars(tk))
        except Exception as ex:                                # noqa: BLE001
            bars[tk] = None
            fail.append((tk, f'{type(ex).__name__}'))
        if i % 50 == 0:
            print(f'  일봉 {i}/{len(tickers)} · {time.time() - t0:.0f}초', flush=True)
    graded = [(r, proof.outcome(r, bars.get(str(r.get('ticker'))))) for r in rows]
    ab = proof.abstain_tally(graded)
    by_action = {}
    for act in sorted({str(r.get('action')) for r in rows}):
        by_action[act] = proof.abstain_tally([(r, o) for r, o in graded if str(r.get('action')) == act])
    st = collections.Counter((o or {}).get('status', 'nobars') for _r, o in graded)
    # 라운드 433 — "추천주가 거의 없지 않았어?" — 얼마나 자주 0 이었나 · 깊게 봐도 0 인가 · 그 후보를 다 샀다면
    from improvement import case_tracker as _ct
    _reports = load_reports()
    reco = proof.reco_summary(_reports, load_registry(), is_off_day=_ct.is_non_trading_date)
    # 라운드 475 — 결과를 세는 셈 셋(조건별 장부 · 다 샀다면 · 기대값 순서)은 **그 케이스를 만든 판**과 짝짓는다(`proof.origin_cores`
    #   한 곳). 종전엔 장부가 파일 이름 순 첫 파일, '다 샀다면'이 날짜마다 마지막 판을 읽어 '하나만 막은 후보'가 판에 따라 부호까지
    #   갈렸다. 추천 빈도는 리포트 내용을 세므로 마지막 판 그대로다.
    _cases = tracker_cases()
    _cores, _n_first = proof.origin_cores(load_history(), _reports)
    _ck = proof.checks_map(_cores)
    gates = proof.gate_ledger(_cases, _ck)
    cands = proof.candidate_outcome(_cases, _ck)
    # 라운드 475 — "너무 보수적 아니야?" — 그날 기대값이 높았던 후보가 실제로 더 벌었나(문턱을 낮추면 무엇을 사나)
    evo = proof.ev_order(_cases, proof.ev_map(_cores))
    _dec = [c for c in _cases if c['status'] in ('success', 'failure', 'unresolved')]
    pairing = dict(rule='추적 케이스를 만든 판(이력의 첫 줄 · 같은 생성 시각의 리포트)', history_keys=_n_first,
                   matched_keys=len(_cores), decided=len(_dec),
                   decided_paired=sum(1 for c in _dec if (proof.code6(c['ticker']), c['signal_date']) in _ck))
    # 라운드 477 — 사전등록 R475(이 조건이 막은 후보를 앞으로의 자료로 판정)의 진행 — 채점기의 구간 셈을 그대로 부른다(결과를 안 읽는다 ·
    #   센 날 / 하한). 화면이 '앞으로의 자료로 판정 중'을 같은 줄에 적게. 못 부르면 None(§3).
    try:
        import gate_forward_r475 as _gf
        _gend, _gcnt = _gf.window_end(_cores, is_off=_ct.is_non_trading_date)
        gate_forward = dict(gate=_gf.GATE, start=_gf.FROM, floor=_gf.DATE_FLOOR, counted=_gcnt, end=_gend,
                            closes_on=(_gf.nth_trading_day(_gend, _gf.H, _ct.is_non_trading_date) if _gend else None),
                            prereg='docs/PREREG_R475_EV_GATE_FORWARD.md')
    except Exception as _ex477:                                # noqa: BLE001
        print(f'R475 진행 셈 못 함 — {type(_ex477).__name__}')
        gate_forward = None
    doc = dict(made=proof.now_iso(), ledger_rows=len(rows), tickers=len(tickers),
               bars_ok=sum(1 for v in bars.values() if v is not None), bars_fail=len(fail),
               status=dict(st), abstain=ab, by_action=by_action, gates=gates, reco=reco, candidates=cands,
               ev_order=evo, pairing=pairing, gate_forward=gate_forward,
               tracker_decided=sum(1 for c in tracker_cases() if c['status'] in ('success', 'failure', 'unresolved')),
               rule=('같은 채점기(기록 가격 진입 · 먼저 닿은 선 · 같은 봉이면 손절 먼저 · 20봉 만료면 그날 종가) · '
                     f"운영 비용 {ab.get('cost_pct')}% 차감 · 판정 1건에 같은 금액 · 문턱 없음"),
               seconds=round(time.time() - t0, 1))
    print(proof.abstain_line(ab))
    print(proof.reco_line(doc) or '추천 빈도 — 셀 리포트가 없다')
    if gates:
        print(proof.gate_line(doc, gates[0]['name']) or f"'{gates[0]['name']}' — 막은 후보 없음")
    print('결과 갈래', dict(st), '· 일봉 실패', len(fail))
    for act, t in by_action.items():
        print(f'  {act}: 결정 {t["decided"]} · 평균 {t["mean_net"]} · 중앙 {t["median_net"]}')
    print('규칙 원장(앞 6)')
    for g in gates[:6]:
        b, p = g['blocked'], g['passed']
        print(f"  {g['name']}: 막음 n {b['n']} 평균 {b['mean_net'] if b['mean_net'] is None else round(b['mean_net'], 2)}"
              f" · 통과 n {p['n']} 평균 {p['mean_net'] if p['mean_net'] is None else round(p['mean_net'], 2)}")
    if write:
        proof.save_scorecard(doc)
        print('썼다', proof.SCORECARD_FILE)
        # 라운드 420 — 배포 앱이 읽는 동봉본(data/)도 같이 — 종목코드 모양이 있으면 쓰지 않는다(§9)
        _sp420, _why420 = proof.ship_scorecard(doc)
        print(_why420 + (f' · {_sp420}' if _sp420 else ''))
    print(f'{doc["seconds"]}초')
    return 0


if __name__ == '__main__':
    sys.exit(main())
