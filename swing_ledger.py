# -*- coding: utf-8 -*-
"""
스윙 자동매매 장부 (라운드 446) — 이 PC 의 `.portfolio/swing.db` 하나. **지우지 않고 덧붙인다.**

계좌 잔고·평단·주문은 개인 자료다(§9) — `.portfolio/` 는 gitignored 이고, 클라우드 업로드·백업은 화이트리스트라 이 파일을
고르지 않는다(백업의 DENY 에도 이름을 적는다). 화면과 워커가 같은 장부를 읽는다(§4) — 상태를 두 곳에 두지 않는다.

표 — 전부 덧붙이기만 한다(지금 상태는 마지막 사건으로 읽는다):
  settings_events   설정 사건 (모드 · 위험 한도 · 긴급정지 · 실전 잠금 해제) — 마지막 값이 지금 값
  plans             그날 계획(바뀌지 않는다 · plan_id 가 정체 · 모델 가격과 주문 가격을 둘 다 든다 · 라운드 453)
  intents           주문 의도(계획 · 방향 · 거래일마다 하나) — 같은 계획·방향·거래일에 두 번 못 만든다
  order_events      주문 상태 사건(PLANNED → … → FILLED/CANCELLED/REJECTED/UNKNOWN/EXPIRED)
  position_events   포지션 사건(소유: 읽기 전용 기존 · 자동매매가 산 것 · 사용자가 넘긴 것)
  account_snapshots 계좌 잔고(이 PC 에만)
  shadow_outcomes   기록만 모드의 모의 결과(같은 채점기)
  heartbeats        워커가 돌았다는 기록
"""
import datetime as _dt
import json
import os
import sqlite3

PROJ = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(PROJ, '.portfolio', 'swing.db')

MODES = ('OFF', 'SHADOW', 'PAPER', 'LIVE')
OWNERSHIP = ('READ_ONLY_EXISTING', 'SWING_OPENED', 'USER_ADOPTED')
#: 자동 매도가 허락된 소유 — 기존 보유는 사용자가 넘기기 전에는 절대 안 판다
AUTO_SELL_OWNERSHIP = ('SWING_OPENED', 'USER_ADOPTED')

STATES = ('PLANNED', 'RISK_APPROVED', 'SUBMITTING', 'BROKER_ACK', 'PARTIAL', 'FILLED',
          'CANCEL_REQUESTED', 'CANCELLED', 'REJECTED', 'UNKNOWN', 'EXPIRED')
TERMINAL = ('FILLED', 'CANCELLED', 'REJECTED', 'EXPIRED')
#: 허락된 전이 — 여기 없는 전이는 장부가 거부한다(상태가 거꾸로 가거나 건너뛰지 않게)
TRANSITIONS = {
    None: ('PLANNED',),
    'PLANNED': ('RISK_APPROVED', 'REJECTED'),
    'RISK_APPROVED': ('SUBMITTING', 'REJECTED'),
    # 보내다 멈춘 뒤 다시 켜서 내역으로 맞추면 곧바로 체결·취소·만료일 수 있다(재시작 맞추기)
    'SUBMITTING': ('BROKER_ACK', 'REJECTED', 'UNKNOWN', 'PARTIAL', 'FILLED', 'CANCELLED', 'EXPIRED'),
    'UNKNOWN': ('BROKER_ACK', 'PARTIAL', 'FILLED', 'REJECTED', 'UNKNOWN', 'CANCELLED', 'EXPIRED'),
    'BROKER_ACK': ('PARTIAL', 'FILLED', 'CANCEL_REQUESTED', 'CANCELLED', 'EXPIRED', 'BROKER_ACK'),
    'PARTIAL': ('PARTIAL', 'FILLED', 'CANCEL_REQUESTED', 'CANCELLED', 'EXPIRED'),
    'CANCEL_REQUESTED': ('CANCELLED', 'PARTIAL', 'FILLED', 'EXPIRED', 'CANCEL_REQUESTED'),
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings_events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, key TEXT, value TEXT, by TEXT);
CREATE TABLE IF NOT EXISTS plans (plan_id TEXT PRIMARY KEY, created_ts TEXT, data_day TEXT, code TEXT, name TEXT,
    spec TEXT, entry REAL, target REAL, stop REAL, horizon INTEGER, wait_bars INTEGER, live_ok INTEGER,
    block_reason TEXT, verdict TEXT, engine_version TEXT, receipt_id TEXT,
    entry_model REAL, target_model REAL, entry_source TEXT, rulebook_version TEXT, cost_pct REAL);
