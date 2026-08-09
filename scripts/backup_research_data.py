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

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(PROJ, '.portfolio')

#: 넣을 것 — 전부 연구 산출물이다
INCLUDE = ('virtual_graded.jsonl', 'bar_paths_s*.jsonl',
           'entry_anchors_s*.jsonl', 'subscore_patch*.jsonl',
           'breakout_flags_s*.jsonl', 'calibration.json',
           'cohort_registry_r46.json', '*_r*.json',
           # 전방 기록 — 8/23 재평가의 핵심 자료다. 개장 전 동결 추천과
           # 예측 로그가 없으면 "그때 무엇을 추천했는가"를 되돌릴 수 없다.
           'premarket_*.json', 'predictions.jsonl')

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
    out_dir = os.path.join(PROJ, '_archive')
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
    sys.exit(main())
