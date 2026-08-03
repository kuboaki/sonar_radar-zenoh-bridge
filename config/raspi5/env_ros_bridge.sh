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

# 【2026-08-04の教訓】~/.local/lib/hakoniwa-pdu-endpoint/python/hakoniwa_pdu_endpoint/
# にはlibhakoniwa_pdu_endpoint.soしか置かれておらず、その依存先libzenohc.soは
# 同梱されていない(install.bash側の既知の欠落)。そのため上のsource文で
# /opt/ros/jazzy/setup.bashを読み込むと、そちらが持つ別ビルドのzenoh-c
# (/opt/ros/jazzy/opt/zenoh_cpp_vendor/lib/libzenohc.so、rmw_zenoh用に
# 別途ビルドされた別バージョン)がLD_LIBRARY_PATH経由で拾われてしまい、
# 当方のcomm_zenoh.cppをビルドした時のzenoh-cとABIが食い違う。この状態で
# ZenohComm::send()を呼ぶ(=start/stop等をZenohへ転送する)と
# "stack smashing detected"で毎回ではないが再現性高くクラッシュする実害が
# あった(hakoniwa_pdu_rosブリッジ経由のROS start/stop注入テストで発見)。
# 当方が実際にビルドしたlibzenohc.so
# (~/Projects/hakoniwa-pdu-endpoint/build/_deps/zenohc-build/release/target/release)
# を明示的に先頭へ入れ、ROS側の同名ライブラリより先に解決させることで回避する。
# 根本対策としては、hakoniwa-pdu-endpoint側のinstall.bashがlibzenohc.soも
# .localへ同梱するよう直すべき(未対応、上流への報告も未実施)。
export LD_LIBRARY_PATH="$HOME/Projects/hakoniwa-pdu-endpoint/build/_deps/zenohc-build/release/target/release:$HOME/.local/lib/hakoniwa-pdu-endpoint/python/hakoniwa_pdu_endpoint:/usr/local/hakoniwa/lib:${LD_LIBRARY_PATH:-}"
