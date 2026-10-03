# -*- coding: utf-8 -*-
"""'이 판단, 얼마나 믿을 수 있나' 칸의 문장 — 산출물에서 읽어 만든다 (라운드 421 · 한 곳 · 순수 함수).

사용자(2026-10-03)가 그 칸을 붙여 *"잘 맞는지 확인해 달라"* 고 했다. 타일의 수(검증·실전 적중 · 매수 기회)는 원장에서
직접 다시 세니 소수점까지 맞았다. 틀린 것은 **옆의 설명**이었다.

  ① *"아래 국면별 표는 58점 이상이라 표본이 더 크고"* — 국면 표는 2026-08 초 원장(검증 530 · 실전 280건)으로 잰 **고정
     값**이라 오늘 타일(검증 1,259 · 실전 1,367건)보다 **작다**. 숫자가 다른 진짜 이유는 문턱이 아니라 잰 시점이다.
  ② *"어젯밤 미국장이 보합이었습니다 — 오늘은 특히 조심하세요"* — 같은 시기 실전 142건에서 나온 주장을 **글자로 박아**
     조언했다. 오늘 원장(실전 7,346건 · 미결 제외)으로 다시 재니 보합은 학습·검증에서는 가장 낮고 실전에서는 실전 전체보다
     높다 — 세 구간에서 같은 답이 아니다.
  ③ *"지금은 ○○ 국면"* 카드가 표(원장)와 **다른 국면 규칙**을 썼다(코스피 거래일의 20.4% 에서 갈린다).
  ④ 매수 기회 타일의 분모(통계 행)가 '되돌려 본 판단'(원장 행)과 달랐는데 왜인지 안 적었다(같은 이름의 수가 둘 · R233).

규칙: 수는 전부 산출물(calibration.json · regime_breakdown.json · us_overnight.json …)에서 읽는다 — 손으로 적은 수는
낡는다(R285). 못 읽으면 그 조각만 뺀다(§3). 문턱 없음 — 비교만 한다.
"""
from __future__ import annotations

SPLITS = (('train', '학습'), ('valid', '검증'), ('blind', '실전'))


def _n(d):
    try:
        return int((d or {}).get('n') or 0)
    except (TypeError, ValueError):
        return 0


def frozen_regime_n(rb, sp):
    """고정 국면 표(regime_breakdown)의 그 구간 표본 — 국면 셋의 n 합. 못 읽으면 None."""
    cells = ((rb or {}).get('buy_zone') or {}).get(sp) or {}
    if not isinstance(cells, dict) or not cells:
        return None
    tot = sum(_n(v) for v in cells.values() if isinstance(v, dict))
    return tot or None


def today_58_n(cal, sp):
    """오늘 원장의 58점+ 표본 = 60점+(buy_zone) + 58~59점(ext_zone). 둘 중 하나라도 없으면 None."""
    s = (cal or {}).get('splits') or {}
    a, b = (s.get('buy_zone') or {}).get(sp), (s.get('ext_zone') or {}).get(sp)
    if not a or not b:
        return None
    return _n(a) + _n(b)


def threshold_note(cal, rb):
    """타일 아래 캡션 — 60점+ 와 국면 표가 왜 다른지 · 전체 사례 적중 · 실전에서 60점+ 와 전체의 비교."""
    s = (cal or {}).get('splits') or {}
    v, b = s.get('valid') or {}, s.get('blind') or {}
    bz = (s.get('buy_zone') or {}).get('blind') or {}
    out = ["위 두 적중률은 **점수 60점 이상**만 센 것입니다."]
    fv, fb = frozen_regime_n(rb, 'valid'), frozen_regime_n(rb, 'blind')
    if fv and fb:
        t = (f"아래 국면별 표는 **58점 이상**이고, 원장이 지금보다 훨씬 작을 때 잰 **고정 값**(검증 {fv:,} · 실전 {fb:,}건)이라 "
             f"위 타일과 숫자가 다릅니다")
        tv, tb = today_58_n(cal, 'valid'), today_58_n(cal, 'blind')
        if tv and tb:
            t += f" — 오늘 원장의 58점 이상은 검증 {tv:,} · 실전 {tb:,}건입니다"
        out.append(t + ".")
    if v.get('hit_rate') is not None and b.get('hit_rate') is not None:
        out.append(f"참고로 점수와 무관하게 전체 사례를 다 센 적중률은 연습 {float(v['hit_rate']):.1f}% ({_n(v):,}건) · 실전 "
                   f"{float(b['hit_rate']):.1f}% ({_n(b):,}건)입니다.")
        if bz.get('hit_rate') is not None:
            h60, hall = float(bz['hit_rate']), float(b['hit_rate'])
            if h60 < hall:
                out.append(f"실전 구간에서는 60점 이상({h60:.1f}%)이 전체({hall:.1f}%)보다 **낮습니다** — 점수가 높을수록 더 "
                           f"맞는다는 근거는 없습니다.")
            else:
                out.append(f"실전 구간에서 60점 이상은 {h60:.1f}%, 전체는 {hall:.1f}% 입니다.")
    out.append("미래 수익을 보장하지 않습니다.")
    return ' '.join(out)


def signal_sub(sig, ledger_rows=None):
    """매수 기회 타일 아랫줄 — 분모가 통계 행이면 원장 행과 왜 다른지 같이 적는다."""
    sig = sig or {}
    try:
        k, tot = int(sig.get('buy_zone') or 0), int(sig.get('total') or 0)
    except (TypeError, ValueError):
        return ''
    if not tot:
        return ''
    out = f"{k:,}/{tot:,}건"
    try:
        lr = int(ledger_rows) if ledger_rows is not None else None
    except (TypeError, ValueError):
        lr = None
    if lr and lr > tot:
        out += f" · 분모는 통계 행(원장 {lr:,}행 중 진입가 축척 어긋남·복사본 {lr - tot:,}행 뺌)"
    return out


