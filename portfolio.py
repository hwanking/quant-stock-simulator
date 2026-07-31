"""
보유종목 · 평균 매수가 관리 모듈.

설계 원칙 (가장 중요):
    평균 매수가는 개인화된 보유·축소·손절 판단에만 사용하고,
    미래 예측 · 적정가 · 종목점수 · 유사패턴 검색에는 절대 넣지 않는다.
    평단가가 예측에 들어가면 "비싸게 샀으니 올라야 한다"는 앵커링 오류가 생긴다.

외부 연동 원칙:
    증권사 로그인 자동화 · 쿠키/세션 수집 · 비공식 보유자산 API 역공학은 하지 않는다.
    입력 경로는 CSV/Excel 가져오기 → 직접 입력 → 로컬 불러오기 → 클립보드 붙여넣기 순.
"""
from __future__ import annotations

import base64
import csv
import io
import json
import os
import re
from dataclasses import dataclass, asdict, field
from datetime import date, datetime

import numpy as np
import pandas as pd

# ─────────────────────────────────────────────────────────────────────────────
# 저장 위치 — 로컬 전용. 서버 전송 없음.
# ─────────────────────────────────────────────────────────────────────────────
PORTFOLIO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".portfolio")
PORTFOLIO_FILE = os.path.join(PORTFOLIO_DIR, "positions.json")

SOURCE_TYPES = ("csv_import", "excel_import", "manual_entry", "clipboard_paste", "local_restore")


@dataclass
class PortfolioPosition:
    ticker: str                      # 005930.KS 형태
    stock_name: str
    market: str                      # KOSPI / KOSDAQ
    quantity: float
    average_buy_price: float
    account_name: str | None = None      # 계좌 별칭 (계좌번호는 저장하지 않는다)
    broker_name: str | None = None
    acquisition_date: str | None = None
    source_type: str = "manual_entry"
    imported_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    dividend_received: float | None = None
    realized_pnl: float | None = None
    fees_paid: float | None = None

    @property
    def code(self) -> str:
        return self.ticker.split('.')[0]

    @property
    def cost_basis(self) -> float:
        return self.quantity * self.average_buy_price


# ─────────────────────────────────────────────────────────────────────────────
# 계좌번호 마스킹 — 저장·로그 어디에도 원본을 남기지 않는다
# ─────────────────────────────────────────────────────────────────────────────
_ACCOUNT_PAT = re.compile(r'\d{2,}[-\s]?\d{2,}[-\s]?\d{2,}')


def mask_account(text):
    """계좌번호처럼 보이는 숫자열을 마스킹한다."""
    if not text:
        return text
    return _ACCOUNT_PAT.sub(lambda m: m.group(0)[:3] + "*" * max(0, len(m.group(0)) - 5) + m.group(0)[-2:],
                            str(text))


def anonymize_for_llm(positions):
    """
    LLM·외부 API 로 보낼 때 쓰는 최소 익명화 뷰.
    수량·평단가·계좌·증권사는 제거하고 종목코드와 비중만 남긴다.
    """
    total = sum(p.cost_basis for p in positions) or 1.0
    return [{"code": p.code, "weight_pct": round(p.cost_basis / total * 100, 1)} for p in positions]


# ─────────────────────────────────────────────────────────────────────────────
# CSV / Excel 가져오기
# ─────────────────────────────────────────────────────────────────────────────
COLUMN_ALIASES = {
    "ticker": ["종목코드", "단축코드", "종목번호", "티커", "코드", "symbol", "ticker", "code"],
    "stock_name": ["종목명", "종목", "상품명", "name", "종목이름"],
    "quantity": ["보유수량", "잔고수량", "수량", "보유주식수", "잔고", "quantity", "shares"],
    "average_buy_price": ["평균매수가", "매입평균가", "평단가", "매입단가", "평균단가",
                          "매입가", "avg_price", "average_price"],
    "cost_amount": ["매입금액", "매입원금", "총매입금액", "취득금액"],
    "market_value": ["평가금액", "평가액", "현재평가금액"],
    "broker_name": ["증권사", "broker", "회사"],
    "account_name": ["계좌", "계좌명", "계좌별칭", "account"],
    "acquisition_date": ["매수일", "최초매수일", "취득일", "매입일"],
}

REQUIRED_FIELDS = ("ticker", "stock_name", "quantity", "average_buy_price")


def _norm(s):
    return re.sub(r'[\s_\-\(\)\[\]/]', '', str(s)).lower()


def suggest_column_mapping(columns):
    """실제 열 이름 → 표준 필드 자동 매핑 제안. 실패한 필드는 None."""
    normalized = {_norm(c): c for c in columns}
    mapping = {}
    for field_name, aliases in COLUMN_ALIASES.items():
        found = None
        for alias in aliases:
            key = _norm(alias)
            if key in normalized:
                found = normalized[key]
                break
        if found is None:                      # 부분 일치 2차 시도
            for alias in aliases:
                key = _norm(alias)
                for norm_col, orig in normalized.items():
                    if key and key in norm_col:
                        found = orig
                        break
                if found:
                    break
        mapping[field_name] = found
    return mapping


def read_table(file_bytes, filename):
    """CSV/Excel 바이트 → DataFrame. 한글 인코딩 자동 판별."""
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(file_bytes))
    for enc in ("utf-8-sig", "cp949", "euc-kr", "utf-8"):
        try:
            return pd.read_csv(io.BytesIO(file_bytes), encoding=enc)
        except (UnicodeDecodeError, pd.errors.ParserError):
            continue
    raise ValueError("CSV 인코딩을 판별하지 못했습니다 (utf-8 / cp949 / euc-kr 시도).")


def parse_clipboard_table(text):
    """탭 또는 쉼표로 구분된 붙여넣기 표 → DataFrame."""
    if not text or not text.strip():
        raise ValueError("붙여넣은 내용이 비어 있습니다.")
    sample = text.strip().split("\n")[0]
    delim = "\t" if "\t" in sample else ("," if "," in sample else None)
    if delim is None:
        raise ValueError("열 구분자를 찾지 못했습니다 (탭 또는 쉼표).")
    return pd.DataFrame(list(csv.DictReader(io.StringIO(text), delimiter=delim)))


# ─────────────────────────────────────────────────────────────────────────────
# 스크린샷 → 텍스트 (OCR)
# 로컬 OCR 엔진이 있을 때만 동작한다. 엔진이 없으면 지어내지 않고 사유를 돌려준다.
# ─────────────────────────────────────────────────────────────────────────────
def ocr_backend():
    """사용 가능한 OCR 백엔드 이름 또는 None."""
    try:
        import pytesseract
        import shutil as _sh
        if _sh.which("tesseract") or getattr(pytesseract.pytesseract, "tesseract_cmd", None):
            return "pytesseract"
    except Exception:
        pass
    try:
        import easyocr  # noqa: F401
        return "easyocr"
    except Exception:
        pass
    return None


OCR_INSTALL_HINT = (
    "스크린샷 인식에는 로컬 OCR 엔진이 필요합니다.\n\n"
    "① 간편 (설치 한 줄):  pip install easyocr\n"
    "② 가벼움: Tesseract 설치 후  pip install pytesseract\n"
    "   (Tesseract 설치 시 한국어 데이터 'kor' 포함 필요)\n\n"
    "설치 전에는 아래 '표 붙여넣기'를 이용하세요 — 화면에서 표를 드래그해 복사하면 됩니다."
)

_EASYOCR_READER = None

# 브라우저에서 붙여넣은 이미지의 상한. 캡처 한 장은 보통 100KB~2MB 이고,
# 이보다 큰 값은 사용자가 의도한 화면 캡처가 아닐 가능성이 높다.
PASTE_MAX_BYTES = 12 * 1024 * 1024


def decode_pasted_image(payload):
    """
    브라우저 붙여넣기 컴포넌트가 돌려준 값 → (image_bytes, error).

    payload 는 {'data_url': 'data:image/png;base64,...', ...} 형태다.
    서버 클립보드가 아니라 **사용자 브라우저의 클립보드**에서 온 것이므로
    원격 접속에서도 안전하게 쓸 수 있다. 이미지는 이 앱 서버까지만 가고
    외부 서비스로 보내지 않는다.
    """
    if not isinstance(payload, dict):
        return None, None
    url = payload.get('data_url')
    if not url or not isinstance(url, str):
        return None, None
    if not url.startswith("data:image/"):
        return None, "이미지가 아닙니다. 화면을 캡처한 그림을 붙여넣어 주세요."
    try:
        header, _, b64 = url.partition(",")
        if "base64" not in header or not b64:
            return None, "붙여넣은 데이터를 해석하지 못했습니다."
        raw = base64.b64decode(b64, validate=False)
    except Exception as exc:
        return None, f"붙여넣은 이미지를 해석하지 못했습니다 ({type(exc).__name__})."
    if not raw:
        return None, "붙여넣은 이미지가 비어 있습니다."
    if len(raw) > PASTE_MAX_BYTES:
        return None, (f"이미지가 너무 큽니다 ({len(raw) / 1048576:.1f}MB). "
                      f"{PASTE_MAX_BYTES // 1048576}MB 이하로 표 영역만 캡처해 주세요.")
    return raw, None


