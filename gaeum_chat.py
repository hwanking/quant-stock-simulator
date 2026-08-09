# -*- coding: utf-8 -*-
"""
가늠 AI에게 물어보기 — 종목 전용 결정적 답변 조합기 (라운드 60).

■ 왜 외부 LLM 이 아닌가
  · CLAUDE.md §9 — 포트폴리오(평단·수량)를 외부 API/LLM 에 보내지 않는다.
    보유자 질문에는 평단이 필요하므로, 외부 호출과 양립할 수 없다
  · 요구 명세 자체가 결정적이다: "중앙 엔진 값만 쓰고, 재계산·창작 금지,
    없으면 없다고 말하고, 결론부터". LLM 은 이 규칙을 어길 수 있고,
    조합기는 어길 수 없다
  외부 모델 연동이 필요해지면 `external_llm_stub()` 자리에 붙이되,
  그때도 포트폴리오 필드는 페이로드에서 제외해야 한다 (아래 가드).

■ 원칙
  · 모든 가격·확률은 build_context 로 받은 중앙 스냅샷 값 그대로.
    여기서 숫자를 만들지 않는다 (§4 — 화면 값은 한 곳에서 나온다)
  · 값이 없으면: "현재 엔진에서 이 값은 산출되지 않았습니다."
  · 신규 매수 기준과 보유자 기준을 절대 섞지 않는다
  · R55 라우팅·R57 즉시 진입은 8/23 전방 검증 전 — 운영 판단처럼
    말하지 않고 '후보 연구'로만 설명한다
  · 질문 해석은 낱말 일치만 (news_feed 와 같은 철학 — 해석 금지)
"""
from __future__ import annotations

import re

NA = '현재 엔진에서 이 값은 산출되지 않았습니다.'

#: 외부 전송 금지 필드 — external_llm_stub 을 구현하더라도 이 키들은
#: 페이로드에 넣지 않는다 (CLAUDE.md §9)
PRIVATE_KEYS = ('user_avg', 'user_qty', 'holder_ret_pct')


def external_llm_stub(question, safe_context):
    """외부 LLM 자리 — 현재 미연동. None 을 돌려 조합기가 답한다."""
    return None


def _w(v, suffix='원'):
    try:
        return f'{float(v):,.0f}{suffix}'
    except (TypeError, ValueError):
        return None


def build_context(*, name, ticker, price, core, fs, verdict, blend=None,
                  regime_code=None, sector=None, news=None, versions=None,
                  user_avg=None, user_qty=None, cb=None):
    """중앙 스냅샷 → 대화 컨텍스트. 계산하지 않고 모아서 이름만 붙인다."""
    core = core or {}
    fs = fs or {}
    vd = verdict or {}
    ret = None
    if user_avg and price:
        try:
            ret = (float(price) / float(user_avg) - 1.0) * 100.0
        except (TypeError, ValueError):
            ret = None
    return dict(
        name=str(name or ''), ticker=str(ticker or ''), price=price,
        headline=vd.get('headline') or '', score=vd.get('score'),
        action=vd.get('action'), vetoes=list(vd.get('vetoes') or []),
        bucket=core.get('bucket'), actionable=core.get('actionable'),
        entry=core.get('pullback_zone'), buy_zone=core.get('buy_zone'),
        breakout=core.get('breakout_price'),
        new_target=core.get('new_target'), new_stop=core.get('new_stop'),
        rr=core.get('rr'), horizon=core.get('horizon_days'),
        hold_trim=core.get('hold_trim'), hold_stop=core.get('hold_stop'),
        fair=fs.get('displayed_fair_value'),
        value_floor=fs.get('recommended_buy_price'),
        fv_status=fs.get('fair_value_status'),
        blend=blend, regime_code=regime_code, sector=sector,
        news=news or {}, versions=versions or {}, cb=cb or {},
        user_avg=user_avg, user_qty=user_qty, holder_ret_pct=ret,
    )


def _evidence(ctx, used):
    bits = ['중앙 판정']
    if '계층' in used and ctx.get('blend'):
        bits.append('계층 보정(R59)')
    n_news = (ctx.get('news') or {}).get('total')
    if '뉴스' in used:
        bits.append(f"뉴스 {n_news if n_news is not None else 0}건")
    mv = (ctx.get('versions') or {}).get('model')
    if mv:
        bits.append(f'모델 {mv}')
    return '근거: ' + ' · '.join(bits)


_RE_AVG = re.compile(r'([0-9][0-9,]{2,})\s*원?\s*에')


