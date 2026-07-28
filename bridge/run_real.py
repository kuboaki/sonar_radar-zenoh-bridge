#!/usr/bin/env python3
"""run_real.py — 実機での動作確認スクリプト。

旧 run_calibration_smoke_test.py / run_start_smoke_test.py を統合したもの。
run_start_smoke_test.py がキャリブレーション完了後にstart協調まで進む
上位互換だったため、2本に分ける理由が無かった(片方への機能追加を
もう片方に反映し忘れる事故が実際に起きたため統合した)。

INIT → WAIT_FOR_CALIBRATE → CALIBRATING → WAIT_FOR_CALIBRATED →
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


def _parse_participants(text: str) -> set:
    return {int(v) for v in text.split(",") if v.strip()}


def main() -> int:
    parser = argparse.ArgumentParser(description="実機での動作確認スクリプト")
    parser.add_argument("--config", default=_DEFAULT_CONFIG, help="endpoint_zenoh.json のパス")
    parser.add_argument("--origin", type=int, default=1, help="自分のorigin識別子")
    parser.add_argument(
        "--participants", default=None,
        help="calibration_participantsのカンマ区切り(例: 1,2)。省略時は自分のoriginのみ",
    )
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
        "--calibration-timeout", type=float, default=5.0,
        help="CALIBRATING系のタイムアウト秒数(既定5秒)。ハードウェア初期化が完了し"
        "動作可能になってから、相手のcalibratedが揃うのを待つ時間(ハードウェア初期化の"
        "時間そのものを吸収するためのものではない。初期化はbroker.open()より前に済ませ、"
        "このタイマーが動き出す前に完了させること)",
    )
    args = parser.parse_args()

    participants = _parse_participants(args.participants) if args.participants else {args.origin}

    # ハードウェア初期化(特にBuild HATのファームウェアロード)は数十秒かかる
    # ことがあるため、tickループが動き出す前(broker.open()より前)に済ませておく。
    closers = []

    # RealRadarBaseとRealStarterはBuild HATへの同じシリアル接続(hat)を
    # 共有する必要がある(複数の同時オープンをサポートしないため)。
    real_hat = None
    if args.real_radar_base or args.real_starter:
        from real_hat import create_real_hat

        real_hat = create_real_hat()
        closers.append(real_hat.close)

    radar_base_calibrate = None
    radar_base_is_calibrated = lambda: True  # noqa: E731 (既定スタブ、即完了)
    if args.real_radar_base:
        from real_radar_base import RealRadarBase

        radar_base = RealRadarBase(real_hat)
        radar_base_calibrate = radar_base.calibrate
        radar_base_is_calibrated = radar_base.is_calibrated

    starter_is_pushed = None
    if args.real_starter:
        from real_starter import RealStarter

        real_starter = RealStarter(real_hat)
        starter_is_pushed = real_starter.is_pushed
    elif args.leader:
        fake_starter = _FakeStarter(press_after_sec=args.press_after, hold_sec=0.5)
        starter_is_pushed = fake_starter.is_pushed

    try:
        return run_app(
            prefix="real",
            config_path=args.config,
            origin=args.origin,
            participants=participants,
            is_leader=args.leader,
            sleep=time.sleep,
            tick_interval_sec=_TICK_INTERVAL_SEC,
            overall_timeout_sec=args.timeout,
            calibration_timeout_sec=args.calibration_timeout,
            starter_is_pushed=starter_is_pushed,
            scanner_get_distance=lambda: _DUMMY_DISTANCE_MM,
            radar_base_calibrate=radar_base_calibrate,
            radar_base_is_calibrated=radar_base_is_calibrated,
        )
    finally:
        for close in closers:
            close()


if __name__ == "__main__":
    sys.exit(main())
