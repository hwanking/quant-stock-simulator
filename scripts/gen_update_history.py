# -*- coding: utf-8 -*-
"""
업데이트 히스토리 생성 — git 커밋 이력(실제 개선 기록)을 data/update_history.json 으로.

원칙: 히스토리는 손으로 쓰지 않는다 — 커밋 로그가 유일한 원천이다 (날조 불가).
푸시 전에 실행해 두면 배포 화면의 '업데이트 히스토리' 탭이 최신이 된다.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, 'data', 'update_history.json')


def main():
    r = subprocess.run(
        ['git', 'log', '--pretty=format:%ad\x1f%h\x1f%s',
         '--date=format:%Y-%m-%d', '-n', '400'],
        cwd=BASE, capture_output=True, text=True, encoding='utf-8')
    if r.returncode != 0:
        print('git log 실패:', r.stderr[:200])
        return 1
    days = {}
    for line in r.stdout.splitlines():
        parts = line.split('\x1f')
        if len(parts) != 3:
            continue
        d, h, s = parts
        days.setdefault(d, []).append({'hash': h, 'subject': s})
    out = {'generated_from': 'git log (커밋 이력 원문)',
           'days': [{'date': d, 'items': items}
                    for d, items in sorted(days.items(), reverse=True)]}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    n = sum(len(v['items']) for v in out['days'])
    print(f'OK {len(out["days"])}일 · {n}건 -> {OUT}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
