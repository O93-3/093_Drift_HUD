Why the public release folder exists

PyInstaller creates an app folder because the exe needs its _internal files.
The default technical output is:

dist\093_Drift_HUD

For normal users, that is easy to miss.

This build script also creates:

PUBLIC_RELEASE\093_Drift_HUD_Public_Test_01

That is the folder to zip and upload.

Users should double-click:

START_093_DRIFT_HUD.bat

or:

093_Drift_HUD.exe

Keep the whole folder together. Do not move only the exe.
