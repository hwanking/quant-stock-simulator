# -*- coding: utf-8 -*-
"""라운드 131 — 수급 연속성에 횡단면 정보가 있는가.

사전등록: docs/PREREG_R131_FLOW.md — **먼저 저장·커밋됐다** (be52ba7).

잣대는 라운드 49·110·111·112 와 **같다**: 같은 날 안에서 변수로 정렬 →
상위5 vs 6위이하 매수권(58+) 도달률 차이 → 날짜별 승패 → 부호검정.
표본 단위는 **날짜**다.

누출 차단: 순매매는 당일 장 마감 후 공표되므로 **D-1 까지만** 쓴다.

    C:/Python314/python.exe scripts/flow_rank_r131.py
"""
import collections
import io
import json
import math
import os
import random
import sys
from datetime import date, datetime, timezone

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJ, 'scripts'))
OUT = os.path.join(PROJ, 'data', 'flow_rank_r131.json')
FLOW = os.path.join(PROJ, '.portfolio', 'flow_daily.jsonl')

import power_r113 as P                                          # noqa: E402

SEED = 131
BOOT = 400
#: 사전등록 §5 — 양측 0.05 / 5시험 = 0.01 → z 2.5758, **올림**
Z_PASS = 2.58
MIN_DAYS = 200                       # 사전등록 §5 P4
#: 사전등록 §4 — 정확히 5개. 늘리지 않는다
VARS = ('frgn_days5', 'inst_days5', 'both_days5', 'frgn_streak', 'frgn_flip')


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def load_flow():
    """{종목: [(날짜, 기관, 외국인) …]} — 날짜 오름차순."""
    by_t = collections.defaultdict(list)
    if not os.path.exists(FLOW):
        return by_t
    with open(FLOW, encoding='utf-8', errors='replace') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:                                  # noqa: BLE001
                continue
            t, d = r.get('ticker'), r.get('date')
            if not t or not d:
                continue
            by_t[t].append((d, r.get('inst'), r.get('frgn')))
    for t in by_t:
        by_t[t].sort()
    return by_t


def features(seq, upto, leak=False):
    """D-1 까지의 수급으로 사전등록 §4 의 5개 변수를 만든다.

    leak=True 면 **당일 D 까지** 쓴다 — 누출 자기검사(ⓒ)에만 쓴다.
    """
    cut = [x for x in seq if (x[0] <= upto if leak else x[0] < upto)]
    if len(cut) < 6:
        return None                       # 5일 창 + 전환 판정에 모자라다
    last5 = cut[-5:]
    frgn5 = [x[2] for x in last5]
    inst5 = [x[1] for x in last5]
    if any(v is None for v in frgn5 + inst5):
        return None                       # 지어내지 않는다 (§3)

    streak = 0
    for x in reversed(cut):
        if x[2] is None or x[2] <= 0:
            break
        streak += 1

    prev5 = [x[2] for x in cut[-10:-5]] if len(cut) >= 10 else []
    flip = 1.0 if (prev5 and all(v is not None and v < 0 for v in prev5)
                   and frgn5[-1] is not None and frgn5[-1] > 0) else 0.0

    return {
        'frgn_days5': float(sum(1 for v in frgn5 if v > 0)),
        'inst_days5': float(sum(1 for v in inst5 if v > 0)),
        'both_days5': float(sum(1 for a, b in zip(frgn5, inst5)
                                if a > 0 and b > 0)),
        'frgn_streak': float(min(streak, 20)),
        'flip_raw': flip,
        'frgn_flip': flip,
    }


def sort_value(row, feat, key):
    """정렬 키의 값. 수급 변수는 feat 에서, 원장 필드는 row 에서 온다.

    ⚠ 처음엔 무조건 feat 에서 꺼냈다. 그래서 대조군 `score` 가 항상
    None 이 되어 **짝비교 0일**로 나왔고, 그 0 을 "대조"라고 찍고 있었다.
    라운드 114 가 적은 그 모양이다 — 0 건이 '없다'인지 '못 봤다'인지
    구분되지 않으면 검사가 아니다. 아래 자기검사 ⓓ 가 이걸 잡는다.
    """
    if key in feat:
        return feat[key]
    v = row.get(key)
    return None if v is None else float(v)


