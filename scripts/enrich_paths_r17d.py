# -*- coding: utf-8 -*-
"""
라운드 17d — 원장에 **경로 전체**를 붙인다. 이게 이번 스터디의 자물쇠였다.

■ 왜 필요한가
  원장의 mfe/mae 는 **청산 봉까지만** 잰 값이다(prediction_log.grade_prediction).
  그건 옳은 설계다 — 손절 뒤 반등을 성과로 세면 안 되니까. 그런데 그래서
  "목표를 더 넓게 잡았으면 어땠을까"는 이 원장으로 **답할 수 없다**.
  청산 이후의 가격을 모르기 때문이다.
  라운드 17 이 그걸 모르고 답을 냈고, 그 답은 무효였다.

■ 무엇을 남기나
  사례마다 기준일 다음 20거래일의 고가·저가를 **진입가 대비 %** 로 남긴다.
  20봉 × 2개 = 숫자 40개. 이것만 있으면 어떤 (목표, 손절) 조합이든
  **선도달 순서까지 정확히** 재현할 수 있다 — 모호분이 아예 사라진다.

■ 판정 규칙은 현행 엔진과 똑같이 맞춘다
  같은 봉에서 목표·손절이 함께 닿으면 **손절 먼저**로 본다 (보수적).
  grade_prediction 과 한 글자도 다르게 하지 않는다 — 다르면 비교가 무의미하다.

■ 누수에 대하여
  이건 '채점'이지 '예측'이 아니다. 채점은 미래를 봐도 된다 — 과거 예측이
  맞았는지 세는 일이기 때문이다. 예측 경로(run_full_pipeline)는 손대지 않는다.
"""
import io
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
LED = os.path.join(BASE, '.portfolio', 'virtual_graded.jsonl')
OUT = os.path.join(BASE, '.portfolio', 'virtual_paths.jsonl')

HORIZON = 20


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
    import bitemporal_engine as be
    from prediction_log import _bars_after

    rows = load_ledger()
    by_tk = {}
    for r in rows:
        by_tk.setdefault(r['ticker'], []).append(r)
    print(f'원장 {len(rows):,}건 · 티커 {len(by_tk)}개')

    # 이미 만든 것은 건너뛴다 (중간에 끊겨도 이어서 돌릴 수 있게)
    done = set()
    if os.path.exists(OUT):
        with open(OUT, encoding='utf-8') as f:
            for ln in f:
                try:
                    d = json.loads(ln)
                    done.add((d['ticker'], d['date']))
                except Exception:
                    pass
        print(f'이미 기록된 경로 {len(done):,}건 — 건너뛴다')

    eng = be.BitemporalEngine()
    t0 = time.time()
    n_new = n_skip = n_fail = 0
    with open(OUT, 'a', encoding='utf-8') as out:
        for i, (tk, group) in enumerate(sorted(by_tk.items()), 1):
            need = [r for r in group if (tk, r['date']) not in done]
            if not need:
                n_skip += len(group)
                continue
            try:
                pdf, _ = eng.generate_synthetic_bitemporal_data(
                    symbol=tk, start_date='2015-01-01', end_date=None)
            except Exception as exc:
                n_fail += len(need)
                print(f'  [{i:>3}/{len(by_tk)}] {tk} 시세 실패 — '
                      f'{type(exc).__name__}: {exc}')
                continue
            got = 0
            for r in need:
                entry = r.get('price')
                if not entry:
                    n_fail += 1
                    continue
                bars = _bars_after(pdf, r.get('date'),
                                   r.get('horizon_days') or HORIZON)
                if not bars:
                    n_fail += 1
                    continue
                highs = [round((h / entry - 1.0) * 100.0, 3) for h, _l, _c in bars]
                lows = [round((l / entry - 1.0) * 100.0, 3) for _h, l, _c in bars]
                closes = [round((c / entry - 1.0) * 100.0, 3) for _h, _l, c in bars]
                out.write(json.dumps({
                    'ticker': tk, 'date': r['date'],
                    'n_bars': len(bars),
                    'high': highs, 'low': lows, 'close': closes,
                }, ensure_ascii=False) + '\n')
                got += 1
                n_new += 1
            out.flush()
            el = time.time() - t0
            print(f'  [{i:>3}/{len(by_tk)}] {tk:<12} +{got:>3}건  '
                  f'누적 {n_new:,}건 · {el:.0f}초')

    print(f'\n완료 — 새로 {n_new:,}건 · 건너뜀 {n_skip:,}건 · 실패 {n_fail:,}건 '
          f'· {time.time() - t0:.0f}초')
    print(f'기록: {OUT}')


if __name__ == '__main__':
    main()
