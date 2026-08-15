# -*- coding: utf-8 -*-
"""전방 기록부 — 2026-11-16 재평가가 읽을 원장 (라운드 97).

■ 왜 따로 만드나
  `predictions.jsonl` 은 "이 앱이 계속 잘 맞고 있나"를 보는 일반 기록이다.
  293건이 쌓여 있지만 **필드가 11개뿐**이고, 전방 재평가에 필요한 것이
  하나도 없다 (실측 14/14 부재):

      어느 엔진이 냈나 · 어느 규칙이었나 · 언제 찍었나 ·
      **어느 가격을 기준으로 한 목표인가** · 그날 국면·업종·뉴스는 뭐였나

  더 나쁜 것은 이미 있는 두 필드다. `target`/`stop` 에 들어간 값은
  `target_tech_1st`/`stop_loss_price` — verdict_core 기준으로 **보유자
  값**이다. 그걸 중립 이름으로 적어 두었으니, 11/16 에 읽는 사람은 그것을
  신규 매수자 목표로 읽는다. §4 가 금지한 바로 그 혼동이다.

      005930.KS · 현재가 262,500 · target 325,000 · stop 216,000
      ↑ 이건 '지금 들고 있다면 어디서 덜고 어디서 끊나'이지
        '지금 사면 어디가 목표인가'가 아니다.

■ 기존 293건은 **고치지 않는다**
  옛 규약으로 찍힌 기록이다. 지금 와서 없는 필드를 채우면 그건 측정이
  아니라 창작이다(§3). 대신 규약 이름을 붙여 갈라 둔다 — 11/16 에
  `contract` 로 걸러 읽으면 된다.

■ 이 원장이 지키는 것
  · 값은 **verdict_core.build() 하나에서만** 온다 (§4 — 경로가 둘이면
    한쪽만 고치는 일이 생긴다)
  · 신규 매수자(new_*)와 보유자(hold_*)를 **다른 키로** 적는다
  · 못 채운 것은 None 으로 두고 **왜 못 채웠는지 같이 적는다** (§3)
  · 추가만 한다. 같은 (종목, 날짜)는 두 번 안 쓴다

저장: .portfolio/forward_registry.jsonl
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
REG_FILE = os.path.join(BASE, '.portfolio', 'forward_registry.jsonl')

#: 기록 규약 이름. 필드 구성을 바꾸면 **반드시 올린다** — 11/16 에 섞여
#: 읽히면 재평가가 무의미해진다.
CONTRACT = 'fr-1'

#: 이 규약이 약속하는 필드. 검사가 이 목록으로 대조한다 (손으로 센 숫자가
#: 아니라 목록 자체를 조건에 넣는다).
FIELDS = (
    'contract', 'ticker', 'name', 'date', 'signal_timestamp',
    'price',
    'action', 'action_label', 'score',
    # 신규 매수자 — **진입가 기준** (§4)
    'new_entry', 'new_buy_zone', 'new_pullback', 'new_target', 'new_stop',
    'new_rr',
    # 보유자 — **현재가 기준** (§4, 절대 섞지 않는다)
    'hold_trim', 'hold_stop',
    'horizon_days',
    'market_regime', 'market_regime_level', 'sector',
    # 뉴스 — **0건과 미수신을 가른다** (§3). feed_ok 가 False 면 0 은
    # '위험 없음'이 아니라 '못 받았다'는 뜻이다.
    'news_feed_ok', 'news_total', 'news_risk', 'news_review',
    'versions', 'model_sha', 'freeze_hash',
    'missing',
)

#: 값이 없어도 되는 필드 — 종목·날짜에 따라 원래 안 나올 수 있는 것.
#: 여기 없는 필드가 비면 그건 **기록 실패**다.
MAY_BE_NONE = (
    'new_entry', 'new_buy_zone', 'new_pullback', 'new_target', 'new_stop',
    'new_rr', 'hold_trim', 'hold_stop', 'sector', 'name', 'action_label',
    'market_regime', 'market_regime_level',
)


def _f(v):
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _ensure_dir(path):
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)


def _entry_of(vd):
    """build() 의 buy_zone 에서 진입가를 되돌린다.

    build 는 `buy_zone = (round(entry*0.99), round(entry*1.01))` 로 만든다.
    따라서 중심값이 진입가다. 적정가 축을 다시 읽지 않는 것이 요점이다 —
    build 가 폴백을 탔을 때 갈라지지 않게 하려는 것이다(§4).
    """
    z = (vd or {}).get('buy_zone')
    if not z or len(z) != 2:
        return None
    lo, hi = _f(z[0]), _f(z[1])
    if lo is None or hi is None:
        return None
    return round((lo + hi) / 2.0, 2)


def stamp():
    """지금 이 순간의 버전·동결 상태. 못 읽으면 None 을 담는다."""
    out = {'versions': None, 'model_sha': None, 'freeze_hash': None,
           'why': []}
    try:
        import versioning as _v
        out['versions'] = _v.snapshot()
    except Exception as exc:                                    # noqa: BLE001
        out['why'].append(f'버전 스냅샷 실패: {type(exc).__name__}')
    try:
        import sys
        sys.path.insert(0, os.path.join(BASE, 'scripts'))
        import model_freeze_guard as _fg
        out['model_sha'] = _fg.sha('quant_indicators.py')
        # 11/16 평가 대상 전체를 한 값으로 — 하나라도 바뀌면 달라진다
        parts = [f'{rel}:{_fg.sha(rel)}' for rel in _fg.FORWARD_TARGETS]
        import hashlib
        out['freeze_hash'] = hashlib.sha256(
            '\n'.join(parts).encode()).hexdigest()[:32]
    except Exception as exc:                                    # noqa: BLE001
        out['why'].append(f'동결 해시 실패: {type(exc).__name__}')
    return out


def build_row(ticker, snap, verdict, *, name=None, horizon_days=None):
    """스냅샷 + 중앙 판정 → 기록 한 줄.

    **값을 여기서 계산하지 않는다.** verdict_core.build() 가 준 것을
    옮겨 적을 뿐이다 — 계산이 두 곳에 있으면 언젠가 갈라진다(§4).
    """
    fs = (snap or {}).get('four_scores') or {}
    vd = verdict or {}
    missing = []

    def pick(key, src, srckey, why):
        v = _f(src.get(srckey))
        if v is None:
            missing.append(f'{key}: {why}')
        return v

    mc = (snap or {}).get('market_context') or {}
    dom = (mc.get('domestic') or {}) if isinstance(mc, dict) else {}
    # ⚠️ 라운드 97 — 여기를 `mc['news']` 로 적었다가 세 필드가 전부 None 이
    #   됐다. 집계는 `news_flags` 에 있다 (mc['news'] 는 기사 목록이다).
    #   이름을 상상해서 적으면 **전부 비어 있는 원장**이 쌓인다.
    nf = (mc.get('news_flags') or {}) if isinstance(mc, dict) else {}
    val = (snap or {}).get('val_eval') or {}

    st = stamp()
    for w in st['why']:
        missing.append(w)

    sector = val.get('sector')
    if not sector:
        missing.append('sector: 업종 분류를 못 받았다 (ETF·리츠는 원래 없다)')
    if not name:
        missing.append('name: 부르는 쪽이 종목명을 주지 않았다 '
                       '(스냅샷에는 이름이 없다 — 티커로 때우지 않는다)')
    if not nf.get('feed_available'):
        missing.append('news_*: 뉴스 피드를 못 받았다 — 0 은 위험 없음이 '
                       '아니라 미수신이다')

    row = {
        'contract': CONTRACT,
        'ticker': str(ticker),
        # ⚠️ 스냅샷에는 종목명이 없다. 옛 기록은 `fs.get('name') or sym` 로
        #   적어 **티커를 이름 자리에 넣고** 있었다 — 이름 칸이 있는데 이름이
        #   없는 셈이다. 지어내지 않고 부르는 쪽이 주면 쓰고, 없으면 비운다.
        'name': (str(name) if name else None),
        'date': str((snap or {}).get('t_ref') or ''),
        'signal_timestamp': datetime.now(timezone.utc)
                            .isoformat(timespec='seconds'),
        'price': _f(vd.get('current_price') or fs.get('current_price')),
        'action': str(vd.get('action') or ''),
        'action_label': str(vd.get('headline') or ''),
        'score': vd.get('score'),
        # 신규 매수자 — 진입가 기준.
        # ⚠️ build() 는 entry 를 그대로 돌려주지 않고 buy_zone 으로만 낸다
        #   (`buy_zone = (entry*0.99, entry*1.01)`). 진입가를 적정가 축에서
        #   **다시 계산하면** build 가 폴백을 탄 경우와 갈라진다 — 목표·손절은
        #   폴백 값 기준인데 기록된 진입가는 축 값이 되는, §4 가 금지한 조합이다.
        #   그래서 build **자기 출력**에서 되돌린다. 원본 구간도 같이 남긴다.
        'new_entry': _entry_of(vd),
        'new_buy_zone': (list(vd['buy_zone'])
                         if vd.get('buy_zone') else None),
        'new_pullback': _f(vd.get('pullback_zone')),
        'new_target': pick('new_target', vd, 'new_target',
                           '신규 목표가 미산출 (정합 깨짐이면 비운다)'),
        'new_stop': pick('new_stop', vd, 'new_stop', '신규 손절 미산출'),
        'new_rr': _f(vd.get('rr')),
        # 보유자 — 현재가 기준
        'hold_trim': _f(vd.get('hold_trim')),
        'hold_stop': _f(vd.get('hold_stop')),
        'horizon_days': int(horizon_days or vd.get('horizon_days') or 20),
        'market_regime': (dom.get('regime_label')
                          or vd.get('regime') or None),
        'market_regime_level': (dom.get('regime_code')
                                or vd.get('regime_level') or None),
        'sector': sector,
        'news_feed_ok': bool(nf.get('feed_available')),
        'news_total': nf.get('total', nf.get('total_count')),
        'news_risk': nf.get('risk_count'),
        'news_review': nf.get('review_count'),
        'versions': st['versions'],
        'model_sha': st['model_sha'],
        'freeze_hash': st['freeze_hash'],
        'missing': missing,
    }
    return row


def validate(row):
    """규약을 지켰는가 — 어긴 것을 목록으로 돌려준다 (빈 목록이면 통과)."""
    bad = []
    if str(row.get('contract') or '') != CONTRACT:
        bad.append(f"contract 가 {CONTRACT} 가 아니다: {row.get('contract')!r}")
    for k in FIELDS:
        if k not in row:
            bad.append(f'{k} 필드가 아예 없다')
        elif row[k] is None and k not in MAY_BE_NONE:
            bad.append(f'{k} 가 비었다 (빌 수 없는 필드)')
    # §4 — 신규 매수자 값이 다 있으면 순서가 말이 돼야 한다
    e, t, s = row.get('new_entry'), row.get('new_target'), row.get('new_stop')
    if None not in (e, t, s) and not (s < e < t):
        bad.append(f'신규 레벨 정합 깨짐: 손절 {s} < 진입 {e} < 목표 {t} 아님')
    # 보유자 값은 현재가 기준 — 익절이 위, 손절이 아래
    px, ht, hs = row.get('price'), row.get('hold_trim'), row.get('hold_stop')
    if px is not None:
        if ht is not None and ht <= px:
            bad.append(f'보유 익절 {ht} 이 현재가 {px} 아래다')
        if hs is not None and hs >= px:
            bad.append(f'보유 손절 {hs} 이 현재가 {px} 위다')
    return bad


def record(row, path=REG_FILE):
    """한 줄 추가. 규약 위반이면 **쓰지 않고** 사유를 돌려준다.

    반환: (기록함?, 사유목록)
    """
    bad = validate(row)
    if bad:
        return False, bad
    key = (str(row['ticker']), str(row['date'])[:10])
    for r in load(path):
        if (str(r.get('ticker')), str(r.get('date'))[:10]) == key:
            return False, ['같은 종목·날짜가 이미 있다 (덮어쓰지 않는다)']
    try:
        _ensure_dir(path)
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
        return True, []
    except Exception as exc:                                    # noqa: BLE001
        return False, [f'쓰기 실패: {type(exc).__name__}: {exc}']


def load(path=REG_FILE):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding='utf-8', errors='replace') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except Exception:                                   # noqa: BLE001
                continue
    return out


def coverage(path=REG_FILE):
    """이 원장이 재평가에 쓸 만한가 — **본 건수를 같이 돌려준다.**

    0건을 '위반 없음'으로 읽지 않기 위해서다.
    """
    rows = load(path)
    ok = [r for r in rows if not validate(r)]
    return {
        'n': len(rows),
        'valid': len(ok),
        'contracts': sorted({str(r.get('contract') or '(없음)')
                             for r in rows}),
        'dates': sorted({str(r.get('date'))[:10] for r in rows}),
        'with_new_levels': sum(
            1 for r in ok if r.get('new_target') is not None),
    }


def _check(path=REG_FILE):
    """규약을 어긴 행이 있으면 실패시킨다 (워크플로가 부른다).

    ■ 무엇을 판정하나
      · 규약 위반 행이 **하나라도** 있으면 실패. 11/16 에 읽을 수 없는
        행이 섞이면 그날 재평가가 무의미해진다.
      · 0건은 실패로 보지 않는다 — 아직 안 쌓인 날일 수 있다. 대신
        **본 건수를 반드시 찍는다** (0건과 통과를 같은 색으로 찍지 않는다).
    """
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                           # noqa: BLE001
        pass
    cov = coverage(path)
    print(f'전방 기록부 {cov["n"]:,}건 · 규약 통과 {cov["valid"]:,}건 · '
          f'신규 레벨 있음 {cov["with_new_levels"]:,}건')
    print(f'  규약 {cov["contracts"]} · 날짜 {len(cov["dates"])}일'
          + (f' ({cov["dates"][0]} ~ {cov["dates"][-1]})'
             if cov['dates'] else ''))
    if cov['n'] == 0:
        print('  아직 0건이다 — 위반 없음이 아니라 **미측정**이다.')
        return 0
    bad = cov['n'] - cov['valid']
    if bad:
        print(f'  규약 위반 {bad}건 — 11/16 에 읽을 수 없는 행이다.')
        for r in load(path):
            v = validate(r)
            if v:
                print(f'    {r.get("ticker")} @ {r.get("date")}: {v[:3]}')
                break
        return 1
    print('  >> 전건 규약 통과')
    return 0


if __name__ == '__main__':
    import sys as _sys
    _sys.exit(_check())
