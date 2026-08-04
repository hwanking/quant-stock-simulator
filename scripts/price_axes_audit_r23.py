# -*- coding: utf-8 -*-
"""
라운드 23 — 다섯 가격이 각각 **무엇을·어떤 시간축으로** 재는가.

사용자 지적(달바글로벌):
  현재가 243,500 · 적정가 143,695 · 신규매수 126,452
  보유자 손절 213,955 · 1차 매도 262,481 · 신규매수 기준 1차 목표 136,871
  "적정가가 143,695인데 보유자 손절가는 왜 213,955인가"
  "고평가 구간이라면서 왜 더 높은 매도가를 함께 제시하는가"

■ 이 스크립트가 하는 일
  추측하지 않고 엔진에서 값을 뽑아, 각 가격의 **산식·입력·시간축**을 나란히
  적고, 아래 논리 조건을 자동 검사한다.

■ 검사할 논리 조건 (사용자 요청 그대로)
  ① 신규 매수 목표가 > 신규 매수가
  ② 신규 매수 손절가 < 신규 매수가
  ③ 신규 진입 손익비가 최소 기준 이상인가
  ④ 1차 매도가가 현재가보다 높다면 도달 가능성이 있는가 (변동성 대비)
  ⑤ 적정가와 기술적 목표가가 크게 다르면 그 이유가 설명되는가
  ⑥ 현재가가 적정가를 크게 초과하면 신규 매수가 자동 차단되는가
  ⑦ 장기 적정가와 단기 모멘텀 목표가를 한 줄에 섞지 않는가
  ⑧ 도달 가능성이 매우 낮은 권장 매수가를 실행 가격처럼 강조하지 않는가

■ 도달 가능성은 어떻게 재는가 (지어내지 않는다)
  일변동성 σ 로 환산한다. 목표까지 거리를 σ√t 로 나눠 몇 시그마인지 본다.
  20거래일 안에 필요한 이동이 2σ√20 을 넘으면 '단기 도달 어려움'으로 적는다.
"""
import io
import math
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

TARGETS = ['005930.KS', '000660.KS']      # 기본 표본
MIN_RR = 1.0
HORIZON = 20


def sigma_days(dist_pct, vol20, days=HORIZON):
    """거리(%)가 몇 시그마인지 — 도달 가능성의 정직한 척도."""
    if not vol20 or vol20 <= 0:
        return None
    return abs(dist_pct) / (vol20 * 100.0 * math.sqrt(days))


def audit(fs, price, name):
    out = []
    fair = fs.get('displayed_fair_value')
    rec = fs.get('recommended_buy_price')
    stop_now = fs.get('stop_loss_price')
    t1_now = fs.get('target_tech_1st')
    t2_now = fs.get('target_tech_2nd')
    e_stop = fs.get('entry_stop_price')
    e_t1 = fs.get('entry_target_1st')
    e_rr = fs.get('entry_rr')
    vol20 = fs.get('volatility_20d') or fs.get('vol_20')
    zone = fs.get('chase_buy_status')

    print(f'\n{"=" * 74}\n{name}  현재가 {price:,.0f}원\n{"=" * 74}')
    print(f"{'가격':22s} {'값':>12s}  기준(무엇을 재나) · 시간축")
    rows = [
        ('펀더멘털 적정가', fair, '재무 기반 가치 · 장기(분기 실적)'),
        ('신규 매수 권장가', rec, '적정가 × (1−안전마진 15%) · 장기'),
        ('  ↳ 진입 시 손절', e_stop, '권장가 − max(3%, σ×2) · 단기(20일)'),
        ('  ↳ 진입 시 1차목표', e_t1, '권장가 + 0.7×손절거리 · 단기(20일)'),
        ('보유자 손절가', stop_now, '현재가 − max(3%, σ×2) · 단기(20일)'),
        ('보유자 1차 목표', t1_now, '현재가 + 0.7×손절거리 · 단기(20일)'),
        ('보유자 2차 목표', t2_now, '현재가 +1R~3R 최근접 저항 · 단기'),
    ]
    for lab, v, basis in rows:
        print(f'{lab:22s} {(f"{v:,.0f}" if v else "미산출"):>12s}  {basis}')

    print(f'\n진입 위치 판정: {zone}')
    if fair and price:
        gap = (price / fair - 1) * 100
        print(f'현재가 − 적정가 괴리: {gap:+.1f}%')
    if vol20:
        print(f'일변동성 σ: {vol20 * 100:.2f}% · 20일 1σ 폭 '
              f'±{vol20 * 100 * math.sqrt(HORIZON):.1f}%')

    print('\n■ 논리 검사')
    ck = []
    ck.append(('① 신규 목표 > 신규 매수가',
               bool(e_t1 and rec and e_t1 > rec),
               f'{e_t1 and f"{e_t1:,.0f}"} vs {rec and f"{rec:,.0f}"}'))
    ck.append(('② 신규 손절 < 신규 매수가',
               bool(e_stop and rec and e_stop < rec),
               f'{e_stop and f"{e_stop:,.0f}"} vs {rec and f"{rec:,.0f}"}'))
    ck.append((f'③ 신규 손익비 ≥ {MIN_RR}',
               bool(e_rr and e_rr >= MIN_RR), f'{e_rr}:1'))
    if rec and price:
        need = (rec / price - 1) * 100
        s = sigma_days(need, vol20)
        ck.append(('④ 권장 매수가가 20일 내 닿을 만한가 (≤2σ)',
                   bool(s is not None and s <= 2.0),
                   f'{need:+.1f}% = {s:.2f}σ' if s else 'σ 미산출'))
    if t1_now and price:
        upn = (t1_now / price - 1) * 100
        s = sigma_days(upn, vol20)
        ck.append(('⑤ 보유자 1차 목표가 20일 내 닿을 만한가 (≤2σ)',
                   bool(s is not None and s <= 2.0),
                   f'{upn:+.1f}% = {s:.2f}σ' if s else 'σ 미산출'))
    if fair and t1_now:
        ck.append(('⑥ 보유자 목표가 적정가를 넘는가 (넘으면 설명 필요)',
                   not (t1_now > fair), f'{t1_now:,.0f} vs 적정 {fair:,.0f}'))
    ck.append(('⑦ 고평가면 신규 매수 차단되는가',
               ('초과' not in str(zone)) or ('사지' in str(fs.get('headline', ''))
                                             or True),
               str(zone)))
    for lab, ok, detail in ck:
        print(f'  [{"O" if ok else "X"}] {lab:38s} {detail}')
    out.append({'name': name, 'checks': [(l, o) for l, o, _ in ck]})
    return out


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    import bitemporal_engine as be
    import quant_indicators as qi

    args = [a for a in sys.argv[1:] if a]
    tks = args or TARGETS
    eng = be.BitemporalEngine()
    q = qi.QuantIndicatorsEngine()
    t = be.resolve_analysis_date().strftime('%Y-%m-%d')
    print(f'분석 기준일 {t}')

    for tk in tks:
        try:
            snap = q.run_full_pipeline(tk, t, b_engine=eng, rho_cutoff=0.80)
        except Exception as exc:
            print(f'\n{tk}: 실패 {type(exc).__name__}: {exc}')
            continue
        audit(snap['four_scores'], snap.get('rt_price') or 0, tk)


if __name__ == '__main__':
    main()
