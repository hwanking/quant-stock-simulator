# -*- coding: utf-8 -*-
"""
라운드 26 — 원장에 **기준일 시점의 지표 레벨**을 남긴다.

라운드 25 에서 진입 엔진을 겨뤘지만 고정 할인·변동성 비례·돌파뿐이었다.
지지선·이동평균·볼린저 기반 진입가는 **원장에 그 값이 없어 겨루지 못했다.**
그 값을 남겨서 마저 겨룬다.

■ 산식은 엔진 것을 그대로 쓴다
  `QuantIndicatorsEngine.compute_technical_indicators` 를 재사용한다.
  연구가 다른 산식을 쓰면 결과를 운영에 옮길 수 없다.

■ 누수 방지 — 이게 이 스크립트의 유일한 위험이다
  지표는 **기준일까지의 봉만** 써서 계산한다(`trade_date <= t_ref`).
  기준일 다음 봉이 한 개라도 섞이면 그 연구는 통째로 무효다.
  라운드 17 이 창 불일치로 무효가 된 걸 기억한다.

■ 남기는 것 (전부 **진입가 대비 %** — 경로 파일과 같은 단위)
  sma5 · sma20 · sma60 · sma120 · bb_upper · bb_mid · bb_lower ·
  high20 · low10 · atr14 · vol20(비율 그대로) · volume_ratio
"""
import io
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
LED = os.path.join(BASE, '.portfolio', 'virtual_graded.jsonl')
OUT = os.path.join(BASE, '.portfolio', 'virtual_levels.jsonl')

WANT = ('sma_5', 'sma_20', 'sma_60', 'sma_120',
        'bb_upper', 'bb_mid', 'bb_lower')


def load_ledger():
    out = []
    with open(LED, encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                try:
                    out.append(json.loads(ln))
                except Exception:
                    pass
    return out


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    import numpy as np
    import bitemporal_engine as be
    import quant_indicators as qi

    rows = load_ledger()
    by_tk = {}
    for r in rows:
        by_tk.setdefault(r['ticker'], []).append(r)
    print(f'원장 {len(rows):,}건 · 티커 {len(by_tk)}개')

    done = set()
    if os.path.exists(OUT):
        with open(OUT, encoding='utf-8') as f:
            for ln in f:
                try:
                    d = json.loads(ln)
                    done.add((d['ticker'], d['date']))
                except Exception:
                    pass
        print(f'이미 기록된 레벨 {len(done):,}건 — 건너뛴다')

    eng = be.BitemporalEngine()
    q = qi.QuantIndicatorsEngine()
    t0 = time.time()
    n_new = n_fail = 0
    with open(OUT, 'a', encoding='utf-8') as out:
        for i, (tk, group) in enumerate(sorted(by_tk.items()), 1):
            need = [r for r in group if (tk, r['date']) not in done]
            if not need:
                continue
            try:
                pdf, _ = eng.generate_synthetic_bitemporal_data(
                    symbol=tk, start_date='2015-01-01', end_date=None)
                # 지표는 한 번만 계산하고 날짜로 잘라 쓴다 — 사례마다 다시
                # 계산하면 268티커 × 74건 = 2만 번이라 몇 시간이 걸린다.
                # 대신 **자를 때** 기준일 이후를 확실히 버린다.
                tdf = q.compute_technical_indicators(pdf)
                tdf['_d'] = tdf['trade_date'].astype(str).str[:10]
            except Exception as exc:
                n_fail += len(need)
                print(f'  [{i:>3}/{len(by_tk)}] {tk} 실패 — '
                      f'{type(exc).__name__}: {exc}')
                continue

            got = 0
            for r in need:
                d = str(r['date'])[:10]
                entry = r.get('price')
                if not entry:
                    n_fail += 1
                    continue
                sub = tdf[tdf['_d'] <= d]          # ← 기준일까지만 (누수 차단)
                if len(sub) < 20 or str(sub['_d'].iloc[-1]) != d:
                    n_fail += 1
                    continue
                last = sub.iloc[-1]
                rec = {'ticker': tk, 'date': d}
                for k in WANT:
                    v = last.get(k)
                    try:
                        v = float(v)
                        rec[k] = (round((v / entry - 1.0) * 100.0, 3)
                                  if np.isfinite(v) else None)
                    except (TypeError, ValueError):
                        rec[k] = None
                try:
                    hi20 = float(sub['high'].tail(20).max())
                    rec['high20'] = round((hi20 / entry - 1.0) * 100.0, 3)
                except Exception:
                    rec['high20'] = None
                try:
                    lo10 = float(sub['low'].tail(10).min())
                    rec['low10'] = round((lo10 / entry - 1.0) * 100.0, 3)
                except Exception:
                    rec['low10'] = None
                try:
                    atr = float(sub['tr'].tail(14).mean())
                    rec['atr14'] = round(atr / entry * 100.0, 3)
                except Exception:
                    rec['atr14'] = None
                for k, col in (('vol20', 'vol_20'),
                               ('volume_ratio', 'volume_ratio')):
                    try:
                        v = float(last.get(col))
                        rec[k] = round(v, 4) if np.isfinite(v) else None
                    except (TypeError, ValueError):
                        rec[k] = None
                out.write(json.dumps(rec, ensure_ascii=False) + '\n')
                got += 1
                n_new += 1
            out.flush()
            print(f'  [{i:>3}/{len(by_tk)}] {tk:<12} +{got:>3}건  '
                  f'누적 {n_new:,} · {time.time() - t0:.0f}초')

    print(f'\n완료 — 새로 {n_new:,}건 · 실패 {n_fail:,}건 · '
          f'{time.time() - t0:.0f}초')
    print(f'기록: {OUT}')


if __name__ == '__main__':
    main()
