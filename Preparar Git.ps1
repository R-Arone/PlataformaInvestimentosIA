$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.git'))) { & git init -b main }
    if ($LASTEXITCODE -ne 0) { throw 'Nao foi possivel preparar o Git.' }
    & git config core.hooksPath .githooks
    & python tools/check_git_safety.py
    if ($LASTEXITCODE -ne 0) { throw 'A conferencia encontrou arquivos privados. Nada foi enviado.' }
    Write-Host 'Protecoes de commit e push configuradas. Nenhum remoto foi adicionado.'
} finally { Pop-Location }
