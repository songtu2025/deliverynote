"""仅使用合成数据构造采购单及资料。"""

from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font


def make_files(root: Path) -> dict[str, Path]:
    paths = {
        name: root / f"{name}.xlsx"
        for name in ("source", "supplier", "product", "warehouse", "template")
    }
    book = Workbook()
    sheet = book.worksheets[0]
    sheet.title = "采购单"
    sheet["A2"] = "采购批次编号：QX-JQ2026040304"
    sheet["B6"] = "SKU"
    sheet["F6"] = "单价（含包装）"
    sheet["G7"] = "美国"
    sheet.merge_cells("G7:H7")
    sheet["I7"] = "TK"
    for column in (7, 8, 9):
        sheet.cell(8, column, datetime(2026, 5, 1))
    sheet["Q6"] = "美国备注"
    sheet["R6"] = "TK备注"
    for row, sku, price, quantities in (
        (9, "SKU-A", 1.25, [10, 0, 20]),
        (10, "SKU-B", 2.1, [0, 0, 30]),
    ):
        sheet.cell(row, 2, sku)
        sheet.cell(row, 6, price)
        for column, quantity in enumerate(quantities, 7):
            sheet.cell(row, column, quantity)
    sheet["B11"] = "合计"
    sheet["B12"] = "交货条款：此处不能作为SKU"
    book.save(paths["source"])

    book = Workbook()
    book.worksheets[0].append(["供应商编号", "供应商名称", "状态", "供应商别名"])
    book.worksheets[0].append(["SUP001", "供应商甲公司", "启用", "供应商甲|甲厂"])
    book.worksheets[0].append(["SUP002", "供应商", "启用", ""])
    book.save(paths["supplier"])

    book = Workbook()
    book.worksheets[0].append(["国家", "SKU", "店铺/站点", "MSKU", "品类A", "锁仓MKSU"])
    book.worksheets[0].append(["US", "SKU-A", "店铺/US", "MSKU-A", "合成品类", ""])
    book.worksheets[0].append(
        ["US", "SKU-B", "AMAZON:店铺/US", "MSKU-B", "合成品类", ""]
    )
    book.save(paths["product"])

    book = Workbook()
    book.worksheets[0].append(["SKU", "仓库"])
    book.worksheets[0].append(["SKU-A", "普通仓"])
    book.worksheets[0].append(["SKU-B", "普通仓"])
    book.save(paths["warehouse"])

    book = Workbook()
    sheet = book.worksheets[0]
    sheet.title = "采购单录入模板"
    for column, label in {
        1: "供应商（编码）",
        2: "付款条件（编码）",
        5: "币种（币种符号）",
        7: "自定义采购单号",
        9: "单据备注",
        10: "*目的仓",
        12: "站点",
        14: "*MSKU",
        15: "*物流方式",
        16: "*采购量",
        19: "不含税单价",
        22: "合同交期",
    }.items():
        sheet.cell(1, column, "基本信息")
        sheet.cell(2, column, label)
        sheet.cell(1, column).font = Font(bold=True)
    sheet["A3"] = "旧供应商隐私"
    sheet["C3"] = "其他旧数据"
    book.create_sheet("辅助计算")["A1"] = "私人资料"
    book.save(paths["template"])
    return paths


def convert(paths: dict[str, Path], filename: str = "甲厂-采购单.xlsx"):
    from delivery_note.purchase_entry import convert_purchase

    return convert_purchase(
        paths["source"],
        filename,
        paths["supplier"],
        paths["product"],
        paths["warehouse"],
    )
