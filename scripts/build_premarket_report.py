# -*- coding: utf-8 -*-
"""개장 전 리포트를 이 PC 의 저녁 작업이 장 마감 뒤에 만든다 (라운드 484 · 화면의 첫 스캔과 같은 함수).

■ 왜 (2026-10-11 실측 · 라운드 483)
  개장 전 리포트는 **앱을 열 때만** 만들어졌다. 그래서 리포트가 언제 만들어지는지가 사람이 언제 앱을 여는지에 묶였다 —
  107개 중 9개가 다음 거래일 **장중**에 만들어져 가격이 장중 값이었고(추적 32건 · 라운드 483 이 채점 경계로 막았다), 하나는 장
  마감 2분 뒤라 가격이 확정 종가가 아니었다(+0.21~+3.66%). 그리고 앱을 안 연 날은 리포트가 없어 그날 추적·전방 판정(R475·R478)·
  자동매매 계획 표본이 통째로 빠진다 — 사람의 습관이 연구 표본을 정했다. 주기적인 일은 사람이 아니라 저녁 작업이 한다(라운드 414).

■ 무엇을 하나
  · 스캔은 `market_scan.run` — 화면의 '최신화'·첫 진입 스캔과 **같은 함수**(§4) · 화면 기본값(종합 이슈 · 상위 5 · rho 0.80) 그대로.
  · 리포트는 `premarket.build_report` — 화면과 같은 함수 · 같은 자료 기준일 규칙(라운드 442) · 이미 있으면 다시 안 만든다(라운드 228).
  · **정규장 중에는 만들지 않는다** — 그때 받는 가격은 장중 값이다(라운드 483). 장 전·장 마감 뒤·휴장일에만.
  · 쓰기 금지(`GAEUM_NO_LOCAL_WRITE`)면 아무것도 안 한다(리포트·이력은 `.portfolio` 에 쓴다 · 회귀·배포는 사용자 자료를 안 쓴다).
  · 예외는 삼키지 않는다 — 사유를 찍고 종료 1(저녁 작업이 그 줄을 기록에 남긴다).

    C:/Python314/python.exe scripts/build_premarket_report.py           # 만들 수 있으면 만든다
    C:/Python314/python.exe scripts/build_premarket_report.py --plan    # 만들지 판단만(네트워크 0 · 쓰기 0)
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:                                              # noqa: BLE001
    pass
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)


def decide(now, has_report, no_write=False):
    """만들지 — (True, 자료 기준일) 또는 (False, 사유). 순수 판단(달력·장 시각은 엔진 한 곳 · 리포트 유무는 넘겨받는다)."""
    if no_write:
        return False, '쓰기 금지(GAEUM_NO_LOCAL_WRITE) — 리포트·이력을 쓰는 단계라 건너뛴다'
    import bitemporal_engine as be
    import premarket
    st = be.get_market_status(now)
    if st.get('state') == '장중':
        return False, ('정규장 중이다 — 이때 받는 가격은 장중 값이라 자료일 리포트로 고정하지 않는다(라운드 483) · '
                       '장 마감 뒤 저녁 작업이 다시 본다')
    # 라운드 486 — 정규장이 끝나도 애프터마켓(16:00~20:00)이 끝나기 전엔 그날 종가·일봉이 움직인다 · 사유는 화면과 같은 한 곳
    blk = premarket.report_fix_blocker(now)
    if blk:
        return False, blk + ' · 저녁 작업이 그 뒤 다시 본다'
    day = premarket.report_day(now)
    if not day:
        return False, '자료 기준일을 정하지 못했다 — 만들지 않는다(§3)'
    if has_report(day):
        return False, f'자료일 {day} 리포트가 이미 있다 — 다시 안 만든다(라운드 228)'
    return True, day


def _won(v):
    return f'{v:,.0f}원' if isinstance(v, (int, float)) else '미수신'


def feed_gate(b):
    """화면과 **같은 시세 관문**을 지난다 → (통과?, 한 줄). 화면은 보는 종목으로, 저녁 작업은 화면의 기본 종목(시총 1위)으로 잰다.

    라운드 486 — 화면에서는 리포트 고정이 이 관문(네이버·다음 현재가 · 허용 오차는 스캐너와 같은 규칙집 값) **안쪽**에서만
    일어나는데 라운드 484 의 저녁 작업은 관문 없이 만들었다. 같은 산출물을 만드는 두 길의 안전장치가 같아야 한다(§4)."""
    import market_scan
    name = b.fetch_realtime_market_cap_no1_stock()
    if not name:
        return False, '시세 교차검증 못 함 — 시총 1위를 못 받았다(화면도 이 상태면 종목을 못 정해 멈춘다)'
    sym, _nm = b.resolve_symbol(name)
    if not sym:
        return False, '시세 교차검증 못 함 — 시총 1위 종목 코드를 못 찾았다'
    cv = b.verify_realtime_sources(sym)
    kind = market_scan.price_feed_gate(cv)
    d = cv.get('diff_pct')
    desc = (f"{sym} 네이버 {_won((cv.get('naver') or {}).get('price'))} · 다음 {_won((cv.get('daum') or {}).get('price'))}"
            + (f' · 오차 {d:.3f}%' if d is not None else ''))
    if kind == 'na':
        return False, f'시세 교차검증 불가 — {desc} (한 곳 이상 미수신)'
    if kind == 'diff':
        return False, f'시세 교차검증 실패 — {desc} > {market_scan.xcheck_tol_pct():.1f}%'
    return True, f'시세 교차검증 통과 — {desc}'


def close_check(rep, fetch):
    """리포트 후보 가격 = 그 자료일의 **확정 일봉 종가**인가 → dict(day, checked, same, diff, unmeasured) (라운드 492).

    라운드 486 이 *"첫 증거는 다음 평일 21:00 실행이다 — 리포트 가격이 그날 일봉 종가(애프터마켓 마감가)와 같은지 그 밤에
    대 본다"* 고 미뤄 둔 확인을 사람이 아니라 저녁 작업이 매일 한다(라운드 414 — 주기적인 일은 사람 몫이 아니다). 판정·리포트는
    안 바꾸고 **적기만** 한다. 문턱 없음 — 원 단위로 같은지(반올림 차 0.5원 미만)만 본다. 다르면 그 리포트의 가격이 확정 종가가
    아닌 값으로 고정됐다는 뜻이다(장중·애프터마켓 중 고정 · 자료원이 종가 뜻을 바꿈 · 라운드 483·486).
    `fetch(symbol)` → 일봉 프레임(trade_date · close_raw) · 못 받거나 그날 봉이 없으면 그 후보는 '못 잼'으로 센다(§3)."""
    day = str((rep or {}).get('data_asof') or (rep or {}).get('date') or '')[:10]
    out = dict(day=day, checked=0, same=0, diff=[], unmeasured=[])
    for p in (rep or {}).get('picks') or []:
        if not isinstance(p, dict):
            out['unmeasured'].append(('?', '후보 칸 모양이 다름'))
            continue
        sym = p.get('symbol') or p.get('code')
        tail = str(p.get('code') or sym or '?')[-4:]
        try:
            price = float(p.get('price'))
        except (TypeError, ValueError):
            out['unmeasured'].append((tail, '리포트 가격 없음'))
            continue
        try:
            df = fetch(sym)
            row = df[df['trade_date'].astype(str).str[:10] == day]
            close = float(row['close_raw'].iloc[-1]) if len(row) else None
        except Exception as ex:                                # noqa: BLE001 — 못 받은 것은 '못 잼'으로(같다·다르다로 안 센다)
            out['unmeasured'].append((tail, f'일봉 못 받음 {type(ex).__name__}'))
            continue
        if close is None:
            out['unmeasured'].append((tail, f'{day} 봉 없음'))
            continue
        out['checked'] += 1
        if abs(price - close) < 0.5:
            out['same'] += 1
        else:
            out['diff'].append((tail, price, close))
    return out


def close_line(chk):
    """`close_check` 결과 → 저녁 작업 기록 한 줄(종목은 코드 끝 네 자리만)."""
    s = f"리포트 가격 = 자료일 {chk['day']} 확정 일봉 종가 {chk['same']}/{chk['checked']}"
    if chk['diff']:
        s += ' · 다름 ' + ', '.join(f"…{t} {p:,.0f}≠{c:,.0f}" for t, p, c in chk['diff'][:5]) + (
            f" 외 {len(chk['diff']) - 5}" if len(chk['diff']) > 5 else '')
    if chk['unmeasured']:
        s += f" · 못 잼 {len(chk['unmeasured'])}(" + ', '.join(f'…{t} {w}' for t, w in chk['unmeasured'][:3]) + (
            f" 외 {len(chk['unmeasured']) - 3}" if len(chk['unmeasured']) > 3 else '') + ')'
    return s


def make_report(q, b, day, scan=None, build=None):
    """관문 → 스캔 → 리포트 → (종료 코드, 한 줄). 화면과 같은 차례 — 관문을 못 지나면 스캔도 고정도 안 한다(라운드 486)."""
    import market_scan
    import premarket
    scan = scan or market_scan.run
    build = build or premarket.build_report
    ok, gate_line = feed_gate(b)
    if not ok:
        return 1, f'실패 — {gate_line} · 리포트를 안 만들었다(화면도 이 관문을 못 지나면 리포트를 고정하지 않는다)'
    t0 = time.time()
    try:
        r = scan(q, b, day)
    except Exception as ex:                                    # noqa: BLE001
        return 1, f'실패 — 스캔이 멈췄다 {type(ex).__name__}: {str(ex)[:200]} · 리포트를 안 만들었다'
    if r.get('kind') != 'ok':
        return 1, f"실패 — 관심종목 후보를 못 받았다: {r.get('reason')} · 리포트를 안 만들었다"
    rep, new = build(q, r['results'], market_label=market_scan.market_label_of(r['results']))
    picks = len((rep or {}).get('picks') or [])
    # 라운드 492 — 고정한 가격이 그 자료일의 확정 일봉 종가와 같은지 그 자리에서 대 본다(적기만 · 판정·종료 코드 불변)
    chk = close_check(rep, lambda s: b.fetch_daily_bars(s))
    return 0, (f"{gate_line} | {'만듦' if new else '이미 있음'} — 자료일 {(rep or {}).get('date')} · 후보 {picks} · "
               f"정밀 분석 {len(r['results'])} · 빠진 후보 {len(r.get('failures') or [])} · "
               f"코드 못 찾음 {len(r.get('unmapped') or [])} · 생성 {(rep or {}).get('generated_at')} · {time.time() - t0:.0f}초"
               f" | {close_line(chk)}")


def existing_close_line(now):
    """리포트가 이미 있으면(화면이 먼저 만든 날) 그 리포트의 가격도 확정 종가와 대 본다 → 한 줄 또는 None (라운드 492).
    봉이 확정된 뒤에만 잰다(정규장 중 · 애프터마켓 중이면 None — 대 볼 종가가 아직 움직인다). 쓰기 0 · 판정 불변."""
    try:
        import bitemporal_engine as be
        import premarket
        if be.get_market_status(now).get('state') == '장중' or premarket.report_fix_blocker(now):
            return None
        day = premarket.report_day(now)
        rep = premarket.load_today_report(day) if day else None
        if not rep:
            return None
        b = be.BitemporalEngine()
        return '이미 있던 리포트 — ' + close_line(close_check(rep, lambda s: b.fetch_daily_bars(s)))
    except Exception as ex:                                    # noqa: BLE001 — 대조는 기록일 뿐 · 못 하면 사유를 적는다
        return f'이미 있던 리포트의 종가 대조 못 함 — {type(ex).__name__}: {str(ex)[:160]}'


def main(argv=None):
    ap = argparse.ArgumentParser(description='개장 전 리포트를 장 마감 뒤에 만든다')
    ap.add_argument('--plan', action='store_true', help='만들지 판단만')
    a = ap.parse_args(argv)
    import premarket
    now = _dt.datetime.now()
    ok, why = decide(now, lambda d: bool(premarket.load_today_report(d)),
                     no_write=bool(os.environ.get('GAEUM_NO_LOCAL_WRITE')))
    if not ok:
        print(f'건너뜀 — {why}')
        if not a.plan:
            ex_line = existing_close_line(now)
            if ex_line:
                print(ex_line)
        return 0
    day = why
    if a.plan:
        print(f'계획 — 자료일 {day} 리포트를 만든다(스캔 상위 5 · 약 2~3분)')
        return 0
    from bitemporal_engine import BitemporalEngine
    from quant_indicators import QuantIndicatorsEngine
    try:
        q, b = QuantIndicatorsEngine(), BitemporalEngine()
    except Exception as ex:                                    # noqa: BLE001
        print(f'실패 — 엔진을 못 만들었다 {type(ex).__name__}: {str(ex)[:200]} · 리포트를 안 만들었다')
        return 1
    code, line = make_report(q, b, day)
    print(line)
    return code


if __name__ == '__main__':
    sys.exit(main())
