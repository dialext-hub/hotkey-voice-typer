# build.ps1 — builds hotkey-voice-typer-setup.exe
# Prerequisites: pip install pyinstaller; Inno Setup with iscc in PATH
# Run from: C:\Projects\hotkey-voice-typer\

Write-Host "=== hotkey-voice-typer build ===" -ForegroundColor Cyan

Write-Host "Step 1: PyInstaller..."
python -m PyInstaller voice_typer.py --onefile --noconsole --name hotkey-voice-typer --clean
if ($LASTEXITCODE -ne 0) { Write-Error "PyInstaller failed"; exit 1 }

$exe = "dist\hotkey-voice-typer.exe"
if (-not (Test-Path $exe)) { Write-Error "exe not found: $exe"; exit 1 }
Write-Host "  OK: $exe" -ForegroundColor Green

Write-Host "Step 2: Inno Setup..."
iscc "installer\setup.iss"
if ($LASTEXITCODE -ne 0) { Write-Error "Inno Setup failed"; exit 1 }

$installer = "installer\hotkey-voice-typer-setup.exe"
if (-not (Test-Path $installer)) { Write-Error "installer not found: $installer"; exit 1 }
Write-Host "  OK: $installer" -ForegroundColor Green

Write-Host "=== Done! ===" -ForegroundColor Cyan
