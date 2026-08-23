# -*- coding: utf-8 -*-
"""OCR 줄 복원 검사를 **자식 프로세스로** 돌리고 결과만 JSON 으로 준다.

■ 왜 (라운드 163)
  회귀 메모리 프로파일에서 §24 가 **+3,058 MB** 로 남은 유일한 큰 봉우리
  였다. easyocr 이 torch 모델을 올리는데, 리더 참조를 끊고 `gc.collect()`
  를 해도 **OS 로 돌아오지 않는다**(torch 의 할당자가 쥐고 있다).
  같은 프로세스 안에서는 못 줄인다 — 프로세스를 나누면 끝날 때 전부
  회수된다. 렌더 검사를 `render_probe.py` 로 옮긴 것과 같은 처방이다.

■ 무엇을 재나 (뜻은 그대로)
  한 줄로 그린 표가 **한 줄로 복원되는가.** 고정 격자(round(y/14))를
  쓰면 중심 104.9 와 105.1 이 다른 줄로 갈라졌던 결함을 지킨다.

    C:/Python314/python.exe scripts/ocr_probe.py
"""
import io
import json
import os
import sys

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
os.chdir(PROJ)


def main():
    out = {'backend': None, 'skipped': True, 'reason': '', 'lines': None,
           'texts': [], 'error': '', 'broken_ok': None}
    try:
        import portfolio as pf
        # 깨진 이미지에 예외를 던지지 않고 사유를 돌려주는가.
        # 이 호출도 ocr_backend() 를 거쳐 easyocr(→torch, 1.5GB)을
        # import 한다 — 그래서 부모가 아니라 여기서 한다.
        _t, _b, _e = pf.extract_text_from_image(b"this-is-not-an-image")
        out['broken_ok'] = bool(_t is None and _e is not None)
        out['broken_err'] = str(_e)[:60]
        out['backend'] = pf.ocr_backend()
        if out['backend'] is None:
            out['reason'] = 'OCR 엔진 미설치'
            return _emit(out)
        from PIL import Image as Im, ImageDraw as Dr, ImageFont as Ft
        f = Ft.truetype(r"C:\Windows\Fonts\malgun.ttf", 30)
        img = Im.new("RGB", (900, 160), "white")
        d = Dr.Draw(img)
        d.text((40, 40), "005930", font=f, fill="black")
        d.text((300, 40), "삼성전자", font=f, fill="black")
        d.text((560, 40), "10", font=f, fill="black")
        d.text((700, 40), "71,200", font=f, fill="black")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        txt, _bk, er = pf.extract_text_from_image(buf.getvalue())
        if er is not None:
            out['reason'] = f'추출 실패: {str(er)[:80]}'
            return _emit(out)
        lines = [l for l in (txt or '').splitlines() if l.strip()]
        out.update(skipped=False, lines=len(lines), texts=lines[:4])
    except Exception as e:                                     # noqa: BLE001
        # 실행 실패는 **검사 실패와 구분**한다 — 부모가 가려서 적는다
        out['reason'] = f'{type(e).__name__}'
        out['error'] = f'{type(e).__name__}: {e}'[:200]
    return _emit(out)


def _emit(out):
    sys.stdout.write('\n@@RESULT@@' + json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.exit(main())
