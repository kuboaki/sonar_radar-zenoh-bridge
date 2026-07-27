#!/usr/bin/env python3
"""run_calibration_smoke_test.py — 第1マイルストーンの動作確認スクリプト。

INIT → WAIT_FOR_CALIBRATE → CALIBRATING → WAIT_FOR_CALIBRATED →
WAIT_FOR_START_PRESS (または → CALIBRATION_FAILED → TERMINATED) を、
実際のZenoh(hakoniwa-pdu-endpoint)経由のpublish/受信で確認する。

デフォルトは1プロセス・1ノード構成(calibration_participants = {自分の
origin} のみ)で、自分のpublishを自分で受信するループバック経路を使って
検証する。--origin/--participants/--config を指定すれば、実機・シムなど
複数マシンにまたがる構成でも同じスクリプトを使って検証できる。

事前にzenohdが起動していること(config/mac/zenohd/router.json5 を使い、
tcp/0.0.0.0:7447 で待ち受け)。

既定ではradar_baseは擬似スタブ(radar_base_is_calibrated=lambda: True、
CALIBRATINGを即座に完了させる)。--real-radar-base を指定すると実機
(Raspberry Pi)のlibspikehatモーターを直接使い、実際に機械的0位置への
ホーミングを行う(real_radar_base.RealRadarBase)。
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
    parser.add_argument(
        "--calibration-timeout", type=float, default=5.0, help="CALIBRATING系のタイムアウト秒数(既定5秒)"
    )
    parser.add_argument(
        "--real-radar-base",
        action="store_true",
        help="radar_baseを擬似スタブではなく実機のモーター(libspikehat)で動かす",
    )
    args = parser.parse_args()

    participants = (
        _parse_participants(args.participants) if args.participants else {args.origin}
    )

    # ハードウェア初期化はbroker.open()より前(run()が動き出す前)に完了させる
    # (calibration_timeout_secはハードウェア初期化時間を吸収するものではない)。
    radar_base_close = None
    if args.real_radar_base:
        from real_radar_base import RealRadarBase

        real_radar_base = RealRadarBase()
        radar_base_calibrate = real_radar_base.calibrate
        radar_base_is_calibrated = real_radar_base.is_calibrated
        radar_base_close = real_radar_base.close
    else:
        radar_base_calibrate = None
        radar_base_is_calibrated = lambda: True  # noqa: E731 (擬似スタブ、即座に完了)

    broker = Broker(f"sonar_radar_zenoh_bridge_smoketest_{args.origin}", args.origin)
    broker.open(args.config)

    app = SonarRadarApp(
        broker=broker,
        calibration_participants=participants,
        is_leader=args.leader,
        radar_base_calibrate=radar_base_calibrate,
        radar_base_is_calibrated=radar_base_is_calibrated,
        calibration_timeout_sec=args.calibration_timeout,
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
            app.run()

            if app.state in reached_states:
                break
            time.sleep(_TICK_INTERVAL_SEC)
        else:
            print("[smoke-test] タイムアウト: 状態遷移が完了しなかった", file=sys.stderr)
            return 1
    finally:
        broker.close()
        if radar_base_close is not None:
            radar_base_close()

    if app.state is State.WAIT_FOR_START_PRESS:
        print("[smoke-test] OK: WAIT_FOR_START_PRESS に到達しました")
        return 0
    else:
        print(f"[smoke-test] NG: 最終状態 {app.state.value}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
