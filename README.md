# 093 Drift HUD - Public Test 02

FH6 / Forza Horizon drift telemetry HUD.
Public Test 02 focuses on visual reaction and HUD texture.

FH6 / Forza Horizon 向けのドリフトHUDです。
Public Test 02では、スコア追加ではなく「走りに反応してかっこよく見えるHUD」を目指しています。

## Start / 起動

For public release ZIP:

```text
START_093_DRIFT_HUD.bat
```

For source/development:

```text
run_hud.bat
```

## FH6 Data Out

```text
IP Address: 127.0.0.1
Port: 5300
```

## SimHub passthrough

SimHub is optional. HUD works without SimHub.

```text
SimHub UDP listen
IP Address: 127.0.0.1
Port: 8001
```

## Exit / 終了

```text
Ctrl + Shift + Q
```

## Public Test 02 highlights

- Operation popups: `HANDBRAKE`, `CLUTCH`, `BRAKE` only
- Removed confusing `THROTTLE` / `COUNTER` text popups
- Reactive INPUT texture
- G TELEMETRY reactive glow and G ring texture
- CAR STATUS atmosphere panel and LIMIT needle texture
- CAR INFO meter-style RPM segments
- TRACK MAP texture / recent line readability
- WHEEL / COUNTER texture
- ANGLE remains clean: no noisy backglow or scan rail
- 1080P final safety pass

## Build Windows release

GitHub Actions builds:

```text
093_Drift_HUD_Public_Test_02_WINDOWS.zip
```

Upload this ZIP to GitHub Releases.


### LIVE224 / Layout safety update

JP:
- 1080Pと1440Pのレイアウト保存を別管理にしました。
- 1080P環境の初回起動は 1080P FULL になります。
- WHEEL / COUNTER と INPUT / CAR INFO が見える状態で起動します。

EN:
- Layout positions are now stored separately for 1080P and 1440P profiles.
- First startup on 1080P / low-height displays uses 1080P FULL.
- WHEEL / COUNTER and INPUT / CAR INFO are visible by default.
