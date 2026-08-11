#!/usr/bin/env python3
"""scan_batch_viewer.py — /sonar_radar/scan_batch を matplotlib WebAgg で
リアルタイムに極座標表示するrclpyノード。

Pi5はGUI無し(DISPLAY未設定)のため、matplotlibのWebAggバックエンド
(自ノード内にHTTPサーバーを立てる)を使う。これにより「Pi5自身での
表示」「別ノードでの表示」「ブラウザでのWeb表示」のいずれも、この
ノードを起動してブラウザで http://<起動ホスト>:<port>/ を開くだけで
満たせる。

bridge/plot_scan.py の「コールバックはqueueに積むだけ、FuncAnimationが
メインスレッドで取り出して描画する」パターン、極座標設定(北基準・
時計回り、set_theta_direction(-1))、origin毎の色分けをそのまま踏襲する
(rclpyの購読コールバックも別スレッドから非同期に呼ばれるため、
plot_scan.pyと同じ理由でqueue経由にする必要がある)。

bridge/broker.pyがsensor_msgs/PointCloudのchannelsへ詰めるのは
"angle"(モーター生角度、dome_angle未補正)/"distance_mm"/"origin"の3本
(docs/pdu_ros_bridge_ros_zenoh_mapping.md参照)。dome_angle相当への変換
(-angle/gear_ratio、bridge/radar_base.pyのgear_ratio既定3と同じ式)は
可視化側の責務としてここで行う。

壁を動かした後の測定は前回までの測定と混ぜて見ても意味が無いため、
/pdu/sonar_radar/state(config/raspi5/ros_bindings_scan_batch.jsonで
pdu_to_ros中継、bridge/plot_scan.pyと同じ設計)を購読し、そのoriginが
CALIBRATINGになったら、そのoriginの蓄積済みプロットを消去する。

このモジュールはrclpy/sensor_msgsに依存する。bridge/broker.pyが明言する
「Zenoh専用・rclpy非依存」という不変条件を壊さないよう、bridge/ではなく
ros/ に置く。

使い方(Pi5、または同じROS2ドメインに参加できる任意のマシンで):
  source /opt/ros/jazzy/setup.bash
  python3 ros/scan_batch_viewer.py --port 8988
  (同じLAN上の任意のブラウザで http://<このホストのIP>:8988/ を開く)
"""

from __future__ import annotations

import argparse
import math
import queue
import threading

import matplotlib

matplotlib.use("WebAgg")

import matplotlib.animation as animation  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import rclpy  # noqa: E402
from rclpy.node import Node  # noqa: E402
from sensor_msgs.msg import PointCloud  # noqa: E402
from std_msgs.msg import String  # noqa: E402

_COLORS = ["tab:blue", "tab:orange", "tab:green", "tab:red", "tab:purple"]
_ABS_MAX_DISTANCE_MM = 5000  # 異常値のクリップ上限(bridge/plot_scan.pyと同じ)
_INITIAL_RMAX_MM = 300
_RMAX_MARGIN = 1.2


