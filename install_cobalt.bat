@echo off
rem Plain setlocal, no delayed expansion: nothing here reads back a variable
rem it set inside a block, and with delayed expansion on, an exclamation
rem mark anywhere in an echoed message is silently eaten.
setlocal

rem ---------------------------------------------------------------------
rem  Install or update Cobalt, from a browser and nothing else.
rem
rem  This is the whole install: download this one file, double-click it.
rem  No Git, no Python, no Node.js, no terminal, no administrator rights.
rem  It downloads the current released build of Cobalt, puts it in place,
rem  and leaves a Cobalt shortcut on the Desktop.
rem
rem  Run it again later and it updates in place -- it is the same file for
rem  installing and for upgrading, because a plant that has to find the
rem  right version of an installer will end up on the wrong one.
rem
rem  It installs the built application, which is the reason it needs
rem  nothing: Cobalt.exe carries its own Python inside it. The trade is
rem  that it is an executable, and a managed machine may refuse to run a
rem  new unsigned one. If that happens, see :blocked at the bottom of this
rem  file -- the from-source route takes Python and Node but involves no
rem  executable at all, and is documented in packaging\README.md.
rem ---------------------------------------------------------------------

set "REPO=ipalmer100/Cobalt"
set "ASSET=Cobalt-windows.zip"
set "URL=https://github.com/%REPO%/releases/latest/download/%ASSET%"
rem Installed under LocalAppData rather than the Desktop or Documents on
rem purpose: those are OneDrive-synced here, and the app folder is several
rem thousand files that would be uploaded one by one. LocalAppData is
rem per-user, needs no elevation, and is not synced.
if "%~1"=="" (set "TARGET=%LOCALAPPDATA%\Cobalt") else (set "TARGET=%~1")
set "WORK=%TEMP%\cobalt-install-%RANDOM%"
set "ZIP=%WORK%\%ASSET%"

echo ============================================================
echo  Cobalt - install / update
echo ============================================================
echo.
echo   From : github.com/%REPO% (latest release)
echo   Into : %TARGET%
echo.

mkdir "%WORK%" 2>nul

rem --- Download --------------------------------------------------------
rem
rem curl.exe ships with Windows 10 1803 and later and is tried first: no
rem PowerShell, no execution policy. It does not use the system proxy
rem though, so a machine behind a corporate proxy falls through to
rem PowerShell, which does.
rem
rem Run without -f and with the status code captured, so an HTTP error can
rem be told apart from a network one. The difference matters: 404 means no
rem release has been published yet, which is not a problem with this
rem machine and nothing it does will fix.

echo === Downloading Cobalt (about 60 MB) ===
set "HTTP="
where curl.exe >nul 2>nul
if errorlevel 1 goto :try_powershell
curl.exe -sSL --retry 3 --progress-bar -o "%ZIP%" -w "%%{http_code}" "%URL%" > "%WORK%\status.txt"
if exist "%WORK%\status.txt" set /p HTTP=<"%WORK%\status.txt"
if "%HTTP%"=="200" goto :downloaded
if "%HTTP%"=="404" goto :no_release

:try_powershell
echo   Retrying through the system proxy...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12;" ^
  "$p=[Net.WebRequest]::GetSystemWebProxy(); $p.Credentials=[Net.CredentialCache]::DefaultCredentials;" ^
  "Invoke-WebRequest -Uri '%URL%' -OutFile '%ZIP%' -UseBasicParsing -Proxy $p.GetProxy('%URL%') -ProxyUseDefaultCredentials" 2>nul
if not errorlevel 1 if exist "%ZIP%" goto :downloaded

rem Without a proxy configured at all, GetProxy returns the URL itself and
rem the call above is rejected. Try it plainly before giving up.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12;" ^
  "Invoke-WebRequest -Uri '%URL%' -OutFile '%ZIP%' -UseBasicParsing"
if errorlevel 1 goto :error_download
if not exist "%ZIP%" goto :error_download

:downloaded
rem A 404 page is a few hundred bytes and saves successfully, so "the file
rem exists" proves nothing. Opening it as a zip does.
call :verify_zip
if errorlevel 1 goto :error_not_a_zip
echo   Downloaded.
echo.

