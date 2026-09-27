# -*- coding: utf-8 -*-
"""
라운드 17c — 원장의 mfe/mae/close 가 서로 모순되지 않는가.

라운드 17b 의 버킷 분해에서 말이 안 되는 값이 나왔다:
  목표(+4.5%)도 손절(-2.96%)도 안 닿은 'OPEN' 사례의 평균 종가수익 +9.80%.
  둘 다 안 닿았으면 가격은 그 사이에 머물렀다는 뜻인데, +9.8% 로 끝날 수 없다.

둘 중 하나다:
  (가) 내 재시뮬 함수가 틀렸다
  (나) 원장의 mfe/mae 와 close_return 이 **서로 다른 창**을 재고 있다

답은 **(나)** 였고 `MODEL_VERSIONS.md` 가 그 사실을 적었다 — mfe/mae 는 **청산 봉까지**,
close_return_pct 는 **20봉 전체**다.

────────────────────────────────────────────────────────────────────────
■ 라운드 368 (2026-09-27) — 이 파일의 불변식 다섯 중 셋이 틀리게 적혀 있었다

라운드 363 이 이 스크립트를 찾았다 — **저장소 전체에서 부르는 곳 0곳**이었고
돌리면 전부 통과 31.4%(68.6% '위반')였다. 그래서 회귀에 배선할 수 없었다.
라운드 368 이 그 68.6% 를 갈랐더니 **틀린 것은 원장이 아니라 이 검사였다**:

  ① *"mfe ≥ 0 이고 mae ≤ 0"* — **애초에 불변식이 아니다.** 이 엔진의 mfe/mae 는
     진입 **다음 봉부터의** 최고·최저를 진입가에 견준 값이라(`path = bars[:upto]`)
     갭상승해 진입가 아래로 안 내려가면 mae > 0 이 **옳다**. 조건부로만 참이다.
  ②③ — **outcome == 'OPEN' 에서만** 불변식이다(그때만 두 창이 같아진다).
  ④⑤ — 진짜 불변식인데 **허용 오차가 틀렸다.** 원장은 `round(..., 2)` 로 담는데
     이 검사는 `1e-6` 으로 견줬다. 걸린 911행 전부 배율 1.000 — 반올림이다.

바르게 적은 다섯을 254,329행에 대면 **위반 0**이다. 판정 규칙은 이제
`ledger_view.consistency_violations` **한 곳**에 있고(§4 · R120e) 이 스크립트와
회귀가 **같은 함수를 부른다** — 여기에 논리를 다시 적으면 두 벌이 된다(R192).

⚠️ 이 다섯은 전부 **행 안**의 정합이다. 라운드 364 의 결함(원장 진입가가 일봉
계열과 축척이 어긋난 16종목)은 행과 **바깥 세계**의 불일치라 못 본다 —
`scripts/entry_scale_audit.py`(R365)가 따로 있어야 하는 까닭이다.

⚠️ 원장을 리스트로 담지 않는다(라운드 282 — 통째로 열면 GB 단위다). 줄 단위로 읽는다.
"""
import io
import json
import os
import sys
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
LED = os.path.join(BASE, '.portfolio', 'virtual_graded.jsonl')

import ledger_view as lv                                        # noqa: E402


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:                                           # noqa: BLE001
        pass

    bad = Counter()
    examples = {}
    n = n_ok = 0
    by_oc = Counter()
    opens = []
    horizon = Counter()
    tb = []

    with io.open(LED, encoding='utf-8', errors='replace') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:                                   # noqa: BLE001
                continue
            n += 1
            by_oc[r.get('outcome')] += 1
            horizon[r.get('horizon_days')] += 1
            if r.get('touched_bar') is not None:
                tb.append(int(r['touched_bar']))
            if r.get('outcome') == 'OPEN' and r.get('close_return_pct') is not None:
                opens.append(float(r['close_return_pct']))

            v = lv.consistency_violations(r)          # ← 규칙은 한 곳에서 (§4)
            if not v:
                n_ok += 1
            for k in v:
                bad[k] += 1
                examples.setdefault(k, r)

    print(f'원장 {n:,}건 · 허용 오차 {lv.CONSISTENCY_TOL:.4f}%p '
          f'(저장 {lv.LEDGER_STORED_DP}자리에서 유도)\n')

    print('■ 불변식 위반 (라운드 368 이 바르게 적은 판)')
    if not bad:
        print('  없음 — 원장은 자체 정합이다')
    for k, v in bad.most_common():
        print(f'  {k:28s} {v:>7,}건 ({v / max(n, 1) * 100:.1f}%)')
    print(f'  전부 통과 {n_ok:,}건 ({n_ok / max(n, 1) * 100:.1f}%)')

    for k, r in examples.items():
        print(f'\n■ 예시 — {k}')
        for fld in ('ticker', 'date', 'price', 'target', 'stop', 'outcome',
                    'mfe_pct', 'mae_pct', 'close_return_pct', 'return_pct',
                    'touched_bar', 'horizon_days'):
            print(f'    {fld:20s} = {r.get(fld)}')

    print('\n■ outcome 분포 — '
          + ' · '.join(f'{k} {v:,}' for k, v in by_oc.most_common()))

    # OPEN 사례만 따로 — 라운드 17b 가 여기서 걸렸다 (그리고 그 값은 옳았다)
    print('\n■ OPEN(현행 기준 미도달) 사례의 종가수익 분포')
    if opens:
        opens.sort()
        print(f'  n={len(opens):,}  최소 {opens[0]:+.1f}%  '
              f'25% {opens[len(opens) // 4]:+.1f}%  중앙 {opens[len(opens) // 2]:+.1f}%  '
              f'75% {opens[len(opens) * 3 // 4]:+.1f}%  최대 {opens[-1]:+.1f}%')
        print(f'  평균 {sum(opens) / len(opens):+.2f}%')

    print('\n■ horizon_days 분포 (mfe/mae/close 가 같은 창을 보는지)')
    print('  ' + ' · '.join(f'{k}일={v:,}' for k, v in horizon.most_common()))
    print('\n■ touched_bar 분포 요약')
    if tb:
        tb.sort()
        print(f'  n={len(tb):,}  중앙 {tb[len(tb) // 2]}봉  최대 {tb[-1]}봉')


if __name__ == '__main__':
    main()
