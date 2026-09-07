# -*- coding: utf-8 -*-
"""회귀 사전 점검 — 전체 회귀(10분 · 실시세)를 돌리기 전에 **초 단위**로 거른다 (라운드 230).

■ 왜
  이 세션에서 전체 회귀가 배경에서 여섯 번 '실패'로 끝났다. 전부 새 절이 **소스 리터럴**을
  잠갔는데 그 리터럴이 두 조각으로 갈렸거나, 옛 절이 이번에 바꾼 낱말을 잠그고 있었기 때문
  이다 — 실시세도 계산도 필요 없는 실패인데 알아내는 데 10분씩 들었다. 사용자: *"백그라운드
  명령어 실패가 계속 나오는데 스마트하게 해줘."*

■ 무엇을 하나
  ① 바뀐 .py(HEAD 대비 + 미추적)를 py_compile 한다.
  ② `test_pipeline_fixes.py` 에서 **자기 완결적인 절**(소스·산출물만 읽는 절)을 떼어 돌린다.
     기본은 최근 N개 절 + 이 저장소가 자주 걸리는 절(§104 §105 §184 §201 §204 §231).
     절 안에서 정의 안 된 이름(앞 절의 변수)을 만나면 '의존'으로 표시하고 넘어간다 —
     통과가 아니라 미측정이다(§6). 전체 회귀가 여전히 최종 판정자다.
  ③ 한 줄 요약과 종료 코드(실패 절 수).

■ 쓰는 법
  C:/Python314/python.exe scripts/preflight.py                # 기본 묶음
  C:/Python314/python.exe scripts/preflight.py --recent 12    # 최근 12개 절
  C:/Python314/python.exe scripts/preflight.py §245 §246      # 지정 절
"""
import argparse
import io
import os
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:                                              # noqa: BLE001
    pass
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST = os.path.join(PROJ, 'test_pipeline_fixes.py')
#: 이 저장소가 자주 걸리는 소스 잠금 절 — 리터럴·머리글·경로를 잠근다
STICKY = ['§104', '§105', '§184', '§201', '§204', '§231']


def _changed_py():
    out = []
    for args in (['git', 'diff', '--name-only', 'HEAD'],
                 ['git', 'ls-files', '--others', '--exclude-standard']):
        try:
            r = subprocess.run(args, cwd=PROJ, capture_output=True, text=True, timeout=20)
            out += [l.strip() for l in r.stdout.splitlines() if l.strip().endswith('.py')]
        except Exception:                                      # noqa: BLE001
            pass
    return sorted(set(out))


def _compile(paths):
    import py_compile
    bad = []
    for p in paths:
        try:
            py_compile.compile(os.path.join(PROJ, p), doraise=True)
        except Exception as e:                                 # noqa: BLE001
            bad.append(f'{p}: {e}')
    return bad


_HEAD_RE = re.compile(r'^print\(f?["\'](§\d+)', flags=re.M)


def _section_markers(src):
    return _HEAD_RE.findall(src)


def _block(src, marker):
    """절 머리(print("§N …") · print(f"§N …") · print('§N …'))부터 다음 절 머리 직전까지."""
    m = re.search(r'^print\(f?["\']%s\b' % re.escape(marker), src, flags=re.M)
    if not m:
        return None
    a = m.start()
    nxt = re.search(r'^print\(f?["\']§\d+', src[a + 10:], flags=re.M)
    summ = src.find('\nprint()\nprint("=" * 72)', a)
    ends = [i for i in ((a + 10 + nxt.start()) if nxt else -1, summ) if i > 0]
    return src[a:min(ends)] if ends else src[a:]


