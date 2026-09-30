# -*- coding: utf-8 -*-
"""관측 산출물을 찾는 길 — 엔진 쪽 (라운드 386).

`.portfolio/`(이 PC 의 최신 기록) 먼저, 없으면 `data/`(저장소 동봉본). 눌린 것(`.gz`)도 같은
이름으로 찾는다. 찾는 차례는 화면의 `web_app._artifact_path` 와 **같다** — 회귀가 둘을 심어서 대
본다(§4 · 한쪽만 고치면 화면과 엔진이 다른 파일을 읽는다).

■ 왜 필요한가
  배포 앱은 **빈 `.portfolio/`** 에서 뜬다(라운드 331). 그런데 엔진이 판정 **중에** 읽는 산출물
  둘 — 국면 게이트의 `regime_breakdown.json` 과 점수대 적중률 `calibration.json` — 을
  `.portfolio/` 에서만 찾고 있었다. 화면은 라운드 108 부터 `data/` 동봉본으로 물러서는데 엔진은
  안 물러섰다. 2026-09-29 실측(전방 기록부 12종목 · 같은 기준일 · 두 파일을 '없음'으로 흉내):
  **12종목 전부** 손절·목표·비용 차감 기대값이 갈렸고, 점수 5종목이 55점으로 · 신뢰도 10종목이
  60으로 눌렸으며, 국면 사유는 *"표본이 없습니다"* 라는 **거짓**을 적었다(표본은 있고 파일을 못
  읽은 것이다 · §3). 클라우드 기록기는 백업 묶음에서 `.portfolio/` 를 되받아 이 문제가 없었다 —
  갈린 것은 **사용자가 보는 배포 화면**이었다.

■ 못 읽으면 None — 빈 dict 가 아니다
  "파일이 없다/못 읽었다"와 "읽었는데 비어 있다"를 가른다(§3 · 라운드 194 의 0 과 미측정).
"""
from __future__ import annotations

import gzip
import json
import os
import threading

BASE = os.path.dirname(os.path.abspath(__file__))
_ONCE_LOCK = threading.Lock()
#: 찾는 차례 — 화면(`web_app._artifact_path`)과 같다
DIRS = ('.portfolio', 'data')


def find(fname, base=BASE):
    """있으면 경로, 없으면 None. 차례: `.portfolio` → `data`, 각각 평문 → `.gz`."""
    for d in DIRS:
        for n in (fname, fname + '.gz'):
            p = os.path.join(base, d, n)
            if os.path.exists(p):
                return p
    return None


def source(fname, base=BASE):
    """어느 쪽을 읽게 되나 — 'live'(.portfolio) · 'bundle'(data) · None."""
    p = find(fname, base)
    if not p:
        return None
    return 'live' if os.path.basename(os.path.dirname(p)) == '.portfolio' else 'bundle'


def load_json(fname, base=BASE):
    """찾아서 읽는다. 없거나 못 읽으면 **None**."""
    p = find(fname, base)
    if not p:
        return None
    try:
        if p.endswith('.gz'):
            with gzip.open(p, 'rt', encoding='utf-8') as f:
                return json.load(f)
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except Exception:                                          # noqa: BLE001
        return None


def load_once(cache, path):
    """게으른 한 번 읽기 — **'읽었다'는 읽은 뒤에 찍는다** (라운드 402).

    `cache` 는 부르는 모듈이 제 것으로 가진 `{'loaded': bool, 'doc': ...}` 다. 못 읽으면 `doc` 은 None 이고
    다시 읽지 않는다(종전 동작 그대로 · 경로도 부르는 쪽이 정한다 — `find` 의 차례를 쓰지 않는다).

    ■ 왜 필요한가
      종전 세 곳(`case_layers._doc` · `case_layers._hier_doc` · `sector_cycle.ledger_perf`)이 깃발을 **읽기 전에**
      올렸다. 그 사이에 다른 세션의 스레드가 오면 깃발은 섰는데 문서는 아직 None 이라 **None 을 받았다** —
      2026-10-01 서버를 막 띄운 첫 화면이 '계층 보정 확률 **미산출**'을 냈고 같은 페이지를 다시 그리자 '약 66%'
      였다(부르는 쪽이 `except: pass` 로 받아 사유도 안 남았다 · §3). json.load 를 늦춰 심으면 셋 다 재현된다.
      Streamlit 은 세션마다 스레드가 따로 돌므로 '처음 부른 사람'이 둘일 수 있다.
    """
    if cache.get('loaded'):
        return cache.get('doc')
    with _ONCE_LOCK:
        if not cache.get('loaded'):
            try:
                with open(path, encoding='utf-8') as f:
                    cache['doc'] = json.load(f)
            except Exception:                                  # noqa: BLE001
                cache['doc'] = None
            cache['loaded'] = True                             # 문서를 넣은 **뒤에** 선다
    return cache.get('doc')
