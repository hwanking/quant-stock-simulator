# -*- coding: utf-8 -*-
"""
라운드 10 — 기존 엔진 말고 다른 알고리즘이 더 잘 맞히는가 (후보 엔진 대결).

사용자 지적: "판단이 이렇게 안 맞는데 맞아? 다른 엔진 혹은 알고리즘으로
높여야 하는 거 아냐. 하락추세만 맞출 게 아니라 예전 데이터들을 학습해야지."

맞는 지적이다. 지금까지는 자기유사·DeMARK·기술지표 조합 하나만 반복했다.
이 스크립트는 **같은 원장·같은 분할**에서 서로 다른 원리의 엔진을 나란히
세우고 실측으로 비교한다.

후보 엔진 (원장에 이미 있는 값만으로 만들 수 있는 것 — 새 데이터 수집 없음):
  base      현행 종합점수 (기준선)
  tsmom     시계열 모멘텀   — 월10선 위 = 추세 지속에 베팅
  meanrev   평균회귀        — RSI 과매도·볼린저 하단 = 되돌림에 베팅
  volbreak  변동성 돌파     — 저변동 + 레인지 상단 = 압축 후 확장에 베팅
  regime    국면 조건부     — 국면마다 다른 엔진을 쓴다 (앙상블의 원형)
  logistic  로지스틱 회귀   — 여러 특징을 가중합해 확률로 (학습 구간에서만 적합)
  ensemble  투표 앙상블     — 위 엔진들의 다수결

각 엔진은 '이 사례를 사겠는가(1)/말겠는가(0)' 만 답한다. 점수를 새로 만들지
않는다 — 비교의 축을 하나로 두기 위해서다.

사전등록 (측정 전 고정):
  선정 기준 : 학습에서 적합 → 검증에서 확인 → 블라인드는 마지막 1회 공개
  채택 조건 : 기준선(base) 대비 **검증과 블라인드 양쪽에서**
              ① 적중률이 낮아지지 않고 (-1.0%p 이내)
              ② 비용 차감 후 기대값이 개선되고 (+0.10%p 이상)
              ③ 신호율이 전체의 3% 이상 (기회를 다 없애면 제품이 아니다)
  실패 시   : 채택하지 않고 기준선을 유지한다.
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
MAX_HIT_DROP = 1.0
MIN_NET_GAIN = 0.10


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


# ── 후보 엔진 — 각자 '살까 말까' 만 답한다 ────────────────────────────────
def e_base(r):
    return (r.get('score') or 0) >= 58


def e_tsmom(r):
    """시계열 모멘텀 — 추세가 살아 있을 때만 산다."""
    return bool(r.get('m10_above')) and (r.get('score') or 0) >= 50


def e_meanrev(r):
    """평균회귀 — 눌린 자리에서 되돌림을 산다."""
    rsi, bb = r.get('rsi'), r.get('bb_pos')
    return ((rsi is not None and rsi < 40) or (bb is not None and bb < 25)) \
        and (r.get('score') or 0) >= 45


def e_volbreak(r):
    """변동성 돌파 — 조용하던 종목이 레인지 상단에 붙었을 때."""
    v, rp = r.get('vol20'), r.get('range_pos')
    return (v is not None and v < 0.020) and (rp is not None and rp >= 70) \
        and (r.get('score') or 0) >= 50


def e_regime(r):
    """
    국면 조건부 — 장세마다 다른 원리를 쓴다.
    상승엔 추세를, 횡보엔 평균회귀를, 하락엔 과매도 반등을.
    """
    g = r.get('regime')
    if g == 'BULL':
        return e_tsmom(r)
    if g == 'SIDEWAYS':
        return e_meanrev(r)
    if g == 'BEAR':
        rsi, bb = r.get('rsi'), r.get('bb_pos')
        return (rsi is not None and rsi < 35) or (bb is not None and bb < 20)
    return e_base(r)


def _feat(r):
    """로지스틱에 넣을 특징 — 원장에 있는 값만."""
    return [
        (float(r.get('score') or 50) - 50.0) / 10.0,
        1.0 if r.get('m10_above') else 0.0,
        (float(r.get('rsi') or 50) - 50.0) / 20.0,
        (float(r.get('bb_pos') or 50) - 50.0) / 30.0,
        (float(r.get('range_pos') or 50) - 50.0) / 30.0,
        (float(r.get('vol20') or 0.02) - 0.02) / 0.02,
        1.0 if r.get('regime') == 'BULL' else 0.0,
        1.0 if r.get('regime') == 'BEAR' else 0.0,
    ]


def fit_logistic(rows, epochs=300, lr=0.08):
    """
    작은 로지스틱 회귀 — 외부 라이브러리 없이 경사하강.
    ⚠️ 학습 구간에서만 적합한다. 검증·블라인드는 절대 보지 않는다.
    """
    d = len(_feat(rows[0]))
    w = [0.0] * d
    b = 0.0
    n = len(rows)
    X = [_feat(r) for r in rows]
    y = [1.0 if r['success'] else 0.0 for r in rows]
    for _ in range(epochs):
        gw = [0.0] * d
        gb = 0.0
        for xi, yi in zip(X, y):
            z = b + sum(wj * xj for wj, xj in zip(w, xi))
            p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
            e = p - yi
            for j in range(d):
                gw[j] += e * xi[j]
            gb += e
        for j in range(d):
            w[j] -= lr * gw[j] / n
        b -= lr * gb / n
    return w, b


def make_logistic(w, b, thr=0.58):
    def f(r):
        z = b + sum(wj * xj for wj, xj in zip(w, _feat(r)))
        p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
        return p >= thr
    return f


def make_ensemble(members):
    def f(r):
        votes = sum(1 for m in members if m(r))
        return votes >= 2          # 둘 이상이 동의해야 산다
    return f


def evaluate(rows, fn):
    picked = [r for r in rows if fn(r)]
    n_all = len(rows)
    n = len(picked)
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
    return {
        'n': n, 'signal_rate': 100.0 * n / max(1, n_all),
        'hit': 100.0 * hit / n, 'wilson': wilson_low(hit, n),
        'net': sum(rets) / n - COST_PCT,
        'pf': (g / p) if p > 0 else (99.0 if g else 0.0),
        'mae': (sum(maes) / len(maes)) if maes else 0.0,
    }


def row(name, m):
    if not m or not m['n']:
        return f"  {name:10s} 신호 없음"
    return (f"  {name:10s} n={m['n']:5d} ({m['signal_rate']:5.1f}%) "
            f"적중 {m['hit']:5.1f}% (하한 {m['wilson']:4.1f}) "
            f"비용후 {m['net']:+6.2f}% PF {m['pf']:5.2f} MAE {m['mae']:5.2f}%")


def main():
    rows = load()
    by = {s: [r for r in rows if r.get('split') == s]
          for s in ('train', 'valid', 'blind')}
    print(f"원장 {len(rows):,}건 — 학습 {len(by['train']):,} · "
          f"검증 {len(by['valid']):,} · 블라인드 {len(by['blind']):,}\n")

    print('■ 로지스틱 회귀 적합 (학습 구간에서만 — 검증·블라인드는 보지 않는다)')
    w, b = fit_logistic(by['train'])
    print('  가중치:', ' '.join(f"{x:+.2f}" for x in w), f"· 절편 {b:+.2f}")
    names = ['점수', '월10선위', 'RSI', '볼밴위치', '레인지위치', '변동성',
             '상승장', '하락장']
    top = sorted(zip(names, w), key=lambda t: -abs(t[1]))[:3]
    print('  가장 크게 작용한 특징:',
          ' · '.join(f"{n}({v:+.2f})" for n, v in top))
    e_logi = make_logistic(w, b)

    ENGINES = [
        ('base', e_base, '현행 종합점수 58+'),
        ('tsmom', e_tsmom, '시계열 모멘텀 (추세 지속)'),
        ('meanrev', e_meanrev, '평균회귀 (눌림 되돌림)'),
        ('volbreak', e_volbreak, '변동성 돌파 (압축 후 확장)'),
        ('regime', e_regime, '국면 조건부 (장세별 다른 원리)'),
        ('logistic', e_logi, '로지스틱 회귀 (특징 가중합)'),
    ]
    ENGINES.append(
        ('ensemble', make_ensemble([e_tsmom, e_meanrev, e_regime, e_logi]),
         '투표 앙상블 (둘 이상 동의)'))

    res = {}
    for split, ko in (('train', '학습'), ('valid', '검증'), ('blind', '블라인드')):
        print(f'\n■ {ko} 구간')
        for key, fn, _desc in ENGINES:
            m = evaluate(by[split], fn)
            res.setdefault(key, {})[split] = m
            print(row(key, m))

    print('\n■ 채택 판정 — 검증·블라인드 양쪽에서 기준선을 이겨야 한다')
    base_v, base_b = res['base']['valid'], res['base']['blind']
    print(f"  기준선: 검증 적중 {base_v['hit']:.1f}% 비용후 {base_v['net']:+.2f}% | "
          f"블라인드 적중 {base_b['hit']:.1f}% 비용후 {base_b['net']:+.2f}%")
    winners = []
    for key, _fn, desc in ENGINES:
        if key == 'base':
            continue
        v, bl = res[key]['valid'], res[key]['blind']
        if not (v['n'] and bl['n']):
            print(f"  [탈락] {key:10s} 표본 부족")
            continue
        cond = [
            v['hit'] >= base_v['hit'] - MAX_HIT_DROP,
            bl['hit'] >= base_b['hit'] - MAX_HIT_DROP,
            v['net'] >= base_v['net'] + MIN_NET_GAIN,
            bl['net'] >= base_b['net'] + MIN_NET_GAIN,
            v['signal_rate'] >= MIN_SIGNAL_RATE,
        ]
        ok = all(cond)
        tags = ''.join('O' if c else 'X' for c in cond)
        print(f"  [{'채택' if ok else '탈락'}] {key:10s} {tags}  "
              f"검증 {v['hit']:.1f}%/{v['net']:+.2f}% · "
              f"블라인드 {bl['hit']:.1f}%/{bl['net']:+.2f}% — {desc}")
        if ok:
            winners.append((key, desc, v, bl))

    print('\n' + '=' * 78)
    if winners:
        print(f'판정: 채택 후보 {len(winners)}개')
        for k, d, v, bl in winners:
            print(f"  · {k} — {d}")
            print(f"    검증 적중 {v['hit']:.1f}% 비용후 {v['net']:+.2f}% · "
                  f"블라인드 적중 {bl['hit']:.1f}% 비용후 {bl['net']:+.2f}%")
    else:
        print('판정: 채택 없음 — 검증·블라인드 양쪽에서 기준선을 이긴 엔진이 '
              '없습니다. 현행 엔진을 유지합니다.')
    print('=' * 78)

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump({
            'generated_from': 'virtual_graded.jsonl',
            'engines': {k: {'desc': d, **{s: res[k][s] for s in by}}
                        for k, _f, d in ENGINES},
            'logistic_weights': dict(zip(names, [round(x, 3) for x in w])),
            'logistic_bias': round(b, 3),
            'adopted': [w_[0] for w_ in winners],
            'criteria': {'max_hit_drop': MAX_HIT_DROP,
                         'min_net_gain': MIN_NET_GAIN,
                         'min_signal_rate': MIN_SIGNAL_RATE},
        }, f, ensure_ascii=False, indent=1)
    print(f'\n대결 결과 저장: {OUT}')
    return 0 if winners else 1


if __name__ == '__main__':
    sys.exit(main())
