# -*- coding: utf-8 -*-
"""
개장 전 확정 추천 리포트 — 전일까지 확정된 데이터로 장 시작 전에 결론을 내린다.

원칙:
  · 하루에 한 번 생성해 파일로 고정한다. 장중에 다시 열어도 점수를 바꾸지 않는다
    (사후에 좋아 보이는 종목을 고르는 것을 구조적으로 차단).
  · 생성 시각·기준 데이터 날짜를 리포트에 박제한다.
  · 모든 추천은 이력(jsonl)에 남고, 이후 실제 경로로 채점된다 — 성과를 숨길 수 없다.
  · 뉴스는 보조 신호다: 위험 낱말은 감점(기존 컨텍스트 상한), '신선한 재료'
    (종목 뉴스 + 참고 낱말 + 시세 후행 보도 아님)는 표기만 하고 가점하지 않는다.

저장: .portfolio/premarket_YYYY-MM-DD.json (자료 기준일 하나에 한 번 고정 · 라운드 442 — 날짜는 **자료 기준일**)
      .portfolio/premarket_history.jsonl (전체 이력 — 추가 전용)
"""
from __future__ import annotations

import json
import os
from datetime import datetime

PM_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".portfolio")
PM_HISTORY = os.path.join(PM_DIR, "premarket_history.jsonl")


def _pm_path(date_key, engine_version=None):
    """
    리포트 경로 — **날짜 × 엔진 버전**으로 가른다.

    종전에는 날짜만 키였다. 그래서 엔진을 고쳐도 그날 처음 만든 리포트가
    영원히 재사용됐고, 화면은 "예전 형식이니 다시 스캔하세요"라고만
    말하면서 계속 같은 옛 값을 보여 줬다. 다시 스캔해도 파일이 있으니
    갱신되지 않았다 — 안내가 실행 불가능한 지시였던 셈이다.

    엔진이 바뀌면 그 엔진의 오늘 리포트는 아직 없으므로 새로 만든다.
    옛 파일은 지우지 않는다 (사후 선택 방지 기록은 그대로 남긴다).
    """
    if engine_version:
        safe = str(engine_version).replace(os.sep, '_').replace('/', '_')
        return os.path.join(PM_DIR, f"premarket_{date_key}__{safe}.json")
    return os.path.join(PM_DIR, f"premarket_{date_key}.json")


#: 라운드 442 — 이 표시가 붙은 리포트·이력 줄은 `date` 가 곧 **자료 기준일**이다. 그 전의 줄은 벽시계 날짜였다.
DAY_BASIS = 'data'


def report_day(now=None):
    """지금(또는 `now`) 열면 보여야 할 리포트의 기준일 — ISO 문자열 · 못 구하면 None (라운드 442).

    ■ 왜 벽시계 날짜가 아닌가 (2026-10-07 실측)
      리포트 열쇠가 `datetime.now()` 의 날짜였다. 내용은 스캔의 분석 기준일(마지막으로 장이 끝난 거래일)로 정해지는데,
      열쇠는 연 날이라 **같은 자료가 날짜 여럿에 걸렸다** — 리포트 105개 중 68개가 '거래일 날짜 · 자료는 전 거래일'
      (장 전·자정 넘어 연 날) · 24개가 휴장일 날짜였고 13개만 날짜 = 자료일이었다. 그래서 ① 휴장일·장 전에 열면 자료가
      그대로인데도 2~3분짜리 스캔을 다시 돌려 파일을 하나 더 만들었고(라운드 228 이 막으려던 그 모양) ② 추적이 그 날짜를
      기준일로 써 **리포트가 겨냥한 거래일을 채점에서 뺐으며**(진입은 전 거래일 종가 · 경로는 날짜 다음 봉부터) ③ 같은
      추천이 저녁 판·다음 날 아침 판 두 기준일로 두 번 세어졌다(확정 32건). 원장(`calibration_lab`)·종목 판정 기록
      (`prediction_log` 은 `snap['t_ref']`)·전방 기록부(판정일)는 모두 자료 기준일을 쓴다 — 리포트만 달랐다(§4).
    ■ 규칙은 엔진이 분석 기준일을 정하는 그 함수(`bitemporal_engine.resolve_analysis_date`) — 여기서 다시 적지 않는다.
    """
    try:
        from bitemporal_engine import resolve_analysis_date
        d = resolve_analysis_date(now)
        return d.isoformat() if hasattr(d, 'isoformat') else _iso_day(d)
    except Exception:                                          # noqa: BLE001
        return None


