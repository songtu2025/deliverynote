"""Create the immutable overreceipt rule tables on an existing database."""

from __future__ import annotations

import argparse
import os

from ..web.database import Database
from ..web.models import BatchOverreceiptRule, OverreceiptRuleVersion


def migrate(database_url: str) -> None:
    database = Database(database_url)
    try:
        OverreceiptRuleVersion.__table__.create(database.engine, checkfirst=True)
        BatchOverreceiptRule.__table__.create(database.engine, checkfirst=True)
    finally:
        database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="新增超收规则版本和批次规则锁定表（可重复执行）"
    )
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    arguments = parser.parse_args()
    if not arguments.database_url:
        parser.error("请通过 --database-url 或 DATABASE_URL 提供数据库连接")
    migrate(arguments.database_url)
    print("overreceipt rule migration applied")


if __name__ == "__main__":
    main()
