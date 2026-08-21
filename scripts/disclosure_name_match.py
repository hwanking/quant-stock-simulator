# -*- coding: utf-8 -*-
"""공시 회사명 → 종목코드 매칭 품질을 잰다 (라운드 146).

이벤트 연구(R124 §3.2)의 조인 기반이 이 매칭이다. 공시 목록(DART
전체공시)에는 종목코드가 없고 **회사명뿐**이라(R139), 이름이 코드에
붙는 비율과 어디서 틀리는지를 **측정 전에 잣대를 적고** 잰다.

잣대 (측정 전에 정한 것 — 이 독스트링이 사전등록이다):
  ① 매칭 방법 두 단계 — 정확 일치, 정규화 일치(공백·㈜·주식회사 제거,
     영문 대문자화). 유사도(편집거리) 매칭은 **안 쓴다** — 동명 오염이
     조용히 늘어나는 길이다.
  ② 주 잣대는 **원장 방향**이다: 원장 유니버스 1,500 티커 중 이름이
     붙는 비율, 그리고 그 이름들이 공시에서 잡히는 건수. 공시 전체
     매칭률은 참고로만 본다 — DART 에는 비상장·SPC·대부업체 공시도
     있어 낮은 것이 정상이다.
  ③ 연도별로 가른다 (R145 §9 — 크기를 말할 때는 표본의 끝을 먼저).
     옛 구간은 사명 변경 때문에 **현재 이름 마스터**로는 덜 붙을
     것이다 — 그 낙차를 정확히 적는 것이 이 측정의 목적이다.
  ④ 충돌(정규화 후 한 이름 → 복수 코드)은 건수를 적고, 이벤트 연구
     에서 그 이름들을 **제외**할 수 있게 목록을 남긴다. 보통주 우선
     같은 임의 해소 규칙을 만들지 않는다 — §2 (숫자를 손으로 고르지
     않는다)의 이름판이다.

이름 마스터: FDR KRX 현재 상장 + KRX-DELISTING(상폐·사명 변경 이력).
스냅샷을 .portfolio/name_master.json 에 저장해 재현 가능하게 한다.

측정 전용 — 점수·게이트·문턱을 바꾸지 않는다. 운영 코드에 매칭을
넣지 않는다 (이벤트 연구 사전등록이 쓸 재료다).

    C:/Python314/python.exe scripts/disclosure_name_match.py
"""
import collections
import io
import json
import os
import re
import sys
from datetime import date, datetime, timezone

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
OUT = os.path.join(PROJ, 'data', 'disclosure_name_match.json')
MASTER = os.path.join(PROJ, '.portfolio', 'name_master.json')
SRC = os.path.join(PROJ, '.portfolio', 'disclosures_daily.jsonl')
UNIV = os.path.join(PROJ, '.portfolio', 'universe_top1500.json')

_STRIP = re.compile(r'\s+|㈜|\(주\)|주식회사')


def norm(name):
    """정규화 — 공백·법인 표기 제거, 영문 대문자화. 그 이상은 안 간다."""
    return _STRIP.sub('', str(name)).upper()


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def build_master():
    """이름 마스터를 받거나(없으면) 스냅샷에서 읽는다."""
    if os.path.exists(MASTER):
        with open(MASTER, encoding='utf-8') as f:
            return json.load(f)
    import FinanceDataReader as fdr
    cur = fdr.StockListing('KRX')
    rows = [dict(code=str(r.Code), name=str(r.Name), mkt=str(r.Market),
                 live=True)
            for r in cur.itertuples()]
    try:
        dl = fdr.StockListing('KRX-DELISTING')
        for r in dl.itertuples():
            nm = str(r.Name)
            if not nm or nm == 'nan':
                continue
            rows.append(dict(code=str(r.Symbol), name=nm,
                             mkt=str(r.Market), live=False,
                             delisted=str(getattr(r, 'DelistingDate', ''))[:10]))
    except Exception as e:                                     # noqa: BLE001
        print(f'   (상폐 목록 실패 — 현재 상장만 쓴다: {type(e).__name__})')
    # ETF 는 DART 공시의 발행 주체가 아니다(운용사가 공시한다). 유니버스를
    # 주식/ETF 로 가르기 위해 코드만 담는다 — 이름 매칭에는 안 쓴다.
    etf_codes = []
    try:
        etf = fdr.StockListing('ETF/KR')
        etf_codes = sorted({str(r.Symbol) for r in etf.itertuples()})
    except Exception as e:                                     # noqa: BLE001
        print(f'   (ETF 목록 실패 — 유니버스를 못 가른다: {type(e).__name__})')
    doc = {'made': date.today().isoformat(), 'rows': rows,
           'etf_codes': etf_codes}
    with open(MASTER, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False)
    return doc


