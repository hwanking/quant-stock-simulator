# -*- coding: utf-8 -*-
"""
라운드 11 — 대규모 엔진 대결 (과거 장세 포함 · 파라미터 훑기 · 실제 교체 판정).

사용자 지시: "엔진 모델 판단이 나오는 건 좋은데 맞춰야지 그게 제일 중요하지.
내 엔진보다 다른 게 잘 맞으면 바꿔. 근데 많은 스터디를 해서 비교해 주고."

라운드 10 과 달라진 점:
  ① **데이터**: 2015년부터 수집 — 2018 하락장 · 2020 팬데믹 급락과 반등 ·
     2021 유동성 장세 · 2022 긴축 하락장이 학습 구간에 들어왔다.
  ② **후보 수**: 7개 → 파라미터를 훑어 수십 개. 문턱 하나 차이로 결론이
     뒤집히는지 봐야 '그 엔진이 좋다'고 말할 수 있다.
  ③ **검증 방식**: 한 번의 분할이 아니라 **워크포워드** 를 함께 본다.
     학습 구간을 시간순으로 4등분해, 앞을 보고 뒤를 맞히는 것을 4번 반복한다.
     한 구간에서만 좋은 규칙은 여기서 걸러진다.
  ④ **교체 판정**: 조건을 만족하면 **실제로 바꾼다.** 지금까지는 전부
     기각이었지만, 기각이 목적이 아니다 — 기준을 통과하면 채택한다.

사전등록 (측정 전 고정 — 결과를 보고 고치지 않는다):
  1차 (워크포워드) : 4개 폴드 중 **3개 이상**에서 기준선보다 적중률이 높을 것
  2차 (검증)       : 적중률 기준선 −1.0%p 이내 · 비용후 기준선 이상
  3차 (블라인드)   : 적중률 기준선 **초과** · 비용후 기준선 이상
  공통             : 신호율 3% 이상 · 매수권 표본 100건 이상
  → 세 관문을 모두 통과한 것 중 **블라인드 비용후가 가장 높은 것**을 채택한다.
  → 하나도 없으면 기준선을 유지한다. 기준을 낮춰 통과시키지 않는다.
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
OUT = os.path.join(BASE, '.portfolio', 'engine_bakeoff.json')

COST_PCT = 0.30
MIN_SIGNAL_RATE = 3.0
MIN_N = 100
MAX_HIT_DROP_VALID = 1.0
N_FOLDS = 4
MIN_FOLDS_WIN = 3


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
                'pf': None, 'mae': None, 'wilson': None}
    hit = sum(1 for r in picked if r['success'])
    rets = [float(r['return_pct']) for r in picked]
    win = [v for v in rets if v > 0]
    loss = [v for v in rets if v <= 0]
    g, p = sum(win), abs(sum(loss))
    maes = [abs(float(r['mae_pct'])) for r in picked
            if r.get('mae_pct') is not None]
    return {'n': n, 'signal_rate': 100.0 * n / max(1, n_all),
            'hit': 100.0 * hit / n, 'wilson': wilson_low(hit, n),
            'net': sum(rets) / n - COST_PCT,
            'pf': (g / p) if p > 0 else (99.0 if g else 0.0),
            'mae': (sum(maes) / len(maes)) if maes else 0.0}


# ── 후보 공간 — 파라미터까지 코드에 미리 적는다 ───────────────────────────
def build_candidates():
    C = {}

    def add(key, desc, fn):
        C[key] = (desc, fn)

    add('base', '현행 종합점수 58+', lambda r: (r.get('score') or 0) >= 58)

    # 점수 문턱 훑기 — 문턱 하나로 결론이 바뀌는지
    for thr in (50, 54, 56, 60, 62, 65):
        add(f'score{thr}', f'종합점수 {thr}+',
            lambda r, t=thr: (r.get('score') or 0) >= t)

    # 시계열 모멘텀 — 추세 필터 + 점수 문턱 조합
    for thr in (45, 50, 55, 58):
        add(f'tsmom{thr}', f'추세 지속 (월10선 위 · 점수 {thr}+)',
            lambda r, t=thr: bool(r.get('m10_above')) and (r.get('score') or 0) >= t)

    # 평균회귀 — RSI·볼밴 문턱 훑기
    for rsi_t, bb_t in ((30, 15), (35, 20), (40, 25), (45, 30)):
        add(f'meanrev{rsi_t}',
            f'눌림 되돌림 (RSI<{rsi_t} 또는 볼밴<{bb_t})',
            lambda r, a=rsi_t, b=bb_t: (
                (r.get('rsi') is not None and r['rsi'] < a)
                or (r.get('bb_pos') is not None and r['bb_pos'] < b)))

    # 추세 + 눌림 (둘 다) — 상승 추세 안의 조정 매수
    for thr in (45, 50):
        add(f'trenddip{thr}', f'추세 속 눌림 (월10선 위 + 볼밴<40 · 점수 {thr}+)',
            lambda r, t=thr: (bool(r.get('m10_above'))
                              and (r.get('bb_pos') is not None and r['bb_pos'] < 40)
                              and (r.get('score') or 0) >= t))

    # 변동성 조건 — 조용한 종목 / 급한 종목
    add('lowvol', '저변동 + 점수 55+',
        lambda r: (r.get('vol20') is not None and r['vol20'] < 0.020)
        and (r.get('score') or 0) >= 55)
    add('hivol', '고변동 + 점수 55+',
        lambda r: (r.get('vol20') is not None and r['vol20'] >= 0.030)
        and (r.get('score') or 0) >= 55)

    # 진입 구역 — 적정가 대비 위치
    add('valuezone', '점수 55+ & 적정가 이하',
        lambda r: (r.get('score') or 0) >= 55
        and '이하' in str(r.get('entry_zone') or ''))
    add('safezone', '점수 55+ & 안전마진 확보',
        lambda r: (r.get('score') or 0) >= 55
        and '안전마진' in str(r.get('entry_zone') or ''))

    # 국면 조건부 — 장세마다 다른 원리
    def regime_fn(r, bull_t=50, side_bb=30, bear_rsi=35):
        g = r.get('regime')
        sc = r.get('score') or 0
        if g == 'BULL':
            return bool(r.get('m10_above')) and sc >= bull_t
        if g == 'SIDEWAYS':
            return (r.get('bb_pos') is not None and r['bb_pos'] < side_bb) and sc >= 45
        if g == 'BEAR':
            return (r.get('rsi') is not None and r['rsi'] < bear_rsi)
        return sc >= 58
    add('regime', '국면 조건부 (상승=추세 / 횡보=눌림 / 하락=과매도)', regime_fn)

    def regime_strict(r):
        """하락 국면에서는 아예 사지 않는 변형."""
        g = r.get('regime')
        if g == 'BEAR':
            return False
        return regime_fn(r)
    add('regime_nobear', '국면 조건부 + 하락장 매수 안 함', regime_strict)

    # 디마크 상태 결합
    add('demark', '디마크 형성 + 점수 55+',
        lambda r: str(r.get('demark_state') or '') == 'FORMING'
        and (r.get('score') or 0) >= 55)

    # 레인지 위치 — 고점권 회피
    add('notop', '점수 55+ & 52주 고점권 아님 (레인지<80)',
        lambda r: (r.get('score') or 0) >= 55
        and (r.get('range_pos') is not None and r['range_pos'] < 80))
    return C


def walk_forward(train_rows, fn, base_fn, folds=N_FOLDS):
    """
    학습 구간을 시간순 4등분해 앞→뒤로 반복 검정한다.
    한 시기에서만 좋은 규칙을 걸러내는 것이 목적이다.
    """
    rows = sorted(train_rows, key=lambda r: str(r.get('date') or ''))
    if len(rows) < folds * 50:
        return 0, folds
    size = len(rows) // folds
    wins = 0
    for i in range(folds):
        seg = rows[i * size:(i + 1) * size] if i < folds - 1 else rows[i * size:]
        a, b = ev(seg, fn), ev(seg, base_fn)
        if a['n'] >= 20 and b['n'] >= 20 and a['hit'] is not None \
                and b['hit'] is not None and a['hit'] > b['hit']:
            wins += 1
    return wins, folds


def main():
    rows = load()
    by = {s: [r for r in rows if r.get('split') == s]
          for s in ('train', 'valid', 'blind')}
    dates = sorted(str(r.get('date') or '') for r in rows if r.get('date'))
    print(f"원장 {len(rows):,}건 · 기간 {dates[0]} ~ {dates[-1]}")
    print(f"학습 {len(by['train']):,} · 검증 {len(by['valid']):,} · "
          f"블라인드 {len(by['blind']):,}")
    yrs = {}
    for r in rows:
        y = str(r.get('date') or '')[:4]
        if y:
            yrs[y] = yrs.get(y, 0) + 1
    print('연도별:', ' '.join(f"{k}:{v}" for k, v in sorted(yrs.items())))

    C = build_candidates()
    base_desc, base_fn = C['base']
    b_tr, b_va, b_bl = (ev(by[s], base_fn) for s in ('train', 'valid', 'blind'))
    print(f"\n■ 기준선 ({base_desc})")
    for ko, m in (('학습', b_tr), ('검증', b_va), ('블라인드', b_bl)):
        print(f"  {ko:5s} n={m['n']:5d} ({m['signal_rate']:5.1f}%) "
              f"적중 {m['hit']:5.1f}% 비용후 {m['net']:+6.2f}% PF {m['pf']:.2f}")

    print(f"\n■ 후보 {len(C) - 1}개 평가 (워크포워드 {N_FOLDS}폴드 포함)")
    results = []
    for key, (desc, fn) in C.items():
        if key == 'base':
            continue
        tr, va, bl = (ev(by[s], fn) for s in ('train', 'valid', 'blind'))
        if not (va['n'] and bl['n']):
            continue
        wins, folds = walk_forward(by['train'], fn, base_fn)
        results.append({'key': key, 'desc': desc, 'wf_wins': wins,
                        'train': tr, 'valid': va, 'blind': bl})

    results.sort(key=lambda x: -(x['blind']['net'] or -99))
    print('  (블라인드 비용후 상위 12개)')
    print('  키            WF   검증적중 검증비용후  실전적중 실전비용후  신호율   n')
    for x in results[:12]:
        va, bl = x['valid'], x['blind']
        print(f"  {x['key']:13s} {x['wf_wins']}/{N_FOLDS}  "
              f"{va['hit']:6.1f}% {va['net']:+8.2f}%  "
              f"{bl['hit']:6.1f}% {bl['net']:+8.2f}%  "
              f"{bl['signal_rate']:5.1f}% {bl['n']:5d}")

    print('\n■ 3관문 판정')
    passed = []
    for x in results:
        va, bl = x['valid'], x['blind']
        gates = [
            ('워크포워드', x['wf_wins'] >= MIN_FOLDS_WIN),
            ('검증 적중', va['hit'] >= b_va['hit'] - MAX_HIT_DROP_VALID),
            ('검증 비용후', va['net'] >= b_va['net']),
            ('실전 적중', bl['hit'] > b_bl['hit']),
            ('실전 비용후', bl['net'] >= b_bl['net']),
            ('신호율', bl['signal_rate'] >= MIN_SIGNAL_RATE),
            ('표본', bl['n'] >= MIN_N),
        ]
        if all(g[1] for g in gates):
            passed.append(x)
            print(f"  [통과] {x['key']:13s} — {x['desc']}")
        elif sum(1 for g in gates if g[1]) >= 5:
            fail = ' '.join(g[0] for g in gates if not g[1])
            print(f"  [근접] {x['key']:13s} 미달: {fail}")

    print('\n' + '=' * 82)
    adopted = None
    if passed:
        passed.sort(key=lambda x: -x['blind']['net'])
        adopted = passed[0]
        print(f"판정: 교체 — {adopted['key']} ({adopted['desc']})")
        for ko, m in (('학습', adopted['train']), ('검증', adopted['valid']),
                      ('블라인드', adopted['blind'])):
            print(f"  {ko:5s} n={m['n']:5d} 적중 {m['hit']:5.1f}% "
                  f"비용후 {m['net']:+.2f}% PF {m['pf']:.2f} MAE {m['mae']:.2f}%")
        print(f"  워크포워드 {adopted['wf_wins']}/{N_FOLDS} 폴드에서 기준선 우위")
        print(f"  기준선 대비 — 검증 적중 "
              f"{adopted['valid']['hit'] - b_va['hit']:+.1f}%p · "
              f"실전 적중 {adopted['blind']['hit'] - b_bl['hit']:+.1f}%p · "
              f"실전 비용후 {adopted['blind']['net'] - b_bl['net']:+.2f}%p")
    else:
        print('판정: 교체 없음 — 3관문을 모두 통과한 후보가 없습니다. 기준선 유지.')
    print('=' * 82)

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump({
            'generated_from': 'virtual_graded.jsonl',
            'period': [dates[0], dates[-1]], 'years': yrs,
            'n_candidates': len(C) - 1,
            'baseline': {'key': 'base', 'desc': base_desc,
                         'train': b_tr, 'valid': b_va, 'blind': b_bl},
            'engines': {x['key']: {'desc': x['desc'], 'wf_wins': x['wf_wins'],
                                   'train': x['train'], 'valid': x['valid'],
                                   'blind': x['blind']} for x in results},
            'adopted': (adopted['key'] if adopted else None),
            'adopted_desc': (adopted['desc'] if adopted else None),
            'criteria': {'walk_forward_folds': N_FOLDS,
                         'min_folds_win': MIN_FOLDS_WIN,
                         'max_hit_drop_valid': MAX_HIT_DROP_VALID,
                         'min_signal_rate': MIN_SIGNAL_RATE, 'min_n': MIN_N},
        }, f, ensure_ascii=False, indent=1)
    print(f'\n결과 저장: {OUT}')
    return 0 if adopted else 1


if __name__ == '__main__':
    sys.exit(main())
