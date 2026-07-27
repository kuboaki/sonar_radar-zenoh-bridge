# sonar_radar-zenoh-bridge

[sonar_radar](https://github.com/kuboaki/sonar_radar) の実機とシミュレータを、複数マシンにまたがって Zenoh 経由の PDU（hakoniwa-pdu-endpoint / hakoniwa-pdu-ros）でリアルタイム同期させるトライアル。

sonar_radar 本体は「実機・スタンドアロンSIM・Hakoniwa SIM」という3つの環境をデジタルツインとして共存させる設計だが、本リポジトリはそれとは別レイヤーの実験として、**ネットワーク越しに複数マシン上で動く実機とシミュレータを、start/stop/calibrate等のイベント単位で疎結合に同期させる**ことを目的とする。

> **設計の転回（進行中）**: 当初は `sonar_radar` 本体に手を入れる形で実装していたが、実装・実機検証を通じて設計上の問題が判明し、**`sonar_radar` は完全に無改造のまま使わず、本リポジトリ側に独立した「Zenoh版 sonar_radar」ステートマシンを新設する**方針に転回した。経緯と現在の状態機械設計は [`docs/zenoh_state_machine_design.md`](docs/zenoh_state_machine_design.md) を参照。このREADMEの一部セクションは転回前の内容のままなので、矛盾する記述は設計ドキュメント側を正とする。

## 背景

Hakoniwa のコンダクターによる時刻同期（`hakopy.usleep()`）は単一ホスト内の複数アセットを密結合に同期させる仕組みで、今回のようにマシンをまたいだ「実機とシムがだいたい同じタイミングで動きつつ、イベント発生時だけ通信する」というユースケースには直接使えない。かわりに、各マシンが自律的にステートマシンの tick ループ（既存の「開いたループ」設計そのまま）を回しつつ、要所で Zenoh 経由の PDU を送受信することで疎結合な同期を実現する。

## 構成

| マシン | 実行するもの | 役割 |
|---|---|---|
| Raspberry Pi 4B+ | `sonar_radar`（実機） + pdu-endpoint (zenoh, client mode) | 実機の `SonarRadarSM` を駆動 |
| Mac | `sonar_radar_sim`（スタンドアロンSIM, mujoco, `--viewer`必須） + pdu-endpoint (zenoh) + zenohd（ルーター） | シム版 `SonarRadarSM` を駆動。zenohd も同居 |
| Raspberry Pi 5 | `hakoniwa-pdu-ros` bridge + pdu-endpoint (zenoh, client mode) | 実機・シム双方のPDUをROSトピックとして中継・モニタリング、外部コマンド注入点 |

実機・シムはそれぞれ zenohd (Mac 上) へ `client` mode で接続する（`peer` mode ではなく、ルーター経由）。

## PDU トピック設計

`SonarRadarSM` の状態遷移イベントそのものを PDU 化する（低レベルI/O値のPDU化ではない）。実機・シムは対称に、自分のイベントを publish し、相手のイベントを subscribe する。

| topic | 意味 | 発生元 | 購読先 |
|---|---|---|---|
| `radar/dome/calibrate` | キャリブレーション実行指示 | 実機/シム起動時、または外部（ブリッジ）コマンド | 実機, シム |
| `radar/dome/calibrated` | 自分のキャリブレーション完了通知 | 実機・シム各自（キャリブレーション完了時） | 相手側、ブリッジ（モニタ） |
| `radar/starter/start` | スキャン開始 | 実機starter / シムstarter / ブリッジ疑似starter | 実機, シム, ブリッジ（モニタ） |
| `radar/starter/stop` | スキャン停止 | 同上 | 同上 |
| `radar/detector/detected` | マーカー検出→方向反転 | 実機 or シムの marker_detector | 相手側、ブリッジ（モニタ） |
| `radar/scanner/scan` | スキャンデータ（angle, dome_angle, distance_mm） | 実機・シム双方の scanner | ブリッジ（→ROSトピック送出） |

## 【廃案】sonar_radar 本体側で必要な変更

> **この節は転回前の設計であり、現在は採用していない。** 経緯は上記「設計の転回」および [`docs/zenoh_state_machine_design.md`](docs/zenoh_state_machine_design.md) の「背景」を参照。実際にコミット `038ed15` として実装・実機検証まで行ったが、(1) Zenohの自己ループバック、(2) 起動順序に依存する取りこぼし、(3) ローカルクリックだけ特別扱いする非対称設計、という3つの問題が見つかり、`sonar_radar` 本体は元に戻す（revert）ことにした。**revert 自体はまだ実行していない**（2026-07-24時点、`sonar_radar` はまだコミット `038ed15` のまま）。以下は記録として残す。

コアの `SonarRadarSM`（`sonar_radar` リポジトリ側）に、以下の小さな変更を加える必要がある。既存の「1状態=1つの待つできごと」というフラットなステートマシン設計方針に従う。

### 新状態: `WAIT_FOR_PEER_CALIBRATED`

```
INIT → CALIB_TO_ZERO → CALIB_TO_OFFSET → WAIT_FOR_PEER_CALIBRATED → WAIT_FOR_START → SCANNING → RETURN_TO_ORIGIN → TERMINATED
```

- `CALIB_TO_OFFSET` 完了時（`zero_pos` 記録直後）に自分の `calibrated` を publish してから遷移
- 「待つもの」＝相手からの `calibrated` 受信のみ
- endpoint 未設定（従来通りの単独実行）の場合は即座に素通りし、既存の動作を変えない

### イベントフック（オプショナル注入）

`SonarRadarSM` のコンストラクタに、以下のタイミングで呼ばれるコールバックを注入できるようにする（未指定時は no-op、既存動作は不変）。

- 送信: フォースセンサークリック検出時、マーカー検出時、キャリブレーション完了時、スキャンデータ記録時
- 受信: `tick()` 冒頭で `endpoint.process_recv_events()` をポーリング呼び出しし、登録済みコールバック経由でインスタンスフラグ（例: `self._peer_calibrated`）を更新する。非同期ディスパッチ（`start_dispatch()`）は使わず、単一スレッド・同期処理の既存方針を維持する

## ディレクトリ構成（実装済み）

```
sonar_radar-zenoh-bridge/
├── README.md
├── docs/
│   ├── zenoh_state_machine_design.md  # 設計転回後の状態機械設計（進行中）
│   └── development_log.md             # 「テストによる段階的な開発」の進め方と教訓の記録
├── pdu/
│   ├── pdudef.json           # robot_name="Radar" で pdutypes.json を参照
│   └── pdutypes.json         # channel 0-5（calibrate/calibrated/start/stop/detected/scan）
├── config/
│   ├── mac/                  # シム側 endpoint 設定。zenohd はMac自身がローカル(127.0.0.1)で稼働する前提
│   │   ├── endpoint_zenoh.json
│   │   ├── cache/buffer.json
│   │   ├── comm/{zenoh_pubsub_comm.json, zenoh/client.json5}
│   │   └── zenohd/router.json5   # zenohd自体の起動設定（REST + memory storage付き）
│   └── raspi4b/               # 実機側 endpoint 設定。zenoh/client.json5 が Mac の LAN IP へ接続
│       ├── endpoint_zenoh.json
│       ├── cache/buffer.json
│       └── comm/{zenoh_pubsub_comm.json, zenoh/client.json5}
├── bridge/                    # 新設計に基づく実装(状態機械図を1状態ずつ実装しながら進める)
│   ├── spikehat_timer.py      # ワンショットタイマー(C移植を見据えた関数シグネチャ)
│   ├── broker.py              # PDU publish/受信を担う抽象層(hakoniwa_pdu_endpoint.Endpointのラップ)
│   ├── sonar_radar_app.py     # ステートマシン本体。実装済み: INIT/WAIT_CALIBRATED/
│   │                          # CALIBRATION_FAILED/TERMINATED、WAIT_FOR_START_PRESSへの到達まで
│   └── run_calibration_smoke_test.py  # 上記を実際のZenoh経由で動作確認するスクリプト
└── driver/
    └── sonar_radar_zenoh.py   # 【旧, 使わない】sonar_radar の SonarRadarSM を import して
                                 # on_event/notify_*() で配線する転回前の実装。bridge/ に
                                 # 置き換わっていく
```

`config/raspi5/`（`hakoniwa-pdu-ros` bridge 用設定）は未着手。

### PDU定義の実装メモ

トリガー系（calibrate/calibrated/start/stop/detected）は受信そのものに意味があり、ペイロードの中身は使わないため、`hakoniwa-pdu-ros`のROS型システムには頼らず`hakoniwa-pdu-endpoint`の生バイトAPI（`send_by_name`/`subscribe_on_recv_callback_by_name`）を直接使う設計にした。`pdutypes.json`の`type`フィールドはC++側のパーサーが必須とするため空にはできないが、値自体はメタデータとしてのみ扱われ検証はされない（`raw/Trigger`, `raw/RadarScan`という独自表記を採用）。

`scan`のペイロードは自前のバイナリ形式（`struct.pack("<idi", angle, dome_angle, distance_mm)`、16バイト固定）。`angle`/`distance_mm`が`None`のときは番兵値`-2147483648`、`dome_angle`が`None`のときは`NaN`を使う。

### ドライバスクリプトの受信方式について（重要な訂正）

設計段階では「`process_recv_events()`をtickループでポーリングする（A案）」を採用する想定だった。しかし実装時に判明した通り、**この仕組みはSHM（共有メモリ）バックエンド専用で、Zenohバックエンドでは何もしない（no-op）**。Zenohの受信は`z_declare_subscriber`のコールバックがZenoh内部スレッドから直接・非同期に呼ばれる方式で、選択の余地なくB案（非同期コールバック）になる。

ただし影響は`driver/sonar_radar_zenoh.py`側の実装（`subscribe_on_recv_callback_by_name`を直接使う）に閉じており、`sonar_radar`本体の`notify_*()`（単純なbool代入のみ）は元々A案/B案どちらでも動く設計だったため、変更不要だった。

## 実装状況（マシンごと）

| マシン | hakoniwa-pdu-endpoint | 状態 |
|---|---|---|
| Mac（このリポジトリの作業機） | Zenoh有効でビルド・`.local`インストール済み | `bridge/`のマイルストーン1(キャリブレーション)を単体・実機との2台構成の両方で動作確認済み |
| Raspberry Pi 4B+ (`192.168.11.3`, 実機, ホスト名`spike-hat`) | Zenoh有効でビルド・`.local`インストール済み | `sonar_radar-zenoh-bridge`を最新化し、Macとの2台構成でキャリブレーション・start協調動作を実ネットワーク越しに確認済み。実機の物理starterボタン、`radar_base`(旋回モーター)によるキャリブレーションの実接続も確認済み(`bridge/real_starter.py`/`bridge/real_radar_base.py`)。詳細は[`docs/development_log.md`](docs/development_log.md) |
| Raspberry Pi 5 (`192.168.1.4`, Ubuntu 24.04 + ROS2 jazzy) | インストール済み（別トライアルで構築） | `sonar_radar-zenoh-bridge`は未クローン、`config/raspi5`も未着手。ブリッジ/モニタ役として今後着手する |

### Mac向けビルドで詰まった点

ラズパイ向けビルド（別トライアル、hakoniwa-pdu-endpoint#36 参照）とほぼ同じ手順だが、macOS固有の差分があった。

- **Python 3.14ではcffi 1.16.0がビルドできない**。cffi 1.16.0（2023年リリース）は`_PyUnicode_AsString`等、Python 3.14で削除された非推奨APIを使っており、ソースビルドがコンパイルエラーになる。`brew install python@3.12`のPython 3.12を明示的に使う必要がある（`sonar_radar`本体が元々Python 3.12前提なのはこれが理由の一つでもある）
- **`HAKO_PDU_ENDPOINT_ENABLE_HAKONIWA_CORE`はmacOSでもデフォルトON**（`WIN32`以外は全てON）。今回はSHM(Hakoniwa Core)を使わずZenohのみで良いため、`-DHAKO_PDU_ENDPOINT_ENABLE_HAKONIWA_CORE=OFF`を明示して、hakoniwa-core-proのビルドという大きな追加作業を回避した
- **cffi 1.16.0のビルドに`setuptools`が必要**（Python 3.12の素のvenvには入っていない）。`pip install -U setuptools wheel`が必要（README.ja.mdのトラブルシューティングに記載あり）
- **`sonar_radar/.venv`は`uv venv`で作られており、`pip`コマンド自体が入っていない**。うっかり`source .venv/bin/activate && pip install ...`とすると、activateが効いていてもPATH解決の都合でシステムのpip（別のPythonバージョン向け）に誤ってインストールしてしまうことがあった。`uv pip install <pkg>`（venvのある場所で実行）を使うのが安全

## 実行方法（現時点で動く範囲）

`hakoniwa_pdu_endpoint`の動作確認だけなら、`sonar_radar`の venv から以下で確認できる。

```bash
cd ~/Projects/sonar_radar
source .venv/bin/activate
PYTHONPATH=$HOME/.local/lib/hakoniwa-pdu-endpoint/python \
HAKO_PDU_ENDPOINT_LIB_DIR=$HOME/.local/lib/hakoniwa-pdu-endpoint/python/hakoniwa_pdu_endpoint \
HAKO_PDU_ENDPOINT_SHARED_LIB=$HOME/.local/lib/hakoniwa-pdu-endpoint/python/hakoniwa_pdu_endpoint/libhakoniwa_pdu_endpoint.dylib \
python3 -c "from hakoniwa_pdu_endpoint import c_endpoint; print('import ok')"
```

`driver/sonar_radar_zenoh.py`（旧実装）自体の実行は未検証・今後使わない。かわりに`bridge/`配下の新実装は以下の手順で動作確認できる。

### `bridge/` の動作確認（キャリブレーション部分、動作確認済み）

1. zenohdルーターを起動する（`config/mac/zenohd/router.json5`を使用。既に起動中なら不要）。

   ```bash
   cd ~/Projects/sonar_radar-zenoh-bridge/config/mac/zenohd
   zenohd -c router.json5
   ```

2. 別ターミナルで、状態遷移を監視するwatchスクリプトを起動しておく（推奨。任意のタイミングで起動・終了してよい）。

   ```bash
   cd ~/Projects/sonar_radar-zenoh-bridge/bridge
   source env.sh
   source ~/Projects/sonar_radar/.venv/bin/activate
   python3 watch_state.py
   ```

3. さらに別ターミナルで、キャリブレーション部分のスモークテストを実行する。

   ```bash
   cd ~/Projects/sonar_radar-zenoh-bridge/bridge
   source env.sh
   source ~/Projects/sonar_radar/.venv/bin/activate
   python3 run_calibration_smoke_test.py
   ```

   `watch_state.py`側のターミナルに `state -> WAIT_FOR_CALIBRATE` → `state -> CALIBRATING` → `state -> WAIT_FOR_CALIBRATED` → `state -> WAIT_FOR_START_PRESS` と時刻つきで表示されれば成功。`zenohd`のREST経由でも状態を直接確認できる（`curl http://localhost:8000/radar/dome/state`）。

`bridge/env.sh`は`hakoniwa_pdu_endpoint`用の環境変数(`PYTHONPATH`等)をまとめたもの。Pythonの実行環境自体は`sonar_radar/.venv`（Python 3.12, cffi対応）を流用している。

## 依存リポジトリ

- [sonar_radar](https://github.com/kuboaki/sonar_radar) — 参考にする既存のドメインロジック（キャリブレーション・starter・スキャン）だが、**本リポジトリはこれをimportせず無改造のまま扱う**。過去の設計転回前の変更（`WAIT_FOR_PEER_CALIBRATED`状態、`on_event`/`notify_*()`フック、コミット`038ed15`）はrevert済み（`19eccc5`）。実機での経過時間計測のため、状態遷移ログへの`_clock()`タイムスタンプ出力も追加済み（`74f374b`）
- [hakoniwa-pdu-endpoint](https://github.com/hakoniwalab/hakoniwa-pdu-endpoint) — Zenoh 経由の PDU 通信ライブラリ
- [hakoniwa-pdu-ros](https://github.com/hakoniwalab/hakoniwa-pdu-ros) — PDU⇄ROSトピック ブリッジ

## 残作業・次のステップ

**設計継続（優先）**

1. [`docs/zenoh_state_machine_design.md`](docs/zenoh_state_machine_design.md) の状態機械設計を継続（`WAIT_FOR_START_PRESS`/`WAIT_FOR_START_RELEASE`相当、`SCANNING`、`detected`の対称設計、参加者コンフィグの形式、hatの受け取り方など未確定事項が複数残っている）

**実装作業（状態機械図を1状態ずつ実装しながら進める方式、進行中。進め方と教訓は[`docs/development_log.md`](docs/development_log.md)を参照）**

2. [x] `bridge/` パッケージを新設。`INIT → WAIT_FOR_CALIBRATE → CALIBRATING → WAIT_FOR_CALIBRATED → (WAIT_FOR_START_PRESS | CALIBRATION_FAILED → TERMINATED)` を実装し、1プロセス構成(`calibration_participants = {自分のorigin}`)で実際のZenoh(zenohd + hakoniwa_pdu_endpoint)経由のpublish/受信により、成功経路・失敗経路(タイムアウト)の両方を動作確認済み(`bridge/run_calibration_smoke_test.py`)。
3. [x] 実機Raspberry Pi 4B+とMacの2台構成で、キャリブレーションの協調動作(`calibration_participants`が複数originで揃うこと)を実ネットワーク越しに確認済み。詳細は[`docs/development_log.md`](docs/development_log.md)を参照。
4. [x] `WAIT_FOR_START_PRESS` / `WAIT_FOR_START_RELEASE` / `WAIT_FOR_SCAN_START` / `SCANNING`（到達まで）を実装し、実機Raspberry Pi 4B+とMacの2台構成（デモ会場用の別ルーター経由）でstart協調動作を確認済み(`bridge/run_start_smoke_test.py`)。詳細は[`docs/development_log.md`](docs/development_log.md)を参照。
5. [x] `bridge/real_starter.py`(`RealStarter`)を新設し、擬似スイッチではなく実機のフォースセンサー(libspikehat)を直接使う`--real-starter`オプションを追加。実際に実機の物理ボタンを押して、実機・Macとも`SCANNING`まで到達することを確認済み。Build HATには準備完了を問い合わせるAPIが無いため、実際にセンサーが読めるようになるまでポーリングして待つ仕組みを実装した。
6. [x] キャリブレーション処理自体が未実装だった設計上の欠落を修正（`WAIT_CALIBRATED`を`WAIT_FOR_CALIBRATE`/`CALIBRATING`/`WAIT_FOR_CALIBRATED`の3状態に分割）。`bridge/real_radar_base.py`(`RealRadarBase`)を新設し、擬似スタブではなく実機のモーター(libspikehat)を直接使う`--real-radar-base`オプションを追加。実際にモーターが機械的0位置→オフセット位置へホーミングし、`CALIBRATING`が完了することを実機で確認済み。詳細は[`docs/development_log.md`](docs/development_log.md)を参照。
7. [x] `sonar_radar` 本体（コミット`038ed15`）をrevert・push・実機pull済み（`19eccc5`）。あわせて実機での経過時間計測のためのタイムスタンプログ出力も追加・push済み（`74f374b`）。
8. 次のマイルストーン: `MARKER_DETECTED` 以降（`detected`対称処理、`WAIT_FOR_INVERT`、stop対称処理、`SCAN_FAILED`）を同様に1状態ずつ実装し、都度2台構成でも確認する
9. `config/raspi5/`（`hakoniwa-pdu-ros` bridge用設定）の作成、ROSトピックとしてのモニタリング確認(ブリッジ役が実際に必要になった段階で着手)

## ステータス

設計転回中。旧設計（sonar_radar本体への変更）は実装・実機検証まで完了していたが、発見された問題により方針転換し、新しい独立ステートマシンの設計を進めている。PDU定義・zenoh設定・Mac/実機のpdu-endpoint環境構築（インフラ部分）は転回の影響を受けず完了済み。ドライバスクリプトの実装は新設計確定後に着手する。
