from fastapi import FastAPI, HTTPException, status
from sqlalchemy import text

from .database import Database


def register_health_routes(app: FastAPI, database: Database) -> None:
    def readiness() -> dict[str, object]:
        try:
            with database.session() as session:
                session.execute(text("SELECT 1"))
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="服务尚未就绪",
            ) from None
        return {"status": "ok"}

    @app.get("/health/live")
    def health_live() -> dict[str, object]:
        return {"status": "ok"}

    @app.get("/health/ready")
    def health_ready() -> dict[str, object]:
        return readiness()

    @app.get("/health")
    def health() -> dict[str, object]:
        return readiness()
