# -*- coding: utf-8 -*-
"""
기존 원장에 하위점수를 채운다 (라운드 50).

■ 왜 필요한가
  calibration_lab 기록부에 q_stock_quality 등을 추가했지만, 체크포인트가
  이미 끝난 (종목, 날짜)를 건너뛴다. 그래서 **새로 도는 건에만** 필드가
  생기고 기존 60,462건은 비어 있다. 그 상태로 분석하면 신규분만 보는
  편향된 부분표본이 된다 (라운드 44-1b 에서 똑같은 사고를 냈다).

■ 무엇을 하나
  기존 행을 읽어 같은 (종목, 기준일)로 리플레이를 다시 돌리고, **채점
  결과는 건드리지 않고** 하위점수 필드만 덧붙인다.

    · 이미 채워진 행은 건너뛴다 (재실행 안전)
    · 결과 필드(success·return_pct·outcome…)는 **읽지도 쓰지도 않는다**
    · 중간 저장 — 언제 끊어도 이어서 돈다

■ 범위
  기본값은 **개발 구간의 매수권(58+)** 만. 순위 분석이 그 구간에서만
  이뤄지기 때문이고, 봉인된 블라인드는 애초에 읽지 않는다.

    C:/Python314/python.exe scripts/backfill_subscores.py [--limit N] [--all]

■ 병렬 (라운드 53)
  단일 프로세스가 한 코어의 30%밖에 못 쓰고 있어 15,726건에 6.7시간이
  걸렸다. 대상을 조각으로 나눠 동시에 돌린다.

    --shard i/n   sorted(todo) 를 n등분한 i번째만 처리 (0부터)
    --out NAME    .portfolio/NAME 에 기록 (조각마다 다른 파일)

  **조각마다 파일을 갈라야 한다.** 여러 프로세스가 한 파일에 append 하면
  줄이 섞여 깨질 수 있다. 완료 판정은 `subscore_patch*.jsonl` 전부를
  읽어서 하므로, 조각을 어떻게 나누든 이미 끝난 건은 다시 돌지 않는다.
"""
import glob
import io
import json
import os
import sys
import time
import warnings
import zlib

warnings.filterwarnings('ignore')
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)


def _utf8_stdout():
    """스크립트로 돌 때만 stdout 을 UTF-8 로 맞춘다.

    모듈 수준에서 새 TextIOWrapper 로 갈아끼우면 임포트하는 쪽의 stdout
    까지 바뀌고, 옛 래퍼가 수거될 때 버퍼를 닫아 그 뒤 출력이 죽는다.
    이 저장소에서 같은 함정을 네 번 밟았다 (lineage_audit · snapshot_guard
    · backup_research_data · 여기). reconfigure 는 같은 객체를 고친다.
    """
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import bitemporal_engine as be                               # noqa: E402
import quant_indicators as qi                                # noqa: E402

P = os.path.join(PROJ, '.portfolio')
LEDGER = os.path.join(P, 'virtual_graded.jsonl')
PATCH = os.path.join(P, 'subscore_patch.jsonl')
THR = 58.0
SEALED = 'blind'

#: 채울 필드 — 라운드 50b 에서 7/7 실재를 확인한 것만
FIELDS = (('q_stock_quality', 'stock_quality_score'),
          ('q_trading_timing', 'trading_timing_score'),
          ('q_risk_safety', 'risk_safety_score'),
          ('q_opportunity', 'opportunity_score'),
          ('q_execution', 'execution_score'),
          ('q_confidence', 'analysis_confidence'),
          ('q_strategy_quality', 'strategy_quality_score'))


def load_done():
    """완료 집합 — 조각 파일을 전부 읽는다.

    한 조각만 읽으면 다른 조각이 끝낸 건을 다시 돌게 된다.
    """
    done = set()
    for path in sorted(glob.glob(os.path.join(P, 'subscore_patch*.jsonl'))):
        with open(path, encoding='utf-8') as f:
            for ln in f:
                try:
                    r = json.loads(ln)
                    done.add((r['ticker'], r['date']))
                except Exception:                            # noqa: BLE001
                    continue
    return done


