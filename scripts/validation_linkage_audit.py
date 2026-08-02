# -*- coding: utf-8 -*-
"""
모델 검증이 실제 매수·매도 판단에 쓰이는가 — 코드 전수 감사.

사용자 질문: "모델 검증은 언제 써먹으려고 하는 거야? 우리 매수 매도 판단에
써먹긴 하는 거야? 확률 올리고 있어?"

정당한 질문이다. 검증 결과를 화면에만 띄우고 판단에 안 쓰면 그건 장식이다.
이 스크립트는 **코드에서 실제 연결을 찾아** 10개 항목을 하나씩 확인한다.
찾으면 근거 줄을 함께 출력하고, 못 찾으면 '연결 없음'이라고 적는다.
있다고 우기지 않는다.
"""
from __future__ import annotations

import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FILES = {
    'engine': os.path.join(BASE, 'quant_indicators.py'),
    'app': os.path.join(BASE, 'web_app.py'),
    'promo': os.path.join(BASE, 'improvement', 'promotion.py'),
    'lab': os.path.join(BASE, 'scripts', 'calibration_lab.py'),
}
SRC = {}
for k, p in FILES.items():
    try:
        SRC[k] = open(p, encoding='utf-8').read().split('\n')
    except Exception:
        SRC[k] = []


def hits(where, *patterns, limit=3):
    """패턴이 실제로 있는 줄을 찾아 (행번호, 줄) 로 돌려준다."""
    out = []
    for i, line in enumerate(SRC.get(where) or []):
        s = line.strip()
        if s.startswith('#'):
            continue
        if all(re.search(p, line) for p in patterns):
            out.append((i + 1, s[:110]))
            if len(out) >= limit:
                break
    return out


CHECKS = [
    ('1. 표본외 적중률이 종합점수·신뢰도에 실제 반영되는가',
     lambda: hits('engine', r'calib_band|calibration_band')),
    ('2. 블라인드/표본외 적중률이 낮으면 최종점수 상한이 걸리는가',
     lambda: hits('engine', r"wilson_low.*<|cap_reasons\.append", r'')),
    ('3. 표본외 성과가 나쁜 전략의 가중치가 낮아지는가',
     lambda: hits('engine', r'weight', r'oos|표본외|calib')),
    ('4. 국면별 성능이 낮은 엔진이 그 장세에서 제한되는가',
     lambda: hits('engine', r'regime|국면', r'cap|상한|gate|게이트')),
    ('5. 자산 유형별 검증 결과가 주식·ETF 에 구분 적용되는가',
     lambda: hits('engine', r'asset_type|ETF_LEV|ETF_INV')),
    ('6. 표본 부족 구간이 높은 신뢰도로 표시되지 않는가',
     lambda: hits('engine', r"n.*<.*(15|30|100)|표본 부족|sample_tier")),
    ('7. 최근 성능이 나빠진 모델이 계속 매수 신호를 내지 않게 통제되는가',
     lambda: hits('engine', r'vetoes\.append')),
    ('8. 후보 모델과 운영 모델이 분리돼 있는가',
     lambda: hits('promo', r'candidate|후보') or hits('engine', r'VETO_NET_MODE')),
    ('9. 검증을 통과한 모델만 실제 판단에 쓰이는가',
     lambda: hits('promo', r'def .*promot|승격')),
    ('10. 모델 변경 후 확률이 개선됐는지 버전별로 비교되는가',
     lambda: hits('promo', r'previous|이전 버전|baseline')),
]

print('■ 모델 검증 → 매매 판단 연결 감사\n')
linked = 0
gaps = []
for title, fn in CHECKS:
    h = fn()
    if h:
        linked += 1
        print(f'[연결됨] {title}')
        for ln, s in h[:2]:
            print(f'         {FILES["engine"].split(os.sep)[-1]}:{ln}  {s}')
    else:
        gaps.append(title)
        print(f'[없음  ] {title}')
    print()

print('=' * 74)
print(f'연결 {linked}/10 · 미연결 {len(CHECKS) - linked}')
if gaps:
    print('\n미연결 항목:')
    for g in gaps:
        print('  ·', g)
print('=' * 74)
