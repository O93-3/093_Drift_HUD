# 093 Drift HUD - Public Test 02

FH6 / Forza Horizon 向けのドリフトHUDです。  
Public Test 02では、スコアや説明を増やすよりも、**走りに反応してかっこよく見えるHUD**を目指して調整しています。

This is a drift-focused telemetry HUD for FH6 / Forza Horizon.  
Public Test 02 focuses on visual reaction and HUD texture, not extra score labels.

---

## Download / ダウンロード

Download this file from **Assets**:

```text
093_Drift_HUD_Public_Test_02_WINDOWS.zip
```

Assets から上記ZIPをダウンロードしてください。

---

## How to use / 使い方

1. Download the ZIP / ZIPをダウンロード
2. Extract the ZIP / ZIPを展開
3. Open the extracted folder / 展開したフォルダを開く
4. Double-click / ダブルクリック

```text
START_093_DRIFT_HUD.bat
```

Python is not required.  
Pythonのインストールは不要です。

Please extract the ZIP before running. Do not run directly from inside the ZIP.  
必ずZIPを展開してから起動してください。ZIPの中から直接起動しないでください。

---

## FH6 Data Out / FH6側設定

Set FH6 Data Out to:  
FH6のData Outを以下に設定してください。

```text
IP Address: 127.0.0.1
Port: 5300
```

If the HUD starts but the values do not move, check FH6 Data Out first.  
HUDは起動したのに数値が動かない場合は、まずFH6側のData Out設定を確認してください。

---

## SimHub passthrough / SimHub併用

SimHub is optional. The HUD works without SimHub.  
SimHubは必須ではありません。HUD単体で使えます。

If you want to use SimHub at the same time, set SimHub UDP listen to:  
SimHubも同時に使う場合は、SimHub側のUDP受信を以下に設定してください。

```text
IP Address: 127.0.0.1
Port: 8001
```

Flow / 流れ:

```text
FH6 Data Out 5300 -> 093 Drift HUD -> SimHub 8001
```

---

## Exit / 終了

```text
Ctrl + Shift + Q
```

---

## Public Test 02 highlights / 主な変更

- Short operation popups only: `HANDBRAKE`, `CLUTCH`, `BRAKE`
- Removed confusing `THROTTLE` / `COUNTER` text popups
- Stronger INPUT reaction texture
- Improved G TELEMETRY reactive glow and G ring texture
- CAR STATUS atmosphere panel and LIMIT needle texture
- CAR INFO meter-style RPM segments
- TRACK MAP texture and recent-line readability
- WHEEL / COUNTER visual texture
- ANGLE remains clean: no noisy backglow or scan rail
- 1080P safety pass for panel bounds and density

- 操作ポップは `HANDBRAKE`, `CLUTCH`, `BRAKE` のみに整理
- 分かりにくい `THROTTLE` / `COUNTER` 文字ポップは削除
- INPUTの反応演出を強化
- G TELEMETRYのリアクティブ発光とGリング質感を強化
- CAR STATUSを雰囲気パネル化、LIMITニードルを追加
- CAR INFOにメーター風RPMセグメントを追加
- TRACK MAPの質感と走行ラインの見やすさを調整
- WHEEL / COUNTERの見た目を調整
- ANGLEは主役としてクリーン維持。うるさいバックグローやスキャンレールは無し
- 1080P環境向けに枠はみ出し・密度を再調整

---

## Notes / 注意

Public Test build. Behavior may vary by environment.  
Public Test版です。環境によって正常に動作しない場合があります。

Use at your own discretion.  
使用は各自の判断でお願いします。


### LIVE224 / Layout safety update

JP:
- 1080Pと1440Pのレイアウト保存を別管理にしました。
- 1080P環境の初回起動は 1080P FULL になります。
- WHEEL / COUNTER と INPUT / CAR INFO が見える状態で起動します。

EN:
- Layout positions are now stored separately for 1080P and 1440P profiles.
- First startup on 1080P / low-height displays uses 1080P FULL.
- WHEEL / COUNTER and INPUT / CAR INFO are visible by default.
