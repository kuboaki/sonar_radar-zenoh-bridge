"""sonar_radar_app — Zenoh版 sonar_radar のステートマシン本体。

docs/zenoh_state_machine_design.md 記載のステートマシン図
(sonar_radar::runのステートマシン図)を、状態名・イベント名を
そのままコードの識別子として1:1で実装したもの。

INIT(broker.open() → hardware_initialize() → timer_create())から
CALIBRATING(ローカルなハードウェアキャリブレーションのみ、マシン間の
通信協調は無し)までを、人が起動してから完了するまで1つの流れに閉じ込め、
完了したら自動的にWAIT_FOR_START_PRESSへ遷移する。マシン間の
calibrate/calibrated協調は廃止した(各machineが独立してキャリブレーション
を完了させる設計に転回したため。経緯はdocs/zenoh_state_machine_design.md
「背景: キャリブレーション協調の廃止」参照)。

CALIBRATING: entryでradar_base_calibrate()を呼び(モーターホーミング等、
完了に時間がかかる処理を想定。calibrate()自体は駆動開始のみで即座に
返る非同期呼び出し前提)、完了はradar_base_is_calibrated()を毎tick
ポーリングして判定する(starter_is_pushed()等と同じ「レベルトリガーを
イベント扱いする」書き方)。exitでtimer_stop()を呼ぶ(「CALIBRATINGで
なくなったら止める」という本来の意味論のため、CALIBRATION_FAILEDの
entry側では呼ばない)。

CALIBRATION_FAILEDは、マシン間協調の失敗ではなく、ローカルなハードウェア
障害(物理的にモーターが固着している等)専用。タイムアウトは20秒
(calibration_timeout_sec、コンストラクタで変更可能)。

starter_is_pushed()/marker_detector_is_detected()/
radar_base_invert_direction()/radar_base_calibrate()/
radar_base_is_calibrated()/radar_base_run()/radar_base_stop()/
radar_base_get_position()/radar_base_get_dome_angle()/scanner_get_distance() は、実ハードウェア(libspikehat)の実装差し替えを
呼び出し側スクリプトに委ねるため、コンストラクタで注入可能にしている
(未指定時はfalse/no-op/0を返す安全なスタブ)。

MARKER_DETECTED/WAIT_FOR_INVERT/stopの対称処理/SCAN_FAILEDは、
start/WAIT_FOR_SCAN_STARTと同じ「ローカル検知→publishのみ、実アクション
(方向反転・終了)は自分のpublishのループバック受信で行う、受信のみの
側は直接遷移する」パターンをそのまま踏襲する。

is_leader(マーカー検出・方向反転の権限)とis_starter(ローカルの
starter_is_pushed()判定・start/stop発行の権限)は独立した属性。
is_starter未指定時はis_leaderと同値になる(既存呼び出し元との後方互換)。
start/stopはconsume_start_received()/consume_stop_received()にis_leader/
is_starterのガードが無いため、実機・シム以外(broker経由の外部)からの
注入も特別な対応無しで受け取れる(is_starterはsonar_radarクラス内だけの
属性で、外部の注入者はこの属性を持たない)。

- SCANNING --[marker_detector_is_detected()][is_leader==true]--> MARKER_DETECTED
  (entryでdetectedをpublish、publish_confirm_timeout_sec付き)
  --[detectedを受信した]--> WAIT_FOR_INVERT(entryでradar_base_invert_direction()、
  無条件でSCANNINGへ戻る)。followerはSCANNINGから直接
  --[detectedを受信した]--> WAIT_FOR_INVERTへ進む(MARKER_DETECTEDを経由しない)。
- SCANNING --[starter_is_pushed()][is_starter==true]--> WAIT_FOR_STOP_PRESS
  --[!starter_is_pushed()]--> WAIT_FOR_STOP_RELEASE(entryでstopをpublish、
  publish_confirm_timeout_sec付き)--[stopを受信した]--> TERMINATED。followerは
  SCANNINGから直接--[stopを受信した]--> TERMINATEDへ進む。
- SCAN_FAILED(entryでスキャン失敗を通知+stopをpublish)は、
  WAIT_FOR_SCAN_START/MARKER_DETECTEDのタイムアウトから到達し、
  無条件でWAIT_FOR_STOP_RELEASEへ進む(通常のstop対称処理に合流し、
  自分のstopのループバック受信を待ってからTERMINATEDへ至る)。

publish_confirm_timeout_sec(既定2秒)は、WAIT_FOR_SCAN_START/
MARKER_DETECTED/WAIT_FOR_STOP_RELEASEに共通の「自分のpublishが
ループバックしてくるのを待つ」タイムアウト。3状態とも目的が同じ
(Zenoh経由の自己確認)なので1つの属性にまとめている。

SCANNING --[timer_is_fired()]--> SCAN_FAILED (scanning_timeout_sec、
既定8秒)は、CALIBRATINGのタイムアウトとは目的が逆であることに注意。
CALIBRATINGの20秒は「機構のずれを実機で外してはめ直す猶予」だが、
SCANNINGのタイムアウトは「ドームが旋回しすぎてセンサーケーブルを
巻き込む前に止める」ための早期カットオフ。基準値は実機実測(マーカー間
1レッグの所要時間、複数回計測で最大約5.3秒。シム側も実時間設計により
同程度)に、ブリッジ経由のオーバーヘッド(Zenoh送受信・tickループ等、
実測+1〜1.5秒程度)を加味したもの(2026-07-29/08-02計測、
docs/development_log.md参照)。ケーブル巻き込みリスクは実機だけの制約
でシムには無いため、既定値はrun_real.py/run_hako.pyそれぞれの
--scanning-timeoutで実機は8秒・シムは12秒に分けている(このクラス
自体の既定値8秒は安全側=実機に合わせたもの)。entryでtimer_start
(scanning_timeout_sec)、exitでtimer_stop()を行う(WAIT_FOR_INVERTからの
再入時も含め、SCANNINGに入るたび1レッグ分としてタイマーを取り直す)。
"""

