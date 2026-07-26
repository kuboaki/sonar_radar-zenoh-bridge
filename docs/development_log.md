# 開発ログ: テストによる段階的な開発

`docs/zenoh_state_machine_design.md` が「何を作るか」の記録だとすると、こちらは「どう作ったか」の記録。メッセージ接続を伴う分散システムでは、メッセージが実際に疎通しないと何も検証できないため、状態機械図の状態を1つずつ実装し、都度実際のメッセージング基盤(Zenoh)で動作確認しながら進めている。この進め方自体と、そこで得られた教訓をここに残す。

## 開発の進め方(方針)

- 状態機械図の最初の状態から、必要最小限のクラス・関数(に相当する関数)を作り、実際に動かして確認する
- 確認できたら次の状態の実装に進む、を繰り返す
- モックで済ませず、実際のメッセージング基盤(zenohd + hakoniwa_pdu_endpoint)を使って検証する
- デバッグ・観測用の処理は、対象システムの実装そのものに混ぜず、横断的関心事として分離する

## マイルストーン1: INIT 〜 WAIT_CALIBRATED (完了)

### 実装したもの

`bridge/spikehat_timer.py`, `broker.py`, `sonar_radar_app.py`, `run_calibration_smoke_test.py`, `watch_state.py`, `state_reporter.py`。詳細は `README.md` の「`bridge/` の動作確認」節を参照。

### 確認した内容

- 単一プロセス内の自己ループバックによる `calibrate` → `calibrated` → guard通過 → `WAIT_FOR_START_PRESS` 到達(成功経路)
- タイムアウト → `CALIBRATION_FAILED` → `TERMINATED`(失敗経路)
- 別プロセス(`watch_state.py`)からのリアルタイム状態観測(別ターミナル・ユーザー自身の手元での再現も含む)

### 得られた教訓

1. **観測用処理は状態機械の実装から外に出す。**
   当初 `broker.publish_state()` の呼び出しを `SonarRadarApp._transition_to()` の中に直接書いていたが、これは状態機械図に無い関心事を実装に混ぜ込むアンチパターンだった。指摘を受け、`run()` を外側からラップする `state_reporter.py` に切り出した。`sonar_radar_app.py` 自体は図に忠実な実装のみを保ち、「状態が変わったらレポートする」という繰り返し構造への付与は変換規則側の仕事として分離した。

2. **分散システムのデバッグでは、まず自分の診断ツール自体を疑う。**
   「別プロセス間でメッセージが届いていない」ように見えた問題は、実際にはZenoh配送は正常で、バックグラウンドプロセスの標準出力がバッファリングされたまま(`-u`なし・`flush=True`なし)、ログファイルを早すぎるタイミングで読んでいた、という検証コード側の不備だった。`-u`(unbuffered)で実行し、プロセスの終了を`wait`してからログを確認して判明した。

3. **環境差は、実装者本人が手元で再現して初めて見つかる場合がある。**
   macOSの `DYLD_LIBRARY_PATH` に `/usr/local/hakoniwa/lib`(以前の `sudo bash install.bash` で作られた、Zenoh無効の古いビルドが残っている場所)が含まれる環境だと、`HAKO_PDU_ENDPOINT_SHARED_LIB` で絶対パス指定していても、dyldが同名ファイルをそちらから優先して読み込んでしまう問題があった。この問題は作業環境(Bashツール側のシェル)では再現せず、ユーザー本人が実際に手元のターミナルで試して初めて発覚した。対処は `bridge/env.sh` で `.local` 側のパスを `DYLD_LIBRARY_PATH` の先頭に追加すること(共有のシステム領域 `/usr/local/hakoniwa/lib` 自体は変更しない)。

## 次のマイルストーン

`WAIT_FOR_START_PRESS` 以降(押下/解放、`SCANNING`、`detected`の対称処理等)。同じ進め方(1状態ずつ実装→実際のZenohで確認)を継続する。
