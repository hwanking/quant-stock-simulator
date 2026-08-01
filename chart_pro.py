# -*- coding: utf-8 -*-
"""
종합 인터랙티브 차트 — TradingView Lightweight Charts(Apache 2.0) 기반.

원칙:
  · 라이브러리 JS는 vendor/ 에 통째로 내장한다 — 시세·종목 데이터가 외부로
    나가지 않고(전부 iframe 안에 인라인), 오프라인·클라우드 어디서든 뜬다.
  · 지표는 이미 검증된 tech_df 값을 그대로 쓴다(차트가 따로 계산해 어긋나는
    것을 막는다). 여기서 새로 계산하는 것은 MA120·MACD 뿐이다.
  · 실행 가격선(손절/목표/추천매수/TDST)은 four_scores 의 값 — 화면 배너와
    같은 숫자다.
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
                 border='#2d3139', legend='#a0a5b5', wm='rgba(160,165,181,0.12)'),
    'light': dict(bg='#ffffff', panel='#ffffff', text='#3a3f4a', grid='#eef1f6',
                  border='#dde2ea', legend='#5a5f6b', wm='rgba(90,95,107,0.10)'),
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
                     theme='dark', user_avg=None, n_bars=360, height=780):
    """전체 차트 HTML(문자열)을 만든다. st.components.v1.html 로 넣는다."""
    th = _THEMES.get(theme, _THEMES['dark'])
    df = tech_df.tail(n_bars).copy().reset_index(drop=True)

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

    # 이동평균 — 5/20/60 은 검증된 컬럼, 120 만 여기서 계산
    mas = {}
    for col, key in (('sma_5', 'ma5'), ('sma_20', 'ma20'), ('sma_60', 'ma60')):
        if col in df.columns:
            mas[key] = _series(times, [_f(x) for x in df[col]])
    _closes_full = [c for c in closes]
    ma120 = []
    for i in range(len(_closes_full)):
        w = [c for c in _closes_full[max(0, i - 119):i + 1] if c is not None]
        ma120.append(sum(w) / len(w) if len(w) >= 120 else None)
    mas['ma120'] = _series(times, ma120)

    bb_u = _series(times, [_f(x) for x in df['bb_upper']]) if 'bb_upper' in df.columns else []
    bb_l = _series(times, [_f(x) for x in df['bb_lower']]) if 'bb_lower' in df.columns else []
    rsi = _series(times, [_f(x) for x in df['rsi_14']]) if 'rsi_14' in df.columns else []

    # MACD(12, 26, 9)
    cl = [c if c is not None else 0.0 for c in closes]
    macd_line = [a - b for a, b in zip(_ema(cl, 12), _ema(cl, 26))]
    sig_line = _ema(macd_line, 9)
    macd = _series(times, macd_line)
    signal = _series(times, sig_line)
    hist = [{'time': t, 'value': round(m - s, 4),
             'color': (_UP if m - s >= 0 else _DN) + '99'}
            for t, m, s in zip(times, macd_line, sig_line)]

    # DeMARK 마커 — 엔진이 만든 시리즈 그대로 (셋업 9 / 카운트다운 13)
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

    # 실행 가격선 — 배너와 같은 숫자만 쓴다
    fs = four_scores or {}
    plines = []
    for val, label, color, style in (
            (fs.get('recommended_buy_price'), '추천 매수가', '#ffd60a', 2),
            (fs.get('target_tech_1st'), '1차 목표가', '#30d158', 2),
            (fs.get('target_tech_2nd'), '2차 목표가', '#2997ff', 2),
            (fs.get('stop_loss_price'), '손절가', '#ff453a', 0),
            (dm.get('tdst_support'), 'TDST 지지', '#30d15888', 1),
            (dm.get('tdst_resistance'), 'TDST 저항', '#ff9f0a88', 1),
            (user_avg, '내 평단가', '#bf5af2', 0)):
        v = _f(val)
        if v and v > 0:
            plines.append({'price': v, 'title': label, 'color': color,
                           'lineStyle': style})

    payload = json.dumps({
        'candles': candles, 'volume': volume, 'mas': mas,
        'bbU': bb_u, 'bbL': bb_l, 'rsi': rsi,
        'macd': macd, 'signal': signal, 'hist': hist,
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

    colors = json.dumps(th)
    return _HTML_TEMPLATE \
        .replace('__LIB__', lib_tag) \
        .replace('__DATA__', payload) \
        .replace('__COLORS__', colors) \
        .replace('__HEIGHT__', str(int(height)))


_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
__LIB__
<style>
  html, body { margin:0; padding:0; background: transparent;
    font-family: 'Pretendard', -apple-system, 'Malgun Gothic', sans-serif; }
  #wrap { border: 1px solid var(--bd); border-radius: 14px; overflow: hidden;
    background: var(--bg); }
  #toolbar { display:flex; flex-wrap:wrap; gap:6px 14px; align-items:center;
    padding: 10px 14px; border-bottom: 1px solid var(--bd);
    color: var(--lg); font-size: 12.5px; }
  #toolbar b.ttl { color: var(--tx); font-size: 13.5px; margin-right: 6px; }
  #toolbar label { display:flex; align-items:center; gap:4px; cursor:pointer;
    user-select:none; }
  #toolbar input { accent-color:#2997ff; }
  .rngbtn { border:1px solid var(--bd); background:transparent; color:var(--lg);
    border-radius:7px; padding:2px 9px; cursor:pointer; font-size:12px; }
  .rngbtn.on { background:#2997ff; color:#fff; border-color:#2997ff; }
  #legend { padding: 4px 14px 0 14px; font-size: 12px; color: var(--lg);
    min-height: 17px; }
  .pane { position: relative; }
  .plabel { position:absolute; left:10px; top:6px; z-index:3; font-size:11px;
    color: var(--lg); pointer-events:none; }
  #attrib { text-align:right; padding: 3px 12px 6px 0; font-size: 10px; }
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
    <span style="flex:1"></span>
    <label><input type="checkbox" id="ckMA" checked>이동평균</label>
    <label><input type="checkbox" id="ckBB" checked>볼린저</label>
    <label><input type="checkbox" id="ckDM" checked>DeMARK 9·13</label>
    <label><input type="checkbox" id="ckPL" checked>실행 가격선</label>
  </div>
  <div id="legend"></div>
  <div class="pane"><div id="cMain"></div></div>
  <div class="pane"><span class="plabel">거래량</span><div id="cVol"></div></div>
  <div class="pane"><span class="plabel">RSI 14 (30/70)</span><div id="cRsi"></div></div>
  <div class="pane"><span class="plabel">MACD 12·26·9</span><div id="cMacd"></div></div>
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

const mainH = Math.round(H * 0.55), subH = Math.round(H * 0.15);
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
  o.width = el.parentElement.clientWidth || el.clientWidth || 900;
  o.height = h;
  if (hideTime) o.timeScale.visible = false;
  return LightweightCharts.createChart(el, o);
}
const chMain = mk('cMain', mainH, false);
const chVol  = mk('cVol',  subH, true);
const chRsi  = mk('cRsi',  subH, true);
const chMacd = mk('cMacd', subH, false);
const charts = [chMain, chVol, chRsi, chMacd];

// ── 시리즈 ──────────────────────────────────────────────
const sCandle = chMain.addCandlestickSeries({
  upColor: '#ff453a', downColor: '#0a84ff',
  borderUpColor: '#ff453a', borderDownColor: '#0a84ff',
  wickUpColor: '#ff453a', wickDownColor: '#0a84ff' });
sCandle.setData(D.candles);
// 기본 scaleMargins(위 20%·아래 10%)에 DeMARK 마커 여백까지 겹치면
// 가격축이 0 아래로 늘어난다 — 위아래 5%로 줄여 캔들을 크게 보인다.
chMain.priceScale('right').applyOptions({
  scaleMargins: { top: 0.05, bottom: 0.05 } });

const maDefs = [['ma5','#ff9f0a','MA5'], ['ma20','#32ade6','MA20'],
                ['ma60','#30d158','MA60'], ['ma120','#bf5af2','MA120']];
const maSeries = [];
for (const [k, col, lb] of maDefs) {
  if (!D.mas[k] || !D.mas[k].length) continue;
  const s = chMain.addLineSeries({ color: col, lineWidth: k==='ma20'?2:1,
    priceLineVisible:false, lastValueVisible:false, title: lb });
  s.setData(D.mas[k]); maSeries.push(s);
}
const bbSeries = [];
for (const dat of [D.bbU, D.bbL]) {
  if (!dat.length) continue;
  const s = chMain.addLineSeries({ color: '#bf5af299', lineWidth: 1,
    lineStyle: 1, priceLineVisible:false, lastValueVisible:false });
  s.setData(dat); bbSeries.push(s);
}

// 실행 가격선
let priceLines = [];
function applyPLines(on) {
  priceLines.forEach(pl => sCandle.removePriceLine(pl)); priceLines = [];
  if (!on) return;
  for (const p of D.plines) {
    priceLines.push(sCandle.createPriceLine({ price: p.price, color: p.color,
      lineWidth: 1, lineStyle: p.lineStyle, axisLabelVisible: true,
      title: p.title }));
  }
}
applyPLines(true);

function applyMarkers(on) { sCandle.setMarkers(on ? D.markers : []); }
applyMarkers(true);

const sVol = chVol.addHistogramSeries({ priceFormat: { type: 'volume' },
  priceLineVisible:false, lastValueVisible:false });
sVol.setData(D.volume);

const sRsi = chRsi.addLineSeries({ color: '#bf5af2', lineWidth: 2,
  priceLineVisible:false, lastValueVisible:false });
sRsi.setData(D.rsi);
for (const lv of [30, 70]) sRsi.createPriceLine({ price: lv,
  color: C.legend + '55', lineWidth: 1, lineStyle: 2, title: String(lv) });

const sHist = chMacd.addHistogramSeries({ priceLineVisible:false,
  lastValueVisible:false });
sHist.setData(D.hist);
const sMacd = chMacd.addLineSeries({ color: '#2997ff', lineWidth: 2,
  priceLineVisible:false, lastValueVisible:false });
sMacd.setData(D.macd);
const sSig = chMacd.addLineSeries({ color: '#ff9f0a', lineWidth: 1,
  priceLineVisible:false, lastValueVisible:false });
sSig.setData(D.signal);

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
// 십자선 동기화 + 범례
const legend = document.getElementById('legend');
const fmt = v => v == null ? '—' : Number(v).toLocaleString('ko-KR',
  { maximumFractionDigits: 2 });
chMain.subscribeCrosshairMove(p => {
  if (!p || !p.time || !p.seriesData) { return; }
  const c = p.seriesData.get(sCandle);
  if (c) legend.innerHTML =
    `<b style="color:${C.text}">${p.time}</b>&nbsp; ` +
    `시 ${fmt(c.open)} · 고 <span style="color:#ff453a">${fmt(c.high)}</span>` +
    ` · 저 <span style="color:#0a84ff">${fmt(c.low)}</span> · 종 ` +
    `<b style="color:${C.text}">${fmt(c.close)}</b> ${D.unit}`;
});

// ── 토글·기간 버튼 ──────────────────────────────────────
document.getElementById('ckMA').onchange = e =>
  maSeries.forEach(s => s.applyOptions({ visible: e.target.checked }));
document.getElementById('ckBB').onchange = e =>
  bbSeries.forEach(s => s.applyOptions({ visible: e.target.checked }));
document.getElementById('ckDM').onchange = e => applyMarkers(e.target.checked);
document.getElementById('ckPL').onchange = e => applyPLines(e.target.checked);

function setRange(months) {
  const n = D.candles.length;
  const bars = months === 0 ? n : Math.min(n, Math.round(months * 21));
  chMain.timeScale().setVisibleLogicalRange({ from: n - bars - 0.5, to: n + 2 });
}
document.querySelectorAll('.rngbtn').forEach(b => b.onclick = () => {
  document.querySelectorAll('.rngbtn').forEach(x => x.classList.remove('on'));
  b.classList.add('on'); setRange(parseInt(b.dataset.m));
});
setRange(12);

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
