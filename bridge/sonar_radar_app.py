"""sonar_radar_app — Zenoh版 sonar_radar のステートマシン本体。

docs/zenoh_state_machine_design.md 記載のステートマシン図
(sonar_radar::runのステートマシン図)を、状態名・イベント名を
そのままコードの識別子として1:1で実装したもの
(docs/zenoh_state_machine_design.md の「どう生成するか」の議論での
「手作業だが規約で縛る」方式)。

マイルストーン1で実装済み: INIT / WAIT_FOR_CALIBRATE / CALIBRATING /
WAIT_FOR_CALIBRATED / CALIBRATION_FAILED / TERMINATED。
マイルストーン2で追加: WAIT_FOR_START_PRESS / WAIT_FOR_START_RELEASE /
WAIT_FOR_SCAN_START / SCANNING(到達まで)。押下→解放→start協調が
このマイルストーンの範囲。MARKER_DETECTED以降(detected対称処理、
WAIT_FOR_INVERT、stop対称処理、SCAN_FAILED)は次のマイルストーンで着手。

radar/dome/calibrate を受信してから実際にキャリブレーションを実施する
までを CALIBRATING で表す(entry で radar_base_calibrate() を呼び、
完了は radar_base_is_calibrated() を毎tickポーリングして判定する。
starter_is_pushed() 等と同じ「レベルトリガーをイベント扱いする」書き方)。
モーターホーミング等、完了に時間がかかる処理を想定しており、
calibrate() 自体は非同期(駆動開始のみ)である前提。

starter_is_pushed()/marker_detector_is_detected()/
radar_base_invert_direction()/radar_base_calibrate()/
radar_base_is_calibrated()/scanner_get_distance() は、実ハードウェア
(libspikehat)がまだこの層に接続されていないため、コンストラクタで
注入可能にしている(未指定時はfalse/no-op/0を返す安全なスタブ)。

calibration_timeout_sec は WAIT_FOR_CALIBRATE / CALIBRATING /
WAIT_FOR_CALIBRATED を通したタイムアウト秒数(設計文書の「timeout秒数は
このステートマシンを持つクラスの属性（既定5秒）」に対応、コンストラクタで
変更可能)。これは「準備が整いrun()が動き出してから、キャリブレーションが
完了し相手のcalibratedが揃うのを待つ時間」であり、実機のBuild HAT等の
ハードウェア初期化にかかる時間は含まない(ハードウェア初期化は状態機械の
モデル外であり、呼び出し側スクリプトの責務。broker.open()自体はINITの
entryで行われ、ハードウェア初期化の完了を待たない)。タイマーの停止は成功経路では
WAIT_FOR_CALIBRATED の exit、失敗経路(3状態いずれからのtimer_is_fired()
でも)は CALIBRATION_FAILED の entry で行う。WAIT_FOR_CALIBRATED からの
失敗経路だけexitとentryの両方でtimer_stop()が呼ばれる形になるが、
spikehat_timer_reset()は冪等(何度呼んでも安全)なので問題ない。
"""

from __future__ import annotations

import enum
from typing import Callable, Optional, Set

from broker import Broker
from spikehat_timer import (
    spikehat_timer_create,
    spikehat_timer_destroy,
    spikehat_timer_is_fired,
    spikehat_timer_reset,
    spikehat_timer_start,
)


