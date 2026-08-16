# -*- coding: utf-8 -*-
"""라운드 113 — 이 잣대는 얼마나 작은 효과까지 볼 수 있는가 (검정력).

사전등록: docs/PREREG_R113_POWER.md — **먼저 저장·커밋됐다.**

라운드 110·111·112 가 25개 시험에서 하나도 통과 못 했고, 그 위에
"순위에 정보가 없다"를 적었다. 그런데 **"못 봤다"와 "보니 없다"는 다른
말이다.** 이 잣대(하루 5종목 적중률 · 날짜 부호검정)가 작은 효과를 볼 수
있는지부터 재야 그 문장을 쓸 자격이 생긴다.

효과를 **인위적으로 주입**하고 얼마나 잡히는지 센다. 합성 데이터를 만들지
않는다 — 실제 원장의 날짜·종목 구성을 그대로 두고 상위5의 결과만 뒤집는다.

    C:/Python314/python.exe scripts/power_r113.py
"""
import collections
import glob
import io
import json
import math
import os
import random
import sys
from datetime import date, datetime, timezone

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(PROJ, '.portfolio')
OUT = os.path.join(PROJ, 'data', 'power_r113.json')

BUY = 58.0
#: 사전등록 §1 — 씨앗 고정. 돌릴 때마다 답이 달라지면 측정이 아니다
SEED = 113
REPEATS = 200
#: Δ=0 은 기계 검사다 — 효과를 안 넣었는데 z≥1.96 이 2.5% 근처로 안 나오면
#: 이 시뮬레이션은 아무것도 재고 있지 않다. C1~C4 에는 쓰지 않는다
DELTAS = (0, 1, 2, 3, 5, 8, 12)       # 적중률 차이 %p
GRID = (1, 2, 3, 5, 8, 12)            # 판정에 쓰는 격자 (Δ=0 제외)
#: 실제로 쓴 문턱 셋 — 보정 없음 · R111 · R112(참 임계)
THRESHOLDS = (('보정없음', 1.96), ('R111', 2.73), ('R112', 2.9552))
#: 날짜 수가 가장 적은 것과 가장 많은 것 (표본이 검정력을 가르는지)
KEYS = (('score', '종합점수'), ('q_confidence', 'confidence'))
POWER_TARGET = 0.80


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def load():
    """개발 구간·판정완료 + 하위점수 패치 합류 (라운드 99 교훈)."""
    patch = {}
    for p in sorted(glob.glob(os.path.join(P, 'subscore_patch*.jsonl'))):
        with open(p, encoding='utf-8', errors='replace') as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    q = json.loads(ln)
                except Exception:                              # noqa: BLE001
                    continue
                patch[(str(q.get('ticker')), str(q.get('date'))[:10])] = q

    rows = []
    with open(os.path.join(P, 'virtual_graded.jsonl'),
              encoding='utf-8', errors='replace') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:                                  # noqa: BLE001
                continue
            if r.get('split') not in ('train', 'valid'):
                continue                       # 봉인 준수
            if r.get('outcome') not in ('TARGET', 'STOP'):
                continue
            if r.get('return_pct') is None or r.get('score') is None:
                continue
            q = patch.get((str(r.get('ticker')), str(r.get('date'))[:10]))
            if q and r.get('q_confidence') is None \
                    and q.get('q_confidence') is not None:
                r['q_confidence'] = q['q_confidence']
            rows.append(r)
    return rows


def day_frames(rows, key):
    """날짜별로 (상위5 적중수, 상위5 미적중수, 6위이하 매수권 적중률).

    잣대는 라운드 49·110·111·112 와 **같다.** 시뮬레이션 때마다 다시
    정렬하지 않도록 한 번만 만들어 둔다.
    """
    by_day = collections.defaultdict(list)
    for r in rows:
        if r.get(key) is None:
            continue
        by_day[str(r.get('date'))[:10]].append(r)

    frames = []
    for d, day in by_day.items():
        if len(day) < 6:
            continue
        o = sorted(day, key=lambda r: (-float(r[key]), str(r.get('ticker'))))
        t5 = o[:5]
        rb = [r for r in o[5:] if float(r.get('score') or 0) >= BUY]
        if not rb:
            continue
        k = sum(1 for r in t5 if r.get('outcome') == 'TARGET')
        hb = sum(1 for r in rb if r.get('outcome') == 'TARGET') / len(rb) * 100
        frames.append((k, len(t5) - k, hb))
    return frames


