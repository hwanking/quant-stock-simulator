# -*- coding: utf-8 -*-
"""라운드 531 — 스윙 칸을 **운영과 같은 실행 모양**으로 두 탭 열어 장부 설정 위젯이 서로를 되돌리지 않는지 본다(회귀 §511 ⑦ 이 부른다).

2차 독립 검토(2026-10-15)가 만든 시험대를 옮겼다. 운영(web_app)에서 스윙 칸은
  · 본문 전체가 조각(st.fragment)이라 위젯 누름과 15초 자동 갱신은 **조각 실행**이고,
  · 위젯이 장부에 적으면 st.rerun() → **전체 실행**이며 그 끝에서 web_app 이 st.stop() 을 부른다(안 그린 위젯을 정리하지 않는다),
  · 세션의 PagesManager 는 하나다(AppTest 기본처럼 실행마다 '페이지 바뀜' 정리가 일어나지 않는다).
AppTest 기본은 셋 다 달라서(늘 전체 실행 · st.stop 없음 · run() 마다 새 PagesManager) 1차 고침(열쇠에 장부 값)이 AppTest 에서만 통했다.
여기서는 셋을 운영처럼 맞춘다. 임시 장부는 _probe/_r531_two_*.db(끝에 지움) · 증권사 생성자 막힘 · naver_price 막힘.

    python scripts/two_tab_harness_r531.py <장면> [1]     # 1 = 돌연변이(옛 열쇠 상태를 안 지우는 1차 고침) — 결함이 다시 나야 한다
장면: kill_race · rule_race · approval_race · single · lost_click → 표준출력 '@@R@@' 뒤에 JSON
"""
import json
import os
import sys
import time

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)
os.chdir(PROJ)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except (AttributeError, ValueError):
    pass
os.environ['GAEUM_SWING_TASK_JSON'] = 'ABSENT'
import noconsole  # noqa: E402
noconsole.install()
import swing_engine as SE  # noqa: E402
import swing_executor as SX  # noqa: E402
import swing_ledger as SL  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402
import streamlit.testing.v1.app_test as _apt  # noqa: E402
import streamlit.testing.v1.local_script_runner as _lsr  # noqa: E402
from streamlit.runtime.scriptrunner_utils.script_requests import RerunData  # noqa: E402

SCEN = sys.argv[1] if len(sys.argv) > 1 else 'single'
MUTANT = len(sys.argv) > 2 and sys.argv[2] == '1'
DB = os.path.join(PROJ, '_probe', f'_r531_two_{SCEN}{int(MUTANT)}.db')
# 돌연변이 — 1차 고침(열쇠에 장부 값만 · 옛 열쇠 상태를 안 지움). 이것이 운영 모양에서 다시 되돌리기를 내야 시험이 결함을 잡는다는 증거다
MUT_SRC = ("import hashlib as _hl\n"
           "def _lk(st, base, v, shown):\n"
           "    return base + '__' + _hl.sha1(_V._canon(v).encode('utf-8')).hexdigest()[:10]\n"
           "_V.ledger_key = _lk\n") if MUTANT else ''

CUR = dict(storage=None, frag=None, auto=False)
_orig_pm = _apt.PagesManager
_pm_cache = {}


class _PersistPM:
    """세션 내내 하나인 PagesManager(운영의 AppSession 과 같게)."""
    uses_pages_directory = None

    def __new__(cls, path, *a, **k):
        if path not in _pm_cache:
            _pm_cache[path] = _orig_pm(path, *a, **k)
        return _pm_cache[path]


_apt.PagesManager = _PersistPM
_orig_mfs = _lsr.MemoryFragmentStorage
_lsr.MemoryFragmentStorage = lambda: CUR['storage']
_orig_run = _lsr.LocalScriptRunner.run


def _run(self, widget_state=None, query_params=None, timeout=3, page_hash=''):
    if not CUR['frag']:
        return _orig_run(self, widget_state, query_params, timeout, page_hash)
    rd = RerunData(widget_states=widget_state, page_script_hash=page_hash, fragment_id_queue=[CUR['frag']],
                   is_fragment_scoped_rerun=True, is_auto_rerun=CUR['auto'])
    self.request_rerun(rd)
    if not self._script_thread:
        self.start()
    _lsr.require_widgets_deltas(self, timeout)
    return _lsr.parse_tree_from_messages(self.forward_msgs())


_lsr.LocalScriptRunner.run = _run


