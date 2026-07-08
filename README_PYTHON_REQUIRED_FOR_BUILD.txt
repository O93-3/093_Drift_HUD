Python is required only to build the Windows exe.

If build_windows_exe.bat says Python was not found:

1. Install Python 3.10 or newer from python.org
2. During install, enable:
   Add python.exe to PATH
3. Close the command window
4. Run build_windows_exe.bat again

Check command:

python --version

After a successful build, the public release folder will be:

PUBLIC_RELEASE\093_Drift_HUD_Public_Test_01

Zip that folder for distribution.
