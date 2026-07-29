#!/bin/bash
# demo_hako_leader.bash — Mac(シミュレータ)をleaderとして起動する。
# 動作シナリオ2(シミュレータ単体でのstart確認)用。MuJoCoビューアの
# Spaceキー操作をstarterとして使う(--hako-starter、plantのforce_sensor
# PDU経由)。
#
# 実機をfollowerにした2台構成でも使える。キャリブレーションはマシン間
# 協調を廃止しローカル完結になったため、実機とMacの起動順序は自由。
#
# 【前提、この2つを別ターミナルで先に済ませておくこと】
# 1. Hakoniwa plant(ビューア付き)を起動しておく:
#      cd ~/Projects/hakoniwa-mujoco-robots
#      MJPYTHON="$(pwd)/.venv/bin/mjpython" bash run-hakopy.bash \
#        ~/Projects/sonar_radar/sim/sonar_radar_hako.py --viewer
# 2. このスクリプト実行→'SonarRadarZenohBridgeController'登録完了の
#    表示後、さらに別ターミナルで `hako-cmd start` を実行する。
#
# plant/ビューアが既に動いている前提のため、他のdemo_*.bashと違い
# cleanup.bashは自動実行しない(呼ぶとplant/ビューアも巻き込んで
# 止めてしまうため)。残存プロセスが疑わしい場合は、事前に手動で
# `bash bridge/cleanup.bash --dry-run` を確認すること。
#
# 起動後、状態が WAIT_FOR_START_PRESS になったら、MuJoCoビューアの
# ウィンドウでSpaceキーを押すこと(押す→離すでSCANNINGへ進む)。
#
# 使い方(Macで実行すること):
#   bash bridge/demo_hako_leader.bash

set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MUJOCO_ROBOTS_DIR="$(cd "${SCRIPT_DIR}/../../hakoniwa-mujoco-robots" && pwd)"

source "${SCRIPT_DIR}/env.sh"

echo "=== run_hako.py (leader, origin=5, --hako-starter) ==="
echo "(plant/ビューアが別ターミナルで起動済みであること。登録完了後、"
echo " 別ターミナルで hako-cmd start を実行すること)"

cd "${MUJOCO_ROBOTS_DIR}"
exec bash run-hakopy.bash "${SCRIPT_DIR}/run_hako.py" \
  --origin 5 \
  --leader \
  --hako-starter \
  --calibration-timeout 60 \
  --timeout 90
