@echo off
echo This file is only for developers.
echo For public users, download the Windows ZIP from GitHub Actions / Releases.
echo.
echo If you still want to build locally, install Python 3.10+ first.
echo Then run:
echo python -m pip install -r requirements.txt
echo python -m pip install pyinstaller
echo python -m PyInstaller --noconfirm --clean --windowed --name "093_Drift_HUD" --add-data "hud_config.json;." --add-data "hud_profile.json;." --add-data "overlay_layout.json;." --add-data "simhub_forward.json;." --add-data "cars.json;." main.py
echo.
pause
