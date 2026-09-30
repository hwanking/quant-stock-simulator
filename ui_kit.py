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
import re as _re
from typing import Iterable, Optional, Sequence

import streamlit as st

# ── 표면 3단계 (테두리 없음 — 이 대비만으로 층이 보인다) ──────────────────
# 라운드 399 (2026-10-01 · 사용자: "제미나이 사이트 스타일로 전체로 바꿔줄래?") — 제미나이(Material 3)
#   톤으로 바꿨다. 다크는 본문 #131314 · 사이드바·카드 #1E1F20 · 올린 면 #282A2C, 라이트는 흰 본문 ·
#   옅은 청회색 면(#F0F4F9). 의미 관례는 그대로다 — 오르면 빨강 · 내리면 파랑(§5).
#   값은 눈대중이 아니라 계산으로 골랐다(_probe/r399_palette.py): 글자 3단·의미색 전부가 본문·카드·
#   올린 면·사이드바 **네 면 모두에서 4.5:1 이상**이다 —
#     다크  tx1 11.2~14.5 · tx2 8.5~10.9 · tx3 6.1~7.8 · 의미색 최저 6.0
#     라이트 tx1 14.2~16.5 · tx2 8.1~9.4 · tx3 5.3~6.1 · 의미색 최저 5.0
#   배경↔카드 명도비 다크 1.125 · 라이트 1.104 (§78 의 1.10 이상).
#   sel_bg/sel_tx 는 선택된 알약(사이드바 항목·탭)의 면과 글자(7.2 · 12.6), on_brand 는 브랜드로 채운
#   버튼 위 글자(7.5 · 6.4)다.
DARK = dict(bg='#131314', card='#1E1F20', raised='#282A2C',
            line='#3C4043', tx1='#E3E3E3', tx2='#C4C7C5', tx3='#A2A9B0',
            brand='#A8C7FA', up='#F28B82', down='#8AB4F8',
            pos='#6DD58C', warn='#FDD663', neg='#FF8A80',
            sel_bg='#004A77', sel_tx='#C2E7FF', on_brand='#062E6F')
#: 사이드바 면 — 제미나이처럼 본문보다 한 단계 밝고 카드와 같은 면
DARK_NAV = '#1E1F20'
LIGHT_NAV = '#F0F4F9'
LIGHT = dict(bg='#FFFFFF', card='#F0F4F9', raised='#E9EEF6',
             line='#DDE3EA', tx1='#1F1F1F', tx2='#444746', tx3='#5E6267',
             brand='#0B57D0', up='#C5221F', down='#0B57D0',
             pos='#146C2E', warn='#8A5300', neg='#B3261E',
             sel_bg='#D3E3FD', sel_tx='#041E49', on_brand='#FFFFFF')
# tx3 는 보조 설명 전용이며 4.5 미만으로 내려가면 안 된다 (작은 12px 글자가 많다).
# (라운드 399 전 값 — 다크 bg #0A0B0F · card #16181F · brand #488AF7 / 라이트 bg #EFF1F6 · card #FFFFFF —
#  은 git 이력에 있다.)

#: 제미나이 서명 그라디언트 — **큰 굵은 글자(로고·본문 대제목)에만** 쓴다(`.gm-grad`). 라이트 바탕에서
#  세 점이 3.1~3.7:1 이라 큰 글자 기준(3:1)은 넘지만 작은 글자 기준(4.5)은 못 넘는다(r399_palette2.py).
GEMINI_GRADIENT = 'linear-gradient(74deg, #4285F4 0%, #9B72CB 45%, #D96570 100%)'

#: 글꼴 — Google Sans Flex(Google Fonts 공개 · 라틴·숫자)를 먼저, 한글은 Google Sans 에 없어 Noto Sans KR ·
#  Pretendard · 애플 · 맑은 고딕 순으로 내려간다. 받지 못해도 다음 글꼴로 내려갈 뿐 화면은 안 깨진다.
FONT_STACK = ('"Google Sans Flex", "Google Sans", "Google Sans Text", "Noto Sans KR", '
              '"Pretendard", "Pretendard Variable", -apple-system, BlinkMacSystemFont, '
              '"Apple SD Gothic Neo", "Segoe UI", Roboto, "Malgun Gothic", sans-serif')
FONT_IMPORT = ("@import url('https://fonts.googleapis.com/css2?"
               "family=Google+Sans+Flex:wght@400;500;600;700"
               "&family=Noto+Sans+KR:wght@400;500;700&display=swap');")


def tokens(theme: str = 'dark') -> dict:
    return DARK if theme == 'dark' else LIGHT


def _esc_attr(s) -> str:
    """속성값 전용 — 순수 이스케이프. `href` · `title` 처럼 태그가 들어가면
    안 되는 자리에만 쓴다. 텍스트 자리에는 `_esc()` 를 쓴다."""
    return _html.escape(str(s if s is not None else ''))


def _esc(s) -> str:
    """텍스트 자리의 기본값 — 이스케이프하되 **굵게** 표기만 <b> 로 살린다.

    ■ 실제 사고 (라운드 120 · 120b · 120c)
      화면 8곳에 별표가 **글자 그대로** 나오고 있었다:
          "위 두 적중률은 **점수 60점 이상**만 센 것입니다"
      엔진·화면의 산문은 마크다운으로 쓰여 있는데, 킷이 그 문장을 인라인
      HTML 안에 넣으면서 순수 이스케이프만 걸었다. HTML 안에서는 마크다운을
      아무도 해석하지 않으므로 `**` 가 남는다.

      한 문장씩 `<b>` 로 고치는 것은 같은 실수를 다시 부른다 — 산문을
      쓰는 사람은 마크다운으로 쓴다. **받는 쪽에서** 해석한다.

    ■ 세 번 고치고 세 번 다 다른 자리였다 (라운드 120d)
      ① 킷의 note() · post_entry_caveat  ② web_app 의 _md_safe
      ③ 엔진 note 를 f-string 으로 직접 보간한 자리
      한 자리씩 `_esc_md()` 로 바꾸는 방식이 세 번 다 새 자리를 남겼다.
      그래서 **기본값 쪽**을 바꾼다 — 텍스트 자리는 아무것도 안 해도
      안전하고, 태그가 들어가면 안 되는 자리만 `_esc_attr()` 로 명시한다.
      빠뜨렸을 때 나는 결과가 '별표 노출'이 아니라 '속성에 태그'가 되므로
      드물고 눈에 띈다.

    ※ 이스케이프를 먼저 하므로 `<b>` 는 우리가 넣은 것만 살아남는다.
      (사용자·외부 문자열의 태그는 그대로 escape 된다 — 주입 안전)
    """
    return _RE_MD_BOLD.sub(r'<b>\1</b>', _esc_attr(s))


def _esc_md(s) -> str:
    """`_esc()` 의 옛 이름. web_app 이 명시적으로 부르는 자리가 있어 남긴다."""
    return _esc(s)


#: `**굵게**` — 여는 별표 **뒤**와 닫는 별표 **앞**에 공백이 오면 마크다운은
#  굵기로 보지 않는다. 그 규칙을 그대로 따라 그런 경우는 건드리지 않는다
#  (실제로 화면에 `** 상장시장 국면 …**` 이 그렇게 남아 있었다).
_RE_MD_BOLD = _re.compile(r'\*\*(?=\S)(.+?)(?<=\S)\*\*', _re.S)


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


def logo(theme: str = 'dark', size: int = 28, sub: str = '',
         href: str = '', title: str = '') -> str:
    """
    가늠 로고 — 마크 하나와 워드마크.

    '가늠'은 가늠쇠에서 온 말이다. 가늠쇠는 총열 끝의 작은 표적 조준점이다.
    라운드 399 부터 마크는 제미나이식 네 갈래 반짝임이고, 네 끝이 조준선 방향,
    가운데 구멍이 가늠쇠 구멍이다(종전: 원 안의 십자와 마침표 — git 이력에 있다).
    `sub` 를 주면 워드마크 아래 한 줄을 13px 로 적는다.

    ■ `href` (라운드 122)
      web_app 1529행에 "제목 자체를 홈 버튼으로 쓴다"고 **주석으로만**
      적혀 있었고, 코드는 맨 `<div>` 였다. 사이드바는 그 아래에서
      "제목을 누르면 첫 화면으로 돌아갑니다"라고 안내하고 있었다 —
      화면이 지키지 못할 약속을 하고 있었던 것이다.
      결정을 주석이 아니라 **코드**로 옮긴다.
    """
    t = tokens(theme)
    # 라운드 399 (2026-10-01 · 사용자: "가늠의 로고도 다시 만들어줘 … 제미나이 스타일로") — 새 로고.
    #   마크: 제미나이식 **네 갈래 반짝임**을 서명 그라디언트(파랑→보라→산호)로 채우고 **가운데를 뚫었다**.
    #   네 끝은 가늠쇠의 조준선 방향(상하좌우)이고 가운데 구멍이 가늠쇠 구멍이다 — 뜻(재 보고 겨눈다)은 그대로다.
    #   워드마크는 고정 크기(타입 스케일 안 · 종전 f-string 이 23px 을 만들어 스케일 밖이었다) · 굵기 500 ·
    #   같은 그라디언트. 큰 글자라 그라디언트 대비 3:1 기준을 넘는다(GEMINI_GRADIENT 주석).
    #   그라디언트 id 는 페이지에 로고가 여럿이어도 같은 정의라 겹쳐도 같은 모양이다.
    #   `size` 는 마크 크기다(워드마크 크기는 아래 `word` 가 정한다).
    mark = (
        f"<svg width='{size}' height='{size}' viewBox='0 0 24 24' "
        f"style='flex:0 0 auto;' aria-hidden='true'>"
        f"<defs><linearGradient id='gaeumGrad' x1='3' y1='21' x2='21' y2='3' "
        f"gradientUnits='userSpaceOnUse'>"
        f"<stop offset='0' stop-color='#4285F4'/><stop offset='0.5' stop-color='#9B72CB'/>"
        f"<stop offset='1' stop-color='#D96570'/></linearGradient></defs>"
        f"<path fill='url(#gaeumGrad)' fill-rule='evenodd' "
        f"d='M12 1.5C12.7 7.3 16.7 11.3 22.5 12C16.7 12.7 12.7 16.7 12 22.5"
        f"C11.3 16.7 7.3 12.7 1.5 12C7.3 11.3 11.3 7.3 12 1.5Z"
        f"M13.6 12a1.6 1.6 0 1 0-3.2 0a1.6 1.6 0 1 0 3.2 0Z'/></svg>")
    # 라운드 399 덤 — 사용자: *"사이즈 더 크게 해줘야지."* 워드마크 22 → 28px · 한 줄 12 → 13px
    #   (둘 다 타입 스케일 안). 마크 크기는 부르는 쪽이 `size` 로 준다.
    word = (f"<span class='gm-grad' style='display:block; font-size:28px; font-weight:500; "
            f"background:{GEMINI_GRADIENT}; -webkit-background-clip:text; background-clip:text; "
            f"-webkit-text-fill-color:transparent; color:{t['tx1']}; "
            f"letter-spacing:-0.01em; line-height:1.1;'>가늠</span>")
    subhtml = (f"<span style='display:block; margin-top:3px; font-size:13px; color:{t['tx3']}; "
               f"font-weight:400; letter-spacing:0; line-height:1.3; white-space:nowrap;'>"
               f"{_esc(sub)}</span>" if sub else '')
    inner = f"{mark}<span style='display:block;'>{word}{subhtml}</span>"
    box = "display:flex; align-items:center; gap:12px;"
    if not href:
        return f"<div class='gm-logo' style='{box}'>{inner}</div>"
    return (f"<a class='gm-logo' href='{_esc_attr(href)}' "
            f"title='{_esc_attr(title or '첫 화면으로')}' "
            f"style='{box} text-decoration:none; cursor:pointer;'>"
            f"{inner}</a>")


#: 아이콘 — Lucide 규격 하나로 통일한다 (24 그리드 · 선 2 · 둥근 끝).
#  직접 그린 장식 아이콘과 이모지는 쓰지 않는다. 의미가 모호하면 아예 안 쓴다.
#  선택 상태에서만 브랜드색을 쓰고, 평소엔 보조색 단색이다.
_ICONS = {
    'target': 'M12 22a10 10 0 100-20 10 10 0 000 20zM12 18a6 6 0 100-12 '
              '6 6 0 000 12zM12 14a2 2 0 100-4 2 2 0 000 4z',
    'wallet': 'M19 7V5a2 2 0 00-2-2H5a2 2 0 000 4h14a2 2 0 012 2v8'
              'a2 2 0 01-2 2H5a2 2 0 01-2-2V5M16 12h.01',
    'chart': 'M3 3v16a2 2 0 002 2h16M7 15l4-4 3 3 5-6',
    'sliders': 'M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3'
               'M1 14h6M9 8h6M17 16h6',
    'search': 'M11 19a8 8 0 100-16 8 8 0 000 16zM21 21l-4.35-4.35',
    'bell': 'M18 8a6 6 0 00-12 0c0 7-3 9-3 9h18s-3-2-3-9'
            'M13.73 21a2 2 0 01-3.46 0',
    'help': 'M12 22a10 10 0 100-20 10 10 0 000 20z'
            'M9.09 9a3 3 0 015.83 1c0 2-3 3-3 3M12 17h.01',
    #: 펼침 표시 — disclose() 가 쓴다. 열리면 CSS 로 180° 돌린다.
    'ChevronDown': 'm6 9 6 6 6-6',
    # ── 추천 카드용 (Lucide 이름 그대로) ──────────────────────────────
    #  한 세트로만 쓴다. 의미가 모호하면 아이콘을 붙이지 않는다.
    'CircleDollarSign': 'M12 22a10 10 0 100-20 10 10 0 000 20z'
                        'M16 8h-6a2 2 0 1 0 0 4h4a2 2 0 1 1 0 4H8M12 18V6',
    'ArrowDownToLine': 'M12 17V3M6 11l6 6 6-6M19 21H5',
    'Target': 'M12 22a10 10 0 100-20 10 10 0 000 20z'
              'M12 18a6 6 0 100-12 6 6 0 000 12z'
              'M12 14a2 2 0 100-4 2 2 0 000 4z',
    'ShieldAlert': 'M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01'
                   'C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72'
                   'a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z'
                   'M12 8v4M12 16h.01',
    'ShieldCheck': 'M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01'
                   'C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72'
                   'a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z'
                   'M9 12l2 2 4-4',
    'Clock3': 'M12 22a10 10 0 100-20 10 10 0 000 20zM12 6v6h4',
    'Newspaper': 'M15 18h-5M18 14h-8'
                 'M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16'
                 'a2 2 0 0 1-2 2Zm0 0a2 2 0 0 1-2-2v-9c0-1.1.9-2 2-2h2',
    'ChartNoAxesCombined': 'M12 16v5M16 14v7M20 10v11'
                           'M22 3l-8.65 8.65a.5.5 0 0 1-.7 0L9.35 8.35'
                           'a.5.5 0 0 0-.7 0L2 15M4 18v3M8 14v7',
    'TriangleAlert': 'M21.73 18l-8-14a2 2 0 0 0-3.48 0l-8 14'
                     'A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3M12 9v4M12 17h.01',
    'CalendarClock': 'M21 7.5V6a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h3.5'
                     'M16 2v4M8 2v4M3 10h5'
                     'M22 16a6 6 0 10-12 0 6 6 0 0012 0zM16 14v2l1 1',
}


def _icon(name, color, size=16):
    """단일 규격 아이콘. 없는 이름이면 아무것도 그리지 않는다 (억지로 붙이지 않는다)."""
    d = _ICONS.get(name)
    if not d:
        return ''
    return (f"<svg width='{size}' height='{size}' viewBox='0 0 24 24' "
            f"fill='none' stroke='{color}' stroke-width='2' "
            f"stroke-linecap='round' stroke-linejoin='round' "
            f"style='flex:0 0 auto;'><path d='{d}'/></svg>")


def disclose(label: str, inner_html: str, color: str = '#9DAABC',
             open_: bool = False) -> str:
    """눌러서 펼치는 상세 — **HTML 문자열을 돌려준다** (라운드 79).

    ■ 왜 st.expander 가 아닌가
      이 카드는 `st.markdown(unsafe_allow_html=True)` 로 그린 하나의 HTML
      덩어리다. 중간에 위젯을 끼울 수 없다. 그리고 카드 안 상세를 위젯으로
      빼면 카드가 두 조각으로 갈라져 §5(카드는 한 종류)가 깨진다.

    ■ 왜 <details> 인가
      스크립트 없이 브라우저가 여는 표준 요소다. Streamlit 이 <script> 를
      지워도 동작하고, 키보드·스크린리더가 그냥 읽는다. 라운드 76 의
      알약처럼 스크립트가 죽으면 못 여는 구조를 만들지 않는다.

    본문은 **호출하는 쪽이 만든 HTML 그대로** 넣는다 (숫자 서식·강조가
    이미 들어 있다). 라벨만 escape 한다.

    ■ 왜 바깥에 div 를 한 겹 두는가 — 서버를 띄워 보고 두 번 고쳤다
      ① Streamlit 의 `st.expander` 도 DOM 에서 `<details>` 다. `details >
         summary { … }` 처럼 요소로만 스코프를 잡으면 화면의 **모든 확장
         패널**(69개였다)의 마커와 hover 가 같이 바뀐다.
      ② 그래서 `<details class='gn-disc'>` 로 바꿨더니 **class 가 지워져**
         나왔다. Streamlit 의 정화기가 `details` 에는 `style` 만 남긴다
         (같은 markdown 안의 `<a class='gn-ask-fab'>` 는 멀쩡했다).
      → class 가 살아남는 `div` 를 한 겹 씌우고 거기서 스코프를 잡는다.
        회귀가 **렌더된 DOM 이 아니라 소스**만 보면 둘 다 못 잡는다 —
        화면 결함은 서버를 띄워야 나온다.
    """
    car = _icon('ChevronDown', color, 14)
    return (
        f"<div class='gn-disc'>"
        f"<details style='margin:6px 0 0 0;'"
        + (' open' if open_ else '') + ">"
        # display:flex 자체가 크롬·사파리의 기본 삼각형을 없앤다.
        # list-style:none 은 파이어폭스용이다. 둘 다 인라인이라
        # 정화기가 class 를 지워도 살아남는다 — CSS 는 회전만 맡는다.
        f"<summary style='list-style:none; cursor:pointer; display:flex; "
        f"align-items:center; gap:4px; font-size:12px; color:{color}; "
        f"padding:2px 0; user-select:none;'>"
        f"<span>{_esc(label)}</span>{car}</summary>"
        f"<div style='margin:6px 0 2px 0; padding:10px 12px; "
        f"background:rgba(255,255,255,.03); border-radius:10px; "
        f"font-size:12px; line-height:1.75;'>{inner_html}</div>"
        f"</details></div>")


def dot(color, size=10):
    """
    판정 표시용 점 — 이모지(🟢🔴🟡⚪🟠) 대체 (라운드 40).

    금융 터미널 레퍼런스 17종(Binance·Coinbase·Kraken·Stripe·Linear 등)에
    이모지를 UI 상태 표시로 쓰는 예가 없다. 이모지는 폰트·OS 마다 모양과
    크기가 달라 정렬이 깨지고, 색을 우리가 통제할 수 없다.
    같은 자리에 **토큰 색을 그대로 쓰는 점**을 그린다.
    """
    return (f"<span style='display:inline-block; width:{size}px; "
            f"height:{size}px; border-radius:50%; background:{color}; "
            f"flex:0 0 auto; vertical-align:middle;'></span>")


def nav_links(items, theme='dark'):
    """
    아코디언 안의 이동 링크 — 아이콘 없이 글자만.

    메뉴마다 아이콘을 붙이면 의미가 흐려진다. 1차 단계에만 아이콘을 두고
    그 안의 항목은 글자로만 구분한다 (참조 화면도 그렇게 한다).
    """
    t = tokens(theme)
    out = []
    for label, href in items:
        out.append(
            f"<a href='{_esc_attr(href)}' style='display:block; padding:7px 12px "
            f"7px 34px; font-size:13px; color:{t['tx2']}; "
            f"text-decoration:none; border-radius:7px; "
            f"white-space:nowrap;'>{_esc(label)}</a>")
    return ("<div style='margin:2px 0 8px 0;'>" + ''.join(out) + "</div>")


def nav_list(items: Sequence[dict], active: str = '',
             theme: str = 'dark') -> str:
    """
    좌측 1차 탭 — 아이콘 + 라벨. 현재 위치는 면으로 표시한다(선이 아니라).

    items: [{'key','label','icon','href'}]
    """
    t = tokens(theme)
    out = []
    for it in items:
        on = (it['key'] == active)
        # 라운드 399 — 선택 표시는 제미나이처럼 옅은 파랑 알약(sel_bg · sel_tx · 대비 7.2 / 12.6)
        col = t['sel_tx'] if on else t['tx2']
        bg = (f"background:{t['sel_bg']};" if on else '')
        out.append(
            f"<a href='{_esc_attr(it.get('href') or '#')}' class='qnav-item' "
            f"style='display:flex; align-items:center; gap:11px; "
            f"padding:9px 14px; border-radius:999px; {bg} "
            f"text-decoration:none; margin-bottom:2px;'>"
            f"{_icon(it.get('icon', 'doc'), col)}"
            f"<span style='font-size:15px; font-weight:{600 if on else 500}; "
            f"color:{col}; white-space:nowrap;'>{_esc(it['label'])}</span></a>")
    return ''.join(out)


def nav_groups(groups: Sequence[dict], active: str = '',
               theme: str = 'dark') -> str:
    """
    2차 서브 내비 — 번호 붙은 그룹 아래 항목들. 참조 화면과 같은 구조.

    groups: [{'title','items':[{'key','label','href','icon'(선택)}]}]
    """
    t = tokens(theme)
    out = []
    for g in groups:
        out.append(
            f"<p style='margin:18px 0 7px 10px; font-size:12px; "
            f"font-weight:600; color:{t['tx3']}; letter-spacing:0.01em;'>"
            f"{_esc(g['title'])}</p>")
        for it in g['items']:
            on = (it['key'] == active)
            col = t['sel_tx'] if on else t['tx2']
            bg = (f"background:{t['sel_bg']};" if on else '')
            ic = (_icon(it['icon'], col, 15) if it.get('icon') else
                  f"<span style='width:15px;'></span>")
            out.append(
                f"<a href='{_esc_attr(it.get('href') or '#')}' class='qnav-sub' "
                f"style='display:flex; align-items:center; gap:10px; "
                f"padding:8px 14px; border-radius:999px; {bg} "
                f"text-decoration:none; margin-bottom:1px;'>{ic}"
                f"<span style='font-size:15px; "
                f"font-weight:{600 if on else 400}; color:{col}; "
                f"white-space:nowrap;'>{_esc(it['label'])}</span></a>")
    return ''.join(out)


def nav_toc(title: str, items: Sequence[dict], theme: str = 'dark') -> str:
    """
    지금 보고 있는 종목의 목차 — 사이드바 검색 바로 아래 (라운드 376).

    전역 메뉴(오늘의 시장·내 자산·검증과 이력)와 **한 목록에 섞지 않는다** — 종전엔
    '3. 이 종목' 이 전역 묶음 사이에 끼어 있어 무엇이 앱 전체이고 무엇이 이 종목인지
    갈리지 않았다. 알약 모양으로 줄바꿈해 세로 공간을 적게 쓴다(여섯 항목 ≈ 두 줄).
    items: [{'key','label','href'}]
    """
    t = tokens(theme)
    pills = ''.join(
        f"<a href='{_esc_attr(it.get('href') or '#')}' class='qnav-toc' "
        f"style='display:inline-block; padding:6px 12px; margin:0 6px 6px 0; "
        f"border-radius:8px; background:{t['raised']}; "
        f"font-size:13px; color:{t['tx2']}; text-decoration:none; "
        f"white-space:nowrap;'>{_esc(it['label'])}</a>"
        for it in items)
    return (f"<div style='padding:10px 2px 4px 2px;'>"
            f"<p style='margin:0 0 7px 2px; font-size:12px; font-weight:600; "
            f"color:{t['tx3']};'>{_esc(title)}</p>{pills}</div>")


