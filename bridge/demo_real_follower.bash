#!/bin/bash
# demo_real_follower.bash — 実機側(follower)を起動する。実機の物理starter
# ボタンを使わず、ROS(Pi5のhakoniwa_pdu_rosブリッジ経由、
# config/raspi5/demo_ros_start.bash・demo_ros_stop.bash参照)や、もう一方の
# leader機からのstart/stop/detected受信だけでSCANNINGへ進む構成。
# 旋回モーター(libspikehat)は実際に駆動する(--real-radar-base)。
#
# demo_real_leader.bashとの違いは、--leaderを付けない(マーカー検出/方向
# 反転の権限を持たない。自機のマーカー検出自体は常に有効で、detected受信は
# is_leader/is_starterのガード無しに受け付ける設計)のと、--real-starterの
# 代わりに明示的な--no-starterを使うこと(demo_mac_follower.bash・
# demo_hako_follower.bashと同じ「followerはstarter操作なし」という設計)。
#
# 起動前に必ずcleanup.bashを実行し、旧driver等の残存プロセスが無い
# 状態から始める(手作業で忘れがちなため、ここで明示的に組み込む)。
#
# 使い方(実機=Raspberry Piで実行すること):
#   bash bridge/demo_real_follower.bash
#
# (ROSからstart/stopを注入する場合は、Pi5で別途
#  config/raspi5/run_ros_bridge.bash を起動しておくこと)

set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

echo "=== cleanup ==="
bash cleanup.bash --skip-watchers

# 実機用venv(hakoniwa-pdu等が入っている)。手作業でactivateを忘れる事故が
# あったため、ここで自動化する。
source "${SCRIPT_DIR}/../.venv/bin/activate"
source env.sh

echo "=== run_real.py (follower, origin=2, 実機ハードウェア, --no-starter) ==="
exec python3 run_real.py \
  --origin 2 \
  --no-starter \
  --real-radar-base \
  --config ../config/raspi4b/endpoint_zenoh.json \
  --calibration-timeout 60 \
  --timeout 90
