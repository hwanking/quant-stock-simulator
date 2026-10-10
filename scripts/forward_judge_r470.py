# -*- coding: utf-8 -*-
"""
라운드 470 — 11-16 에 잴 두 약속의 채점기 (R346 청산 후보 전방 · R404 그림자 R0). 사전등록 docs/PREREG_R470_FORWARD_GRADERS.md.

■ 결과 전에 짠다 — 그날 손으로 짜면 결과를 보며 짠다(라운드 398 이 R55·R57·R66 에서 막은 그 오염).
■ 새로 정한 것이 없다 — 기준은 R346·R404 사전등록 원문 그대로이고, 관문·구간·채점·통계 행은 이미 있는 것을 부른다:
    관문 `forward_judge.judge_gate` · 박제 대조 `forward_judge.pin_drift` · 기록 구간 `forward_judge.record_window`
    채점 `prediction_log.grade_prediction`(후보는 같은 함수에 목표만 비움) · 통계 행 `ledger_view.stat_rows` · 간격 `ledger_view.too_close`
■ 재평가일 전에는 판정하지 않고 **자료를 읽지 않는다**(자료 공급자를 부르지 않는다 · 앞당기는 옵션 없음).
■ 라운드 474 정정(2026-10-10 · 결과 전 · 사전등록 R470 의 '라운드 474 정정' 절) — R346 의 표본 구간을 라운드 398 의 45거래일로
  묶으면 매수권 날이 하한 30 에 구조적으로 못 닿는다(결정 시점 칸으로 센 날 13 · 구간 끝까지 다 기록돼도 미달). 구간 끝을
  `r346_window_end` 가 결과를 안 읽고 정하고(라운드 398 의 끝 또는 하한에 닿는 날 중 늦은 쪽), 그 끝의 20봉이 닫히기 전에는
  채점하지 않는다. 기준(하한 30 · R1 · R2 · 갈래)은 한 글자도 안 바꿨다.

    C:/Python314/python.exe scripts/forward_judge_r470.py
      종료 코드 — 0 판정함 · 2 미측정(재평가일 전) · 1 오류
"""
from __future__ import annotations

import datetime as _dt
import importlib.util
import io
import json
import os
import random
import sys
from collections import Counter

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
sys.path.insert(0, PROJ)
import ledger_view as _lv                                      # noqa: E402
import prediction_log as _plog                                 # noqa: E402

_spec = importlib.util.spec_from_file_location('forward_judge_r398', os.path.join(HERE, 'forward_judge.py'))
FJ = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(FJ)

#: R346 원문 — 날짜 하한(R84·R45 재사용) · 부트스트랩 · 시드
R346_DATE_FLOOR = 30
R346_BOOT, R346_SEED = 2000, 346
#: R404 원문 — 그림자 기록 시작일(사전등록 §4 "2026-10-01 에 시작하면") · R0a 를 이루는 판정 칸
R404_FROM = '2026-10-01'
R404_VERDICT_FIELDS = ('recommended', 'bucket', 'action')
SHADOW = os.path.join(PROJ, '.portfolio', 'forward_shadow.jsonl')


# ══ R346 전방 ══════════════════════════════════════════════════════════
def _r346_decision_ok(r):
    """결정 시점 칸만 — 매수권 하한 · 보유자 레벨 · 가격. 결과·봉은 안 읽는다."""
    try:
        if float(r.get('score')) < _lv.BUY_ZONE_SCORE:
            return False
    except (TypeError, ValueError):
        return False
    return r.get('hold_trim') is not None and r.get('hold_stop') is not None and bool(r.get('price'))


