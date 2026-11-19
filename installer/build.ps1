# Builds dist\Textureng (app folder) and dist\Textureng-Setup.exe (installer).
# The GPU (CUDA) libraries are left out, so the result is small and runs on any PC:
# cloud speech + cloud cleanup, with local Whisper on CPU as an offline fallback.
# The natural read-aloud voices (sherpa-onnx, which includes GPL-3.0 espeak-ng) are
# left out too, so the installer stays MIT; it reads aloud with the Windows voices.
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$py = "$root\.venv\Scripts\python.exe"

& $py -m PyInstaller --noconfirm --clean --windowed --name Textureng `
    --icon "$root\textureng.ico" `
    --exclude-module nvidia `
    --exclude-module sherpa_onnx `
    --collect-submodules winrt `
    --collect-data faster_whisper `
    --collect-submodules keyring.backends `
    --hidden-import win32ctypes.core `
    --distpath "$root\dist" --workpath "$root\build" --specpath "$root\build" `
    "$root\run.pyw"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 not found (winget install JRSoftware.InnoSetup)" }
& $iscc /Q "$root\installer\Textureng.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
Get-Item "$root\dist\Textureng-Setup.exe" | Select-Object FullName, @{n = "MB"; e = { [math]::Round($_.Length / 1MB) } }
