# -*- coding: utf-8 -*-
"""라운드 195 — 사전등록 `docs/PREREG_R192_BAND_MONOTONE.md` 를 그대로 잰다.

물음: 랩이 실제로 내는 칸으로, **검사 자신의 표본 규칙**을 그대로
적용하면 적중률은 점수에 대해 단조 증가하는가?

판정 기준(측정 비용 순 · 사전등록에 적힌 그대로):
  R1 검사가 쓰던 표본 규칙을 **글자 그대로** 옮길 수 있는가
     (아래 칸 n>=30 · **맨 위 칸 n>=15**)                    무료
  R2 그 규칙으로 살아남는 칸이 **3개 이상**인가              무료
  R3 살아남은 칸에서 적중률이 **단조 증가**하는가            무료
  R4 빨간불이 **참인가** — 맨 위 칸의 Wilson 하한이
     아래 칸의 Wilson 상한보다 낮은가(= 잡음과 구분 불가)    수 분

**기준을 내리지 않는다.** R3 미달이면 선택지는 둘뿐이다 —
① 비단조를 사실로 적고 계약을 그 사실에 맞게 다시 쓴다,
② 표본 조건을 못 넘는 칸을 건너뜀으로 남기고 요약에 찍는다.
검사를 지우는 선택지는 없다.

실행: C:/Python314/python.exe scripts/band_monotone_r195.py
"""
import io
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
CAL = os.path.join(PROJ, '.portfolio', 'calibration.json')
OUT = os.path.join(PROJ, 'data', 'band_monotone_r195.json')

# ── 검사가 쓰던 표본 규칙 — 글자 그대로 옮긴다 (R1) ──────────────────
#   test_pipeline_fixes.py §55:
#       if all(b.get('n', 0) >= 30 for b in (_b40, _b50)) and _b60.get('n', 0) >= 15:
#   즉 아래 칸들은 30, **맨 위 칸은 15**.
MIN_N_LOWER = 30
MIN_N_TOP = 15


def wilson(k, n, z=1.96):
    """Wilson 구간 (하한, 상한) — 작은 표본은 이걸로 본다 (§2-4)."""
    if n <= 0:
        return (None, None)
    p = k / n
    d = 1.0 + z * z / n
    c = p + z * z / (2 * n)
    r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - r) / d, (c + r) / d)


def main():
    res = {'prereg': 'docs/PREREG_R192_BAND_MONOTONE.md',
           'measured_at_source': CAL}
    if not os.path.exists(CAL):
        res['error'] = 'calibration.json 없음 — 랩 미실행'
        io.open(OUT, 'w', encoding='utf-8').write(
            json.dumps(res, ensure_ascii=False, indent=1))
        print('SKIP: calibration.json 없음')
        return

    cal = json.load(io.open(CAL, encoding='utf-8'))
    bands = [b for b in (cal.get('bands') or [])
             if b.get('n') is not None and b.get('hit_rate') is not None]
    bands.sort(key=lambda b: (b['lo'], b['hi']))
    res['generated_from'] = cal.get('generated_from')
    res['total_cases'] = cal.get('total_cases')
    res['bands_all'] = [{'lo': b['lo'], 'hi': b['hi'], 'n': b['n'],
                         'hit_rate': b['hit_rate'],
                         'avg_return': b.get('avg_return')} for b in bands]

    # ── R1 — 규칙을 그대로 옮겼는가 ─────────────────────────────────
    res['R1'] = {'rule': f'아래 칸 n>={MIN_N_LOWER} · 맨 위 칸 n>={MIN_N_TOP}',
                 'source': 'test_pipeline_fixes.py §55 (글자 그대로)',
                 'pass': True}

    # ── R2 — 그 규칙으로 살아남는 칸이 3개 이상인가 ─────────────────
    kept = []
    for i, b in enumerate(bands):
        is_top = (i == len(bands) - 1)
        need = MIN_N_TOP if is_top else MIN_N_LOWER
        if b['n'] >= need:
            kept.append(b)
    res['R2'] = {'kept': [f"({b['lo']},{b['hi']}):n={b['n']}" for b in kept],
                 'count': len(kept), 'pass': len(kept) >= 3}
    if not res['R2']['pass']:
        res['verdict'] = 'R2 미달 — 2칸으로는 단조를 말할 수 없다. 기각.'
        _write(res)
        return

    # ── R3 — 단조 증가인가 ─────────────────────────────────────────
    rates = [b['hit_rate'] for b in kept]
    breaks = [(kept[i]['lo'], kept[i]['hi'], rates[i],
               kept[i + 1]['lo'], kept[i + 1]['hi'], rates[i + 1])
              for i in range(len(rates) - 1) if rates[i] >= rates[i + 1]]
    res['R3'] = {'rates': rates, 'monotone': not breaks,
                 'breaks': [f'({a},{b}) {r1:.2f}% >= ({c},{d}) {r2:.2f}%'
                            for a, b, r1, c, d, r2 in breaks],
                 'pass': not breaks}

    # ── R4 — 그 끊김이 잡음과 구분되는가 (Wilson) ───────────────────
    r4 = []
    for a, b, r1, c, d, r2 in breaks:
        hi_band = next(x for x in kept if x['lo'] == a and x['hi'] == b)
        lo_band = next(x for x in kept if x['lo'] == c and x['hi'] == d)
        k_hi = round(hi_band['hit_rate'] / 100.0 * hi_band['n'])
        k_lo = round(lo_band['hit_rate'] / 100.0 * lo_band['n'])
        w_hi = wilson(k_hi, hi_band['n'])
        w_lo = wilson(k_lo, lo_band['n'])
        # 겹치면 '잡음과 구분 불가'
        overlap = not (w_lo[1] < w_hi[0] or w_hi[1] < w_lo[0])
        r4.append({
            'lower_band': f'({a},{b})', 'lower_n': hi_band['n'],
            'lower_ci': [round(w_hi[0] * 100, 2), round(w_hi[1] * 100, 2)],
            'upper_band': f'({c},{d})', 'upper_n': lo_band['n'],
            'upper_ci': [round(w_lo[0] * 100, 2), round(w_lo[1] * 100, 2)],
            'overlap': overlap})
    res['R4'] = {'breaks': r4,
                 'all_overlap': bool(r4) and all(x['overlap'] for x in r4)}

    if res['R3']['pass']:
        res['verdict'] = ('R1~R3 통과 — 랩이 내는 칸과 검사 자신의 표본 '
                          '규칙으로 적중률은 단조 증가한다.')
    elif res['R4']['all_overlap']:
        res['verdict'] = ('R3 미달 — 단조가 아니다. 다만 끊긴 자리의 Wilson '
                          '구간이 전부 겹쳐 **잡음과 구분되지 않는다**. '
                          '기준을 내리지 않는다: 표본 조건을 못 넘는 칸은 '
                          '건너뜀으로 남기고 요약에 찍는다.')
    else:
        res['verdict'] = ('R3 미달 — 단조가 아니고, 끊김이 잡음으로도 '
                          '설명되지 않는다. 비단조를 사실로 적는다.')
    _write(res)


