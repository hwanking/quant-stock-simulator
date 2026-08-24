# -*- coding: utf-8 -*-
"""적정가 대비 어디서 샀나 — 전수 조사 (라운드 168).

■ 물음 (사용자)
  *"펀더멘털 적정가랑 현재가가 비슷한데 이걸 추천해 주는 게 맞아?"*

■ 무엇을 재나
  원장 전건의 `entry_zone` — 그 케이스가 **적정가 대비 어디**였는지.
  엔진이 이미 다섯 칸으로 갈라 기록해 두었다 (새 구간을 만들지 않는다 · §2):

      안전마진 확보 / 적정가 이하(안전마진 미확보) / 적정가 소폭 초과
      / 적정가 초과(추격매수 경고) / 적정가 크게 초과(추격매수 위험)
      / 판정 불가

  칸마다 **실전 적중률·비용 후 기대수익·본전 적중률**을 센다.
  라운드 159 가 쓴 잣대를 그대로 쓴다 — 새 산식을 만들지 않는다.

■ ⚠️ 이 조사가 답할 수 없는 것 — 먼저 적는다 (§3)
  원장은 과거 기준일을 **리플레이**해 만든 것인데, 재무 게시값은 이력이
  없어 **오늘 값이 쓰인다** (`calibration_lab` 이 스스로 적어 둔 한계).
  그래서 2023년 케이스의 '적정가'는 2026년 재무로 계산된 값이고,
  **적정가 대비 위치에는 미래 정보가 섞여 있다.**

  따라서 이 표는 **관찰**이지 인과가 아니다. 이것을 근거로 게이트를
  바꾸지 않는다 — 그러려면 시점별 재무 이력이 필요하고, 지금 없다.

    C:/Python314/python.exe scripts/value_zone_census_r168.py
"""
import collections
import io
import json
import math
import os
import sys
from datetime import datetime

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
os.chdir(PROJ)

LEDGER = os.path.join(PROJ, '.portfolio', 'virtual_graded.jsonl')
OUT = os.path.join(PROJ, 'data', 'value_zone_census_r168.json')

#: 왕복 비용 — 원장 연구가 쓰는 채택값 그대로 (새 숫자를 만들지 않는다)
COST_PCT = 0.36

#: 매수권 문턱 — 라운드 49 채택값. 라운드 159 전수 조사가 쓴 것과 **같은**
#: 정의를 쓴다. 새 기준을 만들지 않는다 (§2).
#: ⚠️ 처음에 `action_title` 로 골랐다가 **0건**이 나왔다. 실제 값은
#:   '신규 매수 보류'(51.7%) · '조건 확인·관망'(44.5%) · '비중축소 검토'
#:   (3.7%) · '제한적 진입'(40건) · '분할매수 검토'(4건) 뿐이라 내가 적은
#:   문구가 원장에 아예 없었다. 0건을 '데이터 없음'으로 보고했으면
#:   거짓말이 될 뻔했다 — 빈 칸이 나오면 **정의부터 실측한다** (§110).
BUY_SCORE = 58.0


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def wilson_lo(k, n, z=1.96):
    """Wilson 하한 — 작은 표본을 부풀리지 않는다 (§2)."""
    if not n:
        return None
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - r) / d * 100.0


