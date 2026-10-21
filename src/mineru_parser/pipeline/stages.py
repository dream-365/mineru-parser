"""管道阶段：封闭枚举，是指标标签与 ``on_error`` 参数的唯一取值来源。"""

from __future__ import annotations

from enum import StrEnum


class PipelineStage(StrEnum):
    """一次 ``parse()`` 调用可能处于的阶段。

    ``CONFIG`` 只在参数校验失败时出现——它表示尚未进入任何执行阶段；
    四个执行阶段（submit / wait / download / extract）在每次调用中都会出现。
    """

    CONFIG = "config"
    SUBMIT = "submit"
    WAIT = "wait"
    DOWNLOAD = "download"
    EXTRACT = "extract"


__all__ = ["PipelineStage"]
