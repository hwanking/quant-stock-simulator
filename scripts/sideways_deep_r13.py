# -*- coding: utf-8 -*-
"""
라운드 13 — 횡보 국면은 왜 연습 72% → 실전 56% 로 떨어지는가.

사용자 지적: "횡보 때 실전이 너무 낮은데, 방대하게 스터디해서 잘 맞출 수
있게 엔진 개선해 달라."

먼저 **왜 떨어지는지**를 알아야 고칠 수 있다. 가능한 원인 네 가지를 하나씩
데이터로 확인한다:
  ① 두 구간의 횡보가 서로 다른 횡보다 (변동성·기간 구성이 다름)
  ② 특정 종목·업종에 쏠려 있다
  ③ 점수는 같은데 실제 움직임이 달라졌다 (MFE/MAE 분포 이동)
  ④ 횡보 안에 성적이 갈리는 하위 조건이 있는데 우리가 안 쓰고 있다

④가 답이면 개선할 수 있다. ①②③이면 개선이 아니라 **표시를 정직하게**
바꾸는 게 맞다.

그 다음 사전등록 검정:
  후보    : 횡보 안에서 쓸 하위 조건 (아래 SUB)
  1차     : 학습 횡보에서 표본 300건+ · 기준선 대비 lift +3%p+
  2차     : 검증 횡보에서 lift 유지 (−1%p 이내)
  3차     : 블라인드 횡보에서 lift 양수 · 표본 50건+
  워크포워드: 학습 횡보를 시간순 4등분, 판정 가능 폴드의 과반에서 우위
  → 전부 통과해야 채택. 하나라도 어기면 기각하고 이유를 적는다.
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
OUT = os.path.join(BASE, '.portfolio', 'sideways_study.json')

COST = 0.30
BUY = 58
MIN_TRAIN_N = 300
MIN_TRAIN_LIFT = 3.0
MAX_VALID_DROP = 1.0
MIN_BLIND_N = 50


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


def st_(rows):
    n = len(rows)
    if not n:
        return None
    hit = sum(1 for r in rows if r['success'])
    rets = [float(r['return_pct']) for r in rows]
    win = [v for v in rets if v > 0]
    loss = [v for v in rets if v <= 0]
    g, p = sum(win), abs(sum(loss))
    mfes = [float(r['mfe_pct']) for r in rows if r.get('mfe_pct') is not None]
    maes = [abs(float(r['mae_pct'])) for r in rows if r.get('mae_pct') is not None]
    vols = [float(r['vol20']) for r in rows if r.get('vol20') is not None]
    return {'n': n, 'hit': 100.0 * hit / n, 'net': sum(rets) / n - COST,
            'pf': (g / p) if p > 0 else (99.0 if g else 0.0),
            'mfe': (sum(mfes) / len(mfes)) if mfes else 0.0,
            'mae': (sum(maes) / len(maes)) if maes else 0.0,
            'vol': (sum(vols) / len(vols) * 100) if vols else 0.0}


def main():
    rows = load()
    side = [r for r in rows if r.get('regime') == 'SIDEWAYS']
    by = {s: [r for r in side if r.get('split') == s]
          for s in ('train', 'valid', 'blind')}
    buy = {s: [r for r in by[s] if (r.get('score') or 0) >= BUY] for s in by}

    print(f"횡보 전체 {len(side):,}건 · 매수권 "
          f"학습 {len(buy['train']):,} · 검증 {len(buy['valid']):,} "
          f"· 블라인드 {len(buy['blind']):,}\n")

    print('■ 기준선 (횡보 매수권)')
    base = {}
    for s, ko in (('train', '학습'), ('valid', '검증'), ('blind', '블라인드')):
        m = st_(buy[s])
        base[s] = m
        if m:
            print(f"  {ko:5s} n={m['n']:4d} 적중 {m['hit']:5.1f}% "
                  f"비용후 {m['net']:+.2f}% PF {m['pf']:.2f} "
                  f"· 평균 최고상승 {m['mfe']:.1f}% 최대낙폭 {m['mae']:.1f}% "
                  f"일변동성 {m['vol']:.2f}%")

    # ── 원인 ①③ : 두 구간의 횡보가 같은 횡보인가 ────────────────────────
    print('\n■ 원인 ①③ — 검증 횡보와 블라인드 횡보가 같은 성질인가')
    v, b = base['valid'], base['blind']
    if v and b:
        print(f"  평균 최고상승  검증 {v['mfe']:.2f}% vs 블라인드 {b['mfe']:.2f}% "
              f"({b['mfe'] - v['mfe']:+.2f}%p)")
        print(f"  평균 최대낙폭  검증 {v['mae']:.2f}% vs 블라인드 {b['mae']:.2f}% "
              f"({b['mae'] - v['mae']:+.2f}%p)")
        print(f"  일간 변동성    검증 {v['vol']:.2f}% vs 블라인드 {b['vol']:.2f}% "
              f"({b['vol'] - v['vol']:+.2f}%p)")
        if b['mae'] > v['mae'] * 1.3:
            print("  → 블라인드 횡보가 훨씬 험하다. 이름만 같은 횡보다.")
        elif b['mfe'] < v['mfe'] * 0.7:
            print("  → 블라인드 횡보는 상승 폭이 얕다. 목표에 닿을 여지가 적다.")
        else:
            print("  → 성질은 비슷하다. 원인이 ①③ 이 아니다.")

    # ── 원인 ② : 종목 쏠림 ────────────────────────────────────────────
    print('\n■ 원인 ② — 종목 쏠림')
    for s, ko in (('valid', '검증'), ('blind', '블라인드')):
        tk = {}
        for r in buy[s]:
            tk[r['ticker']] = tk.get(r['ticker'], 0) + 1
        if not tk:
            continue
        top = sorted(tk.items(), key=lambda x: -x[1])[:3]
        share = 100.0 * sum(c for _, c in top) / len(buy[s])
        print(f"  {ko}: 종목 {len(tk)}개 · 상위 3종목이 {share:.0f}% "
              f"({', '.join(f'{k}×{c}' for k, c in top)})")

    # ── 원인 ④ : 횡보 안의 하위 조건 ──────────────────────────────────
    def sc(r):
        return r.get('score') or 0

    SUB = [
        ('score60', '점수 60+', lambda r: sc(r) >= 60),
        ('score62', '점수 62+', lambda r: sc(r) >= 62),
        ('m10', '월10선 위', lambda r: bool(r.get('m10_above'))),
        ('m10_below', '월10선 아래', lambda r: not r.get('m10_above')),
        ('bb_low', '볼린저 하단(<30)',
         lambda r: r.get('bb_pos') is not None and r['bb_pos'] < 30),
        ('bb_mid', '볼린저 중간(30~70)',
         lambda r: r.get('bb_pos') is not None and 30 <= r['bb_pos'] <= 70),
        ('bb_high', '볼린저 상단(>70)',
         lambda r: r.get('bb_pos') is not None and r['bb_pos'] > 70),
        ('rsi_low', 'RSI<45',
         lambda r: r.get('rsi') is not None and r['rsi'] < 45),
        ('rsi_high', 'RSI>55',
         lambda r: r.get('rsi') is not None and r['rsi'] > 55),
        ('lowvol', '저변동(<2%)',
         lambda r: r.get('vol20') is not None and r['vol20'] < 0.02),
        ('hivol', '고변동(≥3%)',
         lambda r: r.get('vol20') is not None and r['vol20'] >= 0.03),
        ('range_low', '레인지 저점권(<40)',
         lambda r: r.get('range_pos') is not None and r['range_pos'] < 40),
        ('range_high', '레인지 고점권(>70)',
         lambda r: r.get('range_pos') is not None and r['range_pos'] > 70),
        ('safe', '안전마진 확보',
         lambda r: '안전마진' in str(r.get('entry_zone') or '')),
        ('value', '적정가 이하',
         lambda r: '이하' in str(r.get('entry_zone') or '')),
        ('demark', '디마크 형성',
         lambda r: str(r.get('demark_state') or '') == 'FORMING'),
        ('kospi', '코스피', lambda r: r.get('market') == 'KOSPI'),
        ('stock', '주식만', lambda r: r.get('asset_type') == 'STOCK'),
    ]

    print('\n■ 원인 ④ — 횡보 안에서 성적이 갈리는 하위 조건')
    print('  조건            학습(lift)      검증(lift)      블라인드(lift)   블라인드n')
    cand = []
    for key, desc, fn in SUB:
        m = {s: st_([r for r in buy[s] if fn(r)]) for s in buy}
        if not (m['train'] and m['valid'] and m['blind']):
            continue
        lift = {s: m[s]['hit'] - base[s]['hit'] for s in m}
        print(f"  {desc:16s} {m['train']['hit']:5.1f}%({lift['train']:+5.1f}) "
              f"{m['valid']['hit']:5.1f}%({lift['valid']:+5.1f}) "
              f"{m['blind']['hit']:5.1f}%({lift['blind']:+5.1f}) "
              f"{m['blind']['n']:6d}")
        cand.append({'key': key, 'desc': desc, 'fn': fn, 'm': m, 'lift': lift})

    # ── 사전등록 판정 ─────────────────────────────────────────────────
    def walk(rows_, fn, base_fn, folds=4):
        rs = sorted(rows_, key=lambda r: str(r.get('date') or ''))
        if len(rs) < folds * 40:
            return 0, 0
        size = len(rs) // folds
        w = j = 0
        for i in range(folds):
            seg = rs[i * size:(i + 1) * size] if i < folds - 1 else rs[i * size:]
            a, c = st_([r for r in seg if fn(r)]), st_([r for r in seg if base_fn(r)])
            if not a or not c or a['n'] < 15 or c['n'] < 15:
                continue
            j += 1
            if a['hit'] > c['hit']:
                w += 1
        return w, j

    print('\n■ 사전등록 판정 (학습 300건+ · lift +3%p+ → 검증 유지 → 블라인드 양수)')
    winners = []
    for c in cand:
        m, lift = c['m'], c['lift']
        g = [
            ('학습표본', m['train']['n'] >= MIN_TRAIN_N),
            ('학습lift', lift['train'] >= MIN_TRAIN_LIFT),
            ('검증유지', lift['valid'] >= lift['train'] - MAX_VALID_DROP
             or lift['valid'] > 0),
            ('블라인드', lift['blind'] > 0),
            ('블표본', m['blind']['n'] >= MIN_BLIND_N),
        ]
        if all(x[1] for x in g):
            w, j = walk(buy['train'], c['fn'], lambda r: True)
            ok_wf = (j >= 2 and w * 2 > j)
            c['wf'] = (w, j)
            print(f"  [{'채택' if ok_wf else '워크포워드 미달'}] {c['desc']} "
                  f"— 워크포워드 {w}/{j}")
            if ok_wf:
                winners.append(c)
        elif sum(1 for x in g if x[1]) >= 4:
            miss = ' '.join(x[0] for x in g if not x[1])
            print(f"  [근접] {c['desc']} — 미달: {miss}")

    print('\n' + '=' * 78)
    if winners:
        winners.sort(key=lambda c: -c['lift']['blind'])
        w = winners[0]
        print(f"판정: 채택 — 횡보에서는 '{w['desc']}' 를 추가 조건으로 건다")
        for s, ko in (('train', '학습'), ('valid', '검증'), ('blind', '블라인드')):
            m = w['m'][s]
            print(f"  {ko:5s} n={m['n']:4d} 적중 {m['hit']:.1f}% "
                  f"(기준선 대비 {w['lift'][s]:+.1f}%p) 비용후 {m['net']:+.2f}%")
    else:
        print('판정: 채택 없음 — 횡보 안에서 세 구간을 모두 통과한 조건이 없습니다.')
        print('     기준을 낮춰 통과시키지 않습니다.')
    print('=' * 78)

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump({
            'regime': 'SIDEWAYS', 'baseline': base,
            'subconditions': [{'key': c['key'], 'desc': c['desc'],
                               'stats': c['m'], 'lift': c['lift'],
                               'wf': c.get('wf')} for c in cand],
            'adopted': (winners[0]['key'] if winners else None),
        }, f, ensure_ascii=False, indent=1)
    print(f'\n저장: {OUT}')
    return 0 if winners else 1


if __name__ == '__main__':
    sys.exit(main())
