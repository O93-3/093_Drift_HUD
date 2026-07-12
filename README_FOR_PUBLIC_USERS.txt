093 Drift HUD - Public Test 02

English / 日本語

Download / ダウンロード:
1. Open the GitHub Releases page.
   GitHub Releasesページを開きます。
2. Download 093_Drift_HUD_Public_Test_02_WINDOWS.zip from Assets.
   Assetsから 093_Drift_HUD_Public_Test_02_WINDOWS.zip をダウンロードします。
3. Extract the ZIP.
   ZIPを必ず展開します。
4. Open the extracted folder.
   展開したフォルダを開きます。
5. Double-click START_093_DRIFT_HUD.bat.
   START_093_DRIFT_HUD.bat をダブルクリックします。

No Python install is required for public users.
公開ユーザーはPythonのインストール不要です。

FH6 game settings / FH6ゲーム内設定:
HUDを動かすには、FH6側でテレメトリのデータ出力をオンにしてください。

設定 > 画面表示とゲームプレイ > テレメトリ

Set these values:
以下のように設定してください。

Data Out / データ出力: On / オン
Data Out IP Address / データ出力IPアドレス: 127.0.0.1
Data Out IP Port / データ出力IPポート: 5300

If the HUD starts but values do not move, check FH6 Data Out first.
HUDは起動したのに数値が動かない場合は、まずFH6側のデータ出力設定を確認してください。

SimHub passthrough / SimHub併用:
SimHub is optional. The HUD works without SimHub.
SimHubは必須ではありません。HUD単体で使えます。

If using SimHub at the same time, set SimHub UDP listen to:
SimHubも同時に使う場合は、SimHub側のUDP受信を以下に設定してください。
IP Address: 127.0.0.1
Port: 8001

Flow / 流れ:
FH6 Data Out 5300 -> 093 Drift HUD -> SimHub 8001

Exit HUD / 終了:
Ctrl + Shift + Q

HUD profiles / HUDプロファイル:
Ctrl + F9 switches profiles.
Ctrl + F9でプロファイル切替。
1440p displays start in 1440P STREAM.
1080p / low-height displays start in 1080P FULL.
1080p環境では専用1080P FULLレイアウトで自動起動します。

Public Test 02 visual update:
- Operation popups are limited to HANDBRAKE / CLUTCH / BRAKE.
- THROTTLE / COUNTER text popups are removed.
- G TELEMETRY reactive glow, CAR STATUS atmosphere, CAR INFO meter texture, INPUT reaction, TRACK MAP texture, and WHEEL / COUNTER texture are included.
- TRACK MAP east/west movement fix is included.
- WHEEL / COUNTER label position fix is included.
- ANGLE remains clean: no noisy backglow or scan rail.

Public Test 02 主な内容:
- 操作ポップは HANDBRAKE / CLUTCH / BRAKE のみ。
- THROTTLE / COUNTER の文字ポップは削除。
- G TELEMETRYリアクティブ発光、CAR STATUS雰囲気化、CAR INFOメーター質感、INPUT反応、TRACK MAP質感、WHEEL / COUNTER質感を反映。
- TRACK MAPの東西反転修正を反映。
- WHEEL / COUNTERの文字位置修正を反映。
- ANGLEは主役としてクリーン維持。うるさいバックグローやスキャンレールは無し。

Notes / 注意:
Public Test build. Behavior may vary by environment.
Public Test版です。環境によって正常に動作しない場合があります。
Use at your own discretion.
使用は各自の判断でお願いします。
