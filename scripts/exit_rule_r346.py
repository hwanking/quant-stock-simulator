# -*- coding: utf-8 -*-
"""
라운드 346 — 목표를 없애고 손절만 지킨 채 창 끝까지 든다 (사전등록 docs/PREREG_R346_NO_TARGET_KEEP_STOP.md).

판정 기준은 그 문서에 **재기 전에** 적었다. 여기서는 그대로 잰다 — 기준을 다시 적지 않고 아래 상수로만 옮긴다.
규칙은 새로 짓지 않는다: 현행 = `prediction_log.first_touch(bars, target, stop)` · 후보 = 같은 함수에 목표만 None.
원장·경로는 **읽기만** 한다. 산출물: data/exit_rule_r346.json
"""
import glob
import io
import json
import os
import random
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
import ledger_view as lv                                       # noqa: E402
from prediction_log import first_touch                         # noqa: E402

LEDGER = os.path.join(PROJ, '.portfolio', 'virtual_graded.jsonl')
OUT = os.path.join(PROJ, 'data', 'exit_rule_r346.json')
SEED, BOOT = 346, 2000
DATE_FLOOR = 30              # R0 — 이미 채택된 하한 (R84·R45)
REPRO_MATCH = 99.0           # R-재현 — outcome 일치율 %
REPRO_RET = 0.05             # R-재현 — return_pct 평균 차이 %p
SPLITS = ('train', 'valid', 'blind')


def _paths():
    """(ticker, date) → bars[(hi, lo, close)] (가격으로 되돌린다 — 경로는 기준가 대비 % 다)."""
    out = {}
    for fp in sorted(glob.glob(os.path.join(PROJ, '.portfolio', 'bar_paths_s*.jsonl'))):
        with io.open(fp, encoding='utf-8') as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                r = json.loads(ln)
                px = r.get('price')
                if not px:
                    continue
                out[(r['ticker'], str(r['date'])[:10])] = [
                    (px * (1 + b[1] / 100.0), px * (1 + b[2] / 100.0), px * (1 + b[3] / 100.0))
                    for b in (r.get('bars') or [])[:lv.HORIZON_BARS]]
    return out


def _ret(outcome, entry, tp, sl, last_close):
    if outcome == 'TARGET':
        return (tp / entry - 1.0) * 100.0
    if outcome == 'STOP':
        return (sl / entry - 1.0) * 100.0
    return (last_close / entry - 1.0) * 100.0


def _q(a, p):
    a = sorted(a)
    return a[min(len(a) - 1, max(0, int(round(p * (len(a) - 1)))))]


