"""累计实收快照及文件级核对数据；只新增可空字段。"""

from sqlalchemy import inspect, text

from ..web.database import Database


def migrate(database_url: str) -> None:
    database = Database(database_url)
    try:
        with database.engine.begin() as connection:
            for table, names in (
                ("self_operated_batches", ("receipt_snapshot",)),
                ("batch_files", ("receipt_context", "receipt_sites")),
            ):
                columns = {
                    column["name"] for column in inspect(connection).get_columns(table)
                }
                for name in names:
                    if name not in columns:
                        connection.execute(
                            text(f"ALTER TABLE {table} ADD COLUMN {name} JSON")
                        )
    finally:
        database.dispose()
