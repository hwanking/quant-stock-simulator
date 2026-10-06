# -*- coding: utf-8 -*-
"""
라운드 398 — 2026-11-16 전방 재평가 채점기 (R55 · R57 · R66 · 사전등록 글자 그대로).

■ 왜 있나
  전방 기록부(`.portfolio/forward_registry.jsonl` · fr-1)는 매일 쌓이는데 **그것을 채점하는
  코드가 저장소에 없었다.** `forward_eval.py` 는 날짜만 내고 기록부를 읽지 않는다. 읽는
  것은 커버리지·감사 도구뿐이다(horizon_coverage_r349 · rho_coverage_r348 ·
  contamination_audit · forward_registry_check). 판정 기준은 사전등록 문서에만 있었다 —
  그날 손으로 짜면 결과를 보면서 짜게 된다. 그래서 **결과가 없는 지금** 짠다.

■ 새로 정한 것이 없다 (§2)
  · 문턱·지표 정의는 전부 사전등록 문장이거나, 그 등록 숫자를 낸 **실험 스크립트의 함수**를
    불러 쓴다 — 논리를 다시 적지 않는다(R192):
      R55 → scripts/regime_moe_lab.py 의 THR · COST · MIN_CELL_N · PROXIES · metrics · build_states
      R57 → scripts/entry_engine_lab.py 의 H · candidates · fill_of · evaluate
      R66 → scripts/breakout_study.py 의 wilson_low · flags_at (돌파 판정 식은 그 파일 한 곳이다 —
            플래그 파일에 있으면 읽고, 없으면 같은 flags_at 으로 재평가일 봉에서 잰다 · 전방 행은 원장에서
            전부 'blind' 로 찍혀 build_flags 가 건너뛴다. 거짓돌파는 R66 의 **정정 정의**로 여기서 잰다 —
            옛 정의는 R64 가 기각 사유로 쓴 뒤 틀렸다고 밝힌 것이라 쓸 수 없다)
  · 채점은 원장과 같은 채점기 하나 — `prediction_log.grade_prediction`(→ `first_touch` · 20봉 ·
    장중 고가/저가 · 같은 봉 동시 도달은 손절 먼저). 기록부 행은 원장과 **같은 세 칸**으로 채점한다:
    진입 = `price` · 목표 = `hold_trim` · 손절 = `hold_stop`. 이름이 '보유자'인 까닭은
    verdict_core.build 가 원장의 `target_tech_1st`·`stop_loss_price` 를 그 이름으로 옮기기
    때문이다(verdict_core.py `hold_trim = fs['target_tech_1st']` · `hold_stop = fs['stop_loss_price']`).
    `new_*`(진입가 기준)로 채점하면 원장·사전등록 수치와 견줄 수 없다.
  · 원장과 같은 통계 행 규칙 — `ledger_view.stat_rows`(진입가 축척 어긋남 · 같은 종목·날짜 복사본을
    셈에서 뺀다 · R390). 기록부 행에도 채점하는 봉으로 같은 도장(`entry_scale_off`)을 찍는다.

■ 언제 판정하나 — 재평가일 전에는 **판정하지 않는다**
  재평가일은 `forward_eval.eval_date()` 한 곳(박제 파일)이고, 그 전에 돌리면 '미측정'과 사유만
  찍는다. 결과를 미리 보는 순간 "정확히 1회"가 깨진다(R55 §4b). 앞당겨 보는 옵션은 없다.
  기록 구간은 규칙에서 유도한다 — `FORWARD_FROM` 뒤 첫 거래일부터 **45거래일**(R78 §2 ·
  박제 파일의 rule 문장 "45(기록) + 20(채점)"). 고친 달력으로 2026-08-10 ~ 2026-10-16 이고
  (R375 · 사용자 결정 2026-09-28 *"11-16 그대로"* — 45번째(10-16)까지를 11-16 에 채점한다).

■ 두 갈래 (R78 §5 — "둘이 다르면 그 차이가 결과다")
  · 재구성 = 원장(`virtual_graded.jsonl`)의 기준일 FORWARD_FROM 이후 행. R55 박제 파일이 적은
    그대로 *"프록시는 원장 결정시점 필드에서 재구성된다 (scripts/regime_moe_lab.py)"* — **R55·R57
    의 판정 갈래는 이쪽이다.** 기록부에는 프록시 다섯 칸(m10_above·range_pos·bb_pos·
    demark_state·rsi)도 vol20 도 없다(fr-1 FIELDS).
  · 라이브 = 전방 기록부(fr-1). 여기서 채점한 매수권 전체가 라이브 기준선이고, 버전별로도 낸다.
    같은 (종목, 날짜)의 원장 행이 있으면 거기서 프록시를 옮겨 오되, **한 행이라도 비면 라우팅은
    미측정**이다(일부로만 재면 모집단이 바뀐다 · 빈 칸을 '선택 안 됨'으로 읽으면 커버 0% 가
    '기각'으로 둔갑한다 — 라운드 37 의 그 모양 · §3).

■ 버전
  행은 `versions`·`model_sha` 를 싣는다. 사전등록의 판정은 **합계**다(R55 §4b *"기준선 = 같은 전방
  구간의 매수권 전체"*) — R78 §6 은 그 구간 동안 scoring·rulebook 판정 규칙이 동결된다고 전제했다.
  버전별 표는 그 전제가 지켜졌는지 보이려는 공개용이고 **판정에 쓰지 않는다** — 결과를 본 뒤 한
  버전을 고르면 그것이 §2-5 다. 원장 행에는 버전 도장이 없어 재구성 갈래는 버전별로 못 가른다.

    C:/Python314/python.exe scripts/forward_judge.py
      종료 코드 — 0 판정함 · 2 미측정(재평가일 전) · 1 오류
"""
from __future__ import annotations

import datetime as _dt
import glob
import json
import os
import sys
from collections import Counter, defaultdict

try:                       # 라운드 103 — 객체를 갈아끼우지 않는다
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:          # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
for _p in (PROJ, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)
P = os.path.join(PROJ, '.portfolio')

