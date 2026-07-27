"""sonar_radar_app — Zenoh版 sonar_radar のステートマシン本体。

docs/zenoh_state_machine_design.md 記載のステートマシン図
(sonar_radar::runのステートマシン図)を、状態名・イベント名を
そのままコードの識別子として1:1で実装したもの
(docs/zenoh_state_machine_design.md の「どう生成するか」の議論での
「手作業だが規約で縛る」方式)。

マイルストーン1で実装済み: INIT / WAIT_CALIBRATED /
CALIBRATION_FAILED / TERMINATED。
マイルストーン2で追加: WAIT_FOR_START_PRESS / WAIT_FOR_START_RELEASE /
WAIT_FOR_SCAN_START / SCANNING(到達まで)。押下→解放→start協調が
このマイルストーンの範囲。MARKER_DETECTED以降(detected対称処理、
WAIT_FOR_INVERT、stop対称処理、SCAN_FAILED)は次のマイルストーンで着手。

starter_is_pushed()/marker_detector_is_detected()/
radar_base_invert_direction()/scanner_get_distance() は、実ハードウェア
(libspikehat)がまだこの層に接続されていないため、コンストラクタで
注入可能にしている(未指定時はfalse/no-op/0を返す安全なスタブ)。

calibration_timeout_sec は WAIT_CALIBRATED のタイムアウト秒数
(設計文書の「timeout秒数はこのステートマシンを持つクラスの属性
（既定5秒）」に対応、コンストラクタで変更可能)。これは「準備が整い
run()が動き出してから、相手のcalibratedが揃うのを待つ時間」であり、
実機のBuild HAT等のハードウェア初期化にかかる時間は含まない
(初期化は broker.open() より前、run() が始まる前に完了させること)。
"""

from __future__ import annotations

import enum
from typing import Callable, Optional, Set

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
    WAIT_FOR_START_RELEASE = "WAIT_FOR_START_RELEASE"
    WAIT_FOR_SCAN_START = "WAIT_FOR_SCAN_START"
    SCANNING = "SCANNING"
    TERMINATED = "TERMINATED"


class SonarRadarApp:
    def __init__(
        self,
        broker: Broker,
        calibration_participants: Set[int],
        is_leader: bool,
        starter_is_pushed: Optional[Callable[[], bool]] = None,
        marker_detector_is_detected: Optional[Callable[[], bool]] = None,
        radar_base_invert_direction: Optional[Callable[[], None]] = None,
        scanner_get_distance: Optional[Callable[[], int]] = None,
        calibration_timeout_sec: float = 5.0,
    ) -> None:
        self._broker = broker
        self._calibration_participants = calibration_participants
        self.is_leader = is_leader
        self._timer = spikehat_timer_create()
        self._state = State.INIT
        self._calibration_timeout_sec = calibration_timeout_sec
        self._starter_is_pushed_impl = starter_is_pushed or (lambda: False)
        self._marker_detector_is_detected_impl = marker_detector_is_detected or (lambda: False)
        self._radar_base_invert_direction_impl = radar_base_invert_direction or (lambda: None)
        self._scanner_get_distance_impl = scanner_get_distance or (lambda: 0)

    @property
    def state(self) -> State:
        return self._state

    def is_terminated(self) -> bool:
        return self._state is State.TERMINATED

    # --- ガード関数・エフェクト (ClassName_methodName規約に沿った命名) ---

    def check_calibration_participants(self) -> bool:
        """すべての参加者がキャリブレーション実行の応答を返したかチェックする。"""
        return all(
            self._broker.is_calibrated_received_from(origin)
            for origin in self._calibration_participants
        )

    def starter_is_pushed(self) -> bool:
        return bool(self._starter_is_pushed_impl())

    def marker_detector_is_detected(self) -> bool:
        return bool(self._marker_detector_is_detected_impl())

    def radar_base_invert_direction(self) -> None:
        self._radar_base_invert_direction_impl()

    def scanner_get_distance(self) -> int:
        return self._scanner_get_distance_impl()

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
            self._tick_wait_for_start_press()
        elif self._state is State.WAIT_FOR_START_RELEASE:
            self._tick_wait_for_start_release()
        elif self._state is State.WAIT_FOR_SCAN_START:
            self._tick_wait_for_scan_start()
        elif self._state is State.SCANNING:
            self._tick_scanning()
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

    def _tick_wait_for_start_press(self) -> None:
        if self.is_leader and self.starter_is_pushed():
            self._transition_to(State.WAIT_FOR_START_RELEASE)
            return
        if self._broker.consume_start_received():
            self._transition_to(State.SCANNING)

    def _tick_wait_for_start_release(self) -> None:
        if not self.starter_is_pushed():
            self._transition_to(State.WAIT_FOR_SCAN_START)

    def _tick_wait_for_scan_start(self) -> None:
        if self._broker.consume_start_received():
            self.timer_stop()  # exit
            self._transition_to(State.SCANNING)
            return
        if self.timer_is_fired():
            self.timer_stop()  # exit
            # SCAN_FAILEDは次のマイルストーンで実装。現状は失敗を通知して終了する。
            print("[sonar_radar_app] entry: スキャン開始失敗を通知(SCAN_FAILED未実装)")
            self._transition_to(State.TERMINATED)

    def _tick_scanning(self) -> None:
        # do: scanner_get_distance() / radar/scanner/scanをpublish
        distance_mm = self.scanner_get_distance()
        self._broker.publish_scan(angle=0, distance_mm=distance_mm)
        # MARKER_DETECTED/WAIT_FOR_INVERT/stop対称処理/SCAN_FAILEDは
        # 次のマイルストーンで実装。

    def _transition_to(self, new_state: State) -> None:
        self._state = new_state
        if new_state is State.WAIT_CALIBRATED:
            self._broker.publish_calibrate()  # entry
            self.timer_start(self._calibration_timeout_sec)  # entry
        elif new_state is State.CALIBRATION_FAILED:
            print("[sonar_radar_app] entry: キャリブレーション失敗を通知")
        elif new_state is State.WAIT_FOR_SCAN_START:
            self._broker.publish_start()  # entry
            self.timer_start(2.0)  # entry
        elif new_state is State.TERMINATED:
            print("[sonar_radar_app] entry: 終了処理")
