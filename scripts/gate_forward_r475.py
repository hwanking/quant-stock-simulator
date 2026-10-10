# -*- coding: utf-8 -*-
"""사전등록 R475 채점기 — '비용 차감 기대값 양수'가 막은 개장 전 후보는 **앞으로의 자료에서** 비용 뒤에 벌었나.

권위는 `docs/PREREG_R475_EV_GATE_FORWARD.md` 다. 결과를 보기 전(2026-10-10 · 표본 구간이 아직 시작도 안 했다)에 짰다.
이 파일을 고치면 사전등록에 박은 해시도 사유와 함께 같이 간다(동결 자물쇠 ⓐ · 회귀 §457).

    python scripts/gate_forward_r475.py     # 판정할 수 있으면 판정 · 아니면 '미측정'과 사유 (종료 코드 2)

■ 무엇을 재나
  사용자(2026-10-10): *"이거 너무 보수적 아니야?"* — 지난 자료(2026-07-31~)로는 막힌 후보 229건 · 날짜 42일의 비용 뺀 평균이
  +0.11% [−0.83, +1.04] 였다. 그 자료는 **이미 봤다**(R418·R433·R444·R475) — 그래서 판정은 앞으로의 자료로만 한다(R468 표준).

■ 고정한 것 (새 문턱 없음 — 비용은 운영 값 · 하한은 R84·R45 의 날짜 30 · 지평은 채점기의 20봉 · 구간은 `proof.cluster_ci`)
  · 모집단: 추적 케이스를 만든 판(`proof.origin_cores` — 이력의 첫 줄 · 같은 생성 시각의 리포트)의 중앙 판정 조건 목록에서
    이 조건이 미충족인 후보 · 그 날짜(자료 기준일)가 FROM 이후 · 휴장일 날짜 제외.
  · 구간 끝: 그런 후보가 있는 날을 차례로 세어 DATE_FLOOR 번째 날 — **리포트만 읽는다**(결과·봉을 안 읽는다 · 멈추는 규칙이
    결과를 보면 선택 편향이다 · R474 의 `r346_window_end` 와 같은 원칙).
  · 결과: 추적 케이스(같은 채점기 · 리포트 가격 진입 · 20봉)의 실현 수익 − COST. 구간 끝 뒤 20거래일이 지나고 그 안의
    케이스가 전부 정해져야 판정한다.
  · 판정: 날짜로 묶은 95% 구간(BOOT · SEED) — 아래 끝 > 0 → (가) · 위 끝 < 0 → (다) · 그 밖 → (나).
  · 라운드 483 정정(2026-10-11 · 결과 전 · 표본 구간 시작 하루 전) — 추적 케이스의 채점이 그 가격을 **본 순간 이미 열린 장**의 봉을
    뺀다(`prediction_log.grade_after_day` · 장중에 만든 리포트의 가격은 그날 장중 값인데 종전엔 그날 봉 전체 — 그 가격을 보기 전의
    아침 고가·저가까지 — 로 채점했다 · 지난 자료 255건 중 32건). 이 등록은 채점 규칙의 지문을 박지 않았었다 — 추적 채점 함수들의
    소스 지문(`grader_fingerprint`)을 사전등록에 적고 회귀가 대 본다(R478 과 같은 자물쇠).
"""
from __future__ import annotations

import ast
import datetime as _dt
import hashlib
import inspect
import os
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)

GATE = '비용 차감 기대값 양수'
FROM = '2026-10-12'          # 이 채점기를 커밋한 뒤 첫 거래일 — 그 전 날짜는 이미 봤다
DATE_FLOOR = 30              # 날짜 하한(R84·R45 · 시장 수준 표본은 날짜다)
H = 20                       # 채점기의 보유 지평(봉)
COST = 0.41                  # 등록한 날의 운영 왕복 비용(R350) — 운영 값이 바뀌어도 판정은 이 값으로 한다
BOOT = 2000
SEED = 475