import breakout_study as _bs                                   # noqa: E402
import entry_engine_lab as _el                                 # noqa: E402
import forward_eval as _fe                                     # noqa: E402
import ledger_view as _lv                                      # noqa: E402
import prediction_log as _plog                                 # noqa: E402
import regime_moe_lab as _rm                                   # noqa: E402

# ── 사전등록에서 온 숫자 (새로 고른 것 없음) ──────────────────────────────
#: 기록 구간 길이 — R78 §2 "2026-08-10 + 45거래일 → 마지막 판정 기록일" · 박제 rule "45(기록) + 20(채점)"
RECORD_DAYS = 45
#: 지평 — 원장 전 케이스가 이 값이다(forward_eval 한 곳)
H = _fe.HORIZON_DAYS
#: R55 — 매수권 문턱 · 비용 · §3 의 n 하한 · 프록시 · 지표 (실험 스크립트의 것을 그대로)
THR, COST, MIN_ROUTED = _rm.THR, _rm.COST, _rm.MIN_CELL_N
metrics = _rm.metrics
PROXIES = _rm.PROXIES
PROXY_FIELDS = ('m10_above', 'range_pos', 'bb_pos', 'demark_state', 'rsi')
#: R55 §4 — 적중 허용 폭(%p) · 커버(%) · 월평균(건)
R55_HIT_TOL, R55_COVER_MIN, R55_MONTHLY_MIN = 1.0, 30.0, 10.0
#: R57 §3-2 — 체결률(20봉) 하한(%)
R57_FILL_MIN = 50.0
R57_CHAMP, R57_BASE = '즉시', '현행눌림(-1vol)'     # entry_engine_lab.candidates 의 이름
#: R64 §4-3 · R66 §3-3 — 돌파 에피소드 하한 · §3 에피소드 = 같은 종목 35일 묶음
R66_EP_MIN, R66_EP_GAP_DAYS = 300, 35
#: R66 §2 — 정정 거짓돌파: 돌파 후 5봉 이내 종가가 돌파선 아래 마감 · §3-4 비율 상한(%)
R66_FALSE_BARS, R66_FALSE_MAX = 5, 50.0
#: 평균 달력 월(일) — 월평균 '구간 길이에 비례 환산'(R55 §4b)의 정의 상수 (문턱 아님)
MONTH_DAYS = 365.25 / 12

PINNED55 = os.path.join(PROJ, 'data', 'regime_routing_r55.json')
PINNED57 = os.path.join(PROJ, 'data', 'entry_engine_r57.json')


# ══════════════════════════════════════════════════════════════════════
# 날짜 — 재평가일 관문 · 기록 구간
# ══════════════════════════════════════════════════════════════════════
def _cal():
    import bitemporal_engine as _be
    return _be.KrxCalendar()


def nth_trading_day(start, n, cal=None):
    """start 부터(포함) n 번째 거래일. 회귀 §143 의 투영과 같은 셈."""
    cal = cal or _cal()
    d, c = _dt.date.fromisoformat(str(start)[:10]), 0
    for _ in range(4000):
        if cal.is_trading_day(d):
            c += 1
            if c == n:
                return d.isoformat()
        d += _dt.timedelta(days=1)
    return None


def record_window(start=None, n=RECORD_DAYS, cal=None):
    """(첫 기록 거래일, 마지막 기록 거래일) — FORWARD_FROM 뒤 첫 거래일부터 n 거래일."""
    first = nth_trading_day(start or _fe.FORWARD_FROM, 1, cal)
    last = nth_trading_day(first, n, cal) if first else None
    return first, last


def judge_gate(today=None, eval_date=None):
    """(판정해도 되나, 사유, 재평가일). 재평가일 **전이면 판정하지 않는다.**

    재평가일을 못 읽으면 지어내지 않는다 — 판정하지 않는다(§3)."""
    ed = eval_date if eval_date is not None else _fe.eval_date()
    if not ed:
        return False, '박제 파일에서 재평가일을 읽지 못했다 — 날짜를 지어내지 않는다', None
    if today is None:
        from improvement.issue_ops import _today            # 지역 날짜 한 곳 (R306)
        today = _today()
    t = str(today)[:10]
    if t < str(ed)[:10]:
        return (False, f'재평가일 {ed} 전이다(오늘 {t}) — 사전등록은 전방을 정확히 1회만 본다. '
                       f'그 전에 결과를 보면 그 1회가 오염된다', ed)
    return True, '', ed


def months_prorated(first, last):
    """구간 길이(달력일)를 평균 달력 월로 나눈 값 — R55 §4b '월평균은 구간 길이에 비례 환산'."""
    a, b = _dt.date.fromisoformat(first), _dt.date.fromisoformat(last)
    return ((b - a).days + 1) / MONTH_DAYS


def in_window(rows, first, last):
    return [r for r in rows if first <= str(r.get('date'))[:10] <= last]


# ══════════════════════════════════════════════════════════════════════
# 라이브 갈래 — 전방 기록부를 원장 채점기로
# ══════════════════════════════════════════════════════════════════════
def _closes(pdf):
    """일봉 → {날짜: 원시 종가} (calibration_lab 의 _closes390 과 같은 칸 고르기)."""
    try:
        dcol = 'trade_date' if 'trade_date' in pdf.columns else pdf.columns[0]
        ccol = 'close_raw' if 'close_raw' in pdf.columns else 'close'
        return {str(d)[:10]: float(c) for d, c in zip(pdf[dcol], pdf[ccol])}
    except Exception:                                          # noqa: BLE001
        return {}


