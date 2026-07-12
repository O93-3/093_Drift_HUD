# 093 Drift HUD - Public Test 02

FH6 / Forza Horizon 向けのドリフトHUDです。
Public Test 02では、スコア追加ではなく **走りに反応してかっこよく見えるHUD** を目指しています。

FH6 / Forza Horizon drift telemetry HUD.
Public Test 02 focuses on visual reaction and HUD texture.

## Download / ダウンロード

公開版はGitHub ReleasesのAssetsから以下をダウンロードしてください。

```text
093_Drift_HUD_Public_Test_02_WINDOWS.zip
```

## Start / 起動

1. ZIPをダウンロード
2. ZIPを必ず展開
3. 展開したフォルダを開く
4. 以下をダブルクリック

```text
START_093_DRIFT_HUD.bat
```

ZIPの中から直接起動しないでください。
Pythonのインストールは不要です。

For source/development:

```text
run_hud.bat
```

## FH6 game settings / FH6ゲーム内設定

HUDを動かすには、FH6側で **テレメトリのデータ出力** をオンにしてください。

ゲーム内で以下の順番に開きます。

```text
設定
↓
画面表示とゲームプレイ
↓
テレメトリ
```

テレメトリ画面の **データ出力** を以下のように設定します。

```text
データ出力: オン
データ出力IPアドレス: 127.0.0.1
データ出力IPポート: 5300
```

HUDはこの `127.0.0.1:5300` でFH6からのテレメトリを受信します。
HUDは起動しているのに数値が動かない場合は、まずこの3項目を確認してください。

English quick setup:

```text
Settings
↓
HUD and Gameplay
↓
Telemetry

Data Out: On
Data Out IP Address: 127.0.0.1
Data Out IP Port: 5300
```

## SimHub passthrough / SimHub併用

SimHub is optional. HUD works without SimHub.
SimHubは必須ではありません。HUD単体で使えます。

SimHubも同時に使う場合は、SimHub側のUDP受信を以下に設定してください。

```text
SimHub UDP listen
IP Address: 127.0.0.1
Port: 8001
```

Flow / 流れ:

```text
FH6 Data Out 5300 -> 093 Drift HUD -> SimHub 8001
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
- TRACK MAP east/west movement fix
- WHEEL / COUNTER texture and label position fix
- ANGLE remains clean: no noisy backglow or scan rail
- 1080P / 1440P layout positions are stored separately
- 1080P first startup uses 1080P FULL

## Build Windows release

GitHub Actions builds:

```text
093_Drift_HUD_Public_Test_02_WINDOWS.zip
```

Upload this ZIP to GitHub Releases.
