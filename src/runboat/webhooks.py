import logging

from fastapi import APIRouter, BackgroundTasks, Header, Request

from .controller import controller
from .github import CommitInfo
from .settings import settings

_logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/webhooks/github")
async def receive_payload(
    background_tasks: BackgroundTasks,
    request: Request,
    x_github_event: str = Header(...),
) -> None:
    # TODO check x-hub-signature
    payload = await request.json()
    if x_github_event == "pull_request":
        if payload["action"] in ("opened", "synchronize"):
            repo = payload["repository"]["full_name"]
            target_branch = payload["pull_request"]["base"]["ref"]
            if not settings.is_repo_and_branch_supported(repo, target_branch):
                _logger.debug(
                    "Ignoring %s payload for unsupported repo %s or target branch %s",
                    x_github_event,
                    repo,
                    target_branch,
                )
                return
            background_tasks.add_task(
                controller.deploy_commit,
                CommitInfo(
                    repo=repo,
                    target_branch=target_branch,
                    pr=payload["pull_request"]["number"],
                    git_commit=payload["pull_request"]["head"]["sha"],
                ),
            )
    elif x_github_event == "push":
        repo = payload["repository"]["full_name"]
        target_branch = payload["ref"].split("/")[-1]
        if not settings.is_repo_and_branch_supported(repo, target_branch):
            _logger.debug(
                "Ignoring %s payload for unsupported repo %s or target branch %s",
                x_github_event,
                repo,
                target_branch,
            )
            return
        background_tasks.add_task(
            controller.deploy_commit,
            CommitInfo(
                repo=repo,
                target_branch=target_branch,
                pr=None,
                git_commit=payload["after"],
            ),
        )
