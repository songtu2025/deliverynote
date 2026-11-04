"""补齐批次人工处理输入和待处理记录的线下处理字段。"""

from sqlalchemy import inspect, text

from ..web.database import Database


def migrate(database_url: str) -> None:
    database = Database(database_url)
    try:
        with database.engine.begin() as connection:
            additions = {
                "self_operated_batches": {
                    "manual_handling": "JSON NOT NULL DEFAULT '{}'",
                },
                "exceptions": {
                    "offline_quantity": "INTEGER NOT NULL DEFAULT 0",
                    "offline_note": "TEXT NOT NULL DEFAULT ''",
                },
            }
            for table, fields in additions.items():
                columns = {
                    item["name"] for item in inspect(connection).get_columns(table)
                }
                for name, definition in fields.items():
                    if name not in columns:
                        connection.execute(
                            text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
                        )
    finally:
        database.dispose()