def _avg_from_question(q, price):
    """"205,000원에 가지고 있어" 류에서 평단 추출 — 자릿수 가드 포함."""
    m = _RE_AVG.search(q or '')
    if not m:
        return None
    try:
        v = float(m.group(1).replace(',', ''))
    except ValueError:
        return None
    if price and not (float(price) * 0.2 <= v <= float(price) * 5):
        return None                       # 다른 종목 자릿수 — 쓰지 않는다
    return v


def _ans_buy_now(ctx):
    e, px = ctx.get('entry'), ctx.get('price')
    if e is None:
        return (f"진입 기준이 없어 매수를 권할 수 없습니다.\n{NA} "
                f"(실행 진입가) — 근거가 생길 때까지 관망입니다.")
    gap = (float(px) / float(e) - 1) * 100 if px and e else None
    lines = []
    if ctx.get('actionable'):
        lines.append('예 — 오늘 기준 실행 가능 후보입니다 (나눠서).')
    elif gap is not None and gap > 1:
        lines.append('지금은 추격매수하지 않는 쪽입니다.')
    else:
        lines.append(f"지금은 사지 않는 쪽입니다 — {ctx.get('bucket') or '조건 미충족'}.")
    lines.append(f"현재가 {_w(px) or NA} · 1차 매수 검토 {_w(e)} 이하"
                 + (f" (현재가가 기준보다 {gap:+.1f}%)" if gap is not None
                    else ''))
    lines.append(f"1차 목표 {_w(ctx.get('new_target')) or NA} · "
                 f"손절 {_w(ctx.get('new_stop')) or NA}"
                 + (f" · 손익비 {ctx['rr']}:1" if ctx.get('rr') else ''))
    why = []
    if gap is not None and gap > 1:
        why.append(f'현재가와 검증된 진입 기준의 괴리 {gap:+.1f}%')
    for v in ctx.get('vetoes', [])[:2]:
        why.append(str(v))
    b = ctx.get('blend')
    if b:
        why.append(f"같은 조건 계층 실측 약 {b['p'] * 100:.0f}% "
                   f"({b['wilson_low'] * 100:.0f}~{b['wilson_high'] * 100:.0f}%)")
    if why:
        lines.append('이유: ' + ' / '.join(why))
    lines.append(f"{_w(e)} 부근까지 눌린 뒤 지지가 확인되면 다시 후보가 됩니다.")
    return '\n'.join(lines)


def _ans_price_buy(ctx):
    e = ctx.get('entry')
    if e is None:
        return NA + ' (실행 진입가) — 지금은 관망입니다.'
    z = ctx.get('buy_zone')
    out = [f"실행 진입 기준: {_w(e)} 이하"
           + (f" (매수구간 {z[0]:,.0f}~{z[1]:,.0f}원)" if z else '')]
    fair = ctx.get('fair')
    if fair:
        g = (float(e) / float(fair) - 1) * 100
        out.append(f"가치 기준(적정가 {_w(fair)})과는 {g:+.1f}% 차이 — "
                   f"위 값은 타이밍 기준, 적정가는 가치 기준입니다. "
                   f"서로 다른 질문에 대한 답입니다.")
    if ctx.get('breakout') and str(ctx.get('bucket') or '').startswith('돌파'):
        out.append(f"돌파를 기다리는 자리라면 {_w(ctx['breakout'])} 회복 확인 후.")
    return '\n'.join(out)


def _ans_price_sell(ctx):
    t1, t2 = ctx.get('new_target'), None
    out = []
    if t1 is None:
        out.append(NA + ' (1차 목표)')
    else:
        out.append(f"신규 매수 기준 1차 목표 {_w(t1)} · 손절 {_w(ctx.get('new_stop')) or NA}")
    if ctx.get('user_avg'):
        ht, hs = ctx.get('hold_trim'), ctx.get('hold_stop')
        out.append(f"보유자 기준(현재가 기준): 1차 일부 정리 {_w(ht) or NA} · "
                   f"방어선 {_w(hs) or NA}")
    out.append('목표 배수는 "최적"이 아니라 현행 기하입니다 — 0.4R~3.0R 어느 '
               '배수도 세 구간 모두에서 양수가 아니었습니다 (라운드 36). '
               '이른 익절·트레일링 12종도 현행을 이기지 못했습니다 (라운드 58b).')
    return '\n'.join(out)