def extract_text_from_image(image_bytes, langs=("ko", "en")):
    """
    이미지 바이트 → 텍스트. 반환: (text, backend, error)
    OCR 결과는 줄 단위로 재구성해 parse_freeform_holdings 가 그대로 받을 수 있게 한다.
    """
    backend = ocr_backend()
    if backend is None:
        return None, None, "OCR 엔진 미설치"

    try:
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes))
        img.load()
    except Exception as exc:
        return None, backend, f"이미지를 읽을 수 없습니다 ({type(exc).__name__})"

    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    # 저해상도 캡처는 확대하면 인식률이 크게 올라간다
    if max(img.size) < 1400:
        scale = 1400 / max(img.size)
        img = img.resize((int(img.width * scale), int(img.height * scale)))

    try:
        if backend == "pytesseract":
            import pytesseract
            text = pytesseract.image_to_string(img, lang="kor+eng")
            return text, backend, None

        global _EASYOCR_READER
        import easyocr
        import numpy as _np
        if _EASYOCR_READER is None:
            _EASYOCR_READER = easyocr.Reader(list(langs), gpu=False, verbose=False)
        results = _EASYOCR_READER.readtext(_np.array(img), detail=1, paragraph=False)
        # 신뢰도 하한은 낮게 잡는다. 어차피 확정 전에 미리보기 표에서 사람이 검수하므로,
        # 글자를 흘리는 쪽이 잘못 읽는 쪽보다 손해가 크다(종목명이 통째로 사라진다).
        boxes = []
        for box, txt, conf in results:
            if conf < 0.20 or not str(txt).strip():
                continue
            ys = [p[1] for p in box]
            xs = [p[0] for p in box]
            boxes.append({
                'yc': sum(ys) / len(ys),
                'h': max(ys) - min(ys),
                'x': min(xs),
                'xc': sum(xs) / len(xs),
                'text': str(txt).strip(),
            })
        if not boxes:
            return "", backend, None

        # 줄 묶기: 고정 격자로 나누면 경계값에서 같은 줄이 둘로 쪼개진다
        # (예: 중심 104.9 와 105.1 이 서로 다른 칸으로 감). 글자 높이에 비례한
        # 허용오차로 순차 군집화한다.
        boxes.sort(key=lambda b: b['yc'])
        med_h = sorted(b['h'] for b in boxes)[len(boxes) // 2]
        tol = max(6.0, med_h * 0.6)
        lines, cur, ref = [], [boxes[0]], boxes[0]['yc']
        for b in boxes[1:]:
            if abs(b['yc'] - ref) <= tol:
                cur.append(b)
                ref = sum(c['yc'] for c in cur) / len(cur)   # 줄 중심을 갱신
            else:
                lines.append(cur)
                cur, ref = [b], b['yc']
        lines.append(cur)

        # HTS 잔고 화면처럼 헤더가 있는 표는 열 위치를 살려야 한다. 토큰을 그냥
        # 왼쪽부터 이어붙이면 '잔고 400 / 가능 200 / 손익분기 10,267 / … / 매수평균
        # 10,246' 같은 줄에서 몇 번째 숫자가 평단가인지 알 방법이 없다.
        # 헤더 줄을 찾아 그 x중심을 열 기준으로 삼고, 각 토큰을 가장 가까운 열에 넣는다.
        hdr_i, hdr_cols = _detect_header_line(lines)
        if hdr_cols:
            out = ["\t".join(c['text'] for c in hdr_cols)]
            for i, ln in enumerate(lines):
                if i == hdr_i:
                    continue
                cells = [[] for _ in hdr_cols]
                for b in sorted(ln, key=lambda b: b['x']):
                    j = min(range(len(hdr_cols)),
                            key=lambda k: abs(b['xc'] - hdr_cols[k]['xc']))
                    cells[j].append(b['text'])
                out.append("\t".join(" ".join(c) for c in cells))
            return "\n".join(out), backend, None

        out = []
        for ln in lines:
            parts = [b['text'] for b in sorted(ln, key=lambda b: b['x'])]
            out.append("  ".join(parts))            # 2칸 공백 = 열 구분자
        return "\n".join(out), backend, None
    except Exception as exc:
        return None, backend, f"{type(exc).__name__}: {exc}"


# ─────────────────────────────────────────────────────────────────────────────
# 표 헤더 인식
# HTS·증권사 앱 잔고 화면은 열이 10개를 넘고 숫자 열만 6~7개다. 순서 추측으로는
# 평단가를 절대 못 집는다. 헤더 이름으로 열을 특정한다.
# ─────────────────────────────────────────────────────────────────────────────

#: 필드 → 헤더 이름 후보 (앞쪽이 우선). 공백을 제거하고 부분일치로 본다.
#:
#: 뒤쪽 5개(current_price ~ cost_basis)는 **저장 대상이 아니라 검증용**이다.
#: 증권사 잔고 화면은 같은 사실을 여러 열로 중복 표기한다:
#:     평가손익 = (현재가 − 평단가) × 수량,  수익률 = 현재가 ÷ 평단가 − 1
#: 이 중복이 OCR 오독을 잡아내는 유일한 근거다. 예전에는 이 열들을 읽고도 버렸다.
COLUMN_SYNONYMS = {
    'code':     ('종목코드', '단축코드', '표준코드', '코드'),
    'name':     ('종목명', '상품명', '종목', '종목이름'),
    'quantity': ('보유수량', '잔고수량', '결제잔고', '잔고', '보유주식수', '주식수',
                 '보유량', '수량', '보유'),
    'price':    ('매수평균', '매입평균', '평균매수가', '평균매입가', '평균단가',
                 '매입단가', '매수단가', '평단가', '평단', '매입가'),
    # ── 검증 전용 (저장하지 않는다) ──
    'current_price': ('현재가', '현재단가', '시장가', '기준가'),
    'return_pct':    ('수익률', '손익률', '수익율'),
    'pnl':           ('평가손익', '평가손실', '손익금액', '평가손익금액'),
    'market_value':  ('평가금액', '평가금'),
    'cost_basis':    ('매입금액', '매수금액', '매입금', '취득금액'),
}

#: 저장하지 않고 검증에만 쓰는 필드
VALIDATION_FIELDS = ('current_price', 'return_pct', 'pnl', 'market_value', 'cost_basis')

#: 절대 수량·평단가로 잡으면 안 되는 열.
#:  · 손익분기 = 수수료·세금까지 반영한 본전가라서 평단가보다 크다. 이걸 평단가로
#:    쓰면 손익이 전부 어긋난다.
#:  · 가능 = 매도가능수량. 대출·미수가 있으면 잔고보다 작다.
COLUMN_EXCLUDE = ('손익분기', '매도가능', '가능', '대비', '등락',
                  '구분', '실현손익', '비중', '통화', '계좌')

#: quantity/price 에만 적용되는 추가 배제어 (검증 필드로는 잡혀야 하므로 분리한다)
COLUMN_EXCLUDE_FOR_CORE = ('현재가', '수익률', '평가손익', '평가금액', '매입금액',
                           '평가금', '매입금', '손익률', '수익율')

#: 헤더 줄인지 판정할 때 세는 단어 (위 두 목록 전체 + 일반적인 표 머리말)
_HEADER_VOCAB = tuple(set(
    sum((list(v) for v in COLUMN_SYNONYMS.values()), []) + list(COLUMN_EXCLUDE)))


def _norm_header(text):
    return re.sub(r'[\s\-_/()\[\]]', '', str(text or ''))


def classify_header_cells(cells):
    """
    헤더 셀 목록 → {필드: 열 인덱스}. 찾지 못한 필드는 넣지 않는다.

    수량·평단가는 배제어가 강하게 걸린다 (손익분기·가능·현재가 등을 절대 잡으면 안 됨).
    검증 필드(현재가·수익률·평가손익…)는 그 배제어 자체가 목표 열이므로 따로 다룬다.
    """
    norm = [_norm_header(c) for c in cells]
    blocked = set()
    for i, n in enumerate(norm):
        if any(x in n for x in COLUMN_EXCLUDE):
            blocked.add(i)

    mapping = {}
    for field, cands in COLUMN_SYNONYMS.items():
        is_core = field in ('code', 'name', 'quantity', 'price')
        for cand in cands:                       # 앞쪽 후보가 우선
            for i, n in enumerate(norm):
                if i in blocked or i in mapping.values() or not n:
                    continue
                if is_core and any(x in n for x in COLUMN_EXCLUDE_FOR_CORE):
                    continue
                if cand in n:
                    mapping[field] = i
                    break
            if field in mapping:
                break
    return mapping


def _detect_header_line(lines):
    """
    OCR 줄 목록에서 헤더 줄을 찾는다. 반환: (줄 인덱스, 헤더 박스 목록) 또는 (None, None).
    헤더 어휘가 3개 이상 맞고, 종목명·수량·평단가 중 둘 이상을 특정할 수 있어야 한다.
    """
    best = (0, None, None)
    for i, ln in enumerate(lines):
        cols = sorted(ln, key=lambda b: b['x'])
        texts = [b['text'] for b in cols]
        hits = sum(1 for t in texts if any(v in _norm_header(t) for v in _HEADER_VOCAB))
        if hits < 3:
            continue
        mp = classify_header_cells(texts)
        if len(set(mp) & {'name', 'quantity', 'price', 'code'}) < 2:
            continue
        if hits > best[0]:
            best = (hits, i, cols)
    return (best[1], best[2]) if best[2] else (None, None)


def grab_clipboard_image():
    """
    OS 클립보드의 이미지를 PNG 바이트로 돌려준다. 반환: (png_bytes, error)

    이 앱은 사용자 PC에서 직접 도는 로컬 서버이므로 서버 프로세스가 곧 사용자의
    클립보드를 본다. 원격 서버에 올려 쓰는 경우에는 서버 쪽 클립보드를 읽게 되므로
    이 경로를 노출하면 안 된다.

    Win+Shift+S(캡처 도구), PrtSc, 브라우저에서 이미지 복사 모두 지원한다.
    파일 탐색기에서 이미지 파일을 복사한 경우도 받아준다.
    """
    try:
        from PIL import Image, ImageGrab
    except Exception as exc:
        return None, f"Pillow 를 불러오지 못했습니다 ({type(exc).__name__})"

    try:
        obj = ImageGrab.grabclipboard()
    except Exception as exc:
        # 리눅스에서는 xclip/wl-paste 가 없으면 여기로 떨어진다
        return None, f"이 환경에서는 클립보드를 읽을 수 없습니다 ({type(exc).__name__})"

    if obj is None:
        return None, ("클립보드에 이미지가 없습니다. "
                      "Win+Shift+S 로 화면을 캡처한 뒤 다시 누르세요.")

    img = None
    if isinstance(obj, Image.Image):
        img = obj
    elif isinstance(obj, list):
        # 이미지 파일을 복사한 경우 경로 목록이 온다
        for path in obj:
            try:
                img = Image.open(path)
                img.load()
                break
            except Exception:
                continue
        if img is None:
            return None, "클립보드의 파일을 이미지로 열지 못했습니다."
    else:
        return None, f"클립보드 내용이 이미지가 아닙니다 ({type(obj).__name__})"

    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), None


