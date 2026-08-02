# -*- coding: utf-8 -*-
"""
UI 킷 — 애플 HIG(설정·건강·주식 앱) 패턴의 단일 렌더 계층.

지금까지 화면이 통일되지 않은 근본 원인은 카드마다 인라인 HTML을 따로 쓴 것이다.
여기 있는 함수만으로 그리면 표면·여백·타이포가 저절로 같아진다.

핵심 원칙 (애플 디자인의 실체 — 장식이 아니라 '덜어내기'):
  1. 테두리를 쓰지 않는다. 구분은 **표면 대비**와 **여백**으로 한다.
     (예외: 최종 결론 카드 하나만 색 테두리를 갖는다)
  2. 그룹 안의 행은 헤어라인 1px로만 나눈다 — iOS 설정 앱의 inset grouped list.
  3. 여백은 8pt 그리드: 행 12 / 카드 안쪽 20 / 그룹 사이 16 / 섹션 사이 40.
  4. 강조는 색이 아니라 **크기와 위치**로 만든다. 색은 의미(상승·하락·경고)에만.
  5. 크롬(UI 구조물)에는 이모지를 쓰지 않는다.
"""
from __future__ import annotations

import html as _html
from typing import Iterable, Optional, Sequence

import streamlit as st

# ── 표면 3단계 (테두리 없음 — 이 대비만으로 층이 보인다) ──────────────────
DARK = dict(bg='#0B0F17', card='#161D2A', raised='#1C2635',
            line='#222C3C', tx1='#F3F6FA', tx2='#9DAABC', tx3='#7C8AA0',
            brand='#4C8DFF', up='#FF453A', down='#0A84FF',
            pos='#35C98B', warn='#F2B84B', neg='#F26161')
LIGHT = dict(bg='#EFF1F6', card='#FFFFFF', raised='#F2F5F9',
             line='#E6EAF0', tx1='#111827', tx2='#4A4D53', tx3='#666873',
             brand='#2563EB', up='#D93025', down='#1A73E8',
             pos='#16875D', warn='#B7791F', neg='#D14343')
# 글자 3단은 눈대중이 아니라 실측으로 정했다 (WCAG 대비, 회색 배경·흰 카드 양쪽):
#   다크  tx1 15.6 · tx2 7.2 · tx3 4.8   |  라이트 tx1 15.7 · tx2 7.5 · tx3 4.9
# tx3 는 보조 설명 전용이며 4.5 미만으로 내려가면 안 된다 (작은 12px 글자가 많다).


def tokens(theme: str = 'dark') -> dict:
    return DARK if theme == 'dark' else LIGHT


def _esc(s) -> str:
    return _html.escape(str(s if s is not None else ''))


def section(title: str, subtitle: str = '', theme: str = 'dark',
            top: int = 40) -> None:
    """섹션 헤더 — 작고 조용하게. 크기가 아니라 여백이 위계를 만든다."""
    t = tokens(theme)
    sub = (f"<p style='margin:2px 0 0 0; font-size:13px; color:{t['tx2']}; "
           f"line-height:1.5;'>{_esc(subtitle)}</p>" if subtitle else '')
    st.markdown(
        f"<div style='margin:{top}px 0 12px 0;'>"
        f"<p style='margin:0; font-size:20px; font-weight:600; color:{t['tx1']}; "
        f"letter-spacing:-0.014em;'>{_esc(title)}</p>{sub}</div>",
        unsafe_allow_html=True)


def sidebar_section(title: str, sub: str = '', theme: str = 'dark',
                    top: int = 26) -> None:
    """
    사이드바 구역 라벨 — 본문 섹션보다 한 단계 조용하다.

    구분선(---)을 쓰지 않는다. 사이드바에 가로선을 그으면 좁은 폭에서 선만
    눈에 남고 내용이 밀린다. 대신 위 여백과 작은 대문자 라벨로 나눈다.
    """
    t = tokens(theme)
    s = (f"<p style='margin:3px 0 0 0; font-size:12px; color:{t['tx3']}; "
         f"line-height:1.5; word-break:keep-all;'>{_esc(sub)}</p>"
         if sub else '')
    st.sidebar.markdown(
        f"<div style='margin:{top}px 0 8px 0;'>"
        f"<p style='margin:0; font-size:12px; font-weight:600; "
        f"letter-spacing:0.06em; color:{t['tx2']};'>{_esc(title)}</p>{s}</div>",
        unsafe_allow_html=True)


def sidebar_fact(label: str, value: str, theme: str = 'dark',
                 tone: str = '') -> None:
    """사이드바 한 줄 사실 — 색 상자(success/info) 대신 쓴다."""
    t = tokens(theme)
    col = t.get(tone, t['tx1'])
    st.sidebar.markdown(
        f"<div style='display:flex; gap:10px; align-items:baseline; "
        f"padding:4px 0;'>"
        f"<span style='font-size:12px; color:{t['tx3']}; flex:0 0 auto;'>"
        f"{_esc(label)}</span>"
        f"<span style='font-size:13px; color:{col}; font-weight:600; "
        f"margin-left:auto; text-align:right; word-break:break-all;'>"
        f"{_esc(value)}</span></div>",
        unsafe_allow_html=True)