def grade_registry(rows, bars_by_ticker):
    """기록부 행 → 원장 모양의 채점 행. 반환 (채점 행, 빠진 사유별 수).

    채점은 `prediction_log.grade_prediction` 하나 — 원장과 같은 봉·같은 순서 규칙.
    진입 = price · 목표 = hold_trim · 손절 = hold_stop (원장의 target_tech_1st·stop_loss_price).
    """
    out, why = [], Counter()
    closes = {}
    for r in rows:
        tk = str(r.get('ticker'))
        if r.get('hold_trim') is None or r.get('hold_stop') is None or not r.get('price'):
            why['보유자 레벨·가격 없음'] += 1
            continue
        pdf = bars_by_ticker.get(tk)
        if pdf is None:
            why['시세 미수신'] += 1
            continue
        g = _plog.grade_prediction({'date': str(r['date'])[:10], 'price': float(r['price']),
                                    'target': float(r['hold_trim']), 'stop': float(r['hold_stop']),
                                    'horizon_days': int(r.get('horizon_days') or H)}, pdf)
        if not g or not g.get('matured'):
            why['20봉 미경과'] += 1
            continue
        if tk not in closes:
            closes[tk] = _closes(pdf)
        v = r.get('versions') if isinstance(r.get('versions'), dict) else {}
        out.append({
            'ticker': tk, 'date': str(r['date'])[:10], 'score': r.get('score'),
            'price': float(r['price']),
            'outcome': g['outcome'], 'touched_bar': g.get('touched_bar'),
            # 원장이 담는 자릿수 그대로 (calibration_lab 의 round(…, 2))
            'return_pct': round(g['return_pct'], 2),
            'close_return_pct': round(g['close_return_pct'], 2),
            'success': g['outcome'] == 'TARGET',
            'same_bar': g.get('same_bar'),
            'entry_scale_off': _lv.entry_scale_off(r.get('price'),
                                                   closes[tk].get(str(r['date'])[:10])),
            'model_version': v.get('model'), 'rulebook_version': v.get('rulebook'),
            'scoring_version': v.get('scoring'), 'model_sha': r.get('model_sha'),
            **{k: r[k] for k in PROXY_FIELDS if k in r},
        })
    return out, why


def population(rows, first, last, keys=None, min_score=THR):
    """사전등록 측정과 같은 모집단 — 구간 안 · 점수 ≥ min_score · 판정완료(OPEN 제외) · 통계 행.

    regime_moe_lab.main 의 거르기 그대로(블라인드 표시는 보지 않는다 — 전방 행은 원장에서 전부
    'blind' 로 찍히므로 구간으로 고른다). 반환 (행, 뺀 사유별 수)."""
    why = Counter()
    sub = []
    for r in in_window(rows, first, last):
        if min_score is not None and float(r.get('score') or 0) < min_score:
            continue
        if r.get('outcome') == 'OPEN':
            why['OPEN(20봉 안 미도달 · 측정 제외)'] += 1
            continue
        sub.append(r)
    cnt = {}
    kept = list(_lv.stat_rows(sub, keys=keys, counter=cnt))
    if cnt.get('scale'):
        why['진입가 축척 어긋남(통계 제외)'] += cnt['scale']
    if cnt.get('dup'):
        why['같은 종목·날짜 복사본(통계 제외)'] += cnt['dup']
    return kept, why


def by_version(rows, key='model_version'):
    g = defaultdict(list)
    for r in rows:
        g[str(r.get(key) or '(도장 없음)')].append(r)
    return dict(sorted(g.items()))


def copy_proxies(reg_rows, ledger_rows):
    """같은 (종목 6자리, 날짜)의 원장 행에서 프록시 다섯 칸을 옮긴다. 반환 (옮긴 행 수)."""
    idx = {_lv.scale_key(r.get('ticker'), r.get('date')): r for r in ledger_rows}
    n = 0
    for r in reg_rows:
        src = idx.get(_lv.scale_key(r.get('ticker'), r.get('date')))
        if src is not None and all(k in src for k in PROXY_FIELDS):
            for k in PROXY_FIELDS:
                r[k] = src.get(k)
            n += 1
    return n


# ══════════════════════════════════════════════════════════════════════
# R55 — 국면 라우팅
# ══════════════════════════════════════════════════════════════════════
def cell8(code, vol, vmed):
    """regime_moe_lab.main 이 만드는 칸 이름과 같은 글자 (박제 routing 의 열쇠)."""
    return f"{code}|{'고변동' if vol > vmed else '저변동'}"


def r55_gates(m, base):
    """사전등록 §4 의 네 조건 — regime_moe_lab.main 의 gate() 와 같은 식."""
    return {
        'EV>기준선 & EV>0': m['ev'] > base['ev'] and m['ev'] > 0,
        f'적중 ≥ 기준선-{R55_HIT_TOL}%p': m['hit'] >= base['hit'] - R55_HIT_TOL,
        f'커버≥{R55_COVER_MIN:.0f}% & 월≥{R55_MONTHLY_MIN:.0f}':
            m['cover'] >= R55_COVER_MIN and m['monthly'] >= R55_MONTHLY_MIN,
        'PF > 기준선': m['pf'] > base['pf'],
    }


