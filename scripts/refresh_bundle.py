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
  · virtual_graded.jsonl — **라운드 282 부터 전체를 눌러서 동봉한다.**

    종전에는 꼬리 6,508행만 실었다(원장 251,528행의 2.6%). 그 규칙으로는
    화면 숫자가 실제와 안 맞고, **더 실어도 안 맞는다** — 꼬리는 생성 순서
    덩어리라 이웃 행이 서로 상관돼(라운드 217) 표본을 늘려도 수렴하지
    않는다. 2026-09-12 실측(닿음 누적의 최대 어긋남, %p):

        꼬리 6,508행  2.0 | 25,000  1.6 | 50,000  2.1
             100,000  1.8 | 150,000 0.8 | 전체   0.0

    그리고 가장 얇은 도달확률 칸의 표본이 20건이었다(전체면 926건).
    **전체를 실어야 맞는다.** 평문 240MB 는 저장소 파일 한도(100MB)를
    넘지만 gzip 으로 31.9MB(13.3%)라 들어간다. 읽는 쪽은
    `web_app._open_artifact` 하나가 가른다.

    ⚠️ 눌러서 싣는 것과 **메모리에 펼치는 것**은 다른 문제다. 케이스 화면이
      통째로 열면 최대 작업집합이 3,424MB 였다(배포 컨테이너 약 1GB) —
      라운드 282 가 그 자리를 나눠 읽기로 바꿔 437MB 로 내렸다. 이 스크립트를
      되돌려 평문 표본으로 돌아가더라도 그 고침은 그대로 둔다.

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

#: 라운드 282 — 원장은 **전부** 싣는다. 표본 줄 수라는 개념이 없어졌다.
#: 대신 저장소가 받아 주는 크기를 못 넘는지 본다(깃허브 파일 한도 100MB ·
#: 우리가 고른 숫자가 아니라 플랫폼이 정한 값이다).
GITHUB_FILE_LIMIT = 100 * 1024 * 1024

#: 눌림 정도. 6 은 파이썬 gzip 기본값이고 실측 13.3% 였다 — 9 로 올려도
#: 몇 %p 줄고 시간이 배로 든다. 기본값을 그대로 쓴다.
GZIP_LEVEL = 6

LEDGER_NAME = 'virtual_graded.jsonl'


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
    live_led = os.path.join(LIVE, LEDGER_NAME)
    if os.path.exists(live_led):
        out.append((LEDGER_NAME, _count_bundle_ledger(), _count(live_led)))
    return out


def _bundle_ledger_path():
    """동봉본 원장이 실제로 있는 자리 — 눌린 것이 먼저다 (라운드 282)."""
    gz = os.path.join(BUNDLE, LEDGER_NAME + '.gz')
    if os.path.exists(gz):
        return gz
    plain = os.path.join(BUNDLE, LEDGER_NAME)
    return plain if os.path.exists(plain) else None


def _count_bundle_ledger():
    p = _bundle_ledger_path()
    if not p:
        return 0
    if p.endswith('.gz'):
        import gzip
        n = 0
        with gzip.open(p, 'rt', encoding='utf-8', errors='replace') as f:
            for ln in f:
                if ln.strip():
                    n += 1
        return n
    return _count(p)


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

    # ② 원장은 **전부** 눌러서. 줄어들면 멈춘다 (라운드 197·245 의 그 가드)
    import gzip

    live_led = os.path.join(LIVE, LEDGER_NAME)
    total = _count(live_led)
    was = _count_bundle_ledger()
    if total < was and '--allow-shrink' not in sys.argv:
        print(f'\n멈춘다 — 원본 {total:,}행이 지금 동봉본 {was:,}행보다 적다.')
        print('  원장은 늘기만 한다는 전제가 깨진 것이다. 원인을 먼저 본다')
        print('  (정말 줄이려면 --allow-shrink).')
        return 3

    gz_path = os.path.join(BUNDLE, LEDGER_NAME + '.gz')
    tmp = gz_path + '.part'
    wrote = 0
    with open(live_led, encoding='utf-8', errors='replace') as src, \
            gzip.open(tmp, 'wt', encoding='utf-8', newline='',
                      compresslevel=GZIP_LEVEL) as dst:
        for ln in src:
            if ln.strip():
                dst.write(ln if ln.endswith('\n') else ln + '\n')
                wrote += 1
    size = os.path.getsize(tmp)
    if size > GITHUB_FILE_LIMIT:
        os.remove(tmp)
        print(f'\n멈춘다 — 눌러도 {size:,}바이트로 저장소 파일 한도'
              f'({GITHUB_FILE_LIMIT:,})를 넘는다. 실을 수 없다.')
        return 4
    if wrote != total:
        os.remove(tmp)
        print(f'\n멈춘다 — 읽은 {total:,}행과 쓴 {wrote:,}행이 다르다.')
        return 5
    os.replace(tmp, gz_path)

    # 평문 표본이 남아 있으면 치운다 — 같은 이름의 출처가 둘이면 언젠가
    # 한쪽만 갱신된다 (§4). `_artifact_path` 는 평문을 먼저 잡는다.
    plain = os.path.join(BUNDLE, LEDGER_NAME)
    dropped = os.path.exists(plain)
    if dropped:
        os.remove(plain)

    meta = {
        'made': date.today().isoformat(),
        'sample_rows': wrote,
        'ledger_rows_at_bundle': total,
        'compressed_bytes': size,
        'note': ('라운드 282 부터 원장 **전체**를 눌러서 동봉한다. '
                 'sample_rows 와 ledger_rows_at_bundle 이 같으면 표본이 '
                 '아니라 전량이라는 뜻이다. 다르면 표본이고, 화면은 그것을 '
                 '밝혀야 한다 — 전체인 척하면 §3·§9 위반이다.'),
    }
    with open(os.path.join(BUNDLE, 'bundle_meta.json'), 'w',
              encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print(f'\n원장 동봉 갱신 — {wrote:,}건 / 전체 {total:,}건 · '
          f'{size:,}바이트(평문 {os.path.getsize(live_led):,})')
    if dropped:
        print(f'  평문 표본 {plain} 은 지웠다 — 출처는 하나다')
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
