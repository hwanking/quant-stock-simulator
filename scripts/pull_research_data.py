# -*- coding: utf-8 -*-
"""클라우드 스냅샷을 이 PC 로 되받는다 (라운드 93).

■ 왜 필요했나 — 길이 한쪽으로만 나 있었다
  `backup_research_data.py` 는 **올리는** 쪽만 있다. 되받는 로직은
  워크플로 YAML 안에만 살아 있어서, 사람이 쓸 수 있는 길이 없었다.
  그 사이 클라우드는 매일 400건씩 쌓았고 이 PC 는 그대로였다 —
  점검해 보니 로컬 181,959 · 클라우드 183,959 로 2,000건 뒤처져 있었다.

■ 어느 스냅샷을 집는가 (라운드 81 의 사고를 그대로 물려받는다)
  릴리스의 `created_at` 은 **처음 만든 시각**이고 자산을 `--clobber` 로
  덮어써도 안 바뀐다. 실제로 두 릴리스의 created_at 이 초 단위까지 같아
  정렬이 엉뚱한 것을 집었고, 클라우드 원장이 이틀 연속 멈췄다.
  그래서 여기서도 **자산이 실제로 쓰인 시각**(assets[].updated_at)으로
  고른다. 후보 목록을 전부 찍어서 무엇을 왜 골랐는지 보이게 한다.

■ 덮어쓰기 전에 두 가지를 막는다
  ① **줄어들면 멈춘다.** 로컬이 더 최신일 수 있다(로컬에서 축적을
     돌렸다면). 판정은 snapshot_guard 의 패턴·세는 법을 **그대로 쓴다** —
     여기 베껴 두면 한쪽만 고쳐지는 날이 온다.
  ② **개인 자료는 애초에 안 푼다.** 백업이 화이트리스트를 쓰지만,
     내려받는 쪽에서도 backup_research_data.DENY 로 한 번 더 막는다
     (§9). 옛 zip 이나 손댄 zip 이 와도 positions/holdings 는 안 써진다.

■ 기본은 **미리보기**다
    C:/Python314/python.exe scripts/pull_research_data.py
    C:/Python314/python.exe scripts/pull_research_data.py --apply
  줄어드는 것이 정당하면 `--allow-shrink` 를 함께 준다.

■ 이 PC 저녁 작업의 첫 단계다 (라운드 420)
  `scripts/nightly_local.py` 가 평일 17:00 에 `--apply` 로 부른다 — 사람이 며칠에 한 번 손으로 돌리던 사이 이 PC 화면이
  클라우드보다 800~1,600행 뒤에서 말했다(R340·R360·R372·R410). 앱이 떠 있을 수 있는 시각이라 쓰기는 **임시 파일 →
  통째로 바꿔 끼움**이고, 받은 zip 은 최근 `INBOX_KEEP` 개만 둔다. 배포 동봉본(`data/`)을 git 에 싣는 마지막 한 걸음은
  여전히 사람(세션)이다(R261) — 밤 작업은 밖으로 아무것도 안 보낸다.
"""
import fnmatch
import io
import json
import os
import subprocess
import sys
import zipfile

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

P = os.path.join(PROJ, '.portfolio')
#: 두 번째 뿌리 (라운드 261) — 클라우드가 만든 관측 산출물 다섯이 zip 의 `data/` 로 온다.
DATA_DIR = os.path.join(PROJ, 'data')
ARCH = os.path.join(PROJ, '_archive')
#: 받은 zip 을 두는 곳. **backup_research_data 가 만드는 곳과 달라야 한다.**
#: 라운드 97b — 같은 폴더·같은 이름이라 받은 zip 이 방금 만든 백업을
#: 덮어썼고, 그걸 모르고 릴리스에 올려 클라우드 zip 을 클라우드에 도로
#: 올렸다. 크기가 바이트까지 같아서 알아챘다.
INBOX = os.path.join(ARCH, '_incoming')

#: 판정 논리를 베끼지 않는다 — 축소 가드가 쓰는 그 패턴과 그 세는 법을
#: 그대로 부른다 (라운드 92 에서 배운 것: 검사가 논리를 복사하면 코드만
#: 고쳐도 검사는 옛길을 잰다).
from scripts import snapshot_guard as _guard                   # noqa: E402
from scripts import backup_research_data as _backup            # noqa: E402


