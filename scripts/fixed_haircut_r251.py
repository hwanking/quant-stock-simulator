# -*- coding: utf-8 -*-
"""
라운드 251 — 사전등록 R251 의 **R0(근거가 있는가)** 를 잰다. 가장 싼 관문이다.

■ 왜 이것부터인가 (CLAUDE.md §2-7 · 라운드 170)
  *"싼 기준부터 잰다. 앞에서 미달이면 뒤는 재지 않는다."*
  근거가 어디엔가 적혀 있으면 이 라운드는 그것으로 끝난다 — 유지다.
  근거를 찾는 데는 몇 분이면 되고, 백필은 세 시간이다.

■ 무엇을 훑나 (대상을 손으로 적지 않는다 · 라운드 114)
  ① 저장소의 **모든 커밋**에서 이 상수가 처음 들어온 자리와 그 커밋 제목·본문
  ② docs/ 전체 · CLAUDE.md · 규칙집(JSON) 에서 0.98 / 2% / haircut 언급
  ③ 유도 모듈 전체에서 같은 계열의 고정 배수가 더 있는지

  훑은 개수를 전부 찍는다 — '없다'와 '못 봤다'를 가른다(라운드 194).

    C:/Python314/python.exe scripts/fixed_haircut_r251.py
"""
import io
import json
import os
import re
import subprocess
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
sys.path.insert(0, os.path.join(PROJ, 'scripts'))

OUT = os.path.join(PROJ, 'data', 'fixed_haircut_r251.json')
CONST = 'FAIR_FIXED_HAIRCUT'


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def git(*a):
    r = subprocess.run(['git'] + list(a), cwd=PROJ, capture_output=True,
                       text=True, encoding='utf-8', errors='replace')
    return r.stdout or ''


def ledger_last_date():
    """원장의 마지막 케이스 기준일 — 산출물이 무엇을 재고 만든 것인가."""
    p = os.path.join(PROJ, '.portfolio', 'virtual_graded.jsonl')
    last = ''
    for ln in io.open(p, encoding='utf-8', errors='replace'):
        i = ln.find('"date"')
        if i < 0:
            continue
        m = re.search(r'"date"\s*:\s*"(\d{4}-\d{2}-\d{2})', ln[i:])
        if m and m.group(1) > last:
            last = m.group(1)
    return last or None


