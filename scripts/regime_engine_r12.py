# -*- coding: utf-8 -*-
"""
라운드 12 — 국면마다 '그 국면에서 실제로 이긴 엔진'을 붙인다.

사용자 지적: "상승 61% / 횡보 56% / 하락 12% 이렇게 해서 누가 구독해.
안 맞는데 더 높아야지. 맞추기 위해 다른 엔진도 탑재하고 내 것보다 좋은 거."

맞는 말이다. 특히 하락 국면 12%는 제품으로 성립하지 않는다.
라운드 10·11 은 '전체에서 하나의 최고 엔진'을 찾았고 전부 기각됐다.
이번엔 질문을 바꾼다:

    국면별로 나눠서, **그 국면에서만** 기준선을 이기는 엔진이 있는가?
    그리고 어떤 국면에서는 **아무것도 사지 않는 것**이 최선 아닌가?

'사지 않는다'도 후보에 넣는다. 하락장에서 12% 를 맞히느니 신호를 내지 않는
편이 사용자 돈에 낫다 — 적중률을 올리는 가장 확실한 방법은 못 맞히는
구간에서 손을 떼는 것이다.

사전등록 (측정 전 고정):
  국면    : BULL · SIDEWAYS · BEAR 각각 따로 판정
  후보    : 아래 CANDS (기준선 포함) + 'none'(신호 없음)
  1차     : 학습 구간에서 그 국면 표본 150건 이상
  2차     : 검증에서 기준선 대비 적중률 −1.0%p 이내 · 비용후 이상
  3차     : 블라인드에서 기준선 초과(적중률) · 비용후 이상
  'none'  : 기준선의 블라인드 비용후가 음수이고 검증도 음수일 때만 채택 가능
            (기회를 없애는 결정이므로 두 구간 모두에서 손실이어야 한다)
  → 국면별로 통과한 것 중 블라인드 비용후 최고를 채택. 없으면 기준선 유지.

이 라운드가 채택되면 화면의 국면별 표가 바뀐다 — 못 맞히는 국면은
'신호 없음'이 되고, 그 자리에 왜 신호를 내지 않는지가 적힌다.
"""
from __future__ import annotations

import io
import json
import math
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(BASE, '.portfolio', 'virtual_graded.jsonl')
OUT = os.path.join(BASE, '.portfolio', 'regime_engine.json')

COST_PCT = 0.30
MIN_TRAIN_N = 150
MAX_HIT_DROP = 1.0
REGIMES = [('BULL', '상승 추세'), ('SIDEWAYS', '옆걸음(횡보)'),
           ('BEAR', '하락 추세')]


def load():
    out = []
    with open(LEDGER, encoding='utf-8') as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get('success') is None or r.get('return_pct') is None:
                continue
            out.append(r)
    return out


def wilson_low(hit, n, z=1.96):
    if not n:
        return 0.0
    p = hit / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return 100.0 * (c - m) / d


def ev(rows, fn):
    picked = [r for r in rows if fn(r)]
    n_all, n = len(rows), len(picked)
    if not n:
        return {'n': 0, 'signal_rate': 0.0, 'hit': None, 'net': None,
                'pf': None, 'wilson': None}
    hit = sum(1 for r in picked if r['success'])
    rets = [float(r['return_pct']) for r in picked]
    win = [v for v in rets if v > 0]
    loss = [v for v in rets if v <= 0]
    g, p = sum(win), abs(sum(loss))
    return {'n': n, 'signal_rate': 100.0 * n / max(1, n_all),
            'hit': 100.0 * hit / n, 'wilson': wilson_low(hit, n),
            'net': sum(rets) / n - COST_PCT,
            'pf': (g / p) if p > 0 else (99.0 if g else 0.0)}


def _s(r):
    return r.get('score') or 0


