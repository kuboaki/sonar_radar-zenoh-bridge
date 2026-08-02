#!/usr/bin/env python3
"""run_real.py — 実機での動作確認スクリプト。

旧 run_calibration_smoke_test.py / run_start_smoke_test.py を統合したもの。
run_start_smoke_test.py がキャリブレーション完了後にstart協調まで進む
上位互換だったため、2本に分ける理由が無かった(片方への機能追加を
もう片方に反映し忘れる事故が実際に起きたため統合した)。

INIT → CALIBRATING(ローカルのみ、マシン間協調なし) →
WAIT_FOR_START_PRESS → (leaderのみ: WAIT_FOR_START_RELEASE →
WAIT_FOR_SCAN_START →) SCANNING を、実際のZenoh経由のpublish/受信で
確認する。followerはstarterの操作なしで、radar/starter/startを
受信するだけでSCANNINGへ直接遷移する(leader/followerの非対称設計)。

radar_base/starterは既定ではスタブ(即完了/擬似スイッチ)。
--real-radar-base / --real-starter で実機libspikehatに接続する。
"""

from __future__ import annotations

import argparse
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_CONFIG = os.path.join(_HERE, "..", "config", "mac", "endpoint_zenoh.json")

from app_runner import run_app  # noqa: E402
from hardware import RealHardware  # noqa: E402

_TICK_INTERVAL_SEC = 0.05
_OVERALL_TIMEOUT_SEC = 30.0
_DUMMY_DISTANCE_MM = 500


class _FakeStarter:
    """starterボタンの仮想スイッチ。leader側で--real-starter未指定時に使う。

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


def main() -> int:
    parser = argparse.ArgumentParser(description="実機での動作確認スクリプト")
    parser.add_argument("--config", default=_DEFAULT_CONFIG, help="endpoint_zenoh.json のパス")
    parser.add_argument("--origin", type=int, default=1, help="自分のorigin識別子")
    parser.add_argument("--leader", action="store_true", help="is_leader=True にする")
    parser.add_argument(
        "--real-radar-base", action="store_true",
        help="radar_baseを擬似スタブ(即完了)ではなく実機のモーター(libspikehat)で動かす",
    )
    parser.add_argument(
        "--real-starter", action="store_true",
        help="starterを擬似スイッチではなく実機のフォースセンサー(libspikehat)で読む",
    )
    parser.add_argument(
        "--press-after", type=float, default=1.0,
        help="leader側: 何秒後にstarterを押したことにするか(--real-starter未指定時のみ)",
    )
    parser.add_argument("--timeout", type=float, default=_OVERALL_TIMEOUT_SEC, help="全体のタイムアウト秒数")
    parser.add_argument(
        "--calibration-timeout", type=float, default=20.0,
        help="CALIBRATING(ローカルなハードウェアキャリブレーション)のタイムアウト秒数"
        "(既定20秒)。物理的にモーターが固着している等、ローカルなハードウェア障害を"
        "検出するためのもので、マシン間の協調待ちではない(ハードウェア初期化の時間"
        "そのものは含まない。broker.open()はhardware_initialize()より前にINITの"
        "entryで行われるため、初期化中もstart/stop/detected等の受信は取りこぼさない)",
    )
    parser.add_argument(
        "--scanning-timeout", type=float, default=8.0,
        help="SCANNINGのタイムアウト秒数(既定8秒)。ドームが旋回しすぎてセンサー"
        "ケーブルを巻き込む前に止めるための早期カットオフ(実機実測+ブリッジ"
        "経由のオーバーヘッド込み、docs/zenoh_state_machine_design.md参照)。"
        "ケーブル巻き込みリスクは実機のみの制約のため、シム側より小さめの既定値",
    )
    parser.add_argument(
        "--publish-confirm-timeout", type=float, default=2.0,
        help="WAIT_FOR_SCAN_START/MARKER_DETECTED/WAIT_FOR_STOP_RELEASE共通の"
        "タイムアウト秒数(既定2秒)。自分のpublishがループバックしてくるのを待つ",
    )
    args = parser.parse_args()

    # ハードウェア初期化(特にBuild HATのファームウェアロード、数十秒かかる
    # ことがある)は、SonarRadarAppのINITのentry(broker.open()の後)で
    # hardware_initialize()として呼ばれる。RealHardwareがこの遅延束縛を
    # 内部で扱う(hardware.py参照)。
    hardware = RealHardware(use_radar_base=args.real_radar_base, use_starter=args.real_starter)

    if args.real_starter:
        starter_is_pushed = hardware.starter_is_pushed
    elif args.leader:
        fake_starter = _FakeStarter(press_after_sec=args.press_after, hold_sec=0.5)
        starter_is_pushed = fake_starter.is_pushed
    else:
        starter_is_pushed = None

    try:
        return run_app(
            prefix="real",
            config_path=args.config,
            origin=args.origin,
            is_leader=args.leader,
            sleep=time.sleep,
            tick_interval_sec=_TICK_INTERVAL_SEC,
            overall_timeout_sec=args.timeout,
            calibration_timeout_sec=args.calibration_timeout,
            scanning_timeout_sec=args.scanning_timeout,
            publish_confirm_timeout_sec=args.publish_confirm_timeout,
            hardware_initialize=hardware.initialize,
            starter_is_pushed=starter_is_pushed,
            marker_detector_is_detected=hardware.marker_detector_is_detected,
            scanner_get_distance=lambda: _DUMMY_DISTANCE_MM,
            radar_base_calibrate=hardware.radar_base_calibrate,
            radar_base_is_calibrated=hardware.radar_base_is_calibrated,
            radar_base_run=hardware.radar_base_run,
            radar_base_stop=hardware.radar_base_stop,
            radar_base_invert_direction=hardware.radar_base_invert_direction,
        )
    finally:
        hardware.close()


if __name__ == "__main__":
    sys.exit(main())
