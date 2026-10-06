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

import collections
import hashlib
import json
import os
import statistics
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


#: 라운드 433 — 엔진의 매수 쪽 판정 리터럴(`quant_indicators` 의 '사도 됩니다' · '분할매수 검토 가능'). 나머지는 관망·축소·매도다.
ENGINE_BUY_ACTIONS = ('BUY', 'ACCUMULATE')


def latest_by_date(reports, is_off_day=None):
    """날짜마다 마지막 개장 전 리포트 하나(`generated_at` 이 늦은 판) · 휴장일 날짜는 따로 → ({날짜: 리포트}, [휴장일]).
    추천 빈도와 '다 샀다면'이 **같은 후보**를 세게 하는 한 곳(라운드 433 · 첫 판은 둘이 다른 리포트 묶음을 읽었다)."""
    by = {}
    for d in reports or []:
        k = str((d or {}).get('date') or '')[:10]
        if not k:
            continue
        if k not in by or str(d.get('generated_at') or '') > str(by[k].get('generated_at') or ''):
            by[k] = d
    off = sorted(k for k in by if is_off_day and is_off_day(k))
    return {k: by[k] for k in by if k not in off}, off


def pick_keys(latest):
    """{날짜: 리포트} → {(코드6, 날짜): core.checks} — 중앙 판정이 실린 후보만(`candidate_outcome` 의 짝 · §4)."""
    out = {}
    for k, d in (latest or {}).items():
        for p in (d or {}).get('picks') or []:
            ck = ((p or {}).get('core') or {}).get('checks')
            if ck:
                out[(code6(p.get('symbol') or p.get('code')), k)] = ck
    return out


def reco_summary(reports, registry_rows=(), is_off_day=None):
    """'추천이 얼마나 자주 0 이었나' (라운드 433) — 수만 · 문턱 없음 · 셀 리포트가 없으면 None.

    사용자(2026-10-06): *"현재 추천주가 거의 없지 않았어? 괜찮은 거 맞아?"* — 화면은 오늘 하루의 0 만 말했다.
    reports: 개장 전 리포트(같은 날 여럿이면 `generated_at` 이 늦은 판 하나) · 후보마다 **중앙 판정**(`core`)을 센다.
    registry_rows: 전방 기록부 — 매일 **상위 60종목**에 엔진 판정을 남긴다. 정밀분석을 5개보다 깊게 했을 때의 답이다(R264).
    is_off_day(iso) → 참이면 휴장일 — 그날 리포트는 세지 않고 수만 따로 적는다(R252)."""
    by, off = latest_by_date(reports, is_off_day)
    days = sorted(by)
    if not days:
        return None
    cand = no_core = reco = 0
    reco_days, ev, fail = set(), [], collections.Counter()
    for k in days:
        for p in by[k].get('picks') or []:
            c = (p or {}).get('core')
            if not isinstance(c, dict):
                no_core += 1                    # 중앙 판정을 싣기 전의 옛 리포트 — 세지 않고 수만 적는다(§3)
                continue
            cand += 1
            if c.get('recommended'):
                reco += 1
                reco_days.add(k)
            for x in c.get('checks') or []:
                if x.get('ok') is False and x.get('name'):
                    fail[str(x['name'])] += 1
            v = c.get('expected_return')
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                ev.append(float(v))
    reg = list(registry_rows or [])
    top = fail.most_common(1)
    return dict(days=len(days), first=days[0], last=days[-1], off_days=len(off),
                candidates=cand, no_core=no_core, recommended=reco, reco_days=len(reco_days),
                ev_n=len(ev), ev_pos=sum(1 for x in ev if x > 0),
                ev_median=(statistics.median(ev) if ev else None), ev_max=(max(ev) if ev else None),
                top_block=(top[0][0] if top else None), top_block_n=(top[0][1] if top else 0),
                registry_rows=len(reg),
                registry_days=len({str(r.get('date') or '')[:10] for r in reg if r.get('date')}),
                registry_buy=sum(1 for r in reg if str(r.get('action') or '') in ENGINE_BUY_ACTIONS))


def candidate_outcome(cases, picks_by_key, cost=None, boot=2000, seed=433):
    """개장 전 후보를 그날 리포트 가격에 **다 샀다면** (라운드 433) — 추적 케이스 중 그날 리포트 후보였던 것 · 결과가 정해진
    것만 · 비용 뺀 수익(%) · 판정 1건에 같은 금액. 짝짓기는 `gate_ledger` 와 같다(§4). 짝이 하나도 없으면 None.

    평균에는 **날짜로 묶어 다시 뽑은 95% 구간**을 붙인다 — 같은 날 후보는 함께 움직이므로 건수가 아니라 날짜가 표본이다
    (R217 · R45). 시드 고정이라 같은 자료면 같은 구간이다. 문턱은 없다 — 0 을 포함하는지만 말한다."""
    c = _cost() if cost is None else cost
    v, dates, st = [], set(), collections.Counter()
    by_date = {}
    for cs in cases or []:
        if cs.get('status') not in ('success', 'failure', 'unresolved'):
            continue
        key = (code6(cs.get('ticker')), str(cs.get('signal_date'))[:10])
        if not picks_by_key.get(key):
            continue
        try:
            net = float(cs.get('realized_return')) * 100.0 - (c or 0.0)
        except (TypeError, ValueError):
            continue
        v.append(net)
        st[cs['status']] += 1
        dates.add(key[1])
        by_date.setdefault(key[1], []).append(net)
    if not v:
        return None
    ci = None
    if boot and len(by_date) >= 2:
        import random
        rng, ds, means = random.Random(seed), sorted(by_date), []
        for _ in range(int(boot)):
            xs = [x for d in (rng.choice(ds) for _ in ds) for x in by_date[d]]
            means.append(sum(xs) / len(xs))
        means.sort()
        ci = [means[int(0.025 * len(means))], means[int(0.975 * len(means)) - 1]]
    return dict(n=len(v), dates=len(dates), success=st['success'], failure=st['failure'],
                unresolved=st['unresolved'], mean_net=sum(v) / len(v), median_net=statistics.median(v), cost_pct=c,
                ci95=ci, boot=int(boot or 0), seed=seed)


