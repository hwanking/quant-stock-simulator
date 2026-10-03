# -*- coding: utf-8 -*-
"""라운드 423 — '하락 국면 + 과매도/볼린저 하단' 조건부 참고 규칙(라운드 8 채택)을 오늘 원장으로 다시 잰다.

■ 왜
  라운드 8 이 원장 7,947건으로 이 규칙을 '조건부 참고'로 채택했고(종목 홀드아웃 164건 70.7% · +12.2%p), 종목 화면의
  카드가 그 수를 **날짜 없이 글자로** 박아 하락 국면에서 RSI 35 미만 · 볼린저 위치 20 미만이면 *"과거엔 반등이 잦던
  자리입니다"* 라고 적었다. 2026-10-03 같은 스크립트(`scripts/regime_rule_r6.py`)를 **한 글자도 안 고치고** 원장
  257,130행에서 돌리니 **채택 없음**이다(홀드아웃 lift −0.3 ~ +0.2%p · 기준 +5.0%p). 표시 전용으로 채택한 것은 근거가
  무너지면 표시에서 거둔다(라운드 395) — 카드는 이 산출물을 읽어 **오늘 수가 뒷받침하는 말만** 한다.

■ 규칙 (새 숫자 없음)
  · 규칙·분할·채택 기준은 `regime_rule_r6` 의 것을 **불러서** 쓴다(RULES · 티커 사전순 3의 배수 홀드아웃 · 홀드아웃
    150건 이상 · 같은 국면 기준선 대비 +5.0%p 이상 · 비용 뺀 평균 > 0 · 블라인드 lift > 0). 베끼지 않는다(라운드 192).
  · 바꾼 것은 이미 정해진 셈 규칙 셋이다 — ① 통계 행(`ledger_view.stat_rows` · 축척 어긋남·접미사 복사본 제외 · R390)
    ② 미결(OPEN) 제외(원장은 미결에도 success=False 를 적는다 · R421) ③ 비용은 운영 상수 `verdict_core.COST_PCT`.
    옛 스크립트 그대로의 판정도 산출물에 같이 싣는다(`replay_unchanged`) — 셈 규칙을 바꿔서 결론이 바뀐 것이 아님을 보인다.
  · `success` 는 20봉 안에 목표에 **먼저** 닿았다는 뜻이다(채점기 `outcome == 'TARGET'`).

■ 산출물 — `.portfolio/bear_oversold.json` 과 `data/bear_oversold.json`(배포 앱이 읽는 사본 · R386). 수만 담는다(종목 0).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timezone

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:                                              # noqa: BLE001
    pass
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (BASE, os.path.join(BASE, 'scripts')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ledger_view as lv           # noqa: E402
import regime_rule_r6 as r6        # noqa: E402

LEDGER = os.path.join(BASE, '.portfolio', 'virtual_graded.jsonl')
FNAME = 'bear_oversold.json'
OUTS = (os.path.join(BASE, '.portfolio', FNAME), os.path.join(BASE, 'data', FNAME))

#: 라운드 8 이 채택할 때의 수 — `docs/MODEL_VERSIONS.md` '라운드 8' 절 표의 RSI 과매도 행 그대로(이 파일 한 곳).
PREVIOUS = {'ledger_rows': 7947, 'hold_n': 164, 'hold_hit': 70.7, 'hold_lift': 12.2,
            'source': 'docs/MODEL_VERSIONS.md 라운드 8'}


def _cost():
    try:
        import verdict_core as _vc
        return float(_vc.COST_PCT)
    except Exception:                                          # noqa: BLE001
        return None


def stats(rows, cost):
    """적중(목표 먼저) · 평균 · 중앙 · 비용 뺀 평균 · 고유 기준일 수. 표본 0 이면 None(§3)."""
    n = len(rows)
    if not n:
        return None
    hit = sum(1 for r in rows if r['success'])
    rets = sorted(float(r['return_pct']) for r in rows)
    mean = sum(rets) / n
    med = rets[n // 2] if n % 2 else (rets[n // 2 - 1] + rets[n // 2]) / 2
    return {'n': n, 'hit': round(100.0 * hit / n, 2), 'wilson': round(r6.wilson_low(hit, n), 2),
            'mean': round(mean, 3), 'median': round(med, 3),
            'net': (round(mean - cost, 3) if cost is not None else None),
            'dates': len({r.get('date') for r in rows})}


def measure(rows, cost):
    """판정 완료 행(미결 제외)에서 약세 국면 기준선과 규칙 셋을 잰다 — 순수 함수(심어서 잴 수 있게)."""
    bear = [r for r in rows if r.get('regime') == 'BEAR']
    tickers = sorted({r['ticker'] for r in bear})
    hold_t = {t for i, t in enumerate(tickers) if i % 3 == 0}
    parts = {'dev': [r for r in bear if r['ticker'] not in hold_t],
             'hold': [r for r in bear if r['ticker'] in hold_t],
             'blind': [r for r in bear if r.get('split') == 'blind']}
    base = {k: stats(v, cost) for k, v in parts.items()}
    rules = {}
    for name, fn in r6.RULES.items():
        s = {k: stats([r for r in v if fn(r)], cost) for k, v in parts.items()}
        lift = {k: (round(s[k]['hit'] - base[k]['hit'], 2) if s[k] and base[k] else None)
                for k in parts}
        h = s['hold']
        hold_ok = bool(h and h['n'] >= r6.MIN_HOLDOUT_N and lift['hold'] is not None
                       and lift['hold'] >= r6.MIN_LIFT and h['net'] is not None and h['net'] > 0)
        blind_ok = bool(lift['blind'] is not None and lift['blind'] > 0)
        rules[name] = {**s, 'lift': lift, 'hold_ok': hold_ok, 'blind_ok': blind_ok,
                       'adopted': hold_ok and blind_ok}
    return {'bear_rows': len(bear), 'tickers': len(tickers), 'holdout_tickers': len(hold_t),
            'baseline': base, 'rules': rules}


def replay_unchanged(raw):
    """옛 스크립트의 셈 그대로(원장 전 행 · 미결을 실패로 · 비용 0.30) 홀드아웃 판정만 — 비교용."""
    rows = [r for r in raw if r.get('success') is not None and r.get('return_pct') is not None]
    bear = [r for r in rows if r.get('regime') == 'BEAR']
    tickers = sorted({r['ticker'] for r in bear})
    hold_t = {t for i, t in enumerate(tickers) if i % 3 == 0}
    hold = [r for r in bear if r['ticker'] in hold_t]
    bh = r6.stats(hold)
    out = {}
    for name, fn in r6.RULES.items():
        h = r6.stats([r for r in hold if fn(r)])
        lift = (h['hit'] - bh['hit']) if (h and bh) else None
        out[name] = {'hold_n': h['n'] if h else 0,
                     'hold_lift': (round(lift, 2) if lift is not None else None),
                     'hold_ok': bool(h and lift is not None and h['n'] >= r6.MIN_HOLDOUT_N
                                     and lift >= r6.MIN_LIFT and h['net'] > 0)}
    return out


def main(argv=None):
    write = '--dry-run' not in (argv or sys.argv[1:])
    cost = _cost()
    keys = lv.scale_mismatch_keys()
    raw, ledger_rows = [], 0
    with open(LEDGER, encoding='utf-8') as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:                                  # noqa: BLE001
                continue
            ledger_rows += 1
            raw.append(r)
    cnt = {}
    stat = list(lv.stat_rows(raw, keys=keys, counter=cnt))
    opened = sum(1 for r in stat if r.get('outcome') == 'OPEN')
    done = [r for r in stat if r.get('outcome') != 'OPEN'
            and r.get('success') is not None and r.get('return_pct') is not None]
    res = measure(done, cost)
    doc = {'made': date.today().isoformat(),
           'made_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
           'ledger_rows': ledger_rows, 'stat_rows': len(stat), 'excluded': cnt, 'open_excluded': opened,
           'graded_rows': len(done), 'cost_pct': cost,
           'criteria': {'min_holdout_n': r6.MIN_HOLDOUT_N, 'min_lift_pp': r6.MIN_LIFT,
                        'net_gt': 0, 'blind_lift_gt': 0},
           'thresholds': {'rsi_lt': 35, 'bb_pos_lt': 20, 'source': 'scripts/regime_rule_r6.py RULES'},
           'previous': PREVIOUS, 'replay_unchanged': replay_unchanged(raw), **res}
    for name, r in res['rules'].items():
        h, b = r['hold'] or {}, r['blind'] or {}
        print(f"{name}: 홀드아웃 {h.get('n')}건 {h.get('hit')}% (lift {r['lift']['hold']:+.2f}%p) · "
              f"블라인드 {b.get('n')}건 lift {r['lift']['blind']:+.2f}%p (날짜 {b.get('dates')}) · "
              f"{'채택 기준 충족' if r['adopted'] else '채택 기준 미달'}")
    print(f"원장 {ledger_rows:,} · 통계 행 {len(stat):,} · 미결 제외 {opened:,} · 판정 완료 {len(done):,} · "
          f"약세 {res['bear_rows']:,} · 비용 {cost}")
    if write:
        for p in OUTS:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            tmp = p + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(doc, f, ensure_ascii=False, indent=1)
            os.replace(tmp, p)
            print('저장', os.path.relpath(p, BASE))
    return 0


if __name__ == '__main__':
    sys.exit(main())
