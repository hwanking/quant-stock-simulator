# -*- coding: utf-8 -*-
"""라운드 87 — 실행 환경이 엔진의 **가정**을 만족하는가. 아니면 즉시 멈춘다.

■ 왜 있는가 — 두 번 데였다
  · 라운드 81: 복원이 어제 스냅샷을 집어 축적이 하루도 안 쌓였다
  · 라운드 86: 러너 시계가 UTC 라 기준일이 매일 어제였고, 중복 방지에
    걸려 전방 기록이 171 에서 멎었다

  둘 다 전 단계 success 였고 가드도 통과했다. 신호(증분 +0)는 찍히고
  있었는데 **아무도 안 읽었다.** 찍는 것과 읽는 것은 다른 일이다.

■ 그래서 **먼저** 죽는다
  이 검사는 축적 앞에 둔다. 환경이 틀렸으면 100분을 태우기 전에 멈추고,
  아직 아무것도 안 쌓았으므로 잃는 것이 없다.

■ 무엇을 보나 — 엔진이 조용히 기대는 것들
  ① 시계가 KST 인가 (resolve_analysis_date 는 now() 가 KST 라고 가정한다)
  ② 기준일이 달력상 최근 거래일과 같은가
  ③ 올해·내년 휴장일 표가 있는가 (없으면 공휴일을 거래일로 센다)
  ④ 표준출력이 UTF-8 인가 (한글 로그가 깨지면 사고를 못 읽는다)

    C:/Python314/python.exe scripts/env_check.py
"""
import datetime as dt
import io
import os
import sys
import warnings

warnings.filterwarnings('ignore')
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

#: 한국 표준시 — 엔진 명세 §3 이 전제하는 시간대
KST_OFFSET_HOURS = 9


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def checks():
    """(이름, 통과, 설명) 목록. 지어내지 않고 실제 값을 담는다."""
    import bitemporal_engine as be
    out = []

    # ① 시계가 KST 인가 — UTC 와의 차이를 실제로 잰다
    now = dt.datetime.now()
    utc = dt.datetime.utcnow()
    off = round((now - utc).total_seconds() / 3600.0)
    out.append((
        '시계가 KST(UTC+9)인가', off == KST_OFFSET_HOURS,
        f'now={now:%Y-%m-%d %H:%M} · utc={utc:%H:%M} · 차이 {off:+d}시간'
        + ('' if off == KST_OFFSET_HOURS else
           '  ← 워크플로에 TZ: Asia/Seoul 를 넣는다 (라운드 86)')))

    # ② 기준일이 달력상 최근 거래일과 같은가
    cal = be.KrxCalendar()
    today = now.date()
    latest = today if cal.is_trading_day(today) else \
        cal.previous_trading_day(today)
    t_ref = be.resolve_analysis_date()
    # ⚠️ 장이 아직 안 끝났으면 직전 거래일이 **정상**이다 (명세 §3).
    #   처음에 장중만 예외로 뒀다가 자정 직후(00:00)에 오탐이 났다 —
    #   그때도 '장 시작 전'이라 직전 거래일이 맞다. 개장 전·장중을
    #   같이 본다: 오늘이 거래일이고 15:30 전이면 뒤처진 게 정상이다.
    before_close = (cal.is_trading_day(today)
                    and now.time() < dt.time(15, 30))
    okd = (t_ref == latest) or (before_close and t_ref < latest)
    out.append((
        '기준일이 최근 거래일과 맞는가', okd,
        f'기준일 {t_ref} · 달력상 최근 거래일 {latest} · '
        f'지금 {now:%H:%M}'
        + ('  (장 마감 전이라 직전 거래일이 정상)'
           if before_close and t_ref < latest
           else '' if okd else
           '  ← 뒤처졌다. 시계를 확인한다 (라운드 86)')))

    # ③ 휴장일 표가 **실제로 필요한 해**를 덮는가
    #   ⚠️ '올해와 내년'으로 잡았다가 2027 미등록으로 매번 실패했다.
    #   아직 해롭지 않은 조건으로 파이프라인을 막는 것은 신호가 아니라
    #   소음이다. 필요한 해만 요구한다 — 오늘 연도와, 우리가 날짜를
    #   계산해야 하는 해(전방 재평가일). 그 밖의 미등록 연도는 막지 않고
    #   **알리기만** 한다.
    yrs = set(be.KRX_HOLIDAY_YEARS)
    need = {today.year}
    try:
        import forward_eval as _fe
        d = _fe.eval_date()
        if d:
            need.add(int(str(d)[:4]))
    except Exception:                                          # noqa: BLE001
        pass
    miss = sorted(need - yrs)
    out.append((
        '휴장일 표가 필요한 해를 덮는가', not miss,
        f'등록 {min(yrs)}~{max(yrs)} · 필요 {sorted(need)}'
        + ('' if not miss else
           f'  ← {miss} 미등록. 없는 해는 공휴일을 거래일로 센다')))

    # ③b 다가오는 해 — 막지 않고 알린다 (지어내서 채우지 않는다)
    nxt = today.year + 1
    out.append((
        f'{nxt}년 휴장일 (참고 · 막지 않음)', True,
        (f'{nxt} 등록됨' if nxt in yrs else
         f'{nxt} 미등록 — {nxt}-01-01 전에 KRX 공고로 채워야 한다. '
         f'그때까지는 그 해 공휴일을 거래일로 센다')))

    # ④ 표준출력이 UTF-8 인가
    enc = (getattr(sys.stdout, 'encoding', '') or '').lower().replace('-', '')
    out.append((
        '표준출력이 UTF-8 인가', enc.startswith('utf8'),
        f'encoding={getattr(sys.stdout, "encoding", None)}'))
    return out


def main():
    rows = checks()
    print('■ 실행 환경 점검 (라운드 87) — 축적 앞에서 먼저 본다')
    bad = 0
    for name, ok, detail in rows:
        print(f'  [{"OK" if ok else "실패"}] {name}')
        print(f'        {detail}')
        if not ok:
            bad += 1
    if bad:
        print(f'\n환경이 엔진의 가정을 만족하지 않는다 ({bad}건). '
              f'여기서 멈춘다 — 100분을 태우고 조용히 0건을 쌓느니 '
              f'지금 실패하는 편이 낫다.')
        return 1
    print(f'\n{len(rows)}건 전부 통과 — 축적을 진행한다.')
    return 0


if __name__ == '__main__':
    _utf8()
    sys.exit(main())
