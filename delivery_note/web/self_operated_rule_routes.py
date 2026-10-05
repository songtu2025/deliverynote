from _thread import LockType
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, FastAPI, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .dependencies import RequestDependencies
from .models import SelfOperatedOverreceiptRuleVersion, User
from .rule_versions import (
    RuleContext,
    activate_rule,
    publish_rule,
    rename_rule,
    validated_rule_name,
)
from .schemas import RuleVersionNamePayload, SelfOperatedOverreceiptRulePayload
from .serializers import self_operated_overreceipt_rule_json


def register_self_operated_rule_routes(
    app: FastAPI,
    dependencies: RequestDependencies,
    overreceipt_rule_lock: LockType,
    _audit: Callable[..., None],
) -> None:
    get_session = dependencies.get_session
    current_user = dependencies.current_user

    @app.get("/api/self-operated-overreceipt-rule-versions", response_model=None)
    def list_self_operated_overreceipt_rule_versions(
        _user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> list[dict[str, object]]:
        versions = session.scalars(
            select(SelfOperatedOverreceiptRuleVersion).order_by(
                SelfOperatedOverreceiptRuleVersion.created_at.desc(),
                SelfOperatedOverreceiptRuleVersion.id.desc(),
            )
        ).all()
        return [self_operated_overreceipt_rule_json(version) for version in versions]

    @app.put(
        "/api/self-operated-overreceipt-rule-versions/{version_id}/name",
        response_model=None,
    )
    def rename_self_operated_overreceipt_rule(
        version_id: int,
        payload: RuleVersionNamePayload,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, object]:
        name = validated_rule_name(payload.name)
        with overreceipt_rule_lock:
            target = rename_rule(
                RuleContext(session, user.id, _audit),
                SelfOperatedOverreceiptRuleVersion,
                version_id,
                name,
            )
        return self_operated_overreceipt_rule_json(target)

    @app.post(
        "/api/self-operated-overreceipt-rule-versions",
        status_code=status.HTTP_201_CREATED,
        response_model=None,
    )
    def publish_self_operated_overreceipt_rule(
        payload: SelfOperatedOverreceiptRulePayload,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, object]:
        name = validated_rule_name(payload.name)
        with overreceipt_rule_lock:
            version = SelfOperatedOverreceiptRuleVersion(
                name=name,
                allowance=payload.allowance,
                active=True,
                created_by=user.id,
            )
            publish_rule(
                RuleContext(session, user.id, _audit),
                version,
                {"allowance": version.allowance},
            )
        return self_operated_overreceipt_rule_json(version)

    @app.post(
        "/api/self-operated-overreceipt-rule-versions/{version_id}/activate",
        response_model=None,
    )
    def activate_self_operated_overreceipt_rule(
        version_id: int,
        user: Annotated[User, Depends(current_user)],
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, object]:
        with overreceipt_rule_lock:
            target = activate_rule(
                RuleContext(session, user.id, _audit),
                SelfOperatedOverreceiptRuleVersion,
                version_id,
            )
        return self_operated_overreceipt_rule_json(target)
