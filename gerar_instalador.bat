@echo off
setlocal

cd /d "%~dp0"

set "PYTHON_CMD="
set "ISCC_CMD="
set "APP_VERSION=1.0.0"
set "NO_PAUSE="
set "PYINSTALLER_DIST_DIR=build_output\app"
set "PYINSTALLER_WORK_DIR=build_output\work"
set "INSTALLER_OUTPUT_DIR=dist\installer"
set "APP_SOURCE_EXE=%PYINSTALLER_DIST_DIR%\VideoFlow.exe"

if /i "%~1"=="--no-pause" (
    set "NO_PAUSE=1"
)

where py >nul 2>nul && set "PYTHON_CMD=py -3"

if not defined PYTHON_CMD (
    where python >nul 2>nul && set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
    echo Python nao foi encontrado neste computador.
    echo Instale o Python 3 e tente novamente.
    call :maybe_pause
    exit /b 1
)

if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" (
    set "ISCC_CMD=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
)

if not defined ISCC_CMD if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" (
    set "ISCC_CMD=%ProgramFiles%\Inno Setup 6\ISCC.exe"
)

if not defined ISCC_CMD if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" (
    set "ISCC_CMD=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
)

if not defined ISCC_CMD (
    echo Inno Setup nao foi encontrado.
    echo Instale o Inno Setup 6 e tente novamente.
    call :maybe_pause
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

echo Instalando dependencias de build...
".venv\Scripts\python.exe" -m pip install pyinstaller
if errorlevel 1 goto :error

if exist "build_output" rmdir /s /q "build_output"
if exist "%INSTALLER_OUTPUT_DIR%" rmdir /s /q "%INSTALLER_OUTPUT_DIR%"

echo Gerando executavel...
".venv\Scripts\python.exe" -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --name VideoFlow ^
  --distpath "%PYINSTALLER_DIST_DIR%" ^
  --workpath "%PYINSTALLER_WORK_DIR%" ^
  --icon "assets\videoflow.ico" ^
  --add-data "assets;assets" ^
  --add-data "templates;templates" ^
  --add-data "static;static" ^
  desktop_launcher.py
if errorlevel 1 goto :error

echo Compilando instalador...
"%ISCC_CMD%" /DMyAppVersion=%APP_VERSION% /DMyAppSourceExe=%APP_SOURCE_EXE% /O"%INSTALLER_OUTPUT_DIR%" "installer.iss"
if errorlevel 1 goto :error

echo.
echo Instalador gerado com sucesso em:
echo %CD%\dist\installer\VideoFlow-Installer.exe
call :maybe_pause
exit /b 0

:error
echo.
echo Nao foi possivel gerar o instalador.
call :maybe_pause
exit /b 1

:maybe_pause
if not defined NO_PAUSE pause
exit /b 0
