# sonar_radar-zenoh-bridge

[sonar_radar](https://github.com/kuboaki/sonar_radar) の実機とシミュレータを、複数マシンにまたがって Zenoh 経由の PDU（hakoniwa-pdu-endpoint / hakoniwa-pdu-ros）でリアルタイム同期させるトライアル。

sonar_radar 本体は「実機・スタンドアロンSIM・Hakoniwa SIM」という3つの環境をデジタルツインとして共存させる設計だが、本リポジトリはそれとは別レイヤーの実験として、**ネットワーク越しに複数マシン上で動く実機とシミュレータを、start/stop/calibrate等のイベント単位で疎結合に同期させる**ことを目的とする。

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

## sonar_radar 本体側で必要な変更

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
├── pdu/
│   ├── pdudef.json           # robot_name="Radar" で pdutypes.json を参照
│   └── pdutypes.json         # channel 0-5（calibrate/calibrated/start/stop/detected/scan）
├── config/
│   ├── mac/                  # シム側 endpoint 設定。zenohd はMac自身がローカル(127.0.0.1)で稼働する前提
│   │   ├── endpoint_zenoh.json
│   │   ├── cache/buffer.json
│   │   └── comm/{zenoh_pubsub_comm.json, zenoh/client.json5}
│   └── raspi4b/               # 実機側 endpoint 設定。zenoh/client.json5 が Mac の LAN IP へ接続
│       ├── endpoint_zenoh.json
│       ├── cache/buffer.json
│       └── comm/{zenoh_pubsub_comm.json, zenoh/client.json5}
└── driver/
    └── sonar_radar_zenoh.py   # sonar_radar の SonarRadarSM に endpoint を差し込むドライバ
                                 # （sim/sonar_radar_ctrl_hako.py の zenoh 版に相当）
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
| Mac（このリポジトリの作業機） | ビルド済み・`.local`インストール済み | `sonar_radar/.venv`（Python 3.12）から`import hakoniwa_pdu_endpoint`できることを確認済み。zenohd起動・ドライバの実動作確認はこれから |
| Raspberry Pi 4B+ (`192.168.1.62`, 実機, ホスト名`spike-hat`) | 未インストール | `sonar_radar`本体（新状態・フック込み）のpullと実機動作確認は完了。pdu-endpoint一式のビルドがこれから必要 |
| Raspberry Pi 5 (`192.168.1.4`, Ubuntu 24.04 + ROS2 jazzy) | インストール済み（別トライアルで構築） | Zenoh有効でビルド済み。`hakoniwa-pdu-ros` bridgeも稼働実績あり。今回のPDU定義（Radar robot）への対応はこれから |

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

`driver/sonar_radar_zenoh.py`自体の実行はまだ未検証（zenohd起動・実機側環境構築が残っているため）。

## 依存リポジトリ

- [sonar_radar](https://github.com/kuboaki/sonar_radar) — `SonarRadarSM` 本体。`raspi/sonar_radar.py`に`WAIT_FOR_PEER_CALIBRATED`状態と`on_event`/`notify_*()`フックを追加済み（コミット`038ed15`、Mac/実機Pi4B+双方にpull・動作確認済み）
- [hakoniwa-pdu-endpoint](https://github.com/hakoniwalab/hakoniwa-pdu-endpoint) — Zenoh 経由の PDU 通信ライブラリ
- [hakoniwa-pdu-ros](https://github.com/hakoniwalab/hakoniwa-pdu-ros) — PDU⇄ROSトピック ブリッジ

## 残作業・次のステップ

1. Mac上でzenohd（ルーター）を起動する設定を用意し、`driver/sonar_radar_zenoh.py --role sim`を実際に動かして単体確認
2. Raspberry Pi 4B+ (`192.168.1.62`) に`hakoniwa-pdu-endpoint`をビルド・インストール（Mac向け手順のarm64/Linux版、Raspberry Pi OS Bookworm。別トライアルのRaspi5(Ubuntu)向け手順とほぼ同じはずだが要検証）
3. 実機・シム間の疎通確認（calibrated待ち合わせ、start/stop、detected方向反転、scanデータ）
4. `config/raspi5/`（`hakoniwa-pdu-ros` bridge用設定）の作成、ROSトピックとしてのモニタリング確認

## ステータス

設計整理は完了。実装は一部進行中（PDU定義・config・ドライバスクリプトの雛形、Mac側pdu-endpoint環境構築まで完了）。実際のマシン間疎通確認はこれから。
