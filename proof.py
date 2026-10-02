# -*- coding: utf-8 -*-
"""가늠 PROOF — 남긴 판정을 결과로 다시 채점한다 (라운드 418).

■ 왜 이 모듈이 있나
  사용자(2026-10-02): *"우리 사이트만의 특징이 있을까? … 없으면 있게 해야 하잖아 만들어줘."* 함께 붙인 분석 한 편이
  가늠의 씨앗을 짚었다 — 개장 전 결론을 고정하고 장중에 다시 안 잰다 · 후보가 없으면 억지로 추천하지 않는다 · 우위가
  없으면 없다고 적는다 · 전방 추천을 얼려 추적한다. 그리고 그것이 **한 기능으로 묶여 있지 않다**고 했다. 세어 보니 그보다
  나빴다: 가늠은 종목을 열 때마다 그 판정을 **추가 전용**으로 적고 있었는데(`prediction_log` · 2026-10-02 1,492건 ·
  197종목 · 42일) **그 결과를 아무도 볼 수 없었다** — 채점은 매수 판정만 세는데(`ENTRY_ACTIONS`) 엔진의 판정은 1,492건
  **전부** '사지 마세요'(1,475)·'비중 축소'(17)였고, 화면이 가리키던 '판정 성적표'는 이미 걷어낸 패널이었다.

  그래서 **새 예측을 더하지 않는다.** 이미 남기고 있는 판정을 영수증처럼 보이고, '사지 말라'고 한 판정도 결과로 채점한다.

■ 채점 규칙 — 결과를 보기 전에 여기 고정했다 (새 숫자 없음)
  · 채점기는 원장·추적과 **같은 것**(`prediction_log.grade_prediction` · R232): 진입 = 기록 시점 가격 · 기록 다음 거래일
    봉부터 · 목표·손절 중 **먼저 닿은 쪽** · 같은 봉이면 **손절 먼저**(보수) · 20봉 안에 안 닿으면 20봉째 종가로 만료.
  · 비용은 운영 왕복 비용 하나(`verdict_core.COST_PCT` · R350)를 뺀다.
  · '안 산 성적'은 **판정 1건에 같은 금액**을 넣었다고 본다. 판정이 매수가 아니면(`ENTRY_ACTIONS` 밖) 그 계획대로 샀을 때의
    비용 뺀 수익 r 을 잰다 — r < 0 이면 안 산 쪽이 그만큼 나았고(피한 손실), r > 0 이면 그만큼 놓쳤다(놓친 수익).
    합계 차이 = 피한 손실 − 놓친 수익 = −Σr. **좋고 나쁨의 문턱은 없다** — 부호와 크기만 적는다.
  · 같은 날 판정끼리는 함께 움직인다(R217) — 날짜 수를 같이 적고 **유의성은 재지 않는다**고 말한다.

■ 하지 않는 것
  · 화면에 종목 이름을 남기는 집계를 만들지 않는다 — 산출물(`.portfolio/proof_scorecard.json`)은 **수만** 담는다
    (어느 종목을 열어 봤는지는 개인 자료다 · R164).
  · '세계 최초' 같은 말을 하지 않는다. 확인하지 않은 남의 서비스 이야기를 화면에 적지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
SCORECARD_FILE = os.path.join(BASE, '.portfolio', 'proof_scorecard.json')
#: 영수증 번호에 넣는 칸 — 기록이 처음 쓰일 때 고정된 것만 (나중에 붙는 칸은 번호를 바꾸지 않는다)
_ID_FIELDS = ('ticker', 'date', 'price', 'action', 'target', 'stop', 'horizon_days', 'recorded_at')


def _cost():
    try:
        import verdict_core
        return float(verdict_core.COST_PCT)
    except Exception:                                          # noqa: BLE001
        return None


def code6(ticker):
    return str(ticker or '').split('.')[0]


def receipt_id(row):
    """판정 영수증 번호 — `GNM-YYYYMMDD-코드-해시6`. 같은 기록이면 늘 같은 번호(기록은 추가 전용 · 첫 판만 남는다)."""
    row = row or {}
    body = json.dumps({k: row.get(k) for k in _ID_FIELDS}, ensure_ascii=False, sort_keys=True, default=str)
    h = hashlib.sha1(body.encode('utf-8')).hexdigest()[:6].upper()
    return f"GNM-{str(row.get('date') or '')[:10].replace('-', '')}-{code6(row.get('ticker'))}-{h}"


def is_abstain(row):
    """'사지 말라'는 판정인가 — 매수 판정(`prediction_log.ENTRY_ACTIONS`)이 아니면 그렇다."""
    try:
        from prediction_log import ENTRY_ACTIONS
    except Exception:                                          # noqa: BLE001
        ENTRY_ACTIONS = ('BUY', 'ACCUMULATE')
    return str((row or {}).get('action') or '') not in ENTRY_ACTIONS


def outcome(row, bars_df, cost=None):
    """한 판정의 결과 — {'status','return_pct','net_pct','touched_bar','bars_used'} · 채점 못 하면 None.

    status: 'target'(목표 먼저) · 'stop'(손절 먼저) · 'expired'(20봉 안 닿음 · 만료 종가) · 'pending'(아직 기간 중)."""
    import prediction_log as plog
    if bars_df is None:
        return None
    try:
        g = plog.grade_prediction(row, bars_df)
    except Exception:                                          # noqa: BLE001
        return None
    if not g:
        return None
    if g['outcome'] == 'TARGET':
        st = 'target'
    elif g['outcome'] == 'STOP':
        st = 'stop'
    elif g.get('matured'):
        st = 'expired'
    else:
        st = 'pending'
    c = _cost() if cost is None else cost
    ret = float(g['return_pct'])
    return dict(status=st, return_pct=ret,
                net_pct=(None if st == 'pending' or c is None else ret - c),
                touched_bar=g.get('touched_bar'), bars_used=g.get('bars_used'))


def abstain_tally(graded, cost=None):
    """'안 산 성적' — graded: [(row, outcome dict|None)] → 수만 담은 dict (이름 없음).

    판정이 매수가 아닌 것만 센다. 결과가 정해진 것(목표·손절·만료)만 r 을 더한다. 문턱 없음."""
    c = _cost() if cost is None else cost
    n_rows = n_nobars = n_pending = 0
    st = {'target': 0, 'stop': 0, 'expired': 0}
    nets, dates, tgt_d, stp_d = [], set(), [], []
    for row, oc in graded:
        if not is_abstain(row):
            continue
        n_rows += 1
        if oc is None:
            n_nobars += 1
            continue
        if oc['status'] == 'pending':
            n_pending += 1
            continue
        st[oc['status']] += 1
        if oc.get('net_pct') is not None:
            nets.append(float(oc['net_pct']))
            dates.add(str(row.get('date'))[:10])
            try:                                               # 계획의 두 선까지 거리(기록 가격 대비 %) — 잰 값만
                p = float(row['price'])
                tgt_d.append((float(row['target']) / p - 1.0) * 100.0)
                stp_d.append((1.0 - float(row['stop']) / p) * 100.0)
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                pass
    n = len(nets)
    avoided = sum(-x for x in nets if x < 0)
    missed = sum(x for x in nets if x > 0)
    srt = sorted(nets)
    med = (srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2.0) if n else None
    return dict(rows=n_rows, decided=n, pending=n_pending, nobars=n_nobars, dates=len(dates),
                target=st['target'], stop=st['stop'], expired=st['expired'],
                mean_net=(sum(nets) / n if n else None), median_net=med,
                share_neg=(sum(1 for x in nets if x < 0) / n if n else None),
                avoided=avoided, missed=missed, balance=(avoided - missed) if n else None,
                target_dist=(sum(tgt_d) / len(tgt_d) if tgt_d else None),
                stop_dist=(sum(stp_d) / len(stp_d) if stp_d else None),
                cost_pct=c)


#: 채점 규칙 한 줄 — 화면이 이것을 읽는다(같은 규칙을 두 곳에 적지 않는다 · §4)
RULE_LINE = ("채점은 원장과 같은 규칙입니다: 진입은 기록 가격 · 기록 다음 거래일부터 목표·손절 중 먼저 닿은 쪽 · "
             "같은 봉이면 손절 먼저 · 20거래일 안에 안 닿으면 그날 종가 · 운영 왕복 비용을 뺍니다.")
#: 결과 갈래의 사람 말
STATUS_KO = {'target': '목표 먼저', 'stop': '손절 먼저', 'expired': '기간 만료', 'pending': '기간 중'}


def abstain_line(t):
    """'안 산 성적' 한 줄 — 수만 적는다 · 좋고 나쁨의 판정 낱말 없음(문턱이 없으므로) · 표본이 없으면 없다고.

    ⚠️ 첫 판은 평균의 부호로 *"안 산 쪽이 나았습니다"* 를 붙였다 — 2026-10-02 첫 채점의 평균이 −0.03% 였는데 그 말이 나갔을
    것이다. 거의 0 인 수에 판정을 붙인 말이고, 같은 판정들의 **중앙은 +2.32%** 로 부호가 반대였다(손절이 목표보다 멀어서 —
    R345·R346). 평균·중앙·안 산 쪽이 나았던 비율을 같이 적고, 부호가 갈리면 갈린다고만 적는다(R149 — 평균 하나만 보면 틀린다)."""
    t = t or {}
    n = int(t.get('decided') or 0)
    if not n:
        return ("안 산 성적 — 아직 결과가 정해진 판정이 없습니다"
                + (f"(기간 중 {int(t.get('pending') or 0):,}건)" if t.get('pending') else '') + '.')
    m = float(t['mean_net'])
    md = t.get('median_net')
    split = (md is not None and ((m < 0 < md) or (md < 0 < m)))
    return (f"안 산 성적 — 엔진이 '사지 말라'고 한 판정 {n:,}건(날짜 {int(t.get('dates') or 0)}일)을 그 계획대로 샀다면 "
            f"목표 먼저 {int(t['target']):,} · 손절 먼저 {int(t['stop']):,} · 기간 만료 {int(t['expired']):,}, "
            f"비용 {t.get('cost_pct')}% 를 뺀 평균 {m:+.2f}%"
            + (f" · 중앙 {float(md):+.2f}%" if md is not None else '')
            + (f" · 안 산 쪽이 나았던 판정 {float(t['share_neg']) * 100:.0f}%" if t.get('share_neg') is not None else '')
            + (" — 평균과 중앙의 부호가 갈립니다" if split else '')
            + (f"(계획의 두 선까지 평균 거리: 목표 +{float(t['target_dist']):.1f}% · 손절 −{float(t['stop_dist']):.1f}%)"
               if split and t.get('target_dist') is not None and t.get('stop_dist') is not None else '')
            + f". 피한 손실 합 {float(t['avoided']):,.0f}%p · 놓친 수익 합 {float(t['missed']):,.0f}%p (판정 1건에 같은 금액). "
            f"같은 날 판정은 함께 움직여 유의성은 재지 않았습니다.")


def gate_ledger(cases, picks_by_key, cost=None):
    """규칙 원장 — 추적 케이스(결과 확정)를 그날 리포트의 조건 통과·미충족으로 갈라 센다 (이름 없음 · 문턱 없음).

    cases: [{'ticker','signal_date','status','realized_return'(분수)}] · picks_by_key: {(코드6, 날짜): core.checks 목록}.
    반환: [{'name', 'blocked': {...}, 'passed': {...}}] — 한 후보가 여러 조건에 걸리므로 겹친다."""
    c = _cost() if cost is None else cost
    acc = {}
    for cs in cases:
        if cs.get('status') not in ('success', 'failure', 'unresolved'):
            continue
        checks = picks_by_key.get((code6(cs.get('ticker')), str(cs.get('signal_date'))[:10]))
        if not checks:
            continue
        try:
            net = float(cs.get('realized_return')) * 100.0 - (c or 0.0)
        except (TypeError, ValueError):
            continue
        for ck in checks:
            nm = str(ck.get('name') or '')
            if not nm:
                continue
            side = 'passed' if ck.get('ok') else 'blocked'
            d = acc.setdefault(nm, {'blocked': [], 'passed': []})
            d[side].append((cs['status'], net))
    out = []
    for nm, d in acc.items():
        row = {'name': nm}
        for side in ('blocked', 'passed'):
            v = d[side]
            row[side] = dict(n=len(v), success=sum(1 for s, _ in v if s == 'success'),
                             failure=sum(1 for s, _ in v if s == 'failure'),
                             unresolved=sum(1 for s, _ in v if s == 'unresolved'),
                             mean_net=(sum(x for _, x in v) / len(v) if v else None))
        out.append(row)
    return sorted(out, key=lambda r: (-r['blocked']['n'], r['name']))


def bars_frame(df):
    """채점기가 읽을 수 있는 일봉 표인가 — `trade_date` 칸이 있어야 한다(없으면 None · 첫 칸을 날짜로 잘못 읽지 않게)."""
    try:
        if df is not None and 'trade_date' in df.columns and len(df):
            return df
    except Exception:                                          # noqa: BLE001
        pass
    return None


def load_scorecard(path=None):
    """성적표 — 이 PC 것(.portfolio) 먼저, 없으면 저장소 동봉본(data/ · 배포 앱용). 찾는 차례는 `artifact_io` 한 곳(§4).
    성적표에는 종목 이름이 없다(수와 조건 이름만) — 그래서 동봉할 수 있다(§9)."""
    if path:
        try:
            with open(path, encoding='utf-8') as f:
                return json.load(f)
        except Exception:                                      # noqa: BLE001
            return None
    try:
        import artifact_io
        return artifact_io.load_json('proof_scorecard.json')
    except Exception:                                          # noqa: BLE001
        return None


def home_lines(report, scorecard):
    """홈 'PROOF' 카드의 줄들 — 오늘 판정(고정 리포트) · 안 산 성적(성적표) · 어디서 보나. 없는 것은 없다고 적는다(§3)."""
    out = []
    r = report or {}
    picks = r.get('picks') or []
    if r:
        n_rec = sum(1 for p in picks if (p.get('core') or {}).get('recommended'))
        out.append(f"오늘 판정 — 신규 매수 {n_rec}종목 · 후보 {len(picks)}종목 · {minute_of(r.get('generated_at'))} 에 고정"
                   f"(기준 데이터 {r.get('data_asof') or '미상'}) · 장중에 다시 계산하지 않습니다.")
    else:
        out.append("오늘 판정 — 아직 고정된 개장 전 리포트가 없습니다.")
    sc = scorecard or {}
    if sc.get('abstain'):
        out.append(abstain_line(sc['abstain'])
                   + f" (성적표 {minute_of(sc.get('made'))} · 판정 원장 {int(sc.get('ledger_rows') or 0):,}건)")
    else:
        out.append("안 산 성적 — 성적표가 아직 없습니다. 평일 장 마감 뒤 이 PC 작업이 판정 원장을 채점해 만듭니다.")
    out.append("판정 영수증은 종목 화면의 '가늠 PROOF · 판정 영수증' 칸에, 조건별 성적은 모델 성적의 '가늠 PROOF 성적표'에 있습니다.")
    return out


def save_scorecard(doc, path=None):
    p = path or SCORECARD_FILE
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)
    return p


def now_iso():
    return datetime.now().isoformat(timespec='seconds')


def minute_of(ts):
    """시각 문자열 → 'YYYY-MM-DD HH:MM' (분까지). 자르지 않고 읽어서 다시 쓴다 — 못 읽으면 원문 그대로(지어내지 않는다 · §3).
    화면이 글자를 잘라 시각을 줄이면 '말없이 자르는 자리' 검사(R314)가 잡는다 — 그래서 여기 한 곳에서 다시 쓴다."""
    s = str(ts or '').strip()
    if not s:
        return ''
    try:
        return datetime.fromisoformat(s.replace(' ', 'T')).strftime('%Y-%m-%d %H:%M')
    except ValueError:
        return s
