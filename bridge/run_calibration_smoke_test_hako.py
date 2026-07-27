#!/usr/bin/env python3
"""run_calibration_smoke_test_hako.py — MuJoCo(Hakoniwa plant)経由でキャリブレーションを確認する。

run_calibration_smoke_test.py の --real-radar-base 版が実機libspikehatを
直結するのに対し、こちらはHakoniwa plant(sonar_radar_hako.py、別プロセス、
無改造)にHakoniwa PDU(hakopy、共有メモリ)経由で接続し、実際にMuJoCo上の
モーターを動かしてキャリブレーションを行う。

SonarRadarApp / Broker(hakoniwa_pdu_endpoint + zenoh、実機とのメッセージ
交換用)は一切変更しない。radar_base_calibrate/radar_base_is_calibratedの
中身だけが HakoRadarBase(hako_radar_base.py)に差し替わる。

【前提】
1. 事前に `source bridge/env.sh` して hakoniwa_pdu_endpoint 用の環境変数
   (PYTHONPATH, HAKO_PDU_ENDPOINT_*)を設定しておくこと。
2. zenohd が起動していること(--real-radar-baseと同じ)。
3. Hakoniwa plant を別ターミナルで起動しておくこと:
     cd ~/Projects/hakoniwa-mujoco-robots
     MJPYTHON="$(pwd)/.venv/bin/mjpython" \\
       bash run-hakopy.bash ~/Projects/sonar_radar/sim/sonar_radar_hako.py --viewer
4. 本スクリプト自体も run-hakopy.bash 経由で実行すること(hakopy/Python 3.14
   が必要なため):
     cd ~/Projects/hakoniwa-mujoco-robots
     bash run-hakopy.bash <このファイルの絶対パス> [引数...]
5. 実行後、別ターミナルで `hako-cmd start` を叩いてシミュレーションを開始する。

controllerのtickループはhako_hat.sleep()(内部でhakopy.usleep())で駆動する
必要があるため、--real-radar-base版の time.sleep() ベースのループとは
tick駆動の方法が異なる(このスクリプト独自のmain_loop)。
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
# (古い・cffiベースの別ビルド)をPYTHONPATHの先頭近くに追加してしまうため、
# bridge/env.sh で設定される ~/.local 側(ctypes版、Zenoh対応)より先に
# 見つかってimportエラーになる。ここで明示的に先頭へ挿入して優先させる。
_HAKO_PDU_ENDPOINT_DIR = os.environ.get(
    "HAKO_PDU_ENDPOINT_PYTHON_DIR",
    os.path.expanduser("~/.local/lib/hakoniwa-pdu-endpoint/python"),
)
for _p in (_HAKO_PDU_ENDPOINT_DIR, _SONAR_RADAR_SIM_DIR, _HERE):
    if _p in sys.path:
        sys.path.remove(_p)
    sys.path.insert(0, _p)

import hakopy  # noqa: E402  (run-hakopy.bash がPYTHONPATHを設定済みの前提)
from libspikehat_hako import HakoSpikeHat  # noqa: E402

from broker import Broker  # noqa: E402
from console_report import console_report  # noqa: E402
from hako_radar_base import HakoRadarBase  # noqa: E402
from sonar_radar_app import SonarRadarApp, State  # noqa: E402
from state_reporter import with_state_change_reporting  # noqa: E402

ASSET_NAME = "SonarRadarZenohBridgeController"
ROBOT_NAME = "SonarRadarAsset"  # plant(sonar_radar_hako.py)側と一致させる

_PDU_FILENAME = "sonar-radar-pdudef-compact.json"
PDU_DEF_PATH = os.environ.get("SONAR_RADAR_PDU_DEF", "")
if not PDU_DEF_PATH or not os.path.exists(PDU_DEF_PATH):
    PDU_DEF_PATH = os.path.join(os.getcwd(), "config", _PDU_FILENAME)

STEP_USEC = 1000
_TICK_INTERVAL_SEC = 0.05
_OVERALL_TIMEOUT_SEC = 30.0


def _parse_participants(text: str) -> set:
    return {int(v) for v in text.split(",") if v.strip()}


def _run_calibration(args, hako_hat: HakoSpikeHat) -> int:
    participants = (
        _parse_participants(args.participants) if args.participants else {args.origin}
    )

    broker = Broker(f"sonar_radar_zenoh_bridge_hako_smoketest_{args.origin}", args.origin)
    broker.open(args.config)

    radar_base = HakoRadarBase(hako_hat)

    app = SonarRadarApp(
        broker=broker,
        calibration_participants=participants,
        is_leader=args.leader,
        radar_base_calibrate=radar_base.calibrate,
        radar_base_is_calibrated=radar_base.is_calibrated,
        calibration_timeout_sec=args.calibration_timeout,
    )

    def _report(state: State) -> None:
        console_report(state.value, prefix="hako-smoke-test")
        broker.publish_state(state.value)

    with_state_change_reporting(app, _report)

    reached_states = {State.WAIT_FOR_START_PRESS, State.TERMINATED}

    print(
        f"[hako-smoke-test] origin={args.origin} participants={sorted(participants)} "
        f"leader={args.leader} config={args.config}",
        file=sys.stderr,
    )

    elapsed = 0.0
    try:
        while elapsed < args.timeout:
            app.run()
            if app.state in reached_states:
                break
            hako_hat.sleep(_TICK_INTERVAL_SEC)  # シミュレーション時刻を進める
            elapsed += _TICK_INTERVAL_SEC
        else:
            print("[hako-smoke-test] タイムアウト: 状態遷移が完了しなかった", file=sys.stderr)
            return 1
    finally:
        broker.close()

    if app.state is State.WAIT_FOR_START_PRESS:
        print("[hako-smoke-test] OK: WAIT_FOR_START_PRESS に到達しました", file=sys.stderr)
        return 0
    else:
        print(f"[hako-smoke-test] NG: 最終状態 {app.state.value}", file=sys.stderr)
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Hakoniwa plant経由のキャリブレーション動作確認")
    parser.add_argument("--config", default=_DEFAULT_CONFIG, help="endpoint_zenoh.json のパス")
    parser.add_argument("--origin", type=int, default=1, help="自分のorigin識別子")
    parser.add_argument("--participants", default=None, help="calibration_participantsのカンマ区切り")
    parser.add_argument("--leader", action="store_true", help="is_leader=True にする")
    parser.add_argument("--timeout", type=float, default=_OVERALL_TIMEOUT_SEC, help="全体のタイムアウト秒数")
    parser.add_argument("--calibration-timeout", type=float, default=5.0, help="CALIBRATING系のタイムアウト秒数")
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
        result["code"] = _run_calibration(args, hako_hat)
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

    print(f"[hako-smoke-test] '{ASSET_NAME}' 登録完了。hako-cmd start を待機中...", file=sys.stderr)
    hakopy.start()
    sys.exit(result["code"])


if __name__ == "__main__":
    main()
