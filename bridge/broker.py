"""broker — sonar_radar-zenoh-bridge の PDU publish/受信を担う抽象層。

docs/zenoh_state_machine_design.md の「アーキテクチャ概要」で設計した
broker クラスの実装。実体は hakoniwa_pdu_endpoint.c_endpoint.Endpoint
(Zenohバックエンド)をラップしたもの。

受信はZenohの非同期コールバックだが、内部でフラグ化し、
consume_*_received() はポーリングで一度だけtrueを返して内部フラグを
クリアする(旧 driver/sonar_radar_zenoh.py の notify_*()と同じ考え方)。

start/stop/detected のいずれも、自分のpublishが自分に
ループバックしてくることを特別扱いしない
(docs/zenoh_state_machine_design.md の設計方針どおり)。

calibrate/calibratedのマシン間協調は廃止したため、このクラスは
扱わない(経緯はdocs/zenoh_state_machine_design.md
「背景: キャリブレーション協調の廃止」参照)。

start/stop/detected/state は、hakoniwa_pdu_ros(Pi5)の汎用PDU⇔ROS中継が
変換できる標準メッセージ型(std_msgs/Bool, std_msgs/String)でエンコードする
(docs/pdu_ros_bridge_ros_zenoh_mapping.md参照)。エンコードは
hakoniwa_pduパッケージのpdu_conv_*/pdu_pytype_*を使い、独自struct.packでは
手詰めしない(バイト列レベルでhakoniwa_pdu_rosと一致させるため)。
scanは今のところROSへ直接渡らない内部専用チャンネルのため、従来通り
struct.packの生バイト列のままにしている。

scan_batch(pdu_ros_bridge::sonar_radar_ros_bridgeがscanを蓄積して
まとめてpublishするPDU、docs/pdu_ros_bridge_ros_zenoh_mapping.md参照)は
sensor_msgs/PointCloudでエンコードする。scanの購読は、consume_scan=True
(既定False)で構築した場合のみ有効になるopt-inの別立てFIFOキューで扱う
(start/stop/detectedの「前回チェック以降に来たか」を合流させる真偽値
フラグ方式と異なり、scanは1件も欠落させず全サンプルを消費する必要がある
ため)。既定Falseのままなら、SonarRadarAppが使う既存のBrokerは一切
影響を受けない。
"""

from __future__ import annotations

import collections
import struct
import threading
import time
from typing import NamedTuple, Optional, Sequence

from hakoniwa_pdu.pdu_msgs.sensor_msgs.pdu_conv_PointCloud import py_to_pdu_PointCloud
from hakoniwa_pdu.pdu_msgs.sensor_msgs.pdu_pytype_ChannelFloat32 import ChannelFloat32
from hakoniwa_pdu.pdu_msgs.sensor_msgs.pdu_pytype_PointCloud import PointCloud
from hakoniwa_pdu.pdu_msgs.std_msgs.pdu_conv_Bool import py_to_pdu_Bool
from hakoniwa_pdu.pdu_msgs.std_msgs.pdu_conv_String import py_to_pdu_String
from hakoniwa_pdu.pdu_msgs.std_msgs.pdu_pytype_Bool import Bool
from hakoniwa_pdu.pdu_msgs.std_msgs.pdu_pytype_String import String
from hakoniwa_pdu_endpoint.c_endpoint import Endpoint, PduKey

_ROBOT = "Radar"
_SCAN_STRUCT = struct.Struct("<Bidi")  # origin(uint8), angle(int32), dome_angle(float64), distance_mm(int32)

# consume_scan=Trueなプロセス(sonar_radar_ros_bridge.py)のtickが数秒詰まっても
# 実害が出ないための安全網。scan_batch_size(既定15)の100倍以上の余裕を持たせてある。
_SCAN_QUEUE_MAXLEN = 2000


class ScanSample(NamedTuple):
    origin: int
    angle: int
    dome_angle: float
    distance_mm: int


def _encode_bool(value: bool) -> bytes:
    obj = Bool()
    obj.data = value
    return bytes(py_to_pdu_Bool(obj))


def _encode_string(value: str) -> bytes:
    obj = String()
    obj.data = value
    return bytes(py_to_pdu_String(obj))


