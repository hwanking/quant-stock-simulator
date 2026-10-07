# -*- coding: utf-8 -*-
"""
매 거래일 장 종료 후 실행 — 지속 개선 엔진 일일 파이프라인 (실연결판).

단계:
  1. 개장 전 리포트(premarket_history.jsonl)의 픽을 prediction_cases 로 동결
     저장 (중복은 case_id 해시로 자동 무시 — 재실행 안전)
  2. 미결(open) 케이스를 실제 OHLC 경로로 판정 — 원장과 같은 채점기(R232 ·
     prediction_log.grade_prediction: 진입 = 리포트 가격 · 같은 봉은 손절 먼저 · 닿으면 즉시)
  3. 운영 모델 지표 갱신 (calibration.json 실측 → model_versions)
  4. 주요 이슈 자동 감지 (issue_key 로 매일 중복 생성 방지, 해소 시 자동 닫음)

실행:  python scripts/run_daily_improvement.py
"""
from __future__ import annotations

import io
import json
import logging
import os
import sys
from datetime import date, datetime

try:                       # 라운드 103 — 객체를 갈아끼우지 않는다
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:          # noqa: BLE001
    pass
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from improvement.database import get_connection, initialize_database
from improvement.daily_pipeline import run_daily_pipeline
from improvement import case_tracker as ct
from improvement import issue_tracker as it
from improvement import model_registry as mr
from improvement.performance import resolution_from_grade
from improvement.schemas import RECO_CLASS_TO_DECISION, Decision
import versioning as V

PM_HISTORY = os.path.join(BASE, '.portfolio', 'premarket_history.jsonl')
CALIB = os.path.join(BASE, '.portfolio', 'calibration.json')


