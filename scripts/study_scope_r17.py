# -*- coding: utf-8 -*-
"""
스터디 사전 점검 — 무엇이 측정 **가능한가**.

라운드 3 에서 '구조적으로 측정 불가능한 실험'을 돌린 적이 있다. 같은 실수를
반복하지 않기 위해, 설계 전에 표본이 실제로 몇 건인지부터 센다.

이번 스터디의 주제는 사용자가 말한 그대로다:
  · 얼마에 사고  → 진입가(무릎)
  · 얼마에 팔고  → 목표가(어깨)
  · 손실 안 보게 → 손절폭·MAE
  · 지금 사도 되나 → 국면·시장상태 게이트

핵심 자산은 원장의 **mfe_pct / mae_pct** 다. 이게 있으면 목표·손절을 바꿔
가며 재시뮬레이션할 수 있다 — 파이프라인을 다시 돌리지 않아도 된다.

다만 한계가 하나 있고, 이걸 먼저 못 박는다:
  MFE/MAE 는 '얼마나 갔나'만 알려주고 '어느 쪽이 **먼저**' 닿았는지는
  모른다. 원래 조합(target/stop)에서만 outcome 이 그 답을 준다.
  → 목표·손절을 둘 다 바꾸면 일부 사례가 **판정 모호**해진다.
  → 모호분은 최선/최악 두 경계를 모두 계산하고, 채택은 **최악 기준**으로만
    한다. 좋게 보이는 쪽을 고르면 그건 연구가 아니라 희망이다.
"""
import io
import json
import os
import sys
from collections import Counter, defaultdict

try:                       # 라운드 103 — 객체를 갈아끼우지 않는다
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:          # noqa: BLE001
    pass
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LED = os.path.join(BASE, '.portfolio', 'virtual_graded.jsonl')

VOL_CUT = 0.03          # 하루 표준편차 3% — 차분함/거침 (라운드 14 채택 기준)
REG_KO = {'BULL': '상승', 'SIDEWAYS': '옆걸음', 'BEAR': '하락'}


def load():
    out = []
    with open(LED, encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except Exception:
                pass
    return out


def cell6(r):
    """국면 6칸 — 지수 방향 × 종목 변동성 (라운드 14 채택)."""
    rg = r.get('regime')
    if not rg:
        return None
    v = r.get('vol20')
    if v is None:
        return None
    return f"{'거친' if v >= VOL_CUT else '차분한'} {REG_KO.get(rg, rg)}"


#: 매수권 문턱 — 라운드 2 에서 채택한 확장 신호 기준(58+).
#  60+ 는 실전 23건뿐이라 국면 6칸으로 나누면 어느 칸도 판정이 안 된다.
#  국면 표(화면)도 58+ 를 쓰므로 여기에 맞춘다.
BUY = 58


def is_buy(r):
    """추천(매수권) 사례인가 — 화면의 국면 표와 같은 기준."""
    return (r.get('score') or 0) >= BUY and r.get('outcome') in ('TARGET', 'STOP')


rows = load()
print(f'원장 {len(rows):,}건\n')

print('■ 1. 매수권(추천) 신호가 구간별로 몇 건인가')
buy = [r for r in rows if is_buy(r)]
by_split = Counter(r['split'] for r in buy)
print(f'  전체 추천 {len(buy):,}건 = ' +
      ' · '.join(f'{k} {by_split[k]:,}' for k in ('train', 'valid', 'blind')))
print(f'  (신호율 {len(buy) / len(rows) * 100:.1f}%)')

print('\n■ 2. 국면 6칸 × 구간 — 여기가 병목이다')
tab = defaultdict(Counter)
for r in buy:
    c = cell6(r)
    if c:
        tab[c][r['split']] += 1
none_rg = sum(1 for r in buy if not cell6(r))
print(f'  국면 미상 추천 {none_rg:,}건 (전체 추천의 '
      f'{none_rg / max(1, len(buy)) * 100:.0f}%) — 이건 못 쓴다')
print(f'  {"칸":12s} {"학습":>7s} {"검증":>7s} {"실전":>7s}   판정 가능?')
for c in sorted(tab, key=lambda x: -tab[x]['blind']):
    t, v, b = tab[c]['train'], tab[c]['valid'], tab[c]['blind']
    ok = ('가능' if b >= 30 else '실전 표본 부족' if b > 0 else '실전 없음')
    print(f'  {c:12s} {t:>7,} {v:>7,} {b:>7,}   {ok}')

print('\n■ 3. 목표·손절을 바꿨을 때 판정이 모호해지는 비율')
# 현행: target/stop 이 price 대비 몇 %인지
amb = ok_cnt = 0
tgt_pcts, stop_pcts = [], []
for r in buy:
    p, t, s = r.get('price'), r.get('target'), r.get('stop')
    if not (p and t and s):
        continue
    tp = (t / p - 1) * 100
    sp = (1 - s / p) * 100
    tgt_pcts.append(tp)
    stop_pcts.append(sp)
    mfe, mae = r.get('mfe_pct'), r.get('mae_pct')
    if mfe is None or mae is None:
        continue
    # 목표를 낮추고 손절을 좁히면 둘 다 닿는 사례가 늘어난다
    if mfe >= tp * 0.7 and abs(mae) >= sp * 0.7:
        amb += 1
    else:
        ok_cnt += 1
tot = amb + ok_cnt
print(f'  현행 목표폭 중앙값 {sorted(tgt_pcts)[len(tgt_pcts) // 2]:+.2f}% · '
      f'손절폭 중앙값 -{sorted(stop_pcts)[len(stop_pcts) // 2]:.2f}%')
print(f'  현행 손익비(중앙값 기준) '
      f'{sorted(tgt_pcts)[len(tgt_pcts) // 2] / sorted(stop_pcts)[len(stop_pcts) // 2]:.2f} : 1')
print(f'  목표 0.7배·손절 0.7배로 바꾸면 판정 모호 {amb:,}/{tot:,} '
      f'({amb / max(1, tot) * 100:.0f}%)')
print('  → 모호분은 최선·최악 두 경계로 계산하고 채택은 최악 기준으로만 한다')

print('\n■ 4. 진입가 연구가 가능한가 — 진입 위치(entry_zone) 분포')
ez = Counter(str(r.get('entry_zone')) for r in buy)
for k, v in ez.most_common():
    ezb = sum(1 for r in buy
              if str(r.get('entry_zone')) == k and r['split'] == 'blind')
    print(f'  {k:34s} {v:>6,}건 (실전 {ezb:,})')

print('\n■ 5. 종목 홀드아웃 — 본 적 없는 종목에서도 재현되나')
ch = Counter(r.get('cohort') for r in buy)
print('  ' + ' · '.join(f'{k}={v:,}' for k, v in ch.most_common()))

print('\n■ 6. 지금 상황(하락 국면)에 해당하는 표본')
now = [r for r in buy if cell6(r) and '하락' in cell6(r)]
nb = Counter(r['split'] for r in now)
print(f'  하락 국면 추천 {len(now):,}건 = '
      + ' · '.join(f'{k} {nb[k]:,}' for k in ('train', 'valid', 'blind')))
print('  → 오늘 쓰는 판단에 직접 걸리는 표본이 이만큼뿐이다')