def r346_window_end(reg_rows, first, last398, floor=R346_DATE_FLOOR):
    """(R346 표본의 끝 날짜 또는 None, 그날까지 센 매수권 날 수) — 라운드 474 정정 · 결과 전.

    라운드 398 의 기록 구간(45거래일)으로는 매수권 날이 하한 30 에 **구조적으로 못 닿는다** — 2026-10-08 까지 기록된 23일 중
    매수권 행이 있는 날 20 · 구간 끝(10-16)까지 남은 거래일 5 → 최대 25(R253 의 결손 16일 탓). 그대로 두면 11-16 판정은 결과와
    무관하게 '미측정'이다. 그래서 구간을 **라운드 398 의 끝 또는 그 뒤 매수권 날이 하한에 닿는 날 중 늦은 쪽**까지로 둔다.

    읽는 칸은 날짜·종목·점수·price·hold_trim·hold_stop 뿐이다 — 결과(수익·결과)와 봉은 안 읽는다(멈추는 규칙이 결과를 보면
    선택 편향이다). 거르는 순서는 `r346_rows` 의 결정 시점 부분과 같다(매수권 하한 · 레벨·가격 · 같은 종목·날짜 복사본 ·
    같은 종목 35일 간격). 진입가 축척(그날 봉 종가와 대조)과 20봉 닫힘은 봉이 있어야 해서 채점 때 다시 거른다 — 거기서 하한
    아래로 내려가면 미측정이다(하한을 안 내린다). 아직 닿지 않았으면 (None, 센 날 수)."""
    seen, rows = set(), []
    for r in reg_rows:
        d = str(r.get('date') or '')[:10]
        if not d or d < first or not _r346_decision_ok(r):
            continue
        k = (_lv.code6(r.get('ticker')), d)
        if k in seen:
            continue
        seen.add(k)
        rows.append(k)
    rows.sort()
    last_d, days = {}, set()
    for code, d in rows:
        if code in last_d and _lv.too_close([last_d[code]], d):
            continue
        last_d[code] = d
        days.add(d)
    ordered = sorted(days)
    in398 = [d for d in ordered if d <= last398]
    if len(in398) >= floor:
        return last398, len(in398)
    if len(ordered) >= floor:
        return ordered[floor - 1], floor
    return None, len(ordered)


def r346_rows(reg_rows, bars_by_ticker, first, last):
    """기록부 행 → [(종목, 날짜, Δ, 현행 수익, 후보 수익, 현행 결과, 후보 결과)] 과 빠진 사유별 수. 매수권 · 20봉 닫힘 · 통계 행 · 35일 간격."""
    why = Counter()
    graded = []
    for r in FJ.in_window(reg_rows, first, last):
        try:
            if float(r.get('score')) < _lv.BUY_ZONE_SCORE:
                continue
        except (TypeError, ValueError):
            why['점수 없음'] += 1
            continue
        if r.get('hold_trim') is None or r.get('hold_stop') is None or not r.get('price'):
            why['보유자 레벨·가격 없음'] += 1
            continue
        pdf = bars_by_ticker.get(str(r.get('ticker')))
        if pdf is None:
            why['시세 미수신'] += 1
            continue
        base_in = {'date': str(r['date'])[:10], 'price': float(r['price']), 'target': float(r['hold_trim']),
                   'stop': float(r['hold_stop']), 'horizon_days': int(r.get('horizon_days') or FJ.H)}
        b = _plog.grade_prediction(base_in, pdf)
        c = _plog.grade_prediction(dict(base_in, target=None), pdf)
        if not b or not c or not b.get('matured') or not c.get('matured'):
            why['20봉 미경과'] += 1
            continue
        cl = FJ._closes(pdf).get(base_in['date'])
        graded.append({'ticker': str(r['ticker']), 'date': base_in['date'],
                       'entry_scale_off': _lv.entry_scale_off(r.get('price'), cl),
                       'b_ret': float(b['return_pct']), 'c_ret': float(c['return_pct']),
                       'b_out': b['outcome'], 'c_out': c['outcome']})
    cnt = {}
    kept = list(_lv.stat_rows(graded, counter=cnt))
    for k, lab in (('scale', '진입가 축척 어긋남(통계 제외)'), ('dup', '같은 종목·날짜 복사본(통계 제외)')):
        if cnt.get(k):
            why[lab] += cnt[k]
    kept.sort(key=lambda x: (_lv.code6(x['ticker']), x['date']))
    spaced, last_d = [], {}
    for x in kept:
        k = _lv.code6(x['ticker'])
        if k in last_d and _lv.too_close([last_d[k]], x['date']):
            why['같은 종목 35일 안(간격 규칙)'] += 1
            continue
        last_d[k] = x['date']
        spaced.append(x)
    return spaced, why


def _q(a, p):
    a = sorted(a)
    return a[min(len(a) - 1, max(0, int(round(p * (len(a) - 1)))))]


