"""real_scanner — 実機libspikehatの距離センサー(scanner)を使う実装。

sonar_radar/raspi/sonar_radar.py の距離センサー配線(PORT_DISTANCE=3,
DEVICE_DISTANCE)・フィルタリング(filter_distance())と同じ設定を踏襲する。

Build HATは複数の同時オープンをサポートしないため、hatはreal_hat.create_real_hat()
で構築したものをreal_radar_base.RealRadarBase/real_starter.RealStarterと共有する。
"""

from __future__ import annotations

_PORT_DISTANCE = 3
_DIST_MIN_MM = 50
_DIST_MAX_MM = 300
_DIST_INVALID = 2000
_DIST_OFFSET_MM = 25


def _filter_distance(mm: int) -> int | None:
    if mm == _DIST_INVALID:
        return None
    corrected = mm + _DIST_OFFSET_MM
    if corrected < _DIST_MIN_MM or corrected > _DIST_MAX_MM:
        return None
    return corrected


class RealScanner:
    """実機の距離センサーを読む。sonar_radar::unit::scannerに相当。

    hatはreal_hat.create_real_hat()で構築したspikehat.SpikeHat()を渡す
    (real_radar_base.RealRadarBase/real_starter.RealStarterと同じhatを共有する想定)。
    """

    def __init__(self, hat, port: int = _PORT_DISTANCE) -> None:
        self._port = port
        self._hat = hat
        import spikehat  # real_hat.create_real_hat()でパス解決済みの前提

        self._hat.port_config(self._port, spikehat.DEVICE_DISTANCE)
        print(f"[real_scanner] 実機のscanner(distance sensor, port={self._port})を初期化しました")

    def get_distance(self) -> int:
        """フィルタ済みの距離(mm)を返す。無効値/範囲外はsonar_radar本体と同様に扱う
        (SonarRadarAppは毎tick呼ぶ想定のため、有効値が無い間は0を返す)。"""
        try:
            raw = self._hat.distance_read(self._port)
        except RuntimeError:
            return 0
        filtered = _filter_distance(raw)
        return filtered if filtered is not None else 0
