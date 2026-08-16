# -*- coding: utf-8 -*-
"""라운드 112 — 상대화가 순위 정보를 만들어 내는가 (관측 전용).

사전등록: docs/PREREG_R112_RELATIVIZATION.md — **먼저 저장·커밋됐다**
(97da027). 기준을 측정 후에 고치지 않는다.

■ 시험하지 않는 것 (사전등록 §1)
  같은 날 안에서 순위로 바꾸거나 평균을 빼는 것은 **그날 정렬 순서를
  바꾸지 않는다.** 라운드 111 이 이미 같은 날 순위로 비교했으므로
  수학적으로 같은 시험이다. 순서를 실제로 바꾸는 둘만 잰다:
      (A) 업종 내 백분위      — 집단이 다르다
      (B) 자기 이력 대비 z    — 기준이 그 종목의 과거다 (과거만 쓴다)

    C:/Python314/python.exe scripts/relativization_r112.py
"""
import collections
import glob
import io
import json
import math
import os
import statistics
import sys
from datetime import date, datetime, timezone
from statistics import NormalDist

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(PROJ, '.portfolio')
OUT = os.path.join(PROJ, 'data', 'relativization_r112.json')

COST = 0.36
BUY = 58.0
#: 사전등록 §3 에 **적힌 대로의** 값. 기록은 고치지 않는다
Z_CRIT = 2.95
N_TESTS = 16
#: 규칙(0.05/16)을 그대로 풀면 2.9552 다 — 사전등록의 2.95 는 반올림이라
#: 참 임계값보다 0.0052 낮다. 기록은 그대로 두고 **판정은 더 엄한 쪽**으로
#: 한다. 문턱을 내린 채로 통과시키지 않기 위해서다 (§2).
Z_CRIT_EXACT = NormalDist().inv_cdf(1 - (0.05 / N_TESTS) / 2)
Z_APPLIED = max(Z_CRIT, Z_CRIT_EXACT)
#: 사전등록 §4 — B3 은 라운드 49 의 R5 재사용
MIN_CASES, MIN_DATES = 300, 100
#: B4 — 그날 순위에서 뺀 종목이 이 비율을 넘으면 미달
MAX_DROP = 0.50
#: (A) 업종 백분위를 낼 최소 종목 수 (그 아래는 백분위가 뜻이 없다)
MIN_SECTOR = 3
#: (B) 자기 이력 창 — 판정 지평 20 재사용. 10·40 은 민감도로 함께 찍는다
WINDOWS = (10, 20, 40)
PRIMARY_WINDOW = 20
MIN_HISTORY = 10

FIELDS = (('score', '종합점수'),
          ('q_stock_quality', 'stock_quality'),
          ('q_trading_timing', 'trading_timing'),
          ('q_risk_safety', 'risk_safety'),
          ('q_opportunity', 'opportunity'),
          ('q_execution', 'execution'),
          ('q_confidence', 'confidence'),
          ('q_strategy_quality', 'strategy_quality'))


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def load():
    """개발 구간·판정완료 + 하위점수·섹터 패치 합류 (라운드 99 교훈)."""
    patch = {}
    for p in sorted(glob.glob(os.path.join(P, 'subscore_patch*.jsonl'))):
        with open(p, encoding='utf-8', errors='replace') as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    q = json.loads(ln)
                except Exception:                              # noqa: BLE001
                    continue
                patch[(str(q.get('ticker')), str(q.get('date'))[:10])] = q

    rows = []
    with open(os.path.join(P, 'virtual_graded.jsonl'),
              encoding='utf-8', errors='replace') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:                                  # noqa: BLE001
                continue
            if r.get('split') not in ('train', 'valid'):
                continue                       # 봉인 준수
            if r.get('outcome') not in ('TARGET', 'STOP'):
                continue
            if r.get('return_pct') is None or r.get('score') is None:
                continue
            q = patch.get((str(r.get('ticker')), str(r.get('date'))[:10]))
            if q:
                for k, _ in FIELDS:
                    if r.get(k) is None and q.get(k) is not None:
                        r[k] = q[k]
                if not r.get('sector') and q.get('sector'):
                    r['sector'] = q['sector']
            rows.append(r)
    return rows


def hit_ev(sub):
    n = len(sub)
    if not n:
        return None, None
    k = sum(1 for r in sub if r.get('outcome') == 'TARGET')
    return k / n * 100.0, sum(float(r['return_pct']) for r in sub) / n - COST


