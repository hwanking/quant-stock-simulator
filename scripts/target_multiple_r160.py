# -*- coding: utf-8 -*-
"""R160 — 목표를 손절보다 멀리 두면 성과가 나아지는가.

사전등록: docs/PREREG_R160_TARGET_MULTIPLE.md (측정 전 커밋).

  R159 가 짚은 구조 문제: 목표/손절 0.70 : 1 → 본전 적중률 63.7% 인데
  실전은 50.4%. 목표를 손절폭의 M 배로 밀면 나아지는가.

  재시뮬레이션은 prediction_log.grade_prediction 과 한 글자도 같다:
  손절 먼저(같은 봉이면 보수적으로 STOP) · 수익은 닿은 레벨, 아니면
  마지막 종가 · 비용 0.41% 차감.
  잣대는 **비용후 기대값**이다 — 적중률이 아니다.

**자기검사(§5)**: 원래 목표·손절로 재시뮬레이션해 원장 outcome 을
95% 이상 재현해야 한다. 못 하면 측정을 중단한다.

원장 mfe/mae 를 쓰지 않는다 — bar_paths 를 다시 밟는다(R85).
측정 전용 — 점수·게이트·문턱·실행 레벨을 바꾸지 않는다.

    C:/Python314/python.exe scripts/target_multiple_r160.py
"""
import collections
import glob
import io
import json
import math
import os
import sys
from datetime import date, datetime, timezone

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
OUT = os.path.join(PROJ, 'data', 'target_multiple_r160.json')
P = os.path.join(PROJ, '.portfolio')
LEDGER = os.path.join(P, 'virtual_graded.jsonl')

BUY = 58.0                     # R49 채택값
COST = 0.41                    # TOTAL_COST_PCT 채택값
MULTS = (1.0, 1.5, 2.0, 3.0)   # 사전등록 §3
Z_CRIT = 2.50                  # §4 — Bonferroni 4, 올림
MIN_CASES = 1000               # §4 채택값
MIN_DAYS = 300                 # §4 채택값
DEV = ('train', 'valid')
REPRO_MIN = 95.0               # §5 — 재현율 하한(%)
#: 경로 열 순서 — R85 가 문서화한 값 (docs/MFE_WINDOW_R85.md)
C_DATE, C_HI, C_LO, C_CL, C_VOL, C_OP = 0, 1, 2, 3, 4, 5


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def sign_test(vals):
    nz = [v for v in vals if v != 0]
    n = len(nz)
    if n == 0:
        return None, 0, 0
    win = sum(1 for v in nz if v > 0)
    return round((win - n / 2) / math.sqrt(n / 4), 2), win, n


def need_p(n):
    return round((0.5 + Z_CRIT / (2 * math.sqrt(n))) * 100, 1) if n else None


def grade(path, horizon, entry, tp, sl):
    """prediction_log.grade_prediction 과 같은 규칙.

    path 는 [날짜, 고%, 저%, 종%, 거래량배율, 시%] 목록(진입가 대비 %).
    반환: (outcome, 수익률%) — 비용 차감 전.
    """
    bars = path[:horizon]
    if not bars:
        return None, None
    tp_pct = (tp / entry - 1.0) * 100.0 if tp else None
    sl_pct = (sl / entry - 1.0) * 100.0 if sl else None
    for b in bars:
        hi, lo = b[C_HI], b[C_LO]
        if sl_pct is not None and lo <= sl_pct:
            return 'STOP', sl_pct
        if tp_pct is not None and hi >= tp_pct:
            return 'TARGET', tp_pct
    return 'OPEN', bars[-1][C_CL]


