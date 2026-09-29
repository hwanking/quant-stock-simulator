# -*- coding: utf-8 -*-
"""
계층 혼합 확률 운영 표 생성 (라운드 59 채택분 — PREREG_R59 §3).

게이트는 train 적합·valid 1회로 통과했다 (Brier 0.2305 vs 0.2566 ·
보정이탈 12.1 vs 35.4%p · 유사사례 보유 부분집합에서도 압승). 운영 표는
관행대로 **개발 구간 전체(train+valid)** 로 재적합한다 — 게이트 측정은
끝났고 blind 는 여기서도 읽지 않는다.

출력: data/hier_prob_tables.json — 층별 (n, k) 원시 집계 + 변동성 3분위
+ m(=100, train 내부 Brier 로 선택 — 선택 기준이 사전등록에 명시되지
않았던 점은 문서에 공개한다).
"""
import glob
import io
import json
import os
import sys

import numpy as np

try:                       # 라운드 103 — 객체를 갈아끼우지 않는다
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:          # noqa: BLE001
    pass
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
P = os.path.join(PROJ, '.portfolio')

import trade_plan as tp                                       # noqa: E402

BANDS = ((0, 40), (40, 50), (50, 58), (58, 65), (65, 101))


def _today():
    """오늘 날짜 — 라운드 107. 박아 두면 다시 만들어도
    안 바뀌어 낡음을 알 수 없다 (라운드 102 miss_study).
    """
    import datetime as _dt
    return _dt.date.today().isoformat()


def band_of(s):
    for lo, hi in BANDS:
        if lo <= s < hi:
            return f'{lo}-{hi - 1}'
    return None


def build_states():
    """날짜 → 4상태 코드. 코스피 일봉은 `scripts/kospi_index` 한 곳에서 받는다 (라운드 330).

    재현이 목적이라 **캐시가 있으면 그대로** 쓰고 없을 때만 받는다(`prefer_cache=True`) — 종전엔
    `_probe/` 캐시를 직접 열어 이 PC 밖(깨끗한 체크아웃·클라우드)에서는 FileNotFoundError 였다.
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import kospi_index as _ki
    got = _ki.states(prefer_cache=True)
    if not got:
        raise SystemExit('코스피 일봉을 받지 못했다 — 측정 중단 (지어내지 않는다)')
    out = got[0]
    return out


def proxies_of(r):
    out = []
    if r.get('m10_above') and (r.get('range_pos') or 100) <= 50:
        out.append('눌림')
    if (r.get('range_pos') or 0) >= 80:
        out.append('돌파')
    if (r.get('bb_pos') or 100) <= 20:
        out.append('평균회귀')
    if 'BUY' in str(r.get('demark_state') or ''):
        out.append('DeMARK매수')
    return out


def main():
    states = build_states()
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
    with open(os.path.join(P, 'virtual_graded.jsonl'), encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:                                  # noqa: BLE001
                continue
            if r.get('split') == 'blind' or r.get('outcome') == 'OPEN':
                continue
            if not band_of(float(r.get('score') or 0)):
                continue
            elig.append(r)

    # ── 라운드 391 — 통계 행(`ledger_view.stat_rows` · 한 곳 · §4) · 업종은 원장 행 먼저 ─────────────
    #   ⚠️ 이 스크립트를 고쳐도 **운영 표(`data/hier_prob_tables.json` · 2026-08-09 · R59)는 다시 만들지 않았다.**
    #   그 표는 판정 중에 읽히는 확률의 재료라 다시 만들면 화면 확률이 움직인다 — 모델 변경이고(버전·사유)
    #   11-16 전방 재평가 동결 중이다. 여기 고친 것은 **다음에 누가 다시 만들 때** 같은 규칙(축척 어긋남·
    #   복사본 제외)을 타게 하는 것뿐이다. 업종도 종전엔 패치만 봤다(라운드 72 이후 행은 원장 행에 업종이
    #   있다 · R73·R217 의 규칙) — L2 층이 옛 행만 셌다.
    import ledger_view as _lv391
    _keys391 = _lv391.scale_mismatch_keys()
    _cnt391 = {}
    import bitemporal_engine as _be391

    def _row_sec(r):
        """원장 행의 업종 — 업종이 아닌 라벨(비교표 라벨 · R220)은 엔진의 판별로 거른다(§4)."""
        s = str(r.get('sector') or '').strip()
        if not s or s.startswith(_be391.SECTOR_LABEL_PREFIX) or s in _be391.SECTOR_NON_LABELS:
            return None
        return s

    rows = []
    for r in _lv391.stat_rows(elig, _keys391, _cnt391):
        k = (str(r['ticker']), str(r['date'])[:10])
        rows.append((r, band_of(float(r.get('score') or 0)), states.get(k[1]),
                     _row_sec(r) or patch.get(k)))
    print(f"통계에서 뺀 행: 축척 어긋남 {_cnt391.get('scale', 0):,} · 복사본 {_cnt391.get('dup', 0):,}"
          + ('' if _keys391 is not None else ' · 축척 감사 못 읽음 — 행 도장으로만 거름'))

    vols = [float(r['vol20']) for r, _, _, _ in rows
            if isinstance(r.get('vol20'), (int, float))]
    t1, t2 = float(np.percentile(vols, 33.3)), float(np.percentile(vols, 66.7))
    tab = {}

    def add(layer, key, r):
        a = tab.setdefault(f'{layer}|{key}', [0, 0])
        a[0] += 1
        a[1] += 1 if r.get('success') else 0

    for r, b, st, sec in rows:
        add('L5', b, r)
        if st:
            add('L4', f'{b}|{st}', r)
            for pxy in proxies_of(r):
                add('L4b', f'{b}|{st}|{pxy}', r)
        v = r.get('vol20')
        if isinstance(v, (int, float)):
            vb = '저' if v <= t1 else ('중' if v <= t2 else '고')
            add('L3', f"{b}|{r.get('market')}|{vb}", r)
        if sec and st:
            add('L2', f'{b}|{sec}|{st}', r)

    doc = dict(made=_today(), m=100,
               basis='개발 구간(train+valid) 재적합 · 블라인드 미접촉 · '
                     '게이트는 train 적합·valid 1회로 통과 (R59)',
               note='m=100 은 train 내부 Brier 로 선택 — 선택 기준이 '
                    '사전등록에 명시되지 않았던 점을 공개한다 (세 후보 '
                    '전부 내부검증에서 기준선 대비 우위였다)',
               vol_terciles=[round(t1, 5), round(t2, 5)],
               stat_excluded=dict(scale=int(_cnt391.get('scale', 0)),
                                  dup=int(_cnt391.get('dup', 0))),   # 라운드 391
               scale_audit_read=_keys391 is not None,
               cells={k: v for k, v in tab.items() if v[0] >= 1})
    dst = os.path.join(PROJ, 'data', 'hier_prob_tables.json')
    with open(dst, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False)
    print(f'셀 {len(doc["cells"]):,}개 → {dst}')


if __name__ == '__main__':
    main()
