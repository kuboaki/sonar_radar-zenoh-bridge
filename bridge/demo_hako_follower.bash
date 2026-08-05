#!/bin/bash
# demo_hako_follower.bash — Mac(シミュレータ)をROS駆動(--no-starter)で
# 起動する。starter操作なしで、radar/starter/startの受信のみでSCANNINGへ
# 直接遷移する設計のため、--hako-starterは指定せず、明示的に--no-starterを
# 付ける(is_starterを省略した場合の既定値はis_leaderと同値でどのみち
# falseになるが、「明示的な方がよい」という方針に合わせている)。
#
# 既定はfollower(--leaderなし)。ROSからstart/stopを注入する2台構成では、
# 実機・SIMのどちらかが必ずleaderを持つ必要がある(両方followerだと誰も
# マーカー検出/反転をしないためSCANNINGがタイムアウトしSCAN_FAILEDになる、
# 2026-08-04に実地で確認)。LEADER=1環境変数でどちらをleaderにするか
# その場で交換できる(bridge/demo_real_follower.bashと同じ仕組み):
#   LEADER=1 bash bridge/demo_hako_follower.bash   # SIMをleaderにする
#   bash bridge/demo_hako_follower.bash             # SIMはfollowerのまま
#                                                    # (実機側をLEADER=1にする)
#
# 【2026-08-05の教訓】SIMがleaderのとき、既定の--scanning-timeout(8秒、
# 実機のケーブル巻き込み防止に合わせた値)では、SIM自身が自分のマーカーを
# 検出しきれずSCAN_FAILEDになることがあった。SIMには実機のようなケーブル
# 巻き込みリスクが無い(sonar_radar_app.pyのdocstring参照)ため、SIM側だけ
# 長めに設定してよい。SCANNING_TIMEOUT環境変数で上書きできる(既定20秒):
#   SCANNING_TIMEOUT=25 LEADER=1 bash bridge/demo_hako_follower.bash
#
# 長時間スキャンを試すには、既定の--timeout(全体のタイムアウト、90秒固定)
# もすぐ尽きてしまう(SCAN_FAILEDではなく単にプロセス全体がタイムアウト
# して終わる)。TIMEOUT環境変数で延ばせる:
#   TIMEOUT=600 SCANNING_TIMEOUT=25 LEADER=1 bash bridge/demo_hako_follower.bash
#
# キャリブレーションはマシン間協調を廃止しローカル完結になったため、
# 実機とMacの起動順序は自由(以前はキャリブレーション待ち合わせのため
# 実機を先に起動する必要があったが、その制約は無くなった)。ただし
# `hako-cmd start`を押すまでMac側のbroker.open()(Zenoh購読)は開かない
# ため、実機側でstarterボタンを押す(スキャン開始する)のは、Macの
# `hako-cmd start`を済ませた後にすること(そうしないとMacがstart
# publishを取りこぼす)。
#
# 【前提、この2つを別ターミナルで先に済ませておくこと】
# 1. Hakoniwa plant(ビューア付き)を起動しておく:
#      cd ~/Projects/hakoniwa-mujoco-robots
#      MJPYTHON="$(pwd)/.venv/bin/mjpython" bash run-hakopy.bash \
#        ~/Projects/sonar_radar/sim/sonar_radar_hako.py --viewer
# 2. このスクリプト実行→'SonarRadarZenohBridgeController'登録完了の
#    表示後、別ターミナルで `hako-cmd start` を実行する(実機は
#    このスクリプトの前でも後でも起動してよい)。
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

LEADER_FLAG=()
ROLE="follower"
if [ "${LEADER:-0}" = "1" ]; then
  LEADER_FLAG=(--leader)
  ROLE="leader"
fi
SCANNING_TIMEOUT="${SCANNING_TIMEOUT:-20}"
TIMEOUT="${TIMEOUT:-90}"

echo "=== run_hako.py (${ROLE}, origin=5, --no-starter, --scanning-timeout=${SCANNING_TIMEOUT}, --timeout=${TIMEOUT}) ==="
echo "(plant/ビューアが別ターミナルで起動済みであること。登録完了後、"
echo " 別ターミナルで hako-cmd start を実行すること)"

cd "${MUJOCO_ROBOTS_DIR}"
# LEADER_FLAGが空配列のとき、bashのバージョン/ビルドによっては
# set -u下で"${LEADER_FLAG[@]}"が unbound variable になることがある
# (Mac同梱のbash 5.3で実際に発生を確認)。${arr[@]+"${arr[@]}"}は
# 空配列でも未設定変数でも安全に展開できる定番の書き方。
exec bash run-hakopy.bash "${SCRIPT_DIR}/run_hako.py" \
  --origin 5 \
  ${LEADER_FLAG[@]+"${LEADER_FLAG[@]}"} \
  --no-starter \
  --scanning-timeout "${SCANNING_TIMEOUT}" \
  --calibration-timeout 60 \
  --timeout "${TIMEOUT}"
