"""real_marker_detector — 実機libspikehatのmarker_detector(色センサー)を使う実装。

元々はsonar_radar/raspi/sonar_radar.py の _tick_scanning() 内の色判定
(is_red()/is_blue())をそのまま移植していたが、赤は実機実測(2026-08-11)で
チャタリング・誤検出が確認されたため緑に変更した(このファイルのみ先行
対応、sonar_radar.py本体側の追従は別途)。

is_detected() は「立ち上がりエッジ」(前回tickではマーカー上になかったが
今回tickでマーカー上にある)でのみ True を返す。マーカーに乗ったまま
複数tick滞在しても2回目以降はFalseになる(sonar_radar.pyの
self._on_marker と同じロジック)。これにより、SonarRadarAppが
SCANNING→WAIT_FOR_INVERT→SCANNINGと1tickで往復しても、同じマーカー上に
まだ乗っている間に連続で誤検出することを防ぐ。
"""

from __future__ import annotations

# 実機実測(2026-08-11)に基づくしきい値。赤は色相0/360度の境界に近く、
# センサーノイズでhueが339〜342付近を行き来しチャタリング(短時間の連続
# 反転)が起きたため緑に変更した。加えて赤のしきい値は彩度・明度の条件が
# 緩く、機体周辺の茶色パーツ(hue=348〜353、赤の判定条件を満たしてしまう)
# を誤検出するリスクがあったことも実測で確認済み。
# 緑の実測値はhue158〜170で安定。周辺の既知の色(水色hue198〜204、
# 紫hue234〜240、青hue210〜270)から離れているため誤検出リスクは低い。
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


class RealMarkerDetector:
    """実機のmarker_detector(色センサー)を読む。sonar_radar::unit::marker_detectorに相当。

    hatはreal_hat.create_real_hat()で構築したspikehat.SpikeHat()を渡す
    (real_radar_base.RealRadarBase/real_starter.RealStarterと同じhatを共有する想定)。
    """

    def __init__(self, hat, port: int = 2) -> None:
        import spikehat  # real_hat.create_real_hat()でパス解決済みの前提

        self._port = port
        self._hat = hat
        self._hat.port_config(self._port, spikehat.DEVICE_COLOR)
        self._on_marker = False
        print(f"[real_marker_detector] 実機のmarker_detector(color sensor, port={self._port})を初期化しました")

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
