import sys
import textwrap
import time
import re as _re_wa
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
import etf_registry              # ETF 이름·코드·NAV (라운드 164)
import stock_code                # 단축코드를 읽는 한 곳 (라운드 164)
import forward_eval as _fe      # 전방 재평가일 — 단일 출처 (라운드 78)
importlib.reload(market_attention)

from bitemporal_engine import STOCK_NAME_MAP, BitemporalEngine
# 시장(KOSPI/KOSDAQ) 유도는 **엔진의 단일 진입점** 하나만 쓴다(라운드 159).
# 화면에서 `'.KQ' in sym` 을 직접 쓰면 시장을 못 읽은 종목이
# 조용히 한쪽으로 분류된다. 모르면 None 이 돌아오게 한다.
from bitemporal_engine import market_of as _market_of
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

#: 검사가 사용자 자료를 건드리지 않게 하는 스위치 (라운드 165).
#:
#: ⚠️ 실제로 그런 일이 있었다. 라운드 164 가 '최근 본 종목'을 파일에
#:   남기게 했는데, 회귀의 AppTest 렌더가 돌 때마다 **사용자의 목록에
#:   테스트 종목(SK하이닉스·다날·CJ ENM …)이 쌓였다.** 검사가 사용자
#:   자료를 바꾸면 안 된다 (§9 — 보유·관심 자료는 사용자의 것이다).
#:
#: `scripts/render_probe.py` 가 이 값을 켜고, 화면은 그때 **어떤 로컬
#: 파일도 쓰지 않는다.** 읽기는 그대로 둔다 — 검사는 실제 자료 위에서
#: 돌아야 화면이 진짜로 그리는지 알 수 있다.
NO_LOCAL_WRITE = bool(os.environ.get('GAEUM_NO_LOCAL_WRITE'))


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
    page_icon="G",
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


# ── 부호가 있는 값의 색 (라운드 175) ──────────────────────────────────
#
# ⚠️ 라운드 174 는 '두 색 중 고르는' 줄을 고쳤다. 그런데 **반대도 결함**
#   이다 — `+`/`-` 가 붙는 값에 **한 색을 박아** 두면 음수일 때도 그 색이
#   나온다. 실측으로 둘이 걸렸다:
#     · 상대적 밸류에이션 룸 — 음수(고평가)여도 초록
#     · 패턴 조건부 전략 성과 — **우리 전략만** 초록이고 벤치마크 셋은
#       무채색이었다. 성과가 음수여도 초록으로 나가는 자리라 §9
#       ('성과를 좋게 보이게 쓰지 않는다')에 걸린다.
#
# 값이 없으면 **색을 주지 않는다** — 없는 값을 색으로 판단하지 않는다 (§3).
def _signed_col(v, kind='price'):
    """부호에 따른 색. `kind='price'` 는 한국 관행(오르면 빨강),
    `kind='perf'` 는 좋다/나쁘다(초록/빨강)."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return _TOK['tx2']
    if kind == 'perf':
        return _TOK['pos'] if x >= 0 else _TOK['neg']
    return _TOK['up'] if x >= 0 else _TOK['down']


def _perf_col(v):
    """성과 값의 색 — 벤치마크와 **같은 잣대**로 칠한다 (§9)."""
    return _signed_col(v, kind='perf')


def _md_safe(text):
    """
    엔진이 만든 문장을 마크다운 위젯에 넘기기 전에 이스케이프한다.

    ■ 실제 사고 (라운드 44)
      `price_axes` 의 근거 문구 "이익·장부가 모델 5종의 25~75분위 범위
      (넓게 보면 88,863~173,641원)" 가 화면에 **"25 75분위 범위 (넓게
      보면 88,863 173,641원)"** 로 나왔다. 물결표 두 개를 Streamlit
      마크다운이 취소선(`<del>`)으로 묶어 사이 글자를 지운 것이다.

      숫자를 담은 문장은 **데이터**지 마크업이 아니다. 데이터를 마크업
      파서에 그냥 넘긴 것이 원인이므로, 개별 문구가 아니라 **넘기는 자리**
      에서 막는다. (`unsafe_allow_html=True` 블록은 인라인 HTML 안이라
      파서가 건드리지 않아 같은 문구도 멀쩡했다 — 그래서 더 안 보였다)

    ■ 다만 굵게 표기는 살린다 (라운드 120)
      이 함수는 데이터를 지키려고 만들었는데, 실제로는 손으로 쓴 산문도
      여기를 지나간다. 그래서 별표가 통째로 이스케이프돼 화면에 별표가
      글자 그대로 나오고 있었다 (라운드 120 에서 4곳 실측).
      호출부마다 빼는 것은 같은 실수를 다시 부른다 — 산문 쓰는 사람은
      마크다운으로 쓴다. 여기서 짝이 맞는 굵기 표기만 되살린다.
      물결표·밑줄·백틱은 그대로 막으므로 라운드 44 의 사고는 재발하지
      않고, 짝이 안 맞거나 별표에 공백이 붙으면 마크다운과 같은 규칙으로
      막힌다.
    """
    s = '' if text is None else str(text)
    for ch in ('~', '*', '_', '`'):
        s = s.replace(ch, '\\' + ch)
    # 이스케이프된 굵기 표기를 되돌린다 (별표에 공백이 붙은 경우는
    # 마크다운도 굵기로 안 보므로 그대로 둔다)
    return _RE_MD_BOLD_ESC.sub(r'**\1**', s)


#: 위에서 이스케이프한 굵기 표기를 되돌리기 위한 짝 패턴
_RE_MD_BOLD_ESC = _re_wa.compile(
    r'\\\*\\\*(?=\S)(.+?)(?<=\S)\\\*\\\*', _re_wa.S)

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


#: 라이트에서 **다크 카드 안**은 건드리지 않는다는 가드 (라운드 117).
#  카드는 양 테마 모두 다크로 고정인데(250행), 라이트 토큰은 어두운 값이라
#  카드 위에 얹으면 글자가 묻힌다 — 계산으로 확인했다:
#      tx1 1.00 · tx2 2.09 · tx3 3.20 · 의미색 3.42~3.46  (전부 AA 미달)
#  다크 값으로 두면 5.24~14.85 다. 그래서 인라인 배경을 가진 요소의
#  자손은 원래 색을 지킨다.
_CARD_GUARD = (':not(div[style*="background"] *)'
               ':not(table[style*="background"] *)')


def _recolor(pairs):
    """인라인 hex 로 박힌 글자색을 라이트 등가로 되돌리는 규칙을 만든다.

    손으로 적으면 아홉 덩어리 70여 줄이 되고, 실제로 그렇게 적혀 있다가
    **아홉 곳 전부 가드를 빠뜨렸다** (라운드 117에서 발견). 생성으로 바꾸면
    가드를 한 곳에서만 관리한다.

    pairs: [(옛 hex, 라이트에서 쓸 토큰 값), ...]
    """
    out = []
    for old, new in pairs:
        sels = []
        for v in (old.upper(), old.lower(), _hex_to_rgb_str(old)):
            for sp in ('', ' '):
                sels.append(f'.stApp [style*="color:{sp}{v}"]{_CARD_GUARD}')
        out.append(',\n'.join(sels) + f' {{\n    color: {new} !important; }}')
    return '\n'.join(out)


# 카드 표면은 양 테마 모두 '단일 다크'로 고정한다.
# 라이트에서 이 카드들을 흰색으로 바꾸면, 내부 글자색이 밝은 색으로 하드코딩돼
# 있어 통째로 사라진다(과거 라이트 모드 실패의 원인). 흰 배경 위 다크 카드는
# 대시보드 관례이기도 하다 — 대신 9종이던 카드색을 하나로 통일한다.
#
# ⚠️ 그 '하나'가 실은 **둘**이었다 (라운드 115). 서버를 띄워 세어 보니
#    화면의 카드 표면이 두 계열로 갈려 있었다:
#        #161D2A  45개  ← 여기 손으로 적은 값 (인라인 HTML 을 CSS 가 통일)
#        #16181F  30개  ← ui_kit 컴포넌트가 쓰는 팔레트 토큰 DARK['card']
#    두 색은 눈으로 거의 같지만 §5 는 카드 한 종류를 요구한다. 그리고 §5 는
#    "색은 ui_kit 팔레트가 유일 출처" 라고도 한다 — 그러면 답은 정해져 있다.
#    **팔레트 쪽으로 모은다.** DARK 는 고정 dict 이므로(테마별 _TOK 이 아니다)
#    위의 '양 테마 단일 다크' 원칙도 그대로 지켜진다.
#
#    아래 _OLD_SURFACES 의 옛 hex 들은 **선택자**라 그대로 둔다 — 인라인
#    마크업에 남아 있는 값을 잡아 여기 상수로 덮어쓰는 것이 이 장치다.
_CARD_BG = _uk.DARK['card']
_CARD_BG_ELEV = _uk.DARK['raised']

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
           라이트 surface(흰색)로 바꾸면 글자가 사라진다.
           선택자의 #161D2A 는 **마크업에 적힌 옛 값**이라 그대로 두고,
           칠하는 값만 카드 상수로 맞춘다 (라운드 115) */
        background: {_CARD_BG} !important;
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

# ── 실시간 띠 (라운드 48) ──────────────────────────────────────────────
# 사용자 요청: *"업데이트 상황 알려주는 창... 뭐 진행중이다, 핫이슈가 뭐다,
# 실시간으로 사이트나 뉴스 같은 거 맨 위에 계속 움직이게."*
#
# 자리는 지금 잡고 내용은 나중에 채운다 — 스캔 상태·매크로·뉴스가 다
# 모이는 시점이 이 아래이기 때문이다. 자리를 안 잡으면 띠가 화면 중간에
# 나타난다.
_TICKER_SLOT = st.empty()


def _render_ticker(extra=None):
    """
    맨 위 띠를 채운다. 실패해도 화면은 떠야 한다.

    띠는 **알림이지 판단이 아니다** — 여기서 점수를 만들거나 값을 고치지
    않는다. 이미 계산된 것을 줄로 바꿀 뿐이다 (CLAUDE.md §4).
    """
    try:
        # ⚠️ 별칭을 `_lt` 로 두지 않는다 — 2475행에서 **경량 스캔 결과**가
        #    이미 그 이름을 쓴다. 라운드 39에서 `_vc`(verdict_core vs 배너
        #    색)로 똑같은 사고를 냈고, 모듈 객체가 style 속성에 찍혀 나갔다.
        import live_ticker as _ltick
        try:
            import sector_cycle as _sc_t
            _macro = _sc_t.macro()
        except Exception:                                    # noqa: BLE001
            _macro = None
        # name_map 을 주면 헤드라인 클릭 → 그 종목 분석으로 전환된다
        _rows = _ltick.build(session=st.session_state, macro=_macro,
                             extra=extra,
                             name_map=globals().get('STOCK_NAME_MAP'))
        _html = _uk.ticker_bar(_rows, theme=_theme)
        if _html:
            _TICKER_SLOT.markdown(_html, unsafe_allow_html=True)
    except Exception:                                        # noqa: BLE001
        # 띠 하나 때문에 앱이 죽지 않는다. 못 그리면 안 그린다.
        pass


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
    # 라운드 44 — 적정가·섹터를 model 축에서 떼어 냈다. 축을 여기 손으로
    # 나열하면 versioning.AXES 가 늘어도 화면이 안 따라온다(실제로 안 따라왔다).
    # 이름만 여기서 주고, **목록은 versioning 이 정한다.**
    _AX_KO_NAMES = {'model': '모델', 'scoring': '산식', 'rulebook': '룰북',
                    'schema': '스키마', 'news': '뉴스',
                    'valuation': '적정가', 'sector': '업황'}
    _AX_KO = {_a: _AX_KO_NAMES.get(_a, _ver.AXIS_KO.get(_a, _a))
              for _a in _ver.AXES}
    # 라운드 39 — 버전이 낮다고 낡은 게 아니다. 버전은 **그 축이 마지막으로
    # 바뀐 시점**을 가리킨다. 룰북·뉴스가 v2026.08.02 인 것은 그 축의 파일이
    # 그 뒤로 안 바뀌었다는 뜻인데, 화면이 설명을 안 해서 낡아 보였다.
    # (사용자 질문: "룰북, 뉴스는 최신버전이 아니야?")
    # ⚠️ 라운드 182 — 툴팁이 **"언제 바뀌었나"** 는 말하는데 **"언제 다시
    #   보나"** 를 안 말했다. 사용자 물음: *"산식 v2026.08.05.1 / 룰북
    #   v2026.08.16.1 — 이거는 업데이트 계획이 어떻게 되나?"*
    #   업황(라운드 181)과 같은 구멍이다 — 계획이 있어도 화면이 말하지
    #   않으면 사용자에게는 없는 것과 같다.
    #
    #   ⚠️ **날짜를 여기 손으로 적지 않는다.** 열린 이슈의 `next_review` 를
    #     읽어 붙인다 — 이슈가 옮겨지면 화면도 따라 옮겨진다.
    #     이슈가 없는 축은 문구도 없다 (없는 계획을 지어내지 않는다 · §3).
    #   ⚠️ 라운드 222 — 'model' 축이 걸어 둔 `model|vb_gap` 이 **닫혔다.**
    #     일일 파이프라인의 감지 규칙(검증−블라인드 ≥ 10%p 면 열고, 아니면
    #     닫는다 · 기존 규칙)이 2026-09-03 실행에서 괴리 5.4%p(65.4 vs 60.0)로
    #     닫았다. §182 가 "이슈가 닫히면 화면 문구도 사라져야 한다 — 그때 이
    #     검사가 알린다"고 적어 둔 그대로 알렸다. 닫힌 이슈를 열린 과제로
    #     말하지 않는다. 모델 축의 진짜 '다음에 보는 시점'은 이슈가 아니라
    #     전방 재평가일이고, 그 날짜는 `forward_eval`(R78 · 한 곳)에서만 읽는다.
    _AX_ISSUE = {'scoring': 'model|score_not_separating'}
    _ax_plan = {}
    try:
        from improvement import issue_ops as _iop182
        from improvement.database import get_connection as _icx182
        _c182 = _icx182()
        try:
            _iop182.ensure_schema(_c182)
            _byk182 = {str(r.get('issue_key')): r
                       for r in _iop182.issue_view(_c182, 40)
                       if str(r.get('status')) == 'open'}
        finally:
            _c182.close()
        for _a182, _k182 in _AX_ISSUE.items():
            _r182 = _byk182.get(_k182)
            if not _r182:
                continue
            _d182 = str(_r182.get('next_review') or _r182.get('eta') or '')[:10]
            if _d182:
                _ax_plan[_a182] = (
                    f" 다음에 다시 보는 시점은 {_d182} 입니다 — "
                    f"열린 과제: {str(_r182.get('title') or '')[:40]}.")
    except Exception:                                          # noqa: BLE001
        _ax_plan = {}          # 못 읽으면 계획 문구를 안 붙인다 (§3)
    # 모델 축 — 전방 재평가일(박제 파일 · R78)을 읽는다. 날짜를 여기 적지 않는다.
    #   못 읽으면 문구가 없다 — 없는 계획을 지어내지 않는다(§3).
    try:
        import forward_eval as _fe182
        _fed182 = _fe182.eval_date()
        if _fed182 and 'model' not in _ax_plan:
            _ax_plan['model'] = (
                f" 다음에 다시 보는 시점은 {_fed182} 입니다 — 전방 재평가"
                f"(R55 국면 라우팅 판정 · R216 반등 확인 재측정) 뒤 모델 규칙을 "
                f"다시 봅니다. 그 전엔 값이 바뀌지 않습니다.")
    except Exception:                                          # noqa: BLE001
        pass

    _chips = ''.join(
        f"<span style='display:inline-flex; align-items:baseline; gap:4px; "
        f"margin-right:8px; white-space:nowrap;' "
        f"title='{_uk._esc_attr(_ko)} 축은 "
        f"{_uk._esc_attr(_VER_NOW.get(_ax, '—'))} 이후 바뀌지 않았습니다. "
        f"버전은 앱 출시일이 아니라 그 축이 마지막으로 바뀐 시점입니다."
        f"{_uk._esc_attr(_ax_plan.get(_ax, ''))}'>"
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
    # ⚠️ 라운드 198 — 여기가 `total_cases` 였다. 라운드 197 이 '이어받은
    #   행'(시세를 더는 못 받아 다시 채점하지 못한 케이스)을 도입하면서
    #   **두 수가 갈렸다**: total_cases 183,792 vs 원장 184,769.
    #   연구 문서와 스크립트는 **원장 행수**를 센다(`ledger_rows()`).
    #   화면이 다른 수를 내밀면 §4 위반이다 — 원장 쪽으로 맞춘다.
    _STATUS_TOP = ('데이터 점검 완료', 'pos',
                   f"되돌려 본 판단 "
                   f"{_cal_top.get('ledger_rows') or _cal_top.get('total_cases', 0):,}건")
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
       일괄 규칙이 로고까지 13px 로 눌러 마크(34px) 옆에서 찌그러졌었다.

       주의 — **버튼 안도 제외한다** (라운드 116). 이 규칙이 `!important` 로
          사이드바의 모든 p·span 을 tx2 로 칠하는데, Streamlit 은 버튼
          라벨을 <p> 로 그린다. 그래서 파란 '최신화' 버튼 위 글자가 흰색이
          아니라 tx2 로 덮여 **대비 1.23** 이 나왔다 — 회색 글자가 파란
          배경에 거의 안 보인다. 버튼은 자기 배경과 자기 글자색을 갖는다. */
    [data-testid="stSidebar"] p:not([style*="font-size"]):not(button *),
    [data-testid="stSidebar"] span:not([style*="font-size"]):not(button *),
    [data-testid="stSidebar"] label:not([style*="font-size"]):not(button *),
    [data-testid="stSidebar"] li:not(button *),
    [data-testid="stSidebar"] small:not(button *),
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

    /* 주요(primary) 버튼 — 브랜드 파랑 채움 위 글자는 **어둡게** (라운드 116)
       실측: 흰 글자가 3.20:1 로 AA 미달이었고, 사이드바 일괄 규칙에 덮여
       실제로는 tx2 가 얹혀 **1.23:1** 이었다(회색 글자가 파란 배경에 거의
       안 보였다). 더 어두운 파랑을 새로 만들지 않고(§5) 글자를 뒤집는다.
       → 6.15:1 */
    .stApp button[data-testid="stBaseButton-primary"],
    .stApp button[kind="primary"] {{
        color: {_TOK['bg1']} !important;
    }}
    .stApp button[data-testid="stBaseButton-primary"] *,
    .stApp button[kind="primary"] * {{
        color: {_TOK['bg1']} !important;
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

        /* 라운드 176 — 펼친 익스팬더 머리가 라이트에서 안 보였다.
           `.streamlit/config.toml` 이 `base = "dark"` 로 잠겨 있어
           Streamlit 이 **자기 위젯 크롬**을 다크로 칠한다. 그런데 그 다크는
           `details[open] > summary` 에만 붙는다 — 접힌 머리는 투명이다.
           그래서 위의 라이트 규칙이 그 안 글자를 `tx1`(어둡게)로 바꾸면
           **펼친 것만** 다크 배경 + 다크 글자가 된다.

           브라우저 실측(라이트 모드 · 글자 마디 1,802개):
             이 규칙 없이  대비 1.04 인 마디 2개 (열린 익스팬더 4개 중)
             이 규칙 있으면 **0개**
           같은 DOM 에서 규칙만 넣고 빼며 잰 값이다.

           주의 — 접힌 머리(65개)는 이미 투명이라 어두운 글자가 맞다.
           `summary` 전체를 예외로 두면 그 65개가 흰 글자가 돼 더 나빠진다.
           `details[open]` 로 좁히는 이유가 그것이다. */
        .stApp [data-testid="stExpander"] details[open] > summary {{
            background: transparent !important;
        }}

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
           다크 색으로 남는다. 라이트 등가로 되돌리되 **다크 카드 안은
           빼야 한다** — 카드는 양 테마 모두 다크인데(250행) 라이트 토큰은
           어두운 값이라 카드 위에 얹으면 글자가 묻힌다.

           라운드 117 전까지 이 아홉 덩어리가 손으로 적혀 있었고 **아홉 곳
           전부 그 가드를 빠뜨렸다.** 계산으로 확인한 라이트 토큰의 다크
           카드 위 대비: tx1 1.00 · tx2 2.09 · tx3 3.20 · 의미색 3.42~3.46
           — 전부 AA 미달이고 tx1 은 사실상 보이지 않는다.
           생성으로 바꿔 가드를 한 곳(_CARD_GUARD)에서만 관리한다. */
{_recolor([('#F3F6FA', _TOK['tx1']), ('#9DAABC', _TOK['tx2']),
           ('#7C8AA0', _TOK['tx3']), ('#4C8DFF', _TOK['brand']),
           ('#35C98B', _TOK['pos']), ('#F2B84B', _TOK['warn']),
           ('#F26161', _TOK['neg']), ('#FF453A', _TOK['up']),
           ('#0A84FF', _TOK['down'])])}

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
        st.caption("이 환경에서는 붙여넣기 상자를 띄우지 못했습니다 — 아래 파일 올리기를 이용하세요.")
        return None
    try:
        return _paste_component(key=key, default=None)
    except Exception as exc:
        st.caption(f"붙여넣기 상자를 띄우지 못했습니다 ({type(exc).__name__}) — 아래 파일 올리기를 이용하세요.")
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
# 라운드 125 — 묶음을 **본문 인접성**으로 다시 짰다.
#
#   종전 묶음은 뜻으로는 그럴듯한데 본문에서 서로 떨어진 것들을 한
#   묶음이라 부르고 있었다. 메뉴 순서를 본문 위치로 바꿔 보면 여섯
#   군데에서 위로 튀었다 — '오늘의 추천'은 본문 2번째인데 1묶음의
#   네 번째였고, '업데이트 내역'은 본문 5번째인데 4묶음에 있었다.
#   사용자가 "비슷한 것끼리 묶어 달라"고 한 것이 이 어긋남이다.
#
#   그래서 **화면에서 실제로 이웃한 것**을 한 묶음으로 부른다.
#   괄호 안 숫자가 본문 등장 순서다 — 묶음 안에서 단조로워야 한다.
_NAV_SUB = [
    # 시장 전체 이야기 — 종목을 고르기 전에 보는 것들 (1 · 3)
    {'title': '1. 오늘의 시장', 'items': [
        {'key': 'premarket', 'label': '오늘의 추천', 'icon': 'chart',
         'href': '#nav-premarket'},
        # 라운드 105 — '한 줄 결론' 이라는 이름이 **두 곳**에 있다.
        #   개장 전(시장 전체) 과 개별 종목. 내비가 뒤엣것만 가리키고
        #   있어서 앞엣것을 찾을 길이 없었다. 둘 다 넣고 이름으로 가른다.
        {'key': 'premarket_line', 'label': '개장 전 결론', 'icon': 'doc',
         'href': '#nav-premarket-line'},
    ]},
    # 내 자산 (3 · 4)
    # ⚠️ 라운드 136 — '관심종목'을 여기 넣는다. 라운드 135 에서 사이드바
    #   접힌 칸에만 뒀더니 사용자가 "관심목록 리스트 어디서 봐?" 라고
    #   물었다. 라운드 105 와 같은 모양이다 — 화면에는 있는데 갈 길이 없다.
    #   본문 순서(보유종목 → 관심종목)와 같은 차례로 둔다 (§170 ⓔ).
    {'title': '2. 내 자산', 'items': [
        {'key': 'holdings', 'label': '내 보유종목', 'icon': 'wallet',
         'href': '#nav-holdings'},
        {'key': 'watchlist', 'label': '관심종목', 'icon': 'target',
         'href': '#nav-watchlist'},
    ]},
    # 이 종목 이야기 — 판정부터 근거까지 한 줄기 (6 · 7 · 8 · 10 · 11)
    {'title': '3. 이 종목', 'items': [
        {'key': 'verdict', 'label': '이 종목 한 줄 결론', 'icon': 'doc',
         'href': '#nav-verdict'},
        {'key': 'chart', 'label': '차트', 'icon': 'chart',
         'href': '#nav-chart'},
        {'key': 'gaeum', 'label': '가늠 AI', 'icon': 'compass',
         'href': '#nav-gaeum'},
        {'key': 'basis', 'label': '판정 근거', 'icon': 'doc',
         'href': '#nav-basis'},
        {'key': 'context', 'label': '시장·뉴스', 'icon': 'news',
         'href': '#nav-context'},
    ]},
    # 검증과 이력 (10 · 11 · 12 · 13)
    {'title': '4. 검증과 이력', 'items': [
        {'key': 'perf', 'label': '모델 성적', 'icon': 'chart',
         'href': '#nav-perf'},
        # 본문에는 있는데 메뉴에 없어 **찾을 길이 없던** 절들 (라운드 124)
        {'key': 'cases', 'label': '사례 모음', 'icon': 'doc',
         'href': '#nav-cases'},
        {'key': 'scores', 'label': '점수 요인', 'icon': 'chart',
         'href': '#nav-scores'},
        # 라운드 127 — 본문 블록을 여기로 내렸으므로 메뉴도 따라온다.
        #   종전에는 '오늘의 시장'에 있었다(본문 다섯 번째였을 때).
        {'key': 'updates', 'label': '업데이트 내역', 'icon': 'bell',
         'href': '#nav-updates'},
    ]},
    # 도움 — 본문 맨 끝 (16)
    {'title': '5. 도움', 'items': [
        {'key': 'support', 'label': '고객센터', 'icon': 'life',
         'href': '#nav-support'},
    ]},
]
#: 첫 화면으로 되돌릴 때 비우는 상태 — **한 곳에만 적는다.**
#  로고 링크와 '처음으로' 버튼이 같은 목록을 써야 한다. 목록이 둘이면
#  한쪽만 고치는 일이 생긴다 (§4). 보유종목(positions)과 저장본은
#  건드리지 않는다 — 사용자의 자료다.
_HOME_RESET_KEYS = (
    'search_text_input', 'pending_search', 'selected_ticker',
    'show_portfolio', 'show_screener', 'pending_scan',
    'scan_results', 'scan_key', 'scan_universe_total',
    'attention_result', 'attention_unmapped',
    'paste_preview', 'last_ocr_text', 'clip_image',
    'name_candidates', 'horizon_pick', 'freeform_paste')


def _go_home():
    for _k in _HOME_RESET_KEYS:
        st.session_state.pop(_k, None)
    st.rerun()


# 로고 클릭 — Streamlit 위젯은 HTML 앵커에서 못 누르므로 쿼리 파라미터로
# 돌아온다. 파라미터는 처리 후 지운다 (새로고침해도 다시 안 돌게).
if st.query_params.get('home'):
    try:
        del st.query_params['home']
    except Exception:                                          # noqa: BLE001
        st.query_params.clear()
    _go_home()

# 접기 버튼은 스크롤해도 자리에 있어야 한다 (라운드 122).
#   `stSidebarCollapseButton` 은 `stSidebarHeader` 안에 있고, 그 바깥의
#   `stSidebarContent` 가 스크롤 컨테이너다. 헤더가 static 이라 사이드바를
#   내리면 버튼이 위로 밀려 사라졌다 — 메뉴가 길어질수록 더 그렇다.
#   헤더를 스크롤 컨테이너 기준 sticky 로 붙인다. 배경을 함께 주지 않으면
#   아래 내용이 버튼 뒤로 비쳐 보인다.
st.sidebar.markdown(
    f"""<style>
  section[data-testid="stSidebar"] div[data-testid="stSidebarHeader"] {{
      position: sticky; top: 0; z-index: 70;
      background: {_TOK['bg2']};
  }}
  /* 로고 줄도 같이 붙여 두면 '지금 어느 앱인지'가 항상 보인다 */
  section[data-testid="stSidebar"] a.gn-home {{ text-decoration: none; }}
</style>""",
    unsafe_allow_html=True)

st.sidebar.markdown(
    f"<div style='padding:4px 0 14px 0;'>"
    f"{_uk.logo(_theme, size=30, href='?home=1', title='첫 화면으로 (검색어·스캔 결과 초기화)')}"
    f"</div>",
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
    _go_home()

st.sidebar.caption(f"업데이트 {APP_UPDATED} · 제목이나 '처음으로'를 누르면 "
                   f"첫 화면으로 돌아갑니다")

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
    # 항상 펼쳐 둔다 (라운드 38 · 사용자 요청) — 이 영역에서 하는 일은
    # 접는 게 아니라 **다시 불러오는 것**이다.
    {'key': 'find', 'no': '3', 'title': '종목 찾기', 'always': True,
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

# 못 받았으면 '미수신'과 이유를 쓴다 — 지어낸 이름을 사실처럼 두지 않는다
# (§3 · 라운드 119. 엔진이 실패 시 "삼성전자" 를 돌려주고 있었다)
_uk.sidebar_section(
    "종목",
    (f"오늘 시총 1위는 {default_stock_no1}" if default_stock_no1
     else "시총 1위 미수신 — 네이버 시세 응답 없음"),
    _theme, top=6, at=_SB_PICK)

if 'search_text_input' not in st.session_state:
    st.session_state['search_text_input'] = ''

#: `STOCK_NAME_MAP` 은 같은 종목을 이름·'이름 (코드)'·코드 세 키로 담는다.
#: 검색 목록에서 별칭 키만 걸러 내는 식 — **이름에 든 괄호와 구분한다.**
_RE_ALIAS_KEY = _re_wa.compile(r'\s\(' + stock_code.CODE + r'\)$')

# 뉴스 띠에서 넘어온 종목 (라운드 56) — ?pick=이름 (코드) 를 관심종목
# 클릭과 같은 pending_search 경로에 태운다. 경로가 둘이면 한쪽만 고치는
# 일이 생긴다 (§4). 받은 즉시 파라미터를 지워 새로고침 반복을 막는다.
try:
    _qp_pick = st.query_params.get('pick')
    if _qp_pick and str(_qp_pick).strip():
        st.session_state['pending_search'] = str(_qp_pick).strip()
        del st.query_params['pick']
except Exception:                                              # noqa: BLE001
    pass                              # 파라미터 하나 때문에 화면이 죽지 않는다

if 'pending_search' in st.session_state and st.session_state['pending_search']:
    st.session_state['search_text_input'] = st.session_state['pending_search']
    st.session_state['pending_search'] = ""

search_text_input = _SB_PICK.text_input(
    '종목명 일부 또는 티커 입력',
    key='search_text_input',
    placeholder='예: 하이닉스, 타이어, 건설, 페이, 포스코, 073240...',
    help='단어 일부(예: 하이닉스, 타이어, 페이)를 입력하시면 연동 후보 리스트가 하단에 즉시 생성되어 선택할 수 있습니다.'
)

# ── 최근 본 종목 (라운드 164) ────────────────────────────────────────────
# 사용자 요청: *"검색할 때 전에 검색한 리스트도 쭉 나오게 해서 고르게
# 하는 거 어때?"*
#
# 이 앱은 종목 하나를 고르면 전체 파이프라인이 돌아 몇 분씩 걸린다.
# 그래서 **다시 보러 가는 일**이 잦은데 그때마다 이름을 처음부터 쳐야
# 했다. 관심종목(담아 둔 것)과는 다른 목록이다 — 이건 지나온 것이다.
#
# ⚠️ 무엇을 봤는지도 개인 정보다. 원격 접속에서는 파일에 쓰지 않고
#   이 브라우저 세션에만 둔다 (보유종목과 같은 규칙 · §9).
if 'recent_stocks' not in st.session_state:
    try:
        st.session_state['recent_stocks'] = (
            [] if is_remote_exposed() else portfolio.load_search_history())
    except Exception:                                          # noqa: BLE001
        st.session_state['recent_stocks'] = []

_recent_items = st.session_state.get('recent_stocks') or []
if _recent_items:
    _RECENT_PH = "--- 최근 본 종목에서 고르기 ---"
    _recent_labels = [f"{r['name']} ({r['code']})" for r in _recent_items]
    # ⚠️ 고르고 나면 이 칸을 **안내문구로 되돌린다.** 되돌리지 않으면
    #   골라 둔 값이 그대로 남아, 나중에 **같은 종목을 다시 고를 때
    #   '변화 없음'이 되어 아무 일도 안 난다** — 이번 라운드에 고친
    #   '죽은 버튼'과 똑같은 모양이다.
    #   Streamlit 은 위젯이 만들어진 뒤 그 키를 못 고치므로, 이 저장소가
    #   이미 쓰는 방식(`paste_nonce`)대로 **키 자체를 바꿔** 되돌린다.
    _recent_nonce = st.session_state.get('recent_nonce', 0)
    # ⚠️ 개수를 적지 않는다. 이 칸은 종목이 **확정되기 전에** 그려지고
    #   기록은 확정된 뒤에 남으므로, 방금 본 종목이 아직 안 들어 있다.
    #   "2개"라고 적으면 목록에 3개가 보이는 판이 생긴다 — 화면이 스스로
    #   모순되는 그 모양(§4)이다. 목록 자체가 이미 개수를 보여 준다.
    _recent_pick = _SB_PICK.selectbox(
        "최근 본 종목", [_RECENT_PH] + _recent_labels,
        index=0, key=f'recent_pick_{_recent_nonce}',
        help='이 브라우저에서 열어 본 종목입니다. 고르면 검색창에 들어가 '
             '바로 다시 엽니다. 관심종목과는 다른 목록입니다 — '
             '관심종목은 담아 둔 것이고 이것은 지나온 것입니다.')
    if _recent_pick != _RECENT_PH:
        st.session_state['recent_nonce'] = _recent_nonce + 1
        st.session_state['pending_search'] = _recent_pick
        st.rerun()
    _rc1, _rc2 = _SB_PICK.columns([1, 1])
    if _rc2.button("최근 목록 비우기", width='stretch', key='recent_clear'):
        st.session_state['recent_stocks'] = []
        try:
            if not is_remote_exposed():
                portfolio.delete_search_history()
        except Exception:                                      # noqa: BLE001
            pass
        st.rerun()

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
        # ⚠️ 라운드 164 — 여기가 `if '(' in name` 이었다. 뜻은 *"'이름
        #   (코드)' 별칭 키는 건너뛴다"* 였는데, **이름 자체에 괄호가 든
        #   종목까지 통째로 걸렀다.** 사용자가 못 찾은
        #   'ACE 미국빅테크7+데일리타겟커버드콜(합성)' 이 그 모양이다.
        #   별칭만 정확히 골라 낸다 — 끝이 ' (코드)' 인 키.
        if _RE_ALIAS_KEY.search(name):
            continue
        if kw in name.lower() or kw in ticker.lower():
            code_num = ticker.split('.')[0]
            label = f"{name} ({code_num})"
            if label not in matched_stocks:
                matched_stocks.append(label)

    # ── ETF 는 따로 찾는다 (라운드 164) ─────────────────────────────
    # 실측: 네이버 검색이 '미국빅테크7' 에 **0건**을 돌려줬는데 ETF 목록
    # 에는 8종목이 있었다. 이름으로 찾는 길을 네이버 한 곳에만 맡기지
    # 않는다. 목록을 못 받으면 그냥 건너뛴다 — 지어내지 않는다.
    try:
        for _ec, _en in etf_registry.search(search_text_input.strip()):
            _elabel = f"{_en} ({_ec})"
            if _elabel not in matched_stocks:
                matched_stocks.append(_elabel)
    except Exception:                                          # noqa: BLE001
        pass                          # 검색 하나 때문에 화면이 죽지 않는다

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

# ── 최근 본 종목에 남긴다 (라운드 164) ──────────────────────────────────
# 종목이 **확정된 뒤**에 남긴다. 검색어 그대로 남기면 오타·중간 입력이
# 목록을 채운다. 맨 앞이 이미 이 종목이면 파일을 쓰지 않는다 — rerun
# 마다 디스크를 건드리지 않기 위해서다.
_hist_code = portfolio.normalize_code(target_ticker)
if _hist_code:
    _hist_new, _hist_changed = portfolio.push_search_history(
        st.session_state.get('recent_stocks') or [], _hist_code, resolved_name)
    if _hist_changed:
        st.session_state['recent_stocks'] = _hist_new
        try:
            # 검사가 돌 때는 파일에 쓰지 않는다 — 사용자 목록에 테스트
            # 종목이 쌓이던 자리다 (라운드 165 · §9)
            if not is_remote_exposed() and not NO_LOCAL_WRITE:
                portfolio.save_search_history(_hist_new)
        except Exception:                                      # noqa: BLE001
            pass                      # 기록 하나 때문에 화면이 죽지 않는다

# 🚨 [무결성 보장] 네이버 증권 실시간 웹 파서 강제 동적 수신
engine_init.fetch_and_update_naver_realtime(target_ticker)

asset_meta = engine_init.get_asset_currency_and_unit(target_ticker)
unit_currency = asset_meta["currency"]
unit_str = asset_meta["unit_str"]

realtime_price, check_status, matrix_data = engine_init.get_realtime_stock_price_triple_check(target_ticker)

# 상단 툴바 오른쪽 끝에 지금 보는 종목 — 스크롤 중에도 잊지 않게 (sticky)
_render_toolbar(f"보는 중 <b>{_uk._esc(resolved_name)}</b> "
                f"{_uk._esc(target_ticker)}")

# 맨 위 실시간 띠 — 지금 보는 종목까지 확정된 뒤에 채운다
_render_ticker([dict(kind='live', text=f'분석 중 {resolved_name} '
                                       f'{target_ticker}')])

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
#  ⚠️ 라운드 165 — 검사가 돌 때도 끈다. 회귀의 AppTest 렌더가 사용자
#     자료를 바꾸면 안 된다 (§9). 읽기는 그대로다.
#
#  ⚠️ 라운드 200 — **그 주석이 거짓이었다.** 이름이 `ALLOW_LOCAL_STORE`
#     하나뿐이라 읽기와 쓰기가 안 갈렸고, 아래에서 그 하나로 **읽기를
#     막고 있었다.** 그래서 `GAEUM_NO_LOCAL_WRITE=1` 로 도는 회귀의
#     AppTest 렌더는 **보유종목·관심종목이 늘 빈 화면**을 봤다 —
#     보유자 경로가 한 번도 검사된 적이 없다는 뜻이다.
#     (라운드 199 의 '보유 연동' 수정을 값으로 확인하려다 드러났다.)
#     → 읽기와 쓰기를 **다른 이름**으로 가른다. 원격 노출은 종전대로
#       둘 다 막는다(§9 — 공용 파일이 방문자끼리 새면 안 된다).
ALLOW_LOCAL_READ = not is_remote_exposed()
ALLOW_LOCAL_STORE = ALLOW_LOCAL_READ and not NO_LOCAL_WRITE

if 'positions' not in st.session_state:
    if ALLOW_LOCAL_READ:
        _loaded, _saved_at = portfolio.load_positions()
        st.session_state['positions'] = _loaded
        st.session_state['positions_saved_at'] = _saved_at
    else:
        st.session_state['positions'] = []          # 방문자별로 비어서 시작
        st.session_state['positions_saved_at'] = None

if 'watchlist' not in st.session_state:
    if ALLOW_LOCAL_READ:                 # 라운드 200 — 읽기는 막지 않는다
        _wl, _ = portfolio.load_watchlist()
        st.session_state['watchlist'] = _wl
    else:
        st.session_state['watchlist'] = []


# ── 관심종목 담기·보기·지우기 (라운드 135) ───────────────────────────
# 종전에는 **'이 목록을 통째로 저장'** 하나뿐이었다. 한 종목을 담을 수도,
# 하나만 뺄 수도 없었고, 그 버튼은 기존 목록을 **덮어썼다.**
# 담는 곳(스캔 결과)과 보는 곳이 달라서 지금 담긴 게 뭔지도 안 보였다.
#
# 저장은 `portfolio.save_watchlist()` **한 곳**으로만 한다 (§4).
# 원격 노출 상태면 파일에 쓰지 않고 세션에만 둔다 — 앱 인스턴스가 하나라
# `.portfolio/` 가 방문자 전원의 공용 파일이 된다 (§9).

def _go_stock(code, name=''):
    """
    그 종목을 보러 간다 — **이 함수 하나만** 쓴다 (라운드 164).

    ⚠️ 여기가 실제로 고장나 있었다. 관심종목의 이름 버튼 두 곳이
       `st.session_state['ticker_input']` 에 코드를 넣고 rerun 했는데
       **그 키를 읽는 곳이 저장소 어디에도 없었다.** 사이드바 캡션은
       *"이름을 누르면 그 종목을 봅니다"* 라고 적고 있었지만 눌러도
       화면이 그대로였다.

       검색어를 넘기는 길은 원래 하나다 — `pending_search`. 뉴스 띠
       (`?pick=`)·최근 본 종목이 그 길을 쓴다. 경로가 둘이면 한쪽만
       고치는 일이 생긴다 (§4). 이제 셋 다 이 함수를 부른다.
    """
    c = portfolio.normalize_code(code)
    if not c:
        return False
    st.session_state['pending_search'] = f"{name} ({c})" if name else c
    return True


def _wl_items():
    return list(st.session_state.get('watchlist') or [])


def _wl_has(code):
    c = portfolio.normalize_code(code)
    return any(portfolio.normalize_code(w.get('code')) == c
               for w in _wl_items())


def _wl_write(items, msg=''):
    """세션과 파일을 **같이** 바꾼다. 한쪽만 바뀌면 새로고침에 되살아난다."""
    st.session_state['watchlist'] = items
    if ALLOW_LOCAL_STORE:
        try:
            portfolio.save_watchlist(items)
        except Exception as _ex:                               # noqa: BLE001
            st.sidebar.warning(f"로컬 저장 실패: {_ex}")
            return
    if msg:
        st.session_state['wl_flash'] = msg


def _wl_add(code, name):
    """이미 있으면 아무것도 안 한다 — 같은 종목이 두 줄로 늘지 않는다."""
    c = portfolio.normalize_code(code)
    if not c or _wl_has(c):
        return False
    _wl_write(_wl_items() + [{'code': c, 'name': str(name or c)}],
              f"{name or c} 담았습니다")
    return True


def _wl_remove(code):
    c = portfolio.normalize_code(code)
    keep = [w for w in _wl_items()
            if portfolio.normalize_code(w.get('code')) != c]
    _wl_write(keep, '한 종목 뺐습니다')


# ⚠️ 라운드 142 — 사용자 요청: "검색하는 종목에 관심추가 버튼도 넣어줘."
#   버튼은 라운드 135 부터 여기 있었지만 **접힌 칸 안**이라, 검색 직후에는
#   보이지 않았다. 라운드 136 에서 "관심목록 어디서 봐?" 라고 물은 것과
#   같은 모양이다 — 있는데 안 보이면 없는 것이다.
#   → 지금 보는 종목이 **아직 안 담겼으면 펼쳐 둔다.** 담고 나면 접힌다.
_wl_cur_open = bool(portfolio.normalize_code(target_ticker)) and not _wl_has(
    target_ticker)
with st.sidebar.expander(
        f"관심종목 {len(_wl_items())}개", expanded=_wl_cur_open):
    _flash = st.session_state.pop('wl_flash', '')
    if _flash:
        st.success(_flash)

    _cur_code = portfolio.normalize_code(target_ticker)
    if not _cur_code:
        # 지어내지 않는다 — 코드를 못 읽었으면 그렇게 적는다 (§3)
        st.caption(f"{resolved_name} 은(는) 6자리 종목코드가 아니라 "
                   f"담을 수 없습니다.")
    elif _wl_has(_cur_code):
        st.caption(f"{resolved_name} 은(는) 이미 담겨 있습니다.")
    else:
        if st.button(f"지금 이 종목 담기 · {resolved_name}",
                     width='stretch', key='wl_add_cur'):
            _wl_add(_cur_code, resolved_name)
            st.rerun()

    _wl_now = _wl_items()
    if not _wl_now:
        st.caption("아직 담은 종목이 없습니다. 위 버튼이나 스캔 결과에서 "
                   "담을 수 있습니다.")
    else:
        st.caption("이름을 누르면 그 종목을 봅니다 · '빼기'로 하나씩 "
                   "지웁니다.")
        for _w in _wl_now:
            _c1, _c2 = st.columns([3, 1])
            with _c1:
                if st.button(f"{_w.get('name')} · {_w.get('code')}",
                             width='stretch',
                             key=f"wl_go_{_w.get('code')}"):
                    _go_stock(_w.get('code'), _w.get('name'))
                    st.rerun()
            with _c2:
                if st.button("빼기", width='stretch',
                             key=f"wl_del_{_w.get('code')}"):
                    _wl_remove(_w.get('code'))
                    st.rerun()
        if st.button("전체 비우기", width='stretch', key='wl_clear'):
            _wl_write([], '관심종목을 모두 비웠습니다')
            st.rerun()
        if not ALLOW_LOCAL_STORE:
            st.caption("원격 접속이라 이 목록은 **이 브라우저 세션에만** "
                       "남습니다 — 파일로 저장하지 않습니다.")


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

# ══════════════════════════════════════════════════════════════════════
# 보유 여부는 **아코디언 밖에서** 정한다 (라운드 199)
#
#   사용자 지적: *"가지고 있는데 '이 종목을 갖고 계신가요'도 연동되게
#   해줘야지."*  맞다. 라운드 166 이 관심종목의 매입가를 끌어오게 만들어
#   두었는데, 그 조회가 **사이드바 아코디언 안**에 있었다:
#
#       if _uk.acc_row(_SB_STEPS[1], ...):      # '내 보유종목' — 기본 접힘
#           _reg = ...positions 조회...
#           user_entry_price = st.sidebar.number_input(..., value=_wl_paid)
#
#   §5 가 *"사이드바는 아코디언, '종목 찾기'만 항상 펼침"* 이라 그 칸은
#   **기본이 접힘**이다. 접혀 있으면 저 블록이 통째로 안 돌고
#   `user_entry_price` 가 폴백 **0.0** 으로 떨어진다(2577). 그러면
#   본문의 라디오가 `1 if user_entry_price > 0 else 0` 이라 **'아직 없음'**
#   을 고른다 — 사용자가 매입가를 적어 둔 종목인데도.
#
#   ⚠️ 화면 전체가 쓰는 값을 **접히는 위젯이 만들고 있었다.** 위젯은
#     값을 *고치는* 자리이지 *만드는* 자리가 아니다 (§4 의 사촌).
#     그래서 조회를 여기로 올린다 — 아코디언은 열렸을 때 그 값을 보여
#     주고 덮어쓸 뿐이다.
def _held_of(tk):
    """이 종목의 보유 정보 — (평단, 수량, 출처). 없으면 (0, 0, None).

    순서를 못 박는다: **보유종목이 먼저**다(정식 등록). 관심종목의
    매입가는 개인 메모라 그 다음이다 (라운드 166 이 정한 순서 그대로).
    """
    for _p in (st.session_state.get('positions') or []):
        if getattr(_p, 'ticker', None) == tk:
            try:
                return (int(_p.average_buy_price), int(_p.quantity), '보유종목')
            except (TypeError, ValueError):
                return (0, 0, None)
    _c = portfolio.normalize_code(tk)
    for _w in _wl_items():
        if portfolio.normalize_code(_w.get('code')) != _c:
            continue
        try:
            _pd, _qt = int(float(_w.get('paid') or 0)), int(float(_w.get('qty') or 0))
        except (TypeError, ValueError):
            _pd = _qt = 0
        return (_pd, _qt, '관심종목' if _pd > 0 else None)
    return (0, 0, None)


_auto_avg, _auto_qty, _auto_src = _held_of(target_ticker)

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
        _col = _TOK['up'] if (_pnl or 0) >= 0 else _TOK['down']
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
                _rc = _TOK['up'] if (_ret or 0) >= 0 else _TOK['down']
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

    # ── 관심종목에 적어 둔 매입가·수량도 끌어온다 (라운드 166) ─────────
    # 사용자 요청: *"이 종목을 갖고 계신가요를 관심종목이랑 연동시켜야지."*
    # 관심종목 표에 매입가·수량을 적어 두고도 이 칸은 0 이라, 같은 사실을
    # 두 번 적어야 했다.
    # ⚠️ 순서를 못 박는다 — **보유종목이 먼저**다. 그쪽이 정식 등록이고
    #   관심종목의 매입가는 개인 메모다. 어디서 온 값인지 화면이 밝힌다
    #   (§3 · §4 — 값의 출처가 둘이면 어느 쪽인지 보여야 한다).
    _wl_paid = _wl_qty = 0
    if _reg is None:
        _cwl166 = portfolio.normalize_code(target_ticker)
        for _w166 in _wl_items():
            if portfolio.normalize_code(_w166.get('code')) != _cwl166:
                continue
            try:
                _wl_paid = int(float(_w166.get('paid') or 0))
                _wl_qty = int(float(_w166.get('qty') or 0))
            except (TypeError, ValueError):
                _wl_paid = _wl_qty = 0
            break

    if _reg is not None:
        st.sidebar.success(
            f"**{resolved_name}** — 보유종목에서 자동으로 채웠습니다 "
            f"({_reg.quantity:,.0f}주 · 평단 {_reg.average_buy_price:,.0f}원). "
            f"위 목록에서 다른 종목을 누르면 그 종목으로 바뀝니다.")
    elif _wl_paid > 0:
        st.sidebar.info(
            f"**{resolved_name}** — **관심종목**에 적어 두신 값으로 "
            f"채웠습니다 ({_wl_qty:,}주 · 평단 {_wl_paid:,}원). "
            f"포트폴리오 판단에도 넣으려면 '내 보유종목'에 등록하세요 — "
            f"관심종목의 값은 개인 메모입니다.")
    else:
        st.sidebar.caption(f"지금 보고 있는 **{resolved_name}** 한 종목만 임시로 확인합니다. "
                           f"여러 종목을 계속 관리하려면 위 '내 보유종목'에 등록하세요.")
    # ⚠️ 키를 **종목별로** 가른다 (라운드 51 실측 결함)
    #    키가 없으면 스트림릿이 라벨로 키를 만든다. 그러면 종목을 바꿔도
    #    같은 위젯이라 값이 따라온다 — 실제로 금호건설 평단 10,246원이
    #    LG생활건강(약 330,000원) 차트에 '내 평균 매수가'로 그려졌다.
    #    평단은 보유 판단의 유일한 입력이라, 종목이 섞이면 수익률·물타기
    #    판정이 통째로 남의 것이 된다 (CLAUDE.md §9).
    _pk = str(target_ticker or '').replace('.', '_')
    user_entry_price = st.sidebar.number_input(
        "평균 매수가 (원)", min_value=0,
        value=int(_reg.average_buy_price) if _reg else _wl_paid, step=1000,
        key=f"sb_avg_{_pk}",
        help="보유 중인 주당 평균 매수가 (0원 = 미보유) · 종목마다 따로 "
             "기억합니다 · 보유종목 → 관심종목 순으로 채웁니다")
    user_quantity = st.sidebar.number_input(
        "보유 수량 (주)", min_value=0,
        value=int(_reg.quantity) if _reg else _wl_qty, step=10,
        key=f"sb_qty_{_pk}",
        help="보유 중인 총 주식 수량 (0주 = 미보유)")
    if user_entry_price > 0 and user_quantity > 0 and _reg is None:
        if st.sidebar.button("보유종목에 등록", width='stretch'):
            st.session_state['positions'] = (st.session_state.get('positions') or []) + [
                portfolio.PortfolioPosition(
                    ticker=target_ticker, stock_name=resolved_name,
                    market=_market_of(target_ticker),
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

    # 제목은 아코디언 줄(항상 펼침)이 이미 그린다 — 여기서 또 그리면
    # '종목 찾기'가 두 번 나온다 (라운드 38 실행 확인에서 잡음).
    # '코스피·코스닥 전체' 라고 쓰고 있었지만 실제 출발점은 네이버 순위
    # 페이지 2종(거래대금 상위·상승률 상위)이다. 전 종목 목록이 아니다.
    st.sidebar.caption("코스피·코스닥의 **거래대금·상승률 순위 상위**에서 관심종목을 "
                       "먼저 추리고, 그중 **퀀트 최종 행동조건**을 통과한 종목만 "
                       "추천합니다. 전 종목을 정밀분석하지는 않습니다 — "
                       "거래가 한산한 종목은 순위에 오르지 않아 후보에서 빠집니다. "
                       "관심도와 매수 판단은 별개입니다.")

    # ── 종목 찾기는 **항상 열려 있다** (라운드 38) ──────────────────────
    # 종전에는 기본이 접힘이었고, 버튼이 '스캔 / 닫기' 라 한 번 더 누르면
    # 결과가 사라졌다. 사용자가 이 영역에서 하는 일은 접는 게 아니라
    # **다시 불러오는 것**이므로, 기본을 펼침으로 두고 버튼을 '최신화'로 바꾼다.
    if 'show_screener' not in st.session_state:
        st.session_state['show_screener'] = True
        st.session_state['pending_scan'] = True     # 첫 진입에 한 번 자동 스캔

    # ① 검색창·② 빠른 선택은 위쪽 '분석할 종목' 절에 이미 있다.
    # ③ 전체 시장 스캔 조건 — 모바일에서 화면을 덜 먹도록 접어 둔다.
    with st.sidebar.expander("상세 설정 · 스캔 조건", expanded=False):
        _strat_labels = [lbl for _k, lbl in market_attention.STRATEGIES]
        _strat_by_label = {lbl: k for k, lbl in market_attention.STRATEGIES}
        _sel_strat_label = st.selectbox(
            "후보 발굴 방식", _strat_labels, index=0,
            help="시총 상위는 대형주가 반복되므로 기본값은 '종합 이슈'입니다.")
        attention_strategy = _strat_by_label[_sel_strat_label]
        if attention_strategy in market_attention.STRATEGY_UNAVAILABLE:
            st.warning(market_attention.STRATEGY_UNAVAILABLE[attention_strategy])

        scan_depth = st.selectbox(
            f"정밀분석 후보 수 ({_sel_strat_label} 순)", [5, 10, 15, 20, 30],
            index=0,
            help="관심점수 상위 N개에만 종목별 정밀 파이프라인을 돌립니다. "
                 "종목당 일봉·시세 조회가 필요해 N이 클수록 오래 걸립니다. "
                 "기본 5개는 빠르게 훑어보기용이며, 넓게 보려면 15~30개로 올리세요.")

        st.caption("**관심 데이터 연동 현황** — 수집하지 못한 항목은 값을 "
                   "만들어내지 않고 가중치를 0으로 둔 뒤 나머지에 재정규화합니다.")
        for _d in market_attention.data_status():
            _mark = {'full': '연동', 'partial': '부분',
                     'none': '미연동'}[_d['availability']]
            st.markdown(
                f"**{_d['label']}** {_mark}  \n"
                f"명세 {_d['spec_weight_pct']:.0f}% → 적용 "
                f"**{_d['effective_weight_pct']:.1f}%**  \n"
                f"<span style='color:#9DAABC;font-size:12px;'>{_d['detail']}</span>",
                unsafe_allow_html=True)

    # ④ 최신화 버튼 — 실행 중에는 비활성화해 중복 클릭을 막는다
    _scan_busy = bool(st.session_state.get('pending_scan'))
    if st.sidebar.button("최신화", width='stretch', type='primary',
                         disabled=_scan_busy,
                         help="현재가·거래량·거래대금·시장 국면·뉴스·관심점수·"
                              "행동점수·추천 후보를 다시 불러옵니다. "
                              "개장 전 확정 리포트는 전일 확정 데이터 기준이라 "
                              "장중에 바뀌지 않습니다."):
        st.session_state['show_screener'] = True
        st.session_state['pending_scan'] = True
        st.rerun()

    # ⑤ 마지막 갱신 시각 · ⑥ 현재 분석 대상 수 · ⑦ 진행 상태
    if _scan_busy:
        st.sidebar.info("**시장 데이터 최신화 중**  \n"
                        "가격 확인 → 거래량 점검 → 뉴스 갱신 → 후보 재정렬")
    else:
        _last = st.session_state.get('scan_done_at')
        _n_att = len((st.session_state.get('attention_result') or {})
                     .get('rows') or [])
        _n_deep = len(st.session_state.get('scan_results') or [])
        if _last:
            st.sidebar.caption(
                f"최신화 완료 · **{_last}**  \n"
                f"관심종목 {_n_att}개 · 정밀분석 {_n_deep}개  \n"
                f"개장 전 추천은 전일 확정 데이터 기준으로 유지됩니다.")
        else:
            st.sidebar.caption("아직 최신화하지 않았습니다 — "
                               "'최신화'를 누르면 시장 데이터를 불러옵니다.")


if _uk.acc_row(_SB_STEPS[3], _sb_open, _sb_busy):

    _uk.sidebar_section("분석 기준", theme=_theme)

    # [명세 §3] 확정 분석 기준일 — 장중·장 시작 전·휴장일이면 직전 거래일로 되돌린다
    _mkt = bitemporal_engine.get_market_status()
    _resolved_date = bitemporal_engine.resolve_analysis_date(market_status=_mkt)
    st.sidebar.caption(
        f"시장 상태: **{_mkt['state']}** 확정 분석 기준일 **{_resolved_date}**"
        + ("" if _mkt['holiday_data_available'] else " 해당 연도 공휴일 미등록 (주말만 판정)")
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
#: 위젯이 `_keep()` 으로 저장하는 이름 ↔ 본문이 쓰는 전역 이름 (라운드 189).
#: 둘이 달라서 폴백이 죽어 있었다. 새 항목을 넣을 때 여기도 같이 적는다.
_KEEP_ALIAS = {'t_ref_date': 't_ref', 'rho_cutoff': 'rho'}

_g = globals()
if '_mkt' not in _g:
    _mkt = bitemporal_engine.get_market_status()
if '_resolved_date' not in _g:
    _resolved_date = bitemporal_engine.resolve_analysis_date(market_status=_mkt)
for _nm, _dv in (
        ('search_text_input', ''), ('matched_stocks', []),
        ('selected_from_matches', None), ('selected_quick_item', None),
        # 라운드 199 — 접혀 있어도 **보유 사실은 살아 있어야** 한다.
        #   종전 기본값이 0.0 이라, '내 보유종목' 아코디언을 안 펼치면
        #   보유 종목인데도 본문 라디오가 '아직 없음' 을 골랐다.
        ('user_entry_price', float(_auto_avg)), ('user_quantity', _auto_qty),
        ('attention_strategy', 'composite'), ('scan_depth', 5),
        ('t_ref_date', _resolved_date), ('rho_cutoff', 0.80)):
    # ⚠️ 라운드 189 — 이 폴백이 **키 이름 불일치로 통째로 죽어 있었다.**
    #   `_keep()` 은 't_ref' · 'rho' 로 저장하는데(2548 · 2552) 여기서는
    #   't_ref_date' · 'rho_cutoff' 로 찾아 늘 못 찾았다. 그래서 4단계를
    #   접는 순간 사용자가 고른 기준일·rho 가 조용히 기본값으로 되돌아갔다
    #   — 1859-1861 주석이 약속한 "접었다 펼쳐도 유지된다"가 거짓이었다.
    #   저장하는 이름과 찾는 이름을 잇는다. 나머지 여덟은 `_KEEP` 에 한
    #   번도 쓰이지 않으므로 기본값으로 떨어지는 것이 정상이다.
    if _nm not in _g:
        _g[_nm] = _KEEP.get(_KEEP_ALIAS.get(_nm, _nm), _dv)
t_ref_str = t_ref_date.strftime("%Y-%m-%d")


# --- 💼 보유종목 상세 화면 열기 ---
show_portfolio = st.sidebar.toggle(
    "보유종목 상세 화면 (가져오기·판정)", value=st.session_state.get('show_portfolio', False),
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


import premarket as _pm_mod


# ── 산출물 읽기 (라운드 188에 위로 옮김) ──────────────────────────────
# 종전에는 이 둘이 5,100행대에 있었다. 그런데 **스캔 블록(3,000행대)** 이
# 신호율을 화면에 적으면서 파일을 못 읽어 `2.9%` 를 손으로 박아 두고
# 있었고, 그 값이 원장이 자라는 동안 낡아 지금 값(7.2%)과 2.5배 벌어졌다.
# 정의를 위로 올려 **두 자리가 같은 파일을 읽게** 한다 (§4). 함수 본문은
# 한 글자도 안 바꿨다 — 순수 이동이다.
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
def _cal_made_date():
    """캘리브레이션 숫자를 **언제 쟀나** — 없으면 None (지어내지 않는다).

    ⚠️ 라운드 188 — `calibration.json` 에는 날짜 필드가 아예 없다. 그래서
      화면이 인용하는 적중률·신호율·건수가 **전부 날짜 없이** 나가고 있었다.
      §9 는 *"숫자를 인용할 때는 잰 날짜를 같이 적는다 — 날짜 없는 숫자는
      반드시 낡는다"* 고 못 박았고, 실제로 신호율 2.9% 가 7.2% 가 되도록
      아무도 몰랐다. 같은 묶음을 만든 `data/bundle_meta.json` 의 `made` 가
      그 날짜다. 없으면 None 을 돌려주고 화면은 날짜를 안 적는다.
    """
    try:
        import json as _json_md
        _p = _artifact_path("bundle_meta.json")
        if not _p:
            return None
        with open(_p, encoding='utf-8') as _f:
            return (_json_md.load(_f) or {}).get('made') or None
    except Exception:
        return None


# 카드가 쓰는 자산유형 한글 이름 — 카드 조립 함수와 같은 자리에 둔다
# (라운드 39: 함수만 올리고 이 표를 두고 와서 NameError 가 났다)
_ASSET_KO = {'STOCK': '주식', 'ETF': 'ETF', 'ETF_LEV': '레버리지 ETF',
             'ETF_INV': '인버스 ETF'}

# ── 추천 카드 조립 (라운드 39: 모듈 수준으로 끌어올림) ──────────────
# 개장 전 추천과 오늘의 관심종목 후보가 **같은 카드**를 써야 하는데,
# 이 함수가 개장 전 블록 안에 갇혀 있어 목록마다 자기만의 카드를 만들었다.
# 한 화면에 두 종류의 카드가 보이면 어느 쪽을 믿을지 알 수 없다.
def _build_reco_card(p, news_txt, conf_txt):
    """
    스캔 결과 한 건 → 카드가 읽을 값 묶음.

    여기서 지키는 것 (하나라도 어기면 사용자가 값을 잘못 읽는다):
      · 가격 순서는 늘 현재가 → 권장 → 목표 → 손절
      · 목표·손절은 **진입가 기준**만 카드에 올린다. 현재가 기준(보유자용)은
        같은 카드에 섞지 않고 경고 상자로 한 줄만 안내한다.
      · 권장가가 없으면 목표·손절을 **아예 감춘다** — 참고값을 실행 가격
        자리에 두지 않는다.
      · 권장가가 멀면(2σ 초과) 목표·손절을 흐리게 — 닿지 않을 값을
        진하게 두면 실행 가격처럼 보인다.
    """
    _n = p.get('next_action') or {}
    cls = str(p.get('reco_class') or '')
    # ── 중앙 판정 우선 (라운드 34) ────────────────────────────────
    # 카드가 자기만의 가격 조합을 만들면 상세 화면과 어긋난다(라운드 31
    # 진단 ⑤). 중앙 판정이 있으면 그것만 읽고, 없을 때만(옛 리포트)
    # 예전 키로 폴백한다.
    _core = p.get('core') or {}
    price = p.get('price')
    if _core:
        rec = _core.get('pullback_zone') or (
            (_core.get('buy_zone') or [None])[0])
        e_t1, e_stop = _core.get('new_target'), _core.get('new_stop')
    else:
        rec = p.get('rec_buy')
        e_t1, e_stop = p.get('entry_target_1st'), p.get('entry_stop_price')
    # 정합 가드 (라운드 30) — 동결 리포트는 옛 엔진 값을 그대로 들고
    # 있어서, 손절이 매수가 위이거나 목표가 매수가 아래인 카드가 나온다
    # (실측: GS 92,011 매수에 손절 100,775 · NAVER 214,733 매수에 목표
    # 172,895). 성립하지 않는 문장은 **표시하지 않는다** — 경고만 달고
    # 그대로 보여 주면 사용자는 그 숫자를 읽는다.
    if rec:
        if e_stop is not None and float(e_stop) >= float(rec):
            e_stop = None
        if e_t1 is not None and float(e_t1) <= float(rec):
            e_t1 = None
    # ⚠️ 라운드 190 — 카드의 σ가 **화면에 뜼 가격과 다른 값** 기준
    #   이었다. `rec_buy_sigma` 는 엔진이 적정가×안전마진
    #   (`recommended_buy_price` · 라운드 25 폐기 산식)으로 쟠 값인데,
    #   카드가 그리는 가격은 `pullback_zone`(현재가−1σ)이다.
    #   배너는 이미 고쳤는데(:6511 주석) 카드만 남아 한 줄이
    #   `211,023원 · −8.5% · 1.05σ` 처럼 앞뒤 기준이 달랐다.
    #   **중앙 판정의 값을 쓴다** (§4 — 화면 값은 한 곳에서).
    #   단위도 같아진다: `depth_sigma` 는 **하루 σ 배수**고,
    #   배너의 사다리(0.5/1.0/2.1)가 바로 그 단위다.
    _core_sig = (_core or {}).get('depth_sigma')
    if _core_sig is not None:
        sig = _core_sig
        reach = ('가까움' if sig <= 0.5 else
                 '닿을 만함' if sig <= 1.0 else
                 '멀다' if sig <= 2.1 else '사실상 도달 어려움')
    else:                                  # 중앙 판정이 없는 옛 리포트
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
    # ⚠️ 라운드 185 — 중앙 판정이 있으면 **분류(bucket)를 그대로** 배지로
    #   쓴다. 종전의 kind→라벨 사본이 '장기 관찰'(라운드 47 이 "언제 다시
    #   봐야 하는지 알 수 없다"며 지운 이름)을 되살려, 같은 카드가 칸 제목
    #   ('실제로 손댈 수 있는 후보')과 배지('장기 관찰')와 본문("매수
    #   후보에서 뺐습니다")으로 **세 가지 다른 말**을 했다 — 서진시스템
    #   실측. 사본은 중앙 판정이 없는 옛 리포트에서만 쓴다.
    _NA_LABEL = {'buy_now': '지금 분할매수', 'pullback': '눌림목 대기',
                 'breakout': '돌파 확인 대기', 'observe': '오늘 후보 아님',
                 'blocked': '매수 차단', 'no_data': '데이터 부족'}
    label = (_core.get('bucket')
             or _NA_LABEL.get(_n.get('kind'))
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
    if _core.get('bucket') in ('추천 제외', '데이터 부족'):
        # 제외는 회색(관망)이 아니라 빨강 — 대기와 다른 말이다
        state = 'neg' if _core.get('bucket') == '추천 제외' else 'hold'

    # 쉬운 설명 — "사지 마세요"로 끝내지 않는다. 다음 조건 엔진이
    # 낸 한 줄을 먼저 쓰고, 조건들은 아래 목록으로 붙인다.
    # ⚠️ 라운드 177 — 산문에 **날 `<b>` 태그**를 쓰면 안 된다. 사용자 화면에
    #   `<b>분석 보기</b>` 가 **글자 그대로** 나왔다.
    #   `ui_kit._esc()` 는 이스케이프를 먼저 하고 `**굵게**` 표기만 되살린다
    #   (라운드 120d — "산문은 마크다운으로 쓴다, 받는 쪽에서 해석한다").
    #   그러니 굵게는 `**…**` 로 적는다.
    # 산문도 카드 줄과 같은 이름을 쓴다 (라운드 186 — 줄 이름이 '검토
    # 기준가'인데 산문이 '권장 매수가'라 부르면 같은 카드가 두 말을 한다)
    _lb = str((_core.get('entry_label') if _core else None) or '검토 기준가')
    if _n.get('headline'):
        say = f"**{_n['headline']}**"
        if rec and gap is not None and gap > 0:
            say += f" 현재가는 {_lb}보다 {gap:.1f}% 높습니다."
    elif rec and gap is not None and gap > 0:
        say = (f"현재가가 {_lb}보다 **{gap:.1f}%** 높습니다. "
               + ("단기간에 매수 구간까지 내려올 가능성이 낮아 "
                  "**지금은 기다리는 편**이 낫습니다."
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
            f"**분석 보기**에서 확인하세요.")
    elif not rec:
        hold_note = ("**진입 기준이 없어 목표가·손절가를 표시하지 "
                     "않습니다.** 참고값은 분석 보기에서 확인하세요. "
                     "지금은 신규 매수 판단을 보류합니다.")

    # ⚠️ 라운드 182 — 적정가를 못 낸 종목은 **그 사실을 이 카드에서** 말한다.
    #   사용자 지적: *"서진시스템은 펀더멘털 적정가가 안 나오는데 왜
    #   추천한 거야?"* — 카드가 권장 매수가·목표·손절을 다 내면서 그 값이
    #   **밸류 검증을 못 받았다**는 말을 안 하고 있었다. 적정가 미산출은
    #   화면 아래쪽 다른 칸에 있어 이어 읽히지 않았다.
    #   거르지는 않는다(§3) — 대신 **같은 카드에서** 밝힌다.
    _vchk = str((_n or {}).get('value_check') or '')
    if _vchk:
        hold_note = (_vchk + (' ' + hold_note if hold_note else ''))

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
        # 라운드 186 — 이 줄의 이름은 중앙 판정이 정한다 (사용자 R184 분석
        #   P1: 추천 통과가 아니면 '권장'이라 부르지 않는다). 중앙 판정이
        #   없는 옛 리포트는 킷 기본값(검토 기준가)으로 떨어진다.
        'rec_label': (_core.get('entry_label') if _core else None),
        'rec_na': ('차단됨' if '사면 안' in cls else '미산출'),
        'target': e_t1 if rec else None,
        # '권장가 기준' → '진입가 기준' (라운드 186) — 기준가가 검토
        # 기준가일 때도 참인 중립 표기다. verdict_core.price_basis 와 같은
        # 낱말이라 새 이름이 아니다 (§2 재사용).
        'target_basis': ('진입가 기준'
                         + (f" · 손익비(진입가·1차) {p['entry_rr']}:1"
                            if p.get('entry_rr') else '')) if rec else '',
        'stop': e_stop if rec else None,
        'stop_basis': '진입가 기준' if rec else '',
        'dim_levels': far,
        'say': say, 'hold_note': hold_note,
        'news': ' · '.join(news_txt) if news_txt else '특이 뉴스 없음',
        'hit': conf_txt,
        # 라운드 98 — '실행 기준'을 붙여 유사패턴 관찰기간과 구별한다.
        # 같은 화면에 20일과 40일이 이름 없이 같이 있어 모순처럼 보였다.
        'horizon': (f"실행 기준 보유 {p['horizon_days']}거래일"
                    if p.get('horizon_days') else None),
        # 다음 조건 — 무엇을 기다리는지 카드에 적는다
        'next_conditions': [c['text'] for c in (_n.get('conditions') or [])],
        # 왜 이 종목인가 (라운드 47) — 근거가 없으면 카드가 이 칸을 생략한다
        'why': p.get('why'),
        # 가치 프리미엄 (라운드 133) — 사용자 지적: "적정가보다 매수가가
        # 높아서 선뜻 못 사겠다." 화면을 보니 **카드에 가치 정보가 한 줄도
        # 없었다.** `권장 매수가 -7.5%` 만 보고 싼 줄 알았다가 상세에서
        # 적정가를 보면 어긋난다. 계산은 킷 한 곳에서만 한다 (§4).
        # 표시 전용 — 판정·게이트에 안 쓴다 (라운드 28b).
        'value_premium': _uk.value_premium(rec,
                                           p.get('displayed_fair_value')),
    }

# ── 낡은 리포트는 가격을 화면에 두지 않는다 (라운드 30) ──────────────
# 경고만 달고 카드를 그대로 보여 주면 사용자는 그 숫자를 읽는다. 실제로
# 옛 엔진 카드에는 성립하지 않는 값이 있었다(손절이 매수가 위 등).


#: 스캔 단계 — 화면이 '몇 단계 중 몇 번째'를 말할 수 있게 한 곳에 적는다.
#  퍼센트를 지어내지 않는다. 종목 단위 진척은 엔진이 알려 주지 않으므로
#  (`run_screener_scan` 은 콜백이 없다 · §1 계산 파일은 안 건드린다)
#  **단계 단위**로만 말한다 — 2/4 는 50% 가 맞고, 그 이상은 추측이다.
_SCAN_STEPS = ('종목·시장 구분 확인', '관심종목 발굴', '관심지표 계산',
               '정밀 분석')


def run_market_scan():
    """관심종목 발굴 → 정밀 퀀트 분석. 두 단계를 명확히 분리한다."""
    _bar = st.sidebar.empty()
    _st = {'step': 0, 't0': time.time()}

    def _scan_done():
        """진행 표시를 끈다 — 켠 곳이 하나면 끄는 곳도 하나여야 한다.

        라운드 189: 켜는 코드가 없어 표시가 죽어 있었다. 살리면서 **끄는
        길이 둘**(조기 반환·정상 종료)이라 한 곳으로 모은다. 안 그러면
        조기 반환에서 '처리 중 ●' 이 영원히 남는다.
        """
        st.session_state['scan_busy'] = False
        st.session_state['scan_stage'] = ''
        st.session_state['_sb_busy'] = ''

    def _progress(msg, step=None):
        """진행 표시 — 단계·퍼센트·경과 시간을 함께 적는다 (라운드 122).

        종전에는 문장 한 줄만 있었다. 오래 걸리는데 얼마나 남았는지
        화면이 말하지 않으면 사용자는 멈춘 것으로 읽는다.
        경과는 **갱신 시점**의 값이다 — 막힌 호출 중에는 흐르지 않는다.
        그래서 '지난번엔 몇 초 걸렸다'를 같이 적어 기다릴 길이를 준다.
        """
        if step is not None:
            _st['step'] = step
        _cur = max(1, min(_st['step'], len(_SCAN_STEPS)))
        # ⚠️ 라운드 189 — 진행 표시 세 자리가 **통째로 죽어 있었다.**
        #   `_sb_busy`(web_app:1874) · `scan_busy`·`scan_stage`
        #   (live_ticker:51-55) 를 읽는 코드는 있는데 **쓰는 곳이 저장소
        #   어디에도 없어** 늘 빈 값이었다. 그래서 아코디언의 '처리 중 ●'
        #   과 상단 띠의 '지금 돌고 있는 작업' 이 한 번도 안 떴다.
        #   읽는 쪽이 기대하는 그대로 채운다 (§4 — 키는 한 벌만 쓴다).
        st.session_state['scan_busy'] = True
        st.session_state['scan_stage'] = _SCAN_STEPS[_cur - 1]
        st.session_state['_sb_busy'] = _SB_STEPS[3]['key']
        _pct = int(round(100 * _cur / len(_SCAN_STEPS)))
        _el = time.time() - _st['t0']
        _prev = st.session_state.get('scan_last_secs')
        _prev_txt = (f" · 지난번 {_prev:.0f}초" if _prev else '')
        _bar.markdown(
            f"<div style='padding:2px 0 6px 0;'>"
            f"<div style='display:flex; justify-content:space-between; "
            f"font-size:12px; color:{_TOK['tx2']}; margin-bottom:5px;'>"
            f"<span>{_cur}/{len(_SCAN_STEPS)}단계 · "
            f"{_uk._esc(_SCAN_STEPS[_cur - 1])}</span>"
            f"<span style='font-variant-numeric:tabular-nums;'>{_pct}%</span>"
            f"</div>"
            # `_TOK` 는 킷의 `raised` 를 `hover` 라는 이름으로 담는다
            # (_pal 이 이름을 바꿔 싣는다). 킷 키를 그대로 쓰면 KeyError 다 —
            # 실제로 그렇게 써서 스캔이 통째로 죽었다 (라운드 122).
            f"<div style='height:4px; border-radius:3px; "
            f"background:{_TOK['hover']}; overflow:hidden;'>"
            f"<div style='width:{_pct}%; height:100%; "
            f"background:{_TOK['brand']};'></div></div>"
            # §77 — 화면 글자는 12px 미만으로 내려가지 않는다. 여기서
            # 11px 을 썼다가 회귀가 잡았다 (라운드 122).
            f"<div style='font-size:12px; color:{_TOK['tx3']}; "
            f"margin-top:5px; line-height:1.5;'>{_uk._esc(msg)}<br>"
            f"경과 {_el:.0f}초{_prev_txt}</div></div>",
            unsafe_allow_html=True)

    # 1단계 — 오늘의 관심종목 발굴 (순위 페이지 → 후보에만 일봉)
    # '사용자 관심종목' 방식은 저장된 관심종목 + 보유종목을 대상으로 한다
    watch = [w['code'] for w in (st.session_state.get('watchlist') or [])]
    watch += [p.ticker.split('.')[0] for p in (st.session_state.get('positions') or [])
              if p.ticker.split('.')[0] not in watch]
    # ── 전 종목 경량 스캔 ────────────────────────────────────────────
    # 순위 페이지 2종에서만 출발하면 거래가 한산한 종목은 애초에 후보가
    # 되지 못한다. 유니버스에는 이미 시총·거래대금이 실려 있으므로
    # **추가 요청 없이** 전 종목을 한 번 훑을 수 있다. 여기서 거르는 건
    # 데이터가 없거나 유동성이 없어 어차피 못 사는 종목뿐이다.
    #
    # ⚠️ 라운드 37 — 이 블록은 관심종목 탐색 **앞**에 와야 한다.
    # 종전에는 뒤에 있었고, 순위 페이지가 비면 그 전에 return 해 버려서
    # 경량 스캔이 **실행조차 안 된 채** 화면에 '0개'로 찍혔다. 사용자는
    # "전 종목을 훑었는데 하나도 없구나"로 읽는다 — 사실이 아니었다.
    _progress("종목 코드·시장 구분 확인 중", step=1)
    universe = engine_init.get_screener_universe(full_market=True)
    by_code = {u['symbol'].split('.')[0]: u for u in universe}

    _MIN_TRADE_VALUE = 5e8          # 당일 거래대금 5억원
    # ⚠️ 라운드 37 — **못 잰 것으로 거르지 않는다.**
    # 유니버스가 거래대금을 안 실어 오는 시간대(장 시작 전 등)에는
    # today_trade_value 가 전 종목 None 이고 liquidity_confirmed 도 전부
    # False 다. 종전 코드는 이걸 '유동성 없음'으로 세어 2,997종목을 전부
    # 탈락시켰고, 화면은 "유동성·데이터 조건 통과 0개"라고 말했다.
    # 실제로는 유동성이 없는 게 아니라 **거래대금을 수집하지 못한 것**이다.
    # 그래서 수신율을 먼저 보고, 거의 안 왔으면 그 필터를 끈다.
    _tv_seen = sum(1 for u in universe if (u.get('today_trade_value') or 0) > 0)
    _tv_usable = _tv_seen >= max(20, len(universe) * 0.05)
    _lite = {'total': len(universe), 'no_price': 0, 'no_liquidity': 0,
             'thin': 0, 'passed': 0, 'tv_seen': _tv_seen,
             'tv_usable': _tv_usable}
    _lite_pass, _lite_rows = set(), []
    for u in universe:
        if not u.get('base_price'):
            _lite['no_price'] += 1
            continue
        if _tv_usable:
            if not u.get('liquidity_confirmed'):
                _lite['no_liquidity'] += 1
                continue
            if (u.get('today_trade_value') or 0) < _MIN_TRADE_VALUE:
                _lite['thin'] += 1
                continue
        _lite_pass.add(u['symbol'].split('.')[0])
        _lite_rows.append(u)
    _lite['passed'] = len(_lite_pass)
    st.session_state['scan_lite'] = _lite

    # 순위 페이지가 죽으면 경량 스캔 통과 종목을 거래대금 순으로 대신 쓴다
    _progress("거래대금·상승률 순위에서 관심종목 추리는 중", step=2)
    att = market_attention.find_attention_candidates(
        attention_strategy, top_n=scan_depth, progress=_progress,
        watchlist=watch, fallback_pool=_lite_rows)
    st.session_state['attention_result'] = att
    if att.get('unavailable') or not att['rows']:
        _scan_done()
        _bar.empty()
        st.session_state['scan_results'] = []
        st.session_state['scan_universe_total'] = att.get('pool_size', 0)
        return

    # 2단계 — 후보에 시장 구분을 붙여 기존 정밀 파이프라인에 넘긴다

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

    # 막대는 지우지 않는다 — 가장 오래 걸리는 단계에서 화면이 비면
    # 사용자는 멈춘 것으로 읽는다 (라운드 122).
    _progress(f"관심종목 {len(target)}개를 하나씩 정밀 분석하는 중", step=4)
    with st.spinner(f"관심종목 {len(target)}개 정밀 분석 중... (4/4단계)"):
        st.session_state['scan_results'] = q_engine.run_screener_scan(
            target, t_ref_str, b_engine=engine_init, rho_cutoff=rho_cutoff)
    # ⚠️ 라운드 216 — 실패 사유가 **rerun 을 못 넘고 있었다.** 라운드 37 이 조용히
    #   사라지던 종목을 `q_engine.last_scan_failures` 에 남기게 했는데, `q_engine`
    #   은 모듈 수준에서 **매 rerun 새로 만들어진다**(:1631). 스캔이 끝나면 이
    #   함수가 st.rerun() 을 부르고, 다음 그리기의 요약 칸은 **새 엔진의 빈
    #   목록**을 읽었다. 결과(scan_results)는 세션에 남고 사유만 증발해 화면이
    #   "완료 4 · 제외 0" 이면서 그 종목은 '정밀분석 결과 없음'이라 적었다 —
    #   사용자의 "5개(1개 실패)" 가 이것이다(실측: 상위 5 → 완료 4 · 누락 1).
    #   결과와 **같은 곳**(세션)에 사유도 남긴다 (§4).
    st.session_state['scan_failures'] = list(
        getattr(q_engine, 'last_scan_failures', None) or [])
    # 다음번에 '얼마나 기다리면 되는지' 말할 수 있게 실제 소요를 남긴다.
    st.session_state['scan_last_secs'] = time.time() - _st['t0']
    _scan_done()
    _bar.empty()

    # 관심점수를 결과 행에 붙인다 (순위에는 동점 보조기준으로만 쓴다 — §12)
    _att_by_symbol = {t['symbol']: t for t in target}
    for row in (st.session_state.get('scan_results') or []):
        src = _att_by_symbol.get(row.get('symbol'))
        if src:
            row['attention'] = src['attention']
            row['selection_reason'] = src['selection_reason']
            row['attention_components'] = src['attention_components']


if st.session_state.get('pending_scan'):
    # ⚠️ 라운드 38 — pop() 을 쓰면 안 된다.
    # 사이드바는 이 지점보다 **먼저** 그려진다. pop 으로 플래그를 지우면
    # 스캔이 도는 동안 사이드바가 '아직 최신화하지 않았습니다'라고 말하고
    # 버튼도 눌리는 상태가 된다(실측). 플래그는 스캔이 끝날 때까지 켜 두고,
    # 끝난 뒤 rerun 해서 사이드바가 완료 시각을 반영하게 한다.
    # 실패해도 finally 로 반드시 풀어 버튼이 영구 비활성되지 않게 한다.
    try:
        run_market_scan()
    finally:
        import datetime as _dt_scan
        st.session_state['scan_done_at'] = (
            _dt_scan.datetime.now().strftime('%H:%M:%S'))
        st.session_state['pending_scan'] = False
    st.rerun()          # 사이드바에 '최신화 완료 · HH:MM:SS' 를 띄운다

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
        # ⚠️ 라운드 187 — 제목이 **'오늘의 AI 퀀트 최적 종목 TOP 3'** 이었다.
        #   두 군데가 과장이다. ① '최적' — 전 종목이 아니라 관심점수 상위
        #   몇 개만 정밀분석한 결과다(바로 아래 '어디까지 봤나' 칸이 그
        #   사실을 이미 적고 있어 제목과 어긋났다). ② 'TOP 3' — 순위를
        #   주장하는데, 라운드 110 이 원장 166,132건으로 재서 같은 날 점수
        #   상위와 하위의 성적 차이가 **0.0%p**(부호검정 z −1.39, 유의하지
        #   않음)였다. 우리가 없다고 발표한 것을 제목이 팔면 안 된다 (§9).
        #   목록이 실제로 담는 것은 '필수조건을 통과한 종목'이다.
        st.subheader("오늘 추천 필수조건을 통과한 종목")
        if 'scan_results' not in st.session_state:
            run_market_scan()
        scan_results = st.session_state['scan_results']
        if True:
            
            # [명세 §15] 필수조건을 모두 통과한 종목만 추천한다.
            # 통과 종목이 2개면 2개, 0개면 '현재 추천주 없음'.
            # 구버전은 통과 0개일 때 조건 미달 종목을 상승여력% 순으로 3칸 채워 넣었다.
            # 라운드 216 — 사유는 **세션**에서 읽는다. 엔진 객체는 rerun 마다 새로
            #   만들어져 그 속성은 스캔 다음 그리기부터 비어 있다 (:3087 주석).
            scan_failures = list(st.session_state.get('scan_failures')
                                 or getattr(q_engine, 'last_scan_failures', None) or [])
            # 분류가 빠진 행 하나 때문에 화면 전체가 죽지 않게 한다
            # (한 종목의 오류가 전체를 막지 않는다는 원칙을 표시 단계에도 적용)
            def _cat(row):
                return str(row.get('cat') or '')
            recommended = [r for r in scan_results if "추천주" in _cat(r)]
            # ⚠️ 아래 요약 칸은 예전에 scan_results 의 `cat` 문자열을 따로
            #    세었다. 그런데 목록 자체는 verdict_core 의 bucket/actionable
            #    로 갈린다 — **경로가 둘이라 화면이 스스로 모순됐다.**
            #    실제로 "조건 충족을 기다리는 후보 1종목 · 뺀 4종목" 아래에
            #    "눌림 대기 0 · 관찰 후보 0 · 추천 제외 5" 가 찍혔다.
            #    합계만 같고 내역이 달랐다 (§4 — 화면 값은 한 곳에서 나온다).
            #    이제 목록을 만든 그 분류를 그대로 받아 쓴다. 분류가 안 만들
            #    어졌으면 숫자를 지어내지 않고 그 사실을 적는다 (§3).
            _bucket_counts = None

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
            # 분모가 0 이면 비율을 만들지 않는다 — 종전에는 max(1, …) 때문에
            # '0.0% (5/1)' 이라는 말이 안 되는 표시가 나갔다 (라운드 37).
            _deep_pass = int(_lt.get('passed') or 0)
            _deep_rate_txt = (f"{scan_depth / _deep_pass * 100:.1f}% "
                              f"({scan_depth}/{_deep_pass:,})"
                              if _deep_pass > 0
                              else "미산출 — 경량 스캔이 0개를 반환했습니다")
            # ── 라운드 215 — 4단계 후보 전부를 **셈으로 맞춘다** (§3) ──────
            # 사용자: *"사용한 도구 5개(1개 실패) 뭐야? 실패 안 되게 스마트하게."*
            # 종전 줄은 '완료 N · 제외 M' 만 적어, 상위 5 중 유니버스에서 코드를
            # 못 찾아 정밀분석 **전에** 빠진 후보(`attention_unmapped`)가 셈에서
            # 조용히 사라졌다 — 실측 "상위 5 → 완료 4 · 제외 0". 못 잰 것을
            # 표시 없이 지나가면 §3 위반이다. 완료+제외+미매핑+누락 = 상위 N 이
            # 되게 하고, 남는 차이는 '누락(사유 미기록)'이라 그대로 적는다.
            # 제외 사유 첫 건은 접힌 칸을 열지 않아도 보이게 요약 줄에 붙인다.
            # 재시도는 더하지 않았다 — 시세 수신은 fetch_html_with_retry 가 이미
            # 재시도하고, 교차검증 불일치의 스캔 중단은 일부러 둔 안전장치다.
            _scan_unm = len(st.session_state.get('attention_unmapped') or [])
            _scan_lost = max(0, int(scan_depth) - len(scan_results)
                             - len(scan_failures) - _scan_unm)
            _scan_why1 = ((" — 예: " + _uk._esc(str(scan_failures[0].get('reason') or '')[:48]))
                          if scan_failures else "")

            st.markdown(f"""
            <div style='background:#161D2A; padding:16px; border-radius:10px; margin-bottom:16px; '>
                <h4 style='color:#F3F6FA; margin-top:0;'>시장 스캔 완료 — 어디까지 봤나</h4>
                <ul style='color:#9DAABC; font-size:15px; line-height:1.6; margin-bottom:8px;'>
                    <li>분석 기준일: {t_ref_str} · rho {rho_cutoff}</li>
                    <li>1단계 <b>전 종목 경량 스캔</b>: 코스피·코스닥 <b>{_lt.get('total', 0):,}개</b>
                        → 유동성·데이터 조건 통과 <b>{_lt.get('passed', 0):,}개</b>
                        <span style='font-size:13px;'>{
                            f"(시세 없음 {_lt.get('no_price', 0):,} · "
                            f"거래 미확인 {_lt.get('no_liquidity', 0):,} · "
                            f"거래대금 5억 미만 {_lt.get('thin', 0):,} 제외)"
                            if _lt.get('tv_usable')
                            else f"(거래대금 미수신 — 유동성 필터를 적용하지 "
                                 f"않았습니다. 수신 {_lt.get('tv_seen', 0):,}종목. "
                                 f"못 잰 것으로 거르지 않습니다)"
                        }</span></li>
                    <li>2단계 후보 풀: <b>{st.session_state.get('scan_universe_total', 0):,}개</b>
                        — 거래대금·상승률 순위 상위에서 수집 (ETF·우선주·스팩·리츠 제외)</li>
                    <li>3단계 관심지표 계산: 최대 <b>{_deep_cap:,}개</b>
                        → 실제 <b>{_deep_done:,}개</b></li>
                    <li>4단계 정밀분석: <b>{_sel_strat_label}</b> 상위 <b>{scan_depth}개</b>
                        → 완료 {len(scan_results)}개 · 제외 {len(scan_failures)}개{_scan_why1}{
                            f' · 유니버스 미매핑 {_scan_unm}개(정밀분석 전에 빠짐)' if _scan_unm else ''}{
                            f' · <b>누락 {_scan_lost}개</b>(사유 미기록 — 셈이 안 맞습니다)' if _scan_lost else ''}</li>
                    <li>최종 행동 필수조건 통과: <b style='color:{"#35C98B" if recommended else "#F2B84B"};'>{len(recommended)}개</b></li>
                    <li><b>전체 시장 정밀분석 비율: {_deep_rate_txt}</b></li>
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
            # 라운드 188 — 신호율·블라인드 성적을 **파일에서 읽는다.**
            #   손으로 박은 값이 원장이 자라는 동안 낡았다(2.9% vs 7.2%).
            _cal188 = _load_calibration_meta()
            _sf188 = (_cal188.get('signal_frequency') or {})
            _bz188 = ((_cal188.get('splits') or {}).get('buy_zone') or {})
            _bl188 = (_bz188.get('blind') or {})
            _made188 = _cal_made_date()
            # ── 라운드 214 — 신호 계층과 '실제로 손댈 수 있는 후보'를 **한 판정**으로 ──
            # 사용자 지적: *"확장 신호 1종목 — SK이노베이션(59점)인데 다음 거래일에
            # 실제로 손댈 수 있는 후보는 DB손해보험만 나와. 정리해줘야 하는 거 아냐?
            # 관심후보랑 추천후보랑 정리해줘야 하는 거 아닌가?"*
            # 맞다. 이 배너는 **원점수 띠**(58~59 · 60+)로 걸렀고, 아래 실행 후보는
            # `verdict_core` 의 bucket 으로 갈랐다 — 같은 종목을 두 경로로 세는
            # §4 위반(라운드 114 의 그것)이다. 원점수 띠는 *신호*고 bucket 은
            # *판정*이라 둘 다 사실이지만, **왜 신호가 판정에서 빠졌는지**를 배너가
            # 말하지 않아 모순으로 읽혔다.
            # → 판정은 코드마다 **한 번만** 계산한다(`_pick_of` 메모). 배너의
            #   종목 옆에 그 bucket 을 붙이고, 아래 실행/대기/뺌 목록도 **같은
            #   메모·같은 분류 함수**(`_sig_class`)를 읽는다.
            _pick_memo = {}

            def _pick_of(code, sr):
                """scan 행 → premarket pick(verdict_core 포함). 한 코드에 한 번."""
                if code not in _pick_memo:
                    try:
                        _pick_memo[code] = _pm_mod.pick_from_scan_row(q_engine, sr)
                    except Exception:                          # noqa: BLE001
                        _pick_memo[code] = None
                return _pick_memo[code]

            import verdict_core as _vcore214
            #: 조건을 제시할 수 있는 대기 — 아래 대기 목록과 **같은 튜플**이다
            _WAIT_OK_214 = ('과열 해소 대기', '거래량 회복 대기',
                            '시장 국면 회복 대기', '신뢰도·표본 확보 대기')

            def _sig_class(core):
                """verdict_core 결과 → 'live' | 'wait' | 'drop'. 배너·목록이 같이 쓴다."""
                _c = core or {}
                if _c.get('actionable'):
                    return 'live'
                _bk = str(_c.get('bucket') or '')
                if _bk in _WAIT_OK_214 or _bk in _vcore214.ACTIONABLE_BUCKETS:
                    return 'wait'
                return 'drop'

            _SIG_KO_214 = {'live': '실행 후보', 'wait': None, 'drop': None}

            def _sig_tag(r):
                """배너 한 종목: 이름(점수 · 판정). 못 냈으면 그렇게 적는다 (§3)."""
                _cd = str(r.get('symbol', '')).split('.')[0]
                _co = ((_pick_of(_cd, r) or {}).get('core') or {})
                _cls = _sig_class(_co) if _co else None
                if _cls == 'live':
                    _tag = '실행 후보'
                elif _co.get('bucket'):
                    _tag = str(_co.get('bucket'))
                else:
                    _tag = '판정 미산출'
                return f"{r.get('name')}({r.get('final_score')}점 · {_tag})"
            _bz_rate_txt = (f"{_sf188['rate_pct']}%" if _sf188.get('rate_pct')
                            is not None else "미산출")
            if _made188:
                _bz_rate_txt += f" (잰 날 {_made188})"
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
                    + " · ".join(_sig_tag(r) for r in _bz_rows[:5])
                    # ⚠️ 라운드 188 — 여기가 '실측 신호율 2.9%' 로 **박혀**
                    #   있었다. 원장이 자란 지금 값은 7.2% 다(2.5배 차이).
                    #   같은 앱의 홈 타일은 이 값을 파일에서 읽어 7.2% 를
                    #   띄우고 있어 **한 앱이 두 숫자를 말했다.**
                    #   날짜 없는 숫자는 반드시 낡는다 (§9) — 파일에서 읽고
                    #   잰 날을 함께 적는다.
                    + f"  \n실측 신호율 {_bz_rate_txt}의 드문 구간입니다. "
                      f"아래 표에서 종목을 눌러 조건을 확인하세요.")
            if _ext_rows:
                # 라운드 2.5: 이 중 '적정가 이하' 종목이 실측상 가장 좋다
                # (검증 64.2% → 블라인드 61.9%·비용후 +1.15%)
                _ext_below = [r for r in _ext_rows if r.get('entry_candidate')]
                _ext_msg = (
                    f"**확장 신호(58~59점) {len(_ext_rows)}종목** — "
                    + " · ".join(_sig_tag(r) for r in _ext_rows[:6])
                    # ⚠️ 라운드 188 — 종전 문구는 원장 6,508건 시절(2026-08-02)
                    #   값을 **잰 날 없이** 인용했다. 잰 날을 적는다 (§9).
                    + f"  \n사전등록 실측(원장 6,508건 시점 · 2026-08-02): "
                      f"검증 62.5%(n=456) → 블라인드 55.3%(n=226), "
                      f"비용 차감 후 소폭 음수 — 탐색용.")
                if _ext_below:
                    # ⚠️ 라운드 188 — 여기가 **"유일한 비용후 양수 계층입니다"**
                    #   였다. 원장 6,508건 시절의 n=95 짜리 주장인데, 지금
                    #   원장(184,759건)에서 매수권 60+ 블라인드는
                    #   n=1,068 · 적중 51.3% · **비용후 −1.81%** 다.
                    #   화면이 우리가 재서 없다고 발표한 우위를 팔고 있었다 —
                    #   §9 가 금지한 바로 그것이다. 옛 값은 **그때 값이라고**
                    #   적고, 지금 값을 나란히 둔다.
                    _bl_txt188 = (
                        f"지금 원장에서 매수권(60+) 블라인드는 "
                        f"적중 {_bl188['hit_rate']}%(n={_bl188['n']:,}) · "
                        f"비용후 {_bl188['avg_return_after_cost']:+.2f}%"
                        + (f" · 잰 날 {_made188}" if _made188 else "")
                        + "로, 그 우위는 재현되지 않았습니다."
                        if _bl188.get('hit_rate') is not None else
                        "지금 원장의 블라인드 성적은 미산출입니다.")
                    _ext_msg += (
                        f" \n이 중 **적정가 이하 진입 {len(_ext_below)}종목** ("
                        + " · ".join(r.get('name') for r in _ext_below[:4])
                        + ") — 원장 6,508건 시점(2026-08-02)에는 이 조건이 "
                          "블라인드 58.9%(n=95)·비용후 +0.55% 였습니다. "
                        + _bl_txt188)
                st.info(_ext_msg)
            if not _bz_rows and not _ext_rows:
                st.caption("이번 스캔에는 매수권(60점+)·확장 신호(58~59점)가 모두 "
                           "없습니다 — 없는 날은 관망이 결론입니다.")
            else:
                # 신호와 판정을 **한 줄로 잇는다** (라운드 214). 아래 '다음 거래일에
                # 실제로 손댈 수 있는 후보'가 쓰는 것과 같은 메모·같은 함수다.
                _sig_cnt = {'live': 0, 'wait': 0, 'drop': 0}
                for _r in _bz_rows + _ext_rows:
                    _co = ((_pick_of(str(_r.get('symbol', '')).split('.')[0], _r)
                            or {}).get('core') or {})
                    _sig_cnt[_sig_class(_co)] += 1
                st.caption(
                    f"신호 {len(_bz_rows) + len(_ext_rows)}종목의 판정 — 실행 가능 "
                    f"**{_sig_cnt['live']}** · 조건 대기 **{_sig_cnt['wait']}** · "
                    f"추천·대기에서 뺌 **{_sig_cnt['drop']}**. 아래 '다음 거래일에 "
                    f"실제로 손댈 수 있는 후보'와 **같은 판정**입니다 — 신호(원점수 "
                    f"띠)와 판정(11개 조건)은 다른 잣대라 신호가 있어도 판정에서 "
                    f"빠질 수 있고, 그 이유를 종목 옆에 적었습니다.")

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
                    # ⚠️ 라운드 135 — 이 버튼은 기존 관심종목을 **덮어썼다.**
                    #   사이드바에서 하나씩 담고 빼게 된 이상, 덮어쓰기는
                    #   사고다(공들여 담은 목록이 스캔 한 번에 사라진다).
                    #   **합친다.** 이미 있는 것은 그대로 두고 없는 것만 더한다.
                    # ⚠️ 라운드 142 — 사용자 지적: "더하기 하면 왜 5개가 다
                    #   들어가나? 다음 거래일에 실제로 손댈 수 있는 후보만
                    #   들어가야 하는 것 아닌가."
                    #   맞다. 바로 위에서 `_scored_rows`(행동점수가 나온 것)와
                    #   `_excluded_rows`(못 낸 것)로 **갈라 놓고도** 담을 때는
                    #   `_att['rows']` 전체를 썼다. 제외된 종목까지 들어갔다.
                    #   → **점수가 나온 것만** 담는다. 그리고 몇 개를 왜
                    #     안 담았는지 화면에 적는다 (§3 — 조용히 거르지 않는다).
                    if st.button(f"점수 나온 {len(_scored_rows)}종목을 "
                                 f"관심종목에 더하기",
                                 width='stretch', key="btn_save_watchlist",
                                 disabled=not _scored_rows):
                        _before = len(_wl_items())
                        for _r in _scored_rows:
                            _wl_add(_r['code'], _r['name'])
                        _added = len(_wl_items()) - _before
                        _msg = (f"{_added}종목 추가 (이미 있던 "
                                f"{len(_scored_rows) - _added}종목은 그대로) — "
                                f"지금 관심종목 {len(_wl_items())}개.")
                        if _excluded_rows:
                            _msg += (f" 행동점수를 못 낸 "
                                     f"{len(_excluded_rows)}종목은 "
                                     f"**담지 않았습니다** — "
                                     + ", ".join(str(r.get('name'))
                                                 for r in _excluded_rows[:4])
                                     + ".")
                        if not ALLOW_LOCAL_STORE:
                            _msg += ' (이 브라우저 세션에만 유지)'
                        st.success(_msg)
                with _wl_c2:
                    _wl_now = st.session_state.get('watchlist') or []
                    if _wl_now:
                        st.caption("현재 관심종목 " + str(len(_wl_now)) + "개: "
                                   + ", ".join(w['name'] for w in _wl_now[:8])
                                   + (" 외" if len(_wl_now) > 8 else ""))

                _att_rows = []
                for _r in _scored_rows:
                    _a = _r['attention']
                    _c = _r['components']
                    _act = _action_by_code.get(_r['code'])
                    _bucket = market_attention.classify_bucket(_a, _act)
                    _bcol = {'실전 추천 후보': '#35C98B',
                             '관심 급증·추격주의': '#F2B84B',
                             '조용한 선행 후보': '#4C8DFF',
                             '관찰 후보': '#7C8AA0',
                             '추천 제외': '#ff453a'}.get(_bucket, '#7C8AA0')
                    # HTML 안에서 조건식을 조립하면 읽을 수 없어진다 — 먼저 문자열로 만든다
                    _raw_txt = f"원점수 {_a['market_attention_score']:.0f}"
                    if _a['penalty']:
                        _raw_txt += f" · 감점 −{_a['penalty']:.0f}"
                    _pen_html = ""
                    if _a['penalty_reasons']:
                        _pen_html = ("<br><span style='color:#F2B84B;font-size:12px;'>"
                                     + " · ".join(_a['penalty_reasons']) + "</span>")
                    _ratio_txt = ""
                    if _c.get('turnover_ratio'):
                        _ratio_txt = (f" · 거래대금 {_c['turnover_ratio']:.1f}배"
                                      f"({_c.get('turnover_basis', '')})")

                    # 추천 카드와 같은 킷으로 그린다 — 예전에는 이 목록만
                    # 옛 인라인 HTML(이모지 뱃지·왼쪽 색 테두리)이라 한 화면에
                    # 두 가지 디자인이 보였다.
                    _BK = {'실전 추천 후보': ('실전 추천 후보', 'pos'),
                           '관심 급증·추격주의': ('관심 급증 · 추격 주의', 'warn'),
                           '조용한 선행 후보': ('조용한 선행 후보', 'info'),
                           '관찰 후보': ('관찰 후보', 'mute'),
                           '추천 제외': ('추천 제외', 'neg')}
                    _bk_ko, _bk_kind = _BK.get(_bucket, (str(_bucket), 'mute'))
                    _att_rows.append((_r, _a, _bk_ko, _bk_kind, _raw_txt,
                                      _ratio_txt, _act))

                # ── 추천 카드와 **같은 카드**로 그린다 (라운드 39) ──────
                # 사용자 요청: "오늘의 관심후보도 이 스타일로."
                # 스캔 스냅샷에 가격·조건이 이미 다 있으므로, 개장 전 추천과
                # 똑같이 _build_reco_card → _uk.reco_card 로 그린다.
                # 한 화면에 두 가지 카드가 보이면 어느 쪽을 믿을지 모른다.
                _by_sym = {str(r.get('symbol', '')).split('.')[0]: r
                           for r in (scan_results or [])}
                _ATT_PER_ROW = 3
                # ── 실행 가능 / 대기 로 가른다 (라운드 47) ──────────────────
                # 사용자 지적: *"내일 사야되는 종목만 띄워줘. 오늘 매수 후보가
                # 아니면 보여주지마."* 맞다. 조건을 제시할 수 없는 종목이
                # 목록 맨 위에 있으면 사용자는 그걸 추천으로 읽는다.
                #
                # 가르는 자는 verdict_core.actionable 하나다 —
                # MAX_ENTRY_SIGMA(2.1σ · 20봉 체결률 60% 실측) 안이고,
                # 실행 3값이 다 있고, 정합이 깨지지 않은 것.
                _built = []
                for _row in _att_rows:
                    _r0 = _row[0]
                    _sr0 = _by_sym.get(_r0['code'])
                    _pk = None
                    if _sr0:
                        # 배너와 **같은 메모**를 읽는다 (§4 · 라운드 214) — 한 코드에
                        # 판정 한 번. 실패는 메모가 None 으로 기억한다.
                        _pk = _pick_of(_r0['code'], _sr0)
                    if _pk:
                        _pk['reco_class'] = _row[2]
                    _built.append((_row, _pk))
                # ⚠️ 모듈 수준 `import verdict_core as _vcore` 는 이 함수보다
                #    **아래**(4560행)에 있다. 이 함수가 먼저 불리면 NameError 다.
                #    2970행과 같은 지역 임포트로 순서 의존을 없앤다.
                import verdict_core as _vcore
                # 조건을 제시할 수 있는 칸만 대기 목록에 남긴다.
                # '권장가 괴리 과다'는 현실적인 눌림목·돌파 조건을 낼 수 없다는
                # 뜻이므로 대기 목록에도 두지 않는다 — 사용자 지적 그대로다.
                # ⚠️ 라운드 214 — 가르는 함수는 배너와 **같은** `_sig_class` 다.
                #   대기 튜플도 그 함수 안의 `_WAIT_OK_214` 하나뿐이다 (§4).
                _live, _wait, _dropped = [], [], []
                for _x in _built:
                    _cr = (_x[1] or {}).get('core') or {}
                    _bk = str(_cr.get('bucket') or '')
                    _cls = _sig_class(_cr)
                    if _cls == 'live':
                        _live.append(_x)
                    elif _cls == 'wait':
                        _wait.append(_x)
                    else:
                        _dropped.append((_x, _bk or '판정 불가',
                                         str(_cr.get('exclude_reason') or '')))
                # 아래 요약 칸이 **이 분류를 그대로** 쓴다 (§4). 목록과 숫자가
                # 같은 곳에서 나오므로 둘이 어긋날 수 없다.
                _bucket_counts = {'실행 가능': len(_live),
                                  '조건 대기': len(_wait),
                                  '추천·대기에서 뺌': len(_dropped)}

                def _render_att(items, key_prefix):
                    _cols = []
                    for _s in range(0, len(items) or 1, _ATT_PER_ROW):
                        _n2 = min(_ATT_PER_ROW, max(1, len(items) - _s))
                        _cols.extend(st.columns(_ATT_PER_ROW)[:_n2])
                    for _i, (_row, _pick) in enumerate(items):
                        (_r, _a, _bk_ko, _bk_kind, _raw_txt, _ratio_txt,
                         _act) = _row
                        with _cols[_i]:
                            if _pick:
                                _att_news = []
                                if _pick.get('news_fresh'):
                                    _att_news.append(
                                        f"신선 재료 {_pick['news_fresh']}건")
                                if _pick.get('news_lagging'):
                                    _att_news.append(
                                        f"후행 보도 {_pick['news_lagging']}건 제외")
                                _cb_a = _pick.get('confidence_band') or {}
                                _conf_a = (
                                    f"과거 동점수대 리플레이 적중 {_cb_a['hit_rate']:.0f}% "
                                    f"(n={_cb_a['n']})"
                                    if _cb_a.get('hit_rate') is not None
                                    and (_cb_a.get('n') or 0) >= 30
                                    else f"관심점수 "
                                         f"{_a['adjusted_attention_score']:.0f} "
                                         f"· {_raw_txt}")
                                st.markdown(
                                    _uk.reco_card(
                                        _build_reco_card(_pick, _att_news,
                                                         _conf_a),
                                        theme=_theme),
                                    unsafe_allow_html=True)
                            else:
                                # 정밀분석 스냅샷이 없으면 가격을 지어내지 않는다
                                st.markdown(_uk.attention_row({
                                    'name': _r['name'], 'code': _r['code'],
                                    'bucket': _bk_ko, 'bucket_kind': _bk_kind,
                                    'attention':
                                        f"{_a['adjusted_attention_score']:.0f}",
                                    'raw': _raw_txt,
                                    'action': fmt_num(_act, ',.0f'),
                                    'reason': (f"{_r.get('selection_reason', '')}"
                                               f"{_ratio_txt}").strip(' ·'),
                                    'warns': list(_a.get('penalty_reasons') or []),
                                }, theme=_theme), unsafe_allow_html=True)
                            if st.button("분석 보기",
                                         key=f"att_{key_prefix}_{_r['code']}",
                                         width='stretch', type='primary'):
                                st.session_state['pending_search'] = (
                                    f"{_r['name']} ({_r['code']})")
                                st.rerun()

                if _live:
                    st.markdown("###### 다음 거래일에 실제로 손댈 수 있는 후보")
                    st.caption(
                        f"매수가가 현재가에서 {_vcore.MAX_ENTRY_SIGMA}σ 안이고, "
                        f"목표·손절이 같은 진입가 기준으로 산출되며, 가격 정합이 "
                        f"깨지지 않은 종목만 여기 올립니다. "
                        f"({_vcore.SIGMA_BASIS})")
                    _render_att(_live, 'live')
                else:
                    st.info(_vcore.NO_PICK_LINE)

                if _wait:
                    # 조건을 제시할 수 있는 것만 대기 목록에 남긴다.
                    # '언제 다시 봐야 하는지' 없는 종목은 화면에 둘 이유가 없다.
                    with st.expander(
                            f"조건 충족을 기다리는 후보 {len(_wait)}종목 — "
                            f"무엇을 기다리는지 보기"):
                        st.caption(
                            "지금 사는 자리가 아닙니다. 각 카드의 '다음 조건'이 "
                            "충족되면 그때 검토하세요. 현재가와 매수가가 너무 "
                            "벌어져 현실적인 조건을 제시할 수 없는 종목은 "
                            "여기에도 두지 않습니다.")
                        _render_att(_wait, 'wait')

                if _dropped:
                    # 뺀 것도 **왜 뺐는지**는 남긴다. 조용히 사라지면
                    # 사용자는 엔진이 못 본 줄 안다.
                    with st.expander(
                            f"추천·대기에서 뺀 {len(_dropped)}종목 — 사유 보기"):
                        for (_x, _bk, _rz) in _dropped:
                            _rr0 = _x[0][0]
                            st.markdown(
                                f"**{_rr0['name']}** `{_rr0['code']}` · "
                                f"{_bk}"
                                + (f"  \n{_rz}" if _rz else ""))

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
                # ── 데이터 미수신과 판정 결과를 구분한다 (라운드 37) ──────
                # 후보를 하나도 못 받은 것은 **엔진의 판정이 아니라 수집 실패**다.
                # 둘을 같은 문장으로 말하면 "오늘은 살 게 없다"로 읽힌다.
                _scanned = int((st.session_state.get('scan_lite') or {})
                               .get('passed') or 0)
                _pool = int(st.session_state.get('scan_universe_total') or 0)
                if _scanned == 0 or _pool == 0:
                    st.error(
                        "**판정 불가 — 후보 데이터를 받지 못했습니다.** "
                        + ("전 종목 경량 스캔이 0개를 반환했습니다. "
                           if _scanned == 0 else "")
                        + ("순위 페이지에서 후보 풀을 만들지 못했습니다. "
                           if _pool == 0 else "")
                        + "이것은 '오늘 살 종목이 없다'는 **판정이 아니라 "
                          "수집 실패**입니다. 장 시작 전이거나 데이터 출처가 "
                          "일시적으로 응답하지 않을 때 발생합니다 — "
                          "잠시 후 다시 스캔해 주세요.")
                else:
                    st.warning(
                        "**현재 추천주 없음** — 정밀분석한 "
                        f"{len(scan_results)}개 중 필수조건을 모두 통과한 종목이 "
                        "없습니다. 무리한 신규 매수보다 현금 유지가 우선입니다.")
                if block_counter:
                    top_blocks = block_counter.most_common(5)
                    st.markdown(
                        "**가장 많이 걸린 차단 조건**\n\n"
                        + "\n".join(f"- {name} — {cnt}개 종목" for name, cnt in top_blocks)
                    )
            else:
                st.success(f"필수조건을 모두 통과한 종목: **{len(recommended)}개** (최대 3개 표출)")
                # ⚠️ 라운드 187 — 이 목록을 '최적'·'순위'로 부르지 않는다.
                #   라운드 110 실측(원장 166,132건 · 기준일 2,609일): 같은 날
                #   점수 상위5와 6위 이하의 적중률 차이 **중앙값 0.0%p**,
                #   부호검정 z −1.39 로 유의하지 않다. 순위에 정보가 있다는
                #   근거가 없는데 화면이 순위를 팔면 §9 위반이다.
                st.caption(
                    f"정밀분석한 {len(scan_results)}개 중에서 고른 것이며, "
                    f"**나열 순서는 우열이 아닙니다** — 같은 날 점수 상위와 "
                    f"하위의 성적 차이가 원장 실측에서 확인되지 않았습니다 "
                    f"(라운드 110 · 차이 중앙값 0.0%p). 정밀분석하지 않은 "
                    f"종목에 더 나은 후보가 있을 수 있습니다.")

                # --- Interactive Screener Table ---
                st.markdown("통과 종목 (이름을 누르면 분석으로 갑니다)")

                # Header (전략유형 및 월봉 10선 장기추세 컬럼 탑재)
                cols = st.columns([0.5, 1.8, 1.4, 1.1, 1.2, 1.2, 1.4, 1.2, 1.0, 1.2])
                # '순위' → '번호' (라운드 187) — 위 캡션과 같은 이유다.
                # ⚠️ 라운드 191 — '손익비' 라는 **같은 낱말이 두 값**을
                #   가리키고 있었다. 이 표는 `reward_risk_ratio`(2차 목표 ·
                #   현재가 기준 · 게이트 1.3)이고, 카드·배너는
                #   `entry_rr`(1차 목표 · 진입가 기준 · 게이트 0.5)다.
                #   같은 화면에 둘이 나란히 있었고 값도 게이트도 달랐다.
                #   기준을 이름에 넣는다 — 값·게이트는 안 바꿨다 (§4).
                headers = ["번호", "종목명 (클릭)", "전략유형", "현재가", "적정가", "상승여력%", "월봉 10선", "최종점수", "손익비(현재가·2차)", "상태"]
                for col, header in zip(cols, headers):
                    col.markdown(f"<div style='text-align:center; color:#4C8DFF; font-size:13px; font-weight:bold; border-bottom:2px solid #222C3C; padding-bottom:8px;'>{header}</div>", unsafe_allow_html=True)
                
                # Rows
                for i, r in enumerate(top_recs):
                    cols = st.columns([0.5, 1.8, 1.4, 1.1, 1.2, 1.2, 1.4, 1.2, 1.0, 1.2])
                    
                    cols[0].markdown(f"<div style='text-align:center; padding-top:8px;'><span style='background:#4C8DFF; color:#fff; padding:3px 8px; border-radius:12px; font-weight:bold;'>{i+1}</span></div>", unsafe_allow_html=True)
                    
                    with cols[1]:
                        # 라운드 40 — 이모지(🎯)를 걷어내면서 양쪽이 빈
                        # 문자열이 되어 배지가 아무 뜻도 없어졌다. 글자로 되살린다.
                        _entry_badge = "진입후보 " if r.get('entry_candidate') else ""
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
                            
                    st_type = r.get('strategy_type', '가치·반전형')
                    curr_p_str = f"{r['base_price']:,.0f}원"

                    tgt = r.get('target_fundamental')
                    target_p_str = f"{tgt:,.0f}원" if tgt is not None else "미산출"

                    upside_val = r.get('upside_pct')
                    if upside_val is None:
                        upside_str, upside_color = "미산출", "#9DAABC"
                    else:
                        upside_str = f"{upside_val:+.1f}%"
                        upside_color = _TOK['up'] if upside_val > 0 else _TOK['down']

                    m10_stat = r.get('m10_status', '위')
                    m10_disp = r.get('m10_disparity', 0.0)
                    m10_col = _TOK['up'] if m10_stat == "위" else _TOK['down']
                    m10_str = f"{m10_stat} ({m10_disp:+.1f}%)"
                    # 차트 관점 배지: DeMARK 매수 신호가 살아 있으면 함께 표기
                    _dstate = r.get('demark_entry_state')
                    if _dstate in ('COMPLETE', 'SETUP_DONE'):
                        m10_str += " · 매수신호"
                    elif _dstate == 'FORMING':
                        m10_str += " · 셋업중"

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
                
            # ── 정밀분석 종목 분류 요약 ────────────────────────────────────
            # 위 목록을 가른 **그 분류**를 그대로 센다. 이모지 대신
            # ui_kit 의 Lucide 아이콘을 쓴다 (§5).
            if _bucket_counts is None:
                # 분류를 못 만들었으면 0 을 찍지 않는다 — 0 은 '없다'로 읽힌다
                st.caption("정밀분석 종목 분류 요약은 후보 목록을 만들지 "
                           "못해 산출하지 않았습니다 (숫자를 지어내지 "
                           "않습니다).")
            else:
                _bc_icon = {'실행 가능': 'ShieldCheck',
                            '조건 대기': 'Clock3',
                            '추천·대기에서 뺌': 'ShieldAlert'}
                # ⚠️ 여기 색을 `_TOK`(테마별 토큰)으로 썼다가 되돌렸다.
                #    이 파일 250행이 이유를 적어 뒀다 — **카드 표면은 양
                #    테마 모두 단일 다크로 고정**한다. 라이트에서 카드만
                #    희어지면 옆의 카드들과 두 종류가 되고(§5), 내부 글자색이
                #    밝게 하드코딩된 카드는 통째로 사라진다.
                #    그래서 표면은 _CARD_BG, 글자는 다크 팔레트를 쓴다.
                #    (색을 새로 만들지 않는 것과, 테마를 따라가는 것은
                #     다른 이야기다 — 여기서 지켜야 하는 것은 앞의 것이다)
                _bc_tx2, _bc_tx1 = _uk.DARK['tx2'], _uk.DARK['tx1']
                _bc_cells = "".join(
                    f"<div style='text-align:center;'>"
                    f"<span style='color:{_bc_tx2}; font-size:13px; "
                    f"display:inline-flex; align-items:center; gap:6px;'>"
                    f"{_uk._icon(_bc_icon[_k], _bc_tx2, 14)}{_k}</span>"
                    f"<br><b style='color:{_bc_tx1};'>{_v}개</b></div>"
                    for _k, _v in _bucket_counts.items())
                st.markdown(
                    f"<div style='display:flex; justify-content:space-around; "
                    f"background:{_CARD_BG}; padding:12px; "
                    f"border-radius:8px; margin-top:16px;'>{_bc_cells}</div>",
                    unsafe_allow_html=True)

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
                st.toast("오늘의 개장 전 리포트를 고정 저장했습니다")
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
               f"{_pmr.get('note')}")
    # 리포트는 사후 선택 방지를 위해 동결한다. 그런데 엔진을 바꾸면 동결된
    # 값이 낡는다 — 실제로 권장 매수가 산식을 바꿨는데 카드가 옛 값을
    # 그대로 보여 줬다. 낡았으면 화면이 먼저 말해야 한다.
    # 낡은 리포트는 '경고를 달고 계속 보여 주기'로 끝내지 않는다. 종전에는
    # "다시 스캔하세요"라고만 말했는데, 정작 리포트 키가 날짜뿐이라 다시
    # 스캔해도 같은 파일이 재사용됐다 — 실행 불가능한 안내였다.
    # 이제 리포트는 날짜×엔진으로 저장되므로, 엔진이 바뀌면 다시 스캔이
    # 실제로 새 리포트를 만든다.
    _pm_stale = bool(_pmr.get('stale_engine')) or not _pm_ver
    if _pm_stale:
        _pm_old = str(_pmr.get('stale_engine') or _pm_ver or '미상')
        st.warning(
            f"아래 리포트는 엔진 **{_pm_old}** 로 만든 것이고 현재 엔진은 "
            f"**{_VER_NOW['model']}** 입니다. 가격·점수가 지금 산식과 다릅니다."
            f"  \n**사이드바에서 스캔을 다시 실행하면 새 엔진으로 다시 만듭니다** "
            f"(리포트를 날짜별이 아니라 날짜×엔진으로 저장하도록 고쳤습니다 — "
            f"이제 다시 스캔이 실제로 갱신됩니다).")
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
    # ── 실행 가능성 게이트 (라운드 34) ──────────────────────────────────
    # 사용자 지적: *"우진처럼 현재가 14,600원인데 권장 매수가 9,388원인
    # 종목은 오늘의 추천에서 제외해 주세요."* 중앙 판정의 추천 조건(§2 의
    # 10 + R185 밸류 게이트)이 판단하고, 통과 못 한 종목은 **사유와 함께
    # 분류**해서 따로 둔다.
    import verdict_core as _vc_view
    _picks_ok = [p for p in _picks_all
                 if (p.get('core') or {}).get('recommended')]
    _picks_gated = [p for p in _picks_all
                    if (p.get('core') or {})
                    and not (p.get('core') or {}).get('recommended')]
    _picks_legacy = [p for p in _picks_all if not p.get('core')]

    # 추천 카드에는 '사면 안 되는 종목'을 올리지 않는다 — 그건 추천이 아니라 제외다
    if _picks_ok or _picks_gated:
        _picks_show = _picks_ok[:5]
    else:                                    # 옛 리포트 — 중앙 판정이 없다
        _picks_show = [p for p in _picks_legacy
                       if p['reco_class'] != '오늘은 사면 안 되는 종목'][:5]
    _picks_ban = [p for p in _picks_all
                  if p['reco_class'] == '오늘은 사면 안 되는 종목']
    # 파일은 그대로 남기고(사후 선택 방지 감사 흔적), **화면에서만 접는다.**
    if _pm_stale and _picks_show:
        st.caption("이 리포트가 추천했던 종목: "
                   + ", ".join(f"{_p.get('name')}({_p.get('code')})"
                               for _p in _picks_show)
                   + " — 가격·점수는 옛 엔진 값이라 표시하지 않습니다. "
                     "다시 스캔하면 현재 엔진으로 다시 만듭니다.")
        _picks_show = []

    if not _picks_show and not _pm_stale:
        # 억지로 종목 수를 채우지 않는다 (사용자 사양 §2).
        # 다만 **후보를 아예 못 받은 것**과 **받았는데 다 떨어진 것**은
        # 다른 사실이다 (라운드 37). 앞의 경우를 뒤로 말하면 거짓이 된다.
        if not _picks_all:
            st.error(
                "**판정 불가 — 이 리포트는 후보 종목을 받지 못한 상태로 "
                "만들어졌습니다.** 검증 조건을 통과하지 못한 것이 아니라 "
                "**수집 단계에서 후보가 0개**였습니다. 사이드바에서 스캔을 "
                "다시 실행해 주세요.")
        else:
            st.error(f"**{_vc_view.NO_PICK_LINE}**")

    # ── 통과 못 한 종목 — 사유를 8분류로 명시 (사용자 사양 §2) ────────────
    if _picks_gated and not _pm_stale:
        _by_bucket = {}
        for _g in _picks_gated:
            _c = _g.get('core') or {}
            _by_bucket.setdefault(_c.get('bucket') or '추천 제외', []).append(
                (_g, _c))
        st.markdown("###### 오늘 추천에 올리지 못한 종목과 이유")
        for _bk in _vc_view.BUCKETS:
            _items = _by_bucket.get(_bk)
            if not _items:
                continue
            with st.expander(f"{_bk} ({len(_items)}종목)", expanded=False):
                for _g, _c in _items:
                    _gp = _c.get('gap_pct')
                    st.markdown(
                        f"**{_g.get('name')}** ({_g.get('code')}) — "
                        + (f"현재가 {_c['current_price']:,.0f}원"
                           if _c.get('current_price') else '현재가 미산출')
                        + (f" · 진입가 {_c['pullback_zone']:,.0f}원"
                           f"({_gp:+.1f}%)" if _c.get('pullback_zone')
                           and _gp is not None else '')
                        + f"  \n{_c.get('exclude_reason') or ''}")
                    _fail = [c for c in (_c.get('checks') or []) if not c['ok']]
                    if _fail:
                        st.caption("미충족: " + " · ".join(
                            f"{c['name']}({c['detail']})" for c in _fail[:4]))
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
        _conf_txt = (f"과거 동점수대 리플레이 적중 {_cb_p['hit_rate']:.0f}% (n={_cb_p['n']})"
                     if _cb_p.get('hit_rate') is not None and (_cb_p.get('n') or 0) >= 30
                     else "적중률 표본 부족")
        _news_txt = []
        if _p.get('news_fresh'):
            _news_txt.append(f"신선 재료 {_p['news_fresh']}건")
        if _p.get('news_risk'):
            _news_txt.append(f"위험 낱말 {_p['news_risk']}건")
        if _p.get('news_lagging'):
            _news_txt.append(f"후행 보도 {_p['news_lagging']}건 제외")
        # 갭 표기 (라운드 2.5) — 조건부 매수가와 현재 기준가의 거리. 갭이 크면
        # 실측상 '추격 위험' 구간 성과가 최악(54.6%·비용후 -0.98%)임을 경고한다.
        #
        # ⚠️ 라운드 192 — 여기가 **괴리를 재는 넷째 자리**였고, 게다가
        #   부호가 반대였다. 나머지 셋은 전부 `(권장/현재 − 1)` 이다:
        #     verdict_core.gap_pct · next_action.gap_pct · price_axes.gap_pct
        #   이 줄만 `(현재/권장 − 1)` 로 **역수**를 쟀다. 같은 행에
        #   `core['gap_pct']` 가 이미 실려 있는데도 직접 다시 계산했다 —
        #   §4 가 금지한 그것이다(경로가 둘이면 한쪽만 고치는 일이 생긴다).
        #   이제 단일 출처에서 읽고, 화면이 쓰는 '현재가가 권장보다 얼마나
        #   위인가'는 그 값에서 **대수로** 유도한다. 분모(현재가)는
        #   같은 값이고(_core_of 가 realtime_price=base_price 로 부른다),
        #   분자는 엔진이 **실제로 쓰는 진입가**다. 눌림가와 진입 축이
        #   같은 종목은 숫자가 그대로고, 다른 종목은 카드가 이제 엔진과
        #   같은 가격을 기준으로 말한다 — §4 가 요구하는 것이 그것이다.
        #   문턱 7% 는 그대로 뒀다 — 채택된 구간 규칙
        #   (next_action.BANDS 5/10/15 를 ATR 로 조정)으로 바꾸면 카드의
        #   경고 문구가 실제로 바뀐다. 그건 사전등록 감이다 (§2).
        _gap_html = ""
        _core_gap = ((_p.get('core') or {}).get('gap_pct')
                     if isinstance(_p.get('core'), dict) else None)
        if (_core_gap is not None and _p.get('rec_buy') and _p.get('price')
                and '이하로 내려올 때만' in str(_p.get('easy_line'))):
            # gap = (권장/현재 − 1)×100 (음수 = 권장가가 아래).
            # 화면이 말하는 '현재가가 권장보다 얼마나 위' = 그 역수.
            _denom = 100.0 + float(_core_gap)
            _gap_pct = ((100.0 / _denom - 1.0) * 100.0 if _denom > 0 else None)
            # 라운드 206 — 경고 문턱 **7% 를 걷어냈다.** 그 7 은 손으로 고른
            #   수였고(§2), 닫힌 식으로 재니 채택 밴드의 e1(10×scale)이
            #   [7.0, 25.0] 이라 **7% 는 항상 '눌림목 대기'(매수 적격) 안**
            #   이다 — 카드가 관망을 말하는 자리에서 엔진은 늘 적격이었다.
            #   실측(25종목 · 2026-09-02): 발화 1건, 그 1건이 실제 모순.
            #   이제 엔진의 채택 밴드(gap_band)가 유일 잣대다 — '장기 관찰'
            #   이상일 때만 경고한다. 근거: docs/PREREG_R206_CARD_GAP_BAND.md
            _core_band = ((_p.get('core') or {}).get('gap_band')
                          if isinstance(_p.get('core'), dict) else None)
            if _gap_pct is not None and _gap_pct > 0:
                _band_far = _core_band in ('장기 관찰', '괴리 과다')
                _gap_warn = ((f" — 매수구간과 괴리가 큽니다 [{_core_band}]. "
                              f"단기 도달 가능성이 낮습니다.")
                             if _band_far else "")
                _gap_html = (f"<p style='margin:0 0 8px 0; font-size:12px; "
                             f"color:{'#F2B84B' if _band_far else _TOK['tx2']};'>"
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
                # ⚠️ 라운드 135 — 여기가 관심종목을 담는 **세 번째 경로**였고,
                #   혼자만 `normalize_code` 를 안 거쳤다. 같은 종목이
                #   '005930' 과 '005930.KS' 로 두 줄이 될 수 있었고,
                #   중복 판정도 문자열 비교라 못 걸렀다.
                #   담기·빼기·저장을 `_wl_*` 한 벌로 모은다 (§4).
                _in_wl = _wl_has(_cd)
                if st.button('관심 추가됨' if _in_wl else '관심 추가',
                             key=f"pm_wl_{_sym}_{_pi}", width='stretch',
                             help=('이미 관심종목입니다' if _in_wl else
                                   '관심종목에 넣습니다 — 후보 발굴 방식에서 '
                                   "'사용자 관심종목'으로 다시 스캔할 수 있습니다"),
                             disabled=_in_wl):
                    _wl_add(_cd, _nm)
                    st.rerun()
            with _b3:
                if st.button("보유 등록", key=f"pm_pos_{_sym}_{_pi}",
                             width='stretch',
                             help='이 종목을 보유종목으로 등록합니다 — '
                                  '수량·평단가는 보유종목 화면에서 채웁니다'):
                    # 수량·평단가를 모르는 채로 지어내지 않는다. 0 으로 넣고
                    # 보유종목 화면을 열어 사용자가 채우게 한다.
                    _mkt = _market_of(_sym)
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
                _oe = {'TARGET': '', 'STOP': '', 'OPEN': ''}.get(_h['outcome'], '·')
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
            ["포트폴리오 분석", "가져오기 / 입력", " 저장·삭제"])
    else:
        p_tab_import, p_tab_view, p_tab_manage = st.tabs(
            ["가져오기 / 입력", "포트폴리오 분석", " 저장·삭제"])

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
                        return (_i or {}).get('market') or _market_of(t)
                    try:
                        # ⚠️ 라운드 189 — 바로 위에서 `_resolve_market` 을
                        #   정의해 놓고 `resolve_market=None` 을 넘기고
                        #   있었다(정의만 있고 아무도 안 부르는 함수였다).
                        #   그래서 CSV·Excel 가져오기가 **모든 종목의 시장을
                        #   미상으로** 만들고 행마다 경고를 뿌렸다. 붙여넣기
                        #   경로(:4445)는 제대로 넘기고 있어 둘이 달랐다.
                        pos, warns = portfolio.import_positions(
                            df_raw, mapping, resolve_market=_resolve_market,
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
            st.download_button("입력 양식 내려받기", data=_tpl_bytes,
                               file_name=_tpl_name, mime=_tpl_mime,
                               width='stretch', key="btn_dl_template")
            st.caption("종목코드·종목명·보유수량·평균매수가 네 칸만 채우면 됩니다.")
        with _xc2:
            _cur_pos = st.session_state.get('positions') or []
            _exp_df = portfolio.positions_to_dataframe(_cur_pos)
            st.download_button(
                f"지금 보유종목 내보내기 ({len(_cur_pos)}종목)",
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
            with st.expander("열을 직접 지정하기" + (" 자동 인식 실패" if _needs_manual else ""),
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
                _sc = _TOK['up'] if _s_pnl >= 0 else _TOK['down']
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
                _cc = {'ok': '', 'warn': '', 'error': ''}[_ck['level']]
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
            if pc1.button(f"검증 통과 {len(_savable)}행 반영",
                          disabled=not _savable):
                # 사용자가 직접 넣은 종목코드는 시장(KOSPI/KOSDAQ)을 모른다.
                # KOSPI 로 넘겨짚으면 코스닥 종목의 시세 조회가 통째로 실패한다.
                # 라운드 159 — 해석 실패 시에도 KOSPI 로 찍지 않는다.
                #   None 을 돌려주면 portfolio 가 '시장 미지정'으로 넣고 경고를 남긴다.
                def _resolve_mkt(code):
                    try:
                        t, _n = engine_init.resolve_symbol(code)
                        return _market_of(t)
                    except Exception:
                        return None
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
            if pc2.button(" 미리보기 취소"):
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
            if mg1.button("로컬 저장"):
                path = portfolio.save_positions(st.session_state['positions'])
                st.session_state['positions_saved_at'] = datetime.datetime.now().isoformat(timespec="seconds")
                st.success(f"저장 완료: {path}")
            if mg2.button("저장본 불러오기"):
                loaded, saved_at = portfolio.load_positions()
                st.session_state['positions'] = loaded
                st.session_state['positions_saved_at'] = saved_at
                st.success(f"{len(loaded)}종목 불러옴 (저장 시각 {saved_at})")
            if mg3.button("전체 삭제", type="secondary"):
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
            st.download_button("CSV 내보내기",
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
                            st.markdown(f"- {'' if ok else ''} {label}")
                        if not pv['averaging_down_allowed']:
                            st.warning("추가매수 조건을 충족하지 못했습니다. 손실 중이라는 이유만으로 "
                                       "기계적 물타기를 권하지 않습니다.")

                        if m.get('is_multi_account'):
                            st.caption("복수 계좌 보유 — 계좌별 내역")
                            st.dataframe(pd.DataFrame(m['accounts']),
                                         width='stretch', hide_index=True)
    _uk.spacer(28)


# ═══════════════════════════════════════════════════════════════════════════
# 관심종목 화면 (라운드 136)
#
# 사용자 물음: *"관심목록 리스트 어디서 봐?"*
#   라운드 135 에서 사이드바 **접힌 칸**에만 뒀다. 담기는 되는데 어디에
#   쌓이는지 안 보였다. 라운드 105 에서 같은 일이 있었다 — 화면에는
#   있었는데 앵커가 없어 못 찾았다. 그러니 **본문 절 + 메뉴 항목**으로 낸다.
#
# ⚠️ 목표 매수가·매입가는 **개인 메모 전용**이다. 점수·적정가·판정에
#   들어가지 않는다 (§9 — 평균 매수가는 보유 판단에만. 앵커링 방지).
#   보유 중이면 '내 보유종목'에 등록해야 포트폴리오 판단에 들어간다.
# ═══════════════════════════════════════════════════════════════════════════
def _wl_avg_down_snap(row, snapshot):
    """관심종목 한 줄의 **물타기 판정**을 스냅샷에 찍는다 (라운드 214 · 사용자 요청).

    *"관심종목 엔진판단에 가지고 있는 주식 물탈지 말지도 고민해주고."*
    새 문턱을 만들지 않는다 — `personalize_for_position` 이 **이미 채택한
    6조건**(신규 진입 통과 · 비용후 기대수익 양수 · 손익비(현재가·2차) ·
    중기 추세 · 비중 상한 · 표본 게이트)을 그대로 부른다 (§2-6). 정식 보유 화면과
    **같은 함수·같은 비중 정의**(매입원가 기준 · :4709)다 (§4).
    매입가·수량이 없으면 빈 dict — 지어내지 않는다 (§3).
    """
    try:
        paid = float(row.get('paid') or 0)
        qty = float(row.get('qty') or 0)
    except (TypeError, ValueError):
        return {}
    if paid <= 0 or qty <= 0 or not snapshot:
        return {}        # 안 산 종목 — 판정 대상이 아니다 (실패가 아니라 정상)
    tot = 0.0
    for w in _wl_items():
        try:
            tot += float(w.get('paid') or 0) * float(w.get('qty') or 0)
        except (TypeError, ValueError):
            pass
    wpct = (paid * qty / tot * 100.0) if tot > 0 else None
    try:
        pv = q_engine.personalize_for_position(snapshot, paid, qty,
                                               portfolio_weight_pct=wpct)
    except Exception:                                          # noqa: BLE001
        # 못 낸 것은 빈 dict 로 두되(§3 — 지어내지 않는다) **왜 못 냈는지는
        # 서버 로그에 남긴다.** 조용히 {} 만 돌려주면 물타기 칸이 영영 비어도
        # 아무도 모른다.
        import sys as _sys214
        import traceback as _tb214
        print('[관심종목 물타기 판정 실패 — 칸을 비운다]\n'
              + _tb214.format_exc(), file=_sys214.stderr)
        return {}
    _fails = [lbl for lbl, ok in (pv.get('averaging_down_checks') or []) if not ok]
    return {
        # ⚠️ 파일은 **글자 스키마**(portfolio.WATCH_SNAP_TXT)로만 남긴다 — bool·list
        #   는 저장에서 떨어진다(실측: 세션엔 있고 파일엔 없었다). 세션과 파일이
        #   같은 모양이 되도록 처음부터 글자로 찍는다 (§4). '불가'를 0 으로 두면
        #   숫자 칸이 0 을 버려 사라지므로 글자다.
        'snap_avg_down_ok': ('가능' if pv.get('averaging_down_allowed') else '불가'),
        'snap_avg_down_fail': ' · '.join(_fails),
        'snap_holder_key': pv.get('holder_action_key'),
        'snap_holder_title': pv.get('holder_action_title'),
        'snap_weight_basis': ('관심종목 보유분 매입원가 기준'
                              if wpct is not None else '비중 미확인'),
    }


#: 한 번의 그리기 안에서만 산다 — 스크립트가 다시 돌면 비워진다 (낡지 않는다)
_RG214_CACHE = {}


# ── 라운드 217 — 원장의 '겹침 없는' 케이스 수 (25봉 간격 부분집합) ────────────
#   규칙은 `ledger_view` 한 곳. 250,725행 셈이 pandas 루프로 3.5초였다(리스트
#   루프로 0.2초) — 그래도 **여기서 한 번** 세고 캐시한다. 모델 성적 캡션과
#   원장 캡션이 같은 헬퍼를 부른다(§4).
#   캐시 키는 행수·마지막 기준일 — 원장이 자라면 다시 센다.
import ledger_view as _lv217


@st.cache_data(show_spinner=False)
def _spaced_count_cached(_df, n_rows, last_date):
    return _lv217.spaced_count(_df)


def _market_state_214():
    """KOSPI 국면을 **한 그리기에 한 번만** 계산한다 (라운드 214).

    관심종목의 '내 포트폴리오 견해'(앞)와 종목 상세의 국면 칸(뒤 :7176)이
    **같은 함수·같은 값**을 읽는다 (§4). `get_index_regime` 은 지수를 받아
    오므로 두 번 부르면 두 번 받는다. 못 재면 None (§3).
    """
    if 'v' in _RG214_CACHE:
        return _RG214_CACHE['v']
    _ms = None
    try:
        _ir = engine_init.get_index_regime('KOSPI')
        if _ir.get('available'):
            import trade_plan as _tp214
            _ms = _tp214.market_state(_ir['price'], _ir['sma20'],
                                      _ir['sma60'], _ir.get('sma60_prev'))
    except Exception:                                          # noqa: BLE001
        _ms = None
    _RG214_CACHE['v'] = _ms
    return _ms


st.markdown('<div id="nav-watchlist"></div>', unsafe_allow_html=True)
_uk.spacer(28)
st.header("관심종목")

# 지금 보는 종목을 여기서도 담을 수 있게 한다 (라운드 142).
# 사이드바에만 두면 검색 직후에 안 보인다 — 라운드 136 의 "어디서 봐?"
# 와 같은 모양이다.
_wl_cur = portfolio.normalize_code(target_ticker)
_wl_h1, _wl_h2 = st.columns([1.3, 2.7])
with _wl_h1:
    if not _wl_cur:
        st.caption(f"{resolved_name} 은(는) 6자리 종목코드가 아니라 "
                   f"담을 수 없습니다.")
    elif _wl_has(_wl_cur):
        st.caption(f"지금 보는 **{resolved_name}** 은(는) 이미 담겨 "
                   f"있습니다.")
    elif st.button(f"지금 보는 종목 담기 · {resolved_name}",
                   width='stretch', key='wlb_add_cur'):
        _wl_add(_wl_cur, resolved_name)
        st.rerun()

with _wl_h2:
    # ── 한 번에 여러 개 담기 (라운드 143) ────────────────────────────
    # 사용자 요청: *"검색해서 여러 개 등록할 수 있게. 검색하는데 너무
    # 오래 걸리니까 한 번에 등록하는 것."*
    #
    # 종목을 하나 고를 때마다 전체 파이프라인이 돌아 몇 분씩 걸린다.
    # 여기서는 **분석을 돌리지 않고 이름만 골라 담는다** — 값은 나중에
    # 개장 전 리포트나 상세 화면이 채운다 (라운드 141·142 의 그 경로).
    # ⚠️ `_pm_today` 는 이 절보다 **뒤에서** 정의된다 — 참조하면
    #   NameError 다. 이 저장소가 라운드 139 에서 같은 순서 오류를
    #   겪었다(`_read148` 을 정의 전에 씀). 여기서는 세션에 이미 있는
    #   스캔 결과만 쓴다.
    _pool143 = {}
    for _r143 in (st.session_state.get('scan_results') or []):
        _c143 = portfolio.normalize_code(
            _r143.get('code') or _r143.get('symbol'))
        if _c143 and not _wl_has(_c143):
            _pool143[_c143] = str(_r143.get('name') or _c143)
    if _pool143:
        _sel143 = st.multiselect(
            "여러 개 한 번에 담기 (스캔에 나온 종목)",
            options=sorted(_pool143, key=lambda c: _pool143[c]),
            format_func=lambda c: f"{_pool143[c]} · {c}",
            key='wl_bulk_pick',
            help='분석을 돌리지 않고 이름만 담습니다 — 값은 나중에 '
                 '개장 전 리포트나 분석 화면이 채웁니다.')
        if _sel143 and st.button(f"{len(_sel143)}종목 한 번에 담기",
                                 key='wl_bulk_add'):
            for _c143 in _sel143:
                _wl_add(_c143, _pool143[_c143])
            st.rerun()
    else:
        st.caption("한 번에 담을 후보가 없습니다 — 스캔을 돌리거나 "
                   "종목을 검색해 하나씩 담을 수 있습니다.")

_wl_body = _wl_items()
if not _wl_body:
    st.caption("아직 담은 종목이 없습니다. 사이드바 '관심종목' 칸이나 "
               "추천 카드의 '관심 추가'로 담을 수 있습니다.")
else:
    # ⚠️ 라운드 141 — 엔진 값과 사용자 입력을 **눈에 보이게 가른다.**
    #   목표 매수가·1차·2차·적정가는 엔진이 낸 값이고, 매입가·수량·메모는
    #   사용자가 적는 값이다. 섞어 놓으면 어느 쪽이 근거인지 못 읽는다.
    st.caption(
        f"{len(_wl_body)}종목 · **목표 매수가·1차·2차·적정가는 엔진 값**"
        f"이고, 그 종목을 마지막으로 **본 날** 찍힌 것입니다 — 오늘 값이 "
        f"아닐 수 있어 날짜를 함께 적습니다. **매입가·수량은 직접 "
        f"적는 값**이고 점수·적정가·판정에 쓰지 않습니다 — 다만 "
        f"**매입가를 적으면 그 종목의 '엔진 판단'이 보유자 기준으로 "
        f"바뀝니다**(더 살까·들고 갈까·정리할까). 보유 중이라면 "
        f"[내 보유종목](#nav-holdings)에 등록해야 포트폴리오 판단에 "
        f"들어갑니다.")
    # ⚠️ 1차는 **권장가 기준**, 2차는 **현재가 기준**이다. 기준이 다르므로
    #   열 이름에 적는다 — 섞으면 §4 가 금지한 그 버그가 된다.
    # ── 쉬운 표현 (라운드 143) ────────────────────────────────────
    # 사용자 물음: *"판단 점수 진짜 맞는 거야?"*
    # 숨기지 않는다. 화면이 이미 연습 71.5% · 실전 51.3% 를 적고 있고,
    # 51.3% 는 동전 던지기다. 그 사실을 표 옆에 한 문장으로 둔다.
    st.info(
        "**이 표가 말할 수 있는 것과 없는 것** — 아래 값들은 "
        "*'이 자리에서 사면 손절과 목표 중 어디에 먼저 닿았나'* 를 과거로 "
        "되돌려 센 결과입니다. **어느 종목이 더 낫다는 뜻이 아닙니다** — "
        "같은 날 점수 상위와 하위를 짝지어 비교했더니 차이가 없었습니다"
        "(라운드 49·110·111·112). 그래서 이 표는 **순위표가 아니라 "
        "가격 기준표**입니다.")

    # ⚠️ 라운드 169 — '내 계획' 칸을 걷어냈다. 사용자 요청:
    #   *"내 계획은 지워버리고, 엔진 판단부터 제대로 되도록 해줘."*
    #   판단은 `_uk.watch_action()` **한 곳**에서만 나온다 (§4) — 화면이
    #   자기 판정을 짓지 않고, 엔진이 발표한 가격선을 다시 말할 뿐이다.

    # ⚠️ 라운드 171 — 사용자 요청: *"현재 구매한 거랑 몇 프로 밑인지 위인지도
    #   항목 넣어주고, 총 매입수량도 넣어주고."*
    #   손익률·평가금액은 **산수**다 (현재가·매입가·수량만 쓴다). 점수·
    #   적정가·판정에 들어가지 않는다 (§9 — 평단가는 보유 판단에만).
    #
    # ⚠️ 칸을 **더하기만 하면 표가 죽는다.** 손익 두 칸을 그냥 붙였더니
    #   13칸이 되어 폭 996px 을 나눠 쓰다가 매입가 입력이 `4760.(` 로
    #   잘렸고 '빼기' 버튼이 두 줄로 접혔다 (브라우저 실측 —
    #   매입가 칸 56px · 수량 35px · 빼기 27px). 회귀는 초록불이었다.
    #   그래서 **셋을 묶어 10칸으로 줄였다** — 같이 봐야 뜻이 서는 것끼리:
    #     · 적정가 + 신뢰도 (라운드 143 이 "같이 다녀야 한다"고 적은 그것)
    #     · 1차 목표 + 2차 목표
    #     · 매입가 대비 % + 평가손익 + 매입금액
    #   폭은 브라우저에서 재서 맞췄다 (실측 — 표 996px · 칸 사이 16px).
    #   버튼은 좌우 여백이 **20px 씩 고정**이라 61px 칸에서도 '빼기' 가
    #   두 줄로 접혔다 (61 − 40 = 21px < 글자 30px). 81px 로 넓혀 닫았다.
    _WL_COLS = [1.35, 0.85, 0.9, 1.1, 1.0, 1.2, 1.2, 0.75, 1.15, 1.0]
    #
    # ⚠️ 두 목표의 **기준은 열 이름에 남긴다** (§4 · §184). 라운드 30 에서
    #   신규 매수자 값과 보유자 값이 섞여 손절이 진입 위로 나갔다. 칸을
    #   묶느라 기준을 제목 속성(hover)으로 옮겼다가 회귀에 걸렸고,
    #   **그 지적이 옳다** — 마우스를 올려야 보이는 것은 적은 게 아니다.
    #   묶은 열 이름에 둘 다 적는다. **글자 그대로** 적는다 — 상수로 빼면
    #   검사가 열 이름을 읽을 때 이름만 보이고 값이 안 보인다.
    _wl_hdr = st.columns(_WL_COLS)
    # 라운드 186 — '(권장가)' → '(진입가)'. 관심종목에는 추천 아닌 종목이
    # 섞이므로 열 이름의 '권장'은 절반의 행에서 거짓이다. '진입가'는 어느
    # 행에서도 참인 기준 표기다 (verdict_core.price_basis 와 같은 낱말).
    for _c, _h in zip(_wl_hdr, ('종목', '현재가', '목표 매수가',
                                '1차 목표(진입가) · 2차 목표(현재가)',
                                '적정가', '엔진 판단', '매입가', '수량',
                                '매입가 대비 · 평가손익', '')):
        _c.markdown(f"<div style='font-size:12px; color:{_TOK['tx3']}; "
                    f"padding-bottom:6px; line-height:1.35;'>"
                    f"{_uk._esc(_h)}</div>", unsafe_allow_html=True)

    def _wl_cell(v, na='—'):
        """엔진 값 한 칸. 없으면 지어내지 않고 '—' 로 둔다 (§3)."""
        try:
            return f"{float(v):,.0f}원"
        except (TypeError, ValueError):
            return na

    _wl_dirty = False
    #: 아래 '내 포트폴리오 견해'가 쓸 재료 (라운드 169) — 표를 그리면서
    #: 모은다. 판단을 **두 번 계산하지 않는다** (§4).
    _wl_acts = []

    # ── 보유 / 안 산 것으로 가른다 (라운드 177 · 사용자 요청) ────────
    # *"관심종목에 보유주식이랑 있는주식이랑 나눠주는거 어때?"*
    #
    # 두 무리는 **읽는 법이 다르다.** 보유분은 '들고 갈까·더 살까·정리할까'
    # 이고, 안 산 것은 '지금 살 자리인가'다. 라운드 169 가 판단 문구를
    # 이미 그렇게 갈라 놓았는데(`watch_action` 의 `held`) 표는 섞여 있어
    # 한 줄씩 매입가를 확인해야 어느 쪽인지 알 수 있었다.
    #
    # ⚠️ 순서만 바꾼다. **줄을 지우거나 합치지 않는다** — 저장 순서
    #   (`_wl_body` 의 색인)는 그대로 쓰고 그리는 차례만 나눈다.
    #   그래야 아래 저장 로직(`_wl_body[_wi] = _new`)이 그대로 맞는다.
    _wl_owned = [(_i, _r) for _i, _r in enumerate(_wl_body) if _r.get('paid')]
    _wl_free = [(_i, _r) for _i, _r in enumerate(_wl_body)
                if not _r.get('paid')]

    # ── 라운드 214 — 이름순 정렬 + 우선순위 줄 (사용자 요청) ────────────
    # *"보유 중은 이름순으로 정리하고 매도할 거 우선순위, 안 산 것은 마찬가지로
    #   이름순으로 정리하고 매수할 거 우선순위로."*
    # 표는 **이름순**이다(찾기 쉽게). 우선순위는 무리 머리에 **한 줄**로 낸다 —
    # 새 문턱을 만들지 않는다 (§2-6). `watch_action` 이 **이미 발표한 kind** 를
    # 급한 순서로 늘어놓을 뿐이다: 보유분은 '정리 검토'(버틸 수 없는 가격 아래)
    # 가 가장 급하고, 안 산 것은 '지금 매수 가능'(목표가 이하)이 먼저다.
    # 판단은 **한 번만** 계산해(`_wl_pre`) 표를 그릴 때 그대로 쓴다 (§4).
    _WL_SELL_RANK = ('정리 검토', '일부 정리', '보유 유지', '추가 매수 가능',
                     '보유 기준 미산출')
    _WL_BUY_RANK = ('매수 가능', '눌림목 매수 대기', '돌파 후 매수 대기',
                    '과열 해소 대기', '거래량 회복 대기', '시장 국면 회복 대기',
                    '신뢰도·표본 확보 대기', '데이터 부족', '권장가 괴리 과다',
                    '추천 제외')
    _wl_pre = {}          # 저장 색인 → (현재가, 판단) — 표가 이 값을 그대로 쓴다
    for _pi, _pr in enumerate(_wl_body):
        _pc = str(_pr.get('code'))
        # 못 받으면 None 그대로 — 0 원으로 채우지 않는다 (§3)
        _ppx = light_quote(f"{_pc}.KS") or light_quote(f"{_pc}.KQ")
        _wl_pre[_pi] = (_ppx, _uk.watch_action(_pr, _ppx))
    _wl_owned.sort(key=lambda it: str(it[1].get('name') or ''))
    _wl_free.sort(key=lambda it: str(it[1].get('name') or ''))

    def _wl_priority_line(rows, order):
        """무리 머리의 우선순위 한 줄 — kind 를 급한 순서로, 이름은 이름순."""
        _byk = {}
        for _i2, _r2 in rows:
            _a2 = _wl_pre[_i2][1]
            if not _a2:
                continue
            _k2 = _a2['kind']
            # '지금 매수 가능'(목표가 이하)은 '매수 가능' 앞에 둔다 — 같은 kind 의 label
            if _k2 == '매수 가능' and _a2.get('label') == '지금 매수 가능':
                _k2 = '지금 매수 가능'
            _byk.setdefault(_k2, []).append(str(_r2.get('name') or ''))
        _seq = (('지금 매수 가능',) + tuple(order)) if order is _WL_BUY_RANK else tuple(order)
        _parts = []
        for _k2 in _seq:
            if _k2 in _byk:
                _nm2 = sorted(_byk.pop(_k2))
                _parts.append(f"**{_k2}** {len(_nm2)}종목 ({', '.join(_nm2[:5])}"
                              + (f" 외 {len(_nm2) - 5}" if len(_nm2) > 5 else '') + ")")
        for _k2, _nm2 in _byk.items():          # 순서표에 없는 kind 도 버리지 않는다
            _parts.append(f"**{_k2}** {len(_nm2)}종목 ({', '.join(sorted(_nm2)[:5])})")
        return " · ".join(_parts) if _parts else '판단할 값이 아직 없습니다'

    _wl_groups = [('보유 중', _wl_owned,
                   '매입가를 적은 종목 — 보유자 기준 · 이름순', _WL_SELL_RANK,
                   '정리가 급한 순'),
                  ('안 산 것', _wl_free,
                   '매입가가 없는 종목 — 신규 매수 기준 · 이름순', _WL_BUY_RANK,
                   '살 자리가 가까운 순')]

    for _gname, _grows, _ghint, _gorder, _gtitle in _wl_groups:
        if not _grows:
            continue
        _uk.spacer(6)
        st.markdown(
            f"<div style='font-size:13px; font-weight:700; color:{_TOK['tx1']}; "
            f"padding:4px 0 2px 0;'>{_uk._esc(_gname)} "
            f"<span style='font-weight:400; color:{_TOK['tx3']};'>"
            f"{len(_grows)}종목 · {_uk._esc(_ghint)}</span></div>",
            unsafe_allow_html=True)
        # 우선순위 한 줄 (라운드 214) — 표는 이름순, 급한 것은 여기서 먼저 읽는다
        st.caption(f"{_gtitle}: " + _wl_priority_line(_grows, _gorder))
        for _wi, _w in _grows:
            _wc = st.columns(_WL_COLS)
            _wcode = str(_w.get('code'))
            with _wc[0]:
                if st.button(f"{_w.get('name')} · {_wcode}", width='stretch',
                             key=f"wlb_go_{_wcode}"):
                    _go_stock(_wcode, _w.get('name'))
                    st.rerun()
            with _wc[1]:
                # 못 받으면 '미수신'이라 쓴다 — 0 원으로 채우지 않는다 (§3)
                # 라운드 214 — 정렬 때 한 번 받은 값을 그대로 쓴다 (두 번 안 받는다)
                _px_w = _wl_pre[_wi][0]
                st.markdown(
                    f"<div style='padding-top:8px; font-size:13px;'>"
                    f"{(f'{_px_w:,.0f}원' if _px_w else '미수신')}</div>",
                    unsafe_allow_html=True)
            # ── 목표 매수가 — 읽기 전용 ─────────────────────────────
            with _wc[2]:
                st.markdown(
                    f"<div style='padding-top:8px; font-size:13px; "
                    f"color:{_TOK['tx2']};'>{_wl_cell(_w.get('snap_buy'))}</div>",
                    unsafe_allow_html=True)
            # ── 1차·2차 목표 한 칸 (라운드 171) ─────────────────────
            # 기준(권장가/현재가)은 **열 이름에** 있다. 여기서는 어느 쪽인지만
            # 표시하고, 제목 속성으로 한 번 더 풀어 쓴다.
            with _wc[3]:
                st.markdown(
                    f"<div style='padding-top:8px; font-size:13px; "
                    f"color:{_TOK['tx2']}; line-height:1.5;' "
                    f"title='1차는 권장 진입가 기준 · "
                    f"2차는 현재가 기준으로 잰 값입니다'>"
                    f"<span style='color:{_TOK['tx3']};'>1차 </span>"
                    f"{_wl_cell(_w.get('snap_t1'))}<br>"
                    f"<span style='color:{_TOK['tx3']};'>2차 </span>"
                    f"{_wl_cell(_w.get('snap_t2'))}</div>",
                    unsafe_allow_html=True)
            # ── 적정가 + 신뢰도 한 칸 (라운드 143 → 171) ─────────────
            # 값과 신뢰도는 같이 다녀야 한다. 적정가 4,615원만 보여 주면
            # "3배 싸다"는 인상만 남고 **그 4,615원을 믿을 수 있는지**는
            # 안 보인다. 구간은 엔진이 이미 쓰는 70/55 를 재사용한다 (§2).
            with _wc[4]:
                _fc = _w.get('snap_fair_conf')
                try:
                    _fcv = float(_fc)
                except (TypeError, ValueError):
                    _fcv = None
                # ⚠️ 라운드 166 — ETF 가 **'0 낮음'** 으로 나오고 있었다.
                #   엔진은 적정가를 **산출하지 않았고**(status UNCALCULATED)
                #   신뢰도 0.0 은 '못 쟀다'는 뜻인데, 화면이 그것을 **0점짜리
                #   낮은 신뢰도**로 읽어 적었다 — 미산출을 값으로 만든 것이라
                #   §3 위반이다. 적정가가 없으면 신뢰도도 없다.
                if _w.get('snap_fair') in (None, '') or not _fcv:
                    _fct, _fcc = '—', _TOK['tx3']
                elif _fcv >= 70:
                    _fct, _fcc = f'{_fcv:.0f} 높음', _TOK['pos']
                elif _fcv >= 55:
                    _fct, _fcc = f'{_fcv:.0f} 보통', _TOK['tx2']
                else:
                    _fct, _fcc = f'{_fcv:.0f} 낮음', _TOK['warn']
                st.markdown(
                    f"<div style='padding-top:8px; font-size:13px; "
                    f"color:{_TOK['tx2']}; line-height:1.5;'>"
                    f"{_wl_cell(_w.get('snap_fair'))}<br>"
                    f"<span style='font-size:12px; color:{_fcc};'>"
                    f"{_uk._esc(_fct)}</span></div>",
                    unsafe_allow_html=True)
            # ── 엔진 판단 (라운드 166 → 169) ─────────────────────────
            # 사용자 요청: *"엔진 판단부터 제대로 되도록 해줘. 지금 보유한
            # 상태에서는 더 매수인지 매도인지, 없으면 매수인지."*
            #
            # 판단은 `_uk.watch_action()` **한 곳**에서 나온다 (§4). 그 함수는
            # 새 문턱을 만들지 않고 엔진이 발표한 가격선(hold_stop·hold_trim·
            # 목표 매수가)과 현재가를 견주어 다시 말할 뿐이다.
            with _wc[5]:
                # 라운드 214 — 정렬 때 이미 낸 판단을 그대로 쓴다 (§4 — 두 번 안 센다)
                _act = _wl_pre[_wi][1]
                _wl_acts.append((str(_w.get('name') or _wcode), _act, _w, _px_w))
                if not _act:
                    st.markdown(
                        f"<div style='padding-top:8px; font-size:13px; "
                        f"color:{_TOK['tx3']};'>아직 안 잼</div>",
                        unsafe_allow_html=True)
                else:
                    # 물타기 한 줄 (라운드 214) — 보유분만, 찍힌 값이 있을 때만 (§3)
                    _ad_ok = _act.get('avg_down_ok') if _act['held'] else None
                    if _ad_ok is None:
                        _ad_html = ''
                    else:
                        # 라운드 221 — '불가' 한 낱말이 셋을 뭉뚱그렸다: 시장 게이트
                        #   하나에만 막힌 것 · 포지션 조건 미달 · 표본·데이터 미판정.
                        #   라벨은 킷의 avg_down_class 가 낸다(§4 · 한 곳). 미판정은
                        #   경고색이 아니라 회색 — 판단이 아니다(§3).
                        _ad_cls = _act.get('avg_down_class')
                        _ad_col = (_TOK['pos'] if _ad_ok
                                   else _TOK['tx3'] if _ad_cls == '보류'
                                   else _TOK['warn'])
                        _ad_html = (
                            f"<br><span style='font-size:12px; color:{_ad_col};' "
                            f"title='{_uk._esc_attr(_act.get('avg_down_why') or '')}'>"
                            f"{_uk._esc(_act.get('avg_down_label') or ('물타기 가능' if _ad_ok else '물타기 불가'))}"
                            f"</span>")
                    st.markdown(
                        f"<div style='padding-top:8px; font-size:13px; "
                        f"color:{_TOK[_act['tone']]};' "
                        f"title='{_uk._esc_attr(_act['why'])}'>"
                        f"{_uk._esc(_act['label'])}"
                        + (f"<br><span style='font-size:12px; "
                           f"color:{_TOK['tx3']};'>보유 기준</span>"
                           if _act['held'] else '')
                        + _ad_html
                        + "</div>", unsafe_allow_html=True)
            # ── 사용자 입력 두 칸 ────────────────────────────────────
            with _wc[6]:
                # format='%.0f' — 소수점 두 자리가 좁은 칸에서 자리를 먹어
                # 값이 잘렸다. 원 단위라 소수점이 뜻이 없다.
                _pd = st.number_input(
                    "매입가", min_value=0.0, step=100.0, format='%.0f',
                    value=float(_w.get('paid') or 0.0),
                    key=f"wl_pd_{_wcode}", label_visibility='collapsed')
            with _wc[7]:
                _qt = st.number_input(
                    "수량", min_value=0, step=1,
                    value=int(_w.get('qty') or 0),
                    key=f"wl_qt_{_wcode}", label_visibility='collapsed')
            # ── 매입가 대비 · 평가손익 (라운드 171) ─────────────────
            # ⚠️ 방금 입력된 값(`_pd`·`_qt`)으로 센다 — 저장본이 아니라.
            #   저장본으로 세면 방금 고친 값이 한 판 늦게 반영돼 화면이
            #   스스로 어긋난다 (§4).
            # ⚠️ 현재가를 못 받았으면 **비운다.** 0 으로 채우지 않는다 (§3).
            _ret_w = ((_px_w / float(_pd) - 1.0) * 100.0
                      if (_px_w and _pd and float(_pd) > 0) else None)
            _pl_w = ((_px_w - float(_pd)) * float(_qt)
                     if (_ret_w is not None and _qt) else None)
            with _wc[8]:
                if _ret_w is None:
                    # 매입가를 안 적었거나 현재가를 못 받았다 — 지어내지 않는다
                    st.markdown(
                        f"<div style='padding-top:8px; font-size:13px; "
                        f"color:{_TOK['tx3']};'>—</div>", unsafe_allow_html=True)
                else:
                    # 한국 관행 — 오르면 빨강, 내리면 파랑 (§5)
                    _rt_col = _TOK['up'] if _ret_w >= 0 else _TOK['down']
                    _pl_line = (
                        f"<br><span style='font-size:12px;'>{_pl_w:+,.0f}원</span>"
                        f"<br><span style='font-size:12px; color:{_TOK['tx3']};'>"
                        f"매입 {float(_pd) * float(_qt):,.0f}원</span>"
                        if _pl_w is not None else
                        f"<br><span style='font-size:12px; color:{_TOK['tx3']};'>"
                        f"수량 미입력</span>")
                    st.markdown(
                        f"<div style='padding-top:8px; font-size:13px; "
                        f"font-weight:600; line-height:1.5; color:{_rt_col};'>"
                        f"{_ret_w:+.1f}%{_pl_line}</div>",
                        unsafe_allow_html=True)
            with _wc[9]:
                if st.button("빼기", width='stretch', key=f"wlb_del_{_wcode}"):
                    _wl_remove(_wcode)
                    st.rerun()
            # 입력이 바뀌었으면 그때만 저장한다 (매 rerun 마다 쓰지 않는다)
            if ((_w.get('paid') or None) != (_pd or None)
                    or int(_w.get('qty') or 0) != int(_qt or 0)):
                _new = dict(_w)
                _new['paid'] = _pd or None
                _new['qty'] = _qt or None
                _wl_body[_wi] = _new
                _wl_dirty = True
    if _wl_dirty:
        _wl_write(_wl_body)
        # ⚠️ 라운드 184 — 사용자 요청: *"평단이랑 갯수 넣으면 자동적으로
        #   내 포트폴리오 견해에 반영 및 보유중으로 이동해야지."*
        #   보유/안 산 것 묶음과 포트폴리오 견해는 이 render 의 **첫머리**
        #   에서 계산되므로, 방금 입력한 값은 다음 rerun 에야 반영됐다 —
        #   한 번 더 눌러야 움직이는 화면이었다. 저장 직후 rerun 해서
        #   즉시 이동·반영되게 한다.
        #   무한 rerun 없음 — rerun 뒤에는 입력값과 저장값이 같아
        #   `_wl_dirty` 가 다시 서지 않는다.
        st.rerun()

    _old_memo = [(str(_w.get('name') or ''), str(_w.get('memo') or ''))
                 for _w in _wl_items() if str(_w.get('memo') or '').strip()]
    if _old_memo:
        st.caption("예전에 적어 둔 메모 (지우지 않고 그대로 둡니다) — "
                   + " · ".join(f"{_n}: {_m}" for _n, _m in _old_memo[:6])
                   + (f" 외 {len(_old_memo) - 6}건"
                      if len(_old_memo) > 6 else ''))

    # ── 언제 잰 값인가 · 아직 안 본 종목은 그렇게 말한다 (§3) ────────
    _stale = [w for w in _wl_items() if not w.get('snap_at')]
    _snapd = sorted({str(w.get('snap_at')) for w in _wl_items()
                     if w.get('snap_at')})
    if _snapd:
        st.caption(f"엔진 값 기준일 {_snapd[0]}"
                   + (f" ~ {_snapd[-1]}" if _snapd[-1] != _snapd[0] else '')
                   + " — 종목 이름을 눌러 분석을 열면 그날 값으로 채워집니다.")
    # ── 빈 칸을 지금 채운다 (라운드 166) ─────────────────────────────
    # 사용자 지적: *"목표 매수가·1차목표·2차목표·적정가 없는 게 있어.
    # 이거 넣어줘야지."*
    #
    # 종전에는 **그 종목을 열어야만** 채워졌다(라운드 141). 개장 전
    # 리포트에 오르지 않는 종목은 영원히 비어 있었다 — 화신·남화토건·
    # BGF리테일이 그랬다.
    #
    # ⚠️ 자동으로 돌리지 않는다. 한 종목 정밀분석이 1~3분이라 화면을
    #   열 때마다 돌면 앱이 멈춘다(라운드 141 이 그래서 안 했다).
    #   **버튼으로 사용자가 시작하고, 얼마나 걸리는지 미리 적는다.**
    # ⚠️ 라운드 169 — **보유자 기준값이 없는 종목**도 채울 대상이다.
    #   매입가를 적어 둔 종목은 hold_stop·hold_trim 이 있어야 판단이
    #   나온다. 없으면 화면이 '보유 기준 미산출'이라 적고, 이 버튼이
    #   그것을 채운다.
    def _wl_needs_fill(w):
        if not w.get('snap_at') or w.get('snap_buy') is None:
            return True
        if w.get('paid') and not (w.get('snap_hold_stop')
                                  or w.get('snap_hold_trim')):
            return True
        # 라운드 214 보완 — 물타기 스탬프가 없는 **보유** 행도 채울 대상이다.
        #   이 기준이 그 키를 몰라, R214 이전에 저장된 보유 16행은 종목을 하나씩
        #   열기 전엔 영영 '물타기' 칸이 비어 있었다. 매입가·수량 **둘 다** 있을
        #   때만 — 수량이 없으면 헬퍼가 {} 를 돌려주어 키가 안 생기고, 그러면
        #   이 기준이 그 행을 매번 다시 채우자고 해 파이프라인만 헛돈다.
        if (w.get('paid') and w.get('qty')
                and 'snap_avg_down_ok' not in w):
            return True
        return False

    _fill_missing = [w for w in _wl_items() if _wl_needs_fill(w)]
    #: 한 번에 몇 개까지. 오래 걸린다는 사실을 숨기지 않고 나눠 돌린다.
    _WL_FILL_MAX = 5
    if _fill_missing:
        _fm_names = ", ".join(str(w.get('name')) for w in _fill_missing[:8])
        st.warning(
            f"**엔진 값이 모자란 종목 {len(_fill_missing)}개** — {_fm_names}"
            + (f" 외 {len(_fill_missing) - 8}종목"
               if len(_fill_missing) > 8 else '')
            + f"  \n매입가를 적은 종목은 **보유자 기준값**(버틸 수 없는 "
              f"가격 · 팔 가격 1차)까지 있어야 '엔진 판단'이 나옵니다. "
              f"한 종목 정밀분석이 **1~3분** 걸립니다. 한 번에 "
              f"**{_WL_FILL_MAX}종목씩** 채웁니다 — 없는 값을 지어내지 "
              f"않고 실제로 계산합니다.")
        _todo166 = _fill_missing[:_WL_FILL_MAX]
        if st.button(f"{len(_todo166)}종목 지금 계산해서 채우기",
                     key='wl_fill_now', type='primary'):
            import verdict_core as _vc166
            import next_action as _na
            _bar166 = st.progress(0.0)
            _msg166 = st.empty()
            _done166, _fail166 = [], []
            for _i166, _w166 in enumerate(_todo166):
                _c166 = portfolio.normalize_code(_w166.get('code'))
                _nm166 = str(_w166.get('name') or _c166)
                _msg166.info(f"{_i166 + 1}/{len(_todo166)} · **{_nm166}** "
                             f"계산 중…")
                try:
                    _sym166 = (f"{_c166}.KQ"
                               if str(_w166.get('market') or '') == 'KOSDAQ'
                               else f"{_c166}.KS")
                    _snp166, _ = get_shared_snapshot(_sym166, t_ref_str,
                                                     rho_cutoff)
                    _fs166 = _snp166.get('four_scores') or {}
                    # ⚠️ 라운드 169 — 여기가 `build(_snp166)` 이었다.
                    #   `build()` 의 첫 인자는 **four_scores** 인데 스냅샷을
                    #   통째로 넘겨서, 안에서 읽는 키가 전부 None 이 됐다.
                    #   그래서 채운 종목이 죄다 bucket='데이터 부족' 이고
                    #   보유자 값이 비었다 — **못 낸 게 아니라 잘못 물어본
                    #   것**이다. 라운드 167 에서 겪은 것과 같은 모양
                    #   (경로를 베끼면서 한 단계를 빠뜨렸다).
                    #   화면(:5798)이 부르는 방식 그대로 맞춘다 (§4).
                    _vd166 = _snp166.get('verdict')
                    if _vd166 is None:
                        _vd166 = q_engine.build_final_verdict(_snp166)
                    _na166 = _na.build(_fs166, _snp166.get('tech_df'),
                                       _fs166.get('current_price'), _vd166)
                    _co166 = _vc166.build(
                        _fs166, verdict=_vd166,
                        price_axes=_fs166.get('price_axes'),
                        next_action=_na166,
                        realtime_price=_fs166.get('current_price'))
                    _vals166 = {
                        'snap_buy': (_co166.get('pullback_zone')
                                     or (_co166.get('buy_zone') or [None])[0]),
                        'snap_t1': _co166.get('new_target'),
                        'snap_t2': _fs166.get('target_tech_2nd'),
                        'snap_fair': _fs166.get('displayed_fair_value'),
                        'snap_fair_conf': _fs166.get('fair_value_confidence'),
                        'snap_px': _fs166.get('current_price'),
                        'snap_at': t_ref_str,
                        'snap_engine': str(_VER_NOW.get('model') or ''),
                        'snap_bucket': _co166.get('bucket'),
                        # 보유자 기준 (라운드 169) — 다른 키다 (§4)
                        'snap_hold_trim': _co166.get('hold_trim'),
                        'snap_hold_stop': _co166.get('hold_stop'),
                        # 업종 (라운드 214) — 포트폴리오 견해의 업종 비중 재료
                        'snap_sector': (_snp166.get('val_eval') or {}).get('sector'),
                    }
                    # 물타기 판정 (라운드 214) — 매입가·수량이 있을 때만 찍힌다
                    _vals166.update(_wl_avg_down_snap(_w166, _snp166))
                    _done166.append((_c166, _vals166))
                except Exception as _ex166:                    # noqa: BLE001
                    # 실패를 통과로 적지 않는다 — 왜 못 냈는지 그대로 쓴다
                    _fail166.append((_nm166,
                                     f'{type(_ex166).__name__}: {_ex166}'[:90]))
                _bar166.progress((_i166 + 1) / len(_todo166))
            _by166 = dict(_done166)
            _out166 = []
            for _w166 in _wl_items():
                _c166 = portfolio.normalize_code(_w166.get('code'))
                _n166 = dict(_w166)
                for _k166, _v166 in (_by166.get(_c166) or {}).items():
                    if _v166 not in (None, ''):
                        _n166[_k166] = _v166
                _out166.append(_n166)
            if _by166:
                _wl_write(_out166)
            _bar166.empty()
            _msg166.empty()
            if _fail166:
                st.error("채우지 못한 종목 — 사유를 그대로 적습니다 (§3):  \n"
                         + "  \n".join(f"· **{n}** — {r}" for n, r in _fail166))
            if _by166:
                st.success(f"{len(_by166)}종목을 채웠습니다 "
                           f"(기준일 {t_ref_str}).")
            st.rerun()
    if _stale:
        st.caption("아직 분석을 열지 않아 엔진 값이 없는 종목: "
                   + ", ".join(str(w.get('name')) for w in _stale[:8])
                   + (f" 외 {len(_stale) - 8}종목" if len(_stale) > 8 else '')
                   + " — 위 버튼으로 채우거나, 이름을 누르면 채워집니다. "
                     "없는 값을 지어내지 않습니다.")

    # ══════════════════════════════════════════════════════════════
    # 내 포트폴리오 견해 (라운드 169)
    #
    # 사용자 요청: *"내 포트폴리오에 대한 견해도 관심종목 밑에 적절하게
    # 넣어주면 좋겠어."*
    #
    # ⚠️ 새 판정을 만들지 않는다. 위 표가 이미 낸 `_uk.watch_action()`
    #   결과를 **세기만** 한다 (§4 — 값은 한 곳에서). 금액은 사용자가
    #   적은 매입가·수량으로 하는 산수일 뿐이다.
    # ⚠️ §9 — 평단가는 보유 판단에만. 점수·적정가·예측에 안 들어간다.
    # ⚠️ 못 잰 것은 못 쟀다고 적는다 (§3) — 현재가 미수신·엔진 값 없음을
    #   숨기지 않는다.
    # ══════════════════════════════════════════════════════════════
    _pf_held, _pf_watch = [], []
    _pf_cost = _pf_val = 0.0
    _pf_qty = 0                        # 총 매입수량 (라운드 171 · 사용자 요청)
    _pf_noprice, _pf_nojudge = [], []
    for _nm169, _act169, _row169, _px169 in _wl_acts:
        _paid169 = _row169.get('paid')
        _qty169 = _row169.get('qty')
        if not _px169:
            _pf_noprice.append(_nm169)
        if not _act169:
            _pf_nojudge.append(_nm169)
        if _paid169 and _qty169 and _px169:
            _c169 = float(_paid169) * float(_qty169)
            _v169 = float(_px169) * float(_qty169)
            _pf_cost += _c169
            _pf_val += _v169
            _pf_qty += int(_qty169)
            _pf_held.append((_nm169, _act169, _c169, _v169))
        elif _paid169:
            _pf_held.append((_nm169, _act169, None, None))
        else:
            _pf_watch.append((_nm169, _act169))

    _uk.spacer(10)
    st.subheader("내 포트폴리오 견해")

    if not _pf_held and not _pf_watch:
        st.caption("아직 볼 것이 없습니다.")
    else:
        # ── ① 보유 — 금액은 산수, 판단은 위 표에서 그대로 ─────────
        if _pf_cost > 0:
            _pl169 = _pf_val - _pf_cost
            _plp169 = _pl169 / _pf_cost * 100.0
            _top169 = max(_pf_held, key=lambda t: (t[3] or 0))
            _conc169 = (_top169[3] or 0) / _pf_val * 100 if _pf_val else 0
            # 라운드 171 — 사용자 요청으로 **총 매입금액·총 매입수량**을
            # 함께 낸다. 전부 산수다 (매입가 × 수량).
            _uk.stat_tiles([
                dict(label='보유 종목',
                     value=f"{sum(1 for h in _pf_held if h[2]):,}개",
                     sub=f"총 {_pf_qty:,}주"),
                dict(label='총 매입금액', value=f"{_pf_cost:,.0f}원"),
                dict(label='평가금액', value=f"{_pf_val:,.0f}원"),
                # ⚠️ 라운드 174 — 여기만 `pos`(초록)를 쓰고 있었다. 바로 위
                #   표의 같은 값은 `up`(빨강)이라 **한 화면에 두 색 언어**가
                #   있었다. 가격에서 나온 수는 한국 관행을 따른다 (§5).
                dict(label='평가손익', value=f"{_pl169:+,.0f}원",
                     sub=f"{_plp169:+.1f}%",
                     tone=('up' if _pl169 >= 0 else 'down')),
                dict(label='가장 큰 종목 비중',
                     value=f"{_conc169:.0f}%", sub=str(_top169[0])[:14]),
            ], theme=_theme)

        # ── ② 엔진이 지금 뭐라 하는가 — 세기만 한다 ────────────────
        _cnt169 = {}
        for _nm169, _act169, *_ in _pf_held:
            if _act169:
                _cnt169.setdefault(_act169['label'], []).append(_nm169)
        _cnt_w169 = {}
        for _nm169, _act169 in _pf_watch:
            if _act169:
                _cnt_w169.setdefault(_act169['label'], []).append(_nm169)

        def _line169(title, d, empty):
            if not d:
                return f"**{title}** — {empty}"
            return f"**{title}** — " + " · ".join(
                f"{k} **{len(v)}종목**({', '.join(v[:3])}"
                + (f" 외 {len(v) - 3}" if len(v) > 3 else '') + ")"
                for k, v in sorted(d.items(), key=lambda t: -len(t[1])))

        st.markdown(_line169(
            f"보유 중 {len(_pf_held)}종목", _cnt169,
            "매입가를 적은 종목이 없습니다 — 적으면 보유 기준으로 판단합니다."))
        st.markdown(_line169(
            f"안 산 것 {len(_pf_watch)}종목", _cnt_w169,
            "판단할 값이 아직 없습니다."))

        # ── ②' 업종·시장 국면 — **서술만 한다** (라운드 214 · 사용자 요청) ──
        # *"내 포트폴리오 견해에 대해서 섹터별 어떤지 시장상황도 보고 … 이런 거에
        #   대한 판단 엔진도 만들어야 하지 않을까?"*
        # 여기서 **점수를 만들지 않는다.** 포트폴리오 '점수'를 내려면 문턱이
        # 필요한데, 원장은 **종목 단위**라 포트폴리오 단위 성적을 잴 수 없어
        # 사전등록·실측이 불가능하다 (§2 — 잴 수 없는 문턱은 감이다). 그래서
        # **잰 것만 서술한다** — 업종 비중은 산수(매입원가 · :4709 와 같은 정의),
        # 업종 성적은 `sector_cycle.ledger_perf`(표시 전용 · 라운드 44), 국면은
        # 종목 상세와 **같은 함수**(`_market_state_214`)가 낸 라벨이다 (§4).
        _sec214, _sec_unknown, _sec_etf = {}, [], []
        # 라운드 223 — ETF 는 업종이 **구조상 없다**(R218). "종목을 열면 채워집니다"
        #   는 보통주 얘기다. 못 채운 것과 없는 것을 가른다(§3). ETF 목록을 못
        #   읽으면 가르지 않는다 — 지어내지 않는다.
        try:
            import json as _json223
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   'data', 'etf_index.json'), encoding='utf-8') as _f223:
                _etf223 = set((_json223.load(_f223).get('map') or {}).keys())
        except Exception:                                      # noqa: BLE001
            _etf223 = set()
        for _nm169, _act169, _row169, _px169 in _wl_acts:
            if not (_row169.get('paid') and _row169.get('qty')):
                continue
            try:
                _cst = float(_row169['paid']) * float(_row169['qty'])
            except (TypeError, ValueError):
                continue
            _sc = str(_row169.get('snap_sector') or '')
            if _sc:
                _sec214[_sc] = _sec214.get(_sc, 0.0) + _cst
            elif str(_row169.get('code') or '').split('.')[0][:6] in _etf223:
                _sec_etf.append(_nm169)
            else:
                _sec_unknown.append(_nm169)
        if _sec214 or _sec_unknown:
            _sec_tot = sum(_sec214.values())
            _sec_lines = []
            for _sc, _v in sorted(_sec214.items(), key=lambda t: -t[1]):
                _w = _v / _sec_tot * 100.0 if _sec_tot else 0.0
                _perf = ''
                try:
                    import sector_cycle as _sc214
                    _lp = _sc214.ledger_perf(_sc)
                    if _lp and _lp.get('n'):
                        _perf = (f" · 표본 {_lp['n']:,}건뿐" if _lp.get('small')
                                 else f" · 이 업종 매수권 원장 적중 "
                                      f"{_lp['hit']:.0f}%(n={_lp['n']:,})")
                except Exception:                              # noqa: BLE001
                    _perf = ''                # 실측 표 하나 때문에 화면이 죽지 않는다
                _sec_lines.append(f"{_sc} **{_w:.0f}%**{_perf}")
            _hhi = (sum((_v / _sec_tot) ** 2 for _v in _sec214.values())
                    if _sec_tot else None)
            _sec_md = "**업종별 (매입원가 비중)** — " + (
                " · ".join(_sec_lines) if _sec_lines else "업종을 아직 못 읽었습니다")
            if _hhi:
                _sec_md += (f"  \n업종 집중도 HHI {_hhi:.2f} · 유효 업종 수 "
                            f"{1.0 / _hhi:.1f}개 (1에 가까울수록 한 업종에 쏠림)")
            # 라운드 223 — 사용자: "섹터별로 좋은지 평가를 내리는 게 좋지 않을까?"
            #   위 업종별 적중(53~70%)의 차이는 표본·국면 조성 차이 안에 있어
            #   업종을 고르는 근거가 못 된다 — R46 업종 게이트 기각("업종 문제가
            #   아니다") · R181 은 블라인드 날짜 부족으로 재측정을 전방 재평가
            #   뒤로 미뤘다. 숫자만 보여 주고 이 말을 안 하면 사용자는 높은 업종을
            #   고르라는 뜻으로 읽는다(§9). 날짜는 forward_eval 한 곳에서 읽는다.
            try:
                import forward_eval as _fe223
                _fed223 = _fe223.eval_date() or '전방 재평가일 미기록'
            except Exception:                                  # noqa: BLE001
                _fed223 = '전방 재평가일 미기록'
            _sec_md += (f"  \n위 업종별 적중 차이는 **업종을 고르는 근거가 못 됩니다** — "
                        f"표본·국면 조성 차이 안에 있고, 업종 게이트는 실측에서 기각됐습니다"
                        f"(R46). 업황 조정은 {_fed223} 전방 재평가 뒤 다시 잽니다(R181). "
                        f"이 표는 비중을 세어 보여 줄 뿐입니다.")
            if _sec_etf:
                _sec_md += ("  \nETF(업종 없음 · 구조상): " + ", ".join(_sec_etf[:5])
                            + (f" 외 {len(_sec_etf) - 5}" if len(_sec_etf) > 5 else '')
                            + " — 위 업종 비중에는 들어 있지 않습니다")
            if _sec_unknown:
                _sec_md += ("  \n업종 미확인: " + ", ".join(_sec_unknown[:5])
                            + (f" 외 {len(_sec_unknown) - 5}"
                               if len(_sec_unknown) > 5 else '')
                            + " — 종목을 열면 채워집니다")
            st.markdown(_sec_md)
        _ms214 = _market_state_214()
        if _ms214 and _ms214.get('ko'):
            _rg_md = f"**시장 국면** — {_ms214['ko']}"
            if _ms214.get('slope_ko'):
                _rg_md += f" · 60일선 {_ms214['slope_ko']}"
            if _ms214.get('hit') is not None and _ms214.get('n'):
                _rg_md += (f" · 이 국면의 매수권 적중 {_ms214['hit']:.1f}% "
                           f"(n={_ms214['n']:,} · 개발 구간 · 라운드 52 실측)")
            if _ms214.get('say'):
                _rg_md += f"  \n{_ms214['say']}"
            st.markdown(_rg_md)
        else:
            st.caption("시장 국면 — 지수를 못 받아 판정하지 않았습니다 (지어내지 않습니다).")

        # ── ③ 못 잰 것을 밝힌다 (§3) ────────────────────────────────
        if _pf_noprice:
            st.caption("현재가 미수신이라 판단에서 뺀 종목: "
                       + ", ".join(_pf_noprice[:6])
                       + (f" 외 {len(_pf_noprice) - 6}" if len(_pf_noprice) > 6
                          else ''))
        if _pf_nojudge:
            st.caption("엔진 값이 없어 판단하지 못한 종목: "
                       + ", ".join(_pf_nojudge[:6])
                       + (f" 외 {len(_pf_nojudge) - 6}" if len(_pf_nojudge) > 6
                          else '')
                       + " — 위 '지금 계산해서 채우기' 로 채울 수 있습니다.")

        # ── ④ 이 견해가 무엇이고 무엇이 아닌가 (§9) ────────────────
        # 라운드 223 — 이 문구가 '원장 184,759건'을 날짜 없이 박고 있었다(지금
        #   250,725). 잰 날짜와 당시 행수는 손으로 적지 않고 R159 의 산출물
        #   (`data/census_r159.json` 의 made · ledger_rows)에서 읽는다 — 그 파일은
        #   판정한 날 그대로 두는 것이 맞고(R107), 옛 재평가일 리터럴을 .py 에
        #   박으면 R78 의 잠금에 걸린다. 못 읽으면 라운드 번호만 적는다(§3).
        try:
            import json as _json159
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   'data', 'census_r159.json'), encoding='utf-8') as _f159:
                _c159 = _json159.load(_f159)
            _c159_when = (f"{str(_c159.get('made'))[:10]} 실측 · 당시 원장 "
                          f"{int(_c159.get('ledger_rows') or 0):,}건 전수")
            _c159_be = _c159.get('breakeven') or {}
            _c159_verdict = (f"블라인드 적중 {float(_c159_be.get('blind_hit_pct')):.1f}% "
                             f"vs 본전 {float(_c159_be.get('need_hit_pct')):.1f}%"
                             if _c159_be.get('blind_hit_pct') is not None
                             and _c159_be.get('need_hit_pct') is not None
                             else "판정 수치는 산출물에 없음")
        except Exception:                                      # noqa: BLE001
            _c159_when = "실측 시점은 산출물을 못 읽어 미기록"
            _c159_verdict = "판정 수치는 산출물을 못 읽어 미기록"
        _uk.note(
            "**이 견해가 하는 일** — 위 표의 판단을 **세어서** 보여 줄 "
            "뿐입니다. 판단 자체는 엔진이 발표한 가격선(버틸 수 없는 가격 · "
            "팔 가격 1차 · 목표 매수가)과 현재가를 견준 것이고, 여기서 새 "
            "기준을 만들지 않았습니다.  \n"
            "**하지 않는 일** — 비중을 얼마로 하라거나 무엇을 사라고 하지 "
            "않습니다. 이 엔진의 매수 신호에는 **비용 차감 뒤 실전에서 "
            f"재현되는 우위가 확인되지 않았습니다** (라운드 159·168 · "
            f"{_c159_when} — {_c159_verdict}. 원장은 그 뒤 "
            "커졌고 결론은 R215·R216 에서 다시 확인했습니다). "
            "평균 매수가는 보유 판단에만 쓰고 점수·적정가·예측에는 "
            "넣지 않습니다.", theme=_theme)

    _uk.spacer(10)
    _wc1, _wc2 = st.columns([1, 3])
    with _wc1:
        if st.button("전체 비우기", width='stretch', key='wlb_clear'):
            _wl_write([], '관심종목을 모두 비웠습니다')
            st.rerun()
    with _wc2:
        if not ALLOW_LOCAL_STORE:
            st.caption("원격 접속이라 이 목록은 **이 브라우저 세션에만** "
                       "남습니다 — 파일로 저장하지 않습니다.")
_uk.spacer(28)


# ── 캘리브레이션 산출물 로더 — 홈 카드·판정 캡션·모델 성과 섹션이 공유 ──────
# rerun 마다 엔진이 새로 만들어져 속성이 비므로, 파일을 직접 읽어 캐시한다.
# 경로: .portfolio/ (로컬 최신) 우선, 없으면 data/ (저장소 동봉 — 클라우드 배포용).
def _artifact_source(fname):
    """이 값이 **로컬 최신인가 저장소 동봉본인가** (라운드 108).

    ⚠️ `.portfolio` 는 gitignore 라 배포 환경에 없다. 그래서 배포에서는
      늘 `data/` 동봉본을 읽는다. 그런데 동봉본이 2026-08-02 에 멈춰
      있었고(6,508건 · 실제 184,759건), 화면은 그것을 **최신인 양**
      보여 주고 있었다. 더 나쁜 것은 그 숫자가 모델에 유리한 쪽이었다는
      점이다 — 고신뢰 비용후 수익 -0.10(동봉) vs -0.43(실제),
      PF 1.17 vs 1.04. §9 는 성과를 좋게 보이게 쓰지 말라고 한다.

      동봉본은 갱신했고(scripts/refresh_bundle.py), 여기서는 **어느
      쪽을 읽었는지 밝힌다.** 조용한 폴백은 §3 위반이다.
    """
    _base = os.path.dirname(os.path.abspath(__file__))
    if os.path.exists(os.path.join(_base, ".portfolio", fname)):
        return 'live'
    if os.path.exists(os.path.join(_base, "data", fname)):
        return 'bundle'
    return None


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
# ⚠️ 라운드 199 — 지수 조회를 **여기로 올렸다.**
#   아래 '어젯밤 미국장' 카드가 `m_indices` 를 쓰는데 그 이름은
#   **342줄 뒤(5844)**에서 만들어지고 있었다. `except Exception` 이
#   NameError 를 삼켜 `_sp_pct` 가 **항상 None** 이었고, 그래서
#   라운드 16 의 실측 경고(*"전날 미국장이 보합인 날의 성적이 가장
#   나빴다"*)가 **한 번도 화면에 안 나왔다.** 경고는 안 나와도
#   티가 안 나므로 아무도 몰랐다 — §226 이 AST 로 잡았다.
#   조회는 네트워크를 타므로 **한 번만** 부른다(아래 중복 제거).
m_indices = engine_init.get_market_indices()

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
        # 라운드 198 — 원장 행수를 쓴다(위 상태 줄과 같은 수). 이어받은
        #   행이 있으면 **그 사실도 적는다** — 다시 채점되지 않은 수다(§3).
        {'label': '되돌려 본 판단',
         'value': (f"{_home_cal.get('ledger_rows') or _home_cal['total_cases']:,}"),
         'sub': (f"모델 {_VER_NOW['model']}"
                 + (f" · 이어받음 {_home_cal['carried_over']:,}"
                    if _home_cal.get('carried_over') else ''))},
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

            # ── 이 표가 언제 잰 값이고, 무엇을 못 말하는가 (라운드 121) ──
            #
            # 두 가지를 밝힌다. 둘 다 이 표만 봐서는 알 수 없다.
            #   ① **언제 잰 값인가** — 산출물에 측정 시각이 안 적혀 있었다.
            #      §2 가 적어 둔 그대로다: "날짜 없는 숫자는 반드시 낡는다."
            #   ② **케이스 수가 독립 관측 수가 아니다** — 국면은 시장 수준
            #      값이라 같은 날 추천 90건이 케이스 90·날짜 1이다.
            #      VIX 축에서 이미 당했다 ("280건"이 실은 날짜 5개).
            #
            # 표의 숫자는 **고치지 않는다.** 이 파일은 regime_policy 가
            # 점수·비중·손절 상한을 정하는 데 쓰고, R55·R57·R66 전방 표본이
            # 2026-08-09 부터 쌓이는 중이다. 지금 다시 재면 그 표본이 무효다.
            _rgd = None
            try:
                with open(os.path.join(
                        os.path.dirname(os.path.abspath(__file__)),
                        '.portfolio', 'regime_cell_days.json'),
                        encoding='utf-8') as _rdf:
                    _rgd = json.load(_rdf)
            except Exception:                                # noqa: BLE001
                _rgd = None
            _rb_when = _rb.get('generated_at')
            _prov = (f"이 표는 **{_rb_when}** 에 잰 값입니다. "
                     if _rb_when else
                     "이 표에는 **측정 시각이 기록돼 있지 않습니다** — "
                     "언제 잰 값인지 산출물이 말하지 않습니다. ")
            _days_line = ''
            if _rgd and (_rgd.get('cells') or {}):
                _cl = _rgd['cells']
                _pairs = [(f"{_rb['vol_ko'].get(_vb, _vb)} "
                           f"{_rb['regime_ko'].get(_rg, _rg)}",
                           (_cl.get(f'{_rg}|{_vb}') or {}).get('blind') or {})
                          for _rg, _vb in _RG_ORDER]
                _pairs = [(_k, _m) for _k, _m in _pairs if _m.get('days')]
                if _pairs:
                    _wk, _wm = max(_pairs,
                                   key=lambda x: x[1]['n'] / x[1]['days'])
                    _days_line = (
                        f"그리고 국면은 **시장 수준** 값이라 케이스 수가 "
                        f"독립 관측 수가 아닙니다 — {_rgd.get('measured_at')} "
                        f"원장 {_rgd.get('ledger_buyzone_n', 0):,}건으로 재니 "
                        f"실전 칸의 **케이스÷날짜**가 "
                        f"{min(m['n'] / m['days'] for _, m in _pairs):.0f}~"
                        f"{max(m['n'] / m['days'] for _, m in _pairs):.0f}배"
                        f"입니다 (가장 큰 칸: {_wk} {_wm['n']:,}건 = "
                        f"**{_wm['days']}일**). 표의 n 을 독립 표본 수로 "
                        f"읽으면 근거를 실제보다 크게 봅니다. ")
            _uk.note(
                _prov + _days_line
                + f"이 표는 국면 라우팅(R55) 전방 재평가일 "
                  f"**{_fe.eval_date_ko()}** 까지 다시 재지 않습니다 — "
                  f"지금 다시 재면 2026-08-09 부터 쌓은 전방 표본이 "
                  f"무효가 됩니다. 속도가 아니라 방법의 문제입니다.",
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

# ── 개장 전 한 줄 결론 — 자리를 **여기로 되돌렸다** (라운드 127).
#   묶음을 맞추려고 보유종목 앞으로 올렸더니, 라운드 68 이 적어 둔
#   "모델 상태 — 사용자 요청 · 화면 최상단 고정"보다 위로 갔다.
#   지난 사용자 결정을 내 편의로 뒤집지 않는다. 그래서 메뉴에는
#   보유종목이 사이에 끼는 뒤집힘 1건이 남는다 — §170 에 이유를 적었다.
# 개장 전 한 줄 결론 (리포트가 있을 때만 — 없으면 만들지 않는다)
try:
    import premarket as _pm_home
    _pm_today = st.session_state.get('premarket_report') or _pm_home.load_today_report()
except Exception:
    _pm_today = None
if _pm_today and _pm_today.get('picks'):
    # 라운드 120h — 여기서 `reco_class` **문자열**을 세고 있었다. 리포트
    #   본문은 중앙 판정(`core.recommended`)으로 가르는데 배너만 다른
    #   잣대를 써서, 같은 화면에 이 둘이 **함께** 떠 있었다:
    #
    #       "개장 전 한 줄 결론 · 오늘은 매수 후보가 있습니다"
    #       "오늘은 … 실제 매수를 검토할 수 있는 종목이 없습니다"
    #
    #   교촌에프앤비를 보다가 잡았다. `reco_class` 의 '조건부로 사도 되는
    #   종목' 1건이 중앙 판정에서는 추천이 아니었다(실행 가능 0). §4 가
    #   금지한 두 번째 경로다 — 라운드 114 의 요약 칸과 같은 모양이다.
    _pm_picks = _pm_today['picks']
    _pm_has_core = any(_pk.get('core') for _pk in _pm_picks)

    # ── 관심종목 값 주기 갱신 (라운드 142) ──────────────────────────
    # 사용자 요청: "목표매수가·1차·2차·적정가를 **주기적으로 저장**해서
    # 표기해 주는 게 좋을 듯하다."
    #
    # 라운드 141 은 **그 종목을 볼 때**만 찍었다. 그래서 안 열어 본
    # 종목은 영원히 비어 있었다. 개장 전 리포트에 그 종목이 있으면
    # 여기서도 채운다 — 리포트는 매 거래일 다시 만들어지므로 이것이
    # **주기적 갱신**이 된다. 새 계산을 돌리지 않으므로 공짜다.
    #
    # 값은 리포트가 들고 있는 CORE 에서 온다 (§4 — 한 곳에서).
    try:
        _wl_codes142 = {portfolio.normalize_code(w.get('code'))
                        for w in _wl_items()}
        if _wl_codes142:
            _asof142 = str(_pm_today.get('data_asof')
                           or _pm_today.get('date') or '')[:10]
            _eng142 = str(_pm_today.get('engine_version') or '')
            _by142 = {}
            for _pk142 in _pm_picks:
                _c142 = portfolio.normalize_code(_pk142.get('code'))
                if _c142 in _wl_codes142:
                    _by142[_c142] = _pk142
            if _by142:
                _upd142, _dirty142 = [], False
                for _w142 in _wl_items():
                    _c142 = portfolio.normalize_code(_w142.get('code'))
                    _pk142 = _by142.get(_c142)
                    if not _pk142:
                        _upd142.append(_w142)
                        continue
                    _co142 = _pk142.get('core') or {}
                    _snap = {
                        'snap_buy': (_co142.get('pullback_zone')
                                     or _pk142.get('rec_buy')),
                        'snap_t1': _co142.get('new_target'),   # 진입가 기준
                        'snap_t2': _pk142.get('target2'),      # 현재가 기준
                        'snap_fair': _pk142.get('displayed_fair_value'),
                        'snap_fair_conf': _pk142.get(
                            'fair_value_confidence'),
                        'snap_px': _pk142.get('price'),
                        'snap_at': _asof142, 'snap_engine': _eng142,
                        'snap_bucket': _co142.get('bucket'),   # 라운드 166
                        # 보유자 기준 (라운드 169) — 다른 키다 (§4)
                        'snap_hold_trim': _co142.get('hold_trim'),
                        'snap_hold_stop': _co142.get('hold_stop'),
                    }
                    _n142 = dict(_w142)
                    for _k, _v in _snap.items():
                        # 못 낸 값으로 옛 값을 덮어쓰지 않는다 (라운드 141)
                        if _v in (None, ''):
                            continue
                        if _n142.get(_k) != _v:
                            _dirty142 = True
                        _n142[_k] = _v
                    _upd142.append(_n142)
                if _dirty142:
                    _wl_write(_upd142)
    except Exception:                                          # noqa: BLE001
        pass          # 관심종목 갱신 때문에 개장 전 화면이 죽지 않는다
    _buyable = sum(1 for _pk in _pm_picks
                   if (_pk.get('core') or {}).get('recommended'))
    # 칸 이름도 리포트 본문과 같은 어휘(verdict_core 의 bucket)로 적는다.
    _cls_cnt = {}
    for _pk in _pm_picks:
        _bk_pm = (_pk.get('core') or {}).get('bucket') or '판정 없음'
        _cls_cnt[_bk_pm] = _cls_cnt.get(_bk_pm, 0) + 1
    # ⚠️ 라운드 105 — 사용자가 이 문구를 인용하면서 "어디 있어? 안 보이는데"
    #   라고 물었다. 실측하니 **화면에는 있었다**(Y=848). 못 찾은 이유가
    #   둘이었다.
    #     ① 앵커가 없어 내비게이션이 여기로 못 온다. 내비의 '한 줄 결론'은
    #        Y=2093 의 **개별 종목** 판정으로 가서 이 배너를 지나친다.
    #     ② "**아래** '오늘의 추천'" 이라 적었는데 오늘의 추천은 Y=-570 —
    #        1,418px **위**다. 방향이 반대였다.
    #   방향어를 쓰지 않고 **앵커 링크**로 건다 — 위아래가 바뀌어도 안 틀린다.
    st.markdown('<div id="nav-premarket-line"></div>', unsafe_allow_html=True)
    # 중앙 판정이 아예 없는 옛 리포트는 '있다/없다'를 말하지 않는다 (§3).
    if not _pm_has_core:
        _oneline = ("이 리포트에는 중앙 판정이 없습니다 (옛 엔진) — "
                    "[오늘의 추천](#nav-premarket)에서 다시 스캔하세요.")
    else:
        _oneline = (f"오늘은 매수 후보가 {_buyable}종목 있습니다 — "
                    "[오늘의 추천](#nav-premarket)에서 조건을 확인하세요."
                    if _buyable else
                    "오늘은 공격적 매수보다 관망·눌림목 확인이 유리합니다 — 매수 후보가 없습니다.")
    st.info(f"**개장 전 한 줄 결론** · {_oneline}  \n"
            + " · ".join(f"{k} **{v}**" for k, v in _cls_cnt.items())
            + f"  ·  기준 데이터 {_pm_today.get('data_asof')} (전일 확정)")

# (m_indices 는 위 '모델 성적' 블록 앞에서 이미 한 번 부른다 — 라운드 199)

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
                # ⚠️ 라운드 172 — 여기서 문구를 **조립하지 않는다.**
                #   종전에는 화면이 `work_status` 를 배지로 쓰고 경과일·
                #   '즉시 수정 가능'·'다음 점검' 을 스스로 붙였는데,
                #   닫는 길 넷 중 셋이 `work_status` 를 안 고쳐서
                #   **해결된 이슈 3건이 전부 진행 중처럼** 나왔다.
                #   그중 하나는 *"즉시 수정 가능 · 다음 점검 2026-08-15"* —
                #   10일 지난 날짜였다. 이제 `issue_ops` 가 `status` 를
                #   먼저 보고 만든 문구를 그대로 찍는다 (§4).
                _ws = _tr.get('state_label') or _tr.get('work_status') or '확인 중'
                _tone = _uk.tokens(_theme).get(_ST_TONE.get(_ws, 'tx2'))
                _meta = ' · '.join(
                    str(_x) for _x in (_tr.get('age_label'),
                                       _tr.get('fix_label'),
                                       _tr.get('review_label')) if _x)
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
                    f"color:{_TOK['tx2']};'>{_uk._esc(_meta)}</span>"
                    f"<p style='margin:8px 0 4px 0; font-size:15px; "
                    f"font-weight:600; color:{_TOK['tx1']};'>"
                    f"{_uk._esc_md(_tr['title'])}</p>"
                    f"<p style='margin:0; font-size:13px; color:{_TOK['tx2']}; "
                    f"line-height:1.6;'><b>왜 생겼나</b> "
                    f"{_uk._esc_md(_tr.get('cause',''))}<br>"
                    f"<b>영향</b> {_uk._esc_md(_tr.get('user_impact',''))}<br>"
                    f"<b>지금 하는 일</b> "
                    f"{_uk._esc_md(_tr.get('action_plan',''))}<br>"
                    f"<b>임시 안전조치</b> "
                    f"{_uk._esc_md(_tr.get('safeguard',''))}<br>"
                    f"<b>목표</b> {_uk._esc_md(_tr.get('target',''))}"
                    + (f"<br><b>담당</b> <span style='color:{_TOK['tx3']};'>"
                       f"{_uk._esc(_tr.get('module',''))}</span>"
                       if _tr.get('module') else '')
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
                f"{_uk._esc_md(_is['detail'])}</p></div>",
                unsafe_allow_html=True)
        if len(_issues_global) > 3:
            st.markdown("**전체 이슈**")
            st.dataframe(pd.DataFrame([{
                '중요도': i['severity'], '유형': i['type'], '제목': i['title'],
                '내용': i['detail'], '범위': i['scope'], '생성': i['created'],
            } for i in _issues_global]), width='stretch', hide_index=True)

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
# ⚠️ 라운드 164 — 아래에서 `_last_analysis_sec` 를 **쓰기만 하고** 아무도
#   안 읽고 있었다("다음 분석의 예상 시간을 알려주기 위해 기억해 둔다"고
#   적어 놓고 그 다음이 없었다). 스캔 진행줄이 이미 쓰는 표현을 그대로
#   재사용한다 — 새 문구를 만들지 않는다 (§2·§4).
_prev_sec = st.session_state.get('_last_analysis_sec')
_prev_txt = f" · 지난번 {_prev_sec:.0f}초" if _prev_sec else ''
_prog.markdown(_uk.progress(0, label=f"{resolved_name} · 데이터 수집{_prev_txt}",
                            theme=_theme, elapsed=0.0),
               unsafe_allow_html=True)
try:
    snap, snap_origin = get_shared_snapshot(target_ticker, t_ref_str, rho_cutoff)
    _prog.markdown(_uk.progress(4,
                                label=f"{resolved_name} · 과거 유사사례 탐색"
                                      f"{_prev_txt}",
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

chg_color = _TOK['up'] if pct_change >= 0 else _TOK['down']
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

# ── ETF 는 '적정가' 자리가 다르다 (라운드 164) ──────────────────────────
# 기업 적정가(EPS·BPS)는 펀드에 성립하지 않는다 — 엔진이 이미 건너뛴다.
# 대신 **발표되는 값**인 NAV 를 받아다 그대로 적는다. 못 받으면 '미수신'
# 이라 쓰고 지어내지 않는다 (§3).
_etf_nav = None
_etf_is = None
_etf_lt = None
_etf_gap = None
try:
    _etf_is = etf_registry.is_etf(target_ticker)
    if _etf_is:
        _etf_nav = etf_registry.nav_of(target_ticker)
        # 룩스루 적정가 (라운드 167) — 사전등록 기준을 통과한 ETF 만 나온다
        _etf_lt = etf_registry.lookthrough_of(target_ticker)
        # ⚠️ 라운드 171 — 못 내는 ETF 는 **왜 못 내는지**를 적는다.
        #   종전에는 화면이 그냥 조용했고, 그러면 "적정가가 없다"와
        #   "우리가 못 낸다"가 구분되지 않는다 (§3 이 가르라고 한 두 문장).
        #   라운드 170 이 1,161종목을 전수로 갈라 둔 것을 읽어 옮긴다.
        _etf_gap = etf_registry.lookthrough_gap(target_ticker)
except Exception:                                              # noqa: BLE001
    _etf_is, _etf_nav, _etf_lt, _etf_gap = None, None, None, None

_etf_tile_html = ""
if _etf_is:
    _nv_txt = (f"{_etf_nav['nav']:,.0f}원"
               if (_etf_nav and _etf_nav.get('nav')) else "미수신")
    _nv_sub = ((f"괴리 {_etf_nav['premium_pct']:+.2f}% · {_etf_nav['at']}")
               if (_etf_nav and _etf_nav.get('premium_pct') is not None)
               else "네이버 ETF 목록 응답 없음")
    _etf_tile_html = (
        "<div style='background: #161D2A; padding: 8px 12px; "
        "border-radius: 12px; text-align: center;'>"
        "<p style='margin: 0; font-size: 12px; color: #4C8DFF; "
        "font-weight: bold;'>ETF 순자산가치 (NAV)</p>"
        f"<p style='margin: 4px 0 0 0; font-size: 17px; color: #4C8DFF; "
        f"font-weight: bold;'>{_uk._esc(_nv_txt)}</p>"
        f"<p style='margin: 2px 0 0 0; font-size: 12px; color: #9DAABC;'>"
        f"{_uk._esc(_nv_sub)}</p></div>")

# 적정가 미산출 사유 캡션 — 템플릿 안 조건식이 빈 줄을 만들면 markdown 이
# 이어지는 HTML 을 코드 블록으로 바꾼다. 미리 만들어 같은 줄에 붙인다.
_fv_note_html = ""
if (four_scores.get('displayed_fair_value') is None
        and four_scores.get('fair_value_status_note')):
    _fv_note_html = (f"<p style='margin: 2px 0 0 0; font-size: 12px; "
                     f"color: #9DAABC;'>"
                     f"{_uk._esc_md(str(four_scores.get('fair_value_status_note'))[:48])}</p>")

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
    <!-- 9대 핵심 펀더멘털 & 밸류에이션 전광판 -->
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
            <p style='margin: 0; font-size: 12px; color: #4C8DFF; font-weight: bold;'>시장조정 펀더멘털 적정가</p>
            <p style='margin: 4px 0 0 0; font-size: 17px; color: #4C8DFF; font-weight: bold;'>{fmt_num(four_scores.get('displayed_fair_value'), suffix='원')}</p>{_fv_note_html}
        </div>{_etf_tile_html}
    </div>
    <!-- 가격 출처 vs 공시 출처 분리 및 다중 출처 교차검증 -->
    <p style='margin: 12px 0 0 0; color: #35C98B; font-size: 13px; text-align: center; border-top: 1px solid #1C2635; padding-top: 8px;'>
        <b>데이터 출처 분리</b>: <b>연동된 시세 출처</b> — 네이버증권(기준) · 다음금융(교차검증). <b>미연동</b> — KRX·KIND·FnGuide·Investing.
        <b>DART·KIND·기업IR</b>은 공시·재무 출처이며 현재가 대조에 사용하지 않습니다.
    </p>
</div>
""", unsafe_allow_html=True)

# ── ETF 라면 무엇이 다른지 한 문단으로 밝힌다 (라운드 164) ──────────────
# 사용자 요청은 *"ETF 도 적정가 살때말때"* 였다. 절반만 해 줄 수 있다:
#   · 못 하는 것 — **기업 적정가.** EPS·BPS·ROE 가 없는 자산이라 만들면
#     그건 지어낸 값이다 (라운드 44 가 겪은 그 폴백).
#   · 할 수 있는 것 — **NAV 대비 어디인가.** 그리고 진입·손절·목표는
#     가격·변동성으로만 정해지므로 ETF 에도 그대로 성립한다.
# 두 문장을 섞지 않는다 (§3 — '데이터 미수신 ≠ 추천 없음' 과 같은 모양).
if _etf_is:
    _nav_p = _uk.nav_premium((_etf_nav or {}).get('price'),
                             (_etf_nav or {}).get('nav'))
    # ⚠️ `_uk.card` 는 값을 돌려주지 않고 **직접 그린다.** st.markdown 으로
    #   감싸면 화면에 'None' 이 찍힌다.
    _uk.card(
            "<div style='font-size:13px; line-height:1.65; "
            f"color:{_TOK['tx2']};'>"
            "<b style='color:" + _TOK['tx1'] + ";'>이 종목은 ETF 입니다</b> — "
            "기업이 아니라 펀드라서 <b>EPS·BPS·ROE 가 존재하지 않습니다.</b> "
            "그래서 위 '시장조정 펀더멘털 적정가'는 <b>만들지 않습니다</b> "
            "— 없는 값을 지어내지 않기 위해서입니다. ETF 에서 그 자리에 "
            "해당하는 값은 <b>순자산가치(NAV)</b>이고, 그것은 추정이 아니라 "
            "<b>발표되는 값</b>입니다."
            "</div>"
            + _uk.nav_row(_nav_p, (_etf_nav or {}).get('price'),
                          (_etf_nav or {}).get('nav'),
                          (_etf_nav or {}).get('at'), theme=_theme)
            + ("" if _etf_nav else
               f"<p style='margin:9px 0 0 0; font-size:12px; "
               f"color:{_TOK['warn']};'>NAV 미수신 — 네이버 ETF 목록 응답이 "
               f"없습니다. 값을 지어내지 않고 비워 둡니다.</p>")
            # ── 룩스루 적정가 (라운드 167) ─────────────────────────
            # 사용자 요청: *"ETF 도 그 내부의 주식이 어떻게 형성되어
            # 있는지 해서 펀더멘털 적정가를 내주는 방법을 찾자."*
            # 구성종목의 적정가를 비중으로 가중해 낸다. 배수·좌수가 식에
            # 없다 — 못 아는 값을 안 쓴다.
            # ⚠️ 표시 전용이고, **잰 날**을 반드시 함께 적는다.
            # ⚠️ 비율(`ratio`)만 산출물에서 가져오고 **NAV 는 화면이 방금
            #   받은 것**을 쓴다. 산출물의 NAV 는 잰 날의 값이라, 그대로
            #   적으면 바로 위 NAV 타일과 **다른 숫자 두 개**가 한 화면에
            #   나온다 (§4 가 금지한 그 모양 — 실제로 107,601 vs 110,197
            #   로 나왔다). 비율은 배수라 오늘 NAV 에 곱하면 된다.
            + ("" if not (_etf_lt and (_etf_nav or {}).get('nav')) else
               f"<div style='margin-top:11px; padding:10px 12px; "
               f"background:{_TOK['hover']}; border-radius:8px; "
               f"font-size:12px; line-height:1.6; color:{_TOK['tx2']};'>"
               f"<b style='color:{_TOK['tx1']};'>담은 기업들의 가치로 보면</b>"
               f" — 구성종목 {_etf_lt['holdings']}개의 펀더멘털 적정가를 "
               f"비중으로 가중하면 오늘 NAV 의 "
               f"<b>{_etf_lt['ratio']:.3f}배</b>인 "
               f"<b>{_etf_nav['nav'] * _etf_lt['ratio']:,.0f}원</b>입니다. "
               f"평가 가능한 비중 {_etf_lt['valued_pct']:.1f}%"
               + (f" · 값을 못 낸 몫 {_etf_lt['other_pct']:.1f}% 는 "
                  f"<b>1.0 으로 두었습니다</b>(가치 판단을 하지 않는다는 뜻)"
                  if _etf_lt['other_pct'] else '')
               + f" · <span style='color:{_TOK['tx3']};'>배수는 "
                 f"{_uk._esc(str(_etf_lt.get('made')))} 에 잰 것이고 "
                 f"NAV 는 방금 받은 값입니다</span>"
               f"<br><span style='color:{_TOK['tx3']};'>"
               f"<b>표시 전용입니다.</b> 이 값이 실제 성과를 가르는지는 "
               f"<b>재지 않았습니다</b> — 원장에 ETF 가 없어 검증할 표본이 "
               f"없습니다. 점수·게이트·추천에 들어가지 않습니다. "
               f"구성종목은 정기변경으로 바뀌고, 구성종목 적정가도 매일 "
               f"바뀝니다.</span></div>")
            # ── 못 내는 ETF — **왜 못 내는지** (라운드 171) ──────────
            # ⚠️ 값이 없을 때 화면이 조용하면 "적정가가 없다"와 "우리가
            #   못 낸다"가 같은 모양이 된다. 라운드 170 이 전수로 갈라
            #   둔 사유를 그대로 옮긴다 — **여기서 새로 짓지 않는다.**
            + ("" if _etf_lt or not _etf_gap else
               f"<div style='margin-top:11px; padding:10px 12px; "
               f"background:{_TOK['hover']}; border-radius:8px; "
               f"font-size:12px; line-height:1.6; color:{_TOK['tx2']};'>"
               f"<b style='color:{_TOK['tx1']};'>담은 기업들의 가치는 "
               f"내지 못했습니다</b> — {_uk._esc(str(_etf_gap['why']))}."
               + (f" 구성종목은 {_etf_gap['holdings']}개이고 "
                  f"우세 자산은 {_uk._esc(str(_etf_gap['dominant']))}입니다."
                  if _etf_gap.get('holdings') else '')
               + f"<br><span style='color:{_TOK['tx3']};'>"
                 f"국내 ETF {_etf_gap['total']:,}개 중 "
                 f"<b>{_etf_gap['passed']:,}개</b>만 이 값을 낼 수 있습니다"
                 f"({_etf_gap['passed'] / max(1, _etf_gap['total']) * 100:.1f}%). "
                 f"막는 것은 ETF 자료가 아니라 <b>우리 단일종목 적정가 "
                 f"모델</b>입니다 — 고배수·적자 구간에서는 값을 내지 않고 "
                 f"거부합니다. 지어낸 적정가보다 없는 편이 낫기 때문입니다. "
                 f"전수 조사는 {_uk._esc(str(_etf_gap.get('made')))} 에 "
                 f"했습니다.</span></div>")
            + f"<p style='margin:9px 0 0 0; font-size:12px; "
              f"color:{_TOK['tx3']};'>아래 진입가·손절·목표는 <b>가격과 "
              f"변동성만으로</b> 정해지므로 ETF 에도 그대로 성립합니다. "
              f"다만 이 엔진의 매수 신호에는 비용 차감 뒤 재현되는 우위가 "
              f"확인되지 않았고(라운드 148~160), 그 사실은 ETF 라고 달라지지 "
              f"않습니다.</p>",
            theme=_theme, accent=_TOK['brand'])

# (감사 처분: 상단 matplotlib 3단 차트 expander는 아래 '종합 차트'와 완전 중복이라
#  제거했다 — 같은 지표(MA 5·20·60·120, RSI, 거래량)를 종합 차트가 인터랙티브로 제공.)

# ═══════════════════════════════════════════════════════════════════════════
# 🧭 최종 결론 — "이 주식 사? 말어?"
# 6개 탭의 독립 판정을 가중 평균하되, 거부 조건은 평균으로 상쇄되지 않게 따로 본다.
# ═══════════════════════════════════════════════════════════════════════════
verdict = q_engine.build_final_verdict(snap)

# ── 중앙 판정 (라운드 34·37) ─────────────────────────────────────────────
# 추천 카드·종목 상세·가늠 AI·차트·보유자 화면이 **이 결과 하나만** 읽는다.
# 라운드 31 진단: 같은 개념에 이름이 5개(권장 매수가)·2개(손절)·2개(목표)
# 였고, 카드는 premarket 의 rec_buy/target/stop 을, 상세는 four_scores
# 원본을 읽었다. 경로가 둘이라 한쪽만 고치는 일이 생겼다(라운드 30 모순).
#
# ⚠️ 별칭을 `_vc` 로 쓰면 안 된다 — 그 이름은 아래에서 **결론 배너의
# 색상**으로 쓰인다. 실제로 그렇게 썼다가 배너 스타일 자리에 모듈 객체
# (`<module 'verdict_core' from '...'>`)가 찍혀 HTML 이 깨졌고, 화면에
# `from=""` 속성과 `; line-height:1.15;'>` 조각이 텍스트로 새어 나왔다.
#
# 결론 배너가 실행 가격을 여기서 받아 쓰므로 **배너보다 먼저** 만든다.
import next_action as _na
import verdict_core as _vcore
_NA = _na.build(four_scores, tech_df, realtime_price, verdict)
CORE = _vcore.build(four_scores, verdict=verdict,
                    price_axes=four_scores.get('price_axes'),
                    next_action=_NA, realtime_price=realtime_price)

# ── 관심종목 값 채우기 (라운드 141) ──────────────────────────────────
# 사용자 요청: 관심종목에 목표 매수가·1차·2차 목표·적정가를 **가져온다.**
#
# 관심종목 10종목마다 전체 파이프라인을 돌리면 화면이 몇 분씩 멈춘다
# (한 종목 정밀분석이 6단계다). 그래서 **이 종목을 볼 때** 이미 계산된
# 값을 찍어 둔다. 관심종목 화면은 그 값과 **언제 잰 것인지**를 함께
# 보여 준다 — 오늘 값인 척하지 않는다 (§3).
#
# 값은 전부 CORE 에서 온다 (§4 — 화면 값은 한 곳에서).
# ⚠️ `snap_t1` 은 **권장가 기준**, `snap_t2` 는 **현재가 기준**이다.
#   기준이 다르므로 관심종목 화면이 열 이름에 그것을 적는다.
try:
    if _wl_has(target_ticker):
        _snap141 = {
            'snap_buy': (CORE.get('pullback_zone')
                         or (CORE.get('buy_zone') or [None])[0]),
            'snap_t1': CORE.get('new_target'),          # 진입가 기준
            'snap_t2': four_scores.get('target_tech_2nd'),   # 현재가 기준
            'snap_fair': four_scores.get('displayed_fair_value'),
            'snap_fair_conf': four_scores.get('fair_value_confidence'),
            'snap_px': realtime_price,
            'snap_at': datetime.date.today().isoformat(),
            'snap_engine': str(_VER_NOW.get('model') or ''),
            # 엔진의 판단 (라운드 166) — 화면이 새로 만들지 않고 CORE 것을
            # 그대로 담는다 (§4).
            'snap_bucket': CORE.get('bucket'),
            # 보유자 기준 값 (라운드 169) — 신규 매수자 값과 **다른 키**다
            'snap_hold_trim': CORE.get('hold_trim'),
            'snap_hold_stop': CORE.get('hold_stop'),
            # 업종 (라운드 214) — 포트폴리오 견해의 업종 비중 재료
            'snap_sector': val_eval.get('sector'),
        }
        _cw141 = portfolio.normalize_code(target_ticker)
        _items141, _dirty141 = [], False
        for _w141 in _wl_items():
            if portfolio.normalize_code(_w141.get('code')) == _cw141:
                _new141 = dict(_w141)
                # 물타기 판정 (라운드 214) — 이 줄의 매입가·수량으로, 같은 스냅샷에서
                _s141 = dict(_snap141)
                _s141.update(_wl_avg_down_snap(_w141, snap))
                for _k141, _v141 in _s141.items():
                    # 못 낸 값은 **덮어쓰지 않는다** — 어제 잰 값이라도
                    # 오늘 미산출로 지워 버리면 화면이 더 비어 보인다.
                    if _v141 not in (None, ''):
                        if _new141.get(_k141) != _v141:
                            _dirty141 = True
                        _new141[_k141] = _v141
                _items141.append(_new141)
            else:
                _items141.append(_w141)
        if _dirty141:
            _wl_write(_items141)
except Exception:                                              # noqa: BLE001
    # 관심종목 갱신 때문에 분석 화면이 죽지 않는다 — 다만 **왜 못 썼는지는
    # 남긴다** (라운드 214). 종전 `pass` 는 실패를 통째로 삼켰고, 그 침묵이
    # 물타기·업종 스탬프가 한 번도 안 찍히는 결함을 가렸다. 못 쓴 것을
    # 표시 없이 지나가면 §3 위반이다 — 서버 로그에 역추적을 찍는다.
    import sys as _sys141
    import traceback as _tb141
    print('[관심종목 스냅샷 갱신 실패 — 화면은 계속 그린다]\n'
          + _tb141.format_exc(), file=_sys141.stderr)

# 라운드 40 — 이모지(🟢🔴🟡🟠⚪)를 걷어내고 토큰 색 점으로 바꾼다.
# 금융 터미널 레퍼런스 17종(Binance·Coinbase·Kraken·Stripe·Linear …)에
# 이모지를 상태 표시로 쓰는 예가 없다. 이모지는 OS·폰트마다 모양과 크기가
# 달라 정렬이 깨지고 색을 통제할 수 없다.
_ACTION_STYLE = {
    'BUY':        ("#35C98B", "매수"),
    'ACCUMULATE': ("#35C98B", "분할매수"),
    'HOLD':       ("#F2B84B", "관망"),
    'REDUCE':     ("#F26161", "비중 축소"),
    'SELL':       ("#ff453a", "매도"),
    'NO_TRADE':   ("#ff453a", "매수 안 함"),
}
_vc, _vshort = _ACTION_STYLE.get(verdict['action'], ("#9DAABC", "판단 보류"))
_vi = _uk.dot(_vc, 14)
_vscore = verdict['score']

# 실행 가격 기준 — 종합 결론 배너 안에 함께 표시 (표시 위치는 이 배너 한 곳만)
#
# ⚠️ 라운드 37 — 여기가 마지막으로 남아 있던 **두 번째 가격 경로**였다.
# 배너가 `recommended_buy_price`(적정가 × 안전마진)를 실행 가격으로 써서,
# 삼성전자 현재가 240,000원에 "147,567원 이하로 내려올 때만 사세요"(−38.5%)
# 라고 말했다. 그건 라운드 25 에서 폐기한 산식이고, 사용자가 처음부터
# 지적한 바로 그 문제다("14,600원인데 9,388원까지 언제 떨어져").
# 게다가 그 가격 기준으로 그린 손절(180,832원)이 매수가보다 **위**였다.
#
# 이제 배너도 중앙 판정(CORE)이 낸 실행 진입가만 쓴다. 적정가 기반 값은
# 장기 참고선으로 아래에 따로 적는다.
_core_entry = (CORE or {}).get('pullback_zone')
_value_floor = four_scores.get('recommended_buy_price')
rec_buy_val = _core_entry if _core_entry else _value_floor
_er_price = four_scores.get('entry_review_price')
_er_basis = four_scores.get('entry_review_basis') or ''
rec_buy_sub = ''
#: 눌러서 펼치는 상세 (라운드 79). 표면에는 **한 문장**만 남기고 근거·수치·
#: 라운드 번호는 여기로 내린다. 사용자 요청: "조금만 더 쉽게 써주고
#: 클릭하면 더 자세히 보이게." 지우는 게 아니라 **접는다** — 근거를 없애면
#: §9(성과를 좋게 보이게 쓰지 않는다)가 깨진다.
rec_buy_more = ''
#: 게이트가 막고 있는 값인가 — 막혔으면 칸 제목도 '살 가격'이 아니어야 한다.
#: "이 값 이하에서"는 매수 지시로 읽힌다 (라운드 63 이 헤드라인을 고친 이유).
_rec_blocked = False
if rec_buy_val is not None:
    rec_buy_display = f"{rec_buy_val:,.0f}원 이하"
    if _core_entry:
        # ── 두 가격의 역할 분리 (라운드 56) ──────────────────────────
        # 사용자 지적: "적정가 173,656원과 매수 기준 211,023원이 둘 다
        # '사도 되는 가격'처럼 보인다." 역할이 다르다 —
        #   적정가   = 가치상 얼마면 싼가 (재무·업종 기반 중장기 기준)
        #   매수기준 = 지금 장세에서 어디부터 진입할 만한가 (추세·변동성·
        #             체결률 실측 — 라운드 25·35: 20봉 체결률 60% 지점 2.1σ)
        # 둘이 다른 것은 오류가 아니므로, 괴리와 이유를 **엔진 값으로**
        # 자동 생성해 같이 적는다. 새 숫자는 만들지 않는다.
        _fair = four_scores.get('displayed_fair_value')
        # ⚠️ 라운드 133 — 이 나눗셈이 여기 인라인으로만 있었고 추천 카드에는
        #   아예 없었다. 두 화면이 다른 인상을 줬다(카드는 싸 보이고 상세는
        #   비싸다). 계산을 킷 한 곳으로 옮기고 **양쪽이 같은 함수를 부른다**
        #   (§4 — 경로가 둘이면 한쪽만 고치는 일이 생긴다).
        _vp = _uk.value_premium(_core_entry, _fair)
        if _vp:
            _gap_fv = _vp['pct']
            # ⚠️ 라운드 63 — 진입가까지 내려와도 **같은 이유로 여전히 막히는**
            # 경우가 있다. 삼성전자: 진입가 211,023원의 안전마진선 대비 비율이
            # 1.43 이라 'ï적정가 크게 초과' 판정이 그대로 유지된다. 그런데
            # 화면은 "이 값 이하로 내려올 때만 사세요"라고 말했다 — 살 수
            # 없는 가격을 사라고 한 셈이다. 실측(라운드 63)에서 매수권 신호
            # 15,332건 중 '크게 초과' 구간은 **0건**이었다: 엔진이 이미 그
            # 구간 전체를 차단하고 있다. 그러니 문구가 게이트를 따라가야 한다.
            _floor_fv = four_scores.get('buy_entry_max')
            _still_blocked = bool(
                _floor_fv and _floor_fv > 0
                and (_core_entry / float(_floor_fv)) > 1.15)
            if _still_blocked:
                # 제목 자체를 바꾼다 — "…이하"는 매수 지시로 읽힌다
                _rec_blocked = True
                rec_buy_display = (f"{rec_buy_val:,.0f}원 "
                                   f"(가격 조건만 · 매수 신호 아님)")
                # ⚠️ 라운드 166 — 이 문장이 **게이트가 안 쓰는 숫자**를
                #   근거로 대고 있었다. 게이트는 `buy_entry_max`(안전마진선)
                #   와 비교하는데 문장은 `적정가`와의 괴리를 적었고, 그래서
                #   다날에서 *"적정가 5,184원보다 −6.2% 비싸서"* 라는
                #   **자기모순**이 나왔다 (−6.2% 는 싸다는 뜻이다).
                #   실측: 적정가 5,184 · 안전마진선 4,147 · 진입 4,863 →
                #   4,863÷4,147 = 1.173 이라 막힌다. 문장이 그 값을 댄다.
                _over_floor = (float(_core_entry) / float(_floor_fv) - 1.0) * 100
                rec_buy_sub = (
                    f"<b>여기까지 내려와도 아직은 못 삽니다.</b> "
                    f"규칙이 보는 선은 <b>안전마진선 "
                    f"{float(_floor_fv):,.0f}원</b>인데 이 값이 그보다 "
                    f"{_over_floor:+.1f}% 위입니다.")
                rec_buy_more = (
                    f"<b>세 값의 관계</b> — 적정가 <b>{_fair:,.0f}원</b> → "
                    f"안전마진선 <b>{float(_floor_fv):,.0f}원</b>(적정가에서 "
                    f"안전마진을 뺀 자리) → 지금 이 값 "
                    f"<b>{rec_buy_val:,.0f}원</b>. 규칙은 "
                    f"<b>가운데 값</b>과 견줍니다."
                    f"<br><br>"
                    f"<b>언제 살 수 있게 되나</b> — 둘 중 하나가 일어나야 "
                    f"합니다.<br>"
                    f"① 값이 <b>{float(_floor_fv):,.0f}원</b> 부근까지 더 "
                    f"내려온다<br>"
                    f"② 실적·업황이 좋아져 <b>적정가가 올라온다</b>"
                    f"<br><br>"
                    f"<b>왜 막나</b> — 이 자리('적정가 크게 초과')에서 나온 "
                    f"매수 신호는 과거 15,332건 중 <b>0건</b>이었습니다. "
                    f"엔진이 구간을 통째로 막고 있습니다 (라운드 63). "
                    f"위 값은 <b>가격 조건만</b> 본 숫자라, 도달해도 "
                    f"매수 신호로 바뀌지 않습니다.")
            elif _gap_fv >= 3.0:
                rec_buy_sub = (
                    f"가치로 보면 아직 싸지 않습니다 — 적정가 "
                    f"{_fair:,.0f}원보다 {_gap_fv:+.1f}% 위입니다. "
                    f"타이밍으로는 이 값 아래부터 해 볼 만합니다.")
                rec_buy_more = (
                    f"<b>두 가격은 다른 질문에 답합니다.</b><br>"
                    f"· 적정가 {_fair:,.0f}원 = <b>얼마면 싼가</b> "
                    f"(재무·업종 기반 장기 가치)<br>"
                    f"· 위 값 = <b>지금 장세에서 어디부터 들어갈 만한가</b> "
                    f"(추세·변동성 기준)<br><br>"
                    f"위 값의 근거는 기준가에서 20일 변동성 하루치를 뺀 "
                    f"자리이고, 20봉 안에 실제로 체결된 비율을 실측해 "
                    f"정했습니다. 적정가까지 내려오길 기다리는 것은 "
                    f"<b>가치 매수</b>, 위 값에서 들어가는 것은 "
                    f"<b>타이밍 매수</b>입니다 — 둘 다 맞을 수 있습니다.")
            elif _gap_fv <= -3.0:
                rec_buy_sub = (
                    f"가치로 봐도 싼 자리입니다 — 적정가 {_fair:,.0f}원보다 "
                    f"{_gap_fv:+.1f}% 아래입니다.")
                rec_buy_more = (
                    f"타이밍 기준과 가치 기준이 <b>같은 방향</b>을 "
                    f"가리킵니다. 드문 자리지만 그것만으로 안전하지는 "
                    f"않습니다 — 적정가를 얼마나 믿을 수 있는지(신뢰도)와 "
                    f"거래량이 충분한지를 함께 보세요.")
            else:
                rec_buy_sub = (
                    f"적정가({_fair:,.0f}원)와 거의 같은 자리입니다 "
                    f"({_gap_fv:+.1f}%).")
                rec_buy_more = (
                    f"<b>얼마면 싼가</b>(가치)와 <b>어디부터 들어갈 만한가</b>"
                    f"(타이밍)가 겹치는 자리입니다. 두 기준이 서로 다른 값을 "
                    f"말할 때가 많은데, 지금은 같은 곳을 가리킵니다.")
            if _value_floor and abs(_value_floor / _core_entry - 1.0) >= 0.10:
                rec_buy_more += (
                    f"<br><br><b>장기 안전마진선 {_value_floor:,.0f}원</b>은 "
                    f"따로 있습니다 — 가치가 확실히 싸지는 자리지만 20일 "
                    f"안에 닿을 값이 아니라, 오늘의 매수가로는 쓰지 "
                    f"않습니다.")
        elif _value_floor and abs(_value_floor / _core_entry - 1.0) >= 0.10:
            rec_buy_sub = "장기 가치 참고선은 따로 있습니다"
            rec_buy_more = (
                f"장기 가치 참고선은 <b>{_value_floor:,.0f}원</b>입니다. "
                f"다만 20일 안에 닿을 자리가 아니라 오늘의 매수가로는 쓰지 "
                f"않습니다 — 위 값이 오늘 기준입니다.")
    elif _value_floor:
        rec_buy_sub = "적정가 기반 장기 참고선입니다"
        rec_buy_more = ("변동성으로 계산하는 오늘의 진입가를 만들지 못해, "
                        "대신 장기 가치 기준선을 보여 드립니다. 성격이 "
                        "다른 값이므로 '오늘 여기서 사라'는 뜻이 "
                        "아닙니다.")
elif _er_price:
    rec_buy_display = f"{_er_price:,.0f}원 부근"
    _er_why = ("모델 범위 밖" if four_scores.get('fair_value_status') == 'OUT_OF_DOMAIN'
               else "적정가 신뢰도 미달")
    rec_buy_sub = "차트 지지선만 보고 잡은 값입니다 — 가치 검증은 없습니다"
    rec_buy_more = (f"근거: {_er_basis}<br>적정가로 한 번 더 검증하지 "
                    f"못했습니다 ({_er_why}). 가격이 싼지 비싼지는 이 "
                    f"값으로 알 수 없습니다.")
elif four_scores.get('fair_value_status') == 'OUT_OF_DOMAIN':
    # 성장 기대가 가격을 지배하는 종목 — 신뢰도 문제가 아니라 모델이 성립하지 않는다
    rec_buy_display = "산출 불가 (모델 범위 밖)"
    rec_buy_sub = "기준을 만들 수 없습니다 — 현재가 아래 지지선도 없습니다"
    rec_buy_more = ("실적보다 성장 기대가 가격을 지배하는 종목이라 "
                    "적정가 모델이 성립하지 않습니다. 값이 틀린 것이 "
                    "아니라 <b>낼 수 없다</b>는 뜻입니다 — 없는 값을 "
                    "지어내지 않습니다.")
else:
    rec_buy_display = "신뢰도 미달"
    rec_buy_sub = "근거가 생길 때까지 관망 — 현재가 아래 지지선이 없습니다"
    rec_buy_more = ("기댈 지지선도, 믿을 만한 적정가도 없습니다. "
                    "이럴 때 숫자를 만들어 주면 근거 없는 값이 실행 "
                    "가격처럼 보입니다.")
# 주의: f-string 템플릿 안에 조건부로 '빈 줄'을 남기면 markdown 이 이어지는
# HTML 을 코드 블록으로 렌더한다 — 반드시 앞 요소와 같은 줄에 붙인다.
_rec_sub_html = (f"<p style='margin:4px 0 0 0; font-size:12px; "
                 f"color:#9DAABC; line-height:1.6;'>{rec_buy_sub}</p>"
                 if rec_buy_sub else "")
_ex_tgt = fmt_num(four_scores.get('target_tech_1st'), suffix='원', na='산출 불가')
_ex_stop = fmt_num(four_scores.get('stop_loss_price'), suffix='원', na='산출 불가')

# 권장 매수가에 샀을 때의 레벨. 위 두 값은 **현재가** 기준이라, 아직 안 산
# 사람에게는 맞지 않는다. 실측(라운드 22b · 30종목)에서 권장 매수가가 나온
# 17종목 중 11종목(65%)의 손절가가 매수가보다 위였다 — 최대 +193%.
# 그래서 진입가 기준 레벨을 따로 계산해 살 가격 칸 밑에 붙인다.
# 라운드 37: 중앙 판정이 정합 가드를 이미 통과시킨 값만 쓴다. 어긋난 값은
# CORE 가 None 으로 비워 두므로, 여기서 다시 그리지 않는다.
_e_stop = (CORE or {}).get('new_stop')
_e_t1 = (CORE or {}).get('new_target')
_e_rr = (CORE or {}).get('rr')
_entry_lv_html = ''
_entry_lv_more = ''
if _e_stop and _e_t1:
    _entry_lv_html = (
        f"<p style='margin:6px 0 0 0; font-size:12px; color:#9DAABC; "
        f"line-height:1.6;'>이 가격에 사면 → 손절 "
        f"<b style='color:#ff453a;'>{_e_stop:,.0f}원</b> · 1차 목표 "
        f"<b style='color:#4C8DFF;'>{_e_t1:,.0f}원</b>"
        + (f" · 손익비(진입가·1차) <b>{_e_rr}:1</b>" if _e_rr else '')
        + "</p>")
    # 손익비를 '원'으로 풀어 준다. 비율만 보면 0.7:1 이 좋은지 나쁜지
    # 감이 안 온다. 두 값 모두 CORE 가 낸 것이라 화면과 어긋날 수 없다 (§4).
    # 표시 진입가가 CORE 진입가일 때만 뺄셈한다 — 폴백(_value_floor)이면
    # 손익비와 기준이 달라져 숫자가 서로 안 맞는다.
    if _core_entry and _e_rr:
        _risk = _core_entry - _e_stop
        _rewd = _e_t1 - _core_entry
        if _risk > 0 and _rewd > 0:
            # 라운드 161 — "그만큼 적중률이 높아야 본전"까지만 적고 **그
            # 수를 안 적고 있었다.** 얼마나 높아야 하는지가 핵심인데
            # 읽는 사람이 계산할 수 없다. 숫자를 넣는다.
            _be_more = _uk.breakeven_hit_rate(
                _core_entry, _e_stop, _e_t1, q_engine.TOTAL_COST_PCT)
            _entry_lv_more = (
                f"<b>손익비(진입가·1차) {_e_rr}:1 이 무슨 뜻이냐면</b> — "
                f"이 가격에 "
                f"사면 손절까지 <b>{_risk:,.0f}원</b>을 감수하고 1차 "
                f"목표까지 <b>{_rewd:,.0f}원</b>을 노리는 자리입니다. "
                f"1보다 작으면 <b>잃을 폭이 벌 폭보다 큽니다</b> — 그만큼 "
                f"적중률이 높아야 본전입니다."
                + (f" 거래비용 {q_engine.TOTAL_COST_PCT}% 까지 넣으면 "
                   f"<b>열 번 중 {_be_more['pct'] / 10:.1f}번</b>"
                   f"(<b>{_be_more['pct']:.1f}%</b>) 이상 맞아야 본전입니다."
                   if _be_more else ''))

# ── 도달 가능성 · 논리 검사 ──────────────────────────────────────────────
# "권장 매수가가 현실적으로 닿는 가격인가"를 σ 로 재서 말로 옮긴다.
# 안 적으면 현재가의 절반인 값이 실행 가격처럼 보인다.
# 라운드 37 — 이 σ 표기는 **화면에 실제로 뜬 매수가**를 기준으로 해야 한다.
# 엔진의 rec_buy_sigma 는 적정가 기반 값(147,560원) 기준이라, 배너가
# 228,287원을 보여 주면서 "−41.0% · 1.05σ · 멀다"라고 말하는 어긋남이 났다.
_rc_sig = (CORE or {}).get('depth_sigma')
_rc_drop = (CORE or {}).get('gap_pct')
# 라운드 190 — 위 배수와 **같은 단위**의 σ (하루). 화면 문장이 이 둘을
# 곱해 읽히므로 출처가 어긋나면 안 된다 (§4).
_core_vol20 = (CORE or {}).get('vol_20')
if _rc_sig is None:                       # 중앙 판정이 못 낸 경우만 폴백
    _rc_sig = four_scores.get('rec_buy_sigma')
    _rc_drop = four_scores.get('rec_buy_drop_pct')
    _rc_reach = four_scores.get('rec_buy_reach')
else:
    _rc_reach = ('가까움' if _rc_sig <= 0.5 else
                 '닿을 만함' if _rc_sig <= 1.0 else
                 '멀다' if _rc_sig <= 2.1 else '사실상 도달 어려움')
_t1_sig = four_scores.get('target1_sigma')
_t1_reach = four_scores.get('target1_reach')
_sig_pct = four_scores.get('horizon_sigma_pct')
_fair_v = four_scores.get('displayed_fair_value')
_gap_fair = ((realtime_price / _fair_v - 1) * 100
             if (_fair_v and realtime_price) else None)

#: 도달이 어려우면 '실행 가격'이 아니라 '관찰 대상'이다 — 강조를 낮춘다
_rec_is_far = bool(_rc_sig is not None and _rc_sig > 2.0)

_reach_html = ''
_reach_more = ''
if _rc_sig is not None:
    _rc_col = '#F2B84B' if _rec_is_far else '#9DAABC'
    # 표면은 사람 말로만 — σ 같은 기호는 아래 '자세히'로 내린다 (라운드 79).
    _reach_word = {'가까움': '금방 닿을 거리입니다',
                   '닿을 만함': '20일 안에 닿을 만한 거리입니다',
                   '멀다': '20일 안에 닿기는 쉽지 않습니다',
                   '사실상 도달 어려움': '20일 안에 닿기 어렵습니다',
                   }.get(str(_rc_reach), str(_rc_reach))
    _reach_html = (
        f"<p style='margin:6px 0 0 0; font-size:12px; color:{_rc_col}; "
        f"line-height:1.6;'>지금보다 <b>{abs(_rc_drop):.1f}% "
        f"{'아래' if _rc_drop < 0 else '위'}</b> — {_reach_word}"
        + ("<br><b>지금은 매수 후보가 아니라 지켜볼 종목입니다.</b> "
           "계산된 매수가가 너무 멀어 곧 내려올 가능성이 낮습니다."
           if _rec_is_far else '')
        + "</p>")
    # ⚠️ 라운드 190 — 이 문장이 **단위가 다른 두 값을 곱해** 읽히고 있었다.
    #   `_sig_pct`(horizon_sigma_pct)는 **20봉 σ**(하루 σ×√20)인데
    #   `_rc_sig`(depth_sigma)는 **하루 σ 배수**다. "20일 보통 13.4%
    #   움직이는데 매수가까지 2.23배" 라고 적으면 29.9% 라는 뜻이 되지만
    #   실제 거리는 6.7% 다 — **√20 ≈ 4.47배 어긋난다**(실측:
    #   _probe/r190_sigma.py). 판정이 쓰는 자(2.1σ · 라운드 35)가 하루 σ
    #   이므로 **문장도 하루 σ 로 맞춘다.** 문턱은 안 건드린다.
    _day_sig_pct = ((_core_vol20 or 0) * 100.0) if _core_vol20 else None
    _reach_more = (
        f"<b>'닿을 만하다'를 어떻게 재나</b> — 이 종목은 <b>하루</b>에 보통 "
        + (f"<b>{_day_sig_pct:.1f}%</b>" if _day_sig_pct else "얼마나")
        + f"쯤 움직입니다. 위 매수가까지는 그 <b>하루 움직임의 "
        f"{_rc_sig}배</b>({_rc_sig}σ) 거리입니다.<br>"
        f"1배 안쪽이면 흔한 하루 움직임, 2.1배를 넘으면 20일 안에 닿을 "
        f"확률이 60% 아래로 떨어집니다(라운드 35 실측 · n=5,389). "
        f"그래서 '{_rc_reach}'로 적었습니다 — 종목마다 평소 움직임이 "
        f"다르므로 <b>%가 아니라 배수로</b> 잽니다."
        + (f"<br>참고로 20거래일 전체로는 보통 <b>{_sig_pct}%</b>쯤 "
           f"움직입니다(하루 σ×√20)." if _sig_pct else ''))

# 논리 검사 — 사용자가 요청한 조건을 자동으로 걸고, 어긋나면 화면에 적는다
_logic_warn = []
if _e_t1 and rec_buy_val and _e_t1 <= rec_buy_val:
    _logic_warn.append('신규 목표가가 매수가보다 낮거나 같습니다')
if _e_stop and rec_buy_val and _e_stop >= rec_buy_val:
    _logic_warn.append('신규 손절가가 매수가보다 높거나 같습니다')
if _e_rr is not None and _e_rr < 1.0:
    _logic_warn.append(
        f'신규 진입 손익비(진입가·1차)가 {_e_rr}:1 로 1:1 에 '
        f'못 미칩니다 '
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

# _NA · CORE 는 결론 배너보다 앞(4326행 부근)에서 이미 만들었다.
# 배너가 실행 가격을 CORE 에서 받아 쓰기 때문이다.

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
# 라운드 193 — 이 칸이 `_NA['headline']` 을 **그대로** 그리고 있었다.
#   next_action 은 가격 거리만 보고 게이트를 모른다. 그래서 같은 화면이
#   "분할매수할 수 있습니다"(이 칸)와 "쫓아가지 마세요"(지시서)를 함께
#   말했다 — 25종목 중 20종목에서 어긋났고 그중 11종목은 actionable=False.
#   결론 문장은 중앙 판정이 정한다(§4). 조건 목록·가격선은 그대로 쓴다.
_na_head = str(CORE.get('next_headline') or _NA.get('headline') or '')
_na_kind = str(CORE.get('next_kind') or _NA.get('kind') or '')
if _na_head:
    _na_col = {'buy_now': '#35C98B', 'pullback': '#F2B84B',
               'breakout': '#4C8DFF', 'blocked': '#ff453a'}.get(
                   _na_kind, '#9DAABC')
    # 라운드 197 — 조건 목록도 중앙 판정에서 받는다. 막힌 화면에서
    #   next_action 의 buy_now 조건 한 줄("거의 닿았습니다")만 남으면
    #   그 칸이 **무엇을 기다리는지** 말하지 못한다.
    _na_items = ''.join(
        f"<li style='margin:4px 0;'>{_uk._esc(c['text'])}</li>"
        for c in (CORE.get('next_conditions')
                  if CORE.get('next_conditions') is not None
                  else _NA.get('conditions', [])))
    _na_html = (
        f"<div style='margin-top:14px; background:#1C2635; border-radius:12px; "
        f"padding:12px 16px;'>"
        f"<p style='margin:0 0 2px 0; font-size:12px; color:#9DAABC; "
        f"font-weight:700;'>다음 조건 — 언제 사면 되나</p>"
        f"<p style='margin:0 0 6px 0; font-size:17px; font-weight:700; "
        f"color:{_na_col}; line-height:1.4;'>{_uk._esc(_na_head)}</p>"
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
        _dm_line = (f"{_dme['trigger_line']:,.0f}원이 무너지지 않는 동안만 "
                    f"유효합니다"
                    if _dme.get('valid') else
                    f"{_dme['trigger_line']:,.0f}원이 무너져 이 신호는 "
                    f"무효입니다")
    elif _dm_state in ('COMPLETE', 'SETUP_DONE', 'FORMING'):
        _dm_line = "받쳐 주는 선을 산출하지 못했습니다"
    else:
        _dm_line = str(_dme.get('detail', ''))[:60]
    _dm_more = (
        "<b>이게 무슨 신호인가</b> — 하락이 계속되면 파는 힘이 점점 "
        "빠집니다. 그 지친 정도를 9봉까지 세는 것이 DeMARK 셋업입니다. "
        "9까지 차면 <b>하락이 멈출 자리</b>로 봅니다.<br>"
        "'몇/9'는 지금 몇 번째인지이고, 아래 가격은 <b>이 신호가 살아 "
        "있으려면 지켜야 하는 선</b>입니다. 그 선이 무너지면 세던 것을 "
        "버립니다.<br><br>"
        "이건 <b>가격이 아니라 시점</b> 신호입니다 — 위의 매수가(가격 "
        "기준)와 같이 볼 때만 뜻이 있습니다.")
else:
    _dm_head, _dm_line = "산출 불가 (데이터 부족)", "DeMARK 신호를 만들지 못했습니다"
    _dm_more = ("봉 수가 모자라거나 시세를 다 받지 못해 셋업을 셀 수 "
                "없었습니다. 신호가 없다는 뜻이 아니라 <b>재지 못했다</b>는 "
                "뜻입니다.")

st.markdown('<div id="nav-verdict"></div>', unsafe_allow_html=True)
# 헤드라인만으로는 '조건부'가 안 보인다 — 신규 매수자용 쉬운 결론 한 줄을
# 배너 안에 병기해, "지금은 사지 마세요"가 '31,665원 이하로 내려오면 산다'는
# 조건부인지 완전 회피인지 배너에서 바로 구분되게 한다.
try:
    _easy_nb_banner = q_engine.build_easy_advice(
        four_scores, verdict, realtime_price,
        user_avg=None, user_qty=None)['new_buyer']
    _banner_sub = str(_easy_nb_banner.get('line') or '')
    # 라운드 37 — 이 문장은 엔진의 옛 권장 매수가(적정가 × 안전마진)로
    # 만들어진다. 배너 본문은 이미 중앙 판정의 실행 진입가를 보여 주므로,
    # 제목만 옛 값을 말하면 같은 카드 안에서 두 가격이 싸운다
    # (실측: 제목 147,560원 vs 본문 228,287원). 실행 가격으로 다시 쓴다.
    if '이하로 내려올 때만' in _banner_sub and _core_entry:
        _banner_sub = (f"{_core_entry:,.0f}원 이하로 내려올 때만 사세요. "
                       f"(현재가 {realtime_price:,.0f}원은 조건 위)")
    elif '이하로 내려올 때만' in _banner_sub:
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
# 라운드 161 — 적중률만 크게 보여 주면 그 수가 좋은지 나쁜지 알 수 없다.
# 다날(064260)에서 60% 가 이미 마이너스였다(본전 61.2%). **본전 적중률을
# 바로 밑에 같이 놓는다.** 계산은 ui_kit 한 곳에 있고(§4), 진입·손절·목표는
# CORE 값을, 비용은 채택값(TOTAL_COST_PCT)을 그대로 쓴다 — 새 숫자 없음.
_be_banner = _uk.breakeven_hit_rate(
    _core_entry, _e_stop, _e_t1, q_engine.TOTAL_COST_PCT)
if (_cb_banner.get('hit_rate') is not None
        and (_cb_banner.get('n') or 0) >= 30):
    _prob_html = (
        f"<p style='margin:8px 0 0 0; font-size:12px; color:#9DAABC;'>"
        f"비슷했던 과거에서 맞은 비율</p>"
        f"<p style='margin:0; font-size:28px; font-weight:700; "
        f"color:#F3F6FA; line-height:1.1;'>{_cb_banner['hit_rate']:.0f}%"
        f"<span style='font-size:13px; color:#9DAABC;'> "
        f"(n={_cb_banner['n']:,} · W하한 "
        f"{fmt_num(_cb_banner.get('wilson_low'), '.0f', '%', na='—')})</span></p>"
        + _uk.breakeven_row(_be_banner, _cb_banner['hit_rate'],
                            theme=_theme))
elif _cb_banner:
    _prob_html = (
        f"<p style='margin:8px 0 0 0; font-size:12px; color:#F2B84B;'>"
        f"실측 확률 표본 부족 (n={_cb_banner.get('n', 0)}) — 표시 보류</p>")
else:
    _prob_html = ""
# ── 눌러서 펼치는 상세 (라운드 79) ──────────────────────────────────────
# 사용자 요청: "이런 내용 좋다 조금만 더 쉽게 써주고 클릭하면 더 자세히
# 보이게 해줘." 그래서 근거를 **지우지 않고 접는다** — 표면에는 한 문장,
# 눌러야 수치·σ·라운드 번호가 나온다. 근거를 없애면 §9 가 깨진다.
#
# 조각마다 따로 접으면 카드가 아코디언 밭이 된다. 매수 칸은 **하나로**
# 묶고, 타이밍 신호만 따로 둔다 (질문이 다르다 — '얼마에'와 '언제').
_buy_more_parts = [x for x in (rec_buy_more, _reach_more, _entry_lv_more) if x]
_buy_more_html = (
    _uk.disclose('왜 그런가 · 자세히',
                 "<hr style='border:none; border-top:1px solid #263041; "
                 "margin:10px 0;'>".join(_buy_more_parts))
    if _buy_more_parts else '')
_dm_more_html = (_uk.disclose('이 신호가 뭔가 · 자세히', _dm_more)
                 if _dm_more else '')

st.markdown(f"""
<style>
/* 눌러서 펼치는 상세 (라운드 79) — ui_kit.disclose 가 그리는 요소.
   카드 HTML 과 같은 덩어리에 넣어 둔다: 다른 곳의 <style> 순서에
   기대지 않게 하려는 것이다. 기본 삼각형 마커는 브라우저마다 모양이
   달라 지우고 Lucide 셰브런만 쓴다 (§5 — 아이콘 한 세트).

   주의 — 반드시 `.gn-disc` 안에서만 칠한다. 서버를 띄워 보니 Streamlit 의
   st.expander 도 DOM 에서 <details> 였다 — 요소로만 스코프를 잡았더니
   화면의 확장 패널 69개(자산·통화 확인 · 상세 설정 · 제외 사유 …)의
   마커와 hover 가 같이 바뀌고 있었다. 회귀는 통과하는 종류의 결함이다.

   주의 — 그리고 class 는 <details> 에 못 단다. Streamlit 정화기가 지운다.
   ui_kit.disclose 가 바깥에 <div class='gn-disc'> 를 한 겹 씌우므로
   여기서도 그 div 를 타고 내려간다. */
.gn-disc > details > summary::-webkit-details-marker {{ display:none; }}
.gn-disc > details > summary::marker {{ content:''; }}
.gn-disc > details > summary:hover {{ filter:brightness(1.35); }}
.gn-disc > details > summary svg {{ transition:transform .18s ease; }}
.gn-disc > details[open] > summary svg {{ transform:rotate(180deg); }}
@media (prefers-reduced-motion: reduce) {{
  .gn-disc > details > summary svg {{ transition:none; }} }}
</style>
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
      <p style='margin:0; font-size:12px; color:#9DAABC;'>{'여기까지 오면 다시 볼 값' if _rec_blocked else '살 가격 · 이 값 이하에서'}</p>
      <p style='margin:2px 0 0 0; font-size:{'17' if _rec_is_far else '22'}px; font-weight:700;
                color:{'#9DAABC' if _rec_is_far else '#35C98B'};'>{rec_buy_display}</p>{_rec_sub_html}{_reach_html}{_entry_lv_html}{_buy_more_html}
      <p style='margin:14px 0 0 0; font-size:12px; color:#9DAABC;'>언제 사나 · 하락이 지치는 자리</p>
      <p style='margin:2px 0 0 0; font-size:15px; font-weight:700; color:{_dm_color}; line-height:1.3;'>{_dm_head}</p>
      <p style='margin:2px 0 0 0; font-size:12px; color:#9DAABC; line-height:1.6;'>{_dm_line}</p>{_dm_more_html}
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
    DeMARK 는 <b>시점</b> 신호이며 진입 기준가(<b>가격</b> 기준)와 함께 볼 때만 의미가 있습니다.</p>
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
# ⚠️ 키를 종목별로 가른다 — 사이드바와 같은 이유다 (라운드 51).
#    'pos_avg_main' 처럼 고정 키를 쓰면 종목을 바꿔도 값이 남는다.
_pkm = str(target_ticker or '').replace('.', '_')
_pos_default = 1 if user_entry_price > 0 else 0
_pos_mode = st.radio("이 종목을 갖고 계신가요?", ["아직 없음", "보유 중"],
                     index=_pos_default, horizontal=True,
                     key=f"pos_mode_{_pkm}")
# 라운드 199 — **어디서 끌어왔는지 밝힌다** (§3). 값이 저절로 채워지는데
#   출처가 안 보이면 사용자는 자기가 적은 값인지 알 수 없다.
if _auto_src and _auto_avg > 0:
    st.caption(f"{_auto_src}에 적어 두신 값으로 채웠습니다 — "
               f"평단 {_auto_avg:,}원"
               + (f" · {_auto_qty:,}주" if _auto_qty else "")
               + ". 아래에서 고치면 이 화면에만 적용됩니다.")
if _pos_mode == "보유 중":
    _pc1, _pc2 = st.columns(2)
    with _pc1:
        _main_avg = st.number_input(
            "평균 매수가 (원)", min_value=0,
            value=int(user_entry_price) if user_entry_price > 0 else 0,
            step=1000, key=f"pos_avg_{_pkm}",
            help="보유 판단에만 사용합니다 — 예측·적정가·점수에는 절대 반영되지 "
                 "않습니다. 종목마다 따로 기억합니다.")
    with _pc2:
        _main_qty = st.number_input(
            "보유 수량 (주)", min_value=0,
            value=int(user_quantity) if user_quantity > 0 else 0,
            step=10, key=f"pos_qty_{_pkm}")
    if _main_avg > 0:
        user_entry_price, user_quantity = _main_avg, _main_qty
else:
    user_entry_price, user_quantity = 0, 0

# ── 매매 지시서 (라운드 53) ────────────────────────────────────────────
# 사용자 지적: *"판단 점수만 보여주는 시스템에서 끝나면 부족합니다. 결국
# 그래서 지금 사야 하나, 몇 % 먹고 팔아야 하나, 손절은 어디인가, 보유자는
# 어떻게 해야 하나를 알고 싶습니다."*
#
# 값은 전부 중앙 판정(CORE)에서만 가져온다 — 지시서가 자기만의 가격을
# 만들면 화면마다 값이 달라진다 (CLAUDE.md §4).
# 평단이 확정된 **뒤에** 그린다. 보유자 지시가 평단을 쓰기 때문이다.
try:
    import trade_plan as _tp

    _mkt_state = None
    try:
        _kd = (q_engine.market_regime_ctx or {})
        _mkt_state = _tp.market_state(
            _kd.get('price'), _kd.get('sma20'), _kd.get('sma60'),
            _kd.get('sma60_prev'))
    except Exception:                                        # noqa: BLE001
        _mkt_state = None

    _plan = _tp.build(CORE, four_scores,
                      avg=(user_entry_price if user_entry_price > 0 else None),
                      qty=(user_quantity if user_quantity > 0 else None),
                      market=_mkt_state)
    st.markdown(_uk.trade_plan_card(_plan, name=resolved_name, theme=_theme),
                unsafe_allow_html=True)
except Exception:                                            # noqa: BLE001
    # 지시서 하나 때문에 분석 화면이 죽지 않는다. 못 그리면 안 그린다.
    pass

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
      <p style='margin:8px 0; font-size:17px; font-weight:700; color:#F3F6FA;'>{_uk._esc_md(_nb['line'])}</p>
      <p style='margin:0; font-size:15px; color:#9DAABC; line-height:1.55;'>{_uk._esc_md(_nb['detail'])}</p>
    </div>""", unsafe_allow_html=True)
with _ec2:
    _hd = _easy['holder']
    if _hd:
        st.markdown(f"""
        <div style='background:#161D2A; border-radius:14px; padding:16px 16px; height:100%;'>
          <p style='margin:0; font-size:12px; color:#9DAABC; font-weight:700;'>이미 갖고 계신 분께 (평단 {user_entry_price:,.0f}원 · 현재 {_hd['ret_pct']:+.1f}%)</p>
          <p style='margin:8px 0; font-size:17px; font-weight:700; color:#F3F6FA;'>{_uk._esc_md(_hd['line'])}</p>
          <p style='margin:0; font-size:15px; color:#9DAABC; line-height:1.55;'>{_uk._esc_md(_hd['detail'])}</p>
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
# ⚠️ 라운드 187 — '자본의 20% 이내' 라는 비중 제안이 **추천하지 않는
#   종목에도** 붙어 있었다. 사용자 지적: 신규 매수를 권하지 않으면서
#   얼마나 사라고 적으면 그 자체가 매수 지시로 읽힌다. 실제로 결론이
#   '추천 제외'인 화면 바로 아래 줄이 이 문장이었다.
#   → **추천 조건을 통과했을 때만** 낸다. 판정은 새로 만들지 않고
#     중앙 판정의 `recommended` 를 그대로 읽는다 (§2-6 · R186 과 같은 자).
#   → 다만 **조용히 감추지 않는다** (§3) — 왜 안 내는지 적는다.
_pos_sug = four_scores.get('suggested_position_pct')
if _pos_sug and CORE.get('recommended'):
    _extra_bits.append(f"변동성 관리 비중 제안: 자본의 **{_pos_sug:.0f}% 이내** "
                       f"({four_scores.get('suggested_position_basis', '')})")
elif _pos_sug:
    _extra_bits.append(
        "변동성 관리 비중 제안은 **표시하지 않습니다** — 이 종목은 오늘 "
        "추천 필수조건을 통과하지 못했습니다. 얼마나 살지는 살 만한 자리일 "
        "때만 말합니다.")
_rm = four_scores.get('rel_mom_detail')
if _rm and _rm.get('relative') is not None:
    _extra_bits.append(f"상대 모멘텀(12-1): **{_rm['relative']:+.1f}%p** "
                       f"(종목 {_rm['stock']:+.1f}% vs {_rm['market']} {_rm['index']:+.1f}%)")
_tr = four_scores.get('track_record')
if _tr and _tr.get('hit_rate') is not None:
    _extra_bits.append(f"실전 판정 적중률 **{_tr['hit_rate']:.0f}%** "
                       f"({_tr.get('decided', 0)}건 판정 완료 — 점수 확신에 반영)")
_cb = four_scores.get('calibration_band')
if _cb and _cb.get('hit_rate') is not None and _cb.get('n', 0) >= 5:
    _extra_bits.append(
        f"가상 백테스트: 이 점수대({_cb['lo']}~{_cb['hi']}점)의 과거 리플레이 적중률 "
        f"**{_cb['hit_rate']:.0f}%** (n={_cb['n']}, Wilson 하한 {_cb['wilson_low']:.0f}%)")
elif _cb and _cb.get('n', 0) < 5:
    _extra_bits.append(f"이 점수대({_cb['lo']}~{_cb['hi']}점) 리플레이 표본 "
                       f"{_cb.get('n', 0)}건 — 표본 부족으로 적중률 미표시")
# 계층 보정 확률(R59)·국면 — 배너·고정 패널·가늠 AI 타일·대화가 전부
# 이 두 값을 읽는다. 한 번만 계산해 네 곳이 같은 숫자를 말하게 한다 (§4).
_rg58 = None
try:
    # 라운드 214 — 관심종목의 포트폴리오 견해와 **같은 함수**로 한 번만 받는다 (§4)
    _ms58 = _market_state_214()
    _rg58 = (_ms58 or {}).get('code')
except Exception:                                              # noqa: BLE001
    pass
_blend59 = None
try:
    import case_layers as _cl59
    _blend59 = _cl59.blended_prob(
        verdict.get('score'), sector=val_eval.get('sector'),
        regime_code=_rg58, fs=four_scores)
except Exception:                                              # noqa: BLE001
    pass
if _blend59:
    _extra_bits.append(
        f"계층 보정 확률 약 {_blend59['p'] * 100:.0f}% "
        f"[{_blend59['wilson_low'] * 100:.0f}~"
        f"{_blend59['wilson_high'] * 100:.0f}%] · R59")

# ⚠️ 엔진 인스턴스 속성은 스냅샷이 캐시에서 오면 비어 있다 — 파일을 직접 읽는다
_calib_all = _load_calibration_meta()
if _calib_all.get('total_cases'):
    # 라운드 217 — R198 이 '원장 행수(ledger_rows)'로 세기로 하고 사이드바·홈
    #   카드는 고쳤는데 **여기와 모델 성적 캡션은 total_cases 그대로**였다.
    #   그래서 헤더가 '누적 케이스 249,748건' 옆에 '원장 250,725건 기준'을
    #   띄웠다 — 같은 줄 안에서 두 수. 같은 우선순위(:753)로 맞춘다.
    _extra_bits.append(f"모델 {_calib_all.get('rulebook_version', '')} · "
                       f"누적 케이스 {_calib_all.get('ledger_rows') or _calib_all['total_cases']:,}건")
    # 유효 독립 표본 (라운드 54b) — 같은 날 같은 업종 신호는 같은 시장
    # 사건 하나다. raw 건수로 신뢰구간을 좁히면 과신이 된다.
    try:
        import json as _json54
        # 라운드 217 — 종전에는 R54b 의 `effective_n.json` 을 읽었다. 그 파일은
        #   생성 스크립트가 없는 고정본이라(2026-08-09 · 원장 60,462행 · 32,721)
        #   '누적 케이스 250,725건' 옆에 4배 작은 원장의 수가 날짜 없이 서
        #   있었다. 같은 정의(④ 같은 종목 35일 에피소드)를 라운드 72 표본
        #   감사(`scripts/sample_audit.py` → sample_audit.json)가 세므로 그것을
        #   읽고, 기준 행수와 잰 날짜를 같이 낸다 — 낡으면 낡은 것이 보이게(§2).
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               'data', 'sample_audit.json'),
                  encoding='utf-8') as _f54:
            _sa54 = _json54.load(_f54)
        _en54_made = str(_sa54.get('made') or '날짜 미기록')[:10]
        if _sa54.get('independent_episodes'):
            _extra_bits.append(
                f"유효 독립 표본 약 {int(_sa54['independent_episodes']):,}건"
                f" (같은 종목 {int(_sa54.get('episode_days') or 35)}일 내 재신호를 "
                f"한 사건으로 묶음 · "
                f"원장 {int(_sa54.get('raw_cases') or 0):,}건 기준 · {_en54_made})")
    except Exception:                                          # noqa: BLE001
        pass                          # 표기 하나 때문에 화면이 죽지 않는다
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
/* 라운드 122 — 패널의 각 줄에서 본문 해당 절로 갈 수 있게 한다.
   종전에는 숫자만 있고 길이 없어, 왼쪽 메뉴와 오른쪽 패널이 서로를
   모르는 상태였다. 색을 새로 만들지 않고 링크는 글자색을 물려받는다. */
.qside td a {{ color: inherit; text-decoration: none;
  border-bottom: 1px dotted {_TOK['tx3']}; }}
.qside td a:hover {{ color: {_TOK['brand']}; }}
/* 화면이 길어지면 패널이 아래로 넘친다 — 스스로 스크롤하게 두고
   오른쪽 아래 '가늠 AI' 버튼과 겹치지 않게 아래를 비운다. */
.qside {{ max-height: calc(100vh - 200px); overflow-y: auto; }}
@media (max-width: 1760px) {{ .qside {{ display: none; }} }}
</style>
<!-- 라운드 53c — 이 고정 패널이 '진입 검토가'로 recommended_buy_price 를,
     '1차 목표가'·'손절가'로 보유자 값을 이름표 없이 싣고 있었다. 화면 오른쪽에
     항상 붙어 있는 요약이라 배너와 다른 숫자가 나란히 보였다. 전부 CORE 로. -->
<div class="qside">
  <p class="act">{verdict['headline']}</p>
  <table>
    <tr><td><a href="#nav-verdict">종합점수</a></td><td>{verdict['score']}점</td></tr>
    <tr><td><a href="#nav-top">현재가</a></td><td>{realtime_price:,.0f}{unit_str}</td></tr>
    <tr><td><a href="#nav-basis">실행 진입가</a></td><td>{fmt_num((CORE or {}).get('pullback_zone'), ',.0f', unit_str, na='산출 불가')}</td></tr>
    <tr><td><a href="#nav-basis">1차 목표 · 신규</a></td><td>{fmt_num((CORE or {}).get('new_target'), ',.0f', unit_str, na='산출 불가')}</td></tr>
    <tr><td><a href="#nav-basis">손절 · 신규</a></td><td>{fmt_num((CORE or {}).get('new_stop'), ',.0f', unit_str, na='산출 불가')}</td></tr>
    <tr><td><a href="#nav-basis">분석 신뢰도</a></td><td>{fmt_num(_sum_conf, '.0f', '점', na='미산출')}</td></tr>
    <tr><td><a href="#nav-perf">계층 보정 확률</a></td><td>{(f"약 {_blend59['p'] * 100:.0f}%" if _blend59 else '미산출')}</td></tr>
    <tr><td><a href="#nav-perf">이 점수대 원실측</a></td><td>{_sum_band}</td></tr>
  </table>
  <p style='margin:8px 0 0 0;'><a href='#nav-ask' class='gn-ask-open-link'
  style='font-size:12px;
  color:#4C8DFF; text-decoration:none;'>가늠 AI에게 물어보기 →</a></p>
</div>
""", unsafe_allow_html=True)

# ── 떠 있는 '가늠 AI' 버튼 (라운드 65) ────────────────────────────────
# 사용자 요청: "오른쪽에 계속 아이콘처럼 있고 누르면 물어볼 수 있게."
# Streamlit 은 입력 위젯을 고정 레이어에 넣을 수 없다 (위젯은 문서 흐름
# 안에서만 산다). 그래서 **버튼만 고정**하고 누르면 대화 칸으로 데려간다.
# 좁은 화면에서도 남으므로 고정 요약 패널(1760px 이상)과 달리 항상 뜬다.
st.markdown(f"""
<style>
/* 주의 — 글자를 **어둡게** 쓴다 (라운드 116). 브랜드 파랑은 밝은 축이라
   그 위의 흰 글자가 3.36:1 밖에 안 나온다(AA 4.5 미달 — 실측 2.81).
   더 어두운 파랑을 새로 만드는 것은 §5 가 금지하므로("화면 어디서도 새
   색을 만들지 않는다") 글자를 배경 토큰으로 뒤집는다 → 5.86:1. */
.gn-ask-fab {{ position:fixed; right:18px; bottom:22px; z-index:9990;
  display:flex; align-items:center; gap:8px; padding:11px 15px;
  border-radius:999px; background:{_TOK['brand']}; color:{_TOK['bg1']};
  font-size:13px; font-weight:700; text-decoration:none;
  box-shadow:0 6px 20px rgba(0,0,0,.35); }}
.gn-ask-fab * {{ color:{_TOK['bg1']} !important; }}
.gn-ask-fab svg {{ stroke:{_TOK['bg1']} !important; }}
/* 라운드 126 — 라이트 모드에서 이 버튼 글자가 브랜드 파랑 위에 tx1 로
   찍혀 **3.43:1** 이었다 (AA 4.5 미달). 클래스 규칙에 !important 가
   있었는데도 다른 규칙이 이겼다 — 다크에서는 tx1 이 밝아 우연히
   괜찮았고, **라이트에서만 드러나는 결함**이었다.
   특이도 싸움을 끝내려고 ID 로 올린다. 색은 팔레트에서 온다. */
#gn-ask-fab, #gn-ask-fab * {{ color:{_TOK['bg1']} !important; }}
#gn-ask-fab svg {{ stroke:{_TOK['bg1']} !important; }}
.gn-ask-fab:hover {{ filter:brightness(1.08); }}
.gn-ask-fab .gn-ask-t {{ display:inline; }}
@media (max-width: 640px) {{ .gn-ask-fab .gn-ask-t {{ display:none; }}
  .gn-ask-fab {{ padding:13px; right:14px; bottom:16px; }} }}

/* ── 알약과 입력바를 하나로 (라운드 76) ────────────────────────────────
   사용자 지적: "이거 두개 통합해달라니깐. 이걸 클릭하면 '이 종목에 대해
   무엇이든 물어보세요'가 뜨게 해주고 자연스럽게."
   종전에는 파란 알약과 하단 입력바가 **동시에** 떠서 알약이 입력바를
   덮고 있었다. 하나만 보이게 하고, 누르면 서로 자리를 바꾼다.

   주의 — 숨김은 `body.gn-ask-ready` 아래에서만 건다. 스크립트가 못 붙으면
      클래스가 안 생기므로 입력바가 **종전처럼 그대로 보인다** — 자바
      스크립트가 죽었다고 대화 자체를 못 하게 만들지 않는다. */
body.gn-ask-ready [data-testid="stBottom"] {{
  transition: transform .28s cubic-bezier(.2,.7,.3,1), opacity .2s;
  transform: translateY(115%); opacity: 0; pointer-events: none; }}
body.gn-ask-ready.gn-ask-open [data-testid="stBottom"] {{
  transform: none; opacity: 1; pointer-events: auto; }}
.gn-ask-fab {{ transition: transform .2s cubic-bezier(.2,.7,.3,1),
                            opacity .16s; }}
body.gn-ask-open .gn-ask-fab {{
  transform: scale(.72); opacity: 0; pointer-events: none; }}
@media (prefers-reduced-motion: reduce) {{
  .gn-ask-fab, body.gn-ask-ready [data-testid="stBottom"] {{
    transition: none; }} }}
</style>
<a class="gn-ask-fab" id="gn-ask-fab" href="#nav-ask"
   title="{_uk._esc(resolved_name)}에 대해 물어보기"
   aria-label="가늠 AI에게 물어보기">
  {_uk._icon('help', '#fff', 17)}
  <span class="gn-ask-t">가늠 AI</span>
</a>
""", unsafe_allow_html=True)

# ── 버튼을 눌렀을 때 **실제로 무언가 일어나게** 한다 (라운드 75) ──────────
#
# 종전에는 `href="#nav-ask"` 앵커뿐이었다. 그런데 Streamlit 본문은 창이
# 아니라 `.stMain` **안쪽에서 스크롤**된다. 브라우저의 앵커 이동은 바깥
# 창을 움직이므로 눌러도 화면이 그대로였다. 사용자가 이미 대화칸 근처에
# 있으면 더더욱 아무 일도 안 일어난 것처럼 보였다.
#
# st.markdown 은 <script> 를 지우므로 여기서 직접 JS 를 넣을 수 없다.
# 높이 0 짜리 components.html 을 하나 두고, 그 안에서 부모 문서의 버튼에
# 클릭 처리기를 붙인다. 버튼 자체는 부모에 그대로 둬야 화면 위에 뜬다
# (iframe 안의 fixed 는 부모를 덮지 못한다).
#
# 하는 일: ① 실제 스크롤 컨테이너를 찾아 대화칸까지 부드럽게 이동
#          ② 입력칸에 커서를 넣는다 — 누르자마자 바로 타이핑되게
#          ③ 잠깐 테두리를 밝혀 "여기다" 를 눈으로 보이게
try:
    import streamlit.components.v1 as _fabjs
    _fabjs.html(
        """
<script>
(function () {
  const D = window.parent && window.parent.document;
  if (!D) return;
  const fab = D.getElementById('gn-ask-fab');
  if (!fab || fab.dataset.gnBound === '1') return;
  fab.dataset.gnBound = '1';

  function scroller(el) {          // 진짜로 스크롤되는 조상을 찾는다
    let n = el.parentElement;
    while (n && n !== D.body) {
      const st = getComputedStyle(n);
      if ((st.overflowY === 'auto' || st.overflowY === 'scroll')
          && n.scrollHeight > n.clientHeight + 40) return n;
      n = n.parentElement;
    }
    return D.scrollingElement || D.documentElement;
  }

  // 입력바가 실제로 있을 때만 숨김 CSS 를 켠다. 없으면 켜 봐야 숨길
  // 것도 없고, 혹시 선택자가 바뀌면 애먼 것을 지운다.
  if (D.querySelector('[data-testid="stBottom"]')) {
    D.body.classList.add('gn-ask-ready');
  }

  function open_() {
    D.body.classList.add('gn-ask-open');
    // 애니메이션(0.28s)이 끝난 뒤 커서를 넣는다 — 올라오는 도중에 넣으면
    // 브라우저가 스크롤을 함께 흔든다.
    setTimeout(function () {
      const ta = D.querySelector('[data-testid="stChatInput"] textarea');
      if (ta) ta.focus();
    }, 300);
  }
  function close_() {
    D.body.classList.remove('gn-ask-open');
  }

  fab.addEventListener('click', function (e) {
    e.preventDefault();
    open_();
  });

  // 고정 요약 패널의 '가늠 AI에게 물어보기 →' 도 같은 동작을 해야 한다.
  // 입력바가 숨겨진 뒤로 그 링크만 옛 앵커로 남으면, 눌러서 대화 구역에
  // 가 놓고도 물어볼 칸이 없는 어긋난 상태가 된다.
  D.querySelectorAll('.gn-ask-open-link').forEach(function (a) {
    if (a.dataset.gnBound === '1') return;
    a.dataset.gnBound = '1';
    a.addEventListener('click', function () { open_(); });
  });

  // 닫는 길을 둔다 — 열기만 되고 못 닫으면 알약이 영영 안 돌아온다.
  D.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') close_();
  });
  D.addEventListener('mousedown', function (e) {
    if (!D.body.classList.contains('gn-ask-open')) return;
    const bar = D.querySelector('[data-testid="stBottom"]');
    if (bar && !bar.contains(e.target) && e.target !== fab
        && !fab.contains(e.target)) {
      close_();
    }
  });
})();
</script>
        """, height=0)
except Exception:                                          # noqa: BLE001
    # 스크립트를 못 붙여도 앵커(href)는 그대로 남아 있다 — 기능이 줄 뿐
    # 버튼이 사라지지는 않는다.
    pass

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
            f"{_uk._esc_md(_is['detail'])}</p></div>",
            unsafe_allow_html=True)
    if len(_issues_stock) > 3:
        with st.expander(f"전체 이슈 보기 ({len(_issues_stock)}건)",
                         expanded=False):
            st.dataframe(pd.DataFrame([{
                '중요도': i['severity'], '유형': i['type'], '제목': i['title'],
                '내용': i['detail'],
            } for i in _issues_stock]), width='stretch',
                hide_index=True)

# ── 국면 게이트 (라운드 27) ────────────────────────────────────────────
# 6칸 성적을 '모델 성적' 화면에만 두지 않고, 판단이 실제로 깎인 자리에서
# 그 사실과 근거를 같이 보여 준다. 안 깎였으면 아무 말도 하지 않는다.
_rg = four_scores.get('regime_gate') or {}
if _rg.get('cell') and (_rg.get('capped') or _rg.get('block_new')):
    _rg_lines = []
    if _rg.get('score_after') != _rg.get('score_before'):
        _rg_lines.append(f"- 종합점수 {_rg['score_before']}점 → "
                         f"**{_rg['score_after']}점** (국면 상한)")
    if _rg.get('conf_after') != _rg.get('conf_before'):
        _rg_lines.append(f"- 분석 신뢰도 {_rg['conf_before']} → "
                         f"**{_rg['conf_after']}** (국면 상한)")
    if (_rg.get('size_mult') or 1.0) < 1.0:
        _rg_lines.append(f"- 제안 비중 **{_rg['size_mult']:.1f}배**로 축소")
    if (_rg.get('stop_mult') or 1.0) < 1.0:
        _rg_lines.append(f"- 손절 폭 **{_rg['stop_mult']:.1f}배**로 축소 "
                         "(목표는 그대로 — 손실만 줄입니다)")
    _rg_body = _rg['why'] + ("\n\n" + "\n".join(_rg_lines) if _rg_lines else "")
    if _rg.get('block_new'):
        st.error(f"**이 국면에서는 신규 매수를 하지 않습니다** — {_rg_body}")
    else:
        st.warning(f"**국면별 제한을 적용했습니다 ({_rg['level']})** — {_rg_body}")

# ── 뉴스 게이트 (라운드 42) ──────────────────────────────────────────────
# 뉴스가 판단에 **실제로** 개입했으면 그 사실과 근거를 여기서 밝힌다.
# 개입하지 않았으면 아무 말도 하지 않는다.
_ng = four_scores.get('news_gate') or {}
if _ng.get('risk'):
    st.error(
        f"**악재로 신규 매수를 차단했습니다** — {_ng['why']}  \n"
        f"종합점수 {_ng['score_before']} → **{_ng['score_after']}** · "
        f"신뢰도 {_ng['conf_before']} → **{_ng['conf_after']}**  \n"
        f"수집 기사 {_ng.get('total', 0)}건 중 위험 낱말 {_ng['risk']}건 "
        f"(룰북 `RULES_NEWS` · 뉴스 엔진 "
        f"{_VER_NOW.get('news', '—')} · 룰북 {_VER_NOW.get('rulebook', '—')})")
elif _ng and not _ng.get('total'):
    st.caption(f"뉴스 게이트: {_ng.get('why', '')}")

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
    st.caption(f"적정가 괴리율 {float(_up_raw):+.1f}% 는 신뢰도 "
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
    # core=CORE 를 빼면 차트가 four_scores 로 물러서고, 그 순간 배너와 다른
    # 숫자를 그린다 (라운드 53에서 실제로 그러고 있었다). 반드시 넘긴다.
    _chart_html = _cp.build_chart_html(
        tech_df, four_scores, name=resolved_name, unit_str=unit_str,
        theme=st.session_state.get('ui_theme', 'dark'),
        user_avg=(user_entry_price if user_entry_price and user_entry_price > 0
                  else None),
        core=CORE)
    # st.components.v1.html 은 2026-06-01 제거 예정이었고 그 날짜가 이미
    # 지났다 — 스트림릿을 올리는 순간 차트가 통째로 사라진다. 같은 iframe
    # 임베드인 st.iframe 으로 바꾼다 (HTML 문자열도 그대로 받는다).
    # 이 HTML 은 우리가 만든 것이고 외부 입력을 넣지 않는다.
    st.iframe(_chart_html, height=880)
    st.caption("휠 확대·드래그 이동 · 상단 체크박스로 지표 켜고 끄기. "
               "가격선은 중앙 판정에서 그대로 받습니다 — 실선은 **신규 매수자** "
               "기준(실행 진입가·1차 목표·손절)이고, 점선은 참고선"
               "(2차 목표·펀더멘털 적정가·TDST)입니다. 평단을 입력하셨다면 "
               "**보유자** 기준 목표·손절이 파선으로 함께 그려집니다 — "
               "두 기준은 서로 다른 숫자이므로 이름표를 보고 구분해 주세요. "
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


# 목표 선도달 확률은 계층 혼합(R59 채택)으로 낸다 — valid 실측에서
# 현행 유사사례 확률(보정이탈 35.4%p)을 Brier·보정도 모두로 이겼고,
# 유사사례가 있는 행 부분집합에서도 우위였다. 손절/미결 확률은 혼합
# 모델이 예측하지 않으므로 종전대로 유사사례 표본 기준(미산출이면
# 미산출) — 아는 것과 모르는 것을 섞지 않는다.
# (_rg58 · _blend59 는 배너 앞에서 계산됨 — 고정 패널·배너·타일·대화가
#  같은 값을 읽는다 §4)
# ⚠️ 라운드 184 — 세 타일의 합이 **128%** 가 됐다 (사용자 지적).
#   목표 칸만 계층 보정값(약 58%)을 쓰고 손절(50%)·미결(20%)은 유사사례
#   실측 비율을 그대로 썼기 때문이다 — 서로 다른 추정치를 한 분할처럼
#   그려 놓은 것이다. 세 칸은 **같은 표본(유사사례)의 분할**로 통일해
#   합이 100% 가 되게 하고, 계층 보정값(R59 채택 — 배너가 쓰는 값)은
#   **별도 추정치**로 아래 캡션에 갈라 적는다. 값은 하나도 안 바꾼다 —
#   무엇이 무엇과 합산되는지를 바로잡는 것이다 (§4).
# ⚠️ 라운드 199 — 세 칸이 전부 '산출 불가' 로 나가는데 **왜인지 안 적혀
#   있었다.** 사용자 지적: *"산출 불가는 어떻게 해야 해. 자꾸 현명하게
#   해줘."*  맞는 말이다. 규칙 자체는 옳다 — §11 이 유효표본 10건 미만에서
#   확률 환산을 막는다(작은 표본을 확률처럼 내밀지 않는다). 그런데 화면이
#   *"산출 불가"* 세 글자만 내밀면 사용자는 **고장인지 규칙인지** 알 수
#   없고, 우리가 **대신 무엇을 아는지**도 못 본다.
#   → 숫자를 지어내지 않는다(§3). 대신 셋을 적는다:
#     ① 왜 못 내는가 (유사사례 N건 · 문턱 10건)
#     ② 그래도 아는 것 (관찰값 — 몇 건 중 몇 건)
#     ③ 대신 볼 값 (계층 보정 확률 — 아래 캡션이 이미 내는 값)
_na_n199 = _g.get('sample_n')
_na_why199 = (f"유사사례 {_na_n199}건 — 확률로 환산하려면 10건이 필요합니다"
              if isinstance(_na_n199, int) else
              "유사사례 표본을 만들지 못했습니다")
_na_all199 = all(_g.get(k) is None
                 for k in ('tp_first', 'sl_first', 'undecided'))
_uk.stat_tiles([
    {'label': '목표 방향이 먼저 나올 확률 (유사사례 실측)',
     'value': _pc(_g['tp_first']),
     'sub': (_na_why199 if _g['tp_first'] is None
             else '아래 두 칸과 같은 표본 — 셋의 합이 100%입니다'),
     'tone': 'pos'},
    {'label': '손절선에 먼저 닿을 확률', 'value': _pc(_g['sl_first']),
     'sub': (_na_why199 if _g['sl_first'] is None
             else '목표보다 손절에 먼저 닿는 비율'), 'tone': 'neg'},
    {'label': '기간 안에 어느 쪽도 못 닿을 확률', 'value': _pc(_g['undecided']),
     'sub': (_na_why199 if _g['undecided'] is None
             else '보유기간이 끝날 때까지 결판 안 남')},
], theme=_theme)
if _na_all199:
    _obs199 = str(sim_res.get('predicted_prob_str') or '') if sim_res else ''
    st.caption(_md_safe(
        "**세 칸이 비어 있는 것은 고장이 아니라 규칙입니다** — 유효표본이 "
        "10건에 못 미치면 확률로 환산하지 않습니다. 작은 표본을 확률처럼 "
        "내밀면 없는 근거를 만드는 것이기 때문입니다."
        + (f"  \n지금 아는 것은 **관찰값**뿐입니다 — {_obs199}"
           if '건 중' in _obs199 else '')
        + ("  \n대신 **계층 보정 확률**(아래 줄)을 보세요 — 같은 점수대·"
           "국면·자리·업종의 실측을 표본 크기에 따라 섞은 값입니다."
           if _blend59 else
           "  \n계층 보정 확률도 이 종목에서는 만들지 못했습니다.")
        + "  \n거래일이 쌓여 유사사례가 10건을 넘으면 자동으로 채워집니다."))
if _blend59:
    st.caption(_md_safe(
        f"계층 보정 목표 확률(R59 채택 · 배너가 쓰는 값)은 **약 "
        f"{_blend59['p'] * 100:.0f}%** 입니다 — 위 세 칸과 **다른 추정치**"
        f"라 그 분할과 합산되지 않습니다 (근거 {_blend59['layers']}층 · "
        f"최협층 n {_blend59['n_narrow']:,} · 구간 "
        f"{_blend59['wilson_low'] * 100:.0f}~"
        f"{_blend59['wilson_high'] * 100:.0f}%)."))
# ⚠️ 라운드 98 — 화면 아래쪽 '목표별 도달 확률' 표(+2%·+3%···)와 이 타일이
#   둘 다 '확률'이라 같은 것처럼 읽혔다. 정의가 다르다:
#     · 이 타일  = **이 종목의 1차 목표**가 손절보다 먼저 나올 확률
#     · 아래 표  = **고정 폭(+2%·+3%···)**에 닿은 비율 (매수권 사례 실측)
#   목표 폭이 커질수록 도달률은 내려가므로 두 숫자는 원래 다르다.
#   값을 바꾸지 않는다 — 무엇을 재는지 적는다.
st.caption(_md_safe(
    "위 확률은 **이 종목의 1차 목표**가 손절보다 먼저 나올 확률입니다. "
    "화면 아래 '얼마에 팔 것인가' 표의 확률은 **고정 폭(+2%·+3%···)에 "
    "닿은 비율**이라 서로 다른 질문의 답입니다 — 목표 폭이 커질수록 "
    "도달률은 내려갑니다."))
if _blend59:
    st.caption(_md_safe(
        "계층 보정 확률은 이 종목만의 확률이 아니라 같은 점수대·국면·자리"
        "·업종 계층의 실측을 표본 크기에 따라 섞은 값입니다 (R59 게이트 "
        "통과 — Brier·보정도에서 종전 유사사례 확률보다 정확). 초근접 "
        f"유사사례는 {_g.get('sample_n') or 0}건으로 여전히 부족하며, 그 "
        "사실은 아래 한계에 그대로 둡니다."))
_uk.spacer(12)

# ── 계층 실측 (라운드 58) — '산출 불가'로 대화를 끝내지 않는다 ─────────
# 초근접 표본이 5건이면 그 사실은 그대로 두고(문턱을 낮춰 채우면 §2 위반),
# 더 넓은 계층의 실측을 이름표와 함께 병기한다. 어떤 층도 '이 종목의
# 확률'이 아니다 — 그 계층의 실측이다. 층 혼합 확률은 R59 게이트 통과 전
# 금지 (docs/PREREG_R59_HIER_PROB.md).
try:
    import case_layers as _cl58
    # _rg58 은 위 계층 보정 타일에서 이미 계산됨 — 같은 값을 재사용 (§4)
    _lay58, _note58 = _cl58.layers_for(
        verdict.get('score'), sector=val_eval.get('sector'),
        regime_code=_rg58, fs=four_scores, ticker=target_ticker)
    # L5(점수대 전체)는 화면 위 '이 점수대의 실제 성적'(calibration 출처)과
    # 같은 개념이라 다른 집계로 또 보여주면 §4 위반이다 — 좁은 층만 병기
    _lay58 = [r for r in _lay58 if r.get('narrow', 0) > 0]
    if _lay58:
        _lrows58 = [(
            r['label'],
            f"적중 {r['hit']}% (하한 {r['wilson']}) · EV {r['ev']:+.2f} · "
            f"n {r['n']:,}",
            ('pos' if r['ev'] > 0 else 'neg')) for r in _lay58]
        _uk.rows(_lrows58, theme=_theme,
                 title='더 넓은 계층의 실측 — 같은 조건이었던 과거')
        st.caption(_md_safe(
            "위 값은 이 종목의 확률이 아니라 각 계층의 실측입니다. "
            "초근접 사례가 부족해도 판단 재료가 없는 것이 아니라, 좁은 "
            "버킷만 비어 있는 것입니다 — 좁은 층일수록 지금과 닮았고, "
            "넓은 층일수록 표본이 많습니다. 유사도 문턱을 낮춰 표본을 "
            "채우는 방식은 쓰지 않습니다."))
        if _note58:
            st.caption(_md_safe(f"· {_note58}"))
    # 이 종목 자체 과거 신호의 실체 (라운드 61) — "그 사례들이 뭔데?"에
    # 표로 답한다. 표시 전용 · R59 혼합 미포함 (게이트가 SELF 없는 구성으로
    # 통과 — 통과 후 층 추가는 무단 변경).
    _sh61 = _cl58.self_history(target_ticker)
    if _sh61 and _sh61.get('recent'):
        with st.expander(f"이 종목 과거 신호 실체 — 최근 "
                         f"{len(_sh61['recent'])}건 (전체 {_sh61['n']}건 · "
                         f"적중 {_sh61['hit']}%)"):
            import pandas as _pd61
            st.dataframe(_pd61.DataFrame(
                _sh61['recent'],
                columns=['신호일', '점수', '결과', '판정수익%']),
                hide_index=True, width='stretch')
            st.caption("개발 구간 원장 실측 그대로 — 미래 신호의 보장이 "
                       "아니며, 표본이 작을수록 우연에 가깝습니다.")
except Exception:                                              # noqa: BLE001
    pass                          # 계층 표 하나 때문에 화면이 죽지 않는다
_uk.spacer(12)

_rows_g = [
    # ⚠️ 라운드 98 — 이 값은 sim.optimal_holding_period_days 다. 즉
    #   **유사패턴이 고른 관찰 지평**이고, 매매지시서의 '예상 보유 20거래일'
    #   (core.horizon_days)과는 다른 값이다. 둘 다 '예상 보유기간'으로
    #   적혀 있어서 화면이 20일과 40일을 동시에 말하는 것처럼 보였다.
    #   값은 안 바꾼다 — 무엇을 재는지 이름으로 가른다.
    ('유사패턴 관찰기간',
     (f"{_g['hold_days']}거래일" if _g.get('hold_days') else _gai.NA)),
    ('비슷했던 과거 사례',
     (f"{_g['sample_n']:,}건" if _g.get('sample_n') else '찾지 못함')),
    # ⚠️ 라운드 184 — 이 칸이 '안 본 사례'라고 적혀 있었는데 **거짓**이었다.
    #   출처(calibration.json bands)는 판정 완료 177,042건 **전체**
    #   (train 153,620 포함)다. 블라인드 전체가 11,603건인데 한 점수대가
    #   89,520건일 수는 없다(사용자 지적). 표본외라 부르지 않는다.
    ('이 점수대의 리플레이 성적 (학습·검증 포함 전체)',
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

# 유사사례 실체 (라운드 62) — "그 5건이 뭔데?" 에 표로 답한다.
# 확률을 못 내는 표본이어도 **무엇을 봤는지는 보여 준다** — 표시 전용이며
# 이 표에서 새 판정을 만들지 않는다.
try:
    _mh62 = ((sim_res or {}).get('horizons_data') or {}).get(20) or {}
    _mt62 = _mh62.get('matches') or []
    if _mt62:
        with st.expander(f"이 종목의 유사사례 실체 — {len(_mt62)}건 "
                         f"(20일 패턴 · 유사도 {sim_res.get('rho_cutoff_applied', 0.8):.2f} 이상)"):
            import pandas as _pd62
            st.dataframe(_pd62.DataFrame([
                [m['date'], m['rho'], f"{m['price']:,.0f}", m['outcome'],
                 m['ret_pct'], m['mdd_pct']] for m in _mt62],
                columns=['패턴 종료일', '유사도(ρ)', '당시 가격', '20일 결과',
                         '수익%', '최대낙폭%']),
                hide_index=True, width='stretch')
            st.caption(_md_safe(
                "이 종목의 과거 가격 경로에서 지금과 닮은 구간을 찾아, 그 "
                "직후 20영업일에 실제로 무슨 일이 있었는지 그대로 옮긴 "
                "것입니다. 표본이 적으면 확률로 환산하지 않지만, 무엇을 "
                "봤는지는 숨기지 않습니다."))
except Exception:                                              # noqa: BLE001
    pass                          # 사례 표 하나 때문에 화면이 죽지 않는다

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

# ── 판단 품질 · 엔진별 의견 · 연구 레이더 (라운드 61) ─────────────────
# 버전 숫자만 보여주지 않고 "이번 판단을 누가 어떻게 만들었고, 무엇이
# 약하고, 무엇이 연구 중인가"를 편다. 전부 기존 값의 결정적 조합 —
# 여기서 판정을 만들지 않는다. 후보 엔진 상태는 실제 라운드 결과만 쓴다.
try:
    import news_feed as _nf60
    _news60 = _nf60.for_stock(resolved_name)
except Exception:                                              # noqa: BLE001
    _news60 = None
try:
    _eng_rows = []
    _e61 = (CORE or {}).get('pullback_zone')
    _gap61 = ((float(realtime_price) / float(_e61) - 1) * 100
              if _e61 and realtime_price else None)
    _eng_rows.append((
        '타이밍·기술', (CORE or {}).get('bucket') or '미분류',
        (f"현재가가 진입 기준보다 {_gap61:+.1f}%"
         if _gap61 is not None else '진입 기준 미산출'),
        ('강한 부정' if _gap61 is not None and _gap61 > 3 else
         '중립' if _gap61 is not None else '판단 불가')))
    _fair61 = four_scores.get('displayed_fair_value')
    if _fair61 and realtime_price:
        _fg61 = (float(realtime_price) / float(_fair61) - 1) * 100
        _eng_rows.append(('펀더멘털', f'현재가가 적정가 대비 {_fg61:+.0f}%',
                          f"적정가 {_fair61:,.0f}원 "
                          f"({four_scores.get('fair_value_status')})",
                          '부정 참고' if _fg61 > 10 else '중립 참고'))
    else:
        _eng_rows.append(('펀더멘털', '미산출',
                          str(four_scores.get('fair_value_status_note')
                              or '적정가 미산출')[:40], '판단 불가'))
    # ⚠️ 라운드 81b — 이 줄의 n 은 **raw 건수**다. 같은 날 같은 업종
    #   종목은 함께 움직이므로 독립 관측이 아니다. 숫자만 보면 실제보다
    #   단단해 보인다. 그래서 그 업종의 **실측 ICC 를 옆에 적는다.**
    #
    #   변환한 유효표본을 여기 쓰지 않는다 — sector_perf.json 의 모집단과
    #   ICC 를 잰 모집단이 달라, 한쪽 비율을 다른 쪽 n 에 곱하면 근거 없는
    #   숫자가 된다 (§3). 잰 것만 적는다.
    _icc61 = None
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               'data', 'effective_n_icc.json'),
                  encoding='utf-8') as _f61:
            _icc61 = (json.load(_f61).get('sectors') or {})
    except Exception:                                          # noqa: BLE001
        _icc61 = None
    try:
        import sector_cycle as _scq61
        _sp61 = _scq61.ledger_perf(val_eval.get('sector'))
        if _sp61 and not _sp61.get('small'):
            _tone61 = ('긍정 참고' if _sp61['ev'] > 0 else '부정 참고')
            # 표본이 하한(R55 §3 의 n≥200 재사용)에 못 미치면 안 띄운다.
            # '광고' 는 raw 6건인데 ICC 0.98 이 나온다 — 그런 숫자를 화면에
            # 올리는 것이 라운드 27b 가 낸 사고다.
            _ic61 = (_icc61 or {}).get(str(_sp61['sector']))
            _icctxt61 = (f" · 같은 날 상관 ICC {_ic61['icc']:.2f}"
                         if (_ic61 and _ic61.get('report')) else '')
            _eng_rows.append(('업황(표시 전용)',
                              f"{_sp61['sector']}",
                              f"원장 실측 적중 {_sp61['hit']}% · "
                              f"EV {_sp61['ev']:+.2f} "
                              f"(n {_sp61['n']:,} raw{_icctxt61})",
                              _tone61))
    except Exception:                                          # noqa: BLE001
        pass
    # ⚠️ 라운드 178 — **'미수신'과 '기사 없음'을 섞고 있었다.**
    #   화면에 `뉴스 · 미수신 · 수신 기사 없음 — 판단에 미반영` 이 나갔다.
    #   앞은 "우리가 못 받았다"(우리 문제)이고 뒤는 "받았는데 기사가
    #   없다"(정상)다 — §3 이 *"데이터 미수신 ≠ 추천 없음. 두 문장을
    #   반드시 분리한다"* 고 못 박은 그 자리다.
    #   `_news60` 이 `None` 이면 수집 실패, dict 인데 `total` 이 0 이면
    #   수집은 됐고 기사가 없는 것이다. 갈라서 말한다.
    _nt61 = (_news60 or {}).get('total')
    if _news60 is None:
        _news_state61, _news_detail61 = '미수신', '뉴스 수집에 실패했습니다 — 판단에 미반영'
    elif not _nt61:
        _news_state61, _news_detail61 = '기사 없음', '수집은 됐고 관련 기사가 없습니다 — 판단에 미반영'
    elif _news60.get('risk_words'):
        _news_state61, _news_detail61 = '위험 낱말 감지', f"관련 기사 {_nt61}건"
    else:
        _news_state61, _news_detail61 = '중립', f"관련 기사 {_nt61}건"
    _eng_rows.append((
        '뉴스', _news_state61, _news_detail61,
        '감점 요인' if (_news60 or {}).get('risk_words') else '영향 작음'))
    _ST_KO61 = {'ABOVE_BOTH': '상승(20·60선 위)', 'REBOUND': '반등 초기',
                'PULLBACK': '조정', 'BEAR': '약세'}
    _eng_rows.append((
        '시장 국면', _ST_KO61.get(_rg58, '미산출'),
        f'국면 라우팅(R55)은 {_fe.eval_date_ko()} 전방 검증 전 — '
        f'이번 판단에 미사용',
        '참고'))
    if _blend59:
        _eng_rows.append((
            '계층 케이스', f"약 {_blend59['p'] * 100:.0f}%",
            f"{_blend59['layers']}층 혼합 · 최협층 n "
            f"{_blend59['n_narrow']:,}", '확률 근거'))
    _uk.section("이번 판단을 만든 근거들",
                "엔진별 의견 — 판정은 위 배너 하나뿐이고, 여기는 그 구성이다",
                theme=_theme, top=28)
    _uk.rows([(f"{a} · {b}", f"{c} — {d}") for a, b, c, d in _eng_rows],
             theme=_theme)
    # 종합 한 줄 — 규칙 기반 (버킷·괴리로만 구성)
    _bk61 = str((CORE or {}).get('bucket') or '')
    if (_gap61 is not None and _gap61 > 3
            and ('대기' in _bk61 or '제외' in _bk61)):
        # ⚠️ 라운드 184 — 이 문장이 **사실 확인 없이** "기업·업황이 나빠서가
        #   아니라"고 단정하고 있었다. 서진시스템은 기본 매력도 48점 ·
        #   ROE −12.9% · 적정가 미산출인데도 그렇게 나갔다(사용자 지적).
        #   기본 매력도가 게이트(60점)를 넘고 적정가도 있을 때만 그 말을
        #   쓰고, 아니면 **둘 다**라고 말한다.
        _q61 = four_scores.get('stock_quality_score')
        _fv_ok61 = bool(four_scores.get('fair_value_usable'))
        if (_q61 is not None and float(_q61) >= 60 and _fv_ok61):
            st.caption(_md_safe(
                '종합: 기업·업황이 나빠서가 아니라 **현재 진입가격이 검증된 '
                '기준보다 높아서** 신규 매수가 보류된 상태입니다.'))
        else:
            _q_txt61 = (f'기본 매력도 {float(_q61):.0f}점'
                        if _q61 is not None else '기본 매력도 미산출')
            st.caption(_md_safe(
                f'종합: **현재 진입가격이 검증된 기준보다 높고**, 펀더멘털 '
                f'불확실성({_q_txt61}'
                + ('' if _fv_ok61 else ' · 적정가 미산출')
                + ')도 함께 신규 매수를 제한합니다.'))
    # 라운드 81b — 위 표의 업황 n 이 raw 라는 것을 한 번만 설명한다.
    # 표 안에 매번 문장을 넣으면 칸이 터지고, 안 적으면 235 가 독립 관측
    # 235 개로 읽힌다.
    if _icc61 and any(r[0] == '업황(표시 전용)' for r in _eng_rows):
        # ⚠️ 라운드 99 — 여기 범위가 '0.15~0.37' 로 **손으로 적혀** 있었다.
        #   그건 업종 41개일 때 잰 값이고, 유효표본 산출이 패치까지 읽게
        #   되면서 65개(화면에 쓰는 것은 48개)가 됐다. 실제 범위는
        #   0.06~0.43 으로 달라졌다. 잰 값을 문장에 박아 두면 반드시
        #   낡는다 — **같은 파일에서 유도한다.**
        _iccv61 = sorted(v['icc'] for v in (_icc61 or {}).values()
                         if v.get('report') and v.get('icc') is not None)
        _iccr61 = (f'업종별 실측 ICC {_iccv61[0]:.2f}~{_iccv61[-1]:.2f}'
                   if _iccv61 else '업종별 실측 ICC 미산출')
        st.caption(_md_safe(
            '업황 줄의 **n 은 raw 건수**입니다. 같은 날 같은 업종 종목은 '
            f'함께 움직이므로({_iccr61}) 독립 관측 수는 '
            '그보다 훨씬 적습니다 — 적중률·EV 를 그 표본이 주는 것보다 '
            '단단하게 읽지 마세요. 계산은 `docs/EFFECTIVE_N_ICC_R80.md`.'))
    # 이번 판단의 약점 — 가늠 AI 한계에서 상위 2개 재사용 (§4 한 소스)
    _weak61 = list((_g.get('limits') or [])[:2])
    if _blend59 and _blend59.get('n_narrow', 0) < 200:
        _weak61.append(f"가장 좁은 계층 표본이 {_blend59['n_narrow']}건 — "
                       f"계층 보정의 개인화 정도가 낮습니다")
    if _weak61:
        _uk.card(
            "<p style='margin:0 0 6px 0; font-size:13px; "
            f"color:{_TOK['tx3']};'>이번 판단에서 가장 약한 근거</p>"
            + ''.join(f"<p style='margin:0 0 4px 0; font-size:15px; "
                      f"line-height:1.6; color:{_TOK['tx2']};'>· "
                      f"{_uk._esc(w)}</p>" for w in _weak61[:3]),
            theme=_theme, accent='warn')
    with st.expander("다른 엔진과 비교 · 다음 개선 연구 (연구·특허 레이더)"):
        st.markdown(_md_safe(
            "각 후보의 상태는 실제 라운드 결과입니다. 후보 엔진의 숫자는 "
            "운영 판단에 섞이지 않으며, 채택은 사전등록 → valid → 전방 "
            "검증을 통과해야만 합니다. 논문·특허는 아이디어 출처일 뿐 "
            "성능 근거가 아닙니다."))
        # ⚠️ 라운드 82 — 이 표는 여기 DataFrame 리터럴로 박혀 있었다.
        #   그래서 라운드 78 에서 재평가일을 고칠 때 이 표 안의 '8/23' 두
        #   개가 따로 남아 있었다 — 같은 사실이 두 곳에 적혀 있으면 한쪽만
        #   고치게 된다(§4). 이제 data/research_radar.json 한 곳에서 읽는다.
        #   전방검증 대기 항목의 날짜는 forward_eval 이 붙인다 — 표에
        #   날짜를 적어 두지 않는다.
        import pandas as _pd61b
        _rad61 = None
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   'data', 'research_radar.json'),
                      encoding='utf-8') as _rf61:
                _rad61 = json.load(_rf61)
        except Exception:                                      # noqa: BLE001
            _rad61 = None
        if _rad61 and _rad61.get('rows'):
            _rows61 = []
            for _r61 in _rad61['rows']:
                _st61 = str(_r61.get('status') or '')
                if _r61.get('status_needs_eval_date'):
                    _st61 = f"{_st61} ({_fe.eval_date_ko()})"
                _rows61.append([_r61.get('name'), _st61,
                                _r61.get('strength'), _r61.get('limit')])
            st.dataframe(
                _pd61b.DataFrame(_rows61,
                                 columns=(_rad61.get('columns')
                                          or ['엔진·후보', '상태',
                                              '근거·강점', '한계'])),
                hide_index=True, width='stretch')
        else:
            # 없는 표를 지어내지 않는다 (§3) — 못 읽었으면 그렇게 적는다.
            st.caption(_md_safe(
                '후보 목록을 읽지 못했습니다 (`data/research_radar.json`). '
                '목록 없이 표를 만들지 않습니다.'))
        st.caption(_md_safe(
            f"다음 개선 연구: Entry(다층 매수구간 · {_fe.eval_date_ko()} 후) "
            f"· Exit(새 신호 집합 위 재측정) · 뉴스 가격반응 · TSFM 챌린저 "
            f"· 순위 엔진. 전부 계획이며 현재 판단값을 바꾸지 않습니다."))
except Exception:                                              # noqa: BLE001
    pass                          # 설명 칸 때문에 분석 화면이 죽지 않는다

# ── 가늠 AI에게 물어보기 (라운드 60) — 종목 전용 결정적 답변 조합기 ─────
# 외부 LLM 미사용: §9(포트폴리오 외부 전송 금지)와 양립하지 않고, 요구
# 명세("중앙 값만·재계산 금지·없으면 없다고") 자체가 결정적 조합기다.
# 모든 가격은 CORE/four_scores 를 그대로 읽는다 — 여기서 만들지 않는다.
try:
    import gaeum_chat as _gch
    st.markdown("<div id='nav-ask'></div>", unsafe_allow_html=True)
    _uk.section("가늠 AI에게 물어보기",
                f"{resolved_name} 대화 — 종목을 바꾸면 대화도 그 종목 "
                f"것으로 분리됩니다", theme=_theme, top=28)
    # _news60 은 위 '판단 근거' 대시보드에서 이미 수신 — 재수신하지 않는다
    _ctx60 = _gch.build_context(
        name=resolved_name, ticker=target_ticker, price=realtime_price,
        core=CORE, fs=four_scores, verdict=verdict, blend=_blend59,
        regime_code=_rg58, sector=val_eval.get('sector'), news=_news60,
        versions=_ver.snapshot(), cb=_cb,
        user_avg=(user_entry_price if user_entry_price
                  and user_entry_price > 0 else None))
    _ck60 = f"gchat_{str(target_ticker).replace('.', '_')}"
    if _ck60 not in st.session_state:
        st.session_state[_ck60] = []
    # 추천 질문 칩 — 한 줄 배치
    _qcols = st.columns(3)
    _pending_q = None
    for _qi, _qq in enumerate(_gch.QUICK_QUESTIONS[:9]):
        if _qcols[_qi % 3].button(_qq, key=f'{_ck60}_q{_qi}'):
            _pending_q = _qq
    _typed_q = st.chat_input('이 종목에 대해 무엇이든 물어보세요',
                             key=f'{_ck60}_in')
    _ask60 = _typed_q or _pending_q
    if _ask60:
        st.session_state[_ck60].append(('user', _ask60))
        st.session_state[_ck60].append(('assistant',
                                        _gch.answer(_ask60, _ctx60)))
        st.session_state[_ck60] = st.session_state[_ck60][-12:]
    for _role60, _msg60 in st.session_state[_ck60]:
        with st.chat_message(_role60):
            st.markdown(_md_safe(_msg60))
    if not st.session_state[_ck60]:
        st.caption("답은 이 화면의 중앙 판정 값만 씁니다 — 다른 화면과 다른 "
                   "가격을 만들지 않고, 없는 값은 없다고 말합니다. 평단 등 "
                   "개인 정보는 이 PC 를 떠나지 않습니다.")
except Exception:                                              # noqa: BLE001
    pass                          # 대화 한 칸 때문에 분석 화면이 죽지 않는다

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
# ⚠️ 라운드 184 — '표본외 성적'이라고 적었는데 calibration bands 는
#   학습·검증·블라인드 **전체 리플레이**(판정 완료 177,042건)다.
#   블라인드만의 수치는 홈의 '실전 적중률'이 따로 있다. 이름을 바로잡는다.
if _cb_v.get('n'):
    _rows_v.append((
        f"이 점수대({_cb_v.get('lo')}~{_cb_v.get('hi')}점)의 리플레이 성적"
        f" (학습·검증 포함)",
        f"{_cb_v.get('hit_rate', 0):.0f}% · {_cb_v['n']:,}건"
        + (f" · 하한 {_cb_v['wilson_low']:.0f}%"
           if _cb_v.get('wilson_low') is not None else ''),
        'pos' if (_cb_v.get('wilson_low') or 0) >= 55 else 'warn'))
else:
    _rows_v.append(('이 점수대의 리플레이 성적', '표본 부족 — 판단에 반영하지 않음',
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
    <p style="margin:4px 0 0 0; color:#9DAABC; font-size:13px;">종합 결론·점수·실행 가격 기준(진입 기준가/1차 목표가/손절가)은 화면 맨 위 배너에 있습니다. 여기서는 그 근거만 봅니다.</p>
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
    <h4 style="color:#F3F6FA; margin:0 0 8px 0;">DeMARK 신호</h4>
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
# 라운드 186 — 이 상자의 기준값은 `buy_entry_max`(적정가−안전마진)인데
# '권장 매수가'라 부르고 있었다. 배너의 권장 매수가(실행 진입가)와 **다른
# 값**이 같은 이름을 쓰는 자리다(quant_indicators:3860 주석이 지목한 그
# 결함). 게이트 라벨(R184)이 이미 쓰는 이름 '가치 기준선(적정가−안전마진)'
# 으로 통일한다 — 새 이름이 아니다 (§2 재사용).
if _zone == "판정 불가":
    st.warning("**[진입 판정 불가]**: 적정가 신뢰도가 기준에 미달하여 가치 기준선(적정가−안전마진)을 산출하지 못했습니다. "
               "현재가가 적정 진입구간 안인지 판단할 수 없으므로 신규 진입을 권하지 않습니다.")
elif _zone == "안전마진 확보":
    st.success(f"**[안전마진 확보]**: 현재가({curr_price:,.0f}원)가 가치 기준선({_bem_str} · 적정가−안전마진) 이하입니다.")
elif _zone == "적정가 이하 (안전마진 미확보)":
    st.info(f"**[안전마진 미확보]**: 현재가({curr_price:,.0f}원)는 적정가 아래이지만 "
            f"가치 기준선({_bem_str} · 적정가−안전마진)보다는 높습니다. 안전마진 확보 전까지 분할 진입은 보류를 권장합니다.")
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
        # 라운드 120 — 여기 `_reg_icon` 이 이모지 4종이었는데 2026-08-05
        #   '디자인 정리' 에서 전부 빈 문자열이 됐다. 그러자 문장이
        #   `** 상장시장 국면 …**` 이 되고, 마크다운은 **여는 별표 뒤에
        #   공백이 오면 굵기로 보지 않으므로** 별표가 12일 동안 글자
        #   그대로 화면에 나와 있었다. 빈 자리를 남기지 않는다.
        st.markdown(f"**상장시장 국면 — {_dom.get('market')}**")
        st.markdown(f"{_dom.get('regime_label')}")
        st.caption(_dom.get('basis', '') + " · " + _dom.get('source', ''))
    else:
        # 라운드 159 — 시장을 못 읽은 종목은 market 이 None 이다.
        #   그대로 보간하면 '상장시장 국면 — None' 이 화면에 나간다.
        st.markdown(f"**상장시장 국면 — "
                    f"{_mkt_ctx.get('market') or '상장 시장 미확인'}**")
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
        # ⚠️ 라운드 98 — 낱말은 걸렸는데 **사고 맥락이 없어** 확정하지 못한 것.
        #   점수 상한을 걸지 않는다(농심 '인기 폭발' 이 그래서 매수를 막았다).
        #   그렇다고 감추면 사용자가 그 기사가 있었다는 사실조차 모른다 —
        #   막지 않되 **보여는 준다.**
        if _nfl.get('review_count'):
            _rw = ' · '.join(_nfl.get('review_words') or [])
            st.info(
                f"확인이 필요할 수 있는 낱말이 있는 기사 "
                f"**{_nfl['review_count']}건**"
                + (f" ({_rw})" if _rw else '')
                + " — 사고·분쟁 맥락이 함께 나오지 않아 **점수에는 반영하지 "
                  "않았습니다.** 같은 낱말이라도 '공장 폭발'과 '인기 폭발'은 "
                  "다르기 때문입니다. 제목을 직접 보고 판단해 주세요.")
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
            _flag = " " + "·".join(_it['risk_hits']) if _it.get('risk_hits') else ""
            # 확정은 아니지만 걸린 낱말 — 점수엔 안 쓰고 표시만 (라운드 98)
            if not _flag and _it.get('risk_review'):
                _flag = " `확인 필요: " + "·".join(_it['risk_review']) + "`"
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
    st.caption("" + str(_note))

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
    # 라운드 108 — 이 숫자가 **로컬 최신인지 저장소 동봉본인지** 밝힌다.
    # 배포 환경에는 .portfolio 가 없어 늘 동봉본을 읽는데, 그 사실을
    # 안 적으면 옛 표본으로 낸 숫자를 최신으로 읽게 된다(§3·§9).
    _cal_src = _artifact_source("calibration.json")
    # 라운드 217 — R198 의 '원장 행수' 결정을 여기도 따른다 (:753 과 같은 우선순위)
    st.caption(f"과거 기준일 리플레이 **{_perf_cal.get('ledger_rows') or _perf_cal['total_cases']:,}건** · "
               f"규칙집 {_perf_cal.get('rulebook_version', '—')} · "
               + ("로컬 최신 기록" if _cal_src == 'live'
                  else "저장소 동봉본 (배포 환경 — 로컬 기록 없음)")
               + " · 시간 분할: 학습 <2025-07 / 검증 ~2026-01 / "
               "블라인드 ≥2026-02 "
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
        # ── ②' 국면 × 구간 — '연습 vs 실전' 괴리의 정체 (라운드 216) ──────
        # 사용자: *"산식은 개선 어떻게 잡고 있어?"* 원장 250,725행을 점수대×
        # 국면×구간으로 갈라 보니 괴리는 대부분 **국면 조성**이었다 — 검증
        # 구간에 하락장이 거의 없었고(날짜 4) 블라인드는 22%가 하락장이며,
        # 하락장 블라인드에서 점수는 거꾸로 간다. 그것을 숨기면 '연습 71.5%'
        # 가 실력처럼 읽힌다 (§9). **표시 전용** — 규칙·확률 산출은 안 바꾼다.
        # 값은 원장(케이스 스터디와 같은 로더)에서 그 자리에서 센다 (§4).
        # 표본 하한 30 과 Wilson 하한은 옆 표 ②·③ 과 regime_policy 의 것을
        # 그대로 쓴다 — 새 숫자 없음 (§2-6).
        try:
            import regime_policy as _rp216
            _ldf216 = _load_case_ledger()
            if _ldf216 is not None and {'score', 'regime', 'split', 'success'} <= set(_ldf216.columns):
                _bz216 = _ldf216[(pd.to_numeric(_ldf216['score'], errors='coerce') >= 58)
                                 & _ldf216['success'].notna()]
                _rows216 = []
                _cell216 = {}
                for _rg216 in ('BULL', 'SIDEWAYS', 'BEAR', '전체'):
                    _row216 = {'국면': _rg216}
                    _sub = _bz216 if _rg216 == '전체' else _bz216[_bz216['regime'] == _rg216]
                    _hv = {}
                    for _sp216, _lab216 in (('train', '학습'), ('valid', '검증'),
                                            ('blind', '블라인드')):
                        _s = _sub[_sub['split'] == _sp216]
                        _n = int(len(_s))
                        if _n >= 30:
                            _h = float(_s['success'].astype(bool).mean() * 100.0)
                            _row216[_lab216] = (f"{_h:.1f}% (n {_n:,} · 하한 "
                                                f"{_rp216.wilson_low(_h, _n):.1f})")
                            _hv[_sp216] = _h
                        else:
                            _row216[_lab216] = f"n {_n} — 표본 부족"
                        _cell216[(_rg216, _sp216)] = (_n, _hv.get(_sp216))
                    _row216['검증−블라인드'] = (f"{_hv['valid'] - _hv['blind']:+.1f}%p"
                                           if ('valid' in _hv and 'blind' in _hv) else '—')
                    _rows216.append(_row216)
                st.markdown("**②' 같은 신호를 국면 × 구간으로** — '연습 vs 실전' 괴리의 정체")
                st.dataframe(pd.DataFrame(_rows216), width='stretch', hide_index=True)
                # 하락장 블라인드에서 점수가 거꾸로 가는지 — 그 자리에서 센다
                _bb216 = _bz216[(_bz216['regime'] == 'BEAR') & (_bz216['split'] == 'blind')]
                _lo216 = _ldf216[(pd.to_numeric(_ldf216['score'], errors='coerce').between(40, 49))
                                 & (_ldf216['regime'] == 'BEAR') & (_ldf216['split'] == 'blind')
                                 & _ldf216['success'].notna()]
                _hi216 = _bb216[pd.to_numeric(_bb216['score'], errors='coerce').between(60, 64)]
                _inv216 = ''
                if len(_lo216) >= 30 and len(_hi216) >= 30:
                    # ⚠️ '40~49' 처럼 물결표가 한 문장에 **둘** 있으면 GFM 이 취소선
                    #   짝으로 읽어 "4049점" 으로 그렸다(실측). 이스케이프한다.
                    _inv216 = (f" 하락장 블라인드에서는 점수가 거꾸로 갑니다 — 40\\~49점 "
                               f"{_lo216['success'].astype(bool).mean() * 100:.0f}%(n {len(_lo216):,}) · "
                               f"60\\~64점 {_hi216['success'].astype(bool).mean() * 100:.0f}%(n {len(_hi216):,}).")
                _vb216 = _cell216.get(('BEAR', 'valid'), (0, None))[0]
                # 하락장 **날짜** 수 — 그 자리에서 센다 (손 숫자는 낡는다 · §9).
                # ⚠️ '에피소드'(BEAR→회복 전환)로 세지 않는다 — 원장의 regime 은
                #   KOSPI/KOSDAQ 행마다 따로 판정돼 같은 날 다를 수 있어 "하루 한
                #   국면"이 어느 행을 잡느냐에 따라 3·6 도 3·1 도 된다(실측). 행 자체의
                #   regime 으로 세는 날짜 수는 잘 정의된다 — 사전등록 R1 도 이 수를 쓴다.
                _bdays216 = {}
                for _sp216c in ('valid', 'blind'):
                    _bd = _bz216[(_bz216['regime'] == 'BEAR') & (_bz216['split'] == _sp216c)]
                    _bdays216[_sp216c] = int(_bd['date'].astype(str).str[:10].nunique())
                _eps_txt216 = (f"검증·블라인드에서 매수권 신호가 난 하락장 날짜가 각 "
                               f"{_bdays216['valid']}·{_bdays216['blind']}일뿐이라")
                # 라운드 217 — 표의 n 은 케이스 수다. 같은 종목 기준일이 겹쳐 있어
                #   독립 표본 수가 아니므로, 겹침 없는 비율을 같은 헬퍼로 세어 같이 낸다.
                try:
                    _spc216 = _spaced_count_cached(_ldf216, len(_ldf216),
                                                   str(_ldf216['date'].max())[:10])
                    _spshare216 = (f"**{_spc216 / max(1, len(_ldf216)):.1%}**"
                                   f"({_spc216:,}건)")
                except Exception:                              # noqa: BLE001
                    import traceback as _tb217b
                    print('[모델 성적 겹침 없는 비율 셈 실패 — 캡션은 수 없이 그린다]')
                    _tb217b.print_exc()
                    _spshare216 = "이번에 못 셌습니다(사유는 로그)"
                st.caption(
                    f"검증 구간의 하락장 매수권 케이스는 **{_vb216:,}건**뿐이라 '연습' 적중률은 "
                    f"하락장을 거의 안 본 값입니다. 블라인드는 하락장 비중이 커서 낮게 나옵니다 — "
                    f"괴리의 상당 부분이 **국면 조성**입니다.{_inv216} 엔진의 실패는 하락장에 "
                    f"몰려 있고, 그 자리를 겨눈 연구(반등 확인 · 사전등록 R216)는 {_eps_txt216} "
                    f"**아직 판정할 수 없습니다** — 하한(30)을 내리지 않습니다. 이 표는 규칙을 "
                    f"바꾸지 않는 표시 전용입니다. 그리고 표의 n 은 **케이스 수**이지 독립 표본 "
                    f"수가 아닙니다 — 같은 종목의 기준일이 25봉보다 촘촘히 겹쳐 있어(라운드 217) "
                    f"25봉 간격을 지키는 부분집합은 전체의 {_spshare216}입니다.")
        except Exception:                                      # noqa: BLE001
            import sys as _sys216
            import traceback as _tb216
            print('[모델 성적 국면×구간 표 실패 — 나머지는 계속 그린다]\n'
                  + _tb216.format_exc(), file=_sys216.stderr)
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
    # ⚠️ 라운드 217 — 이 줄은 "독립 사례 N건 · 인접 기준일 중복은 25봉 간격
    #   규칙으로 통제합니다" 라고 적고 있었다. 둘 다 거짓이었다. 랩의 격자가
    #   최근 봉 기준이라 거래일마다 밀리고 완료 판정은 정확 일치라, 다른 날
    #   돌릴 때마다 밀린 격자가 통째로 새 케이스였다 — 같은 종목 이웃 기준일의
    #   72%가 20봉 결과 창 안에서 겹친다(2026-09-03 실측 · 250,725행 중 25봉
    #   간격을 지키는 부분집합 122,554건 · 48.9%). 수는 **여기서 그때그때 센다**
    #   (손으로 적은 수는 낡는다) — 규칙은 `ledger_view` 한 곳, 랩도 같은 것을
    #   부른다. 원장 행은 지우지 않았다(R197).
    try:
        _sp217 = _spaced_count_cached(_ledger_df, len(_ledger_df), _lg_last)
        _sp_txt = (f"25봉(={_lv217.MIN_GAP_DAYS}일) 간격을 지키는 부분집합은 "
                   f"**{_sp217:,}건({_sp217 / max(1, len(_ledger_df)):.1%})** 입니다")
    except Exception:                                          # noqa: BLE001
        import traceback as _tb217
        print('[원장 간격 부분집합 셈 실패 — 캡션은 수 없이 그린다]')
        _tb217.print_exc()
        _sp_txt = "25봉 간격을 지키는 부분집합 수는 이번에 못 셌습니다(사유는 로그)"
    # 같은 사실을 표본 감사(R72 · 같은 종목 35일 재신호 = 한 사건)로도 — 헤더가
    # 읽은 그 객체를 그대로 쓴다. 두 값을 따로 만들지 않는다(§4).
    _ep_txt217 = ""
    try:
        if _sa54.get('independent_episodes'):
            _ep_txt217 = (f" 같은 종목 35일 안 재신호를 한 사건으로 묶으면 "
                          f"**{int(_sa54['independent_episodes']):,}건**입니다"
                          f"(표본 감사 {_en54_made}).")
    except Exception:                                          # noqa: BLE001
        pass                          # 헤더가 못 읽었으면 여기도 비운다 — 조용히 다른 값을 만들지 않는다
    st.caption(f"사례 **{len(_ledger_df):,}건** (가상 백테스트 원장 그대로 — "
               "당시 점수·판정·이후 실제 경로·실패 원인). 필터로 직접 확인하세요.  \n"
               "**독립 사례가 아닙니다** — 같은 종목의 기준일이 25봉보다 촘촘히 "
               f"겹쳐 있어 결과 창이 서로 겹칩니다. {_sp_txt}.{_ep_txt217} "
               "(라운드 217 · 격자가 날마다 밀려 생긴 겹침 · 이후 축적은 이 간격을 지킵니다 · "
               "원장 행은 지우지 않았습니다).  \n"
               f"**운영 상태**: 마지막 케이스 기준일 {_lg_last} · 축적은 자동이 아닙니다 — "
               "사람이 랩을 돌려야 자라고, 같은 종목 25봉 안에는 더 쌓지 않습니다.")

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
            # 라운드 222 — 같은 추천이 모델 버전마다 다시 동결돼 있었다(463행 중
            #   복사본 245). 복사본(dup_version)과 시험 픽스처(void_fixture)는
            #   행으로는 남기되(R197) **세지 않는다.** 뺀 수는 옆에 적는다(§3).
            _n_all_imp = _ic.execute(
                "SELECT COUNT(*) FROM prediction_cases "
                "WHERE status NOT IN ('dup_version', 'void_fixture')").fetchone()[0]
            _n_excl_imp = _ic.execute(
                "SELECT COUNT(*) FROM prediction_cases "
                "WHERE status IN ('dup_version', 'void_fixture')").fetchone()[0]
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
                       "닿으면 성공으로 세지 않습니다 (선도달 확인 불가)."
                       + (f" 같은 추천의 버전 복사본·시험 픽스처 {_n_excl_imp}건은 "
                          f"행으로 남기되 세지 않았습니다 (R222)." if _n_excl_imp else ""))
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
                '결과': {'TARGET': '목표', 'STOP': '손절'}.get(
                    r['outcome'], '미도달'),
                '수익률': f"{r['return_pct']:+.1f}%",
                '최대이익 MFE': f"{r['mfe_pct']:+.1f}%",
                '최대손실 MAE': f"{r['mae_pct']:+.1f}%",
                '실패 원인': str(r.get('failure_class') or ''),
            } for _, r in _show.iterrows()]),
                width='stretch', hide_index=True)
            st.caption("성공 = 목표가를 손절가보다 먼저 터치. 수익률은 판정 봉 기준, "
                       "MFE/MAE는 보유 구간의 최대 이익/손실입니다. "
                       "블라인드 구간은 모델 선택에 쓰지 않은 순수 검증분입니다.")

# 고객센터는 **페이지 맨 끝**으로 옮겼다 (라운드 125).
#   여기 있으면 '점수 요인'(#nav-scores)보다 위라서, 메뉴 순서와 본문
#   순서가 뒤집히는 자리가 하나 남았다. 도움말은 마지막에 오는 것이
#   자연스럽기도 하다. 옮긴 자리는 파일 끝, 고지문 바로 앞이다.

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
                   + (" 이번 주 재조회 실패 — 마지막 성공 캐시를 표시 중입니다."
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
st.caption("증권사 리서치·IR 원문은 미연동입니다. 아래는 실제 수집한 가격·거래량·게시 투자지표의 관찰과 정량 해석이며, 사건·원인을 추정해 서술하지 않습니다. (실제 뉴스 기사는 위 '시장·글로벌·뉴스 컨텍스트'에 원문 링크로 표시됩니다.)")
st.markdown(f"[{resolved_name}] 가격·지표 관찰의 시간축 3단계 정리")

n1, n2, n3 = st.columns(3)
with n1:
    dd = news_tf['daily_drivers']
    st.markdown(f"""
    <div style='background: #161D2A; padding: 20px; border-radius: 14px; '>
        <h4 style='color: #ff453a !important; margin-top:0;'>1. 오늘의 변동 요인 ({dd.get('date') or '기준일 미상'})</h4>
        <p style='font-weight: bold; color: #F3F6FA;'>{dd['title']}</p>
        <p style='font-size: 15px; color: #9DAABC;'><b>관찰 내용</b>: {dd['impact']}</p>
        <span style='font-size: 13px; color: #9DAABC;'>출처: {dd['source']} | 성향: {dd['sentiment']}</span>
    </div>
    """, unsafe_allow_html=True)

with n2:
    mc = news_tf['medium_catalysts']
    st.markdown(f"""
    <div style='background: #161D2A; padding: 20px; border-radius: 14px; '>
        <h4 style='color: #F2B84B !important; margin-top:0;'>2. 중기 촉매 ({mc.get('timeframe', '1~3개월')})</h4>
        <p style='font-weight: bold; color: #F3F6FA;'>{mc['title']}</p>
        <p style='font-size: 15px; color: #9DAABC;'><b>정량 해석</b>: {mc['impact']}</p>
        <span style='font-size: 13px; color: #9DAABC;'>출처: {mc['source']} | 성향: {mc['sentiment']}</span>
    </div>
    """, unsafe_allow_html=True)

with n3:
    ln = news_tf['long_narratives']
    st.markdown(f"""
    <div style='background: #161D2A; padding: 20px; border-radius: 14px; '>
        <h4 style='color: #35C98B !important; margin-top:0;'>3. 장기 구조적 서사 ({ln.get('timeframe', '6~12개월')})</h4>
        <p style='font-weight: bold; color: #F3F6FA;'>{ln['title']}</p>
        <p style='font-size: 15px; color: #9DAABC;'><b>정량 해석</b>: {ln['impact']}</p>
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
        user_pos_advice = f"현재 평단가({user_entry_price:,.0f}원)가 고점 부근입니다. 무분별한 물타기는 위험하며 반등 시 1차 비중 30% 축소를 권장합니다."
    elif user_entry_price >= realtime_price * 1.05:
        user_pos_tag = "어깨 가격 (고점 부근)"
        user_pos_color = "#F2B84B"
        user_pos_advice = f"평단가 대비 손실 구간({pnl_pct:.1f}%)입니다. 20일선 지지 안착 확인 전까지 추가 매수를 유의하세요."
    elif user_entry_price >= realtime_price * 0.95:
        user_pos_tag = "허리 가격 (평균 구간)"
        user_pos_color = "#35C98B"
        user_pos_advice = f"평단가 부근 형성 중입니다. 20일선 수급 안착 시 현재 보유량을 유지하며 관망합니다."
    elif user_entry_price >= realtime_price * 0.85:
        user_pos_tag = "무릎 가격 (저점 진입)"
        user_pos_color = "#4C8DFF"
        user_pos_advice = f"수익 구간({pnl_pct:+.1f}%)입니다. 1차 목표가({tp_1st:,.0f}원) 도달 시 분할 익절을 고려하세요."
    else:
        user_pos_tag = "발목 가격 (최저점 매수)"
        user_pos_color = "#4C8DFF"
        # ⚠️ 라운드 188 — '우수 진입 포지션'·'극대화' 는 우리가 잰 것이
        #   아니다. 아는 사실은 '평단이 현재가보다 많이 아래'라는 산술뿐이다.
        user_pos_advice = (f"평단이 현재가보다 크게 아래입니다({pnl_pct:+.1f}%). "
                           f"이 자리가 유리했는지는 측정하지 않았습니다.")

    sma_20_curr = tech_df['sma_20'].iloc[-1]
    
    final_score = four_scores.get('final_quant_score', 50)

    if final_score >= 68:
        add_buy_status = f"<b>매수 (비중 확대)</b><br><span style='font-size:13px; color:#9DAABC;'>단기 목표가 {tp_1st:,.0f}원 도달 시 익절</span>"
        add_buy_color = "#35C98B"
    elif final_score >= 50:
        add_buy_status = f"<b>관망 (보유 비중 유지)</b><br><span style='font-size:13px; color:#9DAABC;'>물타기 금지 / {tp_1st:,.0f}원 반등 시 매도</span>"
        add_buy_color = "#F2B84B"
    else:
        add_buy_status = f"<b>매도 (비중 축소)</b><br><span style='font-size:13px; color:#9DAABC;'>위험 구간 / {sl_1st:,.0f}원 이탈 시 전량 손절</span>"
        add_buy_color = "#ff453a"


    water_msg = ""
    if user_entry_price > tp_1st and realtime_price < tp_1st:
        add_q = max(1, int(user_quantity * (user_entry_price - tp_1st) / (tp_1st - realtime_price)))
        add_cost = add_q * realtime_price
        water_msg = f"<div style='margin-top:16px; background:#1C2635; padding:12px 16px; border-radius:10px; border-left: 4px solid #F2B84B;'><p style='margin:0; font-size:15px; color:#F3F6FA;'><b>맞춤형 물타기(평단가 인하) 시뮬레이션</b></p><p style='margin:4px 0 0 0; font-size:13px; color:#9DAABC;'>현재가 기준 <b>약 {add_q:,}주 ({add_cost:,.0f}원)</b> 추가 매수 시, 평단가를 AI 1차 목표가(<b>{tp_1st:,.0f}원</b>)로 낮춰 본전 탈출이 가능합니다.</p></div>"
    elif user_entry_price > realtime_price and user_entry_price <= tp_1st:
        water_msg = f"<div style='margin-top:16px; background:#1C2635; padding:12px 16px; border-radius:10px; border-left: 4px solid #35C98B;'><p style='margin:0; font-size:13px; color:#9DAABC;'>현재 평단가가 AI 1차 목표가({tp_1st:,.0f}원)보다 낮아, 본전 탈출을 위한 무리한 추가 물타기 없이 목표가 도달 시 수익 전환이 가능합니다.</p></div>"
    elif user_entry_price > 0:
        water_msg = f"<div style='margin-top:16px; background:#1C2635; padding:12px 16px; border-radius:10px; border-left: 4px solid #4C8DFF;'><p style='margin:0; font-size:13px; color:#9DAABC;'>현재 수익 구간입니다. 신규 매수(불타기) 시 평단가가 높아지므로, 잔여 물량은 보유 유지 및 단기 익절 대응을 권장합니다.</p></div>"
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
                <p style='margin:2px 0 0 0; font-size:20px; color:{_TOK["up"] if pnl_val>=0 else _TOK["down"]}; font-weight:bold;'>{pnl_val:+,.0f} 원 ({pnl_pct:+.2f}%)</p>
            </div>
            <div style='background:#161D2A; padding:12px; border-radius:10px; text-align:center;'>
                <p style='margin:0; font-size:13px; color:#9DAABC;'>매수 / 매도 전략</p>
                <p style='margin:2px 0 0 0; font-size:15px; color:{add_buy_color};'>{add_buy_status}</p>
            </div>
        </div>
        <p style='margin:0; font-size:15px; color:#F3F6FA;'><b>맞춤 대응 가이드</b>: {user_pos_advice}</p>
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
            <p style='margin:0; font-weight:bold; color:#35C98B;'>종목 기본 매력도 세부 기여 내역 ({four_scores['stock_quality_score']}점)</p>
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
            <p style='margin:0; font-weight:bold; color:#F2B84B;'>현재 매매 적합도 주요 진단 요인 ({four_scores['trading_timing_score']}점)</p>
            <p style='margin:4px 0; color:{wr_col}; font-size:13px;'>[관찰 승률] 20일 유사패턴 과거 관찰 승률: {fmt_pct(_wr, signed=False)} (전략 표본 {four_scores.get('eff_sample_size', 0):.0f}건 · {four_scores.get('sample_tier', '-')})</p>
            <p style='margin:4px 0; color:{pe_col}; font-size:13px;'>[경로 우위] 20일 평균 수익률: {fmt_pct(_pe)}</p>
            <p style='margin:4px 0; color:{nr_col}; font-size:13px;'>[미도달 비중] 목표가·손절가 모두 미도달: {fmt_pct(_nr, signed=False)}</p>
            <p style='margin:4px 0; color:#4C8DFF; font-size:13px;'>[게이트 판정] <code>{four_scores['gate_reason']}</code></p>
        </div>
        """, unsafe_allow_html=True)

    blocks = four_scores.get('top3_block_reasons', [])
    if blocks:
        # 라운드 187 — 'TOP 3' 를 뗐다. 이 목록은 순위가 아니라
        # **추천 필수조건**이고, 순위에 정보가 있다는 근거가 없다(R110).
        st.markdown("**추천 필수조건 미충족**\n\n" + "\n".join(f"- {b}" for b in blocks))
    else:
        st.markdown("**추천 필수조건 전부 통과**")

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
            <p style='margin: 4px 0; font-size:15px;'>- <b>상대적 밸류에이션 룸</b>: <b style='color:{_signed_col(per_upside['upside_room_pct'])};'>{fmt_pct(per_upside['upside_room_pct'])}</b></p>
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
    """탭 상단의 **관점 점수** 한 줄.

    ⚠️ 라운드 187 — 여기가 `매수  78점 · 이 탭 단독 판정` 으로 찍혀
      운영 판정처럼 읽혔다. 중앙 판정이 '추천 제외'인 종목에서도 그랬다.
      낱말은 엔진에서 우호도로 바꿨고(`_verdict_from_score`), 이 캡션은
      **어느 관점이며 운영 판정이 아니라는 것**을 적는다.
    """
    t = _TAB_VERDICT.get(key)
    if not t:
        return
    score_txt = "—" if t['score'] is None else f"{t['score']}점"
    st.markdown(
        f"<div style='background:#161D2A;border-left:6px solid {t['color']};"
        f"border-radius:10px;padding:12px 16px;margin-bottom:12px;'>"
        f"<span style='font-size:22px;font-weight:700;color:{t['color']};'>{t['verdict']}</span>"
        f"<span style='font-size:17px;font-weight:700;color:#F3F6FA;margin-left:12px;'>{score_txt}</span>"
        f"<span style='color:#9DAABC;font-size:13px;margin-left:8px;'>"
        f"{_uk._esc(t.get('label') or '')} 관점만 본 점수 · 매매 판정 아님 "
        f"(오늘 살지 말지는 맨 위 결론에서 봅니다)</span>"
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
    # ⚠️ 라운드 188 — '7대 적중률 극대화' 는 근거가 없다(라운드 36: 목표
    #   배수 0.4R~3.0R 어느 것도 세 구간 모두에서 양수가 아니었다). 게다가
    #   같은 화면 아래가 *"다중 모델 앙상블은 구현되어 있지 않습니다"* 라고
    #   적어 한 화면이 두 말을 했다. 실제로 하는 일(7단계)만 적는다.
    st.subheader(f"[{resolved_name}] — 자기유사 예측 파이프라인 (7단계)")
    
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
            <b>⑦ 표본 통제</b>: 유사패턴 표본 {sim_res.get('match_count', 0)}건 · 등급 <b>{sim_res.get('sample_tier_label', '-')}</b> — 10건 미만이면 확률 미표시
        </p>
        <p style='font-size: 12px; color:#9DAABC; margin: 8px 0 0 0;'>
            ※ 거래량·수급·RSI를 유사도에 반영하는 다중거리 모델과 다중 모델 앙상블은 구현되어 있지 않습니다.
            유사도는 Pearson 상관과 DTW만 사용합니다.
        </p>
    </div>
    """, unsafe_allow_html=True)

    if not sim_res.get('probabilities_shown', False):
        st.warning(f"**[명세 §11 표본 통제]** 유사패턴 표본 {sim_res.get('match_count', 0)}건 — "
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
            <span style='font-size: 17px; font-weight: bold; color: #F3F6FA;'>최종 예측 상승확률 (베이지안 사후보정): </span>
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
                "유사패턴 표본": h.get('match_count', 0),
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
            # 라운드 98 — '최적 보유기간'은 매매 지시가 아니라 **유사패턴을
            # 몇 봉까지 보고 골랐나**이다. 실행 보유기간(20거래일)과 다른
            # 값이라 이름을 갈랐다.
            {'label': '유사패턴 최적 관찰기간',
             'value': sim_res.get('optimal_holding_period_str', '산출 불가'),
             'sub': '평균수익 × 승률 × 일치도 / √기간 · 매매 지시 아님'},
            {'label': '적용 상관 임계값',
             'value': f"rho ≥ {sim_res.get('rho_cutoff_applied', rho_cutoff)}",
             'sub': '왼쪽에서 설정한 값 그대로'},
        ], theme=_theme)

        # ── 미선정이면 '고장'이 아니라 '판정'임을 근거와 함께 보여준다 ─────────
        if not sim_res.get('optimal_holding_period_days'):
            _elig = sim_res.get('horizon_eligibility') or {}
            _near = sim_res.get('horizon_nearest_miss')
            _nosam = sim_res.get('horizons_without_sample') or []
            with st.expander("유사패턴 최적 관찰기간이 왜 미선정인가 — "
                             "지평별 판정 근거", expanded=True):
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
            mark = " " if H in core else ""
            if H not in avail_h:
                return f"{H}일{mark} (표본없음)"
            return f"{H}일{mark}"

        sel_h = st.radio(
            "예측 기간 선택 (기본 40일 · 는 전략 유형에 맞는 핵심 기간)",
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

        # 보유 여부를 먼저 알아야 한다 — 보유자 기준선을 그릴지가 여기서 갈린다
        _my = None
        for _p in (st.session_state.get('positions') or []):
            if _p.ticker == target_ticker:
                _my = _p.average_buy_price
                break
        if _my is None and user_entry_price > 0:
            _my = float(user_entry_price)
        # 값이 새더라도 화면이 스스로 잡는다 (라운드 51).
        # 평단이 현재가의 1/5 미만이거나 5배를 넘으면 **다른 종목 값**이다 —
        # 실제로 금호건설 평단 10,246원이 LG생활건강(330,000원) 차트에
        # 그려졌다. 위젯 키는 고쳤지만, 한 겹 더 막는다.
        #
        # ⚠️ 이 판정은 기준선을 **고르기 전에** 해야 한다. 뒤에 두었더니
        # "평단을 표시하지 않았습니다"라고 적어 놓고 그 평단으로 켠 보유자
        # 선은 그대로 그려졌다 (라운드 53).
        if _my and curr_price and not (curr_price * 0.2 <= _my <= curr_price * 5):
            st.caption(
                f"입력된 평균 매수가 {_my:,.0f}원이 현재가 {curr_price:,.0f}원과 "
                f"자릿수가 맞지 않아 차트에 표시하지 않았습니다 — 다른 종목의 "
                f"값일 수 있습니다. 사이드바에서 확인해 주세요.")
            _my = None

        # 기준선들 — 모두 참고용이며 경로 분포 계산에는 사용하지 않는다.
        #
        # ⚠️ 라운드 53 — 여기가 마지막까지 남아 있던 **또 하나의 가격 경로**였다.
        # 이 차트만 four_scores 를 직접 읽어서, 배너는 CORE 의 신규 매수자 값을
        # 쓰는데 차트는 보유자 값(target_tech_1st·stop_loss_price)을 '1차 목표가'
        # '손절가'라는 **누구 기준인지 없는 이름**으로 같이 그렸다. 같은 화면에
        # 이름이 같고 숫자가 다른 선이 두 개 있었다는 뜻이다 (CLAUDE.md §4).
        #
        # 그리고 정작 **실제로 걸어야 할 실행 진입가**가 빠져 있었다. 목표와
        # 손절만 있고 어디서 사는지가 없으면 그림이 완성되지 않는다.
        _AX = [(four_scores.get('displayed_fair_value'), '#4C8DFF', ':', 1.1,
                '펀더멘털 적정가 (장기)'),
               (CORE.get('pullback_zone'), '#35C98B', '-', 1.8,
                '실행 진입가 · 신규'),
               (CORE.get('new_target'), '#4C8DFF', '-', 1.5, '1차 목표 · 신규'),
               (CORE.get('new_stop'), '#ff453a', '-', 1.5, '손절 · 신규'),
               (four_scores.get('target_tech_2nd'), '#4C8DFF', ':', 1.1,
                '2차 목표')]
        # 돌파 매수가는 돌파를 기다리는 자리에서만 뜻이 있다 — 늘 그리면 소음이다
        if (CORE.get('bucket') or '').startswith('돌파'):
            _AX.append((CORE.get('breakout_price'), '#35C98B', ':', 1.3,
                        '돌파 매수가 · 신규'))
        # 보유자 기준선은 실제로 갖고 있을 때만. 신규 매수자에게는 남의 숫자다
        if _my:
            _AX += [(CORE.get('hold_trim'), '#4C8DFF', '-.', 1.2,
                     '1차 목표 · 보유자'),
                    (CORE.get('hold_stop'), '#ff453a', '-.', 1.2,
                     '손절 · 보유자')]
        for _v, _c, _ls, _lw, _lb in _AX:
            if _v is None:
                continue
            ax_p.axhline(_v, color=_c, linestyle=_ls, linewidth=_lw,
                         alpha=0.85, label=f"{_lb} ({_v:,.0f})")
        if _my:
            ax_p.axhline(_my, color='#F2B84B', linestyle='--', linewidth=1.8,
                         label=f"내 평균 매수가 ({_my:,.0f})")
            ax_p.fill_between(days, min(_my, curr_price), max(_my, curr_price),
                              color=(_TOK['up'] if curr_price >= _my else _TOK['down']), alpha=0.07)

        title_kind = "예측" if show_forecast else "과거 유사사례 관찰"
        ax_p.set_title(
            f"[{resolved_name}] {sel_h}영업일 {title_kind} — 유사패턴 표본 {h['match_count']}건 · {h['tier_label']}",
            color='#F3F6FA', fontsize=13)
        ax_p.set_xlabel("미래 영업일 (Day)", color='#9DAABC')
        ax_p.set_ylabel(f"주가 ({unit_str})", color='#9DAABC')
        ax_p.tick_params(colors='#F3F6FA')
        ax_p.grid(True, color='#1C2635', linestyle='--')
        ax_p.legend(facecolor='#161D2A', edgecolor='#1C2635', labelcolor='#F3F6FA', fontsize=8)
        st.pyplot(fig_pred)

        if not show_forecast:
            st.warning(f"유사패턴 표본 {h['match_count']}건 — {h['tier_label']}. "
                       f"위 그래프는 **미래 예측이 아니라 과거 유사사례의 관찰 분포**입니다.")

        g1, g2, g3, g4, g5, g6 = st.columns(6)
        g1.metric("유사패턴 표본", f"{h['match_count']}건", h['tier_label'])
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

    # ── 세 가격 축 (라운드 28) ──────────────────────────────────────────
    # '적정가' 한 숫자가 지평이 다른 세 질문에 동시에 답하려다 26,350원짜리
    # 종목에 21,218원이 권장 매수가로 붙었다. 축을 갈라서 먼저 보여 준다.
    _AX = four_scores.get('price_axes') or {}
    if _AX:
        st.markdown("#### 가격은 하나가 아닙니다 — 질문이 셋이라서")
        _ax_c1, _ax_c2, _ax_c3 = st.columns(3)
        _b, _m, _e = (_AX.get('value_band') or {}, _AX.get('market_fair') or {},
                      _AX.get('entry') or {})
        with _ax_c1:
            st.caption("① 이 기업의 값어치는? · 수년")
            if _b.get('available'):
                st.markdown(f"### {_b['low']:,.0f} ~ {_b['high']:,.0f}원")
                st.caption(_md_safe(
                    f"넓게 보면 {_b['wide_low']:,.0f}~{_b['wide_high']:,.0f}원 · "
                    f"신뢰도 {_b['confidence']:.0f}점 ({_b['tier_ko']})"))
                # 라운드 38 — 범위의 **폭**을 말해 준다. LX인터내셔널이
                # 31,860~78,511원(2.5배)이었는데 화면은 그냥 범위만 보여 줬다.
                # 폭이 2배를 넘으면 "적정가가 좋다"고 읽으면 안 된다.
                _bw = ((_b['wide_high'] / _b['wide_low'])
                       if _b.get('wide_low') else None)
                if _bw and _bw >= 2.0:
                    st.warning(f"범위 폭이 **{_bw:.1f}배**입니다 — 모델들이 서로 "
                               f"크게 다른 값을 냈다는 뜻이라, 이 숫자로 "
                               f"'저평가'를 단정하지 마세요.")
                st.caption(_md_safe(_b['basis']))
            else:
                st.markdown("### 미산출")
                st.caption(_md_safe(_b.get('why', '')))
        with _ax_c2:
            st.caption("② 지금 시장이 매길 값은? · 수개월")
            if _m.get('available'):
                st.markdown(f"### {_m['price']:,.0f}원")
                st.caption(_md_safe(_m['basis']))
            else:
                st.markdown("### 미산출")
                st.caption(_md_safe(_m.get('why', '')))
        with _ax_c3:
            st.caption("③ 그래서 얼마에 사나? · 수일")
            if _e.get('available'):
                st.markdown(f"### {_e['price']:,.0f}원")
                if _e.get('gap_pct') is not None:
                    st.caption(f"현재가 대비 {_e['gap_pct']:+.1f}%"
                               + (f" · 손절 {_e['stop']:,.0f}원 · 1차 목표 "
                                  f"{_e['target1']:,.0f}원 (손익비(진입가·1차) {_e['rr']})"
                                  if _e.get('stop') and _e.get('target1') else ""))
                st.caption(_md_safe(_e['basis']))
            else:
                st.markdown("### 미산출")
                st.caption(_md_safe(_e.get('why', '')))
        # 업황조정 가치 — 사양 §3의 가운데 칸.
        # 조정이 0 이어도 **왜 0 인지**를 적는다. 칸만 만들고 값을 비우면
        # 사용자는 '반영됐겠거니' 하고 읽는다.
        _cy = _AX.get('cycle_band') or {}
        if _cy.get('available'):
            st.markdown("###### 업황조정 가치 — 섹터 사이클을 얹으면")
            _cy1, _cy2 = st.columns([1, 2])
            with _cy1:
                if _cy.get('adjusted'):
                    st.markdown(f"**{_cy['low']:,.0f} ~ {_cy['high']:,.0f}원** "
                                f"({_cy['adj_pct']:+.1f}%)")
                else:
                    st.markdown("**업황 미반영** (조정 0.0%)")
            with _cy2:
                if _cy.get('linked'):
                    _mm = []
                    if _cy.get('rs60') is not None:
                        _mm.append(f"S&P500 대비 {_cy['rs60']:+.1f}%p")
                    if _cy.get('mom60') is not None:
                        _mm.append(f"프록시 60일 {_cy['mom60']:+.1f}%")
                    if _cy.get('last_date'):
                        _mm.append(f"최종 수신 {_cy['last_date']}"
                                   + ("" if _cy.get('fresh', True)
                                      else " (신선하지 않음)"))
                    st.caption(_md_safe(f"{_cy.get('sector_ko') or '업종'} · "
                                        + " · ".join(_mm)))
                    if _cy.get('proxy_note'):
                        st.caption(_md_safe(f"대용 지표: {_cy['proxy_note']}"))
                    _rl = set(_cy.get('real_linked') or [])
                    _ri = _cy.get('real_indicators') or []
                    if _ri:
                        _un = [x for x in _ri if x not in _rl]
                        st.caption(_md_safe(
                            "이 업종의 진짜 선행지표 — 연동: "
                            + (", ".join(sorted(_rl)) if _rl else "없음")
                            + " · 미연동: " + ", ".join(_un)))
                else:
                    st.caption(_md_safe(_cy.get('why') or '업종 미연동'))
            if _cy.get('why') and not _cy.get('adjusted'):
                st.caption(_md_safe(_cy['why']))
        # 업종 원장 실측 (라운드 54b) — 프록시 모멘텀이 '지금 업황'이라면
        # 이것은 '이 업종에서 우리 매수권 신호가 과거에 실제로 맞았는가'다.
        # 표시 전용 — 점수·게이트 미사용. 표본이 작으면 그 사실을 먼저 쓴다.
        try:
            import sector_cycle as _scp
            _sp = _scp.ledger_perf(val_eval.get('sector'))
            if _sp:
                _sp_head = (f"표본 {_sp['n']}건뿐이라 판단 근거로 쓰기 이릅니다"
                            if _sp.get('small') else
                            f"적중 {_sp['hit']:.1f}% (Wilson 하한 "
                            f"{_sp['wilson_low']:.1f}) · 비용후 평균 "
                            f"{_sp['ev']:+.3f}%p")
                st.caption(_md_safe(
                    f"이 업종({_sp['sector']}) 매수권 신호의 과거 실측 — "
                    f"{_sp_head} · n {_sp['n']:,} · 개발 구간 · 표시 전용"))
        except Exception:                                       # noqa: BLE001
            pass                       # 실측 표 하나 때문에 축 화면이 죽지 않는다
        for _n in (_AX.get('notes') or []):
            st.caption(_md_safe(f"· {_n}"))
        if not _AX.get('consistent'):
            st.warning("세 축이 서로 어긋납니다 — 위 문구를 먼저 읽어 주세요.")
        _pol = _AX.get('policy') or {}
        if _pol.get('score_cap') is not None:
            st.caption(f"판정 반영: {_pol.get('why', '')}")
        st.divider()

    st.subheader(f"[{resolved_name}] - 시장조정 펀더멘털 적정가")

    target_price = four_scores.get('target_fundamental', realtime_price)
    disp_price = four_scores.get('displayed_fair_value')
    prelim_range = four_scores.get('preliminary_range_str', '미산출')
    base_fair_val = four_scores.get('base_fair_value', target_price)
    upside_pct = four_scores.get('upside_pct')
    upside_eval = four_scores.get('upside_eval', '가치판단 보류')
    # 폴백도 0 — 근거 없는 −2% 를 화면 기본값 자리에 숨기지 않는다 (라운드 44)
    mkt_adj_pct = four_scores.get('market_adjustment_pct', 0.0)
    mkt_adj_why = four_scores.get('market_adjustment_why')
    conf_score = four_scores.get('fair_value_confidence', 0.0)
    # 장기 가치 참고선 — 적정가 × 안전마진. **오늘의 실행가가 아니다.**
    # 라운드 25 에 실행가 자리에서 폐기했고 37 에 배너에서 걷어냈는데,
    # 이 화면만 '권장 매수가 / 안전 매수 구간'이라는 옛 이름으로 남아
    # 있었다(라운드 71 계보 감사에서 발견). 이름을 코드까지 옮긴다 —
    # 주석에만 적어 두면 다음 사람이 또 실행가로 읽는다.
    _value_ref = four_scores.get('recommended_buy_price')
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
        st.error(f"적정가 신뢰도 {conf_score:.0f}점 — {fv_note}. 중심 적정가와 장기 가치 참고선을 산출하지 않았습니다.")

    disp_price_str = f"{disp_price:,.0f}{unit_str}" if disp_price is not None else "산출 보류"
    if upside_pct is None:
        upside_display_str = f"<b style='color:#9DAABC;'>상승여력 미산출</b> ({upside_eval})"
    else:
        upside_color = _TOK['up'] if upside_pct > 0 else _TOK['down']
        upside_display_str = f"현재가 대비 <b style='color:{upside_color};'>{upside_pct:+.1f}%</b> ({upside_eval})"

    if _value_ref is None:
        value_ref_str = "미산출 (신뢰도 미달)"
        # ⚠️ 라운드 179 — 라운드 178 이 진입 위치에서 고친 것과 **같은 모양**
        #   이 여기 남아 있었다. 장기 가치 참고선(적정가 − 안전마진)이 없다고
        #   **적정가 대비 위치까지** 판정을 포기하고 '판정 불가'를 적었다.
        #   화면 census 로 현대건설을 훑으니 이 자리 하나가 마지막으로
        #   남아 있었다 — 바로 위 줄에서 `상승여력 -24.8%` 를 적어 놓고서.
        #   참고선은 못 냈다고 말하되, **아는 값(적정가 대비)은 말한다** (§3).
        if upside_pct is None:
            value_eval_str = "판정 불가 (적정가·참고선 모두 미산출)"
            value_eval_color = _TOK['tx3']
        else:
            value_eval_str = f"참고선 미산출 · 적정가 대비 {upside_pct:+.1f}%"
            # 한국 관행 — 오르면 빨강, 내리면 파랑 (§5 · 라운드 174)
            value_eval_color = (_TOK['up'] if upside_pct > 0
                                else _TOK['down'])
    else:
        value_ref_str = f"{_value_ref:,.0f}{unit_str} 이하"
        # '안전 매수 구간'이라고 쓰지 않는다 — 이 선 아래로 내려와도
        # 실행 게이트는 따로 판단한다. 가치 판정과 매수 신호는 다른 말이다.
        value_eval_str = ("가치 기준 저평가 구간" if realtime_price <= _value_ref
                          else "가치 기준 참고선 위")
        value_eval_color = "#35C98B" if realtime_price <= _value_ref else "#F2B84B"

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
                <p style="margin: 0; font-size: 13px; color: #9DAABC;">업황조정 영향: <b style="color:#F2B84B;">{mkt_adj_pct:+.1f}%</b></p>
                <p style="margin: 4px 0 0 0; font-size: 13px; color: #9DAABC;">적정가 신뢰도: <b style="color:#4C8DFF;">{conf_score:.0f} / 100점</b></p>
            </div>
        </div>
        <hr style="border-color: #222C3C; margin: 16px 0;">
        <div style="display: flex; justify-content: space-around; text-align: center; flex-wrap: wrap;">
            <div style="margin: 4px 8px;">
                <span style="font-size: 13px; color: #9DAABC;">장기 가치 참고선 (안전마진 {mos_pct:.0f}%)</span><br>
                <b style="font-size: 17px; color: #35C98B;">{value_ref_str}</b>
            </div>
            <div style="margin: 4px 8px;">
                <span style="font-size: 13px; color: #9DAABC;">핵심 평가 모델</span><br>
                <b style="font-size: 16px; color: #F3F6FA;">기업특성 기반 선택적 다중 모델</b>
            </div>
            <div style="margin: 4px 8px;">
                <span style="font-size: 13px; color: #9DAABC;">장기 가치 대비</span><br>
                <b style="font-size: 16px; color: {value_eval_color};">
                    {value_eval_str}
                </b>
            </div>
        </div>
    </div>
    ''', unsafe_allow_html=True)

    # 두 가격의 역할을 이 화면에도 적는다 (라운드 56 에 배너에 적은 것과
    # 같은 말이다). 위 참고선은 '가치상 얼마면 싼가'이고, 오늘 실제로 걸어
    # 둘 가격은 중앙 판정이 낸 실행 진입가 하나뿐이다. 새 숫자를 만들지
    # 않고 CORE 값을 그대로 옮긴다 (§4 — 화면 값은 한 곳에서 나온다).
    _exec_entry = (CORE or {}).get('pullback_zone')
    st.caption(_md_safe(
        '위 참고선은 장기 가치 기준입니다 — 여기까지 내려와도 매수 신호가 '
        '켜지는 것은 아닙니다. 오늘의 실행 진입가는 '
        + (f'{_exec_entry:,.0f}{unit_str}' if _exec_entry else '산출 불가')
        + ' (종합 결론 배너와 같은 값).'))

    # 업황조정이 0 이면 **왜 0 인지** 바로 밑에 적는다.
    # 라운드 44 전까지 이 자리는 근거 없는 −2% 상수였고, 화면은 그걸
    # '시장조정'이라고만 불렀다. 수치가 없는 것보다 나쁜 건, 근거 없는
    # 수치를 근거 있는 척 보여 주는 것이다.
    if mkt_adj_why:
        st.caption(_md_safe(f"업황조정 {mkt_adj_pct:+.1f}% — {mkt_adj_why}"))

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
    <tr><td><b>가치 기준선 조건</b></td><td>{' · '.join(('충족' if ok else '미충족') + ' ' + lb for lb, ok in (val_eval.get('buy_price_checks') or []))}</td></tr>
    <tr><td><b>평가 시점 ROE / PER / PBR</b></td><td>{fmt_num(val_eval.get('roe'), '.2f', '%')} / {fmt_num(val_eval.get('per'), '.2f', '배')} / {fmt_num(val_eval.get('pbr'), '.2f', '배')} (BPS {fmt_num(val_eval.get('bps'), ',.0f', unit_str)})</td></tr>
    <tr><td><b>미수신 입력 지표</b></td><td>{', '.join(val_eval.get('missing_inputs') or []) or '없음'}</td></tr>
    <tr><td><b>가중중앙값 원시 괴리율</b></td><td>{fmt_pct(val_eval.get('raw_upside_pct'))} → 윈저화 후 {fmt_pct(val_eval.get('upside_pct'))}</td></tr>
    <tr><td><b>적정가 신뢰도</b></td><td>{val_eval.get('fair_value_confidence', 0):.0f}점 — {_uk._esc_md(val_eval.get('fair_value_status_note', ''))}</td></tr>
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
                <td><b style='color:#35C98B;'>상승 시나리오</b></td>
                <td>20일선 복귀(`{curr_price*(1 + atr_val*0.5):,.0f}{unit_str}`) + 거래량 1.2배 + 외인 전환</td>
                <td><b>{bull_range_low:,.0f}{unit_str} ~ {bull_range_high:,.0f}{unit_str}</b></td>
                <td>{bull_target*0.95:,.0f}{unit_str} / {bull_target:,.0f}{unit_str}</td>
                <td>{bull_stop:,.0f}{unit_str} 하회 시 무효화</td>
                <td>1차 분할 매수 검토</td>
            </tr>
            <tr>
                <td><b style='color:#F2B84B;'>횡보 시나리오</b></td>
                <td>60일선 지지(`{curr_price*(1 - atr_val*0.2):,.0f}{unit_str}`) + 거래량 감소 및 RSI 리셋</td>
                <td><b>{side_range_low:,.0f}{unit_str} ~ {side_range_high:,.0f}{unit_str}</b></td>
                <td>{side_target:,.0f}{unit_str} / N/A</td>
                <td>{side_stop:,.0f}{unit_str} 이탈 시 무효화</td>
                <td>관망 및 지지 확인 후 접근</td>
            </tr>
            <tr>
                <td><b style='color:#ff453a;'>하락 시나리오</b></td>
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
    #
    # ⚠️ 라운드 42 — 이 표는 중앙 판정을 안 쓰고 four_scores 원본을 읽어서,
    # 같은 화면 안에서 배너와 다른 값을 보여 줬다 (실측: 대우건설).
    #     배너   권장 매수가 14,963원 · 1차 목표 16,562원
    #     이 표  권장 매수가 "적정가 신뢰도 미달 (미산출)" · 1차 목표 17,931원
    # 하나는 숫자, 하나는 '미산출'. 사용자가 어느 쪽을 믿어야 할지 알 수 없다.
    # 두 값은 **다른 것**이다 — 배너는 실행 진입가(변동성 기반),
    # 이 표는 적정가 기반 장기 참고선. 이름이 같아서 충돌했다.
    # 이름을 갈라 적고, 실행 가격 행을 별도로 넣어 어느 것이 오늘 쓰는
    # 값인지 분명히 한다.
    st.markdown("목표가격 및 손절·위험선 산출 근거 명시적 표")
    # 물결표를 쓰지 않는다 — 이 문장은 굵게 표시를 의도적으로 쓰므로
    # _md_safe 로 통째로 이스케이프할 수 없고, 물결표 두 개가 짝을 이루면
    # 마크다운이 취소선으로 묶어 사이 글자를 지운다 (라운드 44 실측 결함).
    st.caption("**신규 매수자용 실행 가격**은 아래 1·2행이 아니라 "
               "**'실행 진입가' 행**입니다. 1·2행은 분기 실적 기반 **장기 "
               "가치 참고선**이라 오늘 살 자리와 다를 수 있습니다.")
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
                <td><b>2. 장기 가치 참고선 (적정가 − 안전마진)</b></td>
                <td><b style='color:#9DAABC;'>{f"{four_scores['recommended_buy_price']:,.0f}원" if four_scores.get('recommended_buy_price') is not None else "적정가 신뢰도 미달 (미산출)"}</b></td>
                <td>안전마진 {four_scores.get('margin_of_safety_pct', 15):.0f}% 적용 —
                    <b>오늘의 매수가가 아니다</b> (분기 실적 기반 장기 기준)</td>
            </tr>
            <tr style='background:rgba(53,201,139,0.06);'>
                <td><b>실행 진입가 (오늘 쓰는 값)</b></td>
                <td><b style='color:#35C98B;'>{fmt_num((CORE or {}).get('pullback_zone'), ',.0f', '원', na='산출 불가')}</b></td>
                <td>현재가 − 20일 변동성 1σ · 배너·추천 카드와 <b>같은 값</b>
                    (중앙 판정 verdict_core)</td>
            </tr>
            <tr>
                <td><b>3. 기술적 1차 목표가 <span style='color:#9DAABC;'>(보유자 · 현재가 기준)</span></b></td>
                <td><b style='color:#4C8DFF;'>{fmt_num(four_scores.get('target_tech_1st'), ',.0f', '원', na='산출 불가')}</b></td>
                <td>{four_scores.get('target_tech_1st_note', '')}
                    — <b>이미 보유한 사람</b>의 기준. 신규 매수자는
                    실행 진입가 기준 {fmt_num((CORE or {}).get('new_target'), ',.0f', '원', na='미산출')}</td>
            </tr>
            <tr>
                <td><b>4. 기술적 2차 목표가</b></td>
                <td><b style='color:#4C8DFF;'>{fmt_num(four_scores.get('target_tech_2nd'), ',.0f', '원', na='산출 불가')}</b></td>
                <td>{four_scores.get('target_tech_2nd_note', '')}</td>
            </tr>
            <tr>
                <td><b>5. 손절가 <span style='color:#9DAABC;'>(보유자 · 현재가 기준)</span></b></td>
                <td><b style='color:#ff453a;'>{fmt_num(four_scores.get('stop_loss_price'), ',.0f', '원', na='산출 불가')}</b></td>
                <td>{four_scores.get('stop_loss_note', '')}
                    — 신규 매수자는 실행 진입가 기준
                    {fmt_num((CORE or {}).get('new_stop'), ',.0f', '원', na='미산출')}</td>
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
        <h3 style="color:#F3F6FA; margin-top:0;">DeMARK 9-13 결합신호 종합 대시보드</h3>
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
        _net_color = _TOK['pos'] if (_net_perf or 0) >= 0 else _TOK['neg']
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
            <p style='color:#F2B84B; font-size:13px;'>{cost_metrics['calibration_status']}</p>
        </div>
        """, unsafe_allow_html=True)
        
    with c2:
        st.markdown(f"""
        <div style='background: #161D2A; border-radius: 16px; padding: 20px;'>
            <h4 style='color: #35C98B !important; margin-top:0;'>SR 11-7 모델 리스크 관리 감사 카드 (Section 13)</h4>
            <p>- <b>기준시점 ($t_{{ref}}$)</b>: <b>{snapshot.get('t_ref') if snapshot else '미상'}</b></p>
            <p>- <b>미래 데이터 차단 건수</b>: <b>{f"{snapshot.get('blocked_future_count')} 건 (PTA 통제 완료)" if snapshot else '미산출 — 스냅샷 없음'}</b></p>
            <p>- <b>Shapley-DCLR 미래 누수율</b>: <b style='color:#F2B84B;'>{snapshot.get('shapley_dclr_status') if snapshot else '미산출'}</b></p>
            <p>- <b>중복 유사 패턴 제거</b>: <b>적용 (지평별 최소 H영업일 이격)</b></p>
            <p>- <b>SR 11-7 무결성 루브릭</b>: <b style='color:{"#35C98B" if sr117_audit.get("is_passed") else "#F2B84B"};'>{sr117_audit.get('total_score', 0)}/100점 ({'통과' if sr117_audit.get('is_passed') else '미달'})</b>
               <span style='font-size:13px; color:#9DAABC;'>— 이중시점 {sr117_audit.get('bitemporal_score',0)}({_uk._esc(sr117_audit.get('bitemporal_note','—'))}) / 연산 {sr117_audit.get('math_score',0)} / 일관성 {sr117_audit.get('consistency_score',0)}{'' if sr117_audit.get('consistency_measured') else ' (미측정 상수)'} / 통계 {sr117_audit.get('stat_score',0)} / 가드레일 {sr117_audit.get('guardrail_score',0)}</span></p>
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
            <p>- <b>패턴 조건부 전략 (20일)</b>: <b style='color:{_perf_col(bench_data['ai_perf'])};'>{fmt_pct(bench_data['ai_perf'], digits=2)}</b></p>
            <p>- <b>동일 종목 무조건 보유</b>: <b style='color:{_perf_col(bench_data['buy_hold_perf'])};'>{fmt_pct(bench_data['buy_hold_perf'], digits=2)}</b></p>
            <p>- <b>20일선 위에서만 보유</b>: <b style='color:{_perf_col(bench_data['trend20d_perf'])};'>{fmt_pct(bench_data['trend20d_perf'], digits=2)}</b></p>
            <p>- <b>KOSPI200 지수</b>: <b style='color:{_perf_col(bench_data['kospi200_perf'])};'>{fmt_pct(bench_data['kospi200_perf'], digits=2)}</b>
               <span style='color:#9DAABC;font-size:13px;'>({bench_data['kospi200_note']})</span></p>
            <hr style='border-color:#1C2635; margin:8px 0;'>
            <p style='font-size:13px; color:#F2B84B; margin:0;'><b>판정</b>: {bench_data['judge_text']}</p>
        </div>
        """, unsafe_allow_html=True)

    with ba2:
        if factor_data.get('available'):
            _alpha_col = _TOK['pos'] if (factor_data['alpha_annual_pct'] or 0) >= 0 else _TOK['neg']
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
                <p style='font-size:13px; color:#F2B84B; margin:0;'>미연동 팩터: {', '.join(factor_data['missing_factors'])} — {factor_data['missing_reason']}</p>
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
            <p style='font-size:12px; color:#9DAABC; margin-top:8px;'>{_uk._esc_md(risk_budget['note'])}</p>
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
               · 왕복 거래비용 {_cost:.2f}% → <b style='color:{_TOK["pos"] if _net_edge > 0 else _TOK["neg"]};'>순 {_net_edge:+.2f}%p</b></p>
            <hr style='border-color:#1C2635; margin:8px 0;'>
            <p style='margin:2px 0; color:{_vcol};'><b>판정</b>: {_verdict}</p>
            <p style='font-size:12px; color:#F2B84B; margin-top:8px;'>{_uk._esc_md(_div['note'])}</p>
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

# ── 최근 업데이트 — 라운드 127 에서 **여기로 내렸다**.
#   종전에는 개장 전 결론 바로 다음(본문 다섯 번째)이었다. 메뉴는
#   이걸 "4. 검증과 이력"으로 묶어 놓는데 화면에서는 훨씬 위에 있어,
#   메뉴 순서를 본문 위치로 바꾸면 거기서 뒤집혔다 (라운드 125 측정).
#   블록이 자기 안에서 데이터를 다 만들고 밖에서 쓰는 곳이 없어
#   통째로 옮길 수 있었다.
# ── 최근 업데이트 (v4) — 제품형 릴리스 노트: 요약 5건 + 전체 보기·필터 ────────
_uh_home = _load_update_history()
if _uh_home and _uh_home.get('days'):
    _days_enr = _pops.enrich_update_history(_uh_home)
    _flat_upd = [{**it, 'date': d['date'], 'version': d['version']}
                 for d in _days_enr for it in d['items']]
    _n_upd = len(_flat_upd)
    # ⚠️ 라운드 98b — 여기 `_VER_NOW['model']` 을 붙여 두고 있었다.
    #   건수는 **모든 커밋**을 센 값인데 버전은 **모델 축 하나**여서
    #   "업데이트 213건 · v2026.08.12.1" 처럼 어긋났다. 그 213건 안에는
    #   8/15 룰북 변경이 들어 있는데 표시는 8/12 였다.
    #   §7 이 말한 '5축이 따로 움직인다'를 한 축으로 대표시킨 것이다.
    #   5축 버전은 이미 상단 칩에 따로 있으므로, 여기는 **건수와 같은
    #   출처**인 최근 갱신일을 쓴다 — 그래야 어긋날 수가 없다.
    _latest_day = str((_days_enr[0] or {}).get('date') or '') if _days_enr else ''
    _upd_head = (f"업데이트 {_n_upd}건 · 최근 {_latest_day}"
                 if _latest_day else f"업데이트 {_n_upd}건")
    st.markdown("<div id='nav-updates'></div>", unsafe_allow_html=True)
    # 사용자 요청: 눌러야 나오게, 아주 간략하게. 평소엔 한 줄만 보인다.
    with st.expander(_upd_head, expanded=False):
        # ⚠️ 라운드 180 — 사용자가 이 목록의 한 줄을 **지금 고장난 것**으로
        #   읽었다. *"참고선이 없다고 적정가 대비 위치까지 판정을 포기합니다.
        #   포기하지말고 고쳐줘"* — 그 줄은 **이미 고친 것의 제목**이다.
        #   제목이 커밋 규약상 '고치기 전의 문제'를 적기 때문에, 목록만
        #   훑으면 현재 결함 목록처럼 보인다.
        #   제목을 바꿀 수는 없다(이력 원문이다) — **무엇을 읽고 있는지**를
        #   먼저 밝힌다.
        st.caption("아래는 **이미 반영이 끝난 변경**입니다. 제목은 커밋 규약에 "
                   "따라 **고치기 전의 문제**를 적은 것이라, 지금 남아 있는 "
                   "결함이 아닙니다. 커밋 이력 원문에서 자동 생성하며 손으로 "
                   "쓰지 않습니다.")

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
        st.caption("아래는 **이미 반영이 끝난 변경**입니다 — 제목은 "
                   "**고치기 전의 문제**를 적은 것입니다. 각 줄을 펼치면 왜 "
                   "바꿨는지·무엇이 달라지는지·어떻게 확인했는지가 나옵니다. "
                   "커밋 기록에 없는 항목은 '기록 없음'으로 둡니다 "
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
                # 라운드 99 — 버전은 그날 실제로 발효된 것만 온다.
                # 커밋이 있었다고 축이 움직인 것은 아니므로 빈 날은 그렇게 적는다.
                _meta_u.append(
                    f"버전 {_u['version']} · 커밋 {_u.get('hash', '')}"
                    if _u.get('version')
                    else f"버전 변경 없음 · 커밋 {_u.get('hash', '')}")
                st.caption(" | ".join(_meta_u))
        if len(_sel_upd) > 40:
            st.caption(f"이 카테고리의 나머지 {len(_sel_upd) - 40}건은 아래 표에서 "
                       "보실 수 있습니다.")
            st.dataframe(pd.DataFrame([{
                '날짜': u['date'], '버전': u['version'] or '변경 없음',
                '카테고리': u['category'], '내용': u['subject'],
            } for u in _sel_upd[40:]]), width='stretch',
                hide_index=True)


# ── 고객센터 — 안 될 때 여기부터 (실제 대처법만, 빈 약속 금지) ───────────────
# 라운드 122 — 상단 메뉴의 '고객센터'가 `#nav-support` 를 가리키는데
#   본문에 그 앵커가 **없었다.** 눌러도 아무 데도 안 갔다.
# 라운드 125 — 자리를 페이지 끝으로 옮겼다. 종전 자리(사례 모음과 점수
#   요인 사이)에서는 메뉴 순서와 본문 순서가 거기서 한 번 뒤집혔다.
_uk.spacer(28)
st.markdown('<div id="nav-support"></div>', unsafe_allow_html=True)
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
업데이트 내역은 '업데이트 내역' 절에서, 알려진 한계는 '주요 이슈'에서 확인할 수 있습니다.
""")

_uk.spacer(28)
st.caption("본 시뮬레이터는 네이버증권·다음금융 웹 데이터에 기초한 참고용 정보이며, 특정 종목의 매수·매도 권유가 아닙니다. "
           "투자 판단과 손익의 최종 책임은 투자자 본인에게 있습니다. "
           "KRX·DART·FnGuide 데이터는 네이버 종목페이지를 경유해 간접적으로 사용하며(거래일 달력·업종분류·재무·투자지표), "
           "각 기관 API 직접 조회는 연동되어 있지 않습니다. 표의 '실제 사용처' 행을 참고하세요.")