def _ans_holder(ctx, avg):
    px = ctx.get('price')
    if not avg or not px:
        return ('평균 매수가를 모르면 보유 판단을 할 수 없습니다. 화면의 '
                "'보유 중' 선택에서 평단을 입력해 주세요.")
    ret = (float(px) / float(avg) - 1) * 100
    ht, hs = ctx.get('hold_trim'), ctx.get('hold_stop')
    out = [f"현재 약 {ret:+.1f}% 구간입니다 (평단 {_w(avg)} 기준)."]
    if ret > 5:
        out.append(f"전략: 보유 유지 — 1차 일부 정리 {_w(ht) or NA}, "
                   f"방어선 {_w(hs) or NA}.")
    elif ret >= 0:
        out.append(f"전략: 보유 유지 — 방어선 {_w(hs) or NA} 이탈 시 원칙대로.")
    elif ret > -7:
        out.append('전략: 물타기(평단 낮추기)는 하지 마세요. '
                   f"방어선 {_w(hs) or NA} 종가 이탈 시 정리.")
    else:
        out.append('전략: 비중 축소를 검토하세요 — 반등 시 '
                   f"{_w(ht) or '기술 반등 지점'} 부근에서.")
    e = ctx.get('entry')
    out.append('추가 매수는 ' + (f"실행 기준({_w(e)} 이하)과 실행 가능 판정을 "
                             f"모두 충족할 때만." if e else '지금은 금지.'))
    out.append('신규 매수 기준과 보유자 기준은 다른 값입니다 — 섞지 않습니다.')
    return '\n'.join(out)


def _ans_why_blocked(ctx):
    vs = ctx.get('vetoes') or []
    b = ctx.get('bucket')
    if not vs and ctx.get('actionable'):
        return '지금은 막혀 있지 않습니다 — 실행 가능 후보입니다.'
    out = [f"현재 분류: {b or '미분류'}"]
    if vs:
        out.append('막는 조건: ' + ' / '.join(str(v) for v in vs[:3]))
    else:
        out.append('명시적 거부 조건은 없고, 실행 조건(진입가·도달성·정합)이 '
                   '충족되지 않았습니다.')
    return '\n'.join(out)


def _ans_fair_gap(ctx):
    fair, e = ctx.get('fair'), ctx.get('entry')
    if not fair and ctx.get('fv_status') == 'OUT_OF_DOMAIN':
        return ('적정가는 산출 불가입니다 — 이 종목은 가격의 대부분이 성장 '
                '기대라 이익·자산 기반 모델의 적용 범위 밖입니다.')
    if not fair:
        return NA + ' (적정가)'
    out = [f"적정가 {_w(fair)} = 가치상 얼마면 싼가 (재무·업종 기반 중장기).",
           (f"매수 기준 {_w(e)} = 지금 장세에서 어디부터 진입할 만한가 "
            f"(추세·변동성·체결률 실측)." if e else NA + ' (매수 기준)')]
    if fair and e:
        g = (float(e) / float(fair) - 1) * 100
        out.append(f"괴리 {g:+.1f}% — 오류가 아니라 두 질문이 다른 것입니다. "
                   f"적정가까지의 하락을 기다리는 것은 실측상 역선택이었습니다 "
                   f"(깊이 기다릴수록 체결된 것들의 성과가 나빴습니다 — "
                   f"라운드 57 사전 조사).")
    return '\n'.join(out)


def _ans_news(ctx):
    n = ctx.get('news') or {}
    if not n or n.get('total') in (None, 0):
        return ('이 종목 관련 수신 기사가 없습니다 — 뉴스 미수신과 이슈 '
                '없음은 다른 말이며, 판단에는 반영하지 않았습니다.')
    out = [f"관련 기사 {n['total']}건 (신선 {n.get('fresh', 0)} · "
           f"후행 {n.get('lagging', 0)})"]
    if n.get('risk_words'):
        out.append('위험 낱말: ' + ', '.join(n['risk_words'][:4]))
    ev = n.get('event_types') or {}
    if ev:
        out.append('사건 유형: ' + ' · '.join(f'{k} {v}건'
                                          for k, v in list(ev.items())[:4]))
    out.append('뉴스가 주가에 줄 영향의 크기·방향은 엔진이 예측하지 않습니다 '
               '— 위험 낱말은 감점 요인으로만, 사건 유형은 표시로만 씁니다.')
    return '\n'.join(out)


