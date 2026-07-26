"""console_report — 状態遷移を人間が目視/耳で気づきやすくするための表示。

state_reporter.py が提供する「状態が変わったらレポートする」という
横断的関心事に対する、具体的な出力手段の1つ。ステートマシンの実装
(sonar_radar_app.py)には一切依存を持ち込まない。

失敗・要注意とみなす状態(タイムアウト等)は赤字+ターミナルベルで、
成功とみなす状態は緑字で強調する。それ以外は無地のまま表示する。
状態名の集合は sonar_radar_app.State に依存させず、文字列で持つ
(将来状態が増えてもこのモジュールの改修だけで済むようにするため)。
"""

from __future__ import annotations

_RESET = "\x1b[0m"
_RED = "\x1b[31;1m"
_GREEN = "\x1b[32;1m"
_BEL = "\a"

ALERT_STATES = {"CALIBRATION_FAILED", "SCAN_FAILED"}
SUCCESS_STATES = {"WAIT_FOR_START_PRESS"}


def console_report(state_name: str, *, prefix: str = "state") -> None:
    """状態名を色付き(必要ならベル付き)でprintする。"""
    if state_name in ALERT_STATES:
        print(f"{_BEL}{_RED}[{prefix}] {state_name} — 要確認{_RESET}", flush=True)
    elif state_name in SUCCESS_STATES:
        print(f"{_GREEN}[{prefix}] {state_name}{_RESET}", flush=True)
    else:
        print(f"[{prefix}] {state_name}", flush=True)
