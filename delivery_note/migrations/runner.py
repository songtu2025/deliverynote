"""按固定顺序创建并升级数据库结构。"""

from __future__ import annotations

import argparse
import os
from collections.abc import Callable

from ..web.database import Database
from .overreceipt_rules import migrate as migrate_overreceipt_rules
from .position_draft_row_index import migrate as migrate_position_draft_row_index
from .purchase_sync_optional_versions import (
    migrate as migrate_purchase_sync_optional_versions,
)
from .self_operated_optional_versions import (
    migrate as migrate_self_operated_optional_versions,
)


MIGRATIONS: tuple[Callable[[str], None], ...] = (
    migrate_overreceipt_rules,
    migrate_self_operated_optional_versions,
    migrate_purchase_sync_optional_versions,
    migrate_position_draft_row_index,
)


def migrate_schema(database_url: str) -> None:
    """创建最新表，并按顺序补齐已有部署的结构变更。"""
    database = Database(database_url)
    try:
        database.create_schema()
    finally:
        database.dispose()

    for migration in MIGRATIONS:
        migration(database_url)


def main() -> None:
    parser = argparse.ArgumentParser(description="创建并升级 DeliveryNote 数据库结构")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    arguments = parser.parse_args()
    if not arguments.database_url:
        parser.error("请通过 --database-url 或 DATABASE_URL 提供数据库连接")
    migrate_schema(arguments.database_url)
    print("database schema migrations applied")
