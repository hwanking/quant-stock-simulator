# -*- coding: utf-8 -*-
"""
한국투자증권 Open API 어댑터 (라운드 446) — 이 저장소에서 한국투자 서버를 부르는 곳은 **여기 하나**다.

■ 명세의 출처 — 지어내지 않는다
  주소·TR 코드·요청 칸·응답 칸은 한국투자 공식 저장소 `koreainvestment/open-trading-api` 의
  `examples_llm/domestic_stock/*` 와 `kis_auth.py` 에서 그대로 옮겼다(2026-10-08 확인). 사용자가 붙여 준 예시 코드의
  주문 TR(`TTTC0802U`/`0801U`)은 **옛 코드**였다 — 지금 공식 샘플은 매수 `TTTC0012U` · 매도 `TTTC0011U` 다.
  명세가 바뀌어 응답이 예상과 다르면 값을 짐작해 채우지 않고 실패로 돌려준다(§3).

■ 자격증명 — 저장소 안에는 절대 두지 않는다 (§9)
  읽는 곳은 둘뿐이다: ① 환경변수 ② **저장소 밖** 파일 `~/.gaeum/kis.env`(KEY=VALUE 줄). 토큰도 저장소 밖
  `~/.gaeum/` 에 둔다. 키·계좌번호는 화면·로그에 **가려서**(`mask`) 낸다. 이 모듈은 포트폴리오를 다른 곳에 보내지 않는다 —
  한국투자(사용자 자신의 증권사)에서 읽고, 사용자가 켠 주문만 보낸다.

■ 무엇을 하지 않나
  - 신용·미수 주문 없음(현금 주문 TTTC0012U/0011U 만) · 국내 정규장(KRX)만 · NXT·시간외 없음
  - 네트워크 오류·시간초과에서 주문을 **다시 보내지 않는다** — `TransportError` 를 던지고 부르는 쪽이 주문 상태를
    `UNKNOWN` 으로 두고 체결 조회로 맞춘다(같은 주문이 두 번 나가는 것이 자동매매에서 가장 비싼 사고다).
"""
import datetime as _dt
import hashlib
import io
import json
import os
import threading
import time

import safe_replace   # 라운드 522 — 토큰 파일 바꿔 끼우기(한 곳). 맨 위에서: 못 가져오면 조용히 저장을 건너뛰지 않고 바로 드러나게

ENVS = ('demo', 'real')
BASE_URL = {'real': 'https://openapi.koreainvestment.com:9443',
            'demo': 'https://openapivts.koreainvestment.com:29443'}
#: 요청 사이 간격(초) — 운영 값(판정 문턱 아님). 공식 샘플의 `_smartSleep` 은 실효값이 0.1 이고(모드별 0.05·0.5 대입은
#: 지역 변수라 안 먹는다 · 2026-10-08 독립 검토) 그것도 쪽 넘김 사이에만 쓴다. 공식 README 는 '초당 거래건수 초과(EGW00201)'와
#: '모의투자는 호출 제한이 낮다'만 적는다 — 그래서 실전 0.1 · 모의 0.5 로 넉넉히 둔다.
SLEEP = {'real': 0.1, 'demo': 0.5}
#: 라운드 459 — 토큰 만료 응답 코드. 공식 샘플(koreainvestment/open-trading-api · legacy/rest/current_price_samle.py)이 이 코드를 받으면
#: 토큰을 다시 받고 같은 조회를 한 번 더 부른다. 공식 근거를 확인한 코드만 적는다(다른 코드는 지어내지 않는다 · §3).
TOKEN_EXPIRED_CODES = ('EGW00123',)
#: 쪽 넘김 상한 — 넘으면 **실패**로 멈춘다(말없이 자른 목록으로 체결을 맞추면 들어간 주문을 '없다'로 읽는다)
MAX_PAGES = 20
TR = {
    'balance': {'real': 'TTTC8434R', 'demo': 'VTTC8434R'},
    'psbl': {'real': 'TTTC8908R', 'demo': 'VTTC8908R'},
    'buy': {'real': 'TTTC0012U', 'demo': 'VTTC0012U'},
    'sell': {'real': 'TTTC0011U', 'demo': 'VTTC0011U'},
    'cancel': {'real': 'TTTC0013U', 'demo': 'VTTC0013U'},
    'ccld': {'real': 'TTTC0081R', 'demo': 'VTTC0081R'},
}
PATHS = {
    'token': '/oauth2/tokenP',
    'balance': '/uapi/domestic-stock/v1/trading/inquire-balance',
    'psbl': '/uapi/domestic-stock/v1/trading/inquire-psbl-order',
    'order': '/uapi/domestic-stock/v1/trading/order-cash',
    'cancel': '/uapi/domestic-stock/v1/trading/order-rvsecncl',
    'ccld': '/uapi/domestic-stock/v1/trading/inquire-daily-ccld',
    # 라운드 525 — 일별 분봉 조회(조회만 · `day_feed` 가 쓴다). 라운드 516 은 이 파일을 장중에 안 고치려고 그 모듈이 프로세스 안에서
    #   등록했다 — 장 마감 뒤 표로 옮겼다(공식 샘플 `inquire_time_dailychartprice` 의 경로 · 주문 경로가 아니다).
    'minute_day': '/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice',
}
ORD_LIMIT = '00'      # 지정가
ORD_MARKET = '01'     # 시장가
EXCHANGE = 'KRX'      # v1 은 KRX 정규장만

