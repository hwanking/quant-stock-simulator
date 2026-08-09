# -*- coding: utf-8 -*-
"""
라운드 58b — Exit Engine 측정.

사전등록: docs/PREREG_R58_EXIT_ENGINE.md (먼저 저장·커밋됨).
진입 = 기준가 · 현행 손절 공유 · 같은 봉 동시 도달은 손절 우선(보수) ·
갭 하향 통과는 그 봉 종가 체결(불리한 근사). blind 미사용.
"""
import glob
import io
import json
import os
import sys
import warnings

import numpy as np

warnings.filterwarnings('ignore')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(PROJ, '.portfolio')
H, COST = 20, 0.36
PURGE_FROM = '2025-06-01'


def load_jsonl_map(pattern):
    m = {}
    for path in sorted(glob.glob(os.path.join(P, pattern))):
        with open(path, encoding='utf-8') as f:
            for ln in f:
                try:
                    r = json.loads(ln)
                    m[(r['ticker'], r['date'])] = r
                except Exception:                              # noqa: BLE001
                    continue
    return m


def stop_check(lo, cl, i, stop):
    """i봉에서 손절 발동 여부와 청산가 (갭 하향은 종가 — 불리한 근사)."""
    if lo[i] <= stop:
        return cl[i] if cl[i] < stop else stop
    return None


def run_fixed(hi, lo, cl, stop, tgt):
    """고정 목표 전량 — 같은 봉 동시는 손절 우선."""
    for i in range(H):
        s = stop_check(lo, cl, i, stop)
        if s is not None:
            return s, i + 1
        if hi[i] >= tgt:
            return tgt, i + 1
    return cl[H - 1], H


def run_trail(hi, lo, cl, stop, trail_w, arm_from=0):
    """피크 대비 trail_w(%p) 하회 시 전량. arm_from 봉부터 감시."""
    peak = 0.0
    for i in range(H):
        s = stop_check(lo, cl, i, stop)
        if s is not None:
            return s, i + 1
        peak = max(peak, hi[i])
        lv = peak - trail_w
        if i >= arm_from and lv > stop and lo[i] <= lv:
            return (cl[i] if cl[i] < lv else lv), i + 1
    return cl[H - 1], H


def run_low_trail(hi, lo, cl, stop):
    """직전 5봉 최저 low 하회 시 전량."""
    for i in range(H):
        s = stop_check(lo, cl, i, stop)
        if s is not None:
            return s, i + 1
        if i >= 5:
            lv = min(lo[i - 5:i])
            if lv > stop and lo[i] <= lv:
                return (cl[i] if cl[i] < lv else lv), i + 1
    return cl[H - 1], H


def run_ma10(hi, lo, cl, stop):
    for i in range(H):
        s = stop_check(lo, cl, i, stop)
        if s is not None:
            return s, i + 1
        if i >= 9:
            ma = float(np.mean(cl[i - 9:i + 1]))
            if cl[i] < ma:
                return cl[i], i + 1
    return cl[H - 1], H


def run_partial(hi, lo, cl, stop, legs, trail_w):
    """부분 익절: legs=[(목표%, 비중)], 잔여는 2ATR 트레일링."""
    rem, ret, bars = 1.0, 0.0, H
    done = [False] * len(legs)
    peak = 0.0
    for i in range(H):
        s = stop_check(lo, cl, i, stop)
        if s is not None:
            ret += rem * s
            return ret, i + 1
        peak = max(peak, hi[i])
        for k, (tg, w) in enumerate(legs):
            if not done[k] and hi[i] >= tg:
                done[k] = True
                ret += w * tg
                rem -= w
        lv = peak - trail_w
        if all(done) and rem > 0 and lv > stop and lo[i] <= lv:
            ret += rem * (cl[i] if cl[i] < lv else lv)
            return ret, i + 1
    ret += rem * cl[H - 1]
    return ret, H


