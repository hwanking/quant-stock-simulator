# -*- coding: utf-8 -*-
"""
스윙 자동매매 알림 (라운드 463) — **이 PC 의 Windows 알림으로만** 띄운다. 밖으로 보내지 않는다(§9 · 메일·메신저·웹훅 없음 ·
이 모듈은 네트워크를 쓰지 않는다 — 회귀가 가져오는 모듈을 본다).

경쟁사 레이더의 '알림·외부 전달' 차이는 체결·오류를 사람이 모른다는 것이었다. 밖으로 보내면 계좌 자료가 나가므로, 이 PC 에서 도는
워커가 이 PC 의 알림 센터에 띄우는 데까지만 한다.

무엇을 알리나 — 장부(§4 · 화면과 같은 한 곳)의 **새 사건**과 바퀴 경고만:
  주문 사건   체결 · 일부 체결 · 거절 · 응답 없음(UNKNOWN) · 매수 주문 접수 · 보호 매도(손절·기간 만료) 접수 · 매수 주문 만료
              — 1차 목표 지정가 매도는 날마다 다시 걸리고 이튿날 만료되므로 접수·만료는 안 알린다(체결·거절만)
  포지션 사건 관리 끝
  바퀴 경고   실행부가 `alerts` 로 낸 문장 · 워커 바퀴 실패
같은 날 같은 문장은 한 번만 띄운다. 한 바퀴의 사건이 여럿이면 알림 하나로 묶고 몇 건인지 적는다(말없이 자르지 않는다 · R314).

기본은 **꺼짐**(장부 설정 `notify`). 꺼져 있는 동안에도 읽은 자리(커서)는 앞으로 옮긴다 — 켠 순간 옛 사건이 쏟아지지 않게.
알림이 실패해도 바퀴는 그대로다(부르는 쪽이 예외를 삼키고 사유를 적는다). 쓰기 금지(GAEUM_NO_LOCAL_WRITE=1)면 띄우지도 적지도 않는다.
판정·점수·문턱·주문 규칙을 읽지도 바꾸지도 않는다. 상태 파일 `.portfolio/swing_notify_state.json` 은 종목 이름이 든 개인 자료라
백업 거부 목록(`swing*`)에 걸린다.
"""
import datetime as _dt
import io
import json
import os
import subprocess

# 라운드 485 — 자식 프로세스(git·PowerShell·python)가 콘솔 창을 띄우지 않게
import noconsole                                               # noqa: E402
noconsole.install()

import swing_ledger as L

PROJ = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(PROJ, '.portfolio', 'swing_notify_state.json')
NOTIFY_KEY = 'notify'                     # 장부 설정 열쇠 — {'on': bool}
KST = _dt.timezone(_dt.timedelta(hours=9))
#: 사유(의도의 reason 머리) → 사람 말. 모르는 사유는 방향으로 적는다.
REASON_KO = {'entry': '진입 매수', 'target': '1차 목표 매도', 'stop': '손절 매도', 'expiry': '기간 만료 매도'}
PROTECTIVE = ('stop', 'expiry')
#: 한 알림에 줄로 적는 사건 수 — 나머지는 '외 N건'(화면 폭의 문제이지 판정 문턱이 아니다)
SHOW_LINES = 3
DETAIL_CHARS = 80
#: PowerShell 의 알림 앱 표식(Windows PowerShell 이 자기 알림에 쓰는 것) — 이 PC 의 알림 센터에만 뜬다
_PS_APP_ID = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe'
_PS_TOAST = (
    "$ErrorActionPreference = 'Stop'; "
    "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null; "
    "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null; "
    "$t = [System.Security.SecurityElement]::Escape($env:GAEUM_TOAST_TITLE); "
    "$b = [System.Security.SecurityElement]::Escape($env:GAEUM_TOAST_BODY); "
    "$x = New-Object Windows.Data.Xml.Dom.XmlDocument; "
    "$x.LoadXml(\"<toast><visual><binding template='ToastGeneric'><text>$t</text><text>$b</text></binding></visual></toast>\"); "
    "$n = [Windows.UI.Notifications.ToastNotification]::new($x); "
    "$m = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('" + _PS_APP_ID + "'); "
    "if ($env:GAEUM_TOAST_DRY -ne '1') { $m.Show($n) }")


def _clip(s, n=DETAIL_CHARS):
    s = ' '.join(str(s or '').split())
    return s if len(s) <= n else s[:n - 1] + '…'


def _day(now=None):
    n = now if now is not None else _dt.datetime.now(KST)
    if n.tzinfo is None:
        n = n.replace(tzinfo=KST)
    return n.astimezone(KST).date().isoformat()


def _base(reason):
    return str(reason or '').split('#')[0]