def acc_css(steps, active='', busy='', theme='dark'):
    """
    아코디언 줄 모양 — 한 번만 주입한다. 버튼을 제목 줄처럼 보이게 한다.

    왜 st.expander 를 안 쓰나: expander 는 **서로 독립**이라 '하나를 열면
    나머지가 닫히는' 동작을 만들 수 없다. 열림 상태를 밖에서 통제할 수도
    없어서 자동 접힘이 성립하지 않는다. 그래서 제목 줄을 버튼으로 그리고
    열린 단계를 session_state 하나로 관리한다.
    """
    t = tokens(theme)
    sb = 'section[data-testid="stSidebar"]'
    css = [
        sb + ' div[class*="st-key-_acc_"] button,',
        sb + ' div[class*="st-key-_acc_"] [data-testid^="stBaseButton"] {',
        '  background: transparent !important; border: none !important;',
        '  box-shadow: none !important; text-align: left !important;',
        '  justify-content: flex-start !important;',
        '  padding: 9px 14px !important; border-radius: 999px !important;',
        '  min-height: 0 !important; width: 100% !important; }',
        sb + ' div[class*="st-key-_acc_"] button p {',
        '  font-size: 15px !important; font-weight: 500 !important;',
        '  margin: 0 !important; text-align: left !important;',
        '  width: 100% !important; letter-spacing: 0 !important;',
        '  color: ' + t['tx2'] + ' !important; }',
        sb + ' div[class*="st-key-_acc_"] button:hover {',
        '  background: ' + t['raised'] + ' !important; }',
        # 항상 펼친 단계의 제목 — 버튼이 아니므로 같은 리듬만 맞춘다
        sb + ' .acc-always { font-size: 13px; font-weight: 600;',
        '  color: ' + t['brand'] + '; padding: 9px 11px;',
        '  margin: 0; letter-spacing: 0; }',
    ]
    for s in steps:
        # 일반 규칙(div[class*=...] button p)과 특이도를 맞춘다 —
        # 낮으면 활성 색이 눌려서 어느 단계가 열렸는지 안 보인다
        sel = sb + ' div.st-key-_acc_' + s['key']
        if s['key'] == active:
            # 라운드 399 — 열린 단계는 제미나이 선택 알약(sel_bg · sel_tx)
            css.append(sel + ' button { background: ' + t['sel_bg']
                       + ' !important; }')
            css.append(sel + ' button p { color: ' + t['sel_tx']
                       + ' !important; font-weight: 600 !important; }')
        elif s['key'] == busy:
            css.append(sel + ' button p { color: ' + t['brand']
                       + ' !important; }')
    st.sidebar.markdown('<style>' + '\n'.join(css) + '</style>',
                        unsafe_allow_html=True)


def acc_row(step, active='', busy='', state_key='sb_step'):
    """
    아코디언 제목 줄 하나. 눌리면 그 단계를 열고 나머지는 자동으로 닫는다.
    이미 열린 것을 다시 누르면 닫는다 (전부 닫힌 상태도 허용).
    반환: 이 줄이 지금 열려 있는가
    """
    # always=True 인 단계는 아코디언 규칙에서 빼고 **항상 펼쳐 둔다**
    # (라운드 38 · 사용자 요청): "종목 찾기는 접는 것보다 다시 불러오는 일이
    # 훨씬 잦으니 늘 열려 있어야 한다."
    always = bool(step.get('always'))
    on = always or (step['key'] == active)
    # 아이콘은 Streamlit 내장 Material Symbols 하나로 통일한다 —
    # 직접 그린 SVG 는 버튼 라벨에 못 넣고, 세트를 섞으면 아마추어처럼 보인다.
    ico = step.get('icon') or ''
    head = f":material/{ico}: " if ico else ''
    # 완료는 ✓, 미설정은 표시 안 함(빈 원은 실패처럼 보인다), 처리 중은 ●
    mark = '  ✓' if step.get('done') is True else ''
    run = '  ●' if step['key'] == busy else ''
    arrow = '' if always else ('  ▾' if on else '  ▸')
    label = head + str(step['title']) + run + mark + arrow
    if always:
        # 접을 수 없으므로 버튼이 아니라 제목으로 그린다 — 누를 수 있게
        # 보이는데 아무 일도 안 일어나면 그게 더 나쁘다.
        st.sidebar.markdown(
            f"<div class='acc-always'>{_esc(str(step['title']))}</div>",
            unsafe_allow_html=True)
        return True
    if st.sidebar.button(label, key='_acc_' + step['key'],
                         width='stretch',
                         help=step.get('hint') or None):
        st.session_state[state_key] = ('' if on else step['key'])
        st.rerun()
    return on


def plan_card(plan: str, usage_pct: int, engine: str, version: str,
              theme: str = 'dark') -> str:
    """사이드바 하단 상태 카드 — 참조 화면의 플랜 카드 자리."""
    t = tokens(theme)
    return (
        f"<div style='background:{t['card']}; border-radius:12px; "
        f"padding:14px 14px 12px 14px; margin-top:20px; "
        f"border-top:2px solid {t['brand']};'>"
        f"<div style='display:flex; align-items:center; gap:9px; "
        f"margin-bottom:10px;'>"
        f"<span style='width:26px; height:26px; border-radius:50%; "
        f"background:{t['brand']}; color:#fff; font-size:12px; "
        f"font-weight:700; display:flex; align-items:center; "
        f"justify-content:center; flex:0 0 auto;'>가</span>"
        f"<div style='min-width:0;'>"
        f"<p style='margin:0; font-size:12px; color:{t['tx3']};'>지금 보는 모델</p>"
        f"<p style='margin:0; font-size:13px; font-weight:600; "
        f"color:{t['tx1']};'>{_esc(plan)}</p></div></div>"
        f"<div style='display:flex; justify-content:space-between; "
        f"font-size:12px; color:{t['tx3']}; margin-bottom:5px;'>"
        f"<span>실전 신뢰도</span><span>{usage_pct}%</span></div>"
        f"<div style='height:4px; background:{t['raised']}; border-radius:2px; "
        f"overflow:hidden; margin-bottom:12px;'>"
        f"<div style='height:100%; width:{max(0, min(100, usage_pct))}%; "
        f"background:{t['brand']};'></div></div>"
        f"<p style='margin:0 0 3px 0; font-size:12px; color:{t['tx3']};'>"
        f"분석 엔진</p>"
        f"<p style='margin:0; font-size:13px; color:{t['tx1']}; "
        f"display:flex; align-items:center; gap:7px;'>"
        f"<span style='width:6px; height:6px; border-radius:50%; "
        f"background:{t['pos']};'></span>{_esc(engine)}</p>"
        f"<p style='margin:2px 0 0 13px; font-size:12px; color:{t['tx3']}; "
        f"font-variant-numeric:tabular-nums;'>{_esc(version)}</p></div>")


def status_bar(items: Sequence[tuple], version: str = '',
               theme: str = 'dark', version_href: str = '#nav-updates') -> None:
    """
    상단 상태 줄 — 왼쪽에 지금 상태, 오른쪽 끝에 운영 버전 칩.

    items: [(text, tone)] · tone 은 pos/warn/neg/'' 중 하나.
    화면에서 가장 조용한 줄이어야 한다 — 상태는 배경 정보다.
    """
    t = tokens(theme)
    cells = []
    for i, it in enumerate(items):
        txt = it[0]
        tone = t.get(it[1], t['tx2']) if len(it) > 1 and it[1] else t['tx2']
        dot = (f"<span style='width:6px; height:6px; border-radius:50%; "
               f"background:{tone}; display:inline-block; "
               f"margin-right:7px;'></span>" if i == 0 else '')
        sep = ('' if i == 0 else
               f"<span style='color:{t['tx3']}; margin:0 10px;'>·</span>")
        cells.append(f"{sep}{dot}<span style='color:"
                     f"{tone if i == 0 else t['tx3']};'>{_esc(txt)}</span>")
    # 버전 칩은 **누르면 업데이트 이력으로** 간다. 버전만 보여 주고 무엇이
    # 바뀌었는지 못 찾게 하면 그 숫자는 장식이다.
    chip = (f"<a href='{_esc_attr(version_href)}' style='margin-left:auto; "
            f"display:flex; align-items:center; gap:8px; flex:0 0 auto; "
            f"text-decoration:none;' title='누르면 업데이트 이력으로 갑니다'>"
            f"<span style='font-size:12px; color:{t['tx3']}; "
            f"letter-spacing:0.05em;'>운영 버전</span>"
            f"<span style='background:{t['raised']}; color:{t['tx1']}; "
            f"font-size:12px; font-weight:700; padding:3px 9px; "
            f"border-radius:7px; font-variant-numeric:tabular-nums;'>"
            f"{_esc(version)}</span></a>" if version else '')
    st.markdown(
        f"<div style='display:flex; align-items:center; font-size:12px; "
        f"padding:6px 2px 12px 2px; flex-wrap:wrap; gap:4px 0;'>"
        + ''.join(cells) + chip + "</div>", unsafe_allow_html=True)


def update_bar(version: str, headline: str, theme: str = 'dark',
               kind: str = '') -> None:
    """
    최상단 업데이트 바 — 탭보다 위. 사용자가 가장 중요하다고 한 정보다.

    한 건만 보여 준다. 여러 건을 늘어놓으면 아무것도 안 읽힌다.
    """
    t = tokens(theme)
    tag = (f"<span style='background:{t['raised']}; color:{t['tx2']}; "
           f"font-size:12px; font-weight:600; padding:2px 8px; "
           f"border-radius:6px; flex:0 0 auto;'>{_esc(kind)}</span>"
           if kind else '')
    st.markdown(
        f"<div style='display:flex; align-items:center; gap:12px; "
        f"background:{t['card']}; border-radius:12px; padding:10px 16px; "
        f"margin-bottom:10px; flex-wrap:wrap;'>"
        f"<span style='width:7px; height:7px; border-radius:50%; "
        f"background:{t['pos']}; flex:0 0 auto;'></span>"
        f"<span style='font-size:12px; color:{t['tx3']}; font-weight:600; "
        f"letter-spacing:0.02em; flex:0 0 auto;'>최신 업데이트</span>"
        f"<span style='font-size:12px; color:{t['brand']}; font-weight:700; "
        f"font-variant-numeric:tabular-nums; flex:0 0 auto;'>"
        f"{_esc(version)}</span>{tag}"
        f"<span style='font-size:13px; color:{t['tx1']}; min-width:0; "
        f"overflow:hidden; text-overflow:ellipsis; white-space:nowrap;'>"
        f"{_esc(headline)}</span></div>",
        unsafe_allow_html=True)


#: 분석 파이프라인의 실제 단계 — 화면에 이 순서대로 보여 준다.
#  이름을 지어내지 않는다. 각 단계는 실제로 코드가 하는 일이다.
STEPS = [
    ('collect', '데이터 수집'),
    ('crosscheck', '가격 교차검증'),
    ('indicators', '기술지표 계산'),
    ('news', '뉴스 분석'),
    ('similar', '과거 유사사례 탐색'),
    ('verdict', '최종 판단 생성'),
]


def dur_ko(sec: float | int | None) -> str:
    """초를 사람이 읽는 시간으로 — `187` → `3분 7초` (라운드 99).

    ■ 왜
      진행 표시가 `187초 경과 · 약 240초 남음` 처럼 **초만** 쓰고 있었다.
      2~5분짜리 정밀 분석에서 세 자리 초는 크기가 안 잡힌다. 사람은
      '3분쯤' 으로 읽지 '187초' 로 읽지 않는다.

    ■ 규칙
      · 60초 미만        → `47초`
      · 60초 이상        → `3분 7초` (초가 0이면 `3분`)
      · 1시간 이상       → `1시간 4분`
      · None / 음수      → `—` (없는 값을 0초로 꾸미지 않는다, §3)
    """
    if sec is None:
        return '—'
    try:
        s = int(round(float(sec)))
    except (TypeError, ValueError):
        return '—'
    if s < 0:
        return '—'
    if s < 60:
        return f'{s}초'
    if s < 3600:
        m, r = divmod(s, 60)
        return f'{m}분 {r}초' if r else f'{m}분'
    h, r = divmod(s, 3600)
    m = r // 60
    return f'{h}시간 {m}분' if m else f'{h}시간'


def progress(done: int, total: int = 0, label: str = '',
             theme: str = 'dark', elapsed: float | None = None) -> str:
    """
    절제된 진행 표시 — 얇은 막대와 단계 이름만. 회전하는 장식은 쓰지 않는다.

    반환한 HTML 을 st.empty().markdown 에 넣어 단계마다 갈아 끼운다.
    """
    t = tokens(theme)
    total = total or len(STEPS)
    pct = max(0.0, min(100.0, 100.0 * done / max(1, total)))
    dots = []
    for i, (_k, ko) in enumerate(STEPS[:total]):
        if i < done:
            col, mark = t['pos'], '✓'
        elif i == done:
            col, mark = t['brand'], '·'
        else:
            col, mark = t['tx3'], '·'
        dots.append(
            f"<span style='font-size:12px; color:{col}; white-space:nowrap;'>"
            f"{mark} {_esc(ko)}</span>")
    # 얼마나 걸렸고 얼마나 남았는지 — '멈춘 건가' 를 없애는 유일한 정보
    el = ''
    if elapsed is not None:
        _left = ''
        if done > 0 and done < total:
            _eta = elapsed / done * (total - done)
            _left = f" · 약 {dur_ko(_eta)} 남음"
        el = (f"<span style='font-size:12px; color:{t['tx3']}; "
              f"font-variant-numeric:tabular-nums;'>"
              f"{dur_ko(elapsed)} 경과{_left}</span>")
    return (
        f"<div style='background:{t['card']}; border-radius:14px; "
        f"padding:16px 20px;'>"
        f"<div style='display:flex; align-items:baseline; gap:10px; "
        f"margin-bottom:12px; flex-wrap:wrap;'>"
        f"<span style='font-size:15px; font-weight:600; color:{t['tx1']};'>"
        f"{_esc(label or (STEPS[done][1] if done < len(STEPS) else '완료'))}"
        f"</span>{el}"
        f"<span style='font-size:12px; color:{t['tx3']}; margin-left:auto; "
        f"font-variant-numeric:tabular-nums;'>{done}/{total}</span></div>"
        f"<div style='height:3px; background:{t['raised']}; border-radius:2px; "
        f"overflow:hidden; margin-bottom:12px;'>"
        f"<div style='height:100%; width:{pct:.0f}%; background:{t['brand']}; "
        f"border-radius:2px; transition:width .35s ease;'></div></div>"
        f"<div style='display:flex; gap:14px; flex-wrap:wrap;'>"
        + ''.join(dots) + "</div></div>")


def sidebar_section(title: str, sub: str = '', theme: str = 'dark',
                    top: int = 26, at=None) -> None:
    """
    사이드바 구역 라벨 — 본문 섹션보다 한 단계 조용하다.

    구분선(---)을 쓰지 않는다. 사이드바에 가로선을 그으면 좁은 폭에서 선만
    눈에 남고 내용이 밀린다. 대신 위 여백과 작은 대문자 라벨로 나눈다.

    at: 그릴 자리(st.sidebar.container()). 스트림릿은 **호출 순서대로** 그리므로
        코드를 옮기지 않고 위치만 바꾸려면 미리 잡아 둔 자리를 넘긴다.
    """
    t = tokens(theme)
    s = (f"<p style='margin:3px 0 0 0; font-size:12px; color:{t['tx3']}; "
         f"line-height:1.5; word-break:keep-all;'>{_esc(sub)}</p>"
         if sub else '')
    (at or st.sidebar).markdown(
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


HORIZONS_ALL = (5, 10, 20, 40, 60, 120)


def horizon_counts_line(hz, order=HORIZONS_ALL) -> str:
    """지평별 유사패턴 표본 수를 한 줄로 — "5일 195 · 10일 11 · 20일 0 · 40일 0 · 60일 12 · 120일 3" (라운드 233).

    엔진의 match_count 는 **20일 지평**의 수인데, 화면은 그것을 '유사패턴 표본 0건'이라
    세 번 말한 뒤 60일 표본 12건으로 그래프를 그려 '0건'과 '12건'이 한 화면에 있었다.
    지평별로 먼저 세면 둘은 모순이 아니라 다른 지평이다. hz 에 없는 지평은 건너뛰고,
    하나도 없으면 빈 문자열(호출부가 문장을 안 만든다 — 없는 값을 지어내지 않는다).
    """
    parts = []
    for H in order:
        h = (hz or {}).get(H)
        if not h:
            continue
        parts.append(f"{H}일 {int(h.get('match_count') or 0)}")
    return ' · '.join(parts)


def rho_coverage_line(art):
    """'20일 예측 보류' 옆에 붙는 사실 한 줄 (라운드 348 · 표시 전용).

    사용자가 두 번 물었다 — *"이건 매번 산출 불가인데 도움이 되냐"*. 그때는 문구만 고쳤고 원인은 안 쟀다.
    사전등록(docs/PREREG_R348_RHO_COVERAGE.md)대로 재 보니 이 자리가 비는 것은 대개 **닮은 구간이 없어서가
    아니라 닮음 기준이 엄해서**였다. 그래도 **기준은 안 바꿨다** — 느슨하게 잡아 더 채운 값이 맞는지는 아직
    안 쟀기 때문이다(그 측정은 날짜 하한을 못 채웠다). 수는 산출물에서 읽고 못 읽으면 None(§3).

    물결표를 쓰지 않는다 — 캡션은 마크다운이라 둘이 만나면 취소선이 된다(R295·R337).
    """
    a = art or {}
    per, r0 = a.get('per_rho') or {}, a.get('R0') or {}
    base, loose, cells = r0.get('base_prob_ok'), r0.get('loosest_prob_ok'), a.get('cells')
    rhos = [float(x) for x in (a.get('rhos') or [])]
    op, floors = a.get('operating_rho'), a.get('floors') or {}
    if not (per and cells and rhos and op and floors.get('probability')) or base is None or loose is None:
        return None
    lo = min(rhos)
    zero_op = ((per.get(f'{float(op):.2f}') or {}).get('obs_zero'))
    zero_lo = ((per.get(f'{lo:.2f}') or {}).get('obs_zero'))
    if zero_op is None or zero_lo is None:
        return None
    gain = int(loose) - int(base)
    return (f"이 자리가 비는 까닭을 {a.get('made')} 에 모집단으로 재 봤습니다 — 종목 {a.get('n_codes')}개 × 기준일 "
            f"{len(a.get('asof_dates') or [])}개 = {int(cells):,}칸. 지금 기준(닮음 {float(op):.2f})에서 확률을 낼 만큼 "
            f"모인 칸은 {int(base):,}칸이고, 기준을 {lo:.2f}까지 낮추면 {int(loose):,}칸이 됩니다(+{gain:,}). "
            f"닮은 구간이 **하나도** 없는 칸은 {int(zero_op):,} → {int(zero_lo):,}칸으로 줄어듭니다 — 즉 대개는 "
            f"닮은 구간이 없어서가 아니라 **닮음 기준이 엄해서** 비는 자리입니다. "
            f"그래도 기준은 바꾸지 않았습니다 — 느슨하게 잡아 채운 값이 맞는지를 아직 재지 못했습니다.")


def direction_word(win_rate) -> str:
    """지평의 관찰 방향 — 엔진과 같은 경계(승률 50 이상 = 상승 · 라운드 234). 없으면 '—'."""
    if win_rate is None:
        return '—'
    return '상승' if float(win_rate) >= 50.0 else '하락'


def horizon_directions(hz, order=HORIZONS_ALL) -> dict:
    """지평별 방향 요약 (라운드 234) — 화면이 '방향 일치 67점'을 분자·분모와 같이 말하기 위한 재료.

    엔진의 horizon_consistency_score 는 승률이 산출된 지평(scored) 중 같은 방향인 지평의
    비율이다(max(상승, 하락) / 지평 수 · quant_indicators). 여기서는 그 지평 목록과 상승·하락
    수를 **세기만** 한다 — 점수는 엔진 값을 그대로 쓴다. 표본은 있는데 승률이 없는 지평
    (확률 표시 기준 미달)은 unscored 로 따로 낸다 — 왜 비교에서 빠졌는지 화면이 말해야 한다.
    """
    scored, unscored = [], []
    for H in order:
        h = (hz or {}).get(H)
        if not h:
            continue
        n = int(h.get('match_count') or 0)
        if h.get('win_rate') is None:
            if n:
                unscored.append((H, n))
            continue
        scored.append((H, n, direction_word(h.get('win_rate'))))
    up = sum(1 for _H, _n, d in scored if d == '상승')
    return {'scored': scored, 'unscored': unscored, 'up': up, 'down': len(scored) - up}


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
            # 좁은 화면에서 값이 잘리지 않게 최소폭을 준다. 모자라면 카드가
            # 가로로 스크롤된다 — 숫자를 …으로 지우는 것보다 낫다.
            # 라운드 399 — 타일마다 크기 기준(container)을 둔다: 값 글자가 **화면 폭(vw)이 아니라 타일 폭**을
            #   따라 줄어든다. 종전 `2.4vw` 는 1440px 화면에서 28px 가 되어 좁은 타일(내용 174px)에서
            #   '35,488,337원'(185px)이 …으로 잘렸다(브라우저 실측 2026-10-01).
            f"<div style='flex:1 1 0; min-width:124px; padding:4px 16px; "
            f"container-type:inline-size; {border}'>"
            # 라벨을 …으로 자르지 않는다. 좁으면 두 줄로 흐르게 둔다 —
            # 무슨 지표인지 모르게 만드는 것이 공간 절약보다 나쁘다.
            f"<p style='margin:0; font-size:13px; color:{t['tx2']}; "
            f"font-weight:500; line-height:1.35; word-break:keep-all; "
            f"min-height:2.7em;'>{_esc(it['label'])}</p>"
            # 값은 절대 줄바꿈하지 않는다 — 폭이 좁으면 글자를 줄인다(20·22·28 세 단 ·
            # 단을 고르는 규칙은 global_css 의 `.gm-tv` 한 곳이다).
            f"<p class='gm-tv' style='margin:8px 0 0 0; "
            f"font-weight:600; color:{tone}; letter-spacing:-0.02em; "
            f"line-height:1.15; white-space:nowrap; overflow:hidden; "
            f"text-overflow:ellipsis; font-variant-numeric:tabular-nums;'>"
            f"{_esc(it['value'])}</p>{sub}</div>")
    # ⚠️ 라운드 323 — 카드가 `overflow-x:auto; scrollbar-width:none` 이라 폭이 모자라면 오른쪽이
    #   **스크롤바 없이 가려졌다** — 사용자 화면에서 '왼쪽에서 설정한 값 그대로'가 '… 그대'로 끊겨
    #   보였다(가로 스크롤할 수 있다는 표시가 없으니 잘린 것과 같다). 모자라면 **다음 줄로 흘린다.**
    st.markdown(
        f"<div style='background:{t['card']}; border-radius:18px; "
        f"padding:20px 8px; display:flex; flex-wrap:wrap; row-gap:14px; "
        f"align-items:stretch;'>"
        + ''.join(cells) + "</div>", unsafe_allow_html=True)


def rows_html(items: Sequence[tuple], theme: str = 'dark',
              title: str = '') -> str:
    """`rows()` 의 HTML 본체 — 접는 상세(disclose) 안에 넣을 때 쓴다 (라운드 231).
    그리는 규칙은 rows() 와 같다 — 한 곳."""
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
    return (head + f"<div style='background:{t['card']}; border-radius:18px; "
            f"padding:8px 20px;'>" + ''.join(body) + "</div>")


def rows(items: Sequence[tuple], theme: str = 'dark',
         title: str = '') -> None:
    """
    iOS 설정 앱식 그룹 리스트 — 좌측 라벨 / 우측 값, 행 사이는 헤어라인.

    items: [(label, value)] 또는 [(label, value, tone)]
    """
    st.markdown(rows_html(items, theme, title), unsafe_allow_html=True)
    return
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
    """보조 설명 — 캡션보다 조용하게, 카드 밖에 둔다.

    산문이므로 `**굵게**` 를 해석한다 (_esc_md · 라운드 120).
    """
    t = tokens(theme)
    st.markdown(
        f"<p style='margin:8px 2px 0 2px; font-size:13px; color:{t['tx3']}; "
        f"line-height:1.6;'>{_esc_md(text)}</p>", unsafe_allow_html=True)


