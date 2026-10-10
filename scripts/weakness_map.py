# -*- coding: utf-8 -*-
"""
라운드 69 — 취약구간 지도 (관측 전용).

"어디서 약한가"만 그린다. 점수·게이트를 바꾸지 않는다 — 8/23 이후
무엇부터 연구할지 순서를 정하는 근거로만 쓴다.

축 (전부 이미 기록된 필드):
  · 시장 국면 (코스피 4상태 · R52 규칙 재사용)
  · 변동성 3분위 (train 기준)
  · 진입 위치 (entry_zone · 원장 기록)
  · 업종 (하위점수 패치)
  · 점수대
  · 유사표본 구간 (eff_sample)

각 칸: n · 에피소드 n · 적중 · Wilson 하한 · 비용후EV · PF · 최대낙폭 중앙
"""
import glob
import io
import json
import math
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import numpy as np

try:                       # 라운드 103 — 객체를 갈아끼우지 않는다
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:          # noqa: BLE001
    pass
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
P = os.path.join(PROJ, '.portfolio')
H, COST = 20, 0.36
# 라운드 422 — 이 지도의 '시장 국면' 칸을 매매 지시서·포트폴리오 견해가 읽게 됐다. 화면에 비용이 둘이 되지 않게 운영 비용을
#   쓰고(라운드 350 · 업종 성적은 라운드 391 이 먼저 옮겼다) 쓴 비용을 산출물에 적는다(`cost_pct`).
try:
    import verdict_core as _vc422                              # noqa: E402
    COST = float(_vc422.COST_PCT)
except Exception:                                              # noqa: BLE001
    pass
MIN_N = 60

import trade_plan as tp                                       # noqa: E402
import forward_eval as _fe                                     # noqa: E402

#: 재평가일은 여기서 만들지 않는다 (라운드 78 단일 출처). 라운드 93 에서
#: 이 파일이 '8/23' 을 화면과 data/weakness_map.json 에 계속 찍고 있는 것을
#: 찾았다 — 회귀가 검사 대상 파일을 **손으로 다섯 개** 적어 둔 탓이다.
_FE = _fe.eval_date() or '재평가일 미기록'

ST_KO = {'ABOVE_BOTH': '상승', 'REBOUND': '반등초기', 'PULLBACK': '조정',
         'BEAR': '약세'}


def wilson_low(k, n, z=1.96):
    if n == 0:
        return 0.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - m) / d * 100.0


def ep_n(sub):
    last, n = {}, 0
    for r in sorted(sub, key=lambda x: (str(x['ticker']), str(x['date']))):
        tk = str(r['ticker'])
        try:
            dd = date.fromisoformat(str(r['date'])[:10])
        except ValueError:
            continue
        if tk not in last or (dd - last[tk]) > timedelta(days=35):
            n += 1
            last[tk] = dd
    return n


