#!/bin/bash
# run_scan_batch_viewer.bash — ros/scan_batch_viewer.py をPi5で起動する
# (rclpy購読 + matplotlib WebAggで/pdu/sonar_radar/scan_batchを極座標表示)。
#
# 前提として、以下2つが別ターミナルで動いていること:
#   1. config/raspi5/run_ros_bridge_scan_batch.bash
#      (hakoniwa_pdu_rosのscan_batch/state中継)
#   2. config/raspi5/run_sonar_radar_ros_bridge.bash
#      (scan集約・scan_batch publish)
#
# rclpy標準のsubscriberしか使わない(hakoniwa_pdu_endpoint/hakoniwa_pdu
# には依存しない)ため、ROS2環境のsourceだけで動く。
#
# 使い方(Raspberry Pi 5で実行すること):
#   bash config/raspi5/run_scan_batch_viewer.bash [--port 8988] [追加の引数...]
#   起動後、同じLAN上の任意のブラウザで http://<Pi5のIP>:8988/ を開く

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"
source /opt/ros/jazzy/setup.bash

echo "=== scan_batch_viewer.py (matplotlib WebAgg) ==="
echo "(Ctrl-Cで停止。ブラウザで http://<このホストのIP>:8988/ を開くこと)"

exec python3 ros/scan_batch_viewer.py "$@"
