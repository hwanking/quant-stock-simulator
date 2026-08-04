# -*- coding: utf-8 -*-
"""
라운드 26 — 못 겨뤘던 진입 엔진을 마저 겨룬다 (지지선·이동평균·볼린저).

════════════════════════════════════════════════════════════════════════
■ 왜 이제야 겨루나
  라운드 25 는 고정 할인·변동성 비례·돌파만 겨뤘다. 지지선·이동평균·
  볼린저 기반 진입가는 **원장에 그 값이 없어** 계산할 수 없었다.
  라운드 26 에서 기준일 시점의 지표 레벨을 19,883건 전부 남겼다
  (`virtual_levels.jsonl` · 엔진과 같은 산식 · 기준일 이후 봉 배제).

■ 후보 (전부 기준일에 알 수 있는 값 — 누수 없음)
  현재가 즉시                        기준선
  변동성 1배                         라운드 25 채택안
  20일선 / 60일선                    이동평균 눌림
  볼린저 중심선 / 하단                볼린저 눌림
  최근 10일 저가                     최근 지지선
  20일선·볼린저하단 중 가까운 쪽       복합 지지
  최근 20일 고가 돌파                 돌파 확인

■ 지표가 현재가 **위**에 있으면 그 사례는 그 엔진에서 제외한다
  20일선이 현재가 위인데 "20일선까지 눌리면 산다"는 말이 안 된다.
  억지로 즉시 진입으로 바꾸지 않는다 — 그러면 엔진이 뒤섞인다.
  제외한 비율(적용률)을 함께 보고한다.

■ 프로토콜·채택 기준 — 라운드 25b 와 동일 (낮추지 않는다)
  1단계 학습·검증만 보고 후보를 남긴다
        · 학습·검증 신호당 기대값 > 현행(즉시)
        · 검증 체결률 ≥ 50% · 평균 대기 ≤ 10일
  2단계 실전에서 다섯 항목 — 신호당·부트하한·종목 반반·기간 반반·체결률
  ⑥ 고원 조건: 전 항목 통과가 2개 이상이어야 채택
════════════════════════════════════════════════════════════════════════
"""
import io
import json
import os
import sys
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, 'scripts'))
OUT = os.path.join(BASE, '.portfolio', 'entry_engine_r26.json')
LEVELS = os.path.join(BASE, '.portfolio', 'virtual_levels.jsonl')

import exec_sim as X
from entry_engine_r25 import MIN_FILL, MAX_WAIT, boot_lo, half

MIN_PASS = 2


