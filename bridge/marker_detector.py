"""marker_detector — sonar_radar::unit::marker_detector に相当する、実機/SIM共通のユニット実装。

クラス図の設計意図通り、実機とSIMで別クラスに分けず単一のクラスを共有する。
実機/SIMの違いは、コンストラクタで渡すhatオブジェクト(実機はreal_hat.create_real_hat()
が返すspikehat.SpikeHat、SIMはlibspikehat_hako.HakoSpikeHat)の実装差だけに
閉じ込める(scanner.py/radar_base.pyと同じ設計、device_types.py参照)。

sonar_radar/raspi/sonar_radar.py の _tick_scanning() 内の色判定と同じ
しきい値を使う。元々は赤/青で判定していたが、実機実測(2026-08-11)で
赤のしきい値がセンサーノイズによりチャタリングし、さらに機体周辺の
茶色パーツを誤検出するリスクがあったため緑に変更した。緑の実測値は
hue158〜170で安定。周辺の既知の色(水色hue198〜204、紫hue234〜240、
青hue210〜270)から離れているため誤検出リスクは低い。

is_detected() は「立ち上がりエッジ」(前回tickではマーカー上になかったが
今回tickでマーカー上にある)でのみ True を返す。マーカーに乗ったまま
複数tick滞在しても2回目以降はFalseになる(sonar_radar.pyのself._on_marker
と同じロジック)。これにより、SonarRadarAppがSCANNING→WAIT_FOR_INVERT→
SCANNINGと1tickで往復しても、同じマーカー上にまだ乗っている間に連続で
誤検出することを防ぐ。
"""

from __future__ import annotations

from device_types import DEVICE_COLOR

_GREEN_HUE_LO = 145
_GREEN_HUE_HI = 185
_GREEN_SAT_MIN = 150
_GREEN_VAL_MIN = 50
_BLUE_HUE_LO = 210
_BLUE_HUE_HI = 270
_BLUE_SAT_MIN = 580
_BLUE_VAL_MIN = 100


def _is_green(hue: float, sat: float, val: float) -> bool:
    if sat < _GREEN_SAT_MIN or val < _GREEN_VAL_MIN:
        return False
    return _GREEN_HUE_LO <= hue <= _GREEN_HUE_HI


def _is_blue(hue: float, sat: float, val: float) -> bool:
    if sat < _BLUE_SAT_MIN or val < _BLUE_VAL_MIN:
        return False
    return _BLUE_HUE_LO <= hue <= _BLUE_HUE_HI


class MarkerDetector:
    """marker_detector(色センサー)を読む。sonar_radar::unit::marker_detectorに相当。実機/SIM共通実装。

    hatは実機ならreal_hat.create_real_hat()、SIM(Hakoniwa plant経由)なら
    libspikehat_hako.HakoSpikeHatのインスタンスを渡す。
    """

    def __init__(self, hat, port: int = 2) -> None:
        self._port = port
        self._hat = hat
        self._hat.port_config(self._port, DEVICE_COLOR)
        self._on_marker = False
        print(f"[marker_detector] marker_detector(color sensor, port={self._port})を初期化しました")

    def is_detected(self) -> bool:
        """毎tick呼ぶ想定。マーカー上に新たに乗った(立ち上がりエッジ)ときのみTrue。"""
        try:
            h, s, v = self._hat.color_read_hsv(self._port)
        except RuntimeError:
            return False
        marker = _is_green(h, s, v) or _is_blue(h, s, v)
        detected = marker and not self._on_marker
        self._on_marker = marker
        return detected
