# -*- coding: utf-8 -*-
"""
지금 이 PC 에서 도는 작업 — 상단 바의 '작업 중' 카드가 읽는다 (라운드 472).

사용자(2026-10-09 · OrbitMusic 의 작업 카드를 붙여): *"작업을 하면 이렇게 나타내면 좋을 것 같애."* 카드는 **도는 작업이 있을 때만**
뜬다. 읽는 것은 둘이고 둘 다 가볍다(화면이 15초마다 다시 읽는다 · 셸·네트워크를 안 부른다):

  · 저녁 작업(`scripts/nightly_local.py`) — 실행 기록의 마지막 '작업 시작 · 단계 N' 줄 뒤에 끝 줄이 없으면 도는 중이다. 단계는
    끝날 때 한 줄씩 적히므로 **끝난 단계 수 / N** 이 진행 막대다(지어낸 퍼센트가 아니다). 지금 단계의 이름은 그 스크립트의 단계
    표(`STEPS`)를 **소스에서 읽는다**(그 모듈을 가져오면 표준출력 설정이 이 프로세스에 번진다). 기록이 그 단계의 시간 상한보다
    오래 안 바뀌었으면 도는 중이라 하지 않는다 — 상한을 넘기면 작업이 스스로 '멈췄다'를 적으므로, 그 줄도 없다면 작업이 끊긴
    것이다(PC 꺼짐 등 · 새 숫자 없음 · 상한은 그 스크립트의 것).
  · 스윙 워커 — 잠금 파일의 주인 프로세스가 살아 있나(`swing_ops.worker_status` · 라운드 454 와 같은 판별). 진행률은 없다(장이
    끝날 때까지 도는 작업이라 막대를 그리면 지어낸 것이다).
  · 분봉 백필(라운드 529) — 수집 잠금의 주인이 살아 있고 백필 기록의 마지막 시작 줄의 pid 와 같으면(`backfill_job`). 막대는 이번
    실행의 받은 쌍 / 받을 쌍(기록의 진행 줄).

못 읽은 것은 '안 돈다'로 바꾸지 않는다 — 그 작업은 목록에서 빠지고(카드에 안 뜬다) 사유는 `notes` 에 남는다(§3).
"""
import ast
import datetime as _dt
import os

PROJ = os.path.dirname(os.path.abspath(__file__))
NIGHTLY_SCRIPT = os.path.join(PROJ, 'scripts', 'nightly_local.py')
#: 시험 훅 — 환경변수 `GAEUM_JOBS_NIGHTLY_LOG` 에 심은 기록을 주면 그것을 읽는다(브라우저로 카드를 볼 때 실제 기록을 안 건드리게 ·
#: `swing_ops` 의 `GAEUM_SWING_TASK_JSON` 과 같은 모양). 없으면 실제 기록.
NIGHTLY_LOG = os.environ.get('GAEUM_JOBS_NIGHTLY_LOG') or os.path.join(PROJ, '.portfolio', 'nightly_local_run.txt')
START_MARK = '장 마감 뒤 작업 시작 · 단계 '
END_MARK = '끝 · 가장 나쁜 종료 코드'


