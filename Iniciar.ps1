param([switch]$Restart, [switch]$ForceRestart, [switch]$StopOnly, [switch]$CheckOnly, [switch]$NoBrowser, [ValidateRange(1,65535)][int]$Port = 8765, [string]$Python = '')
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
if ($CheckOnly -and ($ForceRestart -or $StopOnly)) { throw 'CheckOnly nao pode ser combinado com encerramento forcado.' }
# Recovery must work even when Python/imports or the HTTP server are stuck.
if ($ForceRestart -or $StopOnly) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $projectRoot 'Encerrar.ps1') -Port $Port
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    if ($StopOnly) { exit 0 }
}
$bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
function Find-AportePython([string]$Candidate, [switch]$Launcher) {
    $taskProbe = New-Object System.Diagnostics.Process
    try {
        $taskProbe.StartInfo.FileName = $Candidate
        $taskProbe.StartInfo.Arguments = '"' + (Join-Path $projectRoot 'tools\runtime_probe.py') + '" --base --executable'
        if ($Launcher) { $taskProbe.StartInfo.Arguments = '-3 ' + $taskProbe.StartInfo.Arguments }
        $taskProbe.StartInfo.UseShellExecute = $false
        $taskProbe.StartInfo.CreateNoWindow = $true
        $taskProbe.StartInfo.RedirectStandardOutput = $true
        $taskProbe.StartInfo.RedirectStandardError = $true
        $null = $taskProbe.Start()
        $taskOutput = $taskProbe.StandardOutput.ReadToEndAsync()
        $taskErrors = $taskProbe.StandardError.ReadToEndAsync()
        if (-not $taskProbe.WaitForExit(15000)) { $taskProbe.Kill(); $taskProbe.WaitForExit(); return $null }
        $taskResolvedPython = $taskOutput.GetAwaiter().GetResult().Trim()
        $null = $taskErrors.GetAwaiter().GetResult()
        if ($taskProbe.ExitCode -ne 0) { return $null }
        if ($taskResolvedPython) { return $taskResolvedPython }
        if (-not $Launcher) { return $Candidate }
        return $null
    } catch { return $null }
    finally { $taskProbe.Dispose() }
}
$pythonExe = $null
$taskModelPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if ($Python) {
    $pythonExe = Find-AportePython $Python
    if (-not $pythonExe) { throw 'O Python informado nao tem versao ou suporte a SQLite compativel.' }
}
if (-not $pythonExe -and (Test-Path -LiteralPath $taskModelPython)) { $pythonExe = Find-AportePython $taskModelPython }
if (-not $pythonExe -and $pythonCmd) { $pythonExe = Find-AportePython $pythonCmd.Source }
if (-not $pythonExe) {
    $taskPyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($taskPyLauncher) { $pythonExe = Find-AportePython $taskPyLauncher.Source -Launcher }
}
if (-not $pythonExe -and (Test-Path -LiteralPath $bundledPython)) { $pythonExe = Find-AportePython $bundledPython }
if (-not $pythonExe) { throw 'Instale Python 3.11+ com suporte a SQLite e abra novamente. Os pacotes basicos serao preparados automaticamente; IA e opcional.' }
if ($CheckOnly) { Write-Output ('Python compativel: ' + $pythonExe); exit 0 }
$taskPrepareScript = Join-Path $projectRoot 'tools\prepare_runtime.py'
if ((Test-Path -LiteralPath $taskPrepareScript) -and (Test-Path -LiteralPath (Join-Path $projectRoot 'requirements.txt'))) {
    Write-Host 'Conferindo o ambiente da plataforma. Na primeira preparacao ou apos novas dependencias, aguarde a atualizacao...'
    $taskPrepare = New-Object System.Diagnostics.Process
    try {
        $taskPrepare.StartInfo.FileName = $pythonExe
        $taskPrepare.StartInfo.Arguments = '"' + $taskPrepareScript + '"'
        if ($Restart) { $taskPrepare.StartInfo.Arguments += ' --restart --port ' + [string]$Port }
        $taskPrepare.StartInfo.UseShellExecute = $false
        $taskPrepare.StartInfo.CreateNoWindow = $true
        $taskPrepare.StartInfo.RedirectStandardOutput = $true
        $taskPrepare.StartInfo.RedirectStandardError = $true
        $null = $taskPrepare.Start()
        $taskPreparedOutput = $taskPrepare.StandardOutput.ReadToEndAsync()
        $taskPreparedErrors = $taskPrepare.StandardError.ReadToEndAsync()
        $taskPrepare.WaitForExit()
        $taskPreparedPython = $taskPreparedOutput.GetAwaiter().GetResult().Trim()
        $taskPreparationDetails = $taskPreparedErrors.GetAwaiter().GetResult().Trim()
        if ($taskPrepare.ExitCode -ne 0 -or -not $taskPreparedPython) {
            throw ('A preparacao falhou. Confira sua conexao e tente abrir novamente. ' + $taskPreparationDetails)
        }
        $pythonExe = $taskPreparedPython
    } finally { $taskPrepare.Dispose() }
}
$taskAppArguments = @((Join-Path $projectRoot 'app.py'), '--port', [string]$Port)
if ($Restart) { $taskAppArguments += '--restart' }
if ($NoBrowser) { $taskAppArguments += '--no-browser' }
& $pythonExe @taskAppArguments
exit $LASTEXITCODE
