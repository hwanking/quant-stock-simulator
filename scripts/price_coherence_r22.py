# -*- coding: utf-8 -*-
"""
라운드 22 — 화면의 네 가격이 서로 말이 되는가.

사용자 지적: "매도 1차·2차가 우리 엔진 보고 만든 거 맞지? 적정가랑 목표가
괴리가 있는 게 많던데."

■ 지금 구조 (코드에서 확인한 것)
  손절가      = 현재가 − max(3%, 일변동성×2)   ← **현재가** 기준
  2차 목표가  = 현재가 +1R~+3R 안의 최근접 저항 ← **현재가** 기준
  1차 목표가  = 현재가 + 0.7 × 손절거리        ← **현재가** 기준
  권장 매수가 = 적정가 × (1 − 안전마진 15%)     ← **적정가** 기준

  네 값 중 셋은 현재가에 매달려 있고 하나만 적정가에 매달려 있다.
  둘을 잇는 계산은 **없다**. 그래서 서로 모순될 수 있다.

■ 재는 것 (실측 — 추측하지 않는다)
  ① 손절가 > 권장 매수가 인 비율
     → 이러면 "147,590원에 사서 216,000원에 손절" 이라는 말이 된다.
       진입가보다 46% **위**에서 손절하라는 뜻이라 문장 자체가 성립 안 한다.
  ② 권장 매수가에 실제로 샀다고 할 때의 손익비
     → 화면은 현재가 기준 손익비를 보여 주는데, 사용자는 권장가에 산다.
  ③ 1차·2차 목표가가 적정가를 얼마나 넘는가
     → 적정가 173,636원인데 목표 295,050원이면 "70% 고평가 지점까지 오르길
       기다려라"가 된다. 그게 의도라면 근거를 대야 하고, 아니면 버그다.
  ④ 권장 매수가가 현재가에서 얼마나 떨어져 있는가
     → 너무 멀면 사실상 "영원히 사지 마라"다.

■ 이 라운드는 진단이다 — 채택할 후보가 없다.
  숫자를 먼저 보고, 고칠지 말지는 그다음에 정한다.
"""
import io
import json
import os
import statistics as st
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(BASE, '.portfolio')
OUT = os.path.join(P, 'price_coherence_r22.json')

MOS = 0.15          # 안전마진 15% — 권장 매수가에서 적정가를 역산할 때 쓴다


