"""Web 请求参数及字段校验。"""

from dataclasses import dataclass
from typing import Annotated

from fastapi import File, Form, Query, UploadFile
from pydantic import BaseModel, Field


class LoginPayload(BaseModel):
    username: str
    password: str


class UserPayload(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=200)
    role: str = "operator"


class UserStatusPayload(BaseModel):
    active: bool


class PasswordResetPayload(BaseModel):
    password: str = Field(min_length=8, max_length=200)


class BatchPayload(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class BatchDeletePayload(BaseModel):
    batch_ids: list[int] = Field(min_length=1)


class FileOrderPayload(BaseModel):
    file_ids: list[int]


class DraftMutationPayload(BaseModel):
    revision: int = Field(ge=1)


class PositionRowPayload(DraftMutationPayload):
    store_site: str = Field(min_length=1)
    jiaji_sku: str = Field(min_length=1)
    msku: str = ""
    scale_position: str = ""
    stocking_position: str = ""


class BulkDeletePayload(DraftMutationPayload):
    row_ids: list[int] = Field(min_length=1)


class ImportApplyPayload(DraftMutationPayload):
    token: str = Field(min_length=1)


class PublishDraftPayload(DraftMutationPayload):
    name: str = Field(min_length=1, max_length=200)
    confirm_warnings: bool = False


class OverreceiptRulePayload(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    short_tail_limit: int = Field(ge=0)
    medium_tail_limit: int = Field(ge=0)
    long_tail_limit: int = Field(ge=0)
    allowed_warehouses: list[str]


class SelfOperatedOverreceiptRulePayload(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    allowance: int = Field(ge=0)


class RuleVersionNamePayload(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class GerpgoConfigPayload(BaseModel):
    base_url: str = Field(min_length=1, max_length=500)
    app_id: str = Field(default="", max_length=200)
    app_key: str = Field(default="", max_length=500)


@dataclass
class PositionRowFilters:
    """库位草稿行的分页与筛选条件。"""

    offset: Annotated[int, Query(ge=0)] = 0
    limit: Annotated[int, Query(ge=1, le=200)] = 50
    search: str = ""
    site: str = ""
    scale_position: str = ""
    only_errors: bool = False
    only_modified: bool = False


@dataclass
class PositionImportForm:
    """库位导入预览的原始表单字段。"""

    revision: Annotated[int, Form(ge=1)]
    file: UploadFile = File(...)


@dataclass
class DeliveryBatchForm:
    name: Annotated[str, Form()]
    files: list[UploadFile] = File(...)


@dataclass
class SelfOperatedBatchForm:
    name: Annotated[str | None, Form()] = None
    delivery_file: list[UploadFile] | None = File(None)
    inbound_file: UploadFile | None = File(None)