class _ScanBatchListener(Node):
    def __init__(
        self,
        topic: str,
        state_topic: str,
        out_queue: "queue.Queue[tuple[int, float, float]]",
        clear_queue: "queue.Queue[int]",
    ) -> None:
        super().__init__("scan_batch_viewer")
        self._q = out_queue
        self._clear_q = clear_queue
        self.create_subscription(PointCloud, topic, self._on_scan_batch, 10)
        self.create_subscription(String, state_topic, self._on_state, 10)

    def _on_scan_batch(self, msg: PointCloud) -> None:
        channels = {c.name: c.values for c in msg.channels}
        angles = channels.get("angle", [])
        distances = channels.get("distance_mm", [])
        origins = channels.get("origin", [])
        n = min(len(angles), len(distances), len(origins))
        for i in range(n):
            self._q.put((int(round(origins[i])), float(angles[i]), float(distances[i])))

    def _on_state(self, msg: String) -> None:
        origin_str, _, state_name = msg.data.partition(":")
        if state_name == "CALIBRATING":
            try:
                self._clear_q.put(int(origin_str))
            except ValueError:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description="scan_batchをmatplotlib WebAggで極座標表示する")
    parser.add_argument(
        "--topic", default="/pdu/sonar_radar/scan_batch",
        help="hakoniwa_pdu_rosはpdu_to_ros方向のトピックを常に/pdu配下へ"
        "マッピングする(/pdu名前空間はPDU由来トピック専用の予約領域のため)。"
        "config/raspi5/ros_bindings_scan_batch.jsonのtopic指定に関わらず、"
        "実際のトピック名は/pdu/sonar_radar/scan_batchになる",
    )
    parser.add_argument("--host", default="0.0.0.0", help="WebAggサーバーのbindアドレス")
    parser.add_argument("--port", type=int, default=8988)
    parser.add_argument(
        "--max-points", type=int, default=20000,
        help="origin毎に保持する最新点数の安全上限(既定20000、bridge/plot_scan.py"
        "と同じ考え方)。1回のスキャンセッション全体を表示する運用方針のため、"
        "通常の使用でこの上限に達することは想定していない",
    )
    parser.add_argument(
        "--gear-ratio", type=float, default=3.0,
        help="bridge/radar_base.pyのgear_ratio(既定3)と合わせること。"
        "angle(モーター生角度)からdome_angle相当への変換に使う",
    )
    parser.add_argument(
        "--state-topic", default="/pdu/sonar_radar/state",
        help="--topicと同じ理由でconfig/raspi5/ros_bindings_scan_batch.jsonの"
        "topic指定に関わらず実際は/pdu配下になる",
    )
    args, ros_args = parser.parse_known_args()

    matplotlib.rcParams["webagg.address"] = args.host
    matplotlib.rcParams["webagg.port"] = args.port
    matplotlib.rcParams["webagg.open_in_browser"] = False

    rclpy.init(args=ros_args)
    q: "queue.Queue[tuple[int, float, float]]" = queue.Queue()
    clear_q: "queue.Queue[int]" = queue.Queue()
    node = _ScanBatchListener(args.topic, args.state_topic, q, clear_q)
    spin_thread = threading.Thread(target=rclpy.spin, args=(node,), daemon=True)
    spin_thread.start()

    series: dict[int, dict[str, list[float]]] = {}
    scatters: dict[int, "plt.PathCollection"] = {}

    fig = plt.figure()
    ax = fig.add_subplot(projection="polar")
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)  # 上から見て時計回り(bridge/plot_scan.pyと同じ理由)
    rmax_state = {"value": _INITIAL_RMAX_MM}
    ax.set_rmax(rmax_state["value"])
    ax.set_title(f"sonar_radar scan_batch ({args.topic})")

    def _update(_frame):
        while True:
            try:
                clear_origin = clear_q.get_nowait()
            except queue.Empty:
                break
            series[clear_origin] = {"theta": [], "r": []}

        rmax_grew = False
        while True:
            try:
                origin, raw_angle_deg, distance_mm = q.get_nowait()
            except queue.Empty:
                break
            dome_angle_deg = -raw_angle_deg / args.gear_ratio
            s = series.setdefault(origin, {"theta": [], "r": []})
            clipped = min(distance_mm, _ABS_MAX_DISTANCE_MM)
            s["theta"].append(math.radians(dome_angle_deg))
            s["r"].append(clipped)
            if clipped > rmax_state["value"]:
                rmax_state["value"] = clipped
                rmax_grew = True
            if len(s["theta"]) > args.max_points:
                del s["theta"][: len(s["theta"]) - args.max_points]
                del s["r"][: len(s["r"]) - args.max_points]

        if rmax_grew:
            ax.set_rmax(rmax_state["value"] * _RMAX_MARGIN)

        artists = []
        for i, (origin, s) in enumerate(series.items()):
            if origin not in scatters:
                color = _COLORS[i % len(_COLORS)]
                scatters[origin] = ax.scatter([], [], s=8, color=color, label=f"origin={origin}")
                ax.legend(loc="upper right")
            scatters[origin].set_offsets(list(zip(s["theta"], s["r"])))
            artists.append(scatters[origin])
        return artists

    anim = animation.FuncAnimation(fig, _update, interval=200, blit=False, cache_frame_data=False)

    print(
        f"[scan_batch_viewer] 監視中... (topic={args.topic}) "
        f"http://<このホストのIP>:{args.port}/ をブラウザで開いてください",
    )
    try:
        plt.show()
    finally:
        rclpy.shutdown()
        node.destroy_node()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
