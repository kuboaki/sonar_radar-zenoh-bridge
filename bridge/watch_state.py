#!/usr/bin/env python3
"""watch_state.py — sonar_radar_app の状態遷移を外部から観測するツール。

bridge/run_calibration_smoke_test.py 等とは別プロセス・別ターミナルで
起動し、pdu/pdutypes.json の state チャンネル(broker.publish_state()が
publishする)を受信して、変化のたびに時刻つきで表示する。

同じ仕組みは実機・シムをまたいだ確認でも使える(接続先のzenohdが同じで
あれば、どのマシンからでもこのスクリプトで状態を観測できる)。

使い方:
  python3 bridge/watch_state.py [--config path/to/endpoint_zenoh.json]
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys
import time

from hakoniwa_pdu_endpoint.c_endpoint import Endpoint, PduKey

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_CONFIG = os.path.join(_HERE, "..", "config", "mac", "endpoint_zenoh.json")
_ROBOT = "Radar"


def main() -> int:
    parser = argparse.ArgumentParser(description="sonar_radar_app の状態遷移を監視する")
    parser.add_argument("--config", default=_DEFAULT_CONFIG, help="endpoint_zenoh.json のパス")
    args = parser.parse_args()

    endpoint = Endpoint("sonar_radar_zenoh_bridge_watch_state", "inout")
    endpoint.open(args.config)
    endpoint.start()
    endpoint.post_start()

    def _on_recv(_key, payload: bytes) -> None:
        state_name = payload.rstrip(b"\x00").decode("utf-8", errors="replace")
        now = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{now}] state -> {state_name}", flush=True)

    endpoint.subscribe_on_recv_callback_by_name(PduKey(robot=_ROBOT, pdu="state"), _on_recv)

    print(f"[watch_state] 監視中... (config={args.config}) Ctrl-C で終了", flush=True)
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
