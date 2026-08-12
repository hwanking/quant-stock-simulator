# -*- coding: utf-8 -*-
"""
라운드 73 — 파생 데이터 중복 정리 (같은 종목·날짜가 두 번 쓰인 것).

■ 왜 생기나
  샤드 백필은 (종목,날짜)를 키로 append 한다. 그런데 워커가 **서로 다른
  todo 목록**을 보면 조각이 겹친다. 실제로 두 번 겪었다:
    · 하위점수 — 6샤드를 3개씩 나눠 띄워 stride 분할이 어긋남 (3,665건)
    · 돌파 플래그 — 샤드 없이 전체를 돌리며 기존 샤드분을 다시 씀 (45,678건)
  분할 자체는 안정 해시로 고쳤다. 여기서는 이미 생긴 중복만 치운다.

■ 어떻게
  같은 (종목,날짜)는 **마지막 것만** 남긴다. 값은 같은 스냅샷에서 나오므로
  어느 쪽을 남겨도 같지만, 마지막이 최신 코드로 계산된 것이다.
  원본은 .bak 로 남긴다 — 지우기 전에 되돌릴 수 있어야 한다.

    C:/Python314/python.exe scripts/dedupe_patch.py                  # 전체 미리보기
    C:/Python314/python.exe scripts/dedupe_patch.py --apply
    C:/Python314/python.exe scripts/dedupe_patch.py --only breakout  # 일부만
"""
import glob
import io
import json
import os
import shutil
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(PROJ, '.portfolio')

#: 정리 대상 — (이름, 파일 패턴)
TARGETS = (('섹터·하위점수', 'subscore_patch*.jsonl'),
           ('경로', 'bar_paths_s*.jsonl'),
           ('진입 기준선', 'entry_anchors_s*.jsonl'),
           ('돌파 플래그', 'breakout_flags_s*.jsonl'))


def _utf8_stdout():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def dedupe_group(name, pattern, apply):
    """패턴에 걸리는 파일들을 **묶어서** 본다.

    파일 하나씩 보면 파일 사이 중복을 놓친다 — 샤드가 겹친 경우가 정확히
    그 모양이다.
    """
    paths = sorted(glob.glob(os.path.join(P, pattern)))
    if not paths:
        print(f'{name}: 파일 없음')
        return 0
    seen, total, bad = {}, 0, 0
    per_path = {}
    for path in paths:
        rows = []
        with open(path, encoding='utf-8', errors='replace') as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                total += 1
                try:
                    q = json.loads(ln)
                except Exception:                              # noqa: BLE001
                    bad += 1
                    rows.append((None, ln))
                    continue
                rows.append(((str(q.get('ticker')),
                              str(q.get('date'))[:10]), ln))
        per_path[path] = rows
    # 마지막 등장을 남긴다 — 파일 순서 · 줄 순서대로 훑으며 갱신
    for path in paths:
        for k, ln in per_path[path]:
            if k is not None:
                seen[k] = (path, ln)
    uniq = len(seen)
    dup = total - uniq - bad
    print(f'{name:16s} 파일 {len(paths)} · 총 {total:>8,}줄 · '
          f'고유 {uniq:>8,} · 중복 {dup:>7,} · 깨진 줄 {bad}')
    if dup <= 0 or not apply:
        return dup

    keep_by_path = {p: [] for p in paths}
    for k, (p, ln) in seen.items():
        keep_by_path[p].append(ln)
    for path in paths:
        shutil.copyfile(path, path + '.bak')
        with open(path, 'w', encoding='utf-8') as out:
            for ln in keep_by_path[path]:
                out.write(ln + '\n')
    print(f'  → 정리 완료 (원본은 각 파일 .bak)')
    return dup


def main():
    apply = '--apply' in sys.argv
    only = None
    if '--only' in sys.argv:
        only = sys.argv[sys.argv.index('--only') + 1]

    print('■ 파생 데이터 중복 점검\n')
    total_dup = 0
    for name, pat in TARGETS:
        if only and only not in pat and only not in name:
            continue
        total_dup += dedupe_group(name, pat, apply)
    print(f'\n중복 합계 {total_dup:,}줄')
    if total_dup and not apply:
        print('실제로 고치려면 --apply (원본은 .bak 로 남는다).')
    return 0


if __name__ == '__main__':
    _utf8_stdout()
    sys.exit(main())
