import argparse
from datetime import datetime
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

from .config import build_document_note, resolve_supplier
from .excel_io import (
    read_delivery_workbook,
    read_product_workbook,
    read_purchase_workbook,
    read_position_workbook,
    read_supplier_workbook,
    write_delivery_workbook,
)
from .pipeline import (
    BatchResult,
    build_manual_import_rows,
    enrich_pending_import_rows,
    process_data,
)

BEIJING_TIMEZONE = ZoneInfo("Asia/Shanghai")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="生成交货导入文件和人工处理明细")
    parser.add_argument("--delivery", type=Path, required=True, help="供应商交货单")
    parser.add_argument("--purchase", type=Path, required=True, help="采购需求表")
    parser.add_argument("--product-info", type=Path, required=True, help="产品信息表")
    parser.add_argument(
        "--supplier-info", type=Path, required=True, help="供应商资料表"
    )
    parser.add_argument(
        "--position-data", type=Path, required=True, help="MSKU 定位排查表"
    )
    parser.add_argument("--template", type=Path, required=True, help="官方导入模板")
    parser.add_argument(
        "--output-dir", type=Path, default=Path("outputs"), help="结果输出目录"
    )
    return parser


def _validate_input_files(paths: list[Path]) -> None:
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"文件不存在：{path}")


def run_batch(
    delivery_path: Path,
    purchase_path: Path,
    product_info_path: Path,
    supplier_info_path: Path,
    position_data_path: Path,
    template_path: Path,
    output_dir: Path,
    run_time: datetime | None = None,
) -> tuple[Path, BatchResult]:
    _validate_input_files(
        [
            delivery_path,
            purchase_path,
            product_info_path,
            supplier_info_path,
            template_path,
            position_data_path,
        ]
    )
    supplier_rows = read_supplier_workbook(supplier_info_path)
    supplier = resolve_supplier(delivery_path, supplier_rows)
    delivery_lines = read_delivery_workbook(delivery_path)
    product_info = read_product_workbook(product_info_path)
    purchase_rows = read_purchase_workbook(purchase_path)
    position_rows = read_position_workbook(position_data_path)
    result = process_data(
        delivery_lines,
        product_info,
        purchase_rows,
        supplier.name,
        supplier.code,
    )

    timestamp = (run_time or datetime.now(BEIJING_TIMEZONE)).strftime("%Y%m%d_%H%M%S")
    batch_directory = output_dir / timestamp
    output_path = batch_directory / f"{delivery_path.stem}_交货处理.xlsx"

    document_note = build_document_note(delivery_path, supplier_rows)
    import_rows = result.import_rows.copy()
    import_rows["单据备注"] = document_note
    pending_rows = build_manual_import_rows(result.exception_rows, supplier.code)
    pending_rows["单据备注"] = document_note
    pending_rows = enrich_pending_import_rows(pending_rows, position_rows)
    write_delivery_workbook(
        template_path,
        output_path,
        result,
        import_rows,
        pending_rows,
    )

    return output_path, result


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        output_path, result = run_batch(
            delivery_path=args.delivery,
            purchase_path=args.purchase,
            product_info_path=args.product_info,
            template_path=args.template,
            supplier_info_path=args.supplier_info,
            output_dir=args.output_dir,
            position_data_path=args.position_data,
        )
    except Exception as error:
        print(f"处理失败：{error}", file=sys.stderr)
        return 1

    print(f"交货总量：{result.delivery_total}")
    print(f"自动导入量：{result.import_total}（{len(result.import_rows)} 行）")
    print(f"人工处理量：{result.manual_total}（{len(result.exception_rows)} 行）")
    print(f"交货处理文件：{output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
