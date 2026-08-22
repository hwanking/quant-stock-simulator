# -*- coding: utf-8 -*-
"""전수 조사 — 이 엔진이 "적절하게 사는 것"을 얼마나 맞히나 (라운드 159).

물음은 사용자의 것이다: *"지금까지 주식 적절하게 사는 거 맞추는 확률이
얼마야? 개선되고 있는 거 맞아?"*

**세 가지를 갈라서 센다.** 하나의 숫자로 섞으면 무엇이 나쁜지 모른다.
  ① 종목 선별력 — 점수가 높을수록 잘 맞나 (같은 날 비교는 R110 이 이미
     기각했다. 여기서는 점수대별 적중률만 센다)
  ② 진입 자리 — 적중률이 손익분기를 넘나 (목표/손절 비로 계산)
  ③ 개선 여부 — 연도별·구간별로 움직였나

측정 전용 — 점수·게이트·문턱을 바꾸지 않는다. 새 문턱을 만들지 않는다.

    C:/Python314/python.exe scripts/census_r159.py
"""
import collections
import io
import json
import math
import os
import sys
from datetime import date, datetime, timezone

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
OUT = os.path.join(PROJ, 'data', 'census_r159.json')
LEDGER = os.path.join(PROJ, '.portfolio', 'virtual_graded.jsonl')

BUY = 58.0                     # R49 채택값 — 매수권 문턱
COST = 0.41                    # quant_indicators.TOTAL_COST_PCT (채택값)
BANDS = ((58, 60), (60, 65), (65, 70), (70, 200))


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def wilson_lo(k, n, z=1.96):
    """Wilson 하한 — 작은 표본은 이걸로 본다 (§2 규칙)."""
    if not n:
        return None
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return round((c - m) / d * 100, 1)


def band_of(s):
    for lo, hi in BANDS:
        if lo <= s < hi:
            return f'{lo}~{hi if hi < 200 else ""}'.rstrip('~') \
                if hi >= 200 else f'{lo}~{hi}'
    return None


