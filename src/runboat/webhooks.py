from fastapi import APIRouter, BackgroundTasks, Header, Request

from .controller import controller
from .github import CommitInfo

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
            background_tasks.add_task(
                controller.deploy_or_start,
                CommitInfo(
                    repo=payload["repository"]["full_name"],
                    target_branch=payload["pull_request"]["base"]["ref"],
                    pr=payload["pull_request"]["number"],
                    git_commit=payload["pull_request"]["head"]["sha"],
                ),
            )
    elif x_github_event == "push":
        background_tasks.add_task(
            controller.deploy_or_start,
            CommitInfo(
                repo=payload["repository"]["full_name"],
                target_branch=payload["ref"].split("/")[-1],
                pr=None,
                git_commit=payload["after"],
            ),
        )
