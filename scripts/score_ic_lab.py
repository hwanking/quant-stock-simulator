# -*- coding: utf-8 -*-
"""라운드 84 — 점수·지표에 **횡단면 정보**가 있는가 (측정 전용).

사전등록: docs/PREREG_R84_SCORE_IC.md (측정 전에 커밋됨)

■ 무엇을 재나
  같은 날 안에서 지표 순위와 20봉 결과 순위가 얼마나 맞는가
  (스피어만 IC). 날짜 하나가 관측 하나다 — 같은 날 비교라 시장 요인이
  상쇄되므로 라운드 80 의 설계효과를 여기 쓰지 않는다.

■ 무엇을 바꾸지 않나
  점수·게이트·가중치. 이 스크립트는 읽기만 한다.

    C:/Python314/python.exe scripts/score_ic_lab.py
"""
import io
import json
import math
import os
import sys
from collections import defaultdict

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(PROJ, '.portfolio', 'virtual_graded.jsonl')
OUT = os.path.join(PROJ, 'data', 'score_ic_r84.json')

#: 사전등록 §4 — 측정 전에 고정. 여기서 내리지 않는다.
T_FLOOR = 2.0          # IC 연구 표준 관례
MIN_DATES = 30         # 구간별 날짜 하한. 미달이면 '미측정'
PER_DATE = (5, 10, 20)  # 날짜당 최소 종목 — 셋 다 실어 견고성을 보인다

#: 사전등록 §3 — 지표와 기대 방향. '미정' 은 양측으로만 판정한다.
FEATURES = [
    ('score', +1), ('rsi', 0), ('bb_pos', 0), ('range_pos', 0),
    ('vol20', 0), ('demark_bull', +1), ('demark_bear', -1),
    ('win_rate', +1), ('net_expected', +1), ('eff_sample', 0),
]
OUTCOMES = ('close_return_pct', 'success')


def _today():
    """오늘 날짜 — 라운드 107. 박아 두면 다시 만들어도
    안 바뀌어 낡음을 알 수 없다 (라운드 102 miss_study).
    """
    import datetime as _dt
    return _dt.date.today().isoformat()


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def load():
    rows = []
    with open(LEDGER, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:                                  # noqa: BLE001
                pass
    return rows


def _ranks(vals):
    """평균 순위 (동률은 평균) — 스피어만용."""
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    rk = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            rk[order[k]] = avg
        i = j + 1
    return rk


def spearman(xs, ys):
    """스피어만 상관. 한쪽이 상수면 정의되지 않으므로 None."""
    n = len(xs)
    if n < 3:
        return None
    if len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    dy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def ic_series(rows, feat, outcome, per_date):
    """날짜별 IC 목록. 날짜가 표본이다."""
    by_date = defaultdict(list)
    for r in rows:
        x, y = r.get(feat), r.get(outcome)
        if x is None or y is None:
            continue
        try:
            by_date[str(r.get('date'))[:10]].append((float(x), float(y)))
        except (TypeError, ValueError):
            continue
    out = []
    for d, pairs in by_date.items():
        if len(pairs) < per_date:
            continue
        ic = spearman([p[0] for p in pairs], [p[1] for p in pairs])
        if ic is not None:
            out.append(ic)
    return out


def summarize(ics):
    n = len(ics)
    if n < 2:
        return dict(dates=n, mean=None, t=None,
                    why='날짜가 2개 미만 — t 정의 불가')
    m = sum(ics) / n
    var = sum((x - m) ** 2 for x in ics) / (n - 1)
    se = math.sqrt(var / n) if var > 0 else 0.0
    t = (m / se) if se > 0 else None
    return dict(dates=n, mean=round(m, 5),
                t=(round(t, 2) if t is not None else None),
                pos_rate=round(sum(1 for x in ics if x > 0) / n * 100, 1))


def split_of(r):
    return str(r.get('split') or '?')


def main():
    rows = load()
    print(f'원장 {len(rows):,}건')
    splits = {'train': [], 'valid': [], 'blind': []}
    for r in rows:
        s = split_of(r)
        if s in splits:
            splits[s].append(r)
    for s, v in splits.items():
        print(f'  {s:<6} {len(v):>8,}건')

    result = {}
    for outcome in OUTCOMES:
        print(f'\n{"=" * 68}\n결과 지표: {outcome}\n{"=" * 68}')
        result[outcome] = {}
        for feat, want in FEATURES:
            result[outcome][feat] = {'expected_sign': want, 'by_split': {}}
            line = f'  {feat:<14} 기대 {("+" if want > 0 else "−" if want < 0 else "미정"):<3}'
            for s in ('train', 'valid', 'blind'):
                cell = {}
                for pd_ in PER_DATE:
                    cell[f'min{pd_}'] = summarize(
                        ic_series(splits[s], feat, outcome, pd_))
                result[outcome][feat]['by_split'][s] = cell
                m10 = cell['min10']
                line += (f' | {s[:2]} IC '
                         f'{("%+.4f" % m10["mean"]) if m10["mean"] is not None else "  —   "}'
                         f' t{("%+.1f" % m10["t"]) if m10.get("t") is not None else " — "}'
                         f' d{m10["dates"]:>3}')
            print(line)

    # ── 사전등록 §4 판정 — 기준을 여기서 내리지 않는다 ────────────────
    print(f'\n{"=" * 68}\n판정 (사전등록 §4 · min10 기준)\n{"=" * 68}')
    verdicts = {}
    for outcome in OUTCOMES:
        verdicts[outcome] = {}
        for feat, want in FEATURES:
            cells = result[outcome][feat]['by_split']
            ms = {s: cells[s]['min10'] for s in ('train', 'valid', 'blind')}
            enough = all((ms[s]['dates'] or 0) >= MIN_DATES for s in ms)
            if not enough:
                v, why = '미측정', '날짜 수 하한 미달'
            else:
                ts = [ms[s]['t'] for s in ms]
                mm = [ms[s]['mean'] for s in ms]
                t_ok = all(t is not None and abs(t) >= T_FLOOR for t in ts)
                sign_ok = (all(x > 0 for x in mm) or all(x < 0 for x in mm))
                dir_ok = True
                if want != 0 and sign_ok:
                    dir_ok = (mm[0] > 0) == (want > 0)
                if t_ok and sign_ok and dir_ok:
                    v, why = '정보 있음', ''
                else:
                    v = '정보 없음'
                    why = ('|t| 미달' if not t_ok else
                           '구간 부호 불일치' if not sign_ok else
                           '기대 방향과 반대')
            verdicts[outcome][feat] = dict(verdict=v, why=why)
            print(f'  {feat:<14} {outcome:<18} → {v}'
                  + (f'  ({why})' if why else ''))

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(dict(
            # ⚠️ 라운드 107 — 여기 날짜는 **사전등록 연구를 판정한 날**이다.
            #   다시 돌려도 안 바뀌는 게 맞다 (같은 줄의 prereg= 가 표식).
            made='2026-08-13', prereg='docs/PREREG_R84_SCORE_IC.md',
            t_floor=T_FLOOR, min_dates=MIN_DATES, per_date=list(PER_DATE),
            features=[f for f, _ in FEATURES], outcomes=list(OUTCOMES),
            result=result, verdicts=verdicts,
            note='측정 전용 — 점수·게이트·가중치를 바꾸지 않는다. 날짜가 '
                 '표본이다(같은 날 비교라 시장 요인 상쇄 · 라운드 80 §5). '
                 '판정 기준은 사전등록에서 왔고 여기서 내리지 않았다.'),
            f, ensure_ascii=False, indent=1)
    print(f'\n저장: {OUT}')
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
