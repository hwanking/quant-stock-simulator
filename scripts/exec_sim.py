# -*- coding: utf-8 -*-
"""
정확한 실행 재시뮬레이터 — 경로(고가·저가)로 선도달 순서까지 그대로 재현한다.

라운드 17 이 무효였던 이유는 mfe/mae 가 청산 봉까지만 잰 값이라서였다.
여기서는 라운드 17d 가 남긴 20봉 경로를 쓴다. 그래서:
  · 목표를 넓혀도 답할 수 있다 (청산 이후 구간이 경로에 있다)
  · 모호분이 **0** 이다 (어느 쪽이 먼저 닿았는지 봉 단위로 안다)

판정 규칙은 현행 엔진(prediction_log.grade_prediction)과 똑같다:
  같은 봉에서 목표·손절이 둘 다 닿으면 **손절 먼저** — 보수적으로 본다.
  이걸 다르게 하면 현행과의 비교가 무의미해진다.
"""
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LED = os.path.join(BASE, '.portfolio', 'virtual_graded.jsonl')
PATHS = os.path.join(BASE, '.portfolio', 'virtual_paths.jsonl')

COST = 0.41                 # 왕복 거래비용 % — 현행 엔진과 같은 값
BUY = 58                    # 매수권 문턱 — 화면의 국면 표와 같은 기준
VOL_CUT = 0.03
#: 경로를 소수 3자리로 저장한 데서 오는 경계 오차 허용치
EPS = 0.002
REG_KO = {'BULL': '상승', 'SIDEWAYS': '옆걸음', 'BEAR': '하락'}


def _jsonl(path):
    with open(path, encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                try:
                    yield json.loads(ln)
                except Exception:
                    pass


def load_cases(min_score=BUY, need_path=True):
    """
    원장 + 경로를 붙여 재시뮬 가능한 사례 목록으로.

    경로가 없는 사례는 기본적으로 버린다 — 있는 것처럼 채우지 않는다.
    """
    paths = {}
    if os.path.exists(PATHS):
        for d in _jsonl(PATHS):
            paths[(d['ticker'], d['date'])] = d

    out = []
    n_nopath = 0
    for r in _jsonl(LED):
        if (r.get('score') or 0) < min_score:
            continue
        p, t, s = r.get('price'), r.get('target'), r.get('stop')
        if not (p and t and s):
            continue
        TP = (t / p - 1) * 100
        SP = (1 - s / p) * 100
        if TP <= 0 or SP <= 0:
            continue
        pth = paths.get((r['ticker'], r['date']))
        if not pth:
            n_nopath += 1
            if need_path:
                continue
        rg, v = r.get('regime'), r.get('vol20')
        out.append({
            'ticker': r['ticker'], 'date': r['date'], 'split': r['split'],
            'cohort': r.get('cohort'), 'score': r.get('score'),
            'TP': TP, 'SP': SP,
            'regime': rg, 'vol20': v,
            'cell6': (f"{'거친' if (v or 0) >= VOL_CUT else '차분한'} "
                      f"{REG_KO.get(rg, rg)}" if rg and v is not None else None),
            'entry_zone': r.get('entry_zone'),
            'rsi': r.get('rsi'), 'bb_pos': r.get('bb_pos'),
            'range_pos': r.get('range_pos'), 'm10_above': r.get('m10_above'),
            'demark_state': r.get('demark_state'),
            'high': (pth or {}).get('high'),
            'low': (pth or {}).get('low'),
            'close': (pth or {}).get('close'),
        })
    return out, n_nopath


def simulate(c, tp, sp, entry_disc=0.0, max_bars=None):
    """
    목표 +tp% · 손절 -sp% 로 재현. 선도달 순서를 봉 단위로 판정한다.

    entry_disc: 진입 지정가 할인폭 %. 0 이면 기준일 종가에 바로 산다.
                >0 이면 '기준가보다 그만큼 아래로 내려오면 산다' — 안 내려오면
                거래 자체가 없다(NOENTRY). 이게 '얼마에 살 것인가' 연구다.

    반환: (kind, ret_pct)
      kind ∈ TARGET / STOP / OPEN / NOENTRY
      ret 은 비용 차감 **전** 값이다.
    """
    hi, lo, cl = c['high'], c['low'], c['close']
    if not hi:
        return 'NODATA', 0.0
    n = len(hi) if max_bars is None else min(len(hi), max_bars)

    start = 0
    base = 0.0                      # 진입가의 기준일 종가 대비 위치 %
    if entry_disc > 0:
        # 지정가 매수 — 저가가 -entry_disc% 까지 내려온 첫 봉에서 체결
        for i in range(n):
            if lo[i] <= -entry_disc:
                start, base = i, -entry_disc
                break
        else:
            return 'NOENTRY', 0.0

    # 진입가 기준으로 목표·손절을 다시 잡는다 (진입가가 기준가와 다르므로)
    def rel(x):
        """기준일 종가 대비 x% 를 진입가 대비 %로."""
        return ((100.0 + x) / (100.0 + base) - 1.0) * 100.0

    for i in range(start, n):
        h, l = rel(hi[i]), rel(lo[i])
        # 같은 봉에서 둘 다면 손절 먼저 (현행 엔진과 동일한 보수적 규칙)
        # EPS: 경로를 소수 3자리로 저장해서 경계값이 아슬아슬하게 어긋난다.
        # 손절 쪽에만 여유를 준다 — 유리한 쪽으로 기울이지 않는다.
        if l <= -sp + EPS:
            return 'STOP', -sp
        if h >= tp:
            return 'TARGET', tp
    return 'OPEN', rel(cl[n - 1])


def ev(cases, tp_mult=1.0, sp_mult=1.0, entry_disc=0.0, max_bars=None):
    """
    한 설정의 성적. 진입 못 한 건(NOENTRY)은 거래가 없으므로 수익 0 으로
    세되, 비율을 따로 보고한다 — '기회를 얼마나 놓쳤나'가 중요하기 때문이다.
    """
    n_t = n_s = n_o = n_ne = 0
    tot = 0.0
    traded = 0
    for c in cases:
        k, r = simulate(c, c['TP'] * tp_mult, c['SP'] * sp_mult,
                        entry_disc, max_bars)
        if k == 'NODATA':
            continue
        if k == 'NOENTRY':
            n_ne += 1
            continue
        traded += 1
        tot += r - COST
        if k == 'TARGET':
            n_t += 1
        elif k == 'STOP':
            n_s += 1
        else:
            n_o += 1
    n_all = traded + n_ne
    if not traded:
        return None
    return {
        'n': n_all, 'traded': traded,
        'ev': tot / traded,                  # 거래당 기대값
        'ev_per_signal': tot / max(1, n_all),  # 신호당 (미체결 포함)
        'reach': n_t / traded * 100,
        'stop_rate': n_s / traded * 100,
        'open_rate': n_o / traded * 100,
        'noentry_pct': n_ne / max(1, n_all) * 100,
    }


def rets(cases, tp_mult=1.0, sp_mult=1.0, entry_disc=0.0, max_bars=None):
    """거래된 건의 수익률(비용 차감 후) 목록 — 부트스트랩용."""
    out = []
    for c in cases:
        k, r = simulate(c, c['TP'] * tp_mult, c['SP'] * sp_mult,
                        entry_disc, max_bars)
        if k in ('NODATA', 'NOENTRY'):
            continue
        out.append(r - COST)
    return out