def _iso_day(v):
    """'YYYY-MM-DD' 로 읽히면 그 글자 · 아니면 None."""
    s = str(v or '')[:10]
    try:
        datetime.strptime(s, '%Y-%m-%d')
    except ValueError:
        return None
    return s


def data_day_of(row):
    """그 리포트(또는 이력 한 줄)가 쓴 **자료의 기준일** · 못 정하면 None (라운드 442 · 한 곳).

    · 라운드 442 뒤의 줄(`day_basis == 'data'`) → `date` 그대로
    · 그 전의 줄 → 생성 시각(`generated_at`)에 엔진 규칙(`report_day`)을 대어 유도한다. 실측 2026-10-07: 리포트 105개 중
      103개가 그 파일에 적힌 `data_asof` 와 같고, 다른 둘은 `data_asof` 가 날짜로 채워진 초기 판(2026-08-05 장 전)이다.
      옛 이력 줄에는 `data_asof` 가 없어 유도가 유일한 길이기도 하다 — 리포트와 이력이 같은 규칙으로 묶이게 한다(§4).
    · 생성 시각을 못 읽으면 `data_asof` · 그것도 없으면 None — 벽시계 날짜로 몰래 떨어지지 않는다(§3 · 부르는 쪽이 정한다).
    """
    if not isinstance(row, dict):
        return None
    if row.get('day_basis') == DAY_BASIS:
        return _iso_day(row.get('date'))
    g = str(row.get('generated_at') or '').strip().replace('T', ' ')[:19]
    if g:
        try:
            at = datetime.fromisoformat(g)
        except ValueError:
            at = None
        if at is not None:
            d = report_day(at.replace(tzinfo=None))
            if d:
                return d
    return _iso_day(row.get('data_asof'))


def _same_day_files(date_key):
    """오늘 리포트 파일 전부 — (생성 시각, 경로, 내용). 버전이 다른 파일도 같은 날이면 같은
    결론이다(R228 · R222 "정체는 날짜, 버전은 도장")."""
    import glob
    out = []
    for path in glob.glob(os.path.join(PM_DIR, f"premarket_{date_key}__*.json")) +             [_pm_path(date_key)]:
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding='utf-8') as f:
                d = json.load(f)
        except Exception:
            continue
        out.append((str(d.get('generated_at') or ''), path, d))
    out.sort(key=lambda t: t[0])
    return out


def generated_at(date_key, engine_version=None):
    """그 자료 기준일 리포트의 생성 시각 — 라운드 472(자동매매 계획이 '언제 판정됐나'를 적으려고 · 읽기만).
    엔진 버전이 같은 파일 먼저 · 없으면 그날 가장 최근 파일. 자료 기준일이 다른 옛 파일은 안 고른다(라운드 442).
    못 찾으면 None(지어내지 않는다)."""
    if not date_key:
        return None
    files = [t for t in _same_day_files(date_key) if t[0] and data_day_of(t[2]) == date_key]
    if not files:
        return None
    same = [t for t in files if engine_version and str(t[2].get('engine_version')) == str(engine_version)]
    return (same or files)[-1][0]


def _kinds_since(frozen_with, current):
    """모델 축에서 `frozen_with` 뒤에 나온 변경 종류들 — 원장을 못 읽으면 None."""
    try:
        import versioning as _v
        hist = [h for h in _v.history(limit=200, axis='model')]
    except Exception:
        return None
    seen = False
    kinds = []
    for h in sorted(hist, key=lambda h: str(h.get('created_at') or '')):
        if str(h.get('version')) == str(frozen_with):
            seen = True
            continue
        if seen:
            kinds.append(str(h.get('kind') or ''))
        if str(h.get('version')) == str(current):
            break
    return kinds if seen else None


RULE_KINDS = ('gate', 'algorithm', 'weight', 'engine_swap')