def main():
    print('전수 조사 — "적절하게 사는 것"을 얼마나 맞히나')
    print('측정 전용 — 점수·게이트·문턱을 바꾸지 않는다')
    print()

    rows = []
    n_raw = 0
    with open(LEDGER, encoding='utf-8', errors='replace') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            n_raw += 1
            try:
                r = json.loads(ln)
            except Exception:                                  # noqa: BLE001
                continue
            rows.append(r)
    print(f'■ 원장 {n_raw:,}행 ({date.today().isoformat()} 기준)')

    # ── 전체 구성 ──────────────────────────────────────────────────────
    by_split = collections.Counter(r.get('split') or '?' for r in rows)
    graded = [r for r in rows
              if r.get('success') is not None and r.get('score') is not None]
    buy = [r for r in graded if float(r['score']) >= BUY]
    print(f'   채점된 케이스 {len(graded):,} · 매수권(58점+) {len(buy):,}')
    print('   구간별 전체: ' + ' · '.join(
        f'{k} {v:,}' for k, v in sorted(by_split.items())))

    def stat(rs):
        n = len(rs)
        if not n:
            return None
        k = sum(1 for r in rs if r['success'])
        rets = [float(r['return_pct']) for r in rs
                if r.get('return_pct') is not None]
        ev = (sum(rets) / len(rets)) if rets else None
        return dict(n=n, hit=round(k / n * 100, 1), wilson=wilson_lo(k, n),
                    ev_gross=round(ev, 3) if ev is not None else None,
                    ev_net=round(ev - COST, 3) if ev is not None else None)

    # ── ① 구간별 · 점수대별 ────────────────────────────────────────────
    print()
    print('■ ① 점수대별 적중률 — 점수가 높을수록 잘 맞나')
    print(f'{"점수대":<9}' + ''.join(f'{s:>22}' for s in
                                   ('train', 'valid', 'blind')))
    band_tbl = {}
    for lo, hi in BANDS:
        lab = f'{lo}~{hi}' if hi < 200 else f'{lo}+'
        band_tbl[lab] = {}
        line = f'{lab:<9}'
        for sp in ('train', 'valid', 'blind'):
            rs = [r for r in graded
                  if (r.get('split') == sp and lo <= float(r['score']) < hi)]
            st = stat(rs)
            band_tbl[lab][sp] = st
            line += (f'{st["hit"]:>7.1f}% (n={st["n"]:,})'.rjust(22)
                     if st else '—'.rjust(22))
        print(line)

    print()
    print('■ 매수권(58점+) 전체')
    overall = {}
    for sp in ('train', 'valid', 'blind'):
        st = stat([r for r in buy if r.get('split') == sp])
        overall[sp] = st
        if st:
            print(f'   {sp:<6} n {st["n"]:>7,} · 적중 {st["hit"]:>5.1f}% '
                  f'(Wilson 하한 {st["wilson"]}%) · 비용후 EV '
                  f'{st["ev_net"]:+.3f}%')
    st_all = stat(buy)
    print(f'   {"전체":<6} n {st_all["n"]:>7,} · 적중 {st_all["hit"]:>5.1f}% '
          f'· 비용후 EV {st_all["ev_net"]:+.3f}%')

    # ── ② 손익분기 — 목표/손절 비로 필요한 적중률 ──────────────────────
    rr = []
    for r in buy:
        try:
            p, t, s = float(r['price']), float(r['target']), float(r['stop'])
        except Exception:                                      # noqa: BLE001
            continue
        up, dn = (t - p) / p * 100, (p - s) / p * 100
        if up > 0 and dn > 0:
            rr.append(up / dn)
    rr.sort()
    rr_med = rr[len(rr) // 2] if rr else None
    #: 손익분기 적중률 — p·R − (1−p)·1 = 비용/손절폭 … 단순화해 R 만으로
    #  p* = (1 + c) / (1 + R). c 는 손절폭 대비 비용 비율의 근사치다.
    dn_med = None
    dns = sorted((float(r['price']) - float(r['stop'])) / float(r['price'])
                 * 100 for r in buy
                 if r.get('stop') and r.get('price')
                 and float(r['price']) > float(r['stop']))
    if dns:
        dn_med = dns[len(dns) // 2]
    be = None
    if rr_med and dn_med:
        c_units = COST / dn_med             # 비용을 손절폭 단위로
        be = round((1 + c_units) / (1 + rr_med) * 100, 1)
    print()
    print('■ ② 손익분기 — 목표/손절 비가 요구하는 적중률')
    print(f'   목표/손절 비(중앙) {rr_med:.2f} : 1 · 손절폭(중앙) '
          f'{dn_med:.2f}%')
    print(f'   → 본전 적중률 {be}%  ·  실전(blind) 적중률 '
          f'{overall["blind"]["hit"]}%')
    print(f'   차이 {overall["blind"]["hit"] - be:+.1f}%p')

    # ── ③ 개선 여부 — 연도별 ──────────────────────────────────────────
    print()
    print('■ ③ 연도별 매수권 적중률 — 개선되고 있나')
    yr = collections.defaultdict(list)
    for r in buy:
        d = str(r.get('date') or '')[:4]
        if len(d) == 4:
            yr[d].append(r)
    year_tbl = {}
    for y in sorted(yr):
        st = stat(yr[y])
        year_tbl[y] = st
        bar = '█' * int(round((st['hit'] - 40) / 2)) if st['hit'] > 40 else ''
        print(f'   {y}  n {st["n"]:>7,} · 적중 {st["hit"]:>5.1f}% · '
              f'비용후 EV {st["ev_net"]:>+7.3f}%  {bar}')

    # ── 실패 원인 ──────────────────────────────────────────────────────
    fc = collections.Counter(r.get('failure_class') for r in buy
                             if not r['success'] and r.get('failure_class'))
    print()
    print('■ 진 케이스의 원인 (매수권)')
    for k, v in fc.most_common(6):
        print(f'   {k:<24} {v:>7,}')

    doc = {
        'made': date.today().isoformat(),
        'made_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'question': '적절하게 사는 것을 얼마나 맞히나 · 개선되고 있나',
        'ledger_rows': n_raw, 'graded': len(graded), 'buy_zone': len(buy),
        'buy_threshold': BUY, 'cost_pct': COST,
        'by_split': overall, 'all': st_all,
        'by_band': band_tbl,
        'breakeven': dict(rr_median=round(rr_med, 3) if rr_med else None,
                          stop_pct_median=round(dn_med, 3) if dn_med else None,
                          need_hit_pct=be,
                          blind_hit_pct=overall['blind']['hit'] if
                          overall.get('blind') else None),
        'by_year': year_tbl,
        'failure_classes': dict(fc.most_common()),
        'note': ('측정 전용 — 점수·게이트·문턱을 바꾸지 않는다. 새 문턱을 '
                 '만들지 않았다(매수권 58 · 비용 0.41 은 채택값). '
                 '같은 날 순위 비교는 R110 이 이미 기각했으므로 여기서는 '
                 '점수대별 적중률만 센다.'),
    }
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print()
    print(f'저장: {OUT}')
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