def mk_db(kill=None, approval=None, auto_rule='hash'):
    for suf in ('', '-wal', '-shm', '-journal'):
        if os.path.exists(DB + suf):
            os.remove(DB + suf)
    c = SL.connect(DB)
    SL.set_setting(c, 'mode', 'LIVE', by='test')
    SL.set_setting(c, 'live_unlock', SX.LIVE_UNLOCK_PHRASE, by='test')
    SL.set_setting(c, 'limits', dict(risk_per_trade_krw=100000, max_position_pct=20, max_total_exposure_pct=90, min_cash_pct=5,
                                     max_open_positions=5, max_daily_new_orders=3), by='test')
    SL.account_snapshot(c, 'real', dict(cash=10_000_000, total_eval=20_000_000, net_asset=20_000_000, stock_eval=10_000_000,
                                        positions=[]))
    pk = dict(symbol='000001.KS', asset_type='STOCK', name='n', core=dict(
        recommended=False, bucket='추천 제외', exclude_reason='시험 사유', entry_price=10000, new_target=11000, new_stop=9500,
        horizon_days=20, expected_return=-0.31,
        checks=[dict(name='비용 차감 기대값 양수', ok=False)] + [dict(name=f'c{i}', ok=True) for i in range(10)]))
    pl = SE.plan_from_pick(pk, '2026-10-07', 'vtest', '2026-10-07', SE.wait_bars())
    SL.add_plan(c, dict(pl, plan_id='A1', data_day='2026-10-07'))
    if kill is not None:
        SL.set_setting(c, 'kill_switch', kill, by='test')
    if approval is not None:
        SL.set_setting(c, 'order_approval', approval, by='test')
    SL.set_setting(c, 'acct_refresh', {'on': True, 'every': 15}, by='test')     # 자동 갱신 켜짐(갈래가 15초 조각 실행)
    time.sleep(1.1)
    if auto_rule:
        SL.set_setting(c, 'auto_draw', dict(on=True, mode='LIVE', ts=SL.now_ts(), rule=auto_rule), by='test')
    c.close()


SRC = (
    "import sys\n"
    f"sys.path.insert(0, {PROJ!r})\n"
    "import streamlit as st\n"
    "import broker_kis as _B\n"
    "import swing_ledger as _L\n"
    "import swing_view as _V\n"
    "import swing_engine as _SE\n"
    "import ui_kit as _uk\n"
    "class _NoBroker:\n"
    "    def __init__(self, *a, **k):\n"
    "        raise RuntimeError('broker called')\n"
    "_B.KisBroker = _NoBroker\n"
    "_B.load_config = lambda: dict(env='real', app_key='k', app_secret='s', cano='12345678', prdt='01', missing=[], problems=[], source={})\n"
    "if _V.broker_kis.KisBroker is not _NoBroker:\n"
    "    raise SystemExit(99)\n"
    "_SE.naver_price = lambda code: None\n"
    f"_L.connect.__defaults__ = ({DB!r}, False)\n"
    + MUT_SRC +
    "_V.render(st, _uk, allow_read=True, allow_write=True, hold_levels=lambda code: (1.0, 2.0), report=None,\n"
    "          anchor_day='2026-10-07')\n"
    "st.stop()\n")


class Tab:
    def __init__(self, name):
        self.name = name
        self.storage = _orig_mfs()
        self.at = AppTest.from_string(SRC, default_timeout=120)
        self.body = None
        self.log = []

    def _go(self, frag, auto=False):
        CUR['storage'] = self.storage
        CUR['frag'] = (self.body if frag else None)
        CUR['auto'] = auto
        try:
            self.at.run()
        finally:
            CUR['frag'] = None
        if self.body is None:
            roots = [fid for fid, p in self.storage._parent_by_id.items() if p is None]
            self.body = roots[0] if roots else None
        self.log.append(('frag' if frag else 'full') + (' auto' if auto else ''))

    def full(self):
        self._go(False)

    def tick(self):                      # 15초 자동 갱신
        self._go(True, auto=True)

    def click(self):                     # 조각 안 위젯을 누른 뒤의 실행
        self._go(True)

    def kill(self):
        return [t for t in self.at.toggle if t.label == '긴급정지'][0]

    def radio(self, label):
        r = [x for x in self.at.radio if x.label == label]
        return r[0] if r else None

    def warnings(self):
        return [str(w.value) for w in self.at.warning]


def rows(key):
    cc = SL.connect(DB)
    r = [json.loads(x['value']) for x in cc.execute("SELECT value FROM settings_events WHERE key=? ORDER BY id", (key,))]
    cc.close()
    return r


