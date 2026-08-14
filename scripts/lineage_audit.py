# -*- coding: utf-8 -*-
"""
라운드 71 — 결정 계보 감사 (Decision Lineage Audit).

■ 왜 만들었나
  오늘 두 결함을 잡았는데 둘 다 계보 문제였다.
    · 폐기 산식(recommended_buy_price)이 여섯 곳에 살아 있었다 —
      결정은 주석에 적혔고 호출부는 절반만 옮겨졌다
    · 화면이 "211,023원 이하로 사라"고 했는데 그 가격에서도 게이트가
      막고 있었다 — 문구가 게이트를 앞질렀다
  둘 다 "이 숫자가 어디서 왔나"를 자동으로 물었으면 더 빨리 잡힌다.

■ 두 가지를 한다
  ① 정적 감사 (`--static`, 기본) — 소스만 읽는다. 네트워크 없음.
       ⒜ 폐기 키가 표시 경로에 되살아났는가
       ⒝ 신규 매수자 값과 보유자 값이 한 자리에서 섞였는가
       ⒞ 화면이 중앙 판정을 우회해 진입가를 만드는가
       ⒟ 사전등록 후보가 운영 코드에 새어 들어갔는가 (전방 재평가 전 동결)
     **주석·독스트링은 오탐하지 않는다** — ast 로 문자열 표현식 구간과
     `#`·`<!-- -->` 구간을 먼저 걷어낸 뒤 검사한다. 지난 결함들이
     하나같이 "주석엔 적혀 있는데 코드는 안 옮겨진" 형태였으므로,
     주석을 근거로 통과시키면 검사가 결함을 감싸게 된다.

  ② 실행 추적 (`--trace N`) — 실제 종목 N개를 파이프라인에 흘려
     화면에 나갈 값들의 **출처 키**를 기록하고 정합을 재계산한다.
       · 손절 < 진입 < 목표 가 실제로 성립하는가
       · 손익비가 (목표−진입)/(진입−손절) 과 맞는가 — 다른 엔진의
         옛 손익비가 남아 있으면 여기서 어긋난다
       · 진입가가 축(price_axes)에서 왔는가 폴백에서 왔는가
       · 신규 값과 보유자 값이 같은 숫자로 겹치는가
     결과는 data/lineage_audit.json 에 남긴다.

■ 전방 재평가 전 동결 준수 (날짜는 forward_eval 에서만 읽는다)
  감사만 한다. 점수·게이트·문턱을 바꾸지 않는다.

    C:/Python314/python.exe scripts/lineage_audit.py
    C:/Python314/python.exe scripts/lineage_audit.py --trace 12
"""
import ast
import io
import json
import os
import sys
import warnings

warnings.filterwarnings('ignore')
PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

import forward_eval as _fe        # 재평가일 단일 출처 (라운드 78)  # noqa: E402

#: ⚠️ 라운드 93 — 여기에 '8/23' 이 다섯 군데 박혀 있었다. 라운드 78 이
#:   재평가일을 11/16 으로 **정정한 뒤에도** 이 파일만 옛 날짜를 화면과
#:   data/lineage_audit.json 에 계속 찍고 있었다.
#:
#:   회귀 §135 가 못 잡은 이유가 더 나쁘다 — 검사할 파일을 **손으로 다섯
#:   개 적어 뒀고**, 정작 그 검사가 쓰는 이 모듈이 목록에 없었다.
#:   검사가 자기 자신은 안 본 것이다. 이제 §135 는 프로젝트의 .py 를
#:   전부 훑는다.
#:
#:   날짜를 여기서 만들지 않는다. 못 읽으면 지어내지 않고 그렇게 적는다.
FREEZE = _fe.eval_date() or '재평가일 미기록'


