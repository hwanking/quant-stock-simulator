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
#
# Round 462 - recovery within the session: the trigger repeats every -EveryMinutes for -ForHours after -At. While the
# worker is running, Task Scheduler does not start another one (MultipleInstances IgnoreNew); if the worker died
# mid-session, the next repetition starts it again within -EveryMinutes. After a successful post-close cycle the worker
# writes .portfolio/swing_worker_session.json for that day and later repetitions exit at once. The 10-minute default is an
# operating choice (up to that long without stop-loss protection after a crash vs. one quick python start per repetition),
# not a measured value. 8 hours from 08:50 reaches 16:50 (the CSAT-day session ends 16:30). -EveryMinutes 0 = no repetition.
param(
    [switch]$Unregister,
    [string]$At = "08:50",
    [int]$EveryMinutes = 10,
    [int]$ForHours = 8
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
# Start boundary: today if today's window (At .. At + ForHours) has not ended yet, otherwise tomorrow - registering after the
# window would otherwise count every past repetition slot of today as a 'missed run' (seen 2026-10-09: 47 on a holiday evening).
$AtToday = [datetime]::Today.Add([timespan]::Parse($At))
$WindowEnd = $AtToday.AddHours([Math]::Max($ForHours, 0))
$StartAt = if ((Get-Date) -lt $WindowEnd) { $AtToday } else { $AtToday.AddDays(1) }
$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At $StartAt
if ($EveryMinutes -gt 0) {
    # A weekly trigger takes its repetition from a one-time trigger (New-ScheduledTaskTrigger -Weekly has no repetition parameters).
    $Trigger.Repetition = (New-ScheduledTaskTrigger -Once -At $StartAt -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes) `
        -RepetitionDuration (New-TimeSpan -Hours $ForHours)).Repetition
}
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 9) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $Name -Action $Action -Trigger $Trigger -Settings $Settings `
    -RunLevel Limited -Force `
    -Description "Gaeum: swing auto-trading worker - runs every 60s until the regular session close (scripts/run_swing_worker.py --session --loop 60). Called again every $EveryMinutes min during the session; a running worker is not doubled and a finished day exits at once. New buys only in paper/live mode; protection of auto-managed holdings runs in any mode." | Out-Null
$Info = Get-ScheduledTask -TaskName $Name | Get-ScheduledTaskInfo
$Rep = (Get-ScheduledTask -TaskName $Name).Triggers[0].Repetition.Interval
Write-Output ("registered: {0} - weekdays at {1} - repeat {2} - next run {3} - last result {4}" -f $Name, $At, $Rep, $Info.NextRunTime, $Info.LastTaskResult)
