# -*- coding: utf-8 -*-
"""
섹터별 선행지표 표를 **코드에서 생성**한다 → docs/SECTOR_INDICATORS_ko.md

손으로 쓴 표는 코드와 어긋난다. 정본은 `sector_cycle.GROUPS` 하나다.

    C:/Python314/python.exe scripts/gen_sector_table.py
"""
import io
import os
import sys

try:                       # 라운드 103 — 객체를 갈아끼우지 않는다
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:          # noqa: BLE001
    pass
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import sector_cycle as sc                                    # noqa: E402

OUT = os.path.join(BASE, 'docs', 'SECTOR_INDICATORS_ko.md')

HEAD = """# 섹터별 선행지표 — 무엇을 보고 있고, 무엇을 못 보고 있나

> 이 파일은 `scripts/gen_sector_table.py` 가 `sector_cycle.GROUPS` 에서
> **생성**합니다. 직접 고치지 마세요 — 코드를 고치고 다시 생성하세요.

## 읽는 법

각 업종에는 이익과 주가를 실제로 움직이는 **진짜 선행지표**가 있습니다.
이 시스템이 지금 받고 있는 것은 대부분 그것이 아니라 **대용 지표(프록시)**
입니다. 둘을 섞어 부르지 않기 위해 표를 갈라 놓았습니다.

- **프록시** — 지금 실제로 수신 중인 값. 업황의 방향을 대략 봅니다
- **연동된 진짜 지표** — 원지표를 직접 받고 있는 것
- **미연동** — 공개 무료 소스가 없거나 유료라 아직 못 받는 것

### 지금 이 값들은 적정가에 반영되지 않습니다

라운드 44에서 프록시 모멘텀이 국내 종목의 20봉 결과를 예측하는지
원장 16,805건으로 실측했고, **사전등록 게이트를 넘지 못해 기각**했습니다.
특히 `mom60`(프록시 절대 모멘텀)은 블라인드에서 **방향이 반대**였습니다 —
호황 구간 적중 50.0% · 비용후 EV −2.467%.

그래서 업황은 **화면에 보여 주기만** 하고 적정가·점수·판정에는 넣지
않습니다. 근거는 `docs/PREREG_R44_SECTOR_OVERLAY.md` 와
`docs/MODEL_VERSIONS.md` 라운드 44 절에 있습니다.

---

"""


def main():
    lines = [HEAD]
    n_real = n_link = 0

    # 열을 섞지 않는다. `real_linked` 에는 그 업종 고유 지표가 아니라
    # 매크로 축(환율·유가·구리)이 들어 있어서, 한 칸에 합치면
    # "4종 중 연동 1 · 미연동 4" 같은 셈이 안 맞는 줄이 나온다.
    n_macro = 0
    lines.append('## 요약\n')
    lines.append('| 업종 | 프록시 | 업종 고유 지표 | 그중 연동 | 매크로 간접 |')
    lines.append('|---|---|---:|---:|---|')
    for _, g in sc.GROUPS.items():
        real = list(g['real'])
        linked_set = set(g['real_linked'])
        link = [x for x in real if x in linked_set]
        macro = [x for x in g['real_linked'] if x not in set(real)]
        n_real += len(real)
        n_link += len(link)
        n_macro += len(macro)
        lines.append(f"| {g['ko']} | {' · '.join(g['proxy'])} | "
                     f"{len(real)} | {len(link)} | "
                     f"{('· '.join(macro) if macro else '—')} |")
    lines.append('')
    lines.append(f'**업종 고유 선행지표 {n_real}종 중 {n_link}종 연동** '
                 f'({n_link / max(1, n_real) * 100:.0f}%). '
                 f'운임지수·재고·스프레드·수주잔고처럼 그 업종의 이익을 실제로 '
                 f'가르는 지표는 공개 무료 소스가 없거나 유료라 **하나도 받고 '
                 f'있지 않습니다.**\n')
    lines.append(f'따로 받는 것은 매크로 축 {n_macro}건(환율·유가·구리)뿐이고, '
                 f'이것도 업종 고유 지표의 대체물이 아닙니다.\n')
    lines.append('---\n')

    for code, g in sc.GROUPS.items():
        lines.append(f"## {g['ko']} (`{code}`)\n")
        lines.append(f"**프록시** `{'` · `'.join(g['proxy'])}` "
                     f"(벤치 `{g['bench']}`)\n")
        lines.append(f"> {g['proxy_note']}\n")
        linked = set(g['real_linked'])
        lines.append('| 진짜 선행지표 | 상태 |')
        lines.append('|---|---|')
        for r in g['real']:
            lines.append(f"| {r} | {'연동' if r in linked else '**미연동**'} |")
        for x in g['real_linked']:
            if x not in set(g['real']):
                lines.append(f'| {x} (매크로 축) | 연동 |')
        lines.append('')

    lines.append('---\n')
    lines.append('## 업종 매칭\n')
    imap = sc.industry_map()
    if imap:
        inds = sorted(set(imap.values()))
        un = [i for i in inds if not sc.group_of(i)]
        lines.append(f'KRX 업종 분류 **{len(inds)}종** 중 '
                     f'**{len(inds) - len(un)}종**이 프록시에 연결됩니다 '
                     f'({(len(inds) - len(un)) / max(1, len(inds)) * 100:.0f}%).\n')
        lines.append(f'미연동 {len(un)}종은 **조정하지 않고 "미연동"으로 '
                     f'표시**합니다 — 미연동을 중립(0%)으로 바꾸면, 못 잰 것을 '
                     f'잰 것처럼 보이게 됩니다.\n')
        lines.append('<details><summary>미연동 업종 전체</summary>\n')
        for i in un:
            lines.append(f'- {i}')
        lines.append('\n</details>\n')
    else:
        lines.append('업종 분류를 받지 못해 매칭 현황을 낼 수 없습니다.\n')

    lines.append('---\n')
    lines.append('## 매크로 축\n')
    lines.append('| 축 | 티커 | 상태 |')
    lines.append('|---|---|---|')
    for t, ko, _ in sc.MACRO:
        got = sc.series(t)
        lines.append(f"| {ko} | `{t}` | {'연동' if got else '**미수신**'} |")
    lines.append('\n미국채 10년(`US10YT=X`)은 44-0 점검에서 HTTPError 로 '
                 '미수신이라 아예 넣지 않았습니다.\n')

    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'생성: {OUT}')
    print(f'  업종 그룹 {len(sc.GROUPS)}개 · 진짜 지표 {n_real}종 중 '
          f'{n_link}종 연동')


if __name__ == '__main__':
    main()