def _utf8_stdout():
    """스크립트로 돌 때만 stdout 을 UTF-8 로 맞춘다.

    모듈 수준에서 `sys.stdout = TextIOWrapper(sys.stdout.buffer, ...)` 를
    하면 이 파일을 **임포트하는 쪽**(회귀 §107)의 stdout 까지 갈아끼운다.
    옛 래퍼가 수거될 때 버퍼를 닫아 버려 그 뒤 출력이 통째로 죽는다.
    reconfigure 는 같은 객체를 고치므로 그 위험이 없다.
    """
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

#: 표시 경로 — 사용자가 보는 숫자를 만드는 파일
DISPLAY = ('web_app.py', 'ui_kit.py', 'chart_pro.py', 'gaeum_chat.py',
           'trade_plan.py', 'premarket.py', 'report_generator.py',
           'next_action.py', 'verdict_core.py', 'case_layers.py')

#: 폐기 키 — 표시 경로에서 '오늘 살 가격'으로 쓰면 안 되는 것
RETIRED = {
    'recommended_buy_price':
        '적정가 × 안전마진 (라운드 25 폐기) — 장기 가치 참고선이지 '
        '오늘의 실행가가 아니다. 장기 라벨이 붙은 자리에서만 허용',
}
#: 폐기 키가 있어도 되는 자리 — 라벨이 **코드나 화면에** 붙었을 때만.
#: 두 가지만 근거로 친다:
#:   ⓐ 식별자 이름 (value_floor / value_ref) — 다음 사람이 읽는다
#:   ⓑ 사용자에게 실제로 렌더되는 문구 ("장기 가치 참고선" 등)
#: **주석은 근거가 못 된다.** 폐기 산식이 여섯 곳에 살아남은 이유가
#: 정확히 "주석엔 적혀 있었다" 였다 — 주석을 근거로 통과시키면
#: 검사가 결함을 감싸게 된다. prose_lines() 가 주석을 먼저 걷어낸다.
RETIRED_OK_MARKS = ('value_floor', 'value_ref', 'long_term_ref',
                    '장기 가치 참고선', '장기 참고선',
                    '오늘의 매수가가 아니', '오늘의 실행가가 아니')

#: 신규/보유자 키 — 한 자리에서 이름표 없이 섞이면 사고 (라운드 30)
NEW_KEYS = ('entry_target_1st', 'entry_stop_price', 'entry_pullback_price',
            'new_target', 'new_stop')
HOLD_KEYS = ('target_tech_1st', 'stop_loss_price', 'hold_trim', 'hold_stop')

#: 사전등록 후보 — 전방 검증(FREEZE) 전 운영 코드에 들어가면 안 된다
CANDIDATES = ('regime_routing_r55', 'entry_engine_r57', 'breakout_flags_r64',
              'ROUTING_TABLE', 'BREAKOUT_BYPASS')
OPS_FILES = ('quant_indicators.py', 'verdict_core.py', 'regime_policy.py',
             'next_action.py', 'price_axes.py')

#: 왕복 비용 — 수수료 0.03 + 세금 0.20 + 슬리피지 0.18 (원장 연구와 동일)
COST_PCT = 0.36


def read(name):
    p = os.path.join(PROJ, name)
    return open(p, encoding='utf-8').read() if os.path.exists(p) else None


def prose_lines(src):
    """산문(주석·독스트링·HTML 주석)인 줄 번호 집합.

    주석 안의 결정 기록을 검사 근거로 삼으면 안 된다 — 폐기 산식이
    여섯 곳에 살아남은 이유가 정확히 '주석엔 적혀 있었다' 였다.
    """
    out = set()
    lines = src.splitlines()
    for i, ln in enumerate(lines, 1):
        if ln.lstrip().startswith('#'):
            out.add(i)
    # 독스트링·바깥에 떠 있는 문자열 표현식 (설명 블록)
    try:
        tree = ast.parse(src)
    except SyntaxError:
        tree = None
    if tree is not None:
        for node in ast.walk(tree):
            if (isinstance(node, ast.Expr)
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)):
                for i in range(node.lineno, (node.end_lineno or
                                             node.lineno) + 1):
                    out.add(i)
    # f-string 안의 HTML 주석 — 화면에 안 나가는 설명이다
    depth = 0
    for i, ln in enumerate(lines, 1):
        opened = ln.count('<!--')
        closed = ln.count('-->')
        if depth > 0 or opened:
            out.add(i)
        depth = max(0, depth + opened - closed)
    return out


