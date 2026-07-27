"""real_starter — 実機libspikehatのstarter(force sensor)を使う実装。

sonar_radar-zenoh-bridge は sonar_radar(アプリ本体)を import しないという
設計方針だが、libspikehat はハードウェア抽象化ライブラリであり
sonar_radar のドメインロジックとは独立しているため、これだけは直接使う。
sonar_radar リポジトリの raspi/libspikehat 配下にPythonバインディングが
あるため、そこへのパスを解決して import する。

環境変数 SONAR_RADAR_ROOT で sonar_radar リポジトリのルートを指定できる
(未指定時は ../../sonar_radar を既定値として探す。旧 driver/sonar_radar_zenoh.py
と同じ規約)。実機(Raspberry Pi)でのみ動作する。

sonar_radar/raspi/run.sh と同様、Build HAT のファームウェアを別プロセスで
ロードしてから(`from buildhat import Motor; Motor('A')`)、spikehat側で
シリアルポートを開く。同一プロセス内で先にbuildhatパッケージがシリアル
ポートを掴むと、spikehat(ctypes直叩き)側の後続オープンと衝突するため、
run.shにならい別プロセスとして実行する。

Build HATには「準備完了か」を問い合わせるソフトウェアAPIが無く、実機の
LED(赤→消灯、緑点灯)を目視するしかない。自動テストで人手を介さずに
待てるよう、コンストラクタ内で実際にforce_is_pressed()が例外を出さずに
読めるようになるまでポーリングして待つ(is_pushed()が返すようになって
初めて「準備完了」とみなす、というソフトウェアだけで完結する代替手段)。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time


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
    print("[real_starter] Build HATファームウェアをロード中...")
    subprocess.run(
        [sys.executable, "-c", "from buildhat import Motor; Motor('A')"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


class RealStarter:
    """実機のstarter(フォースセンサー)を読む。sonar_radar::unit::starterに相当。"""

    def __init__(
        self,
        port: int = 1,
        ready_timeout_sec: float = 15.0,
        ready_poll_interval_sec: float = 0.2,
    ) -> None:
        _load_buildhat_firmware()

        lib_dir = _resolve_libspikehat_python_dir()
        if lib_dir not in sys.path:
            sys.path.insert(0, lib_dir)
        import spikehat  # noqa: E402  (パス解決後にimportする必要があるため)

        self._port = port
        self._hat = spikehat.SpikeHat()
        self._hat.port_config(self._port, spikehat.DEVICE_FORCE)
        self._wait_until_ready(ready_timeout_sec, ready_poll_interval_sec)
        print(f"[real_starter] 実機のstarter(force sensor, port={self._port})を初期化しました")

    def _wait_until_ready(self, timeout_sec: float, poll_interval_sec: float) -> None:
        """force_is_pressed()が例外を出さずに読めるようになるまで待つ。

        これがBuild HATのLED(赤→緑)の目視確認に相当する、ソフトウェアだけで
        完結する準備完了確認。自動テストでも人手なしで安全に待てる。
        """
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            try:
                self._hat.force_is_pressed(self._port)
                return
            except RuntimeError:
                time.sleep(poll_interval_sec)
        raise RuntimeError(
            f"{timeout_sec}秒待ってもforce sensor(port={self._port})の準備ができませんでした。"
            "Build HATの接続・電源を確認してください。"
        )

    def is_pushed(self) -> bool:
        try:
            return bool(self._hat.force_is_pressed(self._port))
        except RuntimeError:
            # _wait_until_ready()で準備完了は確認済みだが、念のため
            # 防御的に残す(一時的な通信不調等)。押されていないものとして扱う。
            return False

    def close(self) -> None:
        self._hat.close()
