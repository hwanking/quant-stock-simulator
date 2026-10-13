# -*- coding: utf-8 -*-
"""
관심종목 추천 → 스윙 계획 재료 (라운드 507 · 2026-10-13 · 사용자 결정).

■ 왜 있나
  자동매매 계획은 개장 전 리포트(시장 스캔 상위 5)에서만 만들어졌다. 2026-10-12 엔진이 낸 **추천**(조건 11개 전부 통과)은
  관심종목 한 종목이었고 리포트 상위 5 에는 없었다 — 그날 계획 5개는 전부 '추천 아님'이라 실주문 0 이었다. 사용자가 *"관심종목
  추천도 계획에 넣기"* 를 골랐다(2026-10-13 02:50).

■ 새 판단을 만들지 않는다 (§4)
  관심종목의 숫자 코드 종목을 리포트와 **같은 정밀 분석 함수**(`run_screener_scan` · 시세 교차검증·유동성 하한까지 그대로)로 같은
  분석 기준일에 재고, 리포트와 **같은 조립 함수**(`premarket.pick_from_scan_row`)로 후보를 만든다. 그 가운데 중앙 판정이
  **추천**(`core['recommended'] is True`)인 것만 남긴다. 문서의 모양이 리포트와 같아(`date`·`day_basis`·`generated_at`·
  `engine_version`·`picks`) 계획은 리포트와 **같은 함수**(`swing_engine.plans_from_report`)가 만든다 — 계약·실주문 자격·
  plan_id 규칙이 하나다.

■ 리포트와 겹치면 리포트가 이긴다
  같은 판정일 리포트에 이미 있는 종목은 이 문서에 안 넣는다(같은 종목 계획이 두 출처로 둘이 되지 않게 · 실행부도 같은 종목은
  한 번만 산다 · 이중 안전).

■ 사전등록 표본을 건드리지 않는다
  추천 후보만 담으므로 그 계획의 판정 기록에 미충족 조건이 없다 — 사전등록 R478 의 모집단('비용 차감 기대값 양수'에 막힌
  계획)에 들지 않는다. R475 는 개장 전 이력(리포트 후보)을 센다 — 이 문서는 그 이력에 안 쓴다. 계획의 판정 기록에
  `source='watchlist'` 를 남겨 엔진 성적·리포트 계획과 가를 수 있게 한다(plan_id 에는 안 든다).

■ 개인 자료 (§9)
  관심종목 코드가 들어 있다 — 이 PC 의 `.portfolio/` 에만(백업 거부 `swing*` · 업로드 목록 밖 · git 밖).
"""
import json
import os

PROJ = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(PROJ, '.portfolio')
SOURCE = 'watchlist'
PREFIX = 'swing_watch_picks_'


def path_of(day):
    """그 판정일 문서의 자리 — 'YYYY-MM-DD' → .portfolio/swing_watch_picks_YYYYMMDD.json · 날짜가 아니면 None."""
    s = str(day or '')[:10]
    if len(s) != 10 or s[4] != '-' or s[7] != '-' or not s.replace('-', '').isdigit():
        return None
    return os.path.join(DIR, PREFIX + s.replace('-', '') + '.json')


def _code(p):
    return str((p or {}).get('code') or str((p or {}).get('symbol') or '').split('.')[0])


def recommended(p):
    """그 후보가 중앙 판정의 **추천**인가 — `core['recommended'] is True` 만(참 같은 값은 안 받는다 · §3)."""
    return isinstance(p, dict) and ((p.get('core') or {}).get('recommended') is True)


def doc_from(picks, date_key, *, engine_version, generated_at, day_basis, report_codes=(), counts=None, excluded_codes=()):
    """후보 목록 → 리포트 모양의 문서. 추천만 남기고 · 리포트에 이미 있는 종목은 뺀다. 뺀 수를 문서에 적는다(조용히 버리지 않는다).

    `verdicts` — 그날 **잰 종목 전부**의 추천 여부 {코드: True/False}(정밀 분석에서 빠진 종목 `excluded_codes` 는 False). 실행부가
    '최신 판정이 이긴다'에 쓴다 — 어제 추천이라 만든 계획이라도 오늘 잰 판정이 추천이 아니면 그 계획으로는 사지 않는다(2026-10-13
    독립 검토 · 문서에 추천만 남기면 빠진 종목의 흔적이 없어 옛 계획이 대기 기간 내내 사게 된다)."""
    rc = {str(x) for x in (report_codes or ())}
    rec, in_report, not_rec = [], 0, 0
    verdicts = {}
    for p in picks or []:
        verdicts[_code(p)] = bool(recommended(p))
        if not recommended(p):
            not_rec += 1
            continue
        if _code(p) in rc:
            in_report += 1
            continue
        rec.append(p)
    for x in excluded_codes or ():
        verdicts.setdefault(str(x), False)
    c = dict(counts or {})
    c.update(picks=len(picks or []), not_recommended=not_rec, in_report=in_report, kept=len(rec))
    return {'source': SOURCE, 'date': date_key, 'day_basis': day_basis, 'data_asof': date_key,
            'generated_at': generated_at, 'engine_version': engine_version, 'frozen': True,
            'note': ('관심종목의 중앙 판정 추천 후보 — 리포트와 같은 정밀 분석·조립 함수로 같은 분석 기준일에 쟀다. '
                     '리포트에 이미 있는 종목은 뺐다.'),
            'counts': c, 'verdicts': verdicts, 'picks': rec}


def save(doc):
    """임시 파일 → 통째로 바꿔 끼움. 쓴 경로 · 쓰기 금지(GAEUM_NO_LOCAL_WRITE)거나 날짜가 없으면 None."""
    if os.environ.get('GAEUM_NO_LOCAL_WRITE'):
        return None
    path = path_of((doc or {}).get('date'))
    if not path:
        return None
    os.makedirs(DIR, exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    import safe_replace                                        # 라운드 519 — 화면(15초 갱신)이 읽는 순간이면 짧게 다시 · 막히면 복사
    safe_replace.replace_retry(tmp, path)
    return path


def load(day, path=None):
    """그 판정일의 문서 · 없거나 모양이 다르면 None(지어내지 않는다). 읽은 뒤에도 추천만 남긴다(이중 안전)."""
    path = path or path_of(day)
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, encoding='utf-8') as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or doc.get('source') != SOURCE or str(doc.get('date')) != str(day)[:10]:
        return None
    if not isinstance(doc.get('picks'), list):
        return None
    return dict(doc, picks=[p for p in doc['picks'] if recommended(p)])