def _utf8_stdout():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def _gh(args):
    r = subprocess.run(['gh'] + args, cwd=PROJ, capture_output=True,
                       text=True, encoding='utf-8', errors='replace')
    return r.returncode, r.stdout, r.stderr


def repo_slug():
    """owner/name — git 리모트에서 읽는다. 못 읽으면 지어내지 않는다."""
    code, out, _ = _gh(['repo', 'view', '--json', 'nameWithOwner',
                        '--jq', '.nameWithOwner'])
    return out.strip() if code == 0 and out.strip() else None


def candidates(slug):
    """(자산 갱신 시각, 태그, 자산 이름) 목록 — 최신이 마지막."""
    code, out, err = _gh([
        'api', f'repos/{slug}/releases', '--paginate', '--jq',
        '.[] | select(.tag_name|startswith("data-"))'
        ' | .tag_name as $t'
        ' | [.assets[]|select(.name|startswith("research_data_"))]'
        ' | select(length > 0)'
        ' | {tag: $t, at: ([.[].updated_at]|max),'
        '    name: (sort_by(.updated_at)|last|.name)}'])
    if code != 0:
        print('릴리스 목록을 못 읽었다 — 지어내지 않고 멈춘다.')
        print((err or '').strip()[:300])
        return []
    rows = []
    for ln in out.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            rows.append(json.loads(ln))
        except ValueError:
            continue
    rows.sort(key=lambda r: r['at'])
    return rows


def zip_counts(path):
    """zip 안의 줄 수 — 로컬과 **같은 패턴**으로 센다 (guard.WATCH)."""
    out = {pat: dict(lines=0, files=0) for pat in _guard.WATCH}
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            base = os.path.basename(info.filename)
            for pat in _guard.WATCH:
                if fnmatch.fnmatch(base, pat):
                    with z.open(info) as f:
                        n = sum(1 for ln in f if ln.strip())
                    out[pat]['lines'] += n
                    out[pat]['files'] += 1
                    break
    return out


def unsafe_members(path):
    """개인 자료로 보이는 항목 — 있으면 풀지 않는다 (§9)."""
    bad = []
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            base = os.path.basename(info.filename)
            norm = info.filename.replace('\\', '/')
            if norm.startswith('data/'):
                # 라운드 261 — 두 번째 뿌리는 **목록 안의 이름만** 연다. 개인 자료 패턴과
                #   목록 밖 json(`research_radar.json` 같은 git 추적 파일)은 여기서 잘린다.
                #   하위 폴더·`..` 도 안 된다 — 넓히려면 목록(유도)을 넓힌다.
                if (norm.count('/') != 1 or '..' in norm.split('/')
                        or not _backup.picked_data(base)):
                    bad.append((info.filename, 'data/ 목록 밖'))
                continue
            # zip-slip 도 같이 막는다 — .portfolio/ 밖으로 못 나간다
            if not norm.startswith('.portfolio/') or '..' in norm.split('/'):
                bad.append((info.filename, '경로가 .portfolio 밖'))
                continue
            if any(fnmatch.fnmatch(base, d) for d in _backup.DENY):
                bad.append((info.filename, '개인 자료 패턴'))
    return bad


def _ledger_rows_of(text):
    """산출물 본문에서 R259 규약 `ledger_rows` 를 읽는다 — 없으면 None (지어내지 않는다)."""
    try:
        v = json.loads(text).get('ledger_rows')
        return int(v) if v is not None else None
    except Exception:                                          # noqa: BLE001
        return None


def data_newer(zip_text, local_path):
    """zip 의 관측 산출물을 로컬 위에 써도 되나 (라운드 261).

    `data/` 산출물은 줄 수로 비교할 수 없다 — **어느 원장에서 만들었나**(ledger_rows ·
    R259 규약)로 견준다. zip 쪽이 로컬 이상의 원장이면 쓴다. 로컬이 없거나 옛 규약이면
    쓴다. zip 쪽이 옛 규약이면 안 쓴다 — 규약 있는 로컬을 옛것으로 되돌리지 않는다.
    """
    if not os.path.exists(local_path):
        return True
    with open(local_path, encoding='utf-8', errors='replace') as f:
        lr = _ledger_rows_of(f.read())
    if lr is None:
        return True
    zr = _ledger_rows_of(zip_text)
    if zr is None:
        return False
    return zr >= lr