#: OCR 이 자주 헷갈리는 글자 → 숫자. 종목코드 자리에서만 적용한다.
_OCR_DIGIT_LOOKALIKE = {
    'O': '0', 'o': '0', 'D': '0', 'Q': '0',
    'I': '1', 'l': '1', 'i': '1', '|': '1',
    'Z': '2', 'z': '2',
    'A': '4',
    'S': '5', 's': '5',
    'G': '6', 'b': '6',
    'T': '7',
    'B': '8',
    'g': '9', 'q': '9',
}


def repair_ocr_code(token):
    """
    OCR이 흘린 종목코드를 되살린다. 예: '0OO66O' → '000660'.

    종목코드 자리(맨 앞 토큰 또는 A접두)에서만 호출해야 한다. 6자리이고 절반 이상이
    이미 숫자일 때만 손대며, 그 밖의 글자가 하나라도 섞이면 포기한다 — 종목명을
    숫자로 망가뜨리는 쪽이 못 읽고 넘어가는 쪽보다 훨씬 위험하다.
    반환: 교정된 6자리 문자열 또는 None.
    """
    t = str(token or "").replace(" ", "")
    if len(t) != 6:
        return None
    if sum(c.isdigit() for c in t) < 3:
        return None
    out = []
    for c in t:
        if c.isdigit():
            out.append(c)
        elif c in _OCR_DIGIT_LOOKALIKE:
            out.append(_OCR_DIGIT_LOOKALIKE[c])
        else:
            return None
    fixed = "".join(out)
    return fixed if fixed != t else None


def _signed_number(cell):
    """
    부호와 %를 살려서 읽는다. '-9.62%' → -9.62, '+93,299' → 93299.

    _cell_number 는 부호·% 가 붙은 값을 걸러낸다 (평가손익 열을 평단가로 잡지 않기 위해).
    반대로 검증용 열은 부호가 정보 그 자체라 따로 읽어야 한다 —
    마이너스 부호를 흘리면 손실이 이익으로 뒤집힌다.
    """
    s = str(cell or '').strip()
    if not s:
        return None
    neg = s.lstrip('▲▼△▽ ').startswith('-') or '▼' in s
    s2 = re.sub(r'[^\d,.]', '', s)
    s2 = re.sub(r'(?<=\d),(?=\d{3}(?!\d))', '', s2)
    s2 = s2.replace(',', '.')
    if s2.count('.') > 1:                      # '1.234.5' 같은 오인식은 버린다
        return None
    try:
        v = float(s2)
    except ValueError:
        return None
    return -v if neg else v


def _cell_number(cell):
    """표 셀에서 수치만 뽑는다. '▲ 1,100' → 1100, '-2,50%' → None(부호·%는 제외)."""
    s = str(cell or '').strip()
    if not s:
        return None
    if '%' in s or s.lstrip('▲▼△▽+').startswith('-'):
        return None
    s = re.sub(r'[^\d,.\-]', '', s)
    s = re.sub(r'(?<=\d),(?=\d{3}(?!\d))', '', s)      # 천 단위 구분자 제거
    s = s.replace(',', '.')                            # 남은 쉼표는 소수점 오인식
    try:
        v = float(s)
    except ValueError:
        return None
    return v if v > 0 else None


def _split_cells(line):
    """
    한 줄 → 셀 목록. 구분자를 탭 → 2칸이상 공백 → 1칸 공백 순으로 시도한다.

    HTS 화면을 드래그 복사하면 열 사이가 한 칸 공백뿐인 경우가 흔하다.
    탭일 때는 빈 셀도 위치 정보이므로 버리지 않는다.
    """
    if '\t' in line:
        return [c.strip() for c in line.split('\t')]
    if re.search(r'\s{2,}', line):
        return [c.strip() for c in re.split(r'\s{2,}', line) if c.strip()]
    return line.split()


def _align_cells(line, n_cols, name_i, code_i):
    """
    데이터 줄을 헤더 열 수에 맞춰 정렬한다.

    토큰 수가 열 수와 다른 경우가 대부분이다:
      · '구분' 열이 비어 있어 토큰이 하나 모자람
      · 종목명에 공백이 있어 토큰이 남음 ('SOL 팔란티')
    숫자 열은 전부 종목명 오른쪽에 몰려 있으므로 **오른쪽부터 맞춘다**.
    왼쪽에 남는 토큰을 종목명으로 본다.
    """
    if '\t' in line:
        cells = [c.strip() for c in line.split('\t')]
        return (cells + [''] * (n_cols - len(cells)))[:n_cols]

    toks = _split_cells(line)
    if not toks:
        return []
    # 토큰 수가 열 수와 같아도 그대로 쓰면 안 된다. 종목명에 공백이 있고('SOL 팔란티')
    # 동시에 '구분' 열이 비어 있으면 개수가 우연히 맞아떨어져 이름이 잘린다.
    # 숫자 열은 항상 오른쪽에 몰려 있으므로 오른쪽 정렬이 언제나 더 안전하다.
    if name_i is None:
        return (toks + [''] * (n_cols - len(toks)))[:n_cols]

    right_n = n_cols - name_i - 1
    if right_n < 0 or len(toks) < right_n + 1:
        return (toks + [''] * (n_cols - len(toks)))[:n_cols]

    aligned = [''] * n_cols
    right = toks[len(toks) - right_n:] if right_n > 0 else []
    left = toks[:len(toks) - right_n]
    for k, v in enumerate(right):
        aligned[name_i + 1 + k] = v
    if code_i is not None and code_i < name_i and left:
        aligned[code_i] = left[0]
        left = left[1:]
    # 앞쪽에 남은 기호(구분 열의 +/- 표시 등)는 종목명이 아니다
    while len(left) > 1 and not re.search(r'[가-힣A-Za-z0-9]', left[0]):
        left = left[1:]
    aligned[name_i] = ' '.join(left).strip()
    return aligned


