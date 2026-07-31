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
2. **New app** → 방금 만든 저장소 선택
3. Main file path 에 `web_app.py` 입력
4. **Deploy** 클릭

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

### 보유종목은 인증 없이 공개됩니다

현재 설정에서는 **URL을 아는 누구나** 화면에 접근할 수 있고, 여기에는
보유종목·평균매수가가 포함됩니다. 또한 앱 인스턴스가 하나이므로
**방문자 전원이 같은 저장본을 공유**합니다 — 한 사람이 저장하면 다른 사람이 봅니다.

비밀번호를 걸려면 Streamlit Cloud 에서 **Settings → Secrets** 에 한 줄만 넣으면 됩니다.

```toml
app_password = "원하는비밀번호"
```

값이 있으면 즉시 인증 화면이 뜨고, 없으면 지금처럼 공개됩니다.
코드 수정은 필요 없습니다.

### 저장본은 영구적이지 않습니다

클라우드 컨테이너의 파일은 재배포·재시작 시 사라집니다. 보유종목을 오래 보관하려면
**저장·삭제 탭 → CSV 내보내기**로 손에 들고 계세요.

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