def day_frames(rows, key, joined):
    """라운드 113 의 day_frames 와 같은 모양 — 정렬 키만 바꾼다.

    joined[(ticker, date)] = 변수 dict. 수급이 안 붙은 케이스는 그날에서
    제외한다(버리는 것이 아니라 셈해서 보고한다). 대조군도 **같은
    축소 표본**에서 돌려야 비교가 된다 — 라운드 112 가 보였듯 표본을
    줄이는 것만으로 z 가 ±2 움직인다.
    """
    by_day = collections.defaultdict(list)
    for r in rows:
        k = (r.get('ticker'), str(r.get('date'))[:10])
        f = joined.get(k)
        if not f:
            continue
        v = sort_value(r, f, key)
        if v is None:
            continue
        by_day[k[1]].append((r, v))

    frames = []
    for d, day in by_day.items():
        if len(day) < 6:
            continue
        o = sorted(day, key=lambda x: (-float(x[1]),
                                       str(x[0].get('ticker'))))
        t5 = [r for r, _ in o[:5]]
        rb = [r for r, _ in o[5:] if float(r.get('score') or 0) >= P.BUY]
        if not rb:
            continue
        k5 = sum(1 for r in t5 if r.get('outcome') == 'TARGET')
        hb = sum(1 for r in rb if r.get('outcome') == 'TARGET') / len(rb) * 100
        frames.append((k5, len(t5) - k5, hb))
    return frames


def sign_z(frames):
    """부호검정 z — 효과 주입 없이 관측 그대로."""
    win = lose = 0
    for k, s, hb in frames:
        ha = k / 5.0 * 100.0
        if ha > hb:
            win += 1
        elif ha < hb:
            lose += 1
    n = win + lose
    if not n:
        return None, 0, 0, 0
    return (win - n / 2) / math.sqrt(n / 4), win, lose, n


def null_rate(rows, key, joined, rng, repeats=BOOT):
    """ⓐ 그날 결과를 섞은 귀무에서 z>=1.96 이 얼마나 나오나."""
    by_day = collections.defaultdict(list)
    for r in rows:
        k = (r.get('ticker'), str(r.get('date'))[:10])
        f = joined.get(k)
        if not f:
            continue
        v = sort_value(r, f, key)
        if v is None:
            continue
        by_day[k[1]].append((r, v))
    packs = []
    for _d, day in by_day.items():
        if len(day) < 6:
            continue
        o = sorted(day, key=lambda x: (-float(x[1]),
                                       str(x[0].get('ticker'))))
        t5 = [r for r, _ in o[:5]]
        rb = [r for r, _ in o[5:] if float(r.get('score') or 0) >= P.BUY]
        if not rb:
            continue
        packs.append(([1 if r.get('outcome') == 'TARGET' else 0 for r in t5],
                      [1 if r.get('outcome') == 'TARGET' else 0 for r in rb]))
    if not packs:
        return None
    hit = 0
    for _ in range(repeats):
        win = lose = 0
        for a, b in packs:
            pool = a + b
            rng.shuffle(pool)
            ha = sum(pool[:len(a)]) / len(a) * 100.0
            hb = sum(pool[len(a):]) / len(b) * 100.0
            if ha > hb:
                win += 1
            elif ha < hb:
                lose += 1
        n = win + lose
        if n and (win - n / 2) / math.sqrt(n / 4) >= 1.96:
            hit += 1
    return hit / repeats


def min_detectable(frames, rng):
    """R129 의 식으로 이 표본의 최소 가시 효과(%p)를 낸다."""
    tot = sum(k + s for k, s, _ in frames)
    if not tot:
        return None
    p_stop = sum(s for _, s, _ in frames) / tot
    if p_stop <= 0:
        return None
    for dpp in (1, 2, 3, 4, 5, 8, 12, 20):
        q = (dpp / 100.0) / p_stop
        if q > 1.0:
            continue
        win = lose = 0.0
        for k, s, hb in frames:
            for j in range(s + 1):
                pr = (math.comb(s, j) * (q ** j) * ((1 - q) ** (s - j))
                      if s else (1.0 if j == 0 else 0.0))
                if pr <= 0:
                    continue
                ha = (k + j) * 20.0
                if ha > hb:
                    win += pr
                elif ha < hb:
                    lose += pr
        dec = (win + lose) / len(frames)
        p = win / (win + lose) if (win + lose) else 0.0
        if 2 * p - 1 <= 0:
            continue
        need = ((Z_PASS + 0.8416) / (2 * p - 1)) ** 2 / dec
        if need <= len(frames):
            return dpp
    return None


