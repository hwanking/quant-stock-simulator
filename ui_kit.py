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
# 참조 화면(사용자 제공)의 색감 — 남색기를 뺀 중성 다크.
# 사이드바가 본문보다 살짝 밝고, 카드가 그 사이에 놓인다.
DARK = dict(bg='#0A0B0F', card='#16181F', raised='#1E2129',
            line='#282C35', tx1='#E9EBEF', tx2='#9BA1AC', tx3='#858C99',
            brand='#488AF7', up='#F1574C', down='#488AF7',
            pos='#2FBF71', warn='#E0A33E', neg='#E36363')
# 의미색 4개(brand·up·down·neg)는 명도를 조금씩 올린 값이다. 원래 값은
# 가장 밝은 카드면(#1C2635) 위에서 3.99~4.14 로 4.5:1 에 못 미쳤다 — 12·13px
# 글자가 많아 그냥 두면 안 된다. 색상·채도는 그대로 두고 명도만 올려
# 다크의 모든 표면에서 4.5 를 넘긴다 (_probe/fix_dark_contrast.py 로 계산).
#: 사이드바는 본문보다 한 단계 밝은 면 — 참조 화면과 같은 층 구조
DARK_NAV = '#101216'
LIGHT_NAV = '#F7F8FA'
LIGHT = dict(bg='#EFF1F6', card='#FFFFFF', raised='#F2F5F9',
             line='#E6EAF0', tx1='#111827', tx2='#4A4D53', tx3='#666873',
             brand='#2563EB', up='#D02E24', down='#186AD5',
             pos='#147C56', warn='#966319', neg='#C23E3E')