def data_members(path):
    """zip 안의 `data/` 항목 이름 목록 (라운드 261 전의 zip 은 빈 목록)."""
    with zipfile.ZipFile(path) as z:
        return [i.filename for i in z.infolist()
                if not i.is_dir() and i.filename.replace('\\', '/').startswith('data/')]


#: 합집합으로 받는 파일 (라운드 392) — **로컬 앱도 쓰고 클라우드 기록기도 쓰는** 추가 전용 기록.
#: `predictions.jsonl` 은 이 PC 의 앱(web_app·premarket)과 클라우드의 전방 기록기가 둘 다 덧붙인다
#: (forward_recorder 독스트링 · R97). 통째로 덮으면 **이 PC 에만 있던 행이 되받을 때마다 사라진다** —
#: 2026-09-30 되받기에서 4행(09-28·09-29 기준일)이 그렇게 사라질 뻔했고 손으로 열쇠 합집합을 했다
#: (라운드 247 도 같은 파일을 손으로 합쳤다). 축소 가드도 못 막는다 — 받은 쪽이 더 길면 '늘었다'로 본다.
#: 열쇠는 (종목코드 6자리, 기준일)이다 — 오염 점검이 이 파일의 중복을 세는 열쇠와 같다(R390 ·
#: `ledger_view.scale_key` · 시장 접미사만 다른 같은 예측을 두 번 넣지 않는다).
UNION_FILES = frozenset({'predictions.jsonl'})
#: 줄 단위로 합치는 파일 (라운드 415) — 개장 전 리포트 이력은 **이 PC 의 앱만** 쓴다(클라우드는 옛 사본을 들고
#: 다닌다 · 2026-10-02 실측: 이 PC 350줄 · 묶음 256줄 · 이 PC 에만 94줄 · 묶음에만 0). 종전 규칙(수정시각이 새 쪽이
#: 통째로)은 지금은 이 PC 를 남기지만, 어느 쪽이든 고유 줄을 가진 날 진 쪽의 줄이 통째로 사라진다. 열쇠로 묶지 않고
#: **줄 글자 그대로** 합친다 — 한 날짜·한 종목에 버전이 다른 행이 여럿 있을 수 있어(08월 리포트) 열쇠로 묶으면 지운다.
LINE_UNION_FILES = frozenset({'premarket_history.jsonl'})
#: 이 PC 가 원본인 DB (라운드 415) — 추적 케이스는 리포트가 있는 이 PC 에서 동결된다. 받은 DB 가 이 PC 에만 있는
#: 케이스를 갖고 있지 않으면 **덮지 않는다**(덮으면 그 케이스가 사라지고, 다시 동결하면 그날의 도장이 바뀐다).
LOCAL_AUTHORITY_DB = 'improvement.db'
#: 마지막 extract 가 합친 파일의 셈 — main 이 찍는다(조용히 합치지 않는다 · §3).
MERGED = {}


def line_union(incoming, local_lines):
    """받은 줄 + 이 PC 에만 있는 줄(글자 그대로) → (합친 줄, 셈). 순수 함수 · 멱등 (라운드 415)."""
    inc = [ln for ln in (s.strip() for s in incoming) if ln]
    seen = set(inc)
    add = []
    for ln in (s.strip() for s in local_lines):
        if ln and ln not in seen:
            seen.add(ln)
            add.append(ln)
    return inc + add, dict(incoming=len(inc), local_only=len(add), total=len(inc) + len(add))


def db_local_only_cases(local_path, incoming_bytes):
    """이 PC 의 개선 DB 에만 있는 추적 케이스 수 · 못 견주면 None (라운드 415). 아무것도 안 쓴다(임시 파일만)."""
    import sqlite3
    import tempfile
    if not os.path.exists(local_path):
        return 0
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(suffix='.db')
        with os.fdopen(fd, 'wb') as f:
            f.write(incoming_bytes)
        c1, c2 = sqlite3.connect(local_path), sqlite3.connect(tmp)
        try:
            a = {r[0] for r in c1.execute('SELECT case_id FROM prediction_cases')}
            b = {r[0] for r in c2.execute('SELECT case_id FROM prediction_cases')}
        finally:
            c1.close()
            c2.close()
        return len(a - b)
    except Exception:                                          # noqa: BLE001
        return None
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass


def union_merge(incoming, local_lines):
    """받은 줄 + 로컬에만 있는 열쇠의 줄 → (합친 줄, 셈 dict). 순수 함수 (라운드 392).

    받은 것이 먼저다(클라우드가 늘 더 많이 쓴다). 로컬 줄은 **글자 그대로** 붙인다 — 다시 쓰지 않는다.
    못 읽은 로컬 줄은 열쇠를 못 대므로 **버리지 않고** 붙이고 센다(행을 지우지 않는다 · R197 ·
    그 줄은 오염 점검의 `parse_fail` 이 따로 잡는다). 받은 쪽 줄은 손대지 않는다.
    같은 입력을 두 번 넣어도 결과가 같다(멱등 — 합친 결과를 다시 받은 쪽으로 넣어도 늘지 않는다)."""
    import ledger_view as _lv392

    def _key(ln):
        try:
            r = json.loads(ln)
        except Exception:                                      # noqa: BLE001
            return None
        if not isinstance(r, dict):
            return None
        return _lv392.scale_key(r.get('ticker'), r.get('date'))

    inc = [ln for ln in (s.strip() for s in incoming) if ln]
    have = {k for k in (_key(ln) for ln in inc) if k is not None}
    inc_set = set(inc)
    add, dup, only, unparsed = [], 0, 0, 0
    for ln in (s.strip() for s in local_lines):
        if not ln:
            continue
        k = _key(ln)
        if k is None:
            unparsed += 1
            if ln not in inc_set:
                inc_set.add(ln)
                add.append(ln)
            continue
        if k in have:
            dup += 1
            continue
        have.add(k)
        add.append(ln)
        only += 1
    return inc + add, dict(incoming=len(inc), local_only=only, local_dup=dup,
                           local_unparsed=unparsed, total=len(inc) + len(add))


#: 라운드 420 — 되받기가 이 PC 저녁 작업의 첫 단계가 됐다(평일 17:00 · 앱이 떠 있을 수 있는 시각). 종전엔 받은 내용을
#: **제자리에** 덮어써서(240MB 원장을 1MB씩) 그 사이 앱이 읽으면 반쪽 파일을 봤다. 임시 파일에 다 쓴 뒤 통째로 바꿔
#: 끼운다(관심종목 저장과 같은 모양 · 라운드 414). 다른 프로세스가 읽느라 잡고 있으면(Windows) 잠깐 기다려 다시 한다.
_TMP_SUFFIX = '.pulltmp'
#: 끝내 못 바꿔 끼워 제자리 복사로 물러선 파일 — main 이 찍는다(조용히 물러서지 않는다 · §3).
REPLACE_FALLBACK = []


def _replace_retry(tmp, dst, tries=20, wait=0.5):
    """임시 파일을 제자리로 바꿔 끼운다 → 바꿔 끼웠으면 True. 끝내 못 하면 내용을 제자리에 복사하고(종전 동작)
    False — 되받기를 통째로 실패시키지 않는다. 임시 파일은 어느 쪽이든 남기지 않는다.

    2026-10-03 실측: 다른 프로세스가 읽느라 연 파일은 Windows 에서 바꿔 끼우기가 막힌다(PermissionError 5) — 3초 잡게
    심으니 2.5초 기다려 바꿔 끼웠다. 기다림 상한 10초는 원장을 통째로 읽는 시간(약 6초 · 라운드 282)을 덮는 매달림
    방지이지 판정 문턱이 아니다."""
    import shutil
    import time
    try:
        for _ in range(tries):
            try:
                os.replace(tmp, dst)
                return True
            except PermissionError:
                time.sleep(wait)
        shutil.copyfile(tmp, dst)
        REPLACE_FALLBACK.append(os.path.basename(dst))
        return False
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _write_lines_atomic(dst, lines):
    tmp = dst + _TMP_SUFFIX
    with open(tmp, 'w', encoding='utf-8', newline='\n') as out:
        out.write('\n'.join(lines) + ('\n' if lines else ''))
    return _replace_retry(tmp, dst)


def _write_bytes_atomic(dst, body=None, src=None):
    """body(바이트) 또는 src(열린 zip 항목 · 1MB 씩 흘려 쓴다)를 임시 파일에 다 쓴 뒤 바꿔 끼운다."""
    tmp = dst + _TMP_SUFFIX
    with open(tmp, 'wb') as out:
        if body is not None:
            out.write(body)
        else:
            while True:
                chunk = src.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
    return _replace_retry(tmp, dst)