def reco_line(sc):
    """'추천이 얼마나 자주 0 이었나' 한 줄 (라운드 433) — 수만 · '괜찮다'·'보수적이다' 같은 판정 낱말 없음(문턱이 없으므로) ·
    못 읽은 조각은 뺀다(§3). 성적표에 `reco` 가 없으면 None — 부르는 쪽이 줄을 안 그린다."""
    sc = sc or {}
    r = sc.get('reco')
    if not r:
        return None
    parts = [f"개장 전 리포트 {r['days']}거래일({r['first']}~{r['last']}) 후보 {r['candidates']:,}개 중 "
             f"신규 매수 추천 {r['recommended']}개" + (f"(추천이 나온 날 {r['reco_days']}일)" if r['recommended'] else '')]
    if r.get('ev_n'):
        parts.append(f"비용 차감 기대값이 0 보다 큰 후보 {r['ev_pos']}개(중앙 {r['ev_median']:+.2f}% · "
                     f"가장 높은 후보 {r['ev_max']:+.2f}%)")
    if r.get('top_block'):
        parts.append(f"가장 자주 못 넘은 조건 '{r['top_block']}' {r['top_block_n']:,}/{r['candidates']:,}")
    if r.get('registry_rows'):
        parts.append(f"정밀분석을 상위 60종목으로 넓혀 매일 기록한 전방 기록부 {r['registry_days']}거래일 "
                     f"{r['registry_rows']:,}행에서도 엔진의 매수 쪽 판정 {r['registry_buy']}건")
    co = sc.get('candidates')
    if co:
        m, md = float(co['mean_net']), float(co['median_net'])
        ci = co.get('ci95')
        parts.append(f"그 후보를 리포트 가격에 다 샀다면(결과가 정해진 {co['n']:,}건 · 날짜 {co['dates']}일) "
                     f"비용 {co['cost_pct']}% 를 뺀 평균 {m:+.2f}%"
                     + (f"(날짜로 묶어 다시 뽑은 95% 구간 [{ci[0]:+.2f}, {ci[1]:+.2f}] · "
                        + ("0 을 포함" if ci[0] <= 0 <= ci[1] else "0 을 포함하지 않음") + ")"
                        if ci else "")
                     + f" · 중앙 {md:+.2f}%"
                     # 부호가 갈리면 갈린다고만 적는다 — 평균 하나만 보면 틀린다(R149 · abstain_line 과 같은 규칙)
                     + (" — 평균과 중앙의 부호가 갈립니다" if (m < 0 < md) or (md < 0 < m) else ''))
    return "추천이 얼마나 자주 0 이었나 — " + " · ".join(parts) + "."


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
    # 라운드 433 — 오늘 하루의 0 만 말하면 "늘 0 이었나"에 답하지 못한다 · 성적표에 셈이 없으면 안 그린다(§3)
    _rl = reco_line(sc)
    if _rl:
        out.append(_rl)
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


#: 라운드 420 — 배포 앱이 읽는 동봉본. 종전엔 라운드 418 때 **손으로 한 번 복사한 판**에 멈춰 있었다 — 저녁 작업은
#: `.portfolio` 에만 써서 배포 화면의 PROOF 카드가 그날 수를 계속 말했을 것이다. git 에 싣는 것은 여전히 사람이다(R261).
SHIPPED_FILE = os.path.join(BASE, 'data', 'proof_scorecard.json')


def code_like_strings(doc):
    """성적표의 열쇠·글자 값 중 종목코드 모양이 든 것 → 목록(앞 40자). 수는 안 본다 — 종목코드는 글자로만 담기고,
    수를 글자로 읽으면 소수 자리 여섯이 우연히 코드처럼 보인다. 판별식은 `stock_code` 한 곳(§4 · R164)."""
    import stock_code
    bad = []

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(k, str) and stock_code.find_codes(k):
                    bad.append(k[:40])
                walk(v)
        elif isinstance(o, (list, tuple)):
            for v in o:
                walk(v)
        elif isinstance(o, str) and stock_code.find_codes(o):
            bad.append(o[:40])

    walk(doc)
    return bad


def ship_scorecard(doc, path=None):
    """배포용 동봉본을 쓴다 → (쓴 경로 또는 None, 한 줄 사유). 종목코드 모양이 하나라도 있으면 **쓰지 않는다**(§9 —
    성적표는 수와 조건 이름만이라 동봉할 수 있는 것이고, 그 전제가 깨지면 동봉도 멈춘다)."""
    bad = code_like_strings(doc)
    if bad:
        return None, f'종목코드 모양 {len(bad)}개가 들어 있어 동봉하지 않는다 (예: {bad[0]})'
    return save_scorecard(doc, path or SHIPPED_FILE), '배포용 동봉본도 갱신했다'


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
