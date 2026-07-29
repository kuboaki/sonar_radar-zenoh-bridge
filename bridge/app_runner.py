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

import subprocess
import sys
from typing import Callable, Optional, Set

from broker import Broker
from console_report import console_report
from sonar_radar_app import SonarRadarApp, State
from state_reporter import with_state_change_reporting

# 旧driver/sonar_radar_zenoh.py(READMEで「旧・使わない」と明記)が動いた
# まま気づかれず、4日間ノイズを出し続けていた事故があった。同じ理由の
# 再発に気づけるよう、run_app()の最初で毎回チェックする。
_LEGACY_DRIVER_PATTERN = "sonar_radar_zenoh.py"


def _warn_if_legacy_driver_running() -> None:
    try:
        result = subprocess.run(
            ["pgrep", "-f", _LEGACY_DRIVER_PATTERN],
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except (OSError, subprocess.SubprocessError):
        return  # pgrepが無い環境などでは静かに諦める(この確認は無くても動作に支障ない)

    pids = result.stdout.split()
    if not pids:
        return

    print(
        f"\x1b[7m\x1b[31;1m[app_runner] 警告: 旧driver/sonar_radar_zenoh.py が動いたままです "
        f"(pid={','.join(pids)})。同じzenohdへノイズを送り続けている可能性があります。"
        f"bridge/cleanup.bash で停止してから確認してください。\x1b[0m",
        file=sys.stderr,
    )


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
    hardware_initialize: Optional[Callable[[], None]] = None,
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
    _warn_if_legacy_driver_running()

    # brokerの構築のみここで行う。open()とhardware_initialize()の呼び出しは
    # SonarRadarApp自身がINITのentryで行う(broker.open()を先に済ませて
    # から呼ぶため、hardware_initialize()がどれだけブロッキングして時間が
    # かかっても、その間に届いた相手のcalibrated等を取りこぼさない)。
    broker = Broker(f"sonar_radar_zenoh_bridge_{prefix}_{origin}", origin)

    app = SonarRadarApp(
        broker=broker,
        broker_config_path=config_path,
        calibration_participants=participants,
        is_leader=is_leader,
        hardware_initialize=hardware_initialize,
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
        # publish_state()は観測用の追加機能(コア設計の一部ではない)。
        # TERMINATED自身のentryでbroker.close()が先に実行されるため、
        # TERMINATEDへの遷移を報告する時点では既にbrokerが閉じている。
        # 観測手段の都合でコア設計(entryでのclose())を歪めないよう、
        # ここでの送信失敗は無視する。
        try:
            broker.publish_state(state.value)
        except Exception as e:
            print(f"[{prefix}] (state publish skipped: {e})", file=sys.stderr)

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
        # 正常にTERMINATEDへ到達した場合は、SonarRadarApp自身が
        # TERMINATEDのentryでbroker.close()を既に行っている(exitと
        # entryの二重close()を避けるため、未到達=タイムアウト時のみ
        # ここで安全網としてclose()する)。
        if not app.is_terminated():
            broker.close()

    if app.is_terminated():
        print(f"[{prefix}] OK: is_terminated() に到達しました", file=sys.stderr)
        return 0
    else:
        print(f"[{prefix}] NG: タイムアウト(最終状態: {app.state.value})", file=sys.stderr)
        return 1
