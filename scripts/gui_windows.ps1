$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$candidates = @()
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $venvPython) { $candidates += $venvPython }
$candidates += @(Get-Command python -All -ErrorAction SilentlyContinue | ForEach-Object Source)
$python = $null
foreach ($candidate in ($candidates | Select-Object -Unique)) {
    if (-not (Test-Path -LiteralPath $candidate)) { continue }
    try {
        & $candidate -c 'import PySide6' 2>$null
        if ($LASTEXITCODE -eq 0) { $python = $candidate; break }
    } catch { continue }
}
if (-not $python) { throw '找不到已安装 PySide6 的 Python。请先安装 docs/APP_README.md 中的 GUI 依赖。' }
& $python (Join-Path $projectRoot 'prts_crawler.py') gui
exit $LASTEXITCODE
