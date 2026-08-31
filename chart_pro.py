# -*- coding: utf-8 -*-
"""
종합 인터랙티브 차트 — TradingView Lightweight Charts(Apache 2.0) 기반.

원칙:
  · 라이브러리 JS는 vendor/ 에 통째로 내장한다 — 시세·종목 데이터가 외부로
    나가지 않고(전부 iframe 안에 인라인), 오프라인·클라우드 어디서든 뜬다.
  · 지표는 이미 검증된 tech_df 값을 그대로 쓴다(차트가 따로 계산해 어긋나는
    것을 막는다). 여기서 새로 계산하는 것은 MA120·EMA20·MACD·스토캐스틱·OBV 뿐.
  · 실행 가격선(손절/목표/추천매수/TDST)은 four_scores 의 값 — 화면 배너와
    같은 숫자다.
  · 지표 선택창: 사용자가 원하는 지표만 골라 켠다. 선택은 브라우저
    localStorage 에 남아 다음 방문에도 유지된다.
"""
from __future__ import annotations

import json
import os

_VENDOR_JS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          'vendor', 'lightweight-charts.standalone.production.js')
_CDN_URL = ('https://unpkg.com/lightweight-charts@4.2.3/dist/'
            'lightweight-charts.standalone.production.js')

# 한국 관례: 상승 = 빨강, 하락 = 파랑
_UP = '#ff453a'
_DN = '#0a84ff'

_THEMES = {
    'dark': dict(bg='#16181d', panel='#16181d', text='#d5d8e0', grid='#23262e',
                 border='#2d3139', legend='#a0a5b5'),
    'light': dict(bg='#ffffff', panel='#ffffff', text='#3a3f4a', grid='#eef1f6',
                  border='#dde2ea', legend='#5a5f6b'),
}


def _ema(vals, n):
    out, k, prev = [], 2.0 / (n + 1), None
    for v in vals:
        prev = v if prev is None else v * k + prev * (1 - k)
        out.append(prev)
    return out


def _f(x):
    try:
        v = float(x)
        return v if v == v else None          # NaN 제거
    except (TypeError, ValueError):
        return None


def _series(times, vals):
    return [{'time': t, 'value': round(v, 4)}
            for t, v in zip(times, vals) if v is not None]


