$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { $python = (Get-Command python -ErrorAction Stop).Source }
& $python -c 'import PyInstaller, PySide6, prompt_toolkit' 2>$null
if ($LASTEXITCODE -ne 0) { throw '构建 Python 需要安装 .[all] 与 pyinstaller。' }
$dest = Join-Path $projectRoot 'bin\windows'
$work = Join-Path $projectRoot 'build\pyinstaller-windows'
& $python -m PyInstaller --noconfirm --clean --onefile --console --name m3-reader --distpath $dest --workpath $work --specpath $work --paths $projectRoot --collect-submodules prts_tool.collectors --exclude-module PySide6 --exclude-module PIL --exclude-module numpy (Join-Path $PSScriptRoot 'entry_cli.py')
if ($LASTEXITCODE -ne 0) { throw 'CLI 构建失败' }
& $python -m PyInstaller --noconfirm --clean --onefile --windowed --name m3-reader-gui --icon (Join-Path $projectRoot 'assets\icon.png') --add-data "$(Join-Path $projectRoot 'assets\icon.png');assets" --distpath $dest --workpath $work --specpath $work --paths $projectRoot --collect-submodules prts_tool.collectors --hidden-import PySide6.QtPdf --hidden-import PySide6.QtPdfWidgets (Join-Path $PSScriptRoot 'entry_gui.py')
if ($LASTEXITCODE -ne 0) { throw 'GUI 构建失败' }
Write-Host "程序位于 $dest。双击 m3-reader-gui.exe；终端中直接运行 m3-reader.exe。"

