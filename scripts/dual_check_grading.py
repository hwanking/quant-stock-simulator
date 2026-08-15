# -*- coding: utf-8 -*-
"""원장의 채점을 **독립 경로로 다시 매긴다** (라운드 101 · dual-check).

■ 왜 이것부터인가
  이 저장소의 모든 숫자(적중률·EV·리프트·유효표본·국면별 성적)가 원장의
  outcome 하나 위에 서 있다. 그게 틀리면 나머지가 전부 틀린다. 그런데
  라운드 100까지 그 값을 **다른 경로로 다시 매겨 본 적이 없었다.**

■ 무엇이 독립인가 (그리고 무엇은 아닌가)
  · 원장의 outcome  ← calibration_lab 이 채점할 때 받은 OHLC
  · bar_paths_*     ← path_recorder 가 **따로 받아** 신호일 대비 %로 기록
  코드도 실행 시점도 다르다. 다만 출처(네이버)는 같으므로 '원천 데이터가
  틀렸나'는 **못 잡는다.** 잡는 것은 봉 정렬·지평 오프바이원·목표/손절
  뒤바뀜 — 이 저장소에서 실제로 다 났던 종류다.

■ 사전등록 (재기 전에 정한 것 — §2)
  ① 판정 규칙은 원장이 쓰는 것을 그대로 쓴다. 새로 고르지 않는다:
     지평 안에서 고가가 목표에 먼저 닿으면 TARGET, 저가가 손절에 먼저
     닿으면 STOP, **같은 봉에서 둘 다 닿으면 성공으로 안 센다.**
  ② 대조 대상은 원장 결론이 TARGET/STOP 인 건만 (OPEN 은 지평 미완).
  ③ 합격 기준: **불일치율 ≤ 1.0%.** 넘으면 합격시키지 않는다.
  ④ **대조 건수 < 1,000 이면 '못 쟀다'로 적고 판정하지 않는다.**
  ⑤ 불일치가 나오면 성격을 밝힌다 — 쏠리는지 흩어지는지 분포로.

■ 첫 측정에서 내가 틀렸던 것 (기록해 둔다)
  허용오차 없이 재니 불일치 244건(0.138%)이 나왔다. 그런데 그 절반이
  **내 대조의 부작용**이었다. path_recorder 는 봉 %를 `round(...,3)` 으로
  저장하는데 나는 `저가 ≤ 손절` 을 엄격히 따졌다.

      000080.KS 2018-05-14 · 손절 20,700/21,400 = -3.27103%
      경로 5봉 저가 -3.271 (반올림)  →  -3.271 > -3.27103 이라 '미도달'
      원장의 mae 는 정확히 -3.27 이고 그 봉에서 STOP 이라 했다.

  두 원장은 같은 봉을 같게 보고 있었고 갈린 것은 내 비교였다. 허용오차를
  **저장 정밀도에서 유도**하니(EPS=0.0005) 110건(0.062%)으로 줄었다.

    C:/Python314/python.exe scripts/dual_check_grading.py
"""
import collections
import glob
import io
import json
import os
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(PROJ, '.portfolio')
OUT = os.path.join(PROJ, 'data', 'dual_check_grading.json')

MISMATCH_MAX = 0.010      # 사전등록 ③
MIN_N = 1000              # 사전등록 ④
#: 저장 정밀도에서 유도한 허용오차 — 감으로 고른 숫자가 아니다.
#: path_recorder 가 `round(pct, 3)` 로 쓰므로 반올림 오차는 최대 0.0005%p.
EPS = 0.0005


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def _rows(path):
    with open(path, encoding='utf-8', errors='replace') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                yield json.loads(ln)
            except Exception:                                  # noqa: BLE001
                continue


def load():
    led = {}
    for r in _rows(os.path.join(P, 'virtual_graded.jsonl')):
        led[(str(r.get('ticker')), str(r.get('date'))[:10])] = r
    paths = {}
    for p in sorted(glob.glob(os.path.join(P, 'bar_paths_s*.jsonl'))):
        for q in _rows(p):
            paths[(str(q.get('ticker')), str(q.get('date'))[:10])] = q
    return led, paths


