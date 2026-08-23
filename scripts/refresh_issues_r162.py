# -*- coding: utf-8 -*-
"""라운드 162 — 열린 이슈 셋에 최근 측정 결과를 붙이고 검토일을 되살린다.

■ 왜 별도 스크립트인가
  이슈 등록부(.portfolio/improvement.db)는 gitignored 라 저장소에 없다.
  라운드 89(`close_issue_mfe.py`) · 95(`fix_issue_eta_r95.py`)와 같은
  이유로, 어느 환경에서도 같은 상태로 맞출 수 있게 스크립트로 남긴다.

■ 무엇이 문제였나
  세 이슈의 **검토일이 지났거나 오늘**인데 그 사이 R111·
  R112·R159·R160 이 바로 그 목표를 겨냥해 측정했다. 결과가 문서에만
  있고 등록부는 옛 숫자를 안고 열려 있다 — 같은 사실이 두 곳에 있고
  한쪽만 고친 상태다(§4 가 경계하는 그것).

■ 무엇을 하고 무엇을 안 하나
  · 측정 결과를 `verification` 에 붙이고 **지난 검토일을 되살린다**
  · **기한(eta)은 늘리지 않는다** — 동결과 무관한 두 이슈는 원래 기한
    (9/15 · 9/30)을 그대로 둔다. 미루면 이슈가 조용히 흐려진다
  · **어느 것도 resolved 로 바꾸지 않는다** — 셋 다 목표 미달이다.
    닫히지 않은 것을 닫힌 것처럼 적지 않는다(§9)
  · 점수·게이트·문턱·화면을 바꾸지 않는다

    C:/Python314/python.exe scripts/refresh_issues_r162.py [--apply]
"""
import io
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(PROJ, '.portfolio', 'improvement.db')

#: ⚠️ **기한(eta)은 늘리지 않는다.** 지난 검토일을 되살리는 것이 목적이지
#: 마감을 미루는 것이 아니다 — 미루면 이슈가 조용히 흐려진다(§9).
#: 검토일은 그 이슈의 기한에 맞추되, 국면을 맞춘 비교가 필요한
#: 괴리 이슈만 전방 재평가일(2026-11-16)을 쓴다.
FORWARD_EVAL = '2026-11-16'