def build_chart_html(tech_df, four_scores, name='', unit_str='원',
                     theme='dark', user_avg=None, n_bars=None, height=780,
                     core=None):
    """전체 차트 HTML(문자열)을 만든다. st.components.v1.html 로 넣는다.

    n_bars=None 이면 보유한 전체 이력을 싣는다 — '전체' 버튼이 진짜 전체를
    보여야 하기 때문이다 (기본 화면은 JS 쪽에서 1년으로 시작).

    core 는 `verdict_core.build()` 결과다. **넘기면 실행 가격선을 여기서만
    받는다** — 없으면 four_scores 로 물러서지만, 그건 배너와 다른 숫자다
    (아래 실행 가격선 주석 참고).
    """
    th = _THEMES.get(theme, _THEMES['dark'])
    df = (tech_df.tail(int(n_bars)) if n_bars else tech_df).copy() \
        .reset_index(drop=True)

    # Lightweight Charts 는 시계열이 **오름차순·중복 없음**이어야 그린다.
    # 하나라도 어긋나면 예외도 경고도 없이 캔들·거래량·RSI·MACD 를 전부
    # 그리지 않는다 — 격자와 가격선만 남은 빈 화면이 된다 (2026-08-04 실측).
    # 상류를 고쳤더라도 여기서 한 번 더 막는다. 화면이 통째로 죽는 것보다
    # 한 줄을 버리는 쪽이 낫다.
    if 'trade_date' in df.columns and len(df):
        _d = df['trade_date'].astype(str).str[:10]
        _bad = int((_d < _d.shift(1)).sum()) + int(_d.duplicated().sum())
        if _bad:
            df = (df.assign(_t=_d)
                    .drop_duplicates('_t', keep='last')
                    .sort_values('_t', kind='stable')
                    .drop(columns='_t')
                    .reset_index(drop=True))

    times = [str(t)[:10] for t in df['trade_date']]
    closes = [_f(x) for x in df['adj_close']]
    opens = ([_f(x) for x in df['open']] if 'open' in df.columns else closes)
    highs = ([_f(x) for x in df['high']] if 'high' in df.columns else closes)
    lows = ([_f(x) for x in df['low']] if 'low' in df.columns else closes)
    vols = ([_f(x) for x in df['volume']] if 'volume' in df.columns
            else [0.0] * len(df))

    candles, volume = [], []
    for i, t in enumerate(times):
        o, h, l, c = opens[i], highs[i], lows[i], closes[i]
        if c is None:
            continue
        o = o if o is not None else c
        h = h if h is not None else max(o, c)
        l = l if l is not None else min(o, c)
        candles.append({'time': t, 'open': o, 'high': h, 'low': l, 'close': c})
        volume.append({'time': t, 'value': vols[i] or 0.0,
                       'color': (_UP if c >= o else _DN) + '66'})

    # ── 오버레이 지표 ─────────────────────────────────────
    mas = {}
    for col, key in (('sma_5', 'ma5'), ('sma_20', 'ma20'), ('sma_60', 'ma60')):
        if col in df.columns:
            mas[key] = _series(times, [_f(x) for x in df[col]])

    cl = [c if c is not None else 0.0 for c in closes]
    ma120 = []
    for i in range(len(cl)):
        w = [c for c in closes[max(0, i - 119):i + 1] if c is not None]
        ma120.append(sum(w) / len(w) if len(w) >= 120 else None)
    mas['ma120'] = _series(times, ma120)
    _e20 = _ema(cl, 20)
    mas['ema20'] = _series(times, ([None] * 19 + _e20[19:])
                           if len(_e20) > 19 else [])

    bb_u = _series(times, [_f(x) for x in df['bb_upper']]) if 'bb_upper' in df.columns else []
    bb_l = _series(times, [_f(x) for x in df['bb_lower']]) if 'bb_lower' in df.columns else []

    # ── 하단 패널 지표 ────────────────────────────────────
    rsi = _series(times, [_f(x) for x in df['rsi_14']]) if 'rsi_14' in df.columns else []

    macd_line = [a - b for a, b in zip(_ema(cl, 12), _ema(cl, 26))]
    sig_line = _ema(macd_line, 9)
    macd = _series(times, macd_line)
    signal = _series(times, sig_line)
    hist = [{'time': t, 'value': round(m - s, 4),
             'color': (_UP if m - s >= 0 else _DN) + '99'}
            for t, m, s in zip(times, macd_line, sig_line)]

    # 스토캐스틱 슬로우 (14, 3, 3)
    k_raw = []
    for i in range(len(cl)):
        if i < 13:
            k_raw.append(None)
            continue
        hh = max(x for x in highs[i - 13:i + 1] if x is not None)
        ll = min(x for x in lows[i - 13:i + 1] if x is not None)
        k_raw.append(50.0 if hh == ll else (cl[i] - ll) / (hh - ll) * 100.0)

    def _sma3(seq):
        out = []
        for i in range(len(seq)):
            w = [x for x in seq[max(0, i - 2):i + 1] if x is not None]
            out.append(sum(w) / len(w) if len(w) == 3 else None)
        return out

    stoch_k = _sma3(k_raw)
    stoch_d = _sma3(stoch_k)

    # OBV (거래량 누적)
    obv_vals, acc = [], 0.0
    for i in range(len(cl)):
        if i > 0 and closes[i] is not None and closes[i - 1] is not None:
            if closes[i] > closes[i - 1]:
                acc += (vols[i] or 0.0)
            elif closes[i] < closes[i - 1]:
                acc -= (vols[i] or 0.0)
        obv_vals.append(acc)

    # ── DeMARK 마커 (셋업 9 / 카운트다운 13) ──────────────
    dm = (four_scores or {}).get('demark_res') or {}
    markers = []

    def _tail(seq):
        seq = list(seq) if seq is not None else []
        return seq[-len(times):] if len(seq) >= len(times) else \
            [0] * (len(times) - len(seq)) + seq

    b9, s9 = _tail(dm.get('buy_setup_series')), _tail(dm.get('sell_setup_series'))
    b13, s13 = _tail(dm.get('buy_countdown_series')), _tail(dm.get('sell_countdown_series'))
    for i, t in enumerate(times):
        try:
            if int(b13[i]) >= 13:
                markers.append({'time': t, 'position': 'belowBar', 'color': '#30d158',
                                'shape': 'arrowUp', 'text': '13 매수'})
            elif int(b9[i]) == 9:
                markers.append({'time': t, 'position': 'belowBar', 'color': '#30d158',
                                'shape': 'circle', 'text': '9'})
            if int(s13[i]) >= 13:
                markers.append({'time': t, 'position': 'aboveBar', 'color': '#ff453a',
                                'shape': 'arrowDown', 'text': '13 매도'})
            elif int(s9[i]) == 9:
                markers.append({'time': t, 'position': 'aboveBar', 'color': '#ff453a',
                                'shape': 'circle', 'text': '9'})
        except (TypeError, ValueError):
            continue

    # ── 실행 가격선 ───────────────────────────────────────
    #
    # ⚠️ 라운드 53 — 여기에 "배너와 같은 숫자만 쓴다"고 적혀 있었지만
    # **거짓이었다.** 이 차트는 `recommended_buy_price`(적정가 × 안전마진)를
    # '추천 매수가'로 그렸다. 그 산식은 라운드 25 에서 폐기했고 라운드 37 에
    # 배너에서 걷어낸 것이다 — 삼성전자 현재가 240,000원에 "147,567원 이하로
    # 사세요"(−38.5%) 를 만들어 낸 바로 그 값이다. 배너는 이미 CORE 의 실행
    # 진입가를 쓰고 있었으니, 같은 화면에서 '추천 매수가'가 두 개의 다른
    # 숫자였다 (CLAUDE.md §4).
    #
    # 목표·손절도 마찬가지다. `target_tech_1st`/`stop_loss_price` 는 **보유자
    # 기준(현재가 기준)**이고 배너는 **신규 매수자 기준**을 쓴다. 이름표 없이
    # 섞으면 신규 매수자가 남의 손절가를 보게 된다.
    fs = four_scores or {}
    co = core or {}
    if co:
        _rows = [(co.get('pullback_zone'), '실행 진입가 · 신규', '#ffd60a', 0),
                 (co.get('new_target'), '1차 목표 · 신규', '#30d158', 0),
                 (co.get('new_stop'), '손절 · 신규', '#ff453a', 0),
                 (fs.get('target_tech_2nd'), '2차 목표', '#2997ff', 2),
                 (fs.get('displayed_fair_value'), '펀더멘털 적정가 (장기)',
                  '#2997ff', 1)]
        if (co.get('bucket') or '').startswith('돌파'):
            _rows.append((co.get('breakout_price'), '돌파 매수가 · 신규',
                          '#30d158', 2))
        if user_avg:                      # 보유자 값은 실제 보유자에게만
            _rows += [(co.get('hold_trim'), '1차 목표 · 보유자', '#30d158', 2),
                      (co.get('hold_stop'), '손절 · 보유자', '#ff453a', 2)]
    else:
        # 중앙 판정을 못 받은 자리(단독 호출·테스트). 폐기된 추천가는 쓰지
        # 않는다 — 없는 선이 틀린 선보다 낫다.
        _rows = [(fs.get('target_tech_1st'), '1차 목표 · 보유자', '#30d158', 2),
                 (fs.get('target_tech_2nd'), '2차 목표', '#2997ff', 2),
                 (fs.get('stop_loss_price'), '손절 · 보유자', '#ff453a', 2),
                 (fs.get('displayed_fair_value'), '펀더멘털 적정가 (장기)',
                  '#2997ff', 1)]
    plines = []
    for val, label, color, style in (
            _rows + [(dm.get('tdst_support'), 'TDST 지지', '#30d15888', 1),
                     (dm.get('tdst_resistance'), 'TDST 저항', '#ff9f0a88', 1),
                     (user_avg, '내 평단가', '#bf5af2', 0)]):
        v = _f(val)
        if v and v > 0:
            plines.append({'price': v, 'title': label, 'color': color,
                           'lineStyle': style})

    payload = json.dumps({
        'candles': candles, 'volume': volume, 'mas': mas,
        'bbU': bb_u, 'bbL': bb_l, 'rsi': rsi,
        'macd': macd, 'signal': signal, 'hist': hist,
        'stochK': _series(times, stoch_k), 'stochD': _series(times, stoch_d),
        'obv': _series(times, obv_vals),
        'markers': markers, 'plines': plines,
        'name': str(name), 'unit': str(unit_str),
    }, ensure_ascii=False)

    lib_tag = f'<script src="{_CDN_URL}"></script>'
    if os.path.exists(_VENDOR_JS):
        try:
            with open(_VENDOR_JS, encoding='utf-8') as f:
                lib_tag = '<script>' + f.read() + '</script>'
        except Exception:
            pass

    return _HTML_TEMPLATE \
        .replace('__LIB__', lib_tag) \
        .replace('__DATA__', payload) \
        .replace('__COLORS__', json.dumps(th)) \
        .replace('__HEIGHT__', str(int(height)))


