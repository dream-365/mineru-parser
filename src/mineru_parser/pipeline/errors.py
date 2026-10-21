"""管道自身异常：配置错误与端到端预算耗尽。

``PipelineError`` 与三个组件异常家族（``MinerUError`` /
``ResultDownloadError`` / ``ResultExtractionError``）**互不继承**，四者共享
库级根 ``MinerUParserError``。公共消息只使用固定英文文案，不携带凭据、
签名 URL 或文档正文。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..errors import MinerUParserError
from .stages import PipelineStage

if TYPE_CHECKING:
    from .._client.models import MinerUTaskStatus


class PipelineError(MinerUParserError):
    """管道自身失败的基类。"""


class PipelineConfigurationError(PipelineError):
    """参数或配置非法。``field`` 指明出错的参数名；未指明时为 ``None``。"""

    field: str | None

    def __init__(self, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.field = field


class PipelineTimeoutError(PipelineError):
    """端到端预算耗尽。

    ``stage`` 标识耗尽时所处阶段；``task_id`` 是当时已知的任务 id；
    ``last_status`` 只在等待阶段超时时可得（继承 SPEC-001 AC-4.3）。
    被翻译的原始超时异常保存在 ``__cause__`` 上。
    """

    stage: PipelineStage
    task_id: str | None
    last_status: MinerUTaskStatus | None

    def __init__(
        self,
        message: str,
        *,
        stage: PipelineStage,
        task_id: str | None = None,
        last_status: MinerUTaskStatus | None = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.task_id = task_id
        self.last_status = last_status


__all__ = [
    "PipelineConfigurationError",
    "PipelineError",
    "PipelineTimeoutError",
]
