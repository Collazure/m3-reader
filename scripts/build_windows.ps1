$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = if ($env:M3_READER_PYTHON) { $env:M3_READER_PYTHON } else { Join-Path $projectRoot '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $python)) { $python = (Get-Command python -ErrorAction Stop).Source }
& $python -c 'import PyInstaller, PySide6, prompt_toolkit' 2>$null
if ($LASTEXITCODE -ne 0) { throw '构建 Python 需要安装 .[all] 与 pyinstaller。' }
$dest = Join-Path $projectRoot 'bin\windows'
$work = Join-Path $projectRoot 'build\pyinstaller-windows'
$excludes = @(
    '--exclude-module','PySide6.Qt3DAnimation',
    '--exclude-module','PySide6.Qt3DCore',
    '--exclude-module','PySide6.Qt3DExtras',
    '--exclude-module','PySide6.Qt3DInput',
    '--exclude-module','PySide6.Qt3DLogic',
    '--exclude-module','PySide6.Qt3DRender',
    '--exclude-module','PySide6.QtBluetooth',
    '--exclude-module','PySide6.QtCharts',
    '--exclude-module','PySide6.QtDataVisualization',
    '--exclude-module','PySide6.QtGraphs',
    '--exclude-module','PySide6.QtGraphsWidgets',
    '--exclude-module','PySide6.QtHelp',
    '--exclude-module','PySide6.QtHttpServer',
    '--exclude-module','PySide6.QtLocation',
    '--exclude-module','PySide6.QtMultimedia',
    '--exclude-module','PySide6.QtMultimediaWidgets',
    '--exclude-module','PySide6.QtNetworkAuth',
    '--exclude-module','PySide6.QtNfc',
    '--exclude-module','PySide6.QtPositioning',
    '--exclude-module','PySide6.QtQml',
    '--exclude-module','PySide6.QtQuick',
    '--exclude-module','PySide6.QtQuick3D',
    '--exclude-module','PySide6.QtQuickControls2',
    '--exclude-module','PySide6.QtQuickWidgets',
    '--exclude-module','PySide6.QtRemoteObjects',
    '--exclude-module','PySide6.QtScxml',
    '--exclude-module','PySide6.QtSensors',
    '--exclude-module','PySide6.QtSerialBus',
    '--exclude-module','PySide6.QtSerialPort',
    '--exclude-module','PySide6.QtSpatialAudio',
    '--exclude-module','PySide6.QtSql',
    '--exclude-module','PySide6.QtStateMachine',
    '--exclude-module','PySide6.QtTest',
    '--exclude-module','PySide6.QtTextToSpeech',
    '--exclude-module','PySide6.QtUiTools',
    '--exclude-module','PySide6.QtWebChannel',
    '--exclude-module','PySide6.QtWebEngineCore',
    '--exclude-module','PySide6.QtWebEngineQuick',
    '--exclude-module','PySide6.QtWebEngineWidgets',
    '--exclude-module','PySide6.QtWebSockets',
    '--exclude-module','PySide6.QtWebView',
    '--exclude-module','tkinter',
    '--exclude-module','unittest',
    '--exclude-module','pydoc',
    '--exclude-module','PIL',
    '--exclude-module','numpy'
)
$backups = @()
foreach ($name in @('m3-reader.exe', 'm3-reader-gui.exe')) {
    $target = Join-Path $dest $name
    if (Test-Path -LiteralPath $target) {
        $backup = "$name.previous-$PID"
        Rename-Item -LiteralPath $target -NewName $backup
        $backups += Join-Path $dest $backup
    }
}
& $python -m PyInstaller --noconfirm --clean --onefile --optimize 2 --console --name m3-reader --distpath $dest --workpath $work --specpath $work --paths $projectRoot --collect-submodules prts_tool.collectors --exclude-module PySide6 @excludes (Join-Path $PSScriptRoot 'entry_cli.py')
if ($LASTEXITCODE -ne 0) { throw 'CLI 构建失败' }
& $python -m PyInstaller --noconfirm --clean --onefile --optimize 2 --windowed --name m3-reader-gui --icon (Join-Path $projectRoot 'assets\icon.png') --add-data "$(Join-Path $projectRoot 'assets\icon.png');assets" --distpath $dest --workpath $work --specpath $work --paths $projectRoot --collect-submodules prts_tool.collectors --hidden-import PySide6.QtPdf --hidden-import PySide6.QtPdfWidgets @excludes (Join-Path $PSScriptRoot 'entry_gui.py')
if ($LASTEXITCODE -ne 0) { throw 'GUI 构建失败' }
foreach ($backup in $backups) {
    Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue
}
Write-Host "程序位于 $dest。双击 m3-reader-gui.exe；终端中直接运行 m3-reader.exe。"

