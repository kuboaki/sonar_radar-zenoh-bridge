#!/bin/bash
# run_ros_bridge.bash — hakoniwa_pdu_ros の bridge ノードを起動する。
#
# ROS2の/sonar_radar/start_cmd・/sonar_radar/stop_cmd(std_msgs/Bool)を
# Zenoh経由でstart/stop PDUへ中継する(config/raspi5/ros_bindings_start_stop.json、
# config/raspi5/env_ros_bridge.sh参照)。これが動いていないと、demo_ros_start.bash・
# demo_ros_stop.bashを実行しても実機・SIMのどちらにも届かない。
#
# フォアグラウンドで動かし、Ctrl-Cで止める想定(bridge/demo_*.bashと同じ流儀)。
# バックグラウンド常駐させたい場合は、このスクリプトをそのままnohup/setsidで包むこと。
#
# 使い方(Raspberry Pi 5で実行すること):
#   bash config/raspi5/run_ros_bridge.bash

# 【注意】set -u(nounset)は使わない。/opt/ros/jazzy/setup.bashが
# 未定義変数を参照する箇所があり、-u有効時にそこで落ちてしまうため
# (ROS2のsetup.bash自体がstrict modeを想定して書かれていない)。
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"
source "${SCRIPT_DIR}/env_ros_bridge.sh"

echo "=== hakoniwa_pdu_ros bridge (start/stop中継) ==="
echo "(Ctrl-Cで停止。動いている間、demo_ros_start.bash・demo_ros_stop.bashが使える)"

exec ros2 run hakoniwa_pdu_ros bridge --config "${SCRIPT_DIR}/ros_bindings_start_stop.json"
