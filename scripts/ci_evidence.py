"""按代码指纹（Git tree）复用 Pull Request 的 CI 验证结果，供 master CI 与发布共用。"""

import argparse
import json
import os
from typing import Any, Callable
from urllib.request import Request, urlopen

REPOSITORY = "songtu2025/deliverynote"
WORKFLOW_PATH = ".github/workflows/ci.yml"
EVIDENCE_PREFIX = "verified-tree-"
# 只改前端的 PR 按改动范围跳过的任务；其余任务必须全部成功。
SCOPE_SKIPPABLE = {"后端与 Python 质量检查", "隔离演练"}
REUSE_JOB = "复用 PR 验证结果"

Reader = Callable[[str], dict[str, Any]]


def is_reuse_job(name: str) -> bool:
    # 复用任务在可复用工作流中，任务名带调用方前缀「代码指纹 / 」。
    return name == REUSE_JOB or name.endswith(f" / {REUSE_JOB}")


def is_allowed_skip(name: str) -> bool:
    return name in SCOPE_SKIPPABLE or is_reuse_job(name)


class EvidenceError(RuntimeError):
    """没有可复用的 PR 验证结果。"""


def api_reader(token: str | None = None) -> Reader:
    def read(path: str) -> dict[str, Any]:
        headers = {
            "User-Agent": "DeliveryNote-ci",
            "Accept": "application/vnd.github+json",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        url = f"https://api.github.com/repos/{REPOSITORY}{path}"
        with urlopen(Request(url, headers=headers), timeout=15) as response:
            return dict(json.load(response))

    return read


def run_jobs(read: Reader, run_id: int) -> list[dict[str, Any]]:
    jobs = read(f"/actions/runs/{run_id}/jobs?per_page=100")
    entries = list(jobs.get("jobs", []))
    if len(entries) != jobs.get("total_count"):
        raise EvidenceError("CI 任务列表不完整")
    return entries


def pr_run_problem(read: Reader, run_id: int) -> str | None:
    """返回 PR 运行不可复用的原因；可复用时返回 None。"""
    run = read(f"/actions/runs/{run_id}")
    expected = {
        "event": "pull_request",
        "status": "completed",
        "conclusion": "success",
        "path": WORKFLOW_PATH,
    }
    if any(run.get(key) != value for key, value in expected.items()):
        return "PR CI 尚未全部成功"
    entries = run_jobs(read, run_id)
    if len(entries) < 3:
        return "PR CI 任务数异常"
    for job in entries:
        conclusion = job.get("conclusion")
        if conclusion == "success":
            continue
        # PR 运行中复用任务本就不执行；只改前端时后端任务与演练按范围跳过。
        if conclusion == "skipped" and is_allowed_skip(str(job.get("name", ""))):
            continue
        return f"PR CI 任务「{job.get('name')}」结论为 {conclusion}"
    return None


def verified_pr_run(read: Reader, tree: str) -> int:
    """查找测试过同一代码指纹且全部成功的 PR 运行。"""
    artifacts = read(f"/actions/artifacts?name={EVIDENCE_PREFIX}{tree}&per_page=20")
    problems = []
    for artifact in artifacts.get("artifacts", []):
        run_id = int(artifact.get("workflow_run", {}).get("id") or 0)
        if not run_id or artifact.get("expired"):
            continue
        problem = pr_run_problem(read, run_id)
        if problem is None:
            return run_id
        problems.append(problem)
    raise EvidenceError(
        "没有测试过相同代码的成功 PR CI" + (f"：{problems[0]}" if problems else "")
    )


def commit_tree(read: Reader, revision: str) -> str:
    return str(read(f"/commits/{revision}")["commit"]["tree"]["sha"])


def main() -> int:
    parser = argparse.ArgumentParser(description="查找可复用的 PR CI 验证结果")
    parser.add_argument("--tree", required=True)
    parser.add_argument("--output", default=os.environ.get("GITHUB_OUTPUT"))
    arguments = parser.parse_args()
    read = api_reader(os.environ.get("GITHUB_TOKEN"))
    try:
        run_id = str(verified_pr_run(read, arguments.tree))
        print(f"复用 PR CI 运行 {run_id}，代码指纹 {arguments.tree}")
    except (EvidenceError, OSError, ValueError, KeyError) as error:
        # 查不到或 GitHub 接口异常时一律退回完整检查，不因复用失败而放行。
        run_id = ""
        print(f"{error}，执行完整检查")
    if arguments.output:
        with open(arguments.output, "a", encoding="utf-8") as output:
            output.write(f"pr_run={run_id}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
