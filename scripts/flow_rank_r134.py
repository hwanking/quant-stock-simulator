# -*- coding: utf-8 -*-
"""라운드 134 — 수급 연속성 재측정 (표본 6배).

사전등록: docs/PREREG_R134_FLOW_REPLICATION.md — **먼저 커밋됐다**(87ce30b).

라운드 131 의 판정(5개 전부 미달)은 **그대로 선다.** 이 라운드는 그것을
뒤집으려는 것이 아니라, R131 이 볼 수 있는 것이 8~12%p 뿐이었기 때문에
표본을 키워 다시 보는 것이다.

**측정 코드를 다시 쓰지 않는다.** `flow_rank_r131` 의 함수를 그대로
import 한다 — 다시 구현하면 두 라운드가 서로 다른 것을 재게 된다.
여기서 바꾸는 것은 **문턱과 하한뿐**이다.

    C:/Python314/python.exe scripts/flow_rank_r134.py
"""
import collections
import io
import json
import os
import random
import sys
from datetime import date, datetime, timezone

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJ, 'scripts'))
OUT = os.path.join(PROJ, 'data', 'flow_rank_r134.json')

import flow_rank_r131 as R                                     # noqa: E402
import power_r113 as P                                         # noqa: E402

#: 사전등록 §2 — 같은 가설을 두 번 재므로 가족이 10개다.
#: 양측 0.05/10 = 0.005 → z 2.8070 → **올림** 2.81
Z_PASS = 2.81
#: 사전등록 §3 — 조인이 조용히 깨졌을 때 잡는 안전선 (통과 문턱 아님)
MIN_DAYS = 600
PREREG_COMMIT = '87ce30b'


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def main():
    print('라운드 134 — 수급 연속성 재측정 (표본 6배)')
    print(f'사전등록: docs/PREREG_R134_FLOW_REPLICATION.md '
          f'(측정 전 커밋 {PREREG_COMMIT})')
    print('라운드 131 의 판정을 대체하지 않는다 — 나란히 싣는다')
    print()

    rows = P.load()
    flow = R.load_flow()
    print(f'개발 구간·판정완료 {len(rows):,}건 · 수급 종목 {len(flow):,}개')

    joined, joined_leak = {}, {}
    miss_t = miss_d = 0
    for r in rows:
        t, d = r.get('ticker'), str(r.get('date'))[:10]
        seq = flow.get(t)
        if not seq:
            miss_t += 1
            continue
        f = R.features(seq, d)
        if f is None:
            miss_d += 1
            continue
        joined[(t, d)] = f
        joined_leak[(t, d)] = R.features(seq, d, leak=True)
    used = len(joined)
    print(f'조인: 쓸 수 있는 케이스 {used:,} / {len(rows):,} '
          f'({used / max(1, len(rows)) * 100:.1f}%)')
    print(f'   못 쓴 이유 — 종목에 수급 없음 {miss_t:,} · '
          f'그 날짜 이전 5일이 모자람 {miss_d:,}')
    if used == 0:
        print('\n조인이 0건이다 — 측정이 성립하지 않는다.')
        return 1

    rng = random.Random(R.SEED + 3)
    res, frames_by = {}, {}
    print()
    print(f'   {"변수":<14}{"짝비교일":>9}{"이긴날":>7}{"진날":>6}'
          f'{"z":>8}  판정 (문턱 {Z_PASS})')
    for key in R.VARS + ('score',):
        fr = R.day_frames(rows, key, joined)
        frames_by[key] = fr
        z, w, l, n = R.sign_z(fr)
        ok = (z is not None and z >= Z_PASS and len(fr) >= MIN_DAYS)
        res[key] = dict(days=len(fr), win=w, lose=l, decided=n,
                        z=(round(z, 3) if z is not None else None),
                        pass_p1=(z is not None and z >= Z_PASS),
                        pass_p4=len(fr) >= MIN_DAYS)
        tag = '대조' if key == 'score' else ('통과' if ok else '미달')
        print(f'   {key:<14}{len(fr):>9,}{w:>7}{l:>6}'
              f'{(z if z is not None else float("nan")):>8.2f}  {tag}')

    print()
    print('■ P3 — train / valid 방향 일치')
    for key in R.VARS:
        sub = {}
        for sp in ('train', 'valid'):
            rr = [r for r in rows if r.get('split') == sp]
            fr = R.day_frames(rr, key, joined)
            z, _, _, _ = R.sign_z(fr)
            sub[sp] = dict(days=len(fr),
                           z=(round(z, 3) if z is not None else None))
        zt, zv = sub['train']['z'], sub['valid']['z']
        same = (zt is not None and zv is not None and (zt > 0) == (zv > 0))
        res[key]['split'] = sub
        res[key]['pass_p3'] = same
        print(f'   {key:<14} train {str(zt):>7} ({sub["train"]["days"]}일) · '
              f'valid {str(zv):>7} ({sub["valid"]["days"]}일) · '
              f'{"일치" if same else "불일치/미산출"}')

    # ── 자기검사 (R131 의 넷을 그대로) ──────────────────────────
    print()
    print('■ 자기검사 — 통과해야 위 숫자를 쓴다')
    fpr = R.null_rate(rows, 'frgn_days5', joined,
                      random.Random(R.SEED * 7919 + 3))
    ok_a = fpr is not None and 0.005 <= fpr <= 0.06
    print(f'   ⓐ 거짓양성률 z>=1.96 : '
          f'{"%.1f%%" % (fpr * 100) if fpr is not None else "미산출"} '
          f'({"정상" if ok_a else "이상"} · 허용 0.5~6%)')

    shuffled = dict(joined)
    vals = [joined[k]['frgn_days5'] for k in joined]
    rng.shuffle(vals)
    for k, v in zip(list(joined.keys()), vals):
        shuffled[k] = dict(joined[k], frgn_days5=v)
    z_real, _, _, _ = R.sign_z(frames_by['frgn_days5'])
    z_shuf, _, _, _ = R.sign_z(R.day_frames(rows, 'frgn_days5', shuffled))
    ok_b = (z_real is not None and z_shuf is not None
            and abs(z_real - z_shuf) > 1e-9)
    print(f'   ⓑ 변수가 정렬에 들어갔는가 : 실제 z {z_real:+.3f} vs '
          f'섞은 z {z_shuf:+.3f} '
          f'({"정상" if ok_b else "이상 — 변수가 비어 있다"})')

    z_leak, _, _, _ = R.sign_z(R.day_frames(rows, 'frgn_days5', joined_leak))
    ok_c = (z_leak is not None and z_real is not None
            and abs(z_leak - z_real) > 1e-9)
    print(f'   ⓒ 누출 검사 : D-1 z {z_real:+.3f} vs D포함 z {z_leak:+.3f} '
          f'({"정상 — 당일이 실제로 빠져 있다" if ok_c else "이상"})')

    n_ctrl = len(frames_by.get('score') or [])
    ok_d = n_ctrl > 0
    print(f'   ⓓ 대조군이 실제로 측정됐는가 : score 짝비교 {n_ctrl:,}일 '
          f'({"정상" if ok_d else "이상"}) — 판정 기준이 아니다')
    ok = ok_a and ok_b and ok_c and ok_d

    # ── 최소 가시 효과 — 표본을 키운 값어치가 있었는가 ──────────
    print()
    print('■ 이 표본의 최소 가시 효과 (R129 의 식 · 문턱 2.81)')
    _z_save = R.Z_PASS
    R.Z_PASS = Z_PASS                    # min_detectable 이 참조한다
    mdes = {}
    for key in R.VARS:
        m = R.min_detectable(frames_by[key], rng)
        mdes[key] = m
        print(f'   {key:<14} {("%d%%p" % m) if m else "20%p 로도 부족"}')
    R.Z_PASS = _z_save

    # ── 판정 ────────────────────────────────────────────────────
    print()
    print(f'■ 판정 (P1 z>={Z_PASS} · P2 방향 양수 · P3 train/valid 일치 · '
          f'P4 날짜>={MIN_DAYS})')
    verdict = {}
    for key in R.VARS:
        r = res[key]
        p1, p2 = bool(r['pass_p1']), bool(r['z'] is not None and r['z'] > 0)
        p3, p4 = bool(r.get('pass_p3')), bool(r['pass_p4'])
        allp = p1 and p2 and p3 and p4
        verdict[key] = dict(P1=p1, P2=p2, P3=p3, P4=p4, passed=allp)
        print(f'   {key:<14} P1 {"O" if p1 else "X"} · P2 {"O" if p2 else "X"}'
              f' · P3 {"O" if p3 else "X"} · P4 {"O" if p4 else "X"}'
              f'  → {"통과" if allp else "미달"}')
    n_pass = sum(1 for v in verdict.values() if v['passed'])
    print()
    print(f'   {len(R.VARS)}개 중 통과 {n_pass}개'
          + ('' if n_pass else ' — 기각하고 현행 유지한다'))

    # ── R131 과 나란히 ──────────────────────────────────────────
    prev = None
    p131 = os.path.join(PROJ, 'data', 'flow_rank_r131.json')
    if os.path.exists(p131):
        with open(p131, encoding='utf-8') as f:
            prev = json.load(f)
        print()
        print('■ 라운드 131 과 나란히 (대체하지 않는다)')
        print(f'   {"변수":<14}{"R131 z":>9}{"R131 일":>9}'
              f'{"R134 z":>9}{"R134 일":>9}{"하한 변화":>14}')
        for key in R.VARS:
            a = (prev.get('results') or {}).get(key) or {}
            b = res[key]
            m0 = (prev.get('min_detectable_pp') or {}).get(key)
            m1 = mdes.get(key)
            print(f'   {key:<14}{str(a.get("z")):>9}{a.get("days", 0):>9,}'
                  f'{str(b.get("z")):>9}{b.get("days", 0):>9,}'
                  f'{f"{m0}%p → {m1}%p":>14}')

    doc = {
        'made': date.today().isoformat(),
        'made_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'prereg': 'docs/PREREG_R134_FLOW_REPLICATION.md',
        'prereg_commit': PREREG_COMMIT,
        'replicates': 'docs/RESULT_R131_FLOW.md',
        'basis': '개발 구간(train+valid) · 판정완료 · 블라인드/전방 미사용',
        'leak_rule': '수급은 D-1 까지만 사용 (당일은 장 마감 후 공표)',
        'z_pass': Z_PASS, 'min_days': MIN_DAYS,
        'family_size': 10,
        'family_note': ('R131 의 5개 + R134 의 같은 5개 = 10. 같은 가설을 '
                        '두 번 재므로 문턱을 2.58 에서 2.81 로 **올렸다**.'),
        'vars': list(R.VARS),
        'join': dict(rows=len(rows), used=used, miss_ticker=miss_t,
                     miss_window=miss_d,
                     used_pct=round(used / max(1, len(rows)) * 100, 1)),
        'results': res, 'verdict': verdict, 'passed': n_pass,
        'min_detectable_pp': mdes,
        'prev_min_detectable_pp': (prev or {}).get('min_detectable_pp'),
        'selfcheck': dict(fpr=(round(fpr, 4) if fpr is not None else None),
                          fpr_ok=ok_a,
                          z_real=(round(z_real, 4)
                                  if z_real is not None else None),
                          z_shuffled=(round(z_shuf, 4)
                                      if z_shuf is not None else None),
                          var_used_ok=ok_b,
                          z_leak=(round(z_leak, 4)
                                  if z_leak is not None else None),
                          leak_ok=ok_c, control_days=n_ctrl,
                          control_ok=ok_d, ok=ok),
        'note': ('측정 전용 — 점수·게이트·문턱을 바꾸지 않는다. '
                 '라운드 131 을 대체하지 않는다.'),
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
