"""console_report — 状態遷移を人間が目視/耳で気づきやすくするための表示。

state_reporter.py が提供する「状態が変わったらレポートする」という
横断的関心事に対する、具体的な出力手段の1つ。ステートマシンの実装
(sonar_radar_app.py)には一切依存を持ち込まない。

失敗・要注意とみなす状態(タイムアウト等)は赤字で強調し、さらに
反転表示を数回明滅させることで、端末のベル設定やスピーカーの有無に
依存せず気づけるようにする(ベル`\\a`はSSH先の端末アプリの設定や
実機のスピーカー有無に依存し当てにできないため、ANSIエスケープの
明滅を主手段とする。ベルも一応あわせて送るが、鳴らなくても支障は無い)。
成功とみなす状態は緑字で強調する。

WAIT_FOR_DETECTED_GRACE(モーターを止めてdetected受信を待っている状態、
2026-08-05追加)は失敗ではないが、長時間スキャン中に見落とさないよう
同じ明滅の仕組みを黄字で使う(赤=失敗、黄=一時停止して待機中、という
色分け)。それ以外は無地のまま表示する。

状態名の集合は sonar_radar_app.State に依存させず、文字列で持つ
(将来状態が増えてもこのモジュールの改修だけで済むようにするため)。
"""

from __future__ import annotations

import sys
import time

_RESET = "\x1b[0m"
_RED = "\x1b[31;1m"
_YELLOW = "\x1b[33;1m"
_GREEN = "\x1b[32;1m"
_REVERSE = "\x1b[7m"
_BEL = "\a"

ALERT_STATES = {"CALIBRATION_FAILED", "SCAN_FAILED"}
CAUTION_STATES = {"WAIT_FOR_DETECTED_GRACE"}
SUCCESS_STATES = {"WAIT_FOR_START_PRESS"}

_FLASH_COUNT = 4
_FLASH_INTERVAL_SEC = 0.15


def _flash(text: str, color: str) -> None:
    """反転表示との明滅を繰り返す。ベルやスピーカー設定に依存しない代替手段。"""
    for i in range(_FLASH_COUNT):
        style = _REVERSE if i % 2 == 0 else ""
        sys.stdout.write(f"\r{style}{color}{text}{_RESET}")
        sys.stdout.flush()
        time.sleep(_FLASH_INTERVAL_SEC)
    sys.stdout.write(f"\r{color}{text}{_RESET}\n")
    sys.stdout.flush()


def console_report(state_name: str, *, prefix: str = "state") -> None:
    """状態名を色付き(要注意なら明滅+ベル付き)でprintする。"""
    if state_name in ALERT_STATES:
        print(_BEL, end="", flush=True)
        _flash(f"[{prefix}] {state_name} — 要確認", _RED)
    elif state_name in CAUTION_STATES:
        print(_BEL, end="", flush=True)
        _flash(f"[{prefix}] {state_name} — 停止して待機中", _YELLOW)
    elif state_name in SUCCESS_STATES:
        print(f"{_GREEN}[{prefix}] {state_name}{_RESET}", flush=True)
    else:
        print(f"[{prefix}] {state_name}", flush=True)
