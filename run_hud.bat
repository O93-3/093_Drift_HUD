@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo OKUSURI 093 DRIFT HUD START > run_error_log.txt
echo DATE %date% TIME %time% >> run_error_log.txt
echo FOLDER %CD% >> run_error_log.txt
echo. >> run_error_log.txt

echo =========================================
echo  093 DRIFT HUD - START_HERE_FIXED
echo =========================================
echo.
echo Log file: run_error_log.txt
echo.

if not exist "main.py" (
  echo ERROR main.py not found. >> run_error_log.txt
  echo ERROR: main.py not found.
  echo Extract the ZIP first, then run START_HERE_FIXED.cmd inside the extracted folder.
  pause
  exit /b 1
)

REM This is the old working start method for OKUSURI PC.
REM Do not use Windows Store python alias.
set CONDA=C:\Users\junxc\anaconda3\Scripts\conda.exe
set ENVNAME=okusuri_hud_py312

if not exist "%CONDA%" (
  echo ERROR conda.exe not found: %CONDA% >> run_error_log.txt
  echo ERROR: conda.exe not found.
  echo Expected:
  echo %CONDA%
  echo.
  echo This launcher is the OKUSURI PC launcher.
  echo Send run_error_log.txt if this path is wrong.
  pause
  exit /b 1
)

echo Using conda: %CONDA%
echo Using conda: %CONDA% >> run_error_log.txt

echo.
echo Checking env: %ENVNAME%
echo ---- check env %ENVNAME% ---- >> run_error_log.txt
"%CONDA%" run -n %ENVNAME% python --version >> run_error_log.txt 2>&1
if errorlevel 1 (
  echo Creating clean Python 3.12 env. This may take a few minutes...
  echo ---- create env %ENVNAME% ---- >> run_error_log.txt
  "%CONDA%" create -n %ENVNAME% python=3.12 -y >> run_error_log.txt 2>&1
  if errorlevel 1 (
    echo ERROR: conda env create failed.
    type run_error_log.txt
    pause
    exit /b 1
  )
)

echo Checking PyQt6...
echo ---- PyQt6 check/install ---- >> run_error_log.txt
"%CONDA%" run -n %ENVNAME% python -c "import PyQt6; from PyQt6.QtCore import Qt; print('PyQt6 OK')" >> run_error_log.txt 2>&1
if errorlevel 1 (
  echo Installing PyQt6...
  "%CONDA%" run -n %ENVNAME% python -m pip install --upgrade pip >> run_error_log.txt 2>&1
  "%CONDA%" run -n %ENVNAME% python -m pip install PyQt6 >> run_error_log.txt 2>&1
  "%CONDA%" run -n %ENVNAME% python -c "import PyQt6; from PyQt6.QtCore import Qt; print('PyQt6 OK')" >> run_error_log.txt 2>&1
  if errorlevel 1 (
    echo ERROR: PyQt6 still failed.
    type run_error_log.txt
    pause
    exit /b 1
  )
)

echo.
echo Starting overlay with old fixed conda env...
echo ---- START main.py ---- >> run_error_log.txt
"%CONDA%" run -n %ENVNAME% python "%~dp0main.py" >> run_error_log.txt 2>&1

set EXITCODE=%errorlevel%
echo. >> run_error_log.txt
echo EXITCODE %EXITCODE% >> run_error_log.txt

if not "%EXITCODE%"=="0" (
  echo.
  echo ERROR: overlay closed. Showing log:
  echo.
  type run_error_log.txt
  echo.
  pause
  exit /b %EXITCODE%
)

echo.
echo Program closed normally.
pause
endlocal