def _load_calib():
    try:
        with open(CALIB, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _operating_version(calib):
    return str(calib.get('rulebook_version') or 'v-unknown')


def report_stamps(pm_dir=None):
    """날짜별 개장 전 리포트 파일 → {(기준일, 생성 시각 19자): 엔진 버전} (라운드 415).

    이력 행(premarket_history.jsonl)에는 버전 칸이 없고 **그날 리포트 파일**(premarket_YYYY-MM-DD*.json)에
    `engine_version` 이 있다. 행의 `generated_at` 이 그 파일의 `generated_at` 과 같으면 그 파일이 그 추천을
    만든 것이다(2026-10-02 실측: 09-13 뒤 이력 94행 전부 일치 · 그 기간 날짜마다 파일 하나). 못 읽는 파일은 건너뛴다."""
    import glob as _glob
    pm_dir = pm_dir or os.path.dirname(PM_HISTORY)
    out = {}
    for p in _glob.glob(os.path.join(pm_dir, 'premarket_2*.json')):
        try:
            with open(p, encoding='utf-8') as f:
                d = json.load(f)
        except Exception:                                      # noqa: BLE001
            continue
        if d.get('engine_version') and d.get('date') and d.get('generated_at'):
            out[(str(d['date'])[:10], str(d['generated_at'])[:19])] = str(d['engine_version'])
    return out


def case_versions(row, stamps, now_versions):
    """한 이력 행을 동결할 때 찍을 (모델 버전, 규칙집 버전, 출처) — 리포트를 만든 버전이 먼저다 (라운드 415).

    종전엔 늘 **동결하는 날의** 버전을 찍었다. 클라우드가 리포트 다음 밤에 동결할 때는 거의 같았지만, 리포트가
    이 PC 에만 있어 18일 뒤에 동결하면(2026-10-02) 18일 뒤 버전이 그 추천의 도장이 된다 — "이 판단이 어느
    버전에서 나왔나"가 거짓이 된다(§3). 리포트 파일에서 찾으면 그 버전, 규칙집은 그 시각의 버전(`versioning.
    version_at`)이고, 못 찾으면 종전대로 지금 버전에 출처 'freeze_time' 을 붙인다(지어내지 않는다)."""
    gen = str((row or {}).get('generated_at') or '')[:19]
    mv = (stamps or {}).get((str((row or {}).get('date'))[:10], gen))
    if mv:
        rv = V.version_at('rulebook', gen) or now_versions.get('rulebook')
        return mv, rv, 'report'
    return now_versions.get('model'), now_versions.get('rulebook'), 'freeze_time'


def make_create_new_cases(conn, calib):
    def create_new_cases() -> int:
        _vs = V.snapshot()
        if not os.path.exists(PM_HISTORY):
            return 0
        added = 0
        _stamps415 = report_stamps()
        _src415 = {'report': 0, 'freeze_time': 0}
        ver = _operating_version(calib)
        # ⚠️ 라운드 222 — 여기가 **이력 전체를 매번 다시** 읽어 동결했다.
        #   case_id 에 모델 버전이 들어 있어, 버전이 바뀔 때마다 지난 추천이
        #   통째로 '새 케이스'였다(실측 2026-09-04: 463행 중 고유 (종목,기준일)
        #   218 · 복사본 245 · 53%. 08-15 에는 같은 85건이 두 번 들어갔다).
        #   R217 의 격자 밀림과 같은 모양이다 — 완료 판정의 열쇠가 잘못됐다.
        #   추천의 **정체는 (종목, 기준일)** 이고 버전은 도장이다. 이미 동결된
        #   쌍은 어느 버전이든 건너뛴다("이전 버전 케이스는 덮어쓰지 않는다"
        #   의 뜻이 그것이다). 그리고 **미래 기준일**은 있을 수 없으므로 건너뛴다
        #   — 회귀의 시험 픽스처(2099-01-01)가 이력에 남아 버전마다 유입됐다
        #   (7벌). 건너뛴 수를 세어 찍는다 — 조용히 버리지 않는다(§3).
        existing = {(str(t), str(d)) for t, d in conn.execute(
            "SELECT ticker, signal_date FROM prediction_cases")}
        # 라운드 442 — 기준일은 **자료 기준일**이다(`premarket.data_day_of` 한 곳). 옛 케이스는 벽시계 날짜로 동결됐고
        #   scripts/rekey_tracker_basis.py 가 자료 기준일로 옮겼다(원래 날짜는 `orig_signal_date`). 옛 줄은 아래에서
        #   **자료 기준일 · 그 줄의 날짜** 어느 쪽으로든 이미 있으면 '기존'이다 — 옮기지 않은 DB(클라우드 사본)에서도 같은
        #   추천을 다시 동결하지 않는다. ⚠️ `orig_signal_date` 는 '기존' 열쇠에 넣지 않는다 — 넣으면 옮겨 간 옛 케이스의
        #   옛 날짜가 그날 자료로 만든 새 추천을 막는다(오늘 아침 판 D(자료 D-1) → 저녁 판 D(자료 D)).
        import premarket as _pm442
        today = date.today()
        skipped_existing = skipped_future = skipped_non_trading = 0
        with open(PM_HISTORY, encoding='utf-8') as f:
            for line in f:
                try:
                    p = json.loads(line)
                except Exception:
                    continue
                if not p.get('symbol') or not p.get('price'):
                    continue
                try:
                    _raw = date.fromisoformat(str(p['date'])[:10])
                    _sig = date.fromisoformat(_pm442.data_day_of(p) or _raw.isoformat())
                except (TypeError, ValueError):
                    continue
                if _sig > today:
                    skipped_future += 1          # 미래 기준일 — 있을 수 없다
                    continue
                if ((str(p['symbol']), _sig.isoformat()) in existing
                        or (str(p['symbol']), _raw.isoformat()) in existing):
                    skipped_existing += 1        # 이미 동결된 추천 — 버전이 바뀌어도 같은 추천
                    continue
                # 라운드 252 — 휴장일 기준일도 있을 수 없다. 개장 전 리포트가 토·일에
                #   만들어져 그 날짜로 들어왔고, 일요일 픽은 토요일 픽과 5/5 같았다
                #   (같은 추천이 두 날짜). 행은 안 지우고 새로 안 만든다 — 세어 찍는다.
                #   '이미 동결됨' 뒤에 둔다 — 이미 있는 것은 날짜가 어떻든 '기존'이다
                #   (첫 판에 앞에 뒀다가 §239 의 심기가 걸렸다).
                # 라운드 442 — 옛 줄(벽시계 날짜)이 휴장일이면 그대로 건너뛴다: 옮기지 않은 DB 에서는 같은 자료의
                #   거래일 판이 다른 날짜로 이미 동결돼 있어 자료 기준일로 새로 만들면 복사본이 된다. 새 줄은 날짜가 곧 자료일.
                if (_pm442.DAY_BASIS != p.get('day_basis') and ct.is_non_trading_date(_raw.isoformat())) \
                        or ct.is_non_trading_date(_sig.isoformat()):
                    skipped_non_trading += 1
                    continue
                decision = RECO_CLASS_TO_DECISION.get(
                    str(p.get('reco_class')), Decision.UNAVAILABLE)
                # 라운드 415 — 도장은 **그 리포트를 만든 버전**이다(동결하는 날의 버전이 아니다)
                _mv415, _rv415, _vsrc415 = case_versions(p, _stamps415, _vs)
                try:
                    case = ct.create_prediction_case(
                        ticker=str(p['symbol']),
                        asset_type=str(p.get('asset_type') or 'STOCK'),
                        signal_date=_sig,                    # 라운드 442 — 자료 기준일
                        model_version=_mv415,
                        rulebook_version=_rv415,
                        decision=decision,
                        total_score=float(p.get('score') or 0),
                        confidence_score=float(
                            (p.get('confidence_band') or {}).get('hit_rate')
                            or 0),
                        reference_price=float(p['price']),
                        entry_price=(float(p['rec_buy'])
                                     if p.get('rec_buy') else None),
                        target_price=(float(p['target'])
                                      if p.get('target') else None),
                        stop_price=(float(p['stop'])
                                    if p.get('stop') else None),
                        holding_days=int(p.get('horizon_days') or 20),
                        market_regime=str(p.get('entry_zone') or '미기록'),
                        strategy_type=str(p.get('reco_class') or ''),
                        # 케이스마다 버전 도장을 찍는다 — 나중에 "이 판단이
                        # 어느 버전에서 나왔나"를 되짚을 수 있어야 한다.
                        # 이전 버전 케이스는 덮어쓰지 않는다.
                        source_payload=V.stamp(dict(p, version_source=_vsrc415)))
                    if ct.save_prediction_case(conn, case):
                        added += 1
                        _src415[_vsrc415] += 1
                        existing.add((str(p['symbol']), _sig.isoformat()))
                        existing.add((str(p['symbol']), _raw.isoformat()))
                except ValueError:
                    continue
        conn.commit()
        print(f"신규 동결 {added}건 · 이미 동결된 추천 건너뜀 {skipped_existing}건 · "
              f"미래 기준일 건너뜀 {skipped_future}건 (R222) · "
              f"휴장일 기준일 건너뜀 {skipped_non_trading}건 (R252) · "
              f"버전 도장 — 리포트에서 {_src415['report']} · 동결 시점 {_src415['freeze_time']} (R415)")
        return added
    return create_new_cases


def make_resolve_open_cases(conn):
    def resolve_open_cases() -> int:
        rows = ct.open_cases(conn)
        if not rows:
            return 0
        import bitemporal_engine as be
        eng = None
        for nm in dir(be):
            if 'Engine' in nm:
                eng = getattr(be, nm)()
                break
        if eng is None:
            return 0
        import prediction_log as plog
        resolved = 0
        cache = {}
        today = datetime.now().strftime('%Y-%m-%d')
        for r in rows:
            if r['signal_date'] >= today:
                continue                       # 오늘 신호는 아직 판정하지 않는다
            if not (r['target_price'] and r['stop_price']):
                continue
            tk = r['ticker']
            if tk not in cache:
                try:
                    # 라운드 333 — 일봉만 쓴다(아래 grade_prediction 이 원장 채점과 같은 함수다).
                    #   적재 함수는 일봉 앞에 실시간 삼중 확인을 부르고 여기는 그 재무 df 를 버린다.
                    cache[tk] = eng.fetch_daily_bars(tk)
                except Exception:
                    cache[tk] = None
            df = cache[tk]
            if df is None:
                continue
            # ⚠️ 라운드 232 — 채점기는 하나다. 여기가 resolve_long_case 로 **따로** 채점했다:
            #   진입 = 권장매수가(rec_buy · 닿은 적 없어도) · 같은 봉 = unresolved · 종가 = adj ·
            #   MDD 는 청산 뒤 봉까지 · 20봉이 다 지나야 확정. 개장 전 절의 '사후 검증'은
            #   prediction_log 로 진입 = 리포트 가격 · 닿으면 즉시 채점해 같은 페이지에서 다른
            #   수를 냈다(실측 2026-09-07 · docs/RESULT_R232_ONE_GRADER.md: 51건 중 39건이
            #   권장매수가 진입 · 그중 18건은 그 가격에 닿은 적이 없다 · 중앙 수익 +10.4% vs
            #   +6.4%). 원장(scripts/calibration_lab.py)과 같은 함수로 같은 규칙: 진입 =
            #   기준가(리포트 가격) · 먼저 닿은 선 · 같은 봉이면 손절 먼저(보수) · 원시가 ·
            #   MDD 는 청산 봉까지. 닿음은 뒤 봉과 무관하게 최종이므로 그 자리에서 확정하고,
            #   안 닿았으면 보유기간이 다 지나야 '미도달'로 확정한다(그 전엔 open).
            g = plog.grade_prediction(
                {'date': r['signal_date'], 'price': float(r['reference_price']),
                 'target': float(r['target_price']), 'stop': float(r['stop_price']),
                 'horizon_days': int(r['holding_days'])}, df)
            if not g:
                continue
            if g['outcome'] == 'OPEN' and not g['matured']:
                continue                       # 보유기간 미경과 · 미도달 — 계속 open
            res = resolution_from_grade(g, target_price=float(r['target_price']),
                                        stop_price=float(r['stop_price']))
            ct.resolve_case(conn, r['case_id'], status=res.status,
                            exit_price=res.exit_price,
                            realized_return=res.realized_return,
                            max_drawdown=res.max_drawdown,
                            reason=res.reason)
            resolved += 1
        conn.commit()
        return resolved
    return resolve_open_cases


def make_refresh_metrics(conn, calib):
    def refresh_metrics() -> None:
        ver = _operating_version(calib)
        sp = calib.get('splits') or {}
        v, b = sp.get('valid') or {}, sp.get('blind') or {}
        bz = (sp.get('buy_zone') or {}).get('blind') or {}
        sig = calib.get('signal_frequency') or {}
        mr.register_model_version(
            conn, model_version=ver, rulebook_version=ver,
            status='operating',
            change_summary='운영 모델 — 리플레이 실측 자동 갱신')
        mr.update_model_metrics(
            conn, ver,
            validation_count=int(v.get('n') or 0),
            blind_count=int(b.get('n') or 0),
            oos_count=int(v.get('n') or 0),
            validation_accuracy=v.get('hit_rate'),
            oos_accuracy=v.get('hit_rate'),
            blind_accuracy=b.get('hit_rate'),
            high_confidence_accuracy=bz.get('hit_rate'),
            expected_return=b.get('avg_return_after_cost'),
            profit_factor=b.get('profit_factor'),
            max_drawdown=b.get('avg_mae'),
            signal_rate=(sig.get('rate_pct') or 0) / 100.0)
        conn.commit()
    return refresh_metrics


def make_detect_issues(conn, calib):
    def detect_issues() -> None:
        sp = calib.get('splits') or {}
        v, b = sp.get('valid') or {}, sp.get('blind') or {}
        bz = (sp.get('buy_zone') or {}).get('blind') or {}
        sig = calib.get('signal_frequency') or {}
        ver = _operating_version(calib)

        # 라운드 256 — 닫기는 재검토일을 본다(issue_tracker.resolve_by_key). 안 닫으면
        #   그 사유를 찍는다 — 조용히 넘기면 "왜 아직 열려 있나"를 아무도 모른다(§3).
        def _resolve(key):
            why = it.resolve_by_key(conn, key)
            if why:
                print(f"  이슈 {key} 닫지 않음 — {why}")

        # 라운드 394 — 이름을 화면과 맞춘다(라운드 393 이 화면에서 '고신뢰'를 '매수권 60점+'로 좁혔다 ·
        #   그 띠의 블라인드 적중이 전체보다 낮아 이름이 계산보다 넓었다). 이미 등록부에 있는 옛 행의
        #   제목은 이력이라 안 바꾼다.
        if (bz.get('n') or 0) < 30:
            it.create_issue(conn, category='validation', severity='medium',
                            title='매수권(60점+) 신호 표본 부족',
                            summary=f"60점+ 블라인드 {bz.get('n', 0)}건 — "
                                    "적중률을 대표 성과로 쓰지 않는다.",
                            related_model=ver, issue_key='validation|high_conf_n')
        else:
            _resolve('validation|high_conf_n')

        # 라운드 262 — 괴리는 화면이 머리로 내는 모집단(매수권 60점+)도 잰다. 종전엔 전체
        #   구간(매수권 밖 포함)으로만 재서 5.4%p < 10 이라 '해소'를 내는 동안 매수권은
        #   14.8%p 였다(2026-09-10 실측 · 69.0 vs 54.2). 문턱 10%p 는 그대로(이미 채택된 규칙) —
        #   어느 모집단이든 넘으면 열고, 요약이 두 수를 같이 말한다(R233). 매수권 표본이
        #   30 미만인 구간이 있으면 그 모집단은 판정하지 않고 찍는다(§3 · 하한 30 재사용).
        # 라운드 394 — 괴리의 판정은 `product_ops.vb_gap` **한 곳**이다. 종전엔 이 자리와 화면의 '주요 이슈'가
        #   같은 괴리를 따로 쟀고 모집단이 달랐다(여기는 매수권+전체 · 화면은 전체만 → 2026-09-30 한쪽은 괴리
        #   14.9%p · 한쪽은 '없음'). 판정 규칙·문턱·표본 하한은 한 글자도 안 바꿨다(옮겼을 뿐이다).
        import product_ops as _po394
        _g394 = _po394.vb_gap(calib)
        if _g394['unmeasured']:
            print(f"  {_g394['unmeasured']}")
        if _g394['crossed']:
            _new394 = it.create_issue(
                conn, category='model', severity='high',
                title='검증-블라인드 괴리 감시',
                summary=' · '.join(_g394['parts'])
                        + f" — {_po394.VB_GAP_PP}%p 넘은 모집단: {'·'.join(_g394['crossed'])}",
                related_model=ver, issue_key='model|vb_gap')
            # 연 것은 찍는다 — 조용히 열리거나 조용히 안 열리면 무엇이 됐는지 아무도 모른다(라운드 394 가
            #   그렇게 20일을 몰랐다 · §3)
            if _new394:
                print(f"  이슈 model|vb_gap 열림 — {' · '.join(_g394['parts'])}")
        elif _g394['gap_all'] is not None or _g394['gap_bz'] is not None:
            _resolve('model|vb_gap')

        # 라운드 256 이 이 이름을 *"매수권(58점+) 케이스의 비율"* 이라 적었는데 **틀렸다**(라운드 394 정정) —
        #   `calibration_lab` 의 `signal_frequency` 는 처음(v2026.08.02)부터 **60점+** 를 센다
        #   (`score >= 60` · 로그 머리도 '매수권 = 점수 60+'). 매수 추천 자체의 비율이 아니라는 R256 의 요지는
        #   그대로다(신규 매수 제목은 원장 251,528건 중 56건 · 0.022%). 이름을 잰 것에 맞춘다.
        if (sig.get('rate_pct') or 100) < 5.0:
            it.create_issue(conn, category='usability', severity='medium',
                            title='매수권(60점+) 발생률 과소',
                            summary=f"매수권 발생률 {sig.get('rate_pct')}% — 매수 추천 "
                                    "자체의 비율이 아니다 · 실용성 점검.",
                            related_model=ver, issue_key='usability|signal_rate')
        else:
            _resolve('usability|signal_rate')

        # ── 조치 관리: 계획 부여 → 경과일 규칙 적용 (3일 방치 금지) ──────
        from improvement import issue_ops as _io
        _io.ensure_schema(conn)
        for _k in ('validation|high_conf_n', 'model|vb_gap',
                   'usability|signal_rate', 'data|index_missing'):
            _io.apply_playbook(conn, _k, version=ver)
        _esc = _io.escalate(conn)
        if _esc:
            print("경과일 규칙 적용:", _esc)
    return detect_issues


def main() -> int:
    initialize_database()
    calib = _load_calib()
    conn = get_connection()
    try:
        result = run_daily_pipeline(
            conn,
            create_new_cases=make_create_new_cases(conn, calib),
            resolve_open_cases=make_resolve_open_cases(conn),
            refresh_metrics=make_refresh_metrics(conn, calib),
            detect_issues=make_detect_issues(conn, calib))
        print(f"run={result.run_id} status={result.status} "
              f"added={result.added_cases} resolved={result.resolved_cases} "
              f"errors={result.error_count}")
        n_open = len(ct.open_cases(conn))
        print(f"결과 확정 대기: {n_open}건")
        return 0 if result.status in ('success', 'partial_success') else 1
    finally:
        conn.close()


if __name__ == '__main__':
    sys.exit(main())
