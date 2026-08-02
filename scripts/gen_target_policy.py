# -*- coding: utf-8 -*-
"""
'무릎에서 사서 어깨에서 판다' 를 숫자로 만든 산출물.

라운드 9 에서 나온 목표별 도달률이 이 질문의 답이다. 목표를 높이면 먹는 폭은
커지지만 닿을 확률이 떨어진다 — 어디까지가 어깨이고 어디부터가 머리인지를
확률로 그어 준다.

구간 정의 (사전에 정한 기준 — 결과를 보고 고치지 않는다):
  · 무릎  : 도달률 60% 이상  — 자주 닿지만 폭이 얇다
  · 어깨  : 도달률 35~60%    — 폭과 확률이 균형을 이루는 구간
  · 머리  : 도달률 35% 미만  — 가끔 크게 먹지만 대부분 못 닿는다

화면에는 '현재 목표가 어느 구간인지' 를 함께 보여 준다.
"""
from __future__ import annotations

import io
import json
import os
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(BASE, '.portfolio', 'virtual_graded.jsonl')
OUT = os.path.join(BASE, '.portfolio', 'target_policy.json')

BUY_SCORE = 58
STEPS = [2.0, 3.0, 4.0, 5.0, 7.0, 10.0, 15.0]
KNEE_MIN = 60.0
SHOULDER_MIN = 35.0


def zone(rate):
    if rate >= KNEE_MIN:
        return '무릎'
    if rate >= SHOULDER_MIN:
        return '어깨'
    return '머리'


ZONE_NOTE = {
    '무릎': '자주 닿지만 한 번에 먹는 폭이 얇습니다.',
    '어깨': '폭과 확률이 균형을 이루는 구간입니다.',
    '머리': '가끔 크게 먹지만 대부분 못 닿습니다.',
}


def main():
    rows = []
    with open(LEDGER, encoding='utf-8') as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get('mfe_pct') is None or (r.get('score') or 0) < BUY_SCORE:
                continue
            rows.append(r)

    out = {'generated_from': 'virtual_graded.jsonl (매수권 58점+)',
           'knee_min_pct': KNEE_MIN, 'shoulder_min_pct': SHOULDER_MIN,
           'splits': {}}
    for sp, ko in (('train', '학습'), ('valid', '검증'), ('blind', '블라인드')):
        sub = [r for r in rows if r.get('split') == sp]
        if not sub:
            continue
        mfes = [float(r['mfe_pct']) for r in sub]
        steps = []
        for t in STEPS:
            rate = 100.0 * sum(1 for v in mfes if v >= t) / len(mfes)
            steps.append({'target_pct': t, 'reach_rate': round(rate, 1),
                          'zone': zone(rate)})
        out['splits'][sp] = {'n': len(sub), 'steps': steps}
        print(f'[{ko}] n={len(sub):,}')
        for s in steps:
            print(f"  목표 {s['target_pct']:5.1f}% → 도달 {s['reach_rate']:5.1f}% "
                  f"({s['zone']})")
        print()

    # 대표값은 검증 구간 — 학습은 과거, 블라인드는 표본이 얇다
    rep = out['splits'].get('valid') or out['splits'].get('train')
    sh = [s for s in rep['steps'] if s['zone'] == '어깨']
    out['recommended'] = {
        'range_pct': [sh[0]['target_pct'], sh[-1]['target_pct']] if sh else None,
        'sweet_spot_pct': sh[0]['target_pct'] if sh else None,
        'reach_rate': sh[0]['reach_rate'] if sh else None,
        'basis': '검증 구간 매수권 사례의 실제 최고 상승폭 분포',
    }
    out['zone_note'] = ZONE_NOTE
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    if sh:
        print(f"어깨 구간: {sh[0]['target_pct']:.0f}~{sh[-1]['target_pct']:.0f}% "
              f"· 권장 목표 {sh[0]['target_pct']:.0f}% "
              f"(도달률 {sh[0]['reach_rate']:.0f}%)")
    print(f'저장: {OUT}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
