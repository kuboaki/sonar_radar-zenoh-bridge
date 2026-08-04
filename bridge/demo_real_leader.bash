#!/bin/bash
# demo_real_leader.bash — 実機側(leader)を起動する。動作シナリオ1(実機単体)
# と、実機+Macの2台構成デモの両方で使う。実機の物理starterボタン・
# 旋回モーター(libspikehat)を実際に駆動する。
#
# キャリブレーションはマシン間協調を行わずローカルで完結するため、
# 実機単体でも2台構成でも同じコマンドでよい(参加者集合の指定は不要)。
#
# 起動前に必ずcleanup.bashを実行し、旧driver等の残存プロセスが無い
# 状態から始める(手作業で忘れがちなため、ここで明示的に組み込む)。
#
# 使い方(実機=Raspberry Piで実行すること):
#   bash bridge/demo_real_leader.bash
#
# (2台構成のときはMac側でdemo_mac_follower.bashも動かしておくこと)

set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

echo "=== cleanup ==="
bash cleanup.bash --skip-watchers

# 実機用venv(hakoniwa-pdu等が入っている)。手作業でactivateを忘れる事故が
# あったため、ここで自動化する。
source "${SCRIPT_DIR}/../.venv/bin/activate"
source env.sh

echo "=== run_real.py (leader, origin=2, 実機ハードウェア) ==="
exec python3 run_real.py \
  --origin 2 \
  --leader \
  --real-starter \
  --real-radar-base \
  --config ../config/raspi4b/endpoint_zenoh.json \
  --calibration-timeout 60 \
  --timeout 90
