# -*- coding: utf-8 -*-
"""
스윙 관제실의 **그림**(라운드 455) — 전부 HTML/SVG 문자열을 돌려주는 순수 함수다. Streamlit 을 모른다(화면이 `st.markdown(…,
unsafe_allow_html=True)` 로 그린다) · 회귀가 문자열로 잰다 · 새 의존성(plotly 등)을 안 넣는다(배포는 열어 둔 의존성에서 죽는다).

규칙: 색은 `ui_kit` 팔레트 토큰만(새 색 없음 · §5) · 글자는 12px 이상(§77) · 이모지 없음(상태는 점으로 · `ui_kit.dot` 의 규칙) ·
없는 값은 그리지 않고 **빈 상태 문장**을 돌려준다(§3 · 빈 그래프를 숨기지 않는다 — "이력 없음"이라고 적는다).
외부 검토(2026-10-09)가 제안한 시각화 중 자료가 있는 것만 받았다: 자산 곡선 · 자산 구성 도넛 · 위험 한도 사용 막대 · 오늘 후보 깔때기 ·
포지션 가격선 · 주문 생애 타임라인 · 영수증 폭포 · 시스템 상태 띠. 점수·등급·추천 낱말은 어디에도 없다(§9).
"""
import ui_kit as _uk

#: 시스템 상태 다섯 + 확인 불가 — 외부 검토 #10 의 정규화(RUNNING · SCHEDULED · IDLE · DEGRADED · ERROR). 판정이 아니라 **상태**다.
#: OK 는 '도는 것'이 아니라 '열려 있고 쓸 수 있는 것'(장부 · 연결)의 정상 — 외부 검토의 다섯에 하나를 더했다(장부에 '실행 중'은 틀린 말이다).
STATES = ('RUNNING', 'OK', 'SCHEDULED', 'IDLE', 'DEGRADED', 'ERROR', 'UNKNOWN')
STATE_KO = {'RUNNING': '실행 중', 'OK': '정상', 'SCHEDULED': '예약됨', 'IDLE': '대기', 'DEGRADED': '일부 문제', 'ERROR': '조치 필요',
            'UNKNOWN': '확인 불가'}
_FONT = "font-family:inherit;"


def _t(theme):
    return _uk.tokens(theme)


def _e(s):
    return _uk._esc(s)


def _col(t, tone, default=None):
    return t.get(tone or '', default if default is not None else t['tx2'])


def state_color(state, t):
    return {'RUNNING': t['pos'], 'OK': t['pos'], 'SCHEDULED': t['brand'], 'IDLE': t['tx3'], 'DEGRADED': t['warn'], 'ERROR': t['neg'],
            'UNKNOWN': t['warn']}.get(state, t['tx3'])


def state_mark(state, t, size=10):
    """상태 점 — 실행 중·조치 필요는 찬 점, 예약·대기·확인 불가는 빈 점, 일부 문제는 반 찬 점(색은 토큰)."""
    col = state_color(state, t)
    r = size / 2.0
    if state in ('RUNNING', 'OK', 'ERROR'):
        body = f"<circle cx='{r}' cy='{r}' r='{r - 1}' fill='{col}'/>"
    elif state == 'DEGRADED':
        body = (f"<circle cx='{r}' cy='{r}' r='{r - 1}' fill='none' stroke='{col}' stroke-width='1.5'/>"
                f"<path d='M{r} 1A{r - 1} {r - 1} 0 0 1 {r} {size - 1}Z' fill='{col}'/>")
    else:
        body = f"<circle cx='{r}' cy='{r}' r='{r - 1}' fill='none' stroke='{col}' stroke-width='1.5'/>"
    return (f"<svg width='{size}' height='{size}' viewBox='0 0 {size} {size}' style='flex:0 0 auto; vertical-align:middle;' "
            f"role='img' aria-label='{_e(STATE_KO.get(state, state))}'>{body}</svg>")