def rel_sector(rows, field):
    """(A) 그날·그 업종 안 백분위. 조건 못 갖춘 종목은 **빼고 센다**."""
    by_day = collections.defaultdict(list)
    for r in rows:
        by_day[str(r.get('date'))[:10]].append(r)
    out, kept, dropped = collections.defaultdict(list), 0, 0
    for d, day in by_day.items():
        by_sec = collections.defaultdict(list)
        for r in day:
            if r.get(field) is None:
                dropped += 1
                continue
            s = r.get('sector')
            if not s:
                dropped += 1               # ETF·리츠 — 업종이 원래 없다
                continue
            by_sec[s].append(r)
        for s, grp in by_sec.items():
            if len(grp) < MIN_SECTOR:
                dropped += len(grp)
                continue
            vals = sorted(float(x[field]) for x in grp)
            n = len(vals)
            for r in grp:
                v = float(r[field])
                # 백분위 — 같은 값이 여럿이면 중간 순위를 준다
                lo = sum(1 for x in vals if x < v)
                eq = sum(1 for x in vals if x == v)
                r['_rel'] = (lo + (eq - 1) / 2) / max(1, n - 1) if n > 1 else 0.5
                out[d].append(r)
                kept += 1
    return out, kept, dropped


def rel_self(rows, field, window):
    """(B) 자기 이력 대비 z. **과거만** 쓴다 (오늘·이후 관측 금지)."""
    by_tk = collections.defaultdict(list)
    out, kept, dropped = collections.defaultdict(list), 0, 0
    for r in rows:
        if r.get(field) is None:
            dropped += 1          # (A) 와 같은 기준으로 센다 — B4 가 흔들리면 안 된다
        else:
            by_tk[str(r.get('ticker'))].append(r)
    for tk, seq in by_tk.items():
        seq.sort(key=lambda r: str(r.get('date'))[:10])
        hist = []
        for r in seq:
            if len(hist) >= MIN_HISTORY:
                w = hist[-window:]
                mu = statistics.fmean(w)
                sd = statistics.pstdev(w)
                if sd > 0:
                    r['_rel'] = (float(r[field]) - mu) / sd
                    out[str(r.get('date'))[:10]].append(r)
                    kept += 1
                else:
                    dropped += 1          # 분모 0 — 값을 만들지 않는다
            else:
                dropped += 1              # 과거가 모자라다
            hist.append(float(r[field]))
    return out, kept, dropped


def raw_control(by_day, field):
    """대조 — **같은 날·같은 종목**을 원값으로 순위 매긴다 (판정 기준 아님).

    업종내 방식은 조건 못 갖춘 종목을 빼면서 날짜 집합까지 바뀐다
    (810일 → 286일). 그러면 z 가 달라져도 **상대화 덕인지 날짜가 바뀐
    탓인지** 구분이 안 된다. 표본을 그대로 두고 순위 값만 원값으로
    되돌려 그 차이를 분리한다.
    """
    swapped = collections.defaultdict(list)
    for d, day in by_day.items():
        for r in day:
            r2 = dict(r)
            r2['_rel'] = float(r[field])
            swapped[d].append(r2)
    return paired(swapped)


