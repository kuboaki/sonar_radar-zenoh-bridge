"""device_types — libspikehatのポートデバイスタイプ定数。

sonar_radar/raspi/libspikehat/python/spikehat.pyと同じ値。実機用spikehat
モジュールはモジュールレベルでctypes.CDLL()により実機専用の共有ライブラリ
(libspikehat.so)をロードするため、SIM(Hakoniwa plant)実行環境でこの
モジュールをimportするとロードに失敗しうる。sonar_radar::unit層の各クラス
(radar_base/marker_detector/scanner/starter)はport_config()の第2引数として
デバイスタイプの整数値だけを必要とするため、spikehatモジュール本体には
依存せずこの値だけをここに複製して持つ(クラス図の意図通り、unit層を
実機/SIMで共有するための切り出し)。
"""

from __future__ import annotations

DEVICE_NONE = 0
DEVICE_MOTOR_M = 1
DEVICE_MOTOR_L = 2
DEVICE_COLOR = 3
DEVICE_DISTANCE = 4
DEVICE_FORCE = 5
