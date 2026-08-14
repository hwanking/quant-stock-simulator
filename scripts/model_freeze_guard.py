# -*- coding: utf-8 -*-
"""동결 자물쇠 — 자동 실행이 모델을 바꾸지 못하게 (라운드 96).

■ 왜 필요한가
  일일 개선 파이프라인을 클라우드에 붙인다. 그러면 사람이 안 봐도
  매일 돈다 — 그게 목적이다. 그런데 같은 이유로 **사람이 안 보는 사이에
  무언가 바뀌어도 모른다.**

  경계는 분명하다:
      자동 축적·판정  → 허용
      자동 모델 변경  → 금지

  "지금 그 스크립트는 모델을 안 바꾼다"를 읽어서 확인하는 것만으로는
  부족하다. 내일 누가 한 줄 더하면 그만이다. **값으로 잠근다.**

■ 두 가지를 본다
  ⓐ 실행 **전후로** 동결 대상 파일이 바뀌었는가 (--record / --verify)
     바뀌면 실패시킨다. 자동 실행은 이 파일들을 만질 이유가 없다.
  ⓑ 11/16 평가 대상(R55·R57·R66)의 **박제 해시**가 그대로인가
     바뀌면 FORWARD CONTAMINATION RISK 로 알린다. 전방 재평가는
     "그때 정한 것을 그대로" 재는 것이므로, 중간에 바뀌면 평가가 성립하지
     않는다.

■ 안 하는 것
  이 스크립트는 **판단하지 않는다.** 해시가 같은지만 본다. 무엇을
  동결할지는 사람이 아래 목록에 적는다 — 자동으로 늘리면 자물쇠가
  자기가 채운 것만 잠근다.

    python scripts/model_freeze_guard.py --record   (실행 전)
    python scripts/model_freeze_guard.py --verify   (실행 후)
    python scripts/model_freeze_guard.py --pin      (박제 해시 새로 찍기)
    python scripts/model_freeze_guard.py --check    (박제 대조만)
"""
import hashlib
import io
import json
import os
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

STATE = os.path.join(PROJ, '.portfolio', '_freeze_state.json')
PIN = os.path.join(PROJ, 'data', 'freeze_pins.json')

#: ⓐ 자동 실행이 바꾸면 안 되는 것 — 버전·게이트·문턱
#:   (원장·경로·케이스는 **바뀌어야 정상**이므로 여기 없다)
NO_AUTO_CHANGE = (
    'data/version_ledger.json',        # 버전은 사람이 사유와 함께 올린다
    'data/regime_routing_r55.json',    # R55 정책 박제
    'data/entry_engine_r57.json',      # R57 정책 박제
    'regime_policy.py',                # 국면 게이트
    'price_axes.py',                   # 적정가 3축
    'verdict_core.py',                 # 중앙 판정
    'quant_indicators.py',             # 점수 산식·문턱
    'forward_eval.py',                 # 재평가일 단일 출처
)

#: ⓑ 11/16 에 평가할 대상 — 그날까지 한 글자도 안 바뀌어야 한다
FORWARD_TARGETS = (
    'data/regime_routing_r55.json',
    'data/entry_engine_r57.json',
    'docs/PREREG_R55_REGIME_MOE.md',
    'docs/PREREG_R57_ENTRY_ENGINE.md',
    'docs/PREREG_R64_BREAKOUT_BYPASS.md',
    'forward_eval.py',
)


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def sha(rel):
    """파일 해시. 없으면 None — **없는 것을 같다고 하지 않는다.**"""
    p = os.path.join(PROJ, rel)
    if not os.path.exists(p):
        return None
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def snap(files):
    return {rel: sha(rel) for rel in files}


def record():
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    s = snap(NO_AUTO_CHANGE)
    with open(STATE, 'w', encoding='utf-8') as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    got = sum(1 for v in s.values() if v)
    print(f'■ 실행 전 해시 기록 — {got}/{len(s)}개')
    for rel, h in s.items():
        print(f'  {"OK " if h else "없음"} {rel:34s} {h[:12] if h else "-"}')
    if got != len(s):
        print('  ⚠ 없는 파일이 있다. 없는 것은 대조할 수 없다 (미측정).')
    return 0


