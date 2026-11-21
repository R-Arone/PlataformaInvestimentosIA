@echo off
setlocal
set "APP_DIR=%~dp0"
set "WRAPPER=%APP_DIR%gradle\wrapper\gradle-wrapper.jar"
if not exist "%WRAPPER%" (
    echo Prepare o Gradle Wrapper com .\prepare-wrapper.ps1 ou abra o projeto no Android Studio.
    exit /b 1
)
set "JAVA_EXE=java.exe"
if defined JAVA_HOME set "JAVA_EXE=%JAVA_HOME%\bin\java.exe"
"%JAVA_EXE%" -classpath "%WRAPPER%" org.gradle.wrapper.GradleWrapperMain -p "%APP_DIR%." %*
exit /b %ERRORLEVEL%