def code_lines(name):
    """(줄번호, 줄) — 산문을 걷어낸 실제 코드만."""
    src = read(name)
    if src is None:
        return []
    skip = prose_lines(src)
    return [(i, ln) for i, ln in enumerate(src.splitlines(), 1)
            if i not in skip and ln.strip()]


# ══════════════════════════════════════════════════════════════════
# ① 정적 감사
# ══════════════════════════════════════════════════════════════════
def static_audit():
    issues = []

    print('■ ⒜ 폐기 키가 표시 경로에 되살아났는가')
    hit_a = 0
    for f in DISPLAY:
        rows = code_lines(f)
        idx = {i: ln for i, ln in rows}
        for i, ln in rows:
            for key, why in RETIRED.items():
                if key not in ln:
                    continue
                # 같은 줄 또는 바로 위 3줄에 장기 라벨이 붙어 있으면 정당
                ctx = ' '.join(idx.get(j, '') for j in range(i - 3, i + 2))
                if any(m in ctx for m in RETIRED_OK_MARKS):
                    continue
                hit_a += 1
                issues.append(f'{f}:{i} 폐기 키 {key} — {why}')
                print(f'  [문제] {f}:{i}  {ln.strip()[:66]}')
    if not hit_a:
        print('  없음 — 폐기 키는 장기 참고선 라벨이 붙은 자리에만 있다')

    print('\n■ ⒝ 신규 매수자 값과 보유자 값이 이름표 없이 섞였는가')
    hit_b = 0
    for f in DISPLAY:
        for i, ln in code_lines(f):
            n_hit = [k for k in NEW_KEYS if k in ln]
            h_hit = [k for k in HOLD_KEYS if k in ln]
            if not (n_hit and h_hit):
                continue
            # 두 기준을 나란히 두되 **누구의 값인지 적었다면** 정당하다
            if any(m in ln for m in ('보유자', '신규', 'hold_', 'new_')):
                continue
            hit_b += 1
            issues.append(f'{f}:{i} 신규·보유자 혼용 ({n_hit[0]} + {h_hit[0]})')
            print(f'  [문제] {f}:{i}  {ln.strip()[:66]}')
    if not hit_b:
        print('  없음 — 두 기준이 이름표 없이 섞이지 않는다')

    print('\n■ ⒞ 화면이 중앙 판정을 우회해 진입가를 만드는가')
    hit_c = 0
    for f in ('web_app.py', 'ui_kit.py', 'chart_pro.py', 'gaeum_chat.py'):
        for i, ln in code_lines(f):
            if "four_scores.get('entry_pullback_price')" in ln:
                hit_c += 1
                issues.append(f'{f}:{i} 중앙 판정 우회 — CORE.pullback_zone')
                print(f'  [문제] {f}:{i}  {ln.strip()[:66]}')
    if not hit_c:
        print('  없음 — 진입가는 CORE 를 거친다')

    print(f'\n■ ⒟ 사전등록 후보가 운영 코드에 새어 들어갔는가 ({FREEZE} 동결)')
    hit_d = 0
    for f in OPS_FILES:
        for i, ln in code_lines(f):
            for c in CANDIDATES:
                if c in ln:
                    hit_d += 1
                    issues.append(f'{f}:{i} 후보 {c} 가 운영 코드에')
                    print(f'  [문제] {f}:{i}  {ln.strip()[:66]}')
    if not hit_d:
        print('  없음 — 후보는 운영 코드에 없다 (전방 검증 전 동결 유지)')
    return issues


