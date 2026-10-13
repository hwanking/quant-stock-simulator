# Round 527 - register the one-off minute-bar backfill in Windows Task Scheduler (this PC, current user).
#
#   .\scripts\register_minute_backfill_task.ps1               # register (or update): starts in 1 minute, repeats every 30 min for 5 days
#   .\scripts\register_minute_backfill_task.ps1 -Days 7       # a longer window
#   .\scripts\register_minute_backfill_task.ps1 -Unregister   # remove it
#
# The user asked for the minute bars of the research ledger's fixed list (scripts/calibration_lab.py TICKERS + HOLDOUT +
# EXPANSION, 599 codes) as far back as Korea Investment keeps them (about one year). That is ~154k (code, day) pairs at
# ~0.77 s each - tens of hours - so the script stops by itself (collect_minute_bars.backfill_block): during the trading
# session the swing worker uses the same app key (08:40 .. close + 30 min), 20:50 .. 21:00 before the nightly job, while
# the nightly job is running, and when free disk falls below 20 GB. It always fetches the oldest days first (the server
# drops the oldest day every day). One collector at a time (lock file in .portfolio/day_bars). Read-only queries - no orders.
#
# Every repetition runs the same command; when there is nothing left or the window is closed it exits within seconds
# (MultipleInstances IgnoreNew keeps a running one from being doubled). The trigger ends after -Days and the task deletes
# itself one day later (DeleteExpiredTaskAfter), so nothing is left behind. The 30-minute repetition and the 5-day window are
# operating choices, not measured values. Log: .portfolio/day_bars/_backfill_run.txt
param(
    [switch]$Unregister,
    [int]$Days = 5,
    [int]$EveryMinutes = 30
)
$Name = "gaeum-minute-backfill"
if ($Unregister) {
    Unregister-ScheduledTask -TaskName $Name -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output "removed: $Name"
    exit 0
}
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
# Round 485 - pythonw.exe: no console window (the script writes its own log).
$Py = "C:\Python314\pythonw.exe"
if (-not (Test-Path $Py)) { $Py = "C:\Python314\python.exe" }
if (-not (Test-Path $Py)) { $Py = "pythonw" }
$Script = Join-Path $Root "scripts\collect_minute_bars.py"
$Action = New-ScheduledTaskAction -Execute $Py -Argument ('"' + $Script + '" --universe pool --days 260 --backfill --apply') -WorkingDirectory $Root
$StartAt = (Get-Date).AddMinutes(1)
$Trigger = New-ScheduledTaskTrigger -Once -At $StartAt -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes) `
    -RepetitionDuration (New-TimeSpan -Days $Days)
$Trigger.EndBoundary = $StartAt.AddDays($Days).ToString("s")
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 13) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -DeleteExpiredTaskAfter (New-TimeSpan -Days 1)
Register-ScheduledTask -TaskName $Name -Action $Action -Trigger $Trigger -Settings $Settings `
    -RunLevel Limited -Force `
    -Description "Gaeum: one-off minute-bar backfill of the research ledger's fixed list (read-only queries, no orders). Stops itself during the trading session, before and during the nightly job, and on low disk; resumes on the next repetition. Ends after $Days days and deletes itself." | Out-Null
$Info = Get-ScheduledTask -TaskName $Name | Get-ScheduledTaskInfo
Write-Output ("registered: {0} - every {1} min until {2} - next run {3} - last result {4}" -f $Name, $EveryMinutes, $Trigger.EndBoundary, $Info.NextRunTime, $Info.LastTaskResult)
