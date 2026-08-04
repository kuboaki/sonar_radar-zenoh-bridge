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

# 【2026-08-04の教訓、2026-08-04に根本修正済み】以前はここでlibzenohc.soの
# ビルドディレクトリを明示的にLD_LIBRARY_PATHへ足す回避策を入れていた。
# 原因は~/.local/lib/hakoniwa-pdu-endpoint/python/hakoniwa_pdu_endpoint/に
# libhakoniwa_pdu_endpoint.soしか置かれておらず依存先libzenohc.soが
# 同梱されていなかったこと(install.bash側の既知の欠落)。/opt/ros/jazzy/
# setup.bashが読み込むROS自前の別バージョンzenoh-c
# (/opt/ros/jazzy/opt/zenoh_cpp_vendor/lib/libzenohc.so)がLD_LIBRARY_PATH
# 経由で誤って拾われ、ABI不整合で"stack smashing detected"が起きていた。
# hakoniwa-pdu-endpoint側でlibzenohc.soをlibhakoniwa_pdu_endpoint.soと
# 同じディレクトリへ同梱するよう修正したため(install.bashのZenoh対応、
# 別途対応)、下のLD_LIBRARY_PATHが指す.localディレクトリ自体に正しい
# libzenohc.soが同梱されており、ビルドディレクトリを明示的に指す回避策は
# 不要になった。
export LD_LIBRARY_PATH="$HOME/.local/lib/hakoniwa-pdu-endpoint/python/hakoniwa_pdu_endpoint:/usr/local/hakoniwa/lib:${LD_LIBRARY_PATH:-}"
