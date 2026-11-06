"""按代码指纹复用 PR CI 结果的判定：master 复用与发布校验。"""

import unittest
from typing import Any

from scripts.backup.runtime import BackupError
from scripts.ci_evidence import REUSE_JOB, EvidenceError, verified_pr_run
from scripts.release_common import verify_ci

REVISION = "a" * 40
TREE = "t" * 40
CI = ".github/workflows/ci.yml"


def job(name: str, conclusion: str = "success") -> dict[str, Any]:
    return {"name": name, "conclusion": conclusion}


FULL_JOBS = [
    job("前端测试 1/3"),
    job("后端与 Python 质量检查"),
    job("提交与 Compose 配置检查"),
]


class FakeGitHub:
    def __init__(self) -> None:
        self.runs: dict[int, dict[str, Any]] = {}
        self.jobs: dict[int, list[dict[str, Any]]] = {}
        self.artifacts: dict[int, list[dict[str, Any]]] = {}
        self.compare = "identical"
        self.tree = TREE

    def add_run(
        self, run_id: int, event: str, jobs: list[dict[str, Any]], **run: Any
    ) -> None:
        self.runs[run_id] = {
            "event": event,
            "status": "completed",
            "conclusion": "success",
            "path": CI,
            "head_sha": REVISION,
            **run,
        }
        self.jobs[run_id] = jobs

    def evidence(self, run_id: int, tree: str = TREE, expired: bool = False) -> None:
        self.artifacts.setdefault(run_id, []).append(
            {
                "name": f"verified-tree-{tree}",
                "expired": expired,
                "workflow_run": {"id": run_id},
            }
        )

    def read(self, path: str) -> dict[str, Any]:
        if path.startswith("/actions/artifacts?name=verified-tree-"):
            tree = path.split("verified-tree-")[1].split("&")[0]
            items = [
                a
                for items in self.artifacts.values()
                for a in items
                if a["name"].endswith(tree)
            ]
            return {"artifacts": items}
        if path.startswith("/compare/"):
            return {"status": self.compare}
        if path.startswith("/commits/"):
            return {"commit": {"tree": {"sha": self.tree}}}
        run_id = int(path.split("/")[3].split("?")[0])
        if path.endswith("/artifacts?per_page=100"):
            return {"artifacts": self.artifacts.get(run_id, [])}
        if "/jobs" in path:
            return {"jobs": self.jobs[run_id], "total_count": len(self.jobs[run_id])}
        return self.runs[run_id]


class VerifiedPrRunTests(unittest.TestCase):
    def test_accepts_success_and_scope_skips_only(self) -> None:
        github = FakeGitHub()
        jobs = [
            *FULL_JOBS,
            job("隔离演练", "skipped"),
            job(f"代码指纹 / {REUSE_JOB}", "skipped"),
        ]
        github.add_run(7, "pull_request", jobs)
        github.evidence(7)
        self.assertEqual(verified_pr_run(github.read, TREE), 7)

    def test_rejects_failed_or_other_skipped_or_expired(self) -> None:
        for jobs, expired in (
            ([*FULL_JOBS, job("前端测试 2/3", "failure")], False),
            ([*FULL_JOBS, job("前端测试 2/3", "skipped")], False),
            (FULL_JOBS, True),
        ):
            github = FakeGitHub()
            github.add_run(7, "pull_request", jobs)
            github.evidence(7, expired=expired)
            with self.assertRaises(EvidenceError):
                verified_pr_run(github.read, TREE)


class VerifyCiTests(unittest.TestCase):
    def test_full_master_run_passes_without_evidence(self) -> None:
        github = FakeGitHub()
        github.add_run(1, "push", [job(REUSE_JOB), *FULL_JOBS])
        verify_ci(REVISION, 1, github.read)

    def test_reused_master_run_requires_matching_pr_evidence(self) -> None:
        github = FakeGitHub()
        skipped = [job(item["name"], "skipped") for item in FULL_JOBS]
        github.add_run(
            1,
            "push",
            [
                job(f"代码指纹 / {REUSE_JOB}"),
                job("代码指纹 / 记录代码指纹", "skipped"),
                *skipped,
            ],
        )
        with self.assertRaises(BackupError):
            verify_ci(REVISION, 1, github.read)
        github.add_run(7, "pull_request", FULL_JOBS, head_sha="b" * 40)
        github.evidence(7, tree="x" * 40)
        with self.assertRaises(BackupError):
            verify_ci(REVISION, 1, github.read)
        github.evidence(7)
        verify_ci(REVISION, 1, github.read)

    def test_pr_run_direct_needs_evidence_and_master_ancestry(self) -> None:
        github = FakeGitHub()
        github.add_run(7, "pull_request", FULL_JOBS, head_sha="b" * 40)
        with self.assertRaises(BackupError):
            verify_ci(REVISION, 7, github.read)
        github.evidence(7)
        verify_ci(REVISION, 7, github.read)
        github.compare = "behind"
        with self.assertRaises(BackupError):
            verify_ci(REVISION, 7, github.read)

    def test_rejects_failed_partial_or_foreign_runs(self) -> None:
        github = FakeGitHub()
        github.add_run(1, "push", [*FULL_JOBS, job("前端测试 2/3", "skipped")])
        github.add_run(2, "push", FULL_JOBS, head_sha="c" * 40)
        github.add_run(3, "push", FULL_JOBS, path=".github/workflows/other.yml")
        github.add_run(4, "workflow_dispatch", FULL_JOBS)
        for run_id in (1, 2, 3, 4):
            with self.subTest(run_id=run_id), self.assertRaises(BackupError):
                verify_ci(REVISION, run_id, github.read)


if __name__ == "__main__":
    unittest.main()
