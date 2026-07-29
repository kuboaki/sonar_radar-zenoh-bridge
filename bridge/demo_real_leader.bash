#!/bin/bash
# demo_real_leader.bash — 2台構成デモ、実機側(leader)を起動する。
#
# Mac側(follower、demo_mac_follower.bash)と組み合わせて使う。実機の
# 物理starterボタン・旋回モーター(libspikehat)を実際に駆動する。
#
# 起動前に必ずcleanup.bashを実行し、旧driver等の残存プロセスが無い
# 状態から始める(手作業で忘れがちなため、ここで明示的に組み込む)。
#
# 使い方(実機=Raspberry Piで実行すること):
#   bash bridge/demo_real_leader.bash

set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

echo "=== cleanup ==="
bash cleanup.bash --skip-watchers

source env.sh

echo "=== run_real.py (leader, origin=2, 実機ハードウェア) ==="
exec python3 run_real.py \
  --origin 2 \
  --leader \
  --real-starter \
  --real-radar-base \
  --participants 2,5 \
  --config ../config/raspi4b/endpoint_zenoh.json \
  --calibration-timeout 60 \
  --timeout 90
