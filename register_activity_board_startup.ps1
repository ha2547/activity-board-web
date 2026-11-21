param(
    [string]$TaskName = "ActivityBoardWeb",
    [int]$StartupDelaySeconds = 45
)

$ErrorActionPreference = "Stop"

$projectPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = "C:\Users\taeuk.ha\AppData\Local\Programs\Python\Python311\python.exe"
$pythonwExe = "C:\Users\taeuk.ha\AppData\Local\Programs\Python\Python311\pythonw.exe"
$entryScript = Join-Path $projectPath "Activity.py"

if (-not (Test-Path $pythonExe)) {
    throw "Python 실행 파일을 찾을 수 없습니다: $pythonExe"
}

if (-not (Test-Path $entryScript)) {
    throw "실행 스크립트를 찾을 수 없습니다: $entryScript"
}

$taskExecutable = if (Test-Path $pythonwExe) { $pythonwExe } else { $pythonExe }

$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -ne $existingTask) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$action = New-ScheduledTaskAction -Execute $taskExecutable -Argument "`"$entryScript`"" -WorkingDirectory $projectPath

$triggerAtLogOn = New-ScheduledTaskTrigger -AtLogOn
$triggerAtStartup = New-ScheduledTaskTrigger -AtStartup
$triggerAtStartup.Delay = "PT${StartupDelaySeconds}S"

$settings = New-ScheduledTaskSettingsSet `
    -Hidden `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger @($triggerAtLogOn, $triggerAtStartup) `
    -Settings $settings `
    -Principal $principal `
    -Description "Starts and auto-recovers the Activity Board web server." `
    -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName

Write-Host "Scheduled task '$TaskName' registered and started."
Write-Host "Action: $taskExecutable \"$entryScript\""
Write-Host "Triggers: AtLogOn, AtStartup (Delay ${StartupDelaySeconds}s)"

