# -*- coding: utf-8 -*-
"""원장에서 사라진 종목의 채점 행을 **백업에서 되살린다** (라운드 197).

왜 필요한가
  `calibration_lab.py` 는 원장(`virtual_graded.jsonl`)을 매 실행 통째로
  다시 쓴다. 채점 루프는 시세를 못 받은 종목을 `continue` 로 건너뛰므로,
  **그 종목의 모든 케이스가 조용히 사라진 채 원장이 덮어써진다.**

  실측(2026-09-01): 다음 API 가 HTTP 500 을 내 10종목의 시세를 못 받았고
  원장이 184,759 → 183,787 로 **977건 줄었다.** 로그는 성공으로 끝났다.
  그 10종목은 재실행에서도, 직접 조회에서도 계속 실패한다 — 일시적
  장애가 아니라 그 코드로는 더 이상 받을 수 없는 것으로 보인다.

  다행히 `_archive/research_data_*.zip` 백업에 그때의 채점 행이 있다.
  **다시 못 재는 것과 없던 일로 하는 것은 다르다** — 되살린다.

무엇을 하나
  백업 zip 안의 원장에서 **현재 원장에 없는 티커**의 행만 뽑아 덧붙인다.
  덧붙인 행에는 `carried_over: True` 와 `carried_from` 을 찍는다 —
  이번 실행에서 다시 채점되지 않았다는 사실을 분석이 볼 수 있어야 한다(§3).

실행:
  C:/Python314/python.exe scripts/restore_graded_from_backup.py            (미리보기)
  C:/Python314/python.exe scripts/restore_graded_from_backup.py --write    (적용)
"""
import io
import json
import os
import sys
import zipfile

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(PROJ, '.portfolio', 'virtual_graded.jsonl')
ARCH = os.path.join(PROJ, '_archive')
MEMBER = '.portfolio/virtual_graded.jsonl'


def _tickers(path):
    seen = set()
    with io.open(path, encoding='utf-8') as f:
        for line in f:
            if not line.strip():
                continue
            i = line.find('"ticker"')
            if i < 0:
                continue
            seg = line[i + 9:i + 40]
            a = seg.find('"')
            b = seg.find('"', a + 1)
            if a >= 0 and b > a:
                seen.add(seg[a + 1:b])
    return seen


def newest_backup():
    zips = [os.path.join(ARCH, f) for f in os.listdir(ARCH)
            if f.startswith('research_data_') and f.endswith('.zip')]
    return max(zips, key=os.path.getmtime) if zips else None


def main(write=False):
    if not os.path.exists(LEDGER):
        print('원장이 없다 — 할 일 없음')
        return 1
    zp = newest_backup()
    if not zp:
        print('백업 zip 이 없다 — 되살릴 곳이 없다')
        return 1
    cur = _tickers(LEDGER)
    n_cur = sum(1 for l in io.open(LEDGER, encoding='utf-8') if l.strip())
    print(f'현재 원장 {n_cur:,}행 · 티커 {len(cur):,}개')
    print(f'백업: {os.path.basename(zp)}')

    add, add_tk = [], {}
    z = zipfile.ZipFile(zp)
    with z.open(MEMBER) as f:
        for raw in io.TextIOWrapper(f, encoding='utf-8'):
            if not raw.strip():
                continue
            try:
                r = json.loads(raw)
            except Exception:
                continue
            t = r.get('ticker')
            if not t or t in cur:
                continue
            r['carried_over'] = True
            r['carried_from'] = os.path.basename(zp)
            add.append(r)
            add_tk[t] = add_tk.get(t, 0) + 1

    print(f'되살릴 행 {len(add):,}건 · 티커 {len(add_tk)}개')
    for t in sorted(add_tk):
        print(f'   {t}  {add_tk[t]}건')
    if not add:
        print('되살릴 것이 없다')
        return 0
    if not write:
        print('\n미리보기다. 적용하려면 --write')
        return 0
    with io.open(LEDGER, 'a', encoding='utf-8') as f:
        for r in add:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    n_new = sum(1 for l in io.open(LEDGER, encoding='utf-8') if l.strip())
    print(f'\n적용 완료 — 원장 {n_cur:,} → {n_new:,}행')
    return 0


if __name__ == '__main__':
    sys.exit(main(write='--write' in sys.argv))
