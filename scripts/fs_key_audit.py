# -*- coding: utf-8 -*-
"""`four_scores` 의 칸 중 **아무도 안 읽는 것**을 유도한다 (라운드 313).

사용자: *"적정가나 살 타이밍에 전수조사해줘."* 라운드 302 는 스냅샷을 **흔들어서**
재려 했는데 잣대가 닫혀 있었다(표본 6종목이 전부 출발부터 '신규 매수 보류'라 결론이
움직일 자리가 없었다). 그러면 다른 잣대를 쓴다 — **누가 읽는가**는 코드만으로 답이 난다.
이 저장소에서 그 잣대가 두 번 실재를 찾았다: R297(`TAB_WEIGHTS` 읽는 곳 0) ·
R301(`final_score_cap` 만드는 곳도 읽는 곳도 0).

■ 무엇을 재는가 (§6 — 이름만 보고 믿지 않는다)
  잰다   : 엔진이 `four_scores` 로 **내보내는 칸 이름**과, 저장소의 .py 가 그 이름을
           **읽는 횟수**(AST: `.get('X')` · `['X']` / 그리고 **글자 등장**도 따로).
  못 잰다: 동적 접근(`fs.get(varname)`)과 화면이 조립하는 이름. 그래서 '0' 은
           **후보**지 판정이 아니다 — 눈으로 확인하고 문서에 적는다(§3 · R194).

■ ⚠️ 이 판별식은 세 번 틀렸다 (그대로 적는다 — 라운드 313)
  ① 대상: `quant_indicators.py` 의 **20칸 이상 dict 전부**를 모았다 → 315개. 남의
     dict(`prices_df`·`rho_cutoff`…)가 섞였다.
  ② 대상: 그 함수의 `return {...}` 만 봤다 → **5개**. 그 함수는 dict 를 변수
     (`_fs_out`)에 담아 내보낸다.
  ③ 소비자: **만드는 파일을 소비자에서 뺐다** → 21개. `quant_indicators.py` 자신이
     `fs.get('target_first_prob')` 를 읽는다. 자기 리터럴 **줄 안의** 등장만 빼야 한다.
  ①②③ 중 하나라도 남았으면 *"68개가 죽어 있다"* 는 거짓 보고가 나갔다.
"""
import ast
import io
import os
import re

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAKER = 'quant_indicators.py'
#: 엔진이 four_scores 를 담는 지역 변수 이름. 바뀌면 `produced_keys` 가 빈 집합을
#: 돌려주고, 검사는 그것을 **미측정**으로 읽어야 한다 (0 이 아니다).
FS_VAR = '_fs_out'

#: ⚠️ **네 번째 정정** — 검사 자신이 소비자로 세어졌다. 회귀에 *"`final_quant_score`
#:   는 아무도 안 읽는다"* 는 검사를 넣자 그 줄의 **글자** 때문에 그 칸이 '읽힌다' 가
#:   되어 검사가 자기 자신을 틀리게 만들었다(이 감사 모듈의 독스트링도 같은 일을 했다 —
#:   `target_first_prob` 를 적어 두었다). 검사는 소비자가 아니다 — **재는 도구는 재는
#:   대상에서 뺀다.** 뺀 파일 수는 산출물에 적는다(조용히 빼지 않는다 · R194).
AUDITORS = ('test_pipeline_fixes.py', 'scripts/fs_key_audit.py')


def _maker_tree():
    src = io.open(os.path.join(PROJ, MAKER), encoding='utf-8').read()
    return src, ast.parse(src)


def produced_keys():
    """엔진이 `four_scores` 로 내보내는 칸 이름과, 그 리터럴이 차지하는 줄 번호."""
    _src, tree = _maker_tree()
    keys, lines = set(), set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict)
                and any(isinstance(t, ast.Name) and t.id == FS_VAR
                        for t in node.targets)):
            lines |= set(range(node.lineno,
                               (node.end_lineno or node.lineno) + 1))
            for k in node.value.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    keys.add(k.value)
        if (isinstance(node, ast.Assign) and node.targets
                and isinstance(node.targets[0], ast.Subscript)
                and isinstance(node.targets[0].value, ast.Name)
                and node.targets[0].value.id == FS_VAR
                and isinstance(node.targets[0].slice, ast.Constant)
                and isinstance(node.targets[0].slice.value, str)):
            keys.add(node.targets[0].slice.value)
    return keys, lines


def _py_files():
    out = []
    for root, dirs, names in os.walk(PROJ):
        dirs[:] = [d for d in dirs
                   if d not in ('.git', '__pycache__', '_probe', '.portfolio')]
        for n in names:
            if n.endswith('.py'):
                out.append(os.path.relpath(os.path.join(root, n), PROJ))
    return out


def scan():
    """{'produced': N, 'files': N, 'dead': [...], 'ast_only_zero': [...]}.

    `dead` 는 **AST 로도 글자로도** 한 번도 안 읽힌 칸이다(자기 리터럴 줄 제외).
    `ast_only_zero` 는 AST 는 0 인데 글자로는 보이는 칸 — 주석·문서·조립일 수 있어
    사람이 본다.
    """
    keys, fs_lines = produced_keys()
    if not keys:
        return {'produced': 0, 'files': 0, 'dead': [], 'ast_only_zero': [],
                'measured': False, 'skipped_auditors': 0}
    ast_hits = {k: 0 for k in keys}
    lit_hits = {k: 0 for k in keys}
    all_files = _py_files()
    files = [f for f in all_files
             if f.replace('\\', '/') not in AUDITORS]
    skipped = len(all_files) - len(files)
    for rel in files:
        p = os.path.join(PROJ, rel)
        try:
            s = io.open(p, encoding='utf-8', errors='replace').read()
        except Exception:                                      # noqa: BLE001
            continue
        is_maker = rel.replace('\\', '/') == MAKER
        s_lit = ('\n'.join(l for i, l in enumerate(s.splitlines(), 1)
                           if i not in fs_lines) if is_maker else s)
        for k in keys:
            if k in s_lit:
                lit_hits[k] += len(re.findall(re.escape(k), s_lit))
        try:
            t = ast.parse(s)
        except SyntaxError:
            continue
        for node in ast.walk(t):
            name = None
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'get' and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                name = node.args[0].value
            elif (isinstance(node, ast.Subscript)
                  and isinstance(node.slice, ast.Constant)
                  and isinstance(node.slice.value, str)):
                name = node.slice.value
            if name in ast_hits:
                if is_maker and getattr(node, 'lineno', -1) in fs_lines:
                    continue          # 자기 리터럴 — 넣는 것이지 읽는 것이 아니다
                ast_hits[name] += 1
    return {
        'produced': len(keys), 'files': len(files), 'measured': True,
        'skipped_auditors': skipped,
        'dead': sorted(k for k in keys
                       if ast_hits[k] == 0 and lit_hits[k] == 0),
        'ast_only_zero': sorted(k for k in keys
                                if ast_hits[k] == 0 and lit_hits[k] > 0),
    }


if __name__ == '__main__':
    r = scan()
    print('내보내는 칸 %d개 · 훑은 파일 %d개 (검사 도구 %d개 제외)'
          % (r['produced'], r['files'], r['skipped_auditors']))
    print('아무도 안 읽는 칸 %d개' % len(r['dead']))
    for k in r['dead']:
        print('   ' + k)
    print('AST 0 · 글자는 있음 %d개' % len(r['ast_only_zero']))
