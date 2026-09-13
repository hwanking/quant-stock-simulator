# -*- coding: utf-8 -*-
"""올라가는 **그 파일**(zip)을 열어 개인 자료가 들었는지 본다 (라운드 281 · §9).

■ 왜
  워크플로의 §9 단계는 이렇게 잰다:

      if ls .portfolio/positions* .portfolio/holdings* ; then 중단 ; fi

  두 가지가 어긋나 있다.
    ① **이름만** 본다 — 다른 이름의 개인 파일은 그냥 지나간다.
    ② **디렉터리**를 본다 — 정작 나가는 것은 zip 이고, 화이트리스트가 무엇을 담았는지는
       안 본다. 라운드 261 이 두 번째 뿌리 `data/` 를 열었는데 이 검사는 그쪽을 아예 안 본다.
  즉 *남아 있는 것*을 재고 *나가는 것*을 안 잰다. R261 의 *"어느 목록이 그것을 고르는지 본다"*
  를 업로드 쪽에서 한 번 더 하는 것이다.

■ 무엇이 개인 자료인가 (§9)
  *"보유종목·평단가·자격증명 커밋 금지"* — 금지의 핵심은 **평단가**(사용자가 산 가격)다.
  수량(`qty`)만으로는 못 가른다: ETF 구성종목 공개 자료에도 설정단위당 주식수가 들어 있다
  (`etf_holdings_r167.json` — `{"name": "TIGER 단기통안채", "weight": null, "qty": 1832.12}`).
  이름으로도 못 가른다: 같은 파일이 이름에 `holdings` 를 달고 있다. **둘 다 오탐했다**
  (라운드 281 실측 · R194 — 판별식이 넓으면 남의 잘못을 부풀린다).
  그래서 판별은 **평단가 칸이 숫자와 함께 있는가**로 한다.

    python scripts/upload_audit.py _archive/research_data_20260912.zip
"""
import io
import os
import re
import sys
import zipfile

#: 사용자가 **산 가격**. 이것이 §9 가 금지하는 그 값이다.
PAID = re.compile(r'"(paid|avg_price|avg_cost|buy_price|purchase_price|평단|매입가)"\s*:\s*'
                  r'(?!null)(?!"")[0-9"]')
#: 자격증명 — 값이 있는 것만 (빈 문자열·null 은 자리만 있는 것)
SECRET = re.compile(r'"(password|passwd|token|secret|api_key|apikey|cookie|session_id)"\s*:\s*'
                    r'"[^"]{4,}"', re.I)
#: 이름이 닮은 것 — **판정하지 않는다.** 몇 개인지만 적어 사람이 읽게 한다.
NAME_LOOKALIKE = re.compile(r'(position|holding|watchlist|portfolio)', re.I)

TEXT_EXT = ('.json', '.jsonl', '.csv', '.txt', '.md', '.yml', '.yaml')
#: 한 항목에서 읽을 최대 바이트. 원장은 수백 MB 라 통째로 읽으면 못 돈다 —
#: 개인 자료는 파일 머리에 스키마가 드러나므로 앞부분으로 충분하고, **얼마를 봤는지 적는다**.
HEAD_BYTES = 2_000_000


def audit(path, head_bytes=HEAD_BYTES):
    """{'scanned', 'skipped_binary', 'paid', 'secret', 'lookalike', 'bytes'}"""
    out = {'scanned': 0, 'skipped_binary': 0, 'paid': [], 'secret': [],
           'lookalike': [], 'bytes': 0}
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            if n.endswith('/'):
                continue
            if NAME_LOOKALIKE.search(os.path.basename(n)):
                out['lookalike'].append(n)
            if not n.lower().endswith(TEXT_EXT):
                out['skipped_binary'] += 1
                continue
            with z.open(n) as fh:
                raw = fh.read(head_bytes)
            out['scanned'] += 1
            out['bytes'] += len(raw)
            txt = raw.decode('utf-8', 'replace')
            m = PAID.search(txt)
            if m:
                out['paid'].append((n, m.group(0)))
            m = SECRET.search(txt)
            if m:
                out['secret'].append((n, m.group(1)))
    return out


def _main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    if len(sys.argv) < 2:
        print('쓰기: python scripts/upload_audit.py <zip>'); return 2
    p = sys.argv[1]
    if not os.path.exists(p):
        print(f'>> 못 쟀다 — {p} 가 없다. 미측정이다.'); return 2
    a = audit(p)
    print(f'{p}')
    print(f'  훑은 텍스트 항목 {a["scanned"]}개 · {a["bytes"]:,}바이트 · '
          f'건너뛴 비텍스트 {a["skipped_binary"]}개')
    print(f'  이름이 닮은 항목 {len(a["lookalike"])}개 — 이름으로 판정하지 않는다:')
    for n in a['lookalike'][:8]:
        print(f'      {n}')
    if a['scanned'] == 0:
        print('>> 실패 — 아무것도 못 훑었다. 0건은 통과가 아니다.')
        return 1
    if a['paid'] or a['secret']:
        print(f'\n>> 실패 — 개인 자료가 들었다 (평단 {len(a["paid"])} · 자격증명 {len(a["secret"])}):')
        for n, w in (a['paid'] + a['secret'])[:10]:
            print(f'      {n} — {w}')
        return 1
    print('\n>> 통과 — 평단가·자격증명 0건 (수량·ETF 구성종목은 공개 자료라 세지 않는다)')
    return 0


if __name__ == '__main__':
    raise SystemExit(_main())
