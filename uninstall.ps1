# Removes TexTurEng that was set up from source (Git clone or ZIP) with setup.ps1:
# the program folder (including .venv), the desktop shortcut, "Start with Windows",
# settings, history, log, read-aloud voices, the saved cloud API key and the
# downloaded Whisper speech model. Ollama and Python are separate programs and are
# not removed (see the README).
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File uninstall.ps1
#
# Options:
#   -WhatIf            only list what would be removed, change nothing
#   -Yes               do not ask for confirmation
#   -KeepSettings      keep settings, history and voices (%APPDATA%\Textureng)
#   -KeepSpeechModel   keep the downloaded Whisper speech model
param(
    [switch]$WhatIf,
    [switch]$Yes,
    [switch]$KeepSettings,
    [switch]$KeepSpeechModel,
    # The following exist for testing; normal use never needs them.
    [string]$ProgramDir = $PSScriptRoot,
    [string]$SettingsDir = (Join-Path $env:APPDATA "Textureng"),
    [string]$OldSettingsDir = (Join-Path $env:APPDATA "VoxPolish"),
    [string]$ModelCacheDir = (Join-Path $env:USERPROFILE ".cache\huggingface\hub"),
    [string]$DesktopDir = [Environment]::GetFolderPath("Desktop"),
    [string[]]$CredentialNames = @("Textureng", "VoxPolish")
)
$ErrorActionPreference = "Stop"
$ProgramDir = (Resolve-Path $ProgramDir).Path.TrimEnd("\")
$runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"

# Safety check: only ever delete a folder that really is TexTurEng.
foreach ($marker in "textureng\__init__.py", "setup.ps1", "uninstall.ps1") {
    if (-not (Test-Path (Join-Path $ProgramDir $marker))) {
        Write-Host "STOPPED: $ProgramDir does not look like a TexTurEng folder (missing $marker). Nothing was removed."
        exit 1
    }
}

# The same folder can be written in long form or in Windows' short 8.3 form
# (C:\Users\BULENT~1\...); recognise both.
$programForms = @($ProgramDir.ToLower())
try {
    $fso = New-Object -ComObject Scripting.FileSystemObject
    $programForms += $fso.GetFolder($ProgramDir).ShortPath.TrimEnd("\").ToLower()
    $programForms += (Get-Item -LiteralPath $ProgramDir).FullName.TrimEnd("\").ToLower()
} catch { }
$programForms = @($programForms | Select-Object -Unique)

$programLong = (Get-Item -LiteralPath $ProgramDir).FullName.TrimEnd("\").ToLower()

function Points-Here([string]$text) {
    if (-not $text) { return $false }
    $lower = $text.ToLower()
    foreach ($form in $programForms) { if ($lower.Contains($form)) { return $true } }
    # Paths can mix short and long forms; let Windows expand each one and compare.
    $candidates = @([regex]::Matches($text, '"([^"]+)"') | ForEach-Object { $_.Groups[1].Value }) + ($text -split '\s+')
    foreach ($candidate in $candidates) {
        if ($candidate -notmatch '^[A-Za-z]:\\') { continue }
        try { $long = (Get-Item -LiteralPath $candidate -ErrorAction Stop).FullName.TrimEnd("\").ToLower() } catch { continue }
        if ($long -eq $programLong -or $long.StartsWith($programLong + "\")) { return $true }
    }
    return $false
}

# ---- collect what is there ----------------------------------------------------
# Each step is (description, kind, target); nothing is changed while collecting.
$plan = New-Object System.Collections.Generic.List[object]
function Add-Step([string]$what, [string]$kind, $target) {
    $plan.Add([pscustomobject]@{ What = $what; Kind = $kind; Target = $target })
}

$running = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like "python*.exe" -and (Points-Here $_.CommandLine) } |
    ForEach-Object { $_.ProcessId })
if ($running.Count) { Add-Step "Close TexTurEng (it is running)" "process" $running }

$startup = Get-ItemProperty $runKey -ErrorAction SilentlyContinue
foreach ($name in "Textureng", "VoxPolish") {
    if ($startup -and (Points-Here $startup.$name)) { Add-Step "'Start with Windows' entry" "startup" $name }
}

$shell = New-Object -ComObject WScript.Shell
Get-ChildItem $DesktopDir -Filter "*.lnk" -ErrorAction SilentlyContinue |
    Where-Object { $_.BaseName -in "TexTurEng", "Textureng", "VoxPolish" } |
    ForEach-Object {
        $link = $shell.CreateShortcut($_.FullName)
        if ((Points-Here $link.TargetPath) -or (Points-Here $link.Arguments)) {
            Add-Step "Desktop shortcut $($_.Name)" "file" $_.FullName
        }
    }

# cmdkey lists lines like "Target: LegacyGeneric:target=Textureng" ("Hedef:" in Turkish).
$targets = @(cmdkey /list 2>$null | ForEach-Object {
    $line = "$_"
    foreach ($credName in $CredentialNames) {
        if ($line -match [regex]::Escape($credName) -and $line -match ":\s*(\S.*)$") {
            ($Matches[1].Trim() -replace "^LegacyGeneric:target=", "")
        }
    }
} | Select-Object -Unique)
foreach ($target in $targets) { Add-Step "Saved cloud API key ($target) in Credential Manager" "credential" $target }

if (-not $KeepSettings) {
    foreach ($dir in $SettingsDir, $OldSettingsDir) {
        if (Test-Path $dir) { Add-Step "Settings, history, log and voices: $dir" "folder" $dir }
    }
}

if (-not $KeepSpeechModel) {
    Get-ChildItem $ModelCacheDir -Directory -Filter "models--*faster-whisper*" -ErrorAction SilentlyContinue |
        ForEach-Object { Add-Step "Whisper speech model: $($_.Name)" "folder" $_.FullName }
}

# The program folder goes last. It is deleted just after this script ends, because
# a folder cannot be deleted while the script inside it is still running.
Add-Step "Program folder (including .venv): $ProgramDir" "programdir" $ProgramDir

# ---- show, confirm, remove -------------------------------------------------------
Write-Host ""
Write-Host "TexTurEng uninstall will remove:"
$plan | ForEach-Object { Write-Host "  - $($_.What)" }
Write-Host ""
Write-Host "Not removed: Ollama and its models, and Python (other programs may use them; see the README)."
if ($KeepSettings) { Write-Host "Kept: $SettingsDir (-KeepSettings)." }
if ($KeepSpeechModel) { Write-Host "Kept: the Whisper speech model (-KeepSpeechModel)." }
Write-Host ""

if ($WhatIf) { Write-Host "WhatIf: nothing was changed."; exit 0 }
if (-not $Yes) {
    $answer = Read-Host "Remove all of this? This cannot be undone. Type YES to continue"
    if ($answer -cne "YES") { Write-Host "Cancelled. Nothing was removed."; exit 0 }
}

$failed = 0
$deleteProgramDir = $false
foreach ($step in $plan) {
    try {
        switch ($step.Kind) {
            "process"    { $step.Target | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }; Start-Sleep 2 }
            "startup"    { Remove-ItemProperty -Path $runKey -Name $step.Target }
            "file"       { Remove-Item -LiteralPath $step.Target -Force }
            "credential" { cmdkey /delete:"$($step.Target)" | Out-Null; if ($LASTEXITCODE) { throw "cmdkey failed" } }
            "folder"     { Remove-Item -LiteralPath $step.Target -Recurse -Force }
            "programdir" { $deleteProgramDir = $true }
        }
        if ($step.Kind -ne "programdir") { Write-Host "  removed: $($step.What)" }
    } catch {
        $failed++
        Write-Host "  COULD NOT REMOVE: $($step.What) ($($_.Exception.Message))"
    }
}

if ($deleteProgramDir) {
    Set-Location ([IO.Path]::GetTempPath())
    Start-Process -FilePath "cmd.exe" -WindowStyle Hidden `
        -ArgumentList "/c timeout /t 3 /nobreak >nul & rmdir /s /q `"$ProgramDir`""
    Write-Host "  removing the program folder: it disappears a few seconds after this window closes"
}

Write-Host ""
if ($failed) {
    Write-Host "UNINSTALL FINISHED WITH $failed PROBLEM(S): see the lines above."
    exit 1
}
Write-Host "UNINSTALL OK. TexTurEng has been removed."