# ══════════════════════════════════════════════════════════════════
# ② 실행 추적 — 실제 종목을 흘려 정합을 재계산한다
# ══════════════════════════════════════════════════════════════════
#: 화면에 나가는 값 → 그 값을 만든 출처 키. 여기 없는 값이 화면에
#: 나가면 계보가 끊긴 것이다.
LINEAGE = {
    'pullback_zone': 'four_scores.entry_pullback_price',
    'new_target': 'four_scores.entry_target_1st',
    'new_stop': 'four_scores.entry_stop_price',
    'rr': 'four_scores.entry_rr',
    'hold_trim': 'four_scores.target_tech_1st',
    'hold_stop': 'four_scores.stop_loss_price',
    'breakout_price': 'next_action.breakout_price | four_scores.high_20d',
    'current_price': 'realtime_price | four_scores.current_price',
}


def trace(n_tickers):
    import bitemporal_engine as be
    import quant_indicators as qi
    import verdict_core as vc
    from bitemporal_engine import STOCK_METRICS_DB, STOCK_NAME_MAP

    # 유니버스는 앱이 실제로 스냅샷을 만들 수 있는 종목뿐이다. 두 출처를
    # 합친다 — STOCK_METRICS_DB(국내 19종)만 쓰면 조용히 잘린다.
    pool = {s for s in (STOCK_METRICS_DB or {})
            if str(s).endswith(('.KS', '.KQ'))}
    pool |= {str(v) for v in (STOCK_NAME_MAP or {}).values()
             if str(v).endswith(('.KS', '.KQ'))}
    universe = sorted(pool)
    tickers = universe[:max(1, n_tickers)]
    if n_tickers > len(universe):
        # 요청보다 적으면 **밝힌다.** 조용히 자르면 "다 봤다"로 읽힌다.
        print(f'  (요청 {n_tickers}종목 · 사용 가능 {len(universe)}종목 — '
              f'유니버스가 그만큼뿐이다)')
    eng = be.BitemporalEngine()
    q = qi.QuantIndicatorsEngine()
    t_ref = be.resolve_analysis_date().strftime('%Y-%m-%d')
    rows, bad = [], []
    for tk in tickers:
        try:
            snap = q.run_full_pipeline(tk, t_ref, b_engine=eng,
                                       rho_cutoff=0.80)
        except Exception as e:                                 # noqa: BLE001
            rows.append(dict(ticker=tk, ok=False, why=f'스냅샷 실패: {e}'))
            continue
        if not snap:
            rows.append(dict(ticker=tk, ok=False, why='스냅샷 없음'))
            continue
        fs = snap.get('four_scores') or {}
        vd = q.build_final_verdict(snap)
        px = fs.get('current_price')
        core = vc.build(fs, verdict=vd, price_axes=fs.get('price_axes'),
                        realtime_price=px)

        ent = core.get('pullback_zone')
        tgt, stp, rr = (core.get('new_target'), core.get('new_stop'),
                        core.get('rr'))
        ax = (fs.get('price_axes') or {}).get('entry') or {}
        src = ('price_axes.entry' if ax.get('available')
               else 'fallback:entry_pullback_price')

        r = dict(ticker=tk, ok=True, entry_src=src, entry=ent, target=tgt,
                 stop=stp, rr=rr, actionable=bool(core.get('actionable')),
                 incoherence=list(core.get('incoherence') or []))
        # 정합 — 손절 < 진입 < 목표
        if ent and stp is not None and stp >= ent:
            r['fault'] = f'손절 {stp:,.0f} ≥ 진입 {ent:,.0f}'
        elif ent and tgt is not None and tgt <= ent:
            r['fault'] = f'목표 {tgt:,.0f} ≤ 진입 {ent:,.0f}'
        # 손익비 재계산 — 다른 엔진의 옛 값이 남아 있으면 어긋난다
        if ent and tgt and stp and stp < ent < tgt and rr:
            calc = round((tgt - ent) / (ent - stp), 2)
            r['rr_calc'] = calc
            if abs(calc - rr) > 0.15:
                r['fault'] = (f'손익비 표시 {rr} vs 재계산 {calc} — '
                              f'다른 진입 기준이 섞였다')
        # 신규 값과 보유자 값이 같은 숫자로 겹치는가
        if (core.get('new_stop') is not None
                and core.get('new_stop') == core.get('hold_stop')):
            r['fault'] = '신규 손절 = 보유자 손절 (키 분리가 무너졌다)'
        if r.get('fault'):
            bad.append(r)
        rows.append(r)

    ok = [r for r in rows if r.get('ok')]
    ax_src = sum(1 for r in ok if r.get('entry_src') == 'price_axes.entry')
    print(f'\n■ 실행 추적 — 종목 {len(rows)} · 스냅샷 성공 {len(ok)}')
    print(f'  진입가 출처: 축 {ax_src} · 폴백 {len(ok) - ax_src}')
    print(f'  정합 위반: {len(bad)}건')
    for r in bad[:10]:
        print(f'    [문제] {r["ticker"]} — {r["fault"]}')
    if not bad and ok:
        print('    없음 — 손절<진입<목표 · 손익비 재계산 전부 일치')

    # 못 잰 것을 통과로 적지 않는다 (§3). 첫 실행에서 함수 이름이 틀려
    # 10건 전부 실패했는데 감사는 "전부 통과"라고 찍었다 — 감사가 스스로
    # 거짓 안심을 준 셈이다. 실패는 사유와 함께 결함으로 올린다.
    if not ok:
        bad = bad + [dict(ticker='(추적 불가)',
                          fault='잰 종목이 0건이다 — 통과가 아니라 미측정')]
    fails = [r for r in rows if not r.get('ok')]
    if fails:
        whys = sorted({str(r.get('why'))[:90] for r in fails})
        print(f'  스냅샷 실패 {len(fails)}건 — 감사하지 못한 종목이다:')
        for w in whys[:5]:
            print(f'    · {w}')
        bad = bad + [dict(ticker='(추적 불가)',
                          fault=f'스냅샷 {len(fails)}/{len(rows)}건 실패 — '
                                f'{whys[0]}')]

    dst = os.path.join(PROJ, 'data', 'lineage_audit.json')
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, 'w', encoding='utf-8') as f:
        json.dump(dict(made='2026-08-10', lineage=LINEAGE,
                       n_traced=len(rows), n_ok=len(ok),
                       n_axis_src=ax_src, faults=bad, rows=rows,
                       note='감사 전용 — 점수·게이트를 바꾸지 않는다. '
                            '표시되는 값이 전부 CORE 한 곳에서 나오는지, '
                            '정합과 손익비가 같은 진입 기준으로 계산되는지 '
                            f'확인한다 ({FREEZE} 동결 준수).'),
                  f, ensure_ascii=False, indent=1)
    print(f'  저장: {dst}')
    return bad


