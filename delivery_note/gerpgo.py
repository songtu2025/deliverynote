from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
import os
from pathlib import Path
from threading import Lock
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class GerpgoSettings:
    base_url: str
    app_id: str
    app_key: str
    source: str


class GerpgoError(RuntimeError):
    """积加开放平台请求失败。"""

    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
        api_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.api_code = api_code


PostJson = Callable[[str, dict[str, str], dict[str, Any]], dict[str, Any]]


def _error_detail(payload: dict[str, Any]) -> str:
    messages = payload.get("messages") or []
    detail = "；".join(str(message) for message in messages)
    return detail or str(payload.get("message") or "")


def _post_json(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        response_payload: dict[str, Any] = {}
        try:
            response_payload = json.loads(error.read().decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            pass
        raw_api_code = response_payload.get("code")
        api_code = raw_api_code if isinstance(raw_api_code, int) else None
        message = f"积加接口返回 HTTP {error.code}"
        if api_code is not None:
            message += f"（错误码 {api_code}）"
        detail = _error_detail(response_payload)
        if detail:
            message += f"：{detail}"
        raise GerpgoError(
            message,
            http_status=error.code,
            api_code=api_code,
        ) from error
    except URLError as error:
        raise GerpgoError(f"无法连接积加接口：{error.reason}") from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GerpgoError("积加接口返回了无法解析的数据") from error


def gerpgo_config_path(storage_root: Path | str) -> Path:
    return Path(storage_root) / "config" / "gerpgo.json"


def load_gerpgo_settings(
    storage_root: Path | str | None = None,
) -> GerpgoSettings:
    if storage_root is not None:
        config_path = gerpgo_config_path(storage_root)
        if config_path.is_file():
            try:
                payload = json.loads(config_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
                raise GerpgoError("积加配置文件无法读取") from error
            settings = GerpgoSettings(
                base_url=str(payload.get("base_url") or "").strip(),
                app_id=str(payload.get("app_id") or "").strip(),
                app_key=str(payload.get("app_key") or "").strip(),
                source="managed",
            )
            if not all((settings.base_url, settings.app_id, settings.app_key)):
                raise GerpgoError("积加 API 尚未完成配置")
            return settings

    settings = GerpgoSettings(
        base_url=os.getenv("GERPGO_API_BASE_URL", "").strip(),
        app_id=os.getenv("GERPGO_APP_ID", "").strip(),
        app_key=os.getenv("GERPGO_APP_KEY", "").strip(),
        source="environment",
    )
    if not all((settings.base_url, settings.app_id, settings.app_key)):
        raise GerpgoError("积加 API 尚未完成配置")
    return settings


def save_gerpgo_settings(
    storage_root: Path | str,
    settings: GerpgoSettings,
) -> None:
    config_path = gerpgo_config_path(storage_root)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = config_path.with_suffix(".json.tmp")
    temporary_path.write_text(
        json.dumps(
            {
                "base_url": settings.base_url,
                "app_id": settings.app_id,
                "app_key": settings.app_key,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    temporary_path.chmod(0o600)
    temporary_path.replace(config_path)


class GerpgoClient:
    """读取积加采购与自营仓待入库数据。"""

    def __init__(
        self,
        base_url: str,
        app_id: str,
        app_key: str,
        post_json: PostJson = _post_json,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.app_id = app_id
        self.app_key = app_key
        self.post_json = post_json
        self.sleep = sleep
        self.monotonic = monotonic
        self.access_token = ""
        self.last_request_at: dict[str, float] = {}
        self.throttle_lock = Lock()

    @classmethod
    def from_env(cls) -> "GerpgoClient":
        settings = load_gerpgo_settings()
        return cls(settings.base_url, settings.app_id, settings.app_key)

    @classmethod
    def from_config(cls, storage_root: Path | str) -> "GerpgoClient":
        settings = load_gerpgo_settings(storage_root)
        return cls(settings.base_url, settings.app_id, settings.app_key)

    def _throttle(self, group: str, interval: float) -> None:
        with self.throttle_lock:
            previous = self.last_request_at.get(group)
            now = self.monotonic()
            if previous is not None:
                remaining = interval - (now - previous)
                if remaining > 0:
                    self.sleep(remaining)
            self.last_request_at[group] = self.monotonic()

    def _request(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        group: str,
        interval: float,
        authenticated: bool = True,
    ) -> dict[str, Any]:
        headers = {"accessToken": self.access_token} if authenticated else {}
        for retry_count in range(6):
            self._throttle(group, interval)
            try:
                response = self.post_json(f"{self.base_url}{path}", headers, payload)
                if response.get("code") != 200:
                    raw_api_code = response.get("code")
                    api_code = raw_api_code if isinstance(raw_api_code, int) else None
                    raise GerpgoError(
                        _error_detail(response) or "积加接口请求失败",
                        api_code=api_code,
                    )
                return response
            except GerpgoError as error:
                rate_limited = error.http_status == 509 or error.api_code == 90008
                if not rate_limited or retry_count == 5:
                    raise
                with self.throttle_lock:
                    self.sleep(2 ** (retry_count + 1))

        raise RuntimeError("积加接口重试状态异常")

    def authenticate(self) -> None:
        response = self._request(
            "/api_token",
            {"appId": self.app_id, "appKey": self.app_key},
            group="token",
            interval=0,
            authenticated=False,
        )
        token = str((response.get("data") or {}).get("accessToken") or "")
        if not token:
            raise GerpgoError("积加接口未返回 accessToken")
        self.access_token = token

    def list_purchase_orders(
        self,
        statuses: tuple[int, ...] = (3, 6),
    ) -> list[dict[str, Any]]:
        if not self.access_token:
            self.authenticate()
        page = 1
        orders: list[dict[str, Any]] = []
        while True:
            response = self._request(
                "/purchase/srm/procure/page",
                {
                    "invoicesStatusList": list(statuses),
                    "pageInfo": {"page": page, "pagesize": 100},
                },
                group="purchase-list",
                interval=0.5,
            )
            data = response.get("data") or {}
            orders.extend(data.get("rows") or [])
            total = int(data.get("total") or 0)
            if len(orders) >= total:
                return orders
            page += 1

    def purchase_order_detail(self, po_code: str) -> dict[str, Any]:
        if not self.access_token:
            self.authenticate()
        response = self._request(
            "/purchase/srm/procure/detail",
            {"poCode": po_code},
            group="purchase-detail",
            interval=1 / 3,
        )
        return response.get("data") or {}

    def list_self_operated_inbound_orders(self) -> list[dict[str, Any]]:
        """分页读取国内仓待入库和部分入库单及共享调拨明细。"""

        if not self.access_token:
            self.authenticate()
        orders: list[dict[str, Any]] = []
        for rn_type, order_type in (("0", "purchase"), ("1", "transfer")):
            page = 1
            scope_count = 0
            while True:
                response = self._request(
                    "/fulfillment/store/selfInboundListAndDetail/page",
                    {
                        "rnType": rn_type,
                        "orderType": order_type,
                        "orderStatusList": ["WAIT_INBOUND", "PART_INBOUND"],
                        "page": page,
                        "pagesize": 500,
                    },
                    group=f"self-operated-inbound-list-{order_type}",
                    interval=0.5,
                )
                data = response.get("data") or {}
                rows = data.get("rows") or []
                orders.extend(rows)
                scope_count += len(rows)
                total = int(data.get("total") or 0)
                if scope_count >= total:
                    break
                page += 1
        return orders