rem --- Unpack -----------------------------------------------------------

echo === Unpacking ===
where tar.exe >nul 2>nul
if errorlevel 1 goto :unzip_powershell
tar.exe -xf "%ZIP%" -C "%WORK%"
if not errorlevel 1 goto :unzipped
:unzip_powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop'; Expand-Archive -LiteralPath '%ZIP%' -DestinationPath '%WORK%' -Force"
if errorlevel 1 goto :error_unzip
:unzipped

rem The zip holds a Cobalt folder with the exe and its _internal sibling.
rem The exe does not run without that sibling, so a zip that unpacked to
rem something else is not installable and must not be put in place.
set "SRC=%WORK%\Cobalt"
if not exist "%SRC%\Cobalt.exe" goto :error_layout
if not exist "%SRC%\_internal" goto :error_layout

rem --- Put it in place ---------------------------------------------------

if not exist "%TARGET%" goto :fresh
echo === Replacing the previous version ===
rem Stand outside the folder first. Windows will not delete a directory
rem that any process has as its working directory, and running the
rem installer from inside an existing install is an easy thing to do.
cd /d "%TEMP%"
rmdir /s /q "%TARGET%"
if exist "%TARGET%" goto :error_in_use
:fresh

echo === Installing to %TARGET% ===
rem The parent may not exist if TARGET was given as an argument.
for %%P in ("%TARGET%\..") do if not exist "%%~fP" mkdir "%%~fP" 2>nul
move "%SRC%" "%TARGET%" >nul 2>nul
if exist "%TARGET%\Cobalt.exe" goto :moved
rem move cannot relocate a directory across volumes, and LocalAppData is
rem redirected to a network drive on some managed machines. robocopy can,
rem and ships with Windows. Its exit codes below 8 are all success.
echo   Copying instead - the destination is on another drive.
robocopy "%SRC%" "%TARGET%" /E /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto :error_move
if not exist "%TARGET%\Cobalt.exe" goto :error_move
:moved

rem --- Clear the downloaded-from-the-internet mark -----------------------
rem
rem Windows tags a downloaded file with a hidden "Zone.Identifier" stream,
rem and that tag is what makes SmartScreen interrupt the first launch with
rem "Windows protected your PC". Unblock-File removes it -- exactly what
rem the Unblock button on a file's Properties page does, for a file the
rem person has just chosen to download and install.
rem
rem This is not a way around anything else: Defender, its
rem attack-surface-reduction rules and AppLocker all still apply, and none
rem of them look at this mark. If one of those is what blocks Cobalt, the
rem answer is a signature or an allow-list entry from IT, not this.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Get-ChildItem -LiteralPath '%TARGET%' -Recurse -File | Unblock-File" 2>nul

rem --- Shortcut -----------------------------------------------------------
rem
rem Built through `powershell -Command` rather than a .ps1 file on purpose:
rem PowerShell's execution policy restricts script *files*, and a managed
rem machine that blocks .ps1 will still run an inline command.
rem
rem WindowStyle 7 = minimized. Cobalt runs in a console window and closing
rem that window is how you stop it, so it still exists and still sits in
rem the taskbar -- it just does not cover the browser on every launch.
echo === Adding a Desktop shortcut ===
set "LINK=%USERPROFILE%\Desktop\Cobalt.lnk"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('%LINK%');" ^
  "$s.TargetPath = '%TARGET%\Cobalt.exe';" ^
  "$s.WorkingDirectory = '%TARGET%';" ^
  "$s.IconLocation = '%TARGET%\Cobalt.exe';" ^
  "$s.WindowStyle = 7;" ^
  "$s.Description = 'Cobalt - packaging specification editor';" ^
  "$s.Save()" 2>nul

rmdir /s /q "%WORK%" 2>nul

