# -*- coding: utf-8 -*-
"""
정직 점검 — 우리 엔진은 지금 돈을 버는가.

사용자가 물었다: "거짓말하면 안 되는 거야. 우리 모델 엔진이 나쁘면 개선하면
되니까, 어디서 가져오면 되니까, 정말로 이야기해 줘."

그래서 가장 불편한 숫자부터 꺼낸다. 적중률이 아니라 **기대값**을 본다.
승률이 50%를 넘어도 손익비가 나쁘면 돈을 잃는다. 그 계산을 그대로 보여 준다.
"""
from __future__ import annotations

import io
import json
import os
import sys

try:                       # 라운드 103 — 객체를 갈아끼우지 않는다
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:          # noqa: BLE001
    pass
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(BASE, '.portfolio', 'virtual_graded.jsonl')
COST = 0.30
BUY = 58


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


def main():
    rows = [r for r in load() if (r.get('score') or 0) >= BUY]
    by = {s: [r for r in rows if r.get('split') == s]
          for s in ('train', 'valid', 'blind')}

    print('■ 지금 이 신호대로 매매하면 어떻게 되는가 (매수권 58점+)\n')
    for s, ko in (('train', '학습'), ('valid', '연습'), ('blind', '실전')):
        rs = by[s]
        if not rs:
            continue
        rets = [float(r['return_pct']) for r in rs]
        win = [v for v in rets if v > 0]
        loss = [v for v in rets if v <= 0]
        wr = 100.0 * len(win) / len(rs)
        avg_w = (sum(win) / len(win)) if win else 0.0
        avg_l = (abs(sum(loss)) / len(loss)) if loss else 0.0
        rr = (avg_w / avg_l) if avg_l else 0.0
        ev = (wr / 100 * avg_w) - ((1 - wr / 100) * avg_l)
        print(f"  [{ko}] n={len(rs):,}")
        print(f"    이길 확률 {wr:.1f}% · 이길 때 평균 {avg_w:+.2f}% · "
              f"질 때 평균 -{avg_l:.2f}%")
        print(f"    손익비 {rr:.2f} : 1")
        print(f"    기대값 = {wr / 100:.3f}×{avg_w:.2f} − "
              f"{1 - wr / 100:.3f}×{avg_l:.2f} = {ev:+.3f}%")
        print(f"    비용({COST}%) 차감 후 = {ev - COST:+.3f}%  "
              f"{'← 돈을 번다' if ev - COST > 0 else '← 돈을 잃는다'}\n")

    # 손익비를 얼마로 올려야 양수가 되는가
    rs = by['blind']
    rets = [float(r['return_pct']) for r in rs]
    win = [v for v in rets if v > 0]
    loss = [v for v in rets if v <= 0]
    wr = len(win) / len(rs)
    avg_l = abs(sum(loss)) / len(loss)
    need = (COST + (1 - wr) * avg_l) / wr
    print('■ 실전에서 돈을 벌려면 무엇이 바뀌어야 하나')
    print(f"  지금 이길 확률 {wr * 100:.1f}% · 질 때 평균 -{avg_l:.2f}%")
    print(f"  → 이길 때 평균 {need:.2f}% 이상 벌어야 본전을 넘는다")
    print(f"     (지금은 {sum(win) / len(win):.2f}% — "
          f"{need - sum(win) / len(win):+.2f}%p 모자란다)")
    print(f"  → 또는 승률을 "
          f"{100 * (COST + avg_l) / (sum(win) / len(win) + avg_l):.1f}% "
          f"까지 올려야 한다 (지금 {wr * 100:.1f}%)")

    print('\n■ 국면별로 보면 (실전 · 6국면)')
    for rg, rko in (('BULL', '상승'), ('SIDEWAYS', '옆걸음'), ('BEAR', '하락')):
        for vb, vko in (('calm', '차분한'), ('rough', '거친')):
            sub = [r for r in by['blind']
                   if r.get('regime') == rg and r.get('vol20') is not None
                   and (float(r['vol20']) < 0.03) == (vb == 'calm')]
            if len(sub) < 20:
                continue
            rr_ = [float(r['return_pct']) for r in sub]
            w_ = [v for v in rr_ if v > 0]
            l_ = [v for v in rr_ if v <= 0]
            wr_ = 100.0 * len(w_) / len(sub)
            aw = (sum(w_) / len(w_)) if w_ else 0
            al = (abs(sum(l_)) / len(l_)) if l_ else 0
            ev_ = (wr_ / 100 * aw) - ((1 - wr_ / 100) * al) - COST
            print(f"  {vko} {rko:4s} n={len(sub):4d} 승률 {wr_:5.1f}% · "
                  f"이길때 {aw:+5.2f}% · 질때 -{al:5.2f}% · "
                  f"손익비 {(aw / al if al else 0):.2f} · "
                  f"비용후 기대값 {ev_:+.2f}% "
                  f"{'✅' if ev_ > 0 else '❌'}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