def _worst_bands(bands, sp):
    """그 구간에서 적중이 가장 낮은 전날 미국장 구간들(표본 있는 것만 · 동률이면 전부 · 산출물 차례) — 없으면 []."""
    got = []
    for ko, cells in (bands or {}).items():
        m = (cells or {}).get(sp)
        if not m or m.get('hit') is None or not _n(m):
            continue
        got.append((ko, float(m['hit'])))
    if not got:
        return []
    low = min(h for _k, h in got)
    return [k for k, h in got if h == low]


def us_overnight_card(doc, band, cost_now):
    """'어젯밤 미국장' 카드의 둘째 줄과 경고 여부 → (문장, 경고인가). 못 읽으면 ('', False).

    경고는 **오늘 구간이 학습·검증·실전 세 구간 모두에서 가장 낮을 때만** 한다 — 종전엔 '보합'이면 늘 경고했다
    (2026-08 초 실전 142건의 주장 · 오늘 원장에서는 서지 않았다). 문턱 없음 — 세 구간의 순위만 본다."""
    bands = (doc or {}).get('bands') or {}
    cells = bands.get(band) or {}
    m = cells.get('blind') or {}
    which = '실전'
    if not _n(m):
        m, which = cells.get('valid') or {}, '검증'
    if not _n(m) or m.get('hit') is None:
        return ("이 구간은 과거 표본이 적어 성적을 말하지 않습니다.", False)
    if m.get('ret') is not None and cost_now is not None:
        ev = f"운영 비용 {float(cost_now):.2f}% 뺀 평균 {float(m['ret']) - float(cost_now):+.2f}%"
    elif m.get('ev') is not None:
        c = (doc or {}).get('cost_pct')
        ev = f"비용 {float(c):.2f}% 뺀 평균 {float(m['ev']):+.2f}%" if c is not None else f"비용 차감 후 {float(m['ev']):+.2f}%(측정 당시 비용)"
    else:
        ev = ''
    days = m.get('days')
    base = ((doc or {}).get('baseline') or {}).get('blind' if which == '실전' else 'valid') or {}
    line = (f"같은 구간의 과거 매수권({(doc or {}).get('score_floor') or 58}점+) 성적 — {which} 적중 {float(m['hit']):.1f}%"
            + (f" · {ev}" if ev else '') + f" (n={_n(m):,}" + (f" · 날짜 {int(days)}일" if days else '') + ")"
            + (f" · {which} 전체 {float(base['hit']):.1f}%" if base.get('hit') is not None else ''))
    worst = {sp: _worst_bands(bands, sp) for sp, _ko in SPLITS}
    warn = all(worst.get(sp) == [band] for sp, _ko in SPLITS)
    if not warn and all(worst.values()):
        line += (". 가장 나쁜 구간이 학습·검증·실전에서 같지 않아("
                 + ' · '.join(f"{ko} " + '·'.join(w.split(' ')[0] for w in worst[sp]) for sp, ko in SPLITS)
                 + ") 이 구간을 근거로 조심하라고 말하지 않습니다")
    made = (doc or {}).get('made')
    if made:
        line += f" ({made} 측정 · 원장 {int((doc or {}).get('ledger_rows') or 0):,}행)"
    return line, warn


def regime_now_line(price, sma20, sma60, regime_ko, idx_ko='코스피'):
    """'지금은 ○○ 국면' 카드의 근거 줄 — 표(원장)와 **같은 규칙**으로 낸 국면과, 엔진 실시간 게이트가 갈리면 그 사실.

    → (국면 코드 또는 None, 문장). 국면 이름은 regime_ko(산출물의 이름표)에서 읽는다."""
    import ledger_view as _lv
    rg = _lv.ledger_regime(price, sma20, sma60)
    if rg is None:
        return None, ''
    ko = (regime_ko or {}).get(rg, rg)
    line = (f"지금은 <b>{ko}</b> 국면입니다 — {idx_ko} {float(price):,.0f} · 20일선 {float(sma20):,.0f} · "
            f"60일선 {float(sma60):,.0f}. 아래 표와 같은 규칙으로 봅니다(현재가 &gt; 20일선 &gt; 60일선이면 상승 · 20일선과 "
            f"60일선 둘 다 아래면 하락 · 그 밖은 옆걸음 — 하루 등락이 아니라 이동평균 위치입니다). ")
    live = _lv.engine_live_regime(price, sma20, sma60)
    if live and live != rg:
        line += (f"엔진의 실시간 국면 게이트는 20일선만 넘어도 상승으로 봐서 오늘을 "
                 f"<b>{(regime_ko or {}).get(live, live)}</b>(으)로 판정합니다 — 두 규칙이 갈리는 날입니다. ")
    return rg, line


def frozen_basis(doc, label='이 표'):
    """고정 산출물이 무엇으로 잰 값인지 — 산출물에 든 표본 수·기간에서 읽는다. 못 읽으면 ''."""
    d = doc or {}
    parts = []
    base = d.get('baseline') or {}
    spl = d.get('splits') or {}
    for sp, ko in SPLITS:
        n = _n(base.get(sp)) or _n(spl.get(sp))
        if n:
            parts.append(f"{ko} {n:,}")
    if not parts:
        return ''
    per = d.get('period')
    per_txt = (f" · 기준일 {per[0]}~{per[1]}" if isinstance(per, (list, tuple)) and len(per) == 2 else '')
    return (f"{label}는 원장이 지금보다 훨씬 작을 때 잰 고정 값입니다(매수권 {' · '.join(parts)}건{per_txt}) — 그 뒤 다시 재지 "
            f"않았습니다.")