def load_sector_done():
    """**섹터를 가진** (종목,날짜) 집합 — 두 곳을 다 본다.

    원장 행에 직접 있는 것과 패치 파일에 있는 것을 합친다. 라운드 72
    확장분은 축적할 때 원장에 직접 쓰므로 패치만 보면 절반을 놓친다
    (라운드 73 에서 그 착오로 '섹터 96.8% 미기록' 이라 잘못 보고했다).
    """
    out = set()
    for path in sorted(glob.glob(os.path.join(P, 'subscore_patch*.jsonl'))):
        with open(path, encoding='utf-8', errors='replace') as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    q = json.loads(ln)
                except Exception:                              # noqa: BLE001
                    continue
                if q.get('sector'):
                    out.add((str(q.get('ticker')), str(q.get('date'))[:10]))
    with open(LEDGER, encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:                                  # noqa: BLE001
                continue
            if r.get('sector'):
                out.add((str(r.get('ticker')), str(r.get('date'))[:10]))
    return out


def main():
    limit = 10 ** 9
    if '--limit' in sys.argv:
        limit = int(sys.argv[sys.argv.index('--limit') + 1])
    want_all = '--all' in sys.argv
    #: 섹터만 다시 채운다 — 엔진의 코스닥 접미사 결함(라운드 74)을 고친 뒤,
    #: 이미 쌓인 케이스에 그 수정을 반영하기 위한 모드.
    sector_only = '--sector-only' in sys.argv

    out_path = PATCH
    if '--out' in sys.argv:
        name = sys.argv[sys.argv.index('--out') + 1]
        # ⚠️ 라운드 74 — 산출 파일을 'subscore_sector_a.jsonl' 로 지었다가
        #   96,218건이 통째로 묻혔다. **읽는 쪽 glob 이 전부**
        #   `subscore_patch*.jsonl` 인데 이름이 안 맞아 아무도 안 봤다
        #   (sample_audit · weakness_map · load_done · load_sector_done ·
        #    백업 화이트리스트 · 스냅샷 가드 — 여섯 곳).
        #   이름 규칙을 사람 기억에 맡기지 않는다. 안 맞으면 여기서 막는다.
        if not name.startswith('subscore_patch'):
            print(f"산출 파일 이름은 'subscore_patch' 로 시작해야 한다 "
                  f"(받은 값: {name}). 읽는 쪽 glob 이 그 패턴이라, 다른 "
                  f"이름으로 쓰면 채운 데이터를 아무도 못 본다.")
            return 2
        out_path = os.path.join(P, name)
    shard = shards = None
    if '--shard' in sys.argv:
        raw = sys.argv[sys.argv.index('--shard') + 1]
        shard, shards = (int(x) for x in raw.split('/'))
        if not 0 <= shard < shards:
            print(f'조각 번호가 범위를 벗어남: {raw}')
            return 2

    rows = []
    with open(LEDGER, encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                try:
                    rows.append(json.loads(ln))
                except Exception:                            # noqa: BLE001
                    pass
    print(f'원장 {len(rows):,}건')

    if sector_only:
        # ── 섹터만 다시 채우는 모드 (라운드 74) ─────────────────────────
        #   코스닥 종목의 섹터가 통째로 비어 있었다. 원인은 엔진의 접미사
        #   결함이었고 고쳤지만, **이미 쌓인 케이스의 섹터는 그때 계산된
        #   값이라 코드를 고쳐도 안 바뀐다.** 다시 돌려야 한다.
        #
        #   여기서 '완료'의 뜻이 다르다: 패치 행이 있느냐가 아니라
        #   **섹터가 있느냐**다. 패치 행은 있는데 sector=None 인 건들이
        #   바로 다시 돌아야 하는 대상이므로, load_done() 을 쓰면
        #   영영 건너뛴다.
        has_sec = load_sector_done()
        todo = sorted({(str(r.get('ticker')), str(r.get('date'))[:10])
                       for r in rows
                       if (str(r.get('ticker')),
                           str(r.get('date'))[:10]) not in has_sec})
        print(f'섹터 없는 건 {len(todo):,}건 · 이미 섹터 있음 '
              f'{len(has_sec):,}건')
    else:
        todo = []
        for r in rows:
            if not want_all:
                if r.get('split') == SEALED:
                    continue
                if float(r.get('score') or 0) < THR:
                    continue
            if r.get('q_stock_quality') is not None:
                continue                      # 이미 채워짐
            todo.append((str(r.get('ticker')), str(r.get('date'))[:10]))
        todo = sorted(set(todo))
        done = load_done()
        todo = [x for x in todo if x not in done]
        print(f'채울 대상 {len(todo):,}건 '
              f'({"전체" if want_all else "개발 구간 매수권만"}) · '
              f'이미 완료 {len(done):,}건')
    if shards:
        # ⚠️ 라운드 73 — 여기가 `todo[shard::shards]` 였다.
        #   stride 분할은 **모든 워커가 똑같은 todo 목록을 볼 때만** 성립한다.
        #   6개를 3개씩 나눠 띄웠더니 두 번째 묶음이 (그 사이 채워진 만큼
        #   줄어든) 다른 목록을 보고 갈랐고, 조각이 겹쳐 같은 건을 두 번
        #   돌았다 — 실측 중복 3,665건. 유니버스 캐시에서 고친 것과 같은
        #   함정이다: 분할의 입력이 워커마다 다르면 분할이 아니다.
        #
        #   키 자체의 안정 해시로 가른다. 언제 띄우든, todo 가 무엇이든
        #   같은 (종목,날짜)는 항상 같은 조각에 간다.
        todo = [x for x in todo
                if zlib.crc32(f'{x[0]}|{x[1]}'.encode()) % shards == shard]
        print(f'조각 {shard}/{shards} → {len(todo):,}건 · 기록 '
              f'{os.path.basename(out_path)} (안정 해시 분할)')
    if not todo:
        print('채울 것이 없다.')
        return 0

    q = qi.QuantIndicatorsEngine()
    eng = be.BitemporalEngine()
    t0, ran, fail = time.time(), 0, 0
    with open(out_path, 'a', encoding='utf-8') as out:
        for tk, d in todo:
            if ran >= limit:
                print(f'  한도 {limit}건 도달 — 이어서 실행 가능')
                break
            try:
                snap = q.run_full_pipeline(tk, d, b_engine=eng,
                                           rho_cutoff=0.80)
                fs = snap['four_scores']
                patch = {'ticker': tk, 'date': d}
                for lk, ek in FIELDS:
                    patch[lk] = fs.get(ek)
                patch['sector'] = (snap.get('val_eval') or {}).get('sector')
                out.write(json.dumps(patch, ensure_ascii=False) + '\n')
                out.flush()
                ran += 1
                if ran % 25 == 0:
                    el = time.time() - t0
                    print(f'  {ran}/{len(todo)}건 · {el:,.0f}s · '
                          f'건당 {el / ran:.1f}s · 실패 {fail}')
            except Exception as exc:                         # noqa: BLE001
                fail += 1
                if fail <= 5:
                    print(f'  [실패] {tk} @ {d} — {type(exc).__name__}')
    print(f'\n완료 {ran:,}건 · 실패 {fail}건')
    print(f'저장: {out_path}')
    print('  원장 병합은 merge 단계에서 한다 — 채점 결과는 건드리지 않는다.')
    return 0


if __name__ == '__main__':
    _utf8_stdout()
    sys.exit(main())
