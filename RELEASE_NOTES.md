# Release Notes - 093 Drift HUD Public Test 01

First public test package for 093 Drift HUD.

## Includes

- ANGLE display
- HOLD timer and meter
- CAR STATUS
- G TELEMETRY
- TRACK MAP
- WHEEL / COUNTER
- INPUT / CAR INFO
- HUD profiles
- SimHub passthrough config
- Global hotkeys
- Movable panels

## Public Test 01 final adjustment

- WHEEL / COUNTER zero X position follows the ANGLE gauge zero X position.
- Zero marker is drawn on top of the WHEEL / COUNTER bars.
- Horizontal sync only.
- No telemetry logic changes.
- No SimHub changes.

## Telemetry

FH6 Data Out:

```text
127.0.0.1:5300
```

Optional SimHub passthrough:

```text
127.0.0.1:8001
```

## Notes

- This is not a final stable release.
- Visual balance may change.
- Telemetry detection may change.
- Layout may change.
- Windows exe should be built on Windows using `build_windows_exe.bat`.


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
