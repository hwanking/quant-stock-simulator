# -*- coding: utf-8 -*-
"""
라운드 390 — 데이터 오염 **매일** 점검 (관측 전용 · 문턱 없음 · 항등식만).

■ 왜 필요한가
  라운드 389 가 손으로 저장소마다 오염을 셌다 — 대부분 깨끗했고, 실재한 것은 '세는 자리'였다(같은 추천을 두 번
  채점 · 축척이 어긋난 진입가가 통계에 섞임 · 원장에 없는 필터 값). 그 점검을 **한 번 하고 끝내면** R88 의
  '실거래일 대조'처럼 다음 오염은 아무도 안 본다(R375). 그래서 같은 점검을 매일 돌리고, **0 이어야 하는 수**가
  0 이 아니면 붉게 만든다.

■ 무엇을 보나 — 이 저장소에서 실제로 났던 오염의 모양만
  반드시 0 (hard · 하나라도 있으면 실패 — 단 `LEGACY` 에 적힌 알려진 옛 오염은 **늘 때만** 실패):
    · 미래 날짜 · 휴장일 날짜(원장·예측·전방 기록부·판정 원장·시점 재무·잔여 호가) · 픽스처 날짜(2099/1970)
      · 빈 날짜 · (종목, 날짜) 중복 · 종목코드 모양 아님                                    (R222 · R252 · R375)
    · 원장: 가격 0 이하 · 손절 < 진입 < 목표 어긋남 · 행 안 불변식(`ledger_view.consistency_violations`)
      · 구간 표시가 날짜와 어긋남(경계는 `calibration_lab` 의 상수를 읽는다)               (R368 · R217)
    · 전방 기록부: 버전 칸이 빈 행                                                          (R360)
    · 전방 기록부: 그 가격을 **본 순간 이미 정규장이 열린** 행(`seen_in_session` · R483) — 11-16 전방 판정기(R398 · R470)는
      박제돼 있어 이 행을 그날 봉 전체(가격을 보기 전의 고가·저가 포함)로 채점한다. 기록기는 장 마감 뒤에 돌므로 0 이어야 한다
    · 추적 DB: 미래 기준일인데 픽스처 표시가 없는 케이스 · 동결 가드(R252) 뒤에 들어온 휴장일 케이스 (R222 · R252)
  알림용 (info · 실패 아님 — 알려진 것·구조):
    · 진입가 축척 도장 셈(채점 자리 · R390) · 축척 감사의 어긋난 행(R365) · 점수대별 블라인드 비중(R389)
    · 추적 DB 의 옛 휴장일 케이스(갈래에서 빠짐 · R389) · 주말 뉴스(사건 날짜라 정상) · 휴장일 개장 전 리포트(옛 것)
    · 장중에 본 가격으로 동결된 추적 케이스 · 장중에 기록한 판정 원장 줄(R483 — 채점은 그 장의 봉을 뺀다 · 셈만)

■ 안 하는 것
  · 고치지 않는다 — 세고 적는다(원장·DB 행은 안 지운다 · R197). 고침은 사람이 결과를 보고 한다
  · **종목 이름·코드·가격은 산출물에 안 담는다**(§9 · 이 파일은 업로드 묶음에 실린다) — 수만 적는다
  · 못 읽은 저장소는 0 으로 세지 않고 `unmeasured` 에 이유와 함께 적는다(§3 · R194)

    C:/Python314/python.exe scripts/contamination_audit.py            # 재고 산출물을 쓴다
    C:/Python314/python.exe scripts/contamination_audit.py --verify   # 산출물을 읽어 hard 가 0 이 아니면 exit 1
"""
import ast
import collections
import datetime
import glob
import io
import json
import os
import re
import sqlite3
import sys
import time

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
P = os.path.join(PROJ, '.portfolio')
OUT = os.path.join(PROJ, 'data', 'contamination_audit.json')

#: 종목코드 모양 — KRX 문자코드 포함(R164 · `stock_code` 와 같은 모양) · 시장 접미사 허용
CODE_RE = re.compile(r'^[0-9][0-9A-Z]{5}(\.(KS|KQ))?$')
#: 라운드 252 가 추적 동결에 휴장일 건너뛰기를 넣은 날의 다음 날 — 그 뒤로 들어온 휴장일 케이스는 가드가 뚫린 것이다.
FREEZE_SKIP_SINCE = '2026-09-10'
FIXTURE_PREFIXES = ('2099', '1970')


