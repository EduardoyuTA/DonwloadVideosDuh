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

echo Instalando dependencias do app...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo Instalando PyInstaller...
".venv\Scripts\python.exe" -m pip install pyinstaller
if errorlevel 1 goto :error

if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

echo Gerando executavel...
".venv\Scripts\python.exe" -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --name VideoFlow ^
  --icon "assets\videoflow.ico" ^
  --add-data "assets;assets" ^
  --add-data "templates;templates" ^
  --add-data "static;static" ^
  desktop_launcher.py
if errorlevel 1 goto :error

echo.
echo EXE gerado com sucesso em:
echo %CD%\dist\VideoFlow.exe
pause
exit /b 0

:error
echo.
echo Nao foi possivel gerar o executavel.
pause
exit /b 1