#: 헤더 없이 이만큼 많은 숫자가 한 줄에 있으면 어느 것이 평단가인지 알 수 없다
AMBIGUOUS_NUMBER_COUNT = 5


def preview_columns(text, max_rows=3):
    """
    붙여넣은 표를 셀 단위로 쪼개 미리 보여준다 (열 직접 지정 UI용).
    반환: (열 개수, [행별 셀 목록])
    """
    lines = [l for l in str(text or '').splitlines() if l.strip()]
    rows = [_split_cells(l) for l in lines[:max_rows + 1]]
    rows = [r for r in rows if r]
    n = max((len(r) for r in rows), default=0)
    return n, [(r + [''] * (n - len(r))) for r in rows]


def parse_with_explicit_columns(text, name_col=None, code_col=None,
                                qty_col=None, price_col=None, skip_rows=0,
                                resolve_name=None):
    """
    사용자가 직접 지정한 열 번호로 해석한다.
    헤더가 없거나 열 이름을 알아보지 못했을 때의 최종 수단이다.
    추측하지 않으므로 지정이 맞다면 결과도 맞다.
    """
    if qty_col is None or price_col is None:
        return [], ["수량 열과 평단가 열을 모두 지정해야 합니다."]

    all_lines = [l for l in str(text or '').splitlines() if l.strip()]
    # 열 번호는 미리보기 표를 보고 고른 것이다. 미리보기와 같은 정렬 규칙을 써야
    # 종목명에 공백이 있는 행에서 열이 한 칸씩 밀리지 않는다.
    n_cols = max((len(_split_cells(l)) for l in all_lines), default=0)
    lines = all_lines[int(skip_rows):]
    rows, warnings = [], []
    for line in lines:
        cells = _align_cells(line, n_cols, name_col, code_col)
        if not cells:
            continue

        def at(i):
            return cells[i] if (i is not None and 0 <= i < len(cells)) else ''

        qty = _cell_number(at(qty_col))
        price = _cell_number(at(price_col))
        name = at(name_col).strip()
        raw_code = at(code_col).replace(' ', '')

        code = None
        if raw_code:
            if re.fullmatch(r'A?\d{6}', raw_code):
                code = normalize_code(raw_code)
            else:
                fixed = repair_ocr_code(raw_code)
                if fixed:
                    code = normalize_code(fixed)
                    warnings.append(f"종목코드 교정: '{raw_code}' → '{fixed}' (확인 필요)")

        if not name and not code:
            continue
        if qty is None or price is None:
            warnings.append(f"건너뜀 (지정한 열에서 수치를 읽지 못함): {(name or code)[:20]}")
            continue

        ticker = f"{code}.KS" if code else None
        if ticker is None and name and resolve_name:
            try:
                t, real = resolve_name(name)
                if t:
                    ticker, code = t, str(t).split('.')[0]
                    if real:
                        name = real
            except Exception:
                pass
        rows.append({'종목코드': code or '', '종목명': name or (code or ''),
                     '보유수량': qty, '평균매수가': price, '_ticker': ticker})
    if not rows:
        warnings.append("지정한 열로 읽은 종목이 없습니다. 건너뛸 줄 수나 열 번호를 확인하세요.")
    return rows, warnings


def parse_table_with_header(text, resolve_name=None):
    """
    헤더가 있는 표를 열 이름으로 해석한다. 헤더를 못 찾으면 None 을 돌려주고
    호출자가 자유형식 추정으로 넘어가게 한다. 반환: (rows, warnings) | None

    HTS 잔고 화면처럼 숫자 열이 예닐곱 개인 표에서 '몇 번째 숫자가 평단가인가'를
    추측으로 맞히는 것은 불가능하다. 반드시 헤더로 특정해야 한다.
    """
    raw_lines = [l for l in str(text or '').splitlines() if l.strip()]
    if len(raw_lines) < 2:
        return None

    # 헤더가 여러 줄로 쪼개져 들어오는 경우가 흔하다 (화면 폭에 맞춰 줄바꿈된 복사본).
    # 숫자가 없고 헤더 어휘만 있는 앞쪽 줄들은 한 줄로 합친다.
    def _looks_header_only(line):
        if re.search(r'\d', line):
            return False
        cells = _split_cells(line)
        return sum(1 for c in cells
                   if any(v in _norm_header(c) for v in _HEADER_VOCAB)) >= 2

    merged, i = [], 0
    while i < len(raw_lines) and i < 4 and _looks_header_only(raw_lines[i]):
        merged.append(raw_lines[i].rstrip())
        i += 1
    if len(merged) >= 2:
        # 구분자를 섞으면 안 된다. 조각들이 한 칸 공백으로 나뉘어 있는데 '  ' 로 이으면
        # 2칸공백 분할이 먼저 걸려 조각 전체가 한 셀이 되어버린다.
        if any('\t' in m for m in merged):
            sep = '\t'
        elif any(re.search(r'\s{2,}', m) for m in merged):
            sep = '  '
        else:
            sep = ' '
        raw_lines = [sep.join(merged)] + raw_lines[i:]

    hdr_idx, mapping, hdr_cells = None, None, None
    for i, line in enumerate(raw_lines[:5]):        # 헤더는 앞쪽에 있다
        cells = _split_cells(line)
        if len(cells) < 3:
            continue
        hits = sum(1 for c in cells if any(v in _norm_header(c) for v in _HEADER_VOCAB))
        if hits < 3:
            continue
        mp = classify_header_cells(cells)
        if 'quantity' in mp and 'price' in mp and ('name' in mp or 'code' in mp):
            hdr_idx, mapping, hdr_cells = i, mp, cells
            break
    if mapping is None:
        return None

    n_cols = len(hdr_cells)
    name_i = mapping.get('name')
    code_i = mapping.get('code')

    rows, warnings = [], []
    warnings.append(
        "표 헤더를 인식했습니다 — " + ", ".join(
            f"{k}={hdr_cells[v]}" for k, v in sorted(mapping.items())))

    for line in raw_lines[hdr_idx + 1:]:
        cells = _align_cells(line, n_cols, name_i, code_i)
        if not cells:
            continue

        def cell(field):
            i = mapping.get(field)
            return cells[i] if (i is not None and i < len(cells)) else ''

        code = None
        raw_code = cell('code').replace(' ', '')
        if raw_code:
            if re.fullmatch(r'A?\d{6}', raw_code):
                code = normalize_code(raw_code)
            else:
                fixed = repair_ocr_code(raw_code)
                if fixed:
                    code = normalize_code(fixed)
                    warnings.append(f"종목코드 인식 교정: '{raw_code}' → '{fixed}' (확인 필요)")

        name = cell('name').strip()
        qty = _cell_number(cell('quantity'))
        price = _cell_number(cell('price'))

        if not name and not code:
            continue
        # 합계·소계 줄은 종목이 아니다
        if any(k in _norm_header(name) for k in ('합계', '소계', '총계', '평가합계')):
            continue
        if qty is None or price is None:
            warnings.append(f"건너뜀 (수량·평단가를 읽지 못함): {(name or code)[:20]}")
            continue

        ticker = f"{code}.KS" if code else None
        if ticker is None and name and resolve_name:
            try:
                t, real = resolve_name(name)
                if t:
                    ticker = t
                    code = str(t).split('.')[0]
                    if real:
                        name = real
            except Exception:
                pass
        if ticker is None:
            # 이름 오독(예: '코텍'→'코택')으로 조회에 실패해도 행을 버리지 않는다.
            # 수량·평단가는 제대로 읽었으므로, 미리보기에서 이름·코드만 고치면 살릴 수 있다.
            # 여기서 조용히 지우면 사용자는 종목이 빠진 사실조차 모른다.
            warnings.append(
                f"'{name[:20]}' 종목을 찾지 못했습니다 — 미리보기에서 종목코드를 "
                f"직접 넣거나 종목명을 고쳐 주세요 (OCR 오독일 수 있습니다).")

        row = {'종목코드': code or '', '종목명': name or (code or ''),
               '보유수량': qty, '평균매수가': price, '_ticker': ticker}
        # ── 화면에서 읽은 값 = 독립 증거 (_scr_*) ────────────────────────
        # 이 값들은 나중에 실시간 시세로 덮어쓰면 안 된다.
        # 실시간 시세에서 파생한 수익률·평가손익으로 평단가를 검증하면
        # `평가손익 = (현재가−평단)×수량` 이 항등식이 되어 아무것도 못 잡는다.
        row['_scr_현재가'] = _cell_number(cell('current_price'))
        row['_scr_수익률'] = _signed_number(cell('return_pct'))
        row['_scr_평가손익'] = _signed_number(cell('pnl'))
        row['_market_value'] = _cell_number(cell('market_value'))
        row['_cost_basis'] = _cell_number(cell('cost_basis'))
        # 표시용 열 — 실시간 시세가 붙기 전까지는 화면값을 그대로 보여준다
        row['현재가'] = row['_scr_현재가']
        row['수익률'] = row['_scr_수익률']
        row['평가손익'] = row['_scr_평가손익']
        rows.append(row)

    if not rows:
        warnings.append("표는 인식했지만 종목 행을 하나도 읽지 못했습니다.")
    return rows, warnings


