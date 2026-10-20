param([switch]$Restart, [switch]$ForceRestart, [switch]$StopOnly, [switch]$CheckOnly, [switch]$NoBrowser, [ValidateRange(1,65535)][int]$Port = 8765)
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
function Test-AporteRuntime([string]$Candidate, [switch]$AI) {
    $taskProbe = New-Object System.Diagnostics.Process
    try {
        $taskProbe.StartInfo.FileName = $Candidate
        $taskProbe.StartInfo.Arguments = '"' + (Join-Path $projectRoot 'tools\runtime_probe.py') + '"'
        if ($AI) { $taskProbe.StartInfo.Arguments += ' --ai' }
        $taskProbe.StartInfo.UseShellExecute = $false
        $taskProbe.StartInfo.CreateNoWindow = $true
        $taskProbe.StartInfo.RedirectStandardOutput = $true
        $taskProbe.StartInfo.RedirectStandardError = $true
        $null = $taskProbe.Start()
        $taskOutput = $taskProbe.StandardOutput.ReadToEndAsync()
        $taskErrors = $taskProbe.StandardError.ReadToEndAsync()
        if (-not $taskProbe.WaitForExit(30000)) { $taskProbe.Kill(); $taskProbe.WaitForExit(); return $false }
        $null = $taskOutput.GetAwaiter().GetResult()
        $null = $taskErrors.GetAwaiter().GetResult()
        return $taskProbe.ExitCode -eq 0
    } catch { return $false }
    finally { $taskProbe.Dispose() }
}
$pythonExe = $null
$taskModelPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if ((Test-Path -LiteralPath $taskModelPython) -and (Test-AporteRuntime $taskModelPython -AI)) { $pythonExe = $taskModelPython }
elseif ($pythonCmd -and (Test-AporteRuntime $pythonCmd.Source -AI)) { $pythonExe = $pythonCmd.Source }
elseif ((Test-Path -LiteralPath $bundledPython) -and (Test-AporteRuntime $bundledPython)) { $pythonExe = $bundledPython }
elseif ($pythonCmd -and (Test-AporteRuntime $pythonCmd.Source)) { $pythonExe = $pythonCmd.Source }
if (-not $pythonExe) { throw 'Nenhum Python compativel encontrado. Prepare Python 3.11+ com os pacotes de requirements.txt. Os pacotes de IA sao opcionais.' }
if ($CheckOnly) { Write-Output ('Python compativel: ' + $pythonExe); exit 0 }
$taskAppArguments = @((Join-Path $projectRoot 'app.py'), '--port', [string]$Port)
if ($Restart) { $taskAppArguments += '--restart' }
if ($NoBrowser) { $taskAppArguments += '--no-browser' }
& $pythonExe @taskAppArguments
exit $LASTEXITCODE
