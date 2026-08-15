# -*- coding: utf-8 -*-
"""관측 연구 산출물이 **낡았는지** 값으로 판정한다 (라운드 102).

■ 왜 필요한가 — 이 저장소가 세 번 밟은 함정
    라운드 77  전방 기록기가 자동으로 안 돌아 "사람이 앱을 띄운 날만" 쌓였다
    라운드 96  개선 파이프라인이 앱 버튼으로만 돌아 8/8 에 멈춰 있었다
    라운드 102 FN/FP 연구(miss_study)와 취약구간 지도(weakness_map)가
               일일 워크플로에 **한 번도 없었다** — 실측 0회 등장

  셋 다 "도구는 있는데 아무도 안 부른다" 였다. 그런데 더 나쁜 것은
  **멈춘 것을 알아챌 방법이 없었다**는 점이다. 두 산출물은 만든 날짜를
  `made='2026-08-10'` 으로 **박아 두고** 있어서, 다시 만들어도 날짜가
  안 바뀌었다. 낡음이 눈에 보이지 않으면 자동화는 있으나 마나다.

■ 무엇을 판정하나
  각 산출물이 **원장 몇 줄일 때** 만들어졌는지(ledger_rows)를 지금 원장과
  견준다. 원장은 늘기만 하므로, 차이가 곧 밀린 양이다.

  · 산출물이 없다        → 실패 (한 번도 안 돌았다)
  · ledger_rows 가 없다  → 실패 (옛 규약 — 낡음을 판정할 수 없다)
  · 밀린 양 > 허용치     → 실패
  · 0건을 봤다           → 실패 (미측정을 통과로 찍지 않는다)

■ 허용치는 어디서 오나 (§2 — 감으로 고르지 않는다)
  일일 워크플로가 하루에 쌓는 양이 기준이다. 실측으로 하루 +400건 안팎이
  들어온다(라운드 96 클라우드 검증). 하루치까지는 정상 시차로 본다.
  이틀 넘게 벌어지면 파이프라인이 안 도는 것이다.

    C:/Python314/python.exe scripts/study_freshness.py
"""
import io
import json
import os
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(PROJ, '.portfolio', 'virtual_graded.jsonl')

#: 하루 축적량(실측 ~400건)의 두 배. 새 숫자를 고른 게 아니라 이미
#: 관측된 일일 증분에서 유도한다.
MAX_LAG = 800

#: 판정 대상 — 자동으로 돌아야 하는 관측 연구 산출물
STUDIES = (
    ('data/miss_study.json', 'FN/FP 연구 (라운드 67)'),
    ('data/weakness_map.json', '취약구간 지도 (라운드 69)'),
)


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def ledger_rows(path=LEDGER):
    n = 0
    if not os.path.exists(path):
        return 0
    with open(path, encoding='utf-8', errors='replace') as f:
        for ln in f:
            if ln.strip():
                n += 1
    return n


def check(studies=STUDIES, max_lag=MAX_LAG):
    now = ledger_rows()
    print(f'원장 {now:,}줄 · 허용 밀림 {max_lag:,}줄')
    if now == 0:
        print('>> 못 쟀다 — 원장이 0줄이다. 판정하지 않는다.')
        return 2

    if not studies:
        print('>> 못 쟀다 — 판정 대상이 0개다.')
        return 2

    bad, seen = [], 0
    for rel, label in studies:
        seen += 1          # **본 것**을 센다 — 읽는 데 성공한 것이 아니라
        p = os.path.join(PROJ, rel)
        if not os.path.exists(p):
            print(f'  [없음] {label} — {rel} 이 없다 (한 번도 안 돌았다)')
            bad.append(rel)
            continue
        try:
            with open(p, encoding='utf-8') as f:
                doc = json.load(f)
        except Exception as exc:                               # noqa: BLE001
            print(f'  [깨짐] {label} — {type(exc).__name__}')
            bad.append(rel)
            continue
        rows = doc.get('ledger_rows')
        if rows is None:
            print(f'  [옛규약] {label} — ledger_rows 가 없다. '
                  f'낡음을 판정할 수 없다 (made={doc.get("made")})')
            bad.append(rel)
            continue
        lag = now - int(rows)
        mark = 'OK  ' if lag <= max_lag else 'FAIL'
        print(f'  [{mark}] {label} — 원장 {int(rows):,}줄일 때 만듦 · '
              f'밀림 {lag:,}줄 · made={doc.get("made")}')
        if lag > max_lag:
            bad.append(rel)

    # ⚠️ 라운드 102 — 여기서 내가 한 번 틀렸다. `seen` 을 '읽는 데 성공한
    #   개수'로 세는 바람에, 산출물이 **없을 때** seen==0 이 되어 '못 쟀다'
    #   로 빠졌다. 파일이 없는 것은 재 본 결과 없는 것이지 못 잰 게 아니다.
    #   "못 봤다" 와 "보니 없다" 를 섞으면 한 번도 안 돈 상태가 통과로
    #   찍힌다 — 이 파일이 막으려던 바로 그 사고다.
    if seen == 0:
        print('\n>> 못 쟀다 — 본 산출물이 0개다. 판정하지 않는다.')
        return 2
    if bad:
        print(f'\n>> 낡았거나 없다: {bad}')
        print('   자동으로 도는 연구가 멈춰 있다는 뜻이다. '
              '워크플로에 걸려 있는지 본다.')
        return 1
    print(f'\n>> 통과 — {seen}개 산출물 전부 최신이다.')
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(check())
