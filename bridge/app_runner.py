"""app_runner — SonarRadarApp の共通実行ループ。

実機用(run_real.py)・シミュレータ用(run_hako.py)の両方から使われる、
「ハードウェアの実体(スタブ/実機/hako)は呼び出し側が用意して注入し、
ここでは SonarRadarApp の構築・tickループ・state reportingだけを行う」
という共通部分。

以前は run_calibration_smoke_test.py / run_start_smoke_test.py /
それぞれのhako版という4本のスクリプトが、この部分をほぼ同じ内容で
コピーして持っていた。片方にだけ機能追加して他方に反映し忘れる、
という事故(--real-radar-baseの追加漏れ)が実際に起きたため、
1箇所に集約した。

sleep には time.sleep(実機・スタブ用)か hako_hat.sleep(シミュレータ用、
内部でhakopy.usleep()を呼びシミュレーション時刻を進める)を渡す。
"""

from __future__ import annotations

import sys
from typing import Callable, Optional, Set

from broker import Broker
from console_report import console_report
from sonar_radar_app import SonarRadarApp, State
from state_reporter import with_state_change_reporting



def run_app(
    *,
    prefix: str,
    config_path: str,
    origin: int,
    participants: Set[int],
    is_leader: bool,
    sleep: Callable[[float], None],
    tick_interval_sec: float,
    overall_timeout_sec: float,
    calibration_timeout_sec: float = 5.0,
    starter_is_pushed: Optional[Callable[[], bool]] = None,
    marker_detector_is_detected: Optional[Callable[[], bool]] = None,
    radar_base_invert_direction: Optional[Callable[[], None]] = None,
    radar_base_calibrate: Optional[Callable[[], None]] = None,
    radar_base_is_calibrated: Optional[Callable[[], bool]] = None,
    scanner_get_distance: Optional[Callable[[], int]] = None,
) -> int:
    """SonarRadarAppを構築し、is_terminated()になるかタイムアウトするまで動かす。

    停止条件はSonarRadarApp自身のis_terminated()のみで、このハーネス側で
    「どの状態で止めるか」を判断しない(状態機械の設計通りに進めさせる)。
    どの経路(CALIBRATION_FAILED経由か、正常にSCANNINGまで進んだか等)を
    辿ったかは、with_state_change_reportingで出力される状態遷移ログで
    判別する。

    戻り値: is_terminated()に到達すれば0(=状態機械が自律的にどこかの
    終端に達した)、overall_timeout_secに達してもまだ待ち状態のままなら
    1(=何も届かず/完了せず時間切れ)。
    """
    broker = Broker(f"sonar_radar_zenoh_bridge_{prefix}_{origin}", origin)
    broker.open(config_path)

    app = SonarRadarApp(
        broker=broker,
        calibration_participants=participants,
        is_leader=is_leader,
        starter_is_pushed=starter_is_pushed,
        marker_detector_is_detected=marker_detector_is_detected,
        radar_base_invert_direction=radar_base_invert_direction,
        radar_base_calibrate=radar_base_calibrate,
        radar_base_is_calibrated=radar_base_is_calibrated,
        scanner_get_distance=scanner_get_distance,
        calibration_timeout_sec=calibration_timeout_sec,
    )

    def _report(state: State) -> None:
        console_report(state.value, prefix=prefix)
        broker.publish_state(state.value)

    with_state_change_reporting(app, _report)

    print(
        f"[{prefix}] origin={origin} participants={sorted(participants)} "
        f"leader={is_leader} config={config_path}",
        file=sys.stderr,
    )

    elapsed = 0.0
    try:
        while not app.is_terminated() and elapsed < overall_timeout_sec:
            app.run()
            if app.is_terminated():
                break
            sleep(tick_interval_sec)
            elapsed += tick_interval_sec
    finally:
        broker.close()

    if app.is_terminated():
        print(f"[{prefix}] OK: is_terminated() に到達しました", file=sys.stderr)
        return 0
    else:
        print(f"[{prefix}] NG: タイムアウト(最終状態: {app.state.value})", file=sys.stderr)
        return 1
