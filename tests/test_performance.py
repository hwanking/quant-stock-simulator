# -*- coding: utf-8 -*-
"""케이스 동결·중복 방지 검증 — 정본은 test_pipeline_fixes.py §74다.

이 파일은 스펙(tests/ 구조) 충족용 얇은 러너로, 전체 스위트를 실행한다:
    python test_pipeline_fixes.py
"""
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)
import noconsole                                               # noqa: E402 · 라운드 485 — 자식 프로세스(git·PowerShell·python)가 콘솔 창을 띄우지 않게
noconsole.install()

if __name__ == '__main__':
    sys.exit(subprocess.call(
        [sys.executable, os.path.join(BASE, 'test_pipeline_fixes.py')]))
