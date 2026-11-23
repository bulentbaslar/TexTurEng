# Sets TexTurEng up from source in this folder: virtual environment, packages,
# tests, self-test and a desktop shortcut. Safe to run again.
#   powershell -NoProfile -ExecutionPolicy Bypass -File setup.ps1
param(
    [switch]$Laptop,      # force the no-GPU package set even if a GPU is present
    [switch]$NoShortcut   # skip the desktop shortcut
)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

# 1. Python 3.10 - 3.13
$python = $null
foreach ($candidate in @(@("py", "-3.11"), @("py", "-3.12"), @("py", "-3.13"), @("py", "-3.10"), @("python"))) {
    try {
        $exe = $candidate[0]; $rest = @($candidate | Select-Object -Skip 1)
        $version = & $exe @rest -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $version -match '^3\.(10|11|12|13)$') { $python = $candidate; break }
    } catch { }
}
if (-not $python) {
    Write-Host "STEP FAILED: Python 3.10-3.13 not found. Install it with:  winget install Python.Python.3.11"
    exit 1
}
Write-Host "Python: $($python -join ' ') ($version)"

# 2. Virtual environment
if (-not (Test-Path "$root\.venv\Scripts\python.exe")) {
    $exe = $python[0]; $rest = @($python | Select-Object -Skip 1)
    & $exe @rest -m venv "$root\.venv"
}
$py = "$root\.venv\Scripts\python.exe"

# 3. Packages: GPU libraries only when a compatible GPU is present
$hasGpu = $false
if (-not $Laptop) { try { nvidia-smi -L *> $null; $hasGpu = ($LASTEXITCODE -eq 0) } catch { } }
$requirements = if ($hasGpu) { "requirements.txt" } else { "requirements-laptop.txt" }
Write-Host "GPU: $hasGpu -> installing $requirements"
Write-Host ""
Write-Host "Installing packages, this can take 5-15 minutes..." -ForegroundColor Cyan
Write-Host "(several hundred MB are downloaded; the lines below show the progress. Please keep this window open.)"
Write-Host ""
& $py -m pip install --upgrade pip -q
& $py -m pip install -r "$root\$requirements" --progress-bar on --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { Write-Host "STEP FAILED: pip install"; exit 1 }
Write-Host ""
Write-Host "Packages installed." -ForegroundColor Cyan

# 4. Unit tests
Write-Host "Running the tests (under a minute)..." -ForegroundColor Cyan
& $py -m pytest "$root\tests" -q
if ($LASTEXITCODE -ne 0) { Write-Host "STEP FAILED: unit tests"; exit 1 }

# 5. Self-test (microphones, key storage, hotkeys, UI, cloud reachability)
Write-Host "Checking microphone, voices and settings..." -ForegroundColor Cyan
$report = Join-Path $env:TEMP "textureng-selftest.json"
& $py -m textureng --selftest $report
Get-Content $report
if ((Get-Content $report -Raw) -match "FAILED") { Write-Host "STEP FAILED: self-test (see report above)"; exit 1 }

# 6. Desktop shortcut
if (-not $NoShortcut) {
    $link = Join-Path ([Environment]::GetFolderPath("Desktop")) "TexTurEng.lnk"
    $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($link)
    $shortcut.TargetPath = "$root\.venv\Scripts\pythonw.exe"
    $shortcut.Arguments = "`"$root\run.pyw`""
    $shortcut.WorkingDirectory = $root
    $shortcut.IconLocation = "$root\textureng.ico"
    $shortcut.Description = "TexTurEng AI dictation and translation"
    $shortcut.Save()
    Write-Host "Shortcut: $link"
}

# 7. Ollama (optional, for local cleanup)
try {
    $tags = Invoke-RestMethod "http://127.0.0.1:11434/api/tags" -TimeoutSec 3
    Write-Host "Ollama models: $(($tags.models | ForEach-Object { $_.name }) -join ', ')"
} catch { Write-Host "Ollama: not running (only needed for local cleanup)" }

# How to start it: the typed command differs between the Command Prompt and PowerShell
# (in the Command Prompt the quotes are needed: without them "start" is read as
# Windows' own START command).
$parentId = (Get-CimInstance Win32_Process -Filter "ProcessId=$PID" -ErrorAction SilentlyContinue).ParentProcessId
$parentName = (Get-Process -Id $parentId -ErrorAction SilentlyContinue).ProcessName
$cmdLine = '"Start Textureng.bat"'
$psLine = '& ".\Start Textureng.bat"'
Write-Host ""
Write-Host "SETUP OK." -ForegroundColor Green
Write-Host ""
Write-Host "To start TexTurEng:"
if (-not $NoShortcut) { Write-Host "  - double-click the TexTurEng shortcut on your desktop, or" }
if ($parentName -eq "cmd") {
    Write-Host "  - type this in this window, exactly as shown (with the quotes), and press Enter:"
    Write-Host "      $cmdLine" -ForegroundColor Yellow
} elseif ($parentName -in "powershell", "pwsh") {
    Write-Host "  - type this in this window, exactly as shown, and press Enter:"
    Write-Host "      $psLine" -ForegroundColor Yellow
} else {
    Write-Host "  - in a Command Prompt in $root type (with the quotes):  $cmdLine"
    Write-Host "  - in PowerShell in $root type:  $psLine"
}
Write-Host "TexTurEng then appears as a microphone icon in the system tray (bottom right)."
