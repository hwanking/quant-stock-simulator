# Round 452 - register the swing auto-trading worker in Windows Task Scheduler (this PC, current user).
#
#   .\scripts\register_swing_worker_task.ps1              # register (or update) the task
#   .\scripts\register_swing_worker_task.ps1 -At 08:50    # another start time (before the 09:00 regular open)
#   .\scripts\register_swing_worker_task.ps1 -Unregister  # remove it
#
# Same shape as round 414/415 (gaeum-watch-refresh): plain Python, no prompts, only while the user is logged on,
# weekdays; a missed start (PC off at 08:50) runs as soon as the PC is back (StartWhenAvailable) - the worker
# itself reads the day's regular-session hours from the engine (bitemporal_engine.session_times - 10:00-16:30 on
# the CSAT day) and stops after one post-close cycle; on a holiday it exits at once. The ledger's mode decides
# whether anything is sent to the broker: off / shadow -> nothing, ever. The in-app kill switch and the per-plan
# approval (round 451) still apply. The worker's own lock keeps two instances from running at the same time.
param(
    [switch]$Unregister,
    [string]$At = "08:50"
)
$Name = "gaeum-swing-worker"
if ($Unregister) {
    Unregister-ScheduledTask -TaskName $Name -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output "removed: $Name"
    exit 0
}
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Py = "C:\Python314\python.exe"
if (-not (Test-Path $Py)) { $Py = "python" }
$Script = Join-Path $Root "scripts\run_swing_worker.py"
$Action = New-ScheduledTaskAction -Execute $Py -Argument ('"' + $Script + '" --session --loop 60') -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At $At
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 9) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $Name -Action $Action -Trigger $Trigger -Settings $Settings `
    -RunLevel Limited -Force `
    -Description "Gaeum: swing auto-trading worker - runs every 60s until the regular session close (scripts/run_swing_worker.py --session --loop 60). Sends nothing unless the in-app mode is paper/live." | Out-Null
$Info = Get-ScheduledTask -TaskName $Name | Get-ScheduledTaskInfo
Write-Output ("registered: {0} - weekdays at {1} - next run {2} - last result {3}" -f $Name, $At, $Info.NextRunTime, $Info.LastTaskResult)