def null_frames(rows, key):
    """귀무 검사용 — 그날 상위5·6위이하매수권의 **결과 벡터**를 그대로 보관.

    Δ=0 행은 q=0 이라 난수가 아예 안 들어간다. 그건 **재현 검사**이지
    거짓양성률 검사가 아니다 (사전등록에 그렇게 적은 것은 내 잘못이다).
    진짜 귀무는 **그날 안에서 결과를 섞는 것** — 순위와 결과의 연결만
    끊고 날짜 구조·집단 크기·매수권 필터는 그대로 둔다.
    """
    by_day = collections.defaultdict(list)
    for r in rows:
        if r.get(key) is None:
            continue
        by_day[str(r.get('date'))[:10]].append(r)
    out = []
    for d, day in by_day.items():
        if len(day) < 6:
            continue
        o = sorted(day, key=lambda r: (-float(r[key]), str(r.get('ticker'))))
        t5 = o[:5]
        rb = [r for r in o[5:] if float(r.get('score') or 0) >= BUY]
        if not rb:
            continue
        out.append(([1 if r.get('outcome') == 'TARGET' else 0 for r in t5],
                    [1 if r.get('outcome') == 'TARGET' else 0 for r in rb]))
    return out


def null_z(frames, rng):
    """그날 결과를 섞고 부호검정 z — 순위에 정보가 **없을 때**의 분포."""
    win = lose = 0
    for a, b in frames:
        pool = a + b
        rng.shuffle(pool)
        ha = sum(pool[:len(a)]) / len(a) * 100.0
        hb = sum(pool[len(a):]) / len(b) * 100.0
        if ha > hb:
            win += 1
        elif ha < hb:
            lose += 1
    n = win + lose
    return ((win - n / 2) / math.sqrt(n / 4)) if n else None


def sign_z(frames, q, rng):
    """상위5의 STOP 을 확률 q 로 뒤집고 부호검정 z 를 낸다."""
    win = lose = 0
    for k, s, hb in frames:
        flip = rng.binomialvariate(s, q) if (s and q > 0) else 0
        ha = (k + flip) / 5.0 * 100.0
        if ha > hb:
            win += 1
        elif ha < hb:
            lose += 1
    n = win + lose
    return ((win - n / 2) / math.sqrt(n / 4)) if n else None


