Build fix note

If Windows says:
'pyinstaller' is not recognized

Use this updated build_windows_exe.bat.

This version calls PyInstaller through Python:

python -m PyInstaller

instead of relying on the pyinstaller command being available in PATH.
