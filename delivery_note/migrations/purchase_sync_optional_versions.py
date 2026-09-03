"""允许采购同步任务不依赖商品和供应商资料版本。"""

from __future__ import annotations

import argparse
import os

from sqlalchemy import inspect, text

from ..web.database import Database
from ..web.models import PurchaseSyncJob


OPTIONAL_VERSION_COLUMNS = (
    "product_version_id",
    "supplier_version_id",
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
                CREATE TABLE purchase_sync_jobs_new (
                    id INTEGER NOT NULL,
                    status VARCHAR(20) NOT NULL,
                    active_slot INTEGER,
                    created_by INTEGER NOT NULL,
                    base_version_id INTEGER,
                    product_version_id INTEGER,
                    supplier_version_id INTEGER,
                    candidate_version_id INTEGER,
                    total_orders INTEGER NOT NULL,
                    processed_orders INTEGER NOT NULL,
                    raw_detail_count INTEGER NOT NULL,
                    eligible_detail_count INTEGER NOT NULL,
                    filtered_detail_count INTEGER NOT NULL,
                    current_order TEXT,
                    issues JSON NOT NULL,
                    diff JSON NOT NULL,
                    attempts INTEGER NOT NULL,
                    claim_token VARCHAR(64),
                    claimed_at DATETIME,
                    heartbeat_at DATETIME,
                    finished_at DATETIME,
                    error_message TEXT,
                    created_at DATETIME NOT NULL,
                    PRIMARY KEY (id),
                    CONSTRAINT uq_active_purchase_sync_job UNIQUE (active_slot),
                    FOREIGN KEY(created_by) REFERENCES users (id),
                    FOREIGN KEY(base_version_id) REFERENCES input_versions (id),
                    FOREIGN KEY(product_version_id) REFERENCES input_versions (id),
                    FOREIGN KEY(supplier_version_id) REFERENCES input_versions (id),
                    FOREIGN KEY(candidate_version_id) REFERENCES input_versions (id)
                )
                """
                )
            )
            connection.execute(
                text(
                    """
                INSERT INTO purchase_sync_jobs_new (
                    id, status, active_slot, created_by, base_version_id,
                    product_version_id, supplier_version_id,
                    candidate_version_id, total_orders, processed_orders,
                    raw_detail_count, eligible_detail_count,
                    filtered_detail_count, current_order, issues, diff,
                    attempts, claim_token, claimed_at, heartbeat_at,
                    finished_at, error_message, created_at
                )
                SELECT
                    id, status, active_slot, created_by, base_version_id,
                    product_version_id, supplier_version_id,
                    candidate_version_id, total_orders, processed_orders,
                    raw_detail_count, eligible_detail_count,
                    filtered_detail_count, current_order, issues, diff,
                    attempts, claim_token, claimed_at, heartbeat_at,
                    finished_at, error_message, created_at
                FROM purchase_sync_jobs
                """
                )
            )
            connection.execute(text("DROP TABLE purchase_sync_jobs"))
            connection.execute(
                text("ALTER TABLE purchase_sync_jobs_new RENAME TO purchase_sync_jobs")
            )
            connection.execute(
                text(
                    "CREATE INDEX ix_purchase_sync_jobs_status "
                    "ON purchase_sync_jobs (status)"
                )
            )
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError("采购同步任务表迁移后外键校验失败")
    finally:
        if connection.in_transaction():
            connection.rollback()
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.close()


def migrate(database_url: str) -> None:
    database = Database(database_url)
    try:
        inspector = inspect(database.engine)
        if PurchaseSyncJob.__tablename__ not in inspector.get_table_names():
            return
        columns = {
            column["name"]: column
            for column in inspector.get_columns(PurchaseSyncJob.__tablename__)
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
                        f"ALTER TABLE {PurchaseSyncJob.__tablename__} "
                        f"ALTER COLUMN {column} DROP NOT NULL"
                    )
                )
    finally:
        database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="允许采购同步任务不锁定商品和供应商资料版本"
    )
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    arguments = parser.parse_args()
    if not arguments.database_url:
        parser.error("请通过 --database-url 或 DATABASE_URL 提供数据库连接")
    migrate(arguments.database_url)
    print("purchase sync optional version migration applied")


if __name__ == "__main__":
    main()