def main():
    print('라운드 113 — 이 잣대는 얼마나 작은 효과까지 볼 수 있는가')
    print('사전등록: docs/PREREG_R113_POWER.md (측정 전 커밋)\n')
    rows = load()
    print(f'개발 구간·판정완료 {len(rows):,}건\n')

    doc_keys, base = {}, {}
    for key, label in KEYS:
        frames = day_frames(rows, key)
        tot = sum(k + s for k, s, _ in frames)
        stops = sum(s for _, s, _ in frames)
        p_stop = stops / tot if tot else 0.0
        base[key] = dict(days=len(frames), top_cases=tot,
                         stop_rate=round(p_stop * 100, 2))
        print(f'{label}: 짝비교 {len(frames):,}일 · 상위5 케이스 {tot:,}건 · '
              f'그중 미적중 {p_stop * 100:.1f}%')

        # Δ%p 를 만들려면 미적중 중 얼마를 뒤집어야 하는가 —
        # 기대 상승 = q · P(미적중) · 100 = Δ  →  q = Δ / (P(미적중)·100)
        rows_out = {}
        for dpp in DELTAS:
            q = (dpp / 100.0) / p_stop if p_stop else 0.0
            if q > 1.0:
                rows_out[dpp] = dict(q=None, note='미적중을 다 뒤집어도 부족')
                continue
            rng = random.Random(SEED * 1000 + dpp)
            zs = [sign_z(frames, q, rng) for _ in range(REPEATS)]
            zs = [z for z in zs if z is not None]
            hit = {name: sum(1 for z in zs if z >= t) / len(zs)
                   for name, t in THRESHOLDS}
            rows_out[dpp] = dict(q=round(q, 4),
                                 median_z=round(sorted(zs)[len(zs) // 2], 2),
                                 power={k: round(v, 3)
                                        for k, v in hit.items()})
        doc_keys[key] = rows_out

        print(f'   {"Δ(%p)":>7}{"뒤집는비율":>11}{"z중앙":>8}'
              + ''.join(f'{n:>10}' for n, _ in THRESHOLDS))
        for dpp in DELTAS:
            r = rows_out[dpp]
            if r.get('q') is None:
                print(f'   {dpp:>7}{"—":>11}{"—":>8}' + r['note'])
                continue
            print(f'   {dpp:>7}{r["q"]:>11.3f}{r["median_z"]:>8.2f}'
                  + ''.join(f'{r["power"][n] * 100:>9.0f}%'
                            for n, _ in THRESHOLDS))
        print()

    # 기계 검사 ① 재현 — Δ=0 은 q=0 이라 난수가 없다. 실제 z 를 그대로
    # 되짚어야 한다. (사전등록에 이걸 '거짓양성률 검사'라 적은 것은 내 잘못.
    # 결정적인 계산에서 거짓양성률이 나올 리 없다 — 아래 ②로 따로 잰다)
    print('■ 기계 검사 ① 재현 (Δ=0 은 난수가 없다 — 실제 z 와 같아야 한다)')
    repro = {}
    for key, label in KEYS:
        z0 = doc_keys[key][0].get('median_z')
        repro[key] = z0
        print(f'   {label:<12} Δ=0 의 z = {z0:+.2f}  '
              f'(라운드 110·111 이 같은 잣대로 낸 값과 대조)')

    # 기계 검사 ② 진짜 귀무 — 그날 결과를 섞어 순위와의 연결만 끊는다.
    # 여기서 z≥1.96 이 2.5% 근처로 안 나오면 위 검정력 숫자는 못 믿는다.
    print('\n■ 기계 검사 ② 거짓양성률 (그날 결과를 섞은 귀무 분포)')
    sane, null_out = True, {}
    for key, label in KEYS:
        nf = null_frames(rows, key)
        rng = random.Random(SEED * 7919 + len(nf))
        zs = [null_z(nf, rng) for _ in range(REPEATS)]
        zs = [z for z in zs if z is not None]
        rate = {n: sum(1 for z in zs if z >= t) / len(zs)
                for n, t in THRESHOLDS}
        ok = 0.005 <= rate['보정없음'] <= 0.06        # 2.5% 근처
        sane = sane and ok
        # 관측값이 귀무 분포의 어디에 놓이는가 — 정규근사를 안 쓴 p
        obs = repro[key]
        below = sum(1 for z in zs if z <= obs)
        pct = below / len(zs) * 100
        null_out[key] = dict(rate={k: round(v, 4) for k, v in rate.items()},
                             median_z=round(sorted(zs)[len(zs) // 2], 2),
                             observed_z=obs,
                             observed_pctile=round(pct, 1),
                             empirical_p_two_sided=round(
                                 min(1.0, 2 * min(below, len(zs) - below)
                                     / len(zs)), 3),
                             ok=ok)
        print(f'   {label:<12} z≥1.96 {rate["보정없음"] * 100:>5.1f}% · '
              f'z≥2.95 {rate["R112"] * 100:>4.1f}% · '
              f'z중앙 {null_out[key]["median_z"]:+.2f} · '
              f'{"정상" if ok else "이상 — 아래 숫자를 믿지 말 것"}')
        print(f'   {"":<12} 관측 {obs:+.2f} 는 귀무 분포의 {pct:.1f}% 지점 · '
              f'양측 경험 p = {null_out[key]["empirical_p_two_sided"]:.3f}')
    print()

    # C1 — 검정력 80% 를 넘는 최소 효과
    print(f'■ 검정력 {POWER_TARGET:.0%} 를 넘는 최소 효과 (C1)')
    c1 = {}
    for key, label in KEYS:
        for name, _ in THRESHOLDS:
            got = next((d for d in GRID
                        if (doc_keys[key][d].get('power') or {})
                        .get(name, 0) >= POWER_TARGET), None)
            c1[f'{key}:{name}'] = got
            print(f'   {label:<12}{name:<10} '
                  + (f'{got}%p' if got else f'{GRID[-1]}%p 로도 부족'))

    doc = {
        'made': date.today().isoformat(),
        'made_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'prereg': 'docs/PREREG_R113_POWER.md',
        'basis': '개발 구간(train+valid) · 판정완료 · 블라인드 미사용',
        'method': ('실제 원장의 날짜·종목 구성을 그대로 두고 상위5의 '
                   '미적중을 확률 q 로 적중으로 뒤집어 효과를 주입한다. '
                   '합성 데이터를 만들지 않는다.'),
        'seed': SEED, 'repeats': REPEATS, 'deltas': list(DELTAS),
        'grid': list(GRID), 'sanity_ok': sane,
        'reproduction': repro, 'null': null_out,
        'sanity_note': ('기계 검사 둘. ① Δ=0 은 q=0 이라 난수가 없다 — '
                        '실제 z 를 그대로 되짚는 **재현** 검사이지 '
                        '거짓양성률 검사가 아니다(사전등록에 그렇게 적은 '
                        '것은 잘못이다). ② 거짓양성률은 그날 결과를 섞은 '
                        '귀무 분포로 따로 쟀다 — z≥1.96 이 2.5% 근처여야 '
                        '위 검정력 숫자를 믿을 수 있다. 둘 다 C1~C4 에는 '
                        '쓰지 않는다.'),
        'thresholds': {n: t for n, t in THRESHOLDS},
        'power_target': POWER_TARGET,
        'baseline': base, 'power': doc_keys, 'min_detectable': c1,
        'note': ('관측 전용 — 점수·게이트·문턱을 바꾸지 않는다. '
                 '결론을 뒤집는 라운드가 아니라 결론의 **크기**를 '
                 '근거에 맞추는 라운드다.'),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f'\n저장: {OUT}')
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