_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
__LIB__
<style>
  html, body { margin:0; padding:0; background: transparent;
    font-family: 'Pretendard', -apple-system, 'Malgun Gothic', sans-serif; }
  #wrap { border: 1px solid var(--bd); border-radius: 12px; overflow: hidden;
    background: var(--bg); }
  #toolbar { display:flex; flex-wrap:wrap; gap:6px 12px; align-items:center;
    padding: 10px 14px; border-bottom: 1px solid var(--bd);
    color: var(--lg); font-size: 13px; }
  #toolbar b.ttl { color: var(--tx); font-size: 13px; margin-right: 6px; }
  .rngbtn { border:1px solid var(--bd); background:transparent; color:var(--lg);
    border-radius:7px; padding:2px 9px; cursor:pointer; font-size:12px; }
  .rngbtn.on { background:#2997ff; color:#fff; border-color:#2997ff; }
  .tfbtn { border:1px solid var(--bd); background:transparent; color:var(--lg);
    border-radius:7px; padding:2px 9px; cursor:pointer; font-size:12px; }
  .tfbtn.on { background:#30d158; color:#0b1220; border-color:#30d158; }
  /* 지표 선택창 */
  #indWrap { position: relative; }
  #indBtn { border:1px solid var(--bd); background:transparent; color:var(--tx);
    border-radius:7px; padding:3px 11px; cursor:pointer; font-size:13px; }
  #indPanel { display:none; position:absolute; right:0; top:30px; z-index:50;
    background: var(--bg); border:1px solid var(--bd); border-radius:10px;
    padding: 12px 16px; min-width: 380px;
    box-shadow: 0 8px 24px rgba(0,0,0,0.25); }
  #indPanel.open { display:block; }
  #indPanel h5 { margin: 8px 0 5px 0; color: var(--tx); font-size: 12px;
    letter-spacing: .04em; }
  #indPanel h5:first-child { margin-top: 0; }
  .indGrid { display:grid; grid-template-columns: repeat(3, 1fr); gap: 4px 12px; }
  .indGrid label { display:flex; align-items:center; gap:5px; cursor:pointer;
    color: var(--lg); font-size: 13px; white-space:nowrap;
    user-select:none; padding: 2px 0; }
  .indGrid input { accent-color:#2997ff; }
  .sw { display:inline-block; width:9px; height:9px; border-radius:2px; }
  #legend { padding: 4px 14px 0 14px; font-size: 12px; color: var(--lg);
    min-height: 17px; }
  .pane { position: relative; }
  .plabel { position:absolute; left:10px; top:6px; z-index:3; font-size:12px;
    color: var(--lg); pointer-events:none; }
  .sep { width:1px; height:18px; background:var(--gr); margin:0 6px; }
  .tfbtn.off { opacity:.45; cursor:not-allowed; }
  #tfnote { padding: 2px 12px 0 12px; font-size: 12px; color: var(--lg); }
  #attrib { text-align:right; padding: 3px 12px 6px 0; font-size: 12px; }
  #attrib a { color: var(--lg); opacity: .6; text-decoration: none; }