CONFIG_KEYS = ('KIS_ENV', 'KIS_APP_KEY', 'KIS_APP_SECRET', 'KIS_ACCOUNT_NO', 'KIS_ACCOUNT_PRODUCT_CODE')
HOME_DIR = os.path.join(os.path.expanduser('~'), '.gaeum')
SECRET_FILE = os.path.join(HOME_DIR, 'kis.env')
_PROJ = os.path.dirname(os.path.abspath(__file__))


class BrokerError(Exception):
    """한국투자가 **거절**했거나 응답이 명세와 달라 읽지 못했다 — 주문이 안 들어갔다는 것이 확실한 실패."""


class TransportError(BrokerError):
    """네트워크 오류·시간초과 — 주문이 들어갔는지 **모른다.** 다시 보내지 않고 체결 조회로 맞춘다."""


def mask(s, keep=2):
    """가린 글자 — 앞뒤 `keep` 글자만 남긴다. 없으면 '(없음)'."""
    s = '' if s is None else str(s)
    if not s:
        return '(없음)'
    if len(s) <= keep * 2:
        return '*' * len(s)
    return s[:keep] + '*' * (len(s) - keep * 2) + s[-keep:]


def _inside_repo(path):
    try:
        return os.path.commonpath([os.path.abspath(path), _PROJ]) == _PROJ
    except ValueError:
        return False


#: 라운드 525 — 연결 정보 파일 읽기 재시도(라운드 522 토큰 파일과 같은 모양 · 운영 선택이지 잰 문턱이 아니다). 저장은 바꿔 끼우기라
#:   반쪽 파일은 없지만 Windows 에선 바꿔 끼우는 그 순간 열기가 실패한다 — 사용자가 연결 정보를 저장하는 순간 워커가 읽으면 그 바퀴가
#:   '연결 정보를 못 읽었다'로 증권사 없이 돌았다(그 바퀴의 손절 판정). 있는데 못 열면 짧게 다시 · 끝내 못 열면 종전대로 예외(부르는 쪽이 문제로 적는다).
ENV_READ_TRIES = 5
ENV_READ_WAIT = 0.02
#: 끊긴 저장이 남긴 임시 파일(키가 든)을 저장 시작에 치울 때 — 이보다 오래된 것만(지금 다른 저장이 쓰는 중인 것은 안 건드린다 · 운영 값)
STALE_TMP_SEC = 60


def _read_env_file(path, tries=None, wait=None, sleep=time.sleep):
    tries = ENV_READ_TRIES if tries is None else tries
    wait = ENV_READ_WAIT if wait is None else wait
    for k in range(max(1, tries)):
        out = {}
        if not path:
            return out
        if not os.path.exists(path):
            # 독립 검토(2026-10-14) — 바꿔 끼우는 순간 이름이 잠깐(약 20ms) 안 보인 관측이 있었다 · 한 번 더 본다(정말 없으면 그만큼만 늦다)
            if k == 0 and tries > 1:
                sleep(wait)
                if os.path.exists(path):
                    continue
            return out
        try:
            with io.open(path, encoding='utf-8') as f:
                for ln in f:
                    ln = ln.strip()
                    if not ln or ln.startswith('#') or '=' not in ln:
                        continue
                    kk, v = ln.split('=', 1)
                    out[kk.strip()] = v.strip().strip('"').strip("'")
            return out
        except OSError:
            if k >= max(1, tries) - 1:
                raise
            sleep(wait)
    return {}


def load_config(environ=None, path=SECRET_FILE):
    """자격증명 → dict(env, app_key, app_secret, cano, prdt, source, missing, problems).

    환경변수가 먼저고, 없는 칸만 저장소 밖 파일에서 채운다. **저장소 안의 파일은 읽지 않는다** — 경로가 저장소 안이면
    그 파일을 무시하고 문제로 적는다(커밋될 수 있는 자리에 키를 두지 않게). 빈 칸은 `missing` 에 이름으로 적는다."""
    environ = os.environ if environ is None else environ
    problems = []
    fileconf = {}
    if path and _inside_repo(path):
        problems.append('자격증명 파일이 저장소 안에 있어 읽지 않았습니다 — 저장소 밖(~/.gaeum/kis.env)에 두세요')
    else:
        try:
            fileconf = _read_env_file(path)
        except Exception as e:                                 # noqa: BLE001
            problems.append(f'자격증명 파일을 못 읽었습니다 — {type(e).__name__}')
    vals, src = {}, {}
    for k in CONFIG_KEYS:
        v = (environ.get(k) or '').strip()
        if v:
            vals[k], src[k] = v, 'env'
        elif fileconf.get(k):
            vals[k], src[k] = fileconf[k], 'file'
    env = (vals.get('KIS_ENV') or '').lower()
    if env and env not in ENVS:
        problems.append(f"KIS_ENV 는 demo 또는 real 이어야 합니다 (받은 값: {env!r})")
    cano = vals.get('KIS_ACCOUNT_NO') or ''
    prdt = vals.get('KIS_ACCOUNT_PRODUCT_CODE') or ''
    # 계좌번호를 10자리(8+2)로 적었으면 갈라 준다 — 짐작이 아니라 형식이 그 뜻일 때만
    if cano and not prdt and len(cano.replace('-', '')) == 10 and cano.replace('-', '').isdigit():
        c = cano.replace('-', '')
        cano, prdt = c[:8], c[8:]
    if cano and not (len(cano) == 8 and cano.isdigit()):
        problems.append('KIS_ACCOUNT_NO 는 계좌번호 앞 8자리 숫자여야 합니다')
    if prdt and not (len(prdt) == 2 and prdt.isdigit()):
        problems.append('KIS_ACCOUNT_PRODUCT_CODE 는 계좌번호 뒤 2자리 숫자여야 합니다')
    missing = [k for k in CONFIG_KEYS if k != 'KIS_ACCOUNT_PRODUCT_CODE' and not vals.get(k)]
    if not prdt:
        missing.append('KIS_ACCOUNT_PRODUCT_CODE')
    return dict(env=env or None, app_key=vals.get('KIS_APP_KEY'), app_secret=vals.get('KIS_APP_SECRET'),
                cano=cano or None, prdt=prdt or None, source=src, missing=missing, problems=problems)


