# -*- coding: utf-8 -*-
"""
진입 기준선 축적 (라운드 57 — PREREG_R57_ENTRY_ENGINE.md §1).

신호일 **이전 봉만** 써서 (누출 금지) 표준 기준선을 계산해 박제한다:
ATR14 · MA5 · MA20 · BB20 중앙/하단 · 직전 10봉 최저 low · 직전 20봉
최고 high. 전부 기준가 대비 % — 경로 파일과 같은 단위.

판정·선택은 여기서 하지 않는다. 원장은 읽기만 한다.

    C:/Python314/python.exe scripts/entry_anchor_recorder.py [--shard i/n]
"""
import glob
import io
import json
import os
import sys
import time
import warnings

import numpy as np

warnings.filterwarnings('ignore')
try:                       # 라운드 103 — 객체를 갈아끼우지 않는다
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:          # noqa: BLE001
    pass
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
P = os.path.join(PROJ, '.portfolio')

import bitemporal_engine as be                                # noqa: E402


def load_done():
    done = set()
    for path in sorted(glob.glob(os.path.join(P, 'entry_anchors*.jsonl'))):
        with open(path, encoding='utf-8') as f:
            for ln in f:
                try:
                    r = json.loads(ln)
                    done.add((r['ticker'], r['date']))
                except Exception:                              # noqa: BLE001
                    continue
    return done


def pct(v, px):
    return round(float(v) / px * 100 - 100, 3) if v and v > 0 else None


def main():
    shard, shards = 0, 1
    if '--shard' in sys.argv:
        raw = sys.argv[sys.argv.index('--shard') + 1]
        shard, shards = (int(x) for x in raw.split('/'))

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
            tk = str(r.get('ticker'))
            d = str(r.get('date'))[:10]
            px = r.get('price')
            if tk and d and px:
                by_tk.setdefault(tk, {})[d] = float(px)

    tks = sorted(by_tk)[shard::shards]
    done = load_done()
    out_path = os.path.join(P, f'entry_anchors_s{shard}.jsonl')
    print(f'조각 {shard}/{shards} — 종목 {len(tks)} · 이미 완료 {len(done):,}')

    eng = be.BitemporalEngine()
    t0, wrote, skip = time.time(), 0, 0
    with open(out_path, 'a', encoding='utf-8') as out:
        for i, tk in enumerate(tks):
            todo = [(d, px) for d, px in sorted(by_tk[tk].items())
                    if (tk, d) not in done]
            if not todo:
                continue
            try:
                df, _f = eng.load_bitemporal_data(tk, start_date='2014-01-01')
            except Exception:                                  # noqa: BLE001
                skip += 1
                continue
            if df is None or len(df) < 30:
                skip += 1
                continue
            dates = list(df['trade_date'].astype(str).str[:10])
            idx = {d: j for j, d in enumerate(dates)}
            Hi = df['high_raw'].astype(float).to_numpy()
            Lo = df['low_raw'].astype(float).to_numpy()
            Cl = df['adj_close'].astype(float).to_numpy()
            for d, px in todo:
                j = idx.get(d)
                if j is None or j < 21:
                    continue          # 신호일 봉이 없거나 이전 이력 부족
                # 전부 신호일 포함 이전 봉만 (j 까지) — 미래 누출 금지
                tr = np.maximum(Hi[j - 13:j + 1] - Lo[j - 13:j + 1],
                                np.maximum(
                                    np.abs(Hi[j - 13:j + 1] - Cl[j - 14:j]),
                                    np.abs(Lo[j - 13:j + 1] - Cl[j - 14:j])))
                atr14 = float(np.mean(tr))
                c20 = Cl[j - 19:j + 1]
                ma20 = float(np.mean(c20))
                sd20 = float(np.std(c20))
                row = {
                    'ticker': tk, 'date': d, 'price': px,
                    'atr14_pct': round(atr14 / px * 100, 3),
                    'ma5': pct(float(np.mean(Cl[j - 4:j + 1])), px),
                    'ma20': pct(ma20, px),
                    'bb_mid': pct(ma20, px),
                    'bb_low': pct(ma20 - 2 * sd20, px),
                    'pivot_low10': pct(float(np.min(Lo[j - 9:j + 1])), px),
                    'prev_high20': pct(float(np.max(Hi[j - 19:j + 1])), px),
                }
                out.write(json.dumps(row, ensure_ascii=False) + '\n')
                wrote += 1
            out.flush()
            if (i + 1) % 20 == 0:
                el = time.time() - t0
                print(f'  종목 {i + 1}/{len(tks)} · 기록 {wrote:,} · '
                      f'{el:,.0f}s · 실패 {skip}')
    print(f'\n완료 — 기록 {wrote:,}행 · 수신 실패 종목 {skip}')
    print(f'저장: {out_path} (기준가 대비 % · atr 은 %폭)')


if __name__ == '__main__':
    main()
