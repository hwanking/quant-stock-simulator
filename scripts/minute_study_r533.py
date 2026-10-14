# -*- coding: utf-8 -*-
"""라운드 533 — 장중 규칙을 증권거래세가 없는 국내 주식형 ETF 에 (사전등록 `docs/PREREG_R533_ETF_INTRADAY.md` · 결과 전 커밋).

E1 장중 방향(첫 봉 시가 → 15:30 종가) · E2 장중 모멘텀(첫 30분 양수면 15:00 → 15:30). 구간 가격·유동성·구간·부트스트랩은 라운드 532 의
함수를 **그대로 부른다**(베끼지 않는다). 대상은 고정 목록 ∩ 라운드 482 의 국내 주식형 ETF 분류. 비용 벽 0.03%(민감도 0.21%).
블라인드(2026-05-01~)는 `--blind` 없이는 읽지 않는다. 읽기만 하고 결과 파일 하나를 쓴다.
"""
from __future__ import annotations

import argparse
import bisect
import collections
import datetime as _dt
import io
import json
import os
import statistics
import sys
import time

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
sys.path.insert(0, os.path.join(PROJ, 'scripts'))
import minute_study_r532 as M  # noqa: E402

COST_WALL = 0.03            # 수수료만 · 체결 손해 0(전략에 유리한 쪽) — 증권거래세 없음(라운드 482)
COST_OPS = 0.21             # 라운드 482 의 ETF 운영 비용(수수료 0.03 + 체결 손해 0.18) — 민감도만
Z_BONF = 2.25               # Bonferroni(2) 양측 · 올림


def verdict(s):
    tr = s.get('train') or {}
    if tr.get('ci95') and tr['ci95'][1] < 0:
        return 'R0 접음 — 학습 구간 95% 구간 위끝이 0 아래'

    def ok(x):
        return (x.get('n_dates') or 0) >= M.DATE_FLOOR and x.get('mean') is not None and x['mean'] > 0 and x.get('ci95') \
            and x['ci95'][0] > 0 and (x.get('z') or 0) >= Z_BONF
    if all(ok(s.get(k) or {}) for k in ('train', 'valid', 'blind')):
        return '(가) 후보 — 전방 모의 30거래일을 새 사전등록으로'
    if ok(tr) and ok(s.get('valid') or {}):
        return '(나) 보류 — 블라인드를 기다린다'
    return '(다) 접음'


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--blind', action='store_true', help='블라인드(2026-05-01 부터)도 읽는다 — 백필이 끝난 뒤에만')
    ap.add_argument('--out', default=os.path.join(PROJ, 'data', 'minute_study_r533.json'))
    ap.add_argument('--root', default=None, help='시험용 — 분봉 폴더')
    ap.add_argument('--codes', default=None, help='시험용 — 대상 코드(쉼표) · 주면 분류를 안 읽는다')
    a = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError):
        pass
    t0 = time.time()
    root = a.root or M.ROOT
    if a.codes:
        codes = [c.strip() for c in a.codes.split(',') if c.strip()]
    else:
        from collect_minute_bars import pool_codes
        from cost_paths_r482 import domestic_equity_codes
        dom = domestic_equity_codes()
        pool = pool_codes()
        if not dom or not pool:
            print('분류표 또는 고정 목록을 못 읽었다 — 멈춘다')
            return 2
        codes = [c for c in pool if c in dom]
    feats, bad, blind_dropped, day_union = {}, 0, 0, set()
    for code in codes:
        p = os.path.join(root, f'{code}.jsonl')
        if not os.path.exists(p):
            continue
        days, b1, b2 = M.read_code(p, a.blind)
        bad += b1
        blind_dropped += b2
        feats[code] = {d: M.day_features(bs) for d, bs in days.items() if bs}
        day_union.update(feats[code])
    cal = sorted(day_union)
    first_any = collections.defaultdict(lambda: '99:99')
    last_any = collections.defaultdict(str)
    for fd in feats.values():
        for d, f in fd.items():
            first_any[d] = min(first_any[d], f['first_t'])
            last_any[d] = max(last_any[d], f['last_t'])
    normal = [d for d in cal if first_any[d] == '09:00' and last_any[d] == '15:30']
    normal_set = set(normal)
    prev_of = {cal[i]: cal[i - 1] for i in range(1, len(cal))}

    def liquid(code, d):
        fd = feats[code]
        i = bisect.bisect_left(cal, d)
        prior = cal[max(0, i - M.LIQ_DAYS):i]
        if len(prior) < M.LIQ_DAYS:
            return False
        amts = [fd[x]['amt'] for x in prior if x in fd and fd[x].get('amt') is not None]
        return len(amts) >= M.LIQ_DAYS and statistics.mean(amts) >= M.LIQ_FLOOR

    e1, e2, e2_neg = collections.defaultdict(list), collections.defaultdict(list), collections.defaultdict(list)
    n_liq = 0
    for code, fd in feats.items():
        for d, f in fd.items():
            if d not in normal_set or not liquid(code, d):
                continue
            n_liq += 1
            r1 = M.ret(f['open'], f['close'])
            if r1 is not None:
                e1[d].append(r1)
            pd_ = prev_of.get(d)
            pf = fd.get(pd_) if pd_ else None
            if pf and pd_ in normal_set:
                r30, r3 = M.ret(pf['close'], f['p0930']), M.ret(f['p1500'], f['close'])
                if r30 is not None and r3 is not None and f['seg'][12][2]:
                    if r30 > 0:
                        e2[d].append(r3)
                    elif r30 < 0:
                        e2_neg[d].append(r3)
    res = {}
    for name, tb, extra in (('E1', e1, None), ('E2', e2, e2_neg)):
        s = M.summarize(tb, COST_WALL, normal)
        res[name] = dict(wall=s, ops=M.summarize(tb, COST_OPS, normal), verdict=verdict(s), self_gross=M.summarize(tb, 0.0, normal))
        if extra is not None:
            res[name]['compare_gross'] = M.summarize(extra, 0.0, normal)
    out = dict(made=_dt.datetime.now().isoformat(timespec='seconds'), prereg='docs/PREREG_R533_ETF_INTRADAY.md', blind_read=bool(a.blind),
               codes=len(codes), codes_with_bars=len(feats), days=len(cal), normal_days=len(normal),
               abnormal_days=[d for d in cal if d not in normal_set], first_day=(cal[0] if cal else None),
               last_day=(cal[-1] if cal else None), etf_days_liquid=n_liq, bad_lines=bad, blind_lines_dropped=blind_dropped,
               cost_wall=COST_WALL, cost_ops=COST_OPS, z_bonf=Z_BONF, results=res, seconds=round(time.time() - t0, 1))
    tmp = a.out + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    os.replace(tmp, a.out)
    for q in ('E1', 'E2'):
        print(q, res[q]['verdict'])
        for name, _a, _b in M.SPLITS:
            x = res[q]['wall'].get(name) or {}
            g = res[q]['self_gross'].get(name) or {}
            if x.get('n_dates'):
                print(f"   {name}: 날짜 {x['n_dates']} · 거래 {x['trades']:,} · 0.03% 뺀 날짜평균 {x['mean']:+.3f}% · 구간 "
                      f"{x['ci95'] and [round(v, 3) for v in x['ci95']]} · z {x['z'] and round(x['z'], 2)} · 비용 전 {g.get('mean') and round(g['mean'], 3)}")
    print(f"끝 · {out['seconds']}초 · ETF {len(feats)}/{len(codes)} · 날 {len(cal)}(정상 {len(normal)}) · 유동성 통과 ETF-날 {n_liq:,}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
