#!/bin/bash
# cleanup.bash — デモの中断等で残ったsonar_radar-zenoh-bridge関連プロセスを掃除する。
#
# 実際に、README で「旧・使わない」と明記されている driver/sonar_radar_zenoh.py が
# 4日間動いたまま気づかれず、動作確認のノイズになっていたことがあった。デモの前後、
# あるいは「うまく動いているか分からない」と感じたときは、まずこれを実行すること。
#
# 対象(zenohd自体は常駐インフラとして扱い、対象外。止めたい場合は手動で):
#   - driver/sonar_radar_zenoh.py (旧実装、常に停止しておくべき)
#   - run_real.py / run_hako.py (bridge/の動作確認スクリプト)
#   - sonar_radar_hako.py / sonar_radar_ctrl_hako.py (Hakoniwa plant/controller)
#   - sonar_radar_viewer.py / mjpython (MuJoCoビューア)
#
# 使い方:
#   bash bridge/cleanup.bash            # 見つけたプロセスを表示してkillする
#   bash bridge/cleanup.bash --dry-run  # killせず、見つけたプロセスを表示するだけ
#
# Mac・実機(Raspberry Pi)どちらでも同じスクリプトが使える(その機で動いている
# プロセスだけを見る、ローカル専用)。2台構成のときは両方の機で実行すること。

set -u

DRY_RUN=false
if [ "${1:-}" = "--dry-run" ]; then
  DRY_RUN=true
fi

PATTERNS=(
  "sonar_radar_zenoh.py"
  "run_real.py"
  "run_hako.py"
  "sonar_radar_hako.py"
  "sonar_radar_ctrl_hako.py"
  "sonar_radar_viewer.py"
  "mjpython"
)

found_any=false

for pattern in "${PATTERNS[@]}"; do
  pids=$(pgrep -f "$pattern" 2>/dev/null || true)
  if [ -n "$pids" ]; then
    found_any=true
    echo "=== ${pattern} ==="
    ps -o pid,lstart,command -p $pids
    if [ "$DRY_RUN" = false ]; then
      echo "$pids" | xargs kill 2>/dev/null
      echo "-> kill送信"
    fi
    echo
  fi
done

if [ "$found_any" = false ]; then
  echo "残存プロセスは見つかりませんでした。"
elif [ "$DRY_RUN" = true ]; then
  echo "(--dry-run: 実際には停止していません)"
fi
