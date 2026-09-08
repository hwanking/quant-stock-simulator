# -*- coding: utf-8 -*-
"""
라운드 249 — 사전등록 R249 의 **상한 · R1 · R2 · R3** 을 잰다.
(R0 은 `scripts/macro_sample_r249.py` 가 이미 통과시켰다 — 블라인드 기준일 52.)

■ 순서는 사전등록이 정한 대로다 (§2-7 · 라운드 170 · 비용 순)
    상한 → R1 → R2 → R3.  앞에서 미달이면 뒤는 재지 않는다.

    상한  매크로 가름이 **기존 국면 칸과 얼마나 겹치나.**
          겹침이 크면 새로 여는 것이 없다 — 그것만으로 접는다.
    R1    높은 날 vs 낮은 날의 비용 차감 기대값 차이 · 세 구간 모두
    R2    날짜 군집 부트스트랩 CI95 가 0 을 제외하는가
    R3    방향이 train·valid·blind 에서 같은가

■ 표본 단위는 **날짜**다 — 케이스가 아니다
  매크로는 시장 수준 변수라 같은 날 모든 종목이 같은 값이다. 라운드 45 가
  그 사고를 냈다(매수권 280건이 실은 고유 기준일 5개). 그래서 **날짜별 평균**을
  먼저 내고, 그 날짜들을 표본으로 견준다. 부트스트랩도 **날짜를** 재추출한다.

■ 새로 고른 숫자가 없다
    비용 0.36        `verdict_core.COST_PCT` — 라운드 191 이 통일한 그 값을 **불러온다**
    매수권 58        R49 계열이 이미 쓰는 값
    구간 경계        `calibration_lab` 의 2025-07-01 / 2026-02-01
    날짜 하한 30     R45 가 적은 '2구간 × 칸당 15날짜'
    가름 = 중앙값    고르는 값이 아니라 자료가 정하는 값
    보정 z 2.78      Bonferroni(9) · 라운드 113 규칙대로 올림
    조인 규칙        `sector_cycle._upto` — 기준일 **전날까지** (누출 차단)

■ 국면은 **시장별로** 센다
  원장 `regime` 은 시장(KOSPI/KOSDAQ)별 값이다. 날짜만으로 세면 어느 행을
  잡느냐에 따라 수가 갈린다 — 라운드 216 이 그 자리에서 첫 집계를 틀렸다.

    C:/Python314/python.exe scripts/macro_ev_r249.py
"""
import io
import json
import math
import os
import random
import re
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

LEDGER = os.path.join(PROJ, '.portfolio', 'virtual_graded.jsonl')
OUT = os.path.join(PROJ, 'data', 'macro_ev_r249.json')

SPLIT_VALID_FROM = "2025-07-01"          # calibration_lab 의 값
SPLIT_BLIND_FROM = "2026-02-01"          # calibration_lab 의 값
BUY_SCORE = 58                           # R49 계열이 쓰는 값
MIN_DATES = 30                           # R45 가 적은 하한
BOOT = 2000                              # 부트스트랩 횟수
SEED = 249                               # 재현용 — 결과를 보고 안 바꾼다
Z_BONF9 = 2.78                           # Bonferroni(9) 양측 · 올림 (R113)


def _ledger_last_date():
    """원장의 **마지막 케이스 기준일**. 이 산출물이 무엇을 재고 만든 것인가.

    오늘 날짜를 박지 않는다. 파일을 다시 만들 때마다 뜻이 바뀌고, 시간대에
    따라 하루가 어긋난다(라운드 222). 이 값은 '무엇을 재고 만든 것인가'다.
    """
    last = ''
    for ln in io.open(LEDGER, encoding='utf-8', errors='replace'):
        i = ln.find('"date"')
        if i < 0:
            continue
        m = re.search(r'"date"\s*:\s*"(\d{4}-\d{2}-\d{2})', ln[i:])
        if m and m.group(1) > last:
            last = m.group(1)
    return last or None


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def split_of(d):
    if d >= SPLIT_BLIND_FROM:
        return 'blind'
    if d >= SPLIT_VALID_FROM:
        return 'valid'
    return 'train'