def load_today_report(date_key=None, engine_version=None):
    """
    오늘 리포트를 돌려준다 — **정체는 날짜, 버전은 도장** (라운드 228).

    종전(라운드 30)에는 날짜 × 엔진 버전이 열쇠라, 같은 날 엔진 버전이 오르면 그날
    리포트가 '없는 것'이 되어 다음 세션이 스캔을 다시 돌리고 파일을 하나 더 만들었다.
    2026-09-07 실측: 화면·문구만 바꾼 배포 셋 뒤에 **똑같은 내용의 파일 넷**(38,041
    바이트)이 생겼고, 세션마다 2~3분짜리 재스캔이 돌았다. R222 가 추적 DB 에서 같은
    모양을 걷어냈다(버전이 열쇠에 있으면 옛 것이 매번 새 것이다).

    · 현재 엔진으로 고정한 파일이 있으면 그대로.
    · 없으면 **같은 날의 가장 최근 파일**을 돌려주되 `engine_drift` 를 단다 —
      {'frozen_with', 'current', 'kinds'(그 뒤 변경 종류 · 못 읽으면 None),
       'rule_changed'(게이트·알고리즘·가중치·엔진 교체가 끼었는가)}.
      "장중 재계산 금지"가 이날의 규칙이다 — 새 규칙은 내일 리포트부터다.
    · 아무것도 없으면 None.

    라운드 442 — `date_key` 는 **자료 기준일**이다(기본 `report_day()` · 휴장일·장 전·장중에 열어도 마지막으로 장이
    끝난 거래일). 이름이 같아도 자료 기준일이 다른 옛 파일(장 전에 만들어 그날 날짜가 붙은 판)은 그날의 결론이
    아니므로 돌려주지 않는다 — 내용이 정체다. 기준일을 못 구하면 None(어느 날의 결론인지 모르는 파일을 고르지 않는다).
    """
    date_key = date_key or report_day()
    if not date_key:
        return None
    ver = engine_version or _engine_version()
    p = _pm_path(date_key, ver)
    if os.path.exists(p):
        try:
            with open(p, encoding='utf-8') as f:
                d = json.load(f)
        except Exception:
            return None
        if data_day_of(d) == date_key:
            return d
    files = [t for t in _same_day_files(date_key) if data_day_of(t[2]) == date_key]
    if not files:
        return None
    _, _, latest = files[-1]
    frozen_with = str(latest.get('engine_version') or '미상')
    kinds = _kinds_since(frozen_with, ver)
    latest['engine_drift'] = {
        'frozen_with': frozen_with, 'current': str(ver), 'kinds': kinds,
        'rule_changed': (any(k in RULE_KINDS for k in kinds) if kinds else None),
        'files_today': len(files),
    }
    return latest


def _classify_reco(row, easy_line):
    """
    추천 4분류 — 사용자 어휘 그대로.

    분류는 반드시 '아주 쉬운 결론'(easy_line)과 모순되지 않아야 한다.
    예전에는 entry_candidate+점수만으로 '조건부로 사도 되는 종목'을 붙여서,
    카드 제목은 사도 된다는데 본문은 '판단 보류'인 어긋남이 생겼다.
    """
    s = str(easy_line or '')
    if '사도 됩니다' in s and row.get('entry_candidate') \
            and (row.get('final_score') or 0) >= 60:
        return '오늘 사도 되는 종목'
    if '이하로 내려올 때만' in s:
        # 가격 조건이 붙은 매수 — 조건부
        return ('조건부로 사도 되는 종목' if row.get('entry_candidate')
                else '오늘은 기다려야 하는 종목')
    if '보류' in s:
        # 신뢰도·표본 부족 보류 — 사도 된다고 말하지 않는다
        return '오늘은 기다려야 하는 종목'
    return '오늘은 사면 안 되는 종목'


def _why_of(core, fs, news_flags, sector_cycle):
    """
    왜 이 종목인가 — 근거를 사람이 읽는 문장으로 (라운드 47).

    실패해도 카드는 그려져야 한다. 근거를 못 만들면 빈 묶음을 돌려주고,
    카드는 그 칸을 통째로 생략한다 (없는 근거를 지어내지 않는다).
    """
    if not core:
        return None
    try:
        import why_pick as _wp
        return _wp.build(core, fs, news_flags, sector_cycle)
    except Exception:                                        # noqa: BLE001
        return None


