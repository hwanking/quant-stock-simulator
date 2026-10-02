# -*- coding: utf-8 -*-
"""관심종목 스냅샷을 **재는 길 하나** (라운드 414).

■ 왜 이 모듈이 있나
  사용자(2026-10-02): *"'지금 다시 재기' 같은 거는 너가 주기적으로 바꿔줘야지."*
  관심종목 52행의 엔진 값 기준일이 2026-08-21 ~ 10-02 로 흩어져 있었고(오늘 값 1행), 옛 규칙의
  판정('… 대기' · 옛 이름 칸)은 사람이 표에서 '지금 재기'를 눌러야만 새 규칙으로 바뀌었다. 라운드
  166·322·327 이 *"자동으로 돌리지 않는다 — 한 종목 1~3분이라 화면을 열 때마다 돌면 앱이 멈춘다"*
  고 적어 둔 자리인데, **화면을 열 때**가 아니라 **장이 끝난 뒤 혼자** 돌면 그 이유가 사라진다.

  그래서 재는 본문을 화면(`web_app.py` 채우기 버튼 · '지금 재기' 링크)에서 **여기로 옮기고**, 밤에
  혼자 도는 스크립트(`scripts/refresh_watchlist.py` · Windows 작업 스케줄러 · 평일 장 마감 뒤)가
  같은 함수를 부른다(§4 — 재는 길이 둘이면 한쪽만 고치는 일이 생긴다 · 라운드 169 가 경로를 베끼다
  한 단계를 빠뜨린 자리). 값·판정·문턱·6조건·보유 계획 규칙은 **한 글자도 안 바뀐다** — 바뀐 것은
  *누가 언제 누르나*뿐이다.

■ 규칙 (새 숫자 없음)
  · 재는 날(기준일)은 앱과 같은 한 곳 — `bitemporal_engine.resolve_analysis_date`(장 마감 뒤면 오늘,
    장중·장 전·휴장이면 직전 거래일). 못 구하면 None 이고 **그때는 안 잰다**(§3 — '오늘'로 떨어지지 않는다).
  · 다시 잴 행 = 채우기 버튼이 모자라다고 보던 행(`needs_fill` · 라운드 166~387 그대로) + 엔진 값
    기준일이 그 기준일보다 **앞선** 행(`DUE_STALE`). 매 거래일 한 번이면 옛 규칙 스탬프·옛 이름 칸은
    다음 거래일 밤에 전부 새 규칙으로 바뀐다(개장 전 리포트 · 전방 기록기와 같은 하루 주기 · 문턱 아님).
  · 보유 계획(버틸 수 없는 가격 · 1차 매도가)은 **`portfolio.hold_plan_update` 가 정한 대로만** 움직인다 —
    잰 날에 고정 · 1차 매도가에 닿거나 창이 끝나면 다시 잼 · 손절선을 넘긴 계획은 그대로(사용자 결정
    2026-09-28 · 라운드 373). 밤 작업은 `remeasure=False` 다 — 사람이 누르는 '기준 다시 재기'만 True.
  · 저장은 **행마다 그 자리에서**: 파일을 다시 읽어 그 종목의 스냅샷 칸만 바꾸고 바로 쓴다(매입가·수량·
    메모는 손대지 않는다 · 몇 분 걸리는 동안 사용자가 저장한 것을 옛 복사본으로 덮지 않는다). 못 낸 값
    (None·'')으로 옛 값을 지우지 않는다(라운드 141).
  · 실행 기록은 `.portfolio/watch_refresh_log.jsonl` 한 줄 — 화면이 그것을 읽어 *언제 · 몇 종목 · 실패 몇*
    을 적는다. **자동화는 '켜져 있다'가 아니라 '산출물이 생겼다'로 센다**(라운드 412).
  · `GAEUM_NO_LOCAL_WRITE` 가 켜져 있으면(회귀 · 배포) **아무 파일도 안 쓴다**(§9 · 라운드 165).
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
import time

import portfolio
import ledger_view

LOG_FILE = os.path.join(portfolio.PORTFOLIO_DIR, 'watch_refresh_log.jsonl')
LOCK_FILE = os.path.join(portfolio.PORTFOLIO_DIR, 'watch_refresh.lock')
#: 실행 기록은 최근 이만큼만 남긴다 — 파일이 자라지 않게 (라운드 224 의 HOLD_LOG_KEEP 과 같은 이유)
LOG_KEEP = 60

#: 채우기 사유 낱말 — 화면 캡션과 정렬이 이 글자를 읽는다 (라운드 322 의 차례: 보유 → 한 번도 안 잰 것 → 나머지)
FILL_ENGINE = '엔진 값'
DUE_STALE = '기준일 지남'


def no_local_write():
    """회귀·배포는 사용자 자료를 안 쓴다 (라운드 165·200 의 그 깃발 하나)."""
    return bool(os.environ.get('GAEUM_NO_LOCAL_WRITE'))


# ──────────────────────────────────────────────────────────────────────
# 무엇을 다시 재나
# ──────────────────────────────────────────────────────────────────────
def needs_fill(w):
    """채우기 버튼이 '값이 모자라다'고 보는 행 → 사유 낱말, 아니면 '' (라운드 166 → 387 · 본문 그대로 옮김).

    라운드 169 — 보유자 기준값이 없는 종목도 채울 대상이다(매입가를 적은 종목은 hold_stop·hold_trim 이
    있어야 판단이 나온다). 라운드 214 — 물타기 스탬프가 없는 보유 행(매입가·수량 둘 다 있을 때만 — 수량이
    없으면 헬퍼가 {} 를 돌려주어 키가 안 생기고 매번 다시 채우자고 해 헛돈다). 라운드 224·387 — 물타기 첫
    조건의 출처가 바뀌었을 때 옛 스탬프를 다시 채운다. 라운드 241 — 판정 사유가 없는 미보유 행."""
    w = w or {}
    if not w.get('snap_at') or w.get('snap_buy') is None:
        return FILL_ENGINE
    if w.get('paid') and not (w.get('snap_hold_stop') or w.get('snap_hold_trim')):
        return '보유자 기준값'
    if w.get('paid') and w.get('qty') and 'snap_avg_down_ok' not in w:
        return '물타기 판정'
    if w.get('paid') and w.get('qty') and 'snap_new_entry' not in w:
        return '물타기 첫 조건'
    # 라운드 387 — 옛 기준에서 **허락**('가능')이 찍힌 행만 다시 채운다 — 옛 '불가'는 새 기준에서도 불가다.
    if (w.get('paid') and w.get('qty') and w.get('snap_new_entry') == '가능'
            and w.get('snap_avg_down_ok') in (True, '가능')):
        return '물타기 첫 조건'
    if not w.get('paid') and w.get('snap_bucket') and 'snap_why' not in w:
        return '판정 사유'
    return ''


def due_reason(w, ref_day):
    """이 행을 지금 다시 재야 하나 → 사유 낱말, 아니면 ''.

    모자란 값(`needs_fill`)이 먼저다. 값이 다 있어도 엔진 값 기준일(`snap_at`)이 `ref_day` 보다 앞서면
    `DUE_STALE`. `ref_day` 가 None 이면 날짜로는 판정하지 않는다(§3)."""
    r = needs_fill(w)
    if r:
        return r
    at = str((w or {}).get('snap_at') or '')[:10]
    rd = str(ref_day or '')[:10]
    if rd and at and at < rd:
        return DUE_STALE
    return ''


def order_key(w, reason):
    """채우는 차례 — ① 보유 행 ② 한 번도 안 잰 행 ③ 나머지 · 같은 자리는 들어온 순서(안정 정렬 · 라운드 322)."""
    return (0 if (w or {}).get('paid') else 1, 0 if reason == FILL_ENGINE else 1)


def due_rows(items, ref_day, force=False):
    """[(행, 사유)] — 다시 잴 행을 차례대로. `force` 면 전부(사유 '강제')."""
    out = []
    for w in (items or []):
        r = '강제' if force else due_reason(w, ref_day)
        if r:
            out.append((w, r))
    return sorted(out, key=lambda t: order_key(t[0], t[1]))


def ref_day(now=None):
    """재는 날 — 앱의 '확정 분석 기준일'과 같은 한 곳. 못 구하면 None."""
    try:
        import bitemporal_engine as _be
        mkt = _be.get_market_status(now)
        d = _be.resolve_analysis_date(now, market_status=mkt)
        return d.isoformat() if hasattr(d, 'isoformat') else str(d)[:10]
    except Exception:                                          # noqa: BLE001
        return None


def symbol_of(row):
    """관심종목 행 → 엔진 티커 (채우기 버튼과 같은 규칙 · 시장을 모르면 .KS)."""
    code = portfolio.normalize_code((row or {}).get('code'))
    return f"{code}.KQ" if str((row or {}).get('market') or '') == 'KOSDAQ' else f"{code}.KS"


# ──────────────────────────────────────────────────────────────────────
# 한 행을 잰다 — 화면 채우기 버튼의 본문 그대로
# ──────────────────────────────────────────────────────────────────────
def core_of(snp, q):
    """스냅샷 → 중앙 판정 (라운드 169·224 의 차례 그대로 · `build()` 의 첫 인자는 four_scores).
    보유자 손절 조이기(R293)는 **안 건다** — 저장 칸은 늘 엔진이 잰 것 하나만 뜻한다."""
    import verdict_core as _vc
    import next_action as _na
    fs = (snp or {}).get('four_scores') or {}
    vd = (snp or {}).get('verdict')
    if vd is None:
        vd = q.build_final_verdict(snp)
    nx = _na.build(fs, (snp or {}).get('tech_df'), fs.get('current_price'), vd)
    return _vc.build(fs, verdict=vd, price_axes=fs.get('price_axes'), next_action=nx,
                     realtime_price=fs.get('current_price'))


def avg_down_snap(row, snapshot, core, items, q):
    """관심종목 한 줄의 **물타기 판정**을 스냅샷에 찍는다 (라운드 214 → 224 → 387 · 본문 그대로 옮김).

    새 문턱을 만들지 않는다 — `personalize_for_position` 이 **이미 채택한 6조건**을 그대로 부른다(§2-6).
    정식 보유 화면과 **같은 함수·같은 비중 정의**(관심종목 보유분 매입원가 기준)다(§4). 매입가·수량이
    없으면 빈 dict — 지어내지 않는다(§3). 첫 조건은 중앙 판정의 `recommended`(신규 매수 추천 · 11조건
    전부 · 라운드 387) — 호출부가 core 를 안 넘기면 None → 엔진이 '미판정'(보류)으로 찍는다."""
    try:
        paid = float((row or {}).get('paid') or 0)
        qty = float((row or {}).get('qty') or 0)
    except (TypeError, ValueError):
        return {}
    if paid <= 0 or qty <= 0 or not snapshot:
        return {}        # 안 산 종목 — 판정 대상이 아니다 (실패가 아니라 정상)
    tot = 0.0
    for w in (items or []):
        try:
            tot += float(w.get('paid') or 0) * float(w.get('qty') or 0)
        except (TypeError, ValueError):
            pass
    wpct = (paid * qty / tot * 100.0) if tot > 0 else None
    try:
        _ne224 = (core.get('recommended') if isinstance(core, dict) else None)
        pv = q.personalize_for_position(snapshot, paid, qty,
                                        portfolio_weight_pct=wpct,
                                        new_entry_ok=_ne224)
    except Exception:                                          # noqa: BLE001
        # 못 낸 것은 빈 dict 로 두되(§3) **왜 못 냈는지는 로그에 남긴다** — 조용히 {} 만 돌려주면 물타기 칸이
        # 영영 비어도 아무도 모른다(라운드 214).
        import traceback as _tb
        print('[관심종목 물타기 판정 실패 — 칸을 비운다]\n' + _tb.format_exc(), file=sys.stderr)
        return {}
    _fails = [lbl for lbl, ok in (pv.get('averaging_down_checks') or []) if not ok]
    return {
        # 파일은 **글자 스키마**(portfolio.WATCH_SNAP_TXT)로만 남긴다 — bool·list 는 저장에서 떨어진다.
        'snap_avg_down_ok': ('가능' if pv.get('averaging_down_allowed') else '불가'),
        # 실패가 없으면 '없음' — 빈 글자는 병합이 "못 낸 값"으로 보고 건너뛰어 옛 목록이 살아남는다(라운드 224).
        'snap_avg_down_fail': ' · '.join(_fails) or '없음',
        # 첫 조건이 무엇을 읽었는지 (중앙 판정 · 글자 · 라운드 387 — 옛 '가능'/'불가'와 가르는 새 낱말)
        'snap_new_entry': ('미판정' if _ne224 is None else ('추천' if _ne224 else '추천 아님')),
        'snap_holder_key': pv.get('holder_action_key'),
        'snap_holder_title': pv.get('holder_action_title'),
        'snap_weight_basis': ('관심종목 보유분 매입원가 기준' if wpct is not None else '비중 미확인'),
    }


def fair_reach_snap(fs, table):
    """적정가 도달 비율 한 줄 (라운드 224 · 표시 전용 · 본문 그대로 옮김). 문턱 없음 — 수와 n 만 낸다.
    `table` 은 `reach_table_from_ledger()`(또는 화면의 같은 표). 못 재면 '' (스냅샷 병합에서 떨어진다 · §3)."""
    fs = fs or {}
    if not table:
        return ''
    try:
        _fair = float(fs.get('displayed_fair_value') or 0)
        _px = float(fs.get('current_price') or 0)
    except (TypeError, ValueError):
        return ''
    if _fair <= 0 or _px <= 0:
        return ''
    _up = (_fair / _px - 1.0) * 100.0
    _rg = str(((fs.get('regime_gate') or {}).get('cell') or '')).split('|')[0] or None
    _zn = fs.get('entry_zone')
    _r = ledger_view.reach_share(table, _rg, _zn, _up)
    if not _r:
        return ''
    return ledger_view.reach_line(_r[0], _r[1], _up, _rg, _zn)


def reach_table_from_ledger():
    """원장 → 도달 표 — 화면의 `_reach_table_224` 와 같은 재료(통계 행 · `ledger_view.stat_rows` 한 곳).
    원장을 못 찾으면 None — 지어내지 않는다(§3)."""
    try:
        import artifact_io
        p = artifact_io.find('virtual_graded.jsonl')
        if not p:
            return None
        keys = ledger_view.scale_mismatch_keys()

        def _rows():
            if str(p).endswith('.gz'):
                import gzip
                fh = gzip.open(p, 'rt', encoding='utf-8')
            else:
                fh = open(p, encoding='utf-8')
            with fh:
                for line in fh:
                    try:
                        yield json.loads(line)
                    except Exception:                          # noqa: BLE001
                        continue
        t = ledger_view.reach_table(ledger_view.stat_rows(_rows(), keys))
        return t or None
    except Exception:                                          # noqa: BLE001
        return None


def snap_values(row, snp, core, t_ref_str, model_ver, items, q, reach_table=None, remeasure=False):
    """한 행의 스냅샷 값 묶음 — 채우기 버튼이 적던 그대로 (라운드 166 → 413). 쓸 키만 돌려준다.

    신규 매수자 값(`snap_buy`·`snap_t1`)과 보유자 값(`snap_hold_*`)은 **다른 키**다(§4). 보유자 값은
    `portfolio.hold_plan_update` 가 고정할지 다시 잴지 정한다 — 여기서 직접 덮어쓰지 않는다."""
    import ui_kit as _uk
    fs = (snp or {}).get('four_scores') or {}
    core = core or {}
    vals = {
        'snap_buy': (core.get('pullback_zone') or (core.get('buy_zone') or [None])[0]),
        'snap_t1': core.get('new_target'),                       # 진입가 기준
        'snap_t2': fs.get('target_tech_2nd'),                    # 현재가 기준
        'snap_fair': fs.get('displayed_fair_value'),
        'snap_fair_conf': fs.get('fair_value_confidence'),
        'snap_px': fs.get('current_price'),
        'snap_at': t_ref_str,
        'snap_engine': str(model_ver or ''),
        'snap_bucket': core.get('bucket'),
        'snap_why': core.get('exclude_reason') or _uk.WATCH_NO_WHY,   # 라운드 240 → 241
        'snap_sector': ((snp or {}).get('val_eval') or {}).get('sector'),   # 라운드 214
        'snap_fair_reach': fair_reach_snap(fs, reach_table),               # 라운드 224 · 못 재면 ''
    }
    vals.update(avg_down_snap(row, snp, core, items, q))
    vals.update(portfolio.hold_plan_update(
        row, core.get('hold_trim'), core.get('hold_stop'), fs.get('current_price'), t_ref_str,
        horizon_bars=int(core.get('horizon_days') or ledger_view.HORIZON_BARS),
        held=bool((row or {}).get('paid')), remeasure=bool(remeasure)))
    return vals


def merge_into(items, by_code):
    """스냅샷 값을 행에 얹는다 — 못 낸 값(None·'')으로 옛 값을 지우지 않는다(라운드 141). 새 목록을 돌려준다."""
    out = []
    for w in (items or []):
        c = portfolio.normalize_code((w or {}).get('code'))
        n = dict(w or {})
        for k, v in (by_code.get(c) or {}).items():
            if v not in (None, ''):
                n[k] = v
        out.append(n)
    return out


def measure_row(row, t_ref_str, model_ver, items, q, b_engine, reach_table=None, remeasure=False, rho_cutoff=None):
    """한 행을 **실제로** 잰다 → (값 묶음, 스냅샷, 중앙 판정). 스냅샷은 엔진의 전체 파이프라인(화면과 같은 함수)."""
    kw = {} if rho_cutoff is None else {'rho_cutoff': rho_cutoff}
    snp = q.run_full_pipeline(symbol_of(row), t_ref_str, b_engine=b_engine, **kw)
    core = core_of(snp, q)
    return snap_values(row, snp, core, t_ref_str, model_ver, items, q, reach_table=reach_table,
                       remeasure=remeasure), snp, core


# ──────────────────────────────────────────────────────────────────────
# 혼자 도는 실행 — 스크립트가 부른다
# ──────────────────────────────────────────────────────────────────────
def _save_merged(code, vals, path):
    """파일을 **다시 읽어** 그 종목의 칸만 바꾸고 바로 쓴다 — 몇 분 사이 사용자가 저장한 것을 덮지 않는다."""
    cur, _ = portfolio.load_watchlist(path)
    new = merge_into(cur, {code: vals})
    if any(portfolio.normalize_code(w.get('code')) == code for w in cur):
        portfolio.save_watchlist(new, path)
        return True
    return False                     # 그 사이 사용자가 뺀 종목 — 되살리지 않는다


def refresh(items=None, ref=None, limit=None, codes=None, write=True, log=None, path=None,
            log_path=None, force=False, rho_cutoff=None):
    """다시 잴 행을 골라 재고 저장하고 기록한다 → 요약 dict.

    · `write=False` 면 재기만 하고 아무것도 안 쓴다(기록도). `GAEUM_NO_LOCAL_WRITE` 면 강제로 그렇다.
    · `limit` — 이번에 몇 행까지. `codes` — 그 종목만(관심종목에 있는 것만).
    · 되돌려 주는 것: ref_day · rows · due · measured · failed[(code, name, reason)] · seconds · wrote."""
    log = log or (lambda *_a, **_k: None)
    path = path or portfolio.WATCHLIST_FILE
    log_path = log_path or LOG_FILE
    write = bool(write) and not no_local_write()
    t0 = time.time()
    if items is None:
        items, _ = portfolio.load_watchlist(path)
    rd = ref or ref_day()
    out = dict(at=_dt.datetime.now().isoformat(timespec='seconds'), ref_day=rd, rows=len(items or []),
               due=0, measured=0, failed=[], saved=0, seconds=0.0, wrote=False, limit=limit)
    if not rd:
        out['error'] = '기준일을 못 구했다 — 재지 않는다'          # 지어낸 '오늘'로 떨어지지 않는다 (화면에 나가는 문장)
        log(out['error'])
        return out
    todo = due_rows(items, rd, force=force)
    if codes:
        want = {portfolio.normalize_code(c) for c in codes}
        todo = [(w, r) for w, r in todo if portfolio.normalize_code(w.get('code')) in want]
    out['due'] = len(todo)
    if limit is not None:
        todo = todo[:int(limit)]
    out['planned'] = len(todo)
    if not todo:
        log(f'기준일 {rd} · 관심종목 {out["rows"]}행 · 다시 잴 행 0 — 이미 최신')
        out['seconds'] = round(time.time() - t0, 1)
        if write:
            out['wrote'] = True
            _append_log(out, log_path)
        return out
    import versioning as _ver
    from bitemporal_engine import BitemporalEngine
    from quant_indicators import QuantIndicatorsEngine
    model_ver = str(_ver.snapshot().get('model') or '')
    b_engine = BitemporalEngine()
    q = QuantIndicatorsEngine()
    table = reach_table_from_ledger()
    log(f'기준일 {rd} · 관심종목 {out["rows"]}행 · 다시 잴 행 {out["due"]}'
        + (f' (이번엔 {len(todo)})' if len(todo) != out['due'] else '')
        + f' · 모델 {model_ver} · 도달 표 {"있음" if table else "없음"}'
        + ('' if write else ' · 쓰기 없음'))
    for i, (w, reason) in enumerate(todo, 1):
        code = portfolio.normalize_code(w.get('code'))
        name = str(w.get('name') or code)
        t1 = time.time()
        try:
            vals, _snp, core = measure_row(w, rd, model_ver, items, q, b_engine, reach_table=table,
                                           remeasure=False, rho_cutoff=rho_cutoff)
            out['measured'] += 1
            if write and _save_merged(code, vals, path):
                out['saved'] += 1
            log(f'  {i}/{len(todo)} {name} ({code}) · {reason} → {core.get("bucket")} · '
                f'{time.time() - t1:.1f}초' + ('' if write else ' · 안 씀'))
        except Exception as ex:                                # noqa: BLE001
            out['failed'].append((code, name, f'{type(ex).__name__}: {ex}'[:120]))
            log(f'  {i}/{len(todo)} {name} ({code}) · 실패 {type(ex).__name__}: {str(ex)[:80]} · '
                f'{time.time() - t1:.1f}초')
    out['seconds'] = round(time.time() - t0, 1)
    log(f'끝 · 잰 행 {out["measured"]} · 저장 {out["saved"]} · 실패 {len(out["failed"])} · {out["seconds"]}초')
    if write:
        out['wrote'] = True                    # 기록에 실리는 값이므로 적기 **전에** 세운다 (첫 실행 기록이 False 로 남았다)
        _append_log(out, log_path)
    return out


def _append_log(rec, log_path):
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    lines = []
    if os.path.exists(log_path):
        try:
            with open(log_path, encoding='utf-8') as f:
                lines = [ln for ln in f.read().splitlines() if ln.strip()]
        except Exception:                                      # noqa: BLE001
            lines = []
    lines.append(json.dumps(rec, ensure_ascii=False, default=str))
    with open(log_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines[-LOG_KEEP:]) + '\n')


def last_run(log_path=None):
    """마지막 실행 기록 한 줄 → dict, 없거나 못 읽으면 None."""
    log_path = log_path or LOG_FILE
    if not os.path.exists(log_path):
        return None
    try:
        with open(log_path, encoding='utf-8') as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
        return json.loads(lines[-1]) if lines else None
    except Exception:                                          # noqa: BLE001
        return None


def status_line(last, ref=None):
    """화면 한 줄 — 언제 · 몇 종목 · 실패 몇. 기록이 없으면 **없다고** 말한다(라운드 412 — 켜져 있다가 아니라 산출물로 센다)."""
    if not last:
        return ('관심종목 자동 갱신 — 아직 한 번도 돈 기록이 없습니다. 평일 장 마감 뒤 혼자 도는 작업'
                '(scripts/refresh_watchlist.py)이 이 PC 에 등록돼 있어야 합니다.')
    at = str(last.get('at') or '')[:16].replace('T', ' ')
    rd = str(last.get('ref_day') or '')[:10]
    due, measured, failed = int(last.get('due') or 0), int(last.get('measured') or 0), last.get('failed') or []
    s = f'관심종목 자동 갱신 — 마지막 실행 {at} · 기준일 {rd} · 다시 잴 행 {due}'
    if due:
        s += f' 중 {measured} 갱신'
    if failed:
        s += f' · 실패 {len(failed)}'
    if last.get('error'):
        s += f' · {last["error"]}'
    if ref and rd and str(ref)[:10] > rd:
        s += f' · 오늘 기준일({str(ref)[:10]})로는 아직 안 돌았습니다'
    return s


# ──────────────────────────────────────────────────────────────────────
# 겹쳐 돌지 않게 — 잠금 파일 (pid 를 적고, 그 pid 가 살아 있을 때만 잠긴 것으로 본다)
# ──────────────────────────────────────────────────────────────────────
def pid_alive(pid):
    """살아 있으면 True · 죽었으면 False · 모르면 None (모르면 잠긴 것으로 본다 — 안전한 쪽)."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == 'nt':
        try:
            import ctypes
            k = ctypes.windll.kernel32
            h = k.OpenProcess(0x1000, False, pid)           # PROCESS_QUERY_LIMITED_INFORMATION
            if not h:
                return False
            try:
                code = ctypes.c_ulong()
                if k.GetExitCodeProcess(h, ctypes.byref(code)):
                    return code.value == 259                # STILL_ACTIVE
                return None
            finally:
                k.CloseHandle(h)
        except Exception:                                  # noqa: BLE001
            return None
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except Exception:                                      # noqa: BLE001
        return None


def acquire_lock(path=None):
    """잠그면 True. 다른 산 프로세스가 쥐고 있으면 False. 죽은 pid 의 잠금은 걷어내고 잠근다."""
    path = path or LOCK_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                other = int((f.read().strip().split() or ['0'])[0])
        except Exception:                                  # noqa: BLE001
            other = 0
        if other != os.getpid() and pid_alive(other) is not False:
            return False
        try:
            os.remove(path)
        except OSError:
            return False
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(f'{os.getpid()} {_dt.datetime.now().isoformat(timespec="seconds")}\n')
    return True


def release_lock(path=None):
    path = path or LOCK_FILE
    try:
        os.remove(path)
    except OSError:
        pass
