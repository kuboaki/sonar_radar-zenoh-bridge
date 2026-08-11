"""real_hat — 実機libspikehatのSpikeHatを構築する共通ヘルパー。

radar_base.RadarBase と starter.Starter(実機/SIM共通のunitクラス、
2026-08-11にRealRadarBase/RealStarter等から統合)は、どちらも同じ
Build HATに対する単一のシリアル接続(spikehat.SpikeHat())を共有する
必要がある(Build HATは複数の同時オープンをサポートしないため)。

以前は両クラスが独立にspikehat.SpikeHat()を構築しており、
run_calibration_smoke_test.py(--real-radar-base)とrun_start_smoke_test.py
(--real-starter)が別プロセスとしてしか使われていなかった間は問題に
ならなかったが、run_real.pyへ統合し両方を同一プロセスで使ったところ、
2つ目のSpikeHat()構築が「Build HAT をオープンできません」で失敗する
ことが判明した。construction自体をここに1本化する。
"""

from __future__ import annotations

import os
import subprocess
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


def _load_buildhat_firmware() -> None:
    """Build HAT のファームウェアをロードする(sonar_radar/raspi/run.shと同じ手順)。

    別プロセスで実行することで、buildhatパッケージがシリアルポートを
    掴んだままにせず、spikehat側のオープンに影響しないようにする。
    """
    print("[real_hat] Build HATファームウェアをロード中...")
    subprocess.run(
        [sys.executable, "-c", "from buildhat import Motor; Motor('A')"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def create_real_hat():
    """spikehat.SpikeHat()を構築して返す。radar_base.RadarBase/starter.Starterで共有する。"""
    _load_buildhat_firmware()
    lib_dir = _resolve_libspikehat_python_dir()
    if lib_dir not in sys.path:
        sys.path.insert(0, lib_dir)
    import spikehat  # noqa: E402  (パス解決後にimportする必要があるため)

    return spikehat.SpikeHat()
