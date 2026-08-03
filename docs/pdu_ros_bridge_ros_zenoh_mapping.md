# pdu_ros_bridge: ROS⇔Zenoh変換仕様

`pdu_ros_bridge::sonar_radar_ros_bridge`(Raspberry Pi 5)の設計に伴い、既存PDU(`start`/`stop`/`detected`/`scan`/`state`)と新設PDU(`scan_batch`)を、ROS側とどう対応づけるかを決めた記録。設計の経緯は`docs/sonar_radar_zenoh_bridge.asta`のクラス図・状態機械図(`pdu_ros_bridge::sonar_radar_ros_bridge`)を参照。

## 背景: なぜ標準メッセージ型が必要か

`hakoniwa_pdu_ros`(Raspberry Pi 5に導入済み、汎用のPDU⇔ROSトピック中継ツール)は、設定ファイルだけで動く汎用中継だが、変換できるのは`hakoniwa_pdu`パッケージにあらかじめ用意された標準メッセージ型(`std_msgs`/`sensor_msgs`/`geometry_msgs`/`hako_msgs`など)のみ。

現行の`start`/`stop`/`detected`/`scan`/`state`は、この案件独自の生バイト列(`raw/Trigger`・`raw/RadarScan`・`raw/State`、`bridge/broker.py`で`struct.pack`により手詰め)であり、標準カタログに存在しないため、このままでは`hakoniwa_pdu_ros`で中継できない。

対応として、これらのPDUを標準メッセージ型に置き換える(A案)。これにより、state中継とROS側start/stop指示の変換は`hakoniwa_pdu_ros`の設定のみ(コード不要、別プロセス)で賄えるようになる。`sonar_radar_ros_bridge`自身はZenoh専用(rclpy非依存)のまま、scanの蓄積(バッファリング)ロジックだけを自前で持つ。

## 対応表

| 現行PDU | 現行の型 | 新しい型 | 対応 |
|---|---|---|---|
| `start`/`stop`/`detected` | `raw/Trigger`(origin 1byte) | `std_msgs/Bool` | `data: bool`。常に`true`を送る単純なトリガーとして使う(`data`は将来の用途のために予約したパラメータで、現状は値そのものに意味を持たせない)。originはROS側では扱わない(`scan`も同様にorigin無し)。 |
| `state` | `raw/State`(`"{origin}:{name}"` 32byte固定UTF-8) | `std_msgs/String` | `data: str`に既存の`"{origin}:{state_name}"`文字列をそのまま格納。 |
| `scan`(個別、Zenoh内部専用) | `raw/RadarScan`(angle int32, dome_angle float64(未使用), distance_mm int32、16byte) | 変更なし(ROSへは直接渡らない) | `sonar_radar_ros_bridge`が受信・蓄積するだけで、ROS側へは`scan_batch`を経由してのみ渡る。 |
| `scan_batch`(新設) | — | `sensor_msgs/PointCloud` | 下記参照。 |

## scan_batch → sensor_msgs/PointCloud

`sensor_msgs/LaserScan`は角度の等間隔割り当て(`angle_min`+`i`×`angle_increment`)を前提とするため、実機の旋回速度にムラがある(2026-08-03の実測で確認済み)現状では個々のサンプルの実角度を保全できず、不採用とした。

代わりに`sensor_msgs/PointCloud`(`header`/`points: List[Point32]`/`channels: List[ChannelFloat32]`)を採用する。ただし、角度→直交座標(x, y)への変換は`sonar_radar_ros_bridge`の責務とせず、受信側(ROSノードや可視化ツール)に委ねる。

**注記(型の転用について)**: `sensor_msgs/PointCloud`は本来、LiDARやドローンの3次元位置認識など、3次元位置データを表すためのROS標準型である。今回はその本来の意味(3次元座標の点群)としては使わず、`channels`が持つ「名前付きfloat配列を任意個添付できる」という構造だけを流用し、レーダーのスキャンデータ(角度・距離)を運ぶ汎用の入れ物として転用している、という認識のもとで採用している。

- `points[]`: 空リスト。`points`と`channels[].values`の件数一致はrviz等の可視化ツールが期待する慣習であって、`PointCloud`メッセージ自体(および`hakoniwa_pdu`の変換コード)が構造的に要求するものではないため、ダミー値で埋める必要はない。
- `channels[0]`: `name="angle"`, `values=[各サンプルの角度]`
- `channels[1]`: `name="distance_mm"`, `values=[各サンプルの距離(mm)]`
- `header.stamp`: バッチ送出時刻。移動体追跡は今回のスコープ外とし、精度は重視しない(参考情報)。

収集した角度・距離のペアがすべて`channels`にそのまま残るため、データの欠落は無い。実際の可視化(直交座標への変換、プロット)は受信側の仕事とする。

## 前提となる未実装ギャップ(要対応)

上記の設計を成立させるには、以下の既存ギャップの解消が前提となる。

