#!/bin/bash
# demo_real_follower.bash — 実機側をROS駆動(--no-starter)で起動する。
# 実機の物理starterボタンを使わず、ROS(Pi5のhakoniwa_pdu_rosブリッジ経由、
# config/raspi5/demo_ros_start.bash・demo_ros_stop.bash参照)や、もう一方の
# leader機からのstart/stop/detected受信だけでSCANNINGへ進む構成。
# 旋回モーター(libspikehat)は実際に駆動する(--real-radar-base)。
#
# 既定はfollower(--leaderなし、マーカー検出/方向反転の権限を持たない。
# 自機のマーカー検出自体は常に有効で、detected受信はis_leader/is_starterの
# ガード無しに受け付ける設計)。ROSからstart/stopを注入する2台構成では、
# 実機・SIMのどちらかが必ずleaderを持つ必要がある(両方followerだと誰も
# マーカー検出/反転をしないためSCANNINGがタイムアウトしSCAN_FAILEDになる、
# 2026-08-04に実地で確認)。LEADER=1環境変数でどちらをleaderにするか
# その場で交換できる:
#   LEADER=1 bash bridge/demo_real_follower.bash   # 実機をleaderにする
#   bash bridge/demo_real_follower.bash             # 実機はfollowerのまま
#                                                    # (Mac側をLEADER=1にする)
# starterは常に--no-starter(ROS駆動なので、leader/followerどちらでも
# 物理starterは使わない)。
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

LEADER_FLAG=()
ROLE="follower"
if [ "${LEADER:-0}" = "1" ]; then
  LEADER_FLAG=(--leader)
  ROLE="leader"
fi

echo "=== run_real.py (${ROLE}, origin=2, 実機ハードウェア, --no-starter) ==="
# LEADER_FLAGが空配列のとき、bashのバージョン/ビルドによっては
# set -u下で"${LEADER_FLAG[@]}"が unbound variable になることがある
# (Mac同梱のbash 5.3で実際に発生を確認)。${arr[@]+"${arr[@]}"}は
# 空配列でも未設定変数でも安全に展開できる定番の書き方。
exec python3 run_real.py \
  --origin 2 \
  ${LEADER_FLAG[@]+"${LEADER_FLAG[@]}"} \
  --no-starter \
  --real-radar-base \
  --config ../config/raspi4b/endpoint_zenoh.json \
  --calibration-timeout 60 \
  --timeout 90
