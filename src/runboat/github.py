from enum import Enum
from typing import Any

import httpx
from pydantic import BaseModel, validator

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


class CommitInfo(BaseModel):
    repo: str
    target_branch: str
    pr: int | None
    git_commit: str

    @validator("repo")
    def validate_repo(cls, v: str) -> str:
        return v.lower()


async def get_branch_info(repo: str, branch: str) -> CommitInfo:
    branch_data = await _github_request("GET", f"/repos/{repo}/git/ref/heads/{branch}")
    return CommitInfo(
        repo=repo,
        target_branch=branch,
        pr=None,
        git_commit=branch_data["object"]["sha"],
    )


async def get_pull_info(repo: str, pr: int) -> CommitInfo:
    pr_data = await _github_request("GET", f"/repos/{repo}/pulls/{pr}")
    return CommitInfo(
        repo=repo,
        target_branch=pr_data["base"]["ref"],
        pr=pr,
        git_commit=pr_data["head"]["sha"],
    )


class GitHubStatusState(str, Enum):
    error = "error"
    failure = "failure"
    pending = "pending"
    success = "success"


async def notify_status(
    repo: str, sha: str, state: GitHubStatusState, target_url: str | None
) -> None:
    if settings.disable_commit_statuses:
        return
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
