# -*- coding: utf-8 -*-
"""
업종별 원장 실측 성적 생성 (라운드 54b).

업황 카드가 지금은 프록시 모멘텀(현재 상태)만 말한다. 여기에 **이 업종의
매수권 신호가 과거에 실제로 얼마나 맞았는가**를 병기할 재료를 만든다.

  · 원장 개발 구간(train+valid) 매수권(58+) · 판정완료 행만
  · 업종은 **원장 행의 sector 를 먼저**, 없으면 백필 패치 (라운드 217 —
    종전엔 패치만 봐서 R72 이후 행이 전부 빠졌다 · R73 의 규칙과 같게)
  · 블라인드는 읽지 않는다
  · n < 30 업종은 기록하되 화면에서 Wilson 하한과 함께 '표본 부족' 표기

출력: data/sector_perf.json — 표시 전용. 점수·게이트에 쓰지 않는다.
"""
import glob
import io
import json
import math
import os
import sys

try:                       # 라운드 103 — 객체를 갈아끼우지 않는다
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:          # noqa: BLE001
    pass
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(PROJ, '.portfolio')
COST = 0.36


def _today():
    """오늘 날짜 — 라운드 107. 박아 두면 다시 만들어도
    안 바뀌어 낡음을 알 수 없다 (라운드 102 miss_study).
    """
    import datetime as _dt
    return _dt.date.today().isoformat()


def wilson_low(k, n, z=1.96):
    if n == 0:
        return 0.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - m) / d * 100.0


def _code(tk):
    return str(tk or '').split('.')[0][:6]


patch = {}
by_ticker = {}                         # 코드 → 그 종목에 기록된 업종 집합
for path in sorted(glob.glob(os.path.join(P, 'subscore_patch*.jsonl'))):
    with open(path, encoding='utf-8') as f:
        for ln in f:
            try:
                q = json.loads(ln)
                patch[(q['ticker'], q['date'])] = q.get('sector')
                if q.get('sector'):
                    by_ticker.setdefault(_code(q['ticker']), set()).add(q['sector'])
            except Exception:                                  # noqa: BLE001
                continue

LEDGER = os.path.join(P, 'virtual_graded.jsonl')