def _utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def seen_in_session(rows, dkey, skey):
    """가격을 **본 순간 이미 정규장이 열린 거래일**이 자료일보다 뒤인 행 수 — 순수 함수(심어서 잰다 · 라운드 483).
    규칙은 채점기 한 곳(`prediction_log.grade_after_day`)을 부른다. 본 시각이 없는 행은 안 센다(경계 = 자료일)."""
    import prediction_log as plog
    n = 0
    for r in rows:
        d = str(r.get(dkey) or '')[:10]
        if d and plog.grade_after_day(d, r.get(skey)) != d:
            n += 1
    return n


def _is_holiday(day):
    from improvement.case_tracker import is_non_trading_date
    return is_non_trading_date(day)


def date_checks(rows, dkey, tkey, today):
    """(날짜, 종목) 모양의 저장소 한 벌을 센다 — 순수 함수(심어서 잰다).
    반환: {rows, future, holiday, fixture, empty, dup, bad_code} (전부 '0 이어야 하는 수')."""
    n = fut = hol = fx = empty = bad = 0
    seen = collections.Counter()
    for r in rows:
        n += 1
        d = str(r.get(dkey) or '')[:10]
        t = str(r.get(tkey) or '')
        if not d:
            empty += 1
        else:
            if d.startswith(FIXTURE_PREFIXES):
                fx += 1
            elif d > today:
                fut += 1
            if _is_holiday(d):
                hol += 1
        if not CODE_RE.match(t):
            bad += 1
        seen[(t.split('.')[0], d)] += 1
    dup = sum(v - 1 for v in seen.values() if v > 1)
    return {'rows': n, 'future': fut, 'holiday': hol, 'fixture': fx, 'empty': empty, 'dup': dup, 'bad_code': bad}


def _jsonl(path):
    """줄 단위로 흘린다 — 원장(240MB)을 통째로 들지 않는다(R282). 못 읽는 줄은 따로 센다."""
    bad = [0]

    def gen():
        with io.open(path, encoding='utf-8', errors='replace') as f:
            for ln in f:
                if not ln.strip():
                    continue
                try:
                    yield json.loads(ln)
                except ValueError:
                    bad[0] += 1
    return gen, bad


def _split_bounds():
    """학습·검증·블라인드 경계 — `calibration_lab` 의 상수를 **읽는다**(다시 적지 않는다 · §4). 못 읽으면 None."""
    try:
        src = io.open(os.path.join(PROJ, 'scripts', 'calibration_lab.py'), encoding='utf-8').read()
        vals = {}
        for node in ast.parse(src).body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                if node.targets[0].id in ('SPLIT_VALID_FROM', 'SPLIT_BLIND_FROM') \
                        and isinstance(node.value, ast.Constant):
                    vals[node.targets[0].id] = str(node.value.value)
        return (vals['SPLIT_VALID_FROM'], vals['SPLIT_BLIND_FROM'])
    except Exception:                                          # noqa: BLE001
        return None


def ledger_checks(rows_iter, today, bounds):
    """원장 전용 — 날짜 모양 + 가격·선 순서 + 행 안 불변식 + 구간 표시 + 축척 도장·점수대 블라인드 비중(알림)."""
    import ledger_view as lv
    base_rows = []
    bad_px = order = inv = split_bad = 0
    stamp = collections.Counter()
    stamp_off, stamp_same = set(), set()
    band = collections.defaultdict(lambda: [0, 0])       # 점수대 → [판정 완료, 그중 블라인드]
    for r in rows_iter:
        base_rows.append({'date': r.get('date'), 'ticker': r.get('ticker')})
        px, sl, tg = r.get('price'), r.get('stop'), r.get('target')
        if not isinstance(px, (int, float)) or px <= 0:
            bad_px += 1
        elif isinstance(sl, (int, float)) and isinstance(tg, (int, float)) and not (sl < px < tg):
            order += 1
        if lv.consistency_violations(r):
            inv += 1
        if bounds:
            d = str(r.get('date') or '')[:10]
            exp = 'blind' if d >= bounds[1] else ('valid' if d >= bounds[0] else 'train')
            split_bad += int(r.get('split') != exp)
        v = r.get('entry_scale_off', 'missing')
        stamp['missing' if v == 'missing' else ('off' if v is True else ('same' if v is False else 'unknown'))] += 1
        if v is True or v is False:      # 라운드 391 — 두 판정자(도장·감사)를 행으로 대 보려고 열쇠를 모은다
            (stamp_off if v is True else stamp_same).add(lv.scale_key(r.get('ticker'), r.get('date')))
        sc = r.get('score')
        if r.get('outcome') in ('TARGET', 'STOP') and isinstance(sc, (int, float)):
            lo = 40 if sc < 50 else (50 if sc < 55 else (55 if sc < 60 else (60 if sc < 65 else 65)))
            band[lo][0] += 1
            band[lo][1] += int(r.get('split') == 'blind')
    out = date_checks(base_rows, 'date', 'ticker', today)
    out.update({'bad_price': bad_px, 'level_order': order, 'invariant': inv,
                'split_mismatch': split_bad if bounds else None})
    info = {'scale_stamp': dict(stamp),
            'blind_share_by_band': {str(k): {'decided': v[0], 'blind': v[1],
                                             'blind_pct': round(100.0 * v[1] / v[0], 1) if v[0] else None}
                                    for k, v in sorted(band.items())},
            # 산출물에는 안 싣는다(열쇠에 종목코드가 든다 · §9) — run() 이 수로 바꾸고 뺀다
            '_stamp_off_keys': stamp_off, '_stamp_same_keys': stamp_same}
    return out, info


