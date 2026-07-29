#!/bin/bash
# export_diagrams.bash — Astahプロジェクトの全図を docs/diagrams/ へ再エクスポートする。
#
# docs/zenoh_state_machine_design.md 冒頭の注記(「図を更新したら同じパスへ
# 再エクスポートするだけでよく、本文側のリンク修正や画像差し替えは不要」)
# に対応する自動化。これまでAstah GUIの「エクスポート」操作で手動で
# 行っていたが、astah-command.sh(コマンドラインからの画像出力)を使えば
# MCP経由でのcapture_dgm_img等のやり取りを介さずAstah自身に出力させられる。
#
# astah-command.sh -image は、出力先に「プロジェクト名/構造ツリーと同じ
# 階層」でPNGを書き出す(例: <出力先>/sonar_radar_zenoh_bridge/...)。
# docs/diagrams/ 配下は「プロジェクト名」フォルダを含まない1階層浅い
# パスを前提にしているため、一時ディレクトリへ出力してから
# docs/diagrams/ へ中身だけをコピーする。
#
# 使い方:
#   bash docs/export_diagrams.bash

set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_FILE="${SCRIPT_DIR}/sonar_radar_zenoh_bridge.asta"
DEST_DIR="${SCRIPT_DIR}/diagrams"

ASTAH_COMMAND="/Applications/astah professional/astah-command.sh"
if [ ! -x "${ASTAH_COMMAND}" ]; then
  echo "[ERROR] astah-command.sh が見つかりません: ${ASTAH_COMMAND}" >&2
  exit 1
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

echo "=== astah-command.sh で画像出力(一時ディレクトリへ) ==="
"${ASTAH_COMMAND}" -image -f "${PROJECT_FILE}" -o "${TMP_DIR}" -t png

# 出力は <TMP_DIR>/<プロジェクト名(拡張子抜き)>/... という1階層になる。
PROJECT_NAME="$(basename "${PROJECT_FILE}" .asta)"
EXPORTED_DIR="${TMP_DIR}/${PROJECT_NAME}"
if [ ! -d "${EXPORTED_DIR}" ]; then
  echo "[ERROR] 期待した出力ディレクトリがありません: ${EXPORTED_DIR}" >&2
  exit 1
fi

echo "=== docs/diagrams/ へ反映 ==="
mkdir -p "${DEST_DIR}"
# 既存の古い図が残らないよう、一度中身を空にしてからコピーする。
find "${DEST_DIR}" -mindepth 1 -delete
cp -R "${EXPORTED_DIR}/." "${DEST_DIR}/"

echo "=== 完了 ==="
find "${DEST_DIR}" -type f