def block(rows):
    """한 칸의 성적. 못 재는 것은 None 으로 둔다."""
    n = len(rows)
    if not n:
        return None
    dec = [r for r in rows if r.get('outcome') in ('TARGET', 'STOP')]
    hit = sum(1 for r in dec if r.get('outcome') == 'TARGET')
    rets = [float(r.get('return_pct') or 0.0) for r in dec]
    ev = (sum(rets) / len(rets) - COST_PCT) if rets else None
    # 본전 적중률 — 목표폭·손절폭의 중앙으로 낸다 (ui_kit 과 같은 식)
    ups, dns = [], []
    for r in dec:
        try:
            p, t, s = (float(r['price']), float(r['target']), float(r['stop']))
        except (TypeError, ValueError, KeyError):
            continue
        if p > 0 and t > p > s > 0:
            ups.append((t - p) / p * 100.0)
            dns.append((p - s) / p * 100.0)
    be = None
    if ups and dns:
        ups.sort()
        dns.sort()
        u = ups[len(ups) // 2]
        d = dns[len(dns) // 2]
        be = (d + COST_PCT) / (u + d) * 100.0
    return {
        'n': n, 'decided': len(dec),
        'hit_pct': round(hit / len(dec) * 100, 2) if dec else None,
        'wilson_lo': (round(wilson_lo(hit, len(dec)), 2) if dec else None),
        'ev_after_cost_pct': (round(ev, 3) if ev is not None else None),
        'breakeven_pct': (round(be, 2) if be is not None else None),
        'gap_pp': (round((hit / len(dec) * 100) - be, 2)
                   if dec and be is not None else None),
        'median_rr': (round(u / d, 2) if ups and dns else None),
    }


def main():
    print('적정가 대비 위치 — 전수 조사 (라운드 168)')
    print('관찰이다. 이것으로 게이트를 바꾸지 않는다.\n')

    rows = []
    with open(LEDGER, encoding='utf-8') as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except Exception:                                  # noqa: BLE001
                continue
    print(f'■ 원장 {len(rows):,}건 · {datetime.now():%Y-%m-%d} 기준')

    zones = collections.Counter(str(r.get('entry_zone') or '(없음)')
                                for r in rows)
    print(f'■ 적정가 대비 위치 칸 {len(zones)}개')

    by_zone = collections.defaultdict(list)
    for r in rows:
        by_zone[str(r.get('entry_zone') or '(없음)')].append(r)

    order = ['안전마진 확보', '적정가 이하 (안전마진 미확보)', '적정가 소폭 초과',
             '적정가 초과 (추격매수 경고)', '적정가 크게 초과 (추격매수 위험)',
             '판정 불가']
    order += [z for z in sorted(by_zone) if z not in order]

    def table(title, pick):
        print()
        print('=' * 96)
        print(title)
        print('=' * 96)
        print(f"{'칸':32} {'건수':>9} {'판정':>8} {'적중':>7} {'W하한':>7} "
              f"{'비용후EV':>9} {'본전':>7} {'차이':>8} {'손익비':>6}")
        out = {}
        for z in order:
            rs = [r for r in by_zone.get(z, []) if pick(r)]
            b = block(rs)
            out[z] = b
            if not b:
                print(f'{z[:31]:32} {"—":>9}')
                continue
            print(f"{z[:31]:32} {b['n']:>9,} {b['decided']:>8,} "
                  f"{(f'{b['hit_pct']:.1f}%' if b['hit_pct'] is not None else '—'):>7} "
                  f"{(f'{b['wilson_lo']:.1f}%' if b['wilson_lo'] is not None else '—'):>7} "
                  f"{(f'{b['ev_after_cost_pct']:+.3f}%' if b['ev_after_cost_pct'] is not None else '—'):>9} "
                  f"{(f'{b['breakeven_pct']:.1f}%' if b['breakeven_pct'] is not None else '—'):>7} "
                  f"{(f'{b['gap_pp']:+.1f}%p' if b['gap_pp'] is not None else '—'):>8} "
                  f"{(f'{b['median_rr']:.2f}' if b['median_rr'] is not None else '—'):>6}")
        return out

    def _is_buy(r):
        try:
            return float(r.get('score')) >= BUY_SCORE
        except (TypeError, ValueError):
            return False

    n_buy = sum(1 for r in rows if _is_buy(r))
    all_out = table('■ 전체 (점수 무관)', lambda r: True)
    buy_out = table(f'■ 매수권만 (점수 {BUY_SCORE:.0f}+ · {n_buy:,}건)', _is_buy)
    blind_out = table('■ 블라인드 구간만 (안 본 기간)',
                      lambda r: str(r.get('split') or '') == 'blind')
    bb_out = table(f'■ 매수권 × 블라인드 (가장 엄한 잣대)',
                   lambda r: _is_buy(r)
                   and str(r.get('split') or '') == 'blind')

    # ── 자기검사 ──────────────────────────────────────────────────────
    #   ⓐ 칸을 다 합치면 원장 전체와 같은가
    #   ⓑ 매수권이 **0건이 아닌가** — 0 이면 정의가 틀린 것이지 사실이 아니다
    tot = sum(v['n'] for v in all_out.values() if v)
    print()
    print(f'■ 자기검사 ⓐ 칸 합계 {tot:,} vs 원장 {len(rows):,} '
          f'→ {"일치" if tot == len(rows) else "불일치 ← 확인 필요"}')
    print(f'■ 자기검사 ⓑ 매수권 {n_buy:,}건 '
          f'({n_buy / len(rows) * 100:.1f}%) → '
          f'{"측정됨" if n_buy > 1000 else "0에 가깝다 ← 정의를 확인하라"}')

    doc = {
        'made': datetime.now().strftime('%Y-%m-%d'),
        'ledger_rows': len(rows), 'cost_pct': COST_PCT,
        'buy_score': BUY_SCORE, 'buy_cases': n_buy,
        'zones': dict(zones), 'all': all_out, 'buy_only': buy_out,
        'blind_only': blind_out, 'buy_blind': bb_out,
        'limitation': ('원장은 과거 기준일 리플레이이고 재무 게시값은 이력이 '
                       '없어 **오늘 값이 쓰인다**. 그래서 과거 케이스의 '
                       '적정가에는 미래 정보가 섞여 있다 — 이 표는 관찰이지 '
                       '인과가 아니며, 이것으로 게이트를 바꾸지 않는다.'),
        'note': '측정 전용 — 점수·게이트·문턱을 바꾸지 않는다.',
    }
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f'\n저장: {OUT}')
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
