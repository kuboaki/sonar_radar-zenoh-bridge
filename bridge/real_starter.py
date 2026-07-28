"""real_starter — 実機libspikehatのstarter(force sensor)を使う実装。

Build HATは複数の同時オープンをサポートしないため、spikehat.SpikeHat()の
構築はreal_hat.create_real_hat()に一本化し、real_radar_base.RealRadarBase
と共有する(呼び出し側がhatを1つだけ作って両方に渡す)。

Build HATには「準備完了か」を問い合わせるソフトウェアAPIが無く、実機の
LED(赤→消灯、緑点灯)を目視するしかない。自動テストで人手を介さずに
待てるよう、コンストラクタ内で実際にforce_is_pressed()が例外を出さずに
読めるようになるまでポーリングして待つ(is_pushed()が返すようになって
初めて「準備完了」とみなす、というソフトウェアだけで完結する代替手段)。
"""

from __future__ import annotations

import time


class RealStarter:
    """実機のstarter(フォースセンサー)を読む。sonar_radar::unit::starterに相当。

    hatはreal_hat.create_real_hat()で構築したspikehat.SpikeHat()を渡す
    (real_radar_base.RealRadarBaseと同じhatを共有する想定)。
    """

    def __init__(
        self,
        hat,
        port: int = 1,
        ready_timeout_sec: float = 15.0,
        ready_poll_interval_sec: float = 0.2,
    ) -> None:
        self._port = port
        self._hat = hat
        import spikehat  # real_hat.create_real_hat()でパス解決済みの前提

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
