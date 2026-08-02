# -*- coding: utf-8 -*-
"""
버전별 성능 비교표 — "확률이 실제로 올라가고 있나"에 숫자로 답한다.

사용자 지시: "개선 중이라고만 표시하지 말고 수치로 보여 달라.
적중률만 높아지고 신호가 거의 사라지거나 손실이 커졌다면 개선이 아니다."

개선 판정 조건 (전부 충족해야 '개선'):
  ① 블라인드 적중률 상승
  ② 거래비용 차감 후 기대수익 상승
  ③ 최대낙폭 비악화
  ④ 신호율이 지나치게 낮아지지 않음 (직전의 70% 이상 유지)
  ⑤ 충분한 독립 표본에서 재현 (블라인드 100건+)
하나라도 어기면 '개선'이라고 쓰지 않는다 — '변경' 또는 '악화'로 적는다.

산출물: .portfolio/version_compare.json
"""
from __future__ import annotations

import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
OUT = os.path.join(BASE, '.portfolio', 'version_compare.json')

COST_PCT = 0.30
BUY_SCORE = 58


def measure(rows, split):
    sub = [r for r in rows
           if r.get('split') == split and (r.get('score') or 0) >= BUY_SCORE]
    n_all = sum(1 for r in rows if r.get('split') == split)
    if not sub:
        return None
    hit = sum(1 for r in sub if r.get('success'))
    rets = [float(r['return_pct']) for r in sub
            if r.get('return_pct') is not None]
    maes = [abs(float(r['mae_pct'])) for r in sub
            if r.get('mae_pct') is not None]
    win = [v for v in rets if v > 0]
    loss = [v for v in rets if v <= 0]
    g, p = sum(win), abs(sum(loss))
    return {
        'n': len(sub),
        'hit': round(100.0 * hit / len(sub), 1),
        'net': round((sum(rets) / len(rets) - COST_PCT) if rets else 0.0, 2),
        'mdd': round((sum(maes) / len(maes)) if maes else 0.0, 2),
        'signal_rate': round(100.0 * len(sub) / max(1, n_all), 1),
        'pf': round((g / p) if p > 0 else (99.0 if g else 0.0), 2),
    }


def verdict(prev, cur):
    """개선인지 아닌지. 조건을 하나라도 어기면 '개선'이라고 쓰지 않는다."""
    if not prev or not cur:
        return '비교 불가', ['이전 버전 측정값이 없습니다']
    fails = []
    if cur['hit'] <= prev['hit']:
        fails.append(f"블라인드 적중률 {prev['hit']}% → {cur['hit']}% (상승 아님)")
    if cur['net'] <= prev['net']:
        fails.append(f"비용후 기대수익 {prev['net']}% → {cur['net']}% (상승 아님)")
    if cur['mdd'] > prev['mdd'] + 0.5:
        fails.append(f"평균 최대낙폭 {prev['mdd']}% → {cur['mdd']}% (악화)")
    if cur['signal_rate'] < prev['signal_rate'] * 0.7:
        fails.append(f"신호율 {prev['signal_rate']}% → {cur['signal_rate']}% "
                     "(30% 넘게 줄어듦)")
    if cur['n'] < 100:
        fails.append(f"블라인드 표본 {cur['n']}건 — 100건 미만이라 재현 확인 불가")
    if not fails:
        return '개선', []
    return ('악화' if cur['hit'] < prev['hit'] and cur['net'] < prev['net']
            else '변경'), fails


def main():
    import versioning as V

    led = os.path.join(BASE, '.portfolio', 'virtual_graded.jsonl')
    rows = []
    with open(led, encoding='utf-8') as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get('success') is None:
                continue
            rows.append(r)

    cur = {s: measure(rows, s) for s in ('valid', 'blind')}
    snap = V.snapshot()

    # 이전 버전 기록은 원장에 없다 — 있는 것만 쓰고, 없으면 없다고 적는다.
    hist_path = os.path.join(BASE, 'data', 'version_perf.json')
    try:
        with open(hist_path, encoding='utf-8') as f:
            hist = json.load(f)
    except Exception:
        hist = {'versions': []}

    prev = None
    for v in hist.get('versions', []):
        if v.get('status') == 'operating' and v.get('version') != snap['model']:
            prev = v
    row_cur = {
        'version': snap['model'], 'status': '운영',
        'valid': cur['valid'], 'blind': cur['blind'],
    }
    vd, why = verdict((prev or {}).get('blind'), cur['blind'])
    row_cur['verdict'] = vd
    row_cur['verdict_why'] = why

    # 이번 측정을 이력에 남긴다 (덮어쓰지 않고 append)
    vs = [v for v in hist.get('versions', [])
          if v.get('version') != snap['model']]
    for v in vs:
        if v.get('status') == '운영':
            v['status'] = '보관'
    vs.append(row_cur)
    hist['versions'] = vs
    os.makedirs(os.path.dirname(hist_path), exist_ok=True)
    with open(hist_path, 'w', encoding='utf-8') as f:
        json.dump(hist, f, ensure_ascii=False, indent=1)

    print('■ 버전별 성능 (매수권 58점+ 기준)')
    print('  버전                 상태   연습적중  실전적중  비용후   MDD   신호율   표본')
    for v in hist['versions'][-5:]:
        b, va = v.get('blind') or {}, v.get('valid') or {}
        print(f"  {v['version']:20s} {v['status']:5s} "
              f"{va.get('hit', 0):7.1f}% {b.get('hit', 0):7.1f}% "
              f"{b.get('net', 0):+7.2f}% {b.get('mdd', 0):5.2f}% "
              f"{b.get('signal_rate', 0):6.1f}% {b.get('n', 0):6d}")
    print(f"\n  판정: {vd}")
    for w in why:
        print(f"    · {w}")

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump({'current': row_cur, 'history': hist['versions'][-6:],
                   'criteria': [
                       '블라인드 적중률 상승', '비용 차감 후 기대수익 상승',
                       '최대낙폭 비악화', '신호율 30% 넘게 감소 금지',
                       '블라인드 표본 100건 이상']},
                  f, ensure_ascii=False, indent=1)
    print(f'\n저장: {OUT}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