def parse_freeform_holdings(text, resolve_name=None):
    """
    자유 형식 붙여넣기 파서.

    네이버 증권 '내 자산' 화면이나 증권사 앱에서 표를 그대로 드래그해 복사하면
    헤더가 없거나 줄바꿈이 뒤섞인 형태로 들어온다. 그런 입력도 받아낸다.

    인식하는 형태 (한 줄에 하나의 종목):
        005930  삼성전자  10  210,000
        삼성전자 10주 210,000원
        삼성전자,10,210000
        005930 10 210000

    resolve_name(name) -> (ticker, real_name) 로 종목명을 코드로 바꾼다.
    반환: (rows, warnings) — rows 는 dict 목록이며 UI에서 미리보기·수정 후 확정한다.
    """
    if not text or not text.strip():
        return [], ["붙여넣은 내용이 비어 있습니다."]

    # 헤더가 있는 표(HTS 잔고 화면 등)는 열 이름으로 정확히 집을 수 있다.
    # 숫자 순서 추측은 열이 많은 화면에서 반드시 틀리므로 이쪽을 먼저 시도한다.
    table = parse_table_with_header(text, resolve_name=resolve_name)
    if table is not None:
        return table

    rows, warnings = [], []
    HEADER_TOKENS = ("종목", "수량", "평단", "매입", "평가", "코드", "보유", "손익", "수익률")

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # 헤더 줄 건너뛰기
        if sum(1 for t in HEADER_TOKENS if t in line) >= 2 and not re.search(r'\d{3,}', line):
            continue

        # ⚠️ 천 단위 구분자를 먼저 제거한다.
        #    이걸 안 하면 쉼표로 split 할 때 '210,000' 이 '210' + '000' 으로 쪼개진다.
        norm = line
        for _ in range(4):
            norm2 = re.sub(r'(?<=\d),(?=\d{3}(?!\d))', '', norm)
            if norm2 == norm:
                break
            norm = norm2

        parts = [p.strip() for p in re.split(r'\t|,|\s{2,}', norm) if p.strip()]
        if len(parts) < 2:
            parts = norm.split()

        # ── 1) 종목코드 식별 ──────────────────────────────────────────────
        #    6자리 숫자는 평단가(예: 210000)일 수도 있으므로 아무거나 코드로 보면 안 된다.
        #    'A' 접두, 맨 앞 토큰, 또는 0으로 시작하는 경우만 코드로 인정한다.
        code, code_idx = None, -1
        for i, tok in enumerate(parts):
            t = tok.replace(" ", "")
            if re.fullmatch(r'A\d{6}', t):
                code, code_idx = normalize_code(t), i
                break
            if re.fullmatch(r'\d{6}', t) and (i == 0 or t.startswith('0')):
                code, code_idx = normalize_code(t), i
                break
            # 스크린샷 인식본은 0↔O, 5↔S 처럼 글자가 섞여 들어온다. 맨 앞 토큰에
            # 한해 되살려 보고, 고쳤다는 사실을 반드시 경고로 남겨 검수하게 한다.
            if i == 0:
                fixed = repair_ocr_code(t)
                if fixed:
                    code, code_idx = normalize_code(fixed), i
                    warnings.append(f"종목코드 인식 교정: '{t}' → '{fixed}' (확인 필요)")
                    break

        # ── 2) 나머지 토큰에서 종목명과 수치 분리 ─────────────────────────
        name, numbers = None, []
        for i, tok in enumerate(parts):
            if i == code_idx:
                continue
            m_qty = re.fullmatch(r'([\d.]+)\s*주', tok)
            m_amt = re.fullmatch(r'([\d.]+)\s*원', tok)
            if m_qty:
                numbers.append(('qty', _to_number(m_qty.group(1))))
                continue
            if m_amt:
                numbers.append(('amt', _to_number(m_amt.group(1))))
                continue
            if re.fullmatch(r'[+\-]?[\d.]+\s*%?', tok):
                # 수익률(%)과 부호가 붙은 값(+365,000 = 평가손익)은 입력값이 아니다.
                # 수량·평단가에는 부호를 붙이지 않는다.
                if tok.rstrip().endswith('%') or tok.startswith(('+', '-')):
                    continue
                v = _to_number(tok)
                if v is not None:
                    numbers.append(('num', v))
                continue
            if name is None and not re.fullmatch(r'[\d.,+\-%원₩]+', tok):
                name = tok

        if code is None and not name:
            warnings.append(f"건너뜀 (종목 식별 불가): {line[:40]}")
            continue

        qty = next((v for k, v in numbers if k == 'qty'), None)
        price = next((v for k, v in numbers if k == 'amt'), None)
        plain = [v for k, v in numbers if k == 'num' and v is not None]

        # 단위 표기가 없을 때의 추정:
        #  - 수치가 3개 이상이면 뒤쪽은 매입금액·평가금액·손익일 가능성이 크므로
        #    앞의 두 개만 쓴다 (표는 보통 [종목명, 수량, 평단가, 금액...] 순서)
        #  - 둘 중 작은 값을 수량, 큰 값을 평단가로 본다 (순서가 뒤바뀐 표도 흡수)
        if qty is None and price is None and len(plain) >= AMBIGUOUS_NUMBER_COUNT:
            # 헤더 없이 숫자만 대여섯 개인 줄(HTS 잔고 화면을 헤더 없이 복사한 경우)에서
            # '앞의 두 개'를 골라잡으면 매도가능수량을 평단가로 넣는 식으로 반드시 틀린다.
            # 틀린 값을 조용히 넣느니 읽지 못했다고 말하고 사람이 지정하게 한다.
            warnings.append(
                f"'{(name or code or line[:14])}' — 한 줄에 숫자가 {len(plain)}개라 "
                f"어느 것이 수량·평단가인지 알 수 없습니다. **헤더 줄(종목명·잔고·매수평균 …)을 "
                f"함께 복사**하거나 아래 표에서 직접 입력하세요.")
            rows.append({'종목코드': code or '', '종목명': name or (code or ''),
                         '보유수량': None, '평균매수가': None, '_ticker': None})
            continue
        if qty is None and price is None and len(plain) >= 2:
            head = plain[:2]
            qty, price = min(head), max(head)
        elif qty is None and price is not None and plain:
            qty = min(plain)
        elif price is None and qty is not None and plain:
            price = max(plain)

        if not qty or not price:
            warnings.append(f"건너뜀 (수량·평단가를 찾지 못함): {line[:40]}")
            continue

        ticker = None
        if resolve_name:
            # 코드가 있으면 코드로, 없으면 종목명으로 조회한다.
            # 코드로 조회하면 정확한 종목명과 시장(.KS/.KQ)까지 함께 확정된다.
            try:
                t, real = resolve_name(code or name)
                if t:
                    ticker = t
                    if real and real != (code or ""):
                        name = real
            except Exception:
                pass
        if ticker is None and code:
            ticker = f"{code}.KS"      # 조회 실패 시 코드만으로 진행 (시장은 KOSPI 가정)
        if ticker is None:
            warnings.append(f"건너뜀 (종목코드를 찾지 못함): {name or line[:40]}")
            continue

        rows.append({
            "종목코드": ticker.split('.')[0],
            "종목명": name or ticker.split('.')[0],
            "보유수량": float(qty),
            "평균매수가": float(price),
            "_ticker": ticker,
        })

    if not rows and not warnings:
        warnings.append("인식된 행이 없습니다. '종목명 수량 평단가' 순서로 붙여넣어 보세요.")
    return rows, warnings


