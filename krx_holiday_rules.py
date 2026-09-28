# -*- coding: utf-8 -*-
"""휴장일을 **법의 규칙으로 다시 유도**해 엔진의 표와 대 본다 (라운드 376 · 2026-09-28).

■ 왜 있나
  2026-09-28(월)이 엔진 표(`bitemporal_engine.KRX_HOLIDAYS`)에 휴장으로 들어가 있었고 그날 장이 열렸다
  (사용자: "나 출근했는데"). 표를 만들 때 공개 자료를 옮겨 적으며 **대체공휴일 규칙을 추석에 잘못 적용**했다 —
  설·추석은 **일요일**이나 다른 공휴일과 겹칠 때만 대체가 생기는데 토요일 겹침을 대체로 읽었다. 같은 날
  2027 노동절 대체(5/3)가 **빠져** 있던 것도 나왔다. 둘 다 "사람이 규칙을 머리로 적용해 날짜를 옮겨 적는" 자리의
  실수다. 지나간 날은 일봉 대조(`scripts/calendar_truth.py`)가 잡지만 **미래 날짜는 봉이 없어 못 잡는다.**
  그래서 규칙을 코드로 적고, 규칙이 낸 날짜와 표를 **날짜마다 사유와 함께** 대 본다 — 미래 항목도 지금 걸린다.

■ 규칙 (공휴일에 관한 법률 · 2026 기준 · 대체공휴일은 '다음 첫 비공휴일 평일')
  · 신정 1/1 · 현충일 6/6                                      — 대체 없음
  · 3·1절 · 광복절 · 개천절 · 한글날 (국경일)                   — 토·일 겹치면 대체 (2021-08 부터)
  · 제헌절 7/17 (국경일 · 2026 공휴일 재지정)                  — 2026 부터 휴장 · 토·일 겹치면 대체
  · 어린이날 5/5                                                — 토·일·다른 공휴일 겹치면 대체
  · 부처님오신날(음 4/8) · 기독탄신일 12/25                     — 토·일 겹치면 대체 (2023-05 부터)
  · 설날·추석 연휴(당일 ±1일)                                   — **일요일**·다른 공휴일과 겹칠 때만 대체
                                                                   (토요일 겹침은 대체가 아니다 — 이번 사고)
  · 노동절 5/1                                                  — 늘 휴장 · 2026 부터 공휴일이라 토·일 겹치면 대체
  · 선거일·임시공휴일                                           — 규칙으로 못 낸다 → `AD_HOC` 에 출처와 함께
  · KRX 연말 휴장 12/31                                         — 거래소 규정 (그날이 주말이면 표에 없음)

■ 안 하는 것
  · 음력 환산을 계산하지 않는다 — 설날·추석·부처님오신날의 양력 날짜는 `LUNAR` 표로 둔다(연 3개 · 공개 자료).
    이것은 **엔진 표와 독립**이고 틀린 규칙 적용을 잡는 데는 충분하다(오늘의 두 결함은 둘 다 규칙 쪽이었다).
    지나간 해는 일봉 대조가 음력 날짜까지 같이 확인한다.
  · 표를 고치지 않는다. 판정만 한다 — 표를 고치는 것은 사람이 이유와 함께 한다.
"""
import datetime as _dt

#: 음력 명절의 양력 날짜 — 설날(음 1/1) · 추석(음 8/15) · 부처님오신날(음 4/8). 공개 자료(월력요항) 기준.
#:   2025·2026 은 그날의 실제 휴장(일봉 없음)으로도 확인됐다(라운드 375 대조기).
LUNAR = {
    2025: {'seollal': '2025-01-29', 'chuseok': '2025-10-06', 'buddha': '2025-05-05'},
    2026: {'seollal': '2026-02-17', 'chuseok': '2026-09-25', 'buddha': '2026-05-24'},
    2027: {'seollal': '2027-02-07', 'chuseok': '2027-09-15', 'buddha': '2027-05-13'},
}

#: 규칙으로 못 내는 휴장 — 날짜: 사유. 넣을 때는 출처를 주석으로 단다.
AD_HOC = {
    '2025-01-27': '임시공휴일 (정부 지정 · 설 연휴 앞)',
    '2025-06-03': '제21대 대통령 선거일',
    '2026-06-03': '제9회 전국동시지방선거일',
}

_KO_WD = '월화수목금토일'


def _d(s):
    return _dt.date.fromisoformat(s)


