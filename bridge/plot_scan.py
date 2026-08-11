#!/usr/bin/env python3
"""plot_scan.py — scanチャンネルのデータをリアルタイムに極座標プロットする。

watch_all.py の scan 受信パターン(subscribe_on_recv_callback_by_name)を
土台に、angle/dome_angle/distance_mm を極座標(半径=distance_mm、
角度=dome_angle)で可視化する。origin(実機/シム/複数台)ごとに別系列・
別色で表示するため、ROSブリッジ経由での実機/SIM重畳可視化(#1b)に
発展させる際の土台にもなる。

Zenohの受信コールバックは内部スレッドから非同期に呼ばれる(README
「ドライバスクリプトの受信方式について」参照)ため、コールバックでは
queueに積むだけにし、matplotlib側(メインスレッド)のFuncAnimationで
定期的に取り出して描画する。

使い方:
  python3 bridge/plot_scan.py [--config path/to/endpoint_zenoh.json] [--max-points N]

(stderrにはhakoniwa_pdu_endpointライブラリの"WARNING: No subscribers
found..."が出るため、watch_all.py等と同様2>/dev/nullで分離すること)
"""

from __future__ import annotations

import argparse
import math
import os
import queue
import struct
import sys

import matplotlib.animation as animation
import matplotlib.pyplot as plt

from hakoniwa_pdu_endpoint.c_endpoint import Endpoint, PduKey

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_CONFIG = os.path.join(_HERE, "..", "config", "mac", "endpoint_zenoh.json")
_ROBOT = "Radar"
_SCAN_STRUCT = struct.Struct("<Bidi")  # origin(uint8), angle(int32), dome_angle(float64), distance_mm(int32)

_ABS_MAX_DISTANCE_MM = 5000  # 異常値のクリップ上限(実機/シムどちらでもここまでは届かない想定)
_INITIAL_RMAX_MM = 300  # 半径軸の初期値(実機センサーの有効レンジ50〜300mmに合わせる)
_RMAX_MARGIN = 1.2  # 観測最大値を超えたら、この倍率で軸を広げる(縮小はしない)
_COLORS = ["tab:blue", "tab:orange", "tab:green", "tab:red", "tab:purple"]


def main() -> int:
    parser = argparse.ArgumentParser(description="scanチャンネルをリアルタイムに極座標プロットする")
    parser.add_argument("--config", default=_DEFAULT_CONFIG, help="endpoint_zenoh.json のパス")
    parser.add_argument("--max-points", type=int, default=200, help="origin毎に保持する最新点数")
    args = parser.parse_args()

    endpoint = Endpoint("sonar_radar_zenoh_bridge_plot_scan", "inout")
    endpoint.open(args.config)
    endpoint.start()
    endpoint.post_start()

    _q: "queue.Queue[tuple[int, float, int]]" = queue.Queue()

    def _on_scan(_key, payload: bytes) -> None:
        try:
            origin, _angle, dome_angle, distance_mm = _SCAN_STRUCT.unpack(payload)
        except struct.error:
            return
        _q.put((origin, dome_angle, distance_mm))

    endpoint.subscribe_on_recv_callback_by_name(PduKey(robot=_ROBOT, pdu="scan"), _on_scan)

    print(f"[plot_scan] 監視中... (config={args.config}) ウィンドウを閉じると終了します", file=sys.stderr)

    # origin毎の点列(角度[rad]・距離[mm])を保持
    series: dict[int, dict[str, list[float]]] = {}
    scatters: dict[int, "plt.PathCollection"] = {}

    fig = plt.figure()
    ax = fig.add_subplot(projection="polar")
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)  # 上から見て時計回り(コンパス表示と同じ向き)。既定は反時計回りで左右反転して見える
    rmax_state = {"value": _INITIAL_RMAX_MM}
    ax.set_rmax(rmax_state["value"])
    ax.set_title("sonar_radar scan (dome_angle / distance_mm)")

    def _update(_frame):
        rmax_grew = False
        while True:
            try:
                origin, dome_angle_deg, distance_mm = _q.get_nowait()
            except queue.Empty:
                break
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

    anim = animation.FuncAnimation(fig, _update, interval=100, blit=False, cache_frame_data=False)

    try:
        plt.show()
    finally:
        endpoint.stop()
        endpoint.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
