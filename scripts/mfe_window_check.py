# -*- coding: utf-8 -*-
"""라운드 85 — 열린 이슈 '원장 mfe/mae 는 청산 봉까지만' 을 실측으로 판정.

■ 이슈 (medium · open)
  원장의 mfe/mae 는 **청산된 봉까지만** 잰 값이다. 손절로 끝난 케이스의
  이후 상승을 알 수 없어 "목표를 넓히면 어땠을까"를 되돌려 물을 수 없다.

■ 그 뒤로 생긴 것
  라운드 56·73 이 bar_paths_s*.jsonl 을 채웠다 — 신호 다음 봉부터 21봉의
  고·저·종·시가와 거래량 배율이 **청산 여부와 무관하게** 들어 있다.
  경로 열: [날짜, 고가%, 저가%, 종가%, 거래량배율, 시가%]

■ 이 스크립트가 하는 일
  같은 케이스에 대해 두 값을 나란히 잰다:
    ① 원장 mfe (청산 봉까지)
    ② 경로 전체 21봉의 최대 상승 (청산과 무관)
  차이가 크면 **가려져 있던 것이 실제로 있다**는 뜻이고, 경로로 그것을
  볼 수 있다는 뜻이다. 이슈를 닫을 근거가 된다.

관측 전용 — 점수·게이트·문턱을 바꾸지 않는다. 목표 배수를 여기서
고르지 않는다 (그건 사전등록이 필요한 별개 라운드다).

    C:/Python314/python.exe scripts/mfe_window_check.py
"""
import glob
import io
import json
import os
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PF = os.path.join(PROJ, '.portfolio')
OUT = os.path.join(PROJ, 'data', 'mfe_window_r85.json')


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def load_paths():
    """(종목,날짜) → 21봉 경로. 고가%만 쓰므로 그것만 뽑아 메모리를 아낀다."""
    out = {}
    for p in sorted(glob.glob(os.path.join(PF, 'bar_paths_s*.jsonl'))):
        with open(p, encoding='utf-8') as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:                              # noqa: BLE001
                    continue
                bars = r.get('bars') or []
                if not bars:
                    continue
                highs = [b[1] for b in bars if b[1] is not None]
                lows = [b[2] for b in bars if b[2] is not None]
                if highs and lows:
                    out[(r.get('ticker'), str(r.get('date'))[:10])] = (
                        max(highs), min(lows), len(bars))
    return out


def med(a):
    a = sorted(a)
    return a[len(a) // 2] if a else None


def main():
    _utf8()
    paths = load_paths()
    print(f'경로 {len(paths):,}건 적재')

    rows = []
    with open(os.path.join(PF, 'virtual_graded.jsonl'), encoding='utf-8') as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except Exception:                                  # noqa: BLE001
                pass
    print(f'원장 {len(rows):,}건\n')

    by_out = {}
    for r in rows:
        key = (r.get('ticker'), str(r.get('date'))[:10])
        pth = paths.get(key)
        if not pth:
            continue
        led_mfe = r.get('mfe_pct')
        if led_mfe is None:
            continue
        full_up, full_dn, nb = pth
        o = str(r.get('outcome') or '?')
        by_out.setdefault(o, []).append(
            (float(led_mfe), float(full_up), float(full_dn), nb))

    print('청산 결과별 — 원장 mfe(청산까지) vs 경로 전체 21봉 최대 상승')
    print(f'{"결과":<8} {"n":>8} {"원장mfe 중앙":>12} {"경로최대 중앙":>13} '
          f'{"차이 중앙":>10} {"경로가 더 큰 비율":>16}')
    summary = {}
    for o, v in sorted(by_out.items(), key=lambda x: -len(x[1])):
        led = [x[0] for x in v]
        ful = [x[1] for x in v]
        dif = [x[1] - x[0] for x in v]
        bigger = sum(1 for x in v if x[1] > x[0] + 1e-9) / len(v) * 100
        summary[o] = dict(n=len(v), led_mfe_med=med(led),
                          path_max_med=med(ful), diff_med=med(dif),
                          path_bigger_pct=round(bigger, 1))
        print(f'{o:<8} {len(v):>8,} {med(led):>12.2f} {med(ful):>13.2f} '
              f'{med(dif):>10.2f} {bigger:>15.1f}%')

    # 손절로 끝난 케이스에서 '그 뒤에 얼마나 올랐나' — 가려져 있던 것
    stop = by_out.get('STOP') or []
    if stop:
        ups = sorted(x[1] for x in stop)
        print(f'\nSTOP 으로 끝난 {len(stop):,}건의 **경로 전체** 최대 상승 분포')
        for q, lab in ((0.25, '하위25%'), (0.5, '중앙'),
                       (0.75, '상위25%'), (0.9, '상위10%')):
            print(f'   {lab:<8} {ups[int(len(ups) * q)]:+.2f}%')
        for thr in (3.0, 5.0, 10.0):
            c = sum(1 for x in stop if x[1] >= thr)
            print(f'   손절 뒤에도 +{thr:.0f}% 이상 찍은 비율: '
                  f'{c / len(stop) * 100:.1f}% ({c:,}건)')

    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(dict(
            made='2026-08-13', paths=len(paths), ledger=len(rows),
            by_outcome=summary,
            note='관측 전용 — 목표 배수를 고르지 않는다. 원장 mfe 는 청산 '
                 '봉까지라 연구용으로 쓰지 않는다. 경로(bar_paths)는 청산과 '
                 '무관하게 21봉이 남아 있어 목표 확장 연구가 가능하다.'),
            f, ensure_ascii=False, indent=1)
    print(f'\n저장: {OUT}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
