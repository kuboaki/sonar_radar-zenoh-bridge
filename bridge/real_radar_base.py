"""real_radar_base — 実機libspikehatのradar_base(旋回モーター)を使う実装。

Build HATは複数の同時オープンをサポートしないため、spikehat.SpikeHat()の
構築はreal_hat.create_real_hat()に一本化し、real_starter.RealStarterと
共有する(呼び出し側がhatを1つだけ作って両方に渡す)。

キャリブレーション(機械的0位置への復帰 → SENSOR_HOME_OFFSET分の補正)は
sonar_radar/raspi/sonar_radar.py の CALIB_TO_ZERO/CALIB_TO_OFFSET(_drive_to)
と同じ2段階・同じ許容誤差(3度)・同じgear比/オフセット換算・同じ
「毎tick motor_pwm()で現在位置との誤差を補正し続ける」閉ループ制御で行う
(hako_radar_base.pyのis_calibrated()とも同じ設計)。

【2026-08-03の教訓】当初はspikehatのmotor_run_to_position()
(非同期・fire-and-forgetでBuildHAT側がランプ移動を行う一発コマンド)を
使っていたが、これは設計上の欠陥だった。BuildHATファームウェア側が
(こちらの3度基準より緩い)独自の基準で「到達した」と判断してPWMを止めて
しまうと、ソフトウェア側は指令をやり直さずmotor_get_position()を
ポーリングし続けるだけなので、位置が目標の数度手前で永久に止まって
しまう(is_calibrated()が真になるまで進めなくなる)不具合があった。
実機で発生したこの不具合を、標準版(sonar_radar.py)・SIM版
(hako_radar_base.py)と比較して切り分け、標準版・SIM版と同じ閉ループ制御
に統一することで解消した。

run()/stop()/invert_direction()による継続旋回は、sonar_radar.py の
_tick_scanning() と同じ設計(PWM一定駆動、マーカー検出時に符号反転のみ、
都度停止しない)。run()は冪等(既に回転中なら何もしない)。
"""

from __future__ import annotations

_TOLERANCE_DEG = 3  # sonar_radar.py の _drive_to と同じ許容誤差
_ALIGN_PWM_SCALE = 0.3  # sonar_radar.py の _drive_to と同じ換算
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
        self._align_pwm = (abs(align_speed) / 100.0) * _ALIGN_PWM_SCALE
        self._pwm = _SCAN_PWM
        self._running = False
        print(f"[real_radar_base] 実機のradar_base(motor, port={self._port})を初期化しました")

    def calibrate(self) -> None:
        """機械的0位置への移動を開始する(entry相当、1回だけ呼ぶ想定)。"""
        self._stage = "to_zero"

    def is_calibrated(self) -> bool:
        """毎tick呼ぶ想定。目標未到達ならトルクを与え、到達したら次の段階へ進める。"""
        if self._stage in (None, "done"):
            return self._stage == "done"

        target = 0 if self._stage == "to_zero" else self._offset_deg
        try:
            current = self._hat.motor_get_position(self._port)
        except RuntimeError:
            return False

        err = target - current
        if abs(err) < _TOLERANCE_DEG:
            self._hat.motor_stop(self._port)
            if self._stage == "to_zero":
                self._stage = "to_offset"
                return False
            self.zero_pos = current
            self._stage = "done"
            return True

        self._hat.motor_pwm(self._port, self._align_pwm if err > 0 else -self._align_pwm)
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
