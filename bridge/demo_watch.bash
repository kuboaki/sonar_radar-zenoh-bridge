#!/bin/bash
# demo_watch.bash — デモ観測用ターミナル(Mac側)を起動する。
#
# watch_state.py(状態遷移、origin付き)とwatch_all.py(生のトリガー
# メッセージ、アプリの自己申告に頼らない)を、必要な環境変数を揃えた
# 上で起動する。手作業でsource env.sh等を毎回打ち直すのを避けるための
# ラッパー(README.mdの「動作確認」手順と同じ内容)。
#
# 使い方:
#   bash bridge/demo_watch.bash state   # watch_state.py を起動
#   bash bridge/demo_watch.bash all     # watch_all.py を起動 (既定)

set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

source env.sh
source ~/Projects/sonar_radar/.venv/bin/activate

MODE="${1:-all}"
case "$MODE" in
  state)
    exec python3 watch_state.py 2>/dev/null
    ;;
  all)
    exec python3 watch_all.py 2>/dev/null
    ;;
  *)
    echo "Usage: $0 [state|all]" >&2
    exit 1
    ;;
esac
