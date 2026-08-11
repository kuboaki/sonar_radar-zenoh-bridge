"""hako_marker_detector — Hakoniwa PDU経由でMuJoCo plantのmarker_detector(色センサー)を読む実装。

real_marker_detector.RealMarkerDetector と同じロジック(sonar_radar.pyの
is_green()/is_blue()、立ち上がりエッジ検出)を、plant(sonar_radar_hako.py)の
color_sensor PDUチャンネル経由で行う。hako_radar_base.py/hako_starter.pyと
同じく、ポート設定はplant側(sonar_radar_hako.py)が既に行っているため
port_config()は呼ばない。
"""

from __future__ import annotations

# sonar_radar.py / real_marker_detector.py と同じしきい値。赤は実機実測
# (2026-08-11)でチャタリング・誤検出が確認され緑に変更した経緯は
# real_marker_detector.py参照。MuJoCoモデル側もbase_red_geomのrgbaを
# 緑色に変更済み(sonar_radar/mujoco_model/sonar_radar.xml)。
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


class HakoMarkerDetector:
    """Hakoniwa plant経由のmarker_detector(色センサー)。sonar_radar::unit::marker_detectorに相当。"""

    def __init__(self, hako_hat, port: int = 2) -> None:
        self._hat = hako_hat
        self._port = port
        self._on_marker = False

    def is_detected(self) -> bool:
        """毎tick呼ぶ想定。マーカー上に新たに乗った(立ち上がりエッジ)ときのみTrue。"""
        h, s, v = self._hat.color_read_hsv(self._port)
        marker = _is_green(h, s, v) or _is_blue(h, s, v)
        detected = marker and not self._on_marker
        self._on_marker = marker
        return detected
