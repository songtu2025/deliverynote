"""Web 配置校验、数据库启动与应用资源初始化。"""

from dataclasses import dataclass
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from ..migrations.runner import migrate_schema as run_schema_migrations
from .caches import PositionFrameCache, DraftAnalysis, DraftAnalysisCache
from .database import Database
from .dependencies import RequestDependencies, build_request_dependencies
from .errors import register_exception_handlers
from .input_versions import bootstrap_builtin_templates
from .models import User
from .position_import_candidates import PositionImportCandidates
from .user_accounts import create_user_account

DRAFT_ANALYSIS_CACHE_SIZE = 32

_TRUE_BOOLEAN_VALUES = {"1", "true", "yes", "on"}
_FALSE_BOOLEAN_VALUES = {"0", "false", "no", "off"}


def _boolean_environment(name: str, default: bool) -> bool:
    """读取布尔环境变量，并拒绝无法识别的配置。"""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    value = raw_value.strip().lower()
    if value in _TRUE_BOOLEAN_VALUES:
        return True
    if value in _FALSE_BOOLEAN_VALUES:
        return False
    raise ValueError(f"{name} 必须是 true 或 false")


def _positive_setting(value: int | None, name: str, default: int) -> int:
    configured = value if value is not None else int(os.getenv(name, str(default)))
    if configured <= 0:
        raise ValueError(f"{name} 必须大于 0")
    return configured


@dataclass
class ApplicationSettings:
    database_url: str | None
    storage_root: Path | str | None
    bootstrap_admin: tuple[str, str] | None
    max_upload_bytes: int | None
    import_candidate_ttl_seconds: int | None
    position_frame_cache_size: int | None
    auto_migrate_schema: bool | None
    max_concurrent_upload_parses: int | None
    max_batch_upload_files: int | None
    session_cookie_secure: bool | None


@dataclass
class ApplicationResources:
    app: FastAPI
    dependencies: RequestDependencies
    import_candidates: PositionImportCandidates


def initialize_application(settings: ApplicationSettings) -> ApplicationResources:
    resolved_database_url = settings.database_url or os.environ.get(
        "DATABASE_URL", "sqlite+pysqlite:///delivery_note.db"
    )
    auto_migrate_schema = settings.auto_migrate_schema
    if auto_migrate_schema is None:
        auto_migrate_schema = os.getenv("AUTO_MIGRATE_SCHEMA", "true").lower() not in {
            "0",
            "false",
            "no",
        }
    if auto_migrate_schema:
        run_schema_migrations(resolved_database_url)
    database = Database(resolved_database_url)
    storage = Path(
        settings.storage_root or os.environ.get("STORAGE_ROOT", "storage")
    ).resolve()
    storage.mkdir(parents=True, exist_ok=True)
    configured_max_upload_bytes = _positive_setting(
        settings.max_upload_bytes, "MAX_UPLOAD_BYTES", 20 * 1024 * 1024
    )
    configured_max_concurrent_upload_parses = _positive_setting(
        settings.max_concurrent_upload_parses, "MAX_CONCURRENT_UPLOAD_PARSES", 2
    )
    configured_max_batch_upload_files = _positive_setting(
        settings.max_batch_upload_files, "MAX_BATCH_UPLOAD_FILES", 50
    )
    configured_import_candidate_ttl = _positive_setting(
        settings.import_candidate_ttl_seconds, "IMPORT_CANDIDATE_TTL_SECONDS", 900
    )
    configured_position_frame_cache_size = _positive_setting(
        settings.position_frame_cache_size, "POSITION_FRAME_CACHE_SIZE", 8
    )
    configured_session_cookie_secure = (
        settings.session_cookie_secure
        if settings.session_cookie_secure is not None
        else _boolean_environment("SESSION_COOKIE_SECURE", False)
    )
    import_candidate_root = storage / "temporary" / "position-imports"
    import_candidates_state = PositionImportCandidates(import_candidate_root)
    import_candidates_state.remove_expired(configured_import_candidate_ttl)
    position_frame_cache = PositionFrameCache(configured_position_frame_cache_size)
    draft_analysis_cache = DraftAnalysisCache[DraftAnalysis](DRAFT_ANALYSIS_CACHE_SIZE)

    admin_credentials = settings.bootstrap_admin
    if admin_credentials is None:
        username = os.getenv("ADMIN_USERNAME")
        password = os.getenv("ADMIN_PASSWORD")
        if username and password:
            admin_credentials = (username, password)
    if admin_credentials:
        with database.session() as session:
            existing = session.scalar(
                select(User).where(User.username == admin_credentials[0])
            )
            if existing is None:
                create_user_account(
                    session, admin_credentials[0], admin_credentials[1], "admin"
                )
                session.commit()

    bootstrap_builtin_templates(database)

    app = FastAPI(title="供应链交货处理系统", version="1.0.0")
    register_exception_handlers(app)

    app.state.database = database
    app.state.storage_root = storage
    app.state.max_upload_bytes = configured_max_upload_bytes
    app.state.max_concurrent_upload_parses = configured_max_concurrent_upload_parses
    app.state.max_batch_upload_files = configured_max_batch_upload_files
    app.state.import_candidate_ttl_seconds = configured_import_candidate_ttl
    app.state.position_frame_cache_size = configured_position_frame_cache_size
    app.state.position_frame_cache = position_frame_cache
    app.state.draft_analysis_cache = draft_analysis_cache
    app.state.session_cookie_secure = configured_session_cookie_secure
    app.state.position_import_candidates = import_candidates_state.entries
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            origin.strip()
            for origin in os.getenv(
                "CORS_ORIGINS", "http://localhost:5173,http://localhost:8080"
            ).split(",")
            if origin.strip()
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    dependencies = build_request_dependencies(
        database, position_frame_cache, configured_session_cookie_secure
    )
    return ApplicationResources(app, dependencies, import_candidates_state)