VERDICTS = {
    '(가)': '막은 후보가 비용 뒤에도 벌었다 — 이 조건을 다시 볼지는 사람이 정한다(한 시기의 표본이고 진입이 계약과 다르다)',
    '(나)': '0 과 가르지 못한다 — 이 조건은 그대로 둔다',
    '(다)': '막은 후보가 비용 뒤에 잃었다 — 이 조건이 손실을 피했다',
}


def code6(t):
    return str(t or '').split('.')[0]


def gate_failed(core):
    """중앙 판정의 조건 목록에서 이 조건이 미충족인가 — 조건 이름과 통과 여부만 본다."""
    for ck in ((core or {}).get('checks') or []):
        if str((ck or {}).get('name') or '') == GATE and (ck or {}).get('ok') is False:
            return True
    return False


def window_dates(cores, start=FROM, is_off=None):
    """이 조건에 걸린 후보가 있는 날(자료 기준일) — cores 는 `proof.origin_cores` 의 {(코드6, 자료일): 중앙 판정}(추적 케이스를
    만든 판 · 리포트와 이력만 읽는다 · 결과·봉 없음). 휴장일 날짜는 세지 않는다(추적도 안 센다 · R252)."""
    days = set()
    for (_c, d), core in (cores or {}).items():
        if d >= start and not (is_off and is_off(d)) and gate_failed(core):
            days.add(d)
    return sorted(days)


def window_end(cores, start=FROM, floor=DATE_FLOOR, is_off=None):
    """(구간 끝 날짜, 센 날) — 하한에 못 닿으면 (None, 센 날)."""
    ds = window_dates(cores, start, is_off)
    if len(ds) >= floor:
        return ds[floor - 1], floor
    return None, len(ds)


def nth_trading_day(day, n, is_off):
    """day 뒤 n 번째 거래일(day 는 세지 않는다) — 휴장일 판정은 부르는 쪽이 준다(`case_tracker.is_non_trading_date`)."""
    d = _dt.date.fromisoformat(str(day)[:10])
    k = 0
    while k < n:
        d += _dt.timedelta(days=1)
        if d.weekday() < 5 and not is_off(d.isoformat()):
            k += 1
    return d.isoformat()


