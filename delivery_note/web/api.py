from pathlib import Path
from threading import Lock

from fastapi import FastAPI
from sqlalchemy.orm import Session

from .app_setup import ApplicationSettings, initialize_application
from .uploads import build_upload_parser
from .auth_routes import register_auth_routes
from .health_routes import register_health_routes
from .job_routes import build_job_queue, register_job_routes
from .self_operated_creation import SelfOperatedBatchCreator
from .self_operated_creation_routes import register_self_operated_creation_routes
from .batch_creation import DeliveryBatchCreator
from .batch_creation_routes import register_batch_creation_routes
from .batch_file_edits import BatchFileEditor
from .batch_file_uploads import BatchFileUploader
from .batch_file_routes import register_batch_file_routes
from .batch_export_routes import register_batch_export_routes
from .batch_read_routes import register_batch_read_routes
from .batch_maintenance import BatchMaintenance
from .batch_maintenance_routes import register_batch_maintenance_routes
from .batch_views import (
    batch_json,
    batch_list_json,
    merged_export_path,
    merged_export_ready,
)
from .position_draft_import import PositionDraftImporter
from .position_draft_import_routes import register_position_draft_import_routes
from .position_draft_lifecycle import PositionDraftLifecycle
from .position_draft_lifecycle_routes import register_position_draft_lifecycle_routes
from .position_draft_row_routes import register_position_draft_row_routes
from .position_draft_read_routes import register_position_draft_read_routes
from .overreceipt_routes import register_overreceipt_routes
from .self_operated_rule_routes import register_self_operated_rule_routes
from .input_version_routes import register_input_version_routes
from .gerpgo_routes import register_gerpgo_routes
from .exception_views import (
    _exception_json,
    _exception_position_values,
    _split_records_by_exception,
)
from .exception_read_routes import register_exception_read_routes
from .exception_write_routes import register_exception_write_routes
from .input_version_read_routes import register_input_version_read_routes
from .models import AuditLog
from .sync.commands import SyncCommands
from .sync.purchase_routes import register_purchase_routes
from .sync.inbound_routes import register_inbound_routes
from .caches import InputInspectionCache
from .serializers import (
    job_json,
)


def _audit(
    session: Session,
    user_id: int | None,
    action: str,
    entity_type: str,
    entity_id: int | str,
    details: dict[str, object] | None = None,
) -> None:
    session.add(
        AuditLog(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            details=details or {},
        )
    )