#: 받은 zip 을 몇 개 남기나 (라운드 420) — 판정 문턱이 아니라 집안일이다. 받을 때마다 약 160MB 가 `_incoming` 에
#: 쌓였다(2026-10-03 실측 9개 · 1.3GB) — 밤마다 받으면 한 달에 3GB 남짓이다. 지운 zip 은 릴리스에서 다시 받을 수
#: 있다. 셋은 주말을 넘겨 되돌아볼 여유다.
INBOX_KEEP = 3


def prune_incoming(inbox=None, keep=INBOX_KEEP):
    """받은 zip(`research_data_*.zip`) 중 이름(날짜) 순 최근 keep 개만 남긴다 → (남긴 이름들, 지운 이름들).

    다른 이름의 파일은 안 건드린다. 이름이 날짜를 담으므로 이름 순 = 시간 순이다(수정시각은 내려받은 시각이라
    다시 받으면 옛 스냅샷이 새것처럼 보인다)."""
    inbox = inbox or INBOX
    if not os.path.isdir(inbox) or keep < 1:
        return [], []
    names = sorted(n for n in os.listdir(inbox)
                   if fnmatch.fnmatch(n, 'research_data_*.zip') and os.path.isfile(os.path.join(inbox, n)))
    drop = names[:-keep] if len(names) > keep else []
    gone = []
    for n in drop:
        try:
            os.remove(os.path.join(inbox, n))
            gone.append(n)
        except OSError:
            pass
    return [n for n in names if n not in gone], gone


def pattern_of(base):
    """이 파일이 어느 감시 패턴에 속하나 (없으면 None)."""
    for pat in _guard.WATCH:
        if fnmatch.fnmatch(base, pat):
            return pat
    return None


def extract(path, skip_patterns, portfolio_dir=P, data_dir=DATA_DIR):
    """받은 zip 을 푼다 — **줄어드는 패턴은 건너뛴다** (라운드 93).

    전부-아니면-전무로 두면 쓸 수 없다는 것을 첫 실행에서 알았다.
    실제 상태가 이랬다:

        원장·경로·기준선   로컬 181,959  <  클라우드 183,959
        subscore_patch     로컬 192,341  >  클라우드  60,462

    어느 쪽으로 통째로 덮어도 데이터가 없어진다. 이 축적 파일들은 전부
    '늘기만 한다'는 성질을 갖고 있으므로(그래서 snapshot_guard 가 축소를
    막는다), **패턴별로 큰 쪽을 남기는 것**이 그 성질과 맞는 유일한 처리다.

    감시 패턴 밖의 작은 json(연구 결과·유니버스 등)은 줄 수로 비교할 수
    없다. 이쪽은 **없거나 zip 이 더 새 것일 때만** 쓴다 — 로컬에서만
    만든 산출물을 옛 스냅샷이 되돌리지 않게.

    `data/` 항목(라운드 261)은 `data_newer` — 어느 원장에서 만들었나로 견준다.
    """
    import datetime as _dt
    wrote, kept, skipped = [], [], []
    MERGED.clear()
    REPLACE_FALLBACK.clear()
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            base = os.path.basename(info.filename)
            norm = info.filename.replace('\\', '/')
            if base in UNION_FILES and not norm.startswith('data/'):
                # 라운드 392 — 덮지 않고 합친다. 축소 여부와 무관하다(합집합은 두 쪽 모두보다 작지 않다).
                dst = os.path.join(portfolio_dir, base)
                with z.open(info) as src:
                    incoming = src.read().decode('utf-8', errors='replace').splitlines()
                local = []
                if os.path.exists(dst):
                    with open(dst, encoding='utf-8', errors='replace') as f:
                        local = f.read().splitlines()
                merged, cnt = union_merge(incoming, local)
                _write_lines_atomic(dst, merged)
                MERGED[base] = cnt
                wrote.append(base)
                continue
            if base in LINE_UNION_FILES and not norm.startswith('data/'):
                # 라운드 415 — 줄 글자 그대로 합친다(어느 쪽의 고유 줄도 안 지운다)
                dst = os.path.join(portfolio_dir, base)
                with z.open(info) as src:
                    incoming = src.read().decode('utf-8', errors='replace').splitlines()
                local = []
                if os.path.exists(dst):
                    with open(dst, encoding='utf-8', errors='replace') as f:
                        local = f.read().splitlines()
                merged, cnt = line_union(incoming, local)
                _write_lines_atomic(dst, merged)
                cnt['msg'] = (f"받은 {cnt['incoming']:,} + 이 PC 에만 {cnt['local_only']:,} = {cnt['total']:,} (줄 글자 그대로)")
                MERGED[base] = cnt
                wrote.append(base)
                continue
            if base == LOCAL_AUTHORITY_DB and not norm.startswith('data/'):
                # 라운드 415 — 이 PC 에만 있는 추적 케이스가 있거나 견주지 못하면 덮지 않는다
                dst = os.path.join(portfolio_dir, base)
                n = db_local_only_cases(dst, z.read(info))
                if n is None or n > 0:
                    MERGED[base] = dict(msg=('견주지 못해 이 PC 것을 남긴다' if n is None
                                             else f'이 PC 에만 있는 추적 케이스 {n:,}건 — 덮지 않고 이 PC 것을 남긴다'))
                    kept.append(base)
                    continue
            if norm.startswith('data/'):
                dst = os.path.join(data_dir, base)
                with z.open(info) as src:
                    body = src.read()
                if not data_newer(body.decode('utf-8', errors='replace'), dst):
                    kept.append(base)      # 로컬이 더 큰 원장에서 만든 것 — 안 건드린다
                    continue
                os.makedirs(data_dir, exist_ok=True)
                _write_bytes_atomic(dst, body=body)
                wrote.append(base)
                continue
            pat = pattern_of(base)
            if pat and pat in skip_patterns:
                skipped.append(base)
                continue
            dst = os.path.join(portfolio_dir, base)
            if pat is None and os.path.exists(dst):
                zt = _dt.datetime(*info.date_time).timestamp()
                if os.path.getmtime(dst) > zt:
                    kept.append(base)      # 로컬이 더 새 것 — 안 건드린다
                    continue
            with z.open(info) as src:
                _write_bytes_atomic(dst, src=src)
            wrote.append(base)
    return wrote, kept, skipped


