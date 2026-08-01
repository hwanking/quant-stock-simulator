# -*- coding: utf-8 -*-
"""
판정 기록과 사후 채점 — "이 앱이 계속 잘 맞고 있나"를 자기 기록으로 확인한다.

무엇을 하나:
  1. 종목을 분석할 때마다 그 시점의 판정을 그대로 적어 둔다
     (날짜·현재가·행동·점수·목표가·손절가·기간).
  2. 예측 기간이 지난 기록을 실제 일봉과 대조해 채점한다
     — 목표가 먼저 닿았나(적중), 손절가 먼저 닿았나(실패), 둘 다 아닌가(미결).
  3. 행동 등급별 적중률과 실제 수익률을 집계한다.

왜 이렇게 하나:
  · 백테스트(표본외 검증)는 '과거 규칙이 과거에 맞았나'를 본다. 이 기록은
    **실제로 화면에 내보낸 판정**이 이후 시장에서 어떻게 됐는지를 본다.
    둘은 다른 질문이고, 후자를 안 보면 앱이 조용히 나빠져도 알 수 없다.
  · 채점은 저장된 판정을 절대 고쳐 쓰지 않는다. 사후에 유리하게 다듬는 순간
    성적표는 의미를 잃는다. 기록은 추가만 하고, 채점은 따로 계산한다.

저장 위치: .portfolio/predictions.jsonl (한 줄에 판정 하나, 추가 전용)
클라우드처럼 저장소가 매번 초기화되는 환경에서는 기록이 남지 않는다 —
그 사실을 화면에 그대로 밝힌다.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

PRED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".portfolio")
PRED_FILE = os.path.join(PRED_DIR, "predictions.jsonl")

#: 채점 대상 행동 — build_final_verdict 의 action 코드와 같은 어휘를 쓴다.
#: (관망 HOLD·매수안함 NO_TRADE 는 진입 판정이 아니므로 적중률 계산에서 뺀다)
ENTRY_ACTIONS = ("BUY", "ACCUMULATE")


def _ensure_dir(path):
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)


def record_prediction(entry, path=PRED_FILE):
    """
    판정 한 건을 추가한다. 같은 종목·같은 날짜의 기록이 있으면 덮어쓰지 않고 건너뛴다
    (새로고침할 때마다 같은 판정이 쌓이면 적중률이 왜곡된다).
    반환: True(기록함) / False(이미 있음·저장 불가)
    """
    need = ('ticker', 'date', 'price', 'action', 'score')
    if not all(entry.get(k) is not None for k in need):
        return False
    try:
        _ensure_dir(path)
        key = (str(entry['ticker']), str(entry['date']))
        for row in load_predictions(path):
            if (str(row.get('ticker')), str(row.get('date'))) == key:
                return False
        row = {
            'ticker': str(entry['ticker']),
            'name': str(entry.get('name') or ''),
            'date': str(entry['date']),
            'price': float(entry['price']),
            'action': str(entry['action']),
            'action_label': str(entry.get('action_label') or ''),
            'score': int(entry['score']) if entry.get('score') is not None else None,
            'target': (float(entry['target']) if entry.get('target') is not None else None),
            'stop': (float(entry['stop']) if entry.get('stop') is not None else None),
            'horizon_days': int(entry.get('horizon_days') or 20),
            'recorded_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


def load_predictions(path=PRED_FILE):
    """저장된 판정 목록. 파일이 없으면 빈 목록."""
    if not os.path.exists(path):
        return []
    out = []
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception:
        return []
    return out


def _bars_after(prices_df, start_date, days):
    """기록일 다음 거래일부터 days 거래일까지의 (고가, 저가, 종가) 목록."""
    if prices_df is None or len(prices_df) == 0:
        return []
    df = prices_df
    col_date = 'trade_date' if 'trade_date' in df.columns else df.columns[0]

    def _col(*names):
        for n in names:
            if n in df.columns:
                return n
        return None

    # 데이터 계층은 원시가를 *_raw 로 싣는다. 기록된 판정가·목표가도 화면의 원시가이므로
    # 원시가로 대조해야 한다 (수정주가와 섞으면 액면분할 때 전부 어긋난다).
    c_hi = _col('high_raw', 'high')
    c_lo = _col('low_raw', 'low')
    c_cl = _col('close_raw', 'close', 'adj_close')
    if not (c_hi and c_lo and c_cl):
        return []
    try:
        mask = df[col_date].astype(str) > str(start_date)
        sub = df[mask].head(int(days))
    except Exception:
        return []
    rows = []
    for _i, r in sub.iterrows():
        try:
            rows.append((float(r[c_hi]), float(r[c_lo]), float(r[c_cl])))
        except (TypeError, ValueError):
            continue
    return rows


def grade_prediction(row, prices_df):
    """
    판정 한 건 채점. 반환 dict 또는 None(아직 채점 불가).

    목표가·손절가 중 **먼저 닿은 쪽**으로 판정한다. 같은 봉에서 둘 다 닿으면
    보수적으로 '손절 먼저'로 본다 — 유리한 쪽으로 가정하면 성적이 부풀려진다.
    """
    bars = _bars_after(prices_df, row.get('date'), row.get('horizon_days') or 20)
    if not bars:
        return None
    entry = row.get('price')
    tp, sl = row.get('target'), row.get('stop')
    if not entry:
        return None

    outcome, touched_at = 'OPEN', None
    for i, (hi, lo, _c) in enumerate(bars, start=1):
        hit_sl = sl is not None and lo <= sl
        hit_tp = tp is not None and hi >= tp
        if hit_sl:
            outcome, touched_at = 'STOP', i
            break
        if hit_tp:
            outcome, touched_at = 'TARGET', i
            break

    last_close = bars[-1][2]
    ret_pct = (last_close / entry - 1.0) * 100.0
    if outcome == 'TARGET' and tp:
        real_ret = (tp / entry - 1.0) * 100.0
    elif outcome == 'STOP' and sl:
        real_ret = (sl / entry - 1.0) * 100.0
    else:
        real_ret = ret_pct

    # 경로 기록 — 최고 유리/불리 이동(MFE/MAE). 판정이 결정된 봉까지만 본다
    # (손절 이후의 반등을 성과처럼 집계하면 안 된다).
    upto = touched_at if touched_at else len(bars)
    path = bars[:upto]
    mfe_pct = (max(h for h, _l, _c in path) / entry - 1.0) * 100.0
    mae_pct = (min(l for _h, l, _c in path) / entry - 1.0) * 100.0

    return {
        'outcome': outcome,             # TARGET / STOP / OPEN
        'touched_bar': touched_at,
        'bars_used': len(bars),
        'matured': len(bars) >= (row.get('horizon_days') or 20),
        'return_pct': real_ret,
        'close_return_pct': ret_pct,
        'mfe_pct': mfe_pct,             # 최대 유리 이동 (경로 최고가 기준)
        'mae_pct': mae_pct,             # 최대 불리 이동 (경로 최저가 기준)
    }


def summarize(graded):
    """
    채점 결과 집계. 반환: {'n', 'n_entry', 'hit', 'miss', 'open',
                          'hit_rate', 'avg_return', 'by_action'}
    표본이 적으면 적중률을 숫자로 내밀지 않는다 — 5건 미만은 None.
    """
    rows = [g for g in graded if g and g.get('grade')]
    entry_rows = [g for g in rows if g['row'].get('action') in ENTRY_ACTIONS]
    decided = [g for g in entry_rows if g['grade']['outcome'] in ('TARGET', 'STOP')]
    hit = sum(1 for g in decided if g['grade']['outcome'] == 'TARGET')

    by_action = {}
    for g in rows:
        a = g['row'].get('action_label') or g['row'].get('action')
        b = by_action.setdefault(a, {'n': 0, 'hit': 0, 'decided': 0, 'ret': []})
        b['n'] += 1
        if g['grade']['outcome'] in ('TARGET', 'STOP'):
            b['decided'] += 1
            b['hit'] += (g['grade']['outcome'] == 'TARGET')
        b['ret'].append(g['grade']['return_pct'])
    for b in by_action.values():
        b['avg_return'] = (sum(b['ret']) / len(b['ret'])) if b['ret'] else None
        b['hit_rate'] = (b['hit'] / b['decided'] * 100.0) if b['decided'] >= 5 else None

    return {
        'n': len(rows),
        'n_entry': len(entry_rows),
        'decided': len(decided),
        'hit': hit,
        'miss': len(decided) - hit,
        'open': len(entry_rows) - len(decided),
        'hit_rate': (hit / len(decided) * 100.0) if len(decided) >= 5 else None,
        'avg_return': (sum(g['grade']['return_pct'] for g in entry_rows) / len(entry_rows))
                      if entry_rows else None,
        'by_action': by_action,
        'min_sample_note': ("판정이 끝난 진입 기록이 5건 미만이라 적중률을 내지 않습니다 "
                            "— 적은 표본의 비율은 숫자만 그럴듯합니다.")
        if len(decided) < 5 else "",
    }


def evaluate_all(engine, path=PRED_FILE, max_rows=200):
    """
    저장된 판정을 실제 일봉과 대조해 채점한다.
    반환: (graded_rows, summary) — graded_rows 는 [{'row','grade'}, …]
    """
    rows = load_predictions(path)[-int(max_rows):]
    graded, cache = [], {}
    for row in rows:
        tk = row.get('ticker')
        if not tk:
            continue
        if tk not in cache:
            try:
                pdf, _fdf = engine.generate_synthetic_bitemporal_data(
                    symbol=tk, start_date='2020-01-01',
                    end_date=datetime.now().strftime('%Y-%m-%d'))
                cache[tk] = pdf
            except Exception:
                cache[tk] = None
        g = grade_prediction(row, cache.get(tk))
        graded.append({'row': row, 'grade': g})
    return graded, summarize(graded)


def next_check_date(row):
    """이 판정의 채점 예정일 (기록일 + 예측기간, 거래일 근사)."""
    try:
        d = datetime.strptime(str(row.get('date'))[:10], '%Y-%m-%d')
    except Exception:
        return None
    days = int(row.get('horizon_days') or 20)
    return (d + timedelta(days=int(days * 1.45))).strftime('%Y-%m-%d')