def main():
    print('공시 회사명 → 종목코드 매칭 품질 (라운드 146)')
    print('측정 전용 — 점수·게이트·문턱을 바꾸지 않는다')
    print()

    m = build_master()
    rows = m['rows']
    live_rows = [r for r in rows if r.get('live')]
    print(f"■ 이름 마스터: {len(rows):,}행 "
          f"(현재 {len(live_rows):,} · 상폐 {len(rows) - len(live_rows):,}) "
          f"— 스냅샷 {m['made']}")

    # 이름 → 코드 집합 (정확·정규화 각각). live 를 우선 대지 않는다 —
    # 충돌은 해소하지 않고 **적는다**.
    exact = collections.defaultdict(set)
    normed = collections.defaultdict(set)
    for r in rows:
        exact[r['name']].add(r['code'])
        normed[norm(r['name'])].add(r['code'])
    collide = {k: sorted(v) for k, v in normed.items() if len(v) > 1}

    # 원장 유니버스 → 이름. ETF 를 먼저 가른다 — ETF 는 DART 공시의
    # 발행 주체가 아니므로(운용사가 공시) 안 붙는 것이 정상이다.
    with open(UNIV, encoding='utf-8') as f:
        univ = [s.split('.')[0] for s in json.load(f)['symbols']]
    etf_set = set(m.get('etf_codes') or [])
    univ_etf = [c for c in univ if c in etf_set]
    univ_stk = [c for c in univ if c not in etf_set]
    code2live = {r['code']: r['name'] for r in live_rows}
    code2any = {}
    for r in rows:                       # 상폐 포함 — 나중 것이 덮지 않게
        code2any.setdefault(r['code'], r['name'])
    univ_named = [c for c in univ_stk if c in code2live]
    univ_any = [c for c in univ_stk if c in code2live or c in code2any]

    # 공시 이름 × 연도
    per_year = collections.defaultdict(
        lambda: {'n': 0, 'exact': 0, 'norm': 0, 'univ': 0})
    uniq = collections.Counter()
    univ_norm_names = {norm(nm) for c, nm in code2live.items()
                       if c in set(univ)}
    total = 0
    with open(SRC, encoding='utf-8', errors='replace') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:                                  # noqa: BLE001
                continue
            nm = str(r.get('name') or '')
            d = str(r.get('day') or '')[:4]
            if not nm or len(d) < 4:
                continue
            total += 1
            uniq[nm] += 1
            b = per_year[d]
            b['n'] += 1
            if nm in exact:
                b['exact'] += 1
            if norm(nm) in normed:
                b['norm'] += 1
            if norm(nm) in univ_norm_names:
                b['univ'] += 1

    # 고유명 기준
    u_exact = sum(1 for nm in uniq if nm in exact)
    u_norm = sum(1 for nm in uniq if norm(nm) in normed)
    n_exact = sum(c for nm, c in uniq.items() if nm in exact)
    n_norm = sum(c for nm, c in uniq.items() if norm(nm) in normed)

    print()
    print(f"■ 공시 {total:,}건 · 고유 회사명 {len(uniq):,}개")
    print(f"   고유명 매칭  정확 {u_exact / len(uniq) * 100:.1f}% · "
          f"정규화 {u_norm / len(uniq) * 100:.1f}%")
    print(f"   건수 매칭    정확 {n_exact / total * 100:.1f}% · "
          f"정규화 {n_norm / total * 100:.1f}%")
    print(f"   (전체가 100% 일 이유가 없다 — DART 에는 비상장·SPC·"
          f"대부업체 공시가 섞여 있다)")

    print()
    print(f"■ 주 잣대 — 원장 방향")
    print(f"   유니버스 {len(univ):,} = 주식 {len(univ_stk):,} + "
          f"ETF {len(univ_etf):,} (ETF 는 DART 공시 주체가 아니라 제외)")
    print(f"   주식 {len(univ_stk):,} 중 현재 이름이 붙는 것 "
          f"{len(univ_named):,} ({len(univ_named) / len(univ_stk) * 100:.1f}%)"
          f" · 상폐 포함 {len(univ_any):,}"
          f" ({len(univ_any) / len(univ_stk) * 100:.1f}%)")

    years = []
    print()
    print(f'{"연도":>6}{"건수":>10}{"정규화":>8}{"원장교집합":>10}')
    for y in sorted(per_year):
        b = per_year[y]
        nr = round(b['norm'] / b['n'] * 100, 1)
        ur = round(b['univ'] / b['n'] * 100, 1)
        years.append(dict(year=y, n=b['n'], norm_pct=nr, univ_pct=ur))
        print(f'{y:>6}{b["n"]:>10,}{nr:>7.1f}%{ur:>9.1f}%')

    full = [x for x in years if x['n'] >= 50000]     # 부분 해 제외(대략)
    head = {}
    if full:
        head = dict(
            uniq_names=len(uniq),
            uniq_exact_pct=round(u_exact / len(uniq) * 100, 1),
            uniq_norm_pct=round(u_norm / len(uniq) * 100, 1),
            case_exact_pct=round(n_exact / total * 100, 1),
            case_norm_pct=round(n_norm / total * 100, 1),
            univ_total=len(univ), univ_stocks=len(univ_stk),
            univ_etf=len(univ_etf), univ_named=len(univ_named),
            univ_named_pct=round(len(univ_named) / len(univ_stk) * 100, 1),
            univ_any=len(univ_any),
            univ_any_pct=round(len(univ_any) / len(univ_stk) * 100, 1),
            collisions=len(collide),
            norm_min_year=min(full, key=lambda x: x['norm_pct'])['year'],
            norm_min_pct=min(x['norm_pct'] for x in full),
            norm_max_pct=max(x['norm_pct'] for x in full),
        )
        print()
        print(f"■ 정규화 매칭의 연도 범위(온전한 해): "
              f"{head['norm_min_pct']:.1f}% ~ {head['norm_max_pct']:.1f}%"
              f" (최저 {head['norm_min_year']})")
    print(f"■ 정규화 충돌(한 이름 → 복수 코드): {len(collide):,}개 이름")

    doc = {
        'made': date.today().isoformat(),
        'made_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'question': '공시 회사명이 종목코드에 얼마나 붙는가 (이벤트 조인 기반)',
        'master_snapshot': m['made'],
        'master_rows': len(rows),
        'rows_total': total,
        'headline': head,
        'years': years,
        'collision_names_sample': dict(list(collide.items())[:40]),
        'note': ('측정 전용 — 점수·게이트·문턱을 바꾸지 않는다. '
                 '유사도 매칭은 쓰지 않는다. 충돌은 해소하지 않고 적는다.'),
    }
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print()
    print(f'저장: {OUT}')
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
