#!/bin/bash
# demo_hako_follower.bash — Mac(シミュレータ)をfollowerとして起動する。
# 実機+Macの2台構成デモ用(demo_real_leader.bashの相方)。followerは
# starter操作なしで、radar/starter/startの受信のみでSCANNINGへ
# 直接遷移する設計のため、--hako-starterは指定しない。
#
# 【前提、この2つを別ターミナルで先に済ませておくこと】
# 1. Hakoniwa plant(ビューア付き)を起動しておく:
#      cd ~/Projects/hakoniwa-mujoco-robots
#      MJPYTHON="$(pwd)/.venv/bin/mjpython" bash run-hakopy.bash \
#        ~/Projects/sonar_radar/sim/sonar_radar_hako.py --viewer
# 2. このスクリプト実行→'SonarRadarZenohBridgeController'登録完了の
#    表示後、まず実機(demo_real_leader.bash)を先に起動し、それから
#    別ターミナルで `hako-cmd start` を実行する(実機のプロセスは
#    起動したら止められないのに対し、hako-cmd startは任意のタイミング
#    で押せる唯一の開始トリガーなので、常にこちらを最後にする。
#    README.mdの「実機とシミュレータの2台構成」参照)。
#
# plant/ビューアが既に動いている前提のため、他のdemo_*.bashと違い
# cleanup.bashは自動実行しない(呼ぶとplant/ビューアも巻き込んで
# 止めてしまうため)。残存プロセスが疑わしい場合は、事前に手動で
# `bash bridge/cleanup.bash --dry-run` を確認すること。
#
# 使い方(Macで実行すること):
#   bash bridge/demo_hako_follower.bash

set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MUJOCO_ROBOTS_DIR="$(cd "${SCRIPT_DIR}/../../hakoniwa-mujoco-robots" && pwd)"

source "${SCRIPT_DIR}/env.sh"

echo "=== run_hako.py (follower, origin=5, participants=2,5) ==="
echo "(plant/ビューアが別ターミナルで起動済みであること。登録完了後、"
echo " まず実機(demo_real_leader.bash)を起動し、それから別ターミナルで"
echo " hako-cmd start を実行すること)"

cd "${MUJOCO_ROBOTS_DIR}"
exec bash run-hakopy.bash "${SCRIPT_DIR}/run_hako.py" \
  --origin 5 \
  --participants 2,5 \
  --calibration-timeout 60 \
  --timeout 90
