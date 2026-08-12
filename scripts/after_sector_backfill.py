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
    if '--second-pass' in sys.argv:
        # 2차 패스부터 시작 — 기다리지 않고 바로 돌린 뒤 채점·감사까지
        if second_pass() != 0:
            return 1
        if run('채점 (전 샤드 합산)',
               ['scripts/calibration_lab.py', '--limit', '0']) != 0:
            print('채점 실패 — 감사를 돌리지 않는다.', flush=True)
            return 1
        run('표본 감사', ['scripts/sample_audit.py'])
        run('계보 감사 · 원장 정합', ['scripts/lineage_audit.py', '--ledger'])
        run('스냅샷 기준선 갱신', ['scripts/snapshot_guard.py', '--record'])
        print('\n■ 2차 패스까지 전부 끝났다.', flush=True)
        return 0

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


def second_pass():
    """섹터 2차 패스 — 1차에서 못 채운 건을 새 코드로 다시 돌린다.

    ■ 왜 두 번 도나
      1차는 OUT_OF_DOMAIN 수정 **전** 코드로 시작했다. 적정가가 산출
      불가인 종목은 그 반환 dict 에 sector 가 없어 None 으로 기록됐다.
      수정 뒤 표본 12종목으로 재니 11개가 회수됐다(나머지 1개는 ETF —
      원래 업종이 없다). 35,504건 중 약 32,545건이 대상이다.

      --sector-only 는 '섹터 없는 행'을 대상으로 잡으므로, 그냥 한 번 더
      돌리면 자연히 그 건들만 간다. 특별한 지시가 필요 없다.

    ■ 왜 자동으로 반복하지 않나
      회수율이 0 에 수렴하면 멈춰야 하는데, ETF 처럼 **영원히 못 채우는
      건**이 남는다. 그걸 모르고 반복하면 무한히 돈다. 그래서 사람이
      값어치를 재고 한 번 더 돌리는 형태로 둔다 (표본으로 회수율을 먼저
      재는 것이 이 저장소의 방식이다).
    """
    workers = []
    for i, tag in enumerate('abc'):
        workers.append(subprocess.Popen(
            [PY, 'scripts/backfill_subscores.py', '--sector-only',
             '--shard', f'{i}/3', '--limit', '200000',
             # 이름은 반드시 subscore_patch* — 읽는 쪽 glob 이 그 패턴이다
             # (라운드 74 에서 96,218건을 묻은 실수)
             '--out', f'subscore_patch_r74s2_{tag}.jsonl'], cwd=PROJ))
    print(f'2차 패스 워커 {len(workers)}개 시작', flush=True)
    for w in workers:
        w.wait()
    print('2차 패스 완료', flush=True)
    return 0


if __name__ == '__main__':
    _utf8_stdout()
    sys.exit(main())
