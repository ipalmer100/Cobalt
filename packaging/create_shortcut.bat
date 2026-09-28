@echo off
setlocal

rem ---------------------------------------------------------------------
rem  Put a Cobalt shortcut on the Desktop.
rem
rem  A shortcut is the answer to "how do I open this like a normal app
rem  without an .exe". It carries the Cobalt icon, can be pinned to the
rem  taskbar or Start, and opens with one double-click -- but it is not
rem  itself an executable, so nothing new has to be allow-listed. It just
rem  points at run_cobalt.bat.
rem
rem  Built through `powershell -Command` rather than a .ps1 file on purpose:
rem  PowerShell's execution policy restricts script *files*, and a managed
rem  machine that blocks .ps1 will still run an inline command.
rem ---------------------------------------------------------------------

cd /d "%~dp0.."
set "ROOT=%CD%"
set "TARGET=%ROOT%\packaging\run_cobalt.bat"
set "ICON=%ROOT%\packaging\cobalt.ico"
set "LINK=%USERPROFILE%\Desktop\Cobalt.lnk"

if not exist "%TARGET%" goto :no_target

echo Creating a Cobalt shortcut on your Desktop...

rem WindowStyle 7 = minimized. The console window is how you stop Cobalt
rem (closing it stops the server), so it still exists and still sits in the
rem taskbar -- it just doesn't cover the browser on every launch.
powershell -NoProfile -Command ^
  "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('%LINK%');" ^
  "$s.TargetPath = '%TARGET%';" ^
  "$s.WorkingDirectory = '%ROOT%';" ^
  "$s.IconLocation = '%ICON%';" ^
  "$s.WindowStyle = 7;" ^
  "$s.Description = 'Cobalt - packaging specification editor';" ^
  "$s.Save()"
if errorlevel 1 goto :failed
if not exist "%LINK%" goto :failed

echo.
echo ============================================================
echo  Done. "Cobalt" is on your Desktop.
echo.
echo  Double-click it to start the app. To keep it closer to hand,
echo  right-click it and choose "Pin to Start" or "Pin to taskbar".
echo.
echo  Cobalt runs in a minimized console window - find it in the
echo  taskbar. Closing that window stops the app, and it is also
echo  where any error message appears if it fails to start.
echo ============================================================
goto :end

:no_target
echo.
echo Could not find packaging\run_cobalt.bat, so there is nothing to point
echo the shortcut at. Run this from inside your Cobalt folder.
echo.
exit /b 1

:failed
echo.
echo Could not create the shortcut.
echo.
echo Some managed machines block the Windows Script Host component this
echo uses. You can make one by hand instead: right-click the Desktop,
echo choose New ^> Shortcut, and enter this as the location:
echo.
echo     %TARGET%
echo.
echo Then right-click the shortcut, choose Properties, and set "Change
echo Icon" to:
echo.
echo     %ICON%
echo.
exit /b 1

:end
endlocal
