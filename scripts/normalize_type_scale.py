# -*- coding: utf-8 -*-
"""
타입 스케일 정규화 — 46개로 흩어진 글자 크기를 10단 스케일로 기계 통일.

스케일 (Apple HIG 계열, px):
    12 캡션2 · 13 각주 · 15 부제 · 16 콜아웃 · 17 본문 ·
    20 제목3 · 22 제목2 · 28 제목1 · 34 대제목 · 40 히어로(결론 한 줄)

규칙: rem→px(×16) 후 최근접 스케일값, 동률이면 위로 올린다.
      단 위계가 뒤집히지 않게 최상단 두 값만 명시 지정한다
      (2.5rem 결론 헤드라인=40, 3rem 점수=34 — 점수가 결론보다 크면 안 된다).
      11px 미만은 접근성 하한(12px)으로 끌어올린다.
"""
from __future__ import annotations

import io
import re
import sys
from collections import Counter

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

SCALE = [12, 13, 15, 16, 17, 20, 22, 28, 34, 40]
EXPLICIT = {2.5: 40, 3.0: 34}          # rem 기준 명시 지정 (위계 보호)
TARGET = 'web_app.py'


def nearest(px: float) -> int:
    best = SCALE[0]
    bd = abs(px - best)
    for s in SCALE:
        d = abs(px - s)
        if d < bd or (d == bd and s > best):    # 동률은 위로
            best, bd = s, d
    return best


def main(apply: bool) -> int:
    src = open(TARGET, encoding='utf-8').read()
    before = Counter(re.findall(r'font-size:\s*([0-9.]+(?:rem|px))', src))
    changes = Counter()

    def repl(m):
        prefix, val, unit = m.group(1), float(m.group(2)), m.group(3)
        px = val * 16 if unit == 'rem' else val
        if unit == 'rem' and val in EXPLICIT:
            new = EXPLICIT[val]
        else:
            new = nearest(px)
        old_txt = f"{m.group(2)}{unit}"
        if old_txt != f"{new}px":
            changes[f"{old_txt} → {new}px"] += 1
        return f"{prefix}{new}px"

    out = re.sub(r'(font-size:\s*)([0-9.]+)(rem|px)', repl, src)
    after = Counter(re.findall(r'font-size:\s*([0-9.]+px)', out))

    print(f"전: 서로 다른 크기 {len(before)}종 / 선언 {sum(before.values())}개")
    print(f"후: 서로 다른 크기 {len(after)}종 / 선언 {sum(after.values())}개")
    print("\n스케일 분포 (후):")
    for k, v in sorted(after.items(), key=lambda x: float(x[0][:-2])):
        print(f"  {k:>7} {v:>4}개")
    print(f"\n변환 {sum(changes.values())}건 · 유형 {len(changes)}가지")
    if apply:
        open(TARGET, 'w', encoding='utf-8').write(out)
        print("\n적용 완료")
    else:
        print("\n(미적용 — --apply 로 실행)")
    return 0


if __name__ == '__main__':
    sys.exit(main('--apply' in sys.argv))