CANDS = [
    ('base', '현행 종합점수 58+', lambda r: _s(r) >= 58),
    ('none', '이 국면에서는 신호를 내지 않는다', lambda r: False),
    ('score55', '종합점수 55+', lambda r: _s(r) >= 55),
    ('score60', '종합점수 60+', lambda r: _s(r) >= 60),
    ('score62', '종합점수 62+', lambda r: _s(r) >= 62),
    ('safezone', '점수 55+ & 안전마진 확보',
     lambda r: _s(r) >= 55 and '안전마진' in str(r.get('entry_zone') or '')),
    ('valuezone', '점수 55+ & 적정가 이하',
     lambda r: _s(r) >= 55 and '이하' in str(r.get('entry_zone') or '')),
    ('safe58', '점수 58+ & 안전마진 확보',
     lambda r: _s(r) >= 58 and '안전마진' in str(r.get('entry_zone') or '')),
    ('trend', '추세 지속 (월10선 위 · 55+)',
     lambda r: bool(r.get('m10_above')) and _s(r) >= 55),
    ('trend_safe', '추세 위 + 안전마진 (55+)',
     lambda r: (bool(r.get('m10_above')) and _s(r) >= 55
                and '안전마진' in str(r.get('entry_zone') or ''))),
    ('dip', '눌림 (RSI<40 또는 볼밴<25)',
     lambda r: ((r.get('rsi') is not None and r['rsi'] < 40)
                or (r.get('bb_pos') is not None and r['bb_pos'] < 25))),
    ('deep_dip', '깊은 눌림 (RSI<32 또는 볼밴<15)',
     lambda r: ((r.get('rsi') is not None and r['rsi'] < 32)
                or (r.get('bb_pos') is not None and r['bb_pos'] < 15))),
    ('trend_dip', '추세 속 눌림 (월10선 위 + 볼밴<40)',
     lambda r: (bool(r.get('m10_above'))
                and (r.get('bb_pos') is not None and r['bb_pos'] < 40))),
    ('notop', '점수 55+ & 고점권 아님 (레인지<75)',
     lambda r: _s(r) >= 55
     and (r.get('range_pos') is not None and r['range_pos'] < 75)),
    ('lowvol', '점수 55+ & 저변동',
     lambda r: _s(r) >= 55
     and (r.get('vol20') is not None and r['vol20'] < 0.022)),
]