def notify_on(stt):
    v = (stt or {}).get(NOTIFY_KEY)
    return bool(v.get('on')) if isinstance(v, dict) else False


def load_state(path=None):
    try:
        with io.open(path or STATE_PATH, encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(state, path=None):
    p = path or STATE_PATH
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + '.tmp'
    with io.open(tmp, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False)
    os.replace(tmp, p)


def max_ids(c):
    a = c.execute('SELECT COALESCE(MAX(id), 0) FROM order_events').fetchone()[0]
    b = c.execute('SELECT COALESCE(MAX(id), 0) FROM position_events').fetchone()[0]
    return int(a or 0), int(b or 0)


def order_rows(c, after_id, upto_id):
    q = ('SELECT oe.id AS id, oe.state AS state, oe.filled_qty AS filled_qty, oe.avg_fill AS avg_fill, oe.detail AS detail, '
         'i.code AS code, i.side AS side, i.reason AS reason, i.qty AS qty, i.price AS price, p.name AS name '
         'FROM order_events oe JOIN intents i ON i.intent_id = oe.intent_id LEFT JOIN plans p ON p.plan_id = i.plan_id '
         'WHERE oe.id > ? AND oe.id <= ? ORDER BY oe.id')
    return [dict(r) for r in c.execute(q, (int(after_id), int(upto_id)))]


def position_rows(c, after_id, upto_id):
    q = ('SELECT pe.id AS id, pe.code AS code, pe.event AS event, pe.detail AS detail, p.name AS name '
         'FROM position_events pe LEFT JOIN plans p ON p.plan_id = pe.plan_id WHERE pe.id > ? AND pe.id <= ? ORDER BY pe.id')
    return [dict(r) for r in c.execute(q, (int(after_id), int(upto_id)))]


def _who(r):
    nm = (r.get('name') or '').strip()
    return f"{nm}({r['code']})" if nm else str(r.get('code') or '?')


def message_for_order(r):
    """주문 사건 한 줄 → 알릴 문장 또는 None(알리지 않는 사건)."""
    st, side, reason = r.get('state'), r.get('side'), _base(r.get('reason'))
    what = REASON_KO.get(reason, '매수' if side == 'buy' else '매도')
    who = _who(r)
    avg = f" · 평균 {float(r['avg_fill']):,.0f}원" if r.get('avg_fill') else ''
    if st == 'FILLED':
        return f"체결 — {who} {what} {int(r.get('filled_qty') or r.get('qty') or 0)}주{avg}"
    if st == 'PARTIAL':
        return f"일부 체결 — {who} {what} {int(r.get('filled_qty') or 0)}/{int(r.get('qty') or 0)}주{avg}"
    if st == 'REJECTED':
        return f"거절 — {who} {what} · {_clip(r.get('detail'))}"
    if st == 'UNKNOWN':
        return f"응답 없음 — {who} {what} · 다시 보내지 않고 체결 내역으로 맞춥니다"
    if st == 'BROKER_ACK' and (side == 'buy' or reason in PROTECTIVE):
        px = f" · 지정가 {float(r['price']):,.0f}원" if r.get('price') else ' · 시장가'
        return f"주문 접수 — {who} {what} {int(r.get('qty') or 0)}주{px}"
    if st == 'EXPIRED' and side == 'buy':
        return f"매수 주문 만료 — {who} 그날 체결 없음"
    return None


def message_for_position(r):
    if r.get('event') != 'CLOSED':
        return None
    why = REASON_KO.get(_base(r.get('detail')), _clip(r.get('detail'), 40))
    return f"관리 끝 — {_who(r)}" + (f" ({why})" if why else '')


def compose(msgs):
    """사건 문장들 → (제목, 본문). 앞의 몇 줄과 '외 N건' — 말없이 자르지 않는다."""
    n = len(msgs)
    title = '가늠 자동매매 — ' + (msgs[0].split(' — ')[0] if n == 1 else f'사건 {n}건')
    shown = msgs[:SHOW_LINES]
    body = '\n'.join(shown) + (f'\n외 {n - len(shown)}건 — 관제실 주문·체결 갈래에서 봅니다' if n > len(shown) else '')
    return title, body


def toast(title, body, dry=False, runner=None, timeout=20):
    """이 PC 의 Windows 알림 하나 → (ok, 사유). dry=True 면 알림 객체까지만 만들고 띄우지 않는다(시험).
    네트워크를 쓰지 않는다 — PowerShell 의 WinRT 알림 API 를 부른다. Windows 가 아니면 (False, 사유)."""
    if os.name != 'nt' and runner is None:
        return False, 'Windows 가 아니라 알림을 띄울 수 없다'
    env = dict(os.environ, GAEUM_TOAST_TITLE=str(title), GAEUM_TOAST_BODY=str(body), GAEUM_TOAST_DRY='1' if dry else '0')
    try:
        if runner is not None:
            return runner(title, body, dry)
        r = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', _PS_TOAST], env=env,
                           capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
    except Exception as e:                                     # noqa: BLE001 — PowerShell 없음 · 시간초과
        return False, f'{type(e).__name__}: {str(e)[:120]}'
    if r.returncode != 0:
        return False, f'PowerShell 종료 {r.returncode}: {(r.stderr or "").strip()[:160]}'
    return True, None


def _send(msgs, state, now, send):
    title, body = compose(msgs)
    ok, why = (send or toast)(title, body)
    state['sent'] = list(state.get('sent') or []) + msgs      # 실패해도 같은 문장을 바퀴마다 다시 띄우지 않는다
    state['last_ts'] = (now if now is not None else _dt.datetime.now(KST)).isoformat(timespec='seconds')
    state['last_count'] = len(msgs)
    state['last_error'] = None if ok else why
    return f"알림 {len(msgs)}건 띄움" if ok else f"알림 {len(msgs)}건을 못 띄웠다 — {why}"


def after_cycle(c, out=None, now=None, send=None, state_path=None):
    """한 바퀴 뒤 — 장부의 새 사건과 이 바퀴의 경고를 알린다(켜져 있을 때만) → 한 줄 요약 또는 None."""
    if os.environ.get('GAEUM_NO_LOCAL_WRITE') == '1':
        return None
    path = state_path or STATE_PATH
    on = notify_on(L.settings(c))
    state = load_state(path)
    before = json.dumps(state, sort_keys=True, ensure_ascii=False)
    day = _day(now)
    if state.get('day') != day:
        state['day'], state['sent'] = day, []
    om, pm = max_ids(c)
    first = 'order_id' not in state
    msgs = []
    if on and not first:
        for r in order_rows(c, state.get('order_id', 0), om):
            m = message_for_order(r)
            if m:
                msgs.append(m)
        for r in position_rows(c, state.get('position_id', 0), pm):
            m = message_for_position(r)
            if m:
                msgs.append(m)
    if on:
        msgs += ['경고 — ' + _clip(a, 120) for a in ((out or {}).get('alerts') or [])]
    seen = set(state.get('sent') or [])
    fresh = []
    for m in msgs:
        if m not in seen:
            seen.add(m)
            fresh.append(m)
    state['order_id'], state['position_id'] = om, pm          # 꺼져 있어도 커서는 앞으로(켠 순간 옛 사건이 쏟아지지 않게)
    line = _send(fresh, state, now, send) if fresh else None
    if json.dumps(state, sort_keys=True, ensure_ascii=False) != before:
        save_state(state, path)                               # 바뀐 것이 없으면 바퀴마다 파일을 다시 쓰지 않는다
    return line


def failure(text, now=None, send=None, state_path=None, connect=None):
    """워커 바퀴 실패를 알린다(켜져 있을 때만 · 같은 날 같은 문장 한 번) → 한 줄 요약 또는 None. 장부는 읽기만 한다."""
    if os.environ.get('GAEUM_NO_LOCAL_WRITE') == '1':
        return None
    c = (connect or (lambda: L.connect(readonly=True)))()
    if c is None:
        return None
    try:
        if not notify_on(L.settings(c)):
            return None
    finally:
        c.close()
    path = state_path or STATE_PATH
    state = load_state(path)
    day = _day(now)
    if state.get('day') != day:
        state['day'], state['sent'] = day, []
    m = '경고 — ' + _clip(text, 120)
    if m in (state.get('sent') or []):
        return None
    line = _send([m], state, now, send)
    save_state(state, path)
    return line


def status_line(stt, state=None):
    """화면 한 줄 — 켜짐/꺼짐 · 마지막으로 띄운 때 · 마지막 실패 사유. 판정 낱말 없음."""
    st = state if state is not None else load_state()
    if not notify_on(stt):
        return ('이 PC 알림 — 꺼짐. 켜면 체결·거절·응답 없음·보호 매도 접수·관리 끝과 워커 경고를 이 PC 의 Windows 알림으로 '
                '띄웁니다(밖으로 보내지 않습니다 · 설정에서 켭니다)')
    parts = ['이 PC 알림 — 켜짐']
    if st.get('last_ts'):
        parts.append(f"마지막으로 띄운 때 {str(st['last_ts'])[5:16].replace('T', ' ')} ({int(st.get('last_count') or 0)}건)")
    else:
        parts.append('아직 띄운 알림 없음')
    if st.get('last_error'):
        parts.append(f"마지막 알림 실패 — {_clip(st['last_error'], 100)}")
    return ' · '.join(parts) + ' · 워커가 도는 동안 이 PC 에 로그인해 있어야 보입니다'
