param(
    [string]$Destination = (Join-Path $env:LOCALAPPDATA 'Programs\M3 Reader'),
    [switch]$SkipShortcuts
)
$ErrorActionPreference = 'Stop'
$sourceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$installRoot = [IO.Path]::GetFullPath($Destination)
$sourceGui = Join-Path $sourceRoot 'bin\windows\m3-reader-gui.exe'
$sourceCli = Join-Path $sourceRoot 'bin\windows\m3-reader.exe'
if (-not (Test-Path -LiteralPath $sourceGui) -or -not (Test-Path -LiteralPath $sourceCli)) {
    throw '安装包不完整：找不到 GUI 或 CLI 程序。'
}
$bin = Join-Path $installRoot 'bin\windows'
New-Item -ItemType Directory -Path $bin -Force | Out-Null
if ($sourceRoot -ne $installRoot) {
    Copy-Item -LiteralPath $sourceGui -Destination (Join-Path $bin 'm3-reader-gui.exe') -Force
    Copy-Item -LiteralPath $sourceCli -Destination (Join-Path $bin 'm3-reader.exe') -Force
}
foreach ($relative in @('resources\collected\prts_text', 'resources\collected\terra',
                        'resources\ocr\terra_text', 'resources\local',
                        'resources\updates\new', 'workspace')) {
    New-Item -ItemType Directory -Path (Join-Path $installRoot $relative) -Force | Out-Null
}
$gui = Join-Path $bin 'm3-reader-gui.exe'
if (-not $SkipShortcuts) {
    $shell = New-Object -ComObject WScript.Shell
    $desktop = [Environment]::GetFolderPath('Desktop')
    $startMenu = Join-Path ([Environment]::GetFolderPath('StartMenu')) 'Programs'
    foreach ($folder in @($desktop, $startMenu)) {
        $shortcut = $shell.CreateShortcut((Join-Path $folder 'M3 Reader.lnk'))
        $shortcut.TargetPath = $gui
        $shortcut.WorkingDirectory = $installRoot
        $shortcut.IconLocation = $gui
        $shortcut.Save()
    }
}
Write-Host "安装完成：$installRoot。"
