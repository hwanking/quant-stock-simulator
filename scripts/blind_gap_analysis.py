# -*- coding: utf-8 -*-
"""
블라인드 갭 분석 — 검증 66.8% vs 블라인드 51.4% 괴리의 원인을 원장에서 직접 분해.

원칙: 블라인드 구간 통계는 **보고 전용**이다. 이 분석으로 모델을 고치지 않는다 —
고칠 가설은 학습·검증 구간에서 검증한 뒤 사전등록 절차(§58)로만 반영한다.
출력: docs/BLIND_GAP_REPORT.md (실측 수치만, 해석은 '가설'로 명시)
"""
from __future__ import annotations

import io
import json
import os
import sys
from collections import defaultdict

try:                       # 라운드 103 — 객체를 갈아끼우지 않는다
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:          # noqa: BLE001
    pass
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(BASE, '.portfolio', 'virtual_graded.jsonl')
OUT = os.path.join(BASE, 'docs', 'BLIND_GAP_REPORT.md')


def rate(rows):
    n = len(rows)
    if not n:
        return None, 0
    hit = sum(1 for r in rows if r.get('success'))
    return hit / n * 100, n


def fmt(rows):
    r, n = rate(rows)
    return f"{r:.1f}% (n={n})" if r is not None else f"— (n={n})"


def main():
    rows = []
    with open(LEDGER, encoding='utf-8') as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    by_split = defaultdict(list)
    for r in rows:
        by_split[r.get('split')].append(r)

    def cross(field):
        vals = sorted({str(r.get(field)) for r in rows})
        out = []
        for v in vals:
            line = {'key': v}
            for sp in ('train', 'valid', 'blind'):
                line[sp] = fmt([r for r in by_split[sp]
                                if str(r.get(field)) == v])
            line['n_blind'] = sum(1 for r in by_split['blind']
                                  if str(r.get(field)) == v)
            out.append(line)
        return out

    def dist(field, sp):
        sub = by_split[sp]
        n = len(sub) or 1
        cnt = defaultdict(int)
        for r in sub:
            cnt[str(r.get(field))] += 1
        return {k: f"{v} ({v / n * 100:.0f}%)" for k, v in sorted(cnt.items())}

    score_band = lambda s: ('60+' if s >= 60 else '55-59' if s >= 55
                            else '50-54' if s >= 50 else '<50')
    for r in rows:
        r['_band'] = score_band(int(r.get('score') or 0))

    lines = []
    w = lines.append
    w("# 블라인드 갭 분석 — 검증 66.8% vs 블라인드 51.4% (실측 분해)")
    w("")
    w("> 원천: `.portfolio/virtual_graded.jsonl` 전량. 이 보고서는 **관찰**이며,")
    w("> 블라인드 통계로 모델을 직접 고치지 않는다(§58 규율). 개선 가설은")
    w("> 학습·검증 구간에서 검증한 뒤 사전등록으로만 반영한다.")
    w("")
    w(f"- 전체: train {fmt(by_split['train'])} · valid {fmt(by_split['valid'])} · "
      f"blind {fmt(by_split['blind'])}")
    w("")
    w("## 1. 시장 국면 분포 — 구간마다 세상이 달랐다")
    for sp in ('train', 'valid', 'blind'):
        w(f"- {sp}: {dist('regime', sp)}")
    w("")
    w("## 2. 국면별 적중률 (split 교차)")
    w("")
    w("| 국면 | train | valid | blind |")
    w("|---|---|---|---|")
    for line in cross('regime'):
        w(f"| {line['key']} | {line['train']} | {line['valid']} | {line['blind']} |")
    w("")
    w("## 3. 점수대별 (split 교차)")
    w("")
    w("| 점수대 | train | valid | blind |")
    w("|---|---|---|---|")
    for line in cross('_band'):
        w(f"| {line['key']} | {line['train']} | {line['valid']} | {line['blind']} |")
    w("")
    w("## 4. 자산 유형별 (split 교차)")
    w("")
    w("| 유형 | train | valid | blind |")
    w("|---|---|---|---|")
    for line in cross('asset_type'):
        w(f"| {line['key']} | {line['train']} | {line['valid']} | {line['blind']} |")
    w("")
    w("## 5. 시장별 (split 교차)")
    w("")
    w("| 시장 | train | valid | blind |")
    w("|---|---|---|---|")
    for line in cross('market'):
        w(f"| {line['key']} | {line['train']} | {line['valid']} | {line['blind']} |")
    w("")
    w("## 6. 블라인드 실패 원인 상위")
    fails = defaultdict(lambda: [0, 0.0])
    for r in by_split['blind']:
        fc = str(r.get('failure_class') or '').strip()
        if fc and not r.get('success'):
            fails[fc][0] += 1
            fails[fc][1] += float(r.get('return_pct') or 0)
    for fc, (n, loss) in sorted(fails.items(), key=lambda x: x[1][1]):
        w(f"- {fc}: {n}건 · 수익률 합 {loss:+.1f}%p")
    w("")
    w("## 7. 관찰 요약 (가설 — 검증 전까지 채택 금지)")
    w("")
    # 자동 관찰: 국면 분포 차이
    bd = dist('regime', 'blind')
    vd = dist('regime', 'valid')
    w(f"- 블라인드 국면 분포 {bd} vs 검증 {vd} — 분포가 다르면 갭의 상당 부분은")
    w("  '모델 열화'가 아니라 '장세 변화'다. 국면별 교차표(§2)에서 같은 국면끼리")
    w("  비교했을 때도 갭이 남는지가 진짜 과적합 신호다.")
    w("- 60+ 구간(§3)은 블라인드 표본이 아직 작다 — 결론 유보, 축적 우선.")
    w("- 개선 후보(사전등록 대상): 국면 조건부 임계값, 유사패턴의 국면 가중,")
    w("  BEAR 구간 신호 차단 게이트 강화. 전부 학습·검증에서 먼저 검증한다.")
    w("")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))
    print(f"OK -> {OUT}")
    print("\n".join(lines[:40]))
    return 0


if __name__ == '__main__':
    sys.exit(main())
