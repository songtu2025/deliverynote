"""在预检和计算间复用质检文件读取与文件级站点选择。"""

from pathlib import Path

from ..config import resolve_supplier
from ..excel_io import read_self_operated_delivery_workbook, read_supplier_workbook
from ..inbound.models import SelfOperatedInboundRequest


def read_receipt_sources(inputs):
    suppliers = read_supplier_workbook(inputs.version_paths["supplier"])
    requests, identities = [], {}
    for source in inputs.sources:
        try:
            supplier = resolve_supplier(Path(source["original_name"]), suppliers)
            delivery = read_self_operated_delivery_workbook(source["path"])
        except Exception as error:
            raise ValueError(f"{source['original_name']}：{error}") from error
        if delivery.invalid_delivery_values:
            raise ValueError(
                f"{source['original_name']}：交货单号无效：{'、'.join(delivery.invalid_delivery_values)}"
            )
        identities[source["id"]] = supplier
        requests.append(
            SelfOperatedInboundRequest(
                source["id"],
                delivery.delivery_lines,
                delivery.delivery_numbers,
                supplier.name,
            )
        )
    choices = {
        source["id"]: {
            tuple(key.split("\t", 1)): value
            for key, value in source["receipt_sites"].items()
        }
        for source in inputs.sources
    }
    return requests, identities, choices