def regrade(row, path):
    """경로만 보고 다시 매긴다 — 원장의 outcome 을 읽지 않는다.

    목표·손절은 원장이 **그때 내놓은 값**을 쓴다 (사후에 유리하게 고르지
    않는다). 판정에 쓰는 것은 경로의 고가·저가뿐이다.
    """
    px, tgt, stp = row.get('price'), row.get('target'), row.get('stop')
    if not px or tgt is None or stp is None:
        return None, '목표·손절·가격이 비었다'
    try:
        t_pct = float(tgt) / float(px) * 100.0 - 100.0
        s_pct = float(stp) / float(px) * 100.0 - 100.0
    except (TypeError, ValueError, ZeroDivisionError):
        return None, '퍼센트 환산 불가'
    bars = (path.get('bars') or [])[:int(row.get('horizon_days') or 20)]
    if not bars:
        return None, '봉이 없다'
    for i, b in enumerate(bars, 1):
        hi, lo = b[1], b[2]
        hit_t = hi is not None and hi >= t_pct - EPS
        hit_s = lo is not None and lo <= s_pct + EPS
        if hit_t and hit_s:
            return ('STOP', i), ''        # 같은 봉 동시 도달 — 성공 아님
        if hit_t:
            return ('TARGET', i), ''
        if hit_s:
            return ('STOP', i), ''
    return ('OPEN', 0), ''


def run():
    led, paths = load()
    both = sorted(set(led) & set(paths))
    print(f'원장 {len(led):,} · 경로 {len(paths):,} · 겹침 {len(both):,}')

    agree = dis = skipped = 0
    kinds, bar_gap = collections.Counter(), collections.Counter()
    mis_ticker = collections.Counter()
    for k in both:
        row, path = led[k], paths[k]
        out = str(row.get('outcome') or '')
        if out not in ('TARGET', 'STOP'):
            skipped += 1
            continue
        got, _why = regrade(row, path)
        if got is None:
            skipped += 1
            continue
        mine, bar_i = got
        if mine == out:
            agree += 1
            tb = row.get('touched_bar')
            if isinstance(tb, int) and tb:
                bar_gap[bar_i - tb] += 1
        else:
            dis += 1
            kinds[f'{out}→{mine}'] += 1
            mis_ticker[k[0]] += 1

    n = agree + dis
    doc = {
        'n_compared': n, 'agree': agree, 'mismatch': dis,
        'mismatch_rate': (dis / n) if n else None,
        'skipped': skipped,
        'same_bar_rate': (bar_gap.get(0, 0) / max(1, sum(bar_gap.values()))),
        'kinds': dict(kinds.most_common()),
        'top_mismatch_tickers': dict(mis_ticker.most_common(8)),
        'n_mismatch_tickers': len(mis_ticker),
        'threshold': MISMATCH_MAX, 'min_n': MIN_N, 'eps': EPS,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)

    print(f'\n대조 {n:,}건 · 건너뜀 {skipped:,}건')
    if n < MIN_N:
        print(f'>> 못 쟀다 — {n:,} < {MIN_N:,}. 판정하지 않는다.')
        return 2
    print(f'일치 {agree:,} · 불일치 {dis:,} → {dis / n:.3%} '
          f'(기준 {MISMATCH_MAX:.1%})')
    print(f'도달 봉까지 같은 비율 {doc["same_bar_rate"]:.1%}')
    if kinds:
        print(f'  방향: {dict(kinds.most_common())}')
        print(f'  불일치가 몰린 종목 {len(mis_ticker)}개 — '
              f'{dict(mis_ticker.most_common(5))}')
    print(f'저장: {OUT}')
    if dis / n <= MISMATCH_MAX:
        print(f'\n>> 통과 — {n:,}건을 독립 경로로 다시 매겨 '
              f'불일치 {dis / n:.3%}.')
        return 0
    print(f'\n>> 기준 미달 — {dis / n:.3%} > {MISMATCH_MAX:.1%}. '
          f'기준을 내리지 않는다.')
    return 1


if __name__ == '__main__':
    _utf8()
    sys.exit(run())
