"""sonar_radar_app — Zenoh版 sonar_radar のステートマシン本体。

docs/zenoh_state_machine_design.md 記載のステートマシン図
(sonar_radar::runのステートマシン図)を、状態名・イベント名を
そのままコードの識別子として1:1で実装したもの
(docs/zenoh_state_machine_design.md の「どう生成するか」の議論での
「手作業だが規約で縛る」方式)。

このマイルストーンで実装する範囲: INIT / WAIT_CALIBRATED /
CALIBRATION_FAILED / TERMINATED、および WAIT_FOR_START_PRESS への
到達確認まで。WAIT_FOR_START_PRESS 以降の処理は未実装
(次のマイルストーンで着手)。
"""

from __future__ import annotations

import enum
from typing import Set

from broker import Broker
from spikehat_timer import (
    spikehat_timer_create,
    spikehat_timer_is_fired,
    spikehat_timer_reset,
    spikehat_timer_start,
)


class State(enum.Enum):
    INIT = "INIT"
    WAIT_CALIBRATED = "WAIT_CALIBRATED"
    CALIBRATION_FAILED = "CALIBRATION_FAILED"
    WAIT_FOR_START_PRESS = "WAIT_FOR_START_PRESS"
    TERMINATED = "TERMINATED"


class SonarRadarApp:
    def __init__(
        self,
        broker: Broker,
        calibration_participants: Set[int],
        is_leader: bool,
    ) -> None:
        self._broker = broker
        self._calibration_participants = calibration_participants
        self.is_leader = is_leader
        self._timer = spikehat_timer_create()
        self._state = State.INIT

    @property
    def state(self) -> State:
        return self._state

    def is_terminated(self) -> bool:
        return self._state is State.TERMINATED

    # --- ガード関数 (ClassName_methodName規約に沿った命名) ---

    def check_calibration_participants(self) -> bool:
        """すべての参加者がキャリブレーション実行の応答を返したかチェックする。"""
        return all(
            self._broker.is_calibrated_received_from(origin)
            for origin in self._calibration_participants
        )

    # --- タイマー (このステートマシンが1つだけ所有する) ---

    def timer_start(self, duration_sec: float) -> None:
        spikehat_timer_start(self._timer, duration_sec)

    def timer_is_fired(self) -> bool:
        return bool(spikehat_timer_is_fired(self._timer))

    def timer_stop(self) -> None:
        spikehat_timer_reset(self._timer)

    # --- run(): tickごとに呼ばれる ---

    def run(self) -> None:
        if self._state is State.INIT:
            self._tick_init()
        elif self._state is State.WAIT_CALIBRATED:
            self._tick_wait_calibrated()
        elif self._state is State.CALIBRATION_FAILED:
            self._tick_calibration_failed()
        elif self._state is State.WAIT_FOR_START_PRESS:
            pass  # 未実装。到達確認のみがこのマイルストーンの目的。
        elif self._state is State.TERMINATED:
            pass

    def _tick_init(self) -> None:
        # entry: 初期化処理(calibration_participants取得、timer_create等)
        # このアプリでは calibration_participants はコンストラクタ引数で
        # 受け取り済み、timer もコンストラクタで作成済みのため、
        # ここでは即座に自動遷移するのみ。
        self._transition_to(State.WAIT_CALIBRATED)

    def _tick_wait_calibrated(self) -> None:
        if self.check_calibration_participants():
            self.timer_stop()  # exit
            self._transition_to(State.WAIT_FOR_START_PRESS)
            return
        if self.timer_is_fired():
            self.timer_stop()  # exit
            self._transition_to(State.CALIBRATION_FAILED)

    def _tick_calibration_failed(self) -> None:
        # entry: キャリブレーション失敗を通知(即座に自動遷移、待つものなし)
        self._transition_to(State.TERMINATED)

    def _transition_to(self, new_state: State) -> None:
        self._state = new_state
        if new_state is State.WAIT_CALIBRATED:
            self._broker.publish_calibrate()  # entry
            self.timer_start(5.0)  # entry
        elif new_state is State.CALIBRATION_FAILED:
            print("[sonar_radar_app] entry: キャリブレーション失敗を通知")
        elif new_state is State.TERMINATED:
            print("[sonar_radar_app] entry: 終了処理")
