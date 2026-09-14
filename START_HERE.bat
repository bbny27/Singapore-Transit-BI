@echo off
cd /d "%~dp0"
python make.py setup
if errorlevel 1 goto failed
start "" "powerbi\Transit.pbip"
echo In Power BI, click Home - Refresh. First open requires current Power BI Desktop.
pause
exit /b 0
:failed
echo Setup did not finish. Read the error above; do not continue with stale data.
pause
exit /b 1