def r55_judge(rows, states, routing, vmed, months):
    """R55 §4·§4b·§4c 대로 한 갈래를 판정한다. 반환 dict(status='통과'|'기각'|'미측정', …)."""
    out = dict(status='미측정', n_input=len(rows), why=[])
    if not rows:
        out['why'].append('모집단 0행 — 잴 것이 없다')
        return out
    lacking = [r for r in rows if not all(k in r for k in PROXY_FIELDS)]
    if lacking:
        out['why'].append(f'프록시 칸이 없는 행 {len(lacking):,}/{len(rows):,} — 라우팅을 적용할 수 없다 '
                          f'(빈 칸을 "선택 안 됨"으로 읽으면 커버 0% 가 기각으로 둔갑한다 · §3)')
        out['proxy_missing'] = len(lacking)
        return out
    joined = []
    for r in rows:
        st = states.get(str(r.get('date'))[:10])
        if st is None:
            continue
        r['_cell8'] = cell8(st[0], st[1], vmed)
        joined.append(r)
    out['index_dropped'] = len(rows) - len(joined)          # 랩: '지수 이력 밖(측정 제외)'
    if not joined:
        out['why'].append('국면(코스피 일봉)을 한 행에도 못 붙였다 — 지수를 못 받았으면 칸을 못 정한다')
        return out
    rows = joined
    cells = Counter(r['_cell8'] for r in rows)
    out['cells'] = dict(sorted(cells.items()))
    pmap = dict(PROXIES)
    unknown = [c for c in cells if c in routing and routing[c] not in pmap]
    if unknown:
        out['why'].append(f'박제 routing 의 프록시 이름을 실험 스크립트가 모른다: {unknown}')
        return out
    sel = [r for r in rows if (r['_cell8'] not in routing) or pmap[routing[r['_cell8']]](r)]
    base = metrics(rows, len(rows), months) if rows else None
    route = metrics(sel, len(rows), months) if rows else None
    out.update(base=base, routing=route, n_routed=len(sel),
               routed_by_cell=dict(sorted(Counter(r['_cell8'] for r in sel).items())))
    # ── 선행 조건 (§4c · R78 §2·§4) — 미달이면 완화하지 않고 미측정 ──
    pre = {
        '국면 칸 ≥ 2 (R78 §2 하한 B · 라우팅이 성립하는 논리적 최소)': len(cells) >= 2,
        f'라우팅 n ≥ {MIN_ROUTED} (R55 §3 · R78 §4 의 읽기: 매수권 × 라우팅 커버)': len(sel) >= MIN_ROUTED,
        f'커버 ≥ {R55_COVER_MIN:.0f}% · 월평균 ≥ {R55_MONTHLY_MIN:.0f}건 (R55 §4-3 · 월은 구간 길이로 환산)':
            bool(route) and route['cover'] >= R55_COVER_MIN and route['monthly'] >= R55_MONTHLY_MIN,
    }
    out['pre'] = pre
    if not all(pre.values()):
        out['why'].append('선행 조건 미달 — ' + ' · '.join(k for k, v in pre.items() if not v))
        return out
    gates = r55_gates(route, base)
    out['gates'] = gates
    out['status'] = '통과' if all(gates.values()) else '기각'
    return out


# ══════════════════════════════════════════════════════════════════════
# R57 — Entry Engine (챔피언 = 박제 '즉시(다음 봉 시가)' · 기준선 = 현행눌림)
# ══════════════════════════════════════════════════════════════════════
def attach_path(r, path, anc=None):
    """entry_engine_lab.main · breakout_study.analyze 가 행에 붙이는 봉 칸 그대로."""
    bars = path['bars'][:H]
    r['_hi'] = [b[1] for b in bars]
    r['_lo'] = [b[2] for b in bars]
    r['_cl'] = [b[3] for b in bars]
    r['_op'] = [(b[5] if len(b) > 5 else None) for b in bars]
    if anc is not None:
        r['_cands'] = _el.candidates(r, anc)
    return r


def r57_rows(rows, paths, anchors):
    out, why = [], Counter()
    for r in rows:
        k = (str(r['ticker']), str(r['date'])[:10])
        p, anc = paths.get(k), anchors.get(k)
        if not p or not anc or p.get('n_bars', 0) < H:
            why['경로 21봉·진입기준선 없음'] += 1
            continue
        out.append(attach_path(dict(r), p, anc))
    return out, why


def r57_judge(rows, label='R57', champion_pinned=None):
    """R57 §3 네 조건. `champion_pinned` 는 박제 파일의 champion 문장 — 채점기의 챔피언과 다르면 재지 않는다."""
    out = dict(status='미측정', n_input=len(rows), why=[])
    if champion_pinned is not None and not str(champion_pinned).startswith(R57_CHAMP):
        out['why'].append(f'박제 챔피언({champion_pinned})이 채점기의 챔피언({R57_CHAMP})과 다르다')
        return out
    if not rows:
        out['why'].append('경로·진입기준선이 붙은 매수권 행 0 — 잴 것이 없다')
        return out
    tab = _el.evaluate(rows, label)
    ch, base = tab.get(R57_CHAMP), tab.get(R57_BASE)
    out['table'] = tab
    if not ch or not base:
        out['why'].append(f'챔피언({R57_CHAMP})·기준선({R57_BASE}) 중 산출 못 한 것이 있다 '
                          f'(기준선은 vol20 이 있어야 선다)')
        return out
    gates = {
        '정책EV > 기준선': ch['policy_ev'] > base['policy_ev'],
        f'체결률 ≥ {R57_FILL_MIN:.0f}%': ch['fill20'] >= R57_FILL_MIN,
        'PF > 기준선': ch['pf'] > base['pf'],
        '체결분 순EV > 0': ch['ev'] > 0,
    }
    out.update(gates=gates, champion=ch, baseline=base,
               status='통과' if all(gates.values()) else '기각')
    return out


# ══════════════════════════════════════════════════════════════════════
# R66 — 돌파 코호트 · 정정된 거짓돌파
# ══════════════════════════════════════════════════════════════════════
def episodes(rows, gap_days=R66_EP_GAP_DAYS):
    """에피소드 수 — 같은 종목 35일 묶음 (breakout_study.analyze 의 ep_n 과 같은 셈)."""
    last, n = {}, 0
    for r in sorted(rows, key=lambda x: (str(x['ticker']), str(x['date']))):
        tk = str(r['ticker'])
        try:
            dd = _dt.date.fromisoformat(str(r['date'])[:10])
        except ValueError:
            continue
        if tk not in last or (dd - last[tk]) > _dt.timedelta(days=gap_days):
            n += 1
            last[tk] = dd
    return n


def false_break(r, bars=R66_FALSE_BARS):
    """R66 §2 정정 정의 — 돌파 후 5봉 이내 **종가**가 돌파선 아래로 마감(스침은 아니다)."""
    return any(c < r['_fl']['break_line'] for c in r['_cl'][:bars])


