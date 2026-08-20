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

저장: .portfolio/premarket_YYYY-MM-DD.json (당일 고정)
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


def load_today_report(date_key=None, engine_version=None):
    """
    오늘 리포트가 **현재 엔진으로** 고정돼 있으면 그대로 돌려준다.

    같은 날이라도 엔진이 다르면 그 리포트는 오늘의 결론이 아니다.
    낡은 파일이 있으면 내용 대신 `superseded_by` 표시만 붙여 돌려주어,
    화면이 "다시 스캔하세요"가 아니라 왜 비어 있는지 말할 수 있게 한다.
    """
    date_key = date_key or datetime.now().strftime('%Y-%m-%d')
    ver = engine_version or _engine_version()

    p = _pm_path(date_key, ver)
    if os.path.exists(p):
        try:
            with open(p, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None

    # 현재 엔진 리포트가 없다 — 옛 형식(날짜만)이 남아 있는지 본다
    legacy = _pm_path(date_key)
    if os.path.exists(legacy):
        try:
            with open(legacy, encoding='utf-8') as f:
                old = json.load(f)
        except Exception:
            return None
        if str(old.get('engine_version') or '') == str(ver):
            return old
        old['stale_engine'] = str(old.get('engine_version') or '미상')
        old['current_engine'] = str(ver)
        return old
    return None


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
        na = _na.build(fs, None, row.get('base_price'), verdict or {})
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
    try:
        easy = q_engine.build_easy_advice(
            fs, verdict or {'score': r.get('final_score'),
                            'action': 'HOLD', 'vetoes': []},
            r.get('base_price'))
        easy_nb = easy['new_buyer']
    except Exception:
        easy_nb = {'emoji': '', 'line': '판단 보류', 'detail': ''}

    nf = ((snap.get('market_context') or {}).get('news_flags') or {})
    cb = fs.get('calibration_band') or {}
    _core = _core_of(q_engine, r, fs, verdict)
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


def build_report(q_engine, scan_rows, date_key=None, market_label=""):
    """
    스캔 결과(전일 확정 데이터 기반) → 개장 전 리포트. 이미 있으면 기존 것을 반환.

    scan_rows: run_screener_scan 이 만든 행 목록 (스냅샷 포함).
    """
    date_key = date_key or datetime.now().strftime('%Y-%m-%d')
    existing = load_today_report(date_key)
    # 엔진이 바뀌어 낡은 리포트라면 그대로 돌려주지 않는다. 다시 만든다.
    # 이걸 안 해서 "다시 스캔하세요" 안내가 아무 효과가 없었다.
    if existing and not existing.get('stale_engine'):
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
    }
    try:
        os.makedirs(PM_DIR, exist_ok=True)
        # 날짜×엔진으로 저장한다. 같은 날 엔진을 고치면 새 파일이 생기고,
        # 옛 파일은 기록으로 남는다 (사후 선택 방지 감사 흔적).
        with open(_pm_path(date_key, report['engine_version']), 'w',
                  encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
        # 이력에도 추가 (같은 날짜+종목은 중복 저장하지 않음)
        seen = set()
        if os.path.exists(PM_HISTORY):
            with open(PM_HISTORY, encoding='utf-8') as f:
                for line in f:
                    try:
                        h = json.loads(line)
                        seen.add((h.get('date'), h.get('symbol')))
                    except Exception:
                        continue
        with open(PM_HISTORY, 'a', encoding='utf-8') as f:
            for p in picks:
                if (date_key, p['symbol']) not in seen:
                    f.write(json.dumps({**p, 'date': date_key,
                                        'generated_at': report['generated_at']},
                                       ensure_ascii=False) + "\n")
    except Exception:
        pass
    return report, True


def grade_history(b_engine, max_rows=100):
    """
    지난 추천들의 실제 성과 — 목표/손절 선도달 채점 (prediction_log 재사용).
    반환: {'n','target','stop','open','rows':[...]} 또는 None(이력 없음)
    """
    if not os.path.exists(PM_HISTORY):
        return None
    import prediction_log as plog
    rows = []
    with open(PM_HISTORY, encoding='utf-8') as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    rows = rows[-max_rows:]
    today = datetime.now().strftime('%Y-%m-%d')
    cache, out = {}, []
    for r in rows:
        if r.get('date') == today or not r.get('target') or not r.get('stop'):
            continue
        tk = r.get('symbol')
        if tk not in cache:
            try:
                cache[tk], _ = b_engine.generate_synthetic_bitemporal_data(
                    symbol=tk, start_date='2020-01-01', end_date=None)
            except Exception:
                cache[tk] = None
        if cache[tk] is None:
            continue
        g = plog.grade_prediction(
            {'date': r['date'], 'price': r.get('price'),
             'target': r.get('target'), 'stop': r.get('stop'),
             'horizon_days': r.get('horizon_days') or 20}, cache[tk])
        if g:
            out.append({'name': r.get('name'), 'date': r.get('date'),
                        'reco_class': r.get('reco_class'),
                        'outcome': g['outcome'], 'return_pct': g['return_pct']})
    if not out:
        return None
    return {
        'n': len(out),
        'target': sum(1 for o in out if o['outcome'] == 'TARGET'),
        'stop': sum(1 for o in out if o['outcome'] == 'STOP'),
        'open': sum(1 for o in out if o['outcome'] == 'OPEN'),
        'rows': out[-10:],
    }
