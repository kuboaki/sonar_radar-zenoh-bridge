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

## ディレクトリ構成（予定）

まだ実装前のため、設計ドキュメントのみ。今後、以下のような構成を想定している。

```
sonar_radar-zenoh-bridge/
├── README.md
├── config/
│   ├── raspi4b/          # 実機用 endpoint / zenoh 設定
│   ├── mac/              # シム用 endpoint / zenoh 設定、zenohd router.json5
│   └── raspi5/            # bridge (hakoniwa-pdu-ros) 用設定
├── pdu/                    # 上記トピックの pdudef / pdutypes
└── driver/                 # sonar_radar の SonarRadarSM に endpoint を差し込むドライバスクリプト
                             # （sim/sonar_radar_ctrl_hako.py の zenoh 版に相当）
```

## 依存リポジトリ

- [sonar_radar](https://github.com/kuboaki/sonar_radar) — `SonarRadarSM` 本体（コアへの変更が必要）
- [hakoniwa-pdu-endpoint](https://github.com/hakoniwalab/hakoniwa-pdu-endpoint) — Zenoh 経由の PDU 通信ライブラリ
- [hakoniwa-pdu-ros](https://github.com/hakoniwalab/hakoniwa-pdu-ros) — PDU⇄ROSトピック ブリッジ

## ステータス

設計整理段階。実装未着手。
