"""real_starter — 実機libspikehatのstarter(force sensor)を使う実装。

sonar_radar-zenoh-bridge は sonar_radar(アプリ本体)を import しないという
設計方針だが、libspikehat はハードウェア抽象化ライブラリであり
sonar_radar のドメインロジックとは独立しているため、これだけは直接使う。
sonar_radar リポジトリの raspi/libspikehat 配下にPythonバインディングが
あるため、そこへのパスを解決して import する。

環境変数 SONAR_RADAR_ROOT で sonar_radar リポジトリのルートを指定できる
(未指定時は ../../sonar_radar を既定値として探す。旧 driver/sonar_radar_zenoh.py
と同じ規約)。実機(Raspberry Pi)でのみ動作する。
"""

from __future__ import annotations

import os
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


class RealStarter:
    """実機のstarter(フォースセンサー)を読む。sonar_radar::unit::starterに相当。"""

    def __init__(self, port: int = 1) -> None:
        lib_dir = _resolve_libspikehat_python_dir()
        if lib_dir not in sys.path:
            sys.path.insert(0, lib_dir)
        import spikehat  # noqa: E402  (パス解決後にimportする必要があるため)

        self._port = port
        self._hat = spikehat.SpikeHat()
        self._hat.port_config(self._port, spikehat.DEVICE_FORCE)
        print(f"[real_starter] 実機のstarter(force sensor, port={self._port})を初期化しました")

    def is_pushed(self) -> bool:
        return bool(self._hat.force_is_pressed(self._port))

    def close(self) -> None:
        self._hat.close()