from __future__ import annotations

import enum
from typing import Callable, Optional

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
    CALIBRATING = "CALIBRATING"
    CALIBRATION_FAILED = "CALIBRATION_FAILED"
    WAIT_FOR_START_PRESS = "WAIT_FOR_START_PRESS"
    WAIT_FOR_START_RELEASE = "WAIT_FOR_START_RELEASE"
    WAIT_FOR_SCAN_START = "WAIT_FOR_SCAN_START"
    SCANNING = "SCANNING"
    MARKER_DETECTED = "MARKER_DETECTED"
    WAIT_FOR_INVERT = "WAIT_FOR_INVERT"
    WAIT_FOR_STOP_PRESS = "WAIT_FOR_STOP_PRESS"
    WAIT_FOR_STOP_RELEASE = "WAIT_FOR_STOP_RELEASE"
    SCAN_FAILED = "SCAN_FAILED"
    TERMINATED = "TERMINATED"


class SonarRadarApp:
    def __init__(
        self,
        broker: Broker,
        broker_config_path: str,
        is_leader: bool,
        is_starter: Optional[bool] = None,
        hardware_initialize: Optional[Callable[[], None]] = None,
        starter_is_pushed: Optional[Callable[[], bool]] = None,
        marker_detector_is_detected: Optional[Callable[[], bool]] = None,
        radar_base_invert_direction: Optional[Callable[[], None]] = None,
        radar_base_calibrate: Optional[Callable[[], None]] = None,
        radar_base_is_calibrated: Optional[Callable[[], bool]] = None,
        radar_base_run: Optional[Callable[[], None]] = None,
        radar_base_stop: Optional[Callable[[], None]] = None,
        radar_base_get_position: Optional[Callable[[], int]] = None,
        radar_base_get_dome_angle: Optional[Callable[[], float]] = None,
        scanner_get_distance: Optional[Callable[[], int]] = None,
        calibration_timeout_sec: float = 20.0,
        scanning_timeout_sec: float = 8.0,
        publish_confirm_timeout_sec: float = 2.0,
    ) -> None:
        # brokerはコンストラクタで構築済み(集約、生成・破棄は呼び出し側の
        # 責務)だが、まだopen()していないものを受け取る。open()はINITの
        # entryで行う(broker.open()はイベント監視の開始そのものであり、
        # 状態機械が担うべき処理のため)。
        self._broker = broker
        self._broker_config_path = broker_config_path
        self.is_leader = is_leader
        # is_starter未指定時はis_leaderと同値にする(既存呼び出し元との後方
        # 互換。is_leader=マーカー検出/方向反転の権限、is_starter=ローカル
        # starter_is_pushed()の判定・start/stop発行の権限で、本来は独立)。
        self.is_starter = is_leader if is_starter is None else is_starter
        # timerはこのクラスのコンポジション(生成・破棄ともこのクラスが担う)。
        # 生成はINIT、破棄はTERMINATEDのentryで行う(_tick_init/_transition_to参照)。
        self._timer = None
        self._state = State.INIT
        self._calibration_timeout_sec = calibration_timeout_sec
        self._scanning_timeout_sec = scanning_timeout_sec
        self._publish_confirm_timeout_sec = publish_confirm_timeout_sec
        # 実機とシミュレータでは、ハードウェア初期化の中身も外見も異なる
        # (実機: ファームウェアロード等の複数手順・ブロッキング、
        # シミュレータ: 実質的な待ちが無い変数設定)ため、radar_base_*等と
        # 同じく注入可能にし、この違いを呼び出し側(run_real.py/run_hako.py)
        # に吸収させる(既定は何もしないスタブ)。
        self._hardware_initialize_impl = hardware_initialize or (lambda: None)
        self._starter_is_pushed_impl = starter_is_pushed or (lambda: False)
        self._marker_detector_is_detected_impl = marker_detector_is_detected or (lambda: False)
        self._radar_base_invert_direction_impl = radar_base_invert_direction or (lambda: None)
        self._radar_base_calibrate_impl = radar_base_calibrate or (lambda: None)
        self._radar_base_is_calibrated_impl = radar_base_is_calibrated or (lambda: False)
        self._radar_base_run_impl = radar_base_run or (lambda: None)
        self._radar_base_stop_impl = radar_base_stop or (lambda: None)
        self._radar_base_get_position_impl = radar_base_get_position or (lambda: 0)
        self._radar_base_get_dome_angle_impl = radar_base_get_dome_angle or (lambda: 0.0)
        self._scanner_get_distance_impl = scanner_get_distance or (lambda: 0)

    @property
    def state(self) -> State:
        return self._state

    def is_terminated(self) -> bool:
        return self._state is State.TERMINATED

    # --- ガード関数・エフェクト (ClassName_methodName規約に沿った命名) ---

    def hardware_initialize(self) -> None:
        self._hardware_initialize_impl()

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

    def radar_base_run(self) -> None:
        self._radar_base_run_impl()

    def radar_base_stop(self) -> None:
        self._radar_base_stop_impl()

    def radar_base_get_position(self) -> int:
        return self._radar_base_get_position_impl()

    def radar_base_get_dome_angle(self) -> float:
        return self._radar_base_get_dome_angle_impl()

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
        elif self._state is State.CALIBRATING:
            self._tick_calibrating()
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
        elif self._state is State.MARKER_DETECTED:
            self._tick_marker_detected()
        elif self._state is State.WAIT_FOR_INVERT:
            self._tick_wait_for_invert()
        elif self._state is State.WAIT_FOR_STOP_PRESS:
            self._tick_wait_for_stop_press()
        elif self._state is State.WAIT_FOR_STOP_RELEASE:
            self._tick_wait_for_stop_release()
        elif self._state is State.SCAN_FAILED:
            self._tick_scan_failed()
        elif self._state is State.TERMINATED:
            pass

    def _tick_init(self) -> None:
        # entry: broker.open() → hardware_initialize() → timer_create()
        # broker.open()/hardware_initialize()/timer_create()は
        # それぞれ副作用(I/O・リソース確保)を持つ本当の意味でのアクション
        # なので、ここに明示する。
        #
        # broker.open()を先に行うのは、その後のhardware_initialize()が
        # (実機ではBuild HATのファームウェアロード等で)ブロッキングして
        # 時間がかかっても、Zenohの受信は内部スレッドが非同期に処理する
        # ため、その間に届くstart/stop/detected等を取りこぼさないため
        # (calibrate/calibratedのマシン間協調は廃止したため、この時点では
        # 特に待つ相手はいない)。
        #
        # hardware_initialize()の中身は実機とシミュレータで中身も外見も
        # 異なる(実機: ファームウェアロード等の複数手順・ブロッキング、
        # シミュレータ: 実質的な待ちが無い変数設定)ため、radar_base_*等と
        # 同じ「注入可能な関数」として呼び出し側に委ねる(この関数自体は
        # 何も知らない)。
        self._broker.open(self._broker_config_path)
        self.hardware_initialize()
        self._timer = spikehat_timer_create()
        self._transition_to(State.CALIBRATING)

    def _tick_calibrating(self) -> None:
        if self.radar_base_is_calibrated():
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
        if self.is_starter and self.starter_is_pushed():
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
            self._transition_to(State.SCAN_FAILED)

    def _tick_scanning(self) -> None:
        # do: radar_base_get_position() / radar_base_get_dome_angle() / scanner_get_distance() / radar/scanner/scanをpublish
        angle = self.radar_base_get_position()
        dome_angle = self.radar_base_get_dome_angle()
        distance_mm = self.scanner_get_distance()
        self._broker.publish_scan(angle=angle, dome_angle=dome_angle, distance_mm=distance_mm)
        # ローカル検知(publishのみ、状態はここではまだ進めない場合と、
        # 直接遷移する場合がある)。starterはis_starter、marker_detectorは
        # is_leaderとガードが異なる(両者は独立した権限のため)。自分の
        # publishのループバックがこの時点で届いているはずはないため、
        # 両者は同一tickで競合しない。
        if self.is_starter and self.starter_is_pushed():
            self.timer_stop()  # exit
            self._transition_to(State.WAIT_FOR_STOP_PRESS)
            return
        if self.is_leader and self.marker_detector_is_detected():
            self.timer_stop()  # exit
            self._transition_to(State.MARKER_DETECTED)
            return
        if self._broker.consume_stop_received():
            self.timer_stop()  # exit
            self._transition_to(State.TERMINATED)
            return
        if self._broker.consume_detected_received():
            self.timer_stop()  # exit
            self._transition_to(State.WAIT_FOR_INVERT)
            return
        if self.timer_is_fired():
            self.timer_stop()  # exit(ドームのケーブル巻き込み防止のための早期カットオフ)
            self._transition_to(State.SCAN_FAILED)

    def _tick_marker_detected(self) -> None:
        if self._broker.consume_detected_received():
            self.timer_stop()  # exit
            self._transition_to(State.WAIT_FOR_INVERT)
            return
        if self.timer_is_fired():
            self.timer_stop()  # exit
            self._transition_to(State.SCAN_FAILED)

    def _tick_wait_for_invert(self) -> None:
        # entry: radar_base_invert_direction()(_transition_to側で実行済み)。
        # 待つものが無いため、無条件でSCANNINGへ戻る
        # (INIT→CALIBRATING、CALIBRATION_FAILED→TERMINATEDと同じパターン)。
        self._transition_to(State.SCANNING)

    def _tick_wait_for_stop_press(self) -> None:
        if not self.starter_is_pushed():
            self._transition_to(State.WAIT_FOR_STOP_RELEASE)

    def _tick_wait_for_stop_release(self) -> None:
        if self._broker.consume_stop_received():
            self.timer_stop()  # exit
            self._transition_to(State.TERMINATED)

    def _tick_scan_failed(self) -> None:
        # entry: スキャン失敗を通知/stopをpublish(_transition_to側で実行済み)。
        # 通常のstop対称処理に合流し、自分のstopのループバック受信を待って
        # からTERMINATEDへ至る(WAIT_FOR_STOP_RELEASEのentryで再度stopが
        # publishされるが、consume_stop_received()は真偽フラグのため
        # 二重publish自体は無害)。
        self._transition_to(State.WAIT_FOR_STOP_RELEASE)

    def _transition_to(self, new_state: State) -> None:
        self._state = new_state
        if new_state is State.CALIBRATING:
            self.radar_base_calibrate()  # entry
            self.timer_start(self._calibration_timeout_sec)  # entry
        elif new_state is State.CALIBRATION_FAILED:
            print("[sonar_radar_app] entry: キャリブレーション失敗を通知")
        elif new_state is State.WAIT_FOR_SCAN_START:
            self._broker.publish_start()  # entry
            self.timer_start(self._publish_confirm_timeout_sec)  # entry
        elif new_state is State.SCANNING:
            self.radar_base_run()  # entry
            self.timer_start(self._scanning_timeout_sec)  # entry
        elif new_state is State.MARKER_DETECTED:
            self._broker.publish_detected()  # entry
            self.timer_start(self._publish_confirm_timeout_sec)  # entry
        elif new_state is State.WAIT_FOR_INVERT:
            self.radar_base_invert_direction()  # entry
        elif new_state is State.WAIT_FOR_STOP_RELEASE:
            self._broker.publish_stop()  # entry
            self.timer_start(self._publish_confirm_timeout_sec)  # entry
        elif new_state is State.SCAN_FAILED:
            print("[sonar_radar_app] entry: スキャン失敗を通知")
            self._broker.publish_stop()  # entry
        elif new_state is State.TERMINATED:
            self.radar_base_stop()  # entry
            self._broker.close()  # entry
            spikehat_timer_destroy(self._timer)  # entry
            print("[sonar_radar_app] entry: 終了処理")
