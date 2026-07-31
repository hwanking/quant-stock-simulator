# 퀀트 주식 시뮬레이터

코스피·코스닥 종목의 자기유사 패턴 백테스트, 표본외(Blind/OOS) 검증, 밸류에이션,
보유종목 개인화 판정을 하나의 스냅샷으로 계산하는 Streamlit 앱입니다.

**투자 권유가 아닙니다.** 네이버증권·다음금융의 공개 웹 데이터에 기초한 참고용이며,
투자 판단과 손익의 최종 책임은 투자자 본인에게 있습니다.

---

## 로컬 실행

```bash
pip install -r requirements.txt
streamlit run web_app.py
```

스크린샷 인식(OCR)을 쓰려면 로컬에서만 추가로 설치합니다.

```bash
pip install easyocr
```

---

## 클라우드 배포 (Streamlit Community Cloud)

### 1. GitHub 저장소 만들기

이 폴더에서:

```bash
git init
```

```bash
git add .
```

```bash
git commit -m "퀀트 주식 시뮬레이터 초기 배포"
```

GitHub에서 새 저장소를 만든 뒤(예: `quant-stock-sim`), 원격을 연결합니다.

```bash
git remote add origin https://github.com/<사용자명>/<저장소명>.git
```

```bash
git push -u origin main
```

### 2. Streamlit Cloud 연결

1. <https://share.streamlit.io> 접속 → GitHub 계정으로 로그인
2. **Create app** → 방금 만든 저장소 선택
3. Branch: `main` (또는 `master`) · Main file path: `web_app.py`
4. **Advanced settings → Secrets** 에 비밀번호를 넣습니다 (필수 — 없으면 앱이 열리지 않습니다)

   ```toml
   app_password = "본인만아는긴비밀번호"
   ```

5. **Deploy** 클릭

### 3. 코드를 고친 뒤 반영하기

```bash
git add -A
```

```bash
git commit -m "수정 내용"
```

```bash
git push
```

푸시하면 Streamlit Cloud가 자동으로 다시 배포합니다.

---

## ⚠️ 배포 전에 반드시 알아야 할 것

### 비밀번호를 설정해야 앱이 열립니다 (fail-closed)

이 앱에는 보유종목·평균매수가가 들어 있습니다. 그래서 **외부 접속인데 비밀번호가
설정돼 있지 않으면 화면 자체를 열어주지 않습니다.** 실수로 공개 배포되는 것을 막기 위해서입니다.

배포할 때 Streamlit Cloud 의 **Advanced settings → Secrets**(또는 배포 후
Settings → Secrets)에 한 줄을 넣으세요.

```toml
app_password = "본인만아는긴비밀번호"
```

| 상황 | 동작 |
|---|---|
| 로컬 실행 (`localhost`) | 비밀번호 없이 바로 사용 |
| 외부 접속 + 비밀번호 미설정 | **차단** — 설정 안내만 표시 |
| 외부 접속 + 비밀번호 설정 | 잠금 화면 → 통과해야 진입 |
| 비밀번호 틀림 | 계속 잠김 |

`secrets.toml` 파일을 저장소에 커밋하면 안 됩니다. `.gitignore` 가 이미 막고 있습니다.

### 외부 접속에서는 보유종목이 세션에만 유지됩니다

앱 인스턴스가 하나라서 `.portfolio/positions.json` 에 저장하면 **방문자 전원의 공용
파일**이 됩니다 — 한 사람이 저장하면 다른 사람 화면에 나타납니다. 그래서 외부 접속일
때는 서버 파일 저장·불러오기를 아예 끄고, 보유종목을 **브라우저 세션에만** 둡니다.

탭을 닫거나 앱이 재시작되면 사라지므로, 보관하려면 **저장·삭제 탭 → CSV 내보내기**로
받아 두었다가 다음에 '가져오기 / 입력' 탭에서 다시 올리세요.

로컬 실행에서는 예전처럼 `.portfolio/positions.json` 에 저장됩니다.

### 커밋되지 않는 파일

`.gitignore` 가 다음을 제외합니다. 개인 자료가 공개 저장소로 올라가는 것을 막습니다.

| 경로 | 이유 |
|---|---|
| `.portfolio/` | 보유종목·평균매수가 |
| `.streamlit/credentials.toml`, `secrets.toml` | 자격증명 |
| `.claude/` | 로컬 실행 설정 |
| `_archive/`, `__pycache__/` | 개발 잔여물 |

### 클라우드에서 달라지는 기능

| 기능 | 로컬 | 클라우드 |
|---|---|---|
| 스크린샷 OCR | easyocr 설치 시 동작 | **동작 안 함** (메모리 한계로 torch 미설치) |
| 클립보드 붙여넣기 | 동작 | **숨김** (서버 PC 클립보드를 읽게 되므로) |
| 이미지 파일 올리기 | 동작 | 업로드는 되지만 OCR 엔진이 없어 인식 불가 |
| 표 붙여넣기 · CSV 가져오기 | 동작 | **동작** — 클라우드의 기본 입력 경로 |
| 시세·재무·지수 조회 | 동작 | 동작 |

클라우드에서 보유종목을 넣는 가장 정확한 방법은 **CSV 가져오기**, 그다음이 **표 붙여넣기**입니다.

---

## 검증

수정 후에는 회귀 스위트를 돌리세요. 35개 섹션 366건의 불변식 검사입니다.

```bash
python test_pipeline_fixes.py
```

네트워크(네이버·다음)가 필요하며, 실패한 검사는 `[FAIL]` 로 표시되고 종료코드 1을 반환합니다.
