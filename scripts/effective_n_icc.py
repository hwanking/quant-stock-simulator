# -*- coding: utf-8 -*-
"""라운드 80 — 유효표본을 **상관으로** 다시 센다 (관측 전용).

■ 지금 쓰는 잣대와 그 한계
  `sample_audit` 의 ⑤는 "같은 날 같은 섹터는 같이 움직인다"고 보고
  (날짜×업종) 쌍을 센다. 라벨을 믿는 방식이라 두 군데서 샌다 —
  섹터가 없는 종목(ETF·리츠)은 아예 못 묶고, 섹터가 달라도 같이 움직이는
  종목은 따로 센다.

■ 왜 상관 문턱을 안 쓰나 (§2)
  "ρ>0.7 이면 한 군집" 같은 문턱은 **손으로 고른 숫자**다. 대신 군집을
  만들지 않고 **설계효과(design effect)** 를 그대로 쓴다:

      ICC   = 날짜간 분산 / (날짜간 분산 + 날짜내 분산)
      n_eff = N / (1 + (n̄ − 1) × ICC)

  둘 다 교과서 정의이고 새 숫자가 없다. ICC 는 실측하고, n̄ 은 날짜당
  평균 케이스 수다. 문턱을 고르는 대신 **측정된 상관을 그대로 반영**한다.

■ 무엇을 바꾸지 않나
  점수·게이트·문턱을 건드리지 않는다. 이 값은 "우리 표본이 실제로 몇
  개인가"를 정직하게 적기 위한 것이고, 사전등록 하한을 다시 쓰는 데
  쓰인다 (전방 재평가 2026-11-16 이후).

    C:/Python314/python.exe scripts/effective_n_icc.py
"""
import glob
import io
import json
import os
import sys
from collections import defaultdict

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(PROJ, '.portfolio', 'virtual_graded.jsonl')
OUT = os.path.join(PROJ, 'data', 'effective_n_icc.json')

BUY_ZONE = 58          # 채택된 매수권 문턱 (새 숫자 아님)
#: 화면에 ICC 를 띄울 최소 raw 표본 — **새 숫자가 아니다.**
#: R55 §3 이 측정 전에 고정한 칸 하한 200 을 그대로 재사용한다
#: ("Wilson 폭 ±7%p 수준"). 그 아래 업종은 재기는 하되 화면이 안 쓴다.
REPORT_N_FLOOR = 200

MIN_PER_DATE = 5       # 날짜내 분산을 재려면 한 날에 최소 2건은 있어야 한다.
#: 5 는 문턱이 아니라 **정의상 하한**이다 — 1건뿐인 날은 날짜내 분산이
#: 존재하지 않아 ICC 계산에 기여할 수 없다. 넉넉히 5로 둔 값이며,
#: 아래에서 2·5·10 을 모두 찍어 결과가 이 선택에 흔들리는지 보인다.


def _today():
    """오늘 날짜 — 라운드 107. 박아 두면 다시 만들어도
    안 바뀌어 낡음을 알 수 없다 (라운드 102 miss_study).
    """
    import datetime as _dt
    return _dt.date.today().isoformat()


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def load(path=LEDGER):
    """원장 + **하위점수 패치**를 합쳐 읽는다.

    ⚠️ 라운드 99 — 여기가 원장만 읽고 있었다.
      섹터는 원장 행에 직접 있는 것이 **29.9%** 뿐이고 나머지 60.2%p 는
      패치 파일(`subscore_patch*.jsonl`)에만 있다. 옛 케이스는 백필로
      뒤에 채웠고 병합 단계가 없기 때문이다.

      그래서 by_sector 가 원장만 보면 **업종별 표본이 1/3로 잘린다.**
      게다가 화면이 쓰는 report 플래그가 `N >= 200`(R55 §3 하한)이라,
      실제로는 200을 넘는 업종이 못 넘는 것처럼 찍혔다 — 값이 틀린 게
      아니라 **표본이 없는 척**한 것이다.

      저장소의 다른 9개 스크립트는 전부 패치를 함께 읽는다. 반쪽만 보던
      것은 이 파일 하나였다.
    """
    rows = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:                                  # noqa: BLE001
                pass

    patch = {}
    for p in sorted(glob.glob(os.path.join(PROJ, '.portfolio',
                                           'subscore_patch*.jsonl'))):
        with open(p, encoding='utf-8', errors='replace') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    q = json.loads(line)
                except Exception:                              # noqa: BLE001
                    continue
                if q.get('sector'):
                    patch[(str(q.get('ticker')),
                           str(q.get('date'))[:10])] = q['sector']
    n_filled = 0
    for r in rows:
        if not r.get('sector'):
            s = patch.get((str(r.get('ticker')), str(r.get('date'))[:10]))
            if s:
                r['sector'] = s
                n_filled += 1
    # 조용히 채우지 않는다 — 몇 건을 어디서 가져왔는지 밝힌다
    if n_filled:
        print(f'  (패치에서 섹터 {n_filled:,}건 보충 — 원장 단독은 '
              f'{sum(1 for r in rows if r.get("sector")) - n_filled:,}건)')
    return rows


