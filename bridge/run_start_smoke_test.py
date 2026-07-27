#!/usr/bin/env python3
"""run_start_smoke_test.py — 第2マイルストーンの動作確認スクリプト。

第1マイルストーン(キャリブレーション)に続けて、
WAIT_FOR_START_PRESS → WAIT_FOR_START_RELEASE → WAIT_FOR_SCAN_START →
SCANNING を、実際のZenoh経由のpublish/受信で確認する。

--leader を指定した側だけが、starterボタン押下をローカルに検知した
ものとして振る舞う(仮想スイッチ、または --real-starter 指定時は実機の
フォースセンサー)。followerは受信のみで追従する。

marker_detector/radar_base/scannerの実ハードウェアはまだこの層に接続
されていないため、scannerは固定値を返すスタブで代替している。starterは
既定ではタイマー駆動の擬似スイッチ(_FakeStarter)だが、--real-starter を
指定すると実機(Raspberry Pi)のlibspikehatフォースセンサーを直接読む
(real_starter.RealStarter)。
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

_OVERALL_TIMEOUT_SEC = 20.0
_TICK_INTERVAL_SEC = 0.05
_DUMMY_DISTANCE_MM = 500


class _FakeStarter:
    """starterボタンの仮想スイッチ。leader側のテストで使う。

    一定時間後に「押された」を模擬し、さらに一定時間後に「離された」を
    模擬する(press_after_sec <= 経過時間 < press_after_sec + hold_sec の間だけ true)。
    """

    def __init__(self, press_after_sec: float, hold_sec: float) -> None:
        self._t0 = time.monotonic()
        self._press_after = press_after_sec
        self._hold = hold_sec

    def is_pushed(self) -> bool:
        elapsed = time.monotonic() - self._t0
        return self._press_after <= elapsed < self._press_after + self._hold


def _parse_participants(text: str) -> set:
    return {int(v) for v in text.split(",") if v.strip()}


def main() -> int:
    parser = argparse.ArgumentParser(description="start協調(押下〜SCANNING到達)の動作確認スクリプト")
    parser.add_argument("--config", default=_DEFAULT_CONFIG, help="endpoint_zenoh.json のパス")
    parser.add_argument("--origin", type=int, default=1, help="自分のorigin識別子")
    parser.add_argument(
        "--participants",
        default=None,
        help="calibration_participantsのカンマ区切り(例: 1,2)。省略時は自分のoriginのみ",
    )
    parser.add_argument("--leader", action="store_true", help="is_leader=True にする")
    parser.add_argument(
        "--press-after", type=float, default=1.0, help="leader側: 何秒後にstarterを押したことにするか(--real-starter未指定時のみ)"
    )
    parser.add_argument(
        "--real-starter",
        action="store_true",
        help="starterを擬似スイッチではなく実機のフォースセンサー(libspikehat)で読む",
    )
    parser.add_argument("--timeout", type=float, default=_OVERALL_TIMEOUT_SEC, help="全体のタイムアウト秒数")
    parser.add_argument(
        "--calibration-timeout",
        type=float,
        default=5.0,
        help="WAIT_CALIBRATEDのタイムアウト秒数(既定5秒)。ハードウェア初期化が完了し"
        "動作可能になってから、相手のcalibratedが揃うのを待つ時間(ハードウェア初期化の"
        "時間そのものを吸収するためのものではない。初期化はbroker.open()より前に済ませ、"
        "このタイマーが動き出す前に完了させること)",
    )
    args = parser.parse_args()

    participants = _parse_participants(args.participants) if args.participants else {args.origin}

    # ハードウェア初期化(特にBuild HATのファームウェアロード)は数十秒かかる
    # ことがあるため、WAIT_CALIBRATEDのタイマーが動き出す前(broker.open()より前)
    # に済ませておく。相手側は、この初期化が終わったことを示す
    # "初期化しました"のログを見てから自分のスクリプトを起動すること。
    starter_close = None
    if args.real_starter:
        from real_starter import RealStarter

        real_starter = RealStarter()
        starter_is_pushed = real_starter.is_pushed
        starter_close = real_starter.close
    else:
        fake_starter = _FakeStarter(press_after_sec=args.press_after, hold_sec=0.5)
        starter_is_pushed = fake_starter.is_pushed

    broker = Broker(f"sonar_radar_zenoh_bridge_start_smoketest_{args.origin}", args.origin)
    broker.open(args.config)

    app = SonarRadarApp(
        broker=broker,
        calibration_participants=participants,
        is_leader=args.leader,
        starter_is_pushed=starter_is_pushed,
        scanner_get_distance=lambda: _DUMMY_DISTANCE_MM,
        calibration_timeout_sec=args.calibration_timeout,
        # 実機のradar_baseがまだ未接続のため、キャリブレーションは即座に
        # 完了したことにするスタブ(次のマイルストーンで実接続に置き換える)。
        radar_base_is_calibrated=lambda: True,
    )

    def _report(state: State) -> None:
        console_report(state.value, prefix="start-smoke-test")
        broker.publish_state(state.value)

    with_state_change_reporting(app, _report)

    deadline = time.monotonic() + args.timeout
    reached_states = {State.SCANNING, State.TERMINATED}

    print(
        f"[start-smoke-test] origin={args.origin} participants={sorted(participants)} "
        f"leader={args.leader} config={args.config}"
    )

    try:
        while time.monotonic() < deadline:
            app.run()

            if app.state in reached_states:
                break
            time.sleep(_TICK_INTERVAL_SEC)
        else:
            print("[start-smoke-test] タイムアウト: 状態遷移が完了しなかった", file=sys.stderr)
            return 1
    finally:
        broker.close()
        if starter_close is not None:
            starter_close()

    if app.state is State.SCANNING:
        print("[start-smoke-test] OK: SCANNING に到達しました")
        return 0
    else:
        print(f"[start-smoke-test] NG: 最終状態 {app.state.value}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