def _rows():
    with open(LEDGER, encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                yield json.loads(ln)
            except Exception:                                  # noqa: BLE001
                continue


# ── 종목 단위 업종 — 라운드 218 ────────────────────────────────────────────
#   R217 이 '패치만 읽던' 것을 고쳐 n 합이 36,299 → 81,646 이 됐는데, 그래도
#   개발구간 매수권 98,600행 중 16,954(17%)가 빠졌다. 정체를 실측해 보니
#   ETF(구조상 업종 없음) 2,697행뿐이고 **14,102행(83%)은 보통주인데 같은
#   종목의 다른 행에는 업종이 있었다** — 행마다 따로 물어서 빠진 것이다.
#   업종은 날짜가 아니라 **종목의 성질**이므로 종목 단위로 채운다.
#   ⚠️ 다만 기록된 업종이 둘 이상인 종목(재분류·라벨 흔들림)은 **채우지
#      않는다** — 어느 쪽인지 모르는 것을 고르면 그게 지어내는 것이다(§3).
for r in _rows():
    if r.get('sector'):
        by_ticker.setdefault(_code(r.get('ticker')), set()).add(r['sector'])
ticker_sec = {c: next(iter(s)) for c, s in by_ticker.items() if len(s) == 1}
ambiguous = {c for c, s in by_ticker.items() if len(s) > 1}

etf_codes = set()
try:
    with open(os.path.join(PROJ, 'data', 'etf_index.json'), encoding='utf-8') as f:
        etf_codes = set(json.load(f).get('map') or {})
except Exception:                                              # noqa: BLE001
    etf_codes = set()                  # 없으면 ETF 를 '미상'으로 센다 — 지어내지 않는다

agg = {}
cov = dict(rows_eligible=0, by_row=0, by_patch=0, by_ticker=0,
           miss_etf=0, miss_ambiguous=0, miss_unknown=0)
for r in _rows():
    if r.get('split') == 'blind' or r.get('outcome') == 'OPEN':
        continue
    if float(r.get('score') or 0) < 58.0:
        continue
    cov['rows_eligible'] += 1
    # ⚠️ 라운드 217 — 여기가 **패치만** 봤다. 라운드 72 이후 랩은 업종을
    #   원장 행에 직접 쓰고 패치는 그 전 60,462건용이다 — R73 이 표본
    #   감사(`sample_audit.load_sectors`)에서 고친 바로 그 결함이 여기
    #   남아 있었다. 그래서 원장이 250,725행이 돼도 이 표는 옛 60k 행만
    #   세고 있었다(반도체 n 5,750 → 다시 만들어도 5,751). 행의 업종을
    #   먼저, 없으면 패치, 없으면 **같은 종목의 업종**(라운드 218) —
    #   출처를 세어 산출물에 적는다.
    code = _code(r.get('ticker'))
    sec = r.get('sector')
    if sec:
        cov['by_row'] += 1
    else:
        sec = patch.get((str(r.get('ticker')), str(r.get('date'))[:10]))
        if sec:
            cov['by_patch'] += 1
        else:
            sec = ticker_sec.get(code)
            if sec:
                cov['by_ticker'] += 1
            else:
                cov['miss_etf' if code in etf_codes else
                    'miss_ambiguous' if code in ambiguous else
                    'miss_unknown'] += 1
                continue
    a = agg.setdefault(sec, dict(n=0, k=0, net=0.0))
    a['n'] += 1
    a['k'] += 1 if r.get('success') else 0
    a['net'] += float(r.get('return_pct') or 0) - COST

_cov_n = cov['by_row'] + cov['by_patch'] + cov['by_ticker']
cov['covered'] = _cov_n
cov['covered_pct'] = round(_cov_n / max(1, cov['rows_eligible']) * 100, 1)

out = {}
for sec, a in agg.items():
    out[sec] = dict(
        n=a['n'], hit=round(a['k'] / a['n'] * 100, 1),
        wilson_low=round(wilson_low(a['k'], a['n']), 1),
        ev=round(a['net'] / a['n'], 3),
        small=a['n'] < 30)

doc = dict(
    made=_today(), basis='개발 구간(train+valid) 매수권 58+ · 판정완료 · '
    '블라인드 미포함 · 비용 0.36%p 차감',
    note='표시 전용 — 점수·게이트에 사용하지 않는다 (라운드 44 결정 유지)',
    # 라운드 218 — **무엇이 빠졌는지 세어 적는다.** 이 표는 업종을 아는 행만
    #   담는다. 그 사실을 산출물이 말하지 않으면 화면은 전수처럼 보인다(§3).
    coverage=cov,
    coverage_note='업종 출처: 원장 행 → 하위점수 패치 → 같은 종목의 업종'
                  '(라운드 218). 빠진 것은 ETF(구조상 업종 없음) · 업종이 두 '
                  '가지로 기록된 종목(모르는 것을 고르지 않는다) · 한 번도 못 '
                  '받은 종목이다.',
    sectors=out)
dst = os.path.join(PROJ, 'data', 'sector_perf.json')
with open(dst, 'w', encoding='utf-8') as f:
    json.dump(doc, f, ensure_ascii=False, indent=1)
print(f'업종 {len(out)}개 → {dst}')
print(f"  커버리지 {cov['covered']:,}/{cov['rows_eligible']:,}"
      f" ({cov['covered_pct']}%) — 행 {cov['by_row']:,} · 패치 "
      f"{cov['by_patch']:,} · 종목 {cov['by_ticker']:,}")
print(f"  빠짐: ETF {cov['miss_etf']:,} · 업종 중복기록 "
      f"{cov['miss_ambiguous']:,} · 미상 {cov['miss_unknown']:,}")
for sec, v in sorted(out.items(), key=lambda x: -x[1]['n'])[:12]:
    print(f"  {sec:14s} n {v['n']:5,} · 적중 {v['hit']:5.1f}% "
          f"(W하한 {v['wilson_low']:5.1f}) · EV {v['ev']:+.3f}"
          + ('  [표본 부족]' if v['small'] else ''))