CREATE TABLE IF NOT EXISTS intents (intent_id TEXT PRIMARY KEY, plan_id TEXT, side TEXT, code TEXT, qty INTEGER,
    price REAL, ord_dvsn TEXT, mode TEXT, trade_day TEXT, created_ts TEXT, reason TEXT, planned_loss REAL);
CREATE UNIQUE INDEX IF NOT EXISTS intents_once ON intents (plan_id, side, trade_day, reason);
CREATE TABLE IF NOT EXISTS order_events (id INTEGER PRIMARY KEY AUTOINCREMENT, intent_id TEXT, ts TEXT, state TEXT,
    odno TEXT, orgno TEXT, filled_qty INTEGER, avg_fill REAL, detail TEXT);
CREATE TABLE IF NOT EXISTS position_events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, code TEXT, ownership TEXT,
    plan_id TEXT, event TEXT, qty INTEGER, price REAL, target REAL, stop REAL, trade_day TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS account_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, env TEXT, cash REAL,
    total_eval REAL, net_asset REAL, stock_eval REAL, positions TEXT, cash_d2 REAL);
CREATE TABLE IF NOT EXISTS shadow_outcomes (id INTEGER PRIMARY KEY AUTOINCREMENT, plan_id TEXT, ts TEXT, status TEXT,
    fill_day TEXT, fill_price REAL, exit_status TEXT, return_pct REAL, net_pct REAL, detail TEXT);
