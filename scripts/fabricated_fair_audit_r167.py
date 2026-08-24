# -*- coding: utf-8 -*-
"""가짜 적정가가 몇 종목에 나가고 있었나 (라운드 167 — 영향 범위).

■ 무엇이 있었나
  `generate_synthetic_bitemporal_data` 가 **처음 보는 종목**에
  `{"eps":5000.0,"bps":45000.0,"pbr":1.5,"roe":12.0,"debt":40.0}` 라는
  리터럴을 기본값으로 넣고 있었다. DB 를 채우는 호출이 **바로 다음 줄**
  이라, 읽고 나서 채우는 순서 문제였다.

  그 결과 재무가 공시되지 않는 종목은 전부 **같은 가짜 적정가**를 받았다
  (실측: 롯데리츠·SK리츠 모두 52,713.75원 · 신뢰도 70.8 · CALIBRATED).

■ 여기서 재는 것
  **몇 종목이 그 값을 받았는가.** 고친 뒤 값과 대조한다.
  자식 프로세스를 종목마다 새로 띄운다 — 한 프로세스에서 이어 돌리면
  DB 가 데워져 결함이 가려진다(그것이 이 결함을 여태 못 본 이유다).

    C:/Python314/python.exe scripts/fabricated_fair_audit_r167.py [--limit 120]
"""
import argparse
import io
import json
import os
import subprocess
import sys
from datetime import datetime

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
os.chdir(PROJ)

OUT = os.path.join(PROJ, 'data', 'fabricated_fair_audit_r167.json')
#: 가짜 기본값(eps 5000 · bps 45000 · pbr 1.5 · roe 12.0)이 만들어 낸 값.
#: 실측으로 확인한 상수다 — 추정이 아니다.
FAKE_FAIR = 52713.75

CHILD = r'''
import os, sys, json
PROJ = sys.argv[1]; sym = sys.argv[2]
sys.path.insert(0, PROJ); os.chdir(PROJ)
import bitemporal_engine as be, quant_indicators as qi
out = {}
try:
    eng, q = be.BitemporalEngine(), qi.QuantIndicatorsEngine()
    px, fd = eng.generate_synthetic_bitemporal_data(symbol=sym,
                                                    start_date='2022-01-01')
    tech = q.compute_technical_indicators(px)
    v = q.evaluate_valuation_metric(tech, fd, symbol=sym)
    lf = fd.iloc[-1].to_dict() if (fd is not None and len(fd)) else {}
    sm = be.STOCK_METRICS_DB.get(sym) or {}
    out = {'fair': v.get('displayed_fair_value'),
           'status': v.get('fair_value_status'),
           'conf': v.get('fair_value_confidence'),
           'fd_bps': lf.get('bps'), 'fd_pbr': lf.get('pbr'),
           'fd_roe': lf.get('roe'),
           # 이 둘이 없으면 **고치기 전에는 가짜 기본값을 받던 종목**이다.
           'db_bps': sm.get('bps'), 'db_eps': sm.get('eps'),
           'is_fund': bool(sm.get('is_fund'))}
except Exception as e:
    out = {'error': f'{type(e).__name__}: {e}'[:80]}
sys.stdout.write('@@' + json.dumps(out))
'''


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def cold(sym, child_path):
    try:
        r = subprocess.run([sys.executable, child_path, PROJ, sym],
                           capture_output=True, text=True, encoding='utf-8',
                           errors='replace', timeout=300)
        tag = (r.stdout or '').rsplit('@@', 1)
        return json.loads(tag[1]) if len(tag) == 2 else {'error': '결과 없음'}
    except Exception as e:                                     # noqa: BLE001
        return {'error': f'{type(e).__name__}: {e}'[:60]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=120)
    a = ap.parse_args()

    print('가짜 적정가 영향 범위 (라운드 167)')
    print('종목마다 **새 프로세스**로 잰다 — 이어 돌리면 결함이 가려진다\n')

    child = os.path.join(PROJ, '_probe', '_cold_child_r167.py')
    os.makedirs(os.path.dirname(child), exist_ok=True)
    with open(child, 'w', encoding='utf-8') as f:
        f.write(CHILD)

    with open(os.path.join(PROJ, '.portfolio', 'name_master.json'),
              encoding='utf-8') as f:
        rows = (json.load(f).get('rows') or [])[:a.limit]

    hit, ok, err, would = [], [], [], []
    for i, r in enumerate(rows, 1):
        c = str(r.get('code'))
        sym = f"{c}.KQ" if str(r.get('mkt')) == 'KOSDAQ' else f"{c}.KS"
        d = cold(sym, child)
        if d.get('error'):
            err.append((c, r.get('name'), d['error']))
        else:
            if d.get('fair') and abs(float(d['fair']) - FAKE_FAIR) < 1.0:
                hit.append((c, r.get('name'), d))
            else:
                ok.append(c)
            # 고치기 **전이라면** 가짜 기본값을 받았을 종목:
            # 게시 BPS·EPS 가 둘 다 없고 펀드도 아닌 것
            if (d.get('db_bps') in (None, 0) and d.get('db_eps') in (None, 0)
                    and not d.get('is_fund')):
                would.append((c, r.get('name'), d))
        if i % 20 == 0 or i == len(rows):
            print(f'   {i:>4}/{len(rows)}  가짜값 {len(hit)} · 정상 {len(ok)} · '
                  f'오류 {len(err)} · 영향권 {len(would)}')

    n_ok = max(1, len(rows) - len(err))
    print(f'\n■ 지금(고친 뒤) 가짜 적정가 {len(hit)}종목 — '
          f'{"0 이어야 정상" if not hit else "← 남아 있다"}')
    print(f'■ 고치기 **전이라면** 가짜값을 받았을 종목 {len(would)} / {n_ok} '
          f'({len(would) / n_ok * 100:.1f}%)')
    for c, n, d in would[:15]:
        print(f"   {c} {str(n)[:20]:22} 지금 적정 "
              f"{(d['fair'] or 0):>10,.0f} · {d['status']} "
              f"(전에는 {FAKE_FAIR:,.0f} · CALIBRATED 였다)")

    doc = {'made': datetime.now().strftime('%Y-%m-%d'),
           'fake_fair': FAKE_FAIR, 'sampled': len(rows),
           'fabricated_now': len(hit), 'clean': len(ok), 'errors': len(err),
           'would_have_been_fabricated': len(would),
           'affected_pct': round(len(would) / n_ok * 100, 1),
           'affected_list': [{'code': c, 'name': n, **d} for c, n, d in would],
           'note': ('"영향권" 은 게시 BPS·EPS 가 둘 다 없는 종목이다 — '
                    '고치기 전에는 그 종목들이 전부 같은 가짜 적정가 '
                    f'{FAKE_FAIR:,.0f}원(신뢰도 70.8 · CALIBRATED)을 받았다. '
                    '0 건이 미측정이 아니라는 것은 sampled 로 확인한다.')}
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f'\n저장: {OUT}')
    try:
        os.remove(child)
    except OSError:
        pass
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
