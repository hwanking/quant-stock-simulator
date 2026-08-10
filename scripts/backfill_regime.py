# -*- coding: utf-8 -*-
"""
라운드 73 — 국면 미기록 채우기 (지수 봉 수가 모자랐다).

■ 무엇이 문제였나
  원장 181,959건 중 47.6%에 국면(regime)이 없었다. 실측해 보니
  **2021-12-08 이전이 100% 미기록, 그 이후가 0%** — 종목이나 시장 문제가
  아니라 순수한 날짜 절단이었다.

  `calibration_lab.regime_at()` 이 지수를 `fetch_index_daily(mkt, 1200)`
  으로 받는다. 1,200 거래일은 약 4.8년이라 그보다 옛 판정에는 붙일 국면이
  없었다. 지수도 종목과 같은 3,000봉 천장(2014-05-20~)까지 나오므로
  거기까지 받으면 2015년 이후가 전부 채워진다.

■ 여기서 하는 일
  이미 쌓인 **원본**(virtual_predictions*.jsonl)의 regime 을 채운다.
  산출물(virtual_graded.jsonl)은 원본에서 다시 만들어지므로 원본을 고쳐야
  한다 — 라운드 71c 에서 배운 것이다: 산출물만 손대면 다음 채점에 지워진다.

■ 누출 없음
  각 행의 날짜 **이하**로 지수를 자른 뒤 판정한다. 규칙은 calibration_lab
  의 regime_at 과 같다 (p>s20>s60 → BULL, p<s20 이고 p<s60 → BEAR,
  나머지 SIDEWAYS). 새 규칙을 만들지 않는다.

    C:/Python314/python.exe scripts/backfill_regime.py            # 미리보기
    C:/Python314/python.exe scripts/backfill_regime.py --apply
"""
import glob
import io
import json
import os
import shutil
import sys
import warnings

warnings.filterwarnings('ignore')
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
P = os.path.join(PROJ, '.portfolio')

INDEX_BARS = 3000
MISSING = (None, 'None', '')


def _utf8_stdout():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def build_regime_lookup():
    """시장별 {날짜: 국면} — 그 날짜까지의 지수만 보고 판정한다."""
    import numpy as np
    import bitemporal_engine as be

    eng = be.BitemporalEngine()
    out = {}
    for mkt in ('KOSPI', 'KOSDAQ'):
        s = eng.fetch_index_daily(mkt, INDEX_BARS)
        if s is None:
            print(f'  {mkt} 지수 미수신 — 이 시장은 못 채운다')
            out[mkt] = {}
            continue
        dates, closes = s
        closes = np.asarray(closes, dtype=float)
        table = {}
        for i in range(len(closes)):
            if i < 59:
                continue                     # 60일 평균이 성립해야 판정한다
            p = float(closes[i])
            s20 = float(closes[i - 19:i + 1].mean())
            s60 = float(closes[i - 59:i + 1].mean())
            if p > s20 > s60:
                rg = 'BULL'
            elif p < s20 and p < s60:
                rg = 'BEAR'
            else:
                rg = 'SIDEWAYS'
            d = str(dates[i])[:10].replace('-', '')
            table[f'{d[:4]}-{d[4:6]}-{d[6:8]}'] = rg
        out[mkt] = table
        ks = sorted(table)
        print(f'  {mkt} 국면표 {len(table):,}일 · {ks[0]} ~ {ks[-1]}')
    return out


def main():
    apply = '--apply' in sys.argv
    files = sorted(glob.glob(os.path.join(P, 'virtual_predictions*.jsonl')))
    if not files:
        print('원본이 없다 — 채울 것이 없다. 통과가 아니라 미측정이다.')
        return 1

    print('■ 국면표 만들기 (지수 3,000봉)')
    look = build_regime_lookup()
    if not any(look.values()):
        print('국면표가 비었다 — 채우지 않는다.')
        return 1

    total = filled = already = nodata = 0
    per_file = {}
    for path in files:
        rows, chg = [], 0
        with open(path, encoding='utf-8') as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                total += 1
                try:
                    r = json.loads(ln)
                except Exception:                              # noqa: BLE001
                    rows.append(ln)
                    continue
                if r.get('regime') not in MISSING:
                    already += 1
                    rows.append(ln)
                    continue
                mkt = str(r.get('market') or '')
                d = str(r.get('date'))[:10]
                rg = (look.get(mkt) or {}).get(d)
                if rg is None:
                    nodata += 1
                    rows.append(ln)
                    continue
                r['regime'] = rg
                filled += 1
                chg += 1
                rows.append(json.dumps(r, ensure_ascii=False))
        per_file[os.path.basename(path)] = chg
        if apply and chg:
            shutil.copyfile(path, path + '.bak')
            with open(path, 'w', encoding='utf-8') as out:
                for ln in rows:
                    out.write(ln + '\n')

    print(f'\n■ 결과 (원본 {len(files)}개 · {total:,}줄)')
    print(f'  이미 있음  {already:>8,}')
    print(f'  채울 수 있음 {filled:>7,}')
    print(f'  지수 없음  {nodata:>8,}  (2014-05 이전 등 — 지어내지 않는다)')
    for k, v in per_file.items():
        if v:
            print(f'    {k}: {v:,}건')
    if not apply:
        print('\n미리보기다. 실제로 채우려면 --apply (원본은 .bak 로 남는다).')
    else:
        print('\n채웠다. 다음 채점(`calibration_lab.py`)부터 원장에 반영된다.')
    return 0


if __name__ == '__main__':
    _utf8_stdout()
    sys.exit(main())