def _ans_similar(ctx):
    cb = ctx.get('cb') or {}
    b = ctx.get('blend')
    out = []
    if cb.get('n'):
        out.append(f"같은 점수대 원실측: {cb.get('hit_rate', 0):.0f}% "
                   f"(n={cb['n']:,}).")
    if b:
        out.append(f"지금 조건(점수대×국면×자리 등 {b['layers']}층) 계층 실측: "
                   f"약 {b['p'] * 100:.0f}% "
                   f"[{b['wilson_low'] * 100:.0f}~{b['wilson_high'] * 100:.0f}%] "
                   f"· 최협층 n {b['n_narrow']:,}.")
    out.append('초근접 유사사례가 표본 기준에 못 미치면 그 5건만으로 확률을 '
               '만들지 않고, 위 계층 실측을 참고합니다. 각 값은 이 종목만의 '
               '확률이 아니라 그 계층의 실측입니다.')
    return '\n'.join(out) if out else NA


def _ans_prob_trust(ctx):
    b = ctx.get('blend')
    if not b:
        return (NA + ' (계층 보정 확률) — 점수대 원실측만 참고할 수 있고, '
                '그 값도 이 종목만의 확률은 아닙니다.')
    return (f"계층 보정 약 {b['p'] * 100:.0f}% 의 근거: {b['layers']}개 층을 "
            f"표본 크기에 따라 섞었고, 가장 좁은 층의 n 은 "
            f"{b['n_narrow']:,}건입니다 (구간 {b['wilson_low'] * 100:.0f}~"
            f"{b['wilson_high'] * 100:.0f}%).\n"
            f"검증: 사전등록 후 valid 1회에서 종전 유사사례 확률보다 "
            f"Brier·보정도 모두 정확했습니다 (보정이탈 12.1 vs 35.4%p — "
            f"라운드 59). 다만 이것은 과거 실측의 요약이지 미래 보장이 "
            f"아니며, 국면 라우팅(R55)·즉시 진입(R57)은 8/23 전방 검증 "
            f"전이라 운영 판단에 쓰지 않습니다.")


_INTENTS = (
    ('holder', ('가지고 있', '보유 중', '보유중', '평단', '추매', '물타',
                '버텨', '들고')),
    ('price_buy', ('얼마에 사', '얼마에 매수', '몇 원에 사', '매수가 얼마',
                   '어디서 사')),
    ('price_sell', ('얼마에 팔', '언제 팔', '목표가', '익절', '몇 % 먹')),
    ('buy_now', ('지금 사', '사도 돼', '사도돼', '살까', '매수해도')),
    ('why_blocked', ('왜 막', '왜 못 사', '왜 사지 마', '차단')),
    ('fair_gap', ('적정가', '펀더멘털', '괴리')),
    ('news', ('뉴스', '기사', '공시')),
    ('similar', ('유사', '비슷한 과거', '사례')),
    ('prob_trust', ('확률', '믿을 수', '신뢰할')),
)


def answer(question, ctx):
    """질문 → 결론부터 답. 중앙 스냅샷 밖의 숫자는 절대 만들지 않는다."""
    q = str(question or '').strip()
    ext = external_llm_stub(q, {k: v for k, v in ctx.items()
                                if k not in PRIVATE_KEYS})
    if ext:
        return ext
    intent = None
    for name, words in _INTENTS:
        if any(w in q for w in words):
            intent = name
            break
    used = ''
    if intent == 'holder':
        avg = _avg_from_question(q, ctx.get('price')) or ctx.get('user_avg')
        body = _ans_holder(ctx, avg)
    elif intent == 'price_buy':
        body = _ans_price_buy(ctx)
    elif intent == 'price_sell':
        body = _ans_price_sell(ctx)
    elif intent == 'buy_now':
        body, used = _ans_buy_now(ctx), '계층'
    elif intent == 'why_blocked':
        body = _ans_why_blocked(ctx)
    elif intent == 'fair_gap':
        body = _ans_fair_gap(ctx)
    elif intent == 'news':
        body, used = _ans_news(ctx), '뉴스'
    elif intent == 'similar':
        body, used = _ans_similar(ctx), '계층'
    elif intent == 'prob_trust':
        body, used = _ans_prob_trust(ctx), '계층'
    else:
        body = ('이 질문에는 아직 준비된 답변 틀이 없습니다 — 추천 질문 '
                '버튼을 사용해 주세요. 없는 값을 지어내는 대신 답하지 '
                '않는 쪽을 택했습니다.')
    return body + '\n\n' + _evidence(ctx, used)


QUICK_QUESTIONS = ('지금 사도 돼?', '얼마에 사야 해?', '얼마에 팔아?',
                   '보유 중이면 어떻게 해?', '왜 지금 매수를 막았어?',
                   '적정가와 매수가가 왜 달라?', '뉴스 영향은?',
                   '비슷한 과거 사례는?', '확률은 믿을 수 있어?')
