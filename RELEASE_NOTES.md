# Release Notes - 093 Drift HUD Public Test 02

## LIVE222 - Public Test 02 release candidate

- Consolidated the Public Test 02 visual updates.
- Cleaned release notes and README for public release.
- Kept telemetry receiver stable from the working LIVE209+ line.
- No DATA STATUS / WAITING helper changes from the broken LIVE205-LIVE208 path.

## Included visual direction

- Operation popups are limited to `HANDBRAKE`, `CLUTCH`, `BRAKE`.
- `THROTTLE` / `COUNTER` text popups remain removed.
- G TELEMETRY reactive glow is kept.
- ANGLE remains clean with no noisy backglow or scan rail.
- CAR STATUS, CAR INFO, INPUT, TRACK MAP, WHEEL / COUNTER visual texture improvements are included.
- 1080P final safety pass is included.


## LIVE223 - Public Test 02 GitHub Release Ready

- Cleaned root package for GitHub upload.
- Removed old per-LIVE development notes from the release-ready package.
- Removed Public Test 01 release body to avoid confusion.
- Updated public user README with English/Japanese setup, FH6 Data Out, SimHub 8001, ZIP extraction, and exit instructions.
- Kept telemetry receiver and HUD drawing behavior unchanged from LIVE222.


### LIVE224 / Layout safety update

JP:
- 1080Pと1440Pのレイアウト保存を別管理にしました。
- 1080P環境の初回起動は 1080P FULL になります。
- WHEEL / COUNTER と INPUT / CAR INFO が見える状態で起動します。

EN:
- Layout positions are now stored separately for 1080P and 1440P profiles.
- First startup on 1080P / low-height displays uses 1080P FULL.
- WHEEL / COUNTER and INPUT / CAR INFO are visible by default.
