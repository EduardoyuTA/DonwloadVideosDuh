@echo off
setlocal

cd /d "%~dp0"

echo Fechando qualquer processo preso na porta 5000...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":5000 .*LISTENING"') do (
    echo Encerrando PID %%P...
    taskkill /PID %%P /T /F >nul 2>nul
)

timeout /t 1 /nobreak >nul

echo Iniciando o VideoFlow com uma instancia limpa...
call "%~dp0iniciar_app.bat"
