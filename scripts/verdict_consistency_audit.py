# -*- coding: utf-8 -*-
"""
중앙 판정 일관성 감사 (라운드 503) — 개장 전 리포트 후보의 중앙 판정(core)이 **스스로 모순되는 곳**을 전수로 센다.

    python scripts/verdict_consistency_audit.py            최신 리포트는 엄격(모순 있으면 종료 1) · 지난 리포트 전부는 셈만
    python scripts/verdict_consistency_audit.py --all      지난 리포트까지 엄격

판별은 `verdict_core.consistency_problems` **한 곳**(회귀 §483 과 같은 것)이고, 이 스크립트는 읽고 센다 — 판정을 바꾸지 않는다.
저녁 작업의 마지막 단계(`scripts/nightly_local.py`)가 매일 부른다: 그날 만든 리포트(최신)가 모순이면 그날 기록에 남는다.
지난 리포트의 모순은 그 판을 만든 날의 코드가 낸 것이라(예: 라운드 417 전의 '조건이 갖춰지면 후보') 셈만 하고 실패로 치지 않는다.
라운드 508 — 관심종목 추천 문서(라운드 507 · `swing_watch` · 리포트와 같은 모양 · 실주문 자격 계획이 나온다)의 최신 판도 같은
함수로 엄격하게 센다. 문서가 없으면 그 줄은 '미측정'이다.
종목 이름은 찍지 않는다(코드 끝 두 자리만).
"""
import argparse
import glob
import json
import os
import sys
from collections import Counter

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:                                          # noqa: BLE001
        pass


def report_files(pm_dir=None):
    import premarket
    return sorted(glob.glob(os.path.join(pm_dir or premarket.PM_DIR, 'premarket_*.json')),
                  key=lambda p: os.path.getmtime(p))


def watch_files(watch_dir=None):
    """관심종목 추천 문서(라운드 507) — 이름이 판정일(YYYYMMDD)이라 이름 순 = 판정일 순."""
    import swing_watch
    return sorted(glob.glob(os.path.join(watch_dir or swing_watch.DIR, swing_watch.PREFIX + '*.json')))


def audit_report(path):
    """→ (후보 수, [(코드 끝 둘, 문제)])."""
    try:
        with open(path, encoding='utf-8') as f:
            d = json.load(f)
    except Exception as e:                                     # noqa: BLE001
        return 0, [('—', f'리포트를 못 읽었다: {type(e).__name__}')]
    import verdict_core as V
    n, probs = 0, []
    for pk in d.get('picks') or []:
        core = (pk or {}).get('core')
        if not isinstance(core, dict):
            continue
        n += 1
        code = str((pk or {}).get('symbol') or (pk or {}).get('code') or '')
        for pr in V.consistency_problems(core):
            probs.append(('…' + code.split('.')[0][-2:], pr))
    return n, probs


def main(argv=None):
    _utf8()
    ap = argparse.ArgumentParser(description='중앙 판정 일관성 감사 (라운드 503)')
    ap.add_argument('--all', action='store_true', help='지난 리포트까지 모순을 실패로 친다')
    a = ap.parse_args(argv)
    files = report_files()
    bad_w = _audit_watch()
    if not files:
        print('개장 전 리포트가 없다 — 감사할 것 없음(미측정)')
        return 1 if bad_w else 0
    tot_n, tot_p, kinds = 0, 0, Counter()
    for p in files[:-1]:
        n, probs = audit_report(p)
        tot_n += n
        tot_p += len(probs)
        kinds.update(pr.split(':')[0][:30] for _c, pr in probs)
    n_last, probs_last = audit_report(files[-1])
    print(f'지난 리포트 {len(files) - 1}개 · 후보 {tot_n} · 모순 {tot_p}'
          + (f" — 종류: {', '.join(f'{k} {v}' for k, v in kinds.most_common(4))}" if kinds else ''))
    print(f'최신 리포트 {os.path.basename(files[-1])} · 후보 {n_last} · 모순 {len(probs_last)}')
    for c, pr in probs_last[:10]:
        print(f'  {c} · {pr}')
    bad = bool(probs_last) or (a.all and tot_p > 0) or bad_w
    return 1 if bad else 0


def _audit_watch():
    """관심종목 추천 문서의 최신 판 → 모순이 있으면 True(엄격 · 실주문 자격 계획이 여기서 나온다). 없으면 '미측정'을 찍고 False."""
    wf = watch_files()
    if not wf:
        print('관심종목 추천 문서가 없다 — 감사할 것 없음(미측정)')
        return False
    n, probs = audit_report(wf[-1])
    print(f'관심종목 추천 문서 {os.path.basename(wf[-1])} · 후보 {n} · 모순 {len(probs)}')
    for c, pr in probs[:10]:
        print(f'  {c} · {pr}')
    return bool(probs)


if __name__ == '__main__':
    sys.exit(main())
