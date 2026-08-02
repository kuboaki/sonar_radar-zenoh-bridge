#!/usr/bin/env python3
"""run_hako.py — MuJoCo(Hakoniwa plant)経由での動作確認スクリプト。

旧 run_calibration_smoke_test_hako.py / run_start_smoke_test_hako.py を
統合したもの(run_real.pyと同じ理由)。run_real.pyと同じ状態進行を、
hakopy controllerとして登録し、Hakoniwa plant(sonar_radar_hako.py、
別プロセス、無改造)経由のMuJoCoで確認する。

radar_baseは常にHakoRadarBase(Hakoniwa PDU経由でモーターを駆動)。
starterは既定ではスタブ(followerはstarter操作なしでstart受信のみで
SCANNINGへ進む設計のため、これが最も典型的な使い方)。--hako-starter を
指定するとplantのforce_sensor PDU(ビューアのSpaceキー操作も含む)を読む。

【前提】
1. 事前に `source bridge/env.sh` して hakoniwa_pdu_endpoint 用の環境変数
   (PYTHONPATH, HAKO_PDU_ENDPOINT_*)を設定しておくこと。
2. zenohd が起動していること。
3. Hakoniwa plant を別ターミナルで起動しておくこと:
     cd ~/Projects/hakoniwa-mujoco-robots
     MJPYTHON="$(pwd)/.venv/bin/mjpython" \\
       bash run-hakopy.bash ~/Projects/sonar_radar/sim/sonar_radar_hako.py --viewer
4. 本スクリプト自体も run-hakopy.bash 経由で実行すること(hakopy/Python 3.14
   が必要なため):
     cd ~/Projects/hakoniwa-mujoco-robots
     bash run-hakopy.bash <このファイルの絶対パス> [引数...]
5. 実行後、別ターミナルで `hako-cmd start` を叩いてシミュレーションを開始する。
"""

from __future__ import annotations

import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_CONFIG = os.path.join(_HERE, "..", "config", "mac", "endpoint_zenoh.json")
_SONAR_RADAR_SIM_DIR = os.environ.get(
    "SONAR_RADAR_SIM_DIR",
    os.path.join(_HERE, "..", "..", "sonar_radar", "sim"),
)

# run-hakopy.bashは /usr/local/hakoniwa/share/hakoniwa-pdu-endpoint/python
# (古い・cffiビルドのバックエンドが見つからない別ビルド)をPYTHONPATHの
# 先頭近くに追加してしまうため、bridge/env.sh で設定される ~/.local 側
# (Zenoh対応)より先に見つかってimportエラーになる。明示的に優先させる。
_HAKO_PDU_ENDPOINT_DIR = os.environ.get(
    "HAKO_PDU_ENDPOINT_PYTHON_DIR",
    os.path.expanduser("~/.local/lib/hakoniwa-pdu-endpoint/python"),
)
for _p in (_HAKO_PDU_ENDPOINT_DIR, _SONAR_RADAR_SIM_DIR, _HERE):
    if _p in sys.path:
        sys.path.remove(_p)
    sys.path.insert(0, _p)

import hakopy  # noqa: E402
from libspikehat_hako import HakoSpikeHat  # noqa: E402

from app_runner import run_app  # noqa: E402
from hardware import HakoHardware  # noqa: E402

ASSET_NAME = "SonarRadarZenohBridgeController"
ROBOT_NAME = "SonarRadarAsset"  # plant(sonar_radar_hako.py)側と一致させる

_PDU_FILENAME = "sonar-radar-pdudef-compact.json"
PDU_DEF_PATH = os.environ.get("SONAR_RADAR_PDU_DEF", "")
if not PDU_DEF_PATH or not os.path.exists(PDU_DEF_PATH):
    PDU_DEF_PATH = os.path.join(os.getcwd(), "config", _PDU_FILENAME)

STEP_USEC = 1000
_TICK_INTERVAL_SEC = 0.05
_OVERALL_TIMEOUT_SEC = 30.0
_DUMMY_DISTANCE_MM = 500


