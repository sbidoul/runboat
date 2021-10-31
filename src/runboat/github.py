from dataclasses import dataclass
from typing import Any

import requests

from .exceptions import NotFoundOnGithub
from .settings import settings


def _github_get(url: str) -> Any:
    full_url = f"https://api.github.com{url}"
    # TODO github token
    headers = {
        "Accept": "application/vnd.github.v3+json",
    }
    if settings.github_token:
        headers["Authorization"] = f"token {settings.github_token}"
    response = requests.get(full_url, headers=headers)
    if response.status_code == 404:
        raise NotFoundOnGithub(f"GitHub URL not found: {full_url}.")
    response.raise_for_status()
    return response.json()


@dataclass
class BranchInfo:
    org: str
    repo: str
    name: str
    head_sha: str


def get_branch_info(org: str, repo: str, branch: str) -> BranchInfo:
    branch_data = _github_get(f"/repos/{org}/{repo}/git/ref/heads/{branch}")
    return BranchInfo(
        org=org,
        repo=repo,
        name=branch,
        head_sha=branch_data["object"]["sha"],
    )


@dataclass
class PullInfo:
    org: str
    repo: str
    number: int
    head_sha: str
    target_branch: str


def get_pull_info(org: str, repo: str, pr: int) -> PullInfo:
    pr_data = _github_get(f"/repos/{org}/{repo}/pulls/{pr}")
    return PullInfo(
        org=org,
        repo=repo,
        number=pr,
        head_sha=pr_data["head"]["sha"],
        target_branch=pr_data["base"]["ref"],
    )
