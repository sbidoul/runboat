from dataclasses import dataclass
from enum import Enum
from typing import Any

import httpx

from .exceptions import NotFoundOnGitHub
from .settings import settings


async def _github_request(method: str, url: str, json: Any = None) -> Any:
    async with httpx.AsyncClient() as client:
        full_url = f"https://api.github.com{url}"
        headers = {
            "Accept": "application/vnd.github.v3+json",
        }
        if settings.github_token:
            headers["Authorization"] = f"token {settings.github_token}"
        response = await client.request(method, full_url, headers=headers, json=json)
        if response.status_code == 404:
            raise NotFoundOnGitHub(f"GitHub URL not found: {full_url}.")
        response.raise_for_status()
        return response.json()


@dataclass
class BranchInfo:
    repo: str
    name: str
    head_sha: str


async def get_branch_info(repo: str, branch: str) -> BranchInfo:
    branch_data = await _github_request("GET", f"/repos/{repo}/git/ref/heads/{branch}")
    return BranchInfo(
        repo=repo,
        name=branch,
        head_sha=branch_data["object"]["sha"],
    )


@dataclass
class PullInfo:
    repo: str
    number: int
    head_sha: str
    target_branch: str


async def get_pull_info(repo: str, pr: int) -> PullInfo:
    pr_data = await _github_request("GET", f"/repos/{repo}/pulls/{pr}")
    return PullInfo(
        repo=repo,
        number=pr,
        head_sha=pr_data["head"]["sha"],
        target_branch=pr_data["base"]["ref"],
    )


class GitHubStatusState(str, Enum):
    error = "error"
    failure = "failure"
    pending = "pending"
    success = "success"


async def notify_status(
    repo: str, sha: str, state: GitHubStatusState, target_url: str | None
) -> None:
    # https://docs.github.com/en/rest/reference/repos#create-a-commit-status
    await _github_request(
        "POST",
        f"/repos/{repo}/statuses/{sha}",
        json={
            "state": state,
            "target_url": target_url,
            "context": "runboat/build",
        },
    )