def _core_of(q_engine, row, fs, verdict):
    """
    중앙 판정 — 상세 화면과 **같은 함수**를 쓴다 (라운드 34).

    카드가 자기만의 rec_buy/target/stop 조합을 만들던 것이 화면 간 어긋남의
    원인이었다(라운드 31 진단 ⑤). 이제 두 화면이 같은 dict 를 읽는다.
    """
    try:
        import next_action as _na
        import verdict_core as _vc
    except Exception:
        return None
    try:
        # ⚠️ 라운드 185 — 여기가 tech_df 를 안 넘기고 있었다(None). 그러면
        #   next_action 이 첫 줄에서 no_data 로 조기 반환해 **밸류 가드가
        #   아예 안 돌았고**, kind 기반 분류(돌파 대기 등)도 전부 죽어
        #   상세 화면과 카드가 다른 버킷을 냈다 (§4). 스냅샷에 tech_df 가
        #   이미 있다 — _na_of() 가 쓰는 그 값이다.
        _td = (row.get('snapshot') or {}).get('tech_df')
        na = _na.build(fs, _td, row.get('base_price'), verdict or {})
    except Exception:
        na = None
    try:
        return _vc.build(fs, verdict=verdict,
                         price_axes=fs.get('price_axes'), next_action=na,
                         realtime_price=row.get('base_price'))
    except Exception:
        return None


def _engine_version():
    """리포트를 만든 엔진 버전 — 없으면 '미상'(지어내지 않는다)."""
    try:
        import versioning as _v
        return _v.current('model')
    except Exception:
        return '미상'


def _na_of(row):
    """
    스캔 행 하나에 '다음 조건'을 붙인다 — 카드가 "사지 마세요"로 끝나지 않게.

    실패하면 None 을 돌려 준다. 여기서 예외가 나면 리포트 전체가 죽으므로
    감싸되, 조용히 빈 값으로 채우지는 않는다(없으면 없다고 말한다).
    """
    try:
        import next_action as _na
        snap = row.get('snapshot') or {}
        fs = snap.get('four_scores') or {}
        td = snap.get('tech_df')
        price = row.get('base_price') or snap.get('rt_price')
        if td is None or not price:
            return None
        return _na.build(fs, td, price, snap.get('verdict'))
    except Exception:
        return None


def _asset_only_of(snap):
    """라운드 382 — 이 스냅샷의 적정가가 자산 기반 모형으로만 섰는가. 못 가르면 None(§3 · 지어내지 않는다).

    가름은 `model_kinds.split` 한 곳이 한다(라운드 359 · §4). 적정가가 없으면 물음 자체가 없으므로 None.
    """
    try:
        ve = (snap or {}).get('val_eval') or {}
        if ve.get('displayed_fair_value') is None:
            return None
        import model_kinds as _mk
        s = _mk.split(ve.get('model_results'))
        if not (s['asset'] or s['earnings'] or s['unknown']):
            return None
        return bool(s['asset_only'])
    except Exception:                                          # noqa: BLE001
        return None


