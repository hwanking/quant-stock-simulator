# Round 414 - register the nightly watchlist refresh in Windows Task Scheduler (this PC, current user).
#
#   .\scripts\register_watch_refresh_task.ps1              # register (or update) the task
#   .\scripts\register_watch_refresh_task.ps1 -At 17:00    # another start time (must be after the 15:30 regular close)
#   .\scripts\register_watch_refresh_task.ps1 -Unregister  # remove it
#
# Why a Windows task and not a Claude scheduled task: the Claude ones never did any work unattended
# (round 412 - four runs marked "success" with zero output). This task runs plain Python with no
# prompts. It runs only while the user is logged on, weekdays, after the regular session close;
# a missed start (PC off) runs as soon as the PC is back (StartWhenAvailable). The script itself
# decides whether anything is due (holiday -> nothing) and re-reads the file before each save.
param(
    [switch]$Unregister,
    [string]$At = "17:00"
)
$Name = "gaeum-watch-refresh"
if ($Unregister) {
    Unregister-ScheduledTask -TaskName $Name -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output "removed: $Name"
    exit 0
}
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
# Round 485 - pythonw.exe: no console window. The user saw windows flashing; a task launched as python.exe opens a console
#   (the worker for the whole session plus every repetition, the nightly for minutes). The scripts write their own logs
#   under .portfolio (*_run.txt) and start their child steps as python.exe with CREATE_NO_WINDOW (noconsole.py).
$Py = "C:\Python314\pythonw.exe"
if (-not (Test-Path $Py)) { $Py = "C:\Python314\python.exe" }
if (-not (Test-Path $Py)) { $Py = "pythonw" }
# Round 415 - the task runs both steps a person used to press: the case tracker (run_daily_improvement.py,
# the "after close, run now" button) and the watchlist re-measure (refresh_watchlist.py). nightly_local.py runs them in order.
$Script = Join-Path $Root "scripts\nightly_local.py"
$Action = New-ScheduledTaskAction -Execute $Py -Argument ('"' + $Script + '"') -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At $At
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $Name -Action $Action -Trigger $Trigger -Settings $Settings `
    -RunLevel Limited -Force `
    -Description "Gaeum: after the regular session close - freeze/grade premarket picks (run_daily_improvement.py) then re-measure watchlist snapshots (refresh_watchlist.py), via scripts/nightly_local.py." | Out-Null
$Info = Get-ScheduledTask -TaskName $Name | Get-ScheduledTaskInfo
Write-Output ("registered: {0} - weekdays at {1} - next run {2} - last result {3}" -f $Name, $At, $Info.NextRunTime, $Info.LastTaskResult)