def entry_nets(sub, method):
    """진입 방식별 순수익(%) — R64 §3 ①~④. ①②③ 은 breakout_study.analyze.stat 의 식,
    ④ 현행 눌림가는 entry_engine_lab 의 '현행눌림(-1vol)' 후보를 같은 fill_of 로 잰다(체결분만)."""
    net = []
    for r in sub:
        cl = r['_cl'][-1]
        if method == 'close':
            net.append(cl - COST)
        elif method == 'open1':
            net.append(((1 + cl / 100) / (1 + (r['_op'][0] or 0) / 100) - 1) * 100 - COST)
        elif method == 'retest':
            if any(r['_lo'][i] <= 0.0 for i in range(2, min(10, H))):
                net.append(cl - COST)
        elif method == 'pullback':
            v = r.get('vol20')
            if not (isinstance(v, (int, float)) and v > 0):
                continue
            fb, fp = _el.fill_of(-float(v) * 100, False, r['_lo'], r['_hi'], r['_op'])
            if fb is not None:
                net.append(((1 + cl / 100) / (1 + fp / 100) - 1) * 100 - COST)
    return net


def r66_stat(sub, method='close'):
    if not sub:
        return None
    n = len(sub)
    k = sum(1 for r in sub if r.get('success'))
    net = entry_nets(sub, method)
    pos = sum(x for x in net if x > 0)
    neg = -sum(x for x in net if x < 0)
    return dict(n=n, ep=episodes(sub), hit=k / n * 100, wilson=_bs.wilson_low(k, n),
                n_entry=len(net), ev=(sum(net) / len(net) if net else None),
                pf=(pos / neg if neg > 0 else None))


R66_METHODS = (('close', '① 돌파일 종가'), ('open1', '② 다음 봉 시가'),
               ('retest', '③ 3~10봉 되눌림 대기'), ('pullback', '④ 현행 눌림가'))


def compute_missing_flags(rows, flags, bars_of):
    """플래그 파일에 없는 행의 돌파 플래그를 `breakout_study.flags_at` 으로 잰다(파일에 안 쓴다).

    전방 행은 원장에서 전부 'blind' 로 찍혀 `build_flags` 가 건너뛴다(2026-10-01 실측: 구간 안
    원장 행 4,402 중 플래그 0). 식은 그 파일 한 곳 — 여기는 봉을 대 주고 j 를 찾을 뿐이다(build_flags
    의 `len(df) < 260` · `j < 245` 거르기 그대로). 신호일 **이전 봉만** 쓰므로 나중에 재도 누출이
    아니다(R78 §5). `bars_of(ticker)` 는 일봉 DataFrame 또는 None. 반환 (플래그, 못 잰 사유별 수)."""
    need = defaultdict(set)
    for r in rows:
        k = (str(r['ticker']), str(r['date'])[:10])
        if k not in flags:
            need[k[0]].add(k[1])
    made, why = {}, Counter()
    for tk in sorted(need):
        ds = need[tk]
        df = bars_of(tk)
        if df is None:
            why['시세 미수신'] += len(ds)
            continue
        if len(df) < 260:
            why['일봉 260 미만'] += len(ds)
            continue
        dates = list(df['trade_date'].astype(str).str[:10])
        idx = {d: j for j, d in enumerate(dates)}
        C = df['adj_close'].astype(float).to_numpy()
        V = df['volume'].astype(float).to_numpy()
        for d in sorted(ds):
            j = idx.get(d)
            if j is None or j < 245:
                why['신호일 봉 없음·앞 봉 245 미만'] += 1
                continue
            made[(tk, d)] = {'ticker': tk, 'date': d, **_bs.flags_at(C, V, j)}
    return made, why


def r66_rows(rows, flags, paths):
    out, why = [], Counter()
    for r in rows:
        k = (str(r['ticker']), str(r['date'])[:10])
        fl, p = flags.get(k), paths.get(k)
        if not fl:
            why['돌파 플래그 없음'] += 1
            continue
        if not p or p.get('n_bars', 0) < H:
            why['경로 21봉 없음'] += 1
            continue
        rr = attach_path(dict(r), p)
        rr['_fl'] = fl
        out.append(rr)
    return out, why


def r66_judge(rows):
    out = dict(status='미측정', n_input=len(rows), why=[])
    if not rows:
        out['why'].append('돌파 플래그·경로가 붙은 행 0 — 잴 것이 없다')
        return out
    br = [r for r in rows if r['_fl'].get('b1') or r['_fl'].get('b2')]
    nb = [r for r in rows if not (r['_fl'].get('b1') or r['_fl'].get('b2'))]
    s_nb = r66_stat(nb, 'close')
    stats = {m: r66_stat(br, m) for m, _ in R66_METHODS}
    fb = (sum(1 for r in br if false_break(r)) / len(br) * 100) if br else None
    ep = stats['close']['ep'] if stats['close'] else 0
    out.update(n_break=len(br), n_non=len(nb), episodes=ep, false_break=fb,
               stats=stats, non_break=s_nb)
    # §5c — 에피소드 하한을 먼저 본다. 미달이면 완화하지 않고 미측정
    if ep < R66_EP_MIN:
        out['why'].append(f'돌파 에피소드 {ep} < {R66_EP_MIN} (R64 §4-3 · §5c — 먼저 확인)')
        return out
    if not s_nb or s_nb['ev'] is None:
        out['why'].append('비돌파 대조군을 못 셌다')
        return out

    def g14(m):
        s = stats.get(m)
        ev = s and s['ev']
        return {
            '1 비용후 EV > 0 이고 비돌파보다 높다': ev is not None and ev > 0 and ev > s_nb['ev'],
            '2 Wilson 하한 > 비돌파 적중': bool(s) and s['wilson'] > s_nb['hit'],
            f'3 에피소드 ≥ {R66_EP_MIN}': bool(s) and s['ep'] >= R66_EP_MIN,
            f'4 거짓돌파(정정 정의) < {R66_FALSE_MAX:.0f}%': fb is not None and fb < R66_FALSE_MAX,
        }
    per = {m: g14(m) for m, _ in R66_METHODS}
    gates = dict(per['close'])                    # 1~4 는 기본 진입(돌파일 종가 · R64 §3 대조와 같은 진입)
    gates['5 진입 방식 중 하나가 1~4 전부'] = any(all(v.values()) for v in per.values())
    out.update(gates=gates, per_method=per, status='통과' if all(gates.values()) else '기각')
    return out