def health_strip(items, theme='dark', title=''):
    """시스템 상태 띠 — [{'label','state','text'}]. 상태는 STATES 중 하나(모르면 UNKNOWN 으로 그린다 · 숨기지 않는다)."""
    t = _t(theme)
    cells = []
    for it in items:
        st_ = it.get('state') if it.get('state') in STATES else 'UNKNOWN'
        cells.append(
            f"<div style='display:flex; align-items:center; gap:8px; padding:8px 12px; border-radius:999px; "
            f"background:{t['card']}; border:1px solid {t['line']}; white-space:nowrap;'>{state_mark(st_, t)}"
            f"<span style='font-size:13px; color:{t['tx1']}; font-weight:500;'>{_e(it.get('label'))}</span>"
            f"<span style='font-size:13px; color:{state_color(st_, t)};'>{_e(STATE_KO[st_])}</span>"
            + (f"<span style='font-size:12px; color:{t['tx3']};'>{_e(it.get('text'))}</span>" if it.get('text') else '')
            + "</div>")
    head = (f"<p style='margin:0 0 6px 2px; font-size:13px; color:{t['tx2']}; font-weight:500;'>{_e(title)}</p>" if title else '')
    return head + "<div style='display:flex; flex-wrap:wrap; gap:8px;'>" + ''.join(cells) + "</div>"


def command_bar(items, theme='dark'):
    """상단 지휘 띠 — [{'label','value','sub'(선택),'tone'(선택)}]. 값은 **짧게**(정상 · 꺼짐 · 3 · 0%), 시각·설명은 sub 로(외부 검토 R456)."""
    t = _t(theme)
    cells = []
    for i, it in enumerate(items):
        col = _col(t, it.get('tone'), t['tx1'])
        border = '' if i == 0 else f"border-left:1px solid {t['line']};"
        sub = (f"<p style='margin:3px 0 0 0; font-size:12px; color:{t['tx3']}; line-height:1.4; word-break:keep-all;'>"
               f"{_e(it.get('sub'))}</p>" if it.get('sub') else '')
        cells.append(f"<div style='flex:1 1 0; min-width:118px; padding:2px 14px; {border}'>"
                     f"<p style='margin:0; font-size:12px; color:{t['tx2']}; font-weight:500; line-height:1.3;'>{_e(it.get('label'))}</p>"
                     f"<p style='margin:4px 0 0 0; font-size:17px; font-weight:600; color:{col}; line-height:1.2; "
                     f"font-variant-numeric:tabular-nums; white-space:nowrap;'>{_e(it.get('value'))}</p>{sub}</div>")
    return (f"<div style='background:{t['card']}; border-radius:18px; padding:14px 6px; display:flex; flex-wrap:wrap; "
            f"row-gap:12px; align-items:stretch;'>" + ''.join(cells) + "</div>")


