import sys
import textwrap
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
APP_TITLE = "AI 퀀트 주가 예측 시뮬레이터"
APP_NAME = f"⚙️ {APP_TITLE}"
#: 화면·기능을 바꿀 때 이 날짜도 함께 갱신한다 (사이드바 제목 아래에 표시된다)
APP_UPDATED = "2026-07-31"

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
    initial_sidebar_state="expanded"
)

# Secrets 에 app_password 가 설정돼 있을 때만 인증을 요구한다 (없으면 그대로 공개)
check_password()

# ── 테마 토글 (라이트/다크) ────────────────────────────────────────────────
# 화면 배경·본문 텍스트·카드 여백을 전환한다. 기존 정보 카드는 자체 배경(다크)을
# 유지해 라이트 모드에서는 '흰 바탕 위 다크 카드' 대시보드 스타일이 된다.
if 'ui_theme' not in st.session_state:
    st.session_state['ui_theme'] = 'dark'
_theme = st.session_state['ui_theme']
_APP_BG = "#0d0e11" if _theme == 'dark' else "#f4f6fa"
_APP_TX = "#ffffff" if _theme == 'dark' else "#1a1c22"
_SB_BG = "#16181d" if _theme == 'dark' else "#ffffff"

st.markdown(f"""
<style>
    /* 프리미엄 타이포그래피 — 숫자는 고정폭 자릿수(tabular-nums)로 정렬 */
    .stApp {{
        background-color: {_APP_BG};
        color: {_APP_TX};
        font-family: "Pretendard", "Pretendard Variable", -apple-system,
                     BlinkMacSystemFont, "Segoe UI", Roboto, "Malgun Gothic",
                     Helvetica, Arial, sans-serif;
        font-feature-settings: "tnum" 1;
        letter-spacing: -0.01em;
    }}
    .stApp b, .stApp strong {{ font-weight: 750; }}
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
</style>
""", unsafe_allow_html=True)

st.markdown("""
<style>
    /* 전체 다크 모드 고대비 시각성 극대화 최적화 */
    
    /* 사이드바 고대비(High-Contrast) 가독성 100% 최적화 */
    [data-testid="stSidebar"] {
        background-color: #16181d !important;
        border-right: 1px solid #2d3139 !important;
    }
    
    [data-testid="stSidebar"] * {
        color: #ffffff !important;
    }

    [data-testid="stSidebar"] h1, 
    [data-testid="stSidebar"] h2, 
    [data-testid="stSidebar"] h3, 
    [data-testid="stSidebar"] h4, 
    [data-testid="stSidebar"] h5, 
    [data-testid="stSidebar"] h6 {
        color: #ffffff !important;
        font-weight: 800 !important;
        letter-spacing: -0.3px;
        margin-top: 12px !important;
        margin-bottom: 8px !important;
    }

    [data-testid="stSidebar"] p, 
    [data-testid="stSidebar"] span, 
    [data-testid="stSidebar"] label, 
    [data-testid="stSidebar"] li, 
    [data-testid="stSidebar"] small,
    [data-testid="stSidebar"] div[data-testid="stCaptionContainer"] {
        color: #e2e4ed !important;
        font-size: 0.95rem !important;
        font-weight: 600 !important;
    }

    /* 사이드바 입력창 & 드롭다운 가독성 강화 */
    [data-testid="stSidebar"] input {
        background-color: #22252c !important;
        color: #ffffff !important;
        border: 1.5px solid #64d2ff !important;
        border-radius: 8px !important;
        font-weight: bold !important;
        font-size: 1.0rem !important;
    }
    
    [data-testid="stSidebar"] [data-baseweb="select"] {
        background-color: #22252c !important;
        border: 1.5px solid #bf5af2 !important;
        border-radius: 8px !important;
    }

    [data-testid="stSidebar"] [data-baseweb="select"] * {
        color: #ffffff !important;
        background-color: #22252c !important;
        font-weight: bold !important;
    }

    [data-testid="stSidebar"] code {
        background-color: #2c2e36 !important;
        color: #30d158 !important;
        font-weight: 800 !important;
        font-size: 0.95rem !important;
        padding: 2px 6px !radius: 4px;
    }

    /* 메인 지표 카드 고대비 스타일 */
    [data-testid="stMetricValue"] {
        font-size: 2.1rem !important;
        font-weight: 800 !important;
        color: #ffffff !important;
    }
    
    [data-testid="stMetricLabel"] {
        color: #b0b5c0 !important;
        font-size: 0.95rem !important;
        font-weight: 700 !important;
        margin-bottom: 4px !important;
    }
    
    [data-testid="stMetricDelta"] {
        font-size: 0.9rem !important;
        font-weight: 700 !important;
    }

    /* 교차 검증 상태표 표 전용 스타일 */
    .cross-val-matrix {
        width: 100%;
        border-collapse: collapse;
        margin: 12px 0 20px 0;
        background: #181a20;
        border-radius: 12px;
        overflow: hidden;
        border: 1px solid #2d3139;
    }
    .cross-val-matrix th {
        background: #242731;
        color: #64d2ff;
        padding: 11px 15px;
        font-size: 0.92rem;
        font-weight: bold;
        text-align: left;
    }
    .cross-val-matrix td {
        padding: 11px 15px;
        border-top: 1px solid #2d3139;
        color: #f0f2f8;
        font-size: 0.95rem;
    }

    /* 탭 스타일 고대비 */
    .stTabs [data-baseweb="tab-list"] { gap: 6px; background-color: #16181d; padding: 5px; border-radius: 12px; border: 1px solid #2d3139; }
    .stTabs [data-baseweb="tab"] { height: 42px; border-radius: 8px; color: #a0a5b5 !important; font-weight: 700; font-size: 0.95rem; }
    .stTabs [aria-selected="true"] { background-color: #2d3139 !important; color: #ffffff !important; font-weight: 800; }

    /* 버튼 기본 테마 강제 */
    .stButton > button {
        background-color: #242731 !important;
        color: #ffffff !important;
        border: 1px solid #3d4251 !important;
        font-weight: bold !important;
    }
    .stButton > button:hover {
        border-color: #bf5af2 !important;
        color: #bf5af2 !important;
    }
    .stButton > button p {
        color: inherit !important;
        font-weight: bold !important;
    }

    h1, h2, h3, h4, h5, h6 { color: #ffffff !important; font-weight: 800 !important; }
    p, span, li, label { color: #f0f2f8; font-size: 0.98rem; }
</style>
""", unsafe_allow_html=True)

# 라이트 모드 오버라이드 — 구형 다크 규칙 뒤에 와야 이긴다.
# 정보 카드는 자체 다크 배경을 유지한다 (흰 바탕 + 다크 카드 대시보드 스타일).
if _theme == 'light':
    st.markdown("""
    <style>
        .stApp { background-color: #f4f6fa !important; }
        .stApp > header { background-color: transparent !important; }
        h1, h2, h3 { color: #14161c !important; }
        .stApp .block-container > div > div > .stMarkdown p,
        .stApp .block-container > div > div > .stMarkdown li {
            color: #2a2d36;
        }
        .stApp .stCaption, .stApp [data-testid="stCaptionContainer"] p {
            color: #5a5f6b !important;
        }
        [data-testid="stSidebar"] { background-color: #ffffff !important;
                                    border-right: 1px solid #e2e6ee !important; }
        [data-testid="stSidebar"] * { color: #1a1c22 !important; }
        hr { border-color: #dde2ea !important; }
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
      color: #f5f5f7 !important;
      font-weight: 700 !important;
      font-size: 0.95rem !important;
      background: #2c2c2e !important;
      border: 1px solid #48484a !important;
  }
  section[data-testid="stSidebar"] div[data-testid="stButton"] > button:hover {
      background: #3a3a3c !important;
      border-color: #64d2ff !important;
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
      background: #16171a !important;
      border: 2px solid #3a3f4b !important;
      border-radius: 12px !important;
      box-shadow: 0 2px 0 #0a0b0d !important;
      color: #f5f5f7 !important;
      font-size: 1.75rem !important;
      line-height: 1.3 !important;
      font-weight: 900 !important;
      letter-spacing: -0.5px !important;
      padding: 12px 14px !important;
      text-align: left !important;
      justify-content: flex-start !important;
      white-space: normal !important;
      width: 100% !important;
      transition: transform .05s ease, border-color .15s ease !important;
  }
  section[data-testid="stSidebar"] div[data-testid="stButton"].st-key-btn_home > button:hover,
  section[data-testid="stSidebar"] .st-key-btn_home div[data-testid="stButton"] > button:hover,
  section[data-testid="stSidebar"] .st-key-btn_home > button:hover,
  section[data-testid="stSidebar"] .st-key-btn_home button:hover {
      background: #1f2126 !important;
      border-color: #64d2ff !important;
      color: #64d2ff !important;
  }
  /* 눌리는 느낌 — 클릭 순간 살짝 내려앉는다 */
  section[data-testid="stSidebar"] div[data-testid="stButton"].st-key-btn_home > button:active,
  section[data-testid="stSidebar"] .st-key-btn_home button:active {
      transform: translateY(2px) !important;
      box-shadow: 0 0 0 #0a0b0d !important;
  }
</style>
""", unsafe_allow_html=True)