def scale_judges(stamp_off, stamp_same, audit_keys):
    """채점 도장과 축척 감사 — 같은 항등식을 쓰는 두 판정자가 행에서 갈리는 수 (라운드 391 · 알림).

    감사를 못 읽으면(None) 대지 않는다(§3). 도장은 채점하는 그 봉으로, 감사는 같은 날 뒤에 다시 받은 봉으로 재므로
    자료원이 그 사이 과거 봉을 고쳐 쓰면(R389) 정당하게 갈릴 수 있다 — 그래서 실패가 아니라 알림이다."""
    if audit_keys is None:
        return None
    return {'stamp_off': len(stamp_off), 'audit_rows': len(audit_keys),
            'stamp_only': len(stamp_off - audit_keys),
            'audit_only_stamped_same': len(audit_keys & stamp_same)}


def tracker_checks(db_path, today):
    """추적 DB — 미래 기준일인데 픽스처 표시가 없는 것 · 동결 가드 뒤에 들어온 휴장일 케이스(hard) · 옛 휴장일(info)."""
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute('SELECT signal_date, status, created_at FROM prediction_cases').fetchall()
    finally:
        con.close()
    fut = hol_new = hol_old = 0
    for d, st, ca in rows:
        d = str(d or '')[:10]
        if d > today and st != 'void_fixture':
            fut += 1
        if st not in ('dup_version', 'void_fixture') and _is_holiday(d):
            if str(ca or '')[:10] >= FREEZE_SKIP_SINCE:
                hol_new += 1
            else:
                hol_old += 1
    return ({'rows': len(rows), 'future_unmarked': fut, 'holiday_after_guard': hol_new},
            {'legacy_holiday_cases': hol_old})


#: '반드시 0' 칸 — 저장소별로 어느 칸을 hard 로 보나(나머지는 알림)
HARD = {
    'ledger': ('parse_fail', 'future', 'holiday', 'fixture', 'empty', 'dup', 'bad_code', 'bad_price',
               'level_order', 'invariant', 'split_mismatch'),
    'virtual_predictions': ('parse_fail', 'future', 'holiday', 'fixture', 'empty', 'dup', 'bad_code'),
    'forward_registry': ('parse_fail', 'future', 'holiday', 'fixture', 'empty', 'dup', 'bad_code', 'empty_versions',
                         'seen_in_session'),
    'predictions': ('parse_fail', 'future', 'holiday', 'fixture', 'empty', 'dup', 'bad_code'),
    'fin_pit': ('parse_fail', 'future', 'holiday', 'fixture', 'empty', 'dup'),
    'book_pit': ('parse_fail', 'future', 'holiday', 'fixture', 'empty', 'dup'),
    'tracker': ('future_unmarked', 'holiday_after_guard'),
}