</style></head>
<body>
<div id="wrap">
  <div id="toolbar">
    <b class="ttl" id="ttl"></b>
    <button class="rngbtn" data-m="3">3개월</button>
    <button class="rngbtn" data-m="6">6개월</button>
    <button class="rngbtn on" data-m="12">1년</button>
    <button class="rngbtn" data-m="0">전체</button>
    <span class="sep"></span>
    <button class="tfbtn on" data-tf="D">일봉</button>
    <button class="tfbtn" data-tf="W">주봉</button>
    <button class="tfbtn" data-tf="M">월봉</button>
    <button class="tfbtn off" data-tf="m" disabled
      title="분봉 자료를 받지 않습니다. 이 저장소는 일봉만 수집하며, 그래서 같은 날 목표·손절이 함께 닿은 케이스를 성공으로 세지 않습니다(선도달 순서를 알 수 없으므로).">분봉 없음</button>
    <span style="flex:1"></span>
    <div id="indWrap">
      <button id="indBtn">지표 선택 ▾</button>
      <div id="indPanel">
        <h5>가격 오버레이</h5>
        <div class="indGrid" id="gOverlay"></div>
        <h5>보조 패널</h5>
        <div class="indGrid" id="gPane"></div>
        <h5>신호·가격선</h5>
        <div class="indGrid" id="gSig"></div>
      </div>
    </div>
  </div>
  <div id="tfnote"></div>
  <div id="legend"></div>
  <div class="pane" id="pMain"><div id="cMain"></div></div>
  <div class="pane" id="pVol"><span class="plabel">거래량</span><div id="cVol"></div></div>
  <div class="pane" id="pRsi"><span class="plabel">RSI 14 (30/70)</span><div id="cRsi"></div></div>
  <div class="pane" id="pMacd"><span class="plabel">MACD 12·26·9</span><div id="cMacd"></div></div>
  <div class="pane" id="pStoch"><span class="plabel">스토캐스틱 슬로우 14·3·3 (20/80)</span><div id="cStoch"></div></div>
  <div class="pane" id="pObv"><span class="plabel">OBV (거래량 누적)</span><div id="cObv"></div></div>
  <div id="attrib"><a href="https://www.tradingview.com/" target="_blank"
    rel="noopener">Charts: TradingView Lightweight Charts™</a></div>
