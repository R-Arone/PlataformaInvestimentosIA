param([string]$Python = 'python', [ValidateRange(0,9999)][int]$Version = 0)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if ($Version -gt 0) {
    $source = [IO.File]::ReadAllText((Join-Path $projectRoot 'app.py'))
    $actual = [regex]::Match($source, '(?m)^APP_VERSION = (\d+)').Groups[1].Value
    if ($Version -ne [int]$actual) { throw 'A versao do pacote deve ser a versao atual do codigo.' }
}
& $Python (Join-Path $PSScriptRoot 'build_installer.py')
exit $LASTEXITCODE