def paired(by_day):
    """상위5 vs 6위 이하 매수권 — 날짜별 짝비교 (라운드 49 잣대)."""
    win = lose = tie = 0
    d_hit, n_top = [], 0
    for d, day in by_day.items():
        if len(day) < 6:
            continue
        o = sorted(day, key=lambda r: (-float(r['_rel']),
                                       str(r.get('ticker'))))
        t5 = o[:5]
        rb = [r for r in o[5:] if float(r.get('score') or 0) >= BUY]
        if not rb:
            continue
        ha, _ = hit_ev(t5)
        hb, _ = hit_ev(rb)
        if ha is None or hb is None:
            continue
        n_top += len(t5)
        d_hit.append(ha - hb)
        if ha > hb:
            win += 1
        elif ha < hb:
            lose += 1
        else:
            tie += 1
    n = win + lose
    z = ((win - n / 2) / math.sqrt(n / 4)) if n else None
    med = (sorted(d_hit)[len(d_hit) // 2] if d_hit else None)
    return dict(days=len(d_hit), win=win, lose=lose, tie=tie, n_top=n_top,
                sign_z=(round(z, 2) if z is not None else None),
                median_hit_diff=(round(med, 2) if med is not None else None))


def judge(p, kept, dropped):
    drop_rate = dropped / max(1, kept + dropped)
    return {
        'B1 z ≥ 문턱': (p['sign_z'] is not None and p['sign_z'] >= Z_APPLIED),
        'B2 중앙값 > 0': (p['median_hit_diff'] is not None
                       and p['median_hit_diff'] > 0),
        'B3 표본 300건·100일': (p['n_top'] >= MIN_CASES
                            and p['days'] >= MIN_DATES),
        'B4 뺀 표본 < 50%': drop_rate < MAX_DROP,
    }, round(drop_rate * 100, 1)


def main():
    print('라운드 112 — 상대화가 순위 정보를 만들어 내는가')
    print('사전등록: docs/PREREG_R112_RELATIVIZATION.md (측정 전 커밋)')
    print('※ 같은 날 순위·평균빼기는 그날 순서를 안 바꾸므로 시험하지 '
          '않는다 (사전등록 §1)\n')
    rows = load()
    print(f'개발 구간·판정완료 {len(rows):,}건 · '
          f'업종 있음 {sum(1 for r in rows if r.get("sector")):,}건\n')

    res, verd, ctrl = {}, {}, {}
    print(f'{"방식":<8}{"기준":<18}{"날짜":>7}{"이김":>7}{"짐":>7}{"z":>8}'
          f'{"적중차중앙":>11}{"뺀비율":>8}{"원값대조z":>10}')
    for scheme, fn in (('업종내', rel_sector), ('자기이력', rel_self)):
        for f, label in FIELDS:
            if scheme == '업종내':
                by_day, kept, dropped = fn(rows, f)
            else:
                by_day, kept, dropped = fn(rows, f, PRIMARY_WINDOW)
            p = paired(by_day)
            c = raw_control(by_day, f)          # 같은 표본·원값 순위
            v, dr = judge(p, kept, dropped)
            key = f'{scheme}:{f}'
            res[key] = dict(p, kept=kept, dropped=dropped, drop_pct=dr)
            ctrl[key] = c
            verd[key] = v
            print(f'{scheme:<8}{label:<18}{p["days"]:>7,}{p["win"]:>7,}'
                  f'{p["lose"]:>7,}'
                  f'{(f"{p["sign_z"]:+.2f}" if p["sign_z"] is not None else "—"):>8}'
                  f'{(f"{p["median_hit_diff"]:+.2f}%p" if p["median_hit_diff"] is not None else "—"):>11}'
                  f'{dr:>7.1f}%'
                  f'{(f"{c["sign_z"]:+.2f}" if c["sign_z"] is not None else "—"):>10}')

    passed = [k for k, v in verd.items() if all(v.values())]
    print(f'\n■ 채택 조건 (측정 전 고정 · Bonferroni |z| ≥ {Z_CRIT})')
    print(f'   ※ 규칙(0.05/{N_TESTS})의 참 임계는 {Z_CRIT_EXACT:.4f} — '
          f'사전등록의 {Z_CRIT} 는 반올림이라 그만큼 낮다.')
    print(f'   기록은 그대로 두고 **판정은 {Z_APPLIED:.4f}** 로 한다 '
          f'(더 엄한 쪽). 최고 z 가 그 사이에 없어 결과는 같다.')
    for k, v in verd.items():
        if not all(v.values()):
            continue
        print(f'   [통과] {k}')
    print(f'>> 통과한 방식: {passed if passed else "없음"}')

    # 상대화가 한 일과 표본이 한 일을 가른다 (서술 — 판정 기준 아님)
    print('\n■ 상대화의 순수 기여 = 상대화 z − 같은 표본 원값 z')
    contrib = collections.defaultdict(list)
    for k in res:
        a, b = res[k]['sign_z'], ctrl[k]['sign_z']
        if a is None or b is None:
            continue
        contrib[k.split(':')[0]].append(a - b)
        print(f'   {k:<28} 상대화 {a:+.2f} · 원값 {b:+.2f} · '
              f'차이 {a - b:+.2f}')
    summary = {}
    for scheme, ds in contrib.items():
        pos = sum(1 for d in ds if d > 0)
        summary[scheme] = dict(n=len(ds), helped=pos, hurt=len(ds) - pos,
                               mean=round(statistics.fmean(ds), 2),
                               median=round(statistics.median(ds), 2))
        print(f'   >> {scheme}: 도움 {pos}/{len(ds)} · '
              f'평균 {summary[scheme]["mean"]:+.2f} · '
              f'중앙 {summary[scheme]["median"]:+.2f}')

    # 같은 표본에서 **원값만으로** 얼마나 흔들리는가 (잡음 폭)
    raw_z = [ctrl[k]['sign_z'] for k in ctrl
             if k.startswith('업종내') and ctrl[k]['sign_z'] is not None]
    print(f'\n■ 업종 표본으로 줄이기만 했을 때 원값 z 범위: '
          f'{min(raw_z):+.2f} ~ {max(raw_z):+.2f} '
          f'(상대화 없이 · 8개 기준)')

    # 라운드 111 과 날짜 수 대조 — B4 는 종목만 세고 날짜는 안 센다
    r111p = os.path.join(PROJ, 'data', 'score_anatomy_r111.json')
    days_cmp = {}
    if os.path.exists(r111p):
        with open(r111p, encoding='utf-8') as f:
            prev = json.load(f).get('paired', {})
        print('\n■ 짝비교 날짜 수 — 라운드 111 대비 (B4 가 못 보는 축)')
        for f_, label in FIELDS:
            a = prev.get(f_, {}).get('days')
            s = res.get(f'업종내:{f_}', {}).get('days')
            h = res.get(f'자기이력:{f_}', {}).get('days')
            if a:
                days_cmp[f_] = dict(r111=a, sector=s, self=h,
                                    sector_pct=round(s / a * 100, 1),
                                    self_pct=round(h / a * 100, 1))
                print(f'   {label:<18} R111 {a:>5,} → 업종내 {s:>5,} '
                      f'({s / a * 100:>5.1f}%) · 자기이력 {h:>5,} '
                      f'({h / a * 100:>5.1f}%)')

    # 창 길이 민감도 — 결과가 그 선택에 흔들리는지 (사전등록 §2)
    print(f'\n■ 자기이력 창 민감도 (판정은 {PRIMARY_WINDOW})')
    sens = {}
    for w in WINDOWS:
        by_day, kept, dropped = rel_self(rows, 'score', w)
        p = paired(by_day)
        sens[w] = p
        print(f'   창 {w:>2}: 날짜 {p["days"]:>5,} · z {p["sign_z"]} · '
              f'중앙 {p["median_hit_diff"]}%p')

    doc = {
        'made': date.today().isoformat(),
        'made_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'prereg': 'docs/PREREG_R112_RELATIVIZATION.md',
        'basis': '개발 구간(train+valid) · 판정완료 · 블라인드 미사용',
        'not_tested': ('같은 날 순위·평균빼기 — 그날 정렬 순서를 바꾸지 '
                       '않으므로 라운드 111 과 동일한 시험이 된다'),
        'z_crit': Z_CRIT, 'n_tests': N_TESTS,
        'z_crit_exact': round(Z_CRIT_EXACT, 4),
        'z_applied': round(Z_APPLIED, 4),
        'z_note': ('사전등록에 적은 2.95 는 0.05/16 의 참 임계 2.9552 를 '
                   '반올림한 값이라 0.0052 만큼 낮다. 기록은 고치지 않고 '
                   '판정만 더 엄한 쪽으로 했다. 최고 z 가 둘 사이에 없어 '
                   '결과는 어느 쪽이든 같다.'),
        'min_cases': MIN_CASES, 'min_dates': MIN_DATES,
        'max_drop': MAX_DROP, 'min_sector': MIN_SECTOR,
        'window': PRIMARY_WINDOW, 'min_history': MIN_HISTORY,
        'n_rows': len(rows),
        'paired': res, 'verdict': verd, 'passed': passed,
        'raw_control': ctrl,
        'raw_control_note': ('같은 날·같은 종목을 원값으로 순위 매긴 대조. '
                             '상대화가 한 일과 표본이 바뀐 탓을 가른다. '
                             '판정 기준이 아니라 서술이다.'),
        'contribution': summary,
        'raw_z_range_sector': [min(raw_z), max(raw_z)],
        'days_vs_r111': days_cmp,
        'window_sensitivity': {str(k): v for k, v in sens.items()},
        'note': ('관측 전용 — 점수·게이트·문턱을 바꾸지 않는다. '
                 '통과한 방식이 있어도 2026-11-16 이후 사전등록의 '
                 '후보 목록으로만 쓴다.'),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f'\n저장: {OUT}')
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