def r346_judge(rows):
    """원문 R0·R1·R2 를 전방 한 구간에 댄다. 날짜가 30 미만이면 미측정."""
    dates = sorted({x['date'] for x in rows})
    out = dict(n=len(rows), dates=len(dates), floor=R346_DATE_FLOOR)
    if len(dates) < R346_DATE_FLOOR:
        out.update(status='미측정', verdict=f'미측정 — 고유 기준일 {len(dates)} < 하한 {R346_DATE_FLOOR} (하한을 안 내린다)')
        return out
    # 부트스트랩은 R346 원 스크립트(scripts/exit_rule_r346.py)와 같은 방식 — random.Random(346) · 날짜를 재추출 ·
    # 정렬한 뒤 [2.5% 색인, 97.5% 색인 − 1]. 다른 난수기를 쓰면 '같은 기준'이 아니다.
    diffs = [x['c_ret'] - x['b_ret'] for x in rows]
    by = {}
    for x in rows:
        by.setdefault(x['date'], []).append(x['c_ret'] - x['b_ret'])
    ds = sorted(by)
    rnd = random.Random(R346_SEED)
    boots = []
    for _ in range(R346_BOOT):
        smp = [rnd.choice(ds) for _ in ds]
        boots.append(sum(v for d in smp for v in by[d]) / sum(len(by[d]) for d in smp))
    boots.sort()
    lo, hi = boots[int(0.025 * R346_BOOT)], boots[int(0.975 * R346_BOOT) - 1]
    mean, med = float(np.mean(diffs)), float(_q(diffs, 0.5))
    tgt = [x for x in rows if x['b_out'] == 'TARGET']
    out.update(base_mean=round(float(np.mean([x['b_ret'] for x in rows])), 3),
               cand_mean=round(float(np.mean([x['c_ret'] for x in rows])), 3),
               diff_mean=round(mean, 3), ci95=[round(lo, 3), round(hi, 3)], diff_median=round(med, 3),
               cand_better_pct=round(100.0 * sum(1 for v in diffs if v > 0) / len(diffs), 1),
               cand_worse_pct=round(100.0 * sum(1 for v in diffs if v < 0) / len(diffs), 1),
               target_then_stop_pct=(round(100.0 * sum(1 for x in tgt if x['c_out'] == 'STOP') / len(tgt), 1) if tgt else None),
               base_p05=round(_q([x['b_ret'] for x in rows], 0.05), 2), cand_p05=round(_q([x['c_ret'] for x in rows], 0.05), 2))
    r1 = mean > 0 and lo > 0
    r2 = med >= 0
    out['R1'], out['R2'] = r1, r2
    if r1 and r2:
        out.update(status='판정함', verdict='전방에서도 확인 — 룰북 변경 후보 확정 · 채택은 사람')
    elif mean > 0 and r2:
        out.update(status='판정함', verdict='전방에서 못 세움 — 후보 유지 · 현행 유지')
    else:
        out.update(status='판정함', verdict='전방에서 확인 안 됨 — 기각 · 현행 유지')
    return out


