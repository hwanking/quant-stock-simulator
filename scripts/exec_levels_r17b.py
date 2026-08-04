# -*- coding: utf-8 -*-
"""
라운드 17b — 통과 후보를 깨러 간다.

라운드 17 에서 (목표 1.3배 · 손절 0.6배)가 사전등록 기준을 전부 통과했다.
5번의 승격 라운드 만에 처음이다. 그래서 더 의심해야 한다.

■ 라운드 17 설계의 약점 — 내가 먼저 밝힌다
  기준 ⑤ '종목 홀드아웃'은 사실상 무의미했다. holdout 코호트가 전체의
  98%라서 blind 와 거의 같은 집합이다. 독립 검증이 아니었다.

■ 이번에 하는 것 — 후보를 **깨는** 방향으로만
  ① 산수 검증: 기대값을 버킷 분해로 다시 세어 본다 (재시뮬 함수 신뢰성)
  ② 진짜 종목 분할: 실전을 티커로 반씩 갈라 **양쪽 다** 양수인가
  ③ 시간 분할: 실전을 전반/후반으로 갈라 **양쪽 다** 양수인가
  ④ 부트스트랩 1만회: 실전 기대값 95% 신뢰구간 **하한이 0보다 큰가**
  ⑤ 고원인가 첨탑인가: 이웃 격자점도 양수인가 (한 점만 튀면 우연이다)
  ⑥ 모호분 최악 가정이 실제로 최악인가 — 모호분을 전부 손절로 놓고도 양수인가
     (라운드 17 이 이미 그렇게 셌지만, 모호분만 따로 떼어 확인한다)
  ⑦ 국면 쏠림: 특정 칸 하나가 전체 기대값을 만들고 있지 않은가

■ 채택 조건 (사전등록)
  ②③④ **전부** 통과해야 한다. 하나라도 실패하면 이 후보도 기각한다.
  ④의 하한이 0 이하이면 '기대값이 양수라고 말할 수 없다' 는 뜻이므로 기각.
"""
import io
import json
import os
import random
import sys
import zlib
from collections import Counter, defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'scripts'))
OUT = os.path.join(BASE, '.portfolio', 'exec_levels_r17b.json')

from exec_levels_r17 import (BUY, COST, load, prep, resim, evaluate,
                             A_GRID, B_GRID)

CAND = [(1.3, 0.6), (1.3, 0.8)]     # 라운드 17 통과 후보
BOOT = 10000
SEED = 20260804                      # 고정 — 돌릴 때마다 답이 바뀌면 안 된다
VOL_CUT = 0.03
REG_KO = {'BULL': '상승', 'SIDEWAYS': '옆걸음', 'BEAR': '하락'}


def cell6(c):
    rg, v = c.get('regime'), c.get('vol20')
    if not rg or v is None:
        return None
    return f"{'거친' if v >= VOL_CUT else '차분한'} {REG_KO.get(rg, rg)}"


def rets(cases, a, b, worst=True):
    """각 사례의 수익률(최악 가정) 목록 — 비용 차감 전."""
    out = []
    for c in cases:
        tp, sp = c['TP'] * a, c['SP'] * b
        _, bst, wst = resim(c, tp, sp)
        out.append(wst if worst else bst)
    return out


def ev(cases, a, b):
    r = rets(cases, a, b)
    return (sum(r) / len(r) - COST) if r else None