def chip_row(items, theme: str = 'dark', title: str = '') -> None:
    """상태 칩 한 줄 (라운드 226) — [{'label','count','tone'(선택),'sub'(선택)}].

    count 가 0 인 칩은 그리지 않는다(빈 칩은 정보가 아니다). 글자는 12px 이상(§77).
    판단을 만들지 않는다 — 부르는 쪽이 이미 센 수를 그대로 그린다.
    """
    t = tokens(theme)
    chips = []
    for it in items:
        try:
            n = int(it.get('count') or 0)
        except (TypeError, ValueError):
            n = 0
        if n <= 0:
            continue
        col = t.get(it.get('tone') or '', t['tx2'])
        sub = (f"<span style='margin-left:6px; font-size:12px; color:{t['tx3']};'>"
               f"{_esc(it.get('sub'))}</span>" if it.get('sub') else '')
        chips.append(
            f"<span style='display:inline-flex; align-items:center; gap:6px; "
            f"padding:5px 11px; border-radius:999px; background:{t['card']}; "
            f"border:1px solid {t['line']}; font-size:13px; color:{t['tx1']}; "
            f"white-space:nowrap;'>"
            f"<span style='width:8px; height:8px; border-radius:50%; background:{col}; "
            f"display:inline-block;'></span>{_esc(it['label'])} "
            f"<b style='color:{col}; font-variant-numeric:tabular-nums;'>{n}</b>{sub}</span>")
    if not chips:
        return
    head = (f"<p style='margin:0 0 6px 2px; font-size:13px; color:{t['tx2']}; "
            f"font-weight:500;'>{_esc(title)}</p>" if title else '')
    st.markdown(head + "<div style='display:flex; flex-wrap:wrap; gap:8px;'>"
                + ''.join(chips) + "</div>", unsafe_allow_html=True)