# ══════════════════════════════════════════════════════════════════
# ③ 원장 정합 훑기 — 과거에 실제로 나간 값들이 정합했는가
# ══════════════════════════════════════════════════════════════════
def ledger_sweep():
    """원장 전건에서 손절 < 기준가 < 목표 가 성립했는지 본다.

    실행 추적은 오늘 25종목만 본다 — 유니버스가 그만큼뿐이다. 그런데
    라운드 30 사고(GS 손절이 매수가 위, NAVER 목표가 매수가 아래)는
    **과거에 실제로 나간 값**의 문제였다. 원장에는 60,462건의 기준가·
    목표·손절이 남아 있으므로, 같은 사고가 있었는지 전건으로 확인한다.

    감사 전용 — 점수·게이트를 바꾸지 않는다.
    """
    import json as _j
    path = os.path.join(PROJ, '.portfolio', 'virtual_graded.jsonl')
    if not os.path.exists(path):
        # 훑어 달라고 불러 놓고 원장이 없으면 그것은 통과가 아니다.
        # 조용히 넘어가면 "정합 위반 0건"으로 읽힌다.
        print('\n■ 원장 정합 훑기 — 원장 파일이 없다. 통과가 아니라 미측정이다.')
        return ['원장이 없어 정합을 재지 못했다 (.portfolio/'
                'virtual_graded.jsonl)']
    n = 0
    bad_stop, bad_tgt, degen = [], [], []
    rr_vals, ups, dns = [], [], []
    hit = {}                       # split -> [적중, 전체] (매수권 58점+)
    with open(path, encoding='utf-8') as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = _j.loads(ln)
            except Exception:                                  # noqa: BLE001
                continue
            px, tg, st = r.get('price'), r.get('target'), r.get('stop')
            if not all(isinstance(v, (int, float)) for v in (px, tg, st)):
                continue
            n += 1
            if st >= px:
                bad_stop.append((r.get('ticker'), r.get('date'), px, st))
            if tg <= px:
                bad_tgt.append((r.get('ticker'), r.get('date'), px, tg))
            if tg == px or st == px:
                degen.append((r.get('ticker'), r.get('date')))
            if st < px < tg and px > 0:
                rr_vals.append((tg - px) / (px - st))
                ups.append((tg / px - 1) * 100)
                dns.append((1 - st / px) * 100)
            # 매수권(58점+) 실적중 — 손익분기선과 견주려고 함께 센다
            if (r.get('outcome') != 'OPEN'
                    and float(r.get('score') or 0) >= 58.0):
                sp = str(r.get('split') or '?')
                cell = hit.setdefault(sp, [0, 0])
                cell[1] += 1
                if r.get('success'):
                    cell[0] += 1

    print(f'\n■ 원장 정합 훑기 — 기록된 판단 {n:,}건 전부')
    print(f'  손절이 기준가 이상: {len(bad_stop):,}건')
    print(f'  목표가 기준가 이하: {len(bad_tgt):,}건')
    print(f'  목표·손절이 기준가와 같음(퇴화): {len(degen):,}건')
    for lbl, lst in (('손절≥기준가', bad_stop), ('목표≤기준가', bad_tgt)):
        for t, d, px, v in lst[:3]:
            print(f'    [문제] {lbl} {t} {d} — 기준 {px:,.0f} vs {v:,.0f}')
    be_pre = be_post = rr_med = up_med = dn_med = None
    if rr_vals:
        rr_vals.sort()
        q = lambda p: rr_vals[int(len(rr_vals) * p)]            # noqa: E731
        rr_med = q(0.5)
        print(f'  손익비 분포 — 최소 {rr_vals[0]:.2f} · 25% {q(0.25):.2f} · '
              f'중앙 {rr_med:.2f} · 75% {q(0.75):.2f} · 최대 {rr_vals[-1]:.2f}')
        # ── 적중률을 어떻게 읽어야 하는가 ────────────────────────────
        # 손익비가 사실상 상수(0.70)다. 그러면 "적중률 60%" 가 좋은
        # 숫자인지 아닌지는 **손익분기 적중률과 견줘야만** 알 수 있다.
        #   손익분기 p* = (손절폭 + 비용) / (목표폭 + 손절폭)
        # 새 문턱을 만드는 게 아니라 이미 기록된 폭에서 도출되는 값이다.
        ups.sort()
        dns.sort()
        up_med, dn_med = ups[len(ups) // 2], dns[len(dns) // 2]
        be_pre = dn_med / (up_med + dn_med) * 100
        be_post = (dn_med + COST_PCT) / (up_med + dn_med) * 100
        print(f'  기록된 폭 중앙값 — 목표 +{up_med:.2f}% · 손절 −{dn_med:.2f}%')
        print(f'  손익분기 적중률 — 비용 전 {be_pre:.1f}% · '
              f'비용 후({COST_PCT}%) {be_post:.1f}%')
        print('    → 이 원장의 적중률은 이 선과 견줘 읽어야 한다. '
              '선 아래면 적중률이 높아 보여도 지는 구조다.')
        print('  매수권(58점+) 실적중 vs 비용 후 손익분기:')
        for sp in ('train', 'valid', 'blind'):
            k, tot = hit.get(sp, [0, 0])
            if not tot:
                continue
            h = k / tot * 100
            gap = h - be_post
            print(f'    {sp:6s} n {tot:>6,} · 적중 {h:5.2f}% · '
                  f'{gap:+6.2f}%p {"위" if gap > 0 else "아래"}')
        hits = {sp: (round(v[0] / v[1] * 100, 2) if v[1] else None)
                for sp, v in hit.items()}
        above = [sp for sp, h in hits.items() if h is not None and h > be_post]
        print(f'    → 손익분기선 위인 구간: '
              f'{", ".join(above) if above else "없음"}')
    if not (bad_stop or bad_tgt or degen):
        print('  위반 없음 — 기록된 모든 판단이 손절<기준가<목표 를 지켰다')

    dst = os.path.join(PROJ, 'data', 'lineage_ledger_sweep.json')
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, 'w', encoding='utf-8') as f:
        _j.dump(dict(made='2026-08-10', n_checked=n,
                     n_stop_violation=len(bad_stop),
                     n_target_violation=len(bad_tgt),
                     n_degenerate=len(degen),
                     rr_min=(round(rr_vals[0], 3) if rr_vals else None),
                     rr_median=(round(rr_med, 3) if rr_med else None),
                     rr_max=(round(rr_vals[-1], 3) if rr_vals else None),
                     target_pct_median=(round(up_med, 3) if up_med else None),
                     stop_pct_median=(round(dn_med, 3) if dn_med else None),
                     cost_pct=COST_PCT,
                     breakeven_hit_pre_cost=(round(be_pre, 2) if be_pre
                                             else None),
                     breakeven_hit_post_cost=(round(be_post, 2) if be_post
                                              else None),
                     buy_zone_hit=dict(
                         (sp, dict(n=v[1],
                                   hit=(round(v[0] / v[1] * 100, 2)
                                        if v[1] else None)))
                         for sp, v in sorted(hit.items())),
                     samples=dict(stop=bad_stop[:20], target=bad_tgt[:20]),
                     note='감사 전용 — 원장에 기록된 기준가·목표·손절의 '
                          '정합만 본다. 점수·게이트를 바꾸지 않는다. '
                          '손익분기 적중률은 새 문턱이 아니라 기록된 '
                          '폭에서 도출되는 값이다 — 적중률을 읽는 기준선.'),
                f, ensure_ascii=False, indent=1)
    print(f'  저장: {dst}')

    out = []
    if bad_stop:
        out.append(f'원장 손절≥기준가 {len(bad_stop):,}건')
    if bad_tgt:
        out.append(f'원장 목표≤기준가 {len(bad_tgt):,}건')
    if degen:
        out.append(f'원장 퇴화 레벨 {len(degen):,}건')
    if n == 0:
        out.append('원장에서 레벨을 한 건도 읽지 못했다 — 통과가 아니라 미측정')
    return out


def main():
    issues = static_audit()
    if '--ledger' in sys.argv or '--all' in sys.argv:
        issues += ledger_sweep()
    if '--trace' in sys.argv:
        i = sys.argv.index('--trace')
        n = int(sys.argv[i + 1]) if len(sys.argv) > i + 1 else 12
        issues += [f'{r["ticker"]} {r["fault"]}' for r in trace(n)]
    print(f'\n■ 결과: {("문제 " + str(len(issues)) + "건") if issues else "전부 통과"}')
    for x in issues[:20]:
        print(f'  · {x}')
    return 1 if issues else 0


if __name__ == '__main__':
    _utf8_stdout()
    sys.exit(main())