# ══ R404 R0 ════════════════════════════════════════════════════════════
def _sign(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return (f > 0) - (f < 0)


def r404_r0(rows, eval_date, cal=None):
    """원문 R0a·R0b·R0c 와 기록 하한. rows = 그림자 줄(sh-1). 줄의 diff 칸을 그대로 센다."""
    cal = cal or FJ._cal()
    lastd = (_dt.date.fromisoformat(str(eval_date)[:10]) - _dt.timedelta(days=1)).isoformat()
    sub = [r for r in rows if R404_FROM <= str(r.get('date'))[:10] <= lastd and r.get('spec') == 'sh-1']
    d, tdays = _dt.date.fromisoformat(R404_FROM), []
    while d.isoformat() <= lastd:
        if cal.is_trading_day(d):
            tdays.append(d.isoformat())
        d += _dt.timedelta(days=1)
    have = {str(r.get('date'))[:10] for r in sub}
    covered = sum(1 for t in tdays if t in have)
    out = dict(rows=len(sub), trading_days=len(tdays), days_with_rows=covered)
    if not tdays or covered * 2 < len(tdays):
        out.update(status='미측정', verdict=f'(다) 기록이 모자람 — 거래일 {len(tdays)} 중 그림자 줄이 있는 날 {covered}(절반 미만)')
        return out
    df = [set(r.get('diff') or []) for r in sub]
    r0a = sum(1 for s in df if s & set(R404_VERDICT_FIELDS))
    rel = []
    for r in sub:
        fo, fs = (r.get('op') or {}).get('fair'), (r.get('sh') or {}).get('fair')
        try:
            fo, fs = float(fo), float(fs)
        except (TypeError, ValueError):
            continue
        if fo > 0 and fs != fo:
            rel.append(fs / fo - 1.0)
    ev_flip = sum(1 for r in sub if _sign((r.get('op') or {}).get('expected_return')) is not None
                  and _sign((r.get('sh') or {}).get('expected_return')) is not None
                  and _sign((r.get('op') or {}).get('expected_return')) != _sign((r.get('sh') or {}).get('expected_return')))
    out.update(R0a=r0a, R0a_pct=round(100.0 * r0a / len(sub), 2) if sub else None,
               R0b_zone=sum(1 for s in df if 'entry_zone' in s), R0b_status=sum(1 for s in df if 'fair_status' in s),
               R0b_fair_rel_median=(round(float(np.median(rel)) * 100.0, 3) if rel else None), R0b_fair_changed=len(rel),
               R0c_score=sum(1 for s in df if 'score' in s), R0c_ev_sign=ev_flip, status='판정함')
    out['verdict'] = ('(가) 판정을 하나도 안 바꿨다 — 11-16 뒤 운영에 넣자고 제안(사람이 정한다)' if r0a == 0 else
                      '(나) 판정이 바뀐 줄이 있다 — 11-16 에는 채택하지 않고 R1 이 날짜 하한을 채운 날 판정')
    return out


def _jsonl(path):
    out = []
    try:
        with io.open(path, encoding='utf-8') as f:
            for ln in f:
                ln = ln.strip()
                if ln:
                    try:
                        out.append(json.loads(ln))
                    except ValueError:
                        pass
    except OSError:
        pass
    return out


def load_all(first, last):
    """재평가일에만 부른다 — 네트워크(일봉)를 쓴다. 기록부·그림자 줄과 일봉. last 가 None 이면 first 뒤 전부(라운드 474 —
    R346 구간의 끝은 기록부를 받은 뒤 `r346_window_end` 가 정한다)."""
    import bitemporal_engine as _be
    import forward_registry as _fr
    reg = FJ.in_window(_fr.load(), first, last or '9999-12-31')
    eng = _be.BitemporalEngine()
    bars, failed = {}, []
    for tk in sorted({str(r['ticker']) for r in reg}):     # 종목마다 한 번 — 실패도 한 번만 묻는다(R303)
        try:
            df = eng.fetch_daily_bars(tk)
        except Exception:                                      # noqa: BLE001
            df = None
        if df is None:
            failed.append(tk)                                  # 못 받은 수를 세어 찍는다(R37) — 채점에선 '시세 미수신'
        else:
            bars[tk] = df
    return dict(registry=reg, bars=bars, bars_failed=failed, shadow=_jsonl(SHADOW))


def r346_run(d, first, last398, today=None, cal=None):
    """R346 전방 한 번 — 구간 끝(결과 안 읽음) → 그 끝의 20봉이 닫혔나 → 채점. 닫히기 전에는 채점하지 않는다(결과를 안 본다)."""
    end, nd = r346_window_end(d.get('registry') or [], first, last398)
    base = dict(window=[first, end], floor=R346_DATE_FLOOR, bars_failed=d.get('bars_failed', []))
    if end is None:
        return dict(base, status='미측정', dates=nd,
                    verdict=f'미측정 — 결정 시점 칸으로 센 매수권 날 {nd} < 하한 {R346_DATE_FLOOR} '
                            f'(기록이 더 쌓여야 한다 · 하한을 안 내린다)')
    close = FJ.nth_trading_day(end, FJ.H + 1, cal)        # end 를 1번째로 셀 때 21번째 = end 뒤 20번째 거래일
    if today is None:
        from improvement.issue_ops import _today             # 지역 날짜 한 곳 (R306)
        today = _today()
    if close is None or str(today)[:10] < close:
        return dict(base, status='미측정', dates=nd, closes_on=close,
                    verdict=f'미측정 — 구간 마지막 기준일 {end} 의 20봉이 {close} 장 마감에 닫힌다 '
                            f'(그 전에는 채점하지 않는다 · 결과를 안 본다)')
    rows, why = r346_rows(d.get('registry') or [], d.get('bars') or {}, first, end)
    return dict(r346_judge(rows), dropped=dict(why), window=[first, end], closes_on=close,
                bars_failed=d.get('bars_failed', []))


def run(today=None, eval_date=None, data=None):
    ok, reason, ed = FJ.judge_gate(today, eval_date)
    first, last = FJ.record_window()
    res = dict(eval_date=ed, window=[first, last], status='미측정', reason=reason)
    if not ok:
        return res
    drift = FJ.pin_drift()
    if drift:
        res['reason'] = f'박제 파일이 바뀌었다 {drift} — 그때 정한 것을 그대로 잴 수 없어 평가가 성립하지 않는다'
        return res
    d = (data or load_all)(first, None)
    res['r346'] = r346_run(d, first, last, today)
    res['r404'] = r404_r0(d.get('shadow') or [], ed)
    res['status'] = '판정함'
    return res


def main(argv=None, today=None):
    res = run(today=today)
    sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0 if res.get('status') == '판정함' else 2


if __name__ == '__main__':
    sys.exit(main())