def main():
    rows = load()
    cases = []
    for r in rows:
        if (r.get('score') or 0) < BUY:
            continue
        c = prep(r)
        if c:
            c['ticker'] = r.get('ticker')
            c['date'] = r.get('date')
            cases.append(c)
    blind = [c for c in cases if c['split'] == 'blind']
    valid = [c for c in cases if c['split'] == 'valid']
    print(f'실전(blind) {len(blind)}건 · 검증(valid) {len(valid)}건\n')

    result = {}
    for a, b in CAND:
        print('=' * 74)
        print(f'후보: 목표 {a}배 · 손절 {b}배  (손익비 {0.70 * a / b:.2f}:1)')
        print('=' * 74)
        rec = {'a': a, 'b': b, 'checks': {}}

        # ① 산수 검증 — 버킷 분해
        print('\n① 산수 검증 — 버킷으로 다시 세기')
        kinds = Counter()
        contrib = defaultdict(float)
        for c in blind:
            tp, sp = c['TP'] * a, c['SP'] * b
            k, _, wst = resim(c, tp, sp)
            kk = 'STOP' if k == 'AMB' else k       # 최악 가정
            kinds[kk] += 1
            contrib[kk] += wst
        n = len(blind)
        tot = 0.0
        for k in ('TARGET', 'STOP', 'OPEN'):
            if not kinds[k]:
                continue
            share = kinds[k] / n * 100
            avg = contrib[k] / kinds[k]
            tot += contrib[k]
            print(f'   {k:6s} {kinds[k]:>4}건 ({share:5.1f}%) '
                  f'평균 {avg:+6.2f}% → 기여 {contrib[k] / n:+.3f}%p')
        print(f'   합계 {tot / n:+.3f}% − 비용 {COST}% = '
              f'{tot / n - COST:+.3f}%')
        rec['checks']['decomposition'] = {
            k: {'n': kinds[k], 'avg': (contrib[k] / kinds[k]) if kinds[k] else None}
            for k in ('TARGET', 'STOP', 'OPEN')}
        rec['ev_blind'] = tot / n - COST

        # ② 진짜 종목 분할 — 티커 해시로 반씩
        print('\n② 종목 반반 — 양쪽 다 양수인가 (진짜 일반화 검사)')
        # hash() 는 실행마다 달라져 연구가 재현되지 않는다 — crc32 로 고정
        def _half(t):
            return zlib.crc32(str(t).encode()) % 2
        h1 = [c for c in blind if _half(c['ticker']) == 0]
        h2 = [c for c in blind if _half(c['ticker']) == 1]
        e1, e2 = ev(h1, a, b), ev(h2, a, b)
        ok2 = (e1 is not None and e2 is not None and e1 > 0 and e2 > 0
               and len(h1) >= 30 and len(h2) >= 30)
        print(f'   A군 {len(h1):>3}건 {e1:+.2f}%   B군 {len(h2):>3}건 {e2:+.2f}%'
              f'   → {"통과" if ok2 else "실패"}')
        rec['checks']['ticker_halves'] = {'a_n': len(h1), 'a_ev': e1,
                                          'b_n': len(h2), 'b_ev': e2, 'ok': ok2}

        # ③ 시간 분할
        print('\n③ 실전 기간 전반/후반 — 양쪽 다 양수인가')
        sb = sorted(blind, key=lambda c: c['date'])
        mid = len(sb) // 2
        f1, f2 = sb[:mid], sb[mid:]
        e3a, e3b = ev(f1, a, b), ev(f2, a, b)
        ok3 = (e3a is not None and e3b is not None and e3a > 0 and e3b > 0)
        print(f"   전반 {f1[0]['date']}~{f1[-1]['date']} {len(f1):>3}건 "
              f"{e3a:+.2f}%")
        print(f"   후반 {f2[0]['date']}~{f2[-1]['date']} {len(f2):>3}건 "
              f"{e3b:+.2f}%   → {'통과' if ok3 else '실패'}")
        rec['checks']['time_halves'] = {'first_ev': e3a, 'second_ev': e3b,
                                        'ok': ok3}

        # ④ 부트스트랩
        print(f'\n④ 부트스트랩 {BOOT:,}회 — 95% 구간 하한이 0보다 큰가')
        rng = random.Random(SEED)
        base_r = rets(blind, a, b)
        n_b = len(base_r)
        sims = []
        for _ in range(BOOT):
            s = sum(base_r[rng.randrange(n_b)] for _ in range(n_b))
            sims.append(s / n_b - COST)
        sims.sort()
        lo = sims[int(BOOT * 0.025)]
        hi = sims[int(BOOT * 0.975)]
        ok4 = lo > 0
        print(f'   기대값 {sum(base_r) / n_b - COST:+.2f}%  '
              f'95% 구간 [{lo:+.2f}%, {hi:+.2f}%]  '
              f'→ {"통과" if ok4 else "실패 (0을 포함)"}')
        rec['checks']['bootstrap'] = {'lo': lo, 'hi': hi, 'ok': ok4}

        # ⑤ 고원인가
        print('\n⑤ 이웃 격자점도 양수인가 (첨탑이면 우연이다)')
        ia, ib = A_GRID.index(a), B_GRID.index(b)
        nb_ok = nb_tot = 0
        for da in (-1, 0, 1):
            for db in (-1, 0, 1):
                if da == 0 and db == 0:
                    continue
                ja, jb = ia + da, ib + db
                if not (0 <= ja < len(A_GRID) and 0 <= jb < len(B_GRID)):
                    continue
                e = ev(blind, A_GRID[ja], B_GRID[jb])
                nb_tot += 1
                if e is not None and e > 0:
                    nb_ok += 1
        print(f'   이웃 {nb_tot}점 중 양수 {nb_ok}점 '
              f'→ {"고원" if nb_ok >= nb_tot * 0.6 else "첨탑 — 의심"}')
        rec['checks']['plateau'] = {'ok_n': nb_ok, 'total': nb_tot}

        # ⑥ 모호분만 따로
        print('\n⑥ 모호분 — 최악 가정이 실제로 얼마나 아픈가')
        amb = []
        for c in blind:
            tp, sp = c['TP'] * a, c['SP'] * b
            k, bst, wst = resim(c, tp, sp)
            if k == 'AMB':
                amb.append((bst, wst))
        if amb:
            eb = sum(x[0] for x in amb) / len(amb)
            ew = sum(x[1] for x in amb) / len(amb)
            print(f'   모호 {len(amb)}건 ({len(amb) / n * 100:.1f}%) '
                  f'최선 평균 {eb:+.2f}% · 최악 평균 {ew:+.2f}%')
            print(f'   → 전부 목표로 봐도/전부 손절로 봐도 기대값 차이는 '
                  f'{(eb - ew) * len(amb) / n:.2f}%p')
        else:
            print('   모호 0건 — 판정이 전부 확정된다')
        rec['checks']['ambiguous_n'] = len(amb)

        # ⑦ 국면 쏠림
        print('\n⑦ 국면 쏠림 — 한 칸이 전체를 만들고 있지 않은가')
        by = defaultdict(list)
        for c in blind:
            by[cell6(c) or '국면 미상'].append(c)
        for name in sorted(by, key=lambda x: -len(by[x])):
            g = by[name]
            e = ev(g, a, b)
            share = sum(rets(g, a, b)) / n
            print(f'   {name:10s} {len(g):>3}건  기대값 {e:+6.2f}%  '
                  f'전체 기여 {share:+.3f}%p')
        rec['checks']['by_cell'] = {k: {'n': len(v), 'ev': ev(v, a, b)}
                                    for k, v in by.items()}

        verdict = ok2 and ok3 and ok4
        rec['pass'] = verdict
        print(f"\n  ▶ 판정: {'생존 — 채택 검토 가능' if verdict else '기각'}"
              f"  (②{'O' if ok2 else 'X'} ③{'O' if ok3 else 'X'} "
              f"④{'O' if ok4 else 'X'})")
        result[f'{a}_{b}'] = rec
        print()

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump({'round': '17b', 'bootstrap': BOOT, 'seed': SEED,
                   'candidates': result}, f, ensure_ascii=False, indent=1)
    print(f'기록: {OUT}')


if __name__ == '__main__':
    main()
