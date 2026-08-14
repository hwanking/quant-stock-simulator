# -*- coding: utf-8 -*-
"""라운드 95 — 이슈 등록부에 남은 옛 재평가일을 고친다.

■ 무엇이 문제였나
  라운드 78 이 전방 재평가일을 2026-08-23 → 2026-11-16 으로 정정했다.
  라운드 93 이 코드에 남은 것을 전수로 훑어 세 파일을 고쳤다. 그런데
  **등록부(sqlite)는 .py 가 아니라서 그 스캔에 안 걸렸다.**

      [high] 검증-블라인드 괴리 감시 · 기한 2026-08-23

  화면의 '주요 이슈'가 이 기한을 읽어 보여 준다. 지나간 날짜를 목표로
  걸어 두면, 그 이슈는 영원히 '기한 초과'로 보인다.

■ 왜 스크립트로 두나
  등록부는 gitignored 라 저장소에 없다. 다른 환경에서도 같은 상태로
  맞출 수 있어야 한다 (라운드 89 의 close_issue_mfe.py 와 같은 이유).

■ 날짜를 **둘 다** 여기서 만들지 않는다
  · 새 날짜 = forward_eval.eval_date()
  · 옛 날짜 = data/regime_routing_r55.json 의 supersedes_date_in_note

  ⚠️ 처음엔 옛 날짜를 `OLD = '2026-08-23'` 으로 박아 뒀다가 회귀 §135 에
     걸렸다 — "어느 .py 에도 옛 재평가일이 박혀 있지 않다". 예외 목록에
     넣으면 그 검사가 도로 손 목록이 된다(라운드 93 이 없앤 그것).
     찾아보니 박제 파일이 옛 날짜를 이미 갖고 있었다. 정정을 기록해 둔
     그 칸이 바로 단일 출처다. 못 읽으면 지어내지 않고 멈춘다.

    C:/Python314/python.exe scripts/fix_issue_eta_r95.py
    C:/Python314/python.exe scripts/fix_issue_eta_r95.py --apply
"""
import io
import json
import os
import sqlite3
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
DB = os.path.join(PROJ, '.portfolio', 'improvement.db')
PIN = os.path.join(PROJ, 'data', 'regime_routing_r55.json')

import forward_eval as _fe                                     # noqa: E402


def old_date():
    """정정 **전** 날짜 — 박제 파일이 기록해 둔 값. 없으면 None."""
    try:
        with open(PIN, encoding='utf-8') as f:
            fe = (json.load(f) or {}).get('forward_eval') or {}
        return fe.get('supersedes_date_in_note') or None
    except Exception:                                          # noqa: BLE001
        return None


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def main():
    apply = '--apply' in sys.argv
    new = _fe.eval_date()
    old = old_date()
    if not new:
        print('전방 재평가일을 못 읽었다 — 지어내지 않고 멈춘다.')
        return 1
    if not old:
        print('정정 전 날짜를 못 읽었다 (regime_routing_r55.json) — '
              '무엇을 바꿀지 모르므로 멈춘다.')
        return 1
    if old == new:
        print(f'옛 날짜와 새 날짜가 같다 ({new}) — 바꿀 것이 없다.')
        return 0
    OLD = old
    print(f'옛 날짜 {OLD}  →  {new} (forward_eval)')

    if not os.path.exists(DB):
        print('등록부가 없다 — 이 환경에는 반영할 것이 없다.')
        return 0
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    # 어느 칸에 남아 있는지 **찾아서** 고친다. 칸 이름을 손으로 적으면
    # 다음에 다른 칸에 생겼을 때 또 놓친다 (라운드 93 의 교훈).
    cols = [r[1] for r in con.execute('PRAGMA table_info(improvement_issues)')]
    hits = []
    for r in con.execute('SELECT * FROM improvement_issues'):
        for c in cols:
            v = r[c]
            if isinstance(v, str) and OLD in v:
                hits.append((r['issue_id'], r['title'], c, v))
    if not hits:
        print('옛 날짜가 남은 칸이 없다.')
        con.close()
        return 0
    print(f'\n옛 날짜가 남은 칸 {len(hits)}개')
    for iid, title, c, v in hits:
        print(f"  [{title}] {c} = {v}")

    if not apply:
        print('\n(미리보기) --apply 를 주면 실제로 고친다.')
        con.close()
        return 0

    for iid, _t, c, v in hits:
        con.execute(f'UPDATE improvement_issues SET "{c}"=? '
                    f'WHERE issue_id=?', (v.replace(OLD, new), iid))
    con.commit()
    left = 0
    for r in con.execute('SELECT * FROM improvement_issues'):
        for c in cols:
            v = r[c]
            if isinstance(v, str) and OLD in v:
                left += 1
    print(f'\n{len(hits)}개를 고쳤다. 남은 것 {left}개.')
    for r in con.execute('SELECT title, eta, target FROM improvement_issues '
                         "WHERE status != 'resolved' ORDER BY rowid"):
        print(f"  {r['title']} · 기한 {r['eta']}")
    con.close()
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
