# -*- coding: utf-8 -*-
"""
라운드 249 — 사전등록 R249 의 **R0(표본 구조)** 만 잰다. 가장 싼 관문이다.

■ 왜 이것부터인가 (CLAUDE.md §2-7 · 라운드 170)
  *"싼 기준부터 잰다 — 비용 순으로 정렬한다. 이득의 상한을 재기 전에 먼저
  셈해 본다. 상한이 작으면 그것만으로 접는다 — 기각도 비용이다."*
  매크로 축의 성적을 재려면 원장 조인·부트스트랩이 필요하지만, **표본 구조**는
  몇 초면 안다. 여기서 미달이면 뒤는 재지 않는다.

■ 무엇을 재나
  ① 블라인드 구간의 **매수권 고유 기준일** 수 — R45 가 이미 적어 둔 최소선
     (2구간 × 칸당 15날짜 = 30)을 재사용한다. **새 숫자를 만들지 않는다.**
  ② 각 매크로 축을 그 날짜들에 붙이고 중앙값으로 가른 뒤,
     **연속 덩어리(run)** 가 몇 개인지 센다.
     매크로는 느리게 움직여 '높음/낮음' 칸이 곧 **시기**가 된다. 덩어리가 하나면
     그 축의 차이는 시기 차이와 구분되지 않는다 — 라운드 45 가 VIX 에서 당한
     그 모양이다(케이스 280건이 실은 날짜 5개, lift 의 거의 전부가 하루에서 나옴).
     ⚠️ 덩어리 수에는 **문턱을 두지 않는다** — 그것은 새 숫자다(§2).
        세어서 판정문에 적고, 적으면 그 축의 결과를 해석에서 그렇게 다룬다.

■ 누출 차단
  매크로는 `sector_cycle._upto(as_of)` 로 **기준일 전날까지만** 잘라서 붙인다.
  그 함수는 이미 그렇게 쓰이고 있다 — 새 규칙이 아니다.

    C:/Python314/python.exe scripts/macro_sample_r249.py
"""
import io
import json
import os
import re
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

LEDGER = os.path.join(PROJ, '.portfolio', 'virtual_graded.jsonl')
OUT = os.path.join(PROJ, 'data', 'macro_sample_r249.json')

#: 구간 경계 — calibration_lab 이 쓰는 그 값 그대로 (새 숫자 아님)
SPLIT_VALID_FROM = "2025-07-01"
SPLIT_BLIND_FROM = "2026-02-01"

#: 매수권 문턱 — 이 저장소가 이미 쓰는 58 (R49 계열 · 새 숫자 아님)
BUY_SCORE = 58

#: 날짜 하한 — R45 가 적은 '2구간 × 칸당 15날짜' (재사용 · 새 숫자 아님)
MIN_DATES = 30


def _ledger_last_date():
    """원장의 **마지막 케이스 기준일**. 이 산출물이 무엇을 재고 만든 것인가.

    오늘 날짜를 박지 않는다. 파일을 다시 만들 때마다 뜻이 바뀌고, 시간대에
    따라 하루가 어긋난다(라운드 222). 이 값은 '무엇을 재고 만든 것인가'다.
    """
    last = ''
    for ln in io.open(LEDGER, encoding='utf-8', errors='replace'):
        i = ln.find('"date"')
        if i < 0:
            continue
        m = re.search(r'"date"\s*:\s*"(\d{4}-\d{2}-\d{2})', ln[i:])
        if m and m.group(1) > last:
            last = m.group(1)
    return last or None


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def split_of(d):
    if d >= SPLIT_BLIND_FROM:
        return 'blind'
    if d >= SPLIT_VALID_FROM:
        return 'valid'
    return 'train'


def buy_dates():
    """구간별 매수권 고유 기준일. 원장을 한 번만 훑는다."""
    out = {'train': set(), 'valid': set(), 'blind': set()}
    rows = bad = 0
    for ln in io.open(LEDGER, encoding='utf-8', errors='replace'):
        ln = ln.strip()
        if not ln:
            continue
        rows += 1
        try:
            r = json.loads(ln)
        except Exception:                                      # noqa: BLE001
            bad += 1
            continue
        try:
            sc = float(r.get('score') or r.get('total_score') or 0)
        except (TypeError, ValueError):
            continue
        if sc < BUY_SCORE:
            continue
        d = str(r.get('date') or r.get('as_of') or '')[:10]
        if len(d) == 10:
            out[split_of(d)].add(d)
    return out, rows, bad


