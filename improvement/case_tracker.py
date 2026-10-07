# -*- coding: utf-8 -*-
"""케이스 동결 저장 — 중복 방지(case_id 해시)·입력 데이터 해시 동결."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date, datetime, timezone
from typing import Any, Mapping, Optional

from improvement.schemas import CaseStatus, Decision, PredictionCase


def make_data_hash(payload: Mapping[str, Any]) -> str:
    normalized = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                            default=str).encode('utf-8')
    return hashlib.sha256(normalized).hexdigest()


def make_case_id(ticker: str, signal_date: date, model_version: str,
                 decision: Decision) -> str:
    raw = (f"{ticker}|{signal_date.isoformat()}|"
           f"{model_version}|{decision.value}")
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]


def create_prediction_case(*, ticker: str, asset_type: str, signal_date: date,
                           model_version: str, rulebook_version: str,
                           decision: Decision, total_score: float,
                           confidence_score: float, reference_price: float,
                           entry_price: Optional[float],
                           target_price: Optional[float],
                           stop_price: Optional[float], holding_days: int,
                           market_regime: str, strategy_type: str,
                           source_payload: Mapping[str, Any]) -> PredictionCase:
    if reference_price <= 0:
        raise ValueError("reference_price는 0보다 커야 합니다.")
    if holding_days <= 0:
        raise ValueError("holding_days는 1 이상이어야 합니다.")
    for nm, v in (('entry_price', entry_price), ('target_price', target_price),
                  ('stop_price', stop_price)):
        if v is not None and v <= 0:
            raise ValueError(f"{nm}는 0보다 커야 합니다.")
    return PredictionCase(
        case_id=make_case_id(ticker, signal_date, model_version, decision),
        ticker=ticker, asset_type=asset_type, signal_date=signal_date,
        created_at=datetime.now(timezone.utc),
        model_version=model_version, rulebook_version=rulebook_version,
        decision=decision, total_score=float(total_score),
        confidence_score=float(confidence_score),
        reference_price=float(reference_price), entry_price=entry_price,
        target_price=target_price, stop_price=stop_price,
        holding_days=holding_days, market_regime=market_regime,
        strategy_type=strategy_type,
        data_hash=make_data_hash(source_payload))


def save_prediction_case(conn: sqlite3.Connection,
                         case: PredictionCase) -> bool:
    """INSERT OR IGNORE — 같은 종목·날짜·모델·판단이면 조용히 무시 (중복 방지)."""
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO prediction_cases (
            case_id, ticker, asset_type, signal_date, created_at,
            model_version, rulebook_version, decision,
            total_score, confidence_score,
            reference_price, entry_price, target_price, stop_price,
            holding_days, market_regime, strategy_type, data_hash, status
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (case.case_id, case.ticker, case.asset_type,
         case.signal_date.isoformat(), case.created_at.isoformat(),
         case.model_version, case.rulebook_version, case.decision.value,
         case.total_score, case.confidence_score, case.reference_price,
         case.entry_price, case.target_price, case.stop_price,
         case.holding_days, case.market_regime, case.strategy_type,
         case.data_hash, case.status.value))
    return cur.rowcount == 1


def resolve_case(conn: sqlite3.Connection, case_id: str, *, status: str,
                 exit_price, realized_return, max_drawdown, reason: str) -> None:
    """결과 확정 — open 상태만 갱신한다 (확정된 케이스는 덮어쓰지 않는다)."""
    conn.execute(
        """
        UPDATE prediction_cases
        SET status=?, exit_price=?, realized_return=?, max_drawdown=?,
            result_reason=?, resolved_at=?
        WHERE case_id=? AND status='open'
        """,
        (status, exit_price, realized_return, max_drawdown, reason,
         datetime.now(timezone.utc).isoformat(), case_id))


def open_cases(conn: sqlite3.Connection) -> list:
    return conn.execute(
        "SELECT * FROM prediction_cases WHERE status='open' "
        "ORDER BY signal_date").fetchall()


def today_added_count(conn: sqlite3.Connection, day: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM prediction_cases WHERE signal_date=?",
        (day,)).fetchone()[0]


EXCLUDED_STATUSES = ('dup_version', 'void_fixture')


def is_non_trading_date(iso_day) -> bool:
    """휴장일(주말 · KRX 휴일)인가 — **한 곳** (라운드 252).

    실측 2026-09-09: 확정 169건 · 고유 기준일 33개 중 9개가 토·일이었고 일요일 픽은
    토요일 픽과 5/5 같았다. 개장 전 리포트가 만들어진 날이 기준일로 들어와서다.
    휴일 목록은 저장소가 이미 가진 것을 쓴다(손으로 안 적는다) — 못 읽으면 주말만 본다.
    """
    from datetime import date as _date
    try:
        y, m, d = (int(x) for x in str(iso_day)[:10].split('-'))
        if _date(y, m, d).weekday() >= 5:
            return True
    except (TypeError, ValueError):
        return False
    try:
        from bitemporal_engine import KRX_HOLIDAYS
        return str(iso_day)[:10] in KRX_HOLIDAYS
    except Exception:                                          # noqa: BLE001
        return False


def report_dates(history_path, today=None) -> list:
    """개장 전 리포트 이력에서 동결할 수 있는 기준일 — 거래일 · 오늘 이하 · 정렬 (라운드 415).
    파일이 없거나 못 읽으면 None(없는 것과 못 읽은 것을 가른다 · §3)."""
    import os as _os
    today = str(today or date.today().isoformat())[:10]
    if not history_path or not _os.path.exists(history_path):
        return None
    out = set()
    # 라운드 442 — 기준일은 자료 기준일이다(동결이 그 날짜로 케이스를 만든다 · `premarket.data_day_of` 한 곳).
    #   옛 줄의 `date` 는 벽시계 날짜라 그대로 견주면 동결된 날(자료일)과 안 맞아 밀린 날로 잘못 센다.
    try:
        from premarket import data_day_of as _day_of
    except Exception:                                          # noqa: BLE001
        _day_of = None
    try:
        with open(history_path, encoding='utf-8') as f:
            for line in f:
                try:
                    _row = json.loads(line)
                    d = str(((_day_of(_row) if _day_of else None) or _row.get('date')) or '')[:10]
                except Exception:                              # noqa: BLE001
                    continue
                if len(d) == 10 and d <= today and not is_non_trading_date(d):
                    out.add(d)
    except Exception:                                          # noqa: BLE001
        return None
    return sorted(out)


def freeze_gap(conn: sqlite3.Connection, history_path, today=None) -> dict:
    """개장 전 리포트는 있는데 **아직 동결되지 않은** 거래일 (라운드 415 · 한 곳).

    2026-10-02 실측: 리포트는 이 PC 의 앱만 만드는데 클라우드에는 09-12 판이 마지막이라, 클라우드의 추적 루틴이
    09-14 뒤로 **한 건도 동결하지 못했다**(496건에서 멈춤 · 이 PC 에만 리포트 19일치). 화면의 추적 줄은 그 사실을
    말하지 않았다. 반환: last_report · last_frozen(거래일 케이스의 마지막 기준일) · pending(그 뒤의 리포트 거래일 목록).
    리포트 이력을 못 읽으면 pending 은 None 이다."""
    days = report_dates(history_path, today)
    frozen = [str(d)[:10] for (d,) in conn.execute(
        "SELECT DISTINCT signal_date FROM prediction_cases WHERE status NOT IN (?, ?)", EXCLUDED_STATUSES)]
    frozen = sorted(d for d in frozen if not is_non_trading_date(d))
    last_frozen = frozen[-1] if frozen else None
    if days is None:
        return {'last_report': None, 'last_frozen': last_frozen, 'pending': None}
    have = set(frozen)
    pending = [d for d in days if d not in have and (last_frozen is None or d > last_frozen)]
    return {'last_report': days[-1] if days else None, 'last_frozen': last_frozen, 'pending': pending}


def freeze_gap_line(gap) -> str:
    """화면 한 줄 — 밀린 날이 있을 때만. 없으면 빈 글자(늘 말하면 소음이다)."""
    gap = gap or {}
    pend = gap.get('pending')
    if pend is None:
        return ''
    if not pend:
        return ''
    return (f"개장 전 리포트는 {gap.get('last_report')} 까지 있는데 동결된 마지막 추천은 "
            f"{gap.get('last_frozen') or '없음'} 입니다 — 리포트 {len(pend)}거래일치가 아직 추적에 안 들어갔습니다. "
            f"이 PC 의 평일 장 마감 뒤 자동 실행이 동결합니다(그 추천을 만든 버전으로 도장을 찍습니다).")


def tally(conn: sqlite3.Connection) -> dict:
    """
    확정·대기의 갈래 — **한 곳** (라운드 232). 화면의 두 자리(개장 전 절의 '사후 검증' ·
    모델 성적의 '실전 추천 추적' 줄)가 이것만 읽는다. 버전 복사본·시험 픽스처(R222)는
    행으로 남기되 세지 않고 `excluded` 에 따로 센다(§3). 분모가 0 이면 비율은 None.
    휴장일 기준일 행(R252 전의 옛 동결)도 행으로 남기되 갈래에서 빼고 `non_trading` ·
    `non_trading_decided` 에 따로 센다(라운드 389).
    """
    counts = dict(conn.execute(
        "SELECT status, COUNT(*) FROM prediction_cases GROUP BY status").fetchall())
    excluded = sum(int(counts.get(s) or 0) for s in EXCLUDED_STATUSES)
    # 라운드 252 — 휴장일 기준일은 **날짜 표본**을 부풀린다(토·일 픽이 같은 추천의
    #   복사본). 행은 그대로 두고, 그 수와 **거래일 고유 기준일 수**를 같이 낸다 —
    #   날짜가 표본인 판정(뉴스 축 하한 30 · R84)은 `trading_dates` 를 읽는다.
    # 라운드 389 — 그런데 성공·실패는 **여전히 휴장일 행까지** 세고 있었다. 실측 2026-09-29:
    #   휴장일 기준일 50건 중 44건이 **다음 거래일의 같은 종목 케이스와 겹친다** — 같은 추천을
    #   두 번 채점한 것이다. 동결은 R252 부터 휴장일을 건너뛰므로(새 행은 안 생긴다) 옛 행에도
    #   **같은 규칙**을 적용한다: 행은 안 지우고(R197) 갈래·분모에서 빼며 그 수를 따로 낸다(§3).
    #   화면 두 자리(사후 검증 · 추적 줄)가 이것만 읽으므로 둘이 같이 바뀐다(§4).
    _days = conn.execute(
        "SELECT signal_date, status FROM prediction_cases").fetchall()
    _live = [(str(d)[:10], st) for d, st in _days if st not in EXCLUDED_STATUSES]
    _hol = [(d, st) for d, st in _live if is_non_trading_date(d)]
    _trd = [(d, st) for d, st in _live if not is_non_trading_date(d)]
    ok = sum(1 for _, st in _trd if st == 'success')
    bad = sum(1 for _, st in _trd if st == 'failure')
    un = sum(1 for _, st in _trd if st == 'unresolved')
    non_trading = len(_hol)
    trading_dates = len({d for d, st in _trd if st in ('success', 'failure', 'unresolved')})
    return {
        'success': ok, 'failure': bad, 'unresolved': un,
        'open': sum(1 for _, st in _trd if st == 'open'),
        'data_error': int(counts.get('data_error') or 0),
        'excluded': excluded,
        'non_trading': non_trading,
        'non_trading_decided': sum(1 for _, st in _hol if st in ('success', 'failure', 'unresolved')),
        'trading_dates': trading_dates,
        'frozen': sum(int(v) for k, v in counts.items() if k not in EXCLUDED_STATUSES),
        'resolved': ok + bad + un,
        'decided': ok + bad,
        'success_pct': (ok / (ok + bad) * 100.0) if (ok + bad) else None,
    }
