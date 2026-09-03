"""允许自营仓批次不锁定原交货流程专用版本。"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import inspect, text

from ..web.database import Database
from ..web.models import Batch


OPTIONAL_VERSION_COLUMNS = (
    "purchase_version_id",
    "position_version_id",
    "template_version_id",
)


def _sqlite_migrate(database: Database) -> None:
    connection = database.engine.connect()
    try:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
        with connection.begin():
            connection.execute(
                text(
                    """
                CREATE TABLE batches_new (
                    id INTEGER NOT NULL,
                    name VARCHAR(200) NOT NULL,
                    status VARCHAR(30) NOT NULL,
                    created_by INTEGER NOT NULL,
                    purchase_version_id INTEGER,
                    product_version_id INTEGER NOT NULL,
                    supplier_version_id INTEGER NOT NULL,
                    position_version_id INTEGER,
                    template_version_id INTEGER,
                    zip_path TEXT,
                    error_message TEXT,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    PRIMARY KEY (id),
                    FOREIGN KEY(created_by) REFERENCES users (id),
                    FOREIGN KEY(purchase_version_id) REFERENCES input_versions (id),
                    FOREIGN KEY(product_version_id) REFERENCES input_versions (id),
                    FOREIGN KEY(supplier_version_id) REFERENCES input_versions (id),
                    FOREIGN KEY(position_version_id) REFERENCES input_versions (id),
                    FOREIGN KEY(template_version_id) REFERENCES input_versions (id)
                )
                """
                )
            )
            connection.execute(
                text(
                    """
                INSERT INTO batches_new (
                    id, name, status, created_by,
                    purchase_version_id, product_version_id,
                    supplier_version_id, position_version_id,
                    template_version_id, zip_path, error_message,
                    created_at, updated_at
                )
                SELECT
                    id, name, status, created_by,
                    purchase_version_id, product_version_id,
                    supplier_version_id, position_version_id,
                    template_version_id, zip_path, error_message,
                    created_at, updated_at
                FROM batches
                """
                )
            )
            connection.execute(text("DROP TABLE batches"))
            connection.execute(text("ALTER TABLE batches_new RENAME TO batches"))
            connection.execute(
                text("CREATE INDEX ix_batches_status ON batches (status)")
            )
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError("批次表迁移后外键校验失败")
    finally:
        if connection.in_transaction():
            connection.rollback()
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.close()


def migrate(database_url: str) -> None:
    database = Database(database_url)
    try:
        columns = {
            column["name"]: column
            for column in inspect(database.engine).get_columns(Batch.__tablename__)
        }
        if all(columns[column]["nullable"] for column in OPTIONAL_VERSION_COLUMNS):
            return

        if database.engine.dialect.name == "sqlite":
            _sqlite_migrate(database)
            return

        with database.engine.begin() as connection:
            for column in OPTIONAL_VERSION_COLUMNS:
                connection.execute(
                    text(
                        f"ALTER TABLE {Batch.__tablename__} "
                        f"ALTER COLUMN {column} DROP NOT NULL"
                    )
                )
    finally:
        database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="允许自营仓批次不锁定采购、库位和原导出模板版本"
    )
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    arguments = parser.parse_args()
    if not arguments.database_url:
        parser.error("请通过 --database-url 或 DATABASE_URL 提供数据库连接")
    migrate(arguments.database_url)
    print("self-operated optional version migration applied")


if __name__ == "__main__":
    main()