def states():
    """(날짜 → 4상태 코드, 출처, 마지막 날짜). 코스피 일봉은 `scripts/kospi_index` 한 곳 (라운드 330).

    ⚠️ 종전엔 `_probe/kospi_daily_cache.json` 을 **직접** 열었다 — gitignored 라 클라우드에는 없고
    쓰는 곳도 이 스크립트가 아니어서, 자동 축적에서 이 파일은 매번 FileNotFoundError 로 죽었고
    `|| true` 가 삼켰다. 원장이 801줄 자란 2026-09-16 실행에서 신선도 검사가 처음 붉어져 드러났다.
    관측 산출물이므로 **먼저 받고**(캐시는 2026-08-07 에 멈춰 있었다) 못 받으면 캐시, 둘 다 없으면
    멈춘다 — 국면 없는 지도를 만들지 않는다(§3).
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import kospi_index as _ki
    got = _ki.states(prefer_cache=False)
    if not got:
        raise SystemExit('코스피 일봉을 받지 못했다(실시간·캐시 모두) — 취약구간 지도를 만들지 않는다')
    out = got
    return out


def cell(sub):
    n = len(sub)
    k = sum(1 for r in sub if r.get('success'))
    net = np.array([float(r['return_pct']) - COST for r in sub])
    pos, neg = float(net[net > 0].sum()), float(-net[net < 0].sum())
    mae = ([min(r['_lo']) for r in sub if '_lo' in r] or [float('nan')])
    return dict(n=n, ep=ep_n(sub), hit=round(k / n * 100, 1),
                wilson=round(wilson_low(k, n), 1),
                ev=round(float(net.mean()), 3),
                pf=round(pos / neg, 2) if neg > 0 else None,
                mae=round(float(np.median(mae)), 2))


def main():
    stt, idx_src, idx_last = states()
    print(f"코스피 일봉 — {idx_src} · 마지막 {idx_last}")
    paths = {}
    for path in sorted(glob.glob(os.path.join(P, 'bar_paths_s*.jsonl'))):
        with open(path, encoding='utf-8') as f:
            for ln in f:
                try:
                    q = json.loads(ln)
                    paths[(q['ticker'], q['date'])] = q
                except Exception:                              # noqa: BLE001
                    continue
    patch = {}
    for path in sorted(glob.glob(os.path.join(P, 'subscore_patch*.jsonl'))):
        with open(path, encoding='utf-8') as f:
            for ln in f:
                try:
                    q = json.loads(ln)
                    patch[(q['ticker'], q['date'])] = q.get('sector')
                except Exception:                              # noqa: BLE001
                    continue

    elig = []
    _ledger_rows = 0        # 원장이 몇 줄일 때 잰 것인지 — 낡음 판정의 근거
    with open(os.path.join(P, 'virtual_graded.jsonl'), encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:                                  # noqa: BLE001
                continue
            _ledger_rows += 1
            if (r.get('split') == 'blind' or r.get('outcome') == 'OPEN'
                    or float(r.get('score') or 0) < 58.0):
                continue
            elig.append(r)

    # ── 라운드 391 — 통계 행(`ledger_view.stat_rows` · 한 곳 · §4) ─────────────────────────────
    #   운영 보정표(랩)·화면 통계와 같은 규칙으로 센다: 진입가 축척이 어긋난 행(지어낸 승패 · R364)과 시장
    #   접미사만 다른 복사본(R390)을 셈에서 뺀다(원장 행은 안 지운다 · R197) · 뺀 수를 산출물에 적는다.
    import ledger_view as _lv391
    _keys391 = _lv391.scale_mismatch_keys()
    _cnt391 = {}
    # 업종은 **원장 행을 먼저**, 없으면 패치 (라운드 73·217 의 규칙). ⚠️ 라운드 391 — 여기가 패치만 봤다.
    #   라운드 72 이후 랩은 업종을 원장 행에 직접 쓰고 패치는 그 전 60,462건용이라, 원장이 25만 행이 돼도
    #   이 지도의 업종 칸은 옛 행만 셌다(2026-09-30 실측: 반도체 n 5,751 · 같은 모집단의 업종 성적은 11,808).
    #   업종이 아닌 라벨(비교표 라벨 · R220)은 엔진의 판별로 거른다(§4 — 두 벌 금지).
    import bitemporal_engine as _be391
    sec_src = dict(row=0, patch=0, none=0, bad_label=0)

    def _sec391(r, k):
        s = str(r.get('sector') or '').strip()
        if s and (s.startswith(_be391.SECTOR_LABEL_PREFIX) or s in _be391.SECTOR_NON_LABELS):
            sec_src['bad_label'] += 1
            return None
        if s:
            sec_src['row'] += 1
            return s
        s = patch.get(k)
        if s:
            sec_src['patch'] += 1
            return s
        sec_src['none'] += 1
        return None

    rows = []
    for r in _lv391.stat_rows(elig, _keys391, _cnt391):
        k = (str(r['ticker']), str(r['date'])[:10])
        p = paths.get(k)
        if p and p.get('n_bars', 0) >= H:
            r['_lo'] = [b[2] for b in p['bars'][:H]]
        r['_st'] = stt.get(str(r['date'])[:10])
        r['_sec'] = _sec391(r, k)
        rows.append(r)
    print(f"통계에서 뺀 행: 축척 어긋남 {_cnt391.get('scale', 0):,} · 복사본 {_cnt391.get('dup', 0):,}"
          + ('' if _keys391 is not None else ' · 축척 감사 못 읽음 — 행 도장으로만 거름'))
    print(f"업종 출처: 원장 행 {sec_src['row']:,} · 패치 {sec_src['patch']:,} · 없음 {sec_src['none']:,} · "
          f"업종 아닌 라벨 {sec_src['bad_label']:,}")
    vols = [float(r['vol20']) for r in rows
            if isinstance(r.get('vol20'), (int, float))]
    t1, t2 = np.percentile(vols, 33.3), np.percentile(vols, 66.7)
    base = cell(rows)
    # 국면이 빈 행은 '약세·상승이 아닌 것'이 아니라 **지수가 그 날짜를 못 덮은 것**이다 — 세어 적는다(§3)
    no_state = sum(1 for r in rows if r.get('_st') is None)
    print(f"국면 미기록 {no_state:,}행 / {len(rows):,}행 (지수 일봉이 덮지 못한 기준일)")
    print(f"기준선 (매수권 전체) n {base['n']:,} · 적중 {base['hit']}% · "
          f"EV {base['ev']:+.3f} · PF {base['pf']}\n")

    axes = {
        '시장 국면': lambda r: ST_KO.get(r['_st']),
        '변동성': lambda r: (None if not isinstance(r.get('vol20'),
                                                (int, float))
                          else '저변동' if r['vol20'] <= t1
                          else '중변동' if r['vol20'] <= t2 else '고변동'),
        '진입 위치': lambda r: str(r.get('entry_zone') or '')[:14] or None,
        '업종': lambda r: r['_sec'],
        '점수대': lambda r: f"{int(float(r.get('score') or 0)) // 5 * 5}점대",
        '유사표본': lambda r: (None if not isinstance(r.get('eff_sample'),
                                                 (int, float))
                           else '표본<30' if r['eff_sample'] < 30
                           else '표본30~99' if r['eff_sample'] < 100
                           else '표본100+'),
    }
    out = {}
    weak = []
    for ax, fn in axes.items():
        g = defaultdict(list)
        for r in rows:
            v = fn(r)
            if v:
                g[v].append(r)
        cells = {k: cell(v) for k, v in g.items() if len(v) >= MIN_N}
        if not cells:
            continue
        out[ax] = cells
        print(f'■ {ax}')
        for k in sorted(cells, key=lambda x: cells[x]['ev']):
            c = cells[k]
            mark = '  ← 취약' if c['ev'] < base['ev'] - 0.3 else ''
            print(f"  {k:16s} n {c['n']:>6,}(ep {c['ep']:>5,}) · "
                  f"적중 {c['hit']:5.1f}%(W {c['wilson']:4.1f}) · "
                  f"EV {c['ev']:+7.3f} · PF {str(c['pf']):>5} · "
                  f"MAE {c['mae']:+6.2f}%{mark}")
            if c['ev'] < base['ev'] - 0.3:
                weak.append((ax, k, c['ev'], c['n']))
        print()

    # ── 라운드 474 — '시장 국면' 칸을 학습·검증으로 갈라 **날짜 수**와 같이 싣는다(판정·문턱 없음) ──────────────────────
    #   위 칸은 개발 구간(학습+검증)을 합친 수다. 시장 수준 축은 날짜가 표본인데(R45) 합친 수만 내면 짧은 검증 구간이 칸
    #   하나를 끌어올린 것이 안 보인다 — 2026-10-10 실측 '조정' 비용 뺀 +0.33% 는 학습 288일 +0.15% · 검증 16일 +2.02% 였고,
    #   매매 지시서가 그 칸을 *"4상태 중 유일하게 양수"* 로 적고 있었다. 화면이 두 구간을 날짜 수와 함께 같이 적게 한다.
    split_cells = {}
    for k_ko in out.get('시장 국면', {}):
        per = {}
        for sp in ('train', 'valid'):
            sub = [r for r in rows if ST_KO.get(r['_st']) == k_ko and r.get('split') == sp]
            if sub:
                c = cell(sub)
                per[sp] = dict(n=c['n'], dates=len({str(r['date'])[:10] for r in sub}), hit=c['hit'], ev=c['ev'])
        if per:
            split_cells[k_ko] = per
    if split_cells:
        print('■ 시장 국면 — 구간별 (날짜 수)')
        for k_ko, per in split_cells.items():
            print('  ' + k_ko + ' · ' + ' · '.join(f"{sp} {v['dates']}일 n {v['n']:,} EV {v['ev']:+.3f}"
                                                   for sp, v in per.items()))
        print()

    print(f'■ 가장 약한 칸 ({_FE} 이후 연구 우선순위 후보)')
    for ax, k, ev, n in sorted(weak, key=lambda x: x[2])[:8]:
        print(f'  {ax:10s} {k:16s} EV {ev:+.3f} (n {n:,})')

    dst = os.path.join(PROJ, 'data', 'weakness_map.json')
    with open(dst, 'w', encoding='utf-8') as f:
        # ⚠️ 라운드 102 — 여기도 `made='2026-08-10'` 이 박혀 있었다
        #   (miss_study 와 같은 자리). 다시 만들어도 날짜가 안 바뀌니
        #   낡았는지 알 수 없었다. 언제 돌렸는지와 **무엇으로 쟀는지**를
        #   같이 적는다 — ledger_rows 로 낡음을 값으로 판정한다.
        json.dump(dict(made=date.today().isoformat(),
                       made_at=datetime.now(timezone.utc)
                       .isoformat(timespec='seconds'),
                       ledger_rows=_ledger_rows,
                       joined_n=len(rows),
                       cost_pct=COST,          # 라운드 422 — 'ev' 를 뺀 비용(화면이 이름과 함께 적는다)
                       # 라운드 391 — 통계 행 규칙으로 뺀 수 · 업종 출처(행 → 패치)
                       stat_excluded=dict(scale=int(_cnt391.get('scale', 0)),
                                          dup=int(_cnt391.get('dup', 0))),
                       scale_audit_read=_keys391 is not None,
                       sector_source=sec_src,
                       index_source=idx_src, index_last=idx_last,
                       regime_missing_n=no_state,
                       base=base, axes=out,
                       axes_split={'시장 국면': split_cells},   # 라운드 474 — 구간별 · 날짜 수
                       min_n=MIN_N,
                       note='관측 전용 — 점수·게이트를 바꾸지 않는다. '
                            f'{_FE} 이후 연구 순서를 정하는 근거로만 쓴다.',
                       weakest=[dict(axis=a, cell=k, ev=e, n=n)
                                for a, k, e, n in
                                sorted(weak, key=lambda x: x[2])[:10]]),
                  f, ensure_ascii=False, indent=1)
    print(f'\n저장: {dst}')


if __name__ == '__main__':
    main()
