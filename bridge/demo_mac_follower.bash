#!/bin/bash
# demo_mac_follower.bash — 2台構成デモ、Mac側(follower)を起動する。
#
# 実機(leader、demo_real_leader.bash)と組み合わせて使う。followerは
# starter操作なしで、radar/starter/startの受信のみでSCANNINGへ直接
# 遷移する設計(README.md「実機とシミュレータの2台構成」参照)。
#
# 起動前に必ずcleanup.bashを実行し、旧driver等の残存プロセスが無い
# 状態から始める(手作業で忘れがちなため、ここで明示的に組み込む)。
#
# 使い方:
#   bash bridge/demo_mac_follower.bash

set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

echo "=== cleanup ==="
bash cleanup.bash --skip-watchers

source env.sh
source ~/Projects/sonar_radar/.venv/bin/activate

echo "=== run_real.py (follower, origin=5) ==="
exec python3 run_real.py \
  --origin 5 \
  --calibration-timeout 60 \
  --timeout 90
