#!/usr/bin/env python3
"""sonar_radar_ros_bridge — scanを蓄積してscan_batchにまとめるZenoh専用ブリッジ。

docs/sonar_radar_zenoh_bridge.asta の pdu_ros_bridge::sonar_radar_ros_bridge
(クラス図・「sonar_radar_ros_bridge::runのステートマシン図」)を1:1で
翻訳したもの(sonar_radar_app.pyと同じ変換ルール、
docs/zenoh_state_machine_design.md参照)。

sonar_radar/sonar_radar_simのインスタンスではない第三者。Zenoh専用
(rclpy非依存)で、Pi5でこのプロセスを動かし、hakoniwa_pdu_ros(別プロセス、
config/raspi5/run_ros_bridge_scan_batch.bash)がscan_batchをROSトピックへ
中継する。state中継・ROS側start/stop指示の変換はhakoniwa_pdu_rosの汎用
中継(設定のみ)に任せるため、本モジュールはscanの受信中継のみを行う。

状態機械(図の通り、終了状態を持たない): INIT(entry: broker.open()) →
RUNNING(無条件) → ACCUMULATING_SCAN(蓄積件数+1 < scan_batch_size、entry:
バッファへ追加) → RUNNING、または FLUSHING_SCAN(蓄積件数+1 >=
scan_batch_size、またはstop受信時。entry: 直近scanがあれば追加した上で
publish_scan_batch()、バッファをクリア) → RUNNING。
"""

from __future__ import annotations

import argparse
import enum
import os
import sys
import time
from typing import List, Optional

from broker import Broker, ScanSample
from console_report import console_report
from state_reporter import with_state_change_reporting

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_CONFIG = os.path.join(_HERE, "..", "config", "raspi5", "endpoint_zenoh.json")
_TICK_INTERVAL_SEC = 0.05


class State(enum.Enum):
    INIT = "INIT"
    RUNNING = "RUNNING"
    ACCUMULATING_SCAN = "ACCUMULATING_SCAN"
    FLUSHING_SCAN = "FLUSHING_SCAN"


class SonarRadarRosBridge:
    def __init__(
        self,
        broker: Broker,
        broker_config_path: str,
        scan_batch_size: int = 15,
    ) -> None:
        self._broker = broker
        self._broker_config_path = broker_config_path
        self._scan_batch_size = scan_batch_size  # private属性(Astah通り)
        self._state = State.INIT
        self._buffer: List[ScanSample] = []
        self._pending_sample: Optional[ScanSample] = None

    @property
    def state(self) -> State:
        return self._state

    # --- run(): tickごとに呼ばれる ---

    def run(self) -> None:
        if self._state is State.INIT:
            self._tick_init()
        elif self._state is State.RUNNING:
            self._tick_running()
        elif self._state is State.ACCUMULATING_SCAN:
            self._transition_to(State.RUNNING)
        elif self._state is State.FLUSHING_SCAN:
            self._transition_to(State.RUNNING)

    def _tick_init(self) -> None:
        # entry: broker.open()
        self._broker.open(self._broker_config_path)
        self._transition_to(State.RUNNING)  # 無条件遷移

    def _tick_running(self) -> None:
        # 優先順位: scan受信 → stop受信(sonar_radar_app.pyと同じく
        # 「コード上の判定順=優先順位」とする)。
        sample = self._broker.consume_scan_received()
        if sample is not None:
            self._pending_sample = sample
            if len(self._buffer) + 1 < self._scan_batch_size:
                self._transition_to(State.ACCUMULATING_SCAN)
            else:
                self._transition_to(State.FLUSHING_SCAN)
            return
        if self._broker.consume_stop_received():
            self._transition_to(State.FLUSHING_SCAN)

    def _transition_to(self, new_state: State) -> None:
        self._state = new_state
        if new_state is State.ACCUMULATING_SCAN:
            assert self._pending_sample is not None
            self._buffer.append(self._pending_sample)  # entry
            self._pending_sample = None
        elif new_state is State.FLUSHING_SCAN:
            if self._pending_sample is not None:
                self._buffer.append(self._pending_sample)
                self._pending_sample = None
            self._broker.publish_scan_batch(self._buffer)  # entry
            self._buffer = []


def main() -> int:
    parser = argparse.ArgumentParser(description="scan集約・scan_batch publishブリッジ(Pi5, Zenoh専用)")
    parser.add_argument("--config", default=_DEFAULT_CONFIG, help="endpoint_zenoh.json のパス")
    parser.add_argument(
        "--scan-batch-size", type=int, default=15,
        help="蓄積件数の閾値(既定15)。15から変更する場合、pdu/pdutypes.json の "
        "scan_batch の pdu_size を 584 + 12*N バイトに再計算し、全マシンへ配布し"
        "直すこと(既定値のまま使うことを推奨)",
    )
    parser.add_argument("--tick-interval", type=float, default=_TICK_INTERVAL_SEC)
    args = parser.parse_args()

    broker = Broker("sonar_radar_zenoh_bridge_ros_bridge", origin=0, consume_scan=True)
    bridge = SonarRadarRosBridge(
        broker=broker,
        broker_config_path=args.config,
        scan_batch_size=args.scan_batch_size,
    )
    with_state_change_reporting(bridge, lambda s: console_report(s.value, prefix="ros_bridge"))

    print(
        f"[ros_bridge] config={args.config} scan_batch_size={args.scan_batch_size}",
        file=sys.stderr,
    )
    try:
        while True:
            bridge.run()
            time.sleep(args.tick_interval)
    except KeyboardInterrupt:
        pass
    finally:
        broker.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