def load_rows():
    """premarket 스냅샷·이력에서 네 가격이 다 있는 건만."""
    seen = set()
    rows = []
    files = [f for f in os.listdir(P) if f.startswith('premarket_')]
    for fn in sorted(files):
        path = os.path.join(P, fn)
        try:
            if fn.endswith('.jsonl'):
                chunks = []
                with open(path, encoding='utf-8') as f:
                    for ln in f:
                        ln = ln.strip()
                        if ln:
                            chunks.append(json.loads(ln))
            else:
                with open(path, encoding='utf-8') as f:
                    chunks = [json.load(f)]
        except Exception:
            continue
        for ch in chunks:
            date = ch.get('date') or ''
            for it in (ch.get('picks') or ch.get('items') or []):
                key = (date, it.get('symbol'))
                if key in seen:
                    continue
                seen.add(key)
                rows.append(dict(it, _date=date))
    return rows


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    rows = load_rows()
    full = [r for r in rows
            if all(r.get(k) for k in ('price', 'rec_buy', 'stop', 'target'))]
    print(f'개장 전 스냅샷 {len(rows)}건 · 네 가격이 다 있는 건 {len(full)}건\n')
    if not full:
        print('측정할 표본이 없습니다.')
        return

    bad_stop = []
    rr_at_rec = []
    over_fair_1 = []
    over_fair_2 = []
    rec_gap = []
    detail = []

    for r in full:
        p = float(r['price'])
        rec = float(r['rec_buy'])
        stop = float(r['stop'])
        t1 = float(r['target'])
        t2 = float(r['target2']) if r.get('target2') else t1
        fair = rec / (1.0 - MOS)          # 권장 매수가에서 적정가 역산

        if stop >= rec:
            bad_stop.append(r)
        # 권장가에 샀다면의 손익비 (화면이 보여 주는 건 현재가 기준이다)
        if rec > stop:
            rr_at_rec.append((t1 - rec) / (rec - stop))
        over_fair_1.append((t1 / fair - 1) * 100)
        over_fair_2.append((t2 / fair - 1) * 100)
        rec_gap.append((rec / p - 1) * 100)
        detail.append({
            'date': r['_date'], 'name': r.get('name'),
            'symbol': r.get('symbol'), 'price': p, 'fair': fair,
            'rec_buy': rec, 'stop': stop, 't1': t1, 't2': t2,
            'stop_above_rec': stop >= rec,
            't1_over_fair_pct': (t1 / fair - 1) * 100,
            'rec_gap_pct': (rec / p - 1) * 100,
        })

    def q(v, name, unit='%'):
        if not v:
            print(f'  {name}: 표본 없음')
            return
        v = sorted(v)
        print(f'  {name}: 중앙 {st.median(v):+.1f}{unit} · '
              f'최소 {v[0]:+.1f}{unit} · 최대 {v[-1]:+.1f}{unit}')

    print('■ ① 손절가가 권장 매수가보다 위인가 (문장이 성립하지 않는 경우)')
    print(f'  {len(bad_stop)}/{len(full)}건 ({len(bad_stop) / len(full) * 100:.0f}%)')
    for r in bad_stop[:6]:
        p, rec, stop = float(r['price']), float(r['rec_buy']), float(r['stop'])
        print(f"    {r.get('name','?'):10s} 현재 {p:>10,.0f} · "
              f"권장매수 {rec:>10,.0f} · 손절 {stop:>10,.0f}  "
              f"→ 손절이 매수가보다 {(stop / rec - 1) * 100:+.0f}%")

    print('\n■ ② 권장 매수가에 실제로 샀다면의 손익비')
    q(rr_at_rec, '손익비(1차 목표 기준)', ':1')
    print('  ※ 화면이 보여 주는 손익비는 **현재가** 기준이라 이 값과 다르다')

    print('\n■ ③ 목표가가 적정가를 얼마나 넘는가')
    q(over_fair_1, '1차 목표 − 적정가')
    q(over_fair_2, '2차 목표 − 적정가')
    n_over = sum(1 for x in over_fair_1 if x > 0)
    print(f'  1차 목표가 적정가보다 위인 경우 {n_over}/{len(full)}건 '
          f'({n_over / len(full) * 100:.0f}%)')

    print('\n■ ④ 권장 매수가가 현재가에서 얼마나 떨어져 있나')
    q(rec_gap, '권장매수가 − 현재가')
    n_far = sum(1 for x in rec_gap if x < -30)
    print(f'  현재가보다 30% 넘게 낮은 경우 {n_far}/{len(full)}건 '
          f'({n_far / len(full) * 100:.0f}%) — 사실상 "사지 마라"')

    print('\n■ 전체 표')
    print(f"  {'종목':10s} {'현재가':>10s} {'적정가':>10s} {'권장매수':>10s} "
          f"{'손절':>10s} {'1차목표':>10s} │ 문제")
    for d in detail:
        flags = []
        if d['stop_above_rec']:
            flags.append('손절>매수가')
        if d['t1_over_fair_pct'] > 20:
            flags.append(f"목표>적정가{d['t1_over_fair_pct']:+.0f}%")
        if d['rec_gap_pct'] < -30:
            flags.append(f"매수가 {d['rec_gap_pct']:+.0f}%")
        print(f"  {str(d['name'])[:10]:10s} {d['price']:>10,.0f} "
              f"{d['fair']:>10,.0f} {d['rec_buy']:>10,.0f} {d['stop']:>10,.0f} "
              f"{d['t1']:>10,.0f} │ {' · '.join(flags) or '—'}")

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump({'round': 22, 'n': len(full),
                   'stop_above_rec_n': len(bad_stop),
                   'rr_at_rec_median': (st.median(rr_at_rec)
                                        if rr_at_rec else None),
                   't1_over_fair_median': st.median(over_fair_1),
                   't2_over_fair_median': st.median(over_fair_2),
                   'rec_gap_median': st.median(rec_gap),
                   'detail': detail}, f, ensure_ascii=False, indent=1)
    print(f'\n기록: {OUT}')


if __name__ == '__main__':
    main()