def icc_and_neff(rows, field='close_return_pct', min_per_date=MIN_PER_DATE):
    """일원분산분석(ANOVA)식 ICC 와 설계효과 보정 표본.

    반환: dict(N, dates, n_bar, icc, n_eff, ...) — 못 재면 None 을 담는다.
    **지어내지 않는다**: 표본이 모자라면 값을 만들지 않고 사유를 적는다.
    """
    by_date = defaultdict(list)
    for r in rows:
        v = r.get(field)
        if v is None:
            continue
        try:
            by_date[str(r.get('date'))[:10]].append(float(v))
        except (TypeError, ValueError):
            continue
    groups = {d: v for d, v in by_date.items() if len(v) >= min_per_date}
    if len(groups) < 2:
        return dict(N=0, dates=len(groups), n_bar=None, icc=None,
                    n_eff=None, why='날짜가 2개 미만 — ICC 정의 불가')

    N = sum(len(v) for v in groups.values())
    k = len(groups)
    grand = sum(sum(v) for v in groups.values()) / N
    # 집단간 제곱합 / 집단내 제곱합
    ssb = sum(len(v) * (sum(v) / len(v) - grand) ** 2 for v in groups.values())
    ssw = sum(sum((x - (sum(v) / len(v))) ** 2 for x in v)
              for v in groups.values())
    dfb, dfw = k - 1, N - k
    if dfb <= 0 or dfw <= 0:
        return dict(N=N, dates=k, n_bar=None, icc=None, n_eff=None,
                    why='자유도 부족')
    msb, msw = ssb / dfb, ssw / dfw
    # 불균형 집단 크기 보정 (Snedecor–Cochran n0)
    n_sum = sum(len(v) for v in groups.values())
    n_sq = sum(len(v) ** 2 for v in groups.values())
    n0 = (n_sum - n_sq / n_sum) / (k - 1)
    denom = msb + (n0 - 1) * msw
    if denom <= 0 or n0 <= 0:
        return dict(N=N, dates=k, n_bar=n_sum / k, icc=None, n_eff=None,
                    why='분산이 0 이하 — ICC 정의 불가')
    icc = (msb - msw) / denom
    icc = max(0.0, min(1.0, icc))          # 음수 ICC 는 0 으로 (관례)
    n_bar = n_sum / k
    deff = 1.0 + (n_bar - 1.0) * icc
    return dict(N=N, dates=k, n_bar=round(n_bar, 1), icc=round(icc, 4),
                design_effect=round(deff, 2),
                n_eff=round(N / deff, 1), why=None)