class State(enum.Enum):
    INIT = "INIT"
    WAIT_FOR_CALIBRATE = "WAIT_FOR_CALIBRATE"
    CALIBRATING = "CALIBRATING"
    WAIT_FOR_CALIBRATED = "WAIT_FOR_CALIBRATED"
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
        broker_config_path: str,
        calibration_participants: Set[int],
        is_leader: bool,
        starter_is_pushed: Optional[Callable[[], bool]] = None,
        marker_detector_is_detected: Optional[Callable[[], bool]] = None,
        radar_base_invert_direction: Optional[Callable[[], None]] = None,
        radar_base_calibrate: Optional[Callable[[], None]] = None,
        radar_base_is_calibrated: Optional[Callable[[], bool]] = None,
        scanner_get_distance: Optional[Callable[[], int]] = None,
        calibration_timeout_sec: float = 5.0,
    ) -> None:
        # brokerはコンストラクタで構築済み(集約、生成・破棄は呼び出し側の
        # 責務)だが、まだopen()していないものを受け取る。open()はINITの
        # entryで行う(broker.open()はイベント監視の開始そのものであり、
        # 状態機械が担うべき処理のため)。
        self._broker = broker
        self._broker_config_path = broker_config_path
        self._calibration_participants = calibration_participants
        self.is_leader = is_leader
        # timerはこのクラスのコンポジション(生成・破棄ともこのクラスが担う)。
        # 生成はINIT、破棄はTERMINATEDのentryで行う(_tick_init/_transition_to参照)。
        self._timer = None
        self._state = State.INIT
        self._calibration_timeout_sec = calibration_timeout_sec
        self._starter_is_pushed_impl = starter_is_pushed or (lambda: False)
        self._marker_detector_is_detected_impl = marker_detector_is_detected or (lambda: False)
        self._radar_base_invert_direction_impl = radar_base_invert_direction or (lambda: None)
        self._radar_base_calibrate_impl = radar_base_calibrate or (lambda: None)
        self._radar_base_is_calibrated_impl = radar_base_is_calibrated or (lambda: False)
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

    def radar_base_calibrate(self) -> None:
        self._radar_base_calibrate_impl()

    def radar_base_is_calibrated(self) -> bool:
        return bool(self._radar_base_is_calibrated_impl())

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
        elif self._state is State.WAIT_FOR_CALIBRATE:
            self._tick_wait_for_calibrate()
        elif self._state is State.CALIBRATING:
            self._tick_calibrating()
        elif self._state is State.WAIT_FOR_CALIBRATED:
            self._tick_wait_for_calibrated()
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
        # entry: broker.open() → timer_create()
        # calibration_participants はコンストラクタ引数で受け取り済み
        # (副作用も他への依存も無い純粋なデータ設定のため、コンストラクタで
        # 済ませてよい)。broker.open()とtimer_create()は、それぞれ副作用
        # (I/O・リソース確保)を持つ本当の意味でのアクションなので、ここに
        # 明示する。broker.open()はハードウェア初期化(実機のBuild HAT等)を
        # 待たない(そちらは呼び出し側スクリプトの責務でモデル外、待って
        # しまうとイベント監視の開始が遅れ、先に届いた相手のcalibrated等を
        # 取りこぼす)。
        self._broker.open(self._broker_config_path)
        self._timer = spikehat_timer_create()
        self._transition_to(State.WAIT_FOR_CALIBRATE)

    def _tick_wait_for_calibrate(self) -> None:
        if self._broker.consume_calibrate_received():
            self._transition_to(State.CALIBRATING)
            return
        if self.timer_is_fired():
            self._transition_to(State.CALIBRATION_FAILED)

    def _tick_calibrating(self) -> None:
        if self.radar_base_is_calibrated():
            self._transition_to(State.WAIT_FOR_CALIBRATED)
            return
        if self.timer_is_fired():
            self._transition_to(State.CALIBRATION_FAILED)

    def _tick_wait_for_calibrated(self) -> None:
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
        #
        # 【実装作業の便法、図には対応する遷移なし】SCANNINGから出る本来の
        # 遷移(stop対称処理等)が未実装の間、is_terminated()でtickループを
        # 終了できるようにするための暫定処置として、doを1回実行したら
        # 無条件にTERMINATEDへ遷移する。次のマイルストーンでSCANNINGから
        # 出る遷移を実装するときは、この行を削除し、その遷移に置き換える。
        self._transition_to(State.TERMINATED)

    def _transition_to(self, new_state: State) -> None:
        self._state = new_state
        if new_state is State.WAIT_FOR_CALIBRATE:
            self._broker.publish_calibrate()  # entry
            self.timer_start(self._calibration_timeout_sec)  # entry
        elif new_state is State.CALIBRATING:
            self.radar_base_calibrate()  # entry
        elif new_state is State.WAIT_FOR_CALIBRATED:
            self._broker.publish_calibrated()  # entry
        elif new_state is State.CALIBRATION_FAILED:
            self.timer_stop()  # entry
            print("[sonar_radar_app] entry: キャリブレーション失敗を通知")
        elif new_state is State.WAIT_FOR_SCAN_START:
            self._broker.publish_start()  # entry
            self.timer_start(2.0)  # entry
        elif new_state is State.TERMINATED:
            self._broker.close()  # entry
            spikehat_timer_destroy(self._timer)  # entry
            print("[sonar_radar_app] entry: 終了処理")
