"""以真实 HTTP 构建待入库文件、歧义及已选站点批次。"""

from pathlib import Path
from typing import Any
from urllib.parse import unquote

from tests.support.business_scenario import DeliveryScenario
from tests.support.inbound_inputs import create_ambiguous_product
from tests.support.worker import WorkerCase


class InboundScenario(DeliveryScenario):
    def __init__(self, url: str, root: Path) -> None:
        super().__init__(url, root)
        self.batch_ids: list[int] = []

    def create_inbound_baseline(self) -> list[int]:
        self.activate_inputs()
        self.request(
            "POST",
            "/api/self-operated-overreceipt-rule-versions",
            201,
            json={"name": "恢复批次共享超收5件", "allowance": 5},
        )
        self.create_inbound_batch(multiple=True)
        self.export()
        product = create_ambiguous_product(self.root / "product-ambiguous.xlsx")
        with product.open("rb") as upload:
            self.request(
                "POST",
                "/api/input-versions/product",
                201,
                data={"name": "product-ambiguous", "activate": "true"},
                files={"file": (product.name, upload)},
            )
        self.create_inbound_batch()
        self.create_inbound_batch()
        self.choose_site()
        self.export()
        return self.batch_ids

    def create_inbound_batch(self, *, multiple: bool = False) -> None:
        self.batch_id = self.request(
            "POST",
            "/api/self-operated-batches",
            201,
            json={"name": "自营仓恢复业务基线"},
        ).json()["id"]
        self.batch_ids.append(self.batch_id)
        uploaded = []
        for letter, quantity in (("A", 10), ("B", 8)) if multiple else (("A", 18),):
            path = WorkerCase.create_self_operated_delivery(
                self.root / f"260817-狂飙-{letter}质检交货单.xlsx", quantity
            )
            with path.open("rb") as upload:
                uploaded.append(
                    self.request(
                        "POST",
                        f"/api/batches/{self.batch_id}/files",
                        201,
                        files={"file": (path.name, upload)},
                    ).json()["id"]
                )
        if multiple:
            self.request(
                "PUT",
                f"/api/batches/{self.batch_id}/files/order",
                json={"file_ids": list(reversed(uploaded))},
            )
        inbound = WorkerCase.create_self_operated_inbound(self.root / "待入库.xlsx")
        with inbound.open("rb") as upload:
            self.request(
                "POST",
                f"/api/self-operated-batches/{self.batch_id}/inbound-file",
                files={"file": (inbound.name, upload)},
            )
        self.request("POST", f"/api/batches/{self.batch_id}/preflight")
        job = self.request("POST", f"/api/batches/{self.batch_id}/compute", 202)
        self.wait_job(job.json()["id"])

    def choose_site(self) -> dict[str, Any]:
        record = self.request("GET", f"/api/batches/{self.batch_id}/exceptions").json()[
            0
        ]
        job = self.request(
            "PUT",
            f"/api/exceptions/{record['id']}/self-operated-site",
            202,
            json={"full_site": "AMAZON:RIVMOUNT:US"},
        )
        return self.wait_job(job.json()["id"])

    def snapshot(self) -> dict[str, Any]:
        # 一次捕获所有批次，保留各自锁定资料和规则版本。
        batches = {}
        for identifier in self.batch_ids:
            self.batch_id = identifier
            batch = self.batch()
            prefix = f"/api/batches/{identifier}"
            batches[identifier] = {
                "batch": batch,
                "exceptions": self.request("GET", prefix + "/exceptions").json(),
                "exports": {
                    source["original_name"]: self.download_file(
                        f"/api/batch-files/{source['id']}/download",
                        Path(source["original_name"]).stem + "_积加入库.xlsx",
                    )
                    for source in batch["files"]
                    if source["download_ready"]
                },
                "download": self.download_file(
                    prefix + "/download",
                    f"batch-{identifier}.zip"
                    if len(batch["files"]) > 1
                    else Path(batch["files"][0]["original_name"]).stem
                    + "_积加入库.xlsx",
                )
                if batch["download_ready"]
                else None,
                "merged": self.download_file(
                    prefix + "/download-merged", f"batch-{identifier}-merged.xlsx"
                )
                if batch["merged_download_ready"]
                else None,
            }
        versions = self.request("GET", "/api/input-versions").json()
        return {
            "versions": versions,
            "input_files": {
                version["id"]: self.request(
                    "GET", f"/api/input-versions/{version['id']}/download"
                ).content
                for version in versions
            },
            "inspection": {
                version["id"]: self.request(
                    "GET", f"/api/input-versions/{version['id']}/inspection"
                ).json()
                for version in versions
                if version["active"]
            },
            "rules": self.request(
                "GET", "/api/self-operated-overreceipt-rule-versions"
            ).json(),
            "batches": batches,
        }

    def download_file(self, path: str, filename: str) -> bytes:
        response = self.request("GET", path)
        assert filename in unquote(response.headers["content-disposition"])
        return response.content
