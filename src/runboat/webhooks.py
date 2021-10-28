import logging

from fastapi import APIRouter, BackgroundTasks, Header, Request

from . import controller
from .settings import settings

_logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/webhook/github")
async def receive_payload(
    background_tasks: BackgroundTasks,
    request: Request,
    x_github_event: str = Header(...),
):
    # TODO check x-hub-signature
    payload = await request.json()
    repo = payload["repository"]["full_name"]
    if not repo:
        return
    repo = repo.lower()
    if repo not in settings.supported_repos:
        _logger.info(f"Ignoring webhook delivery for unsupported repo {repo}.")
        return
    action = payload.get("action")
    if x_github_event == "pull_request":
        if action in ("opened", "synchronize"):
            background_tasks.add_task(
                controller.Build.deploy,
                repo=repo,
                target_branch=payload["pull_request"]["base"]["ref"],
                pr=payload["pull_request"]["number"],
                commit=payload["pull_request"]["head"]["sha"],
            )
    elif x_github_event == "push":
        background_tasks.add_task(
            controller.Build.deploy,
            repo=repo,
            target_branch=payload["ref"].split("/")[-1],
            pr=None,
            commit=payload["after"],
        )
