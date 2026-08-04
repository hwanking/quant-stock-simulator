import sys
import textwrap
import time
import streamlit as st
import pandas as pd
import numpy as np
import datetime
import importlib
import matplotlib
matplotlib.use("Agg")          # 헤드리스 서버에는 GUI 백엔드가 없다
import matplotlib.pyplot as plt
import urllib.request
import json
import os

# ── Matplotlib 한글 폰트 ────────────────────────────────────────────────
# 'Malgun Gothic' 을 그대로 박아두면 리눅스(클라우드)에는 그 폰트가 없어
# 차트마다 경고가 쏟아지고 한글이 네모로 깨진다. 설치된 것 중에서 고른다.
# (클라우드에는 packages.txt 의 fonts-nanum 이 설치된다)
def _pick_korean_font():
    from matplotlib import font_manager
    installed = {f.name for f in font_manager.fontManager.ttflist}
    for name in ("Malgun Gothic", "AppleGothic", "NanumGothic", "NanumBarunGothic",
                 "Noto Sans CJK KR", "Noto Sans KR", "DejaVu Sans"):
        if name in installed:
            return name
    return "DejaVu Sans"


matplotlib.rcParams['font.family'] = _pick_korean_font()
matplotlib.rcParams['axes.unicode_minus'] = False

# 모듈 핫 리로딩
import bitemporal_engine
import quant_indicators
import report_generator
import leakage_guard

importlib.reload(bitemporal_engine)
importlib.reload(quant_indicators)
importlib.reload(report_generator)
importlib.reload(leakage_guard)

import portfolio
importlib.reload(portfolio)

import market_attention
importlib.reload(market_attention)

from bitemporal_engine import STOCK_NAME_MAP, BitemporalEngine
from quant_indicators import QuantIndicatorsEngine
from report_generator import QuantReportGenerator
from leakage_guard import LeakageGuard

# 1. 스트림릿 페이지 설정 및 애플(Apple.com) 스타일 다크모드 고대비 CSS
#: 앱 이름은 여기 하나만 고친다. 사이드바 홈 버튼과 본문 대제목이 같은 값을 쓴다.
#: (예전에는 '퀀트 주식 시뮬레이터' / '차세대 AI 퀀트 주가 예측 시뮬레이터' 로 달랐다)
APP_TITLE = "가늠"
APP_TAGLINE = "사기 전에, 재봅니다"
APP_NAME = APP_TITLE
def _last_update_date():
    """업데이트 날짜는 손으로 적지 않는다 — 커밋 이력이 원천이다."""
    try:
        import json as _j
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               'data', 'update_history.json'),
                  encoding='utf-8') as _f:
            return str(_j.load(_f)['days'][0]['date'])
    except Exception:
        return datetime.date.today().isoformat()


APP_UPDATED = _last_update_date()

def is_remote_exposed():
    """
    지금 접속이 이 PC 밖에서 온 것인가? (클라우드·터널·LAN 모두 포함)

    판정 근거를 여러 개 쓴다. 하나라도 '외부'를 가리키면 외부로 본다 —
    인증은 **막는 쪽으로 틀려야** 안전하기 때문이다.
    """
    # Streamlit Community Cloud 는 앱을 /mount/src 아래에 마운트한다
    try:
        if os.path.isdir("/mount/src"):
            return True
    except Exception:
        pass
    try:
        host = str(st.context.headers.get("host") or "").split(":")[0].lower()
    except Exception:
        host = ""
    if host.endswith(".streamlit.app"):
        return True
    # 호스트가 있는데 localhost 가 아니면 외부 접속이다 (LAN·터널 포함)
    return bool(host) and host not in ("localhost", "127.0.0.1", "::1")


def is_local_session():
    """
    클립보드 붙여넣기를 노출해도 되는 상황인가?

    클립보드 읽기는 **서버 프로세스의 클립보드**를 읽는다. 로컬 실행일 때는
    그게 곧 사용자의 클립보드지만, 클라우드에 올리면 남의 서버 클립보드를
    읽으려 드는 무의미한(그리고 오해를 부르는) 기능이 된다.

    두 조건을 모두 만족해야 한다:
      ① 접속이 localhost 에서 왔거나 호스트를 알 수 없음(로컬 개발)
      ② 클립보드 읽기가 실제로 동작하는 OS (Windows/macOS)
         — 클라우드는 리눅스 컨테이너라 xclip 없이는 동작하지 않는다.
    """
    if sys.platform not in ("win32", "darwin"):
        return False
    try:
        host = str(st.context.headers.get("host") or "")
    except Exception:
        return True          # 헤더를 못 읽으면 로컬 실행으로 본다
    host = host.split(":")[0].lower()
    return host in ("localhost", "127.0.0.1", "::1", "")


def check_password():
    """
    외부 접속이면 반드시 인증을 통과해야 한다.

    ⚠️ **fail-closed 로 동작한다.** 비밀번호가 설정돼 있지 않은데 외부에서
       접속하면 화면을 열어주지 않는다. 예전에는 '비밀번호 없으면 공개'였는데,
       그 상태로 클라우드에 올리면 보유종목·평단가가 URL 만 알면 다 보인다.

    이 함수는 set_page_config 직후, 엔진 생성·보유종목 로드보다 **먼저** 불린다.
    통과하지 못하면 st.stop() 이므로 그 아래 코드는 실행되지 않는다.
    """
    if st.session_state.get("_authed"):
        return True

    try:
        expected = st.secrets.get("app_password")
    except Exception:
        expected = None
    remote = is_remote_exposed()

    if not remote and not expected:
        return True                      # 로컬 실행 — 인증 없이 사용

    st.title(APP_NAME)
    st.caption(f"업데이트 {APP_UPDATED}")

    if remote and not expected:
        st.error(
            "**접속 비밀번호가 설정되지 않아 화면을 열 수 없습니다.**\n\n"
            "이 앱에는 보유종목·평균매수가가 들어 있어, 비밀번호 없이 외부에 "
            "공개하지 않습니다.\n\n"
            "Streamlit Cloud → **Settings → Secrets** 에 아래 한 줄을 넣고 "
            "앱을 재시작하세요.")
        st.code('app_password = "원하는비밀번호"', language="toml")
        st.stop()

    pw = st.text_input("접속 비밀번호", type="password", key="_pw_input")
    if pw:
        if pw == expected:
            st.session_state["_authed"] = True
            st.rerun()
        st.error("비밀번호가 맞지 않습니다.")
    st.stop()

st.set_page_config(
    page_title=APP_TITLE,
    page_icon="⚙️",
    layout="wide",
    # 좁은 화면에서는 자동으로 접힌다 — 모바일에서 사이드바가 본문을 덮으면
    # 결론을 볼 수가 없다
    initial_sidebar_state="auto"
)

# Secrets 에 app_password 가 설정돼 있을 때만 인증을 요구한다 (없으면 그대로 공개)
check_password()

# ── 테마 토글 (라이트/다크) ────────────────────────────────────────────────
# 화면 배경·본문 텍스트·카드 여백을 전환한다. 기존 정보 카드는 자체 배경(다크)을
# 유지해 라이트 모드에서는 '흰 바탕 위 다크 카드' 대시보드 스타일이 된다.
if 'ui_theme' not in st.session_state:
    st.session_state['ui_theme'] = 'dark'
_theme = st.session_state['ui_theme']
# ── 디자인 토큰 (docs/REDESIGN_BRIEF_v2_ko.md — 사용자 지정 hex 그대로) ────
import ui_kit as _uk          # 색·간격·컴포넌트의 유일 출처

# 색은 여기 한 곳에서만 정의한다 (ui_kit 팔레트가 유일 출처 — 14토큰).
# 화면 어디서도 새 색을 만들지 않는다: 강조는 색이 아니라 크기·위치로 준다.
def _pal(_p):
    return dict(bg1=_p['bg'], bg2=_p['card'], surface=_p['card'],
                hover=_p['raised'], border=_p['line'], tx1=_p['tx1'],
                tx2=_p['tx2'], tx3=_p['tx3'], brand=_p['brand'],
                up=_p['up'], down=_p['down'], pos=_p['pos'],
                warn=_p['warn'], neg=_p['neg'])


_TOK = {'dark': _pal(_uk.DARK), 'light': _pal(_uk.LIGHT)}[_theme]
_APP_BG = _TOK['bg1']
_APP_TX = _TOK['tx1']
_SB_BG = _TOK['bg2']

# 흩어진 인라인 다크 표면·경계선을 토큰으로 접합한다 — 카드마다 다른 색 금지 (v2)
_OLD_SURFACES = ['#161D2A', '#161D2A', '#161D2A', '#161D2A', '#161D2A',
                 '#1C2635', '#1C2635', '#161D2A', '#0B0F17']
_OLD_ELEVATED = ['#1C2635', '#1C2635', '#222C3C']
_OLD_BORDERS = ['#1C2635', '#222C3C', '#222C3C', '#222C3C', '#222C3C']
_ACCENT_BORDERS = ['#4C8DFF', '#0a84ff', '#4C8DFF', '#4C8DFF', '#35C98B',
                   '#F2B84B', '#F2B84B', '#4C8DFF', '#4C8DFF']


def _hex_to_rgb_str(c):
    c = c.lstrip('#')
    return f"rgb({int(c[0:2], 16)}, {int(c[2:4], 16)}, {int(c[4:6], 16)})"


def _sel(prop, colors, extra=''):
    # 주의: Streamlit 이 인라인 hex 를 'prop: rgb(r, g, b)' 로 정규화한다 —
    # hex 형태만 매칭하면 셀렉터가 통째로 헛돈다. 두 표기를 모두 커버한다.
    out = []
    for c in colors:
        for v in (c, _hex_to_rgb_str(c)):
            for sp in ('', ' '):
                out.append(f'.stApp div[style*="{prop}:{sp}{v}"]{extra}')
    return ',\n'.join(out)


# 카드 표면은 양 테마 모두 '단일 다크'로 고정한다.
# 라이트에서 이 카드들을 흰색으로 바꾸면, 내부 글자색이 밝은 색으로 하드코딩돼
# 있어 통째로 사라진다(과거 라이트 모드 실패의 원인). 흰 배경 위 다크 카드는
# 대시보드 관례이기도 하다 — 대신 9종이던 카드색을 하나로 통일한다.
_CARD_BG = '#161D2A'
_CARD_BG_ELEV = '#1C2635'

_CSS_SURFACE_MAP = f"""
    {_sel('background-color', _OLD_SURFACES)},
    {_sel('background', _OLD_SURFACES)} {{
        background-color: {_CARD_BG} !important;
        background-image: none !important;
    }}
    {_sel('background-color', _OLD_ELEVATED)},
    {_sel('background', _OLD_ELEVATED)} {{
        background-color: {_CARD_BG_ELEV} !important;
    }}
    .stApp div[style*="linear-gradient(135deg,#161D2A"],
    .stApp div[style*="linear-gradient(135deg, rgb(20, 20, 22)"] {{
        /* 결론 배너는 양 테마 모두 다크 카드 — 내부 글자가 밝은 색 하드코딩이라
           라이트 surface(흰색)로 바꾸면 글자가 사라진다 */
        background: #161D2A !important;
    }}
"""
_CSS_BORDER_MAP = ',\n'.join(
    f'.stApp div[style*="border:{w} solid {v}"],'
    f'.stApp div[style*="border: {w} solid {v}"]'
    for w in ('1px', '1.5px', '2px')
    for c in (_OLD_BORDERS + _ACCENT_BORDERS)
    for v in (c, _hex_to_rgb_str(c))
) + ' { border-color: #222C3C !important; }'   # 다크 카드 위 경계선 — 양 테마 동일

st.markdown(f"""
<style>
    /* v2 디자인 토큰 */
    :root {{
        --q-bg1: {_TOK['bg1']}; --q-bg2: {_TOK['bg2']};
        --q-surface: {_TOK['surface']}; --q-hover: {_TOK['hover']};
        --q-border: {_TOK['border']};
        --q-tx1: {_TOK['tx1']}; --q-tx2: {_TOK['tx2']};
        --q-brand: {_TOK['brand']}; --q-pos: {_TOK['pos']};
        --q-warn: {_TOK['warn']}; --q-neg: {_TOK['neg']};
    }}
    /* 프리미엄 타이포그래피 — 숫자는 고정폭 자릿수(tabular-nums)로 정렬 */
    .stApp {{
        background-color: {_APP_BG};
        color: {_APP_TX};
        /* 애플 시스템 폰트를 먼저 찾고, 없으면 Pretendard·Inter 로 자연스럽게
           내려간다. 애플 폰트 파일을 배포하지 않는다 — 설치된 환경에서만 쓴다. */
        font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display",
                     "SF Pro Text", "Apple SD Gothic Neo", "Pretendard",
                     "Pretendard Variable", "Inter", "Noto Sans KR",
                     "Segoe UI", Roboto, "Malgun Gothic", sans-serif;
        font-feature-settings: "tnum" 1, "case" 1, "ss01" 1;
        font-variant-numeric: tabular-nums;
        letter-spacing: -0.011em;
        -webkit-font-smoothing: antialiased;
        -moz-osx-font-smoothing: grayscale;
        text-rendering: optimizeLegibility;
    }}
    /* 큰 글자일수록 자간을 좁힌다 — 애플이 크기별로 트래킹을 다르게 주는 이유.
       같은 자간을 모든 크기에 쓰면 큰 제목이 성기게 벌어져 보인다. */
    .stApp h1, .stApp [style*="font-size:40px"], .stApp [style*="font-size: 40px"] {{
        letter-spacing: -0.024em !important; }}
    .stApp h2, .stApp [style*="font-size:34px"], .stApp [style*="font-size:28px"] {{
        letter-spacing: -0.021em !important; }}
    .stApp h3, .stApp [style*="font-size:22px"], .stApp [style*="font-size:20px"] {{
        letter-spacing: -0.017em !important; }}
    /* 본문은 여유 있는 행간 — 한글은 라틴보다 조금 더 필요하다 */
    .stApp p, .stApp li {{ line-height: 1.62; }}
    /* 숫자는 어디서나 자릿수 고정 — 표에서 자리가 흔들리면 비교가 안 된다 */
    .stApp [style*="font-variant-numeric"], .stApp td, .stApp th {{
        font-variant-numeric: tabular-nums; }}
    /* 표면·경계선 접합 — 카드마다 다른 색 금지 */
    {_CSS_SURFACE_MAP}
    {_CSS_BORDER_MAP}
    .stApp b, .stApp strong {{ font-weight: 600; }}
    /* 카드 공통 폴리시 — 부드러운 그림자 + 미세 호버 */
    .stApp div[style*="border-radius:14px"],
    .stApp div[style*="border-radius:16px"],
    .stApp div[style*="border-radius:20px"] {{
        box-shadow: 0 2px 14px rgba(0,0,0,{0.35 if _theme == 'dark' else 0.10});
        transition: transform .12s ease, box-shadow .12s ease;
    }}
    .stApp div[style*="border-radius:14px"]:hover {{
        transform: translateY(-1px);
    }}
    /* 본문 폭은 ui_kit.global_css 한 곳에서만 정한다 — 두 곳에서 정하면
       나중에 주입된 쪽이 이겨서 어느 값이 실제로 적용됐는지 알 수 없다. */
    /* v7 타입 스케일 — 12·13·15·16·17·20·22·28·34·40 열 단계만 쓴다.
       광학 보정: 큰 글자는 자간을 좁히고, 작은 글자는 살짝 벌린다 (애플 방식) */
    .stApp h1:not([style*="font-size"]) {{ font-size: 28px !important;
                    font-weight: 700 !important;
                letter-spacing: -0.021em !important; line-height: 1.22 !important; }}
    .stApp h2 {{ font-size: 22px !important; font-weight: 700 !important;
                letter-spacing: -0.017em !important; line-height: 1.26 !important; }}
    .stApp h3 {{ font-size: 20px !important; font-weight: 600 !important;
                letter-spacing: -0.014em !important; line-height: 1.3 !important; }}
    .stApp h4 {{ font-size: 17px !important; font-weight: 600 !important;
                letter-spacing: -0.01em !important; }}
    .stApp hr {{ margin: 24px 0 !important; opacity: .75; }}
    /* Streamlit 기본 본문(14px)이 스케일 밖이라 컨테이너를 직접 겨냥한다 */
    .stApp .stMarkdown p, .stApp .stMarkdown li,
    .stApp [data-testid="stMarkdownContainer"] p,
    .stApp [data-testid="stMarkdownContainer"] li,
    .stApp [data-testid="stMarkdownContainer"] > b,
    .stApp [data-testid="stMarkdownContainer"] > strong {{
        font-size: 15px; line-height: 1.62; letter-spacing: -0.003em; }}
    .stApp [data-testid="stCaptionContainer"] [data-testid="stMarkdownContainer"] p {{
        font-size: 13px; }}
    /* 알림 아이콘·코드 조각도 스케일 안으로 (11px·18px 잔재 제거) */
    .stApp [data-testid="stAlertDynamicIcon"] {{ font-size: 17px !important; }}
    .stApp code {{ font-size: 1em !important; }}
    .stApp [data-testid="stCaptionContainer"] p {{
        font-size: 13px !important; line-height: 1.55 !important;
        letter-spacing: 0 !important; }}
    /* 지수·모델 카드 숫자는 배경정보 — 첫 화면 최대 요소로 만들지 않는다 (v2) */
    .stApp [data-testid="stMetricValue"] {{ font-size: 22px !important;
        font-weight: 600 !important; letter-spacing: -0.015em !important; }}
    .stApp [data-testid="stMetricLabel"] {{ font-size: 13px !important;
        font-weight: 500 !important; }}
    /* 40px 이상 대형 숫자·헤드라인의 광학 자간 (인라인 크기에도 적용) */
    .stApp [style*="font-size:40px"], .stApp [style*="font-size: 40px"] {{
        letter-spacing: -0.028em; }}
    .stApp [style*="font-size:34px"], .stApp [style*="font-size: 34px"] {{
        letter-spacing: -0.022em; }}
    .stApp [style*="font-size:28px"], .stApp [style*="font-size: 28px"] {{
        letter-spacing: -0.018em; }}

    /* v5 — 애플·삼성풍 정돈: 접이식 패널을 카드 언어로 통일, pill 버튼, 여백 */
    .stApp [data-testid="stExpander"] {{
        background: {_TOK['surface']};
        border: 1px solid {_TOK['border']} !important;
        border-radius: 12px !important;
        margin-bottom: 8px;
        overflow: hidden;
    }}
    .stApp [data-testid="stExpander"] summary {{
        font-size: 15px !important; font-weight: 700 !important;
        padding: 12px 20px !important;
    }}
    .stApp [data-testid="stExpander"] summary:hover {{
        background: {_TOK['hover']};
    }}
    .stApp [data-testid="stExpander"] details {{ border: none !important; }}
    .stApp .stButton > button,
    .stApp [data-testid="stDownloadButton"] button {{
        border-radius: 999px !important;
        border: 1px solid {_TOK['border']} !important;
        font-weight: 700 !important;
    }}
    .stApp .stButton > button:hover {{
        border-color: {_TOK['brand']} !important;
        color: {_TOK['brand']} !important;
    }}
    .stApp hr {{ border-color: {_TOK['border']} !important; }}
    .stApp [data-testid="stRadio"] label {{ font-size: 15px; }}

    /* v6 애플 정돈 — 알림·코드·구분선의 색 소음 제거 */
    .stApp [data-testid="stAlert"] {{
        background: {_TOK['surface']} !important;
        border: 1px solid {_TOK['border']} !important;
        border-left-width: 3px !important;
        border-radius: 12px !important;
        box-shadow: none !important;
    }}
    .stApp [data-testid="stAlert"]:has([data-testid="stAlertContentSuccess"]) {{
        border-left-color: {_TOK['pos']} !important; }}
    .stApp [data-testid="stAlert"]:has([data-testid="stAlertContentInfo"]) {{
        border-left-color: {_TOK['brand']} !important; }}
    .stApp [data-testid="stAlert"]:has([data-testid="stAlertContentWarning"]) {{
        border-left-color: {_TOK['warn']} !important; }}
    .stApp [data-testid="stAlert"]:has([data-testid="stAlertContentError"]) {{
        border-left-color: {_TOK['neg']} !important; }}
    /* 코드 조각은 칩이 아니라 조용한 보조 텍스트다 */
    .stApp code, [data-testid="stSidebar"] code {{
        background: transparent !important;
        color: {_TOK['tx2']} !important;
        padding: 0 !important;
        font-size: 1em !important;   /* 스케일 유지 — 축소하면 11px 잔재가 생긴다 */
        font-weight: 600;
    }}
    [data-testid="stSidebar"] hr {{ margin: 16px 0 !important; }}

    /* 종목 검색 입력 — 사이드바에서 가장 눈에 띄는 요소로 (사용자 요청) */
    [data-testid="stSidebar"] input[aria-label*="종목명"] {{
        border: 2px solid {_TOK['brand']} !important;
        box-shadow: 0 0 0 3px {_TOK['brand']}30 !important;
        background-color: #1C2635 !important;
        color: #ffffff !important;
        font-size: 15px !important;
        font-weight: 700 !important;
        padding: 12px 12px !important;
        border-radius: 10px !important;
    }}
    [data-testid="stSidebar"] input[aria-label*="종목명"]::placeholder {{
        color: #9DAABC !important; font-weight: 600 !important;
    }}
    [data-testid="stSidebar"] input[aria-label*="종목명"]:focus {{
        box-shadow: 0 0 0 4px {_TOK['brand']}55 !important;
    }}
</style>
""", unsafe_allow_html=True)

# ── UI 킷 전역 규칙 (애플 정돈: 테두리 제거·표면 대비·8pt 리듬) ────────────
# 카드마다 인라인 HTML을 따로 쓰던 방식이 통일 실패의 원인이었다.
# 이제 표면·여백·위젯 스타일은 ui_kit 한 곳에서 정의한다.

st.markdown(f"<style>{_uk.global_css(_theme)}</style>", unsafe_allow_html=True)

# ── 글로벌 내비게이션 (정보구조 1단계 — 섹션 앵커 바) ─────────────────────
# 화면 분리 전 단계: 단일 페이지의 주요 섹션을 상단 바에서 바로 이동한다.
# 메뉴 이름은 docs/REDESIGN_BRIEF_ko.md 의 정보구조를 따른다.
# 툴바 규칙: 이름표(브랜드)는 왼쪽 끝에 한 번, 이동 링크는 조용하게, 지금
# 보고 있는 종목은 오른쪽 끝에 항상. 링크를 전부 굵게 하면 무엇이 현재
# 위치인지 알 수 없으므로 기본은 보조색·보통 굵기로 두고 hover에서만 올린다.
st.markdown(f"""
<style>
.qnav {{ position: sticky; top: 0; z-index: 999; display: flex; gap: 2px;
  flex-wrap: wrap; align-items: center; padding: 8px 16px;
  background: {_TOK['bg2']}; border-radius: 14px; margin-bottom: 16px; }}
.qnav a {{ color: {_TOK['tx2']} !important; text-decoration: none !important;
  font-size: 13px; font-weight: 500; padding: 4px 12px; border-radius: 9px;
  white-space: nowrap; transition: background .12s, color .12s; }}
.qnav a:hover {{ background: {_TOK['hover']};
  color: {_TOK['tx1']} !important; }}
.qnav .brand {{ font-weight: 600; margin-right: 4px; font-size: 15px;
  letter-spacing: -0.01em; color: {_TOK['tx1']}; }}
.qnav .rule {{ width: 1px; height: 15px; background: {_TOK['border']};
  margin: 0 8px; flex: 0 0 auto; }}
/* 엔진 버전 칩 묶음 — 위 `.qnav a` 의 패딩·글자색을 물려받으면 안 된다.
   버전은 읽는 값이지 누르는 메뉴가 아니므로 조용해야 한다. */
.qnav a.qvers {{ padding: 2px 4px !important; font-size: 12px !important;
  font-weight: 400 !important; white-space: normal !important;
  border-radius: 7px; }}
.qnav a.qvers:hover {{ background: {_TOK['hover']}; }}
.qnav .here {{ margin-left: auto; font-size: 12px; color: {_TOK['tx3']};
  padding-left: 12px; white-space: nowrap; }}
.qnav .here b {{ color: {_TOK['tx1']}; font-weight: 600; }}
[id^="nav-"] {{ scroll-margin-top: 68px; }}
</style>
<div id="nav-top"></div>
""", unsafe_allow_html=True)

_NAV_SLOT = st.empty()          # 종목이 확정된 뒤 채운다 (자리는 지금 잡는다)


def _render_toolbar(here_html: str = '') -> None:
    # 내비는 좌측 사이드바 한 곳에만 둔다 (참조 화면과 같다). 여기는 지금
    # 보고 있는 종목만 표시한다 — 같은 링크를 두 곳에 두면 어느 쪽이
    # 현재 위치인지 알 수 없다.
    if not here_html:
        _NAV_SLOT.empty()
        return
    # 상단 바는 **한 줄**이다. 예전에는 두 줄이었고 룰북·산식이 양쪽에 두 번,
    # '운영 버전' 칩은 모델 축과 같은 값이라 세 번째 중복이었다.
    # 왼쪽: 상태 점 + 되돌려 본 판단 수 + 엔진 5축 버전 (누르면 업데이트 이력)
    # 오른쪽: 지금 보고 있는 종목
    _AX_KO = {'model': '모델', 'scoring': '산식', 'rulebook': '룰북',
              'schema': '스키마', 'news': '뉴스'}
    _chips = ''.join(
        f"<span style='display:inline-flex; align-items:baseline; gap:4px; "
        f"margin-right:8px; white-space:nowrap;'>"
        f"<span style='font-size:12px; color:{_TOK['tx3']};'>{_ko}</span>"
        f"<span style='font-size:12px; font-weight:700; color:{_TOK['tx2']}; "
        f"font-variant-numeric:tabular-nums;'>{_VER_NOW.get(_ax, '—')}</span>"
        f"</span>"
        for _ax, _ko in _AX_KO.items())

    _st_txt, _st_tone, _st_more = _STATUS_TOP
    _status = (
        f"<span style='display:inline-flex; align-items:center; gap:7px; "
        f"margin-right:10px; white-space:nowrap;'>"
        f"<span style='width:6px; height:6px; border-radius:50%; "
        f"background:{_TOK.get(_st_tone, _TOK['tx2'])}; "
        f"display:inline-block;'></span>"
        f"<span style='font-size:12px; color:{_TOK.get(_st_tone, _TOK['tx2'])};'>"
        f"{_uk._esc(_st_txt)}</span></span>"
        + (f"<span style='font-size:12px; color:{_TOK['tx3']}; "
           f"margin-right:10px; white-space:nowrap;'>{_uk._esc(_st_more)}"
           f"</span>" if _st_more else ''))

    _NAV_SLOT.markdown(
        f'<div class="qnav">{_status}'
        f"<a href='#nav-updates' class='qvers' "
        f"title='누르면 업데이트 이력으로 갑니다'>{_chips}</a>"
        f'<span class="here">{here_html}</span></div>',
        unsafe_allow_html=True)


# ── 최상단 업데이트 바 (탭보다 위) ──────────────────────────────────────
# 사용자 요구: "업데이트가 가장 중요하다 — 엔진 맨 위, 탭 위에 넣어라".
# 한 건만 보여 준다. 전체는 아래 히스토리에서 본다.
import versioning as _ver
_VER_NOW = _ver.snapshot()

# 상태 줄은 따로 그리지 않는다 — 위 내비 바 하나로 합쳤다.
# 예전에는 줄이 둘이었고 룰북·산식이 양쪽에 **두 번** 나왔으며,
# '운영 버전' 칩은 모델 축과 같은 값이라 세 번째 중복이었다.
try:
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           '.portfolio', 'calibration.json'), encoding='utf-8') as _f:
        _cal_top = json.load(_f)
    _STATUS_TOP = ('데이터 점검 완료', 'pos',
                   f"되돌려 본 판단 {_cal_top.get('total_cases', 0):,}건")
except Exception:
    _STATUS_TOP = ('데이터 점검 중', 'warn', '')

_render_toolbar()               # 우선 비워서 그린다 (자리 이동 방지)

st.markdown(f"""
<style>
    /* 사이드바 — 색은 토큰에서만 온다 (테마 전환 시 함께 바뀐다) */
    
    /* 사이드바 고대비(High-Contrast) 가독성 100% 최적화 */
    [data-testid="stSidebar"] {{
        background-color: {_uk.DARK_NAV if _theme == 'dark' else _uk.LIGHT_NAV} !important;
        border-right: 1px solid {_TOK['border']} !important;
    }}
    
    /* (삭제) [data-testid="stSidebar"] * {{ color:#fff }}
       전 요소를 흰색·굵게 만들어 라벨과 값이 구분되지 않았다.
       사이드바도 본문과 같은 3단 텍스트 위계를 쓴다. */
    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3,
    [data-testid="stSidebar"] h4,
    [data-testid="stSidebar"] h5,
    [data-testid="stSidebar"] h6 {{
        color: {_TOK['tx1']} !important;
        font-weight: 600 !important;
        letter-spacing: -0.014em;
        margin-top: 24px !important;
        margin-bottom: 8px !important;
    }}

    /* 크기·굵기를 직접 지정한 요소(로고 워드마크 등)는 제외한다.
       일괄 규칙이 로고까지 13px 로 눌러 마크(34px) 옆에서 찌그러졌었다. */
    [data-testid="stSidebar"] p:not([style*="font-size"]),
    [data-testid="stSidebar"] span:not([style*="font-size"]),
    [data-testid="stSidebar"] label:not([style*="font-size"]),
    [data-testid="stSidebar"] li,
    [data-testid="stSidebar"] small,
    [data-testid="stSidebar"] div[data-testid="stCaptionContainer"] {{
        color: {_TOK['tx2']} !important;
        font-size: 13px !important;
        font-weight: 400 !important;
    }}

    /* 사이드바 입력창 & 드롭다운 가독성 강화 */
    [data-testid="stSidebar"] input {{
        background-color: {_TOK['hover']} !important;
        color: {_TOK['tx1']} !important;
        border-radius: 8px !important;
        font-weight: bold !important;
        font-size: 16px !important;
    }}
    
    [data-testid="stSidebar"] [data-baseweb="select"] {{
        background-color: {_TOK['hover']} !important;
        border-radius: 8px !important;
    }}

    [data-testid="stSidebar"] [data-baseweb="select"] * {{
        color: #ffffff !important;
        background-color: {_TOK['hover']} !important;
        font-weight: bold !important;
    }}

    /* (v6) 사이드바 code 는 칩이 아니라 조용한 보조 텍스트 — 토큰 블록에서 통일 */

    /* 메인 지표 카드 고대비 스타일 */
    [data-testid="stMetricValue"] {{
        font-size: 34px !important;
        font-weight: 700 !important;
        color: #ffffff !important;
    }}
    
    [data-testid="stMetricLabel"] {{
        color: {_TOK['tx2']} !important;
        font-size: 15px !important;
        font-weight: 700 !important;
        margin-bottom: 4px !important;
    }}
    
    [data-testid="stMetricDelta"] {{
        font-size: 15px !important;
        font-weight: 700 !important;
    }}

    /* 교차 검증 상태표 표 전용 스타일 */
    .cross-val-matrix {{
        width: 100%;
        border-collapse: collapse;
        margin: 12px 0 20px 0;
        background: {_TOK['bg2']};
        border-radius: 12px;
        overflow: hidden;
        }}
    .cross-val-matrix th {{
        background: {_TOK['hover']};
        color: {_TOK['brand']};
        padding: 12px 16px;
        font-size: 15px;
        font-weight: bold;
        text-align: left;
    }}
    .cross-val-matrix td {{
        padding: 12px 16px;
        border-top: 1px solid {_TOK['border']};
        color: {_TOK['tx1']};
        font-size: 15px;
    }}

    /* 탭 스타일 고대비 */
    .stTabs [data-baseweb="tab-list"] {{ gap: 6px; background-color: {_TOK['bg2']}; padding: 4px; border-radius: 12px; }}
    .stTabs [data-baseweb="tab"] {{ height: 42px; border-radius: 8px; color: {_TOK['tx2']} !important; font-weight: 700; font-size: 15px; }}
    .stTabs [aria-selected="true"] {{ background-color: {_TOK['border']} !important; color: #ffffff !important; font-weight: 700; }}

    /* 버튼 기본 테마 강제 */
    .stButton > button {{
        background-color: {_TOK['hover']} !important;
        color: #ffffff !important;
        font-weight: bold !important;
    }}
    .stButton > button:hover {{
        border-color: {_TOK['brand']} !important;
        color: {_TOK['brand']} !important;
    }}
    .stButton > button p {{
        color: inherit !important;
        font-weight: bold !important;
    }}

    h1, h2, h3, h4, h5, h6 {{ color: #ffffff !important; font-weight: 700 !important; }}
    p, span, li, label {{ color: {_TOK['tx1']}; font-size: 16px; }}
</style>
""", unsafe_allow_html=True)

# 라이트 모드 오버라이드 — 구형 다크 규칙 뒤에 와야 이긴다.
# 핵심 원리: 다크 카드 내부 글자는 전부 인라인 color 를 갖고 있다. 그래서
# **인라인 color 가 없는 요소만** 어둡게 바꾸면, 흰 바탕의 일반 본문은 읽히고
# 다크 카드 내부는 그대로 보존된다 (:not([style*="color"]) 선택자).
if _theme == 'light':
    # 가드 원칙: ① 인라인 color 를 가진 요소는 건드리지 않는다 ② 인라인 background
    # 를 가진 요소(다크 카드)의 **자손 전체**를 건드리지 않는다 — <b>·<span> 이
    # 부모의 밝은 색을 상속받아야 하기 때문 ③ 버튼·알림·코드칩은 별도 규칙.
    _G = (':not([style*="color"]):not(div[style*="background"] *)'
          ':not(table[style*="background"] *):not(.cross-val-matrix *)'
          ':not([data-testid="stAlert"] *):not(button *):not(code):not(kbd)')
    st.markdown(f"""
    <style>
        .stApp {{ background-color: {_TOK['bg1']} !important; }}
        .stApp > header {{ background-color: transparent !important; }}

        /* 흰 바탕의 일반 텍스트 → 어둡게 (다크 카드 자손·버튼·알림 제외) */
        .stApp p{_G}, .stApp span{_G}, .stApp li{_G}, .stApp label{_G},
        .stApp em{_G}, .stApp strong{_G}, .stApp b{_G},
        .stApp td{_G}, .stApp th{_G} {{
            color: {_TOK['tx1']} !important;
        }}
        .stApp h1{_G}, .stApp h2{_G}, .stApp h3{_G},
        .stApp h4{_G}, .stApp h5{_G}, .stApp h6{_G} {{
            color: {_TOK['tx1']} !important;
        }}
        .stApp [data-testid="stCaptionContainer"] p{_G} {{ color: {_TOK['tx2']} !important; }}

        /* 메트릭 숫자 */
        [data-testid="stMetricValue"] {{ color: {_TOK['tx1']} !important; }}
        [data-testid="stMetricLabel"] {{ color: {_TOK['tx2']} !important; }}

        /* 알림 박스: 배경이 반투명 틴트라 라이트 모드에선 밝아진다 → 글자는 어둡게 */
        .stApp [data-testid="stAlert"] p, .stApp [data-testid="stAlert"] span,
        .stApp [data-testid="stAlert"] li, .stApp [data-testid="stAlert"] b,
        .stApp [data-testid="stAlert"] strong {{
            color: {_TOK['tx1']} !important;
        }}
        /* 코드 조각: 라이트에서도 칩이 아니라 조용한 보조 텍스트 (v6) */
        .stApp code, .stApp kbd,
        [data-testid="stSidebar"] code, [data-testid="stSidebar"] kbd {{
            background-color: transparent !important; color: {_TOK['tx2']} !important;
            padding: 0 !important;
        }}
        /* 버튼도 테마를 따른다. 라이트에서만 버튼을 다크로 남기면
           숫자 입력의 +/- 나 드롭다운 화살표까지 밝은 글자가 돼 흰 배경
           위에서 사라진다 — 특례를 두지 않는 쪽이 결국 덜 깨진다. */
        .stApp [data-testid^="stBaseButton"],
        .stApp [data-testid^="stBaseButton"] *,
        [data-testid="stSidebar"] [data-testid^="stBaseButton"],
        [data-testid="stSidebar"] [data-testid^="stBaseButton"] * {{
            color: {_TOK['tx1']} !important;
        }}
        /* 배경도 같이 잡아야 한다 — 다크 규칙이 더 구체적이라 이겼고,
           그 결과 다크 버튼 위에 라이트 글자가 얹혀 안 보였다.
           같은 모양의 셀렉터로 맞받아 배경을 테마 쪽으로 되돌린다. */
        /* help= 가 붙은 버튼은 툴팁 span 으로 한 겹 더 감싸여 있어
           div[data-testid="stButton"] > button 에 걸리지 않는다 */
        section[data-testid="stSidebar"] div[data-testid="stButton"] > button,
        section[data-testid="stSidebar"] span[data-testid="stTooltipHoverTarget"] > button,
        .stApp span[data-testid="stTooltipHoverTarget"] > button,
        .stApp div[data-testid="stButton"] > button,
        .stApp div[data-testid="stDownloadButton"] > button {{
            background: {_TOK['bg2']} !important;
            border: 1px solid {_TOK['border']} !important;
        }}
        section[data-testid="stSidebar"] div[data-testid="stButton"] > button *,
        section[data-testid="stSidebar"] span[data-testid="stTooltipHoverTarget"] > button *,
        .stApp span[data-testid="stTooltipHoverTarget"] > button *,
        .stApp div[data-testid="stButton"] > button *,
        .stApp div[data-testid="stDownloadButton"] > button * {{
            color: {_TOK['tx1']} !important;
        }}
        /* 탭 라벨 */
        .stApp [data-testid="stTabs"] button p {{ color: {_TOK['tx2']} !important; }}
        .stApp [data-testid="stTabs"] button[aria-selected="true"] p {{
            color: {_TOK['brand']} !important; font-weight: 700 !important; }}

        [data-testid="stSidebar"] {{ background-color: {_TOK['bg2']} !important;
                                    border-right: 1px solid {_TOK['border']} !important; }}
        [data-testid="stSidebar"] p{_G}, [data-testid="stSidebar"] span{_G},
        [data-testid="stSidebar"] li{_G}, [data-testid="stSidebar"] label{_G},
        [data-testid="stSidebar"] b{_G}, [data-testid="stSidebar"] strong{_G},
        [data-testid="stSidebar"] h1{_G}, [data-testid="stSidebar"] h2{_G},
        [data-testid="stSidebar"] h3{_G}, [data-testid="stSidebar"] h4{_G} {{
            color: {_TOK['tx1']} !important;
        }}
        hr {{ border-color: {_TOK['border']} !important; }}

        /* 인라인 color 가 박힌 글자는 위 가드를 통과해 라이트에서도
           다크 색으로 남는다. 글자 토큰 3단만 라이트 등가로 되돌린다
           (의미색 상승·하락·경고는 건드리지 않는다). */
        .stApp [style*="color:#F3F6FA"],
        .stApp [style*="color: #F3F6FA"],
        .stApp [style*="color:#f3f6fa"],
        .stApp [style*="color: #f3f6fa"],
        .stApp [style*="color:rgb(243, 246, 250)"],
        .stApp [style*="color: rgb(243, 246, 250)"] {{
            color: {_TOK['tx1']} !important; }}
        .stApp [style*="color:#9DAABC"],
        .stApp [style*="color: #9DAABC"],
        .stApp [style*="color:#9daabc"],
        .stApp [style*="color: #9daabc"],
        .stApp [style*="color:rgb(157, 170, 188)"],
        .stApp [style*="color: rgb(157, 170, 188)"] {{
            color: {_TOK['tx2']} !important; }}
        .stApp [style*="color:#7C8AA0"],
        .stApp [style*="color: #7C8AA0"],
        .stApp [style*="color:#7c8aa0"],
        .stApp [style*="color: #7c8aa0"],
        .stApp [style*="color:rgb(124, 138, 160)"],
        .stApp [style*="color: rgb(124, 138, 160)"] {{
            color: {_TOK['tx3']} !important; }}

        /* 의미색(상승·하락·좋음·경고)도 라이트 등가로 — 다크 팔레트
           값은 흰 카드 위에서 대비가 3.4 안팎으로 떨어진다 (실측). */
        .stApp [style*="color:#4C8DFF"],
        .stApp [style*="color: #4C8DFF"],
        .stApp [style*="color:#4c8dff"],
        .stApp [style*="color: #4c8dff"],
        .stApp [style*="color:rgb(76, 141, 255)"],
        .stApp [style*="color: rgb(76, 141, 255)"] {{
            color: {_TOK['brand']} !important; }}
        .stApp [style*="color:#35C98B"],
        .stApp [style*="color: #35C98B"],
        .stApp [style*="color:#35c98b"],
        .stApp [style*="color: #35c98b"],
        .stApp [style*="color:rgb(53, 201, 139)"],
        .stApp [style*="color: rgb(53, 201, 139)"] {{
            color: {_TOK['pos']} !important; }}
        .stApp [style*="color:#F2B84B"],
        .stApp [style*="color: #F2B84B"],
        .stApp [style*="color:#f2b84b"],
        .stApp [style*="color: #f2b84b"],
        .stApp [style*="color:rgb(242, 184, 75)"],
        .stApp [style*="color: rgb(242, 184, 75)"] {{
            color: {_TOK['warn']} !important; }}
        .stApp [style*="color:#F26161"],
        .stApp [style*="color: #F26161"],
        .stApp [style*="color:#f26161"],
        .stApp [style*="color: #f26161"],
        .stApp [style*="color:rgb(242, 97, 97)"],
        .stApp [style*="color: rgb(242, 97, 97)"] {{
            color: {_TOK['neg']} !important; }}
        .stApp [style*="color:#FF453A"],
        .stApp [style*="color: #FF453A"],
        .stApp [style*="color:#ff453a"],
        .stApp [style*="color: #ff453a"],
        .stApp [style*="color:rgb(255, 69, 58)"],
        .stApp [style*="color: rgb(255, 69, 58)"] {{
            color: {_TOK['up']} !important; }}
        .stApp [style*="color:#0A84FF"],
        .stApp [style*="color: #0A84FF"],
        .stApp [style*="color:#0a84ff"],
        .stApp [style*="color: #0a84ff"],
        .stApp [style*="color:rgb(10, 132, 255)"],
        .stApp [style*="color: rgb(10, 132, 255)"] {{
            color: {_TOK['down']} !important; }}

        /* 링크 — 기본 하늘색은 흰 배경에서 미달 */
        .stApp a:not(.qnav a) {{ color: {_TOK['brand']} !important; }}

        /* 반투명 틴트 카드도 라이트에선 어두운 솔리드로 바뀐다 —
           그 안쪽 글자 역시 밝은 쪽으로 되돌린다 (인라인은 rgba 로 남아
           위 hex/rgb 매칭에 걸리지 않는다). */
        .stApp div[style*="rgb(22, 29, 42)"] p,
        .stApp div[style*="rgb(22, 29, 42)"] span,
        .stApp div[style*="rgb(28, 38, 53)"] p,
        .stApp div[style*="rgb(28, 38, 53)"] span,
        /* code 가 이 목록에 없어서 코드 칩만 라이트 글자색으로 남아
           다크 카드 위에서 대비 1.99 였다 (p·span 은 이미 되돌아감). */
        .stApp div[style*="rgb(22, 29, 42)"] code,
        .stApp div[style*="rgb(28, 38, 53)"] code,
        .stApp div[style*="rgb(28, 38, 53)"] li,
        .stApp div[style*="rgb(22, 29, 42)"] li,
        .stApp div[style*="rgba(48, 209, 88"] *,
        .stApp div[style*="rgba(255, 69, 58"] *,
        .stApp div[style*="rgba(76, 141, 255"] *,
        .stApp div[style*="rgba(242, 184, 75"] *,
        .stApp div[style*="rgba(10, 132, 255"] * {{
            color: {_uk.DARK['tx1']} !important; }}

        /* 단, 양 테마에서 다크로 고정되는 카드 안쪽은 다시 밝게.
           위 규칙 뒤에 와야 같은 특이도에서 이긴다. */
        .stApp div[style*="background:#161D2A"] p,
        .stApp div[style*="background:#161D2A"] span,
        .stApp div[style*="background:#161D2A"] li,
        .stApp div[style*="background:#161D2A"] b,
        .stApp div[style*="background:#161D2A"] strong,
        .stApp div[style*="background:#161D2A"] div,
        .stApp div[style*="background: #161D2A"] p,
        .stApp div[style*="background: #161D2A"] span,
        .stApp div[style*="background: #161D2A"] li,
        .stApp div[style*="background: #161D2A"] b,
        .stApp div[style*="background: #161D2A"] strong,
        .stApp div[style*="background: #161D2A"] div,
        .stApp div[style*="background-color:#161D2A"] p,
        .stApp div[style*="background-color:#161D2A"] span,
        .stApp div[style*="background-color:#161D2A"] li,
        .stApp div[style*="background-color:#161D2A"] b,
        .stApp div[style*="background-color:#161D2A"] strong,
        .stApp div[style*="background-color:#161D2A"] div,
        .stApp div[style*="background-color: #161D2A"] p,
        .stApp div[style*="background-color: #161D2A"] span,
        .stApp div[style*="background-color: #161D2A"] li,
        .stApp div[style*="background-color: #161D2A"] b,
        .stApp div[style*="background-color: #161D2A"] strong,
        .stApp div[style*="background-color: #161D2A"] div,
        .stApp div[style*="background:#161d2a"] p,
        .stApp div[style*="background:#161d2a"] span,
        .stApp div[style*="background:#161d2a"] li,
        .stApp div[style*="background:#161d2a"] b,
        .stApp div[style*="background:#161d2a"] strong,
        .stApp div[style*="background:#161d2a"] div,
        .stApp div[style*="background: #161d2a"] p,
        .stApp div[style*="background: #161d2a"] span,
        .stApp div[style*="background: #161d2a"] li,
        .stApp div[style*="background: #161d2a"] b,
        .stApp div[style*="background: #161d2a"] strong,
        .stApp div[style*="background: #161d2a"] div,
        .stApp div[style*="background-color:#161d2a"] p,
        .stApp div[style*="background-color:#161d2a"] span,
        .stApp div[style*="background-color:#161d2a"] li,
        .stApp div[style*="background-color:#161d2a"] b,
        .stApp div[style*="background-color:#161d2a"] strong,
        .stApp div[style*="background-color:#161d2a"] div,
        .stApp div[style*="background-color: #161d2a"] p,
        .stApp div[style*="background-color: #161d2a"] span,
        .stApp div[style*="background-color: #161d2a"] li,
        .stApp div[style*="background-color: #161d2a"] b,
        .stApp div[style*="background-color: #161d2a"] strong,
        .stApp div[style*="background-color: #161d2a"] div,
        .stApp div[style*="background:rgb(22, 29, 42)"] p,
        .stApp div[style*="background:rgb(22, 29, 42)"] span,
        .stApp div[style*="background:rgb(22, 29, 42)"] li,
        .stApp div[style*="background:rgb(22, 29, 42)"] b,
        .stApp div[style*="background:rgb(22, 29, 42)"] strong,
        .stApp div[style*="background:rgb(22, 29, 42)"] div,
        .stApp div[style*="background: rgb(22, 29, 42)"] p,
        .stApp div[style*="background: rgb(22, 29, 42)"] span,
        .stApp div[style*="background: rgb(22, 29, 42)"] li,
        .stApp div[style*="background: rgb(22, 29, 42)"] b,
        .stApp div[style*="background: rgb(22, 29, 42)"] strong,
        .stApp div[style*="background: rgb(22, 29, 42)"] div,
        .stApp div[style*="background-color:rgb(22, 29, 42)"] p,
        .stApp div[style*="background-color:rgb(22, 29, 42)"] span,
        .stApp div[style*="background-color:rgb(22, 29, 42)"] li,
        .stApp div[style*="background-color:rgb(22, 29, 42)"] b,
        .stApp div[style*="background-color:rgb(22, 29, 42)"] strong,
        .stApp div[style*="background-color:rgb(22, 29, 42)"] div,
        .stApp div[style*="background-color: rgb(22, 29, 42)"] p,
        .stApp div[style*="background-color: rgb(22, 29, 42)"] span,
        .stApp div[style*="background-color: rgb(22, 29, 42)"] li,
        .stApp div[style*="background-color: rgb(22, 29, 42)"] b,
        .stApp div[style*="background-color: rgb(22, 29, 42)"] strong,
        .stApp div[style*="background-color: rgb(22, 29, 42)"] div,
        .stApp div[style*="background:#1C2635"] p,
        .stApp div[style*="background:#1C2635"] span,
        .stApp div[style*="background:#1C2635"] li,
        .stApp div[style*="background:#1C2635"] b,
        .stApp div[style*="background:#1C2635"] strong,
        .stApp div[style*="background:#1C2635"] div,
        .stApp div[style*="background: #1C2635"] p,
        .stApp div[style*="background: #1C2635"] span,
        .stApp div[style*="background: #1C2635"] li,
        .stApp div[style*="background: #1C2635"] b,
        .stApp div[style*="background: #1C2635"] strong,
        .stApp div[style*="background: #1C2635"] div,
        .stApp div[style*="background-color:#1C2635"] p,
        .stApp div[style*="background-color:#1C2635"] span,
        .stApp div[style*="background-color:#1C2635"] li,
        .stApp div[style*="background-color:#1C2635"] b,
        .stApp div[style*="background-color:#1C2635"] strong,
        .stApp div[style*="background-color:#1C2635"] div,
        .stApp div[style*="background-color: #1C2635"] p,
        .stApp div[style*="background-color: #1C2635"] span,
        .stApp div[style*="background-color: #1C2635"] li,
        .stApp div[style*="background-color: #1C2635"] b,
        .stApp div[style*="background-color: #1C2635"] strong,
        .stApp div[style*="background-color: #1C2635"] div,
        .stApp div[style*="background:#1c2635"] p,
        .stApp div[style*="background:#1c2635"] span,
        .stApp div[style*="background:#1c2635"] li,
        .stApp div[style*="background:#1c2635"] b,
        .stApp div[style*="background:#1c2635"] strong,
        .stApp div[style*="background:#1c2635"] div,
        .stApp div[style*="background: #1c2635"] p,
        .stApp div[style*="background: #1c2635"] span,
        .stApp div[style*="background: #1c2635"] li,
        .stApp div[style*="background: #1c2635"] b,
        .stApp div[style*="background: #1c2635"] strong,
        .stApp div[style*="background: #1c2635"] div,
        .stApp div[style*="background-color:#1c2635"] p,
        .stApp div[style*="background-color:#1c2635"] span,
        .stApp div[style*="background-color:#1c2635"] li,
        .stApp div[style*="background-color:#1c2635"] b,
        .stApp div[style*="background-color:#1c2635"] strong,
        .stApp div[style*="background-color:#1c2635"] div,
        .stApp div[style*="background-color: #1c2635"] p,
        .stApp div[style*="background-color: #1c2635"] span,
        .stApp div[style*="background-color: #1c2635"] li,
        .stApp div[style*="background-color: #1c2635"] b,
        .stApp div[style*="background-color: #1c2635"] strong,
        .stApp div[style*="background-color: #1c2635"] div,
        .stApp div[style*="background:rgb(28, 38, 53)"] p,
        .stApp div[style*="background:rgb(28, 38, 53)"] span,
        .stApp div[style*="background:rgb(28, 38, 53)"] li,
        .stApp div[style*="background:rgb(28, 38, 53)"] b,
        .stApp div[style*="background:rgb(28, 38, 53)"] strong,
        .stApp div[style*="background:rgb(28, 38, 53)"] div,
        .stApp div[style*="background: rgb(28, 38, 53)"] p,
        .stApp div[style*="background: rgb(28, 38, 53)"] span,
        .stApp div[style*="background: rgb(28, 38, 53)"] li,
        .stApp div[style*="background: rgb(28, 38, 53)"] b,
        .stApp div[style*="background: rgb(28, 38, 53)"] strong,
        .stApp div[style*="background: rgb(28, 38, 53)"] div,
        .stApp div[style*="background-color:rgb(28, 38, 53)"] p,
        .stApp div[style*="background-color:rgb(28, 38, 53)"] span,
        .stApp div[style*="background-color:rgb(28, 38, 53)"] li,
        .stApp div[style*="background-color:rgb(28, 38, 53)"] b,
        .stApp div[style*="background-color:rgb(28, 38, 53)"] strong,
        .stApp div[style*="background-color:rgb(28, 38, 53)"] div,
        .stApp div[style*="background-color: rgb(28, 38, 53)"] p,
        .stApp div[style*="background-color: rgb(28, 38, 53)"] span,
        .stApp div[style*="background-color: rgb(28, 38, 53)"] li,
        .stApp div[style*="background-color: rgb(28, 38, 53)"] b,
        .stApp div[style*="background-color: rgb(28, 38, 53)"] strong,
        .stApp div[style*="background-color: rgb(28, 38, 53)"] div,
        .stApp div[style*="background:#0B0F17"] p,
        .stApp div[style*="background:#0B0F17"] span,
        .stApp div[style*="background:#0B0F17"] li,
        .stApp div[style*="background:#0B0F17"] b,
        .stApp div[style*="background:#0B0F17"] strong,
        .stApp div[style*="background:#0B0F17"] div,
        .stApp div[style*="background: #0B0F17"] p,
        .stApp div[style*="background: #0B0F17"] span,
        .stApp div[style*="background: #0B0F17"] li,
        .stApp div[style*="background: #0B0F17"] b,
        .stApp div[style*="background: #0B0F17"] strong,
        .stApp div[style*="background: #0B0F17"] div,
        .stApp div[style*="background-color:#0B0F17"] p,
        .stApp div[style*="background-color:#0B0F17"] span,
        .stApp div[style*="background-color:#0B0F17"] li,
        .stApp div[style*="background-color:#0B0F17"] b,
        .stApp div[style*="background-color:#0B0F17"] strong,
        .stApp div[style*="background-color:#0B0F17"] div,
        .stApp div[style*="background-color: #0B0F17"] p,
        .stApp div[style*="background-color: #0B0F17"] span,
        .stApp div[style*="background-color: #0B0F17"] li,
        .stApp div[style*="background-color: #0B0F17"] b,
        .stApp div[style*="background-color: #0B0F17"] strong,
        .stApp div[style*="background-color: #0B0F17"] div,
        .stApp div[style*="background:#0b0f17"] p,
        .stApp div[style*="background:#0b0f17"] span,
        .stApp div[style*="background:#0b0f17"] li,
        .stApp div[style*="background:#0b0f17"] b,
        .stApp div[style*="background:#0b0f17"] strong,
        .stApp div[style*="background:#0b0f17"] div,
        .stApp div[style*="background: #0b0f17"] p,
        .stApp div[style*="background: #0b0f17"] span,
        .stApp div[style*="background: #0b0f17"] li,
        .stApp div[style*="background: #0b0f17"] b,
        .stApp div[style*="background: #0b0f17"] strong,
        .stApp div[style*="background: #0b0f17"] div,
        .stApp div[style*="background-color:#0b0f17"] p,
        .stApp div[style*="background-color:#0b0f17"] span,
        .stApp div[style*="background-color:#0b0f17"] li,
        .stApp div[style*="background-color:#0b0f17"] b,
        .stApp div[style*="background-color:#0b0f17"] strong,
        .stApp div[style*="background-color:#0b0f17"] div,
        .stApp div[style*="background-color: #0b0f17"] p,
        .stApp div[style*="background-color: #0b0f17"] span,
        .stApp div[style*="background-color: #0b0f17"] li,
        .stApp div[style*="background-color: #0b0f17"] b,
        .stApp div[style*="background-color: #0b0f17"] strong,
        .stApp div[style*="background-color: #0b0f17"] div,
        .stApp div[style*="background:rgb(11, 15, 23)"] p,
        .stApp div[style*="background:rgb(11, 15, 23)"] span,
        .stApp div[style*="background:rgb(11, 15, 23)"] li,
        .stApp div[style*="background:rgb(11, 15, 23)"] b,
        .stApp div[style*="background:rgb(11, 15, 23)"] strong,
        .stApp div[style*="background:rgb(11, 15, 23)"] div,
        .stApp div[style*="background: rgb(11, 15, 23)"] p,
        .stApp div[style*="background: rgb(11, 15, 23)"] span,
        .stApp div[style*="background: rgb(11, 15, 23)"] li,
        .stApp div[style*="background: rgb(11, 15, 23)"] b,
        .stApp div[style*="background: rgb(11, 15, 23)"] strong,
        .stApp div[style*="background: rgb(11, 15, 23)"] div,
        .stApp div[style*="background-color:rgb(11, 15, 23)"] p,
        .stApp div[style*="background-color:rgb(11, 15, 23)"] span,
        .stApp div[style*="background-color:rgb(11, 15, 23)"] li,
        .stApp div[style*="background-color:rgb(11, 15, 23)"] b,
        .stApp div[style*="background-color:rgb(11, 15, 23)"] strong,
        .stApp div[style*="background-color:rgb(11, 15, 23)"] div,
        .stApp div[style*="background-color: rgb(11, 15, 23)"] p,
        .stApp div[style*="background-color: rgb(11, 15, 23)"] span,
        .stApp div[style*="background-color: rgb(11, 15, 23)"] li,
        .stApp div[style*="background-color: rgb(11, 15, 23)"] b,
        .stApp div[style*="background-color: rgb(11, 15, 23)"] strong,
        .stApp div[style*="background-color: rgb(11, 15, 23)"] div,
        .stApp div[style*="background:#222C3C"] p,
        .stApp div[style*="background:#222C3C"] span,
        .stApp div[style*="background:#222C3C"] li,
        .stApp div[style*="background:#222C3C"] b,
        .stApp div[style*="background:#222C3C"] strong,
        .stApp div[style*="background:#222C3C"] div,
        .stApp div[style*="background: #222C3C"] p,
        .stApp div[style*="background: #222C3C"] span,
        .stApp div[style*="background: #222C3C"] li,
        .stApp div[style*="background: #222C3C"] b,
        .stApp div[style*="background: #222C3C"] strong,
        .stApp div[style*="background: #222C3C"] div,
        .stApp div[style*="background-color:#222C3C"] p,
        .stApp div[style*="background-color:#222C3C"] span,
        .stApp div[style*="background-color:#222C3C"] li,
        .stApp div[style*="background-color:#222C3C"] b,
        .stApp div[style*="background-color:#222C3C"] strong,
        .stApp div[style*="background-color:#222C3C"] div,
        .stApp div[style*="background-color: #222C3C"] p,
        .stApp div[style*="background-color: #222C3C"] span,
        .stApp div[style*="background-color: #222C3C"] li,
        .stApp div[style*="background-color: #222C3C"] b,
        .stApp div[style*="background-color: #222C3C"] strong,
        .stApp div[style*="background-color: #222C3C"] div,
        .stApp div[style*="background:#222c3c"] p,
        .stApp div[style*="background:#222c3c"] span,
        .stApp div[style*="background:#222c3c"] li,
        .stApp div[style*="background:#222c3c"] b,
        .stApp div[style*="background:#222c3c"] strong,
        .stApp div[style*="background:#222c3c"] div,
        .stApp div[style*="background: #222c3c"] p,
        .stApp div[style*="background: #222c3c"] span,
        .stApp div[style*="background: #222c3c"] li,
        .stApp div[style*="background: #222c3c"] b,
        .stApp div[style*="background: #222c3c"] strong,
        .stApp div[style*="background: #222c3c"] div,
        .stApp div[style*="background-color:#222c3c"] p,
        .stApp div[style*="background-color:#222c3c"] span,
        .stApp div[style*="background-color:#222c3c"] li,
        .stApp div[style*="background-color:#222c3c"] b,
        .stApp div[style*="background-color:#222c3c"] strong,
        .stApp div[style*="background-color:#222c3c"] div,
        .stApp div[style*="background-color: #222c3c"] p,
        .stApp div[style*="background-color: #222c3c"] span,
        .stApp div[style*="background-color: #222c3c"] li,
        .stApp div[style*="background-color: #222c3c"] b,
        .stApp div[style*="background-color: #222c3c"] strong,
        .stApp div[style*="background-color: #222c3c"] div,
        .stApp div[style*="background:rgb(34, 44, 60)"] p,
        .stApp div[style*="background:rgb(34, 44, 60)"] span,
        .stApp div[style*="background:rgb(34, 44, 60)"] li,
        .stApp div[style*="background:rgb(34, 44, 60)"] b,
        .stApp div[style*="background:rgb(34, 44, 60)"] strong,
        .stApp div[style*="background:rgb(34, 44, 60)"] div,
        .stApp div[style*="background: rgb(34, 44, 60)"] p,
        .stApp div[style*="background: rgb(34, 44, 60)"] span,
        .stApp div[style*="background: rgb(34, 44, 60)"] li,
        .stApp div[style*="background: rgb(34, 44, 60)"] b,
        .stApp div[style*="background: rgb(34, 44, 60)"] strong,
        .stApp div[style*="background: rgb(34, 44, 60)"] div,
        .stApp div[style*="background-color:rgb(34, 44, 60)"] p,
        .stApp div[style*="background-color:rgb(34, 44, 60)"] span,
        .stApp div[style*="background-color:rgb(34, 44, 60)"] li,
        .stApp div[style*="background-color:rgb(34, 44, 60)"] b,
        .stApp div[style*="background-color:rgb(34, 44, 60)"] strong,
        .stApp div[style*="background-color:rgb(34, 44, 60)"] div,
        .stApp div[style*="background-color: rgb(34, 44, 60)"] p,
        .stApp div[style*="background-color: rgb(34, 44, 60)"] span,
        .stApp div[style*="background-color: rgb(34, 44, 60)"] li,
        .stApp div[style*="background-color: rgb(34, 44, 60)"] b,
        .stApp div[style*="background-color: rgb(34, 44, 60)"] strong,
        .stApp div[style*="background-color: rgb(34, 44, 60)"] div {{
            color: {_uk.DARK['tx1']} !important; }}


        /* 양 테마에서 다크로 고정되는 카드(결론 배너·점수 카드) 안쪽은
           라이트 재색칠에서 빼는 것만으로 부족하다 — 색을 지정하지 않은
           글자가 라이트 본문색(어두움)을 상속해 다크 카드 위에서
           사라진다. 다크 표면의 자손을 명시적으로 밝은 글자로 되돌린다.
           (Streamlit 이 인라인 hex 를 rgb() 로 정규화하므로 두 표기 모두) */
        .stApp div[style*="background:#161D2A"] p:not([style*="color"]),
        .stApp div[style*="background:#161D2A"] span:not([style*="color"]),
        .stApp div[style*="background:#161D2A"] li:not([style*="color"]),
        .stApp div[style*="background: #161D2A"] p:not([style*="color"]),
        .stApp div[style*="background: #161D2A"] span:not([style*="color"]),
        .stApp div[style*="background: #161D2A"] li:not([style*="color"]),
        .stApp div[style*="background-color:#161D2A"] p:not([style*="color"]),
        .stApp div[style*="background-color:#161D2A"] span:not([style*="color"]),
        .stApp div[style*="background-color:#161D2A"] li:not([style*="color"]),
        .stApp div[style*="background-color: #161D2A"] p:not([style*="color"]),
        .stApp div[style*="background-color: #161D2A"] span:not([style*="color"]),
        .stApp div[style*="background-color: #161D2A"] li:not([style*="color"]),
        .stApp div[style*="background:#161d2a"] p:not([style*="color"]),
        .stApp div[style*="background:#161d2a"] span:not([style*="color"]),
        .stApp div[style*="background:#161d2a"] li:not([style*="color"]),
        .stApp div[style*="background: #161d2a"] p:not([style*="color"]),
        .stApp div[style*="background: #161d2a"] span:not([style*="color"]),
        .stApp div[style*="background: #161d2a"] li:not([style*="color"]),
        .stApp div[style*="background-color:#161d2a"] p:not([style*="color"]),
        .stApp div[style*="background-color:#161d2a"] span:not([style*="color"]),
        .stApp div[style*="background-color:#161d2a"] li:not([style*="color"]),
        .stApp div[style*="background-color: #161d2a"] p:not([style*="color"]),
        .stApp div[style*="background-color: #161d2a"] span:not([style*="color"]),
        .stApp div[style*="background-color: #161d2a"] li:not([style*="color"]),
        .stApp div[style*="background:rgb(22, 29, 42)"] p:not([style*="color"]),
        .stApp div[style*="background:rgb(22, 29, 42)"] span:not([style*="color"]),
        .stApp div[style*="background:rgb(22, 29, 42)"] li:not([style*="color"]),
        .stApp div[style*="background: rgb(22, 29, 42)"] p:not([style*="color"]),
        .stApp div[style*="background: rgb(22, 29, 42)"] span:not([style*="color"]),
        .stApp div[style*="background: rgb(22, 29, 42)"] li:not([style*="color"]),
        .stApp div[style*="background-color:rgb(22, 29, 42)"] p:not([style*="color"]),
        .stApp div[style*="background-color:rgb(22, 29, 42)"] span:not([style*="color"]),
        .stApp div[style*="background-color:rgb(22, 29, 42)"] li:not([style*="color"]),
        .stApp div[style*="background-color: rgb(22, 29, 42)"] p:not([style*="color"]),
        .stApp div[style*="background-color: rgb(22, 29, 42)"] span:not([style*="color"]),
        .stApp div[style*="background-color: rgb(22, 29, 42)"] li:not([style*="color"]),
        .stApp div[style*="background:#1C2635"] p:not([style*="color"]),
        .stApp div[style*="background:#1C2635"] span:not([style*="color"]),
        .stApp div[style*="background:#1C2635"] li:not([style*="color"]),
        .stApp div[style*="background: #1C2635"] p:not([style*="color"]),
        .stApp div[style*="background: #1C2635"] span:not([style*="color"]),
        .stApp div[style*="background: #1C2635"] li:not([style*="color"]),
        .stApp div[style*="background-color:#1C2635"] p:not([style*="color"]),
        .stApp div[style*="background-color:#1C2635"] span:not([style*="color"]),
        .stApp div[style*="background-color:#1C2635"] li:not([style*="color"]),
        .stApp div[style*="background-color: #1C2635"] p:not([style*="color"]),
        .stApp div[style*="background-color: #1C2635"] span:not([style*="color"]),
        .stApp div[style*="background-color: #1C2635"] li:not([style*="color"]),
        .stApp div[style*="background:#1c2635"] p:not([style*="color"]),
        .stApp div[style*="background:#1c2635"] span:not([style*="color"]),
        .stApp div[style*="background:#1c2635"] li:not([style*="color"]),
        .stApp div[style*="background: #1c2635"] p:not([style*="color"]),
        .stApp div[style*="background: #1c2635"] span:not([style*="color"]),
        .stApp div[style*="background: #1c2635"] li:not([style*="color"]),
        .stApp div[style*="background-color:#1c2635"] p:not([style*="color"]),
        .stApp div[style*="background-color:#1c2635"] span:not([style*="color"]),
        .stApp div[style*="background-color:#1c2635"] li:not([style*="color"]),
        .stApp div[style*="background-color: #1c2635"] p:not([style*="color"]),
        .stApp div[style*="background-color: #1c2635"] span:not([style*="color"]),
        .stApp div[style*="background-color: #1c2635"] li:not([style*="color"]),
        .stApp div[style*="background:rgb(28, 38, 53)"] p:not([style*="color"]),
        .stApp div[style*="background:rgb(28, 38, 53)"] span:not([style*="color"]),
        .stApp div[style*="background:rgb(28, 38, 53)"] li:not([style*="color"]),
        .stApp div[style*="background: rgb(28, 38, 53)"] p:not([style*="color"]),
        .stApp div[style*="background: rgb(28, 38, 53)"] span:not([style*="color"]),
        .stApp div[style*="background: rgb(28, 38, 53)"] li:not([style*="color"]),
        .stApp div[style*="background-color:rgb(28, 38, 53)"] p:not([style*="color"]),
        .stApp div[style*="background-color:rgb(28, 38, 53)"] span:not([style*="color"]),
        .stApp div[style*="background-color:rgb(28, 38, 53)"] li:not([style*="color"]),
        .stApp div[style*="background-color: rgb(28, 38, 53)"] p:not([style*="color"]),
        .stApp div[style*="background-color: rgb(28, 38, 53)"] span:not([style*="color"]),
        .stApp div[style*="background-color: rgb(28, 38, 53)"] li:not([style*="color"]),
        .stApp div[style*="background:#0B0F17"] p:not([style*="color"]),
        .stApp div[style*="background:#0B0F17"] span:not([style*="color"]),
        .stApp div[style*="background:#0B0F17"] li:not([style*="color"]),
        .stApp div[style*="background: #0B0F17"] p:not([style*="color"]),
        .stApp div[style*="background: #0B0F17"] span:not([style*="color"]),
        .stApp div[style*="background: #0B0F17"] li:not([style*="color"]),
        .stApp div[style*="background-color:#0B0F17"] p:not([style*="color"]),
        .stApp div[style*="background-color:#0B0F17"] span:not([style*="color"]),
        .stApp div[style*="background-color:#0B0F17"] li:not([style*="color"]),
        .stApp div[style*="background-color: #0B0F17"] p:not([style*="color"]),
        .stApp div[style*="background-color: #0B0F17"] span:not([style*="color"]),
        .stApp div[style*="background-color: #0B0F17"] li:not([style*="color"]),
        .stApp div[style*="background:#0b0f17"] p:not([style*="color"]),
        .stApp div[style*="background:#0b0f17"] span:not([style*="color"]),
        .stApp div[style*="background:#0b0f17"] li:not([style*="color"]),
        .stApp div[style*="background: #0b0f17"] p:not([style*="color"]),
        .stApp div[style*="background: #0b0f17"] span:not([style*="color"]),
        .stApp div[style*="background: #0b0f17"] li:not([style*="color"]),
        .stApp div[style*="background-color:#0b0f17"] p:not([style*="color"]),
        .stApp div[style*="background-color:#0b0f17"] span:not([style*="color"]),
        .stApp div[style*="background-color:#0b0f17"] li:not([style*="color"]),
        .stApp div[style*="background-color: #0b0f17"] p:not([style*="color"]),
        .stApp div[style*="background-color: #0b0f17"] span:not([style*="color"]),
        .stApp div[style*="background-color: #0b0f17"] li:not([style*="color"]),
        .stApp div[style*="background:rgb(11, 15, 23)"] p:not([style*="color"]),
        .stApp div[style*="background:rgb(11, 15, 23)"] span:not([style*="color"]),
        .stApp div[style*="background:rgb(11, 15, 23)"] li:not([style*="color"]),
        .stApp div[style*="background: rgb(11, 15, 23)"] p:not([style*="color"]),
        .stApp div[style*="background: rgb(11, 15, 23)"] span:not([style*="color"]),
        .stApp div[style*="background: rgb(11, 15, 23)"] li:not([style*="color"]),
        .stApp div[style*="background-color:rgb(11, 15, 23)"] p:not([style*="color"]),
        .stApp div[style*="background-color:rgb(11, 15, 23)"] span:not([style*="color"]),
        .stApp div[style*="background-color:rgb(11, 15, 23)"] li:not([style*="color"]),
        .stApp div[style*="background-color: rgb(11, 15, 23)"] p:not([style*="color"]),
        .stApp div[style*="background-color: rgb(11, 15, 23)"] span:not([style*="color"]),
        .stApp div[style*="background-color: rgb(11, 15, 23)"] li:not([style*="color"]),
        .stApp div[style*="background:#222C3C"] p:not([style*="color"]),
        .stApp div[style*="background:#222C3C"] span:not([style*="color"]),
        .stApp div[style*="background:#222C3C"] li:not([style*="color"]),
        .stApp div[style*="background: #222C3C"] p:not([style*="color"]),
        .stApp div[style*="background: #222C3C"] span:not([style*="color"]),
        .stApp div[style*="background: #222C3C"] li:not([style*="color"]),
        .stApp div[style*="background-color:#222C3C"] p:not([style*="color"]),
        .stApp div[style*="background-color:#222C3C"] span:not([style*="color"]),
        .stApp div[style*="background-color:#222C3C"] li:not([style*="color"]),
        .stApp div[style*="background-color: #222C3C"] p:not([style*="color"]),
        .stApp div[style*="background-color: #222C3C"] span:not([style*="color"]),
        .stApp div[style*="background-color: #222C3C"] li:not([style*="color"]),
        .stApp div[style*="background:#222c3c"] p:not([style*="color"]),
        .stApp div[style*="background:#222c3c"] span:not([style*="color"]),
        .stApp div[style*="background:#222c3c"] li:not([style*="color"]),
        .stApp div[style*="background: #222c3c"] p:not([style*="color"]),
        .stApp div[style*="background: #222c3c"] span:not([style*="color"]),
        .stApp div[style*="background: #222c3c"] li:not([style*="color"]),
        .stApp div[style*="background-color:#222c3c"] p:not([style*="color"]),
        .stApp div[style*="background-color:#222c3c"] span:not([style*="color"]),
        .stApp div[style*="background-color:#222c3c"] li:not([style*="color"]),
        .stApp div[style*="background-color: #222c3c"] p:not([style*="color"]),
        .stApp div[style*="background-color: #222c3c"] span:not([style*="color"]),
        .stApp div[style*="background-color: #222c3c"] li:not([style*="color"]),
        .stApp div[style*="background:rgb(34, 44, 60)"] p:not([style*="color"]),
        .stApp div[style*="background:rgb(34, 44, 60)"] span:not([style*="color"]),
        .stApp div[style*="background:rgb(34, 44, 60)"] li:not([style*="color"]),
        .stApp div[style*="background: rgb(34, 44, 60)"] p:not([style*="color"]),
        .stApp div[style*="background: rgb(34, 44, 60)"] span:not([style*="color"]),
        .stApp div[style*="background: rgb(34, 44, 60)"] li:not([style*="color"]),
        .stApp div[style*="background-color:rgb(34, 44, 60)"] p:not([style*="color"]),
        .stApp div[style*="background-color:rgb(34, 44, 60)"] span:not([style*="color"]),
        .stApp div[style*="background-color:rgb(34, 44, 60)"] li:not([style*="color"]),
        .stApp div[style*="background-color: rgb(34, 44, 60)"] p:not([style*="color"]),
        .stApp div[style*="background-color: rgb(34, 44, 60)"] span:not([style*="color"]),
        .stApp div[style*="background-color: rgb(34, 44, 60)"] li:not([style*="color"]) {{
            color: {_uk.DARK['tx1']} !important; }}

        .stApp [data-testid="stWidgetLabel"] p{_G} {{ color: {_TOK['tx1']} !important; }}

        /* 탭: 다크용 #222C3C 배경(선택 탭·패널 모두)을 라이트로 교체 */
        .stApp .stTabs [data-baseweb="tab-list"] {{
            background-color: {_TOK['bg1']} !important; border-color: {_TOK['border']} !important; }}
        .stApp .stTabs [aria-selected="true"] {{
            background-color: {_TOK['bg2']} !important; }}

        /* 반투명 틴트 카드: 라이트 바탕에선 배경이 밝아져 다크용 인라인 색이
           안 보인다 → 어두운 솔리드로 고정 (내부 텍스트는 가드로 원색 유지) */
        .stApp div[style*="background: rgba(48, 209, 88"],
        .stApp div[style*="background-color: rgba(48, 209, 88"],
        .stApp div[style*="background: rgba(255, 159, 10"],
        .stApp div[style*="background-color: rgba(255, 159, 10"],
        .stApp div[style*="background: rgba(255, 69, 58"],
        .stApp div[style*="background-color: rgba(255, 69, 58"],
        .stApp div[style*="background: rgba(100, 210, 255"],
        .stApp div[style*="background-color: rgba(100, 210, 255"],
        .stApp div[style*="background: rgba(191, 90, 242"],
        .stApp div[style*="background-color: rgba(191, 90, 242"],
        .stApp div[style*="background: rgba(142, 142, 147"],
        .stApp div[style*="background-color: rgba(142, 142, 147"] {{
            background: #161D2A !important;
        }}
    </style>
    """, unsafe_allow_html=True)

# ── 브라우저 클립보드 붙여넣기 컴포넌트 ──────────────────────────────────────
# 사용자 브라우저의 paste 이벤트로 이미지를 받는다. 서버 클립보드를 읽는 방식과 달리
# 온라인(클라우드) 접속에서도 그대로 동작하고, 이미지는 이 앱 서버까지만 전달된다.
# 정적 HTML 하나라 별도 빌드가 필요 없다.
_PASTE_COMPONENT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "components", "paste_image")
_paste_component = None
if os.path.isdir(_PASTE_COMPONENT_DIR):
    try:
        import streamlit.components.v1 as _st_components
        _paste_component = _st_components.declare_component(
            "paste_image", path=_PASTE_COMPONENT_DIR)
    except Exception:
        _paste_component = None


def paste_image_box(key="paste_box"):
    """붙여넣은 이미지 정보를 담은 dict 또는 None. 컴포넌트를 못 쓰면 None."""
    if _paste_component is None:
        st.caption("ℹ️ 이 환경에서는 붙여넣기 상자를 띄우지 못했습니다 — 아래 파일 올리기를 이용하세요.")
        return None
    try:
        return _paste_component(key=key, default=None)
    except Exception as exc:
        st.caption(f"ℹ️ 붙여넣기 상자를 띄우지 못했습니다 ({type(exc).__name__}) — 아래 파일 올리기를 이용하세요.")
        return None


# ── 미산출(None) 값 표기 헬퍼 ────────────────────────────────────────────────
# 엔진은 표본·신뢰도가 부족하면 숫자 대신 None을 돌려준다.
# 화면은 0으로 채우지 않고 '미산출'로 적는다. (모든 화면보다 먼저 정의되어야 한다)
def fmt_num(v, spec=",.0f", suffix="", na="미산출"):
    try:
        return f"{v:{spec}}{suffix}" if v is not None else na
    except (TypeError, ValueError):
        return na


def fmt_pct(v, digits=1, signed=True, na="미산출"):
    if v is None:
        return na
    try:
        return f"{v:+.{digits}f}%" if signed else f"{v:.{digits}f}%"
    except (TypeError, ValueError):
        return na


# [명세 §17] 모든 화면은 run_full_pipeline 이 만든 하나의 스냅샷을 공유한다.
# 상단 TOP3와 상세화면이 따로 계산하지 않도록, 스캔 결과에 실린 스냅샷을 그대로 재사용한다.
def _expected_cache_key(symbol, t_ref_str, rho_threshold):
    Q = QuantIndicatorsEngine
    return (symbol, t_ref_str, round(rho_threshold, 4),
            Q.CALC_VERSION, Q.MODEL_VERSION, Q.RULEBOOK_VERSION)


def get_shared_snapshot(symbol, t_ref_str, rho_threshold):
    """
    [명세 §17] 화면 전체가 공유할 스냅샷을 돌려준다.

    캐시 적중 조건: 종목 + 분석기준일 + rho + 계산식/모델/규칙집 버전이 모두 일치하고,
    생성 후 TTL(15분)이 지나지 않았을 것. 하나라도 어긋나면 재계산한다.
    """
    engine = BitemporalEngine()
    q = QuantIndicatorsEngine()
    want = _expected_cache_key(symbol, t_ref_str, rho_threshold)

    # 1) 스캐너 결과에 실린 스냅샷 재사용 (상단 표와 상세화면의 동일성 보장)
    for r in st.session_state.get('scan_results', []) or []:
        snap = r.get('snapshot')
        if snap is None:
            continue
        try:
            if snap.cache_key() == want and not snap.is_stale:
                return snap, "scan"
        except Exception:
            continue

    # 2) 상세화면 전용 캐시
    cached = st.session_state.get('detail_snapshot')
    if cached is not None:
        try:
            if cached.cache_key() == want and not cached.is_stale:
                return cached, "cache"
        except Exception:
            pass

    # 3) 재계산
    snap = q.run_full_pipeline(symbol, t_ref_str, b_engine=engine, rho_cutoff=rho_threshold)
    st.session_state['detail_snapshot'] = snap
    return snap, "fresh"


def build_report_context(snap):
    engine = BitemporalEngine()
    rep_gen = QuantReportGenerator()
    pit_snapshot = engine.get_point_in_time_snapshot(snap['t_ref'], symbol=snap['symbol'])
    report_text = rep_gen.generate_full_report(
        snap['symbol'], snap['tech_df'], snap['fund_df'],
        snap['sim_res'], snap['val_eval'], snapshot=pit_snapshot,
        four_scores=snap['four_scores'])
    audit = rep_gen.audit_compliance(pit_snapshot, snap['tech_df'], snap['sim_res'])
    guard = getattr(rep_gen, 'last_guardrail_result', {})
    return report_text, pit_snapshot, pit_snapshot['latest_fundamental'], audit, guard

engine_init = BitemporalEngine()
q_engine = QuantIndicatorsEngine()
# 경로 확률 임계값은 엔진 상수를 그대로 읽는다 (화면 라벨과 계산 기준을 분리하지 않는다)
TP_SL = (QuantIndicatorsEngine.TP_THRESHOLD_PCT, QuantIndicatorsEngine.SL_THRESHOLD_PCT)
rep_gen_init = QuantReportGenerator()

# 2. 사이드바 - 종목 검색 & 파라미터
# 제목 자체를 홈 버튼으로 쓴다 (Streamlit 의 title 은 클릭할 수 없다).
# ⚠️ 사이드바 버튼 CSS 는 **이 한 곳에서만** 정의한다.
#    두 곳에서 주입하면 나중에 삽입된 규칙이 이겨서, 제목이 소제목보다 작아진다.
#    제목 규칙은 일반 버튼 규칙보다 선택자를 더 구체적으로 써서 항상 이기게 한다.
st.sidebar.markdown("""
<style>
  /* ① 일반 사이드바 버튼 — 보유종목 등. 어두운 배경에 묻히지 않게 대비를 올린다 */
  section[data-testid="stSidebar"] div[data-testid="stButton"] > button {
      color: #F3F6FA !important;
      font-weight: 500 !important;
      font-size: 13px !important;
      background: #1C2635 !important;
      }
  section[data-testid="stSidebar"] div[data-testid="stButton"] > button:hover {
      background: #222C3C !important;
      border-color: #4C8DFF !important;
      color: #ffffff !important;
  }

  /* ② 제목(홈 버튼) — 사이드바에서 가장 큰 글자이고, 눌리는 버튼임이 보여야 한다.
        st-key- 클래스는 Streamlit 버전에 따라 위치가 달라질 수 있으므로,
        '사이드바의 첫 번째 버튼' 이라는 구조 선택자를 함께 걸어 항상 잡히게 한다. */
  section[data-testid="stSidebar"] div[data-testid="stButton"].st-key-btn_home > button,
  section[data-testid="stSidebar"] .st-key-btn_home div[data-testid="stButton"] > button,
  section[data-testid="stSidebar"] .st-key-btn_home > button,
  section[data-testid="stSidebar"] .st-key-btn_home button,
  section[data-testid="stSidebar"] div[data-testid="stSidebarUserContent"]
      > div > div > div[data-testid="element-container"]:first-of-type
      div[data-testid="stButton"] > button {
      /* 로고가 제목 역할을 하므로 이 버튼은 조용한 보조로 둔다.
         28px 짜리 꽉 찬 버튼이 34px 로고 옆에 붙으면 비율이 무너진다. */
      background: transparent !important;
      border-radius: 8px !important;
      box-shadow: none !important;
      color: #7C8AA0 !important;
      font-size: 13px !important;
      line-height: 1.4 !important;
      font-weight: 500 !important;
      letter-spacing: -0.01em !important;
      padding: 4px 0 !important;
      text-align: left !important;
      justify-content: flex-start !important;
      white-space: nowrap !important;
      width: auto !important;
      min-height: 0 !important;
      transition: transform .05s ease, border-color .15s ease !important;
  }
  section[data-testid="stSidebar"] div[data-testid="stButton"].st-key-btn_home > button:hover,
  section[data-testid="stSidebar"] .st-key-btn_home div[data-testid="stButton"] > button:hover,
  section[data-testid="stSidebar"] .st-key-btn_home > button:hover,
  section[data-testid="stSidebar"] .st-key-btn_home button:hover {
      background: #161D2A !important;
      border-color: #4C8DFF !important;
      color: #4C8DFF !important;
  }
  /* 눌리는 느낌 — 클릭 순간 살짝 내려앉는다 */
  section[data-testid="stSidebar"] div[data-testid="stButton"].st-key-btn_home > button:active,
  section[data-testid="stSidebar"] .st-key-btn_home button:active {
      transform: translateY(2px) !important;
      box-shadow: 0 0 0 #0B0F17 !important;
  }
</style>
""", unsafe_allow_html=True)

# ── 좌측 내비 (참조 화면 구조) — 로고 · 1차 탭 · 서브 항목 ────────────────
# 내비는 앵커 링크다. 눌리면 그 구역으로 이동한다. 화면이 한 장이라
# 라우팅 대신 앵커를 쓰지만, 보이는 구조와 동작은 참조와 같다.
_NAV_MAIN = [
    {'key': 'top', 'label': '홈', 'icon': 'home', 'href': '#nav-top'},
    {'key': 'verdict', 'label': '종목 분석', 'icon': 'compass',
     'href': '#nav-verdict'},
    {'key': 'perf', 'label': '모델 성적', 'icon': 'chart', 'href': '#nav-perf'},
    {'key': 'updates', 'label': '업데이트', 'icon': 'bell',
     'href': '#nav-updates'},
    {'key': 'support', 'label': '고객센터', 'icon': 'life',
     'href': '#nav-support'},
]
_NAV_SUB = [
    {'title': '1. 오늘의 판단', 'items': [
        {'key': 'verdict', 'label': '한 줄 결론', 'icon': 'doc',
         'href': '#nav-verdict'},
        {'key': 'gaeum', 'label': '가늠 AI', 'icon': 'compass',
         'href': '#nav-gaeum'},
        {'key': 'premarket', 'label': '오늘의 추천', 'icon': 'chart',
         'href': '#nav-premarket'},
    ]},
    {'title': '2. 근거 확인', 'items': [
        {'key': 'context', 'label': '시장·뉴스', 'icon': 'news',
         'href': '#nav-context'},
        {'key': 'basis', 'label': '판정 근거', 'icon': 'doc',
         'href': '#nav-basis'},
    ]},
    {'title': '3. 내 자산', 'items': [
        {'key': 'holdings', 'label': '내 보유종목', 'icon': 'wallet',
         'href': '#nav-holdings'},
    ]},
    {'title': '4. 검증과 이력', 'items': [
        {'key': 'perf', 'label': '모델 성적', 'icon': 'chart',
         'href': '#nav-perf'},
        {'key': 'updates', 'label': '업데이트 내역', 'icon': 'bell',
         'href': '#nav-updates'},
    ]},
]
st.sidebar.markdown(
    f"<div style='padding:4px 0 14px 0;'>{_uk.logo(_theme, size=30)}</div>",
    unsafe_allow_html=True)

# 종목 검색은 이 앱의 첫 동작이다 — 메뉴보다 위에 있어야 한다.
# 그런데 검색 코드는 종목 확정·시세 조회까지 한 덩어리라 위로 못 옮긴다
# (if/elif/else 체인 + 아래 화면 전체가 그 결과에 기댄다).
# 그래서 **자리만 먼저 잡아 두고** 코드는 제자리에서 이 자리에 그린다 —
# 스트림릿 컨테이너는 호출 시점이 아니라 잡아 둔 위치에 렌더된다.
_SB_PICK = st.sidebar.container()

st.sidebar.markdown(
    # 검색 블록과 메뉴는 성격이 다르다 — 붙여 놓으면 드롭다운의 연장으로
    # 보인다. 선을 긋지 않고 여백으로만 나눈다 (§78).
    "<div style='margin-top:18px;'>"
    + _uk.nav_list(_NAV_MAIN, active='top', theme=_theme)
    + _uk.nav_groups(_NAV_SUB, theme=_theme)
    + "</div>",
    unsafe_allow_html=True)
st.sidebar.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
if st.sidebar.button("처음으로", width='content', key="btn_home",
                     help="첫 화면으로 돌아갑니다 (검색어·스캔 결과·열린 화면 초기화). "
                          "보유종목은 지워지지 않습니다."):
    # 보유종목(positions)과 저장본은 건드리지 않는다 — 사용자의 자료다.
    for _k in ('search_text_input', 'pending_search', 'selected_ticker',
               'show_portfolio', 'show_screener', 'pending_scan',
               'scan_results', 'scan_key', 'scan_universe_total',
               'attention_result', 'attention_unmapped',
               'paste_preview', 'last_ocr_text', 'clip_image',
               'name_candidates', 'horizon_pick', 'freeform_paste'):
        st.session_state.pop(_k, None)
    st.rerun()

st.sidebar.caption(f"업데이트 {APP_UPDATED} · 제목을 누르면 첫 화면으로 돌아갑니다")

# 라이트/다크 테마 토글
_theme_is_light = st.sidebar.toggle("라이트 모드", value=(_theme == 'light'),
                                    key="tgl_theme")
if _theme_is_light != (_theme == 'light'):
    st.session_state['ui_theme'] = 'light' if _theme_is_light else 'dark'
    st.rerun()

default_stock_no1 = engine_init.fetch_realtime_market_cap_no1_stock()

# ── 좌측 설정 아코디언 (1~4단계) ─────────────────────────────────────────
# 평소엔 제목만 보이고, 누른 단계만 펼쳐진다. 다른 단계는 자동으로 접힌다.
# ⚠️ 접힌 단계의 위젯은 렌더되지 않아 Streamlit 이 상태를 비운다.
#    그래서 값을 _KEEP 에 복사해 두고, 접혔을 때는 그 값을 쓴다 —
#    "접었다 펼쳐도 설정이 유지된다"를 보장하는 유일한 방법이다.
_KEEP = st.session_state.setdefault('_sb_keep', {})


def _keep(name, value):
    _KEEP[name] = value
    return value


def _kept(name, default):
    return _KEEP.get(name, default)


_sb_busy = st.session_state.get('_sb_busy', '')
_SB_STEPS = [
    {'key': 'pick', 'no': '1', 'title': '분석할 종목',
     'done': bool(st.session_state.get('search_text_input')
                  or st.session_state.get('selected_ticker')),
     'icon': 'search',
     'hint': '종목명 일부나 티커로 찾습니다'},
    {'key': 'hold', 'no': '2', 'title': '내 보유종목',
     'done': bool(st.session_state.get('positions')),
     'icon': 'account_balance_wallet',
     'hint': '보유 중이면 판단이 달라집니다'},
    {'key': 'find', 'no': '3', 'title': '종목 찾기',
     'done': bool(st.session_state.get('scan_results')),
     'icon': 'query_stats',
     'hint': '조건에 맞는 후보를 발굴합니다'},
    {'key': 'crit', 'no': '4', 'title': '분석 기준',
     'done': None,
     'icon': 'tune',
     'hint': '기준일과 유사도 임계값'},
]
_sb_open = st.session_state.setdefault('sb_step', 'pick')
_uk.acc_css(_SB_STEPS, _sb_open, _sb_busy, _theme)


# ── 종목 검색·선택 (아코디언 밖 · 항상 보인다) ──────────────────────────
# 검색은 이 앱의 입구다. 설정 단계 안에 두면 접힌 순간 사라져서 사용자가
# 아무것도 시작할 수 없다. 접힘 상태와 무관하게 항상 그린다.
# (if/elif/else 체인이라 검색만 떼어낼 수 없다 — 종목 확정까지 함께 뺀다)

_uk.sidebar_section("종목", f"오늘 시총 1위는 {default_stock_no1}", _theme,
                    top=6, at=_SB_PICK)

if 'search_text_input' not in st.session_state:
    st.session_state['search_text_input'] = ''

if 'pending_search' in st.session_state and st.session_state['pending_search']:
    st.session_state['search_text_input'] = st.session_state['pending_search']
    st.session_state['pending_search'] = ""

search_text_input = _SB_PICK.text_input(
    '종목명 일부 또는 티커 입력',
    key='search_text_input',
    placeholder='예: 하이닉스, 타이어, 건설, 페이, 포스코, 073240...',
    help='단어 일부(예: 하이닉스, 타이어, 페이)를 입력하시면 연동 후보 리스트가 하단에 즉시 생성되어 선택할 수 있습니다.'
)

matched_stocks = []
if search_text_input.strip():
    # 네이버 조회가 섞여 있어 1~2초 걸린다. 아무 표시도 없으면 멈춘 것처럼
    # 보이므로 검색 중임을 사이드바에 그대로 알린다.
    _sp = _SB_PICK.empty()
    _sp.markdown(
        f"<div style='display:flex; align-items:center; gap:8px; "
        f"padding:8px 2px; font-size:12px; color:{_TOK['tx3']};'>"
        f"<span style='width:12px; height:12px; border-radius:50%; "
        f"display:inline-block; animation:gspin .7s linear infinite; "
        f"background:conic-gradient({_TOK['brand']} 0 90deg, "
        f"{_TOK['border']} 90deg 360deg); "
        f"mask:radial-gradient(circle, transparent 3px, #000 3.5px); "
        f"-webkit-mask:radial-gradient(circle, transparent 3px, #000 3.5px);'>"
        f"</span>"
        f"'{_uk._esc(search_text_input.strip())}' 찾는 중…</div>"
        f"<style>@keyframes gspin{{to{{transform:rotate(360deg)}}}}</style>",
        unsafe_allow_html=True)
    kw = search_text_input.strip().lower()
    for name, ticker in STOCK_NAME_MAP.items():
        if '(' in name: continue
        if kw in name.lower() or kw in ticker.lower():
            code_num = ticker.split('.')[0]
            label = f"{name} ({code_num})"
            if label not in matched_stocks:
                matched_stocks.append(label)
            
    naver_matches = engine_init.search_naver_stocks_realtime(search_text_input.strip())
    for nm in naver_matches:
        if nm not in matched_stocks:
            matched_stocks.append(nm)
    _sp.empty()          # 결과가 나오면 조용히 사라진다

if matched_stocks:
    _SB_PICK.markdown(f"'{search_text_input}' 일치 {len(matched_stocks)}개 — 골라 주세요")
    selected_from_matches = _SB_PICK.selectbox("검색 종목 선택", matched_stocks)
    final_query = selected_from_matches
elif search_text_input.strip():
    final_query = search_text_input.strip()
else:
    _SB_PICK.caption("시가총액 상위에서 고르기")
    # 종목 목록을 코드에 박아두지 않는다 — 시총 상위에서 매번 가져온다
    if 'quick_top' not in st.session_state:
        st.session_state['quick_top'] = engine_init.fetch_market_cap_top(10)
    QUICK_PLACEHOLDER = "--- 시총 상위 종목 선택 ---"     # 안내문구 (검색어로 넘기지 않는다)
    quick_select_options = [QUICK_PLACEHOLDER] + st.session_state['quick_top']
    selected_quick_item = _SB_PICK.selectbox("시총 상위 퀵 선택", quick_select_options)

    if st.session_state.get('selected_ticker'):
        final_query = st.session_state['selected_ticker']
    elif selected_quick_item and selected_quick_item != QUICK_PLACEHOLDER:
        final_query = selected_quick_item
    else:
        final_query = default_stock_no1


# ── 종목 확정 · 시세 조회 (아코디언 밖) ──────────────────────────────────
# 아코디언 안에는 **사용자가 조작하는 위젯만** 둔다. 그 결과로 계산되는 값은
# 여기서, 접혔든 펼쳐졌든 항상 구한다 — 본문 전체가 이 값들을 쓴다.
# 접혀 있을 때는 마지막으로 고른 검색어를 그대로 쓴다.
if not final_query:
    final_query = (_KEEP.get('final_query')
                   or st.session_state.get('selected_ticker')
                   or default_stock_no1)
_KEEP['final_query'] = final_query

target_ticker, resolved_name = engine_init.resolve_symbol(final_query)

# 종목 해석 실패는 앱 전체를 중단시키지 않는다 — 명확히 알리고 멈춘다
if not target_ticker:
    st.error(f"**종목을 해석하지 못했습니다**: `{final_query}`\n\n"
             f"종목명 또는 6자리 종목코드를 입력해 주세요. "
             f"네이버증권 검색이 일시적으로 실패했을 수도 있습니다.")
    st.stop()
# 🚨 [무결성 보장] 네이버 증권 실시간 웹 파서 강제 동적 수신
engine_init.fetch_and_update_naver_realtime(target_ticker)

asset_meta = engine_init.get_asset_currency_and_unit(target_ticker)
unit_currency = asset_meta["currency"]
unit_str = asset_meta["unit_str"]

realtime_price, check_status, matrix_data = engine_init.get_realtime_stock_price_triple_check(target_ticker)

# 상단 툴바 오른쪽 끝에 지금 보는 종목 — 스크롤 중에도 잊지 않게 (sticky)
_render_toolbar(f"보는 중 <b>{_uk._esc(resolved_name)}</b> "
                f"{_uk._esc(target_ticker)}")

# 1단계 — 지금 무엇을 보고 있는지. 검색은 위에 있고 여기엔 결과만 담는다.
if _uk.acc_row(_SB_STEPS[0], _sb_open, _sb_busy):
    _uk.sidebar_fact("보고 있는 종목", f"{resolved_name} · {target_ticker}",
                     _theme, tone="brand")
    _uk.sidebar_fact("현재가",
                     (f"{realtime_price:,.0f} {unit_str}"
                      if unit_currency == "KRW"
                      else f"${realtime_price:,.2f}"), _theme)
    with st.sidebar.expander("자산·통화 확인"):
        st.caption(f"자산 구별 {asset_meta['type']} · 통화 {unit_currency} · "
                   f"가격 단위 {unit_str}")


# ═══════════════════════════════════════════════════════════════════════════
# 💼 내 보유종목 — 사이드바 상시 표시
# 현재가만 가볍게 조회한다 (전체 파이프라인은 본문 화면에서만 실행)
# ═══════════════════════════════════════════════════════════════════════════
# 원격 접속(클라우드·터널)에서는 로컬 파일 저장소를 쓰지 않는다.
# 앱 인스턴스가 하나라 `.portfolio/positions.json` 이 방문자 전원의 공용 파일이 되어
# 한 사람이 저장하면 다른 사람 화면에 그대로 나타난다. 세션에만 두고 CSV 로 내보낸다.
ALLOW_LOCAL_STORE = not is_remote_exposed()

if 'positions' not in st.session_state:
    if ALLOW_LOCAL_STORE:
        _loaded, _saved_at = portfolio.load_positions()
        st.session_state['positions'] = _loaded
        st.session_state['positions_saved_at'] = _saved_at
    else:
        st.session_state['positions'] = []          # 방문자별로 비어서 시작
        st.session_state['positions_saved_at'] = None

if 'watchlist' not in st.session_state:
    if ALLOW_LOCAL_STORE:
        _wl, _ = portfolio.load_watchlist()
        st.session_state['watchlist'] = _wl
    else:
        st.session_state['watchlist'] = []

QUOTE_TTL_SEC = 60


def light_quote(ticker):
    """사이드바용 경량 현재가 조회 (60초 캐시). 실패 시 None."""
    cache = st.session_state.setdefault('quote_cache', {})
    now = datetime.datetime.now().timestamp()
    hit = cache.get(ticker)
    if hit and (now - hit[1]) < QUOTE_TTL_SEC:
        return hit[0]
    try:
        px, _st, _mx = engine_init.get_realtime_stock_price_triple_check(ticker)
        px = float(px) if px else None
    except Exception:
        px = None
    cache[ticker] = (px, now)
    return px


_positions = st.session_state.get('positions') or []

if _uk.acc_row(_SB_STEPS[1], _sb_open, _sb_busy):

    _uk.sidebar_section(f"내 보유종목 · {len(_positions)}", theme=_theme)

    if not _positions:
        st.sidebar.caption("등록된 보유종목이 없습니다. 증권사 앱 보유종목 화면을 "
                           "`Win`+`Shift`+`S` 로 캡처해 두고 아래 버튼을 누르면, "
                           "본문에서 클립보드 이미지를 그대로 읽어 등록할 수 있습니다.")
        if st.sidebar.button("스크린샷으로 등록하기", width='stretch',
                             key="btn_open_pf_from_empty"):
            st.session_state['show_portfolio'] = True
            st.rerun()
    else:
        _merged = portfolio.merge_duplicate_positions(_positions)
        _tot_cost = _tot_val = 0.0
        _rows = []
        for _m in _merged:
            _px = light_quote(_m['ticker'])
            _cost = _m['quantity'] * _m['average_buy_price']
            _val = _m['quantity'] * _px if _px else None
            _ret = ((_px / _m['average_buy_price'] - 1) * 100) if _px else None
            _tot_cost += _cost
            if _val:
                _tot_val += _val
            _rows.append((_m, _px, _ret))

        # 수익률 내림차순
        _rows.sort(key=lambda r: (r[2] if r[2] is not None else -1e9), reverse=True)

        _tot_ret = ((_tot_val / _tot_cost - 1) * 100) if (_tot_cost and _tot_val) else None
        _pnl = _tot_val - _tot_cost if _tot_val else None
        _col = "#35C98B" if (_pnl or 0) >= 0 else "#ff453a"
        st.sidebar.markdown(
            f"<div style='background:#161D2A;border-radius:10px;"
            f"padding:8px 12px;margin-bottom:8px;'>"
            f"<div style='font-size:12px;color:#9DAABC;'>총 평가손익</div>"
            f"<div style='font-size:20px;font-weight:700;color:{_col};'>"
            f"{fmt_num(_pnl, '+,.0f', '원')}</div>"
            f"<div style='font-size:13px;color:#9DAABC;'>수익률 {fmt_pct(_tot_ret)} · "
            f"평가 {fmt_num(_tot_val, ',.0f', '원')}</div></div>",
            unsafe_allow_html=True)

        # 사이드바 버튼 스타일은 여기서 주입하지 않는다.
        # 예전에는 이 자리에서 모든 사이드바 버튼에 font-size:15px !important 를 걸었는데,
        # 그 규칙이 제목(홈 버튼) 규칙보다 구체적이고 나중에 삽입돼서 제목 글자를
        # 본문 소제목보다 작게 만들어버렸다. 스타일은 파일 상단 한 곳에서만 정의한다.

        for _m, _px, _ret in _rows:
            _c1, _c2 = st.sidebar.columns([1.35, 1])
            _is_cur = (_m['ticker'] == target_ticker)
            with _c1:
                if st.button(("▶ " if _is_cur else "") + _m['stock_name'],
                             key=f"pos_{_m['ticker']}", width='stretch',
                             type="primary" if _is_cur else "secondary",
                             help=f"{_m['quantity']:,.0f}주 · 평단 {_m['average_buy_price']:,.0f}원"):
                    st.session_state['pending_search'] = f"{_m['stock_name']} ({_m['ticker'].split('.')[0]})"
                    st.rerun()
            with _c2:
                _rc = "#35C98B" if (_ret or 0) >= 0 else "#ff453a"
                st.markdown(
                    f"<div style='text-align:right;padding-top:8px;'>"
                    f"<span style='color:{_rc};font-weight:700;font-size:15px;'>{fmt_pct(_ret)}</span><br>"
                    f"<span style='color:#9DAABC;font-size:12px;'>{fmt_num(_px, ',.0f', '원', na='조회실패')}</span>"
                    f"</div>", unsafe_allow_html=True)

        st.sidebar.caption("※ 평단가는 보유 판단에만 사용하며 예측·적정가·점수에는 반영되지 않습니다.")

    # 📌 선택 종목 1건만 빠르게 넣어보는 입력 (포트폴리오 등록 없이 임시 확인용)
    _uk.sidebar_section("이 종목만 임시로 계산", theme=_theme)

    _reg = next((p for p in (st.session_state.get('positions') or [])
                 if p.ticker == target_ticker), None)
    if _reg is not None:
        st.sidebar.success(
            f"✅ **{resolved_name}** — 보유종목에서 자동으로 채웠습니다 "
            f"({_reg.quantity:,.0f}주 · 평단 {_reg.average_buy_price:,.0f}원). "
            f"위 목록에서 다른 종목을 누르면 그 종목으로 바뀝니다.")
    else:
        st.sidebar.caption(f"지금 보고 있는 **{resolved_name}** 한 종목만 임시로 확인합니다. "
                           f"여러 종목을 계속 관리하려면 위 '내 보유종목'에 등록하세요.")
    user_entry_price = st.sidebar.number_input(
        "평균 매수가 (원)", min_value=0,
        value=int(_reg.average_buy_price) if _reg else 0, step=1000,
        help="보유 중인 주당 평균 매수가 (0원 = 미보유)")
    user_quantity = st.sidebar.number_input(
        "보유 수량 (주)", min_value=0,
        value=int(_reg.quantity) if _reg else 0, step=10,
        help="보유 중인 총 주식 수량 (0주 = 미보유)")
    if user_entry_price > 0 and user_quantity > 0 and _reg is None:
        if st.sidebar.button("보유종목에 등록", width='stretch'):
            st.session_state['positions'] = (st.session_state.get('positions') or []) + [
                portfolio.PortfolioPosition(
                    ticker=target_ticker, stock_name=resolved_name,
                    market="KOSDAQ" if target_ticker.endswith(".KQ") else "KOSPI",
                    quantity=float(user_quantity), average_buy_price=float(user_entry_price),
                    source_type="manual_entry")]
            st.rerun()

    # (사이드바 실측 성적 패널은 사용자 요청으로 제거 — 전문 수치는 혼란만 준다.
    #  '틀릴 가능성 약 N% (과거 사례 n건)' 형태로 본문 쉬운 결론에만 녹여 표시하고,
    #  상세 수치는 .portfolio/calibration.json 과 docs/MODEL_VERSIONS.md 가 정본이다.
    #  판정 기록(record_prediction)·자기보정 상한은 백엔드에서 계속 동작한다.)


    # --- 분석 파라미터 (스캐너와 상세화면이 동일 값을 써야 하므로 먼저 정의한다) ---
    # ═══════════════════════════════════════════════════════════════════════════
    # 🔥 AI 퀀트 시장 트렌드 탐색기
    # 위젯만 여기서 그리고, 실제 스캔은 분석 파라미터(t_ref·rho)가 확정된 뒤에 돌린다.
    # ═══════════════════════════════════════════════════════════════════════════

if _uk.acc_row(_SB_STEPS[2], _sb_open, _sb_busy):

    _uk.sidebar_section("종목 찾기", theme=_theme)
    # '코스피·코스닥 전체' 라고 쓰고 있었지만 실제 출발점은 네이버 순위
    # 페이지 2종(거래대금 상위·상승률 상위)이다. 전 종목 목록이 아니다.
    st.sidebar.caption("코스피·코스닥의 **거래대금·상승률 순위 상위**에서 관심종목을 "
                       "먼저 추리고, 그중 **퀀트 최종 행동조건**을 통과한 종목만 "
                       "추천합니다. 전 종목을 정밀분석하지는 않습니다 — "
                       "거래가 한산한 종목은 순위에 오르지 않아 후보에서 빠집니다. "
                       "관심도와 매수 판단은 별개입니다.")

    if 'show_screener' not in st.session_state:
        st.session_state['show_screener'] = False

    _strat_labels = [lbl for _k, lbl in market_attention.STRATEGIES]
    _strat_by_label = {lbl: k for k, lbl in market_attention.STRATEGIES}
    _sel_strat_label = st.sidebar.selectbox(
        "후보 발굴 방식", _strat_labels, index=0,
        help="시총 상위는 대형주가 반복되므로 기본값은 '종합 이슈'입니다.")
    attention_strategy = _strat_by_label[_sel_strat_label]
    if attention_strategy in market_attention.STRATEGY_UNAVAILABLE:
        st.sidebar.warning(market_attention.STRATEGY_UNAVAILABLE[attention_strategy])

    scan_depth = st.sidebar.selectbox(
        f"정밀분석 후보 수 ({_sel_strat_label} 순)", [5, 10, 15, 20, 30], index=0,
        help="관심점수 상위 N개에만 종목별 정밀 파이프라인을 돌립니다. "
             "종목당 일봉·시세 조회가 필요해 N이 클수록 오래 걸립니다. "
             "기본 5개는 빠르게 훑어보기용이며, 넓게 보려면 15~30개로 올리세요.")

    with st.sidebar.expander("관심 데이터 연동 현황"):
        st.caption("수집하지 못한 항목은 값을 만들어내지 않고 가중치를 0으로 둔 뒤, "
                   "나머지 항목에 재정규화합니다.")
        for _d in market_attention.data_status():
            _mark = {'full': '🟢 연동', 'partial': '🟡 부분', 'none': '🔴 미연동'}[_d['availability']]
            st.markdown(
                f"**{_d['label']}** {_mark}  \n"
                f"명세 {_d['spec_weight_pct']:.0f}% → 적용 **{_d['effective_weight_pct']:.1f}%**  \n"
                f"<span style='color:#9DAABC;font-size:12px;'>{_d['detail']}</span>",
                unsafe_allow_html=True)

    if st.sidebar.button("오늘의 관심종목 스캔 / 닫기", width='stretch'):
        st.session_state['show_screener'] = not st.session_state['show_screener']
        st.session_state['pending_scan'] = st.session_state['show_screener']


if _uk.acc_row(_SB_STEPS[3], _sb_open, _sb_busy):

    _uk.sidebar_section("분석 기준", theme=_theme)

    # [명세 §3] 확정 분석 기준일 — 장중·장 시작 전·휴장일이면 직전 거래일로 되돌린다
    _mkt = bitemporal_engine.get_market_status()
    _resolved_date = bitemporal_engine.resolve_analysis_date(market_status=_mkt)
    st.sidebar.caption(
        f"🕒 시장 상태: **{_mkt['state']}** 확정 분석 기준일 **{_resolved_date}**"
        + ("" if _mkt['holiday_data_available'] else "  ⚠️ 해당 연도 공휴일 미등록 (주말만 판정)")
    )
    t_ref_date = _keep('t_ref', st.sidebar.date_input(
        "백테스트 기준일 (t_ref)", value=_kept('t_ref', _resolved_date)))
    if t_ref_date != _resolved_date:
        st.sidebar.warning(f"기준일을 수동 변경했습니다 (권장: {_resolved_date}).")
    rho_cutoff = _keep('rho', st.sidebar.slider(
        "자기유사 상관계수 기준 (rho)", min_value=0.70, max_value=0.95,
        value=_kept('rho', 0.80), step=0.05))

# ── 접힌 단계의 값 확정 ──────────────────────────────────────────────────
# 아코디언이 접히면 그 안의 위젯이 렌더되지 않는다. 본문이 쓰는 이름은
# 전부 여기서 채운다 — 하나라도 빠뜨리면 그 단계를 접는 순간 화면이 죽는다.
_g = globals()
if '_mkt' not in _g:
    _mkt = bitemporal_engine.get_market_status()
if '_resolved_date' not in _g:
    _resolved_date = bitemporal_engine.resolve_analysis_date(market_status=_mkt)
for _nm, _dv in (
        ('search_text_input', ''), ('matched_stocks', []),
        ('selected_from_matches', None), ('selected_quick_item', None),
        ('user_entry_price', 0.0), ('user_quantity', 0),
        ('attention_strategy', 'composite'), ('scan_depth', 5),
        ('t_ref_date', _resolved_date), ('rho_cutoff', 0.80)):
    if _nm not in _g:
        _g[_nm] = _KEEP.get(_nm, _dv)
t_ref_str = t_ref_date.strftime("%Y-%m-%d")


# --- 💼 보유종목 상세 화면 열기 ---
show_portfolio = st.sidebar.toggle(
    "💼 보유종목 상세 화면 (가져오기·판정)", value=st.session_state.get('show_portfolio', False),
    help="CSV·Excel 가져오기, 다중기간 전망 비교, 보유자 행동판정을 본문에서 봅니다.")
st.session_state['show_portfolio'] = show_portfolio
st.sidebar.caption("증권사 CSV·Excel 가져오기 또는 직접 입력. "
                   + ("로그인 정보·쿠키를 수집하지 않으며 데이터는 이 PC에만 저장됩니다."
                      if ALLOW_LOCAL_STORE else
                      "로그인 정보·쿠키를 수집하지 않습니다. 원격 접속에서는 서버에 저장하지 않고 "
                      "이 브라우저 세션에만 유지됩니다.")
                   + (f" · 저장 {st.session_state.get('positions_saved_at')}"
                      if st.session_state.get('positions_saved_at') else " · 미저장"))

# --- 관심종목 스캔 실행 (위젯은 위에서 이미 그렸고, 여기서 t_ref·rho 를 써서 돌린다) ---
# 파라미터가 바뀌면 이전 스캔 결과는 더 이상 같은 스냅샷이 아니므로 폐기한다
_scan_key = f"{t_ref_str}|{rho_cutoff}|{scan_depth}|{attention_strategy}"
if st.session_state.get('scan_key') not in (None, _scan_key):
    st.session_state.pop('scan_results', None)
    st.session_state.pop('scan_universe_total', None)
    st.session_state.pop('attention_result', None)
st.session_state['scan_key'] = _scan_key


def run_market_scan():
    """관심종목 발굴 → 정밀 퀀트 분석. 두 단계를 명확히 분리한다."""
    _bar = st.sidebar.empty()

    def _progress(msg):
        _bar.caption(f"⏳ {msg}")

    # 1단계 — 오늘의 관심종목 발굴 (순위 페이지 → 후보에만 일봉)
    # '사용자 관심종목' 방식은 저장된 관심종목 + 보유종목을 대상으로 한다
    watch = [w['code'] for w in (st.session_state.get('watchlist') or [])]
    watch += [p.ticker.split('.')[0] for p in (st.session_state.get('positions') or [])
              if p.ticker.split('.')[0] not in watch]
    att = market_attention.find_attention_candidates(
        attention_strategy, top_n=scan_depth, progress=_progress, watchlist=watch)
    st.session_state['attention_result'] = att
    if att.get('unavailable') or not att['rows']:
        _bar.empty()
        st.session_state['scan_results'] = []
        st.session_state['scan_universe_total'] = att.get('pool_size', 0)
        return

    # 2단계 — 후보에 시장 구분을 붙여 기존 정밀 파이프라인에 넘긴다
    _progress("종목 코드·시장 구분 확인 중")
    universe = engine_init.get_screener_universe(full_market=True)
    by_code = {u['symbol'].split('.')[0]: u for u in universe}

    # ── 전 종목 경량 스캔 ────────────────────────────────────────────
    # 순위 페이지 2종에서만 출발하면 거래가 한산한 종목은 애초에 후보가
    # 되지 못한다. 유니버스에는 이미 시총·거래대금이 실려 있으므로
    # **추가 요청 없이** 전 종목을 한 번 훑을 수 있다. 여기서 거르는 건
    # 데이터가 없거나 유동성이 없어 어차피 못 사는 종목뿐이다.
    _MIN_TRADE_VALUE = 5e8          # 당일 거래대금 5억원
    _lite = {'total': len(universe), 'no_price': 0, 'no_liquidity': 0,
             'thin': 0, 'passed': 0}
    _lite_pass = set()
    for u in universe:
        if not u.get('base_price'):
            _lite['no_price'] += 1
            continue
        if not u.get('liquidity_confirmed'):
            _lite['no_liquidity'] += 1
            continue
        if (u.get('today_trade_value') or 0) < _MIN_TRADE_VALUE:
            _lite['thin'] += 1
            continue
        _lite_pass.add(u['symbol'].split('.')[0])
    _lite['passed'] = len(_lite_pass)
    st.session_state['scan_lite'] = _lite

    target, unmapped = [], []
    for r in att['rows']:
        u = by_code.get(r['code'])
        if not u:
            unmapped.append(f"{r['name']}({r['code']})")
            continue
        target.append({**u, 'attention': r['attention'],
                       'selection_reason': r.get('selection_reason'),
                       'attention_components': r['components']})
    st.session_state['attention_unmapped'] = unmapped
    st.session_state['scan_universe_total'] = att['pool_size']

    _bar.empty()
    with st.spinner(f"관심종목 {len(target)}개 정밀 분석 중... (2단계)"):
        st.session_state['scan_results'] = q_engine.run_screener_scan(
            target, t_ref_str, b_engine=engine_init, rho_cutoff=rho_cutoff)

    # 관심점수를 결과 행에 붙인다 (순위에는 동점 보조기준으로만 쓴다 — §12)
    _att_by_symbol = {t['symbol']: t for t in target}
    for row in (st.session_state.get('scan_results') or []):
        src = _att_by_symbol.get(row.get('symbol'))
        if src:
            row['attention'] = src['attention']
            row['selection_reason'] = src['selection_reason']
            row['attention_components'] = src['attention_components']


if st.session_state.pop('pending_scan', False):
    run_market_scan()

# 3. 메인 타이틀
import uuid
import datetime
run_id = f"RUN-{datetime.datetime.now().strftime('%Y%m%d')}-{target_ticker.split('.')[0][-5:]}"
# 본문 대제목 — 사이드바 홈 버튼과 같은 이름을 쓴다 (APP_TITLE 하나로 관리)
st.markdown(
    f"<div style='margin:4px 0 28px 0;'>"
    f"<p style='margin:0 0 10px 0; font-size:13px; font-weight:600; "
    f"letter-spacing:0.04em; color:{_TOK['tx3']};'>오늘의 판단</p>"
    f"<h1 style='font-size:40px; font-weight:700; letter-spacing:-0.026em; "
    f"line-height:1.15; margin:0 0 10px 0; color:{_TOK['tx1']};'>"
    f"{_uk._esc(resolved_name)}<span style='color:{_TOK['tx3']}; "
    f"font-size:20px; font-weight:500; letter-spacing:-0.01em; "
    f"margin-left:10px;'>{_uk._esc(target_ticker)}</span></h1>"
    f"<p style='margin:0; font-size:17px; color:{_TOK['tx2']}; "
    f"line-height:1.6; letter-spacing:-0.01em;'>"
    f"과거로 되돌려 실제로 맞았는지 세어 본 뒤에 판단합니다. "
    f"미래 정보는 잘라내고 검증했습니다.</p></div>",
    unsafe_allow_html=True)

# --- 종목 검색기 렌더링 ---
if st.session_state.get('show_screener', False):
    _uk.spacer(28)
    st.subheader("네이버·다음 실시간 시세 교차검증 상태 (Cross-Validation)")
    st.caption("※ 네이버증권과 다음금융은 현재 공식 API가 아닌 웹 스크래핑/폴링 방식으로 연결되어 있으므로, 2차 교차검증 출처로만 사용됩니다.")
    
    with st.spinner("네이버·다음 실시간 시세 조회 및 정합성 검증 중..."):
        cv_data = engine_init.verify_realtime_sources(target_ticker)

    def _cv_price(v):
        return f"{v:,.0f}원" if isinstance(v, (int, float)) else "수신 실패"

    cv_nv, cv_dm = cv_data['naver'], cv_data['daum']
    cv_diff_str = f"{cv_data['diff_pct']:.3f}%" if cv_data.get('diff_pct') is not None else "대조 불가"
    nv_col = "#35C98B" if cv_nv['ok'] else "#ff453a"
    dm_col = "#35C98B" if (cv_dm['ok'] and "오류" not in cv_dm['cross_val']) else "#ff453a"

    cv_col1, cv_col2 = st.columns(2)
    with cv_col1:
        st.markdown(f"""
        <div style='background:#161D2A; padding:16px; border-radius:10px; '>
            <h4 style='color:{nv_col}; margin:0 0 8px 0;'>네이버증권 (Naver Finance)</h4>
            <p style='margin:2px 0; font-size:13px; color:#9DAABC;'>- 연결 상태: <b>{cv_nv['status']}</b></p>
            <p style='margin:2px 0; font-size:13px; color:#9DAABC;'>- 조회 시각: {cv_nv['receive_time']}</p>
            <p style='margin:2px 0; font-size:13px; color:#9DAABC;'>- 데이터 유형: {cv_nv['data_type']}</p>
            <p style='margin:2px 0; font-size:13px; color:#9DAABC;'>- 현재가 반환값: {_cv_price(cv_nv['price'])}</p>
            <p style='margin:2px 0; font-size:13px; color:#9DAABC;'>- 실측 응답시간: {cv_nv['delay_ms']}ms</p>
            <p style='margin:2px 0; font-size:13px; color:#F2B84B;'>- API 인증: {cv_nv['is_official']}</p>
        </div>
        """, unsafe_allow_html=True)
    with cv_col2:
        st.markdown(f"""
        <div style='background:#161D2A; padding:16px; border-radius:10px; '>
            <h4 style='color:{dm_col}; margin:0 0 8px 0;'>다음금융 (Daum Finance)</h4>
            <p style='margin:2px 0; font-size:13px; color:#9DAABC;'>- 연결 상태: <b>{cv_dm['status']}</b></p>
            <p style='margin:2px 0; font-size:13px; color:#9DAABC;'>- 조회 시각: {cv_dm['receive_time']}</p>
            <p style='margin:2px 0; font-size:13px; color:#9DAABC;'>- 교차검증 상태: <b>{cv_dm['cross_val']}</b> (오차율: {cv_diff_str})</p>
            <p style='margin:2px 0; font-size:13px; color:#9DAABC;'>- 현재가 반환값: {_cv_price(cv_dm['price'])}</p>
            <p style='margin:2px 0; font-size:13px; color:#9DAABC;'>- 실측 응답시간: {cv_dm['delay_ms']}ms</p>
            <p style='margin:2px 0; font-size:13px; color:#F2B84B;'>- API 인증: {cv_dm['is_official']}</p>
        </div>
        """, unsafe_allow_html=True)

    if not cv_data.get('comparable'):
        st.error("**실시간 시세 교차검증 불가**: 네이버·다음 중 최소 한 곳에서 현재가를 수신하지 못했습니다. "
                 "단일 출처만으로는 시세 무결성을 보증할 수 없어 스캔을 중단합니다.")
    elif cv_data['diff_pct'] > 1.0:
        st.error(f"**실시간 시세 교차검증 실패**: 출처 간 현재가 오차가 {cv_diff_str}로 1.0%를 초과하여 스캔을 중단합니다.")
    else:
        st.markdown("<br>", unsafe_allow_html=True)
        st.subheader("오늘의 AI 퀀트 최적 종목 TOP 3")
        if 'scan_results' not in st.session_state:
            run_market_scan()
        scan_results = st.session_state['scan_results']
        if True:
            
            # [명세 §15] 필수조건을 모두 통과한 종목만 추천한다.
            # 통과 종목이 2개면 2개, 0개면 '현재 추천주 없음'.
            # 구버전은 통과 0개일 때 조건 미달 종목을 상승여력% 순으로 3칸 채워 넣었다.
            scan_failures = getattr(q_engine, 'last_scan_failures', []) or []
            # 분류가 빠진 행 하나 때문에 화면 전체가 죽지 않게 한다
            # (한 종목의 오류가 전체를 막지 않는다는 원칙을 표시 단계에도 적용)
            def _cat(row):
                return str(row.get('cat') or '')
            recommended = [r for r in scan_results if "추천주" in _cat(r)]
            wait_pullback = sum(1 for r in scan_results if "눌림 대기" in _cat(r))
            watch_list = sum(1 for r in scan_results if "관찰 후보" in _cat(r))
            excluded = sum(1 for r in scan_results if "추천 제외" in _cat(r))

            top_recs = recommended[:3]

            # 왜 통과 종목이 없는지 — 가장 흔한 차단 사유를 집계해 보여준다
            from collections import Counter
            block_counter = Counter()
            for r in scan_results:
                for reason in r.get('top3_block_reasons', []):
                    block_counter[reason.split('(')[0].strip()] += 1

            # 탐색 깊이를 있는 그대로 — 몇 개를 실제로 계산했나
            _att_res = st.session_state.get('attention_result') or {}
            _deep_done = int(_att_res.get('deep_count') or 0)
            try:
                _deep_cap = int(market_attention.DEEP_POOL_MAX)
            except Exception:
                _deep_cap = _deep_done
            _lt = st.session_state.get('scan_lite') or {}
            # 탐색률 — 유동성 있는 전체 중 몇 %를 정밀분석했나. 과장하지 않는다.
            _deep_rate = (scan_depth / _lt['passed'] * 100
                          if _lt.get('passed') else 0.0)

            st.markdown(f"""
            <div style='background:#161D2A; padding:16px; border-radius:10px; margin-bottom:16px; '>
                <h4 style='color:#F3F6FA; margin-top:0;'>시장 스캔 완료 — 어디까지 봤나</h4>
                <ul style='color:#9DAABC; font-size:15px; line-height:1.6; margin-bottom:8px;'>
                    <li>분석 기준일: {t_ref_str} · rho {rho_cutoff}</li>
                    <li>1단계 <b>전 종목 경량 스캔</b>: 코스피·코스닥 <b>{_lt.get('total', 0):,}개</b>
                        → 유동성·데이터 조건 통과 <b>{_lt.get('passed', 0):,}개</b>
                        <span style='font-size:13px;'>(시세 없음 {_lt.get('no_price', 0):,} ·
                        거래 미확인 {_lt.get('no_liquidity', 0):,} ·
                        거래대금 5억 미만 {_lt.get('thin', 0):,} 제외)</span></li>
                    <li>2단계 후보 풀: <b>{st.session_state.get('scan_universe_total', 0):,}개</b>
                        — 거래대금·상승률 순위 상위에서 수집 (ETF·우선주·스팩·리츠 제외)</li>
                    <li>3단계 관심지표 계산: 최대 <b>{_deep_cap:,}개</b>
                        → 실제 <b>{_deep_done:,}개</b></li>
                    <li>4단계 정밀분석: <b>{_sel_strat_label}</b> 상위 <b>{scan_depth}개</b>
                        → 완료 {len(scan_results)}개 · 제외 {len(scan_failures)}개</li>
                    <li>최종 행동 필수조건 통과: <b style='color:{"#35C98B" if recommended else "#F2B84B"};'>{len(recommended)}개</b></li>
                    <li><b>전체 시장 정밀분석 비율: {_deep_rate:.1f}%</b>
                        ({scan_depth}/{max(1, _lt.get('passed', 0)):,})</li>
                </ul>
                <p style='margin:0; font-size:13px; color:#F2B84B; line-height:1.65;'>
                    오늘의 추천은 코스피·코스닥 전 종목을 <b>경량 스캔</b>한 뒤,
                    거래대금·상승률 순위에서 모은 후보 중 <b>관심점수 상위 {scan_depth}개만
                    정밀분석</b>한 결과입니다.
                    <b>정밀분석하지 않은 종목에 더 좋은 후보가 있을 수 있습니다 —
                    '추천 없음'은 시장에 후보가 없다는 뜻이 아닙니다.</b>
                    2단계 후보 수집이 순위 페이지에서 출발하므로, 거래가 한산한 종목은
                    경량 스캔을 통과해도 후보에 오르지 못합니다.</p>
            </div>
            """, unsafe_allow_html=True)

            # ── 신호 2계층 (사전등록 라운드 2 채택 — docs/MODEL_VERSIONS.md) ──
            # 고신뢰 매수권(60+)은 드물고, 확장 신호(58~59)는 4,229건 실측에서
            # 검증 61.2%(n=304) → 블라인드 58.2%(n=146)인 탐색층이다.
            # 비용후 기대값은 소폭 음수 — '후보 탐색'이지 수익 보장이 아니다.
            _bz_rows = sorted(
                [r for r in scan_results if (r.get('final_score') or 0) >= 60],
                key=lambda r: r.get('final_score') or 0, reverse=True)
            _ext_rows = sorted(
                [r for r in scan_results
                 if 58 <= (r.get('final_score') or 0) < 60],
                key=lambda r: r.get('final_score') or 0, reverse=True)
            if _bz_rows:
                st.success(
                    f"**고신뢰 매수권(60점+) {len(_bz_rows)}종목** — "
                    + " · ".join(f"{r.get('name')}({r.get('final_score')}점)"
                                 for r in _bz_rows[:5])
                    + "  \n실측 신호율 2.9%의 드문 구간입니다. 아래 표에서 "
                      "종목을 눌러 조건을 확인하세요.")
            if _ext_rows:
                # 라운드 2.5: 이 중 '적정가 이하' 종목이 실측상 가장 좋다
                # (검증 64.2% → 블라인드 61.9%·비용후 +1.15%)
                _ext_below = [r for r in _ext_rows if r.get('entry_candidate')]
                _ext_msg = (
                    f"**확장 신호(58~59점) {len(_ext_rows)}종목** — "
                    + " · ".join(f"{r.get('name')}({r.get('final_score')}점)"
                                 for r in _ext_rows[:6])
                    + "  \n사전등록 실측(6,508건): 검증 62.5%(n=456) → "
                      "블라인드 55.3%(n=226), 비용 차감 후 소폭 음수 — 탐색용.")
                if _ext_below:
                    _ext_msg += (
                        f"  \n⭐ 이 중 **적정가 이하 진입 {len(_ext_below)}종목** ("
                        + " · ".join(r.get('name') for r in _ext_below[:4])
                        + ") — 이 조건은 블라인드 58.9%(n=95)·비용후 +0.55%로 "
                          "유일한 비용후 양수 계층입니다 (라운드 2.5 실측).")
                st.info(_ext_msg)
            if not _bz_rows and not _ext_rows:
                st.caption("이번 스캔에는 매수권(60점+)·확장 신호(58~59점)가 모두 "
                           "없습니다 — 없는 날은 관망이 결론입니다.")

            _att = st.session_state.get('attention_result') or {}
            if _att.get('used_confirmed_bars_only'):
                st.caption("※ 장중이므로 추세·돌파·변동성은 **직전 확정 거래일**까지만 사용했고, "
                           "거래대금 배수는 **오늘 누적**으로 계산했습니다. "
                           "장 초반에는 누적이 적어 배수가 낮게 나옵니다.")
            st.caption(f"※ 관심점수 상위 {scan_depth}개만 정밀분석했습니다. "
                       f"나머지 후보는 분석하지 않았으므로 '추천 없음'이 "
                       f"시장 전체에 후보가 없다는 뜻은 아닙니다.")
            if _att.get('unavailable'):
                st.warning(_att['unavailable'])
            if st.session_state.get('attention_unmapped'):
                st.caption("※ 종목코드를 유니버스에서 찾지 못해 정밀분석에서 빠진 후보: "
                           + ", ".join(st.session_state['attention_unmapped']))

            # ── §10 후보 카드 · §13 결과 분류 ──────────────────────────────
            if _att.get('rows'):
                st.markdown("오늘의 관심종목 후보")
                st.caption("관심점수는 **지금 시장이 주목하는가**이고, 행동점수는 "
                           "**지금 매매할 가치가 있는가**입니다. 둘은 다릅니다 — "
                           "관심점수가 높다고 추천에 넣지 않습니다.")
                # ⚠️ 스캔 행의 키는 'final_score' 다. 예전에는 없는 키
                #    'final_action_score' 를 읽어 전 종목이 '미산출' 로 표시됐다.
                _action_by_code = {str(r.get('symbol', '')).split('.')[0]:
                                   r.get('final_score')
                                   for r in scan_results}
                # 정밀분석에서 제외된 종목의 사유 (유동성·교차검증·데이터 실패)
                _fail_by_code = {str(f.get('symbol', '')).split('.')[0]:
                                 str(f.get('reason', ''))
                                 for f in scan_failures}

                # 행동점수가 나온 후보를 먼저, 제외 후보는 접힌 목록으로 분리한다
                # (점수를 계산할 수 없는 카드가 본 목록에 섞이면 판단에 쓸 수 없다)
                _scored_rows = [r for r in _att['rows']
                                if _action_by_code.get(r['code']) is not None]
                _excluded_rows = [r for r in _att['rows']
                                  if _action_by_code.get(r['code']) is None]

                # ── 관심종목 저장 ─────────────────────────────────────────
                _wl_c1, _wl_c2 = st.columns([1, 2.2])
                with _wl_c1:
                    if st.button("이 목록을 관심종목으로 저장",
                                 width='stretch', key="btn_save_watchlist"):
                        _items = [{'code': r['code'], 'name': r['name']}
                                  for r in _att['rows']]
                        st.session_state['watchlist'] = _items
                        if ALLOW_LOCAL_STORE:
                            try:
                                portfolio.save_watchlist(_items)
                                st.success(f"{len(_items)}종목 저장 — 후보 발굴 방식에서 "
                                           f"'사용자 관심종목'으로 다시 스캔할 수 있습니다.")
                            except Exception as _ex:
                                st.warning(f"로컬 저장 실패: {_ex}")
                        else:
                            st.success(f"{len(_items)}종목 저장 (이 브라우저 세션에만 유지)")
                with _wl_c2:
                    _wl_now = st.session_state.get('watchlist') or []
                    if _wl_now:
                        st.caption("현재 관심종목 " + str(len(_wl_now)) + "개: "
                                   + ", ".join(w['name'] for w in _wl_now[:8])
                                   + (" 외" if len(_wl_now) > 8 else ""))

                for _r in _scored_rows:
                    _a = _r['attention']
                    _c = _r['components']
                    _act = _action_by_code.get(_r['code'])
                    _bucket = market_attention.classify_bucket(_a, _act)
                    _bcol = {'🏆 실전 추천 후보': '#35C98B',
                             '🔥 관심 급증·추격주의': '#F2B84B',
                             '🌱 조용한 선행 후보': '#4C8DFF',
                             '👀 관찰 후보': '#7C8AA0',
                             '🚫 추천 제외': '#ff453a'}.get(_bucket, '#7C8AA0')
                    # HTML 안에서 조건식을 조립하면 읽을 수 없어진다 — 먼저 문자열로 만든다
                    _raw_txt = f"원점수 {_a['market_attention_score']:.0f}"
                    if _a['penalty']:
                        _raw_txt += f" · 감점 −{_a['penalty']:.0f}"
                    _pen_html = ""
                    if _a['penalty_reasons']:
                        _pen_html = ("<br><span style='color:#F2B84B;font-size:12px;'>⚠️ "
                                     + " · ".join(_a['penalty_reasons']) + "</span>")
                    _ratio_txt = ""
                    if _c.get('turnover_ratio'):
                        _ratio_txt = (f" · 거래대금 {_c['turnover_ratio']:.1f}배"
                                      f"({_c.get('turnover_basis', '')})")

                    _cc1, _cc2 = st.columns([3, 1])
                    with _cc1:
                        st.markdown(
                            f"<div style='background:#161D2A;border-left:4px solid {_bcol};"
                            f"border-radius:8px;padding:8px 16px;margin-bottom:8px;'>"
                            f"<b style='color:#F3F6FA;font-size:16px;'>{_r['name']}</b> "
                            f"<span style='color:#9DAABC;font-size:13px;'>{_r['code']}</span><br>"
                            f"<span style='color:{_bcol};font-weight:700;font-size:13px;'>{_bucket}</span><br>"
                            f"<span style='color:#9DAABC;font-size:13px;'>"
                            f"시장 관심점수 <b>{_a['adjusted_attention_score']:.0f}</b>"
                            f"<span style='color:#9DAABC;'> ({_raw_txt})</span>"
                            f" · 퀀트 행동점수 <b>{fmt_num(_act, ',.0f')}</b></span><br>"
                            f"<span style='color:#9DAABC;font-size:13px;'>"
                            f"{_r.get('selection_reason', '')}{_ratio_txt}</span>"
                            f"{_pen_html}</div>", unsafe_allow_html=True)
                    with _cc2:
                        if st.button("분석 →", key=f"att_{_r['code']}",
                                     width='stretch'):
                            st.session_state['pending_search'] = f"{_r['name']} ({_r['code']})"
                            st.rerun()

                if not _scored_rows:
                    st.info("행동점수까지 산출된 후보가 없습니다. 아래 제외 사유를 확인하세요.")

                # 행동점수를 산출하지 못한 후보 — '미산출' 로 섞지 않고 사유와 함께 분리
                if _excluded_rows:
                    with st.expander(f"행동점수 미산출로 본 목록에서 제외된 "
                                     f"{len(_excluded_rows)}종목 (사유 보기)"):
                        st.caption("관심점수는 있으나 정밀 퀀트 분석이 유동성·데이터·"
                                   "교차검증 게이트에 걸려 행동점수를 내지 못한 종목입니다. "
                                   "점수 없이 카드에 섞으면 판단에 쓸 수 없어 분리했습니다.")
                        for _r in _excluded_rows:
                            _why = _fail_by_code.get(_r['code']) or "정밀분석 결과 없음"
                            _ec1, _ec2 = st.columns([3, 1])
                            _ec1.markdown(
                                f"**{_r['name']}** `{_r['code']}` · "
                                f"관심 {_r['attention']['adjusted_attention_score']:.0f}점  \n"
                                f"<span style='color:#F2B84B;font-size:13px;'>"
                                f"제외 사유: {_why[:120]}</span>",
                                unsafe_allow_html=True)
                            if _ec2.button("분석 →", key=f"attx_{_r['code']}",
                                           width='stretch'):
                                st.session_state['pending_search'] = \
                                    f"{_r['name']} ({_r['code']})"
                                st.rerun()
                _uk.spacer(28)

            if scan_failures:
                with st.expander(f"분석에서 제외된 {len(scan_failures)}개 종목 사유 보기"):
                    for f in scan_failures:
                        st.markdown(f"- **{f['name']}** (`{f['symbol']}`) — {f['reason']}")

            if len(top_recs) == 0:
                st.warning("**현재 추천주 없음** — 필수조건을 모두 통과한 종목이 없습니다. "
                           "무리한 신규 매수보다 현금 유지가 우선입니다.")
                if block_counter:
                    top_blocks = block_counter.most_common(5)
                    st.markdown(
                        "**가장 많이 걸린 차단 조건**\n\n"
                        + "\n".join(f"- {name} — {cnt}개 종목" for name, cnt in top_blocks)
                    )
            else:
                st.success(f"필수조건을 모두 통과한 종목: **{len(recommended)}개** (최대 3개 표출)")

                # --- Interactive Screener Table ---
                st.markdown("AI 퀀트 최적 종목 결과 (Clickable)")
                
                # Header (전략유형 및 월봉 10선 장기추세 컬럼 탑재)
                cols = st.columns([0.5, 1.8, 1.4, 1.1, 1.2, 1.2, 1.4, 1.2, 1.0, 1.2])
                headers = ["순위", "종목명 (클릭)", "전략유형", "현재가", "적정가", "상승여력%", "월봉 10선", "최종점수", "손익비", "상태"]
                for col, header in zip(cols, headers):
                    col.markdown(f"<div style='text-align:center; color:#4C8DFF; font-size:13px; font-weight:bold; border-bottom:2px solid #222C3C; padding-bottom:8px;'>{header}</div>", unsafe_allow_html=True)
                
                # Rows
                for i, r in enumerate(top_recs):
                    cols = st.columns([0.5, 1.8, 1.4, 1.1, 1.2, 1.2, 1.4, 1.2, 1.0, 1.2])
                    
                    cols[0].markdown(f"<div style='text-align:center; padding-top:8px;'><span style='background:#4C8DFF; color:#fff; padding:3px 8px; border-radius:12px; font-weight:bold;'>{i+1}</span></div>", unsafe_allow_html=True)
                    
                    with cols[1]:
                        _entry_badge = "🎯" if r.get('entry_candidate') else ""
                        if st.button(f"{_entry_badge}{r['name']}", key=f"btn_{r['symbol']}_{i}",
                                     width='stretch',
                                     help=("진입 후보 — 적정가 이하 & 순기대수익 양수. "
                                           "점수대별 실측 적중률은 종합 결론의 "
                                           "'가상 백테스트' 표기를 보세요."
                                           if r.get('entry_candidate') else None)):
                            # 스냅샷은 st.session_state['scan_results'] 안에 그대로 있으므로
                            # 종목만 전환하면 상세화면이 같은 객체를 찾아 재사용한다 (§17)
                            st.session_state['pending_search'] = f"{r['name']} ({r['symbol'].split('.')[0]})"
                            st.rerun()
                            
                    st_type = r.get('strategy_type', '💎 가치·반전형')
                    curr_p_str = f"{r['base_price']:,.0f}원"

                    tgt = r.get('target_fundamental')
                    target_p_str = f"{tgt:,.0f}원" if tgt is not None else "미산출"

                    upside_val = r.get('upside_pct')
                    if upside_val is None:
                        upside_str, upside_color = "미산출", "#9DAABC"
                    else:
                        upside_str = f"{upside_val:+.1f}%"
                        upside_color = "#35C98B" if upside_val > 0 else "#ff453a"

                    m10_stat = r.get('m10_status', '위')
                    m10_disp = r.get('m10_disparity', 0.0)
                    m10_col = "#35C98B" if m10_stat == "위" else "#ff453a"
                    m10_str = f"{m10_stat} ({m10_disp:+.1f}%)"
                    # 차트 관점 배지: DeMARK 매수 신호가 살아 있으면 함께 표기
                    _dstate = r.get('demark_entry_state')
                    if _dstate in ('COMPLETE', 'SETUP_DONE'):
                        m10_str += " · ⏱️매수신호"
                    elif _dstate == 'FORMING':
                        m10_str += " · ⏱️셋업중"

                    # 컬럼 헤더가 '손익비'이므로 실제 손익비를 넣는다 (구버전은 승률을 표시했음)
                    rr_val = r.get('reward_risk_ratio')
                    rr_str = f"{rr_val:.2f}" if rr_val is not None else "미산출"

                    cols[2].markdown(f"<div style='text-align:center; padding-top:8px; font-size:13px; font-weight:bold;'>{st_type}</div>", unsafe_allow_html=True)
                    cols[3].markdown(f"<div style='text-align:center; padding-top:8px; color:#F3F6FA; font-weight:bold;'>{curr_p_str}</div>", unsafe_allow_html=True)
                    cols[4].markdown(f"<div style='text-align:center; padding-top:8px; color:#4C8DFF; font-weight:bold;'>{target_p_str}</div>", unsafe_allow_html=True)
                    cols[5].markdown(f"<div style='text-align:center; padding-top:8px; color:{upside_color}; font-weight:700; font-size:16px;'>{upside_str}</div>", unsafe_allow_html=True)
                    cols[6].markdown(f"<div style='text-align:center; padding-top:8px; color:{m10_col}; font-weight:bold; font-size:13px;'>{m10_str}</div>", unsafe_allow_html=True)
                    cols[7].markdown(f"<div style='text-align:center; padding-top:8px; color:#4C8DFF; font-weight:bold; font-size:16px;'>{r['final_score']}점</div>", unsafe_allow_html=True)
                    cols[8].markdown(f"<div style='text-align:center; padding-top:8px;'>{rr_str}</div>", unsafe_allow_html=True)
                    
                    color = "#35C98B" if "추천주" in r['cat'] else ("#4C8DFF" if "매수" in r['cat'] else "#F2B84B")
                    cols[9].markdown(f"<div style='text-align:center; padding-top:8px; color:{color}; font-weight:bold; font-size:13px;'>{r['cat']}</div>", unsafe_allow_html=True)
                    
                st.info("**TIP:** 위 표에서 종목명 버튼을 클릭하면, 해당 종목이 자동으로 선택되고 하단의 상세 분석 화면이 즉시 갱신됩니다.")
                
            st.markdown(f"""
            <div style='display:flex; justify-content:space-around; background:#161D2A; padding:12px; border-radius:8px; margin-top:16px; '>
                <div style='text-align:center;'><span style='color:#9DAABC; font-size:15px;'>⏳ 눌림 대기</span><br><b style='color:#F3F6FA;'>{wait_pullback}개</b></div>
                <div style='text-align:center;'><span style='color:#9DAABC; font-size:15px;'>👀 관찰 후보</span><br><b style='color:#F3F6FA;'>{watch_list}개</b></div>
                <div style='text-align:center;'><span style='color:#9DAABC; font-size:15px;'>🚫 추천 제외</span><br><b style='color:#F3F6FA;'>{excluded}개</b></div>
            </div>
            """, unsafe_allow_html=True)

            # ── 📋 개장 전 확정 리포트 — 스캔 결과를 당일 파일로 고정 ──────────
            import premarket as _pm
            _pm_mkt = ""
            try:
                _pm_fs0 = (scan_results[0].get('snapshot') or {}).get('four_scores') or {}
                _pm_mkt = str(_pm_fs0.get('context_regime_label') or
                              _pm_fs0.get('market_regime_label') or '')
            except Exception:
                _pm_mkt = ""
            _pm_report, _pm_new = _pm.build_report(q_engine, scan_results,
                                                   market_label=_pm_mkt)
            if _pm_new:
                st.toast("📋 오늘의 개장 전 리포트를 고정 저장했습니다")
            st.session_state['premarket_report'] = _pm_report

    _uk.spacer(28)

# ═══════════════════════════════════════════════════════════════════════════
# 📋 오늘의 추천 — 개장 전 확정 리포트 (전일 확정 데이터 기준 · 장중 재계산 금지)
# ═══════════════════════════════════════════════════════════════════════════
import premarket as _pm_view

_pmr = st.session_state.get('premarket_report') or _pm_view.load_today_report()
st.markdown('<div id="nav-premarket"></div>', unsafe_allow_html=True)
if _pmr:
    st.markdown("## 오늘의 추천 — 개장 전 확정 리포트")
    _pm_ver = str(_pmr.get('engine_version') or '')
    st.caption(f"기준 데이터 **{_pmr.get('data_asof')}** · 생성 **{_pmr.get('generated_at')}** · "
               f"{_pmr.get('market_label') or ''}"
               + (f" · 엔진 **{_pm_ver}**" if _pm_ver else '') + "  \n"
               f"🔒 {_pmr.get('note')}")
    # 리포트는 사후 선택 방지를 위해 동결한다. 그런데 엔진을 바꾸면 동결된
    # 값이 낡는다 — 실제로 권장 매수가 산식을 바꿨는데 카드가 옛 값을
    # 그대로 보여 줬다. 낡았으면 화면이 먼저 말해야 한다.
    if _pm_ver and _pm_ver != _VER_NOW['model']:
        st.warning(f"이 리포트는 엔진 **{_pm_ver}** 로 만들어졌고 현재 엔진은 "
                   f"**{_VER_NOW['model']}** 입니다. 아래 가격은 예전 산식 "
                   f"기준이라 지금 계산과 다를 수 있습니다 — 사이드바에서 "
                   f"스캔을 다시 실행하면 새 엔진으로 만듭니다.")
    elif not _pm_ver:
        st.warning("이 리포트에는 만든 엔진 버전이 기록돼 있지 않습니다 "
                   "(예전 형식). 지금 엔진과 다를 수 있으니 스캔을 다시 "
                   "실행하는 편이 안전합니다.")
    _CLS_COLOR = {'오늘 사도 되는 종목': '#35C98B', '조건부로 사도 되는 종목': '#4C8DFF',
                  '오늘은 기다려야 하는 종목': '#F2B84B', '오늘은 사면 안 되는 종목': '#ff453a'}

    # 표시 정합 가드 — 분류 라벨이 '아주 쉬운 결론'과 모순되면 결론 쪽을 따른다
    # (제목은 사도 된다는데 본문이 '판단 보류'인 카드를 만들지 않는다. 가격·점수는 불변)
    def _pm_display_class(p):
        cls, easy = str(p.get('reco_class') or ''), str(p.get('easy_line') or '')
        # 다음 조건 엔진이 '추천 자격 없음'으로 본 종목은 추천 자리에 두지
        # 않는다. 26,350원짜리에 21,218원(-19.5%)을 오늘의 추천으로 내밀면
        # 계산은 맞아도 실행할 수 없는 값이다.
        _n = p.get('next_action') or {}
        if _n.get('exclude_reason') and not _n.get('reco_eligible'):
            return '오늘은 기다려야 하는 종목'
        if '보류' in easy and cls in ('오늘 사도 되는 종목', '조건부로 사도 되는 종목'):
            return '오늘은 기다려야 하는 종목'
        if '사지 마세요' in easy and cls != '오늘은 사면 안 되는 종목':
            return '오늘은 사면 안 되는 종목'
        return cls

    _picks_all = [{**p, 'reco_class': _pm_display_class(p)}
                  for p in (_pmr.get('picks') or [])]
    # 추천 카드에는 '사면 안 되는 종목'을 올리지 않는다 — 그건 추천이 아니라 제외다
    _picks_show = [p for p in _picks_all
                   if p['reco_class'] != '오늘은 사면 안 되는 종목'][:5]
    _picks_ban = [p for p in _picks_all
                  if p['reco_class'] == '오늘은 사면 안 되는 종목']
    _ASSET_KO = {'STOCK': '주식', 'ETF': 'ETF', 'ETF_LEV': '레버리지 ETF',
                 'ETF_INV': '인버스 ETF'}

    def _build_reco_card(p, news_txt, conf_txt):
        """
        스캔 결과 한 건 → 카드가 읽을 값 묶음.

        여기서 지키는 것 (하나라도 어기면 사용자가 값을 잘못 읽는다):
          · 가격 순서는 늘 현재가 → 권장 → 목표 → 손절
          · 목표·손절은 **권장가 기준**만 카드에 올린다. 현재가 기준(보유자용)은
            같은 카드에 섞지 않고 경고 상자로 한 줄만 안내한다.
          · 권장가가 없으면 목표·손절을 **아예 감춘다** — 참고값을 실행 가격
            자리에 두지 않는다.
          · 권장가가 멀면(2σ 초과) 목표·손절을 흐리게 — 닿지 않을 값을
            진하게 두면 실행 가격처럼 보인다.
        """
        _n = p.get('next_action') or {}
        cls = str(p.get('reco_class') or '')
        price, rec = p.get('price'), p.get('rec_buy')
        e_t1, e_stop = p.get('entry_target_1st'), p.get('entry_stop_price')
        sig, reach = p.get('rec_buy_sigma'), p.get('rec_buy_reach')
        gap = ((float(price) / float(rec) - 1) * 100
               if (price and rec) else None)
        far = bool(sig is not None and sig > 2.0) or bool(
            gap is not None and gap >= 30)

        if not rec:
            state = 'neg' if '사면 안' in cls else 'hold'
        elif '사도 되는' in cls:
            state = 'pos'
        elif '사면 안' in cls:
            state = 'neg'
        else:
            state = 'warn'

        # 상태 라벨도 '무엇을 기다리는가'로 — '관망'만 쓰면 행동을 못 정한다
        _NA_LABEL = {'buy_now': '지금 분할매수', 'pullback': '눌림목 대기',
                     'breakout': '돌파 확인 대기', 'observe': '장기 관찰',
                     'blocked': '매수 차단', 'no_data': '데이터 부족'}
        label = (_NA_LABEL.get(_n.get('kind'))
                 or ('사실상 관망' if (far and rec) else
                     cls.replace('오늘은 ', '오늘 ') or '판단 보류'))
        if _n.get('kind') == 'buy_now':
            state = 'pos'
        elif _n.get('kind') in ('blocked',):
            state = 'neg'
        elif _n.get('kind') in ('observe', 'no_data'):
            state = 'hold'
        elif _n.get('kind'):
            state = 'warn'

        # 쉬운 설명 — "사지 마세요"로 끝내지 않는다. 다음 조건 엔진이
        # 낸 한 줄을 먼저 쓰고, 조건들은 아래 목록으로 붙인다.
        if _n.get('headline'):
            say = f"<b>{_n['headline']}</b>"
            if rec and gap is not None and gap > 0:
                say += f" 현재가는 권장 매수가보다 {gap:.1f}% 높습니다."
        elif rec and gap is not None and gap > 0:
            say = (f"현재가가 권장 매수가보다 <b>{gap:.1f}%</b> 높습니다. "
                   + ("단기간에 매수 구간까지 내려올 가능성이 낮아 "
                      "<b>지금은 기다리는 편</b>이 낫습니다."
                      if far else "조금만 기다리면 매수 구간에 닿습니다."))
        elif rec:
            say = "현재가가 이미 매수 구간 안에 있습니다."
        else:
            say = str(p.get('easy_line') or '')

        rec_basis = ''
        if rec and gap is not None:
            rec_basis = f"{-gap:+.1f}%"
            if sig is not None:
                rec_basis += f" · {sig}σ · {reach}"

        # 보유자 기준은 섞지 않는다 — 있으면 한 줄 안내로만
        hold_note = ''
        if p.get('target') and p.get('stop') and rec:
            hold_note = (
                f"보유 중이시면 기준이 다릅니다 — 현재가 기준 1차 목표 "
                f"{float(p['target']):,.0f}원 · 손절 {float(p['stop']):,.0f}원. "
                f"<b>분석 보기</b>에서 확인하세요.")
        elif not rec:
            hold_note = ("<b>진입 기준이 없어 목표가·손절가를 표시하지 "
                         "않습니다.</b> 참고값은 분석 보기에서 확인하세요. "
                         "지금은 신규 매수 판단을 보류합니다.")

        _cb = p.get('confidence_band') or {}
        return {
            'state': state, 'state_label': label,
            'name': p.get('name'), 'code': p.get('code'),
            'asset_ko': _ASSET_KO.get(str(p.get('asset_type')),
                                      p.get('asset_type')),
            'score': p.get('score'),
            'conf': (f"신뢰도 {p['confidence']:.0f}"
                     if isinstance(p.get('confidence'), (int, float)) else None),
            'price': price,
            'rec_buy': rec, 'rec_basis': rec_basis,
            'rec_na': ('차단됨' if '사면 안' in cls else '미산출'),
            'target': e_t1 if rec else None,
            'target_basis': ('권장가 기준'
                             + (f" · 손익비 {p['entry_rr']}:1"
                                if p.get('entry_rr') else '')) if rec else '',
            'stop': e_stop if rec else None,
            'stop_basis': '권장가 기준' if rec else '',
            'dim_levels': far,
            'say': say, 'hold_note': hold_note,
            'news': ' · '.join(news_txt) if news_txt else '특이 뉴스 없음',
            'hit': conf_txt,
            'horizon': (f"예상 보유 {p['horizon_days']}거래일"
                        if p.get('horizon_days') else None),
            # 다음 조건 — 무엇을 기다리는지 카드에 적는다
            'next_conditions': [c['text'] for c in (_n.get('conditions') or [])],
        }

    if not _picks_show:
        st.info("오늘은 사도 되는·기다릴 후보가 없습니다 — 전 종목이 제외됐습니다. "
                "없는 날은 관망이 결론입니다 (아래 제외 목록에서 이유를 확인하세요).")
    # 한 줄에 5개를 우겨 넣으면 카드 폭이 ~280px 로 줄어 '242,500원'의 원이
    # 잘리고 종목명이 어색하게 접힌다. 한 줄 3개로 두면 ~450px 이 나온다.
    # 스트림릿 컬럼은 자동 줄바꿈이 없으므로 직접 묶어서 여러 줄로 만든다.
    _PER_ROW = 3
    _pm_cols = []
    for _s in range(0, len(_picks_show) or 1, _PER_ROW):
        _n = min(_PER_ROW, max(1, len(_picks_show) - _s))
        _row = st.columns(_PER_ROW)          # 마지막 줄도 폭을 맞춘다
        _pm_cols.extend(_row[:_n])
    for _pi, _p in enumerate(_picks_show):
        _cc = _CLS_COLOR.get(_p.get('reco_class'), '#9DAABC')
        _cb_p = _p.get('confidence_band') or {}
        _conf_txt = (f"과거 동점수대 적중 {_cb_p['hit_rate']:.0f}% (n={_cb_p['n']})"
                     if _cb_p.get('hit_rate') is not None and (_cb_p.get('n') or 0) >= 30
                     else "적중률 표본 부족")
        _news_txt = []
        if _p.get('news_fresh'):
            _news_txt.append(f"신선 재료 {_p['news_fresh']}건")
        if _p.get('news_risk'):
            _news_txt.append(f"⚠️위험 낱말 {_p['news_risk']}건")
        if _p.get('news_lagging'):
            _news_txt.append(f"후행 보도 {_p['news_lagging']}건 제외")
        # 갭 표기 (라운드 2.5) — 조건부 매수가와 현재 기준가의 거리. 갭이 크면
        # 실측상 '추격 위험' 구간 성과가 최악(54.6%·비용후 -0.98%)임을 경고한다.
        _gap_html = ""
        if _p.get('rec_buy') and _p.get('price') and '이하로 내려올 때만' in str(_p.get('easy_line')):
            _gap_pct = (float(_p['price']) / float(_p['rec_buy']) - 1) * 100
            if _gap_pct > 0:
                _gap_warn = (" — 갭이 커서 단기 도달 가능성이 낮습니다. 사실상 관망"
                             if _gap_pct >= 7 else "")
                _gap_html = (f"<p style='margin:0 0 8px 0; font-size:12px; "
                             f"color:{'#F2B84B' if _gap_pct >= 7 else _TOK['tx2']};'>"
                             f"기준가가 권장보다 {_gap_pct:+.1f}% 위{_gap_warn}</p>")
        with _pm_cols[_pi]:
            st.markdown(_uk.reco_card(_build_reco_card(_p, _news_txt, _conf_txt),
                                      theme=_theme), unsafe_allow_html=True)
            # 카드 하단 세 동작. 여기서 바로 처리해야 카드를 떠나지 않는다.
            _b1, _b2, _b3 = st.columns([1.4, 1, 1])
            _sym, _cd, _nm = (_p.get('symbol'), _p.get('code'), _p.get('name'))
            with _b1:
                if st.button("분석 보기", key=f"pm_go_{_sym}_{_pi}",
                             width='stretch', type='primary'):
                    st.session_state['pending_search'] = f"{_nm} ({_cd})"
                    st.rerun()
            with _b2:
                _wl_now = st.session_state.get('watchlist') or []
                _in_wl = any(str(w.get('code')) == str(_cd) for w in _wl_now)
                if st.button('관심 추가됨' if _in_wl else '관심 추가',
                             key=f"pm_wl_{_sym}_{_pi}", width='stretch',
                             help=('이미 관심종목입니다' if _in_wl else
                                   '관심종목에 넣습니다 — 후보 발굴 방식에서 '
                                   "'사용자 관심종목'으로 다시 스캔할 수 있습니다"),
                             disabled=_in_wl):
                    _items = _wl_now + [{'code': _cd, 'name': _nm}]
                    st.session_state['watchlist'] = _items
                    if ALLOW_LOCAL_STORE:
                        # 저장 실패를 삼키면 사용자는 저장된 줄 안다
                        try:
                            portfolio.save_watchlist(_items)
                        except Exception as _ex:
                            st.warning(f"관심종목 파일 저장 실패 — 이 세션에만 "
                                       f"남습니다 ({type(_ex).__name__})")
                    st.rerun()
            with _b3:
                if st.button("보유 등록", key=f"pm_pos_{_sym}_{_pi}",
                             width='stretch',
                             help='이 종목을 보유종목으로 등록합니다 — '
                                  '수량·평단가는 보유종목 화면에서 채웁니다'):
                    # 수량·평단가를 모르는 채로 지어내지 않는다. 0 으로 넣고
                    # 보유종목 화면을 열어 사용자가 채우게 한다.
                    _mkt = ('KOSDAQ' if str(_sym).endswith('.KQ') else 'KOSPI')
                    st.session_state['positions'] = (
                        (st.session_state.get('positions') or [])
                        + [portfolio.PortfolioPosition(
                            ticker=_sym, stock_name=_nm, market=_mkt,
                            quantity=0.0, average_buy_price=0.0,
                            source_type='scan_card')])
                    st.session_state['show_portfolio'] = True
                    st.toast(f"{_nm} 등록 — 보유종목 화면에서 수량·평단가를 "
                             f"채워 주세요")
                    st.rerun()
    if _picks_ban:
        with st.expander(f"오늘 제외된 종목 {len(_picks_ban)}건 — 사면 안 되는 이유",
                         expanded=False):
            for _b in _picks_ban:
                st.markdown(f"- **{_b.get('name')}** ({_b.get('code')} · "
                            f"{_b.get('score')}점) — {_b.get('easy_line')}  \n"
                            f"  <span style='font-size:12px; color:{_TOK['tx2']};'>"
                            f"{' / '.join(_b.get('reasons') or []) or '게이트 차단'}"
                            f"</span>", unsafe_allow_html=True)
    with st.expander("지난 개장 전 추천의 실제 성과 (사후 검증)"):
        _hist = _pm_view.grade_history(engine_init)
        if _hist:
            st.markdown(f"지난 추천 **{_hist['n']}건** — 목표 도달 {_hist['target']} · "
                        f"손절 {_hist['stop']} · 미결 {_hist['open']} "
                        f"(분모 = 목표+손절, 미결은 별도)")
            for _h in _hist['rows'][::-1]:
                _oe = {'TARGET': '🟢', 'STOP': '🔴', 'OPEN': '⏳'}.get(_h['outcome'], '·')
                st.caption(f"{_oe} {_h['date']} {_h['name']} ({_h['reco_class']}) → "
                           f"{_h['outcome']} {_h['return_pct']:+.1f}%")
        else:
            st.caption("아직 채점할 과거 추천이 없습니다. 리포트가 쌓이면 여기서 "
                       "실제 성과를 그대로 보여줍니다 — 숨기지 않습니다.")
elif st.session_state.get('scan_results') is None:
    st.caption("오늘의 개장 전 리포트는 위 **트렌드 탐색기**에서 스캔을 실행하면 "
               "전일 확정 데이터 기준으로 생성·고정됩니다.")

# ═══════════════════════════════════════════════════════════════════════════
# 💼 내 보유종목 화면
# ═══════════════════════════════════════════════════════════════════════════
st.markdown('<div id="nav-holdings"></div>', unsafe_allow_html=True)
if st.session_state.get('show_portfolio'):
    _uk.spacer(28)
    st.header("내 보유종목")
    st.caption("평균 매수가는 **보유·축소·손절 판단에만** 사용합니다. "
               "미래 예측·적정가·종목점수 계산에는 들어가지 않습니다 (앵커링 방지).")

    # 보유종목이 없으면 '분석' 탭은 빈 화면이다. 그때는 '가져오기'를 앞에 둬서
    # 화면을 열자마자 등록 수단이 보이게 한다.
    if st.session_state.get('positions'):
        p_tab_view, p_tab_import, p_tab_manage = st.tabs(
            ["📊 포트폴리오 분석", "📥 가져오기 / 입력", "⚙️ 저장·삭제"])
    else:
        p_tab_import, p_tab_view, p_tab_manage = st.tabs(
            ["📥 가져오기 / 입력", "📊 포트폴리오 분석", "⚙️ 저장·삭제"])

    # ── 가져오기 / 직접 입력 ────────────────────────────────────────────
    with p_tab_import:
        st.info("증권사 로그인 자동화·쿠키 수집·비공식 보유자산 API는 사용하지 않습니다. "
                "Npay 증권 화면은 사용자가 직접 대조하는 보조 수단으로만 참고하세요. "
                "('내 자산'은 결제일 기준이라 국내주식은 최대 2영업일 지연될 수 있습니다.)")

        up = st.file_uploader("증권사 CSV / Excel 파일", type=["csv", "xlsx", "xls"])
        if up is not None:
            try:
                df_raw = portfolio.read_table(up.getvalue(), up.name)
                st.success(f"{len(df_raw)}행 읽음 · 열: {', '.join(map(str, df_raw.columns))}")
                auto = portfolio.suggest_column_mapping(list(df_raw.columns))
                st.markdown("**열 매핑** (자동 인식 실패 항목은 직접 선택하세요)")
                cols_opt = ["(사용 안 함)"] + [str(c) for c in df_raw.columns]
                mapping, mc = {}, st.columns(2)
                for i, (fld, ko) in enumerate([
                        ('ticker', '종목코드*'), ('stock_name', '종목명*'),
                        ('quantity', '보유수량*'), ('average_buy_price', '평균매수가*'),
                        ('cost_amount', '매입금액'), ('broker_name', '증권사'),
                        ('account_name', '계좌별칭'), ('acquisition_date', '취득일')]):
                    cur = auto.get(fld)
                    idx = cols_opt.index(str(cur)) if cur and str(cur) in cols_opt else 0
                    with mc[i % 2]:
                        sel = st.selectbox(ko, cols_opt, index=idx, key=f"map_{fld}")
                    mapping[fld] = None if sel == "(사용 안 함)" else sel

                if st.button("가져오기 실행", type="primary"):
                    def _resolve_market(code):
                        t, _n, _i = engine_init.fetch_and_update_naver_realtime(code)
                        return "KOSDAQ" if (t or "").endswith(".KQ") else "KOSPI"
                    try:
                        pos, warns = portfolio.import_positions(
                            df_raw, mapping, resolve_market=None,
                            source_type="excel_import" if up.name.lower().endswith(('.xlsx', '.xls'))
                            else "csv_import")
                        st.session_state['positions'] = pos
                        st.success(f"{len(pos)}종목 가져오기 완료")
                        for w in warns:
                            st.warning(w)
                    except Exception as ex:
                        st.error(f"가져오기 실패: {ex}")
            except Exception as ex:
                st.error(f"파일을 읽지 못했습니다: {ex}")

        def make_name_resolver():
            """
            종목명 → 티커. 정확검색이 실패하면 유사 후보를 모아 두었다가
            미리보기에서 사람이 고르게 한다. 자동으로 확정하지 않는다 —
            '코택'을 '코텍'으로 멋대로 바꾸면 엉뚱한 종목이 등록될 수 있다.
            """
            st.session_state['name_candidates'] = {}

            def _r(nm):
                try:
                    t, real, cands = engine_init.resolve_name_with_fallback(nm)
                except Exception:
                    return None, None
                if not t and cands:
                    st.session_state['name_candidates'][nm] = cands
                return t, real
            return _r

        # ═══ 📗 엑셀로 가져오기 — OCR 을 아예 거치지 않는 가장 정확한 경로 ═══
        _uk.spacer(28)
        st.markdown("엑셀 파일로 가져오기 (가장 정확)")
        st.caption("스크린샷 인식은 글자를 잘못 읽을 수 있습니다. **증권사 HTS 에서 내려받은 "
                   "엑셀** 이나 아래 **양식**을 채워 올리면 숫자를 그대로 읽어 오독이 없습니다.")

        _xc1, _xc2 = st.columns(2)
        with _xc1:
            _tpl_bytes, _tpl_name, _tpl_mime = portfolio.build_template_bytes()
            st.download_button("📥 입력 양식 내려받기", data=_tpl_bytes,
                               file_name=_tpl_name, mime=_tpl_mime,
                               width='stretch', key="btn_dl_template")
            st.caption("종목코드·종목명·보유수량·평균매수가 네 칸만 채우면 됩니다.")
        with _xc2:
            _cur_pos = st.session_state.get('positions') or []
            _exp_df = portfolio.positions_to_dataframe(_cur_pos)
            st.download_button(
                f"📤 지금 보유종목 내보내기 ({len(_cur_pos)}종목)",
                data=_exp_df.to_csv(index=False).encode("utf-8-sig"),
                file_name="내_보유종목.csv", mime="text/csv",
                width='stretch', disabled=not _cur_pos,
                key="btn_export_positions")
            st.caption("백업하거나 엑셀에서 수정한 뒤 다시 올릴 수 있습니다.")

        _xls = st.file_uploader("엑셀·CSV 파일 (HTS 내보내기 또는 위 양식)",
                                type=["xlsx", "xls", "csv"], key="xls_uploader")
        if _xls is not None:
            try:
                _df_x = portfolio.read_table(_xls.getvalue(), _xls.name)
                st.success(f"{len(_df_x)}행 읽음 · 인식된 열: "
                           + ", ".join(map(str, _df_x.columns))[:200])
                _auto = portfolio.suggest_column_mapping(list(_df_x.columns))
                _hdr_map = portfolio.classify_header_cells([str(c) for c in _df_x.columns])
                _cols_x = ["(사용 안 함)"] + [str(c) for c in _df_x.columns]

                def _pick(field, alt_idx):
                    """자동 매핑 → 없으면 표 헤더 분류기 결과로 채운다."""
                    cur = _auto.get(field)
                    if cur is None and alt_idx is not None and alt_idx < len(_df_x.columns):
                        cur = str(_df_x.columns[alt_idx])
                    return _cols_x.index(str(cur)) if cur and str(cur) in _cols_x else 0

                _mx = {}
                _mcol = st.columns(2)
                for _i, (_fld, _ko, _alt) in enumerate([
                        ('ticker', '종목코드 *', _hdr_map.get('code')),
                        ('stock_name', '종목명 *', _hdr_map.get('name')),
                        ('quantity', '보유수량 *', _hdr_map.get('quantity')),
                        ('average_buy_price', '평균매수가 *', _hdr_map.get('price'))]):
                    with _mcol[_i % 2]:
                        _sel = st.selectbox(_ko, _cols_x, index=_pick(_fld, _alt),
                                            key=f"xmap_{_fld}")
                    _mx[_fld] = None if _sel == "(사용 안 함)" else _sel

                if st.button("엑셀에서 가져오기", type="primary", key="btn_xls_import"):
                    _missing = [k for k in ('ticker', 'stock_name', 'quantity',
                                            'average_buy_price') if not _mx.get(k)]
                    # 종목코드가 없어도 종목명이 있으면 이름으로 찾을 수 있다
                    if 'ticker' in _missing and _mx.get('stock_name'):
                        _missing.remove('ticker')
                    if _missing:
                        st.error("필수 열을 선택하세요: " + ", ".join(_missing))
                    else:
                        _resolver = make_name_resolver()
                        _rows_x, _warn_x = [], []
                        for _ridx, _r in _df_x.iterrows():
                            _nm = (str(_r.get(_mx['stock_name'], '')).strip()
                                   if _mx.get('stock_name') else '')
                            _cd = (portfolio.read_code_cell(_r.get(_mx['ticker']))[0]
                                   if _mx.get('ticker') else None)
                            _qt = portfolio._cell_number(_r.get(_mx['quantity']))
                            _pr = portfolio._cell_number(_r.get(_mx['average_buy_price']))
                            if not _nm and not _cd:
                                continue
                            if _qt is None or _pr is None:
                                _warn_x.append(f"{_ridx + 2}행 건너뜀 — 수량·평단가를 "
                                               f"숫자로 읽지 못했습니다: {_nm or _cd}")
                                continue
                            _tk = f"{_cd}.KS" if _cd else None
                            if _nm and _resolver:
                                try:
                                    _t2, _real2 = _resolver(_nm)
                                except Exception:
                                    _t2, _real2 = None, None
                                if _t2:
                                    if _cd and str(_t2).split('.')[0] != _cd:
                                        _warn_x.append(
                                            f"'{_nm}' 종목코드({_cd})와 종목명이 다른 종목을 "
                                            f"가리켜 종목명 기준({str(_t2).split('.')[0]})으로 "
                                            f"잡았습니다.")
                                    _tk = _t2
                                    _cd = str(_t2).split('.')[0]
                                    if _real2:
                                        _nm = _real2
                            _rows_x.append({'종목코드': _cd or '', '종목명': _nm or (_cd or ''),
                                            '보유수량': _qt, '평균매수가': _pr,
                                            '_ticker': _tk})
                        st.session_state['paste_preview'] = _rows_x
                        for _w in _warn_x[:6]:
                            st.warning(_w)
                        if _rows_x:
                            st.success(f"{len(_rows_x)}종목을 읽었습니다 — 아래 "
                                       f"**미리보기**에서 확인한 뒤 '반영'을 누르세요. "
                                       f"엑셀 숫자를 그대로 쓰므로 OCR 오독이 없습니다.")
                        else:
                            st.error("가져올 행이 없습니다. 열 선택을 확인해 주세요.")
            except Exception as _xexc:
                st.error(f"파일을 읽지 못했습니다 ({type(_xexc).__name__}): {_xexc}")

        _uk.spacer(28)
        st.markdown("스크린샷으로 가져오기")
        st.caption("인식 결과는 반드시 미리보기에서 확인하세요. 정확도가 중요하면 위 "
                   "**엑셀 가져오기**를 쓰는 편이 안전합니다.")
        _ocr = portfolio.ocr_backend()
        if _ocr is None and not ALLOW_LOCAL_STORE:
            # 온라인(클라우드) 실행인데 엔진이 안 잡힌 경우. 서버에 Tesseract 를 함께
            # 배포하도록 되어 있으므로(packages.txt) 여기까지 왔다면 그 설치가 아직
            # 반영되지 않았다는 뜻이다. 사용자 PC 문제로 오해하지 않도록 밝혀 둔다.
            st.warning("**지금은 서버에서 스크린샷 인식 엔진을 찾지 못했습니다** — "
                       "여러분 PC의 문제가 아닙니다. 서버에 OCR 엔진(Tesseract)을 함께 배포하도록 "
                       "설정돼 있으나, 방금 배포된 경우 반영까지 몇 분 걸릴 수 있습니다.")
            st.caption("그 사이에는 아래 **표 붙여넣기**를 이용하세요 — 증권사 화면에서 표를 드래그해 "
                       "복사하면 그대로 읽습니다. 내 PC에서 실행할 때는 `pip install easyocr` 로 "
                       "더 정확한 엔진을 쓸 수 있습니다.")
        elif _ocr is None:
            st.warning("**스크린샷 인식 불가** — 이 PC에 OCR 엔진이 설치되어 있지 않습니다.")
            st.code("pip install easyocr", language="bash")
            st.caption(portfolio.OCR_INSTALL_HINT)
        else:
            st.caption(f"OCR 엔진: **{_ocr}** · 보유종목 화면을 캡처해 올리면 표를 읽어 미리보기로 만듭니다.")
            st.info(
                "스크린샷 인식에는 오류가 발생할 수 있습니다. 시스템이 **종목코드·현재가·수익률·"
                "평가손익·합계금액을 교차검증**해 오류 가능성이 높은 값을 표시하고 대안 후보를 "
                "제시하지만, 저장 전 반드시 확인해 주세요.\n\n"
                "**현재가·수익률·평가손익 열이 함께 보이도록 캡처하면 검증 정확도가 크게 올라갑니다** "
                "— 그 열들이 있어야 `평가손익 = (현재가−평단)×수량` 관계로 오독을 잡아낼 수 있습니다."
            )
            def _recognize_image(img_bytes):
                """업로드·클립보드 두 경로가 같은 인식 절차를 쓰도록 한 곳에 모은다."""
                with st.spinner("이미지에서 텍스트를 읽는 중..."):
                    txt, _backend, err = portfolio.extract_text_from_image(img_bytes)
                if err:
                    st.error(f"인식 실패: {err}")
                    return
                st.session_state['last_ocr_text'] = txt or ""
                with st.expander("인식된 원문 보기"):
                    st.code(txt or "(빈 결과)", language="text")

                rows, warns = portfolio.parse_freeform_holdings(
                    txt, resolve_name=make_name_resolver())
                st.session_state['paste_preview'] = rows
                for w in warns[:6]:
                    st.warning(w)
                if len(warns) > 6:
                    with st.expander(f"경고 {len(warns) - 6}건 더 보기"):
                        for w in warns[6:]:
                            st.write("· " + w)
                if rows:
                    st.success(f"{len(rows)}종목 인식 — 아래 **미리보기**에서 수량·평단가를 "
                               f"확인·수정한 뒤 '반영'을 누르세요.")
                else:
                    st.error("종목을 인식하지 못했습니다. 표 영역만 크게 캡처하거나 "
                             "아래 '표 붙여넣기'를 이용하세요.")

            # ── ① 브라우저에서 바로 붙여넣기 (로컬·온라인 모두) ────────────────
            # 브라우저의 paste 이벤트로 사용자 클립보드를 읽으므로 원격 접속에서도
            # 동작한다. (서버 클립보드를 읽던 기존 방식은 아래 ②로 남겨 둔다.)
            st.markdown("**① 캡처해서 바로 붙여넣기** — 파일로 저장할 필요 없습니다.")
            _pasted = paste_image_box(key="paste_box_holdings")
            if _pasted:
                _img, _perr = portfolio.decode_pasted_image(_pasted)
                if _perr:
                    st.error(_perr)
                elif _img and st.session_state.get('paste_nonce') != _pasted.get('nonce'):
                    st.session_state['paste_nonce'] = _pasted.get('nonce')
                    st.session_state['clip_image'] = _img
                    _recognize_image(_img)
                elif _img:
                    st.caption("위 상자에 다시 붙여넣으면 새 이미지로 인식합니다.")

            # ── ② 서버 클립보드 직접 읽기 (로컬 실행 전용) ─────────────────────
            # 이 경로는 **서버 프로세스의 클립보드**를 읽는다. 로컬 실행에서는 그게 곧
            # 사용자의 클립보드지만, 클라우드에서는 남의 서버 클립보드를 읽으려 드는
            # 무의미한 동작이라 원격에서는 노출하지 않는다.
            if is_local_session():
                with st.expander("붙여넣기가 안 될 때 — 클립보드에서 직접 읽기 (이 PC 실행 전용)"):
                    if st.button("클립보드 이미지 읽기", key="btn_clip_ocr"):
                        _img2, _cerr = portfolio.grab_clipboard_image()
                        if _cerr:
                            st.error(_cerr)
                        else:
                            st.session_state['clip_image'] = _img2
                            _recognize_image(_img2)
            if st.session_state.get('clip_image'):
                with st.expander("붙여넣은 이미지 보기"):
                    st.image(st.session_state['clip_image'], width='stretch')

            # ── ③ 파일로 올리기 ────────────────────────────────────────────
            st.markdown("**② 이미지 파일로 올리기** (붙여넣기가 막힌 브라우저용)")
            shot = st.file_uploader("스크린샷 이미지 (PNG/JPG)", type=["png", "jpg", "jpeg"],
                                    key="shot_uploader")
            if shot is not None:
                st.image(shot, caption="업로드한 스크린샷", width='stretch')
                if st.button("이미지에서 인식하기", key="btn_file_ocr"):
                    _recognize_image(shot.getvalue())

        _uk.spacer(28)
        st.markdown("화면에서 표를 긁어 붙여넣기")
        st.caption("네이버 증권 **내 자산** 화면이나 증권사 앱에서 보유종목 표를 드래그해 복사한 뒤 "
                   "그대로 붙여넣으세요. 헤더가 없어도, 줄마다 형식이 달라도 인식합니다. "
                   "붙여넣은 뒤 아래 미리보기에서 직접 고칠 수 있습니다.")
        with st.expander("인식하는 형태 보기"):
            st.code("005930  (종목명)  10  210,000\n"
                    "(종목명) 10주 210,000원\n"
                    "(종목명),10,210000\n"
                    "005930 10 210000\n"
                    "\n"
                    "· 헤더 줄, 합계 줄, 빈 줄은 자동으로 건너뜁니다\n"
                    "· 평가손익·수익률 열이 섞여 있어도 수량·평단가만 골라냅니다\n"
                    "· 종목코드가 없으면 종목명으로 조회합니다", language="text")

        paste = st.text_area("여기에 붙여넣기", height=140, key="freeform_paste")
        if st.button("인식하기", type="primary"):
            rows, warns = portfolio.parse_freeform_holdings(
                paste, resolve_name=make_name_resolver())
            st.session_state['paste_preview'] = rows
            for w in warns:
                st.warning(w)
            if rows:
                st.success(f"{len(rows)}종목 인식 — 아래에서 확인 후 '반영'을 누르세요.")

        # ── 열 직접 지정 (헤더가 없거나 자동 인식이 실패했을 때의 최종 수단) ──
        _src_text = paste or st.session_state.get('last_ocr_text') or ""
        _prev_rows = st.session_state.get('paste_preview') or []
        _needs_manual = any(r.get('보유수량') is None or r.get('평균매수가') is None
                            for r in _prev_rows)
        if _src_text.strip():
            with st.expander("열을 직접 지정하기" + ("  ⬅️ 자동 인식 실패" if _needs_manual else ""),
                             expanded=_needs_manual):
                _ncol, _cells = portfolio.preview_columns(_src_text)
                if _ncol < 2:
                    st.caption("열을 나눌 수 없습니다. 표 형태로 복사했는지 확인하세요.")
                else:
                    st.caption(f"인식된 열 {_ncol}개 — 아래 표에서 몇 번째 열이 무엇인지 고르세요. "
                               f"추측하지 않으므로 지정이 맞으면 결과도 맞습니다.")
                    st.dataframe(pd.DataFrame(
                        _cells, columns=[f"{i}" for i in range(_ncol)]),
                        width='stretch', hide_index=True)
                    _opts = list(range(_ncol))
                    _mc1, _mc2, _mc3, _mc4 = st.columns(4)
                    _skip = _mc1.number_input("건너뛸 윗줄 수", 0, 10, 1, key="mancol_skip")
                    _nm = _mc2.selectbox("종목명 열", _opts, index=min(1, _ncol - 1), key="mancol_name")
                    _qt = _mc3.selectbox("수량 열", _opts, index=min(4, _ncol - 1), key="mancol_qty")
                    _pr = _mc4.selectbox("평단가 열", _opts, index=_ncol - 1, key="mancol_price")
                    if st.button("지정한 열로 다시 읽기", key="btn_mancol"):
                        _r2, _w2 = portfolio.parse_with_explicit_columns(
                            _src_text, name_col=_nm, qty_col=_qt, price_col=_pr,
                            skip_rows=_skip, resolve_name=make_name_resolver())
                        st.session_state['paste_preview'] = _r2
                        for _w in _w2[:6]:
                            st.warning(_w)
                        if _r2:
                            st.success(f"{len(_r2)}종목을 지정한 열로 읽었습니다.")
                        st.rerun()

        preview = st.session_state.get('paste_preview')
        if preview:
            st.markdown("미리보기 — 반영 전 확인")
            _unresolved = [r for r in preview if not r.get('_ticker')]
            if _unresolved:
                _cands = st.session_state.get('name_candidates') or {}
                st.error(f"**종목을 찾지 못한 행 {len(_unresolved)}건** — "
                         f"이름이 잘못 인식됐을 수 있습니다(예: 대한항공→대한항곰). "
                         f"아래에서 맞는 종목을 고르세요.")
                for _ur in _unresolved:
                    _nm = str(_ur.get('종목명') or '')
                    _cl = _cands.get(_nm) or []
                    _uc1, _uc2 = st.columns([1, 2])
                    _uc1.markdown(f"**{_nm}**  \n"
                                  f"<span style='color:#9DAABC;font-size:13px;'>"
                                  f"{fmt_num(_ur.get('보유수량'), ',.0f', '주')} · "
                                  f"평단 {fmt_num(_ur.get('평균매수가'), ',.0f', '원')}</span>",
                                  unsafe_allow_html=True)
                    if not _cl:
                        _uc2.caption("유사 종목을 찾지 못했습니다. 아래 표에 종목코드 6자리를 직접 넣으세요.")
                        continue
                    _labels = ["(고르지 않음)"] + [
                        f"{c['name']} ({c['code']}) · 유사도 {c['score']:.0%}" for c in _cl]
                    _pick = _uc2.selectbox("맞는 종목", _labels, key=f"nc_{_nm}",
                                           label_visibility="collapsed")
                    if _pick != "(고르지 않음)":
                        _c = _cl[_labels.index(_pick) - 1]
                        _ur['종목코드'] = _c['code']
                        _ur['종목명'] = _c['name']
                        _ur['_ticker'] = _c['symbol']
                        st.session_state['paste_preview'] = preview
                st.caption("고른 뒤 아래 표에 반영됩니다. 고르지 않은 행은 반영 시 제외됩니다.")
            # ── 인식 결과 교차검증 (§12·§13) ──────────────────────────────
            # 증권사 화면은 같은 사실을 여러 열로 중복 표기한다:
            #   평가손익 = (현재가−평단)×수량,  수익률 = 현재가÷평단−1
            # 이 중복이 오독을 잡아내는 유일한 근거다.
            # 현재가는 조회하면 되는 값이다 — 화면에서 읽을 이유가 없다.
            # (OCR 이 열을 잘못 집으면 영원무역 90원, 대한항공 26원 같은 값이 들어온다)
            # 수익률·평가손익도 실시간 현재가에서 계산해 보여준다.
            preview, _npx, _pxfail = portfolio.enrich_with_market_prices(
                preview, light_quote)
            _mkt_px = {str(r.get('_ticker')): r.get('현재가')
                       for r in preview if r.get('현재가')}
            _vrows, _vtot = portfolio.validate_portfolio(
                preview, market_prices=_mkt_px)
            st.session_state['paste_preview'] = _vrows
            preview = _vrows

            if _npx:
                st.caption(f"현재가 {_npx}종목을 실시간 시세로 채웠습니다 — "
                           f"수익률·평가손익은 이 현재가 기준입니다. "
                           f"화면에서 읽은 값은 별도로 보관해 평단가·수량 검증에 씁니다.")
            if _pxfail:
                st.caption("시세 조회 실패: " + ", ".join(_pxfail[:6]))

            # 실시간 시세 기준 평가 요약 — 원본 화면과 눈으로 대조할 수 있게
            _s_cost = sum((r.get('보유수량') or 0) * (r.get('평균매수가') or 0)
                          for r in preview)
            _s_val = sum((r.get('보유수량') or 0) * (r.get('현재가') or 0)
                         for r in preview if r.get('현재가'))
            if _s_cost > 0 and _s_val > 0:
                _s_pnl = _s_val - _s_cost
                _s_ret = (_s_val / _s_cost - 1.0) * 100.0
                _sc = "#35C98B" if _s_pnl >= 0 else "#ff453a"
                st.markdown(
                    f"<div style='background:#161D2A;"
                    f"border-radius:10px;padding:8px 16px;margin:8px 0;'>"
                    f"<b>실시간 평가 요약</b> — 매입 {_s_cost:,.0f}원 · "
                    f"평가 {_s_val:,.0f}원 · "
                    f"<b style='color:{_sc};'>손익 {_s_pnl:+,.0f}원 "
                    f"({_s_ret:+.2f}%)</b>"
                    f"<br><span style='color:#9DAABC;font-size:13px;'>"
                    f"원본 화면의 총 평가손익과 다르면 수량·평단가가 잘못 인식된 것입니다."
                    f"</span></div>", unsafe_allow_html=True)

            _c_ok, _c_warn, _c_err = _vtot['ok'], _vtot['warn'], _vtot['error']
            st.markdown(
                f"**검증 결과** — 전체 {_vtot['rows']}행 · "
                f"<span style='color:#35C98B;'>확실 {_c_ok}</span> · "
                f"<span style='color:#F2B84B;'>확인 필요 {_c_warn}</span> · "
                f"<span style='color:#ff453a;'>오류 가능 {_c_err}</span>",
                unsafe_allow_html=True)
            for _ck in _vtot['checks']:
                _cc = {'ok': '🟢', 'warn': '🟡', 'error': '🔴'}[_ck['level']]
                st.caption(f"{_cc} {_ck['name']} — {_ck['detail']}")
            if _vtot.get('worst_rows'):
                st.caption("오차 기여가 큰 행: " + ", ".join(
                    f"**{w['name']}** (표시 {w['shown']:,.0f} vs 계산 {w['derived']:,.0f})"
                    for w in _vtot['worst_rows']))
            if not _vtot['checks']:
                st.caption("현재가·수익률·평가손익 열이 없어 교차검증을 하지 못했습니다 — "
                           "그 열들이 보이도록 캡처하면 오독을 자동으로 잡아냅니다.")

            # 문제 행별 상세 + 후보 제시
            _bad = [r for r in preview if r['_validation']['severity'] != 'ok']
            if _bad:
                with st.expander(f"확인이 필요한 {len(_bad)}행 자세히 보기", expanded=True):
                    for _br in _bad:
                        _v = _br['_validation']
                        _col = '#ff453a' if _v['severity'] == 'error' else '#F2B84B'
                        st.markdown(
                            f"<b style='color:{_col};'>{_br.get('종목명')}</b> "
                            f"<span style='color:#9DAABC;font-size:13px;'>신뢰도 "
                            f"{_v['confidence']:.0f}%</span>", unsafe_allow_html=True)
                        for _c in _v['checks']:
                            if not _c['ok']:
                                st.caption(f"{_c['name']} — {_c['detail']}")
                        for _f, _cands in (_v['suggestions'] or {}).items():
                            _lbl = ["(그대로 두기)"] + [f"{c:,.0f}" for c in _cands]
                            _pick = st.selectbox(
                                f"　{_br.get('종목명')} · {_f} 후보",
                                _lbl, key=f"sg_{_br.get('종목코드')}_{_f}")
                            if _pick != "(그대로 두기)":
                                _br[_f] = float(_pick.replace(',', ''))
                                _br.pop('_validation', None)
                                st.session_state['paste_preview'] = preview
                                st.rerun()
                        if st.checkbox(f"　✓ {_br.get('종목명')} 확인함 (그대로 저장)",
                                       key=f"cf_{_br.get('종목코드')}_{_br.get('종목명')}"):
                            _br['_confirmed'] = True

            st.caption("셀을 눌러 바로 수정할 수 있습니다. 현재가·수익률·평가손익은 "
                       "**검증 전용**이며 저장되지 않습니다.")
            edited = st.data_editor(
                pd.DataFrame([{k: v for k, v in r.items()
                               if not k.startswith('_')} for r in preview]),
                num_rows="dynamic", width='stretch', key="paste_editor",
                column_config={
                    "보유수량": st.column_config.NumberColumn(format="%.0f"),
                    "평균매수가": st.column_config.NumberColumn(format="%.0f"),
                    "현재가": st.column_config.NumberColumn(format="%.0f", disabled=True),
                    "수익률": st.column_config.NumberColumn(format="%.2f", disabled=True),
                    "평가손익": st.column_config.NumberColumn(format="%.0f", disabled=True)})

            # 저장 가능 여부 (§20)
            _savable, _blocked = [], []
            _by_key = {(str(r.get('종목코드')), str(r.get('종목명'))): r for r in preview}
            for _rec in edited.to_dict('records'):
                _src = _by_key.get((str(_rec.get('종목코드')), str(_rec.get('종목명'))))
                _merged = dict(_rec)
                if _src:
                    _merged['_ticker'] = _src.get('_ticker')
                    _merged['_confirmed'] = _src.get('_confirmed')
                _ok, _why = portfolio.can_save_row(_merged)
                (_savable if _ok else _blocked).append((_merged, _why))

            if _blocked:
                st.warning(f"저장이 막힌 행 {len(_blocked)}건 — "
                           + ", ".join(f"{r.get('종목명')}({w})" for r, w in _blocked[:4]))

            pc1, pc2 = st.columns(2)
            if pc1.button(f"✅ 검증 통과 {len(_savable)}행 반영",
                          disabled=not _savable):
                # 사용자가 직접 넣은 종목코드는 시장(KOSPI/KOSDAQ)을 모른다.
                # KOSPI 로 넘겨짚으면 코스닥 종목의 시세 조회가 통째로 실패한다.
                def _resolve_mkt(code):
                    try:
                        t, _n = engine_init.resolve_symbol(code)
                        return "KOSDAQ" if str(t or "").endswith(".KQ") else "KOSPI"
                    except Exception:
                        return "KOSPI"
                pos, warns = portfolio.rows_to_positions(
                    [r for r, _ in _savable], resolve_market=_resolve_mkt)
                st.session_state['positions'] = pos
                st.session_state.pop('paste_preview', None)
                # 로컬에서만 파일로 저장한다. 원격에서는 `.portfolio/positions.json` 이
                # 방문자 전원의 공용 파일이 되어 서로의 보유종목을 덮어쓴다.
                if ALLOW_LOCAL_STORE:
                    try:
                        portfolio.save_positions(pos)
                        st.session_state['positions_saved_at'] = \
                            datetime.datetime.now().isoformat(timespec="seconds")
                        st.success(f"{len(pos)}종목 반영·저장")
                    except Exception as _ex:
                        st.success(f"{len(pos)}종목 반영")
                        st.warning(f"로컬 저장 실패: {_ex}")
                else:
                    st.success(f"{len(pos)}종목 반영 (이 브라우저 세션에만 유지)")
                    st.caption("원격 접속이라 서버에 저장하지 않습니다. 보관하려면 "
                               "**저장·삭제 탭 → CSV 내보내기**를 쓰세요.")
                for w in warns:
                    st.warning(w)
                st.rerun()
            if pc2.button("✖ 미리보기 취소"):
                st.session_state.pop('paste_preview', None)
                st.rerun()

        _uk.spacer(28)
        st.markdown("표에서 직접 편집")
        st.caption("행을 추가·수정·삭제한 뒤 '저장'을 누르세요. 종목코드 6자리와 수량·평단가만 있으면 됩니다.")
        cur_rows = portfolio.positions_to_rows(st.session_state.get('positions') or [])
        editor_df = pd.DataFrame(cur_rows) if cur_rows else pd.DataFrame(
            columns=["종목코드", "종목명", "보유수량", "평균매수가", "_ticker"])
        edited_direct = st.data_editor(
            editor_df, num_rows="dynamic", width='stretch', key="direct_editor",
            column_config={"_ticker": None,
                           "보유수량": st.column_config.NumberColumn(format="%.0f"),
                           "평균매수가": st.column_config.NumberColumn(format="%.0f")})
        if st.button("편집 내용 반영"):
            pos, warns = portfolio.rows_to_positions(
                edited_direct.to_dict('records'), source_type="manual_entry")
            st.session_state['positions'] = pos
            if ALLOW_LOCAL_STORE:
                try:
                    portfolio.save_positions(pos)
                    st.session_state['positions_saved_at'] = \
                        datetime.datetime.now().isoformat(timespec="seconds")
                    st.success(f"{len(pos)}종목 반영·저장")
                except Exception as _ex:
                    st.success(f"{len(pos)}종목 반영")
                    st.warning(f"로컬 저장 실패: {_ex}")
            else:
                st.success(f"{len(pos)}종목 반영 (이 브라우저 세션에만 유지)")
            for w in warns:
                st.warning(w)
            st.rerun()

    # ── 저장 / 삭제 ────────────────────────────────────────────────────
    with p_tab_manage:
        if ALLOW_LOCAL_STORE:
            st.markdown("보유 정보는 **이 PC의 `.portfolio/positions.json`** 에만 저장됩니다. "
                        "서버 전송·외부 API 전달을 하지 않으며, 계좌번호는 마스킹되어 저장됩니다.")
            mg1, mg2, mg3 = st.columns(3)
            if mg1.button("💾 로컬 저장"):
                path = portfolio.save_positions(st.session_state['positions'])
                st.session_state['positions_saved_at'] = datetime.datetime.now().isoformat(timespec="seconds")
                st.success(f"저장 완료: {path}")
            if mg2.button("📂 저장본 불러오기"):
                loaded, saved_at = portfolio.load_positions()
                st.session_state['positions'] = loaded
                st.session_state['positions_saved_at'] = saved_at
                st.success(f"{len(loaded)}종목 불러옴 (저장 시각 {saved_at})")
            if mg3.button("🗑️ 전체 삭제", type="secondary"):
                portfolio.delete_positions()
                st.session_state['positions'] = []
                st.session_state['positions_saved_at'] = None
                st.success("삭제 완료")
        else:
            # 원격에서는 서버 파일에 쓰지 않는다 — 앱 인스턴스가 하나라 방문자
            # 전원의 공용 파일이 되어 서로의 보유종목을 덮어쓴다.
            st.info("**원격 접속 — 보유종목은 이 브라우저 세션에만 유지됩니다.**\n\n"
                    "서버에 저장하지 않으므로 다른 접속자와 자료가 섞이지 않습니다. "
                    "탭을 닫거나 앱이 재시작되면 사라지니, 보관하려면 아래 "
                    "**CSV 내보내기**로 받아 두었다가 다음에 "
                    "'가져오기 / 입력' 탭에서 다시 올리세요.")
            if st.button("이 세션 보유종목 지우기", type="secondary"):
                st.session_state['positions'] = []
                st.session_state['positions_saved_at'] = None
                st.success("삭제 완료")
        if st.session_state['positions']:
            st.download_button("⬇️ CSV 내보내기",
                               portfolio.export_positions_csv(st.session_state['positions']),
                               file_name="portfolio.csv", mime="text/csv")
            st.caption("LLM·외부 전송 시 사용하는 익명화 뷰 (수량·평단가 제외): "
                       + str(portfolio.anonymize_for_llm(st.session_state['positions'])))

    # ── 포트폴리오 분석 ────────────────────────────────────────────────
    with p_tab_view:
        positions = st.session_state.get('positions') or []
        if not positions:
            st.info("등록된 보유종목이 없습니다. '가져오기 / 입력' 탭에서 추가하세요.")
        else:
            merged = portfolio.merge_duplicate_positions(positions)
            with st.spinner(f"보유 {len(merged)}종목 정밀 분석 중..."):
                rows, snaps = [], {}
                for m in merged:
                    try:
                        s, _org = get_shared_snapshot(m['ticker'], t_ref_str, rho_cutoff)
                    except Exception as ex:
                        rows.append({"종목": m['stock_name'], "오류": str(ex)[:60]})
                        continue
                    snaps[m['ticker']] = (m, s)

                total_cost = sum(m['quantity'] * m['average_buy_price'] for m, _ in snaps.values())
                port_rows = []
                for ticker, (m, s) in snaps.items():
                    px = float(s['tech_df']['adj_close'].iloc[-1])
                    w = (m['quantity'] * m['average_buy_price'] / total_cost * 100) if total_cost else None
                    pv = q_engine.personalize_for_position(
                        s, m['average_buy_price'], m['quantity'], portfolio_weight_pct=w)
                    hzd = s['sim_res'].get('horizons_data') or {}

                    def _cell(H):
                        h = hzd.get(H)
                        if not h or h.get('status') == 'INSUFFICIENT':
                            return "미산출"
                        tier = h['tier_label'].split('(')[0].strip()
                        return f"{fmt_pct(h['median_perf'])} · {tier} · ESS {h.get('ess', 0):.0f}"

                    port_rows.append({
                        "종목": m['stock_name'],
                        "평단가": f"{m['average_buy_price']:,.0f}",
                        "현재가": f"{px:,.0f}",
                        "수익률": fmt_pct(pv['unrealized_return_pct']),
                        "5일": _cell(5), "10일": _cell(10), "20일": _cell(20),
                        "40일": _cell(40), "60일": _cell(60), "120일": _cell(120),
                        "최적기간": s['sim_res'].get('optimal_holding_period_str', '미선정'),
                        "신규 진입": pv['new_entry_title'],
                        "보유자 의견": pv['holder_action_title'],
                    })
                    m['_pv'], m['_snap'], m['_px'] = pv, s, px

                total_value = sum(m['quantity'] * m['_px'] for m, _ in snaps.values() if '_px' in m)
                t1, t2, t3, t4, t5 = st.columns(5)
                t1.metric("총 매입금액", f"{total_cost:,.0f}원")
                t2.metric("총 평가금액", f"{total_value:,.0f}원")
                t3.metric("총 평가손익", f"{total_value - total_cost:+,.0f}원")
                t4.metric("총 수익률", fmt_pct((total_value / total_cost - 1) * 100 if total_cost else None))
                t5.metric("보유 종목 수", f"{len(snaps)}종목")

                weights = sorted(((m['quantity'] * m['average_buy_price'] / total_cost * 100)
                                  for m, _ in snaps.values()), reverse=True) if total_cost else []
                if weights:
                    st.caption(f"상위 3개 집중도 **{sum(weights[:3]):.1f}%** · "
                               f"최대 단일종목 비중 **{weights[0]:.1f}%**")

                st.markdown("포트폴리오 전체 요약 (기간별: 중앙 예상수익률 · 예측등급 · ESS)")
                st.dataframe(pd.DataFrame(port_rows), width='stretch', hide_index=True)

                st.markdown("종목별 상세")
                for ticker, (m, s) in snaps.items():
                    pv = m['_pv']
                    with st.expander(f"{m['stock_name']} — 보유자: **{pv['holder_action_title']}** / "
                                     f"신규: {pv['new_entry_title']} / 수익률 {fmt_pct(pv['unrealized_return_pct'])}"):
                        c1, c2, c3, c4 = st.columns(4)
                        c1.metric("평균 매수가", f"{pv['average_buy_price']:,.0f}원")
                        c2.metric("현재가", f"{m['_px']:,.0f}원")
                        c3.metric("평가손익", f"{pv['unrealized_profit']:+,.0f}원", fmt_pct(pv['unrealized_return_pct']))
                        if (pv['unrealized_return_pct'] or 0) < 0:
                            c4.metric("본전까지 필요 상승률", fmt_pct(pv['recovery_required_pct']),
                                      "손실률의 반대값이 아님")
                        else:
                            c4.metric("1차 목표까지", fmt_pct(pv['distance_to_target_pct']))

                        d1, d2, d3 = st.columns(3)
                        d1.metric("보유자 행동점수", f"{pv['holder_action_score']}점", pv['holder_action_title'])
                        d2.metric("신규 진입 점수", f"{pv['new_entry_score']}점", pv['new_entry_title'])
                        d3.metric("포트폴리오 비중", fmt_pct(pv['portfolio_weight_pct'], signed=False))

                        st.markdown("**보유자 행동점수 구성**")
                        st.dataframe(pd.DataFrame(
                            [{"구성요소": k, "점수": v} for k, v in pv['components'].items()]),
                            width='stretch', hide_index=True)

                        st.markdown("**추가매수(물타기) 허용 조건** — 전부 통과해야 허용")
                        for label, ok in pv['averaging_down_checks']:
                            st.markdown(f"- {'✅' if ok else '❌'} {label}")
                        if not pv['averaging_down_allowed']:
                            st.warning("추가매수 조건을 충족하지 못했습니다. 손실 중이라는 이유만으로 "
                                       "기계적 물타기를 권하지 않습니다.")

                        if m.get('is_multi_account'):
                            st.caption("복수 계좌 보유 — 계좌별 내역")
                            st.dataframe(pd.DataFrame(m['accounts']),
                                         width='stretch', hide_index=True)
    _uk.spacer(28)

# ── 캘리브레이션 산출물 로더 — 홈 카드·판정 캡션·모델 성과 섹션이 공유 ──────
# rerun 마다 엔진이 새로 만들어져 속성이 비므로, 파일을 직접 읽어 캐시한다.
# 경로: .portfolio/ (로컬 최신) 우선, 없으면 data/ (저장소 동봉 — 클라우드 배포용).
def _artifact_path(fname):
    _base = os.path.dirname(os.path.abspath(__file__))
    for _d in (".portfolio", "data"):
        _p = os.path.join(_base, _d, fname)
        if os.path.exists(_p):
            return _p
    return None


@st.cache_data(ttl=600, show_spinner=False)
def _load_calibration_meta():
    try:
        import json as _json_cal
        _p = _artifact_path("calibration.json")
        if not _p:
            return {}
        with open(_p, encoding='utf-8') as _f:
            return _json_cal.load(_f)
    except Exception:
        return {}


@st.cache_data(ttl=600, show_spinner=False)
def _load_case_ledger():
    """가상 백테스트 원장 — 케이스 스터디 화면 전용. 없으면 None."""
    try:
        _p = _artifact_path("virtual_graded.jsonl")
        if not _p:
            return None
        _df = pd.read_json(_p, lines=True)
        return _df if len(_df) else None
    except Exception:
        return None


@st.cache_data(ttl=600, show_spinner=False)
def _load_update_history():
    try:
        import json as _json_uh
        _p = _artifact_path("update_history.json")
        if not _p:
            return None
        with open(_p, encoding='utf-8') as _f:
            return _json_uh.load(_f)
    except Exception:
        return None


# ── 홈 1순위: 모델 상태 (사용자 요청 — 화면 최상단 고정, 전부 실측·n 병기) ──
# 이 판정을 얼마나 믿을 수 있는지가 첫 화면의 첫 정보다.
_home_cal = _load_calibration_meta()
if _home_cal.get('total_cases'):
    _sp = _home_cal.get('splits') or {}
    _bz = (_sp.get('buy_zone') or {})
    _v, _b, _bzb = _sp.get('valid') or {}, _sp.get('blind') or {}, _bz.get('blind') or {}
    # 대표 지표는 '실제로 추천한 것' 기준 — 전체 사례에는 우리가 애초에
    # 추천하지 않는 사례가 다 들어 있어 구독자가 받는 성적과 다르다.
    _bzv, _bzb2 = _bz.get('valid') or {}, _bz.get('blind') or {}
    _sig = _home_cal.get('signal_frequency') or {}
    # UI 킷 타일 — 한 카드 안에서 헤어라인으로 나눈다 (테두리 없음)
    _uk.section("이 판단, 얼마나 믿을 수 있나",
                "과거로 되돌려 실제로 맞았는지 세어 본 결과입니다", theme=_theme, top=8)
    _uk.stat_tiles([
        {'label': '되돌려 본 판단',
         'value': f"{_home_cal['total_cases']:,}",
         'sub': f"모델 {_VER_NOW['model']}"},
        {'label': '60점+ 신호 연습 적중률',
         'value': (f"{_bzv['hit_rate']:.1f}%"
                   if _bzv.get('hit_rate') is not None else "미산출"),
         'sub': f"매수 신호 {_bzv.get('n', 0):,}건 중"},
        # '추천만 골랐을 때' 타일은 이 타일과 **같은 값**(buy_zone·blind)을
        # 읽고 있었다. 같은 측정이 두 번 서 있으면 두 번 확인된 것처럼
        # 읽힌다 — 표본 부족 경고만 이 타일로 합치고 중복은 지운다.
        {'label': '60점+ 신호 실전 적중률',
         'value': (f"{_bzb2['hit_rate']:.1f}%"
                   if _bzb2.get('hit_rate') is not None else "미산출"),
         'sub': (f"안 본 기간 {_bzb2.get('n', 0):,}건 중 · 표본 부족"
                 if (_bzb2.get('n') or 0) < 30
                 else f"안 본 기간 {_bzb2.get('n', 0):,}건 중"),
         'tone': 'warn' if (_bzb2.get('n') or 0) < 30 else ''},
        {'label': '매수 기회',
         'value': (f"{_sig['rate_pct']:.1f}%" if _sig.get('rate_pct') is not None
                   else "미산출"),
         'sub': f"{_sig.get('buy_zone', 0)}/{_sig.get('total', 0):,}건"},
    ], theme=_theme)
    _uk.note(
        # 위 타일은 60점+, 아래 국면 표는 58점+ 다. 둘 다 '추천'이라고
        # 부르면 사용자는 같은 집단으로 읽는다 — 문턱을 밝혀서 가른다.
        f"위 두 적중률은 **점수 60점 이상**만 센 것입니다 — 가장 좁게 잡은 "
        f"기준이라 표본이 작습니다. 아래 국면별 표는 **58점 이상**이라 "
        f"표본이 더 크고, 그래서 두 표의 숫자는 서로 다릅니다. "
        f"참고로 점수와 무관하게 전체 사례를 다 센 적중률은 연습 "
        f"{_v.get('hit_rate', 0):.1f}% ({_v.get('n', 0):,}건) · 실전 "
        f"{_b.get('hit_rate', 0):.1f}% ({_b.get('n', 0):,}건)입니다. "
        f"미래 수익을 보장하지 않습니다.",
        theme=_theme)

    # ── 국면별 성적 (라운드 7 실측) ────────────────────────────────────
    # 평균 한 줄은 사용자가 오늘 자기 상황에 적용할 수 없다. 적중률을
    # 지배하는 것은 점수가 아니라 시장 국면이라는 것이 실측으로 확인됐다
    # (docs/MODEL_VERSIONS.md 라운드 4~7). 그래서 나눠서 보여 준다.
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               '.portfolio', 'regime_breakdown.json'),
                  encoding='utf-8') as _rf:
            _rb = json.load(_rf)
    except Exception:
        _rb = None
    # ── 전날 미국장 경고 (라운드 16) ────────────────────────────────
    # 사용자 직관("미장 영향 많이 받는다")은 맞았는데 방향이 반대였다.
    # 급락한 다음날이 아니라 **보합인 다음날**이 나쁘다 — 미국이 방향을
    # 정하지 못하면 한국은 방향 없이 흔들린다.
    # 게이트로 막지는 않는다(신호가 절반으로 줄어 사전등록 미달). 대신 알린다.
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               '.portfolio', 'us_overnight.json'),
                  encoding='utf-8') as _uf:
            _uo = json.load(_uf)
    except Exception:
        _uo = None
    _sp_pct = None
    try:
        _sp_raw = str((m_indices.get('sp500') or {}).get('pct') or '')
        _sp_pct = float(_sp_raw.replace('%', '').replace('+', '').strip())
        if _sp_raw.strip().startswith('-'):
            _sp_pct = -abs(_sp_pct)
    except Exception:
        _sp_pct = None
    if _uo and _sp_pct is not None:
        _bko = ('급락 (−2%↓)' if _sp_pct < -2 else
                '하락 (−2~−0.5%)' if _sp_pct < -0.5 else
                '보합 (±0.5%)' if _sp_pct < 0.5 else
                '상승 (+0.5~+2%)' if _sp_pct < 2 else '급등 (+2%↑)')
        _bs = ((_uo.get('bands') or {}).get(_bko) or {})
        _bbl = _bs.get('blind') or _bs.get('valid') or {}
        _uk.spacer(20)
        if _bko == '보합 (±0.5%)':
            _uk.card(
                f"<p style='margin:0 0 8px 0; font-size:15px; font-weight:600; "
                f"color:{_TOK['tx1']};'>어젯밤 미국장이 보합이었습니다 "
                f"({_sp_pct:+.2f}%) — 오늘은 특히 조심하세요</p>"
                f"<p style='margin:0; font-size:13px; line-height:1.7; "
                f"color:{_TOK['tx2']};'>과거 실측에서 <b>전날 미국장이 보합인 "
                f"날의 추천 성적이 가장 나빴습니다</b> — 실전 적중 "
                f"{_bbl.get('hit', 0):.0f}% · 비용 차감 후 "
                f"{_bbl.get('ev', 0):+.2f}% (n={_bbl.get('n', 0)}). "
                f"미국이 방향을 정하지 못하면 한국은 방향 없이 흔들립니다. "
                f"오늘 나오는 매수 결론은 평소보다 낮게 보시는 편이 안전합니다.</p>",
                theme=_theme, accent='warn')
        else:
            _uk.card(
                f"<p style='margin:0 0 6px 0; font-size:13px; "
                f"color:{_TOK['tx3']};'>어젯밤 미국장</p>"
                f"<p style='margin:0; font-size:15px; line-height:1.7; "
                f"color:{_TOK['tx1']};'>S&amp;P 500 <b>{_sp_pct:+.2f}%</b> · "
                f"{_bko}</p>"
                + (f"<p style='margin:6px 0 0 0; font-size:13px; "
                   f"color:{_TOK['tx2']};'>같은 구간의 과거 추천 성적: "
                   f"적중 {_bbl.get('hit', 0):.0f}% · 비용 차감 후 "
                   f"{_bbl.get('ev', 0):+.2f}% (n={_bbl.get('n', 0)})</p>"
                   if _bbl.get('n') else
                   f"<p style='margin:6px 0 0 0; font-size:13px; "
                   f"color:{_TOK['tx3']};'>이 구간은 과거 표본이 적어 성적을 "
                   f"말하지 않습니다.</p>"),
                theme=_theme)

    if _rb and _rb.get('cells6') and _rb.get('mode') == '6':
        # 국면을 변동성으로 쪼갠 6칸 (라운드 14). 같은 판단을 더 정확한
        # 이름으로 묶으니 연습-실전 격차가 31.8%p → 6.5%p 로 줄었다.
        # 지수가 옆으로 가는 것과 개별 종목이 조용한 것은 다른 이야기다.
        _uk.spacer(20)
        _rows_rg = []
        _RG_ORDER = [('BULL', 'calm'), ('BULL', 'rough'),
                     ('SIDEWAYS', 'calm'), ('SIDEWAYS', 'rough'),
                     ('BEAR', 'calm'), ('BEAR', 'rough')]
        for _rg, _vb in _RG_ORDER:
            _c = (_rb['cells6'].get(f'{_rg}|{_vb}') or {})
            _v, _b2 = _c.get('valid') or {}, _c.get('blind') or {}
            if not (_v.get('n') or _b2.get('n')):
                continue
            _ko = (f"{_rb['vol_ko'].get(_vb, _vb)} "
                   f"{_rb['regime_ko'].get(_rg, _rg)}")
            _thin = ((_v.get('n') or 0) < 30 or (_b2.get('n') or 0) < 30)

            def _fmt(_m):
                if not _m or _m.get('hit') is None:
                    return '표본 없음'
                if (_m.get('n') or 0) >= 30:
                    return f"{_m['hit']:.0f}%"
                return f"{_m.get('ci_low', 0):.0f}~{_m.get('ci_high', 0):.0f}%"

            _rows_rg.append((
                _ko,
                f"연습 {_fmt(_v)} (n={_v.get('n', 0)}) · "
                f"실전 {_fmt(_b2)} (n={_b2.get('n', 0)})",
                'warn' if _thin else ''))
        if _rows_rg:
            # 지금이 어느 칸인지 — 표만 보여 주면 사용자가 자기 상황을 못 찾는다
            _now_basis = ''
            try:
                _ir = bitemporal_engine.BitemporalEngine().get_index_regime('KOSPI')
                _gi_mkt_label = ('하락' if (_ir.get('price') and _ir.get('sma60')
                                          and _ir['price'] < _ir['sma60'])
                                 else '상승' if (_ir.get('price') and _ir.get('sma20')
                                               and _ir['price'] > _ir['sma20'])
                                 else '옆걸음')
                # 위 시장 타일은 **하루** 등락이고 국면은 **60일 추세**다.
                # 근거를 안 적으면 '+17% 인데 하락 국면?' 으로 읽혀 화면이
                # 앞뒤가 안 맞는 말을 하는 것처럼 보인다.
                _pp, _s20, _s60 = (_ir.get('price'), _ir.get('sma20'),
                                   _ir.get('sma60'))
                if _pp and _s60:
                    _ref, _refko = ((_s60, '60일 평균') if _gi_mkt_label == '하락'
                                    else (_s20, '20일 평균') if _s20 else
                                    (_s60, '60일 평균'))
                    _gapp = (_pp / _ref - 1) * 100
                    _now_basis = (
                        f"코스피가 {_refko}보다 {abs(_gapp):.1f}% "
                        f"{'아래' if _gapp < 0 else '위'}에 있습니다 — "
                        f"하루 등락이 아니라 60일 추세로 봅니다. ")
            except Exception:
                _gi_mkt_label = ''
            _now_rg = ('BEAR' if '하락' in str(_gi_mkt_label)
                       else 'BULL' if ('상승' in str(_gi_mkt_label)
                                       or '과열' in str(_gi_mkt_label))
                       else 'SIDEWAYS' if _gi_mkt_label else '')
            if _now_rg:
                _now_ko = _rb['regime_ko'].get(_now_rg, '')
                _uk.card(
                    f"<p style='margin:0; font-size:15px; line-height:1.7; "
                    f"color:{_TOK['tx1']};'>지금은 <b>{_now_ko}</b> 국면입니다. "
                    f"{_now_basis}"
                    # 표의 행 이름은 '차분한 하락'·'거친 하락' 처럼 국면이
                    # 뒤에 온다. '~로 시작하는' 은 표와 맞지 않는 안내였다.
                    f"아래 표에서 <b>차분한 {_now_ko}</b> · <b>거친 {_now_ko}</b> "
                    f"두 줄이 지금 상황의 성적입니다 — 같은 {_now_ko} 장이라도 "
                    f"종목이 얼마나 흔들리느냐에 따라 성적이 다릅니다."
                    f"</p>", theme=_theme, accent='brand')
                _uk.spacer(12)
            _uk.rows(_rows_rg, theme=_theme,
                     title='시장 국면별 성적 (58점+ 신호) — 지수 방향 × 종목 변동성')
            _uk.note(
                f"국면을 지수 방향(상승·옆걸음·하락)만이 아니라 **종목 변동성**"
                f"으로도 나눴습니다. 같은 '옆걸음'이라도 하루 2%씩 움직이는 장과 "
                f"5%씩 흔들리는 장은 전혀 다른 시장인데, 그동안 한 칸에 묶여 "
                f"있었습니다. 나누고 나니 연습과 실전의 차이가 "
                f"{_rb.get('gap3', 0):.0f}%p에서 {_rb.get('gap6', 0):.0f}%p로 "
                f"줄었습니다 — 모델이 갑자기 좋아진 게 아니라, 그동안 서로 다른 "
                f"시장을 비교하고 있었던 것입니다. 주황색은 표본 30건 미만이라 "
                f"하나의 숫자 대신 95% 신뢰구간을 보여 드립니다.",
                theme=_theme)
    elif _rb and _rb.get('buy_zone'):
        _rows_rg = []
        for _rg, _ko in (('BULL', '상승 추세'), ('SIDEWAYS', '옆걸음(횡보)'),
                         ('BEAR', '하락 추세')):
            _bv = (_rb['buy_zone'].get('valid') or {}).get(_rg) or {}
            _bb2 = (_rb['buy_zone'].get('blind') or {}).get(_rg) or {}
            if not (_bv or _bb2):
                continue
            def _ci(_m):
                """표본이 적으면 숫자 대신 범위를 보여 준다 — n=16 의 12% 는
                성적이 아니라 잡음이다. 범위를 숨기면 사용자가 그걸 성적으로
                읽는다."""
                _n = _m.get('n') or 0
                if not _n or _m.get('hit') is None:
                    return None
                if _n >= 30:
                    return f"{_m['hit']:.0f}%"
                _p = float(_m['hit']) / 100.0
                _z = 1.96
                _d = 1 + _z * _z / _n
                _c = _p + _z * _z / (2 * _n)
                _mg = _z * ((_p * (1 - _p) / _n
                             + _z * _z / (4 * _n * _n)) ** 0.5)
                return (f"{100 * (_c - _mg) / _d:.0f}~"
                        f"{100 * (_c + _mg) / _d:.0f}%")

            _vv, _bb3 = _ci(_bv), _ci(_bb2)
            _vtxt = (f"연습 {_vv} (n={_bv['n']})" if _vv else '연습 표본 없음')
            _btxt = (f"실전 {_bb3} (n={_bb2['n']})" if _bb3 else '실전 표본 없음')
            # 표본이 30건 미만이면 수치를 강조하지 않는다 (우연일 수 있다)
            _thin = ((_bv.get('n') or 0) < 30 or (_bb2.get('n') or 0) < 30)
            _rows_rg.append((_ko, f"{_vtxt} · {_btxt}",
                             'warn' if _thin else ''))
        if _rows_rg:
            _uk.spacer(20)
            _uk.rows(_rows_rg, theme=_theme,
                     title='시장 국면별 성적 (58점+ 신호) — 같은 모델도 장세에 따라 다릅니다')
            _uk.note(
                "주황색은 표본 30건 미만이라 성적으로 인정하지 않는 구간이며, "
                "하나의 숫자 대신 **95% 신뢰구간**을 보여 드립니다. 예를 들어 "
                "16건에서 2번 맞았다면 참값은 3%일 수도 36%일 수도 있습니다 — "
                "그건 성적이 아니라 잡음입니다. 특히 하락 추세는 연습과 실전이 "
                "크게 엇갈리므로 이 국면의 판단은 신뢰하지 마세요.",
                theme=_theme)

# 개장 전 한 줄 결론 (리포트가 있을 때만 — 없으면 만들지 않는다)
try:
    import premarket as _pm_home
    _pm_today = st.session_state.get('premarket_report') or _pm_home.load_today_report()
except Exception:
    _pm_today = None
if _pm_today and _pm_today.get('picks'):
    _cls_cnt = {}
    for _pk in _pm_today['picks']:
        _cls_cnt[_pk.get('reco_class', '?')] = _cls_cnt.get(_pk.get('reco_class', '?'), 0) + 1
    _buyable = _cls_cnt.get('오늘 사도 되는 종목', 0) + _cls_cnt.get('조건부로 사도 되는 종목', 0)
    _oneline = ("오늘은 매수 후보가 있습니다 — 아래 '오늘의 추천'에서 조건을 확인하세요."
                if _buyable else
                "오늘은 공격적 매수보다 관망·눌림목 확인이 유리합니다 — 매수 후보가 없습니다.")
    st.info(f"**개장 전 한 줄 결론** · {_oneline}  \n"
            + " · ".join(f"{k} **{v}**" for k, v in _cls_cnt.items())
            + f"  ·  기준 데이터 {_pm_today.get('data_asof')} (전일 확정)")

m_indices = engine_init.get_market_indices()

# ── 주요 이슈 (v4) — 지금 꼭 봐야 할 것: 요약 3건 + 전체 보기. 실경고에서만 생성 ──
import product_ops as _pops

_gi_calib = _load_calibration_meta()
_gi_mkt = {'index_missing': (m_indices['kospi']['price'] == 'N/A'
                             or m_indices['kosdaq']['price'] == 'N/A')}
_issues_global = _pops.build_global_issues(_gi_calib, _gi_mkt)
# 배지 색도 토큰에서만 온다 — 라이트에서 자기 틴트 위 대비가 무너졌었다
_SEV_BADGE = {'높음': (_TOK['neg'], '높음'), '중간': (_TOK['warn'], '중간'),
              '낮음': (_TOK['tx2'], '낮음')}
if _issues_global:
    # 토글형 (v5) — 접힌 상태에서도 건수·최상위 이슈가 제목에 보인다
    with st.expander(f"주요 이슈 {len(_issues_global)}건 — "
                     f"{_issues_global[0]['title']}", expanded=False):
        # ── 조치 관리 (경고만 띄우지 않는다) ─────────────────────────
        # 각 이슈의 원인·영향·조치·예정일·상태를 함께 보여준다.
        # 3일 넘게 방치되면 성격이 자동 재분류되므로 같은 경고가 설명 없이
        # 반복되지 않는다.
        try:
            from improvement import issue_ops as _iops
            from improvement.database import get_connection as _icx
            _ic2 = _icx()
            try:
                _iops.ensure_schema(_ic2)
                _tracked = [r for r in _iops.issue_view(_ic2, 12)
                            if r.get('cause')]
            finally:
                _ic2.close()
        except Exception:
            _tracked = []
        if _tracked:
            _ST_TONE = {'해결 완료': 'pos', '검증 중': 'brand', '수정 중': 'warn',
                        '확인 중': 'warn', '즉시 수정 불가': 'tx2',
                        '장기 개선 과제': 'tx2'}
            for _tr in _tracked:
                _ws = _tr.get('work_status') or '확인 중'
                _tone = _uk.tokens(_theme).get(_ST_TONE.get(_ws, 'tx2'))
                _fix = ('즉시 수정 가능' if _tr.get('fixable_now')
                        else '지금은 즉시 해결 불가')
                st.markdown(
                    f"<div style='background:{_TOK['surface']}; "
                    f"border-radius:14px; padding:16px 20px; margin-bottom:8px;'>"
                    f"<span style='background:{_TOK['hover']}; "
                    f"color:{_TOK['tx1']}; font-size:12px; font-weight:600; "
                    f"padding:2px 8px; border-radius:6px; display:inline-flex; "
                    f"align-items:center; gap:6px;'>"
                    f"<span style='width:6px; height:6px; border-radius:50%; "
                    f"background:{_tone};'></span>{_ws}</span>"
                    f"<span style='margin-left:8px; font-size:12px; "
                    f"color:{_TOK['tx2']};'>{_tr.get('age_days', 0)}일 경과 · "
                    f"{_fix} · 다음 점검 {_tr.get('next_review') or _tr.get('eta') or '—'}</span>"
                    f"<p style='margin:8px 0 4px 0; font-size:15px; "
                    f"font-weight:600; color:{_TOK['tx1']};'>{_tr['title']}</p>"
                    f"<p style='margin:0; font-size:13px; color:{_TOK['tx2']}; "
                    f"line-height:1.6;'><b>왜 생겼나</b> {_tr.get('cause','')}<br>"
                    f"<b>영향</b> {_tr.get('user_impact','')}<br>"
                    f"<b>지금 하는 일</b> {_tr.get('action_plan','')}<br>"
                    f"<b>임시 안전조치</b> {_tr.get('safeguard','')}<br>"
                    f"<b>목표</b> {_tr.get('target','')}"
                    + (f"<br><b>담당</b> <span style='color:{_TOK['tx3']};'>"
                       f"{_tr.get('module','')}</span>" if _tr.get('module') else '')
                    + "</p></div>", unsafe_allow_html=True)
            st.caption("이슈는 3일 넘게 조치 없이 같은 경고만 반복되지 않도록 "
                       "경과일에 따라 자동으로 재분류됩니다. 표본 축적처럼 물리적으로 "
                       "빨리 해결할 수 없는 항목은 억지로 해결 처리하지 않고 "
                       "안전조치와 재평가 시점을 명시합니다.")
            _uk.spacer(28)
        st.caption("아래는 실측에서 자동 감지된 원본 경고입니다.")
        for _is in _issues_global[:3]:
            _bc, _bt = _SEV_BADGE.get(_is['severity'], ('#9DAABC', '—'))
            st.markdown(
                f"<div style='background:{_TOK['surface']}; border-left:3px solid "
                f"{_bc if _is['severity'] == '높음' else 'transparent'}; "
                f"border-radius:12px; padding:12px 16px; margin-bottom:8px;'>"
                f"<span style='background:{_TOK['hover']}; color:{_bc}; font-size:12px; "
                f"font-weight:700; padding:2px 8px; border-radius:6px;'>{_bt}</span> "
                f"<span style='background:{_TOK['hover']}; color:{_TOK['tx2']}; "
                f"font-size:12px; font-weight:700; padding:2px 8px; border-radius:6px;'>"
                f"{_is['type']}</span> "
                f"<b style='font-size:15px; color:{_TOK['tx1']};'> {_is['title']}</b>"
                f"<p style='margin:4px 0 0 0; font-size:13px; color:{_TOK['tx2']};'>"
                f"{_is['detail']}</p></div>", unsafe_allow_html=True)
        if len(_issues_global) > 3:
            st.markdown("**전체 이슈**")
            st.dataframe(pd.DataFrame([{
                '중요도': i['severity'], '유형': i['type'], '제목': i['title'],
                '내용': i['detail'], '범위': i['scope'], '생성': i['created'],
            } for i in _issues_global]), width='stretch', hide_index=True)

# ── 최근 업데이트 (v4) — 제품형 릴리스 노트: 요약 5건 + 전체 보기·필터 ────────
_uh_home = _load_update_history()
if _uh_home and _uh_home.get('days'):
    _days_enr = _pops.enrich_update_history(_uh_home)
    _flat_upd = [{**it, 'date': d['date'], 'version': d['version']}
                 for d in _days_enr for it in d['items']]
    _n_upd = len(_flat_upd)
    _latest_ver = _VER_NOW['model']       # 버전 원장이 유일 출처
    st.markdown("<div id='nav-updates'></div>", unsafe_allow_html=True)
    # 사용자 요청: 눌러야 나오게, 아주 간략하게. 평소엔 한 줄만 보인다.
    with st.expander(f"업데이트 {_n_upd}건 · {_latest_ver}", expanded=False):
        st.caption("커밋 이력 원문에서 자동 생성 — 손으로 쓰지 않습니다.")

        # 아주 간략하게 — 한 줄씩. 자세한 건 아래 '전체 업데이트 보기'.
        for _u in _flat_upd[:8]:
            st.markdown(
                f"<div style='display:flex; gap:10px; align-items:baseline; "
                f"padding:6px 0;'>"
                f"<span style='font-size:12px; color:{_TOK['tx3']}; "
                f"width:78px; flex:0 0 auto; "
                f"font-variant-numeric:tabular-nums;'>{_u['date']}</span>"
                f"<span style='font-size:12px; color:{_TOK['tx3']}; "
                f"width:56px; flex:0 0 auto;'>{_u['category']}</span>"
                f"<span style='font-size:13px; color:{_TOK['tx1']}; "
                f"min-width:0; overflow:hidden; text-overflow:ellipsis; "
                f"white-space:nowrap;'>{_uk._esc(_u['subject'])}</span></div>",
                unsafe_allow_html=True)

    
    with st.expander(f"전체 업데이트 보기 ({_n_upd}건 · 카테고리 필터)",
                     expanded=False):
        _cats = ['전체'] + sorted({u['category'] for u in _flat_upd})
        _f_cat = st.selectbox("카테고리", _cats, key="upd_cat_filter")
        _sel_upd = [u for u in _flat_upd
                    if _f_cat == '전체' or u['category'] == _f_cat]
        st.caption("각 줄을 펼치면 왜 바꿨는지·무엇이 달라지는지·어떻게 확인했는지가 "
                   "나옵니다. 커밋 기록에 없는 항목은 '기록 없음'으로 둡니다 "
                   "(보기 좋게 지어내지 않습니다).")
        for _u in _sel_upd[:40]:
            _dt_u = _u.get('detail') or {}
            with st.expander(f"{_u['date']} · {_u['category']} · {_u['subject']}",
                             expanded=False):
                for _lab, _val in (("변경 전 문제", _dt_u.get('problem')),
                                   ("변경 이유", _dt_u.get('why')),
                                   ("사용자에게 달라지는 점",
                                    _dt_u.get('user_effect')),
                                   ("테스트 결과", _dt_u.get('tests'))):
                    _dim = (_val in (None, '', '기록 없음'))
                    st.markdown(
                        f"<div style='padding:4px 0;'><span style='font-size:12px;"
                        f" color:{_TOK['tx3']};'>{_lab}</span><br>"
                        f"<span style='font-size:13px; color:"
                        f"{_TOK['tx3'] if _dim else _TOK['tx1']};"
                        f" line-height:1.65;'>"
                        f"{_uk._esc(_val or '기록 없음')}</span></div>",
                        unsafe_allow_html=True)
                _meta_u = []
                if _dt_u.get('related'):
                    _meta_u.append("관련 회귀 " + " ".join(_dt_u['related']))
                if _dt_u.get('modules'):
                    _meta_u.append("담당 모듈 " + " · ".join(_dt_u['modules']))
                _meta_u.append(f"버전 {_u['version']} · 커밋 {_u.get('hash', '')}")
                st.caption(" | ".join(_meta_u))
        if len(_sel_upd) > 40:
            st.caption(f"이 카테고리의 나머지 {len(_sel_upd) - 40}건은 아래 표에서 "
                       "보실 수 있습니다.")
            st.dataframe(pd.DataFrame([{
                '날짜': u['date'], '버전': u['version'],
                '카테고리': u['category'], '내용': u['subject'],
            } for u in _sel_upd[40:]]), width='stretch',
                hide_index=True)

# 시장 지수 — 배경정보 (v2: 홈의 주인공이 아니다). 킷 타일로 통일.
_uk.section("시장", "국내·해외 지수와 환율 (전일 대비)", theme=_theme)


def _idx_tile(label, key):
    _d = m_indices.get(key) or {}
    _pct = str(_d.get('pct', ''))
    # 한국 관례: 상승 = 빨강, 하락 = 파랑
    _tone = ('up' if _pct.strip().startswith(('+', '▲'))
             else 'down' if _pct.strip().startswith(('-', '▼')) else '')
    return {'label': label, 'value': f"{_d.get('price', 'N/A')}",
            'sub': f"{_d.get('change', '')} {_pct}".strip(), 'tone': _tone}


_uk.stat_tiles([
    _idx_tile("KOSPI", 'kospi'), _idx_tile("KOSDAQ", 'kosdaq'),
    _idx_tile("USD/KRW", 'usd_krw'), _idx_tile("S&P 500", 'sp500'),
], theme=_theme)

if m_indices['kospi']['price'] == 'N/A' or m_indices['kosdaq']['price'] == 'N/A':
    st.warning("**KOSPI·KOSDAQ 데이터 미수신 알림**: 최신 지수 수치가 연동되지 않아 **`[시장 국면: 판정 보류]`** 상태가 적용되었으며, 매매 적합도 상한(59점) 게이트 통제가 활성화되었습니다.")

st.markdown("<div style='margin-bottom: 12px;'></div>", unsafe_allow_html=True)

# 파이프라인 연산 실행 — 화면 전체가 이 단일 스냅샷 하나만 사용한다
# 기본 스피너는 '무언가 돌고 있다'만 말한다. 어느 단계인지 보여야 기다릴 수 있다.
_prog = st.empty()
_t0 = time.time()
_prog.markdown(_uk.progress(0, label=f"{resolved_name} · 데이터 수집",
                            theme=_theme, elapsed=0.0),
               unsafe_allow_html=True)
try:
    snap, snap_origin = get_shared_snapshot(target_ticker, t_ref_str, rho_cutoff)
    _prog.markdown(_uk.progress(4, label=f"{resolved_name} · 과거 유사사례 탐색",
                                theme=_theme, elapsed=time.time() - _t0),
                   unsafe_allow_html=True)
    report_text, snapshot, latest_fund, sr117_audit, guard_res = build_report_context(snap)
    _elapsed = time.time() - _t0
    _prog.markdown(_uk.progress(6, label="완료", theme=_theme,
                                elapsed=_elapsed), unsafe_allow_html=True)
    # 다음 분석의 예상 시간을 알려주기 위해 기억해 둔다
    st.session_state['_last_analysis_sec'] = _elapsed
finally:
    _prog.empty()          # 끝나면 조용히 사라진다

tech_df   = snap['tech_df']
fund_df   = snap['fund_df']
sim_res   = snap['sim_res']
val_eval  = snap['val_eval']
four_scores = snap['four_scores']
price_pos = snap['price_pos']
matrix_data = snap['source_matrix']

_m = snap['meta']
_origin_txt = {"scan": "상단 스캔 결과와 **동일한 스냅샷**", "cache": "캐시된 스냅샷", "fresh": "새로 산출한 스냅샷"}[snap_origin]
# 개발자용 실행 메타는 접어 둔다 — 첫인상은 결론이 지배해야 한다 (v6)
with st.expander(f"실행 정보 — 분석기준일 {_m['analysis_date']} · "
                 f"{_origin_txt.replace('**', '')}", expanded=False):
    st.caption(
        f"{_origin_txt} · 생성 {_m['generated_at']} · Run `{_m['run_id']}` · "
        f"분석기준일 `{_m['analysis_date']}` · 가격기준 `{_m['price_asof']}` ({_m['price_type']}) · "
        f"재무: 현재 게시값 스냅샷 `{_m['fiscal_asof']}` 수집"
        f"{' (보고서 기준일 아님 — 공시 원문 미연동)' if _m.get('fiscal_is_estimated') else ''} · "
        f"calc `{_m['calc_version']}` / model `{_m['model_version']}` / rulebook `{_m['rulebook_version']}`")

if snap.get('status') == 'REVIEW_REQUIRED':
    st.error("**[무결성 게이트 발동 — 재검토 필요]** 모듈 간 대조에서 모순이 발견되어 이 종목의 추천을 중단했습니다.\n\n"
             + "\n".join(f"- {c}" for c in snap.get('contradictions', [])))

# 종목별 실시간 정밀 시세 정보 추출 (네이버 증권 원본 대조)
stock_info = bitemporal_engine.STOCK_METRICS_DB.get(target_ticker, {})
if not stock_info:
    stock_info = engine_init.get_realtime_stock_price_triple_check(target_ticker)[0] or {}

curr_price = float(four_scores.get('curr_price', stock_info.get('base_price', tech_df['adj_close'].iloc[-1])))
curr_p_formatted = f"{curr_price:,.0f}{unit_str}" if unit_currency == "KRW" else f"${curr_price:,.2f}"

pct_change = float(stock_info.get('pct_change', 0.0))
diff_price = float(stock_info.get('diff_price', 0.0))
open_p = float(stock_info.get('open_p', curr_price))
high_p = float(stock_info.get('high_p', curr_price))
low_p = float(stock_info.get('low_p', curr_price))
volume_p = float(stock_info.get('volume', 0.0))

chg_color = "#35C98B" if pct_change >= 0 else "#ff453a"
chg_sign = "▲ +" if pct_change >= 0 else "▼ "
chg_text = f"{chg_sign}{pct_change:.2f}% ({diff_price:+,.0f}원)" if unit_currency=="KRW" else f"{chg_sign}{pct_change:.2f}% (${diff_price:+.2f})"

# 펀더멘털 & 밸류에이션 핵심 지표 추출
#
# ⚠️ dict.get(key, default) 는 **키가 없을 때만** 기본값을 쓴다.
#    키가 있고 값이 None 이면 None 이 그대로 나와 float(None) 로 터진다.
#    ETF 는 EPS·BPS·ROE 가 아예 없어서 None 이 들어오므로 실제로 터졌다.
# ⚠️ 그리고 12.4·18.4·1973.0 같은 리터럴 기본값은 '지어낸 값'이다.
#    수신하지 못한 지표는 숫자를 만들지 않고 None 으로 두고 화면에 '미수신'으로 적는다.
def _metric(*vals, positive_only=False):
    """첫 유효 수치를 돌려준다. 전부 없으면 None (리터럴로 채우지 않는다)."""
    for v in vals:
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if np.isnan(f):
            continue
        if positive_only and f <= 0:
            continue          # 이 코드베이스에서 PER/BPS 등의 0 은 '미수신' 을 뜻한다
        return f
    return None


_lf = latest_fund if isinstance(latest_fund, dict) else {}
per_val = _metric(four_scores.get('fwd_per'), stock_info.get('per'),
                  val_eval.get('fwd_per'), _lf.get('per'), positive_only=True)
pbr_val = _metric(four_scores.get('pbr'), stock_info.get('pbr'),
                  _lf.get('pbr'), positive_only=True)
roe_val = _metric(stock_info.get('roe'), _lf.get('roe'))          # ROE 는 음수도 유효
eps_val = _metric(stock_info.get('eps'), _lf.get('eps'), positive_only=True)
bps_val = _metric(stock_info.get('bps'), _lf.get('bps'), positive_only=True)

# 적정가 미산출 사유 캡션 — 템플릿 안 조건식이 빈 줄을 만들면 markdown 이
# 이어지는 HTML 을 코드 블록으로 바꾼다. 미리 만들어 같은 줄에 붙인다.
_fv_note_html = ""
if (four_scores.get('displayed_fair_value') is None
        and four_scores.get('fair_value_status_note')):
    _fv_note_html = (f"<p style='margin: 2px 0 0 0; font-size: 12px; "
                     f"color: #9DAABC;'>"
                     f"{str(four_scores.get('fair_value_status_note'))[:48]}</p>")

# 배당은 fetch_dividend_info 하나만 쓴다.
# 구버전은 헤더와 하단 패널이 서로 다른 경로로 계산해 같은 종목의 DPS 가 두 값이었다
# (헤더 1,668원 / 하단 1,444원). 리터럴 폴백(200원·2.11%·'2026-12-28 (연배당)')도 제거한다.
div_info = engine_init.fetch_dividend_info(target_ticker, current_price=realtime_price)
div_payout = div_info.get('dps') if div_info.get('available') else None
div_yield = div_info.get('dividend_yield_pct') if div_info.get('available') else None
div_date = div_info.get('estimated_ex_date') if div_info.get('available') else None

debt_val = _metric(stock_info.get('debt'), _lf.get('debt_to_equity'))
# (예전에 있던 fair_target 은 어디서도 쓰이지 않는 죽은 변수였고,
#  없으면 '현재가 × 1.15' 를 지어내는 폴백까지 달려 있어 함께 제거했다.)

# [1] 가격 헤더 모듈 (최상단)

st.markdown(f"""
<div style='background: #161D2A; border-radius: 12px; padding: 24px 24px; margin-bottom: 20px;'>
    <div style='display: flex; justify-content: space-between; align-items: flex-end; flex-wrap: wrap; gap: 16px;'>
        <div>
            <p style='margin:0; font-size: 20px; font-weight: 700; color: #F3F6FA;'>
                {resolved_name} <span style='font-size: 15px; font-weight: 700; color: #9DAABC;'>{target_ticker}</span>
            </p>
            <div style='font-size: 34px; font-weight: 700; color: {chg_color}; margin: 4px 0 0 0;'>
                {curr_p_formatted} <span style='font-size: 17px; font-weight: 700; margin-left: 8px;'>{chg_text}</span>
            </div>
            <p style='margin: 8px 0 0 0; color: #9DAABC; font-size: 13px;'>
                {_mkt['state']} · 분석 기준일 {t_ref_str} · 통화 {unit_currency} · 단위 {unit_str}
            </p>
        </div>
        <div style='text-align: right; color: #9DAABC; font-size: 13px;'>
            <p style='margin:0;'>시가 {open_p:,.0f} · 고가 <span style='color:#ff453a;'>{high_p:,.0f}</span> · 저가 <span style='color:#0a84ff;'>{low_p:,.0f}</span>{unit_str}</p>
            <p style='margin:8px 0 0 0;'>거래량 {volume_p:,.0f}주 (20일 평균 대비 {fmt_num(tech_df['volume_ratio'].iloc[-1] if 'volume_ratio' in tech_df.columns else None, '.2f', '배')})</p>
            <p style='margin:8px 0 0 0;'>20일 평균 거래대금 {fmt_num((four_scores.get('avg_turnover_20d') or 0) / 1e8, ',.0f', '억원', na='미산출')}</p>
        </div>
    </div>
    <hr style='border: 0; border-top: 1px solid #1C2635; margin: 16px 0 16px 0;'>
    <!-- 📊 9대 핵심 펀더멘털 & 밸류에이션 전광판 -->
    <div style='display: grid; grid-template-columns: repeat(auto-fit, minmax(135px, 1fr)); gap: 10px;'>
        <div style='background: #161D2A; padding: 8px 12px; border-radius: 12px; text-align: center;'>
            <p style='margin: 0; font-size: 12px; color: #9DAABC; font-weight: bold;'>PER (주가수익비율)</p>
            <p style='margin: 4px 0 0 0; font-size: 17px; color: #35C98B; font-weight: bold;'>{fmt_num(per_val, '.1f', '배', na='미수신')}</p>
        </div>
        <div style='background: #161D2A; padding: 8px 12px; border-radius: 12px; text-align: center;'>
            <p style='margin: 0; font-size: 12px; color: #9DAABC; font-weight: bold;'>PBR (주가순자산비율)</p>
            <p style='margin: 4px 0 0 0; font-size: 17px; color: #4C8DFF; font-weight: bold;'>{fmt_num(pbr_val, '.2f', '배', na='미수신')}</p>
        </div>
        <div style='background: #161D2A; padding: 8px 12px; border-radius: 12px; text-align: center;'>
            <p style='margin: 0; font-size: 12px; color: #9DAABC; font-weight: bold;'>ROE (자기자본이익률)</p>
            <p style='margin: 4px 0 0 0; font-size: 17px; color: #F2B84B; font-weight: bold;'>{fmt_num(roe_val, '.1f', '%', na='미수신')}</p>
        </div>
        <div style='background: #161D2A; padding: 8px 12px; border-radius: 12px; text-align: center;'>
            <p style='margin: 0; font-size: 12px; color: #9DAABC; font-weight: bold;'>EPS (주당순이익)</p>
            <p style='margin: 4px 0 0 0; font-size: 17px; color: #F3F6FA; font-weight: bold;'>{fmt_num(eps_val, ',.0f', '원', na='미수신')}</p>
        </div>
        <div style='background: #161D2A; padding: 8px 12px; border-radius: 12px; text-align: center;'>
            <p style='margin: 0; font-size: 12px; color: #9DAABC; font-weight: bold;'>BPS (주당순자산)</p>
            <p style='margin: 4px 0 0 0; font-size: 17px; color: #F3F6FA; font-weight: bold;'>{fmt_num(bps_val, ',.0f', '원', na='미수신')}</p>
        </div>
        <div style='background: #161D2A; padding: 8px 12px; border-radius: 12px; text-align: center;'>
            <p style='margin: 0; font-size: 12px; color: #9DAABC; font-weight: bold;'>주당 배당금 (수익률)</p>
            <p style='margin: 4px 0 0 0; font-size: 17px; color: #35C98B; font-weight: bold;'>{fmt_num(div_payout, ',.0f', '원', na='무배당·미공시')} ({fmt_pct(div_yield, digits=2)})</p>
        </div>
        <div style='background: #161D2A; padding: 8px 12px; border-radius: 12px; text-align: center;'>
            <p style='margin: 0; font-size: 12px; color: #9DAABC; font-weight: bold;'>배당락일 (추정)</p>
            <p style='margin: 4px 0 0 0; font-size: 15px; color: #9DAABC; font-weight: bold;'>{div_date or '—'}</p>
            <p style='margin: 2px 0 0 0; font-size: 12px; color: #F2B84B;'>{('D-' + str(div_info['days_to_ex']) + ' · 관례 추정') if div_info.get('available') and div_info.get('days_to_ex') is not None else '공시 미연동'}</p>
        </div>
        <div style='background: #161D2A; padding: 8px 12px; border-radius: 12px; text-align: center;'>
            <p style='margin: 0; font-size: 12px; color: #9DAABC; font-weight: bold;'>부채비율 (재무안전)</p>
            <p style='margin: 4px 0 0 0; font-size: 17px; color: #35C98B; font-weight: bold;'>{fmt_num(debt_val, '.1f', '%', na='미수신')}</p>
        </div>
        <div style='background: #161D2A; padding: 8px 12px; border-radius: 12px; text-align: center;'>
            <p style='margin: 0; font-size: 12px; color: #4C8DFF; font-weight: bold;'>💎 시장조정 펀더멘털 적정가</p>
            <p style='margin: 4px 0 0 0; font-size: 17px; color: #4C8DFF; font-weight: bold;'>{fmt_num(four_scores.get('displayed_fair_value'), suffix='원')}</p>{_fv_note_html}
        </div>
    </div>
    <!-- 🛡️ 가격 출처 vs 공시 출처 분리 및 다중 출처 교차검증 -->
    <p style='margin: 12px 0 0 0; color: #35C98B; font-size: 13px; text-align: center; border-top: 1px solid #1C2635; padding-top: 8px;'>
        🛡️ <b>데이터 출처 분리</b>: <b>연동된 시세 출처</b> — 네이버증권(기준) · 다음금융(교차검증). <b>미연동</b> — KRX·KIND·FnGuide·Investing.
        <b>DART·KIND·기업IR</b>은 공시·재무 출처이며 현재가 대조에 사용하지 않습니다.
    </p>
</div>
""", unsafe_allow_html=True)

# (감사 처분: 상단 matplotlib 3단 차트 expander는 아래 '종합 차트'와 완전 중복이라
#  제거했다 — 같은 지표(MA 5·20·60·120, RSI, 거래량)를 종합 차트가 인터랙티브로 제공.)

# ═══════════════════════════════════════════════════════════════════════════
# 🧭 최종 결론 — "이 주식 사? 말어?"
# 6개 탭의 독립 판정을 가중 평균하되, 거부 조건은 평균으로 상쇄되지 않게 따로 본다.
# ═══════════════════════════════════════════════════════════════════════════
verdict = q_engine.build_final_verdict(snap)

_ACTION_STYLE = {
    'BUY':        ("#35C98B", "🟢", "매수"),
    'ACCUMULATE': ("#35C98B", "🟢", "분할매수"),
    'HOLD':       ("#F2B84B", "🟡", "관망"),
    'REDUCE':     ("#F26161", "🟠", "비중 축소"),
    'SELL':       ("#ff453a", "🔴", "매도"),
    'NO_TRADE':   ("#ff453a", "🔴", "매수 안 함"),
}
_vc, _vi, _vshort = _ACTION_STYLE.get(verdict['action'], ("#9DAABC", "⚪", "판단 보류"))
_vscore = verdict['score']

# 실행 가격 기준 — 종합 결론 배너 안에 함께 표시 (표시 위치는 이 배너 한 곳만; 상세 카드에서는 중복 표기하지 않음)
# 적정가 기반 권장 매수가가 없으면 기술 지지 기반 '진입 검토가'를 대신 보여준다
# (엔진이 이미 계산한 지지선 재사용 — 계층이 다름을 라벨로 명시, 없으면 없다고 말한다).
rec_buy_val = four_scores.get('recommended_buy_price')
_er_price = four_scores.get('entry_review_price')
_er_basis = four_scores.get('entry_review_basis') or ''
rec_buy_sub = ''
if rec_buy_val is not None:
    rec_buy_display = f"{rec_buy_val:,.0f}원 이하"
elif _er_price:
    rec_buy_display = f"{_er_price:,.0f}원 부근"
    _er_why = ("모델 범위 밖" if four_scores.get('fair_value_status') == 'OUT_OF_DOMAIN'
               else "적정가 신뢰도 미달")
    rec_buy_sub = f"기술 지지 기준: {_er_basis} — 적정가 검증 없음 ({_er_why})"
elif four_scores.get('fair_value_status') == 'OUT_OF_DOMAIN':
    # 성장 기대가 가격을 지배하는 종목 — 신뢰도 문제가 아니라 모델이 성립하지 않는다
    rec_buy_display = "산출 불가 (모델 범위 밖)"
    rec_buy_sub = "현재가 아래 유효 지지선도 없음 — 진입 기준 자체가 없습니다"
else:
    rec_buy_display = "신뢰도 미달"
    rec_buy_sub = "현재가 아래 유효 지지선도 없음 — 근거가 생길 때까지 관망"
# 주의: f-string 템플릿 안에 조건부로 '빈 줄'을 남기면 markdown 이 이어지는
# HTML 을 코드 블록으로 렌더한다 — 반드시 앞 요소와 같은 줄에 붙인다.
_rec_sub_html = (f"<p style='margin:4px 0 0 0; font-size:12px; "
                 f"color:#9DAABC;'>{rec_buy_sub}</p>" if rec_buy_sub else "")
_ex_tgt = fmt_num(four_scores.get('target_tech_1st'), suffix='원', na='산출 불가')
_ex_stop = fmt_num(four_scores.get('stop_loss_price'), suffix='원', na='산출 불가')

# 권장 매수가에 샀을 때의 레벨. 위 두 값은 **현재가** 기준이라, 아직 안 산
# 사람에게는 맞지 않는다. 실측(라운드 22b · 30종목)에서 권장 매수가가 나온
# 17종목 중 11종목(65%)의 손절가가 매수가보다 위였다 — 최대 +193%.
# 그래서 진입가 기준 레벨을 따로 계산해 살 가격 칸 밑에 붙인다.
_e_stop = four_scores.get('entry_stop_price')
_e_t1 = four_scores.get('entry_target_1st')
_e_rr = four_scores.get('entry_rr')
_entry_lv_html = ''
if _e_stop and _e_t1:
    _entry_lv_html = (
        f"<p style='margin:6px 0 0 0; font-size:12px; color:#9DAABC; "
        f"line-height:1.6;'>이 가격에 사면 → 손절 "
        f"<b style='color:#ff453a;'>{_e_stop:,.0f}원</b> · 1차 목표 "
        f"<b style='color:#4C8DFF;'>{_e_t1:,.0f}원</b>"
        + (f" · 손익비 <b>{_e_rr}:1</b>" if _e_rr else '')
        + "</p>")

# ── 도달 가능성 · 논리 검사 ──────────────────────────────────────────────
# "권장 매수가가 현실적으로 닿는 가격인가"를 σ 로 재서 말로 옮긴다.
# 안 적으면 현재가의 절반인 값이 실행 가격처럼 보인다.
_rc_sig = four_scores.get('rec_buy_sigma')
_rc_reach = four_scores.get('rec_buy_reach')
_rc_drop = four_scores.get('rec_buy_drop_pct')
_t1_sig = four_scores.get('target1_sigma')
_t1_reach = four_scores.get('target1_reach')
_sig_pct = four_scores.get('horizon_sigma_pct')
_fair_v = four_scores.get('displayed_fair_value')
_gap_fair = ((realtime_price / _fair_v - 1) * 100
             if (_fair_v and realtime_price) else None)

#: 도달이 어려우면 '실행 가격'이 아니라 '관찰 대상'이다 — 강조를 낮춘다
_rec_is_far = bool(_rc_sig is not None and _rc_sig > 2.0)

_reach_html = ''
if _rc_sig is not None:
    _rc_col = '#F2B84B' if _rec_is_far else '#9DAABC'
    _reach_html = (
        f"<p style='margin:6px 0 0 0; font-size:12px; color:{_rc_col}; "
        f"line-height:1.6;'>현재가에서 <b>{_rc_drop:+.1f}%</b> "
        f"— 20일 변동폭({_sig_pct}%) 대비 <b>{_rc_sig}σ</b> · {_rc_reach}"
        + ("<br><b>지금은 매수 후보가 아니라 관찰 대상입니다.</b> "
           "계산된 매수가까지 차이가 너무 커 단기간에 내려올 가능성이 낮습니다."
           if _rec_is_far else '')
        + "</p>")

# 논리 검사 — 사용자가 요청한 조건을 자동으로 걸고, 어긋나면 화면에 적는다
_logic_warn = []
if _e_t1 and rec_buy_val and _e_t1 <= rec_buy_val:
    _logic_warn.append('신규 목표가가 매수가보다 낮거나 같습니다')
if _e_stop and rec_buy_val and _e_stop >= rec_buy_val:
    _logic_warn.append('신규 손절가가 매수가보다 높거나 같습니다')
if _e_rr is not None and _e_rr < 1.0:
    _logic_warn.append(
        f'신규 진입 손익비가 {_e_rr}:1 로 1:1 에 못 미칩니다 '
        f'(목표를 손절거리의 0.7배로 잡는 현행 구조 탓 — 라운드 21 기록)')
if (_gap_fair is not None and _gap_fair > 20
        and four_scores.get('target_tech_1st')
        and _fair_v and four_scores['target_tech_1st'] > _fair_v):
    _logic_warn.append(
        f'장기 적정가({_fair_v:,.0f}원)보다 현재가가 {_gap_fair:+.0f}% 높은데 '
        f'보유자 목표가는 그보다 더 위입니다 — 목표가는 밸류에이션이 아니라 '
        f'20일 변동성·저항으로만 계산되기 때문입니다')
if _t1_sig is not None and _t1_sig > 2.0:
    _logic_warn.append(f'보유자 1차 목표가 20일 변동폭 대비 {_t1_sig}σ '
                       f'로 멀어 도달 가능성이 낮습니다')

# ── 다음 조건 — "사지 마세요"로 끝내지 않는다 ────────────────────────────
# 관망이라면 **언제·어떤 조건에서** 살 수 있는지 반드시 적는다.
import next_action as _na
_NA = _na.build(four_scores, tech_df, realtime_price, verdict)

# ── 관망 조건 감시 — 저장만 하고 다시 안 보면 매번 직접 검색해야 한다 ────
import watch_alerts as _wa
_watch_now = None
try:
    _wa_items = (_wa.load().get('items') or [])
    _watch_now = next((it for it in _wa_items
                       if it.get('symbol') == target_ticker), None)
except Exception:
    _wa_items = []

_watch_html = ''
if _watch_now:
    # 등록해 둔 조건을 **오늘 값으로 다시 잰다**
    try:
        _lastbar = tech_df.iloc[-1]
        _res = _wa.check_one(
            _watch_now, price=realtime_price,
            low=float(_lastbar.get('low')), high=float(_lastbar.get('high')),
            close=realtime_price,
            bb_pos=four_scores.get('bb_position_pct'),
            wr=four_scores.get('williams_r_value'),
            vol_ratio=(float(_lastbar.get('volume_ratio'))
                       if _lastbar.get('volume_ratio') is not None else None))
    except Exception:
        _res = None
    if _res:
        _wcol = '#35C98B' if _res['resolved'] else '#9DAABC'
        _lines = ''.join(
            f"<li style='margin:3px 0; color:#35C98B;'>{_uk._esc(x)}</li>"
            for x in _res['met'])
        _lines += ''.join(
            f"<li style='margin:3px 0;'>{_uk._esc(x)}</li>"
            for x in (_res['unmet'] + _res.get('pending', [])))
        _hdr = (_wa.sentence(_watch_now, _res) if _res['resolved']
                else '등록한 관망 조건 — 아직 기다리는 중입니다')
        _watch_html = (
            f"<div style='margin-top:12px; background:#1C2635; "
            f"border-radius:12px; padding:12px 16px;'>"
            f"<p style='margin:0 0 4px 0; font-size:12px; color:#9DAABC; "
            f"font-weight:700;'>알림 감시 "
            f"({_watch_now.get('registered_at', '')[:10]} 등록)</p>"
            f"<p style='margin:0 0 6px 0; font-size:15px; font-weight:700; "
            f"color:{_wcol}; line-height:1.5;'>{_uk._esc(_hdr)}</p>"
            f"<ul style='margin:0; padding-left:18px; font-size:12px; "
            f"color:#9DAABC; line-height:1.65;'>{_lines}</ul></div>")

_na_html = ''
if _NA.get('headline'):
    _na_col = {'buy_now': '#35C98B', 'pullback': '#F2B84B',
               'breakout': '#4C8DFF', 'blocked': '#ff453a'}.get(
                   _NA['kind'], '#9DAABC')
    _na_items = ''.join(
        f"<li style='margin:4px 0;'>{_uk._esc(c['text'])}</li>"
        for c in _NA.get('conditions', []))
    _na_html = (
        f"<div style='margin-top:14px; background:#1C2635; border-radius:12px; "
        f"padding:12px 16px;'>"
        f"<p style='margin:0 0 2px 0; font-size:12px; color:#9DAABC; "
        f"font-weight:700;'>다음 조건 — 언제 사면 되나</p>"
        f"<p style='margin:0 0 6px 0; font-size:17px; font-weight:700; "
        f"color:{_na_col}; line-height:1.4;'>{_uk._esc(_NA['headline'])}</p>"
        + (f"<ul style='margin:0; padding-left:18px; font-size:13px; "
           f"color:#9DAABC; line-height:1.65;'>{_na_items}</ul>"
           if _na_items else '')
        + (f"<p style='margin:6px 0 0 0; font-size:12px; color:#9DAABC;'>"
           f"괴리 {_NA['gap_pct']:+.1f}% · [{_NA['gap_band']}] · "
           f"일 변동폭 {_NA['atr_pct']}%"
           + (f" · 예상 대기 {_NA['wait_days']}거래일"
              if _NA.get('wait_days') else '')
           + "</p>" if _NA.get('gap_band') else '')
        + "</div>")

# 보유자 목표의 도달 가능성도 같은 잣대로 적는다
_hold_reach_html = ''
if _t1_sig is not None and realtime_price and four_scores.get('target_tech_1st'):
    _up = (four_scores['target_tech_1st'] / realtime_price - 1) * 100
    _hold_reach_html = (
        f"<p style='margin:10px 0 0 0; font-size:12px; color:#9DAABC; "
        f"line-height:1.6;'>1차 목표까지 <b>{_up:+.1f}%</b> — 20일 변동폭"
        f"({_sig_pct}%) 대비 <b>{_t1_sig}σ</b> · {_t1_reach}</p>")

# 논리 검사에 걸린 것은 숨기지 않고 그 자리에 적는다 (경고 없는 모순이 제일 나쁘다)
_logic_warn_html = ''
if _logic_warn:
    _items = ''.join(f"<li style='margin:3px 0;'>{_uk._esc(x)}</li>"
                     for x in _logic_warn)
    _logic_warn_html = (
        f"<div style='margin-top:12px; background:#1C2635; border-radius:12px; "
        f"padding:10px 14px;'>"
        f"<p style='margin:0 0 4px 0; font-size:12px; color:#F2B84B; "
        f"font-weight:700;'>가격 체계 자동 점검 — 걸린 항목 {len(_logic_warn)}건</p>"
        f"<ul style='margin:0; padding-left:18px; font-size:12px; "
        f"color:#9DAABC; line-height:1.65;'>{_items}</ul></div>")

# ⏱️ DeMARK 매수 포인트 — 신호 상태와 유효 하한선(TDST 지지)을 함께 보여준다.
_dme = four_scores.get('demark_entry') or {}
_dm_state = _dme.get('state')
_dm_color = {'COMPLETE': '#35C98B', 'SETUP_DONE': '#35C98B',
             'FORMING': '#F2B84B'}.get(_dm_state, '#9DAABC')
if _dme:
    _dm_head = _dme.get('headline', '')
    # 유효 하한선은 신호가 있을 때만 보여준다. 신호가 없는데 선만 띄우면
    # 진입 근거가 있는 것처럼 읽힌다.
    if _dme.get('trigger_line') and _dm_state in ('COMPLETE', 'SETUP_DONE', 'FORMING'):
        _dm_line = (f"유효 하한 {_dme['trigger_line']:,.0f}원 "
                    f"({'지지 유지 중' if _dme.get('valid') else '이탈 — 신호 무효'})")
    elif _dm_state in ('COMPLETE', 'SETUP_DONE', 'FORMING'):
        _dm_line = "유효 하한(TDST 지지) 산출 불가"
    else:
        _dm_line = str(_dme.get('detail', ''))[:60]
else:
    _dm_head, _dm_line = "산출 불가 (데이터 부족)", "DeMARK 신호를 만들지 못했습니다"

st.markdown('<div id="nav-verdict"></div>', unsafe_allow_html=True)
# 헤드라인만으로는 '조건부'가 안 보인다 — 신규 매수자용 쉬운 결론 한 줄을
# 배너 안에 병기해, "지금은 사지 마세요"가 '31,665원 이하로 내려오면 산다'는
# 조건부인지 완전 회피인지 배너에서 바로 구분되게 한다.
try:
    _easy_nb_banner = q_engine.build_easy_advice(
        four_scores, verdict, realtime_price,
        user_avg=None, user_qty=None)['new_buyer']
    _banner_sub = str(_easy_nb_banner.get('line') or '')
    if '이하로 내려올 때만' in _banner_sub:
        _banner_sub += f" (현재가 {realtime_price:,.0f}원은 조건 위)"
except Exception:
    _banner_sub = ''
_banner_sub_html = (
    f"<p style='margin:8px 0 0 0; font-size:17px; font-weight:700; "
    f"color:#F3F6FA;'>{_banner_sub}</p>" if _banner_sub
    and _banner_sub not in str(verdict['headline']) else "")

# 매수·매도 성공 확률이 최우선이다 — 점수 바로 아래에 실측 확률을 1등으로 표시.
# 원천은 리플레이 실측(점수대 캘리브레이션)뿐이며, 표본이 부족하면 %를 숨기고
# '표본 부족'을 그대로 보여준다 (요행 수치를 대표값으로 쓰지 않는다).
_cb_banner = four_scores.get('calibration_band') or {}
if (_cb_banner.get('hit_rate') is not None
        and (_cb_banner.get('n') or 0) >= 30):
    _prob_html = (
        f"<p style='margin:8px 0 0 0; font-size:12px; color:#9DAABC;'>"
        f"비슷했던 과거에서 맞은 비율</p>"
        f"<p style='margin:0; font-size:28px; font-weight:700; "
        f"color:#F3F6FA; line-height:1.1;'>{_cb_banner['hit_rate']:.0f}%"
        f"<span style='font-size:13px; color:#9DAABC;'> "
        f"(n={_cb_banner['n']:,} · W하한 "
        f"{fmt_num(_cb_banner.get('wilson_low'), '.0f', '%', na='—')})</span></p>")
elif _cb_banner:
    _prob_html = (
        f"<p style='margin:8px 0 0 0; font-size:12px; color:#F2B84B;'>"
        f"실측 확률 표본 부족 (n={_cb_banner.get('n', 0)}) — 표시 보류</p>")
else:
    _prob_html = ""
st.markdown(f"""
<div style='background:linear-gradient(135deg,#161D2A 0%,#161D2A 100%);
            border:3px solid {_vc}; border-radius:20px; padding:24px 24px; margin-bottom:16px;
            box-shadow:0 10px 34px {_vc}22;'>
  <div style='display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:14px;'>
    <div>
      <p style='margin:0; font-size:13px; color:#9DAABC; font-weight:700;'>
        {resolved_name} · 오늘의 판단</p>
      <p style='margin:4px 0 0 0; font-size:40px; font-weight:800; color:{_vc}; line-height:1.15;'>
        {_vi} {verdict['headline']}</p>{_banner_sub_html}
    </div>
    <div style='text-align:right;'>
      <p style='margin:0; font-size:13px; color:#9DAABC;'>판단 점수</p>
      <p style='margin:0; font-size:34px; font-weight:700; color:{_vc}; line-height:1;'>
        {fmt_num(_vscore, ',.0f', na='—')}<span style='font-size:17px; color:#9DAABC;'> / 100</span></p>{_prob_html}
      <p style='margin:2px 0 0 0; font-size:15px; font-weight:700; color:{_vc};'>{_vshort}</p>
    </div>
  </div>
  <div style='display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:12px;
              margin-top:16px; padding-top:16px; border-top:1px solid #1C2635;'>
    <div style='background:#161D2A; border-radius:14px; padding:14px 16px;'>
      <p style='margin:0 0 10px 0; font-size:13px; color:#35C98B; font-weight:700;'>
        아직 안 샀다면 <span style='color:#9DAABC; font-weight:400;'>· 신규 매수 기준</span></p>
      <p style='margin:0; font-size:12px; color:#9DAABC;'>살 가격 · 이 값 이하에서</p>
      <p style='margin:2px 0 0 0; font-size:{'17' if _rec_is_far else '22'}px; font-weight:700;
                color:{'#9DAABC' if _rec_is_far else '#35C98B'};'>{rec_buy_display}</p>{_rec_sub_html}{_reach_html}{_entry_lv_html}
      <p style='margin:10px 0 0 0; font-size:12px; color:#9DAABC;'>매수 타이밍 신호 · 하락세가 힘 빠지는 지점</p>
      <p style='margin:2px 0 0 0; font-size:15px; font-weight:700; color:{_dm_color}; line-height:1.3;'>{_dm_head}</p>
      <p style='margin:2px 0 0 0; font-size:12px; color:#9DAABC;'>{_dm_line}</p>
    </div>
    <div style='background:#161D2A; border-radius:14px; padding:14px 16px;'>
      <p style='margin:0 0 10px 0; font-size:13px; color:#4C8DFF; font-weight:700;'>
        이미 갖고 있다면 <span style='color:#9DAABC; font-weight:400;'>· 현재가 기준 대응</span></p>
      <div style='display:flex; gap:18px; flex-wrap:wrap;'>
        <div><p style='margin:0; font-size:12px; color:#9DAABC;'>팔 가격 1차 · 일부 정리</p>
          <p style='margin:2px 0 0 0; font-size:22px; font-weight:700; color:#4C8DFF;'>{_ex_tgt}</p></div>
        <div><p style='margin:0; font-size:12px; color:#9DAABC;'>버틸 수 없는 가격 · 손실을 끊는 선</p>
          <p style='margin:2px 0 0 0; font-size:22px; font-weight:700; color:#ff453a;'>{_ex_stop}</p></div>
      </div>{_hold_reach_html}
    </div>
  </div>{_na_html}{_watch_html}{_logic_warn_html}
  <p style='margin:10px 0 0 0; font-size:12px; color:#9DAABC; line-height:1.7;'>
    <b style='color:#F2B84B;'>시간축이 다릅니다.</b>
    펀더멘털 적정가는 <b>분기 실적 기반 장기 가치</b>이고, 위 목표·손절은 <b>20일 변동성과 저항선</b>으로 계산합니다.
    그래서 고평가 구간에서도 단기 목표가가 현재가보다 위에 나올 수 있습니다 — 목표가는 밸류에이션을 보지 않습니다.
    신규 매수 판단과 보유자 대응은 서로 다른 결론일 수 있고, 그것이 정상입니다.
    DeMARK 는 <b>시점</b> 신호이며 권장 매수가(<b>가격</b> 기준)와 함께 볼 때만 의미가 있습니다.</p>
</div>
""", unsafe_allow_html=True)

# ── 알림 감시 등록·해제 ─────────────────────────────────────────────────
# 관망 조건을 저장해 두면 다음에 이 종목을 열 때 오늘 값으로 다시 재서
# 풀렸는지 알려 준다. 매번 직접 검색하지 않아도 되게 하는 것이 목적이다.
if _NA.get('alert'):
    _wc1, _wc2 = st.columns([1, 3])
    with _wc1:
        if _watch_now:
            if st.button("알림 해제", width='stretch', key='btn_wa_off'):
                _wa.remove(target_ticker)
                st.rerun()
        else:
            if st.button("이 조건 알림 등록", width='stretch',
                         type='primary', key='btn_wa_on'):
                _wa.register(target_ticker, resolved_name, realtime_price,
                             _NA, engine_version=_VER_NOW['model'])
                st.rerun()
    with _wc2:
        st.caption("등록하면 다음에 이 종목을 열 때 위 조건을 오늘 값으로 "
                   "다시 재서 풀렸는지 알려 드립니다. 시세·지표를 못 받으면 "
                   "'확인 불가'로 남기고 충족으로 세지 않습니다."
                   if not _watch_now else
                   "이 종목은 알림 감시 중입니다. 조건은 이 화면을 열 때마다 "
                   "다시 잽니다.")

# ═══ 아주 쉬운 결론 — 신규 매수자와 보유자를 절대 섞지 않는다 ═══════════════
# 사용자 상태 선택기 (v2): 분석 화면 안에서 미보유/보유를 고른다.
# '보유 중' 선택 시 여기 입력값이 이후 모든 보유자 판정(쉬운 결론·포지션 진단)에
# 쓰인다 — 사이드바 입력은 기본값 공급원이다.
_pos_default = 1 if user_entry_price > 0 else 0
_pos_mode = st.radio("이 종목을 갖고 계신가요?", ["아직 없음", "보유 중"],
                     index=_pos_default, horizontal=True, key="pos_mode_main")
if _pos_mode == "보유 중":
    _pc1, _pc2 = st.columns(2)
    with _pc1:
        _main_avg = st.number_input(
            "평균 매수가 (원)", min_value=0,
            value=int(user_entry_price) if user_entry_price > 0 else 0,
            step=1000, key="pos_avg_main",
            help="보유 판단에만 사용합니다 — 예측·적정가·점수에는 절대 반영되지 않습니다.")
    with _pc2:
        _main_qty = st.number_input(
            "보유 수량 (주)", min_value=0,
            value=int(user_quantity) if user_quantity > 0 else 0,
            step=10, key="pos_qty_main")
    if _main_avg > 0:
        user_entry_price, user_quantity = _main_avg, _main_qty
else:
    user_entry_price, user_quantity = 0, 0

_easy = q_engine.build_easy_advice(
    four_scores, verdict, realtime_price,
    user_avg=(user_entry_price if user_entry_price > 0 else None),
    user_qty=(user_quantity if user_quantity > 0 else None))
_ec1, _ec2 = st.columns(2)
with _ec1:
    _nb = _easy['new_buyer']
    st.markdown(f"""
    <div style='background:#161D2A; border-radius:14px; padding:16px 16px; height:100%;'>
      <p style='margin:0; font-size:12px; color:#9DAABC; font-weight:700;'>처음 사는 분께</p>
      <p style='margin:8px 0; font-size:17px; font-weight:700; color:#F3F6FA;'>{_nb['emoji']} {_nb['line']}</p>
      <p style='margin:0; font-size:15px; color:#9DAABC; line-height:1.55;'>{_nb['detail']}</p>
    </div>""", unsafe_allow_html=True)
with _ec2:
    _hd = _easy['holder']
    if _hd:
        st.markdown(f"""
        <div style='background:#161D2A; border-radius:14px; padding:16px 16px; height:100%;'>
          <p style='margin:0; font-size:12px; color:#9DAABC; font-weight:700;'>이미 갖고 계신 분께 (평단 {user_entry_price:,.0f}원 · 현재 {_hd['ret_pct']:+.1f}%)</p>
          <p style='margin:8px 0; font-size:17px; font-weight:700; color:#F3F6FA;'>{_hd['emoji']} {_hd['line']}</p>
          <p style='margin:0; font-size:15px; color:#9DAABC; line-height:1.55;'>{_hd['detail']}</p>
        </div>""", unsafe_allow_html=True)
    else:
        st.markdown("""
        <div style='background:#161D2A; border-radius:14px; padding:16px 16px; height:100%;'>
          <p style='margin:0; font-size:12px; color:#9DAABC; font-weight:700;'>이미 갖고 계신 분께</p>
          <p style='margin:8px 0; font-size:15px; color:#9DAABC; line-height:1.6;'>
            위에서 <b>'보유 중'</b>을 선택하고 평균 매수가를 넣으면<br>
            보유·일부 매도·손절·추가 매수 여부를 <b>내 평단 기준</b>으로 알려드립니다.</p>
        </div>""", unsafe_allow_html=True)
st.caption("신규 매수 기준과 보유자 기준은 서로 다릅니다 — 신규 진입가와 보유자 손절가가 "
           "다른 값인 것이 정상입니다. 투자 권유가 아니며 판단 책임은 본인에게 있습니다.")

# 변동성 관리 비중 · 상대 모멘텀 · 실전 적중률 — 결론 바로 아래 한 줄 요약
_extra_bits = []
_pos_sug = four_scores.get('suggested_position_pct')
if _pos_sug:
    _extra_bits.append(f"📐 변동성 관리 비중 제안: 자본의 **{_pos_sug:.0f}% 이내** "
                       f"({four_scores.get('suggested_position_basis', '')})")
_rm = four_scores.get('rel_mom_detail')
if _rm and _rm.get('relative') is not None:
    _extra_bits.append(f"🏁 상대 모멘텀(12-1): **{_rm['relative']:+.1f}%p** "
                       f"(종목 {_rm['stock']:+.1f}% vs {_rm['market']} {_rm['index']:+.1f}%)")
_tr = four_scores.get('track_record')
if _tr and _tr.get('hit_rate') is not None:
    _extra_bits.append(f"🎯 실전 판정 적중률 **{_tr['hit_rate']:.0f}%** "
                       f"({_tr.get('decided', 0)}건 판정 완료 — 점수 확신에 반영)")
_cb = four_scores.get('calibration_band')
if _cb and _cb.get('hit_rate') is not None and _cb.get('n', 0) >= 5:
    _extra_bits.append(
        f"🧪 가상 백테스트: 이 점수대({_cb['lo']}~{_cb['hi']}점)의 과거 리플레이 적중률 "
        f"**{_cb['hit_rate']:.0f}%** (n={_cb['n']}, Wilson 하한 {_cb['wilson_low']:.0f}%)")
elif _cb and _cb.get('n', 0) < 5:
    _extra_bits.append(f"🧪 이 점수대({_cb['lo']}~{_cb['hi']}점) 리플레이 표본 "
                       f"{_cb.get('n', 0)}건 — 표본 부족으로 적중률 미표시")
# ⚠️ 엔진 인스턴스 속성은 스냅샷이 캐시에서 오면 비어 있다 — 파일을 직접 읽는다
_calib_all = _load_calibration_meta()
if _calib_all.get('total_cases'):
    _extra_bits.append(f"📚 모델 {_calib_all.get('rulebook_version', '')} · "
                       f"누적 케이스 {_calib_all['total_cases']:,}건")
if _extra_bits:
    st.caption("  ·  ".join(_extra_bits))

# ── 우측 고정 요약 패널 (v2) — 긴 분석을 읽어도 핵심 판단은 계속 보인다 ─────
# 넓은 화면에서만 표시 (본문 1440px + 사이드바 + 패널 폭이 확보될 때).
_sum_conf = four_scores.get('analysis_confidence')
_sum_band = (f"{_cb['hit_rate']:.0f}% (n={_cb['n']})"
             if _cb and _cb.get('hit_rate') is not None and _cb.get('n', 0) >= 5
             else "표본 부족")
st.markdown(f"""
<style>
.qside {{ position: fixed; right: 22px; top: 120px; width: 248px; z-index: 90;
  background: {_TOK['surface']}; border-radius: 12px; padding: 20px 20px; }}
.qside .act {{ color: {_vc}; font-size: 17px; font-weight: 700;
  margin: 0 0 8px 0; line-height: 1.3; }}
.qside table {{ width: 100%; border-collapse: collapse; }}
.qside td {{ padding: 3px 0; font-size: 13px; color: {_TOK['tx2']}; }}
.qside td:last-child {{ text-align: right; color: {_TOK['tx1']};
  font-weight: 700; font-variant-numeric: tabular-nums; }}
@media (max-width: 1760px) {{ .qside {{ display: none; }} }}
</style>
<div class="qside">
  <p class="act">{verdict['headline']}</p>
  <table>
    <tr><td>종합점수</td><td>{verdict['score']}점</td></tr>
    <tr><td>현재가</td><td>{realtime_price:,.0f}{unit_str}</td></tr>
    <tr><td>진입 검토가</td><td>{fmt_num(four_scores.get('recommended_buy_price'), ',.0f', unit_str, na='산출 불가')}</td></tr>
    <tr><td>1차 목표가</td><td>{fmt_num(four_scores.get('target_tech_1st'), ',.0f', unit_str, na='산출 불가')}</td></tr>
    <tr><td>손절가</td><td>{fmt_num(four_scores.get('stop_loss_price'), ',.0f', unit_str, na='산출 불가')}</td></tr>
    <tr><td>분석 신뢰도</td><td>{fmt_num(_sum_conf, '.0f', '점', na='미산출')}</td></tr>
    <tr><td>이 점수대 실측</td><td>{_sum_band}</td></tr>
  </table>
</div>
""", unsafe_allow_html=True)

# ── 원칙 3: 결론·가격 다음에 '이유' — 점수를 움직인 요인 상·하위 3개 ────────
# verdict['composition'] 실측만 사용한다 (label/score/weight_pct/contribution).
_comp_scored = [c for c in verdict.get('composition', [])
                if c.get('score') is not None]
# 상·하위 3개씩 잘라 놓으면 요인이 3개뿐일 때 **같은 세 줄이 양쪽에** 선다 —
# 실제로 그랬다. 기준은 개수가 아니라 가중평균이어야 한다. 그보다 높으면 올린
# 요인, 낮으면 내린 요인이고, 한쪽이 비면 나누지 않고 한 줄로 세운다.
_comp_w = sum((c.get('weight_pct') or 0) for c in _comp_scored)
_comp_avg = (sum(c['score'] * (c.get('weight_pct') or 0)
                 for c in _comp_scored) / _comp_w) if _comp_w else None
if _comp_scored and _comp_avg is not None:
    def _comp_line(c):
        return (f"- {c['label']} — **{c['score']}점** "
                f"(비중 {c['weight_pct']:.0f}% · 평균 대비 "
                f"{c['score'] - _comp_avg:+.0f}점)")

    _comp_hi = sorted([c for c in _comp_scored if c['score'] > _comp_avg],
                      key=lambda c: c['score'], reverse=True)
    _comp_lo = sorted([c for c in _comp_scored if c['score'] < _comp_avg],
                      key=lambda c: c['score'])
    if _comp_hi and _comp_lo:
        _fc1, _fc2 = st.columns(2)
        with _fc1:
            st.markdown(f"**점수를 끌어올린 요인 {len(_comp_hi)}**")
            for c in _comp_hi[:3]:
                st.markdown(_comp_line(c))
        with _fc2:
            st.markdown(f"**점수를 끌어내린 요인 {len(_comp_lo)}**")
            for c in _comp_lo[:3]:
                st.markdown(_comp_line(c))
    else:
        st.markdown(f"**점수를 만든 요인 {len(_comp_scored)}** — "
                    f"가중평균 {_comp_avg:.0f}점 기준")
        for c in sorted(_comp_scored, key=lambda c: c['score'], reverse=True):
            st.markdown(_comp_line(c))

# ── 이 종목의 주요 이슈 (v4) — 이미 계산된 경고의 재표현만, 요약 + 전체 보기 ──
_nf_iss = ((snap.get('market_context') or {}).get('news_flags') or {})
_issues_stock = _pops.build_stock_issues(four_scores, verdict, _nf_iss,
                                         name=resolved_name)
if _issues_stock:
    st.markdown("#### 이 종목의 주요 이슈")
    for _is in _issues_stock[:3]:
        _bc, _bt = _SEV_BADGE.get(_is['severity'], ('#9DAABC', '—'))
        st.markdown(
            f"<div style='background:{_TOK['surface']}; border-left:3px solid "
            f"{_bc if _is['severity'] == '높음' else 'transparent'}; "
            f"border-radius:12px; padding:12px 16px; margin-bottom:8px;'>"
            f"<span style='background:{_TOK['hover']}; color:{_bc}; font-size:12px; "
            f"font-weight:700; padding:2px 8px; border-radius:6px;'>{_bt}</span> "
            f"<span style='background:{_TOK['hover']}; color:{_TOK['tx2']}; "
            f"font-size:12px; font-weight:700; padding:2px 8px; border-radius:6px;'>"
            f"{_is['type']}</span> "
            f"<b style='font-size:13px; color:{_TOK['tx1']};'> {_is['title']}</b>"
            f"<p style='margin:4px 0 0 0; font-size:13px; color:{_TOK['tx2']};'>"
            f"{_is['detail']}</p></div>", unsafe_allow_html=True)
    if len(_issues_stock) > 3:
        with st.expander(f"전체 이슈 보기 ({len(_issues_stock)}건)",
                         expanded=False):
            st.dataframe(pd.DataFrame([{
                '중요도': i['severity'], '유형': i['type'], '제목': i['title'],
                '내용': i['detail'],
            } for i in _issues_stock]), width='stretch',
                hide_index=True)

if verdict['vetoes']:
    st.error("**매수 결론을 막는 조건 " + str(len(verdict['vetoes'])) + "건** — "
             "다른 점수가 높아도 이 조건들이 먼저입니다.\n\n"
             + "\n".join(f"- {x}" for x in verdict['vetoes']))

# 신호 간 이견이 있었지만 판정을 폐기하지 않고 보수적으로 화해시킨 경우 그 내역을 보여준다.
_soft_notes = four_scores.get('soft_conflict_notes') or []
if _soft_notes:
    st.info("**신호 간 이견을 화해시켰습니다** — 모듈들이 다른 방향을 가리켰지만, "
            "이견은 '판정 불가'가 아니라 '확신을 낮출 이유'입니다. 보수적인 쪽으로 "
            "결론을 내렸습니다.\n\n" + "\n".join(f"- {x}" for x in _soft_notes))

_up_raw = four_scores.get('upside_pct')
_up_shr = four_scores.get('upside_shrunk_pct')
if (_up_raw is not None and _up_shr is not None
        and abs(float(_up_raw) - float(_up_shr)) >= 3.0):
    st.caption(f"ℹ️ 적정가 괴리율 {float(_up_raw):+.1f}% 는 신뢰도 "
               f"{four_scores.get('fair_value_confidence', 0):.0f}점을 반영해 "
               f"**{float(_up_shr):+.1f}%** 로 수축시켜 판단에 씁니다 "
               f"(신뢰도가 낮을수록 시장가격 쪽으로 끌어당김 — Black–Litterman 방식).")

_vc1, _vc2 = st.columns([1.15, 1])
with _vc1:
    st.markdown("**이 점수는 이렇게 나왔습니다**")
    st.dataframe(pd.DataFrame([{
        "구성 항목": c['label'],
        "점수": "—" if c['score'] is None else f"{c['score']}",
        "비중": f"{c['weight_pct']:.0f}%",
        "기여": "—" if c['contribution'] is None else f"{c['contribution']:.1f}",
    } for c in verdict['composition']]), width='stretch', hide_index=True)
    if verdict['cap_applied']:
        st.markdown(f"가중합 **{verdict['raw_weighted_sum']:.0f}점** 게이트 상한 적용 → "
                    f"**{verdict['score']}점**")
        if verdict.get('gate_reason'):
            st.caption("상한 사유: " + str(verdict['gate_reason'])[:300])
    else:
        st.markdown(f"가중합 **{verdict['raw_weighted_sum']:.0f}점** = 최종 **{verdict['score']}점** "
                    f"(상한 미적용)")
    st.caption("이 표가 **유일한 종합 점수 산식**입니다. 아래 관점별 판정은 근거를 보여줄 뿐 "
               "따로 합산하지 않습니다 — 점수가 둘이면 어느 쪽을 믿을지 알 수 없습니다.")
with _vc2:
    st.markdown("**관점별 독립 판정** (합산하지 않음)")
    _pv = pd.DataFrame([{
        "관점": t['label'],
        "점수": "—" if t['score'] is None else f"{t['score']}",
        "판정": t['verdict'],
    } for t in verdict['tabs']])
    st.dataframe(_pv, width='stretch', hide_index=True)
    st.markdown("**한눈에**")
    for s in verdict['summary']:
        st.markdown(f"- {s}")
    st.caption("투자 권유가 아닙니다. 최종 판단과 손익 책임은 투자자 본인에게 있습니다.")

_uk.spacer(28)

# 📈 [종합 인터랙티브 차트 — 판정 근거보다 위. 배너와 같은 실행 가격선을 눈으로 확인]
st.markdown('<div id="nav-chart"></div>', unsafe_allow_html=True)
st.markdown(f"### [{resolved_name}] 종합 차트")
try:
    import chart_pro as _cp
    _chart_html = _cp.build_chart_html(
        tech_df, four_scores, name=resolved_name, unit_str=unit_str,
        theme=st.session_state.get('ui_theme', 'dark'),
        user_avg=(user_entry_price if user_entry_price and user_entry_price > 0
                  else None))
    # st.components.v1.html 은 2026-06-01 제거 예정이었고 그 날짜가 이미
    # 지났다 — 스트림릿을 올리는 순간 차트가 통째로 사라진다. 같은 iframe
    # 임베드인 st.iframe 으로 바꾼다 (HTML 문자열도 그대로 받는다).
    # 이 HTML 은 우리가 만든 것이고 외부 입력을 넣지 않는다.
    st.iframe(_chart_html, height=880)
    st.caption("휠 확대·드래그 이동 · 상단 체크박스로 지표 켜고 끄기. "
               "실행 가격선(추천 매수가·1·2차 목표가·손절가·TDST)은 위 배너와 같은 숫자입니다. "
               "차트 데이터는 이 화면 안에만 있고 외부로 전송되지 않습니다.")
except Exception as _cp_err:
    st.caption(f"종합 차트를 그리지 못했습니다: {_cp_err}")

_uk.spacer(28)

# ── 약세 국면 과매도 반등 — 조건부 참고 (라운드 8 채택) ────────────────────
# 점수·게이트·산식은 건드리지 않는다. 이 조건에서 과거 적중률이 높았다는
# 사실만 알려 주는 참고 표시다. 채택 근거는 종목 홀드아웃(본 적 없는 종목
# 164건에서 70.7%)이며, 블라인드 하락장에서는 맞아도 비용 차감 후 손실이
# 났다는 사실을 같은 자리에 함께 적는다 — 유리한 절반만 보여 주지 않는다.
_bear_now = '하락' in str(four_scores.get('market_regime_label') or '')
_rsi_now = four_scores.get('rsi_value')
_bbp_now = four_scores.get('bb_position_pct')
if _bear_now and ((_rsi_now is not None and _rsi_now < 35)
                  or (_bbp_now is not None and _bbp_now < 20)):
    _cond = ('RSI 과매도' if (_rsi_now is not None and _rsi_now < 35)
             else '볼린저 하단')
    _uk.card(
        f"<p style='margin:0 0 8px 0; font-size:15px; font-weight:600; "
        f"color:{_uk.DARK['tx1']};'>하락 국면 + {_cond} — 과거엔 반등이 잦던 "
        f"자리입니다</p>"
        f"<p style='margin:0; font-size:13px; line-height:1.7; "
        f"color:{_uk.DARK['tx2']};'>같은 조건의 과거 사례에서 "
        f"<b>본 적 없는 종목 164건 기준 70.7%</b>가 20거래일 안에 목표에 "
        f"닿았습니다 (하락 국면 평균 58.5%보다 12.2%p 높음).<br>"
        f"다만 <b>실전(안 본 기간) 하락장 13건에서는 맞아도 비용 차감 후 "
        f"평균 −4.03%</b>였습니다 — 맞는 비율은 높지만 이길 때 조금 벌고 질 때 "
        f"크게 잃었다는 뜻입니다. 그래서 이 표시는 매수 신호가 아니라 "
        f"<b>참고</b>이며, 위의 결론과 점수는 이 규칙 때문에 바뀌지 "
        f"않습니다.</p>",
        theme=_theme, accent=_uk.DARK['warn'])
    _uk.spacer(24)

# ── 가늠 AI — 무엇을 가늠했는지 사용자 말로 ────────────────────────────
# 이름만 AI 처럼 보이지 않게, 실제로 잰 것을 전부 펼친다. 계산은 여기서 새로
# 하지 않는다 — 엔진이 낸 값을 모아 번역할 뿐이다(두 개의 진실 금지).
import gaeum_ai as _gai
# 최종 판정(verdict)을 그대로 넘긴다. 스냅샷의 원본 verdict 에는 거부권·
# 최종점수가 없어서, 카드가 '가장 큰 위험요인'으로 거부 조건 대신 상한 사유
# 뭉치를 잘라 보여 주고 있었다 — 화면 위아래가 서로 다른 말을 하던 원인이다.
_g = _gai.build(four_scores, sim_res, verdict, price=realtime_price)
st.markdown("<div id='nav-gaeum'></div>", unsafe_allow_html=True)
_uk.section("가늠 AI", "이 종목을 어떻게 가늠했는지 그대로 보여 드립니다",
            theme=_theme, top=28)
_uk.card(
    f"<p style='margin:0; font-size:17px; line-height:1.7; "
    f"color:{_TOK['tx1']};'>{_uk._esc(_gai.sentence(_g))}</p>",
    theme=_theme, accent='brand')
_uk.spacer(12)


def _pc(v, suf='%'):
    return f"{v:.1f}{suf}" if v is not None else _gai.NA


_uk.stat_tiles([
    {'label': '목표 방향이 먼저 나올 확률', 'value': _pc(_g['tp_first']),
     'sub': '손절선보다 목표에 먼저 닿는 비율', 'tone': 'pos'},
    {'label': '손절선에 먼저 닿을 확률', 'value': _pc(_g['sl_first']),
     'sub': '목표보다 손절에 먼저 닿는 비율', 'tone': 'neg'},
    {'label': '기간 안에 어느 쪽도 못 닿을 확률', 'value': _pc(_g['undecided']),
     'sub': '보유기간이 끝날 때까지 결판 안 남'},
], theme=_theme)
_uk.spacer(12)

_rows_g = [
    ('예상 보유기간',
     (f"{_g['hold_days']}거래일" if _g.get('hold_days') else _gai.NA)),
    ('비슷했던 과거 사례',
     (f"{_g['sample_n']:,}건" if _g.get('sample_n') else '찾지 못함')),
    ('이 점수대의 실제 성적 (안 본 사례)',
     (f"{_g['oos_hit']:.0f}% · {_g['oos_n']:,}건 기준"
      if _g.get('oos_hit') is not None else _gai.NA)),
    ('95% 신뢰구간',
     (f"{_g['ci_low']:.0f}% ~ {_g['ci_high']:.0f}%"
      if _g.get('ci_low') is not None else _gai.NA)),
    ('신뢰도', str(_g.get('confidence') or _gai.NA),
     ('pos' if _g.get('confidence') == '높음'
      else 'warn' if _g.get('confidence') in ('낮음', '판단 불가') else '')),
]
if _g.get('price_low') and _g.get('price_high'):
    _rows_g.insert(0, ('기대 가격 범위 (10~90분위)',
                       f"{_g['price_low']:,.0f} ~ {_g['price_high']:,.0f}원"))
_uk.rows(_rows_g, theme=_theme, title='가늠한 값')

if _g.get('risk'):
    _uk.spacer(12)
    _uk.card(
        f"<p style='margin:0 0 6px 0; font-size:13px; color:{_TOK['tx3']};'>"
        f"가장 큰 위험요인</p>"
        f"<p style='margin:0; font-size:15px; line-height:1.65; "
        f"color:{_TOK['tx1']};'>{_uk._esc(_g['risk'])}</p>",
        theme=_theme, accent='warn')

_uk.spacer(12)
_lim_html = ''.join(
    f"<li style='margin:0 0 6px 0;'>{_uk._esc(x)}</li>" for x in _g['limits'])
_uk.card(
    f"<p style='margin:0 0 8px 0; font-size:13px; color:{_TOK['tx3']};'>"
    f"지금 판단의 한계</p>"
    f"<ul style='margin:0; padding-left:18px; font-size:15px; line-height:1.7; "
    f"color:{_TOK['tx2']};'>{_lim_html}</ul>", theme=_theme)

# ── 모델 검증 반영 (사용자 요구: 검증이 판단에 어떻게 쓰이는지 보여라) ────
# 검증 결과를 화면에만 띄우고 판단에 안 쓰면 그건 장식이다. 실제로 이번
# 판단에 걸린 게이트·상한·표본을 그대로 적는다. 감사 결과는
# scripts/validation_linkage_audit.py 로 언제든 다시 확인할 수 있다.
_uk.spacer(20)
_cb_v = four_scores.get('calibration_band') or {}
_vd_v = snap.get('verdict') or {}
_rows_v = [
    ('운영 모델 버전', _VER_NOW['model']),
    ('점수 산식 · 룰북', f"{_VER_NOW['scoring']} · {_VER_NOW['rulebook']}"),
]
if _cb_v.get('n'):
    _rows_v.append((
        f"이 점수대({_cb_v.get('lo')}~{_cb_v.get('hi')}점)의 표본외 성적",
        f"{_cb_v.get('hit_rate', 0):.0f}% · {_cb_v['n']:,}건"
        + (f" · 하한 {_cb_v['wilson_low']:.0f}%"
           if _cb_v.get('wilson_low') is not None else ''),
        'pos' if (_cb_v.get('wilson_low') or 0) >= 55 else 'warn'))
else:
    _rows_v.append(('이 점수대의 표본외 성적', '표본 부족 — 판단에 반영하지 않음',
                    'warn'))
_bzb_v = ((_gi_calib or {}).get('splits') or {}).get('buy_zone') or {}
_blv = _bzb_v.get('blind') or {}
if _blv.get('n'):
    _rows_v.append(('추천 신호의 실전 성적 (안 본 기간)',
                    f"{_blv['hit_rate']:.0f}% · {_blv['n']:,}건"))
_rows_v.append(('비슷했던 과거 사례',
                f"{sim_res.get('match_count', 0):,}건 · "
                f"{sim_res.get('confidence_grade', '—')}"))
# 이번 판단에 실제로 걸린 게이트·상한을 그대로 적는다
_gates_v = []
if _vd_v.get('cap_applied') and four_scores.get('gate_reason'):
    _gates_v.append(str(four_scores['gate_reason'])[:90])
for _vt in (_vd_v.get('vetoes') or [])[:2]:
    _gates_v.append(str(_vt)[:90])
_rows_v.append(('검증 때문에 걸린 제한',
                (f"{len(_gates_v)}건 적용" if _gates_v else '없음'),
                'warn' if _gates_v else 'pos'))
_uk.rows(_rows_v, theme=_theme, title='모델 검증 반영 — 이번 판단에 쓰인 근거')
if _gates_v:
    _uk.note('적용된 제한: ' + ' / '.join(_gates_v), theme=_theme)
_uk.note(
    "검증이 판단에 쓰이는 방식: ① 점수대별 표본외 적중률이 낮으면 최종점수에 "
    "상한이 걸립니다 ② 유효표본이 모자라면 확률을 표시하지 않습니다 "
    "③ 비용 차감 후 기대수익이 0 이하면 신규 매수를 막습니다 "
    "④ 자산 유형(주식·ETF·레버리지)별로 다른 기준을 씁니다. "
    "아직 연결되지 않은 것도 있습니다 — 국면별 엔진 제한과 전략별 가중치 "
    "조정은 미구현이며 주요 이슈에 등록돼 있습니다.", theme=_theme)

# ── 엔진들은 서로 뭐라고 하나 (라운드 10) ──────────────────────────────
# 사용자 요구: "최종 결론에는 각 엔진의 판단을 보여주세요."
# 단, 이 엔진들은 **채택되지 않았다** — 6개 전부 블라인드에서 현행보다
# 나빴다. 그래서 판단에 반영하지 않고, '다른 원리는 뭐라고 하는지' 참고로만
# 보여 준다. 신뢰도 칸에는 그 엔진의 실제 블라인드 성적을 적는다.
try:
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           '.portfolio', 'engine_bakeoff.json'),
              encoding='utf-8') as _ef:
        _bake = json.load(_ef)
except Exception:
    _bake = None
if _bake and _bake.get('engines'):
    _uk.spacer(20)

    def _eng_says(key):
        """이 종목에 대해 그 엔진이라면 뭐라고 할지 — 원장과 같은 규칙으로."""
        _m10 = bool(four_scores.get('m10_above'))
        _rsi = four_scores.get('rsi_value')
        _bbp = four_scores.get('bb_position_pct')
        _rp = four_scores.get('range_position_pct') or price_pos.get('pct')
        _v = four_scores.get('vol_20')
        _sc = int(four_scores.get('final_action_score') or 0)
        if key == 'base':
            return _sc >= 58
        if key == 'tsmom':
            return _m10 and _sc >= 50
        if key == 'meanrev':
            return ((_rsi is not None and _rsi < 40)
                    or (_bbp is not None and _bbp < 25)) and _sc >= 45
        if key == 'volbreak' or key == 'lowvol':
            return (_v is not None and _v < 0.020) and _sc >= 55
        if key.startswith('score'):
            try:
                return _sc >= int(key[5:])
            except ValueError:
                return None
        if key.startswith('tsmom'):
            try:
                return _m10 and _sc >= int(key[5:])
            except ValueError:
                return None
        if key.startswith('meanrev'):
            return ((_rsi is not None and _rsi < 40)
                    or (_bbp is not None and _bbp < 25))
        if key in ('valuezone', 'safezone'):
            _z = str(four_scores.get('entry_zone_label')
                     or (snap.get('verdict') or {}).get('entry_zone') or '')
            _kw = '이하' if key == 'valuezone' else '안전마진'
            return (_sc >= 55 and _kw in _z) if _z else None
        return None

    _rows_e = []
    _base_e = _bake.get('baseline') or {}
    if _base_e.get('blind'):
        _say0 = _eng_says('base')
        _rows_e.append(('현행 종합점수',
                        ('산다' if _say0 else '관망')
                        + f" · 실전 적중 {_base_e['blind']['hit']:.0f}%",
                        'pos' if _say0 else ''))
    # 실전 비용후가 좋은 순으로 상위 3개만 — 스물네 줄을 늘어놓으면 안 읽힌다
    _cands = sorted(
        ((k, v) for k, v in (_bake.get('engines') or {}).items()
         if (v.get('blind') or {}).get('hit') is not None
         and (v['blind'].get('n') or 0) >= 30),
        key=lambda kv: -(kv[1]['blind'].get('net') or -99))[:3]
    for _k, _e in _cands:
        _bl = _e['blind']
        _say = _eng_says(_k)
        _lab = ('산다' if _say is True else '관망' if _say is False
                else '판단 보류')
        _rows_e.append((str(_e.get('desc') or _k),
                        f"{_lab} · 실전 적중 {_bl['hit']:.0f}% (n={_bl['n']})",
                        'pos' if _say is True else ''))
    _uk.rows(_rows_e, theme=_theme,
             title='다른 원리는 뭐라고 하나 — 참고 (판단에는 반영하지 않습니다)')
    _uk.note(
        "이 엔진들은 채택되지 않았습니다. 6개 후보를 같은 데이터로 겨뤄 봤고 "
        "전부 실전(안 본 기간)에서 현행보다 나빴습니다 — 특히 눌림 되돌림은 "
        "연습에서 가장 좋았는데(67%) 실전에서 가장 나빴습니다(31%). "
        "연습에서 좋을수록 실전에서 더 무너진다는 뜻이라, 여기 보이는 판단이 "
        "엇갈린다고 해서 현행 결론을 뒤집지 마세요. 상세: 모델 성적 화면.",
        theme=_theme)

# ── 얼마나 먹을 것인가 — 무릎·어깨·머리 (라운드 9 실측) ────────────────
# 사용자 요구: "확률로 몇 프로 정도 먹을건지 정해야 한다. 머리도 발도 아니고
# 무릎에서." 목표를 높이면 폭은 커지지만 닿을 확률이 떨어진다 — 그 교환을
# 숫자로 그어 준다.
try:
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           '.portfolio', 'target_policy.json'),
              encoding='utf-8') as _tf:
        _tp_pol = json.load(_tf)
except Exception:
    _tp_pol = None
if _tp_pol and (_tp_pol.get('splits') or {}).get('valid'):
    _uk.spacer(20)
    _steps = _tp_pol['splits']['valid']['steps']
    _rec = _tp_pol.get('recommended') or {}
    _rows_t = []
    for _s in _steps:
        _tone = ('pos' if _s['zone'] == '어깨'
                 else 'warn' if _s['zone'] == '머리' else '')
        _rows_t.append((f"+{_s['target_pct']:.0f}% 목표",
                        f"{_s['reach_rate']:.0f}% 도달 · {_s['zone']}", _tone))
    _uk.rows(_rows_t, theme=_theme,
             title='얼마에 팔 것인가 — 목표별 도달 확률 (매수권 사례 실측)')
    _uk.note(
        f"무릎(자주 닿지만 얇다) · 어깨(폭과 확률의 균형) · 머리(대부분 못 닿는다). "
        f"실측상 어깨는 "
        f"{_rec.get('range_pct', [3, 5])[0]:.0f}~{_rec.get('range_pct', [3, 5])[1]:.0f}% "
        f"구간입니다. 이 종목의 1차 목표도 그 안에 들어오도록 잡습니다 — "
        f"더 높은 목표는 기대값이 오히려 줄어듭니다.", theme=_theme)

st.markdown("<div id='nav-basis'></div>", unsafe_allow_html=True)
# 🎯 [판정 근거 상세 — 시간축 3단계 정리보다 위에 배치. 실행 가격은 위 배너 한 곳에서만 표기]
action_bg_color = "#161D2A"

st.markdown(f'''
<div style="background: {action_bg_color}; padding: 20px; border-radius: 12px; margin-bottom: 20px; ">
<div style="margin-bottom:20px;">
    <h3 style="margin:0; color:#F3F6FA;">판정 근거 상세</h3>
    <p style="margin:4px 0 0 0; color:#9DAABC; font-size:13px;">종합 결론·점수·실행 가격 기준(권장 매수가/1차 목표가/손절가)은 화면 맨 위 배너에 있습니다. 여기서는 그 근거만 봅니다.</p>
</div>

<div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap:15px; margin-bottom:16px;">
<div style="background:#1C2635; padding:16px; border-radius:8px; border-left: 4px solid #4C8DFF;">
    <h4 style="color:#F3F6FA; margin:0 0 8px 0;">신뢰도 통제 상한</h4>
    <p style="color:#9DAABC; margin:2px 0; font-size:15px;">- 분석 신뢰도: {four_scores.get('analysis_confidence', 0)}점</p>
    <p style="color:#9DAABC; margin:2px 0; font-size:15px;">- 전략 품질: {fmt_num(four_scores.get('strategy_quality_score'), suffix='점', na='미검증')}</p>
    <p style="color:#9DAABC; margin:2px 0; font-size:15px;">- Blind Test: {four_scores.get('blind_test_status', '미수행')}</p>
    <p style="color:#F2B84B; margin:8px 0 2px 0; font-size:15px; font-weight:bold;">- 최종점수 상한 캡: {four_scores.get('sq_cap', 100)}점</p>
</div>
</div>

<div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap:15px;">
<div style="background:#1C2635; padding:16px; border-radius:8px;">
    <h4 style="color:#F3F6FA; margin:0 0 8px 0;">⏱️ DeMARK 신호</h4>
    <p style="color:#35C98B; margin:2px 0; font-size:15px;">- Bullish: {four_scores.get('demark_bullish_score', 0)}점</p>
    <p style="color:{_TOK['up']}; margin:2px 0; font-size:15px;">- Bearish: {four_scores.get('demark_bearish_score', 0)}점</p>
    <p style="color:#9DAABC; margin:2px 0; font-size:15px;">- 방향: {four_scores.get('demark_direction_text', '중립')}</p>
</div>

<div style="background:#1C2635; padding:16px; border-radius:8px;">
    <h4 style="color:#F3F6FA; margin:0 0 8px 0;">확인 지표</h4>
    <p style="color:#9DAABC; margin:2px 0; font-size:15px;">- TDST: {four_scores.get('tdst_support_str', '')} / {four_scores.get('tdst_resist_str', '')}</p>
    <p style="color:#9DAABC; margin:2px 0; font-size:15px;">- Bollinger: {four_scores.get('bb_state', '산출 불가')} (밴드 내 {fmt_num(four_scores.get('bb_position_pct'), '.0f', '%')})</p>
    <p style="color:#9DAABC; margin:2px 0; font-size:15px;">- Williams %R: {fmt_num(four_scores.get('williams_r_value'), '.0f')}</p>
    <p style="color:#9DAABC; margin:2px 0; font-size:15px;">- RSI: {fmt_num(four_scores.get('rsi_value'), '.0f')}</p>
</div>
</div>

<div style="background:#1C2635; padding:16px; border-radius:8px; margin-top:16px;">
<h4 style="color:#F3F6FA; margin:0 0 8px 0;">최종 근거</h4>
<p style="color:#9DAABC; margin:0; line-height:1.5; font-size:15px;">{four_scores.get('final_action_explain', '')}</p>
</div>
</div>
''', unsafe_allow_html=True)

_zone = four_scores.get('entry_zone', four_scores.get('chase_buy_status'))
_bem_str = fmt_num(four_scores.get('buy_entry_max'), suffix='원')
if _zone == "판정 불가":
    st.warning("**[진입 판정 불가]**: 적정가 신뢰도가 기준에 미달하여 권장 매수가를 산출하지 못했습니다. "
               "현재가가 적정 진입구간 안인지 판단할 수 없으므로 신규 진입을 권하지 않습니다.")
elif _zone == "안전마진 확보":
    st.success(f"**[안전마진 확보]**: 현재가({curr_price:,.0f}원)가 권장 매수가({_bem_str}) 이하입니다.")
elif _zone == "적정가 이하 (안전마진 미확보)":
    st.info(f"**[안전마진 미확보]**: 현재가({curr_price:,.0f}원)는 적정가 아래이지만 "
            f"권장 매수가({_bem_str})보다는 높습니다. 안전마진 확보 전까지 분할 진입은 보류를 권장합니다.")
elif _zone:
    st.error(f"**[{_zone}]**: 현재가({curr_price:,.0f}원)가 적정가"
             f"({fmt_num(four_scores.get('displayed_fair_value'), suffix='원')})를 초과했습니다. "
             f"신규 추격매수보다 눌림목 또는 지지선 안착 확인을 권장합니다.")

if four_scores.get('contradiction_detected', False):
    reasons_str = " / ".join(four_scores.get('contradiction_reasons', []))
    st.error(f"**[무결성 게이트 발동 — 재검토 필요]**: 이 종목에서 데이터 모순이 탐지되었습니다. 추천 결과를 신뢰하기 전에 아래 사유를 확인하세요.\n\n**탐지 사유**: {reasons_str}")

_uk.spacer(28)

# ── 🌐 시장·글로벌·뉴스 컨텍스트 — 이 종목만 보지 않고 판을 함께 본다 ─────────
_mkt_ctx = snap.get('market_context') or {}
st.markdown('<div id="nav-context"></div>', unsafe_allow_html=True)
st.markdown(f"### [{resolved_name}] 시장·글로벌·뉴스 컨텍스트")
st.caption("이 판이 나쁠 때는 종목 점수가 좋아도 최종 점수에 상한이 걸립니다. "
           "좋아 보이는 뉴스로 점수를 **올리지는 않습니다** — 뉴스 해석은 사람이 합니다.")

_ctx_c1, _ctx_c2 = st.columns([1, 1])
with _ctx_c1:
    _dom = _mkt_ctx.get('domestic') or {}
    if _dom.get('available'):
        _reg_icon = {"BULL_STRONG": "🟢", "BULL_MILD": "🟡",
                     "SIDEWAYS": "⚪", "BEAR_PANIC": "🔴"}.get(_dom.get('regime_code'), "⚪")
        st.markdown(f"**{_reg_icon} 상장시장 국면 — {_dom.get('market')}**")
        st.markdown(f"{_dom.get('regime_label')}")
        st.caption(_dom.get('basis', '') + " · " + _dom.get('source', ''))
    else:
        st.markdown(f"**상장시장 국면 — {_mkt_ctx.get('market', '')}**")
        st.caption("미수신 — " + str(_dom.get('reason', '지수 데이터 없음')))

    # 국내 지수 상세 — 코스피·코스닥 이격도·최근 등락·52주 위치 (전부 일봉 실계산)
    try:
        import market_context as _mc_dd
        _dd_rows = []
        for _mk in ('KOSPI', 'KOSDAQ'):
            _dd = _mc_dd.fetch_domestic_detail(engine_init, _mk)
            if _dd.get('available'):
                _dd_rows.append({
                    "지수": _mk,
                    "현재": f"{_dd['price']:,.2f}",
                    "20일선 이격": f"{_dd['disp20']:+.1f}%",
                    "60일선 이격": f"{_dd['disp60']:+.1f}%",
                    "5일 등락": fmt_pct(_dd.get('chg5')),
                    "20일 등락": fmt_pct(_dd.get('chg20')),
                    "52주 위치": (f"{_dd['pos52']:.0f}%"
                                if _dd.get('pos52') is not None else "—"),
                })
        if _dd_rows:
            st.dataframe(pd.DataFrame(_dd_rows), width='stretch',
                         hide_index=True)
            st.caption("이격 = 현재가÷이동평균−1 · 52주 위치 = 저점 0%~고점 100% "
                       "구간에서의 현재 위치. 전부 일봉 실계산이며 해석을 덧붙이지 "
                       "않습니다.")
    except Exception:
        pass

    _glob = _mkt_ctx.get('global') or {}
    if _glob:
        _grows = []
        for _gk in ('sp500', 'nasdaq', 'vix', 'usdkrw'):
            _gv = _glob.get(_gk) or {}
            if _gv.get('available'):
                _grows.append({
                    "지표": _gv['label'],
                    "현재": f"{_gv['price']:,.2f}",
                    "20일 변화": fmt_pct(_gv.get('chg20_pct')),
                    "60일선": "위" if _gv.get('above_sma60') else "아래",
                })
            else:
                _grows.append({"지표": _gv.get('label', _gk), "현재": "미수신",
                               "20일 변화": "—", "60일선": "—"})
        st.dataframe(pd.DataFrame(_grows), width='stretch', hide_index=True)
        st.caption("출처: Yahoo Finance 일봉 (10분 캐시)")
    _gw = _mkt_ctx.get('global_warnings') or []
    if _gw:
        st.warning("**글로벌 위험 신호 " + str(len(_gw)) + "건**\n\n" +
                   "\n".join(f"- {w}" for w in _gw) +
                   ("\n\n→ 2건 이상이면 종합 점수에 상한이 걸립니다." if len(_gw) < 2
                    else "\n\n→ **종합 점수 상한 적용됨** (위 산식표의 상한 사유 참조)"))

with _ctx_c2:
    _news = _mkt_ctx.get('news') or {}
    _nfl = _mkt_ctx.get('news_flags') or {}
    if _news.get('available'):
        st.markdown(f"**실제 종목 뉴스 (최근 {len(_news.get('items', []))}건)**")
        if _nfl.get('risk_count'):
            st.error(f"제목에 확인이 필요한 낱말이 있는 기사 **{_nfl['risk_count']}건** — "
                     "종합 점수에 상한이 걸렸습니다. 기사 원문을 직접 확인하세요.")
        # 관련성 뱃지 — 제목에 종목명이 실제로 들어간 기사만 '직접'.
        # 나머지는 업종·시장 참고 기사다 (낱말 일치만 — 해석하지 않는다).
        _nm_keys = [resolved_name]
        if len(resolved_name) >= 4:
            _nm_keys.append(resolved_name[:3])
        _direct_items = [_it for _it in (_news.get('items') or [])
                         if any(k in str(_it.get('title', '')) for k in _nm_keys)]
        _indirect_items = [_it for _it in (_news.get('items') or [])
                           if _it not in _direct_items]
        if not _direct_items:
            st.caption(f"제목에 '{resolved_name}'이(가) 직접 언급된 기사가 없습니다 "
                       "— 아래는 업종·시장 참고 기사입니다.")

        def _render_news_item(_it, direct):
            _flag = " 🔴" + "·".join(_it['risk_hits']) if _it.get('risk_hits') else ""
            _tag = "" if direct else " `참고`"
            _link = (f"[{_it['title']}]({_it['url']})" if _it.get('url')
                     else _it['title'])
            st.markdown(f"- {_link}{_tag}{_flag}")
            _meta_line = f"{_it.get('press', '')} · {_it.get('datetime', '')}"
            if _it.get('related_count'):
                _meta_line += f" · 연관기사 {_it['related_count']}건"
            st.caption("  " + _meta_line)
            if _it.get('related'):
                with st.expander(f"연관 뉴스 {_it['related_count']}건 보기"):
                    for _r in _it['related'][:8]:
                        _rl = (f"[{_r['title']}]({_r['url']})" if _r.get('url')
                               else _r['title'])
                        st.markdown(f"- {_rl}  \n  "
                                    f"{_r.get('press', '')} · {_r.get('datetime', '')}")

        _n_direct_shown = len(_direct_items[:5])
        for _it in _direct_items[:5]:
            _render_news_item(_it, True)
        for _it in _indirect_items[:max(1, 6 - _n_direct_shown)]:
            _render_news_item(_it, False)
        st.caption("출처: " + str(_news.get('source', '')) +
                   " — 제목·언론사·시각을 원문 그대로 표시하며, 기사 내용을 요약·해석해 "
                   "만들어 내지 않습니다. 위험 표시는 제목의 낱말 일치일 뿐입니다.")
    else:
        st.markdown("**실제 종목 뉴스**")
        st.caption("미수신 — " + str(_news.get('reason', '')))

for _note in (_mkt_ctx.get('notes') or []):
    st.caption("ℹ️ " + str(_note))

# ── 기업 공시 — 원문 나열만 (해석·요약 생성 금지, 점수 미반영) ──────────────
try:
    import market_context as _mc_disc
    _disc = _mc_disc.fetch_stock_disclosures(target_ticker, limit=8)
except Exception as _de:
    _disc = {'available': False, 'items': [], 'reason': str(_de)}
with st.expander(f"최근 기업 공시 ({len(_disc.get('items', []))}건) — 원문 제목 그대로",
                 expanded=False):
    if _disc.get('available'):
        for _d in _disc['items']:
            st.markdown(f"- [{_d['title']}]({_d['url']})  \n"
                        f"  <span style='font-size:12px; color:#9DAABC;'>"
                        f"{_d['provider']} · {_d['date']}</span>",
                        unsafe_allow_html=True)
        st.caption(f"출처: {_disc.get('source')} — 공시 내용을 요약·해석해 만들어 내지 "
                   "않으며, 점수에 자동 반영하지 않습니다. 원문을 직접 확인하세요.")
    else:
        st.caption("공시 미수신 — " + str(_disc.get('reason', '')))

# ── 이 컨텍스트가 퀀트 점수를 얼마나 움직였는지 (상한과는 별개의 산식 반영분) ──
_rgd = four_scores.get('market_regime_detail') or {}
with st.expander("이 시장·뉴스가 퀀트 점수를 얼마나 움직였나 (산식 반영분)", expanded=False):
    st.caption("아래는 **점수 상한과 별개로**, 시장·글로벌·뉴스가 점수 산식 안에서 "
               "차지한 몫입니다. 좋은 뉴스로 점수를 올리는 경로는 없습니다 — 위험 낱말이 "
               "있을 때만 깎입니다.")
    _rows_ctx = []
    if four_scores.get('market_regime_excluded'):
        st.warning("시장 국면 점수를 산출하지 못해 **매매 적합도에서 이 항목을 빼고** "
                   "나머지 항목으로 재정규화했습니다 — 못 받은 값을 중립 50점으로 "
                   "메우지 않습니다. 사유: " + str(_rgd.get('reason', '지수·글로벌 미수신')))
    else:
        _rows_ctx.append({
            "항목": "시장 국면 (매매 적합도 안)",
            "점수": fmt_num(four_scores.get('market_regime_score'), '.1f'),
            "가중치": f"{float(four_scores.get('market_regime_weight') or 0) * 100:.0f}%",
            "구성": (f"국내 {fmt_num(_rgd.get('domestic_score'), '.0f')} × "
                     f"{float(q_engine.W_MARKET_CTX.get('weight_domestic_regime', 0.6)) * 100:.0f}% + "
                     f"글로벌 {fmt_num(_rgd.get('global_score'), '.0f')} × "
                     f"{float(q_engine.W_MARKET_CTX.get('weight_global_risk', 0.4)) * 100:.0f}%"
                     + ("  (한쪽 미수신 → 재정규화)" if _rgd.get('renormalized') else "")),
        })
    _rows_ctx.append({
        "항목": "뉴스 위험 (리스크 안전성 안)",
        "점수": fmt_num(four_scores.get('news_risk_score'), '.1f'),
        "가중치": f"{float(four_scores.get('news_risk_weight') or 0) * 100:.0f}%",
        "구성": str(four_scores.get('news_risk_note', '')),
    })
    st.dataframe(pd.DataFrame(_rows_ctx), width='stretch', hide_index=True)

    if _rgd.get('global_hits'):
        st.markdown("**글로벌 감점 내역** (규칙집 [RULES_MARKET_CONTEXT] 기준)")
        st.dataframe(pd.DataFrame([{"사유": t, "감점": f"-{p:.0f}점"}
                                   for t, p in _rgd['global_hits']]),
                     width='stretch', hide_index=True)
    if _rgd.get('global_missing'):
        st.caption("미수신 지표(감점도 가점도 하지 않음): " + ", ".join(_rgd['global_missing']))
    if four_scores.get('context_cap', 100) < 100:
        st.markdown(f"위 반영분과 **별개로**, 상한 규칙이 최종 점수를 "
                    f"**{four_scores.get('context_cap')}점 이하**로 제한했습니다.")

# ── 🧪 모델 성과 — 적중률을 과장하지 않는 감사 화면 (calibration.json 실측) ──
st.markdown('<div id="nav-perf"></div>', unsafe_allow_html=True)
_perf_cal = _load_calibration_meta()
if _perf_cal.get('total_cases'):
    st.markdown("### 모델 자체 점검")
    st.caption(f"과거 기준일 리플레이 **{_perf_cal['total_cases']:,}건** · "
               f"규칙집 {_perf_cal.get('rulebook_version', '—')} · "
               "시간 분할: 학습 <2025-07 / 검증 ~2026-01 / 블라인드 ≥2026-02 "
               "(블라인드는 보고 전용 — 모델 선택에 쓰지 않습니다)")
    with st.expander("성과 분해 · 점수대 캘리브레이션 · 실패 원인 (펼쳐보기)",
                     expanded=False):
        _sp_p = _perf_cal.get('splits') or {}
        _rows_sp = []
        for _k, _lab in (('train', '학습(표본내)'), ('valid', '검증(표본외)'),
                         ('blind', '블라인드')):
            _s = _sp_p.get(_k) or {}
            if not _s.get('n'):
                continue
            _rows_sp.append({
                '구간': _lab, '표본': _s['n'],
                '적중률': f"{_s['hit_rate']:.1f}%",
                'Wilson 하한': f"{_s['wilson_low']:.1f}%",
                'Profit Factor': f"{_s['profit_factor']:.2f}",
                '비용 차감 평균수익': f"{_s['avg_return_after_cost']:+.2f}%",
            })
        if _rows_sp:
            st.markdown("**① 시간 분할 성과** — 검증·블라인드가 실력입니다")
            st.dataframe(pd.DataFrame(_rows_sp), width='stretch',
                         hide_index=True)
        _bz_p = (_sp_p.get('buy_zone') or {})
        _rows_bz = []
        for _k, _lab in (('train', '학습'), ('valid', '검증'), ('blind', '블라인드')):
            _s = _bz_p.get(_k) or {}
            if not _s.get('n'):
                continue
            _rows_bz.append({
                '구간': _lab, '표본': _s['n'],
                '적중률': f"{_s['hit_rate']:.1f}%",
                'Wilson 하한': f"{_s['wilson_low']:.1f}%",
                '비고': '표본 부족 — 확대 축적 중' if _s['n'] < 30 else '',
            })
        if _rows_bz:
            st.markdown("**② 매수권(60점 이상) 신호만** — 실제 추천이 나가는 구간")
            st.dataframe(pd.DataFrame(_rows_bz), width='stretch',
                         hide_index=True)
        _bands_p = [b for b in (_perf_cal.get('bands') or []) if b.get('n')]
        if _bands_p:
            st.markdown("**③ 점수대별 실측 적중률** — 점수가 확률로 이어지는가")
            st.dataframe(pd.DataFrame([{
                '점수대': f"{b['lo']}~{b['hi']}", '표본': b['n'],
                '적중률': f"{b['hit_rate']:.1f}%",
                'Wilson 하한': (f"{b['wilson_low']:.1f}%"
                              if b.get('wilson_low') is not None else '—'),
                '평균수익': (f"{b['avg_return']:+.2f}%"
                          if b.get('avg_return') is not None else '—'),
                '비고': '표본 부족' if b['n'] < 30 else '',
            } for b in _bands_p]), width='stretch', hide_index=True)
        _fails_p = _perf_cal.get('failure_classes') or []
        if _fails_p:
            st.markdown("**④ 실패 원인 분류** — 어디서 잃었는가 (손실 기여 순)")
            st.dataframe(pd.DataFrame([{
                '실패 유형': f['class'], '건수': f['n'],
                '누적 손실 기여': f"{f['total_loss']:+.1f}%p",
            } for f in _fails_p]), width='stretch', hide_index=True)
        _warn_lines = []
        _v_p, _b_p = _sp_p.get('valid') or {}, _sp_p.get('blind') or {}
        if (_v_p.get('hit_rate') is not None and _b_p.get('hit_rate') is not None
                and _v_p['hit_rate'] - _b_p['hit_rate'] >= 10):
            _warn_lines.append(
                f"검증({_v_p['hit_rate']:.1f}%)과 블라인드({_b_p['hit_rate']:.1f}%) "
                "적중률 괴리가 큽니다 — 특정 장세 편중·과최적화 가능성을 감시 중입니다.")
        _bzb_p = (_bz_p.get('blind') or {})
        if (_bzb_p.get('n') or 0) < 30:
            _warn_lines.append(
                f"고신뢰(60점+) 블라인드 표본이 {_bzb_p.get('n', 0)}건으로 부족합니다 "
                "— 90% 목표 달성 여부는 표본 100건 이상에서 판정합니다.")
        _note_p = str(_perf_cal.get('note') or '')
        if _note_p:
            _warn_lines.append(_note_p)
        if _warn_lines:
            st.warning("**반드시 함께 읽어야 하는 한계**\n\n"
                       + "\n".join(f"- {w}" for w in _warn_lines))

# ── 📚 케이스 스터디 — 리플레이 원장을 직접 뒤져본다 (필터·사례 상세) ─────────
st.markdown('<div id="nav-cases"></div>', unsafe_allow_html=True)
_ledger_df = _load_case_ledger()
if _ledger_df is not None:
    st.markdown("### 과거 판단 하나하나 열어 보기")
    _lg_last = str(_ledger_df['date'].max())[:10] if 'date' in _ledger_df.columns else '—'
    st.caption(f"독립 사례 **{len(_ledger_df):,}건** (가상 백테스트 원장 그대로 — "
               "당시 점수·판정·이후 실제 경로·실패 원인). 필터로 직접 확인하세요.  \n"
               f"🔄 **운영 상태**: 마지막 케이스 기준일 {_lg_last} · "
               f"1단계 3,000·2단계 5,000 달성 — 다음 목표 **10,000건**. 축적은 중단하지 않습니다. "
               "동일 종목·인접 기준일 중복은 25봉 간격 규칙으로 통제합니다.")

    # ── 지속 개선 파이프라인 상태 (실전 추천 추적 계층 — improvement DB) ────
    try:
        from improvement import case_tracker as _imp_ct
        from improvement.daily_pipeline import last_run as _imp_last
        from improvement.database import get_connection as _imp_conn
        from improvement.database import initialize_database as _imp_init
        _imp_init()
        _ic = _imp_conn()
        try:
            _lr = _imp_last(_ic)
            _n_open_imp = len(_imp_ct.open_cases(_ic))
            _n_all_imp = _ic.execute(
                "SELECT COUNT(*) FROM prediction_cases").fetchone()[0]
        finally:
            _ic.close()
        _lr_txt = (f"{str(_lr['started_at'])[:16]} ({_lr['status']} · "
                   f"추가 {_lr['added_cases']} · 확정 {_lr['resolved_cases']})"
                   if _lr else "아직 실행 이력 없음")
        _pc1, _pc2 = st.columns([3, 1])
        with _pc1:
            st.caption(f"**실전 추천 추적 파이프라인**: 동결 케이스 "
                       f"{_n_all_imp}건 · 결과 확정 대기 {_n_open_imp}건 · "
                       f"마지막 실행 {_lr_txt}. 같은 봉에서 목표·손절이 함께 "
                       "닿으면 성공으로 세지 않습니다 (선도달 확인 불가).")
        with _pc2:
            if st.button("장 종료 후 지금 실행", key="btn_run_improvement",
                         width='stretch'):
                import subprocess as _sp_imp
                with st.spinner("일일 파이프라인 실행 중 (동결→판정→지표→이슈)..."):
                    # encoding 을 안 주면 윈도우 기본(cp949)으로 읽어
                    # 한글 출력에서 UnicodeDecodeError 로 죽는다.
                    # errors='replace' — 로그 한 글자 때문에 실행 결과를
                    # 통째로 잃지 않는다.
                    _rr = _sp_imp.run(
                        [sys.executable,
                         os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      'scripts', 'run_daily_improvement.py')],
                        capture_output=True, text=True, timeout=600,
                        encoding='utf-8', errors='replace')
                st.toast(("파이프라인 완료: " + (_rr.stdout or '').strip()[-120:])
                         if _rr.returncode == 0
                         else ("실행 실패 — " +
                               (_rr.stderr or '').strip()[-120:]))
                st.rerun()
        try:
            if is_remote_exposed():
                st.warning("클라우드 배포에서는 로컬 파일 저장(.portfolio — "
                           "케이스 DB·추천 이력)이 **재배포 시 초기화**될 수 "
                           "있습니다. 장기 축적은 로컬 실행 또는 외부 영속 DB "
                           "연동(운영 문서 §17 검토 항목)으로 운영하세요.")
        except Exception:
            pass
    except Exception as _imp_err:
        st.caption(f"실전 추천 추적 파이프라인 미초기화: {_imp_err}")
    with st.expander("원장 필터·사례 보기 (펼쳐보기)", expanded=False):
        _cf1, _cf2, _cf3, _cf4 = st.columns(4)
        with _cf1:
            _f_split = st.selectbox("시간 분할", ["전체", "train(학습)",
                                    "valid(검증)", "blind(블라인드)"], key="cs_split")
        with _cf2:
            _f_out = st.selectbox("결과", ["전체", "성공(목표 선도달)",
                                  "실패(손절 선도달)", "미도달(만기)"], key="cs_out")
        with _cf3:
            _f_score = st.selectbox("점수대", ["전체", "60점 이상(매수권)",
                                    "55~59", "50~54", "50 미만"], key="cs_score")
        with _cf4:
            _f_reg = st.selectbox("시장 국면", ["전체", "BULL", "NEUTRAL", "BEAR"],
                                  key="cs_regime")
        _cs = _ledger_df
        if _f_split != "전체":
            _cs = _cs[_cs['split'] == _f_split.split('(')[0]]
        if _f_out == "성공(목표 선도달)":
            _cs = _cs[_cs['outcome'] == 'TARGET']
        elif _f_out == "실패(손절 선도달)":
            _cs = _cs[_cs['outcome'] == 'STOP']
        elif _f_out == "미도달(만기)":
            _cs = _cs[~_cs['outcome'].isin(['TARGET', 'STOP'])]
        if _f_score == "60점 이상(매수권)":
            _cs = _cs[_cs['score'] >= 60]
        elif _f_score == "55~59":
            _cs = _cs[(_cs['score'] >= 55) & (_cs['score'] <= 59)]
        elif _f_score == "50~54":
            _cs = _cs[(_cs['score'] >= 50) & (_cs['score'] <= 54)]
        elif _f_score == "50 미만":
            _cs = _cs[_cs['score'] < 50]
        if _f_reg != "전체":
            _cs = _cs[_cs['regime'] == _f_reg]

        if len(_cs) == 0:
            st.info("이 조건에 해당하는 사례가 없습니다 — 필터를 넓혀 보세요.")
        else:
            _n_t = int((_cs['outcome'] == 'TARGET').sum())
            _n_s = int((_cs['outcome'] == 'STOP').sum())
            _cm1, _cm2, _cm3, _cm4 = st.columns(4)
            _cm1.metric("사례 수", f"{len(_cs):,}건", delta_color="off")
            _cm2.metric("성공(목표 선도달)",
                        f"{_n_t / len(_cs) * 100:.1f}%", f"{_n_t}건",
                        delta_color="off")
            _cm3.metric("실패(손절 선도달)",
                        f"{_n_s / len(_cs) * 100:.1f}%", f"{_n_s}건",
                        delta_color="off")
            _cm4.metric("평균 수익률(판정 봉)",
                        f"{_cs['return_pct'].mean():+.2f}%",
                        f"평균 MAE {_cs['mae_pct'].mean():.1f}%",
                        delta_color="off")
            if len(_cs) < 30:
                st.caption("표본이 30건 미만입니다 — 이 비율로 결론을 내리지 마세요.")
            _fail_cs = _cs[_cs['failure_class'].astype(str).str.len() > 0] \
                if 'failure_class' in _cs.columns else _cs.iloc[0:0]
            if len(_fail_cs):
                _fc_top = (_fail_cs.groupby('failure_class')['return_pct']
                           .agg(['count', 'sum']).sort_values('sum'))
                st.markdown("**이 조건에서의 실패 원인** (손실 기여 순)")
                st.dataframe(pd.DataFrame([{
                    '실패 유형': idx, '건수': int(r['count']),
                    '누적 손실': f"{r['sum']:+.1f}%p",
                } for idx, r in _fc_top.iterrows()]),
                    width='stretch', hide_index=True)
            st.markdown("**사례 목록** (최근 50건 — 당시 판정과 이후 실제 경로)")
            _show = _cs.sort_values('date', ascending=False).head(50)
            st.dataframe(pd.DataFrame([{
                '기준일': str(r['date'])[:10], '종목': r['ticker'],
                '국면': r['regime'], '점수': int(r['score']),
                '당시 판정': r['action_title'],
                '결과': {'TARGET': '✅ 목표', 'STOP': '❌ 손절'}.get(
                    r['outcome'], '⏳ 미도달'),
                '수익률': f"{r['return_pct']:+.1f}%",
                '최대이익 MFE': f"{r['mfe_pct']:+.1f}%",
                '최대손실 MAE': f"{r['mae_pct']:+.1f}%",
                '실패 원인': str(r.get('failure_class') or ''),
            } for _, r in _show.iterrows()]),
                width='stretch', hide_index=True)
            st.caption("성공 = 목표가를 손절가보다 먼저 터치. 수익률은 판정 봉 기준, "
                       "MFE/MAE는 보유 구간의 최대 이익/손실입니다. "
                       "블라인드 구간은 모델 선택에 쓰지 않은 순수 검증분입니다.")

# ── 고객센터 — 안 될 때 여기부터 (실제 대처법만, 빈 약속 금지) ───────────────
st.markdown("### 고객센터 — 안 될 때 여기부터")
with st.expander("자주 겪는 문제와 대처법 · 문제 신고 (펼쳐보기)", expanded=False):
    st.markdown("""
**자주 겪는 문제**

| 증상 | 원인 | 대처 |
|---|---|---|
| 스크린샷 인식이 틀림 | OCR이 1↔7 등 숫자를 오독 | 현재가·수익률·평가손익 열이 **함께 보이게** 캡처하면 교차검증이 오독을 걸러냅니다. 미리보기 표에서 직접 수정도 됩니다 |
| 추천 종목이 0개 | 게이트가 전부 차단 — **오류 아님** | 조건 미달이면 추천하지 않는 것이 설계입니다. '제외 사유'를 확인하세요 |
| 지수·시세 미수신 경고 | 네이버·다음 응답 지연 | 잠시 후 새로고침. 미수신 동안은 상한 게이트가 보수적으로 작동합니다 |
| 차트가 안 뜸 | 브라우저 캐시 | 새로고침(Ctrl+F5). 그래도 안 되면 아래로 신고해 주세요 |
| 글자가 안 보임 | 구버전 배포 캐시 | 새로고침 후에도 지속되면 화면 캡처와 함께 신고해 주세요 |
| 보유종목이 사라짐 | 로컬 저장(.portfolio)은 기기별 | 같은 기기·브라우저에서 열어야 합니다. 클라우드 배포에는 저장되지 않습니다 |

**문제 신고** — 화면 캡처와 함께
[GitHub Issues](https://github.com/hwanking/quant-stock-simulator/issues)에 남겨 주세요.
업데이트 내역은 위 '최근 업데이트'에서, 알려진 한계는 '주요 이슈'에서 확인할 수 있습니다.
""")

# ── 무료 언어모델 주간 관찰 — 7일마다 자동 갱신 (관찰 전용·채택은 검증 후) ────
try:
    import llm_watch as _lw
    _lw_data = _lw.get_llm_watch()
except Exception:
    _lw_data = {'models': []}
if _lw_data.get('models'):
    with st.expander(f"무료 언어모델 주간 관찰 ({len(_lw_data['models'])}종 · "
                     f"갱신 {_lw_data.get('fetched_at', '—')})", expanded=False):
        st.caption("공개 API에서 **주 1회 자동 갱신**합니다 (우리 데이터는 아무것도 "
                   "보내지 않는 조회 전용). 여기 나온 모델을 파이프라인에 자동 연결하지 "
                   "않습니다 — 채택은 다른 방법과 똑같이 표본외·블라인드 검증을 통과해야 "
                   "하며, **포트폴리오 정보는 어떤 외부 모델에도 전송하지 않습니다.**"
                   + (" ⚠️ 이번 주 재조회 실패 — 마지막 성공 캐시를 표시 중입니다."
                      if _lw_data.get('stale') else ""))
        st.dataframe(pd.DataFrame([{
            '모델': m['id'], '다운로드': f"{m['downloads']:,}",
            '좋아요': m['likes'], '라이선스': m['license'],
        } for m in _lw_data['models']]), width='stretch',
            hide_index=True)
        st.caption(f"출처: {_lw_data.get('source', '')}")

# ── 📌 판정 기록 — 이 판정이 나중에 맞았는지 스스로 채점하기 위한 원본 ─────────
try:
    import prediction_log as _plog
    if ALLOW_LOCAL_STORE:
        _tp_rec = four_scores.get('target_tech_1st')
        _sl_rec = four_scores.get('stop_loss_price')
        _recorded = _plog.record_prediction({
            'ticker': target_ticker, 'name': resolved_name,
            'date': snap.get('t_ref'), 'price': curr_price,
            'action': verdict.get('action'), 'action_label': verdict.get('headline'),
            'score': verdict.get('score'),
            'target': _tp_rec, 'stop': _sl_rec,
            'horizon_days': 20,
        })
        if _recorded:
            st.caption("오늘 판정을 기록했습니다 — 예측 기간이 지나면 사이드바 "
                       "'판정 성적표'에서 실제 주가와 대조해 채점됩니다.")
except Exception:
    pass

_uk.spacer(28)

# 🚨 [사용자 요청] 뉴스·공시·촉매의 시간축 3단계 분리 분석을 한줄핵심결론 위로 배치
news_tf = engine_init.get_timeframe_news_analysis(target_ticker)
st.caption("ℹ️ 증권사 리서치·IR 원문은 미연동입니다. 아래는 실제 수집한 가격·거래량·게시 투자지표의 관찰과 정량 해석이며, 사건·원인을 추정해 서술하지 않습니다. (실제 뉴스 기사는 위 '시장·글로벌·뉴스 컨텍스트'에 원문 링크로 표시됩니다.)")
st.markdown(f"[{resolved_name}] 가격·지표 관찰의 시간축 3단계 정리")

n1, n2, n3 = st.columns(3)
with n1:
    dd = news_tf['daily_drivers']
    st.markdown(f"""
    <div style='background: #161D2A; padding: 20px; border-radius: 14px; '>
        <h4 style='color: #ff453a !important; margin-top:0;'>1. 오늘의 변동 요인 ({dd.get('date', '2026-07-30')})</h4>
        <p style='font-weight: bold; color: #F3F6FA;'>{dd['title']}</p>
        <p style='font-size: 15px; color: #9DAABC;'>💡 <b>관찰 내용</b>: {dd['impact']}</p>
        <span style='font-size: 13px; color: #9DAABC;'>출처: {dd['source']} | 성향: {dd['sentiment']}</span>
    </div>
    """, unsafe_allow_html=True)

with n2:
    mc = news_tf['medium_catalysts']
    st.markdown(f"""
    <div style='background: #161D2A; padding: 20px; border-radius: 14px; '>
        <h4 style='color: #F2B84B !important; margin-top:0;'>2. 중기 촉매 ({mc.get('timeframe', '1~3개월')})</h4>
        <p style='font-weight: bold; color: #F3F6FA;'>{mc['title']}</p>
        <p style='font-size: 15px; color: #9DAABC;'>💡 <b>정량 해석</b>: {mc['impact']}</p>
        <span style='font-size: 13px; color: #9DAABC;'>출처: {mc['source']} | 성향: {mc['sentiment']}</span>
    </div>
    """, unsafe_allow_html=True)

with n3:
    ln = news_tf['long_narratives']
    st.markdown(f"""
    <div style='background: #161D2A; padding: 20px; border-radius: 14px; '>
        <h4 style='color: #35C98B !important; margin-top:0;'>3. 장기 구조적 서사 ({ln.get('timeframe', '6~12개월')})</h4>
        <p style='font-weight: bold; color: #F3F6FA;'>{ln['title']}</p>
        <p style='font-size: 15px; color: #9DAABC;'>💡 <b>정량 해석</b>: {ln['impact']}</p>
        <span style='font-size: 13px; color: #9DAABC;'>출처: {ln['source']} | 성향: {ln['sentiment']}</span>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<div style='margin-bottom: 12px;'></div>", unsafe_allow_html=True)

# 📌 [사용자 요청] 내 보유 포지션 맞춤 포트폴리오 진단 & 물타기 안전성 계산기
if user_entry_price > 0 and user_quantity > 0:
    eval_val = realtime_price * user_quantity
    cost_val = user_entry_price * user_quantity
    pnl_val = eval_val - cost_val
    pnl_pct = (pnl_val / (cost_val + 1e-8)) * 100.0
    
    # 목표가·손절가 키는 target_tech_1st / stop_loss_price 이다 ('target_price_1st'는 존재하지 않는 키였음)
    tp_1st = four_scores.get('target_tech_1st', realtime_price * 1.05)
    sl_1st = four_scores.get('stop_loss_price', realtime_price * 0.95)

    if user_entry_price >= realtime_price * 1.15:
        user_pos_tag = "머리 가격 (최상투 고점)"
        user_pos_color = "#ff453a"
        user_pos_advice = f"🚨 현재 평단가({user_entry_price:,.0f}원)가 고점 부근입니다. 무분별한 물타기는 위험하며 반등 시 1차 비중 30% 축소를 권장합니다."
    elif user_entry_price >= realtime_price * 1.05:
        user_pos_tag = "어깨 가격 (고점 부근)"
        user_pos_color = "#F2B84B"
        user_pos_advice = f"⚠️ 평단가 대비 손실 구간({pnl_pct:.1f}%)입니다. 20일선 지지 안착 확인 전까지 추가 매수를 유의하세요."
    elif user_entry_price >= realtime_price * 0.95:
        user_pos_tag = "허리 가격 (평균 구간)"
        user_pos_color = "#35C98B"
        user_pos_advice = f"🟢 평단가 부근 형성 중입니다. 20일선 수급 안착 시 현재 보유량을 유지하며 관망합니다."
    elif user_entry_price >= realtime_price * 0.85:
        user_pos_tag = "무릎 가격 (저점 진입)"
        user_pos_color = "#4C8DFF"
        user_pos_advice = f"💎 수익 구간({pnl_pct:+.1f}%)입니다. 1차 목표가({tp_1st:,.0f}원) 도달 시 분할 익절을 고려하세요."
    else:
        user_pos_tag = "발목 가격 (최저점 매수)"
        user_pos_color = "#4C8DFF"
        user_pos_advice = f"🚀 최저가 부근 우수 진입 포지션입니다({pnl_pct:+.1f}%). 잔여 이익을 극대화하세요."

    sma_20_curr = tech_df['sma_20'].iloc[-1]
    
    final_score = four_scores.get('final_quant_score', 50)

    if final_score >= 68:
        add_buy_status = f"🟢 <b>매수 (비중 확대)</b><br><span style='font-size:13px; color:#9DAABC;'>단기 목표가 {tp_1st:,.0f}원 도달 시 익절</span>"
        add_buy_color = "#35C98B"
    elif final_score >= 50:
        add_buy_status = f"🟡 <b>관망 (보유 비중 유지)</b><br><span style='font-size:13px; color:#9DAABC;'>물타기 금지 / {tp_1st:,.0f}원 반등 시 매도</span>"
        add_buy_color = "#F2B84B"
    else:
        add_buy_status = f"🔴 <b>매도 (비중 축소)</b><br><span style='font-size:13px; color:#9DAABC;'>위험 구간 / {sl_1st:,.0f}원 이탈 시 전량 손절</span>"
        add_buy_color = "#ff453a"


    water_msg = ""
    if user_entry_price > tp_1st and realtime_price < tp_1st:
        add_q = max(1, int(user_quantity * (user_entry_price - tp_1st) / (tp_1st - realtime_price)))
        add_cost = add_q * realtime_price
        water_msg = f"<div style='margin-top:16px; background:#1C2635; padding:12px 16px; border-radius:10px; border-left: 4px solid #F2B84B;'><p style='margin:0; font-size:15px; color:#F3F6FA;'>💡 <b>맞춤형 물타기(평단가 인하) 시뮬레이션</b></p><p style='margin:4px 0 0 0; font-size:13px; color:#9DAABC;'>현재가 기준 <b>약 {add_q:,}주 ({add_cost:,.0f}원)</b> 추가 매수 시, 평단가를 AI 1차 목표가(<b>{tp_1st:,.0f}원</b>)로 낮춰 본전 탈출이 가능합니다.</p></div>"
    elif user_entry_price > realtime_price and user_entry_price <= tp_1st:
        water_msg = f"<div style='margin-top:16px; background:#1C2635; padding:12px 16px; border-radius:10px; border-left: 4px solid #35C98B;'><p style='margin:0; font-size:13px; color:#9DAABC;'>💡 현재 평단가가 AI 1차 목표가({tp_1st:,.0f}원)보다 낮아, 본전 탈출을 위한 무리한 추가 물타기 없이 목표가 도달 시 수익 전환이 가능합니다.</p></div>"
    elif user_entry_price > 0:
        water_msg = f"<div style='margin-top:16px; background:#1C2635; padding:12px 16px; border-radius:10px; border-left: 4px solid #4C8DFF;'><p style='margin:0; font-size:13px; color:#9DAABC;'>💡 현재 수익 구간입니다. 신규 매수(불타기) 시 평단가가 높아지므로, 잔여 물량은 보유 유지 및 단기 익절 대응을 권장합니다.</p></div>"
    st.markdown(f"""
    <div style='background: #161D2A; border-radius: 16px; padding: 20px 24px; margin: 12px 0 20px 0;'>
        <div style='display:flex; justify-size:space-between; align-items:center; flex-wrap:wrap; gap:10px;'>
            <h3 style='margin:0; color:{user_pos_color}; font-size:20px;'>내 보유 포지션 맞춤 포트폴리오 진단 & 물타기 안전성 리포트</h3>
            <span style='background:{user_pos_color}; color:#000; padding:4px 16px; border-radius:14px; font-weight:bold; font-size:15px;'>{user_pos_tag}</span>
        </div>
        <div style='display:grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap:12px; margin:16px 0;'>
            <div style='background:#161D2A; padding:12px; border-radius:10px; text-align:center;'>
                <p style='margin:0; font-size:13px; color:#9DAABC;'>내 평균 매수가</p>
                <p style='margin:2px 0 0 0; font-size:20px; color:#F3F6FA; font-weight:bold;'>{user_entry_price:,.0f} 원</p>
            </div>
            <div style='background:#161D2A; padding:12px; border-radius:10px; text-align:center;'>
                <p style='margin:0; font-size:13px; color:#9DAABC;'>보유 수량 / 총 평가금액</p>
                <p style='margin:2px 0 0 0; font-size:17px; color:#F3F6FA; font-weight:bold;'>{user_quantity} 주 ({eval_val:,.0f} 원)</p>
            </div>
            <div style='background:#161D2A; padding:12px; border-radius:10px; text-align:center;'>
                <p style='margin:0; font-size:13px; color:#9DAABC;'>평가 손익 (수익률)</p>
                <p style='margin:2px 0 0 0; font-size:20px; color:{"#35C98B" if pnl_val>=0 else "#ff453a"}; font-weight:bold;'>{pnl_val:+,.0f} 원 ({pnl_pct:+.2f}%)</p>
            </div>
            <div style='background:#161D2A; padding:12px; border-radius:10px; text-align:center;'>
                <p style='margin:0; font-size:13px; color:#9DAABC;'>매수 / 매도 전략</p>
                <p style='margin:2px 0 0 0; font-size:15px; color:{add_buy_color};'>{add_buy_status}</p>
            </div>
        </div>
        <p style='margin:0; font-size:15px; color:#F3F6FA;'>💡 <b>맞춤 대응 가이드</b>: {user_pos_advice}</p>
        {water_msg}
    </div>
    """, unsafe_allow_html=True)
# 세부 점수 — v2 3단계 위계: 큰 숫자 카드 5장 대신 작은 수평 막대 (종합점수는
# 위 배너 한 곳뿐이며, 여기는 관찰용 세부 지표다)
st.markdown('<div id="nav-scores"></div>', unsafe_allow_html=True)


def _score_bar_row(label, val, note=''):
    v = None
    try:
        v = float(val)
    except (TypeError, ValueError):
        pass
    if v is None:
        bar, txt, col = 0, '미산출', _TOK['tx2']
    else:
        bar = max(0, min(100, v))
        txt = f"{v:.0f}"
        col = _TOK['pos'] if v >= 70 else (_TOK['warn'] if v >= 50 else _TOK['neg'])
    return (
        f"<div style='display:flex; align-items:center; gap:12px; margin:8px 0;'>"
        f"<span style='width:150px; font-size:13px; color:{_TOK['tx2']};'>{label}</span>"
        f"<span style='flex:1; height:6px; background:{_TOK['border']}; border-radius:3px; overflow:hidden;'>"
        f"<span style='display:block; width:{bar}%; height:100%; background:{col};'></span></span>"
        f"<span style='width:36px; text-align:right; font-size:13px; font-weight:700; color:{_TOK['tx1']};'>{txt}</span>"
        f"<span style='width:220px; font-size:12px; color:{_TOK['tx2']};'>{note}</span>"
        f"</div>")


_sq_note = (f"OOS Sharpe {fmt_num((snap.get('oos_result') or {}).get('sharpe'), spec='.2f')} · "
            f"상한 {four_scores.get('sq_cap')}점")
st.markdown(f"""
<div style='background:#161D2A; border-radius:12px;
            padding:20px 24px; margin-bottom:12px;'>
  <p style='margin:0 0 8px 0; font-size:15px; font-weight:700; color:{_TOK['tx1']};'>
    세부 점수 <span style='font-size:12px; font-weight:600; color:{_TOK['tx2']};'>
    — 종합점수 산식은 위 '이 점수는 이렇게 나왔습니다' 표가 유일합니다</span></p>
  {_score_bar_row('종목 기본 매력도', four_scores['stock_quality_score'], four_scores['stock_quality_grade'])}
  {_score_bar_row('현재 매매 적합도', four_scores['trading_timing_score'], four_scores['trading_action'])}
  {_score_bar_row('분석 신뢰도', four_scores['analysis_confidence'], four_scores['conf_grade'])}
  {_score_bar_row('전략 품질 (표본외)', four_scores.get('strategy_quality_score'), _sq_note)}
  <div style='display:flex; align-items:center; gap:12px; margin:8px 0;'>
    <span style='width:150px; font-size:13px; color:{_TOK['tx2']};'>현재 가격 위치</span>
    <span style='flex:1; font-size:13px; color:{_TOK['tx1']}; font-weight:700;'>
      {price_pos['range_name']} <span style='color:{_TOK['tx2']}; font-weight:600;'>· 52주 범위 {price_pos['range_pos_pct']}%</span></span>
  </div>
</div>
""", unsafe_allow_html=True)

# # 🏢 [주요 가점·감점 및 기여도 세부 보기 (Section 18)]
with st.expander("[클릭] 4대 분리 점수별 주요 긍정 기여 및 제한 요인 세부 내역 보기", expanded=False):
    s_col1, s_col2 = st.columns(2)
    with s_col1:
        st.markdown(f"""
        <div style='background:#161D2A; border-radius:12px; padding:16px;'>
            <p style='margin:0; font-weight:bold; color:#35C98B;'>🏆 종목 기본 매력도 세부 기여 내역 ({four_scores['stock_quality_score']}점)</p>
            <p style='margin:4px 0; color:#9DAABC; font-size:13px;'>펀더멘털 30%: {four_scores['f_score']}점 → 기여 {four_scores['f_score']*0.30:.1f}점</p>
            <p style='margin:4px 0; color:#9DAABC; font-size:13px;'>밸류에이션 25%: {four_scores['v_score']}점 → 기여 {four_scores['v_score']*0.25:.1f}점</p>
            <p style='margin:4px 0; color:#9DAABC; font-size:13px;'>재무안전 20%: {four_scores['r_score']}점 → 기여 {four_scores['r_score']*0.20:.1f}점</p>
            <p style='margin:4px 0; color:#9DAABC; font-size:13px;'>산업경쟁력 15%: {four_scores['s_score']}점 → 기여 {four_scores['s_score']*0.15:.1f}점</p>
            <p style='margin:4px 0; color:#9DAABC; font-size:13px;'>중장기 구조 10%: {four_scores['i_score']}점 → 기여 {four_scores['i_score']*0.10:.1f}점</p>
            <p style='margin:8px 0 0 0; color:#9DAABC; font-size:12px;'>※ 기술적 구조({four_scores['t_score']}점)는 기본 매력도가 아니라 매매 적합도에 반영됩니다.</p>
        </div>
        """, unsafe_allow_html=True)
    with s_col2:
        _wr = four_scores.get('win_rate')
        _pe = four_scores.get('path_edge')
        _nr = four_scores.get('non_reach')
        wr_col = "#9DAABC" if _wr is None else ("#35C98B" if _wr >= 60 else "#F2B84B")
        pe_col = "#9DAABC" if _pe is None else ("#35C98B" if _pe > 5 else "#ff453a")
        nr_col = "#9DAABC" if _nr is None else ("#ff453a" if _nr >= 60 else "#35C98B")
        st.markdown(f"""
        <div style='background:#161D2A; border-radius:12px; padding:16px;'>
            <p style='margin:0; font-weight:bold; color:#F2B84B;'>🎯 현재 매매 적합도 주요 진단 요인 ({four_scores['trading_timing_score']}점)</p>
            <p style='margin:4px 0; color:{wr_col}; font-size:13px;'>[관찰 승률] 20일 유사패턴 과거 관찰 승률: {fmt_pct(_wr, signed=False)} (유효표본 {four_scores.get('eff_sample_size', 0):.0f}건 · {four_scores.get('sample_tier', '-')})</p>
            <p style='margin:4px 0; color:{pe_col}; font-size:13px;'>[경로 우위] 20일 평균 수익률: {fmt_pct(_pe)}</p>
            <p style='margin:4px 0; color:{nr_col}; font-size:13px;'>[미도달 비중] 목표가·손절가 모두 미도달: {fmt_pct(_nr, signed=False)}</p>
            <p style='margin:4px 0; color:#4C8DFF; font-size:13px;'>[게이트 판정] <code>{four_scores['gate_reason']}</code></p>
        </div>
        """, unsafe_allow_html=True)

    blocks = four_scores.get('top3_block_reasons', [])
    if blocks:
        st.markdown("**TOP 3 추천 미충족 조건**\n\n" + "\n".join(f"- {b}" for b in blocks))
    else:
        st.markdown("**TOP 3 추천 필수조건 전부 통과**")

# 🏢 [6대 영역 세부 프로필 (Section 18)]
with st.expander("4대 분리 점수 세부 산출 근거 및 실시간 정량 기여도 펼쳐보기"):
    st.write("### 퀀트 점수 산출 로직 (전면 개편)\n")
    st.write("- **원시 종합점수**: 종목 기본 매력도 35% + 현재 매매 적합도 45% + 리스크 안전성 20%\n")
    st.write("- **신뢰도 조정**: 50 + (원시점수 - 50) × (분석 신뢰도/100)\n")
    st.write(f"- **분석 신뢰도**: 데이터 50% + 통계 30% + 모델검증 20% = **{four_scores.get('analysis_confidence', 0)}점** "
             f"(Blind/OOS 미구현이므로 모델검증 항목은 0점)\n")
    st.write("- **최종 행동 원점수**: 신뢰도 조정점수 45% + 기회점수 30% + 실행가능성 15% + 신호 합의도 10%\n")
    st.write("- **최종점수**: 위 원점수에 데이터·통계·전략품질·추격위험 게이트 상한을 적용한 값\n")
    st.write("- *DeMARK 9-13 및 밴드/모멘텀 신호는 현재 매매 적합도에 14% 비중으로 반영됩니다.*\n")
    st.write(f"- **독립 가격 위치 ({price_pos['range_name']} - 52주 범위 {price_pos['range_pos_pct']}%)**: 52주 고저 범위({price_pos['low_52w']:,.0f}~{price_pos['high_52w']:,.0f}{unit_str}) 및 60일선 이격률({price_pos['disparity_60']:+.1f}%).\n")

# 기업 분석(퀀터멘탈·프로필·PER 비교)은 전문가 옵션으로 격리한다 (브리프 v2 §7).
# ETF·ETN은 기업 재무 개념이 적용되지 않으므로 아예 표시하지 않는다.
_is_stock_asset = str(four_scores.get('asset_type', 'STOCK')) == 'STOCK'
if not _is_stock_asset:
    st.caption("기업 재무·퀀터멘탈 분석은 개별 주식 전용입니다 — "
               "ETF·ETN에는 적용하지 않습니다 (자산 유형별 분리 원칙).")
else:
  with st.expander("기업 재무·퀀터멘탈 분석 (전문가 보기 — 주식 전용)",
                   expanded=False):
    qm_score = q_engine.calculate_quantamental_hybrid_score(tech_df, fund_df, target_ticker, four_scores=four_scores)
    sharpe_turnover = q_engine.calculate_sharpe_and_turnover(sim_res, four_scores=four_scores)
    per_upside = q_engine.calculate_sector_per_upside(val_eval, target_ticker)
    profile = q_engine.get_company_profile(target_ticker, val_eval=val_eval, four_scores=four_scores)

    q_col1, q_col2, q_col3 = st.columns(3)

    with q_col1:
        st.markdown(f"""
        <div style='background: #161D2A; border-radius: 12px; padding: 20px;'>
            <h4 style='margin-top:0;'>1. 시장 국면 & 밸류에이션 위치</h4>
            <p style='margin: 4px 0; font-size:15px;'>- <b>섹터 10년 평균 PER</b>: <b>{fmt_num(per_upside['sector_10yr_per'], '.1f', '배')}</b> | <b>현재 PER</b>: <b>{fmt_num(per_upside['curr_per'], '.1f', '배')}</b></p>
            <p style='margin: 4px 0; font-size:15px;'>- <b>상대적 밸류에이션 룸</b>: <b style='color:#35C98B;'>{fmt_pct(per_upside['upside_room_pct'])}</b></p>
            <p style='margin: 4px 0; font-size:13px; color:#F2B84B;'><b>FOMO 방지 지수</b>: {per_upside['fomo_status']}</p>
        </div>
        """, unsafe_allow_html=True)

    with q_col2:
        st.markdown(f"""
        <div style='background: #161D2A; border-radius: 12px; padding: 20px;'>
            <h4 style='margin-top:0;'>2. 백테스트 품질 평가 지표</h4>
            <p style='margin: 4px 0; font-size:15px;'>- <b>표본내 Sharpe</b> (유사패턴 분포 기준): <b>{fmt_num(sharpe_turnover['sharpe_ratio'], spec='.2f')}</b>
               <span style='font-size:12px; color:#9DAABC;'>— 표본외 Sharpe는 아래 Blind/OOS 섹션 참조</span></p>
            <p style='margin: 4px 0; font-size:15px;'>- <b>연환산 회전율 (Turnover)</b>: <b>{fmt_num(sharpe_turnover['turnover_pct'], spec='.0f', suffix='%')}</b> (권장 보유 {fmt_num(sharpe_turnover['holding_days'], suffix='영업일')})</p>
            <p style='margin: 4px 0; font-size:13px; color:#9DAABC;'>- <b>Profit Factor</b>: <b>{fmt_num(sharpe_turnover['real_profit_factor'], spec='.2f')}</b> | <b>비용 차감 수익</b>: {fmt_pct(sharpe_turnover['net_excess_return'], digits=2)}</p>
        </div>
        """, unsafe_allow_html=True)

    with q_col3:
        st.markdown(f"""
        <div style='background: #161D2A; border-radius: 12px; padding: 20px;'>
            <h4 style='margin-top:0;'>3. 퀀터멘탈(Quantamental) 점수</h4>
            <h2 style='color: #35C98B; margin: 4px 0; font-size: 28px;'>{qm_score['hybrid_score']}점 <span style='font-size:15px; color:#9DAABC;'>(하이브리드)</span></h2>
            <p style='margin: 4px 0; font-size:13px; color:#9DAABC;'><code>{qm_score['formula_str']}</code></p>
            <p style='margin: 4px 0; font-size:13px; color:#9DAABC;'>가격은 실제 일봉만 사용하며, 수신 실패 시 합성값으로 대체하지 않습니다. 과거 분기 재무 시계열은 미연동입니다.</p>
        </div>
        """, unsafe_allow_html=True)

    _mix = " · ".join(f"{t['name']} {t['probability_pct']:.0f}%" for t in profile['type_mix'])
    _applied = " · ".join(f"{m['model']} {m['weight_pct']:.0f}%" for m in profile['applied_models']) or "없음"
    _excluded = ", ".join(profile['excluded_models']) or "없음"
    st.markdown(f"""
    <div style='background: #161D2A; border-radius: 12px; padding: 20px; margin: 12px 0;'>
        <h4 style='margin-top:0;'>기업 프로필 (수치 기반 · 주식 전용 산출)</h4>
        <p style='margin:4px 0; font-size:15px;'>- <b>기업유형 분류</b>: {profile['enterprise_class']} &nbsp;|&nbsp; <code>{_mix}</code></p>
        <p style='margin:4px 0; font-size:15px;'>- <b>적용 평가모델</b>: {_applied}</p>
        <p style='margin:4px 0; font-size:15px; color:#9DAABC;'>- <b>유효성 미통과 모델</b>: {_excluded}</p>
        <p style='margin:4px 0; font-size:15px;'>- <b>20일 평균 거래대금</b>: {fmt_num((profile['metrics']['avg_turnover_20d'] or 0)/1e8, ',.0f', '억원', na='미산출')}
           &nbsp;|&nbsp; <b>유동성 점수</b>: {fmt_num(profile['metrics']['liquidity_score'], suffix='점')}
           &nbsp;|&nbsp; <b>미수신 입력</b>: {', '.join(profile['missing_inputs']) or '없음'}</p>
        <p style='margin:8px 0 0 0; font-size:13px; color:#F2B84B;'>{profile['qualitative_note']}</p>
    </div>
    """, unsafe_allow_html=True)

_uk.spacer(28)


# 탭마다 그 탭의 독립 판정을 맨 위에 띄운다. 종합 결론과 다르면 그 사실이 보여야 한다.
_TAB_VERDICT = {t['key']: t for t in verdict['tabs']}


def show_tab_verdict(key):
    t = _TAB_VERDICT.get(key)
    if not t:
        return
    score_txt = "—" if t['score'] is None else f"{t['score']}점"
    st.markdown(
        f"<div style='background:#161D2A;border-left:6px solid {t['color']};"
        f"border-radius:10px;padding:12px 16px;margin-bottom:12px;'>"
        f"<span style='font-size:22px;font-weight:700;color:{t['color']};'>{t['verdict']}</span>"
        f"<span style='font-size:17px;font-weight:700;color:#F3F6FA;margin-left:12px;'>{score_txt}</span>"
        f"<span style='color:#9DAABC;font-size:13px;margin-left:8px;'>이 탭 단독 판정</span>"
        + "".join(f"<br><span style='color:#9DAABC;font-size:15px;'>· {r}</span>"
                  for r in t['reasons'])
        + "</div>", unsafe_allow_html=True)


# 🚨 [사용자 요청] 5대 핵심 분석 탭을 교차검증 상태표 위로 이동!
# 탭 이름은 사용자 언어로 (내부 용어는 각 탭 안에서 설명) — 브리프 v2 §6
tab_pred, tab_val, tab_scen, tab_demark, tab_flow, tab_audit = st.tabs([
    "과거 비슷한 사례",
    "현재 가격 위치",
    "오르면 · 횡보하면 · 내리면",
    "추세 소진 신호",
    "차트와 거래량",
    "모델 신뢰도 · 데이터 검사"
])

# [Section 5 & 6 & 19] 자기유사 패턴 과거 백테스트 결과 (7대 적중률 극대화 파이프라인 가동)
with tab_pred:
    show_tab_verdict('pattern')
    st.subheader(f"[{resolved_name}] - 자기유사 예측 & 7대 적중률 극대화 엔진 파이프라인")
    
    # [19-10] 거래 회피(Abstain) 알림
    if sim_res.get('is_abstain'):
        st.warning(f"**퀀트 리스크 관리 알림**: 현재 구간은 [{sim_res.get('abstain_reason')}] 조건이 감지되어 **`[예측 보류 / 거래 회피(Abstain)]`**를 권장합니다.")
    
    st.markdown(f"""
    <div style='background: #161D2A; border-radius: 16px; padding: 20px; margin-bottom: 20px;'>
        <h4 style='color: #35C98B !important; margin-top:0;'>자기유사 예측 파이프라인 — 실제 실행 단계</h4>
        <p style='font-size: 15px; margin: 4px 0; line-height: 1.7;'>
            <b>① 시장 국면 판정</b>: <b style='color:#4C8DFF;'>[{four_scores.get('market_regime_label', '판정 보류')}]</b> — 지수 일봉 120봉의 20/60일선 대비 실측<br>
            <b>② 패턴 정규화</b>: 최근 H봉 종가를 Z-Score 정규화 후 전 구간 스캔<br>
            <b>③ 유사도</b>: Pearson 상관 (임계 rho ≥ {sim_res.get('rho_cutoff_applied', rho_cutoff)}) + H≤40 구간은 DTW 결합 (0.7 / 0.3)<br>
            <b>④ 독립성 확보</b>: 매칭 간 최소 H영업일 간격 강제 (중복 이벤트 제거)<br>
            <b>⑤ 경로 확률</b>: 손절(-{TP_SL[1]:.0f}%) vs 목표(+{TP_SL[0]:.0f}%) 선도달 여부를 매칭별로 실제 경로 추적<br>
            <b>⑥ 베이지안 보정</b>: Beta-Binomial 사후평균 (사후확률: <b style='color:#35C98B;'>{fmt_pct(sim_res.get('bayes_prob'), signed=False)}</b>) + 95% Wilson 구간<br>
            <b>⑦ 표본 통제</b>: 유효표본 {sim_res.get('match_count', 0)}건 · 등급 <b>{sim_res.get('sample_tier_label', '-')}</b> — 10건 미만이면 확률 미표시
        </p>
        <p style='font-size: 12px; color:#9DAABC; margin: 8px 0 0 0;'>
            ※ 거래량·수급·RSI를 유사도에 반영하는 다중거리 모델과 다중 모델 앙상블은 구현되어 있지 않습니다.
            유사도는 Pearson 상관과 DTW만 사용합니다.
        </p>
    </div>
    """, unsafe_allow_html=True)

    if not sim_res.get('probabilities_shown', False):
        st.warning(f"**[명세 §11 표본 통제]** 유효표본 {sim_res.get('match_count', 0)}건 — "
                   f"{sim_res.get('sample_tier_label', '')}. 이 구간에서는 확률을 산출·표시하지 않고 "
                   f"과거 관찰값만 제공합니다.")

    st.markdown(f"경로 기반 확률 대시보드 (목표가 +{TP_SL[0]:.0f}% vs 손절가 -{TP_SL[1]:.0f}% 선도달)")
    # 구버전은 사후확률을 9등분해 '9개 앙상블 모델 중 N개 상승'으로 표시했다.
    # 실제 다중 모델 앙상블이 없으므로, 실제로 계산되는 지평 일치도로 대체한다.
    _hcs = sim_res.get('horizon_consistency_score')
    _scored = [H for H, hh in (sim_res.get('horizons_data') or {}).items()
               if hh.get('win_rate') is not None]
    _uk.stat_tiles([
        {'label': f"목표가 +{TP_SL[0]:.0f}% 먼저 닿을 확률",
         'value': fmt_pct(sim_res.get('tp_first_prob'), signed=False),
         'sub': '손절가보다 목표가에 먼저 도달', 'tone': 'pos'},
        {'label': f"손절가 -{TP_SL[1]:.0f}% 먼저 닿을 확률",
         'value': fmt_pct(sim_res.get('sl_first_prob'), signed=False),
         'sub': '목표가보다 손절가에 먼저 도달', 'tone': 'neg'},
        {'label': '베이지안 사후 상승확률',
         'value': fmt_pct(sim_res.get('bayes_prob'), signed=False),
         'sub': 'Beta-Binomial 보정'},
        {'label': '기간 간 방향 일치도', 'value': fmt_num(_hcs, suffix='점'),
         'sub': f"산출 가능 지평 {len(_scored)}개 기준"},
    ], theme=_theme)

    if not sim_res.get('probabilities_shown', False):
        st.info(f"**예측 확률 미표시** — {sim_res.get('blind_reason', '표본 부족')}. "
                f"아래 '과거 관찰 성과'는 실제 관찰된 값이며 미래 확률로 해석하지 마십시오.")
    else:
        prob_val = sim_res.get('predicted_probability') or 50.0
        prob_color = "#35C98B" if prob_val >= 60.0 else ("#4C8DFF" if prob_val >= 50.0 else "#F2B84B")

        st.markdown(f"""
        <div style='background: rgba(48, 209, 88, 0.10); border-radius: 12px; padding: 16px 20px; margin: 12px 0;'>
            <span style='font-size: 17px; font-weight: bold; color: #F3F6FA;'>🎯 최종 예측 상승확률 (베이지안 사후보정): </span>
            <span style='font-size: 20px; font-weight: 700; color: {prob_color}; margin-left: 8px;'>{sim_res['predicted_prob_str']}</span>
            <span style='font-size: 15px; color: #9DAABC; margin-left: 12px;'>(95% 신뢰구간: <code style="color:#4C8DFF;">{sim_res['ci_str']}</code> | 분류: <b>{sim_res['confidence_grade']}</b>)</span>
        </div>
        """, unsafe_allow_html=True)
        
    # ── [명세 §10] 다중기간(5·10·20·40·60·120일) 독립 예측 결과 ──────────────
    st.markdown("다중기간 독립 예측 (5 · 10 · 20 · 40 · 60 · 120 영업일)")
    hz = sim_res.get('horizons_data') or {}
    if hz:
        hz_rows = []
        for H in [5, 10, 20, 40, 60, 120]:
            h = hz.get(H)
            if not h:
                continue
            hz_rows.append({
                "기간": f"{H}일",
                "유효표본": h.get('match_count', 0),
                "등급": h.get('tier_label', '-'),
                "관찰승률": fmt_pct(h.get('obs_win_rate'), signed=False),
                "평균": fmt_pct(h.get('mean_perf')),
                "중앙값": fmt_pct(h.get('median_perf')),
                "10~90분위": (f"{fmt_pct(h.get('p10_perf'))} ~ {fmt_pct(h.get('p90_perf'))}"
                              if h.get('p10_perf') is not None else "미산출"),
                "평균 MDD": fmt_pct(h.get('mdd')),
                f"목표(+{TP_SL[0]:.0f}%) 선도달": fmt_pct(h.get('tp_first_prob'), signed=False),
                f"손절(-{TP_SL[1]:.0f}%) 선도달": fmt_pct(h.get('sl_first_prob'), signed=False),
            })
        if hz_rows:
            st.dataframe(pd.DataFrame(hz_rows), width='stretch', hide_index=True)

        _uk.stat_tiles([
            {'label': '기간 간 방향 일치도',
             'value': fmt_num(sim_res.get('horizon_consistency_score'),
                              suffix='점'),
             'sub': '산출 가능한 지평 기준'},
            {'label': '최적 보유기간',
             'value': sim_res.get('optimal_holding_period_str', '산출 불가'),
             'sub': '평균수익 × 승률 × 일치도 / √기간'},
            {'label': '적용 상관 임계값',
             'value': f"rho ≥ {sim_res.get('rho_cutoff_applied', rho_cutoff)}",
             'sub': '왼쪽에서 설정한 값 그대로'},
        ], theme=_theme)

        # ── 미선정이면 '고장'이 아니라 '판정'임을 근거와 함께 보여준다 ─────────
        if not sim_res.get('optimal_holding_period_days'):
            _elig = sim_res.get('horizon_eligibility') or {}
            _near = sim_res.get('horizon_nearest_miss')
            _nosam = sim_res.get('horizons_without_sample') or []
            with st.expander("최적 보유기간이 왜 미선정인가 — 지평별 판정 근거", expanded=True):
                st.caption(
                    "게이트를 통과한 지평이 없다는 뜻이며, 오류가 아닙니다. "
                    "억지로 하나를 고르면 손실이 기대되는 기간을 '최적'이라 부르게 됩니다.")
                if _elig:
                    st.dataframe(pd.DataFrame([{
                        "지평": f"{H}일",
                        "순기대수익(비용차감)": f"{v.get('net_expected_return', 0):+.2f}%",
                        "자격": "통과" if v['eligible'] else "미달",
                        "미달 사유": " · ".join(v['reasons']) or "—",
                    } for H, v in sorted(_elig.items())]),
                        width='stretch', hide_index=True)
                if _near:
                    st.markdown(
                        f"**가장 근접한 지평: {_near['horizon']}일** — "
                        + (" / ".join(_near['needs']) if _near['needs'] else "조건 충족"))
                if _nosam:
                    st.caption(
                        "유효 표본이 없어 자격 판정 자체를 못한 지평: "
                        + ", ".join(f"{H}일" for H in _nosam)
                        + f" — 현재 rho ≥ {sim_res.get('rho_cutoff_applied', rho_cutoff)} "
                          "기준으로 닮은 과거 구간이 없습니다. "
                          "사이드바에서 rho 를 낮추면 표본이 늘지만 유사도는 떨어집니다.")

        strat = sim_res.get('strategy_probabilities') or {}
        if strat:
            STRAT_KO = {
                'mean_reversion': '평균회귀', 'demark_reversal': 'DeMARK 반전',
                'pullback': '눌림목', 'trend_breakout': '추세돌파',
                'earnings_momentum': '실적 모멘텀', 'monthly_trend': '월봉 장기추세',
            }
            ordered = sorted(strat.items(), key=lambda kv: kv[1], reverse=True)
            st.caption("전략 유형 확률: " + " · ".join(
                f"{STRAT_KO.get(k, k)} {v:.0f}%" for k, v in ordered))
    else:
        st.info("다중기간 결과가 없습니다 (표본 부족).")

    st.markdown("과거 관찰 성과 세부 분리 지표 (20일)")
    # 6칸을 한 줄에 넣으면 좁은 화면에서 값이 잘린다 — 3칸씩 두 줄로 나눈다.
    _uk.stat_tiles([
        {'label': '비슷했던 사례 수', 'value': f"{sim_res['match_count']}건",
         'sub': sim_res['confidence_grade']},
        {'label': '평균 수익률',
         'value': (f"{sim_res['mean_perf']}%"
                   if sim_res['mean_perf'] is not None else '산출 불가'),
         'sub': '20거래일 보유 기준'},
        {'label': '중앙값 수익률',
         'value': (f"{sim_res['median_perf']}%"
                   if sim_res['median_perf'] is not None else '산출 불가'),
         'sub': '극단값에 덜 흔들리는 값'},
    ], theme=_theme)
    _uk.stat_tiles([
        {'label': '최고 / 최저',
         'value': (f"{sim_res['max_perf']}% / {sim_res['min_perf']}%"
                   if sim_res['max_perf'] is not None else '산출 불가'),
         'sub': '가장 좋았을 때와 나빴을 때'},
        {'label': '평균 최대낙폭',
         'value': (f"{sim_res['mdd']}%"
                   if sim_res['mdd'] is not None else '산출 불가'),
         'sub': '보유 중 겪은 평균 최대 하락', 'tone': 'neg'},
        {'label': '오른 사례 / 내린 사례',
         'value': f"{sim_res['win_count']} / {sim_res['loss_count']}",
         'sub': '같은 조건에서의 결과 분포'},
    ], theme=_theme)

    # ── [명세 §10] 기간 선택형 경로 그래프 ─────────────────────────────────
    # 상·중·하 시나리오는 평균선의 평행이동이 아니라 시점별로 독립 계산한 분위수 경로다.
    st.markdown("기간별 경로 분포")

    core = sim_res.get('core_horizons') or [10, 20, 40]
    ALL_H = [5, 10, 20, 40, 60, 120]
    avail_h = [H for H in ALL_H if (hz.get(H) or {}).get('status') != 'INSUFFICIENT']
    # ⚠️ 표본이 없는 지평을 목록에서 빼버리면 '기능이 사라진 것'처럼 보인다.
    #    6개 지평은 항상 노출하고, 표본이 없으면 그 사실과 이유를 보여준다.
    if not avail_h:
        st.info("표본이 충분한 예측 기간이 없어 경로 그래프를 표시하지 않습니다.")
    else:
        # 기본 선택은 중기(40일 우선, 없으면 60일)로 둔다. 짧은 기간은 표본이 많아
        # 기본으로 잡히기 쉬운데, 노이즈가 커서 판단 근거로는 약하다.
        PREFERRED_DEFAULT_H = (40, 60, 20, 120, 10, 5)
        default_h = next((H for H in PREFERRED_DEFAULT_H if H in avail_h and H in core), None)
        if default_h is None:
            default_h = next((H for H in PREFERRED_DEFAULT_H if H in avail_h), avail_h[0])

        def _h_label(H):
            mark = " ⭐" if H in core else ""
            if H not in avail_h:
                return f"{H}일{mark} (표본없음)"
            return f"{H}일{mark}"

        sel_h = st.radio(
            "예측 기간 선택 (기본 40일 · ⭐는 전략 유형에 맞는 핵심 기간)",
            ALL_H, index=ALL_H.index(default_h), horizontal=True,
            format_func=_h_label, key="horizon_pick")

        if sel_h not in avail_h:
            _mc = (hz.get(sel_h) or {}).get('match_count', 0)
            st.warning(
                f"**{sel_h}일 지평은 유효 표본이 {_mc}건**이라 경로를 그리지 않습니다. "
                f"현재 상관 임계값 **rho ≥ {rho_cutoff}** 에서 과거에 지금과 닮은 "
                f"{sel_h}일 구간이 그만큼밖에 없다는 뜻입니다. "
                f"긴 지평일수록 비교 가능한 구간 수 자체가 줄어듭니다 "
                f"(가격 이력이 N봉이면 {sel_h}일 구간은 최대 N−{sel_h}개). "
                f"사이드바에서 rho 를 낮추면 표본이 늘지만 유사도는 떨어집니다.")
            st.caption("표본이 있는 지평: " + ", ".join(f"{H}일" for H in avail_h))
            sel_h = default_h
            st.info(f"아래 그래프는 표본이 있는 **{sel_h}일** 기준입니다.")

        h = hz[sel_h]
        show_forecast = q_engine.probabilities_allowed(h['status'])
        days = np.arange(1, sel_h + 1)

        fig_pred, ax_p = plt.subplots(figsize=(12, 5.2))
        fig_pred.patch.set_facecolor('#0B0F17')
        ax_p.set_facecolor('#161D2A')

        # 불확실성 밴드 (10~90분위 / 25~75분위)
        ax_p.fill_between(days, h['traj_p10'], h['traj_p90'], color='#4C8DFF', alpha=0.10,
                          label="10~90분위 구간")
        ax_p.fill_between(days, h['traj_p25'], h['traj_p75'], color='#4C8DFF', alpha=0.20,
                          label="25~75분위 구간")

        # 군집 대표경로 (낙관·중립·비관) — 실제 경로들의 평균이라 모양이 서로 다르다
        cs = h.get('cluster_sizes') or {}
        ax_p.plot(days, h['path_bull'], color='#35C98B', linewidth=2.0, linestyle='--',
                  label=f"낙관 군집 평균 (n={cs.get('bull', 0)})")
        ax_p.plot(days, h['trajectory'], color='#4C8DFF', linewidth=2.8,
                  label=f"중앙 경로 (median, n={h['match_count']})")
        ax_p.plot(days, h['path_bear'], color='#ff453a', linewidth=2.0, linestyle='--',
                  label=f"비관 군집 평균 (n={cs.get('bear', 0)})")
        ax_p.axhline(curr_price, color='#F3F6FA', linestyle='-', linewidth=1.2, label="현재가")
        # 기준선들 — 모두 참고용이며 경로 분포 계산에는 사용하지 않는다
        for _v, _c, _lb in (
                (four_scores.get('displayed_fair_value'), '#4C8DFF', '펀더멘털 적정가'),
                (four_scores.get('buy_entry_max'), '#35C98B', '권장 매수가 상단'),
                (four_scores.get('target_tech_1st'), '#4C8DFF', '1차 목표가'),
                (four_scores.get('target_tech_2nd'), '#4C8DFF', '2차 목표가'),
                (four_scores.get('stop_loss_price'), '#ff453a', '손절가')):
            if _v is not None:
                ax_p.axhline(_v, color=_c, linestyle=':', linewidth=1.1, alpha=0.85, label=_lb)

        # 보유 중이면 평균 매수가를 개인 참고선으로만 겹쳐 그린다
        _my = None
        for _p in (st.session_state.get('positions') or []):
            if _p.ticker == target_ticker:
                _my = _p.average_buy_price
                break
        if _my is None and user_entry_price > 0:
            _my = float(user_entry_price)
        if _my:
            ax_p.axhline(_my, color='#F2B84B', linestyle='--', linewidth=1.8,
                         label=f"내 평균 매수가 ({_my:,.0f})")
            ax_p.fill_between(days, min(_my, curr_price), max(_my, curr_price),
                              color=('#35C98B' if curr_price >= _my else '#ff453a'), alpha=0.07)

        title_kind = "예측" if show_forecast else "과거 유사사례 관찰"
        ax_p.set_title(
            f"[{resolved_name}] {sel_h}영업일 {title_kind} — 유효표본 {h['match_count']}건 · {h['tier_label']}",
            color='#F3F6FA', fontsize=13)
        ax_p.set_xlabel("미래 영업일 (Day)", color='#9DAABC')
        ax_p.set_ylabel(f"주가 ({unit_str})", color='#9DAABC')
        ax_p.tick_params(colors='#F3F6FA')
        ax_p.grid(True, color='#1C2635', linestyle='--')
        ax_p.legend(facecolor='#161D2A', edgecolor='#1C2635', labelcolor='#F3F6FA', fontsize=8)
        st.pyplot(fig_pred)

        if not show_forecast:
            st.warning(f"유효표본 {h['match_count']}건 — {h['tier_label']}. "
                       f"위 그래프는 **미래 예측이 아니라 과거 유사사례의 관찰 분포**입니다.")

        g1, g2, g3, g4, g5, g6 = st.columns(6)
        g1.metric("유효표본", f"{h['match_count']}건", h['tier_label'])
        g2.metric("ESS", fmt_num(h.get('ess'), '.1f', '건'), "분포 쏠림 보정")
        g3.metric("평균 / 중앙값", f"{fmt_pct(h['mean_perf'])} / {fmt_pct(h['median_perf'])}")
        g4.metric("25~75분위", f"{fmt_pct(h.get('p10_perf'))} ~ {fmt_pct(h.get('p90_perf'))}", "10~90분위")
        g5.metric("평균 MDD", fmt_pct(h['mdd']))
        g6.metric(f"목표 / 손절 선도달",
                  f"{fmt_pct(h['tp_first_prob'], signed=False)} / {fmt_pct(h['sl_first_prob'], signed=False)}"
                  if show_forecast else "미산출")

# [Section 8 & 8-1] 밸류에이션 및 적정가 (시장조정 펀더멘털 적정가 단일 체제)
with tab_val:
    show_tab_verdict('valuation')
    st.subheader(f"[{resolved_name}] - 시장조정 펀더멘털 적정가")
    
    target_price = four_scores.get('target_fundamental', realtime_price)
    disp_price = four_scores.get('displayed_fair_value')
    prelim_range = four_scores.get('preliminary_range_str', '미산출')
    base_fair_val = four_scores.get('base_fair_value', target_price)
    upside_pct = four_scores.get('upside_pct')
    upside_eval = four_scores.get('upside_eval', '가치판단 보류')
    mkt_adj_pct = four_scores.get('market_adjustment_pct', -2.0)
    conf_score = four_scores.get('fair_value_confidence', 0.0)
    rec_buy = four_scores.get('recommended_buy_price')
    mos_pct = four_scores.get('margin_of_safety_pct', 15.0)
    fv_status = four_scores.get('fair_value_status', 'UNCALCULATED')
    fv_note = four_scores.get('fair_value_status_note', '')

    # [명세 §7] 신뢰도 미달 구간에서는 중심 적정가와 권장 매수가를 숫자로 내보내지 않는다
    if fv_status == "CALIBRATED":
        st.success(f"적정가 신뢰도 {conf_score:.0f}점 — {fv_note}")
    elif fv_status == "CAUTION":
        st.warning(f"적정가 신뢰도 {conf_score:.0f}점 — {fv_note}")
    elif fv_status == "REFERENCE_ONLY":
        st.warning(f"적정가 신뢰도 {conf_score:.0f}점 — {fv_note}. 아래 예비 모델 범위만 참고하십시오.")
    else:
        st.error(f"적정가 신뢰도 {conf_score:.0f}점 — {fv_note}. 중심 적정가와 권장 매수가를 산출하지 않았습니다.")

    disp_price_str = f"{disp_price:,.0f}{unit_str}" if disp_price is not None else "산출 보류"
    if upside_pct is None:
        upside_display_str = f"<b style='color:#9DAABC;'>상승여력 미산출</b> ({upside_eval})"
    else:
        upside_color = "#35C98B" if upside_pct > 0 else "#ff453a"
        upside_display_str = f"현재가 대비 <b style='color:{upside_color};'>{upside_pct:+.1f}%</b> ({upside_eval})"

    if rec_buy is None:
        rec_buy_str = "미산출 (신뢰도 미달)"
        entry_eval_str = "판정 불가"
        entry_eval_color = "#9DAABC"
    else:
        rec_buy_str = f"{rec_buy:,.0f}{unit_str} 이하"
        entry_eval_str = "안전 매수 구간" if realtime_price <= rec_buy else "안전마진 상단 초과 (눌림 대기)"
        entry_eval_color = "#35C98B" if realtime_price <= rec_buy else "#F2B84B"

    st.markdown(f'''
    <div style="background: #161D2A; border-radius: 18px; padding: 24px; margin-bottom: 20px;">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap;">
            <div>
                <h3 style="margin-top:0; color:#4C8DFF;">시장조정 펀더멘털 적정가 (캘리브레이션 연동)</h3>
                <p style="font-size: 34px; font-weight: bold; margin: 4px 0; color: #F3F6FA;">{disp_price_str}</p>
                <p style="font-size: 17px; font-weight: bold; margin: 0; color: #9DAABC;">{upside_display_str}</p>
                <p style="font-size: 15px; color: #9DAABC; margin-top: 8px;">
                    참고 중심값 <b style="color:#F3F6FA;">{fmt_num(val_eval.get('reference_fair_value'), suffix=unit_str)}</b><br>
                    핵심 합리적 범위 (25~75분위) <b style="color:#4C8DFF;">{val_eval.get('fair_value_range_core_str', '미산출')}</b><br>
                    확장 불확실성 범위 (10~90분위) <b style="color:#9DAABC;">{val_eval.get('fair_value_range_wide_str', '미산출')}</b>
                </p>
            </div>
            <div style="text-align: right; background: #1C2635; padding: 16px 20px; border-radius: 12px; ">
                <p style="margin: 0; font-size: 13px; color: #9DAABC;">기초 펀더멘털 가치</p>
                <p style="margin: 4px 0 8px 0; font-size: 17px; font-weight: bold; color: #F3F6FA;">{base_fair_val:,.0f}{unit_str}</p>
                <p style="margin: 0; font-size: 13px; color: #9DAABC;">시장조정 영향: <b style="color:#F2B84B;">{mkt_adj_pct:+.1f}%</b></p>
                <p style="margin: 4px 0 0 0; font-size: 13px; color: #9DAABC;">적정가 신뢰도: <b style="color:#4C8DFF;">{conf_score:.0f} / 100점</b></p>
            </div>
        </div>
        <hr style="border-color: #222C3C; margin: 16px 0;">
        <div style="display: flex; justify-content: space-around; text-align: center; flex-wrap: wrap;">
            <div style="margin: 4px 8px;">
                <span style="font-size: 13px; color: #9DAABC;">권장 매수가 (안전마진 {mos_pct:.0f}% 적용)</span><br>
                <b style="font-size: 17px; color: #35C98B;">{rec_buy_str}</b>
            </div>
            <div style="margin: 4px 8px;">
                <span style="font-size: 13px; color: #9DAABC;">핵심 평가 모델</span><br>
                <b style="font-size: 16px; color: #F3F6FA;">기업특성 기반 선택적 다중 모델</b>
            </div>
            <div style="margin: 4px 8px;">
                <span style="font-size: 13px; color: #9DAABC;">현재 진입 평가</span><br>
                <b style="font-size: 16px; color: {entry_eval_color};">
                    {entry_eval_str}
                </b>
            </div>
        </div>
    </div>
    ''', unsafe_allow_html=True)
        
    with st.expander("[적정가 산출 근거 & 기업유형별 평가모델 내역 펼쳐보기]", expanded=True):
        # 기업유형 소속 확률 (상위 4개)
        tprobs = val_eval.get('type_probabilities') or {}
        TYPE_KO = {
            'A_STABLE': '안정적 흑자', 'B_CYCLICAL': '경기민감·자본집약', 'C_FINANCIAL': '금융',
            'D_PLATFORM': '플랫폼·핀테크', 'E_BIOTECH': '바이오·신약', 'F_DEFICIT': '적자 고성장',
            'G_HOLDING': '자산가치·지주', 'H_TURNAROUND': '턴어라운드',
        }
        top_types = sorted(tprobs.items(), key=lambda kv: kv[1], reverse=True)[:4]
        type_rows = "".join(
            f"<tr><td>{TYPE_KO.get(k, k)}</td><td>{v*100:.0f}%</td></tr>" for k, v in top_types
        ) or "<tr><td colspan='2'>분류 불가</td></tr>"

        # 실제 사용된 모델별 값·가중치 (불허 모델은 제외 사유와 함께 표시)
        mres = val_eval.get('model_results') or {}
        used_rows, excluded_rows = "", ""
        for key, m in sorted(mres.items(), key=lambda kv: -kv[1].get('weight', 0)):
            nm = m.get('name', key)
            if m.get('valid') and m.get('weight', 0) > 0:
                used_rows += (f"<tr><td>{nm}</td><td>{m['val']:,.0f}{unit_str}</td>"
                              f"<td>{m['weight']*100:.1f}%</td></tr>")
            else:
                excluded_rows += f"<tr><td>{nm}</td><td colspan='2'>유효성 검사 미통과 → 가중치 0%</td></tr>"
        if not used_rows:
            used_rows = "<tr><td colspan='3'>유효 모델 없음</td></tr>"

        st.markdown(f'''
<table class="cross-val-matrix">
<thead><tr><th>기업유형 소속 확률</th><th>비중</th></tr></thead>
<tbody>{type_rows}</tbody>
</table>

<table class="cross-val-matrix">
<thead><tr><th>적용 평가모델</th><th>모델별 산출가</th><th>혼합 가중치</th></tr></thead>
<tbody>{used_rows}{excluded_rows}</tbody>
</table>

<table class="cross-val-matrix">
<tbody>
    <tr><td><b>기업 분류 유형</b></td><td>{val_eval.get('enterprise_class', '판단 불가')}</td></tr>
    <tr><td><b>분류 근거</b></td><td>{val_eval.get('classification_basis', '-')} (분류 신뢰도 {val_eval.get('classification_confidence', 0):.0f}점)</td></tr>
    <tr><td><b>제외된 모델</b></td><td>{'<br>'.join(f"{d['name']} — {d['reason']}" for d in (val_eval.get('excluded_models') or [])) or '없음'}</td></tr>
    <tr><td><b>권장 매수가 조건</b></td><td>{' · '.join(('✅' if ok else '❌') + ' ' + lb for lb, ok in (val_eval.get('buy_price_checks') or []))}</td></tr>
    <tr><td><b>평가 시점 ROE / PER / PBR</b></td><td>{fmt_num(val_eval.get('roe'), '.2f', '%')} / {fmt_num(val_eval.get('per'), '.2f', '배')} / {fmt_num(val_eval.get('pbr'), '.2f', '배')} (BPS {fmt_num(val_eval.get('bps'), ',.0f', unit_str)})</td></tr>
    <tr><td><b>미수신 입력 지표</b></td><td>{', '.join(val_eval.get('missing_inputs') or []) or '없음'}</td></tr>
    <tr><td><b>가중중앙값 원시 괴리율</b></td><td>{fmt_pct(val_eval.get('raw_upside_pct'))} → 윈저화 후 {fmt_pct(val_eval.get('upside_pct'))}</td></tr>
    <tr><td><b>적정가 신뢰도</b></td><td>{val_eval.get('fair_value_confidence', 0):.0f}점 — {val_eval.get('fair_value_status_note', '')}</td></tr>
    <tr><td><b>할인율 가정</b></td><td>WACC 8.5% / 영구성장률 2.0% (중복 할인 없음)</td></tr>
    <tr><td><b>최종 계산 기준일</b></td><td>{t_ref_date.strftime('%Y-%m-%d')} (Point-in-Time)</td></tr>
</tbody>
</table>
''', unsafe_allow_html=True)

# [Section 11] 조건별 3가지 시나리오 & 가격 대응 전략
with tab_scen:
    show_tab_verdict('scenario')
    st.subheader(f"[{resolved_name}] - 조건별 20일 대응 시나리오 대시보드")
    
    atr_val = tech_df['vol_20'].iloc[-1] if 'vol_20' in tech_df.columns else 0.02
    # Bullish scenario: +1 to +3 ATR
    bull_target = curr_price * (1 + atr_val * 2.0)
    bull_range_low = curr_price * (1 + atr_val * 1.5)
    bull_range_high = curr_price * (1 + atr_val * 3.0)
    bull_stop = curr_price * (1 - atr_val * 1.0)
    # Sideways: -0.5 to +1 ATR  
    side_target = curr_price * (1 - atr_val * 0.5)
    side_range_low = curr_price * (1 - atr_val * 0.75)
    side_range_high = curr_price * (1 + atr_val * 1.0)
    side_stop = curr_price * (1 - atr_val * 1.5)
    # Bearish: -1 to -2 ATR
    bear_target = curr_price * (1 - atr_val * 1.0)
    bear_range_low = curr_price * (1 - atr_val * 2.5)
    bear_range_high = curr_price * (1 - atr_val * 1.5)
    
    st.markdown(f"""
    <table class='cross-val-matrix'>
        <thead>
            <tr>
                <th>시나리오</th>
                <th>진입 조건</th>
                <th>예상 가격 범위</th>
                <th>1차 / 2차 목표가</th>
                <th>손절 및 위험 기준</th>
                <th>실전 대응 전략</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td><b style='color:#35C98B;'>🟢 상승 시나리오</b></td>
                <td>20일선 복귀(`{curr_price*(1 + atr_val*0.5):,.0f}{unit_str}`) + 거래량 1.2배 + 외인 전환</td>
                <td><b>{bull_range_low:,.0f}{unit_str} ~ {bull_range_high:,.0f}{unit_str}</b></td>
                <td>{bull_target*0.95:,.0f}{unit_str} / {bull_target:,.0f}{unit_str}</td>
                <td>{bull_stop:,.0f}{unit_str} 하회 시 무효화</td>
                <td>1차 분할 매수 검토</td>
            </tr>
            <tr>
                <td><b style='color:#F2B84B;'>🟡 횡보 시나리오</b></td>
                <td>60일선 지지(`{curr_price*(1 - atr_val*0.2):,.0f}{unit_str}`) + 거래량 감소 및 RSI 리셋</td>
                <td><b>{side_range_low:,.0f}{unit_str} ~ {side_range_high:,.0f}{unit_str}</b></td>
                <td>{side_target:,.0f}{unit_str} / N/A</td>
                <td>{side_stop:,.0f}{unit_str} 이탈 시 무효화</td>
                <td>관망 및 지지 확인 후 접근</td>
            </tr>
            <tr>
                <td><b style='color:#ff453a;'>🔴 하락 시나리오</b></td>
                <td>60일선 종가 이탈(`{curr_price*(1 - atr_val*0.5):,.0f}{unit_str}` 하회) + 기관 동반 매도</td>
                <td><b>{bear_range_low:,.0f}{unit_str} ~ {bear_range_high:,.0f}{unit_str}</b></td>
                <td>N/A (하방 지지선 탐색)</td>
                <td>종가 {bear_target:,.0f}{unit_str} 이탈 즉시 손절</td>
                <td>비중 축소 / 손절선 준수</td>
            </tr>
        </tbody>
    </table>
    """, unsafe_allow_html=True)
    
    _uk.spacer(28)
    # [Section 1-6 Spec] 목표가격 5종 세트 산출 근거 표
    st.markdown("목표가격 및 손절·위험선 산출 근거 명시적 표")
    st.markdown(f"""
    <table class='cross-val-matrix'>
        <thead>
            <tr>
                <th>구분</th>
                <th>목표 / 위험 가격</th>
                <th>산출 근거 및 공식</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <td><b>1. 시장조정 펀더멘털 적정가</b></td>
                <td><b style='color:#4C8DFF;'>{fmt_num(four_scores.get('displayed_fair_value'), suffix='원', na='미산출 (신뢰도 미달)')}</b></td>
                <td>{four_scores['target_fundamental_note']}</td>
            </tr>
            <tr>
                <td><b>2. 권장 매수가 (안전마진 적용)</b></td>
                <td><b style='color:#35C98B;'>{f"{four_scores['recommended_buy_price']:,.0f}원 이하" if four_scores.get('recommended_buy_price') is not None else "적정가 신뢰도 미달 (미산출)"}</b></td>
                <td>안전마진 {four_scores.get('margin_of_safety_pct', 15):.0f}% 적용 실제 진입 가격</td>
            </tr>
            <tr>
                <td><b>3. 기술적 1차 목표가</b></td>
                <td><b style='color:#4C8DFF;'>{fmt_num(four_scores.get('target_tech_1st'), ',.0f', '원', na='산출 불가')}</b></td>
                <td>{four_scores.get('target_tech_1st_note', '')}</td>
            </tr>
            <tr>
                <td><b>4. 기술적 2차 목표가</b></td>
                <td><b style='color:#4C8DFF;'>{fmt_num(four_scores.get('target_tech_2nd'), ',.0f', '원', na='산출 불가')}</b></td>
                <td>{four_scores.get('target_tech_2nd_note', '')}</td>
            </tr>
            <tr>
                <td><b>5. 손절가 (Stop-Loss)</b></td>
                <td><b style='color:#ff453a;'>{fmt_num(four_scores.get('stop_loss_price'), ',.0f', '원', na='산출 불가')}</b></td>
                <td>{four_scores.get('stop_loss_note', '')}</td>
            </tr>
            <tr>
                <td><b>6. ATR / DeMARK 구조적 위험선</b></td>
                <td><b style='color:#F2B84B;'>{fmt_num(four_scores.get('atr_risk_level'), ',.0f', '원', na='산출 불가')}</b></td>
                <td>{four_scores.get('atr_risk_level_note', '')}</td>
            </tr>
        </tbody>
    </table>
    """, unsafe_allow_html=True)

# DeMARK 9-13 추세 소진 분석 탭
with tab_demark:
    show_tab_verdict('demark')
    dm = four_scores['demark_res']
    
    st.markdown(f"""
    <div style="background-color:#161D2A; padding:20px; border-radius:12px; margin-bottom:20px;">
        <h3 style="color:#F3F6FA; margin-top:0;">⏱️ DeMARK 9-13 결합신호 종합 대시보드</h3>
        <div style="display:flex; justify-content:space-between; flex-wrap:wrap; color:#F3F6FA; font-size:16px; line-height:1.6;">
            <div style="flex:1; min-width:250px;">
                <b style="color:#4C8DFF;">[DeMARK 카운트]</b><br>
                Buy Setup: {dm.get('buy_setup_count', 0)}/9 완료<br>
                Sell Setup: {dm.get('sell_setup_count', 0)}/9 완료<br>
                Perfected: {dm.get('perfected_status', '미충족')}<br>
                Buy Countdown: {dm.get('buy_13_status', '0/13')}<br>
                Sell Countdown: {dm.get('sell_13_status', '0/13')}<br>
                TDST 지지: {dm.get('tdst_support', 0):,.0f}{unit_str}<br>
                TDST 저항: {dm.get('tdst_resistance', 0):,.0f}{unit_str}<br>
            </div>
            <div style="flex:1; min-width:250px;">
                <b style="color:#0a84ff;">[다중 지표 확인]</b><br>
                Bollinger: {dm.get('bb_state', '산출 불가')} (밴드 내 {fmt_num(dm.get('bb_position_pct'), '.0f', '%')} · 폭 {fmt_num(dm.get('bb_width_pct'), '.1f', '%')}){'  ← 하단 재진입' if dm.get('bollinger_lower_reentry') else ('  ← 상단 재진입' if dm.get('bollinger_upper_reentry') else '')}<br>
                Williams %R: {'-80 상향 회복 (매수형)' if dm.get('williams_r_buy_reversal') else '-20 하향 이탈 (매도형)' if dm.get('williams_r_sell_reversal') else f"{dm.get('williams_r_val', 0):.1f}"}<br>
                RSI: {fmt_num(dm.get('rsi_value'), '.0f')}{' (침체권 반등)' if dm.get('rsi_bullish_reversal') else (' (과열권 반락)' if dm.get('rsi_bearish_reversal') else '')}<br>
                거래량: {'조건 충족 (20일 평균 1.2배 상회)' if dm.get('vol_confirmed') else '평이함'}<br>
                ADX 추세강도: {dm.get('adx', 0):.1f}<br>
            </div>
            <div style="flex:1; min-width:250px;">
                <b style="color:#F2B84B;">[최종 판정 점수]</b><br>
                Bullish 점수: {dm.get('bullish_score', 50)} / 100점<br>
                Bearish 점수: {dm.get('bearish_score', 50)} / 100점<br><br>
                <b style="color:#35C98B; font-size:17px;">최종 판정: {dm.get('demark_label', '중립')}</b><br>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown(f"[{resolved_name}] DeMARK 9-13 & 다중 지표 정밀 차트")
    
    recent_dm_df = tech_df.tail(100).copy().reset_index(drop=True)
    dates = pd.to_datetime(recent_dm_df['trade_date'])
    
    # GridSpec Figure
    fig_dm = plt.figure(figsize=(14, 12))
    fig_dm.patch.set_facecolor('#0B0F17')
    gs = fig_dm.add_gridspec(4, 1, height_ratios=[5, 1.5, 1.5, 1.5], hspace=0.15)
    
    ax_main = fig_dm.add_subplot(gs[0, 0])
    ax_vol = fig_dm.add_subplot(gs[1, 0], sharex=ax_main)
    ax_wr = fig_dm.add_subplot(gs[2, 0], sharex=ax_main)
    ax_rsi = fig_dm.add_subplot(gs[3, 0], sharex=ax_main)
    
    for ax in [ax_main, ax_vol, ax_wr, ax_rsi]:
        ax.set_facecolor('#161D2A')
        ax.tick_params(colors='#F3F6FA')
        ax.grid(True, color='#1C2635', linestyle='--')
        
    # 1. Main Chart (Candlestick)
    opens = recent_dm_df['open'].values if 'open' in recent_dm_df.columns else recent_dm_df['adj_close'].values
    closes = recent_dm_df['adj_close'].values
    highs = recent_dm_df['high'].values if 'high' in recent_dm_df.columns else closes
    lows = recent_dm_df['low'].values if 'low' in recent_dm_df.columns else closes
    
    up = closes >= opens
    down = closes < opens
    
    ax_main.bar(dates[up], closes[up] - opens[up], bottom=opens[up], color='#ff453a', width=0.6, edgecolor='#ff453a')
    ax_main.vlines(dates[up], lows[up], highs[up], color='#ff453a', linewidth=1)
    
    ax_main.bar(dates[down], opens[down] - closes[down], bottom=closes[down], color='#0a84ff', width=0.6, edgecolor='#0a84ff')
    ax_main.vlines(dates[down], lows[down], highs[down], color='#0a84ff', linewidth=1)
    
    # MAs & BB
    if 'sma_5' in recent_dm_df: ax_main.plot(dates, recent_dm_df['sma_5'], color='#F2B84B', linewidth=1, label='MA 5')
    if 'sma_20' in recent_dm_df: ax_main.plot(dates, recent_dm_df['sma_20'], color='#4C8DFF', linewidth=1.5, label='MA 20')
    if 'sma_60' in recent_dm_df: ax_main.plot(dates, recent_dm_df['sma_60'], color='#35C98B', linewidth=1.5, label='MA 60')
    
    if 'bb_upper' in recent_dm_df: 
        ax_main.plot(dates, recent_dm_df['bb_upper'], color='#4C8DFF', linestyle=':', linewidth=1.5, label='BB Upper')
        ax_main.plot(dates, recent_dm_df['bb_lower'], color='#4C8DFF', linestyle=':', linewidth=1.5, label='BB Lower')
        ax_main.fill_between(dates, recent_dm_df['bb_lower'], recent_dm_df['bb_upper'], color='#4C8DFF', alpha=0.05)
        
    # TDST
    res_val = dm.get('tdst_resistance')
    sup_val = dm.get('tdst_support')
    if res_val: ax_main.axhline(res_val, color='#F2B84B', linestyle='--', linewidth=1.5, alpha=0.8, label=f'TDST Res ({res_val:,.0f})')
    if sup_val: ax_main.axhline(sup_val, color='#35C98B', linestyle='--', linewidth=1.5, alpha=0.8, label=f'TDST Sup ({sup_val:,.0f})')
    
    # DeMARK Markers (Setup 9 & Countdown 13)
    full_b_setup = dm.get('buy_setup_series', [])
    full_s_setup = dm.get('sell_setup_series', [])
    full_b_cd = dm.get('buy_countdown_series', [])
    full_s_cd = dm.get('sell_countdown_series', [])
    
    b_setup = full_b_setup[-100:] if len(full_b_setup) >= 100 else full_b_setup
    s_setup = full_s_setup[-100:] if len(full_s_setup) >= 100 else full_s_setup
    b_cd = full_b_cd[-100:] if len(full_b_cd) >= 100 else full_b_cd
    s_cd = full_s_cd[-100:] if len(full_s_cd) >= 100 else full_s_cd
    
    for i in range(len(closes)):
        b_cnt = int(b_setup[i]) if i < len(b_setup) else 0
        s_cnt = int(s_setup[i]) if i < len(s_setup) else 0
        b_c_cnt = int(b_cd[i]) if i < len(b_cd) else 0
        s_c_cnt = int(s_cd[i]) if i < len(s_cd) else 0
        
        p_range = highs[i] - lows[i] if highs[i] != lows[i] else closes[i]*0.02
        
        # Setup Markers (Green for Buy, Red for Sell)
        if b_cnt > 0:
            ax_main.text(dates[i], lows[i] - p_range*0.8, str(b_cnt), color='#35C98B', fontsize=9, ha='center', va='top', fontweight='bold')
            if b_cnt == 9:
                ax_main.scatter(dates[i], lows[i] - p_range*1.6, color='#35C98B', marker='^', s=160, zorder=5)
                ax_main.annotate('매수준비 9', xy=(dates[i], lows[i] - p_range*2.8), color='#35C98B', fontsize=10, ha='center', va='top', fontweight='bold', backgroundcolor='#161D2A')
                
        if s_cnt > 0:
            ax_main.text(dates[i], highs[i] + p_range*0.8, str(s_cnt), color='#ff453a', fontsize=9, ha='center', va='bottom', fontweight='bold')
            if s_cnt == 9:
                ax_main.scatter(dates[i], highs[i] + p_range*1.6, color='#ff453a', marker='v', s=160, zorder=5)
                ax_main.annotate('매도경계 9', xy=(dates[i], highs[i] + p_range*2.8), color='#ff453a', fontsize=10, ha='center', va='bottom', fontweight='bold', backgroundcolor='#161D2A')
        
        # Countdown 13 Markers (High Priority)
        if b_c_cnt >= 13:
            ax_main.scatter(dates[i], lows[i] - p_range*2.0, color='#35C98B', marker='D', s=200, zorder=8)
            ax_main.annotate('13 확정 · 매수 타이밍', xy=(dates[i], lows[i] - p_range*3.8), color='#35C98B', fontsize=11, ha='center', va='top', fontweight='bold', backgroundcolor='#161D2A')
        elif s_c_cnt >= 13:
            ax_main.scatter(dates[i], highs[i] + p_range*2.0, color='#ff453a', marker='D', s=200, zorder=8)
            ax_main.annotate('13 확정 · 매도 타이밍', xy=(dates[i], highs[i] + p_range*3.8), color='#ff453a', fontsize=11, ha='center', va='bottom', fontweight='bold', backgroundcolor='#161D2A')

    # Info Box inside Chart (Top Left overlay)
    info_str = f"[DeMARK 9-13 현황]\n" \
               f"• Buy Setup: {dm.get('buy_setup_count', 0)}/9\n" \
               f"• Sell Setup: {dm.get('sell_setup_count', 0)}/9\n" \
               f"• Perfected: {dm.get('perfected_status', '미충족')}\n" \
               f"• Buy Countdown: {dm.get('buy_13_status', '0/13')}\n" \
               f"• Sell Countdown: {dm.get('sell_13_status', '0/13')}\n" \
               f"• TDST 지지: {dm.get('tdst_support', 0):,.0f}{unit_str}\n" \
               f"• TDST 저항: {dm.get('tdst_resistance', 0):,.0f}{unit_str}"

    ax_main.text(0.02, 0.96, info_str, transform=ax_main.transAxes, fontsize=8,
                 verticalalignment='top', color='#F3F6FA',
                 bbox=dict(boxstyle='round,pad=0.4', facecolor='#161D2A', alpha=0.8, edgecolor='#222C3C', lw=1),
                 zorder=12)

    ax_main.set_ylabel('Price', color='#9DAABC')
    ax_main.legend(loc='upper right', facecolor='#161D2A', edgecolor='#1C2635', labelcolor='#F3F6FA', fontsize=8)
    
    # 2. Volume
    vols = recent_dm_df['volume'].values
    vols_ma = recent_dm_df['vol_20_avg'].values if 'vol_20_avg' in recent_dm_df else None
    
    ax_vol.bar(dates[up], vols[up], color='#ff453a', alpha=0.7)
    ax_vol.bar(dates[down], vols[down], color='#0a84ff', alpha=0.7)
    if vols_ma is not None:
        ax_vol.plot(dates, vols_ma, color='#F3F6FA', linewidth=1.5, label='Vol MA20')
    ax_vol.set_ylabel('Volume', color='#9DAABC')
    ax_vol.legend(loc='upper left', facecolor='#161D2A', edgecolor='#1C2635', labelcolor='#F3F6FA', fontsize=8)
    
    # 3. Williams %R
    if 'williams_r' in recent_dm_df:
        wr = recent_dm_df['williams_r'].values
        ax_wr.plot(dates, wr, color='#4C8DFF', linewidth=1.5)
        ax_wr.axhline(-20, color='#ff453a', linestyle=':')
        ax_wr.axhline(-80, color='#35C98B', linestyle=':')
        ax_wr.fill_between(dates, 0, -20, color='#ff453a', alpha=0.1)
        ax_wr.fill_between(dates, -80, -100, color='#35C98B', alpha=0.1)
        ax_wr.set_ylim(-100, 0)
    ax_wr.set_ylabel('Williams %R', color='#9DAABC')
    
    # 4. RSI
    if 'rsi_14' in recent_dm_df:
        rsi = recent_dm_df['rsi_14'].values
        ax_rsi.plot(dates, rsi, color='#4C8DFF', linewidth=1.5)
        ax_rsi.axhline(70, color='#ff453a', linestyle=':')
        ax_rsi.axhline(50, color='#F3F6FA', linestyle='--', alpha=0.3)
        ax_rsi.axhline(30, color='#35C98B', linestyle=':')
        ax_rsi.fill_between(dates, 70, 100, color='#ff453a', alpha=0.1)
        ax_rsi.fill_between(dates, 0, 30, color='#35C98B', alpha=0.1)
        ax_rsi.set_ylim(0, 100)
    ax_rsi.set_ylabel('RSI 14', color='#9DAABC')
    
    plt.tight_layout()
    st.pyplot(fig_dm)

with tab_flow:
    show_tab_verdict('technical')
    st.subheader(f"[{resolved_name}] - 기술적 캔들/이동평균선 & 수급 차트 점검")
    
    is_settled, settled_msg = q_engine.check_20sma_settlement(tech_df)
    st.info(f"**20일선 안착 정량 규칙 검증**: {settled_msg}")
    
    recent_tech = tech_df.tail(90)
    x_dates = pd.to_datetime(recent_tech['trade_date'])
    
    # 📈 [1] 3-Subplot 프리미엄 기술적 주가 콤보 차트 (가격/이동평균선, RSI, 거래량)
    fig_tech, (ax_price, ax_rsi, ax_vol) = plt.subplots(3, 1, figsize=(12, 9), sharex=True, gridspec_kw={'height_ratios': [3, 1, 1]})
    fig_tech.patch.set_facecolor('#0B0F17')
    
    for ax in (ax_price, ax_rsi, ax_vol):
        ax.set_facecolor('#161D2A')
        ax.tick_params(colors='#F3F6FA')
        ax.grid(True, color='#1C2635', linestyle='--')
        
    # (1) 주가 및 5·20·60·120일 이동평균선
    ax_price.plot(x_dates, recent_tech['adj_close'], label=f"{resolved_name} 수정종가", color='#F3F6FA', linewidth=2.5)
    ax_price.plot(x_dates, recent_tech['sma_5'], label="5일선 (단기)", color='#4C8DFF', linestyle='-', linewidth=1.5)
    ax_price.plot(x_dates, recent_tech['sma_20'], label="20일선 (중기)", color='#F2B84B', linestyle='-', linewidth=2.0)
    ax_price.plot(x_dates, recent_tech['sma_60'], label="60일선 (수급선)", color='#4C8DFF', linestyle='--', linewidth=1.5)
    ax_price.plot(x_dates, recent_tech['sma_120'], label="120일선 (장기)", color='#FF453A', linestyle=':', linewidth=1.5)
    
    ax_price.set_title(f"[{resolved_name}] 이동평균선(5·20·60·120일) & 기술적 분석 차트", color='#F3F6FA', fontsize=13, fontweight='bold')
    ax_price.set_ylabel(f"주가 ({unit_str})", color='#9DAABC')
    ax_price.legend(facecolor='#161D2A', edgecolor='#1C2635', labelcolor='#F3F6FA', loc='upper left')
    
    # (2) RSI 14 모멘텀 지표
    ax_rsi.plot(x_dates, recent_tech['rsi_14'], label="RSI 14", color='#4C8DFF', linewidth=1.8)
    ax_rsi.axhline(70, color='#ff453a', linestyle='--', alpha=0.7, label="과매수(70)")
    ax_rsi.axhline(30, color='#35C98B', linestyle='--', alpha=0.7, label="과매도(30)")
    ax_rsi.set_ylabel("RSI (14)", color='#9DAABC')
    ax_rsi.set_ylim(10, 90)
    ax_rsi.legend(facecolor='#161D2A', edgecolor='#1C2635', labelcolor='#F3F6FA', loc='upper left')
    
    # (3) 거래량 차트 & 20일 평균선
    ax_vol.bar(x_dates, recent_tech['volume'], color='#4C8DFF', alpha=0.7, label="거래량")
    ax_vol.plot(x_dates, recent_tech['vol_20_avg'], color='#F2B84B', linewidth=1.5, label="20일 평균 거래량")
    ax_vol.set_ylabel("거래량 (주)", color='#9DAABC')
    ax_vol.set_xlabel("거래일자", color='#9DAABC')
    ax_vol.legend(facecolor='#161D2A', edgecolor='#1C2635', labelcolor='#F3F6FA', loc='upper left')
    
    plt.tight_layout()
    st.pyplot(fig_tech)
    
    _uk.spacer(28)
    st.markdown("최근 60영업일 3대 주체 (외국인 · 기관 · 개인) 누적 순매수 동향")

    recent_flow = tech_df.tail(60)
    flow_cols = ['foreign_cum_5d', 'institution_cum_5d', 'retail_cum_5d']
    flow_available = all(c in recent_flow.columns for c in flow_cols) and \
        not recent_flow[flow_cols].isna().all().all()

    if not flow_available:
        # 구버전은 sin/cos 파형 + 정규난수로 만든 곡선을 실제 수급인 것처럼 그렸다.
        st.info("**투자자별 수급 데이터 미연동** — 외국인·기관·개인 순매매 시계열은 현재 연결되어 있지 않습니다. "
                "임의 생성한 곡선을 표시하지 않기 위해 차트를 비워 둡니다. "
                "(이 항목은 DeMARK 수급 확인 가점에서도 제외되어 점수에 반영되지 않습니다.)")
    else:
        fig_flow, ax_f = plt.subplots(figsize=(12, 4.5))
        fig_flow.patch.set_facecolor('#0B0F17')
        ax_f.set_facecolor('#161D2A')
        x_flow_dates = pd.to_datetime(recent_flow['trade_date'])
        ax_f.plot(x_flow_dates, recent_flow['foreign_cum_5d']/1e8, label="외국인 5일 누적 (억원)", color='#35C98B', linewidth=2)
        ax_f.plot(x_flow_dates, recent_flow['institution_cum_5d']/1e8, label="기관 5일 누적 (억원)", color='#4C8DFF', linewidth=2)
        ax_f.plot(x_flow_dates, recent_flow['retail_cum_5d']/1e8, label="개인 5일 누적 (억원)", color='#ff453a', linestyle=':', linewidth=1.5)
        ax_f.axhline(0, color='#F3F6FA', linestyle='--', alpha=0.5)
        ax_f.set_title(f"[{resolved_name}] 3대 주체 순매수 수급 차트", color='#F3F6FA', fontsize=12)
        ax_f.tick_params(colors='#F3F6FA')
        ax_f.grid(True, color='#1C2635', linestyle='--')
        ax_f.legend(facecolor='#161D2A', edgecolor='#1C2635', labelcolor='#F3F6FA')
        st.pyplot(fig_flow)

# [Section 7, 12, 13] SR 11-7 무결성 감사 및 모델 성능 검증 대시보드
with tab_audit:
    show_tab_verdict('integrity')
    st.subheader(f"[{resolved_name}] - SR 11-7 무결성 감사 및 모델 성능 대시보드")
    
    is_large_cap = (val_eval.get("enterprise_class") in ["대형 우량 기술주 (Large Quality)", "대형 경기민감 제조기업 (Automotive / Cyclical Mfg)"] or curr_price > 100000.0)
    cost_metrics = q_engine.calculate_backtest_costs_and_metrics(
        sim_res, oos=snap.get('oos_result'), is_large_cap=is_large_cap)

    # ── [명세 §14] 표본외(Blind/OOS) 검증 결과 ────────────────────────────
    _oos = snap.get('oos_result') or {}
    _sq = snap.get('strategy_quality') or {}
    st.markdown("표본외(Blind / Out-of-Sample) Walk-Forward 검증")
    if not _oos.get('available'):
        st.warning(f"표본외 검증 미수행 — {_oos.get('reason', '사유 미상')}. "
                   f"최종 행동점수 상한 {four_scores.get('sq_cap')}점이 적용됩니다.")
    else:
        o1, o2, o3, o4 = st.columns(4)
        o1.metric("전략 품질점수", fmt_num(_sq.get('score'), '.1f', '점'),
                  f"상한 {four_scores.get('sq_cap')}점")
        o2.metric("방향 적중률", fmt_pct(_oos['directional_hit_pct'], signed=False),
                  f"표본외 {_oos['n_predictions']}건")
        o3.metric("Brier / MAE", f"{_oos['brier_score']} / {_oos['mae_pct']}%", "확률 보정 품질")
        o4.metric("Sharpe / MDD", f"{_oos['sharpe']} / {_oos['mdd_pct']}%",
                  f"{_oos['n_trades']}회 매매")
        st.caption(
            f"학습 {_oos['train_bars']}봉 → 검증 {_oos['oos_bars']}봉 (시작 {_oos['oos_start_date']}) · "
            f"purge embargo {_oos['embargo']}봉 · 진입 임계 {q_engine.OOS_ENTRY_PROB:.0f}% · "
            f"거래비용 {q_engine.TOTAL_COST_PCT}% 차감 후 "
            f"전략 {fmt_pct(_oos['net_return_pct'])} vs 매수보유 {fmt_pct(_oos['buy_hold_pct'])} "
            f"(초과 {fmt_pct(_oos['excess_vs_buy_hold'])}p)")
        with st.expander("전략 품질 구성요소 보기"):
            st.dataframe(pd.DataFrame([
                {"항목": k, "환산점수": v, "가중치": _sq['weights'].get(k)}
                for k, v in _sq['components'].items()]),
                width='stretch', hide_index=True)
    _uk.spacer(28)
    
    c1, c2 = st.columns(2)
    with c1:
        # ⚠️ 표본이 부족하면 mean_perf 가 None 이다. 여기에 :.1f 를 직접 쓰면
        #    화면 전체가 TypeError 로 죽는다 (실제로 클라우드에서 발생).
        #    부호도 하드코딩하면 안 된다 — 손실인데 '+' 가 붙는다.
        _raw_perf = cost_metrics.get('raw_perf')
        _net_perf = cost_metrics.get('net_perf')
        _net_color = "#35C98B" if (_net_perf or 0) >= 0 else "#ff453a"
        st.markdown(f"""
        <div style='background: #161D2A; border-radius: 16px; padding: 20px;'>
            <h4 style='color: #4C8DFF !important; margin-top:0;'>백테스트 거래비용 차감 후 모델 성과 (Section 7 & 12)</h4>
            <p>- <b>비용 반영 전 수익률</b>: <b>{fmt_pct(_raw_perf)}</b></p>
            <p>- <b>총 거래비용 (수수료+세금+슬리피지)</b>: <b>-{fmt_num(cost_metrics.get('total_cost_pct'), '.3f', '%')}</b></p>
            <p>- <b>비용 반영 후 실질 수익률</b>: <span style='color:{_net_color};'><b>{fmt_pct(_net_perf)}</b></span></p>
            <hr style='border-color:#1C2635;'>
            <p>- <b>20일 관찰 승률</b>: <b>{fmt_pct(cost_metrics['win_rate_20d'], signed=False)}</b> | <b>Profit Factor</b>: <b>{fmt_num(cost_metrics['profit_factor'], spec='.2f')}</b></p>
            <p>- <b>Brier Score</b>: <b>{fmt_num(cost_metrics['brier_score'], spec='.3f')}</b> | <b>MAE</b>: <b>{fmt_pct(cost_metrics['mae_pct'], signed=False)}</b></p>
            <p style='color:#9DAABC; font-size:13px;'>표본 등급: {cost_metrics['sample_note']}</p>
            <p style='color:#F2B84B; font-size:13px;'>⚠️ {cost_metrics['calibration_status']}</p>
        </div>
        """, unsafe_allow_html=True)
        
    with c2:
        st.markdown(f"""
        <div style='background: #161D2A; border-radius: 16px; padding: 20px;'>
            <h4 style='color: #35C98B !important; margin-top:0;'>SR 11-7 모델 리스크 관리 감사 카드 (Section 13)</h4>
            <p>- <b>기준시점 ($t_{{ref}}$)</b>: <b>{snapshot.get('t_ref') if snapshot else '2026-07-30'}</b></p>
            <p>- <b>미래 데이터 차단 건수</b>: <b>{snapshot.get('blocked_future_count') if snapshot else 0} 건 (PTA 통제 완료)</b></p>
            <p>- <b>Shapley-DCLR 미래 누수율</b>: <b style='color:#F2B84B;'>{snapshot.get('shapley_dclr_status') if snapshot else '미산출'}</b></p>
            <p>- <b>중복 유사 패턴 제거</b>: <b>적용 (지평별 최소 H영업일 이격)</b></p>
            <p>- <b>SR 11-7 무결성 루브릭</b>: <b style='color:{"#35C98B" if sr117_audit.get("is_passed") else "#F2B84B"};'>{sr117_audit.get('total_score', 0)}/100점 ({'통과' if sr117_audit.get('is_passed') else '미달'})</b>
               <span style='font-size:13px; color:#9DAABC;'>— 이중시점 {sr117_audit.get('bitemporal_score',0)} / 연산 {sr117_audit.get('math_score',0)} / 일관성 {sr117_audit.get('consistency_score',0)} / 통계 {sr117_audit.get('stat_score',0)} / 가드레일 {sr117_audit.get('guardrail_score',0)}</span></p>
            <p>- <b>금지 표현 자동 교정</b>: <b>{guard_res.get('violations_found', 0)}건</b></p>
            <p>- <b>규칙집 버전</b>: <code>{quant_indicators.QuantIndicatorsEngine.RULEBOOK_VERSION}</code> | <b>Run ID</b>: <code>{run_id}</code></p>
        </div>
        """, unsafe_allow_html=True)
        
    _uk.spacer(28)
    
    # 📊 [Section 20-3 & 20-7 & 20-14] 벤치마크 대조 & 팩터 귀속 분해 & 위험예산 대시보드
    # 지수·보유 포트폴리오를 실제로 넘겨야 이 패널들이 값을 낸다.
    # 인자를 안 넘기면 전부 '미연동'으로 떨어진다 (구버전이 그랬다).
    bench_data = q_engine.calculate_benchmark_comparisons(
        sim_res, tech_df=tech_df, b_engine=engine_init)
    factor_data = q_engine.calculate_factor_attribution(
        sim_res, tech_df=tech_df, b_engine=engine_init)
    risk_budget = q_engine.calculate_portfolio_risk_budget(
        positions=st.session_state.get('positions'), b_engine=engine_init,
        market_regime_code=four_scores.get('market_regime_code'))

    st.markdown("전략 유효성 벤치마크 대조 & 팩터 귀속 분해 대시보드")
    ba1, ba2 = st.columns(2)

    with ba1:
        st.markdown(f"""
        <div style='background: #161D2A; border-radius: 14px; padding: 20px;'>
            <h4 style='color: #4C8DFF !important; margin-top:0;'>전략 유효성 벤치마크 직접 대조 (Section 20-3)</h4>
            <p>- <b>패턴 조건부 전략 (20일)</b>: <b style='color:#35C98B;'>{fmt_pct(bench_data['ai_perf'], digits=2)}</b></p>
            <p>- <b>동일 종목 무조건 보유</b>: <b>{fmt_pct(bench_data['buy_hold_perf'], digits=2)}</b></p>
            <p>- <b>20일선 위에서만 보유</b>: <b>{fmt_pct(bench_data['trend20d_perf'], digits=2)}</b></p>
            <p>- <b>KOSPI200 지수</b>: <b>{fmt_pct(bench_data['kospi200_perf'], digits=2)}</b>
               <span style='color:#9DAABC;font-size:13px;'>({bench_data['kospi200_note']})</span></p>
            <hr style='border-color:#1C2635; margin:8px 0;'>
            <p style='font-size:13px; color:#F2B84B; margin:0;'>💡 <b>판정</b>: {bench_data['judge_text']}</p>
        </div>
        """, unsafe_allow_html=True)

    with ba2:
        if factor_data.get('available'):
            _alpha_col = "#35C98B" if (factor_data['alpha_annual_pct'] or 0) >= 0 else "#ff453a"
            st.markdown(f"""
            <div style='background: #161D2A; border-radius: 14px; padding: 20px;'>
                <h4 style='color: #4C8DFF !important; margin-top:0;'>수익률 팩터 귀속 분해 (Section 20-7)</h4>
                <p style='font-size:13px; color:#9DAABC; margin-top:0;'>{factor_data['model']} · {factor_data['n_days']}일</p>
                <p>- <b>시장 베타 (β)</b>: <b>{factor_data['beta']:.3f}</b>
                   · 설명력 R² <b>{factor_data['r_squared']:.3f}</b></p>
                <p>- <b>시장 설명분</b>: <b>{fmt_pct(factor_data['market_contribution_pct'], digits=1)}</b></p>
                <p>- <b>알파 (잔차)</b>: <b style='color:{_alpha_col};'>{fmt_pct(factor_data['alpha_contribution_pct'], digits=1)}</b>
                   · 연환산 <b style='color:{_alpha_col};'>{fmt_pct(factor_data['alpha_annual_pct'], digits=2)}</b></p>
                <p>- <b>실현 총수익률</b>: <b>{fmt_pct(factor_data['realized_total_pct'], digits=1)}</b></p>
                <hr style='border-color:#1C2635; margin:8px 0;'>
                <p style='font-size:13px; color:#F2B84B; margin:0;'>⚠️ 미연동 팩터: {', '.join(factor_data['missing_factors'])} — {factor_data['missing_reason']}</p>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div style='background: #161D2A; border-radius: 14px; padding: 20px;'>
                <h4 style='color: #9DAABC !important; margin-top:0;'>수익률 팩터 귀속 분해 (Section 20-7)</h4>
                <p style='color:#9DAABC;'><b>미산출</b></p>
                <p style='font-size:13px; color:#9DAABC;'>사유: {factor_data['reason']}</p>
                <p style='font-size:13px; color:#9DAABC;'>관찰 총수익률만 제공: <b>{fmt_pct(factor_data['total_perf'], digits=2)}</b></p>
            </div>
            """, unsafe_allow_html=True)

    if risk_budget.get('available'):
        _cash = risk_budget['recommended_cash_pct']
        _ccol = "#ff453a" if _cash >= 40 else ("#F2B84B" if _cash >= 25 else "#35C98B")
        _hrows = "".join(
            f"<tr><td style='padding:4px 8px;'>{h['name']}</td>"
            f"<td style='padding:4px 8px;text-align:right;'>{h['weight_pct']:.1f}%</td>"
            f"<td style='padding:4px 8px;text-align:right;'>{h['vol_annual_pct']:.1f}%</td>"
            f"<td style='padding:4px 8px;text-align:right;'>{fmt_pct(h['risk_share_pct'], digits=1)}</td></tr>"
            for h in risk_budget['holdings'])
        st.markdown(f"""
        <div style='background: #161D2A; border-radius: 14px; padding: 16px; margin-top: 12px;'>
            <h4 style='color: #F3F6FA !important; margin-top:0;'>포트폴리오 위험예산 & 현금 비중 가이드 (Section 20-14 &amp; 20-15)</h4>
            <p style='font-size:13px;color:#9DAABC;margin-top:0;'>보유 {risk_budget['n_holdings']}종목 · 최근 {risk_budget['window_days']}거래일 · 평가금액 {risk_budget['total_value']:,.0f}원</p>
            <table style='width:100%; font-size:15px; color:#9DAABC; border-collapse:collapse;'>
                <tr style='color:#4C8DFF;'><th style='text-align:left;padding:4px 8px;'>종목</th>
                    <th style='text-align:right;padding:4px 8px;'>비중</th>
                    <th style='text-align:right;padding:4px 8px;'>연변동성</th>
                    <th style='text-align:right;padding:4px 8px;'>위험기여</th></tr>
                {_hrows}
            </table>
            <hr style='border-color:#1C2635; margin:8px 0;'>
            <p style='margin:2px 0;'>- 집중도 HHI <b>{risk_budget['hhi']:.3f}</b> (유효 종목수 <b>{risk_budget['effective_n']:.1f}개</b>)</p>
            <p style='margin:2px 0;'>- 종목 간 평균 상관 <b>{fmt_num(risk_budget['avg_correlation'], '.2f')}</b> · 최대 <b>{fmt_num(risk_budget['max_correlation'], '.2f')}</b></p>
            <p style='margin:2px 0;'>- 포트폴리오 연환산 변동성 <b>{risk_budget['portfolio_vol_annual_pct']:.1f}%</b>
               (개별 가중평균 {risk_budget['weighted_indiv_vol_pct']:.1f}% → 분산효과 <b>{risk_budget['diversification_benefit_pct']:.1f}%</b>)</p>
            <p style='margin:2px 0;'>- 과거 최대낙폭 <b style='color:#ff453a;'>{risk_budget['historical_mdd_pct']:.1f}%</b></p>
            <p style='margin:8px 0 2px;'>- <b>권장 현금 비중</b>: <b style='color:{_ccol}; font-size:17px;'>{_cash:.0f}%</b></p>
            <p style='font-size:13px; color:#9DAABC; margin:2px 0;'>사유: {' · '.join(risk_budget['cash_reasons'])}</p>
            <p style='font-size:12px; color:#9DAABC; margin-top:8px;'>ℹ️ {risk_budget['note']}</p>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div style='background: #161D2A; border-radius: 14px; padding: 16px; margin-top: 12px;'>
            <h4 style='color: #9DAABC !important; margin-top:0;'>포트폴리오 위험예산 & 현금 비중 가이드 (Section 20-14 &amp; 20-15)</h4>
            <p style='margin: 4px 0; font-size:15px; color:#9DAABC;'><b>미산출</b> — {risk_budget['reason']}</p>
            <p style='margin: 4px 0; font-size:13px; color:#4C8DFF;'>보유종목을 등록하면 비중·집중도·상관·변동성·권장 현금비중이 실제 일봉으로 계산됩니다.</p>
        </div>
        """, unsafe_allow_html=True)
    
    # ── 배당 · 배당락 분석 ────────────────────────────────────────────────
    st.markdown("배당 & 배당락 분석")
    _div = div_info      # 헤더와 같은 객체 — 두 번 조회하지도, 두 값을 만들지도 않는다
    if not _div.get('available'):
        st.info(f"배당 정보 미산출 — {_div.get('reason')}")
    else:
        _dte = _div['days_to_ex']
        _yld = _div['dividend_yield_pct'] or 0.0
        # 배당락 임박 판단: 진입 가치는 '배당수익률 > 거래비용' 이고 퀀트 조건도 통과할 때만.
        # 배당만 보고 들어가면 배당락 갭하락으로 세후 손실이 나는 경우가 많다.
        _cost = q_engine.TOTAL_COST_PCT
        _net_edge = _yld - _cost
        _quant_ok = four_scores.get('final_action_score', 0) >= q_engine.TOP3_MIN_ACTION_SCORE
        _entry_ok = four_scores.get('entry_zone') in (
            "안전마진 확보", "적정가 이하 (안전마진 미확보)")

        if _dte is not None and 0 <= _dte <= 30:
            if _net_edge > 0 and _quant_ok and _entry_ok:
                _verdict, _vcol = ("배당 + 퀀트 조건 동시 충족 — 분할 진입 검토 가능", "#35C98B")
            elif _net_edge <= 0:
                _verdict, _vcol = (
                    f"배당수익률 {_yld:.2f}%가 왕복 거래비용 {_cost:.2f}%를 넘지 못함 — "
                    f"배당만 노린 진입은 손실", "#ff453a")
            else:
                _miss = []
                if not _quant_ok:
                    _miss.append(f"행동점수 {four_scores.get('final_action_score')} < {q_engine.TOP3_MIN_ACTION_SCORE}")
                if not _entry_ok:
                    _miss.append(f"진입구간 '{four_scores.get('entry_zone')}'")
                _verdict, _vcol = ("배당은 매력적이나 퀀트 조건 미달 — " + " · ".join(_miss),
                                   "#F2B84B")
        else:
            _verdict, _vcol = (f"배당락까지 {_dte}일 — 아직 배당 전략 구간이 아닙니다 "
                               f"(30일 이내부터 판정)", "#9DAABC")

        st.markdown(f"""
        <div style='background:#161D2A; border-radius:14px; padding:16px;'>
            <p style='margin:2px 0;'>- <b>주당배당금(DPS)</b>: <b>{fmt_num(_div.get('dps'), ',.0f', '원', na='미공시')}</b>
               · <b>배당수익률</b>: <b>{fmt_pct(_div.get('dividend_yield_pct'), digits=2)}</b>
               (현재가 {fmt_num(realtime_price, ',.0f', '원')} 기준)</p>
            <p style='margin:2px 0;'>- <b>추정 배당락일</b>: <b>{_div['estimated_ex_date']}</b>
               (D-{_dte}) · 추정 배당기준일 {_div['estimated_record_date']}</p>
            <p style='margin:2px 0;'>- <b>배당락 이론 하락폭</b>: 약 <b>{fmt_pct(_div['expected_drop_pct'], digits=2)}</b>
               · 왕복 거래비용 {_cost:.2f}% → <b style='color:{"#35C98B" if _net_edge > 0 else "#ff453a"};'>순 {_net_edge:+.2f}%p</b></p>
            <hr style='border-color:#1C2635; margin:8px 0;'>
            <p style='margin:2px 0; color:{_vcol};'><b>판정</b>: {_verdict}</p>
            <p style='font-size:12px; color:#F2B84B; margin-top:8px;'>⚠️ {_div['note']}</p>
        </div>
        """, unsafe_allow_html=True)

    _uk.spacer(28)
    st.markdown("10대 표준 레포트 원문 정밀 전체 보기")
    with st.expander("[클릭] 10대 표준 퀀트 레포트 원문 전체 펼쳐보기", expanded=True):
        st.markdown(f"""
        <div style='background: #161D2A; border-radius: 14px; padding: 24px 28px; line-height: 1.8;'>
            {report_text}
        </div>
        """, unsafe_allow_html=True)

_uk.spacer(28)

# 데이터 출처 교차검증 상태표 (Section 2 & P1-4 Matrix)
st.markdown("데이터 출처별 교차검증 상태표 (5대 출처 우선순위)")
st.markdown(f"""
<table class='cross-val-matrix'>
    <thead>
        <tr>
            <th>출처명 (Priority Source)</th>
            <th>수신 시각</th>
            <th>기준 거래일</th>
            <th>현재가</th>
            <th>가격 유형</th>
            <th>상태</th>
            <th>지연시간</th>
            <th>일치 여부</th>
        </tr>
    </thead>
    <tbody>
        {"".join([
            "<tr>"
            f"<td><b>{row['source']}</b></td>"
            f"<td>{row['fetch_time']}</td>"
            f"<td>{row['trade_date']}</td>"
            # 미연동 출처는 가격을 표시하지 않는다 (구버전은 6개 행 전부 현재가를 찍었다)
            f"<td>{fmt_num(row['price'], suffix=unit_str, na='—')}</td>"
            f"<td>{row['price_type']}</td>"
            f"<td><span style='color:{'#35C98B' if '정상' in row['status'] else ('#4C8DFF' if '간접' in row['status'] else '#9DAABC')};'>{row['status']}</span></td>"
            f"<td>{row['delay']}</td>"
            f"<td><span style='color:{'#35C98B' if '일치' in row['diff'] else '#9DAABC'};'>{row['diff']}</span></td>"
            "</tr>"
            "<tr>"
            f"<td colspan='8' style='padding:2px 12px 8px; color:#9DAABC; font-size:13px; border-top:none;'>"
            f"↳ 이 빌드에서의 실제 사용처: {row.get('role', '—')}</td>"
            "</tr>"
            for row in matrix_data])}
    </tbody>
</table>
""", unsafe_allow_html=True)

_uk.spacer(28)
st.caption("본 시뮬레이터는 네이버증권·다음금융 웹 데이터에 기초한 참고용 정보이며, 특정 종목의 매수·매도 권유가 아닙니다. "
           "투자 판단과 손익의 최종 책임은 투자자 본인에게 있습니다. "
           "KRX·DART·FnGuide 데이터는 네이버 종목페이지를 경유해 간접적으로 사용하며(거래일 달력·업종분류·재무·투자지표), "
           "각 기관 API 직접 조회는 연동되어 있지 않습니다. 표의 '실제 사용처' 행을 참고하세요.")