def load_cases():
    """매수권 케이스를 (구간, 날짜) 로 묶는다. 시장 국면도 같이 센다."""
    by = {'train': {}, 'valid': {}, 'blind': {}}
    regime = {}                       # (구간, 날짜, 시장) -> 국면
    rows = kept = 0
    for ln in io.open(LEDGER, encoding='utf-8', errors='replace'):
        ln = ln.strip()
        if not ln:
            continue
        rows += 1
        try:
            r = json.loads(ln)
        except Exception:                                      # noqa: BLE001
            continue
        try:
            sc = float(r.get('score') or 0)
            ret = float(r.get('return_pct'))
        except (TypeError, ValueError):
            continue
        if sc < BUY_SCORE:
            continue
        d = str(r.get('date') or '')[:10]
        if len(d) != 10:
            continue
        sp = split_of(d)
        by[sp].setdefault(d, []).append(ret)
        mk = str(r.get('market') or '?')
        rg = str(r.get('regime') or '')
        if rg:
            regime[(sp, d, mk)] = rg          # 시장별 (R216)
        kept += 1
    return by, regime, rows, kept


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def boot_ci(hi_vals, lo_vals, rng):
    """날짜를 재추출한다 — 케이스가 아니라 **날짜**가 표본이다."""
    diffs = []
    for _ in range(BOOT):
        a = [hi_vals[rng.randrange(len(hi_vals))] for _ in hi_vals]
        b = [lo_vals[rng.randrange(len(lo_vals))] for _ in lo_vals]
        diffs.append(mean(a) - mean(b))
    diffs.sort()
    lo95 = diffs[int(0.025 * BOOT)]
    hi95 = diffs[int(0.975 * BOOT) - 1]
    sd = (sum((x - mean(diffs)) ** 2 for x in diffs) / (len(diffs) - 1)) ** 0.5
    return lo95, hi95, sd