</div>
<script>
const D = __DATA__;
const C = __COLORS__;
const H = __HEIGHT__;
const root = document.documentElement;
root.style.setProperty('--bg', C.bg); root.style.setProperty('--bd', C.border);
root.style.setProperty('--tx', C.text); root.style.setProperty('--lg', C.legend);
document.getElementById('ttl').textContent = D.name + ' 종합 차트';

const mainH = Math.round(H * 0.52), subH = Math.round(H * 0.15);
const base = {
  layout: { background: { color: C.panel }, textColor: C.text,
            fontFamily: "'Pretendard', sans-serif", fontSize: 11 },
  grid: { vertLines: { color: C.grid }, horzLines: { color: C.grid } },
  rightPriceScale: { borderColor: C.border },
  timeScale: { borderColor: C.border, timeVisible: false },
  crosshair: { mode: 0 },
  handleScroll: true, handleScale: true,
};
function mk(id, h, hideTime) {
  const el = document.getElementById(id);
  const o = JSON.parse(JSON.stringify(base));
  o.width = document.getElementById('wrap').clientWidth || 900;
  o.height = h;
  if (hideTime) o.timeScale.visible = false;
  return LightweightCharts.createChart(el, o);
}
const chMain  = mk('cMain',  mainH, false);
const chVol   = mk('cVol',   subH, true);
const chRsi   = mk('cRsi',   subH, true);
const chMacd  = mk('cMacd',  subH, true);
const chStoch = mk('cStoch', subH, true);
const chObv   = mk('cObv',   subH, false);
const charts = [chMain, chVol, chRsi, chMacd, chStoch, chObv];

// ── 메인 시리즈 ─────────────────────────────────────────
const sCandle = chMain.addCandlestickSeries({
  upColor: '#ff453a', downColor: '#0a84ff',
  borderUpColor: '#ff453a', borderDownColor: '#0a84ff',
  wickUpColor: '#ff453a', wickDownColor: '#0a84ff' });
sCandle.setData(D.candles);
// 기본 scaleMargins(위 20%·아래 10%)에 DeMARK 마커 여백까지 겹치면
// 가격축이 0 아래로 늘어난다 — 위아래 5%로 줄여 캔들을 크게 보인다.
chMain.priceScale('right').applyOptions({
  scaleMargins: { top: 0.05, bottom: 0.05 } });

function line(ch, data, col, w, style) {
  const s = ch.addLineSeries({ color: col, lineWidth: w || 1,
    lineStyle: style || 0, priceLineVisible: false, lastValueVisible: false });
  s.setData(data); return s;
}