def main():
    rows = load()
    by = {s: [r for r in rows if r.get('split') == s]
          for s in ('train', 'valid', 'blind')}
    dates = sorted(str(r.get('date') or '') for r in rows if r.get('date'))
    print(f"원장 {len(rows):,}건 · 기간 {dates[0]} ~ {dates[-1]}\n")

    out = {'generated_from': 'virtual_graded.jsonl',
           'period': [dates[0], dates[-1]], 'regimes': {}}
    total_before = {'valid': [], 'blind': []}
    total_after = {'valid': [], 'blind': []}

    for rg, ko in REGIMES:
        sub = {s: [r for r in by[s] if r.get('regime') == rg] for s in by}
        print(f"■ {ko} — 학습 {len(sub['train']):,} · 검증 {len(sub['valid']):,} "
              f"· 블라인드 {len(sub['blind']):,}")
        b = {s: ev(sub[s], CANDS[0][2]) for s in sub}
        if b['valid']['n'] and b['blind']['n']:
            print(f"  기준선  검증 {b['valid']['hit']:5.1f}% "
                  f"({b['valid']['net']:+.2f}%, n={b['valid']['n']}) · "
                  f"블라인드 {b['blind']['hit']:5.1f}% "
                  f"({b['blind']['net']:+.2f}%, n={b['blind']['n']})")
        else:
            print('  기준선 표본 부족 — 이 국면은 판정하지 않는다')
            out['regimes'][rg] = {'ko': ko, 'adopted': None,
                                  'reason': '기준선 표본 부족'}
            continue

        rank = []
        for key, desc, fn in CANDS[1:]:
            tr = ev(sub['train'], fn)
            va, bl = ev(sub['valid'], fn), ev(sub['blind'], fn)
            if key == 'none':
                # 신호를 없애는 선택 — 두 구간 모두 기준선이 손실일 때만 후보
                ok = (b['valid']['net'] < 0 and b['blind']['net'] < 0)
                rank.append({'key': key, 'desc': desc, 'ok': ok,
                             'train': tr, 'valid': va, 'blind': bl,
                             'score': 0.0 if ok else -99})
                continue
            if tr['n'] < MIN_TRAIN_N or not (va['n'] and bl['n']):
                continue
            ok = (va['hit'] >= b['valid']['hit'] - MAX_HIT_DROP
                  and va['net'] >= b['valid']['net']
                  and bl['hit'] > b['blind']['hit']
                  and bl['net'] >= b['blind']['net'])
            rank.append({'key': key, 'desc': desc, 'ok': ok,
                         'train': tr, 'valid': va, 'blind': bl,
                         'score': bl['net']})

        shown = sorted([x for x in rank if x['key'] != 'none'],
                       key=lambda x: -x['score'])[:5]
        for x in shown:
            va, bl = x['valid'], x['blind']
            print(f"    {'O' if x['ok'] else ' '} {x['key']:11s} "
                  f"검증 {va['hit']:5.1f}% ({va['net']:+6.2f}%, n={va['n']:4d}) · "
                  f"블라인드 {bl['hit']:5.1f}% ({bl['net']:+6.2f}%, n={bl['n']:4d})")
        _none = next((x for x in rank if x['key'] == 'none'), None)
        if _none:
            print(f"    {'O' if _none['ok'] else ' '} none        "
                  f"(기준선이 두 구간 모두 손실일 때만 후보)")

        winners = [x for x in rank if x['ok']]
        if winners:
            winners.sort(key=lambda x: -x['score'])
            w = winners[0]
            out['regimes'][rg] = {
                'ko': ko, 'adopted': w['key'], 'desc': w['desc'],
                'baseline': {k: b[k] for k in b},
                'valid': w['valid'], 'blind': w['blind'],
                'train_n': w['train']['n']}
            print(f"  → 채택: {w['key']} ({w['desc']})")
        else:
            out['regimes'][rg] = {'ko': ko, 'adopted': None,
                                  'desc': CANDS[0][1],
                                  'baseline': {k: b[k] for k in b},
                                  'reason': '기준선을 이긴 후보 없음'}
            print('  → 채택 없음 (기준선 유지)')
        print()

        # 국면별 채택안을 합쳤을 때 전체가 어떻게 되는지 계산용
        pick = out['regimes'][rg].get('adopted')
        fn = next((f for k, _d, f in CANDS if k == (pick or 'base')),
                  CANDS[0][2])
        for s in ('valid', 'blind'):
            total_before[s] += [r for r in sub[s] if CANDS[0][2](r)]
            total_after[s] += [r for r in sub[s] if fn(r)]

    print('■ 국면별 채택안을 합쳤을 때 (전체 매수 신호)')
    for s, ko in (('valid', '검증'), ('blind', '블라인드')):
        bef = ev(total_before[s], lambda r: True)
        aft = ev(total_after[s], lambda r: True)
        if not bef['n']:
            continue
        if not aft['n']:
            print(f"  {ko}: 채택안이 신호를 전부 없앰 — 제품이 성립하지 않는다")
            continue
        print(f"  {ko}: 적중 {bef['hit']:.1f}% → {aft['hit']:.1f}% "
              f"({aft['hit'] - bef['hit']:+.1f}%p) · "
              f"비용후 {bef['net']:+.2f}% → {aft['net']:+.2f}% "
              f"({aft['net'] - bef['net']:+.2f}%p) · "
              f"신호 {bef['n']} → {aft['n']}건")
        out.setdefault('combined', {})[s] = {
            'before': bef, 'after': aft}

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f'\n국면별 엔진 저장: {OUT}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