def by_sector(rows, min_per_date=2):
    """업종별 유효표본 — 화면이 raw n 옆에 병기할 값 (라운드 81b).

    ■ 왜 필요한가
      판정 근거 화면이 "업황 … 적중 59.6% · EV −0.07 (n 235)" 라고 적는다.
      235 는 raw 다. 같은 날 케이스는 서로 독립이 아니므로 이 숫자만 보면
      **실제보다 단단해 보인다.** 옆에 유효표본을 같이 적는다.

      값을 바꾸지 않는다 — 병기만 한다. 게이트가 아니라 표시 라벨이다.

    못 재는 업종은 **넣지 않는다** (지어내지 않는다 · §3).

    ■ 화면에 띄울 만한가 — `report` 플래그
      '광고' 업종은 raw 6건인데 ICC 0.982 가 나온다. 표본 6개짜리 상관을
      화면에 0.98 이라고 띄우면 **작은 표본으로 큰 결론**이다(라운드 27b).
      그렇다고 여기서 새 문턱을 고르지 않는다 — 이미 채택된 하한을
      재사용한다: **R55 §3 의 n ≥ 200** ("Wilson 폭 ±7%p 수준"으로
      측정 전에 고정된 값). 그 아래는 재기는 하되 `report=False` 로 두고
      화면이 안 쓴다.
    """
    per = defaultdict(list)
    for r in rows:
        s = r.get('sector')
        if s:
            per[str(s)].append(r)
    out = {}
    for s, sub in per.items():
        d = icc_and_neff(sub, min_per_date=min_per_date)
        if d.get('n_eff') is None:
            continue
        out[s] = dict(N=d['N'], dates=d['dates'], icc=d['icc'],
                      design_effect=d['design_effect'], n_eff=d['n_eff'],
                      report=bool(d['N'] >= REPORT_N_FLOOR))
    return out


def main():
    rows = load()
    print(f'원장 {len(rows):,}건')
    buy = [r for r in rows if (r.get('score') or 0) >= BUY_ZONE]
    print(f'매수권({BUY_ZONE}+) {len(buy):,}건\n')

    sets = {'전체 원장': rows, f'매수권({BUY_ZONE}+)': buy}
    result = {}
    for name, sub in sets.items():
        print(f'── {name} ──')
        per = {}
        for mpd in (2, 5, 10):
            d = icc_and_neff(sub, min_per_date=mpd)
            per[f'min{mpd}'] = d
            if d.get('icc') is None:
                print(f'   날짜당 {mpd}건+ : 산출 불가 — {d.get("why")}')
                continue
            print(f'   날짜당 {mpd:>2}건+ : 날짜 {d["dates"]:>5,} · '
                  f'N {d["N"]:>7,} · 평균 {d["n_bar"]:>6} · '
                  f'ICC {d["icc"]:.4f} · 설계효과 {d["design_effect"]:>6} '
                  f'→ 유효 {d["n_eff"]:>8,}')
        result[name] = per
        print()

    # 종전 잣대와 나란히 — 어느 쪽이 크다고 주장하지 않고 **같이** 적는다
    old = os.path.join(PROJ, 'data', 'effective_n.json')
    prev = None
    if os.path.exists(old):
        with open(old, encoding='utf-8') as f:
            prev = json.load(f)
        print('종전 잣대 (data/effective_n.json · 라운드 54b):')
        for k, v in (prev.get('sets') or {}).items():
            print(f'   {k}: raw {v.get("raw"):,} · 에피소드 '
                  f'{v.get("episodes"):,} · 섹터군집 {v.get("clusters"):,} · '
                  f'날짜 {v.get("dates"):,}')

    # 업종별 — 화면이 raw n 옆에 병기한다 (라운드 81b)
    sec = by_sector(buy)
    print(f'\n업종별 유효표본 (매수권 기준) — 잰 업종 {len(sec)}개')
    for s, d in sorted(sec.items(), key=lambda x: -x[1]['N'])[:12]:
        print(f"   {s:<16} raw {d['N']:>6,} · 날짜 {d['dates']:>4,} · "
              f"ICC {d['icc']:.3f} → 유효 {d['n_eff']:>7,.0f}")

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(dict(
            made=_today(), method='ANOVA ICC + design effect',
            buy_zone=BUY_ZONE, sets=result, sectors=sec, previous=prev,
            note='관측 전용 — 점수·게이트·문턱을 바꾸지 않는다. 상관 문턱을 '
                 '고르는 대신 설계효과(1+(n̄−1)ICC)를 그대로 쓴다. 날짜당 '
                 '최소 건수는 2·5·10 을 모두 실어 결과가 그 선택에 '
                 '흔들리는지 볼 수 있게 했다.'),
            f, ensure_ascii=False, indent=1)
    print(f'\n저장: {OUT}')
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
