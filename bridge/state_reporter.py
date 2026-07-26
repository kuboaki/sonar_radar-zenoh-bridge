"""state_reporter — 状態遷移のレポートを付与する横断的関心事。

sonar_radar_app.py のようなステートマシン実装(図をそのまま1:1で
翻訳したもの)には、デバッグ・観測用の処理を混ぜない。
「run()というtickごとに呼ばれる繰り返し構造の冒頭で、前回と状態が
変わっていたら新しい状態をレポートする」というパターンは、
個々のステートマシンの実装ではなく、それをどう変換・運用するかという
規約(変換ルール)側の関心事としてここに切り出す。

手作業で実装したステートマシンにも、m2t のようなテンプレート生成でも、
同じ規約を機械的に適用できる。
"""

from __future__ import annotations

from typing import Any, Callable, Protocol


class Tickable(Protocol):
    """run()を持ち、現在の状態をstateプロパティで参照できるオブジェクト。"""

    @property
    def state(self) -> Any: ...

    def run(self) -> None: ...


def with_state_change_reporting(app: Tickable, report: Callable[[Any], None]) -> Tickable:
    """app.run を、状態変化を検知して report(new_state) するラッパーに差し替える。

    app自体(ステートマシンの実装)は一切変更しない。同じ app に対して
    複数回呼べば、report を複数登録できる。
    """
    original_run = app.run
    last_state = [app.state]

    def run() -> None:
        original_run()
        if app.state != last_state[0]:
            last_state[0] = app.state
            report(app.state)

    app.run = run  # type: ignore[method-assign]
    return app
