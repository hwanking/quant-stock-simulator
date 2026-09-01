# -*- coding: utf-8 -*-
"""라운드 208 — 사전등록 `docs/PREREG_R208_EV_GATE_ANTISELECT.md` 를 잰다.

물음: 매수권(58+) 블라인드에서 exp_ret>0(운영 게이트 통과) 행이
미통과 행보다 실측 성적이 나쁜가(역선별)?

R1(기확인): 복원식 = 운영 산식 동일 (p·up+(1−p)·dn−COST_PCT ·
  케이스 자신의 밴드 p · n≥30).
R2: 통과 vs 미통과 원수익 평균 차 — **날짜 군집 부트스트랩** 95% CI
  (같은 날 케이스는 함께 움직인다 · R80 ICC / R129).
R3: train·valid 에서도 같은 부호인가.
R4: MDE — 지금 표본으로 몇 %p 까지 보나. 관측 차 < MDE 면 판정 불가.

결정 선택지·표본 조건(블라인드 통과 n≥30)은 사전등록에 적힌 그대로다.
난수 시드는 고정한다(재현).

실행: C:/Python314/python.exe scripts/ev_gate_antiselect_r208.py
"""
import io
import json
import os
import random

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LED = os.path.join(PROJ, '.portfolio', 'virtual_graded.jsonl')
CAL = os.path.join(PROJ, '.portfolio', 'calibration.json')
OUT = os.path.join(PROJ, 'data', 'ev_gate_antiselect_r208.json')

COST = 0.36          # 운영 게이트 (verdict_core.COST_PCT)
N_BOOT = 2000
SEED = 208


def main():
    cal = json.load(io.open(CAL, encoding='utf-8'))
    bands = [b for b in (cal.get('bands') or []) if b.get('lo') is not None]

    def hit_for(score):
        for b in bands:
            if b['lo'] <= score <= b['hi'] and (b.get('n') or 0) >= 30:
                return b.get('hit_rate')
        return None

    # split → date → {'pass': [...], 'fail': [...]} (원수익)
    by = {s: {} for s in ('train', 'valid', 'blind')}
    n_rows = 0
    for line in io.open(LED, encoding='utf-8'):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        n_rows += 1
        sp = str(r.get('split') or '')
        if sp not in by:
            continue
        try:
            sc = float(r.get('score') or 0)
            if sc < 58:
                continue
            px = float(r.get('price') or 0)
            tg = float(r.get('target') or 0)
            st = float(r.get('stop') or 0)
            ret = float(r.get('return_pct') or 0)
        except (TypeError, ValueError):
            continue
        if not (px > 0 and tg > 0 and st > 0):
            continue
        h = hit_for(sc)
        if h is None:
            continue
        p = h / 100.0
        up = (tg / px - 1.0) * 100.0
        dn = (st / px - 1.0) * 100.0
        exp = p * up + (1 - p) * dn - COST
        d = str(r.get('date') or '?')
        cell = by[sp].setdefault(d, {'pass': [], 'fail': []})
        cell['pass' if exp > 0 else 'fail'].append(ret)

    def summarize(cells):
        pn = sum(len(c['pass']) for c in cells.values())
        fn = sum(len(c['fail']) for c in cells.values())
        pm = (sum(sum(c['pass']) for c in cells.values()) / pn) if pn else None
        fm = (sum(sum(c['fail']) for c in cells.values()) / fn) if fn else None
        return pn, fn, pm, fm

    res = {'prereg': 'docs/PREREG_R208_EV_GATE_ANTISELECT.md',
           'cost': COST, 'measured_at_rows': n_rows,
           'R1': 'formula identical to verdict_core.build (code-verified)'}

    # ── 표본 조건 먼저 (사전등록: 블라인드 통과 n>=30 미달이면 안 잰다) ──
    bp, bf, bpm, bfm = summarize(by['blind'])
    res['blind'] = {'pass_n': bp, 'fail_n': bf,
                    'pass_mean': bpm, 'fail_mean': bfm}
    if bp < 30:
        res['verdict'] = ('표본 부족 — 블라인드 통과 %d건 < 30. 판정 불가 · '
                          '(a) 현행 유지' % bp)
        _write(res)
        return

    # ── R2 — 날짜 군집 부트스트랩 (블라인드) ─────────────────────────
    rng = random.Random(SEED)
    dates = [d for d, c in by['blind'].items() if c['pass'] or c['fail']]
    diffs = []
    for _ in range(N_BOOT):
        ps, fs = [], []
        for _ in range(len(dates)):
            c = by['blind'][rng.choice(dates)]
            ps += c['pass']
            fs += c['fail']
        if ps and fs:
            diffs.append(sum(ps) / len(ps) - sum(fs) / len(fs))
    diffs.sort()
    lo = diffs[int(0.025 * len(diffs))]
    hi = diffs[int(0.975 * len(diffs))]
    obs = bpm - bfm
    res['R2'] = {'obs_diff_pass_minus_fail': round(obs, 4),
                 'boot_ci95': [round(lo, 4), round(hi, 4)],
                 'n_boot': len(diffs), 'seed': SEED,
                 'excludes_zero': (lo > 0 or hi < 0)}

    # ── R3 — train·valid 부호 ────────────────────────────────────────
    r3 = {}
    for sp in ('train', 'valid'):
        pn, fn, pm, fm = summarize(by[sp])
        r3[sp] = {'pass_n': pn, 'fail_n': fn,
                  'pass_mean': (round(pm, 4) if pm is not None else None),
                  'fail_mean': (round(fm, 4) if fm is not None else None),
                  'diff': (round(pm - fm, 4)
                           if pm is not None and fm is not None else None)}
    res['R3'] = r3
    signs = {(-1 if (v['diff'] or 0) < 0 else 1)
             for v in r3.values() if v['diff'] is not None}
    signs.add(-1 if obs < 0 else 1)
    res['R3_same_sign'] = (len(signs) == 1)

    # ── R4 — MDE (CI 반폭) ──────────────────────────────────────────
    mde = (hi - lo) / 2.0
    res['R4'] = {'mde_halfwidth': round(mde, 4),
                 'obs_within_noise': abs(obs) < mde}

    # ── 판정 (사전등록 선택지) ──────────────────────────────────────
    if res['R2']['excludes_zero'] and obs < 0 and res['R3_same_sign']:
        res['verdict'] = ('(b) 조건 충족 — 역선별이 군집 CI 로 확인되고 세 '
                          '구간 부호 일관. 다만 게이트 제거는 별도 라운드의 '
                          '구현·회귀로 한다(이 산출물은 측정이다).')
    elif obs < 0 and res['R3_same_sign']:
        res['verdict'] = ('(c) — CI 는 0 을 포함하나 세 구간 부호가 일관되게 '
                          '역선별 방향. 게이트는 유지하되 사실을 기재한다.')
    else:
        res['verdict'] = '(a) 현행 유지 — 역선별의 일관된 증거 없음.'
    _write(res)


def _write(res):
    io.open(OUT, 'w', encoding='utf-8').write(
        json.dumps(res, ensure_ascii=False, indent=1))
    print(json.dumps(res, ensure_ascii=False, indent=1)
          .encode('ascii', 'replace').decode('ascii'))
    print('->', OUT)


if __name__ == '__main__':
    main()
