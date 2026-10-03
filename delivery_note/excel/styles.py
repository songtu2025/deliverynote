"""Excel 单元格样式所需的第三方类型约束。"""

from typing import Protocol

from openpyxl.styles.cell_style import StyleArray


class _StyledCell(Protocol):
    """描述现有样式字段，补足 openpyxl 的类型声明。"""

    _style: StyleArray | None
