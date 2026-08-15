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
            # zip-slip 도 같이 막는다 — .portfolio/ 밖으로 못 나간다
            if not norm.startswith('.portfolio/') or '..' in norm.split('/'):
                bad.append((info.filename, '경로가 .portfolio 밖'))
                continue
            if any(fnmatch.fnmatch(base, d) for d in _backup.DENY):
                bad.append((info.filename, '개인 자료 패턴'))
    return bad


def pattern_of(base):
    """이 파일이 어느 감시 패턴에 속하나 (없으면 None)."""
    for pat in _guard.WATCH:
        if fnmatch.fnmatch(base, pat):
            return pat
    return None


def extract(path, skip_patterns):
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
    """
    import datetime as _dt
    wrote, kept, skipped = [], [], []
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            base = os.path.basename(info.filename)
            pat = pattern_of(base)
            if pat and pat in skip_patterns:
                skipped.append(base)
                continue
            dst = os.path.join(P, base)
            if pat is None and os.path.exists(dst):
                zt = _dt.datetime(*info.date_time).timestamp()
                if os.path.getmtime(dst) > zt:
                    kept.append(base)      # 로컬이 더 새 것 — 안 건드린다
                    continue
            with z.open(info) as src, open(dst, 'wb') as out:
                while True:
                    chunk = src.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
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

    before = _guard.counts() if os.path.isdir(P) else {}
    after = zip_counts(zip_path)
    print('\n■ 지금(이 PC) → 받은 스냅샷')
    shrunk, grew = [], 0
    for k in _guard.WATCH:
        b = (before.get(k) or {}).get('lines', 0)
        a = (after.get(k) or {}).get('lines', 0)
        mark = ''
        if a < b:
            shrunk.append((k, b, a))
            mark = '  ← 줄어든다'
        elif a > b:
            grew += 1
        print(f'  {k:30s} {b:>9,} → {a:>9,} ({a - b:+,}){mark}')

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
    if grew == 0 and not shrunk:
        print('\n달라지는 것이 없다 — 이미 최신이다.')
        return 0
    if grew == 0 and skip:
        print('\n커지는 항목이 없다 — 받을 것이 없다.')
        return 0

    if not apply:
        print('\n(미리보기) --apply 를 주면 실제로 덮어쓴다.')
        return 0

    os.makedirs(P, exist_ok=True)
    wrote, kept, skipped = extract(zip_path, skip)
    print(f'\n덮어씀 {len(wrote)}개 · 로컬 유지 {len(kept) + len(skipped)}개')
    if skipped:
        print('  축소라 건너뜀: ' + ', '.join(sorted(skipped)[:6])
              + (' …' if len(skipped) > 6 else ''))
    if kept:
        print('  로컬이 더 새 것: ' + ', '.join(sorted(kept)[:6])
              + (' …' if len(kept) > 6 else ''))
    now = _guard.counts()
    print('■ 푼 뒤 실제 줄 수')
    for k in _guard.WATCH:
        b = (before.get(k) or {}).get('lines', 0)
        a = (now.get(k) or {}).get('lines', 0)
        print(f'  {k:30s} {b:>9,} → {a:>9,} ({a - b:+,})')
    print('\n※ 이 PC 에만 있는 것(subscore 등)이 클라우드에 없다면 백업이'
          ' 불완전한 것이다 — backup_research_data.py 로 다시 올려야 한다.')
    return 0


if __name__ == '__main__':
    _utf8_stdout()
    sys.exit(main())
