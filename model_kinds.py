# -*- coding: utf-8 -*-
"""가치평가 모형을 **재료**로 가른다 — 이익을 쓰는 것과 자산을 쓰는 것.

라운드 358 이 적자 종목에서 지어낸 양수 이익을 쓰는 모형 다섯을 무효로 돌렸다.
그러자 적자·ROE 음수 종목에는 **자산 기반 모형만** 남는데(실측 34종목 전부 · 그중
28종목은 유효 모형이 **하나**뿐 · 2026-09-22 · 유니버스 앞 200종목에서 고른 표본),
화면은 그 수를 여전히 여덟 모형을 교차검증한 값처럼 내고 있었다:

    price_axes.value_band → basis = "이익·장부가 모델 1종의 25~75분위 범위"

**그 문장은 거짓이다** — 이익 모형은 한 종도 안 섰다. 이름이 계산보다 넓으면
사용자는 없는 근거를 있다고 읽는다(라운드 237·239 가 두 번 고친 그 자리).

여기서 정하는 것은 **가름 하나**뿐이다. 문턱도, 점수도, 새 수도 없다.

가르는 규칙: **그 모형의 산출값 식이 정상화 EPS·추정 EBITDA 를 쓰는가.**
  · 쓰면 이익 기반 — 적자 종목에서는 그 값이 지어낸 이익 위에 선다
  · 안 쓰면 자산 기반 — BPS·ROE 만 쓴다

⚠️ **유효 조건이 아니라 산출값 식으로 가른다.** rNPV 는 유효 조건이
`bool(pipeline_data)` 라 이익이 안 보이지만 값은 `bps*8.5 + norm_eps*15.0` 이다.
유효 조건으로 갈랐으면 그것을 자산 기반이라 부를 뻔했다.

⚠️ **이 목록은 손으로 적은 것이고 낡는다**(라운드 114 의 그 규칙). 회귀가
`quant_indicators.py` 의 `model_results[...] = {'val': …}` 와 그 변수의 식에서
**유도해** 이 두 값과 대 본다 — 엔진에 모형을 더하거나 식을 바꾸면 그 절이
먼저 붉어진다.
"""

#: 산출값이 BPS·ROE 만 쓰는 모형 (적자 기업도 이 값은 지어낸 것이 아니다)
ASSET_MODELS = ('PBR_ROE', 'DDM', 'SOTP')

#: 산출값이 정상화 EPS·추정 EBITDA 를 쓰는 모형
EARNINGS_MODELS = ('PER', 'EV_EBITDA', 'FCFF', 'rNPV', 'EV_GP', 'DCF_SCENARIO')


def split(model_results):
    """유효 모형을 재료별로 가른다.

    반환: dict(asset=[키], earnings=[키], unknown=[키], asset_only=bool)
      · `asset_only` 은 **유효 모형이 하나 이상이고 전부 자산 기반**일 때만 참이다.
        유효 모형이 0개면 적정가 자체가 안 나오므로(엔진이 UNCALCULATED) 거짓이다.
      · 모르는 키는 `unknown` 으로 두고 **자산 기반으로 세지 않는다** —
        모르는 것을 한쪽에 넣으면 그게 지어내는 것이다 (§3).
        하나라도 모르면 `asset_only` 은 거짓이다.
    """
    asset, earn, unknown = [], [], []
    if isinstance(model_results, dict):
        for key, m in model_results.items():
            if not (isinstance(m, dict) and m.get('valid')):
                continue
            if key in ASSET_MODELS:
                asset.append(key)
            elif key in EARNINGS_MODELS:
                earn.append(key)
            else:
                unknown.append(key)
    return dict(asset=sorted(asset), earnings=sorted(earn), unknown=sorted(unknown),
                asset_only=bool(asset) and not earn and not unknown)


def basis_kind_ko(model_results):
    """축 설명에 쓸 재료 이름. 가를 수 없으면 종전 표현을 그대로 돌려준다.

    종전 문장은 언제나 '이익·장부가' 였다 — 가를 수 있을 때만 좁힌다.
    """
    s = split(model_results)
    if not (s['asset'] or s['earnings'] or s['unknown']):
        return '이익·장부가'                      # 못 가른다 — 종전 표현 그대로
    if s['asset_only']:
        return '장부가'
    if s['earnings'] and not s['asset']:
        return '이익'
    return '이익·장부가'
