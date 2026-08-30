# -*- coding: utf-8 -*-
"""KRX 단축코드를 읽는 **한 곳** (라운드 164).

■ 왜 이 파일이 생겼나
  사용자가 두 종목을 못 찾았다.

    · SOL 팔란티어커버드콜OTM채권혼합  `0040Y0`
    · ACE 미국빅테크7+데일리타겟커버드콜(합성)  `480020`

  짐작하지 않고 쟀더니(`_probe/etf_code_probe.py`) 원인이 하나였다 —
  **이 저장소는 종목코드를 `\\d{6}` 으로만 읽는다.** 그런데 KRX 는 요즘
  문자가 섞인 6자리 코드를 발급한다. 네이버 ETF 목록 1,161종목 중
  **296종목(25.5%)** 이 그 모양이다. 네 자리 중 한 자리가 안 보였다.

  더 나쁜 것은 못 읽는 데서 그치지 않았다는 점이다:

    portfolio.normalize_code('0040Y0') → '000400'   ← 롯데손해보험
    portfolio.normalize_code('ACE 미국빅테크7') → '000007'

  숫자만 뽑아 zfill 하는 방식이라 **다른 종목의 코드를 만들어 냈다.**
  §3(없는 값을 지어내지 않는다)이 금지한 그것이고, 관심종목·보유종목이
  이 함수를 쓰므로 **남의 종목 값이 내 줄에 붙을 수 있었다.**

■ 왜 새 규칙을 만들지 않았나 (§2)
  이 저장소는 문자 포함 코드 규칙을 **이미 채택해 두고 있었다** —
  `portfolio._read_code_token` ③번 가지가 `[0-9][0-9A-Z]{5}` 에 숫자
  4자리 이상을 요구하며 주석에 `ETF '0040Y0'` 을 예로 적고 있다.
  OCR 경로에만 살아 있던 그 규칙을 여기로 올려 **모두가 같은 것을
  부르게** 한다. 새 문턱을 만들지 않았다.

■ 왜 호출부마다 고치지 않았나 (§6 · 라운드 120c~e)
  같은 결함을 호출부에서 세 번 고치고도 네 번째가 남았던 적이 있다.
  그래서 이번에는 **읽는 곳을 한 곳으로 모으고** 호출부는 그것을 부른다.
  검사(§201)가 `\\d{6}` 이 되살아나는지 본다.

■ 이 파일이 하지 않는 것 — 경계를 분명히 한다
  **유니버스·스캔·원장은 넓히지 않는다.** `fetch_market_listing`(시가총액
  순위 스크래핑)은 지금 그대로 숫자 6자리만 읽는다. 그것을 넓히면 ETF 가
  추천 스캔 모집단에 들어가 **연구 표본이 바뀐다** — R129 가 "결과를 본
  뒤에 잣대를 넓히지 않는다"고 참았던 자리와 같은 성격이다.
  여기서 넓히는 것은 **사용자가 직접 친 것을 찾아 주는 경로**뿐이다.

의존성 없음 — 어느 모듈에서든 import 할 수 있어야 한다.
"""
from __future__ import annotations

import re

#: KRX 단축코드 한 개의 모양. 첫 자리는 숫자이고 나머지는 숫자 또는 대문자.
#:   · 보통주·ETF 대부분  `005930` `480020`
#:   · 문자 포함 신형 코드 `0040Y0` `0087F0` `0193T0`
#: `portfolio._read_code_token` ③ 이 이미 쓰던 것과 같은 식이다 (§2 재사용).
CODE = r'[0-9][0-9A-Z]{5}'

#: 문자가 섞였을 때 요구하는 최소 숫자 개수. 위 함수가 쓰던 값 그대로.
_MIN_DIGITS = 4

#: 시장 접미사. 코드 자체가 아니므로 읽기 전에 떼어 낸다.
_SUFFIX = re.compile(r'\.(KS|KQ|KN|KRX)$', re.IGNORECASE)