def main():
    apply = '--apply' in sys.argv
    allow_shrink = '--allow-shrink' in sys.argv

    slug = repo_slug()
    if not slug:
        print('저장소를 알 수 없다 (gh 인증/리모트 확인). 멈춘다.')
        return 1
    print(f'저장소 {slug}')

    rows = candidates(slug)
    if not rows:
        print('내려받을 스냅샷이 없다.')
        return 1
    print('\n■ 후보 스냅샷 (자산이 실제로 쓰인 시각 순)')
    for r in rows:
        print(f"  {r['at']}  {r['tag']:16s} {r['name']}")
    pick = rows[-1]
    print(f"\n고른 것: {pick['tag']} — 가장 최근에 쓰인 자산"
          f" ({pick['at']})")
    print('  릴리스 created_at 이 아니라 **자산 updated_at** 으로 고른다 —'
          ' 라운드 81 에서 여기서 이틀을 잃었다.')

    os.makedirs(ARCH, exist_ok=True)
    # ⚠️ 라운드 97b — 여기가 `_archive/research_data_YYYYMMDD.zip` 로 받았다.
    #   그건 **backup_research_data 가 만드는 파일과 같은 이름·같은 폴더**다.
    #   실제로 사고가 났다: 로컬에서 5시간짜리 섹터 정착을 돌리고 백업 zip 을
    #   만든 뒤 pull 을 미리보기로 한 번 돌렸더니, 받은 zip 이 방금 만든
    #   백업을 덮어썼다. 그걸 모르고 릴리스에 올려 **클라우드 zip 을 클라우드에
    #   도로 올렸다**(크기가 바이트까지 같아서 알아챘다).
    #   받는 것과 만드는 것은 이름이 달라야 한다.
    #   `--clobber` 는 **이름을 바꾸기 전에** 이미 덮어쓴다. 그래서 받는
    #   폴더 자체를 갈라야 한다 (INBOX — 모듈 상수로 둬서 검사가 본다).
    os.makedirs(INBOX, exist_ok=True)
    zip_path = os.path.join(INBOX, pick['name'])
    print(f'\n내려받는 중 → {zip_path}')
    code, _, err = _gh(['release', 'download', pick['tag'],
                        '-p', pick['name'], '-D', INBOX, '--clobber'])
    if code != 0 or not os.path.exists(zip_path):
        print('내려받기 실패 — 멈춘다.')
        print((err or '').strip()[:300])
        return 1
    mb = os.path.getsize(zip_path) / 1048576
    print(f'받음 {mb:,.1f}MB')

    bad = unsafe_members(zip_path)
    if bad:
        print(f'\n안전하지 않은 항목 {len(bad)}개 — 풀지 않는다 (§9):')
        for name, why in bad[:8]:
            print(f'  {name}  ({why})')
        return 1

    # 라운드 261 — 관측 산출물(data/)이 동봉됐는지, 그중 로컬보다 새 원장의 것이 몇인지.
    dmem = data_members(zip_path)
    dnew = []
    with zipfile.ZipFile(zip_path) as z:
        for m in dmem:
            with z.open(m) as f:
                txt = f.read().decode('utf-8', errors='replace')
            if data_newer(txt, os.path.join(DATA_DIR, os.path.basename(m))):
                dnew.append(os.path.basename(m))
    if dmem:
        print(f'\n관측 산출물(data/) {len(dmem)}개 동봉 · 이 PC 보다 새 원장의 것 {len(dnew)}개'
              + (': ' + ', '.join(dnew) if dnew else ''))
    else:
        print('\n관측 산출물(data/) 0개 — 라운드 261 전의 zip 이다 (다음 클라우드 실행부터 실린다)')

    before = _guard.counts() if os.path.isdir(P) else {}
    after = zip_counts(zip_path)
    print('\n■ 지금(이 PC) → 받은 스냅샷')
    shrunk, grew = [], 0
    for k in _guard.WATCH:
        b = (before.get(k) or {}).get('lines', 0)
        a = (after.get(k) or {}).get('lines', 0)
        mark = ''
        if k in UNION_FILES:
            mark = '  ← 덮지 않고 (종목 6자리, 날짜)로 합친다'
            grew += int(a != b)
        elif a < b:
            shrunk.append((k, b, a))
            mark = '  ← 줄어든다'
        elif a > b:
            grew += 1
        print(f'  {k:30s} {b:>9,} → {a:>9,} ({a - b:+,}){mark}')
    # 라운드 392 — 합칠 파일은 미리보기에서도 몇 줄이 이 PC 에만 있어 남는지 적는다
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            base = os.path.basename(info.filename)
            if base in UNION_FILES and not info.filename.replace('\\', '/').startswith('data/'):
                dst = os.path.join(P, base)
                local = []
                if os.path.exists(dst):
                    with open(dst, encoding='utf-8', errors='replace') as f:
                        local = f.read().splitlines()
                _m, cnt = union_merge(z.read(info).decode('utf-8', errors='replace').splitlines(), local)
                print(f"  {base}: 받은 {cnt['incoming']:,} + 이 PC 에만 {cnt['local_only']:,} = {cnt['total']:,}"
                      f" (같은 열쇠 {cnt['local_dup']:,} · 못 읽은 로컬 줄 {cnt['local_unparsed']:,})")
            elif base in LINE_UNION_FILES and not info.filename.replace('\\', '/').startswith('data/'):
                # 라운드 415 — 줄 단위 합집합도 미리보기에서 센다
                dst = os.path.join(P, base)
                local = []
                if os.path.exists(dst):
                    with open(dst, encoding='utf-8', errors='replace') as f:
                        local = f.read().splitlines()
                _m, cnt = line_union(z.read(info).decode('utf-8', errors='replace').splitlines(), local)
                print(f"  {base}: 받은 {cnt['incoming']:,} + 이 PC 에만 {cnt['local_only']:,} = {cnt['total']:,} (줄 그대로 합친다)")
            elif base == LOCAL_AUTHORITY_DB and not info.filename.replace('\\', '/').startswith('data/'):
                n = db_local_only_cases(os.path.join(P, base), z.read(info))
                print(f"  {base}: " + ('견주지 못함 — 이 PC 것을 남긴다' if n is None else
                                       (f'이 PC 에만 있는 추적 케이스 {n:,}건 — 이 PC 것을 남긴다' if n else
                                        '이 PC 에만 있는 케이스 0 — 종전 규칙(수정시각)대로')))

    skip = set()
    if shrunk:
        if allow_shrink:
            print(f'\n--allow-shrink — 줄어드는 {len(shrunk)}건도 덮어쓴다.')
        else:
            skip = {k for k, _b, _a in shrunk}
            print(f'\n줄어드는 {len(shrunk)}건은 **건너뛴다** (로컬을 남긴다):')
            for k, b, a in shrunk:
                print(f'  {k} — 로컬 {b:,}줄 vs 받은 것 {a:,}줄')
            print('  이 파일들은 늘기만 하는 성질이라, 큰 쪽이 맞는 쪽이다.')
            print('  일부러 되돌리려면 --allow-shrink 를 준다.')
    if grew == 0 and not shrunk and not dnew:
        print('\n달라지는 것이 없다 — 이미 최신이다.')
        return 0
    if grew == 0 and skip and not dnew:
        print('\n커지는 항목이 없다 — 받을 것이 없다.')
        return 0

    if not apply:
        print('\n(미리보기) --apply 를 주면 실제로 덮어쓴다.')
        return 0

    os.makedirs(P, exist_ok=True)
    wrote, kept, skipped = extract(zip_path, skip)
    print(f'\n덮어씀 {len(wrote)}개 · 로컬 유지 {len(kept) + len(skipped)}개')
    for base, cnt in MERGED.items():
        if cnt.get('msg'):                                     # 라운드 415 — 줄 합집합 · 이 PC 가 원본인 DB
            print(f"  {base}: {cnt['msg']}")
            continue
        print(f"  합침 {base}: 받은 {cnt['incoming']:,} + 이 PC 에만 {cnt['local_only']:,} = {cnt['total']:,}"
              f" (같은 열쇠 {cnt['local_dup']:,} · 못 읽은 로컬 줄 {cnt['local_unparsed']:,})")
    _dw = [b for b in wrote if b in dnew]
    if dmem:
        print(f'  관측 산출물(data/) 덮어씀 {len(_dw)}개 — git 에 올리려면 커밋은 사람이 한다(R261)')
    if skipped:
        print('  축소라 건너뜀: ' + ', '.join(sorted(skipped)[:6])
              + (' …' if len(skipped) > 6 else ''))
    if kept:
        print('  로컬이 더 새 것: ' + ', '.join(sorted(kept)[:6])
              + (' …' if len(kept) > 6 else ''))
    # 라운드 420 — 임시 파일 → 바꿔 끼움. 다른 프로세스가 잡고 있어 끝내 못 바꿔 끼운 것은 제자리 복사로 물러섰다
    print(f'  바꿔 끼움 {len(wrote) - len(REPLACE_FALLBACK)}개'
          + (f' · 제자리 복사로 물러섬 {len(REPLACE_FALLBACK)}개 (다른 프로세스가 읽는 중이었다): '
             + ', '.join(sorted(REPLACE_FALLBACK)[:6]) if REPLACE_FALLBACK else ''))
    _kept420, _gone420 = prune_incoming()
    print(f'  받은 zip 정리 — 남김 {len(_kept420)}개 · 지움 {len(_gone420)}개 (최근 {INBOX_KEEP}개만 둔다 · 릴리스에서 다시 받을 수 있다)')
    now = _guard.counts()
    print('■ 푼 뒤 실제 줄 수')
    for k in _guard.WATCH:
        b = (before.get(k) or {}).get('lines', 0)
        a = (now.get(k) or {}).get('lines', 0)
        print(f'  {k:30s} {b:>9,} → {a:>9,} ({a - b:+,})')
    print('\n※ 이 PC 에만 있는 것(subscore 등)이 클라우드에 없다면 백업이'
          ' 불완전한 것이다 — backup_research_data.py 로 다시 올려야 한다.')
    # 라운드 420 — 저녁 작업 로그는 끝 몇 줄만 남기므로 마지막 줄이 요약이다
    _g420 = 'virtual_graded.jsonl'
    print(f"되받기 끝 · {pick['tag']} · 원장 {(before.get(_g420) or {}).get('lines', 0):,} → "
          f"{(now.get(_g420) or {}).get('lines', 0):,} · 덮어씀 {len(wrote)} · 물러섬 {len(REPLACE_FALLBACK)} · "
          f"zip 지움 {len(_gone420)}")
    return 0


if __name__ == '__main__':
    _utf8_stdout()
    sys.exit(main())
