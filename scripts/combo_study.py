# -*- coding: utf-8 -*-
"""
퀀트 조합 대결 — 현재 조합 vs 대표 퀀트 스타일들 (1,950건 원장, 시간 분할).

규율:
  · 후보 조합은 문헌에서 사전 정의한다 (원장을 보고 만들어 붙이지 않는다)
  · 승자 선정은 학습+검증 구간만 사용, 블라인드는 승자 확정 후 보고만
  · 지표: 적중률·평균수익·비용후·PF·표본수·신호 발생률 — 적중률만 보지 않는다
"""
import json
import os
import sys

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
PROJ = r"C:\Users\HWAN-9800X3D\.gemini\antigravity\scratch\quant_backtest_claude"

G = []
with open(os.path.join(PROJ, ".portfolio", "virtual_graded.jsonl"), encoding="utf-8") as f:
    for line in f:
        r = json.loads(line)
        if r.get('outcome') in ('TARGET', 'STOP'):
            G.append(r)

print(f"판정 완료 {len(G)}건 (미결 제외)")


def num(r, k, d=None):
    v = r.get(k)
    return float(v) if v is not None else d


# ── 후보 조합 (사전 정의 — 각각 대표 퀀트 스타일) ─────────────────────────────
COMBOS = {
    "A. 현재 시스템 매수권 (점수≥60)":
        lambda r: r['score'] >= 60,
    "B. 추세추종 CTA형 (월10↑·52주상단)":
        lambda r: r.get('m10_above') and (num(r, 'range_pos', 0) or 0) > 50,
    "C. 가치+추세 (진입후보·월10↑)":
        lambda r: ('초과' not in str(r.get('entry_zone') or '')
                   and (num(r, 'net_expected', -1) or -1) > 0 and r.get('m10_above')),
    "D. 52주 고점 모멘텀 (George–Hwang)":
        lambda r: (num(r, 'range_pos', 0) or 0) > 70 and r.get('m10_above'),
    "E. 점수+추세+국면 (58↑·월10↑·비하락)":
        lambda r: r['score'] >= 58 and r.get('m10_above') and r.get('regime') != 'BEAR',
    "F. 역발상 (RSI<35·볼린저 하단)":
        lambda r: (num(r, 'rsi', 99) or 99) < 35 and (num(r, 'bb_pos', 99) or 99) < 30,
    "G. 승률중립+추세 (관찰승률 45~55·월10↑)":
        lambda r: 45 <= (num(r, 'win_rate', -1) or -1) <= 55 and r.get('m10_above'),
}


def split_of(d):
    d = str(d)
    return 'blind' if d >= '2026-02-01' else ('valid' if d >= '2025-07-01' else 'train')


def metrics(sub, total_n):
    if not sub:
        return None
    hit = sum(1 for r in sub if r['success'])
    rets = [r['return_pct'] for r in sub]
    wins = sum(x for x in rets if x > 0)
    losses = -sum(x for x in rets if x < 0)
    return {
        'n': len(sub), 'hit_rate': hit / len(sub) * 100,
        'avg': float(np.mean(rets)), 'after_cost': float(np.mean(rets)) - 0.55,
        'pf': (wins / losses) if losses > 0 else float('inf'),
        'signal_rate': len(sub) / total_n * 100,
    }


print()
print("=" * 100)
print(f"{'조합':<38}{'구간':<7}{'n':>5}{'적중률':>8}{'평균':>8}{'비용후':>8}{'PF':>7}{'신호율':>8}")
print("=" * 100)
results = {}
for name, fn in COMBOS.items():
    results[name] = {}
    for sp in ('train', 'valid'):
        pool = [r for r in G if split_of(r['date']) == sp]
        m = metrics([r for r in pool if fn(r)], len(pool))
        results[name][sp] = m
        if m:
            print(f"{name:<38}{sp:<7}{m['n']:>5}{m['hit_rate']:>7.1f}%{m['avg']:>+7.2f}%"
                  f"{m['after_cost']:>+7.2f}%{m['pf']:>7.2f}{m['signal_rate']:>7.1f}%")
        else:
            print(f"{name:<38}{sp:<7}{'0':>5}")
    print("-" * 100)

# ── 승자 선정 (학습+검증 — 블라인드 미사용) ─────────────────────────────────
# 기준: 검증 비용후 기대값 양수 & 검증 n≥30, 그중 검증 적중률 최고.
# 학습·검증 괴리가 크면(>15%p) 과적합 의심으로 제외.
print()
print("=" * 100)
print("승자 선정 (검증 n≥30 · 비용후>0 · 학습-검증 괴리 15%p 이내 → 검증 적중률 최고)")
print("=" * 100)
cands = []
for name, sp in results.items():
    tr, va = sp.get('train'), sp.get('valid')
    if not tr or not va or va['n'] < 30:
        print(f"  제외: {name} — 검증 표본 부족")
        continue
    if va['after_cost'] <= 0:
        print(f"  제외: {name} — 검증 비용후 {va['after_cost']:+.2f}% (음수)")
        continue
    if abs(tr['hit_rate'] - va['hit_rate']) > 15:
        print(f"  제외: {name} — 학습/검증 괴리 {abs(tr['hit_rate']-va['hit_rate']):.1f}%p")
        continue
    cands.append((name, va))
    print(f"  후보: {name} — 검증 {va['hit_rate']:.1f}% · 비용후 {va['after_cost']:+.2f}% · n={va['n']}")

if cands:
    winner = max(cands, key=lambda x: x[1]['hit_rate'])
    print(f"\n  ★ 승자: {winner[0]}")
    # 승자 확정 후에만 블라인드 공개
    fn = COMBOS[winner[0]]
    pool_b = [r for r in G if split_of(r['date']) == 'blind']
    mb = metrics([r for r in pool_b if fn(r)], len(pool_b))
    if mb:
        print(f"  블라인드 재현: n={mb['n']} 적중 {mb['hit_rate']:.1f}% "
              f"비용후 {mb['after_cost']:+.2f}% PF {mb['pf']:.2f}")
    else:
        print("  블라인드: 신호 없음")

# ── 부속 연구: 적정가 '산출 보류(판정 불가)' 케이스 성과 ─────────────────────
print()
print("=" * 100)
print("부속 연구 — 적정가 산출 보류(판정 불가) 케이스 (로직은 유지, 성과만 공부)")
print("=" * 100)
hold = [r for r in G if str(r.get('entry_zone') or '') == '판정 불가'
        and r.get('asset_type', 'STOCK') == 'STOCK']
rest = [r for r in G if str(r.get('entry_zone') or '') != '판정 불가'
        and r.get('asset_type', 'STOCK') == 'STOCK']
for label, sub in [("산출 보류(주식)", hold), ("정상 산출(주식)", rest)]:
    m = metrics(sub, len(G)) if sub else None
    if m:
        print(f"  {label:<16} n={m['n']:<5} 적중 {m['hit_rate']:.1f}% 평균 {m['avg']:+.2f}% PF {m['pf']:.2f}")
    else:
        print(f"  {label:<16} n=0")
