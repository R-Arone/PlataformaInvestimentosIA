param([switch]$NoShortcuts)
$ErrorActionPreference = 'Stop'
$installRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
$marker = Join-Path $installRoot 'INSTALLATION-MARKER.txt'
if (-not (Test-Path -LiteralPath $marker) -or (Get-Content -LiteralPath $marker -Raw).Trim() -ne 'APORTE-BRASIL-INSTALL-V1') { throw 'Esta pasta nao e uma instalacao valida do Aporte Brasil.' }
if ($installRoot -eq [System.IO.Path]::GetPathRoot($installRoot)) { throw 'Pasta de instalacao invalida.' }
$privateRoot = [System.IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'AporteBrasil'))
if ($installRoot.StartsWith($privateRoot, [System.StringComparison]::OrdinalIgnoreCase)) { throw 'A pasta privada dos dados nao pode ser removida.' }
# Remove only installer-owned files; unexpected user files are preserved.
foreach ($name in @('AporteBrasil.exe','INSTALLATION-MARKER.txt','Uninstall.ps1')) {
    $target = [System.IO.Path]::GetFullPath((Join-Path $installRoot $name))
    if ([System.IO.Path]::GetDirectoryName($target) -ne $installRoot) { throw 'Destino inesperado.' }
    if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Force }
}
$runtimeRoot = [System.IO.Path]::GetFullPath((Join-Path $installRoot '_internal'))
if ([System.IO.Path]::GetDirectoryName($runtimeRoot) -ne $installRoot) { throw 'Destino inesperado.' }
if (Test-Path -LiteralPath $runtimeRoot) { Remove-Item -LiteralPath $runtimeRoot -Recurse -Force }
if (-not $NoShortcuts) {
    $menuRoot = Join-Path ([Environment]::GetFolderPath('Programs')) 'Aporte Brasil'
    foreach ($shortcut in @((Join-Path ([Environment]::GetFolderPath('Desktop')) 'Aporte Brasil.lnk'),(Join-Path $menuRoot 'Aporte Brasil.lnk'),(Join-Path $menuRoot 'Desinstalar Aporte Brasil.lnk'))) {
        if (Test-Path -LiteralPath $shortcut) { Remove-Item -LiteralPath $shortcut -Force }
    }
}
Write-Host 'Aplicativo removido. Dados privados e backups preservados.'