def config_summary(cfg):
    """화면·로그용 — 값은 가리고 무엇이 있는지만."""
    if not cfg:
        return '연결 정보 없음'
    if cfg.get('missing'):
        return '연결 정보가 모자랍니다: ' + ', '.join(cfg['missing'])
    # 라운드 453 — 앱 키는 가린 조각조차 보이지 않는다(외부 검토 #14 · 등록됐다는 사실이면 된다). 계좌는 가린 모양으로.
    return (f"{'모의투자' if cfg['env'] == 'demo' else '실전'} · 계좌 {mask(cfg['cano'])}-{cfg['prdt']} · "
            f"앱 키·시크릿 등록됨")


def _urllib_transport(method, url, headers, params=None, body=None, timeout=10):
    """기본 운송 — (상태 코드, 응답 머리, JSON) · 네트워크가 끊기면 TransportError."""
    import urllib.error
    import urllib.parse
    import urllib.request
    if params:
        url = url + '?' + urllib.parse.urlencode(params)
    data = json.dumps(body).encode('utf-8') if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode('utf-8', errors='replace')
            return r.status, {k.lower(): v for k, v in r.headers.items()}, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8', errors='replace')
        try:
            doc = json.loads(raw) if raw else {}
        except Exception:                                      # noqa: BLE001
            doc = {'_raw': raw[:200]}
        return e.code, {k.lower(): v for k, v in (e.headers or {}).items()}, doc
    except Exception as e:                                     # noqa: BLE001 — 시간초과·연결 끊김
        raise TransportError(f'{type(e).__name__}: {str(e)[:120]}')


def _num(v):
    try:
        if v is None or str(v).strip() == '':
            return None
        return float(str(v).replace(',', ''))
    except (TypeError, ValueError):
        return None


