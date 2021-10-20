import asyncio
import logging
import uuid
from enum import Enum

from kubernetes_asyncio.client.models.v1_deployment import V1Deployment

from runboat.build_images import get_build_image

from . import k8s
from .settings import settings
from .utils import slugify

_logger = logging.getLogger(__name__)


class BuildStatus(str, Enum):
    stopped = "stopped"
    starting = "starting"
    started = "started"


class BuildTodo(str, Enum):
    start = "start"


class Build:
    def __init__(self, deployment: V1Deployment):
        self._deployment = deployment

    @property
    def name(self) -> str:
        return self._deployment.metadata.labels["runboat/build"]

    @property
    def repo(self) -> str:
        return self._deployment.metadata.annotations["runboat/repo"]

    @property
    def target_branch(self) -> str:
        return self._deployment.metadata.annotations["runboat/target-branch"]

    @property
    def pr(self) -> int | None:
        return self._deployment.metadata.annotations["runboat/pr"] or None

    @property
    def commit(self) -> str:
        return self._deployment.metadata.annotations["runboat/commit"]

    @classmethod
    def make_slug(
        cls, repo: str, target_branch: str, pr: int | None, commit: str
    ) -> str:
        slug = f"{slugify(repo)}-{slugify(target_branch)}"
        if pr:
            slug = f"{slug}-pr{slugify(pr)}"
        slug = f"{slug}-{commit[:12]}"
        return slug

    @property
    def slug(self) -> str:
        return self.make_slug(self.repo, self.target_branch, self.pr, self.commit)

    @property
    def link(self) -> str:
        return f"https://{self.slug}.{settings.build_domain}"

    @property
    def status(self) -> BuildStatus:
        replicas = self._deployment.status.replicas
        if not replicas:
            status = BuildStatus.stopped
        else:
            if self._deployment.status.ready_replicas == replicas:
                status = BuildStatus.started
            else:
                status = BuildStatus.starting
        # TODO detect stopping, deploying, undeploying ?
        # TODO: failed status
        return status

    @property
    def todo(self) -> BuildTodo | None:
        return self._deployment.metadata.annotations["runboat/todo"] or None

    async def delay_start(self) -> None:
        """Mark a build for startup.

        This is done by setting the runboat/todo annotation to 'start'.
        This will in turn let the starter process it when there is
        available capacity.
        """
        await k8s.patch_deployment(
            self._deployment.metadata.name,
            [
                {
                    "op": "replace",
                    "path": "/metadata/annotations/runboat~1todo",
                    "value": "start",
                },
            ],
        )

    async def start(self) -> None:
        """Start a build.

        Set replicas to 1, and reset todo.
        """
        _logger.info(f"Starting {self.slug} ({self.name})")
        await k8s.patch_deployment(
            self._deployment.metadata.name,
            [
                {
                    "op": "replace",
                    "path": "/metadata/annotations/runboat~1todo",
                    "value": "",
                },
                {
                    "op": "replace",
                    "path": "/spec/replicas",
                    "value": 1,
                },
            ],
        )

    async def stop(self) -> None:
        """Stop a build.

        Set replicas to 0, and reset todo.
        """
        _logger.info(f"Stopping {self.slug} ({self.name})")
        await k8s.patch_deployment(
            self._deployment.metadata.name,
            [
                {
                    "op": "replace",
                    "path": "/metadata/annotations/runboat~1todo",
                    "value": "",
                },
                {
                    "op": "replace",
                    "path": "/spec/replicas",
                    "value": 0,
                },
            ],
        )

    async def undeploy(self) -> None:
        """Undeploy a build.

        Delete all resources, and drop the database.
        """
        _logger.info(f"Undeploying {self.slug} ({self.name})")
        await k8s.undeploy(self.name)
        await k8s.dropdb(self.name)

    @classmethod
    async def deploy(
        cls, repo: str, target_branch: str, pr: int | None, commit: str
    ) -> None:
        """Deploy a build, without starting it."""
        name = str(uuid.uuid4())
        slug = cls.make_slug(repo, target_branch, pr, commit)
        _logger.info("Deploying {slug} ({name})")
        image = get_build_image(target_branch)
        deployment_vars = k8s.make_deployment_vars(
            name,
            slug,
            repo.lower(),
            target_branch,
            pr,
            commit,
            image,
        )
        await k8s.deploy(deployment_vars)


