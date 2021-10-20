from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import controller, github
from .deps import authenticated

router = APIRouter()


class Status(BaseModel):
    deployed: int
    running: int
    starting: int

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
    # created: datetime.datetime
    repo: str
    target_branch: str
    pr: Optional[int]
    commit: str
    image: str
    link: str
    status: controller.BuildStatus

    class Config:
        orm_mode = True
        read_with_orm_mode = True


class BranchOrPull(BaseModel):
    # created: datetime.datetime
    repo: str
    target_branch: str
    pr: Optional[int]
    link: str
    builds: List[Build]

    class Config:
        orm_mode = True


@router.get("/status", response_model=Status)
async def controller_status():
    return controller.controller


@router.get("/repos", response_model=List[Repo])
async def repos():
    # return models.Repo.all()
    ...


@router.get(
    "/repos/{org}/{repo}/branches-and-pulls",
    response_model=List[BranchOrPull],
    response_model_exclude_none=True,
)
async def branches_and_pulls(org: str, repo: str):
    # return await models.Repo.by_org_repo(org, repo).branches_and_pulls()
    ...


@router.post(
    "/repos/{org}/{repo}/branches/{branch}/trigger",
    response_model=Build,
    dependencies=[Depends(authenticated)],
)
async def trigger_branch(org: str, repo: str, branch: str):
    """Trigger build for a branch."""
    # TODO async github call
    branch_info = github.get_branch_info(org, repo, branch)
    controller.Build.deploy(
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
    await controller.Build.deploy(
        repo=f"{pull_info.org}/{pull_info.repo}",
        target_branch=pull_info.target_branch,
        pr=pull_info.number,
        commit=pull_info.head_sha,
    )


def _build_by_name(name: str) -> controller.Build:
    try:
        # TODO do not access controller internals
        return controller.controller._builds_by_name[name]
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
    await build.stop()


@router.delete("/builds/{name}", dependencies=[Depends(authenticated)])
async def delete(name: str):
    """Delete the deployment and drop the database."""
    build = _build_by_name(name)
    await build.undeploy()