#: 알려진 옛 오염 — 행은 안 지우므로(R197) 영원히 남는다. **늘면** 실패, 그대로거나 줄면 통과(§324 · §362 와 같은 모양).
#:   2026-09-29 실측 · 라운드 390: 같은 종목·같은 날이 시장 접미사만 다르게 두 번 든 복사본(진입가·결과까지 같다).
#:   원인(완료 판정 열쇠에 접미사가 들었다)은 같은 라운드에 고쳤고, 통계는 `ledger_view.stat_rows` 가 뺀다.
#:   ⚠️ 2026-10-06 · 라운드 428 — 2,499 → **2,500** · 287 → **288**. 클라우드 꼬리 검사가 이 칸에서 붉어졌고(제 일을 했다),
#:   10-03 → 10-06 스냅샷 사이에 **1묶음**이 새로 생겼다. 라운드 390 의 열쇠 고침은 실행 **사이**의 재생성만 막았고, 계획
#:   목록이 같은 종목을 두 접미사로 들고 있어(고정 목록 안 1 · 유니버스 덧붙이기가 전체 티커로 빼서 다시 든 변이) **한
#:   실행 안**에서 두 변이가 둘 다 '아직 안 만든 것'이었다. 원인은 `calibration_lab.dedupe_by_code` · 계획 집합으로 닫았다.
#:   그 1행은 지우지 않는다 — 수만 옮긴다. 또 늘면 그것은 새 누수다.
LEGACY = {
    'ledger.dup': 2500,
    'virtual_predictions.dup': 288,
}


def hard_nonzero(stores, legacy=None):
    """hard 칸 중 0 이 아닌 것(알려진 옛 오염은 그 수를 **넘을 때만**) — ['저장소.칸=수', …].
    None(못 잰 칸)은 여기 안 넣는다(unmeasured 가 따로 센다)."""
    legacy = LEGACY if legacy is None else legacy
    out = []
    for name, cols in HARD.items():
        st = stores.get(name)
        if not isinstance(st, dict):
            continue
        for c in cols:
            v = st.get(c)
            if isinstance(v, int) and v > int(legacy.get(f'{name}.{c}', 0)):
                out.append(f'{name}.{c}={v}' + (f' (알려진 옛 {legacy[f"{name}.{c}"]:,} 초과)'
                                                if f'{name}.{c}' in legacy else ''))
    return out