// 오버레이 지표 정의 — 지표 선택창의 '가격 오버레이' 그룹
const overlayDefs = [
  { id:'ma5',   label:'MA 5',    col:'#ff9f0a', mk:() => line(chMain, D.mas.ma5||[],   '#ff9f0a', 1) },
  { id:'ma20',  label:'MA 20',   col:'#32ade6', mk:() => line(chMain, D.mas.ma20||[],  '#32ade6', 2) },
  { id:'ma60',  label:'MA 60',   col:'#30d158', mk:() => line(chMain, D.mas.ma60||[],  '#30d158', 1) },
  { id:'ma120', label:'MA 120',  col:'#bf5af2', mk:() => line(chMain, D.mas.ma120||[], '#bf5af2', 1) },
  { id:'ema20', label:'EMA 20',  col:'#64d2ff', mk:() => line(chMain, D.mas.ema20||[], '#64d2ff', 1, 2) },
  { id:'bb',    label:'볼린저밴드', col:'#bf5af2', mk:() => [
      line(chMain, D.bbU, '#bf5af299', 1, 1), line(chMain, D.bbL, '#bf5af299', 1, 1)] },
];
// 보조 패널 정의 — '보조 패널' 그룹 (켜고 끄면 패널 자체가 나타나고 사라진다)
const paneDefs = [
  { id:'vol',   label:'거래량',    col:'#2997ff', pane:'pVol',   ch:chVol,
    mk:() => { const s = chVol.addHistogramSeries({ priceFormat:{type:'volume'},
      priceLineVisible:false, lastValueVisible:false }); s.setData(D.volume); return s; } },
  { id:'rsi',   label:'RSI',      col:'#bf5af2', pane:'pRsi',   ch:chRsi,
    mk:() => { const s = line(chRsi, D.rsi, '#bf5af2', 2);
      [30, 70].forEach(lv => s.createPriceLine({ price: lv, color: C.legend+'55',
        lineWidth: 1, lineStyle: 2, title: String(lv) })); return s; } },
  { id:'macd',  label:'MACD',     col:'#2997ff', pane:'pMacd',  ch:chMacd,
    mk:() => { const h = chMacd.addHistogramSeries({ priceLineVisible:false,
        lastValueVisible:false }); h.setData(D.hist);
      return [h, line(chMacd, D.macd, '#2997ff', 2), line(chMacd, D.signal, '#ff9f0a', 1)]; } },
  { id:'stoch', label:'스토캐스틱', col:'#ffd60a', pane:'pStoch', ch:chStoch,
    mk:() => { const k = line(chStoch, D.stochK, '#ffd60a', 2);
      line(chStoch, D.stochD, '#ff453a', 1);
      [20, 80].forEach(lv => k.createPriceLine({ price: lv, color: C.legend+'55',
        lineWidth: 1, lineStyle: 2, title: String(lv) })); return k; } },
  { id:'obv',   label:'OBV',      col:'#30d158', pane:'pObv',   ch:chObv,
    mk:() => line(chObv, D.obv, '#30d158', 2) },
];
// 신호·가격선 정의
const sigDefs = [
  { id:'demark', label:'DeMARK 9·13', col:'#30d158' },
  { id:'plines', label:'실행 가격선',  col:'#ffd60a' },
];

// 기본 켜짐 + localStorage 복원
const DEFAULT_ON = ['ma5','ma20','ma60','ma120','bb','vol','rsi','macd','demark','plines'];
let saved = null;
try { saved = JSON.parse(localStorage.getItem('qchart_ind_v1')); } catch (e) {}
const isOn = id => Array.isArray(saved) ? saved.includes(id) : DEFAULT_ON.includes(id);
function persist() {
  const on = [...document.querySelectorAll('#indPanel input:checked')].map(i => i.dataset.id);
  try { localStorage.setItem('qchart_ind_v1', JSON.stringify(on)); } catch (e) {}
}

const live = {};                     // id → 시리즈(또는 배열)
function setSeriesVisible(obj, vis) {
  (Array.isArray(obj) ? obj : [obj]).forEach(s =>
    s.applyOptions({ visible: vis }));
}
let priceLines = [];
function applyPLines(on) {
  priceLines.forEach(pl => sCandle.removePriceLine(pl)); priceLines = [];
  if (!on) return;
  for (const p of D.plines)
    priceLines.push(sCandle.createPriceLine({ price: p.price, color: p.color,
      lineWidth: 1, lineStyle: p.lineStyle, axisLabelVisible: true, title: p.title }));
}
function applyMarkers(on) { sCandle.setMarkers(on ? D.markers : []); }

