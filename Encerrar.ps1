param([ValidateRange(1,65535)][int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
$appPath = Join-Path $projectRoot 'app.py'
$exePath = Join-Path $projectRoot 'AporteBrasil.exe'

function Test-AporteProcess($Process) {
    if (-not $Process -or $Process.ProcessId -eq $PID) { return $false }
    if ($Process.ExecutablePath -and $Process.ExecutablePath.Equals($exePath, [System.StringComparison]::OrdinalIgnoreCase)) {
        $isApp = $true
    } else {
        # Require an entire absolute script argument, never just a name or a port.
        if ($Process.Name -notmatch '^python(?:w|\d+(?:\.\d+)?)?\.exe$') { return $false }
        $scriptPattern = '(?i)^\s*(?:"[^"]+"|\S+)\s+(?:(?:-[uBEIsSO]|-OO)\s+)*(?:"' + [regex]::Escape($appPath) + '"|' + [regex]::Escape($appPath) + ')(?=\s|$)'
        $isApp = $Process.CommandLine -match $scriptPattern
    }
    if (-not $isApp -or -not $Process.CommandLine) { return $false }
    $portMatch = [regex]::Match($Process.CommandLine, '(?:^|\s)--port(?:\s+|=)"?(\d+)"?(?=\s|$)')
    $processPort = 8765
    if ($portMatch.Success) { $processPort = [int]$portMatch.Groups[1].Value }
    return $processPort -eq $Port
}

function Test-LocalPort {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $connection = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
        if (-not $connection.AsyncWaitHandle.WaitOne(300)) { return $false }
        $client.EndConnect($connection)
        return $true
    } catch { return $false }
    finally { $client.Dispose() }
}

try {
    $targets = @(Get-CimInstance Win32_Process | Where-Object { Test-AporteProcess $_ })
    foreach ($target in $targets) {
        # Recheck identity immediately before killing to avoid stale/reused PIDs.
        $current = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $target.ProcessId)
        if (-not $current) { continue }
        if ($current.CreationDate -ne $target.CreationDate -or -not (Test-AporteProcess $current)) {
            throw 'O processo mudou durante a verificacao. Execute novamente.'
        }
        Write-Host ('Encerrando Aporte Brasil e seus subprocessos (PID ' + $target.ProcessId + ')...')
        $killer = New-Object System.Diagnostics.Process
        try {
            $killer.StartInfo.FileName = Join-Path $env:SystemRoot 'System32\taskkill.exe'
            $killer.StartInfo.Arguments = '/PID ' + $target.ProcessId + ' /T /F'
            $killer.StartInfo.UseShellExecute = $false
            $killer.StartInfo.CreateNoWindow = $true
            $killer.StartInfo.RedirectStandardOutput = $true
            $killer.StartInfo.RedirectStandardError = $true
            $null = $killer.Start()
            $output = $killer.StandardOutput.ReadToEndAsync()
            $errors = $killer.StandardError.ReadToEndAsync()
            if (-not $killer.WaitForExit(10000)) {
                $killer.Kill()
                throw 'O Windows nao concluiu o encerramento em 10 segundos. Execute novamente.'
            }
            $null = $output.GetAwaiter().GetResult()
            $null = $errors.GetAwaiter().GetResult()
            if ($killer.ExitCode -ne 0) {
                $remaining = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $target.ProcessId)
                if ($remaining -and $remaining.CreationDate -eq $target.CreationDate) {
                    throw 'O Windows recusou encerrar o processo. Verifique se ele foi aberto por outro usuario ou como administrador.'
                }
            }
        } finally { $killer.Dispose() }
    }
    $deadline = [DateTime]::UtcNow.AddSeconds(5)
    while (Test-LocalPort) {
        if ([DateTime]::UtcNow -ge $deadline) {
            throw 'A porta continua ocupada. Nenhum processo de outra pasta ou de outro aplicativo sera encerrado.'
        }
        Start-Sleep -Milliseconds 150
    }
    if ($targets.Count -eq 0) { Write-Host 'Nenhum processo do Aporte Brasil desta pasta foi encontrado.' }
    else { Write-Host 'Encerramento forcado concluido. Tarefas interrompidas precisam ser executadas novamente.' }
    exit 0
} catch {
    Write-Host ('Nao foi possivel concluir: ' + $_.Exception.Message)
    exit 1
}
