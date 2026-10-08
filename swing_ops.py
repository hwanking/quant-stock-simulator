# -*- coding: utf-8 -*-
"""
스윙 워커의 실행 환경을 **읽는다** (라운드 453) — Windows 작업 스케줄러의 작업 상태. 관제실이 "등록하세요"라고만 적지 않고
실제로 등록됐는지 · 다음 실행이 언제인지 · 마지막 결과가 무엇인지를 직접 읽어 보인다(외부 검토 P1-4).

읽기만 한다(등록·해제는 `scripts/register_swing_worker_task.ps1`). PowerShell 의 `Get-ScheduledTask` 를 부르므로 Windows 에서만
값이 있다 — 다른 OS · PowerShell 실패 · 작업 없음은 전부 사유와 함께 돌려준다(§3 · 못 읽은 것을 '없음'이라 적지 않는다).
한 번 읽은 값은 잠깐(TTL) 들고 있는다 — 화면이 rerun 마다 셸을 띄우지 않게.

시험은 `runner` 를 끼워 넣거나 환경변수 `GAEUM_SWING_TASK_JSON` 에 응답을 심는다(자식 프로세스 렌더에서도 셸을 안 띄우게).
"""
import json
import os
import subprocess
import time

TASK_NAME = 'gaeum-swing-worker'
#: Windows 작업 스케줄러의 마지막 결과 코드 — 자주 보는 것만 이름을 붙인다(그 밖은 16진수 그대로). 공식 값(SCHED_S_*).
RESULT_KO = {0: '정상 종료', 0x41301: '실행 중', 0x41303: '아직 돈 적 없음', 0x41306: '사용자가 멈춤',
             0x41325: '실행 대기', 0x800710E0: 'PC 가 꺼져 있어 못 돌았음(절전·종료)'}
_CACHE = {}
_PS = ("$t = Get-ScheduledTask -TaskName '{name}' -ErrorAction SilentlyContinue; if ($t) {{ $i = $t | Get-ScheduledTaskInfo; "
       "[pscustomobject]@{{ State = [string]$t.State; NextRunTime = [string]$i.NextRunTime; LastRunTime = [string]$i.LastRunTime; "
       "LastTaskResult = $i.LastTaskResult; NumberOfMissedRuns = $i.NumberOfMissedRuns }} | ConvertTo-Json -Compress }} else {{ 'ABSENT' }}")


def _run_powershell(name, timeout=15):
    """→ (표준출력 글자, 오류 사유 또는 None)."""
    if os.name != 'nt':
        return None, 'Windows 가 아니다'
    try:
        r = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', _PS.format(name=name)],
                           capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
    except Exception as e:                                     # noqa: BLE001 — PowerShell 없음 · 시간초과
        return None, f'{type(e).__name__}: {str(e)[:80]}'
    if r.returncode != 0:
        return None, f'PowerShell 종료 {r.returncode}: {(r.stderr or "").strip()[:120]}'
    return (r.stdout or '').strip(), None


def parse(text):
    """PowerShell 응답 글자 → dict(installed, state, next_run, last_run, last_result, last_result_ko, missed) · 못 읽으면 None."""
    s = (text or '').strip()
    if s == 'ABSENT':
        return dict(installed=False, state=None, next_run=None, last_run=None, last_result=None, last_result_ko=None, missed=None)
    try:
        d = json.loads(s)
    except (TypeError, ValueError):
        return None
    if not isinstance(d, dict):
        return None
    try:
        code = int(d.get('LastTaskResult')) if d.get('LastTaskResult') is not None else None
    except (TypeError, ValueError):
        code = None
    ko = (RESULT_KO.get(code) if code is not None else None) or (f'결과 코드 0x{code:X}' if code is not None else None)
    last = str(d.get('LastRunTime') or '')
    if last.startswith('11/30/1999') or last.startswith('1999-11-30'):
        last = None                                            # 작업 스케줄러가 '돈 적 없음'을 이 날짜로 적는다
    return dict(installed=True, state=d.get('State'), next_run=(d.get('NextRunTime') or None), last_run=last,
                last_result=code, last_result_ko=ko, missed=d.get('NumberOfMissedRuns'))


def scheduled_task(name=TASK_NAME, runner=None, ttl=60, now=None):
    """작업 스케줄러의 작업 상태 → dict(ok, ...parse 의 칸..., reason). ok=False 면 reason 이 못 읽은 사유다.

    runner(name) → (글자, 오류) 를 끼워 넣을 수 있다(시험). 환경변수 GAEUM_SWING_TASK_JSON 이 있으면 그것을 응답으로 읽는다."""
    stub = os.environ.get('GAEUM_SWING_TASK_JSON')
    if stub is not None:
        d = parse(stub)
        return dict(d, ok=True, reason=None) if d else dict(ok=False, reason='심은 응답을 못 읽었다')
    t = now if now is not None else time.time()
    hit = _CACHE.get(name)
    if runner is None and hit and t - hit[0] < ttl:
        return hit[1]
    text, err = (runner or _run_powershell)(name)
    if err:
        res = dict(ok=False, installed=None, reason=f'작업 상태를 못 읽었다 — {err}')
    else:
        d = parse(text)
        res = dict(d, ok=True, reason=None) if d else dict(ok=False, installed=None, reason='작업 상태 응답을 못 읽었다')
    if runner is None:
        _CACHE[name] = (t, res)
    return res


def task_line(info):
    """화면 한 줄 — 사실만. 못 읽었으면 그 사유. `info` 는 scheduled_task 의 결과."""
    if not info or not info.get('ok'):
        return f"워커 예약 작업({TASK_NAME}) — {(info or {}).get('reason') or '상태를 못 읽었다'}"
    if not info.get('installed'):
        return (f"워커 예약 작업({TASK_NAME}) — 등록돼 있지 않습니다. 평일 아침마다 혼자 돌게 하려면 "
                "scripts/register_swing_worker_task.ps1 을 한 번 돌립니다")
    parts = [f"워커 예약 작업({TASK_NAME}) 등록됨 · 상태 {info.get('state') or '—'}"]
    if info.get('next_run'):
        parts.append(f"다음 실행 {info['next_run']}")
    parts.append(f"마지막 실행 {info['last_run']}" if info.get('last_run') else '마지막 실행 없음')
    if info.get('last_result_ko'):
        parts.append(f"마지막 결과 {info['last_result_ko']}")
    if info.get('missed'):
        parts.append(f"놓친 실행 {info['missed']}회")
    return ' · '.join(parts) + '. PC 가 꺼져 있거나 잠들어 있으면 이 작업도 돌지 않습니다(정규장 동안 절전을 끄세요).'