def stat_tiles(items: Sequence[dict], theme: str = 'dark') -> None:
    """
    지표 타일 줄 — st.metric 대체. 한 그룹 카드 안에 세로 헤어라인으로 나눈다.

    items: [{'label','value','sub'(선택),'tone'(선택: pos|neg|warn|brand)}]
    """
    t = tokens(theme)
    n = max(1, len(items))
    cells = []
    for i, it in enumerate(items):
        tone = t.get(it.get('tone') or '', t['tx1'])
        border = ('' if i == 0 else
                  f"border-left:1px solid {t['line']};")
        # 보조 설명은 잘라내지 말고 두 줄까지 흘린다 (정보 손실 금지)
        sub = (f"<p style='margin:4px 0 0 0; font-size:12px; color:{t['tx3']}; "
               f"line-height:1.45; word-break:keep-all;'>"
               f"{_esc(it.get('sub'))}</p>" if it.get('sub') else '')
        cells.append(
            f"<div style='flex:1 1 0; min-width:0; padding:4px 16px; {border}'>"
            # 라벨을 …으로 자르지 않는다. 좁으면 두 줄로 흐르게 둔다 —
            # 무슨 지표인지 모르게 만드는 것이 공간 절약보다 나쁘다.
            f"<p style='margin:0; font-size:13px; color:{t['tx2']}; "
            f"font-weight:500; line-height:1.35; word-break:keep-all; "
            f"min-height:2.7em;'>{_esc(it['label'])}</p>"
            # 값은 절대 줄바꿈하지 않는다 — 폭이 좁으면 글자를 줄인다(clamp).
            # 경계값 20·28 은 타입 스케일 안이다.
            f"<p style='margin:8px 0 0 0; font-size:clamp(20px, 2.4vw, 28px); "
            f"font-weight:600; color:{tone}; letter-spacing:-0.02em; "
            f"line-height:1.15; white-space:nowrap; overflow:hidden; "
            f"text-overflow:ellipsis; font-variant-numeric:tabular-nums;'>"
            f"{_esc(it['value'])}</p>{sub}</div>")
    st.markdown(
        f"<div style='background:{t['card']}; border-radius:18px; "
        f"padding:20px 8px; display:flex; align-items:stretch;'>"
        + ''.join(cells) + "</div>", unsafe_allow_html=True)


def rows(items: Sequence[tuple], theme: str = 'dark',
         title: str = '') -> None:
    """
    iOS 설정 앱식 그룹 리스트 — 좌측 라벨 / 우측 값, 행 사이는 헤어라인.

    items: [(label, value)] 또는 [(label, value, tone)]
    """
    t = tokens(theme)
    head = (f"<p style='margin:0 0 8px 2px; font-size:13px; color:{t['tx2']}; "
            f"font-weight:500;'>{_esc(title)}</p>" if title else '')
    body = []
    for i, it in enumerate(items):
        label, value = it[0], it[1]
        tone = t.get(it[2], t['tx1']) if len(it) > 2 and it[2] else t['tx1']
        line = ('' if i == 0 else f"border-top:1px solid {t['line']};")
        body.append(
            f"<div style='display:flex; justify-content:space-between; "
            f"align-items:baseline; gap:16px; padding:12px 0; {line}'>"
            f"<span style='font-size:15px; color:{t['tx2']};'>{_esc(label)}</span>"
            f"<span style='font-size:15px; font-weight:600; color:{tone}; "
            f"font-variant-numeric:tabular-nums; text-align:right;'>"
            f"{_esc(value)}</span></div>")
    st.markdown(
        head + f"<div style='background:{t['card']}; border-radius:18px; "
        f"padding:8px 20px;'>" + ''.join(body) + "</div>",
        unsafe_allow_html=True)


def card(body_html: str, theme: str = 'dark', accent: str = '',
         pad: int = 22) -> None:
    """일반 카드 — 테두리 없음. accent 를 주면 좌측 3px 액센트만 붙는다."""
    t = tokens(theme)
    edge = (f"border-left:3px solid {t.get(accent, accent)};" if accent else '')
    st.markdown(
        f"<div style='background:{t['card']}; border-radius:18px; "
        f"padding:{pad}px; {edge}'>{body_html}</div>",
        unsafe_allow_html=True)


def note(text: str, theme: str = 'dark') -> None:
    """보조 설명 — 캡션보다 조용하게, 카드 밖에 둔다."""
    t = tokens(theme)
    st.markdown(
        f"<p style='margin:8px 2px 0 2px; font-size:13px; color:{t['tx3']}; "
        f"line-height:1.6;'>{_esc(text)}</p>", unsafe_allow_html=True)


