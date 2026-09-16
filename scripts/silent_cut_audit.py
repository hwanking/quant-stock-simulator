# -*- coding: utf-8 -*-
"""화면이 **말없이 자르는 자리**를 유도한다 (라운드 314).

같은 결함을 두 번 고쳤다 — R301(상한 사유 `[:300]` 이 문장 중간에서 끊겼다) ·
R312(제외 사유 `_fail[:4]` 가 리포트 87개 중 16번 말없이 잘랐다). **두 번째 고칠 때는
공통 진입점을 찾는다**(R120e). 여기서는 고칠 함수가 하나가 아니라 **자리마다 다른
문장**이므로, 대신 **자리를 유도해서 세고 늘지 못하게** 한다.

  잰다   : 화면으로 나가는 호출(`st.caption` 등) 안에서 `X[:N]`(N 은 2 이상 상수)로
           자르는 자리와, 그 **앞뒤 4줄에 개수를 말하는 표현**이 있는지.
  못 잰다: 개수를 **다른 문단에서** 말하는 경우와, 자르는 것이 목적인 계산
           (`sum(weights[:3])` — 상위 3개 집중도)은 기계가 못 가른다.
           그래서 이 산출물은 **후보 목록**이고 판정은 사람이 한다(§3 · R194).

⚠️ 실측(2026-09-16 · 화면 도달 모듈 39개): 자르는 자리 **11곳** 중 아홉은 정직했다
   (옆에서 총 개수를 말하거나 `외 N` 을 붙인다). 결함은 둘이었다 —
     · 제외 사유 `_why[:120]`  — 문장 중간에서 끊기고 잘렸다는 말이 없었다
     · 시세 조회 실패 `_pxfail[:6]` — **수를 아예 안 적고** 이름 여섯 개만 나열했다
   **기계가 잡은 11곳을 그대로 '결함 11건' 이라 적으면 그것이 판별식이 넓은 것이다.**
"""
import ast
import io
import os
import re
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)

#: 화면으로 나가는 호출 이름
RENDER = ('markdown', 'caption', 'write', 'warning', 'info', 'error',
          'success', 'expander', 'metric', 'text')
#: '몇 개 중 몇 개'를 말하는 표현 — 있으면 정직한 자리일 **수** 있다(사람이 본다)
COUNTY = re.compile(r'len\(|외 \{|나머지|더 있|\{len')


def scan():
    """[{'module','line','n','src','has_count'}] — 자르는 자리 전부."""
    import scripts.lineage_audit as la
    out = []
    for m in sorted(set(la.reachable_modules('web_app.py'))):
        p = os.path.join(PROJ, m)
        if not os.path.exists(p):
            continue
        src = io.open(p, encoding='utf-8', errors='replace').read()
        lines = src.splitlines()
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in RENDER):
                continue
            for sub in ast.walk(node):
                if not (isinstance(sub, ast.Subscript)
                        and isinstance(sub.slice, ast.Slice)):
                    continue
                up = sub.slice.upper
                if not (isinstance(up, ast.Constant)
                        and isinstance(up.value, int)):
                    continue
                if sub.slice.lower is not None or up.value <= 1:
                    continue
                ln = getattr(sub, 'lineno', 0)
                lo, hi = max(1, ln - 4), min(len(lines), ln + 4)
                chunk = '\n'.join(lines[lo - 1:hi])
                out.append({
                    'module': m, 'line': ln, 'n': up.value,
                    'src': lines[ln - 1].strip()[:120] if ln else '',
                    'has_count': bool(COUNTY.search(chunk)),
                })
    return out


if __name__ == '__main__':
    r = scan()
    print('자르는 자리 %d곳 · 그중 옆에서 개수를 말하는 곳 %d곳'
          % (len(r), sum(1 for x in r if x['has_count'])))
    for x in r:
        print('  %-14s :%-6d [:%d] %s  %s'
              % (x['module'], x['line'], x['n'],
                 '개수 있음' if x['has_count'] else '개수 **없음**', x['src']))
