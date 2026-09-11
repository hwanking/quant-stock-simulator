# -*- coding: utf-8 -*-
"""화면의 "못 냈다" 표현에 사유가 붙어 있나 — 판별식 **한 곳** (라운드 274 · PLAN_R177 §5.1).

■ 왜
  라운드 177 이 렌더한 화면을 훑어 `판정 불가`·`미수신`·`산출 불가` 14곳에 **사유가 0%** 임을 셌고
  *"이 비율을 회귀가 센다"* 고 적었다(§5.1). 그 뒤 15일 동안 회귀에 관련 검사가 0건이었다(전수조사
  #67). 판별식은 R177 의 프로브(`_probe/unavailable_census_r177.py`)에만 있었다 — 검사와 도구가 같은
  판별식을 베끼면 한쪽이 낡는다(R192). 여기 한 곳에 두고 둘 다 부른다.

■ 무엇을 재나
  `audit_text(txt)` — 렌더된 화면 글자에서 MARK 낱말을 찾고, 낱말 뒤 90자 안에 사유 표식
  (`—` · `(` · `·` · `:` 로 이어지는 글 · '때문')이 있으면 '사유 있음'. R177 의 판별식 그대로(값을
  잠그는 것이 아니라 판별식을 옮긴 것). CORE 세 낱말이 §5.1 의 대상이다.

    C:/Python314/python.exe scripts/unavailable_audit.py --ticker 000720
"""
import collections
import re

#: 화면이 "못 냈다"고 말하는 표현들 (R177)
#:   라운드 274 — '미수신 입력 : 없음' 의 '미수신' 은 라벨(무엇이 안 왔나를 세는 칸의 이름)이지
#:   상태값이 아니다. 첫 실측(000720 · 15곳 중 13곳 '사유 없음')에서 그 라벨과 업데이트 내역에
#:   렌더된 커밋 문장이 절반을 차지했다 — 판별식이 넓으면 남의 잘못을 부풀린다(R194). 라벨은 뺀다.
#:   그리고 낱말이 **문장 속 명사**로 쓰인 자리("미수신 동안은 … 작동합니다" · "미수신이다")는 상태값이
#:   아니다 — 조사·'동안'·'이면' 처럼 문장으로 이어지는 쓰임은 구조로 뺀다(산문 판단이 아니라 어미 규칙).
_PROSE = r'(?![이은는을를]|\s*(?:동안|이면|일 때|인 경우|이라|으로))'
MARK = re.compile(
    r'(미산출' + _PROSE + r'|미선정' + _PROSE + r'|미수신(?! 입력)' + _PROSE + r'|미연동' + _PROSE
    + r'|산출 불가' + _PROSE + r'|판정 불가' + _PROSE + r'|판정 보류' + _PROSE + r'|미측정' + _PROSE
    + r'|표본 없음|미공시|미기재|자료 없음|계산 불가|없음\b)')

#: PLAN_R177 §5.1 이 사유를 요구하는 세 낱말 (14곳 · 사유 0% 였다)
CORE = ('판정 불가', '미수신', '산출 불가')

#: 뒤쪽 사유 — '—' '(' '·' ':' 로 이어지는 글. 라운드 274 — 마크다운 표에서는 **다음 칸**(`|`)이 사유다
#: (고객센터 FAQ: "지수·시세 미수신 경고 | 네이버·다음 응답 지연 | …").
_REASON_TAIL = re.compile(r'\s*[—(·:|]\s*[^\s—(·:|]')     # 구분자 뒤에 **글자**가 와야 사유다 (빈 칸 `| |` 는 아니다)
#: 업데이트 내역 카드(커밋 문장을 그대로 렌더한다 · `gen_update_history`)는 화면의 상태값이 아니라
#: 역사 산문이다 — "시총 1위 미수신" 같은 낱말이 그 안에 있어도 오늘 화면이 못 낸 값이 아니다.
#: 그 카드에만 있는 라벨로 덩어리째 뺀다(첫 실측에서 핵심 낱말 '사유 없음' 6곳 중 4곳이 이것이었다).
#: 카드는 라벨마다 한 덩어리(`<span>라벨</span><br><span>본문</span>`)라 원문 모양으로 정확히 맞춘다.
HISTORY_MARKERS = ('>변경 전 문제</span><br>', '>변경 이유</span><br>',
                   '>사용자에게 달라지는 점</span><br>', '>테스트 결과</span><br>',
                   # 업데이트 목록의 제목 행(날짜 · 분류 · 커밋 제목) — 카드 밖의 같은 산문
                   "width:78px; flex:0 0 auto; font-variant-numeric:tabular-nums;'>")
#: 같은 줄 **앞쪽**의 사유 — "미산출 — 보유 구성 미입력 — 팩터 노출도 산출 불가" 처럼 사유가 먼저
#: 오는 문장. ':'·'(' 는 앞에서는 라벨 구분자일 뿐이라(예: "진입 위치: 판정 불가") 세지 않는다.
_REASON_HEAD = re.compile(r'(—|때문)')


