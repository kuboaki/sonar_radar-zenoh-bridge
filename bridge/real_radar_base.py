"""real_radar_base — 実機libspikehatのradar_base(旋回モーター)を使う実装。

Build HATは複数の同時オープンをサポートしないため、spikehat.SpikeHat()の
構築はreal_hat.create_real_hat()に一本化し、real_starter.RealStarterと
共有する(呼び出し側がhatを1つだけ作って両方に渡す)。

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

run()/stop()/invert_direction()による継続旋回は、sonar_radar.py の
_tick_scanning() と同じ設計(PWM一定駆動、マーカー検出時に符号反転のみ、
都度停止しない)。run()は冪等(既に回転中なら何もしない)。
"""

from __future__ import annotations

_TOLERANCE_DEG = 3  # sonar_radar.py の _drive_to と同じ許容誤差
_SCAN_PWM = 0.1  # sonar_radar.py の SCAN_PWM と同じ値


class RealRadarBase:
    """実機のradar_base(旋回モーター)を使う。sonar_radar::unit::radar_baseに相当。

    hatはreal_hat.create_real_hat()で構築したspikehat.SpikeHat()を渡す
    (real_starter.RealStarterと同じhatを共有する想定)。
    """

    def __init__(
        self,
        hat,
        port: int = 0,
        align_speed: int = 10,
        gear_ratio: int = 3,
        sensor_home_offset_deg: int = 5,
    ) -> None:
        import spikehat  # real_hat.create_real_hat()でパス解決済みの前提

        self._port = port
        self._align_speed = align_speed
        # dome_to_motor(sensor_home_offset_deg) と同じ換算(sonar_radar.py参照)
        self._offset_deg = round(-sensor_home_offset_deg * gear_ratio)
        self._gear_ratio = gear_ratio
        self._hat = hat
        self._hat.port_config(self._port, spikehat.DEVICE_MOTOR_L)
        self._stage: str | None = None  # None→未開始, "to_zero", "to_offset", "done"
        self.zero_pos = 0
        self._pwm = _SCAN_PWM
        self._running = False
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

    def run(self) -> None:
        """継続旋回を開始する(冪等、既に回転中なら何もしない)。"""
        if self._running:
            return
        self._running = True
        self._hat.motor_pwm(self._port, self._pwm)

    def stop(self) -> None:
        """継続旋回を停止する。"""
        self._running = False
        self._hat.motor_stop(self._port)

    def invert_direction(self) -> None:
        """回転方向を反転する(PWM符号反転、止めずに切り替える)。"""
        self._pwm = -self._pwm
        self._hat.motor_pwm(self._port, self._pwm)

    def get_position(self) -> int:
        """現在のモーター角度(度、zero_pos基準の生値)を返す。"""
        try:
            current = self._hat.motor_get_position(self._port)
        except RuntimeError:
            return 0
        return round(current - self.zero_pos)

    def get_dome_angle(self) -> float:
        """現在のドーム角度(度)を返す。sonar_radar.pyのmotor_to_dome()と同じ換算(符号反転あり)。"""
        return -self.get_position() / self._gear_ratio