# ══════════════════════════════════════════════════════════════════════
# 자료 읽기 (재평가일에만 · 결과가 아닌 구조는 그 전에도)
# ══════════════════════════════════════════════════════════════════════
def _jsonl(path):
    out = []
    if not os.path.exists(path):
        return out
    with open(path, encoding='utf-8', errors='replace') as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                try:
                    out.append(json.loads(ln))
                except Exception:                              # noqa: BLE001
                    continue
    return out


def load_ledger_forward(first, last, path=None):
    """원장에서 구간 안 기준일 행만 (전 원장을 메모리에 올리지 않는다)."""
    path = path or os.path.join(P, 'virtual_graded.jsonl')
    out = []
    if not os.path.exists(path):
        return out
    y0 = f'"date": "{first[:4]}-'
    with open(path, encoding='utf-8', errors='replace') as f:
        for ln in f:
            if y0 not in ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:                                  # noqa: BLE001
                continue
            if first <= str(r.get('date'))[:10] <= last:
                out.append(r)
    return out


def load_keyed(pattern, first, last):
    """(종목, 날짜) → 행 — 구간 안 날짜만. `.bak` 은 읽지 않는다."""
    m = {}
    y0 = f'"date": "{first[:4]}-'
    for path in sorted(glob.glob(os.path.join(P, pattern))):
        if path.endswith('.bak'):
            continue
        with open(path, encoding='utf-8', errors='replace') as f:
            for ln in f:
                if y0 not in ln:
                    continue
                try:
                    q = json.loads(ln)
                except Exception:                              # noqa: BLE001
                    continue
                d = str(q.get('date'))[:10]
                if first <= d <= last:
                    m[(str(q.get('ticker')), d)] = q
    return m


def premise_releases(first, last):
    """구간 안의 model·scoring·rulebook 릴리스 중 화면·문구(ui·copy)가 아닌 것 — R78 §6 전제 점검."""
    try:
        import versioning as _v
        hist = _v.history(limit=100000)
    except Exception:                                          # noqa: BLE001
        return None
    out = []
    for e in hist:
        v = str(e.get('version') or '')
        d = v[1:11].replace('.', '-') if v.startswith('v') else ''
        if e.get('axis') in ('model', 'scoring', 'rulebook') and first <= d <= last \
                and e.get('kind') not in ('ui', 'copy'):
            out.append((e.get('axis'), v, e.get('kind')))
    return out


def _fmt(m):
    if not m:
        return '산출 없음'
    return _rm.fmt(m)


def _fmt_short(m):
    """버전별 줄 — 커버·월평균은 그 버전 안에서는 뜻이 없어 뺀다."""
    if not m:
        return '산출 없음'
    return (f"적중 {m['hit']:5.1f}% (W {m['wilson']:4.1f}) · 순EV {m['ev']:+.3f} · "
            f"PF {m['pf']:.2f} · n {m['n']:,}")


def feasibility(first, last):
    """재평가일 전 — **결과가 아닌 구조만** 센다(행 수·칸 유무·날짜). 채점하지 않는다."""
    import forward_registry as _fr
    reg = in_window(_fr.load(), first, last)
    print(f'\n■ 준비 상태 (결과 아님 — 채점하지 않았다 · 점수·칸 유무·날짜만)')
    cov = _fr.date_coverage(start=first, today=min(last, _dt.date.today().isoformat()))
    print(f'  라이브(전방 기록부 fr-1): 구간 안 {len(reg):,}행 · 기록된 거래일 '
          f'{cov["recorded"]}/{cov["trading_days"]} · 매수권(≥{THR:.0f}) {sum(1 for r in reg if float(r.get("score") or 0) >= THR):,}행 '
          f'(OPEN 제외 전) · model 버전 {len({(r.get("versions") or {}).get("model") for r in reg})}개')
    has_px = sum(1 for r in reg if all(k in r for k in PROXY_FIELDS))
    print(f'    프록시 다섯 칸 있는 행 {has_px}/{len(reg)} · vol20 칸 있는 행 '
          f'{sum(1 for r in reg if "vol20" in r)}/{len(reg)} · 돌파 에피소드 상한(전 행을 돌파로 쳐도) '
          f'{episodes(reg)} (하한 {R66_EP_MIN})')
    led = load_ledger_forward(first, last)
    paths = load_keyed('bar_paths_s*.jsonl', first, last)
    anch = load_keyed('entry_anchors_s*.jsonl', first, last)
    flags = load_keyed('breakout_flags_s*.jsonl', first, last)
    lk = {(str(r['ticker']), str(r['date'])[:10]) for r in led}
    print(f'  재구성(원장 virtual_graded): 구간 안 {len(led):,}행 · 날짜 '
          f'{len({str(r["date"])[:10] for r in led})}일 · 매수권 '
          f'{sum(1 for r in led if float(r.get("score") or 0) >= THR):,}행 (OPEN 제외 전)')
    print(f'    경로 {len(lk & set(paths)):,} · 진입기준선 {len(lk & set(anch)):,} · '
          f'돌파 플래그 {len(lk & set(flags)):,} (구간 안 원장 행 {len(lk):,} 중)')
    if not (lk & set(flags)):
        print('    ⚠ 돌파 플래그가 전방 행에 하나도 없다 — breakout_study.build_flags 가 '
              "split=='blind' 행을 건너뛰고, 전방 행은 원장에서 전부 'blind' 로 찍힌다. "
              '재평가일에 이 채점기가 같은 식(breakout_study.flags_at)으로 오늘 봉에서 잰다(파일에 안 씀).')
    rel = premise_releases(first, last)
    if rel is not None:
        kinds = Counter(f'{a}:{k}' for a, _v, k in rel)
        print(f'  전제 점검(R78 §6 동결): 구간 안 ui·copy 가 아닌 릴리스 {len(rel)}건 — '
              + ', '.join(f'{k} {n}' for k, n in sorted(kinds.items())))