class KisBroker:
    """한국투자 국내주식 현금 계좌 하나. `transport` 를 바꿔 끼우면 네트워크 없이 시험할 수 있다."""

    def __init__(self, cfg, transport=None, token_dir=HOME_DIR, clock=time.time, sleep=time.sleep):
        if not cfg or cfg.get('missing') or cfg.get('problems'):
            raise BrokerError('연결 정보가 모자라거나 잘못됐습니다 — ' + config_summary(cfg)
                              + ('' if not (cfg or {}).get('problems') else ' · ' + ' · '.join(cfg['problems'])))
        self.cfg = cfg
        self.env = cfg['env']
        self.base = BASE_URL[self.env]
        self.transport = transport or _urllib_transport
        self.token_dir = token_dir
        self.clock = clock
        self.sleep = sleep
        self._token = None
        self._last = 0.0

    # ── 토큰 ─────────────────────────────────────────────────────────────
    # 라운드 522 — 화면(15초 갱신)·워커·저녁 작업이 같은 토큰 파일을 같이 읽는다. 종전엔 제자리로 다시 써서(열기 = 0바이트로 자름) 쓰는
    #   순간 읽은 쪽이 빈 파일을 보고 '토큰 없음'으로 새로 발급하러 갔다(한국투자는 발급을 1분에 한 번으로 묶는다 → 그 바퀴 실패 ·
    #   워커라면 그 바퀴의 손절 판정). 탐침(가짜 파일 · 쉬지 않고 쓰고 읽기 · 2026-10-13): 종전 쓰기는 읽기 1,718번 중 빈 파일 874번 ·
    #   읽는 쪽이 다시 읽어도 94번 중 7번 '없음' 결론. 임시 파일 → 바꿔 끼우기만으로는 Windows 에서 바꿔 끼우는 순간 열기 실패 3,141번 ·
    #   복사로 물러선 332번에 빈 파일 314번이 남았다 — 그래서 **둘 다**: 쓰기는 바꿔 끼우기 · 읽기는 '있는데 못 읽으면' 짧게 다시.
    #   둘을 같이 하면 다시 읽기 1,024,821번 중 '없음' 결론 0. 횟수·간격은 운영 선택이지 잰 문턱이 아니다(그 창을 넘기는 짧은 시간).
    TOKEN_READ_TRIES = 5
    TOKEN_READ_WAIT = 0.02
    #   발급이 거절되면(1분 1회) 다른 프로세스가 방금 받아 적었을 수 있다 — 이만큼 기다려 파일을 한 번 다시 읽는다(운영 선택 · 그 프로세스가
    #   응답을 받아 파일에 적는 시간 · 실패 경로에만 든다).
    TOKEN_REREAD_WAIT = 1.0

    def _token_path(self):
        h = hashlib.sha256((self.cfg['app_key'] or '').encode('utf-8')).hexdigest()[:10]
        return os.path.join(self.token_dir, f'kis_token_{self.env}_{h}.json')

    def _read_token_file(self, p):
        """토큰 파일 → ('missing', None) · ('ok', dict) · ('unreadable', None) (라운드 522).

        없으면 바로 'missing'(새로 받을 일). 있는데 못 읽으면(바꿔 끼우는 순간의 열기 실패 · 빈 파일 · 깨진 json) 짧게 다시 읽는다 —
        다른 프로세스가 막 새 토큰을 적는 중일 수 있다. 끝내 못 읽으면 'unreadable'(부르는 쪽이 종전대로 다룬다)."""
        for k in range(self.TOKEN_READ_TRIES):
            if not os.path.exists(p):
                return 'missing', None
            try:
                with io.open(p, encoding='utf-8') as f:
                    d = json.load(f)
                if isinstance(d, dict):
                    return 'ok', d
            except (OSError, ValueError):
                pass
            if k < self.TOKEN_READ_TRIES - 1:
                self.sleep(self.TOKEN_READ_WAIT)
        return 'unreadable', None

    def _load_token(self):
        try:
            st, d = self._read_token_file(self._token_path())
            if st == 'ok' and float(d.get('expires_ts') or 0) - 600 > self.clock():
                return d.get('access_token')
        except Exception:                                      # noqa: BLE001
            return None
        return None

    def token(self):
        """토큰 — 저장소 밖 파일에 하루치를 두고 다시 쓴다(한국투자는 발급 횟수를 제한한다). 만료 10분 전이면 새로 받는다."""
        if self._token:
            return self._token
        t = self._load_token()
        if t:
            self._token = t
            return t
        st, _h, doc = self.transport('POST', self.base + PATHS['token'], {'Content-Type': 'application/json'},
                                     body={'grant_type': 'client_credentials', 'appkey': self.cfg['app_key'],
                                           'appsecret': self.cfg['app_secret']})
        t = (doc or {}).get('access_token')
        if st != 200 or not t:
            # 라운드 522 — 거절돼도 바로 실패하지 않고 파일을 한 번 다시 읽는다(둘이 같이 만료 직전을 넘었거나, 한쪽이 지운 뒤 다른 쪽이
            #   막 새로 받은 자리). 있으면 그것을 쓴다 · 없으면 종전대로 실패(지어 쓰지 않는다).
            self.sleep(self.TOKEN_REREAD_WAIT)
            t2 = self._load_token()
            if t2:
                self._token = t2
                return t2
            raise BrokerError(f"토큰을 못 받았습니다 (HTTP {st}) — {str((doc or {}).get('error_description') or (doc or {}).get('msg1') or '')[:120]}")
        exp = (doc or {}).get('access_token_token_expired')
        try:
            exp_ts = _dt.datetime.strptime(exp, '%Y-%m-%d %H:%M:%S').timestamp() if exp else self.clock() + 86400 * 0.9
        except (TypeError, ValueError):
            exp_ts = self.clock() + 86400 * 0.9
        if not _inside_repo(self.token_dir):
            try:
                os.makedirs(self.token_dir, exist_ok=True)
                # 라운드 522 — 임시 파일 → 바꿔 끼우기(읽는 쪽이 빈 파일을 안 보게). 이름에 프로세스·스레드를 넣는다(화면은 세션을 스레드로
                #   돌린다 — 둘이 같이 발급해도 남의 반쪽 임시 파일을 바꿔 끼우지 않는다).
                p = self._token_path()
                tmp = f'{p}.{os.getpid()}.{threading.get_ident()}.tmp'
                try:
                    with io.open(tmp, 'w', encoding='utf-8') as f:
                        json.dump({'access_token': t, 'expires_ts': exp_ts}, f)
                    safe_replace.replace_retry(tmp, p, tries=5, wait=0.05)
                finally:
                    if os.path.exists(tmp):                    # 쓰다 실패해 바꿔 끼우기까지 못 갔으면 토큰 조각을 남기지 않는다
                        try:
                            os.remove(tmp)
                        except OSError:
                            pass
            except Exception:                                  # noqa: BLE001 — 못 남겨도 이번 호출은 쓴다
                pass
        self._token = t
        return t

    # ── 호출 하나 ────────────────────────────────────────────────────────
    def _forget_token(self, used=None):
        """토큰을 잊는다 — 메모리와 저장소 밖 파일 둘 다(라운드 459). 다음 호출이 새로 받는다.

        라운드 496 — `used`(만료 응답을 받은 그 토큰)를 주면 파일의 토큰이 **그것과 같을 때만** 파일을 지운다. 화면(15초 갱신)과 워커가
        같은 파일을 함께 쓰는데, 한쪽이 이미 새 토큰을 받아 파일에 적어 둔 뒤 다른 쪽이 낡은 토큰으로 만료 응답을 받으면 종전엔 그 새
        토큰 파일까지 지웠다 — 그러면 다시 발급해야 하고 한국투자는 발급을 1분에 한 번으로 묶는다(그 분 안의 두 번째는 거절). 파일을 못
        읽으면 종전대로 지운다(모르는 것으로 낡은 토큰을 붙잡지 않는다)."""
        self._token = None
        p = self._token_path()
        if not _inside_repo(self.token_dir):
            try:
                if os.path.exists(p):
                    if used is not None:
                        # 라운드 522 — 읽기도 같은 함수로: 다른 프로세스가 막 새 토큰을 바꿔 끼우는 순간이면 짧게 다시 읽는다.
                        #   종전엔 그 순간의 열기 실패를 '못 읽음'으로 보고 방금 적힌 새 토큰까지 지웠다(라운드 496 의 그 자리).
                        st, d = self._read_token_file(p)
                        if st == 'missing':
                            return
                        cur = (d or {}).get('access_token') if st == 'ok' else used   # 끝내 못 읽으면 지운다(종전대로)
                        if cur and cur != used:
                            return
                    os.remove(p)
            except OSError:
                pass

    def _call(self, method, key, tr_id, params=None, body=None, tr_cont='', _retried=False):
        gap = SLEEP[self.env] - (self.clock() - self._last)
        if gap > 0:
            self.sleep(gap)
        # 공식 `_base_headers` 와 같은 머리(Accept · charset)를 같이 보낸다
        tok = self.token()
        headers = {'Content-Type': 'application/json', 'Accept': 'text/plain', 'charset': 'UTF-8',
                   'authorization': f'Bearer {tok}',
                   'appkey': self.cfg['app_key'], 'appsecret': self.cfg['app_secret'],
                   'tr_id': tr_id, 'custtype': 'P', 'tr_cont': tr_cont}
        try:
            st, h, doc = self.transport(method, self.base + PATHS[key], headers, params=params, body=body)
        finally:
            self._last = self.clock()
        doc = doc or {}
        # 라운드 459 — 토큰 만료(증권사가 먼저 무효로 했다 · 시계가 어긋났다): 파일의 토큰을 하루 끝까지 다시 쓰면 그동안 모든 호출이 실패한다.
        #   잊고 · 조회는 새 토큰으로 한 번만 다시 · 주문·취소는 다시 보내지 않는다(게이트웨이가 코드를 붙여 거절했으니 들어간 주문은 없다 —
        #   다시 보내는 판단은 실행부의 상태기계가 한다 · 같은 바퀴의 앞선 조회가 이미 새 토큰을 받아 둔다).
        if str(doc.get('msg_cd') or '') in TOKEN_EXPIRED_CODES:
            self._forget_token(used=tok)                      # 라운드 496 — 이 토큰이 파일의 것일 때만 파일을 지운다
            if key not in ('order', 'cancel', 'token') and not _retried:
                return self._call(method, key, tr_id, params=params, body=body, tr_cont=tr_cont, _retried=True)
            raise BrokerError(f"토큰 만료({doc.get('msg_cd')}) — 토큰을 잊었고 다음 호출에서 새로 받습니다"
                              + (' · 주문·취소는 다시 보내지 않았습니다' if key in ('order', 'cancel') else ''))
        has_code = doc.get('rt_cd') is not None or doc.get('msg_cd') is not None
        # ⚠️ 주문·취소에서 200 이 아닌데 한국투자의 응답 코드도 없으면(게이트웨이 502·504 등) **들어갔는지 모른다** —
        #   거절로 적으면 들어간 주문을 '없다'로 읽는다(2026-10-08 독립 검토). 모름으로 올리고 체결 내역으로 맞춘다.
        if st != 200 and not has_code and key in ('order', 'cancel'):
            raise TransportError(f'HTTP {st} · 응답 코드 없음 — 들어갔는지 모른다')
        if st != 200:
            raise BrokerError(f'HTTP {st} {doc.get("msg_cd") or ""} — {str(doc.get("msg1") or "")[:120]}')
        if doc.get('rt_cd') is None and key in ('order', 'cancel'):
            raise TransportError('200 인데 응답 코드(rt_cd)가 없다 — 들어갔는지 모른다')
        if str(doc.get('rt_cd')) != '0':
            raise BrokerError(f"거절 {doc.get('msg_cd') or ''} — {str(doc.get('msg1') or '')[:120]}")
        return doc, h or {}

    def _acct(self):
        return {'CANO': self.cfg['cano'], 'ACNT_PRDT_CD': self.cfg['prdt']}

    # ── 조회 ─────────────────────────────────────────────────────────────
    def get_balance(self):
        """잔고 → dict(positions=[…], cash, total_eval, net_asset, pages). 보유 행은 수량이 있는 것만."""
        positions, summary, fk, nk, pages, cont = [], {}, '', '', 0, ''
        while True:
            params = dict(self._acct(), AFHR_FLPR_YN='N', OFL_YN='', INQR_DVSN='02', UNPR_DVSN='01',
                          FUND_STTL_ICLD_YN='N', FNCG_AMT_AUTO_RDPT_YN='N', PRCS_DVSN='00',
                          CTX_AREA_FK100=fk, CTX_AREA_NK100=nk)
            doc, h = self._call('GET', 'balance', TR['balance'][self.env], params=params, tr_cont=cont)
            pages += 1
            for r in doc.get('output1') or []:
                q = _num(r.get('hldg_qty'))
                if not q:
                    continue
                positions.append(dict(code=str(r.get('pdno') or ''), name=r.get('prdt_name'), qty=int(q),
                                      sellable_qty=int(_num(r.get('ord_psbl_qty')) or 0),
                                      avg_price=_num(r.get('pchs_avg_pric')), price=_num(r.get('prpr')),
                                      eval_amt=_num(r.get('evlu_amt')), pnl=_num(r.get('evlu_pfls_amt')),
                                      pnl_pct=_num(r.get('evlu_pfls_rt'))))
            o2 = doc.get('output2') or []
            if isinstance(o2, list) and o2:
                summary = o2[0]
            elif isinstance(o2, dict):
                summary = o2
            fk, nk = doc.get('ctx_area_fk100') or '', doc.get('ctx_area_nk100') or ''
            if str(h.get('tr_cont') or '') not in ('M', 'F'):
                break
            if pages >= MAX_PAGES:
                raise BrokerError(f'잔고가 {MAX_PAGES}쪽을 넘어 끝까지 못 읽었다 — 자른 목록으로 판단하지 않는다')
            cont = 'N'
        if not summary:
            raise BrokerError('잔고 응답에 요약(output2)이 없습니다 — 명세가 바뀌었을 수 있습니다')
        return dict(positions=positions, cash=_num(summary.get('dnca_tot_amt')),
                    cash_d2=_num(summary.get('prvs_rcdl_excc_amt')), total_eval=_num(summary.get('tot_evlu_amt')),
                    net_asset=_num(summary.get('nass_amt')), stock_eval=_num(summary.get('scts_evlu_amt')),
                    pages=pages)

    def get_orderable(self, code, price):
        """미수 없이 살 수 있는 금액·수량 (매수가능조회).

        공식 예시: '전량매수 가능수량은 반드시 ORD_DVSN 01(시장가)로 — 지정가(00)는 종목증거금율이 반영되지 않는다' ·
        미수 없이는 `nrcvb_buy_amt`·`nrcvb_buy_qty`. 첫 판은 00 으로 물어 수량이 부풀 수 있었다(2026-10-08 독립 검토)."""
        if not (price and float(price) > 0):
            raise BrokerError('매수가능 조회에 가격이 없습니다')
        params = dict(self._acct(), PDNO=str(code), ORD_UNPR=str(int(price)), ORD_DVSN=ORD_MARKET,
                      CMA_EVLU_AMT_ICLD_YN='N', OVRS_ICLD_YN='N')
        doc, _h = self._call('GET', 'psbl', TR['psbl'][self.env], params=params)
        o = doc.get('output') or {}
        if not o:
            raise BrokerError('매수가능 응답에 output 이 없습니다')
        return dict(cash=_num(o.get('ord_psbl_cash')), amt=_num(o.get('nrcvb_buy_amt')),
                    qty=int(_num(o.get('nrcvb_buy_qty')) or 0))

    def get_daily_orders(self, start, end):
        """주문·체결 내역(3개월 안) — 주문마다 dict. 날짜는 'YYYYMMDD'."""
        out, fk, nk, cont, pages = [], '', '', '', 0
        while True:
            params = dict(self._acct(), INQR_STRT_DT=start, INQR_END_DT=end, SLL_BUY_DVSN_CD='00', INQR_DVSN='00',
                          PDNO='', CCLD_DVSN='00', ORD_GNO_BRNO='', ODNO='', INQR_DVSN_3='00', INQR_DVSN_1='',
                          CTX_AREA_FK100=fk, CTX_AREA_NK100=nk, EXCG_ID_DVSN_CD=EXCHANGE)
            doc, h = self._call('GET', 'ccld', TR['ccld'][self.env], params=params, tr_cont=cont)
            pages += 1
            for r in doc.get('output1') or []:
                out.append(dict(date=str(r.get('ord_dt') or ''), orgno=str(r.get('ord_gno_brno') or ''),
                                odno=str(r.get('odno') or ''), orig_odno=str(r.get('orgn_odno') or ''),
                                side={'01': 'sell', '02': 'buy'}.get(str(r.get('sll_buy_dvsn_cd')), None),
                                code=str(r.get('pdno') or ''), ord_qty=int(_num(r.get('ord_qty')) or 0),
                                ord_price=_num(r.get('ord_unpr')), time=str(r.get('ord_tmd') or ''),
                                filled_qty=int(_num(r.get('tot_ccld_qty')) or 0), avg_fill=_num(r.get('avg_prvs')),
                                remain_qty=int(_num(r.get('rmn_qty')) or 0), rejected_qty=int(_num(r.get('rjct_qty')) or 0),
                                cancelled=str(r.get('cncl_yn') or '') == 'Y',
                                cancel_qty=int(_num(r.get('cnc_cfrm_qty')) or 0)))
            fk, nk = doc.get('ctx_area_fk100') or '', doc.get('ctx_area_nk100') or ''
            if str(h.get('tr_cont') or '') not in ('M', 'F'):
                break
            if pages >= MAX_PAGES:
                raise BrokerError(f'주문 내역이 {MAX_PAGES}쪽을 넘어 끝까지 못 읽었다 — 자른 목록으로 체결을 맞추지 않는다')
            cont = 'N'
        return out

    def health_check(self):
        """연결 확인 — 토큰 + 잔고 한 번(주문 안 함). dict(ok, env, account, positions, message)."""
        try:
            b = self.get_balance()
            return dict(ok=True, env=self.env, account=f"{mask(self.cfg['cano'])}-{self.cfg['prdt']}",
                        positions=len(b['positions']), message='연결 정상 — 잔고를 읽었습니다(주문은 안 했습니다)',
                        balance=b)                     # 라운드 459 — 화면이 같은 잔고를 한 번 더 읽지 않게
        except BrokerError as e:
            return dict(ok=False, env=self.env, account=f"{mask(self.cfg['cano'])}-{self.cfg['prdt']}",
                        positions=None, message=f'{type(e).__name__}: {e}')

    #: 주문 경로 점검의 단계 이름 — 워커가 실주문 때 부르는 증권사 호출 여섯(라운드 491). 넷은 조회라 주문 없이 부를 수 있고,
    #:   둘(매수 · 취소)은 실제로 보내야만 확인된다.
    PATH_STEPS = ('토큰·잔고 조회', '주문·체결 내역 조회', '매수가능 조회', '주문 넣기·취소')

    def order_path_check(self, code, price, today=None, days=30):
        """주문 경로 점검 — **주문은 안 낸다**(라운드 491). → [dict(step, ok, detail)] · ok 는 True(불러서 읽었다) · False(실패 ·
        사유) · None(부르지 않았다 · 사유). 금액·계좌번호는 안 싣는다.

        '연결 확인'은 잔고 하나만 읽는다. 실주문 한 번에 워커는 잔고(TTTC8434R) · 주문·체결 내역(TTTC0081R · 들어간 주문을 맞춘다) ·
        매수가능(TTTC8908R · 수량을 정한다) · 매수(TTTC0012U) · 취소(TTTC0013U)를 부른다. 앞의 셋은 조회라 여기서 **실제로** 불러
        응답 칸을 읽는지 본다. 매수·취소는 보내야만 확인되므로 부르지 않고 그렇다고 적는다 — 첫 실주문이 그 둘의 첫 시험이다.
        앞 단계가 실패하면 뒤 단계는 안 부른다(같은 토큰·계좌로 도는 호출이다)."""
        import datetime as _dt491
        out = []

        def _add(step, ok, detail):
            out.append(dict(step=step, ok=ok, detail=detail))

        try:
            b = self.get_balance()
            _add(self.PATH_STEPS[0], True, f"토큰을 받고 잔고를 읽었다 · 보유 {len(b['positions'])}종목 · {b['pages']}쪽")
        except BrokerError as e:
            _add(self.PATH_STEPS[0], False, f'{type(e).__name__}: {e}')
            for s in self.PATH_STEPS[1:3]:
                _add(s, None, '앞 단계가 실패해 부르지 않았다')
        else:
            end = today or _dt491.date.today()
            try:
                rows = self.get_daily_orders((end - _dt491.timedelta(days=int(days))).strftime('%Y%m%d'), end.strftime('%Y%m%d'))
                _add(self.PATH_STEPS[1], True, f'최근 {int(days)}일 주문 {len(rows)}건을 읽었다(체결 맞춤에 쓰는 조회)')
            except BrokerError as e:
                _add(self.PATH_STEPS[1], False, f'{type(e).__name__}: {e}')
            if not (code and price and float(price) > 0):
                _add(self.PATH_STEPS[2], None, '물어볼 종목·가격이 없어 부르지 않았다(계획이 있으면 그 진입가로 묻는다)')
            else:
                try:
                    o = self.get_orderable(code, price)
                    _add(self.PATH_STEPS[2], True, '주문 가능 금액·수량 칸을 읽었다' + (' (지금 살 수 있는 수량 0)' if not o.get('qty') else ''))
                except BrokerError as e:
                    _add(self.PATH_STEPS[2], False, f'{type(e).__name__}: {e}')
        _add(self.PATH_STEPS[3], None, '실제로 보내야만 확인된다(TTTC0012U 매수 · TTTC0013U 취소) — 부르지 않았다. 첫 실주문이 이 둘의 첫 시험이다')
        return out

    # ── 주문 ─────────────────────────────────────────────────────────────
    def place_order(self, side, code, qty, price=None, ord_dvsn=ORD_LIMIT):
        """현금 주문 하나 → dict(odno, orgno, time). 거절이면 BrokerError · 오류·시간초과면 TransportError(다시 보내지 않는다)."""
        if side not in ('buy', 'sell'):
            raise BrokerError(f'알 수 없는 방향 {side!r}')
        if not (isinstance(qty, int) and qty > 0):
            raise BrokerError(f'수량이 0 이하입니다 ({qty!r})')
        if ord_dvsn == ORD_LIMIT and not (price and price > 0):
            raise BrokerError('지정가 주문에 가격이 없습니다')
        body = dict(self._acct(), PDNO=str(code), ORD_DVSN=ord_dvsn, ORD_QTY=str(qty),
                    ORD_UNPR=str(int(price)) if ord_dvsn == ORD_LIMIT else '0', EXCG_ID_DVSN_CD=EXCHANGE,
                    SLL_TYPE='01' if side == 'sell' else '', CNDT_PRIC='')
        doc, _h = self._call('POST', 'order', TR[side][self.env], body=body)
        o = doc.get('output') or {}
        odno = str(o.get('ODNO') or '')
        if not odno:
            # 성공 코드인데 주문번호가 없다 — 들어갔는지 모른다(지어내지 않는다)
            raise TransportError('성공 응답에 주문번호(ODNO)가 없습니다 — 체결 조회로 맞춰야 합니다')
        return dict(odno=odno, orgno=str(o.get('KRX_FWDG_ORD_ORGNO') or ''), time=str(o.get('ORD_TMD') or ''))

    def cancel_order(self, orgno, odno, qty=0, all_qty=True):
        """남은 수량 취소."""
        body = dict(self._acct(), KRX_FWDG_ORD_ORGNO=str(orgno), ORGN_ODNO=str(odno), ORD_DVSN=ORD_LIMIT,
                    RVSE_CNCL_DVSN_CD='02', ORD_QTY=str(int(qty or 0)), ORD_UNPR='0',
                    QTY_ALL_ORD_YN='Y' if all_qty else 'N', EXCG_ID_DVSN_CD=EXCHANGE)
        doc, _h = self._call('POST', 'cancel', TR['cancel'][self.env], body=body)
        # 공식 메타데이터가 이 응답 칸의 대소문자를 두 가지로 적는다(chk_order_rvsecncl 은 소문자) — 둘 다 읽는다
        o = {str(k).upper(): v for k, v in (doc.get('output') or {}).items()}
        return dict(odno=str(o.get('ODNO') or ''), orgno=str(o.get('KRX_FWDG_ORD_ORGNO') or ''))