CREATE TABLE IF NOT EXISTS heartbeats (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, mode TEXT, status TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS intent_meta (intent_id TEXT PRIMARY KEY, pre_odnos TEXT);
"""


class LedgerError(Exception):
    """장부가 거부한 일 — 허락 안 된 상태 전이 · 같은 의도 두 번."""


def now_ts():
    return _dt.datetime.now().astimezone().isoformat(timespec='seconds')


def connect(path=PATH, readonly=False):
    """장부를 연다(없으면 표를 만든다 · 있는 행 불변). `:memory:` 도 된다(시험용).

    readonly=True — 쓰기가 꺼진 화면(회귀의 앱 테스트 · GAEUM_NO_LOCAL_WRITE)용. 파일이 없으면 **만들지 않고** None 을
    돌려주고, 있으면 읽기 전용으로 연다 — 사용자 자료를 검사가 바꾸지 않는다(라운드 165)."""
    if readonly:
        if path == ':memory:' or not os.path.exists(path):
            return None
        c = sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=10)
        c.row_factory = sqlite3.Row
        return c
    if path != ':memory:':
        os.makedirs(os.path.dirname(path), exist_ok=True)
    c = sqlite3.connect(path, timeout=10)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    _migrate(c)
    c.commit()
    return c


#: 라운드 453 — 계획에 더한 열. 모델(중앙 판정) 가격과 호가 단위로 맞춘 주문 가격을 **둘 다** 남긴다(한쪽이 다른 쪽을 덮지
#: 않는다) · 진입가의 출처 · 계약에 든 규칙집 버전과 비용. 옛 장부에는 열이 없으므로 여기서 더한다(있는 행 불변 · 멱등).
PLAN_COLUMNS_453 = (('entry_model', 'REAL'), ('target_model', 'REAL'), ('entry_source', 'TEXT'),
                    ('rulebook_version', 'TEXT'), ('cost_pct', 'REAL'))


#: 라운드 454 — 계좌 스냅샷에 더한 열: D+2 정산 예정 예수금(한국투자 잔고 요약 prvs_rcdl_excc_amt). 옛 장부에는 열이 없으므로
#: 여기서 더한다(있는 행 불변 · 멱등 · 표가 아예 없는 옛 시험 장부는 건너뛴다).
ACCOUNT_COLUMNS_454 = (('cash_d2', 'REAL'),)


def _migrate(c):
    have = {r[1] for r in c.execute('PRAGMA table_info(plans)')}
    for name, typ in PLAN_COLUMNS_453:
        if name not in have:
            c.execute(f'ALTER TABLE plans ADD COLUMN {name} {typ}')
    have2 = {r[1] for r in c.execute('PRAGMA table_info(account_snapshots)')}
    for name, typ in ACCOUNT_COLUMNS_454:
        if have2 and name not in have2:
            c.execute(f'ALTER TABLE account_snapshots ADD COLUMN {name} {typ}')


# ── 설정 ────────────────────────────────────────────────────────────────
def set_setting(c, key, value, by='ui'):
    c.execute('INSERT INTO settings_events (ts, key, value, by) VALUES (?,?,?,?)',
              (now_ts(), key, json.dumps(value, ensure_ascii=False), by))
    c.commit()


def settings(c):
    """지금 설정 — 열쇠마다 마지막 사건의 값."""
    out = {}
    for r in c.execute('SELECT key, value FROM settings_events ORDER BY id'):
        try:
            out[r['key']] = json.loads(r['value'])
        except Exception:                                      # noqa: BLE001
            out[r['key']] = None
    return out


def mode_of(c):
    m = settings(c).get('mode') or 'OFF'
    return m if m in MODES else 'OFF'


# ── 계획 ────────────────────────────────────────────────────────────────
def add_plan(c, p):
    """계획을 남긴다 — 같은 plan_id 가 있으면 아무것도 안 바꾼다(바뀌지 않는 영수증). 새로 남겼으면 True."""
    cur = c.execute(
        'INSERT OR IGNORE INTO plans (plan_id, created_ts, data_day, code, name, spec, entry, target, stop, horizon, '
        'wait_bars, live_ok, block_reason, verdict, engine_version, receipt_id, entry_model, target_model, entry_source, '
        'rulebook_version, cost_pct) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
        (p['plan_id'], now_ts(), p['data_day'], p['code'], p.get('name'), p['spec'], p.get('entry'), p.get('target'),
         p.get('stop'), p.get('horizon'), p.get('wait_bars'), int(bool(p.get('live_ok'))), p.get('block_reason'),
         json.dumps(p.get('verdict') or {}, ensure_ascii=False), p.get('engine_version'), p.get('receipt_id'),
         p.get('entry_model'), p.get('target_model'), p.get('entry_source'), p.get('rulebook_version'), p.get('cost_pct')))
    c.commit()
    return cur.rowcount == 1


def plans(c, data_day=None):
    q = 'SELECT * FROM plans' + (' WHERE data_day = ?' if data_day else '') + ' ORDER BY data_day DESC, code'
    return [dict(r) for r in c.execute(q, (data_day,) if data_day else ())]


def plan(c, plan_id):
    r = c.execute('SELECT * FROM plans WHERE plan_id = ?', (plan_id,)).fetchone()
    return dict(r) if r else None


# ── 주문 의도와 상태 ────────────────────────────────────────────────────
def add_intent(c, it, pre_odnos=None):
    """주문 의도 — 같은 (계획, 방향, 거래일, 이유)는 한 번뿐이다(중복 주문 금지 · 장부가 막는다).

    pre_odnos: 보내기 **직전** 증권사 내역에 이미 있던 같은 종목·방향의 오늘 주문번호들. 응답을 못 받아 주문번호를 모를 때
    '내 주문'을 그 밖에서만 찾는다 — PC 시계와 증권사 시계를 견주지 않는다(1초 빨라도 들어간 주문을 '없다'로 읽던 결함 ·
    2026-10-08 독립 검토). 모르면 None(그때는 아무것도 빼지 않는다)."""
    try:
        c.execute('INSERT INTO intents (intent_id, plan_id, side, code, qty, price, ord_dvsn, mode, trade_day, created_ts, '
                  'reason, planned_loss) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                  (it['intent_id'], it['plan_id'], it['side'], it['code'], int(it['qty']), it.get('price'),
                   it['ord_dvsn'], it['mode'], it['trade_day'], now_ts(), it.get('reason') or 'entry',
                   it.get('planned_loss')))
    except sqlite3.IntegrityError as e:
        raise LedgerError(f'같은 주문 의도가 이미 있습니다 — {it["plan_id"]} · {it["side"]} · {it["trade_day"]}') from e
    if pre_odnos is not None:
        c.execute('INSERT OR REPLACE INTO intent_meta (intent_id, pre_odnos) VALUES (?,?)',
                  (it['intent_id'], json.dumps(sorted(set(str(x) for x in pre_odnos)))))
    order_event(c, it['intent_id'], 'PLANNED', commit=False)
    c.commit()


def pre_odnos(c, intent_id):
    """보내기 직전에 이미 있던 주문번호들(집합) · 모르면 None."""
    r = c.execute('SELECT pre_odnos FROM intent_meta WHERE intent_id = ?', (intent_id,)).fetchone()
    if not r:
        return None
    try:
        return set(json.loads(r['pre_odnos'] or '[]'))
    except Exception:                                          # noqa: BLE001
        return None


def intent(c, intent_id):
    r = c.execute('SELECT * FROM intents WHERE intent_id = ?', (intent_id,)).fetchone()
    return dict(r) if r else None


def last_event(c, intent_id):
    r = c.execute('SELECT * FROM order_events WHERE intent_id = ? ORDER BY id DESC LIMIT 1', (intent_id,)).fetchone()
    return dict(r) if r else None


def order_event(c, intent_id, state, odno=None, orgno=None, filled_qty=None, avg_fill=None, detail=None, commit=True):
    """상태 사건 하나 — 허락 안 된 전이는 거부한다. 주문번호는 한 번 알면 이어받는다.
    commit=False 면 부르는 쪽이 묶음으로 커밋한다(체결 반영과 상태 기록을 한 번에 — 중간에 멈춰 두 번 세지 않게)."""
    if state not in STATES:
        raise LedgerError(f'모르는 상태 {state!r}')
    prev = last_event(c, intent_id)
    cur = prev['state'] if prev else None
    if cur in TERMINAL:
        raise LedgerError(f'끝난 주문({cur})은 다시 바꾸지 않습니다 — {intent_id}')
    if state not in TRANSITIONS.get(cur, ()):
        raise LedgerError(f'허락 안 된 전이 {cur} → {state} — {intent_id}')
    odno = odno or (prev or {}).get('odno')
    orgno = orgno or (prev or {}).get('orgno')
    if filled_qty is None:
        filled_qty = (prev or {}).get('filled_qty')
    if avg_fill is None:
        avg_fill = (prev or {}).get('avg_fill')
    c.execute('INSERT INTO order_events (intent_id, ts, state, odno, orgno, filled_qty, avg_fill, detail) '
              'VALUES (?,?,?,?,?,?,?,?)', (intent_id, now_ts(), state, odno, orgno, filled_qty, avg_fill, detail))
    if commit:
        c.commit()


def intents_with_state(c, states=None):
    """의도 + 지금 상태. states 를 주면 그 상태인 것만."""
    out = []
    for r in c.execute('SELECT * FROM intents ORDER BY created_ts'):
        d = dict(r)
        ev = last_event(c, d['intent_id']) or {}
        d.update(state=ev.get('state'), odno=ev.get('odno'), orgno=ev.get('orgno'),
                 filled_qty=ev.get('filled_qty') or 0, avg_fill=ev.get('avg_fill'), last_ts=ev.get('ts'),
                 detail=ev.get('detail'))
        if states is None or d['state'] in states:
            out.append(d)
    return out


def events_of(c, intent_id):
    return [dict(r) for r in c.execute('SELECT * FROM order_events WHERE intent_id = ? ORDER BY id', (intent_id,))]


# ── 포지션 ──────────────────────────────────────────────────────────────
def position_event(c, code, ownership, event, plan_id=None, qty=None, price=None, target=None, stop=None,
                   trade_day=None, detail=None, commit=True):
    if ownership not in OWNERSHIP:
        raise LedgerError(f'모르는 소유 {ownership!r}')
    if event not in POSITION_EVENTS:
        raise LedgerError(f'모르는 포지션 사건 {event!r}')
    c.execute('INSERT INTO position_events (ts, code, ownership, plan_id, event, qty, price, target, stop, trade_day, detail) '
              'VALUES (?,?,?,?,?,?,?,?,?,?,?)',
              (now_ts(), code, ownership, plan_id, event, qty, price, target, stop, trade_day, detail))
    if commit:
        c.commit()


#: 포지션 사건 — SEEN(계좌에서 처음 본 기존 보유 · 관리 안 함) · OPENED(자동매매 매수 체결 · 관리 시작) ·
#: FILL_ADD(같은 계획의 추가 체결) · ADOPTED(사용자가 넘김 · 관리 시작) · SOLD(매도 체결 · 수량 줄임) ·
#: CLOSED(다 팔림 · 관리 끝) · RELEASE_REQUESTED(사용자가 되돌려 받기를 눌렀다 · 열린 매도 주문이 있어 취소 확인 전 ·
#: 새 보호 주문은 안 낸다 · 라운드 453) · RELEASED(되돌려 받음 확인 · 관리 끝, 기존 보유로)
POSITION_EVENTS = ('SEEN', 'OPENED', 'FILL_ADD', 'ADOPTED', 'SOLD', 'CLOSED', 'RELEASE_REQUESTED', 'RELEASED')


def positions(c):
    """종목마다 지금 상태 {code: dict(ownership, managed, releasing, qty, entry_price, target, stop, plan_id, opened_day, last_event)}.

    `managed` 가 참인 것만 자동 매도 대상이다. 기존 보유(SEEN)는 사용자가 넘기기(ADOPTED) 전에는 managed 가 안 된다.
    `releasing` 이 참이면(되돌려 받기 요청 · 취소 확인 전) 관리 수량은 계좌에 맞추되 **새 보호 주문은 안 낸다**(라운드 453)."""
    out = {}
    for r in c.execute('SELECT * FROM position_events ORDER BY id'):
        d = dict(r)
        ev = d['event']
        cur = dict(out.get(d['code']) or dict(ownership=d['ownership'], managed=False, releasing=False, qty=0))
        if ev == 'SEEN':
            if not cur.get('managed'):
                cur.update(ownership='READ_ONLY_EXISTING', qty=int(d.get('qty') or 0))
        elif ev in ('OPENED', 'ADOPTED'):
            cur.update(ownership=d['ownership'], managed=True, releasing=False, qty=int(d.get('qty') or 0),
                       entry_price=d.get('price'), target=d.get('target'), stop=d.get('stop'), plan_id=d.get('plan_id'),
                       opened_day=d.get('trade_day'))
        elif ev == 'FILL_ADD':
            cur['qty'] = int(cur.get('qty') or 0) + int(d.get('qty') or 0)
        elif ev == 'SOLD':
            cur['qty'] = max(0, int(cur.get('qty') or 0) - int(d.get('qty') or 0))
        elif ev == 'CLOSED':
            cur.update(managed=False, releasing=False, qty=0, closed_day=d.get('trade_day'))
        elif ev == 'RELEASE_REQUESTED':
            cur['releasing'] = True
        elif ev == 'RELEASED':
            cur.update(ownership='READ_ONLY_EXISTING', managed=False, releasing=False)
        cur['last_event'] = ev
        out[d['code']] = cur
    return out


def managed_open(c):
    """자동 매도가 허락된 열린 포지션 — 읽기 전용 기존 보유는 절대 안 들고, 되돌려 받기 요청 중(취소 확인 전)인 것도 안 든다
    (새 보호 주문을 내지 않는다 · 그 종목의 열린 매도는 워커가 취소를 확인할 때까지 바퀴마다 다시 요청한다)."""
    return {k: v for k, v in positions(c).items()
            if v.get('managed') and not v.get('releasing') and v.get('ownership') in AUTO_SELL_OWNERSHIP
            and int(v.get('qty') or 0) > 0}


def releasing(c):
    """되돌려 받기 요청 중(열린 매도 주문의 취소 확인 전)인 포지션 {code: dict} — 라운드 453."""
    return {k: v for k, v in positions(c).items() if v.get('managed') and v.get('releasing')}


def protect_needed(c):
    """워커가 증권사를 불러야 하는 보유가 있나 — 관리 중(보호 매도) 또는 해제 확인 중(열린 매도 취소). 모드와 무관하다(라운드 453)."""
    return bool(managed_open(c) or releasing(c))


# ── 계좌·모의·심박 ──────────────────────────────────────────────────────
def account_snapshot(c, env, bal):
    c.execute('INSERT INTO account_snapshots (ts, env, cash, total_eval, net_asset, stock_eval, positions, cash_d2) '
              'VALUES (?,?,?,?,?,?,?,?)', (now_ts(), env, bal.get('cash'), bal.get('total_eval'), bal.get('net_asset'),
                                           bal.get('stock_eval'), json.dumps(bal.get('positions') or [], ensure_ascii=False),
                                           bal.get('cash_d2')))
    c.commit()


def account_history(c, limit=500):
    """계좌 스냅샷 이력(오래된 것부터) — 자산 곡선용(라운드 455). 보유 JSON 은 안 푼다(가볍게). 없으면 []."""
    rows = [dict(r) for r in c.execute('SELECT id, ts, env, cash, total_eval, net_asset, stock_eval, cash_d2 FROM account_snapshots '
                                       'ORDER BY id DESC LIMIT ?', (int(limit),))]
    rows.reverse()
    return rows


def last_account(c):
    r = c.execute('SELECT * FROM account_snapshots ORDER BY id DESC LIMIT 1').fetchone()
    if not r:
        return None
    d = dict(r)
    try:
        d['positions'] = json.loads(d['positions'] or '[]')
    except Exception:                                          # noqa: BLE001
        d['positions'] = []
    return d


def shadow_outcome(c, plan_id, res):
    c.execute('INSERT INTO shadow_outcomes (plan_id, ts, status, fill_day, fill_price, exit_status, return_pct, net_pct, '
              'detail) VALUES (?,?,?,?,?,?,?,?,?)',
              (plan_id, now_ts(), res.get('status'), res.get('fill_day'), res.get('fill_price'), res.get('exit_status'),
               res.get('return_pct'), res.get('net_pct'), res.get('detail')))
    c.commit()


def shadow_latest(c):
    """계획마다 마지막 모의 결과 {plan_id: dict}."""
    out = {}
    for r in c.execute('SELECT * FROM shadow_outcomes ORDER BY id'):
        out[r['plan_id']] = dict(r)
    return out


def heartbeat(c, mode, status, detail=''):
    c.execute('INSERT INTO heartbeats (ts, mode, status, detail) VALUES (?,?,?,?)', (now_ts(), mode, status, detail))
    c.commit()


def heartbeats_recent(c, n=5):
    """최근 심박 n개(최근순) — 관제실 '최근 사건' 칸(라운드 455)."""
    return [dict(r) for r in c.execute('SELECT ts, mode, status, detail FROM heartbeats ORDER BY id DESC LIMIT ?', (int(n),))]


def last_heartbeat(c):
    r = c.execute('SELECT * FROM heartbeats ORDER BY id DESC LIMIT 1').fetchone()
    return dict(r) if r else None