def clean_render_text(parts, skip_history=True):
    """AppTest 의 markdown·caption 값 목록 → 태그·CSS 를 걷어낸 한 덩어리 글자.
    skip_history: 업데이트 내역 카드(HISTORY_MARKERS 가 든 덩어리)는 뺀다 — 몇 개를 뺐는지는
    `clean_render_text.skipped` 에 남긴다(0 인지 못 봤는지를 가르기 위해)."""
    kept, skipped = [], 0
    for p in parts:
        s = str(p or '')
        if skip_history and any(m in s for m in HISTORY_MARKERS):
            skipped += 1
            continue
        kept.append(s)
    clean_render_text.skipped = skipped
    txt = '\n'.join(kept)
    txt = re.sub(r'<[^>]+>', ' ', txt)
    txt = re.sub(r'/\*.*?\*/', ' ', txt, flags=re.S)
    txt = re.sub(r'\{[^{}]*:[^{}]*\}', ' ', txt)
    return re.sub(r'[ \t]+', ' ', txt)


def has_reason(txt, end, start=None):
    tail = txt[end:end + 90]
    if bool(_REASON_TAIL.match(tail)) or '때문' in tail:
        return True
    if start is None:
        return False
    line_start = txt.rfind('\n', 0, start) + 1
    line_end = txt.find('\n', end)
    line = txt[line_start:(line_end if line_end >= 0 else len(txt))]
    # 마크다운 표의 행이면 낱말이 든 **칸의 다음 칸**이 사유다 ("지수·시세 미수신 경고 | 네이버·다음 응답 지연")
    if line.count('|') >= 2:
        cell_end = txt.find('|', end)
        if 0 <= cell_end < (line_end if line_end >= 0 else len(txt)):
            nxt = txt[cell_end + 1:cell_end + 60].split('|', 1)[0].strip()
            if nxt:
                return True
    head = txt[max(0, start - 120):start]
    head = head.rsplit('\n', 1)[-1]                 # 같은 줄 안에서만
    return bool(_REASON_HEAD.search(head))


def audit_text(txt, sample_chars=60, max_samples=6):
    """{낱말: {'n', 'with_reason', 'without': [주변 글자…]}} · 'scanned' = 찾은 표현 수."""
    out = {}
    for m in MARK.finditer(txt):
        w = m.group(1)
        d = out.setdefault(w, {'n': 0, 'with_reason': 0, 'without': [], 'with': []})
        d['n'] += 1
        seg = txt[max(0, m.start() - sample_chars):m.end() + sample_chars].replace('\n', ' ').strip()
        if has_reason(txt, m.end(), m.start()):
            d['with_reason'] += 1
            if len(d['with']) < max_samples:
                d['with'].append(seg)
        elif len(d['without']) < max_samples:
            d['without'].append(seg)
    out['scanned'] = sum(v['n'] for k, v in out.items() if k != 'scanned')
    return out


def core_summary(audit):
    """CORE 세 낱말의 (곳, 사유 있음, 사유 없음)."""
    n = sum((audit.get(w) or {}).get('n', 0) for w in CORE)
    yes = sum((audit.get(w) or {}).get('with_reason', 0) for w in CORE)
    return n, yes, n - yes


def _main():
    import argparse
    import io
    import os
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    proj = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, proj)
    os.chdir(proj)
    os.environ['GAEUM_NO_LOCAL_WRITE'] = '1'
    ap = argparse.ArgumentParser()
    ap.add_argument('--ticker', default='000720')
    a = ap.parse_args()
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(os.path.join(proj, 'web_app.py'), default_timeout=1800)
    at.session_state['selected_ticker'] = a.ticker
    at.run()
    print(f'■ {a.ticker} · 예외 {len(at.exception)}건')
    txt = clean_render_text([getattr(m, 'value', '') for m in at.markdown]
                            + [getattr(c, 'value', '') for c in at.caption])
    au = audit_text(txt)
    print(f'■ "못 냈다" 표현 {au["scanned"]}곳 · 업데이트 내역 카드 {clean_render_text.skipped}덩어리 제외')
    for w, d in sorted(((k, v) for k, v in au.items() if k != 'scanned'), key=lambda kv: -kv[1]['n']):
        print(f'   {d["n"]:>4}  {w:<8}  사유 붙은 것 {d["with_reason"]}/{d["n"]}')
    n, yes, no = core_summary(au)
    print(f'■ 핵심 세 낱말 {n}곳 · 사유 {yes} · 사유 없음 {no}')
    for w in CORE:
        for seg in (au.get(w) or {}).get('without', []):
            print(f'   [{w}] … {seg[:140]} …')
    print('■ 핵심 세 낱말 — 사유 있는 자리 (분류표 재료)')
    for w in CORE:
        for seg in (au.get(w) or {}).get('with', []):
            print(f'   [{w}] … {seg[:160]} …')
    return 0


if __name__ == '__main__':
    raise SystemExit(_main())
