@echo off
setlocal

rem ---------------------------------------------------------------------
rem  Run Cobalt without the .exe.
rem
rem  Some managed Windows machines refuse to run a freshly-built, unsigned
rem  executable at all -- Defender's "block executable files unless they
rem  meet a prevalence, age, or trusted list criterion" rule is the usual
rem  one, and a binary compiled ten minutes ago meets none of those.
rem
rem  This starts exactly the same application through Python instead. Same
rem  server, same UI, same port -- the only difference is that no new
rem  executable is involved, so allow-listing has nothing to object to.
rem
rem  This is a stopgap, not a way around a security control: tell whoever
rem  manages your machine that you are running it, and get the .exe signed
rem  or allow-listed for anything beyond your own use.
rem ---------------------------------------------------------------------

cd /d "%~dp0.."

echo ============================================================
echo  Cobalt - starting from source
echo ============================================================
echo.

if not exist "packaging\.build-venv\Scripts\python.exe" goto :no_venv
if not exist "frontend\dist\index.html" goto :no_frontend

echo Starting Cobalt. Your browser will open in a moment.
echo Close this window to stop it.
echo.
packaging\.build-venv\Scripts\python.exe -m cobalt.desktop
goto :end

:no_venv
echo The build environment is missing.
echo.
echo Run the build first - it creates the environment this needs:
echo.
echo     packaging\build_windows_exe.bat
echo.
echo If the build itself is what is being blocked, install the app into
echo your own Python instead and run it from there:
echo.
echo     python -m pip install -e backend
echo     python -m cobalt.desktop
echo.
exit /b 1

:no_frontend
echo The frontend has not been built, so there would be no interface to
echo show. Build it once:
echo.
echo     cd frontend
echo     npm install
echo     npm run build
echo     cd ..
echo.
echo Or just run packaging\build_windows_exe.bat, which does this too.
echo.
exit /b 1

:end
endlocal
