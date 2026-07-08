# 093 Drift HUD - Public Test 01

**FH6 Telemetry Drift Overlay**

093 Drift HUD は、FH6 のテレメトリを使ったドリフト向け HUD です。  
ANGLE、HOLD、CAR STATUS、G TELEMETRY、TRACK MAP、WHEEL / COUNTER などを表示します。

This is a public test build of **093 Drift HUD**, a drift-focused telemetry overlay for FH6.

---

## Download

For normal users, download the Windows ZIP from **GitHub Releases** or the GitHub Actions artifact:

```text
093_Drift_HUD_Public_Test_01_WINDOWS.zip
```

Extract it and double-click:

```text
START_093_DRIFT_HUD.bat
```

The source ZIP is for developers.

---

## Status

This is an early public test build.

表示バランス、レイアウト、テレメトリ判定、スコア系の挙動は今後変更される可能性があります。  
Visual balance, layout, telemetry behavior, and scoring logic may change in future versions.

---

## Project naming

- **093 Drift HUD** = this HUD / telemetry overlay
- **CHASE//EDGE** = future drift battle project name

この HUD は、今後予定しているドリフトバトル企画 **CHASE//EDGE** でも使用予定です。  
This HUD may also be used in the future **CHASE//EDGE** drift battle project.

---

## FH6 Data Out settings

Set FH6 Data Out to:

```text
IP:   127.0.0.1
Port: 5300
```

The HUD listens on UDP port `5300`.

---

## Optional SimHub passthrough

If you want to use SimHub at the same time:

```text
SimHub listen IP:   127.0.0.1
SimHub listen port: 8001
```

The HUD receives FH6 telemetry on `5300` and forwards the same packet to SimHub on `8001`.

---

## Run from source

### Requirements

- Windows
- Python 3.10+
- PyQt6

Install dependencies:

```bat
python -m pip install -r requirements.txt
```

Run:

```bat
python main.py
```

Or double-click:

```text
run_hud.bat
```

---

## Build Windows exe

On Windows:

Python is required to build the Windows exe. Install Python 3.10+ and enable `Add python.exe to PATH`.

```bat
build_windows_exe.bat
```

Output folders:

```text
dist\093_Drift_HUD
PUBLIC_RELEASE\093_Drift_HUD_Public_Test_01
```

For public release, zip this folder:

```text
PUBLIC_RELEASE\093_Drift_HUD_Public_Test_01
```

Users can start the HUD with:

```text
START_093_DRIFT_HUD.bat
```

If PyInstaller creates an `_internal` folder, do **not** upload only the exe.  
Keep the whole folder together.

---

## Hotkeys

```text
Ctrl + F1   HUD ALL ON/OFF
Ctrl + F2   CAR STATUS ON/OFF
Ctrl + F3   TRACK MAP ON/OFF
Ctrl + F4   G TELEMETRY ON/OFF
Ctrl + F5   WHEEL / COUNTER ON/OFF
Ctrl + F6   INPUT / CAR INFO ON/OFF
Ctrl + F9   HUD PROFILE NEXT
Ctrl + F10  SHOW CURRENT PROFILE
Ctrl + F11  HELP / KEY LIST
Ctrl + F12  TRACK MAP RESET
Ctrl + Shift + Q  EXIT HUD
Alt + Drag  MOVE PANEL
```

---

## HUD profiles

```text
1440P STREAM
1440P CLEAN
1080P STREAM
1080P FULL
```

Use `Ctrl + F9` to cycle profiles.

---

## Public Test 01 note

- WHEEL / COUNTER zero position follows the ANGLE gauge zero X position.
- Horizontal sync only.
- HUD layout and telemetry logic may change in future versions.

---

## Version

```text
093 Drift HUD - Public Test 01
Based on LIVE182_WHEEL_COUNTER_ANGLE_ZERO_SYNC
Cleaned as GitHub source package
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


LIVE193 1080P TRUE SCALE SELF TEST
- 1080P profile uses 0.75x true-scale sizing from 1440p.
- Starts in 1080P STREAM for immediate testing.
- Offsets are scaled in 1080P so 1440p saved layout does not explode on 1080p.

## Self start / old method

For local testing, double-click:

```text
CLICK_START_093_DRIFT_HUD.bat
```

This uses the old/simple method: run `main.py` directly with Python.

Exit HUD:

```text
Ctrl + Shift + Q
```