# 라이트의 의미색은 색상(hue)은 그대로 두고 명도만 낮췄다 — 흰 카드와
# 회색 배경 **양쪽에서** 4.5:1 을 넘겨야 하기 때문이다 (실측 4.53~4.59).
# 글자 3단은 눈대중이 아니라 실측으로 정했다 (WCAG 대비, 회색 배경·흰 카드 양쪽):
#   다크  tx1 15.6 · tx2 7.2 · tx3 4.8   |  라이트 tx1 15.7 · tx2 7.5 · tx3 4.9
# tx3 는 보조 설명 전용이며 4.5 미만으로 내려가면 안 된다 (작은 12px 글자가 많다).


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
    가늠 워드마크 — 글자 하나로 로고를 만든다.

    '가늠'은 가늠쇠에서 온 말이다. 가늠쇠는 총열 끝의 작은 표적 조준점이고,
    그 모양이 이 로고의 유일한 도형이다 — 원 안의 십자, 그리고 마침표.
    마침표는 '재보고 나서 결론을 낸다'는 뜻이다. 장식은 이게 전부다.

    ■ `href` (라운드 122)
      web_app 1529행에 "제목 자체를 홈 버튼으로 쓴다"고 **주석으로만**
      적혀 있었고, 코드는 맨 `<div>` 였다. 사이드바는 그 아래에서
      "제목을 누르면 첫 화면으로 돌아갑니다"라고 안내하고 있었다 —
      화면이 지키지 못할 약속을 하고 있었던 것이다.
      결정을 주석이 아니라 **코드**로 옮긴다.
    """
    t = tokens(theme)
    r = size * 0.42
    mark = (
        f"<svg width='{size}' height='{size}' viewBox='0 0 24 24' "
        f"fill='none' style='flex:0 0 auto;'>"
        f"<circle cx='12' cy='12' r='9' stroke='{t['brand']}' "
        f"stroke-width='1.6'/>"
        f"<path d='M12 3v4M12 17v4M3 12h4M17 12h4' stroke='{t['tx2']}' "
        f"stroke-width='1.6' stroke-linecap='round'/>"
        f"<circle cx='12' cy='12' r='2.4' fill='{t['brand']}'/></svg>")
    subhtml = (f"<span style='font-size:12px; color:{t['tx3']}; "
               f"font-weight:500; letter-spacing:0;'>{_esc(sub)}</span>"
               if sub else '')
    inner = (
        f"{mark}"
        f"<span style='font-size:{size * 0.78:.0f}px; font-weight:700; "
        f"color:{t['tx1']}; letter-spacing:-0.03em; line-height:1;'>가늠"
        f"<span style='color:{t['brand']};'>.</span></span>{subhtml}")
    box = "display:flex; align-items:center; gap:9px;"
    if not href:
        return f"<div style='{box}'>{inner}</div>"
    return (f"<a href='{_esc_attr(href)}' "
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
        col = t['brand'] if on else t['tx2']
        bg = (f"background:{t['raised']};" if on else '')
        out.append(
            f"<a href='{_esc_attr(it.get('href') or '#')}' class='qnav-item' "
            f"style='display:flex; align-items:center; gap:11px; "
            f"padding:9px 12px; border-radius:9px; {bg} "
            f"text-decoration:none; margin-bottom:2px;'>"
            f"{_icon(it.get('icon', 'doc'), col)}"
            f"<span style='font-size:13px; font-weight:{600 if on else 500}; "
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
            col = t['brand'] if on else t['tx2']
            bg = (f"background:{t['raised']};" if on else '')
            ic = (_icon(it['icon'], col, 15) if it.get('icon') else
                  f"<span style='width:15px;'></span>")
            out.append(
                f"<a href='{_esc_attr(it.get('href') or '#')}' class='qnav-sub' "
                f"style='display:flex; align-items:center; gap:10px; "
                f"padding:8px 10px; border-radius:8px; {bg} "
                f"text-decoration:none; margin-bottom:1px;'>{ic}"
                f"<span style='font-size:13px; "
                f"font-weight:{600 if on else 400}; color:{col}; "
                f"white-space:nowrap;'>{_esc(it['label'])}</span></a>")
    return ''.join(out)


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
        '  padding: 9px 11px !important; border-radius: 9px !important;',
        '  min-height: 0 !important; width: 100% !important; }',
        sb + ' div[class*="st-key-_acc_"] button p {',
        '  font-size: 13px !important; font-weight: 500 !important;',
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
            css.append(sel + ' button { background: ' + t['raised']
                       + ' !important; }')
            css.append(sel + ' button p { color: ' + t['brand']
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
            f"<div style='flex:1 1 0; min-width:124px; padding:4px 16px; "
            f"{border}'>"
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
        f"padding:20px 8px; display:flex; align-items:stretch; "
        f"overflow-x:auto; scrollbar-width:none;'>"
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
    """보조 설명 — 캡션보다 조용하게, 카드 밖에 둔다.

    산문이므로 `**굵게**` 를 해석한다 (_esc_md · 라운드 120).
    """
    t = tokens(theme)
    st.markdown(
        f"<p style='margin:8px 2px 0 2px; font-size:13px; color:{t['tx3']}; "
        f"line-height:1.6;'>{_esc_md(text)}</p>", unsafe_allow_html=True)


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
    _fail = [str(s).strip() for s in (fails or []) if str(s).strip()]
    if ok is None:
        return None, None, '아직 안 잼'
    if ok:
        return '가능', '물타기 가능', '6조건 전부 통과'
    if AVG_DOWN_DATA_GATE in _fail:
        return ('보류', '물타기 판정 보류',
                '표본·데이터 게이트를 못 넘어 판단하지 않았다 — 불가가 아니라 미판정(§3)')
    if _fail == [AVG_DOWN_MARKET_GATE]:
        # 라운드 224 — 첫 조건의 출처가 TOP3 깃발에서 **중앙 판정**(verdict_core.actionable)
        #   으로 바뀌었다. 사전등록 R224: 직전 관측 대비 하락 중인 매수권 케이스의
        #   적중률 차가 세 구간 CI95 모두 0 을 포함(train +1.7 · valid +3.9 · blind
        #   −5.8%p) — 하락 중이라는 사실이 판정을 바꾼다는 증거가 없어 물타기의
        #   첫 조건 = 신규 매수 판정이다. 5%p 미만은 이 잣대로 못 본다(R113).
        return ('시장게이트', '물타기 불가 · 신규 매수 판정만',
                '포지션 조건 5개는 통과 — 중앙 판정이 이 종목을 지금 살 수 있는 '
                '후보로 보지 않는다. 물타기의 첫 조건은 신규 매수 판정과 같다(R224: '
                '하락 중이라는 사실이 판정을 바꾼다는 증거 없음)')
    # 앞 셋만 적고 나머지는 '외 N' — 자르기는 슬라이스로 한다. 비교식에
    # 숫자를 두면 §2 문턱 검사(watch_action 안 Compare 의 숫자)에 걸린다.
    _head, _more = _fail[:3], _fail[3:]
    _why = ('미충족: ' + ' · '.join(_head)
            + (f' 외 {len(_more)}' if _more else '')) if _fail else '조건 미충족'
    return '포지션미달', '물타기 불가', _why


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
    h_stop = _n((row or {}).get('snap_hold_stop'))
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
    _ad_cls, _ad_label, _ad_why = avg_down_class(_ad_ok, _ad_fail)

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
        d['avg_down_ok'] = _ad_ok
        d['avg_down_class'] = _ad_cls
        d['avg_down_label'] = _ad_label
        d['avg_down_why'] = ((_ad_why or '') + ' · 이 판정은 R224 이전 스탬프(첫 조건이 TOP3 '
                             '깃발이던 때) — 다시 채우면 중앙 판정으로 갱신됩니다'
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
        d['hold_why'] = [w for w in why if w]
        _log = [s for s in str((row or {}).get('snap_hold_log') or '').split(' | ') if s]
        d['hold_log'] = _log
        return d

    if paid and px:
        # ── 보유자 관점 ────────────────────────────────────────────
        # ⚠️ 보유자 가격선이 **하나도 없으면 판단하지 않는다.** 없는 채로
        #   '보유 유지'라고 적으면 *못 잰 것*을 *판단*으로 만드는 것이라
        #   §3 위반이다. 화면 실측에서 실제로 13종목이 전부 '보유 유지'로
        #   나왔고, 그건 판단이 아니라 값이 없었던 것이다.
        if not (h_stop or h_trim):
            return _held(dict(kind='보유 기준 미산출', label='보유 기준 미산출',
                              tone='tx3', held=True,
                              why='이 종목의 보유자 기준값(버틸 수 없는 가격·팔 '
                                  '가격 1차)을 아직 안 냈습니다 — 채우면 판단합니다'))
        if h_stop and px <= h_stop:
            return _held(dict(kind='정리 검토', label='정리 검토', tone='neg',
                              held=True,
                              why=f'현재가가 버틸 수 없는 가격({h_stop:,.0f}원) 아래입니다'))
        if h_trim and px >= h_trim:
            return _held(dict(kind='일부 정리', label='일부 정리', tone='pos',
                              held=True,
                              why=f'1차 매도가({h_trim:,.0f}원)를 넘었습니다 '
                                  f'({(px / h_trim - 1) * 100:+.1f}%)'))
        # 라운드 224 — '추가 매수 가능'은 **물타기 판정과 같은 답**이어야 한다 (§4).
        #   종전엔 bucket 만 봐서, 물타기가 '불가'인 행에 '추가 매수 가능'이 찍힐 수
        #   있었다(한 종목에 "더 살 수 있나"의 답이 둘). 이제 6조건 전부 통과일 때만,
        #   그리고 엔진의 진입가 이하일 때만이다. 진입가 위면 '보유 유지'로 두고
        #   이유에 적는다.
        if _ad_ok and buy and px <= buy:
            return _held(dict(kind='추가 매수 가능', label='추가 매수 가능',
                              tone='pos', held=True,
                              why=f'물타기 6조건 전부 통과이고 진입가({buy:,.0f}원) '
                                  f'이하입니다'))
        return _held(dict(kind='보유 유지', label='보유 유지', tone='tx2', held=True,
                          why=(('버틸 수 없는 가격과 1차 매도가 사이입니다'
                                if (h_stop and h_trim) else
                                (f'버틸 수 없는 가격({h_stop:,.0f}원) 위입니다'
                                 if h_stop else
                                 f'1차 매도가({h_trim:,.0f}원)에 아직 못 미칩니다'))
                               + (f' · 물타기는 가능하나 진입가({buy:,.0f}원) 이하에서만'
                                  if (_ad_ok and buy and px > buy) else ''))))

    # ── 미보유 관점 — bucket 을 그대로 짧게 말한다 ──────────────────
    if not bucket:
        return None
    if bucket == '오늘 매수 가능':
        if buy and px and px <= buy:
            return dict(kind='매수 가능', label='지금 매수 가능', tone='pos',
                        held=False,
                        why=f'목표 매수가({buy:,.0f}원) 이하입니다')
        return dict(kind='매수 가능', label='매수 가능', tone='pos',
                    held=False,
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
        '데이터 부족': ('데이터 부족', 'tx3'),
        '추천 제외': ('사지 않음', 'neg'),
    }
    lbl, tone = _short.get(bucket, (bucket[:7], 'tx3'))
    return dict(kind=bucket, label=lbl, tone=tone, held=False, why=bucket)


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
            _row('1차 목표', _won(b.get('target')),
                 (f"{b['target_pct']:+.1f}%" if b.get('target_pct') else ''),
                 t['up']),
            _row('2차 목표', _won(b.get('target2')),
                 (f"{b['target2_pct']:+.1f}%" if b.get('target2_pct') else ''),
                 t['up']),
            _row('손절', _won(b.get('stop')),
                 (f"{b['stop_pct']:+.1f}%" if b.get('stop_pct') else ''),
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
