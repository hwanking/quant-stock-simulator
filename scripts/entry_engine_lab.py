# -*- coding: utf-8 -*-
"""
라운드 57 — Entry Engine 측정.

사전등록: docs/PREREG_R57_ENTRY_ENGINE.md (먼저 저장·커밋됨).
train 비교표 → 챔피언(정책 EV 최고 · 체결률≥50%) → valid 1회 게이트.
blind 미사용.
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


def candidates(row, anc):
    """신호 하나의 진입 후보 목록 [(이름, 후보가 %, 돌파형?)]. 누출 없음."""
    out = [('즉시', 0.0, False)]
    v = row.get('vol20')
    if isinstance(v, (int, float)) and v > 0:
        out.append(('현행눌림(-1vol)', -float(v) * 100, False))
    a = anc.get('atr14_pct')
    if isinstance(a, (int, float)) and a > 0:
        out.append(('ATR0.5눌림', -0.5 * a, False))
        out.append(('ATR1.0눌림', -1.0 * a, False))
    for key, nm in (('ma5', 'MA5'), ('ma20', 'MA20'),
                    ('bb_mid', 'BB중앙'), ('bb_low', 'BB하단'),
                    ('pivot_low10', '피벗지지10')):
        x = anc.get(key)
        if isinstance(x, (int, float)) and x < 0:   # 기준가 아래일 때만
            out.append((nm, float(x), False))
    ph = anc.get('prev_high20')
    if isinstance(ph, (int, float)):
        out.append(('돌파재지지', float(ph), True))
    return out


def fill_of(cand_pct, breakout, lo, hi, op):
    """(체결 봉 인덱스, 체결가 %) 또는 (None, None).

    라운드 57b 실행 정확화:
      · 즉시형은 **1봉째 시가**에 체결 — 종가 체결 가정은 갭 상승 장에서
        EV 를 부풀린다 (실전은 다음 날 시가에 산다)
      · 지정가는 시가가 이미 지정가 아래면 **시가**에 체결 (갭 통과 —
        지정가보다 유리한 실제 체결가). 아니면 지정가
      · 같은 봉 돌파+재지지 동시는 보수적으로 미체결
    """
    if not breakout:
        if cand_pct >= 0:                    # 즉시형 — 1봉째 시가
            o0 = op[0] if op and op[0] is not None else None
            return (0, o0) if o0 is not None else (None, None)
        for i, l_ in enumerate(lo):
            if l_ <= cand_pct:
                oi = op[i] if op and op[i] is not None else cand_pct
                return i, (oi if oi <= cand_pct else cand_pct)
        return None, None
    conf = None
    for i, h_ in enumerate(hi):
        if h_ >= max(cand_pct, 0.01):
            conf = i
            break
    if conf is None:
        return None, None
    for i in range(conf + 1, len(lo)):       # 같은 봉 재지지는 미체결 처리
        if lo[i] <= cand_pct:
            oi = op[i] if op and op[i] is not None else cand_pct
            return i, (oi if oi <= cand_pct else cand_pct)
    return None, None


def evaluate(rows, name):
    """후보별 집계표."""
    agg = {}
    for r in rows:
        for nm, cp, bo in r['_cands']:
            fb, fp = fill_of(cp, bo, r['_lo'], r['_hi'], r['_op'])
            a = agg.setdefault(nm, dict(n=0, f3=0, f5=0, f10=0, f20=0,
                                        net=[], miss=[], bars=[]))
            a['n'] += 1
            if fb is None:
                a['miss'].append(r['_cl'][-1] - COST)
                continue
            net = ((1 + r['_cl'][-1] / 100) / (1 + fp / 100) - 1) * 100 - COST
            a['net'].append(net)
            a['bars'].append(fb + 1)
            a['f20'] += 1
            if fb < 3:
                a['f3'] += 1
            if fb < 5:
                a['f5'] += 1
            if fb < 10:
                a['f10'] += 1
    out = {}
    print(f'\n■ {name} — 후보별 (n={len(rows):,})')
    print(f"{'후보':16s} {'체결20':>6} | {'체결EV':>7} {'양수':>5} {'PF':>5} "
          f"{'중앙봉':>4} | {'정책EV':>7} | {'미체결EV':>7}")
    for nm, a in agg.items():
        if a['n'] == 0:
            continue
        fr = a['f20'] / a['n'] * 100
        net = np.array(a['net']) if a['net'] else np.array([0.0])
        pos = sum(x for x in net if x > 0)
        neg = -sum(x for x in net if x < 0)
        pf = pos / neg if neg > 0 else float('inf')
        pol = float(np.sum(net)) / a['n'] if a['net'] else 0.0
        miss = float(np.mean(a['miss'])) if a['miss'] else None
        out[nm] = dict(n=a['n'], fill20=fr, ev=float(np.mean(net)),
                       win=float((net > 0).mean() * 100), pf=float(pf),
                       med_bar=(float(np.median(a['bars']))
                                if a['bars'] else None),
                       policy_ev=pol, miss_ev=miss)
        print(f"{nm:16s} {fr:>5.1f}% | {np.mean(net):>+7.3f} "
              f"{(net > 0).mean() * 100:>4.1f}% {pf:>5.2f} "
              f"{(np.median(a['bars']) if a['bars'] else 0):>4.0f} | "
              f"{pol:>+7.3f} | "
              f"{(miss if miss is not None else 0):>+7.3f}")
    return out


def main():
    anchors = load_jsonl_map('entry_anchors_s*.jsonl')
    paths = load_jsonl_map('bar_paths_s*.jsonl')
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
            bars = p['bars'][:H]
            r['_hi'] = [b[1] for b in bars]
            r['_lo'] = [b[2] for b in bars]
            r['_cl'] = [b[3] for b in bars]
            r['_op'] = [(b[5] if len(b) > 5 else None) for b in bars]
            r['_cands'] = candidates(r, anc)
            rows.append(r)
    tr = [r for r in rows if r['split'] == 'train'
          and str(r['date'])[:10] < PURGE_FROM]
    va = [r for r in rows if r['split'] == 'valid']
    print(f'결합 {len(rows):,} · train {len(tr):,}(퍼지 적용) · '
          f'valid {len(va):,}')

    t_tab = evaluate(tr, 'train')
    # 챔피언: 체결률≥50% 후보 중 정책 EV 최고 (사전등록 §3)
    elig = {k: v for k, v in t_tab.items()
            if v['fill20'] >= 50 and k != '현행눌림(-1vol)'}
    champ = max(elig, key=lambda k: elig[k]['policy_ev'])
    print(f'\n챔피언(train): {champ} — 정책EV {elig[champ]["policy_ev"]:+.3f}')

    v_tab = evaluate(va, 'valid (1회)')
    base, ch = v_tab.get('현행눌림(-1vol)'), v_tab.get(champ)
    print('\n■ 채택 게이트 (사전등록 §3 · valid)')
    gates = {
        '정책EV > 기준선': ch['policy_ev'] > base['policy_ev'],
        '체결률 ≥ 50%': ch['fill20'] >= 50,
        'PF > 기준선': ch['pf'] > base['pf'],
        '체결분 순EV > 0': ch['ev'] > 0,
    }
    ok = True
    for k, v in gates.items():
        ok &= v
        print(f"  [{'통과' if v else '미달'}] {k}")
    print(f"\n판정: {'전부 통과 — 전방 병행 자격' if ok else '기각 — 현행 유지'}")
    print(f"  기준선(현행눌림) 정책EV {base['policy_ev']:+.3f} · "
          f"PF {base['pf']:.2f} · 체결 {base['fill20']:.1f}%")
    print(f"  챔피언({champ})   정책EV {ch['policy_ev']:+.3f} · "
          f"PF {ch['pf']:.2f} · 체결 {ch['fill20']:.1f}%")

    with open(os.path.join(P, 'entry_engine_r57.json'), 'w',
              encoding='utf-8') as f:
        json.dump(dict(train=t_tab, valid=v_tab, champion=champ,
                       gates={k: bool(v) for k, v in gates.items()},
                       gate_pass=bool(ok), made='2026-08-09',
                       blind_touched=False),
                  f, ensure_ascii=False, indent=1)
    print('\n저장: .portfolio/entry_engine_r57.json (blind 미접촉)')


if __name__ == '__main__':
    main()
