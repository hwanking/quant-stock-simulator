# -*- coding: utf-8 -*-
"""
연구 데이터 백업 꾸러미 만들기 (라운드 68).

■ 왜
  원장·경로 189MB 가 이 PC 에만 있다. 디스크가 죽으면 6만 건이 사라지고,
  다른 곳에서 이어서 작업할 수도 없다.

■ 무엇을 넣고 무엇을 뺀다 (화이트리스트)
  **개인 자료는 이름이 아니라 목록으로 막는다.** 나중에 보유종목 파일이
  생겨도 이 목록에 없으면 애초에 들어가지 않는다 (§9).

    포함: 원장 · 경로 · 진입 기준선 · 하위점수 패치 · 돌파 플래그 ·
          연구 산출 json (라운드별 결과)
    제외: positions*.json · holdings* · *.secret* · 그 밖 전부

    C:/Python314/python.exe scripts/backup_research_data.py
    → _archive/research_data_YYYYMMDD.zip (gitignored)
       gh release create data-YYYYMMDD <zip> 로 올린다
"""
import fnmatch
import io
import os
import sys
import zipfile
from datetime import date

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(PROJ, '.portfolio')
#: 만든 zip 을 두는 곳. **pull_research_data.INBOX 와 달라야 한다** —
#: 같으면 받은 zip 이 방금 만든 백업을 덮어쓴다 (라운드 97b 실사고).
OUT_DIR = os.path.join(PROJ, '_archive')


def _utf8_stdout():
    """스크립트로 돌 때만 stdout 을 UTF-8 로 맞춘다.

    모듈 수준에서 stdout 을 새 TextIOWrapper 로 갈아끼우면, 이 파일을
    **임포트하는 쪽**(회귀 §107)의 stdout 까지 바뀐다. 옛 래퍼가 수거될
    때 버퍼를 닫아 그 뒤 출력이 통째로 죽는다. 오늘 이 함정을 세 번
    밟았다 (lineage_audit · snapshot_guard · 여기).
    """
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