def create_app(
    database_url: str | None = None,
    storage_root: Path | str | None = None,
    bootstrap_admin: tuple[str, str] | None = None,
    max_upload_bytes: int | None = None,
    import_candidate_ttl_seconds: int | None = None,
    position_frame_cache_size: int | None = None,
    auto_migrate_schema: bool | None = None,
    max_concurrent_upload_parses: int | None = None,
    max_batch_upload_files: int | None = None,
    session_cookie_secure: bool | None = None,
) -> FastAPI:
    resources = initialize_application(
        ApplicationSettings(
            database_url=database_url,
            storage_root=storage_root,
            bootstrap_admin=bootstrap_admin,
            max_upload_bytes=max_upload_bytes,
            import_candidate_ttl_seconds=import_candidate_ttl_seconds,
            position_frame_cache_size=position_frame_cache_size,
            auto_migrate_schema=auto_migrate_schema,
            max_concurrent_upload_parses=max_concurrent_upload_parses,
            max_batch_upload_files=max_batch_upload_files,
            session_cookie_secure=session_cookie_secure,
        )
    )
    app = resources.app
    dependencies = resources.dependencies
    database = app.state.database
    storage = app.state.storage_root
    position_frame_cache = app.state.position_frame_cache
    draft_analysis_cache = app.state.draft_analysis_cache
    import_candidates_state = resources.import_candidates
    overreceipt_rule_lock = Lock()
    overreceipt_warehouse_cache: dict[int, tuple[str, ...]] = {}
    input_inspection_cache = InputInspectionCache(32, 4)
    configured_session_cookie_secure = app.state.session_cookie_secure
    get_session = dependencies.get_session
    current_user = dependencies.current_user
    admin_user = dependencies.admin_user
    get_batch_or_404 = dependencies.get_batch_or_404
    register_health_routes(app, database)
    register_auth_routes(app, dependencies, configured_session_cookie_secure, _audit)

    parse_uploaded_workbook = build_upload_parser(
        app.state.max_concurrent_upload_parses
    )
    inspect_version = input_inspection_cache.inspect

    register_input_version_routes(
        app, dependencies, storage, parse_uploaded_workbook, _audit
    )

    register_gerpgo_routes(app, dependencies, storage, _audit)
    register_overreceipt_routes(
        app, dependencies, overreceipt_rule_lock, _audit, overreceipt_warehouse_cache
    )
    register_self_operated_rule_routes(app, dependencies, overreceipt_rule_lock, _audit)

    sync_commands = SyncCommands(storage, _audit)
    register_purchase_routes(app, dependencies, sync_commands)
    register_inbound_routes(app, dependencies, sync_commands)
    register_batch_read_routes(
        app=app,
        get_session=get_session,
        current_user=current_user,
        batch_json=batch_json,
        batch_list_json=batch_list_json,
        get_batch_or_404=get_batch_or_404,
    )
    register_exception_read_routes(
        app=app,
        get_session=get_session,
        current_user=current_user,
        get_batch_or_404=get_batch_or_404,
        exception_position_values=_exception_position_values,
        position_frame_cache=position_frame_cache,
        split_records_by_exception=_split_records_by_exception,
        exception_json=_exception_json,
    )

    register_input_version_read_routes(
        app=app,
        get_session=get_session,
        admin_user=admin_user,
        inspect_version=inspect_version,
    )

    register_position_draft_read_routes(
        app, dependencies, draft_analysis_cache, storage
    )
    register_position_draft_row_routes(app, dependencies, import_candidates_state)
    register_position_draft_import_routes(
        app,
        dependencies,
        PositionDraftImporter(app, import_candidates_state, parse_uploaded_workbook),
    )
    register_position_draft_lifecycle_routes(
        app,
        dependencies,
        PositionDraftLifecycle(
            storage, _audit, draft_analysis_cache, import_candidates_state
        ),
    )

    register_self_operated_creation_routes(
        app,
        dependencies,
        SelfOperatedBatchCreator(app, storage, _audit, parse_uploaded_workbook),
    )
    register_batch_creation_routes(
        app,
        dependencies,
        DeliveryBatchCreator(app, storage, _audit, parse_uploaded_workbook),
    )
    register_batch_file_routes(
        app,
        dependencies,
        BatchFileUploader(app, dependencies, storage, _audit, parse_uploaded_workbook),
        BatchFileEditor(dependencies, _audit),
    )
    register_batch_maintenance_routes(
        app, dependencies, BatchMaintenance(storage, _audit, dependencies)
    )

    queue_job = build_job_queue(_audit)
    register_job_routes(app, dependencies, queue_job, _audit)

    register_exception_write_routes(
        app=app,
        get_session=get_session,
        current_user=current_user,
        get_batch_or_404=get_batch_or_404,
        position_frame_cache=position_frame_cache,
        exception_position_values=_exception_position_values,
        split_records_by_exception=_split_records_by_exception,
        exception_json=_exception_json,
        queue_job=queue_job,
        job_json=job_json,
        audit=_audit,
    )

    register_batch_export_routes(
        app=app,
        get_session=get_session,
        current_user=current_user,
        get_batch_or_404=get_batch_or_404,
        merged_export_path=merged_export_path,
        merged_export_ready=merged_export_ready,
        queue_job=queue_job,
        job_json=job_json,
    )

    return app
