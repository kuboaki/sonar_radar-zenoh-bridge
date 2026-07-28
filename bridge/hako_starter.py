"""hako_starter — Hakoniwa PDU経由でMuJoCo plantのstarter(フォースセンサー)を読む実装。

real_starter.RealStarter / hako_radar_base.HakoRadarBase と同じ設計方針。
plant(sonar_radar_hako.py)のforce_sensor PDUチャンネルをそのまま読むだけ。

plantのビューア(sonar_radar_viewer.py)でSpaceキーを押した場合も、
plant側がその押下リクエストをMuJoCoのpress_ctrlへ適用し、結果として
force_sensor PDUの値が変わる。つまりこのクラスからは、人間がビューアで
操作したのか、HakoSpikeHat.schedule_auto_press()で自動注入したのかを
区別しない(実機の物理ボタンと同じ扱い)。
"""

from __future__ import annotations


class HakoStarter:
    """Hakoniwa plant経由のstarter(フォースセンサー)。sonar_radar::unit::starterに相当。"""

    def __init__(self, hako_hat, port: int = 1) -> None:
        self._hat = hako_hat
        self._port = port

    def is_pushed(self) -> bool:
        return bool(self._hat.force_is_pressed(self._port))
