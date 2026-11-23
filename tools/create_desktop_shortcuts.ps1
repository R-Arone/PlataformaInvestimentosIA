[CmdletBinding()]
param([string]$Destination = [Environment]::GetFolderPath('DesktopDirectory'))

$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$destinationPath = (Resolve-Path -LiteralPath $Destination).ProviderPath
$shell = New-Object -ComObject WScript.Shell

$launchers = @(
    @{ Name = 'Abrir Aporte Brasil'; Icon = 'abrir-aporte.ico'; Description = 'Abrir o Aporte Brasil deste projeto' }
    @{ Name = 'Reiniciar Aporte Brasil'; Icon = 'reiniciar-aporte.ico'; Description = 'Abrir o menu para reiniciar o Aporte Brasil' }
)

foreach ($launcher in $launchers) {
    $target = (Resolve-Path -LiteralPath (Join-Path $project ($launcher.Name + '.cmd'))).ProviderPath
    $iconPath = (Resolve-Path -LiteralPath (Join-Path $project ('packaging/' + $launcher.Icon))).ProviderPath
    $shortcutPath = Join-Path $destinationPath ($launcher.Name + '.lnk')
    $shortcut = $shell.CreateShortcut($shortcutPath)

    if ((Test-Path -LiteralPath $shortcutPath) -and $shortcut.TargetPath -ne $target) {
        Write-Warning "Atalho existente preservado: $shortcutPath"
        continue
    }

    $shortcut.TargetPath = $target
    $shortcut.WorkingDirectory = $project
    $shortcut.IconLocation = "$iconPath,0"
    $shortcut.Description = $launcher.Description
    $shortcut.Save()
    Get-Item -LiteralPath $shortcutPath
}
