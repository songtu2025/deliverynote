"""将文件单据备注扩为文本，完整保留多交货单号。"""

from sqlalchemy import Text, inspect, text

from ..web.database import Database


def migrate(database_url: str) -> None:
    database = Database(database_url)
    try:
        if database.engine.dialect.name != "postgresql":
            return
        with database.engine.begin() as connection:
            column = next(
                column
                for column in inspect(connection).get_columns("batch_files")
                if column["name"] == "document_note"
            )
            if not isinstance(column["type"], Text):
                connection.execute(
                    text("ALTER TABLE batch_files ALTER COLUMN document_note TYPE TEXT")
                )
    finally:
        database.dispose()
