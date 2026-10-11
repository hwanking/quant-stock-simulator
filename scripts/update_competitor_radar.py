# -*- coding: utf-8 -*-
"""
경쟁 서비스 레이더 갱신 도우미 (라운드 456).

    python scripts/update_competitor_radar.py --check      JSON 구조·낱말·도메인·날짜 검사(네트워크 0) · 문제가 있으면 종료 1
    python scripts/update_competitor_radar.py --render     docs/COMPETITOR_RADAR.md 를 JSON 에서 다시 만든다(결정적)
    python scripts/update_competitor_radar.py --diff       git HEAD 의 JSON 과 견줘 상태가 바뀐 항목을 찍고 previous_state·changed 를 맞춘다
    python scripts/update_competitor_radar.py --urls       근거 URL 이 지금도 답하는지(HEAD/GET · 네트워크) — 못 열면 적기만 한다

이 스크립트는 **읽고 적는 일을 대신하지 않는다** — 경쟁사 페이지를 읽고 feature·current_state 를 고치는 것은 사람·조사 작업이고,
여기서는 그 결과가 규칙(공식 도메인 · 상태 낱말 · 날짜 · 점수 없음)을 지키는지와 문서·바뀐 것을 기계적으로 만든다.
경쟁사 변화가 산식·가중치·문턱을 바꾸는 길은 없다(이 모듈은 계산부를 읽지도 쓰지도 않는다).
"""
import argparse
import io
import json
import os
import subprocess
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)
import noconsole                                               # noqa: E402 · 라운드 485 — 자식 프로세스(git·PowerShell·python)가 콘솔 창을 띄우지 않게
noconsole.install()
sys.path.insert(0, PROJ)
import competitor_radar as CR  # noqa: E402


def _print(s):
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode('utf-8', 'replace').decode('ascii', 'replace'))


def cmd_check(doc):
    probs = CR.validate(doc)
    _print(f"항목 {len(doc.get('items') or [])} · 경쟁사 {len(doc.get('competitors') or [])} · 축 {len(doc.get('dimensions') or [])} · "
           f"차이(BUILD·CONSIDER) {len(CR.gaps(doc))} · 바뀜 {len(CR.changed(doc))} · 문제 {len(probs)}")
    for p in probs:
        _print('  문제 ' + p)
    return 1 if probs else 0


def cmd_render(doc, out=CR.DOC):
    text = CR.render_md(doc)
    io.open(out, 'w', encoding='utf-8', newline='\n').write(text)
    _print(f'썼다 {out} · {len(text):,}자')
    return 0


def cmd_diff(doc, path=CR.PATH, write=False):
    try:
        prev_text = subprocess.run(['git', 'show', 'HEAD:' + os.path.relpath(path, PROJ).replace(os.sep, '/')], cwd=PROJ,
                                   capture_output=True, text=True, encoding='utf-8', errors='replace').stdout
        prev = json.loads(prev_text) if prev_text.strip() else None
    except (OSError, ValueError):
        prev = None
    if prev is None:
        _print('HEAD 에 이전 판이 없다 — 첫 판')
        return 0
    before = {(it['competitor'], it['dimension']): it['current_state'] for it in prev.get('items') or []}
    n = 0
    for it in doc.get('items') or []:
        p = before.get((it['competitor'], it['dimension']))
        it['previous_state'] = p
        it['changed'] = (p is not None and p != it['current_state'])
        if it['changed']:
            n += 1
            _print(f"  바뀜 {it['competitor']} · {it['dimension']} — {p} → {it['current_state']}")
    _print(f'바뀐 항목 {n}')
    if write:
        io.open(path, 'w', encoding='utf-8', newline='\n').write(json.dumps(doc, ensure_ascii=False, indent=1) + '\n')
        _print('previous_state·changed 를 적었다')
    return 0


def cmd_urls(doc, timeout=10):
    import urllib.request
    bad = 0
    seen = set()
    for it in doc.get('items') or []:
        u = it['source_url']
        if u in seen:
            continue
        seen.add(u)
        try:
            req = urllib.request.Request(u, method='GET', headers={'User-Agent': 'Mozilla/5.0 (gaeum radar check)'})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                _print(f'  {r.status} {u}')
        except Exception as e:                                 # noqa: BLE001
            bad += 1
            _print(f'  못 열음 {u} — {type(e).__name__}: {str(e)[:80]}')
    _print(f'URL {len(seen)}개 · 못 연 것 {bad}')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--render', action='store_true')
    ap.add_argument('--diff', action='store_true')
    ap.add_argument('--write', action='store_true', help='--diff 결과(previous_state·changed)를 JSON 에 적는다')
    ap.add_argument('--urls', action='store_true')
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    doc = CR.load()
    rc = 0
    if a.diff:
        rc |= cmd_diff(doc, write=a.write)
    if a.check or not (a.render or a.diff or a.urls):
        rc |= cmd_check(doc)
    if a.render:
        rc |= cmd_render(doc)
    if a.urls:
        rc |= cmd_urls(doc)
    return rc


if __name__ == '__main__':
    sys.exit(main())
