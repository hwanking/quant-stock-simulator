# -*- coding: utf-8 -*-
"""화면이 조용히 삼키는 예외를 센다 — 손으로 돌리는 조사 도구 (라운드 441 · 읽기만 · 쓰기 금지 앱 테스트).

■ 왜
  `except …: pass` 와 `except …: 값 = None` 은 그 칸이 **조용히 빠져도** 회귀가 초록인 자리다. 라운드 402(캐시
  경합 → 첫 화면 '미산출') · 424(계층 실측 표가 64/64 종목에서 한 번도 안 그려짐) · 441(매매 지시서의 '시장 진단'이
  엔진 객체의 없는 속성을 읽어 2026-08-08 부터 한 번도 안 나감)이 전부 거기서 나왔다. 코드를 읽어서는 안 보인다 —
  **실제로 어느 핸들러가 걸리는지**는 심어서 한 번 돌려야 안다.

■ 무엇을
  ① 화면 도달 모듈 전부(`lineage_audit.reachable_modules`)에서 except 핸들러와 그중 몸통이 `pass` 뿐인 것을 AST 로 센다.
  ② web_app.py 사본을 만들어 핸들러마다 (원본 줄 · 예외 종류 · 메시지) 를 builtins 의 목록에 적게 바꾸고
     (`--all` 이면 전부 · 아니면 pass 뿐인 것만), 쓰기를 막은 앱 테스트(`GAEUM_NO_LOCAL_WRITE=1`)로 한 번 렌더해
     **실제로 걸린 자리**를 원본 줄 번호와 앞 몇 줄과 함께 찍는다. 줄 번호는 원본 AST 의 lineno 를 상수로 심는다
     (unparse 가 줄을 바꾼다). `__file__` 은 원본 경로 상수로 바꾼다(web_app 이 여덟 곳에서 쓴다).

■ 범위 — 한 종목 · 한 렌더 · 그날의 자료다. 걸린 0 은 "없다"가 아니라 "이 렌더에서 안 걸렸다"(라운드 274·295 의
  규칙). 걸린 자리는 **후보**다 — 설계대로 받는 것(None 을 '—' 로 · 비밀번호 파일 없음)과 결함을 사람이 가른다.
  회귀에 넣지 않는다 — 실제 렌더(2~3분)와 실시세가 필요하다(§6 의 그 자리).

    C:/Python314/python.exe scripts/swallow_census.py          # pass 뿐인 핸들러만
    C:/Python314/python.exe scripts/swallow_census.py --all    # 핸들러 전부 (몸통 유지 · 기록만 앞에)
"""
import ast
import builtins
import os
import re
import sys

os.environ['GAEUM_NO_LOCAL_WRITE'] = '1'
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:                                              # noqa: BLE001
    pass
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJ)
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)
from scripts import lineage_audit as _la  # noqa: E402

WEB = os.path.join(PROJ, 'web_app.py')
ALL = '--all' in sys.argv


def _is_pass_only(handler):
    return len(handler.body) == 1 and isinstance(handler.body[0], ast.Pass)


def static_census():
    """(pass 뿐, 전체, 파일) 목록 — 화면 도달 모듈 전부."""
    rows = []
    for m in sorted(_la.reachable_modules()):
        path = m if os.path.isabs(m) else os.path.join(PROJ, m)
        if not path.endswith('.py'):
            path += '.py'
        if not os.path.exists(path):
            continue
        try:
            tree = ast.parse(open(path, encoding='utf-8').read())
        except Exception as e:                                 # noqa: BLE001
            print('파싱 실패', m, e)
            continue
        n_all = n_pass = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                n_all += 1
                n_pass += _is_pass_only(node)
        if n_all:
            rows.append((n_pass, n_all, os.path.relpath(path, PROJ)))
    rows.sort(reverse=True)
    return rows


class _Instr(ast.NodeTransformer):
    def __init__(self):
        self.n = 0

    def visit_Name(self, node):
        if node.id == '__file__':
            return ast.copy_location(ast.Constant(WEB), node)
        return node

    def visit_ExceptHandler(self, node):
        self.generic_visit(node)
        if not ALL and not _is_pass_only(node):
            return node
        self.n += 1
        if node.type is None:
            node.type = ast.Name(id='BaseException', ctx=ast.Load())
        nm = node.name or '_e_sw'
        node.name = nm
        rec = ast.parse(
            f"__import__('builtins')._GAEUM_SWALLOW.append(({node.lineno}, type({nm}).__name__, str({nm})[:200], {int(_is_pass_only(node))}))"
        ).body[0]
        node.body = [rec] if _is_pass_only(node) else [rec] + node.body
        return node


def main():
    rows = static_census()
    print(f'① 화면 도달 모듈 · except 핸들러 {sum(r[1] for r in rows)}개 · 몸통이 pass 뿐 {sum(r[0] for r in rows)}개')
    for n_pass, n_all, name in rows[:15]:
        print(f'   {n_pass:4d} / {n_all:4d}  {name}')

    src = open(WEB, encoding='utf-8').read()
    tree = ast.parse(src)
    sw = []
    builtins._GAEUM_SWALLOW = sw
    ins = _Instr()
    tree = ins.visit(tree)
    ast.fix_missing_locations(tree)
    code = ast.unparse(tree)
    print(f'② web_app.py 에 심은 자리 {ins.n}개 ({"전부" if ALL else "pass 뿐"}) · 사본 {len(code):,}자')

    from streamlit.testing.v1 import AppTest
    at = AppTest.from_string(code, default_timeout=900)
    at.run()
    print('렌더 예외', len(at.exception), [str(e.value)[:160] for e in at.exception])
    texts = []
    for kind in ('caption', 'markdown', 'info', 'warning', 'error', 'success', 'subheader', 'header', 'title'):
        for el in getattr(at, kind):
            texts.append(str(el.value))
    flat = re.sub(r'<[^>]+>', ' ', '\n'.join(texts))
    print('렌더 글자 수', len(flat))

    lines = src.splitlines()
    by_line = {}
    for ln, typ, msg, is_pass in sw:
        by_line.setdefault(ln, []).append((typ, msg))
    n_pass_fired = len({ln for ln, _, _, p in sw if p})
    print(f'\n③ 실제로 걸린 자리 {len(by_line)}개 (그중 pass 뿐 {n_pass_fired}개) · 걸린 횟수 {len(sw)}회 · 심은 자리 {ins.n}개')
    for ln in sorted(by_line):
        hits = by_line[ln]
        typs = {}
        for typ, msg in hits:
            typs[(typ, msg)] = typs.get((typ, msg), 0) + 1
        print(f'\n--- web_app.py:{ln}  ×{len(hits)}')
        for (typ, msg), c in sorted(typs.items(), key=lambda kv: -kv[1])[:3]:
            print(f'    {typ}: {msg!r} ×{c}')
        for i in range(max(0, ln - 9), ln):
            print(f'    {i + 1:5d}  {lines[i][:150]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