def run_section(src, marker, base_globals):
    """(실행 수, 실패 목록, 의존으로 못 돈 이름 | None)."""
    block = _block(src, marker)
    if block is None:
        return 0, ['절 머리를 못 찾았다'], None, []
    fails, skips, runs = [], [], [0]

    def check(name, cond, detail='', scanned=None):
        runs[0] += 1
        if scanned == 0:
            fails.append('%s [scanned=0]' % name)
        elif not cond:
            fails.append('%s — %s' % (name, str(detail)[:120]))

    def skipped(name, reason):
        skips.append('%s [건너뜀 — %s]' % (name, reason))

    g = dict(base_globals)
    g.update({'check': check, 'skipped': skipped, 'print': lambda *a, **k: None})
    try:
        exec(compile(block, '<%s>' % marker, 'exec'), g)
    except NameError as e:
        return runs[0], fails, str(e), skips
    except Exception as e:                                     # noqa: BLE001
        fails.append('절이 죽었다 — %s: %s' % (type(e).__name__, str(e)[:120]))
    return runs[0], fails, None, skips


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('sections', nargs='*', help='§번호들 (없으면 기본 묶음)')
    ap.add_argument('--recent', type=int, default=9, help='최근 N개 절 (기본 9)')
    a = ap.parse_args(argv)
    os.chdir(PROJ)
    sys.path.insert(0, PROJ)
    src = io.open(TEST, encoding='utf-8').read()
    markers = _section_markers(src)
    if a.sections:
        todo = [m if m.startswith('§') else '§' + m for m in a.sections]
    else:
        todo = STICKY + markers[-a.recent:]
    todo = [m for i, m in enumerate(todo) if m not in todo[:i]]
    changed = _changed_py()
    bad = _compile(changed)
    print(f'① 컴파일 — 바뀐 .py {len(changed)}개 · 실패 {len(bad)}개')
    for b in bad:
        print('   ', b)
    import json as _json
    base = {'_os': os, '_re': re, '_json': _json, 'PROJ': PROJ, 'sys': sys,
            '__file__': TEST}
    try:
        import verdict_core as _vc105
        base['_vc105'] = _vc105
    except Exception:                                          # noqa: BLE001
        pass
    base['_w231'] = io.open(os.path.join(PROJ, 'web_app.py'), encoding='utf-8').read()
    # 앞 절이 정의해 두는 흔한 이름들 — 같은 뜻으로 공급한다 (그만큼 절이 더 돈다).
    #   못 주는 것(실시세 스냅샷 · 앞 절의 계산값)은 '의존'으로 남는다 — 그건 전체 회귀 몫.
    import ast as _ast165

    def _read148(path):
        try:
            with open(path, encoding='utf-8', errors='replace') as f:
                return f.read()
        except Exception:                                      # noqa: BLE001
            return ''
    base.update({'_ast165': _ast165, '_ast16': _ast165, '_read148': _read148, '_w100': base['_w231'],
                 '_uk231': _read148(os.path.join(PROJ, 'ui_kit.py')),
                 '_self235': _read148(TEST)})
    try:
        import ui_kit as _uk201
        base['_uk201'] = _uk201
    except Exception:                                          # noqa: BLE001
        pass
    try:
        import scripts.lineage_audit as _la
        base['_la135'] = _la
        base['_la16'] = _la
    except Exception:                                          # noqa: BLE001
        pass
    print(f'② 절 드라이런 — {len(todo)}개')
    n_fail_sections = 0
    n_skips = 0
    n_dep = 0
    for m in todo:
        runs, fails, dep, skips = run_section(src, m, base)
        n_skips += len(skips)
        _sk = f' · 미측정 {len(skips)}건(실시세 필요)' if skips else ''
        if dep:
            # 앞 절의 이름이 없어 중간에 섰다 — 그 전의 실패도 앞 절 없이 돈 결과라
            # 판정으로 쓰지 않는다(참고로만 찍는다). 이 절은 전체 회귀가 본다.
            n_dep += 1
            print(f'   {m:<6} 의존 (앞 절의 이름: {dep[:50]}) · 실행 {runs}건 — 전체 회귀에서 본다'
                  + (f' · 참고: 앞 절 없이 돈 실패 {len(fails)}건' if fails else ''))
        elif fails:
            n_fail_sections += 1
            print(f'   {m:<6} 실패 {len(fails)}건 / 실행 {runs}건{_sk}')
            for f in fails[:6]:
                print('       FAIL', f)
        else:
            print(f'   {m:<6} 통과 · {runs}건{_sk}')
    total_fail = len(bad) + n_fail_sections
    print(f'③ 요약 — 컴파일 실패 {len(bad)} · 실패한 절 {n_fail_sections} · 의존으로 못 본 절 {n_dep} · '
          f'미측정 {n_skips}건 · '
          + ('전체 회귀로 넘어가도 된다 (미측정은 거기서 본다)' if total_fail == 0
             else '전체 회귀 전에 고친다'))
    return total_fail


if __name__ == '__main__':
    sys.exit(main())