def clean_cell_str(v):
    """
    표 셀 → 문자열 또는 None.

    ⚠️ st.data_editor 는 값을 Arrow 로 왕복시킨다. 값이 전부 비어 있는 열은
    돌아올 때 None 이 아니라 **float('nan')** 이 된다. NaN 은 참(truthy)이라
    `if not ticker:` 같은 검사를 그대로 통과해버리고, 뒤에서 `.endswith()` 를
    부르는 순간 AttributeError 로 터진다. 여기서 한 번에 정규화한다.
    """
    if v is None:
        return None
    if isinstance(v, float) and np.isnan(v):
        return None
    s = str(v).strip()
    if not s or s.lower() in ('nan', 'none', '<na>'):
        return None
    return s


# ─────────────────────────────────────────────────────────────────────────────
# 인식 결과 검증 (§12·§13·§14)
#
# 핵심 발상: 증권사 잔고 화면은 같은 사실을 여러 열로 중복 표기한다.
#     평가손익 = (현재가 − 평단가) × 수량
#     수익률   = 현재가 ÷ 평단가 − 1
# 실측해 보면 이 관계가 오차 0.2% 이내로 성립한다. 따라서 한 값이 오독되면
# 나머지와 어긋나고, **어긋난다는 사실 자체로 오독을 잡아낼 수 있다.**
# 나아가 현재가와 수익률로 평단가를 역산할 수 있어 후보값도 제시할 수 있다.
# ─────────────────────────────────────────────────────────────────────────────

#: 상대오차 허용치 (실측 기준 0.0~0.2% 였으므로 여유를 둔다)
TOL_PASS = 0.01        # 1% 이내 통과
TOL_WARN = 0.03        # 3% 이내 주의, 초과는 오류

#: OCR 이 자주 헷갈리는 숫자쌍 — 일괄 치환이 아니라 후보 생성에만 쓴다
_DIGIT_CONFUSIONS = (('1', '7'), ('7', '1'), ('3', '8'), ('8', '3'),
                     ('0', '8'), ('8', '0'), ('5', '6'), ('6', '5'),
                     ('0', '9'), ('9', '0'), ('1', '4'), ('4', '1'))


def _rel_err(a, b):
    """상대오차. 둘 중 하나라도 없으면 None."""
    if a is None or b is None:
        return None
    denom = max(abs(a), abs(b), 1e-9)
    return abs(a - b) / denom


def digit_candidates(value, max_out=6):
    """
    한 자리씩 흔한 오인식으로 바꿔 본 후보들. 일괄 치환이 아니라 **후보 생성**이다.
    785000 → 185000, 735000, 785000 … 처럼 '어느 자리가 틀렸을 수 있는지'를 넓힌다.
    """
    if value is None:
        return []
    s = f"{int(round(float(value)))}"
    out = []
    for i, ch in enumerate(s):
        for a, b in _DIGIT_CONFUSIONS:
            if ch != a:
                continue
            cand = s[:i] + b + s[i + 1:]
            if cand.startswith('0') and len(cand) > 1:
                continue
            try:
                v = float(cand)
            except ValueError:
                continue
            if v > 0 and v != value and v not in out:
                out.append(v)
    return out[:max_out]


def enrich_with_market_prices(rows, quote_fn):
    """
    표시용 현재가·수익률·평가손익을 **실시간 시세**로 채운다.

    OCR 이 읽은 현재가는 열이 어긋나면 엉뚱한 값이 들어온다(영원무역 90원, 대한항공 26원).
    시세는 조회하면 되는 값이므로 화면에서 읽을 이유가 없다.

    ⚠️ 화면에서 읽은 값(_scr_*)은 절대 덮어쓰지 않는다.
       그것만이 평단가·수량을 **독립적으로** 검증할 근거이기 때문이다.
       실시간 시세에서 파생한 수익률로 평단가를 검증하면 항등식이 되어 무의미하다.

    반환: (rows, 조회성공수, 조회실패목록)
    """
    ok, failed = 0, []
    for r in rows:
        ticker = clean_cell_str(r.get('_ticker'))
        if not ticker:
            code = normalize_code(r.get('종목코드'))
            ticker = f"{code}.KS" if code else None
        px = None
        if ticker:
            try:
                px = quote_fn(ticker)
            except Exception:
                px = None
        if not px or px <= 0:
            if ticker:
                failed.append(str(r.get('종목명') or ticker))
            r['현재가'] = None
            r['수익률'] = None
            r['평가손익'] = None
            r['_price_source'] = '조회실패'
            continue

        px = float(px)
        qty = _to_number(r.get('보유수량'))
        avg = _to_number(r.get('평균매수가'))
        r['현재가'] = px
        r['수익률'] = round((px / avg - 1.0) * 100.0, 2) if (avg and avg > 0) else None
        r['평가손익'] = round((px - avg) * qty, 0) if (avg and qty) else None
        r['_price_source'] = '실시간'
        ok += 1
    return rows, ok, failed


def validate_row(row, market_price=None):
    """
    한 행의 숫자 정합성을 검증한다.

    market_price: 실시간 시세(선택). 화면에 현재가가 없거나 오독됐을 때의 기준점.
    반환 dict:
        checks       : [{name, ok, detail}]
        implied_price: 수익률·현재가로 역산한 평단가
        suggestions  : {'평균매수가': [후보...], '보유수량': [...]}
        severity     : 'ok' | 'warn' | 'error'
        confidence   : 0~100
    """
    qty = _to_number(row.get('보유수량'))
    avg = _to_number(row.get('평균매수가'))

    # ⚠️ 검증에는 **화면에서 읽은 값(_scr_*)만** 쓴다.
    #    표시용 현재가·수익률·평가손익은 실시간 시세에서 파생한 값이라
    #    그걸로 평단가를 검증하면 `평가손익 = (현재가−평단)×수량` 이 항등식이 된다.
    #    _scr_ 키가 없는 입력(직접 입력·CSV)은 예전처럼 표시값을 쓴다.
    has_scr = any(k in row for k in ('_scr_현재가', '_scr_수익률', '_scr_평가손익'))
    if has_scr:
        cur = _to_number(row.get('_scr_현재가'))
        ret = _to_number(row.get('_scr_수익률'))
        pnl = _to_number(row.get('_scr_평가손익'))
    else:
        cur = _to_number(row.get('현재가'))
        ret = _to_number(row.get('수익률'))
        pnl = _to_number(row.get('평가손익'))
    mval = _to_number(row.get('_market_value'))
    cost = _to_number(row.get('_cost_basis'))

    # 실시간 시세는 '그럴듯함' 판정에만 쓴다 (독립 증거가 아니므로 교차검증에는 안 쓴다)
    live = market_price if (market_price and market_price > 0) else None
    if cur is None:
        cur = live

    checks, sugg = [], {}

    def add(name, ok, detail=""):
        checks.append({'name': name, 'ok': ok, 'detail': detail})

    # ① 필수값 존재
    add("보유수량 인식", qty is not None and qty > 0,
        "미인식" if qty is None else f"{qty:,.0f}주")
    add("평균매수가 인식", avg is not None and avg > 0,
        "미인식" if avg is None else f"{avg:,.0f}원")
    add("종목 식별", bool(clean_cell_str(row.get('_ticker'))
                       or normalize_code(row.get('종목코드'))),
        str(row.get('종목명') or ''))

    # ② 수익률 ↔ 현재가 ↔ 평단가
    implied = None
    if cur and ret is not None and (1.0 + ret / 100.0) != 0:
        implied = cur / (1.0 + ret / 100.0)
    if implied and avg:
        e = _rel_err(avg, implied)
        ok = e is not None and e <= TOL_WARN
        add("평단가 ↔ 수익률 역산", ok,
            f"표시 {avg:,.0f}원 vs 역산 {implied:,.0f}원 (오차 {e * 100:.1f}%)")
        if not ok:
            # 역산값에 가까운 자리오독 후보를 우선 제시한다
            cands = [c for c in digit_candidates(avg)
                     if _rel_err(c, implied) is not None and _rel_err(c, implied) <= TOL_WARN]
            sugg['평균매수가'] = cands or [round(implied)]
    elif implied and not avg:
        sugg['평균매수가'] = [round(implied)]
        add("평단가 ↔ 수익률 역산", False, f"평단가 미인식 — 역산값 {implied:,.0f}원")

    # ③ 평가손익 = (현재가 − 평단가) × 수량
    if pnl is not None and cur and avg and qty:
        calc = (cur - avg) * qty
        e = _rel_err(calc, pnl)
        ok = e is not None and e <= TOL_WARN
        add("평가손익 = (현재가−평단)×수량", ok,
            f"표시 {pnl:,.0f} vs 계산 {calc:,.0f} (오차 {e * 100:.1f}%)")
        if not ok and cur != avg:
            implied_qty = pnl / (cur - avg)
            # 역산 수량이 1주 미만이면 다른 값이 틀린 것이다 — 엉뚱한 후보를 내지 않는다
            if implied_qty >= 1:
                cands = [c for c in digit_candidates(qty)
                         if abs(c - implied_qty) / max(abs(implied_qty), 1) <= TOL_WARN]
                sugg['보유수량'] = cands or [round(implied_qty)]

    # ④ 평가금액 = 현재가 × 수량 / 매입금액 = 평단가 × 수량
    if mval and cur and qty:
        e = _rel_err(cur * qty, mval)
        add("평가금액 = 현재가×수량", e is not None and e <= TOL_WARN,
            f"표시 {mval:,.0f} vs 계산 {cur * qty:,.0f}")
    if cost and avg and qty:
        e = _rel_err(avg * qty, cost)
        add("매입금액 = 평단×수량", e is not None and e <= TOL_WARN,
            f"표시 {cost:,.0f} vs 계산 {avg * qty:,.0f}")

    # ⑤ 부호 정합 — 마이너스가 흘러가면 손실이 이익으로 뒤집힌다
    if pnl is not None and ret is not None:
        add("평가손익·수익률 부호 일치", (pnl >= 0) == (ret >= 0),
            f"손익 {pnl:,.0f} / 수익률 {ret:+.2f}%")

    # ⑥ 실시간 시세 대비 그럴듯함 — 화면에 검증 열이 없어도 극단값은 잡을 수 있다.
    #    독립 증거가 아니므로 '교차검증'이 아니라 '개연성'으로만 다룬다.
    if live and avg and avg > 0:
        live_ret = (live / avg - 1.0) * 100.0
        plausible = -90.0 <= live_ret <= 400.0
        add("실시간 시세 대비 평단가 개연성", plausible,
            f"현재가 {live:,.0f}원 기준 수익률 {live_ret:+.1f}%"
            + ("" if plausible else " — 평단가 자릿수 오독 가능"))
        if not plausible:
            cands = [c for c in digit_candidates(avg)
                     if -90.0 <= (live / c - 1.0) * 100.0 <= 400.0]
            if cands:
                sugg.setdefault('평균매수가', cands)

    fired = [c for c in checks if not c['ok']]
    if any(c['name'] in ("보유수량 인식", "평균매수가 인식", "종목 식별") for c in fired):
        severity = 'error'
    elif fired:
        severity = 'warn'
    else:
        severity = 'ok'

    # 신뢰도: 검증 통과 비율 기반. 교차검증할 열이 없으면 상한을 낮춘다
    cross = [c for c in checks if c['name'] not in
             ("보유수량 인식", "평균매수가 인식", "종목 식별")]
    if not cross:
        conf = 60.0 if severity != 'error' else 20.0
        add("교차검증 가능 열", False, "현재가·수익률·평가손익 열이 없어 대조 불가")
    else:
        passed = sum(1 for c in cross if c['ok'])
        conf = 55.0 + 45.0 * (passed / len(cross))
        if severity == 'error':
            conf = min(conf, 30.0)
    return {
        'checks': checks,
        'implied_price': implied,
        'suggestions': sugg,
        'severity': severity,
        'confidence': round(float(np.clip(conf, 0, 100)), 1),
    }


