# 라운드 201 — 어제 넣은 봉 버튼이 실제로는 안 돌고 있었다

측정: 2026-09-01 · 근거: 브라우저 실측 · `scripts/chart_js_smoke.js`

## 무슨 일이 있었나

라운드 199 가 사용자 요청으로 차트에 **일봉·주봉·월봉** 버튼을 넣었다.
회귀 §227 은 소스에 `data-tf="W"` 가 있는지 **글자로** 확인해 통과했고,
나는 그것으로 "됐다"고 적었다.

그리고 화면에서 눌러 봤다. **안 눌렸다.**

```js
window.__dbg   // undefined
```

라이브러리는 로드돼 있고(`typeof LightweightCharts === 'object'`),
캔들도 그려져 있었다(캔버스 42개, 제목도 JS 가 채운 값). 그런데 스크립트
**마지막 줄**이 만드는 `__dbg` 가 없었다 — 중간에 죽었다는 뜻이다.

## 원인 — `let` 의 TDZ

```js
document.querySelectorAll('.rngbtn').forEach(...);   // 여기까지는 붙는다
setRange(12);                                        // ← 여기서 던진다
// ─ 아래가 전부 죽는다 ─
function bucketKey(...) {}
let curTf = 'D';
document.querySelectorAll('.tfbtn').forEach(...);    // 봉 버튼 바인딩
window.__dbg = { ... };
window.addEventListener('resize', ...);
```

`setRange` 안에서 이렇게 썼다:

```js
const perMonth = { D: 21, W: 4.3, M: 1 }[
  typeof curTf === 'undefined' ? 'D' : curTf] || 21;
```

`typeof` 로 감쌌으니 안전하다고 생각했다. **아니다.** `var` 라면
맞지만 `curTf` 는 `let` 이고, `let` 은 선언 전에는 **TDZ(Temporal Dead
Zone)** 에 있어 `typeof` 로도 접근할 수 없다 — `ReferenceError` 다.

그래서 `setRange(12)` 가 던졌고, **그 아래 전부가 죽었다**:
봉 버튼 바인딩 · `__dbg` · 리사이즈 핸들러. 게다가 초기 보이는 범위도
설정되지 않았다.

**그런데 캔들은 이미 그려진 뒤라 눈으로는 멀쩡해 보였다.** 버튼도
정적 HTML 이라 **보이기는 했다** — 눌러야만 안다.

## 왜 검사가 못 잡았나

§227 이 본 것:

```python
check(f"차트에 {_lb227} 버튼이 있다", f'data-tf="{_tf227}"' in _c227)
```

**소스에 글자가 있는지**만 봤다. 그 글자가 만드는 버튼이 **동작하는지**는
안 봤다. 라운드 191 이 파이썬에서 얻은 결론과 **똑같은 말**이다:

> **존재는 실행이 아니다.**

그때는 상수의 존재만 보고 그 줄을 실행하지 않아 `NameError` 를 놓쳤다.
이번엔 버튼의 존재만 보고 스크립트를 실행하지 않아 `ReferenceError` 를
놓쳤다. **언어만 바뀌었다.**

## 고침 둘

**① 선언 순서에 기대지 않는다.** `curTf` 변수를 없애고 **DOM 에서**
현재 봉을 읽는다 — 켜져 있는 버튼이 곧 현재 봉이다.

```js
function activeTf() {
  const b = document.querySelector('.tfbtn.on');
  return (b && b.dataset && b.dataset.tf) || 'D';
}
```

버튼 클릭 핸들러가 `.on` 을 먼저 옮기고 `setTf` 를 부르므로, 그 안에서
`setRange` 가 읽는 값은 항상 맞다. **상태를 두 곳에 두지 않는다**는
점에서 §4 와 같은 방향이다.

**② node 로 진짜 돌린다** (`scripts/chart_js_smoke.js`).

차트 HTML 에서 마지막 인라인 스크립트를 떼어 실행하고, **끝줄이 만드는
`__dbg` 가 대입됐는지** 본다. 앞에서 무엇이 던지면 없다.

DOM 은 **무엇을 물어도 스텁을 돌려주는 Proxy** 다. 손으로 DOM 을 흉내
내면 스텁이 얇아서 그쪽이 먼저 터지고(실제로 처음에 그랬다 —
*"Cannot read properties of undefined (reading 'style')"*), 그러면 재려던
것을 못 잰다. **DOM 은 절대 안 터지게 하고 남는 예외만 본다** —
TDZ · ReferenceError · 문법.

## 검사 (§229)

- 차트 HTML 을 만든다 (0바이트면 미측정)
- **node 로 실행**해 끝까지 도는지 (`rc=0`)
- **심어서** — 그 버그를 되심으면 잡는가:

```
{"ok":false,"error":"Cannot access 'curTf' before initialization"}
```

- 심을 자리를 못 찾으면 그것도 실패다 (심기가 헛돌지 않게)
- node 가 없으면 **건너뜀**으로 남긴다 — 통과가 아니다

## 곁들여 — §226 이 이 절을 쓰는 도중에 나를 잡았다

§229 를 쓰면서 차트 호출을 이렇게 적었다:

```python
_html229 = _cp229.build_chart_html(tech_df, four_scores, ..., core=CORE)
```

`tech_df` · `four_scores` · `CORE` 는 **web_app 의 이름**이지 이 파일의
이름이 아니다. 라운드 197 이 넣은 §226(정의 전 사용)이 **40분짜리 회귀를
돌리기 전에** 3건으로 잡았다.

두 라운드 전에 넣은 검사가 곧바로 값을 했다. 그리고 §110(이모지)도
잡았다 — 이 문서와 같은 `⚠️` 를 JS 주석에 썼는데, 그 주석이 **차트 HTML
템플릿 문자열 안**이라 화면 문자열로 센다(§5). 옳은 판정이라 글자를
`[주의]` 로 바꿨다.
