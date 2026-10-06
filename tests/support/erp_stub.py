"""仅服务隔离恢复测试的积加认证与待入库 HTTP 桩。"""

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
from typing import Any


class Handler(BaseHTTPRequestHandler):
    def reply(self, code: int, data: dict[str, Any]) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self) -> None:
        self.reply(200, {"status": "ok"})

    def do_POST(self) -> None:
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/api_token":
            assert payload == {"appId": "fixture-app", "appKey": "fixture-key"}
            self.reply(200, {"code": 200, "data": {"accessToken": "fixture-token"}})
            return
        assert self.path == "/fulfillment/store/selfInboundListAndDetail/page"
        assert self.headers["accessToken"] == "fixture-token"
        assert payload["orderStatusList"] == ["WAIT_INBOUND", "PART_INBOUND"]
        assert payload["page"] == 1 and payload["pagesize"] == 500
        assert (payload["rnType"], payload["orderType"]) in {
            ("0", "purchase"),
            ("1", "transfer"),
        }
        case = json.loads(Path("/stub/case.json").read_text())
        if case.get("fail"):
            self.reply(200, {"code": 400, "message": "隔离接口故障"})
            return
        rows = case["rows"] if payload["rnType"] == "0" else []
        self.reply(200, {"code": 200, "data": {"rows": rows, "total": len(rows)}})

    def log_message(self, format: str, *args: Any) -> None:
        pass


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
