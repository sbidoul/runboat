import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from . import k8s
from .db import BuildsDb
from .github import CommitInfo
from .models import Build, BuildEvent, BuildInitStatus, BuildStatus
from .settings import settings

_logger = logging.getLogger(__name__)

# In some circumstances, on_build_event can be called very frequently (e.g. when the
# controller starts and discovers existing deployments). A small delay before the wakeup
# of the background tasks and the clearing of the wakeup avoids waking up the tasks
# too often.
EVENT_BUFFERING_DELAY = 1
# When an exception happens in background tasks, restart them after a delay.
WALKING_DEAD_RESTART_DELAY = 5


class Controller:
    """The controller monitors and manages the deployments.

    It runs several background tasks:

    - The 'deployment_watcher' listens to kubernetes events on deployments and maintains
      an in-memory database of existing deployments and their state. It wakes up the
      initializer, stopper and undeployer when the state of deployments change.
    - The 'job_watcher' listens to kubernetes events on jobs, to maintain the
      runboat/init-status annotation on deployments, and act on such events (such as
      changing the init-status when an initialization succeeded or failed or undeploying
      when a cleanup succeeded).
    - The 'initializer' starts initialization jobs for deployment that have been marked
      with 'runboat/init-status=todo', while making sure that the maximum number of
      deployments initializing concurrently does not exceed the limit.
    - The 'cleaner' starts cleanup jobs for deployment that have been marked for
      deletion.
    - The 'stopper' stops old running deployments.
    - The 'undeployer' undeploys old stopped deployments.
    """

    def __init__(self) -> None:
        self._tasks: list[asyncio.Task[None]] = []
        self._wakeup_initializer = asyncio.Event()
        self._wakeup_stopper = asyncio.Event()
        self._wakeup_undeployer = asyncio.Event()
        self._wakeup_cleaner = asyncio.Event()
        self.db = BuildsDb()
        self.db.register_listener(self)

    def on_build_event(self, event: BuildEvent, build: Build) -> None:
        self._wakeup_initializer.set()
        self._wakeup_stopper.set()
        self._wakeup_undeployer.set()
        self._wakeup_cleaner.set()

    @property
    def stopped(self) -> int:
        return self.db.count_by_status(BuildStatus.stopped)

    @property
    def failed(self) -> int:
        return self.db.count_by_status(BuildStatus.failed)

    @property
    def started(self) -> int:
        return self.db.count_by_status(BuildStatus.started)

    @property
    def max_started(self) -> int:
        return settings.max_started

    @property
    def to_initialize(self) -> int:
        return self.db.count_by_init_status(BuildInitStatus.todo)

    @property
    def initializing(self) -> int:
        return self.db.count_by_init_status(BuildInitStatus.started)

    @property
    def max_initializing(self) -> int:
        return settings.max_initializing

    @property
    def deployed(self) -> int:
        return self.db.count_deployed()

    @property
    def max_deployed(self) -> int:
        return settings.max_deployed

    @property
    def undeploying(self) -> int:
        return self.db.count_by_status(BuildStatus.undeploying)

    async def deploy_commit(self, commit_info: CommitInfo) -> None:
        """Deploy build for a commit, or do nothing if build already exist."""
        build = self.db.get_for_commit(
            repo=commit_info.repo,
            target_branch=commit_info.target_branch,
            pr=commit_info.pr,
            git_commit=commit_info.git_commit,
        )
        if build is None:
            await Build.deploy(commit_info)

    async def undeploy_builds(
        self,
        repo: str | None = None,
        target_branch: str | None = None,
        branch: str | None = None,
        pr: int | None = None,
    ) -> None:
        for build in self.db.search(
            repo=repo, target_branch=target_branch, branch=branch, pr=pr
        ):
            await build.undeploy()

    async def get_build(self, build_name: str, db_only: bool = True) -> Build | None:
        build = self.db.get(build_name)
        if build is not None:
            return build
        if not db_only:
            _logger.debug(
                "Build %s not in local db, fetching from k8s api.", build_name
            )
            build = await Build.from_name(build_name)
            if build is not None:
                self.db.add(build)
                return build
        return None

    async def deployment_watcher(self) -> None:
        self.db.reset()  # empty the local db each time we start watching
        async for event_type, deployment in k8s.watch_deployments():
            _logger.debug(
                "Event %s %s %s dr=%s/rr=%s",
                event_type,
                deployment.metadata.name,
                deployment.metadata.resource_version,
                deployment.spec.replicas,
                deployment.status.available_replicas,
            )
            build_name = deployment.metadata.labels.get("runboat/build")
            if not build_name:
                continue
            if event_type in (None, "ADDED", "MODIFIED"):
                build = Build.from_deployment(deployment)
                self.db.add(build)
            elif event_type == "DELETED":
                self.db.remove(build_name)

    async def job_watcher(self) -> None:
        async for event_type, job in k8s.watch_jobs():
            _logger.debug(
                "Event %s %s %s a=%s/s=%s/f=%s",
                event_type,
                job.metadata.name,
                job.metadata.resource_version,
                job.status.active,
                job.status.succeeded,
                job.status.failed,
            )
            build_name = job.metadata.labels.get("runboat/build")
            if not build_name:
                continue
            job_kind = job.metadata.labels.get("runboat/job-kind")
            if job_kind not in ("initialize", "cleanup"):
                continue
            if event_type in (None, "ADDED", "MODIFIED"):
                # Look for build in local db and also in k8s api.
                # This is necessary because job events may come before build events
                # have arrived.
                build = await self.get_build(build_name, db_only=False)
                if build is None:
                    _logger.warning(
                        f"Received job event for {job.metadata.name} "
                        f"of kind {job_kind} "
                        f"but the corresponding deployment {build_name} is gone. "
                        f"Deleting all build resources."
                    )
                    await k8s.delete_resources(build_name)
                    continue
                if job_kind == "initialize":
                    if job.status.active:
                        await build.on_initialize_started()
                    elif job.status.succeeded:
                        await build.on_initialize_succeeded()
                    elif job.status.failed:
                        await build.on_initialize_failed()
                if job_kind == "cleanup":
                    if job.status.active:
                        await build.on_cleanup_started()
                    elif job.status.succeeded:
                        await build.on_cleanup_succeeded()
                    elif job.status.failed:
                        await build.on_cleanup_failed()
            elif event_type == "DELETED":
                pass

    async def cleaner(self) -> None:
        while True:
            await self._wakeup_cleaner.wait()
            await asyncio.sleep(EVENT_BUFFERING_DELAY)
            self._wakeup_cleaner.clear()
            for build in self.db.to_cleanup():
                await build.cleanup()

    async def initializer(self) -> None:
        while True:
            await self._wakeup_initializer.wait()
            await asyncio.sleep(EVENT_BUFFERING_DELAY)
            self._wakeup_initializer.clear()
            can_initialize = self.max_initializing - self.initializing
            if can_initialize <= 0:
                continue  # no capacity for now, back to sleep
            to_initialize = self.db.to_initialize(limit=can_initialize)
            if not to_initialize:
                continue  # nothing to initialize, back to sleep
            _logger.info(
                f"{self.initializing} builds of max {self.max_initializing} "
                f"are initializing. Launching {len(to_initialize)} initialization jobs."
            )
            for build in to_initialize:
                await build.initialize()

    async def stopper(self) -> None:
        while True:
            await self._wakeup_stopper.wait()
            await asyncio.sleep(EVENT_BUFFERING_DELAY)
            self._wakeup_stopper.clear()
            can_stop = self.started - self.max_started
            if can_stop <= 0:
                continue  # no need to stop for now, back to sleep
            to_stop = self.db.oldest_started(limit=can_stop)
            if not to_stop:
                continue  # nothing stoppable, back to sleep
            _logger.info(
                f"{self.started} builds of max {self.max_started} are started. "
                f"Stopping {len(to_stop)}."
            )
            for build in to_stop:
                await build.stop()

    async def undeployer(self) -> None:
        while True:
            await self._wakeup_undeployer.wait()
            await asyncio.sleep(EVENT_BUFFERING_DELAY)
            self._wakeup_undeployer.clear()
            can_undeploy = self.deployed - self.max_deployed
            if can_undeploy <= 0:
                continue  # no need to undeploy for now, back to sleep
            to_undeploy = self.db.oldest_stopped(limit=can_undeploy)
            if not to_undeploy:
                continue  # nothing undeployable, back to sleep
            _logger.info(
                f"{self.deployed} builds of max {self.max_deployed} are deployed. "
                f"Undeploying {len(to_undeploy)}."
            )
            for build in to_undeploy:
                await build.undeploy()

    async def start(self) -> None:
        _logger.info("Starting controller tasks.")

        async def walking_dead(func: Callable[..., Awaitable[Any]]) -> None:
            while True:
                _logger.info(f"(Re)starting {func.__name__}")
                try:
                    await func()
                except k8s.WatchException as e:
                    _logger.info(
                        f"Watch error {e} in {func.__name__}, "
                        f"restarting in {WALKING_DEAD_RESTART_DELAY} sec."
                    )
                    await asyncio.sleep(WALKING_DEAD_RESTART_DELAY)
                except Exception:
                    _logger.exception(
                        f"Unhandled exception in {func.__name__}, "
                        f"restarting in {WALKING_DEAD_RESTART_DELAY} sec."
                    )
                    await asyncio.sleep(WALKING_DEAD_RESTART_DELAY)

        for f in (
            self.deployment_watcher,
            self.job_watcher,
            self.cleaner,
            self.initializer,
            self.stopper,
            self.undeployer,
        ):
            self._tasks.append(asyncio.create_task(walking_dead(f)))

    async def stop(self) -> None:
        _logger.info("Stopping controller tasks.")
        for task in self._tasks:
            task.cancel()
        # Wait until all tasks are cancelled.
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()


controller = Controller()
