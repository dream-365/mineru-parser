"""库级公共异常。

``MinerUParserError`` 是客户端、下载器与提取器三条失败路径的公共根异常。
三条路径**互不继承**，捕获任意一条不会意外捕获另外两条；需要"一网打尽"
全库失败时使用本根异常。
"""

from __future__ import annotations


class MinerUParserError(Exception):
    """``mineru-parser`` 全部组件异常的公共根。"""


__all__ = ["MinerUParserError"]
