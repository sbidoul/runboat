import datetime
from typing import List, Optional

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
    running: int
    max_running: int
    starting: int
    max_starting: int

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
    commit: str
    image: str
    link: str
    status: models.BuildStatus
    created: datetime.datetime
    last_scaled: Optional[datetime.datetime]

    class Config:
        orm_mode = True
        read_with_orm_mode = True


class BranchOrPull(BaseModel):
    repo: str
    target_branch: str
    pr: Optional[int]
    link: str
    builds: list[Build]

    class Config:
        orm_mode = True
        read_with_orm_mode = True


@router.get("/status", response_model=Status)
async def controller_status():
    return controller


@router.get("/repos", response_model=List[Repo])
async def repos():
    return [models.Repo(name=name) for name in settings.supported_repos]


@router.get(
    "/repos/{org}/{repo}/branches-and-pulls",
    response_model=List[BranchOrPull],
    response_model_exclude_none=True,
)
async def branches_and_pulls(org: str, repo: str):
    return controller.db.branches_and_pulls(f"{org}/{repo}")


@router.post(
    "/repos/{org}/{repo}/branches/{branch}/trigger",
    response_model=Build,
    dependencies=[Depends(authenticated)],
)
async def trigger_branch(org: str, repo: str, branch: str):
    """Trigger build for a branch."""
    # TODO async github call
    branch_info = github.get_branch_info(org, repo, branch)
    await models.Build.deploy(
        repo=f"{branch_info.org}/{branch_info.repo}",
        target_branch=branch_info.name,
        pr=None,
        commit=branch_info.head_sha,
    )


@router.post(
    "/repos/{org}/{repo}/pulls/{pr}/trigger",
    response_model=Build,
    dependencies=[Depends(authenticated)],
)
async def trigger_pull(org: str, repo: str, pr: int):
    """Trigger build for a pull request."""
    # TODO async github call
    pull_info = github.get_pull_info(org, repo, pr)
    await models.Build.deploy(
        repo=f"{pull_info.org}/{pull_info.repo}",
        target_branch=pull_info.target_branch,
        pr=pull_info.number,
        commit=pull_info.head_sha,
    )


def _build_by_name(name: str) -> models.Build:
    try:
        return controller.db.get(name)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND)


@router.get("/builds/{name}", response_model=Build)
async def build(name: str):
    return _build_by_name(name)


@router.get(
    "/builds/{name}/init-log",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/plain": {}}}},
)
async def init_log(name: str):
    # build = _build_by_name(name)
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
    build = _build_by_name(name)
    await build.delay_start()


@router.post("/builds/{name}/stop")
async def stop(name: str):
    """Stop the deployment."""
    build = _build_by_name(name)
    await build.scale(0)


@router.delete("/builds/{name}", dependencies=[Depends(authenticated)])
async def delete(name: str):
    """Delete the deployment and drop the database."""
    build = _build_by_name(name)
    await build.undeploy()
