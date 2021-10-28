import asyncio
import logging

from . import k8s
from .db import BuildsDb
from .models import Build, BuildStatus
from .settings import settings

_logger = logging.getLogger(__name__)


class Controller:
    """The controller monitors and manages the deployments.

    It run several background tasks:
    - The 'watcher' listens to kubernetes events on deployements and maintains an
      in-memory database of existing deployments and their state. It wakes up the
      starter and the reaper when necessary.
    - The 'starter' starts deployment that have been flagged to start, while making sure
      that the maximum number of deployment starting concurrently does not exceed the
      limit.
    - The 'stopper' stops old running deployments.
    - The 'undeployer' undeploys old stopped deployments.
    """

    db: BuildsDb
    _tasks: list[asyncio.Task]
    _wakeup_event: asyncio.Event

    def __init__(self):
        self._tasks = []
        self._wakeup_event = asyncio.Event()
        self.reset()

    def reset(self):
        self.db = BuildsDb()

    @property
    def running(self) -> int:
        return self.db.count_by_statuses([BuildStatus.started, BuildStatus.starting])

    @property
    def starting(self) -> int:
        return self.db.count_by_statuses([BuildStatus.starting])

    @property
    def deployed(self) -> int:
        return self.db.count_all()

    def _wakeup(self) -> None:
        self._wakeup_event.set()
        self._wakeup_event.clear()

    async def watcher(self) -> None:
        self.reset()  # empty the local db each time we start watching
        async for event_type, deployment in k8s.watch_deployments():
            build_name = deployment.metadata.labels.get("runboat/build")
            if not build_name:
                continue
            _logger.debug(f"{event_type} deployment {build_name}")
            if event_type in ("ADDED", "MODIFIED"):
                self.db.add(Build.from_deployment(deployment))
            elif event_type == "DELETED":
                self.db.remove(build_name)
            else:
                _logger.error(f"Unexpected k8s event type {event_type}.")
            self._wakeup()

    async def starter(self) -> None:
        while True:
            await self._wakeup_event.wait()
            while True:
                can_start = max(
                    settings.max_running - self.running,
                    settings.max_starting - self.starting,
                )
                if can_start <= 0:
                    break
                for build in self.db.to_start(limit=can_start):
                    await build.scale(1)

    async def stopper(self) -> None:
        while True:
            await self._wakeup_event.wait()
            while True:
                can_stop = self.running - settings.max_running
                if can_stop <= 0:
                    break
                for build in self.db.oldest_started(limit=can_stop):
                    await build.scale(0)

    async def undeployer(self) -> None:
        while True:
            await self._wakeup_event.wait()
            while True:
                can_undeploy = self.deployed - settings.max_deployed
                if can_undeploy <= 0:
                    break
                for build in self.db.oldest_stopped(limit=can_undeploy):
                    await build.undeploy()

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

        for f in (self.watcher, self.starter, self.stopper, self.undeployer):
            self._tasks.append(asyncio.create_task(walking_dead(f)))

    async def stop(self):
        _logger.info("Stopping controller tasks.")
        for task in self._tasks:
            task.cancel()
        # Wait until all tasks are cancelled.
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._task = []


controller = Controller()
