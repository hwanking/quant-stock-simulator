// 글자 넘침 전수조사 (라운드 515 · 2026-10-13) — 브라우저에서 다 그린 화면에 붙여 돌린다(개발자 도구 콘솔 · 브라우저 도구의 javascript 실행).
//
// "상자"(바탕이나 테두리가 있는 요소 · 버튼)마다, 안의 글자 줄 사각형이 상자 밖으로 1px 넘게 나가는지 센다.
// 오탐 셋을 판별식에 넣었다(첫 판이 셋 다 '넘침'으로 셌다 — 2026-10-13):
//   ① 닫힌 <details>(펼침 칸) 안의 글자 — 브라우저가 그리지 않는데도 위치를 계산해 돌려준다
//   ② 상자와 글자 사이에 잘라 숨기는(hidden·clip) 칸이 있으면 — 그 칸이 글자를 자른다(보이는 넘침이 아니다)
//   ③ 스크롤 칸(auto·scroll) — 넘치는 것이 정상이다
// 다 그린 뒤에만 잰다 — 글자 수가 20초 안 변하고 data-stale 요소가 0 일 때(라운드 399 · 덜 그려진 화면은 가짜 결함을 낸다).
//
// 쓰는 법:  textOverflowCensus('[data-testid="stMain"]')  ·  textOverflowCensus('section[data-testid="stSidebar"]')
// 돌려주는 값: { boxes: 본 상자 수, n: 넘친 상자 수, out: [{tag, tid, key, w, h, over, txt}] }
// ⚠️ 결과의 txt 에는 화면 글자(관심종목 이름 등)가 들어 있다 — 문서·커밋에 옮겨 적지 않는다(§9 · 갈래와 수만 적는다).
function textOverflowCensus(rootSel) {
  function clipsBetween(box, node) {
    let p = node.parentElement;
    while (p && p !== box) {
      const cs = getComputedStyle(p);
      if (/(auto|scroll|hidden|clip)/.test(cs.overflowX + cs.overflowY)) return true;   // ② ③
      if (p.tagName === 'DETAILS' && !p.open) return true;                              // ①
      p = p.parentElement;
    }
    return false;
  }
  const root = document.querySelector(rootSel || '.stApp');
  const out = [];
  let boxes = 0;
  for (const el of root.querySelectorAll('*')) {
    const cs = getComputedStyle(el);
    if (cs.display === 'inline' || cs.display === 'none' || cs.visibility === 'hidden') continue;
    const bg = cs.backgroundColor && cs.backgroundColor !== 'rgba(0, 0, 0, 0)';
    const bd = ['Top', 'Right', 'Bottom', 'Left'].some(s => parseFloat(cs['border' + s + 'Width']) > 0 && cs['border' + s + 'Style'] !== 'none');
    if (!(bg || bd || el.tagName === 'BUTTON')) continue;
    if (/(auto|scroll|hidden|clip)/.test(cs.overflowX + cs.overflowY)) continue;      // 상자 자신이 자르거나 스크롤한다
    if (el.tagName === 'DETAILS' && !el.open) continue;                                 // ① 닫힌 펼침 칸 자신
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) continue;
    if (el.closest('svg, canvas, iframe, [data-testid="stDataFrame"]')) continue;
    boxes++;
    const tw = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    let n, worst = 0, txt = '';
    while ((n = tw.nextNode())) {
      if (!n.textContent.trim()) continue;
      if (clipsBetween(el, n)) continue;
      const rg = document.createRange();
      rg.selectNodeContents(n);
      for (const q of rg.getClientRects()) {
        if (q.width < 1) continue;
        const d = Math.max(q.right - r.right, r.left - q.left, q.bottom - r.bottom, r.top - q.top);
        if (d > worst) { worst = d; txt = n.textContent.trim().slice(0, 30); }
      }
    }
    if (worst > 1) {
      const k = (el.closest('[class*="st-key-"]') || { className: '' }).className.toString().match(/st-key-[\w-]+/);
      out.push({ tag: el.tagName, tid: el.getAttribute('data-testid') || '', key: k ? k[0] : '', w: Math.round(r.width),
                 h: Math.round(r.height), over: Math.round(worst), txt });
    }
  }
  return { boxes, n: out.length, out };
}
