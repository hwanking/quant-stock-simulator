// 차트 스크립트가 **끝까지 도는가** — 소스를 읽지 말고 실행해 본다 (라운드 201)
//
// ■ 왜 필요한가
//   라운드 199 가 봉 단위(일·주·월) 버튼을 넣었고, 회귀 §227 은 소스에
//   `data-tf="W"` 가 있는지 **글자로** 확인해 통과했다. 그런데 브라우저
//   에서는 **스크립트가 중간에 죽어 있었다**:
//
//       setRange(12);          // ← 여기서 호출
//       ...
//       let curTf = 'D';       // ← 선언은 뒤
//
//   `setRange` 안에서 `typeof curTf` 를 썼는데 `let` 은 **TDZ** 라
//   `typeof` 로도 막히지 않는다. ReferenceError 가 나서 그 뒤 코드가
//   통째로 죽었다 — 봉 버튼 바인딩·__dbg·리사이즈 핸들러까지.
//   **차트는 이미 그려진 뒤라 눈으로는 멀쩡해 보였다.**
//
//   §222 가 파이썬에서 배운 것과 같은 말이다 — **존재는 실행이 아니다.**
//   그래서 여기서는 진짜로 돌린다.
//
// ■ 무엇을 하나
//   최소 DOM 스텁 위에서 차트 스크립트를 실행하고, **끝줄까지 닿았는지**
//   를 `window.__dbg` 로 확인한다. 그 줄은 스크립트의 마지막이라, 앞에서
//   무엇이 던지면 없다.
//
// 실행:  node scripts/chart_js_smoke.js <chart.html>
'use strict';

const fs = require('fs');

// ── 무엇을 물어도 스텁을 돌려주는 DOM (라운드 201) ──────────────────
//   손으로 DOM 을 흉내 내면 스텁이 얇아서 그쪽이 먼저 터진다. 그러면
//   재려던 것(스크립트가 끝까지 도는가)을 못 잰다. 그래서 **DOM 은 절대
//   안 터지게** 하고, 남는 예외만 본다 — TDZ·ReferenceError·문법.
function stub(name) {
  const target = function () { return stub(name + '()'); };
  target.__stub = name;
  return new Proxy(target, {
    get(t, k) {
      if (k === Symbol.toPrimitive) return () => 0;
      if (k === Symbol.iterator) return function* () {};
      if (k === 'length') return 0;
      if (k === 'then') return undefined;          // await 오작동 방지
      if (k === 'toString') return () => '';
      if (k === 'valueOf') return () => 0;
      if (k === '__stub') return name;
      if (k === 'dataset') return stub(name + '.dataset');
      if (k in t && typeof t[k] !== 'undefined' && k !== 'name') return t[k];
      return stub(name + '.' + String(k));
    },
    set() { return true; },
    has() { return true; },
    apply() { return stub(name + '()'); },
    construct() { return stub('new ' + name); },
  });
}

function makeSeries() {
  let data = [];
  const s = stub('series');
  return new Proxy(s, {
    get(t, k) {
      if (k === 'setData') return d => { data = d || []; };
      if (k === 'data') return () => data;
      return t[k];
    },
    set() { return true; },
  });
}

function makeChart() {
  const c = stub('chart');
  return new Proxy(c, {
    get(t, k) {
      if (k === 'addCandlestickSeries' || k === 'addLineSeries'
          || k === 'addHistogramSeries' || k === 'addAreaSeries') {
        return makeSeries;
      }
      return t[k];
    },
    set() { return true; },
  });
}

function run(htmlPath) {
  const html = fs.readFileSync(htmlPath, 'utf8');
  // 인라인 <script> 중 **마지막**이 차트 코드다 (앞은 라이브러리 번들)
  const scripts = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)]
    .map(m => m[1]).filter(s => s.trim().length > 200);
  if (!scripts.length) throw new Error('인라인 스크립트를 못 찾았다');
  const code = scripts[scripts.length - 1];

  const doc = stub('document');
  const store = {};                       // window 에 **실제로 대입된 것**
  const real = {
    document: doc,
    LightweightCharts: { createChart: makeChart },
    console,
    devicePixelRatio: 1,
    Event: function (t) { this.type = t; },
    addEventListener() {}, removeEventListener() {}, dispatchEvent() {},
    setTimeout() { return 0; }, clearTimeout() {},
    requestAnimationFrame() { return 0; },
  };
  const win = new Proxy(function () {}, {
    get(t, k) {
      if (k === 'window' || k === 'self') return win;
      if (k in real) return real[k];
      if (k in store) return store[k];
      return stub('window.' + String(k));
    },
    set(t, k, v) { store[k] = v; return true; },   // __dbg 를 여기서 잡는다
    has() { return true; },
  });

  const fn = new Function('window', 'document', 'LightweightCharts', 'console',
                          'Event', 'setTimeout', 'requestAnimationFrame',
                          '"use strict";\n' + code);
  fn(win, doc, real.LightweightCharts, console, real.Event,
     real.setTimeout, real.requestAnimationFrame);
  return store;
}

if (require.main === module) {
  const p = process.argv[2];
  try {
    const store = run(p);
    const done = Object.prototype.hasOwnProperty.call(store, '__dbg');
    console.log(JSON.stringify({ ok: true, reached_end: done,
                                 assigned: Object.keys(store).slice(0, 8) }));
    process.exit(done ? 0 : 3);
  } catch (e) {
    console.log(JSON.stringify({ ok: false,
      error: String((e && e.message) || e).slice(0, 300) }));
    process.exit(2);
  }
}

module.exports = { run };
