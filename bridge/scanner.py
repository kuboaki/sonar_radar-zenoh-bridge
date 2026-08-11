"""scanner — sonar_radar::unit::scanner に相当する、実機/SIM共通のユニット実装。

クラス図(sonar_radar_zenoh_bridgeのクラス図)の設計意図通り、実機とSIMで
別クラスに分けず単一のクラスを共有する。実機/SIMの違いは、コンストラクタで
渡すhatオブジェクト(実機はreal_hat.create_real_hat()が返すspikehat.SpikeHat、
SIMはlibspikehat_hako.HakoSpikeHat)の実装差だけに閉じ込める。両者とも
port_config(port, device_type)/distance_read(port)という同じインターフェース
を持つ(HakoSpikeHat.port_config()は何もしないno-op実装だが、シグネチャは
実機と同じなので無条件で呼び出せる)。

sonar_radar/raspi/sonar_radar.py の距離センサー配線(PORT_DISTANCE=3,
DEVICE_DISTANCE)・フィルタリング(filter_distance())と同じ設定を踏襲する。
"""

from __future__ import annotations

from device_types import DEVICE_DISTANCE

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


class Scanner:
    """距離センサーを読む。sonar_radar::unit::scannerに相当。実機/SIM共通実装。

    hatは実機ならreal_hat.create_real_hat()、SIM(Hakoniwa plant経由)なら
    libspikehat_hako.HakoSpikeHatのインスタンスを渡す。
    """

    def __init__(self, hat, port: int = _PORT_DISTANCE) -> None:
        self._port = port
        self._hat = hat
        self._hat.port_config(self._port, DEVICE_DISTANCE)
        print(f"[scanner] scanner(distance sensor, port={self._port})を初期化しました")

    def get_distance(self) -> int:
        """フィルタ済みの距離(mm)を返す。無効値/範囲外はsonar_radar本体と同様に扱う
        (SonarRadarAppは毎tick呼ぶ想定のため、有効値が無い間は0を返す)。"""
        try:
            raw = self._hat.distance_read(self._port)
        except RuntimeError:
            return 0
        filtered = _filter_distance(raw)
        return filtered if filtered is not None else 0