def expected_closed(year):
    """그 해 규칙이 낸 휴장일 {ISO 날짜: 사유}. 주말에 떨어지는 공휴일도 사유와 함께 담는다(표가 적어 둘 수 있다).
    `LUNAR` 에 그 해가 없으면 None — 모르는 해를 지어내지 않는다."""
    lun = LUNAR.get(year)
    if lun is None:
        return None
    hol = {}                   # date → 사유
    sub_kind = {}              # date → 'weekend'(토·일 대체) | 'sunday'(일요일만 대체) | None

    def put(day, why, kind):
        s = day.isoformat()
        hol[s] = (hol[s] + ' · ' + why) if s in hol else why
        # 같은 날 둘이 겹치면(2025-05-05 어린이날+부처님오신날) 대체 성질은 더 넓은 쪽
        prev = sub_kind.get(s)
        sub_kind[s] = 'weekend' if 'weekend' in (prev, kind) else (prev or kind)

    Y = year
    put(_dt.date(Y, 1, 1), '신정', None)
    put(_dt.date(Y, 3, 1), '3·1절', 'weekend')
    put(_dt.date(Y, 5, 1), '노동절' if Y >= 2026 else '근로자의 날', 'weekend' if Y >= 2026 else None)
    put(_dt.date(Y, 5, 5), '어린이날', 'weekend')
    put(_dt.date(Y, 6, 6), '현충일', None)
    if Y >= 2026:
        put(_dt.date(Y, 7, 17), '제헌절', 'weekend')
    put(_dt.date(Y, 8, 15), '광복절', 'weekend')
    put(_dt.date(Y, 10, 3), '개천절', 'weekend')
    put(_dt.date(Y, 10, 9), '한글날', 'weekend')
    put(_dt.date(Y, 12, 25), '기독탄신일', 'weekend')
    put(_d(lun['buddha']), '부처님오신날', 'weekend')
    blocks = []
    for key, name in (('seollal', '설날'), ('chuseok', '추석')):
        c = _d(lun[key])
        days = [c - _dt.timedelta(days=1), c, c + _dt.timedelta(days=1)]
        for i, day in enumerate(days):
            put(day, name + (' 연휴' if i != 1 else ''), 'sunday')
        blocks.append((name, days))
    for s, why in AD_HOC.items():
        if s.startswith(str(Y)):
            put(_d(s), why, None)
    dec31 = _dt.date(Y, 12, 31)
    if dec31.weekday() < 5:
        put(dec31, 'KRX 연말 휴장', None)

    # 대체공휴일 — 날짜 순으로, 겹침 판정 → 다음 첫 '주말도 공휴일도 아닌 날'
    base = dict(hol)
    subs = []
    handled_blocks = set()
    for s in sorted(base):
        day = _d(s)
        kind = sub_kind.get(s)
        if kind is None:
            continue
        # 설·추석은 연휴 **묶음**으로 본다 — 묶음 안에 일요일이나 다른 공휴일 겹침이 있으면 묶음 뒤에 하나씩
        blk = next(((n, ds) for n, ds in blocks if day in ds), None)
        if blk is not None:
            if blk[0] in handled_blocks:
                continue
            handled_blocks.add(blk[0])
            n_over = 0
            for bd in blk[1]:
                others = [w for w in base[bd.isoformat()].split(' · ') if not w.startswith(blk[0])]
                if bd.weekday() == 6 or others:        # 일요일 · 다른 공휴일 (토요일은 세지 않는다)
                    n_over += 1
            anchor = blk[1][-1]
            for _ in range(n_over):
                subs.append((anchor, blk[0] + ' 대체공휴일'))
            continue
        why = base[s]
        over = day.weekday() >= 5 or ' · ' in why          # 토·일 또는 같은 날 두 공휴일
        if kind == 'weekend' and over:
            subs.append((day, why.split(' · ')[0] + ' 대체공휴일'))
    for anchor, why in sorted(subs):
        nxt = anchor + _dt.timedelta(days=1)
        while nxt.weekday() >= 5 or nxt.isoformat() in hol:
            nxt += _dt.timedelta(days=1)
        hol[nxt.isoformat()] = why
    return hol


def audit(table=None, years=None):
    """엔진 표와 규칙을 날짜마다 대 본다. 평일만 판정한다(주말은 표에 있든 없든 휴장이다).

    반환 dict:
      rows      — [{date, wd, in_table, reason, status}] (표 ∪ 규칙의 평일 · 날짜 순)
      mismatch  — status 가 '일치' 가 아닌 행
      years     — 대 본 해 · no_rule_years — `LUNAR` 가 없어 못 댄 해(표에는 있다)
    status: '일치' · '표에만 있음 — 규칙에 없는 휴장' · '규칙상 휴장인데 표에 없음'
    """
    if table is None:
        import bitemporal_engine as _be
        table = _be.KRX_HOLIDAYS
    table = set(table)
    t_years = sorted({int(s[:4]) for s in table})
    years = sorted(years or t_years)
    rows, no_rule = [], []
    for y in years:
        exp = expected_closed(y)
        if exp is None:
            no_rule.append(y)
            continue
        days = {s for s in table if s.startswith(str(y))} | set(exp)
        for s in sorted(days):
            day = _d(s)
            if day.weekday() >= 5:
                continue
            in_t, in_e = s in table, s in exp
            status = ('일치' if in_t == in_e else
                      '표에만 있음 — 규칙에 없는 휴장' if in_t else '규칙상 휴장인데 표에 없음')
            rows.append({'date': s, 'wd': _KO_WD[day.weekday()], 'in_table': in_t,
                         'reason': exp.get(s) or '', 'status': status})
    return {'rows': rows, 'mismatch': [r for r in rows if r['status'] != '일치'],
            'years': [y for y in years if y not in no_rule], 'no_rule_years': no_rule}


def upcoming(today=None, n=8, table=None):
    """오늘 이후 평일 휴장 n 개 — 화면용. 각 행에 규칙 판정을 붙인다."""
    today = today or _dt.date.today()
    res = audit(table=table)
    return [r for r in res['rows'] if r['date'] >= today.isoformat() and r['in_table']][:n], res
