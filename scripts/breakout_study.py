# -*- coding: utf-8 -*-
"""
라운드 64 — 장기 돌파 하이패스 측정.

사전등록: docs/PREREG_R64_BREAKOUT_BYPASS.md (먼저 저장·커밋됨).
계기: BGF리테일이 전고·장기밴드 돌파에도 '표본 0건·EV 음수'로 제외됐다.
질문: 눌림목 중심 룰이 추세 돌파형을 체계적으로 놓치는가?

돌파 지표는 신호일 **이전 봉만**으로 계산한다 (누출 금지).
blind 미사용 · 개발 구간만.
"""
import glob
import io
import json
import math
import os
import sys
import time
import warnings
import zlib
from datetime import date, timedelta

import numpy as np

warnings.filterwarnings('ignore')
try:                       # 라운드 103 — 객체를 갈아끼우지 않는다
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:          # noqa: BLE001
    pass
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
P = os.path.join(PROJ, '.portfolio')
H, COST = 20, 0.36

import bitemporal_engine as be                                # noqa: E402


def wilson_low(k, n, z=1.96):
    if n == 0:
        return 0.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - m) / d * 100.0


def build_flags(shard, shards):
    """종목별로 시세 1회 수신 → 신호일마다 돌파 조건 5종 판정."""
    by_tk = {}
    with open(os.path.join(P, 'virtual_graded.jsonl'), encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:                                  # noqa: BLE001
                continue
            if r.get('split') == 'blind' or r.get('outcome') == 'OPEN':
                continue
            by_tk.setdefault(str(r['ticker']), set()).add(str(r['date'])[:10])

    # ⚠️ 라운드 106 — 여기가 `sorted(by_tk)[shard::shards]` 였다.
    #   **위치로 가르는 분할**은 목록이 고정일 때만 성립한다. 원장에 종목이
    #   하나 늘면 정렬 위치가 통째로 밀려 **모든 종목이 다른 조각으로 간다.**
    #   backfill_subscores 가 라운드 73 에서 정확히 이 문제를 고치며 적어
    #   뒀는데(안정 해시), 이 파일에는 안 왔다.
    #
    #   실측 결과: 돌파 플래그 '설명 안 됨' 2,642건이 **20종목에만** 몰려
    #   있고, 그 20종목 전부가 다른 날짜에는 플래그를 받았다. 2015~2026 에
    #   고르게 흩어져 있고 최근 축적분은 0% — 시점 문제가 아니라 분할 문제다.
    #
    #   키 자체의 안정 해시로 가른다. 종목이 몇 개든 같은 종목은 늘 같은 조각.
    tks = [t for t in sorted(by_tk)
           if zlib.crc32(t.encode()) % shards == shard]
    out_path = os.path.join(P, f'breakout_flags_s{shard}.jsonl')
    # ⚠️ 그리고 `done` 을 **자기 조각 파일에서만** 읽고 있었다.
    #   조각이 바뀐 종목의 옛 기록은 다른 파일에 있어 안 보인다 —
    #   path_recorder 는 처음부터 전체 glob 을 읽는다(그래서 100%다).
    done = set()
    for _p in sorted(glob.glob(os.path.join(P, 'breakout_flags_s*.jsonl'))):
        with open(_p, encoding='utf-8', errors='replace') as f:
            for ln in f:
                try:
                    q = json.loads(ln)
                    done.add((q['ticker'], q['date']))
                except Exception:                              # noqa: BLE001
                    continue
    eng = be.BitemporalEngine()
    t0, wrote, skip = time.time(), 0, 0
    with open(out_path, 'a', encoding='utf-8') as out:
        for i, tk in enumerate(tks):
            todo = sorted(d for d in by_tk[tk] if (tk, d) not in done)
            if not todo:
                continue
            try:
                df, _ = eng.load_bitemporal_data(tk, start_date='2013-01-01')
            except Exception:                                  # noqa: BLE001
                skip += 1
                continue
            if df is None or len(df) < 260:
                skip += 1
                continue
            dates = list(df['trade_date'].astype(str).str[:10])
            idx = {d: j for j, d in enumerate(dates)}
            C = df['adj_close'].astype(float).to_numpy()
            V = df['volume'].astype(float).to_numpy()
            for d in todo:
                j = idx.get(d)
                if j is None or j < 245:
                    continue
                px = float(C[j])
                prev240 = C[j - 240:j]           # 신호일 제외 (누출 금지)
                ma240 = float(prev240.mean())
                sd240 = float(prev240.std())
                ma200 = float(C[j - 200:j].mean())
                ma60 = float(C[j - 60:j].mean())
                ma120 = float(C[j - 120:j].mean())
                v20 = float(V[j - 20:j].mean())
                out.write(json.dumps({
                    'ticker': tk, 'date': d,
                    'b1': bool(px > float(prev240.max())),
                    'b2': bool(px > ma240 + 2 * sd240),
                    'b3': bool(px > ma200),
                    'b4': bool(v20 > 0 and V[j] >= v20 * 1.5),
                    'b5': bool(ma60 > ma120 > ma240),
                    'break_line': round(max(float(prev240.max()),
                                            ma240 + 2 * sd240) / px * 100
                                        - 100, 3),
                }, ensure_ascii=False) + '\n')
                wrote += 1
            out.flush()
            if (i + 1) % 20 == 0:
                print(f'  {i + 1}/{len(tks)} · {wrote:,}행 · '
                      f'{time.time() - t0:,.0f}s · 실패 {skip}')
    print(f'완료 {wrote:,}행 · 수신 실패 {skip}종목 → {out_path}')


def analyze():
    flags = {}
    for path in sorted(glob.glob(os.path.join(P, 'breakout_flags_s*.jsonl'))):
        with open(path, encoding='utf-8') as f:
            for ln in f:
                try:
                    q = json.loads(ln)
                    flags[(q['ticker'], q['date'])] = q
                except Exception:                              # noqa: BLE001
                    continue
    paths = {}
    for path in sorted(glob.glob(os.path.join(P, 'bar_paths_s*.jsonl'))):
        with open(path, encoding='utf-8') as f:
            for ln in f:
                try:
                    q = json.loads(ln)
                    paths[(q['ticker'], q['date'])] = q
                except Exception:                              # noqa: BLE001
                    continue

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
            if r.get('split') == 'blind' or r.get('outcome') == 'OPEN':
                continue
            k = (str(r['ticker']), str(r['date'])[:10])
            fl, p = flags.get(k), paths.get(k)
            if not fl or not p or p.get('n_bars', 0) < H:
                continue
            bars = p['bars'][:H]
            r['_fl'] = fl
            r['_hi'] = [b[1] for b in bars]
            r['_lo'] = [b[2] for b in bars]
            r['_cl'] = [b[3] for b in bars]
            r['_op'] = [(b[5] if len(b) > 5 else None) for b in bars]
            rows.append(r)
    print(f'결합 {len(rows):,}건 (점수 무관 · 개발 구간 · 블라인드 제외)\n')

    def ep_n(sub):
        """에피소드 수 — 같은 종목 35일 묶음."""
        last, n = {}, 0
        for r in sorted(sub, key=lambda x: (str(x['ticker']), str(x['date']))):
            tk = str(r['ticker'])
            try:
                dd = date.fromisoformat(str(r['date'])[:10])
            except ValueError:
                continue
            if tk not in last or (dd - last[tk]) > timedelta(days=35):
                n += 1
                last[tk] = dd
        return n

    def stat(sub, name, entry='close'):
        if not sub:
            print(f'  {name:28s} 표본 없음')
            return None
        n = len(sub)
        k = sum(1 for r in sub if r.get('success'))
        if entry == 'close':
            net = np.array([r['_cl'][-1] - COST for r in sub])
        elif entry == 'open1':
            net = np.array([
                ((1 + r['_cl'][-1] / 100) / (1 + (r['_op'][0] or 0) / 100)
                 - 1) * 100 - COST for r in sub])
        else:                                    # retest 3~10봉 되눌림
            net = []
            for r in sub:
                fill = None
                for i in range(2, min(10, H)):
                    if r['_lo'][i] <= 0.0:
                        fill = 0.0
                        break
                if fill is None:
                    continue
                net.append(r['_cl'][-1] - COST)
            net = np.array(net) if net else np.array([0.0])
        pos = float(net[net > 0].sum())
        neg = float(-net[net < 0].sum())
        false_br = np.mean([min(r['_lo']) <= r['_fl']['break_line']
                            for r in sub]) * 100
        print(f"  {name:28s} n {n:>6,} (ep {ep_n(sub):>5,}) · "
              f"적중 {k / n * 100:5.1f}% (W {wilson_low(k, n):4.1f}) · "
              f"EV {net.mean():+7.3f} · PF "
              f"{(pos / neg if neg > 0 else 0):4.2f} · 거짓돌파 "
              f"{false_br:4.1f}%")
        return dict(n=n, ep=ep_n(sub), hit=round(k / n * 100, 1),
                    wilson=round(wilson_low(k, n), 1),
                    ev=round(float(net.mean()), 3),
                    pf=round(pos / neg, 2) if neg > 0 else None,
                    false_break=round(float(false_br), 1))

    br = [r for r in rows if r['_fl']['b1'] or r['_fl']['b2']]
    nb = [r for r in rows if not (r['_fl']['b1'] or r['_fl']['b2'])]
    print('■ 돌파 vs 비돌파 (진입 = 돌파일 종가)')
    s_br = stat(br, '돌파 (B1 or B2)')
    s_nb = stat(nb, '비돌파')

    print('\n■ 돌파 진입 방식 비교')
    s_open = stat(br, '돌파 → 다음 봉 시가', entry='open1')
    s_re = stat(br, '돌파 → 되눌림 대기', entry='retest')

    print('\n■ 조건 조합 분해 (B1 전고 · B2 밴드 · B3 월10선 · B4 거래량 · B5 정렬)')
    combos = {}
    for name, cond in (
            ('B1 전고 돌파', lambda f: f['b1']),
            ('B2 장기밴드 상단', lambda f: f['b2']),
            ('B1+B4 거래량 동반', lambda f: f['b1'] and f['b4']),
            ('B1+B5 추세 정렬', lambda f: f['b1'] and f['b5']),
            ('B1+B3+B4+B5', lambda f: (f['b1'] and f['b3'] and f['b4']
                                       and f['b5'])),
            ('전부(B1~B5)', lambda f: all(f[k] for k in
                                        ('b1', 'b2', 'b3', 'b4', 'b5'))),
    ):
        combos[name] = stat([r for r in rows if cond(r['_fl'])], name)

    print('\n■ 매수권(58+) 안에서는 어떤가 — 지금 통과하는 신호들')
    hi = [r for r in rows if float(r.get('score') or 0) >= 58]
    stat([r for r in hi if r['_fl']['b1'] or r['_fl']['b2']], '매수권 · 돌파')
    stat([r for r in hi if not (r['_fl']['b1'] or r['_fl']['b2'])],
         '매수권 · 비돌파')

    gates = {
        'EV > 0': bool(s_br and s_br['ev'] > 0),
        'EV > 비돌파': bool(s_br and s_nb and s_br['ev'] > s_nb['ev']),
        'Wilson 하한 > 비돌파 적중': bool(
            s_br and s_nb and s_br['wilson'] > s_nb['hit']),
        '에피소드 ≥ 300': bool(s_br and s_br['ep'] >= 300),
        '거짓돌파 < 50%': bool(s_br and s_br['false_break'] < 50),
    }
    print('\n■ 채택 게이트 (사전등록 §4)')
    ok = True
    for k, v in gates.items():
        ok &= v
        print(f"  [{'통과' if v else '미달'}] {k}")
    print(f"\n판정: {'하이패스 후보 자격 — 전방 재평가로' if ok else '기각 — 현행 유지'}")

    with open(os.path.join(P, 'breakout_study_r64.json'), 'w',
              encoding='utf-8') as f:
        json.dump(dict(breakout=s_br, non_breakout=s_nb, open1=s_open,
                       retest=s_re, combos=combos,
                       gates={k: bool(v) for k, v in gates.items()},
                       gate_pass=bool(ok), made='2026-08-10',
                       blind_touched=False), f, ensure_ascii=False, indent=1)
    print('저장: .portfolio/breakout_study_r64.json (blind 미접촉)')


if __name__ == '__main__':
    if '--build' in sys.argv:
        sh, shs = 0, 1
        if '--shard' in sys.argv:
            raw = sys.argv[sys.argv.index('--shard') + 1]
            sh, shs = (int(x) for x in raw.split('/'))
        build_flags(sh, shs)
    else:
        analyze()
