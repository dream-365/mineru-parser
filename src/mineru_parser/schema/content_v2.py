"""MinerU ``content_list_v2.json`` 的校验 Schema。

本模块只描述解析结果文档的结构，不参与 HTTP 调用。
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

# 版面坐标 (x1, y1, x2, y2)，固定四元组
BBox = tuple[int, int, int, int]


# 1. 基础通用文本片 (Inline Text Component)
class TextSegment(BaseModel):
    # equation_inline 为行内公式段，结构与 text 一致（content 为 LaTeX 字符串）
    type: Literal["text", "equation_inline"]
    content: str


TextSegments = list[TextSegment]


# 2. 图片路径结构
class ImageSource(BaseModel):
    path: str


# 3. 各类型 Block 的 content 载荷定义


class TitleContent(BaseModel):
    title_content: TextSegments
    level: int | None = None


class ParagraphContent(BaseModel):
    paragraph_content: TextSegments


class PageHeaderContent(BaseModel):
    page_header_content: TextSegments


class PageFooterContent(BaseModel):
    page_footer_content: TextSegments


class PageFootnoteContent(BaseModel):
    page_footnote_content: TextSegments


class PageNumberContent(BaseModel):
    page_number_content: TextSegments


# 装订线旁注（MinerU 的 aside_text 在 v2 中按页输出为该类型）
class PageAsideTextContent(BaseModel):
    page_aside_text_content: TextSegments


class TableContent(BaseModel):
    image_source: ImageSource | None = None
    table_caption: TextSegments = Field(default_factory=list)
    table_footnote: TextSegments = Field(default_factory=list)
    html: str | None = None
    # table_type 的词表在此收窄（与统一模型 Table.table_type 的 Literal 一致）：
    # 越界取值 / 缺失在本层反序列化（validate_json）就带字段路径报错，
    # 而不是拖到 parser 映射统一模型时才抛 ValidationError
    table_type: Literal["complex_table", "simple_table"]
    table_nest_level: int | None = None


# image / chart 共用的载荷：可选图片源 + 可选的描述文本
class MediaContent(BaseModel):
    image_source: ImageSource | None = None
    content: str | None = ""


class ImageContent(MediaContent):
    image_caption: TextSegments = Field(default_factory=list)
    image_footnote: TextSegments = Field(default_factory=list)


class ChartContent(MediaContent):
    chart_caption: TextSegments = Field(default_factory=list)
    chart_footnote: TextSegments = Field(default_factory=list)


class EquationInterlineContent(BaseModel):
    math_content: str
    math_type: str | None = None
    image_source: ImageSource | None = None


class ListItem(BaseModel):
    # item_type 词表在此收窄（与统一模型 ListItem.item_type 的 Literal 一致）：
    # 越界取值 / 缺失在反序列化阶段就带字段路径报错
    item_type: Literal["text"]
    item_content: TextSegments


class ListContent(BaseModel):
    # list_type 词表在此收窄（与统一模型 List.list_type 的 Literal 一致）：
    # 越界取值 / 缺失在反序列化阶段就带字段路径报错
    list_type: Literal["reference_list"]
    list_items: list[ListItem]


# 算法块正文：caption（如 "Algorithm 1 ..."，常为空）
# + 算法步骤正文（text / equation_inline 混排）
class AlgorithmContent(BaseModel):
    algorithm_caption: TextSegments = Field(default_factory=list)
    algorithm_content: TextSegments


# 4. 具名元素节点定义 (Document Layout Blocks)
#
# 每种版面块都是 type / content / bbox 三字段，靠 type 判别。用泛型基类把这组
# 固定字段收成一份声明：TypeT 承载判别字面量，ContentT 承载载荷类型。


class BlockBase[ContentT: BaseModel, TypeT: str](BaseModel):
    type: TypeT
    content: ContentT
    bbox: BBox


class TitleBlock(BlockBase[TitleContent, Literal["title"]]): ...


class ParagraphBlock(BlockBase[ParagraphContent, Literal["paragraph"]]): ...


class PageHeaderBlock(BlockBase[PageHeaderContent, Literal["page_header"]]): ...


class PageFooterBlock(BlockBase[PageFooterContent, Literal["page_footer"]]): ...


class PageFootnoteBlock(BlockBase[PageFootnoteContent, Literal["page_footnote"]]): ...


class PageNumberBlock(BlockBase[PageNumberContent, Literal["page_number"]]): ...


class PageAsideTextBlock(
    BlockBase[PageAsideTextContent, Literal["page_aside_text"]]
): ...


class TableBlock(BlockBase[TableContent, Literal["table"]]): ...


class ImageBlock(BlockBase[ImageContent, Literal["image"]]): ...


class EquationInterlineBlock(
    BlockBase[EquationInterlineContent, Literal["equation_interline"]]
): ...


class ChartBlock(BlockBase[ChartContent, Literal["chart"]]): ...


class ListBlock(BlockBase[ListContent, Literal["list"]]): ...


class AlgorithmBlock(BlockBase[AlgorithmContent, Literal["algorithm"]]): ...


# 5. 顶层 Schema 定义

# 单个版面元素（多态联合，按 type 判别：未知 type 会得到一行清晰报错）
LayoutElement = Annotated[
    TitleBlock
    | ParagraphBlock
    | PageHeaderBlock
    | PageFooterBlock
    | PageFootnoteBlock
    | PageNumberBlock
    | PageAsideTextBlock
    | TableBlock
    | ImageBlock
    | EquationInterlineBlock
    | ChartBlock
    | ListBlock
    | AlgorithmBlock,
    Field(discriminator="type"),
]

# 单页（元素列表）
Page = list[LayoutElement]

# 整个文档（多页列表）
DocumentContentSchema = list[Page]