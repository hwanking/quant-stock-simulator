# -*- coding: utf-8 -*-
"""회귀 실행기 — 죽으면 왜 죽었는지 말하고, 죽은 것만 다시 돌린다.

■ 왜 (라운드 163)
  이 PC 에서 회귀가 자주 끊겼다. 종료 코드 127/255, 트레이스백 없음,
  죽는 지점이 매번 달랐다. 원인은 코드가 아니라 **커밋 한도 초과**
  (`0xC000012D`)였다 — 다른 작업들이 이미 50GB 안팎을 쓰는데 회귀가
  7GB 봉우리를 만들었다.

  봉우리는 프로파일로 잡아 **7,065 → 1,239 MB** 로 줄였다(무거운 블록을
  자식 프로세스로 격리). 그래도 남의 작업이 더 커지면 언제든 다시
  밀릴 수 있다. 그때 **사람이 로그를 뒤져 원인을 짐작하지 않도록** 이
  실행기가 대신 가른다.

■ 무엇을 가르나
  · **검사 실패**(exit 1 · [FAIL] 줄 있음) — 재시도하지 않는다.
    코드 문제이므로 다시 돌려도 같다.
  · **비정상 종료**(127 · 255 · 음수 · [FAIL] 없이 끊김) — 자원 문제로
    보고 **정해진 횟수만** 다시 돌린다. 왜 그렇게 판단했는지 적는다.

  둘을 섞으면 진짜 결함을 "자원 탓"으로 넘기게 된다 — 그래서 가른다.

    C:/Python314/python.exe scripts/run_regression.py [--retries 2]
"""
import argparse
import io
import os
import re
import subprocess
import sys
import time
from datetime import datetime

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def _headroom_gb():
    """커밋 여유(GB). 못 재면 None — 지어내지 않는다(§3)."""
    try:
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [('dwLength', ctypes.c_ulong),
                        ('dwMemoryLoad', ctypes.c_ulong),
                        ('ullTotalPhys', ctypes.c_ulonglong),
                        ('ullAvailPhys', ctypes.c_ulonglong),
                        ('ullTotalPageFile', ctypes.c_ulonglong),
                        ('ullAvailPageFile', ctypes.c_ulonglong),
                        ('ullTotalVirtual', ctypes.c_ulonglong),
                        ('ullAvailVirtual', ctypes.c_ulonglong),
                        ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]
        m = MS()
        m.dwLength = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return round(m.ullAvailPageFile / (1024 ** 3), 1)
    except Exception:                                          # noqa: BLE001
        return None


def run_once():
    """한 번 돌리고 (종료코드, 통과수, 실패목록, 초) 반환."""
    t0 = time.time()
    p = subprocess.Popen(
        [sys.executable, '-u', 'test_pipeline_fixes.py'], cwd=PROJ,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding='utf-8', errors='replace', bufsize=1,
        env=dict(os.environ, PYTHONIOENCODING='utf-8'))
    ok = 0
    fails = []
    for ln in p.stdout:
        s = ln.rstrip()
        if s.startswith('  [OK  ]'):
            ok += 1
        elif s.startswith('  [FAIL]'):
            fails.append(s[9:].strip())
            print(s)
        elif s.startswith('전체 통과') or s.startswith('실패 '):
            print(s)
    p.wait()
    return p.returncode, ok, fails, time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--retries', type=int, default=2)
    a = ap.parse_args()

    print('회귀 실행기 (라운드 163)')
    hg = _headroom_gb()
    print(f'  커밋 여유 {hg} GB' if hg else '  커밋 여유 미측정')
    print()

    for attempt in range(1, a.retries + 2):
        print(f'■ {attempt}차 시도 — {datetime.now().strftime("%H:%M:%S")}')
        rc, ok, fails, sec = run_once()
        print(f'   종료 {rc} · 통과 {ok:,} · 실패 {len(fails)} · {sec:.0f}s')

        if rc == 0 and not fails:
            print('\n■ 전체 통과')
            return 0
        if fails:
            # 검사가 실제로 걸렸다 — 자원 탓으로 넘기지 않는다
            print(f'\n■ 검사 실패 {len(fails)}건 — 재시도하지 않는다')
            print('   (코드 문제이므로 다시 돌려도 같다)')
            for f in fails[:10]:
                print(f'   · {f}')
            return 1
        # [FAIL] 없이 끊겼다 → 자원 문제로 본다
        hg = _headroom_gb()
        print(f'   [FAIL] 없이 끊겼다 — 자원 문제로 본다 '
              f'(커밋 여유 {hg} GB)')
        if attempt <= a.retries:
            print(f'   {attempt}/{a.retries} 재시도합니다.\n')
        else:
            print('\n■ 재시도를 다 썼는데도 끊긴다.')
            print('   봉우리는 라운드 163 에서 7,065 → 1,239 MB 로 줄였다.')
            print('   그래도 끊긴다면 다른 작업이 커밋을 많이 쓰고 있다 —')
            print('   scripts/profile_regression.py 로 다시 재 보라.')
            return 2
    return 2


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