def _num(node):
    """상수·곱셈만 된 식(예: 30 * 60)의 값 · 그 밖은 None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        a, b = _num(node.left), _num(node.right)
        return None if a is None or b is None else a * b
    return None


def nightly_steps(script=None):
    """저녁 작업의 단계 표 → [(이름, 시간 상한 초)] — 소스의 `STEPS = (...)` 를 AST 로 읽는다. 못 읽으면 None."""
    try:
        with open(script or NIGHTLY_SCRIPT, encoding='utf-8') as f:
            tree = ast.parse(f.read())
    except (OSError, SyntaxError, ValueError):
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, 'id', '') == 'STEPS' for t in node.targets):
            out = []
            for el in getattr(node.value, 'elts', []):
                parts = getattr(el, 'elts', [])
                if len(parts) >= 3 and isinstance(parts[0], ast.Constant) and isinstance(parts[0].value, str):
                    out.append((parts[0].value, _num(parts[2])))
            return out or None
    return None


def _is_step_line(ln):
    """'[10-09 17:00:44]   클라우드 되받기 — 종료 0 · …' 처럼 단계 하나가 끝난 줄인가(시각 뒤 두 칸 들여 쓴 줄)."""
    return len(ln) > 18 and ln.startswith('[') and ln[15:17] == '] ' and ln[17:19] == '  ' and ' — ' in ln


def nightly_job(log_path=None, now=None, mtime=None, steps=None, tail=400):
    """도는 중이면 dict(kind, title, sub, done, total, step, since) · 안 돌면 None · 못 읽으면 dict(kind='note', note=사유)
    (카드에는 안 뜨고 사유만 남는다)."""
    path = log_path or NIGHTLY_LOG
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            lines = f.read().splitlines()[-tail:]
        mt = mtime if mtime is not None else os.path.getmtime(path)
    except OSError as e:
        return dict(kind='note', note=f'저녁 작업 기록을 못 읽었다 — {type(e).__name__}')
    start_i = None
    for i, ln in enumerate(lines):
        if START_MARK in ln:
            start_i = i
    if start_i is None:
        return None
    after = lines[start_i + 1:]
    if any(END_MARK in ln for ln in after):
        return None
    try:
        total = int(lines[start_i].split(START_MARK, 1)[1].split()[0])
    except (IndexError, ValueError):
        return dict(kind='note', note='저녁 작업 시작 줄에서 단계 수를 못 읽었다')
    done = sum(1 for ln in after if _is_step_line(ln))
    st = steps if steps is not None else nightly_steps()
    cur = st[done] if (st and done < len(st)) else None
    now_ts = now if now is not None else _dt.datetime.now().timestamp()
    limit = cur[1] if cur else None
    if limit and now_ts - mt > limit:
        return dict(kind='note', note=f'저녁 작업 기록이 {int((now_ts - mt) // 60)}분째 그대로다 — 단계 상한({limit // 60}분)을 넘겼는데 '
                                      f'멈췄다는 줄도 없어 끊긴 것으로 본다(도는 중이라 하지 않는다)')
    since = lines[start_i][1:15]
    name = cur[0] if cur else '다음 단계'
    return dict(kind='nightly', title=f'저녁 작업 — {name}', step=name, done=done, total=total,
                sub=f'{min(done + 1, total)}/{total}단계 · {since[6:11]} 시작 · 끝난 단계 {done}개', since=since)


def worker_job(status=None):
    """스윙 워커가 살아 있으면 dict · 아니면 None(모르면 note)."""
    try:
        if status is None:
            import swing_ops
            status = swing_ops.worker_status()
    except Exception as e:                                     # noqa: BLE001
        return dict(kind='note', note=f'워커 상태를 못 읽었다 — {type(e).__name__}')
    if status.get('running') is None:
        return dict(kind='note', note=status.get('note') or '워커 상태를 모른다')
    if not status.get('running'):
        return None
    since = str(status.get('since') or '')
    return dict(kind='worker', title='스윙 워커 — 장중 주문·보호', done=None, total=None,
                sub='정규장 마감 뒤 한 바퀴 더 돌고 끝' + (f' · {since[11:16]} 부터' if len(since) >= 16 else ''))


#: 라운드 529 — 분봉 백필(라운드 527 · 이 PC 의 작업 gaeum-minute-backfill)도 며칠을 도는데 화면 어디에도 안 보였다(기록 파일에만).
BACKFILL_LOG = os.environ.get('GAEUM_JOBS_BACKFILL_LOG') or os.path.join(PROJ, '.portfolio', 'day_bars', '_backfill_run.txt')
BACKFILL_LOCK = os.path.join(PROJ, '.portfolio', 'day_bars', '_collect.lock')
BACKFILL_START = '] 백필 시작 · pid '
BACKFILL_PLAN = '받을 (종목, 날짜) '


def _pid_alive_default(pid):
    try:
        from scripts.run_swing_worker import _pid_alive      # 워커와 같은 판별(한 곳)
        return _pid_alive(pid)
    except Exception:                                      # noqa: BLE001
        return None


def backfill_job(log_path=None, lock_path=None, alive=None, tail=5000):
    """분봉 백필이 지금 도는가 — 잠금 주인이 살아 있고 그 주인이 기록의 **마지막** '백필 시작' 줄의 pid 이며 그 뒤에 끝·멈춤 줄이 없으면
    dict · 안 돌면 None · 못 읽으면 note. 같은 잠금을 저녁 작업의 분봉 단계도 잡는다 — pid 가 다르면 백필이 아니다(저녁 작업 카드가 보인다).

    진행 막대는 **이번 실행**의 '받은 쌍 / 받을 쌍'(기록의 진행 줄과 계획 줄 · 지어낸 값이 아니다). 진행 줄은 200쌍마다라 막대도 그만큼씩
    움직인다. 한 실행이 밤새 수백 줄을 적으므로(15만 쌍 ÷ 200 = 약 770줄 + 실패 줄) 읽는 꼬리는 넉넉히 — 첫 판은 200줄이라 밤새 돈
    실행의 시작 줄이 꼬리 밖으로 밀려 **도는 중인데 안 뜬다**가 났다(실제 기록으로 처음 그려 보고 잡았다)."""
    lp = lock_path or BACKFILL_LOCK
    if not os.path.exists(lp):
        return None
    try:
        with open(lp, encoding='utf-8') as f:
            owner = int((f.read().strip() or '0'))
        with open(log_path or BACKFILL_LOG, encoding='utf-8', errors='replace') as f:
            lines = f.read().splitlines()[-tail:]
    except (OSError, ValueError) as e:
        return dict(kind='note', note=f'분봉 백필 기록·잠금을 못 읽었다 — {type(e).__name__}')
    start_i = None
    for i, ln in enumerate(lines):
        if BACKFILL_START in ln:
            start_i = i
    if start_i is None:
        return None
    try:
        pid = int(lines[start_i].split(BACKFILL_START, 1)[1].split()[0])
    except (IndexError, ValueError):
        return dict(kind='note', note='분봉 백필 시작 줄에서 pid 를 못 읽었다')
    if not owner or owner != pid:
        return None
    ok = (alive or _pid_alive_default)(pid)
    if ok is None:
        return dict(kind='note', note='분봉 백필 프로세스가 살아 있는지 모른다')
    if not ok:
        return None
    after = lines[start_i + 1:]
    if any(ln.startswith('[끝]') or ln.startswith('[멈춤]') or ln.startswith('[계획만]') for ln in after):
        return None
    total = done = None
    day = ''
    for ln in after:
        if BACKFILL_PLAN in ln:
            try:
                total = int(ln.split(BACKFILL_PLAN, 1)[1].split()[0].replace(',', ''))
            except (IndexError, ValueError):
                total = None
        elif ln.startswith('[') and '] ' in ln and '/' in ln.split('] ', 1)[1].split(' · ')[0]:
            head = ln.split('] ', 1)[1].split(' · ')
            try:
                done = int(head[0].split('/')[0].replace(',', ''))
                day = head[1] if len(head) > 1 else ''
            except (IndexError, ValueError):
                pass
    since = lines[start_i][1:15]
    sub = (f'{done or 0:,}/{total:,}쌍' if total else '계획 세는 중') + (f' · {day} 받는 중' if day else '') + \
          f' · {since[:11]} 시작 · 조회만 · 장 시간·저녁 작업엔 스스로 멈춤'
    return dict(kind='backfill', title='분봉 백필 — 연구용 1년치 받기', done=((done or 0) if total else None), total=total,
                sub=sub, since=since)


def running_jobs(nightly=None, worker=None, backfill=None):
    """(도는 작업 목록, 못 읽은 사유 목록). 저녁 작업을 먼저 — 진행 막대가 있는 쪽이 카드의 머리다. 분봉 백필은 맨 뒤(라운드 529)."""
    jobs, notes = [], []
    for j in ((nightly_job() if nightly is None else nightly), (worker_job() if worker is None else worker),
              (backfill_job() if backfill is None else backfill)):
        if not j:
            continue
        if j.get('kind') == 'note':
            notes.append(j['note'])
        else:
            jobs.append(j)
    return jobs, notes
