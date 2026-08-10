# -*- coding: utf-8 -*-
"""
라운드 71c — 스냅샷 축소 방지 (클라우드 축적이 데이터를 깎지 못하게).

■ 무슨 일이 있었나
  일일 축적 워크플로가 이렇게 돌았다:
    ① 지난 스냅샷 복원 (원장 60,462건)
    ② calibration_lab --limit 400
    ③ 새 스냅샷 업로드 (--clobber)
  그런데 ②가 원장을 **통째로 다시 쓴다** — 원본(virtual_predictions.jsonl)
  을 전부 재채점해 virtual_graded.jsonl 을 open(...,'w') 로 덮는다.
  그 원본이 백업 화이트리스트에 없어서 클라우드에는 없었다. 결과:
  원장이 400건짜리로 새로 만들어졌고, 그게 좋은 스냅샷을 덮었다.

  화이트리스트는 고쳤다. 그런데 **고쳤다는 것만으로는 부족하다** —
  같은 종류의 사고(무언가가 파일을 재생성하며 줄이는)는 또 날 수 있고,
  그때도 조용히 덮어쓰기가 성공할 것이다. 그래서 자물쇠를 건다.

■ 무엇을 하나
    --record : 복원 직후 주요 파일의 줄 수를 기록한다
    --verify : 업로드 직전에 다시 세서 **줄어들었으면 실패**한다
  줄어드는 것이 정당한 경우(사람이 의도한 정리)는 --allow-shrink 로 넘긴다.
  기본은 막는다 — 축적 작업이 데이터를 줄일 이유가 없다.

    python scripts/snapshot_guard.py --record
    python scripts/snapshot_guard.py --verify
"""
import glob
import io
import json
import os
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(PROJ, '.portfolio')
BASE = os.path.join(P, '_snapshot_baseline.json')


def _utf8_stdout():
    """스크립트로 돌 때만 stdout 을 UTF-8 로 맞춘다.

    모듈 수준에서 `sys.stdout = TextIOWrapper(sys.stdout.buffer, ...)` 를
    하면 임포트하는 쪽의 stdout 까지 갈아끼우고, 옛 래퍼가 수거될 때
    버퍼를 닫아 그 뒤 출력이 통째로 죽는다. 같은 실수를 오늘 두 번 했다
    (lineage_audit.py · 여기). reconfigure 는 같은 객체를 고친다.
    """
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

#: 줄어들면 안 되는 축적 파일 (append-only 이거나 재생성되더라도 커져야 한다)
WATCH = ('virtual_predictions*.jsonl', 'virtual_graded.jsonl',
         'bar_paths_s*.jsonl', 'entry_anchors_s*.jsonl',
         'subscore_patch*.jsonl', 'breakout_flags_s*.jsonl',
         'news_events.jsonl', 'predictions.jsonl')


def counts():
    """패턴별 총 줄 수 — 샤드가 늘거나 줄어도 합으로 본다."""
    out = {}
    for pat in WATCH:
        total, files = 0, 0
        for path in sorted(glob.glob(os.path.join(P, pat))):
            files += 1
            with open(path, encoding='utf-8', errors='replace') as f:
                total += sum(1 for ln in f if ln.strip())
        out[pat] = dict(lines=total, files=files)
    return out


def record():
    if not os.path.isdir(P):
        print('.portfolio 가 없다 — 기록할 것이 없다.')
        return 0
    c = counts()
    with open(BASE, 'w', encoding='utf-8') as f:
        json.dump(c, f, ensure_ascii=False, indent=1)
    print('■ 복원 직후 기준선')
    for k, v in c.items():
        print(f"  {k:30s} {v['lines']:>9,}줄 · 파일 {v['files']}")
    print(f'저장: {BASE}')
    return 0


def verify(allow_shrink=False):
    if not os.path.exists(BASE):
        # 기준선이 없으면 비교할 수 없다. 통과로 적지 않는다 (§3).
        print('기준선이 없다 — 축소 여부를 확인하지 못했다. '
              '통과가 아니라 미측정이다.')
        return 1
    with open(BASE, encoding='utf-8') as f:
        before = json.load(f)
    after = counts()
    print('■ 업로드 직전 대조 (복원 직후 → 지금)')
    shrunk = []
    for k in sorted(set(before) | set(after)):
        b = (before.get(k) or {}).get('lines', 0)
        a = (after.get(k) or {}).get('lines', 0)
        mark = ''
        if a < b:
            shrunk.append((k, b, a))
            mark = '  ← 줄었다'
        print(f'  {k:30s} {b:>9,} → {a:>9,} ({a - b:+,}){mark}')
    if not shrunk:
        print('축소 없음 — 업로드해도 좋다.')
        return 0
    print(f'\n축소 {len(shrunk)}건:')
    for k, b, a in shrunk:
        print(f'  {k} — {b:,}줄이 {a:,}줄이 됐다')
    if allow_shrink:
        print('--allow-shrink 가 켜져 있어 그대로 진행한다.')
        return 0
    print('\n업로드를 막는다. 축적 작업이 데이터를 줄일 이유가 없다 — '
          '줄었다면 재생성이 원본을 못 찾았을 가능성이 높다.')
    return 1


if __name__ == '__main__':
    _utf8_stdout()
    if '--verify' in sys.argv:
        sys.exit(verify(allow_shrink='--allow-shrink' in sys.argv))
    sys.exit(record())
