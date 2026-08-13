# -*- coding: utf-8 -*-
"""라운드 89 — 라운드 85 가 실측으로 닫은 이슈를 등록부에도 반영한다.

■ 왜 별도 스크립트인가
  이슈 등록부(.portfolio/improvement.db)는 gitignored 라 저장소에 없다.
  그래서 '닫았다'는 사실이 문서에만 남고 등록부는 open 인 채였다 —
  같은 사실이 두 곳에 있고 한쪽만 고친 상태다(§4 가 경계하는 그것).
  이 스크립트를 두면 어느 환경에서도 같은 상태로 맞출 수 있다.

■ 무엇을 닫나
  'medium · 원장 mfe/mae 는 청산 봉까지만 — 연구용 창이 다르다'
  근거: docs/MFE_WINDOW_R85.md — bar_paths 가 청산과 무관하게 21봉을
  보존한다(표본 60,000건 중 100%). 목표 확장 연구가 성립한다.

  **원장 필드는 안 고쳤다.** mfe_pct 는 '실제로 실현된 것'이라는 다른
  뜻이라 그대로 두고, 연구는 경로만 쓴다는 규칙으로 가른다.

    C:/Python314/python.exe scripts/close_issue_mfe.py [--apply]
"""
import io
import os
import sqlite3
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(PROJ, '.portfolio', 'improvement.db')
KEY = '원장 mfe/mae'
NOTE = ('라운드 85 실측으로 해결. bar_paths 가 청산 여부와 무관하게 21봉을 '
        '보존한다(표본 60,000건 중 100%). 손절 종료 71,510건의 경로 전체 '
        '최대 상승은 중앙 +2.50%, +10% 이상이 17.3%. 다만 이는 한쪽만 센 '
        '숫자이므로 목표·손절을 바꾸는 근거로 쓰지 않는다 — 다음 라운드는 '
        '사전등록으로, 도달률 하락을 포함한 신호 전체 EV 로 판정한다. '
        '원장 mfe_pct 는 고치지 않는다(연구는 경로만 쓴다). '
        '근거: docs/MFE_WINDOW_R85.md')


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def main():
    apply = '--apply' in sys.argv
    if not os.path.exists(DB):
        print('등록부가 없다 — 이 환경에는 반영할 것이 없다.')
        return 0
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT issue_id, title, status FROM improvement_issues "
        "WHERE title LIKE ?", (f'%{KEY}%',)).fetchall()
    if not rows:
        print(f"'{KEY}' 이슈를 찾지 못했다 — 지어내지 않고 끝낸다.")
        con.close()
        return 0
    for r in rows:
        print(f"  [{r['status']}] {r['title']}")
    todo = [r for r in rows if r['status'] != 'resolved']
    if not todo:
        print('이미 resolved — 바꿀 것이 없다.')
        con.close()
        return 0
    if not apply:
        print(f'\n{len(todo)}건이 아직 open 이다. '
              f'--apply 를 주면 resolved 로 바꾼다.')
        con.close()
        return 0
    for r in todo:
        con.execute(
            "UPDATE improvement_issues SET status='resolved', "
            "resolved_at=datetime('now'), verification=? "
            "WHERE issue_id=?", (NOTE, r['issue_id']))
    con.commit()
    print(f'\n{len(todo)}건을 resolved 로 바꿨다.')
    for r in con.execute("SELECT status, title FROM improvement_issues "
                         "ORDER BY rowid DESC"):
        print(f"  [{r['status']:<8}] {r['title']}")
    con.close()
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
