"""starter — sonar_radar::unit::starter に相当する、実機/SIM共通のユニット実装。

クラス図の設計意図通り、実機とSIMで別クラスに分けず単一のクラスを共有する。
実機/SIMの違いは、コンストラクタで渡すhatオブジェクト(実機はreal_hat.create_real_hat()
が返すspikehat.SpikeHat、SIMはlibspikehat_hako.HakoSpikeHat)の実装差だけに
閉じ込める(scanner.py/radar_base.py/marker_detector.pyと同じ設計)。

Build HATには「準備完了か」を問い合わせるソフトウェアAPIが無く、実機の
LED(赤→消灯、緑点灯)を目視するしかない。自動テストで人手を介さずに
待てるよう、コンストラクタ内で実際にforce_is_pressed()が例外を出さずに
読めるようになるまでポーリングして待つ(is_pushed()が返すようになって
初めて「準備完了」とみなす、というソフトウェアだけで完結する代替手段)。
SIM(HakoSpikeHat)側のforce_is_pressed()は例外を投げない設計のため、この
待機ループは初回呼び出しで即座に完了する(実質的な遅延は生じない)。

plantのビューア(sonar_radar_viewer.py)でSpaceキーを押した場合も、plant側
がその押下リクエストをMuJoCoのpress_ctrlへ適用し、結果としてforce_sensor
PDUの値が変わる。つまりこのクラスからは、人間がビューアで操作したのか、
HakoSpikeHat.schedule_auto_press()で自動注入したのかを区別しない
(実機の物理ボタンと同じ扱い)。
"""

from __future__ import annotations

import time

from device_types import DEVICE_FORCE


class Starter:
    """starter(フォースセンサー)を読む。sonar_radar::unit::starterに相当。実機/SIM共通実装。

    hatは実機ならreal_hat.create_real_hat()、SIM(Hakoniwa plant経由)なら
    libspikehat_hako.HakoSpikeHatのインスタンスを渡す。
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
        self._hat.port_config(self._port, DEVICE_FORCE)
        self._wait_until_ready(ready_timeout_sec, ready_poll_interval_sec)
        print(f"[starter] starter(force sensor, port={self._port})を初期化しました")

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
