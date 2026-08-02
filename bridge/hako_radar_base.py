"""hako_radar_base — Hakoniwa PDU経由でMuJoCo plantのradar_base(旋回モーター)を使う実装。

real_radar_base.py と同じ設計方針だが、実機libspikehatの代わりに
sonar_radar/sim/libspikehat_hako.py の HakoSpikeHat 経由で、別プロセスの
plant(sonar_radar_hako.py)とHakoniwa PDUでやり取りする。

HakoSpikeHat.motor_run_to_position()はブロッキング実装(内部でhat.sleep()を
繰り返し呼び、目標到達かタイムアウトまで戻らない)。そのまま使うと、
CALIBRATING中SonarRadarAppのtickループ(Zenohメッセージ処理)が止まって
しまうため、real_radar_base.py と同じ「calibrate()で開始、
is_calibrated()を毎tickポーリング」というノンブロッキング設計にする。
motor_pwm()/motor_get_position()を直接使い、sonar_radar.pyの_drive_to()
と同じtickベースの微調整ロジックをis_calibrated()内に持たせている。

hako_hat(HakoSpikeHat)はこのクラスが所有せず、呼び出し側から注入される。
これは、controllerのtickループ自体がhako_hat.sleep()(内部でhakopy.usleep()
を呼ぶ)で駆動される必要があり、その責務はこのクラスの外側(エントリポイント
スクリプト)にあるため。

run()/stop()/invert_direction()による継続旋回は、real_radar_base.pyと
同じくsonar_radar.pyの_tick_scanning()と同じ設計(PWM一定駆動、マーカー
検出時に符号反転のみ、都度停止しない)。calibrate()用のPWM(_pwm、align用)
とは別に、scan用のPWM(_scan_pwm)を持つ。
"""

from __future__ import annotations

_TOLERANCE_DEG = 3  # sonar_radar.py の _drive_to と同じ許容誤差
_ALIGN_PWM_SCALE = 0.3  # sonar_radar.py の _drive_to と同じ換算
_SCAN_PWM = 0.1  # sonar_radar.py の SCAN_PWM と同じ値


class HakoRadarBase:
    """Hakoniwa plant経由のradar_base(旋回モーター)。sonar_radar::unit::radar_baseに相当。"""

    def __init__(
        self,
        hako_hat,
        port: int = 0,
        align_speed: int = 10,
        gear_ratio: int = 3,
        sensor_home_offset_deg: int = 5,
    ) -> None:
        self._hat = hako_hat
        self._port = port
        self._pwm = (abs(align_speed) / 100.0) * _ALIGN_PWM_SCALE
        # dome_to_motor(sensor_home_offset_deg) と同じ換算(sonar_radar.py参照)
        self._offset_deg = round(-sensor_home_offset_deg * gear_ratio)
        self._stage: str | None = None  # None→未開始, "to_zero", "to_offset", "done"
        self.zero_pos = 0
        self._scan_pwm = _SCAN_PWM
        self._running = False

    def calibrate(self) -> None:
        """機械的0位置への移動を開始する(entry相当、1回だけ呼ぶ想定)。"""
        self._stage = "to_zero"

    def is_calibrated(self) -> bool:
        """毎tick呼ぶ想定。目標未到達ならトルクを与え、到達したら次の段階へ進める。"""
        if self._stage in (None, "done"):
            return self._stage == "done"

        target = 0 if self._stage == "to_zero" else self._offset_deg
        current = self._hat.motor_get_position(self._port)
        err = target - current
        if abs(err) < _TOLERANCE_DEG:
            self._hat.motor_stop(self._port)
            if self._stage == "to_zero":
                self._stage = "to_offset"
                return False
            self.zero_pos = current
            self._stage = "done"
            return True

        self._hat.motor_pwm(self._port, self._pwm if err > 0 else -self._pwm)
        return False

    def run(self) -> None:
        """継続旋回を開始する(冪等、既に回転中なら何もしない)。"""
        if self._running:
            return
        self._running = True
        self._hat.motor_pwm(self._port, self._scan_pwm)

    def stop(self) -> None:
        """継続旋回を停止する。"""
        self._running = False
        self._hat.motor_stop(self._port)

    def invert_direction(self) -> None:
        """回転方向を反転する(PWM符号反転、止めずに切り替える)。"""
        self._scan_pwm = -self._scan_pwm
        self._hat.motor_pwm(self._port, self._scan_pwm)