def tick_size(price):
    """KRX 주식 호가가격단위 (2023-01-25 시행 개편) — 2천원 미만 1 · 5천 미만 5 · 2만 미만 10 · 5만 미만 50 ·
    20만 미만 100 · 50만 미만 500 · 그 이상 1,000원. ETF·ETN 은 확인하지 않아 다루지 않는다(주식만)."""
    p = float(price)
    for lim, t in ((2000, 1), (5000, 5), (20000, 10), (50000, 50), (200000, 100), (500000, 500)):
        if p < lim:
            return t
    return 1000


def round_to_tick(price, side):
    """매수는 아래로(계획보다 비싸게 사지 않는다) · 매도 지정가는 아래로(목표에 닿으면 체결되게)."""
    if price is None or price <= 0:
        return None
    t = tick_size(price)
    v = int(float(price) // t * t)
    # 경계: 내린 값이 아래 구간이면 그 구간의 단위로 다시 맞춘다
    t2 = tick_size(v)
    return int(v // t2 * t2) if t2 != t else v


# ── 자격증명 저장 (라운드 449) — 사용자가 화면의 가려진 칸에 직접 넣고, 저장소 밖 파일에만 쓴다 ──────────────────────
def save_config(values, path=SECRET_FILE):
    """{KIS_ENV, KIS_APP_KEY, KIS_APP_SECRET, KIS_ACCOUNT_NO[, KIS_ACCOUNT_PRODUCT_CODE]} → 저장소 밖 파일(KEY=VALUE) → 읽어 돌려준 cfg.

    저장소 안 경로는 **거부**한다(커밋될 수 있는 자리에 키를 두지 않는다 · §9). 값은 돌려주지도 찍지도 않는다 — 부르는 쪽은
    `config_summary`(가린 요약)만 보인다. 10자리 계좌번호는 `load_config` 가 8+2 로 가른다. 임시 파일에 쓰고 바꿔 끼운다.
    파일 권한은 따로 손대지 않는다 — 사용자 프로필 폴더(~/.gaeum)는 Windows 가 이미 그 사용자·관리자에게만 열어 둔다. 첫 판은
    `icacls` 로 더 좁히려 했는데 사용자 이름과 컴퓨터 이름이 같은 PC 에서 대상이 엉뚱하게 풀려 **사용자 자신이 못 읽는** 파일이
    됐다(§435 가 PermissionError 로 잡았다). 자기 자신을 잠그는 장치는 없는 편이 낫다."""
    if _inside_repo(path):
        raise BrokerError('자격증명 파일을 저장소 안에 두지 않습니다 — 저장소 밖(~/.gaeum/kis.env)에만 씁니다')
    vals = {k: str((values or {}).get(k) or '').strip() for k in CONFIG_KEYS}
    env = vals['KIS_ENV'].lower()
    if env not in ENVS:
        raise BrokerError("KIS_ENV 는 demo 또는 real 이어야 합니다")
    vals['KIS_ENV'] = env
    if not (vals['KIS_APP_KEY'] and vals['KIS_APP_SECRET'] and vals['KIS_ACCOUNT_NO']):
        raise BrokerError('앱 키 · 앱 시크릿 · 계좌번호가 모두 있어야 합니다')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _remove_tmps(path, older_than=STALE_TMP_SEC)               # 끊긴 저장이 남긴 키 든 임시 파일(독립 검토 2026-10-14)
    # 라운드 525 — 바꿔 끼우기는 한 곳(`safe_replace` · 읽는 쪽이 막 열고 있으면 짧게 다시 · 라운드 519·522) · 임시 이름에 프로세스·스레드 ·
    #   쓰다 실패하면 임시 파일(키가 든)을 남기지 않는다 · **복사로 물러서지 않는다**(fallback=False — 복사는 제자리를 먼저 비우므로 그 순간
    #   읽은 워커가 빈 연결 정보를 보고, 쓰다 끊기면 키가 통째로 사라진다 · 독립 검토가 재현했다) — 끝내 막히면 옛 파일 그대로 두고 거절한다
    tmp = f'{path}.{os.getpid()}.{threading.get_ident()}.tmp'
    try:
        with io.open(tmp, 'w', encoding='utf-8', newline='\n') as f:
            f.write('# 가늠 한국투자 자격증명 — 이 파일은 저장소 밖에 있고 커밋·백업되지 않는다\n')
            for k in CONFIG_KEYS:
                if vals[k]:
                    f.write(f'{k}={vals[k]}\n')
        try:
            safe_replace.replace_retry(tmp, path, tries=5, wait=0.05, fallback=False)
        except safe_replace.ReplaceRefused:
            raise BrokerError('다른 프로그램이 연결 정보 파일을 잡고 있어 바꿔 끼우지 못했습니다 — 저장된 연결 정보는 그대로입니다 · '
                              '잠시 뒤 다시 저장하세요') from None
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    return load_config(environ={}, path=path)


def _remove_tmps(path, older_than=None, clock=time.time):
    """그 자격증명 파일의 임시 파일(`<path>.<pid>.<thread>.tmp` · 옛 이름 `<path>.tmp`)을 지운다 → 지운 수. older_than(초)을 주면 그보다
    오래된 것만. 못 지운 것은 건너뛴다."""
    import glob
    n = 0
    for p in set(glob.glob(glob.escape(path) + '.*.tmp') + glob.glob(glob.escape(path) + '.tmp')):
        try:
            if older_than is not None and clock() - os.path.getmtime(p) < older_than:
                continue
            os.remove(p)
            n += 1
        except OSError:
            continue
    return n


def delete_config(path=SECRET_FILE):
    """저장소 밖 자격증명 파일을 지운다 → 지웠으면 True. 환경변수는 못 지운다(사용자가 한다).
    라운드 525 — 끊긴 저장이 남긴 임시 파일(키가 든)도 같이 지운다(독립 검토 2026-10-14: '지우기' 뒤에도 키 사본이 남았다)."""
    _remove_tmps(path)
    if os.path.exists(path):
        os.remove(path)
        return True
    return False


def balance_to_rows(bal):
    """한국투자 잔고 → 앱의 보유종목 미리보기 행(`portfolio.rows_to_positions` 가 읽는 한글 열 이름). 수량 0 은 뺀다.
    평단이 없으면 행을 그대로 두고(rows_to_positions 가 사유와 함께 제외한다) 지어내지 않는다."""
    out = []
    for p in (bal or {}).get('positions') or []:
        if not p.get('qty'):
            continue
        out.append({'종목코드': str(p.get('code') or ''), '종목명': p.get('name') or '', '보유수량': p.get('qty'),
                    '평균매수가': p.get('avg_price')})
    return out
