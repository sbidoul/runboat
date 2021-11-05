from dataclasses import dataclass
from typing import Any

import httpx

from .exceptions import NotFoundOnGitHub
from .settings import settings


async def _github_get(url: str) -> Any:
    async with httpx.AsyncClient() as client:
        full_url = f"https://api.github.com{url}"
        headers = {
            "Accept": "application/vnd.github.v3+json",
        }
        if settings.github_token:
            headers["Authorization"] = f"token {settings.github_token}"
        response = await client.get(full_url, headers=headers)
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
    branch_data = await _github_get(f"/repos/{repo}/git/ref/heads/{branch}")
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
    pr_data = await _github_get(f"/repos/{repo}/pulls/{pr}")
    return PullInfo(
        repo=repo,
        number=pr,
        head_sha=pr_data["head"]["sha"],
        target_branch=pr_data["base"]["ref"],
    )
