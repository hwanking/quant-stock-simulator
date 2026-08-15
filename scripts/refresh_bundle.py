# -*- coding: utf-8 -*-
"""배포 동봉본을 최신으로 맞춘다 (라운드 108).

■ 무엇이 문제였나
  `.portfolio/` 는 gitignore 라 **배포 환경(Streamlit Cloud)에 없다.**
  `web_app._artifact_path` 는 `.portfolio` → `data` 순으로 찾으므로,
  배포에서는 저장소에 커밋된 `data/` 동봉본을 읽는다.

  그런데 동봉본이 **2026-08-02 에 멈춰 있었다.** 그 사이 원장은
  6,508 → 184,759 건으로 자랐다. 배포 화면은 실제 표본의 **3.5%** 로
  계산된 숫자를 최신인 양 보여 주고 있었다.

  더 나쁜 것은 그 숫자가 **모델에 유리한 쪽**이었다는 점이다:

      고신뢰(65+)      실제        배포(옛 동봉본)
      표본 n           588         45
      비용후 수익      -0.43       -0.10
      Profit Factor    1.04        1.17
      Wilson 하한      56.0        47.6

  §9 — 성과를 좋게 보이게 쓰지 않는다. 우연이라도 그렇게 되면 고친다.

■ 무엇을 동봉하나 / 안 하나
  · calibration.json  — **집계표(7.7KB)라 통째로** 동봉한다. 이게 화면
    숫자의 출처다.
  · virtual_graded.jsonl — 원장 전체는 171MB 라 커밋할 수 없다.
    **표본을 동봉하되 몇 건인지 밝힌다** (지어내지 않는다 · §3).
    표본은 최근 것부터 고른다 — 케이스 화면이 최근 사례를 보여 준다.

    C:/Python314/python.exe scripts/refresh_bundle.py            (미리보기)
    C:/Python314/python.exe scripts/refresh_bundle.py --apply
"""
import io
import json
import os
import shutil
import sys
from datetime import date

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = os.path.join(PROJ, '.portfolio')
BUNDLE = os.path.join(PROJ, 'data')

#: 원장 표본 줄 수. 지금 동봉본(6,508)과 같은 규모를 유지한다 —
#: 새 숫자를 고른 게 아니라 이미 커밋돼 있던 크기를 그대로 쓴다.
LEDGER_SAMPLE = 6508


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def _count(path):
    n = 0
    if not os.path.exists(path):
        return 0
    with open(path, encoding='utf-8', errors='replace') as f:
        for ln in f:
            if ln.strip():
                n += 1
    return n


def plan():
    out = []
    live_cal = os.path.join(LIVE, 'calibration.json')
    bun_cal = os.path.join(BUNDLE, 'calibration.json')
    if os.path.exists(live_cal):
        lv = json.load(open(live_cal, encoding='utf-8'))
        bv = (json.load(open(bun_cal, encoding='utf-8'))
              if os.path.exists(bun_cal) else {})
        out.append(('calibration.json', bv.get('total_cases'),
                    lv.get('total_cases')))
    live_led = os.path.join(LIVE, 'virtual_graded.jsonl')
    bun_led = os.path.join(BUNDLE, 'virtual_graded.jsonl')
    if os.path.exists(live_led):
        out.append(('virtual_graded.jsonl', _count(bun_led),
                    _count(live_led)))
    return out


def main():
    rows = plan()
    if not rows:
        print('.portfolio 에 원본이 없다 — 동봉본을 만들 수 없다.')
        return 2
    print('■ 동봉본 vs 실제')
    for name, cur, live in rows:
        print(f'   {name:<26} 동봉 {str(cur):>9} · 실제 {live:>9,}')

    if '--apply' not in sys.argv:
        print('\n(미리보기) --apply 를 주면 실제로 갱신한다.')
        return 0

    # ① 집계표는 통째로 (작다)
    src = os.path.join(LIVE, 'calibration.json')
    dst = os.path.join(BUNDLE, 'calibration.json')
    shutil.copyfile(src, dst)
    n_cal = json.load(open(dst, encoding='utf-8')).get('total_cases')
    print(f'\n집계표 갱신 — total_cases {n_cal:,}')

    # ② 원장은 표본만. **몇 건 중 몇 건인지 같이 남긴다** (§3)
    live_led = os.path.join(LIVE, 'virtual_graded.jsonl')
    total = _count(live_led)
    keep = []
    with open(live_led, encoding='utf-8', errors='replace') as f:
        for ln in f:
            if ln.strip():
                keep.append(ln)
                if len(keep) > LEDGER_SAMPLE:
                    keep.pop(0)          # 최근 것만 남긴다
    with open(os.path.join(BUNDLE, 'virtual_graded.jsonl'), 'w',
              encoding='utf-8', newline='') as f:
        f.writelines(keep)
    meta = {
        'made': date.today().isoformat(),
        'sample_rows': len(keep),
        'ledger_rows_at_bundle': total,
        'note': ('배포 동봉용 표본이다. 원장 전체는 저장소에 넣지 않는다'
                 '(용량). 화면은 이것이 표본임을 밝혀야 한다 — 전체인 척'
                 '하면 §3·§9 위반이다.'),
    }
    with open(os.path.join(BUNDLE, 'bundle_meta.json'), 'w',
              encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print(f'원장 표본 갱신 — {len(keep):,}건 / 전체 {total:,}건 '
          f'(bundle_meta.json 에 기록)')
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