def runs(flags):
    """True/False 목록에서 **연속 덩어리** 수. [T,T,F,T] → 3."""
    n = 0
    prev = None
    for f in flags:
        if f != prev:
            n += 1
            prev = f
    return n


def main():
    _utf8()
    import sector_cycle as sc

    print("R0 — 표본 구조 (가장 싼 관문 · 여기서 미달이면 뒤는 재지 않는다)")
    print("=" * 72)
    dates, rows, bad = buy_dates()
    print(f"원장 {rows:,}행 · 파싱 실패 {bad} · 매수권 {BUY_SCORE}점 이상")
    for k in ('train', 'valid', 'blind'):
        print(f"   {k:<6} 고유 기준일 {len(dates[k]):>6,}")
    blind = sorted(dates['blind'])
    print()
    print(f"R0-①  블라인드 기준일 {len(blind)} vs 하한 {MIN_DATES} "
          f"→ {'통과' if len(blind) >= MIN_DATES else '미달'}")
    if len(blind) < MIN_DATES:
        print("   미달이므로 R0-② 를 재지 않는다. 사전등록대로 여기서 접는다.")
        json.dump({'ledger_last_date': _ledger_last_date(), 'made': None, 'blind_dates': len(blind),
                   'min_dates': MIN_DATES, 'verdict': 'R0-① 미달'},
                  io.open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
        return 0

    print()
    print(f"R0-②  축별 연속 덩어리 (블라인드 {len(blind)}일 · 중앙값으로 가름)")
    print(f"   {'축':<16}{'붙은 날':>8}{'중앙값':>12}{'덩어리':>8}   해석")
    print('   ' + '-' * 68)
    axes = {}
    for tk, ko, key in sc.MACRO:
        px = sc.series(tk)
        vals, used = [], []
        for d in blind:
            rowsd = sc._upto(px, d)          # 기준일 **전날까지** — 누출 차단
            if rowsd:
                vals.append(rowsd[-1][1])
                used.append(d)
        if len(vals) < MIN_DATES:
            print(f"   {ko:<16}{len(vals):>8}{'—':>12}{'—':>8}   "
                  f"붙은 날이 하한 미만 — 이 축은 미측정")
            axes[key] = {'ko': ko, 'joined': len(vals), 'runs': None,
                         'note': '붙은 날이 하한 미만'}
            continue
        med = sorted(vals)[len(vals) // 2]
        flags = [v >= med for v in vals]
        r = runs(flags)
        note = ('덩어리가 적다 — 이 축의 차이는 시기 차이와 구분되지 않는다'
                if r <= 3 else '시기가 갈려 있다')
        print(f"   {ko:<16}{len(vals):>8}{med:>12,.2f}{r:>8}   {note}")
        axes[key] = {'ko': ko, 'joined': len(vals), 'median': round(med, 4),
                     'runs': r, 'note': note}

    ok = [k for k, v in axes.items() if (v.get('runs') or 0) > 3]
    print()
    print("판정")
    print(f"   R0-① 통과 (블라인드 기준일 {len(blind)} ≥ {MIN_DATES})")
    print(f"   R0-② 덩어리 4개 이상인 축 {len(ok)}/{len(axes)} — {ok if ok else '없음'}")
    print()
    if not ok:
        print("   >> 어느 축도 시기가 갈리지 않는다. 지금 재면 매크로 차이가 아니라")
        print("      **시기 차이**를 재는 것이다 — 라운드 45 가 VIX 에서 당한 그 모양.")
        print("      사전등록대로 **여기서 접는다.** 새 하락장·새 국면이 지나야 열린다.")
    else:
        print("   >> 그 축들만 R1 로 넘긴다. 나머지는 미측정으로 적는다.")
    json.dump({'ledger_last_date': _ledger_last_date(), 'blind_dates': len(blind), 'min_dates': MIN_DATES,
               'axes': axes, 'passed_axes': ok,
               'split_valid_from': SPLIT_VALID_FROM,
               'split_blind_from': SPLIT_BLIND_FROM,
               'buy_score': BUY_SCORE, 'ledger_rows': rows},
              io.open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f"\n저장: {OUT}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
