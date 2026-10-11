# -*- coding: utf-8 -*-
"""Windows 에서 외부 프로그램(git · PowerShell · python 자식)이 **콘솔 창을 띄우지 않게** 하는 한 곳 (라운드 485 · 2026-10-11).

■ 왜
  사용자: *"화면에 창이 떴다가 꺼졌다가 하는데 너 때문이야? 안되게 해줘 · 모든 외부 프로그램 실행을 창 없이."*
  콘솔이 없는 프로세스(배경에서 도는 회귀 · 브라우저 미리보기로 띄운 앱 서버 · 작업 스케줄러가 띄운 작업)가 콘솔 프로그램을
  자식으로 띄우면 Windows 는 자식마다 **새 콘솔 창**을 만든다 — 회귀 한 번이 git·PowerShell·python 자식을 수백 번 띄우므로 창이
  계속 떴다 꺼졌다. 자식에 ``CREATE_NO_WINDOW`` 를 붙이면 콘솔은 있되 창이 없고, 그 자식의 자식은 그 숨은 콘솔을 물려받는다.

■ 어떻게
  ``install()`` 이 ``subprocess.Popen`` 의 기본 ``creationflags`` 에 ``CREATE_NO_WINDOW`` 를 더한다(멱등 · Windows 에서만).
  호출이 콘솔 깃발(새 콘솔 · 분리 · 창 없음)을 스스로 줬으면 건드리지 않는다. 출력·종료 코드·환경은 그대로다 — 창만 없다.
  자식 프로세스를 띄우는 모듈·스크립트는 import 직후 ``noconsole.install()`` 을 부른다(회귀 §466 이 AST 로 빠짐없는지 본다).

  작업 스케줄러가 띄우는 작업은 창 없는 ``pythonw.exe`` 로 띄운다(등록 스크립트). 그 프로세스의 자식은 출력을 파이프로 받아야
  하므로 콘솔 프로그램 ``python.exe`` 로 띄운다 — ``console_python()``.
"""
from __future__ import annotations

import os
import subprocess
import sys

#: Windows `CREATE_NO_WINDOW` — 콘솔은 만들되 창은 안 만든다
CREATE_NO_WINDOW = 0x08000000
#: 호출이 이 중 하나를 줬으면 그 뜻을 따른다(새 콘솔 · 분리 · 창 없음)
_CONSOLE_FLAGS = 0x00000010 | 0x00000008 | CREATE_NO_WINDOW


def flags(creationflags=0):
    """붙일 깃발 — Windows 가 아니면 그대로."""
    cf = int(creationflags or 0)
    if os.name != 'nt' or (cf & _CONSOLE_FLAGS):
        return cf
    return cf | CREATE_NO_WINDOW


def install():
    """``subprocess.Popen`` 기본값에 ``CREATE_NO_WINDOW`` — 처음 부를 때 True · 이미 했거나 Windows 가 아니면 False."""
    if os.name != 'nt' or getattr(subprocess.Popen, '_gaeum_noconsole', False):
        return False
    orig = subprocess.Popen.__init__

    def __init__(self, *args, **kwargs):
        kwargs['creationflags'] = flags(kwargs.get('creationflags', 0))
        orig(self, *args, **kwargs)

    subprocess.Popen.__init__ = __init__
    subprocess.Popen._gaeum_noconsole = True
    return True


def console_python(exe=None):
    """자식으로 띄울 파이썬 — 지금이 ``pythonw.exe`` 면 같은 자리의 ``python.exe``(출력을 파이프로 받는 콘솔 프로그램).

    창은 ``install()`` 이 막는다. 같은 자리에 ``python.exe`` 가 없으면 받은 그대로 돌려준다."""
    exe = exe or sys.executable
    d, b = os.path.split(exe)
    if b.lower() == 'pythonw.exe':
        cand = os.path.join(d, 'python.exe')
        if os.path.exists(cand):
            return cand
    return exe
