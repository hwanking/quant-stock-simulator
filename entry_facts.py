# -*- coding: utf-8 -*-
"""
진입가 근거 문장 — '그 가격에 닿는가'와 '닿은 뒤 이익이 남는가'를 **같은 줄**에 적는다 (라운드 344).

■ 무엇이 있었나
  두 자리(적정가 3축 · 엔진의 눌림 진입 근거)가 *"체결률 79.3% · 평균 3.4거래일 (경로 5,389건)"* 을 글자로 박고
  있었다. 산출물을 열어 보니 ① 79.3% 는 5,389건이 아니라 **블라인드 280건**의 값이고(전체는 78.3% · 3.05일)
  ② 3.4거래일은 어느 산출물에도 없으며 ③ **같은 행**에 닿은 뒤 성적(목표 먼저 · 손절 먼저 · 비용 차감 평균 ·
  신호당 평균)이 있는데 좋아 보이는 절반만 화면에 나갔다. 눈에 띄는 수에는 그 값어치를 같은 자리에 적는다.

■ 규칙
  수는 손으로 안 적는다 — `data/entry_fill_facts.json` 에서 읽는다(원본은 gitignored 라 배포 화면이 못 읽는다).
  못 읽으면 수를 지어내지 않고 못 읽었다고 적는다(§3). 부호가 구간마다 갈리면 갈린다고만 적는다 — 사라·말라를
  대신 말하지 않는다. 일봉 모의 체결이지 실제 주문 체결이 아니라는 것도 같은 줄에 적는다.
"""
import io
import json
import os

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'entry_fill_facts.json')
_MEM = {}
SPLIT_KO = (('train', '학습'), ('valid', '검증'), ('blind', '블라인드'))


def load(path=PATH):
    """산출물 요약. 못 읽으면 None."""
    if path in _MEM:
        return _MEM[path]
    try:
        with io.open(path, encoding='utf-8') as f:
            d = json.load(f)
        if not isinstance((d.get('splits') or {}).get('all'), dict):
            d = None
    except Exception:                                          # noqa: BLE001
        d = None
    _MEM[path] = d
    return d


def _cost_gap(measured):
    """잰 당시 비용과 오늘 운영 비용이 다르면 그 사실을 같은 줄에 적는다 (라운드 350).

    같은 화면에 비용이 둘이면 사용자는 어느 것이 기준인지 모른다. 이 표는 그때의 실측이라
    **그때의 비용**으로 차감돼 있고, 다시 재지 않는 한 그 수가 맞다 — 고칠 것은 수가 아니라
    **어느 비용으로 뺀 값인지 적는 것**이다. 운영 비용은 늦은 임포트로 읽어 순환을 만들지
    않는다. 못 읽으면 아무 말도 안 붙인다(§3).
    """
    try:
        from verdict_core import COST_PCT as _op
        if measured is None or abs(float(measured) - float(_op)) < 1e-9:
            return ''
        return f" (잰 당시 비용입니다 — 지금 운영 비용은 {float(_op):g}%)"
    except Exception:                                          # noqa: BLE001
        return ''


def line(facts='__load__'):
    """진입가 근거의 실측 꼬리 문장."""
    d = load() if facts == '__load__' else facts
    a = ((d or {}).get('splits') or {}).get('all') or {}
    need = ('n', 'fill_rate', 'days', 'tgt_first', 'stop_first', 'ret', 'ev_sig')
    if not d or any(a.get(k) is None for k in need):
        return '실측 표를 읽지 못해 도달 비율과 닿은 뒤 성적을 적지 않습니다'
    per = [(ko, (d['splits'].get(k) or {}).get('ret')) for k, ko in SPLIT_KO]
    per = [(ko, v) for ko, v in per if v is not None]
    signs = {(v > 0) - (v < 0) for _, v in per}
    if len(per) < 2:
        tail = ''
    elif len(signs) > 1:
        tail = ' — 구간마다 부호가 갈립니다'
    else:
        tail = ' — 세 구간 부호가 같습니다'
    per_txt = ' · '.join(f'{ko} {v:+.2f}' for ko, v in per)
    return (f"{int(d.get('max_bars') or 20)}봉 안에 이 가격에 닿은 비율 {a['fill_rate']:.1f}% · 평균 {a['days']:.2f}거래일 "
            f"({d.get('made')} · 매수권 신호 {int(a['n']):,}건 · 일봉으로 모의한 값이라 실제 주문 체결과 다를 수 있습니다) · "
            f"닿은 뒤에는 목표 먼저 {a['tgt_first']:.1f}% · 손절 먼저 {a['stop_first']:.1f}% · "
            f"왕복 비용 {d.get('cost_pct')}% 차감 평균 {a['ret']:+.2f}%" + _cost_gap(d.get('cost_pct'))
            + (f" ({per_txt}{tail})" if per_txt else '')
            + f" · 못 산 신호까지 넣은 신호당 평균 {a['ev_sig']:+.2f}% — "
            f"가격에 닿는 것과 닿은 뒤 이익이 남는 것은 다른 사실이고, 이 종목 값이 아니라 전체 실측입니다")
