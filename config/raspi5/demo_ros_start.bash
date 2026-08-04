#!/bin/bash
# demo_ros_start.bash — ROS2から/sonar_radar/start_cmdをpublishし、
# 実機・SIM(hakoniwa_pdu_rosブリッジ経由でZenohのstart PDUへ中継される側)を
# WAIT_FOR_START_PRESS→SCANNINGへ進める。
#
# 実機・SIMのどちらが動いていても(あるいは両方でも)同じstart PDUが届く
# (originを区別しないチャンネルのため)。事前に run_ros_bridge.bash を
# 別ターミナルで動かしておくこと。
#
# 使い方(Raspberry Pi 5で実行すること):
#   bash config/raspi5/demo_ros_start.bash

# set -uは使わない(/opt/ros/jazzy/setup.bashが未定義変数を参照するため)。
set -e
source /opt/ros/jazzy/setup.bash

echo "=== ROS start_cmd を1回publish ==="
timeout 15 ros2 topic pub --once /sonar_radar/start_cmd std_msgs/msg/Bool "{data: true}"
