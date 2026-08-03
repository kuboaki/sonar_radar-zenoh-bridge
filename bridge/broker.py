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
"""

from __future__ import annotations

import struct
import threading

from hakoniwa_pdu_endpoint.c_endpoint import Endpoint, PduKey

_ROBOT = "Radar"
_SCAN_STRUCT = struct.Struct("<Bidi")  # origin(uint8), angle(int32), dome_angle(float64), distance_mm(int32)
_STATE_PDU_SIZE = 32  # pdu/pdutypes.json の state チャンネル(channel_id=6)と合わせる


class Broker:
    def __init__(self, name: str, origin: int) -> None:
        self._origin = origin
        self._origin_bytes = origin.to_bytes(1, "big")
        self._endpoint = Endpoint(name, "inout")
        self._lock = threading.Lock()
        self._start_received = False
        self._stop_received = False
        self._detected_received = False

    def open(self, config_path: str) -> None:
        self._endpoint.open(config_path)
        self._endpoint.start()
        self._endpoint.post_start()
        self._subscribe("start", self._on_start)
        self._subscribe("stop", self._on_stop)
        self._subscribe("detected", self._on_detected)

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

        pdu/pdutypes.json の state チャンネル(32バイト固定)へ、
        "{origin}:{状態名}" をUTF-8でpublishする。全originが同じ1つの
        チャンネルを共有するため、どのマシン(origin)の遷移かを区別
        できるようにoriginを含めている。zenohdのREST/storage_manager
        経由(curl http://localhost:8000/radar/dome/state)や
        bridge/watch_state.py で受信・表示できる。
        """
        text = f"{self._origin}:{state_name}"
        payload = text.encode("utf-8")[:_STATE_PDU_SIZE].ljust(_STATE_PDU_SIZE, b"\x00")
        self._endpoint.send_by_name(PduKey(robot=_ROBOT, pdu="state"), payload)

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

    # --- 内部 ---

    def _publish(self, pdu_name: str) -> None:
        self._endpoint.send_by_name(PduKey(robot=_ROBOT, pdu=pdu_name), self._origin_bytes)

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
