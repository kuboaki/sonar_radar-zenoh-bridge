# bridge/env.sh — hakoniwa_pdu_endpoint を使うために必要な環境変数。
# source して使う: `source bridge/env.sh`
# macOS/Linux両対応(uname -s で分岐)。

export PYTHONPATH="$HOME/.local/lib/hakoniwa-pdu-endpoint/python"
export HAKO_PDU_ENDPOINT_LIB_DIR="$HOME/.local/lib/hakoniwa-pdu-endpoint/python/hakoniwa_pdu_endpoint"

if [ "$(uname -s)" = "Darwin" ]; then
  export HAKO_PDU_ENDPOINT_SHARED_LIB="$HAKO_PDU_ENDPOINT_LIB_DIR/libhakoniwa_pdu_endpoint.dylib"
  # 【重要】シェルの DYLD_LIBRARY_PATH に /usr/local/hakoniwa/lib が含まれている場合、
  # macOSのdyldは絶対パス指定のdlopenでも同名ファイルがあればそちらを優先してしまう。
  # /usr/local/hakoniwa/lib には(Zenoh無効の)古いビルドの libhakoniwa_pdu_endpoint.dylib が
  # 残っているため、それより先に .local 側を検索させることでシャドーイングを回避する。
  export DYLD_LIBRARY_PATH="$HAKO_PDU_ENDPOINT_LIB_DIR:$DYLD_LIBRARY_PATH"
else
  export HAKO_PDU_ENDPOINT_SHARED_LIB="$HAKO_PDU_ENDPOINT_LIB_DIR/libhakoniwa_pdu_endpoint.so"
  export LD_LIBRARY_PATH="$HAKO_PDU_ENDPOINT_LIB_DIR:$LD_LIBRARY_PATH"
fi