def pick_from_scan_row(q_engine, r):
    """
    스캔 행 하나 → 추천 카드가 읽는 pick dict.

    라운드 39 — build_report 안에만 있던 조립을 함수로 뺐다.
    "오늘의 관심종목 후보"도 개장 전 추천과 **같은 카드**로 그려야 하는데,
    조립이 한 함수 안에 갇혀 있어 목록마다 자기만의 카드를 만들고 있었다.
    한 화면에 두 종류의 카드가 보이면 어느 쪽을 믿을지 알 수 없다.
    """
    snap = r.get('snapshot') or {}
    fs = (snap.get('four_scores') or r.get('scores_obj') or {})
    snap = r.get('snapshot') or {}
    fs = (snap.get('four_scores') or r.get('scores_obj') or {})
    verdict = None
    try:
        verdict = q_engine.build_final_verdict(snap) if snap else None
    except Exception:
        verdict = None
    # 라운드 386 — 중앙 판정을 **먼저** 만들고 쉬운 결론에 넘긴다. 종전엔 쉬운 결론이 엔진 판정만 보고
    #   '사세요'를 적을 수 있었고(두 번째 판정자 · R193), 카드 분류(reco_class)가 그 문장을 읽었다.
    _core = _core_of(q_engine, r, fs, verdict)
    try:
        easy = q_engine.build_easy_advice(
            fs, verdict or {'score': r.get('final_score'),
                            'action': 'HOLD', 'vetoes': []},
            r.get('base_price'), core=_core)
        easy_nb = easy['new_buyer']
    except Exception:
        easy_nb = {'emoji': '', 'line': '판단 보류', 'detail': ''}

    nf = ((snap.get('market_context') or {}).get('news_flags') or {})
    cb = fs.get('calibration_band') or {}
    return {
        'code': str(r.get('symbol', '')).split('.')[0],
        'symbol': r.get('symbol'),
        'name': r.get('name'),
        'asset_type': fs.get('asset_type', 'STOCK'),
        'reco_class': _classify_reco(r, easy_nb.get('line')),
        # 라운드 120g — `easy_emoji` 를 뺐다. 엔진의 `emoji` 는 **모든 대입이
        # 빈 문자열**이고(이모지 금지 · §5), 아무도 읽지 않는 필드였다.
        # 화면은 그걸 `{emoji} {line}` 으로 그려 빈 자리와 앞 공백만 남겼다.
        'easy_line': easy_nb.get('line'),
        'score': r.get('final_score'),
        'price': r.get('base_price'),          # 추천 시점 가격 (전일 종가 기준)
        # 카드가 쓰는 '권장 매수가'는 **실행 가능한 눌림가**다 (라운드 25).
        # 적정가 기반 값은 장기 참고선으로 따로 싣는다 — 오늘의 매수가가
        # 아니다 (현재가와 30~50% 벌어지는 일이 흔했다).
        # 라운드 53c — 폴백을 뗐다. 위 주석이 이미 "오늘의 매수가가 아니다"
        # 라고 적어 둔 값이었다. 게다가 폴백이 걸리면 아래 rec_buy_basis
        # (entry_pullback_basis)와 짝이 맞지 않아, 근거 없는 가격이 카드에
        # 실린다. 없으면 None 으로 두고 카드가 '미산출'이라 말한다.
        'rec_buy': fs.get('entry_pullback_price'),
        'rec_buy_basis': fs.get('entry_pullback_basis'),
        'value_floor': fs.get('value_floor_price'),
        # 적정가 — 라운드 133 에서 **빠져 있는 것을 발견했다.** 카드는
        # `권장 매수가 -7.5%` 만 보여 줘서 싸 보이는데, 상세로 들어가면
        # 적정가가 그보다 아래인 경우가 있다(대우건설·현대건설). 두 화면이
        # 다른 인상을 준다. 카드가 가치 프리미엄을 그리려면 이 값이 행에
        # 실려야 한다. **이름을 바꾸지 않는다** — 같은 사실을 다른 이름으로
        # 부르면 계보가 끊긴다.
        # ⚠️ `value_floor`(장기 안전마진선)로 대신하지 않는다. 그건 적정가에
        #   안전마진을 곱한 다른 값이고, 라운드 53c 가 폐기 산식이라 적었다.
        'displayed_fair_value': fs.get('displayed_fair_value'),
        # 적정가 신뢰도 — 라운드 143 에서 **또 빠져 있는 것을 발견했다.**
        # 적정가만 실으면 "4,615원이 1,659원의 3배"라는 사실만 보이고
        # 그 4,615원을 **믿을 수 있는지**는 안 보인다. 값과 신뢰도는
        # 같이 다녀야 한다.
        'fair_value_confidence': fs.get('fair_value_confidence'),
        # 라운드 382 — 그 적정가가 **자산 기반 모형으로만** 섰는가(라운드 359 의 가름 · `model_kinds` 한 곳).
        #   카드가 '가치로 봐도 싼'을 '장부가로 보면 싼'으로 좁히는 데만 쓴다(표시 전용). 못 가르면 None.
        'fair_asset_only': _asset_only_of(snap),
        'entry_zone': fs.get('entry_zone'),
        'chase_max': fs.get('buy_entry_max'),
        # 현재가 기준 (보유자용) — 카드에서는 경고 상자로만 안내한다
        'target': fs.get('target_tech_1st'),
        'target2': fs.get('target_tech_2nd'),
        'stop': fs.get('stop_loss_price'),
        # 권장 매수가 기준 (신규 매수자용) — 카드의 목표·손절은 이쪽이다.
        # 둘을 같은 카드에 섞으면 "126,452원에 사서 213,955원에 손절"
        # 같은 말이 된다 (라운드 22 실측: 17종목 중 11종목이 그랬다).
        'entry_target_1st': fs.get('entry_target_1st'),
        'entry_stop_price': fs.get('entry_stop_price'),
        'entry_rr': fs.get('entry_rr'),
        # 도달 가능성 — 권장가가 정말 닿는 가격인가 (라운드 23)
        'rec_buy_sigma': fs.get('rec_buy_sigma'),
        'rec_buy_reach': fs.get('rec_buy_reach'),
        'rec_buy_drop_pct': fs.get('rec_buy_drop_pct'),
        # 다음 조건 — "사지 마세요"로 끝내지 않는다 (라운드 24)
        'next_action': _na_of(r),
        'confidence': fs.get('analysis_confidence'),
        'horizon_days': 20,
        'entry_candidate': bool(r.get('entry_candidate')),
        'm10_above': bool(r.get('m10_above')),
        'news_risk': int(nf.get('risk_count', 0) or 0),
        'news_fresh': int(nf.get('fresh_watch_count', 0) or 0),
        'news_lagging': int(nf.get('lagging_count', 0) or 0),
        # 라운드 473 — 뉴스를 **받기는 했는가**(엔진 `news_flags.feed_available` · 라운드 42 가 '받지 못한 것과 악재가
        #   없는 것은 다르다'며 만든 칸). 위 세 칸은 못 받은 날도 0 이라 '위험 낱말 없음'과 '피드 못 받음'이 같은 0 이었다 —
        #   확정 추적 케이스 243건이 그 둘을 가를 수 없었다(§3). 이력 줄은 후보를 통째로 옮기므로 이 칸도 같이 남는다.
        #   맥락이 아예 없으면 None(모른다 · 받았다고도 못 받았다고도 안 적는다).
        'news_feed_ok': (bool(nf['feed_available']) if 'feed_available' in nf else None),
        'confidence_band': ({'lo': cb.get('lo'), 'hi': cb.get('hi'),
                             'hit_rate': cb.get('hit_rate'), 'n': cb.get('n')}
                            if cb else None),
        'reasons': [str(x)[:90] for x in
                    (str(fs.get('gate_reason', '')).split(' / ')[:3])],
        # ── 중앙 판정 (라운드 34) ────────────────────────────────
        # 카드가 자기만의 가격 조합을 만들지 않도록, 상세 화면과 **같은
        # 함수**가 낸 결과를 통째로 싣는다. 화면 간 값이 어긋나면
        # 회귀가 잡는다.
        'core': _core,
        # ── 왜 이 종목인가 (라운드 47) ───────────────────────────
        # 사용자 지적: *"단순히 점수가 높다는 이유만 보여줄 것이 아니라,
        # 왜 이 종목을 계속 관심 있게 봐야 하는지 명확하게 설명해 주세요."*
        # 근거가 없으면 빈 묶음이 온다 — 그때는 카드가 이 칸을 안 그린다.
        'why': _why_of(_core, fs, nf, fs.get('sector_cycle')),
    }


