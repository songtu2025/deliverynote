"""为历史待处理记录补齐稳定的原因代码。"""

from sqlalchemy import case, inspect, text, update

from ..exception_reasons import ExceptionReason
from ..web.database import Database
from ..web.models import ExceptionRecord


def migrate(database_url: str) -> None:
    database = Database(database_url)
    try:
        columns = {
            column["name"]
            for column in inspect(database.engine).get_columns(
                ExceptionRecord.__tablename__
            )
        }
        with database.engine.begin() as connection:
            if "reason_code" not in columns:
                connection.execute(
                    text("ALTER TABLE exceptions ADD COLUMN reason_code VARCHAR(50)")
                )
            connection.execute(
                update(ExceptionRecord)
                .where(ExceptionRecord.reason_code.is_(None))
                .values(
                    reason_code=case(
                        {
                            str(reason): reason.name.lower()
                            for reason in ExceptionReason
                        },
                        value=ExceptionRecord.reason,
                        else_="unknown",
                    )
                )
            )
    finally:
        database.dispose()
