# -*- coding: utf-8 -*-
"""
가늠 AI — 대화형 모델 연결 (라운드 390 · 켜져 있을 때만).

사용자: *"가늠 AI 도 챗봇이 그냥 ChatGPT 처럼 대화하면서 할 수 있게 · 다양하게 정보도 묻고 확장성 있게."*

■ 왜 지금 붙이나 — 그리고 무엇을 안 바꾸나
  라운드 60 이 외부 모델을 안 붙인 이유는 둘이었다: ① §9 — 평단·수량을 밖으로 보낼 수 없다 ② 요구가 결정적이었다
  ("중앙 엔진 값만 · 재계산·창작 금지 · 없으면 없다고"). 사용자가 대화형을 골랐으므로 ①②를 **지키는 모양**으로 붙인다.
  · **보내는 것은 공개된 판정 값뿐** — 이 종목의 중앙 판정(결론·진입·목표·손절·적정가·확률)·시장 국면·엔진 성적표·
    말뜻 목록. 평단·수량·보유 계획·계좌는 **안 보낸다**(`gaeum_chat.PRIVATE_KEYS` + 아래 `_DROP`).
  · **보유 이야기는 보내지 않는다** — 질문에 평단·수량·보유·계좌가 들어가면(`is_private_question`) 이 PC 의 정해진
    답으로만 답한다. 사용자가 직접 친 문장이라도 밖으로 안 나간다.
  · **숫자는 앱이 낸 것만** — 모델에게 사실 묶음(JSON) 밖의 가격·확률을 만들지 말라고 하고, 앱의 결론 한 줄을
    답 머리에 **늘 앱이 붙인다**(모델이 결론을 바꿔 말해도 화면에는 앱의 결론이 먼저 선다 · §4).
  · **키가 없거나 연결이 실패하면** 종전의 정해진 답으로 대화한다(사유를 적는다 · §3). 회귀·배포는 키 없이 돈다.

■ 확장성 — 사실 묶음은 표 하나(`FACT_SOURCES`)다
  새 정보를 대화에 넣으려면 `(이름, 함수)` 한 줄을 더한다. 함수는 대화 맥락을 받아 **공개해도 되는 dict** 를 돌려준다
  (없으면 None). 사실 묶음에 없는 값은 모델도 말할 수 없다 — 그것이 이 설계의 경계다.

■ 연결
  · 키: 환경변수 `ANTHROPIC_API_KEY` 또는 Streamlit secrets 의 같은 이름(`.streamlit/secrets.toml` · 저장소 밖).
    키는 이 저장소에 적지 않는다(§9).
  · 모델: 기본 `claude-opus-5-5` · 바꾸려면 `GAEUM_LLM_MODEL`. 끄려면 `GAEUM_LLM_OFF=1`.
  · 새 의존성 없음 — 표준 라이브러리 `urllib` 로 Messages API 를 부른다(배포 의존성을 안 늘린다).
"""
from __future__ import annotations

import io
import json
import os
import re
import urllib.error
import urllib.request

API_URL = 'https://api.anthropic.com/v1/messages'
API_VERSION = '2023-06-01'
DEFAULT_MODEL = 'claude-opus-5-5'
MAX_TOKENS = 1200
TIMEOUT_SEC = 45
#: 대화 기억 — 최근 몇 턴을 같이 보내나(보낼 수 있는 턴만 · 보유 이야기는 빠진다)
HISTORY_TURNS = 8

#: 사실 묶음에서 빼는 칸 — 보유 계획·물타기 판정은 **보유 여부**를 드러낸다(값이 공개 판정이라도 · §9).
_DROP = ('user_avg', 'user_qty', 'holder_ret_pct', 'hold_trim', 'hold_stop', 'avg_down_ok')

#: 밖으로 보내지 않는 질문 — 평단·수량·보유·계좌 이야기(사용자가 친 문장이라도 · §9).
_PRIVATE_Q = re.compile(
    r'(평단|매입가|매입 ?단가|평균 ?단가|원에 ?(샀|사|갖|들고|보유|매수)|[0-9][0-9,]*\s*주\b|'
    r'[0-9][0-9,]*\s*주(를|를요|있|샀|갖|보유|들고)|내 ?계좌|내 ?포트|보유 ?중|갖고 ?있|들고 ?있|물타기|'
    r'손절할까|팔까|내 ?수익|수익률 ?얼마|손실 ?얼마)')


def api_key():
    """키 — 환경변수 먼저, 없으면 Streamlit secrets. 없으면 None(지어내지 않는다)."""
    k = os.environ.get('ANTHROPIC_API_KEY')
    if k:
        return k.strip()
    try:
        import streamlit as st
        v = st.secrets.get('ANTHROPIC_API_KEY')         # 없으면 None · secrets 파일이 없으면 예외
        return str(v).strip() if v else None
    except Exception:                                          # noqa: BLE001
        return None


