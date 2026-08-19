# -*- coding: utf-8 -*-
"""git 훅을 저장소의 `.githooks/` 로 연결한다 (라운드 132).

`.git/hooks/` 는 저장소에 안 실린다. 그래서 훅을 커밋해도 새 클론에는
안 붙는다. `core.hooksPath` 를 `.githooks` 로 돌려서, **커밋된 훅이
실제로 도는** 상태로 만든다.

    C:/Python314/python.exe scripts/setup_hooks.py          # 설치
    C:/Python314/python.exe scripts/setup_hooks.py --check  # 상태만 본다

무엇을 자동화하나: `pre-commit` 이 `gen_update_history.py` 를 돌려
업데이트 이력을 커밋에 같이 싣는다. 손으로 돌리는 것을 잊어 회귀 §105 가
다섯 라운드 연속으로 걸렸다.

**검사를 대신하지 않는다.** §105 는 그대로 있고, 훅이 꺼지면 그 검사가
다시 걸린다 — 자동화가 조용히 멈추는 것을 막기 위해서다.
"""
import io
import os
import stat
import subprocess
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS_DIR = '.githooks'
HOOKS = ('pre-commit',)


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def current_path():
    r = subprocess.run(['git', 'config', '--get', 'core.hooksPath'],
                       cwd=PROJ, capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    return r.stdout.strip()


def status():
    """(연결됐나, 훅 파일이 다 있나, 현재 hooksPath)."""
    cur = current_path()
    wired = cur.replace('\\', '/').rstrip('/') == HOOKS_DIR
    have = all(os.path.exists(os.path.join(PROJ, HOOKS_DIR, h))
               for h in HOOKS)
    return wired, have, cur


def main():
    check_only = '--check' in sys.argv
    wired, have, cur = status()

    print('git 훅 상태')
    print(f'   core.hooksPath = {cur or "(설정 안 됨)"}')
    print(f'   {HOOKS_DIR}/ 훅 파일 : '
          + ' · '.join(f'{h} {"있음" if os.path.exists(os.path.join(PROJ, HOOKS_DIR, h)) else "없음"}'
                       for h in HOOKS))
    print(f'   연결됨 : {"예" if wired else "아니오"}')

    if not have:
        print(f'\n{HOOKS_DIR}/ 에 훅 파일이 없다 — 연결해도 아무 일도 '
              '일어나지 않으므로 멈춘다.')
        return 1
    if check_only:
        return 0 if wired else 1
    if wired:
        print('\n이미 연결돼 있다. 바꾸지 않는다.')
        return 0

    # 실행 비트 — Windows 에서는 의미가 없지만, 같은 저장소를 리눅스에서
    # 클론했을 때 필요하다. 여기서 켜 두면 git 이 모드를 기억한다.
    for h in HOOKS:
        p = os.path.join(PROJ, HOOKS_DIR, h)
        try:
            os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR
                     | stat.S_IXGRP | stat.S_IXOTH)
        except Exception:                                      # noqa: BLE001
            pass

    r = subprocess.run(['git', 'config', 'core.hooksPath', HOOKS_DIR],
                       cwd=PROJ, capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    if r.returncode != 0:
        print('\n연결 실패:', (r.stderr or '')[:200])
        return 1
    print(f'\n연결했다 — core.hooksPath = {HOOKS_DIR}')
    print('다음 커밋부터 업데이트 이력이 자동으로 실린다.')
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
