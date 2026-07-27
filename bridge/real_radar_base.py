"""real_radar_base — 実機libspikehatのradar_base(旋回モーター)を使う実装。

real_starter.py と同じ設計方針: sonar_radar-zenoh-bridge は sonar_radar
(アプリ本体)を import しないが、ハードウェア抽象化ライブラリである
libspikehat だけは直接使う。ファームウェアロード・パス解決の手順も
real_starter.py と共通(重複コードだが、各ハードウェアラッパーが
自己完結する方を優先した)。

キャリブレーション(機械的0位置への復帰 → SENSOR_HOME_OFFSET分の補正)は
sonar_radar/raspi/sonar_radar.py の CALIB_TO_ZERO/CALIB_TO_OFFSET と
同じ2段階・同じ許容誤差(3度)・同じgear比/オフセット換算で行う。

sonar_radar.py 自身は毎tick motor_pwm()で微調整する実装だが(単一の
flatなtickループ設計のため)、こちらは spikehat の motor_run_to_position()
(非同期・fire-and-forgetでBuildHAT側がランプ移動を行う)を使い、
calibrate()を1回呼んだら、is_calibrated()を毎tickポーリングするだけで
段階を進める設計にした。SonarRadarApp.CALIBRATING の
「entryでcalibrate()を1回、以後is_calibrated()を毎tickポーリング」
という構造にちょうど合う。
"""

from __future__ import annotations

import os
import subprocess
import sys


def _resolve_libspikehat_python_dir() -> str:
    root = os.environ.get("SONAR_RADAR_ROOT")
    if not root:
        here = os.path.dirname(os.path.abspath(__file__))
        root = os.path.join(here, "..", "..", "sonar_radar")
    lib_dir = os.path.join(os.path.realpath(root), "raspi", "libspikehat", "python")
    if not os.path.isdir(lib_dir):
        raise RuntimeError(
            f"libspikehatのPythonバインディングが見つかりません: {lib_dir}\n"
            "SONAR_RADAR_ROOT環境変数でsonar_radarリポジトリのルートを指定してください。"
        )
    return lib_dir


def _load_buildhat_firmware() -> None:
    print("[real_radar_base] Build HATファームウェアをロード中...")
    subprocess.run(
        [sys.executable, "-c", "from buildhat import Motor; Motor('A')"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


_TOLERANCE_DEG = 3  # sonar_radar.py の _drive_to と同じ許容誤差


class RealRadarBase:
    """実機のradar_base(旋回モーター)を使う。sonar_radar::unit::radar_baseに相当。"""

    def __init__(
        self,
        port: int = 0,
        align_speed: int = 10,
        gear_ratio: int = 3,
        sensor_home_offset_deg: int = 5,
    ) -> None:
        _load_buildhat_firmware()

        lib_dir = _resolve_libspikehat_python_dir()
        if lib_dir not in sys.path:
            sys.path.insert(0, lib_dir)
        import spikehat  # noqa: E402  (パス解決後にimportする必要があるため)

        self._port = port
        self._align_speed = align_speed
        # dome_to_motor(sensor_home_offset_deg) と同じ換算(sonar_radar.py参照)
        self._offset_deg = round(-sensor_home_offset_deg * gear_ratio)
        self._hat = spikehat.SpikeHat()
        self._hat.port_config(self._port, spikehat.DEVICE_MOTOR_L)
        self._stage: str | None = None  # None→未開始, "to_zero", "to_offset", "done"
        self.zero_pos = 0
        print(f"[real_radar_base] 実機のradar_base(motor, port={self._port})を初期化しました")

    def calibrate(self) -> None:
        """機械的0位置への移動を開始する(entry相当、1回だけ呼ぶ想定)。"""
        self._stage = "to_zero"
        self._hat.motor_run_to_position(self._port, 0, self._align_speed)

    def is_calibrated(self) -> bool:
        """毎tick呼ぶ想定。段階が進んだら次の目標へ自動で進める。"""
        if self._stage in (None, "done"):
            return self._stage == "done"

        try:
            current = self._hat.motor_get_position(self._port)
        except RuntimeError:
            return False

        if self._stage == "to_zero":
            if abs(current - 0) < _TOLERANCE_DEG:
                self._stage = "to_offset"
                self._hat.motor_run_to_position(self._port, self._offset_deg, self._align_speed)
            return False

        # self._stage == "to_offset"
        if abs(current - self._offset_deg) < _TOLERANCE_DEG:
            self.zero_pos = current
            self._stage = "done"
            return True
        return False

    def invert_direction(self) -> None:
        raise NotImplementedError("次のマイルストーン(MARKER_DETECTED以降)で実装")

    def close(self) -> None:
        self._hat.close()
