# -*- coding: utf-8 -*-
"""
DESIGN.md 레퍼런스 내려받기 (VoltAgent/awesome-design-md · MIT).

사용자 요청: getdesign.md 카탈로그를 참고 자료로 쓰고 싶다.
카탈로그 사이트의 개별 페이지는 열리지 않고(404), 실제 파일은 MIT 라이선스
GitHub 저장소에 공개돼 있다. 그쪽에서 받는다.

■ 왜 프로젝트 루트가 아니라 references/ 인가
  DESIGN.md 는 프로젝트 루트에 두면 "이 프로젝트의 디자인 사양"이 된다.
  76개를 루트에 쏟으면 어느 것이 우리 사양인지 알 수 없다.
  레퍼런스는 references/design-md/ 에 모으고, 그중 골라 쓴 것만
  우리 DESIGN.md 로 정리한다.

실행: python scripts/fetch_design_md.py
"""
import io
import json
import os
import sys
import urllib.request

try:                       # 라운드 103 — 객체를 갈아끼우지 않는다
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:          # noqa: BLE001
    pass
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, 'references', 'design-md')

RAW = ('https://raw.githubusercontent.com/VoltAgent/awesome-design-md/'
       'main/design-md/{name}/DESIGN.md')
#: 저장소 폴더 목록 (GitHub API 는 비로그인 시 시간당 한도가 낮아 raw 로 직접 받는다)
NAMES = ['airbnb', 'airtable', 'apple', 'binance', 'bmw-m', 'bmw', 'bugatti', 'cal', 'claude', 'clay', 'clickhouse', 'cohere', 'coinbase', 'composio', 'cursor', 'dell-1996', 'elevenlabs', 'expo', 'ferrari', 'figma', 'framer', 'hashicorp', 'hp', 'ibm', 'intercom', 'kraken', 'lamborghini', 'linear.app', 'lovable', 'mastercard', 'meta', 'minimax', 'mintlify', 'miro', 'mistral.ai', 'mongodb', 'nike', 'nintendo-2001', 'notion', 'nvidia', 'ollama', 'opencode.ai', 'pinterest', 'playstation', 'posthog', 'raycast', 'renault', 'replicate', 'resend', 'revolut', 'runwayml', 'sanity', 'sentry', 'shopify', 'slack', 'spacex', 'spotify', 'starbucks', 'stripe', 'supabase', 'superhuman', 'tesla', 'theverge', 'together.ai', 'uber', 'vercel', 'vodafone', 'voltagent', 'warp', 'webflow', 'wired', 'wise', 'x.ai', 'zapier']
UA = {'User-Agent': 'gaeum-design-fetch'}
TIMEOUT = 20


def get(url, raw=False):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        data = r.read()
    return data if raw else json.loads(data.decode('utf-8'))


def listing():
    """이름 목록 → (이름, raw URL)."""
    return [(n, RAW.format(name=n)) for n in NAMES]


def main():
    os.makedirs(OUT, exist_ok=True)
    try:
        files = listing()
    except Exception as e:
        print(f'목록을 받지 못했습니다: {type(e).__name__}: {e}')
        return 1
    print(f'저장소에 DESIGN.md {len(files)}개\n')

    ok = fail = skip = 0
    for name, url in files:
        stem = name.lower()
        dst = os.path.join(OUT, f'{stem}.md')
        if os.path.exists(dst) and os.path.getsize(dst) > 200:
            skip += 1
            continue
        try:
            body = get(url, raw=True)
        except Exception as e:
            print(f'  실패 {stem:22s} {type(e).__name__}')
            fail += 1
            continue
        with open(dst, 'wb') as f:
            f.write(body)
        ok += 1
        print(f'  받음 {stem:22s} {len(body):>7,}자')

    print(f'\n새로 받음 {ok} · 이미 있음 {skip} · 실패 {fail}')
    print(f'저장 위치: {OUT}')
    print('\n출처: https://github.com/VoltAgent/awesome-design-md (MIT)')
    print('레퍼런스일 뿐이며, 우리 프로젝트 사양은 루트 CLAUDE.md 와 '
          'docs/ 가 정본이다.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
