$ErrorActionPreference = 'Stop'
$version = '9.3.1'
$expected = 'b3a875ddc1f044746e1b1a55f645584505f4a10438c1afea9f15e92a7c42ec13'
$wrapper = Join-Path $PSScriptRoot 'gradle/wrapper/gradle-wrapper.jar'

if ((Test-Path -LiteralPath $wrapper) -and (Get-FileHash -LiteralPath $wrapper).Hash -eq $expected) {
    Write-Output "Gradle Wrapper $version verificado."
    exit 0
}

$temporary = "$wrapper.$PID.tmp"
try {
    $url = "https://raw.githubusercontent.com/gradle/gradle/v$version/gradle/wrapper/gradle-wrapper.jar"
    Invoke-WebRequest -Uri $url -OutFile $temporary
    if ((Get-FileHash -LiteralPath $temporary).Hash -ne $expected) {
        throw "O SHA-256 do Gradle Wrapper $version diverge do publicado pelo Gradle."
    }
    Move-Item -LiteralPath $temporary -Destination $wrapper -Force
    Write-Output "Gradle Wrapper $version preparado e verificado."
} finally {
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary }
}