1. **`scan`の`angle`が常に0固定**: (2026-08-03 解消済み) `radar_base`に`get_position()`(モーターの生角度)/`get_dome_angle()`(ギア比補正後のドーム角度、`-get_position()/gear_ratio`)を追加し、`hardware.py`経由で`sonar_radar_app.py`の`_tick_scanning()`から両方呼び出すよう配線した。あわせて`scan`にoriginが無く実機/SIM同時稼働時にデータを区別できなかった問題も修正した(`_SCAN_STRUCT`に`origin`を追加)。Astah側もSCANNINGのdoActivity・`radar_base`の操作・`broker.publish_scan()`の引数を更新済み。実機+SIMの組み合わせで`dome_angle = -angle/3`が全サンプルで一致することを確認済み。
2. **既存の`start`/`stop`/`detected`/`state`のバイナリ実装の置き換え**: (2026-08-03 解消済み) `bridge/broker.py`の`publish_start`/`publish_stop`/`publish_detected`/`publish_state`/`_publish`を、`hakoniwa_pdu`パッケージの`pdu_conv_Bool`/`pdu_conv_String`を使うよう書き換えた。`start`/`stop`/`detected`は`std_msgs/Bool`(実測28byte、常に`data=true`)、`state`は`std_msgs/String`(実測152byte、`"{origin}:{state_name}"`)。`pdu/pdutypes.json`の`pdu_size`もこれに合わせて変更した(`start`/`stop`/`detected`: 1→28、`state`: 32→152)。`bridge/watch_all.py`/`watch_state.py`の表示側も追従済み。1プロセス自己ループバックで動作確認済み。**注記**: `hakoniwa_pdu`のエンコード形式は単純な値の詰め替えではなく、24byteのメタデータヘッダ+データ部という独自バイナリ形式(`binary_io.PduMetaData.PDU_META_DATA_SIZE=24`)。`pdu_size`はこの合計サイズに合わせる必要がある。

## 影響範囲

- `pdu/pdutypes.json`: `start`/`stop`/`detected`/`state`の`type`を標準型へ変更、`scan_batch`チャンネルを新設。
- `bridge/broker.py`: `publish_start`/`publish_stop`/`publish_detected`/`publish_state`/`consume_*_received`の実装を標準型のエンコード/デコードに置き換え。`publish_scan_batch`/`consume_scan_received`を新設。標準型のPDU⇔バイト列変換には`hakoniwa_pdu`パッケージ(pip名`hakoniwa-pdu`、v1.6.2)の`pdu_conv_*`/`pdu_pytype_*`(PointCloud/Bool/String等)を利用する。`hakoniwa_pdu_ros`(Pi5)の`PduEndpointManager`も内部で`hakoniwa_pdu_endpoint.c_endpoint.Endpoint`を使っており、broker.pyの通信層と完全に同一のため、バイト列レベルでの相互運用性は問題ない(2026-08-03確認)。`hakoniwa_pdu`はMacの`bridge/`実行環境(`~/Projects/sonar_radar/.venv`)へ導入済み。Pi4・Pi5(Pi5は`hakoniwa-pdu-ros`導入時に既に入っている)にも同様に導入が必要。
  - **既知の不具合**: `hakoniwa_pdu==1.6.2`の`pdu_pytype_Empty.py`はコード生成のバグで`__init__`の中身が空になっており、importの時点で`IndentationError`になる(フィールドを持たないメッセージ型の自動生成コードに共通する不具合の可能性がある)。このため`start`/`stop`/`detected`は`std_msgs/Empty`ではなく`std_msgs/Bool`を採用した(上記対応表参照)。不具合自体は影響を受けないため今回のPDU設計に支障はないが、上流プロジェクトへの報告を別途検討する。
- `bridge/sonar_radar_app.py`: `_tick_scanning()`で実角度を`publish_scan()`へ渡すよう配線変更。
- Raspberry Pi 5側: `hakoniwa_pdu_ros`用のbinding設定(`scan_batch`/`state`: `pdu_to_ros`、ROS側start/stopトピック: `ros_to_pdu`)を新設。

## ROS側からのstart/stop注入(距離センサー配線・scan_batchより先行して実施)

distance_mmの実センサー配線とscan_batchの実装は保留し、まず「ROS側からstart/stopをかけられる」ところまでを先に成立させる。

1. `bridge/broker.py`のstart/stop標準型化(上記「前提となる未実装ギャップ」2番、解消済み)。
2. `config/raspi5/ros_bindings_start_stop.json`(新設)。ROSトピック→`start`/`stop` PDUへの`ros_to_pdu`一方向binding。
   ```json
   {
     "endpoint_config": "endpoint_zenoh.json",
     "bindings": [
       { "pdu_key": { "robot_name": "Radar", "pdu_name": "start" }, "topic": "/sonar_radar/start_cmd", "direction": "ros_to_pdu" },
       { "pdu_key": { "robot_name": "Radar", "pdu_name": "stop" },  "topic": "/sonar_radar/stop_cmd",  "direction": "ros_to_pdu" }
     ]
   }
   ```
   Pi5での起動: `ros2 run hakoniwa_pdu_ros bridge --config config/raspi5/ros_bindings_start_stop.json`(`hakoniwa-pdu-ros`のsetup.pyで`bridge`エントリポイントとして登録されている)。
3. **ROS側の「スターターもどき」**: 専用ノードはまだ作らず、`ros2 topic pub`での手動トリガーで動作確認する。
   ```bash
   ros2 topic pub --once /sonar_radar/start_cmd std_msgs/msg/Bool "{data: true}"
   ros2 topic pub --once /sonar_radar/stop_cmd  std_msgs/msg/Bool "{data: true}"
   ```
   実機・SIM側は`is_starter=False`にしておく(物理スターターとROS注入が競合しないようにするため、運用上の推奨。ガード上は必須ではない、`consume_start_received()`/`consume_stop_received()`はis_starterに関わらず受信を受け付ける設計のため)。

まだ実施していない: 上記2・3の実機(Pi5)での動作確認。
