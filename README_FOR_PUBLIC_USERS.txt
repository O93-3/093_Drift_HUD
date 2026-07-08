For public users

Do not download the source ZIP unless you know how to run Python.

Use the Windows release ZIP:

093_Drift_HUD_Public_Test_01_WINDOWS.zip

After downloading:

1. Extract the ZIP.
2. Open the extracted folder.
3. Double-click START_093_DRIFT_HUD.bat.

FH6 Data Out:
127.0.0.1:5300

SimHub passthrough:
127.0.0.1:8001

Keep the whole extracted folder together.
Do not move only the exe.


Exit HUD:

```text
Ctrl + Shift + Q
```


1080p safety:
- On displays lower than 1200px high, the HUD now starts in 1080P STREAM automatically.
- 1440p users still start with the normal 1440P STREAM layout.
- Users can still switch profiles with Ctrl + F9.


LIVE191 1080p compact fix:
- 1080P STREAM / 1080P FULL now use smaller dedicated panel geometry and compact font scaling.
- Low-height screens still auto-start in 1080P STREAM.


LIVE192 force-exit cleanup:
- Ctrl + Shift + Q now stops HUD timers, closes UDP sockets, quits the Qt app, and force-exits if Windows leaves the overlay in background processes.
