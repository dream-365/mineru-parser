"""时间辅助函数。"""

from __future__ import annotations

import time


def elapsed_ms(started: float) -> float:
    """返回自 ``started``（``time.perf_counter()``）以来的毫秒数。"""
    return round((time.perf_counter() - started) * 1000, 3)


__all__ = ["elapsed_ms"]