def verify():
    if not os.path.exists(STATE):
        print('기록이 없다 — 바뀌었는지 확인하지 못했다. '
              '통과가 아니라 **미측정**이다.')
        return 1
    with open(STATE, encoding='utf-8') as f:
        before = json.load(f)
    after = snap(NO_AUTO_CHANGE)
    changed, checked = [], 0
    for rel in NO_AUTO_CHANGE:
        b, a = before.get(rel), after.get(rel)
        if b is None or a is None:
            continue                      # 못 잰 것은 통과로 세지 않는다
        checked += 1
        if b != a:
            changed.append(rel)
    print(f'■ 실행 후 대조 — {checked}개 실제로 비교')
    if checked == 0:
        print('  0개를 비교했다 — 통과가 아니라 미측정이다.')
        return 1
    if not changed:
        print('  바뀐 것 없음 — 자동 실행이 모델을 건드리지 않았다.')
        return 0
    print(f'  ⛔ 바뀐 파일 {len(changed)}개:')
    for rel in changed:
        print(f'     {rel}  {before[rel][:12]} → {after[rel][:12]}')
    print('\n자동 실행은 이 파일들을 바꿀 수 없다.')
    print('버전·게이트·문턱은 사람이 사유와 함께 올린다 (CLAUDE.md §2·§7).')
    return 1


def pin():
    os.makedirs(os.path.dirname(PIN), exist_ok=True)
    s = snap(FORWARD_TARGETS)
    miss = [r for r, v in s.items() if not v]
    if miss:
        print('박제할 수 없다 — 없는 파일이 있다:')
        for r in miss:
            print(f'  {r}')
        return 1
    with open(PIN, 'w', encoding='utf-8') as f:
        json.dump(dict(
            note='2026-11-16 전방 재평가 대상의 박제 해시. 그날까지 바뀌면 '
                 '평가가 성립하지 않는다 — 재평가는 "그때 정한 것을 그대로" '
                 '재는 일이다.',
            pinned_at_utc=None,          # 시각은 커밋 이력이 갖고 있다
            files=s), f, ensure_ascii=False, indent=1)
    print(f'■ 전방 평가 대상 {len(s)}개 박제 → {PIN}')
    for rel, h in s.items():
        print(f'  {rel:38s} {h[:16]}')
    return 0


def check():
    if not os.path.exists(PIN):
        print('박제 파일이 없다 — --pin 으로 먼저 찍는다. (미측정)')
        return 1
    with open(PIN, encoding='utf-8') as f:
        pinned = (json.load(f) or {}).get('files') or {}
    now = snap(pinned.keys())
    drift, checked = [], 0
    for rel, h in pinned.items():
        cur = now.get(rel)
        if cur is None:
            drift.append((rel, h, '파일이 없어졌다'))
            continue
        checked += 1
        if cur != h:
            drift.append((rel, h, cur))
    print(f'■ 전방 평가 대상 대조 — {checked}/{len(pinned)}개 실제로 비교')
    if not drift:
        print('  전부 그대로 — 전방 재평가 조건이 살아 있다.')
        return 0
    print(f'\n  ⛔ FORWARD CONTAMINATION RISK — {len(drift)}건')
    for rel, old, cur in drift:
        print(f'     {rel}')
        print(f'       박제 {old[:16]} → 지금 '
              f'{cur[:16] if len(str(cur)) > 16 else cur}')
    print('\n11/16 재평가는 **그때 정한 것을 그대로** 재는 일이다.')
    print('중간에 바뀌었다면 그 사실을 먼저 기록하고, 무엇이 왜 바뀌었는지')
    print('밝힌 뒤에 평가한다. 조용히 넘어가면 평가가 거짓이 된다.')
    return 1


if __name__ == '__main__':
    _utf8()
    if '--verify' in sys.argv:
        sys.exit(verify())
    if '--pin' in sys.argv:
        sys.exit(pin())
    if '--check' in sys.argv:
        sys.exit(check())
    sys.exit(record())
