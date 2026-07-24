#!/usr/bin/env python3
"""
sonar_radar_zenoh.py — SonarRadarSM に hakoniwa-pdu-endpoint (Zenoh) を差し込み、
実機とシミュレータをマシン間で同期させるドライバ。

sim/sonar_radar_ctrl_hako.py の Zenoh 版に相当する。
SonarRadarSM 自身は zenoh / hakoniwa_pdu_endpoint を一切知らない。
on_event コールバック（送信）と notify_*() メソッド（受信）だけで疎結合に連携する。

【重要: 受信はポーリングではなく非同期コールバック】
hakoniwa-pdu-endpoint の process_recv_events() は SHM バックエンド専用の仕組みで、
Zenoh バックエンドでは何もしない（no-op）。Zenoh の受信は
subscribe_on_recv_callback_by_name() で登録したコールバックが、
Zenoh 内部のスレッドから直接・非同期に呼ばれる。
そのため notify_*() は tick ループとは別スレッドから呼ばれうるが、
単純な bool フラグの代入のみを行うため、Python の GIL のもとでは実用上安全。

使い方:
  # 実機（Raspi 4B+）
  python3 driver/sonar_radar_zenoh.py --role real \\
      --config config/raspi4b/endpoint_zenoh.json

  # シム（Mac, MuJoCo。--viewer 相当の対話実行は今後の課題）
  python3 driver/sonar_radar_zenoh.py --role sim \\
      --config config/mac/endpoint_zenoh.json

環境変数:
  SONAR_RADAR_ROOT   sonar_radar リポジトリのルート（省略時は本リポジトリの兄弟
                      ディレクトリ ../sonar_radar を探す）
  SPIKEHAT_SIM_XML   --role sim のときの MuJoCo XML パス（省略時は sonar_radar 側の既定値）
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
import time


# ─── パス解決 ──────────────────────────────────────────────────────────────

_here = os.path.dirname(os.path.abspath(__file__))
_bridge_root = os.path.join(_here, "..")


def _resolve_sonar_radar_root() -> str:
    root = os.environ.get("SONAR_RADAR_ROOT")
    if root and os.path.isdir(root):
        return os.path.realpath(root)
    guess = os.path.join(_bridge_root, "..", "sonar_radar")
    if os.path.isdir(guess):
        return os.path.realpath(guess)
    raise RuntimeError(
        "sonar_radar リポジトリが見つかりません。"
        "SONAR_RADAR_ROOT 環境変数でパスを指定してください。"
    )


SONAR_RADAR_ROOT = _resolve_sonar_radar_root()
RASPI_DIR = os.path.join(SONAR_RADAR_ROOT, "raspi")


def _make_hat_and_sm_class(role: str):
    """role に応じた spikehat 実装を sys.path へ差し込んでから SonarRadarSM を import する。

    sonar_radar.py のモジュールレベルで `from spikehat import ...` が実行されるため、
    import する前に対象実装を sys.path の先頭へ入れておく必要がある
    （sim/sonar_radar_sim.py, sim/sonar_radar_ctrl_hako.py と同じ手法）。
    """
    if role == "real":
        lib_dir = os.path.join(RASPI_DIR, "libspikehat", "python")
    elif role == "sim":
        lib_dir = os.path.join(SONAR_RADAR_ROOT, "sim", "libspikehat_sim", "python")
    else:
        raise ValueError(f"unknown role: {role!r}")

    for d in (lib_dir, RASPI_DIR):
        if d not in sys.path:
            sys.path.insert(0, d)

    import spikehat as _sh  # noqa: E402
    from sonar_radar import SonarRadarSM, SAMPLE_INTERVAL_S  # noqa: E402

    if role == "real":
        hat = _sh.SpikeHat()
    else:
        xml_default = os.path.join(SONAR_RADAR_ROOT, "mujoco_model", "sonar_radar.xml")
        xml_path = os.environ.get("SPIKEHAT_SIM_XML", os.path.realpath(xml_default))
        hat = _sh.SpikeHat(xml_path=xml_path)

    return hat, SonarRadarSM, SAMPLE_INTERVAL_S


# ─── PDU ペイロードのエンコード/デコード ────────────────────────────────────
# calibrated/start/stop/detected はトリガーのみ（受信そのものが意味を持つ）。
#
# 【自己ループバック対策】
# Zenoh の z_declare_subscriber はデフォルト(zc_locality_t::ZC_LOCALITY_ANY)で
# 自分自身が publish したデータも受信する。hakoniwa-pdu-endpoint は endpoint
# ごとに単一の subscriber を宣言する実装のため、これを ZC_LOCALITY_REMOTE に
# 変更して自己echoを止めると *その endpoint の全チャンネル* が一律に影響を
# 受けてしまい、「このイベントだけは自分の発行を自分でも拾いたい」という
# 将来の使い方ができなくなる。そのため hakoniwa-pdu-endpoint 側は変更せず、
# トリガーのペイロードに送信元識別子（役割）を積み、受信側で自分自身の
# 識別子と一致するものは無視するアプリケーションレベルの対策にした。
_ORIGIN = {"real": b"\x01", "sim": b"\x02"}
_SCAN_STRUCT = struct.Struct("<idi")  # angle(int32), dome_angle(float64), distance_mm(int32)
_MISSING_INT = -2_147_483_648  # angle / distance_mm が None のときの番兵値


def _encode_scan(sample: dict) -> bytes:
    angle = sample.get("angle")
    dome_angle = sample.get("dome_angle")
    dist = sample.get("distance_mm")
    return _SCAN_STRUCT.pack(
        _MISSING_INT if angle is None else int(angle),
        float("nan") if dome_angle is None else float(dome_angle),
        _MISSING_INT if dist is None else int(dist),
    )


def _decode_scan(data: bytes) -> dict:
    angle, dome_angle, dist = _SCAN_STRUCT.unpack(data)
    return {
        "angle": None if angle == _MISSING_INT else angle,
        "dome_angle": None if dome_angle != dome_angle else dome_angle,  # NaN check
        "distance_mm": None if dist == _MISSING_INT else dist,
    }


# ─── メイン ──────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="sonar_radar Zenoh bridge driver")
    parser.add_argument("--role", choices=["real", "sim"], required=True,
                         help="real: 実機(Raspi 4B+) / sim: シム(Mac, MuJoCo)")
    parser.add_argument("--config", required=True,
                         help="endpoint_zenoh.json のパス")
    parser.add_argument("--robot", default="Radar",
                         help="pdudef.json 上のロボット名（既定: Radar）")
    args = parser.parse_args()

    hat, SonarRadarSM, SAMPLE_INTERVAL_S = _make_hat_and_sm_class(args.role)

    # sonar_radar 側の import より後でないと sys.path 設定が意味を持たないため、
    # hakoniwa_pdu_endpoint の import はここで行う。
    from hakoniwa_pdu_endpoint.c_endpoint import Endpoint, PduKey  # noqa: E402

    endpoint = Endpoint(f"sonar_radar_zenoh_{args.role}", "inout")
    endpoint.open(args.config)
    endpoint.start()
    endpoint.post_start()

    my_origin = _ORIGIN[args.role]

    def on_event(name: str, payload: dict) -> None:
        """SonarRadarSM からの送信フック（tick ループと同じスレッドで同期的に呼ばれる）。"""
        data = _encode_scan(payload) if name == "scan" else my_origin
        endpoint.send_by_name(PduKey(robot=args.robot, pdu=name), data)

    sm_holder: list = []  # 受信コールバックから SonarRadarSM 本体を参照するための入れ物
                           # （SonarRadarSM 生成前に購読登録する必要があるため）

    def _subscribe(pdu_name: str, on_recv) -> None:
        def _cb(_key, recv_payload: bytes) -> None:
            if recv_payload == my_origin:
                return  # 自己ループバック（Zenohセッションローカル配送）を無視
            on_recv()
        endpoint.subscribe_on_recv_callback_by_name(PduKey(robot=args.robot, pdu=pdu_name), _cb)

    _subscribe("calibrated", lambda: sm_holder[0].notify_peer_calibrated())
    _subscribe("start",      lambda: sm_holder[0].notify_start())
    _subscribe("stop",       lambda: sm_holder[0].notify_stop())
    _subscribe("detected",   lambda: sm_holder[0].notify_detected())

    sm = SonarRadarSM(clock=time.monotonic, on_event=on_event)
    sm_holder.append(sm)

    print(f"[{args.role}] sonar_radar_zenoh 起動。config={args.config}", file=sys.stderr)

    with hat:
        while not sm.is_terminated():
            sm.tick(hat)
            hat.sleep(SAMPLE_INTERVAL_S)

    endpoint.stop()
    endpoint.close()
    print(f"[{args.role}] 終了。{len(sm.results)} サンプル取得。", file=sys.stderr)


if __name__ == "__main__":
    main()