def main():
    _utf8()
    import sector_cycle as sc
    from verdict_core import COST_PCT          # R191 이 통일한 값 — 불러온다

    rng = random.Random(SEED)
    print("R249 — 매크로 축이 매수권 판정을 개선하나")
    print("=" * 78)
    print(f"비용 {COST_PCT}%p (verdict_core.COST_PCT · 라운드 191) · "
          f"매수권 {BUY_SCORE}점 · 부트 {BOOT}회 · 시드 {SEED}")

    by, regime, rows, kept = load_cases()
    print(f"원장 {rows:,}행 → 매수권 {kept:,}건")
    for k in ('train', 'valid', 'blind'):
        nd = len(by[k])
        nc = sum(len(v) for v in by[k].values())
        print(f"   {k:<6} 날짜 {nd:>6,} · 케이스 {nc:>8,}")

    # ── 상한 — 매크로 가름이 기존 국면 칸과 겹치나 ────────────────────────
    print()
    print("이득의 상한 — 기존 국면 칸과의 겹침 (재기 전에 셈한다 · §2-7)")
    print("-" * 78)
    bl = sorted(by['blind'])
    bear_days = sorted({d for (sp, d, _mk), rg in regime.items()
                        if sp == 'blind' and rg == 'BEAR'})
    print(f"   블라인드 매수권 날짜 {len(bl)} · 그중 BEAR 를 가진 날 "
          f"{len(bear_days)} ({100.0 * len(bear_days) / max(1, len(bl)):.0f}%)")
    print("   국면은 시장별 값이라 '그 날 어느 시장이든 BEAR' 로 센다 (R216)")

    # ── 축별 측정 ────────────────────────────────────────────────────────
    print()
    print("R1·R2 — 높은 날 vs 낮은 날 (구간 안 중앙값으로 가름 · 날짜가 표본)")
    print("-" * 78)
    print(f"   {'축':<14}{'구간':<7}{'날짜(고/저)':>13}{'차이%p':>9}"
          f"{'CI95':>20}{'보정z':>8}")
    print('   ' + '-' * 71)

    axes_out = {}
    for tk, ko, key in sc.MACRO:
        px = sc.series(tk)
        per_split = {}
        for sp in ('train', 'valid', 'blind'):
            days = sorted(by[sp])
            vals, dmean = [], []
            for d in days:
                rowsd = sc._upto(px, d)       # 기준일 **전날까지** — 누출 차단
                if not rowsd:
                    continue
                vals.append(rowsd[-1][1])
                dmean.append(mean(by[sp][d]))
            if len(vals) < MIN_DATES:
                per_split[sp] = {'n_dates': len(vals), 'note': '날짜 하한 미만'}
                print(f"   {ko:<14}{sp:<7}{len(vals):>13}"
                      f"{'—':>9}{'미측정 (날짜 하한 미만)':>20}")
                continue
            med = sorted(vals)[len(vals) // 2]
            hi = [m for v, m in zip(vals, dmean) if v >= med]
            lo = [m for v, m in zip(vals, dmean) if v < med]
            if len(hi) < 2 or len(lo) < 2:
                per_split[sp] = {'n_dates': len(vals), 'note': '한쪽이 비었다'}
                continue
            diff = mean(hi) - mean(lo)
            l95, h95, sd = boot_ci(hi, lo, rng)
            z = (diff / sd) if sd > 0 else 0.0
            per_split[sp] = {
                'n_dates': len(vals), 'n_hi': len(hi), 'n_lo': len(lo),
                'median': round(med, 4),
                'ev_hi_net': round(mean(hi) - COST_PCT, 4),
                'ev_lo_net': round(mean(lo) - COST_PCT, 4),
                'diff': round(diff, 4), 'ci95': [round(l95, 4), round(h95, 4)],
                'z': round(z, 3),
                'ci95_excl0': (l95 > 0 or h95 < 0),
                'bonf9_pass': abs(z) >= Z_BONF9,
            }
            print(f"   {ko:<14}{sp:<7}{len(hi):>6}/{len(lo):<6}"
                  f"{diff:>+9.3f}"
                  f"{('[' + f'{l95:+.2f}, {h95:+.2f}' + ']'):>20}"
                  f"{z:>+8.2f}")
        axes_out[key] = {'ko': ko, 'ticker': tk, 'splits': per_split}

    # ── R3 — 방향이 세 구간에서 같은가 ──────────────────────────────────
    print()
    print("R3 — 방향이 train·valid·blind 에서 같은가 (사전등록 · 이것이 최종 관문)")
    print("-" * 78)
    passed = []
    for key, a in axes_out.items():
        sp = a['splits']
        got = [sp.get(k, {}).get('diff') for k in ('train', 'valid', 'blind')]
        if any(g is None for g in got):
            print(f"   {a['ko']:<14} 구간 하나가 미측정 — 판정 불가")
            a['r3'] = None
            continue
        signs = {(1 if g > 0 else -1) for g in got}
        same = len(signs) == 1
        excl = all(sp[k].get('ci95_excl0') for k in ('train', 'valid', 'blind'))
        bonf = all(sp[k].get('bonf9_pass') for k in ('train', 'valid', 'blind'))
        a['r3'] = {'same_sign': same, 'all_ci_excl0': excl, 'all_bonf9': bonf,
                   'diffs': [round(g, 4) for g in got]}
        mark = ('통과' if (same and excl and bonf) else
                ('방향 어긋남' if not same else
                 ('CI 가 0 포함' if not excl else '보정에서 떨어짐')))
        print(f"   {a['ko']:<14} {'  '.join(f'{g:+.2f}' for g in got)}   → {mark}")
        if same and excl and bonf:
            passed.append(key)

    print()
    print("판정")
    print("-" * 78)
    if passed:
        print(f"   세 관문을 모두 통과한 축: {passed}")
        print("   >> 통과해도 2026-11-16 전방 재평가 전에는 게이트에 넣지 않는다")
        print("      (사전등록 §5 · 동결 R78 · 두 국면 규칙을 동시에 넣지 않는다).")
        verdict = f"통과 축 {len(passed)}개 — 배포는 11-16 이후"
    else:
        print("   통과한 축 **0개**.")
        print("   >> (a) 현행 유지 — 매크로는 **표시 전용**으로 둔다.")
        print("      기준을 내리지 않는다. 미측정이 아니라 **재고 미달**이다.")
        verdict = "(a) 현행 유지 — 통과 축 0"
    print(f"   {verdict}")

    json.dump({'ledger_last_date': _ledger_last_date(), 'verdict': verdict, 'passed_axes': passed,
               'cost_pct': COST_PCT, 'buy_score': BUY_SCORE,
               'min_dates': MIN_DATES, 'boot': BOOT, 'seed': SEED,
               'z_bonf9': Z_BONF9, 'ledger_rows': rows, 'buy_cases': kept,
               'blind_dates': len(bl), 'blind_bear_days': len(bear_days),
               'dates': {k: len(v) for k, v in by.items()},
               'axes': axes_out},
              io.open(OUT, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print(f"\n저장: {OUT}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
