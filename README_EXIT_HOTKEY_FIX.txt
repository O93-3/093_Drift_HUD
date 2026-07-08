Exit hotkey fix

Public Test 01 safety fix:
- Ctrl + Shift + Q exits the HUD.
- Works through global hotkey polling on Windows, even when FH6 has focus.
- Esc still exits when the HUD itself has focus.
- In-HUD help list now shows Ctrl + Shift + Q = EXIT HUD.


1080p safety:
- On displays lower than 1200px high, the HUD now starts in 1080P STREAM automatically.
- 1440p users still start with the normal 1440P STREAM layout.
- Users can still switch profiles with Ctrl + F9.


LIVE192 force-exit cleanup:
- Ctrl + Shift + Q now stops HUD timers, closes UDP sockets, quits the Qt app, and force-exits if Windows leaves the overlay in background processes.
