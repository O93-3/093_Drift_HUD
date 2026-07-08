Force exit cleanup fix

Public safety fix:
- Ctrl + Shift + Q now exits the whole app, not only the overlay window.
- Stops HUD timers.
- Closes FH6 UDP receiver socket.
- Closes SimHub passthrough socket.
- Calls QApplication.quit().
- Uses a short delayed os._exit(0) fallback so no 093_Drift_HUD.exe remains in background processes.
