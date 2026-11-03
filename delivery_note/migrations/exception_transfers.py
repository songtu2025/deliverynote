from typing import cast

from sqlalchemy import Table

from ..web.database import Database
from ..web.models.batches import ExceptionTransfer


def migrate(database_url: str) -> None:
    database = Database(database_url)
    try:
        cast(Table, ExceptionTransfer.__table__).create(
            database.engine, checkfirst=True
        )
    finally:
        database.dispose()
