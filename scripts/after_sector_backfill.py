# -*- coding: utf-8 -*-
"""
라운드 74 — 섹터 재백필이 끝나면 채점·감사까지 이어서 돌린다.

■ 왜 필요한가
  재백필은 패치 파일에만 쓴다. 원장(virtual_graded.jsonl)에 들어오려면
  채점을 한 번 더 돌려야 한다. 8시간 뒤에 사람이 기억해서 돌리는 것보다
  이어 붙이는 게 낫다.

■ 무엇을 하나
  ① 워커가 끝날 때까지 기다린다
     — 완료 신호는 **패치 파일이 더 이상 자라지 않는 것**으로 본다.
       프로세스 수로 보면 다른 파이썬 작업까지 세게 된다.
       연속 STILL 회 동안 증가가 없으면 끝난 것으로 판단한다.
  ② calibration_lab 로 전 샤드 합쳐 채점 (원장 갱신)
  ③ sample_audit · lineage_audit --ledger 로 다시 잰다
  ④ snapshot_guard --record 로 기준선 갱신

  각 단계는 실패해도 다음으로 넘어가지 않는다 — 채점이 안 됐는데 감사만
  돌면 옛 숫자를 새 숫자처럼 보고하게 된다.

    C:/Python314/python.exe scripts/after_sector_backfill.py
"""
import glob
import io
import os
import subprocess
import sys
import time

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(PROJ, '.portfolio')
PY = sys.executable

#: 몇 번 연속으로 증가가 없으면 끝난 것으로 보나 (60초 간격)
STILL = 8
#: 최대 대기 (안전장치 — 무한 대기 금지)
MAX_WAIT_SEC = 14 * 3600


def _utf8_stdout():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:                                          # noqa: BLE001
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')


def lines():
    n = 0
    for path in glob.glob(os.path.join(P, 'subscore_sector_*.jsonl')):
        with open(path, encoding='utf-8', errors='replace') as f:
            n += sum(1 for ln in f if ln.strip())
    return n


def run(label, args):
    print(f'\n=== {label} ===', flush=True)
    t0 = time.time()
    rc = subprocess.run([PY] + args, cwd=PROJ).returncode
    print(f'--- {label} 종료코드 {rc} · {time.time() - t0:,.0f}s', flush=True)
    return rc


def main():
    print('■ 섹터 재백필이 끝나기를 기다린다', flush=True)
    t0 = time.time()
    last, still = lines(), 0
    while time.time() - t0 < MAX_WAIT_SEC:
        time.sleep(60)
        cur = lines()
        if cur > last:
            still = 0
            print(f'  {cur:,}건 (+{cur - last})', flush=True)
        else:
            still += 1
            print(f'  {cur:,}건 · 정지 {still}/{STILL}', flush=True)
        last = cur
        if still >= STILL:
            break
    else:
        print(f'최대 대기({MAX_WAIT_SEC // 3600}시간)를 넘겼다 — '
              f'그래도 진행한다. 남은 건은 다음에 이어서 돌린다.', flush=True)
    print(f'\n재백필 산출 {last:,}건 — 채점으로 넘어간다.', flush=True)

    if run('채점 (전 샤드 합산)',
           ['scripts/calibration_lab.py', '--limit', '0']) != 0:
        print('채점이 실패했다 — 감사를 돌리지 않는다. '
              '옛 숫자를 새 숫자처럼 보고하지 않기 위해서다.', flush=True)
        return 1
    run('표본 감사', ['scripts/sample_audit.py'])
    run('계보 감사 · 원장 정합', ['scripts/lineage_audit.py', '--ledger'])
    run('스냅샷 기준선 갱신', ['scripts/snapshot_guard.py', '--record'])
    print('\n■ 전부 끝났다.', flush=True)
    return 0


if __name__ == '__main__':
    _utf8_stdout()
    sys.exit(main())