out = dict(scen=SCEN, mutant=MUTANT)
try:
    if SCEN == 'kill_race':
        mk_db(kill=True)
        A, B = Tab('A'), Tab('B')
        A.full(); B.full()
        A.kill().set_value(False); A.click()                 # A 가 끈다
        B.tick()
        B.kill().set_value(True); B.click()                  # B 가 A 의 다음 갱신 전에 다시 켠다
        for _ in range(3):
            A.tick(); B.tick()                               # 둘 다 입력 없이 15초마다
        out['kill'] = rows('kill_switch')
        out['A_shows'], out['B_shows'] = A.kill().value, B.kill().value
        out['exc'] = len(A.at.exception) + len(B.at.exception)
    elif SCEN == 'rule_race':
        mk_db(auto_rule='hash')
        A, B = Tab('A'), Tab('B')
        A.full(); B.full()
        for T in (A, B):
            T.at.radio(key='sw_nav').set_value('오늘 계획'); T.click(); T.full()
        A.radio('고르는 규칙').set_value('ev'); A.click()
        B.tick()
        B.radio('고르는 규칙').set_value('hash'); B.click()
        for _ in range(3):
            A.tick(); B.tick()
        out['rules'] = [d.get('rule') for d in rows('auto_draw')]
        out['exc'] = len(A.at.exception) + len(B.at.exception)
    elif SCEN == 'approval_race':
        mk_db(approval='approve')
        A, B = Tab('A'), Tab('B')
        A.full(); B.full()
        for T in (A, B):
            T.at.radio(key='sw_nav').set_value('시스템'); T.click(); T.full()
        A.radio('실전 주문 방식').set_value('auto'); A.click()
        B.full()
        B.radio('실전 주문 방식').set_value('approve'); B.click()
        A.click()                                            # A 가 나중에 아무 칸이나 눌러 조각이 돈다
        out['approval'] = rows('order_approval')
        out['A_shows'] = A.radio('실전 주문 방식').value
        out['exc'] = len(A.at.exception) + len(B.at.exception)
    elif SCEN == 'lost_click':
        # 장부의 긴급정지가 한 번도 안 적힌(None) 상태 · B 가 켰다 끈다 · 그동안 그대로인 A 가 켬을 누른다 → 적지 않고 그 사실을 알린다
        mk_db(kill=None)
        A, B = Tab('A'), Tab('B')
        A.full(); B.full()
        B.kill().set_value(True); B.click()
        B.kill().set_value(False); B.click()
        A.kill().set_value(True); A.click()
        out['kill'] = rows('kill_switch')
        out['A_shows'] = A.kill().value
        out['A_warn'] = A.warnings()
        out['exc'] = len(A.at.exception) + len(B.at.exception)
    else:                                                    # single — 한 탭 · 누름 하나에 사건 하나 · 보이는 값이 장부와 같다
        mk_db(kill=None, approval=None, auto_rule='hash')
        A = Tab('A')
        A.full()
        seq = []
        for v in (True, False, True):
            A.kill().set_value(v); A.click()
            seq.append(A.kill().value)
            A.tick(); A.tick()
            seq.append(A.kill().value)
        out['kill_shows'], out['kill'] = seq, rows('kill_switch')
        A.at.radio(key='sw_nav').set_value('시스템'); A.click(); A.full()
        aps = []
        for v in ('auto', 'approve'):
            A.radio('실전 주문 방식').set_value(v); A.click()
            aps.append(A.radio('실전 주문 방식').value)
            A.click()
            aps.append(A.radio('실전 주문 방식').value)
        out['ap_shows'], out['approval'] = aps, rows('order_approval')
        A.at.radio(key='sw_nav').set_value('오늘 계획'); A.click(); A.full()
        rs = []
        for v in ('ev', 'hash'):
            A.radio('고르는 규칙').set_value(v); A.click()
            rs.append(A.radio('고르는 규칙').value)
            A.tick()
            rs.append(A.radio('고르는 규칙').value)
        out['rule_shows'], out['rule'] = rs, [d.get('rule') for d in rows('auto_draw')]
        out['exc'] = len(A.at.exception)
except Exception:  # noqa: BLE001
    import traceback
    out['crash'] = traceback.format_exc()[-2000:]
finally:
    for suf in ('', '-wal', '-shm', '-journal'):
        try:
            os.remove(DB + suf)
        except OSError:
            pass
sys.stdout.write('@@R@@' + json.dumps(out, ensure_ascii=False, default=str))