def main():
    paths = _paths()
    rows = []
    n_buy = n_nopath = n_short = 0
    with io.open(LEDGER, encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            r = json.loads(ln)
            try:
                if float(r.get('score')) < lv.BUY_ZONE_SCORE or r.get('split') not in SPLITS:
                    continue
                entry, tp, sl = float(r['price']), float(r['target']), float(r['stop'])
            except (TypeError, ValueError, KeyError):
                continue
            n_buy += 1
            bars = paths.get((r['ticker'], str(r['date'])[:10]))
            if not bars:
                n_nopath += 1
                continue
            if len(bars) < lv.HORIZON_BARS:
                n_short += 1
                continue
            rows.append((r['ticker'], str(r['date'])[:10], r['split'], entry, tp, sl, bars,
                         r.get('outcome'), r.get('return_pct')))
    # 겹치지 않는 부분집합 — 같은 종목 35일 (ledger_view 규칙 · 날짜 오름차순 탐욕)
    rows.sort(key=lambda x: (x[0], x[1]))
    kept, last = [], {}
    for x in rows:
        prev = last.get(x[0])
        if prev is not None and lv.too_close([prev], x[1]):
            continue
        last[x[0]] = x[1]
        kept.append(x)

    res = dict(made=None, prereg='docs/PREREG_R346_NO_TARGET_KEEP_STOP.md', seed=SEED, boot=BOOT,
               counts=dict(buy_zone=n_buy, no_path=n_nopath, short_path=n_short, with_path=len(rows), spaced=len(kept)),
               splits={})
    import datetime
    res['made'] = datetime.date.today().isoformat()

    # R0
    by = {s: {} for s in SPLITS}
    match = tot = 0
    ret_diff = []
    for tk, d, sp, entry, tp, sl, bars, oc_led, ret_led in kept:
        oc0, _, _ = first_touch(bars, tp, sl)
        r0 = _ret(oc0, entry, tp, sl, bars[-1][2])
        oc1, _, _ = first_touch(bars, None, sl)
        r1 = _ret(oc1, entry, tp, sl, bars[-1][2])
        tot += 1
        match += int(oc0 == oc_led)
        try:
            ret_diff.append(r0 - float(ret_led))
        except (TypeError, ValueError):
            pass
        by[sp].setdefault(d, []).append((r0, r1, oc0, oc1))
    dates = {s: len(by[s]) for s in SPLITS}
    res['R0'] = dict(dates=dates, floor=DATE_FLOOR, ok=all(v >= DATE_FLOOR for v in dates.values()))
    res['repro'] = dict(n=tot, outcome_match_pct=round(100.0 * match / tot, 2) if tot else None,
                        ret_mean_diff=round(sum(ret_diff) / len(ret_diff), 4) if ret_diff else None)
    res['repro']['ok'] = bool(tot and res['repro']['outcome_match_pct'] >= REPRO_MATCH
                              and abs(res['repro']['ret_mean_diff']) <= REPRO_RET)
    if not res['R0']['ok']:
        res['verdict'] = '미측정 — R0(날짜 하한) 미달'
    elif not res['repro']['ok']:
        res['verdict'] = '중단 — R-재현 미달 (허용 오차를 늘리지 않는다)'
    else:
        rnd = random.Random(SEED)
        r1_ok, r2_ok, signs = [], [], []
        for sp in SPLITS:
            ds = sorted(by[sp])
            pairs = [p for d in ds for p in by[sp][d]]
            diffs = [p[1] - p[0] for p in pairs]
            n = len(diffs)
            mean = sum(diffs) / n
            boots = []
            for _ in range(BOOT):
                s = [rnd.choice(ds) for _ in ds]
                num = sum(p[1] - p[0] for d in s for p in by[sp][d])
                den = sum(len(by[sp][d]) for d in s)
                boots.append(num / den)
            boots.sort()
            lo, hi = boots[int(0.025 * BOOT)], boots[int(0.975 * BOOT) - 1]
            med = _q(diffs, 0.5)
            tgt = [p for p in pairs if p[2] == 'TARGET']
            res['splits'][sp] = dict(
                n=n, dates=len(ds), base_mean=round(sum(p[0] for p in pairs) / n, 3),
                cand_mean=round(sum(p[1] for p in pairs) / n, 3), diff_mean=round(mean, 3),
                ci95=[round(lo, 3), round(hi, 3)], diff_median=round(med, 3),
                cand_better_pct=round(100.0 * sum(1 for x in diffs if x > 0) / n, 1),
                cand_worse_pct=round(100.0 * sum(1 for x in diffs if x < 0) / n, 1),
                target_rows=len(tgt),
                target_then_stop_pct=(round(100.0 * sum(1 for p in tgt if p[3] == 'STOP') / len(tgt), 1) if tgt else None),
                base_p05=round(_q([p[0] for p in pairs], 0.05), 2), cand_p05=round(_q([p[1] for p in pairs], 0.05), 2))
            r1_ok.append(lo > 0)
            r2_ok.append(med >= 0)
            signs.append(mean > 0)
        res['R1'] = dict(ok=all(r1_ok), per_split=dict(zip(SPLITS, r1_ok)))
        res['R2'] = dict(ok=all(r2_ok), per_split=dict(zip(SPLITS, r2_ok)))
        if all(r1_ok) and all(r2_ok):
            res['verdict'] = '(가) 후보 확정 — 독립 확인은 전방 기록부로'
        elif r1_ok[0] and r1_ok[1] and not r1_ok[2] and signs[2] and all(r2_ok):
            res['verdict'] = '(나) 후보 유지 · 현행 유지 — 블라인드만 CI 가 0 포함'
        else:
            res['verdict'] = '(다) 기각 · 현행 유지'
    with io.open(OUT, 'w', encoding='utf-8', newline='\n') as f:
        f.write(json.dumps(res, ensure_ascii=False, indent=1) + '\n')
    sys.stdout.write(json.dumps(res, ensure_ascii=True)[:200] + '\n')


if __name__ == '__main__':
    main()
