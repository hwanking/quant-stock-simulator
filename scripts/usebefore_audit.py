# -*- coding: utf-8 -*-
"""모듈 최상위에서 **정의보다 먼저 쓰는 이름**을 찾는다 (라운드 199).

■ 왜 이 파일이 따로 있나
  라운드 197 이 같은 판별식을 **두 벌** 만들었다 — `_probe/r197_usebefore.py`
  와 회귀 §226. 그리고 라운드 199 에서 **한쪽만 고쳤다.** 프로브는 0건,
  회귀는 74건. 이 세션이 내내 다룬 그 결함(§4 — 경로가 둘이면 한쪽만
  고치는 일이 생긴다)을 판별식에서 그대로 저질렀다.
  그래서 구현을 **한 곳**에 둔다. 프로브도 §226 도 여기를 부른다.

■ 무엇을 재나
  모듈 본문을 **줄 순서대로** 훑으며 최상위에서 묶이는 이름을 모으고,
  아직 안 묶인 이름을 **즉시** `Load` 하는 자리를 잡는다. 그런 자리는
  **컴파일은 통과하고 실행에서 `NameError`** 다.

■ 무엇은 안 보나 (셋 다 오탐을 내다 하나씩 배운 것)
  · 함수·람다·클래스 **몸통** — 나중에 호출되므로 순서가 문제되지 않는다.
    ⚠️ 최상위 문장이 **그 자체로 def/class** 인 경우도 몸통을 보면 안 된다.
       라운드 199 가 여기서 오탐 74건을 냈다.
  · **같은 문장 안에서 묶이는 이름** — `for k in xs: f(k)` 의 `k`.
    ⚠️ 이걸 안 빼면 3,124건이 나온다.
  · `X if 'X' in dir() else Y` — 저장소가 **스스로 막아 둔** 자리.
"""
import ast
import builtins

BUILTINS = set(dir(builtins)) | {'__name__', '__file__', '__doc__'}
DEFER = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


def _bound_by(node):
    """이 최상위 문장이 **남기는** 이름 (다음 문장부터 쓸 수 있다)."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            out.add(n.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                out.add((a.asname or a.name).split('.')[0])
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                            ast.ClassDef)):
            out.add(n.name)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            out.add(n.name)
    return out


def _local_binds(node):
    """이 **문장 안에서** 묶이는 이름 — for 변수·컴프리헨션·인자 등."""
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            out.add(n.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                out.add((a.asname or a.name).split('.')[0])
        elif isinstance(n, DEFER):
            nm = getattr(n, 'name', None)
            if nm:
                out.add(nm)
            a = getattr(n, 'args', None)
            if a is not None:
                for arg in (list(getattr(a, 'posonlyargs', []))
                            + list(a.args) + list(a.kwonlyargs)):
                    out.add(arg.arg)
                if a.vararg:
                    out.add(a.vararg.arg)
                if a.kwarg:
                    out.add(a.kwarg.arg)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            out.add(n.name)
        elif isinstance(n, ast.comprehension):
            for t in ast.walk(n.target):
                if isinstance(t, ast.Name):
                    out.add(t.id)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            out.update(n.names)
    return out


def _loads(node):
    """이 문장이 **즉시** 읽는 이름 — 미뤄지는 몸통은 건너뛴다."""
    out = []

    def walk(n, top=False):
        if isinstance(n, DEFER) and not top:
            for d in getattr(n, 'decorator_list', []):
                walk(d)
            return
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            out.append((n.id, n.lineno))
        for c in ast.iter_child_nodes(n):
            walk(c)

    # 최상위 문장이 그 자체로 def/class 면 **몸통은 안 본다** —
    # 데코레이터와 기본값만 즉시 평가된다.
    if isinstance(node, DEFER):
        for d in getattr(node, 'decorator_list', []):
            walk(d)
        a = getattr(node, 'args', None)
        if a is not None:
            for df in list(a.defaults) + [x for x in a.kw_defaults if x]:
                walk(df)
        return out
    walk(node, top=True)
    return out


def _guarded(node):
    """`X if 'X' in dir() else Y` — 스스로 막아 둔 자리는 위반이 아니다."""
    out = set()
    for n in ast.walk(node):
        if (isinstance(n, ast.Compare) and len(n.ops) == 1
                and isinstance(n.ops[0], ast.In)
                and isinstance(n.left, ast.Constant)
                and isinstance(n.left.value, str)
                and isinstance(n.comparators[0], ast.Call)
                and getattr(n.comparators[0].func, 'id', '')
                in ('dir', 'globals')):
            out.add(n.left.value)
    return out


def scan(src):
    """(훑은 최상위 문장 수, ['줄:이름', …]) 을 돌려준다."""
    tree = ast.parse(src)
    bound, bad, stmts = set(BUILTINS), [], 0
    for stmt in tree.body:
        stmts += 1
        local = _local_binds(stmt) | _guarded(stmt)
        for name, lineno in _loads(stmt):
            if name not in bound and name not in local:
                bad.append(f'{lineno}:{name}')
        bound |= _bound_by(stmt)
    return stmts, bad


#: 심기 — 있을 때 잡고, 없을 때 조용한가. 오탐 셋도 함께 확인한다.
PLANTS = {
    'bad': ("x = later()\ndef later():\n    return 1\n", 1),
    'ok': ("def later():\n    return 1\nx = later()\n", 0),
    'for': ("for k in [1, 2]:\n    print(k)\n"
            "ys = [z * 2 for z in [1, 2]]\n", 0),
    'dir': ("a = f() if 'f' in dir() else 1\n", 0),
    'body': ("def f():\n    return later()\ndef later():\n    return 1\n", 0),
}


def self_check():
    """심기 다섯이 기대대로인가 — (통과 여부, 상세)."""
    detail = {}
    ok = True
    for k, (src, want) in PLANTS.items():
        got = len(scan(src)[1])
        detail[k] = f'{got}/{want}'
        if got != want:
            ok = False
    return ok, detail