def model_name():
    return (os.environ.get('GAEUM_LLM_MODEL') or DEFAULT_MODEL).strip()


def enabled():
    """켜져 있나 — 키가 있고 끄는 깃발이 없을 때만."""
    return bool(api_key()) and not os.environ.get('GAEUM_LLM_OFF')


def is_private_question(q):
    """보유·계좌 이야기인가 — 참이면 밖으로 안 보낸다. 낱말(`_PRIVATE_Q`)과 챗의 의도(보유자·계좌)를 둘 다 본다."""
    if _PRIVATE_Q.search(str(q or '')):
        return True
    try:
        import gaeum_chat as _gc
        return _gc.intent_of(q) in ('holder', 'portfolio')
    except Exception:                                          # noqa: BLE001
        return False


def safe_history(history):
    """밖으로 보내도 되는 대화만 — 보유·계좌 질문은 **그 질문과 바로 뒤의 답**을 같이 뺀다
    (보유자 답에는 평단이 들 수 있다 · §9). 반환: [(role, text)]."""
    out, skip_next_answer = [], False
    for role, text in (history or []):
        if role == 'user':
            skip_next_answer = is_private_question(text)
            if not skip_next_answer:
                out.append((role, text))
        elif role == 'assistant':
            if not skip_next_answer:
                out.append((role, text))
            skip_next_answer = False
    return out


# ── 사실 묶음 ───────────────────────────────────────────────────────────────────────────────
def _stock_facts(ctx):
    """이 종목의 공개 판정 값 — 대화 맥락에서 보유 칸을 뺀 것 그대로(계산하지 않는다)."""
    import gaeum_chat as _gc
    drop = set(_DROP) | set(_gc.PRIVATE_KEYS)
    out = {}
    for k, v in (ctx or {}).items():
        if k in drop:
            continue
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v
        elif isinstance(v, (list, tuple)):
            out[k] = [x for x in v if isinstance(x, (str, int, float))][:12]
        elif isinstance(v, dict):
            out[k] = {kk: vv for kk, vv in v.items()
                      if isinstance(vv, (str, int, float, bool)) or vv is None}
    return out or None


def _engine_facts(_ctx):
    """엔진 성적표 — 화면이 읽는 같은 산출물(표본 감사 · 매수권 성적 · 운영 비용)."""
    out = {}
    # 라운드 429 — 화면·엔진과 같은 찾는 길 · 매수권 성적은 집계표에서 그 자리에서 센다(날짜 없는 옛 파일을 안 읽는다)
    try:
        import artifact_io as _aio
        import ledger_view as _lvz
        sa = _aio.load_json('sample_audit.json')
        out['sample_audit'] = ({k: v for k, v in sa.items() if isinstance(v, (str, int, float, bool)) or v is None}
                               if isinstance(sa, dict) else None)
        bz = _lvz.buyzone_summary(_aio.load_json('calibration.json'))
        out['buy_zone_scorecard'] = (dict(bz, contract_cost_pct=_lvz.CALIB_COST_PCT,
                                          net_after_contract_cost=round(bz['avg_return'] - _lvz.CALIB_COST_PCT, 5))
                                     if bz else None)
    except Exception:                                          # noqa: BLE001
        out.setdefault('sample_audit', None)
        out.setdefault('buy_zone_scorecard', None)
    try:
        from verdict_core import COST_PCT
        out['operating_round_trip_cost_pct'] = COST_PCT
    except Exception:                                          # noqa: BLE001
        pass
    out['standing_conclusion'] = ('이 엔진의 매수권 신호에는 실전에서 재현되는 비용 차감 우위가 없다 · '
                                  '같은 날 종목 순위에 정보가 없다(잰 범위에서) · 5%p 미만 효과는 못 본다')
    return out


def _glossary_facts(_ctx):
    """설명 사전의 항목 이름 — 말뜻 질문은 앱의 사전 문장을 먼저 쓴다(사전 본문은 앱의 정해진 답이 이미 싣는다)."""
    try:
        import gaeum_glossary as _gl
        titles = [e[1] for e in getattr(_gl, 'ENTRIES', ()) if isinstance(e, (list, tuple)) and len(e) >= 2]
        return {'terms': titles[:60]} if titles else None
    except Exception:                                          # noqa: BLE001
        return None


#: 확장 지점 — (이름, 함수(ctx) → dict | None). 여기에 한 줄을 더하면 대화가 그 정보를 알 수 있다.
FACT_SOURCES = (
    ('stock', _stock_facts),
    ('engine', _engine_facts),
    ('glossary', _glossary_facts),
)