def report_fix_blocker(now=None):
    """지금 개장 전 리포트를 **고정하면 안 되는** 사유 · 없으면 None. 화면과 저녁 작업이 같이 부른다(라운드 486 · §4).

    정규장 마감 뒤 애프터마켓(16:00~20:00)이 끝나기 전에는 그날 종가·일봉이 아직 움직인다 — 2026-09-14 부터 네이버 종가가
    애프터마켓 체결을 따라가기 때문이다(엔진 `bar_final`). 그때 고정하면 그날 리포트가 **미완성 봉**으로 굳고, 같은 자료일의
    리포트는 다시 안 만드므로(라운드 228) 애프터마켓이 끝난 뒤 저녁 작업이 만들 자리를 먼저 차지한다. 정규장 중 고정은 여기서
    막지 않는다 — 그때의 리포트는 전 거래일 자료일이고 채점 경계(라운드 483)가 다룬다."""
    try:
        import bitemporal_engine as _be
        now = now or datetime.now()
        st = _be.get_market_status(now)
        if st.get('state') == '장 종료' and not _be.bar_final(now):
            end = _be.after_market_end(now.date())
            return (f"애프터마켓이 {end.strftime('%H:%M') if end else '끝나기'} 전이라 오늘 종가·일봉이 아직 움직입니다 — "
                    "개장 전 리포트는 그 뒤에 고정합니다(2026-09-14 부터 종가가 애프터마켓 체결을 따라갑니다)")
    except Exception:                                          # noqa: BLE001
        return None
    return None


