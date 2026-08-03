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

1. **`scan`の`angle`が常に0固定**: `bridge/sonar_radar_app.py`の`_tick_scanning()`で`self._broker.publish_scan(angle=0, distance_mm=distance_mm)`と実角度が配線されていない。`radar_base`側にはモーター位置取得(`motor_get_position()`)が既にあるため、これを`radar_base_get_position()`のような形で公開し、`_tick_scanning()`から実際の角度を渡すよう配線する必要がある(実機とSIMを同じ2次元グラフ上で比較するために必須、とのユーザー判断)。
2. **既存の`start`/`stop`/`detected`/`state`のバイナリ実装の置き換え**: `bridge/broker.py`は`sonar_radar`・`sonar_radar_sim`・`pdu_ros_bridge`が共有するため、型を変更すると3者とも同時に実装を変更する必要がある(動作確認済みの既存チャンネルへの変更を伴う)。

## 影響範囲

- `pdu/pdutypes.json`: `start`/`stop`/`detected`/`state`の`type`を標準型へ変更、`scan_batch`チャンネルを新設。
- `bridge/broker.py`: `publish_start`/`publish_stop`/`publish_detected`/`publish_state`/`consume_*_received`の実装を標準型のエンコード/デコードに置き換え。`publish_scan_batch`/`consume_scan_received`を新設。標準型のPDU⇔バイト列変換には`hakoniwa_pdu`パッケージ(pip名`hakoniwa-pdu`、v1.6.2)の`pdu_conv_*`/`pdu_pytype_*`(PointCloud/Bool/String等)を利用する。`hakoniwa_pdu_ros`(Pi5)の`PduEndpointManager`も内部で`hakoniwa_pdu_endpoint.c_endpoint.Endpoint`を使っており、broker.pyの通信層と完全に同一のため、バイト列レベルでの相互運用性は問題ない(2026-08-03確認)。`hakoniwa_pdu`はMacの`bridge/`実行環境(`~/Projects/sonar_radar/.venv`)へ導入済み。Pi4・Pi5(Pi5は`hakoniwa-pdu-ros`導入時に既に入っている)にも同様に導入が必要。
  - **既知の不具合**: `hakoniwa_pdu==1.6.2`の`pdu_pytype_Empty.py`はコード生成のバグで`__init__`の中身が空になっており、importの時点で`IndentationError`になる(フィールドを持たないメッセージ型の自動生成コードに共通する不具合の可能性がある)。このため`start`/`stop`/`detected`は`std_msgs/Empty`ではなく`std_msgs/Bool`を採用した(上記対応表参照)。不具合自体は影響を受けないため今回のPDU設計に支障はないが、上流プロジェクトへの報告を別途検討する。
- `bridge/sonar_radar_app.py`: `_tick_scanning()`で実角度を`publish_scan()`へ渡すよう配線変更。
- Raspberry Pi 5側: `hakoniwa_pdu_ros`用のbinding設定(`scan_batch`/`state`: `pdu_to_ros`、ROS側start/stopトピック: `ros_to_pdu`)を新設。
