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
- `channels[2]`: `name="origin"`, `values=[各サンプルのorigin]`(2026-08-11追加。実機/SIM複数台のデータを1トピックで重畳表示できるよう、既存の`scan`と同じく送信元をoriginで区別する。`robot_name`はプロジェクト全体で`"Radar"`固定・静的なのに対しoriginは起動時`--origin`で渡す動的な値のため、origin毎に別トピックを用意せず単一トピック+`channels`に埋め込む方式を採用した)
- `header.stamp`: バッチ送出時刻。移動体追跡は今回のスコープ外とし、精度は重視しない(参考情報)。

収集した角度・距離・originの組がすべて`channels`にそのまま残るため、データの欠落は無い。実際の可視化(直交座標への変換、origin別のプロット)は受信側の仕事とする。

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

distance_mmの実センサー配線とscan_batchの実装は保留し、まず「ROS側からstart/stopをかけられる」ところをPi5実機で確認済み(2026-08-03)。

1. `bridge/broker.py`のstart/stop標準型化(上記「前提となる未実装ギャップ」2番、解消済み)。
2. `run_real.py`/`run_hako.py`に`--starter`/`--no-starter`を追加(解消済み)。実機・SIM側は`--no-starter`で起動し、物理/擬似スターターとROS注入が競合しないようにする(`consume_start_received()`/`consume_stop_received()`自体はis_starterに関わらず受信を受け付けるので、ガード上は必須ではないが運用上の推奨)。
3. **`config/raspi5/ros_bindings_start_stop.json`**(新設)。ROSトピック→`start`/`stop` PDUへの`ros_to_pdu`一方向binding。
   ```json
   {
     "endpoint_config": "endpoint_zenoh_ros_bridge.json",
     "bindings": [
       { "pdu_key": { "robot_name": "Radar", "pdu_name": "start" }, "topic": "/sonar_radar/start_cmd", "direction": "ros_to_pdu" },
       { "pdu_key": { "robot_name": "Radar", "pdu_name": "stop" },  "topic": "/sonar_radar/stop_cmd",  "direction": "ros_to_pdu" }
     ]
   }
   ```
   **専用のcomm/endpoint設定が必要**: `hakoniwa_pdu_ros`はbinding設定と実際のzenoh comm設定(`notify_on_recv`)の整合性を`validate_zenoh_io_for_config()`で検証する。`config/raspi5/comm/zenoh_pubsub_comm.json`(全チャンネル`notify_on_recv:true`、`sonar_radar`本体用)をそのまま使うと、`start`/`stop`が`ros_to_pdu`(送信のみ、受信通知不要)であることと矛盾し検証エラーになる。そのため`config/raspi5/comm/zenoh_ros_start_stop_comm.json`(`start`/`stop`のみ`notify_on_recv:false`)と、それを参照する`config/raspi5/endpoint_zenoh_ros_bridge.json`を別途新設した。生成コマンド: `python3 -m hakoniwa_pdu_ros.gen_zenoh_io <binding.json> --comm <comm.json> --write`。