def states_through(last, build=None, refresh=None):
    """국면(코스피 4상태 × 20일 변동성) — regime_moe_lab.build_states 를 그대로 부른다.

    ⚠️ 그 함수는 **재현용이라 지수 캐시를 먼저 읽고**(prefer_cache=True) 캐시에는 신선도 검사가 없다.
    2026-10-01 에 돌려 보니 캐시가 2026-09-29 에서 끝나 있었다 — 재평가일에 그대로 쓰면 구간 뒤쪽 행이
    '지수 이력 밖'으로 조용히 빠진다. 구간 끝까지 못 닿으면 지수를 새로 받아 캐시를 갈고(kospi_index 한 곳)
    **같은 함수로** 다시 만든다. 그래도 못 닿으면 있는 만큼만 쓰고, 빠진 행 수는 판정 결과에 남는다(§3)."""
    build = build or _rm.build_states
    if refresh is None:
        def refresh():
            import kospi_index as _ki
            return _ki.series(prefer_cache=False)

    def _b():
        try:
            return build() or {}
        except SystemExit:                  # 지수를 못 받으면 랩은 SystemExit 로 멈춘다
            return {}
    st = _b()
    if not st or max(st) < last:
        refresh()
        st = _b()
    return st


def pin_drift():
    """박제 해시(data/freeze_pins.json)와 지금 파일이 다른 것 — 못 대 보면 그 사실을 돌려준다."""
    import model_freeze_guard as _fg
    try:
        with open(_fg.PIN, encoding='utf-8') as f:
            files = (json.load(f) or {}).get('files') or {}
    except Exception as exc:                                   # noqa: BLE001
        return [f'박제 해시를 못 읽었다({type(exc).__name__})']
    if not files:
        return ['박제 해시가 비었다']
    return [rel for rel, h in files.items() if _fg.sha(rel) != h]


def run(today=None, eval_date=None, data=None):
    """판정 한 번. `data` 는 재평가일에만 불리는 자료 공급자(callable → dict)다 —
    관문을 못 넘으면 **부르지 않는다**(회귀가 그것을 심어서 본다)."""
    ok, reason, ed = judge_gate(today, eval_date)
    first, last = record_window()
    res = dict(eval_date=ed, window=[first, last], status='미측정', reason=reason)
    if not ok:
        return res
    drift = pin_drift()
    if drift:
        # 전방 재평가는 "그때 정한 것을 그대로" 재는 일이다 — 정책·사전등록이 바뀌었으면 성립하지 않는다
        res['reason'] = f'박제 파일이 바뀌었다 {drift} — 그때 정한 것을 그대로 잴 수 없어 평가가 성립하지 않는다'
        return res
    d = (data or load_all)(first, last)
    months = months_prorated(first, last)
    res['months'] = months
    # ── 라이브 갈래 ──
    live, drop = grade_registry(in_window(d['registry'], first, last), d['bars'])
    copied = copy_proxies(live, d['ledger'])
    live_pop, live_why = population(live, first, last)
    reg_in = in_window(d['registry'], first, last)
    res['live'] = dict(graded=len(live), dropped=dict(drop), proxies_copied=copied,
                       n=len(live_pop), excluded=dict(live_why),
                       # 박제 대상 해시가 구간 동안 하나였는가 (행마다 찍힌 동결 해시 · 공개용)
                       freeze_hashes=sorted({str(r.get('freeze_hash')) for r in reg_in}),
                       base=(metrics(live_pop, len(live_pop), months) if live_pop else None),
                       by_version={v: metrics(rs, len(rs), months)
                                   for v, rs in by_version(live_pop).items()},
                       r55=r55_judge([dict(r) for r in live_pop], d['states'], d['routing'],
                                     d['vmed'], months))
    # ── 재구성 갈래 (R55·R57 의 판정 갈래) ──
    led_pop, led_why = population(d['ledger'], first, last, keys=d.get('scale_keys'))
    res['recon'] = dict(n=len(led_pop), excluded=dict(led_why),
                        r55=r55_judge([dict(r) for r in led_pop], d['states'], d['routing'],
                                      d['vmed'], months))
    r57_in, r57_why = r57_rows(led_pop, d['paths'], d['anchors'])
    res['recon']['r57'] = dict(r57_judge(r57_in, 'R57 전방', d.get('r57_champion')),
                               dropped=dict(r57_why))
    all_pop, _ = population(d['ledger'], first, last, keys=d.get('scale_keys'), min_score=None)
    r66_in, r66_why = r66_rows(all_pop, d['flags'], d['paths'])
    res['recon']['r66'] = dict(r66_judge(r66_in), dropped=dict(r66_why),
                               flags_made=d.get('flags_made'), flags_why=d.get('flags_why'))
    ub = episodes(reg_in)                 # 전 행을 돌파로 쳐도 넘을 수 없는 수 (결과 아님)
    res['live']['r66'] = dict(status='미측정', episodes_upper=ub, why=(
        [f'전 행을 돌파로 쳐도 에피소드 {ub} — 하한 {R66_EP_MIN} 에 구조적으로 못 닿는다'] if ub < R66_EP_MIN
        else ['전방 기록부(fr-1)에는 돌파 플래그·경로 칸이 없다']))
    res['live']['r57'] = dict(status='미측정',
                              why=['전방 기록부(fr-1)에는 vol20·진입기준선·경로 칸이 없어 기준선(현행눌림)을 못 세운다'])
    res['premise'] = premise_releases(first, last)
    res['status'] = '판정함'
    return res