def validate_portfolio(rows, screen_totals=None, market_prices=None):
    """
    행별 검증 + 포트폴리오 합계 검증 (§13).

    screen_totals: {'market_value':…, 'pnl':…, 'cost_basis':…} 화면에 찍힌 합계.
    market_prices: {ticker: price} 실시간 시세(선택).
    반환: (검증붙은 rows, summary)
    """
    out = []
    s_val = s_cost = s_pnl_derived = s_pnl_shown = 0.0
    have_val = have_cost = have_derived = have_shown = False
    contrib = []            # 파생-표시 손익 차이가 큰 행을 짚어주기 위한 기록

    for r in rows:
        mp = None
        if market_prices:
            mp = market_prices.get(clean_cell_str(r.get('_ticker')) or '')
        v = validate_row(r, market_price=mp)
        rr = dict(r)
        rr['_validation'] = v
        out.append(rr)

        qty = _to_number(r.get('보유수량'))
        avg = _to_number(r.get('평균매수가'))
        # 합계 검증도 '화면에서 읽은 값' 대 '저장할 값으로 재계산한 값'의 대조여야 한다.
        # 양쪽 다 실시간 시세에서 나오면 항등식이 되어 아무것도 못 잡는다.
        has_scr = '_scr_평가손익' in r or '_scr_현재가' in r
        cur = (_to_number(r.get('_scr_현재가')) if has_scr
               else _to_number(r.get('현재가'))) or mp
        shown = (_to_number(r.get('_scr_평가손익')) if has_scr
                 else _to_number(r.get('평가손익')))

        if qty and cur:
            s_val += qty * cur
            have_val = True
        if qty and avg:
            s_cost += qty * avg
            have_cost = True
        # ⚠️ 파생 손익은 **저장할 값(수량·평단가)** 으로 계산해야 한다.
        #    OCR 이 읽은 평가손익 열을 그대로 더하면, 수량을 400→4 로 잘못 읽어도
        #    합계가 그대로라 검증이 아무것도 잡아내지 못한다.
        derived = (cur - avg) * qty if (qty and avg and cur) else None
        if derived is not None:
            s_pnl_derived += derived
            have_derived = True
        if shown is not None:
            s_pnl_shown += shown
            have_shown = True
        if derived is not None and shown is not None:
            contrib.append((abs(derived - shown), str(r.get('종목명') or ''),
                            derived, shown))

    totals = {
        'rows': len(out),
        'ok': sum(1 for r in out if r['_validation']['severity'] == 'ok'),
        'warn': sum(1 for r in out if r['_validation']['severity'] == 'warn'),
        'error': sum(1 for r in out if r['_validation']['severity'] == 'error'),
        'sum_market_value': s_val if have_val else None,
        'sum_cost_basis': s_cost if have_cost else None,
        'sum_pnl_derived': s_pnl_derived if have_derived else None,
        'sum_pnl_shown': s_pnl_shown if have_shown else None,
        'checks': [],
        'blocking': False,
    }

    def _add_check(label, mine, shown_v):
        if mine is None or shown_v is None:
            return
        e = _rel_err(mine, shown_v)
        lvl = 'ok' if e <= TOL_PASS else ('warn' if e <= TOL_WARN else 'error')
        totals['checks'].append({
            'name': label, 'level': lvl,
            'detail': f"표시 {shown_v:,.0f} vs 저장값 기준 {mine:,.0f} (오차 {e * 100:.2f}%)"})
        if lvl == 'error':
            totals['blocking'] = True

    # ① 화면에 찍힌 손익 열 합계 ↔ 저장할 수량·평단가로 재계산한 손익 합계.
    #    화면 총계가 없어도 검증이 성립한다 (열 자체가 화면에 있으므로).
    _add_check("행별 평가손익 합계", totals['sum_pnl_derived'], totals['sum_pnl_shown'])

    # ② 화면 하단 총계가 있으면 그것과도 대조
    st = screen_totals or {}
    _add_check("화면 총 평가금액", totals['sum_market_value'], _to_number(st.get('market_value')))
    _add_check("화면 총 매입금액", totals['sum_cost_basis'], _to_number(st.get('cost_basis')))
    _add_check("화면 총 평가손익", totals['sum_pnl_derived'], _to_number(st.get('pnl')))

    # 오차에 가장 크게 기여한 행을 짚어 준다
    if any(c['level'] != 'ok' for c in totals['checks']) and contrib:
        contrib.sort(reverse=True)
        totals['worst_rows'] = [
            {'name': n, 'derived': d, 'shown': s, 'gap': g}
            for g, n, d, s in contrib[:3] if g > 1]
    return out, totals


def can_save_row(row):
    """§20 저장 조건. 사용자가 확인(_confirmed)했거나 검증이 깨끗해야 한다."""
    v = row.get('_validation') or validate_row(row)
    if v['severity'] == 'error':
        return False, "필수값 미인식 또는 종목 미식별"
    if v['severity'] == 'warn' and not row.get('_confirmed'):
        return False, "검증 경고 — 확인 후 저장하세요"
    return True, ""