def main():
    print('R160 — 목표를 손절보다 멀리 두면 성과가 나아지는가')
    print('사전등록: docs/PREREG_R160_TARGET_MULTIPLE.md')
    print('측정 전용 — 점수·게이트·문턱·실행 레벨을 바꾸지 않는다')
    print()

    paths = {}
    for fp in sorted(glob.glob(os.path.join(P, 'bar_paths_s*.jsonl'))):
        with open(fp, encoding='utf-8', errors='replace') as f:
            for ln in f:
                try:
                    q = json.loads(ln)
                except Exception:                              # noqa: BLE001
                    continue
                if q.get('bars'):
                    paths[(str(q['ticker']), str(q['date'])[:10])] = q['bars']
    print(f'■ 경로 {len(paths):,}건')

    cases, n_buy, n_nopath, n_norisk = [], 0, 0, 0
    with open(LEDGER, encoding='utf-8', errors='replace') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:                                  # noqa: BLE001
                continue
            if r.get('score') is None or float(r['score']) < BUY:
                continue
            n_buy += 1
            key = (str(r.get('ticker')), str(r.get('date'))[:10])
            pth = paths.get(key)
            if not pth:
                n_nopath += 1
                continue
            try:
                entry = float(r['price'])
                sl = float(r['stop'])
                tp = float(r['target'])
            except Exception:                                  # noqa: BLE001
                continue
            if not entry or sl >= entry:
                n_norisk += 1
                continue
            cases.append(dict(
                d=str(r.get('date'))[:10], split=str(r.get('split') or ''),
                entry=entry, tp=tp, sl=sl, path=pth,
                horizon=int(r.get('horizon_days') or 20),
                outcome=r.get('outcome')))
    print(f'■ 매수권 {n_buy:,} · 경로 있음 {len(cases) + n_norisk:,} · '
          f'경로 없음 {n_nopath:,} · 위험≤0 제외 {n_norisk:,}')
    print(f'   → 분석 대상 {len(cases):,}건')

    # ── 자기검사 (사전등록 §5) — 원래 레벨로 원장 outcome 재현 ─────────
    ok = tot = 0
    mism = collections.Counter()
    for c in cases:
        if not c['outcome']:
            continue
        o, _ = grade(c['path'], c['horizon'], c['entry'], c['tp'], c['sl'])
        tot += 1
        if o == c['outcome']:
            ok += 1
        else:
            mism[f"{c['outcome']}→{o}"] += 1
    rate = round(ok / tot * 100, 2) if tot else 0.0
    print()
    print(f'■ 자기검사 — 원래 레벨로 원장 outcome 을 재현하는가 (§5)')
    print(f'   {ok:,}/{tot:,} = {rate}%  (문턱 {REPRO_MIN}%)')
    if mism:
        print('   어긋난 꼴: ' + ' · '.join(
            f'{k} {v:,}' for k, v in mism.most_common(4)))
    if rate < REPRO_MIN:
        print()
        print('■ 재현 실패 — 측정을 중단한다 (사전등록 §5). '
              '문턱을 내리지 않는다.')
        return 2

    # ── 기준선(현행 목표)과 M 별 결과 ──────────────────────────────────
    def run(m, splits):
        """m=None 이면 현행 목표. 날짜별 비용후 평균 수익을 낸다."""
        by_day = collections.defaultdict(list)
        hits = n = 0
        for c in cases:
            if c['split'] not in splits:
                continue
            if m is None:
                tp = c['tp']
            else:
                risk = (c['entry'] - c['sl']) / c['entry']
                tp = c['entry'] * (1.0 + m * risk)
            o, ret = grade(c['path'], c['horizon'], c['entry'], tp, c['sl'])
            if ret is None:
                continue
            n += 1
            if o == 'TARGET':
                hits += 1
            by_day[c['d']].append(ret - COST)
        return by_day, n, (round(hits / n * 100, 1) if n else None)

    base_dev, base_n, base_hit = run(None, DEV)
    print()
    print(f'■ 현행(그대로) — 개발 구간 케이스 {base_n:,} · '
          f'목표 도달률 {base_hit}%')
    ev0 = [sum(v) / len(v) for v in base_dev.values()]
    ev0s = sorted(ev0)
    base_mean = sum(ev0) / len(ev0)
    base_med = ev0s[len(ev0) // 2]
    base_p10 = ev0s[int(0.10 * (len(ev0s) - 1))]
    print(f'   날짜 {len(ev0):,} · 비용후 EV  평균 {base_mean:+.3f}% · '
          f'중앙 {base_med:+.3f}% · 하위10% {base_p10:+.3f}%')

    results = {}
    print()
    print(f'{"M":>5}{"도달률":>8}{"EV평균":>9}{"EV중앙":>9}{"하위10%":>9}'
          f'{"ΔEV평균":>9}{"ΔEV중앙":>9}{"승률":>7}{"z":>7}  판정')
    for m in MULTS:
        bd, n, hit = run(m, DEV)
        days = sorted(set(bd) & set(base_dev))
        d = [sum(bd[x]) / len(bd[x]) - sum(base_dev[x]) / len(base_dev[x])
             for x in days]
        z, win, nn = sign_test(d)
        ev = [sum(bd[x]) / len(bd[x]) for x in days]
        evs = sorted(ev)
        sample_ok = n >= MIN_CASES and len(days) >= MIN_DAYS
        z_ok = z is not None and abs(z) >= Z_CRIT
        if not sample_ok:
            verdict = '표본 미달'
        elif z_ok:
            verdict = '낫다(+)' if z > 0 else '더 나쁘다(−)'
        else:
            verdict = '미달 — 차이 못 봄'
        # 기전 진단(판정 아님) — 이득이 어느 날에서 나오나.
        #   손절 먼저 규칙 때문에 '나쁜 날'(손절로 끝나는 날)은 목표를
        #   밀어도 그대로다. 이득이 '이미 좋았던 날'에서만 나오는지 본다.
        med_base = sorted(sum(base_dev[x]) / len(base_dev[x])
                          for x in days)[len(days) // 2]
        lo_d = [d[i] for i, x in enumerate(days)
                if sum(base_dev[x]) / len(base_dev[x]) < med_base]
        hi_d = [d[i] for i, x in enumerate(days)
                if sum(base_dev[x]) / len(base_dev[x]) >= med_base]
        where = dict(
            bad_days_median=(round(sorted(lo_d)[len(lo_d) // 2], 3)
                             if lo_d else None),
            bad_days_mean=(round(sum(lo_d) / len(lo_d), 3) if lo_d else None),
            good_days_median=(round(sorted(hi_d)[len(hi_d) // 2], 3)
                              if hi_d else None),
            good_days_mean=(round(sum(hi_d) / len(hi_d), 3) if hi_d else None))
        results[str(m)] = dict(
            gain_where=where,
            mult=m, cases=n, days=len(days), hit_pct=hit,
            ev_mean=round(sum(ev) / len(ev), 3) if ev else None,
            ev_median=round(evs[len(evs) // 2], 3) if ev else None,
            ev_p10=round(evs[int(0.10 * (len(evs) - 1))], 3) if ev else None,
            ev_p90=round(evs[int(0.90 * (len(evs) - 1))], 3) if ev else None,
            d_mean=round(sum(d) / len(d), 3) if d else None,
            d_median=round(sorted(d)[len(d) // 2], 3) if d else None,
            win_pct=round(win / nn * 100, 1) if nn else None,
            need_pct=need_p(nn), sign_z=z, sample_ok=sample_ok,
            z_ok=z_ok, verdict=verdict, blind=None)
        r = results[str(m)]
        print(f'{m:>5.1f}{(hit or 0):>7.1f}%{(r["ev_mean"] or 0):>9.3f}'
              f'{(r["ev_median"] or 0):>9.3f}{(r["ev_p10"] or 0):>9.3f}'
              f'{(r["d_mean"] or 0):>9.3f}{(r["d_median"] or 0):>9.3f}'
              f'{(r["win_pct"] or 0):>6.1f}%'
              f'{(z if z is not None else 0):>7.2f}  {verdict}')
        print(f'{"":>5}  이득이 나는 곳: 현행이 나쁜 날 ΔEV 중앙 '
              f'{where["bad_days_median"]} · 좋은 날 '
              f'{where["good_days_median"]}')

    passed = [k for k, r in results.items() if r['sample_ok'] and r['z_ok']]
    print()
    if passed:
        print('■ blind 확인 (통과한 M 만 — 사전등록 §4)')
        bb, bn, bh = run(None, ('blind',))
        for k in passed:
            m = results[k]['mult']
            mb, mn, mh = run(m, ('blind',))
            days = sorted(set(mb) & set(bb))
            d = [sum(mb[x]) / len(mb[x]) - sum(bb[x]) / len(bb[x])
                 for x in days]
            z, win, nn = sign_test(d)
            results[k]['blind'] = dict(
                cases=mn, days=len(days), hit_pct=mh,
                d_mean=round(sum(d) / len(d), 3) if d else None,
                sign_z=z)
            print(f'   M={m}: 케이스 {mn:,} · 날짜 {len(days)} · '
                  f'도달률 {mh}% · ΔEV {results[k]["blind"]["d_mean"]}% · '
                  f'z {z}')
    else:
        print('■ 문턱을 넘은 M 이 없다 — blind 를 열지 않는다')

    doc = {
        'made': date.today().isoformat(),
        'made_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'prereg': 'docs/PREREG_R160_TARGET_MULTIPLE.md',
        'criteria': dict(z_crit=Z_CRIT, mults=list(MULTS), buy=BUY,
                         cost_pct=COST, min_cases=MIN_CASES,
                         min_days=MIN_DAYS, repro_min=REPRO_MIN,
                         n_tests=len(MULTS), dev=list(DEV)),
        'coverage': dict(buy_zone=n_buy, no_path=n_nopath,
                         no_risk=n_norisk, analyzed=len(cases)),
        'self_check': dict(matched=ok, total=tot, rate_pct=rate,
                           threshold=REPRO_MIN, passed=True,
                           mismatch=dict(mism.most_common())),
        'baseline': dict(cases=base_n, hit_pct=base_hit,
                         ev_mean=round(base_mean, 3),
                         ev_median=round(base_med, 3),
                         ev_p10=round(base_p10, 3)),
        'tests': results, 'passed': passed,
        'note': ('측정 전용 — 점수·게이트·문턱·실행 레벨을 바꾸지 않는다. '
                 '원장 mfe/mae 미사용(청산 봉 함정) — bar_paths 를 다시 '
                 '밟았다(R85). 채점 규칙은 prediction_log 와 동일. '
                 '잣대는 비용후 기대값이지 적중률이 아니다. 통과해도 '
                 '이 라운드에서 목표 산식을 바꾸지 않는다 — 실행 레벨 '
                 '변경은 2026-11-16 이후 별도 사전등록이다.'),
    }
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print()
    print(f'저장: {OUT}')
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