def spacer(px: int = 24) -> None:
    st.markdown(f"<div style='height:{px}px'></div>", unsafe_allow_html=True)


def global_css(theme: str = 'dark') -> str:
    """
    킷 밖의 Streamlit 기본 위젯까지 같은 언어로 맞추는 전역 규칙.
    web_app 의 CSS 블록 끝에 붙인다.
    """
    t = tokens(theme)
    return f"""
    /* ── 애플 정돈: 테두리 제거 · 표면 대비로 층 만들기 ───────────── */
    .stApp [data-testid="stExpander"] {{
        background: {t['card']} !important;
        border: none !important;
        border-radius: 18px !important;
        margin-bottom: 12px !important;
        box-shadow: none !important;
    }}
    .stApp [data-testid="stExpander"] summary {{
        padding: 16px 20px !important;
        font-size: 15px !important;
        font-weight: 600 !important;
    }}
    .stApp [data-testid="stExpander"] summary:hover {{
        background: {t['raised']} !important;
    }}
    .stApp [data-testid="stExpanderDetails"] {{ padding: 0 20px 16px 20px; }}

    /* 알림 — 색 면 대신 조용한 카드 + 좌측 액센트 */
    .stApp [data-testid="stAlert"] {{
        background: {t['card']} !important;
        border: none !important;
        border-left: 3px solid {t['brand']} !important;
        border-radius: 14px !important;
        padding: 16px 20px !important;
        box-shadow: none !important;
    }}
    .stApp [data-testid="stAlert"]:has([data-testid="stAlertContentSuccess"]) {{
        border-left-color: {t['pos']} !important; }}
    .stApp [data-testid="stAlert"]:has([data-testid="stAlertContentWarning"]) {{
        border-left-color: {t['warn']} !important; }}
    .stApp [data-testid="stAlert"]:has([data-testid="stAlertContentError"]) {{
        border-left-color: {t['neg']} !important; }}
    .stApp [data-testid="stAlertDynamicIcon"] {{ display: none !important; }}

    /* 표 — 테두리 제거, 헤어라인만 */
    .stApp [data-testid="stDataFrame"] {{
        border: none !important; border-radius: 14px; overflow: hidden; }}

    /* 사이드바 정숙화 — 색 박스의 벽을 없앤다 */
    [data-testid="stSidebar"] [data-testid="stAlert"] {{
        background: transparent !important;
        border-left: 2px solid {t['line']} !important;
        border-radius: 0 !important;
        padding: 4px 0 4px 12px !important;
    }}
    [data-testid="stSidebar"] hr {{
        margin: 20px 0 !important; border-color: {t['line']} !important; }}

    /* 버튼 — 채움 대신 형태로 (애플식 pill) */
    .stApp .stButton > button,
    .stApp .stButton > button * {{
        color: {t['tx1']} !important;   /* 표면이 바뀌면 글자색도 따라와야 한다 */
    }}
    .stApp .stButton > button {{
        border-radius: 980px !important;
        border: 1px solid {t['line']} !important;
        background: {t['raised']} !important;
        font-weight: 600 !important;
        padding: 8px 20px !important;
        transition: background .2s ease, border-color .2s ease !important;
    }}
    .stApp .stButton > button:hover {{
        background: {t['card']} !important;
        border-color: {t['brand']} !important; }}
    .stApp .stButton > button:hover * {{ color: {t['brand']} !important; }}

    /* 슬라이더 — 시안 형광 대신 브랜드 한 색 */
    .stApp [data-testid="stSlider"] [data-baseweb="slider"] div[role="slider"],
    [data-testid="stSidebar"] [data-testid="stSlider"] div[role="slider"] {{
        background: {t['brand']} !important; }}
    .stApp [data-testid="stSlider"] [data-testid="stTickBar"],
    .stApp [data-testid="stSlider"] [data-baseweb="slider"] > div > div {{
        background: {t['line']} !important; }}
    .stApp [data-testid="stSlider"] [data-baseweb="slider"] > div > div > div {{
        background: {t['brand']} !important; }}
    /* 손잡이 위 숫자는 브랜드색 배경에 얹히므로 흰 글자로 고정한다.
       기본값(보조 회색)이면 대비 1.4 로 읽히지 않는다 (실측). */
    [data-testid="stSliderThumbValue"],
    [data-testid="stSliderThumbValue"] * {{
        color: #FFFFFF !important; font-weight: 600 !important; }}

    /* 수직 리듬 — 8pt 그리드 */
    .stApp hr {{ margin: 40px 0 !important; border-color: {t['line']} !important;
                opacity: 1 !important; }}
    .stMainBlockContainer {{ max-width: 1120px !important;
                            padding-top: 2rem !important; }}
    """