#: HTS 종목번호 열의 접두 문자 ('A005930').
_PREFIX = 'A'

_RE_ONE = re.compile(f'^{CODE}$')
_RE_ANY = re.compile(CODE)
_RE_FLOAT_INT = re.compile(r'^(\d+)\.0+$')


def strip_suffix(s):
    """'005930.KS' → '005930'. 접미사가 없으면 그대로."""
    return _SUFFIX.sub('', str(s or '').strip())


def is_code(s):
    """정확히 KRX 단축코드 한 개인가. 접미사·접두는 미리 떼고 부른다."""
    up = str(s or '').strip().upper()
    if not _RE_ONE.match(up):
        return False
    if up.isdigit():
        return True
    return sum(c.isdigit() for c in up) >= _MIN_DIGITS


def _token_code(tok):
    """토큰 하나를 코드로 읽어 본다. 아니면 None — **지어내지 않는다.**"""
    t = strip_suffix(tok).strip().upper()
    if not t:
        return None
    # 'A005930' 처럼 접두가 붙은 7자리
    if len(t) == 7 and t[0] == _PREFIX:
        t = t[1:]
    # '5930.0' — 표 왕복에서 숫자형이 된 코드 (앞자리 0 이 날아간 뒤 소수 표기)
    m = _RE_FLOAT_INT.match(t)
    if m:
        t = m.group(1)
    if t.isdigit():
        # 순수 숫자는 자리수를 맞춘다. 6자리를 넘으면 뒤 6자리 (기존 규칙 유지).
        if len(t) > 6:
            t = t[-6:]
        return t.zfill(6)
    return t if is_code(t) else None


def normalize(raw):
    """
    어떤 표기든 KRX 단축코드 6자리로. 읽지 못하면 **None** 이다.

        'A005930' · '5930' · '005930.KS' · 5930.0  → '005930'
        '0040Y0' · '0040y0.KS'                     → '0040Y0'
        'ACE 미국빅테크7' · '삼성전자' · ''          → None

    ⚠️ 마지막 줄이 이 함수의 존재 이유다. 종전 구현은 숫자만 뽑아
       zfill 해서 'ACE 미국빅테크7' 을 **'000007'** 로, '0040Y0' 을
       **'000400'** 으로 바꿨다 — 둘 다 실재하는 **다른 종목**이다.
       못 읽는 것과 남의 코드를 만드는 것은 전혀 다른 실패다.
    """
    if raw is None:
        return None
    # numpy/pandas 의 NaN 을 import 없이 판별한다 (이 파일은 의존성이 없다)
    if isinstance(raw, float):
        if raw != raw:                                   # NaN
            return None
        if float(raw).is_integer():
            raw = int(raw)
    s = str(raw).strip()
    if not s or s.lower() in ('nan', 'none', '<na>', 'null'):
        return None

    # ① 통째로 코드인가 (가장 흔한 길)
    code = _token_code(s)
    if code:
        return code

    # ② 여러 낱말이면 낱말마다 본다 ('005930 삼성전자' · 'A002990 -462,205')
    #    ⚠️ 여기서 **숫자 조각을 이어 붙이지 않는다.** 종전 구현이 그렇게
    #       해서 이름에 든 숫자 하나가 코드가 됐다('ACE 미국빅테크7' → 000007).
    #    ⚠️ 그리고 낱말 단위에서는 **자리수를 채워 주지 않는다.** 수량·가격
    #       열이 딸려 들어왔을 때 '38' 같은 값이 코드가 되면 안 된다.
    for tok in re.split(r'[\s,;|/]+', s):
        bare = strip_suffix(tok).strip().upper()
        if len(bare) == 7 and bare[0] == _PREFIX:
            bare = bare[1:]
        if len(bare) != 6:
            continue
        c = _token_code(bare)
        if c:
            return c
    return None