def judge(cases, cores, today, is_off, start=FROM, floor=DATE_FLOOR):
    """판정 — dict(verdict, why, …). 판정을 못 하면 verdict='미측정'과 사유. cores 는 `proof.origin_cores` 의 첫 값."""
    import proof
    end, n = window_end(cores, start, floor, is_off)
    if end is None:
        return dict(verdict='미측정', why=f"이 조건에 걸린 후보가 있는 날 {n} < 하한 {floor} (시작 {start})", counted=n)
    close = nth_trading_day(end, H, is_off)
    if str(today)[:10] <= close:
        return dict(verdict='미측정', why=f"구간 끝 {end} 의 {H}봉이 {close} 장 마감에 닫힌다 — 그 뒤에 판정한다",
                    window=[start, end], closes_on=close)
    keys = []
    for (c6, d), core in sorted((cores or {}).items(), key=lambda kv: (kv[0][1], kv[0][0])):
        if d < start or d > end or (is_off and is_off(d)) or not gate_failed(core):
            continue
        fails = [str(c.get('name') or '') for c in (core.get('checks') or []) if c.get('ok') is False]
        keys.append(((c6, d), fails == [GATE], core.get('expected_return')))
    by_key = {(code6(c.get('ticker')), str(c.get('signal_date'))[:10]): c for c in cases or []}
    rows, missing, pending = [], 0, 0
    for key, only, ev in keys:
        cs = by_key.get(key)
        if cs is None:
            missing += 1
            continue
        if cs.get('status') not in ('success', 'failure', 'unresolved'):
            pending += 1
            continue
        try:
            net = float(cs.get('realized_return')) * 100.0 - COST
        except (TypeError, ValueError):
            missing += 1
            continue
        rows.append((key[1], net, only, ev, cs))
    if pending:
        return dict(verdict='미측정', why=f"구간 안 케이스 {pending}건이 아직 기간 중", window=[start, end], pending=pending)
    by_date = {}
    for d, net, *_ in rows:
        by_date.setdefault(d, []).append(net)
    ci = proof.cluster_ci(by_date, BOOT, SEED)
    if not rows or ci is None:
        return dict(verdict='미측정', why=f"짝이 맞은 케이스 {len(rows)}건 · 날짜 {len(by_date)} — 구간을 못 낸다",
                    window=[start, end], missing=missing)
    v = '(가)' if ci[0] > 0 else ('(다)' if ci[1] < 0 else '(나)')
    only_by = {}
    for d, net, only, *_ in rows:
        if only:
            only_by.setdefault(d, []).append(net)
    only_v = [x for xs in only_by.values() for x in xs]
    ev_key = {(code6(cs.get('ticker')), d): float(ev) for d, _n, _o, ev, cs in rows
              if isinstance(ev, (int, float)) and not isinstance(ev, bool)}
    evo = proof.ev_order([cs for *_, cs in rows], ev_key, cost=COST, boot=BOOT, seed=SEED)
    return dict(verdict=v, why=VERDICTS[v], window=[start, end], closes_on=close,
                n=len(rows), dates=len(by_date), mean_net=sum(x for _, x, *_ in rows) / len(rows), ci95=ci,
                missing=missing,
                only=dict(n=len(only_v), dates=len(only_by), mean_net=(sum(only_v) / len(only_v) if only_v else None),
                          ci95=proof.cluster_ci(only_by, BOOT, SEED)),
                ev_order=evo)


def grader_fingerprint():
    """추적 케이스 채점 함수의 소스 지문(줄바꿈·주석과 무관 — AST 를 다시 쓴 글자의 sha256 앞 16자 · 라운드 483).
    일일 루틴의 채점(`make_resolve_open_cases`) · 동결한 줄을 본 시각(`freeze_seen_at`) · 채점기(`grade_prediction` · `grade_seen` ·
    `grade_after_day`) · 결과 → 케이스(`resolution_from_grade`). 결과를 본 뒤 이 중 하나가 바뀌면 판정 전에 드러난다."""
    sys.path.insert(0, os.path.join(PROJ, 'scripts'))
    import prediction_log
    import run_daily_improvement as rdi
    from improvement.performance import resolution_from_grade
    h = hashlib.sha256()
    for fn in (rdi.make_resolve_open_cases, rdi.freeze_seen_at, prediction_log.grade_prediction, prediction_log.grade_seen,
               prediction_log.grade_after_day, resolution_from_grade):
        h.update(ast.unparse(ast.parse(inspect.getsource(fn))).encode('utf-8'))
    return h.hexdigest()[:16]


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:                                          # noqa: BLE001
        pass
    sys.path.insert(0, os.path.join(PROJ, 'scripts'))
    import proof
    import proof_scorecard as ps
    from improvement import case_tracker as ct
    cores, _n = proof.origin_cores(ps.load_history(), ps.load_reports())
    r = judge(ps.tracker_cases(), cores, _dt.date.today().isoformat(), ct.is_non_trading_date)
    print(f"R475 — '{GATE}'가 막은 후보 (전방 · {FROM} 부터): {r['verdict']} — {r['why']}")
    print(f"  채점 규칙 지문 {grader_fingerprint()}")
    for k in ('window', 'closes_on', 'n', 'dates', 'mean_net', 'ci95', 'missing', 'only', 'ev_order'):
        if k in r:
            print(f"  {k}: {r[k]}")
    return 0 if r['verdict'] != '미측정' else 2


if __name__ == '__main__':
    sys.exit(main())
