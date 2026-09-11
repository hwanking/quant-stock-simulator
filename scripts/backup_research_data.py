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
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)
from scripts import study_freshness as _fresh                  # noqa: E402

P = os.path.join(PROJ, '.portfolio')
#: 만든 zip 을 두는 곳. **pull_research_data.INBOX 와 달라야 한다** —
#: 같으면 받은 zip 이 방금 만든 백업을 덮어쓴다 (라운드 97b 실사고).
OUT_DIR = os.path.join(PROJ, '_archive')
#: 두 번째 뿌리 — `data/` 의 관측 산출물 (라운드 261). 클라우드가 매 평일 만드는
#: 다섯(FN/FP · 취약구간 · 표본 감사 · ICC · 업종 성적)이 여기 없어서 신선도 검사를
#: 통과한 직후 작업 컨테이너와 함께 버려졌다 — 라운드 259 의 *"만든 것이 올라가야
#: 화면에 닿는다"* 가 이 자리에서 끊겨 있었다(화면은 git 의 `data/` 를 읽는다).
DATA_DIR = os.path.join(PROJ, 'data')


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

#: `data/` 에서 실을 것 — **손으로 적지 않는다.** 신선도 검사가 보는 목록
#: (`study_freshness.STUDIES`)에서 유도한다: 검사가 보는 것이 곧 실어 나르는 것이다.
#: 한쪽에 넣고 다른 쪽을 잊는 날이 없다(R114 · 손 목록은 낡는다). 와일드카드가 아니라
#: 이름이다 — `*.json` 처럼 열면 머리말의 약속이 깨진다.
DATA_INCLUDE = tuple(os.path.basename(p) for p, _ in _fresh.STUDIES)


def picked(name):
    if any(fnmatch.fnmatch(name, d) for d in DENY):
        return False
    return any(fnmatch.fnmatch(name, i) for i in INCLUDE)


def picked_data(name):
    """`data/<name>` 을 실을까 — DENY 먼저, 그 다음 유도된 이름 목록 (라운드 261)."""
    if any(fnmatch.fnmatch(name, d) for d in DENY):
        return False
    return name in DATA_INCLUDE


def arcnames(portfolio_dir=P, data_dir=DATA_DIR):
    """백업이 담을 항목의 zip 안 이름 — 두 뿌리 (`.portfolio/…` · `data/…`).

    쓰지 않고 계획만 낸다 — 검사가 실제 목록을 보되 200MB zip 을 만들지 않게.
    """
    out = []
    if os.path.isdir(portfolio_dir):
        out += [f'.portfolio/{f}' for f in sorted(os.listdir(portfolio_dir)) if picked(f)]
    if os.path.isdir(data_dir):
        out += [f'data/{f}' for f in sorted(os.listdir(data_dir)) if picked_data(f)]
    return out


def main():
    if not os.path.isdir(P):
        print('.portfolio 가 없습니다.')
        return 1
    out_dir = OUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    stamp = date.today().strftime('%Y%m%d')
    dst = os.path.join(out_dir, f'research_data_{stamp}.zip')

    arcs = arcnames(P, DATA_DIR)
    files = [a for a in arcs if a.startswith('.portfolio/')]
    dfiles = [a for a in arcs if a.startswith('data/')]
    denied = sorted(f for f in os.listdir(P) if not picked(f))
    raw = sum(os.path.getsize(os.path.join(PROJ, a)) for a in arcs)
    print(f'포함 {len(files)}개 (.portfolio) · 관측 산출물 {len(dfiles)}개 (data · '
          f'라운드 261) · 원본 {raw / 1048576:,.1f}MB')
    if len(dfiles) < len(DATA_INCLUDE):
        # 없는 것은 없다고 찍는다 — 신선도 검사가 맨 뒤에서 잡지만 여기서도 보이게.
        missing = [n for n in DATA_INCLUDE if f'data/{n}' not in dfiles]
        print(f'  ⚠ data/ 관측 산출물 {len(missing)}개가 없어 못 실었다: {", ".join(missing)}')
    with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED,
                         compresslevel=9) as z:
        for a in arcs:
            z.write(os.path.join(PROJ, a), arcname=a)
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
