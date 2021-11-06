import logging

from fastapi import APIRouter, BackgroundTasks, Header, Request

from runboat.build_images import is_branch_supported, is_main_branch

from .controller import controller
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
    repo = payload["repository"]["full_name"]
    if not repo:
        return
    repo = repo.lower()
    if repo not in settings.supported_repos:
        _logger.debug(f"Ignoring webhook delivery for unsupported repo {repo}.")
        return
    action = payload.get("action")
    if x_github_event == "pull_request":
        if action in ("opened", "synchronize"):
            target_branch = payload["pull_request"]["base"]["ref"]
            if not is_branch_supported(target_branch):
                _logger.debug(
                    f"Ignoring webhook delivery for pull request "
                    f"to unsupported branch {target_branch}"
                )
                return
            background_tasks.add_task(
                controller.deploy_or_start,
                repo=repo,
                target_branch=target_branch,
                pr=payload["pull_request"]["number"],
                git_commit=payload["pull_request"]["head"]["sha"],
            )
    elif x_github_event == "push":
        target_branch = payload["ref"].split("/")[-1]
        if not is_branch_supported(target_branch):
            _logger.debug(
                f"Ignoring webhook delivery for push "
                f"to unsupported branch {target_branch}"
            )
            return
        if not is_main_branch(target_branch):
            _logger.debug(
                f"Ignoring webhook delivery for push "
                f"to non-main branch {target_branch}"
            )
            return
        background_tasks.add_task(
            controller.deploy_or_start,
            repo=repo,
            target_branch=target_branch,
            pr=None,
            git_commit=payload["after"],
        )