def main() -> None:
    parser = argparse.ArgumentParser(description="Hakoniwa plant経由の動作確認スクリプト")
    parser.add_argument("--config", default=_DEFAULT_CONFIG, help="endpoint_zenoh.json のパス")
    parser.add_argument("--origin", type=int, default=1, help="自分のorigin識別子")
    parser.add_argument("--leader", action="store_true", help="is_leader=True にする")
    parser.add_argument(
        "--hako-starter", action="store_true",
        help="starterをスタブではなくplantのforce_sensor PDU(ビューアのSpaceキー操作を含む)で読む",
    )
    parser.add_argument("--timeout", type=float, default=_OVERALL_TIMEOUT_SEC, help="全体のタイムアウト秒数")
    parser.add_argument(
        "--calibration-timeout", type=float, default=20.0,
        help="CALIBRATING(ローカルなハードウェアキャリブレーション)のタイムアウト秒数(既定20秒)",
    )
    parser.add_argument(
        "--scanning-timeout", type=float, default=12.0,
        help="SCANNINGのタイムアウト秒数(既定12秒)。ドームが旋回しすぎてセンサー"
        "ケーブルを巻き込む前に止める早期カットオフだが、シムには実在するケーブル"
        "が無いため、実機(既定8秒)より余裕を持たせて誤検出を避ける"
        "(docs/zenoh_state_machine_design.md参照)",
    )
    parser.add_argument(
        "--publish-confirm-timeout", type=float, default=2.0,
        help="WAIT_FOR_SCAN_START/MARKER_DETECTED/WAIT_FOR_STOP_RELEASE共通の"
        "タイムアウト秒数(既定2秒)。自分のpublishがループバックしてくるのを待つ",
    )
    args = parser.parse_args()

    if not os.path.exists(PDU_DEF_PATH):
        print(f"[ERROR] PDU def not found: {PDU_DEF_PATH}", file=sys.stderr)
        sys.exit(1)

    hako_hat = HakoSpikeHat(robot_name=ROBOT_NAME)
    result = {"code": 1}

    def on_initialize(_ctx):
        return 0

    def on_reset(_ctx):
        return 0

    def on_manual_timing_control(_ctx):
        hardware = HakoHardware(hako_hat, use_starter=args.hako_starter)

        result["code"] = run_app(
            prefix="hako",
            config_path=args.config,
            origin=args.origin,
            is_leader=args.leader,
            sleep=hako_hat.sleep,
            tick_interval_sec=_TICK_INTERVAL_SEC,
            overall_timeout_sec=args.timeout,
            calibration_timeout_sec=args.calibration_timeout,
            scanning_timeout_sec=args.scanning_timeout,
            publish_confirm_timeout_sec=args.publish_confirm_timeout,
            hardware_initialize=hardware.initialize,
            starter_is_pushed=hardware.starter_is_pushed,
            marker_detector_is_detected=hardware.marker_detector_is_detected,
            scanner_get_distance=lambda: _DUMMY_DISTANCE_MM,
            radar_base_calibrate=hardware.radar_base_calibrate,
            radar_base_is_calibrated=hardware.radar_base_is_calibrated,
            radar_base_run=hardware.radar_base_run,
            radar_base_stop=hardware.radar_base_stop,
            radar_base_invert_direction=hardware.radar_base_invert_direction,
        )
        return 0

    cb = {
        "on_initialize": on_initialize,
        "on_simulation_step": None,
        "on_manual_timing_control": on_manual_timing_control,
        "on_reset": on_reset,
    }

    ret = hakopy.asset_register(
        ASSET_NAME, PDU_DEF_PATH, cb, STEP_USEC, hakopy.HAKO_ASSET_MODEL_CONTROLLER
    )
    if not ret:
        print("[ERROR] hakopy.asset_register failed", file=sys.stderr)
        sys.exit(1)

    print(f"[hako] '{ASSET_NAME}' 登録完了。hako-cmd start を待機中...", file=sys.stderr)
    hakopy.start()
    sys.exit(result["code"])


if __name__ == "__main__":
    main()