def evaluate(rows, name):
    out = {}
    res = {}
    for r in rows:
        hi, lo, cl = r['_hi'], r['_lo'], r['_cl']
        stop, atr = r['_stp'], r['_atr']
        base_net = float(r['return_pct']) - COST
        cands = {'현행(기준선)': (base_net, None)}
        for tg in (3.0, 5.0, 7.0, 10.0):
            px, b = run_fixed(hi, lo, cl, stop, tg)
            cands[f'고정+{tg:.0f}'] = (px - COST, b)
        px, b = run_fixed(hi, lo, cl, stop, 4.0)
        cands['A:+4전량'] = (px - COST, b)
        px, b = run_partial(hi, lo, cl, stop, [(4.0, 0.5)], 2 * atr)
        cands['B:+4절반→2ATR'] = (px - COST, b)
        px, b = run_partial(hi, lo, cl, stop, [(5.0, 0.3), (8.0, 0.3)],
                            2 * atr)
        cands['C:+5/+8→2ATR'] = (px - COST, b)
        px, b = run_trail(hi, lo, cl, stop, 2 * atr)
        cands['2ATR트레일'] = (px - COST, b)
        px, b = run_low_trail(hi, lo, cl, stop)
        cands['5봉저점트레일'] = (px - COST, b)
        px, b = run_ma10(hi, lo, cl, stop)
        cands['MA10이탈'] = (px - COST, b)
        cands['타임스탑10'] = (cl[9] - COST, 10)
        for nm, (net, b) in cands.items():
            a = res.setdefault(nm, dict(net=[], bars=[]))
            a['net'].append(net)
            if b:
                a['bars'].append(b)
    print(f'\n■ {name} (n={len(rows):,})')
    print(f"{'후보':16s} {'순EV':>7} {'승률':>6} {'PF':>6} {'보유중앙':>5}")
    for nm, a in res.items():
        net = np.array(a['net'])
        pos = float(net[net > 0].sum())
        neg = float(-net[net < 0].sum())
        out[nm] = dict(ev=float(net.mean()), win=float((net > 0).mean() * 100),
                       pf=(pos / neg if neg > 0 else float('inf')),
                       bars=(float(np.median(a['bars']))
                             if a['bars'] else None))
        print(f"{nm:16s} {net.mean():>+7.3f} "
              f"{(net > 0).mean() * 100:>5.1f}% {out[nm]['pf']:>6.2f} "
              f"{(np.median(a['bars']) if a['bars'] else 20):>5.0f}")
    return out


def main():
    paths = load_jsonl_map('bar_paths_s*.jsonl')
    anchors = load_jsonl_map('entry_anchors_s*.jsonl')
    rows = []
    with open(os.path.join(P, 'virtual_graded.jsonl'), encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:                                  # noqa: BLE001
                continue
            if (r.get('split') == 'blind' or r.get('outcome') == 'OPEN'
                    or float(r.get('score') or 0) < 58.0):
                continue
            k = (str(r['ticker']), str(r['date'])[:10])
            p, anc = paths.get(k), anchors.get(k)
            if not p or not anc or p.get('n_bars', 0) < H:
                continue
            atr = anc.get('atr14_pct')
            if not isinstance(atr, (int, float)) or atr <= 0:
                continue
            bars = p['bars'][:H]
            px = float(r['price'])
            r['_hi'] = [b[1] for b in bars]
            r['_lo'] = [b[2] for b in bars]
            r['_cl'] = [b[3] for b in bars]
            r['_stp'] = (float(r['stop']) / px - 1) * 100
            r['_atr'] = float(atr)
            rows.append(r)
    tr = [r for r in rows if r['split'] == 'train'
          and str(r['date'])[:10] < PURGE_FROM]
    va = [r for r in rows if r['split'] == 'valid']
    print(f'결합 {len(rows):,} · train {len(tr):,} · valid {len(va):,}')

    t_tab = evaluate(tr, 'train')
    champ = max((k for k in t_tab if k != '현행(기준선)'),
                key=lambda k: t_tab[k]['ev'])
    print(f'\n챔피언(train): {champ} — 순EV {t_tab[champ]["ev"]:+.3f} '
          f'(기준선 {t_tab["현행(기준선)"]["ev"]:+.3f})')

    v_tab = evaluate(va, 'valid (1회)')
    base, ch = v_tab['현행(기준선)'], v_tab[champ]
    tb, tc = t_tab['현행(기준선)'], t_tab[champ]
    gates = {
        '순EV > 기준선 (valid)': ch['ev'] > base['ev'],
        'PF > 기준선 (valid)': ch['pf'] > base['pf'],
        '승률 ≥ 기준선-3%p': ch['win'] >= base['win'] - 3.0,
        'train 도 같은 방향': tc['ev'] > tb['ev'] and tc['pf'] > tb['pf'],
    }
    print('\n■ 채택 게이트 (사전등록 §3)')
    ok = True
    for k, v in gates.items():
        ok &= v
        print(f"  [{'통과' if v else '미달'}] {k}")
    print(f"\n판정: {'전부 통과 — 전방 병행 자격' if ok else '기각 — 현행 유지'}")

    with open(os.path.join(P, 'exit_engine_r58.json'), 'w',
              encoding='utf-8') as f:
        json.dump(dict(train=t_tab, valid=v_tab, champion=champ,
                       gates={k: bool(v) for k, v in gates.items()},
                       gate_pass=bool(ok), made='2026-08-09',
                       blind_touched=False),
                  f, ensure_ascii=False, indent=1)
    print('저장: .portfolio/exit_engine_r58.json (blind 미접촉)')


if __name__ == '__main__':
    main()
