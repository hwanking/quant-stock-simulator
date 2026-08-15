# -*- coding: utf-8 -*-
"""
봉 단위 경로 축적 (라운드 56 — Exit·추적손절 연구의 선행 조건).

■ 왜 필요한가
  원장의 mfe/mae 는 **청산 봉까지만** 기록돼 있어 (라운드 36 교훈)
  "+3% 찍고 -2%가 됐는가", "추적손절 2ATR 이 더 나았는가" 같은 질문을
  과거에 되돌려 물을 수 없다. 신호 이후 21봉의 고·저·종가 경로를
  원장과 별도 파일에 박제한다.

■ 원칙
  · 경로는 시장 원자료다 — 판정·채점을 여기서 하지 않는다
  · 원장(virtual_graded.jsonl)은 읽기만 하고 쓰지 않는다
  · 블라인드 행의 경로도 저장은 한다. **분석 시점의 분리**는 각 연구의
    사전등록이 지킨다 — 저장과 사용은 다른 문제다
  · 종목당 시세 1회 수신 → 행별 슬라이스. 실패 종목은 건너뛰고 기록한다

    C:/Python314/python.exe scripts/path_recorder.py [--shard i/n]
"""
import glob
import io
import json
import os
import sys
import time
import warnings
import zlib

warnings.filterwarnings('ignore')
try:                       # 라운드 103 — 객체를 갈아끼우지 않는다
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:          # noqa: BLE001
    pass
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
P = os.path.join(PROJ, '.portfolio')

import bitemporal_engine as be                                # noqa: E402

BARS = 21                      # 신호 다음 날부터 21봉 (판정 지평 20 + 여유 1)


def load_done():
    done = set()
    for path in sorted(glob.glob(os.path.join(P, 'bar_paths*.jsonl'))):
        with open(path, encoding='utf-8') as f:
            for ln in f:
                try:
                    r = json.loads(ln)
                    done.add((r['ticker'], r['date']))
                except Exception:                              # noqa: BLE001
                    continue
    return done


def main():
    shard, shards = 0, 1
    if '--shard' in sys.argv:
        raw = sys.argv[sys.argv.index('--shard') + 1]
        shard, shards = (int(x) for x in raw.split('/'))

    # 원장에서 (종목 → [(date, price)]) 를 모은다 — 결과 필드는 읽지 않는다
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

    # 라운드 106 — 위치 분할을 안정 해시로 바꿨다. 원장에 종목이 하나만
    # 늘어도 정렬 위치가 밀려 모든 종목이 다른 조각으로 간다(라운드 73 이
    # backfill_subscores 에서 고친 것과 같은 함정). 여기는 done 을 전체
    # glob 으로 읽어 와서 구멍이 안 났을 뿐, 분할 자체는 같은 결함이었다.
    tks = [t for t in sorted(by_tk)
           if zlib.crc32(t.encode()) % shards == shard]
    done = load_done()
    out_path = os.path.join(P, f'bar_paths_s{shard}.jsonl')
    total_rows = sum(len(v) for t, v in by_tk.items() if t in set(tks))
    print(f'조각 {shard}/{shards} — 종목 {len(tks)} · 행 {total_rows:,} · '
          f'이미 완료 {len(done):,}')

    eng = be.BitemporalEngine()
    t0, wrote, skip_tk = time.time(), 0, 0
    with open(out_path, 'a', encoding='utf-8') as out:
        for i, tk in enumerate(tks):
            todo = [(d, px) for d, px in sorted(by_tk[tk].items())
                    if (tk, d) not in done]
            if not todo:
                continue
            try:
                # 반환은 (일봉 df, 재무 df) 튜플이다 — 첫 실행에서 df 로
                # 착각해 98종목 전부 조용히 건너뛰었다. 실패는 삼키되
                # **집계로는 남긴다**.
                df, _fund = eng.load_bitemporal_data(tk,
                                                     start_date='2014-01-01')
            except Exception:                                  # noqa: BLE001
                skip_tk += 1
                continue
            if df is None or len(df) < 30:
                skip_tk += 1
                continue
            dates = list(df['trade_date'].astype(str).str[:10])
            idx = {d: j for j, d in enumerate(dates)}
            O = df['open_raw'].astype(float).tolist()
            H = df['high_raw'].astype(float).tolist()
            L = df['low_raw'].astype(float).tolist()
            C = df['adj_close'].astype(float).tolist()
            V = df['volume'].astype(float).tolist()
            for d, px in todo:
                j = idx.get(d)
                if j is None:
                    # 신호일이 봉에 없으면 다음 거래일을 찾는다 (주말 신호)
                    later = [k for k, dd in enumerate(dates) if dd > d]
                    if not later:
                        continue
                    j = later[0] - 1
                seg = range(j + 1, min(j + 1 + BARS, len(dates)))
                # 볼륨은 신호일 거래량 대비 배율 (라운드 57 명세 — 거래량
                # 이탈형 Exit 후보 연구에 필요). 신호일 거래량이 0이면
                # 배율을 지어내지 않고 None.
                # 시가(라운드 57b)는 '다음 날 시가 체결'을 실측하기 위해
                # 필요하다 — 종가 체결 가정은 갭 상승 장에서 즉시 매수
                # EV 를 부풀린다.
                v0 = V[j] if j < len(V) and V[j] > 0 else None
                bars = [[dates[k],
                         round(H[k] / px * 100 - 100, 3),
                         round(L[k] / px * 100 - 100, 3),
                         round(C[k] / px * 100 - 100, 3),
                         (round(V[k] / v0, 2) if v0 else None),
                         (round(O[k] / px * 100 - 100, 3)
                          if O[k] > 0 else None)]
                        for k in seg]
                if not bars:
                    continue          # 신호 직후 봉이 아직 없다 (최근 신호)
                out.write(json.dumps(
                    {'ticker': tk, 'date': d, 'price': px,
                     'bars': bars, 'n_bars': len(bars)},
                    ensure_ascii=False) + '\n')
                wrote += 1
            out.flush()
            if (i + 1) % 10 == 0:
                el = time.time() - t0
                print(f'  종목 {i + 1}/{len(tks)} · 기록 {wrote:,}행 · '
                      f'{el:,.0f}s · 수신실패 {skip_tk}')
    print(f'\n완료 — 기록 {wrote:,}행 · 수신 실패 종목 {skip_tk}')
    print(f'저장: {out_path} (고·저·종가는 기준가 대비 %)')


if __name__ == '__main__':
    main()