if st.sidebar.button(APP_NAME, use_container_width=True, key="btn_home",
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
_theme_is_light = st.sidebar.toggle("☀️ 라이트 모드", value=(_theme == 'light'),
                                    key="tgl_theme")
if _theme_is_light != (_theme == 'light'):
    st.session_state['ui_theme'] = 'light' if _theme_is_light else 'dark'
    st.rerun()

default_stock_no1 = engine_init.fetch_realtime_market_cap_no1_stock()

st.sidebar.markdown("### 🔍 실시간 종목 자동완성 검색")
st.sidebar.caption(f"👑 **오늘의 국내 시총 1위 대장주**: `{default_stock_no1}`")

if 'search_text_input' not in st.session_state:
    st.session_state['search_text_input'] = ''

if 'pending_search' in st.session_state and st.session_state['pending_search']:
    st.session_state['search_text_input'] = st.session_state['pending_search']
    st.session_state['pending_search'] = ""

search_text_input = st.sidebar.text_input(
    '🔍 종목명 일부 또는 티커 입력',
    key='search_text_input',
    placeholder='예: 하이닉스, 타이어, 건설, 페이, 포스코, 073240...',
    help='단어 일부(예: 하이닉스, 타이어, 페이)를 입력하시면 연동 후보 리스트가 하단에 즉시 생성되어 선택할 수 있습니다.'
)

matched_stocks = []
if search_text_input.strip():
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

if matched_stocks:
    st.sidebar.markdown(f"👇 **'{search_text_input}' 일치 종목 ({len(matched_stocks)}개) — 클릭하여 선택**")
    selected_from_matches = st.sidebar.selectbox("🎯 검색 종목 선택", matched_stocks)
    final_query = selected_from_matches
elif search_text_input.strip():
    final_query = search_text_input.strip()
else:
    st.sidebar.caption("📋 **시가총액 상위 퀵 선택** (실시간 수집)")
    # 종목 목록을 코드에 박아두지 않는다 — 시총 상위에서 매번 가져온다
    if 'quick_top' not in st.session_state:
        st.session_state['quick_top'] = engine_init.fetch_market_cap_top(10)
    QUICK_PLACEHOLDER = "--- 시총 상위 종목 선택 ---"     # 안내문구 (검색어로 넘기지 않는다)
    quick_select_options = [QUICK_PLACEHOLDER] + st.session_state['quick_top']
    selected_quick_item = st.sidebar.selectbox("시총 상위 퀵 선택", quick_select_options)

    if st.session_state.get('selected_ticker'):
        final_query = st.session_state['selected_ticker']
    elif selected_quick_item and selected_quick_item != QUICK_PLACEHOLDER:
        final_query = selected_quick_item
    else:
        final_query = default_stock_no1

target_ticker, resolved_name = engine_init.resolve_symbol(final_query)

# 종목 해석 실패는 앱 전체를 중단시키지 않는다 — 명확히 알리고 멈춘다
if not target_ticker:
    st.error(f"🚨 **종목을 해석하지 못했습니다**: `{final_query}`\n\n"
             f"종목명 또는 6자리 종목코드를 입력해 주세요. "
             f"네이버증권 검색이 일시적으로 실패했을 수도 있습니다.")
    st.stop()
# 🚨 [무결성 보장] 네이버 증권 실시간 웹 파서 강제 동적 수신
engine_init.fetch_and_update_naver_realtime(target_ticker)

asset_meta = engine_init.get_asset_currency_and_unit(target_ticker)
unit_currency = asset_meta["currency"]
unit_str = asset_meta["unit_str"]

realtime_price, check_status, matrix_data = engine_init.get_realtime_stock_price_triple_check(target_ticker)

st.sidebar.success(f"🎯 **선택 종목**: [{resolved_name}] (`{target_ticker}`)")
st.sidebar.info(f"🛡️ **자산/통화 스키마 검증**:\n- **자산 구별**: {asset_meta['type']}\n- **통화 코드**: `{unit_currency}`\n- **가격 단위**: `{unit_str}`\n- **현재가**: `{realtime_price:,.0f}` {unit_str}" if unit_currency=="KRW" else f"- **현재가**: `${realtime_price:,.2f}`")


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


st.sidebar.markdown("---")
_positions = st.session_state.get('positions') or []
st.sidebar.markdown(f"### 💼 내 보유종목 ({len(_positions)})")

if not _positions:
    st.sidebar.caption("등록된 보유종목이 없습니다. 증권사 앱 보유종목 화면을 "
                       "`Win`+`Shift`+`S` 로 캡처해 두고 아래 버튼을 누르면, "
                       "본문에서 클립보드 이미지를 그대로 읽어 등록할 수 있습니다.")
    if st.sidebar.button("📸 스크린샷으로 등록하기", use_container_width=True,
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
    _col = "#30d158" if (_pnl or 0) >= 0 else "#ff453a"
    st.sidebar.markdown(
        f"<div style='background:#1c1c1e;border:1px solid {_col};border-radius:10px;"
        f"padding:10px 12px;margin-bottom:8px;'>"
        f"<div style='font-size:0.78rem;color:#86868b;'>총 평가손익</div>"
        f"<div style='font-size:1.25rem;font-weight:800;color:{_col};'>"
        f"{fmt_num(_pnl, '+,.0f', '원')}</div>"
        f"<div style='font-size:0.8rem;color:#d2d2d7;'>수익률 {fmt_pct(_tot_ret)} · "
        f"평가 {fmt_num(_tot_val, ',.0f', '원')}</div></div>",
        unsafe_allow_html=True)

    # 사이드바 버튼 스타일은 여기서 주입하지 않는다.
    # 예전에는 이 자리에서 모든 사이드바 버튼에 font-size:0.95rem !important 를 걸었는데,
    # 그 규칙이 제목(홈 버튼) 규칙보다 구체적이고 나중에 삽입돼서 제목 글자를
    # 본문 소제목보다 작게 만들어버렸다. 스타일은 파일 상단 한 곳에서만 정의한다.

    for _m, _px, _ret in _rows:
        _c1, _c2 = st.sidebar.columns([1.35, 1])
        _is_cur = (_m['ticker'] == target_ticker)
        with _c1:
            if st.button(("▶ " if _is_cur else "") + _m['stock_name'],
                         key=f"pos_{_m['ticker']}", use_container_width=True,
                         type="primary" if _is_cur else "secondary",
                         help=f"{_m['quantity']:,.0f}주 · 평단 {_m['average_buy_price']:,.0f}원"):
                st.session_state['pending_search'] = f"{_m['stock_name']} ({_m['ticker'].split('.')[0]})"
                st.rerun()
        with _c2:
            _rc = "#30d158" if (_ret or 0) >= 0 else "#ff453a"
            st.markdown(
                f"<div style='text-align:right;padding-top:6px;'>"
                f"<span style='color:{_rc};font-weight:700;font-size:0.92rem;'>{fmt_pct(_ret)}</span><br>"
                f"<span style='color:#86868b;font-size:0.72rem;'>{fmt_num(_px, ',.0f', '원', na='조회실패')}</span>"
                f"</div>", unsafe_allow_html=True)

    st.sidebar.caption("※ 평단가는 보유 판단에만 사용하며 예측·적정가·점수에는 반영되지 않습니다.")

# 📌 선택 종목 1건만 빠르게 넣어보는 입력 (포트폴리오 등록 없이 임시 확인용)
st.sidebar.markdown("---")
st.sidebar.markdown("### 📌 내 포지션 입력 (선택)")

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
    if st.sidebar.button("➕ 보유종목에 등록", use_container_width=True):
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
st.sidebar.markdown("---")
st.sidebar.markdown("### 🔥 AI 퀀트 시장 트렌드 탐색기")
st.sidebar.caption("코스피·코스닥 전체에서 거래대금·수급·추세가 변화하는 **관심종목**을 먼저 발굴하고, "
                   "그중 **퀀트 최종 행동조건**을 통과한 종목만 추천합니다. "
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

with st.sidebar.expander("📡 관심 데이터 연동 현황"):
    st.caption("수집하지 못한 항목은 값을 만들어내지 않고 가중치를 0으로 둔 뒤, "
               "나머지 항목에 재정규화합니다.")
    for _d in market_attention.data_status():
        _mark = {'full': '🟢 연동', 'partial': '🟡 부분', 'none': '🔴 미연동'}[_d['availability']]
        st.markdown(
            f"**{_d['label']}** {_mark}  \n"
            f"명세 {_d['spec_weight_pct']:.0f}% → 적용 **{_d['effective_weight_pct']:.1f}%**  \n"
            f"<span style='color:#86868b;font-size:0.78rem;'>{_d['detail']}</span>",
            unsafe_allow_html=True)

if st.sidebar.button("🚀 오늘의 관심종목 스캔 / 닫기", use_container_width=True):
    st.session_state['show_screener'] = not st.session_state['show_screener']
    st.session_state['pending_scan'] = st.session_state['show_screener']

st.sidebar.markdown("---")
st.sidebar.markdown("### 🧮 분석 파라미터")

# [명세 §3] 확정 분석 기준일 — 장중·장 시작 전·휴장일이면 직전 거래일로 되돌린다
_mkt = bitemporal_engine.get_market_status()
_resolved_date = bitemporal_engine.resolve_analysis_date(market_status=_mkt)
st.sidebar.caption(
    f"🕒 시장 상태: **{_mkt['state']}** → 확정 분석 기준일 **{_resolved_date}**"
    + ("" if _mkt['holiday_data_available'] else "  ⚠️ 해당 연도 공휴일 미등록 (주말만 판정)")
)
t_ref_date = st.sidebar.date_input("백테스트 기준일 (t_ref)", value=_resolved_date)
if t_ref_date != _resolved_date:
    st.sidebar.warning(f"기준일을 수동 변경했습니다 (권장: {_resolved_date}).")
rho_cutoff = st.sidebar.slider("자기유사 상관계수 기준 (rho)", min_value=0.70, max_value=0.95, value=0.80, step=0.05)
t_ref_str = t_ref_date.strftime("%Y-%m-%d")

# --- 💼 보유종목 상세 화면 열기 ---
st.sidebar.markdown("---")
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
    f"<h1 style='font-size:2.6rem; font-weight:900; letter-spacing:-1px; "
    f"margin:0 0 4px 0; color:#f5f5f7;'>🎯 {APP_TITLE}</h1>",
    unsafe_allow_html=True)
st.caption(f"⚡ 네이버·다음 실데이터 기반 · 표본/신뢰도 게이트 적용 · "
           f"Purged Walk-Forward 표본외 검증 수행 (Run ID: `{run_id}`)\n")

# --- 종목 검색기 렌더링 ---
if st.session_state.get('show_screener', False):
    st.markdown("---")
    st.subheader("📡 네이버·다음 실시간 시세 교차검증 상태 (Cross-Validation)")
    st.caption("※ 네이버증권과 다음금융은 현재 공식 API가 아닌 웹 스크래핑/폴링 방식으로 연결되어 있으므로, 2차 교차검증 출처로만 사용됩니다.")
    
    with st.spinner("네이버·다음 실시간 시세 조회 및 정합성 검증 중..."):
        cv_data = engine_init.verify_realtime_sources(target_ticker)

    def _cv_price(v):
        return f"{v:,.0f}원" if isinstance(v, (int, float)) else "수신 실패"

    cv_nv, cv_dm = cv_data['naver'], cv_data['daum']
    cv_diff_str = f"{cv_data['diff_pct']:.3f}%" if cv_data.get('diff_pct') is not None else "대조 불가"
    nv_col = "#30d158" if cv_nv['ok'] else "#ff453a"
    dm_col = "#30d158" if (cv_dm['ok'] and "오류" not in cv_dm['cross_val']) else "#ff453a"

    cv_col1, cv_col2 = st.columns(2)
    with cv_col1:
        st.markdown(f"""
        <div style='background:#1c1c1e; padding:15px; border-radius:10px; border: 1px solid {nv_col};'>
            <h4 style='color:{nv_col}; margin:0 0 10px 0;'>🟢 네이버증권 (Naver Finance)</h4>
            <p style='margin:2px 0; font-size:0.85rem; color:#d2d2d7;'>- 연결 상태: <b>{cv_nv['status']}</b></p>
            <p style='margin:2px 0; font-size:0.85rem; color:#d2d2d7;'>- 조회 시각: {cv_nv['receive_time']}</p>
            <p style='margin:2px 0; font-size:0.85rem; color:#d2d2d7;'>- 데이터 유형: {cv_nv['data_type']}</p>
            <p style='margin:2px 0; font-size:0.85rem; color:#d2d2d7;'>- 현재가 반환값: {_cv_price(cv_nv['price'])}</p>
            <p style='margin:2px 0; font-size:0.85rem; color:#d2d2d7;'>- 실측 응답시간: {cv_nv['delay_ms']}ms</p>
            <p style='margin:2px 0; font-size:0.85rem; color:#ff9f0a;'>- API 인증: {cv_nv['is_official']}</p>
        </div>
        """, unsafe_allow_html=True)
    with cv_col2:
        st.markdown(f"""
        <div style='background:#1c1c1e; padding:15px; border-radius:10px; border: 1px solid {dm_col};'>
            <h4 style='color:{dm_col}; margin:0 0 10px 0;'>🟡 다음금융 (Daum Finance)</h4>
            <p style='margin:2px 0; font-size:0.85rem; color:#d2d2d7;'>- 연결 상태: <b>{cv_dm['status']}</b></p>
            <p style='margin:2px 0; font-size:0.85rem; color:#d2d2d7;'>- 조회 시각: {cv_dm['receive_time']}</p>
            <p style='margin:2px 0; font-size:0.85rem; color:#d2d2d7;'>- 교차검증 상태: <b>{cv_dm['cross_val']}</b> (오차율: {cv_diff_str})</p>
            <p style='margin:2px 0; font-size:0.85rem; color:#d2d2d7;'>- 현재가 반환값: {_cv_price(cv_dm['price'])}</p>
            <p style='margin:2px 0; font-size:0.85rem; color:#d2d2d7;'>- 실측 응답시간: {cv_dm['delay_ms']}ms</p>
            <p style='margin:2px 0; font-size:0.85rem; color:#ff9f0a;'>- API 인증: {cv_dm['is_official']}</p>
        </div>
        """, unsafe_allow_html=True)

    if not cv_data.get('comparable'):
        st.error("🚨 **실시간 시세 교차검증 불가**: 네이버·다음 중 최소 한 곳에서 현재가를 수신하지 못했습니다. "
                 "단일 출처만으로는 시세 무결성을 보증할 수 없어 스캔을 중단합니다.")
    elif cv_data['diff_pct'] > 1.0:
        st.error(f"🚨 **실시간 시세 교차검증 실패**: 출처 간 현재가 오차가 {cv_diff_str}로 1.0%를 초과하여 스캔을 중단합니다.")
    else:
        st.markdown("<br>", unsafe_allow_html=True)
        st.subheader("🏆 오늘의 AI 퀀트 최적 종목 TOP 3")
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

            st.markdown(f"""
            <div style='background:#1c1c1e; padding:15px; border-radius:10px; margin-bottom:15px; border:1px solid #3a3a3c;'>
                <h4 style='color:#f5f5f7; margin-top:0;'>📊 시장 스캔 완료</h4>
                <ul style='color:#d2d2d7; font-size:0.95rem; line-height:1.6; margin-bottom:0;'>
                    <li>분석 기준일: {t_ref_str} · rho {rho_cutoff}</li>
                    <li>1단계 관심종목 후보 풀: <b>{st.session_state.get('scan_universe_total', 0):,}개</b>
                        (ETF·우선주·스팩·리츠 제외 후)</li>
                    <li>2단계 정밀분석: <b>{_sel_strat_label}</b> 상위 <b>{scan_depth}개</b>
                        → 분석 완료 {len(scan_results)}개 · 제외 {len(scan_failures)}개</li>
                    <li>최종 행동 필수조건 통과: <b style='color:{"#30d158" if recommended else "#ff9f0a"};'>{len(recommended)}개</b></li>
                </ul>
            </div>
            """, unsafe_allow_html=True)

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
                st.markdown("### 🔥 오늘의 관심종목 후보")
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
                    if st.button("⭐ 이 목록을 관심종목으로 저장",
                                 use_container_width=True, key="btn_save_watchlist"):
                        _items = [{'code': r['code'], 'name': r['name']}
                                  for r in _att['rows']]
                        st.session_state['watchlist'] = _items
                        if ALLOW_LOCAL_STORE:
                            try:
                                portfolio.save_watchlist(_items)
                                st.success(f"⭐ {len(_items)}종목 저장 — 후보 발굴 방식에서 "
                                           f"'사용자 관심종목'으로 다시 스캔할 수 있습니다.")
                            except Exception as _ex:
                                st.warning(f"로컬 저장 실패: {_ex}")
                        else:
                            st.success(f"⭐ {len(_items)}종목 저장 (이 브라우저 세션에만 유지)")
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
                    _bcol = {'🏆 실전 추천 후보': '#30d158',
                             '🔥 관심 급증·추격주의': '#ff9f0a',
                             '🌱 조용한 선행 후보': '#64d2ff',
                             '👀 관찰 후보': '#8e8e93',
                             '🚫 추천 제외': '#ff453a'}.get(_bucket, '#8e8e93')
                    # HTML 안에서 조건식을 조립하면 읽을 수 없어진다 — 먼저 문자열로 만든다
                    _raw_txt = f"원점수 {_a['market_attention_score']:.0f}"
                    if _a['penalty']:
                        _raw_txt += f" · 감점 −{_a['penalty']:.0f}"
                    _pen_html = ""
                    if _a['penalty_reasons']:
                        _pen_html = ("<br><span style='color:#ff9f0a;font-size:0.78rem;'>⚠️ "
                                     + " · ".join(_a['penalty_reasons']) + "</span>")
                    _ratio_txt = ""
                    if _c.get('turnover_ratio'):
                        _ratio_txt = (f" · 거래대금 {_c['turnover_ratio']:.1f}배"
                                      f"({_c.get('turnover_basis', '')})")

                    _cc1, _cc2 = st.columns([3, 1])
                    with _cc1:
                        st.markdown(
                            f"<div style='background:#1c1c1e;border-left:4px solid {_bcol};"
                            f"border-radius:8px;padding:10px 14px;margin-bottom:8px;'>"
                            f"<b style='color:#f5f5f7;font-size:1.02rem;'>{_r['name']}</b> "
                            f"<span style='color:#86868b;font-size:0.8rem;'>{_r['code']}</span><br>"
                            f"<span style='color:{_bcol};font-weight:700;font-size:0.85rem;'>{_bucket}</span><br>"
                            f"<span style='color:#d2d2d7;font-size:0.85rem;'>"
                            f"시장 관심점수 <b>{_a['adjusted_attention_score']:.0f}</b>"
                            f"<span style='color:#86868b;'> ({_raw_txt})</span>"
                            f" · 퀀트 행동점수 <b>{fmt_num(_act, ',.0f')}</b></span><br>"
                            f"<span style='color:#86868b;font-size:0.8rem;'>"
                            f"{_r.get('selection_reason', '')}{_ratio_txt}</span>"
                            f"{_pen_html}</div>", unsafe_allow_html=True)
                    with _cc2:
                        if st.button("분석 →", key=f"att_{_r['code']}",
                                     use_container_width=True):
                            st.session_state['pending_search'] = f"{_r['name']} ({_r['code']})"
                            st.rerun()

                if not _scored_rows:
                    st.info("행동점수까지 산출된 후보가 없습니다. 아래 제외 사유를 확인하세요.")

                # 행동점수를 산출하지 못한 후보 — '미산출' 로 섞지 않고 사유와 함께 분리
                if _excluded_rows:
                    with st.expander(f"⛔ 행동점수 미산출로 본 목록에서 제외된 "
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
                                f"<span style='color:#ff9f0a;font-size:0.82rem;'>"
                                f"제외 사유: {_why[:120]}</span>",
                                unsafe_allow_html=True)
                            if _ec2.button("분석 →", key=f"attx_{_r['code']}",
                                           use_container_width=True):
                                st.session_state['pending_search'] = \
                                    f"{_r['name']} ({_r['code']})"
                                st.rerun()
                st.markdown("---")

            if scan_failures:
                with st.expander(f"⚠️ 분석에서 제외된 {len(scan_failures)}개 종목 사유 보기"):
                    for f in scan_failures:
                        st.markdown(f"- **{f['name']}** (`{f['symbol']}`) — {f['reason']}")

            if len(top_recs) == 0:
                st.warning("🚨 **현재 추천주 없음** — 필수조건을 모두 통과한 종목이 없습니다. "
                           "무리한 신규 매수보다 현금 유지가 우선입니다.")
                if block_counter:
                    top_blocks = block_counter.most_common(5)
                    st.markdown(
                        "**가장 많이 걸린 차단 조건**\n\n"
                        + "\n".join(f"- {name} — {cnt}개 종목" for name, cnt in top_blocks)
                    )
            else:
                st.success(f"✅ 필수조건을 모두 통과한 종목: **{len(recommended)}개** (최대 3개 표출)")

                # --- Interactive Screener Table ---
                st.markdown("### 🏆 AI 퀀트 최적 종목 결과 (Clickable)")
                
                # Header (전략유형 및 월봉 10선 장기추세 컬럼 탑재)
                cols = st.columns([0.5, 1.8, 1.4, 1.1, 1.2, 1.2, 1.4, 1.2, 1.0, 1.2])
                headers = ["순위", "종목명 (클릭)", "전략유형", "현재가", "적정가", "상승여력%", "월봉 10선", "최종점수", "손익비", "상태"]
                for col, header in zip(cols, headers):
                    col.markdown(f"<div style='text-align:center; color:#64d2ff; font-size:0.85rem; font-weight:bold; border-bottom:2px solid #3d4251; padding-bottom:6px;'>{header}</div>", unsafe_allow_html=True)
                
                # Rows
                for i, r in enumerate(top_recs):
                    cols = st.columns([0.5, 1.8, 1.4, 1.1, 1.2, 1.2, 1.4, 1.2, 1.0, 1.2])
                    
                    cols[0].markdown(f"<div style='text-align:center; padding-top:10px;'><span style='background:#bf5af2; color:#fff; padding:3px 8px; border-radius:12px; font-weight:bold;'>{i+1}</span></div>", unsafe_allow_html=True)
                    
                    with cols[1]:
                        _entry_badge = "🎯" if r.get('entry_candidate') else ""
                        if st.button(f"{_entry_badge}{r['name']}", key=f"btn_{r['symbol']}_{i}",
                                     use_container_width=True,
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
                        upside_str, upside_color = "미산출", "#86868b"
                    else:
                        upside_str = f"{upside_val:+.1f}%"
                        upside_color = "#30d158" if upside_val > 0 else "#ff453a"

                    m10_stat = r.get('m10_status', '위')
                    m10_disp = r.get('m10_disparity', 0.0)
                    m10_col = "#30d158" if m10_stat == "위" else "#ff453a"
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

                    cols[2].markdown(f"<div style='text-align:center; padding-top:10px; font-size:0.85rem; font-weight:bold;'>{st_type}</div>", unsafe_allow_html=True)
                    cols[3].markdown(f"<div style='text-align:center; padding-top:10px; color:#f0f2f8; font-weight:bold;'>{curr_p_str}</div>", unsafe_allow_html=True)
                    cols[4].markdown(f"<div style='text-align:center; padding-top:10px; color:#bf5af2; font-weight:bold;'>{target_p_str}</div>", unsafe_allow_html=True)
                    cols[5].markdown(f"<div style='text-align:center; padding-top:10px; color:{upside_color}; font-weight:800; font-size:1.0rem;'>{upside_str}</div>", unsafe_allow_html=True)
                    cols[6].markdown(f"<div style='text-align:center; padding-top:10px; color:{m10_col}; font-weight:bold; font-size:0.85rem;'>{m10_str}</div>", unsafe_allow_html=True)
                    cols[7].markdown(f"<div style='text-align:center; padding-top:10px; color:#00f0ff; font-weight:bold; font-size:1.0rem;'>{r['final_score']}점</div>", unsafe_allow_html=True)
                    cols[8].markdown(f"<div style='text-align:center; padding-top:10px;'>{rr_str}</div>", unsafe_allow_html=True)
                    
                    color = "#30d158" if "추천주" in r['cat'] else ("#bf5af2" if "매수" in r['cat'] else "#ff9f0a")
                    cols[9].markdown(f"<div style='text-align:center; padding-top:10px; color:{color}; font-weight:bold; font-size:0.85rem;'>{r['cat']}</div>", unsafe_allow_html=True)
                    
                st.info("💡 **TIP:** 위 표에서 종목명 버튼을 클릭하면, 해당 종목이 자동으로 선택되고 하단의 상세 분석 화면이 즉시 갱신됩니다.")
                
            st.markdown(f"""
            <div style='display:flex; justify-content:space-around; background:#1c1c1e; padding:12px; border-radius:8px; margin-top:15px; border:1px solid #3a3a3c;'>
                <div style='text-align:center;'><span style='color:#86868b; font-size:0.9rem;'>⏳ 눌림 대기</span><br><b style='color:#f5f5f7;'>{wait_pullback}개</b></div>
                <div style='text-align:center;'><span style='color:#86868b; font-size:0.9rem;'>👀 관찰 후보</span><br><b style='color:#f5f5f7;'>{watch_list}개</b></div>
                <div style='text-align:center;'><span style='color:#86868b; font-size:0.9rem;'>🚫 추천 제외</span><br><b style='color:#f5f5f7;'>{excluded}개</b></div>
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

    st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════
# 📋 오늘의 추천 — 개장 전 확정 리포트 (전일 확정 데이터 기준 · 장중 재계산 금지)
# ═══════════════════════════════════════════════════════════════════════════
import premarket as _pm_view

_pmr = st.session_state.get('premarket_report') or _pm_view.load_today_report()
if _pmr:
    st.markdown("## 📋 오늘의 추천 — 개장 전 확정 리포트")
    st.caption(f"기준 데이터 **{_pmr.get('data_asof')}** · 생성 **{_pmr.get('generated_at')}** · "
               f"{_pmr.get('market_label') or ''}  \n"
               f"🔒 {_pmr.get('note')}")
    _CLS_COLOR = {'오늘 사도 되는 종목': '#30d158', '조건부로 사도 되는 종목': '#64d2ff',
                  '오늘은 기다려야 하는 종목': '#ff9f0a', '오늘은 사면 안 되는 종목': '#ff453a'}
    _pm_cols = st.columns(min(5, max(1, len(_pmr.get('picks') or []))))
    for _pi, _p in enumerate((_pmr.get('picks') or [])[:5]):
        _cc = _CLS_COLOR.get(_p.get('reco_class'), '#86868b')
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
        with _pm_cols[_pi]:
            st.markdown(f"""
            <div style='background:#141416; border:1px solid {_cc}55; border-top:3px solid {_cc};
                        border-radius:14px; padding:12px 14px; min-height:240px;'>
              <p style='margin:0; font-size:0.72rem; color:{_cc}; font-weight:800;'>{_p.get('reco_class')}</p>
              <p style='margin:4px 0 2px 0; font-size:1.05rem; font-weight:900; color:#f5f5f7;'>{_p.get('name')}</p>
              <p style='margin:0; font-size:0.72rem; color:#86868b;'>{_p.get('code')} · {_p.get('asset_type')} · {_p.get('score')}점</p>
              <p style='margin:8px 0 4px 0; font-size:0.85rem; font-weight:800; color:{_cc};'>{_p.get('easy_emoji')} {_p.get('easy_line')}</p>
              <p style='margin:0; font-size:0.75rem; color:#d2d2d7; line-height:1.6;'>
                권장 {'{:,.0f}원'.format(_p['rec_buy']) if _p.get('rec_buy') else '미산출'} ·
                목표 {'{:,.0f}원'.format(_p['target']) if _p.get('target') else '—'} ·
                손절 {'{:,.0f}원'.format(_p['stop']) if _p.get('stop') else '—'}<br>
                {' · '.join(_news_txt) if _news_txt else '특이 뉴스 없음'}<br>
                <span style='color:#86868b;'>{_conf_txt}</span></p>
            </div>""", unsafe_allow_html=True)
    with st.expander("📈 지난 개장 전 추천의 실제 성과 (사후 검증)"):
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
    st.caption("📋 오늘의 개장 전 리포트는 위 **트렌드 탐색기**에서 스캔을 실행하면 "
               "전일 확정 데이터 기준으로 생성·고정됩니다.")

# ═══════════════════════════════════════════════════════════════════════════
# 💼 내 보유종목 화면
# ═══════════════════════════════════════════════════════════════════════════
if st.session_state.get('show_portfolio'):
    st.markdown("---")
    st.header("💼 내 보유종목")
    st.caption("⚠️ 평균 매수가는 **보유·축소·손절 판단에만** 사용합니다. "
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
        st.info("🔒 증권사 로그인 자동화·쿠키 수집·비공식 보유자산 API는 사용하지 않습니다. "
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
                        st.success(f"✅ {len(pos)}종목 가져오기 완료")
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
        st.markdown("---")
        st.markdown("### 📗 엑셀 파일로 가져오기 (가장 정확)")
        st.caption("스크린샷 인식은 글자를 잘못 읽을 수 있습니다. **증권사 HTS 에서 내려받은 "
                   "엑셀** 이나 아래 **양식**을 채워 올리면 숫자를 그대로 읽어 오독이 없습니다.")

        _xc1, _xc2 = st.columns(2)
        with _xc1:
            _tpl_bytes, _tpl_name, _tpl_mime = portfolio.build_template_bytes()
            st.download_button("📥 입력 양식 내려받기", data=_tpl_bytes,
                               file_name=_tpl_name, mime=_tpl_mime,
                               use_container_width=True, key="btn_dl_template")
            st.caption("종목코드·종목명·보유수량·평균매수가 네 칸만 채우면 됩니다.")
        with _xc2:
            _cur_pos = st.session_state.get('positions') or []
            _exp_df = portfolio.positions_to_dataframe(_cur_pos)
            st.download_button(
                f"📤 지금 보유종목 내보내기 ({len(_cur_pos)}종목)",
                data=_exp_df.to_csv(index=False).encode("utf-8-sig"),
                file_name="내_보유종목.csv", mime="text/csv",
                use_container_width=True, disabled=not _cur_pos,
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

                if st.button("📗 엑셀에서 가져오기", type="primary", key="btn_xls_import"):
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
                            st.success(f"✅ {len(_rows_x)}종목을 읽었습니다 — 아래 "
                                       f"**미리보기**에서 확인한 뒤 '반영'을 누르세요. "
                                       f"엑셀 숫자를 그대로 쓰므로 OCR 오독이 없습니다.")
                        else:
                            st.error("가져올 행이 없습니다. 열 선택을 확인해 주세요.")
            except Exception as _xexc:
                st.error(f"파일을 읽지 못했습니다 ({type(_xexc).__name__}): {_xexc}")

        st.markdown("---")
        st.markdown("### 📸 스크린샷으로 가져오기")
        st.caption("⚠️ 인식 결과는 반드시 미리보기에서 확인하세요. 정확도가 중요하면 위 "
                   "**엑셀 가져오기**를 쓰는 편이 안전합니다.")
        _ocr = portfolio.ocr_backend()
        if _ocr is None and not ALLOW_LOCAL_STORE:
            # 온라인(클라우드) 실행인데 엔진이 안 잡힌 경우. 서버에 Tesseract 를 함께
            # 배포하도록 되어 있으므로(packages.txt) 여기까지 왔다면 그 설치가 아직
            # 반영되지 않았다는 뜻이다. 사용자 PC 문제로 오해하지 않도록 밝혀 둔다.
            st.warning("⚠️ **지금은 서버에서 스크린샷 인식 엔진을 찾지 못했습니다** — "
                       "여러분 PC의 문제가 아닙니다. 서버에 OCR 엔진(Tesseract)을 함께 배포하도록 "
                       "설정돼 있으나, 방금 배포된 경우 반영까지 몇 분 걸릴 수 있습니다.")
            st.caption("그 사이에는 아래 **표 붙여넣기**를 이용하세요 — 증권사 화면에서 표를 드래그해 "
                       "복사하면 그대로 읽습니다. 내 PC에서 실행할 때는 `pip install easyocr` 로 "
                       "더 정확한 엔진을 쓸 수 있습니다.")
        elif _ocr is None:
            st.warning("⚠️ **스크린샷 인식 불가** — 이 PC에 OCR 엔진이 설치되어 있지 않습니다.")
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
                    st.caption("↑ 위 상자에 다시 붙여넣으면 새 이미지로 인식합니다.")

            # ── ② 서버 클립보드 직접 읽기 (로컬 실행 전용) ─────────────────────
            # 이 경로는 **서버 프로세스의 클립보드**를 읽는다. 로컬 실행에서는 그게 곧
            # 사용자의 클립보드지만, 클라우드에서는 남의 서버 클립보드를 읽으려 드는
            # 무의미한 동작이라 원격에서는 노출하지 않는다.
            if is_local_session():
                with st.expander("붙여넣기가 안 될 때 — 클립보드에서 직접 읽기 (이 PC 실행 전용)"):
                    if st.button("📋 클립보드 이미지 읽기", key="btn_clip_ocr"):
                        _img2, _cerr = portfolio.grab_clipboard_image()
                        if _cerr:
                            st.error(_cerr)
                        else:
                            st.session_state['clip_image'] = _img2
                            _recognize_image(_img2)
            if st.session_state.get('clip_image'):
                with st.expander("붙여넣은 이미지 보기"):
                    st.image(st.session_state['clip_image'], use_container_width=True)

            # ── ③ 파일로 올리기 ────────────────────────────────────────────
            st.markdown("**② 이미지 파일로 올리기** (붙여넣기가 막힌 브라우저용)")
            shot = st.file_uploader("스크린샷 이미지 (PNG/JPG)", type=["png", "jpg", "jpeg"],
                                    key="shot_uploader")
            if shot is not None:
                st.image(shot, caption="업로드한 스크린샷", use_container_width=True)
                if st.button("📸 이미지에서 인식하기", key="btn_file_ocr"):
                    _recognize_image(shot.getvalue())

        st.markdown("---")
        st.markdown("### 📋 화면에서 표를 긁어 붙여넣기")
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
        if st.button("🔍 인식하기", type="primary"):
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
            with st.expander("🔧 열을 직접 지정하기" + ("  ⬅️ 자동 인식 실패" if _needs_manual else ""),
                             expanded=_needs_manual):
                _ncol, _cells = portfolio.preview_columns(_src_text)
                if _ncol < 2:
                    st.caption("열을 나눌 수 없습니다. 표 형태로 복사했는지 확인하세요.")
                else:
                    st.caption(f"인식된 열 {_ncol}개 — 아래 표에서 몇 번째 열이 무엇인지 고르세요. "
                               f"추측하지 않으므로 지정이 맞으면 결과도 맞습니다.")
                    st.dataframe(pd.DataFrame(
                        _cells, columns=[f"{i}" for i in range(_ncol)]),
                        use_container_width=True, hide_index=True)
                    _opts = list(range(_ncol))
                    _mc1, _mc2, _mc3, _mc4 = st.columns(4)
                    _skip = _mc1.number_input("건너뛸 윗줄 수", 0, 10, 1, key="mancol_skip")
                    _nm = _mc2.selectbox("종목명 열", _opts, index=min(1, _ncol - 1), key="mancol_name")
                    _qt = _mc3.selectbox("수량 열", _opts, index=min(4, _ncol - 1), key="mancol_qty")
                    _pr = _mc4.selectbox("평단가 열", _opts, index=_ncol - 1, key="mancol_price")
                    if st.button("🔧 지정한 열로 다시 읽기", key="btn_mancol"):
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
            st.markdown("#### ✏️ 미리보기 — 반영 전 확인")
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
                                  f"<span style='color:#86868b;font-size:0.8rem;'>"
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
                st.caption(f"💹 현재가 {_npx}종목을 실시간 시세로 채웠습니다 — "
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
                _sc = "#30d158" if _s_pnl >= 0 else "#ff453a"
                st.markdown(
                    f"<div style='background:#1c1c1e;border:1px solid {_sc};"
                    f"border-radius:10px;padding:10px 14px;margin:6px 0;'>"
                    f"<b>실시간 평가 요약</b> — 매입 {_s_cost:,.0f}원 · "
                    f"평가 {_s_val:,.0f}원 · "
                    f"<b style='color:{_sc};'>손익 {_s_pnl:+,.0f}원 "
                    f"({_s_ret:+.2f}%)</b>"
                    f"<br><span style='color:#86868b;font-size:0.8rem;'>"
                    f"원본 화면의 총 평가손익과 다르면 수량·평단가가 잘못 인식된 것입니다."
                    f"</span></div>", unsafe_allow_html=True)

            _c_ok, _c_warn, _c_err = _vtot['ok'], _vtot['warn'], _vtot['error']
            st.markdown(
                f"**검증 결과** — 전체 {_vtot['rows']}행 · "
                f"<span style='color:#30d158;'>확실 {_c_ok}</span> · "
                f"<span style='color:#ff9f0a;'>확인 필요 {_c_warn}</span> · "
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
                st.caption("⚪ 현재가·수익률·평가손익 열이 없어 교차검증을 하지 못했습니다 — "
                           "그 열들이 보이도록 캡처하면 오독을 자동으로 잡아냅니다.")

            # 문제 행별 상세 + 후보 제시
            _bad = [r for r in preview if r['_validation']['severity'] != 'ok']
            if _bad:
                with st.expander(f"⚠️ 확인이 필요한 {len(_bad)}행 자세히 보기", expanded=True):
                    for _br in _bad:
                        _v = _br['_validation']
                        _col = '#ff453a' if _v['severity'] == 'error' else '#ff9f0a'
                        st.markdown(
                            f"<b style='color:{_col};'>{_br.get('종목명')}</b> "
                            f"<span style='color:#86868b;font-size:0.8rem;'>신뢰도 "
                            f"{_v['confidence']:.0f}%</span>", unsafe_allow_html=True)
                        for _c in _v['checks']:
                            if not _c['ok']:
                                st.caption(f"　🔴 {_c['name']} — {_c['detail']}")
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
                num_rows="dynamic", use_container_width=True, key="paste_editor",
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
                        st.success(f"✅ {len(pos)}종목 반영·저장")
                    except Exception as _ex:
                        st.success(f"✅ {len(pos)}종목 반영")
                        st.warning(f"로컬 저장 실패: {_ex}")
                else:
                    st.success(f"✅ {len(pos)}종목 반영 (이 브라우저 세션에만 유지)")
                    st.caption("원격 접속이라 서버에 저장하지 않습니다. 보관하려면 "
                               "**저장·삭제 탭 → CSV 내보내기**를 쓰세요.")
                for w in warns:
                    st.warning(w)
                st.rerun()
            if pc2.button("✖ 미리보기 취소"):
                st.session_state.pop('paste_preview', None)
                st.rerun()

        st.markdown("---")
        st.markdown("### ✏️ 표에서 직접 편집")
        st.caption("행을 추가·수정·삭제한 뒤 '저장'을 누르세요. 종목코드 6자리와 수량·평단가만 있으면 됩니다.")
        cur_rows = portfolio.positions_to_rows(st.session_state.get('positions') or [])
        editor_df = pd.DataFrame(cur_rows) if cur_rows else pd.DataFrame(
            columns=["종목코드", "종목명", "보유수량", "평균매수가", "_ticker"])
        edited_direct = st.data_editor(
            editor_df, num_rows="dynamic", use_container_width=True, key="direct_editor",
            column_config={"_ticker": None,
                           "보유수량": st.column_config.NumberColumn(format="%.0f"),
                           "평균매수가": st.column_config.NumberColumn(format="%.0f")})
        if st.button("💾 편집 내용 반영"):
            pos, warns = portfolio.rows_to_positions(
                edited_direct.to_dict('records'), source_type="manual_entry")
            st.session_state['positions'] = pos
            if ALLOW_LOCAL_STORE:
                try:
                    portfolio.save_positions(pos)
                    st.session_state['positions_saved_at'] = \
                        datetime.datetime.now().isoformat(timespec="seconds")
                    st.success(f"✅ {len(pos)}종목 반영·저장")
                except Exception as _ex:
                    st.success(f"✅ {len(pos)}종목 반영")
                    st.warning(f"로컬 저장 실패: {_ex}")
            else:
                st.success(f"✅ {len(pos)}종목 반영 (이 브라우저 세션에만 유지)")
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
            if st.button("🗑️ 이 세션 보유종목 지우기", type="secondary"):
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

                st.markdown("#### 📋 포트폴리오 전체 요약 (기간별: 중앙 예상수익률 · 예측등급 · ESS)")
                st.dataframe(pd.DataFrame(port_rows), use_container_width=True, hide_index=True)

                st.markdown("#### 🗂️ 종목별 상세")
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
                            use_container_width=True, hide_index=True)

                        st.markdown("**추가매수(물타기) 허용 조건** — 전부 통과해야 허용")
                        for label, ok in pv['averaging_down_checks']:
                            st.markdown(f"- {'✅' if ok else '❌'} {label}")
                        if not pv['averaging_down_allowed']:
                            st.warning("추가매수 조건을 충족하지 못했습니다. 손실 중이라는 이유만으로 "
                                       "기계적 물타기를 권하지 않습니다.")

                        if m.get('is_multi_account'):
                            st.caption("복수 계좌 보유 — 계좌별 내역")
                            st.dataframe(pd.DataFrame(m['accounts']),
                                         use_container_width=True, hide_index=True)
    st.markdown("---")

# 🚨 [사용자 요청] 실시간 글로벌/국내 주요 증시 지수 전광판 최상단배치
m_indices = engine_init.get_market_indices()
idx_col1, idx_col2, idx_col3, idx_col4 = st.columns(4)

with idx_col1:
    st.metric("KOSPI 코스피", f"{m_indices['kospi']['price']}", f"{m_indices['kospi']['change']} ({m_indices['kospi']['pct']})")
with idx_col2:
    st.metric("KOSDAQ 코스닥", f"{m_indices['kosdaq']['price']}", f"{m_indices['kosdaq']['change']} ({m_indices['kosdaq']['pct']})")
with idx_col3:
    st.metric("USD/KRW 환율", f"{m_indices['usd_krw']['price']}", f"{m_indices['usd_krw']['change']} ({m_indices['usd_krw']['pct']})")
with idx_col4:
    st.metric("S&P 500", f"{m_indices['sp500']['price']}", f"{m_indices['sp500']['change']} ({m_indices['sp500']['pct']})")

if m_indices['kospi']['price'] == 'N/A' or m_indices['kosdaq']['price'] == 'N/A':
    st.warning("⚠️ **KOSPI·KOSDAQ 데이터 미수신 알림**: 최신 지수 수치가 연동되지 않아 **`[시장 국면: 판정 보류]`** 상태가 적용되었으며, 매매 적합도 상한(59점) 게이트 통제가 활성화되었습니다.")

st.markdown("<div style='margin-bottom: 12px;'></div>", unsafe_allow_html=True)

# 파이프라인 연산 실행 — 화면 전체가 이 단일 스냅샷 하나만 사용한다
with st.spinner(f"[{resolved_name}] 동적 무결성 점수 및 시계열 연산 중..."):
    snap, snap_origin = get_shared_snapshot(target_ticker, t_ref_str, rho_cutoff)
    report_text, snapshot, latest_fund, sr117_audit, guard_res = build_report_context(snap)

tech_df   = snap['tech_df']
fund_df   = snap['fund_df']
sim_res   = snap['sim_res']
val_eval  = snap['val_eval']
four_scores = snap['four_scores']
price_pos = snap['price_pos']
matrix_data = snap['source_matrix']

_m = snap['meta']
_origin_txt = {"scan": "상단 스캔 결과와 **동일한 스냅샷**", "cache": "캐시된 스냅샷", "fresh": "새로 산출한 스냅샷"}[snap_origin]
st.caption(
    f"🔗 {_origin_txt} · 생성 {_m['generated_at']} · Run `{_m['run_id']}` · "
    f"분석기준일 `{_m['analysis_date']}` · 가격기준 `{_m['price_asof']}` ({_m['price_type']}) · "
    f"재무: 현재 게시값 스냅샷 `{_m['fiscal_asof']}` 수집"
    f"{' (보고서 기준일 아님 — 공시 원문 미연동)' if _m.get('fiscal_is_estimated') else ''} · "
    f"calc `{_m['calc_version']}` / model `{_m['model_version']}` / rulebook `{_m['rulebook_version']}`")

if snap.get('status') == 'REVIEW_REQUIRED':
    st.error("🚨 **[무결성 게이트 발동 — 재검토 필요]** 모듈 간 대조에서 모순이 발견되어 이 종목의 추천을 중단했습니다.\n\n"
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

chg_color = "#30d158" if pct_change >= 0 else "#ff453a"
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
<div style='background: #1c1c1e; border: 2px solid #64d2ff; border-radius: 18px; padding: 24px 28px; margin-bottom: 20px; box-shadow: 0 8px 30px rgba(100, 210, 255, 0.12);'>
    <div style='display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 16px;'>
        <div>
            <div style='background: rgba(100, 210, 255, 0.12); border: 2px solid #64d2ff; border-radius: 14px; padding: 10px 22px; display: inline-block; margin-bottom: 12px;'>
                <span style='font-size: 3.4rem; font-weight: 900; color: #64d2ff; letter-spacing: -0.5px;'>{resolved_name}</span>
                <span style='font-size: 2.2rem; font-weight: 800; color: #ffffff; margin-left: 12px;'>({target_ticker})</span>
            </div>
            <div style='font-size: 3.2rem; font-weight: 900; color: {chg_color}; margin: 6px 0;'>
                {curr_p_formatted} <span style='font-size: 1.8rem; font-weight: 800; margin-left: 8px;'>{chg_text}</span>
            </div>
            <p style='margin: 8px 0 0 0; color: #30d158; font-size: 1.0rem; font-weight: bold;'>
                <b>통화 코드</b>: <code>{unit_currency}</code> | <b>가격 단위</b>: <code>{unit_str}</code> | <b>시장 상태</b>: {_mkt['state']} | <b>분석 기준일</b>: {t_ref_str}
            </p>
        </div>
        <div style='text-align: right; color: #d2d2d7; font-size: 1.05rem;'>
            <p style='margin:0; font-weight: bold;'><b>시가</b>: {open_p:,.0f}{unit_str} | <b style='color:#ff453a;'>고가</b>: {high_p:,.0f}{unit_str} | <b style='color:#30d158;'>저가</b>: {low_p:,.0f}{unit_str}</p>
            <p style='margin:8px 0 0 0;'><b>거래량</b>: <b style='color:#64d2ff;'>{volume_p:,.0f}주</b> (20일 평균 대비 {fmt_num(tech_df['volume_ratio'].iloc[-1] if 'volume_ratio' in tech_df.columns else None, '.2f', '배')}) | <b>20일 평균 거래대금</b>: {fmt_num((four_scores.get('avg_turnover_20d') or 0) / 1e8, ',.0f', '억원', na='미산출')}</p>
        </div>
    </div>
    <hr style='border: 0; border-top: 1px solid #2c2c2e; margin: 14px 0 14px 0;'>
    <!-- 📊 9대 핵심 펀더멘털 & 밸류에이션 전광판 -->
    <div style='display: grid; grid-template-columns: repeat(auto-fit, minmax(135px, 1fr)); gap: 10px;'>
        <div style='background: #141416; padding: 10px 12px; border-radius: 12px; border: 1px solid #2c2c2e; text-align: center;'>
            <p style='margin: 0; font-size: 0.75rem; color: #86868b; font-weight: bold;'>PER (주가수익비율)</p>
            <p style='margin: 4px 0 0 0; font-size: 1.15rem; color: #30d158; font-weight: bold;'>{fmt_num(per_val, '.1f', '배', na='미수신')}</p>
        </div>
        <div style='background: #141416; padding: 10px 12px; border-radius: 12px; border: 1px solid #2c2c2e; text-align: center;'>
            <p style='margin: 0; font-size: 0.75rem; color: #86868b; font-weight: bold;'>PBR (주가순자산비율)</p>
            <p style='margin: 4px 0 0 0; font-size: 1.15rem; color: #64d2ff; font-weight: bold;'>{fmt_num(pbr_val, '.2f', '배', na='미수신')}</p>
        </div>
        <div style='background: #141416; padding: 10px 12px; border-radius: 12px; border: 1px solid #2c2c2e; text-align: center;'>
            <p style='margin: 0; font-size: 0.75rem; color: #86868b; font-weight: bold;'>ROE (자기자본이익률)</p>
            <p style='margin: 4px 0 0 0; font-size: 1.15rem; color: #ff9f0a; font-weight: bold;'>{fmt_num(roe_val, '.1f', '%', na='미수신')}</p>
        </div>
        <div style='background: #141416; padding: 10px 12px; border-radius: 12px; border: 1px solid #2c2c2e; text-align: center;'>
            <p style='margin: 0; font-size: 0.75rem; color: #86868b; font-weight: bold;'>EPS (주당순이익)</p>
            <p style='margin: 4px 0 0 0; font-size: 1.15rem; color: #f5f5f7; font-weight: bold;'>{fmt_num(eps_val, ',.0f', '원', na='미수신')}</p>
        </div>
        <div style='background: #141416; padding: 10px 12px; border-radius: 12px; border: 1px solid #2c2c2e; text-align: center;'>
            <p style='margin: 0; font-size: 0.75rem; color: #86868b; font-weight: bold;'>BPS (주당순자산)</p>
            <p style='margin: 4px 0 0 0; font-size: 1.15rem; color: #f5f5f7; font-weight: bold;'>{fmt_num(bps_val, ',.0f', '원', na='미수신')}</p>
        </div>
        <div style='background: #141416; padding: 10px 12px; border-radius: 12px; border: 1px solid #2c2c2e; text-align: center;'>
            <p style='margin: 0; font-size: 0.75rem; color: #86868b; font-weight: bold;'>주당 배당금 (수익률)</p>
            <p style='margin: 4px 0 0 0; font-size: 1.05rem; color: #30d158; font-weight: bold;'>{fmt_num(div_payout, ',.0f', '원', na='무배당·미공시')} ({fmt_pct(div_yield, digits=2)})</p>
        </div>
        <div style='background: #141416; padding: 10px 12px; border-radius: 12px; border: 1px solid #2c2c2e; text-align: center;'>
            <p style='margin: 0; font-size: 0.75rem; color: #86868b; font-weight: bold;'>배당락일 (추정)</p>
            <p style='margin: 4px 0 0 0; font-size: 0.9rem; color: #d2d2d7; font-weight: bold;'>{div_date or '—'}</p>
            <p style='margin: 2px 0 0 0; font-size: 0.68rem; color: #ff9f0a;'>{('D-' + str(div_info['days_to_ex']) + ' · 관례 추정') if div_info.get('available') and div_info.get('days_to_ex') is not None else '공시 미연동'}</p>
        </div>
        <div style='background: #141416; padding: 10px 12px; border-radius: 12px; border: 1px solid #2c2c2e; text-align: center;'>
            <p style='margin: 0; font-size: 0.75rem; color: #86868b; font-weight: bold;'>부채비율 (재무안전)</p>
            <p style='margin: 4px 0 0 0; font-size: 1.15rem; color: #30d158; font-weight: bold;'>{fmt_num(debt_val, '.1f', '%', na='미수신')}</p>
        </div>
        <div style='background: #141416; padding: 10px 12px; border-radius: 12px; border: 1px solid #bf5af2; text-align: center;'>
            <p style='margin: 0; font-size: 0.75rem; color: #bf5af2; font-weight: bold;'>💎 시장조정 펀더멘털 적정가</p>
            <p style='margin: 4px 0 0 0; font-size: 1.15rem; color: #bf5af2; font-weight: bold;'>{fmt_num(four_scores.get('displayed_fair_value'), suffix='원')}</p>
        </div>
    </div>
    <!-- 🛡️ 가격 출처 vs 공시 출처 분리 및 다중 출처 교차검증 -->
    <p style='margin: 12px 0 0 0; color: #30d158; font-size: 0.8rem; text-align: center; border-top: 1px solid #2c2c2e; padding-top: 8px;'>
        🛡️ <b>데이터 출처 분리</b>: <b>연동된 시세 출처</b> — 네이버증권(기준) · 다음금융(교차검증). <b>미연동</b> — KRX·KIND·FnGuide·Investing.
        <b>DART·KIND·기업IR</b>은 공시·재무 출처이며 현재가 대조에 사용하지 않습니다.
    </p>
</div>
""", unsafe_allow_html=True)

# 📈 [상단 차트 추가] 실시간 주가 캔들/이동평균선(5·20·60·120일) 차트 바로보기
with st.expander(f"📈 [클릭] [{resolved_name}] 실시간 주가 차트 (5·20·60·120일선 & RSI/거래량) 바로보기", expanded=False):
    recent_tech_top = tech_df.tail(90)
    x_dates_top = pd.to_datetime(recent_tech_top['trade_date'])
    
    fig_top, (ax_p_top, ax_r_top, ax_v_top) = plt.subplots(3, 1, figsize=(12, 8), sharex=True, gridspec_kw={'height_ratios': [3, 1, 1]})
    fig_top.patch.set_facecolor('#000000')
    
    for ax in (ax_p_top, ax_r_top, ax_v_top):
        ax.set_facecolor('#1c1c1e')
        ax.tick_params(colors='#f5f5f7')
        ax.grid(True, color='#2c2c2e', linestyle='--')
        
    ax_p_top.plot(x_dates_top, recent_tech_top['adj_close'], label=f"{resolved_name} 수정종가", color='#f5f5f7', linewidth=2.5)
    ax_p_top.plot(x_dates_top, recent_tech_top['sma_5'], label="5일선", color='#64d2ff', linewidth=1.5)
    ax_p_top.plot(x_dates_top, recent_tech_top['sma_20'], label="20일선", color='#ff9f0a', linewidth=2.0)
    ax_p_top.plot(x_dates_top, recent_tech_top['sma_60'], label="60일선", color='#bf5af2', linestyle='--', linewidth=1.5)
    ax_p_top.plot(x_dates_top, recent_tech_top['sma_120'], label="120일선", color='#ff3b30', linestyle=':', linewidth=1.5)
    ax_p_top.set_title(f"📈 [{resolved_name}] 기술적 차트 (이동평균선 & RSI/거래량)", color='#f5f5f7', fontsize=12)
    ax_p_top.legend(facecolor='#1c1c1e', edgecolor='#2c2c2e', labelcolor='#f5f5f7', loc='upper left')
    
    ax_r_top.plot(x_dates_top, recent_tech_top['rsi_14'], label="RSI 14", color='#bf5af2', linewidth=1.8)
    ax_r_top.axhline(70, color='#ff453a', linestyle='--', alpha=0.7)
    ax_r_top.axhline(30, color='#30d158', linestyle='--', alpha=0.7)
    ax_r_top.set_ylabel("RSI")
    
    ax_v_top.bar(x_dates_top, recent_tech_top['volume'], color='#2997ff', alpha=0.7)
    ax_v_top.plot(x_dates_top, recent_tech_top['vol_20_avg'], color='#ff9f0a', linewidth=1.5)
    ax_v_top.set_ylabel("거래량")
    
    plt.tight_layout()
    st.pyplot(fig_top)

# ═══════════════════════════════════════════════════════════════════════════
# 🧭 최종 결론 — "이 주식 사? 말어?"
# 6개 탭의 독립 판정을 가중 평균하되, 거부 조건은 평균으로 상쇄되지 않게 따로 본다.
# ═══════════════════════════════════════════════════════════════════════════
verdict = q_engine.build_final_verdict(snap)

_ACTION_STYLE = {
    'BUY':        ("#30d158", "🟢", "매수"),
    'ACCUMULATE': ("#7bd88f", "🟢", "분할매수"),
    'HOLD':       ("#ff9f0a", "🟡", "관망"),
    'REDUCE':     ("#ff7a45", "🟠", "비중 축소"),
    'SELL':       ("#ff453a", "🔴", "매도"),
    'NO_TRADE':   ("#ff453a", "🔴", "매수 안 함"),
}
_vc, _vi, _vshort = _ACTION_STYLE.get(verdict['action'], ("#86868b", "⚪", "판단 보류"))
_vscore = verdict['score']

# 실행 가격 기준 — 종합 결론 배너 안에 함께 표시 (표시 위치는 이 배너 한 곳만; 상세 카드에서는 중복 표기하지 않음)
rec_buy_val = four_scores.get('recommended_buy_price')
if rec_buy_val is not None:
    rec_buy_display = f"{rec_buy_val:,.0f}원 이하"
elif four_scores.get('fair_value_status') == 'OUT_OF_DOMAIN':
    # 성장 기대가 가격을 지배하는 종목 — 신뢰도 문제가 아니라 모델이 성립하지 않는다
    rec_buy_display = "산출 불가 (모델 범위 밖)"
else:
    rec_buy_display = "신뢰도 미달"
_ex_tgt = fmt_num(four_scores.get('target_tech_1st'), suffix='원', na='산출 불가')
_ex_stop = fmt_num(four_scores.get('stop_loss_price'), suffix='원', na='산출 불가')

# ⏱️ DeMARK 매수 포인트 — 신호 상태와 유효 하한선(TDST 지지)을 함께 보여준다.
_dme = four_scores.get('demark_entry') or {}
_dm_state = _dme.get('state')
_dm_color = {'COMPLETE': '#30d158', 'SETUP_DONE': '#30d158',
             'FORMING': '#ff9f0a'}.get(_dm_state, '#86868b')
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

st.markdown(f"""
<div style='background:linear-gradient(135deg,#141416 0%,#1c1c1e 100%);
            border:3px solid {_vc}; border-radius:20px; padding:22px 26px; margin-bottom:16px;
            box-shadow:0 10px 34px {_vc}22;'>
  <div style='display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:14px;'>
    <div>
      <p style='margin:0; font-size:0.85rem; color:#86868b; font-weight:700;'>
        {resolved_name} — 퀀트 종합 결론</p>
      <p style='margin:4px 0 0 0; font-size:2.5rem; font-weight:900; color:{_vc}; line-height:1.15;'>
        {_vi} {verdict['headline']}</p>
    </div>
    <div style='text-align:right;'>
      <p style='margin:0; font-size:0.8rem; color:#86868b;'>종합 점수</p>
      <p style='margin:0; font-size:3rem; font-weight:900; color:{_vc}; line-height:1;'>
        {fmt_num(_vscore, ',.0f', na='—')}<span style='font-size:1.1rem; color:#86868b;'> / 100</span></p>
      <p style='margin:2px 0 0 0; font-size:0.9rem; font-weight:800; color:{_vc};'>{_vshort}</p>
    </div>
  </div>
  <div style='display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:10px;
              margin-top:16px; padding-top:14px; border-top:1px solid #2c2c2e;'>
    <div style='background:#141416; border:1px solid #30d15855; border-radius:12px; padding:10px 14px;'>
      <p style='margin:0; font-size:0.78rem; color:#86868b; font-weight:700;'>🟢 권장 매수가 <span style='font-weight:400;'>(신규 진입 기준)</span></p>
      <p style='margin:2px 0 0 0; font-size:1.3rem; font-weight:900; color:#30d158;'>{rec_buy_display}</p>
    </div>
    <div style='background:#141416; border:1px solid #64d2ff55; border-radius:12px; padding:10px 14px;'>
      <p style='margin:0; font-size:0.78rem; color:#86868b; font-weight:700;'>🔵 1차 목표가 <span style='font-weight:400;'>(현재가 기준 기술 레벨)</span></p>
      <p style='margin:2px 0 0 0; font-size:1.3rem; font-weight:900; color:#64d2ff;'>{_ex_tgt}</p>
    </div>
    <div style='background:#141416; border:1px solid #ff453a55; border-radius:12px; padding:10px 14px;'>
      <p style='margin:0; font-size:0.78rem; color:#86868b; font-weight:700;'>🔴 손절가 <span style='font-weight:400;'>(현재가 기준 — 보유자용)</span></p>
      <p style='margin:2px 0 0 0; font-size:1.3rem; font-weight:900; color:#ff453a;'>{_ex_stop}</p>
    </div>
    <div style='background:#141416; border:1px solid {_dm_color}55; border-radius:12px; padding:10px 14px;'>
      <p style='margin:0; font-size:0.78rem; color:#86868b; font-weight:700;'>⏱️ DeMARK 매수 포인트 <span style='font-weight:400;'>(9-13 추세 소진)</span></p>
      <p style='margin:2px 0 0 0; font-size:1.0rem; font-weight:800; color:{_dm_color}; line-height:1.3;'>{_dm_head}</p>
      <p style='margin:3px 0 0 0; font-size:0.78rem; color:#d2d2d7;'>{_dm_line}</p>
    </div>
  </div>
  <p style='margin:10px 0 0 0; font-size:0.78rem; color:#ff9f0a;'>
    ⚠️ 실행 가격 기준: 목표·손절은 현재가 기준 기술 레벨이고 권장 매수가는 신규 진입 기준입니다.
    신규 진입 시에는 진입가 기준으로 손절가를 다시 설정해야 합니다.
    DeMARK 매수 포인트는 <b>시점</b> 신호이며, 위 권장 매수가(<b>가격</b> 기준)와 함께 볼 때만 의미가 있습니다.</p>
</div>
""", unsafe_allow_html=True)

# ═══ 🧭 아주 쉬운 결론 — 신규 매수자와 보유자를 절대 섞지 않는다 ═══════════
_easy = q_engine.build_easy_advice(
    four_scores, verdict, realtime_price,
    user_avg=(user_entry_price if user_entry_price > 0 else None),
    user_qty=(user_quantity if user_quantity > 0 else None))
_ec1, _ec2 = st.columns(2)
with _ec1:
    _nb = _easy['new_buyer']
    st.markdown(f"""
    <div style='background:#141416; border:2px solid #2c2c2e; border-radius:14px; padding:14px 16px; height:100%;'>
      <p style='margin:0; font-size:0.78rem; color:#86868b; font-weight:700;'>🧭 아직 이 종목이 없다면</p>
      <p style='margin:6px 0; font-size:1.15rem; font-weight:900; color:#f5f5f7;'>{_nb['emoji']} {_nb['line']}</p>
      <p style='margin:0; font-size:0.88rem; color:#d2d2d7; line-height:1.55;'>{_nb['detail']}</p>
    </div>""", unsafe_allow_html=True)
with _ec2:
    _hd = _easy['holder']
    if _hd:
        st.markdown(f"""
        <div style='background:#141416; border:2px solid #2c2c2e; border-radius:14px; padding:14px 16px; height:100%;'>
          <p style='margin:0; font-size:0.78rem; color:#86868b; font-weight:700;'>💼 보유 중이라면 (평단 {user_entry_price:,.0f}원 · 현재 {_hd['ret_pct']:+.1f}%)</p>
          <p style='margin:6px 0; font-size:1.15rem; font-weight:900; color:#f5f5f7;'>{_hd['emoji']} {_hd['line']}</p>
          <p style='margin:0; font-size:0.88rem; color:#d2d2d7; line-height:1.55;'>{_hd['detail']}</p>
        </div>""", unsafe_allow_html=True)
    else:
        st.markdown("""
        <div style='background:#141416; border:2px dashed #2c2c2e; border-radius:14px; padding:14px 16px; height:100%;'>
          <p style='margin:0; font-size:0.78rem; color:#86868b; font-weight:700;'>💼 보유 중이라면</p>
          <p style='margin:6px 0; font-size:0.95rem; color:#d2d2d7; line-height:1.6;'>
            사이드바의 <b>내 포지션 입력</b>에 평균 매수가와 수량을 넣으면<br>
            보유·일부 매도·손절·추가 매수 여부를 <b>내 평단 기준</b>으로 알려드립니다.</p>
        </div>""", unsafe_allow_html=True)
st.caption("⚠️ 신규 매수 기준과 보유자 기준은 서로 다릅니다 — 신규 진입가와 보유자 손절가가 "
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
@st.cache_data(ttl=600)
def _load_calibration_meta():
    try:
        import json as _json_cal
        _p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          ".portfolio", "calibration.json")
        with open(_p, encoding='utf-8') as _f:
            _c = _json_cal.load(_f)
        return {'total_cases': _c.get('total_cases'),
                'rulebook_version': _c.get('rulebook_version')}
    except Exception:
        return {}


_calib_all = _load_calibration_meta()
if _calib_all.get('total_cases'):
    _extra_bits.append(f"📚 모델 {_calib_all.get('rulebook_version', '')} · "
                       f"누적 케이스 {_calib_all['total_cases']:,}건")
if _extra_bits:
    st.caption("  ·  ".join(_extra_bits))

if verdict['vetoes']:
    st.error("**⛔ 매수 결론을 막는 조건 " + str(len(verdict['vetoes'])) + "건** — "
             "다른 점수가 높아도 이 조건들이 먼저입니다.\n\n"
             + "\n".join(f"- {x}" for x in verdict['vetoes']))

# 신호 간 이견이 있었지만 판정을 폐기하지 않고 보수적으로 화해시킨 경우 그 내역을 보여준다.
_soft_notes = four_scores.get('soft_conflict_notes') or []
if _soft_notes:
    st.info("**🤝 신호 간 이견을 화해시켰습니다** — 모듈들이 다른 방향을 가리켰지만, "
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
    st.markdown("**📊 이 점수는 이렇게 나왔습니다**")
    st.dataframe(pd.DataFrame([{
        "구성 항목": c['label'],
        "점수": "—" if c['score'] is None else f"{c['score']}",
        "비중": f"{c['weight_pct']:.0f}%",
        "기여": "—" if c['contribution'] is None else f"{c['contribution']:.1f}",
    } for c in verdict['composition']]), use_container_width=True, hide_index=True)
    if verdict['cap_applied']:
        st.markdown(f"가중합 **{verdict['raw_weighted_sum']:.0f}점** → 게이트 상한 적용 → "
                    f"**{verdict['score']}점**")
        if verdict.get('gate_reason'):
            st.caption("상한 사유: " + str(verdict['gate_reason'])[:300])
    else:
        st.markdown(f"가중합 **{verdict['raw_weighted_sum']:.0f}점** = 최종 **{verdict['score']}점** "
                    f"(상한 미적용)")
    st.caption("이 표가 **유일한 종합 점수 산식**입니다. 아래 관점별 판정은 근거를 보여줄 뿐 "
               "따로 합산하지 않습니다 — 점수가 둘이면 어느 쪽을 믿을지 알 수 없습니다.")
with _vc2:
    st.markdown("**🧭 관점별 독립 판정** (합산하지 않음)")
    _pv = pd.DataFrame([{
        "관점": t['label'],
        "점수": "—" if t['score'] is None else f"{t['score']}",
        "판정": t['verdict'],
    } for t in verdict['tabs']])
    st.dataframe(_pv, use_container_width=True, hide_index=True)
    st.markdown("**🧾 한눈에**")
    for s in verdict['summary']:
        st.markdown(f"- {s}")
    st.caption("⚠️ 투자 권유가 아닙니다. 최종 판단과 손익 책임은 투자자 본인에게 있습니다.")

st.markdown("---")

# 🎯 [판정 근거 상세 — 시간축 3단계 정리보다 위에 배치. 실행 가격은 위 배너 한 곳에서만 표기]
action_bg_color = "#1c1c1e"

st.markdown(f'''
<div style="background: {action_bg_color}; padding: 20px; border-radius: 12px; margin-bottom: 20px; border: 1px solid #3a3a3c;">
<div style="margin-bottom:20px;">
    <h3 style="margin:0; color:#f5f5f7;">🎯 판정 근거 상세</h3>
    <p style="margin:4px 0 0 0; color:#86868b; font-size:0.85rem;">종합 결론·점수·실행 가격 기준(권장 매수가/1차 목표가/손절가)은 화면 맨 위 배너에 있습니다. 여기서는 그 근거만 봅니다.</p>
</div>

<div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap:15px; margin-bottom:15px;">
<div style="background:#2c2c2e; padding:15px; border-radius:8px; border-left: 4px solid #bf5af2;">
    <h4 style="color:#f5f5f7; margin:0 0 10px 0;">🛡️ 신뢰도 통제 상한</h4>
    <p style="color:#d2d2d7; margin:2px 0; font-size:0.9rem;">- 분석 신뢰도: {four_scores.get('analysis_confidence', 0)}점</p>
    <p style="color:#d2d2d7; margin:2px 0; font-size:0.9rem;">- 전략 품질: {fmt_num(four_scores.get('strategy_quality_score'), suffix='점', na='미검증')}</p>
    <p style="color:#d2d2d7; margin:2px 0; font-size:0.9rem;">- Blind Test: {four_scores.get('blind_test_status', '미수행')}</p>
    <p style="color:#ff9f0a; margin:10px 0 2px 0; font-size:0.9rem; font-weight:bold;">- 최종점수 상한 캡: {four_scores.get('sq_cap', 100)}점</p>
</div>
</div>

<div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap:15px;">
<div style="background:#2c2c2e; padding:15px; border-radius:8px;">
    <h4 style="color:#f5f5f7; margin:0 0 10px 0;">⏱️ DeMARK 신호</h4>
    <p style="color:#30d158; margin:2px 0; font-size:0.9rem;">- Bullish: {four_scores.get('demark_bullish_score', 0)}점</p>
    <p style="color:#ff453a; margin:2px 0; font-size:0.9rem;">- Bearish: {four_scores.get('demark_bearish_score', 0)}점</p>
    <p style="color:#d2d2d7; margin:2px 0; font-size:0.9rem;">- 방향: {four_scores.get('demark_direction_text', '중립')}</p>
</div>

<div style="background:#2c2c2e; padding:15px; border-radius:8px;">
    <h4 style="color:#f5f5f7; margin:0 0 10px 0;">✅ 확인 지표</h4>
    <p style="color:#d2d2d7; margin:2px 0; font-size:0.9rem;">- TDST: {four_scores.get('tdst_support_str', '')} / {four_scores.get('tdst_resist_str', '')}</p>
    <p style="color:#d2d2d7; margin:2px 0; font-size:0.9rem;">- Bollinger: {four_scores.get('bb_state', '산출 불가')} (밴드 내 {fmt_num(four_scores.get('bb_position_pct'), '.0f', '%')})</p>
    <p style="color:#d2d2d7; margin:2px 0; font-size:0.9rem;">- Williams %R: {fmt_num(four_scores.get('williams_r_value'), '.0f')}</p>
    <p style="color:#d2d2d7; margin:2px 0; font-size:0.9rem;">- RSI: {fmt_num(four_scores.get('rsi_value'), '.0f')}</p>
</div>
</div>

<div style="background:#2c2c2e; padding:15px; border-radius:8px; margin-top:15px;">
<h4 style="color:#f5f5f7; margin:0 0 8px 0;">📌 최종 근거</h4>
<p style="color:#d2d2d7; margin:0; line-height:1.5; font-size:0.95rem;">{four_scores.get('final_action_explain', '')}</p>
</div>
</div>
''', unsafe_allow_html=True)

_zone = four_scores.get('entry_zone', four_scores.get('chase_buy_status'))
_bem_str = fmt_num(four_scores.get('buy_entry_max'), suffix='원')
if _zone == "판정 불가":
    st.warning("⚠️ **[진입 판정 불가]**: 적정가 신뢰도가 기준에 미달하여 권장 매수가를 산출하지 못했습니다. "
               "현재가가 적정 진입구간 안인지 판단할 수 없으므로 신규 진입을 권하지 않습니다.")
elif _zone == "안전마진 확보":
    st.success(f"🟢 **[안전마진 확보]**: 현재가({curr_price:,.0f}원)가 권장 매수가({_bem_str}) 이하입니다.")
elif _zone == "적정가 이하 (안전마진 미확보)":
    st.info(f"🔵 **[안전마진 미확보]**: 현재가({curr_price:,.0f}원)는 적정가 아래이지만 "
            f"권장 매수가({_bem_str})보다는 높습니다. 안전마진 확보 전까지 분할 진입은 보류를 권장합니다.")
elif _zone:
    st.error(f"⚠️ **[{_zone}]**: 현재가({curr_price:,.0f}원)가 적정가"
             f"({fmt_num(four_scores.get('displayed_fair_value'), suffix='원')})를 초과했습니다. "
             f"신규 추격매수보다 눌림목 또는 지지선 안착 확인을 권장합니다.")

if four_scores.get('contradiction_detected', False):
    reasons_str = " / ".join(four_scores.get('contradiction_reasons', []))
    st.error(f"🚨 **[무결성 게이트 발동 — 재검토 필요]**: 이 종목에서 데이터 모순이 탐지되었습니다. 추천 결과를 신뢰하기 전에 아래 사유를 확인하세요.\n\n**탐지 사유**: {reasons_str}")

st.markdown("---")

# ── 🌐 시장·글로벌·뉴스 컨텍스트 — 이 종목만 보지 않고 판을 함께 본다 ─────────
_mkt_ctx = snap.get('market_context') or {}
st.markdown(f"### 🌐 [{resolved_name}] 시장·글로벌·뉴스 컨텍스트")
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
        st.markdown(f"**⚪ 상장시장 국면 — {_mkt_ctx.get('market', '')}**")
        st.caption("미수신 — " + str(_dom.get('reason', '지수 데이터 없음')))

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
        st.dataframe(pd.DataFrame(_grows), use_container_width=True, hide_index=True)
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
        st.markdown(f"**📰 실제 종목 뉴스 (최근 {len(_news.get('items', []))}건)**")
        if _nfl.get('risk_count'):
            st.error(f"⚠️ 제목에 확인이 필요한 낱말이 있는 기사 **{_nfl['risk_count']}건** — "
                     "종합 점수에 상한이 걸렸습니다. 기사 원문을 직접 확인하세요.")
        for _it in (_news.get('items') or [])[:6]:
            _flag = " 🔴" + "·".join(_it['risk_hits']) if _it.get('risk_hits') else ""
            _link = f"[{_it['title']}]({_it['url']})" if _it.get('url') else _it['title']
            st.markdown(f"- {_link}{_flag}")
            _meta_line = f"{_it.get('press', '')} · {_it.get('datetime', '')}"
            if _it.get('related_count'):
                _meta_line += f" · 연관기사 {_it['related_count']}건"
            st.caption("  " + _meta_line)
            if _it.get('related'):
                with st.expander(f"연관 뉴스 {_it['related_count']}건 보기"):
                    for _r in _it['related'][:8]:
                        _rl = f"[{_r['title']}]({_r['url']})" if _r.get('url') else _r['title']
                        st.markdown(f"- {_rl}  \n  {_r.get('press','')} · {_r.get('datetime','')}")
        st.caption("출처: " + str(_news.get('source', '')) +
                   " — 제목·언론사·시각을 원문 그대로 표시하며, 기사 내용을 요약·해석해 "
                   "만들어 내지 않습니다. 위험 표시는 제목의 낱말 일치일 뿐입니다.")
    else:
        st.markdown("**📰 실제 종목 뉴스**")
        st.caption("미수신 — " + str(_news.get('reason', '')))

for _note in (_mkt_ctx.get('notes') or []):
    st.caption("ℹ️ " + str(_note))

# ── 이 컨텍스트가 퀀트 점수를 얼마나 움직였는지 (상한과는 별개의 산식 반영분) ──
_rgd = four_scores.get('market_regime_detail') or {}
with st.expander("🧮 이 시장·뉴스가 퀀트 점수를 얼마나 움직였나 (산식 반영분)", expanded=False):
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
    st.dataframe(pd.DataFrame(_rows_ctx), use_container_width=True, hide_index=True)

    if _rgd.get('global_hits'):
        st.markdown("**글로벌 감점 내역** (규칙집 [RULES_MARKET_CONTEXT] 기준)")
        st.dataframe(pd.DataFrame([{"사유": t, "감점": f"-{p:.0f}점"}
                                   for t, p in _rgd['global_hits']]),
                     use_container_width=True, hide_index=True)
    if _rgd.get('global_missing'):
        st.caption("미수신 지표(감점도 가점도 하지 않음): " + ", ".join(_rgd['global_missing']))
    if four_scores.get('context_cap', 100) < 100:
        st.markdown(f"위 반영분과 **별개로**, 상한 규칙이 최종 점수를 "
                    f"**{four_scores.get('context_cap')}점 이하**로 제한했습니다.")

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
            st.caption("📌 오늘 판정을 기록했습니다 — 예측 기간이 지나면 사이드바 "
                       "'판정 성적표'에서 실제 주가와 대조해 채점됩니다.")
except Exception:
    pass

st.markdown("---")

# 🚨 [사용자 요청] 뉴스·공시·촉매의 시간축 3단계 분리 분석을 한줄핵심결론 위로 배치
news_tf = engine_init.get_timeframe_news_analysis(target_ticker)
st.caption("ℹ️ 증권사 리서치·IR 원문은 미연동입니다. 아래는 실제 수집한 가격·거래량·게시 투자지표의 관찰과 정량 해석이며, 사건·원인을 추정해 서술하지 않습니다. (실제 뉴스 기사는 위 '시장·글로벌·뉴스 컨텍스트'에 원문 링크로 표시됩니다.)")
st.markdown(f"### 📰 [{resolved_name}] 가격·지표 관찰의 시간축 3단계 정리")

n1, n2, n3 = st.columns(3)
with n1:
    dd = news_tf['daily_drivers']
    st.markdown(f"""
    <div style='background: #1c1c1e; padding: 18px; border-radius: 14px; border: 1px solid #ff453a;'>
        <h4 style='color: #ff453a !important; margin-top:0;'>1. 오늘의 변동 요인 ({dd.get('date', '2026-07-30')})</h4>
        <p style='font-weight: bold; color: #f5f5f7;'>{dd['title']}</p>
        <p style='font-size: 0.9em; color: #d2d2d7;'>💡 <b>관찰 내용</b>: {dd['impact']}</p>
        <span style='font-size: 0.8rem; color: #86868b;'>출처: {dd['source']} | 성향: {dd['sentiment']}</span>
    </div>
    """, unsafe_allow_html=True)

with n2:
    mc = news_tf['medium_catalysts']
    st.markdown(f"""
    <div style='background: #1c1c1e; padding: 18px; border-radius: 14px; border: 1px solid #ff9f0a;'>
        <h4 style='color: #ff9f0a !important; margin-top:0;'>2. 중기 촉매 ({mc.get('timeframe', '1~3개월')})</h4>
        <p style='font-weight: bold; color: #f5f5f7;'>{mc['title']}</p>
        <p style='font-size: 0.9em; color: #d2d2d7;'>💡 <b>정량 해석</b>: {mc['impact']}</p>
        <span style='font-size: 0.8rem; color: #86868b;'>출처: {mc['source']} | 성향: {mc['sentiment']}</span>
    </div>
    """, unsafe_allow_html=True)

with n3:
    ln = news_tf['long_narratives']
    st.markdown(f"""
    <div style='background: #1c1c1e; padding: 18px; border-radius: 14px; border: 1px solid #30d158;'>
        <h4 style='color: #30d158 !important; margin-top:0;'>3. 장기 구조적 서사 ({ln.get('timeframe', '6~12개월')})</h4>
        <p style='font-weight: bold; color: #f5f5f7;'>{ln['title']}</p>
        <p style='font-size: 0.9em; color: #d2d2d7;'>💡 <b>정량 해석</b>: {ln['impact']}</p>
        <span style='font-size: 0.8rem; color: #86868b;'>출처: {ln['source']} | 성향: {ln['sentiment']}</span>
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
        user_pos_color = "#ff9f0a"
        user_pos_advice = f"⚠️ 평단가 대비 손실 구간({pnl_pct:.1f}%)입니다. 20일선 지지 안착 확인 전까지 추가 매수를 유의하세요."
    elif user_entry_price >= realtime_price * 0.95:
        user_pos_tag = "허리 가격 (평균 구간)"
        user_pos_color = "#30d158"
        user_pos_advice = f"🟢 평단가 부근 형성 중입니다. 20일선 수급 안착 시 현재 보유량을 유지하며 관망합니다."
    elif user_entry_price >= realtime_price * 0.85:
        user_pos_tag = "무릎 가격 (저점 진입)"
        user_pos_color = "#64d2ff"
        user_pos_advice = f"💎 수익 구간({pnl_pct:+.1f}%)입니다. 1차 목표가({tp_1st:,.0f}원) 도달 시 분할 익절을 고려하세요."
    else:
        user_pos_tag = "발목 가격 (최저점 매수)"
        user_pos_color = "#bf5af2"
        user_pos_advice = f"🚀 최저가 부근 우수 진입 포지션입니다({pnl_pct:+.1f}%). 잔여 이익을 극대화하세요."

    sma_20_curr = tech_df['sma_20'].iloc[-1]
    
    final_score = four_scores.get('final_quant_score', 50)

    if final_score >= 68:
        add_buy_status = f"🟢 <b>매수 (비중 확대)</b><br><span style='font-size:0.8rem; color:#d2d2d7;'>단기 목표가 {tp_1st:,.0f}원 도달 시 익절</span>"
        add_buy_color = "#30d158"
    elif final_score >= 50:
        add_buy_status = f"🟡 <b>관망 (보유 비중 유지)</b><br><span style='font-size:0.8rem; color:#d2d2d7;'>물타기 금지 / {tp_1st:,.0f}원 반등 시 매도</span>"
        add_buy_color = "#ff9f0a"
    else:
        add_buy_status = f"🔴 <b>매도 (비중 축소)</b><br><span style='font-size:0.8rem; color:#d2d2d7;'>위험 구간 / {sl_1st:,.0f}원 이탈 시 전량 손절</span>"
        add_buy_color = "#ff453a"


    water_msg = ""
    if user_entry_price > tp_1st and realtime_price < tp_1st:
        add_q = max(1, int(user_quantity * (user_entry_price - tp_1st) / (tp_1st - realtime_price)))
        add_cost = add_q * realtime_price
        water_msg = f"<div style='margin-top:14px; background:#2c2c2e; padding:12px 16px; border-radius:10px; border-left: 4px solid #ff9f0a;'><p style='margin:0; font-size:0.9rem; color:#f5f5f7;'>💡 <b>맞춤형 물타기(평단가 인하) 시뮬레이션</b></p><p style='margin:4px 0 0 0; font-size:0.85rem; color:#d2d2d7;'>현재가 기준 <b>약 {add_q:,}주 ({add_cost:,.0f}원)</b> 추가 매수 시, 평단가를 AI 1차 목표가(<b>{tp_1st:,.0f}원</b>)로 낮춰 본전 탈출이 가능합니다.</p></div>"
    elif user_entry_price > realtime_price and user_entry_price <= tp_1st:
        water_msg = f"<div style='margin-top:14px; background:#2c2c2e; padding:12px 16px; border-radius:10px; border-left: 4px solid #30d158;'><p style='margin:0; font-size:0.85rem; color:#d2d2d7;'>💡 현재 평단가가 AI 1차 목표가({tp_1st:,.0f}원)보다 낮아, 본전 탈출을 위한 무리한 추가 물타기 없이 목표가 도달 시 수익 전환이 가능합니다.</p></div>"
    elif user_entry_price > 0:
        water_msg = f"<div style='margin-top:14px; background:#2c2c2e; padding:12px 16px; border-radius:10px; border-left: 4px solid #bf5af2;'><p style='margin:0; font-size:0.85rem; color:#d2d2d7;'>💡 현재 수익 구간입니다. 신규 매수(불타기) 시 평단가가 높아지므로, 잔여 물량은 보유 유지 및 단기 익절 대응을 권장합니다.</p></div>"
    st.markdown(f"""
    <div style='background: #141416; border: 2px solid {user_pos_color}; border-radius: 16px; padding: 20px 24px; margin: 12px 0 20px 0;'>
        <div style='display:flex; justify-size:space-between; align-items:center; flex-wrap:wrap; gap:10px;'>
            <h3 style='margin:0; color:{user_pos_color}; font-size:1.3rem;'>📌 내 보유 포지션 맞춤 포트폴리오 진단 & 물타기 안전성 리포트</h3>
            <span style='background:{user_pos_color}; color:#000; padding:4px 14px; border-radius:14px; font-weight:bold; font-size:0.9rem;'>{user_pos_tag}</span>
        </div>
        <div style='display:grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap:12px; margin:14px 0;'>
            <div style='background:#1c1c1e; padding:12px; border-radius:10px; text-align:center;'>
                <p style='margin:0; font-size:0.8rem; color:#86868b;'>내 평균 매수가</p>
                <p style='margin:2px 0 0 0; font-size:1.2rem; color:#f5f5f7; font-weight:bold;'>{user_entry_price:,.0f} 원</p>
            </div>
            <div style='background:#1c1c1e; padding:12px; border-radius:10px; text-align:center;'>
                <p style='margin:0; font-size:0.8rem; color:#86868b;'>보유 수량 / 총 평가금액</p>
                <p style='margin:2px 0 0 0; font-size:1.1rem; color:#f5f5f7; font-weight:bold;'>{user_quantity} 주 ({eval_val:,.0f} 원)</p>
            </div>
            <div style='background:#1c1c1e; padding:12px; border-radius:10px; text-align:center;'>
                <p style='margin:0; font-size:0.8rem; color:#86868b;'>평가 손익 (수익률)</p>
                <p style='margin:2px 0 0 0; font-size:1.2rem; color:{"#30d158" if pnl_val>=0 else "#ff453a"}; font-weight:bold;'>{pnl_val:+,.0f} 원 ({pnl_pct:+.2f}%)</p>
            </div>
            <div style='background:#1c1c1e; padding:12px; border-radius:10px; text-align:center;'>
                <p style='margin:0; font-size:0.8rem; color:#86868b;'>매수 / 매도 전략</p>
                <p style='margin:2px 0 0 0; font-size:0.9rem; color:{add_buy_color};'>{add_buy_status}</p>
            </div>
        </div>
        <p style='margin:0; font-size:0.95rem; color:#e8e8ed;'>💡 <b>맞춤 대응 가이드</b>: {user_pos_advice}</p>
        {water_msg}
    </div>
    """, unsafe_allow_html=True)
# 🏆 [상단 핵심 카드 5종 (Section 17 UI 표준)]
st.markdown("### 📊 AI 퀀트 4대 분리 점수 & 독립 가격 위치 전광판")
m_col1, m_col2, m_col3, m_col4, m_col5 = st.columns(5)

with m_col1:
    st.markdown(f"""
    <div style='background: #1c1c1e; border: 1px solid #ffd60a; border-radius: 14px; padding: 14px; text-align: center;'>
        <h4 style='color: #86868b !important; margin: 0; font-size: 0.85rem;'>🏆 종목 기본 매력도</h4>
        <h1 style='color: #f5f5f7; margin: 4px 0; font-size: 1.8rem;'>{four_scores['stock_quality_score']} <span style='font-size:0.8rem; color:#86868b;'>/ 100</span></h1>
        <p style='color: #30d158; margin: 0; font-weight: bold; font-size: 0.8rem;'>{four_scores['stock_quality_grade']}</p>
        <p style='color: #86868b; margin: 2px 0 0 0; font-size: 0.7rem;'>기업 가치 및 펀더멘털</p>
    </div>
    """, unsafe_allow_html=True)

with m_col2:
    fit_color = "#30d158" if four_scores['trading_timing_score']>=70 else ("#ff9f0a" if four_scores['trading_timing_score']>=50 else "#ff453a")
    st.markdown(f"""
    <div style='background: #1c1c1e; border: 1px solid #ff375f; border-radius: 14px; padding: 14px; text-align: center;'>
        <h4 style='color: #86868b !important; margin: 0; font-size: 0.85rem;'>🎯 현재 매매 적합도</h4>
        <h1 style='color: #f5f5f7; margin: 4px 0; font-size: 1.8rem;'>{four_scores['trading_timing_score']} <span style='font-size:0.8rem; color:#86868b;'>/ 100</span></h1>
        <p style='color: {fit_color}; margin: 0; font-weight: bold; font-size: 0.8rem;'>{four_scores['trading_action']}</p>
        <p style='color: #86868b; margin: 2px 0 0 0; font-size: 0.7rem;'>진입 타이밍 & 기대값</p>
    </div>
    """, unsafe_allow_html=True)

with m_col3:
    st.markdown(f"""
    <div style='background: #1c1c1e; border: 1px solid #2997ff; border-radius: 14px; padding: 14px; text-align: center;'>
        <h4 style='color: #86868b !important; margin: 0; font-size: 0.85rem;'>🛡️ 분석 신뢰도</h4>
        <h1 style='color: #f5f5f7; margin: 4px 0; font-size: 1.8rem;'>{four_scores['analysis_confidence']} <span style='font-size:0.8rem; color:#86868b;'>/ 100</span></h1>
        <p style='color: #2997ff; margin: 0; font-weight: bold; font-size: 0.8rem;'>{four_scores['conf_grade']}</p>
        <p style='color: #86868b; margin: 2px 0 0 0; font-size: 0.7rem;'>데이터·통계 무결성</p>
    </div>
    """, unsafe_allow_html=True)

with m_col4:
    st.markdown(f"""
    <div style='background: #1c1c1e; border: 1px solid #00f0ff; border-radius: 14px; padding: 14px; text-align: center;'>
        <h4 style='color: #00f0ff !important; margin: 0; font-size: 0.85rem;'>🧪 전략 품질점수 (표본외)</h4>
        <h1 style='color: #00f0ff; margin: 4px 0; font-size: 1.8rem;'>{fmt_num(four_scores.get('strategy_quality_score'), spec='.0f', na='—')} <span style='font-size:0.8rem; color:#86868b;'>/ 100</span></h1>
        <p style='color: #ff9f0a; margin: 0; font-weight: bold; font-size: 0.8rem;'>{four_scores['sq_grade']}</p>
        <p style='color: #86868b; margin: 2px 0 0 0; font-size: 0.7rem;'>OOS Sharpe {fmt_num((snap.get('oos_result') or {}).get('sharpe'), spec='.2f')} | OOS MDD {fmt_pct((snap.get('oos_result') or {}).get('mdd_pct'))} → 상한 {four_scores.get('sq_cap')}점</p>
    </div>
    """, unsafe_allow_html=True)

with m_col5:
    st.markdown(f"""
    <div style='background: #1c1c1e; border: 1px solid #bf5af2; border-radius: 14px; padding: 14px; text-align: center;'>
        <h4 style='color: #86868b !important; margin: 0; font-size: 0.85rem;'>💎 현재 가격 위치</h4>
        <h1 style='color: #bf5af2; margin: 4px 0; font-size: 1.5rem;'>{price_pos['range_name']}</h1>
        <p style='color: #f5f5f7; margin: 0; font-weight: bold; font-size: 0.8rem;'>52주 범위 {price_pos['range_pos_pct']}%</p>
        <p style='color: #86868b; margin: 2px 0 0 0; font-size: 0.7rem;'>독립 가격 위치 산출</p>
    </div>
    """, unsafe_allow_html=True)

# # 🏢 [주요 가점·감점 및 기여도 세부 보기 (Section 18)]
with st.expander("📊 [클릭] 4대 분리 점수별 주요 긍정 기여 및 제한 요인 세부 내역 보기", expanded=False):
    s_col1, s_col2 = st.columns(2)
    with s_col1:
        st.markdown(f"""
        <div style='background:#1c1c1e; border:1px solid #2c2c2e; border-radius:12px; padding:16px;'>
            <p style='margin:0; font-weight:bold; color:#30d158;'>🏆 종목 기본 매력도 세부 기여 내역 ({four_scores['stock_quality_score']}점)</p>
            <p style='margin:4px 0; color:#d2d2d7; font-size:0.85rem;'>펀더멘털 30%: {four_scores['f_score']}점 → 기여 {four_scores['f_score']*0.30:.1f}점</p>
            <p style='margin:4px 0; color:#d2d2d7; font-size:0.85rem;'>밸류에이션 25%: {four_scores['v_score']}점 → 기여 {four_scores['v_score']*0.25:.1f}점</p>
            <p style='margin:4px 0; color:#d2d2d7; font-size:0.85rem;'>재무안전 20%: {four_scores['r_score']}점 → 기여 {four_scores['r_score']*0.20:.1f}점</p>
            <p style='margin:4px 0; color:#d2d2d7; font-size:0.85rem;'>산업경쟁력 15%: {four_scores['s_score']}점 → 기여 {four_scores['s_score']*0.15:.1f}점</p>
            <p style='margin:4px 0; color:#d2d2d7; font-size:0.85rem;'>중장기 구조 10%: {four_scores['i_score']}점 → 기여 {four_scores['i_score']*0.10:.1f}점</p>
            <p style='margin:8px 0 0 0; color:#86868b; font-size:0.78rem;'>※ 기술적 구조({four_scores['t_score']}점)는 기본 매력도가 아니라 매매 적합도에 반영됩니다.</p>
        </div>
        """, unsafe_allow_html=True)
    with s_col2:
        _wr = four_scores.get('win_rate')
        _pe = four_scores.get('path_edge')
        _nr = four_scores.get('non_reach')
        wr_col = "#86868b" if _wr is None else ("#30d158" if _wr >= 60 else "#ff9f0a")
        pe_col = "#86868b" if _pe is None else ("#30d158" if _pe > 5 else "#ff453a")
        nr_col = "#86868b" if _nr is None else ("#ff453a" if _nr >= 60 else "#30d158")
        st.markdown(f"""
        <div style='background:#1c1c1e; border:1px solid #2c2c2e; border-radius:12px; padding:16px;'>
            <p style='margin:0; font-weight:bold; color:#ff9f0a;'>🎯 현재 매매 적합도 주요 진단 요인 ({four_scores['trading_timing_score']}점)</p>
            <p style='margin:4px 0; color:{wr_col}; font-size:0.85rem;'>[관찰 승률] 20일 유사패턴 과거 관찰 승률: {fmt_pct(_wr, signed=False)} (유효표본 {four_scores.get('eff_sample_size', 0):.0f}건 · {four_scores.get('sample_tier', '-')})</p>
            <p style='margin:4px 0; color:{pe_col}; font-size:0.85rem;'>[경로 우위] 20일 평균 수익률: {fmt_pct(_pe)}</p>
            <p style='margin:4px 0; color:{nr_col}; font-size:0.85rem;'>[미도달 비중] 목표가·손절가 모두 미도달: {fmt_pct(_nr, signed=False)}</p>
            <p style='margin:4px 0; color:#2997ff; font-size:0.85rem;'>[게이트 판정] <code>{four_scores['gate_reason']}</code></p>
        </div>
        """, unsafe_allow_html=True)

    blocks = four_scores.get('top3_block_reasons', [])
    if blocks:
        st.markdown("**🚫 TOP 3 추천 미충족 조건**\n\n" + "\n".join(f"- {b}" for b in blocks))
    else:
        st.markdown("**✅ TOP 3 추천 필수조건 전부 통과**")

# 🏢 [6대 영역 세부 프로필 (Section 18)]
with st.expander("🔍 4대 분리 점수 세부 산출 근거 및 실시간 정량 기여도 펼쳐보기"):
    st.write("### 📌 퀀트 점수 산출 로직 (전면 개편)\n")
    st.write("- **원시 종합점수**: 종목 기본 매력도 35% + 현재 매매 적합도 45% + 리스크 안전성 20%\n")
    st.write("- **신뢰도 조정**: 50 + (원시점수 - 50) × (분석 신뢰도/100)\n")
    st.write(f"- **분석 신뢰도**: 데이터 50% + 통계 30% + 모델검증 20% = **{four_scores.get('analysis_confidence', 0)}점** "
             f"(Blind/OOS 미구현이므로 모델검증 항목은 0점)\n")
    st.write("- **최종 행동 원점수**: 신뢰도 조정점수 45% + 기회점수 30% + 실행가능성 15% + 신호 합의도 10%\n")
    st.write("- **최종점수**: 위 원점수에 데이터·통계·전략품질·추격위험 게이트 상한을 적용한 값\n")
    st.write("- *DeMARK 9-13 및 밴드/모멘텀 신호는 현재 매매 적합도에 14% 비중으로 반영됩니다.*\n")
    st.write(f"- **💎 독립 가격 위치 ({price_pos['range_name']} - 52주 범위 {price_pos['range_pos_pct']}%)**: 52주 고저 범위({price_pos['low_52w']:,.0f}~{price_pos['high_52w']:,.0f}{unit_str}) 및 60일선 이격률({price_pos['disparity_60']:+.1f}%).\n")

# 🏛️ [유니스트 김민겸 퀀트 챔피언 인사이트 반영] 퀀터멘탈(Quantamental) 무결성 & 밸류체인 분석 확장 모듈
qm_score = q_engine.calculate_quantamental_hybrid_score(tech_df, fund_df, target_ticker, four_scores=four_scores)
sharpe_turnover = q_engine.calculate_sharpe_and_turnover(sim_res, four_scores=four_scores)
per_upside = q_engine.calculate_sector_per_upside(val_eval, target_ticker)
profile = q_engine.get_company_profile(target_ticker, val_eval=val_eval, four_scores=four_scores)

st.markdown("### 🏛️ 퀀터멘탈(Quantamental) 무결성 & AI 밸류체인 확장 모듈")
q_col1, q_col2, q_col3 = st.columns(3)

with q_col1:
    st.markdown(f"""
    <div style='background: #1c1c1e; border: 1px solid #00f0ff; border-radius: 14px; padding: 18px;'>
        <h4 style='color: #00f0ff !important; margin-top:0;'>1. 시장 국면 & 밸류에이션 위치</h4>
        <p style='margin: 4px 0; font-size:0.9rem;'>- <b>섹터 10년 평균 PER</b>: <b>{fmt_num(per_upside['sector_10yr_per'], '.1f', '배')}</b> | <b>현재 PER</b>: <b>{fmt_num(per_upside['curr_per'], '.1f', '배')}</b></p>
        <p style='margin: 4px 0; font-size:0.9rem;'>- <b>상대적 밸류에이션 룸</b>: <b style='color:#30d158;'>{fmt_pct(per_upside['upside_room_pct'])}</b></p>
        <p style='margin: 4px 0; font-size:0.85rem; color:#ff9f0a;'>💡 <b>FOMO 방지 지수</b>: {per_upside['fomo_status']}</p>
    </div>
    """, unsafe_allow_html=True)

with q_col2:
    st.markdown(f"""
    <div style='background: #1c1c1e; border: 1px solid #bf5af2; border-radius: 14px; padding: 18px;'>
        <h4 style='color: #bf5af2 !important; margin-top:0;'>2. 백테스트 품질 평가 지표</h4>
        <p style='margin: 4px 0; font-size:0.9rem;'>- <b>표본내 Sharpe</b> (유사패턴 분포 기준): <b>{fmt_num(sharpe_turnover['sharpe_ratio'], spec='.2f')}</b>
           <span style='font-size:0.78rem; color:#86868b;'>— 표본외 Sharpe는 아래 Blind/OOS 섹션 참조</span></p>
        <p style='margin: 4px 0; font-size:0.9rem;'>- <b>연환산 회전율 (Turnover)</b>: <b>{fmt_num(sharpe_turnover['turnover_pct'], spec='.0f', suffix='%')}</b> (권장 보유 {fmt_num(sharpe_turnover['holding_days'], suffix='영업일')})</p>
        <p style='margin: 4px 0; font-size:0.85rem; color:#86868b;'>- <b>Profit Factor</b>: <b>{fmt_num(sharpe_turnover['real_profit_factor'], spec='.2f')}</b> | <b>비용 차감 수익</b>: {fmt_pct(sharpe_turnover['net_excess_return'], digits=2)}</p>
    </div>
    """, unsafe_allow_html=True)

with q_col3:
    st.markdown(f"""
    <div style='background: #1c1c1e; border: 1px solid #30d158; border-radius: 14px; padding: 18px;'>
        <h4 style='color: #30d158 !important; margin-top:0;'>3. 퀀터멘탈(Quantamental) 점수</h4>
        <h2 style='color: #30d158; margin: 4px 0; font-size: 1.8rem;'>{qm_score['hybrid_score']}점 <span style='font-size:0.9rem; color:#86868b;'>(하이브리드)</span></h2>
        <p style='margin: 4px 0; font-size:0.8rem; color:#d2d2d7;'><code>{qm_score['formula_str']}</code></p>
        <p style='margin: 4px 0; font-size:0.8rem; color:#86868b;'>ℹ️ 가격은 실제 일봉만 사용하며, 수신 실패 시 합성값으로 대체하지 않습니다. 과거 분기 재무 시계열은 미연동입니다.</p>
    </div>
    """, unsafe_allow_html=True)

_mix = " · ".join(f"{t['name']} {t['probability_pct']:.0f}%" for t in profile['type_mix'])
_applied = " · ".join(f"{m['model']} {m['weight_pct']:.0f}%" for m in profile['applied_models']) or "없음"
_excluded = ", ".join(profile['excluded_models']) or "없음"
st.markdown(f"""
<div style='background: #161618; border: 1px solid #2c2c2e; border-radius: 14px; padding: 18px; margin: 12px 0;'>
    <h4 style='color: #2997ff !important; margin-top:0;'>🏷️ 기업 프로필 (수치 기반 · 전 종목 공통 산출)</h4>
    <p style='margin:4px 0; font-size:0.95rem;'>- <b>기업유형 분류</b>: {profile['enterprise_class']} &nbsp;|&nbsp; <code>{_mix}</code></p>
    <p style='margin:4px 0; font-size:0.95rem;'>- <b>적용 평가모델</b>: {_applied}</p>
    <p style='margin:4px 0; font-size:0.95rem; color:#86868b;'>- <b>유효성 미통과 모델</b>: {_excluded}</p>
    <p style='margin:4px 0; font-size:0.95rem;'>- <b>20일 평균 거래대금</b>: {fmt_num((profile['metrics']['avg_turnover_20d'] or 0)/1e8, ',.0f', '억원', na='미산출')}
       &nbsp;|&nbsp; <b>유동성 점수</b>: {fmt_num(profile['metrics']['liquidity_score'], suffix='점')}
       &nbsp;|&nbsp; <b>미수신 입력</b>: {', '.join(profile['missing_inputs']) or '없음'}</p>
    <p style='margin:10px 0 0 0; font-size:0.82rem; color:#ff9f0a;'>ℹ️ {profile['qualitative_note']}</p>
</div>
""", unsafe_allow_html=True)

st.markdown("---")


# 탭마다 그 탭의 독립 판정을 맨 위에 띄운다. 종합 결론과 다르면 그 사실이 보여야 한다.
_TAB_VERDICT = {t['key']: t for t in verdict['tabs']}


def show_tab_verdict(key):
    t = _TAB_VERDICT.get(key)
    if not t:
        return
    score_txt = "—" if t['score'] is None else f"{t['score']}점"
    st.markdown(
        f"<div style='background:#1c1c1e;border-left:6px solid {t['color']};"
        f"border-radius:10px;padding:12px 16px;margin-bottom:12px;'>"
        f"<span style='font-size:1.5rem;font-weight:900;color:{t['color']};'>{t['verdict']}</span>"
        f"<span style='font-size:1.1rem;font-weight:800;color:#f5f5f7;margin-left:12px;'>{score_txt}</span>"
        f"<span style='color:#86868b;font-size:0.85rem;margin-left:10px;'>이 탭 단독 판정</span>"
        + "".join(f"<br><span style='color:#d2d2d7;font-size:0.88rem;'>· {r}</span>"
                  for r in t['reasons'])
        + "</div>", unsafe_allow_html=True)


# 🚨 [사용자 요청] 5대 핵심 분석 탭을 교차검증 상태표 위로 이동!
tab_pred, tab_val, tab_scen, tab_demark, tab_flow, tab_audit = st.tabs([
    "🔮 20일 자기유사 예측 (표본 통제)", 
    "💎 밸류에이션 & 2중 적정가 범위", 
    "🎯 조건별 3가지 대응 시나리오", 
    "⏱️ DeMARK 9-13 추세 소진 분석",
    "🌊 수급 & 기술적 차트 점검", 
    "🏛️ SR 11-7 무결성 감사 및 모델 성능"
])

# [Section 5 & 6 & 19] 자기유사 패턴 과거 백테스트 결과 (7대 적중률 극대화 파이프라인 가동)
with tab_pred:
    show_tab_verdict('pattern')
    st.subheader(f"🔮 [{resolved_name}] - 자기유사 예측 & 7대 적중률 극대화 엔진 파이프라인")
    
    # [19-10] 거래 회피(Abstain) 알림
    if sim_res.get('is_abstain'):
        st.warning(f"⚠️ **퀀트 리스크 관리 알림**: 현재 구간은 [{sim_res.get('abstain_reason')}] 조건이 감지되어 **`[예측 보류 / 거래 회피(Abstain)]`**를 권장합니다.")
    
    st.markdown(f"""
    <div style='background: #1c1c1e; border: 1px solid #30d158; border-radius: 16px; padding: 20px; margin-bottom: 20px;'>
        <h4 style='color: #30d158 !important; margin-top:0;'>🚀 자기유사 예측 파이프라인 — 실제 실행 단계</h4>
        <p style='font-size: 0.93rem; margin: 4px 0; line-height: 1.7;'>
            <b>① 시장 국면 판정</b>: <b style='color:#64d2ff;'>[{four_scores.get('market_regime_label', '판정 보류')}]</b> — 지수 일봉 120봉의 20/60일선 대비 실측<br>
            <b>② 패턴 정규화</b>: 최근 H봉 종가를 Z-Score 정규화 후 전 구간 스캔<br>
            <b>③ 유사도</b>: Pearson 상관 (임계 rho ≥ {sim_res.get('rho_cutoff_applied', rho_cutoff)}) + H≤40 구간은 DTW 결합 (0.7 / 0.3)<br>
            <b>④ 독립성 확보</b>: 매칭 간 최소 H영업일 간격 강제 (중복 이벤트 제거)<br>
            <b>⑤ 경로 확률</b>: 손절(-{TP_SL[1]:.0f}%) vs 목표(+{TP_SL[0]:.0f}%) 선도달 여부를 매칭별로 실제 경로 추적<br>
            <b>⑥ 베이지안 보정</b>: Beta-Binomial 사후평균 (사후확률: <b style='color:#30d158;'>{fmt_pct(sim_res.get('bayes_prob'), signed=False)}</b>) + 95% Wilson 구간<br>
            <b>⑦ 표본 통제</b>: 유효표본 {sim_res.get('match_count', 0)}건 · 등급 <b>{sim_res.get('sample_tier_label', '-')}</b> — 10건 미만이면 확률 미표시
        </p>
        <p style='font-size: 0.78rem; color:#86868b; margin: 8px 0 0 0;'>
            ※ 거래량·수급·RSI를 유사도에 반영하는 다중거리 모델과 다중 모델 앙상블은 구현되어 있지 않습니다.
            유사도는 Pearson 상관과 DTW만 사용합니다.
        </p>
    </div>
    """, unsafe_allow_html=True)

    if not sim_res.get('probabilities_shown', False):
        st.warning(f"⚠️ **[명세 §11 표본 통제]** 유효표본 {sim_res.get('match_count', 0)}건 — "
                   f"{sim_res.get('sample_tier_label', '')}. 이 구간에서는 확률을 산출·표시하지 않고 "
                   f"과거 관찰값만 제공합니다.")

    st.markdown(f"#### 🎯 경로 기반 확률 대시보드 (목표가 +{TP_SL[0]:.0f}% vs 손절가 -{TP_SL[1]:.0f}% 선도달)")
    tp_c1, tp_c2, tp_c3, tp_c4 = st.columns(4)
    with tp_c1:
        st.metric(f"🎯 목표가 (+{TP_SL[0]:.0f}%) 선도달 확률", fmt_pct(sim_res.get('tp_first_prob'), signed=False), "목표가 우선 도달")
    with tp_c2:
        st.metric(f"🛡️ 손절가 (-{TP_SL[1]:.0f}%) 선도달 확률", fmt_pct(sim_res.get('sl_first_prob'), signed=False), "위험 관리 구간")
    with tp_c3:
        st.metric("🔮 베이지안 사후 상승확률", fmt_pct(sim_res.get('bayes_prob'), signed=False), "Beta-Binomial")
    with tp_c4:
        # 구버전은 사후확률을 9등분해 '9개 앙상블 모델 중 N개 상승'으로 표시했다.
        # 실제 다중 모델 앙상블이 없으므로, 실제로 계산되는 지평 일치도로 대체한다.
        _hcs = sim_res.get('horizon_consistency_score')
        _scored = [H for H, hh in (sim_res.get('horizons_data') or {}).items()
                   if hh.get('win_rate') is not None]
        st.metric("🗓️ 기간 간 방향 일치도", fmt_num(_hcs, suffix='점'),
                  f"산출 가능 지평 {len(_scored)}개 기준")

    st.markdown("---")

    if not sim_res.get('probabilities_shown', False):
        st.info(f"📌 **예측 확률 미표시** — {sim_res.get('blind_reason', '표본 부족')}. "
                f"아래 '과거 관찰 성과'는 실제 관찰된 값이며 미래 확률로 해석하지 마십시오.")
    else:
        prob_val = sim_res.get('predicted_probability') or 50.0
        prob_color = "#30d158" if prob_val >= 60.0 else ("#64d2ff" if prob_val >= 50.0 else "#ff9f0a")

        st.markdown(f"""
        <div style='background: rgba(48, 209, 88, 0.10); border: 1.5px solid {prob_color}; border-radius: 12px; padding: 14px 18px; margin: 12px 0;'>
            <span style='font-size: 1.05rem; font-weight: bold; color: #f5f5f7;'>🎯 최종 예측 상승확률 (베이지안 사후보정): </span>
            <span style='font-size: 1.2rem; font-weight: 900; color: {prob_color}; margin-left: 6px;'>{sim_res['predicted_prob_str']}</span>
            <span style='font-size: 0.9rem; color: #a0a5b5; margin-left: 12px;'>(95% 신뢰구간: <code style="color:#64d2ff;">{sim_res['ci_str']}</code> | 분류: <b>{sim_res['confidence_grade']}</b>)</span>
        </div>
        """, unsafe_allow_html=True)
        
    # ── [명세 §10] 다중기간(5·10·20·40·60·120일) 독립 예측 결과 ──────────────
    st.markdown("#### 🗓️ 다중기간 독립 예측 (5 · 10 · 20 · 40 · 60 · 120 영업일)")
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
            st.dataframe(pd.DataFrame(hz_rows), use_container_width=True, hide_index=True)

        hc1, hc2, hc3 = st.columns(3)
        with hc1:
            st.metric("기간 간 방향 일치도",
                      fmt_num(sim_res.get('horizon_consistency_score'), suffix='점'),
                      "산출 가능한 지평 기준")
        with hc2:
            st.metric("최적 보유기간", sim_res.get('optimal_holding_period_str', '산출 불가'),
                      "mean×승률×일치도 / √H")
        with hc3:
            st.metric("적용 상관 임계값", f"rho ≥ {sim_res.get('rho_cutoff_applied', rho_cutoff)}",
                      "사용자 설정값 그대로 적용")

        # ── 미선정이면 '고장'이 아니라 '판정'임을 근거와 함께 보여준다 ─────────
        if not sim_res.get('optimal_holding_period_days'):
            _elig = sim_res.get('horizon_eligibility') or {}
            _near = sim_res.get('horizon_nearest_miss')
            _nosam = sim_res.get('horizons_without_sample') or []
            with st.expander("❓ 최적 보유기간이 왜 미선정인가 — 지평별 판정 근거", expanded=True):
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
                        use_container_width=True, hide_index=True)
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

    st.markdown("#### 📊 과거 관찰 성과 세부 분리 지표 (20일)")
    p1, p2, p3, p4, p5, p6 = st.columns(6)
    with p1:
        st.metric("유효 표본 수", f"{sim_res['match_count']} 건", sim_res['confidence_grade'])
    with p2:
        st.metric("평균 수익률", f"{sim_res['mean_perf']}%" if sim_res['mean_perf'] is not None else "N/A")
    with p3:
        st.metric("중앙값 수익률", f"{sim_res['median_perf']}%" if sim_res['median_perf'] is not None else "N/A")
    with p4:
        st.metric("최고 / 최저 수익률", f"{sim_res['max_perf']}% / {sim_res['min_perf']}%" if sim_res['max_perf'] is not None else "N/A")
    with p5:
        st.metric("평균 MDD (최대낙폭)", f"{sim_res['mdd']}%" if sim_res['mdd'] is not None else "N/A")
    with p6:
        st.metric("상승 / 하락 사례 수", f"{sim_res['win_count']}건 / {sim_res['loss_count']}건")

    # ── [명세 §10] 기간 선택형 경로 그래프 ─────────────────────────────────
    # 상·중·하 시나리오는 평균선의 평행이동이 아니라 시점별로 독립 계산한 분위수 경로다.
    st.markdown("#### 📈 기간별 경로 분포")

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
        fig_pred.patch.set_facecolor('#000000')
        ax_p.set_facecolor('#1c1c1e')

        # 불확실성 밴드 (10~90분위 / 25~75분위)
        ax_p.fill_between(days, h['traj_p10'], h['traj_p90'], color='#2997ff', alpha=0.10,
                          label="10~90분위 구간")
        ax_p.fill_between(days, h['traj_p25'], h['traj_p75'], color='#2997ff', alpha=0.20,
                          label="25~75분위 구간")

        # 군집 대표경로 (낙관·중립·비관) — 실제 경로들의 평균이라 모양이 서로 다르다
        cs = h.get('cluster_sizes') or {}
        ax_p.plot(days, h['path_bull'], color='#30d158', linewidth=2.0, linestyle='--',
                  label=f"낙관 군집 평균 (n={cs.get('bull', 0)})")
        ax_p.plot(days, h['trajectory'], color='#2997ff', linewidth=2.8,
                  label=f"중앙 경로 (median, n={h['match_count']})")
        ax_p.plot(days, h['path_bear'], color='#ff453a', linewidth=2.0, linestyle='--',
                  label=f"비관 군집 평균 (n={cs.get('bear', 0)})")
        ax_p.axhline(curr_price, color='#f5f5f7', linestyle='-', linewidth=1.2, label="현재가")
        # 기준선들 — 모두 참고용이며 경로 분포 계산에는 사용하지 않는다
        for _v, _c, _lb in (
                (four_scores.get('displayed_fair_value'), '#bf5af2', '펀더멘털 적정가'),
                (four_scores.get('buy_entry_max'), '#30d158', '권장 매수가 상단'),
                (four_scores.get('target_tech_1st'), '#64d2ff', '1차 목표가'),
                (four_scores.get('target_tech_2nd'), '#2997ff', '2차 목표가'),
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
            ax_p.axhline(_my, color='#ffd60a', linestyle='--', linewidth=1.8,
                         label=f"내 평균 매수가 ({_my:,.0f})")
            ax_p.fill_between(days, min(_my, curr_price), max(_my, curr_price),
                              color=('#30d158' if curr_price >= _my else '#ff453a'), alpha=0.07)

        title_kind = "예측" if show_forecast else "과거 유사사례 관찰"
        ax_p.set_title(
            f"[{resolved_name}] {sel_h}영업일 {title_kind} — 유효표본 {h['match_count']}건 · {h['tier_label']}",
            color='#f5f5f7', fontsize=13)
        ax_p.set_xlabel("미래 영업일 (Day)", color='#86868b')
        ax_p.set_ylabel(f"주가 ({unit_str})", color='#86868b')
        ax_p.tick_params(colors='#f5f5f7')
        ax_p.grid(True, color='#2c2c2e', linestyle='--')
        ax_p.legend(facecolor='#1c1c1e', edgecolor='#2c2c2e', labelcolor='#f5f5f7', fontsize=8)
        st.pyplot(fig_pred)

        if not show_forecast:
            st.warning(f"⚠️ 유효표본 {h['match_count']}건 — {h['tier_label']}. "
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
    st.subheader(f"💎 [{resolved_name}] - 시장조정 펀더멘털 적정가")
    
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
        st.success(f"✅ 적정가 신뢰도 {conf_score:.0f}점 — {fv_note}")
    elif fv_status == "CAUTION":
        st.warning(f"⚠️ 적정가 신뢰도 {conf_score:.0f}점 — {fv_note}")
    elif fv_status == "REFERENCE_ONLY":
        st.warning(f"⚠️ 적정가 신뢰도 {conf_score:.0f}점 — {fv_note}. 아래 예비 모델 범위만 참고하십시오.")
    else:
        st.error(f"🚨 적정가 신뢰도 {conf_score:.0f}점 — {fv_note}. 중심 적정가와 권장 매수가를 산출하지 않았습니다.")

    disp_price_str = f"{disp_price:,.0f}{unit_str}" if disp_price is not None else "산출 보류"
    if upside_pct is None:
        upside_display_str = f"<b style='color:#86868b;'>상승여력 미산출</b> ({upside_eval})"
    else:
        upside_color = "#30d158" if upside_pct > 0 else "#ff453a"
        upside_display_str = f"현재가 대비 <b style='color:{upside_color};'>{upside_pct:+.1f}%</b> ({upside_eval})"

    if rec_buy is None:
        rec_buy_str = "미산출 (신뢰도 미달)"
        entry_eval_str = "판정 불가"
        entry_eval_color = "#86868b"
    else:
        rec_buy_str = f"{rec_buy:,.0f}{unit_str} 이하"
        entry_eval_str = "안전 매수 구간" if realtime_price <= rec_buy else "안전마진 상단 초과 (눌림 대기)"
        entry_eval_color = "#30d158" if realtime_price <= rec_buy else "#ff9f0a"

    st.markdown(f'''
    <div style="background: #1c1c1e; border: 2px solid #bf5af2; border-radius: 18px; padding: 22px; margin-bottom: 20px;">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap;">
            <div>
                <h3 style="margin-top:0; color:#bf5af2;">💎 시장조정 펀더멘털 적정가 (캘리브레이션 연동)</h3>
                <p style="font-size: 2.3rem; font-weight: bold; margin: 5px 0; color: #f5f5f7;">{disp_price_str}</p>
                <p style="font-size: 1.15rem; font-weight: bold; margin: 0; color: #d2d2d7;">{upside_display_str}</p>
                <p style="font-size: 0.9rem; color: #86868b; margin-top: 6px;">
                    참고 중심값 <b style="color:#f5f5f7;">{fmt_num(val_eval.get('reference_fair_value'), suffix=unit_str)}</b><br>
                    핵심 합리적 범위 (25~75분위) <b style="color:#64d2ff;">{val_eval.get('fair_value_range_core_str', '미산출')}</b><br>
                    확장 불확실성 범위 (10~90분위) <b style="color:#86868b;">{val_eval.get('fair_value_range_wide_str', '미산출')}</b>
                </p>
            </div>
            <div style="text-align: right; background: #2c2c2e; padding: 14px 20px; border-radius: 12px; border: 1px solid #3a3a3c;">
                <p style="margin: 0; font-size: 0.85rem; color: #86868b;">기초 펀더멘털 가치</p>
                <p style="margin: 3px 0 8px 0; font-size: 1.1rem; font-weight: bold; color: #f5f5f7;">{base_fair_val:,.0f}{unit_str}</p>
                <p style="margin: 0; font-size: 0.85rem; color: #86868b;">시장조정 영향: <b style="color:#ff9f0a;">{mkt_adj_pct:+.1f}%</b></p>
                <p style="margin: 3px 0 0 0; font-size: 0.85rem; color: #86868b;">적정가 신뢰도: <b style="color:#64d2ff;">{conf_score:.0f} / 100점</b></p>
            </div>
        </div>
        <hr style="border-color: #3a3a3c; margin: 15px 0;">
        <div style="display: flex; justify-content: space-around; text-align: center; flex-wrap: wrap;">
            <div style="margin: 5px 10px;">
                <span style="font-size: 0.85rem; color: #86868b;">권장 매수가 (안전마진 {mos_pct:.0f}% 적용)</span><br>
                <b style="font-size: 1.15rem; color: #30d158;">{rec_buy_str}</b>
            </div>
            <div style="margin: 5px 10px;">
                <span style="font-size: 0.85rem; color: #86868b;">핵심 평가 모델</span><br>
                <b style="font-size: 1.0rem; color: #f5f5f7;">기업특성 기반 선택적 다중 모델</b>
            </div>
            <div style="margin: 5px 10px;">
                <span style="font-size: 0.85rem; color: #86868b;">현재 진입 평가</span><br>
                <b style="font-size: 1.0rem; color: {entry_eval_color};">
                    {entry_eval_str}
                </b>
            </div>
        </div>
    </div>
    ''', unsafe_allow_html=True)
        
    with st.expander("🔍 [적정가 산출 근거 & 기업유형별 평가모델 내역 펼쳐보기]", expanded=True):
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
    st.subheader(f"🎯 [{resolved_name}] - 조건별 20일 대응 시나리오 대시보드")
    
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
                <td><b style='color:#30d158;'>🟢 상승 시나리오</b></td>
                <td>20일선 복귀(`{curr_price*(1 + atr_val*0.5):,.0f}{unit_str}`) + 거래량 1.2배 + 외인 전환</td>
                <td><b>{bull_range_low:,.0f}{unit_str} ~ {bull_range_high:,.0f}{unit_str}</b></td>
                <td>{bull_target*0.95:,.0f}{unit_str} / {bull_target:,.0f}{unit_str}</td>
                <td>{bull_stop:,.0f}{unit_str} 하회 시 무효화</td>
                <td>1차 분할 매수 검토</td>
            </tr>
            <tr>
                <td><b style='color:#ff9f0a;'>🟡 횡보 시나리오</b></td>
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
    
    st.markdown("---")
    # [Section 1-6 Spec] 목표가격 5종 세트 산출 근거 표
    st.markdown("#### 🎯 목표가격 및 손절·위험선 산출 근거 명시적 표")
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
                <td><b style='color:#bf5af2;'>{fmt_num(four_scores.get('displayed_fair_value'), suffix='원', na='미산출 (신뢰도 미달)')}</b></td>
                <td>{four_scores['target_fundamental_note']}</td>
            </tr>
            <tr>
                <td><b>2. 권장 매수가 (안전마진 적용)</b></td>
                <td><b style='color:#30d158;'>{f"{four_scores['recommended_buy_price']:,.0f}원 이하" if four_scores.get('recommended_buy_price') is not None else "적정가 신뢰도 미달 (미산출)"}</b></td>
                <td>안전마진 {four_scores.get('margin_of_safety_pct', 15):.0f}% 적용 실제 진입 가격</td>
            </tr>
            <tr>
                <td><b>3. 기술적 1차 목표가</b></td>
                <td><b style='color:#64d2ff;'>{fmt_num(four_scores.get('target_tech_1st'), ',.0f', '원', na='산출 불가')}</b></td>
                <td>{four_scores.get('target_tech_1st_note', '')}</td>
            </tr>
            <tr>
                <td><b>4. 기술적 2차 목표가</b></td>
                <td><b style='color:#2997ff;'>{fmt_num(four_scores.get('target_tech_2nd'), ',.0f', '원', na='산출 불가')}</b></td>
                <td>{four_scores.get('target_tech_2nd_note', '')}</td>
            </tr>
            <tr>
                <td><b>5. 손절가 (Stop-Loss)</b></td>
                <td><b style='color:#ff453a;'>{fmt_num(four_scores.get('stop_loss_price'), ',.0f', '원', na='산출 불가')}</b></td>
                <td>{four_scores.get('stop_loss_note', '')}</td>
            </tr>
            <tr>
                <td><b>6. ATR / DeMARK 구조적 위험선</b></td>
                <td><b style='color:#ff9f0a;'>{fmt_num(four_scores.get('atr_risk_level'), ',.0f', '원', na='산출 불가')}</b></td>
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
    <div style="background-color:#1c1c1e; padding:20px; border-radius:12px; border:1px solid #2c2c2e; margin-bottom:20px;">
        <h3 style="color:#f5f5f7; margin-top:0;">⏱️ DeMARK 9-13 결합신호 종합 대시보드</h3>
        <div style="display:flex; justify-content:space-between; flex-wrap:wrap; color:#e5e5ea; font-size:1.0rem; line-height:1.6;">
            <div style="flex:1; min-width:250px;">
                <b style="color:#bf5af2;">[DeMARK 카운트]</b><br>
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
                <b style="color:#ff9f0a;">[최종 판정 점수]</b><br>
                Bullish 점수: {dm.get('bullish_score', 50)} / 100점<br>
                Bearish 점수: {dm.get('bearish_score', 50)} / 100점<br><br>
                <b style="color:#30d158; font-size:1.1rem;">최종 판정: {dm.get('demark_label', '중립')}</b><br>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown(f"#### 📈 [{resolved_name}] DeMARK 9-13 & 다중 지표 정밀 차트")
    
    recent_dm_df = tech_df.tail(100).copy().reset_index(drop=True)
    dates = pd.to_datetime(recent_dm_df['trade_date'])
    
    # GridSpec Figure
    fig_dm = plt.figure(figsize=(14, 12))
    fig_dm.patch.set_facecolor('#000000')
    gs = fig_dm.add_gridspec(4, 1, height_ratios=[5, 1.5, 1.5, 1.5], hspace=0.15)
    
    ax_main = fig_dm.add_subplot(gs[0, 0])
    ax_vol = fig_dm.add_subplot(gs[1, 0], sharex=ax_main)
    ax_wr = fig_dm.add_subplot(gs[2, 0], sharex=ax_main)
    ax_rsi = fig_dm.add_subplot(gs[3, 0], sharex=ax_main)
    
    for ax in [ax_main, ax_vol, ax_wr, ax_rsi]:
        ax.set_facecolor('#1c1c1e')
        ax.tick_params(colors='#f5f5f7')
        ax.grid(True, color='#2c2c2e', linestyle='--')
        
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
    if 'sma_5' in recent_dm_df: ax_main.plot(dates, recent_dm_df['sma_5'], color='#ff9f0a', linewidth=1, label='MA 5')
    if 'sma_20' in recent_dm_df: ax_main.plot(dates, recent_dm_df['sma_20'], color='#32ade6', linewidth=1.5, label='MA 20')
    if 'sma_60' in recent_dm_df: ax_main.plot(dates, recent_dm_df['sma_60'], color='#30d158', linewidth=1.5, label='MA 60')
    
    if 'bb_upper' in recent_dm_df: 
        ax_main.plot(dates, recent_dm_df['bb_upper'], color='#bf5af2', linestyle=':', linewidth=1.5, label='BB Upper')
        ax_main.plot(dates, recent_dm_df['bb_lower'], color='#bf5af2', linestyle=':', linewidth=1.5, label='BB Lower')
        ax_main.fill_between(dates, recent_dm_df['bb_lower'], recent_dm_df['bb_upper'], color='#bf5af2', alpha=0.05)
        
    # TDST
    res_val = dm.get('tdst_resistance')
    sup_val = dm.get('tdst_support')
    if res_val: ax_main.axhline(res_val, color='#ff9f0a', linestyle='--', linewidth=1.5, alpha=0.8, label=f'TDST Res ({res_val:,.0f})')
    if sup_val: ax_main.axhline(sup_val, color='#30d158', linestyle='--', linewidth=1.5, alpha=0.8, label=f'TDST Sup ({sup_val:,.0f})')
    
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
            ax_main.text(dates[i], lows[i] - p_range*0.8, str(b_cnt), color='#30d158', fontsize=9, ha='center', va='top', fontweight='bold')
            if b_cnt == 9:
                ax_main.scatter(dates[i], lows[i] - p_range*1.6, color='#30d158', marker='^', s=160, zorder=5)
                ax_main.annotate('⚡매수준비(9)', xy=(dates[i], lows[i] - p_range*2.8), color='#30d158', fontsize=10, ha='center', va='top', fontweight='bold', backgroundcolor='#1c1c1e')
                
        if s_cnt > 0:
            ax_main.text(dates[i], highs[i] + p_range*0.8, str(s_cnt), color='#ff453a', fontsize=9, ha='center', va='bottom', fontweight='bold')
            if s_cnt == 9:
                ax_main.scatter(dates[i], highs[i] + p_range*1.6, color='#ff453a', marker='v', s=160, zorder=5)
                ax_main.annotate('⚡매도경계(9)', xy=(dates[i], highs[i] + p_range*2.8), color='#ff453a', fontsize=10, ha='center', va='bottom', fontweight='bold', backgroundcolor='#1c1c1e')
        
        # Countdown 13 Markers (High Priority)
        if b_c_cnt >= 13:
            ax_main.scatter(dates[i], lows[i] - p_range*2.0, color='#30d158', marker='D', s=200, zorder=8)
            ax_main.annotate('🔥Countdown 13 확정 매수타이밍', xy=(dates[i], lows[i] - p_range*3.8), color='#30d158', fontsize=11, ha='center', va='top', fontweight='bold', backgroundcolor='#1c1c1e')
        elif s_c_cnt >= 13:
            ax_main.scatter(dates[i], highs[i] + p_range*2.0, color='#ff453a', marker='D', s=200, zorder=8)
            ax_main.annotate('🔥Countdown 13 확정 매도타이밍', xy=(dates[i], highs[i] + p_range*3.8), color='#ff453a', fontsize=11, ha='center', va='bottom', fontweight='bold', backgroundcolor='#1c1c1e')

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
                 verticalalignment='top', color='#f5f5f7',
                 bbox=dict(boxstyle='round,pad=0.4', facecolor='#1c1c1e', alpha=0.8, edgecolor='#3a3a3c', lw=1),
                 zorder=12)

    ax_main.set_ylabel('Price', color='#86868b')
    ax_main.legend(loc='upper right', facecolor='#1c1c1e', edgecolor='#2c2c2e', labelcolor='#f5f5f7', fontsize=8)
    
    # 2. Volume
    vols = recent_dm_df['volume'].values
    vols_ma = recent_dm_df['vol_20_avg'].values if 'vol_20_avg' in recent_dm_df else None
    
    ax_vol.bar(dates[up], vols[up], color='#ff453a', alpha=0.7)
    ax_vol.bar(dates[down], vols[down], color='#0a84ff', alpha=0.7)
    if vols_ma is not None:
        ax_vol.plot(dates, vols_ma, color='#f5f5f7', linewidth=1.5, label='Vol MA20')
    ax_vol.set_ylabel('Volume', color='#86868b')
    ax_vol.legend(loc='upper left', facecolor='#1c1c1e', edgecolor='#2c2c2e', labelcolor='#f5f5f7', fontsize=8)
    
    # 3. Williams %R
    if 'williams_r' in recent_dm_df:
        wr = recent_dm_df['williams_r'].values
        ax_wr.plot(dates, wr, color='#32ade6', linewidth=1.5)
        ax_wr.axhline(-20, color='#ff453a', linestyle=':')
        ax_wr.axhline(-80, color='#30d158', linestyle=':')
        ax_wr.fill_between(dates, 0, -20, color='#ff453a', alpha=0.1)
        ax_wr.fill_between(dates, -80, -100, color='#30d158', alpha=0.1)
        ax_wr.set_ylim(-100, 0)
    ax_wr.set_ylabel('Williams %R', color='#86868b')
    
    # 4. RSI
    if 'rsi_14' in recent_dm_df:
        rsi = recent_dm_df['rsi_14'].values
        ax_rsi.plot(dates, rsi, color='#bf5af2', linewidth=1.5)
        ax_rsi.axhline(70, color='#ff453a', linestyle=':')
        ax_rsi.axhline(50, color='#f5f5f7', linestyle='--', alpha=0.3)
        ax_rsi.axhline(30, color='#30d158', linestyle=':')
        ax_rsi.fill_between(dates, 70, 100, color='#ff453a', alpha=0.1)
        ax_rsi.fill_between(dates, 0, 30, color='#30d158', alpha=0.1)
        ax_rsi.set_ylim(0, 100)
    ax_rsi.set_ylabel('RSI 14', color='#86868b')
    
    plt.tight_layout()
    st.pyplot(fig_dm)

with tab_flow:
    show_tab_verdict('technical')
    st.subheader(f"🌊 [{resolved_name}] - 기술적 캔들/이동평균선 & 수급 차트 점검")
    
    is_settled, settled_msg = q_engine.check_20sma_settlement(tech_df)
    st.info(f"📌 **20일선 안착 정량 규칙 검증**: {settled_msg}")
    
    recent_tech = tech_df.tail(90)
    x_dates = pd.to_datetime(recent_tech['trade_date'])
    
    # 📈 [1] 3-Subplot 프리미엄 기술적 주가 콤보 차트 (가격/이동평균선, RSI, 거래량)
    fig_tech, (ax_price, ax_rsi, ax_vol) = plt.subplots(3, 1, figsize=(12, 9), sharex=True, gridspec_kw={'height_ratios': [3, 1, 1]})
    fig_tech.patch.set_facecolor('#000000')
    
    for ax in (ax_price, ax_rsi, ax_vol):
        ax.set_facecolor('#1c1c1e')
        ax.tick_params(colors='#f5f5f7')
        ax.grid(True, color='#2c2c2e', linestyle='--')
        
    # (1) 주가 및 5·20·60·120일 이동평균선
    ax_price.plot(x_dates, recent_tech['adj_close'], label=f"{resolved_name} 수정종가", color='#f5f5f7', linewidth=2.5)
    ax_price.plot(x_dates, recent_tech['sma_5'], label="5일선 (단기)", color='#64d2ff', linestyle='-', linewidth=1.5)
    ax_price.plot(x_dates, recent_tech['sma_20'], label="20일선 (중기)", color='#ff9f0a', linestyle='-', linewidth=2.0)
    ax_price.plot(x_dates, recent_tech['sma_60'], label="60일선 (수급선)", color='#bf5af2', linestyle='--', linewidth=1.5)
    ax_price.plot(x_dates, recent_tech['sma_120'], label="120일선 (장기)", color='#ff3b30', linestyle=':', linewidth=1.5)
    
    ax_price.set_title(f"📈 [{resolved_name}] 이동평균선(5·20·60·120일) & 기술적 분석 차트", color='#f5f5f7', fontsize=13, fontweight='bold')
    ax_price.set_ylabel(f"주가 ({unit_str})", color='#86868b')
    ax_price.legend(facecolor='#1c1c1e', edgecolor='#2c2c2e', labelcolor='#f5f5f7', loc='upper left')
    
    # (2) RSI 14 모멘텀 지표
    ax_rsi.plot(x_dates, recent_tech['rsi_14'], label="RSI 14", color='#bf5af2', linewidth=1.8)
    ax_rsi.axhline(70, color='#ff453a', linestyle='--', alpha=0.7, label="과매수(70)")
    ax_rsi.axhline(30, color='#30d158', linestyle='--', alpha=0.7, label="과매도(30)")
    ax_rsi.set_ylabel("RSI (14)", color='#86868b')
    ax_rsi.set_ylim(10, 90)
    ax_rsi.legend(facecolor='#1c1c1e', edgecolor='#2c2c2e', labelcolor='#f5f5f7', loc='upper left')
    
    # (3) 거래량 차트 & 20일 평균선
    ax_vol.bar(x_dates, recent_tech['volume'], color='#2997ff', alpha=0.7, label="거래량")
    ax_vol.plot(x_dates, recent_tech['vol_20_avg'], color='#ff9f0a', linewidth=1.5, label="20일 평균 거래량")
    ax_vol.set_ylabel("거래량 (주)", color='#86868b')
    ax_vol.set_xlabel("거래일자", color='#86868b')
    ax_vol.legend(facecolor='#1c1c1e', edgecolor='#2c2c2e', labelcolor='#f5f5f7', loc='upper left')
    
    plt.tight_layout()
    st.pyplot(fig_tech)
    
    st.markdown("---")
    st.markdown("#### 🌊 최근 60영업일 3대 주체 (외국인 · 기관 · 개인) 누적 순매수 동향")

    recent_flow = tech_df.tail(60)
    flow_cols = ['foreign_cum_5d', 'institution_cum_5d', 'retail_cum_5d']
    flow_available = all(c in recent_flow.columns for c in flow_cols) and \
        not recent_flow[flow_cols].isna().all().all()

    if not flow_available:
        # 구버전은 sin/cos 파형 + 정규난수로 만든 곡선을 실제 수급인 것처럼 그렸다.
        st.info("📌 **투자자별 수급 데이터 미연동** — 외국인·기관·개인 순매매 시계열은 현재 연결되어 있지 않습니다. "
                "임의 생성한 곡선을 표시하지 않기 위해 차트를 비워 둡니다. "
                "(이 항목은 DeMARK 수급 확인 가점에서도 제외되어 점수에 반영되지 않습니다.)")
    else:
        fig_flow, ax_f = plt.subplots(figsize=(12, 4.5))
        fig_flow.patch.set_facecolor('#000000')
        ax_f.set_facecolor('#1c1c1e')
        x_flow_dates = pd.to_datetime(recent_flow['trade_date'])
        ax_f.plot(x_flow_dates, recent_flow['foreign_cum_5d']/1e8, label="외국인 5일 누적 (억원)", color='#30d158', linewidth=2)
        ax_f.plot(x_flow_dates, recent_flow['institution_cum_5d']/1e8, label="기관 5일 누적 (억원)", color='#2997ff', linewidth=2)
        ax_f.plot(x_flow_dates, recent_flow['retail_cum_5d']/1e8, label="개인 5일 누적 (억원)", color='#ff453a', linestyle=':', linewidth=1.5)
        ax_f.axhline(0, color='#f5f5f7', linestyle='--', alpha=0.5)
        ax_f.set_title(f"[{resolved_name}] 3대 주체 순매수 수급 차트", color='#f5f5f7', fontsize=12)
        ax_f.tick_params(colors='#f5f5f7')
        ax_f.grid(True, color='#2c2c2e', linestyle='--')
        ax_f.legend(facecolor='#1c1c1e', edgecolor='#2c2c2e', labelcolor='#f5f5f7')
        st.pyplot(fig_flow)

# [Section 7, 12, 13] SR 11-7 무결성 감사 및 모델 성능 검증 대시보드
with tab_audit:
    show_tab_verdict('integrity')
    st.subheader(f"🏛️ [{resolved_name}] - SR 11-7 무결성 감사 및 모델 성능 대시보드")
    
    is_large_cap = (val_eval.get("enterprise_class") in ["대형 우량 기술주 (Large Quality)", "대형 경기민감 제조기업 (Automotive / Cyclical Mfg)"] or curr_price > 100000.0)
    cost_metrics = q_engine.calculate_backtest_costs_and_metrics(
        sim_res, oos=snap.get('oos_result'), is_large_cap=is_large_cap)

    # ── [명세 §14] 표본외(Blind/OOS) 검증 결과 ────────────────────────────
    _oos = snap.get('oos_result') or {}
    _sq = snap.get('strategy_quality') or {}
    st.markdown("#### 🧪 표본외(Blind / Out-of-Sample) Walk-Forward 검증")
    if not _oos.get('available'):
        st.warning(f"⚠️ 표본외 검증 미수행 — {_oos.get('reason', '사유 미상')}. "
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
                use_container_width=True, hide_index=True)
    st.markdown("---")
    
    c1, c2 = st.columns(2)
    with c1:
        # ⚠️ 표본이 부족하면 mean_perf 가 None 이다. 여기에 :.1f 를 직접 쓰면
        #    화면 전체가 TypeError 로 죽는다 (실제로 클라우드에서 발생).
        #    부호도 하드코딩하면 안 된다 — 손실인데 '+' 가 붙는다.
        _raw_perf = cost_metrics.get('raw_perf')
        _net_perf = cost_metrics.get('net_perf')
        _net_color = "#30d158" if (_net_perf or 0) >= 0 else "#ff453a"
        st.markdown(f"""
        <div style='background: #1c1c1e; border: 1px solid #2c2c2e; border-radius: 16px; padding: 20px;'>
            <h4 style='color: #2997ff !important; margin-top:0;'>📊 백테스트 거래비용 차감 후 모델 성과 (Section 7 & 12)</h4>
            <p>- <b>비용 반영 전 수익률</b>: <b>{fmt_pct(_raw_perf)}</b></p>
            <p>- <b>총 거래비용 (수수료+세금+슬리피지)</b>: <b>-{fmt_num(cost_metrics.get('total_cost_pct'), '.3f', '%')}</b></p>
            <p>- <b>비용 반영 후 실질 수익률</b>: <span style='color:{_net_color};'><b>{fmt_pct(_net_perf)}</b></span></p>
            <hr style='border-color:#2c2c2e;'>
            <p>- <b>20일 관찰 승률</b>: <b>{fmt_pct(cost_metrics['win_rate_20d'], signed=False)}</b> | <b>Profit Factor</b>: <b>{fmt_num(cost_metrics['profit_factor'], spec='.2f')}</b></p>
            <p>- <b>Brier Score</b>: <b>{fmt_num(cost_metrics['brier_score'], spec='.3f')}</b> | <b>MAE</b>: <b>{fmt_pct(cost_metrics['mae_pct'], signed=False)}</b></p>
            <p style='color:#86868b; font-size:0.8rem;'>표본 등급: {cost_metrics['sample_note']}</p>
            <p style='color:#ff9f0a; font-size:0.85rem;'>⚠️ {cost_metrics['calibration_status']}</p>
        </div>
        """, unsafe_allow_html=True)
        
    with c2:
        st.markdown(f"""
        <div style='background: #1c1c1e; border: 1px solid #2c2c2e; border-radius: 16px; padding: 20px;'>
            <h4 style='color: #30d158 !important; margin-top:0;'>🛡️ SR 11-7 모델 리스크 관리 감사 카드 (Section 13)</h4>
            <p>- <b>기준시점 ($t_{{ref}}$)</b>: <b>{snapshot.get('t_ref') if snapshot else '2026-07-30'}</b></p>
            <p>- <b>미래 데이터 차단 건수</b>: <b>{snapshot.get('blocked_future_count') if snapshot else 0} 건 (PTA 통제 완료)</b></p>
            <p>- <b>Shapley-DCLR 미래 누수율</b>: <b style='color:#ff9f0a;'>{snapshot.get('shapley_dclr_status') if snapshot else '미산출'}</b></p>
            <p>- <b>중복 유사 패턴 제거</b>: <b>적용 (지평별 최소 H영업일 이격)</b></p>
            <p>- <b>SR 11-7 무결성 루브릭</b>: <b style='color:{"#30d158" if sr117_audit.get("is_passed") else "#ff9f0a"};'>{sr117_audit.get('total_score', 0)}/100점 ({'통과' if sr117_audit.get('is_passed') else '미달'})</b>
               <span style='font-size:0.8rem; color:#86868b;'>— 이중시점 {sr117_audit.get('bitemporal_score',0)} / 연산 {sr117_audit.get('math_score',0)} / 일관성 {sr117_audit.get('consistency_score',0)} / 통계 {sr117_audit.get('stat_score',0)} / 가드레일 {sr117_audit.get('guardrail_score',0)}</span></p>
            <p>- <b>금지 표현 자동 교정</b>: <b>{guard_res.get('violations_found', 0)}건</b></p>
            <p>- <b>규칙집 버전</b>: <code>{quant_indicators.QuantIndicatorsEngine.RULEBOOK_VERSION}</code> | <b>Run ID</b>: <code>{run_id}</code></p>
        </div>
        """, unsafe_allow_html=True)
        
    st.markdown("---")
    
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

    st.markdown("#### 📊 전략 유효성 벤치마크 대조 & 팩터 귀속 분해 대시보드")
    ba1, ba2 = st.columns(2)

    with ba1:
        st.markdown(f"""
        <div style='background: #1c1c1e; border: 1px solid #00f0ff; border-radius: 14px; padding: 18px;'>
            <h4 style='color: #00f0ff !important; margin-top:0;'>📊 전략 유효성 벤치마크 직접 대조 (Section 20-3)</h4>
            <p>- <b>패턴 조건부 전략 (20일)</b>: <b style='color:#30d158;'>{fmt_pct(bench_data['ai_perf'], digits=2)}</b></p>
            <p>- <b>동일 종목 무조건 보유</b>: <b>{fmt_pct(bench_data['buy_hold_perf'], digits=2)}</b></p>
            <p>- <b>20일선 위에서만 보유</b>: <b>{fmt_pct(bench_data['trend20d_perf'], digits=2)}</b></p>
            <p>- <b>KOSPI200 지수</b>: <b>{fmt_pct(bench_data['kospi200_perf'], digits=2)}</b>
               <span style='color:#86868b;font-size:0.8rem;'>({bench_data['kospi200_note']})</span></p>
            <hr style='border-color:#2c2c2e; margin:8px 0;'>
            <p style='font-size:0.85rem; color:#ff9f0a; margin:0;'>💡 <b>판정</b>: {bench_data['judge_text']}</p>
        </div>
        """, unsafe_allow_html=True)

    with ba2:
        if factor_data.get('available'):
            _alpha_col = "#30d158" if (factor_data['alpha_annual_pct'] or 0) >= 0 else "#ff453a"
            st.markdown(f"""
            <div style='background: #1c1c1e; border: 1px solid #bf5af2; border-radius: 14px; padding: 18px;'>
                <h4 style='color: #bf5af2 !important; margin-top:0;'>📐 수익률 팩터 귀속 분해 (Section 20-7)</h4>
                <p style='font-size:0.85rem; color:#86868b; margin-top:0;'>{factor_data['model']} · {factor_data['n_days']}일</p>
                <p>- <b>시장 베타 (β)</b>: <b>{factor_data['beta']:.3f}</b>
                   · 설명력 R² <b>{factor_data['r_squared']:.3f}</b></p>
                <p>- <b>시장 설명분</b>: <b>{fmt_pct(factor_data['market_contribution_pct'], digits=1)}</b></p>
                <p>- <b>알파 (잔차)</b>: <b style='color:{_alpha_col};'>{fmt_pct(factor_data['alpha_contribution_pct'], digits=1)}</b>
                   · 연환산 <b style='color:{_alpha_col};'>{fmt_pct(factor_data['alpha_annual_pct'], digits=2)}</b></p>
                <p>- <b>실현 총수익률</b>: <b>{fmt_pct(factor_data['realized_total_pct'], digits=1)}</b></p>
                <hr style='border-color:#2c2c2e; margin:8px 0;'>
                <p style='font-size:0.8rem; color:#ff9f0a; margin:0;'>⚠️ 미연동 팩터: {', '.join(factor_data['missing_factors'])} — {factor_data['missing_reason']}</p>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div style='background: #1c1c1e; border: 1px solid #3a3a3c; border-radius: 14px; padding: 18px;'>
                <h4 style='color: #86868b !important; margin-top:0;'>📐 수익률 팩터 귀속 분해 (Section 20-7)</h4>
                <p style='color:#86868b;'><b>미산출</b></p>
                <p style='font-size:0.85rem; color:#86868b;'>사유: {factor_data['reason']}</p>
                <p style='font-size:0.85rem; color:#86868b;'>관찰 총수익률만 제공: <b>{fmt_pct(factor_data['total_perf'], digits=2)}</b></p>
            </div>
            """, unsafe_allow_html=True)

    if risk_budget.get('available'):
        _cash = risk_budget['recommended_cash_pct']
        _ccol = "#ff453a" if _cash >= 40 else ("#ff9f0a" if _cash >= 25 else "#30d158")
        _hrows = "".join(
            f"<tr><td style='padding:4px 10px;'>{h['name']}</td>"
            f"<td style='padding:4px 10px;text-align:right;'>{h['weight_pct']:.1f}%</td>"
            f"<td style='padding:4px 10px;text-align:right;'>{h['vol_annual_pct']:.1f}%</td>"
            f"<td style='padding:4px 10px;text-align:right;'>{fmt_pct(h['risk_share_pct'], digits=1)}</td></tr>"
            for h in risk_budget['holdings'])
        st.markdown(f"""
        <div style='background: #161618; border: 1px solid {_ccol}; border-radius: 14px; padding: 16px; margin-top: 12px;'>
            <h4 style='color: #f5f5f7 !important; margin-top:0;'>⚖️ 포트폴리오 위험예산 & 현금 비중 가이드 (Section 20-14 &amp; 20-15)</h4>
            <p style='font-size:0.85rem;color:#86868b;margin-top:0;'>보유 {risk_budget['n_holdings']}종목 · 최근 {risk_budget['window_days']}거래일 · 평가금액 {risk_budget['total_value']:,.0f}원</p>
            <table style='width:100%; font-size:0.88rem; color:#d2d2d7; border-collapse:collapse;'>
                <tr style='color:#64d2ff;'><th style='text-align:left;padding:4px 10px;'>종목</th>
                    <th style='text-align:right;padding:4px 10px;'>비중</th>
                    <th style='text-align:right;padding:4px 10px;'>연변동성</th>
                    <th style='text-align:right;padding:4px 10px;'>위험기여</th></tr>
                {_hrows}
            </table>
            <hr style='border-color:#2c2c2e; margin:10px 0;'>
            <p style='margin:2px 0;'>- 집중도 HHI <b>{risk_budget['hhi']:.3f}</b> (유효 종목수 <b>{risk_budget['effective_n']:.1f}개</b>)</p>
            <p style='margin:2px 0;'>- 종목 간 평균 상관 <b>{fmt_num(risk_budget['avg_correlation'], '.2f')}</b> · 최대 <b>{fmt_num(risk_budget['max_correlation'], '.2f')}</b></p>
            <p style='margin:2px 0;'>- 포트폴리오 연환산 변동성 <b>{risk_budget['portfolio_vol_annual_pct']:.1f}%</b>
               (개별 가중평균 {risk_budget['weighted_indiv_vol_pct']:.1f}% → 분산효과 <b>{risk_budget['diversification_benefit_pct']:.1f}%</b>)</p>
            <p style='margin:2px 0;'>- 과거 최대낙폭 <b style='color:#ff453a;'>{risk_budget['historical_mdd_pct']:.1f}%</b></p>
            <p style='margin:8px 0 2px;'>- <b>권장 현금 비중</b>: <b style='color:{_ccol}; font-size:1.1rem;'>{_cash:.0f}%</b></p>
            <p style='font-size:0.82rem; color:#86868b; margin:2px 0;'>사유: {' · '.join(risk_budget['cash_reasons'])}</p>
            <p style='font-size:0.78rem; color:#86868b; margin-top:8px;'>ℹ️ {risk_budget['note']}</p>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div style='background: #161618; border: 1px solid #2c2c2e; border-radius: 14px; padding: 16px; margin-top: 12px;'>
            <h4 style='color: #86868b !important; margin-top:0;'>⚖️ 포트폴리오 위험예산 & 현금 비중 가이드 (Section 20-14 &amp; 20-15)</h4>
            <p style='margin: 4px 0; font-size:0.9rem; color:#86868b;'><b>미산출</b> — {risk_budget['reason']}</p>
            <p style='margin: 4px 0; font-size:0.85rem; color:#64d2ff;'>보유종목을 등록하면 비중·집중도·상관·변동성·권장 현금비중이 실제 일봉으로 계산됩니다.</p>
        </div>
        """, unsafe_allow_html=True)
    
    # ── 배당 · 배당락 분석 ────────────────────────────────────────────────
    st.markdown("#### 💰 배당 & 배당락 분석")
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
                _verdict, _vcol = ("배당 + 퀀트 조건 동시 충족 — 분할 진입 검토 가능", "#30d158")
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
                                   "#ff9f0a")
        else:
            _verdict, _vcol = (f"배당락까지 {_dte}일 — 아직 배당 전략 구간이 아닙니다 "
                               f"(30일 이내부터 판정)", "#86868b")

        st.markdown(f"""
        <div style='background:#1c1c1e; border:1px solid {_vcol}; border-radius:14px; padding:16px;'>
            <p style='margin:2px 0;'>- <b>주당배당금(DPS)</b>: <b>{fmt_num(_div.get('dps'), ',.0f', '원', na='미공시')}</b>
               · <b>배당수익률</b>: <b>{fmt_pct(_div.get('dividend_yield_pct'), digits=2)}</b>
               (현재가 {fmt_num(realtime_price, ',.0f', '원')} 기준)</p>
            <p style='margin:2px 0;'>- <b>추정 배당락일</b>: <b>{_div['estimated_ex_date']}</b>
               (D-{_dte}) · 추정 배당기준일 {_div['estimated_record_date']}</p>
            <p style='margin:2px 0;'>- <b>배당락 이론 하락폭</b>: 약 <b>{fmt_pct(_div['expected_drop_pct'], digits=2)}</b>
               · 왕복 거래비용 {_cost:.2f}% → <b style='color:{"#30d158" if _net_edge > 0 else "#ff453a"};'>순 {_net_edge:+.2f}%p</b></p>
            <hr style='border-color:#2c2c2e; margin:10px 0;'>
            <p style='margin:2px 0; color:{_vcol};'><b>판정</b>: {_verdict}</p>
            <p style='font-size:0.78rem; color:#ff9f0a; margin-top:8px;'>⚠️ {_div['note']}</p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("#### 📑 10대 표준 레포트 원문 정밀 전체 보기")
    with st.expander("📄 [클릭] 10대 표준 퀀트 레포트 원문 전체 펼쳐보기", expanded=True):
        st.markdown(f"""
        <div style='background: #161618; border: 1px solid #2c2c2e; border-radius: 14px; padding: 24px 28px; line-height: 1.8;'>
            {report_text}
        </div>
        """, unsafe_allow_html=True)

st.markdown("---")

# 데이터 출처 교차검증 상태표 (Section 2 & P1-4 Matrix)
st.markdown("#### 📡 데이터 출처별 교차검증 상태표 (5대 출처 우선순위)")
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
            f"<td><span style='color:{'#30d158' if '정상' in row['status'] else ('#64d2ff' if '간접' in row['status'] else '#86868b')};'>{row['status']}</span></td>"
            f"<td>{row['delay']}</td>"
            f"<td><span style='color:{'#30d158' if '일치' in row['diff'] else '#86868b'};'>{row['diff']}</span></td>"
            "</tr>"
            "<tr>"
            f"<td colspan='8' style='padding:2px 12px 10px; color:#86868b; font-size:0.8rem; border-top:none;'>"
            f"↳ 이 빌드에서의 실제 사용처: {row.get('role', '—')}</td>"
            "</tr>"
            for row in matrix_data])}
    </tbody>
</table>
""", unsafe_allow_html=True)

st.markdown("---")
st.caption("⚠️ 본 시뮬레이터는 네이버증권·다음금융 웹 데이터에 기초한 참고용 정보이며, 특정 종목의 매수·매도 권유가 아닙니다. "
           "투자 판단과 손익의 최종 책임은 투자자 본인에게 있습니다. "
           "KRX·DART·FnGuide 데이터는 네이버 종목페이지를 경유해 간접적으로 사용하며(거래일 달력·업종분류·재무·투자지표), "
           "각 기관 API 직접 조회는 연동되어 있지 않습니다. 표의 '실제 사용처' 행을 참고하세요.")
