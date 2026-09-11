# 결과 R261 — 클라우드가 매일 만드는 관측 산출물 다섯이 릴리스에 안 실려 그날 버려진다 (2026-09-10)

라운드 259 가 *"워크플로가 셋을 만든다 — 업로드 **앞**(만든 것이 올라가야 화면에 닿는다)"* 라고
적었다. **올라가지 않았다.** 업로드는 `backup_research_data.py` 의 화이트리스트가 고르는데 그
목록은 `.portfolio/` 한 뿌리뿐이고, 관측 산출물 다섯은 전부 `data/` 에 쓰인다.

## 1. 실측 — 사슬의 어느 고리가 비었나

| 고리 | 사실 (2026-09-10) |
|---|---|
| 생성 | 클라우드 단계 "관측 산출물 갱신"이 `data/{sample_audit,effective_n_icc,sector_perf}.json` 을, FN/FP 단계가 `data/{miss_study,weakness_map}.json` 을 **매 평일** 만든다 |
| 신선도 검사 | 맨 뒤 단계가 그 다섯을 읽어 **통과**한다 — 방금 만든 파일을 본다 |
| 업로드 | `backup_research_data.INCLUDE` 는 `.portfolio/` 의 이름만 담는다. `data/` 는 **한 개도 안 담는다** |
| 되받기 | `pull_research_data.unsafe_members` 가 `.portfolio/` 밖 경로를 **거부**한다(zip-slip 가드) — 담아도 못 푼다 |
| 화면 | `web_app._artifact_path` 는 `.portfolio` → `data` 순. 관측 산출물은 `.portfolio` 에 없으므로 **git 의 `data/`** 를 읽는다 |
| git 의 `data/` | 마지막 갱신 **2026-09-10 (R259 · 이 PC 에서 손으로)** · 그 전은 09-08 · 09-03 · 09-02 — 전부 사람 손 |

즉 클라우드의 다섯은 **신선도 검사를 통과한 직후 작업 컨테이너와 함께 사라진다.** 라운드 217 이
*"여덟 배치 동안 한 번도 갱신되지 않았다"* 고 적은 그 상태가, 생성기를 붙인 뒤에도 화면 기준으로는
그대로였다 — 생성이 아니라 **운반**이 없었다. 라운드 102 가 붙인 FN/FP·취약구간 지도 둘도 같은
처지였다(2026-08-10 부터).

## 2. 고침 — 운반로를 만들되 화이트리스트 방식은 지킨다

- **목록을 손으로 적지 않는다.** `backup_research_data.DATA_INCLUDE` 는 `study_freshness.STUDIES`
  에서 **유도**한다 — 신선도 검사가 보는 것이 곧 실어 나르는 것이다. 한쪽에 넣고 다른 쪽을 잊는
  날이 없다(R114 · 손 목록은 낡는다).
- **zip 안의 두 번째 뿌리 `data/`.** `picked_data(name)` 가 DENY(개인 자료 패턴) → DATA_INCLUDE
  순으로 거른다. `*.json` 처럼 통째로 열지 않는다 — 머리말의 약속(*"목록에 없으면 애초에 안
  들어간다"*)이 그대로다.
- **되받는 쪽의 가드는 좁게 연다.** `unsafe_members` 는 `data/<이름>` 을 **`picked_data` 가 참일
  때만** 허용한다. `data/positions.json` 도 `data/research_radar.json` 도 거부한다(§9 · 후자는
  목록 밖). `..` 는 여전히 막는다.
- **되돌리지 않는다.** `data/` 산출물은 줄 수로 비교할 수 없으므로 R259 규약 `ledger_rows` 로
  견준다 — zip 의 것이 로컬 이상일 때만 쓴다. 로컬이 더 큰 원장에서 만든 것이면 남긴다(mtime 이
  아니라 **어느 원장에서 만들었나**가 기준이다).
- 워크플로는 **안 고쳤다** — 복원 단계의 `unzip -o` 가 `data/` 항목을 체크아웃의 `data/` 에 풀고,
  그 뒤 생성 단계가 어차피 다시 만든다. 업로드 단계는 `backup_research_data.py` 를 부르므로
  목록이 늘면 같이 실린다.

## 3. 잠근 것 — §275

DATA_INCLUDE 가 STUDIES 에서 유도됐다(둘이 같다 · 소스에 `study_freshness.STUDIES`) ·
`picked_data` 가 개인 자료·목록 밖을 거른다(심기 양방향) · `unsafe_members` 가 `data/` 를 목록
안에서만 연다(심기 셋) · `extract` 가 `ledger_rows` 로 되돌림을 막는다(심기 둘 · 임시 디렉터리).
값은 잠그지 않는다.

## 4. 남은 것 (정직하게)

- **배포 화면**(Streamlit Cloud)은 여전히 git 의 `data/` 를 읽는다. 이 라운드는 클라우드 → 릴리스
  → 이 PC(`pull_research_data --apply`) 까지의 길이다. 이 PC 에서 git 으로 가는 마지막 한 걸음은
  사람이 커밋한다 — 원장 동봉본(`refresh_bundle.py`)과 같은 규칙이다. 봇이 main 에 커밋하게 하는
  것은 이력·버전 사슬(§7)에 닿는 별개 결정이라 여기서 안 했다.
- 다음 클라우드 실행의 zip 에 `data/` 다섯이 실제로 들어 있는지는 그 실행이 증명한다
  (`unzip -l` · 이 PC 에서 `pull_research_data.py` 미리보기가 목록을 찍는다).