4. **Pi5での起動**: `config/raspi5/env_ros_bridge.sh`(新設、必要な環境変数をまとめたもの)を`source`してから起動する。デモ用に`config/raspi5/run_ros_bridge.bash`としてまとめてある(下記5参照)。
   ```bash
   cd ~/Projects/sonar_radar-zenoh-bridge
   source config/raspi5/env_ros_bridge.sh
   ros2 run hakoniwa_pdu_ros bridge --config config/raspi5/ros_bindings_start_stop.json
   ```
   **既知の不具合(解消済み)**: `hakoniwa_pdu_ros/__main__.py`に`if __name__ == "__main__": main()`が無く、`python3 -m hakoniwa_pdu_ros`で実行すると`main()`が一度も呼ばれずに無出力・exit 0で終了する(何も起きない)。`ros2 run`のconsole_scriptsエントリポイントは`main()`を直接呼ぶため問題ない。Pi5では、ソース(`~/Projects/hakoniwa-pdu-ros/hakoniwa_pdu_ros/__main__.py`)にガードを追記して`colcon build --packages-select hakoniwa_pdu_ros`で再ビルド済み(`~/Projects/ros2_ws`)。上流へIssue報告済み: [hakoniwalab/hakoniwa-pdu-ros#13](https://github.com/hakoniwalab/hakoniwa-pdu-ros/issues/13)。
   **既知の不具合(2026-08-04に解消済み)**: `hakoniwa_pdu_ros`ブリッジがstart/stopを中継する際、「stack smashing detected」で非決定的にクラッシュすることがあった。gdbで追跡した結果、依存先の`libzenohc.so`が`hakoniwa-pdu-endpoint`の`.local`インストールに同梱されておらず、実行環境(ROS2 Jazzyの`zenoh_cpp_vendor`パッケージ)が持つ別バージョンのzenoh-cをLD_LIBRARY_PATH経由で誤って読み込み、ABI不整合でスタックが壊れていたことが原因。`hakoniwa-pdu-endpoint`の`install.bash`を修正し、Zenoh有効時は依存先zenoh-cの共有ライブラリも`libhakoniwa_pdu_endpoint.so`と同じディレクトリへ同梱するようにした(`HAKO_PDU_ENDPOINT_ENABLE_ZENOH=ON bash install.bash`)ため、`env_ros_bridge.sh`側の特別な回避策は不要になった。
5. **ROS側の「スターターもどき」**: 専用ノードはまだ作らず、`ros2 topic pub`での手動トリガーで動作確認する。デモを楽にするため、以下3本のスクリプトを`config/raspi5/`に用意した(いずれもPi5で実行すること)。
   ```bash
   # 1. ブリッジを起動する(別ターミナルでフォアグラウンド実行、Ctrl-Cで停止)
   bash config/raspi5/run_ros_bridge.bash

   # 2. startを注入する(実機・SIMのどちらが動いていても、両方動いていても届く)
   bash config/raspi5/demo_ros_start.bash

   # 3. stopを注入する
   bash config/raspi5/demo_ros_stop.bash
   ```
   中身は`ros2 topic pub --once /sonar_radar/start_cmd std_msgs/msg/Bool "{data: true}"`等をラップしただけ。`set -u`は使っていない(`/opt/ros/jazzy/setup.bash`が未定義変数を参照するため、strict mode下だと落ちる)。

**動作確認(2026-08-04)**: Mac(SIM、`run_hako.py`)を相手に、`run_ros_bridge.bash`→`demo_ros_start.bash`→(WAIT_FOR_START_PRESS→SCANNING→マーカー検出/反転を確認)→`demo_ros_stop.bash`→TERMINATEDまで、ブリッジをクラッシュさせずに完走することを確認済み。実機(Pi4)側でも2026-08-03に同じ流れ(SCANNING到達)を確認済みだが、stopまでの完走はSIM側でのみ確認(実機は機材移動のため未実施)。

## scan_batchのROS中継(Pi5、2026-08-11実装・動作確認済み)

`bridge/sonar_radar_ros_bridge.py`(scanを蓄積してscan_batchとしてpublishするZenoh専用プロセス、`docs/sonar_radar_zenoh_bridge.asta`の`pdu_ros_bridge::sonar_radar_ros_bridge`参照)が送出する`scan_batch`(`sensor_msgs/PointCloud`)を、`config/raspi5/ros_bindings_scan_batch.json`(`direction: "pdu_to_ros"`)経由でROSトピックへ中継する。

**実際のトピック名は`/pdu/sonar_radar/scan_batch`になる**(bindingの`topic`指定に関わらず)。`hakoniwa_pdu_ros`は`direction: "pdu_to_ros"`のbindingを常に`/pdu`名前空間の下へマッピングする仕様(`/pdu`はPDU由来トピック専用の予約領域、`config_loader.py`の`_topic_for_direction()`/`_validate_ros_topic()`参照)。`ros_to_pdu`方向(start/stop等)にはこのプレフィックスは付かない。

**既知の不具合(2026-08-11発見・ローカルパッチで解消済み)**: `hakoniwa_pdu_ros`の`type_mapper.py`の`_list_item_type()`は、ネストしたリストフィールド(`sensor_msgs/PointCloud`の`channels: List[ChannelFloat32]`等)の要素型を`dst_parent.__class__.__annotations__`から解決しようとするが、rclpy生成クラスは`__annotations__`が空(型情報は`get_fields_and_field_types()`側にのみ`"sequence<pkg/Msg>"`形式で入っている)。そのため要素型の解決に失敗し、`_copy_list()`が`src_item.__class__()`(hakoniwa_pdu側の`pdu_pytype`クラス、ROS側の型ではない)にフォールバックしてしまい、rclpyのC変換層(`sensor_msgs__msg__channel_float32__convert_from_py`)で`AssertionError`が起きてブリッジプロセスがクラッシュする。`_list_item_type()`に`get_fields_and_field_types()`ベースのフォールバック解決(`"sequence<pkg/Msg>"`から`import_ros_msg_class()`で正しいROS型を解決)を追加し、Pi5の`~/Projects/hakoniwa-pdu-ros/hakoniwa_pdu_ros/type_mapper.py`にローカルパッチ・`colcon build --packages-select hakoniwa_pdu_ros`で再ビルド済み。単純な`float32[]`等のフィールドしか使わない既存のstart/stop/state/scanは影響を受けない(この不具合はネストしたカスタム型リストを持つメッセージ型でのみ発生する)。

**動作確認(2026-08-11)**: Mac上で`bridge.Broker.publish_scan()`をorigin=1(実機を模擬)・origin=2(SIM を模擬)交互に20回ずつ呼ぶ合成データで、`sonar_radar_ros_bridge.py`(Pi5)がscan_batch_size(既定15)件毎に正しくFLUSHING_SCANへ遷移してpublish_scan_batch()を呼び、`ros2 topic echo /pdu/sonar_radar/scan_batch`で`channels`(angle/distance_mm/origin)がoriginごとに正しく区別された値で届くことを確認済み(実機Pi4を使わない合成データでの検証、実機+SIM実データでの通し確認は未実施)。