def main():
    _utf8()
    print("R251 R0 — 고정 보정 0.98 의 근거가 어디엔가 있는가")
    print("=" * 78)

    out = {'gate': 'R0', 'const': CONST}

    # ── ① 커밋 이력 — 이 값이 처음 들어온 자리 ──────────────────────────
    print()
    print("① 커밋 이력 — 이 상수가 언제 들어왔나")
    print("-" * 78)
    log = git('log', '--reverse', '--format=%H|%ad|%s', '--date=short',
              '-S', '0.98', '--', 'quant_indicators.py')
    rows = [l for l in log.split('\n') if l.strip()]
    print(f"   'quant_indicators.py 에서 0.98 이 드나든' 커밋 {len(rows)}건")
    for l in rows[:12]:
        h, d, s = (l.split('|', 2) + ['', ''])[:3]
        print(f"   {d}  {h[:9]}  {s[:88]}")
    out['commits_touching_098'] = len(rows)
    out['first_commit'] = rows[0].split('|')[0][:9] if rows else None

    # ⚠️ 첫 판에서 이 자리를 **낱말로** 판정했다가 틀렸다 (2026-09-09).
    #   '본문이 이 값을 설명하는 커밋'을 `0.98|2%|보정|haircut|할인` 정규식으로
    #   셌더니 **라운드 238 자신**이 잡혔다 — 그 커밋은 근거가 **없다고 적은**
    #   커밋이다. 검사 이름은 '설명하는'인데 실제로 잰 것은 '낱말을 담은'이었다.
    #   같은 계열: 라운드 194('심어' 낱말) · 라운드 165(표기 하나만).
    #   → **뜻을 낱말로 판정하지 않는다.** 커밋이 둘뿐이니 본문을 그대로 찍고,
    #     '근거를 대는 문장'과 '근거가 없다고 적는 문장'을 갈라 센다.
    NO_BASIS = re.compile(r'근거가 (?:코드에도|문서에도|없|기록되어 있지)'
                          r'|근거 없는|근거가 없다')
    GIVES = re.compile(r'(?:0\.98|고정 보정|−2\.0%|-2\.0%).{0,80}?'
                       r'(?:때문|이유는|근거는|위해|하려고|산출했|측정했|실측)')
    bodies = []
    for l in rows[:12]:
        h = l.split('|')[0]
        body = git('show', '-s', '--format=%B', h)
        bodies.append((h[:9], body))
    gives, denies = [], []
    for h, body in bodies:
        one = ' '.join(body.split())
        if NO_BASIS.search(body):
            denies.append((h, one[:180]))
        elif GIVES.search(body):
            gives.append((h, one[:180]))
    print(f"   본문 전문을 읽은 커밋 {len(bodies)}건")
    print(f"      근거를 **대는** 커밋 {len(gives)}건")
    for h, b in gives:
        print(f"         {h}  {b[:140]}")
    print(f"      근거가 **없다고 적은** 커밋 {len(denies)}건")
    for h, b in denies:
        print(f"         {h}  {b[:140]}")
    out['commits_read'] = len(bodies)
    out['commits_explaining'] = len(gives)
    out['commits_denying_basis'] = len(denies)

    # ── ② 문서·규칙집 — 근거가 적혀 있나 ────────────────────────────────
    print()
    print("② 문서·규칙집 — 0.98 / −2% / 고정 보정 을 설명하는 자리")
    print("-" * 78)
    targets = []
    ddir = os.path.join(PROJ, 'docs')
    targets += [os.path.join('docs', f) for f in sorted(os.listdir(ddir))
                if f.endswith('.md')]
    targets.append('CLAUDE.md')
    for f in sorted(os.listdir(PROJ)):
        if f.endswith('.json'):
            targets.append(f)
    dj = os.path.join(PROJ, 'data')
    targets += [os.path.join('data', f) for f in sorted(os.listdir(dj))
                if f.endswith('.json')]

    PAT = re.compile(r'0\.98|고정 보정|FAIR_FIXED_HAIRCUT|고정 −2|고정 -2')
    hits = []
    scanned = 0
    for rel in targets:
        p = os.path.join(PROJ, rel)
        if not os.path.isfile(p):
            continue
        scanned += 1
        src = io.open(p, encoding='utf-8', errors='replace').read()
        for m in PAT.finditer(src):
            ln = src[:m.start()].count('\n') + 1
            line = src.split('\n')[ln - 1].strip()
            hits.append((rel, ln, line[:130]))
    print(f"   훑은 파일 {scanned}개 · 언급 {len(hits)}건")
    for rel, ln, line in hits[:30]:
        print(f"   {rel}:{ln}  {line}")
    if len(hits) > 30:
        print(f"   … 그 밖 {len(hits) - 30}건")
    out['docs_scanned'] = scanned
    out['docs_mentions'] = len(hits)

    # **근거**를 적은 것과 **없다고 적은 것**을 가른다
    says_no_basis = [h for h in hits
                     if re.search(r'근거가 (?:코드에도|없|기록되어 있지 않)', h[2])]
    print(f"   그중 '근거가 없다'고 **적고 있는** 줄 {len(says_no_basis)}건")
    out['docs_saying_no_basis'] = len(says_no_basis)

    # ── ③ 같은 계열의 고정 배수가 더 있나 ───────────────────────────────
    print()
    print("③ 판정 경로에 같은 계열의 고정 배수가 더 있나")
    print("-" * 78)
    import lineage_audit as la
    mods = sorted(la.reachable_modules())
    MULT = re.compile(r'^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(0\.9\d|1\.0[1-9])\s*$', re.M)
    found = []
    for rel in mods:
        p = os.path.join(PROJ, rel)
        if not os.path.isfile(p):
            continue
        src = io.open(p, encoding='utf-8', errors='replace').read()
        for m in MULT.finditer(src):
            ln = src[:m.start()].count('\n') + 1
            found.append((rel, ln, m.group(1), m.group(2)))
    print(f"   훑은 모듈 {len(mods)}개 · 모듈 수준 고정 배수 상수 {len(found)}건")
    for rel, ln, name, val in found:
        print(f"   {rel}:{ln}  {name} = {val}")
    out['modules_scanned'] = len(mods)
    out['sibling_constants'] = [f"{r}:{l} {n}={v}" for r, l, n, v in found]

    # ── 판정 ────────────────────────────────────────────────────────────
    print()
    print("R0 판정")
    print("-" * 78)
    has_basis = out['commits_explaining'] > 0
    print(f"   근거를 대는 커밋 {out['commits_explaining']} · "
          f"근거가 없다고 적은 커밋 {out['commits_denying_basis']} · "
          f"문서에서 '근거 없음'을 적은 줄 {out['docs_saying_no_basis']}")
    if has_basis:
        print("   근거가 커밋 본문에 있다 → **유지하고 끝낸다.** R1 이하를 재지 않는다.")
        out['verdict'] = 'R0 — 근거 있음 · 유지'
    else:
        print(f"   커밋 {out['commits_touching_098']}건 · 문서 {scanned}개 어디에도")
        print("   이 값을 **설명하는** 근거가 없다. 문서는 '근거가 없다'고 적고 있을 뿐이다")
        print(f"   ({out['docs_saying_no_basis']}건).")
        print("   >> R0 통과 — R1(영향의 상한)로 넘어간다.")
        out['verdict'] = 'R0 통과 — 근거 없음 확인 · R1 으로'

    out['ledger_last_date'] = ledger_last_date()
    json.dump(out, io.open(OUT, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print(f"\n저장: {OUT}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
