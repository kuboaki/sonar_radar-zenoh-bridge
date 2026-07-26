"""spikehat_timer — ワンショットタイマー。

docs/zenoh_state_machine_design.md のクラス図(sonar_radar::libspikehat::timer)
に対応する実装。C移植を見据え、関数名・シグネチャは「オペークなハンドルを
第一引数に取るC関数」の形に揃えている
(spikehat_timer_create/start/is_fired/reset/remain/destroy)。
Python版は time.monotonic() を使うだけの軽量実装。
"""

from __future__ import annotations

import time
from typing import Optional


class SpikehatTimerHandle:
    """spikehat_timer_t* に相当するオペークハンドル。中身はこのモジュール外から触らない。"""

    def __init__(self) -> None:
        self._deadline: Optional[float] = None
        self._fired: bool = False


def spikehat_timer_create() -> SpikehatTimerHandle:
    return SpikehatTimerHandle()


def spikehat_timer_start(t: SpikehatTimerHandle, duration_sec: float) -> int:
    """one-shot。既存のアーム状態は上書きする。"""
    t._deadline = time.monotonic() + duration_sec
    t._fired = False
    return 0


def spikehat_timer_is_fired(t: SpikehatTimerHandle) -> int:
    """発火済みか問い合わせ。発火後はresetするまで真を返し続ける。"""
    if t._deadline is None:
        return 0
    if not t._fired and time.monotonic() >= t._deadline:
        t._fired = True
    return 1 if t._fired else 0


def spikehat_timer_reset(t: SpikehatTimerHandle) -> int:
    """再アーム（未起動状態に戻す）。"""
    t._deadline = None
    t._fired = False
    return 0


def spikehat_timer_remain(t: SpikehatTimerHandle) -> float:
    """残り時間（UI表示等に便利）。"""
    if t._deadline is None:
        return 0.0
    return max(0.0, t._deadline - time.monotonic())


def spikehat_timer_destroy(t: SpikehatTimerHandle) -> None:
    t._deadline = None
    t._fired = False
