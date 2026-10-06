"""复用站点歧义测试的产品资料。"""

from pathlib import Path

from openpyxl import Workbook


def create_ambiguous_product(path: Path) -> Path:
    workbook = Workbook()
    sheet = workbook.worksheets[0]
    sheet.append(["SKU", "店铺/站点", "品类A", "锁仓MKSU"])
    sheet.append(["SKU-A", "RIVMOUNT:US", "水鞋", "锁"])
    sheet.append(["SKU-A", "SEEKWAY:US", "水鞋", "锁"])
    workbook.save(path)
    workbook.close()
    return path