def _fmt_won_short(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return '—'
    if abs(v) >= 1e8:
        return f'{v / 1e8:,.2f}억'
    if abs(v) >= 1e4:
        return f'{v / 1e4:,.0f}만'
    return f'{v:,.0f}'


def equity_curve(points, theme='dark', width=640, height=170, empty_note='실전 거래 이력 없음'):
    """자산 곡선 — points: [{'ts','total','cash','managed'(선택)}] 오래된 것부터. 2점 미만이면 **평평한 선 + 문장**(숨기지 않는다).
    값은 증권사 총평가·예수금 그대로(수익률로 바꾸지 않는다) · 축 글자 12px."""
    t = _t(theme)
    pts = [p for p in (points or []) if p.get('total') is not None]
    pad_l, pad_r, pad_t, pad_b = 64, 12, 14, 26
    w_in, h_in = width - pad_l - pad_r, height - pad_t - pad_b
    if len(pts) < 2:
        total = pts[0]['total'] if pts else None
        y = pad_t + h_in / 2.0
        line = (f"<line x1='{pad_l}' y1='{y}' x2='{width - pad_r}' y2='{y}' stroke='{t['brand']}' stroke-width='2' "
                f"stroke-dasharray='4 4'/>" if total is not None else '')
        lab = (f"<text x='{pad_l - 6}' y='{y + 4}' text-anchor='end' style='font-size:12px; fill:{t['tx2']}; {_FONT}'>"
               f"{_e(_fmt_won_short(total))}</text>" if total is not None else '')
        note = f"{empty_note} · 스냅샷 {len(pts)}개" + ('' if pts else ' — 계좌를 읽으면 첫 점이 생깁니다')
        return (f"<svg width='100%' viewBox='0 0 {width} {height}' preserveAspectRatio='none' style='display:block;'>{line}{lab}"
                f"<text x='{pad_l + w_in / 2.0}' y='{y - 10}' text-anchor='middle' style='font-size:12px; fill:{t['tx3']}; {_FONT}'>"
                f"{_e(note)}</text></svg>")
    series = [('total', t['brand'], '총자산', ''), ('cash', t['tx3'], '예수금', "stroke-dasharray='4 3'"),
              ('managed', t['pos'], '자동매매 평가', '')]
    vals = [float(p[k]) for p in pts for k, _c, _l, _d in series if p.get(k) is not None]
    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-9:
        lo, hi = lo - 1.0, hi + 1.0
    n = len(pts)

    def x_of(i):
        return pad_l + (w_in * i / (n - 1))

    def y_of(v):
        return pad_t + h_in - (h_in * (float(v) - lo) / (hi - lo))
    paths, legend = [], []
    for key, col, label, dash in series:
        seg = [(x_of(i), y_of(p[key])) for i, p in enumerate(pts) if p.get(key) is not None]
        if len(seg) < 2:
            continue
        d = 'M' + ' L'.join(f'{x:.1f} {y:.1f}' for x, y in seg)
        paths.append(f"<path d='{d}' fill='none' stroke='{col}' stroke-width='2' {dash}/>")
        legend.append(f"<span style='display:inline-flex; align-items:center; gap:6px; font-size:12px; color:{t['tx2']};'>"
                      f"{_uk.dot(col, 8)}{_e(label)}</span>")
    first, last = str(pts[0].get('ts') or '')[:10], str(pts[-1].get('ts') or '')[:10]
    grid = ''.join(f"<line x1='{pad_l}' y1='{pad_t + h_in * k / 2.0:.1f}' x2='{width - pad_r}' y2='{pad_t + h_in * k / 2.0:.1f}' "
                   f"stroke='{t['line']}' stroke-width='1'/>" for k in range(3))
    labels = (f"<text x='{pad_l - 6}' y='{pad_t + 4}' text-anchor='end' style='font-size:12px; fill:{t['tx2']}; {_FONT}'>{_e(_fmt_won_short(hi))}</text>"
              f"<text x='{pad_l - 6}' y='{pad_t + h_in + 4}' text-anchor='end' style='font-size:12px; fill:{t['tx2']}; {_FONT}'>{_e(_fmt_won_short(lo))}</text>"
              f"<text x='{pad_l}' y='{height - 6}' style='font-size:12px; fill:{t['tx3']}; {_FONT}'>{_e(first)}</text>"
              f"<text x='{width - pad_r}' y='{height - 6}' text-anchor='end' style='font-size:12px; fill:{t['tx3']}; {_FONT}'>{_e(last)}</text>")
    return (f"<svg width='100%' viewBox='0 0 {width} {height}' preserveAspectRatio='none' style='display:block;'>{grid}{''.join(paths)}{labels}</svg>"
            f"<div style='display:flex; gap:14px; flex-wrap:wrap; margin-top:6px;'>{''.join(legend)}"
            f"<span style='font-size:12px; color:{t['tx3']};'>스냅샷 {n}개 · 증권사 값 그대로</span></div>")


_DONUT_TONES = ('brand', 'pos', 'warn', 'up', 'down', 'tx3')


def donut(parts, theme='dark', size=150, title=''):
    """자산 구성 도넛 — parts: [{'label','pct','tone'(선택)}] · 합이 100 을 넘으면 넘는 조각을 그리지 않는다(숨기지 않고 범례에 적는다).
    값이 없으면 빈 상태 문장."""
    t = _t(theme)
    ps = [p for p in (parts or []) if p.get('pct') is not None and float(p['pct']) > 0]
    if not ps:
        return f"<p style='margin:0; font-size:13px; color:{t['tx3']};'>자산 구성을 그릴 값이 없습니다(총자산을 못 받았습니다).</p>"
    r, sw = size / 2.0 - 12, 16
    circ = 2 * 3.141592653589793 * r
    arcs, legend, cum = [], [], 0.0
    for i, p in enumerate(ps):
        pct = float(p['pct'])
        col = _col(t, p.get('tone') or _DONUT_TONES[i % len(_DONUT_TONES)], t['brand'])
        if cum + pct <= 100.0 + 1e-9:
            arcs.append(f"<circle cx='{size / 2.0}' cy='{size / 2.0}' r='{r}' fill='none' stroke='{col}' stroke-width='{sw}' "
                        f"stroke-dasharray='{circ * pct / 100.0:.2f} {circ:.2f}' stroke-dashoffset='{-circ * cum / 100.0:.2f}' "
                        f"transform='rotate(-90 {size / 2.0} {size / 2.0})'/>")
        legend.append(f"<div style='display:flex; align-items:center; gap:8px; font-size:13px; color:{t['tx1']};'>{_uk.dot(col, 9)}"
                      f"<span style='flex:1 1 auto;'>{_e(p['label'])}</span>"
                      f"<span style='color:{t['tx2']}; font-variant-numeric:tabular-nums;'>{pct:.1f}%</span></div>")
        cum += pct
    head = (f"<p style='margin:0 0 6px 2px; font-size:13px; color:{t['tx2']}; font-weight:500;'>{_e(title)}</p>" if title else '')
    svg = (f"<svg width='{size}' height='{size}' viewBox='0 0 {size} {size}' style='flex:0 0 auto;'>"
           f"<circle cx='{size / 2.0}' cy='{size / 2.0}' r='{r}' fill='none' stroke='{t['line']}' stroke-width='{sw}'/>{''.join(arcs)}</svg>")
    return (head + f"<div style='display:flex; align-items:center; gap:18px; background:{t['card']}; border-radius:18px; padding:14px 18px;'>"
            f"{svg}<div style='display:flex; flex-direction:column; gap:6px; flex:1 1 auto;'>{''.join(legend)}</div></div>")


def risk_bars(items, theme='dark', title=''):
    """위험 한도 사용 막대 — [{'label','used','limit','unit','text'(선택)}]. 한도가 없으면 막대 없이 '한도 없음'. 판정 낱말 없음 —
    한도를 넘은 막대는 경고색으로 **보일 뿐** 규칙 위반 판정이 아니다(사용자가 직접 산 보유도 포함되므로 · 라운드 454)."""
    t = _t(theme)
    rows = []
    for it in items or []:
        used, limit = it.get('used'), it.get('limit')
        unit = it.get('unit') or ''
        if used is None:
            bar, txt = 0.0, '값 없음'
            col = t['tx3']
        elif limit in (None, 0):
            bar, txt, col = 0.0, f"{used:g}{unit} · 한도 없음", t['tx3']
        else:
            ratio = float(used) / float(limit)
            bar = max(0.0, min(100.0, ratio * 100.0))
            txt = f"{float(used):,.{0 if unit == '원' else 1}f}{unit} / {float(limit):,.{0 if unit == '원' else 0}f}{unit} ({ratio * 100:.0f}%)"
            col = t['warn'] if ratio > 1.0 else t['brand']
        rows.append(f"<div style='display:grid; grid-template-columns:minmax(110px,1.2fr) 3fr minmax(150px,1.5fr); align-items:center; gap:10px; padding:5px 0;'>"
                    f"<span style='font-size:13px; color:{t['tx1']};'>{_e(it.get('label'))}</span>"
                    f"<span style='height:8px; background:{t['line']}; border-radius:4px; overflow:hidden;'>"
                    f"<span style='display:block; width:{bar:.1f}%; height:100%; background:{col};'></span></span>"
                    f"<span style='font-size:12px; color:{t['tx2']}; text-align:right; font-variant-numeric:tabular-nums;'>{_e(txt)}"
                    + (f" <span style='color:{t['tx3']};'>· {_e(it.get('text'))}</span>" if it.get('text') else '') + "</span></div>")
    if not rows:
        return f"<p style='margin:0; font-size:13px; color:{t['tx3']};'>위험 한도가 비어 있어 사용량을 그릴 수 없습니다(시스템 → 설정).</p>"
    head = (f"<p style='margin:0 0 4px 2px; font-size:13px; color:{t['tx2']}; font-weight:500;'>{_e(title)}</p>" if title else '')
    return head + f"<div style='background:{t['card']}; border-radius:14px; padding:10px 16px;'>" + ''.join(rows) + "</div>"


def funnel(stages, theme='dark', title=''):
    """오늘 후보 깔때기 — [{'label','n','sub'(선택)}]. 수는 부르는 쪽이 센 것 그대로(판정 아님). 화살표는 글자(이모지 아님)."""
    t = _t(theme)
    cells = []
    for i, s in enumerate(stages or []):
        n = s.get('n')
        cells.append((f"<span style='font-size:16px; color:{t['tx3']}; padding:0 4px;'>→</span>" if i else '')
                     + f"<div style='flex:1 1 0; min-width:96px; background:{t['card']}; border-radius:14px; padding:10px 12px; text-align:center;'>"
                     f"<p style='margin:0; font-size:12px; color:{t['tx2']};'>{_e(s.get('label'))}</p>"
                     f"<p style='margin:4px 0 0 0; font-size:20px; font-weight:600; color:{t['tx1']}; font-variant-numeric:tabular-nums;'>"
                     f"{_e('—' if n is None else f'{int(n):,}')}</p>"
                     + (f"<p style='margin:3px 0 0 0; font-size:12px; color:{t['tx3']};'>{_e(s.get('sub'))}</p>" if s.get('sub') else '')
                     + "</div>")
    head = (f"<p style='margin:0 0 6px 2px; font-size:13px; color:{t['tx2']}; font-weight:500;'>{_e(title)}</p>" if title else '')
    return head + "<div style='display:flex; align-items:center; gap:4px; flex-wrap:wrap;'>" + ''.join(cells) + "</div>"


def range_bar(stop, entry, current, target, theme='dark', width=560):
    """포지션 가격선 — 손절 | 진입 · 현재 | 목표 를 가로 눈금으로. 셋(손절·진입·목표) 중 하나라도 없으면 문장(그리지 않는다)."""
    t = _t(theme)
    try:
        s, e_, tg = float(stop), float(entry), float(target)
    except (TypeError, ValueError):
        return f"<p style='margin:0; font-size:12px; color:{t['tx3']};'>가격선을 그릴 수 없습니다 — 손절·진입·목표 중 빈 값이 있습니다.</p>"
    cur = None
    try:
        cur = float(current) if current is not None else None
    except (TypeError, ValueError):
        cur = None
    lo = min(s, e_, tg, cur if cur is not None else s)
    hi = max(s, e_, tg, cur if cur is not None else tg)
    span = (hi - lo) or 1.0
    pad = 60
    h = 64

    def x(v):
        return pad + (width - 2 * pad) * (v - lo) / span
    parts = [f"<line x1='{x(s):.1f}' y1='30' x2='{x(tg):.1f}' y2='30' stroke='{t['line']}' stroke-width='6' stroke-linecap='round'/>"]
    for v, col, lab, anchor in ((s, t['down'], f'손절 {s:,.0f}', 'middle'), (tg, t['up'], f'목표 {tg:,.0f}', 'middle'), (e_, t['tx2'], f'진입 {e_:,.0f}', 'middle')):
        parts.append(f"<line x1='{x(v):.1f}' y1='22' x2='{x(v):.1f}' y2='38' stroke='{col}' stroke-width='3' stroke-linecap='round'/>"
                     f"<text x='{x(v):.1f}' y='{14 if v == e_ else 54}' text-anchor='{anchor}' style='font-size:12px; fill:{col}; {_FONT}'>{_e(lab)}</text>")
    if cur is not None:
        parts.append(f"<circle cx='{x(cur):.1f}' cy='30' r='7' fill='{t['brand']}' stroke='{t['bg']}' stroke-width='2'/>"
                     f"<text x='{x(cur):.1f}' y='{14 if abs(x(cur) - x(e_)) > 48 else 8}' text-anchor='middle' style='font-size:12px; fill:{t['brand']}; {_FONT}'>현재 {cur:,.0f}</text>")
    return f"<svg width='100%' viewBox='0 0 {width} {h}' preserveAspectRatio='none' style='display:block; overflow:visible;'>{''.join(parts)}</svg>"


def timeline(events, theme='dark', title=''):
    """주문 생애 타임라인 — [{'ts','label','detail'(선택),'tone'(선택)}] 시간순. 비면 빈 상태 문장."""
    t = _t(theme)
    if not events:
        return f"<p style='margin:0; font-size:13px; color:{t['tx3']};'>아직 사건이 없습니다.</p>"
    rows = []
    for i, ev in enumerate(events):
        col = _col(t, ev.get('tone'), t['brand'])
        rows.append(f"<div style='display:grid; grid-template-columns:18px 150px 1fr; gap:10px; align-items:start; padding:4px 0;'>"
                    f"<div style='display:flex; flex-direction:column; align-items:center;'>{_uk.dot(col, 10)}"
                    + (f"<span style='width:2px; flex:1 1 auto; min-height:14px; background:{t['line']};'></span>" if i < len(events) - 1 else '')
                    + "</div>"
                    f"<span style='font-size:12px; color:{t['tx3']}; font-variant-numeric:tabular-nums; white-space:nowrap;'>{_e(ev.get('ts'))}</span>"
                    f"<span style='font-size:13px; color:{t['tx1']};'>{_e(ev.get('label'))}"
                    + (f"<span style='color:{t['tx3']}; font-size:12px;'> · {_e(ev.get('detail'))}</span>" if ev.get('detail') else '')
                    + "</span></div>")
    head = (f"<p style='margin:0 0 6px 2px; font-size:13px; color:{t['tx2']}; font-weight:500;'>{_e(title)}</p>" if title else '')
    return head + f"<div style='background:{t['card']}; border-radius:14px; padding:10px 16px;'>" + ''.join(rows) + "</div>"


def waterfall(steps, theme='dark', width=560, height=170):
    """영수증 폭포 — steps: [{'label','delta'}] 누적 → 마지막 '추정 비용후' 막대. 값이 없으면 문장. 손익 색은 한국 관행(이익 빨강·손실 파랑)."""
    t = _t(theme)
    ss = [s for s in (steps or []) if s.get('delta') is not None]
    if not ss:
        return f"<p style='margin:0; font-size:13px; color:{t['tx3']};'>폭포를 그릴 값이 없습니다(체결가를 못 받았습니다).</p>"
    cum, bars = 0.0, []
    for s in ss:
        d = float(s['delta'])
        bars.append((s['label'], cum, cum + d, d, False))
        cum += d
    bars.append(('추정 비용후', 0.0, cum, cum, True))
    lo = min(0.0, min(min(a, b) for _l, a, b, _d, _f in bars))
    hi = max(0.0, max(max(a, b) for _l, a, b, _d, _f in bars))
    if hi - lo < 1e-9:
        hi = lo + 1.0
    pad_l, pad_t, pad_b = 48, 14, 40
    h_in = height - pad_t - pad_b
    n = len(bars)
    bw = (width - pad_l - 12) / n

    def y(v):
        return pad_t + h_in - h_in * (v - lo) / (hi - lo)
    out = [f"<line x1='{pad_l}' y1='{y(0):.1f}' x2='{width - 12}' y2='{y(0):.1f}' stroke='{t['line']}' stroke-width='1'/>"]
    for i, (lab, a, b, d, final) in enumerate(bars):
        x0 = pad_l + bw * i + bw * 0.15
        col = t['tx2'] if final else (t['up'] if d >= 0 else t['down'])
        top, bot = y(max(a, b)), y(min(a, b))
        out.append(f"<rect x='{x0:.1f}' y='{top:.1f}' width='{bw * 0.7:.1f}' height='{max(1.0, bot - top):.1f}' rx='3' fill='{col}'/>"
                   f"<text x='{x0 + bw * 0.35:.1f}' y='{top - 4:.1f}' text-anchor='middle' style='font-size:12px; fill:{t['tx1']}; {_FONT}'>{d:+.2f}%</text>"
                   f"<text x='{x0 + bw * 0.35:.1f}' y='{height - 22}' text-anchor='middle' style='font-size:12px; fill:{t['tx2']}; {_FONT}'>{_e(lab)}</text>")
    return f"<svg width='100%' viewBox='0 0 {width} {height}' preserveAspectRatio='none' style='display:block; overflow:visible;'>{''.join(out)}</svg>"


def kv_card(title, rows, theme='dark', accent=''):
    """작은 사실 카드 — rows: [(label, value, tone(선택))]. 관제실의 '실행 상태' · 'PROOF' · '최근 사건' 칸."""
    t = _t(theme)
    body = ''.join(f"<div style='display:flex; justify-content:space-between; gap:12px; padding:6px 0; border-top:1px solid {t['line']};'>"
                   f"<span style='font-size:13px; color:{t['tx2']};'>{_e(r[0])}</span>"
                   f"<span style='font-size:13px; font-weight:600; color:{_col(t, r[2] if len(r) > 2 else None, t['tx1'])}; text-align:right; "
                   f"font-variant-numeric:tabular-nums;'>{_e(r[1])}</span></div>" for r in rows)
    edge = f"border-left:3px solid {_col(t, accent, t['brand'])};" if accent else ''
    return (f"<div style='background:{t['card']}; border-radius:18px; padding:14px 18px; {edge}'>"
            f"<p style='margin:0 0 4px 0; font-size:13px; color:{t['tx2']}; font-weight:500;'>{_e(title)}</p>{body}</div>")
