"""创建超收规则表和异常指引字段。"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import inspect, text

from ..web.database import Database
from ..web.models import (
    BatchOverreceiptRule,
    ExceptionRecord,
    OverreceiptRuleVersion,
)


EXCEPTION_GUIDANCE_COLUMNS = (
    "purchase_allocated_quantity",
    "overreceipt_allocated_quantity",
    "overreceipt_remaining_quantity",
)


def migrate(database_url: str) -> None:
    database = Database(database_url)
    try:
        OverreceiptRuleVersion.__table__.create(database.engine, checkfirst=True)
        BatchOverreceiptRule.__table__.create(database.engine, checkfirst=True)
        existing_columns = {
            column["name"]
            for column in inspect(database.engine).get_columns(
                ExceptionRecord.__tablename__
            )
        }
        with database.engine.begin() as connection:
            for column in EXCEPTION_GUIDANCE_COLUMNS:
                if column not in existing_columns:
                    connection.execute(
                        text(
                            f"ALTER TABLE {ExceptionRecord.__tablename__} "
                            f"ADD COLUMN {column} INTEGER"
                        )
                    )
    finally:
        database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="新增超收规则表和待处理分配明细字段（可重复执行）"
    )
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    arguments = parser.parse_args()
    if not arguments.database_url:
        parser.error("请通过 --database-url 或 DATABASE_URL 提供数据库连接")
    migrate(arguments.database_url)
    print("overreceipt rule and exception guidance migration applied")


if __name__ == "__main__":
    main()