echo.
echo ============================================================
echo  Cobalt is installed.
echo.
if not exist "%LINK%" goto :no_shortcut_line
echo  Start it from the Cobalt shortcut on your Desktop, or by
echo  running:
goto :start_line_done
:no_shortcut_line
echo  A Desktop shortcut could not be created - this machine blocks
echo  the component that makes them. Start Cobalt by running:
:start_line_done
echo.
echo      %TARGET%\Cobalt.exe
echo.
echo  A console window opens - leave it open, it is the running app -
echo  and your browser opens to Cobalt. Click "Browse..." and pick
echo  your folder of spec files.
echo.
echo  Closing the console window stops Cobalt.
echo.
echo  To update later, run this installer again. Your spec files are
echo  never touched: they stay in their own folder, which this does
echo  not go near.
echo ============================================================
echo.

choice /c yn /n /m "Start Cobalt now? [y/n] "
if errorlevel 2 goto :end
start "" "%TARGET%\Cobalt.exe"
goto :end

rem --- Subroutines -------------------------------------------------------

:verify_zip
rem Confirms the download really is a readable archive with something in
rem it. An HTTP error page saves to disk perfectly happily.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "try { Add-Type -AssemblyName System.IO.Compression.FileSystem;" ^
  "$z = [IO.Compression.ZipFile]::OpenRead('%ZIP%');" ^
  "$n = $z.Entries.Count; $z.Dispose();" ^
  "if ($n -lt 1) { exit 1 } else { exit 0 } } catch { exit 1 }"
goto :eof

rem --- Failure paths -----------------------------------------------------

:no_release
echo.
echo There is no published release to install yet.
echo.
echo Cobalt is built on a Windows machine and attached to a GitHub
echo release; until somebody does that, there is nothing here to
echo download. Nothing is wrong with this machine.
echo.
echo   Check github.com/%REPO%/releases
echo.
echo If you are the one who builds it, see RELEASING.md in the
echo repository - build, then attach %ASSET% to a new release.
echo.
pause
exit /b 1

:error_download
echo.
echo Could not download Cobalt from GitHub.
echo.
echo Tried:
echo     %URL%
echo.
echo Open that address in your browser. If it downloads a zip file, the
echo problem is this script's network access rather than the address.
echo.
echo On a corporate network this is usually a proxy that needs
echo credentials, or GitHub being blocked outright. Whoever manages the
echo machine can confirm which.
echo.
pause
exit /b 1

:error_not_a_zip
echo.
echo The download finished but is not a usable zip file.
echo.
echo That normally means something on the network returned a sign-in or
echo error page instead of the file. The downloaded file is at:
echo.
echo     %ZIP%
echo.
echo Open it in Notepad - if it is a web page, that is what happened.
echo.
pause
exit /b 1

:error_unzip
echo.
echo Downloaded Cobalt but could not unpack it.
echo.
echo The file is at %ZIP% if you want to open it by hand.
echo.
pause
exit /b 1

:error_layout
echo.
echo The download unpacked, but does not contain Cobalt.exe next to an
echo _internal folder, which is the only arrangement that runs.
echo.
echo The release asset was probably built or zipped wrongly - zip the
echo Cobalt FOLDER, not the exe on its own. See RELEASING.md.
echo.
pause
exit /b 1

:error_in_use
echo.
echo Could not replace the existing install at:
echo.
echo     %TARGET%
echo.
echo Cobalt is probably still running. Close its console window - not
echo just the browser tab - and run this file again.
echo.
pause
exit /b 1

:error_move
echo.
echo Could not move the downloaded files into:
echo.
echo     %TARGET%
echo.
pause
exit /b 1

:blocked
rem Not jumped to: this script cannot tell whether Windows will refuse the
rem exe, because that happens on first launch, after it is done. Kept here
rem as the answer to the question somebody will have at that point.
rem
rem   "Windows protected your PC" with a Run anyway under More info
rem       SmartScreen. The installer clears the mark that causes this, so
rem       it should not appear; if it does, click through once.
rem   "Windows cannot access the specified device, path, or file" plus a
rem   "Risky action blocked" notification
rem       Defender for Endpoint's rule about executables that are new and
rem       not yet widely seen. Needs an allow-list entry or a signature.
rem   Nothing happens, or "blocked by your administrator"
rem       AppLocker or WDAC refusing unsigned code. Only IT can fix it.
rem
rem In all of those, Cobalt can still be run from source instead, which
rem involves no executable for a policy to object to: see "Running it on a
rem managed PC" in packaging\README.md.
goto :eof

:end
endlocal