def build_report(q_engine, scan_rows, date_key=None, market_label=""):
    """
    스캔 결과(전일 확정 데이터 기반) → 개장 전 리포트. 이미 있으면 기존 것을 반환.

    scan_rows: run_screener_scan 이 만든 행 목록 (스냅샷 포함).

    라운드 442 — `date_key` 는 **자료 기준일**이다. 기본은 그 스캔이 실제로 쓴 분석 기준일(첫 행 스냅샷의 `t_ref`)이고,
    못 읽으면 `report_day()`(같은 규칙). 둘 다 못 구하면 리포트는 만들되 **파일로 고정하지 않는다** — 어느 날의 결론인지
    모르는 파일은 다음 날 결론처럼 읽힌다(§3).
    """
    if not date_key:
        try:
            _t442 = (scan_rows[0].get('snapshot') or {}).get('t_ref') if scan_rows else None
        except Exception:                                      # noqa: BLE001
            _t442 = None
        date_key = _iso_day(_t442) or report_day()
    existing = load_today_report(date_key) if date_key else None
    # 라운드 228 — 같은 날 리포트가 있으면 엔진 버전이 달라도 **그것이 오늘 결론**이다
    #   (장중 재계산 금지 · 정체는 날짜). 종전에는 버전이 다르면 다시 만들어, 화면·문구
    #   배포마다 똑같은 파일이 하나씩 늘고 세션마다 재스캔이 돌았다. 드리프트는 화면이
    #   도장으로 말한다(`engine_drift`). 새 규칙은 내일 리포트부터.
    if existing:
        return existing, False               # (리포트, 새로 생성했는가)

    picks = []
    for r in (scan_rows or [])[:5]:
        p = pick_from_scan_row(q_engine, r)
        if p:
            picks.append(p)

    report = {
        'date': date_key,
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'data_asof': str((scan_rows[0].get('snapshot') or {}).get('t_ref', date_key)
                         if scan_rows else date_key),
        'market_label': market_label,
        'frozen': True,
        # 어느 엔진이 만든 리포트인지 찍는다. 이게 없으면 엔진을 바꾼 뒤에도
        # 낡은 값을 들고 있는 걸 알 수 없다 — 실제로 라운드 25 에서 권장
        # 매수가 산식을 바꿨는데 카드가 옛 9,388원을 그대로 보여 줬다.
        'engine_version': _engine_version(),
        'note': ("이 리포트는 생성 시각의 확정 데이터 기준이며, 오늘 장중에는 "
                 "다시 계산하지 않습니다 (사후 선택 방지)."),
        'picks': picks,
        'day_basis': DAY_BASIS,             # 라운드 442 — `date` 는 자료 기준일
    }
    if not date_key:
        report['note'] += " 분석 기준일을 정하지 못해 파일로 고정하지 않았습니다."
        return report, False
    try:
        os.makedirs(PM_DIR, exist_ok=True)
        # 날짜×엔진으로 저장한다. 같은 날 엔진을 고치면 새 파일이 생기고,
        # 옛 파일은 기록으로 남는다 (사후 선택 방지 감사 흔적).
        with open(_pm_path(date_key, report['engine_version']), 'w',
                  encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
        # 이력에도 추가 (같은 자료 기준일+종목은 중복 저장하지 않음)
        # 라운드 442 — 옛 줄의 `date` 는 벽시계 날짜라 같은 자료의 줄을 날짜로 견주면 못 알아본다(장 전 판과 저녁 판).
        #   옛 줄도 `data_day_of` 로 자료 기준일을 구해 견준다 — 못 구하면 그 줄의 날짜 그대로.
        seen = set()
        if os.path.exists(PM_HISTORY):
            with open(PM_HISTORY, encoding='utf-8') as f:
                for line in f:
                    try:
                        h = json.loads(line)
                        seen.add((data_day_of(h) or h.get('date'), h.get('symbol')))
                    except Exception:
                        continue
        with open(PM_HISTORY, 'a', encoding='utf-8') as f:
            for p in picks:
                if (date_key, p['symbol']) not in seen:
                    f.write(json.dumps({**p, 'date': date_key, 'day_basis': DAY_BASIS,
                                        'generated_at': report['generated_at']},
                                       ensure_ascii=False) + "\n")
    except Exception:
        pass
    return report, True


def _history_names():
    """(종목, 기준일) → (이름, 분류). 이력 파일에서 — DB 행은 코드만 가진다."""
    out = {}
    if not os.path.exists(PM_HISTORY):
        return out
    with open(PM_HISTORY, encoding='utf-8') as f:
        for line in f:
            try:
                h = json.loads(line)
            except Exception:
                continue
            out[(h.get('symbol'), h.get('date'))] = (h.get('name'), h.get('reco_class'))
            # 라운드 442 — 추적 케이스의 기준일은 자료 기준일이다(옛 케이스도 옮겼다). 옛 줄은 그 날짜로도 찾게 한다.
            _dd = data_day_of(h)
            if _dd:
                out.setdefault((h.get('symbol'), _dd), (h.get('name'), h.get('reco_class')))
    return out


OUTCOME_KO = {'success': '목표 도달', 'failure': '손절', 'unresolved': '미도달'}


def grade_history(conn=None, max_rows=10, db_path=None):
    """
    지난 개장 전 추천의 실제 성과 — improvement DB 의 확정 결과를 **읽는다** (라운드 232).

    종전엔 여기서 prediction_log 로 이력 마지막 100행을 다시 채점했다(진입 = 리포트 가격 ·
    닿으면 즉시). 모델 성적의 추적 줄은 DB(진입 = 권장매수가 · 20봉 뒤 · 같은 봉은 미결)를
    읽어 **같은 페이지에서 다른 수**를 냈다 — 실측 2026-09-07: 95건 목표 30·손절 26·미결 39
    vs 확정 51 성공 29·실패 15·미결 7. 채점은 일일 루틴(scripts/run_daily_improvement.py →
    prediction_log.grade_prediction · 원장과 같은 채점기)이 한 번 하고, 화면은 읽기만 한다(§4).
    반환 {'tally','rows','dates'} 또는 None(케이스 없음 · DB 없음).
    """
    from improvement import case_tracker as _ct
    from improvement.database import get_connection, initialize_database, DEFAULT_DB_PATH
    own = conn is None
    if own:
        path = db_path or DEFAULT_DB_PATH
        if not os.path.exists(path):
            return None
        # ⚠️ 라운드 331 — 배포 앱이 여기서 **통째로 죽었다**(sqlite3.OperationalError · 2026-09-17).
        #   파일이 있는지만 봤는데, `get_connection` 은 연결만 열어도 **빈 파일을 만든다** — 새로 뜬
        #   컨테이너에서 다른 자리가 먼저 연결을 열면 '파일은 있고 표는 없는' 상태가 되고 첫 SELECT 가
        #   죽는다. 같은 DB 를 읽는 다른 자리(모델 성적의 추적 줄)는 이미 `initialize_database` 를 먼저
        #   부르고 있었다 — 그 순서를 여기도 따른다(CREATE TABLE IF NOT EXISTS · 있는 행은 안 건드린다).
        initialize_database(path)
        conn = get_connection(path)
    try:
        t = _ct.tally(conn)
        if not (t['resolved'] or t['open']):
            return None
        # 라운드 389 — 목록·기준일 범위도 집계(tally)와 같은 모집단이다: 휴장일 기준일 행은
        #   갈래에서 빠지므로 여기서도 뺀다(한 칸에서 집계와 목록이 다른 행을 세면 §4).
        _all = conn.execute(
            "SELECT ticker, signal_date, status, strategy_type, realized_return "
            "FROM prediction_cases WHERE status IN ('success','failure','unresolved') "
            "ORDER BY resolved_at DESC, signal_date DESC").fetchall()
        _all = [r for r in _all if not _ct.is_non_trading_date(r['signal_date'])]
        rows = _all[:int(max_rows)]
        _ds = sorted(str(r['signal_date'])[:10] for r in _all)
        d1, d2 = (_ds[0], _ds[-1]) if _ds else (None, None)
    finally:
        if own:
            conn.close()
    names = _history_names()
    out = []
    for r in rows:
        nm, rc = names.get((r['ticker'], r['signal_date']), (None, None))
        out.append({'name': nm or r['ticker'], 'date': r['signal_date'],
                    'reco_class': rc or r['strategy_type'] or '',
                    'outcome': OUTCOME_KO.get(r['status'], r['status']),
                    'return_pct': float(r['realized_return'] or 0.0) * 100.0})
    return {'tally': t, 'rows': out, 'dates': (d1, d2)}