import asyncio
import datetime
from typing import AsyncGenerator, Optional

from ansi2html import Ansi2HTMLConverter
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from starlette.status import HTTP_404_NOT_FOUND

from . import github, models
from .controller import Controller, controller
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
    deploy_link: str
    repo_link: str
    repo_commit_link: str
    webui_link: str
    status: models.BuildStatus
    created: datetime.datetime
    last_scaled: Optional[datetime.datetime]

    class Config:
        orm_mode = True
        read_with_orm_mode = True


class BuildEvent(BaseModel):
    event: models.BuildEvent
    build: Build


@router.get("/status", response_model=Status)
async def controller_status() -> Controller:
    return controller


@router.get("/repos", response_model=list[Repo])
async def repos() -> list[models.Repo]:
    return [models.Repo(name=name) for name in settings.supported_repos]


@router.get(
    "/builds",
    response_model=list[Build],
    response_model_exclude_none=True,
)
async def builds(repo: Optional[str] = None) -> list[models.Build]:
    return list(controller.db.search(repo))


@router.post(
    "/builds/trigger/branch",
    dependencies=[Depends(authenticated)],
)
async def trigger_branch(repo: str, branch: str) -> None:
    """Trigger build for a branch."""
    branch_info = await github.get_branch_info(repo, branch)
    await controller.deploy_or_start(
        repo=branch_info.repo,
        target_branch=branch_info.name,
        pr=None,
        git_commit=branch_info.head_sha,
    )


@router.post(
    "/builds/trigger/pr",
    dependencies=[Depends(authenticated)],
)
async def trigger_pull(repo: str, pr: int) -> None:
    """Trigger build for a pull request."""
    pull_info = await github.get_pull_info(repo, pr)
    await controller.deploy_or_start(
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
    return Ansi2HTMLConverter().convert(log)  # type: ignore [no-any-return]


@router.get(
    "/builds/{name}/log",
    response_class=HTMLResponse,
)
async def log(name: str) -> str:
    build = await _build_by_name(name)
    log = await build.log()
    if not log:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="No log found.")
    return Ansi2HTMLConverter().convert(log)  # type: ignore [no-any-return]


@router.post("/builds/{name}/start")
async def start(name: str) -> None:
    """Start the deployment."""
    build = await _build_by_name(name)
    await build.start()


@router.post("/builds/{name}/stop")
async def stop(name: str) -> None:
    """Stop the deployment."""
    build = await _build_by_name(name)
    await build.stop()


@router.delete("/builds/{name}", dependencies=[Depends(authenticated)])
async def delete(name: str) -> None:
    """Delete the deployment and drop the database."""
    build = await _build_by_name(name)
    await build.undeploy()


class BuildEventSource:
    def __init__(
        self,
        request: Request,
        repo: str | None = None,
        target_branch: str | None = None,
        build_name: str | None = None,
    ):
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.request = request
        self.repo = repo
        self.target_branch = target_branch
        self.build_name = build_name
        controller.db.register_listener(self)

    @classmethod
    def _serialize(cls, event: models.BuildEvent, build: models.Build) -> str:
        return BuildEvent(event=event, build=Build.from_orm(build)).json()

    def on_build_event(self, event: models.BuildEvent, build: models.Build) -> None:
        if self.repo and build.repo != self.repo:
            return
        if self.target_branch and build.target_branch != self.target_branch:
            return
        if self.build_name and build.name != self.build_name:
            return
        self.queue.put_nowait(self._serialize(event, build))

    async def events(self) -> AsyncGenerator[str, None]:
        for build in controller.db.search(
            self.repo, self.target_branch, self.build_name
        ):
            yield self._serialize(models.BuildEvent.modified, build)
        while True:
            try:
                event = await asyncio.wait_for(self.queue.get(), timeout=10)
            except asyncio.TimeoutError:
                pass
            else:
                yield event
            # Check if the client is still there and wait for events again.
            if await self.request.is_disconnected():
                break


@router.get("/build-events")
async def eventsource_endpoint(
    request: Request,
    repo: Optional[str] = None,
    target_branch: Optional[str] = None,
    build_name: Optional[str] = None,
) -> EventSourceResponse:
    event_source = BuildEventSource(request, repo, target_branch, build_name)
    return EventSourceResponse(event_source.events())