def facts(ctx):
    out = {}
    for name, fn in FACT_SOURCES:
        try:
            v = fn(ctx)
        except Exception:                                      # noqa: BLE001
            v = None
        if v:
            out[name] = v
    return out


SYSTEM = """당신은 '가늠'이라는 한국 주식 퀀트 시뮬레이터 안의 대화 도우미 '가늠 AI'입니다.
사용자와 자연스럽게 대화하며, 합니다체로 짧고 분명하게 답합니다.

반드시 지킬 것:
1. 숫자(가격·확률·수익률·건수)는 아래 '사실 묶음'과 '앱의 정해진 답'에 있는 값만 씁니다. 없는 값은 만들지 말고
   "이 앱이 그 값을 내지 않았습니다"라고 말합니다. 계산해서 새 가격을 만들지 않습니다.
2. 이 종목을 살지·팔지의 결론은 앱의 결론(headline·bucket)을 바꾸지 않습니다. 질문이 낙관적이든 비관적이든
   같은 결론을 말합니다. 결론을 뒤집는 조언을 하지 않습니다.
3. 내일·앞으로의 가격을 예측하지 않습니다. 지표를 이어 붙여 원인을 설명하는 이야기를 지어내지 않습니다.
4. 이 앱이 잰 것과 일반 지식을 구분합니다. 일반 지식(용어·제도·투자 개념)을 말할 때는 "일반적인 설명입니다 —
   이 앱이 재 본 값은 아닙니다"라고 밝힙니다.
5. 이 앱의 서 있는 결론(매수권 신호에 비용 차감 우위가 없다)을 감추지 않습니다. 성과를 좋게 보이게 말하지 않습니다.
6. 개인의 보유·평단·계좌 이야기는 이 대화로 받지 않습니다. 그런 질문이면 "보유 이야기는 이 PC 의 정해진 답으로
   답합니다"라고 안내합니다.
7. 개인 맞춤 투자 권유를 하지 않습니다. 앱의 판정을 설명하는 것까지입니다.
8. 답 끝에 사용자가 이어서 물어볼 만한 질문을 1~2개 제안합니다(예: "왜 매수를 막았는지도 볼까요?").
"""


def build_request(question, history, ctx, rule_answer, model=None):
    """Messages API 요청 본문 — 순수 함수(심어서 잰다 · 네트워크 없음)."""
    fx = facts(ctx)
    msgs = []
    for role, text in (history or [])[-2 * HISTORY_TURNS:]:
        if role in ('user', 'assistant') and text:
            msgs.append({'role': role, 'content': str(text)[:4000]})
    # 대화는 user 로 시작해야 한다 — 앞이 assistant 면 떼어 낸다
    while msgs and msgs[0]['role'] != 'user':
        msgs.pop(0)
    user_turn = ("[사실 묶음 — 이 값들만 인용할 수 있습니다]\n"
                 + json.dumps(fx, ensure_ascii=False, default=str)[:12000]
                 + "\n\n[앱의 정해진 답 — 참고용 · 결론은 이것과 같아야 합니다]\n"
                 + str(rule_answer or '')[:4000]
                 + "\n\n[사용자의 질문]\n" + str(question))
    msgs.append({'role': 'user', 'content': user_turn})
    return {'model': model or model_name(), 'max_tokens': MAX_TOKENS, 'system': SYSTEM, 'messages': msgs}


def _post(body, key):
    req = urllib.request.Request(API_URL, data=json.dumps(body).encode('utf-8'), method='POST', headers={
        'x-api-key': key, 'anthropic-version': API_VERSION, 'content-type': 'application/json'})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as r:
        return json.loads(r.read().decode('utf-8'))


#: 보내는 길 — 회귀가 가짜로 바꿔 끼워 잰다(네트워크 없이 · 무엇이 나가는지 본다)
TRANSPORT = _post


def ask(question, history, ctx, rule_answer):
    """모델에게 묻는다 → (답 | None, 사유). 못 하면 None 과 사유(정해진 답으로 대신한다 · §3)."""
    if not enabled():
        return None, '키가 없어 꺼져 있습니다'
    if is_private_question(question):
        return None, '보유·계좌 이야기는 밖으로 보내지 않습니다'
    body = build_request(question, safe_history(history), ctx, rule_answer)
    try:
        resp = TRANSPORT(body, api_key())
    except urllib.error.HTTPError as e:
        return None, f'연결 실패(HTTP {e.code})'
    except Exception as e:                                     # noqa: BLE001
        return None, f'연결 실패({type(e).__name__})'
    try:
        text = ''.join(b.get('text', '') for b in (resp.get('content') or []) if b.get('type') == 'text').strip()
    except Exception:                                          # noqa: BLE001
        text = ''
    if not text:
        return None, '빈 답을 받았습니다'
    return text, None
