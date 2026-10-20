@echo off
setlocal
cd /d "%~dp0"
if /i "%~1"=="--kill" goto kill
if /i "%~1"=="--force" goto force
if not "%~1"=="" goto normal
echo.
echo Aporte Brasil - reiniciar ou encerrar
echo.
echo 1. Reiniciar normalmente
echo 2. Forcar encerramento e reiniciar (se travou)
echo 3. Forcar encerramento sem reabrir
echo 4. Sair
echo.
echo Ao forcar, formularios e tarefas ainda nao salvos podem ser perdidos.
choice /c 1234 /n /m "Escolha uma opcao [1-4]: "
if errorlevel 4 exit /b 0
if errorlevel 3 goto kill
if errorlevel 2 goto force
:normal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Iniciar.ps1" -Restart %*
goto done
:force
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Iniciar.ps1" -ForceRestart
goto done
:kill
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Iniciar.ps1" -StopOnly
:done
set "aporteResult=%errorlevel%"
if not "%aporteResult%"=="0" echo Se o reinicio normal falhou, abra este arquivo e escolha a opcao 2 ou 3.
pause
exit /b %aporteResult%
