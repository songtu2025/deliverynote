from _thread import LockType
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, FastAPI, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .dependencies import RequestDependencies
from .models import OverreceiptRuleVersion, User
from .rule_versions import (
    RuleContext,
    activate_rule,
    publish_rule,
    purchase_warehouses,
    rename_rule,
    validated_rule_name,
    validated_warehouses,
)
from .schemas import OverreceiptRulePayload, RuleVersionNamePayload
from .serializers import overreceipt_rule_json


def register_overreceipt_routes(
    app: FastAPI,
    dependencies: RequestDependencies,
    overreceipt_rule_lock: LockType,
    _audit: Callable[..., None],
    overreceipt_warehouse_cache: dict[int, tuple[str, ...]],
) -> None:
    get_session = dependencies.get_session
    current_user = dependencies.current_user

    @app.get("/api/overreceipt-rule-versions/warehouses", response_model=None)
    def list_overreceipt_warehouses(
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> list[str]:
        return purchase_warehouses(session, overreceipt_warehouse_cache)

    @app.get("/api/overreceipt-rule-versions", response_model=None)
    def list_overreceipt_rule_versions(
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> list[dict[str, object]]:
        versions = session.scalars(
            select(OverreceiptRuleVersion).order_by(
                OverreceiptRuleVersion.created_at.desc(),
                OverreceiptRuleVersion.id.desc(),
            )
        ).all()
        return [overreceipt_rule_json(version) for version in versions]

    @app.put("/api/overreceipt-rule-versions/{version_id}/name", response_model=None)
    def rename_overreceipt_rule(
        version_id: int,
        payload: RuleVersionNamePayload,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, object]:
        name = validated_rule_name(payload.name)
        with overreceipt_rule_lock:
            target = rename_rule(
                RuleContext(session, user.id, _audit),
                OverreceiptRuleVersion,
                version_id,
                name,
            )
        return overreceipt_rule_json(target)

    @app.post(
        "/api/overreceipt-rule-versions",
        status_code=status.HTTP_201_CREATED,
        response_model=None,
    )
    def publish_overreceipt_rule(
        payload: OverreceiptRulePayload,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, object]:
        name = validated_rule_name(payload.name)
        warehouses = validated_warehouses(payload.allowed_warehouses)
        with overreceipt_rule_lock:
            version = OverreceiptRuleVersion(
                name=name,
                short_tail_limit=payload.short_tail_limit,
                medium_tail_limit=payload.medium_tail_limit,
                long_tail_limit=payload.long_tail_limit,
                allowed_warehouses=warehouses,
                active=True,
                created_by=user.id,
            )
            publish_rule(
                RuleContext(session, user.id, _audit),
                version,
                {
                    "short_tail_limit": version.short_tail_limit,
                    "medium_tail_limit": version.medium_tail_limit,
                    "long_tail_limit": version.long_tail_limit,
                    "allowed_warehouses": version.allowed_warehouses,
                },
            )
        return overreceipt_rule_json(version)

    @app.post(
        "/api/overreceipt-rule-versions/{version_id}/activate", response_model=None
    )
    def activate_overreceipt_rule(
        version_id: int,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, object]:
        with overreceipt_rule_lock:
            target = activate_rule(
                RuleContext(session, user.id, _audit),
                OverreceiptRuleVersion,
                version_id,
            )
        return overreceipt_rule_json(target)
