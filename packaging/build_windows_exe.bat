@echo off
setlocal

cd /d "%~dp0.."

echo === Building frontend (npm install + build) ===
pushd frontend
call npm install
if errorlevel 1 goto :error
call npm run build
if errorlevel 1 goto :error
popd

echo === Setting up an isolated Python build environment ===
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -m venv packaging\.build-venv
) else (
    python -m venv packaging\.build-venv
)
if errorlevel 1 goto :error

call packaging\.build-venv\Scripts\activate.bat
if errorlevel 1 goto :error

python -m pip install --upgrade pip
python -m pip install -e "backend[build]"
if errorlevel 1 goto :error

echo === Building SpecWrite.exe (this can take a few minutes) ===
pyinstaller --clean --noconfirm --distpath packaging\dist --workpath packaging\build packaging\specwrite.spec
if errorlevel 1 goto :error

echo.
echo ============================================================
echo Done! SpecWrite.exe is at: packaging\dist\SpecWrite.exe
echo Copy that one file anywhere and double-click it to run the app.
echo ============================================================
goto :end

:error
echo.
echo Build failed -- see the error above for details.
exit /b 1

:end
endlocal