function addCheck(grid, def, checked, onChange) {
  const lb = document.createElement('label');
  lb.innerHTML = `<input type="checkbox" data-id="${def.id}"` +
    `${checked ? ' checked' : ''}><span class="sw" style="background:${def.col}">` +
    `</span>${def.label}`;
  lb.querySelector('input').addEventListener('change', e => {
    onChange(e.target.checked); persist(); });
  document.getElementById(grid).appendChild(lb);
}

for (const d of overlayDefs) {
  live[d.id] = d.mk();
  const on = isOn(d.id);
  setSeriesVisible(live[d.id], on);
  addCheck('gOverlay', d, on, v => setSeriesVisible(live[d.id], v));
}
for (const d of paneDefs) {
  live[d.id] = d.mk();
  const on = isOn(d.id);
  document.getElementById(d.pane).style.display = on ? '' : 'none';
  addCheck('gPane', d, on, v => {
    document.getElementById(d.pane).style.display = v ? '' : 'none';
    relayout();
  });
}
addCheck('gSig', sigDefs[0], isOn('demark'), v => applyMarkers(v));
addCheck('gSig', sigDefs[1], isOn('plines'), v => applyPLines(v));
applyMarkers(isOn('demark'));
applyPLines(isOn('plines'));

// 마지막으로 보이는 보조 패널에만 시간축을 보여준다
function relayout() {
  const visPanes = paneDefs.filter(d =>
    document.getElementById(d.pane).style.display !== 'none');
  paneDefs.forEach(d => d.ch.timeScale().applyOptions({ visible: false }));
  if (visPanes.length)
    visPanes[visPanes.length - 1].ch.timeScale().applyOptions({ visible: true });
  else
    chMain.timeScale().applyOptions({ visible: true });
  window.dispatchEvent(new Event('resize'));
}
relayout();

// 지표 선택창 열고 닫기
const indBtn = document.getElementById('indBtn');
const indPanel = document.getElementById('indPanel');
indBtn.onclick = e => { e.stopPropagation(); indPanel.classList.toggle('open'); };
document.addEventListener('click', e => {
  if (!indPanel.contains(e.target)) indPanel.classList.remove('open'); });

// ── 팬·줌 동기화 ────────────────────────────────────────
let syncing = false;
for (const src of charts) {
  src.timeScale().subscribeVisibleLogicalRangeChange(r => {
    if (syncing || !r) return; syncing = true;
    for (const dst of charts) if (dst !== src)
      dst.timeScale().setVisibleLogicalRange(r);
    syncing = false;
  });
}
// 십자선 범례
const legend = document.getElementById('legend');
const fmt = v => v == null ? '—' : Number(v).toLocaleString('ko-KR',
  { maximumFractionDigits: 2 });
chMain.subscribeCrosshairMove(p => {
  if (!p || !p.time || !p.seriesData) return;
  const c = p.seriesData.get(sCandle);
  if (c) legend.innerHTML =
    `<b style="color:${C.text}">${p.time}</b>&nbsp; ` +
    `시 ${fmt(c.open)} · 고 <span style="color:#ff453a">${fmt(c.high)}</span>` +
    ` · 저 <span style="color:#0a84ff">${fmt(c.low)}</span> · 종 ` +
    `<b style="color:${C.text}">${fmt(c.close)}</b> ${D.unit}`;
});

// ── 기간 버튼 ───────────────────────────────────────────
function setRange(months) {
  // 라운드 199 — 봉 단위마다 **한 달에 들어가는 봉 수가 다르다.**
  //   일 21 · 주 4.3 · 월 1. 이걸 안 나누면 주봉에서 '1년' 이 5년치를
  //   보여 준다 (같은 수를 다른 단위로 읽는 것 — 라운드 190 의 그 모양).
  const perMonth = { D: 21, W: 4.3, M: 1 }[typeof curTf === 'undefined'
    ? 'D' : curTf] || 21;
  const n = (sCandle.data && sCandle.data() ? sCandle.data().length
             : D.candles.length) || D.candles.length;
  const bars = months === 0 ? n : Math.min(n, Math.max(5,
    Math.round(months * perMonth)));
  chMain.timeScale().setVisibleLogicalRange({ from: n - bars - 0.5, to: n + 2 });
}
document.querySelectorAll('.rngbtn').forEach(b => b.onclick = () => {
  document.querySelectorAll('.rngbtn').forEach(x => x.classList.remove('on'));
  b.classList.add('on'); setRange(parseInt(b.dataset.m));
});
setRange(12);

