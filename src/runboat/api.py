import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import github, models
from .controller import controller
from .deps import authenticated
from .settings import settings

router = APIRouter()


class Status(BaseModel):
    deployed: int
    max_deployed: int
    started: int
    max_started: int
    to_initialize: int
    initializing: int
    max_initializing: int
    undeploying: int

    class Config:
        orm_mode = True
        read_with_orm_mode = True


class Repo(BaseModel):
    name: str
    link: str

    class Config:
        orm_mode = True
        read_with_orm_mode = True


class Build(BaseModel):
    name: str
    repo: str
    target_branch: str
    pr: Optional[int]
    git_commit: str
    image: str
    link: str
    status: models.BuildStatus
    created: datetime.datetime
    last_scaled: Optional[datetime.datetime]

    class Config:
        orm_mode = True
        read_with_orm_mode = True


@router.get("/status", response_model=Status)
async def controller_status():
    return controller


@router.get("/repos", response_model=list[Repo])
async def repos():
    return [models.Repo(name=name) for name in settings.supported_repos]


@router.get(
    "/builds",
    response_model=list[Build],
    response_model_exclude_none=True,
)
async def builds(repo: Optional[str] = None):
    return controller.db.search(repo)


@router.post(
    "/builds/trigger/branch",
    dependencies=[Depends(authenticated)],
)
async def trigger_branch(repo: str, branch: str):
    """Trigger build for a branch."""
    branch_info = await github.get_branch_info(repo, branch)
    await controller.deploy_or_delay_start(
        repo=branch_info.repo,
        target_branch=branch_info.name,
        pr=None,
        git_commit=branch_info.head_sha,
    )


@router.post(
    "/builds/trigger/pr",
    dependencies=[Depends(authenticated)],
)
async def trigger_pull(repo: str, pr: int):
    """Trigger build for a pull request."""
    pull_info = await github.get_pull_info(repo, pr)
    await controller.deploy_or_delay_start(
        repo=pull_info.repo,
        target_branch=pull_info.target_branch,
        pr=pull_info.number,
        git_commit=pull_info.head_sha,
    )


async def _build_by_name(name: str) -> models.Build:
    build = await controller.get_build(name)
    if build is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return build


@router.get("/builds/{name}", response_model=Build)
async def build(name: str):
    return await _build_by_name(name)


@router.get(
    "/builds/{name}/init-log",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/plain": {}}}},
)
async def init_log(name: str):
    # build = await _build_by_name(name)
    ...


@router.get(
    "/builds/{name}/log",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/plain": {}}}},
)
async def log(name: str):
    # build = _build_by_name(name)
    ...


@router.post("/builds/{name}/start")
async def start(name: str):
    """Start the deployment."""
    build = await _build_by_name(name)
    await build.start()


@router.post("/builds/{name}/stop")
async def stop(name: str):
    """Stop the deployment."""
    build = await _build_by_name(name)
    await build.stop()


@router.delete("/builds/{name}", dependencies=[Depends(authenticated)])
async def delete(name: str):
    """Delete the deployment and drop the database."""
    build = await _build_by_name(name)
    await build.undeploy()