#: 넣을 것 — 전부 연구 산출물이다
INCLUDE = ('virtual_graded.jsonl',
           # ⚠️ 라운드 71c — 이게 빠져 있어서 클라우드 원장이 깎였다.
           # `virtual_graded.jsonl` 은 **산출물**이고, calibration_lab 은
           # 매 실행마다 원본(`virtual_predictions.jsonl`)을 전부 다시
           # 채점해 산출물을 통째로 덮어쓴다(open(..., 'w')). 원본을 안
           # 담아 두면 클라우드는 매일 그 회차 400건만 가진 원장을 새로
           # 만들어 좋은 스냅샷 위에 올린다. 실제로 60,462건 → 400건이
           # 됐다. 산출물만 지키면 안 되고 **원본을 지켜야** 한다.
           # 별표가 붙어 있어야 샤드(virtual_predictions_s1.jsonl …)까지
           # 담긴다. 라운드 72 에서 샤딩을 붙이고 정확한 이름만 적어 뒀다가
           # 신규 121,497건이 통째로 백업에서 빠질 뻔했다 — 71c 와 같은 사고다.
           'virtual_predictions*.jsonl',
           'bar_paths_s*.jsonl',
           'entry_anchors_s*.jsonl', 'subscore_patch*.jsonl',
           'breakout_flags_s*.jsonl', 'calibration.json',
           'cohort_registry_r46.json', '*_r*.json',
           # 전방 기록 — 재평가(2026-11-16)의 핵심 자료다. 개장 전 동결
           # 추천과 예측 로그가 없으면 "그때 무엇을 추천했는가"를 되돌릴 수
           # 없다.
           'premarket_*.json', 'predictions.jsonl',
           # ⚠️ 라운드 97 — 전방 기록부(fr-1 규약). predictions.jsonl 은
           #   필드가 11개뿐이라 "어느 엔진이 · 어느 가격 기준으로" 를
           #   답할 수 없다. 11/16 재평가는 **이 파일**을 읽는다.
           #   여기 안 넣으면 클라우드가 매일 새로 만들고 매일 잃는다.
           'forward_registry.jsonl',
           # ⚠️ 라운드 78 — 유니버스 목록도 지켜야 한다. 없으면 클라우드가
           # **매일 그 날의 시총으로 종목을 새로 고른다.** 전방 구간에서
           # 그건 속도 문제가 아니라 방법론 문제다 — 동결(2026-08-09) 이후
           # 순위로 표본을 고르면 그 사이 오른 종목이 들어오고 빠진 종목이
           # 나간다. 전방 표본은 **동결 시점 목록으로 고정**해야 한다.
           # 지금 박제된 것은 2026-08-10 자 3,014종목이다.
           'universe_top*.json',
           'news_events.jsonl',          # 뉴스 사건 사후 경로 (라운드 70)
           # ⚠️ 라운드 93 — 되받는 스크립트를 만들다 **화이트리스트 밖에
           #   13개(약 18MB)가 있는 것**을 알았다. 전부 다시 돌려야 만들거나
           #   아예 못 만드는 것들인데, 원리적으로 영영 안 올라가고 있었다.
           #   (같은 라운드에서 subscore 131,879줄이 사본 없이 이 PC 에만
           #   있던 것도 찾았다 — 그건 목록엔 있었는데 안 올라간 경우다.)
           #
           #   넓히되 **화이트리스트 방식은 유지한다.** `*.json` 처럼 통째로
           #   여는 순간 이 파일 머리말의 약속("나중에 보유종목 파일이
           #   생겨도 목록에 없으면 애초에 안 들어간다")이 깨진다.
           'virtual_paths.jsonl', 'virtual_levels.jsonl',
           'premarket_history.jsonl',
           '*_policy.json',              # target · stop · rr
           'regime_*.json',              # regime_engine · regime_breakdown
           'sideways_study.json', 'engine_bakeoff.json',
           'us_overnight.json', 'version_compare.json', 'llm_watch.json',
           # 개선 이슈 등록부 — 다시 못 만든다. sqlite 라 내용 검사가 못
           # 읽으므로 스키마를 직접 훑어 확인했다: 6개 테이블 전부 모델·
           # 이슈·파이프라인 자료이고 평단·수량·자격증명 열쇠가 없다.
           # (holding_days 는 **보유기간**이지 보유종목이 아니다.)
           'improvement.db')

#: 절대 넣지 않을 것 — 개인 자료 (INCLUDE 에 걸려도 여기서 잘린다)
DENY = ('positions*', 'holdings*', '*secret*', '*credential*',
        '*.env', '*token*')


def picked(name):
    if any(fnmatch.fnmatch(name, d) for d in DENY):
        return False
    return any(fnmatch.fnmatch(name, i) for i in INCLUDE)


def main():
    if not os.path.isdir(P):
        print('.portfolio 가 없습니다.')
        return 1
    out_dir = OUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    stamp = date.today().strftime('%Y%m%d')
    dst = os.path.join(out_dir, f'research_data_{stamp}.zip')

    files = sorted(f for f in os.listdir(P) if picked(f))
    denied = sorted(f for f in os.listdir(P) if not picked(f))
    raw = sum(os.path.getsize(os.path.join(P, f)) for f in files)
    print(f'포함 {len(files)}개 · 원본 {raw / 1048576:,.1f}MB')
    with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED,
                         compresslevel=9) as z:
        for f in files:
            z.write(os.path.join(P, f), arcname=f'.portfolio/{f}')
    got = os.path.getsize(dst)
    print(f'압축 {got / 1048576:,.1f}MB ({got / max(1, raw) * 100:.0f}%) → {dst}')
    if denied:
        print(f'\n제외 {len(denied)}개 (화이트리스트 밖):')
        for f in denied[:8]:
            print(f'  {f}')
    print('\n올리기:')
    print(f'  gh release create data-{stamp} "{dst}" '
          f'--title "연구 데이터 {stamp}" --notes "원장·경로·기준선 스냅샷"')
    print('내려받기 (다른 PC):')
    print(f'  gh release download data-{stamp} -D .')
    return 0


if __name__ == '__main__':
    _utf8_stdout()
    sys.exit(main())