// ── 봉 단위 (일·주·월) ──────────────────────────────────────
//   사용자 지적: "종합차트에 분봉, 일봉, 주봉도 되게 해줘야지."
//   주봉·월봉은 **일봉을 묶어** 만든다 — 새 자료를 받아 오지 않는다.
//   시가=첫 봉 시가 · 고가=최고 · 저가=최저 · 종가=마지막 봉 종가 ·
//   거래량=합. 지어내는 값이 없다.
//   분봉은 **자료가 없다.** 버튼을 비활성으로 두고 이유를 적는다 —
//   숨기면 "왜 없지"를 알 수 없다.
function bucketKey(tsSec, tf) {
  const d = new Date(tsSec * 1000);
  if (tf === 'M') return d.getUTCFullYear() * 100 + (d.getUTCMonth() + 1);
  // 주: 그 주의 월요일로 묶는다 (ISO)
  const wd = (d.getUTCDay() + 6) % 7;          // 월=0
  const mon = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() - wd);
  return Math.floor(mon / 86400000);
}
function aggregate(tf) {
  if (tf === 'D') return { candles: D.candles, volume: D.volume };
  const cs = [], vs = [];
  let key = null, cur = null, vol = 0;
  for (let i = 0; i < D.candles.length; i++) {
    const c = D.candles[i];
    const t = (typeof c.time === 'number') ? c.time
      : Math.floor(Date.parse(c.time + 'T00:00:00Z') / 1000);
    const k = bucketKey(t, tf);
    if (k !== key) {
      if (cur) { cs.push(cur); vs.push({ time: cur.time, value: vol,
        color: (D.volume[i - 1] || {}).color }); }
      key = k; cur = { time: c.time, open: c.open, high: c.high,
                       low: c.low, close: c.close }; vol = 0;
    } else {
      cur.high = Math.max(cur.high, c.high);
      cur.low = Math.min(cur.low, c.low);
      cur.close = c.close;
    }
    const v = D.volume[i];
    if (v && typeof v.value === 'number') vol += v.value;
  }
  if (cur) { cs.push(cur); vs.push({ time: cur.time, value: vol }); }
  return { candles: cs, volume: vs };
}
let curTf = 'D';
const TF_LABEL = { D: '일봉', W: '주봉', M: '월봉' };
function setTf(tf) {
  if (tf === curTf) return;
  curTf = tf;
  const agg = aggregate(tf);
  sCandle.setData(agg.candles);
  if (live.vol) {
    const vseries = Array.isArray(live.vol) ? live.vol[0] : live.vol;
    if (vseries && vseries.setData) vseries.setData(agg.volume);
  }
  // 지표는 **일봉으로 계산된 값**이다. 주봉·월봉 캔들 위에 그대로 얹으면
  // 다른 잣대를 겹쳐 읽게 된다 — 그래서 끈다 (라운드 190 의 교훈).
  const note = document.getElementById('tfnote');
  if (tf === 'D') {
    note.textContent = '';
  } else {
    document.querySelectorAll('#gOverlay input, #gPane input').forEach(inp => {
      if (inp.checked && inp.dataset.id !== 'vol') {
        inp.checked = false; inp.dispatchEvent(new Event('change'));
      }
    });
    note.textContent = TF_LABEL[tf] + '은 일봉을 묶어 만든 값입니다'
      + ' (시가=첫 봉·고가=최고·저가=최저·종가=마지막 봉·거래량=합).'
      + ' 지표는 일봉으로 계산한 값이라 함께 껐습니다 —'
      + ' 다른 잣대를 겹쳐 읽지 않기 위해서입니다.';
  }
  setRange(parseInt(
    (document.querySelector('.rngbtn.on') || { dataset: { m: '12' } }).dataset.m));
}
document.querySelectorAll('.tfbtn').forEach(b => {
  if (b.disabled) return;
  b.onclick = () => {
    document.querySelectorAll('.tfbtn').forEach(x => x.classList.remove('on'));
    b.classList.add('on'); setTf(b.dataset.tf);
  };
});

window.__dbg = { charts, sCandle, mainH };
window.addEventListener('resize', () => {
  const w = document.getElementById('wrap').clientWidth;
  charts.forEach((c, i) => c.applyOptions({ width: w,
    height: i === 0 ? mainH : subH }));
});
window.dispatchEvent(new Event('resize'));
</script>
</body></html>
"""