class Broker:
    def __init__(self, name: str, origin: int, *, consume_scan: bool = False) -> None:
        self._origin = origin
        self._endpoint = Endpoint(name, "inout")
        self._lock = threading.Lock()
        self._start_received = False
        self._stop_received = False
        self._detected_received = False
        self._consume_scan = consume_scan
        self._scan_queue: "collections.deque[ScanSample]" = collections.deque(maxlen=_SCAN_QUEUE_MAXLEN)

    def open(self, config_path: str) -> None:
        self._endpoint.open(config_path)
        self._endpoint.start()
        self._endpoint.post_start()
        self._subscribe("start", self._on_start)
        self._subscribe("stop", self._on_stop)
        self._subscribe("detected", self._on_detected)
        if self._consume_scan:
            self._subscribe("scan", self._on_scan)

    def close(self) -> None:
        self._endpoint.stop()
        self._endpoint.close()

    # --- publish系 ---

    def publish_start(self) -> None:
        self._publish("start")

    def publish_stop(self) -> None:
        self._publish("stop")

    def publish_detected(self) -> None:
        self._publish("detected")

    def publish_scan(self, angle: int, dome_angle: float, distance_mm: int) -> None:
        payload = _SCAN_STRUCT.pack(self._origin, angle, dome_angle, distance_mm)
        self._endpoint.send_by_name(PduKey(robot=_ROBOT, pdu="scan"), payload)

    def publish_state(self, state_name: str) -> None:
        """状態遷移を外部から観測できるようにする(designed APIには無い、観測用の追加メソッド)。

        pdu/pdutypes.json の state チャンネル(std_msgs/String)へ、
        "{origin}:{状態名}" をUTF-8でpublishする。全originが同じ1つの
        チャンネルを共有するため、どのマシン(origin)の遷移かを区別
        できるようにoriginを含めている。zenohdのREST/storage_manager
        経由(curl http://localhost:8000/radar/dome/state)や
        bridge/watch_state.py で受信・表示できる。
        """
        text = f"{self._origin}:{state_name}"
        payload = _encode_string(text)
        self._endpoint.send_by_name(PduKey(robot=_ROBOT, pdu="state"), payload)

    def publish_scan_batch(self, samples: Sequence[ScanSample]) -> None:
        """蓄積したscanレコード群をscan_batch PDU(sensor_msgs/PointCloud)としてpublishする。

        pdu_ros_bridge::sonar_radar_ros_bridgeのFLUSHING_SCAN(状態機械図)から
        呼ばれる想定。samplesが空(stop受信時に蓄積0件だった場合)でも、
        図の設計通り無条件にpublishする(空channelsが送出されるだけで実害は無い)。
        角度・距離に加え、実機/SIM複数台のデータを1トピックで重畳表示できるよう
        originもchannelsに含める(docs/pdu_ros_bridge_ros_zenoh_mapping.md参照)。
        """
        obj = PointCloud()
        now = time.time()
        obj.header.stamp.sec = int(now)
        obj.header.stamp.nanosec = int((now - int(now)) * 1e9)

        angle_ch = ChannelFloat32()
        angle_ch.name = "angle"
        angle_ch.values = [float(s.angle) for s in samples]

        distance_ch = ChannelFloat32()
        distance_ch.name = "distance_mm"
        distance_ch.values = [float(s.distance_mm) for s in samples]

        origin_ch = ChannelFloat32()
        origin_ch.name = "origin"
        origin_ch.values = [float(s.origin) for s in samples]

        obj.channels = [angle_ch, distance_ch, origin_ch]
        payload = bytes(py_to_pdu_PointCloud(obj))
        self._endpoint.send_by_name(PduKey(robot=_ROBOT, pdu="scan_batch"), payload)

    # --- consume系 (ポーリング、一度だけtrueを返し内部フラグをクリア) ---

    def consume_start_received(self) -> bool:
        with self._lock:
            v, self._start_received = self._start_received, False
            return v

    def consume_stop_received(self) -> bool:
        with self._lock:
            v, self._stop_received = self._stop_received, False
            return v

    def consume_detected_received(self) -> bool:
        with self._lock:
            v, self._detected_received = self._detected_received, False
            return v

    def consume_scan_received(self) -> Optional[ScanSample]:
        """scanキューから1件FIFOでpopする。無ければNone(consume_scan=False構築時は常にNone)。"""
        with self._lock:
            if not self._scan_queue:
                return None
            return self._scan_queue.popleft()

    # --- 内部 ---

    def _publish(self, pdu_name: str) -> None:
        """トリガー系(start/stop/detected)をstd_msgs/Boolでpublishする。

        dataは常にtrue(単純なトリガー、将来用途のために予約したパラメータ)。
        originはこのメッセージ型には含まれない(scanと同様に、これらの
        チャンネルではoriginを扱わない設計)。
        """
        self._endpoint.send_by_name(PduKey(robot=_ROBOT, pdu=pdu_name), _encode_bool(True))

    def _subscribe(self, pdu_name: str, on_recv) -> None:
        def _cb(_key, payload: bytes) -> None:
            on_recv(payload)

        self._endpoint.subscribe_on_recv_callback_by_name(PduKey(robot=_ROBOT, pdu=pdu_name), _cb)

    def _on_start(self, _payload: bytes) -> None:
        with self._lock:
            self._start_received = True

    def _on_stop(self, _payload: bytes) -> None:
        with self._lock:
            self._stop_received = True

    def _on_detected(self, _payload: bytes) -> None:
        with self._lock:
            self._detected_received = True

    def _on_scan(self, payload: bytes) -> None:
        try:
            sample = ScanSample(*_SCAN_STRUCT.unpack(payload))
        except struct.error:
            return
        with self._lock:
            self._scan_queue.append(sample)  # maxlen到達時はdequeが自動的に最古の1件を破棄する