UPDATES = {
    'model|vb_gap': dict(
        note=(
            '라운드 159 전수 조사(원장 184,759건)로 다시 쟀다. '
            '매수권(58점+) 기준 valid 65.1%(n 6,925) vs blind 50.4%'
            '(n 5,458) — 격차 14.7%p 로 목표(같은 국면끼리 5%p 이내)에 '
            '한참 못 미친다. 점수대별로도 blind 는 50.4 / 50.2 / 50.7% 로 '
            '평평하다(valid 는 64.1 / 70.1 / 70.6%). '
            '다만 **국면을 맞춰 견준 것이 아니므로** 목표 달성 여부를 '
            '판정하지는 않았다 — 그 비교는 별도 사전등록이 필요하다. '
            '곁들여 연도별(45.8~69.6%)은 추세가 아니라 국면이다. 이 원장은 '
            '동결된 하나의 엔진을 여러 시기에 되돌려 본 기록이라 '
            '"엔진이 좋아졌나"를 이 표로는 답할 수 없다. '
            '근거: docs/RESULT_R159_CENSUS.md'),
        # 국면을 맞춘 비교는 전방 재평가 뒤에야 가능하다
        next_review=FORWARD_EVAL, keep_eta=False, eta=FORWARD_EVAL),
    'model|score_not_separating': dict(
        note=(
            '목표("구성요소 중 학습·검증 양쪽에서 lift>0 인 것 1개 이상")를 '
            '실제로 겨냥해 두 번 쟀고 **둘 다 미달**이다. '
            '라운드 111 — 하위점수 7종을 각각 같은 날·짝비교로 돌려 8개 '
            '전부 미달(최고 trading_timing z +0.72, 보정 문턱 2.73). '
            '라운드 112 — 업종 내 백분위·자기 이력 z 로 상대화해 16개 전부 '
            '미달(문턱 2.9552, 최고 +2.17). 대조로 상대화 없이 표본만 줄여도 '
            '원값 z 가 −0.42~+2.10 으로 흩어졌다 — +2.17 은 증거가 아니다. '
            '라운드 159 가 점수대별로도 확인했다: blind 50.4 / 50.2 / 50.7%. '
            '→ action_plan ①② 는 수행됐고 결과는 음성이다. 남은 것은 ③ '
            '(점수를 매수 신호가 아니라 점검 체크리스트로 재정의)이며, '
            '라운드 161 이 화면에 "본전에 필요한 적중률"을 병기해 그 방향으로 '
            '한 걸음 갔다. 근거: docs/RESULT_R111_SCORE_ANATOMY.md · '
            'docs/RESULT_R112_RELATIVIZATION.md · docs/RESULT_R159_CENSUS.md'),
        # 남은 것은 ③ 화면 재정의 — 동결과 무관하므로 기한을 그대로 둔다
        keep_eta=True),
    'usability|loss_control_tradeoff': dict(
        note=(
            '라운드 160 이 거울상(손절이 아니라 **목표**를 미는 쪽)을 '
            '사전등록으로 쟀고, 맞바꿈이 숫자로 확인됐다. 목표를 손절폭의 '
            '1.0~3.0배로 밀면 비용후 기대값 평균은 −0.432 → +0.117% 로 '
            '단조 개선되지만 **중앙값은 반대로** −0.252 → −1.088% 로 '
            '악화되고 하위 10% 도 −4.754 → −6.514% 로 나빠진다. '
            '이득은 전부 "이미 좋았던 날"에서만 나온다 — 현행이 나쁜 날의 '
            'ΔEV 중앙값이 네 배수 전부 정확히 0.000 이다(손절이 먼저 닿으면 '
            '목표가 어디 있든 같다). blind 에서 재현되는 것은 1.0R 하나뿐. '
            '→ "공짜 개선이 아니다"라는 이 이슈의 요지가 실측으로 뒷받침됐다. '
            '노출 여부는 여전히 미결이고, 실행 레벨 변경은 2026-11-16 이후 '
            '별도 사전등록이다. 근거: docs/RESULT_R160_TARGET_MULTIPLE.md'),
        # 노출 여부 결정은 동결과 무관하므로 기한을 그대로 둔다
        keep_eta=True),
}


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def main():
    apply = '--apply' in sys.argv
    if not os.path.exists(DB):
        print(f'등록부가 없습니다: {DB}')
        print('  (gitignored — 이 환경에 아직 만들어지지 않았습니다)')
        return 0
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    print('라운드 162 — 열린 이슈에 최근 측정 결과를 붙인다')
    print(f'  등록부 {DB}')
    print(f'  적용 {"예" if apply else "아니오 (미리보기)"}\n')
    hit = 0
    for key, up in UPDATES.items():
        row = conn.execute(
            "SELECT * FROM improvement_issues WHERE issue_key=? "
            "AND status='open'", (key,)).fetchone()
        if not row:
            print(f'  · {key} — 열린 항목 없음 (건너뜀)')
            continue
        hit += 1
        print(f"  ■ {key} [{row['severity']}] {row['title']}")
        # 기한을 그대로 두는 이슈는 **그 기한**을 검토일로 삼는다
        new_eta = row['eta'] if up.get('keep_eta') else up['eta']
        new_rev = up.get('next_review') or new_eta
        print(f"     지금 next_review={row['next_review']} · eta={row['eta']}")
        print(f"     → next_review={new_rev} · eta={new_eta}"
              + ('  (기한 유지)' if up.get('keep_eta') else ''))
        print(f"     붙일 근거: {up['note'][:90]}…")
        if apply:
            conn.execute(
                "UPDATE improvement_issues SET verification=?, "
                "next_review=?, eta=?, escalated_at=? WHERE issue_id=?",
                (up['note'], new_rev, new_eta,
                 datetime.now(timezone.utc).isoformat(), row['issue_id']))
    if apply:
        conn.commit()
        print(f'\n  {hit}건 갱신했습니다.')
    else:
        print(f'\n  {hit}건이 대상입니다. 적용하려면 --apply 를 붙이세요.')
    print('\n  ⚠️ 어느 것도 resolved 로 바꾸지 않았습니다 — 셋 다 목표 '
          '미달입니다.')
    conn.close()
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
