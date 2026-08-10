# -*- coding: utf-8 -*-
"""
라운드 73 — 하위점수 패치 중복 정리 (같은 종목·날짜가 두 번 쓰인 것).

■ 왜 생겼나
  샤드를 3개씩 나눠 띄웠더니 두 번째 묶음이 (그 사이 채워진 만큼 줄어든)
  다른 todo 목록을 보고 `todo[i::n]` 로 갈랐다. stride 분할은 모든 워커가
  같은 목록을 볼 때만 성립한다. 조각이 겹쳐 3,665건을 두 번 돌았다.
  분할은 안정 해시로 고쳤고, 여기서는 이미 생긴 중복만 치운다.

■ 어떻게 치우나
  같은 (종목,날짜)는 **마지막 것만** 남긴다. 값은 같은 스냅샷에서 나오므로
  어느 쪽을 남겨도 같지만, 마지막이 최신 코드로 계산된 것이다.
  원본은 .bak 로 남긴다 — 지우기 전에 되돌릴 수 있어야 한다.

    C:/Python314/python.exe scripts/dedupe_patch.py [--apply]
"""
import io
import json
import os
import shutil
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(PROJ, '.portfolio')
F = os.path.join(P, 'subscore_patch.jsonl')


def main():
    if not os.path.exists(F):
        print('패치 파일이 없다.')
        return 1
    keep, order = {}, []
    total = bad = 0
    with open(F, encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            total += 1
            try:
                q = json.loads(ln)
            except Exception:                                  # noqa: BLE001
                bad += 1
                continue
            k = (str(q.get('ticker')), str(q.get('date'))[:10])
            if k not in keep:
                order.append(k)
            keep[k] = ln                       # 마지막 것이 남는다

    print(f'{os.path.basename(F)} — 총 {total:,}줄 · 고유 {len(keep):,}건 · '
          f'중복 {total - len(keep) - bad:,} · 깨진 줄 {bad:,}')
    if total == len(keep):
        print('중복 없음 — 손댈 것이 없다.')
        return 0
    if '--apply' not in sys.argv:
        print('실제로 고치려면 --apply 를 붙인다 (원본은 .bak 로 남는다).')
        return 0

    shutil.copyfile(F, F + '.bak')
    with open(F, 'w', encoding='utf-8') as out:
        for k in order:
            out.write(keep[k] + '\n')
    print(f'정리 완료 — {len(keep):,}줄로 다시 썼다. 원본: '
          f'{os.path.basename(F)}.bak')
    return 0


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.exit(main())