def main():
    print('라운드 131 — 수급 연속성에 횡단면 정보가 있는가')
    print('사전등록: docs/PREREG_R131_FLOW.md (측정 전 커밋 be52ba7)')
    print()

    rows = P.load()                       # train+valid · 판정완료 · 봉인 준수
    flow = load_flow()
    print(f'개발 구간·판정완료 {len(rows):,}건 · 수급 종목 {len(flow):,}개')

    # ── 조인 — 몇 %를 못 쓰는지 적는다 (버리지 않고 셈한다) ─────────
    joined, joined_leak = {}, {}
    miss_t = miss_d = 0
    for r in rows:
        t, d = r.get('ticker'), str(r.get('date'))[:10]
        seq = flow.get(t)
        if not seq:
            miss_t += 1
            continue
        f = features(seq, d)
        if f is None:
            miss_d += 1
            continue
        joined[(t, d)] = f
        joined_leak[(t, d)] = features(seq, d, leak=True)
    used = len(joined)
    print(f'조인: 쓸 수 있는 케이스 {used:,} / {len(rows):,} '
          f'({used / max(1, len(rows)) * 100:.1f}%)')
    print(f'   못 쓴 이유 — 종목에 수급 없음 {miss_t:,} · '
          f'그 날짜 이전 5일이 모자람 {miss_d:,}')
    if used == 0:
        print('\n조인이 0건이다 — 측정이 성립하지 않는다. '
              '결과를 "미달"로 적지 않는다.')
        return 1

    rng = random.Random(SEED)
    res, frames_by = {}, {}

    print()
    print(f'   {"변수":<14}{"짝비교일":>9}{"이긴날":>7}{"진날":>6}'
          f'{"z":>8}  판정 (문턱 {Z_PASS})')
    for key in VARS + ('score',):
        fr = day_frames(rows, key, joined)
        frames_by[key] = fr
        z, w, l, n = sign_z(fr)
        ok = (z is not None and z >= Z_PASS and len(fr) >= MIN_DAYS)
        res[key] = dict(days=len(fr), win=w, lose=l, decided=n,
                        z=(round(z, 3) if z is not None else None),
                        pass_p1=(z is not None and z >= Z_PASS),
                        pass_p4=len(fr) >= MIN_DAYS)
        tag = '대조' if key == 'score' else ('통과' if ok else '미달')
        print(f'   {key:<14}{len(fr):>9,}{w:>7}{l:>6}'
              f'{(z if z is not None else float("nan")):>8.2f}  {tag}')

    # ── P3 — train / valid 방향 일치 ────────────────────────────
    print()
    print('■ P3 — train / valid 방향 일치')
    for key in VARS:
        sub = {}
        for sp in ('train', 'valid'):
            rr = [r for r in rows if r.get('split') == sp]
            fr = day_frames(rr, key, joined)
            z, _, _, _ = sign_z(fr)
            sub[sp] = dict(days=len(fr),
                           z=(round(z, 3) if z is not None else None))
        zt, zv = sub['train']['z'], sub['valid']['z']
        same = (zt is not None and zv is not None
                and (zt > 0) == (zv > 0))
        res[key]['split'] = sub
        res[key]['pass_p3'] = same
        print(f'   {key:<14} train {str(zt):>7} ({sub["train"]["days"]}일) · '
              f'valid {str(zv):>7} ({sub["valid"]["days"]}일) · '
              f'{"일치" if same else "불일치/미산출"}')

    # ── 자기검사 ────────────────────────────────────────────────
    print()
    print('■ 자기검사 — 통과해야 위 숫자를 쓴다')

    # ⓐ 거짓양성률
    fpr = null_rate(rows, 'frgn_days5', joined, random.Random(SEED * 7919))
    ok_a = fpr is not None and 0.005 <= fpr <= 0.06
    print(f'   ⓐ 거짓양성률 z>=1.96 : '
          f'{"%.1f%%" % (fpr * 100) if fpr is not None else "미산출"} '
          f'({"정상" if ok_a else "이상"} · 허용 0.5~6%)')

    # ⓑ 변수가 실제로 정렬에 들어갔는가 — 섞으면 z 가 바뀌어야 한다
    shuffled = dict(joined)
    vals = [joined[k]['frgn_days5'] for k in joined]
    rng.shuffle(vals)
    for k, v in zip(list(joined.keys()), vals):
        shuffled[k] = dict(joined[k], frgn_days5=v)
    z_real, _, _, _ = sign_z(frames_by['frgn_days5'])
    z_shuf, _, _, _ = sign_z(day_frames(rows, 'frgn_days5', shuffled))
    ok_b = (z_real is not None and z_shuf is not None
            and abs(z_real - z_shuf) > 1e-9)
    print(f'   ⓑ 변수가 정렬에 들어갔는가 : 실제 z {z_real:+.3f} vs '
          f'섞은 z {z_shuf:+.3f} ({"정상" if ok_b else "이상 — 변수가 비어 있다"})')

    # ⓒ 누출 검사 — 당일을 쓰면 달라지는가
    z_leak, _, _, _ = sign_z(day_frames(rows, 'frgn_days5', joined_leak))
    ok_c = (z_leak is not None and z_real is not None
            and abs(z_leak - z_real) > 1e-9)
    print(f'   ⓒ 누출 검사 : D-1 z {z_real:+.3f} vs D포함 z {z_leak:+.3f} '
          f'({"정상 — 당일이 실제로 빠져 있다" if ok_c else "이상"})')

    # ⓓ 대조군이 실제로 측정됐는가 — 0 을 "대조"라고 찍으면 안 된다.
    #   처음 판에서 대조군 `score` 가 짝비교 **0일**로 나왔는데 그걸
    #   그대로 표에 찍고 있었다. 0 건과 미측정을 가른다 (라운드 114).
    #
    #   ⚠ 이 검사를 처음엔 `n_ctrl >= MIN_DAYS` 로 썼다. MIN_DAYS 는
    #   **P4(판정 기준)** 의 상수인데 자기검사에 빌려 쓴 것이라 틀렸다.
    #   ⓓ 가 재려던 것은 "쟀느냐"이지 "충분하냐"가 아니다. 사전등록
    #   §4 도 score 를 *판정 대상 아님 · 해석용* 이라 적었다.
    #   → 기준을 내린 것이 아니라 **검사를 제 목적에 맞춘 것**이다.
    #     대신 날짜가 변수들보다 적다는 사실은 아래에 그대로 찍는다.
    n_ctrl = len(frames_by.get('score') or [])
    ok_d = n_ctrl > 0
    n_var = len(frames_by.get(VARS[0]) or [])
    print(f'   ⓓ 대조군이 실제로 측정됐는가 : score 짝비교 {n_ctrl:,}일 '
          f'({"정상" if ok_d else "이상 — 0 을 대조라고 찍지 말 것"})')
    print(f'      └ 대조 {n_ctrl:,}일 < 변수 {n_var:,}일 — '
          f'점수로 정렬하면 상위5가 매수권을 먹어 대조군이 더 자주 빈다 '
          f'(라운드 129 가 잰 그 구조)')

    ok = ok_a and ok_b and ok_c and ok_d

    # ── 검정력 — 미달을 "효과 없음"으로 쓰지 않기 위해 ───────────
    print()
    print('■ 이 표본의 최소 가시 효과 (R129 의 식)')
    mdes = {}
    for key in VARS:
        m = min_detectable(frames_by[key], rng)
        mdes[key] = m
        print(f'   {key:<14} {("%d%%p" % m) if m else "20%p 로도 부족"}')

    # ── 판정 ────────────────────────────────────────────────────
    print()
    print('■ 판정 (P1 z>=2.58 · P2 방향 양수 · P3 train/valid 일치 · '
          f'P4 날짜>={MIN_DAYS})')
    verdict = {}
    for key in VARS:
        r = res[key]
        p1 = bool(r['pass_p1'])
        p2 = bool(r['z'] is not None and r['z'] > 0)
        p3 = bool(r.get('pass_p3'))
        p4 = bool(r['pass_p4'])
        allp = p1 and p2 and p3 and p4
        verdict[key] = dict(P1=p1, P2=p2, P3=p3, P4=p4, passed=allp)
        print(f'   {key:<14} P1 {"O" if p1 else "X"} · P2 {"O" if p2 else "X"}'
              f' · P3 {"O" if p3 else "X"} · P4 {"O" if p4 else "X"}'
              f'  → {"통과" if allp else "미달"}')
    n_pass = sum(1 for v in verdict.values() if v['passed'])
    print()
    print(f'   {len(VARS)}개 중 통과 {n_pass}개'
          + ('' if n_pass else ' — 기각하고 현행 유지한다'))

    doc = {
        'made': date.today().isoformat(),
        'made_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'prereg': 'docs/PREREG_R131_FLOW.md',
        'prereg_commit': 'be52ba7',
        'basis': '개발 구간(train+valid) · 판정완료 · 블라인드/전방 미사용',
        'leak_rule': '수급은 D-1 까지만 사용 (당일은 장 마감 후 공표)',
        'seed': SEED, 'z_pass': Z_PASS, 'min_days': MIN_DAYS,
        'vars': list(VARS),
        'join': dict(rows=len(rows), used=used, miss_ticker=miss_t,
                     miss_window=miss_d,
                     used_pct=round(used / max(1, len(rows)) * 100, 1)),
        'results': res,
        'verdict': verdict,
        'passed': n_pass,
        'min_detectable_pp': mdes,
        'selfcheck': dict(fpr=(round(fpr, 4) if fpr is not None else None),
                          fpr_ok=ok_a,
                          z_real=(round(z_real, 4)
                                  if z_real is not None else None),
                          z_shuffled=(round(z_shuf, 4)
                                      if z_shuf is not None else None),
                          var_used_ok=ok_b,
                          z_leak=(round(z_leak, 4)
                                  if z_leak is not None else None),
                          leak_ok=ok_c, ok=ok),
        'note': ('측정 전용 — 점수·게이트·문턱을 바꾸지 않는다. '
                 '통과해도 2026-11-16 전에는 운영에 넣지 않는다.'),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print()
    print(f'저장: {OUT}')
    return 0 if ok else 1


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
