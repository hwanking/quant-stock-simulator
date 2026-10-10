# -*- coding: utf-8 -*-
"""사전등록 R478 채점기 — '비용 차감 기대값 양수'에 막힌 자동매매 계획을 **계약 그대로** 샀다면 비용 뒤에 벌었나.

권위는 `docs/PREREG_R478_EV_GATE_CONTRACT_FORWARD.md` 다. 결과를 보기 전(2026-10-10 · 장부의 모의 결과 5건 전부 '대기 중' ·
닫힌 결과 0 · 표본 구간은 아직 시작도 안 했다)에 짰다. 이 파일을 고치면 사전등록의 해시도 사유와 함께 같이 간다(동결 자물쇠 ⓐ · 회귀 §459).

    python scripts/gate_forward_r478.py     # 판정할 수 있으면 판정 · 아니면 '미측정'과 사유 (종료 코드 2)

■ 무엇을 재나 — R475 와 다른 점
  R475 는 추적 케이스(개장 전 리포트 가격에 **바로** 산 계획)로 잰다. 자동매매는 그렇게 사지 않는다 — 진입가 지정가를 걸고 최대
  20거래일 기다리고, 안 닿으면 **사지 않는다**. 사용자가 "너무 보수적 아니야?"를 물은 자리가 자동매매 칸이므로, 그 계약 그대로의
  결과가 이 물음의 직접 답이다. 장부(`.portfolio/swing.db`)가 매일 그날 후보의 계획을 남기고 일봉으로 계약대로 굴린 모의 결과를 적는다
  (`swing_engine.shadow_grade` · 라운드 446) — 그 결과를 이 등록이 미리 정한 대로만 센다.

■ 고정한 것 (새 문턱 없음)
  · 모집단: 장부의 계획 중 판정 기록의 미충족 목록에 이 조건이 든 것 · 계획 날짜(자료 기준일)가 FROM 이후 · 휴장일 날짜 제외.
  · 한 계획의 값: 체결돼 닫혔으면 그 수익(return_pct) − COST · 대기 기간에 안 닿았으면(no_fill) **0**(거래가 없었다 · 비용도 없다) ·
    'invalid' 는 빼고 센다. 판정은 이 '계획 1건에 같은 금액' 평균이다 — 게이트가 막는 단위가 계획이므로.
  · 구간 끝: 이 조건에 막힌 계획이 있는 날을 차례로 세어 DATE_FLOOR 번째 날 — **계획 날짜와 판정 기록만 읽는다**(결과·봉·체결 여부를
    안 읽는다 · R474·R475 와 같은 원칙).
  · 판정 시점: 구간 안 계획이 전부 끝났을 때(closed · no_fill · invalid) — 대기 20 + 보유 20 거래일까지 걸릴 수 있다.
  · 판정: 날짜로 묶은 95% 구간(`proof.cluster_ci` · BOOT · SEED) — 아래 끝 > 0 → (가) · 위 끝 < 0 → (다) · 그 밖 → (나).
  · 채점 규칙의 지문: 모의 채점 함수 둘(`swing_engine.shadow_grade` · `prediction_log.grade_prediction`)의 소스 지문을 등록에 박는다 —
    결과를 본 뒤 채점 규칙이 바뀌면 판정 전에 드러난다(`grader_fingerprint`).
  · 라운드 483 정정(2026-10-11 · 결과 전 · 표본 구간 시작 하루 전) — 모의가 계획을 그 판정을 낸 리포트를 **본 순간 이미 열린 장**의
    봉으로 체결시키지 않게 했다(`prediction_log.grade_after_day` · 장중에 만든 리포트의 계획이 그날 아침 저가로 '체결'되던 자리).
    지문이 그 규칙과 생성 시각을 읽는 함수까지 덮는다(넷). 사전등록에 사유와 새 지문을 적었다.
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
FROM = '2026-10-12'          # 이 등록을 커밋한 뒤 첫 거래일
DATE_FLOOR = 30              # 날짜 하한(R84·R45)
COST = 0.41                  # 등록한 날의 운영 왕복 비용(R350) — 판정은 이 값으로
BOOT = 2000
SEED = 478
DONE = ('closed', 'no_fill', 'invalid')

VERDICTS = {
    '(가)': '막힌 계획을 계약대로 샀다면 비용 뒤에도 벌었다 — 이 조건을 다시 볼지는 사람이 정한다(한 시기의 표본이다)',
    '(나)': '0 과 가르지 못한다 — 이 조건은 그대로 둔다',
    '(다)': '막힌 계획을 계약대로 샀다면 비용 뒤에 잃었다 — 이 조건이 손실을 피했다',
}


def _verdict(plan):
    import json
    v = (plan or {}).get('verdict')
    if isinstance(v, dict):
        return v
    try:
        return json.loads(v) if v else {}
    except (TypeError, ValueError):
        return {}


def gate_blocked(plan):
    """이 계획이 이 조건에 막혔나 — 판정 기록의 미충족 목록만 본다."""
    return GATE in (_verdict(plan).get('failed') or [])


def window_dates(plans, start=FROM, is_off=None):
    """이 조건에 막힌 계획이 있는 날 — 계획 날짜와 판정 기록만 읽는다(결과·봉·체결 여부 없음)."""
    days = set()
    for p in plans or []:
        d = str((p or {}).get('data_day') or '')[:10]
        if d and d >= start and not (is_off and is_off(d)) and gate_blocked(p):
            days.add(d)
    return sorted(days)


def window_end(plans, start=FROM, floor=DATE_FLOOR, is_off=None):
    """(구간 끝 날짜, 센 날) — 하한에 못 닿으면 (None, 센 날)."""
    ds = window_dates(plans, start, is_off)
    if len(ds) >= floor:
        return ds[floor - 1], floor
    return None, len(ds)


def grader_fingerprint():
    """모의 채점 함수의 소스 지문(줄바꿈·주석과 무관 — AST 를 다시 쓴 글자의 sha256 앞 16자). 라운드 483 — 대기 창의 시작을 정하는
    두 함수(`swing_engine.report_ts_of` · `prediction_log.grade_after_day`)까지 넷."""
    import prediction_log
    import swing_engine
    h = hashlib.sha256()
    for fn in (swing_engine.shadow_grade, swing_engine.report_ts_of, prediction_log.grade_prediction,
               prediction_log.grade_after_day):
        h.update(ast.unparse(ast.parse(inspect.getsource(fn))).encode('utf-8'))
    return h.hexdigest()[:16]


def judge(plans, shadows, is_off, start=FROM, floor=DATE_FLOOR):
    """판정 — plans: 장부 계획 목록 · shadows: {plan_id: 마지막 모의 결과}. 판정을 못 하면 verdict='미측정'과 사유."""
    import proof
    end, n = window_end(plans, start, floor, is_off)
    if end is None:
        return dict(verdict='미측정', why=f"이 조건에 막힌 계획이 있는 날 {n} < 하한 {floor} (시작 {start})", counted=n)
    pop = [p for p in plans if start <= str(p.get('data_day'))[:10] <= end and gate_blocked(p)
           and not (is_off and is_off(str(p.get('data_day'))[:10]))]
    undone = [p for p in pop if (shadows.get(p['plan_id']) or {}).get('status') not in DONE]
    if undone:
        return dict(verdict='미측정', why=f"구간 안 계획 {len(undone)}건이 아직 끝나지 않았다(대기·보유 중이거나 모의 기록 없음)",
                    window=[start, end], undone=len(undone))
    by_date, fills, invalid = {}, {}, 0
    for p in pop:
        s = shadows[p['plan_id']]
        d = str(p['data_day'])[:10]
        if s['status'] == 'invalid':
            invalid += 1
            continue
        if s['status'] == 'no_fill':
            val = 0.0
        else:
            try:
                val = float(s.get('return_pct')) - COST
            except (TypeError, ValueError):
                invalid += 1
                continue
            fills.setdefault(d, []).append(val)
        by_date.setdefault(d, []).append(val)
    ci = proof.cluster_ci(by_date, BOOT, SEED)
    vals = [x for xs in by_date.values() for x in xs]
    if not vals or ci is None:
        return dict(verdict='미측정', why=f"셀 계획 {len(vals)}건 · 날짜 {len(by_date)} — 구간을 못 낸다", window=[start, end])
    v = '(가)' if ci[0] > 0 else ('(다)' if ci[1] < 0 else '(나)')
    fv = [x for xs in fills.values() for x in xs]
    return dict(verdict=v, why=VERDICTS[v], window=[start, end], n=len(vals), dates=len(by_date),
                mean_net=sum(vals) / len(vals), ci95=ci, invalid=invalid,
                filled=dict(n=len(fv), rate=(len(fv) / len(vals) if vals else None),
                            mean_net=(sum(fv) / len(fv) if fv else None), ci95=proof.cluster_ci(fills, BOOT, SEED)),
                grader=grader_fingerprint())


def load_ledger(path=None):
    """장부를 **읽기 전용**으로 연다 → (계획 목록, {plan_id: 마지막 모의 결과}). 없으면 ([], {})."""
    import sqlite3
    import swing_ledger as L
    p = path or os.path.join(PROJ, '.portfolio', 'swing.db')
    if not os.path.exists(p):
        return [], {}
    c = sqlite3.connect(f'file:{p}?mode=ro', uri=True)
    c.row_factory = sqlite3.Row
    try:
        return L.plans(c), L.shadow_latest(c)
    finally:
        c.close()


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:                                          # noqa: BLE001
        pass
    from improvement import case_tracker as ct
    plans, shadows = load_ledger()
    r = judge(plans, shadows, ct.is_non_trading_date)
    print(f"R478 — '{GATE}'에 막힌 자동매매 계획 (계약 그대로 · 전방 · {FROM} 부터): {r['verdict']} — {r['why']}")
    print(f"  채점 규칙 지문 {grader_fingerprint()}")
    for k in ('window', 'n', 'dates', 'mean_net', 'ci95', 'invalid', 'filled', 'undone'):
        if k in r:
            print(f"  {k}: {r[k]}")
    return 0 if r['verdict'] != '미측정' else 2


if __name__ == '__main__':
    sys.exit(main())
