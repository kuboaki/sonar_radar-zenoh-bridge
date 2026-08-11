#!/bin/bash
# run_sonar_radar_ros_bridge.bash — bridge/sonar_radar_ros_bridge.py を
# Pi5で起動する(Zenoh専用、rclpy非依存のscan集約プロセス)。
#
# scan(実機/SIM双方から届く個々のスキャンサンプル)をscan_batch_size件
# たまるかstop受信時にscan_batchとしてまとめてpublishする
# (docs/sonar_radar_zenoh_bridge.asta の pdu_ros_bridge::sonar_radar_ros_bridge
# 参照)。config/raspi5/run_ros_bridge_scan_batch.bash(hakoniwa_pdu_rosの
# scan_batch/state中継)と対で使う(どちらもフォアグラウンド、別ターミナル)。
#
# bridge/env.sh(hakoniwa_pdu_endpoint用のPYTHONPATH/LD_LIBRARY_PATH)に加え、
# hakoniwa_pdu(sensor_msgs/PointCloud等の変換コード)がPi5では
# ~/Projects/.venv に入っているため、そちらもPYTHONPATHに追加する必要がある。
# 【2026-08-12の教訓】env_ros_bridge.sh(hakoniwa_pdu_ros bridge専用)と同じ
# 順序(venvパスを先頭に追加)で結合すると、hakoniwa_pdu_endpointの実装が
# venv側の別ビルド(libconductor.so.1依存、Pi5には無い)で誤ってシャドー
# イングされ、importに失敗する。bridge/env.sh側のPYTHONPATHを優先させる
# 順序(venvパスは末尾に追加)にする必要がある。加えて、bridge/env.sh
# (Linux分岐)のLD_LIBRARY_PATHにはlibconductor.so.1を含む
# /usr/local/hakoniwa/lib が含まれていないため、それも明示的に追加する。
#
# 使い方(Raspberry Pi 5で実行すること):
#   bash config/raspi5/run_sonar_radar_ros_bridge.bash [追加の引数...]
#   (例: bash config/raspi5/run_sonar_radar_ros_bridge.bash --scan-batch-size 15)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

cd "${REPO_ROOT}"
source bridge/env.sh
export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}:/usr/local/hakoniwa/lib"
export PYTHONPATH="${PYTHONPATH:-}:$HOME/Projects/.venv/lib/python3.12/site-packages"

echo "=== sonar_radar_ros_bridge.py (scan集約) ==="
echo "(Ctrl-Cで停止。config/raspi5/run_ros_bridge_scan_batch.bash が別ターミナルで動いていること)"

exec python3 bridge/sonar_radar_ros_bridge.py --config config/raspi5/endpoint_zenoh.json "$@"