def run(today=None):
    today = today or datetime.date.today().isoformat()
    t0 = time.time()
    stores, info, unmeasured = {}, {}, []

    def _simple(name, fname, dkey, tkey, extra=None):
        path = os.path.join(P, fname)
        if not os.path.exists(path):
            unmeasured.append(f'{name}: 파일 없음')
            return
        gen, bad = _jsonl(path)
        rows = list(gen()) if extra else gen()
        st = date_checks(rows, dkey, tkey, today)
        st['parse_fail'] = bad[0]
        if extra:
            st.update(extra(rows))
        stores[name] = st

    led = os.path.join(P, 'virtual_graded.jsonl')
    if os.path.exists(led):
        gen, bad = _jsonl(led)
        st, linfo = ledger_checks(gen(), today, _split_bounds())
        st['parse_fail'] = bad[0]
        stores['ledger'] = st
        info.update(linfo)
        if st.get('split_mismatch') is None:
            unmeasured.append('ledger.split_mismatch: 구간 경계를 calibration_lab 에서 못 읽음')
    else:
        unmeasured.append('ledger: 파일 없음')
    _simple('virtual_predictions', 'virtual_predictions.jsonl', 'date', 'ticker')
    _simple('forward_registry', 'forward_registry.jsonl', 'date', 'ticker',
            extra=lambda rows: {'empty_versions': sum(1 for r in rows if not r.get('versions')),
                                'seen_in_session': seen_in_session(rows, 'date', 'signal_timestamp')})
    _simple('predictions', 'predictions.jsonl', 'date', 'ticker',
            extra=lambda rows: {'seen_in_session': seen_in_session(rows, 'date', 'recorded_at')})
    _simple('fin_pit', 'fin_pit.jsonl', 'date', 'code')
    _simple('book_pit', 'book_pit.jsonl', 'date', 'code')
    db = os.path.join(P, 'improvement.db')
    if os.path.exists(db):
        try:
            st, tinfo = tracker_checks(db, today)
            stores['tracker'] = st
            info.update(tinfo)
        except Exception as e:                                 # noqa: BLE001
            unmeasured.append(f'tracker: {type(e).__name__}')
    else:
        unmeasured.append('tracker: DB 없음')
    # 라운드 483 — 장중에 본 가격으로 동결된 추적 케이스(알림 · 채점은 그 장의 봉을 뺀다). 본 시각은 동결 규칙 한 곳에서.
    try:
        sys.path.insert(0, os.path.join(PROJ, 'scripts'))
        import run_daily_improvement as _rdi483
        import prediction_log as _pl483
        _seen483 = _rdi483.freeze_seen_at()
        if not os.path.exists(db):
            raise FileNotFoundError('improvement.db')     # 연결만 열어도 빈 파일을 만든다(R331) — 먼저 본다
        _con483 = sqlite3.connect(db)
        try:
            _cs483 = _con483.execute("SELECT ticker, signal_date, reference_price FROM prediction_cases "
                                     "WHERE status NOT IN ('dup_version', 'void_fixture')").fetchall()
        finally:
            _con483.close()
        info['tracker_seen_in_session'] = sum(
            1 for t, d, px in _cs483
            if _pl483.grade_after_day(d, _seen483.get((str(t), str(d)[:10], float(px or 0)))) != str(d)[:10])
    except Exception as e:                                     # noqa: BLE001
        info['tracker_seen_in_session'] = None
        unmeasured.append(f'tracker_seen_in_session: {type(e).__name__}')
    ne = os.path.join(P, 'news_events.jsonl')
    if os.path.exists(ne):
        gen, _ = _jsonl(ne)
        info['news_weekend_rows'] = sum(1 for r in gen() if _is_holiday(str(r.get('date') or '')[:10]))
    info['premarket_holiday_reports'] = sum(
        1 for x in {os.path.basename(p)[10:20] for p in glob.glob(os.path.join(P, 'premarket_2026-*.json'))}
        if _is_holiday(x))
    try:
        esa = json.load(io.open(os.path.join(PROJ, 'data', 'entry_scale_audit.json'), encoding='utf-8'))
        info['scale_audit'] = {'made': esa.get('made'), 'offenders': esa.get('offenders'),
                               'offender_key_rows': esa.get('offender_key_rows'),
                               # 라운드 391 — 20행 미만 종목(종목 목록 밖 · 행 목록 안) · 옛 판이면 None
                               'small_offenders': esa.get('small_offenders'),
                               'small_offender_key_rows': esa.get('small_offender_key_rows')}
    except Exception:                                          # noqa: BLE001
        info['scale_audit'] = None
    _off391 = info.pop('_stamp_off_keys', set())
    _same391 = info.pop('_stamp_same_keys', set())
    try:
        import ledger_view as _lv391
        info['scale_judges'] = scale_judges(_off391, _same391, _lv391.scale_mismatch_keys())
    except Exception:                                          # noqa: BLE001
        info['scale_judges'] = None
    hard = hard_nonzero(stores)
    return {
        'made': today, 'made_at': time.strftime('%Y-%m-%d %H:%M'),
        'ledger_rows': (stores.get('ledger') or {}).get('rows'),       # 신선도 규약(R259)
        'took_sec': round(time.time() - t0, 1),
        'stores': stores, 'info': info, 'hard_nonzero': hard, 'unmeasured': unmeasured,
        'legacy': LEGACY,
        'scanned_rows': sum(int((s or {}).get('rows') or 0) for s in stores.values()),
        'note': ('0 이어야 하는 수(hard)와 알림(info)을 가른다. 문턱이 없다 — 전부 항등식이다. 이름·코드·가격은 안 담는다(§9). '
                 '못 읽은 저장소는 0 으로 세지 않고 unmeasured 에 적는다(§3).'),
    }


def main(argv):
    _utf8()
    if '--verify' in argv:
        try:
            doc = json.load(io.open(OUT, encoding='utf-8'))
        except Exception as e:                                 # noqa: BLE001
            print(f'>> 못 쟀다 — 산출물을 못 읽음 ({type(e).__name__}) · 통과 아님')
            return 2
        print(f"오염 점검 산출물 {doc.get('made_at')} · 본 행 {doc.get('scanned_rows'):,} · "
              f"못 잰 곳 {len(doc.get('unmeasured') or [])}")
        if not doc.get('scanned_rows'):
            print('>> 못 쟀다 — 본 행이 0 이다 · 통과 아님')
            return 2
        if doc.get('hard_nonzero'):
            print(f">> 0 이어야 하는 수가 0 이 아니다: {doc['hard_nonzero']}")
            return 1
        print('>> 통과 — 0 이어야 하는 수가 전부 0 이다')
        return 0
    doc = run()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with io.open(OUT, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    print(f"오염 점검 — 본 행 {doc['scanned_rows']:,} · {doc['took_sec']}초")
    for name, st in doc['stores'].items():
        print(f'  {name}: ' + ' · '.join(f'{k} {v}' for k, v in st.items()))
    print(f"  알림: {json.dumps(doc['info'], ensure_ascii=False)[:600]}")
    print(f"  못 잰 곳: {doc['unmeasured'] or '없음'}")
    print(f">> 0 이어야 하는데 아닌 것: {doc['hard_nonzero'] or '없음'}")
    print(f'저장: {OUT}')
    return 1 if doc['hard_nonzero'] else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
