#!/bin/bash
# demo_real_leader.bash — 実機側(leader)を起動する。動作シナリオ1(実機単体)
# と、実機+Macの2台構成デモの両方で使う。実機の物理starterボタン・
# 旋回モーター(libspikehat)を実際に駆動する。
#
# 起動前に必ずcleanup.bashを実行し、旧driver等の残存プロセスが無い
# 状態から始める(手作業で忘れがちなため、ここで明示的に組み込む)。
#
# 使い方(実機=Raspberry Piで実行すること):
#   bash bridge/demo_real_leader.bash solo   # 動作シナリオ1: 実機単体(participants=2のみ)
#   bash bridge/demo_real_leader.bash        # 実機+Macの2台構成(既定、participants=2,5)
#
# (2台構成のときはMac側でdemo_mac_follower.bashも動かしておくこと)

set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

MODE="${1:-pair}"
case "$MODE" in
  solo) PARTICIPANTS="2" ;;
  pair) PARTICIPANTS="2,5" ;;
  *)
    echo "Usage: $0 [solo|pair]" >&2
    exit 1
    ;;
esac

echo "=== cleanup ==="
bash cleanup.bash --skip-watchers

source env.sh

echo "=== run_real.py (leader, origin=2, 実機ハードウェア, participants=${PARTICIPANTS}) ==="
exec python3 run_real.py \
  --origin 2 \
  --leader \
  --real-starter \
  --real-radar-base \
  --participants "${PARTICIPANTS}" \
  --config ../config/raspi4b/endpoint_zenoh.json \
  --calibration-timeout 60 \
  --timeout 90
