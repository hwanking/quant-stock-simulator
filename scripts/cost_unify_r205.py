# -*- coding: utf-8 -*-
"""라운드 205 — 사전등록 `docs/PREREG_R191_COST_UNIFY.md` 의 R3·R4 를 잰다.

R1(무료·기측정): 항목 합 = 0.41 정확. **0.36 은 어떤 부분집합·자연
  변형(편도 0.205 · 세금 제외 0.21 · 슬리피지 제외 0.23)에서도 안 나온다.**
  사전등록 문구대로 "산술 착오"다. (산술 사실 하나: 세금을 0.15 로 두면
  0.03+0.15+0.18 = 0.36 이 정확히 나온다 — 다만 이 저장소에 세율 근거
  문서는 없다. 해석이지 측정이 아니다.)
R2(기측정): 슬리피지 0.18 은 이 저장소에서 **측정된 적 없다** — 사전등록·
  주석의 단언뿐이다. 세율 0.20 의 근거 문서도 없다. 곁들여 PREREG_R54 의
  내역(0.03×2+0.20+0.18)은 합이 0.44 인데 0.36 이라 적는 어긋난 사본이다.

여기서 재는 것:
R3  비용 민감도 — 매수권(58+) 블라인드에서 적중률(비용 무관)과
    비용별 순 EV(0.30/0.36/0.41). 세 값의 **부호가 같은가**.
R4  게이트 비교 — 기대값 게이트(exp>0)를 0.36/0.41 로 각각 걸었을 때
    통과분의 **블라인드 실측 성적**. 0.41 통과분이 0.36 통과분보다
    나쁘면 그 게이트는 걸러 내는 게 아니라 표본만 줄이는 것이다.
    잣대는 `_probe/r191_cost3.py` 의 복원식을 **그대로** 쓴다:
    exp = p·up + (1−p)·dn − COST (p = 그 점수대 밴드 적중률).

채택 조건(사전등록 그대로): R1 통과 + R3 세 값 방향 동일 + R4 0.41
통과분이 나빠지지 않을 것. 하나라도 미달이면 기각·현행(0.36) 유지.

실행: C:/Python314/python.exe scripts/cost_unify_r205.py
"""
import io
import json
import os

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LED = os.path.join(PROJ, '.portfolio', 'virtual_graded.jsonl')
CAL = os.path.join(PROJ, '.portfolio', 'calibration.json')
OUT = os.path.join(PROJ, 'data', 'cost_unify_r205.json')

COSTS = (0.30, 0.36, 0.41)


def main():
    cal = json.load(io.open(CAL, encoding='utf-8'))
    bands = [b for b in (cal.get('bands') or []) if b.get('lo') is not None]

    def hit_for(score):
        for b in bands:
            if b['lo'] <= score <= b['hi'] and (b.get('n') or 0) >= 30:
                return b.get('hit_rate')
        return None

    n_rows = usable = 0
    # R3 — 블라인드 매수권(58+) 실측
    blind = {'n': 0, 'hits': 0, 'sum_ret': 0.0}
    # R4 — 게이트 통과분 (전 구간에서 게이트를 걸고, 블라인드 부분집합 성적)
    gate = {c: {'n_all': 0, 'blind_n': 0, 'blind_hits': 0,
                'blind_sum_ret': 0.0} for c in COSTS}
    carried = 0

    for line in io.open(LED, encoding='utf-8'):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        n_rows += 1
        if r.get('carried_over'):
            carried += 1
        try:
            px = float(r.get('price') or 0)
            tg = float(r.get('target') or 0)
            st = float(r.get('stop') or 0)
            sc = float(r.get('score') or 0)
            ret = float(r.get('return_pct') or 0)
        except (TypeError, ValueError):
            continue
        split = str(r.get('split') or '')
        is_blind = (split == 'blind')
        if sc >= 58 and is_blind:
            blind['n'] += 1
            blind['hits'] += 1 if r.get('success') else 0
            blind['sum_ret'] += ret
        if not (px > 0 and tg > 0 and st > 0):
            continue
        h = hit_for(sc)
        if h is None:
            continue
        usable += 1
        p = h / 100.0
        up = (tg / px - 1.0) * 100.0
        dn = (st / px - 1.0) * 100.0
        base = p * up + (1 - p) * dn
        for c in COSTS:
            if base - c > 0:
                g = gate[c]
                g['n_all'] += 1
                if is_blind:
                    g['blind_n'] += 1
                    g['blind_hits'] += 1 if r.get('success') else 0
                    g['blind_sum_ret'] += ret

    res = {'measured_at_rows': n_rows, 'usable': usable,
           'carried_over_rows': carried,
           'prereg': 'docs/PREREG_R191_COST_UNIFY.md'}

    # ── R3 ──
    bn = blind['n']
    mean_ret = (blind['sum_ret'] / bn) if bn else None
    r3 = {'blind_n_58plus': bn,
          'hit_rate': (100.0 * blind['hits'] / bn) if bn else None,
          'mean_ret_raw': mean_ret,
          'net_ev': {str(c): (None if mean_ret is None
                              else round(mean_ret - c, 4)) for c in COSTS}}
    signs = ({(1 if v > 0 else (-1 if v < 0 else 0))
              for v in r3['net_ev'].values() if v is not None}
             if mean_ret is not None else set())
    r3['same_sign'] = (len(signs) == 1)
    res['R3'] = r3

    # ── R4 ──
    r4 = {}
    for c in COSTS:
        g = gate[c]
        bn4 = g['blind_n']
        r4[str(c)] = {
            'passers_all': g['n_all'],
            'blind_n': bn4,
            'blind_hit': (100.0 * g['blind_hits'] / bn4) if bn4 else None,
            'blind_mean_ret_raw': (g['blind_sum_ret'] / bn4) if bn4 else None,
        }
    res['R4'] = r4
    a, b = r4['0.36'], r4['0.41']
    both = (a['blind_n'] or 0) > 0 and (b['blind_n'] or 0) > 0
    res['R4_verdict'] = {
        'comparable': both,
        'strict_not_worse': (both and b['blind_mean_ret_raw'] is not None
                             and a['blind_mean_ret_raw'] is not None
                             and b['blind_mean_ret_raw']
                             >= a['blind_mean_ret_raw']),
        'note': ('블라인드 통과분이 한쪽이라도 0건이면 R4 는 판정 불가 — '
                 '못 잰 것을 통과로 적지 않는다 (§3)')}

    io.open(OUT, 'w', encoding='utf-8').write(
        json.dumps(res, ensure_ascii=False, indent=1))
    print(json.dumps(res, ensure_ascii=False, indent=1)
          .encode('ascii', 'replace').decode('ascii'))
    print('->', OUT)


if __name__ == '__main__':
    main()
