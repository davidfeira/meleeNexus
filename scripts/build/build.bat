@echo off
echo ========================================
echo Building MEX Manager Distribution
echo ========================================
echo.

REM Store project root directory for absolute paths
REM %~dp0 gives us the directory where this batch file is located (scripts\build\)
REM Go up 2 directories to get to project root
set "PROJECT_ROOT=%~dp0..\.."
pushd "%PROJECT_ROOT%"
set "PROJECT_ROOT=%cd%"
popd

REM Disable code signing to avoid symlink issues on Windows
set CSC_IDENTITY_AUTO_DISCOVERY=false
set DEBUG=electron-builder

REM Check if PyInstaller is installed
python -c "import PyInstaller" 2>nul
if %errorlevel% neq 0 (
    echo PyInstaller not found. Installing...
    pip install pyinstaller
)

REM Force delete old build artifacts to prevent caching issues
echo Cleaning old build artifacts...
if exist "%PROJECT_ROOT%\dist" (
    rmdir /s /q "%PROJECT_ROOT%\dist"
)
if exist "%~dp0build" (
    rmdir /s /q "%~dp0build"
)
if exist "%~dp0__pycache__" (
    rmdir /s /q "%~dp0__pycache__"
)

echo.
echo [1/4] Building Python Backend...
echo ----------------------------------------
python -m PyInstaller "%~dp0mex_backend.spec" --clean --noconfirm
if %errorlevel% neq 0 (
    echo ERROR: Python backend build failed
    pause
    exit /b 1
)

echo.
echo [2/4] Building .NET MexCLI (self-contained)...
echo ----------------------------------------
if not exist "%PROJECT_ROOT%\utility\MexManager\MexCLI" (
    echo ERROR: Cannot find MexCLI directory at %PROJECT_ROOT%\utility\MexManager\MexCLI
    pause
    exit /b 1
)
cd /d "%PROJECT_ROOT%\utility\MexManager\MexCLI"
dotnet publish -c Release -r win-x64 --self-contained true -p:PublishSingleFile=false -o "%PROJECT_ROOT%\dist-backend\mex"
if %errorlevel% neq 0 (
    echo ERROR: MexCLI build failed
    cd /d "%PROJECT_ROOT%"
    pause
    exit /b 1
)

echo Copying codes.gct to dist-backend\mex...
copy /Y "bin\Release\net6.0\codes.gct" "%PROJECT_ROOT%\dist-backend\mex\codes.gct"
cd /d "%PROJECT_ROOT%"

echo.
echo [3/4] Building React Frontend...
echo ----------------------------------------
if not exist "%PROJECT_ROOT%\viewer" (
    echo ERROR: Cannot find viewer directory at %PROJECT_ROOT%\viewer
    pause
    exit /b 1
)
cd /d "%PROJECT_ROOT%\viewer"
call npm run build
if %errorlevel% neq 0 (
    echo ERROR: Frontend build failed
    cd /d "%PROJECT_ROOT%"
    pause
    exit /b 1
)
cd /d "%PROJECT_ROOT%"

echo.
echo [4/4] Creating Electron Installer...
echo ----------------------------------------
REM Clear electron-builder cache to avoid symlink issues
if exist "%LOCALAPPDATA%\electron-builder\Cache\winCodeSign\" (
    echo Clearing electron-builder cache...
    rmdir /s /q "%LOCALAPPDATA%\electron-builder\Cache\winCodeSign"
)
call npm run package -- --win
if %errorlevel% neq 0 (
    echo ERROR: Electron packaging failed
    pause
    exit /b 1
)

echo.
echo ========================================
echo Build Complete!
echo ========================================
echo.
echo Installer location: dist-electron\
echo.
dir /b dist-electron\*.exe 2>nul
echo.
pause
