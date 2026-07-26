#!/usr/bin/env python3
"""run_calibration_smoke_test.py — 第1マイルストーンの動作確認スクリプト。

INIT → WAIT_CALIBRATED → WAIT_FOR_START_PRESS (または → CALIBRATION_FAILED
→ TERMINATED) を、実際のZenoh(hakoniwa-pdu-endpoint)経由のpublish/受信で
確認する。

デフォルトは1プロセス・1ノード構成(calibration_participants = {自分の
origin} のみ)で、自分のpublishを自分で受信するループバック経路を使って
検証する。--origin/--participants/--config を指定すれば、実機・シムなど
複数マシンにまたがる構成でも同じスクリプトを使って検証できる。

事前にzenohdが起動していること(config/mac/zenohd/router.json5 を使い、
tcp/0.0.0.0:7447 で待ち受け)。

【注意】calibrate受信→calibrated publishという「キャリブレーション処理」
自体はステートマシン上まだ未設計(CALIBRATINGに相当する状態が無い)。
このスクリプトでは broker.consume_calibrate_received() を使い、
「calibrateを受信したら即座にcalibratedを返す」という最小のスタブで
代替している。SonarRadarApp本体にはこの処理を持たせていない。
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from broker import Broker
from console_report import console_report
from sonar_radar_app import SonarRadarApp, State
from state_reporter import with_state_change_reporting

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_CONFIG = os.path.join(_HERE, "..", "config", "mac", "endpoint_zenoh.json")

_OVERALL_TIMEOUT_SEC = 10.0
_TICK_INTERVAL_SEC = 0.05


def _parse_participants(text: str) -> set:
    return {int(v) for v in text.split(",") if v.strip()}


def main() -> int:
    parser = argparse.ArgumentParser(description="キャリブレーション部分の動作確認スクリプト")
    parser.add_argument("--config", default=_DEFAULT_CONFIG, help="endpoint_zenoh.json のパス")
    parser.add_argument("--origin", type=int, default=1, help="自分のorigin識別子")
    parser.add_argument(
        "--participants",
        default=None,
        help="calibration_participantsのカンマ区切り(例: 1,2)。省略時は自分のoriginのみ",
    )
    parser.add_argument("--leader", action="store_true", help="is_leader=True にする")
    parser.add_argument(
        "--timeout", type=float, default=_OVERALL_TIMEOUT_SEC, help="全体のタイムアウト秒数"
    )
    args = parser.parse_args()

    participants = (
        _parse_participants(args.participants) if args.participants else {args.origin}
    )

    broker = Broker(f"sonar_radar_zenoh_bridge_smoketest_{args.origin}", args.origin)
    broker.open(args.config)

    app = SonarRadarApp(
        broker=broker,
        calibration_participants=participants,
        is_leader=args.leader,
    )

    def _report(state: State) -> None:
        console_report(state.value, prefix="smoke-test")
        broker.publish_state(state.value)

    with_state_change_reporting(app, _report)

    deadline = time.monotonic() + args.timeout
    reached_states = {State.WAIT_FOR_START_PRESS, State.TERMINATED}

    print(
        f"[smoke-test] origin={args.origin} participants={sorted(participants)} "
        f"leader={args.leader} config={args.config}"
    )

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
