#!/usr/bin/env python3
"""run_calibration_smoke_test.py — 第1マイルストーンの動作確認スクリプト。

INIT → WAIT_CALIBRATED → WAIT_FOR_START_PRESS (または → CALIBRATION_FAILED
→ TERMINATED) を、実際のZenoh(hakoniwa-pdu-endpoint)経由のpublish/受信で
確認する。1プロセス・1ノード構成(calibration_participants = {自分の
origin} のみ)で、自分のpublishを自分で受信するループバック経路を
使って検証する。

事前にzenohdが起動していること(config/mac/zenohd/router.json5 を使い、
tcp/0.0.0.0:7447 で待ち受け)。

【注意】calibrate受信→calibrated publishという「キャリブレーション処理」
自体はステートマシン上まだ未設計(CALIBRATINGに相当する状態が無い)。
このスクリプトでは broker.consume_calibrate_received() を使い、
「calibrateを受信したら即座にcalibratedを返す」という最小のスタブで
代替している。SonarRadarApp本体にはこの処理を持たせていない。
"""

from __future__ import annotations

import os
import sys
import time

from broker import Broker
from sonar_radar_app import SonarRadarApp, State
from state_reporter import with_state_change_reporting

_HERE = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_HERE, "..", "config", "mac", "endpoint_zenoh.json")

_MY_ORIGIN = 1
_OVERALL_TIMEOUT_SEC = 10.0
_TICK_INTERVAL_SEC = 0.05


def main() -> int:
    broker = Broker("sonar_radar_zenoh_bridge_smoketest", _MY_ORIGIN)
    broker.open(_CONFIG_PATH)

    app = SonarRadarApp(
        broker=broker,
        calibration_participants={_MY_ORIGIN},
        is_leader=True,
    )
    def _report(state: State) -> None:
        print(f"[smoke-test] state -> {state.value}")
        broker.publish_state(state.value)

    with_state_change_reporting(app, _report)

    deadline = time.monotonic() + _OVERALL_TIMEOUT_SEC
    reached_states = {State.WAIT_FOR_START_PRESS, State.TERMINATED}

    try:
        while time.monotonic() < deadline:
            # calibrate受信 -> calibrated publish のスタブ(SonarRadarAppの外側)
            if broker.consume_calibrate_received():
                print("[smoke-test] calibrate受信(スタブ): calibratedをpublish")
                broker.publish_calibrated()

            app.run()

            if app.state in reached_states:
                break
            time.sleep(_TICK_INTERVAL_SEC)
        else:
            print("[smoke-test] タイムアウト: 状態遷移が完了しなかった", file=sys.stderr)
            return 1
    finally:
        broker.close()

    if app.state is State.WAIT_FOR_START_PRESS:
        print("[smoke-test] OK: WAIT_FOR_START_PRESS に到達しました")
        return 0
    else:
        print(f"[smoke-test] NG: 最終状態 {app.state.value}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
