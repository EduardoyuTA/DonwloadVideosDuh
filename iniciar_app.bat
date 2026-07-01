@echo off
setlocal

cd /d "%~dp0"

set "PYTHON_CMD="
where py >nul 2>nul && set "PYTHON_CMD=py -3"

if not defined PYTHON_CMD (
    where python >nul 2>nul && set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
    echo Python nao foi encontrado neste computador.
    echo Instale o Python 3 e tente novamente.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Criando ambiente virtual...
    %PYTHON_CMD% -m venv .venv
    if errorlevel 1 goto :error
)

echo Instalando ou verificando dependencias...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo Encerrando instancias antigas na porta 5000, se existirem...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":5000 .*LISTENING"') do (
    taskkill /PID %%P /T /F >nul 2>nul
)
timeout /t 1 /nobreak >nul

echo Iniciando o servidor...
start "VideoFlow Downloader" cmd /k ""%CD%\.venv\Scripts\python.exe" "%CD%\app.py""

echo Abrindo o navegador...
timeout /t 3 /nobreak >nul
start "" "http://127.0.0.1:5000"

exit /b 0

:error
echo Nao foi possivel iniciar o app.
pause
exit /b 1
