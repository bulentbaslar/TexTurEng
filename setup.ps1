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
& $py -m pip install --upgrade pip -q
& $py -m pip install -r "$root\$requirements" -q
if ($LASTEXITCODE -ne 0) { Write-Host "STEP FAILED: pip install"; exit 1 }

# 4. Unit tests
& $py -m pytest "$root\tests" -q
if ($LASTEXITCODE -ne 0) { Write-Host "STEP FAILED: unit tests"; exit 1 }

# 5. Self-test (microphones, key storage, hotkeys, UI, cloud reachability)
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

Write-Host "SETUP OK. Start the app with the desktop shortcut or 'Start Textureng.bat'."