def load_all(first, last):
    """재평가일에만 부른다 — 네트워크(일봉·지수)를 쓴다."""
    import bitemporal_engine as _be
    import forward_registry as _fr
    with open(PINNED55, encoding='utf-8') as f:
        pin = json.load(f)
    with open(PINNED57, encoding='utf-8') as f:
        champ57 = json.load(f).get('champion')
    reg = in_window(_fr.load(), first, last)
    eng = _be.BitemporalEngine()
    cache = {}                   # 실패도 기억한다 (R303 — 같은 종목을 다시 묻지 않는다)

    def bars_of(tk):
        # build_flags 의 load_bitemporal_data 도 같은 fetch_daily_bars 프레임을 돌려준다
        # (bitemporal_engine.generate_synthetic_bitemporal_data · R330)
        if tk not in cache:
            try:
                cache[tk] = eng.fetch_daily_bars(tk)
            except Exception:                                  # noqa: BLE001
                cache[tk] = None
        return cache[tk]
    bars = {}
    for tk in sorted({str(r['ticker']) for r in reg}):
        df = bars_of(tk)
        if df is not None:
            bars[tk] = df
    states = states_through(last)
    print(f'  국면 날짜 {len(states):,}일 (끝 {max(states) if states else None}) · 구간 끝 {last}')
    ledger = load_ledger_forward(first, last)
    flags = load_keyed('breakout_flags_s*.jsonl', first, last)
    made, fwhy = compute_missing_flags(ledger, flags, bars_of)
    flags_all = dict(made)
    flags_all.update(flags)      # 파일에 있는 것이 먼저다
    print(f'  돌파 플래그 — 파일 {len(flags):,} · 오늘 봉으로 잰 것 {len(made):,} · 못 잰 것 {dict(fwhy)}')
    return dict(registry=reg, bars=bars,
                bars_failed=sorted(t for t, v in cache.items() if v is None),
                ledger=ledger, states=states,
                routing=pin['routing'], vmed=float(pin['vol_median_train']),
                paths=load_keyed('bar_paths_s*.jsonl', first, last),
                anchors=load_keyed('entry_anchors_s*.jsonl', first, last),
                flags=flags_all, flags_made=len(made), flags_why=dict(fwhy),
                r57_champion=champ57, scale_keys=_lv.scale_mismatch_keys())


def _print(res):
    ed, (first, last) = res['eval_date'], res['window']
    print(f"전방 재평가 채점기 — 재평가일 {ed} (박제) · 기록 구간 {first} ~ {last} "
          f"(규칙: {_fe.FORWARD_FROM} 뒤 첫 거래일부터 {RECORD_DAYS}거래일)")
    if res['status'] != '판정함':
        print(f"\n미측정 — {res['reason']}")
        return
    print(f"  월 환산 {res['months']:.2f}개월 (구간 달력일 ÷ {MONTH_DAYS:.2f}) · 비용 {COST}%p (사전등록 측정값)")
    lv = res['live']
    print(f"\n■ 라이브 — 전방 기록부 채점 {lv['graded']:,}행 · 빠짐 {lv['dropped']} · "
          f"모집단 {lv['n']:,} · 제외 {lv['excluded']}")
    print(f"  기준선(매수권 전체 · 합계 — 사전등록의 판정 단위) {_fmt(lv['base'])}")
    print(f"  행에 찍힌 동결 해시 {len(lv['freeze_hashes'])}종 {[h[:8] for h in lv['freeze_hashes']]} "
          f"(1종이어야 박제 대상이 구간 동안 그대로였다)")
    for v, m in lv['by_version'].items():
        print(f"    model {v:16s} {_fmt_short(m)}  (공개용 · 판정에 안 씀)")
    for key in ('r55', 'r57', 'r66'):
        x = lv[key]
        print(f"  {key.upper()} {x['status']} — {' · '.join(x.get('why') or []) or ''}")
    rc = res['recon']
    print(f"\n■ 재구성 — 원장 전방 행 · 모집단 {rc['n']:,} · 제외 {rc['excluded']}")
    x = rc['r55']
    if x.get('base'):
        print(f"  R55 기준선 {_fmt(x['base'])}")
        print(f"  R55 라우팅 {_fmt(x['routing'])}")
        print(f"      칸별 {x.get('cells')} · 라우팅된 칸별 {x.get('routed_by_cell')} · "
              f"국면을 못 붙여 뺀 행 {x.get('index_dropped')}")
    for k, v in (x.get('pre') or {}).items():
        print(f"      [{'충족' if v else '미달'}] {k}")
    for k, v in (x.get('gates') or {}).items():
        print(f"      [{'통과' if v else '미달'}] {k}")
    print(f"  R55 판정: {x['status']} {' · '.join(x.get('why') or [])}")
    if lv.get('base') and x.get('base'):
        # R78 §5 — "두 갈래가 다르면 그 차이가 결과다" (판정 아님 · 사실만)
        print(f"  두 갈래 기준선 차이(라이브 − 재구성): 적중 {lv['base']['hit'] - x['base']['hit']:+.1f}%p · "
              f"순EV {lv['base']['ev'] - x['base']['ev']:+.3f} · n {lv['base']['n']:,} vs {x['base']['n']:,}")
    x = rc['r57']
    for k, v in (x.get('gates') or {}).items():
        print(f"      [{'통과' if v else '미달'}] {k}")
    print(f"  R57 판정: {x['status']} {' · '.join(x.get('why') or [])} · 빠짐 {x.get('dropped')}")
    x = rc['r66']
    for k, v in (x.get('gates') or {}).items():
        print(f"      [{'통과' if v else '미달'}] {k}")
    print(f"  R66 판정: {x['status']} {' · '.join(x.get('why') or [])} · 빠짐 {x.get('dropped')} · "
          f"플래그 오늘 잰 것 {x.get('flags_made')} · 못 잰 것 {x.get('flags_why')}")
    if res.get('premise') is not None:
        print(f"\n■ 전제 점검 — 구간 안 ui·copy 가 아닌 릴리스 {len(res['premise'])}건 "
              f"(R78 §6 은 scoring·rulebook 동결을 전제했다 · 판정은 여전히 합계)")
        for a, v, k in res['premise']:
            print(f"    {a:8s} {v:16s} {k}")


def main(argv=None, today=None):
    res = run(today=today)
    _print(res)
    if res['status'] != '판정함':
        first, last = res['window']
        if first and last:
            feasibility(first, last)
        return 2
    out = os.path.join(P, 'forward_judge_r398.json')
    try:
        os.makedirs(P, exist_ok=True)
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(res, f, ensure_ascii=False, indent=1, default=str)
        print(f'\n저장: {out}')
    except Exception as exc:                                   # noqa: BLE001
        print(f'\n저장 실패 — {type(exc).__name__}: {exc} (판정은 위에 찍힌 그대로다)')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except Exception as _e:                                    # noqa: BLE001
        print(f'오류 — {type(_e).__name__}: {_e}')
        sys.exit(1)