def _write(res):
    io.open(OUT, 'w', encoding='utf-8').write(
        json.dumps(res, ensure_ascii=False, indent=1))
    for k in ('R1', 'R2', 'R3', 'R4'):
        if k in res:
            line = k + ' ' + json.dumps(res[k], ensure_ascii=False)[:220]
            print(line.encode('ascii', 'replace').decode('ascii'))
    print(('VERDICT: ' + str(res.get('verdict')))
          .encode('ascii', 'replace').decode('ascii'))
    print('->', OUT)


if __name__ == '__main__':
    main()


# ── 곁들여: §55 의 **두 번째 계약**도 함께 잰다 ──────────────────────
#   check("매수권(60점+) 평균수익 양수 — 비용 차감 후에도",
#         (_b60.get('avg_return') or -1) - 0.55 > 0)
#   이 검사도 (60,100) 칸을 물어 같이 죽어 있었다. 랩이 내는 칸으로
#   60점 이상을 **가중 합산**해 다시 잰다. 비용 0.55 도 그대로 쓴다.
COST_PCT_55 = 0.55


def buyzone_ev():
    import io as _io
    import json as _json
    import os as _os
    cal = _json.load(_io.open(CAL, encoding='utf-8'))
    bands = [b for b in (cal.get('bands') or [])
             if b.get('n') and b.get('avg_return') is not None]
    top = [b for b in bands if b['lo'] >= 60]
    n = sum(b['n'] for b in top)
    if not n:
        return None
    ev = sum(b['n'] * b['avg_return'] for b in top) / n
    hit = sum(b['n'] * b['hit_rate'] for b in top) / n
    out = {'bands': [f"({b['lo']},{b['hi']}):n={b['n']}" for b in top],
           'n': n, 'avg_return': round(ev, 5),
           'hit_rate': round(hit, 3),
           'cost_pct': COST_PCT_55,
           'net': round(ev - COST_PCT_55, 5),
           'positive_after_cost': (ev - COST_PCT_55) > 0}
    p = _os.path.join(PROJ, 'data', 'buyzone_ev_r195.json')
    _io.open(p, 'w', encoding='utf-8').write(
        _json.dumps(out, ensure_ascii=False, indent=1))
    print(('BUYZONE ' + _json.dumps(out, ensure_ascii=False))
          .encode('ascii', 'replace').decode('ascii'))
    return out


if __name__ == '__main__':
    buyzone_ev()
