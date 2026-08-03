# config/raspi5/env_ros_bridge.sh — Raspberry Pi 5 で hakoniwa_pdu_ros の
# bridgeノードを動かすために必要な環境変数をまとめたもの。
# source して使う: `source config/raspi5/env_ros_bridge.sh`
#
# 前提:
#   - ROS2(jazzy)が /opt/ros/jazzy にインストール済み
#   - hakoniwa-pdu-ros が ~/Projects/ros2_ws で colcon build 済み
#   - hakoniwa-pdu(pip, std_msgs/Bool等の変換コード)が
#     ~/Projects/.venv に導入済み(このvenv自体はactivateしなくてよい。
#     PYTHONPATHへ直接site-packagesを足すだけで足りる)
#   - hakoniwa-pdu-endpoint(Zenoh通信層)が
#     ~/.local/lib/hakoniwa-pdu-endpoint/python にビルド済み
#
# bridge/env.sh(Mac/Pi4でsonar_radar/sonar_radar_simを動かす用)とは別物。
# こちらはPi5でhakoniwa_pdu_ros経由のROS中継を動かす用。

source /opt/ros/jazzy/setup.bash
source ~/Projects/ros2_ws/install/setup.bash

export HAKONIWA_PDU_ENDPOINT_PYTHON_PATH="$HOME/.local/lib/hakoniwa-pdu-endpoint/python"
export PYTHONPATH="$HOME/Projects/.venv/lib/python3.12/site-packages:${PYTHONPATH:-}"
export LD_LIBRARY_PATH="$HOME/.local/lib/hakoniwa-pdu-endpoint/python/hakoniwa_pdu_endpoint:/usr/local/hakoniwa/lib:${LD_LIBRARY_PATH:-}"
