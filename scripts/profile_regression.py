# -*- coding: utf-8 -*-
"""회귀가 어디서 메모리를 먹는지 잰다 — 고치기 전에 먼저 본다 (라운드 163).

■ 무엇이 문제였나
  이 환경에서 회귀가 자주 죽는다. 종료 코드 127/255, 트레이스백 없음,
  죽는 지점이 매번 다름(110 · 640 · 712 · 1,210 · 1,214 · 3,453).
  앞선 진단에서 `dofork: ... exit code 0xC000012D`(STATUS_COMMITMENT_LIMIT)
  를 실제로 봤다 — **커밋 한도 초과**다. 물리 RAM 31.2GB + 페이지파일
  36.5GB = 한도 약 67.7GB 인데, 다른 작업(llama-server 8GB ·
  automatic_worker 12GB · ChatGPT 5GB · streamlit 여럿)이 이미 50GB
  안팎을 잡고 있어 회귀가 크게 부풀면 못 버틴다.

■ 그래서 무엇을 재나
  **회귀 자신의 봉우리**를 절 단위로 잰다. 남의 프로세스는 우리가 못
  줄이지만, 우리 봉우리는 줄일 수 있다. 어느 절에서 튀는지 모르면
  줄일 수도 없다.

  자식 프로세스로 회귀를 띄우고 0.5초마다 private bytes 를 샘플링하며,
  그 순간 마지막으로 출력된 절 제목을 붙여 둔다. 죽어도 그때까지의
  기록이 남는다.

    C:/Python314/python.exe scripts/profile_regression.py [--top 15]
"""
import io
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(PROJ, 'data', 'regression_profile.json')
SAMPLE_SEC = 0.5

_SEC = re.compile(r'^(§?\d+[a-z]?)[\.\s]|^={10,}')


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def _mem_mb(pid):
    """private bytes(MB). psutil 없으면 None — 지어내지 않는다."""
    try:
        import psutil
        return psutil.Process(pid).memory_info().private / (1024 * 1024)
    except Exception:                                          # noqa: BLE001
        return None


def main():
    top_n = 15
    if '--top' in sys.argv:
        try:
            top_n = int(sys.argv[sys.argv.index('--top') + 1])
        except Exception:                                      # noqa: BLE001
            pass
    if _mem_mb(os.getpid()) is None:
        print('psutil 이 없어 메모리를 잴 수 없습니다.')
        print('  C:/Python314/python.exe -m pip install psutil')
        return 2

    print('회귀 메모리 프로파일 — 어느 절에서 봉우리가 생기나')
    print(f'  샘플 {SAMPLE_SEC}s · 대상 test_pipeline_fixes.py\n')
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    p = subprocess.Popen(
        [sys.executable, '-u', 'test_pipeline_fixes.py'],
        cwd=PROJ, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        env=env, text=True, encoding='utf-8', errors='replace', bufsize=1)

    state = {'sec': '(시작)', 'checks': 0, 'peak': 0.0, 'last': 0.0}
    marks = []            # (절, 그 절에서 본 최대 MB)
    lock = threading.Lock()

    def reader():
        for ln in p.stdout:
            s = ln.rstrip()
            with lock:
                if s.startswith('§') or (s and s[0].isdigit()
                                         and '. ' in s[:6]):
                    state['sec'] = s[:60]
                    marks.append([s[:60], state['last'], state['checks']])
                elif s.startswith('  [OK  ]') or s.startswith('  [FAIL]'):
                    state['checks'] += 1
    t = threading.Thread(target=reader, daemon=True)
    t.start()

    series = []
    t0 = time.time()
    while p.poll() is None:
        m = _mem_mb(p.pid)
        if m:
            with lock:
                state['last'] = m
                state['peak'] = max(state['peak'], m)
                series.append((round(time.time() - t0, 1), round(m, 1),
                               state['sec'], state['checks']))
                if marks:
                    marks[-1][1] = max(marks[-1][1], m)
        time.sleep(SAMPLE_SEC)
    t.join(timeout=3)
    rc = p.returncode
    dur = time.time() - t0

    print(f'■ 종료 코드 {rc} · {dur:.0f}s · 검사 {state["checks"]:,}건')
    print(f'■ 봉우리 {state["peak"]:,.0f} MB')
    print()
    print(f'■ 메모리가 가장 크게 오른 절 상위 {top_n}')
    rise = []
    for i, (sec, hi, ck) in enumerate(marks):
        base = marks[i - 1][1] if i else 0.0
        rise.append((hi - base, hi, sec, ck))
    rise.sort(reverse=True)
    for d, hi, sec, ck in rise[:top_n]:
        print(f'   +{d:>7,.0f} MB → {hi:>7,.0f} MB   {sec}')

    import json
    doc = {
        'made_at': datetime.now().isoformat(timespec='seconds'),
        'returncode': rc, 'seconds': round(dur, 1),
        'checks': state['checks'], 'peak_mb': round(state['peak'], 1),
        'sections': [dict(section=s, peak_mb=round(h, 1), checks_at=c)
                     for s, h, c in marks],
        'top_rises': [dict(rise_mb=round(d, 1), peak_mb=round(h, 1),
                           section=s) for d, h, s, _ in rise[:40]],
        'note': ('측정 전용. 남의 프로세스는 못 줄이지만 회귀 자신의 '
                 '봉우리는 줄일 수 있다 — 어디서 튀는지 먼저 본다.'),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f'\n저장: {OUT}')
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
