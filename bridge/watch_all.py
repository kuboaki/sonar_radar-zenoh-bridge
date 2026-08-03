#!/usr/bin/env python3
"""watch_all.py — sonar_radar-zenoh-bridge の全PDUメッセージを時系列で観測するツール。

watch_state.py はアプリが自己申告する状態(state)チャンネルだけを見るが、
アプリの実装にバグがあれば自己申告自体が誤りうる。こちらはzenohd上で
実際にやり取りされる生メッセージ(start/stop/detected/scan)を直接購読し、
アプリの自己申告に頼らず「実際に何がいつ・どのoriginから送られたか」を
時系列で確認できるようにする。

start/stop/detected/stateは、hakoniwa_pduの標準メッセージ型(std_msgs/Bool,
std_msgs/String)でエンコードされている(docs/pdu_ros_bridge_ros_zenoh_mapping.md
参照)。start/stop/detectedはoriginを含まない単純なトリガーのため送信元は
表示しない。stateは"{origin}:{状態名}"形式なので送信元を表示できる。
scanは今のところROSへ直接渡らない内部専用チャンネルのため、従来通り
自前のバイナリ形式(origin・角度・dome角度・距離)のまま。

使い方:
  python3 bridge/watch_all.py [--config path/to/endpoint_zenoh.json] 2>/dev/null

(stderrにはhakoniwa_pdu_endpointライブラリの"WARNING: No subscribers
found..."が出るため、watch_state.pyと同様2>/dev/nullで分離すること)
"""

from __future__ import annotations

import argparse
import datetime
import os
import struct
import sys
import time

from hakoniwa_pdu.pdu_msgs.std_msgs.pdu_conv_String import pdu_to_py_String
from hakoniwa_pdu_endpoint.c_endpoint import Endpoint, PduKey

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_CONFIG = os.path.join(_HERE, "..", "config", "mac", "endpoint_zenoh.json")
_ROBOT = "Radar"
_SCAN_STRUCT = struct.Struct("<Bidi")  # origin(uint8), angle(int32), dome_angle(float64), distance_mm(int32)

_TRIGGER_CHANNELS = ["start", "stop", "detected"]


def _now() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]


def main() -> int:
    parser = argparse.ArgumentParser(description="全PDUメッセージ(生のトリガー含む)を時系列で観測する")
    parser.add_argument("--config", default=_DEFAULT_CONFIG, help="endpoint_zenoh.json のパス")
    args = parser.parse_args()

    endpoint = Endpoint("sonar_radar_zenoh_bridge_watch_all", "inout")
    endpoint.open(args.config)
    endpoint.start()
    endpoint.post_start()

    def _make_trigger_cb(pdu_name: str):
        def _cb(_key, _payload: bytes) -> None:
            print(f"[{_now()}] {pdu_name}", flush=True)

        return _cb

    for pdu_name in _TRIGGER_CHANNELS:
        endpoint.subscribe_on_recv_callback_by_name(
            PduKey(robot=_ROBOT, pdu=pdu_name), _make_trigger_cb(pdu_name)
        )

    def _on_scan(_key, payload: bytes) -> None:
        try:
            origin, angle, dome_angle, distance_mm = _SCAN_STRUCT.unpack(payload)
        except struct.error:
            print(f"[{_now()}]         scan (unpack失敗)", flush=True)
            return
        print(
            f"[{_now()}] origin={origin:<3} scan angle={angle} dome_angle={dome_angle} distance_mm={distance_mm}",
            flush=True,
        )

    endpoint.subscribe_on_recv_callback_by_name(PduKey(robot=_ROBOT, pdu="scan"), _on_scan)

    def _on_state(_key, payload: bytes) -> None:
        try:
            text = pdu_to_py_String(bytearray(payload)).data
        except (ValueError, struct.error):
            print(f"[{_now()}]         state (unpack失敗)", flush=True)
            return
        origin, _, state_name = text.partition(":")
        print(f"[{_now()}] origin={origin:<3} state -> {state_name or text}", flush=True)

    endpoint.subscribe_on_recv_callback_by_name(PduKey(robot=_ROBOT, pdu="state"), _on_state)

    print(
        f"[watch_all] 監視中... (config={args.config}) Ctrl-C で終了 (stderrは2>/dev/nullで分離推奨)",
        flush=True,
    )
    try:
        while True:
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        endpoint.stop()
        endpoint.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
