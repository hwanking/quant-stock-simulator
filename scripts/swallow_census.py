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
    C:/Python314/python.exe scripts/swallow_census.py --all --modules ui_kit,portfolio,trade_plan
        # 가져오는 모듈도 심는다 — 바꾼 소스를 원본 경로 이름으로 컴파일해 sys.modules 에 먼저 넣어 두면
        # web_app 의 `import ui_kit` 이 그것을 받는다(`__file__` 은 원본 경로 · 라운드 441 의 '안 심은 곳')
    C:/Python314/python.exe scripts/swallow_census.py --all --ticker 069500
        # 다른 종목 화면으로(ETF · 코스닥 · 보유 종목) — 갈래가 다르면 걸리는 핸들러가 다르다
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
MODULES = []
TICKER = None                        # --ticker 005930 → 회귀 하네스(render_probe)와 같은 `selected_ticker` 세션 키
for _i, _a in enumerate(sys.argv):
    if _a == '--modules' and _i + 1 < len(sys.argv):
        MODULES = [m.strip() for m in sys.argv[_i + 1].split(',') if m.strip()]
    if _a == '--ticker' and _i + 1 < len(sys.argv):
        TICKER = sys.argv[_i + 1].strip()


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
    """핸들러마다 (파일 · 원본 줄 · 예외 종류 · 메시지 · pass 뿐인가) 를 builtins 목록에 적게 바꾼다."""

    def __init__(self, path):
        self.n = 0
        self.path = path
        self.tag = os.path.relpath(path, PROJ).replace('\\', '/')

    def visit_Name(self, node):
        if node.id == '__file__':
            return ast.copy_location(ast.Constant(self.path), node)
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
            f"__import__('builtins')._GAEUM_SWALLOW.append(({self.tag!r}, {node.lineno}, type({nm}).__name__, "
            f"str({nm})[:200], {int(_is_pass_only(node))}))"
        ).body[0]
        node.body = [rec] if _is_pass_only(node) else [rec] + node.body
        return node


def instrument(path):
    """(바꾼 소스, 심은 수, 원본 줄 목록) — 원본은 안 건드린다."""
    src = open(path, encoding='utf-8').read()
    tree = ast.parse(src)
    ins = _Instr(path)
    tree = ins.visit(tree)
    ast.fix_missing_locations(tree)
    return ast.unparse(tree), ins.n, src.splitlines()


def preload_modules(names):
    """가져오는 모듈을 심은 채로 sys.modules 에 먼저 넣는다 — web_app 의 import 가 이것을 받는다."""
    import types
    out = {}
    for name in names:
        path = os.path.join(PROJ, *name.split('.')) + '.py'
        if not os.path.exists(path):
            print(f'   ⚠ 모듈 없음 {name} ({path})')
            continue
        code, n, lines = instrument(path)
        mod = types.ModuleType(name)
        mod.__file__ = path
        sys.modules[name] = mod
        exec(compile(code, path, 'exec'), mod.__dict__)
        out[name] = (n, lines)
        print(f'   심음 {name}: 핸들러 {n}개')
    return out


def main():
    rows = static_census()
    print(f'① 화면 도달 모듈 · except 핸들러 {sum(r[1] for r in rows)}개 · 몸통이 pass 뿐 {sum(r[0] for r in rows)}개')
    for n_pass, n_all, name in rows[:15]:
        print(f'   {n_pass:4d} / {n_all:4d}  {name}')

    sw = []
    builtins._GAEUM_SWALLOW = sw
    src_by = {}
    n_total = 0
    if MODULES:
        print(f'②-0 가져오는 모듈 먼저 심기 — {len(MODULES)}개')
        for name, (n, lines) in preload_modules(MODULES).items():
            src_by[name.replace('.', '/') + '.py'] = lines
            n_total += n
    code, n_web, web_lines = instrument(WEB)
    src_by['web_app.py'] = web_lines
    n_total += n_web
    print(f'② web_app.py 에 심은 자리 {n_web}개 ({"전부" if ALL else "pass 뿐"}) · 사본 {len(code):,}자 · 심은 자리 합 {n_total}개')

    from streamlit.testing.v1 import AppTest
    at = AppTest.from_string(code, default_timeout=900)
    if TICKER:
        at.session_state['selected_ticker'] = TICKER     # 다른 종목이면 다른 갈래의 핸들러가 걸린다 (라운드 441 의 '남은 것')
        print(f'   종목 {TICKER} 화면으로 렌더')
    at.run()
    print('렌더 예외', len(at.exception), [str(e.value)[:160] for e in at.exception])
    texts = []
    for kind in ('caption', 'markdown', 'info', 'warning', 'error', 'success', 'subheader', 'header', 'title'):
        for el in getattr(at, kind):
            texts.append(str(el.value))
    flat = re.sub(r'<[^>]+>', ' ', '\n'.join(texts))
    print('렌더 글자 수', len(flat))

    by_site = {}
    for tag, ln, typ, msg, is_pass in sw:
        by_site.setdefault((tag, ln), []).append((typ, msg))
    n_pass_fired = len({(t, ln) for t, ln, _, _, p in sw if p})
    print(f'\n③ 실제로 걸린 자리 {len(by_site)}개 (그중 pass 뿐 {n_pass_fired}개) · 걸린 횟수 {len(sw)}회 · 심은 자리 {n_total}개')
    for tag, ln in sorted(by_site):
        hits = by_site[(tag, ln)]
        typs = {}
        for typ, msg in hits:
            typs[(typ, msg)] = typs.get((typ, msg), 0) + 1
        print(f'\n--- {tag}:{ln}  ×{len(hits)}')
        for (typ, msg), c in sorted(typs.items(), key=lambda kv: -kv[1])[:3]:
            print(f'    {typ}: {msg!r} ×{c}')
        lines = src_by.get(tag) or []
        for i in range(max(0, ln - 9), min(ln, len(lines))):
            print(f'    {i + 1:5d}  {lines[i][:150]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