def bar_list(items, theme: str = 'dark', title: str = '', max_rows: int = 6) -> None:
    """비중 막대 목록 (라운드 226) — [{'label','pct','sub'(선택)}] · pct 는 0~100.

    상위 max_rows 를 그리고 나머지는 '기타'로 합친다(합은 100 을 넘지 않는다).
    """
    t = tokens(theme)
    rows_ = []
    seq = sorted((it for it in items if it.get('pct') is not None),
                 key=lambda it: -float(it['pct']))
    head_rows, rest = seq[:max_rows], seq[max_rows:]
    if rest:
        head_rows = head_rows + [dict(label=f"기타 {len(rest)}개",
                                      pct=sum(float(it['pct']) for it in rest))]
    for it in head_rows:
        pct = max(0.0, min(100.0, float(it['pct'])))
        sub = (f"<span style='color:{t['tx3']}; font-size:12px;'> · {_esc(it.get('sub'))}</span>"
               if it.get('sub') else '')
        rows_.append(
            f"<div style='display:grid; grid-template-columns:minmax(120px,1.4fr) 3fr 56px; "
            f"align-items:center; gap:10px; padding:5px 0;'>"
            f"<span style='font-size:13px; color:{t['tx1']}; overflow:hidden; "
            f"text-overflow:ellipsis; white-space:nowrap;'>{_esc(it['label'])}{sub}</span>"
            f"<span style='height:8px; background:{t['line']}; border-radius:4px; overflow:hidden;'>"
            f"<span style='display:block; width:{pct:.1f}%; height:100%; background:{t['brand']};'></span></span>"
            f"<span style='font-size:13px; color:{t['tx2']}; text-align:right; "
            f"font-variant-numeric:tabular-nums;'>{pct:.0f}%</span></div>")
    if not rows_:
        return
    head = (f"<p style='margin:0 0 4px 2px; font-size:13px; color:{t['tx2']}; "
            f"font-weight:500;'>{_esc(title)}</p>" if title else '')
    st.markdown(head + f"<div style='background:{t['card']}; border-radius:14px; "
                f"padding:10px 16px;'>" + ''.join(rows_) + "</div>", unsafe_allow_html=True)


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
    /* .stApp p 규칙(0,1,1)이 !important 로 이기므로 특이도를 더 올린다 */
    .stApp [data-testid="stSliderThumbValue"] p,
    .stApp [data-testid="stSliderThumbValue"],
    [data-testid="stSidebar"] [data-testid="stSliderThumbValue"] p,
    [data-testid="stSidebar"] [data-testid="stSliderThumbValue"] {{
        color: #0B0F17 !important; font-weight: 600 !important; }}

    /* 수직 리듬 — 8pt 그리드 */
    .stApp hr {{ margin: 40px 0 !important; border-color: {t['line']} !important;
                opacity: 1 !important; }}
    /* ── 모바일 (≤768px) ─────────────────────────────────────────────
       데스크톱을 축소하지 않는다. 한 열로 세우고, 터치 대상을 44px 이상으로
       키우고, 넘치는 것은 각자의 상자 안에서만 넘치게 한다. */
    @media (max-width: 768px) {{
        .stMainBlockContainer {{ padding: 12px 16px !important; }}
        /* 타일 줄 — 줄이면 숫자가 안 보인다. 가로로 밀어 보게 한다 */
        .stApp div[style*="align-items:stretch"] {{
            overflow-x: auto !important; -webkit-overflow-scrolling: touch;
            scrollbar-width: none; }}
        .stApp div[style*="align-items:stretch"] > div {{
            min-width: 136px !important; }}
        /* 컬럼은 한 열로 */
        .stApp [data-testid="stHorizontalBlock"] {{
            flex-direction: column !important; gap: 12px !important; }}
        .stApp [data-testid="stColumn"] {{ width: 100% !important;
            flex: 1 1 100% !important; min-width: 0 !important; }}
        /* 표는 자기 상자 안에서만 넘친다 — 본문이 밀리면 안 된다 */
        .stApp [data-testid="stDataFrame"] {{ max-width: 100% !important; }}
        .stApp table {{ display: block; overflow-x: auto; max-width: 100%; }}
        /* 탭은 가로 스크롤 */
        .stApp .stTabs [data-baseweb="tab-list"] {{
            overflow-x: auto !important; flex-wrap: nowrap !important;
            scrollbar-width: none; }}
        /* 터치 대상 44px — 애플 HIG 최소치 */
        .stApp button, .stApp [role="tab"] {{ min-height: 44px !important; }}
        /* 상단 툴바는 좁게, 종목 표시는 접는다 */
        .qnav {{ padding: 8px 10px !important; gap: 4px !important; }}
        .qnav .here {{ display: none !important; }}
        .qnav a {{ font-size: 12px !important; padding: 6px 9px !important; }}
    }}
    /* 타일 값(stat_tiles · 라운드 399) — 타일 폭을 따라 **타입 스케일의 세 단(20·22·28)** 으로만 커진다.
       첫 판은 clamp(20px, 13cqw, 28px) 였는데 연속값이라 22.62px 같은 스케일 밖 크기가 나왔다(브라우저 실측 ·
       타일 5개). 문턱은 새로 고른 수가 아니라 같은 비율(글자 = 타일 내용 폭의 13%)이 22·28 에 닿는 폭이다 —
       22 ÷ 0.13 = 169.2 → 170px · 28 ÷ 0.13 = 215.4 → 216px. 그래서 잘리지 않는 성질은 그대로다. */
    /* !important — 본문 문단 규칙(`.stApp .stMarkdown p` 16px)이 클래스 하나보다 구체적이다. 종전엔 인라인이라 이겼다
       주의 — 첫 판은 바닥을 20px 로 두었는데 휴대폰(375px)에서 타일 내용 폭이 107px 이라 '35,488,337원' 이 잘렸다(21개 중
       4개 · 브라우저 실측). 같은 비율(13%)을 스케일의 **모든 단**에 건다 — 문턱은 전부 '단 ÷ 0.13' 이다(새 숫자 없음):
       15→116 · 16→124 · 17→131 · 20→154 · 22→170 · 28→216px, 그보다 좁으면 13px(제미나이 층이 12px 을 13 으로 올리는
       바닥과 같은 값). */
    .gm-tv {{ font-size: 13px !important; }}
    @container (min-width: 116px) {{ .gm-tv {{ font-size: 15px !important; }} }}
    @container (min-width: 124px) {{ .gm-tv {{ font-size: 16px !important; }} }}
    @container (min-width: 131px) {{ .gm-tv {{ font-size: 17px !important; }} }}
    @container (min-width: 154px) {{ .gm-tv {{ font-size: 20px !important; }} }}
    @container (min-width: 170px) {{ .gm-tv {{ font-size: 22px !important; }} }}
    @container (min-width: 216px) {{ .gm-tv {{ font-size: 28px !important; }} }}
    /* 화면 폭을 다 쓴다. 1120px 로 묶어 두면 넓은 모니터에서 양옆이 비고
       표·차트가 좁아진다. 다만 무한정 늘리면 한 줄이 너무 길어 읽기 나빠지므로
       본문 글줄만 별도로 제한한다. */
    .stMainBlockContainer {{ max-width: 1600px !important;
                            padding-top: 1.5rem !important;
                            padding-left: 2.5rem !important;
                            padding-right: 2.5rem !important; }}
    @media (min-width: 1900px) {{
        .stMainBlockContainer {{ max-width: 1800px !important; }}
    }}
    """


def gemini_css(theme: str = 'dark') -> str:
    """제미나이 톤의 층 — web_app 이 **전역 CSS 층들 뒤에 한 번** 주입한다 (라운드 399).

    사용자: *"제미나이 사이트 스타일로 전체로 바꿔줄래? 사이트 다시 단장하고 싶어졌어."*
    앞 층들(애플 정돈 · 옛 다크 규칙 · 라이트 오버라이드)을 하나씩 고치지 않고 **위에 얹는다** — 층마다
    손대면 한 곳이 빠진다(§4). 색은 전부 토큰에서 온다(새 hex 는 서명 그라디언트뿐 · GEMINI_GRADIENT).
    **값·배치·판정은 안 건드린다** — 바꾸는 것은 글꼴 · 모서리 · 채움 · 선택 표시 · 그림자뿐이다.
    """
    t = tokens(theme)
    nav = DARK_NAV if theme == 'dark' else LIGHT_NAV
    return f"""
    {FONT_IMPORT}
    /* 글꼴 — `.stApp` 에만 걸면 Streamlit 이 마크다운·캡션·버튼·라벨마다 박는 "Source Sans" 가 이긴다
       (브라우저 실측 2026-10-01: 본문·캡션·제목·버튼·라벨 전부 Source Sans 였다 — 종전의 애플 글꼴 목록도
       같은 이유로 한 번도 안 닿았다). 모든 요소에 걸되 **아이콘 글꼴과 코드는 뺀다**(Material Symbols 를
       덮으면 아이콘 대신 'keyboard_arrow_down' 같은 글자가 나온다). */
    /*    주의 — 라벨 속 `:material/이름:` 아이콘은 testid 없이 `<span role="img" translate="no" style="font-family:
          Material Symbols …">` 로 그려진다 — 첫 판이 그것을 덮어 사이드바에 'search'·'tune' 같은 글자가 나왔다
          (브라우저 실측). translate="no" 와 인라인 Material 글꼴도 뺀다. */
    .stApp, .stApp *:not([data-testid="stIconMaterial"]):not([class*="material"]):not([translate="no"]):not([style*="Material Symbols"]):not([role="img"]):not(code):not(code *):not(pre):not(pre *):not(kbd) {{
        font-family: {FONT_STACK} !important; }}
    /* Streamlit 머리줄(60px)은 투명 · 누름은 그 안의 메뉴 버튼만 — 불투명이면 본문 맨 위 상단 바(엔진 정보)를 덮어
       빈 줄로 보였다(사용자 화면 · 2026-10-01). 상단 바가 그 자리를 쓴다. */
    .stApp [data-testid="stHeader"] {{ background: transparent !important; pointer-events: none; }}
    .stApp [data-testid="stHeader"] [data-testid="stToolbar"], .stApp [data-testid="stHeader"] button,
    .stApp [data-testid="stHeader"] a {{ pointer-events: auto; }}
    /* 한글 줄바꿈 — 낱말 가운데서 끊지 않는다('고치/기' · '부/족' 처럼 끊겼다 · 브라우저 실측). 너무 긴
       한 낱말만 넘칠 때 끊는다(break-word 는 칸 최소 폭 계산을 안 바꾼다 — anywhere 는 표 칸을 한 글자로 좁힌다) */
    .stApp {{ word-break: keep-all; overflow-wrap: break-word; }}
    /* 본문 16px — 제미나이 본문 크기(타입 스케일 안). 크기를 직접 적은 글자·사이드바(13)는 아래 규칙대로 */
    .stApp .stMarkdown p, .stApp .stMarkdown li,
    .stApp [data-testid="stMarkdownContainer"] p, .stApp [data-testid="stMarkdownContainer"] li {{
        font-size: 16px; line-height: 1.65; }}

    /* ── 읽기 정돈 (사용자: "배치가 따닥따닥 · 글자 크기 작은 것 · 안 보이는 것 — 전문가가 만든 걸로") ──────────
       브라우저 실측(2026-10-01 · 1440px · 글자 요소 2,662개): 12px 651(24%) · 13px 1,007(38%) · 16px 760 — 글자의
       62% 가 13px 이하였다. 흐린 글자 20곳은 전부 Streamlit 캡션(156개)이 불투명도 60% 로 그려져 4.37:1 이었다. */
    /* ① 제목 안 span — Streamlit 은 제목 글자를 span 으로 감싸는데 옛 층의 전역 `span {{ font-size:16px }}` 가
          그 span 을 눌러 **40px 대제목이 16px** 로 나오고 있었다. 크기를 적지 않은 span 은 제목 크기를 따른다. */
    .stApp :is(h1, h2, h3, h4, h5, h6) span:not([style*="font-size"]) {{ font-size: inherit !important; }}
    /* ② 바닥 13px — 12px 로 적힌 글자는 13px 로(스케일 안의 다음 단) */
    .stApp [style*="font-size:12px"], .stApp [style*="font-size: 12px"] {{ font-size: 13px !important; }}
    /* ③ 본문 문단 — 13px 로 적힌 **문단·항목**은 15px(표 칸·칩·꼬리표 같은 span 은 그대로 13) */
    .stMain p[style*="font-size:13px"], .stMain p[style*="font-size: 13px"],
    .stMain li[style*="font-size:13px"], .stMain li[style*="font-size: 13px"] {{
        font-size: 15px !important; line-height: 1.6 !important; }}
    /* ④ 캡션 — 불투명도 60% 를 걷고 글자 3단(모든 면에서 6:1 이상)으로 · 본문에서는 15px */
    .stApp [data-testid="stCaptionContainer"] {{ opacity: 1 !important; }}
    .stApp [data-testid="stCaptionContainer"] p {{ color: {t['tx3']} !important; }}
    .stMain [data-testid="stCaptionContainer"] p {{ font-size: 15px !important; line-height: 1.6 !important; }}
    /* ⑤ 지표 값이 말줄임으로 잘렸다(예: '35,488,337원' — 실측 3곳) — 줄을 넘기되 자르지 않는다 */
    .stApp [data-testid="stMetricValue"], .stApp [data-testid="stMetricValue"] * {{
        font-size: 28px !important; overflow: visible !important; text-overflow: clip !important;
        white-space: normal !important; line-height: 1.2 !important; }}
    .stApp [data-testid="stMetricLabel"] p {{ font-size: 15px !important; color: {t['tx2']} !important; }}
    /* ⑥ 사이드바 버튼 글자가 두 줄로 꺾였다('최근 목록 비 / 우기') — 한 줄로, 여백을 조금 줄여서 */
    section[data-testid="stSidebar"] .stButton > button {{ padding: 6px 14px !important; }}
    section[data-testid="stSidebar"] .stButton > button p {{ white-space: nowrap !important; }}

    /* 사이드바 머리 — 로고를 접기 버튼 줄로 끌어올린다(사용자: "사이드바 오른쪽 위에 너무 비워져 있어").
       종전엔 머리줄 60px(빈 로고 자리 + 오른쪽 접기 버튼) 아래 빈 style 칸 둘(각 16px 간격)을 지나 108px 에서야
       로고가 시작했다. ① style 만 든 칸은 숨긴다(숨겨도 규칙은 먹는다) ② 로고 줄을 머리줄 위로 올리고
       머리줄보다 위에 그린다 — 머리줄은 R122 대로 sticky · 불투명 그대로라 접기 버튼이 스크롤에도 남는다. */
    section[data-testid="stSidebar"] [data-testid="stElementContainer"]:has(style):not(:has(:is(p, a, span, img, svg, button, input, textarea, iframe, label, table, h1, h2, h3, h4))) {{
        display: none !important; }}
    /* 본문도 같다 — style 만 든 칸 115개(실측)가 각각 16px 간격을 먹어 같은 종류의 줄 사이 틈이 16·40px 으로
       들쭉날쭉했다(예: '추천 제외' 와 다음 접는 칸). 숨겨도 규칙은 먹는다. 보이는 것이 하나라도 있으면 안 숨긴다. */
    .stMain [data-testid="stElementContainer"]:has(style):not(:has(:is(p, a, span, img, svg, button, input, textarea, iframe, label, table, h1, h2, h3, h4, canvas, video))) {{
        display: none !important; }}
    /* 아무것도 안 그린 열 줄(st.columns 가 비었을 때 · 높이 0)도 간격 16px 을 먹었다 — 같은 조건으로 숨긴다 */
    .stMain div:has(> [data-testid="stHorizontalBlock"]):not(:has(:is(p, a, span, img, svg, button, input, textarea, iframe, label, table, h1, h2, h3, h4, canvas, video))) {{
        display: none !important; }}
    /* 접는 칸의 아래 여백 12px 이 줄 간격(16px)에 더해져 28px 이 됐다 — 간격은 줄 간격 하나로 */
    .stApp [data-testid="stExpander"] {{ margin-bottom: 0 !important; }}
    section[data-testid="stSidebar"] div[data-testid="stSidebarHeader"] {{
        background: {nav} !important; }}
    section[data-testid="stSidebar"] [data-testid="stElementContainer"]:has(.gm-logo) {{
        position: relative; z-index: 75; margin-top: -64px; pointer-events: none; }}
    /* 줄 전체가 머리줄 위에 있으므로 오른쪽 접기 버튼을 가리지 않게 — 누르는 것은 로고뿐이다 */
    section[data-testid="stSidebar"] .gm-logo {{
        pointer-events: auto; display: inline-flex !important; width: fit-content; }}
    section[data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] button {{
        background: {t['raised']} !important; border-radius: 999px !important; }}

    /* 제목 — 옛 다크 층이 박은 흰색(#ffffff) 대신 글자 1단 · 제미나이는 굵기를 덜 쓴다 */
    .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6 {{
        color: {t['tx1']} !important; font-weight: 500 !important; }}
    .stApp [data-testid="stMetricValue"] {{ color: {t['tx1']} !important; }}

    /* 표면 — 납작하게(그림자·들뜸 없음) · 모서리를 넉넉히 */
    .stApp div[style*="border-radius:14px"], .stApp div[style*="border-radius:16px"],
    .stApp div[style*="border-radius:18px"], .stApp div[style*="border-radius:20px"] {{
        border-radius: 20px !important; box-shadow: none !important; }}
    .stApp div[style*="border-radius:14px"]:hover {{ transform: none !important; }}

    /* 접는 칸 */
    .stApp [data-testid="stExpander"] {{
        background: {t['card']} !important; border: none !important;
        border-radius: 20px !important; }}
    .stApp [data-testid="stExpander"] summary {{
        font-weight: 500 !important; border-radius: 20px !important; }}
    .stApp [data-testid="stExpander"] summary:hover {{ background: {t['raised']} !important; }}

    /* 알림 — 테두리 대신 의미색을 옅게 섞은 면 */
    .stApp [data-testid="stAlert"] {{
        background: color-mix(in srgb, {t['brand']} 10%, {t['card']}) !important;
        border: none !important; border-radius: 16px !important; }}
    .stApp [data-testid="stAlert"]:has([data-testid="stAlertContentSuccess"]) {{
        background: color-mix(in srgb, {t['pos']} 10%, {t['card']}) !important; }}
    .stApp [data-testid="stAlert"]:has([data-testid="stAlertContentWarning"]) {{
        background: color-mix(in srgb, {t['warn']} 12%, {t['card']}) !important; }}
    .stApp [data-testid="stAlert"]:has([data-testid="stAlertContentError"]) {{
        background: color-mix(in srgb, {t['neg']} 10%, {t['card']}) !important; }}

    /* 버튼 — 보조는 채운 알약, 주요는 브랜드 채움(글자 on_brand · 7.5 / 6.4) */
    .stApp .stButton > button, .stApp [data-testid="stDownloadButton"] button,
    .stApp [data-testid="stFormSubmitButton"] button {{
        border-radius: 999px !important; border: none !important;
        background: {t['raised']} !important; font-weight: 500 !important;
        box-shadow: none !important; }}
    .stApp .stButton > button, .stApp .stButton > button * {{ color: {t['tx1']} !important; }}
    .stApp .stButton > button:hover {{
        background: color-mix(in srgb, {t['tx1']} 8%, {t['raised']}) !important; }}
    .stApp .stButton > button:hover * {{ color: {t['tx1']} !important; }}
    .stApp button[data-testid="stBaseButton-primary"], .stApp button[kind="primary"] {{
        background: {t['brand']} !important; border: none !important; }}
    .stApp button[data-testid="stBaseButton-primary"],
    .stApp button[data-testid="stBaseButton-primary"] *,
    .stApp button[kind="primary"], .stApp button[kind="primary"] * {{
        color: {t['on_brand']} !important; }}
    .stApp button[data-testid="stBaseButton-primary"]:hover,
    .stApp button[kind="primary"]:hover {{
        background: color-mix(in srgb, {t['brand']} 88%, {t['tx1']}) !important; }}
    /* 위의 '보조 버튼 hover → tx1' 규칙(0,3,1)이 주요 버튼 글자(0,2,1)를 이기면 다크에서 밝은 파랑 위
       밝은 글자가 된다 — 주요 버튼의 hover 글자를 같은 무게로 한 번 더 적는다 */
    .stApp button[data-testid="stBaseButton-primary"]:hover *,
    .stApp button[kind="primary"]:hover * {{ color: {t['on_brand']} !important; }}

    /* 입력 — 채운 면 · 둥근 모서리 · 초점만 브랜드 */
    .stApp [data-baseweb="input"], .stApp [data-baseweb="textarea"],
    .stApp [data-baseweb="select"] > div {{
        background: {t['raised']} !important; border-radius: 12px !important;
        border-color: transparent !important; }}
    .stApp [data-baseweb="input"]:focus-within,
    .stApp [data-baseweb="textarea"]:focus-within {{ border-color: {t['brand']} !important; }}
    [data-testid="stSidebar"] input[aria-label*="종목명"] {{
        background-color: {t['card']} !important; color: {t['tx1']} !important;
        border: 1px solid {t['brand']} !important; box-shadow: none !important;
        border-radius: 999px !important; padding: 12px 18px !important; }}
    [data-testid="stSidebar"] input[aria-label*="종목명"]::placeholder {{
        color: {t['tx3']} !important; }}
    [data-testid="stSidebar"] input[aria-label*="종목명"]:focus {{
        box-shadow: 0 0 0 3px color-mix(in srgb, {t['brand']} 35%, transparent) !important; }}
    [data-testid="stSidebar"] [data-baseweb="select"] * {{ color: {t['tx1']} !important; }}
    .stApp [data-testid="stChatInput"] {{
        background: {t['card']} !important; border-radius: 28px !important;
        border: 1px solid {t['line']} !important; }}
    /* 대화 얼굴 — Streamlit 기본은 주황(#FF8700 · 팔레트 밖)인데 옛 층이 아이콘을 밝은 글자색으로 칠해 다크에서
       대비 1.88 이었다(브라우저 실측 · 이 화면의 유일한 미달). 브랜드 면 + on_brand(7.5 · 6.4) / 올린 면 + tx1 */
    .stApp [data-testid="stChatMessageAvatarAssistant"] {{ background: {t['brand']} !important; }}
    .stApp [data-testid="stChatMessageAvatarAssistant"] * {{ color: {t['on_brand']} !important; }}
    .stApp [data-testid="stChatMessageAvatarUser"] {{ background: {t['raised']} !important; }}
    .stApp [data-testid="stChatMessageAvatarUser"] * {{ color: {t['tx1']} !important; }}

    /* 탭 — 알약 · 선택은 옅은 파랑 면(sel_bg · sel_tx) */
    .stApp .stTabs [data-baseweb="tab-list"] {{
        background: transparent !important; gap: 8px !important; padding: 0 !important; }}
    .stApp .stTabs [data-baseweb="tab"] {{
        border-radius: 999px !important; padding: 0 16px !important; height: 38px !important;
        background: {t['card']} !important; color: {t['tx2']} !important;
        font-weight: 500 !important; }}
    .stApp .stTabs [aria-selected="true"] {{
        background: {t['sel_bg']} !important; color: {t['sel_tx']} !important; }}
    .stApp .stTabs [aria-selected="true"] * {{ color: {t['sel_tx']} !important; }}
    .stApp .stTabs [data-baseweb="tab-highlight"],
    .stApp .stTabs [data-baseweb="tab-border"] {{ display: none !important; }}

    /* 사이드바 — 경계선 없이 면으로만 · 항목은 알약 */
    [data-testid="stSidebar"] {{ background-color: {nav} !important; border-right: none !important; }}
    /* 사이드바 버튼 — web_app 의 사이드바 블록('사이드바 버튼 CSS 는 이 한 곳')이 (0,2,3)으로 위 버튼 규칙을
       이기므로 한 단계 더 구체적으로 적는다. 아코디언 줄과 홈 버튼은 **빼고**(투명 · 선택 알약은 acc_css) */
    .stApp section[data-testid="stSidebar"] div[data-testid="stButton"] > button:not([data-testid="stBaseButton-primary"]):not([class*="st-key-_acc_"] *):not(.st-key-btn_home *) {{
        background: {t['raised']} !important; color: {t['tx1']} !important;
        border: none !important; border-radius: 999px !important; }}
    .stApp section[data-testid="stSidebar"] div[data-testid="stButton"] > button:not([data-testid="stBaseButton-primary"]):not([class*="st-key-_acc_"] *):not(.st-key-btn_home *):hover {{
        background: color-mix(in srgb, {t['tx1']} 8%, {t['raised']}) !important; }}
    .stApp section[data-testid="stSidebar"] div[data-testid="stButton"] > button:not([data-testid="stBaseButton-primary"]):not([class*="st-key-_acc_"] *):not(.st-key-btn_home *) * {{
        color: {t['tx1']} !important; }}
    .stApp section[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"] {{
        background: {t['brand']} !important; border: none !important; border-radius: 999px !important; }}
    .stApp section[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"],
    .stApp section[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"] * {{
        color: {t['on_brand']} !important; }}
    .stApp section[data-testid="stSidebar"] .st-key-btn_home button:hover {{
        background: {t['raised']} !important; color: {t['tx1']} !important; }}
    a.qnav-item:hover, a.qnav-sub:hover {{ background: {t['raised']} !important; }}

    /* 상단 바 — 엔진 상태·버전·업데이트·보는 중(라운드 399 · 사용자: "요기에 예전처럼 엔진정보 넣자").
       바탕은 본문과 같은 면(붙어서 따라올 때 아래 글자가 비치지 않게). 오른쪽 여백은 16px 뿐이다 — 이 앱의
       머리줄에는 오른쪽 메뉴 버튼이 없다(브라우저 실측 · 자식 0개). 종전 120px 은 줄만 더 꺾었다. */
    .qnav {{ background: {t['bg']} !important; padding: 10px 16px 10px 4px !important;
        row-gap: 6px !important; border-radius: 0 !important; }}
    /* 배포 환경(Streamlit Cloud)은 머리줄 오른쪽 도구 줄(stToolbar)에 아이콘을 그릴 수 있다 — 이 PC 에서는 못 잰다
       (여기서는 도구 줄이 아예 없다). 그 줄에 누를 것이 **실제로 있을 때만** 오른쪽을 비워 첫 줄 오른쪽 글자('보는
       중')가 그 아래 깔리지 않게 한다. 주의 — 첫 판은 '머리줄 안의 버튼'으로 걸었는데 사이드바를 접으면 펼침 버튼이
       머리줄 **왼쪽**에 들어와 조건이 켜졌다 — 도구 줄로 좁혀도 같았다(펼침 버튼이 도구 줄 **안**의 `<button
       data-testid="stExpandSidebarButton">` 다 · 브라우저 실측). 그 버튼만 빼고 센다 */
    .stApp:has([data-testid="stToolbar"] :is(button, a):not([data-testid="stExpandSidebarButton"])) .qnav {{
        padding-right: 160px !important; }}
    /* 사이드바를 접으면 펼침 버튼(x 18~46 · 실측)이 첫 줄 글자 머리(x 44)를 덮는다 — 그때만 왼쪽을 비운다 */
    .stApp:has([data-testid="stExpandSidebarButton"]) .qnav {{ padding-left: 24px !important; }}
    .qnav a {{ border-radius: 999px !important; }}
    /* 두 줄로 정돈 — 첫 줄: 상태·판단 수(왼쪽) · 업데이트·보는 중(오른쪽), 둘째 줄: 엔진 축 버전 칩 7개.
       종전엔 칩 덩어리(926px)가 줄 가운데서 꺾여 네 줄(119px)이 됐다(브라우저 실측) */
    .qnav .qchips {{ order: 2; flex-basis: 100%; }}
    .qnav .qupd {{ margin-left: auto; }}
    /* '보는 중' — 옛 층이 클래스로 12px 을 적어 인라인만 보는 13px 바닥 규칙을 빠져나갔다(브라우저 실측).
       둘째 줄 칩의 글자는 인라인 12px 이라 바닥 규칙이 이미 13px 로 올린다(측정한 화면에 12px 글자 0) */
    .qnav .here {{ margin-left: 12px !important; font-size: 13px !important; }}
    /* 휴대폰·태블릿(킷 전역의 모바일 구간 768px 그대로) — 상단 바가 sticky 라 칩 일곱이 여러 줄로 꺾인 채 **206px(375px
       화면 높이의 25%)** 를 늘 덮었다(브라우저 실측). 칩 줄은 한 줄로 가로로 밀고, 바는 붙어 따라오지 않게 한다 — 엔진
       정보는 맨 위에서 한 번 보면 되는 참고 정보다('보는 중'은 이 구간에서 이미 숨는다). */
    @media (max-width: 768px) {{
        .qnav {{ position: static !important; }}
        /* 셀렉터를 한 단계 더 구체적으로 — web_app 의 `.qnav a.qvers {{ white-space: normal !important }}`(0,2,1)가
           첫 판의 `.qnav .qchips`(0,2,0)를 이겨 칩이 여전히 여러 줄로 꺾였다(브라우저 실측 · 129px) */
        .qnav a.qvers.qchips {{ white-space: nowrap !important; overflow-x: auto !important;
            scrollbar-width: none; -webkit-overflow-scrolling: touch; }}
        .qnav a.qvers.qchips::-webkit-scrollbar {{ display: none; }}
    }}

    /* 제미나이 서명 — 큰 굵은 글자에만 (GEMINI_GRADIENT 주석) */
    .gm-grad {{ background: {GEMINI_GRADIENT}; -webkit-background-clip: text;
        background-clip: text; -webkit-text-fill-color: transparent; }}
    """


# ── 추천 카드 ────────────────────────────────────────────────────────────
# 시안: scratchpad/gaeum-card-spec.html
#
# 설계 원칙 (하나라도 어기면 사용자가 값을 잘못 읽는다):
#   1. 가격 네 줄은 **늘 같은 순서·같은 자리** — 현재가 → 권장 → 목표 → 손절.
#      카드마다 순서가 바뀌면 눈이 매번 다시 읽어야 한다.
#   2. 값 아래에 **어느 기준인지** 붙인다. 기준이 다른 값이 한 표에 서도
#      섞여 읽히지 않게 하는 유일한 방법이다.
#   3. 권장가가 멀면(2σ 초과) 목표·손절을 흐리게 — 닿지 않을 값을 진하게 두면
#      실행 가격처럼 보인다.
#   4. 진입 기준이 없으면 목표·손절을 **아예 감춘다**. 참고값을 실행 가격
#      자리에 두지 않는다.
#   5. 보유자 기준은 카드에 섞지 않고 경고 상자로 한 줄만.
#   6. 테두리 없음 — 상태는 상단 3px 스트라이프로만 (§78).

def _won(v, na='—'):
    try:
        return f"{float(v):,.0f}원"
    except (TypeError, ValueError):
        return na


def _price_row(icon, label, value, basis='', color=None, muted=False,
               big=False, theme='dark'):
    t = tokens(theme)
    col = t['tx3'] if muted else (color or t['tx1'])
    ic = _icon(icon, t['tx3'] if muted else (color or t['tx2']), 17)
    sub = (f"<span style='display:block; font-size:12px; font-weight:400; "
           f"color:{t['tx3']}; margin-top:1px;'>{_esc(basis)}</span>"
           if basis else '')
    return (
        f"<div style='display:contents;'>"
        f"<div style='padding:7px 0;'>{ic}</div>"
        f"<div style='padding:7px 0; font-size:12px; color:{t['tx2']}; "
        f"white-space:nowrap;'>{_esc(label)}</div>"
        f"<div style='padding:7px 0; text-align:right; white-space:nowrap; "
        f"font-size:{17 if big else 15}px; "
        f"font-weight:{400 if muted else 700}; color:{col}; "
        f"font-variant-numeric:tabular-nums;'>{value}{sub}</div>"
        f"</div>")


def _why_row(icon, text, color=None, theme='dark'):
    t = tokens(theme)
    return (f"<div style='display:flex; align-items:center; gap:7px;'>"
            f"{_icon(icon, color or t['tx3'], 16)}"
            f"<span>{_esc(text)}</span></div>")


# ── 가치 프리미엄 — 진입가가 적정가보다 얼마나 비싼가 (라운드 133) ────
#
# 사용자 지적: *"대우건설·현대건설을 추천해 줬는데 적정가보다 매수가가
# 높아서 선뜻 못 사겠다."* 화면을 보니 원인이 분명했다 —
# **추천 카드에 가치 정보가 한 줄도 없다.** 카드에는
# `권장 매수가 16,002원 (-7.5%)` 만 있어서 싸 보이는데, 상세로 들어가면
# 적정가가 그보다 아래다. 두 화면이 서로 다른 인상을 준다.
#
# 라운드 56 이 상세 배너에 이미 같은 계산을 넣어 뒀는데(인라인),
# 카드에는 없었고 계산도 web_app 안에 박혀 있었다. **한 곳으로 옮긴다**
# (§4 — 경로가 둘이면 한쪽만 고치는 일이 생긴다).
#
# ⚠️ 표시 전용이다. 판정·게이트·문턱에 **쓰지 않는다** —
#   라운드 28b 가 적정가 구간이 성과를 유의하게 가르지 못한다고 이미
#   측정했다(`verdict_core` 과열 판정 주석). 등급처럼 보이는 다단 구간을
#   새로 만들지 않는 이유도 그것이다.
#
# 갈래는 **라운드 56 이 이미 채택한 ±3%** 를 그대로 쓴다. 새 문턱을
# 감으로 만들지 않는다 (§2 — 가능하면 채택된 구간 규칙을 재사용한다).
VALUE_NEAR_PCT = 3.0


def value_premium(entry, fair):
    """(진입가 ÷ 적정가 − 1). 둘 중 하나라도 없으면 None — 지어내지 않는다.

    반환: dict(pct, kind, kind_ko, line)
      · kind 'trend'  — 적정가보다 비싼 자리 (추세를 사는 것)
      · kind 'value'  — 적정가보다 싼 자리
      · kind 'near'   — 거의 같은 자리
    """
    try:
        e, f = float(entry), float(fair)
    except (TypeError, ValueError):
        return None
    if not (e > 0 and f > 0):
        return None
    pct = (e / f - 1.0) * 100.0
    if pct >= VALUE_NEAR_PCT:
        kind, ko = 'trend', '추세형'
        line = (f"가치가 싸서 고른 자리가 아닙니다 — 매수가가 적정가보다 "
                f"{pct:+.1f}% 위입니다.")
    elif pct <= -VALUE_NEAR_PCT:
        kind, ko = 'value', '가치형'
        line = (f"가치로 봐도 싼 자리입니다 — 매수가가 적정가보다 "
                f"{pct:+.1f}% 아래입니다.")
    else:
        kind, ko = 'near', '중립'
        line = f"적정가와 거의 같은 자리입니다 ({pct:+.1f}%)."
    return dict(pct=round(pct, 1), kind=kind, kind_ko=ko, line=line)


def value_premium_basis(vp, asset_only):
    """라운드 382 — 적정가가 **자산 기반 모형으로만** 섰으면 '가치로 봐도 싼'을 '장부가로 보면 싼'으로 좁힌다.

    라운드 359 가 같은 사실을 적정가 신뢰도 줄 아래 한 곳에만 적었고, 카드와 상세 배너는 여전히
    *"가치로 봐도 싼 자리입니다"* 라 적었다(외부 검토 · ROE 음수 · EPS 미수신 종목 · 2026-09-29).
    그 적정가는 BPS 배수라 **장부가 대비** 싼지를 말하지 이익 대비 싼지를 말하지 않는다(R237·R239 ·
    이름이 계산보다 넓으면 없는 근거를 있다고 읽는다). 가름은 `model_kinds` 가 하고 여기는 문장만.
    `asset_only` 가 None(못 가름 · 옛 리포트)이면 **그대로 둔다** — 모르는 것을 한쪽으로 몰지 않는다(§3).
    수·갈래(kind)·문턱 불변 — 문장과 짧은 이름만.
    """
    if not vp or asset_only is not True or vp.get('kind') != 'value':
        return vp
    out = dict(vp)
    out['kind_ko'] = '장부가 기준'
    out['line'] = (f"장부가로 보면 싼 자리입니다 — 매수가가 적정가보다 {vp['pct']:+.1f}% 아래입니다. "
                   f"이 적정가는 자산 기반 모형으로만 서서 이익 대비 싼지는 말하지 않습니다.")
    return out


#: 라운드 383 — 스캔 제외 사유의 **문장 머리**(`quant_indicators.run_screener_scan` 이 만든다 · 읽기만).
#:   채택된 유동성 하한은 실패가 아니라 규칙이고, 두 출처 시세 불일치는 못 믿어서 뺀 것이며, 나머지는
#:   예외(시세·계산 오류)다. 머리 글자가 엔진 문장과 같은지는 회귀가 잠근다(R221·R327 의 방식).
SCAN_RULE_HEAD = '20일 평균 거래대금 '
SCAN_XCHECK_HEAD = '시세 교차검증 실패'


def scan_failure_kind(reason):
    """스캔 제외 사유 한 줄 → 'rule'(채택된 하한) · 'xcheck'(두 출처 불일치) · 'error'(그 밖 · 예외)."""
    s = str(reason or '')
    if s.startswith(SCAN_RULE_HEAD):
        return 'rule'
    if s.startswith(SCAN_XCHECK_HEAD):
        return 'xcheck'
    return 'error'


def scan_status_line(tried_at, ok_at, outcome, n_att=0, n_deep=0):
    """사이드바 '최신화' 아래 상태 한 칸 — **시도와 성공을 가른다** (라운드 383). 반환 (갈래, 마크다운).

    ■ 왜 (라운드 376 이 미룬 사용자 제안 · 2026-09-29 확인)
      완료 시각을 `finally:` 에서 찍어, 스캔이 **예외로 죽거나 후보를 하나도 못 받아도** *"최신화 완료 ·
      HH:MM:SS"* 가 나갔다. 화면 아래의 스캔 결과는 **옛 성공**의 것인데 방금 새로 잰 것처럼 읽혔다(§3).
      갈래: 'fail'(예외 · 사유와 마지막 성공 시각) · 'empty'(후보 0 · 사유) · 'partial'(끝까지 갔지만 분석
      실패·출처 불일치로 빠진 후보가 있다) · 'ok'. 채택된 유동성 하한으로 빠진 것은 실패로 세지 않는다.
      사유가 길면 자르되 **잘랐다고 표시한다**(…) — 전체는 본문 요약 줄과 서버 로그에 있다(R314).
    """
    o = outcome or {}
    kind = o.get('kind')
    why = str(o.get('reason') or '사유 미기록')
    if len(why) > 140:
        why = why[:139] + '…'
    last_ok = (f"화면의 스캔 결과는 마지막 성공(**{ok_at}**) 것입니다." if ok_at
               else "이 세션에서 끝까지 간 최신화는 아직 없습니다.")
    if tried_at and kind == 'fail':
        return 'fail', f"**최신화 실패** · {tried_at} — {why}  \n{last_ok}"
    if tried_at and kind == 'empty':
        return 'empty', f"최신화 · {tried_at} — **후보 0개**: {why}"
    if tried_at and kind == 'ok':
        n_err = int(o.get('n_err') or 0)
        n_x = int(o.get('n_xcheck') or 0)
        tail = []
        if n_err:
            tail.append(f"분석 실패 {n_err}개")
        if n_x:
            tail.append(f"두 출처 시세 불일치로 뺀 {n_x}개")
        head = ("**최신화 부분 완료**" if tail else "최신화 완료") + f" · **{tried_at}**"
        return ('partial' if tail else 'ok'), (
            f"{head}  \n관심종목 {n_att}개 · 정밀분석 {n_deep}개"
            + (f"  \n{' · '.join(tail)} — 사유는 본문 요약 줄" if tail else ''))
    return None, ''


def distribution_vs_stop(price, stop, div, month_now):
    """라운드 385 — **매달 분배금이 나가는 ETF** 에서 가격과 손절선의 차이가 한 달치 분배금 평균 안이면 한 문장. 아니면 ''.

    ■ 왜 (사용자: *"진짜 매도 맞지?"* · 2026-09-29 · 보유 커버드콜 ETF 한 행)
      이 엔진은 가격을 **조정하지 않는다**(라운드 364 · 원시 종가 = 조정 종가). 분배금이 나가는 날 가격이 그만큼
      빠지는데 손절선은 그 가격과 견준다. 그 행은 12개월 분배금 합이 가격의 약 27% 라 한 달 평균이 약 2.2% 이고,
      손절선까지 거리도 그만큼이었다 — **한 번의 분배금만으로 손실 없이 선 아래**로 갈 수 있는 자리다.
      판정은 안 바꾼다(언제 나갔는지를 받지 않아 가를 수 없다 · §3). 사실만 옆에 적는다.
    ■ 문턱 없음 — 두 잰 양(가격과 선의 차이 · 12개월 합 ÷ 12)을 견줄 뿐이다. 매달 나가는지는 올해 지급 횟수가
      지난 달 수 이상인지로 본다(받은 칸 그대로). 못 읽으면 ''(지어내지 않는다).
    """
    try:
        p, s = float(price), float(stop)
        d = div or {}
        dps = float(d.get('dps_ttm'))
        cnt = int(d.get('count_this_year'))
        m = int(month_now)
    except (TypeError, ValueError):
        return ''
    if not (p > 0 and s > 0 and dps > 0) or cnt < max(1, m - 1):
        return ''
    avg = dps / 12.0
    gap = p - s
    if abs(gap) > avg:
        return ''
    head = (f"이 상품은 매달 분배금이 나갑니다(12개월 합 {dps:,.0f}원 · 한 달 평균 약 {avg:,.0f}원). "
            f"분배금이 나가는 날 가격이 그만큼 빠지는데 이 엔진은 분배금을 가격에 되돌려 넣지 않고 손절선과 견줍니다")
    if gap < 0:
        return (f"{head} — 지금 가격이 선보다 {-gap:,.0f}원 아래지만 한 달치 평균보다 작은 차이라, '선 아래' 판정에 "
                f"분배금 몫이 섞여 있을 수 있습니다(언제 나갔는지는 받지 않아 가르지 못합니다 · 판정은 그대로).")
    return (f"{head} — 지금 가격은 선보다 {gap:,.0f}원 위지만 한 달치 평균보다 가까워, 분배금이 나가는 날 "
            f"손실 없이도 선 아래로 갈 수 있습니다.")


def value_row(vp, theme='dark'):
    """가치 프리미엄 한 줄. `value_premium()` 결과를 그대로 받는다."""
    if not vp:
        return ''
    t = tokens(theme)
    col = {'trend': t['warn'], 'value': t['pos'], 'near': t['tx2']}.get(
        vp['kind'], t['tx2'])
    return (
        f"<div style='display:flex; align-items:flex-start; gap:7px; "
        f"margin-top:9px; padding:8px 10px; background:{t['raised']}; "
        f"border-radius:8px;'>"
        f"{_icon('CircleDollarSign', col, 15)}"
        f"<div style='font-size:12px; line-height:1.5; color:{t['tx2']};'>"
        f"<b style='color:{col};'>{_esc(vp['kind_ko'])} 매수</b> · "
        f"{_esc(vp['line'])}</div></div>")


# ── 본전에 필요한 적중률 — 라운드 161 ────────────────────────────────────
#
# 사용자 지적(다날 064260): *"펀더멘털 적정가가 이런데 추천하면 얼마 못
# 버는 거 아냐?"* 화면을 보니 그 말이 맞았다 —
#
#     비슷했던 과거에서 맞은 비율   60% (n=12,423 · W하한 59%)
#     이 가격에 사면 → 손절 4,356원 · 1차 목표 5,217원 · 손익비 0.7:1
#
# **60% 가 좋은 수인지 나쁜 수인지 화면만 봐서는 알 수 없다.** 실제로는
# 이 구조(0.70:1)에서 본전이 **61.2%** 라 60% 는 이미 마이너스다.
# 라운드 159 가 전수로 잰 값도 같은 자리를 가리킨다 — 원장 전체의
# 목표/손절 중앙이 0.70:1 이고 본전 63.7%, 실전 적중률 50.4%.
#
# 그래서 **적중률 옆에 본전 적중률을 같이 놓는다.** 한쪽만 보여 주는 것은
# §9("성과를 좋게 보이게 쓰지 않는다")에 걸린다.
#
# ⚠️ 표시 전용이다. 판정·게이트·문턱·실행 레벨에 **쓰지 않는다.**
#   목표 배수를 바꾸는 문제는 라운드 160 이 측정만 했고, 채택은
#   2026-11-16 이후 별도 사전등록이다.
#
# 새 숫자를 만들지 않는다 — 진입·손절·목표는 `verdict_core` 가 낸 값을
# 그대로 받고, 비용은 호출부가 채택값(`TOTAL_COST_PCT`)을 넘긴다.
def breakeven_hit_rate(entry, stop, target, cost_pct):
    """본전에 필요한 적중률(%). 목표·손절·비용만으로 정해지는 값.

        p·(목표−진입) − (1−p)·(진입−손절) − 비용 = 0
        →  p = (손절폭 + 비용) / (목표폭 + 손절폭)

    셋 중 하나라도 없거나 방향이 어긋나면 **None** — 지어내지 않는다(§3).
    반환: dict(pct, up_pct, dn_pct, rr)
    """
    try:
        e, s, t = float(entry), float(stop), float(target)
        c = float(cost_pct)
    except (TypeError, ValueError):
        return None
    if not (e > 0 and s > 0 and t > 0):
        return None
    up = (t - e) / e * 100.0
    dn = (e - s) / e * 100.0
    if up <= 0 or dn <= 0:          # 정합이 깨진 값은 그리지 않는다 (§4)
        return None
    pct = (dn + c) / (up + dn) * 100.0
    return dict(pct=round(pct, 1), up_pct=round(up, 2),
                dn_pct=round(dn, 2), rr=round(up / dn, 2))


def breakeven_line(be, observed=None):
    """본전 적중률 한 줄(문구만). `breakeven_hit_rate()` 결과를 받는다.

    실측 적중률을 같이 주면 **모자란 폭까지** 적는다 — 두 수를 나란히
    놓아야 60% 가 좋은 수인지 알 수 있다.

    ⚠️ 실측값을 **반올림 없이 그대로** 적는다. 배지는 `{:.0f}%` 라
    59.7% 가 '60%' 로 보이는데, 차이만 0.6%p 로 적으면 읽는 사람이
    `60 − 60.3 = 0.3` 으로 계산해 어긋난다 — 라운드 131 이 겪은
    "같은 숫자를 두 번 반올림하면 두 곳이 달라진다" 그대로다.
    세 수(실측·본전·차이)가 **서로 검산되게** 한 줄에 같이 놓는다.
    """
    if not be:
        return '', None
    if observed is None:
        return (f"본전에 필요한 적중률 {be['pct']:.1f}% "
                f"(손익비(진입가·1차) {be['rr']:.2f}:1)"), None
    obs = float(observed)
    gap = obs - be['pct']
    tail = (f"{abs(gap):.1f}%p {'넘습니다' if gap >= 0 else '모자랍니다'}")
    return (f"본전에 필요한 적중률 {be['pct']:.1f}% — "
            f"실측 {obs:.1f}% 로 {tail}"), gap


def breakeven_row(be, observed=None, theme='dark'):
    """본전 적중률 한 줄(HTML). 모자라면 경고색, 넘으면 긍정색."""
    txt, gap = breakeven_line(be, observed)
    if not txt:
        return ''
    t = tokens(theme)
    col = t['tx2'] if gap is None else (t['pos'] if gap >= 0 else t['warn'])
    return (f"<p style='margin:4px 0 0 0; font-size:12px; "
            f"color:{col};'>{_esc(txt)}</p>")


# ── 관심종목 한 줄 판단 — 보유 여부까지 본다 (라운드 169) ────────────────
#
# 사용자 요청: *"엔진 판단부터 제대로 되도록 해줘. 지금 보유한 상태에서는
# 더 매수인지 매도인지, 없으면 매수인지."*
#
# ⚠️ **새 판정을 만들지 않는다.** 여기서 하는 일은 엔진이 이미 발표한
#   가격선들과 현재가를 견주어 **한 줄로 다시 말하는 것**뿐이다:
#
#       snap_hold_stop  버틸 수 없는 가격 (보유자 기준 · CORE)
#       snap_hold_trim  팔 가격 1차       (보유자 기준 · CORE)
#       snap_buy        목표 매수가       (신규 매수자 기준 · CORE)
#       snap_bucket     신규 매수 판정    (verdict_core.bucket 그대로)
#
#   새 문턱·새 계산이 없다. 문턱을 하나라도 만들면 §2 위반이고, 판정을
#   여기서 다시 지으면 §4 위반이다(화면 값은 한 곳에서).
#
# ⚠️ 신규 매수자 값과 보유자 값을 **섞지 않는다** (§4 · 라운드 30 사고).
#   보유 중이면 hold_* 만, 미보유면 bucket·snap_buy 만 본다.
#
#: 보유 중일 때 나올 수 있는 말 — 순서가 곧 우선순위다.
WATCH_HOLD_ACTIONS = ('정리 검토', '일부 정리', '추가 매수 가능', '보유 유지')

#: 라운드 338 — 사용자: *"정리 검토가 팔라는거지? 확실하게 이야기해줘 표현을."* kind 는 **판정의
#:   이름**이라 안 바꾼다(순서표·색 지도·저장 스냅샷·챗이 그 이름으로 잇는다 · R292·R327). 화면과 챗이
#:   **사람에게 보이는 글자**만 이 표에서 받는다 — 무엇을 하라는 말인지가 이름표에 들어간다(R322 의 그 규칙).
#:   '정리 검토'는 현재가가 **버틸 수 없는 가격 아래**라는 뜻이고, 그 선은 잰 날에 고정된 보유 계획의
#:   손절선이다(R224) — 계획대로면 파는 자리다. 새 문턱 없음 · 판정 불변.
HOLD_LABELS = {
    '정리 검토': '매도 — 손절선 아래',
    '일부 정리': '일부 매도 — 1차 매도가 넘음',
    '추가 매수 가능': '추가 매수 가능',
    '보유 유지': '보유 유지',
    '보유 기준 미산출': '보유 기준 미산출',
}


def hold_label(kind):
    """보유 판정 kind → 화면·챗에 보이는 이름표 (한 곳 · §4). 모르는 kind 는 그대로 돌려준다."""
    return HOLD_LABELS.get(kind, kind or '')


def clip_reason(text, width=34):
    """관심종목 표의 사유 한 줄을 칸 폭에 맞게 자른다 — 전체는 툴팁에 있다.

    라운드 327 이 *"낱말 가운데서 끊긴 조각보다 한 문장이 낫다"* 며 첫 문장 끝('다. ')에서 자르게
    했는데, 그 판별이 `find()` 의 **−1(없음)** 을 못 걸렀다 — `0 < -1 + 2` 가 참이라 '다. ' 가 **없는**
    긴 사유는 **첫 글자 하나**만 남았다. 화면 실측(2026-09-18): 미보유 행 여섯이 전부 `유 …`
    (*"유사패턴 …"* 의 첫 글자). 사용자: *"유 … 이게 뭐야?"* 여기 한 곳에 두고 심어서 잰다(R120e).
    """
    s = '' if text is None else str(text)
    if len(s) <= width:
        return s
    cut = s.find('다. ')
    if 0 <= cut and cut + 2 <= width:
        return s[:cut + 2] + ' …'
    return s[:width - 1] + '…'


#: 라운드 371 — 보유 계획이 끝난 사유 한 줄(`portfolio.hold_plan_update` 가 남긴 문장)을 읽는 자리.
#:   사용자: *"관심종목에서는 팔라고 하고 밑에서는 조건이 갖춰지면 후보라는데 뭐가 어떻게 된거야?"*
#:   표는 옛 계획(09-04 손절선)으로 '매도'를 그렸고, 종목을 열자 규칙(닿으면 다시 잼 · R224)이 계획을
#:   오늘 값으로 다시 재 '보유 유지'가 됐다. 그 사이를 잇는 말은 이력 줄에 있었는데 표가 34자로 잘라
#:   *"2026-09-27 버틸 수 없는 가격 6,115원(2026-…"* 까지만 남고 **"→ 정리 검토 · 기준 다시 잼"** 은
#:   툴팁에만 있었다(R301·R312·R314 의 *말없이 자르는 자리*). 문장을 되파싱하므로 생성기 출력을 그대로
#:   넣어 세 갈래가 다 읽히는지 심어서 잰다(§4) — 모르는 문장은 None(지어내지 않는다 · §3).
#: 라운드 373 — 손절선 아래는 이제 두 문장이다: 옛 자동 재측정(`→ 정리 검토 · 기준 다시 잼` · 저장된
#:   이력에 남아 있다)과 **계획 유지**(`→ 계획 유지 · 다시 재기는 사람이`). 그리고 사람이 다시 잰 문장.
#:   꼬리·머리 글자는 `portfolio` 가 정하고 여기서는 **부른다**(§4).
_HOLD_LOG_RX = (
    ('stop_hold', _re.compile(r'^(\d{4}-\d{2}-\d{2}) 버틸 수 없는 가격 ([\d,]+)원\((\d{4}-\d{2}-\d{2}) 기준\) 아래 '
                              r'.*→ 계획 유지')),
    ('stop', _re.compile(r'^(\d{4}-\d{2}-\d{2}) 버틸 수 없는 가격 ([\d,]+)원\((\d{4}-\d{2}-\d{2}) 기준\) 아래 '
                         r'.*→ 정리 검토')),
    ('trim', _re.compile(r'^(\d{4}-\d{2}-\d{2}) 1차 매도가 ([\d,]+)원\((\d{4}-\d{2}-\d{2}) 기준\)을 넘음')),
    ('expiry', _re.compile(r'^(\d{4}-\d{2}-\d{2}) 보유 계획 창\(.*?· (\d{4}-\d{2}-\d{2}) 기준\) 경과')),
    ('manual', _re.compile(r'^(\d{4}-\d{2}-\d{2}) 사람이 기준을 다시 잼 \(옛 버틸 수 없는 가격 ([\d,]+)원 · '
                           r'1차 ([\d,]+)원 · (\d{4}-\d{2}-\d{2}) 기준')),
)


def hold_log_parse(line):
    """보유 계획 이력 한 줄 → `dict(kind, date, old, old_at)` 또는 None.

    kind: 'stop'(옛 자동 재측정 · 손절선 아래) · 'stop_hold'(손절선 아래 · 계획 유지 · 라운드 373) ·
    'trim'(1차 매도가 넘음) · 'expiry'(창 경과 · old 는 None) · 'manual'(사람이 다시 잼 · old 는 옛 손절선).
    """
    s = '' if line is None else str(line).strip()
    for kind, rx in _HOLD_LOG_RX:
        m = rx.match(s)
        if not m:
            continue
        if kind == 'expiry':
            return dict(kind=kind, date=m.group(1), old=None, old_at=m.group(2))
        try:
            old = float(m.group(2).replace(',', ''))
        except ValueError:
            return None
        if kind == 'manual':
            return dict(kind=kind, date=m.group(1), old=old, old_at=m.group(4))
        return dict(kind=kind, date=m.group(1), old=old, old_at=m.group(3))
    return None


def effective_hold_stop(row):
    """보유 판단에 쓸 **버틸 수 없는 가격** — (값, 되살린 이력 또는 None). 라운드 378 · 읽는 쪽만 · 파일 불변.

    2026-09-28 사용자 결정(라운드 373): *손절선을 넘긴 계획은 그대로 둔다* — 다시 재는 것은 사람이 누를 때뿐.
    그 결정 **전에** 옛 규칙(닿으면 다시 잼)이 이미 손절선을 낮춘 행이 있었다(보유 14행 중 3행 · 이력에
    "손절선 N원 넘겨 기준 다시 잼 → 새 손절선 M원"). 라운드 373 은 옛 1차 매도가가 이력에 없어 그 행들을 **되돌리지
    않았고**, 그래서 그 셋은 선을 넘긴 뒤 **낮아진 선** 기준으로 '보유 유지'가 됐다. 사용자: *"왜 보유해야 해?
    계속 떨어지는 거 아냐?"* — 그 '보유 유지'는 새 판단이 아니라 옛 규칙이 선을 내린 결과였다.
    그래서 **지금 계획이 바로 그 자동 재측정으로 만들어진 것이면**(마지막 이력이 옛 규칙의 손절선 재측정이고 그 날짜 =
    잰 날) 판단에는 **이력에 남은 옛 손절선**을 쓴다. 사람이 '기준 다시 재기'를 누르면 마지막 이력이 바뀌어 이 규칙이
    풀린다. 1차 매도가는 옛 값이 이력에 없어 지금 값을 그대로 쓴다(지어내지 않는다 · §3). 새 문턱 없음.
    """
    def _n(v):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return f if f > 0 else None
    r = row or {}
    cur = _n(r.get('snap_hold_stop'))
    log = [x for x in str(r.get('snap_hold_log') or '').split(' | ') if x]
    # 뒤에 붙은 '계획 유지' 줄(라운드 373 이 선 아래에서 한 번 남긴다)은 건너뛴다 — 그 줄은 계획을 바꾸지 않는다.
    #   건너뛰지 않으면 되살린 행이 선 아래에서 한 줄을 남기는 순간 다시 낮춘 선으로 돌아간다(서로를 무른다).
    last = None
    for x in reversed(log):
        pp = hold_log_parse(x)
        if pp and pp.get('kind') == 'stop_hold':
            continue
        last = pp
        break
    at = str(r.get('snap_hold_at') or '')[:10]
    if (last and last.get('kind') == 'stop' and at and last.get('date') == at
            and _n(last.get('old'))):
        return _n(last['old']), last
    return cur, None


def hold_log_short(line, new_stop=None, new_trim=None, today=None, width=34, revived=False):
    """관심종목 표의 이력 한 줄 — 어느 선을 넘겨 다시 쟀고 새 선이 얼마인지. 못 읽는 문장은 종전대로 자른다."""
    p = hold_log_parse(line)
    if not p:
        return clip_reason(line, width)

    def _won(v):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return f"{f:,.0f}원" if f > 0 else None

    when = '오늘' if (today and p['date'] == str(today)[:10]) else p['date'][5:].replace('-', '/')
    if p['kind'] == 'stop':
        if revived:                      # 라운드 378 — 판단은 옛 손절선으로 본다(effective_hold_stop)
            return (f"{when} 손절선 {_won(p['old'])} 넘김 — 옛 계획으로 봄"
                    + (f" (그때 다시 잰 선 {_won(new_stop)}은 '기준 다시 재기'로)" if _won(new_stop) else ''))
        s = f"{when} 손절선 {_won(p['old'])} 넘겨 기준 다시 잼"
        return s + (f" → 새 손절선 {_won(new_stop)}" if _won(new_stop) else '')
    if p['kind'] == 'stop_hold':
        return f"{when} 손절선 {_won(p['old'])} 넘김 — 계획 유지 (다시 재기는 사람이)"
    if p['kind'] == 'manual':
        s = f"{when} 사람이 기준 다시 잼 (옛 손절선 {_won(p['old'])})"
        return s + (f" → 새 손절선 {_won(new_stop)}" if _won(new_stop) else '')
    if p['kind'] == 'trim':
        s = f"{when} 1차 매도가 {_won(p['old'])} 넘어 기준 다시 잼"
        return s + (f" → 새 1차 {_won(new_trim)}" if _won(new_trim) else '')
    return f"{when} 계획 창 지나 기준 다시 잼"


#: `personalize_for_position` 의 6조건 이름 중 화면이 **갈라 읽는** 둘 (라운드 221).
#:   값을 다시 계산하지 않는다 — 스냅샷에 찍힌 실패 목록의 **이름**만 본다.
#:   이름은 `quant_indicators` 의 리터럴과 같아야 하므로 §238 이 그 리터럴을
#:   잠근다 (두 벌이 되면 한쪽이 조용히 어긋난다 · §4).
AVG_DOWN_MARKET_GATE = '신규 진입 조건 통과'
AVG_DOWN_DATA_GATE = '데이터·표본 게이트 통과'
#: 실패 목록이 비었을 때 파일에 남기는 글자 (라운드 224) — 빈 글자('')는 스냅샷 병합이
#:   "못 낸 값"으로 보고 건너뛰어 옛 목록이 살아남는다. 쓰는 쪽(web_app)과 읽는 쪽이
#:   같은 낱말을 쓴다 (§4).
AVG_DOWN_NO_FAIL = '없음'
#: 제외 사유가 **없을 때** 파일에 남기는 글자 (라운드 241). 같은 이유다 — 빈
#:   글자('')는 스냅샷 병합이 "못 낸 값"으로 보고 건너뛰어, 제외가 풀린 행에
#:   **옛 사유가 그대로 남는다**(실측: '오늘 매수 가능' 아래 '추격매수 위험').
#:   쓰는 쪽(web_app 채우기 네 자리)과 읽는 쪽이 같은 낱말을 쓴다 (§4).
WATCH_NO_WHY = '없음'
#: '표본외 성적 미달' 갈래 사유 문장의 머리 (라운드 327) — `verdict_core` 가 그 갈래에 내는 문장이 이것으로
#:   시작한다. R292 이전 스냅샷(옛 이름 '신뢰도·표본 확보 대기')을 같은 가름으로 읽을 때 쓴다(§333 이 잠근다).
OOS_FAIL_WHY_HEAD = '표본외 검증은 마쳤고'
#: 라운드 387 — 중앙 판정이 더는 만들지 않는 두 대기 칸과 그 사유 머리. `verdict_core.WAIT_BUCKETS_RETIRED` ·
#:   `WAIT_NOT_CURED_HEAD` 와 글자까지 같아야 한다(§378 이 잠근다 · 킷은 판정 모듈을 부르지 않는다).
_WAIT_RETIRED = ('눌림목 매수 대기', '돌파 후 매수 대기')
_WAIT_NOT_CURED_HEAD = '진입가·목표·손절이 현재가를 따라 같은 비율로 다시 잡혀,'
#: 라운드 396 — 중앙 판정이 기다림의 이름을 줄 때 사유 앞에 붙이는 머리(`verdict_core.WAIT_ONLY_HEAD` 와 글자까지 같다 ·
#:   회귀가 잠근다). 이 머리가 없는 '… 대기' 스냅샷은 그 규칙 **전**에 찍혀, 기다려도 안 풀리는 조건이 같이 걸렸는지
#:   가르지 않은 판정이다(개장 전 리포트 2026-09-30 실측: 그런 '과열 해소 대기' 40개 전부가 같이 걸려 있었다).
_WAIT_ONLY_HEAD = '기다리면 풀릴 수 있는 조건만 남았습니다 — '
_WAIT_NAMED = ('과열 해소 대기', '거래량 회복 대기', '시장 국면 회복 대기', '신뢰도·표본 확보 대기')
_WAIT_UNSORTED = '옛 규칙 판정(안 풀리는 조건을 안 가림) — 다시 재면 가려집니다. '


def avg_down_class(ok, fails):
    """물타기 판정을 **넷으로 가른다** (라운드 221 · 사용자: "진짜 다 불가야?").

    실측(2026-09-04 · 보유 16행): 16행 **전부**가 같은 조건 하나('신규 진입
    조건 통과')에 걸렸고, 나머지 다섯 조건은 행마다 달랐다(10·4·4·1건).
    원장 250,725건 중 신규 매수 제목은 4건 — 그 게이트는 사실상 늘 닫혀 있어
    그것을 **요구하는** 물타기도 늘 '불가'다. 계산은 맞지만 '불가' 한 낱말이
    셋을 뭉뚱그렸다: ① 시장 게이트 하나에만 막힌 것(포지션 조건 5개는 통과)
    ② 포지션 조건 미달 ③ 표본·데이터 게이트를 못 넘어 **판단하지 않은** 것.
    ③은 불가가 아니라 미판정이다(§3 — 못 잰 것 ≠ 판단). 같은 줄에서 왜
    막혔는지 말한다(§4 · R214 의 `_sig_class` 와 같은 모양).

    반환 `(cls, label, why)` — cls ∈ {'가능','보류','시장게이트','포지션미달'} | None.
    새 문턱 없음 — 이름만 읽는다.
    """
    # 라운드 322 — 사용자: *"보유 유지 물타기 불가 · 신규 매수 판정만 이게 뭐고 · 보유 유지 물타기
    #   가능 이게 뭐야 · 쉽게."* 이름표를 **무엇을 하라는 말인지**로 바꿨다(등급 cls·규칙·이유 문장
    #   불변). '물타기 가능'은 *조건을 통과했다*는 뜻이지 *지금 사라*가 아니었는데(진입가 위면 kind 는
    #   '보유 유지') 낱말만 보면 지금 사라로 읽혔다 — '추가매수 조건 통과'로 적고, 가격은 표의 짧은
    #   줄(`avg_down_short`)이 말한다.
    _fail = [str(s).strip() for s in (fails or []) if str(s).strip()]
    if ok is None:
        return None, None, '아직 안 잼'
    if ok:
        return '가능', '추가매수 조건 통과', '6조건 전부 통과'
    if AVG_DOWN_DATA_GATE in _fail:
        return ('보류', '추가매수 판단 보류',
                '표본·데이터 게이트를 넘지 못해 판단하지 않았습니다 — 불가가 아니라 미판정입니다')
    if _fail == [AVG_DOWN_MARKET_GATE]:
        # 라운드 224 — 첫 조건의 출처가 TOP3 깃발에서 **중앙 판정**(verdict_core.actionable)
        #   으로 바뀌었다. 사전등록 R224: 직전 관측 대비 하락 중인 매수권 케이스의
        #   적중률 차가 세 구간 CI95 모두 0 을 포함(train +1.7 · valid +3.9 · blind
        #   −5.8%p) — 하락 중이라는 사실이 판정을 바꾼다는 증거가 없어 물타기의
        #   첫 조건 = 신규 매수 판정이다. 5%p 미만은 이 잣대로 못 본다(R113).
        # 라운드 322 — 사용자: *"물타기 불가 · 신규 매수 판정만 진짜 쉽게 설명 써줘."* 이유 문장을
        #   **처음 사는 사람 기준**으로 풀어 쓴다(규칙·등급 불변 · 출처 낱말 '신규 매수 판정'은 남긴다).
        return ('시장게이트', '추가매수 안 함 · 지금은 새로 살 때 아님',
                '이 종목을 오늘 처음 산다고 해도 엔진이 사라고 하지 않는 상태라, 더 사는 것(물타기)도 '
                '권하지 않습니다. 가격·손절선 같은 나머지 조건 5개는 괜찮습니다 — 엔진이 신규 매수 판정을 '
                '사도 된다로 바꾸는 날 추가매수 가능으로 바뀝니다 '
                '(실측: 떨어지고 있다는 사실만으로 판단이 좋아진다는 증거는 없었습니다)')
    # 앞 셋만 적고 나머지는 '외 N' — 자르기는 슬라이스로 한다. 비교식에
    # 숫자를 두면 §2 문턱 검사(watch_action 안 Compare 의 숫자)에 걸린다.
    _head, _more = _fail[:3], _fail[3:]
    _why = ('미충족: ' + ' · '.join(_head)
            + (f' 외 {len(_more)}' if _more else '')) if _fail else '조건 미충족'
    return '포지션미달', '추가매수 안 함', _why


def holder_kind(px, hold_stop, hold_trim, buy=None, avg_down_ok=None):
    """보유자 행동 판정 — **이 저장소에서 유일한 자리**. `(kind, why)` 또는 `(None, 사유)`.

    ⚠️ 라운드 304 — 사용자가 붙여 넣은 분석문이 짚었다: *"`_ans_holder()` 에는 수익률
    구간에 따라 '보유 유지'·'물타기 금지'·'비중 축소 검토' 문장을 **자체적으로 선택하는
    분기**가 있습니다. 이 결과가 중앙 보유자 판정과 항상 일치하는지 확인해야 합니다."*

    **세어 보니 어긋났다.** 격자 120칸에서 **64칸(53%)** 이 다른 답이었고, 가장 나쁜
    갈래는 중앙이 **'정리 검토'** 인데 챗이 **'보유 유지'** 라고 하는 **32칸**이다
    (평단이 낮아 수익 중이면 챗은 무조건 유지라고 했다). 챗은 **평단 대비 수익률**
    (+5/0/−7 · 저장소 어디에도 없는 손으로 고른 수 · §2)로 고르고, 중앙은 **가격선
    위치**(버틸 수 없는 가격 · 1차 매도가 · 진입가 · 물타기 6조건)로 고른다 — 재는
    것이 처음부터 달랐다. R193·R246 의 *"화면도 판정자다"* 가 채팅 화면에 남아 있었다.

    분기는 `watch_action` 의 것을 **그대로** 옮겼다 — 새 문턱 없음 · 판정 불변.
    `avg_down_ok` 를 모르면(None) '추가 매수 가능'은 **주장하지 않는다**(§3).
    """
    def _n(v):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return f if f > 0 else None

    px, h_stop, h_trim, buy = _n(px), _n(hold_stop), _n(hold_trim), _n(buy)
    if not px:
        return None, '현재가를 모르면 보유 판단을 하지 않습니다'
    # 보유자 가격선이 하나도 없으면 **판단하지 않는다** (R214 의 그 자리)
    if not (h_stop or h_trim):
        return ('보유 기준 미산출',
                '이 종목의 보유자 기준값(버틸 수 없는 가격·팔 가격 1차)을 아직 '
                '안 냈습니다 — 채우면 판단합니다')
    if h_stop and px <= h_stop:
        # 라운드 338 — "팔라는 거지?" 에 문장이 답한다: 그 선은 보유 계획의 손절선이다.
        return ('정리 검토',
                f'현재가가 버틸 수 없는 가격({h_stop:,.0f}원) 아래입니다 — '
                f'계획대로면 파는 자리입니다')
    if h_trim and px >= h_trim:
        return ('일부 정리',
                f'1차 매도가({h_trim:,.0f}원)를 넘었습니다 '
                f'({(px / h_trim - 1) * 100:+.1f}%) — 계획대로면 일부 파는 자리입니다')
    if avg_down_ok and buy and px <= buy:
        return ('추가 매수 가능',
                f'물타기 6조건 전부 통과이고 진입가({buy:,.0f}원) 이하입니다')
    return ('보유 유지',
            ('버틸 수 없는 가격과 1차 매도가 사이입니다'
             if (h_stop and h_trim) else
             (f'버틸 수 없는 가격({h_stop:,.0f}원) 위입니다' if h_stop else
              f'1차 매도가({h_trim:,.0f}원)에 아직 못 미칩니다'))
            + (f' · 물타기는 가능하나 진입가({buy:,.0f}원) 이하에서만'
               if (avg_down_ok and buy and px > buy) else ''))


def watch_action(row, price=None, today=None):
    """
    관심종목 한 줄의 판단. 반환:

        {'kind', 'label', 'tone', 'why', 'held'}   또는 None

    · `held=True`  — 매입가를 적어 둔 종목 (보유자 관점)
    · `held=False` — 안 적은 종목 (신규 매수자 관점 · bucket 그대로)
    · 잰 값이 없으면 **None** — 지어내지 않는다 (§3)
    """
    def _n(v):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return f if f > 0 else None

    px = _n(price) or _n((row or {}).get('snap_px'))
    paid = _n((row or {}).get('paid'))
    bucket = str((row or {}).get('snap_bucket') or '')
    # 라운드 378 — 판단에 쓰는 손절선은 한 곳(`effective_hold_stop`)에서. 파일의 값은 `h_stop_plan` 으로 남긴다.
    h_stop_plan = _n((row or {}).get('snap_hold_stop'))
    h_stop, _rev378 = effective_hold_stop(row)
    h_trim = _n((row or {}).get('snap_hold_trim'))
    buy = _n((row or {}).get('snap_buy'))

    if not bucket and not (h_stop or h_trim or buy):
        return None                      # 아직 아무것도 안 쟀다

    # ── 물타기 판정을 먼저 읽는다 (라운드 224 — 보유자 kind 가 이것을 본다) ──
    #   새 문턱을 만들지 않는다 — 스냅샷에 찍힌 `personalize_for_position` 의
    #   6조건 결과(`snap_avg_down_ok`·`snap_avg_down_fail`)를 **다시 말할 뿐**
    #   (§2-6 · §4). 안 찍혔으면 None — 지어내지 않는다 (§3). 파일은 글자
    #   ('가능'/'불가')로 남기고(portfolio.WATCH_SNAP_TXT), 같은 세션의 옛 값은
    #   bool 로 올 수 있다 — 둘 다 읽는다.
    _ok_raw = (row or {}).get('snap_avg_down_ok')
    if _ok_raw in (True, '가능'):
        _ad_ok = True
    elif _ok_raw in (False, '불가'):
        _ad_ok = False
    else:
        _ad_ok = None
    _fr = (row or {}).get('snap_avg_down_fail')
    # '없음' 은 "실패 없음"의 글자 표기다 (라운드 224 — 빈 글자는 병합에서 떨어져 옛
    #   목록이 남는다). 목록에서 뺀다.
    _ad_fail = ([s for s in str(_fr).split(' · ') if s and s != AVG_DOWN_NO_FAIL]
                if isinstance(_fr, str) else list(_fr or []))
    # 라운드 387 — 첫 조건의 출처가 `actionable` → `recommended`(신규 매수 추천)로 바뀌었다. 옛 기준의 **허락**은
    #   엔진이 아직 사지 말라는 칸('눌림목 매수 대기')에서 나왔을 수 있다(리포트 후보 458개 중 actionable 26 · 추천 0 ·
    #   그 26개의 비용 차감 기대값 전부 음수). 옛 글자('가능')로 찍힌 허락은 추가매수 허락으로 쓰지 않고 '아직 안 잼'으로
    #   둔다 — 채우기 기준이 그 행을 다시 고른다. 새 스탬프는 '추천'/'추천 아님' 이다.
    if _ad_ok and (row or {}).get('snap_new_entry') == '가능':
        _ad_ok, _ad_fail = None, []
    _ad_cls, _ad_label, _ad_why = avg_down_class(_ad_ok, _ad_fail)

    # ── 제외 사유를 **보여 줄지**는 여기서 정한다 (라운드 241 · §4) ──────
    #   종전에는 화면이 `snap_why` 를 직접 읽어 `held` 만 봤다. 그래서 제외가
    #   풀려 '매수 가능'이 된 행에도 옛 사유('추격매수 위험')가 붙을 수 있었다
    #   — 한 줄 안에서 스스로 모순이다. 판정은 한 곳에서 하고 화면은 읽기만.
    _raw241 = str((row or {}).get('snap_why') or '').strip()
    _why241 = (None if (not _raw241 or _raw241 == WATCH_NO_WHY
                        or bucket == '오늘 매수 가능') else _raw241)

    def _held(d):
        """보유자 판단에 **물타기 판정 · 정리 사유**를 붙인다 (라운드 214 → 224).

        *"관심종목 엔진판단에 가지고 있는 주식 물탈지 말지도 고민해주고."* (R214)
        *"정리하는 이유도 써줘 — 적정가는 있는데 너무 오래 기다려야 한다 ·
        1차 매도가가 넘었다 이런 것도."* (R224)
        `hold_why` 는 이 행에 대해 **잰 것만** 문장으로 잇는다 — 판단 kind 의
        이유 · 보유 계획의 기준 날짜와 창 · 적정가까지의 거리와 원장 도달 비율
        (`snap_fair_reach` · 문턱 없음) · 물타기 판정. 어느 줄도 새 문턱을
        만들지 않는다. 계획이 끝났을 때 남긴 한 줄(`snap_hold_log`)은 `hold_log`.
        """
        # 라운드 224 — 첫 조건의 출처가 바뀌었다(TOP3 깃발 → 중앙 판정). 그 전에 찍힌
        #   스탬프(`snap_new_entry` 없음)는 옛 게이트의 답이라, 새 문구("중앙 판정이 …
        #   보지 않는다")를 그대로 달면 재지 않은 것을 말하는 셈이다(§3). 사실대로 적고
        #   채우기를 가리킨다 — 라벨(등급)은 같다, 이유만 다르다.
        _stale = (_ad_ok is not None and not (row or {}).get('snap_new_entry'))
        # 보유 행에는 제외 사유를 안 붙인다 — 보유자에게는 보유 기준값 문장이
        #   답이다 (라운드 240 에서 정한 것 · 241 이 키로 명시한다).
        d['why_line'] = None
        d['avg_down_ok'] = _ad_ok
        d['avg_down_class'] = _ad_cls
        d['avg_down_label'] = _ad_label
        d['avg_down_why'] = ((_ad_why or '') + ' · 이 판정은 첫 조건의 기준이 바뀌기 전에 '
                             '찍힌 것입니다 — 다시 채우면 중앙 판정으로 갱신됩니다'
                             if _stale else _ad_why)
        d['avg_down_stale'] = _stale
        d['holder_title'] = (row or {}).get('snap_holder_title')
        why = [str(d.get('why') or '')]
        # ① 보유 계획 — 잰 날과 창 (기준값은 잰 날에 고정 · portfolio.hold_plan_update)
        _at = str((row or {}).get('snap_hold_at') or '')[:10]
        if _at and (h_stop or h_trim):
            _line = f"보유 기준값(버틸 수 없는 가격·1차 매도가)은 {_at} 에 잰 것"
            try:
                import datetime as _dt
                import ledger_view as _lv
                _td = today or _dt.date.today()
                _age = (_td - _dt.date.fromisoformat(_at)).days
                _days = _lv.bars_to_days(_lv.HORIZON_BARS)
                if _age >= _days:
                    _line += (f" · 창({_lv.HORIZON_BARS}봉={_days}일)이 지났습니다 — "
                              f"종목을 열면 다시 잽니다")
                else:
                    _line += f" · 창 {_days}일 중 {_age}일째"
            except Exception:                                  # noqa: BLE001
                pass
            why.append(_line)
        # ② 적정가 — 거리와 원장 도달 비율. 시간을 재지 않는다(못 잰다 · R215).
        _fair = _n((row or {}).get('snap_fair'))
        if _fair and px:
            _up = (_fair / px - 1.0) * 100.0
            _reach = str((row or {}).get('snap_fair_reach') or '')
            if _up > 0:
                why.append(_reach if _reach else f"적정가 {_fair:,.0f}원까지 {_up:+.1f}%")
                if _reach:
                    why.append("이 창에서 닿기 어려운 크기면 적정가는 이 보유의 이유가 못 "
                               "됩니다 — 기다리는 비용은 사용자가 정합니다")
            else:
                why.append(f"현재가가 적정가({_fair:,.0f}원)보다 {-_up:.1f}% 위 — "
                           f"적정가는 이 보유의 이유가 못 됩니다")
        # ③ 물타기 (옛 스탬프면 그 사실까지 · 위 avg_down_why 와 같은 글)
        if _ad_label:
            why.append(f"{_ad_label} — {d['avg_down_why']}")
        _log = [s for s in str((row or {}).get('snap_hold_log') or '').split(' | ') if s]
        d['hold_log'] = _log
        # ④ 라운드 371 — 지금 계획이 **선을 넘겨** 다시 잰 것이면(마지막 이력의 날짜 = 잰 날) 그 사실을
        #   문장으로 잇는다. 옛 계획대로면 파는 자리였다는 것과 새 선을 같은 줄에 — 없으면 사용자는
        #   표의 '매도'와 상세의 '보유 유지'를 엔진이 말을 바꾼 것으로 읽는다(R340 이 이력 줄을 넣었지만
        #   표가 잘라 그 말이 툴팁에만 있었다). 규칙·판정 불변 · 새 문턱 없음.
        _last371 = hold_log_parse(_log[-1]) if _log else None
        _reset371 = _last371 if (_last371 and _at and _last371['date'] == _at) else None
        d['hold_reset'] = _reset371
        try:
            import datetime as _dt371
            _td371 = today or _dt371.date.today()
        except Exception:                                      # noqa: BLE001
            _td371 = today
        d['hold_log_short'] = (hold_log_short(_log[-1], new_stop=h_stop_plan, new_trim=h_trim,
                                              today=_td371, revived=bool(_rev378)) if _log else '')
        d['hold_stop_revived'] = _rev378
        d['hold_stop_eff'] = h_stop
        if _rev378 and h_stop:
            # 옛 규칙의 재측정은 선을 낮출 수도 올릴 수도 있었다(회귀 픽스처는 9,000 → 9,300) — 방향을 사실대로.
            _moved378 = ('낮췄습니다' if (h_stop_plan or 0) < h_stop else '다시 쟀습니다')
            why.insert(1, (f"옛 계획의 버틸 수 없는 가격 {h_stop:,.0f}원({_rev378['old_at']} 기준)을 {_rev378['date']} 에 "
                           f"넘겼고, 그때 규칙(닿으면 다시 잼)이 선을 {h_stop_plan or 0:,.0f}원으로 {_moved378}. "
                           f"2026-09-28 결정(넘긴 계획은 그대로)을 이 종목에도 적용해 **옛 손절선으로 봅니다** — "
                           f"낮춘 선으로 보려면 '기준 다시 재기'를 누르세요(1차 매도가는 옛 값이 이력에 없어 지금 값)"))
        elif _reset371 and _reset371['kind'] == 'stop' and h_stop:
            why.insert(1, (f"옛 계획(버틸 수 없는 가격 {_reset371['old']:,.0f}원 · {_reset371['old_at']} 기준)"
                           f"으로는 파는 자리였습니다 — 그때 규칙(닿으면 다시 잼)대로 {_at} 에 기준을 다시 쟀고, "
                           f"새 버틸 수 없는 가격은 {h_stop:,.0f}원입니다 · 2026-09-28 부터는 손절선을 넘긴 "
                           f"계획을 그대로 둡니다"))
        elif _reset371 and _reset371['kind'] == 'manual' and h_stop:
            why.insert(1, (f"{_at} 에 사람이 기준을 다시 쟀습니다 — 옛 버틸 수 없는 가격 "
                           f"{_reset371['old']:,.0f}원({_reset371['old_at']} 기준) → 새 {h_stop:,.0f}원"))
        elif _reset371 and _reset371['kind'] == 'trim' and h_trim:
            why.insert(1, (f"옛 계획(1차 매도가 {_reset371['old']:,.0f}원 · {_reset371['old_at']} 기준)"
                           f"으로는 일부 파는 자리였습니다 — 닿으면 다시 재는 규칙대로 {_at} 에 기준을 다시 "
                           f"쟀고, 새 1차 매도가는 {h_trim:,.0f}원입니다 · 규칙은 바꾸지 않았습니다"))
        # 라운드 373 — 손절선을 넘긴 계획은 **그대로 둔다**(사용자 결정 2026-09-28). 종전엔 종목을 여는
        #   순간 다시 재어 '매도'가 스스로 지워졌다(보유 14행 중 넘긴 3행 전부). 이 판정이 서 있는 동안
        #   그 사실과 푸는 길 둘을 같은 줄에 적는다 — 낱말만 보면 "엔진이 아직 안 봤나"로 읽힌다.
        if d.get('kind') == '정리 검토':
            # 라운드 378 — 종전 "…누를 때까지 이 판정이 남습니다" 는 넘친 말이었다: 남는 것은 **계획(선)** 이고 판정은
            #   현재가를 그 선에 대 본 결과라 가격이 선 위로 돌아오면 '보유 유지' 가 된다(실측 2026-09-29 · 3행 중 2행).
            why.insert(1, "이 계획은 손절선을 넘긴 뒤에도 그대로 둡니다(2026-09-28 사용자 결정) — "
                          "'팔았음'을 누르거나 '기준 다시 재기'를 누를 때까지 이 선이 남고, 현재가가 선 아래인 동안 "
                          "판정은 '매도'입니다")
        d['hold_why'] = [w for w in why if w]
        # ── 짧은 판 (라운드 226 · 사용자: "너무 길다 · 핵심만") — 같은 재료를 낱말로.
        #   긴 문장(hold_why)은 종목 상세가, 짧은 판(hold_brief)은 포트폴리오 견해가 쓴다.
        #   두 판 다 이 함수 하나에서 나온다(§4). 문턱 없음.
        brief = []
        _k = d.get('kind')
        if _k == '일부 정리' and h_trim:
            brief.append(f"1차 매도가 {h_trim:,.0f}원 넘음 {(px / h_trim - 1) * 100:+.1f}%")
        elif _k == '정리 검토' and h_stop:
            brief.append(f"버틸 수 없는 가격 {h_stop:,.0f}원 아래")
        elif _k == '추가 매수 가능' and buy:
            brief.append(f"진입가 {buy:,.0f}원 이하")
        elif _k == '보유 유지':
            brief.append('두 선 사이' if (h_stop and h_trim) else
                         ('손절선 위' if h_stop else '1차 매도가 아래'))
            # 라운드 230 — "다 보유 유지인데 맞아?": 두 선까지의 거리 (산수 · 문턱 없음).
            #   '손절선 x% 아래' = 현재가에서 그만큼 내려가야 닿는다 (1 − 손절/현재가).
            if h_stop and h_trim and px:
                brief.append(f"손절선 {(1 - h_stop / px) * 100:.1f}% 아래 · "
                             f"1차 +{(h_trim / px - 1) * 100:.1f}% 위")
        if _at and (h_stop or h_trim):
            try:
                import datetime as _dt2
                import ledger_view as _lv2
                _td2 = today or _dt2.date.today()
                _age2 = (_td2 - _dt2.date.fromisoformat(_at)).days
                _days2 = _lv2.bars_to_days(_lv2.HORIZON_BARS)
                brief.append(f"계획 창 경과 · 다시 잼" if _age2 >= _days2
                             else f"계획 {_at[5:]} · {_age2}/{_days2}일")
            except Exception:                                  # noqa: BLE001
                brief.append(f"계획 {_at[5:]}")
        if _fair and px:
            _up2 = (_fair / px - 1.0) * 100.0
            if _up2 > 0:
                try:
                    import ledger_view as _lv3
                    _pr = _lv3.parse_reach_line((row or {}).get('snap_fair_reach'))
                except Exception:                              # noqa: BLE001
                    _pr = None
                brief.append(f"적정가 {_up2:+.0f}% · {_pr['bars']}봉 도달 {_pr['share']:.1f}%"
                             f"(n={_pr['n']:,})" if _pr else f"적정가 {_up2:+.0f}%")
            else:
                brief.append(f"현재가가 적정가보다 {-_up2:.0f}% 위")
        # ── 표에 쓰는 **짧은 한 줄** (라운드 322) — 무엇을 하라는 말인지 · 가격까지.
        #   '보유 유지'인데 조건은 통과한 행은 *지금 사라*가 아니라 *진입가 이하로 내려오면*이다
        #   (holder_kind 의 같은 갈래 · 새 문턱 없음). '추가 매수 가능' 행은 kind 가 이미 그 말이다.
        # 라운드 387 — 이 판정은 **찍힌 날**의 것이다. 가격이 나중에 진입가로 내려와 이 행이 '추가 매수 가능'으로
        #   바뀌어도 그 사이 다시 잰 적은 없다 — 종전 *"지금 추가매수 가능"* 은 옛 판정을 오늘의 지시로 읽히게 했다
        #   (사용자: 추가매수하라 해서 샀다가 손실). 판정 날짜와 '사기 전에 다시 재라'를 같은 줄에 적는다.
        _at_ad = str((row or {}).get('snap_at') or '')[:10]
        _when_ad = f"{_at_ad} 판정" if _at_ad else "판정 날짜 모름"
        if _ad_cls == '가능':
            _short = (f"진입가 {buy:,.0f}원 이하 · 추가매수 조건 통과({_when_ad}) — 사기 전에 '지금 재기'로 다시 확인"
                      if _k == '추가 매수 가능' and buy
                      else f"추가매수 조건 통과({_when_ad}) · {buy:,.0f}원 이하에서만 — 그때 다시 잰 판정으로" if buy
                      else '추가매수 조건 통과 · 진입가 미산출')
        elif _ad_cls == '시장게이트':
            _short = '추가매수 안 함 · 지금은 새로 살 때 아님'
        elif _ad_cls == '포지션미달':
            _short = f"추가매수 안 함 · 조건 {len(_ad_fail)}개 미충족"
        elif _ad_cls == '보류':
            _short = '추가매수 판단 보류 · 표본 부족'
        elif (row or {}).get('qty'):
            _short = "추가매수 아직 안 잼 · 아래 '지금 계산해서 채우기'"
        else:
            _short = '수량을 넣으면 추가매수를 잽니다'
        d['avg_down_short'] = _short
        brief.append(_short)
        if _stale and _ad_cls:
            brief.append('옛 기준 스탬프 · 다시 채우기')
        d['hold_brief'] = brief
        return d

    if paid and px:
        # ── 보유자 관점 ────────────────────────────────────────────
        # ⚠️ 보유자 가격선이 **하나도 없으면 판단하지 않는다.** 없는 채로
        #   '보유 유지'라고 적으면 *못 잰 것*을 *판단*으로 만드는 것이라
        #   §3 위반이다. 화면 실측에서 실제로 13종목이 전부 '보유 유지'로
        #   나왔고, 그건 판단이 아니라 값이 없었던 것이다.
        # 라운드 304 — 판정은 `holder_kind` **한 곳**이다. 종전엔 이 다섯 갈래가 여기
        #   에만 있었고, 가늠 AI 는 **자기 문턱**(평단 대비 +5/0/−7)으로 따로 골라
        #   격자 120칸 중 **64칸(53%)** 이 어긋났다(§4 · R193·R246 의 그 자리).
        #   이름·순서·이유 문장은 그대로 — 자리만 옮겼다.
        # 라운드 224 — '추가 매수 가능'은 **물타기 판정과 같은 답**이어야 한다 (§4).
        #   종전엔 bucket 만 봐서, 물타기가 '불가'인 행에 '추가 매수 가능'이 찍힐 수
        #   있었다(한 종목에 "더 살 수 있나"의 답이 둘). 이제 6조건 전부 통과일 때만,
        #   그리고 엔진의 진입가 이하일 때만이다. 진입가 위면 '보유 유지'로 두고
        #   이유에 적는다.
        _hk, _hw = holder_kind(px, h_stop, h_trim, buy=buy, avg_down_ok=_ad_ok)
        _TONE304 = {'보유 기준 미산출': 'tx3', '정리 검토': 'neg', '일부 정리': 'pos',
                    '추가 매수 가능': 'pos', '보유 유지': 'tx2'}
        return _held(dict(kind=_hk, label=hold_label(_hk), tone=_TONE304.get(_hk, 'tx2'),
                          held=True, why=_hw))

    # ── 미보유 관점 — bucket 을 그대로 짧게 말한다 ──────────────────
    if not bucket:
        return None
    if bucket == '오늘 매수 가능':
        if buy and px and px <= buy:
            return dict(kind='매수 가능', label='지금 매수 가능', tone='pos',
                        held=False, why_line=None,
                        why=f'목표 매수가({buy:,.0f}원) 이하입니다')
        return dict(kind='매수 가능', label='매수 가능', tone='pos',
                    held=False, why_line=None,
                    why=(f'다만 목표 매수가 {buy:,.0f}원 이하로 내려와야 '
                         f'합니다' if buy else '엔진이 매수 가능으로 봅니다'))
    _short = {
        '눌림목 매수 대기': ('눌림목 대기', 'brand'),
        '돌파 후 매수 대기': ('돌파 대기', 'brand'),
        '과열 해소 대기': ('과열 대기', 'warn'),
        '거래량 회복 대기': ('거래량 대기', 'warn'),
        '시장 국면 회복 대기': ('국면 대기', 'warn'),
        '권장가 괴리 과다': ('괴리 과다', 'warn'),
        '신뢰도·표본 확보 대기': ('표본 대기', 'tx3'),
        # 라운드 292 — 이 칸은 **기다려서 풀리는 것이 아니다**(검증을 이미 했고 성적이
        #   못 미쳤다). 짧은 이름에도 '대기'를 쓰지 않는다 — 사용자가 화면에서 '표본 대기'
        #   를 보고 기다리면 되는 줄로 읽었다.
        '표본외 성적 미달': ('성적 미달', 'tx3'),
        '데이터 부족': ('데이터 부족', 'tx3'),
        '추천 제외': ('추천 제외', 'neg'),        # 라운드 226 — '사지 않음'은 판정이 아니라 지시처럼 읽혔다
    }
    # ⚠️ 라운드 327 — 사용자: *"(한 종목) 표본 대기 · 표본외 검증은 마쳤고, 그 성적이 기준에 못 미쳤습니다 …
    #   개선해주고."* 중앙 판정이 이 사유를 **'표본외 성적 미달'** 로 가른 것은 2026-09-14 부터다(R292).
    #   그 전에 찍힌 스냅샷은 같은 사유를 옛 이름 '신뢰도·표본 확보 대기' 로 안고 있어, 표가 *"표본 대기"*
    #   (기다리면 된다) 옆에 *"사례가 쌓인다고 풀리는 조건이 아닙니다"* 를 적었다 — 한 줄이 스스로 어긋났다.
    #   새로 재지 않고 **중앙 판정과 같은 가름**을 옛 스냅샷에 적용한다: 사유가 그 갈래의 문장이면 그 이름이다
    #   (판별 낱말은 verdict_core 의 문장 머리 · §333 이 두 곳이 같은지 잠근다).
    if bucket == '신뢰도·표본 확보 대기' and OOS_FAIL_WHY_HEAD in _raw241:
        bucket = '표본외 성적 미달'
    # ⚠️ 라운드 387 — 중앙 판정은 2026-09-29 부터 '눌림목 매수 대기'·'돌파 후 매수 대기'를 **만들지 않는다**(기다려서
    #   풀리지 않는 미충족 — 손익비·기대값 — 에 기다림의 이름을 줬다 · verdict_core._bucket). 그 전 스냅샷은 옛 이름과
    #   옛 사유(*"더 낮은 자리에서만 셈이 맞습니다"* · *"눌림을 기다립니다"*)를 안고 있다. R327 과 같은 방식으로 **읽는
    #   쪽이 같은 가름을 적용한다** — 그 두 칸은 구조상 늘 그 미충족을 안고 있었으므로(위 갈래가 풀리는 것을 먼저
    #   가져갔다) '추천 제외'로 읽고, 옛 사유는 새 사유 문장 머리로 바꿔 말한다(새로 재지 않는다).
    _retired387 = bucket in _WAIT_RETIRED
    if _retired387:
        bucket = '추천 제외'
        _why241 = (f"옛 분류 '눌림·돌파 대기'였습니다 — {_WAIT_NOT_CURED_HEAD} 기다려도 손익비(진입가·1차)·기대값 셈은 거의 그대로라 "
                   f"추천 제외로 읽습니다(다시 채우면 새 판정)")
    # ⚠️ 라운드 396 — 사용자: *"미보유에서 과열대기가 좋은거야 거래량 대기가 좋은거야?"* 중앙 판정은 이제 기다리면 풀릴
    #   것만 남았을 때만 '… 대기'를 준다(verdict_core._bucket). 그 전 스냅샷은 미충족 목록을 안 담고 있어 **다시 가를 수
    #   없다** — R387 처럼 '추천 제외'로 읽으면 재지 않은 것을 말하는 셈이다(§3). 이름은 두고, 옛 규칙의 판정이라는 것과
    #   다시 재는 길을 같은 칸에 적는다(`remeasure` → 화면이 '지금 재기' 링크를 붙인다 · 새로 재지 않는다).
    _unsorted396 = bucket in _WAIT_NAMED and _WAIT_ONLY_HEAD not in _raw241
    if _unsorted396:
        _why241 = _WAIT_UNSORTED + (_why241 or '')
    lbl, tone = _short.get(bucket, (bucket[:7], 'tx3'))
    # 라운드 240 — 종전 why 는 bucket 을 그대로 되풀이해 아무것도 더 말하지 않았다.
    #   중앙 판정이 결론과 함께 낸 사유(`exclude_reason` → `snap_why`)가 있으면 그것을
    #   쓴다. 없으면 종전대로 bucket — 지어내지 않는다.
    return dict(kind=bucket, label=lbl, tone=tone, held=False,
                why_line=_why241, why=(_why241 or bucket), remeasure=_unsorted396)


def regime_gate_line(rg):
    """국면 게이트가 **지금 실제로** 무엇을 걸고 있나 — 한 줄. 없으면 없다고 말한다.

    라운드 248 — 사용자 물음: *"이 방향이면 내일 방어적으로 세팅을 해야하는지."*
    화면이 정직하게 낼 수 있는 답은 **이미 채택된 것**뿐이다 — 국면×변동성 6칸과
    그 칸의 실측 하한, 그리고 그것이 지금 건 제한(점수 상한·비중 배수·손절 배수).

    종전에는 **깎였을 때만** 말했다(web_app 의 국면 경고). 안 깎였을 때 침묵하면
    사용자는 '재지 않았다'로 읽는다 — 그래서 안 깎였을 때도 말한다.
    못 잰 칸은 '판정 보류'라 적는다. 지어내지 않는다(§3).
    """
    g = rg or {}
    cell = str(g.get('cell') or '').strip()
    if not cell:
        return '국면 판정 보류 — 지수를 못 받아 국면별 제한을 재지 않았습니다.'
    bits = []
    if g.get('score_after') is not None and g.get('score_before') is not None \
            and g['score_after'] != g['score_before']:
        bits.append(f"종합점수 {g['score_before']}→{g['score_after']}점")
    try:
        if float(g.get('size_mult') or 1.0) < 1.0:
            bits.append(f"제안 비중 {float(g['size_mult']):.1f}배")
    except (TypeError, ValueError):
        pass
    try:
        if float(g.get('stop_mult') or 1.0) < 1.0:
            bits.append(f"손절 폭 {float(g['stop_mult']):.1f}배")
    except (TypeError, ValueError):
        pass
    if g.get('block_new'):
        bits.append('신규 매수 차단')
    head = f"지금 국면 칸 **{cell}**"
    if g.get('level'):
        head += f" ({g['level']})"
    return head + (' — ' + ' · '.join(bits) if bits
                   else ' — 국면별 추가 제한 없음')


#: 매크로 보드의 묶음 — 사용자가 한눈에 읽는 순서다 (라운드 248).
#:   판단이 아니라 **분류**다. 어느 묶음이 좋다는 뜻이 아니다.
MACRO_GROUPS = (
    ('국내 지수', ('kospi', 'kosdaq')),
    ('해외 지수·변동성', ('spx', 'vix')),
    ('원자재', ('oil', 'copper', 'gold')),
    ('금리·환율', ('ust10', 'fx')),
)


def macro_board(macro, theme='dark'):
    """매크로 축을 한 판으로. **판단을 만들지 않는다** — 받은 값을 줄로 옮길 뿐.

    라운드 248 — 사용자 요청: *"유가 금 금리 등등을 보면서 … 디자인도 잘 보이게."*

    · 색은 **방향**이다(한국 관행 · 오름 빨강 / 내림 파랑). 좋고 나쁨이 아니다 —
      금리·변동성지수는 오르는 것이 위험 신호일 수 있다. 그 말을 캡션이 한다.
    · 금리는 **%p** 로 읽는다(`is_rate`). 4.81 → 4.70 은 −2.3% 가 아니라 −0.11%p 다.
    · 못 받은 축은 '미수신'이라 적는다. 0 으로 채우지 않는다.
    """
    m = macro or {}
    t = tokens(theme)
    # 값이 **하나도** 없으면 빈 문자열이다. 미수신 아홉 줄로 화면을 채우지
    #   않는다 — 왜 못 받았는지는 부르는 쪽이 사유와 함께 적는다(§3).
    if not any(isinstance(m.get(k), dict)
               for _g, ks in MACRO_GROUPS for k in ks):
        return ''
    rows = []
    for gname, keys in MACRO_GROUPS:
        cells = []
        for k in keys:
            v = m.get(k)
            if not isinstance(v, dict):
                cells.append(
                    f"<tr><td style='color:{t['tx3']};'>{_esc(str(k))}</td>"
                    f"<td class='n' colspan='4' style='color:{t['tx3']};'>"
                    f"미수신</td></tr>")
                continue
            rate = bool(v.get('is_rate'))

            def _mv(pct, dif):
                """금리는 %p · 나머지는 %. 못 재면 '—'."""
                x = dif if rate else pct
                if x is None:
                    return f"<span style='color:{t['tx3']};'>—</span>"
                col = t['up'] if x > 0 else t['down'] if x < 0 else t['tx3']
                unit = '%p' if rate else '%'
                return (f"<span style='color:{col};'>{x:+,.2f}{unit}</span>")

            last = v.get('last')
            cells.append(
                "<tr>"
                f"<td>{_esc(str(v.get('ko') or k))}"
                f"<span style='color:{t['tx3']}; font-size:12px;'> "
                f"{_esc(str(v.get('ticker') or ''))}</span></td>"
                f"<td class='n'>{(f'{last:,.2f}' if last is not None else '—')}</td>"
                f"<td class='n'>{_mv(v.get('chg5'), v.get('diff5'))}</td>"
                f"<td class='n'>{_mv(v.get('chg20'), v.get('diff20'))}</td>"
                f"<td class='n' style='color:{t['tx3']};'>"
                f"{_esc(str(v.get('last_date') or ''))}</td>"
                "</tr>")
        if cells:
            rows.append(
                f"<tr><td colspan='5' style='padding-top:10px; font-size:12px; "
                f"color:{t['tx3']}; font-weight:700;'>{_esc(gname)}</td></tr>"
                + ''.join(cells))
    if not rows:
        return ''
    head = ''.join(f"<th{' class=\'n\'' if i else ''}>{_esc(h)}</th>"
                   for i, h in enumerate(('지표', '현재', '5일', '20일', '기준일')))
    return (
        f"<div style='overflow-x:auto;'><table style='width:100%; "
        f"border-collapse:collapse; font-size:13px; line-height:1.35; "
        f"color:{t['tx2']};'>"
        f"<thead><tr style='color:{t['tx3']}; font-size:12px; text-align:left;'>"
        f"{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>")


# ── ETF 의 '적정가' — 순자산가치(NAV) · 라운드 164 ───────────────────────
#
# 사용자 요청: *"같은 주식도 검색해서 적정가 살때말때도 해줬으면 좋겠어"*
# (ETF 두 개를 가리키며).
#
# **ETF 에 기업 적정가는 없다.** EPS·BPS·ROE 가 존재하지 않는 자산이라
# 엔진은 `is_fund_like` 로 펀더멘털 밸류에이션을 건너뛴다 — 그게 옳다.
# 라운드 44 주석이 경고한 대로, 여기서 폴백이 걸리면 KODEX 200 에
# '적정가 90,069원' 같은 **근거 없는 값**이 붙는다.
#
# 그렇다고 "적정가 없음"으로 끝낼 일은 아니다. ETF 에는 원래부터 정답에
# 해당하는 값이 있다 — **순자산가치(NAV)**. 담고 있는 자산을 그날 값으로
# 평가한 것이라 **추정하는 값이 아니라 발표되는 값**이다.
#
# ⚠️ 갈래 기준을 새로 만들지 않았다. 이미 채택된 `VALUE_NEAR_PCT`(±3%)를
#   그대로 쓴다 (§2). 국내 ETF 의 괴리는 보통 이보다 훨씬 작아서 대부분
#   '중립'으로 나오는데, 그것이 **사실**이다 — 잘 따라간다는 뜻이다.
#   좁은 기준을 감으로 만들어 없는 신호를 만들지 않는다.
def nav_premium(price, nav):
    """(현재가 ÷ NAV − 1). 둘 중 하나라도 없으면 None — 지어내지 않는다.

    반환: dict(pct, kind, kind_ko, line)
      · 'rich'  — NAV 보다 비싸게 거래 (담은 자산보다 비싸게 사는 것)
      · 'cheap' — NAV 보다 싸게 거래
      · 'near'  — 거의 같다 (정상적인 ETF 의 보통 모습)
    """
    try:
        p, n = float(price), float(nav)
    except (TypeError, ValueError):
        return None
    if not (p > 0 and n > 0):
        return None
    pct = (p / n - 1.0) * 100.0
    if pct >= VALUE_NEAR_PCT:
        kind, ko = 'rich', '고평가'
        line = (f"담고 있는 자산 가치(NAV)보다 {pct:+.2f}% 비싸게 "
                f"거래되고 있습니다 — 그만큼 얹어 사는 것입니다.")
    elif pct <= -VALUE_NEAR_PCT:
        kind, ko = 'cheap', '저평가'
        line = (f"담고 있는 자산 가치(NAV)보다 {pct:+.2f}% 싸게 "
                f"거래되고 있습니다.")
    else:
        kind, ko = 'near', '정상'
        line = (f"NAV 와 거의 같습니다 ({pct:+.2f}%) — 지수를 잘 "
                f"따라가고 있다는 뜻입니다.")
    return dict(pct=round(pct, 2), kind=kind, kind_ko=ko, line=line)


def nav_row(np_, price=None, nav=None, at=None, theme='dark'):
    """ETF NAV 한 줄(HTML). `nav_premium()` 결과를 그대로 받는다.

    ⚠️ **받은 시각을 반드시 함께 적는다.** NAV 는 그 시점의 값이고,
       낡은 값을 오늘 값처럼 보여 주면 §3 위반이다.
    """
    if not np_:
        return ''
    t = tokens(theme)
    col = {'rich': t['warn'], 'cheap': t['pos'], 'near': t['tx2']}.get(
        np_['kind'], t['tx2'])
    nums = ''
    if price and nav:
        nums = (f"현재가 {float(price):,.0f}원 · NAV {float(nav):,.0f}원 · ")
    when = f" <span style='color:{t['tx3']};'>({_esc(at)} 조회)</span>" if at else ''
    return (
        f"<div style='display:flex; align-items:flex-start; gap:7px; "
        f"margin-top:9px; padding:8px 10px; background:{t['raised']}; "
        f"border-radius:8px;'>"
        f"{_icon('CircleDollarSign', col, 15)}"
        f"<div style='font-size:12px; line-height:1.5; color:{t['tx2']};'>"
        f"<b style='color:{col};'>ETF · NAV 대비 {_esc(np_['kind_ko'])}</b> · "
        f"{_esc(nums)}{_esc(np_['line'])}{when}</div></div>")


def etf_structure_block(struct, ttm=None, own_rows=None, cls_label=None, cls_rows=None,
                        theme='dark') -> str:
    """ETF 구조 사실 · 분배금 포함 12개월 · 원장 적용 범위 — 라운드 377 (표시 전용 · 판정 불변).

    사용자가 붙인 영상 둘에서 **확인되는 사실만** 옮겼다. 점수 0점·매매 금지·N분할·'횡보장이면 보유' 같은 규칙은
    넣지 않는다 — 원장에서 잰 적이 없는 규칙이다(§2). 대신 구조가 무엇이고, 분배금을 받고도 벌었는지, 이 엔진의
    규칙이 이 상품군에서 잰 것인지를 같은 카드에 적는다(값어치를 같은 화면에 — 라운드 285).
    struct: `etf_registry.structure_of` · ttm: `etf_registry.ttm_total_return` · own_rows/cls_rows: 원장 행 수.
    쓸 것이 없으면 '' 를 돌려준다.
    """
    t = tokens(theme)
    s = struct or {}
    lines = []
    mult = s.get('mult')
    geared = bool(s.get('daily_reset')) and mult is not None and mult != 1.0
    if geared:
        k = f"{mult:+g}".replace('+', '')
        lines.append(
            f"<b style='color:{t['tx1']};'>하루 수익률의 {k}배를 따라가는 구조</b> — 운용사 설명대로 매일 다시 "
            f"맞춥니다. 그래서 <b>여러 날의 수익률은 {k}배가 아닙니다</b>: 오르내림을 되풀이하는 장에서는 기초가 "
            f"제자리여도 잃을 수 있고, 한 방향으로 계속 가는 장에서는 {k}배보다 더 벌거나 더 잃을 수 있습니다.")
        if s.get('single_stock'):
            lines.append(
                f"<b style='color:{t['tx1']};'>기초가 회사 하나입니다(단일종목)</b> — 여러 종목에 나눠 담은 지수와 "
                f"달리 그 회사 하나의 악재가 {k}배로 옵니다.")
    if s.get('covered_call'):
        lines.append(
            f"<b style='color:{t['tx1']};'>콜옵션을 파는 구조(커버드콜)</b> — 옵션을 팔아 받은 돈을 분배금으로 "
            f"나눠 줍니다. 기초자산이 크게 오를 때 <b>상승분이 잘리고</b>, 떨어질 때는 받은 돈만큼만 덜 떨어집니다"
            f"(손실을 막아 주지는 않습니다). <b>분배율은 수익률이 아닙니다.</b> 아래 목표가는 이 ETF 자신의 가격 "
            f"움직임으로 잰 값이고, 옵션으로 잘리는 상승분을 따로 계산하지 않았습니다.")
    tt = ttm or {}
    if tt.get('total_pct') is not None and (tt.get('dist_pct') or 0) > 0:
        _c = t['up'] if tt['total_pct'] > 0 else t['down'] if tt['total_pct'] < 0 else t['tx2']
        lines.append(
            f"<b style='color:{t['tx1']};'>분배금 포함 최근 12개월</b> ({_esc(tt['start'])} ~ {_esc(tt['end'])}): "
            f"가격 {tt['price_pct']:+.1f}% · 분배금 {tt['dist_pct']:+.1f}% (1년 전 가격 대비) · "
            f"<b style='color:{_c};'>합계 {tt['total_pct']:+.1f}%</b> — 분배금을 받고도 전체로 벌었는지는 이 합계가 "
            f"말합니다. 재투자·세금·매매비용은 빼지 않았고 운용보수는 가격에 이미 들어 있습니다. 분배금은 네이버의 "
            f"'최근 12개월 합'이라 가격 구간과 며칠 어긋날 수 있습니다.")
    if (geared or s.get('covered_call')) and own_rows is not None:
        _cl = (f" · 같은 상품군(상품명으로 가른 '{_esc(cls_label)}') {cls_rows:,}행" if cls_label and cls_rows is not None
               else '')
        _zero = (cls_rows == 0) if cls_label and cls_rows is not None else (own_rows == 0)
        lines.append(
            f"<span style='color:{t['tx3']};'>이 엔진의 규칙과 확률은 원장(되돌려 본 판단)에서 잰 것입니다 — 이 상품은 "
            f"원장에 {own_rows:,}행{_cl}."
            + (" 이 상품군에서는 <b>한 번도 재 본 적이 없습니다</b> — 이 엔진이 내는 판정은 다른 자산에서 잰 규칙을 "
               "그대로 적용한 것입니다." if _zero else '')
            + "</span>")
    if not lines:
        return ''
    return (f"<div style='margin-top:11px; padding:10px 12px; background:{t['raised']}; border-radius:8px; "
            f"font-size:12px; line-height:1.65; color:{t['tx2']};'>"
            + '<br>'.join(lines) + "</div>")


def etf_profile_block(prof, premium_pct=None, band_line=None, theme='dark'):
    """ETF 카드 안 — 괴리율로 본 적정가 · 무엇을 따라가나 · 분배금 · 담은 것 (라운드 332).

    값은 `etf_registry.profile` 이 받은 것만 쓴다. 없는 줄은 안 그린다(§3). 괴리율 수는 화면의 NAV 줄과
    **같은 출처**(`nav_of`)만 받는다 — 프로필에도 괴리가 있지만 받은 시각이 달라 두 수가 한 화면에 나온다(§4).
    """
    t = tokens(theme)
    rows = []
    # ① 괴리율로 본 적정가 — ETF 의 적정가는 추정이 아니라 발표값(NAV)이다
    fv = ("<b style='color:" + t['tx1'] + ";'>괴리율로 본 적정가</b> — ETF 의 적정가는 매일 발표되는 "
          "<b>NAV</b> 자체입니다. 괴리율은 그 값보다 <b>얼마나 비싸게·싸게 사는지</b>만 말하고, 담긴 자산이 "
          "싼지 비싼지는 말하지 않습니다(그 물음은 아래 '담은 기업들의 가치'가 답합니다 — 국내 주식형 일부만).")
    if band_line:
        fv += ' ' + _esc(band_line)
    rows.append(fv)
    if prof:
        # ② 무엇을 따라가나
        bits = []
        if prof.get('issuer'):
            bits.append(f"운용 {_esc(prof['issuer'])}")
        if prof.get('listed'):
            bits.append(f"상장 {_esc(prof['listed'])}")
        if prof.get('fee_pct') is not None:
            bits.append(f"총보수 연 {prof['fee_pct']:g}%")
        if prof.get('tracking_error_pct') is not None:
            bits.append(f"추적오차 {prof['tracking_error_pct']:g}%")
        if prof.get('base_index') or bits:
            line = "<b style='color:" + t['tx1'] + ";'>무엇을 따라가나</b> — "
            line += (f"<b>{_esc(prof['base_index'])}</b>" if prof.get('base_index') else '기초지수 미수신')
            if bits:
                line += ' · ' + ' · '.join(bits)
            if prof.get('summary'):
                line += f"<br><span style='color:{t['tx3']};'>{_esc(prof['summary'])}</span>"
            rows.append(line)
        # ③ 분배금
        dv = prof.get('div') or {}
        if dv.get('dps_ttm') is not None:
            if dv['dps_ttm'] > 0:
                ms = dv.get('months') or []
                line = (f"<b style='color:{t['tx1']};'>분배금</b> — 최근 1년 합 <b>{dv['dps_ttm']:,.0f}원</b>"
                        + (f" · 분배율 {dv['yield_ttm_pct']:g}%" if dv.get('yield_ttm_pct') is not None else '')
                        + (f" · 올해 {'·'.join(str(m) for m in ms)}월 지급" if ms else '')
                        + (f"({dv['count_this_year']}회)" if dv.get('count_this_year') else '')
                        + ". 분배금은 NAV 에서 빠져나가므로 분배 기준일 다음 날 가격이 그만큼 낮아지는 것이 "
                          "정상입니다 — 분배율이 높다고 수익이 그만큼 더 나는 것은 아닙니다.")
            else:
                line = (f"<b style='color:{t['tx1']};'>분배금</b> — 최근 1년 분배가 없습니다"
                        " (받은 값이 0원입니다).")
            rows.append(line)
        # ④ 담은 것
        assets = [(a, w) for a, w in (prof.get('assets') or []) if w and w > 0][:4]
        top = [(n, w) for n, w in (prof.get('top') or [])][:5]
        if assets or top:
            line = f"<b style='color:{t['tx1']};'>담은 것</b> — "
            if assets:
                line += ' · '.join(f"{_esc(a)} {w:.1f}%" for a, w in assets)
            if top:
                line += (' · ' if assets else '') + '상위 ' + ', '.join(
                    _esc(n) + (f" {w:.1f}%" if w is not None else '') for n, w in top)
            rows.append(line)
        if prof.get('at'):
            rows.append(f"<span style='color:{t['tx3']};'>네이버 ETF 정보 {_esc(prof['at'])} 조회"
                        + (f" · 성과 기준일 {_esc(prof['ref_date'])}" if prof.get('ref_date') else '')
                        + "</span>")
    else:
        rows.append(f"<span style='color:{t['tx3']};'>추종 지수·분배금·구성 정보를 받지 못했습니다 — "
                    "값을 지어내지 않고 비워 둡니다.</span>")
    inner = ''.join(f"<p style='margin:0 0 6px 0;'>{r}</p>" for r in rows)
    return (f"<div style='margin-top:11px; padding:10px 12px; background:{t['raised']}; "
            f"border-radius:8px; font-size:12px; line-height:1.6; color:{t['tx2']};'>{inner}</div>")


def reco_card(p: dict, theme: str = 'dark') -> str:
    """
    오늘의 추천·관망 카드 한 장.

    p 에서 읽는 것: state(pos|warn|hold|neg) · state_label · name · code ·
    asset_ko · score · conf · price · rec_buy · rec_basis · target ·
    target_basis · stop · stop_basis · dim_levels(bool) · say · hold_note ·
    news · hit · horizon · risk · **why**(why_pick.build 결과)
    없는 값은 그리지 않는다 — 지어내지 않는다.
    """
    t = tokens(theme)
    STATE = {'pos': (t['pos'], 'ShieldCheck'),
             'warn': (t['warn'], 'Clock3'),
             'hold': (t['tx2'], 'Clock3'),
             'neg': (t['neg'], 'TriangleAlert')}
    col, sic = STATE.get(p.get('state', 'hold'), STATE['hold'])
    stripe = col if p.get('state') != 'hold' else t['tx3']

    head = (
        f"<span style='display:inline-flex; align-items:center; gap:6px; "
        f"background:{t['raised']}; color:{col}; font-size:12px; "
        f"font-weight:700; padding:3px 9px; border-radius:7px; "
        f"white-space:nowrap;'>{_icon(sic, col, 14)}"
        f"{_esc(p.get('state_label', ''))}</span>")

    meta = ' · '.join(str(x) for x in (
        p.get('code'), p.get('asset_ko'),
        (f"{p['score']}점" if p.get('score') is not None else None),
        p.get('conf')) if x)

    # 가격 — 늘 같은 순서. 없는 줄은 그리지 않는다.
    dim = bool(p.get('dim_levels'))
    rows = [_price_row('CircleDollarSign', '현재가', _won(p.get('price')),
                       big=True, theme=theme)]
    # 라운드 186 — 이 줄의 이름은 중앙 판정이 정한다 (rec_label ←
    #   verdict_core.entry_label). 추천 조건을 통과했을 때만 '권장 매수가'고
    #   아니면 '검토 기준가'다. **기본값은 검토 기준가** — 호출부가 라벨을
    #   빠뜨렸을 때 나는 실패 중 '추천 아닌 종목에 권장이라 적기'(과장)가
    #   '추천 종목에 검토라 적기'(축소)보다 나쁘다 (라운드 120e 의 기준).
    rows.append(_price_row(
        'ArrowDownToLine', str(p.get('rec_label') or '검토 기준가'),
        _won(p['rec_buy']) if p.get('rec_buy') else _esc(p.get('rec_na', '미산출')),
        p.get('rec_basis', ''),
        color=(col if p.get('rec_buy') else None),
        muted=not p.get('rec_buy'), theme=theme))
    # 가치 프리미엄 — 가격 줄 **바로 아래**에 둔다 (라운드 133).
    # 접힌 영역에 두면 안 읽힌다. 실제로 라운드 56 이 같은 내용을 상세
    # 배너의 '더 보기' 안에 넣어 뒀는데, 카드만 보는 사용자에게는 그
    # 문장이 존재하지 않는 것과 같았다.
    _vp_html = value_row(p.get('value_premium'), theme=theme)
    if p.get('target'):
        rows.append(_price_row('Target', '1차 목표가', _won(p['target']),
                               p.get('target_basis', ''),
                               color=t['brand'], muted=dim, theme=theme))
    if p.get('stop'):
        rows.append(_price_row('ShieldAlert', '손절가', _won(p['stop']),
                               p.get('stop_basis', ''),
                               color=t['up'], muted=dim, theme=theme))
    prices = (f"<div style='background:{t['raised']}; border-radius:11px; "
              f"padding:4px 12px; display:grid; "
              f"grid-template-columns:17px 1fr auto; gap:0 10px; "
              f"align-items:center;'>{''.join(rows)}</div>"
              + _vp_html)

    say = (f"<p style='margin:0; font-size:13px; line-height:1.65; "
           f"color:{t['tx1']};'>{_esc(p['say'])}</p>" if p.get('say') else '')

    # 다음 조건 — "사지 마세요"로 끝내지 않는다. 관망이면 무엇을 기다리는지
    # 여기에 적는다. 조건이 없으면 이 상자를 아예 그리지 않는다.
    nextbox = ''
    if p.get('next_conditions'):
        _items = ''.join(f"<li style='margin:3px 0;'>{_esc(x)}</li>"
                         for x in p['next_conditions'][:3])
        nextbox = (
            f"<div style='background:{t['raised']}; border-radius:10px; "
            f"padding:9px 11px;'>"
            f"<p style='margin:0 0 4px 0; font-size:12px; color:{t['tx3']}; "
            f"font-weight:700;'>다음 조건</p>"
            f"<ul style='margin:0; padding-left:16px; font-size:12px; "
            f"color:{t['tx2']}; line-height:1.6;'>{_items}</ul></div>")

    box = ''
    if p.get('hold_note'):
        box = (f"<div style='background:{t['raised']}; border-radius:10px; "
               f"padding:9px 11px; display:flex; gap:8px; "
               f"align-items:flex-start; font-size:12px; color:{t['tx2']}; "
               f"line-height:1.6;'>{_icon('TriangleAlert', t['warn'], 16)}"
               f"<span>{_esc(p['hold_note'])}</span></div>")

    # ── 왜 이 종목인가 ────────────────────────────────────────────────
    # 사용자 지적: *"단순히 점수가 높다는 이유만 보여줄 것이 아니라, 왜 이
    # 종목을 계속 관심 있게 봐야 하는지 명확하게 설명해 주세요."*
    # '49점 · 신뢰도 88' 은 근거가 아니라 라벨이다. 그 점수가 어떤 매수
    # 논리를 뜻하는지 숫자와 함께 적는다. 근거가 없으면 이 칸을 안 그린다.
    whybox = ''
    wp = p.get('why') or {}
    if wp.get('quant') or (wp.get('news') or {}).get('text') or wp.get('sector'):
        rows = []
        for title, body in (wp.get('quant') or []):
            rows.append(
                f"<li style='margin:0 0 5px 0;'>"
                f"<b style='color:{t['tx1']};'>{_esc(title)}</b> — "
                f"{_esc(body)}</li>")
        nw = wp.get('news') or {}
        if nw.get('text'):
            rows.append(
                f"<li style='margin:0 0 5px 0;'>"
                f"<b style='color:{t['tx1']};'>뉴스·이슈</b> — "
                f"{_esc(nw['text'])}</li>")
        if wp.get('sector'):
            st_, sb_ = wp['sector']
            rows.append(
                f"<li style='margin:0 0 5px 0;'>"
                f"<b style='color:{t['tx1']};'>{_esc(st_)}</b> — "
                f"{_esc(sb_)}</li>")
        rk = wp.get('risk')
        risk_html = ''
        if rk:
            rt, rb = rk
            risk_html = (
                f"<p style='margin:8px 0 0 0; font-size:12px; "
                f"color:{t['warn']}; display:flex; gap:6px; "
                f"align-items:flex-start; line-height:1.65;'>"
                f"{_icon('TriangleAlert', t['warn'], 14)}"
                f"<span><b>{_esc(rt)}</b> — {_esc(rb)}</span></p>")
        whybox = (
            f"<div style='background:{t['raised']}; border-radius:10px; "
            f"padding:11px 13px;'>"
            f"<p style='margin:0 0 7px 0; font-size:12px; font-weight:700; "
            f"color:{t['tx2']};'>왜 이 종목인가</p>"
            f"<ul style='margin:0; padding-left:16px; font-size:12px; "
            f"color:{t['tx2']}; line-height:1.65;'>{''.join(rows)}</ul>"
            f"{risk_html}</div>")

    whys = []
    if p.get('risk'):
        whys.append(_why_row('TriangleAlert', p['risk'], t['neg'], theme))
    if p.get('news') and not whybox:
        # 왜-칸이 뉴스를 이미 서술했으면 개수 줄을 또 쓰지 않는다
        whys.append(_why_row('Newspaper', p['news'], theme=theme))
    if p.get('hit'):
        whys.append(_why_row('ChartNoAxesCombined', p['hit'], theme=theme))
    if p.get('horizon'):
        whys.append(_why_row('CalendarClock', p['horizon'], theme=theme))
    why = (f"<div style='display:flex; flex-direction:column; gap:5px; "
           f"font-size:12px; color:{t['tx2']};'>{''.join(whys)}</div>"
           if whys else '')

    parts = [x for x in (
        head,
        f"<div><p style='margin:0; font-size:17px; font-weight:700; "
        f"color:{t['tx1']}; letter-spacing:-0.01em; text-wrap:balance;'>"
        f"{_esc(p.get('name', ''))}</p>"
        f"<p style='margin:0; font-size:12px; color:{t['tx2']}; "
        f"font-variant-numeric:tabular-nums;'>{_esc(meta)}</p></div>",
        prices, say, nextbox, whybox, box, why) if x]

    return (
        f"<div style='background:{t['card']}; border-radius:14px; "
        f"overflow:hidden;'>"
        f"<div style='height:3px; background:{stripe};'></div>"
        f"<div style='padding:16px 18px 18px; display:flex; "
        f"flex-direction:column; gap:12px;'>{''.join(parts)}</div></div>")


def ticker_bar(items, theme: str = 'dark', height: int = 34) -> str:
    """
    화면 맨 위 흐르는 띠 — 지금 무엇이 돌고 있고, 무슨 이슈가 있는가.

    사용자 요청: *"업데이트 상황 알려주는 창... 뭐 진행중이다, 핫이슈가
    뭐다, 실시간으로 사이트나 뉴스 같은 거 맨 위에 계속 움직이게."*

    items: [{'kind': 'live'|'issue'|'news'|'market'|'idle',
             'text': str, 'href': str|None, 'meta': str|None,
             'pick': str|None}]

    ■ 지키는 것
      · **없는 것을 흘리지 않는다.** 뉴스를 못 받으면 그 사실을 흘린다.
        빈 띠를 채우려고 문구를 지어내지 않는다 (CLAUDE.md §3)
      · 이모지 대신 색 점 하나. 종류를 색으로만 가른다
      · `prefers-reduced-motion` 이면 **멈춘다.** 계속 움직이는 띠는
        어지럼·주의력 문제를 만든다. 접근성은 선택이 아니다
      · 마우스를 올리면 멈춘다 — 읽으려는데 지나가면 소용이 없다
      · 기사 링크는 새 창. **pick 이 있으면 제목 클릭은 같은 창** —
        ?pick=종목 으로 앱을 다시 열어 그 종목 분석으로 넘어간다
        (라운드 56: "뉴스 클릭하면 관련 종목으로 아래 내용도 바뀌게")
    """
    from urllib.parse import quote as _q56
    t = tokens(theme)
    KIND = {'live': t['brand'], 'issue': t['warn'], 'news': t['tx2'],
            'market': t['pos'], 'idle': t['tx3'], 'neg': t['neg']}
    items = [x for x in (items or []) if str(x.get('text') or '').strip()]
    if not items:
        return ''

    def one(x):
        col = KIND.get(str(x.get('kind') or 'news'), t['tx2'])
        meta = (f"<span style='color:{t['tx3']}; margin-left:6px;'>"
                f"{_esc(x['meta'])}</span>" if x.get('meta') else '')
        body = (f"<span style='width:6px; height:6px; border-radius:50%; "
                f"background:{col}; display:inline-block; flex:0 0 auto;'>"
                f"</span><span style='color:{t['tx2']};'>"
                f"{_esc(x['text'])}</span>{meta}")
        if x.get('pick'):
            # 제목 → 같은 창에서 그 종목 분석(?pick= 을 앱이 받아 검색
            # 경로로 넘긴다). 원문은 별도 '기사' 링크로 남긴다 — 두 목적
            # (분석 전환/원문 읽기)을 한 클릭에 섞지 않는다.
            art = (f"<a href='{_esc_attr(x['href'])}' target='_blank' "
                   f"rel='noopener noreferrer' style='color:{t['tx3']}; "
                   f"margin-left:6px; font-size:12px;"
                   f"text-decoration:underline;'>기사</a>"
                   if x.get('href') else '')
            inner = (f"<a href='?pick={_q56(str(x['pick']))}' "
                     f"target='_self' title='{_esc_attr(x['pick'])} 분석으로 이동' "
                     f"style='display:inline-flex; align-items:center; "
                     f"gap:7px; text-decoration:none;'>{body}</a>{art}")
        elif x.get('href'):
            inner = (f"<a href='{_esc_attr(x['href'])}' target='_blank' "
                     f"rel='noopener noreferrer' style='display:inline-flex; "
                     f"align-items:center; gap:7px; text-decoration:none;'>"
                     f"{body}</a>")
        else:
            inner = (f"<span style='display:inline-flex; align-items:center; "
                     f"gap:7px;'>{body}</span>")
        return (f"<span style='display:inline-flex; align-items:center; "
                f"gap:7px; margin-right:34px; white-space:nowrap;'>"
                f"{inner}</span>")

    row = ''.join(one(x) for x in items)
    # 같은 줄을 두 번 이어 붙여 끊김 없이 순환시킨다 (-50% 지점에서 원위치)
    dur = max(24, len(items) * 7)
    return (
        f"<style>"
        f"@keyframes gnTick {{from{{transform:translateX(0)}}"
        f"to{{transform:translateX(-50%)}}}}"
        f".gn-tick-wrap{{overflow:hidden; background:{t['card']}; "
        f"border-radius:9px; height:{height}px; display:flex; "
        f"align-items:center; margin:0 0 10px 0;}}"
        f".gn-tick{{display:inline-flex; align-items:center; "
        f"animation:gnTick {dur}s linear infinite; font-size:12px; "
        f"font-variant-numeric:tabular-nums; will-change:transform;}}"
        f".gn-tick-wrap:hover .gn-tick{{animation-play-state:paused;}}"
        f"@media (prefers-reduced-motion: reduce){{"
        f".gn-tick{{animation:none; overflow-x:auto;}}"
        f".gn-tick-wrap{{overflow-x:auto;}}}}"
        f"</style>"
        f"<div class='gn-tick-wrap' role='status' aria-live='off' "
        f"aria-label='진행 상황과 시장 소식'>"
        f"<div class='gn-tick'>{row}{row}</div></div>")


def trade_plan_card(p: dict, name: str = '', theme: str = 'dark') -> str:
    """
    매매 지시서 — 화면 맨 위. "그래서 얼마에 사서 언제 파는가".

    p: trade_plan.build() 결과
    없는 값은 그리지 않는다. 특히 **한계 문구를 빼지 않는다** — 지시서는
    확신처럼 읽히므로, 검증되지 않은 부분을 밝히지 않으면 과장이 된다.
    """
    t = tokens(theme)
    b = p.get('buyer') or {}
    h = p.get('holder') or {}
    m = p.get('market') or {}

    def _won(v):
        f = None
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return None if f != f else f'{f:,.0f}원'

    def _row(label, value, sub='', col=None):
        if not value:
            return ''
        return (f"<div style='min-width:132px;'>"
                f"<p style='margin:0; font-size:12px; color:{t['tx3']};'>"
                f"{_esc(label)}</p>"
                f"<p style='margin:2px 0 0 0; font-size:16px; font-weight:700; "
                f"color:{col or t['tx1']}; font-variant-numeric:tabular-nums;'>"
                f"{_esc(value)}</p>"
                + (f"<p style='margin:1px 0 0 0; font-size:12px;"
                   f"color:{t['tx3']};'>{_esc(sub)}</p>" if sub else '')
                + "</div>")

    # ① 시장 진단
    mkt = ''
    if m:
        note = m.get('slope_note') or ''
        mkt = (f"<div style='background:{t['raised']}; border-radius:9px; "
               f"padding:9px 12px;'>"
               f"<p style='margin:0; font-size:12px; color:{t['tx3']};'>"
               f"시장 진단</p>"
               f"<p style='margin:2px 0 0 0; font-size:13px; "
               f"color:{t['tx1']};'><b>{_esc(m.get('ko'))}</b>"
               + (f" · 60일선 {_esc(m.get('slope_ko'))}"
                  if m.get('slope_ko') else '') + "</p>"
               f"<p style='margin:3px 0 0 0; font-size:12px; "
               f"color:{t['tx2']}; line-height:1.6;'>{_esc(m.get('say'))}"
               + (f" {_esc(note)}" if note else '') + "</p>"
               f"<p style='margin:3px 0 0 0; font-size:12px;"
               f"color:{t['tx3']};'>개발 구간 실측 n={m.get('n'):,}"
               f" · 기준일 {m.get('days')}일 · 적중 {m.get('hit')}%"
               f" · 비용후 EV {m.get('ev'):+.3f}% — "
               f"시장 상태는 하루 안에서 모든 종목에 같은 값이라 유효 표본이 "
               f"날짜입니다. 블라인드로 확정하지 못했습니다.</p></div>")

    # ② 신규 매수 지시
    buy = ''
    if b.get('available'):
        col = t['pos'] if b.get('actionable') else t['warn']
        # 라운드 186 — 추천 통과가 아니면 '매수구간·이 값 이하에서만'이라
        #   적지 않는다. 머리말이 "오늘은 실행 자리가 아닙니다"인데 바로
        #   아래 줄이 매수 지시어를 쓰면 한 카드가 두 말을 한다.
        _reco_b = bool(b.get('recommended'))
        prices = ''.join((
            _row(('매수구간' if _reco_b else '검토 기준가'),
                 (f"{b['entry_zone'][0]:,.0f}~{b['entry_zone'][1]:,.0f}원"
                  if b.get('entry_zone') else _won(b.get('entry'))),
                 ('이 값 이하에서만' if _reco_b
                  else '매수 지시 아님 — 조건 충족 시 검토')),
            _row('돌파 매수', _won(b.get('breakout')), '거래량 동반 시'),
            # 라운드 279 — 이 셋은 **진입가** 기준이고, 종목 상세의 보유자 카드('팔 가격 1차' ·
            #   '버틸 수 없는 가격')는 **현재가** 기준이라 같은 규칙인데도 수가 다르다. 기준을 안
            #   적으면 한 화면의 두 매도가가 모순으로 읽힌다(사용자 지적 2026-09-11). 값 불변 —
            #   낱말은 이미 채택된 것(`verdict_core.price_basis` · 관심종목 열 이름)을 그대로 쓴다.
            #   2차 목표만은 구조적 저항(시장에 실재하는 가격대)이라 기준가와 무관하다 — %만 진입가 대비.
            _row('1차 목표', _won(b.get('target')),
                 ((f"{b['target_pct']:+.1f}% · " if b.get('target_pct') else '') + '진입가 기준'),
                 t['up']),
            _row('2차 목표', _won(b.get('target2')),
                 ((f"{b['target2_pct']:+.1f}% · " if b.get('target2_pct') else '')
                  + '구조적 저항 · 진입가 대비'),
                 t['up']),
            _row('손절', _won(b.get('stop')),
                 ((f"{b['stop_pct']:+.1f}% · " if b.get('stop_pct') else '') + '진입가 기준'),
                 t['down']),
            # 라운드 191 — 이 rr 은 CORE.rr(= entry_rr · 진입가·1차 목표)다.
            # 홈 표의 '손익비'(reward_risk_ratio · 현재가·2차)와 다른 값이라
            # 기준을 이름에 넣는다.
            _row('손익비(진입가·1차)', (f"{b['rr']}:1" if b.get('rr') else None)),
            _row('예상 보유', f"{b.get('horizon')}거래일"),
        ))
        ev = b.get('expected')
        buy = (f"<div>"
               f"<p style='margin:0 0 4px 0; font-size:15px; font-weight:700; "
               f"color:{col};'>{_esc(b.get('headline'))}</p>"
               + (f"<p style='margin:0 0 9px 0; font-size:13px; "
                  f"color:{t['tx2']}; line-height:1.65;'>"
                  f"{_esc(b.get('line'))}</p>" if b.get('line') else '')
               + f"<div style='display:flex; gap:18px; flex-wrap:wrap;'>"
                 f"{prices}</div>"
               + (f"<p style='margin:8px 0 0 0; font-size:12px; "
                  f"color:{t['warn'] if (ev or 0) <= 0 else t['pos']};'>"
                  f"비용 차감 기대값 {ev:+.2f}%</p>" if ev is not None else '')
               + f"<p style='margin:6px 0 0 0; font-size:12px;"
                 f"color:{t['tx3']}; line-height:1.6;'>"
                 f"{_esc(b.get('target_caveat'))}</p></div>")
    elif b.get('why'):
        buy = (f"<p style='margin:0; font-size:13px; color:{t['tx2']};'>"
               f"{_esc(b['why'])}</p>")

    # ③ 보유자 지시
    hold = ''
    if h.get('available'):
        rc = t['up'] if (h.get('ret_pct') or 0) >= 0 else t['down']
        hold = (f"<div style='background:{t['raised']}; border-radius:9px; "
                f"padding:10px 13px;'>"
                f"<p style='margin:0; font-size:12px; color:{t['tx3']};'>"
                f"이미 갖고 계신 분께 · 평단 {h['avg']:,.0f}원 · "
                f"<span style='color:{rc}; font-weight:700;'>"
                f"{h['ret_pct']:+.1f}%</span></p>"
                # 15px — 스케일에 14 는 없다 (12·13·15·16·17…).
                # 주변 본문이 12px 이므로 헤드라인은 위로 올린다 (라운드 118)
                f"<p style='margin:4px 0 0 0; font-size:15px; font-weight:700; "
                f"color:{t['tx1']};'>{_esc(h.get('headline'))}</p>"
                f"<p style='margin:3px 0 0 0; font-size:12px; "
                f"color:{t['tx2']}; line-height:1.65;'>{_esc(h.get('body'))}"
                f" {_esc(h.get('add_note'))}</p></div>")

    # ④ 매수 후 규칙
    steps = ''.join(
        f"<li style='margin:0 0 3px 0;'><b style='color:{t['tx1']};'>"
        f"{_esc(k)}</b> — {_esc(v)}</li>"
        for k, v in (p.get('post_entry') or []))
    post = (f"<div><p style='margin:0 0 5px 0; font-size:12px; "
            f"font-weight:700; color:{t['tx2']};'>산 뒤에는</p>"
            f"<ul style='margin:0; padding-left:16px; font-size:12px; "
            f"color:{t['tx2']}; line-height:1.65;'>{steps}</ul>"
            f"<p style='margin:6px 0 0 0; font-size:12px;color:{t['tx3']}; "
            # 산문이라 `**굵게**` 를 해석한다 (라운드 120 — 여기 별표가
            # 글자로 나오고 있었다: "**각 지점의 최적 수치는 …**")
            f"line-height:1.6;'>{_esc_md(p.get('post_entry_caveat'))}"
            f"</p></div>"
            if steps else '')

    parts = [x for x in (mkt, buy, hold, post) if x]
    return (
        f"<div style='background:{t['card']}; border-radius:14px; "
        f"overflow:hidden; margin-bottom:14px;'>"
        f"<div style='height:3px; background:{t['brand']};'></div>"
        f"<div style='padding:15px 18px 17px; display:flex; "
        f"flex-direction:column; gap:13px;'>"
        f"<p style='margin:0; font-size:13px; font-weight:700; "
        f"color:{t['tx2']}; letter-spacing:0.01em;'>"
        f"내일 매매 지시서{(' · ' + _esc(name)) if name else ''}</p>"
        f"{''.join(parts)}</div></div>")


def attention_row(a: dict, theme: str = 'dark') -> str:
    """
    관심종목 후보 한 줄 — 추천 카드와 같은 표면·타이포·아이콘을 쓴다.

    이 목록은 '지금 시장이 주목하는가'이고 추천 카드는 '지금 살 만한가'다.
    둘은 다른 질문이라 카드 크기도 다르지만, **보이는 언어는 같아야** 한다.
    예전에는 이 목록만 옛 인라인 HTML(이모지 뱃지·왼쪽 색 테두리)이라
    같은 화면에서 두 가지 디자인이 보였다.

    a: {name, code, bucket, bucket_kind, attention, raw, action, reason,
        warns[]}
    """
    t = tokens(theme)
    KIND = {'pos': (t['pos'], 'ShieldCheck'), 'warn': (t['warn'], 'Clock3'),
            'info': (t['brand'], 'ChartNoAxesCombined'),
            'mute': (t['tx2'], 'Clock3'), 'neg': (t['neg'], 'TriangleAlert')}
    col, ic = KIND.get(a.get('bucket_kind', 'mute'), KIND['mute'])

    warn = ''
    if a.get('warns'):
        warn = (f"<p style='margin:4px 0 0 0; font-size:12px; "
                f"color:{t['warn']}; display:flex; align-items:center; "
                f"gap:6px;'>{_icon('TriangleAlert', t['warn'], 14)}"
                f"<span>{_esc(' · '.join(a['warns']))}</span></p>")

    return (
        f"<div style='background:{t['card']}; border-radius:12px; "
        f"overflow:hidden; margin-bottom:8px;'>"
        f"<div style='height:3px; background:{col};'></div>"
        f"<div style='padding:10px 14px 12px;'>"
        f"<div style='display:flex; align-items:baseline; gap:8px; "
        f"flex-wrap:wrap;'>"
        f"<span style='font-size:16px; font-weight:700; color:{t['tx1']};'>"
        f"{_esc(a.get('name', ''))}</span>"
        f"<span style='font-size:12px; color:{t['tx2']}; "
        f"font-variant-numeric:tabular-nums;'>{_esc(a.get('code', ''))}</span>"
        f"</div>"
        f"<p style='margin:3px 0 0 0; font-size:13px; font-weight:700; "
        f"color:{col}; display:flex; align-items:center; gap:6px;'>"
        f"{_icon(ic, col, 15)}<span>{_esc(a.get('bucket', ''))}</span></p>"
        f"<p style='margin:5px 0 0 0; font-size:13px; color:{t['tx2']}; "
        f"font-variant-numeric:tabular-nums;'>"
        f"시장 관심점수 <b style='color:{t['tx1']};'>{_esc(a.get('attention'))}"
        f"</b>"
        + (f" <span style='color:{t['tx3']};'>({_esc(a['raw'])})</span>"
           if a.get('raw') else '')
        + (f" · 퀀트 행동점수 <b style='color:{t['tx1']};'>"
           f"{_esc(a.get('action'))}</b>" if a.get('action') else '')
        + "</p>"
        + (f"<p style='margin:3px 0 0 0; font-size:12px; color:{t['tx3']}; "
           f"line-height:1.6;'>{_esc(a['reason'])}</p>"
           if a.get('reason') else '')
        + warn + "</div></div>")
