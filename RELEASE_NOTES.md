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
