# -*- coding: utf-8 -*-
"""라운드 215 — 사전등록 `docs/PREREG_R215_FAIR_VALUE_CALIBRATION.md` 의 R1 을 잰다.

물음: 매수권(58+)에서 '적정가 이하 (안전마진 미확보)' 가 '안전마진 확보'(깊은
할인)보다 **정말** 낫나 — 원장 전체 · 세 구간 · 날짜 군집 부트스트랩.

  ① blind 에서 (이하 − 확보) 원수익 차의 CI95 가 0 을 제외하는가
  ② train · valid 에서도 같은 부호인가

잣대는 R208 을 그대로 재사용한다(시드만 215). 새 숫자 없음.
곁들여 여섯 구역 전부의 세 구간 표를 찍는다 — 보정 곡선의 거친 밑그림.

실행: C:/Python314/python.exe scripts/fair_value_zone_r215.py
"""
import io
import json
import os
import random

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LED = os.path.join(PROJ, '.portfolio', 'virtual_graded.jsonl')
OUT = os.path.join(PROJ, 'data', 'fair_value_zone_r215.json')

BUY = 58.0
N_BOOT = 2000
SEED = 215
ZA = '적정가 이하 (안전마진 미확보)'     # 얕은 할인
ZB = '안전마진 확보'                      # 깊은 할인
ZONES = (ZB, ZA, '적정가 소폭 초과', '적정가 초과 (추격매수 경고)',
         '적정가 크게 초과 (추격매수 위험)', '판정 불가')


def _wilson_low(k, n, z=1.96):
    if not n:
        return None
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5
    return round((c - r) / d * 100.0, 1)


def main():
    by = {s: {} for s in ('train', 'valid', 'blind')}   # split → date → zone → [ret]
    n_rows = n_buy = 0
    for line in io.open(LED, encoding='utf-8'):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:                                      # noqa: BLE001
            continue
        n_rows += 1
        sp = str(r.get('split') or '')
        if sp not in by:
            continue
        try:
            if float(r.get('score') or 0) < BUY:
                continue
            ret = float(r.get('return_pct') or 0)
        except (TypeError, ValueError):
            continue
        if r.get('outcome') is None and r.get('success') is None:
            continue
        n_buy += 1
        z = str(r.get('entry_zone') or '판정 불가')
        by[sp].setdefault(str(r.get('date') or '?'), {}).setdefault(z, []).append(
            (ret, bool(r.get('success'))))

    def table(cells):
        out = {}
        for z in ZONES:
            rs = [x for c in cells.values() for x in c.get(z, [])]
            n = len(rs)
            if not n:
                out[z] = dict(n=0)
                continue
            hit = sum(1 for _, s in rs if s)
            out[z] = dict(n=n, hit_pct=round(hit / n * 100.0, 1),
                          wilson_low=_wilson_low(hit, n),
                          mean_ret=round(sum(v for v, _ in rs) / n, 4))
        return out

    res = {'prereg': 'docs/PREREG_R215_FAIR_VALUE_CALIBRATION.md',
           'measured_at_rows': n_rows, 'buy_zone_rows': n_buy,
           'seed': SEED, 'n_boot': N_BOOT, 'zones': {}, 'R1': {}}
    for sp in ('train', 'valid', 'blind'):
        res['zones'][sp] = table(by[sp])

    # ── R1 — (이하 − 확보) 날짜 군집 부트스트랩, 세 구간 각각 ───────────
    rng = random.Random(SEED)
    for sp in ('train', 'valid', 'blind'):
        dates = [d for d, c in by[sp].items() if c.get(ZA) or c.get(ZB)]
        a_all = [v for c in by[sp].values() for v, _ in c.get(ZA, [])]
        b_all = [v for c in by[sp].values() for v, _ in c.get(ZB, [])]
        if not (a_all and b_all and dates):
            res['R1'][sp] = dict(n_a=len(a_all), n_b=len(b_all), note='표본 없음')
            continue
        obs = sum(a_all) / len(a_all) - sum(b_all) / len(b_all)
        diffs = []
        for _ in range(N_BOOT):
            a, b = [], []
            for _ in range(len(dates)):
                c = by[sp][rng.choice(dates)]
                a += [v for v, _ in c.get(ZA, [])]
                b += [v for v, _ in c.get(ZB, [])]
            if a and b:
                diffs.append(sum(a) / len(a) - sum(b) / len(b))
        diffs.sort()
        lo = diffs[int(0.025 * len(diffs))]
        hi = diffs[int(0.975 * len(diffs))]
        res['R1'][sp] = dict(n_a=len(a_all), n_b=len(b_all), dates=len(dates),
                             obs_diff=round(obs, 4), ci95=[round(lo, 4), round(hi, 4)],
                             excludes_zero=(lo > 0 or hi < 0),
                             sign=(1 if obs > 0 else -1))

    b = res['R1'].get('blind', {})
    t = res['R1'].get('train', {})
    v = res['R1'].get('valid', {})
    c1 = bool(b.get('excludes_zero')) and b.get('sign') == 1
    c2 = (t.get('sign') == 1 and v.get('sign') == 1)
    if c1 and c2:
        res['verdict'] = ('H1 후보 — blind 유의(+) · train·valid 같은 부호. '
                          'R2(블라인드 백필)로 연다. 규칙은 아직 안 바꾼다.')
    elif c1 and not c2:
        res['verdict'] = ('(a) 현행 유지 — blind 만 유의. train/valid 부호가 다르다 '
                          '→ 조성 변화 의심 (R212·R213 의 그 모양). 채택 안 한다.')
    else:
        res['verdict'] = '(a) 현행 유지 — H0. 깊은 할인이 더 나쁘다는 증거가 없다.'
    io.open(OUT, 'w', encoding='utf-8').write(json.dumps(res, ensure_ascii=False, indent=1))
    print(json.dumps(res, ensure_ascii=False, indent=1).encode('ascii', 'replace').decode('ascii'))
    print('->', OUT)


if __name__ == '__main__':
    main()
