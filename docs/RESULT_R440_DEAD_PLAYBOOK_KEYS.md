# 라운드 440 — 이슈 교본의 죽은 항목 일곱 · 읽는 곳 없는 버전 비교 생성기

2026-10-07 · 코드 문구·목록만 · 판정·점수·문턱·화면 값 불변 · 버전 없음

라운드 435·438 이 *"찾았지만 미뤘다"* 고 적은 둘을 닫았다.

## ① 교본(PLAYBOOK)의 열쇠 열셋 중 일곱은 열어 주는 규칙이 없다

`improvement/issue_ops.PLAYBOOK` 은 등록부의 **열린** 이슈에 붙는 원인·영향·조치·안전조치 문구의 한 곳이다(R394). 그런데 그 열쇠를
실제로 여는 것은 일일 파이프라인의 `create_issue(..., issue_key=…)` 셋(`validation|high_conf_n` · `model|vb_gap` ·
`usability|signal_rate`)과 사람이 스크립트로 넣은 셋(`score_not_separating` · `loss_control_tradeoff` · `ledger_path_window`)뿐이다.
나머지 **일곱**(`regime_dependence` · `overfit_gap` · `stop_width` · `validation_not_wired` · `negative_edge` · `us_overnight` ·
`index_missing`)은 여는 규칙도 등록부 행도 없다 — 화면에 나갈 수 없는 죽은 글이고, 라운드 421(`us_overnight`)·426(`index_missing`)은
그중 둘의 문구를 *화면에 나간다고 믿고* 고쳤다(`index_missing` 의 화면 이슈는 `product_ops` 의 화면 규칙이지 등록부가 아니다).

- 손 목록으로 적지 않는다 — `issue_ops.creatable_keys()` 가 스크립트 AST(`create_issue` 의 `issue_key` 리터럴)와 등록부 열쇠의
  합집합을 유도하고, `unreachable_playbook_keys()` 가 교본과 대 본다. 회귀 §426 이 그 일곱이 **그대로**인지 본다(늘면 여는 규칙 없이
  교본만 더한 것 · 줄면 여는 규칙이 생긴 것 — 어느 쪽이든 보여야 한다).
- 지우지 않았다 — 결정의 기록이다(R297 이 죽은 표를 남긴 판단). 다만 **거짓 주장은 고쳤다**: `validation_not_wired` 의 조치
  *"③ 버전별 비교는 이번에 만들었습니다(gen_version_compare.py)"* 와 안전조치 *"'아직 연결되지 않은 것도 있습니다'라고 판단 화면에서
  밝힙니다"*(그 문장은 저장소 어디에도 없다 — 라운드 252 가 화면을 엔진 값 읽기로 바꿨다). 버전별로 세는 것은 전방 기록부(행마다
  버전 · R360)와 11-16 채점기(`forward_judge` · R398)라고 적었다.
- 나머지 여섯의 날짜 없는 옛 수(`overfit_gap` 의 67.0/31.1% · `stop_width` 의 11.7%/5.25% · `negative_edge` 의 손익비 등)는
  **고치지 않았다** — 나갈 수 없는 글을 오늘 수로 고쳐 적으면 그것이 또 낡는다. 여는 규칙이 생기는 날 §426 이 먼저 붉어지고 그때 잰다.

## ② `scripts/gen_version_compare.py` — 2026-08-02 에 한 번, 읽는 곳 0

`.portfolio/version_compare.json`(버전 1개)을 남긴 뒤 화면·스크립트·워크플로 어디도 읽지 않고 자동 실행에도 없다. 규칙도 낡았다 —
비용 0.30(운영 0.41 · R350) · 매수권 58점(R393) · `success` 를 그대로 셈(미결을 실패로 · R424) · 원장 전 행(통계 행 아님 · R389·R391).
그리고 같은 원장을 다른 시점에 잰 것이라 버전 간 비교 자체가 성립하지 않는다(R282 — 채점은 매 실행 현행 엔진으로 다시 돈다).
파일은 기록으로 두고 머리말에 그 사실을 적었으며, 백업 화이트리스트에서 `version_compare.json` 을 뺐다(만든 것은 실린 것이 되게 한
R261 의 거울상 — 읽는 곳 없는 것을 매일 실어 나를 이유가 없다).

## 검사

§426(3건) — ① 유도한 죽은 열쇠 = 일곱 · 일일 규칙의 셋은 열린다(훑은 파일 수 찍음) ② 교본 문구에 거짓 주장 없음 ③ 백업 목록에
없음 · 생성기 머리말.
