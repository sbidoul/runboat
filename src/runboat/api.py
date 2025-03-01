import asyncio
import datetime
from collections.abc import AsyncGenerator

from ansi2html import Ansi2HTMLConverter
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict
from sse_starlette.sse import EventSourceResponse
from starlette.status import HTTP_404_NOT_FOUND

from . import github, models
from .controller import Controller, controller
from .db import SortOrder
from .deps import authenticated

router = APIRouter()


class Status(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    deployed: int
    max_deployed: int
    failed: int
    stopped: int
    started: int
    max_started: int
    to_initialize: int
    initializing: int
    max_initializing: int
    undeploying: int


class Repo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    link: str


class Build(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    commit_info: github.CommitInfo
    deploy_link: str
    deploy_link_mailhog: str
    repo_target_branch_link: str
    repo_pr_link: str | None
    repo_commit_link: str
    webui_link: str
    status: models.BuildStatus
    created: datetime.datetime
    last_scaled: datetime.datetime


class BuildEvent(BaseModel):
    event: models.BuildEvent
    build: Build


@router.get("/status", response_model=Status)
async def controller_status() -> Controller:
    return controller


@router.get("/repos", response_model=list[Repo])
async def repos() -> list[models.Repo]:
    return controller.db.repos()


@router.get(
    "/builds",
    response_model=list[Build],
    response_model_exclude_none=True,
)
async def builds(
    repo: str | None = None,
    target_branch: str | None = None,
    branch: str | None = None,
    pr: int | None = None,
    status: models.BuildStatus | None = None,
) -> list[models.Build]:
    return list(
        controller.db.search(
            repo=repo, target_branch=target_branch, branch=branch, pr=pr, status=status
        )
    )


@router.delete(
    "/builds",
    dependencies=[Depends(authenticated)],
)
async def undeploy_builds(
    repo: str | None = None,
    target_branch: str | None = None,
    branch: str | None = None,
    pr: int | None = None,
) -> None:
    await controller.undeploy_builds(repo, target_branch, branch, pr)


@router.post(
    "/builds/trigger/branch",
    dependencies=[Depends(authenticated)],
)
async def trigger_branch(repo: str, branch: str) -> None:
    """Trigger build for a branch."""
    commit_info = await github.get_branch_info(repo, branch)
    await controller.deploy_commit(commit_info)


@router.post(
    "/builds/trigger/pr",
    dependencies=[Depends(authenticated)],
)
async def trigger_pull(repo: str, pr: int) -> None:
    """Trigger build for a pull request."""
    commit_info = await github.get_pull_info(repo, pr)
    await controller.deploy_commit(commit_info)


async def _build_by_name(name: str) -> models.Build:
    build = await controller.get_build(name)
    if build is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return build


@router.get("/builds/{name}", response_model=Build)
async def build(name: str) -> models.Build:
    return await _build_by_name(name)


@router.get(
    "/builds/{name}/init-log",
    response_class=HTMLResponse,
)
async def init_log(name: str) -> str:
    build = await _build_by_name(name)
    log = await build.init_log()
    if not log:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="No log found.")
    return Ansi2HTMLConverter().convert(log)


@router.get(
    "/builds/{name}/log",
    response_class=HTMLResponse,
)
async def log(name: str) -> str:
    build = await _build_by_name(name)
    log = await build.log()
    if not log:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="No log found.")
    return Ansi2HTMLConverter().convert(log)


@router.post("/builds/{name}/start")
async def start_build(name: str) -> None:
    """Start the deployment."""
    build = await _build_by_name(name)
    await build.start()


@router.post("/builds/{name}/stop")
async def stop_build(name: str) -> None:
    """Stop the deployment."""
    build = await _build_by_name(name)
    await build.stop()


@router.post("/builds/{name}/reset")
async def reset_build(name: str) -> None:
    """Redeploy, so as to reinitialize."""
    build = await _build_by_name(name)
    await build.redeploy()


@router.delete("/builds/{name}", dependencies=[Depends(authenticated)])
async def undeploy_build(name: str) -> None:
    """Delete the deployment and drop the database."""
    build = await _build_by_name(name)
    await build.undeploy()


class BuildEventSource:
    def __init__(
        self,
        request: Request,
        repo: str | None = None,
        target_branch: str | None = None,
        branch: str | None = None,
        pr: int | None = None,
        build_name: str | None = None,
    ):
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.request = request
        self.repo = repo
        self.target_branch = target_branch
        self.branch = branch
        self.pr = pr
        self.build_name = build_name
        controller.db.register_listener(self)

    @classmethod
    def _serialize(cls, event: models.BuildEvent, build: models.Build) -> str:
        return BuildEvent(event=event, build=Build.from_orm(build)).json()

    def on_build_event(self, event: models.BuildEvent, build: models.Build) -> None:
        if self.repo and build.commit_info.repo != self.repo:
            return
        if self.target_branch and build.commit_info.target_branch != self.target_branch:
            return
        if self.branch and (
            build.commit_info.target_branch != self.branch or build.commit_info.pr
        ):
            return
        if self.pr and build.commit_info.pr != self.pr:
            return
        if self.build_name and build.name != self.build_name:
            return
        self.queue.put_nowait(self._serialize(event, build))

    async def events(self) -> AsyncGenerator[str]:
        for build in controller.db.search(
            repo=self.repo,
            target_branch=self.target_branch,
            branch=self.branch,
            pr=self.pr,
            name=self.build_name,
            sort=SortOrder.asc,
        ):
            yield self._serialize(models.BuildEvent.modified, build)
        while True:
            try:
                event = await asyncio.wait_for(self.queue.get(), timeout=10)
            except TimeoutError:
                pass
            else:
                yield event
            # Check if the client is still there and wait for events again.
            if await self.request.is_disconnected():
                break


@router.get("/build-events")
async def build_events(
    request: Request,
    repo: str | None = None,
    target_branch: str | None = None,
    branch: str | None = None,
    pr: int | None = None,
    build_name: str | None = None,
) -> EventSourceResponse:
    event_source = BuildEventSource(
        request, repo, target_branch, branch, pr, build_name
    )
    return EventSourceResponse(event_source.events())