def find_codes(text):
    """문자열·HTML 에서 코드로 보이는 것을 **모두** 뽑는다 (등장 순서)."""
    out, seen = [], set()
    for m in _RE_ANY.finditer(str(text or '').upper()):
        c = m.group(0)
        if is_code(c) and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def first_code(text):
    """`find_codes` 의 첫 번째. 없으면 None."""
    got = find_codes(text)
    return got[0] if got else None


#: 이 저장소의 라벨 약속 — `'이름 (코드)'`. 뉴스 띠(`?pick=`)·관심종목
#: 이름 버튼·최근 본 종목이 모두 이 모양으로 종목을 넘긴다.
_RE_LABEL = re.compile(r'\((' + CODE + r')\)\s*$')


def from_label(text):
    """
    `'이름 (코드)'` 를 코드로. 라벨이 아니면 `first_code` 와 같다.

    ⚠️ 앞에서부터 훑으면 **이름 조각이 코드가 될 수 있다.** 라벨에서는
       괄호 안이 코드라는 것이 약속이므로 그것을 먼저 읽는다.
    """
    m = _RE_LABEL.search(str(text or '').strip().upper())
    if m and is_code(m.group(1)):
        return m.group(1)
    return first_code(text)


def has_letter(code):
    """문자가 섞인 신형 코드인가 — 화면이 한계를 밝힐 때 쓴다."""
    return bool(code) and not str(code).isdigit()


#: KRX 가 문자 포함 코드에 **쓰지 않는** 글자 (라운드 189 실측).
#: 네이버 ETF 1,161종목 중 문자 포함 296종목이 쓰는 글자는
#: `ABCDEFGHJKLMNPRSTVWXYZ` 이고 **I·O·Q·U 가 한 번도 안 나온다.**
#: 그 넷은 정확히 숫자와 헷갈리는 글자들이다(I→1 · O→0 · Q→0) —
#: KRX 가 일부러 피한 것으로 보인다. 그래서 이 자리에 I·O·Q 가 있으면
#: **실재 코드가 아니라 오독**이라고 볼 수 있다.
#: ⚠️ 표본은 ETF 296종목이다. 다른 코드군에서 이 넷이 나오면 이 값을 고친다.
ALPHA_EXCLUDED = frozenset('IOQU')

#: 실재 KRX 문자코드의 모양 (라운드 189 실측 · 296/296 = 100%).
#:   `0` + 숫자 3 + **문자 1개(5번째 자리)** + 숫자 1
#: 296종목 전부가 이 모양이고 예외가 없었다. 순수 숫자코드는 구조상
#: 걸리지 않는다(자리 4가 숫자다).
_ALPHA_SHAPE = re.compile(r'0\d{3}[A-Z]\d')


def looks_like_krx_alpha(code):
    """이 토큰이 **실재하는 KRX 문자코드의 모양**인가 (라운드 189).

    ■ 왜 필요했나
      `portfolio._read_code_token` ② 가 *"섞인 글자가 전부 숫자로 오해받는
      글자면 OCR 오독"* 으로 보고 숫자로 되돌렸다. 그런데 KRX 가 실제로
      쓰는 글자(D·Z·G·A·S·T·B …)가 그 표에 다 들어 있어서, **진짜 코드가
      남의 코드로 바뀌었다.** 실측: 문자 포함 296개 중 **114개(38.5%)** —
      `0000Z0`(RISE AI TOP10) → `000020`(동화약품).

      라운드 165 가 적은 그대로다: *"못 읽었다는 표시가 남는 실패가
      조용히 남의 값이 되는 실패보다 낫다."*

    ■ 무엇으로 가르나 (감이 아니라 실측)
      실재 코드는 **문자가 정확히 하나, 5번째 자리**이고 그 글자가
      I·O·Q·U 가 아니다. OCR 오독은 글자가 아무 자리에나 오고, 흔한
      오독 글자가 바로 그 I·O·Q 다. 두 집합이 겹치지 않는다.
    """
    c = strip_suffix(str(code or '')).upper()
    if len(c) != 6 or not _ALPHA_SHAPE.fullmatch(c):
        return False
    return c[4] not in ALPHA_EXCLUDED
