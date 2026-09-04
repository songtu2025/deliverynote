"""为库位草稿分页查询补齐复合索引。"""

from sqlalchemy import inspect

from ..web.database import Database
from ..web.models import (
    POSITION_DRAFT_PAGE_INDEX_NAME,
    PositionDraftRow,
)


def migrate(database_url: str) -> None:
    """幂等创建库位草稿分页索引，兼容已有数据库。"""

    database = Database(database_url)
    try:
        tables = inspect(database.engine).get_table_names()
        if PositionDraftRow.__tablename__ not in tables:
            return
        page_index = next(
            index
            for index in PositionDraftRow.__table__.indexes
            if index.name == POSITION_DRAFT_PAGE_INDEX_NAME
        )
        page_index.create(database.engine, checkfirst=True)
    finally:
        database.dispose()