class Controller:
    """The controller monitors and manages the deployments.

    It run several background tasks:
    - The 'watcher' listens to kubernetes events on deployements and maintains an
      in-memory data structure about existing deployments and their state. It wakes up
      the starter and the reaper when necessary.
    - The 'starter' starts deployment that have been flagged to start, while making sure
      that the maximum number of deployment starting concurrently does not exceed the
      limit.
    - The 'reaper' stops old running deployments, and deletes old stopped deployments so
      as to limit the maximum number of each.
    """

    _tasks: list[asyncio.Task]
    _wakeup_event: asyncio.Event
    _builds_by_name: dict[str, Build]
    _starting: int
    _started: int
    _starter_queue: asyncio.Queue

    def __init__(self):
        self._tasks = []
        self._wakeup_event = asyncio.Event()
        self.reset()

    def reset(self):
        self._builds_by_name = {}
        self._starting = 0
        self._started = 0
        self._starter_queue = asyncio.Queue()

    @property
    def running(self) -> int:
        return self._starting + self._started

    @property
    def starting(self) -> int:
        return self._starting

    @property
    def deployed(self) -> int:
        return len(self._builds_by_name)

    def _add(self, build: Build) -> None:
        self._remove(build.name)
        if build.status == BuildStatus.starting:
            self._starting += 1
        elif build.status == BuildStatus.started:
            self._started += 1
        self._builds_by_name[build.name] = build

    def _remove(self, build_name: str) -> None:
        old_build = self._builds_by_name.get(build_name)
        if old_build is None:
            return
        if old_build.status == BuildStatus.starting:
            self._starting -= 1
        elif old_build.status == BuildStatus.started:
            self._started -= 1
        del self._builds_by_name[build_name]

    def _wakeup(self) -> None:
        self._wakeup_event.set()
        self._wakeup_event.clear()

    def added(self, build_name: str, deployment: V1Deployment) -> None:
        new_build = Build(deployment)
        assert new_build.name == build_name
        assert new_build.name not in self._builds_by_name
        if new_build.todo == BuildTodo.start:
            self._starter_queue.put_nowait(new_build.name)
        self._add(new_build)
        self._wakeup()

    def modified(self, build_name: str, deployment: V1Deployment) -> None:
        new_build = Build(deployment)
        assert new_build.name == build_name
        assert new_build.name in self._builds_by_name
        old_build = self._builds_by_name[new_build.name]
        if new_build.todo == BuildTodo.start and new_build.todo != old_build.todo:
            self._starter_queue.put_nowait(new_build.name)
        self._add(new_build)
        self._wakeup()

    def deleted(self, build_name: str) -> None:
        self._remove(build_name)
        self._wakeup()

    async def watcher(self) -> None:
        async for event_type, deployment in k8s.watch_deployments():
            build_name = deployment.metadata.labels.get("runboat/build")
            if not build_name:
                continue
            _logger.debug(f"{event_type} deployment {build_name}")
            if event_type == "ADDED":
                self.added(build_name, deployment)
            elif event_type == "MODIFIED":
                self.modified(build_name, deployment)
            elif event_type == "DELETED":
                self.deleted(build_name)
            else:
                _logger.error(f"Unexpected event type {event_type}.")

    async def starter(self) -> None:
        while True:
            await self._wakeup_event.wait()
            while not self._starter_queue.empty():
                if self.starting >= settings.max_starting:
                    # Too many starting, back to sleep.
                    break
                if self.running > settings.max_running:
                    # Too many started, back to sleep. If ==, we are going to start one
                    # more and let the reaper do it's job to get back to the maximum.
                    break
                build_name = await self._starter_queue.get()
                try:
                    build = self._builds_by_name.get(build_name)
                    if build is None:
                        continue
                    await build.start()
                finally:
                    # TODO in case of exception, add back to starter queue ?
                    self._starter_queue.task_done()

    async def reaper(self) -> None:
        while True:
            await self._wakeup_event.wait()
            # TODO
            # - stop old started
            # - undeploy old deployed
            # - keep sticky builds

    async def start(self):
        _logger.info("Starting controller tasks.")

        async def walking_dead(func):
            while True:
                try:
                    await func()
                except Exception:
                    delay = 5
                    _logger.exception(
                        f"Unhandled exception in {func}, restarting in {delay} sec."
                    )
                    await asyncio.sleep(delay)

        for f in (self.watcher, self.starter, self.reaper):
            self._tasks.append(asyncio.create_task(walking_dead(f)))

    async def stop(self):
        _logger.info("Stopping controller tasks.")
        for task in self._tasks:
            task.cancel()
        # Wait until all tasks are cancelled.
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._task = []


controller = Controller()
