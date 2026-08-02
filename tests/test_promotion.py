# -*- coding: utf-8 -*-
"""케이스 동결·중복 방지 검증 — 정본은 test_pipeline_fixes.py §74다.

이 파일은 스펙(tests/ 구조) 충족용 얇은 러너로, 전체 스위트를 실행한다:
    python test_pipeline_fixes.py
"""
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if __name__ == '__main__':
    sys.exit(subprocess.call(
        [sys.executable, os.path.join(BASE, 'test_pipeline_fixes.py')]))
