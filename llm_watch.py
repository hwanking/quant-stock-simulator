# -*- coding: utf-8 -*-
"""
무료 언어모델 주간 관찰 — 공개 API(HuggingFace)에서 무료·오픈 모델을 자동 수집.

원칙:
  · **관찰 전용이다.** 여기 나온 모델을 파이프라인에 자동 연결하지 않는다 —
    채택은 다른 모든 방법과 같이 표본외·블라인드 검증(§58 규율)을 통과해야 한다.
  · 조회는 GET 뿐이며 우리 데이터(포트폴리오·시세·종목)는 아무것도 보내지 않는다.
  · 주 1회(7일) 자동 갱신 — 앱이 뜰 때 캐시가 오래됐으면 스스로 새로 받는다.
    실패하면 마지막 성공 캐시를 그대로 쓴다 (빈 화면·날조 금지).
"""
from __future__ import annotations

import json
import os
import time
import urllib.request

_BASE = os.path.dirname(os.path.abspath(__file__))
_CACHE_DIRS = [os.path.join(_BASE, '.portfolio'), os.path.join(_BASE, 'data')]
_CACHE_NAME = 'llm_watch.json'
_TTL_SECONDS = 7 * 24 * 3600          # 주단위
_API = ("https://huggingface.co/api/models?pipeline_tag=text-generation"
        "&sort=downloads&direction=-1&limit=60")
_EXCLUDE = ('tiny', 'internal-testing', 'test')


def _cache_path_read():
    for d in _CACHE_DIRS:
        p = os.path.join(d, _CACHE_NAME)
        if os.path.exists(p):
            return p
    return None


def _cache_path_write():
    for d in _CACHE_DIRS:
        try:
            os.makedirs(d, exist_ok=True)
            return os.path.join(d, _CACHE_NAME)
        except Exception:
            continue
    return None


def _license_of(tags):
    for t in tags or []:
        if str(t).startswith('license:'):
            return str(t).split(':', 1)[1]
    return '미표기'


def _fetch_from_api():
    req = urllib.request.Request(_API, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode('utf-8'))
    models = []
    for m in data:
        mid = str(m.get('modelId') or '')
        if not mid or any(x in mid.lower() for x in _EXCLUDE):
            continue
        if (m.get('likes') or 0) < 100 or (m.get('downloads') or 0) < 1_000_000:
            continue
        models.append({
            'id': mid,
            'downloads': int(m.get('downloads') or 0),
            'likes': int(m.get('likes') or 0),
            'license': _license_of(m.get('tags')),
        })
        if len(models) >= 12:
            break
    if not models:
        raise ValueError('필터를 통과한 모델이 없습니다')
    return {
        'fetched_at': time.strftime('%Y-%m-%d %H:%M'),
        'fetched_ts': time.time(),
        'source': 'HuggingFace 공개 모델 API (text-generation · 다운로드순 · 무인증 GET)',
        'models': models,
    }


def get_llm_watch():
    """
    주간 관찰 데이터를 돌려준다. 캐시가 7일 이내면 그대로, 지났으면 재조회.
    반환에 'stale': True 가 있으면 재조회 실패로 옛 캐시를 쓰고 있다는 뜻이다.
    """
    cached = None
    p = _cache_path_read()
    if p:
        try:
            with open(p, encoding='utf-8') as f:
                cached = json.load(f)
        except Exception:
            cached = None
    fresh_enough = (cached and
                    (time.time() - float(cached.get('fetched_ts') or 0))
                    < _TTL_SECONDS)
    if fresh_enough:
        return cached
    try:
        result = _fetch_from_api()
        wp = _cache_path_write()
        if wp:
            with open(wp, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=1)
        return result
    except Exception as e:
        if cached:
            cached['stale'] = True
            cached['stale_reason'] = str(e)[:120]
            return cached
        return {'fetched_at': None, 'models': [],
                'source': 'HuggingFace 공개 모델 API',
                'error': str(e)[:120]}


if __name__ == '__main__':
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    w = get_llm_watch()
    print('fetched_at:', w.get('fetched_at'), '| models:', len(w.get('models', [])))
    for m in w.get('models', [])[:12]:
        print(f"  {m['id']}  dl {m['downloads']:,}  좋아요 {m['likes']}  "
              f"{m['license']}")