def load_levels():
    out = {}
    if not os.path.exists(LEVELS):
        return out
    with open(LEVELS, encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                d = json.loads(ln)
                out[(d['ticker'], d['date'])] = d
            except Exception:
                pass
    return out


def spec(name, c):
    """
    엔진 이름 → (kind, pct). pct 는 기준가 대비 % (양수 = 그만큼 아래).
    적용 불가면 (None, None) — 그 사례는 이 엔진에서 뺀다.
    """
    lv = c.get('_lv') or {}

    def below(key):
        """지표가 현재가 아래일 때만 쓴다 (위면 눌림 진입이 성립 안 함)."""
        v = lv.get(key)
        if v is None or v >= 0:
            return None
        return -float(v)          # -3.2% → 3.2 (아래로 3.2%)

    def above(key):
        v = lv.get(key)
        if v is None or v <= 0:
            return None
        return float(v)

    if name == '현재가 즉시':
        return 'now', 0.0
    if name == '변동성 1배':
        v = c.get('vol20')
        return ('limit', float(v) * 100.0) if v else (None, None)
    if name == '20일선 눌림':
        return ('limit', below('sma_20')) if below('sma_20') else (None, None)
    if name == '60일선 눌림':
        return ('limit', below('sma_60')) if below('sma_60') else (None, None)
    if name == '볼린저 중심선':
        return ('limit', below('bb_mid')) if below('bb_mid') else (None, None)
    if name == '볼린저 하단':
        return ('limit', below('bb_lower')) if below('bb_lower') else (None, None)
    if name == '최근 10일 저가':
        return ('limit', below('low10')) if below('low10') else (None, None)
    if name == '복합 지지(가까운 쪽)':
        cands = [x for x in (below('sma_20'), below('bb_lower'),
                             below('low10')) if x]
        return ('limit', min(cands)) if cands else (None, None)
    if name == '20일 고가 돌파':
        return ('breakout', above('high20')) if above('high20') else (None, None)
    return None, None


NAMES = ['현재가 즉시', '변동성 1배', '20일선 눌림', '60일선 눌림',
         '볼린저 중심선', '볼린저 하단', '최근 10일 저가',
         '복합 지지(가까운 쪽)', '20일 고가 돌파']


def run(cases, name):
    n_t = n_s = n_o = n_ne = n_na = 0
    tot = 0.0
    bars, rets = [], []
    for c in cases:
        kind, pct = spec(name, c)
        if kind is None or (kind != 'now' and (pct is None or pct <= 0)):
            n_na += 1
            continue
        r = X.simulate_entry(c, c['TP'], c['SP'], kind, pct or 0.0)
        if r['kind'] == 'NODATA':
            n_na += 1
            continue
        if r['kind'] == 'NOENTRY':
            n_ne += 1
            continue
        net = r['ret'] - X.COST
        tot += net
        rets.append(net)
        if r['entry_bar']:
            bars.append(r['entry_bar'])
        if r['kind'] == 'TARGET':
            n_t += 1
        elif r['kind'] == 'STOP':
            n_s += 1
        else:
            n_o += 1
    traded = n_t + n_s + n_o
    n_all = traded + n_ne
    if not n_all:
        return None
    return {'name': name, 'n': n_all, 'traded': traded, 'na': n_na,
            'apply_pct': n_all / max(1, n_all + n_na) * 100,
            'fill_pct': traded / n_all * 100,
            'wait_days': (sum(bars) / len(bars)) if bars else 0.0,
            'ev_signal': tot / n_all,
            'ev_trade': (tot / traded) if traded else None,
            'reach': (n_t / traded * 100) if traded else 0.0,
            'rets': rets}


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    cases, _ = X.load_cases()
    lv = load_levels()
    n_lv = 0
    for c in cases:
        d = lv.get((c['ticker'], c['date']))
        c['_lv'] = d
        if d:
            n_lv += 1
    by = defaultdict(list)
    for c in cases:
        by[c['split']].append(c)
    print(f"매수권({X.BUY}+) {len(cases):,}건 · 지표 레벨 붙은 것 "
          f"{n_lv:,}건 ({n_lv / max(1, len(cases)) * 100:.1f}%)")
    print(' · '.join(f'{k} {len(by[k]):,}' for k in
                     ('train', 'valid', 'blind')) + '\n')

    b_tr, b_va, b_bl = (run(by['train'], '현재가 즉시'),
                        run(by['valid'], '현재가 즉시'),
                        run(by['blind'], '현재가 즉시'))
    print(f"■ 기준선(현재가 즉시)  학습 {b_tr['ev_signal']:+.2f}% · "
          f"검증 {b_va['ev_signal']:+.2f}% · 실전 {b_bl['ev_signal']:+.2f}%\n")

    print('■ 1단계 — 학습·검증만 (실전 미열람)')
    print(f"  {'엔진':18s} │ {'적용률':>6s} {'학습':>8s} {'검증':>8s} "
          f"{'검증체결':>7s} {'대기':>6s} │ 1단계")
    stage1 = []
    rows1 = []
    for nm in NAMES:
        tr, va = run(by['train'], nm), run(by['valid'], nm)
        if not tr or not va:
            continue
        bad = []
        if tr['ev_signal'] <= b_tr['ev_signal']:
            bad.append('학습')
        if va['ev_signal'] <= b_va['ev_signal']:
            bad.append('검증')
        if va['fill_pct'] < MIN_FILL:
            bad.append('체결률')
        if va['wait_days'] > MAX_WAIT:
            bad.append('대기일')
        if not bad and nm != '현재가 즉시':
            stage1.append(nm)
        rows1.append({'name': nm, 'apply': va['apply_pct'],
                      'train': tr['ev_signal'], 'valid': va['ev_signal'],
                      'fill': va['fill_pct'], 'wait': va['wait_days'],
                      'fails': bad})
        print(f"  {nm:18s} │ {va['apply_pct']:>5.1f}% {tr['ev_signal']:>+7.2f}% "
              f"{va['ev_signal']:>+7.2f}% {va['fill_pct']:>6.1f}% "
              f"{va['wait_days']:>5.1f}일 │ "
              f"{'통과' if not bad else '기각 ' + ','.join(bad)}")

    res = {'round': 26, 'levels_attached': n_lv, 'stage1': rows1,
           'passed': [], 'adopted': None}
    if not stage1:
        print('\n1단계 통과 없음 — 실전을 볼 필요도 없다.')
        with open(OUT, 'w', encoding='utf-8') as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        print(f'기록: {OUT}')
        return

    print(f'\n■ 2단계 — 실전 ({len(stage1)}개)')
    bl = by['blind']
    base_lo = boot_lo(b_bl['rets'], b_bl['n'])
    h1 = [c for c in bl if half(c['ticker']) == 0]
    h2 = [c for c in bl if half(c['ticker']) == 1]
    sb = sorted(bl, key=lambda c: c['date'])
    f1, f2 = sb[:len(sb) // 2], sb[len(sb) // 2:]
    bh1, bh2 = run(h1, '현재가 즉시'), run(h2, '현재가 즉시')
    bf1, bf2 = run(f1, '현재가 즉시'), run(f2, '현재가 즉시')
    print(f"  {'엔진':18s} │ {'신호당':>8s} {'부트하한':>8s} "
          f"{'종목반반':>15s} {'기간반반':>15s} {'체결':>6s} │ 판정")
    passed, rows2 = [], []
    for nm in stage1:
        d = run(bl, nm)
        if not d:
            continue
        lo = boot_lo(d['rets'], d['n'])
        a1, a2 = run(h1, nm), run(h2, nm)
        g1, g2 = run(f1, nm), run(f2, nm)
        c1 = d['ev_signal'] > b_bl['ev_signal']
        c2 = lo is not None and base_lo is not None and lo > base_lo
        c3 = bool(a1 and a2 and a1['ev_signal'] > bh1['ev_signal']
                  and a2['ev_signal'] > bh2['ev_signal'])
        c4 = bool(g1 and g2 and g1['ev_signal'] > bf1['ev_signal']
                  and g2['ev_signal'] > bf2['ev_signal'])
        c5 = d['fill_pct'] >= MIN_FILL
        okk = c1 and c2 and c3 and c4 and c5
        if okk:
            passed.append(nm)
        rows2.append({'name': nm, 'ev_signal': d['ev_signal'], 'boot_lo': lo,
                      'fill': d['fill_pct'], 'wait': d['wait_days'],
                      'apply': d['apply_pct'], 'reach': d['reach'],
                      'checks': [c1, c2, c3, c4, c5], 'pass': okk})
        print(f"  {nm:18s} │ {d['ev_signal']:>+7.2f}% {lo:>+7.2f}% "
              f"{(a1 or {}).get('ev_signal', 0):>+6.2f}/"
              f"{(a2 or {}).get('ev_signal', 0):>+6.2f}   "
              f"{(g1 or {}).get('ev_signal', 0):>+6.2f}/"
              f"{(g2 or {}).get('ev_signal', 0):>+6.2f}   "
              f"{d['fill_pct']:>5.1f}% │ "
              f"{'★통과' if okk else '기각 ' + ''.join(
                  m for m, cc in zip('①②③④⑤', [c1, c2, c3, c4, c5]) if not cc)}")

    print('\n' + '=' * 78)
    if len(passed) >= MIN_PASS:
        cand = [r for r in rows2 if r['pass']]
        cand.sort(key=lambda r: (-r['fill'], r['wait']))
        res['adopted'] = cand[0]['name']
        print(f"통과 {len(passed)}개 — 고원 조건 충족 · 채택 **{cand[0]['name']}**")
    elif passed:
        print(f"통과 {len(passed)}개 — 고원 조건({MIN_PASS}개) 미달로 기각")
        print(f"  ({', '.join(passed)} 하나만 통과 — 우연일 수 있다)")
    else:
        print('전 항목 통과 엔진 없음 — 채택하지 않는다.')
        print('현행(라운드 25 채택안 · 변동성 1배)을 유지한다.')
    print('=' * 78)

    res['stage2'] = rows2
    res['passed'] = passed
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(f'기록: {OUT}')


if __name__ == '__main__':
    main()