def rows_to_positions(rows, source_type="clipboard_paste", resolve_market=None):
    """미리보기 표(dict 목록) → PortfolioPosition 목록."""
    out, warns = [], []
    for r in rows:
        code = normalize_code(clean_cell_str(r.get("종목코드")))
        qty = _to_number(r.get("보유수량"))
        avg = _to_number(r.get("평균매수가"))
        name = (clean_cell_str(r.get("종목명")) or code or "").strip()
        if not code:
            warns.append(f"[{name or '이름 없음'}] 종목코드가 없어 제외")
            continue
        if not qty or qty <= 0:
            warns.append(f"[{name}] 보유수량이 0 이하이거나 비어 있어 제외 ({qty})")
            continue
        if not avg or avg <= 0:
            warns.append(f"[{name}] 평균 매수가가 0 이하이거나 비어 있어 제외 ({avg})")
            continue
        # ⚠️ 종목코드가 사용자가 직접 고칠 수 있는 유일한 식별자다.
        #    _ticker 는 숨겨진 열이라 표에서 고칠 수 없다. 둘이 어긋나면 **종목코드가 이긴다**.
        #    예전에는 _ticker 가 이겨서, 표에서 종목코드를 009970→111770 으로 고쳐도
        #    반영 버튼이 옛 종목을 그대로 저장했다 ("반영해도 안 바뀐다"의 원인).
        hint = clean_cell_str(r.get("_ticker"))
        hint_code = normalize_code(hint) if hint else None
        if hint and hint_code == code:
            ticker = hint                      # 코드가 같으면 시장 접미사를 그대로 쓴다
        else:
            market = None
            if resolve_market:
                try:
                    market = resolve_market(code)
                except Exception:
                    market = None
            ticker = f"{code}{'.KQ' if market == 'KOSDAQ' else '.KS'}"
            if hint and hint_code and hint_code != code:
                warns.append(f"[{name}] 종목코드를 {hint_code} → {code} 로 바꿔 반영했습니다.")
        out.append(PortfolioPosition(
            ticker=ticker, stock_name=name,
            market="KOSDAQ" if ticker.endswith(".KQ") else "KOSPI",
            quantity=float(qty), average_buy_price=float(avg),
            source_type=source_type))
    return out, warns


def positions_to_rows(positions):
    """PortfolioPosition 목록 → 편집용 표."""
    return [{"종목코드": p.code, "종목명": p.stock_name,
             "보유수량": p.quantity, "평균매수가": p.average_buy_price,
             "_ticker": p.ticker} for p in positions]


def _to_number(v):
    """'1,234,500원' / '₩1,234' / '1 234' → float. 실패 시 None."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    if isinstance(v, (int, float, np.number)):
        return float(v)
    s = re.sub(r'[^\d\.\-]', '', str(v))
    if s in ("", "-", "."):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def normalize_code(raw):
    """
    종목코드 6자리 정규화. 'A005930', '5930', '005930.KS' 모두 처리.

    ⚠️ 표 왕복(Arrow/엑셀)에서 종목코드 열이 숫자형으로 바뀌면 '005930' 이 5930.0 이 된다.
       그대로 숫자만 뽑으면 '59300' → 059300 이라는 **없는 종목코드**가 만들어진다.
       소수점 표기를 먼저 걷어낸 뒤 자리수를 맞춘다.
    """
    if raw is None:
        return None
    if isinstance(raw, float):
        if np.isnan(raw):
            return None
        if float(raw).is_integer():
            raw = int(raw)
    s = str(raw).strip()
    if not s or s.lower() in ('nan', 'none', '<na>'):
        return None
    # '5930.0' 처럼 정수를 실수로 표기한 문자열도 정수부만 쓴다
    m = re.fullmatch(r'(\d+)\.0+', s)
    if m:
        s = m.group(1)
    digits = re.sub(r'\D', '', s)
    if not digits:
        return None
    if len(digits) > 6:
        digits = digits[-6:]
    return digits.zfill(6)


def import_positions(df, mapping, resolve_market=None, source_type="csv_import"):
    """
    매핑된 DataFrame → (positions, warnings).
    검증 실패 행은 버리지 않고 사유와 함께 warnings 로 돌려준다.
    """
    positions, warnings = [], []
    missing = [f for f in REQUIRED_FIELDS if not mapping.get(f)]
    if missing:
        raise ValueError(f"필수 열이 매핑되지 않았습니다: {', '.join(missing)}")

    for idx, row in df.iterrows():
        line = idx + 2
        code = normalize_code(row.get(mapping['ticker']))
        name = str(row.get(mapping['stock_name']) or "").strip()
        qty = _to_number(row.get(mapping['quantity']))
        avg = _to_number(row.get(mapping['average_buy_price']))

        if not code:
            warnings.append(f"{line}행: 종목코드를 읽지 못해 제외 ({row.get(mapping['ticker'])!r})")
            continue
        if qty is None or qty <= 0:
            warnings.append(f"{line}행 [{name or code}]: 보유수량이 0 이하이거나 비어 있어 제외 ({qty})")
            continue
        if avg is None or avg <= 0:
            # 매입금액이 있으면 역산한다
            cost = _to_number(row.get(mapping.get('cost_amount'))) if mapping.get('cost_amount') else None
            if cost and qty:
                avg = cost / qty
                warnings.append(f"{line}행 [{name or code}]: 평단가가 없어 매입금액÷수량으로 산출 ({avg:,.0f}원)")
            else:
                warnings.append(f"{line}행 [{name or code}]: 평균 매수가가 0 이하이거나 비어 있어 제외 ({avg})")
                continue

        market = resolve_market(code) if resolve_market else "KOSPI"
        suffix = ".KQ" if market == "KOSDAQ" else ".KS"

        positions.append(PortfolioPosition(
            ticker=f"{code}{suffix}",
            stock_name=name or code,
            market=market,
            quantity=float(qty),
            average_buy_price=float(avg),
            account_name=mask_account(row.get(mapping['account_name'])) if mapping.get('account_name') else None,
            broker_name=str(row.get(mapping['broker_name'])) if mapping.get('broker_name') else None,
            acquisition_date=str(row.get(mapping['acquisition_date'])) if mapping.get('acquisition_date') else None,
            source_type=source_type,
        ))
    return positions, warnings


def merge_duplicate_positions(positions):
    """
    같은 종목이 여러 계좌에 있으면 계좌별 내역은 보존하고 통합 평단가를 만든다.
    반환: [{ticker, stock_name, market, quantity, average_buy_price, accounts:[...]}, ...]
    """
    by_ticker = {}
    for p in positions:
        by_ticker.setdefault(p.ticker, []).append(p)

    merged = []
    for ticker, group in by_ticker.items():
        total_qty = sum(g.quantity for g in group)
        if total_qty <= 0:
            continue
        combined = sum(g.quantity * g.average_buy_price for g in group) / total_qty
        merged.append({
            "ticker": ticker,
            "stock_name": group[0].stock_name,
            "market": group[0].market,
            "quantity": total_qty,
            "average_buy_price": combined,
            "accounts": [{"account_name": g.account_name, "broker_name": g.broker_name,
                          "quantity": g.quantity, "average_buy_price": g.average_buy_price}
                         for g in group],
            "is_multi_account": len(group) > 1,
        })
    return merged


# ─────────────────────────────────────────────────────────────────────────────
# 로컬 저장 / 불러오기 / 삭제
# ─────────────────────────────────────────────────────────────────────────────
def save_positions(positions, path=PORTFOLIO_FILE):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {"saved_at": datetime.now().isoformat(timespec="seconds"),
               "positions": [asdict(p) for p in positions]}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return path


def load_positions(path=PORTFOLIO_FILE):
    if not os.path.exists(path):
        return [], None
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    return ([PortfolioPosition(**d) for d in payload.get("positions", [])],
            payload.get("saved_at"))


def delete_positions(path=PORTFOLIO_FILE):
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# 관심종목(watchlist) — 스캔 결과를 저장해 두었다가 '사용자 관심종목' 방식으로
# 다시 발굴할 때 쓴다. 보유종목과 같은 원칙: 로컬 파일에만, 서버 전송 없음.
# ─────────────────────────────────────────────────────────────────────────────
WATCHLIST_FILE = os.path.join(PORTFOLIO_DIR, "watchlist.json")


def save_watchlist(items, path=WATCHLIST_FILE):
    """items: [{'code': '028670', 'name': '팬오션'}, ...]"""
    clean = []
    for it in (items or []):
        code = normalize_code((it or {}).get('code'))
        if not code:
            continue
        clean.append({'code': code, 'name': str((it or {}).get('name') or code)})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {"saved_at": datetime.now().isoformat(timespec="seconds"),
               "items": clean}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return path


def load_watchlist(path=WATCHLIST_FILE):
    if not os.path.exists(path):
        return [], None
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    return payload.get("items", []), payload.get("saved_at")


def delete_watchlist(path=WATCHLIST_FILE):
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


def export_positions_csv(positions):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["종목코드", "종목명", "시장", "보유수량", "평균매수가", "증권사", "계좌별칭", "취득일"])
    for p in positions:
        w.writerow([p.code, p.stock_name, p.market, p.quantity, p.average_buy_price,
                    p.broker_name or "", p.account_name or "", p.acquisition_date or ""])
    return buf.getvalue()
