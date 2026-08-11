#!/bin/bash
# run_ros_bridge_scan_batch.bash — hakoniwa_pdu_ros の bridge ノードを起動する。
#
# Zenohの scan_batch PDU(sensor_msgs/PointCloud、bridge/sonar_radar_ros_bridge.py が
# scanを蓄積してpublishする)を、ROS2の /sonar_radar/scan_batch トピックへ中継する
# (config/raspi5/ros_bindings_scan_batch.json 参照)。これが動いていないと、
# ros/scan_batch_viewer.py にデータが届かない。
#
# start/stop中継用のrun_ros_bridge.bashとは別プロセス(通知方向がpdu_to_ros/
# ros_to_pduで逆かつ高頻度データ系のため、意図的に独立させている。両方同時に
# 動かして構わない)。
#
# フォアグラウンドで動かし、Ctrl-Cで止める想定(run_ros_bridge.bashと同じ流儀)。
#
# 使い方(Raspberry Pi 5で実行すること):
#   bash config/raspi5/run_ros_bridge_scan_batch.bash

# 【注意】set -u(nounset)は使わない(run_ros_bridge.bashと同じ理由、
# /opt/ros/jazzy/setup.bashがstrict modeを想定していないため)。
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"
source "${SCRIPT_DIR}/env_ros_bridge.sh"

echo "=== hakoniwa_pdu_ros bridge (scan_batch中継) ==="
echo "(Ctrl-Cで停止。動いている間、ros/scan_batch_viewer.py が使える)"

exec ros2 run hakoniwa_pdu_ros bridge --config "${SCRIPT_DIR}/ros_bindings_scan_batch.json"
