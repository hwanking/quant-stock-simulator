# -*- coding: utf-8 -*-
"""
라운드 22b — 가격 정합성을 넓은 표본에서. "괴리가 많다"가 얼마나 많은가.

라운드 22 는 개장 전 스냅샷 6건뿐이었다. 종목을 넓혀 실제 비율을 잰다.
파이프라인을 직접 돌리므로 화면과 **같은 값**을 본다.

재는 것은 라운드 22 와 동일:
  ① 손절가 ≥ 권장 매수가 (문장이 성립 안 함)
  ② 권장가에 샀을 때의 손익비 vs 화면이 보여 주는 현재가 기준 손익비
  ③ 목표가가 적정가를 넘는 정도
  ④ 괴리와 '현재가/적정가' 의 관계 — 고평가일수록 어긋나는가
"""
import io
import json
import os
import statistics as st
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
OUT = os.path.join(BASE, '.portfolio', 'price_coherence_wide_r22b.json')
LED = os.path.join(BASE, '.portfolio', 'virtual_graded.jsonl')

N_TICKERS = 30


def sample_tickers(n):
    """원장 티커에서 고르게 뽑는다 — 무작위가 아니라 결정적으로."""
    seen = []
    with open(LED, encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                t = json.loads(ln).get('ticker')
            except Exception:
                continue
            if t and t not in seen:
                seen.append(t)
    step = max(1, len(seen) // n)
    return seen[::step][:n]


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    import quant_indicators as qi
    import bitemporal_engine as be

    # run_full_pipeline 은 클래스 메서드다 — 인스턴스를 만들어야 한다.
    # 기준일도 필요하다(None 이면 안 된다).
    eng = be.BitemporalEngine()
    q = qi.QuantIndicatorsEngine()
    t_ref = be.resolve_analysis_date().strftime('%Y-%m-%d')
    print(f'분석 기준일 {t_ref}')
    tks = sample_tickers(N_TICKERS)
    print(f'표본 {len(tks)}종목 — 파이프라인 직접 실행\n')

    rows = []
    t0 = time.time()
    for i, tk in enumerate(tks, 1):
        try:
            snap = q.run_full_pipeline(tk, t_ref, b_engine=eng,
                                       rho_cutoff=0.80)
            fs = snap.get('four_scores') or {}
        except Exception as exc:
            print(f'  [{i:>2}/{len(tks)}] {tk:<12} 실패 '
                  f'{type(exc).__name__}: {str(exc)[:80]}')
            continue
        # 현재가는 four_scores 가 아니라 스냅샷 최상위에 있다
        p = snap.get('rt_price')
        rec = fs.get('recommended_buy_price')
        stop = fs.get('stop_loss_price')
        t1 = fs.get('target_tech_1st')
        t2 = fs.get('target_tech_2nd')
        fair = fs.get('displayed_fair_value')
        if not all(isinstance(x, (int, float)) and x
                   for x in (p, stop, t1)):
            print(f'  [{i:>2}/{len(tks)}] {tk:<12} 값 부족 — '
                  f'현재가={p} 손절={stop} 1차={t1}')
            continue
        rows.append({
            'ticker': tk, 'price': float(p),
            'fair': float(fair) if fair else None,
            'rec_buy': float(rec) if rec else None,
            'stop': float(stop), 't1': float(t1),
            't2': float(t2) if t2 else float(t1),
            # 진입가 기준 레벨 — 고친 뒤에도 깨지는 게 있는지 본다
            'e_stop': fs.get('entry_stop_price'),
            'e_t1': fs.get('entry_target_1st'),
            'e_rr': fs.get('entry_rr'),
        })
        print(f'  [{i:>2}/{len(tks)}] {tk:<12} 현재 {float(p):>10,.0f} '
              f"적정 {(float(fair) if fair else 0):>10,.0f} "
              f"권장 {(float(rec) if rec else 0):>10,.0f} "
              f'손절 {float(stop):>10,.0f} · {time.time() - t0:.0f}초')

    print(f'\n수집 {len(rows)}건 · {time.time() - t0:.0f}초\n')
    withrec = [r for r in rows if r['rec_buy'] and r['fair']]
    print(f'권장 매수가·적정가가 다 산출된 건 {len(withrec)}건')
    if not withrec:
        print('측정 불가 — 권장 매수가가 산출된 종목이 없습니다.')
        return

    bad = [r for r in withrec if r['stop'] >= r['rec_buy']]
    print(f"\n■ ① 손절가 ≥ 권장 매수가: {len(bad)}/{len(withrec)}건 "
          f"({len(bad) / len(withrec) * 100:.0f}%)")
    for r in bad[:10]:
        print(f"    {r['ticker']:<12} 권장 {r['rec_buy']:>10,.0f} · "
              f"손절 {r['stop']:>10,.0f} → {(r['stop'] / r['rec_buy'] - 1) * 100:+.0f}%")

    print('\n■ ② 손익비 — 화면(현재가 기준) vs 실제(권장가에 샀을 때)')
    scr, real = [], []
    for r in withrec:
        if r['price'] > r['stop']:
            scr.append((r['t1'] - r['price']) / (r['price'] - r['stop']))
        if r['rec_buy'] > r['stop']:
            real.append((r['t1'] - r['rec_buy']) / (r['rec_buy'] - r['stop']))
    if scr:
        print(f'  화면 표시(현재가 기준) 중앙 {st.median(scr):.2f}:1')
    if real:
        print(f'  실제(권장가 기준)    중앙 {st.median(real):.2f}:1  '
              f'(계산 가능 {len(real)}/{len(withrec)}건)')
    print(f'  → 나머지 {len(withrec) - len(real)}건은 손절이 권장가 위라 '
          f'손익비를 정의할 수조차 없다')

    print('\n■ ③ 1차 목표가가 적정가를 넘는 정도')
    over = sorted((r['t1'] / r['fair'] - 1) * 100 for r in withrec)
    n_over = sum(1 for x in over if x > 0)
    print(f'  중앙 {st.median(over):+.1f}% · 최소 {over[0]:+.1f}% · '
          f'최대 {over[-1]:+.1f}%')
    print(f'  적정가보다 위인 경우 {n_over}/{len(withrec)}건 '
          f'({n_over / len(withrec) * 100:.0f}%)')

    print('\n■ ④ 고평가일수록 어긋나는가 (현재가/적정가 vs 손절-권장가 관계)')
    pairs = sorted((r['price'] / r['fair'], r['stop'] / r['rec_buy'])
                   for r in withrec)
    lo = [b for a, b in pairs if a < 1.0]
    hi = [b for a, b in pairs if a >= 1.0]
    if lo:
        print(f'  저평가(현재<적정) {len(lo)}건 — 손절/권장가 중앙 '
              f'{st.median(lo):.2f}')
    if hi:
        print(f'  고평가(현재≥적정) {len(hi)}건 — 손절/권장가 중앙 '
              f'{st.median(hi):.2f}   ← 1.0 을 넘으면 손절이 매수가 위')

    print('\n■ ⑤ 고친 뒤 — 진입가 기준 레벨은 정합한가')
    fixed = [r for r in withrec if r.get('e_stop')]
    still = [r for r in fixed if r['e_stop'] >= r['rec_buy']]
    print(f'  진입가 기준 레벨이 산출된 건 {len(fixed)}/{len(withrec)}건')
    print(f'  그중 손절 ≥ 매수가 (여전히 깨짐): {len(still)}건')
    for r in still[:5]:
        print(f"    {r['ticker']:<12} 권장 {r['rec_buy']:>10,.0f} · "
              f"손절 {r['e_stop']:>10,.0f}")
    rrs = [r['e_rr'] for r in fixed if r.get('e_rr')]
    if rrs:
        print(f'  진입가 기준 손익비 중앙 {st.median(rrs):.2f}:1 '
              f'(정의 가능 {len(rrs)}/{len(fixed)}건)')

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump({'round': '22b', 'n': len(rows), 'n_with_rec': len(withrec),
                   'stop_above_rec': len(bad),
                   'rr_screen_median': st.median(scr) if scr else None,
                   'rr_real_median': st.median(real) if real else None,
                   'rr_undefined': len(withrec) - len(real),
                   't1_over_fair_median': st.median(over),
                   't1_over_fair_n': n_over,
                   'rows': rows}, f, ensure_ascii=False, indent=1)
    print(f'\n기록: {OUT}')


if __name__ == '__main__':
    main()
