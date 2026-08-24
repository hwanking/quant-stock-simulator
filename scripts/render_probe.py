# -*- coding: utf-8 -*-
"""렌더 검사 한 건을 **자식 프로세스로** 돌리고 결과만 JSON 으로 돌려준다.

■ 왜 (라운드 163)
  회귀가 이 PC 에서 자주 죽었다 — 종료 코드 127/255, 트레이스백 없음,
  죽는 지점이 매번 달랐다. 진단에서 `0xC000012D`
  (STATUS_COMMITMENT_LIMIT · 커밋 한도 초과)를 봤다.

  `scripts/profile_regression.py` 로 절 단위 봉우리를 재니 **7,065 MB**
  였고, 해제 지점을 넣어도 **5,230 MB** 에서 죽었다. 원인이 누적이
  아니라 **단발 봉우리**였기 때문이다 — AppTest 가 한 번 돌 때마다 앱
  전체(원장 18만 건 포함)를 올려 2.2GB 를 쓰고, OCR 의 torch 모델은
  놓아 줘도 OS 로 안 돌아온다.

  같은 프로세스 안에서는 이걸 못 줄인다. **프로세스를 나누면** 끝날 때
  OS 가 전부 회수한다. 그래서 렌더 한 건을 여기서 따로 돌린다.

■ 무엇을 돌려주나
  검사가 실제로 쓰는 것만 — 예외 개수·첫 예외 문구·요청한 세션 키의
  존재 여부. 검사의 **뜻은 하나도 바꾸지 않는다.**

    C:/Python314/python.exe scripts/render_probe.py --ticker 069500
    C:/Python314/python.exe scripts/render_probe.py --sb-step setup \
        --state-json "{\"_sb_keep\": {\"rho\": 0.9}}" --want-key _sb_keep
"""
import argparse
import io
import json
import os
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# AppTest 가 web_app.py 를 exec 할 때 프로젝트 모듈을 찾아야 한다.
# 부모 회귀는 PROJ 에서 돌아 경로가 이미 있지만 자식은 없다 —
# 넣지 않으면 'No module named bitemporal_engine' 으로 **렌더가 아니라
# 경로 때문에** 실패한다(실제로 그렇게 한 번 나왔다).
sys.path.insert(0, PROJ)
os.chdir(PROJ)

# ⚠️ 라운드 165 — 검사가 **사용자 자료를 바꾸고 있었다.** 라운드 164 가
#   '최근 본 종목'을 파일에 남기게 했는데, 이 프로브가 돌 때마다 테스트
#   종목(SK하이닉스·다날·CJ ENM …)이 사용자 목록에 쌓였다.
#   화면은 이 값을 보면 **로컬 파일을 쓰지 않는다** (읽기는 그대로 —
#   검사는 실제 자료 위에서 돌아야 화면이 진짜로 그리는지 알 수 있다).
#   os.environ 에 여기서 넣어야 AppTest 가 exec 하는 web_app 이 본다.
os.environ['GAEUM_NO_LOCAL_WRITE'] = '1'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ticker')
    ap.add_argument('--sb-step')
    ap.add_argument('--search')
    ap.add_argument('--state-json', default='')
    ap.add_argument('--want-key', action='append', default=[])
    ap.add_argument('--timeout', type=int, default=1800)
    a = ap.parse_args()

    # ⚠️ 라운드 165 — 렌더가 **사용자 자료를 바꾸는지** 여기서 잰다.
    #
    # ⚠️ 라운드 170 — 처음엔 **파일 수정시각**으로 쟀다. 그랬더니 회귀가
    #   실패했는데 원인이 렌더가 아니라 **사용자가 열어 둔 streamlit
    #   서버**였다 (서버를 끄고 다시 재니 0건). 검사가 잰 것(파일이
    #   바뀌었다)은 맞았지만 **원인 지목이 틀렸다** — 남의 프로세스를
    #   우리 탓으로 적었다.
    #   그래서 **우리 코드가 저장 함수를 불렀는지**를 직접 센다.
    #   파일 상태가 아니라 **우리 행동**을 재는 것이라 남의 프로세스에
    #   흔들리지 않는다.
    _calls = []
    try:
        import portfolio as _pf
        for _fn in ('save_watchlist', 'save_search_history', 'save_positions'):
            _orig = getattr(_pf, _fn, None)
            if not callable(_orig):
                continue

            def _wrap(name, fn):
                def _inner(*a, **k):
                    _calls.append(name)
                    return fn(*a, **k)
                return _inner
            setattr(_pf, _fn, _wrap(_fn, _orig))
    except Exception:                                          # noqa: BLE001
        _calls = None                   # 못 걸었으면 '못 쟀다'로 둔다 (§3)

    out = {'ok': False, 'exceptions': None, 'first': '', 'keys': {},
           'error': '', 'touched': None}
    try:
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(os.path.join(PROJ, 'web_app.py'),
                               default_timeout=a.timeout)
        if a.ticker:
            at.session_state['selected_ticker'] = a.ticker
        if a.sb_step is not None:
            at.session_state['sb_step'] = a.sb_step
        if a.search:
            at.session_state['search_text_input'] = a.search
        if a.state_json:
            for k, v in json.loads(a.state_json).items():
                at.session_state[k] = v
        at.run()
        out['exceptions'] = len(at.exception)
        out['first'] = str(at.exception[:1])[:300] if at.exception else ''
        out['keys'] = {k: (k in at.session_state) for k in a.want_key}
        out['ok'] = True
    except Exception as e:                                     # noqa: BLE001
        # 자식이 죽으면 부모가 그것을 **검사 실패가 아니라 실행 실패**로
        # 구분할 수 있어야 한다. 지어내지 않는다(§3).
        out['error'] = f'{type(e).__name__}: {e}'[:300]
    # 우리 코드가 부른 저장 함수 이름들. 계측을 못 걸었으면 None 이다 —
    # '안 불렀다'와 '못 쟀다'를 가른다 (§3).
    out['touched'] = (sorted(set(_calls)) if _calls is not None else None)
    sys.stdout.write('\n@@RESULT@@' + json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.exit(main())
